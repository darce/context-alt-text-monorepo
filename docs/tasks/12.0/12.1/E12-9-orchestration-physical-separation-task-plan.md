# Task Plan

> **Metadata**
>
> - **Date**: 2026-03-29 22:00 EDT
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12
> - **Review Coverage Target**: 2

---

# E12-9. Orchestration Physical Separation

## Objective

Physically relocate all orchestration code out of `agent-handoff-mcp` so that the handoff package contains zero orchestration modules, zero orchestration CLI commands, and zero lane/worker/metrics CRUD. `agent-handoff-mcp` becomes a self-contained ledger package that can be installed and used without any orchestration dependency. `agent-orchestrator-mcp` owns all orchestration code and depends on `agent-handoff-mcp` as a library.

## Problem Statement

E12-5 and E12-6 accomplished the *logical* separation: handoff MCP exposes 27 tools, orchestrator MCP exposes 38, the tool registries are split, and `core.py` was decomposed into domain modules. But the *physical* separation was never completed:

1. **`orchestration/` directory** (33 files, ~450 KB) still lives inside `agent-handoff-mcp/src/agent_handoff_mcp/orchestration/`.
2. **Lane/worker/metrics CRUD** (`lanes.py`, plan cursor functions in `core.py`) still lives in `agent-handoff-mcp` — these are only used by the orchestrator MCP surface.
3. **Orchestration CLI commands** (~20 subcommands: `orchestrator-start`, `worker-start`, `lane-upsert`, `dispatch-lane-work`, `single-cycle`, `run-structured-turn`, etc.) still registered in `agent-handoff-mcp/cli.py`.
4. **`agent-orchestrator-mcp`** is entirely untracked in git and re-imports all implementation from `agent-handoff-mcp` via `_scripts_mcp_dir()` pointing back to `agent_handoff_mcp/orchestration/`.
5. **Orchestration wrapper functions** (`orchestrator_start`, `worker_start`, etc.) are duplicated in both `agent-handoff-mcp/api.py` and `agent-orchestrator-mcp/api.py`.

This means `agent-handoff-mcp` cannot be shipped as a standalone package — it drags 33 orchestration files and their transitive dependencies (subprocess, signal, fcntl, etc.) along.

## Constraints

- `core.py` must remain pure handoff-state CRUD per `rg-013`: no orchestration imports, no subprocess calls, no lock management.
- Orchestration modules must use late-binding (function-level) imports for `agent_handoff_mcp` symbols per `rg-014`.
- Both packages share `handoff.db` via SQLite WAL mode. Only one package should own writes to any given table.
- All existing tests must pass after each slice. Both `agent-handoff-mcp` (788+ tests) and `agent-orchestrator-mcp` (6+ tests) suites.
- `.mcp.json` and `.vscode/mcp.json` must remain functional after each slice.
- The `orchestration/` directory relocation must not break daemon subprocess invocations (orchestrator_daemon.py, worker_daemon.py are launched via `subprocess.Popen` with explicit script paths).

## Workflow Principles

- Each slice produces behavior plus proof. No scaffold-only slices.
- Move code, don't copy. After each move, the source location must not contain the moved code.
- Table ownership follows the write path: tables only orchestration writes to (`worktree_lanes`, `lane_messages`, `worker_reports`, `plan_cursors`, `turn_metrics`) belong in the orchestrator package.
- Schema DDL for orchestration-owned tables moves to orchestrator but uses `CREATE TABLE IF NOT EXISTS` for idempotent initialization on the shared DB.

## Terminology

- **Physical separation**: Code files physically reside in `agent-orchestrator-mcp`, not just re-exported via import aliases.
- **Orchestration CRUD**: Lane, worker report, turn metric, plan cursor, and lane message database operations — functions that exist in `lanes.py` and `core.py` today but are exclusively consumed by orchestrator tools.
- **Handoff ledger**: The core set of tables and operations that any agent needs regardless of orchestration: task state, decisions, review findings, artifacts, import/export, search.

## Current State Analysis

