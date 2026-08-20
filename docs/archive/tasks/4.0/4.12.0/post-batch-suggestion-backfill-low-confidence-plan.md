# 4.12.0 Implementation Plan: Post-Batch Suggestion Backfill and Low-Confidence Inference

## Problem Statement

Top unlabeled cards remain stuck on "Name this person" even when embeddings strongly match existing confirmed identities. This happens most often after later scan batches, where new unlabeled clusters are created after the one-time "newly labeled cluster" surfacing pass already ran. Users need those cards to become suggestion CTAs (including low-confidence variants) without requiring manual rename/relabel loops.

## Roadmap Alignment

This plan advances the sovereign cluster roadmap (`docs/roadmaps/v0.1.0/wp-sovereign-cluster-roadmap.md`) by improving the **data quality of backend compute** — making suggestion and inference output more complete before it lands in a snapshot. Specifically:

- **Inference robustness** (Phase 1) improves snapshot content — clusters that previously had no suggestion will now have one when the snapshot is pulled.
- **Post-batch backfill** (Phase 2) ensures suggestion coverage is continuous, so snapshots contain current suggestion state for all clusters, not just those that existed at label-time.
- **Rejection lifecycle** (Phase 3) is scoped to avoid violating the roadmap's curation-first precedence policy. See Phase 3 notes.

**Not in scope:** This plan does not build any WordPress-local storage or sync infrastructure. It deepens backend intelligence that will feed into the roadmap's snapshot export endpoint once built.

## Workflow Principles

- Suggestion surfacing must be continuous across batches, not only at label-time.
- Confirmed labels remain the only automatic target candidates.
- Low-confidence suggestions are shown as reviewable, never auto-merged.
- Rejected suggestions are respected, but stale rejections must not permanently hide newly valid matches.
- Rejection reopening must respect the roadmap's curation-first precedence: the backend must not autonomously override user curation decisions.

## Terminology

- **Post-batch backfill**: Re-running suggestion surfacing for newly created unlabeled clusters against all confirmed clusters after each clustering batch.
- **Inference fallback**: Top-unlabeled label inference path that works even when `representative_identity_id` is null.
- **Low-confidence suggestion**: Similarity in the reviewable band (below normal confidence, above minimum surfacing floor), shown with explicit caution styling.
- **Stale rejection**: A previously rejected suggestion whose source cluster/representatives changed enough that the old rejection should not be treated as permanent.

## Current State Analysis

- `surface_for_newly_labeled_cluster` is triggered when labels are created, but new unlabeled clusters from later batches are not revisited against already confirmed clusters.
- Top-unlabeled inference exits early if `target_cluster.representative_identity` is missing, even when the cluster has representative embeddings in `identity_cluster_representatives`.
- Suggestion upsert keeps non-pending rows untouched, so previously rejected matches do not re-open in later contexts.
- Observed clusters show strong similarity to expected confirmed identities while remaining unlabeled cards.
- This behavior is mostly "working as currently designed" but mismatched with intended curation UX.

## Proposed Solution

Implement a continuous suggestion lifecycle:

1. Add post-batch backfill orchestration that evaluates new unlabeled clusters against all confirmed clusters after clustering completes.
2. Make top-unlabeled inference resilient to missing `representative_identity_id` by using representative rows (and member fallback) as embedding source.
3. Introduce controlled stale-rejection handling for backfill context — surface as _new evidence_ rather than reopening the original rejected suggestion (aligns with roadmap curation-first precedence).
4. Keep the existing low-confidence surfacing band but ensure it is reachable in post-batch backfill and exposed in top-card CTA metadata.
5. Preserve idempotency: one identity-target pair is surfaced once per effective state (keyed by `identity_id` + `cluster_id` + `evidence_generation`).

## Design Decisions

### Rejection Gate — Curation-Driven, Not Time-Based

The gate for surfacing new-evidence suggestions after a rejection is purely curation-driven: did the confirmed cluster's representative set change since the rejection? If yes → surface new evidence. If no → skip.

