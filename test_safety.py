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


def test_preview_query():
    """Test the preview_query functionality."""
    print("\n" + "=" * 80)
    print("PREVIEW_QUERY FUNCTIONALITY TESTS")
    print("=" * 80)

    validator = QueryValidator(
        max_complexity=50,
        max_rows=10000,
        allow_cross_joins=False
    )

    # Test cases: (query, expected_safe, expected_complexity_range, description)
    test_cases = [
        # Safe queries
        ("SELECT * FROM users WHERE id = 123", True, (5, 10), "Simple safe query"),
        ("SELECT COUNT(*) FROM orders", True, (5, 10), "Aggregate query"),
        ("SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = 'PENDING'", True, (10, 20), "Proper join"),

        # Unsafe queries
        ("SELECT * FROM orders, customers", False, (0, 100), "Cartesian product"),
        ("DELETE FROM users WHERE id = 1", False, (0, 100), "Write operation"),
        ("SELECT * FROM users CROSS JOIN orders", False, (0, 100), "Cross join"),
    ]

    passed = 0
    failed = 0

    for query, expected_safe, (min_score, max_score), description in test_cases:
        print(f"\n{'='*60}")
        print(f"Test: {description}")
        print(f"Query: {query[:70]}...")

        # Simulate preview_query logic
        validation = validator.validate(query)
        safe_query = validator.wrap_with_row_limit(query)
        row_limit_applied = safe_query != query

        # Build preview response (mimics oracle_mcp_server.py preview_query)
        preview_response = {
            "preview_mode": True,
            "query_to_execute": query,
            "safe_query_with_limit": safe_query if row_limit_applied else None,
            "validation": {
                "is_safe": validation.is_safe,
                "complexity_score": validation.complexity_score,
                "max_complexity": validator.max_complexity,
                "complexity_explanation": "Lower is simpler. Score based on: JOINs (+5 each), subqueries (+3 each), GROUP BY (+2), aggregates (+1 each)",
                "warnings": validation.warnings if validation.warnings else [],
                "error_message": validation.error_message if not validation.is_safe else None
            },
            "safety_limits": {
                "max_rows": validator.max_rows,
                "row_limit_will_be_applied": row_limit_applied,
                "allow_cross_joins": validator.allow_cross_joins
            },
            "next_steps": "If query is safe and you approve, call query_oracle with the same query to execute it."
        }

        # Verify response structure
        test_results = []

        # Test 1: Response has all required keys
        required_keys = ["preview_mode", "query_to_execute", "validation", "safety_limits", "next_steps"]
        has_all_keys = all(key in preview_response for key in required_keys)
        test_results.append(("Required keys present", has_all_keys))

        # Test 2: Safety assessment matches expectation
        safety_matches = preview_response["validation"]["is_safe"] == expected_safe
        test_results.append(("Safety assessment correct", safety_matches))

        # Test 3: Complexity score is in expected range
        complexity = preview_response["validation"]["complexity_score"]
        complexity_in_range = min_score <= complexity <= max_score
        test_results.append(("Complexity score reasonable", complexity_in_range))

        # Test 4: Preview mode flag is set
        preview_mode_set = preview_response["preview_mode"] == True
        test_results.append(("Preview mode flag set", preview_mode_set))

        # Test 5: Validation structure is complete
        validation_keys = ["is_safe", "complexity_score", "max_complexity", "complexity_explanation", "warnings", "error_message"]
        validation_complete = all(key in preview_response["validation"] for key in validation_keys)
        test_results.append(("Validation structure complete", validation_complete))

        # Print results
        all_passed = all(result[1] for result in test_results)

        if all_passed:
            print("✅ PASS: Preview response correct")
            passed += 1
        else:
            print("❌ FAIL: Preview response incorrect")
            failed += 1

        for test_name, result in test_results:
            status = "✅" if result else "❌"
            print(f"  {status} {test_name}")

        # Print preview details
        print(f"\n  Preview Details:")
        print(f"    Is Safe: {preview_response['validation']['is_safe']}")
        print(f"    Complexity: {complexity}/{validator.max_complexity}")
        if preview_response['validation']['warnings']:
            print(f"    Warnings: {len(preview_response['validation']['warnings'])}")
        if preview_response['validation']['error_message']:
            print(f"    Error: {preview_response['validation']['error_message'][:60]}...")
        print(f"    Row Limit Applied: {row_limit_applied}")

    print("\n" + "=" * 80)
    print(f"PREVIEW TESTS: {passed} passed, {failed} failed")
    print("=" * 80)

    return failed == 0


if __name__ == "__main__":
    # Run all tests
    print("\n🧪 Starting Oracle MCP Safety Test Suite\n")

    safety_passed = test_dangerous_queries()
    test_row_limiting()
    preview_passed = test_preview_query()

    # Summary
    print("\n" + "=" * 80)
    print("FINAL TEST SUMMARY")
    print("=" * 80)
    print(f"Safety Tests:  {'✅ PASSED' if safety_passed else '❌ FAILED'}")
    print(f"Preview Tests: {'✅ PASSED' if preview_passed else '❌ FAILED'}")

    all_passed = safety_passed and preview_passed

    if all_passed:
        print("\n🎉 ALL TEST SUITES PASSED!")
        print("Your Oracle MCP is production-ready with preview functionality.")
    else:
        print("\n⚠️  SOME TESTS FAILED!")
        print("Review the failures above and fix before deploying.")

    print("=" * 80)

    # Exit with appropriate code
    exit(0 if all_passed else 1)
