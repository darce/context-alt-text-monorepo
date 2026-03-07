# Recognition Pipeline Insights vs. Apple

## Scope

Reviewed:

- `apps/prototype-description-service/recognition/application/__init__.py`
- the recognition application and infrastructure under `apps/prototype-description-service/recognition/`
- Apple literature extracts in `docs/literature/extracted/recognition/apple/`

Primary local literature used:

- `Recognizing People in Photos Through Private On-Device Machine Learning - Apple Machine Learning Research.txt`
- `ArcFace--Additive-Angular-Margin-Loss-for-Deep-Face-Recognition.txt`
- `CurricularFace--Adaptive-Curriculum-Learning-Loss-for-Deep-Face-Recognition.txt`
- `AirFace--Lightweight-and-Efficient-Model-for-Face-Recognition.txt`
- `Searching-for-MobileNetV3.txt`
- `Squeeze-and-Excitation Networks.txt`
- `Learning-Feature-Representations-with-K-means.txt`

## Current Pipeline Summary

The current recognition stack is already better than a naive face-clustering pipeline in a few ways:

- incremental clustering rather than full rebuilds
- multi-stage discovery: representatives, centroids, then graph clustering
- adaptive assignment thresholds with maturity and curriculum bias
- representative diversity logic, including pose coverage
- optional HAC refinement after graph discovery

The biggest gap relative to Apple is not "one missing threshold." It is that Apple’s system is built around richer evidence and stricter gallery curation:

- face plus upper-body evidence
- moment-local context
- explicit filtering of unclear / OOD observations
- exemplar-set gallery assignment rather than nearest-match assignment
- conservative clustering first, then recall-oriented growth
- model training and fairness work that are tightly coupled to deployment

This codebase is still mostly a face-only embedding and cosine-similarity pipeline with some good operational heuristics layered on top.

## Highest-Value Improvements

### 1. Add multimodal person observations instead of face-only matching

Apple’s biggest product-level gain appears to come from combining face and upper-body evidence, with body cues used carefully inside short-lived temporal or "moment" windows.

Current bottleneck:

- `recognition/shared/similarity.py` truncates larger embeddings to the first 512 dimensions.
- `recognition/domain/identity.py` exposes `face_vector` and most downstream discovery code consumes only that face vector.

Recommended direction:

- represent each observation as separate channels:
  - face embedding
  - upper-body embedding
  - moment/context features
- do not collapse them into one similarity too early
- score them conditionally:
  - cross-moment matching should rely mostly on face
  - within-moment matching can borrow body/clothing evidence
- persist moment-local metadata such as:
  - capture timestamp bucket
  - coarse location bucket
  - photo burst / event grouping

Practical implication: the current "extended embedding" seam is only nominal. The stack still behaves as face-only.

### 2. Replace nearest-match assignment with exemplar-set scoring

Apple explicitly describes gallery assignment with canonical exemplars and sparse-code energy, not just centroid or nearest-neighbor matching.

Current bottleneck:

- `recognition/application/discovery/representative.py` picks a single best cluster by max similarity.
- `recognition/application/similarity/search.py` returns best-match results by raw similarity.
- `recognition/application/discovery/graph/helpers.py` reduces groups and anchors to simple mean vectors.

Recommended direction:

- store multiple canonical exemplars per cluster, not just representatives for coverage
- score a candidate against a cluster using:
  - top-k exemplar similarities
  - exemplar diversity buckets
  - cluster reliability / maturity
  - ambiguity margin to the runner-up cluster
- auto-assign only when:
  - aggregate evidence is strong
  - the winner is clearly separated from the runner-up

This should reduce brittle behavior when a person has multiple appearance modes, strong pose variation, or a nearby lookalike cluster.

### 3. Make clustering more conservative early, then grow clusters in a second pass

Apple’s write-up is clear: the first pass is tuned for high precision, then a second HAC pass grows recall across moment boundaries.

Current bottleneck:

- the graph path still relies on HDBSCAN plus mean-based anchor matching
- `recognition/infrastructure/clustering/hdbscan_adapter.py` uses basic HDBSCAN with Euclidean distance
- `recognition/application/discovery/graph/helpers.py` uses centroid/mean-style reductions

Recommended direction:

- split clustering into explicit phases:
  1. conservative local clustering
     - same or nearby moment only
     - allow body/context evidence
     - high precision threshold
  2. cross-moment expansion
     - face-only or face-dominant
     - cluster-to-cluster distance, not point-to-centroid only
     - median-linkage or robust sampled linkage, not simple means
- use cluster uncertainty to prevent bridge merges
- require stronger evidence when joining two already-nontrivial clusters than when attaching a singleton

This is likely a better fit than continuing to tune HDBSCAN parameters around a face-only embedding space.

