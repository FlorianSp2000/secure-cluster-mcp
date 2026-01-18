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


def get_remote_base_path() -> str:
    """Get REMOTE_BASE_PATH with trailing slash stripped."""
    return get_settings().remote_base_path.rstrip("/")


async def poll_until_complete(
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
        await asyncio.sleep(interval_seconds)

    return f"still running after {max_attempts} attempts. Last status: {status}"


# =============================================================================
# MCP Tools
# =============================================================================


@mcp.tool()
def cluster_info() -> str:
    """Show current cluster connection info and settings."""
    settings = get_settings()
    return f"""Cluster Connection:
  Host: {settings.cluster_host}
  User: {settings.cluster_user}
  Path: {settings.remote_base_path}

Mode:
  DRY_RUN: {settings.dry_run}

Guardrails:
  Rate limit: {settings.rate_limit_commands} commands per {settings.rate_limit_window_seconds}s
  Log tail lines: {settings.log_tail_lines}"""


@mcp.tool()
@handle_tool_errors
def transfer_file(local_path: str, remote_path: str) -> str:
    """Transfer a local file to the cluster.

    Args:
        local_path: Absolute path to local file
        remote_path: Destination on cluster (must be under REMOTE_BASE_PATH)
    """
    return get_ssh_client().upload_file(local_path, remote_path)


@mcp.tool()
@handle_tool_errors
def submit_job(script_path: str) -> str:
    """Submit a SLURM job using sbatch.

    Args:
        script_path: Path to sbatch script (must be under REMOTE_BASE_PATH)
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
    """Check SLURM queue for current user's jobs."""
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
async def poll_job(job_id: str, interval_seconds: int = 10, max_attempts: int = 60) -> str:
    """Poll job status until completion.

    Args:
        job_id: SLURM job ID to monitor
        interval_seconds: Seconds between checks
        max_attempts: Max attempts (max 60)
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

    result = await poll_until_complete(check_status, interval_seconds, max_attempts)
    return f"Job {job_id} {result}"


@mcp.tool()
@handle_tool_errors
def read_logs(job_id_or_path: str, log_type: str = "out", lines: int = 200) -> str:
    """Read job log file (stdout or stderr).

    Args:
        job_id_or_path: Job ID (looks in logs/) or full path
        log_type: "out" for stdout, "err" for stderr
        lines: Lines to read (0=full file)
    """
    if "/" in job_id_or_path:
        log_path = job_id_or_path
    else:
        ext = "err" if log_type == "err" else "out"
        log_dir = get_settings().log_dir
        log_path = f"{get_remote_base_path()}/{log_dir}/{job_id_or_path}.{ext}"

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
    pattern: str = "",
    mmin: int = 0,
    mtime: int = 0,
    max_depth: int = 1,
    detailed: bool = False,
    limit: int = 50,
) -> str:
    """List files using find with time filtering.

    Args:
        path: Directory (relative to REMOTE_BASE_PATH)
        pattern: Glob (e.g., "*.err", "*.out")
        mmin: Files modified within N minutes (e.g., 360 = last 6 hours)
        mtime: Files modified within N days (e.g., 1 = last 24 hours)
        max_depth: Search depth (default 1 = current dir only, 0 = unlimited)
        detailed: If True, show size + date + filename; if False, filenames only
        limit: Max files to return (default 50, 0 = unlimited)

    Examples:
        list_remote("logs", pattern="*.err", mtime=1)  # .err files last 24h
    """
    validated = validate_remote_path(path)

    # Build find command
    cmd_parts = ["find", validated]

    if max_depth > 0:
        cmd_parts.extend(["-maxdepth", str(max_depth)])

    cmd_parts.extend(["-type", "f"])

    if pattern:
        cmd_parts.extend(["-name", f"'{pattern}'"])

    if mmin > 0:
        cmd_parts.extend(["-mmin", f"-{mmin}"])
    elif mtime > 0:
        cmd_parts.extend(["-mtime", f"-{mtime}"])

    if detailed:
        # Date + filename (tab-separated for cut)
        cmd_parts.append(r"-printf '%T@\t%Tb %Td %TH:%TM\t%f\n'")
    else:
        # Filenames only (tab-separated for cut)
        cmd_parts.append(r"-printf '%T@\t%f\n'")

    # Sort by time (newest first), limit, remove timestamp prefix
    cmd_parts.append("| sort -rn")
    if limit > 0:
        cmd_parts.append(f"| head -n {limit}")
    cmd_parts.append("| cut -f2-")

    cmd = " ".join(cmd_parts)
    output = run_command(cmd)

    if not output.strip():
        msg = f"No files found in {validated}"
        if pattern:
            msg += f" matching '{pattern}'"
        return msg

    return output


@mcp.tool()
@handle_tool_errors
def download_file(remote_path: str, local_path: str) -> str:
    """Download file from cluster to local machine.

    Args:
        remote_path: Path on cluster (must be under REMOTE_BASE_PATH)
        local_path: Local destination path
    """
    return get_ssh_client().download_file(remote_path, local_path)


@mcp.tool()
@handle_tool_errors
def search_logs(
    pattern: str,
    file_pattern: str = "*.err",
    path: str = "",
    context_lines: int = 2,
    mmin: int = 0,
    mtime: int = 0,
) -> str:
    """Search log files for pattern using find + grep.

    Args:
        pattern: Regex pattern (e.g., "Error|Exception")
        file_pattern: File glob (default "*.err")
        path: Directory to search (default: logs/)
        context_lines: Lines before/after match (max 10)
        mmin: Only files modified within N minutes
        mtime: Only files modified within N days
    """
    if len(pattern) > 200:
        raise ValueError("Pattern must be <200 chars")

    if context_lines > 10:
        context_lines = 10

    log_dir = get_settings().log_dir
    search_path = path if path else f"{get_remote_base_path()}/{log_dir}"
    validated = validate_remote_path(search_path)

    if is_dry_run():
        time_filter = ""
        if mmin > 0:
            time_filter = f" (last {mmin} min)"
        elif mtime > 0:
            time_filter = f" (last {mtime} days)"
        return f"[DRY_RUN] Would search {validated}/{file_pattern}{time_filter} for: {pattern}"

    # Build find + grep command
    cmd_parts = ["find", validated, "-type", "f", "-name", f"'{file_pattern}'"]

    if mmin > 0:
        cmd_parts.extend(["-mmin", f"-{mmin}"])
    elif mtime > 0:
        cmd_parts.extend(["-mtime", f"-{mtime}"])

    # -exec grep with context lines, show filename and line numbers
    cmd_parts.append(f"-exec grep -H -n -C {context_lines} '{pattern}' {{}} +")

    cmd = " ".join(cmd_parts)
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

    Args:
        command: Command to execute
        timeout_seconds: Timeout (max 600s)
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
    logger.info(f"  Path: {settings.remote_base_path}")
    logger.info(f"  DRY_RUN: {settings.dry_run}")
    logger.info(f"  Rate limit: {settings.rate_limit_commands}/{settings.rate_limit_window_seconds}s")

    if settings.dry_run:
        logger.warning("DRY_RUN=true - No real cluster commands will execute!")

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
