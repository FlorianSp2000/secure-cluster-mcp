"""SSH client wrapper with DRY_RUN safety.

SAFETY CRITICAL:
- DRY_RUN=true: logs commands without executing
- All operations check rate limits
- All paths validated before transfer
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import paramiko

from .config import get_settings
from .guardrails import get_rate_limiter, validate_remote_path

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a remote command execution."""

    stdout: str
    stderr: str
    exit_code: int
    dry_run: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class SSHConnectionError(Exception):
    """Raised when SSH connection fails."""

    pass


class ClusterSSH:
    """SSH client for cluster operations with safety guardrails.

    SAFETY:
    - DRY_RUN mode logs without executing
    - All commands rate-limited
    - All paths validated
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: paramiko.SSHClient | None = None

    def _get_client(self) -> paramiko.SSHClient:
        """Get or create SSH client connection."""
        if self._client is not None:
            # Check if still connected
            transport = self._client.get_transport()
            if transport is not None and transport.is_active():
                return self._client
            self._client = None

        if self.settings.dry_run:
            raise SSHConnectionError(
                "Cannot connect in DRY_RUN mode. Set DRY_RUN=false to enable real connections."
            )

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=self.settings.cluster_host,
                username=self.settings.cluster_user,
                key_filename=str(self.settings.ssh_key_path),
            )
        except Exception as e:
            raise SSHConnectionError(f"Failed to connect to cluster: {e}") from e

        self._client = client
        return client

    def close(self) -> None:
        """Close SSH connection."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def exec_command(self, command: str, check_rate_limit: bool = True) -> CommandResult:
        """Execute command on remote cluster.

        SAFETY: Checks DRY_RUN and rate limits before executing.

        Args:
            command: Command to execute
            check_rate_limit: Whether to check/record rate limit

        Returns:
            CommandResult with stdout, stderr, exit_code
        """
        if check_rate_limit:
            get_rate_limiter().check_and_record()

        # DRY_RUN: Log and return mock result
        if self.settings.dry_run:
            logger.info(f"[DRY_RUN] Would execute: {command}")
            return CommandResult(
                stdout=f"[DRY_RUN] Would execute: {command}",
                stderr="",
                exit_code=0,
                dry_run=True,
            )

        # Real execution
        client = self._get_client()
        stdin, stdout, stderr = client.exec_command(command)

        exit_code = stdout.channel.recv_exit_status()
        stdout_str = stdout.read().decode("utf-8", errors="replace")
        stderr_str = stderr.read().decode("utf-8", errors="replace")

        logger.info(f"Executed: {command} (exit={exit_code})")
        return CommandResult(
            stdout=stdout_str,
            stderr=stderr_str,
            exit_code=exit_code,
            dry_run=False,
        )

    def upload_file(self, local_path: str | Path, remote_path: str) -> str:
        """Upload file to cluster via SCP.

        SAFETY:
        - Validates local file exists
        - Validates remote path under CLUSTER_PATH
        - Checks rate limit
        - Respects DRY_RUN

        Args:
            local_path: Local file path
            remote_path: Remote destination path

        Returns:
            Confirmation message

        Raises:
            FileNotFoundError: If local file doesn't exist
            PathValidationError: If remote path invalid
        """
        local = Path(local_path)
        if not local.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        if not local.is_file():
            raise ValueError(f"Local path is not a file: {local_path}")

        # Validate remote path
        validated_remote = validate_remote_path(remote_path)

        # Rate limit
        get_rate_limiter().check_and_record()

        # DRY_RUN
        if self.settings.dry_run:
            msg = f"[DRY_RUN] Would upload: {local_path} -> {validated_remote}"
            logger.info(msg)
            return msg

        # Real upload
        client = self._get_client()
        sftp = client.open_sftp()
        try:
            sftp.put(str(local), validated_remote)
            msg = f"Uploaded: {local_path} -> {validated_remote}"
            logger.info(msg)
            return msg
        finally:
            sftp.close()

    def download_file(self, remote_path: str, local_path: str | Path) -> str:
        """Download file from cluster via SCP.

        SAFETY:
        - Validates remote path under CLUSTER_PATH
        - Checks rate limit
        - Respects DRY_RUN

        Args:
            remote_path: Remote file path
            local_path: Local destination path

        Returns:
            Confirmation message
        """
        local = Path(local_path)

        # Validate remote path
        validated_remote = validate_remote_path(remote_path)

        # Rate limit
        get_rate_limiter().check_and_record()

        # DRY_RUN
        if self.settings.dry_run:
            msg = f"[DRY_RUN] Would download: {validated_remote} -> {local_path}"
            logger.info(msg)
            return msg

        # Real download
        client = self._get_client()
        sftp = client.open_sftp()
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(validated_remote, str(local))
            msg = f"Downloaded: {validated_remote} -> {local_path}"
            logger.info(msg)
            return msg
        finally:
            sftp.close()

    def read_remote_file_tail(self, remote_path: str, lines: int | None = None) -> str:
        """Read tail of remote file.

        Args:
            remote_path: Remote file path
            lines: Number of lines (defaults to config value)

        Returns:
            File content (tail)
        """
        validated_remote = validate_remote_path(remote_path)
        num_lines = lines if lines is not None else self.settings.log_tail_lines

        result = self.exec_command(f"tail -n {num_lines} {validated_remote}")
        return result.stdout

    def list_directory(self, remote_path: str) -> str:
        """List remote directory contents.

        SAFETY:
        - Validates path under CLUSTER_PATH
        - Respects DRY_RUN

        Args:
            remote_path: Remote directory path

        Returns:
            Directory listing
        """
        validated_remote = validate_remote_path(remote_path)
        result = self.exec_command(f"ls -la {validated_remote}")
        return result.stdout


# Module-level instance (lazy initialized)
_ssh_client: ClusterSSH | None = None


def get_ssh_client() -> ClusterSSH:
    """Get SSH client singleton."""
    global _ssh_client
    if _ssh_client is None:
        _ssh_client = ClusterSSH()
    return _ssh_client


def reset_ssh_client() -> None:
    """Reset SSH client (for testing)."""
    global _ssh_client
    if _ssh_client is not None:
        _ssh_client.close()
    _ssh_client = None