### 4. Add a real unclear-face / OOD filter before gallery pollution

Apple treats false positives and out-of-distribution observations as a first-class failure mode and mentions a dedicated embedding-confidence branch.

Current bottleneck:

- `recognition/application/assignment/quality.py` uses only:
  - detection confidence
  - pose
  - face size
- `recognition/application/embedding/detector.py` converts those into one quality score
- there is no explicit embedding-confidence or OOD head

Recommended direction:

- add an uncertainty score trained to detect:
  - non-faces
  - extreme blur
  - heavy occlusion
  - out-of-domain crops
  - poor landmark geometry
- keep low-confidence observations out of:
  - cluster formation
  - gallery promotion
  - automatic assignments
- allow them only in manual-review or weak-evidence buckets

This is one of the clearest direct opportunities to improve overall system accuracy.

### 5. Separate "all clusters" from the "gallery of known people"

Apple does not treat every cluster as a known person. The gallery is curated from recurring, reliable individuals using cluster size and distance heuristics plus user feedback.

Current bottleneck:

- the stack clusters identities, but the documented "known people gallery" concept is weak
- auto-assignment is mostly tied to cluster maturity rather than explicit gallery admission

Recommended direction:

- add a gallery promotion layer driven by:
  - cluster recurrence across moments
  - minimum cluster size
  - pose coverage
  - inter/intra-cluster separation
  - user confirmation or label confidence
- only gallery clusters should be eligible for aggressive online assignment
- non-gallery clusters should stay conservative and suggestion-heavy

This should reduce false positives for one-off or unstable clusters.

### 6. Improve the embedding model and training recipe, not just the clustering logic

Apple’s paper points to gains from:

- margin-based classification losses
- curriculum-style mining
- lightweight attention-enabled mobile backbones
- strong augmentation
- explicit fairness work

Recommended model roadmap:

- evaluate a stronger face embedding model trained with:
  - ArcFace or sub-center ArcFace
  - CurricularFace-style hard-sample curriculum
- evaluate mobile backbones closer to:
  - AirFace
  - MobileNetV3 variants
  - SE-augmented bottlenecks
- use a training recipe closer to:
  - AdamW
  - one-cycle LR or similarly disciplined schedule
  - stronger augmentation including blur, compression, occlusion, synthetic masks

This matters because the current clustering logic can only recover so much if the embedding geometry is weak.

### 7. Add fairness and failure-analysis instrumentation

Apple explicitly treats fairness as a development constraint, not a post-hoc report.

Recommended direction:

- benchmark accuracy by:
  - skin tone
  - age
  - gender presentation
  - occlusion class
  - pose bucket
- track both:
  - assignment errors
  - cluster fragmentation / cluster collapse
- keep a regression harness for:
  - false merges
  - missed merges
  - OOD pollution
  - duplicate or near-duplicate media

Without this, tuning will drift toward the easiest subsets.

## Concrete Code Hotspots

These are the most obvious leverage points for follow-up implementation.

### Face-only choke points

- `apps/prototype-description-service/recognition/shared/similarity.py`
- `apps/prototype-description-service/recognition/domain/identity.py`

These currently guarantee that anything beyond the first 512 face dimensions is ignored for similarity and discovery.

### Brittle assignment scoring

- `apps/prototype-description-service/recognition/application/discovery/representative.py`
- `apps/prototype-description-service/recognition/application/similarity/search.py`

These should move from max similarity to richer exemplar-set or energy-based scoring.

### Weak unclear-face rejection

- `apps/prototype-description-service/recognition/application/assignment/quality.py`
- `apps/prototype-description-service/recognition/application/embedding/detector.py`

These should be extended with explicit uncertainty / OOD scoring.

### Mean-based cluster matching

- `apps/prototype-description-service/recognition/application/discovery/graph/helpers.py`
- `apps/prototype-description-service/recognition/infrastructure/clustering/hdbscan_adapter.py`

These should evolve toward more conservative local clustering plus robust cluster-linkage growth.

### Detection and embedding architecture seam

- `apps/prototype-description-service/recognition/infrastructure/embeddings/__init__.py`

This is the place to widen the observation model beyond face-only InsightFace outputs.

## Upper-Body Embedding Stack

If the requirement is deterministic inference, the most practical choice is:

- OpenCV for person / torso crop extraction and geometric normalization
- ONNX Runtime on CPU for the upper-body embedding model
- a frozen person-ReID backbone such as OSNet or a FastReID / Torchreid-exported model

Why this stack:

- deterministic CPU inference is easier to control than PyTorch GPU inference
- OpenCV already fits the current Python service shape for crop handling
- ReID models are a better starting point than generic image encoders because they are trained to separate individuals under clothing, pose, and viewpoint change

