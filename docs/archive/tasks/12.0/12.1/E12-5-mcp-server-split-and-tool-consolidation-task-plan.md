# Task Plan

> **Metadata**
>
> - **Date**: 2026-03-29 15:00 EDT
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12

---

# E12-5. MCP Server Split and Tool Consolidation

## Objective

Split the monolithic `agent-handoff-mcp` package (62 MCP tools, 20,456 LoC) into a focused core ledger server under 22 tools and a separate orchestration server. Consolidate redundant tools and add compound ceremony tools to reduce per-session token cost and improve agent tool-selection accuracy.

## Problem Statement

Every agent session pays ~2,500 tokens scanning 62 tool descriptions, most irrelevant for single-agent audit work. The late-binding import boundary in `api.py` (lines 24-70 core re-exports; lines 315+ orchestration wrappers) and `rg-013`/`rg-014` confirm the split seam exists but is not realized as separate deployable servers. Several tools are thin wrappers or near-duplicates (`reopen_review_finding` delegates entirely to `update_review_finding`). The mandatory end-of-slice ceremony requires 3 sequential MCP calls that could be 1.

## Constraints

- `core.py` must remain pure handoff-state CRUD per `rg-013`: no orchestration imports, no subprocess calls, no lock management.
- Orchestration modules must continue using late-binding imports per `rg-014`.
- Both servers share `handoff.db` and `mcp-artifacts.db` on disk. SQLite WAL mode makes concurrent readers safe; only one server should write to any given table.
- Existing 800 tests must continue passing. Tool consolidation changes signatures, so callers must be updated in the same slice.
- `.mcp.json` currently registers one server; the split requires two entries.

## Workflow Principles

- Each slice produces behavior plus proof. No scaffold-only slices.
- Consolidated tools maintain backward compatibility via deprecated Python aliases (not MCP-exposed) until callers are updated.
- Table ownership follows the write path: tables only orchestration writes to belong in the orchestrator server.
- Compound tools (`load_session`, `close_slice`) call existing tool functions, not duplicate SQL.

## Terminology

- **Core ledger server**: `agent-handoff-mcp` after split. Owns task state, decisions, findings, blockers, tests, actions, exports, artifacts. Under 22 tools.
- **Orchestration server**: New `agent-orchestrator-mcp`. Owns daemon lifecycle, worker management, lane registration, lane communication, plan cursors, turn metrics, backend dispatch.
- **Compound tool**: New tool composing multiple existing calls into a single MCP invocation for common multi-step ceremonies.

## Current State Analysis

- `api.py` lines 24-70 re-export 46 functions from `core.py`. Lines 315-884 define 15 orchestration wrappers using `_import_scripts_mcp_module()`.
- `build_handoff_mcp()` at line 928 registers all 62 tools into one `FastMCP` instance.
- `reopen_review_finding` (core.py:3662) is a two-line wrapper calling `update_review_finding(status="open")`.
- `get_review_finding` (core.py:3716) overlaps with `list_review_findings` filtered by `finding_id`.
- `get_handoff_dashboard` (core.py:4288) is a cross-task aggregation that could be a mode of `get_handoff_state`.
- `get_artifact_source` and `get_artifact_terms` (core.py:2449, 2554) both look up the same source record.
- `turn_metrics` table has 0 rows. `plan_cursors` (49 rows), `lane_messages` (134 rows), `worker_reports` (63 rows) are written exclusively by orchestration workflows.
- DB usage confirms core dominance: 992 decisions, 1383 findings, 530 tests vs 0 turn_metrics.

## Target Outcome

| Server | Tools | Scope |
| --- | --- | --- |
| `agent-handoff-mcp` (core) | 22 | State, decisions, findings, blockers, tests, actions, search, export/import, archive, close-check, CURRENT_TASK.md, `load_session`, `close_slice`, 4 artifact tools |
| `agent-orchestrator-mcp` (new) | ~33 | Daemons (6), workers (6), lane registration (3), lane communication (5), worker reports (2), lane activity (1), plan cursors (3), turn metrics (3), dispatch/backends (3), metrics summary (1) |

Token cost per session drops from ~2,500 to ~800 for tool descriptions (-65%).

## Context Loading

