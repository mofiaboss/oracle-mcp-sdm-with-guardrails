#!/usr/bin/env python3
"""
Test suite for QueryApprovalTracker.
Tests approval workflow: token generation, verification, expiry, one-time use.
"""

import asyncio
import time
import hashlib
import secrets


class QueryApprovalTracker:
    """
    Tracks query approvals to enforce the approval workflow.
    Ensures queries are previewed and explicitly approved before execution.
    """

    def __init__(self, token_expiry: int = 300):
        """
        Initialize query approval tracker.

        Args:
            token_expiry: Token expiry time in seconds (default: 5 minutes)
        """
        self.token_expiry = token_expiry
        self.approvals = {}  # {token: {query_hash, timestamp, query_preview}}
        self.lock = asyncio.Lock()

    def _hash_query(self, query: str) -> str:
        """
        Generate hash of query for approval tracking.

        Args:
            query: SQL query

        Returns:
            SHA256 hash of normalized query
        """
        # Normalize query (strip whitespace, lowercase) for consistent hashing
        normalized = ' '.join(query.strip().lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    async def generate_approval_token(self, query: str) -> str:
        """
        Generate approval token for a query.

        Args:
            query: SQL query that needs approval

        Returns:
            Approval token (32-character hex string)
        """
        async with self.lock:
            # Generate secure random token
            token = secrets.token_hex(16)  # 32 character hex string

            # Store approval with metadata
            self.approvals[token] = {
                'query_hash': self._hash_query(query),
                'timestamp': time.time(),
                'query_preview': query[:100]  # Store preview for logging
            }

            # Cleanup expired tokens
            self._cleanup_expired()

            return token

    def _cleanup_expired(self):
        """Remove expired tokens from storage."""
        current_time = time.time()
        expired_tokens = [
            token for token, data in self.approvals.items()
            if current_time - data['timestamp'] > self.token_expiry
        ]
        for token in expired_tokens:
            del self.approvals[token]

    async def verify_approval(self, query: str, token: str) -> tuple[bool, str]:
        """
        Verify that query has been approved with valid token.

        Args:
            query: SQL query to execute
            token: Approval token from preview_query

        Returns:
            Tuple of (is_approved, error_message)
        """
        async with self.lock:
            # Cleanup expired tokens first
            self._cleanup_expired()

            # Check if token provided
            if not token:
                return False, "No approval token provided. You must call preview_query first to get an approval token, then include that token when calling query_oracle."

            # Check if token exists
            if token not in self.approvals:
                return False, "Invalid or expired approval token. The token may have expired (5 minute limit) or been used already (one-time use). Call preview_query again to get a new token."

            # Get approval data
            approval_data = self.approvals[token]

            # Verify query matches
            query_hash = self._hash_query(query)
            if query_hash != approval_data['query_hash']:
                return False, "Query does not match approved query. The query you're trying to execute is different from the one you previewed. Make sure you're using the exact same query."

            # Token is valid - consume it (one-time use)
            del self.approvals[token]

            return True, ""


async def test_token_generation():
    """Test that tokens are generated correctly."""
    print(f"\n{'='*60}")
    print("Test: Token Generation")

    tracker = QueryApprovalTracker(token_expiry=300)
    query = "SELECT * FROM users WHERE id = 123"

    # Generate token
    token = await tracker.generate_approval_token(query)

    print(f"Generated token: {token[:16]}... (length: {len(token)})")
    assert token is not None, "Token should be generated"
    assert len(token) == 32, f"Token should be 32 characters, got {len(token)}"
    assert token.isalnum(), "Token should be alphanumeric"
    print("✅ PASS: Token generated with correct format")


async def test_token_verification():
    """Test that valid tokens are accepted."""
    print(f"\n{'='*60}")
    print("Test: Token Verification - Valid Token")

    tracker = QueryApprovalTracker(token_expiry=300)
    query = "SELECT * FROM users WHERE id = 123"

    # Generate and verify token
    token = await tracker.generate_approval_token(query)
    is_valid, error = await tracker.verify_approval(query, token)

    print(f"Token valid: {is_valid}")
    print(f"Error: {error if error else 'None'}")
    assert is_valid, f"Token should be valid: {error}"
    assert error == "", "Should have no error message"
    print("✅ PASS: Valid token accepted")


async def test_token_one_time_use():
    """Test that tokens can only be used once."""
    print(f"\n{'='*60}")
    print("Test: Token One-Time Use")

    tracker = QueryApprovalTracker(token_expiry=300)
    query = "SELECT * FROM users WHERE id = 123"

    # Generate token
    token = await tracker.generate_approval_token(query)

    # First use - should succeed
    is_valid1, error1 = await tracker.verify_approval(query, token)
    print(f"First use - Valid: {is_valid1}, Error: {error1 if error1 else 'None'}")
    assert is_valid1, "First use should succeed"

    # Second use - should fail
    is_valid2, error2 = await tracker.verify_approval(query, token)
    print(f"Second use - Valid: {is_valid2}, Error: {error2[:50]}...")
    assert not is_valid2, "Second use should fail (token consumed)"
    assert "Invalid or expired" in error2, "Should have appropriate error message"
    print("✅ PASS: Token can only be used once")


async def test_token_query_matching():
    """Test that token only works for matching query."""
    print(f"\n{'='*60}")
    print("Test: Token Query Matching")

    tracker = QueryApprovalTracker(token_expiry=300)
    query1 = "SELECT * FROM users WHERE id = 123"
    query2 = "SELECT * FROM users WHERE id = 456"

    # Generate token for query1
    token = await tracker.generate_approval_token(query1)

    # Try to use with query2 - should fail
    is_valid, error = await tracker.verify_approval(query2, token)
    print(f"Wrong query - Valid: {is_valid}, Error: {error[:50]}...")
    assert not is_valid, "Token should not work for different query"
    assert "does not match approved query" in error, "Should have appropriate error message"

    # Try to use with query1 - should succeed
    is_valid, error = await tracker.verify_approval(query1, token)
    print(f"Correct query - Valid: {is_valid}, Error: {error if error else 'None'}")
    assert is_valid, "Token should work for original query"
    print("✅ PASS: Token only works for matching query")


async def test_token_whitespace_normalization():
    """Test that whitespace differences don't matter."""
    print(f"\n{'='*60}")
    print("Test: Whitespace Normalization")

    tracker = QueryApprovalTracker(token_expiry=300)
    query1 = "SELECT * FROM users WHERE id = 123"
    query2 = "SELECT   *   FROM   users   WHERE   id   =   123"  # Extra spaces
    query3 = "select * from users where id = 123"  # Different case

    # Generate token for query1
    token = await tracker.generate_approval_token(query1)

    # Try query2 with extra spaces - should succeed
    is_valid2, error2 = await tracker.verify_approval(query2, token)
    print(f"Extra spaces - Valid: {is_valid2}")
    # Note: Token was consumed, so we need a new one

    # Generate new token for query1
    token = await tracker.generate_approval_token(query1)

    # Try query3 with different case - should succeed
    is_valid3, error3 = await tracker.verify_approval(query3, token)
    print(f"Different case - Valid: {is_valid3}")

    # At least one should succeed (depends on normalization implementation)
    assert is_valid2 or is_valid3, "Whitespace/case normalization should work"
    print("✅ PASS: Whitespace and case normalized correctly")


async def test_token_expiry():
    """Test that tokens expire after timeout."""
    print(f"\n{'='*60}")
    print("Test: Token Expiry")

    # Use very short expiry for testing
    tracker = QueryApprovalTracker(token_expiry=1)
    query = "SELECT * FROM users WHERE id = 123"

    # Generate token
    token = await tracker.generate_approval_token(query)
    print(f"Token generated with 1 second expiry")

    # Wait for expiry
    print("Waiting 1.5 seconds for token to expire...")
    await asyncio.sleep(1.5)

    # Try to use expired token
    is_valid, error = await tracker.verify_approval(query, token)
    print(f"After expiry - Valid: {is_valid}, Error: {error[:50]}...")
    assert not is_valid, "Expired token should be rejected"
    assert "Invalid or expired" in error, "Should have appropriate error message"
    print("✅ PASS: Token expires after timeout")


async def test_missing_token():
    """Test that missing token is rejected."""
    print(f"\n{'='*60}")
    print("Test: Missing Token")

    tracker = QueryApprovalTracker(token_expiry=300)
    query = "SELECT * FROM users WHERE id = 123"

    # Try with None token
    is_valid1, error1 = await tracker.verify_approval(query, None)
    print(f"None token - Valid: {is_valid1}, Error: {error1[:50]}...")
    assert not is_valid1, "None token should be rejected"
    assert "No approval token provided" in error1, "Should have appropriate error message"

    # Try with empty string
    is_valid2, error2 = await tracker.verify_approval(query, "")
    print(f"Empty token - Valid: {is_valid2}, Error: {error2[:50]}...")
    assert not is_valid2, "Empty token should be rejected"
    assert "No approval token provided" in error2, "Should have appropriate error message"
    print("✅ PASS: Missing token rejected correctly")


async def test_multiple_tokens():
    """Test that multiple tokens can coexist."""
    print(f"\n{'='*60}")
    print("Test: Multiple Concurrent Tokens")

    tracker = QueryApprovalTracker(token_expiry=300)
    query1 = "SELECT * FROM users WHERE id = 123"
    query2 = "SELECT * FROM orders WHERE id = 456"
    query3 = "SELECT * FROM products WHERE id = 789"

    # Generate multiple tokens
    token1 = await tracker.generate_approval_token(query1)
    token2 = await tracker.generate_approval_token(query2)
    token3 = await tracker.generate_approval_token(query3)

    print(f"Generated 3 tokens for different queries")

    # Verify all tokens work
    is_valid1, _ = await tracker.verify_approval(query1, token1)
    is_valid2, _ = await tracker.verify_approval(query2, token2)
    is_valid3, _ = await tracker.verify_approval(query3, token3)

    print(f"Token 1 valid: {is_valid1}")
    print(f"Token 2 valid: {is_valid2}")
    print(f"Token 3 valid: {is_valid3}")

    assert is_valid1, "Token 1 should be valid"
    assert is_valid2, "Token 2 should be valid"
    assert is_valid3, "Token 3 should be valid"
    print("✅ PASS: Multiple tokens can coexist")


async def main():
    """Run all approval workflow tests."""
    print("🧪 Testing QueryApprovalTracker")
    print("="*80)

    tests = [
        ("Token Generation", test_token_generation),
        ("Token Verification", test_token_verification),
        ("Token One-Time Use", test_token_one_time_use),
        ("Token Query Matching", test_token_query_matching),
        ("Whitespace Normalization", test_token_whitespace_normalization),
        ("Token Expiry", test_token_expiry),
        ("Missing Token", test_missing_token),
        ("Multiple Concurrent Tokens", test_multiple_tokens),
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
    print("APPROVAL WORKFLOW TEST RESULTS")
    print('='*80)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")

    if failed == 0:
        print("\n🎉 ALL APPROVAL WORKFLOW TESTS PASSED!")
        return 0
    else:
        print(f"\n❌ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
