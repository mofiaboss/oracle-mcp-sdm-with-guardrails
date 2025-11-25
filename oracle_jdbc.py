#!/usr/bin/env python3
"""
Oracle database connection using JDBC via subprocess.
Works through StrongDM proxy on Apple Silicon.
Implements connection pooling with maximum 2 concurrent connections.
"""

import json
import logging
import os
import subprocess
import threading
import time
import queue
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

# Set up logging
logger = logging.getLogger(__name__)


class Connection:
    """Represents a single connection to Oracle via long-lived Java subprocess."""

    def __init__(self, connection_id: int, java_bin: Path, classpath: str, jdbc_url: str, work_dir: Path, env: dict):
        """
        Initialize a connection.

        Args:
            connection_id: Unique identifier for this connection
            java_bin: Path to Java binary
            classpath: Java classpath
            jdbc_url: JDBC connection URL
            work_dir: Working directory for subprocess
            env: Environment variables (including credentials)
        """
        self.connection_id = connection_id
        self.java_bin = java_bin
        self.classpath = classpath
        self.jdbc_url = jdbc_url
        self.work_dir = work_dir
        self.env = env
        self.process = None
        self.lock = threading.Lock()
        self.is_busy = False
        self.last_used = time.time()
        self.start_time = None

    def start(self):
        """Start the Java subprocess."""
        if self.process is not None:
            logger.warning(f"Connection {self.connection_id} already started")
            return

        logger.info(f"Starting connection {self.connection_id}")
        self.process = subprocess.Popen(
            [
                str(self.java_bin),
                "-cp", self.classpath,
                "OracleQueryServer",
                self.jdbc_url
            ],
            cwd=str(self.work_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
            env=self.env
        )
        self.start_time = time.time()

        # Wait for ready signal
        try:
            ready_line = self.process.stdout.readline()
            ready_response = json.loads(ready_line)
            if ready_response.get('status') == 'ready':
                logger.info(f"Connection {self.connection_id} ready: {ready_response.get('message')}")
            else:
                raise RuntimeError(f"Unexpected ready response: {ready_response}")
        except Exception as e:
            logger.error(f"Failed to start connection {self.connection_id}: {e}")
            self.stop()
            raise

    def execute(self, query: str, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Execute query on this connection.

        Args:
            query: SQL query to execute
            timeout: Query timeout in seconds

        Returns:
            Query result dictionary
        """
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError(f"Connection {self.connection_id} is not running")

            self.is_busy = True
            try:
                # Send query
                self.process.stdin.write(query + "\n")
                self.process.stdin.flush()

                # Read response with timeout
                start_time = time.time()
                result_line = None

                while True:
                    if time.time() - start_time > timeout:
                        raise TimeoutError(f"Query timeout after {timeout}s")

                    # Try to read line with small timeout
                    if self.process.stdout in []:
                        time.sleep(0.1)
                        continue

                    result_line = self.process.stdout.readline()
                    if result_line:
                        break

                    if self.process.poll() is not None:
                        raise RuntimeError(f"Connection {self.connection_id} died unexpectedly")

                    time.sleep(0.1)

                # Parse response
                response = json.loads(result_line)
                self.last_used = time.time()
                return response

            except Exception as e:
                logger.error(f"Query execution failed on connection {self.connection_id}: {e}")
                return {
                    'success': False,
                    'error': f"Connection error: {str(e)}"
                }
            finally:
                self.is_busy = False

    def ping(self) -> bool:
        """
        Check if connection is alive.

        Returns:
            True if alive, False otherwise
        """
        try:
            with self.lock:
                if self.process is None or self.process.poll() is not None:
                    return False

                self.process.stdin.write("PING\n")
                self.process.stdin.flush()

                response_line = self.process.stdout.readline()
                response = json.loads(response_line)

                return response.get('status') == 'alive' and response.get('connected', False)
        except Exception as e:
            logger.error(f"Ping failed on connection {self.connection_id}: {e}")
            return False

    def stop(self):
        """Stop the Java subprocess."""
        if self.process is None:
            return

        logger.info(f"Stopping connection {self.connection_id}")
        try:
            # Send EXIT command
            self.process.stdin.write("EXIT\n")
            self.process.stdin.flush()

            # Wait for graceful shutdown
            self.process.wait(timeout=2)
        except Exception:
            # Force kill if graceful shutdown fails
            self.process.kill()
        finally:
            self.process = None

    def is_alive(self) -> bool:
        """Check if subprocess is running."""
        return self.process is not None and self.process.poll() is None


class ConnectionPool:
    """
    Manages a pool of Oracle database connections with maximum 2 concurrent connections.
    Implements connection pooling with health checks and automatic reconnection.
    """

    def __init__(self, jdbc_url: str, user: str, password: str, java_bin: Path, classpath: str, work_dir: Path):
        """
        Initialize connection pool.

        Args:
            jdbc_url: JDBC connection URL
            user: Database user
            password: Database password
            java_bin: Path to Java binary
            classpath: Java classpath
            work_dir: Working directory for subprocesses
        """
        self.jdbc_url = jdbc_url
        self.user = user
        self.password = password
        self.java_bin = java_bin
        self.classpath = classpath
        self.work_dir = work_dir

        # Environment with credentials
        self.env = os.environ.copy()
        self.env['ORACLE_USER'] = user
        self.env['ORACLE_PASSWORD'] = password

        # Pool configuration
        self.max_connections = 2
        self.connections: List[Connection] = []
        self.pool_lock = threading.Lock()
        self.query_queue = queue.Queue()

        # Initialize connections
        self._initialize_pool()

        logger.info(f"Connection pool initialized with {self.max_connections} connections")

    def _initialize_pool(self):
        """Initialize the connection pool with 2 connections."""
        for i in range(self.max_connections):
            conn = Connection(
                connection_id=i,
                java_bin=self.java_bin,
                classpath=self.classpath,
                jdbc_url=self.jdbc_url,
                work_dir=self.work_dir,
                env=self.env
            )
            try:
                conn.start()
                self.connections.append(conn)
            except Exception as e:
                logger.error(f"Failed to start connection {i}: {e}")
                raise

    def execute(self, query: str, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Execute query using an available connection from the pool.

        Args:
            query: SQL query to execute
            timeout: Query timeout in seconds

        Returns:
            Query result dictionary
        """
        # Wait for available connection
        max_wait_time = 30.0  # 30 seconds max wait for connection
        start_wait = time.time()

        while True:
            # Find available connection
            with self.pool_lock:
                for conn in self.connections:
                    if not conn.is_busy and conn.is_alive():
                        try:
                            result = conn.execute(query, timeout)
                            return result
                        except Exception as e:
                            logger.error(f"Connection {conn.connection_id} failed: {e}")
                            # Try to restart connection
                            conn.stop()
                            conn.start()
                            continue

            # Check if we've exceeded max wait time
            if time.time() - start_wait > max_wait_time:
                return {
                    'success': False,
                    'error': f"No available connections after {max_wait_time}s"
                }

            # Wait a bit before retrying
            time.sleep(0.1)

    def health_check(self) -> Dict[str, Any]:
        """
        Check health of all connections in the pool.

        Returns:
            Health status dictionary
        """
        with self.pool_lock:
            healthy = 0
            unhealthy = 0

            for conn in self.connections:
                if conn.ping():
                    healthy += 1
                else:
                    unhealthy += 1
                    logger.warning(f"Connection {conn.connection_id} is unhealthy")

            return {
                'total_connections': len(self.connections),
                'healthy': healthy,
                'unhealthy': unhealthy,
                'all_healthy': unhealthy == 0
            }

    def shutdown(self):
        """Shutdown all connections in the pool."""
        logger.info("Shutting down connection pool")
        with self.pool_lock:
            for conn in self.connections:
                conn.stop()
        logger.info("Connection pool shutdown complete")


class OracleJDBC:
    """Oracle database connection using JDBC through Java subprocess with connection pooling."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 10006,
        service_name: str = "ylvoprd",
        user: str = "username",
        password: str = "password"
    ):
        """
        Initialize Oracle JDBC connection with connection pooling.

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

        # Build classpath
        classpath = f".:{self.json_jar}:{self.jdbc_jar}"

        # Initialize connection pool with 2 max connections
        self.pool = ConnectionPool(
            jdbc_url=self.jdbc_url,
            user=user,
            password=password,
            java_bin=self.java_bin,
            classpath=classpath,
            work_dir=self.work_dir
        )

        logger.info("OracleJDBC initialized with connection pooling (max 2 connections)")

    def execute(self, query: str) -> Dict[str, Any]:
        """
        Execute SQL query using connection pool and return results.

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
        """
        # Use connection pool to execute query
        return self.pool.execute(query, timeout=5.0)

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
        Test database connection using connection pool.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            result = self.query_one("SELECT 'OK' as status FROM DUAL")
            return result is not None and result.get('STATUS') == 'OK'
        except Exception:
            return False

    def pool_health(self) -> Dict[str, Any]:
        """
        Get connection pool health status.

        Returns:
            Dictionary with pool health information
        """
        return self.pool.health_check()

    def shutdown(self):
        """Shutdown connection pool and cleanup resources."""
        self.pool.shutdown()


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
