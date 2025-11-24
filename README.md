# Oracle MCP Server with Advanced Safety Features

A Model Context Protocol (MCP) server for Oracle databases with comprehensive query safety features, designed to work through StrongDM proxies and on Apple Silicon Macs.

**🔒 Security Audited:** ✅ All vulnerabilities fixed (2025-11-21)

## 🛡️ Why This MCP?

Unlike other database MCP servers, this implementation includes **production-grade safety features**:

- ✅ **SQL Injection Protection** - Strict input validation on all entry points
- ✅ **Blocks cartesian products** - Prevents accidental cross joins that could lock your database
- ✅ **Query complexity scoring** - Rejects overly complex queries before execution
- ✅ **Result set limits** - Automatically enforces maximum row returns (10,000 default)
- ✅ **Read-only enforcement** - Blocks all write operations (DELETE, UPDATE, INSERT, DROP, UNION, etc.)
- ✅ **Multi-layer validation** - Pattern detection, keyword blocking, and complexity analysis
- ✅ **Credential security** - Passwords never exposed in process listings
- ✅ **Comment stripping** - Prevents SQL comment-based bypasses
- ✅ **Detailed logging** - All blocked queries are logged with reasons

**Security Research:** 43% of popular MCP servers contain SQL injection vulnerabilities. This implementation was built with security-first design and has passed comprehensive security auditing.

## 🏗️ Architecture

This MCP uses a **Java subprocess pattern** to connect to Oracle via JDBC:

```
┌─────────────────┐
│ Claude/AI Agent │
└────────┬────────┘
         │ MCP Protocol
┌────────▼────────────────┐
│ oracle_mcp_server.py    │  ← Python MCP Server
│  + Query Validator      │  ← SAFETY LAYER
└────────┬────────────────┘
         │ Subprocess
┌────────▼────────────────┐
│  Java JDBC Process      │  ← OracleQuery.java
│  ojdbc11.jar            │
└────────┬────────────────┘
         │ TCP/StrongDM
┌────────▼────────────────┐
│  Oracle Database        │
└─────────────────────────┘
```

### Why Java Subprocess?

This implementation was created because **existing MCP solutions don't work** with StrongDM + Apple Silicon:

- ❌ **mcp-alchemy** with Python `oracledb` → Failed (StrongDM incompatible)
- ❌ **Python-Java bridges** (JPype1, PyJNIus) → Crashed on Apple Silicon
- ✅ **Java JDBC subprocess** → Uses proven DataGrip JDBC driver

**Benefits:**
- Works with StrongDM proxies where Python libraries fail
- Proven stability (same driver as JetBrains DataGrip)
- Process isolation prevents crashes
- No native library complications on Apple Silicon

## 🚀 Quick Start

### Prerequisites

- Java 21+ (OpenJDK recommended)
- Python 3.12+
- Oracle JDBC driver (ojdbc11)
- Access to Oracle database (direct or via StrongDM proxy)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/mofiaboss/oracle-mcp-sdm-with-guardrails.git
   cd oracle-mcp-sdm-with-guardrails
   ```

2. **Create virtual environment:**
   ```bash
   # Use python3.10 or later (python3.12 recommended)
   python3.12 -m venv oracle_mcp_venv
   source oracle_mcp_venv/bin/activate  # On Windows: oracle_mcp_venv\Scripts\activate
   ```

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Download Oracle JDBC driver:**
   - Download `ojdbc11-23.5.0.24.07.jar` (or later) from [Oracle](https://www.oracle.com/database/technologies/jdbc-ucp-downloads.html)
   - Place in the project directory or note the path

5. **Download JSON library:**
   - Download `json-20240303.jar` from [Maven Central](https://mvnrepository.com/artifact/org.json/json/20240303)
   - Rename to `json.jar` and place in the project directory

6. **Compile Java query program:**
   ```bash
   export JDBC_JAR="/path/to/ojdbc11-23.5.0.24.07.jar"
   javac -cp ".:json.jar:$JDBC_JAR" OracleQuery.java
   ```

7. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your Oracle connection details
   ```

