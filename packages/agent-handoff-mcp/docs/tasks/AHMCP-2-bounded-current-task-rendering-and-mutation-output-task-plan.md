# AHMCP-2. Bounded CURRENT_TASK Rendering and Mutation Output Cleanup

> **Metadata**
>
> - **Date**: 2026-04-02
> - **Author**: GPT-5.4
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-2`
> - **Target Branch**: `feature/ahmcp-2-bounded-rendering`
> - **Review Coverage Target**: 2

---

## Objective

Implement the Tier 1 output-contract v2 changes (OC-001, OC-002, OC-003, OC-007) so `CURRENT_TASK.json` stops growing without bound, `close_slice` returns the decision and revision state callers need, and `export_handoff_state` stops embedding rendered markdown by default. Additionally, implement OC-008 (task initiation with branch binding) as an independent additive slice.

## Problem Statement

The approved output-contract v2 spec identified four low-risk changes that should land before the common envelope work: remove durable all-status findings history from `CURRENT_TASK.json`, cap cross-task findings in the render, return the recorded decision row from `close_slice`, and default exports to canonical state without embedded markdown. These changes are independent of the later envelope rollout, but they materially reduce token cost and stale render noise immediately.

If they do not land first, Tier 2 will wrap an already-wasteful render path and preserve avoidable follow-up reads for `close_slice` callers.

## Constraints

- This task implements Tier 1 items from the approved spec: OC-001, OC-002, OC-003, OC-007, and OC-008.
- OC-004 response envelopes are out of scope here; Tier 1 should preserve the pre-envelope response contract except for the explicitly approved new fields on `close_slice` and the `generate_current_task_md` parameter addition.
- Active-task open findings remain uncapped; the cap applies only to cross-task grouped findings.
- `CURRENT_TASK.json` remains a bounded render artifact, not the canonical long-term history store for findings.
- Contract docs and deterministic tests must move in the same slices as the behavior changes.

## Workflow Principles

- Remove or bound expensive render sections before introducing any broader response wrapping.
- Prefer deterministic proof through targeted tests over narrative inspection comments.
- Keep each slice vertically honest: render behavior, public tool surface, and contract docs change together.
- Do not introduce compatibility shims for the removed all-history section; the history remains available through existing query tools.

## Terminology

- **Render artifact**: Generated markdown such as `CURRENT_TASK.json`; useful for hot-state consumption but not the canonical store.
- **Cross-task findings**: Findings from tasks other than the one currently being rendered.
- **Mutation confirmation**: The minimum structured response a caller needs from a write tool to avoid an immediate follow-up read.
- **Canonical export**: Exported handoff JSON that contains durable state, with rendered markdown included only when explicitly requested.

## Current State Analysis

- The approved output-contract v2 spec is the canonical current-state source for OC-001, OC-002, OC-003, and OC-007; this task plan intentionally does not restate the spec's line-by-line evidence.
- Tier 1 stays implementation-first: the remaining work here is to bind those approved spec items to the concrete code paths, proof commands, and lane ownership needed for execution.
- Existing regression coverage already touches the affected render, lifecycle, and export surfaces in `test_handoff_state.py`, `test_review_findings.py`, and `test_import_export_regressions.py`, so the work can land with narrowly scoped updates rather than new harnesses.

## Target Outcome

After this task:

- `CURRENT_TASK.json` contains no durable all-status history section
- cross-task findings render with a bounded per-task cap
- `close_slice` returns both the recorded decision row and the new task revision
- `export_handoff_state` omits `current_task_markdown` unless callers explicitly ask for it
- the contract doc and regression suite describe and prove the new behavior

## Context Loading

- Spec: `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md`
- Contract: `docs/agentic/contracts/agent-handoff-mcp.md`
- Render/runtime anchors:
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
- Test anchors:
  - `packages/agent-handoff-mcp/tests/test_handoff_state.py`
  - `packages/agent-handoff-mcp/tests/test_review_findings.py`
  - `packages/agent-handoff-mcp/tests/test_import_export_regressions.py`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `generate_current_task_md` render output | handoff core | bounded hot-state render, but still includes durable findings history | remove all-history section; add optional cross-task cap parameter | Yes; default active-task behavior stays useful | render regression tests + contract doc |
| `close_slice` success payload | handoff core | boolean-only success confirmation | include `decision` row and `task_revision` | No; greenfield contract improvement | close-slice regression tests |
| `export_handoff_state` default payload | handoff core | canonical state plus markdown by default | canonical state only by default; markdown explicit | No; greenfield output cleanup | export/import regression tests |
| MCP tool signature for render generation | handoff core | existing tool args only | add `max_cross_task_findings` to public API/tool surface | Yes; additive parameter | API + contract update |

## Proposed Solution

Land the render cleanup and write/export confirmation work in four slices. First, cut the unbounded render state and cap cross-task findings at the render source. Second, thread the new cap through the public `generate_current_task_md` API and update the contract so callers can rely on it. Third, enrich the two remaining mutation/output surfaces that still force avoidable follow-up reads or mix render artifacts into canonical exports. Fourth, add `target_branch` to task state so tasks can declare their intended work branch.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| CURRENT_TASK render state | `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | remove all-history collection/rendering; cap cross-task findings |
| Public generator surface | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | add `max_cross_task_findings` parameter to `generate_current_task_md` |
| Slice-close lifecycle output | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | return `decision` and `task_revision` from `close_slice` |
| Export defaults | `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py` | default `include_markdown` to `False` |
| Contract docs | `docs/agentic/contracts/agent-handoff-mcp.md` | document the bounded render and new `close_slice` / export behavior |
| Render regressions | `packages/agent-handoff-mcp/tests/test_handoff_state.py` | update/add coverage for removed all-history and cross-task caps |
| Render regressions | `packages/agent-handoff-mcp/tests/test_review_findings.py` | keep CURRENT_TASK cross-task finding assertions aligned |
| Export regressions | `packages/agent-handoff-mcp/tests/test_import_export_regressions.py` | assert markdown is absent by default and present when explicit |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` | shared helpers may need minor alignment if render-state helpers are re-exported |
| `packages/agent-handoff-mcp/tests/test_stdio.py` | no surface-count change expected, but tool signature additions should remain transport-safe |
| `docs/assessments/agent-handoff-mcp-output-state-keeping-report.md` | original assessment that motivated the bounded render and canonical-export work |

## Verification Strategy

Use environment-variable-based commands only. Do not hardcode user-local absolute filesystem paths such as `/Users/...`; prefer `${PYENV_ROOT:-$HOME/.pyenv}` for interpreter paths.

- Lane `render-bounds`:
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q -k "generate_current_task_md and (related or history or no_other_open_findings)"`
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_review_findings.py -q -k "generate_current_task_md"`
- Lane `lifecycle-export`:
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q -k "close_slice"`
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_import_export_regressions.py -q`
- Manual verification:
  - inspect one cross-task-heavy render and confirm each non-active task group stays within the configured cap

## Slice Delivery

### Slice 1: Remove Unbounded Findings History and Cap Cross-Task Render Noise

**Goal**: Make `CURRENT_TASK.json` bounded by removing durable all-status history and limiting cross-task findings.

Changes:

- Delete `_collect_all_findings_history()` and stop populating `findings_history_all`
- Remove the `## All Review Findings History` section from the markdown render
- Add a per-task cap for cross-task open/deferred findings while leaving active-task open findings uncapped
- Update render-focused tests to assert the bounded behavior directly

