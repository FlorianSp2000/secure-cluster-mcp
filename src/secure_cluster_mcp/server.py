"""MCP Server with cluster tools.

SAFETY CRITICAL:
- All tools enforce guardrails
- DRY_RUN mode prevents real execution
- Rate limits and job limits enforced
"""

import asyncio
import logging
import re
from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from fastmcp import FastMCP

from .config import get_settings
from .guardrails import GuardrailError, validate_remote_path
from .ssh_client import get_ssh_client

logger = logging.getLogger(__name__)

# Create MCP server
mcp = FastMCP(
    "secure-cluster-mcp",
    instructions="Safe HPC cluster interactions with guardrails. DRY_RUN mode prevents real execution.",
)

P = ParamSpec("P")
T = TypeVar("T")


# =============================================================================
# Shared Helpers
# =============================================================================


def handle_tool_errors(func: Callable[P, T]) -> Callable[P, str]:
    """Decorator that handles common exceptions for MCP tools."""
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            return f"ERROR: {e}"
        except GuardrailError as e:
            return f"BLOCKED: {e}"
        except Exception as e:
            return f"ERROR: {e}"
    return wrapper


def run_command(cmd: str, check_rate_limit: bool = True) -> str:
    """Execute command on cluster, return stdout. Raises on failure."""
    ssh = get_ssh_client()
    result = ssh.exec_command(cmd, check_rate_limit=check_rate_limit)
    if result.dry_run:
        return result.stdout
    if not result.success:
        raise RuntimeError(f"Command failed (exit {result.exit_code}): {result.stderr}")
    return result.stdout


def is_dry_run() -> bool:
    """Check if we're in DRY_RUN mode."""
    return get_settings().dry_run


def get_cluster_path() -> str:
    """Get CLUSTER_PATH with trailing slash stripped."""
    return get_settings().cluster_path.rstrip("/")


def poll_until_complete(
    check_fn: Callable[[], str | None],
    interval_seconds: int = 10,
    max_attempts: int = 60,
    on_complete: Callable[[], None] | None = None,
) -> str:
    """Poll until check_fn returns None (complete) or a terminal status.

    Args:
        check_fn: Returns current status string, or None if complete
        interval_seconds: Seconds between checks (min 5)
        max_attempts: Max attempts (max 60)
        on_complete: Optional callback when complete

    Returns:
        Final status message
    """
    if max_attempts > 60:
        max_attempts = 60
    if interval_seconds < 5:
        interval_seconds = 5

    status = None
    for attempt in range(max_attempts):
        status = check_fn()

        if status is None:
            if on_complete:
                on_complete()
            return "completed (no longer in queue)"

        if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
            if on_complete:
                on_complete()
            return f"finished with status: {status}"

        logger.info(f"Status: {status} (attempt {attempt + 1}/{max_attempts})")
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(interval_seconds))

    return f"still running after {max_attempts} attempts. Last status: {status}"


# =============================================================================
# MCP Tools
# =============================================================================


@mcp.tool()
def cluster_info() -> str:
    """Show current cluster connection info and settings.

    Returns:
        Connection details, DRY_RUN status, and guardrail limits
    """
    settings = get_settings()
    return f"""Cluster Connection:
  Host: {settings.cluster_host}
  User: {settings.cluster_user}
  Path: {settings.cluster_path}

Mode:
  DRY_RUN: {settings.dry_run}

Guardrails:
  Rate limit: {settings.rate_limit_commands} commands per {settings.rate_limit_window_seconds}s
  Log tail lines: {settings.log_tail_lines}"""


@mcp.tool()
@handle_tool_errors
def transfer_file(local_path: str, remote_path: str) -> str:
    """Transfer a local file to the cluster.

    SAFETY: Validates local file exists, remote path is under CLUSTER_PATH,
    and rate limits are not exceeded.

    Args:
        local_path: Absolute path to local file
        remote_path: Destination path on cluster (must be under CLUSTER_PATH)

    Returns:
        Confirmation message or error
    """
    return get_ssh_client().upload_file(local_path, remote_path)


