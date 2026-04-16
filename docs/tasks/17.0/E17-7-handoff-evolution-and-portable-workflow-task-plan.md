# E17-7. Phase 3 Follow-On — Handoff State Evolution, Trace Archive, Tool Surface Compression, and Portable Workflow Normalization

- **Date**: 2026-04-16
- **Author**: GPT-5.4
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-7`
- **Review Coverage Target**: 2

---

## Objective

After the E17-6 Phase 3 core retrofit is approved, land the split-out follow-on work: evolve `agent-handoff-mcp` from a singleton active-task model to concurrent task rows, preserve richer session/slice status for cold starts, store raw test traces with change-outcome lookup, compress the MCP tool surface, and finish portable workflow normalization so Claude, VS Code, and Codex all consume the same command contract from `config/agent-workflows/portable_commands.json`.

## Why This Is Separate

This plan was split out of `E17-6` to keep the Phase 3 core reviewable against the epic's retrofit/routing/gating deliverables. Everything here changes either:

- the `agent-handoff-mcp` state model
- the query/rendering surface for cold-start state
- the registered MCP tool surface
- the cross-host workflow command contract, including Codex-specific command routing

Those changes are valuable, but they are not required to complete the E17-6 core retrofit.

## Problem Statement

Four follow-on gaps remain once the E17-6 core is separated:

1. **Singleton handoff state blocks parallel work**: `handoff_state WHERE id = 1` still assumes one active task at a time.
2. **Cold starts lose failure detail**: `verified_tests.result` preserves only a 280-character summary, not raw trace content.
3. **The MCP tool surface is larger than necessary**: several read/write tool pairs can be merged into compound tools without changing the Python API.
4. **Codex portable-command parity is incomplete**: `portable_commands.json` already generates Claude and VS Code adapters, but Codex still depends on handwritten router text in `instructions.md` and `CLAUDE.md`. That leaves `/branch-review`, `/planning-review`, and the other workflow ids vulnerable to drift in this harness.

## Constraints

- `portable_commands.json` remains the canonical command contract.
- `scripts/generate_agent_workflows.py` remains the single generator for host-specific workflow artifacts.
- `make check-agent-workflows` must verify the Codex router artifact in addition to Claude and VS Code outputs.
- `make check-codex-command-router` must fail on router drift between the manifest and the committed Codex instruction surfaces.
- `make smoke-agent-workflows` should be optional and backend-aware; it must not become a flaky mandatory gate for environments that cannot execute the live backend check.
- Test trace retrieval is additive to `get_verified_tests`; no separate trace MCP tool should be introduced.
- Python-level API compatibility should be preserved where practical even if MCP tool names are compressed.

## Current State Analysis

**Portable workflow contract**:

- `config/agent-workflows/portable_commands.json` already exists as the canonical command manifest.
- `scripts/generate_agent_workflows.py` currently generates `.claude/commands/*.md` and `.github/prompts/*.prompt.md` only.
- `make generate-agent-workflows` and `make check-agent-workflows` already exist.
- Codex routing still lives in handwritten text in `docs/agentic/instructions.md` and `CLAUDE.md`.

**Conflicting review routing still exists before the E17-6 prerequisite lands**:

- Both docs describe portable command routing.
- Both docs also still contain direct review-routing text that tells agents to load `branch-review-guide.md` or `planning-review-guide.md` directly.
- That conflict is a likely cause of `/branch-review` feeling unreliable in Codex even though the manifest and generated host adapters exist.
- E17-6 Slice 4 removes that guide-first routing before this follow-on starts; Slice 1 here builds on the already-redirected surfaces.

**Handoff-state model**:

- `handoff_state` is still singleton-keyed.
- `_resolve_task_ref()` still falls back to the singleton active row when `task_ref` is omitted.

**Test verification surface**:

- `verified_tests.result` stores only the summary string.
- There is no raw trace table and no correlated-file query surface.

**MCP tool surface**:

- The MCP API still exposes separate `generate_current_task_md`, `generate_dashboard_md`, `export_handoff_state`, `import_handoff_state`, `archive_task_state`, and `get_archived_task` tools.

## Target Outcome

- `portable_commands.json` generates Claude, VS Code, and Codex workflow artifacts from one source.
- `CLAUDE.md` and `docs/agentic/instructions.md` consume generated or clearly delimited generated Codex routing content instead of handwritten command-id lists.
- `make check-agent-workflows` fails on Claude, VS Code, or Codex adapter drift.
- `make check-codex-command-router` fails if the committed Codex router text diverges from the manifest.
- `make smoke-agent-workflows` can validate live command resolution for `/branch-review` and `/planning-review`.
- `handoff_state` supports concurrent in-progress tasks keyed by `task_ref`.
- `load_session` / `get_handoff_state` can surface completed slices explicitly.
- `get_verified_tests(include_traces=True)` returns raw stored traces.
- The MCP tool surface is reduced via compound tools while Python-level compatibility aliases remain.

## Context Loading

- Phase 3 core prerequisite: [E17-6](./E17-6-phase3-retrofit-task-plan.md)
- Canonical workflow manifest: `config/agent-workflows/portable_commands.json`
- Generator: `scripts/generate_agent_workflows.py`
- Existing generated adapters: `.claude/commands/*.md`, `.github/prompts/*.prompt.md`
- Codex router surfaces: `docs/agentic/instructions.md`, `CLAUDE.md`
- Handoff package: `packages/agent-handoff-mcp/src/agent_handoff_mcp/`
- Orchestrator tests: `packages/agent-orchestrator-mcp/tests/`

## Proposed Solution

Four slices deliver the follow-on. Slice 1 is independent of the handoff-schema work and should land first because it closes the user-visible Codex command gap. Slices 2-4 then proceed in dependency order:

1. Portable workflow normalization for Codex
2. Multi-active-task registry + slice status / task-plan sync
3. Test trace archive and change-outcome linkage
4. MCP tool surface compression

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `portable_commands.json` | `config/agent-workflows/` | canonical command ids, Claude + VS Code adapters | extend to Codex router artifact content | non-breaking manifest authority | generator/check passes |
| `scripts/generate_agent_workflows.py` | scripts | writes Claude + VS Code adapters | also writes Codex router artifact | non-breaking generator expansion | generated outputs match |
| `make check-agent-workflows` | root `Makefile` | checks Claude + VS Code adapters | also checks Codex router artifact | non-breaking stronger gate | drift fails |
| `make check-codex-command-router` | root `Makefile` (new) | does not exist | static Codex router drift gate | n/a — new target | handwritten/router drift fails |
| `make smoke-agent-workflows` | root `Makefile` (new) | does not exist | optional runtime command-resolution smoke test | n/a — new target | `/branch-review` + `/planning-review` resolve |
| `handoff_state` | `shared_schema.py` | singleton row | task-ref keyed multi-row state | breaking internal schema | tests pass |
| `load_session` / `get_handoff_state` | `core.py`, `handoff_state.py` | no explicit slice-status section | add `slices_completed` section | non-breaking additive response | cold-start status visible |
| `verified_tests` + `test_traces` | `shared_schema.py`, `verified_tests.py`, `decisions.py` | summary-only result | raw traces + correlated-file retrieval | non-breaking additive query params | trace roundtrip works |
| MCP tool registry | `api.py` | 6 single-purpose tools | 3 compound tools | breaking MCP names, Python aliases kept | tool count reduced |

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| Portable manifest | `config/agent-workflows/portable_commands.json` | extend manifest ownership to Codex router text where needed |
| Workflow generator | `scripts/generate_agent_workflows.py` | generate Codex router artifact in addition to Claude + VS Code adapters |
| Generated Codex router | `docs/agentic/generated/codex-command-router.md` (new) | generated Codex command-routing artifact |
| Codex router consumers | `docs/agentic/instructions.md`, `CLAUDE.md` | replace handwritten command-id lists with generated content or delimited generated blocks |
| Static drift gate | root `Makefile` | expand `check-agent-workflows`; add `check-codex-command-router` |
| Runtime smoke test | root `Makefile` and script(s) | add optional `smoke-agent-workflows` |
| Handoff schema | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py` | re-key `handoff_state`; add `test_traces` |
| Task resolution | `shared_primitives.py`, `handoff_state.py`, `core.py`, `import_export.py`, `shared_write_context.py`, `decisions.py`, `review_findings.py`, `current_task_rendering.py`, `dashboard_rendering.py` | update singleton task-resolution assumptions |
| Slice status surface | `core.py`, `handoff_state.py` | add `slices_completed` section |
| Task-plan sync | `scripts/hooks/sync-task-plan-checkboxes.sh`, `scripts/context.sh` | auto-sync and stale-checkbox warning |
| Verification surface | `decisions.py`, `verified_tests.py`, `api.py` | raw traces + correlated-file lookup |
| Tool compression | `api.py`, `__init__.py`, hook matcher references, contracts docs | compound MCP tools + Python aliases |

## Verification Strategy

- `make check-agent-workflows` passes with Claude, VS Code, and Codex generated artifacts in sync.
- `make check-codex-command-router` fails when `instructions.md` or `CLAUDE.md` diverge from the generated Codex router content.
- `make smoke-agent-workflows` resolves `/branch-review` and `/planning-review` through the active backend and confirms skill/target parity with the manifest.
- Concurrent active-task tests pass for the handoff schema redesign.
- `load_session` and `get_handoff_state(sections="slices_completed")` surface completed slices correctly.
- Trace roundtrip, correlated-file lookup, and bounded retention tests pass.
- Compound MCP tool tests pass and Python aliases continue to resolve.

## Slice Delivery

### Slice 1: Portable Workflow Normalization for Codex

**Goal**: one manifest drives Claude, VS Code, and Codex command routing.

Prerequisite:

- E17-6 Slice 4 already removed the guide-first review-routing conflict from `docs/agentic/instructions.md` and `CLAUDE.md`. This slice does not re-own that redirect; it adds Codex generator, drift-check, and smoke-test coverage on top of the redirected routing surfaces.

Changes:

- Extend `scripts/generate_agent_workflows.py` to generate `docs/agentic/generated/codex-command-router.md`.
- Replace handwritten portable-command lists in `docs/agentic/instructions.md` and `CLAUDE.md` with generated content or clearly delimited generated blocks sourced from that artifact.
- Preserve the E17-6 skill-first routing redirect while replacing the remaining handwritten Codex command-routing content with generated content.
- Expand `make check-agent-workflows` to verify the generated Codex router artifact too.
- Add `make check-codex-command-router` to fail when the committed router text disagrees with the manifest.
- Add optional `make smoke-agent-workflows` that asks the active backend to resolve `/branch-review` and `/planning-review` and checks the resolved skill/target pair against the manifest.

Proof:

- `portable_commands.json` remains the only command registry.
- `/branch-review` and `/planning-review` resolve through the same contract across all three hosts.
- Static drift and optional smoke checks both pass.

### Slice 2: Multi-Active-Task Registry + Slice Status Follow-On

**Goal**: allow concurrent active tasks and improve cold-start task-state visibility.

Changes:

- Re-key `handoff_state` by `task_ref`.
- Migration approach: edit the baseline schema definition in `shared_schema.py` directly. This repo is greenfield, so no runtime migration path is required; local dev databases can be regenerated from the updated baseline schema.
- Evolve `_resolve_task_ref()` to use worktree/cwd matching when `task_ref` is omitted.
- Task resolution algorithm:
  - if `task_ref` is passed explicitly, resolve that task directly
  - otherwise compare the caller cwd against `target_worktree_path` across active `handoff_state` rows
  - exact path match wins first; if none exist, fall back to unique prefix-match ownership
  - if exactly one active row matches, return it
  - if zero rows match or multiple rows match, raise an explicit ambiguity error naming the candidate task refs so CLI callers stop relying on the singleton fallback
- Add `slices_completed` to `load_session` and `get_handoff_state`.
- Carry forward the split-out task-plan sync/status ideas from the former E17-6 draft:
  - `scripts/hooks/sync-task-plan-checkboxes.sh`
  - stale-checkbox warning in `make context`

Proof:

- Two active tasks can coexist without eviction.
- `load_session()` shows completed slices explicitly.
- Task-plan checkbox sync/status surfaces work as documented.

### Slice 3: Test Trace Archive and Change-Outcome Linkage

**Goal**: store raw test traces and expose selective retrieval for cold-start debugging.

Changes:

- Add `test_traces` table.
- Extend `record_test_result` / `record_event(test_result)` with optional traces.
- Extend `get_verified_tests` with `include_traces`, `correlated_file`, `correlation_window_minutes`, and `exclude_never_passed`.

Proof:

- Raw traces round-trip.
- Correlated-file queries return meaningful failure history.
- Existing callers remain backward-compatible.

### Slice 4: MCP Tool Surface Compression

**Goal**: reduce MCP tool count while preserving Python-level compatibility.

Changes:

- Replace the six single-purpose tools with:
  - `generate_md`
  - `handoff_transfer`
  - `task_archive`
- Keep Python aliases for compatibility.
- Update docs, hook matchers, and contracts to the new MCP surface.

Proof:

- Compound-tool dispatch tests pass.
- Python aliases still resolve.
- Tool count matches the compressed target.

---

## Consolidated Checklist

### Slice 1: Portable Workflow Normalization

- [ ] `scripts/generate_agent_workflows.py` generates a Codex router artifact
- [ ] `docs/agentic/instructions.md` and `CLAUDE.md` consume generated Codex router content
- [ ] Conflicting guide-first review routing is removed from those surfaces
- [ ] `make check-agent-workflows` validates Claude, VS Code, and Codex generated artifacts
- [ ] `make check-codex-command-router` exists and fails on drift
- [ ] `make smoke-agent-workflows` exists as an optional runtime validation

### Slice 2: Multi-Active Tasks + Slice Status

- [ ] `handoff_state` re-keyed by `task_ref`
- [ ] `_resolve_task_ref` handles concurrent active tasks safely
- [ ] `slices_completed` is available in `load_session` and `get_handoff_state`
- [ ] Task-plan checkbox sync and stale-checkbox warning are implemented if retained

### Slice 3: Test Trace Archive

- [ ] `test_traces` table added
- [ ] `record_test_result` stores optional traces
- [ ] `get_verified_tests` supports trace and correlated-file retrieval
- [ ] Bounded retention works

### Slice 4: Tool Surface Compression

- [ ] `generate_md` replaces the two rendering MCP tools
- [ ] `handoff_transfer` replaces export/import MCP tools
- [ ] `task_archive` replaces archive/get MCP tools
- [ ] Python aliases remain available

## Review Readiness

- [ ] E17-6 core is approved or complete before this task starts
- [ ] `make check-agent-workflows` is green after Slice 1
- [ ] `make test-handoff` is green after each schema/tooling slice
- [ ] `make test-orchestrator` is green when schema-facing behavior changes

## Success Criteria

- [ ] Codex, Claude, and VS Code command routing all derive from `portable_commands.json`
- [ ] `/branch-review` and `/planning-review` no longer rely on handwritten Codex-only router text
- [ ] Concurrent active tasks are supported without singleton eviction
- [ ] Cold-start agents can retrieve raw test traces on demand
- [ ] The MCP tool surface is compressed without breaking Python imports
