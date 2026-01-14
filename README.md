# secure-cluster-mcp

MCP server for safe HPC cluster interactions with guardrails.

## Prerequisites

- Python 3.10+
- SSH access to your cluster (key-based authentication)
- SLURM scheduler (sbatch, squeue commands)
- Network access to cluster (SSH port 22)

## Safety First

This tool enforces guardrails to prevent cluster abuse:
- **DRY_RUN=true default** - logs commands without executing
- **Rate limiting** - max 30 commands per 5 minutes
- **Path validation** - all paths must be under CLUSTER_PATH
- **Dangerous command blocklist** - blocks `rm -rf`, `mkfs`, fork bombs, etc.

**Set DRY_RUN=false only after reviewing what commands would execute.**

## Installation

```bash
# From GitHub
pip install git+https://github.com/FlorianSp2000/secure-cluster-mcp.git

# Or clone and install locally
git clone https://github.com/FlorianSp2000/secure-cluster-mcp.git
cd secure-cluster-mcp
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
```

**Required settings:**
```bash
CLUSTER_HOST=your.cluster.ip      # Cluster IP or hostname
CLUSTER_USER=your_username        # Your cluster username
CLUSTER_PATH=/path/to/project/    # Remote working directory
SSH_KEY_PATH=~/.ssh/id_rsa        # Path to SSH private key
```

**Optional settings:**
```bash
DRY_RUN=true                      # Safety mode (default: true)
LOG_DIR=logs                      # Log directory relative to CLUSTER_PATH
RATE_LIMIT_COMMANDS=30            # Max commands per window
RATE_LIMIT_WINDOW_SECONDS=300     # Rate limit window (5 min)
LOG_TAIL_LINES=200                # Default lines to read from logs
```

## Claude Code Integration

Add to `~/.claude.json`:
```json
{
  "mcpServers": {
    "cluster": {
      "command": "uv",
      "args": ["--directory", "/path/to/secure-cluster-mcp", "run", "secure-cluster-mcp"]
    }
  }
}
```

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
| `list_remote` | List remote directory with filtering |
| `search_logs` | Grep across log files for patterns |
| `run_remote_command` | Execute command on login node |

## Troubleshooting

### "Connection refused" or timeout
- Verify SSH access: `ssh -i ~/.ssh/id_rsa user@host`
- Check VPN connection if required
- Ensure SSH key has correct permissions: `chmod 600 ~/.ssh/id_rsa`

### "Path not under CLUSTER_PATH"
- All remote paths must be under the configured CLUSTER_PATH
- Check CLUSTER_PATH in your .env ends with `/`

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

## Building

```bash
uv build
```

## License

MIT
