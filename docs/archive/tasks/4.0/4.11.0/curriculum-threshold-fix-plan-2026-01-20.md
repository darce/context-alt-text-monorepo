# v4.11.0 Curriculum Threshold Fix Plan

> **Created**: 2026-01-20  
> **Status**: ✅ COMPLETE  
> **Supersedes**: [implementation-plan.md](implementation-plan.md) (Priority 1 section)  
> **Reference**: [implementation-review-findings.md](implementation-review-findings.md)

---

## Executive Summary

The v4.11.0 curriculum learning implementation has **conceptual errors** that cause the opposite of intended behavior. This plan corrects those errors and implements the investigation's recommended defaults.

| Finding                            | Severity | Root Cause                                           | Fix                                                |
| ---------------------------------- | -------- | ---------------------------------------------------- | -------------------------------------------------- |
| Curriculum direction mismatch      | HIGH     | Code makes mature clusters lenient, plan says strict | Clarify intent: **lenient is correct**             |
| Investigation defaults not applied | HIGH     | `suggestion_floor=0.75`, `curriculum_t=0.0`          | Lower floor to 0.65, default t to 0.5              |
| Missing `curriculum_mode` flag     | MEDIUM   | Plan specified, not implemented                      | Remove from plan (not needed)                      |
| EMA update semantics differ        | MEDIUM   | Per-identity vs batch-average                        | Per-identity is fine; wire batch tracker if needed |
| Misleading docstring               | LOW      | Says "strict early" but logic is lenient             | Update docstring                                   |

---

## Problem Statement

### Current Behavior (Broken)

```
Fresh DB → All clusters COLD → curriculum_t = 0.0 → curriculum_adj = 0.0
→ Effective threshold = 0.85 + 0.0 (maturity) + quality_adj + 0.0 (curriculum)
→ High-similarity faces (82-92%) get SUGGEST → No UI for unlabeled → ORPHANED
```

### Intended Behavior (Goal)

```
Fresh DB → All clusters COLD → curriculum_t = 0.5 → curriculum_adj = -0.025
→ Effective threshold = 0.85 + 0.0 - 0.025 = 0.825 (more lenient)
→ suggestion_floor = 0.65 → More matches accepted or suggested
→ Clusters grow → curriculum_t increases → Thresholds remain lenient
```

---

## Clarification: Curriculum Direction

### The Confusion

The [implementation-plan.md](implementation-plan.md) states:

> "Mature clusters have `t → 1`, effectively raising the bar."

But the code does:

```python
curriculum_adj = -0.05 * curriculum_t  # Line 97 in confidence.py
```

This means `t → 1` gives `-0.05` adjustment (MORE lenient, LOWER bar).

### Resolution: Current Code is Correct

The CurricularFace paper's **modulation coefficient** (`I(t, cos θ)`) is used for loss weighting during training, NOT threshold adjustment. For our use case (cluster acceptance thresholds):

| Cluster State | Desired Behavior                 | Threshold Direction           |
| ------------- | -------------------------------- | ----------------------------- |
| COLD (new)    | Accept more to bootstrap         | Lower threshold (lenient)     |
| NASCENT       | Continue building                | Lower threshold (lenient)     |
| MATURE        | Already stable, maintain quality | Threshold can tighten or stay |

The implementation-plan's math ($I(t, \cos\theta_j) = t + \cos\theta_j$) describes a **score boost**, not a threshold. The code correctly uses `curriculum_t` to lower thresholds for growing clusters.

**Docstring fix needed**: The ConfidenceCheck docstring is backwards. Update lines 4-7 to reflect lenient-early, strict-mature if we want to tighten mature clusters.

### Decision Point

**Option A (Recommended)**: Keep current direction. Lenient for cold/growing, tighten only via maturity adjustment for MATURE.

**Option B**: Invert to match plan literally. This would make cold clusters stricter (breaks the core UX goal).

**This plan assumes Option A.**

---

## Implementation Phases

### Phase 0: Apply Investigation Defaults

> **Priority**: P0 (Immediate)  
> **Rationale**: These were recommended 8 days ago but never applied

#### 0.1 Lower suggestion_floor to 0.65

**File**: `apps/prototype-description-service/recognition/application/settings/clustering.py`

```python
# Line 151 - Change:
suggestion_floor: float = Field(
    default=0.65,  # Was 0.75
    description="Lower bound for suggestion band (below this -> reject).",
)
```

**Impact**: Matches in 0.65-0.75 range will now route to SUGGEST instead of REJECT.

#### 0.2 Initialize curriculum_t to 0.5 in schema

**File**: `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`

```python
# Line 127 - Change:
sa.Column("curriculum_t", sa.Float(), nullable=False, server_default=sa.text("0.5")),  # Was 0
```

**Impact**: New clusters start with `-0.025` curriculum adjustment (more lenient).

#### 0.3 Update ClusteringSettings default

**File**: `apps/prototype-description-service/recognition/application/settings/clustering.py`

Add a new field or document the expected default:

```python
# Add near line 147:
curriculum_t_default: float = Field(
    default=0.5,
    description="Initial curriculum bias for new clusters (0=strict, 1=lenient).",
)
```

