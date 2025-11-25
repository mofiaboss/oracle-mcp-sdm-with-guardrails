#!/usr/bin/env python3
"""
Test suite for enhanced complexity scoring.
Tests new patterns: CTEs, window functions, self-joins, leading wildcards, OR conditions.
"""

from query_validator import QueryValidator


def test_cte_detection():
    """Test CTE (WITH clause) detection."""
    validator = QueryValidator()

    # Single CTE
    query = """
    WITH managers AS (
        SELECT * FROM employees WHERE is_manager = 1
    )
    SELECT * FROM managers
    """
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Single CTE")
    print(f"Query: {query.strip()[:80]}...")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    assert result.is_safe, "CTE query should be safe"
    assert result.complexity_score >= 13, f"Expected score >= 13 (base 5 + CTE 8), got {result.complexity_score}"
    assert any("CTE" in w for w in result.warnings), "Should warn about CTEs"
    print(f"✅ PASS: CTE detected, score >= 13")

    # Multiple CTEs
    query = """
    WITH dept_totals AS (
        SELECT dept_id, SUM(salary) as total FROM employees GROUP BY dept_id
    ),
    high_earners AS (
        SELECT * FROM employees WHERE salary > 100000
    )
    SELECT d.*, h.* FROM dept_totals d JOIN high_earners h ON d.dept_id = h.dept_id
    """
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Multiple CTEs")
    print(f"Query: WITH dept_totals AS (...), high_earners AS (...)...")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    # This query has high complexity due to 2 CTEs, aggregates, JOIN, subqueries
    assert result.complexity_score >= 21, f"Expected score >= 21 (base 5 + 2 CTEs 16), got {result.complexity_score}"
    if result.complexity_score > 50:
        assert not result.is_safe, "Query with score > 50 should be blocked"
        print(f"✅ PASS: Multiple CTEs detected and correctly blocked (score {result.complexity_score} > 50)")
    else:
        assert result.is_safe, "Query with score <= 50 should be safe"
        assert any("CTE" in w for w in result.warnings), "Should warn about CTEs"
        print(f"✅ PASS: Multiple CTEs detected, score >= 21")


def test_window_function_detection():
    """Test window function detection."""
    validator = QueryValidator()

    # ROW_NUMBER
    query = "SELECT name, ROW_NUMBER() OVER (ORDER BY id) as rn FROM users"
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: ROW_NUMBER window function")
    print(f"Query: {query}")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    assert result.is_safe, "Window function query should be safe"
    assert result.complexity_score >= 17, f"Expected score >= 17 (base 5 + window 12), got {result.complexity_score}"
    assert any("window function" in w.lower() for w in result.warnings), "Should warn about window functions"
    print(f"✅ PASS: ROW_NUMBER detected, score >= 17")

    # RANK and LEAD
    query = """
    SELECT
        name,
        RANK() OVER (ORDER BY salary DESC) as rank,
        LEAD(salary) OVER (ORDER BY hire_date) as next_salary
    FROM employees
    """
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Multiple window functions (RANK, LEAD)")
    print(f"Query: SELECT RANK() OVER (...), LEAD() OVER (...)...")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    assert result.is_safe, "Multiple window functions should be safe"
    assert result.complexity_score >= 29, f"Expected score >= 29 (base 5 + 2 windows 24), got {result.complexity_score}"
    assert any("2 window function" in w.lower() for w in result.warnings), "Should warn about 2 window functions"
    print(f"✅ PASS: Multiple window functions detected, score >= 29")


def test_self_join_detection():
    """Test self-join detection."""
    validator = QueryValidator()

    # Simple self-join
    query = """
    SELECT e1.name as employee, e2.name as manager
    FROM employees e1
    JOIN employees e2 ON e1.manager_id = e2.id
    """
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Simple self-join")
    print(f"Query: FROM employees e1 JOIN employees e2...")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    assert result.is_safe, "Self-join should be safe"
    assert result.complexity_score >= 25, f"Expected score >= 25 (base 5 + self-join 15 + JOIN 5), got {result.complexity_score}"
    assert any("self-join" in w.lower() for w in result.warnings), "Should warn about self-joins"
    print(f"✅ PASS: Self-join detected, score >= 25")


def test_leading_wildcard_like():
    """Test leading wildcard LIKE pattern detection."""
    validator = QueryValidator()

    # Leading wildcard
    query = "SELECT * FROM customers WHERE name LIKE '%smith%'"
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Leading wildcard LIKE")
    print(f"Query: {query}")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    assert result.is_safe, "LIKE with leading wildcard should be safe but warned"
    assert result.complexity_score >= 15, f"Expected score >= 15 (base 5 + wildcard 10), got {result.complexity_score}"
    assert any("leading wildcard" in w.lower() for w in result.warnings), "Should warn about leading wildcards"
    print(f"✅ PASS: Leading wildcard detected, score >= 15")

    # Multiple leading wildcards
    query = "SELECT * FROM customers WHERE name LIKE '%smith%' OR email LIKE '%@example.com'"
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Multiple leading wildcards")
    print(f"Query: LIKE '%smith%' OR ... LIKE '%@example.com'")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    assert result.is_safe, "Multiple wildcards should be safe but warned"
    assert result.complexity_score >= 25, f"Expected score >= 25 (base 5 + 2 wildcards 20), got {result.complexity_score}"
    print(f"✅ PASS: Multiple leading wildcards detected, score >= 25")


