#!/usr/bin/env python3
"""
Security test suite for Oracle MCP Server fixes.
Tests all vulnerabilities identified by security review.
"""

import sys
import re
from query_validator import QueryValidator

def test_union_blocking():
    """Test that UNION and UNION ALL are blocked."""
    print("\n=== Testing UNION Blocking ===")
    validator = QueryValidator()

    tests = [
        ("SELECT * FROM users UNION SELECT * FROM passwords", False, "UNION injection"),
        ("SELECT * FROM users UNION ALL SELECT * FROM passwords", False, "UNION ALL injection"),
        ("SELECT * FROM users WHERE name = 'test'", True, "Normal query"),
    ]

    passed = 0
    for query, should_pass, description in tests:
        result = validator.validate(query)
        if result.is_safe == should_pass:
            print(f"✅ PASS: {description}")
            passed += 1
        else:
            print(f"❌ FAIL: {description}")
            print(f"   Query: {query[:50]}...")
            print(f"   Expected safe={should_pass}, got safe={result.is_safe}")
            if result.error_message:
                print(f"   Error: {result.error_message}")

    return passed, len(tests)


def test_comment_stripping():
    """Test that SQL comments are stripped before validation."""
    print("\n=== Testing Comment Stripping ===")
    validator = QueryValidator()

    tests = [
        ("SELECT * FROM users -- DELETE FROM users", True, "Single-line comment bypass attempt"),
        ("SELECT * FROM users /* DELETE FROM users */", True, "Multi-line comment bypass attempt"),
        ("SELECT * FROM users WHERE /* ROWNUM */ 1=1", True, "ROWNUM in comment bypass attempt"),
        ("SELECT * /* comment */ FROM users WHERE id = 1", True, "Inline comment"),
    ]

    passed = 0
    for query, should_pass, description in tests:
        result = validator.validate(query)
        if result.is_safe == should_pass:
            print(f"✅ PASS: {description}")
            passed += 1
        else:
            print(f"❌ FAIL: {description}")
            print(f"   Query: {query[:50]}...")
            print(f"   Expected safe={should_pass}, got safe={result.is_safe}")

    return passed, len(tests)


def test_rownum_bypass_fix():
    """Test that ROWNUM bypass is properly detected."""
    print("\n=== Testing ROWNUM Bypass Fix ===")
    validator = QueryValidator()

    # Queries that already have ROWNUM should not be wrapped
    tests = [
        ("SELECT * FROM users WHERE ROWNUM <= 100", False),  # Should NOT wrap
        ("SELECT * FROM users WHERE id = 1 AND ROWNUM < 50", False),  # Should NOT wrap
        ("SELECT * FROM users WHERE id = 1", True),  # Should wrap
        ("SELECT * FROM (SELECT * FROM users) WHERE ROWNUM <= 10", False),  # Should NOT wrap
    ]

    passed = 0
    for query, should_wrap in tests:
        wrapped = validator.wrap_with_row_limit(query)
        was_wrapped = wrapped != query.strip()

        if was_wrapped == should_wrap:
            print(f"✅ PASS: {'Wrapped' if should_wrap else 'Not wrapped'}: {query[:50]}...")
            passed += 1
        else:
            print(f"❌ FAIL: Expected {'wrap' if should_wrap else 'no wrap'}: {query[:50]}...")
            print(f"   Original: {query[:80]}")
            print(f"   Result:   {wrapped[:80]}")

    return passed, len(tests)


def validate_identifier(identifier: str, max_length: int = 30) -> bool:
    """
    Validate database identifier (table name, schema name, etc.).
    Copied from oracle_mcp_server.py to avoid MCP dependency.
    """
    if not identifier:
        return False

    if len(identifier) > max_length:
        return False

    if not re.match(r'^[A-Za-z][A-Za-z0-9_$#]*$', identifier):
        return False

    return True


