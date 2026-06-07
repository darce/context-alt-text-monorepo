# REFA-1. Decompose `class-cluster-mutations-controller.php`

> **Metadata**
>
> - **Date**: 2026-06-07
> - **Author**: Claude (claude-opus-4-8)
> - **Owning Epic**: `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
> - **Epic Short ID**: REFA
> - **Target Branch**: `feature/refa-1`
> - **Review Coverage Target**: 2
>
> **Review coverage note:** Finding/coverage state is DB-generated. Query with
> `review_findings(operation=list, task_ref=REFA-1)` / `review_runs(operation=coverage, task_ref=REFA-1)`.
> Claims re-verified vs `main` HEAD `0a955f1c` (2026-06-07).

## Objective

Reduce `src/api/class-cluster-mutations-controller.php` (1257 LOC, 21 declared methods, 11 `acx/v1` routes) to a thin composition root that delegates each mutation operation to a focused service, **without changing observable behavior**. Phase 1 of epic REFA.

## Problem Statement

The controller concentrates 11 route handlers plus their business logic, request parsing, inline transactions, and curation-marker side effects in one class. Only the dual-write path is covered (`ClusterMutationsControllerDualWriteTest`); the other handlers have no characterization safety net, so any edit risks silent `acx/v1` regressions.

The 11 route handlers (verified): `cluster_media`, `reassign_cluster_identity`, `update_cluster_label`, `dismiss_cluster`, `undismiss_cluster`, `merge_cluster`, `split_cluster`, `create_cluster_for_identity`, `revert_merge_cluster`, `assign_outlier_to_cluster`, `pin_representative`.

## Constraints

- Behavior-preserving; `acx/v1` response shapes unchanged (rg-002; no contract change).
- Preserve exact inline transaction boundaries (`$wpdb->query('START TRANSACTION'|'COMMIT'|'ROLLBACK')`, e.g. lines 247/319/383); no commit/rollback timing change (sr-009/rg-002). `run_transactional` adoption is deferred (epic Deferred).
- Preserve the `SyncStateRepository::touch_local_curation_marker()` side effect (and `get_snapshot_version` reads) on the handlers that currently invoke it (label/dismiss/split today); do not add or drop it elsewhere.
- sr-008: service constructors group >8 collaborators into typed objects.
- rg-016: new `class-*.php` is not PSR-4 autoloaded — add `require_once` in `src/api/class-api.php` and verify.

## Workflow Principles

- Safety net first: golden-JSON characterization for every route before extraction (Fowler Ch4).
- Two Hats; one cohesive service per extraction step; compile/test after each.
- Per-slice stop rule: any behavior diff in a golden assertion, or 2 consecutive red steps with unclear cause → revert and re-plan smaller.
- Format before lint (`composer cs-fix`); never relax a gate.
- Each slice decision cites `docs/tasks/tech-debt/refactoring-evaluation.md` + Fowler Ch7 (Extract Class).

## Terminology

- **Composition root**: controller keeps route registration + request parsing, delegates logic to injected services. Mirror the established **constructor-injection idiom** (`?Dep $x = null` → `$x ?? new Dep()`) used by `class-recognition-controller.php` and by this controller itself. NB: recognition-controller is a controller-of-controllers *facade* (it injects 8 sub-controllers, including this one), **not** a service layer — `AltContext\Api\Services\` is a new layer this task introduces.
- **Characterization (golden JSON)**: `WP_REST_Request` dispatched via `rest_do_request()`, response serialized to a committed fixture, asserted byte-equal pre/post.

## Current State Analysis

- Works: all 11 routes function; the dual-write path is covered.
- Insufficient: 10 of 11 handlers lack characterization; logic + parsing + transactions + curation-marker side effects are co-located in one 1257-LOC class.
- Misleading: only `ClusterMutationsControllerDualWriteTest` exists, giving false confidence the controller is "covered."

## Target Outcome

`class-cluster-mutations-controller.php` shrinks to route registration + parsing + delegation. All 11 handlers move into ~6 cohesive, unit-tested services under `src/api/services/` (`AltContext\Api\Services\`). Every route returns byte-identical `acx/v1` responses; all existing + new tests green.

## Context Loading

- Rules: `docs/workstate/rules/backend-php-guidelines.md`, constitution (sr-008/sr-009, rg-002/rg-016).
- Injection-idiom precedent: `src/api/class-recognition-controller.php`; registrar: `src/api/class-api.php`.
- Technique: `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler Ch7).
- Handoff: epic `REFA`; this task `REFA-1`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `acx/v1` cluster-mutation routes (11) | backend | response shapes in this controller | **none** (behavior-preserving) | no | golden-JSON parity via `rest_do_request` for all 11; `ClusterMutationsControllerDualWriteTest` |

## Proposed Solution

