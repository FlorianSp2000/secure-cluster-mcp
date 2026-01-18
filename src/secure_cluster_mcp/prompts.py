"""MCP Prompts for common SLURM workflows."""


def register_prompts(mcp):
    """Register all prompts with the MCP server."""

    @mcp.prompt()
    def check_failed_jobs(hours: int = 24) -> str:
        """Check for failed jobs in recent logs."""
        return f"""Check for failed jobs in the last {hours} hours:

1. Use search_logs to find "Error|Exception|Traceback" in .err files (mmin={hours * 60})
2. List affected job IDs and summarize error types
3. For each unique error, show one example with context
4. Suggest fixes if patterns are obvious (e.g., missing files, OOM, timeouts)"""

    @mcp.prompt()
    def submit_array_job(script: str, array_range: str) -> str:
        """Guide for submitting a SLURM array job."""
        return f"""Submit an array job:

**Script**: {script}
**Array range**: {array_range}

1. Use submit_job with args="--array={array_range}" and script_path="{script}"
2. After submission, use check_queue to verify job is queued
3. Explain how to monitor with: list_remote("logs", pattern="*_$JOBID_*.err", mmin=60)"""

    @mcp.prompt()
    def cluster_status() -> str:
        """Get overview of cluster and recent job status."""
        return """Provide cluster status overview:

1. Use check_queue to show current jobs (running/pending)
2. Use list_remote("logs", pattern="*.err", mmin=360) to find recent job logs
3. Use search_logs("Error", mmin=360) to check for recent failures
4. Summarize: jobs running, jobs pending, recent failures (if any)"""

    @mcp.prompt()
    def debug_job(job_id: str) -> str:
        """Debug a specific job."""
        return f"""Debug job {job_id}:

1. Use read_logs("{job_id}", log_type="err") to check stderr
2. Use read_logs("{job_id}", log_type="out") to check stdout
3. Look for: errors, stack traces, resource issues (OOM, timeout)
4. Summarize what went wrong and suggest fixes"""
