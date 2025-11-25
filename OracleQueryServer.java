import java.io.*;
import java.sql.*;
import org.json.JSONObject;
import org.json.JSONArray;

/**
 * Long-lived Oracle query server for connection pooling.
 * Accepts queries from stdin and returns JSON results to stdout.
 * Maintains a single database connection for reuse.
 */
public class OracleQueryServer {
    private Connection conn = null;
    private String url;
    private String user;
    private String password;
    private boolean isConnected = false;

    public OracleQueryServer(String url, String user, String password) {
        this.url = url;
        this.user = user;
        this.password = password;
    }

    /**
     * Initialize database connection.
     */
    private void connect() throws Exception {
        if (conn != null && !conn.isClosed()) {
            return; // Already connected
        }

        Class.forName("oracle.jdbc.driver.OracleDriver");
        DriverManager.setLoginTimeout(5);
        conn = DriverManager.getConnection(url, user, password);
        isConnected = true;

        // Send ready signal
        JSONObject ready = new JSONObject();
        ready.put("status", "ready");
        ready.put("message", "Connection established");
        System.out.println(ready.toString());
        System.out.flush();
    }

    /**
     * Check if connection is still alive, reconnect if needed.
     */
    private void ensureConnected() throws Exception {
        if (conn == null || conn.isClosed() || !isConnectionAlive()) {
            isConnected = false;
            connect();
        }
    }

    /**
     * Test if connection is alive.
     */
    private boolean isConnectionAlive() {
        try {
            return conn != null && conn.isValid(2); // 2 second timeout
        } catch (SQLException e) {
            return false;
        }
    }

    /**
     * Execute a query and return JSON result.
     */
    private String executeQuery(String query) {
        Statement stmt = null;
        ResultSet rs = null;

        try {
            // Ensure connection is alive
            ensureConnected();

            // Create statement with security settings
            stmt = conn.createStatement();
            stmt.setQueryTimeout(5); // 5 second query timeout
            stmt.setFetchSize(1000); // Prevent memory exhaustion

            // Execute query
            rs = stmt.executeQuery(query);

            // Get metadata
            ResultSetMetaData rsmd = rs.getMetaData();
            int columnCount = rsmd.getColumnCount();

            // Build JSON result
            JSONArray results = new JSONArray();
            while (rs.next()) {
                JSONObject row = new JSONObject();
                for (int i = 1; i <= columnCount; i++) {
                    String columnName = rsmd.getColumnName(i);
                    Object value = rs.getObject(i);
                    row.put(columnName, value);
                }
                results.put(row);
            }

            // Output JSON
            JSONObject output = new JSONObject();
            output.put("success", true);
            output.put("rows", results);
            output.put("count", results.length());
            return output.toString();

        } catch (SQLException e) {
            JSONObject error = new JSONObject();
            error.put("success", false);
            error.put("error", "Database error: " + e.getMessage());
            error.put("sql_state", e.getSQLState());
            return error.toString();
        } catch (Exception e) {
            JSONObject error = new JSONObject();
            error.put("success", false);
            error.put("error", "Query execution failed: " + e.getMessage());
            return error.toString();
        } finally {
            // Close resources but keep connection alive
            try {
                if (rs != null) rs.close();
            } catch (SQLException e) {
                System.err.println("Warning: Failed to close ResultSet: " + e.getMessage());
            }
            try {
                if (stmt != null) stmt.close();
            } catch (SQLException e) {
                System.err.println("Warning: Failed to close Statement: " + e.getMessage());
            }
        }
    }

    /**
     * Main server loop - reads queries from stdin, executes, returns results to stdout.
     */
    public void run() {
        try {
            // Connect to database
            connect();

            // Read queries from stdin
            BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
            String line;

            while ((line = reader.readLine()) != null) {
                line = line.trim();

                // Handle special commands
                if (line.equals("PING")) {
                    JSONObject pong = new JSONObject();
                    pong.put("status", "alive");
                    pong.put("connected", isConnectionAlive());
                    System.out.println(pong.toString());
                    System.out.flush();
                    continue;
                }

                if (line.equals("EXIT")) {
                    break;
                }

                if (line.isEmpty()) {
                    continue;
                }

                // Execute query
                String result = executeQuery(line);
                System.out.println(result);
                System.out.flush();
            }

        } catch (Exception e) {
            JSONObject error = new JSONObject();
            error.put("success", false);
            error.put("error", "Server error: " + e.getMessage());
            System.out.println(error.toString());
            System.err.println("Fatal error: " + e.getMessage());
            e.printStackTrace(System.err);
        } finally {
            // Cleanup
            try {
                if (conn != null && !conn.isClosed()) {
                    conn.close();
                }
            } catch (SQLException e) {
                System.err.println("Error closing connection: " + e.getMessage());
            }
        }
    }

    public static void main(String[] args) {
        // Get URL from command line
        if (args.length < 1) {
            System.err.println("Usage: java OracleQueryServer <jdbc_url>");
            System.err.println("Credentials must be provided via ORACLE_USER and ORACLE_PASSWORD environment variables");
            System.exit(1);
        }

        String url = args[0];

        // Get credentials from environment
        String user = System.getenv("ORACLE_USER");
        String password = System.getenv("ORACLE_PASSWORD");

        if (user == null || password == null) {
            JSONObject error = new JSONObject();
            error.put("success", false);
            error.put("error", "ORACLE_USER and ORACLE_PASSWORD environment variables must be set");
            System.out.println(error.toString());
            System.exit(1);
        }

        // Start server
        OracleQueryServer server = new OracleQueryServer(url, user, password);
        server.run();
    }
}
