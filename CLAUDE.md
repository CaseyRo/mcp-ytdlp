# CLAUDE.md

Fleet MCP server; the README covers what it does and how it deploys. This file holds what an agent must not get wrong.

## fastmcp 4 idioms

- `fastmcp>=4.0.10,<5.0.0`; streamable-http with `stateless_http=True` passed to `run()`/`http_app()`, never the constructor (v4 rejects it). No `allowed_hosts` workaround: that was the 3.4.3 host guard.
- Annotations are snake_case (`read_only_hint`, `destructive_hint`, ...). CI runs with `FASTMCP_MCP_CAMELCASE_COMPAT=false`, so camelCase access fails the build.
- Failures raise `ToolError`. A returned error payload is logged by usage telemetry as `outcome: ok`.
- `src/mcp_ytdlp/usage.py` is vendored verbatim from `CDiT-infrastructure/scripts/mcp_usage_middleware.py`; re-copy it, never edit it here.
- Releases are tag-only: the release workflow pushes the next `v*` tag and commits nothing to the protected branch. Never bump `version` in `pyproject.toml`. The tag triggers `publish.yml` (PyPI via trusted publishing; the wheel takes its version from the tag).
- Testing: the `mcp-testing` skill. Release/deploy: the `cdit-release-pipeline` skill. Fleet conventions: `CDiT-infrastructure/docs/wiki/topics/mcp-fleet.md`.