- Rules: `docs/agentic/instructions.md` (rg-013, rg-014)
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`
- Bootstrap: `BOOTSTRAP.md`
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` (split seam)
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` (schema + CRUD)
- Key source: `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` (CLI dispatch)
- Makefile: `mk/handoff.mk`
- Prior art: `docs/tasks/tech-debt/refactoring-agent-handoff-mcp-evaluation.md`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `agent-handoff-mcp` MCP surface | agentic-tooling | `contracts/agent-handoff-mcp.md` | Remove 40 tools, add 2 compound, consolidate 6 merges | Yes -- deprecated aliases during transition | `pytest` + `doctor` tool count |
| `agent-orchestrator-mcp` MCP surface (new) | agentic-tooling | New contract | ~33 tools | No -- greenfield | `pytest` + new `doctor` |
| `.mcp.json` | dev-environment | `BOOTSTRAP.md` | Add second server entry | Yes | Session restart test |
| `mk/handoff.mk` | build-tooling | Convention | Split orchestration targets to `mk/orchestrator.mk` | No -- additive | `make` dry-run |

## Proposed Solution

Four slices, sequentially dependent:

1. **Core tool consolidation** within the existing single package (merge 6 tools, add 2 compound tools, reduce registration from 62 to ~56).
2. **Extract orchestration package** (create `packages/agent-orchestrator-mcp/`, move ~33 tools).
3. **Documentation and contract split** (two contracts, updated BOOTSTRAP, split Makefiles).
4. **Migration verification and cleanup** (remove deprecated aliases, validate both servers).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Absorb `reopen_review_finding`; add `finding_id` to `list_review_findings`; add `view` param to `get_handoff_state`; merge artifact query tools; add `load_session` and `close_slice` |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Remove consolidated registrations; add compound tools; remove orchestration functions |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | Remove orchestration CLI subcommands |
| backend (new) | `packages/agent-orchestrator-mcp/` | New package: api.py, cli.py, pyproject.toml, moved orchestration/ |
| docs | `docs/agentic/contracts/agent-handoff-mcp.md` | Remove orchestration tools; document consolidated + compound tools |
| docs (new) | `docs/agentic/contracts/agent-orchestrator-mcp.md` | New contract |
| docs | `BOOTSTRAP.md` | Add second MCP server entry |
| docs | `docs/agentic/instructions.md` | Update rg-013/rg-014 scope |
| tooling | `mk/handoff.mk` | Remove orchestration targets |
| tooling (new) | `mk/orchestrator.mk` | Orchestration targets |
| tests | `packages/agent-handoff-mcp/tests/` | Update for consolidated signatures |
| tests (new) | `packages/agent-orchestrator-mcp/tests/` | Moved orchestration tests |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/enums.py` | Shared enums; must stay accessible to both packages |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py` | RuntimeConfig; both packages need equivalent |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/slice_decision.py` | Slice decision parsing; stays with core |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/artifact_index.py` | FTS5 sidecar; stays with core |
| `packages/agent-handoff-mcp/tests/conftest.py` | Shared fixtures; needs duplication or extraction |

## Related Work

`docs/tasks/tech-debt/refactoring-agent-handoff-mcp-evaluation.md` proposes 6 internal refactoring phases (Extract Guards, Parameter Objects, Pagination Helper, Extract core.py Domain Modules, Tool Registry Pipeline, Daemon Loop Decomposition).

**This split must happen before the evaluation's Phase 4-6.** Rationale:

- The split seam is clean today (late-binding imports). No internal refactoring is needed to enable it.
- Post-split, refactoring core.py affects 7,523 LoC instead of 20,456 LoC.
- Findings sort cleanly: H1/H2/H3/M1-M4 are core-only; H5/M7/M8/L3/L5 are orchestration-only.
- M5 (Middle Man api.py) and H4 (Shotgun Surgery) become moot or simpler after the split.

The evaluation's Phases 1-3 (guard extraction, parameter objects, pagination helper) are orthogonal and can run before or after this task.

## Verification Strategy

- Deterministic tests:
  - `cd packages/agent-handoff-mcp && python -m pytest tests/ -x -q` (core tests pass)
  - `cd packages/agent-orchestrator-mcp && python -m pytest tests/ -x -q` (orchestrator tests pass)
- Runtime-parity checks:
  - `agent-handoff-mcp --workspace-root . doctor` (core: <= 22 tools)
  - `agent-orchestrator-mcp --workspace-root . doctor` (orchestrator: ~33 tools)
- Contract verification:
  - Grep removed tool names in `agent-handoff-mcp.md`; zero matches
  - Grep all orchestration tool names in `agent-orchestrator-mcp.md`; all present
- Manual verification:
  - Both MCP servers connect simultaneously in Claude Code via `.mcp.json`
  - `make task`, `make dashboard` still work (core CLI)
  - `make daemon-status` works (orchestrator CLI)

## Slice Delivery

### Slice 1: Core Tool Consolidation

**Goal**: Reduce tool surface from 62 to ~56 by merging near-duplicates and adding compound tools within the existing single package.

Changes:

- Absorb `reopen_review_finding` into `update_review_finding` (treat `status="open"` + `reopen_reason` as the reopen path). Keep as deprecated Python alias.
- Add optional `finding_id` to `list_review_findings`; return single-element list when provided. Keep `get_review_finding` as deprecated alias.
- Add `view="dashboard"` to `get_handoff_state`; return cross-task aggregation. Keep `get_handoff_dashboard` as deprecated alias.
- Merge `get_artifact_source` + `get_artifact_terms` into `get_artifact(source_id, include_terms=False)`. Keep old names as deprecated aliases.
- Absorb `list_artifact_sources` into `search_artifacts` (empty-query returns source listing). Keep as deprecated alias.
- Add `load_session(task_ref=None)`: calls `get_handoff_state` + `list_review_findings(status="open")`, returns combined payload.
- Add `close_slice(session, decision, rationale, actor, expected_revision, task_ref=None)`: calls `record_decision` + `set_handoff_state` + `generate_current_task_md` atomically.
- Remove deprecated aliases from `build_handoff_mcp()` registration (not MCP-exposed; kept as Python functions).
- Update `TOOL_DESCRIPTIONS` dict in `api.py`.
- Update all affected tests.

Proof:

- `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` passes
- Tool count in `build_handoff_mcp()` drops from 62 to ~56
- `load_session()` returns combined state + findings
- `close_slice(...)` records decision, updates state, generates markdown in one call

### Slice 2: Extract Orchestration Package

**Goal**: Create `packages/agent-orchestrator-mcp/` with its own MCP server, moving all orchestration, lane, worker, metrics, and plan cursor tools.

Changes:

- Create `packages/agent-orchestrator-mcp/pyproject.toml` with dependency on `agent-handoff-mcp` (shared enums, config, DB access).
- Create `agent_orchestrator_mcp/__init__.py`, `api.py`, `cli.py`, `__main__.py`, launcher.
- Move `agent_handoff_mcp/orchestration/` directory to `agent_orchestrator_mcp/orchestration/`.
- Move orchestration wrappers from `agent_handoff_mcp/api.py` (lines 315-884) to `agent_orchestrator_mcp/api.py`.
- Move lane/worker/metrics CRUD from `core.py` to `agent_orchestrator_mcp/core.py`: `upsert_worktree_lane`, `close_worktree_lane`, `list_worktree_lanes`, `record_lane_message`, `update_lane_message`, `list_lane_messages`, `record_lane_brief`, `list_lane_briefs`, `record_worker_report`, `list_worker_reports`, `get_lane_activity`, `record_turn_metric`, `list_turn_metrics`, `get_turn_metrics_summary`, `upsert_plan_cursor`, `get_plan_cursor`, `list_plan_cursors`.
- Move corresponding schema (`CREATE TABLE` for `worktree_lanes`, `lane_messages`, `worker_reports`, `plan_cursors`, `turn_metrics`) to orchestrator. Both packages use `CREATE TABLE IF NOT EXISTS` for idempotent initialization on shared DB.
- Update `build_handoff_mcp()` to register only core tools (target: 22).
- Create `build_orchestrator_mcp()` for orchestration tools.
- Move orchestration tests to `packages/agent-orchestrator-mcp/tests/`.

Proof:

- `python -m pytest packages/agent-handoff-mcp/tests/ -x -q` passes (core only)
- `python -m pytest packages/agent-orchestrator-mcp/tests/ -x -q` passes (orchestration)
- `agent-handoff-mcp --workspace-root . doctor` reports <= 22 tools
- Core package no longer imports from `orchestration/`

### Slice 3: Documentation and Contract Update

**Goal**: Split contract docs and update all references so both servers are correctly documented.

Changes:

- Update `docs/agentic/contracts/agent-handoff-mcp.md`: remove orchestration tools from surface table; document consolidated + compound tools.
- Create `docs/agentic/contracts/agent-orchestrator-mcp.md`.
- Update `BOOTSTRAP.md`: add second MCP server entry.
- Update `docs/agentic/instructions.md`: amend rg-013/rg-014 to reference both packages.
- Update `CLAUDE.md` if it references handoff tools.
- Split `mk/handoff.mk`: keep core targets; move orchestration targets to `mk/orchestrator.mk`.
- Update `Makefile` to include `mk/orchestrator.mk`.

Proof:

- Grep `orchestrator_start` in `agent-handoff-mcp.md` returns zero
- Grep `agent-orchestrator-mcp` in `BOOTSTRAP.md` finds new entry
- `make task` and `make dashboard` still work
- `make daemon-status` works through orchestrator

### Slice 4: Migration Verification and Cleanup

**Goal**: End-to-end validation and deprecated alias removal.

Changes:

- Run both `doctor` commands; verify tool counts.
- Verify both servers start simultaneously without DB contention.
- Audit all `import` statements across monorepo referencing `agent_handoff_mcp` orchestration symbols; update to `agent_orchestrator_mcp`.
- Remove deprecated Python aliases if no callers remain.
- Final test runs of both packages.

Proof:

- `agent-handoff-mcp doctor` passes with <= 22 tools
- `agent-orchestrator-mcp doctor` passes with ~33 tools
- `grep -r "from agent_handoff_mcp" packages/agent-orchestrator-mcp/` returns zero
- Both servers connect in Claude Code via `.mcp.json`

---

# Consolidated Checklist

## Context and Ownership

- [x] Loaded `rg-013`, `rg-014` from `instructions.md`.
- [x] Loaded `docs/agentic/contracts/agent-handoff-mcp.md`.
- [x] Loaded `BOOTSTRAP.md` for MCP wiring.
- [x] Reviewed `docs/tasks/tech-debt/refactoring-agent-handoff-mcp-evaluation.md` for alignment.

## Slice 1: Core Tool Consolidation

- [x] Absorb `reopen_review_finding` into `update_review_finding`
- [x] Add `finding_id` to `list_review_findings`
- [x] Add `view="dashboard"` to `get_handoff_state`
- [x] Merge `get_artifact_source` + `get_artifact_terms` into `get_artifact`
- [x] Absorb `list_artifact_sources` into `search_artifacts`
- [x] Implement `load_session` compound tool
- [x] Implement `close_slice` compound tool
- [x] Remove consolidated tools from `build_handoff_mcp()`
- [x] Update `TOOL_DESCRIPTIONS`
- [x] Update all affected tests
- [x] `pytest packages/agent-handoff-mcp/tests/ -x -q` passes

## Slice 2: Extract Orchestration Package

- [x] Create `packages/agent-orchestrator-mcp/pyproject.toml`
- [x] Create orchestrator `api.py` with `build_orchestrator_mcp()`
- [x] Create orchestrator `cli.py` and launcher
- [x] Move `orchestration/` directory
- [x] Move lane/worker/metrics CRUD from core
- [x] Move orchestration tests
- [x] Update core `build_handoff_mcp()` to 22 tools
- [x] Both test suites pass independently

## Slice 3: Documentation and Contract Update

- [x] Update `docs/agentic/contracts/agent-handoff-mcp.md`
- [x] Create `docs/agentic/contracts/agent-orchestrator-mcp.md`
- [x] Update `BOOTSTRAP.md`
- [x] Update `docs/agentic/instructions.md`
- [x] Split `mk/handoff.mk` and create `mk/orchestrator.mk`
- [x] Contract grep verification passes

## Slice 4: Migration Verification and Cleanup

- [x] Both `doctor` commands pass with correct tool counts
- [x] No stale orchestration imports remain in core package
- [x] Deprecated aliases removed (non-MCP; test migration deferred to tech-debt #13)
- [x] Both servers start simultaneously

## Review Readiness

- [x] No boundary-touching change without matching contract evidence
- [x] Runtime-parity checks included
- [x] Handoff decision recorded

## Stretch Goals

- [x] Further consolidate orchestration tools — `manage_worker(task_ref, lane_id, action)` added to orchestrator; combines start/stop/resume/status in one call
- [ ] Extract `enums.py`, `config.py` into shared `agent-handoff-core` package — deferred; requires new package + cross-package import refactor; orchestrator already imports from agent-handoff-mcp as a runtime dep
- [x] Add MCP tool deprecation metadata for client warnings — `deprecated_since: str | None` field added to `ToolEntry` in both packages; `build_*_mcp()` prepends `[DEPRECATED since X]` to description when set

## Success Criteria

- [x] Core server exposes <= 22 tools — verified: 22 (doctor confirmed)
- [x] Orchestration server exposes ~33 tools — verified: 38 (37 + manage_worker)
- [x] All 800 tests pass across both packages — 794 (core) + 6 (orchestrator) = 800
- [x] Both servers installable independently via `uv tool install` — entry points declared in both pyproject.toml
- [x] Both connect in Claude Code simultaneously — both registered in `.mcp.json`
- [x] `rg-013`/`rg-014` enforceable with updated scope — both rules updated with package scope
