# Clustering Pipeline Diagnostic Report

## Critical Issues Found

### 1. [ISSUE] Maturity Check Blocks All Cold-Start Clustering

**Setting**: `min_representatives_for_maturity = 2`  
**Problem**: New clusters created during cold start have **only 1 representative**  
**Result**: ALL faces go to SUGGEST, nothing gets auto-accepted

```
[clustering] Gate decision: suggest (failed: ['maturity'])
[clustering] SUGGESTED ... reason=cluster not mature
```

**Fix**: Either:
- Lower `min_representatives_for_maturity` to 1 for cold start
- OR ensure new clusters get 2+ representatives via FPS selection

---

### 2. [ISSUE] `/clusters/create-for-identity` Endpoint Missing

**Frontend expects**: `POST /recognition/clusters/create-for-identity`  
**Backend has**: This endpoint exists in **archived** code only  
**Result**: 405 Method Not Allowed error

```
Request failed (405): {"detail":"Method Not Allowed"}
```

**Fix**: Port endpoint from archived router to current codebase

---

### 3. [ISSUE] `recompute_representatives()` Not Implemented

**Status**: Method doesn't exist on `AssignmentWriter`  
**Result**: Merges don't update representatives, causing Muted Yarrow issue

---

### 4. [WARN] Default UUID Clusters Suggested to User

**Problem**: Suggestions include clusters with UUID labels (e.g., `901afe40-...`)  
**Expected**: Only user-labeled clusters should be suggested

---

### 5. [WARN] Chunking Implemented But Not Helping

**Current behavior**: 5-image chunks during cold start [x]  
**Problem**: New chunks create new singleton clusters instead of matching existing  
**Root cause**: Maturity check blocks all matches, so nothing gets assigned

---

## Root Cause Summary

The **maturity check is too strict for cold start**:

1. Chunk 1: 5 faces -> 5 singleton clusters (1 rep each)
2. Chunk 2: 5 faces -> fail maturity check (need 2 reps) -> SUGGEST
3. Chunk 3-N: Same pattern, nothing ever matures

**The chunking fix is correct, but maturity threshold defeats it.**

---

## Recommended Fixes (Priority Order)

1. **Bypass maturity for anchor-linked candidates** (already partially done)
2. **Ensure new clusters get 2+ reps** via FPS from initial members
3. **Add missing `/create-for-identity` endpoint**
4. **Filter suggestions to user-labeled clusters only**
5. **Implement `recompute_representatives()`**
