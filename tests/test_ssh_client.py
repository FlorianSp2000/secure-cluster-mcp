"""Tests for SSH client module."""

import os

import pytest

from secure_cluster_mcp.ssh_client import ClusterSSH, CommandResult, get_ssh_client


class TestDryRunMode:
    """Tests for DRY_RUN safety mode."""

    def test_exec_command_dry_run(self):
        """exec_command in DRY_RUN should not execute."""
        os.environ["DRY_RUN"] = "true"

        ssh = ClusterSSH()
        result = ssh.exec_command("rm -rf /")

        assert result.dry_run is True
        assert "[DRY_RUN]" in result.stdout
        assert "rm -rf /" in result.stdout
        assert result.exit_code == 0

    def test_upload_file_dry_run(self, temp_local_file):
        """upload_file in DRY_RUN should not upload."""
        os.environ["DRY_RUN"] = "true"

        ssh = ClusterSSH()
        result = ssh.upload_file(
            str(temp_local_file),
            "/home/testuser/project/uploaded.txt"
        )

        assert "[DRY_RUN]" in result
        assert "Would upload" in result

    def test_download_file_dry_run(self, tmp_path):
        """download_file in DRY_RUN should not download."""
        os.environ["DRY_RUN"] = "true"

        ssh = ClusterSSH()
        result = ssh.download_file(
            "/home/testuser/project/remote.txt",
            str(tmp_path / "local.txt")
        )

        assert "[DRY_RUN]" in result
        assert "Would download" in result
        assert not (tmp_path / "local.txt").exists()


class TestPathValidation:
    """Tests for path validation in SSH client."""

    def test_upload_rejects_invalid_remote_path(self, temp_local_file):
        """upload_file should reject paths outside REMOTE_BASE_PATH."""
        os.environ["DRY_RUN"] = "true"

        ssh = ClusterSSH()
        with pytest.raises(Exception) as exc:
            ssh.upload_file(str(temp_local_file), "/etc/passwd")

        assert "not under REMOTE_BASE_PATH" in str(exc.value)

    def test_upload_rejects_missing_local_file(self):
        """upload_file should reject nonexistent local files."""
        os.environ["DRY_RUN"] = "true"

        ssh = ClusterSSH()
        with pytest.raises(FileNotFoundError):
            ssh.upload_file("/nonexistent/file.txt", "/home/testuser/project/dest.txt")

    def test_list_directory_rejects_invalid_path(self):
        """list_directory should reject paths outside REMOTE_BASE_PATH."""
        os.environ["DRY_RUN"] = "true"

        ssh = ClusterSSH()
        with pytest.raises(Exception) as exc:
            ssh.list_directory("/var/log")

        assert "not under REMOTE_BASE_PATH" in str(exc.value)


class TestCommandResult:
    """Tests for CommandResult dataclass."""

    def test_success_true_on_zero_exit(self):
        """success should be True for exit_code 0."""
        result = CommandResult(stdout="ok", stderr="", exit_code=0)
        assert result.success is True

    def test_success_false_on_nonzero_exit(self):
        """success should be False for non-zero exit_code."""
        result = CommandResult(stdout="", stderr="error", exit_code=1)
        assert result.success is False
