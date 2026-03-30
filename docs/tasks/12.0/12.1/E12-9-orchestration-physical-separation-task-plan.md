# E12-9. Orchestration Physical Separation

> **Metadata**
>
> - **Date**: 2026-03-30 19:40 EDT
> - **Author**: GitHub Copilot (GPT-5.4)
> - **Owning Epic**: [docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12
> - **Review Coverage Target**: 2

---

## Objective

Finish the physical separation between `agent-handoff-mcp` and `agent-orchestrator-mcp` so that:

- `agent-handoff-mcp` is a standalone ledger package with no orchestration implementation, no lane-owned CRUD, and no orchestration CLI surface
- `agent-orchestrator-mcp` owns orchestration runtime, daemon lifecycle, lane CRUD, plan cursors, metrics, and orchestration CLI commands
- the remaining package boundary is explicit, documented, and extraction-ready for independent repositories

## Status Summary

This task plan previously described a much earlier state of the codebase. That is no longer accurate.

The following separation work is already complete in the current workspace:

1. `agent-handoff-mcp` no longer exposes orchestration commands in its CLI.
2. `agent-handoff-mcp/api.py` no longer exposes orchestration wrapper functions.
3. `agent-handoff-mcp/__init__.py` no longer re-exports lane or orchestration helpers.
4. `agent-handoff-mcp/src/agent_handoff_mcp/orchestration/` is gone.
5. `agent-handoff-mcp/src/agent_handoff_mcp/lanes.py` is gone.
6. Plan cursor CRUD no longer lives in `agent-handoff-mcp/core.py`.
7. `agent-orchestrator-mcp` now owns local copies of `orchestration/`, `lanes.py`, and plan cursor CRUD.
8. Package extraction groundwork already landed: package-local `pyproject.toml` cleanup, package-local Makefiles, and standalone-first README workflows.
9. The `_shared.py` decomposition originally proposed in E12-10 has already materially landed: `current_task_rendering.py`, `shared_write_context.py`, `shared_schema.py`, `shared_db_utils.py`, `shared_archival.py`, and `shared_tool_adapters.py` now exist, and `_shared.py` re-exports those extracted surfaces for compatibility.

The remaining work is narrower and more specific:

1. `agent-orchestrator-mcp/api.py` still uses `_scripts_mcp_dir()` and `_import_scripts_mcp_module()` indirection instead of a fully package-local runtime surface.
2. `agent-orchestrator-mcp/cli.py` is still minimal and does not yet own the orchestration CLI commands that were removed from the handoff package.
3. `agent-orchestrator-mcp/lanes.py` still imports orchestration-adjacent helpers from the `agent_handoff_mcp._shared` compatibility layer, so table/helper ownership is not fully normalized.
4. Final verification, contract updates, and installability proof have not been completed.

This means E12-10 no longer makes sense as a separate active execution plan. Its extraction work is already part of the current codebase; the only live follow-on is the remaining package-boundary cleanup tracked here.

## Problem Statement

The codebase has already passed the first major boundary line: the handoff package is no longer the place where orchestration code lives. The remaining problem is that the orchestrator package still behaves like an extracted shell around transitional internals rather than a fully self-owned package.

Today, the main blockers are:

1. **Runtime indirection in `agent-orchestrator-mcp/api.py`**. The API still resolves orchestration modules through `_scripts_mcp_dir()` and dynamic imports instead of relying on package-local modules directly.
2. **Residual dependency on handoff internals**. `agent-orchestrator-mcp` still imports from `agent_handoff_mcp.core`, the `_shared` compatibility layer, `agent_handoff_mcp.import_export`, and `agent_handoff_mcp.review_findings` in places where the final boundary should be more explicit.
3. **Incomplete CLI ownership**. The orchestrator binary still does not expose the operational commands required to replace the removed handoff CLI surface.
4. **Verification gap**. The repo now reflects partial completion, but the task plan still describes pre-separation work and does not focus the remaining slices on the real blockers.

## Constraints

- `core.py` must remain pure handoff-state CRUD per `rg-013`: no orchestration imports, no subprocess calls, no lock management.
- Orchestration modules must continue using late-binding imports for `agent_handoff_mcp` symbols where `rg-014` requires them.
- Both packages share `handoff.db` and `mcp-artifacts.db`; ownership must follow the write path, not convenience imports.
- The final package boundary must support independent repositories with package-root workflows.
- `.mcp.json` and `.vscode/mcp.json` must remain functional.
- Daemon subprocess entrypoints must continue to work after import-path cleanup.

## Workflow Principles

- Each remaining slice must produce behavior plus proof.
- Prefer ownership cleanup over compatibility shims.
- Remove transitional indirection once the destination package already owns the implementation.
- Keep package-local developer workflows (`make`, `pytest`, `ruff`, `mypy`, README instructions) aligned with the extraction target.

## Current State Analysis

### Handoff Package

- `agent-handoff-mcp` MCP surface remains the ledger surface at 27 tools.
- `agent-handoff-mcp/cli.py` is now registry-based and ledger-only.
- `agent-handoff-mcp/api.py` exports ledger operations only.
- `agent-handoff-mcp/__init__.py` no longer exposes orchestration helpers.
- `agent-handoff-mcp` does not contain `orchestration/` or `lanes.py` anymore.
- `agent-handoff-mcp/_shared.py` has already been decomposed into focused modules and now serves partly as a compatibility re-export surface instead of the sole home for those clusters.

### Orchestrator Package

- `agent-orchestrator-mcp` owns the moved orchestration implementation under its own package tree.
- `agent-orchestrator-mcp/lanes.py` owns lane CRUD, worker reports, turn metrics, and plan cursor CRUD.
- `agent-orchestrator-mcp/api.py` re-exports the orchestration surface locally, but still relies on dynamic script-path helpers and several handoff internal modules.
- `agent-orchestrator-mcp/cli.py` still only exposes `serve`, `serve-stdio`, and `doctor`.
- The orchestrator package now has a substantial local test surface and no longer looks like an empty shell package.

### Extraction Readiness Work Already Landed

- Package-local `pyproject.toml` configuration exists for all three Python packages.
- Package-local Makefiles now exist for:
  - `agent-handoff-mcp`
  - `agent-orchestrator-mcp`
  - `codex-subagent-bridge`
- Package READMEs now describe package-root installation and development workflows first.

## Remaining Boundary Issues

1. Orchestrator runtime loading:
   Current state: `agent-orchestrator-mcp/api.py` still uses `_scripts_mcp_dir()` and `_import_scripts_mcp_module()`.
   Target state: orchestrator API imports package-local modules directly.

2. Handoff internal coupling:
   Current state: orchestrator imports from `agent_handoff_mcp.core`, `_shared`, `import_export`, and `review_findings`.
   Target state: only intentional, documented library boundaries remain.

3. Orchestration CLI ownership:
   Current state: removed from handoff, not yet rehomed in orchestrator CLI.
   Target state: `agent-orchestrator-mcp` owns the orchestration CLI surface.

4. Shared helper ownership:
   Current state: `agent_orchestrator_mcp/lanes.py` still depends on `agent_handoff_mcp._shared` re-exports.
   Target state: orchestrator imports move to focused modules or an explicit shared base; `_shared.py` remains handoff compatibility only.

5. Final extraction proof:
   Current state: partial package-local workflows exist.
   Target state: both packages are independently installable and verifiably separated.

## Files and Surfaces to Change

- `backend`: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py`
  Remaining change: remove `_scripts_mcp_dir()` / `_import_scripts_mcp_module()` and normalize imports.

- `backend`: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/cli.py`
  Remaining change: add orchestration CLI subcommands and package-local dispatch.

- `backend`: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py`
  Remaining change: replace `_shared` compatibility imports with focused modules or explicit supported seams.

- `backend`: `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py`
  Remaining change: re-home or explicitly document orchestration-owned bootstrap/DDL concerns that still sit on the handoff side.

- `backend`: `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py`
  Remaining change: keep `_shared.py` as a handoff compatibility layer only; do not preserve orchestrator ownership there.

- `backend`: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/**/*.py`
  Remaining change: audit imports and subprocess entrypoint resolution after API cleanup.

- `docs`: `docs/agentic/contracts/agent-handoff-mcp.md`
  Remaining change: confirm no orchestration CLI references remain.

- `docs`: `docs/agentic/contracts/agent-orchestrator-mcp.md`
  Remaining change: document final orchestrator CLI/runtime boundary.

- `docs`: `docs/agentic/BOOTSTRAP.md`
  Remaining change: keep startup and tool-count guidance aligned with the separated packages.

- `tooling`: `mk/handoff.mk` / `mk/orchestrator.mk`
  Remaining change: ensure orchestration targets are owned only by orchestrator tooling.

## Proposed Solution

The focused `_shared.py` extraction work proposed in E12-10 has already landed far enough that it should be treated as completed prerequisite work inside this task, not as a separate active plan. Three remaining slices are sufficient.

### Slice 1: Runtime Boundary Normalization

**Goal**: Turn `agent-orchestrator-mcp` into a self-owned package runtime instead of a package wrapper around transitional script-path helpers.

Changes:

- Remove `_scripts_mcp_dir()` and `_import_scripts_mcp_module()` from `agent-orchestrator-mcp/api.py`.
- Replace dynamic script-path imports with direct imports from `agent_orchestrator_mcp.orchestration.*`.
- Audit subprocess launch paths so daemon and worker entrypoints still resolve from the orchestrator package after the import cleanup.
- Migrate orchestrator imports off `agent_handoff_mcp._shared` re-exports and, where needed, re-home orchestration-owned bootstrap helpers currently surfaced through handoff-side modules.
- Reduce orchestrator imports from handoff internals to intentional package-library seams.

Proof:

- `grep -r "_scripts_mcp_dir\|_import_scripts_mcp_module" packages/agent-orchestrator-mcp/` returns zero matches.
- `grep -r "agent_handoff_mcp\._shared" packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/` is either zero or reduced to explicitly accepted shared-base seams.
- `python -c "import agent_handoff_mcp; print('ok')"` succeeds without importing orchestrator runtime.
- `python -c "import agent_orchestrator_mcp; print('ok')"` succeeds.

### Slice 2: Complete Orchestrator CLI Ownership

**Goal**: Move the operational CLI surface to the orchestrator package so the binary matches the MCP/runtime ownership split.

Changes:

- Add orchestration CLI commands to `agent-orchestrator-mcp/cli.py` for daemon lifecycle, worker lifecycle, lane management, dispatch, review-summary, and structured turn execution.
- Keep `agent-handoff-mcp` CLI ledger-only.
- Ensure `mk/orchestrator.mk` owns orchestration targets and `mk/handoff.mk` does not reintroduce them.

Proof:

- `agent-orchestrator-mcp --help` shows the orchestration command surface.
- `agent-handoff-mcp --help` remains ledger-only.
- CLI commands run through package-local imports rather than reaching back into handoff paths.

### Slice 3: Verification, Docs, and Extraction Proof

**Goal**: Finish the package split with test proof, contract proof, and installability proof.

Changes:

- Run both package test suites from their package roots.
- Run both `doctor` commands and verify tool counts remain correct.
- Update contract docs and bootstrap docs to describe the final package boundary and CLI ownership.
- Prove both servers can still be registered together via `.mcp.json`.
- Remove any dead imports, dead wrappers, and stale fixtures left from the transitional move.

Proof:

- `agent-handoff-mcp doctor` reports 27 tools.
- `agent-orchestrator-mcp doctor` reports the full orchestration tool surface.
- Both package-local `pytest` suites pass.
- `grep -r "from agent_handoff_mcp.orchestration" packages/` returns zero matches.
- `grep -r "from agent_handoff_mcp.lanes" packages/` returns zero matches.

## Verification Strategy

- Package-local tests:
  - `cd packages/agent-handoff-mcp && pyenv exec python -m pytest tests/ -x -q`
  - `cd packages/agent-orchestrator-mcp && pyenv exec python -m pytest tests/ -x -q`
- Package-local static checks as needed:
  - `make -C packages/agent-handoff-mcp check-handoff`
  - `make -C packages/agent-orchestrator-mcp check-orchestrator`
- Runtime parity:
  - `agent-handoff-mcp --workspace-root . doctor`
  - `agent-orchestrator-mcp --workspace-root . doctor`
- Boundary audit:
  - search for stale handoff orchestration imports
  - search for stale orchestrator imports of `agent_handoff_mcp._shared`
  - search for stale script-dir indirection
  - search for orchestration CLI leakage back into handoff

## Consolidated Checklist

## Already Completed

- [x] `agent-handoff-mcp` MCP surface remains ledger-only at 27 tools.
- [x] `agent-handoff-mcp` CLI no longer exposes orchestration commands.
- [x] `agent-handoff-mcp/api.py` no longer exports orchestration wrappers.
- [x] `agent-handoff-mcp/__init__.py` no longer exports orchestration helpers.
- [x] `agent-handoff-mcp/src/agent_handoff_mcp/orchestration/` has been removed.
- [x] `agent-handoff-mcp/src/agent_handoff_mcp/lanes.py` has been removed.
- [x] Plan cursor CRUD no longer lives in `agent-handoff-mcp/core.py`.
- [x] `agent-orchestrator-mcp` now owns moved orchestration modules locally.
- [x] Package-local `pyproject.toml` cleanup landed for the Python packages.
- [x] Package-local Makefiles landed for `agent-handoff-mcp`, `agent-orchestrator-mcp`, and `codex-subagent-bridge`.
- [x] Package READMEs were rewritten for standalone-first workflows.
- [x] Tool-count docs in contracts and `BOOTSTRAP.md` already reflect 27 and ~38 tools.
- [x] Focused shared modules from the former E12-10 plan already landed: `current_task_rendering.py`, `shared_write_context.py`, `shared_schema.py`, `shared_db_utils.py`, `shared_archival.py`, and `shared_tool_adapters.py`.
- [x] `_shared.py` already re-exports those focused modules for compatibility; the remaining work is boundary cleanup, not first-time extraction.

## Remaining: Slice 1

- [x] Remove `_scripts_mcp_dir()` from `agent-orchestrator-mcp/api.py`.
- [x] Remove `_import_scripts_mcp_module()` from `agent-orchestrator-mcp/api.py`.
- [x] Replace script-path indirection with package-local imports (`_orchestration_dir`, `_import_orchestration_module`).
- [x] Created `shared_primitives.py`; rewrote `_shared.py` to thin re-export stub (~220 lines, down from 553).
- [x] Inverted all back-imports in focused modules (no late imports from `_shared` in any focused module).
- [x] Added `orchestration/__init__.py` to make orchestration a proper subpackage.
- [x] Migrated `lanes.py` off `agent_handoff_mcp._shared` to 6 focused import sources.
- [x] Verified: `grep -r "_scripts_mcp_dir\|_import_scripts_mcp_module" packages/agent-orchestrator-mcp/` returns zero matches.
- [x] Both test suites green: 264 + 571 passed.

## Remaining: Slice 2

- [x] Add orchestration CLI subcommands to `agent-orchestrator-mcp/cli.py` (daemon lifecycle, worker lifecycle, dispatch, metrics, list-backends).
- [x] Keep `agent-handoff-mcp --help` ledger-only (unchanged).
- [x] Verify `agent-orchestrator-mcp --help` shows the full orchestration command surface.
- [x] Ensure make/CLI ownership for orchestration lives under orchestrator tooling only.

## Remaining: Slice 3

- [x] Run both package-local test suites (264 + 571 passed).
- [x] Run both `doctor` commands and verify counts.
- [x] Update contract docs for the final CLI/runtime boundary.
- [x] Verify both servers still connect simultaneously via `.mcp.json`.
- [x] Remove dead transitional helpers and stale fixtures.
- [x] Record final handoff proof for the completed separation.

## Success Criteria

- [x] `agent-handoff-mcp` remains a clean ledger package with no orchestration implementation or orchestration CLI surface.
- [x] `agent-orchestrator-mcp` owns orchestration runtime, CLI, and package-local entrypoints without script-dir indirection.
- [x] Orchestrator-owned tables and helpers no longer depend on the handoff compatibility layer or other wrong-side internals.
- [x] Both packages are independently installable with package-root workflows.
- [x] Both MCP servers still run together with the expected tool surfaces.

## Deferred Follow-On

- [x] Evaluated dedicated shared base package: **not needed**. `_shared.py` is a 220-line re-export stub; `agent-orchestrator-mcp` already imports from focused modules directly. No `agent_handoff_mcp._shared` imports exist in orchestrator source. Trigger for re-evaluation: a third consumer or ownership change (decision id 1102).
- [x] Added `agent-orchestrator-mcp` to CI as a first-class package. Created `.github/workflows/mcp-packages.yml` (lint + tests for both `agent-handoff-mcp` and `agent-orchestrator-mcp`). Fixed broken `.github/workflows/handoff-integrity.yml` (was referencing deleted `scripts/mcp/handoff_integrity_guard.py`; now points to the package-local guard). Added `check-all-packages` target to `packages/Makefile`.