8. **Update paths in `oracle_jdbc.py`:**
   Edit lines 38-47 to match your Java and JDBC paths:
   ```python
   self.java_home = Path("/opt/homebrew/opt/openjdk@21")
   self.jdbc_jar = Path("/path/to/ojdbc11-23.5.0.24.07.jar")
   ```

### Testing

```bash
# Test safety features
python test_safety.py

# Test Python wrapper
python oracle_jdbc.py
```

## 🔧 Configuration

### Claude Desktop Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "oracle": {
      "command": "/path/to/oracle_mcp_venv/bin/python",
      "args": [
        "/path/to/oracle_mcp_server.py"
      ],
      "env": {
        "ORACLE_HOST": "127.0.0.1",
        "ORACLE_PORT": "10006",
        "ORACLE_SERVICE_NAME": "ORCL",
        "ORACLE_USER": "your_username",
        "ORACLE_PASSWORD": "your_password"
      }
    }
  }
}
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ORACLE_HOST` | Database host | `127.0.0.1` |
| `ORACLE_PORT` | Database port | `10006` |
| `ORACLE_SERVICE_NAME` | Oracle service name | `ylvoprd` |
| `ORACLE_USER` | Database username | `username` |
| `ORACLE_PASSWORD` | Database password | `password` |

### Safety Configuration

Adjust safety settings in `oracle_mcp_server.py` (lines 48-52):

```python
validator = QueryValidator(
    max_complexity=50,      # Maximum complexity score (lower = stricter)
    max_rows=10000,         # Maximum result rows
    allow_cross_joins=False # Enable to allow CROSS JOIN (not recommended)
)
```

## 🛡️ Safety Features

See [SAFETY_FEATURES.md](SAFETY_FEATURES.md) for complete documentation.

### What Gets Blocked

```sql
-- ❌ Cartesian products
SELECT * FROM orders, customers

-- ❌ Explicit cross joins
SELECT * FROM users CROSS JOIN orders

-- ❌ All write operations
DELETE FROM users WHERE id = 1
UPDATE orders SET status = 'X'
INSERT INTO users VALUES (1, 'test')
DROP TABLE sensitive_data
TRUNCATE TABLE logs

-- ❌ Overly complex queries (score > 50)
SELECT * FROM t1, t2, t3, t4 WHERE t1.id = 1
```

### What Gets Allowed (with warnings)

```sql
-- ✅ Simple queries
SELECT * FROM users WHERE id = 123

-- ✅ Proper joins with conditions
SELECT * FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.status = 'PENDING'

