# E15-7. Local Sync Completion and Audit Closure

> **Metadata**
>
> - **Date**: 2026-04-07
> - **Author**: GPT-5.4
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-7
> - **Target Branch**: `feature/invest-local-sync`
> - **Review Coverage Target**: 2

---

## Objective

Finish the remaining local-sync work so the plugin can keep recognition results locally available through backend interruptions without relying on ambiguous or misleading sync state. When this task is complete, the committed `feature/invest-local-sync` branch should satisfy the remaining product-correctness findings, have an honest contract for fallback/projection metadata, and be able to pass the pre-merge gate with only explicitly deferred follow-up work left open.

## Problem Statement

Decision `#1439` closed the bootstrap and H1 regression work, but the implementation is still incomplete in two product-critical ways and several review findings still block calling the branch correct. `INVEST-LOCAL-SYNC-004-no-persistence-path-from-analyze` remains open because local durability still depends on a later snapshot pull rather than a direct local persistence path from analyze results. `INVEST-LOCAL-SYNC-006-likely-coupling-to-bug401` remains open because the branch does not yet prove or surface whether snapshot reads can still fail on the same auth-dependent path that broke analyze. In parallel, the remaining `REVIEW-LOCAL-SYNC-*` and `VERIFY-*` findings show contract drift, duplicate triggering risk, coverage gaps, and stale audit rows that need to be resolved before the implementation can be called correct rather than merely improved.

## Constraints

- Continue from the already committed `feature/invest-local-sync` branch state; do not restart the work on `main` or create a second competing implementation branch.
- Preserve the greenfield policy: prefer direct, correct behavior over compatibility shims, but do not silently change externally consumed response fields without updating the contract and test surface in the same slice.
- Any cross-boundary change touching WordPress plugin responses, backend job/snapshot payloads, or local-sync status semantics must update the owning contract/doc surface and include verification on both sides of the boundary.
- Findings must close only with commit-backed verification evidence; prose-only handoff rows are not acceptable substitutes for implementation progress.

## Workflow Principles

- A local-read/offline-first claim is only true when analyze success can be turned into durable local state without depending on a second fragile network round-trip.
- Fallback adapters must be honest: no invented metadata, no contradictory provenance/status combinations, and no hidden repeated side effects on polling paths.
- Review cleanup follows code truth, not the other way around. Land the correct behavior, verify it on the real branch SHA, then close only the findings that the commit actually resolves.

## Terminology

- **Analyze persistence path**: The path that turns a successful `/recognition/analyze` result into durable local plugin state.
- **Projection gate**: The logic deciding whether the plugin should trust the local projection as authoritative for reads.
- **Backend-proxy fallback**: The read path that serves live backend data while local projection is bootstrapping or degraded.
- **Audit closure bundle**: The committed SHA, deterministic tests, contract updates, and finding lifecycle changes required to pass the pre-merge gate.

## Current State Analysis

- `feature/invest-local-sync` already contains a committed slice (`#1439`, commit `65230db53cbe72b20b22e5744687e74cb697d723`) that fixes top-unlabeled fallback bootstrapping, empty-snapshot initialization, rowless gate behavior, unreachable cooldown recovery, and the H1 sentinel regression.
- `INVEST-LOCAL-SYNC` now has only two open product findings: `INVEST-LOCAL-SYNC-004-no-persistence-path-from-analyze` and `INVEST-LOCAL-SYNC-006-likely-coupling-to-bug401`.
- `BUG-401-recognition-auth-header` still carries 16 open review/audit findings that matter to local-sync correctness and closure:
- Medium severity: `VERIFY-1438-M3-branch-deletion-invalidates-1436-further`, `VERIFY-1438-M2-claimed-correction-pattern-does-not-exist`, `VERIFY-1438-M1-decision-name-violates-grammar`, `VERIFY-1436-M3-only-h1-addressed-other-findings-untouched`, `VERIFY-1436-M2-pre-merge-gate-not-satisfied`, `VERIFY-1436-M1-cross-task-finding-not-closed`, `REVIEW-LOCAL-SYNC-M2-projection-sync-fires-on-every-poll`, `REVIEW-LOCAL-SYNC-M1-singleton-count-invented`
- Low severity: `VERIFY-1438-L2-handoff-rounds-without-progress-meta-pattern`, `VERIFY-1438-L1-h1-fix-preserves-sentinel-write`, `VERIFY-1436-H2-fix-content-correct-when-applied`, `REVIEW-LOCAL-SYNC-L4-refresh-curation-metrics-on-empty-path`, `REVIEW-LOCAL-SYNC-L2-set-last-sync-result-untested`, `REVIEW-LOCAL-SYNC-L1-sse-call-site-untested`, `REVIEW-LOCAL-SYNC-M4-finding-004-fix-still-routes-through-snapshot`, `REVIEW-LOCAL-SYNC-M3-projection-status-bootstrapping-on-proxy-path`
- The branch has real commit and test evidence now, so the remaining work should shift from “prove anything happened” to “finish the missing behavior and cleanly retire stale review debt.”
- `handoff_close_check` still fails for `INVEST-LOCAL-SYNC` because the task is not active/done and two medium findings remain open; it also cannot become merge-ready cleanly until the cross-task BUG-401 review findings above are given explicit lifecycle outcomes.

