# secure-cluster-mcp

MCP server for safe HPC cluster interactions with guardrails.

## Safety First

This tool enforces guardrails to prevent cluster abuse:
- **DRY_RUN=true default** - logs commands without executing
- **Rate limiting** - max 30 commands per 5 minutes
- **Path validation** - all paths must be under CLUSTER_PATH
- **Dangerous command blocklist** - blocks `rm -rf`, `mkfs`, fork bombs, etc.

**Set DRY_RUN=false only after reviewing what commands would execute.**

## Installation

```bash
# With uv (recommended)
uv sync

# With pip
pip install -e .
```

## Configuration (.env)

**Required:**
```bash
CLUSTER_HOST=your.cluster.ip
CLUSTER_USER=username
CLUSTER_PATH=/remote/project/root/
SSH_KEY_PATH=/path/to/your/ssh/key
```

**Optional:**
```bash
DRY_RUN=true  # default true, set false for real execution
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

## Development

```bash
uv sync --extra dev
uv run pytest -v
```

## Building

```bash
uv build
```

## License

MIT