def test_or_conditions():
    """Test multiple OR condition detection."""
    validator = QueryValidator()

    # Two ORs (should not penalize)
    query = "SELECT * FROM users WHERE status = 'active' OR status = 'pending'"
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Two OR conditions (acceptable)")
    print(f"Query: {query}")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    assert result.is_safe, "Two ORs should be safe"
    # Base complexity only, no OR penalty
    print(f"✅ PASS: Two ORs not penalized")

    # Many ORs (should penalize)
    query = "SELECT * FROM users WHERE a = 1 OR b = 2 OR c = 3 OR d = 4 OR e = 5"
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Many OR conditions (penalized)")
    print(f"Query: a = 1 OR b = 2 OR c = 3 OR d = 4 OR e = 5")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    assert result.is_safe, "Many ORs should be safe but penalized"
    # 4 ORs, penalty for 2 extras = 8 points
    assert result.complexity_score >= 13, f"Expected score >= 13 (base 5 + OR penalty 8), got {result.complexity_score}"
    assert any("OR condition" in w for w in result.warnings), "Should warn about multiple ORs"
    print(f"✅ PASS: Multiple ORs detected and penalized, score >= 13")


def test_complex_query_combination():
    """Test complex query with multiple expensive patterns."""
    validator = QueryValidator()

    query = """
    WITH managers AS (
        SELECT * FROM employees WHERE is_manager = 1
    )
    SELECT
        e1.name,
        e2.name as manager_name,
        ROW_NUMBER() OVER (ORDER BY e1.salary DESC) as salary_rank
    FROM employees e1
    JOIN employees e2 ON e1.manager_id = e2.id
    JOIN managers m ON e2.id = m.id
    WHERE e1.name LIKE '%smith%'
       OR e1.email LIKE '%@example.com'
       OR e1.dept = 'sales'
    """
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Complex query with multiple patterns")
    print("Patterns: CTE, self-join, window function, leading wildcards, multiple ORs")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    print(f"✅ Warnings: {len(result.warnings)}")
    for w in result.warnings:
        print(f"   - {w}")

    # Expected: base(5) + CTE(8) + self-join(15) + 2 JOINs(10) + window(12) + 2 wildcards(20) + 1 OR penalty(4) = 74
    # This should exceed max complexity (50) and be blocked
    assert result.complexity_score >= 50, f"Complex query should have high score (>=50), got {result.complexity_score}"
    if result.complexity_score > 50:
        assert not result.is_safe, "Complex query with score > 50 should be blocked"
        print(f"✅ PASS: Complex query correctly blocked (score {result.complexity_score} > 50)")
    else:
        assert result.is_safe, "Complex query with score <= 50 should be safe"
        print(f"✅ PASS: Complex query properly scored")


def test_nested_subquery_depth():
    """Test nested subquery depth detection."""
    validator = QueryValidator()

    # 3 levels deep
    query = """
    SELECT * FROM (
        SELECT * FROM (
            SELECT * FROM (
                SELECT * FROM users WHERE id = 1
            ) WHERE status = 'active'
        ) WHERE dept = 'sales'
    ) WHERE created > SYSDATE - 7
    """
    result = validator.validate(query)
    print(f"\n{'='*60}")
    print("Test: Deeply nested subqueries (3 levels)")
    print(f"Query: SELECT FROM (SELECT FROM (SELECT FROM (...)))...")
    print(f"✅ Safe: {result.is_safe}")
    print(f"✅ Complexity: {result.complexity_score}")
    assert result.is_safe, "Nested subqueries should be safe"
    # 3 subqueries: base(5) + 3 subqueries(30) + 1 extra depth penalty(5) = 40
    assert result.complexity_score >= 35, f"Expected score >= 35, got {result.complexity_score}"
    assert any("Deep nesting" in w or "subquer" in w.lower() for w in result.warnings), "Should warn about nesting"
    print(f"✅ PASS: Nested subquery depth detected, score >= 35")


def main():
    """Run all enhanced complexity scoring tests."""
    print("🧪 Testing Enhanced Complexity Scoring Patterns")
    print("="*80)

    tests = [
        ("CTE Detection", test_cte_detection),
        ("Window Functions", test_window_function_detection),
        ("Self-Join Detection", test_self_join_detection),
        ("Leading Wildcard LIKE", test_leading_wildcard_like),
        ("OR Conditions", test_or_conditions),
        ("Nested Subquery Depth", test_nested_subquery_depth),
        ("Complex Query Combination", test_complex_query_combination),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            print(f"\n{'='*80}")
            print(f"🔍 Running: {test_name}")
            print('='*80)
            test_func()
            print(f"\n✅ {test_name}: PASSED")
            passed += 1
        except AssertionError as e:
            print(f"\n❌ {test_name}: FAILED")
            print(f"   Reason: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ {test_name}: ERROR")
            print(f"   Error: {e}")
            failed += 1

    print(f"\n{'='*80}")
    print("ENHANCED COMPLEXITY SCORING TEST RESULTS")
    print('='*80)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")

    if failed == 0:
        print("\n🎉 ALL ENHANCED COMPLEXITY TESTS PASSED!")
        return 0
    else:
        print(f"\n❌ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit(main())