Write golden-JSON characterization for all 11 routes first, then Extract Class per cohesive operation group into `AltContext\Api\Services\` collaborators injected via the existing nullable-constructor idiom. Route registration + request parsing stay in the controller (composition root). Inline transactions and the `touch_local_curation_marker` side effect move with their operation but keep identical boundaries/timing. Register each new service via `require_once` in `src/api/class-api.php` (rg-016).

Service grouping (covers all 11 handlers):

| Service | Handlers |
| --- | --- |
| `ClusterLabelService` | `update_cluster_label` |
| `ClusterLifecycleService` | `dismiss_cluster`, `undismiss_cluster` |
| `ClusterMergeService` | `merge_cluster`, `revert_merge_cluster` |
| `ClusterSplitService` | `split_cluster` |
| `ClusterMembershipService` | `reassign_cluster_identity`, `assign_outlier_to_cluster`, `create_cluster_for_identity` |
| `ClusterRepresentativeService` | `pin_representative` |
| (controller or `ClusterMediaService`) | `cluster_media` — verify read-vs-mutation at Slice 1; keep in controller if a thin read |

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `src/api/class-cluster-mutations-controller.php` | reduce to composition root delegating all 11 handlers |
| backend (new) | `src/api/services/class-cluster-label-service.php`, `…-lifecycle-service.php`, `…-merge-service.php`, `…-split-service.php`, `…-membership-service.php`, `…-representative-service.php` (+ optional `…-media-service.php`) | extracted operation services (`AltContext\Api\Services\`) |
| backend (autoload) | `src/api/class-api.php` | `require_once` each new service |
| tests | `tests/Unit/ClusterMutations*` + new per-service tests + golden fixtures | characterization + unit coverage |

## Related Files

| File | Note |
| --- | --- |
| `src/api/class-recognition-controller.php` | constructor-injection idiom precedent (a facade of sub-controllers, not a service layer) |
| `src/sovereign/repositories/class-clusters-repository.php` | collaborator (REFA-2 target — do not refactor here) |
| `SyncStateRepository::touch_local_curation_marker()` | curation-marker side effect — preserve on handlers that currently call it (label/dismiss/split) |

## Verification Strategy

- Deterministic: `cd apps/prototype-wp-alt-context && composer test && composer phpstan && composer cs-check`.
- Autoload (rg-016) per new service: `composer dump-autoload && php -l <file> && php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\Api\\\\Services\\\\ClusterLabelService'));"`.
- Contract: golden-JSON fixtures asserted byte-equal before vs. after each extraction for all 11 routes.
- Full gate before review-ready: root `make check-all`.

## Slice Delivery

### Slice 1: Characterization safety net

**Goal**: Pin current behavior of all 11 routes before touching structure; classify `cluster_media` as read or mutation.

Changes:
- Golden-JSON fixtures via `rest_do_request()` for all 11 handlers; capture side effects (outbox, `touch_local_curation_marker`, snapshot_version).

Proof: new characterization tests green against the current controller; `composer test` green.

### Slice 2: Extract `ClusterLabelService` + `ClusterLifecycleService`

**Goal**: Move label and dismiss/undismiss logic to services; prove the extraction pattern (both carry transactions + curation marker).

Changes:
- `ClusterLabelService` (`update_cluster_label`), `ClusterLifecycleService` (`dismiss_cluster`, `undismiss_cluster`); controller delegates; `require_once` in `class-api.php`.

Proof: label/dismiss/undismiss golden fixtures byte-identical; per-service tests; phpstan/cs green.

### Slice 3: Extract `ClusterMergeService` + `ClusterSplitService`

**Goal**: Move merge/revert-merge and split logic (transaction-bearing) to services.

Changes:
- `ClusterMergeService` (`merge_cluster`, `revert_merge_cluster`), `ClusterSplitService` (`split_cluster`); preserve transaction boundaries + curation marker.

Proof: merge/revert-merge/split golden fixtures byte-identical; per-service tests; phpstan/cs green.

### Slice 4: Extract membership + representative; resolve `cluster_media`; thin controller

**Goal**: Finish extraction; controller becomes thin dispatch.

Changes:
- `ClusterMembershipService` (`reassign_cluster_identity`, `assign_outlier_to_cluster`, `create_cluster_for_identity`), `ClusterRepresentativeService` (`pin_representative`); place `cluster_media` per Slice-1 classification; remove residual business logic from controller.

Proof: all 11 golden fixtures byte-identical; full per-service unit coverage; `make check-all` green.

---

## Consolidated Checklist

> Describe work delivered, not finding status (query `review_findings(operation=list, status=open, task_ref=REFA-1)`).

## Context and Ownership

- [ ] Loaded backend-php guidelines + constitution (sr-008/sr-009, rg-002/rg-016) and the Fowler evaluation.
- [ ] Confirmed `ctx7` not required.
- [ ] Recorded `acx/v1` boundary ownership = backend, expected change = none.

### Checklist for Slice 1: Characterization safety net

- [ ] Golden-JSON fixtures for all 11 routes (incl. side effects) committed.
- [ ] `cluster_media` classified read-vs-mutation.
- [ ] Characterization tests green against the current controller.

### Checklist for Slice 2: Extract label + lifecycle services

- [ ] `ClusterLabelService` + `ClusterLifecycleService` created under `src/api/services/`; controller delegates; `require_once` added + verified.
- [ ] label/dismiss/undismiss golden fixtures byte-identical; per-service tests green.

### Checklist for Slice 3: Extract merge + split services

- [ ] `ClusterMergeService` + `ClusterSplitService` extracted; transaction boundaries + curation marker preserved.
- [ ] merge/revert-merge/split golden fixtures byte-identical; per-service tests green.

### Checklist for Slice 4: Extract membership + representative; thin controller

- [ ] `ClusterMembershipService` + `ClusterRepresentativeService` extracted; `cluster_media` placed; controller reduced to composition root.
- [ ] All 11 golden fixtures byte-identical; `make check-all` green.

## Review Readiness

- [ ] Every extracted handler has golden-JSON + unit evidence; no behavior-touching change without proof.
- [ ] rg-016 autoload checks run for each new service.
- [ ] Handoff decision records moves, verification, citation, and confirms no `acx/v1` shape change.

## Stretch Goals

- [ ] Note any `run_transactional` extraction opportunity for the epic's deferred wrapper slice (do not implement here).

## Success Criteria

- [ ] Controller reduced to a thin composition root; all 11 handlers delegated to ~6 unit-tested services.
- [ ] All 11 `acx/v1` routes return byte-identical responses (golden fixtures prove it).
- [ ] `make check-all` green at HEAD.
