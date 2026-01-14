"""Pytest fixtures for secure-cluster-mcp tests."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path):
    """Set up test environment variables and clean state."""
    # Set required env vars
    os.environ["CLUSTER_HOST"] = "test.cluster.local"
    os.environ["CLUSTER_USER"] = "testuser"
    os.environ["REMOTE_BASE_PATH"] = "/home/testuser/project"
    os.environ["DRY_RUN"] = "true"
    os.environ["SSH_KEY_PATH"] = str(tmp_path / "id_rsa")

    # Create fake SSH key
    (tmp_path / "id_rsa").write_text("fake-key")

    # Reset all singletons
    from secure_cluster_mcp.config import reset_settings
    from secure_cluster_mcp.guardrails import reset_guardrails
    from secure_cluster_mcp.ssh_client import reset_ssh_client

    reset_settings()
    reset_guardrails()
    reset_ssh_client()

    yield

    # Cleanup
    reset_settings()
    reset_guardrails()
    reset_ssh_client()


@pytest.fixture
def temp_state_dir(tmp_path):
    """Provide temporary state directory."""
    state_dir = tmp_path / ".secure-cluster-mcp"
    state_dir.mkdir()
    os.environ["STATE_DIR"] = str(state_dir)
    return state_dir


@pytest.fixture
def mock_ssh_client():
    """Mock paramiko SSHClient."""
    with patch("paramiko.SSHClient") as mock_class:
        mock_client = MagicMock()
        mock_class.return_value = mock_client

        # Mock exec_command
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"test output"
        mock_stdout.channel.recv_exit_status.return_value = 0

        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""

        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        # Mock SFTP
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp

        yield mock_client


@pytest.fixture
def temp_local_file(tmp_path):
    """Create a temporary local file for transfer tests."""
    test_file = tmp_path / "test_file.txt"
    test_file.write_text("test content")
    return test_file