Proof:

- The targeted `test_handoff_state.py` and `test_review_findings.py` render tests pass
- No render output contains `## All Review Findings History`

### Slice 2: Thread the Cap Through the Public Render Surface

**Goal**: Expose the new render bound through the public generator interface and document it.

Changes:

- Add `max_cross_task_findings` to the public `generate_current_task_md` API surface
- Preserve a sane default value of `5`
- Update `docs/agentic/contracts/agent-handoff-mcp.md` so the new parameter and render semantics are discoverable
- Keep transport-visible behavior additive; existing callers work without passing the new parameter

Proof:

- Public API tests continue to pass with no caller changes
- The contract doc describes the default cap and the removed all-history section

### Slice 3: Return Mutation Confirmation and Canonicalize Export Defaults

**Goal**: Remove avoidable follow-up reads after `close_slice` and keep exports canonical by default.

Changes:

- Update `close_slice` to return the recorded `decision` row and `task_revision`
- Default `export_handoff_state(... include_markdown=False)`
- Add or tighten regression tests for both surfaces
- Document the changed defaults and confirmation payload in the contract doc

Proof:

- `close_slice` regression tests assert both `decision` and `task_revision`
- export/import regression tests prove markdown is absent by default and present only when requested

### Slice 4: Task Initiation with Branch Binding

**Goal**: Give tasks a declared target branch so agents can discover the intended work branch from handoff state.