@mcp.tool()
@handle_tool_errors
def submit_job(script_path: str) -> str:
    """Submit a SLURM job using sbatch.

    SAFETY: Path must be under CLUSTER_PATH. MCP requires user permission for each call.

    Args:
        script_path: Path to sbatch script on cluster (must be under CLUSTER_PATH)

    Returns:
        Job ID if successful, error message otherwise
    """
    validated_path = validate_remote_path(script_path)

    if is_dry_run():
        return f"[DRY_RUN] Would submit job: sbatch {validated_path}"

    output = run_command(f"sbatch {validated_path}")

    match = re.search(r"Submitted batch job (\d+)", output)
    if match:
        return f"Job submitted: {match.group(1)}"

    return f"Job submitted but could not parse ID:\n{output}"


@mcp.tool()
@handle_tool_errors
def check_queue() -> str:
    """Check SLURM queue for current user's jobs.

    Returns:
        List of running/pending jobs with status
    """
    settings = get_settings()
    output = run_command(
        f"squeue -u {settings.cluster_user} --format='%i|%j|%T|%M|%l|%D|%R' --noheader"
    )

    if is_dry_run():
        return output

    if not output.strip():
        return "No jobs in queue"

    lines = ["JobID | Name | State | Time | TimeLimit | Nodes | Reason", "-" * 60]
    lines.extend(line.replace("|", " | ") for line in output.strip().split("\n"))
    return "\n".join(lines)


@mcp.tool()
@handle_tool_errors
def poll_job(job_id: str, interval_seconds: int = 10, max_attempts: int = 60) -> str:
    """Poll job status until completion.

    SAFETY: Limited to 60 attempts (10 min default) to prevent infinite loops.

    Args:
        job_id: SLURM job ID to monitor
        interval_seconds: Seconds between checks (default 10)
        max_attempts: Maximum poll attempts (default 60, max 60)

    Returns:
        Final job status
    """
    if is_dry_run():
        return f"[DRY_RUN] Would poll job {job_id} every {interval_seconds}s for max {max_attempts} attempts"

    def check_status() -> str | None:
        output = run_command(
            f"squeue -j {job_id} --format='%T' --noheader",
            check_rate_limit=False,
        )
        status = output.strip()
        return status if status else None

    result = poll_until_complete(check_status, interval_seconds, max_attempts)
    return f"Job {job_id} {result}"


@mcp.tool()
@handle_tool_errors
def read_logs(job_id_or_path: str, log_type: str = "out", lines: int = 200) -> str:
    """Read job log file (stdout or stderr).

    Args:
        job_id_or_path: Either a job ID (will look in logs/{job_id}.out/.err)
                        or full path to log file
        log_type: "out" for stdout, "err" for stderr (ignored if full path given)
        lines: Number of lines to read (default 200, 0 = full file)

    Returns:
        Log file content (tail, or full if lines=0)
    """
    if "/" in job_id_or_path:
        log_path = job_id_or_path
    else:
        ext = "err" if log_type == "err" else "out"
        log_path = f"{get_cluster_path()}/logs/{job_id_or_path}.{ext}"

    ssh = get_ssh_client()

    if lines == 0:
        validated = validate_remote_path(log_path)
        content = run_command(f"cat {validated}")
        label = "full file"
    else:
        content = ssh.read_remote_file_tail(log_path, lines)
        label = f"last {lines} lines"

    if not content.strip():
        return f"Log file empty or not found: {log_path}"

    return f"=== {log_path} ({label}) ===\n{content}"


@mcp.tool()
@handle_tool_errors
def list_remote(
    path: str,
    sort_by: str = "time",
    max_age_minutes: int = 0,
    limit: int = 50,
    pattern: str = "",
) -> str:
    """List files in a remote directory with filtering.

    SAFETY: Path must be under CLUSTER_PATH.

    Args:
        path: Remote directory path to list
        sort_by: "time" (newest first) or "name" (alphabetical)
        max_age_minutes: Only show files modified within N minutes (0 = no filter)
        limit: Maximum entries to return (default 50, 0 = no limit)
        pattern: Glob pattern filter (e.g., "*.out", "*.err")

    Returns:
        Directory listing
    """
    validated = validate_remote_path(path)

    if max_age_minutes > 0:
        cmd = f"find {validated} -maxdepth 1 -type f -mmin -{max_age_minutes}"
        if pattern:
            cmd += f" -name '{pattern}'"
        cmd += " -printf '%T@ %p\\n' | sort -rn"
        if limit > 0:
            cmd += f" | head -n {limit}"
        cmd += " | cut -d' ' -f2-"
    else:
        sort_flag = "-t" if sort_by == "time" else ""
        if pattern:
            cmd = f"ls -la {sort_flag} {validated}/{pattern} 2>/dev/null"
        else:
            cmd = f"ls -la {sort_flag} {validated}"
        if limit > 0:
            cmd += f" | head -n {limit + 1}"

    output = run_command(cmd)

    if not output.strip():
        return f"No files found in {validated}" + (f" matching '{pattern}'" if pattern else "")

    return output