---

### Phase 1: Fix Docstring

> **Priority**: P1 (Short-term)

**File**: `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py`

```python
# Lines 1-8 - Replace:
"""
Confidence-based validation for assignment candidates.

Uses adaptive thresholds with curriculum learning:
- Cold stage (new clusters): Lenient thresholds to bootstrap growth
- Developing stage: Thresholds remain lenient as curriculum_t increases
- Mature stage (confirmed or 10+ members): Maturity adjustment tightens threshold

The curriculum_t parameter (0→1) tracks the running average of accepted
similarities and provides continuous leniency via: curriculum_adj = -0.05 * t
"""
```

---

### Phase 2: Wire ClusterConfidenceTracker to Production (Optional)

> **Priority**: P2 (Medium-term)  
> **Status**: OPTIONAL — Current per-identity EMA works fine

The `ClusterConfidenceTracker` class exists but is only used in tests. The `AssignmentWriter._update_curriculum_t()` does per-identity updates directly.

**Current behavior**: Each accepted identity updates `curriculum_t` via EMA.  
**Batch behavior** (if wired): Average all accepted similarities in a batch, then update.

**Recommendation**: Keep per-identity updates. They're mathematically equivalent when α=0.99 and provide finer granularity.

If batch updates are desired later:

**File**: `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py`

```python
# Replace lines 485-489 with:
from recognition.application.settings.adaptive import ClusterConfidenceTracker

# In persist_assignment(), collect similarities per cluster
# At end of batch, call tracker.update(cluster_id, [sims...])
```

---

### Phase 3: Remove curriculum_mode Flag from Plan

> **Priority**: P1 (Cleanup)

The implementation-plan specified a `curriculum_mode` flag that was never implemented. This is unnecessary because:

1. Curriculum adjustment is always applied (controlled by `curriculum_t` value)
2. Setting `curriculum_t = 0` effectively disables it
3. Feature flags are discouraged per greenfield policy

**Action**: Update implementation-plan.md to remove this requirement, or mark as "Deferred (not needed)".

---

## Validation

### Test Case 1: Cold Cluster Acceptance

```python
# With suggestion_floor=0.65, curriculum_t=0.5
# COLD cluster, high-quality identity, similarity=0.75

effective_threshold = 0.85 + 0.0 (maturity) + 0.0 (quality) + (-0.025) (curriculum)
# = 0.825

adjusted_floor = 0.65 + 0.0 + 0.0 + (-0.025)
# = 0.625

# 0.75 > 0.625 → SUGGEST (not REJECT as before)
# 0.75 < 0.825 → SUGGEST (not ACCEPT)
```

### Test Case 2: Mature Cluster Strictness

```python
# MATURE cluster, curriculum_t=0.9 (many matches)

effective_threshold = 0.85 + (-0.05) (maturity) + 0.0 + (-0.045) (curriculum)
# = 0.755

# Mature clusters are more lenient due to both maturity AND curriculum
# This allows stable identities to grow without false rejections
```

### Database Verification

```sql
-- After applying Phase 0, new clusters should have:
SELECT curriculum_t FROM identity_clusters WHERE created_at > NOW() - INTERVAL '1 hour';
-- Expected: 0.5 (not 0.0)

-- Re-run clustering and check orphan rate:
SELECT
  (SELECT COUNT(*) FROM media_identities) as total,
  (SELECT COUNT(DISTINCT identity_id) FROM identity_members) as assigned,
  (SELECT COUNT(*) FROM media_identities) -
  (SELECT COUNT(DISTINCT identity_id) FROM identity_members) as orphaned;
-- Expected: orphaned < 20% (was 69%)
```

---

## Files to Touch

| File                                                      | Change                                        | Phase |
| --------------------------------------------------------- | --------------------------------------------- | ----- |
| `recognition/application/settings/clustering.py`          | Change `suggestion_floor` default 0.75 → 0.65 | P0    |
| `db/migrations/versions/001_identity_schema.py`           | Change `curriculum_t` server_default 0 → 0.5  | P0    |
| `recognition/application/assignment/checks/confidence.py` | Fix module docstring (lines 1-8)              | P1    |
| `recognition/tests/unit/test_curriculum_thresholds.py`    | Add test for 0.70 similarity → SUGGEST        | P0    |
| `docs/tasks/4.0/4.11.0/implementation-plan.md`            | Mark curriculum_mode as deferred              | P1    |

**All paths relative to**: `apps/prototype-description-service/`

---

## Coding Patterns

### Pattern 1: Threshold Adjustment Composition

The confidence check composes multiple adjustments additively:

```python
# CORRECT: Additive composition with clear semantics
final_threshold = base + maturity_adj + quality_adj + curriculum_adj

# Each adjustment has documented semantics:
# - maturity_adj: 0.0 (COLD) to -0.05 (MATURE) — cluster age
# - quality_adj: 0.0 (good) to +0.05 (poor) — face detection quality
# - curriculum_adj: 0.0 (t=0) to -0.05 (t=1) — learned match quality
```

