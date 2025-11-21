#!/usr/bin/env python3
"""
Oracle MCP Server using JDBC via subprocess.
Works through StrongDM proxy on Apple Silicon.
"""

import asyncio
import json
import logging
from typing import Any
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
            name="query_oracle",
            description="""Execute SQL query on Oracle database.

Returns rows as JSON array. Use for SELECT queries.

**SAFETY FEATURES:**
- Blocks all write operations (INSERT/UPDATE/DELETE/DROP)
- Prevents cartesian products and cross joins
- Enforces maximum result size (10,000 rows)
- Validates query complexity
- Requires WHERE clauses on multi-table queries

Example queries:
- SELECT * FROM users WHERE id = 123
- SELECT COUNT(*) as total FROM orders
- SELECT SYSDATE FROM DUAL

Note: Query results are returned as list of dictionaries.
Column names are uppercase. Validation warnings included in response.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL query to execute (SELECT statements only)"
                    }
                },
                "required": ["query"]
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
        if name == "query_oracle":
            query = arguments.get("query")
            if not query:
                return [TextContent(
                    type="text",
                    text="Error: 'query' parameter is required"
                )]

            # Validate query for safety
            validation = validator.validate(query)

            if not validation.is_safe:
                error_response = {
                    "success": False,
                    "error": validation.error_message,
                    "complexity_score": validation.complexity_score,
                    "warnings": validation.warnings
                }
                logger.warning(f"Query blocked: {validation.error_message}")
                logger.warning(f"Query: {query[:100]}...")
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

            # Execute query
            result = db.execute(safe_query)

            if result.get('success'):
                # Format response
                rows = result.get('rows', [])
                count = result.get('count', 0)

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

            # Get table structure
            query = f"""
                SELECT
                    column_name,
                    data_type,
                    data_length,
                    nullable,
                    data_default
                FROM user_tab_columns
                WHERE table_name = '{table_name.upper()}'
                ORDER BY column_id
            """

            columns = db.query(query)

            # Get primary key info
            pk_query = f"""
                SELECT column_name
                FROM user_cons_columns
                WHERE constraint_name = (
                    SELECT constraint_name
                    FROM user_constraints
                    WHERE table_name = '{table_name.upper()}'
                    AND constraint_type = 'P'
                )
            """

            pk_columns = [row['COLUMN_NAME'] for row in db.query(pk_query)]

            response = {
                "table_name": table_name.upper(),
                "columns": columns,
                "primary_keys": pk_columns
            }

            return [TextContent(
                type="text",
                text=json.dumps(response, indent=2, default=str)
            )]

        elif name == "list_tables":
            schema = arguments.get("schema")

            if schema:
                query = f"""
                    SELECT table_name, owner
                    FROM all_tables
                    WHERE owner = '{schema.upper()}'
                    ORDER BY table_name
                """
            else:
                query = """
                    SELECT table_name, 'USER' as owner
                    FROM user_tables
                    ORDER BY table_name
                """

            tables = db.query(query)

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
