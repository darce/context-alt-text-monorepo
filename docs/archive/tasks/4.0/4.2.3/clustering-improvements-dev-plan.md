# Clustering Improvements Development Plan

**Date**: November 25, 2025  
**Sprint**: 4.2.3  
**Related**: [clustering-algorithm-comprehensive-analysis.md](./clustering-algorithm-comprehensive-analysis.md)

---

## Overview

This document provides actionable development tasks for improving the face clustering pipeline. Tasks are organized by feature slice with checkboxes for tracking progress.

**Goals**:

1. Reduce singleton clusters (improve recall)
2. Reduce false positives (maintain precision)
3. Enable data-driven threshold tuning
4. Implement deterministic hybrid clustering with HDBSCAN singleton rescue

---

## Table of Contents

1. [Metrics & Observability](#1-metrics--observability) ⬅️ Start here
2. [Slice A: Option C - Confidence Weighting](#slice-a-option-c---confidence-weighting)
3. [Slice B: Extended 1024D Vectors](#slice-b-extended-1024d-vectors)
4. [Slice C: Configurable Thresholds](#slice-c-configurable-thresholds)
5. [Slice D: Deterministic CW + HDBSCAN](#slice-d-deterministic-cw--hdbscan)
6. [Slice E: In-Session Reconciliation](#slice-e-in-session-reconciliation)
7. [Slice F: Auto-Tuning Framework](#slice-f-auto-tuning-framework)
8. [Slice G: Color Histogram Sessions](#slice-g-color-histogram-sessions)
9. [Best Practices & Patterns](#best-practices--patterns)

---

## 1. Metrics & Observability

> **Priority**: HIGH - Implement first to measure impact of all other changes

### 1.1 Core Metrics Definition

- [ ] **Define key performance indicators (KPIs)**

  ```python
  @dataclass
  class ClusteringMetrics:
      """Core metrics for clustering quality."""
      # Cluster distribution
      total_identities: int
      total_clusters: int
      singleton_count: int
      singleton_ratio: float  # singleton_count / total_clusters

      # Cluster sizes
      avg_cluster_size: float
      median_cluster_size: float
      max_cluster_size: int

      # Quality indicators
      avg_intra_cluster_similarity: float  # Higher = tighter clusters
      min_intra_cluster_similarity: float  # Catch outlier members

      # User feedback (if available)
      suggestion_acceptance_rate: float
      merge_rate: float  # User-initiated merges
      split_rate: float  # User-initiated splits

      # Performance
      clustering_duration_ms: float
      batch_size: int
  ```

- [ ] **Create metrics collection utility**
  - File: `recognition/application/metrics.py`
  ```python
  async def collect_clustering_metrics(
      tenant_id: UUID,
      session: AsyncSession,
  ) -> ClusteringMetrics:
      """Collect current clustering metrics for a tenant."""
      # Implementation
  ```

### 1.2 Logging Infrastructure

- [ ] **Structured logging for clustering events**

  ```python
  # Pattern: Use structured logs with consistent fields
  logger.info(
      "clustering_complete",
      extra={
          "tenant_id": str(tenant_id),
          "batch_size": len(identities),
          "clusters_created": len(new_clusters),
          "singletons": singleton_count,
          "duration_ms": duration_ms,
          "algorithm": "chinese_whispers",  # or "hdbscan"
          "threshold": settings.similarity_threshold,
      }
  )
  ```

- [ ] **Add logging to key decision points**
  - [ ] Representative matching results
  - [ ] Cluster assignment decisions
  - [ ] Threshold comparisons
  - [ ] Outlier detection

### 1.3 Metrics API Endpoint

- [ ] **Create metrics endpoint**
  - File: `api/routes/metrics_router.py`
  ```python
  @router.get("/tenants/{tenant_id}/clustering/metrics")
  async def get_clustering_metrics(
      tenant_id: UUID,
      days: int = 7,
  ) -> ClusteringMetricsResponse:
      """Return clustering quality metrics."""
  ```

### 1.4 Baseline Measurement

- [ ] **Record current baseline before changes**
  - Run metrics collection on existing data
  - Document current singleton ratio
  - Document current acceptance rate (if tracked)
  - Save as benchmark for comparison

### 1.5 Log Archiving & Comparison

> **Purpose**: Preserve `recognition.log` snapshots before and after changes to enable A/B metric comparison.

- [ ] **Archive current logs before implementing changes**

  ```bash
  # Location: apps/prototype-description-service/logs/

  # Before any changes, create baseline snapshot
  TIMESTAMP=$(date +%Y%m%d_%H%M%S)
  cp recognition.log recognition.log.baseline_${TIMESTAMP}

  # Example: recognition.log.baseline_20251125_143000
  ```

- [ ] **Create named snapshots for each slice**

  ```bash
  # After implementing Slice A (Confidence Weighting):
  cp recognition.log recognition.log.slice_a_confidence_$(date +%Y%m%d)

  # After implementing Slice D (Deterministic CW + HDBSCAN):
  cp recognition.log recognition.log.slice_d_hybrid_$(date +%Y%m%d)
  ```

- [ ] **Log naming convention**
      | Pattern | Purpose |
      |---------|---------|
      | `recognition.log` | Current active log |
      | `recognition.log.baseline_YYYYMMDD_HHMMSS` | Pre-change baseline |
      | `recognition.log.slice_X_NAME_YYYYMMDD` | Post-slice implementation |
      | `recognition.log.experiment_NAME_YYYYMMDD` | Ad-hoc experiments |

- [ ] **Extract metrics from archived logs**

  ```bash
  # Count singleton clusters created
  grep "Creating NEW cluster" recognition.log.baseline_* | wc -l
  grep "Creating NEW cluster" recognition.log.slice_a_* | wc -l

  # Count successful assignments
  grep "Assigned to existing cluster" recognition.log.baseline_* | wc -l
  grep "Assigned to existing cluster" recognition.log.slice_a_* | wc -l

  # Count member validation failures (false positive prevention)
  grep "MEMBER VALIDATION FAILED" recognition.log.baseline_* | wc -l
  grep "MEMBER VALIDATION FAILED" recognition.log.slice_a_* | wc -l

  # Count borderline validations
  grep "BORDERLINE" recognition.log.baseline_* | wc -l
  grep "VALIDATED" recognition.log.slice_a_* | wc -l
  ```

- [ ] **Create comparison script** (optional)

  - File: `scripts/compare_clustering_logs.sh`

  ```bash
  #!/bin/bash
  # Compare clustering metrics between two log files

  LOG_A="${1:-recognition.log.baseline}"
  LOG_B="${2:-recognition.log}"

  echo "=== Clustering Log Comparison ==="
  echo "Baseline: $LOG_A"
  echo "Current:  $LOG_B"
  echo ""

  echo "--- Cluster Creation ---"
  echo "New clusters (baseline): $(grep -c 'Creating NEW cluster' "$LOG_A" 2>/dev/null || echo 0)"
  echo "New clusters (current):  $(grep -c 'Creating NEW cluster' "$LOG_B" 2>/dev/null || echo 0)"
  echo ""

  echo "--- Assignments ---"
  echo "Assigned to existing (baseline): $(grep -c 'Assigned to existing' "$LOG_A" 2>/dev/null || echo 0)"
  echo "Assigned to existing (current):  $(grep -c 'Assigned to existing' "$LOG_B" 2>/dev/null || echo 0)"
  echo ""

  echo "--- Validation ---"
  echo "Member validation failed (baseline): $(grep -c 'MEMBER VALIDATION FAILED' "$LOG_A" 2>/dev/null || echo 0)"
  echo "Member validation failed (current):  $(grep -c 'MEMBER VALIDATION FAILED' "$LOG_B" 2>/dev/null || echo 0)"
  echo ""

  echo "--- Borderline Cases ---"
  echo "Borderline attempts (baseline): $(grep -c 'BORDERLINE' "$LOG_A" 2>/dev/null || echo 0)"
  echo "Borderline attempts (current):  $(grep -c 'BORDERLINE' "$LOG_B" 2>/dev/null || echo 0)"
  echo "Validated (baseline): $(grep -c 'VALIDATED' "$LOG_A" 2>/dev/null || echo 0)"
  echo "Validated (current):  $(grep -c 'VALIDATED' "$LOG_B" 2>/dev/null || echo 0)"
  ```

- [ ] **Rotation policy for archived logs**
  - Keep baseline logs indefinitely (small, valuable)
  - Keep slice logs for duration of sprint
  - Delete experiment logs after 7 days
  - Consider `gzip` for logs > 10MB:
    ```bash
    gzip recognition.log.baseline_20251125_143000
    # Creates: recognition.log.baseline_20251125_143000.gz
    ```

---

## Slice A: Option C - Confidence Weighting

> **Prerequisite**: Metrics infrastructure (Section 1)

### A.1 Detection Quality Storage

- [ ] **Verify MediaIdentity stores detection metadata**

  - Check if `det_score` column exists
  - Check if `bbox` dimensions are stored
  - File: `db/models/media_identity.py`

- [ ] **Migration if needed**

  ```python
  # If columns missing, add migration
  op.add_column('media_identities', sa.Column('det_score', sa.Float, nullable=True))
  op.add_column('media_identities', sa.Column('bbox_width', sa.Integer, nullable=True))
  op.add_column('media_identities', sa.Column('bbox_height', sa.Integer, nullable=True))
  ```

- [ ] **Backfill existing records** (if migration added)
  - Set det_score to 0.9 (assume high quality for existing)
  - Extract bbox dimensions from stored bbox if available

### A.2 Confidence Factor Calculation

- [ ] **Create confidence utilities**

  - File: `recognition/application/confidence_utils.py`

  ```python
  def compute_detection_confidence(
      det_score: float,
      bbox_area: int,
      min_bbox_area: int = 10000,
  ) -> float:
      """
      Compute confidence factor from detection quality.

      Returns:
          float: Confidence factor in [0, 1]
      """
      # Detection confidence
      det_conf = det_score

      # Size confidence (penalize small faces)
      size_conf = min(1.0, bbox_area / min_bbox_area)

      # Geometric mean for combined confidence
      return (det_conf * size_conf) ** 0.5


  def compute_pair_confidence(
      source_det_score: float,
      source_bbox_area: int,
      target_det_score: float,
      target_bbox_area: int,
  ) -> float:
      """Compute confidence for a pair of detections."""
      source_conf = compute_detection_confidence(source_det_score, source_bbox_area)
      target_conf = compute_detection_confidence(target_det_score, target_bbox_area)
      return (source_conf * target_conf) ** 0.5
  ```

- [ ] **Unit tests for confidence calculation**
  - File: `recognition/tests/test_confidence_utils.py`
  - Test high-quality pair → high confidence
  - Test low-quality pair → low confidence
  - Test mixed quality → medium confidence

### A.3 Adaptive Threshold Implementation

- [ ] **Create adaptive threshold function**

  ```python
  def adaptive_threshold(
      base_threshold: float,
      confidence: float,
      settings: ClusteringSettings,
  ) -> float:
      """
      Adjust threshold based on detection confidence.

      High confidence → lower threshold (easier to match)
      Low confidence → higher threshold (harder to match)
      """
      midpoint = settings.confidence_midpoint  # e.g., 0.85
      max_adj = settings.threshold_max_adjustment  # e.g., 0.10

      adjustment = max_adj * (confidence - midpoint) / (1.0 - midpoint)
      adjustment = np.clip(adjustment, -max_adj, max_adj)

      return base_threshold - adjustment
  ```

- [ ] **Unit tests for adaptive threshold**
  - High confidence (0.95) with base 0.65 → ~0.60
  - Low confidence (0.75) with base 0.65 → ~0.70
  - Edge cases: confidence at bounds

### A.4 Integration with Representative Matching

- [ ] **Modify `_find_best_representative_match`**

  - File: `recognition/application/identity_clustering_service.py`

  ```python
  async def _find_best_representative_match(
      self,
      identity: MediaIdentity,
      identity_vector: np.ndarray,
  ) -> tuple[UUID | None, float]:
      # Get detection quality
      det_score = identity.det_score or 0.9
      bbox_area = (identity.bbox_width or 100) * (identity.bbox_height or 100)

      for cluster_id, representatives in self.cluster_reps.items():
          for rep in representatives:
              raw_similarity = np.dot(identity_vector, rep.embedding)

              # Compute pair confidence
              confidence = compute_pair_confidence(
                  det_score, bbox_area,
                  rep.det_score, rep.bbox_area,
              )

              # Adaptive threshold
              threshold = adaptive_threshold(
                  self.settings.similarity_threshold,
                  confidence,
                  self.settings,
              )

              if raw_similarity >= threshold:
                  # Log decision for analysis
                  logger.debug(
                      "rep_match_decision",
                      extra={
                          "identity_id": str(identity.id),
                          "cluster_id": str(cluster_id),
                          "raw_similarity": raw_similarity,
                          "confidence": confidence,
                          "threshold": threshold,
                          "decision": "accept",
                      }
                  )
                  return cluster_id, raw_similarity

      return None, 0.0
  ```

- [ ] **Integration test: confidence weighting end-to-end**
  - Create identities with varying detection quality
  - Verify high-quality faces cluster more easily
  - Verify low-quality faces require higher similarity

---

## Slice B: Extended 1024D Vectors

> **Prerequisite**: Slice A (confidence calculation)

### B.1 Define Extended Embedding Layout

- [x] **Document embedding layout**
  - File: `recognition/application/embedding_layout.py` ✅ Created
  - Constants for all indices and scales
  - 15 tests in `test_embedding_builder.py`

### B.2 Extended Embedding Builder

- [x] **Create embedding builder utility**
  - File: `recognition/application/embedding_builder.py` ✅ Created
  - Functions: `build_extended_embedding()`, `ensure_1024d()`, `extract_face_embedding()`
  - All 15 tests passing

### B.3 Update Face Detection Pipeline

- [x] **Modify InsightFace integration to extract all attributes**

  - File: `recognition/infrastructure/embedding_provider.py`
  - Uses `build_extended_embedding()` to construct 1024D embeddings
  - Extracts pose, age, gender, landmarks from InsightFace results

- [x] **Update identity creation to use extended embedding**
  - `FaceEmbeddingProvider.analyze()` now produces 1024D embeddings
  - Test updated in `test_embedding_provider.py` to use normalized mock embedding

### B.4 Backward Compatibility

- [x] **Handle existing 512D embeddings**

  - `ensure_1024d()` implemented in `embedding_builder.py`
  - `extract_face_embedding()` extracts first 512D from extended embedding
  - `prepare_embedding()` utility for consistent embedding preparation

- [x] **Update all embedding reads to use `ensure_1024d`**
  - Updated `representative_matcher.py` to use `prepare_embedding()`
  - Updated `identity_clustering_service.py` to use `prepare_embedding()`
  - Updated `cluster_factory.py` to use `prepare_embedding()`
  - Updated `clustering_utils.py` `normalize_embeddings()` to use `prepare_embedding()`
  - Updated `centroid_utils.py` with dimension-agnostic similarity/update functions

---

## Slice C: Configurable Thresholds

> **Prerequisite**: Metrics (Section 1)

### C.1 Expand ClusteringSettings

- [x] **Add new configurable parameters**

  - File: `recognition/application/clustering/clustering_settings.py`

  ```python
  @dataclass(frozen=True)
  class ClusteringSettings:
      # === Similarity Thresholds ===
      similarity_threshold: float = 0.65
      member_validation_threshold: float = 0.68
      cw_threshold: float = 0.75

      # === Confidence Weighting (NEW) ===
      confidence_weighting_enabled: bool = False
      confidence_midpoint: float = 0.85
      threshold_max_adjustment: float = 0.10
      min_bbox_area: int = 10000

      # === Chinese Whispers Determinism (NEW) ===
      cw_max_iterations: int = 20
      cw_quality_weighted_votes: bool = True  # Use quality-weighted voting

      # === HDBSCAN Singleton Rescue (NEW) ===
      use_hdbscan_for_outliers: bool = False
      hdbscan_min_cluster_size: int = 2
      hdbscan_min_samples: int = 1

      # === Auto-Tuning Bounds (NEW) ===
      auto_tune_enabled: bool = False
      threshold_min: float = 0.50
      threshold_max: float = 0.80
      auto_tune_target_acceptance: float = 0.70

      # === Session Inference (NEW) ===
      session_boost_enabled: bool = False
      session_similarity_threshold: float = 0.85
      session_boost_amount: float = 0.05
  ```

### C.2 Database-Backed Configuration

- [x] **Create tenant configuration table**

  - File: `db/migrations/versions/001_identity_schema.py` (merged)
  - Table: `tenant_clustering_configs`
  - All clustering parameters with sensible defaults
  - Check constraints for value ranges
  - RLS policy for tenant isolation

- [x] **Create config repository**

  - File: `recognition/infrastructure/config_repository.py`

  ```python
  async def get_tenant_config(session, tenant_id) -> ClusteringSettings
  async def save_tenant_config(session, tenant_id, settings) -> TenantClusteringConfig
  async def update_tenant_config(session, tenant_id, updates) -> ClusteringSettings
  async def delete_tenant_config(session, tenant_id) -> bool
  ```

### C.3 Configuration API

- [x] **Create config management endpoints**

  - File: `recognition/interface_adapters/http/config_router.py`

  ```python
  @router.get("/config")      # Get current clustering configuration
  @router.patch("/config")    # Update specific configuration fields
  @router.delete("/config")   # Reset configuration to defaults
  ```

### C.4 Tests

- [x] **Config repository tests**

  - File: `recognition/tests/test_config_repository.py`
  - 11 tests covering CRUD operations and edge cases

- [x] **Config API endpoint tests**
  - File: `recognition/tests/test_config_endpoints.py`
  - 14 tests covering GET/PATCH/DELETE endpoints

---

## Slice D: Deterministic CW + HDBSCAN

> **Prerequisite**: Configurable thresholds (Slice C)
>
> **Design Decision**: We chose to skip HAC-based two-pass clustering (originally Slice D) to avoid introducing an additional threshold parameter. Instead, we implement deterministic Chinese Whispers with quality-weighted votes and HDBSCAN for singleton rescue. This approach:
>
> - Uses quality-weighted votes for determinism (compatible with auto-tuning in Slice F)
> - Uses UUID-based tie-breaking for stable ordering
> - Leverages HDBSCAN's natural outlier detection (label=-1) for singleton rescue

### D.1 Make Chinese Whispers Deterministic

- [ ] **Implement deterministic node ordering and quality-weighted votes**

  - File: `recognition/application/clustering/chinese_whispers.py`

  ```python
  async def deterministic_chinese_whispers(
      identities: list[MediaIdentity],
      settings: ClusteringSettings,
  ) -> list[int]:
      """
      Deterministic Chinese Whispers clustering.

      Key changes from standard CW:
      1. Stable node order via UUID sorting (neutral anchor)
      2. Quality-weighted votes for neighbor influence
      3. UUID tie-breaking when vote counts are equal
      """
      n = len(identities)
      if n == 0:
          return []

      # Initialize: each node in its own cluster
      labels = list(range(n))

      # Stable node order: sort by UUID (deterministic, neutral)
      node_order = sorted(range(n), key=lambda i: str(identities[i].id))

      # Build similarity graph (precompute for efficiency)
      embeddings = np.array([
          normalize(i.embedding[:512]) for i in identities
      ])
      sim_matrix = np.dot(embeddings, embeddings.T)

      # Extract quality scores for weighting
      qualities = np.array([
          compute_detection_confidence(
              i.det_score or 0.9,
              (i.bbox_width or 100) * (i.bbox_height or 100),
          ) for i in identities
      ])

      # Iterate until convergence
      max_iterations = settings.cw_max_iterations  # e.g., 20
      for iteration in range(max_iterations):
          changes = 0

          for i in node_order:
              # Find neighbors above threshold
              neighbors = [
                  j for j in range(n)
                  if j != i and sim_matrix[i, j] >= settings.cw_threshold
              ]

              if not neighbors:
                  continue

              # Quality-weighted votes for each label
              votes: dict[int, float] = {}
              for j in neighbors:
                  label = labels[j]
                  sim = sim_matrix[i, j]
                  quality = qualities[j]

                  # Weight vote by similarity * neighbor quality
                  weighted_vote = sim * quality
                  votes[label] = votes.get(label, 0.0) + weighted_vote

              if not votes:
                  continue

              # Find best label with UUID tie-breaking
              max_vote = max(votes.values())
              candidates = [lbl for lbl, v in votes.items() if v == max_vote]

              if len(candidates) == 1:
                  best_label = candidates[0]
              else:
                  # Tie-break: pick label with smallest UUID among members
                  def min_uuid_for_label(lbl: int) -> str:
                      member_ids = [
                          str(identities[k].id)
                          for k in range(n) if labels[k] == lbl
                      ]
                      return min(member_ids) if member_ids else ""

                  best_label = min(candidates, key=min_uuid_for_label)

              if labels[i] != best_label:
                  labels[i] = best_label
                  changes += 1

          logger.debug(
              "cw_iteration",
              extra={
                  "iteration": iteration,
                  "changes": changes,
                  "clusters": len(set(labels)),
              }
          )

          if changes == 0:
              break

      return labels
  ```

- [ ] **Unit tests for deterministic CW**
  - File: `recognition/tests/test_chinese_whispers.py`
  - Test same input → same output (determinism)
  - Test quality weighting affects cluster assignment
  - Test UUID tie-breaking produces consistent results
  - Test convergence within max iterations

### D.2 HDBSCAN Integration

- [ ] **Add HDBSCAN dependency**

  - File: `requirements_main.txt`

  ```text
  scikit-learn>=1.3.0  # HDBSCAN included in sklearn 1.3+
  ```

- [ ] **Create HDBSCAN wrapper for singleton rescue**

  - File: `recognition/application/clustering/hdbscan_clustering.py`

  ```python
  from sklearn.cluster import HDBSCAN

  async def hdbscan_rescue_singletons(
      singletons: list[MediaIdentity],
      settings: ClusteringSettings,
  ) -> tuple[list[list[MediaIdentity]], list[MediaIdentity]]:
      """
      Attempt to cluster singletons using HDBSCAN.

      Args:
          singletons: Identities that CW left as singletons
          settings: Clustering configuration

      Returns:
          (rescued_groups, remaining_outliers):
              - rescued_groups: Lists of identities that form new clusters
              - remaining_outliers: Identities still unclustered (HDBSCAN label=-1)
      """
      if len(singletons) < 2:
          return [], singletons

      # Extract embeddings
      embeddings = np.array([
          normalize(i.embedding[:512]) for i in singletons
      ])

      # Compute distance matrix (1 - similarity)
      sim_matrix = np.dot(embeddings, embeddings.T)
      dist_matrix = 1 - sim_matrix
      np.fill_diagonal(dist_matrix, 0)

      # HDBSCAN clustering with looser parameters for rescue
      clusterer = HDBSCAN(
          min_cluster_size=settings.hdbscan_min_cluster_size,  # 2
          min_samples=settings.hdbscan_min_samples,  # 1
          metric='precomputed',
          cluster_selection_epsilon=1 - settings.similarity_threshold,  # ~0.35
      )
      labels = clusterer.fit_predict(dist_matrix)

      # Separate rescued clusters from remaining outliers
      rescued_groups: dict[int, list[MediaIdentity]] = {}
      remaining_outliers: list[MediaIdentity] = []

      for i, label in enumerate(labels):
          if label == -1:
              remaining_outliers.append(singletons[i])
          else:
              if label not in rescued_groups:
                  rescued_groups[label] = []
              rescued_groups[label].append(singletons[i])

      logger.info(
          "hdbscan_rescue_complete",
          extra={
              "input_singletons": len(singletons),
              "rescued_clusters": len(rescued_groups),
              "remaining_outliers": len(remaining_outliers),
          }
      )

      return list(rescued_groups.values()), remaining_outliers
  ```

- [ ] **Unit tests for HDBSCAN rescue**
  - File: `recognition/tests/test_hdbscan_clustering.py`
  - Test similar singletons get rescued into clusters
  - Test dissimilar singletons remain outliers
  - Test deterministic output (HDBSCAN is deterministic)
  - Test edge cases: 0, 1, 2 singletons

### D.3 Hybrid Pipeline

- [ ] **Create hybrid CW + HDBSCAN pipeline**

  - File: `recognition/application/clustering/hybrid_clustering.py`

  ```python
  async def hybrid_clustering(
      identities: list[MediaIdentity],
      settings: ClusteringSettings,
  ) -> list[IdentityCluster]:
      """
      Hybrid approach: Deterministic CW for bulk clustering,
      HDBSCAN for singleton rescue.

      Pipeline:
      1. Run deterministic Chinese Whispers on all identities
      2. Identify singletons (clusters with 1 member)
      3. Run HDBSCAN on singletons to rescue similar ones
      4. Create final clusters
      """
      if not identities:
          return []

      # Step 1: Deterministic Chinese Whispers
      labels = await deterministic_chinese_whispers(identities, settings)

      # Group by label
      label_groups: dict[int, list[MediaIdentity]] = {}
      for i, label in enumerate(labels):
          if label not in label_groups:
              label_groups[label] = []
          label_groups[label].append(identities[i])

      # Separate multi-member clusters from singletons
      valid_clusters: list[list[MediaIdentity]] = []
      singletons: list[MediaIdentity] = []

      for members in label_groups.values():
          if len(members) == 1:
              singletons.append(members[0])
          else:
              valid_clusters.append(members)

      logger.info(
          "hybrid_cw_phase_complete",
          extra={
              "total_identities": len(identities),
              "valid_clusters": len(valid_clusters),
              "singletons_for_rescue": len(singletons),
          }
      )

      # Step 2: HDBSCAN rescue for singletons
      if settings.use_hdbscan_for_outliers and len(singletons) >= 2:
          rescued_groups, remaining_outliers = await hdbscan_rescue_singletons(
              singletons, settings
          )

          # Add rescued groups as new clusters
          valid_clusters.extend(rescued_groups)

          # Remaining outliers become singleton clusters
          for outlier in remaining_outliers:
              valid_clusters.append([outlier])
      else:
          # No HDBSCAN rescue: singletons become singleton clusters
          for singleton in singletons:
              valid_clusters.append([singleton])

      # Step 3: Create cluster objects
      final_clusters: list[IdentityCluster] = []
      for members in valid_clusters:
          cluster = await create_cluster_from_members(members)
          final_clusters.append(cluster)

      logger.info(
          "hybrid_clustering_complete",
          extra={
              "total_clusters": len(final_clusters),
              "singleton_clusters": sum(
                  1 for c in final_clusters if len(c.members) == 1
              ),
          }
      )

      return final_clusters
  ```

### D.4 Algorithm Selector

- [ ] **Create main entry point with algorithm selection**

  ```python
  async def cluster_identities(
      identities: list[MediaIdentity],
      settings: ClusteringSettings,
  ) -> list[IdentityCluster]:
      """
      Main entry point for clustering.

      Routes to appropriate algorithm based on settings:
      - Hybrid CW + HDBSCAN (default when hdbscan enabled)
      - Pure deterministic CW (fallback)
      """
      if settings.use_hdbscan_for_outliers:
          return await hybrid_clustering(identities, settings)

      # Pure CW without HDBSCAN rescue
      labels = await deterministic_chinese_whispers(identities, settings)
      return await labels_to_clusters(identities, labels)
  ```

- [ ] **Integration tests for hybrid pipeline**
  - File: `recognition/tests/test_hybrid_clustering.py`
  - Test end-to-end clustering produces deterministic results
  - Test singleton ratio is reduced with HDBSCAN rescue
  - Test quality weighting influences cluster formation
  - Test graceful degradation when HDBSCAN disabled

---

## Slice E: In-Session Reconciliation

> **Prerequisite**: Deterministic CW + HDBSCAN (Slice D)

### E.1 Reconciliation Events

- [ ] **Define reconciliation triggers**

  - File: `recognition/application/reconciliation.py`

  ```python
  from enum import Enum

  class ReconciliationTrigger(Enum):
      USER_CONFIRMS = "user_confirms"
      USER_MERGES = "user_merges"
      USER_SPLITS = "user_splits"
      BATCH_COMPLETE = "batch_complete"

  @dataclass
  class ReconciliationContext:
      trigger: ReconciliationTrigger
      tenant_id: UUID
      cluster_id: UUID | None = None
      identity_id: UUID | None = None
      affected_cluster_ids: list[UUID] = field(default_factory=list)
  ```

### E.2 Scoped Reconciliation

- [ ] **Implement lightweight reconciliation**

  ```python
  async def reconcile_cluster_neighbors(
      context: ReconciliationContext,
      session: AsyncSession,
      settings: ClusteringSettings,
  ) -> ReconciliationResult:
      """
      Fast reconciliation for a single cluster update.
      """
      if context.trigger == ReconciliationTrigger.USER_CONFIRMS:
          return await reconcile_on_confirm(
              context.cluster_id,
              context.identity_id,
              session,
              settings,
          )

      elif context.trigger == ReconciliationTrigger.USER_MERGES:
          return await reconcile_on_merge(
              context.affected_cluster_ids,
              session,
              settings,
          )

      elif context.trigger == ReconciliationTrigger.USER_SPLITS:
          return await reconcile_on_split(
              context.affected_cluster_ids,
              session,
              settings,
          )

      return ReconciliationResult(changes=0)


  async def reconcile_on_confirm(
      cluster_id: UUID,
      new_member_id: UUID,
      session: AsyncSession,
      settings: ClusteringSettings,
  ) -> ReconciliationResult:
      """
      After user confirms a suggestion, check related singletons.
      """
      # Get newly confirmed member
      new_member = await get_identity(session, new_member_id)
      new_embedding = normalize(new_member.embedding[:512])

      # Get recent singletons
      singletons = await get_recent_singletons(
          session,
          tenant_id=new_member.tenant_id,
          limit=50,
      )

      promoted = 0
      for singleton in singletons:
          singleton_embedding = normalize(singleton.embedding[:512])
          similarity = np.dot(new_embedding, singleton_embedding)

          if similarity >= settings.recompute_similarity_threshold:
              # Check against full cluster
              avg_sim = await compute_avg_cluster_similarity(
                  session, cluster_id, singleton_embedding
              )

              if avg_sim >= settings.member_validation_threshold:
                  await add_to_cluster(session, cluster_id, singleton)
                  promoted += 1

      return ReconciliationResult(changes=promoted)
  ```

### E.3 Background Task Integration

- [ ] **Create background task wrapper**

  - File: `api/routes/cluster_router.py`

  ```python
  from fastapi import BackgroundTasks

  @router.post("/clusters/{cluster_id}/confirm/{suggestion_id}")
  async def confirm_suggestion(
      cluster_id: UUID,
      suggestion_id: UUID,
      background_tasks: BackgroundTasks,
      session: AsyncSession = Depends(get_session),
      settings: ClusteringSettings = Depends(get_settings),
  ):
      # Confirm synchronously
      identity_id = await confirm_identity_to_cluster(
          session, cluster_id, suggestion_id
      )

      # Queue reconciliation
      context = ReconciliationContext(
          trigger=ReconciliationTrigger.USER_CONFIRMS,
          tenant_id=current_tenant_id(),
          cluster_id=cluster_id,
          identity_id=identity_id,
      )

      background_tasks.add_task(
          reconcile_cluster_neighbors,
          context,
          session,
          settings,
      )

      return {"status": "confirmed", "reconciliation": "queued"}
  ```

---

## Slice F: Auto-Tuning Framework

> **Prerequisite**: In-session reconciliation (Slice E)

### F.1 Feedback Collection

- [ ] **Create feedback tracker**

  - File: `recognition/application/auto_tuning.py`

  ```python
  @dataclass
  class FeedbackMetrics:
      confirmations: int = 0
      rejections: int = 0
      merges: int = 0
      splits: int = 0
      period_start: datetime = field(default_factory=datetime.utcnow)

  class AutoTuner:
      def __init__(
          self,
          initial_threshold: float = 0.65,
          settings: ClusteringSettings = None,
      ):
          self.threshold = initial_threshold
          self.settings = settings or ClusteringSettings()
          self.metrics = FeedbackMetrics()
          self.min_samples = 20

      def record_confirmation(self) -> None:
          self.metrics.confirmations += 1
          self._maybe_adjust()

      def record_rejection(self) -> None:
          self.metrics.rejections += 1
          self._maybe_adjust()

      def record_merge(self) -> None:
          self.metrics.merges += 1
          self._maybe_adjust()

      def record_split(self) -> None:
          self.metrics.splits += 1
          self._maybe_adjust()

      def _maybe_adjust(self) -> None:
          total = sum([
              self.metrics.confirmations,
              self.metrics.rejections,
              self.metrics.merges,
              self.metrics.splits,
          ])

          if total < self.min_samples:
              return

          # Positive: confirmations, merges (threshold OK or too strict)
          # Negative: rejections, splits (threshold too loose)
          positive = self.metrics.confirmations + self.metrics.merges
          negative = self.metrics.rejections + self.metrics.splits

          if positive + negative == 0:
              return

          ratio = positive / (positive + negative)
          target = self.settings.auto_tune_target_acceptance

          step = 0.02

          if ratio > target + 0.1:
              # Too conservative, lower threshold
              new_threshold = self.threshold - step
              self.threshold = max(self.settings.threshold_min, new_threshold)
              logger.info(f"Auto-tune: lowered threshold to {self.threshold:.3f}")

          elif ratio < target - 0.1:
              # Too permissive, raise threshold
              new_threshold = self.threshold + step
              self.threshold = min(self.settings.threshold_max, new_threshold)
              logger.info(f"Auto-tune: raised threshold to {self.threshold:.3f}")

          # Reset for next period
          self.metrics = FeedbackMetrics()
  ```

### F.2 Per-Tenant Auto-Tuners

- [ ] **Create tenant-scoped auto-tuner registry**

  ```python
  # In-memory cache (for now)
  _tuners: dict[UUID, AutoTuner] = {}

  async def get_auto_tuner(
      tenant_id: UUID,
      session: AsyncSession,
  ) -> AutoTuner:
      if tenant_id not in _tuners:
          config = await get_tenant_config(session, tenant_id)
          _tuners[tenant_id] = AutoTuner(
              initial_threshold=config.similarity_threshold,
              settings=config,
          )
      return _tuners[tenant_id]

  async def persist_auto_tuner(
      tenant_id: UUID,
      tuner: AutoTuner,
      session: AsyncSession,
  ) -> None:
      """Persist tuned threshold to database."""
      await save_tenant_config(
          session,
          tenant_id,
          replace(tuner.settings, similarity_threshold=tuner.threshold),
      )
  ```

### F.3 Integration with User Actions

- [ ] **Wire auto-tuner to API endpoints**

  ```python
  @router.post("/clusters/{cluster_id}/reject/{suggestion_id}")
  async def reject_suggestion(
      cluster_id: UUID,
      suggestion_id: UUID,
      session: AsyncSession = Depends(get_session),
  ):
      await mark_suggestion_rejected(session, suggestion_id)

      # Record feedback
      tuner = await get_auto_tuner(current_tenant_id(), session)
      tuner.record_rejection()

      # Persist periodically (not every action)
      if tuner.metrics.confirmations + tuner.metrics.rejections >= 20:
          await persist_auto_tuner(current_tenant_id(), tuner, session)

      return {"status": "rejected"}
  ```

---

## Slice G: Color Histogram Sessions

> **Priority**: LOW - Implement after core features validated

### G.1 Scene Signature Extraction

- [ ] **Create scene signature utility**

  - File: `recognition/application/scene_signature.py`

  ```python
  import cv2

  def extract_scene_signature(image: np.ndarray) -> np.ndarray:
      """
      Extract scene-level color features for session detection.
      """
      # Downsample
      small = cv2.resize(image, (64, 64))
      hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

      features = []

      # HSV histograms
      for channel, bins, max_val in [(0, 16, 180), (1, 8, 256), (2, 8, 256)]:
          hist = cv2.calcHist([hsv], [channel], None, [bins], [0, max_val])
          features.append(hist.flatten())

      # Dominant colors (k-means)
      pixels = small.reshape(-1, 3).astype(np.float32)
      criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
      _, _, centers = cv2.kmeans(pixels, 5, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
      features.append(centers.flatten())

      # Color temperature
      b, _, r = cv2.split(small)
      temp = np.mean(b) / (np.mean(r) + 1e-6)
      features.append([temp])

      # Brightness
      features.append([np.mean(hsv[:,:,2]), np.std(hsv[:,:,2])])

      return normalize(np.concatenate(features))
  ```

### G.2 Session Grouping

- [ ] **Create session grouping utility**

  ```python
  async def group_by_session(
      identities: list[MediaIdentity],
      settings: ClusteringSettings,
  ) -> list[list[MediaIdentity]]:
      """
      Group identities by inferred session using scene similarity.
      """
      if not settings.session_boost_enabled:
          return [identities]  # Single group

      # Extract signatures (cached or computed)
      signatures = []
      for identity in identities:
          sig = await get_or_compute_scene_signature(identity.media_id)
          signatures.append(sig)

      # Greedy grouping
      sessions = []
      assigned = set()

      for i, identity in enumerate(identities):
          if i in assigned:
              continue

          session = [identity]
          assigned.add(i)

          for j in range(i + 1, len(identities)):
              if j in assigned:
                  continue

              sim = np.dot(signatures[i], signatures[j])
              if sim >= settings.session_similarity_threshold:
                  session.append(identities[j])
                  assigned.add(j)

          sessions.append(session)

      return sessions
  ```

### G.3 Session Boost Integration

- [ ] **Apply session boost to similarity**

  ```python
  async def compute_similarity_with_session_boost(
      identity_a: MediaIdentity,
      identity_b: MediaIdentity,
      base_similarity: float,
      settings: ClusteringSettings,
  ) -> float:
      """
      Boost similarity if identities are from same inferred session.
      """
      if not settings.session_boost_enabled:
          return base_similarity

      sig_a = await get_or_compute_scene_signature(identity_a.media_id)
      sig_b = await get_or_compute_scene_signature(identity_b.media_id)

      scene_sim = np.dot(sig_a, sig_b)

      if scene_sim >= settings.session_similarity_threshold:
          return min(1.0, base_similarity + settings.session_boost_amount)

      return base_similarity
  ```

---

## Best Practices & Patterns

### Pattern 1: Structured Logging

```python
# Always use structured logs with consistent fields
logger.info(
    "operation_name",
    extra={
        "tenant_id": str(tenant_id),
        "duration_ms": duration,
        "input_count": len(inputs),
        "output_count": len(outputs),
        "algorithm": "chinese_whispers",
        "threshold": threshold,
        # Add relevant context
    }
)
```

### Pattern 2: Feature Flags via Settings

```python
# Use settings for feature flags, not environment variables
if settings.two_pass_enabled:
    clusters = await two_pass_clustering(identities, settings)
else:
    clusters = await chinese_whispers_cluster(identities, settings)
```

### Pattern 3: Backward Compatibility

```python
# Always handle legacy data formats
def ensure_1024d(embedding: np.ndarray) -> np.ndarray:
    """Pad 512D embeddings for backward compatibility."""
    if len(embedding) == 512:
        padded = np.zeros(1024, dtype=np.float32)
        padded[0:512] = embedding
        return padded
    return embedding
```

### Pattern 4: Metrics Before Changes

```python
# Collect baseline metrics before any change
async def with_metrics(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        before = await collect_metrics()
        result = await func(*args, **kwargs)
        after = await collect_metrics()

        log_metric_delta(before, after)
        return result
    return wrapper
```

### Pattern 5: Configurable Defaults

```python
@dataclass(frozen=True)
class ClusteringSettings:
    # Document each parameter
    similarity_threshold: float = 0.65  # Range: [0.5, 0.8], higher = stricter

    @classmethod
    def with_overrides(cls, base: 'ClusteringSettings', **overrides) -> 'ClusteringSettings':
        """Create new settings with specific overrides."""
        return replace(base, **overrides)
```

### Pattern 6: Async Background Tasks

```python
# Use FastAPI BackgroundTasks for non-blocking operations
@router.post("/endpoint")
async def handler(background_tasks: BackgroundTasks):
    # Do synchronous work
    result = await sync_operation()

    # Queue async work (runs after response)
    background_tasks.add_task(async_operation, result.id)

    return {"status": "ok", "async_work": "queued"}
```

### Pattern 7: Graceful Degradation

```python
async def cluster_with_fallback(identities, settings):
    """Try advanced algorithm, fall back to simple if needed."""
    try:
        if len(identities) > 5000:
            raise ValueError("Too large for HDBSCAN")
        return await hdbscan_cluster(identities, settings)
    except Exception as e:
        logger.warning(f"HDBSCAN failed, falling back to CW: {e}")
        return await chinese_whispers_cluster(identities, settings)
```

### Pattern 8: Test Data Builders

```python
# Use builders for test data
class IdentityBuilder:
    def __init__(self):
        self._det_score = 0.95
        self._embedding = np.random.randn(512)

    def with_det_score(self, score: float) -> 'IdentityBuilder':
        self._det_score = score
        return self

    def with_embedding(self, embedding: np.ndarray) -> 'IdentityBuilder':
        self._embedding = embedding
        return self

    def build(self) -> MediaIdentity:
        return MediaIdentity(
            det_score=self._det_score,
            embedding=build_extended_embedding(self._embedding, ...),
        )

# Usage in tests
identity = IdentityBuilder().with_det_score(0.75).build()
```

---

## Progress Tracking

### Completed

- [x] Section 1: Metrics & Observability
  - [x] 1.1 Core Metrics Definition (ClusteringMetrics dataclass)
  - [x] 1.5 Log Archiving (baseline archived)
  - [x] 1.2 Logging Infrastructure (clustering_logger.py + integration)
  - [x] 1.3 Metrics API Endpoint (metrics_router.py)
  - [x] 1.4 Baseline Measurement (collect_baseline_metrics.py script)
- [x] Slice A: Option C - Confidence Weighting
  - [x] A.2 Confidence Factor Calculation (confidence_utils.py)
  - [x] A.3 Adaptive Threshold Implementation
  - [x] A.1 Detection Quality Storage (verified: bbox_width, bbox_height, confidence exist)
  - [x] A.4 Integration with Representative Matching (settings param added)
- [x] Slice B: Extended 1024D Vectors
  - [x] B.1 Define Extended Embedding Layout (embedding_layout.py)
  - [x] B.2 Extended Embedding Builder (embedding_builder.py)
  - [x] B.3 Update Face Detection Pipeline (embedding_provider.py uses build_extended_embedding)
  - [x] B.4 Removed - backward compatibility not needed (ensure_1024d deleted)
- [x] Slice C: Configurable Thresholds
  - [x] C.1 Expand ClusteringSettings (all new parameters added)
  - [x] C.2 Database-Backed Configuration (tenant_clustering_configs table + config_repository.py)
  - [x] C.3 Configuration API (config_router.py with GET/PATCH/DELETE)
  - [x] C.4 Tests (25 tests: test_config_repository.py + test_config_endpoints.py)
- [ ] Slice D: Deterministic CW + HDBSCAN
  - [ ] D.1 Make Chinese Whispers deterministic (quality-weighted votes, UUID tie-breaking)
  - [ ] D.2 HDBSCAN integration (sklearn 1.3+, singleton rescue)
  - [ ] D.3 Hybrid pipeline (CW bulk + HDBSCAN rescue)
  - [ ] D.4 Algorithm selector and integration tests
- [ ] Slice E: In-Session Reconciliation
  - [ ] E.1 Define reconciliation triggers (USER_CONFIRMS, USER_MERGES, USER_SPLITS)
  - [ ] E.2 Scoped reconciliation (reconcile_on_confirm, reconcile_on_merge, reconcile_on_split)
  - [ ] E.3 Background task integration with FastAPI BackgroundTasks
  - [ ] E.4 Tests for reconciliation logic
- [ ] Slice F: Auto-Tuning Framework
  - [ ] F.1 Feedback collection (FeedbackMetrics, AutoTuner class)
  - [ ] F.2 Per-tenant auto-tuners with registry
  - [ ] F.3 Wire auto-tuner to API endpoints (confirm/reject/merge/split)
  - [ ] F.4 Tests for auto-tuning logic
- [ ] Slice G: Color Histogram Sessions
  - [ ] G.1 Scene signature extraction (HSV histograms, dominant colors)
  - [ ] G.2 Session grouping utility
  - [ ] G.3 Session boost integration with similarity calculation
  - [ ] G.4 Tests for session detection

### Weekly Goals

**Week 1**:

- [x] Metrics infrastructure (1.1-1.5 complete)
- [x] Confidence weighting (A.1-A.4 complete)
- [x] Extended vectors (B.1-B.4 complete)

**Week 2**:

- [x] Configurable thresholds (C.1-C.4 complete)
- [ ] Deterministic CW + HDBSCAN (D.1-D.4)

**Week 3**:

- [ ] In-session reconciliation (E.1-E.4)
- [ ] Auto-tuning framework (F.1-F.4)
- [ ] Color histogram sessions (G.1-G.4) [if time permits]

---

## Appendix: File Index

| Slice            | Files to Create/Modify                                                                                                                                                                                           | Status  |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| Metrics          | `recognition/application/metrics.py` ✅, `recognition/application/clustering/clustering_logger.py` ✅, `recognition/interface_adapters/http/metrics_router.py` ✅                                                | Done    |
| Option C         | `recognition/application/representatives/confidence_utils.py` ✅, `recognition/application/representatives/representative_matcher.py` ✅, `recognition/application/clustering/identity_clustering_service.py` ✅ | Done    |
| Extended Vectors | `recognition/domain/embeddings/layout.py` ✅, `recognition/domain/embeddings/builder.py` ✅, `recognition/infrastructure/embedding_provider.py` ✅                                                               | Done    |
| Config           | `recognition/application/clustering/clustering_settings.py` ✅, `recognition/infrastructure/config_repository.py` ✅, `recognition/interface_adapters/http/config_router.py` ✅, `db/models.py` ✅               | Done    |
| CW + HDBSCAN     | `recognition/application/clustering/chinese_whispers.py`, `recognition/application/clustering/hdbscan_clustering.py`, `recognition/application/clustering/hybrid_clustering.py`                                  | Pending |
| Reconciliation   | `recognition/application/reconciliation.py`, `api/routes/cluster_router.py`                                                                                                                                      | Pending |
| Auto-Tune        | `recognition/application/auto_tuning.py`                                                                                                                                                                         | Pending |
| Sessions         | `recognition/application/scene_signature.py`                                                                                                                                                                     | Pending |

### Test Files Created

| Test File                                     | Coverage                                                                                            |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `recognition/tests/test_confidence_utils.py`  | 19 tests covering confidence calculation, adaptive threshold, and RepresentativeMatcher integration |
| `recognition/tests/test_metrics.py`           | 10 tests covering ClusteringMetrics dataclass, snapshots, and comparison                            |
| `recognition/tests/test_clustering_logger.py` | 18 tests covering structured logging events and helper functions                                    |
| `recognition/tests/test_metrics_router.py`    | 4 tests covering metrics API endpoint                                                               |
| `recognition/tests/test_embedding_builder.py` | 11 tests covering extended embedding builder (backward compat tests removed)                        |
| `recognition/tests/test_config_repository.py` | 11 tests covering config repository CRUD operations                                                 |
| `recognition/tests/test_config_endpoints.py`  | 14 tests covering config API endpoints (GET/PATCH/DELETE)                                           |

### Scripts Created

| Script                                | Purpose                                                         |
| ------------------------------------- | --------------------------------------------------------------- |
| `scripts/collect_baseline_metrics.py` | Collect and save baseline clustering metrics for A/B comparison |
