#!/usr/bin/env python3
"""
Query validator for Oracle MCP Server.
Prevents dangerous queries like cross joins, cartesian products, and expensive operations.
"""

import re
from typing import Tuple, List, Optional
from dataclasses import dataclass
from collections import Counter


@dataclass
class ValidationResult:
    """Result of query validation."""
    is_safe: bool
    error_message: Optional[str] = None
    warnings: List[str] = None
    complexity_score: int = 0

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class QueryValidator:
    """Validates SQL queries for safety before execution."""

    # Maximum allowed complexity score
    MAX_COMPLEXITY_SCORE = 50

    # Maximum result rows (will be enforced via ROWNUM)
    MAX_RESULT_ROWS = 10000

    # Dangerous keywords that require special attention
    DANGEROUS_PATTERNS = [
        r'\bCROSS\s+JOIN\b',  # Explicit cross joins
        r'\bCARTESIAN\b',  # Cartesian references
    ]

    # Keywords that are completely blocked
    BLOCKED_KEYWORDS = [
        r'\bDROP\b',
        r'\bTRUNCATE\b',
        r'\bDELETE\b',
        r'\bINSERT\b',
        r'\bUPDATE\b',
        r'\bMERGE\b',
        r'\bALTER\b',
        r'\bCREATE\b',
        r'\bEXEC\b',
        r'\bEXECUTE\b',
        r'\bCALL\b',
        r'\bGRANT\b',
        r'\bREVOKE\b',
        r'\bUNION\s+ALL\b',  # Block UNION ALL for data exfiltration
        r'\bUNION\b',        # Block UNION for data exfiltration
    ]

    def __init__(
        self,
        max_complexity: int = MAX_COMPLEXITY_SCORE,
        max_rows: int = MAX_RESULT_ROWS,
        allow_cross_joins: bool = False
    ):
        """
        Initialize query validator.

        Args:
            max_complexity: Maximum allowed complexity score
            max_rows: Maximum rows to return (enforced via ROWNUM)
            allow_cross_joins: Allow explicit CROSS JOIN keywords (dangerous!)
        """
        self.max_complexity = max_complexity
        self.max_rows = max_rows
        self.allow_cross_joins = allow_cross_joins

    def _strip_sql_comments(self, query: str) -> str:
        """
        Strip SQL comments from query to prevent bypass via comment injection.

        Args:
            query: SQL query with potential comments

        Returns:
            Query with comments removed
        """
        # Remove single-line comments (-- ...)
        query = re.sub(r'--[^\n]*', '', query)

        # Remove multi-line comments (/* ... */)
        query = re.sub(r'/\*.*?\*/', '', query, flags=re.DOTALL)

        return query

    def validate(self, query: str) -> ValidationResult:
        """
        Validate a SQL query for safety.

        Args:
            query: SQL query to validate

        Returns:
            ValidationResult with safety assessment
        """
        # Strip comments first to prevent comment-based bypasses
        query = self._strip_sql_comments(query)
        query_upper = query.upper()
        warnings = []
        complexity_score = 0

        # 1. Check for blocked keywords (write operations)
        for pattern in self.BLOCKED_KEYWORDS:
            if re.search(pattern, query_upper):
                return ValidationResult(
                    is_safe=False,
                    error_message=f"Blocked operation detected: {pattern}. Only SELECT queries are allowed."
                )

        # 2. Must be a SELECT query or CTE (WITH clause)
        if not re.match(r'^\s*(SELECT|WITH)\b', query_upper):
            return ValidationResult(
                is_safe=False,
                error_message="Only SELECT queries (including CTEs with WITH clause) are allowed."
            )

        # 3. Check for dangerous patterns
        if not self.allow_cross_joins:
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, query_upper):
                    return ValidationResult(
                        is_safe=False,
                        error_message=f"Dangerous pattern detected: {pattern}. Cross joins and cartesian products are not allowed."
                    )

        # 4. Detect implicit cartesian products (multiple tables without JOIN keyword)
        complexity_score += self._check_implicit_cartesian(query_upper, warnings)

        # 5. Count tables in FROM clause
        table_count = self._count_tables(query_upper)
        complexity_score += table_count * 5

        if table_count > 1:
            warnings.append(f"Query involves {table_count} tables. Ensure proper JOIN conditions exist.")

        # 6. Check for missing WHERE clause on multi-table queries
        if table_count > 1 and not self._has_where_clause(query_upper):
            # Check if it's using explicit JOINs (which have ON conditions)
            if not re.search(r'\bJOIN\b.*\bON\b', query_upper):
                return ValidationResult(
                    is_safe=False,
                    error_message="Multi-table query without WHERE clause or JOIN ON conditions detected. This could create a cartesian product."
                )
            warnings.append("Multi-table query without WHERE clause. Ensure JOIN conditions are sufficient.")

        # 7. Check for SELECT * with multiple tables
        if table_count > 1 and re.search(r'\bSELECT\s+\*', query_upper):
            complexity_score += 10
            warnings.append("SELECT * with multiple tables can be expensive. Consider specifying columns.")

        # 8. Look for subqueries (more accurately - find SELECT within parentheses)
        # Pattern: ( ... SELECT ... ) indicates a subquery
        # This is better than counting all SELECT keywords which can appear in strings/comments
        subquery_pattern = r'\(\s*SELECT\s+'
        subquery_matches = re.findall(subquery_pattern, query_upper)
        subquery_count = len(subquery_matches)
        if subquery_count > 0:
            complexity_score += subquery_count * 10
            warnings.append(f"Query contains {subquery_count} subquery(ies). Monitor performance.")

            # Check for nested subquery depth (subqueries within subqueries)
            # Nested depth adds additional complexity
            if subquery_count > 2:
                complexity_score += (subquery_count - 2) * 5
                warnings.append(f"Deep nesting detected ({subquery_count} subqueries). This can significantly impact performance.")

        # 9. Check for CTEs (WITH clauses)
        cte_pattern = r'\bWITH\s+\w+\s+AS\s*\('
        cte_matches = re.findall(cte_pattern, query_upper)
        cte_count = len(cte_matches)
        if cte_count > 0:
            complexity_score += cte_count * 8
            warnings.append(f"Query contains {cte_count} CTE(s) (WITH clause). CTEs can be expensive if not materialized.")

        # 10. Check for window functions
        window_functions = [
            r'\bROW_NUMBER\s*\(',
            r'\bRANK\s*\(',
            r'\bDENSE_RANK\s*\(',
            r'\bNTILE\s*\(',
            r'\bLAG\s*\(',
            r'\bLEAD\s*\(',
            r'\bFIRST_VALUE\s*\(',
            r'\bLAST_VALUE\s*\(',
            r'\bPERCENT_RANK\s*\(',
            r'\bCUME_DIST\s*\(',
        ]
        window_function_count = 0
        for pattern in window_functions:
            window_function_count += len(re.findall(pattern, query_upper))

        if window_function_count > 0:
            complexity_score += window_function_count * 12
            warnings.append(f"Query contains {window_function_count} window function(s). Window functions can be very expensive on large datasets.")

        # 11. Check for self-joins (same table appears multiple times)
        # Look for table names after FROM or JOIN keywords
        # Pattern: (FROM|JOIN) table_name [AS] alias
        table_pattern = r'(?:FROM|JOIN)\s+([A-Z_][A-Z0-9_]*)\s+(?:AS\s+)?[A-Z_][A-Z0-9_]*'
        table_references = re.findall(table_pattern, query_upper)
        if table_references:
            # Count duplicate table names (self-joins)
            table_counts = Counter(table_references)
            self_joins = sum(1 for table, count in table_counts.items() if count > 1)
            if self_joins > 0:
                complexity_score += self_joins * 15
                warnings.append(f"Query contains {self_joins} self-join(s). Self-joins can create large intermediate result sets.")

        # 12. Check for LIKE with leading wildcard (very expensive)
        leading_wildcard_pattern = r"LIKE\s+['\"]%"
        leading_wildcard_matches = re.findall(leading_wildcard_pattern, query_upper)
        if leading_wildcard_matches:
            leading_wildcard_count = len(leading_wildcard_matches)
            complexity_score += leading_wildcard_count * 10
            warnings.append(f"Query contains {leading_wildcard_count} LIKE pattern(s) with leading wildcard ('%...'). This prevents index usage and causes full table scans.")

        # 13. Check for OR conditions (can prevent index usage)
        or_pattern = r'\bOR\b'
        or_matches = re.findall(or_pattern, query_upper)
        or_count = len(or_matches)
        if or_count > 2:  # More than 2 ORs is concerning
            complexity_score += (or_count - 2) * 4
            warnings.append(f"Query contains {or_count} OR condition(s). Multiple ORs can prevent index usage and degrade performance.")

        # 14. Check for DISTINCT
        if 'DISTINCT' in query_upper:
            complexity_score += 5
            warnings.append("DISTINCT can be expensive on large result sets.")

        # 15. Check for aggregate functions
        aggregates = ['COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'GROUP BY']
        aggregate_count = sum(1 for agg in aggregates if agg in query_upper)
        if aggregate_count > 0:
            complexity_score += aggregate_count * 3

        # 16. Verify complexity score
        if complexity_score > self.max_complexity:
            return ValidationResult(
                is_safe=False,
                error_message=f"Query complexity score ({complexity_score}) exceeds maximum allowed ({self.max_complexity}). Simplify the query.",
                complexity_score=complexity_score,
                warnings=warnings
            )

        # Query is safe!
        return ValidationResult(
            is_safe=True,
            warnings=warnings,
            complexity_score=complexity_score
        )

    def _check_implicit_cartesian(self, query_upper: str, warnings: List[str]) -> int:
        """
        Check for implicit cartesian products (comma-separated tables in FROM).

        Returns:
            Complexity score penalty
        """
        complexity_penalty = 0

        # Look for FROM clause with comma-separated tables
        from_match = re.search(r'\bFROM\s+(.*?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|$)', query_upper, re.DOTALL)

        if from_match:
            from_clause = from_match.group(1)

            # Exclude subqueries in FROM clause
            from_clause = re.sub(r'\(.*?\)', '', from_clause)

            # Count commas (indicates multiple tables)
            comma_count = from_clause.count(',')

            if comma_count > 0:
                # This is comma-separated table syntax (old-style join)
                complexity_penalty = comma_count * 20  # Heavy penalty
                warnings.append(
                    f"Detected {comma_count + 1} comma-separated tables in FROM clause. "
                    "This can create cartesian products. Use explicit JOIN syntax."
                )

        return complexity_penalty

    def _count_tables(self, query_upper: str) -> int:
        """
        Count number of tables in FROM clause.

        Returns:
            Number of tables
        """
        # Look for FROM clause
        from_match = re.search(r'\bFROM\s+(.*?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|$)', query_upper, re.DOTALL)

        if not from_match:
            return 1  # Assume at least one table

        from_clause = from_match.group(1)

        # Remove subqueries
        from_clause = re.sub(r'\(.*?\)', '', from_clause)

        # Count table references (commas + JOINs)
        comma_count = from_clause.count(',')
        join_count = len(re.findall(r'\bJOIN\b', from_clause))

        # Total tables = 1 (first table) + commas + joins
        return 1 + comma_count + join_count

    def _has_where_clause(self, query_upper: str) -> bool:
        """Check if query has a WHERE clause."""
        return bool(re.search(r'\bWHERE\b', query_upper))

    def _has_rownum_constraint(self, query: str) -> bool:
        """
        Check if query already has a ROWNUM constraint.

        Args:
            query: SQL query to check

        Returns:
            True if query has ROWNUM constraint, False otherwise
        """
        query_upper = query.upper()

        # Look for ROWNUM in WHERE clause or comparison
        # Match patterns like:
        # - WHERE ROWNUM <= 100
        # - AND ROWNUM < 1000
        # - ROWNUM = 1
        if re.search(r'\bROWNUM\s*[<>=]+\s*\d+', query_upper):
            return True

        # Check for ROWNUM in subquery wrapping pattern
        if re.search(r'WHERE\s+ROWNUM\s*<=', query_upper):
            return True

        return False

    def wrap_with_row_limit(self, query: str) -> str:
        """
        Wrap query with ROWNUM limit to prevent massive result sets.

        Args:
            query: Original SQL query

        Returns:
            Query wrapped with ROWNUM limit
        """
        query_stripped = query.strip()
        query_upper = query_stripped.upper()

        # If query already has proper ROWNUM constraint, don't wrap
        if self._has_rownum_constraint(query_stripped):
            return query_stripped

        # If query has ORDER BY, we need to preserve it
        if 'ORDER BY' in query_upper:
            # Wrap the entire query and apply ROWNUM in outer query
            return f"""
SELECT * FROM (
    {query_stripped}
) WHERE ROWNUM <= {self.max_rows}
""".strip()
        else:
            # Simple case: just add WHERE ROWNUM
            # Check if query already has WHERE
            if 'WHERE' in query_upper:
                # Add AND ROWNUM condition
                return f"{query_stripped} AND ROWNUM <= {self.max_rows}"
            else:
                # Add WHERE ROWNUM condition
                return f"{query_stripped} WHERE ROWNUM <= {self.max_rows}"


def main():
    """Test the query validator."""
    validator = QueryValidator()

    test_queries = [
        # Safe queries
        "SELECT * FROM users WHERE id = 123",
        "SELECT name, email FROM customers WHERE created_date > SYSDATE - 7",
        "SELECT COUNT(*) FROM orders",

        # Dangerous queries
        "SELECT * FROM orders, customers",  # Implicit cartesian product
        "SELECT * FROM users CROSS JOIN orders",  # Explicit cross join
        "SELECT * FROM table1, table2, table3 WHERE table1.id = 1",  # Multiple tables, suspicious WHERE
        "DELETE FROM users WHERE id = 1",  # Write operation
        "DROP TABLE users",  # Blocked operation

        # Complex queries
        "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = 'PENDING'",
        "SELECT DISTINCT customer_id FROM orders WHERE order_date > SYSDATE - 30",
    ]

    print("Query Validator Test Results")
    print("=" * 80)

    for i, query in enumerate(test_queries, 1):
        print(f"\n{i}. Query: {query[:60]}...")
        result = validator.validate(query)

        print(f"   Safe: {result.is_safe}")
        print(f"   Complexity: {result.complexity_score}")

        if result.error_message:
            print(f"   ❌ Error: {result.error_message}")

        if result.warnings:
            for warning in result.warnings:
                print(f"   ⚠️  Warning: {warning}")

        if result.is_safe:
            wrapped = validator.wrap_with_row_limit(query)
            if wrapped != query:
                print(f"   📝 Wrapped with row limit")


if __name__ == "__main__":
    main()
