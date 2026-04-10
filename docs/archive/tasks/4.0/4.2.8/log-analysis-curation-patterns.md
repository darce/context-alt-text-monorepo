# Log Analysis: Curation Patterns and Suggestions Strategy Validation

**Date:** 2024-12-20  
**Source:** `apps/prototype-description-service/logs/recognition.log`  
**Purpose:** Validate whether the Suggestions Strategy will improve UX and accuracy

---

## Executive Summary

Analysis of production curation logs strongly supports implementing the Suggestions Strategy. The dominant pattern is **singleton merge corrections** (74% of merges), indicating users spend significant time finding and correcting false negatives that the suggestion system could surface automatically.

**Recommendation:** YES - Implement Suggestions Strategy with high priority on Phase 3 (suggestion refresh).

---

## Curation Event Summary

| Event Type                 | Count  | Notes                                        |
| -------------------------- | ------ | -------------------------------------------- |
| MERGED                     | 19     | User merged identities into labeled clusters |
| RENAMED                    | 10     | User applied/changed cluster labels          |
| SPLIT                      | 1      | User split a mixed cluster                   |
| REMOVED                    | 1      | User removed identity from cluster           |
| **Total Curation Actions** | **31** |                                              |

---

## Rejection Analysis

| Metric                                  | Count |
| --------------------------------------- | ----- |
| Total Automatic Rejections              | 25    |
| Suggestions Skipped (unlabeled cluster) | 8     |

### Rejection Reasons

| Reason                                   | Count | Percentage |
| ---------------------------------------- | ----- | ---------- |
| complete-link similarity below threshold | 19    | 76%        |
| member distribution mismatch             | 6     | 24%        |

**Insight:** 76% of rejections are pure similarity threshold failures - these are prime candidates for the suggestion band (marginal rejects that users might want to review).

---

## Merge Size Distribution

| Moved Count   | Frequency | Pattern                  |
| ------------- | --------- | ------------------------ |
| 1 identity    | 14        | **Singleton correction** |
| 2 identities  | 3         | Small correction         |
| 13 identities | 1         | Medium batch merge       |
| 59 identities | 1         | Large batch merge        |

### Key Finding: Singleton Dominance

- **74% of merges** (14/19) moved exactly 1 identity
- This pattern indicates users are manually hunting for faces that should have been auto-assigned
- Each singleton merge represents a false negative the system failed to catch

---

## UX Impact Analysis

### Current User Workflow (Without Suggestions)

1. User labels a cluster
2. User manually searches for other occurrences of the same person
3. User finds unlabeled/orphan identities one at a time
4. User merges each singleton manually
5. Repeat for each new cluster

**Estimated time per singleton merge:** ~30 seconds (navigate, identify, merge)  
**Total time for 14 singleton merges:** ~7 minutes of manual hunting

### Proposed Workflow (With Suggestions)

1. User labels a cluster
2. System presents ranked suggestions (marginal rejects)
3. User accepts/rejects suggestions with single click
4. Suggestions auto-resolve as user curates

**Estimated time per suggestion review:** ~3 seconds (view, click accept/reject)  
**Projected time savings:** ~86% reduction in correction time

---

## Implementation Priority Based on Findings

### Highest Impact: Phase 3 (Suggestion Refresh)

The singleton merge pattern indicates users need:

1. **Automatic suggestion refresh after labeling** - when a cluster is labeled, refresh suggestions for orphan identities that might match
2. **Lower suggestion band** - `suggestion_floor: 0.70` captures marginal rejects that are currently becoming orphans
3. **Exclusive resolve** - when user merges a singleton, auto-reject suggestions for other clusters

### Medium Impact: Phase 2 (Forced Split)

Only 1 split event in logs, but critical for correctness when it does occur.

### Lower Priority: Phase 4 (UI Components)

Depends on Phase 3 backend implementation.

---

## Specific Log Patterns

### Pattern 1: Immediate Merge After Labeling

```
[curation] RENAMED cluster=X label='Person Name'
[curation] MERGED target_cluster=X moved_count=1 identity=Y
[curation] MERGED target_cluster=X moved_count=1 identity=Z
```

User labels a cluster, then immediately starts merging related faces they've found manually.

**With Suggestions:** System would present Y and Z as suggestions after labeling, eliminating manual search.

### Pattern 2: Batch Merge of Related Faces

```
[curation] MERGED target_cluster=X moved_count=59 source_cluster=Y
```

User found an entire unlabeled cluster of the same person.

**With Suggestions:** System could have surfaced cluster Y as a high-confidence merge candidate.

### Pattern 3: Rejections Creating Orphans

```
[assignment] REJECTED identity=X cluster=Y reason=complete-link similarity below threshold
```

Identity becomes an orphan because it fell just below threshold.

**With Suggestions:** Identity X would appear as pending suggestion for cluster Y, allowing user review.

---

## Validation Metrics for Post-Implementation

Track these metrics to validate the Suggestions Strategy:

1. **Suggestion Acceptance Rate** - target: >50%
2. **Singleton Merge Reduction** - expect significant drop in moved_count=1 merges
3. **Time to Complete Roster** - measure before/after labeling session duration
4. **Suggestion Freshness** - time between refresh trigger and suggestion availability

---

## Conclusion

The production log data provides strong evidence that:

1. **False negatives are the dominant correction pattern** (74% singleton merges)
2. **Current thresholds are too aggressive** (25 rejections, 19 from similarity alone)
3. **Users are manually doing what suggestions should automate** (hunting for related faces)

The Suggestions Strategy directly addresses these patterns by:

- Converting marginal rejects into reviewable suggestions
- Auto-refreshing suggestions after curation events
- Eliminating manual search for related faces

**Implementation should prioritize Phase 3 (suggestion refresh and resolve) for maximum user impact.**
