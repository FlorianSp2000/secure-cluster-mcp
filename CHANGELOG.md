# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-05-25

### Added
- `singularity_test` tool: lightweight container validation on login node (no GPU, 60s cap)
- Tool annotations (`readOnlyHint`, `destructiveHint`, `openWorldHint`) on all 11 tools — enables Claude Code auto-permission decisions
- Functional tests via FastMCP `Client` (39 tests, up from 24)
- GitHub Actions CI (Python 3.11 + 3.12 matrix)
- MCP Inspector dev entry point (`dev_server.py`)
- Dynamic server instructions baked in at startup with real config values

### Fixed
- Shell injection via unquoted single-quote in `search_logs`/`list_remote` pattern args — now uses `shlex.quote`
- `singularity_test` missing `DANGEROUS_PATTERNS` check and length cap on `command` arg
- `singularity_test` stderr silently dropped on exit 0 (parity with `run_remote_command`)
- `submit_job` `args` not checked for shell metacharacters
- Test fixture missing `SSH_KEY_PATH` causing import crash in CI without `.env`

### Changed
- FastMCP version pin tightened from `>=0.4.0` to `>=2.0.0`
- Tool docstrings improved with `USE WHEN` hints and `Examples:` blocks

## [0.1.0] - 2026-05-10

### Added
- Initial SLURM cluster MCP server with 10 tools: `cluster_info`, `transfer_file`, `submit_job`, `check_queue`, `poll_job`, `read_logs`, `list_remote`, `download_file`, `search_logs`, `run_remote_command`
- DRY_RUN mode (default false) — all commands log without executing
- Path validation: all remote paths must be under `REMOTE_BASE_PATH`
- Rate limiting: 30 commands per 5-minute window, persisted across restarts
- Dangerous command blocklist (`rm -rf`, `mkfs`, fork bombs, etc.)
- SSH key authentication via Paramiko
- Prompts: `check_failed_jobs`, `submit_array_job`, `cluster_status`, `debug_job`
- `.env`-based configuration with pydantic-settings
