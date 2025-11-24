import java.sql.*;
import org.json.JSONObject;
import org.json.JSONArray;

public class OracleQuery {
    public static void main(String[] args) {
        // Accept URL and query from command line, but get credentials from environment
        // This prevents credentials from appearing in process listings
        if (args.length < 2) {
            System.err.println("Usage: java OracleQuery <url> <query>");
            System.err.println("Credentials must be provided via ORACLE_USER and ORACLE_PASSWORD environment variables");
            System.exit(1);
        }

        String url = args[0];
        String query = args[1];

        // Get credentials from environment variables (not command line)
        String user = System.getenv("ORACLE_USER");
        String password = System.getenv("ORACLE_PASSWORD");

        if (user == null || password == null) {
            JSONObject error = new JSONObject();
            error.put("success", false);
            error.put("error", "ORACLE_USER and ORACLE_PASSWORD environment variables must be set");
            System.out.println(error.toString());
            System.exit(1);
        }

        Connection conn = null;
        Statement stmt = null;
        ResultSet rs = null;

        try {
            // Load Oracle JDBC driver
            Class.forName("oracle.jdbc.driver.OracleDriver");

            // Connect to database with timeout
            DriverManager.setLoginTimeout(5); // 5 second connection timeout
            conn = DriverManager.getConnection(url, user, password);

            // Create statement with timeout and security settings
            stmt = conn.createStatement();

            // CRITICAL SECURITY: Set query timeout to prevent resource exhaustion
            stmt.setQueryTimeout(5); // 5 seconds max query execution

            // Set fetch size to prevent memory exhaustion
            stmt.setFetchSize(1000);

            // Execute query (note: PreparedStatement not possible for dynamic queries)
            // Security depends on validation in Python layer
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
            System.out.println(output.toString());

        } catch (SQLException e) {
            // SQL-specific errors - safe to return detailed message
            JSONObject error = new JSONObject();
            error.put("success", false);
            error.put("error", "Database error: " + e.getMessage());
            error.put("sql_state", e.getSQLState());
            System.out.println(error.toString());
            System.exit(1);
        } catch (ClassNotFoundException e) {
            // Driver not found
            JSONObject error = new JSONObject();
            error.put("success", false);
            error.put("error", "JDBC driver not found");
            System.out.println(error.toString());
            System.exit(1);
        } catch (Exception e) {
            // Generic errors - don't leak implementation details
            JSONObject error = new JSONObject();
            error.put("success", false);
            error.put("error", "Query execution failed");
            System.out.println(error.toString());
            System.exit(1);
        } finally {
            // Ensure cleanup happens even if errors occur
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
            try {
                if (conn != null) conn.close();
            } catch (SQLException e) {
                System.err.println("Warning: Failed to close Connection: " + e.getMessage());
            }
        }
    }
}
