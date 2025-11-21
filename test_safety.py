#!/usr/bin/env python3
"""
Integration test for Oracle MCP safety features.
Tests dangerous queries to ensure they are blocked.
"""

from query_validator import QueryValidator
import json


def test_dangerous_queries():
    """Test that dangerous queries are properly blocked."""

    validator = QueryValidator(
        max_complexity=50,
        max_rows=10000,
        allow_cross_joins=False
    )

    # Test cases: (query, should_be_blocked, reason)
    test_cases = [
        # SHOULD BE BLOCKED
        ("SELECT * FROM orders, customers", True, "Implicit cartesian product"),
        ("SELECT * FROM users CROSS JOIN orders", True, "Explicit cross join"),
        ("SELECT * FROM t1, t2, t3, t4", True, "Too many comma-separated tables"),
        ("DELETE FROM users WHERE id = 1", True, "Write operation"),
        ("DROP TABLE users", True, "Destructive operation"),
        ("UPDATE users SET name = 'test'", True, "Write operation"),
        ("INSERT INTO users VALUES (1, 'test')", True, "Write operation"),
        ("TRUNCATE TABLE users", True, "Destructive operation"),

        # SHOULD BE ALLOWED (with warnings)
        ("SELECT * FROM users WHERE id = 123", False, "Simple safe query"),
        ("SELECT COUNT(*) FROM orders", False, "Aggregate query"),
        ("SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = 'PENDING'", False, "Proper join with WHERE"),
        ("SELECT SYSDATE FROM DUAL", False, "System query"),
        ("SELECT name, email FROM customers WHERE created_date > SYSDATE - 7", False, "Simple filtered query"),
    ]

    print("=" * 80)
    print("ORACLE MCP SAFETY TEST RESULTS")
    print("=" * 80)

    passed = 0
    failed = 0

    for query, should_block, reason in test_cases:
        print(f"\nTest: {reason}")
        print(f"Query: {query[:70]}...")

        result = validator.validate(query)

        # Check if result matches expectation
        if should_block:
            if not result.is_safe:
                print("✅ PASS: Query correctly blocked")
                print(f"   Reason: {result.error_message}")
                passed += 1
            else:
                print("❌ FAIL: Query should have been blocked but was allowed!")
                failed += 1
        else:
            if result.is_safe:
                print("✅ PASS: Query correctly allowed")
                if result.warnings:
                    print(f"   Warnings: {', '.join(result.warnings[:2])}")
                print(f"   Complexity: {result.complexity_score}")
                passed += 1
            else:
                print("❌ FAIL: Safe query was incorrectly blocked!")
                print(f"   Reason: {result.error_message}")
                failed += 1

    print("\n" + "=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 80)

    if failed == 0:
        print("🎉 ALL TESTS PASSED! Your database is protected.")
        return True
    else:
        print("⚠️  SOME TESTS FAILED! Review the validator configuration.")
        return False


def test_row_limiting():
    """Test that row limiting works correctly."""
    print("\n" + "=" * 80)
    print("ROW LIMITING TESTS")
    print("=" * 80)

    validator = QueryValidator(max_rows=1000)

    test_queries = [
        "SELECT * FROM users WHERE id = 123",
        "SELECT * FROM users WHERE id = 123 ORDER BY name",
        "SELECT * FROM users WHERE id = 123 AND ROWNUM <= 5",
    ]

    for query in test_queries:
        print(f"\nOriginal: {query}")
        wrapped = validator.wrap_with_row_limit(query)
        print(f"Wrapped:  {wrapped[:100]}...")

        if 'ROWNUM' in wrapped.upper():
            print("✅ Row limit applied")
        else:
            print("ℹ️  Row limit already present or not needed")


if __name__ == "__main__":
    # Run tests
    success = test_dangerous_queries()
    test_row_limiting()

    # Exit with appropriate code
    exit(0 if success else 1)
