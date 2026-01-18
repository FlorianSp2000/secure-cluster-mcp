"""Configuration via environment variables.

SAFETY: DRY_RUN=true by default - no real cluster commands execute.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Cluster connection settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required cluster connection
    cluster_host: str = Field(..., description="Cluster IP or hostname")
    cluster_user: str = Field(..., description="SSH username")
    remote_base_path: str = Field(..., description="Remote project root path")

    # Required - no default, user must specify
    ssh_key_path: Path = Field(..., description="Path to SSH private key")
    
    def model_post_init(self, __context) -> None:
        """Expand ~ in paths after loading."""
        object.__setattr__(self, "ssh_key_path", self.ssh_key_path.expanduser())
        
    dry_run: bool = Field(
        default=False,
        description="If true, log commands without executing",
    )

    # Guardrail limits
    rate_limit_commands: int = Field(default=30, description="Max commands per window")
    rate_limit_window_seconds: int = Field(default=300, description="Rate limit window (5 min)")
    log_tail_lines: int = Field(default=200, description="Default lines to read from logs")
    log_dir: str = Field(default="logs", description="Log directory relative to REMOTE_BASE_PATH")

    # State persistence
    state_dir: Path = Field(
        default=Path.home() / ".secure-cluster-mcp",
        description="Directory for state persistence",
    )

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    def validate_settings(self) -> None:
        """Validate required settings are present. Raises ValueError if invalid."""
        if not self.cluster_host:
            raise ValueError("CLUSTER_HOST is required")
        if not self.cluster_user:
            raise ValueError("CLUSTER_USER is required")
        if not self.remote_base_path:
            raise ValueError("REMOTE_BASE_PATH is required")
        if not self.remote_base_path.startswith("/"):
            raise ValueError("REMOTE_BASE_PATH must be absolute path")
        if not self.ssh_key_path or not self.ssh_key_path.exists():
            raise ValueError(f"SSH_KEY_PATH is required and must exist: {self.ssh_key_path}")


# Singleton instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get settings singleton. Creates on first call."""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.validate_settings()
    return _settings


def reset_settings() -> None:
    """Reset settings singleton (for testing)."""
    global _settings
    _settings = None
