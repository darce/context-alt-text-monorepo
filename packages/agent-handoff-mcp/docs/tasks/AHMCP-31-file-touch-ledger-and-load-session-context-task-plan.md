# AHMCP-31. File-Touch Ledger and load_session Context

> **Metadata**
>
> - **Date**: 2026-04-14
> - **Author**: GPT-5.4
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-31`
> - **Target Branch**: `feature/ahmcp-31-file-touch-ledger`
> - **Review Coverage Target**: 2

---

## Objective

Persist task-scoped file-touch records in `agent-handoff-mcp` and expose them through a dedicated query plus `load_session`, so cold-start handoff reads can see which files a task has touched without relying on `git diff` or rationale parsing.

## Problem Statement

The handoff ledger currently has no canonical task-level file-touch table. The closest existing surface is `decisions.changed_files_json`, but that only exists on decision rows and only when callers explicitly pass `changed_files` on `record_event(... event_kind="decision")` or `close_slice(...)`. Ordinary edits outside slice-complete writes do not land anywhere durable, and `load_session` currently returns only nested handoff state plus open findings. That leaves agents to infer touched files from git state, task-plan prose, or recent decisions, which is fragile at cold start and inconsistent across harnesses.

## Constraints

- Keep this task package-local to `agent-handoff-mcp`; do not wire `.claude/settings.json` or `.github/hooks/terminal-guard.json` in this task.
- No historical backfill from legacy `changed_files_json` rows; this MVP starts collecting new file touches only.
- Preserve the current `load_session` default contract; any `touched_files` addition must be additive.
- Support `change_kind` values `edit`, `add`, and `delete` in the DB schema and Python enum from day one, but do not require delete-hook coverage in this task.
- Keep the cold-start payload bounded and deterministic; `load_session` must not grow into an unbounded edit-history dump.

## Current State Analysis

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py` defines `handoff_state`, `decisions`, `blockers`, and related tables, but there is no `touched_files` table yet.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` implements `load_session()` as a compound helper that returns nested `state`, `open_findings`, and `open_findings_count`; it does not include file-touch context.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` exposes `load_session` in the tool registry, but there is no `record_file_touch` or `get_touched_files` tool today.
- `docs/agentic/contracts/agent-handoff-mcp.md` documents `load_session` as a two-part compound read (`get_handoff_state` + open findings). Adding file-touch context changes the public contract surface and must be documented.
- The active parent task `E17-4` already treats file-touch tracking as a package dependency and explicitly defers repo hook wiring until after this package task lands.

## Target Outcome

`agent-handoff-mcp` owns a durable, task-scoped file-touch ledger and exposes it through a small, explicit tool surface. Callers can record file touches during a task, query them directly, and receive a bounded `touched_files` list from `load_session()` at cold start. The package remains agnostic about how touches are produced; repo hook automation is a separate follow-up.

## Context Loading

