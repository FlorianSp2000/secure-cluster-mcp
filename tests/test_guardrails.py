"""Tests for guardrails module."""

import time

import pytest

from secure_cluster_mcp.guardrails import (
    PathValidationError,
    RateLimitError,
    RateLimiter,
    StateManager,
    validate_remote_path,
)


class TestPathValidation:
    """Tests for path validation."""

    def test_valid_path_under_cluster_path(self):
        """Valid path under REMOTE_BASE_PATH should pass."""
        result = validate_remote_path("/home/testuser/project/src/file.py")
        assert result == "/home/testuser/project/src/file.py"

    def test_valid_path_exact_cluster_path(self):
        """Exact REMOTE_BASE_PATH should pass."""
        result = validate_remote_path("/home/testuser/project")
        assert result == "/home/testuser/project"

    def test_invalid_path_outside_cluster_path(self):
        """Path outside REMOTE_BASE_PATH should fail."""
        with pytest.raises(PathValidationError) as exc:
            validate_remote_path("/home/otheruser/data")
        assert "not under REMOTE_BASE_PATH" in str(exc.value)

    def test_valid_relative_path(self):
        """Relative path should resolve to REMOTE_BASE_PATH."""
        result = validate_remote_path("subdir/file.txt")
        assert result == "/home/testuser/project/subdir/file.txt"

    def test_relative_path_traversal_blocked(self):
        """Relative path with .. escaping should fail."""
        with pytest.raises(PathValidationError):
            validate_remote_path("../../../etc/passwd")

    def test_invalid_empty_path(self):
        """Empty path should fail."""
        with pytest.raises(PathValidationError) as exc:
            validate_remote_path("")
        assert "cannot be empty" in str(exc.value)

    def test_path_traversal_attack(self):
        """Path traversal should not escape REMOTE_BASE_PATH validation."""
        # This path looks like it's under cluster path but tries to escape
        with pytest.raises(PathValidationError):
            validate_remote_path("/home/testuser/project/../../../etc/passwd")

    def test_similar_prefix_rejected(self):
        """Path with similar prefix but different dir should fail."""
        with pytest.raises(PathValidationError):
            validate_remote_path("/home/testuser/project_backup/file.py")


class TestRateLimiter:
    """Tests for rate limiting."""

    def test_allows_under_limit(self, tmp_path):
        """Commands under limit should pass."""
        state_mgr = StateManager(tmp_path / "state.json")
        limiter = RateLimiter(state_mgr)
        limiter.max_commands = 5

        # Should allow 5 commands
        for _ in range(5):
            limiter.check_and_record()

    def test_blocks_over_limit(self, tmp_path):
        """Commands over limit should fail."""
        state_mgr = StateManager(tmp_path / "state.json")
        limiter = RateLimiter(state_mgr)
        limiter.max_commands = 3

        # Use up limit
        for _ in range(3):
            limiter.check_and_record()

        # Next should fail
        with pytest.raises(RateLimitError) as exc:
            limiter.check()
        assert "Rate limit exceeded" in str(exc.value)

    def test_window_expiry(self, tmp_path):
        """Old commands should expire from window."""
        state_mgr = StateManager(tmp_path / "state.json")
        limiter = RateLimiter(state_mgr)
        limiter.max_commands = 2
        limiter.window_seconds = 1  # 1 second window for test

        # Use up limit
        limiter.check_and_record()
        limiter.check_and_record()

        # Wait for window to expire
        time.sleep(1.1)

        # Should allow again
        limiter.check_and_record()


class TestStateManager:
    """Tests for state persistence."""

    def test_persists_state(self, tmp_path):
        """State should persist to file."""
        state_file = tmp_path / "state.json"

        # Write state
        mgr1 = StateManager(state_file)
        state1 = mgr1.load()
        state1.command_timestamps.append(123.456)
        mgr1.save()

        # Read with new manager
        mgr2 = StateManager(state_file)
        state2 = mgr2.load()

        assert 123.456 in state2.command_timestamps

    def test_handles_missing_file(self, tmp_path):
        """Should create new state if file missing."""
        state_file = tmp_path / "nonexistent" / "state.json"
        mgr = StateManager(state_file)
        state = mgr.load()

        assert state.command_timestamps == []

    def test_handles_corrupt_file(self, tmp_path):
        """Should create new state if file corrupt."""
        state_file = tmp_path / "state.json"
        state_file.write_text("not valid json")

        mgr = StateManager(state_file)
        state = mgr.load()

        assert state.command_timestamps == []
