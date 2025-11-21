#!/usr/bin/env python3
"""
Oracle database connection using JDBC via subprocess.
Works through StrongDM proxy on Apple Silicon.
"""

import json
import subprocess
from typing import List, Dict, Any, Optional
from pathlib import Path

class OracleJDBC:
    """Oracle database connection using JDBC through Java subprocess."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 10006,
        service_name: str = "ylvoprd",
        user: str = "username",
        password: str = "password"
    ):
        """
        Initialize Oracle JDBC connection.

        Args:
            host: Database host (default: 127.0.0.1 for StrongDM)
            port: Database port (default: 10006 for StrongDM)
            service_name: Oracle service name
            user: Database user
            password: Database password
        """
        self.jdbc_url = f"jdbc:oracle:thin:@{host}:{port}/{service_name}"
        self.user = user
        self.password = password

        # Paths
        import os
        self.java_home = Path(os.getenv("JAVA_HOME", "/opt/homebrew/opt/openjdk@21"))
        self.java_bin = self.java_home / "bin" / "java"
        self.work_dir = Path(__file__).parent

        # Try to find JDBC jar in project directory first, then fall back to environment variable
        jdbc_jar_name = "ojdbc11-23.5.0.24.07.jar"
        jdbc_jar_local = self.work_dir / jdbc_jar_name

        if jdbc_jar_local.exists():
            self.jdbc_jar = jdbc_jar_local
        elif os.getenv("JDBC_JAR_PATH"):
            self.jdbc_jar = Path(os.getenv("JDBC_JAR_PATH"))
        else:
            # Fall back to DataGrip location (may not exist for all users)
            self.jdbc_jar = Path(
                f"{Path.home()}/Library/Application Support/JetBrains/"
                "DataGrip2024.3/jdbc-drivers/Oracle/23.5/"
                "com/oracle/database/jdbc/ojdbc11/23.5.0.24.07/"
                f"{jdbc_jar_name}"
            )

        self.json_jar = self.work_dir / "json.jar"

        # Validate paths
        if not self.java_bin.exists():
            raise FileNotFoundError(f"Java not found at {self.java_bin}")
        if not self.jdbc_jar.exists():
            raise FileNotFoundError(f"JDBC driver not found at {self.jdbc_jar}")
        if not self.json_jar.exists():
            raise FileNotFoundError(f"JSON library not found at {self.json_jar}")

    def execute(self, query: str) -> Dict[str, Any]:
        """
        Execute SQL query and return results.

        Args:
            query: SQL query to execute

        Returns:
            Dictionary with structure:
            {
                'success': bool,
                'rows': List[Dict[str, Any]],
                'count': int,
                'error': str (only if success=False)
            }

        Raises:
            subprocess.CalledProcessError: If Java process fails
            json.JSONDecodeError: If response is not valid JSON
        """
        # Build classpath
        classpath = f".:{self.json_jar}:{self.jdbc_jar}"

        # Run Java subprocess
        result = subprocess.run(
            [
                str(self.java_bin),
                "-cp", classpath,
                "OracleQuery",
                self.jdbc_url,
                self.user,
                self.password,
                query
            ],
            cwd=str(self.work_dir),
            capture_output=True,
            text=True,
            timeout=30
        )

        # Parse JSON response
        try:
            response = json.loads(result.stdout)
            return response
        except json.JSONDecodeError as e:
            # If JSON parsing fails, include raw output
            return {
                'success': False,
                'error': f"Invalid JSON response: {e}",
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """
        Execute SQL query and return rows only.

        Args:
            sql: SQL query to execute

        Returns:
            List of row dictionaries

        Raises:
            RuntimeError: If query fails
        """
        result = self.execute(sql)

        if not result.get('success'):
            error_msg = result.get('error', 'Unknown error')
            raise RuntimeError(f"Query failed: {error_msg}")

        return result.get('rows', [])

    def query_one(self, sql: str) -> Optional[Dict[str, Any]]:
        """
        Execute SQL query and return first row only.

        Args:
            sql: SQL query to execute

        Returns:
            First row dictionary, or None if no results

        Raises:
            RuntimeError: If query fails
        """
        rows = self.query(sql)
        return rows[0] if rows else None

    def test_connection(self) -> bool:
        """
        Test database connection.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            result = self.query_one("SELECT 'OK' as status FROM DUAL")
            return result is not None and result.get('STATUS') == 'OK'
        except Exception:
            return False


def main():
    """Test the Oracle JDBC connection."""
    print("Testing Oracle JDBC Connection")
    print("=" * 50)

    try:
        # Create connection
        db = OracleJDBC()
        print(f"JDBC URL: {db.jdbc_url}")

        # Test connection
        print("\nTesting connection...")
        if db.test_connection():
            print("✅ Connection successful!")
        else:
            print("❌ Connection failed")
            return

        # Run sample query
        print("\nRunning sample query...")
        result = db.execute("SELECT SYSDATE as current_time FROM DUAL")
        print(f"Success: {result['success']}")
        print(f"Row count: {result['count']}")
        print(f"Results: {json.dumps(result['rows'], indent=2)}")

        # Test query helper
        print("\nTesting query helper...")
        rows = db.query("SELECT 'Test 1' as col1, 'Test 2' as col2 FROM DUAL")
        print(f"Rows: {rows}")

        # Test query_one helper
        print("\nTesting query_one helper...")
        row = db.query_one("SELECT USER as current_user FROM DUAL")
        print(f"Current user: {row}")

        print("\n🎉 All tests passed! Oracle JDBC connection working through StrongDM.")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
