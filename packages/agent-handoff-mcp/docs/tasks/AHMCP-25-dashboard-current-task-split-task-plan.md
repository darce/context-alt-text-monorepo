# AHMCP-25. DASHBOARD.md / CURRENT_TASK.json Surface Split <!-- lint-dashboard-txt: allow -->

> **Metadata**
>
> - **Date**: 2026-04-11
> - **Author**: GitHub Copilot
> - **Project**: agent-handoff-mcp
> - **Task ID**: AHMCP-25
> - **Target Branch**: `feature/ahmcp-25`
> - **Type**: Retroactive task plan — implementation preceded the planning artifact due to the ad-hoc/reactive nature of the work. See [planning-pipeline.md § Retroactive task plans](../../../../docs/agentic/rules/planning-pipeline.md#retroactive-task-plans).

---

## Objective

`CURRENT_TASK.json` was originally a human-readable markdown dashboard used as the MCP
fallback display surface. During active use it became clear that agents benefit more from
a machine-readable JSON snapshot (for programmatic inspection) while humans benefit from
a stable human-readable view (for VS Code preview, git diffs, and code review).

This task splits the two concerns into separate files:

- **`CURRENT_TASK.json`** — machine-readable JSON snapshot of the active task state.
  Written by `generate_current_task_md` and read by `handoff_close_check`.
  Listed in `.gitignore` (generated, not tracked).
- **`DASHBOARD.md`** — human-readable markdown mirror of the same state. <!-- lint-dashboard-txt: allow -->
  Written alongside `CURRENT_TASK.json` by `generate_current_task_md`.
  Listed in `.gitignore` (generated, not tracked).

The previously tracked `DASHBOARD.md` (a hand-maintained static file) is deleted. <!-- lint-dashboard-txt: allow -->
Agents reading CLAUDE.md are updated to use `DASHBOARD.md` as the stale MCP fallback. <!-- lint-dashboard-txt: allow -->

---

## Scope

**Package:** `packages/agent-handoff-mcp/`

Changed files:
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` — JSON render helpers
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` — `generate_current_task_md` writes both surfaces
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` — `dashboard` subcommand targets `DASHBOARD.md` <!-- lint-dashboard-txt: allow -->
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` — sync-check uses JSON compare
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` — renders JSON + markdown
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py` — `handoff_close_check` validates JSON
- `packages/agent-handoff-mcp/tests/test_handoff_state.py` — updated assertions
- `packages/agent-handoff-mcp/tests/test_review_findings.py` — updated assertions
- `CLAUDE.md` — MCP fallback text updated to reference `DASHBOARD.md` <!-- lint-dashboard-txt: allow -->
- `docs/agentic/instructions.md` — fallback text updated
- `docs/agentic/contracts/agent-handoff-mcp.md` — contract updated with new surface descriptions
- `docs/agentic/playbooks/host-adapters/worktree-codex-playbook.md` — playbook updated
- `.gitignore` — `DASHBOARD.md` and `CURRENT_TASK.json` added as generated files <!-- lint-dashboard-txt: allow -->
- `DASHBOARD.md` — deleted (replaced by generated file) <!-- lint-dashboard-txt: allow -->

---

## Handoff Reference

- **MCP task ref**: AHMCP-25
- **Slice decision**: `cop_slice_complete_AHMCP-25_dashboard_current_task_split` (decision id 1595)
- **Test evidence**: test run id 707 — `177 passed in 15.53s`
  (`packages/agent-handoff-mcp/tests/test_handoff_state.py` + `tests/test_review_findings.py`)
- **Review run**: `AHMCP-25-review-1` — verdict `pass_with_findings` (3 medium, 1 low; no high)

---

## Open Findings (at time of this artifact)

| Finding ID        | Severity | Status | Summary |
|-------------------|----------|--------|---------|
| AHMCP-25-BR-01    | medium   | open   | `dashboard_path` not centralised in `RuntimeConfig` |
| AHMCP-25-BR-02    | medium   | open   | Main-branch docs lag until merge (auto-resolved on merge) |
| AHMCP-25-BR-03    | low      | open   | CLI dashboard fallback is silent on rendering failure |
| AHMCP-25-BR-04    | medium   | open   | This retroactive task plan (resolved by this commit) |
