import java.sql.*;
import org.json.JSONObject;
import org.json.JSONArray;

public class OracleQuery {
    public static void main(String[] args) {
        if (args.length < 4) {
            System.err.println("Usage: java OracleQuery <url> <user> <password> <query>");
            System.exit(1);
        }

        String url = args[0];
        String user = args[1];
        String password = args[2];
        String query = args[3];

        Connection conn = null;
        Statement stmt = null;
        ResultSet rs = null;

        try {
            // Load Oracle JDBC driver
            Class.forName("oracle.jdbc.driver.OracleDriver");

            // Connect to database
            conn = DriverManager.getConnection(url, user, password);

            // Execute query
            stmt = conn.createStatement();
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

        } catch (Exception e) {
            JSONObject error = new JSONObject();
            error.put("success", false);
            error.put("error", e.getMessage());
            System.out.println(error.toString());
            System.exit(1);
        } finally {
            try {
                if (rs != null) rs.close();
                if (stmt != null) stmt.close();
                if (conn != null) conn.close();
            } catch (SQLException e) {
                // Ignore
            }
        }
    }
}