def test_identifier_validation():
    """Test that table/schema name validation prevents SQL injection."""
    print("\n=== Testing Identifier Validation ===")

    tests = [
        ("USERS", True, "Normal table name"),
        ("MY_TABLE", True, "Table name with underscore"),
        ("TABLE123", True, "Table name with numbers"),
        ("TABLE$NAME", True, "Table name with $"),
        ("TABLE#NAME", True, "Table name with #"),
        ("USERS' OR '1'='1", False, "SQL injection attempt"),
        ("USERS; DROP TABLE USERS;--", False, "SQL injection with DROP"),
        ("USERS UNION SELECT", False, "SQL injection with UNION"),
        ("", False, "Empty string"),
        ("A" * 31, False, "Too long (>30 chars)"),
        ("123TABLE", False, "Starts with number"),
        ("TABLE NAME", False, "Contains space"),
        ("TABLE-NAME", False, "Contains dash"),
    ]

    passed = 0
    for identifier, should_pass, description in tests:
        result = validate_identifier(identifier)
        if result == should_pass:
            print(f"✅ PASS: {description}")
            passed += 1
        else:
            print(f"❌ FAIL: {description}")
            print(f"   Identifier: '{identifier}'")
            print(f"   Expected valid={should_pass}, got valid={result}")

    return passed, len(tests)


def test_credentials_not_in_process():
    """Test that credentials are passed via environment, not command line."""
    print("\n=== Testing Credentials Not in Process Listing ===")

    # Read the Java file to verify it uses environment variables
    with open('/Users/rvillucci/dev/oracle-mcp-sdm-with-guardrails/OracleQuery.java', 'r') as f:
        java_content = f.read()

    # Read the Python file to verify it passes credentials via environment
    with open('/Users/rvillucci/dev/oracle-mcp-sdm-with-guardrails/oracle_jdbc.py', 'r') as f:
        python_content = f.read()

    passed = 0
    total = 3

    # Check Java uses System.getenv for credentials
    if 'System.getenv("ORACLE_USER")' in java_content and 'System.getenv("ORACLE_PASSWORD")' in java_content:
        print("✅ PASS: Java code uses environment variables for credentials")
        passed += 1
    else:
        print("❌ FAIL: Java code does not use environment variables")

    # Check Java does NOT accept credentials from command line
    if 'args[2]' not in java_content and 'args[3]' not in java_content:
        print("✅ PASS: Java code does not accept credentials from command line")
        passed += 1
    else:
        print("❌ FAIL: Java code still accepts credentials from command line")

    # Check Python passes credentials via environment
    if "env['ORACLE_USER']" in python_content and "env['ORACLE_PASSWORD']" in python_content:
        print("✅ PASS: Python code passes credentials via environment")
        passed += 1
    else:
        print("❌ FAIL: Python code does not pass credentials via environment")

    return passed, total


def main():
    """Run all security tests."""
    print("=" * 60)
    print("Oracle MCP Server Security Test Suite")
    print("Testing fixes for identified vulnerabilities")
    print("=" * 60)

    all_passed = 0
    all_total = 0

    # Run all tests
    passed, total = test_union_blocking()
    all_passed += passed
    all_total += total

    passed, total = test_comment_stripping()
    all_passed += passed
    all_total += total

    passed, total = test_rownum_bypass_fix()
    all_passed += passed
    all_total += total

    passed, total = test_identifier_validation()
    all_passed += passed
    all_total += total

    passed, total = test_credentials_not_in_process()
    all_passed += passed
    all_total += total

    # Print summary
    print("\n" + "=" * 60)
    print(f"SUMMARY: {all_passed}/{all_total} tests passed")
    if all_passed == all_total:
        print("✅ All security fixes validated!")
    else:
        print(f"❌ {all_total - all_passed} tests failed")
    print("=" * 60)

    return 0 if all_passed == all_total else 1


if __name__ == "__main__":
    sys.exit(main())
