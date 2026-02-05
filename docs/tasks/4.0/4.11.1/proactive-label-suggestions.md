# Proactive Label Suggestions for Unlabeled Clusters

**Date:** 2026-01-26  
**Status:** Planning  
**Goal:** Surface label suggestions directly in the UI with confirm/reject actions while keeping unlabeled clusters understandable and actionable.

---

## Problem Statement

Two separate issues combine to block useful suggestions:

1. **Visibility**: Suggestions for unlabeled clusters are filtered out in the backend list endpoint, so the UI receives zero items.
2. **Meaningfulness**: Even if suggestions appear, unlabeled clusters are unclear (“who is this?”), and acceptance requires extra clicks to label.

**Desired behavior:**

- Suggestions should be visible even when clusters are unlabeled.
- Users should understand who the cluster represents before confirming.
- Users can accept/reject quickly, and can recalibrate by removing incorrect identities.
- Users can label the cluster collectively in a focused UI.

---

## Constraints

- **Do not use filename/metadata** as a label source. It is unreliable unless EXIF is present, and EXIF support is **out of scope for MVP**.
- Merging into unlabeled clusters **is allowed**, but the cluster must be clearly legible (face grid + provenance) and correctable.

## Copy + CTA Evaluation

We need consistent copy that preserves trust. We will **not** show “Add to this cluster?” in suggestions.

### Options

1. **“Is this {label}?”**
   - Only when the label is reliable (manual label or inference with provenance).
   - High clarity and confidence.
   - Risky if label is guessed without attribution.

2. **“Name this person”**
   - Best as a **labeling CTA** for a face-grid (cluster-level UI).
   - Not a replacement for suggestion acceptance.

### Recommendation (Rule-Based Copy)

- If **label exists or is inferred with provenance**, show: **“Is this {label}?”** with Yes/No actions.
- If **no reliable label**, do **not** show accept/reject. Show **“Name this person”** on the face-grid and open the cluster labeling UI.

**We cannot claim engagement gains without data.** Treat copy effectiveness as a hypothesis to validate.

---

## Label Source Priority (MVP)

Use only reliable sources:

1. **Matched identity name** (if suggestion links to a known identity)
2. **Roster entry name** (if identity links to roster)
3. **Most similar labeled cluster** (with explicit provenance: “inferred from {label}”)
4. **None** → show “Name this person” CTA only (no accept/reject until labeled)

**Excluded:** filename/metadata (unreliable without EXIF; out of MVP scope)

---

## UX Requirements (Must-Have)

### 1) Cluster Legibility

- Always show a **face grid** preview for the target cluster in suggestions.
- Show **label provenance** when inferred (roster/nearest labeled cluster).

### 2) Cluster Review UI (Required)

Users must be able to:

- See the full collection of faces in a cluster
- Remove identities that don’t belong
- Trigger similarity **recalibration** after removals

### 3) Collective Cluster Labeling UI (Required)

- Present a focused “label this cluster” view
- Show representative face + grid + count
- Allow user to apply a name in one place
- On save: update cluster label, mark user_confirmed, refresh suggestions

---

## Backend Changes

### Remove Label Filter

**File:** `recognition/infrastructure/repositories/suggestion_repository.py`

Remove the label-only filters in `list_pending_with_details()` so unlabeled clusters are returned.

### Extend API Response

Add fields to expose a suggested label and provenance:

```python
SuggestedLabelSource = Literal["identity", "roster", "similar_cluster", "none"]

class ClusterResponse(BaseModel):
    id: str
    label: str | None
    is_labeled: bool
    identity_count: int
    suggested_label: str | None = None
    suggested_label_source: SuggestedLabelSource | None = None
    suggested_label_confidence: float | None = None

class SuggestionResponse(BaseModel):
    id: str
    identity_id: str
    cluster_id: str
    rep_similarity: float
    member_similarity: float | None
    status: Literal["pending", "accepted", "rejected"]
    cluster_label: str | None = None
    suggested_label: str | None = None
    suggested_label_source: SuggestedLabelSource | None = None
    suggested_label_confidence: float | None = None
```

Use flat `suggested_label*` fields (no nested object) to match existing contract patterns.

### Label Suggestion Logic

Compute once per cluster, using the priority list above. If no reliable source exists, return `None` and the UI shows **“Name this person”** (no accept/reject until labeled).