@mcp.tool()
@handle_tool_errors
def download_file(remote_path: str, local_path: str) -> str:
    """Download file from cluster to local machine.

    SAFETY: Remote path must be under CLUSTER_PATH.

    Args:
        remote_path: Path on cluster (must be under CLUSTER_PATH)
        local_path: Local destination path

    Returns:
        Confirmation message or error
    """
    return get_ssh_client().download_file(remote_path, local_path)


@mcp.tool()
@handle_tool_errors
def search_logs(
    pattern: str,
    file_pattern: str = "*.err",
    path: str = "",
    context_lines: int = 2,
    max_matches: int = 100,
) -> str:
    """Search log files for pattern using grep.

    SAFETY: Read-only. Path must be under CLUSTER_PATH. Output truncated.

    Args:
        pattern: Regex pattern to search (e.g., "Error|Exception|Traceback")
        file_pattern: File glob (default "*.err")
        path: Directory to search (default: CLUSTER_PATH/logs)
        context_lines: Lines before/after match (default 2, max 10)
        max_matches: Max matching lines returned (default 100, max 500)

    Returns:
        Matching lines with context, or "No matches"
    """
    if len(pattern) > 200:
        raise ValueError("Pattern must be <200 chars")

    if context_lines > 10:
        context_lines = 10
    if max_matches > 500:
        max_matches = 500

    search_path = path if path else f"{get_cluster_path()}/logs"
    validated = validate_remote_path(search_path)

    if is_dry_run():
        return f"[DRY_RUN] Would search {validated}/{file_pattern} for: {pattern}"

    # Use grep with context, limit output
    cmd = f"grep -r -n -C {context_lines} '{pattern}' {validated}/{file_pattern} 2>/dev/null | head -n {max_matches}"
    output = run_command(cmd)

    if not output.strip():
        return f"No matches for '{pattern}' in {validated}/{file_pattern}"

    return output


# Dangerous patterns that should never be executed
DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -r /",
    "rm -rf ~",
    "rm -rf *",
    "rm -rf .",
    "mkfs",
    "dd if=",
    "> /dev/",
    "chmod -R 777 /",
    "chmod 777 /",
    ":(){:|:&};:",  # fork bomb
    "mv /* ",
    "mv / ",
    "wget|sh",
    "curl|sh",
    "wget|bash",
    "curl|bash",
]


@mcp.tool()
@handle_tool_errors
def run_remote_command(command: str, timeout_seconds: int = 300) -> str:
    """Execute command on cluster login node.

    SAFETY: Dangerous patterns blocked. MCP requires user permission.
    Use for: singularity build, module commands, pip install, etc.

    Args:
        command: Command to execute on login node
        timeout_seconds: Timeout (default 300s, max 600s)

    Returns:
        Command output (stdout + stderr)
    """
    if len(command) > 2000:
        raise ValueError("Command must be <2000 chars")

    # Block dangerous patterns
    cmd_lower = command.lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd_lower:
            raise GuardrailError(f"Blocked dangerous pattern: '{pattern}'")

    if timeout_seconds > 600:
        timeout_seconds = 600

    if is_dry_run():
        return f"[DRY_RUN] Would execute: {command}"

    ssh = get_ssh_client()
    result = ssh.exec_command(command)

    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]:\n{result.stderr}"

    if not result.success:
        return f"Command failed (exit {result.exit_code}):\n{output}"

    return output if output.strip() else "(no output)"


# =============================================================================
# Entry Point
# =============================================================================


def main():
    """Entry point for CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    settings = get_settings()

    logger.info("Starting secure-cluster-mcp server")
    logger.info(f"  Cluster: {settings.cluster_user}@{settings.cluster_host}")
    logger.info(f"  Path: {settings.cluster_path}")
    logger.info(f"  DRY_RUN: {settings.dry_run}")
    logger.info(f"  Rate limit: {settings.rate_limit_commands}/{settings.rate_limit_window_seconds}s")

    if settings.dry_run:
        logger.warning("DRY_RUN=true - No real cluster commands will execute!")

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