- Rules: `docs/agentic/instructions.md`
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`
- Parent task dependency: `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md` Slice 4
- Scope intake: `docs/ideas/ahmcp-31-32-scope-note.md`
- Recorded intake decision: `1725` (`scope_intake_AHMCP-31_package_only_mvp`)

## Contract and Boundary Impact

| Boundary               | Owner        | Current Contract                                                  | Expected Change                                                                                                                                 | Compatibility Needed?                                  | Verification                                             |
| ---------------------- | ------------ | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------- |
| Schema                 | handoff core | No task-level file-touch table                                    | Add `touched_files` table, update `_HANDOFF_REQUIRED_TABLES`, keep file-touch storage out of FTS5, and bump schema version                      | Yes; warm-start migration must preserve existing DBs   | schema migration tests + doctor coverage + package suite |
| MCP tool surface       | handoff core | No file-touch tools; `load_session` returns state + findings only | Add `record_file_touch`, `get_touched_files`, and additive `load_session.data.touched_files`                                                    | Yes; existing `load_session` callers must keep working | tool registry tests + load-session regressions           |
| Python package surface | handoff core | No root export for file-touch helpers                             | Export the new helpers from the package root and add them to `__all__`                                                                          | Yes; additive                                          | import smoke coverage                                    |
| Contract docs          | repo docs    | `load_session` documented as two-part compound read               | Document the new file-touch tools and additive `touched_files` payload with explicit tool-table rows plus a `load_session` contract-note bullet | Yes; docs must match runtime                           | contract doc review                                      |

## Data Model and API Decisions

- `touched_files` is append-only. Each `record_file_touch(...)` call inserts one row; duplicate paths across calls are permitted and expected.
- MVP write shape is single-path-per-call. Batch recording is out of scope for this task; callers may invoke the tool multiple times.
- Table shape: `task_ref TEXT NOT NULL`, `file_path TEXT NOT NULL`, `change_kind TEXT NOT NULL CHECK (change_kind IN ('edit', 'add', 'delete'))`, optional `session`, optional `commit_sha`, and `touched_at TEXT NOT NULL DEFAULT (datetime('now'))`.
- Define a canonical Python `StrEnum` such as `ChangeKind` in `file_touches.py` so callers import values instead of scattering magic strings.
- `get_touched_files(..., limit: int = 20)` and `load_session(..., top_n_touched_files: int = 20)` both use the same bounded default, sourced from a module-level constant in `file_touches.py`, and return rows in stable `touched_at DESC, id DESC` order.
- `touched_files` does not get an FTS5 shadow table or triggers; exact-path reads are sufficient for this domain.

## Proposed Solution

Add a small file-touch domain to `agent-handoff-mcp`.

1. Extend the schema with a `touched_files` table keyed by `task_ref`, storing `file_path`, `change_kind`, optional `session`, optional `commit_sha`, and `touched_at`; update `_HANDOFF_REQUIRED_TABLES`; keep the table out of FTS5; and bump `HANDOFF_SCHEMA_VERSION`.
2. Introduce explicit write/read helpers for file touches, exposed as `record_file_touch(...)` and `get_touched_files(...)` through the package root, `__all__`, API registry, and MCP tool surface. For MVP, `record_file_touch(...)` is append-only and accepts one file path per call.
3. Extend `load_session(...)` so its response includes an additive `touched_files` list for the resolved task. The list is bounded by `top_n_touched_files: int = 20`, uses the same default constant as `get_touched_files(...)`, and returns newest-first stable ordering for cold-start use.
4. Update tests and contract docs so the new surface is verified across schema, direct Python calls, MCP tool registration, and contract-note text. In `docs/agentic/contracts/agent-handoff-mcp.md`, add tool-table rows for `record_file_touch` and `get_touched_files`, plus a `load_session` note documenting the additive bounded `touched_files` payload.

## Files and Surfaces to Change

| Surface                   | File                                                                | Change                                                                                                                               |
| ------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Schema DDL and migration  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py` | Add `touched_files` table, migration path, `_HANDOFF_REQUIRED_TABLES` update, explicit no-FTS decision, and schema-version bump      |
| File-touch domain helpers | `packages/agent-handoff-mcp/src/agent_handoff_mcp/file_touches.py`  | Add append-only storage/query helpers, `ChangeKind` `StrEnum`, and the shared default limit constant                                 |
| Core compound reads       | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`          | Extend `load_session` to include additive `touched_files` data                                                                       |
| Package/API exports       | `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py`      | Re-export file-touch helpers and add them to `__all__`                                                                               |
| MCP / CLI registry        | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`           | Register `record_file_touch` and `get_touched_files`; update `load_session` description                                              |
| Contract docs             | `docs/agentic/contracts/agent-handoff-mcp.md`                       | Add tool-table rows for `record_file_touch` and `get_touched_files`, plus a `load_session` note for additive bounded `touched_files` |
| Package docs              | `packages/agent-handoff-mcp/README.md`                              | Add file-touch tool usage and session-load behavior notes                                                                            |
| Regression tests          | `packages/agent-handoff-mcp/tests/test_handoff_state.py`            | Extend `load_session` coverage for additive `touched_files`                                                                          |
| Regression tests          | `packages/agent-handoff-mcp/tests/test_file_touches.py`             | Add direct storage/query coverage for recording and listing touched files                                                            |
| Regression tests          | `packages/agent-handoff-mcp/tests/test_schema_migrations.py`        | Add warm-start migration coverage for the version bump that introduces `touched_files`                                               |
| Transport/tool-list tests | `packages/agent-handoff-mcp/tests/test_stdio.py`                    | Verify tool registry includes the new file-touch tools                                                                               |
| Transport/tool-list tests | `packages/agent-handoff-mcp/tests/test_http.py`                     | Verify tool registry includes the new file-touch tools                                                                               |

## Related Files

| File                                                                       | Note                                                                                        |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/tests/conftest.py`                             | Existing package test bootstrap should continue to guard worktree-local imports             |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_write_context.py` | Not part of this task; file-touch recording stays independent from branch-enforcement logic |
| `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md`                    | Parent task that will consume this package work and later wire repo hook automation         |

## Verification Strategy

- Primary package verification:
  - `cd packages/agent-handoff-mcp && make test-handoff`