- `agent-handoff-mcp` MCP surface: 27 tools (correct — no orchestration tools exposed via MCP).
- `agent-handoff-mcp` CLI surface: ~50 subcommands including ~20 orchestration commands that should not be there.
- `agent-handoff-mcp/src/agent_handoff_mcp/orchestration/`: 33 Python files, ~450 KB of orchestration implementation.
- `agent-handoff-mcp/src/agent_handoff_mcp/lanes.py`: ~750 lines of lane/worker/metrics CRUD (18 functions).
- `agent-handoff-mcp/src/agent_handoff_mcp/core.py`: contains `upsert_plan_cursor`, `get_plan_cursor`, `list_plan_cursors` (~120 lines).
- `agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py`: 992 lines, all orchestration wrapper functions duplicated from `agent-handoff-mcp/api.py`, with `_scripts_mcp_dir()` pointing back to `agent_handoff_mcp/orchestration/`.
- `agent-orchestrator-mcp/` is untracked — never committed.

## Target Outcome

After all slices:

| Package | Contains | Does NOT contain |
| --- | --- | --- |
| `agent-handoff-mcp` | Task state, decisions, findings, artifacts, search, import/export, archive, close-check, `load_session`, `close_slice`, schema for ledger tables, CLI for ledger operations only | `orchestration/` dir, `lanes.py`, plan cursor CRUD, orchestration CLI commands, orchestration wrapper functions |
| `agent-orchestrator-mcp` | `orchestration/` dir (33 files), lane/worker/metrics CRUD, plan cursor CRUD, orchestration CLI commands, all daemon/dispatch/metrics wrapper functions, schema for orchestration tables | Duplicated code from handoff; direct SQL against ledger-only tables |

`agent-handoff-mcp` is installable and fully functional without `agent-orchestrator-mcp` present. `agent-orchestrator-mcp` declares `agent-handoff-mcp` as a dependency and imports ledger functions via its public API.

## Context Loading

- Rules: `docs/agentic/instructions.md` (rg-013, rg-014)
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`, `docs/agentic/contracts/agent-orchestrator-mcp.md`
- Prior work: E12-5 (`docs/tasks/12.0/12.1/E12-5-mcp-server-split-and-tool-consolidation-task-plan.md`) — logical split
- Prior work: E12-6 (`docs/tasks/12.0/12.1/E12-6-agent-handoff-mcp-internal-refactoring-task-plan.md`) — core.py decomposition
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` (orchestration wrappers to remove)
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` (orchestration CLI to remove)
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/lanes.py` (CRUD to relocate)
- Key source: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` (current wrapper state)

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `agent-handoff-mcp` MCP surface | agentic-tooling | `contracts/agent-handoff-mcp.md` | None — 27 tools unchanged | No | `doctor` tool_count = 27 |
| `agent-handoff-mcp` CLI surface | agentic-tooling | Convention | Remove ~20 orchestration subcommands | No — orchestrator CLI takes over | `agent-handoff-mcp --help` shows no orchestration commands |
| `agent-orchestrator-mcp` MCP surface | agentic-tooling | `contracts/agent-orchestrator-mcp.md` | None — 38 tools, now backed by local code | No | `doctor` tool_count = 38 |
| `agent-orchestrator-mcp` CLI surface | agentic-tooling | Convention | Absorb orchestration subcommands from handoff CLI | No — additive | `agent-orchestrator-mcp --help` shows orchestration commands |
| `mk/handoff.mk` | build-tooling | Convention | Remove orchestration targets | No — `mk/orchestrator.mk` owns them | `make` dry-run |
| `.mcp.json` / `.vscode/mcp.json` | dev-environment | `BOOTSTRAP.md` | No change — already registers both servers | No | Both servers start |

## Proposed Solution

Three slices, sequentially dependent:

1. **Detach and move** — strip all orchestration references from `agent-handoff-mcp` (CLI subcommands, API wrappers, re-exports in `api.py`, `core.py`, and `__init__.py`), then physically relocate `orchestration/`, `lanes.py`, and plan cursor CRUD to `agent-orchestrator-mcp`. CLI/API detachment must happen first within this slice to avoid an import-broken intermediate state when files are deleted.
2. **Add orchestration CLI to `agent-orchestrator-mcp`** — wire all commands removed from `agent-handoff-mcp` into `agent-orchestrator-mcp/cli.py` so they remain accessible via the orchestrator binary.
3. **Verification and cleanup** — end-to-end validation, import audit, remove dead code, verify both packages are independently installable.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/` | Delete entire directory |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/lanes.py` | Move to orchestrator package |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Remove `from .lanes import` re-export block (16 symbols, lines 64-71); remove plan cursor CRUD (3 functions) |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Remove orchestration wrapper functions (~570 lines), remove orchestration re-exports |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | Remove ~20 orchestration CLI subcommands |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | Remove lane/worker/metrics/plan-cursor exports |
| backend | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/` | Receive moved files |
| backend | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py` | Receive moved file |
| backend | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | Replace re-imports with local imports; remove `_scripts_mcp_dir()` indirection |
| backend | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/cli.py` | Add orchestration CLI subcommands |
| tests | `packages/agent-handoff-mcp/tests/` | Update imports; move orchestration-specific tests |
| tests | `packages/agent-orchestrator-mcp/tests/` | Receive moved tests; add new integration tests |
| tooling | `mk/handoff.mk` | Remove orchestration targets (if any remain) |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/enums.py` | Shared enums; stays in handoff, imported by orchestrator |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py` | `RuntimeConfig`; stays in handoff, imported by orchestrator |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` | Schema + DB helpers; orchestration tables DDL must move out |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` | Stays in handoff; orchestrator imports `reconcile_review_findings` and `get_review_findings_summary` |
| `packages/agent-handoff-mcp/tests/test_worker_daemon.py` | Must move to orchestrator tests |
| `packages/agent-handoff-mcp/tests/test_review_runner.py` | Must move to orchestrator tests |
| `packages/agent-handoff-mcp/tests/test_lane_prompt_artifacts.py` | Must move to orchestrator tests |