Changes:

- Add `target_branch TEXT` column to `handoff_state` schema and bump `HANDOFF_SCHEMA_VERSION`
- Add `target_branch` parameter to both `switch_task` (task init/switch boundary) and `set_handoff_state` (in-place update)
- `switch_task` sets `target_branch` on init; `set_handoff_state` preserves existing value when omitted
- Include `target_branch` in `get_handoff_state` active section (included via row dict)
- Add `Target branch:` line to CURRENT_TASK.json render header when set
- Update `docs/agentic/contracts/agent-handoff-mcp.md` with the new schema field
- Update `docs/agentic/contracts/agent-orchestrator-mcp.md` with the `switch_task` signature change (`switch_task` is registered on the orchestrator surface)

Proof:

- `switch_task(task_ref="X", target_branch="feature/x")` persists and `get_handoff_state` returns it
- `set_handoff_state` without `target_branch` preserves the existing value
- CURRENT_TASK.json shows `Target branch: feature/x` in the header

## Lane-Ready Execution Brief

### Lanes

| Lane ID | Owned Files | Narrowest Proving Commands |
| --- | --- | --- |
| `render-bounds` | `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`, `docs/agentic/contracts/agent-handoff-mcp.md` | `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q -k "generate_current_task_md and (related or history or no_other_open_findings)"`; `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_review_findings.py -q -k "generate_current_task_md"` |
| `lifecycle-export` | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py` | `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q -k "close_slice"`; `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_import_export_regressions.py -q` |
| `branch-binding` | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py` (switch_task), `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q -k "set_handoff_state or get_handoff_state or switch_task or generate_current_task_md"` |

### Merge Order

1. `render-bounds`
2. `lifecycle-export`
3. `branch-binding` (independent of 1 and 2 but ordered last to avoid merge conflicts in shared files)
4. Final integration pass to resolve any shared contract wording in `docs/agentic/contracts/agent-handoff-mcp.md`

### Lane Notes

- `render-bounds` owns the only public-signature change in Tier 1: `max_cross_task_findings` on `generate_current_task_md`.
- `lifecycle-export` owns the two write/output changes that should not be blocked on the render edits.
- `branch-binding` owns the schema migration and `target_branch` plumbing through `switch_task`, `set_handoff_state`, and the CURRENT_TASK render header.
- Shared test files are intentionally not lane-owned; they are the proving surface for the code-owning lanes above.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the approved output-contract v2 spec and the live handoff contract before editing.
- [ ] Confirmed Tier 1 remains pre-envelope work; no OC-004 wrapping lands here.
- [ ] Verified the render/history cleanup does not move any historical-query responsibility out of existing query tools.

### Checklist: Slice 1

- [ ] `_collect_all_findings_history()` and its render section are removed.
- [ ] Cross-task open/deferred findings are capped per task.
- [ ] Active-task open findings remain uncapped.
- [ ] Render regression tests prove the new bounded behavior.

### Checklist: Slice 2

- [ ] `generate_current_task_md` accepts `max_cross_task_findings`.
- [ ] Default cap is `5`.
- [ ] Contract docs describe the cap and the removed history section.

### Checklist: Slice 3

- [ ] `close_slice` returns `decision` and `task_revision`.
- [ ] `export_handoff_state` defaults `include_markdown` to `False`.
- [ ] Export and lifecycle regressions cover the new behavior.

### Checklist: Slice 4

- [ ] `handoff_state` schema has `target_branch` column.
- [ ] `HANDOFF_SCHEMA_VERSION` bumped with migration.
- [ ] `set_handoff_state` accepts and persists `target_branch`.
- [ ] CURRENT_TASK.json render header shows the target branch.
- [ ] Contract doc updated.

## Review Readiness

- [ ] No Tier 1 behavior change is left undocumented in `docs/agentic/contracts/agent-handoff-mcp.md`.
- [ ] The deterministic regression suite proves the render is bounded and the new outputs are machine-usable.
- [ ] Handoff decisions reference the spec items implemented in each slice.

## Success Criteria

- [ ] `CURRENT_TASK.json` no longer includes durable all-status findings history.
- [ ] Cross-task findings render is bounded without hiding active-task open work.
- [ ] `close_slice` callers can confirm the recorded decision and revision without an immediate follow-up read.
- [ ] Default exports contain canonical handoff state without embedded markdown.
- [ ] Tasks can declare a target branch at init, discoverable from handoff state and CURRENT_TASK.json.