-- ✅ Aggregate queries
SELECT COUNT(*) FROM orders WHERE created_date > SYSDATE - 7
```

### Query Complexity Scoring

Queries are scored based on:
- **+5** points per table
- **+20** points per comma-separated table (implicit join)
- **+10** points per subquery
- **+5** points for `DISTINCT`
- **+3** points per aggregate function
- **+10** points for `SELECT *` with multiple tables

Maximum score: **50** (configurable)

## 📊 Query Response Format

Successful queries return validation metadata:

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

Blocked queries return detailed errors:

```json
{
  "success": false,
  "error": "Dangerous pattern detected: CROSS JOIN...",
  "complexity_score": 0,
  "warnings": []
}
```

## 🔌 Available MCP Tools

### 🎯 Recommended Query Workflow

**For maximum safety, always preview queries before execution:**

1. **Preview First:** Use `preview_query` to validate and see complexity score
2. **Review:** Claude will show you the query and complexity details
3. **Confirm:** Explicitly approve the query execution
4. **Execute:** Claude will then use `query_oracle` to run it

This two-step workflow ensures you're always aware of what will run against your database.

### `preview_query` ⭐ **USE THIS FIRST**

Preview and validate SQL queries WITHOUT executing them. Shows:
- The exact query that will be executed
- Complexity score (0-50, lower is simpler)
- Any validation warnings or errors
- Whether row limits will be applied
- Safety assessment

**Example:**
```
Preview this query: SELECT * FROM customers WHERE country = 'US'
```

**Response includes:**
```json
{
  "preview_mode": true,
  "query_to_execute": "SELECT * FROM customers WHERE country = 'US'",
  "validation": {
    "is_safe": true,
    "complexity_score": 8,
    "max_complexity": 50,
    "complexity_explanation": "Lower is simpler. Score based on: JOINs (+5 each), subqueries (+3 each), GROUP BY (+2), aggregates (+1 each)",
    "warnings": ["Table 'customers' used - ensure proper WHERE clause"]
  },
  "safety_limits": {
    "max_rows": 10000,
    "row_limit_will_be_applied": true
  }
}
```

### `query_oracle`

Execute SQL SELECT queries with safety validation.

**Important:** Should only be called AFTER using `preview_query` and getting user confirmation.

**Example:**
```
Query the database: SELECT * FROM customers WHERE country = 'US'
```

### `describe_table`
Get table structure, columns, data types, and primary keys.

**Example:**
```
Describe the ORDERS table structure
```

### `list_tables`
List all accessible tables in the database.

**Example:**
```
List all tables in the current schema
```

## 📁 Project Structure

```
oracle-mcp-server/
├── oracle_mcp_server.py    # Main MCP server
├── oracle_jdbc.py           # JDBC wrapper
├── query_validator.py       # Safety validation layer
├── OracleQuery.java         # Java JDBC query program
├── OracleQuery.class        # Compiled Java class
├── json.jar                 # JSON library for Java
├── test_safety.py           # Safety feature tests
├── SAFETY_FEATURES.md       # Detailed safety documentation
├── README.md                # This file
├── requirements.txt         # Python dependencies
└── .env.example            # Environment configuration template
```

## 🐛 Troubleshooting

### Connection Fails

1. **Verify Java installation:**
   ```bash
   java -version
   # Should show Java 21+
   ```

2. **Test database connectivity:**
   ```bash
   # Via SQLPlus or another tool
   sqlplus username/password@//host:port/service_name
   ```

3. **Check StrongDM (if using):**
   ```bash
   ps aux | grep sdm
   nc -zv 127.0.0.1 10006
   ```

4. **Verify JDBC jar path:**
   ```bash
   ls -la /path/to/ojdbc11*.jar
   ```

### Java Errors

- **ClassNotFoundException**: JDBC jar not in classpath
- **UnsatisfiedLinkError**: Java version mismatch
- **Connection refused**: Database not accessible on specified host/port

### MCP Server Not Loading

1. Restart Claude Desktop completely
2. Check logs in Claude Desktop for errors
3. Test Python script directly: `python oracle_mcp_server.py`
4. Verify all dependencies installed: `pip list`

## 🤝 Contributing

Contributions welcome! Areas for improvement:

- [ ] Add support for more database types
- [ ] Implement connection pooling
- [ ] Add query plan analysis
- [ ] Create Docker container
- [ ] Add metrics/monitoring endpoints
- [ ] Support for Oracle Wallet authentication

## 📝 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- Built as a workaround for StrongDM proxy compatibility issues on Apple Silicon
- Inspired by security research from Datadog Security Labs on MCP vulnerabilities
- Query validation patterns based on OWASP SQL injection prevention guidelines
- Uses the proven Oracle JDBC driver from JetBrains DataGrip

## 📚 Related Documentation

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Oracle JDBC Driver](https://www.oracle.com/database/technologies/appdev/jdbc.html)
- [OWASP SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- [StrongDM](https://www.strongdm.com/)
- [MCP Security Best Practices](https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/)

---

**Security Note:** This MCP server blocks write operations by default. If you need write access, you should implement additional authentication and authorization layers appropriate for your environment.
