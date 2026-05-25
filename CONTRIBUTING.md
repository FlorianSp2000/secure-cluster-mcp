# Contributing

## Development setup

```bash
git clone https://github.com/<your-fork>/secure-cluster-mcp
cd secure-cluster-mcp
uv sync --extra dev
cp .env.example .env   # fill in CLUSTER_HOST, CLUSTER_USER, REMOTE_BASE_PATH, SSH_KEY_PATH
```

## Running tests

No real cluster needed — all fixtures run with `DRY_RUN=true`.

```bash
uv run pytest -v
```

## Testing interactively

Launch the MCP Inspector (UI at `http://localhost:6274`):

```bash
uv run fastmcp dev dev_server.py:mcp
```

## Adding a new tool

- Add `@mcp.tool(annotations={...})` + `@handle_tool_errors` to `server.py`
- Add the tool name to `test_mcp_has_expected_tools` in `tests/test_server.py`
- Add a functional test using `Client` (with `DRY_RUN=true`)
- Add an entry to the README tools table

## Commit style

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `chore:` — maintenance (deps, config, etc.)

## Pull requests

- Branch naming: `feature/short-desc`
- All tests must pass (`uv run pytest -v`)
- Update `CHANGELOG.md` under `[Unreleased]`
