# MAINT-AOMCP-QUALITY-FIXES-20260419 — Task Plan

Resolve the 11 open findings recorded against `MAINT-AOMCP-QUALITY-20260417`.
Rule-violations in `packages/agent-orchestrator-mcp/`: rg-014 (late-binding imports from `agent_handoff_mcp`), rg-018 (raw sqlite against `handoff.db`), subprocess hygiene, daemon logging, magic-string comparisons, and greenfield-policy violations.

The parent review task `MAINT-AOMCP-QUALITY-20260417` remains the source of truth for finding IDs; this task only closes them.

## Slice Breakdown

Sliced for minimum coupling and blast radius. Each slice stays inside one concern and closes 1-3 findings at a time.

### Slice A — subprocess timeout (M-04)

- **Files**: `lane_result.py`
- **Change**: add `timeout=300` to `subprocess.run` at line 233; handle `subprocess.TimeoutExpired` explicitly.
- **Test**: unit test patches `subprocess.run` to assert `timeout=` kwarg is passed; regression test for timeout handling.
- **Closes**: AOMCP-QA-M-04

### Slice B — daemon logging (M-06)

- **Files**: `_env.py`, `lane_result.py`
- **Change**: `logger = logging.getLogger(__name__)`, replace error-path `print()` with `logger.warning/info`. Dry-run JSON stdout stays.
- **Test**: caplog assertion that load-failure paths emit WARNING records on the module logger.
- **Closes**: AOMCP-QA-M-06

### Slice C — silent exception swallowing (M-05)

- **Files**: `worker_daemon.py` (lines 200-208, 674, 1476, 1571)
- **Change**: narrow `except Exception` to specific exception tuples; `logger.warning(...)` before returning `{}`.
- **Test**: simulated broken-config path emits a warning record; healthy path stays quiet.
- **Closes**: AOMCP-QA-M-05

### Slice D — backend_registry cleanup (M-01, M-02, M-07)

- **Files**: `backend_registry.py`, `_env.py`, `tests/test_lane_exec.py`, `tests/test_backend_registry.py`
- **Changes**:
  - Remove `sys.path.insert`; use full-path imports from `agent_orchestrator_mcp.orchestration.*`.
  - Replace five pass-through factory functions + `BackendSpec.adapter_class` with `adapter_path: str` + `importlib` lazy resolver.
  - Delete `find_codex` back-compat wrapper; update tests to import from `adapters.codex_cli`.
- **Test**: existing backend-registry suites pass.
- **Closes**: AOMCP-QA-M-01, M-02, M-07

### Slice E — magic-string status sweep (L-02)

- **Files**: `lanes.py`, `lane_prompt.py`, `orchestrator_daemon.py`, `worker_daemon.py`, `review_dispatch.py`
- **Change**: replace `== 'open'`/`'dispatched'`/etc. with `LaneStatus.*` / `MessageStatus.*` / `FindingStatus.*` from `agent_handoff_mcp.enums`.
- **Test**: existing suites green.
- **Closes**: AOMCP-QA-L-02

### Slice F — SNAPSHOT_PHASES (L-01) + `_json_load` removal (M-03)

- **Files**: `api.py`, `cli.py`, `lane_prompt.py` + 43 call sites across 7 orchestration modules.
- **Change**: verify no live automation reads a1/a2/a3; delete SNAPSHOT_PHASES and `_legacy_tool_entries`. Audit that `agent_handoff_mcp` tools return dict; delete `_json_load`; replace every `payload = _json_load(result)` with `payload = result`.
- **Test**: affected test modules + CLI snapshot test.
- **Closes**: AOMCP-QA-L-01, M-03

### Slice G — api.py late-binding + drop re-export shims (H-02, H-04)

- **Files**: `api.py`
- **Change**: move lines 18-22 imports into each function that uses them. Drop the bulk `from agent_handoff_mcp.api import ...` re-export block (lines 41-68). Drop `generate_current_task_md` / `generate_dashboard_md` re-exports (lines 48-49); repoint callers at `render_handoff(kind=...)`.
- **Test**: import-smoke test — `import agent_orchestrator_mcp.api` does NOT load `agent_handoff_mcp.core` (assert via `sys.modules`).
- **Closes**: AOMCP-QA-H-02, H-04

### Slice H — lanes.py rg-014 late-binding (H-01)

- **Files**: `lanes.py` + handoff-side public API promotions.
- **Change**: audit private-helper imports, promote required helpers to public `agent_handoff_mcp` surface or refactor to use existing public API; move imports into each function that uses them.
- **Test**: import-smoke test (as Slice G); existing `lanes.py` suite.
- **Closes**: AOMCP-QA-H-01

### Slice I — rg-018 raw sqlite in ace_metrics (H-03)

- **Files**:
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` — add public `get_turn_metrics(task_ref, ...)`.
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` — re-export.
  - `ace_metrics.py` — delete raw-sqlite `_load_turn_metrics` body; call public helper.
- **Test**: new `test_get_turn_metrics.py` in handoff; updated `ace_metrics` test proves no raw sqlite remains.
- **Closes**: AOMCP-QA-H-03. Cross-package; single `slice-commit` covers both.

## Ordering

A → B → C → D → E → F → G → H → I. Smallest/safest first so the branch is always mergeable; the two big refactors (H, F) land after lower-risk hygiene slices have been reviewed.

## Non-goals

- No behaviour changes — every slice preserves observable behaviour.
- No new deprecations on the handoff-side public surface beyond `get_turn_metrics` (H-03).
- No doc rewrites outside finding scope.

## Verification strategy

- Per slice: targeted `pytest` on the affected file / module.
- Post-last-slice: full `make test-orchestrator` + `make test-handoff` green.
- `handoff_close_check(enforce=True, require_fresh_tests=True)` passes before merge.

## Consolidated Triage Checklist (2026-04-30)

**Disposition:** Ephemeral/superseded; transfer or archive.
**Evaluation basis:** Current `main` repository layout.

- [x] The in-monorepo `packages/agent-handoff-mcp/` and `packages/agent-orchestrator-mcp/` implementation directories are absent from current `main`.
- [x] Current agent instructions route MCP package verification to standalone external package refs rather than package-local monorepo tests.
- [ ] Query or review the external MCP package task/finding state for `MAINT-AOMCP-QUALITY-20260417` before declaring every slice closed.
- [ ] If any AOMCP quality finding remains open, move it to the external repo's task system instead of keeping this monorepo doc active.
- [ ] Archive this doc once the external-package status is confirmed or the residual work is transferred.
