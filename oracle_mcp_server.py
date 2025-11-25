#!/usr/bin/env python3
"""
Oracle MCP Server using JDBC via subprocess.
Works through StrongDM proxy on Apple Silicon.
"""

import asyncio
import hashlib
import json
import logging
import re
import secrets
import time
from collections import deque
from typing import Any, Optional
from mcp.server import Server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)
from oracle_jdbc import OracleJDBC
from query_validator import QueryValidator, ValidationResult

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oracle-mcp-server")

# Create MCP server
server = Server("oracle-jdbc-server")

# Global database connection and validator
db: OracleJDBC = None
validator: QueryValidator = None


class RateLimiter:
    """Simple rate limiter to prevent DoS attacks."""

    def __init__(self, max_requests: int = 60, time_window: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()

    def is_allowed(self) -> tuple[bool, str]:
        """
        Check if a request is allowed.

        Returns:
            Tuple of (allowed, error_message)
        """
        now = time.time()

        # Remove old requests outside the time window
        while self.requests and self.requests[0] < now - self.time_window:
            self.requests.popleft()

        # Check if limit exceeded
        if len(self.requests) >= self.max_requests:
            return False, f"Rate limit exceeded: {self.max_requests} requests per {self.time_window} seconds"

        # Record this request
        self.requests.append(now)
        return True, ""


# Global rate limiter
rate_limiter = RateLimiter(max_requests=60, time_window=60)


class QueryApprovalTracker:
    """
    Tracks query approvals to enforce the approval workflow.
    Ensures queries are previewed and explicitly approved before execution.
    """

    def __init__(self, token_expiry: int = 300):
        """
        Initialize query approval tracker.

        Args:
            token_expiry: Token expiry time in seconds (default: 5 minutes)
        """
        self.token_expiry = token_expiry
        self.approvals = {}  # {token: {query_hash, timestamp, query_preview}}
        self.lock = asyncio.Lock()

    def _hash_query(self, query: str) -> str:
        """
        Generate hash of query for approval tracking.

        Args:
            query: SQL query

        Returns:
            SHA256 hash of normalized query
        """
        # Normalize query (strip whitespace, lowercase) for consistent hashing
        normalized = ' '.join(query.strip().lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    async def generate_approval_token(self, query: str) -> str:
        """
        Generate approval token for a query.

        Args:
            query: SQL query that needs approval

        Returns:
            Approval token (32-character hex string)
        """
        async with self.lock:
            # Generate secure random token
            token = secrets.token_hex(16)  # 32 character hex string

            # Store approval with metadata
            self.approvals[token] = {
                'query_hash': self._hash_query(query),
                'timestamp': time.time(),
                'query_preview': query[:100]  # Store preview for logging
            }

            # Clean up expired tokens
            self._cleanup_expired()

            logger.info(f"[APPROVAL] Generated token for query: {query[:50]}...")
            return token

    async def verify_approval(self, query: str, token: str) -> tuple[bool, str]:
        """
        Verify that query has been approved with valid token.

        Args:
            query: SQL query to execute
            token: Approval token from preview_query

        Returns:
            Tuple of (is_approved, error_message)
        """
        async with self.lock:
            # Clean up expired tokens first
            self._cleanup_expired()

            if not token:
                return False, "No approval token provided. You must call preview_query first and include the approval_token in your query_oracle call."

            # Check if token exists
            if token not in self.approvals:
                return False, "Invalid or expired approval token. Please call preview_query again to get a new approval token."

            approval_data = self.approvals[token]
            query_hash = self._hash_query(query)

            # Verify query matches the approved query
            if query_hash != approval_data['query_hash']:
                logger.warning(f"[APPROVAL] Query hash mismatch for token {token}")
                return False, "Query does not match approved query. The query you're trying to execute is different from the one you previewed."

            # Token is valid - consume it (one-time use)
            del self.approvals[token]

            logger.info(f"[APPROVAL] Token verified and consumed for query: {query[:50]}...")
            return True, ""

    def _cleanup_expired(self):
        """Remove expired approval tokens."""
        now = time.time()
        expired = [
            token for token, data in self.approvals.items()
            if now - data['timestamp'] > self.token_expiry
        ]

        for token in expired:
            logger.info(f"[APPROVAL] Token expired: {token}")
            del self.approvals[token]

    def get_pending_approvals(self) -> int:
        """Get count of pending approvals."""
        self._cleanup_expired()
        return len(self.approvals)


# Global approval tracker
approval_tracker = QueryApprovalTracker(token_expiry=300)  # 5 minute expiry


class CircuitBreaker:
    """
    Circuit breaker pattern to prevent hammering a failing database.
    States: CLOSED (normal), OPEN (failing), HALF_OPEN (testing recovery)
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60, success_threshold: int = 2):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures to open circuit
            recovery_timeout: Seconds to wait before attempting recovery
            success_threshold: Number of consecutive successes to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        # Circuit state
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        """
        Execute function through circuit breaker.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            RuntimeError: If circuit is open
        """
        async with self.lock:
            # Check circuit state
            if self.state == "OPEN":
                # Check if recovery timeout has elapsed
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    logger.info("[CIRCUIT_BREAKER] Entering HALF_OPEN state for recovery attempt")
                    self.state = "HALF_OPEN"
                    self.success_count = 0
                else:
                    # Circuit is open, reject request
                    remaining = int(self.recovery_timeout - (time.time() - self.last_failure_time))
                    logger.warning(f"[CIRCUIT_BREAKER] Circuit OPEN - rejecting request. Retry in {remaining}s")
                    raise RuntimeError(f"Circuit breaker is OPEN. Database appears to be down. Retry in {remaining} seconds.")

        # Execute function
        try:
            result = func(*args, **kwargs) if not asyncio.iscoroutinefunction(func) else await func(*args, **kwargs)

            # Success - update circuit state
            async with self.lock:
                self.failure_count = 0

                if self.state == "HALF_OPEN":
                    self.success_count += 1
                    if self.success_count >= self.success_threshold:
                        logger.info(f"[CIRCUIT_BREAKER] Circuit CLOSED - database recovered after {self.success_count} successes")
                        self.state = "CLOSED"
                        self.success_count = 0

            return result

        except Exception as e:
            # Failure - update circuit state
            async with self.lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                self.success_count = 0

                if self.state == "HALF_OPEN":
                    # Recovery attempt failed
                    logger.warning("[CIRCUIT_BREAKER] Recovery attempt failed - returning to OPEN state")
                    self.state = "OPEN"
                elif self.failure_count >= self.failure_threshold:
                    # Threshold exceeded
                    logger.error(f"[CIRCUIT_BREAKER] Circuit OPEN - {self.failure_count} consecutive failures")
                    self.state = "OPEN"

            raise

    def get_state(self) -> dict:
        """Get current circuit breaker state."""
        return {
            'state': self.state,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'last_failure_time': self.last_failure_time
        }


# Global circuit breaker
circuit_breaker = CircuitBreaker(
    failure_threshold=5,     # Open after 5 consecutive failures
    recovery_timeout=60,     # Wait 60 seconds before testing recovery
    success_threshold=2      # Close after 2 consecutive successes
)


def validate_identifier(identifier: str, max_length: int = 30) -> bool:
    """
    Validate database identifier (table name, schema name, etc.).

    Args:
        identifier: The identifier to validate
        max_length: Maximum allowed length

    Returns:
        True if valid, False otherwise
    """
    if not identifier:
        return False

    # Oracle identifier rules:
    # - Must start with letter
    # - Can contain letters, numbers, underscore, $, #
    # - Max 30 chars (or 128 in 12.2+, but we use 30 for safety)
    # - Case insensitive (we'll uppercase)
    if len(identifier) > max_length:
        return False

    # Allow only safe characters: alphanumeric, underscore
    # Block any SQL injection characters
    if not re.match(r'^[A-Za-z][A-Za-z0-9_$#]*$', identifier):
        return False

    return True


def init_db():
    """Initialize database connection and query validator."""
    global db, validator
    if db is None:
        import os
        db = OracleJDBC(
            host=os.getenv("ORACLE_HOST", "127.0.0.1"),
            port=int(os.getenv("ORACLE_PORT", "10006")),
            service_name=os.getenv("ORACLE_SERVICE_NAME", "ylvoprd"),
            user=os.getenv("ORACLE_USER", "username"),
            password=os.getenv("ORACLE_PASSWORD", "password")
        )
        logger.info("Database connection initialized")

    if validator is None:
        validator = QueryValidator(
            max_complexity=50,      # Maximum complexity score
            max_rows=10000,         # Maximum result rows
            allow_cross_joins=False # Block cartesian products
        )
        logger.info("Query validator initialized")


@server.list_resources()
async def list_resources() -> list[Resource]:
    """List available database resources."""
    return [
        Resource(
            uri="oracle://connection",
            name="Oracle Connection Status",
            mimeType="text/plain",
            description="Check Oracle database connection status"
        ),
        Resource(
            uri="oracle://info",
            name="Database Information",
            mimeType="application/json",
            description="Get Oracle database version and connection info"
        )
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read database resource."""
    init_db()

    if uri == "oracle://connection":
        if db.test_connection():
            return "✅ Oracle database connection is active"
        else:
            return "❌ Oracle database connection is down"

    elif uri == "oracle://info":
        try:
            version = db.query_one("""
                SELECT
                    banner as version,
                    USER as current_user,
                    SYS_CONTEXT('USERENV', 'DB_NAME') as db_name,
                    SYS_CONTEXT('USERENV', 'HOST') as host
                FROM v$version
                WHERE banner LIKE 'Oracle%'
            """)
            return json.dumps(version, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    else:
        raise ValueError(f"Unknown resource URI: {uri}")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available database tools."""
    return [
        Tool(
            name="preview_query",
            description="""Preview and validate SQL query WITHOUT executing it.

**USE THIS FIRST** before query_oracle to show the user:
- The query that will be executed
- Complexity score (0-50, lower is simpler)
- Any validation warnings or errors
- Whether the query is safe to execute

Returns validation results only. Does NOT execute the query.

**REQUIRED WORKFLOW:**
1. Call preview_query first
2. Show results to user with complexity score
3. Get explicit user confirmation
4. Only then call query_oracle to execute

Example: preview_query with "SELECT * FROM users WHERE id = 123" """,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL query to preview and validate"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="query_oracle",
            description="""Execute SQL query on Oracle database.

**CRITICAL: APPROVAL WORKFLOW REQUIRED**
1. Call preview_query FIRST to get validation results and approval_token
2. Review complexity score, warnings, and query details
3. Get explicit user confirmation
4. Call this tool with BOTH the query AND the approval_token

**SAFETY FEATURES:**
- Enforces approval workflow (preview → approve → execute)
- Blocks all write operations (INSERT/UPDATE/DELETE/DROP)
- Prevents cartesian products and cross joins
- Enforces maximum result size (10,000 rows)
- Validates query complexity
- Requires WHERE clauses on multi-table queries
- Connection pool limited to 2 max connections

Example usage:
1. preview = preview_query(query="SELECT * FROM users WHERE id = 123")
2. Get user approval and extract approval_token from preview response
3. result = query_oracle(query="SELECT * FROM users WHERE id = 123", approval_token="<token>")

Note: Approval tokens expire after 5 minutes and are single-use.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL query to execute (must match the query previewed)"
                    },
                    "approval_token": {
                        "type": "string",
                        "description": "Approval token received from preview_query (required for execution)"
                    }
                },
                "required": ["query", "approval_token"]
            }
        ),
        Tool(
            name="describe_table",
            description="""Get table structure and column information.

Returns column names, data types, nullable status, and primary keys.

Example:
- table_name: "USERS"
- table_name: "ORDERS"

Note: Table names are case-sensitive (typically uppercase in Oracle).""",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Name of the table to describe (case-sensitive)"
                    }
                },
                "required": ["table_name"]
            }
        ),
        Tool(
            name="list_tables",
            description="""List all accessible tables in the database.

Returns table names with optional schema filter.

Example:
- schema: "SYSTEM" (optional)
- schema: null (lists tables in current user's schema)

Note: Returns only tables accessible by current user.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema": {
                        "type": "string",
                        "description": "Schema name to filter tables (optional)"
                    }
                }
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Execute database tool."""
    init_db()

    try:
        if name == "preview_query":
            query = arguments.get("query")
            if not query:
                return [TextContent(
                    type="text",
                    text="Error: 'query' parameter is required"
                )]

            # Validate query for safety
            validation = validator.validate(query)

            # Determine if row limit would be applied
            safe_query = validator.wrap_with_row_limit(query)
            row_limit_applied = safe_query != query

            # Generate approval token
            approval_token = await approval_tracker.generate_approval_token(query)

            # Build preview response
            preview_response = {
                "preview_mode": True,
                "query_to_execute": query,
                "safe_query_with_limit": safe_query if row_limit_applied else None,
                "validation": {
                    "is_safe": validation.is_safe,
                    "complexity_score": validation.complexity_score,
                    "max_complexity": validator.max_complexity,
                    "complexity_explanation": "Lower is simpler. Score based on: JOINs (+5 each), subqueries (+10 each), GROUP BY (+2), aggregates (+3 each)",
                    "warnings": validation.warnings if validation.warnings else [],
                    "error_message": validation.error_message if not validation.is_safe else None
                },
                "safety_limits": {
                    "max_rows": validator.max_rows,
                    "row_limit_will_be_applied": row_limit_applied,
                    "allow_cross_joins": validator.allow_cross_joins
                },
                "approval": {
                    "token": approval_token,
                    "expires_in_seconds": 300,
                    "message": "Include this approval_token when calling query_oracle to execute the query"
                },
                "next_steps": "If query is safe and you approve, call query_oracle with the same query AND the approval_token to execute it."
            }

            logger.info(f"Query preview - Complexity: {validation.complexity_score}, Safe: {validation.is_safe}, Token: {approval_token}")

            return [TextContent(
                type="text",
                text=json.dumps(preview_response, indent=2)
            )]

        elif name == "query_oracle":
            query = arguments.get("query")
            approval_token = arguments.get("approval_token")

            if not query:
                return [TextContent(
                    type="text",
                    text="Error: 'query' parameter is required"
                )]

            # CRITICAL: Verify approval token
            is_approved, approval_error = await approval_tracker.verify_approval(query, approval_token)
            if not is_approved:
                logger.warning(f"[AUDIT] APPROVAL_DENIED | Query: {query[:50]}... | Reason: {approval_error}")
                return [TextContent(
                    type="text",
                    text=f"Error: {approval_error}"
                )]

            # SECURITY: Rate limiting check
            allowed, rate_limit_error = rate_limiter.is_allowed()
            if not allowed:
                # AUDIT LOG: Rate limit exceeded
                logger.warning(f"[AUDIT] RATE_LIMIT_EXCEEDED | {rate_limit_error}")
                return [TextContent(
                    type="text",
                    text=f"Error: {rate_limit_error}. Please wait before retrying."
                )]

            # AUDIT LOG: Query attempt (approved)
            logger.info(f"[AUDIT] Operation: query_oracle | APPROVED | Query length: {len(query)} chars")
            logger.info(f"[AUDIT] Query preview: {query[:150]}...")

            # Validate query for safety
            validation = validator.validate(query)

            if not validation.is_safe:
                # AUDIT LOG: Query blocked
                logger.warning(f"[AUDIT] BLOCKED | Reason: {validation.error_message} | Complexity: {validation.complexity_score}")
                logger.warning(f"[AUDIT] Blocked query: {query}")

                error_response = {
                    "success": False,
                    "error": validation.error_message,
                    "complexity_score": validation.complexity_score,
                    "warnings": validation.warnings
                }
                return [TextContent(
                    type="text",
                    text=json.dumps(error_response, indent=2)
                )]

            # Log warnings if any
            if validation.warnings:
                for warning in validation.warnings:
                    logger.info(f"Query warning: {warning}")

            # Wrap query with row limit for safety
            safe_query = validator.wrap_with_row_limit(query)

            if safe_query != query:
                logger.info(f"Query wrapped with row limit: {validator.max_rows}")

            # Execute query through circuit breaker
            try:
                result = await circuit_breaker.call(db.execute, safe_query)
            except RuntimeError as e:
                # Circuit breaker is open
                logger.error(f"[AUDIT] CIRCUIT_BREAKER_OPEN | {str(e)}")
                return [TextContent(
                    type="text",
                    text=f"Error: {str(e)}"
                )]

            if result.get('success'):
                # Format response
                rows = result.get('rows', [])
                count = result.get('count', 0)

                # AUDIT LOG: Successful execution
                logger.info(f"[AUDIT] SUCCESS | Rows returned: {count} | Complexity: {validation.complexity_score} | Row limit applied: {safe_query != query}")

                response = {
                    "success": True,
                    "row_count": count,
                    "rows": rows,
                    "validation": {
                        "complexity_score": validation.complexity_score,
                        "warnings": validation.warnings if validation.warnings else [],
                        "row_limit_applied": validator.max_rows if safe_query != query else None
                    }
                }

                return [TextContent(
                    type="text",
                    text=json.dumps(response, indent=2, default=str)
                )]
            else:
                error = result.get('error', 'Unknown error')
                # AUDIT LOG: Execution failed
                logger.error(f"[AUDIT] FAILED | Error: {error}")
                return [TextContent(
                    type="text",
                    text=f"Error executing query: {error}"
                )]

        elif name == "describe_table":
            table_name = arguments.get("table_name")
            if not table_name:
                return [TextContent(
                    type="text",
                    text="Error: 'table_name' parameter is required"
                )]

            # AUDIT LOG: describe_table attempt
            logger.info(f"[AUDIT] Operation: describe_table | Table: {table_name}")

            # Validate table name to prevent SQL injection
            if not validate_identifier(table_name):
                # AUDIT LOG: Invalid table name
                logger.warning(f"[AUDIT] BLOCKED | Invalid table name: {table_name}")
                return [TextContent(
                    type="text",
                    text=f"Error: Invalid table name '{table_name}'. Table names must start with a letter and contain only alphanumeric characters, underscores, $, or #."
                )]

            # Use uppercase for Oracle (case-insensitive but stored as uppercase)
            safe_table_name = table_name.upper()

            # Get table structure - using bind variables would be ideal but Oracle system tables
            # don't support them, so we use validated identifiers instead
            query = f"""
                SELECT
                    column_name,
                    data_type,
                    data_length,
                    nullable,
                    data_default
                FROM user_tab_columns
                WHERE table_name = '{safe_table_name}'
                ORDER BY column_id
            """

            try:
                columns = await circuit_breaker.call(db.query, query)
            except RuntimeError as e:
                logger.error(f"[AUDIT] CIRCUIT_BREAKER_OPEN | describe_table: {safe_table_name}")
                return [TextContent(
                    type="text",
                    text=f"Error: {str(e)}"
                )]

            # Get primary key info
            pk_query = f"""
                SELECT column_name
                FROM user_cons_columns
                WHERE constraint_name = (
                    SELECT constraint_name
                    FROM user_constraints
                    WHERE table_name = '{safe_table_name}'
                    AND constraint_type = 'P'
                )
            """

            try:
                pk_result = await circuit_breaker.call(db.query, pk_query)
                pk_columns = [row['COLUMN_NAME'] for row in pk_result]
            except RuntimeError as e:
                logger.error(f"[AUDIT] CIRCUIT_BREAKER_OPEN | get primary keys: {safe_table_name}")
                pk_columns = []  # Continue without PK info if circuit is open

            # AUDIT LOG: Successful describe_table
            logger.info(f"[AUDIT] SUCCESS | describe_table: {safe_table_name} | Columns: {len(columns)} | PKs: {len(pk_columns)}")

            response = {
                "table_name": safe_table_name,
                "columns": columns,
                "primary_keys": pk_columns
            }

            return [TextContent(
                type="text",
                text=json.dumps(response, indent=2, default=str)
            )]

        elif name == "list_tables":
            schema = arguments.get("schema")

            # AUDIT LOG: list_tables attempt
            logger.info(f"[AUDIT] Operation: list_tables | Schema: {schema if schema else 'current_user'}")

            if schema:
                # Validate schema name to prevent SQL injection
                if not validate_identifier(schema):
                    # AUDIT LOG: Invalid schema name
                    logger.warning(f"[AUDIT] BLOCKED | Invalid schema name: {schema}")
                    return [TextContent(
                        type="text",
                        text=f"Error: Invalid schema name '{schema}'. Schema names must start with a letter and contain only alphanumeric characters, underscores, $, or #."
                    )]

                safe_schema = schema.upper()
                query = f"""
                    SELECT table_name, owner
                    FROM all_tables
                    WHERE owner = '{safe_schema}'
                    ORDER BY table_name
                """
            else:
                query = """
                    SELECT table_name, 'USER' as owner
                    FROM user_tables
                    ORDER BY table_name
                """

            try:
                tables = await circuit_breaker.call(db.query, query)
            except RuntimeError as e:
                logger.error(f"[AUDIT] CIRCUIT_BREAKER_OPEN | list_tables: {schema if schema else 'current_user'}")
                return [TextContent(
                    type="text",
                    text=f"Error: {str(e)}"
                )]

            # AUDIT LOG: Successful list_tables
            logger.info(f"[AUDIT] SUCCESS | list_tables | Schema: {schema.upper() if schema else 'current_user'} | Tables found: {len(tables)}")

            response = {
                "schema": schema.upper() if schema else "current_user",
                "table_count": len(tables),
                "tables": tables
            }

            return [TextContent(
                type="text",
                text=json.dumps(response, indent=2, default=str)
            )]

        else:
            return [TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]

    except Exception as e:
        logger.error(f"Error in tool {name}: {e}", exc_info=True)
        return [TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]


async def main():
    """Run the MCP server."""
    logger.info("Starting Oracle JDBC MCP Server")

    # Initialize database connection
    try:
        init_db()
        if db.test_connection():
            logger.info("✅ Database connection established")
        else:
            logger.error("❌ Database connection failed")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    # Run server
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
