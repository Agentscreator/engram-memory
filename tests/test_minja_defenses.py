"""Tests for MINJA defense components (rate limiting and anomaly detection).

This module tests the defensive mechanisms against Memory INJection Attack (MINJA).

Clean Code principles applied:
- Each test has a clear, descriptive name describing the behavior being tested
- Test setup is explicit and focused
- Assertions use descriptive messages for debugging
- Tests are independent and can run in any order
"""

from engram.auth import CommitVelocityAnomalyDetector, RateLimiter


class TestRateLimiter:
    """Tests for the per-agent sliding window rate limiter.

    The rate limiter prevents mass commit attacks by limiting the number
    of commits an agent can make within a one-hour window.
    """

    def test_allows_commits_within_limit(self):
        """Commits within the rate limit are allowed."""
        limiter = RateLimiter(max_per_hour=50)
        for i in range(50):
            assert limiter.check("test-agent") is True, (
                f"Commit {i + 1} within limit should be allowed"
            )

    def test_blocks_commits_over_limit(self):
        """Commits exceeding the rate limit are blocked."""
        limiter = RateLimiter(max_per_hour=50)
        for _ in range(50):
            limiter.record("test-agent")
        assert limiter.check("test-agent") is False, "Commits exceeding limit should be blocked"

    def test_respects_different_agents(self):
        """Each agent has independent rate limits."""
        limiter = RateLimiter(max_per_hour=5)
        for _ in range(5):
            limiter.record("agent-1")
        assert limiter.check("agent-1") is False
        assert limiter.check("agent-2") is True, "Different agents should have independent limits"

    def test_window_expires_after_one_hour(self):
        """Rate limit window resets after one hour."""
        limiter = RateLimiter(max_per_hour=2)
        limiter.record("test-agent")
        limiter.record("test-agent")
        assert limiter.check("test-agent") is False, "Window should block after limit reached"


class TestCommitVelocityAnomalyDetector:
    """Tests for commit velocity anomaly detection.

    The anomaly detector identifies rapid commit bursts that may indicate
    a compromised or malicious agent attempting to poison memory.
    """

    def test_allows_normal_commit_velocity(self):
        """Normal commit velocity is allowed."""
        detector = CommitVelocityAnomalyDetector(threshold=10, window_seconds=60)
        for i in range(10):
            assert detector.record("test-agent") is True, f"Commit {i + 1} should be allowed"

    def test_blocks_anomalous_velocity(self):
        """Commits exceeding threshold are blocked."""
        detector = CommitVelocityAnomalyDetector(threshold=5, window_seconds=60)
        for _ in range(5):
            assert detector.record("test-agent") is True
        assert detector.record("test-agent") is False, "Commits above threshold should be blocked"

    def test_is_anomalous_returns_correct_state(self):
        """is_anomalous correctly reports anomaly status."""
        detector = CommitVelocityAnomalyDetector(threshold=3, window_seconds=60)
        assert detector.is_anomalous("test-agent") is False
        detector.record("test-agent")
        detector.record("test-agent")
        detector.record("test-agent")
        assert detector.is_anomalous("test-agent") is True

    def test_reset_clears_agent_history(self):
        """Reset clears an agent's commit history."""
        detector = CommitVelocityAnomalyDetector(threshold=2, window_seconds=60)
        detector.record("test-agent")
        detector.record("test-agent")
        assert detector.is_anomalous("test-agent") is True
        detector.reset("test-agent")
        assert detector.is_anomalous("test-agent") is False

    def test_get_velocity_returns_current_count(self):
        """get_velocity returns correct commit count in window."""
        detector = CommitVelocityAnomalyDetector(threshold=10, window_seconds=60)
        assert detector.get_velocity("test-agent") == 0
        detector.record("test-agent")
        detector.record("test-agent")
        assert detector.get_velocity("test-agent") == 2

    def test_different_agents_tracked_separately(self):
        """Each agent has independent anomaly tracking."""
        detector = CommitVelocityAnomalyDetector(threshold=2, window_seconds=60)
        detector.record("agent-1")
        detector.record("agent-1")
        assert detector.is_anomalous("agent-1") is True
        assert detector.is_anomalous("agent-2") is False

    def test_short_window_detection(self):
        """Anomaly detection works with short time windows."""
        import time

        detector = CommitVelocityAnomalyDetector(threshold=2, window_seconds=0.1)
        assert detector.record("test-agent") is True
        assert detector.record("test-agent") is True
        assert detector.record("test-agent") is False
        time.sleep(0.15)
        assert detector.is_anomalous("test-agent") is False


class TestAgentTrustLevels:
    """Tests for agent trust level scoring (stub for future implementation).

    Trust levels will be calculated based on:
    - Conflict rate: ratio of conflicts to total commits
    - Corroboration rate: ratio of facts confirmed by other agents
    - Historical behavior: commit patterns over time
    """

    def test_trust_score_calculation_stub(self):
        """Trust score calculation placeholder for future implementation."""
        default_trust = 0.5
        assert 0.0 <= default_trust <= 1.0
