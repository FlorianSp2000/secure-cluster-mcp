# Secure Cluster MCP

[![CI](https://github.com/FlorianSp2000/secure-cluster-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/FlorianSp2000/secure-cluster-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/secure-cluster-mcp)](https://pypi.org/project/secure-cluster-mcp/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Let AI coding assistants manage your SLURM cluster jobs safely.

Built with [FastMCP](https://github.com/jlowin/fastmcp) for ML researchers who want seamless experiment management through Claude Code or other MCP-compatible agents.

## Why?

Running ML experiments on HPC clusters typically means manual `scp`/`ssh` commands. This MCP server lets your AI assistant handle the workflow - transferring code, submitting jobs, monitoring progress, debugging failures - with built-in safety guardrails.

- **Structure** - well-defined tools for common workflows (transfer, submit, read logs)
- **Guardrails** - path validation, rate limiting, dangerous command blocking
- **Permissions** - read-only tools auto-allowed, write operations require confirmation

### Recommended Claude Code permissions

In `settings.local.json`, auto-allow read-only tools:
```json
{
  "permissions": {
    "allow": [
      "mcp__cluster__cluster_info",
      "mcp__cluster__list_remote",
      "mcp__cluster__check_queue",
      "mcp__cluster__read_logs",
      "mcp__cluster__search_logs"
    ]
  }
}
```

Tools requiring permission (write/execute): `transfer_file`, `download_file`, `submit_job`, `poll_job`, `run_remote_command`, `singularity_test`

## Prerequisites

- SSH access to your cluster (key-based authentication)
- SLURM scheduler (sbatch, squeue commands)

## Guardrails

- **Rate limiting** - max 30 commands per 5 min (configurable via env)
- **Path validation** - all paths must be under REMOTE_BASE_PATH
- **Dangerous command blocklist** - blocks `rm -rf`, `mkfs`, fork bombs, etc.
- **DRY_RUN mode** - set `DRY_RUN=true` to log commands without executing


## Installation

```bash
# From PyPI (recommended)
uv add secure-cluster-mcp

# Or from GitHub
uv add git+https://github.com/FlorianSp2000/secure-cluster-mcp.git

# Or clone and install locally for development
git clone https://github.com/FlorianSp2000/secure-cluster-mcp.git
cd secure-cluster-mcp
uv sync --extra dev
```

## Configuration

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
```

**Required settings:**
```bash
CLUSTER_HOST=your.cluster.ip           # Cluster IP or hostname
CLUSTER_USER=your_username             # Your cluster username
REMOTE_BASE_PATH=/home/user/project/   # Your working directory on cluster
SSH_KEY_PATH=~/.ssh/your_key           # Path to SSH private key
```

**Optional settings:**
```bash
DRY_RUN=false                     # Set true to log without executing (default: false)
LOG_DIR=logs                      # Log subdirectory for job output (default: logs)
RATE_LIMIT_COMMANDS=30            # Max commands per window (default: 30)
RATE_LIMIT_WINDOW_SECONDS=300     # Rate limit window in seconds (default: 300)
LOG_TAIL_LINES=200                # Default lines to read from logs (default: 200)
```

## Claude Code Integration

Register the server with the Claude Code CLI. `cluster` is the name Claude Code uses internally — it becomes the tool permission prefix (`mcp__cluster__submit_job`, etc.).

**Installed via PyPI:**
```bash
claude mcp add cluster secure-cluster-mcp
```

**From cloned repo (development):**
```bash
claude mcp add cluster uv -- --directory /path/to/secure-cluster-mcp run secure-cluster-mcp
```

<details>
<summary>Manual JSON config</summary>

Add to `~/.claude/settings.json` or `.claude/settings.local.json`:

```json
{
  "mcpServers": {
    "cluster": {
      "command": "secure-cluster-mcp"
    }
  }
}
```
</details>

## Available Tools

| Tool | Description |
|------|-------------|
| `cluster_info` | Show connection info and settings |
| `transfer_file` | Upload local file to cluster |
| `download_file` | Download file from cluster to local |
| `submit_job` | Submit sbatch script |
| `check_queue` | List user's jobs in SLURM queue |
| `poll_job` | Wait for job completion |
| `read_logs` | Read job stdout/stderr (tail) |
| `list_remote` | List files with time filtering (mmin/mtime) |
| `search_logs` | Grep log files with time filtering |
| `run_remote_command` | Execute command on login node |
| `singularity_test` | Test container on login node (no GPU, 60s cap) |

## Prompts

Pre-defined workflows for common tasks:

| Prompt | Description |
|--------|-------------|
| `check_failed_jobs(hours)` | Find errors in recent logs, summarize failures |
| `submit_array_job(script, range)` | Guide for submitting array jobs |
| `cluster_status()` | Overview of queue and recent job status |
| `debug_job(job_id)` | Debug a specific job's stdout/stderr |

### Time filtering with `list_remote` and `search_logs`

Both tools support time-based filtering:
- `mmin=N` - files modified within last N minutes
- `mtime=N` - files modified within last N days

```python
# List .err files from last 24h
list_remote("logs", pattern="*.err", mtime=1)

# Search for errors in logs from last 6 hours
search_logs("Error", mmin=360)
```

### Notes on `read_logs`

Can read **any file** under `REMOTE_BASE_PATH`:

```bash
# By job ID - uses LOG_DIR
read_logs("12345")  # → {REMOTE_BASE_PATH}/{LOG_DIR}/12345.out

# By full path
read_logs("/home/user/project/results/output.csv")
```

## Troubleshooting

### "Connection refused" or timeout
- Verify SSH access works: `ssh user@cluster_host`
- Check VPN connection if required
- Ensure SSH key has correct permissions: `chmod 600 ~/.ssh/your_key`

### "Path not under REMOTE_BASE_PATH"
- All remote paths must be under the configured REMOTE_BASE_PATH
- Check REMOTE_BASE_PATH in your .env is correct

### "Rate limit exceeded"
- Wait 5 minutes or adjust RATE_LIMIT_COMMANDS
- Rate limits persist across MCP restarts

### "Log file empty or not found"
- Check LOG_DIR matches your cluster's log location
- Use full path: `read_logs("/full/path/to/file.log")`
- Verify job ID exists: `check_queue`

### Commands execute but nothing happens
- Check DRY_RUN setting - must be `false` for real execution
- Review output for `[DRY_RUN]` prefix

## Limitations

- **SLURM only** - PBS/Torque/GridEngine not supported
- **Unix paths** - Windows cluster paths not supported
- **SSH key auth** - Password authentication not supported

## Development

```bash
git clone https://github.com/FlorianSp2000/secure-cluster-mcp.git
cd secure-cluster-mcp
uv sync --extra dev
uv run pytest -v
```

## License

MIT