## Verification Strategy

- Deterministic tests:
  - `cd packages/agent-handoff-mcp && python -m pytest tests/ -x -q` (all handoff tests pass)
  - `cd packages/agent-orchestrator-mcp && python -m pytest tests/ -x -q` (all orchestrator tests pass)
- Runtime-parity checks:
  - `agent-handoff-mcp --workspace-root . doctor` — tool_count = 27; no orchestration subcommands in `--help`
  - `agent-orchestrator-mcp --workspace-root . doctor` — tool_count = 38
- Independence check:
  - `python -c "import agent_handoff_mcp"` succeeds without `agent-orchestrator-mcp` installed
  - `grep -r "from agent_handoff_mcp.orchestration" packages/agent-handoff-mcp/` returns zero matches
  - `grep -r "from agent_handoff_mcp.lanes" packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` returns zero matches
- Contract verification:
  - Grep orchestration tool names in `agent-handoff-mcp` CLI `--help`; zero matches
  - Both MCP servers connect simultaneously in Claude Code via `.mcp.json`

## Slice Delivery

### Slice 1: Move Orchestration Implementation

**Goal**: Physically relocate `orchestration/`, `lanes.py`, and plan cursor CRUD from `agent-handoff-mcp` to `agent-orchestrator-mcp` so all orchestration code lives in one package.

> **Prerequisite doc updates (do first in this slice):** `docs/agentic/contracts/agent-handoff-mcp.md` and `docs/agentic/BOOTSTRAP.md` still advertise ≤22 tools; the actual MCP surface is 27. Update both docs before making code changes so proof points in this plan are consistent with the prerequisite boundary docs.

Changes:

**Step 1 — Detach orchestration from `agent-handoff-mcp` CLI and API (must happen before physical file deletion to avoid an import-broken intermediate state):**