## Target Outcome

Analyze completion becomes a durable local event rather than a hopeful precursor to a later snapshot sync. When a clustering/analyze job finishes, the plugin either projects that result locally immediately or records a precise, user-visible degraded state explaining why local projection could not be updated. Read-side fallback envelopes become contract-honest, repeated server-side triggers are bounded/idempotent, and the remaining review findings collapse to either `fixed` with proof or explicitly deferred follow-up work with rationale. The resulting branch can pass `handoff_close_check` without relying on stale or misleading decision rows.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/backend-php-guidelines.md`
- Rules: `docs/agentic/rules/testing-php.md`
- Rules: `docs/agentic/rules/branch-review-guide.md`
- Context maps: `docs/agentic/maps/php-plugin.md`, `docs/agentic/maps/integration.md`
- Contracts: `docs/agentic/contracts/recognition-clustering.md`, `docs/agentic/contracts/curation-sync-api.md`
- Handoff/MCP state: `INVEST-LOCAL-SYNC`, `BUG-401-recognition-auth-header`, decision `#1439`, open findings `INVEST-LOCAL-SYNC-004`, `INVEST-LOCAL-SYNC-006`, `REVIEW-LOCAL-SYNC-M1/M2/M3/M4`, `VERIFY-1436-*`, `VERIFY-1438-*`
- External docs via `ctx7` only if: backend FastAPI/transport behavior or a third-party library forces a contract decision that cannot be derived from repo code

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Analyze -> local projection persistence | plugin + backend integration | `docs/agentic/contracts/recognition-clustering.md`, `docs/agentic/maps/integration.md` | Update `docs/agentic/contracts/recognition-clustering.md` and any matching sync contract surface in the same slice so successful analyze/clustering completion can carry a deterministic projection payload without requiring a later snapshot round-trip | Yes; existing analyze callers must still receive the current response shape while the local projection path gains deterministic persistence semantics | PHPUnit controller/projector coverage plus runtime parity check of analyze-followed-by-offline-read |
| Snapshot/job-status sync health | plugin + backend integration | `docs/agentic/contracts/curation-sync-api.md`, `docs/agentic/maps/integration.md` | Surface or verify auth/transport failure modes distinctly so local-sync degradation is explicit instead of silent | Yes; keep current endpoints callable while making failure/projection status more truthful | PHPUnit for sync/job-status paths plus backend/runtime log or fixture verification |
| Backend-proxy fallback envelope | plugin controller + frontend consumer | `docs/agentic/contracts/recognition-clustering.md` | Remove invented metadata or source it from the backend/contract explicitly (`singleton_count`, `projection_status`, acknowledgement semantics) | Yes; frontend behavior must remain stable while response semantics become honest | PHPUnit response assertions and contract/doc update in same slice |
| Handoff / review closure evidence | MCP handoff + workflow docs | `docs/agentic/rules/development-workflow.md` | No behavioral contract change; task closes stale verification findings against the real branch SHA | N/A | `record_event`, `review_findings(update)`, `handoff_close_check` |

## Proposed Solution

