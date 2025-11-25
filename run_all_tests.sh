#!/bin/bash
# Master test script to run all Oracle MCP test suites

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        ORACLE MCP SERVER - COMPREHENSIVE TEST SUITE           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

FAILED=0
PASSED=0

# Test 1: Safety and Preview Tests
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 TEST SUITE 1: Safety and Preview Tests"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 test_safety.py
if [ $? -eq 0 ]; then
    echo "✅ Safety and Preview Tests: PASSED"
    PASSED=$((PASSED+1))
else
    echo "❌ Safety and Preview Tests: FAILED"
    FAILED=$((FAILED+1))
fi
echo ""

# Test 2: Enhanced Complexity Scoring
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 TEST SUITE 2: Enhanced Complexity Scoring"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 test_complexity_scoring.py
if [ $? -eq 0 ]; then
    echo "✅ Complexity Scoring Tests: PASSED"
    PASSED=$((PASSED+1))
else
    echo "❌ Complexity Scoring Tests: FAILED"
    FAILED=$((FAILED+1))
fi
echo ""

# Test 3: Approval Workflow
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 TEST SUITE 3: Approval Workflow"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 test_approval_workflow.py
if [ $? -eq 0 ]; then
    echo "✅ Approval Workflow Tests: PASSED"
    PASSED=$((PASSED+1))
else
    echo "❌ Approval Workflow Tests: FAILED"
    FAILED=$((FAILED+1))
fi
echo ""

# Test 4: Circuit Breaker
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 TEST SUITE 4: Circuit Breaker Pattern"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 test_circuit_breaker.py
if [ $? -eq 0 ]; then
    echo "✅ Circuit Breaker Tests: PASSED"
    PASSED=$((PASSED+1))
else
    echo "❌ Circuit Breaker Tests: FAILED"
    FAILED=$((FAILED+1))
fi
echo ""

# Summary
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    FINAL TEST SUMMARY                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Test Suites Passed: $PASSED/4"
echo "Test Suites Failed: $FAILED/4"
echo ""

if [ $FAILED -eq 0 ]; then
    echo "🎉 ALL TEST SUITES PASSED!"
    echo "✅ System is production-ready"
    echo ""
    echo "Test Coverage:"
    echo "  ✓ Query validation (cartesian products, cross joins, write ops)"
    echo "  ✓ Complexity scoring (CTEs, window functions, self-joins, etc.)"
    echo "  ✓ Approval workflow (token generation, verification, expiry)"
    echo "  ✓ Circuit breaker (CLOSED, OPEN, HALF_OPEN states)"
    echo "  ✓ Row limiting"
    echo "  ✓ Preview functionality"
    exit 0
else
    echo "❌ $FAILED test suite(s) failed"
    echo "⚠️  System needs fixes before production deployment"
    exit 1
fi
