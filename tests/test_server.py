"""Tests for MCP server module."""

import asyncio
import os

import pytest
from fastmcp import Client


@pytest.fixture(autouse=True)
def setup_env():
    """Set required env vars for all tests."""
    from secure_cluster_mcp.config import reset_settings
    os.environ["CLUSTER_HOST"] = "test.cluster.local"
    os.environ["CLUSTER_USER"] = "testuser"
    os.environ["REMOTE_BASE_PATH"] = "/home/testuser/project"
    os.environ["DRY_RUN"] = "true"
    os.environ["SSH_KEY_PATH"] = __file__  # file exists; SSH never runs (DRY_RUN=true)
    reset_settings()


def test_mcp_server_creates():
    """MCP server should create with correct name."""
    from secure_cluster_mcp.server import mcp

    assert mcp is not None
    assert mcp.name == "secure-cluster-mcp"


@pytest.mark.asyncio
async def test_mcp_has_expected_tools():
    """MCP server should have all expected tools registered."""
    from secure_cluster_mcp.server import mcp

    expected_tools = {
        "cluster_info",
        "transfer_file",
        "submit_job",
        "check_queue",
        "poll_job",
        "read_logs",
        "list_remote",
        "download_file",
        "search_logs",
        "run_remote_command",
        "singularity_test",
    }

    registered_tools = set(await mcp.get_tools())

    assert registered_tools == expected_tools


@pytest.mark.asyncio
async def test_tool_annotations_readonly():
    """Read-only tools should carry readOnlyHint=True."""
    from secure_cluster_mcp.server import mcp

    tools = await mcp.get_tools()
    readonly_tools = {"cluster_info", "check_queue", "list_remote", "read_logs", "search_logs"}

    for name in readonly_tools:
        tool = tools[name]
        assert tool.annotations is not None, f"{name} missing annotations"
        assert tool.annotations.readOnlyHint is True, f"{name} should have readOnlyHint=True"


@pytest.mark.asyncio
async def test_tool_annotations_run_remote_destructive():
    """run_remote_command should carry destructiveHint=True."""
    from secure_cluster_mcp.server import mcp

    tools = await mcp.get_tools()
    tool = tools["run_remote_command"]
    assert tool.annotations.destructiveHint is True


@pytest.mark.asyncio
async def test_cluster_info_returns_connection_details():
    """cluster_info should return host, user, path, and DRY_RUN status."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("cluster_info")
    text = result.content[0].text
    assert "test.cluster.local" in text
    assert "testuser" in text
    assert "/home/testuser/project" in text
    assert "DRY_RUN" in text


@pytest.mark.asyncio
async def test_check_queue_dry_run():
    """check_queue in DRY_RUN should return dry-run prefixed output."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("check_queue")
    assert "[DRY_RUN]" in result.content[0].text


@pytest.mark.asyncio
async def test_submit_job_dry_run():
    """submit_job in DRY_RUN should show sbatch command, not execute."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("submit_job", {"script_path": "train.sbatch"})
    text = result.content[0].text
    assert "[DRY_RUN]" in text
    assert "sbatch" in text
    assert "train.sbatch" in text


@pytest.mark.asyncio
async def test_submit_job_invalid_path_blocked():
    """submit_job with path outside REMOTE_BASE_PATH should be blocked."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("submit_job", {"script_path": "/etc/passwd"})
    assert "BLOCKED" in result.content[0].text


@pytest.mark.asyncio
async def test_submit_job_shell_injection_blocked():
    """submit_job args with shell metacharacters should be blocked."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool(
            "submit_job", {"script_path": "train.sbatch", "args": "--partition=gpu; rm -rf ~"}
        )
    assert "BLOCKED" in result.content[0].text


@pytest.mark.asyncio
async def test_list_remote_dry_run():
    """list_remote in DRY_RUN should return dry-run output."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("list_remote", {"path": "logs"})
    assert "[DRY_RUN]" in result.content[0].text


@pytest.mark.asyncio
async def test_list_remote_invalid_path_blocked():
    """list_remote with path outside base should be blocked."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("list_remote", {"path": "/tmp"})
    assert "BLOCKED" in result.content[0].text


@pytest.mark.asyncio
async def test_search_logs_dry_run():
    """search_logs in DRY_RUN should describe what it would search."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("search_logs", {"pattern": "Error"})
    assert "[DRY_RUN]" in result.content[0].text


@pytest.mark.asyncio
async def test_transfer_file_missing_local_blocked():
    """transfer_file with nonexistent local file should return error."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool(
            "transfer_file",
            {"local_path": "/nonexistent/file.py", "remote_path": "scripts/file.py"},
        )
    assert "ERROR" in result.content[0].text


@pytest.mark.asyncio
async def test_singularity_test_dangerous_pattern_blocked():
    """singularity_test with dangerous command should be blocked."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool(
            "singularity_test",
            {"image": "containers/ml.sif", "command": "python -c 'import os; os.system(\"rm -rf ~\")'"},
        )
    assert "BLOCKED" in result.content[0].text


@pytest.mark.asyncio
async def test_singularity_test_dry_run():
    """singularity_test in DRY_RUN should show singularity exec command."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool(
            "singularity_test",
            {"image": "containers/ml.sif", "command": "python --version"},
        )
    text = result.content[0].text
    assert "[DRY_RUN]" in text
    assert "singularity exec" in text


@pytest.mark.asyncio
async def test_run_remote_command_dangerous_blocked():
    """run_remote_command with blocklisted pattern should be blocked."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("run_remote_command", {"command": "rm -rf /"})
    assert "BLOCKED" in result.content[0].text


@pytest.mark.asyncio
async def test_run_remote_command_dry_run():
    """run_remote_command in DRY_RUN should return dry-run message."""
    from secure_cluster_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("run_remote_command", {"command": "hostname"})
    assert "[DRY_RUN]" in result.content[0].text
