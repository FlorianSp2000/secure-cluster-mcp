"""MCP Server with cluster tools.

SAFETY CRITICAL:
- All tools enforce guardrails
- DRY_RUN mode prevents real execution
- Rate limits and job limits enforced
"""

import asyncio
import logging
import re

from fastmcp import FastMCP

from .config import get_settings
from .guardrails import (
    GuardrailError,
    JobLimitError,
    PathValidationError,
    RateLimitError,
    get_job_limiter,
    validate_remote_path,
)
from .ssh_client import CommandResult, get_ssh_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create MCP server
mcp = FastMCP(
    "secure-cluster-mcp",
    instructions="Safe HPC cluster interactions with guardrails. DRY_RUN mode prevents real execution.",
)


def _format_result(result: CommandResult) -> str:
    """Format command result for tool response."""
    output = []
    if result.dry_run:
        output.append("[DRY_RUN MODE - No real execution]")
    if result.stdout:
        output.append(f"stdout:\n{result.stdout}")
    if result.stderr:
        output.append(f"stderr:\n{result.stderr}")
    if not result.dry_run:
        output.append(f"exit_code: {result.exit_code}")
    return "\n".join(output) if output else "No output"


@mcp.tool()
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
    try:
        ssh = get_ssh_client()
        return ssh.upload_file(local_path, remote_path)
    except FileNotFoundError as e:
        return f"ERROR: {e}"
    except PathValidationError as e:
        return f"BLOCKED: {e}"
    except RateLimitError as e:
        return f"BLOCKED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def submit_job(script_path: str) -> str:
    """Submit a SLURM job using sbatch.

    SAFETY: Checks job limit before submission. Maximum 5 concurrent jobs.

    Args:
        script_path: Path to sbatch script on cluster (must be under CLUSTER_PATH)

    Returns:
        Job ID if successful, error message otherwise
    """
    try:
        # Validate path
        validated_path = validate_remote_path(script_path)

        # Check current job count
        ssh = get_ssh_client()
        settings = get_settings()

        queue_result = ssh.exec_command(f"squeue -u {settings.cluster_user} -h | wc -l")
        if queue_result.dry_run:
            return f"[DRY_RUN] Would submit job: sbatch {validated_path}"

        try:
            current_jobs = int(queue_result.stdout.strip())
        except ValueError:
            current_jobs = 0

        # Check job limit
        job_limiter = get_job_limiter()
        job_limiter.check(current_jobs)

        # Submit job
        result = ssh.exec_command(f"sbatch {validated_path}")
        if not result.success:
            return f"ERROR: sbatch failed\n{result.stderr}"

        # Parse job ID from "Submitted batch job 12345"
        match = re.search(r"Submitted batch job (\d+)", result.stdout)
        if match:
            job_id = match.group(1)
            job_limiter.track_job(job_id)
            return f"Job submitted: {job_id}"

        return f"Job submitted but could not parse ID:\n{result.stdout}"

    except PathValidationError as e:
        return f"BLOCKED: {e}"
    except JobLimitError as e:
        return f"BLOCKED: {e}"
    except RateLimitError as e:
        return f"BLOCKED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def check_queue() -> str:
    """Check SLURM queue for current user's jobs.

    Returns:
        List of running/pending jobs with status
    """
    try:
        ssh = get_ssh_client()
        settings = get_settings()

        result = ssh.exec_command(
            f"squeue -u {settings.cluster_user} "
            f"--format='%i|%j|%T|%M|%l|%D|%R' --noheader"
        )

        if result.dry_run:
            return result.stdout

        if not result.stdout.strip():
            return "No jobs in queue"

        # Format output
        lines = ["JobID | Name | State | Time | TimeLimit | Nodes | Reason"]
        lines.append("-" * 60)
        for line in result.stdout.strip().split("\n"):
            lines.append(line.replace("|", " | "))

        return "\n".join(lines)

    except RateLimitError as e:
        return f"BLOCKED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
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
    # Cap max attempts to prevent infinite loops
    if max_attempts > 60:
        max_attempts = 60
    if interval_seconds < 5:
        interval_seconds = 5

    try:
        ssh = get_ssh_client()
        settings = get_settings()

        if settings.dry_run:
            return f"[DRY_RUN] Would poll job {job_id} every {interval_seconds}s for max {max_attempts} attempts"

        for attempt in range(max_attempts):
            result = ssh.exec_command(
                f"squeue -j {job_id} --format='%T' --noheader",
                check_rate_limit=False,  # Don't count polling against rate limit
            )

            status = result.stdout.strip()

            if not status:
                # Job no longer in queue = completed
                job_limiter = get_job_limiter()
                job_limiter.untrack_job(job_id)
                return f"Job {job_id} completed (no longer in queue)"

            if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                job_limiter = get_job_limiter()
                job_limiter.untrack_job(job_id)
                return f"Job {job_id} finished with status: {status}"

            logger.info(f"Job {job_id} status: {status} (attempt {attempt + 1}/{max_attempts})")
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(interval_seconds))

        return f"Job {job_id} still running after {max_attempts} attempts. Last status: {status}"

    except RateLimitError as e:
        return f"BLOCKED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def read_logs(job_id_or_path: str, log_type: str = "out", lines: int = 100) -> str:
    """Read job log file (stdout or stderr).

    SAFETY: Only reads tail of log (max 100 lines). Path must be under CLUSTER_PATH.

    Args:
        job_id_or_path: Either a job ID (will look in logs/{job_id}.out/.err)
                        or full path to log file
        log_type: "out" for stdout, "err" for stderr (ignored if full path given)
        lines: Number of lines to read (max 100)

    Returns:
        Log file content (tail)
    """
    settings = get_settings()

    # Cap lines at configured maximum
    if lines > settings.log_tail_lines:
        lines = settings.log_tail_lines

    try:
        # Determine log path
        if "/" in job_id_or_path:
            # Full path provided
            log_path = job_id_or_path
        else:
            # Job ID provided - construct path
            ext = "err" if log_type == "err" else "out"
            log_path = f"{settings.cluster_path.rstrip('/')}/logs/{job_id_or_path}.{ext}"

        ssh = get_ssh_client()
        content = ssh.read_remote_file_tail(log_path, lines)

        if not content.strip():
            return f"Log file empty or not found: {log_path}"

        return f"=== {log_path} (last {lines} lines) ===\n{content}"

    except PathValidationError as e:
        return f"BLOCKED: {e}"
    except RateLimitError as e:
        return f"BLOCKED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def list_remote(path: str) -> str:
    """List files in a remote directory.

    SAFETY: Path must be under CLUSTER_PATH.

    Args:
        path: Remote directory path to list

    Returns:
        Directory listing
    """
    try:
        ssh = get_ssh_client()
        return ssh.list_directory(path)
    except PathValidationError as e:
        return f"BLOCKED: {e}"
    except RateLimitError as e:
        return f"BLOCKED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def main():
    """Entry point for CLI."""
    settings = get_settings()

    logger.info("Starting secure-cluster-mcp server")
    logger.info(f"  Cluster: {settings.cluster_user}@{settings.cluster_host}")
    logger.info(f"  Path: {settings.cluster_path}")
    logger.info(f"  DRY_RUN: {settings.dry_run}")
    logger.info(f"  Rate limit: {settings.rate_limit_commands}/{settings.rate_limit_window_seconds}s")
    logger.info(f"  Max jobs: {settings.max_concurrent_jobs}")

    if settings.dry_run:
        logger.warning("DRY_RUN=true - No real cluster commands will execute!")

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
