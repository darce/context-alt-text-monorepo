# E17-14. Root-Visible Task Plans and CURRENT_TASK Demotion

- **Date**: 2026-04-25 (re-scoped 2026-04-27)
- **Author**: GitHub Copilot (GPT-5.4)
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-14`
- **Review Coverage Target**: 2

> **Scope note (2026-04-27 re-scope):** The external handoff-package work originally drafted as Slice 1 will not be implemented in this repo and has been removed from this plan; it lives in a separate external work stream. **Slice 3 has been merged** to `main` in commit `3892997a` (2026-04-27) and is retained below as a record of work shipped under this task ref. **Slice 2** — scratch-consumer verification — remains the only in-repo work still in scope, and is gated on the external Slice 1 landing and being tagged.

## Objective

Make every active task plan discoverable from the monorepo root without switching the root worktree away from `main`, while removing the remaining workflow assumption that `CURRENT_TASK.json` must always be regenerated and kept in sync.

## Problem Statement

The current handoff workflow stores `target_worktree_path` for active tasks, but it does not persist a structured task-plan path that the root workspace can use to surface planning artifacts living in sibling worktrees. As a result, the operator can have the correct active task in MCP and still be unable to discover or open the plan from the root workspace without manual context switching. The friction is compounded by older helper paths and docs that still treat `CURRENT_TASK.json` as a standing machine-state artifact even though the newer workflow guidance already positions it as on-demand.

## Constraints

- The root worktree must remain on `main`; this task must not rely on checking feature branches out in the root workspace.
- The canonical implementation boundary for handoff runtime changes is the external `darce/mcp-agent-handoff` repo; this monorepo only carries the consumer-facing plan, adoption, and verification surfaces.
- Avoid background mirroring or continuous file copying. Operator visibility should come from structured state and explicit read/open flows, not repeated artifact regeneration.
- `DASHBOARD.txt` remains the operator-facing live surface after state-changing writes. `CURRENT_TASK.json` may remain as an explicit export surface, but not as a required always-current singleton.
- Task-plan visibility must work for multiple active tasks and must not rely on parsing freeform prose from `focus`.

## Workflow Principles

- Keep the source of truth singular: `.task-state/handoff.db` owns task state; rendered files are derived views only.
- Surface task plans by metadata plus explicit path resolution, not by copying task-plan files into root.
- Separate package implementation from consumer verification: external repo changes land first, monorepo adoption and cleanup follow.
- Prefer one operator-visible root artifact over multiple mirrors.

## Terminology

- **Root-visible task plan**: an active task plan that can be discovered and opened from the monorepo root workspace without switching the root worktree to the task branch.
- **Task-plan metadata**: structured handoff fields such as `task_plan_path`, resolved absolute plan path, and existence state.
- **On-demand current-task render**: an explicit `render_handoff(kind='current_task', ...)` call used only when a task-scoped machine snapshot is needed.

## Current State Analysis

- Active handoff state already carries `target_branch` and `target_worktree_path`, which is enough to locate a task worktree but not enough to render or open its plan deterministically.
- The current plan path often survives only as prose inside `focus`, which is not a stable contract surface for renderers, close checks, or operator tooling.
- The root `.vscode/mcp.json` launcher and the consumer docs (`CLAUDE.md`, `docs/agentic/instructions.md`, `docs/agentic/consumer-setup.md`) were converged on on-demand `CURRENT_TASK.json` semantics in Slice 3 (merged 2026-04-27 in commit `3892997a`), so they are no longer remaining-scope surfaces.
- The remaining `CURRENT_TASK.json` assumption that this plan still has authority over is the **external package contract** (out of scope for this repo). Inside this repo, the only pending convergence work is the Slice 2 verification gate that proves the on-demand model holds end-to-end through a packaged consumer install.

## Target Outcome

The root workspace exposes a durable operator surface listing every active task plan with its owning task ref, target branch, worktree path, repo-relative plan path, and resolved absolute plan path. The external `mcp-agent-handoff` package owns the state-model and dashboard changes that make this possible. This monorepo consumes the new package version, verifies the behavior from the root workspace, and removes local docs/helper assumptions that `CURRENT_TASK.json` must be regenerated after every relevant workflow step.

## Context Loading

- Rules: [docs/agentic/instructions.md](../../agentic/instructions.md), [docs/agentic/rules/development-workflow.md](../../agentic/rules/development-workflow.md), [docs/agentic/rules/planning-review-guide.md](../../agentic/rules/planning-review-guide.md)
- Constitution: [docs/agentic/constitution.md](../../agentic/constitution.md)
- Related plans: [docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md), [docs/tasks/17.0/E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md](./E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md), [docs/tasks/17.0/E17-13-hoisted-surface-cleanup-task-plan.md](./E17-13-hoisted-surface-cleanup-task-plan.md)
- Contracts: [docs/agentic/contracts/agent-handoff-mcp.md](../../agentic/contracts/agent-handoff-mcp.md), [docs/agentic/contracts/harness-protocol.yaml](../../agentic/contracts/harness-protocol.yaml)
- Consumer setup: [docs/agentic/consumer-setup.md](../../agentic/consumer-setup.md)
- Handoff/MCP state: active task refs, target worktree paths, and current dashboard rendering behavior

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Handoff task state | `darce/mcp-agent-handoff` | active rows expose worktree metadata but no structured task-plan metadata | add structured `task_plan_path` plus resolved plan-path fields | yes; existing task-state reads must remain valid | external package tests + root consumer smoke |
| Dashboard operator surface | `darce/mcp-agent-handoff` | `DASHBOARD.txt` shows active tasks but not a complete active-task-plan index | add active task-plan visibility section and/or columns | yes; ASCII operator view must remain stable | dashboard render tests + root manual smoke |
| Current-task renderer | `darce/mcp-agent-handoff` | `CURRENT_TASK.json` still appears in default package contract and some helper flows | demote to on-demand-only render semantics | yes; explicit exports still work | external package tests + root verification |
| Planning/workflow docs (remaining-scope verification only) | monorepo root | docs were converged on on-demand `CURRENT_TASK.json` semantics in Slice 3 | confirm convergence end-to-end through a packaged consumer install in Slice 2 | n/a (no further doc edits planned) | scratch-consumer verification fixture (see Slice 2) |

## Proposed Solution

Introduce structured task-plan metadata in the external handoff package, resolve it against `target_worktree_path`, and render all active task plans into the root operator surface. Then update this monorepo to consume that package behavior, verify it from the root workspace, and remove local workflow language and helper assumptions that still require `CURRENT_TASK.json` to be kept current continuously.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Planning artifact | `docs/tasks/17.0/E17-14-root-visible-task-plans-and-current-task-demotion-task-plan.md` | Root reviewable plan for the full change |
| External package | `darce/mcp-agent-handoff` runtime, renderers, and tests | Add task-plan metadata + dashboard visibility + current-task demotion |
| Slice 2 verification artifact | `docs/tasks/17.0/E17-14-slice2-verification-proof.md` (new) | Captures the scratch-consumer setup, install command, observed root-visible plan output, and pass/fail conclusion |
| Operator workflow doc | `docs/agentic/consumer-setup.md` | Append a short Slice 2 operator-workflow section that names the install/probe commands and links to the proof artifact |

## Related Files

| File | Note |
| --- | --- |
| `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md` | Already records deferred `CURRENT_TASK.json` demotion work |
| `docs/tasks/17.0/E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md` | Captures multi-active-task implications for current-task rendering |
| `docs/tasks/17.0/E17-13-hoisted-surface-cleanup-task-plan.md` | Defines the external repo ownership boundary |
| `docs/agentic/contracts/agent-handoff-mcp.md` | Current package contract that still treats `CURRENT_TASK.json` as a default artifact |
| `docs/agentic/consumer-setup.md` | Consumer update and doctor workflow (already converged in Slice 3; referenced for Slice 2 verification only) |

## Verification Strategy

- Deterministic tests:
  - external `mcp-agent-handoff` unit/integration coverage for task-state metadata, dashboard rendering, and current-task render-on-demand behavior
  - root-repo targeted checks for updated helper/docs expectations once consumer changes land
- Runtime-parity / environment checks:
  - create a fresh scratch consumer repo, install the reviewed packaged consumer toolchain, and run `agentic-bootstrap install --target . --remote-ref <reviewed-ref>` so the proof exercises the published install path rather than a mutable shared environment
  - restart/reload MCP in that scratch consumer and verify root discovery of active task plans from the consumer root after bootstrap install
  - optional local smoke only: upgrade the shared `description-service` environment if needed to compare local behavior, but do not treat that path as release proof
- Contract/fixture verification:
  - verify `get_handoff_state` and dashboard output expose the new task-plan metadata without breaking existing fields
  - verify explicit `render_handoff(kind='current_task')` still returns a parseable task snapshot when requested
- Manual verification:
  - from the scratch consumer root, inspect the operator surface and open an active task plan without switching the consumer checkout

## Slice Delivery

> Slice 1 (external handoff-package metadata and renderer changes) is **out of scope for this repo** and has been removed. That work lives in the external work stream and is tracked there. This task ref consumes the resulting tagged ref via Slice 2.

### Slice 2: Consumer Root Verification from This Monorepo

**Goal**: Prove the root workspace can consume the new external package behavior without switching the root worktree.

**Verification fixture (mandatory; gates this slice):**

1. **Scratch consumer location**: `/tmp/e17-14-scratch-consumer/` — created fresh from `git init` (not a clone of this monorepo) so the target is a minimal initialized repo before the bootstrap installer touches it. Tear down at slice end.
2. **Reviewed external ref**: the tagged `mcp-agent-handoff` release that ships task-plan metadata + on-demand `CURRENT_TASK.json` semantics. Pin the exact tag in the proof artifact (placeholder `<reviewed-ref>` resolved at run time; recorded as a 40-char SHA in the proof file).
3. **Install command** (run after step 1): `agentic-bootstrap install --target /tmp/e17-14-scratch-consumer --remote-ref <reviewed-ref>` from a clean shell with no `PYTHONPATH` overrides. The installer is the only writer that provisions consumer-side handoff scaffolding into the `git init`'d target.
4. **Seeded handoff state**: from the scratch consumer root, register two active tasks via `set_handoff_state` with distinct `task_ref`, `target_branch`, `target_worktree_path`, and `task_plan_path` values. Create empty placeholder task-plan files at the resolved absolute paths (under sibling worktree dirs `/tmp/e17-14-scratch-consumer-task-a/` and `-task-b/`) so existence checks pass.
5. **Probe**: from the scratch consumer root (still on `main`), run `make context` and read `DASHBOARD.txt` plus a single `render_handoff(kind='current_task', task_ref=<task-a>)` call. Capture stdout for both.

**Pass criteria (each must be true; any failure blocks merge):**

- `agentic-bootstrap install` exits 0 and produces an MCP launcher config that does not pass `--current-task-path`.
- MCP server starts cleanly (handoff doctor exits 0).
- `DASHBOARD.txt` lists both seeded task refs with their `task_plan_path` values resolved to existing files.
- The on-demand `render_handoff(kind='current_task', task_ref=<task-a>)` call returns a parseable snapshot for that task only, without regenerating a default `CURRENT_TASK.json` for the other task.
- No `CURRENT_TASK.json` file is auto-written by `make context` or any state-changing handoff write during the probe.

**Proof artifact (durable, committed to this repo):**

- `docs/tasks/17.0/E17-14-slice2-verification-proof.md` — records the resolved 40-char `<reviewed-ref>`, the exact install/probe commands, the captured `DASHBOARD.txt` excerpt, the captured `render_handoff` output excerpt, the absence-of-auto-write check, and a final pass/fail line. Linked from the slice-complete decision.

Changes:

- Author the proof artifact above against the fixture; commit it on `feature/e17-14`.
- Capture the operator workflow (install + probe + dashboard read) in `docs/agentic/consumer-setup.md` or an adjacent doc, linking back to the proof artifact.

Proof:

- The committed `E17-14-slice2-verification-proof.md` shows all five pass-criteria lines marked PASS with command output excerpts.
- Operator workflow doc references the artifact and the install command as the canonical verification path.

### Slice 3: Cleanup of CURRENT_TASK Assumptions in Local Docs and Helpers — **MERGED 2026-04-27 in commit `3892997a`**

**Goal**: Remove stale root-repo assumptions that `CURRENT_TASK.json` must always be present, current, or part of every close/verification path.

Changes:

- Update local docs, prompts, and helper scripts to treat `DASHBOARD.txt` as the always-current operator surface and `CURRENT_TASK.json` as on-demand.
- Remove or relax helper checks that fail merely because `CURRENT_TASK.json` was not regenerated on unrelated workflow paths.
- Preserve any explicit current-task export command only where a task-scoped machine snapshot is genuinely required.

Proof:

- Root-repo targeted checks pass with the new semantics.
- Grep/doc audit confirms stale always-current language is removed or narrowed to explicit on-demand cases.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed external runtime changes belong in `darce/mcp-agent-handoff`, while this monorepo owns consumer-facing planning, adoption, and verification.
- [ ] Recorded boundary ownership and compatibility expectations for the external package, dashboard surface, and local helper/docs cleanup.

### Checklist for Slice 2: Consumer Root Verification from This Monorepo

- [ ] Scratch consumer at `/tmp/e17-14-scratch-consumer/` provisioned via `agentic-bootstrap install --remote-ref <reviewed-ref>` against the tagged external ref.
- [ ] Two seeded handoff tasks with distinct `task_plan_path` values render correctly in `DASHBOARD.txt` from the consumer root.
- [ ] On-demand `render_handoff(kind='current_task', task_ref=...)` returns a parseable snapshot and no auto-write of `CURRENT_TASK.json` is observed during the probe.
- [ ] `docs/tasks/17.0/E17-14-slice2-verification-proof.md` is committed with all five pass-criteria lines marked PASS and a 40-char ref recorded.
- [ ] Operator workflow doc references the proof artifact as the canonical consumer-verification path.

### Checklist for Slice 3: Cleanup of CURRENT_TASK Assumptions in Local Docs and Helpers — **MERGED 2026-04-27**

- [x] Local docs and prompts no longer describe `CURRENT_TASK.json` as always-current by default.
- [x] Local helper scripts/configs no longer require constant `CURRENT_TASK.json` regeneration where it is not needed.
- [x] Remaining explicit current-task render paths are intentional and documented.

## Review Readiness

- [ ] The task-plan metadata contract is explicit enough that implementation does not need to infer it from prose.
- [ ] The plan does not depend on file mirroring, root branch switching, or background artifact churn.
- [ ] External-package work, root consumer verification, and local cleanup are separated into reviewable slices with proof.

## Stretch Goals

- [ ] Add an explicit operator command or MCP query for resolving and opening a task plan by `task_ref` from the root workspace.

## Success Criteria

- [ ] The root workspace can discover every active task plan without checking the root worktree out to the task branch. *(Depends on external Slice 1 + verified by Slice 2.)*
- [ ] The operator can open or inspect an active task plan from the root workspace with no mirrored plan files. *(Depends on external Slice 1 + verified by Slice 2.)*
- [ ] The external handoff package no longer treats `CURRENT_TASK.json` as an always-current required artifact. *(Out of scope for this repo; tracked externally.)*
- [x] This monorepo's docs and helpers no longer depend on continuous `CURRENT_TASK.json` regeneration. *(Slice 3, merged 2026-04-27 in commit `3892997a`.)*