Finish the feature in three code slices and one closure slice. First, give analyze/clustering completion a real local persistence path so durable local state no longer depends entirely on the snapshot endpoint. Second, make the snapshot/job-status path truthful and bounded by eliminating ambiguous fallback metadata and repeated server-side trigger behavior. Third, add the missing tests that prove these behaviors across the controller/projector/repository seams. Finally, resolve or defer the remaining review and provenance findings with commit-backed evidence so the branch can pass the pre-merge gate honestly.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend/plugin | `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php` | Add or route a direct local persistence/projection path for analyze completion and tighten acknowledgement/retry semantics |
| backend/plugin | `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Support direct projection/delta application and explicit degraded-state handling when snapshot persistence cannot complete |
| backend/plugin | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | Record explicit sync/projection state needed for truthful degraded/offline behavior without sentinel ambiguity |
| backend/plugin | `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php` | Remove invented fallback metadata and align proxy/local response envelopes with the documented contract |
| backend/plugin | `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php` | Surface bounded failure/retry state if snapshot persistence still fails after analyze completion |
| backend/plugin | `apps/prototype-wp-alt-context/tests/Unit/AnalysisJobsControllerTest.php` | Add direct-persistence, acknowledgement, and repeated-poll regression coverage |
| backend/plugin | `apps/prototype-wp-alt-context/tests/Unit/ClustersControllerTest.php` | Assert honest fallback metadata and corrected proxy/local read behavior |
| backend/plugin | `apps/prototype-wp-alt-context/tests/Unit/SyncStateRepositoryTest.php` | Add transition coverage for successful vs failed persistence state updates |
| backend/plugin | `apps/prototype-wp-alt-context/tests/Unit/SyncPullJobTest.php` | Verify bounded retry/degraded-state behavior |
| docs/contracts | `docs/agentic/contracts/recognition-clustering.md` | Update response/persistence semantics if fallback or analyze-projection behavior changes |
| docs/contracts | `docs/agentic/contracts/curation-sync-api.md` | Update sync-status or acknowledgement semantics if surfaced behavior changes |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | Likely home for shared projection gate or degraded-state logic touched by `INVEST-LOCAL-SYNC-006` |
| `apps/prototype-wp-alt-context/js/hooks/useJobStateMachineEffects.ts` | Frontend caller for projecting-phase sync behavior; verify whether server-side trigger work remains duplicated |
| `apps/prototype-wp-alt-context/js/components/TopClustersSection.tsx` | Consumer of `data_source`, `projection_status`, and singleton metadata; must stay consistent with any envelope changes |
| `apps/prototype-description-service/recognition/interface_adapters/http/routes/` | Backend route surface to inspect if job-status or snapshot payloads need explicit contract support |
| `docs/agentic/rules/development-workflow.md` | Governs final slice evidence and handoff close-check expectations |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/AnalysisJobsControllerTest.php tests/Unit/ClustersControllerTest.php tests/Unit/SnapshotProjectorTest.php tests/Unit/SyncPullJobTest.php tests/Unit/SyncStateRepositoryTest.php`
- Runtime-parity / environment checks:
  - Exercise analyze completion followed by a local read with the backend snapshot route intentionally unavailable, confirming locally durable data or an explicit degraded-state surface
  - Verify snapshot/job-status behavior after the BUG-401 auth fix is in scope on the same branch state
- Contract/fixture verification:
  - Assert that top-unlabeled fallback responses do not invent `singleton_count` or contradictory `projection_status`
  - Assert job-status/projection acknowledgement paths fire at most once per job/version unit
- Manual verification:
  - In the WordPress workbench, confirm the “Local identities are still syncing” symptom is replaced by either real local data or a precise degraded message after analyze completes
  - Run `handoff_close_check(enforce=True, current_commit_sha=<HEAD>)` once findings are updated

## Slice Delivery

### Slice 1: Direct Analyze Persistence

**Goal**: Make successful analyze/clustering completion produce durable local state without requiring a later snapshot round-trip.

Changes:

- Data source: extend the completed job-status path, not the raw `/recognition/analyze` response, to expose a completed-job projection payload for the affected tenant/job so the plugin can persist local state without calling the snapshot endpoint again
- Projection path: reuse `SnapshotProjector::project_delta()` (or a narrowly named sibling) so the new durability path writes through the same normalization/projection seam rather than inventing a second storage format
- Contract change: update `docs/agentic/contracts/recognition-clustering.md` and any matching job-status/sync contract surface to document the completed-job projection payload envelope and acknowledgement semantics
- Persist the sync/projection bookkeeping needed so local-authoritative reads become available immediately after successful analyze completion even when later snapshot fetches fail