Implementation details (MVP):
- Compute `suggested_label` inline during `list_pending_with_details()` (no caching).
- For `similar_cluster`: reuse merge suggestions and pick the highest-similarity pending match where the *other* cluster is labeled; accept only if `similarity >= ClusteringSettings.suggestion_floor` (currently `0.45`).
- Use `ClusteringSettings.suggestion_floor` as the minimum confidence for any inferred label.
- Do not persist label-rejection state for MVP; rejected suggestions disappear via existing pending-status filtering.
- Update the `list_pending_with_details()` docstring in `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py` to reflect unlabeled clusters with suggested-label inference.

---

## Frontend Changes

### Suggestion Copy Rules

```tsx
// Preferred copy logic
if (label || inferredLabel) {
  prompt = `Is this ${label || inferredLabel}?`;
  badge = inferredLabel ? labelSourceBadge : null;
  showActions = true;
} else {
  prompt = "Name this person";
  showActions = false;
}
```

### Suggestion UI Requirements

- Face grid preview (not just a label)
- Inference badge when label is inferred
- “Review cluster” action opens cluster review UI
- “Name this person” CTA opens collective labeling UI

---

## Interaction With Existing Features

- **Suggestions Panel** still lists suggestions, but now includes unlabeled clusters.
- **Merge suggestions** remain separate, but may coexist with label suggestions.
- **Manual label edit** still works and overrides suggestions.

---

## Implementation Plan (Augmented)

### Backend: Functions/Modules to Modify

- `recognition/infrastructure/repositories/suggestion_repository.py`
  - `list_pending_with_details()` — remove label-only filters.
- `recognition/application/suggestions/refresh_service.py`
  - `surface_for_newly_labeled_cluster()` — ensure it’s invoked after labeling and after identity removals.
- `recognition/application/orchestration/cluster_service.py`
  - `update_cluster()` — must mark `user_confirmed` and trigger suggestion refresh/surface.
  - `remove_identity_from_cluster()` — after removal, recompute centroid and refresh suggestions.
- `recognition/interface_adapters/http/routers/clusters.py`
  - Add/extend endpoints for cluster labeling (“name this person”) and label rejection tracking if needed.

### Frontend: Functions/Components to Modify

- `js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx`
  - Apply new copy rules and hide accept/reject when label is missing.
- `js/admin/pages/workbench/identity-clusters/*`
  - Add “Name this person” CTA and “Review cluster” UI entry point.
- Cluster review UI (new component)
  - Face grid, identity removal actions, and recalibration triggers.

### Patterns to Follow (From instructions.md)

- **Scaffold first**: add signatures + docstrings + test stubs before implementation.
- **Baseline migration only** for schema changes (update `001_identity_schema.py`).
- **Delete-over-flag**: do not add feature flags for this flow.
- **Deterministic tests**: no randomness/time without seams.
- **Contracts first**: update shared schemas in `docs/agentic/contracts/` before endpoints.

### New Tables (If Needed)

If we must persist rejections to avoid re-suggesting the same name (Phase 5, not MVP), add a lightweight table. For MVP, rely on existing suggestion status so rejected items drop out of pending lists.

`cluster_label_suggestion_rejections` (new)

- `id` (UUID PK)
- `tenant_id` (FK)
- `cluster_id` (FK)
- `label` (text)
- `source` (enum/text: identity | roster | similar_cluster)
- `rejected_at` (timestamp)
- Unique constraint on (`cluster_id`, `label`, `source`)

## Cross-Layer Contracts (Required)

- `docs/agentic/contracts/recognition-clustering.md` — document `ClusterResponse` + `SuggestionResponse` additions for suggested labels/provenance.
- `docs/agentic/contracts/clustering-api.md` — mirror the same fields for the WP proxy response examples.

## Related Files