No time-based cooldown window. A fixed cooldown (e.g., 7 days) assumes constant usage cadence, which cannot be guaranteed — users may engage in bursts separated by weeks or months. Time is the wrong signal. The representative set delta is the right one: it directly measures whether the cluster context that produced the rejection is still the same context. The `_cluster_context_changed()` predicate compares the confirmed cluster's representative set composition at `resolved_at` against its current state. If representatives were added, removed, or replaced, context has changed and new evidence is warranted.

This eliminates a settings field (`rejection_cooldown_days`) that would consume cognitive space for a trivial decision with no correct universal default.

### Dedup Key — Schema Change Required (`evidence_generation` Column)

The existing `SuggestionModel` has a unique constraint on `(identity_id, suggested_cluster_id)` ([db/models/constraints.py line 105](../../../../apps/prototype-description-service/db/models/constraints.py#L105)). You **cannot** create a second suggestion row for the same identity→cluster pair without violating this constraint. Encoding generation in `source` or metadata doesn't help — the DB will reject the INSERT regardless.

Required schema change:

- Add `evidence_generation: int` column (default `0`, matching all existing rows)
- Widen unique constraint to `(identity_id, suggested_cluster_id, evidence_generation)`

```python
# db/models/constraints.py — SuggestionModel
evidence_generation: Mapped[int] = mapped_column(
    Integer, nullable=False, server_default=text("0")
)

# Updated unique constraint:
UniqueConstraint(
    "identity_id", "suggested_cluster_id", "evidence_generation",
    name="unique_identity_suggestion",
)
```

Generation 0 = original suggestion. Generation N+1 = new-evidence re-proposal after context change. Both the original rejection and new evidence coexist as separate rows with clean audit trail. Greenfield DB — migration cost is zero.

### Backfill Trigger Point — Clustering Jobs Only

Backfill runs after successful clustering jobs only. Manual operations (label, split, merge, reassign) are already covered by existing infrastructure:

- **Label/rename** → calls `surface_for_newly_labeled_cluster` directly ([cluster_service.py line 294](../../../../apps/prototype-description-service/recognition/application/orchestration/cluster_service.py#L294))
- **Split** → produces `SuggestionRefreshReason.MANUAL_SPLIT`, triggers suggestion refresh for new sub-clusters
- **Merge** → `cluster_merge.py` resolves pending suggestions for the absorbed cluster
- **Reassign** → `SuggestionRefreshReason.MANUAL_ASSIGN` handles re-evaluation

Backfill solves a different problem: new unlabeled clusters from batch processing that missed the label-time surfacing window. If a manual operation gap is discovered later, add it then.

### Candidate Set Bounds — Strict IDs With Time-Window Fallback

Use `created_cluster_ids` from `ClusterJobResult` as the primary candidate set. Add a bounded time-window fallback for resiliency (catches clusters missed due to race conditions or partial job failures).

```python
async def backfill_for_new_unlabeled_clusters(
    self,
    *,
    tenant_id: str,
    created_cluster_ids: Sequence[str],
    fallback_window_minutes: int = 30,
) -> int:
    candidates = set(created_cluster_ids)

    # Resiliency: catch clusters created in the window that were
    # missed due to race conditions or partial job results.
    if fallback_window_minutes > 0:
        recent = await cluster_repo.get_unlabeled_created_after(
            tenant_id, minutes_ago=fallback_window_minutes
        )
        candidates |= {c.id for c in recent}
```

Strict IDs are deterministic and testable. The 30-minute fallback window is generous (clustering jobs rarely take more than a few minutes). `fallback_window_minutes` is a parameter so tests can set it to `0` for determinism.

A full "all unlabeled clusters without suggestions" sweep is intentionally not part of post-batch flow — that's a separate admin reindex action.

## Patterns to Follow

### Backend: Post-Batch Backfill Orchestration

```python
async def backfill_for_new_unlabeled_clusters(
    self,
    *,
    tenant_id: str,
    created_cluster_ids: Sequence[str],
    fallback_window_minutes: int = 30,
) -> int:
    """Surface suggestions for newly created unlabeled clusters against confirmed labels.

    Uses created_cluster_ids as the primary candidate set, with a time-window
    fallback for resiliency (race conditions, partial job failures).
    Triggered after successful clustering jobs only — manual ops are
    already covered by existing refresh infrastructure.
    """
    candidates = set(created_cluster_ids)
    if fallback_window_minutes > 0:
        recent = await self._cluster_repo.get_unlabeled_created_after(
            tenant_id, minutes_ago=fallback_window_minutes
        )
        candidates |= {c.id for c in recent}

    if not candidates:
        return 0

    confirmed_clusters = await self._cluster_repo.get_confirmed_labeled(tenant_id)
    if not confirmed_clusters:
        return 0

    surfaced = 0
    for confirmed in confirmed_clusters:
        surfaced += await self.surface_for_newly_labeled_cluster(
            cluster_id=confirmed.id,
            cluster_label=confirmed.label,
            candidate_cluster_ids=list(candidates),
        )
    return surfaced
```

### Backend: Inference Fallback Without Representative Identity Link

```python
if not target_cluster.representative_identity:
    reps = await cluster_repository.get_representative_embeddings(cluster_id)
    if not reps:
        reps = await cluster_repository.get_member_fallback_embeddings(cluster_id, limit=4)
    if not reps:
        return None
    target_embedding = np.mean(np.asarray(reps, dtype=np.float32), axis=0)
```

### Backend: Stale-Context New-Evidence Pattern (Roadmap-Aligned)

Instead of reopening rejected suggestions (which violates curation-first precedence), surface a **new suggestion row** with a different provenance marker when cluster context has materially changed since the rejection. The original rejection remains intact.

```python
if existing_suggestion and existing_suggestion.resolution == SuggestionStatus.REJECTED.value:
    if not _cluster_context_changed(cluster_uuid, existing_suggestion.resolved_at):
        # Representative set unchanged since rejection — skip.
        # No time-based cooldown: the gate is purely whether the
        # cluster's representative composition changed, not how
        # long ago the user rejected.
        return self._to_domain(existing_suggestion)

    # Representative set changed since rejection — create NEW suggestion row
    # with incremented evidence_generation. Original rejection stays immutable.
    next_gen = existing_suggestion.evidence_generation + 1
    model = SuggestionModel(
        tenant_id=tenant_uuid,
        identity_id=identity_uuid,
        suggested_cluster_id=cluster_uuid,
        representative_similarity=_clamp_similarity(payload.representative_similarity),
        avg_member_similarity=_clamp_similarity(payload.member_similarity),
        confidence_score=_clamp_similarity(payload.confidence_score),
        resolution=SuggestionStatus.PENDING.value,
        source="backfill_new_evidence",
        evidence_generation=next_gen,
    )
    self._session.add(model)
    await self._session.flush()
    await self._session.refresh(model)
    return self._to_domain(model)
```

> **Roadmap alignment:** The sovereign cluster roadmap states "Backend suggestions can propose, but must not overwrite curated ground truth without explicit user action." A rejected suggestion is curated ground truth. Reopening it server-side would violate this principle. The new-evidence pattern surfaces changed context as a _proposal_ without mutating the user's prior decision.

### Frontend: Low-Confidence CTA Styling (ALREADY IMPLEMENTED)

> **Status: Complete.** `SuggestionReviewPanel.tsx` already implements `isLowConfidence` detection at line 75 using `LOW_CONFIDENCE_THRESHOLD = 0.6`, applies `acx-suggestion-card--low-confidence` class at line 100, and renders a caution indicator at line 167. SCSS styling exists at `_workbench.scss` line 610. Test coverage exists at `SuggestionReviewPanel.test.tsx` line 453.

No frontend work needed for low-confidence styling.

## Functions to Change

| File                                                               | Actual Location                                                 | Change                                                                                                                                                                                                         |
| ------------------------------------------------------------------ | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `recognition/application/suggestions/label_inference.py`           | Line 152–153 (nearest-neighbor fallback section)                | Remove hard `return None` when `representative_identity` is null; add representative table / member fallback embedding lookup.                                                                                 |
| `recognition/infrastructure/repositories/cluster_repository.py`    | New methods                                                     | Add `get_representative_embeddings(cluster_id)` and `get_member_fallback_embeddings(cluster_id, limit)` queries against `identity_cluster_representatives` and `identity_members` + `media_identities` tables. |
| `recognition/application/suggestions/refresh_service.py`           | After line 677 (after `surface_for_newly_labeled_cluster`)      | Add sibling method `backfill_for_new_unlabeled_clusters()` that iterates confirmed clusters and calls `surface_for_newly_labeled_cluster` with `candidate_cluster_ids`.                                        |
| `recognition/application/orchestration/clustering/orchestrator.py` | `ClusterJobResult` dataclass + `_process_chunks` + `run()`      | Extend `ClusterJobResult` to carry `created_cluster_ids: list[str]`. Collect IDs during chunk processing and return them.                                                                                      |
| `recognition/application/tasks/clustering.py`                      | After existing `run_background_surface_suggestions` (~line 193) | Add new `run_background_backfill_suggestions` function (same fresh-session pattern) that calls `backfill_for_new_unlabeled_clusters` with the newly created cluster IDs.                                       |
| `recognition/infrastructure/repositories/suggestion_repository.py` | `_upsert_suggestion` (line 371–384)                             | Add new-evidence path: when existing suggestion is rejected and `_cluster_context_changed` returns true, create new row with incremented `evidence_generation`.                                                 |
| `db/models/constraints.py`                                         | `SuggestionModel` (line 55–105)                                 | Add `evidence_generation` integer column (default 0). Widen unique constraint to `(identity_id, suggested_cluster_id, evidence_generation)`.                                                                   |
| `recognition/infrastructure/repositories/cluster_repository.py`    | New method                                                      | Add `get_unlabeled_created_after(tenant_id, minutes_ago)` for time-window fallback candidate set.                                                                                                              |
| `recognition/interface_adapters/http/routers/clusters.py`          | Lines 198–210 (top-unlabeled CTA enrichment)                    | No change needed — `infer_suggested_label` improvements flow through automatically. Verify inference results include low-confidence metadata.                                                                  |
| `recognition/tests/service/test_suggestion_refresh.py`             | Append                                                          | Add tests for post-batch backfill orchestration and new-evidence pattern for stale rejections.                                                                                                                 |
| `recognition/tests/integration/test_label_inference.py`            | Append                                                          | Add case: cluster with null `representative_identity_id` but rows in `identity_cluster_representatives`.                                                                                                       |
| `recognition/tests/integration/test_pipeline_integration.py`       | Append                                                          | Add end-to-end backfill test across multi-batch flow.                                                                                                                                                          |

### Frontend — No Changes Needed

| File                             | Status                                                                                                                   |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `SuggestionReviewPanel.tsx`      | **Already complete.** Low-confidence detection at line 75, class application at line 100, caution indicator at line 167. |
| `_workbench.scss`                | **Already complete.** `--low-confidence` modifier at line 610.                                                           |
| `SuggestionReviewPanel.test.tsx` | **Already complete.** Low-confidence test at line 453.                                                                   |

## Related Files

| File                                                                        | Note                                                                                            |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `recognition/application/assignment/checks/confidence.py`                   | Defines suggestion band and fatal quality behavior that low-confidence surfacing depends on.    |
| `recognition/application/settings/clustering.py`                            | Holds `suggestion_floor`, low-confidence band settings, and floor derivation.                   |
| `recognition/domain/suggestion.py`                                          | Source enums and suggestion status semantics used by new-evidence policy.                       |
| `recognition/application/orchestration/clustering/job_result.py`            | `ClusterJobResult` dataclass — needs `created_cluster_ids` field.                               |
| `db/models/identity.py`                                                     | `IdentityClusterRepresentative` model (line 186) — source for representative embedding queries. |
| `db/models/constraints.py`                                                  | `SuggestionModel` — needs `evidence_generation` column + widened unique constraint.             |
| `recognition/application/orchestration/protocols.py`                        | `SuggestionRefreshServiceProtocol` — needs backfill method signature.                           |
| `logs/recognition.log`                                                      | Validation source for proving post-batch surfacing behavior in real runs.                       |
| `docs/tasks/4.0/4.12.0/suggestion-panel-current-batch-top-clusters-plan.md` | Prior queue architecture plan this slice extends.                                               |
| `docs/roadmaps/v0.1.0/wp-sovereign-cluster-roadmap.md`                      | Sovereign cluster roadmap — curation-first precedence policy governs rejection handling.        |
| `CURRENT_TASK.md`                                                           | Active tracker that should reference this plan once implementation begins.                      |

---

# Consolidated Checklist

## Completed

- [x] Confirmed media-to-identity mapping for reported cards.
- [x] Verified strong similarity cases that remained unlabeled.
- [x] Confirmed no block/constraint records preventing these specific matches.
- [x] Confirmed lifecycle gap: label-time surfacing only, no guaranteed post-batch backfill.

## Phase 0: Scaffolding

- [x] Add `backfill_for_new_unlabeled_clusters` signature to `SuggestionRefreshServiceProtocol` in `orchestration/protocols.py`.
- [x] Add `get_representative_embeddings` and `get_member_fallback_embeddings` signatures to `ClusterRepository` protocol in `domain/repositories.py`.
- [x] Add `get_unlabeled_created_after(tenant_id, minutes_ago)` signature to `ClusterRepository` protocol.
- [x] Extend `ClusterJobResult` with `created_cluster_ids: list[str]` field.
- [x] Add `evidence_generation` column to `SuggestionModel` in `db/models/constraints.py` (default `0`). Widen unique constraint to `(identity_id, suggested_cluster_id, evidence_generation)`.
- [x] Generate Alembic migration for schema change. (Greenfield baseline updated; optional standalone migration still pending.)
- [x] Add test coverage in `tests/service/test_suggestion_refresh.py` and `tests/integration/test_label_inference.py` (implemented concrete tests instead of `@pytest.mark.skip("scaffold")` stubs).
- [x] Verify type checks compile: `PYENV_VERSION=description-service mypy .`.

> **Implementation order note:** Phase 1 (inference) should be implemented before Phase 2 (backfill) because it is the smallest, most isolated change with immediate value. Fixing the `representative_identity` null guard alone will improve top-card CTAs without any backfill machinery.

## Phase 1: Inference Robustness (Highest Value, Lowest Risk)

- [x] Add `get_representative_embeddings(cluster_id)` to `SqlAlchemyClusterRepository` — query `identity_cluster_representatives` table for embeddings by cluster.
- [x] Add `get_member_fallback_embeddings(cluster_id, limit=4)` to `SqlAlchemyClusterRepository` — query `identity_members` → `media_identities` for embedding fallback.
- [x] Update `infer_suggested_label` nearest-neighbor section to use representative table rows when `representative_identity` is null, with member fallback.
- [x] Mean-pool multiple representative embeddings into a single target embedding for cosine search.
- [x] Preserve confidence/source metadata contract for top-unlabeled CTA (no API change needed).
- [x] Add integration test: cluster with null `representative_identity_id` but rows in `identity_cluster_representatives` still receives inferred suggestion.

## Phase 2: Post-Batch Backfill Orchestration

> **Trigger scope:** Backfill runs after successful clustering jobs only. Manual operations (label, split, merge, reassign) are already covered by existing suggestion refresh infrastructure — see Design Decisions.

- [x] Add `backfill_for_new_unlabeled_clusters()` to `SuggestionRefreshService` with `created_cluster_ids` primary set + `fallback_window_minutes=30` time-window fallback.
- [x] Add `get_confirmed_labeled(tenant_id)` helper to `SqlAlchemyClusterRepository` — `get_confirmed_with_representatives` does not exist.
- [x] Add `get_unlabeled_created_after(tenant_id, minutes_ago)` to `SqlAlchemyClusterRepository` for fallback candidate set.
- [x] Collect created cluster IDs in orchestrator's `_process_chunks` and populate `ClusterJobResult.created_cluster_ids`.
- [x] Add `run_background_backfill_suggestions` in `tasks/clustering.py` (fresh-session pattern, matching `run_background_surface_suggestions` structure).
- [x] Wire backfill trigger in scan worker after successful clustering completion, passing created cluster IDs.
- [x] Add 30s timeout guard matching existing background task pattern.
- [x] Add idempotent accounting to avoid duplicate suggestion churn (keyed by `identity_id` + `cluster_id` + `evidence_generation`).
- [x] Add observable logs for surfaced, skipped, and fallback-recovered suggestion counts.
- [x] Add service test for backfill orchestration (set `fallback_window_minutes=0` for determinism).
- [x] Add end-to-end integration test for multi-batch backfill flow.

## Phase 3: Rejection Lifecycle Policy (Roadmap-Aligned)

> **Curation-first constraint:** The sovereign cluster roadmap states backend suggestions "must not overwrite curated ground truth without explicit user action." A user's rejection is curated ground truth. This phase uses a **new-evidence pattern** instead of reopening rejected suggestions.

- [x] Define `_cluster_context_changed()` predicate: return true if the confirmed cluster's representative set composition changed after `resolved_at` on the rejection (representatives added, removed, or replaced). No time-based cooldown — the representative delta is the only gate.
- [x] When `_upsert_suggestion` encounters a rejected suggestion and `_cluster_context_changed` returns true, create a **new suggestion row** with `evidence_generation = max(existing) + 1` and `source="backfill_new_evidence"`. Do NOT mutate the existing rejection.
- [x] When `_cluster_context_changed` returns false, skip entirely — return the existing rejected suggestion unchanged.
- [x] Query for max `evidence_generation` for the `(identity_id, cluster_id)` pair to determine next generation number.
- [x] Original rejection remains immutable — visible in audit trail. Both rows coexist under widened unique constraint.
- [x] Add deterministic tests for: new-evidence created, skip-when-context-unchanged, generation-increment-correctness, rapid-reject-then-context-change (no artificial delay).

## Phase 4: Frontend UX

> **Status: Already complete for low-confidence styling.**
>
> - `SuggestionReviewPanel.tsx` line 75: `isLowConfidence` detection using `LOW_CONFIDENCE_THRESHOLD = 0.6`
> - `SuggestionReviewPanel.tsx` line 100: `acx-suggestion-card--low-confidence` class application
> - `SuggestionReviewPanel.tsx` line 167: caution indicator rendering
> - `_workbench.scss` line 610: `--low-confidence` modifier styling
> - `SuggestionReviewPanel.test.tsx` line 453: test coverage

- [x] Surface low-confidence CTA state in top-cluster cards with explicit visual cue.
- [x] Add panel tests for low-confidence rendering.
- [x] Add automated test coverage ensuring no batch-wide side effects when accepting/rejecting a single suggestion card.
- [ ] (Optional) Add "new evidence" badge for suggestions with `source=backfill_new_evidence` to distinguish from first-time suggestions — deferred until Phase 3 backend is complete.

## Phase 5: Verification

- [x] Run targeted backend tests for inference and backfill slices.
- [x] Add automated regression test proving post-batch cards produce suggestion CTAs for known labels.
- [x] Verify no regression in existing label-time surfacing flow.

## Stretch Goals

- [ ] Add optional admin control for low-confidence floor offset in non-production environments.
- [ ] Add telemetry counters for "would-have-been-missed" suggestions to measure improvement.
- [ ] Add frontend "new evidence" badge/indicator for re-surfaced suggestions (depends on Phase 3 completion).

## Success Criteria

- [x] Newly created unlabeled clusters from later batches can surface suggestions to already confirmed labels without relabeling triggers.
- [x] Clusters with null `representative_identity_id` still receive inferred top-card suggestions when representative/member embeddings are available.
- [x] Previously rejected suggestions are never mutated by the backend — new evidence is surfaced as a distinct proposal.
- [x] Automated tests cover the reported Sable/Sable/Jen-style scenarios as suggestion CTAs (including low-confidence where applicable) instead of persistent "Name this person".
