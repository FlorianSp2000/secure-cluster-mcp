# CLAUDE.md - Project Instructions

## CRITICAL: CLUSTER SAFETY

**This MCP server interacts with a shared university HPC cluster. Mistakes can:**
- Waste compute resources (expensive)
- Block other researchers' jobs
- Corrupt research data
- Get user banned from cluster

### MANDATORY RULES

1. **DRY_RUN=true by default** - Never execute real SSH/SCP without explicit user confirmation
2. **Never spam cluster** - Rate limit all commands (max 30/5min)
3. **Never exceed job limits** - Max 5 concurrent jobs per agent
4. **Validate ALL paths** - Must be under CLUSTER_PATH, reject others
5. **Log tail only** - Never read full logs (100 lines max)
6. **No destructive commands** - Never rm, never overwrite without confirmation
7. **Fail fast** - If validation fails, raise error immediately, don't proceed

### Before ANY cluster interaction:
- Check DRY_RUN flag
- Validate paths
- Check rate limits
- Log what would happen

## Cluster File Transfer

Use `scp` via the MCP tools, never raw commands.

**Cluster details (from `.env`):**
- `CLUSTER_HOST` - cluster IP
- `CLUSTER_USER` - username
- `CLUSTER_PATH` - remote project root

**ALWAYS confirm with user before:**
1. Any file transfer
2. Any job submission
3. Any command that modifies remote state

## Development

Use `uv` for Python environment management.