Proof:

- PHPUnit coverage for the analyze controller + projector path, including a test with a failing `SnapshotClient` injected after analyze completion
- Runtime parity check showing analyze completion followed by a local read still works when snapshot fetch is unavailable

### Slice 2: Truthful Sync and Fallback Semantics

**Goal**: Remove ambiguous metadata and repeated side effects from fallback/projection status behavior.

Changes:

- Resolve `REVIEW-LOCAL-SYNC-M1` by sourcing `singleton_count` honestly or omitting it when the backend contract cannot support it
- Resolve `REVIEW-LOCAL-SYNC-M2` by bounding server-side projection triggering so repeated polling does not refire indefinitely
- Resolve `REVIEW-LOCAL-SYNC-M3` by making `projection_status` truthful on backend-proxy responses
- Resolve `INVEST-LOCAL-SYNC-006` by proving or explicitly surfacing snapshot/auth failure state rather than leaving it as a silent inference

Proof:

- PHPUnit response/state assertions covering fallback envelopes and poll deduplication
- Contract/doc update plus a runtime/log verification path for snapshot/auth behavior
- Backend verification that `/recognition/jobs/{id}` really carries `projection_acknowledged_at` with the semantics the plugin guard relies on, or a same-slice contract/backend change that adds and tests that field explicitly

### Slice 3: Coverage and Edge-Case Hardening

**Goal**: Close the remaining behavior-coverage gaps around the corrected implementation.

Changes:

- Add the missing persistence transition coverage (`REVIEW-LOCAL-SYNC-L2`)
- Add or extract testable SSE/polling logic to cover the higher-risk call site (`REVIEW-LOCAL-SYNC-L1`)
- Evaluate and either fix or explicitly defer low-risk performance/cleanup items by finding id: `REVIEW-LOCAL-SYNC-L4-refresh-curation-metrics-on-empty-path`, `VERIFY-1436-H2-fix-content-correct-when-applied`, and `VERIFY-1438-L1-h1-fix-preserves-sentinel-write`

Proof:

- Expanded PHPUnit subset passes on the branch HEAD
- Any intentionally deferred low-severity items are marked with rationale instead of left as open ambiguity

### Slice 4: Audit and Merge-Readiness Closure

**Goal**: Retire stale provenance/meta findings and leave the branch in an honest pre-merge state.

Changes:

- Close or defer the remaining `VERIFY-1436-*` and `VERIFY-1438-*` findings based on the real branch SHA and the final implementation state
- Update `INVEST-LOCAL-SYNC-004` and `006` to `fixed` or `deferred` with explicit rationale and verification
- Regenerate `CURRENT_TASK.md`, record a fresh slice-complete decision, and run `handoff_close_check`

Finding closure table:

| Finding ID | Target state | Planned handling |
| --- | --- | --- |
| `INVEST-LOCAL-SYNC-004-no-persistence-path-from-analyze` | `fixed` | Slice 1 |
| `INVEST-LOCAL-SYNC-006-likely-coupling-to-bug401` | `fixed` or `deferred` | Slice 2 |
| `REVIEW-LOCAL-SYNC-M1-singleton-count-invented` | `fixed` | Slice 2 |
| `REVIEW-LOCAL-SYNC-M2-projection-sync-fires-on-every-poll` | `fixed` | Slice 2 |
| `REVIEW-LOCAL-SYNC-M3-projection-status-bootstrapping-on-proxy-path` | `fixed` | Slice 2 |
| `REVIEW-LOCAL-SYNC-M4-finding-004-fix-still-routes-through-snapshot` | `fixed` if Slice 1 lands direct persistence; otherwise `deferred` with rationale | Slice 1 / Slice 4 |
| `REVIEW-LOCAL-SYNC-L1-sse-call-site-untested` | `fixed` | Slice 3 |
| `REVIEW-LOCAL-SYNC-L2-set-last-sync-result-untested` | `fixed` | Slice 3 |
| `REVIEW-LOCAL-SYNC-L4-refresh-curation-metrics-on-empty-path` | `fixed` or `deferred` | Slice 3 |
| `VERIFY-1436-H2-fix-content-correct-when-applied` | `fixed` | Slice 3 |
| `VERIFY-1436-M1-cross-task-finding-not-closed` | `fixed` | Slice 4 |
| `VERIFY-1436-M2-pre-merge-gate-not-satisfied` | `fixed` | Slice 4 |
| `VERIFY-1436-M3-only-h1-addressed-other-findings-untouched` | `fixed` | Slice 4 |
| `VERIFY-1438-M1-decision-name-violates-grammar` | `wontfix` | Slice 4; append-only historical decision row |
| `VERIFY-1438-M2-claimed-correction-pattern-does-not-exist` | `wontfix` | Slice 4; append-only historical decision row |
| `VERIFY-1438-M3-branch-deletion-invalidates-1436-further` | `fixed` | Slice 4; superseding branch/decision evidence |
| `VERIFY-1438-L1-h1-fix-preserves-sentinel-write` | `fixed` or `deferred` | Slice 3 / Slice 4 |
| `VERIFY-1438-L2-handoff-rounds-without-progress-meta-pattern` | `deferred` | Slice 4; route to process-hardening follow-up |

Proof:

- `review_findings(operation="list", task_ref="INVEST-LOCAL-SYNC", status="open")` returns zero or only explicitly deferred/wontfix items
- `handoff_close_check(enforce=True, current_commit_sha=<HEAD>)`

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the PHP-plugin, integration, testing, and branch-review guidance before editing.
- [ ] Verified the current open MCP findings for `INVEST-LOCAL-SYNC` and `BUG-401-recognition-auth-header`.
- [ ] Confirmed whether each boundary change is owned by plugin code, backend payloads, or contract docs before implementation.

### Checklist for Slice 1: Direct Analyze Persistence

- [ ] Successful analyze/job-complete flow writes durable local projection state without depending solely on snapshot pull success.
- [ ] Sync/projection bookkeeping is updated in the same slice.
- [ ] Contract/docs/tests are updated in the same slice.

### Checklist for Slice 2: Truthful Sync and Fallback Semantics

- [ ] Fallback response metadata is honest and contract-backed.
- [ ] Repeated job-status/SSE polling does not refire projection sync indefinitely.
- [ ] Snapshot/auth failure state is either fixed or surfaced explicitly enough to close `INVEST-LOCAL-SYNC-006`.

### Checklist for Slice 3: Coverage and Edge-Case Hardening

- [ ] Missing persistence transition tests are added.
- [ ] SSE/polling coverage exists for the higher-risk call path.
- [ ] Any remaining low-risk implementation findings are either fixed or explicitly deferred with rationale.

### Checklist for Slice 4: Audit and Merge-Readiness Closure

- [ ] Remaining review/provenance findings are updated against the real branch SHA.
- [ ] Slice 4 applies the explicit finding closure table rather than ad hoc cleanup.
- [ ] `CURRENT_TASK.md` is regenerated after handoff state changes.
- [ ] `handoff_close_check` passes or reports only intentionally deferred items.

## Review Readiness

- [ ] No boundary-touching behavior change is left without matching contract/doc/test evidence.
- [ ] The final slice evidence is tied to the actual branch HEAD, not a worktree-only diff.
- [ ] Handoff decisions and finding closures describe real implementation progress rather than meta commentary.

## Stretch Goals

- [ ] If the direct analyze-persistence path lands cleanly, evaluate whether the snapshot path can become a reconciliation mechanism rather than the primary durability path.
- [ ] If practical, replace sentinel-write fallback behavior with a `NULL`/unset write path so the read guard becomes true defense-in-depth instead of a required invariant.

## Success Criteria

- [ ] A completed analyze/clustering flow leaves usable local data or an explicit degraded state even when the snapshot route is unavailable immediately afterward.
- [ ] No fallback response invents unsupported metadata or contradictory projection status.
- [ ] Polling-based projection triggers are idempotent and covered by tests.
- [ ] The remaining open `INVEST-LOCAL-SYNC` findings are fixed or explicitly deferred with rationale.
- [ ] The branch can satisfy `handoff_close_check` using real commit-backed evidence.
