# Early Stage Suggestion Guard

**Status**: Backend Complete, Frontend Pending  
**Sprint**: 4.2.3  
**Created**: 2024-11-28  
**Branch**: `subfeature/4.2.3.1-suggestion-guard`

## Problem Statement

During early stage training (< 30 labeled clusters), the system makes clustering decisions with insufficient data, leading to:

1. **False Positives**: Different people merged into same cluster (e.g., wrong face added to "Cobalt Verity" at 81% match)
2. **False Negatives**: Same person split across clusters (e.g., Muted Yarrow split at 71% direct similarity, 85.1% representative match)

### Root Cause

Early training has competing pressures:

- **Strict thresholds** (0.85) prevent false positives but create many singletons
- **Borderline matches** (0.76-0.85) are uncertain - could be same person or different
- **Auto-merge decisions** are irreversible and contaminate clusters when wrong

## Proposed Solution

### Core Principle

> **During early training, borderline matches become suggestions rather than auto-decisions.**

Instead of the system deciding whether to merge or reject borderline matches, surface them to the user for confirmation. This applies to ALL qualifying cluster matches, regardless of label status.

### Decision Matrix

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Match Score              │  Early Stage (<30)      │  Mature Stage (≥30)   │
├───────────────────────────┼─────────────────────────┼───────────────────────┤
│  ≥ high_confidence (0.90) │  Auto-assign            │  Auto-assign          │
│  borderline (0.76-0.89)   │  CREATE SUGGESTION      │  Auto-assign          │
│  < threshold (0.76)       │  Create singleton       │  Create singleton     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Suggestions apply to any cluster match** - Labels are orthogonal to clustering accuracy
2. **Labels applied post-merge** - User labels after confirming/rejecting suggestion
3. **Existing `identity_suggestions` table** - Already in schema, ready to use
4. **Gradual relaxation** - As system matures, auto-assign more, suggest less

## Implementation Plan

### Phase 1: Backend - Suggestion Creation Logic

**File**: `recognition/application/clustering/identity_clustering_service.py`

#### Task 1.1: Add early-stage suggestion logic to RepresentativeMatcher

```python
# In RepresentativeMatcher._try_match_to_cluster()
async def _try_match_to_cluster(self, identity, cluster, representatives):
    best_sim = compute_best_representative_similarity(identity, representatives)

    # Get training stage
    labeled_count = await self._count_labeled_clusters()
    is_early_stage = labeled_count < self.settings.adaptive_threshold_maturity_point

    # High confidence threshold for auto-assign during early stage
    high_confidence_threshold = 0.90

    if is_early_stage and self.threshold <= best_sim < high_confidence_threshold:
        # Borderline during early stage → suggest instead of auto-assign
        await self._create_suggestion(
            identity_id=identity.id,
            suggested_cluster_id=cluster.id,
            representative_similarity=best_sim,
        )
        return None  # Don't assign, leave as singleton for now

    if best_sim >= self.threshold:
        return cluster  # Auto-assign (mature stage or high confidence)

    return None  # Below threshold
```

#### Task 1.2: Add settings for early-stage suggestion behavior

**File**: `recognition/application/clustering/clustering_settings.py`

```python
# === Early Stage Suggestion Guard ===
early_stage_suggestion_enabled: bool = True  # Create suggestions for borderline matches during early training
early_stage_high_confidence: float = 0.90    # Threshold for auto-assign even during early stage
early_stage_maturity_point: int = 30         # Number of labeled clusters to exit early stage
```

#### Task 1.3: Implement suggestion creation

**File**: `recognition/application/clustering/identity_clustering_service.py`

```python
async def _create_suggestion(
    self,
    identity_id: UUID,
    suggested_cluster_id: UUID,
    representative_similarity: float,
    avg_member_similarity: float | None = None,
) -> None:
    """Create a pending suggestion for user confirmation."""
    suggestion = IdentitySuggestion(
        id=uuid4(),
        tenant_id=self.tenant_id,
        identity_id=identity_id,
        suggested_cluster_id=suggested_cluster_id,
        representative_similarity=representative_similarity,
        avg_member_similarity=avg_member_similarity or representative_similarity,
        confidence_score=representative_similarity,  # Can be refined later
        resolution="pending",
    )
    self.session.add(suggestion)
```

### Phase 2: Backend - Suggestion Resolution Endpoints

**File**: `recognition/interface_adapters/http/recognition_router.py`

#### Task 2.1: List pending suggestions

```python
@router.get("/suggestions", response_model=list[SuggestionResponse])
async def list_pending_suggestions(
    tenant_id: UUID,
    limit: int = Query(default=20, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[SuggestionResponse]:
    """Get pending suggestions for user review, ordered by confidence."""
```

#### Task 2.2: Accept suggestion (merge)

```python
@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Accept suggestion: assign identity to suggested cluster."""
    # 1. Load suggestion
    # 2. Assign identity to cluster
    # 3. Add representative if high quality
    # 4. Update suggestion.resolution = 'accepted'
    # 5. Update suggestion.resolved_at = now()
```

#### Task 2.3: Reject suggestion (keep separate)

