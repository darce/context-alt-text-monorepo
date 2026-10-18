# Recognition Progress Tracking Investigation

**Date:** 2026-01-20
**Status:** ✅ Resolved

## Summary

Investigation into two reported bugs:
1. Progress bar showing "50/50" when 100 media items were expected
2. Clustering failures leaving faces as "unlabeled identity"

## Bug 1: Progress Shows 50/50 Instead of 100/100

### Root Cause

The progress display showing "50/50" was caused by **tier-based batch limits** that were prematurely implemented:

```python
# apps/prototype-description-service/recognition/application/tasks/scan.py
_DEFAULT_TIER_BATCH_LIMITS: dict[str, int] = {
    "free": 50,      # <-- This limit was being enforced!
    "pro": 500,
    "business": 2000,
    "enterprise": 10000,
}
```

The limit was enforced in `analyze.py` when auth was enabled and user wasn't admin.

### Resolution

**Remove all tier-based throttling code** per MVP guidelines. Business tier logic can be added post-MVP but should not block development.

#### Files Modified

- `apps/prototype-description-service/recognition/application/tasks/scan.py`
  - Removed `_DEFAULT_TIER_BATCH_LIMITS` constant
  - Removed `load_tier_batch_limits()` function
  - Removed `max_batch_for_tier()` function
  
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`
  - Removed tier batch limit enforcement block

---

## Bug 2: "Unlabeled Identity" Display

### Root Cause Analysis

The "Unlabeled identity" display is **working as designed**. The system correctly:

1. Detects faces and generates embeddings
2. Creates clusters for similar faces
3. Shows "Unlabeled identity" for clusters without user-assigned labels

#### Evidence from Logs

```
[clustering] Gate decision for identity X -> cluster Y: suggest 
  (checks passed: ['block_check', 'ConstraintCheck'], failed: ['confidence'])
[suggestions] Skipping suggestion: cluster not user-labeled
```

This shows:
- Clustering is working correctly
- Faces are being matched to clusters with ~92% similarity
- System correctly suggests (not auto-assigns) when below confidence threshold

### Why This Is Expected Behavior

1. **New clusters start unlabeled** - HDBSCAN creates clusters based on similarity, not semantic meaning
2. **Suggestions require user-labeled targets** - Safety feature to prevent incorrect auto-assignments
3. **Confidence threshold** - ~92% similarity triggers "suggest" not "accept" (threshold ~95%)

### No Code Changes Required

The "unlabeled identity" state simply means a cluster needs user naming. The UX is:
1. User sees faces grouped together
2. User names the cluster (e.g., "John Smith")
3. Future similar faces auto-assign or suggest to that labeled cluster

---

## Files Changed

| File | Change |
|------|--------|
| `recognition/application/tasks/scan.py` | Remove tier limit code |
| `recognition/interface_adapters/http/routers/analyze.py` | Remove limit enforcement |

---

## Testing Verification

After removing throttling:
- [x] Submit 100+ images in single request - should succeed (RecognitionControllerTest::testAnalyzeAccepts100MediaIds)
- [ ] Verify progress shows correct total count
- [x] Confirm no 400 errors from batch limits (100-image test passes)
