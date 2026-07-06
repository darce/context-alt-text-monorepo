# Resolution — 2026-07-05

**Status: unblocked (consumer side); upstream patch tracked in workbay monorepo.**

The shared `mcp-workbay-orchestrator` uv tool was reinstalled from the same `workbay-v0.3.8` tag with `workbay-codex-bridge` (0.2.0) added:

```bash
R="git+https://github.com/darce/workbay.git@workbay-v0.3.8"
uv tool install --no-sources --force \
  --with "$R#subdirectory=packages/workbay-protocol" \
  --with "$R#subdirectory=packages/mcp-workbay-handoff" \
  --with "$R#subdirectory=packages/workbay-codex-bridge" \
  --from "$R#subdirectory=packages/mcp-workbay-orchestrator" \
  mcp-workbay-orchestrator
```

`workbay_codex_bridge` verified importable in the tool venv. **Reconnect the `workbay-orchestrator-mcp` MCP server in any live session**, then verify `list_available_backends(probe=true)` → `codex-subagent.is_available: true`.

Root cause is upstream, not this repo's state: package-mode installs (`source_kind: "package"`) never reach the bridge-inclusive gitonly tool install (`workbay_bootstrap/install.py::_resolve_gitonly_member_specs` has no `package` branch), and the orchestrator README one-liner omits the bridge. Tracked upstream as finding `WB-BOOTSTRAP-PKGMODE-BRIDGE-GAP-01` on task `MAINT-crash-codexbridge-daemon-20260705`; assessment: `agentic-protocol-monorepo/docs/assessments/orchestration-crash-codex-bridge-daemon-removal-2026-07-05.md`. A fresh package-mode install will reproduce the gap until that lands.