- Remove orchestration CLI subcommands from `agent-handoff-mcp/cli.py`: `orchestrator-start`, `orchestrator-status`, `orchestrator-stop`, `orchestrator-pause`, `orchestrator-resume`, `worker-start`, `worker-status`, `worker-stop`, `worker-resume`, `worker-start-all`, `worker-event-history`, `lane-upsert`, `lane-list`, `lane-activity`, `lane-report`, `lane-report-list`, `lane-message`, `lane-brief`, `lane-message-update`, `lane-message-list`, `lane-brief-list`, `dispatch-lane-work`, `run-structured-turn`, `single-cycle`, `review-summary`, `switch`.
- Remove orchestration wrapper functions from `agent-handoff-mcp/api.py`: `orchestrator_start`, `orchestrator_status`, `orchestrator_stop`, `orchestrator_pause`, `orchestrator_resume`, `orchestrator_single_cycle`, `worker_start`, `worker_status`, `worker_event_history`, `worker_stop`, `worker_resume`, `worker_start_all`, `manage_worker`, `run_structured_turn`, `dispatch_lane_work`, `list_available_backends`, `get_metrics_summary`, and all supporting helpers (`_scripts_mcp_dir`, `_import_scripts_mcp_module`, `_handoff_pythonpath`, `_orchestrator_paths`, `_worker_paths`, `_worker_lane_config`, `_read_lock_pid`, `_pid_is_running`, `_last_log_event`, `_count_log_events`). Remove all orchestrator-owned re-exports — the complete set is: `switch_task`, `get_latest_slice_review_packet`, `get_lane_activity`, `list_lane_messages`, `record_worker_report`, `upsert_worktree_lane`, `record_turn_metric`, `close_worktree_lane`, `list_worktree_lanes`, `list_lane_briefs`, `record_lane_message`, `record_lane_brief`, `update_lane_message`, `list_worker_reports`, `upsert_plan_cursor`, `get_plan_cursor`, `list_plan_cursors`, `list_turn_metrics`, `get_turn_metrics_summary`, `get_review_findings_summary`, `reconcile_review_findings`. Remove matching `TOOL_DESCRIPTIONS` entries for all 21.
- Remove the `from .lanes import (...)` block from `agent-handoff-mcp/core.py` (the 16-symbol block at lines 64-71: `_get_lane_row`, `upsert_worktree_lane`, `close_worktree_lane`, `list_worktree_lanes`, `record_turn_metric`, `list_turn_metrics`, `get_turn_metrics_summary`, `get_lane_activity`, `get_latest_slice_review_packet`, `record_worker_report`, `list_worker_reports`, `record_lane_message`, `record_lane_brief`, `update_lane_message`, `list_lane_messages`, `list_lane_briefs`). This block must be removed before `lanes.py` is physically moved in Step 2 or `core.py` will break on import.
- Remove from `agent-handoff-mcp/__init__.py`: (a) all 21 orchestration re-exports listed above, (b) `from .orchestration.slice_review_packet import SliceReviewPacket` (line 3), and (c) the `SliceReviewPacket` entry from `__all__`. The `SliceReviewPacket` import must be removed before Step 2 moves `orchestration/` or `__init__.py` breaks on import.
- Verify `agent-handoff-mcp` imports cleanly (`python -c "import agent_handoff_mcp"`) after this step before proceeding to physical file moves.

**Step 2 — Physical relocation:**