```python
@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Reject suggestion: identity stays in its current cluster/singleton."""
    # 1. Load suggestion
    # 2. Update suggestion.resolution = 'rejected'
    # 3. Update suggestion.resolved_at = now()
    # 4. Optionally: create explicit "not same person" record for future learning
```

### Phase 3: Frontend - Suggestion Review UI

**File**: `js/admin/pages/workbench/SuggestionPanel.tsx`

#### Task 3.1: Create SuggestionPanel component

```tsx
interface SuggestionPanelProps {
  tenantId: string;
}

export function SuggestionPanel({ tenantId }: SuggestionPanelProps) {
  const { data: suggestions, isLoading } = useSuggestions(tenantId);

  if (!suggestions?.length) return null;

  return (
    <div className="acx-suggestion-panel">
      <h3>Pending Matches ({suggestions.length})</h3>
      {suggestions.map((s) => (
        <SuggestionCard key={s.id} suggestion={s} />
      ))}
    </div>
  );
}
```

#### Task 3.2: Create SuggestionCard component

```tsx
function SuggestionCard({ suggestion }: { suggestion: Suggestion }) {
  const acceptMutation = useAcceptSuggestion();
  const rejectMutation = useRejectSuggestion();

  return (
    <div className="acx-suggestion-card">
      <div className="acx-suggestion-card__thumbnails">
        <img src={suggestion.identity_thumbnail} alt="New face" />
        <span className="acx-suggestion-card__arrow">→</span>
        <img src={suggestion.cluster_thumbnail} alt="Existing cluster" />
      </div>
      <div className="acx-suggestion-card__info">
        <span className="acx-suggestion-card__score">
          {(suggestion.representative_similarity * 100).toFixed(0)}% match
        </span>
        <span className="acx-suggestion-card__cluster">
          {suggestion.cluster_label ||
            `Cluster ${suggestion.suggested_cluster_id.slice(0, 8)}`}
        </span>
      </div>
      <div className="acx-suggestion-card__actions">
        <button onClick={() => acceptMutation.mutate(suggestion.id)}>
          ✓ Same Person
        </button>
        <button onClick={() => rejectMutation.mutate(suggestion.id)}>
          ✗ Different
        </button>
      </div>
    </div>
  );
}
```

#### Task 3.3: Add hooks and API

**File**: `js/admin/hooks/useRecognitionHooks.ts`

```typescript
export function useSuggestions(tenantId: string) {
  return useQuery({
    queryKey: ["suggestions", tenantId],
    queryFn: () => fetchSuggestions(tenantId),
  });
}

export function useAcceptSuggestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (suggestionId: string) => acceptSuggestion(suggestionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suggestions"] });
      queryClient.invalidateQueries({ queryKey: ["clusters"] });
    },
  });
}
```

### Phase 4: Integration & Polish

#### Task 4.1: Add suggestion count to training stage banner

Update `TrainingStageBanner.tsx` to show pending suggestion count:

```tsx
<div className="acx-training-stage-banner__suggestions">
  {suggestionCount > 0 && (
    <span className="acx-training-stage-banner__badge">
      {suggestionCount} pending review
    </span>
  )}
</div>
```

#### Task 4.2: Expire stale suggestions

When a cluster is deleted or identity is reassigned, mark related suggestions as 'expired':

```python
async def expire_suggestions_for_cluster(cluster_id: UUID):
    await session.execute(
        update(IdentitySuggestion)
        .where(IdentitySuggestion.suggested_cluster_id == cluster_id)
        .where(IdentitySuggestion.resolution == 'pending')
        .values(resolution='expired', resolved_at=func.now())
    )
```

#### Task 4.3: Tests

- `test_early_stage_creates_suggestion_for_borderline_match`
- `test_mature_stage_auto_assigns_borderline_match`
- `test_high_confidence_auto_assigns_even_in_early_stage`
- `test_accept_suggestion_merges_identity_to_cluster`
- `test_reject_suggestion_keeps_identity_separate`
- `test_cluster_deletion_expires_pending_suggestions`

## Success Criteria

1. **No more false positives to labeled clusters** - Borderline matches require confirmation
2. **Reduced false negatives** - User sees suggested matches they would have missed
3. **Training signal** - Accept/reject patterns inform threshold tuning
4. **Clean UX** - Suggestions surfaced prominently, easy to resolve

## Future Enhancements

1. **Batch accept/reject** - Handle multiple suggestions at once
2. **Learning from rejections** - Use rejection patterns to improve thresholds
3. **Cluster merge suggestions** - Suggest merging two existing clusters that are similar
4. **Confidence calibration** - Adjust confidence_score based on detection quality metrics

## Related Files

- `db/models.py` - `IdentitySuggestion` model (already exists)
- `db/migrations/versions/001_identity_schema.py` - `identity_suggestions` table (already exists)
- `recognition/application/clustering/clustering_settings.py` - Add new settings
- `recognition/application/clustering/identity_clustering_service.py` - Core logic changes
- `recognition/interface_adapters/http/recognition_router.py` - New endpoints
- `js/admin/pages/workbench/` - New UI components