Recommended pattern:

- keep face embeddings and upper-body embeddings as separate vectors
- do not concatenate them and immediately feed them into the existing face-only similarity path
- gate upper-body usage by moment-local constraints and confidence

Avoid as a first choice:

- CLIP-style general image embeddings as the main body signal
- body embeddings used across long time gaps with no contextual constraints
- GPU-only inference paths if reproducibility matters more than raw throughput

## Depth Mapping

Depth can help, but it should be treated as an auxiliary cue, not a primary identity signal.

Where depth helps:

- better person / torso segmentation
- cleaner crop extraction under cluttered backgrounds
- occlusion reasoning
- foreground weighting when building upper-body embeddings
- separating nearby people in the same frame

Where depth does not help much:

- long-range identity matching across unrelated moments
- person identity by itself when clothing and pose have changed
- pipelines using only monocular estimated depth with no confidence gating

Recommendation:

- use depth first as a crop-quality and masking aid
- if the media source contains real depth data, use that before predicted monocular depth
- do not add depth as a first-class similarity channel until face, body, and uncertainty work are already stable

Priority:

- real depth or portrait-depth metadata: useful
- monocular depth prediction: maybe useful, but phase-later

## Files To Touch

### Phase 1: Uncertainty and observation quality

- `apps/prototype-description-service/recognition/application/assignment/quality.py`
- `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py`
- `apps/prototype-description-service/recognition/application/embedding/detector.py`
- `apps/prototype-description-service/recognition/application/scan/service.py`
- `apps/prototype-description-service/recognition/tests/unit/test_identity_quality.py`
- `apps/prototype-description-service/recognition/tests/integration/test_scan_service_pose_quality.py`

### Phase 2: Multimodal observation model

- `apps/prototype-description-service/recognition/domain/identity.py`
- `apps/prototype-description-service/db/models/identity.py`
- `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`
- `apps/prototype-description-service/recognition/shared/similarity.py`
- `apps/prototype-description-service/recognition/application/scan/service.py`
- `apps/prototype-description-service/recognition/infrastructure/embeddings/__init__.py`
- add migration files for new media identity columns if body or depth vectors are persisted

### Phase 3: Exemplar-set assignment

- `apps/prototype-description-service/recognition/application/discovery/representative.py`
- `apps/prototype-description-service/recognition/application/similarity/search.py`
- `apps/prototype-description-service/recognition/application/assignment/candidate.py`
- `apps/prototype-description-service/recognition/application/assignment/gate.py`
- `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py`
- `apps/prototype-description-service/recognition/tests/unit/test_representative_discovery.py`

### Phase 4: Conservative-first clustering and cluster growth

- `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py`
- `apps/prototype-description-service/recognition/application/discovery/graph/discovery.py`
- `apps/prototype-description-service/recognition/application/discovery/graph/helpers.py`
- `apps/prototype-description-service/recognition/infrastructure/clustering/hdbscan_adapter.py`
- `apps/prototype-description-service/recognition/application/settings/clustering.py`
- `apps/prototype-description-service/recognition/tests/unit/test_graph_discovery.py`
- `apps/prototype-description-service/recognition/tests/unit/test_hac_refinement.py`

### Phase 5: Gallery promotion and assignment policy

- `apps/prototype-description-service/recognition/domain/maturity.py`
- `apps/prototype-description-service/recognition/application/settings/clustering.py`
- `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py`
- `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`
- `apps/prototype-description-service/recognition/application/suggestions/service.py`
- regression-harness reporting files under `apps/prototype-description-service/recognition/application/regression_harness/`

### Phase 6: Evaluation and fairness instrumentation

- regression harness builders and reports under `apps/prototype-description-service/recognition/application/regression_harness/`
- observability and event logging under `apps/prototype-description-service/recognition/observability/`
- targeted tests in `apps/prototype-description-service/recognition/tests/integration/`

## Patterns To Follow

### Keep modalities separate until late scoring

Do:

- store `face_embedding`, `body_embedding`, and optional `depth_mask_signal` separately
- combine scores with explicit rules

Do not:

- hide multimodal behavior inside one overloaded `embedding` without naming the channels

### Preserve the face-only baseline path

Do:

- keep face-only matching as a fallback
- add feature-gated multimodal scoring

Do not:

- replace the current pipeline in one flag day

### Additive seams, not cross-cutting rewrites

Do:

- introduce new helpers beside existing ones
- migrate call sites phase by phase

Do not:

- break every repository and test fixture at once

### Use settings-driven rollout

Do:

- add explicit settings toggles for body evidence, exemplar scoring, uncertainty filtering, and depth masking
- make every new stage measurable