- Deterministic assertions to add:
  - Recording a touch for a task persists the row and returns the resolved `task_ref`
  - Querying touched files returns only rows for the requested task in stable `touched_at DESC, id DESC` order and honors the shared default limit of 20
  - `load_session(task_ref=..., top_n_touched_files=...)` includes additive `touched_files` without regressing `state`, `open_findings`, or `open_findings_count`
  - Existing databases migrate cleanly without any attempted backfill from `changed_files_json`
  - Warm-start migration coverage proves the version bump adds `touched_files` on an already-bootstrapped v3 database
- Manual package-level sanity check:
  - Record two file touches for a task, then call `load_session(task_ref=...)`; the response should include both file paths in `touched_files`

## Slice Delivery

### Slice 1: Add Schema and File-Touch Domain Surface

**Goal**: The package can persist and query task-scoped file-touch rows.

Changes:

- Add `touched_files` schema and migration logic, including `_HANDOFF_REQUIRED_TABLES` and explicit no-FTS handling
- Add append-only storage/query helpers plus the `ChangeKind` enum and shared default limit constant
- Export the helpers through the package root, `__all__`, and MCP registry
- Add direct regression tests for record/list behavior

Proof:

- `make test-handoff` passes with file-touch storage/query coverage
- Tool lists include `record_file_touch` and `get_touched_files`

### Slice 2: Extend load_session with File-Touch Context

**Goal**: Cold-start session loads include bounded file-touch context for the resolved task.

Changes:

- Extend `load_session` response data with additive `touched_files`
- Add `top_n_touched_files: int = 20` to keep the payload bounded by default
- Keep existing `state`, `open_findings`, and `open_findings_count` behavior stable
- Update tool descriptions, README, and contract docs to reflect the additive payload
- In the contract doc, add two tool-table rows and one `load_session` contract-note bullet matching the existing format
- Add regression coverage proving `load_session` still works for callers that do not care about file touches

Proof:

- `make test-handoff` passes with extended `load_session` assertions
- Contract docs and README match the live runtime behavior

### Slice 3: Keep the New Surface Bounded and MVP-Scoped

**Goal**: The package stores useful file-touch context without silently expanding into hook wiring or historical replay work.

Changes:

- Keep file-touch collection package-local; do not modify repo hook config in this task
- Do not backfill legacy decisions into the new table
- Keep delete automation and broader rollout as explicit follow-up work under E17-4
- Add regression coverage for bounded query behavior where needed
- Keep the surface single-path-per-call and append-only for MVP; batch writes remain explicit follow-up work

Proof:

- The new package tests pass without any root hook/config edits
- Scope exclusions remain documented in the task plan and contract notes

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the relevant rules, contracts, and parent-task dependency before implementation starts.
- [x] Kept the task package-local; no repo hook wiring is mixed into this branch.
- [x] Preserved additive compatibility for `load_session` callers.

### Checklist: Slice 1

- [x] `shared_schema.py` gains a `touched_files` table and migration path.
- [x] `shared_schema.py` updates `_HANDOFF_REQUIRED_TABLES` and keeps `touched_files` out of FTS5.
- [x] File-touch storage/query helpers are implemented and exported.
- [x] MCP tool registration exposes `record_file_touch` and `get_touched_files`.
- [x] Direct regression tests cover record/list behavior.

### Checklist: Slice 2

- [x] `load_session` includes additive `touched_files` data for the resolved task.
- [x] `load_session` uses `top_n_touched_files` with a shared default limit of 20.
- [x] Existing `load_session` fields remain backward-compatible.
- [x] README and contract docs describe the new payload shape.
- [x] Transport/tool-list tests cover the new tool registration.

### Checklist: Slice 3

- [x] No historical `changed_files_json` backfill is implemented.
- [x] No repo hook wiring is added in `.claude/settings.json` or `.github/hooks/terminal-guard.json`.
- [x] Delete-hook automation remains explicitly out of scope.
- [x] Query/output behavior stays bounded for cold-start use.
- [x] `record_file_touch` remains append-only and single-path-per-call for MVP.

## Review Readiness

- [x] The schema change has a deterministic migration test path.
- [x] The additive `load_session` change is covered by regression tests.
- [x] The contract doc matches the final tool names and payload shape.
- [x] The handoff decision records the implementation scope and verification evidence.

## Success Criteria

- [x] `agent-handoff-mcp` can durably record task-scoped file touches through an explicit tool surface.
- [x] `load_session(task_ref=...)` returns additive `touched_files` context for cold-start handoff reads.
- [x] The task ships without historical backfill or repo hook wiring.
- [x] The surface is explicit about `ChangeKind`, bounded defaults, and append-only write behavior.
- [x] `cd packages/agent-handoff-mcp && make test-handoff` passes on the task branch.
