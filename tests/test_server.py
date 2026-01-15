"""Tests for MCP server module."""

import asyncio
import os

import pytest


@pytest.fixture(autouse=True)
def setup_env():
    """Set required env vars for all tests."""
    os.environ["CLUSTER_HOST"] = "test.cluster.local"
    os.environ["CLUSTER_USER"] = "testuser"
    os.environ["REMOTE_BASE_PATH"] = "/home/testuser/project"
    os.environ["DRY_RUN"] = "true"


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
    }

    registered_tools = set(await mcp.get_tools())

    assert registered_tools == expected_tools