| Area                  | Path                                                                                                                | Purpose                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Backend API schema    | `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py`                       | Add suggested label fields to `ClusterResponse` + `SuggestionResponse`.       |
| Backend domain model  | `apps/prototype-description-service/recognition/domain/suggestion.py`                                               | Extend `SuggestionDetails` (and add `SuggestedLabel` data structure).         |
| Suggestion mapping    | `apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py`                     | Populate suggested label fields in `_to_response_with_details()`.             |
| Suggestion query      | `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py`               | Remove label-only filter in `list_pending_with_details()`.                    |
| Suggestion refresh    | `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py`                         | Surface suggestions after labeling/removal.                                   |
| Cluster orchestration | `apps/prototype-description-service/recognition/application/orchestration/cluster_service.py`                       | Ensure `update_cluster()` + `remove_identity_from_cluster()` trigger refresh. |
| Cluster router        | `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py`                        | Cluster labeling/review endpoints.                                            |
| Schema baseline       | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`                                  | Add rejection table if needed.                                                |
| Frontend API types    | `apps/prototype-wp-alt-context/js/admin/api/recognition/types/suggestion.ts`                                        | Add suggested label fields to `PendingSuggestion`.                            |
| UI panel              | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx`                | Copy rules + CTA gating.                                                      |
| UI entry points       | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/`                                         | New cluster review + labeling components.                                     |
| Frontend tests        | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx` | Copy rule coverage + CTA visibility.                                          |

## Scaffolding Definition of Done

A scaffold is complete only when:

- Signatures are present with full type hints and docstrings (Args/Returns/Raises) in the listed files.
- Python scaffolds contain only `raise NotImplementedError("TODO: ...")`.
- Frontend stubs compile with typed props and placeholder returns.
- `PYENV_VERSION=description-service mypy .` from `apps/prototype-description-service/` (or `PYENV_VERSION=description-service mypy --config-file apps/prototype-description-service/pyproject.toml apps/prototype-description-service` from repo root) and `npm run typecheck` in `apps/prototype-wp-alt-context` both pass.
- Test stubs exist with `@pytest.mark.skip("scaffold")` and `it.todo("scaffold: ...")`.

## Verification Steps

1. Reset DB
2. Scan → identities created
3. Clustering → unlabeled clusters + suggestions created
4. UI shows suggestions with face grid
5. Accept/reject works without extra label clicks
6. Cluster review removes identities and recalibrates suggestions
7. Cluster labeling UI sets label + refreshes suggestions

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Backend schema scaffolds: add `SuggestedLabel` + `SuggestedLabelSource` in `apps/prototype-description-service/recognition/domain/suggestion.py`, and add suggested label fields to `ClusterResponse` + `SuggestionResponse` in `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py` (with placeholder mapping in `apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py`).
- [x] Backend inference scaffold: create `apps/prototype-description-service/recognition/application/suggestions/label_inference.py` with `async def infer_suggested_label(tenant_id: str, cluster_id: str, *, session: AsyncSession) -> SuggestedLabel | None` and `raise NotImplementedError("TODO: infer label + provenance")`.
- [x] Frontend scaffolds: extend `apps/prototype-wp-alt-context/js/admin/api/recognition/types/suggestion.ts` (`PendingSuggestion`) with `suggested_label`, `suggested_label_source`, `suggested_label_confidence`, and add stub components in `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx` + `ClusterLabelingPanel.tsx`.
- [x] Scaffolding verification + tests: add `@pytest.mark.skip("scaffold")` tests in `apps/prototype-description-service/recognition/tests/api/test_api_suggestions.py` and `it.todo("scaffold: ...")` in `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx`; run `PYENV_VERSION=description-service mypy .` from `apps/prototype-description-service/` (or `PYENV_VERSION=description-service mypy --config-file apps/prototype-description-service/pyproject.toml apps/prototype-description-service` from repo root) and `npm run typecheck` in `apps/prototype-wp-alt-context`.

## Phase 1: Backend

- [x] Remove label filter in `list_pending_with_details()`
- [x] Implement label inference (identity → roster → similar cluster)
- [x] Return `suggested_label`, `suggested_label_source`, `suggested_label_confidence`

## Phase 2: Frontend

- [x] Implement rule-based copy (“Is this {label}?” only when label exists; otherwise “Name this person”)
- [x] Add provenance badges for inferred labels
- [x] Show face-grid preview in suggestions
- [x] Add “Review cluster” + “Name this person” CTAs

## Phase 3: Cluster Review + Labeling

- [x] Implement cluster review UI with identity removal
- [x] Trigger recompute + suggestion refresh after removals
- [x] Implement collective cluster labeling UI

## Phase 4: Tests

- [x] Integration: unlabeled clusters returned by API
- [x] Integration: removal triggers suggestion refresh
- [x] Frontend: copy rules render correctly
- [x] Frontend: cluster review removes identities

## Success Criteria

- [x] Suggestions visible without prior manual labeling
- [x] Users understand cluster identity before confirming
- [x] Unlabeled merges are clear and reversible
- [x] Cluster review + labeling recalibrates suggestions

