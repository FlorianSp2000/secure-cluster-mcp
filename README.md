# secure-cluster-mcp

MCP server for safe HPC cluster interactions with guardrails.

## SAFETY FIRST

This tool enforces guardrails to prevent cluster abuse:
- **DRY_RUN=true default** - logs commands without executing
- **Rate limiting** - max 30 commands per 5 minutes
- **Job limits** - max 5 concurrent jobs
- **Path validation** - all paths must be under CLUSTER_PATH
- **Log truncation** - tail 100 lines only, never full files

**Set DRY_RUN=false only after reviewing what commands would execute.**

## Install

```bash
uv sync
```

## Config (.env)

**All required - no defaults:**
```
CLUSTER_HOST=your.cluster.ip
CLUSTER_USER=username
CLUSTER_PATH=/remote/project/root/
SSH_KEY_PATH=/path/to/your/ssh/key
```

**Optional:**
```
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
| `transfer_file` | Upload local file to cluster (validates path) |
| `submit_job` | Submit sbatch script (enforces job limit) |
| `check_queue` | List user's jobs in SLURM queue |
| `poll_job` | Wait for job completion |
| `read_logs` | Read job stdout/stderr (tail only) |
| `list_remote` | List remote directory |

## Run Standalone

```bash
uv run secure-cluster-mcp
```

## Dev

```bash
uv sync --extra dev
uv run pytest -v
```