- Move `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/` (33 files) to `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/`.
- Move `packages/agent-handoff-mcp/src/agent_handoff_mcp/lanes.py` to `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py`.
- Move `upsert_plan_cursor`, `get_plan_cursor`, `list_plan_cursors` from `agent-handoff-mcp/core.py` to a new `agent-orchestrator-mcp/plan_cursors.py` (or into orchestrator's `lanes.py`).
- Move orchestration-owned schema DDL (`CREATE TABLE` for `worktree_lanes`, `lane_messages`, `worker_reports`, `plan_cursors`, `turn_metrics`) from `agent-handoff-mcp/_shared.py` to orchestrator. Use `CREATE TABLE IF NOT EXISTS` for idempotent init.
- Update all internal imports within the moved `orchestration/` files: `from agent_handoff_mcp.orchestration.X` becomes relative imports within `agent_orchestrator_mcp.orchestration.X`.
- Update `agent-orchestrator-mcp/api.py`: replace `_scripts_mcp_dir()` / `_import_scripts_mcp_module()` with direct imports from `agent_orchestrator_mcp.orchestration.*`. Replace re-exports of CRUD functions (`upsert_worktree_lane = core.upsert_worktree_lane`) with imports from `agent_orchestrator_mcp.lanes`.
- Update `agent-orchestrator-mcp/pyproject.toml` if new dependencies are needed.
- Move orchestration-specific tests (`test_worker_daemon.py`, `test_review_runner.py`, `test_lane_prompt_artifacts.py`, and any others that test orchestration modules) to `packages/agent-orchestrator-mcp/tests/`.

Proof:

- `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- `python -m pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes
- `ls packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/` returns "No such file or directory"
- `ls packages/agent-handoff-mcp/src/agent_handoff_mcp/lanes.py` returns "No such file or directory"
- `grep -rn "from agent_handoff_mcp.orchestration" packages/agent-orchestrator-mcp/src/` returns zero matches (all imports are now local)
- `agent-handoff-mcp --help` shows only ledger commands (~27 subcommands: `serve-stdio`, `serve-http`, `doctor`, `dashboard`, `set`, `state`, `decision`, `action`, `test`, `blocker`, `review-record`, `review-update`, `review-list`, `review-run-record`, `review-run-list`, `review-coverage`, `handoff-close-check`, `task`, `export`, `import`, `archive`, `audit-decisions`, `artifact-record`, `artifact-search`, `artifact-get`, `artifact-purge`, `handoff-search`)
- `grep -n "orchestrator_start\|worker_start\|_scripts_mcp\|switch_task\|upsert_worktree_lane" packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` returns zero matches
- `grep -n "from .lanes import\|from .orchestration" packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` returns zero matches
- `grep -n "SliceReviewPacket\|from .orchestration" packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` returns zero matches
- `agent-handoff-mcp doctor` tool_count = 27
- `agent-orchestrator-mcp doctor` tool_count = 38

### Slice 2: Add Orchestration CLI to `agent-orchestrator-mcp`

**Goal**: Wire the orchestration CLI into `agent-orchestrator-mcp` so the commands removed from `agent-handoff-mcp` in Slice 1 are now accessible via the orchestrator binary.

Changes:

- Add orchestration CLI subcommands to `agent-orchestrator-mcp/cli.py` (currently only has `serve` and `doctor`). Mirror all commands removed from `agent-handoff-mcp` in Slice 1: `orchestrator-start`, `orchestrator-status`, `orchestrator-stop`, `orchestrator-pause`, `orchestrator-resume`, `worker-start`, `worker-status`, `worker-stop`, `worker-resume`, `worker-start-all`, `worker-event-history`, `lane-upsert`, `lane-list`, `lane-activity`, `lane-report`, `lane-report-list`, `lane-message`, `lane-brief`, `lane-message-update`, `lane-message-list`, `lane-brief-list`, `dispatch-lane-work`, `run-structured-turn`, `single-cycle`, `review-summary`, `switch`.
- Verify `mk/handoff.mk` has no references to orchestration targets; ensure `mk/orchestrator.mk` covers them.

Proof:

- `agent-orchestrator-mcp --help` shows all orchestration commands
- `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- `python -m pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes

### Slice 3: Verification and Cleanup

**Goal**: End-to-end validation that both packages are independently functional, no dead code remains, and the separation is complete.

Changes:

- Run both `doctor` commands; verify tool counts (27 and 38).
- Verify `agent-handoff-mcp` has zero imports from `orchestration` or `lanes`:
  - `grep -r "from agent_handoff_mcp.orchestration" packages/agent-handoff-mcp/` → zero
  - `grep -r "from agent_handoff_mcp.lanes" packages/agent-handoff-mcp/src/agent_handoff_mcp/` → zero
  - `grep -r "import lanes" packages/agent-handoff-mcp/src/agent_handoff_mcp/` → zero
- Verify `agent-orchestrator-mcp` does not use `_scripts_mcp_dir()` or `_import_scripts_mcp_module()`:
  - `grep -r "_scripts_mcp_dir\|_import_scripts_mcp_module" packages/agent-orchestrator-mcp/` → zero
- Verify both servers start simultaneously without DB contention via `.mcp.json`.
- Remove any dead imports, unused helper functions, or orphaned test fixtures in both packages.
- Update `docs/agentic/contracts/agent-handoff-mcp.md`: remove any remaining references to orchestration CLI commands.
- Update `docs/agentic/contracts/agent-orchestrator-mcp.md`: document CLI surface.
- Update `CLAUDE.md` rg-013/rg-014 scope if needed.

Proof:

- `agent-handoff-mcp doctor` tool_count = 27
- `agent-orchestrator-mcp doctor` tool_count = 38
- `python -c "import agent_handoff_mcp; print(hasattr(agent_handoff_mcp, 'upsert_worktree_lane'))"` prints `False`
- `python -c "import agent_orchestrator_mcp; print('ok')"` succeeds
- Both servers connect in Claude Code simultaneously
- All tests pass in both packages

---

# Consolidated Checklist

## Context and Ownership

- [ ] Loaded `rg-013`, `rg-014` from `instructions.md`.
- [ ] Read E12-5 and E12-6 completion state for context.
- [ ] Verified current tool counts: handoff=27, orchestrator=38.
- [ ] Confirmed `orchestration/` directory contents before move.

## Slice 1: Detach and Move

- [ ] **Step 1 (detach first):** Orchestration CLI subcommands removed from `agent-handoff-mcp/cli.py`
- [ ] **Step 1:** All 21 orchestration re-exports removed from `agent-handoff-mcp/api.py` (wrapper functions + CRUD re-exports + `TOOL_DESCRIPTIONS` entries)
- [ ] **Step 1:** `from .lanes import (...)` block removed from `agent-handoff-mcp/core.py` (lines 64-71, 16 symbols)
- [ ] **Step 1:** `SliceReviewPacket` import and `__all__` entry removed from `agent-handoff-mcp/__init__.py`
- [ ] **Step 1:** `agent-handoff-mcp` imports cleanly after detach (`python -c "import agent_handoff_mcp"` succeeds)
- [ ] **Step 2:** `orchestration/` directory moved to `agent-orchestrator-mcp`
- [ ] **Step 2:** `lanes.py` moved to `agent-orchestrator-mcp`
- [ ] **Step 2:** Plan cursor CRUD moved to `agent-orchestrator-mcp`
- [ ] **Step 2:** Orchestration table DDL moved to orchestrator schema init
- [ ] **Step 2:** All internal imports within moved files updated
- [ ] **Step 2:** `agent-orchestrator-mcp/api.py` uses direct local imports (no `_scripts_mcp_dir`)
- [ ] **Step 2:** Orchestration tests moved to `agent-orchestrator-mcp/tests/`
- [ ] `pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- [ ] `pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes
- [ ] `agent-handoff-mcp` contains zero files under `orchestration/`

## Slice 2: Add Orchestration CLI to `agent-orchestrator-mcp`

- [ ] Orchestration CLI subcommands added to `agent-orchestrator-mcp/cli.py`
- [ ] `mk/handoff.mk` has no orchestration targets
- [ ] `agent-handoff-mcp --help` shows only ledger commands
- [ ] `agent-orchestrator-mcp --help` shows orchestration commands
- [ ] Both test suites pass

## Slice 3: Verification and Cleanup

- [ ] Both `doctor` commands pass with correct tool counts
- [ ] Zero cross-package orchestration imports in handoff
- [ ] Zero `_scripts_mcp_dir` references in orchestrator
- [ ] Both servers start simultaneously via `.mcp.json`
- [ ] Dead code removed from both packages
- [ ] Contract docs updated
- [ ] Both test suites pass

## Review Readiness

- [ ] No boundary-touching implementation without matching contract/doc evidence.
- [ ] Runtime-parity checks included.
- [ ] Handoff decision recorded per slice.

## Stretch Goals

- [ ] Extract `enums.py` and `config.py` into a shared `agent-handoff-core` base package (deferred from E12-5)
- [ ] Add `agent-orchestrator-mcp` to CI pipeline alongside `agent-handoff-mcp`

## Success Criteria

- [ ] `agent-handoff-mcp` has zero files under `orchestration/`, zero `lanes.py`, zero plan cursor CRUD
- [ ] `agent-handoff-mcp` CLI shows only ledger commands (~25 subcommands)
- [ ] `agent-handoff-mcp` is installable and passes all tests without `agent-orchestrator-mcp`
- [ ] `agent-orchestrator-mcp` owns all orchestration code (33+ files) and passes all tests
- [ ] `agent-orchestrator-mcp` declares `agent-handoff-mcp` as a dependency and imports ledger functions via public API
- [ ] Both MCP servers connect simultaneously with correct tool counts (27 and 38)