Do not:

- rely on implicit behavior changes hidden behind existing thresholds

### Favor conservative auto-assignment

Do:

- send ambiguous multimodal results to suggestion flow
- require stronger evidence for cluster-to-cluster merges than singleton attachments

Do not:

- use body or depth cues to force aggressive cross-moment assignments early

### Extend tests at each seam

Do:

- add unit tests for each new scoring rule
- add integration tests for persistence and clustering transitions

Do not:

- depend on only end-to-end clustering snapshots to validate behavior

## Encapsulated Phases

### Phase 0: Measurement baseline

Goal:

- lock in current false-merge, false-split, suggestion, and OOD baselines

Deliverables:

- regression report for representative, centroid, graph, and HAC paths
- known hard cases catalog

### Phase 1: Unclear-face and OOD guardrail

Goal:

- stop bad observations from polluting clusters

Deliverables:

- uncertainty score
- new gate behavior for low-confidence observations
- tests proving low-quality detections do not enter the same path as clean observations

### Phase 2: Multimodal observation seam

Goal:

- persist and expose face plus body evidence without changing assignment policy yet

Deliverables:

- new domain fields
- repository and ORM support
- optional body embedding generation path

### Phase 3: Exemplar-set assignment

Goal:

- improve cluster assignment without changing cluster construction yet

Deliverables:

- canonical exemplar selection
- top-k or weighted exemplar scoring
- ambiguity-margin fallback to suggestion flow

### Phase 4: Conservative-first clustering

Goal:

- reduce bridge errors and over-merges

Deliverables:

- same-moment or nearby-moment local clustering stage
- stronger cross-moment growth stage
- robust cluster linkage metrics

### Phase 5: Gallery promotion

Goal:

- separate raw clusters from assignable known-person gallery

Deliverables:

- gallery admission rules
- gallery-only aggressive assignment
- non-gallery conservative behavior

### Phase 6: Depth-assisted crop quality

Goal:

- use depth only where it clearly improves segmentation and crop quality

Deliverables:

- optional foreground mask path
- benchmark showing whether depth improves body embeddings or disambiguation

### Phase 7: Training and fairness upgrades

Goal:

- lift embedding quality and monitor subgroup regressions

Deliverables:

- stronger face model evaluation
- fairness dashboard slices
- augmentation and training recipe experiments

## Consolidated Checklist

- [ ] Capture baseline regression-harness metrics before changing scoring.
- [ ] Add explicit low-quality / OOD handling separate from pose-size-confidence heuristics.
- [ ] Decide whether uncertainty is heuristic-only or model-backed.
- [ ] Add body-observation schema fields or a new observation table.
- [ ] Keep face and body embeddings separate in domain and persistence models.
- [ ] Add deterministic torso crop extraction and normalization.
- [ ] Integrate a deterministic ReID-style body embedding model behind a feature flag.
- [ ] Add moment-local metadata needed to gate body evidence.
- [ ] Add exemplar-selection logic distinct from representative thumbnail logic.
- [ ] Replace best-match representative assignment with weighted exemplar scoring.
- [ ] Add runner-up margin checks before auto-assignment.
- [ ] Route ambiguous multimodal results to suggestion flow.
- [ ] Split clustering into local high-precision clustering and cross-moment expansion.
- [ ] Replace mean-based cluster matching with more robust cluster linkage.
- [ ] Add gallery promotion heuristics distinct from cluster maturity.
- [ ] Restrict aggressive auto-assignment to gallery-eligible clusters.
- [ ] Benchmark whether real depth data improves crop masks or person separation.
- [ ] Defer monocular depth similarity features unless masking gains are proven.
- [ ] Add subgroup-oriented fairness and failure-analysis reports.
- [ ] Re-run regression harness after every phase and block rollout on false-merge regressions.

## Recommended Order

If the goal is highest product accuracy per unit effort, the order should be:

1. Add uncertainty / unclear-face filtering.
2. Add gallery admission heuristics separate from raw clusters.
3. Move assignment to exemplar-set scoring with ambiguity margins.
4. Add multimodal face + upper-body + moment-local evidence.
5. Rework clustering into conservative local pass plus cross-moment HAC growth.
6. Upgrade the embedding model and training recipe.
7. Formalize fairness and failure-analysis benchmarks.

## Bottom Line

To mimic Apple’s success, this project should stop thinking of recognition as "better thresholds on face cosine similarity" and instead treat it as a layered system:

- richer observations
- stricter uncertainty filtering
- curated gallery promotion
- exemplar-based assignment
- conservative-first clustering
- stronger embedding training
- optional depth-assisted crop quality

The current codebase already has enough structure to support that transition, but it is still operating on a much narrower evidence model than the one Apple describes.