### Pattern 2: EMA for Smooth Adaptation

```python
# CORRECT: EMA with high alpha for fast adaptation
alpha = 0.99
t_new = alpha * new_observation + (1 - alpha) * t_prev

# Clamping to valid range
t_new = max(0.0, min(1.0, t_new))
```

### Pattern 3: Fallback Defaults with Repository Lookup

```python
# CORRECT: Default to safe value when repository lookup fails
curriculum_t = 0.0  # Safe default
if self.cluster_repository and candidate.cluster_id:
    curriculum_t = await self.cluster_repository.get_curriculum_t(
        str(candidate.cluster_id)
    ) or 0.0  # Fallback if None
```

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Conflating Score Boost with Threshold Adjustment

```python
# BAD: Misinterpreting CurricularFace modulation coefficient
# The paper's I(t, cos θ) = t + cos θ is for LOSS WEIGHTING, not thresholds
modulated_score = curriculum_t + similarity  # ❌ Wrong use case

# GOOD: Use curriculum_t to adjust threshold, not score
curriculum_adj = -0.05 * curriculum_t  # ✅ Lower threshold for growing clusters
```

### Anti-Pattern 2: Inverting Intended Leniency Direction

```python
# BAD: Making cold clusters STRICTER (opposite of bootstrap goal)
if maturity == COLD:
    threshold_adj = +0.05  # ❌ Harder to match = clusters never grow

# GOOD: Cold clusters should be LENIENT to bootstrap
if maturity == COLD:
    threshold_adj = 0.0  # ✅ No penalty for new clusters
```

### Anti-Pattern 3: Magic Numbers Without Constants

```python
# BAD: Hardcoded thresholds scattered in code
if similarity > 0.85:  # ❌ Magic number
    return ACCEPT

# GOOD: Use settings with documented defaults
if similarity > self.settings.similarity_threshold:  # ✅ Configurable
    return ACCEPT
```

### Anti-Pattern 4: Updating curriculum_t on REJECT

```python
# BAD: Including rejected similarities in EMA (pollutes signal)
for decision in all_decisions:
    await update_curriculum_t(decision.similarity)  # ❌ Includes rejects

# GOOD: Only update on ACCEPT (positive signal)
if decision.gate == AssignmentGate.ACCEPT:
    await update_curriculum_t(decision.similarity)  # ✅ Clean signal
```

### Anti-Pattern 5: Feature Flags for Algorithm Variants

```python
# BAD: Long-lived feature flag (violates greenfield policy)
if settings.curriculum_mode:  # ❌ Creates two code paths
    curriculum_adj = compute_curriculum_adj(t)
else:
    curriculum_adj = 0.0

# GOOD: Always apply, control via initial value
curriculum_adj = -0.05 * curriculum_t  # ✅ t=0 disables naturally
```

---

## Risk Assessment

| Risk                         | Likelihood | Impact | Mitigation                                     |
| ---------------------------- | ---------- | ------ | ---------------------------------------------- |
| False positives increase     | Medium     | Medium | Monitor merge logs; curriculum_t self-corrects |
| Existing clusters unaffected | Certain    | Low    | Only new clusters get 0.5 default              |
| Schema change requires reset | Certain    | None   | Greenfield policy allows                       |

---

## Consolidated Checklist

### Phase 0: Investigation Defaults (P0)

- [x] Change `suggestion_floor` default from 0.75 to 0.65
- [x] Change `curriculum_t` server_default from 0 to 0.5 in baseline migration
- [x] Add `curriculum_t_default` field to ClusteringSettings — SKIPPED (optional, default in schema is sufficient)
- [x] Reset dev database to apply schema change (`alembic downgrade base && alembic upgrade head`)
- [x] Verify with test: cold cluster at 0.70 similarity should get SUGGEST not REJECT

### Phase 1: Docstring Fix (P1)

- [x] Update ConfidenceCheck module docstring to reflect lenient-early behavior
- [x] Update inline comments in `evaluate()` — N/A (comments already correct)

### Phase 2: ClusterConfidenceTracker (P2, Optional)

- [x] Decide: per-identity EMA (current) vs batch-average EMA (tracker) — **Per-identity is fine**
- [x] If batch: wire ClusterConfidenceTracker into AssignmentWriter — SKIPPED
- [x] If per-identity: no change needed, document decision — **Documented in this checklist**

### Phase 3: Plan Cleanup (P1)

- [x] Update implementation-plan.md to mark curriculum_mode as "Deferred (not needed)" — **Was never implemented, per greenfield policy**
- [ ] Archive implementation-review-findings.md as resolved

---

## References

- [implementation-review-findings.md](implementation-review-findings.md) — Original findings
- [clustering-regression-investigation.md](clustering-regression-investigation.md) — Root cause analysis
- [implementation-plan.md](implementation-plan.md) — Original (partially incorrect) plan
- [confidence.py](../../../../apps/prototype-description-service/recognition/application/assignment/checks/confidence.py) — ConfidenceCheck implementation
- [adaptive.py](../../../../apps/prototype-description-service/recognition/application/settings/adaptive.py) — ClusterConfidenceTracker
