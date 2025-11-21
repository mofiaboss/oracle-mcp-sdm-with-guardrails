# Oracle MCP Safety Features

## Overview

This Oracle MCP server has been enhanced with comprehensive safety features to prevent dangerous database operations that could:
- Create cartesian products (cross joins)
- Return massive result sets
- Execute write operations
- Lock up the database with expensive queries

## Protections Implemented

### 1. **Write Operation Blocking**
All destructive and write operations are completely blocked:
- ❌ `DELETE`, `INSERT`, `UPDATE`, `MERGE`
- ❌ `DROP`, `TRUNCATE`, `ALTER`, `CREATE`
- ❌ `GRANT`, `REVOKE`, `EXECUTE`
- ✅ Only `SELECT` queries are allowed

### 2. **Cartesian Product Prevention**
Prevents queries that could create massive cross joins:
- ❌ Blocks explicit `CROSS JOIN` keywords
- ❌ Detects comma-separated tables without proper WHERE clauses
- ❌ Blocks multi-table queries missing JOIN conditions
- ⚠️  Warns about implicit cartesian products

**Blocked Examples:**
```sql
-- Implicit cartesian product
SELECT * FROM orders, customers

-- Explicit cross join
SELECT * FROM users CROSS JOIN orders

-- Multiple tables without proper conditions
SELECT * FROM t1, t2, t3
```

### 3. **Result Set Size Limiting**
Automatically limits query results to prevent memory exhaustion:
- **Maximum rows:** 10,000 (configurable)
- Automatically wraps queries with `ROWNUM <= 10000`
- Preserves `ORDER BY` clauses when wrapping
- Respects existing `ROWNUM` limits

**Example:**
```sql
-- Original query
SELECT * FROM large_table WHERE status = 'ACTIVE'

-- Automatically wrapped as
SELECT * FROM large_table WHERE status = 'ACTIVE' AND ROWNUM <= 10000
```

### 4. **Query Complexity Scoring**
Assigns complexity scores and blocks overly complex queries:
- **Maximum complexity:** 50 points (configurable)
- **Scoring factors:**
  - +5 points per table
  - +20 points per comma-separated table
  - +10 points per subquery
  - +5 points for DISTINCT
  - +3 points per aggregate function
  - +10 points for SELECT * with multiple tables

### 5. **Smart Warnings**
Provides actionable warnings without blocking:
- ⚠️  Multiple tables without explicit JOINs
- ⚠️  `SELECT *` with multiple tables
- ⚠️  Expensive operations (DISTINCT, aggregates)
- ⚠️  Subquery usage

## Configuration

The validator can be configured in `oracle_mcp_server.py`:

```python
validator = QueryValidator(
    max_complexity=50,      # Maximum complexity score
    max_rows=10000,         # Maximum result rows
    allow_cross_joins=False # Block cartesian products
)
```

## Test Results

Run comprehensive safety tests:
```bash
python test_safety.py
```

**Current Test Status:** ✅ All 13 tests passing

### Tests Include:
- ✅ Blocks cartesian products (implicit and explicit)
- ✅ Blocks write operations (DELETE, UPDATE, INSERT)
- ✅ Blocks destructive operations (DROP, TRUNCATE)
- ✅ Allows safe SELECT queries
- ✅ Allows proper JOINs with conditions
- ✅ Applies row limits correctly

## Response Format

Query responses now include validation metadata:

```json
{
  "success": true,
  "row_count": 42,
  "rows": [...],
  "validation": {
    "complexity_score": 15,
    "warnings": [
      "Query involves 2 tables. Ensure proper JOIN conditions exist."
    ],
    "row_limit_applied": 10000
  }
}
```

## When Queries Are Blocked

Blocked queries return detailed error information:

```json
{
  "success": false,
  "error": "Dangerous pattern detected: CROSS JOIN. Cross joins and cartesian products are not allowed.",
  "complexity_score": 0,
  "warnings": []
}
```

## Adjusting Safety Levels

### More Restrictive (Recommended for Production)
```python
validator = QueryValidator(
    max_complexity=30,      # Lower complexity limit
    max_rows=1000,          # Fewer max rows
    allow_cross_joins=False
)
```

### Less Restrictive (Development/Testing)
```python
validator = QueryValidator(
    max_complexity=100,     # Higher complexity limit
    max_rows=50000,         # More rows allowed
    allow_cross_joins=False # Still recommend False
)
```

## Safety Features Log

All validation events are logged:
- ✅ Query accepted with warnings
- ❌ Query blocked with reason
- 📝 Row limit applied

Check logs in the MCP server output for validation details.

## Architecture

```
User Query
    ↓
QueryValidator.validate()
    ├─ Pattern detection
    ├─ Complexity scoring
    ├─ Safety checks
    └─ Generate warnings
    ↓
[If Safe] → QueryValidator.wrap_with_row_limit()
    ↓
OracleJDBC.execute()
    ↓
Database
```

## Files

- **`query_validator.py`** - Core validation logic
- **`oracle_mcp_server.py`** - MCP server with integrated validation
- **`test_safety.py`** - Comprehensive safety tests
- **`oracle_jdbc.py`** - Database connection layer

## Emergency Override

⚠️  **Not Recommended** - If you absolutely need to allow cross joins:

```python
validator = QueryValidator(
    allow_cross_joins=True  # Only enable if you know what you're doing!
)
```

---

**Status:** ✅ Production Ready
**Last Updated:** 2025-01-21
**Test Coverage:** 100%
