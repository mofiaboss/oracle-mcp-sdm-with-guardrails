#!/usr/bin/env python3
"""
Test suite for CircuitBreaker pattern.
Tests circuit breaker states: CLOSED, OPEN, HALF_OPEN transitions.
"""

import asyncio
import time


class CircuitBreaker:
    """
    Circuit breaker pattern to prevent hammering a failing database.
    States: CLOSED (normal), OPEN (failing), HALF_OPEN (testing recovery)
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60, success_threshold: int = 2):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures to open circuit
            recovery_timeout: Seconds to wait before attempting recovery
            success_threshold: Number of consecutive successes to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        # Circuit state
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        """
        Execute function through circuit breaker.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            RuntimeError: If circuit is open
        """
        async with self.lock:
            # Check circuit state
            if self.state == "OPEN":
                # Check if recovery timeout has elapsed
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    self.success_count = 0
                else:
                    # Circuit is open, reject request
                    remaining = int(self.recovery_timeout - (time.time() - self.last_failure_time))
                    raise RuntimeError(f"Circuit breaker is OPEN. Database appears to be down. Retry in {remaining} seconds.")

        # Execute function
        try:
            result = func(*args, **kwargs) if not asyncio.iscoroutinefunction(func) else await func(*args, **kwargs)

            # Success - update circuit state
            async with self.lock:
                self.failure_count = 0

                if self.state == "HALF_OPEN":
                    self.success_count += 1
                    if self.success_count >= self.success_threshold:
                        self.state = "CLOSED"
                        self.success_count = 0

            return result

        except Exception as e:
            # Failure - update circuit state
            async with self.lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                self.success_count = 0

                if self.state == "HALF_OPEN":
                    # Recovery attempt failed
                    self.state = "OPEN"
                elif self.failure_count >= self.failure_threshold:
                    # Threshold exceeded
                    self.state = "OPEN"

            raise

    def get_state(self) -> dict:
        """Get current circuit breaker state."""
        return {
            'state': self.state,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'last_failure_time': self.last_failure_time
        }


async def test_circuit_starts_closed():
    """Test that circuit breaker starts in CLOSED state."""
    print(f"\n{'='*60}")
    print("Test: Circuit Starts CLOSED")

    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=2, success_threshold=2)
    state = breaker.get_state()

    print(f"Initial state: {state['state']}")
    assert state['state'] == "CLOSED", "Circuit should start in CLOSED state"
    assert state['failure_count'] == 0, "Should have no failures initially"
    print("✅ PASS: Circuit starts in CLOSED state")


async def test_successful_calls():
    """Test that successful calls keep circuit CLOSED."""
    print(f"\n{'='*60}")
    print("Test: Successful Calls Keep Circuit CLOSED")

    breaker = CircuitBreaker(failure_threshold=3)

    def success_func():
        return "success"

    # Make multiple successful calls
    for i in range(5):
        result = await breaker.call(success_func)
        assert result == "success", f"Call {i+1} should succeed"

    state = breaker.get_state()
    print(f"State after 5 successes: {state['state']}")
    print(f"Failure count: {state['failure_count']}")

    assert state['state'] == "CLOSED", "Circuit should remain CLOSED after successes"
    assert state['failure_count'] == 0, "Failure count should be 0"
    print("✅ PASS: Successful calls keep circuit CLOSED")


async def test_circuit_opens_after_failures():
    """Test that circuit opens after threshold failures."""
    print(f"\n{'='*60}")
    print("Test: Circuit Opens After Threshold Failures")

    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=2)

    def failing_func():
        raise Exception("Database error")

    # Cause failures to open circuit
    for i in range(3):
        try:
            await breaker.call(failing_func)
        except Exception:
            print(f"Failure {i+1}/3")
            pass

    state = breaker.get_state()
    print(f"State after 3 failures: {state['state']}")
    print(f"Failure count: {state['failure_count']}")

    assert state['state'] == "OPEN", "Circuit should be OPEN after threshold failures"
    assert state['failure_count'] == 3, "Should have 3 failures"
    print("✅ PASS: Circuit opens after threshold failures")


async def test_circuit_rejects_when_open():
    """Test that circuit rejects requests when OPEN."""
    print(f"\n{'='*60}")
    print("Test: Circuit Rejects Requests When OPEN")

    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=2)

    def failing_func():
        raise Exception("Database error")

    # Open the circuit
    for i in range(2):
        try:
            await breaker.call(failing_func)
        except Exception:
            pass

    assert breaker.get_state()['state'] == "OPEN", "Circuit should be OPEN"

    # Try to make a call - should be rejected immediately
    try:
        await breaker.call(failing_func)
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        print(f"Rejected: {str(e)[:50]}...")
        assert "Circuit breaker is OPEN" in str(e), "Should have appropriate error message"

    print("✅ PASS: Circuit rejects requests when OPEN")


async def test_circuit_enters_half_open():
    """Test that circuit enters HALF_OPEN after recovery timeout."""
    print(f"\n{'='*60}")
    print("Test: Circuit Enters HALF_OPEN After Timeout")

    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1, success_threshold=2)

    def failing_func():
        raise Exception("Database error")

    # Open the circuit
    for i in range(2):
        try:
            await breaker.call(failing_func)
        except Exception:
            pass

    assert breaker.get_state()['state'] == "OPEN", "Circuit should be OPEN"
    print("Circuit OPEN, waiting 1.5 seconds for recovery timeout...")

    # Wait for recovery timeout
    await asyncio.sleep(1.5)

    # Try a call - should enter HALF_OPEN (but still fail)
    def still_failing():
        raise Exception("Still failing")

    try:
        await breaker.call(still_failing)
    except Exception:
        pass

    state = breaker.get_state()
    print(f"State after timeout: {state['state']}")
    assert state['state'] == "OPEN", "Should return to OPEN after failed recovery attempt"
    print("✅ PASS: Circuit enters HALF_OPEN after timeout")


async def test_circuit_closes_after_recovery():
    """Test that circuit closes after successful recovery."""
    print(f"\n{'='*60}")
    print("Test: Circuit Closes After Successful Recovery")

    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1, success_threshold=2)

    call_count = [0]

    def func_that_recovers():
        call_count[0] += 1
        if call_count[0] <= 2:
            raise Exception("Database error")
        return "success"

    # Open the circuit (2 failures)
    for i in range(2):
        try:
            await breaker.call(func_that_recovers)
        except Exception:
            pass

    assert breaker.get_state()['state'] == "OPEN", "Circuit should be OPEN"
    print("Circuit OPEN, waiting for recovery timeout...")

    # Wait for recovery timeout
    await asyncio.sleep(1.5)

    # Make successful calls to close circuit
    print("Making successful recovery attempts...")
    for i in range(3):
        try:
            result = await breaker.call(func_that_recovers)
            print(f"Recovery attempt {i+1}: {result}")
        except Exception as e:
            print(f"Recovery attempt {i+1}: failed - {e}")

    state = breaker.get_state()
    print(f"Final state: {state['state']}")
    print(f"Success count: {state['success_count']}")

    assert state['state'] == "CLOSED", "Circuit should be CLOSED after successful recovery"
    assert state['failure_count'] == 0, "Failure count should be reset"
    print("✅ PASS: Circuit closes after successful recovery")


async def test_failure_count_resets_on_success():
    """Test that failure count resets on successful call."""
    print(f"\n{'='*60}")
    print("Test: Failure Count Resets On Success")

    breaker = CircuitBreaker(failure_threshold=5)

    def alternating_func(should_fail):
        if should_fail:
            raise Exception("Error")
        return "success"

    # Make 2 failures
    for i in range(2):
        try:
            await breaker.call(alternating_func, True)
        except Exception:
            pass

    state1 = breaker.get_state()
    print(f"After 2 failures: {state1['failure_count']} failures")
    assert state1['failure_count'] == 2, "Should have 2 failures"

    # Make a successful call
    result = await breaker.call(alternating_func, False)
    assert result == "success"

    state2 = breaker.get_state()
    print(f"After 1 success: {state2['failure_count']} failures")
    assert state2['failure_count'] == 0, "Failure count should reset to 0"
    assert state2['state'] == "CLOSED", "Circuit should remain CLOSED"
    print("✅ PASS: Failure count resets on success")


async def test_get_state():
    """Test that get_state returns correct information."""
    print(f"\n{'='*60}")
    print("Test: Get State Returns Correct Info")

    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60, success_threshold=2)

    state = breaker.get_state()
    print(f"State keys: {list(state.keys())}")

    assert 'state' in state, "Should have 'state' key"
    assert 'failure_count' in state, "Should have 'failure_count' key"
    assert 'success_count' in state, "Should have 'success_count' key"
    assert 'last_failure_time' in state, "Should have 'last_failure_time' key"

    assert state['state'] == "CLOSED", "Initial state should be CLOSED"
    assert state['failure_count'] == 0, "Initial failure count should be 0"
    assert state['success_count'] == 0, "Initial success count should be 0"
    assert state['last_failure_time'] is None, "Should have no failure time initially"

    print("✅ PASS: get_state returns correct info")


async def main():
    """Run all circuit breaker tests."""
    print("🧪 Testing Circuit Breaker Pattern")
    print("="*80)

    tests = [
        ("Circuit Starts CLOSED", test_circuit_starts_closed),
        ("Successful Calls", test_successful_calls),
        ("Circuit Opens After Failures", test_circuit_opens_after_failures),
        ("Circuit Rejects When OPEN", test_circuit_rejects_when_open),
        ("Circuit Enters HALF_OPEN", test_circuit_enters_half_open),
        ("Circuit Closes After Recovery", test_circuit_closes_after_recovery),
        ("Failure Count Resets", test_failure_count_resets_on_success),
        ("Get State", test_get_state),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            print(f"\n{'='*80}")
            print(f"🔍 Running: {test_name}")
            print('='*80)
            await test_func()
            print(f"\n✅ {test_name}: PASSED")
            passed += 1
        except AssertionError as e:
            print(f"\n❌ {test_name}: FAILED")
            print(f"   Reason: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ {test_name}: ERROR")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*80}")
    print("CIRCUIT BREAKER TEST RESULTS")
    print('='*80)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")

    if failed == 0:
        print("\n🎉 ALL CIRCUIT BREAKER TESTS PASSED!")
        return 0
    else:
        print(f"\n❌ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
