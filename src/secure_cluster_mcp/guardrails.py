"""Guardrails to prevent cluster abuse.

SAFETY CRITICAL:
- All validators raise exceptions on failure (fail-fast)
- Never silently allow invalid operations
- State persists across restarts
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import get_settings


class GuardrailError(Exception):
    """Base exception for guardrail violations."""

    pass


class PathValidationError(GuardrailError):
    """Raised when path is not under REMOTE_BASE_PATH."""

    pass


class RateLimitError(GuardrailError):
    """Raised when rate limit exceeded."""

    pass


def validate_remote_path(path: str) -> str:
    """Validate remote path is under REMOTE_BASE_PATH.

    Args:
        path: Remote path to validate

    Returns:
        Normalized path if valid

    Raises:
        PathValidationError: If path is not under REMOTE_BASE_PATH
    """
    settings = get_settings()
    remote_base_path = settings.remote_base_path.rstrip("/")

    # Basic validation
    if not path or not path.strip():
        raise PathValidationError("Path cannot be empty")

    # Must be absolute
    if not path.startswith("/"):
        raise PathValidationError(f"Path must be absolute: {path}")

    # Normalize path - resolve .. and . components
    # Split into parts, process each
    parts = []
    for part in path.split("/"):
        if part == "" or part == ".":
            continue
        if part == "..":
            if parts:
                parts.pop()
            # else: at root, ignore
        else:
            parts.append(part)

    normalized = "/" + "/".join(parts)

    # Must be under REMOTE_BASE_PATH (after normalization)
    if not (normalized == remote_base_path or normalized.startswith(remote_base_path + "/")):
        raise PathValidationError(
            f"Path '{path}' is not under REMOTE_BASE_PATH '{remote_base_path}'. "
            "This is a safety guardrail to prevent writing to wrong locations."
        )

    return normalized


@dataclass
class PersistentState:
    """State that persists across MCP restarts."""

    command_timestamps: list[float] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "command_timestamps": self.command_timestamps,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PersistentState":
        return cls(
            command_timestamps=data.get("command_timestamps", []),
            last_updated=data.get("last_updated", time.time()),
        )


class StateManager:
    """Manages persistent state for guardrails."""

    def __init__(self, state_file: Path | None = None):
        settings = get_settings()
        self.state_file = state_file or settings.state_file
        self._state: PersistentState | None = None

    def _ensure_dir(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> PersistentState:
        """Load state from file or create new."""
        if self._state is not None:
            return self._state

        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self._state = PersistentState.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                self._state = PersistentState()
        else:
            self._state = PersistentState()

        return self._state

    def save(self) -> None:
        """Persist state to file."""
        if self._state is None:
            return
        self._ensure_dir()
        self._state.last_updated = time.time()
        self.state_file.write_text(json.dumps(self._state.to_dict(), indent=2))

    def clear(self) -> None:
        """Clear all state (for testing)."""
        self._state = PersistentState()
        if self.state_file.exists():
            self.state_file.unlink()


class RateLimiter:
    """Rate limiter for cluster commands.

    SAFETY: Prevents spamming cluster with too many commands.
    """

    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        settings = get_settings()
        self.max_commands = settings.rate_limit_commands
        self.window_seconds = settings.rate_limit_window_seconds

    def _clean_old_timestamps(self, state: PersistentState) -> None:
        """Remove timestamps outside current window."""
        cutoff = time.time() - self.window_seconds
        state.command_timestamps = [ts for ts in state.command_timestamps if ts > cutoff]

    def check(self) -> None:
        """Check if rate limit allows another command.

        Raises:
            RateLimitError: If rate limit exceeded
        """
        state = self.state_manager.load()
        self._clean_old_timestamps(state)

        if len(state.command_timestamps) >= self.max_commands:
            oldest = min(state.command_timestamps)
            wait_seconds = int(oldest + self.window_seconds - time.time()) + 1
            raise RateLimitError(
                f"Rate limit exceeded: {self.max_commands} commands per {self.window_seconds}s. "
                f"Wait {wait_seconds}s before next command."
            )

    def record(self) -> None:
        """Record a command execution."""
        state = self.state_manager.load()
        state.command_timestamps.append(time.time())
        self.state_manager.save()

    def check_and_record(self) -> None:
        """Check rate limit and record if allowed."""
        self.check()
        self.record()


# Module-level instances (lazy initialized)
_state_manager: StateManager | None = None
_rate_limiter: RateLimiter | None = None


def get_state_manager() -> StateManager:
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(get_state_manager())
    return _rate_limiter


def reset_guardrails() -> None:
    """Reset all guardrails (for testing)."""
    global _state_manager, _rate_limiter
    if _state_manager is not None:
        _state_manager.clear()
    _state_manager = None
    _rate_limiter = None
