# ⚠️ ARCHIVED: Cluster Rework Documents

**Status**: ARCHIVED (November 25, 2025)

This directory contains historical analysis documents from the clustering pipeline rework. These documents capture the evolution of our thinking but contain overlapping, sometimes contradictory, and outdated information.

## Current Authoritative Documents

For current clustering documentation, see:

1. **[../4.2.3/clustering-algorithm-comprehensive-analysis.md](../4.2.3/clustering-algorithm-comprehensive-analysis.md)**

   - FAISS usage and purpose
   - Cosine similarity vs Euclidean distance
   - Apple Photos algorithm analysis
   - HDBSCAN vs Chinese Whispers comparison
   - Confidence-weighted thresholds (Option C)
   - eps parameter explanation
   - Recall vs precision tradeoffs

2. **[../4.2.3/clustering-pipeline-analysis.md](../4.2.3/clustering-pipeline-analysis.md)**

   - Dead code analysis
   - Current threshold complexity
   - Pipeline simplification recommendations

3. **[../4.2.3/improve-suggestion-ux-reduce-false-negatives.md](../4.2.3/improve-suggestion-ux-reduce-false-negatives.md)**
   - Suggestion tier proposal (Option D)
   - Implementation tasks

## Why These Documents Are Archived

The documents in this directory were created during exploratory phases and contain:

- **Multiple algorithm proposals** that were never implemented
- **Ward clustering references** that were replaced by Chinese Whispers
- **FAISS integration plans** that were deprioritized
- **Threshold values** that have since been updated
- **Centroid normalization fixes** that were applied

## Historical Document Index

| Document                                    | Original Purpose             | Status                               |
| ------------------------------------------- | ---------------------------- | ------------------------------------ |
| `algorithm_comparison.md`                   | Initial algorithm evaluation | Superseded by comprehensive analysis |
| `centroid-fidelity-plan.md`                 | Fix for centroid drift       | Implemented                          |
| `centroid-regression-notes.md`              | Debug notes                  | Resolved                             |
| `cluster-regression-analysis.md`            | Batch size regression        | Resolved                             |
| `clustering-algorithm-evaluation.md`        | CW vs pipeline evaluation    | Superseded                           |
| `clustering-fix-implementation-plan.md`     | Two-stage hybrid clustering  | Partially implemented (Ward removed) |
| `clustering-pipeline-redesign.md`           | Pipeline redesign proposal   | Superseded                           |
| `clustering-rearchitecture-proposal.md`     | Architecture overhaul        | Superseded                           |
| `clustering-redesign-proposals.md`          | Design proposals             | Superseded                           |
| `clustering-rework-proposal.md`             | Original rework proposal     | Superseded                           |
| `clustering_analysis.md`                    | General analysis             | Superseded                           |
| `critique_report.md`                        | Code review notes            | Historical                           |
| `debug-clustering-batch-size-regression.md` | Debug session notes          | Resolved                             |

## Do Not Update

These documents are preserved for historical reference only. Do not update them. All new clustering documentation should go in `docs/tasks/4.0/4.2.3/`.
