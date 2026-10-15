# S2 · In-process legs, arms, contract-keyed cache, per-face search records

- **Wave:** W3 batch B · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_legs.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_legs.py`

## Goal

Run detect → align → embed → search for each leg on identical image bytes, and record where every GT face ended. SFace-128 and AuraFace-512 share the YuNet detector. Each uses its own model-compatible five-point alignment, so the native comparison is between model-compatible pipelines, not identical aligned pixels. InsightFace buffalo_l is the judge-side reference, and it is fused: it has no separable alignment stage. Each leg is its own embedding space (EMB-01), and a contract change invalidates its cache (IDX-02).

## Read first (bounded reads only)

- README shared names, `FaceSearchRecord` fields, non-mated source unit, run-artifact layout
- `recognition/infrastructure/embeddings/face_pipeline_adapter.py`:
  - `sface_embedding_model_manifest()` (line ~315), `auraface_embedding_model_manifest()` (~339)
  - `FacePipelineRuntime` (~295), `FacePipelineFaceDetector` (~762), `decode_image_bytes`, `xywh_to_corner_bbox`
  - `assert_three_way_embedding_dimensions` (~402) and `_load_face_pipeline_runtime` (~605): production guards, read only
  - `get_shared_face_pipeline_runtime` (~640) reads the global dimensions and is not used to build legs (Build 1)
  - Read `sed -n '280,420p;640,800p'`; do not cat the file.
- `scripts/eval_harness/buffalo_bench.py`: `BuffaloFusedLeg`, `process_image_bgr_buffalo`, `l2_normalize`. `build_baseline_leg` returns a placeholder aligner, which this brief does not use.
- `scripts/eval_harness/landmark_cache.py`: `build_landmark_cache`, `LandmarkCache`, `LandmarkCacheProvenance`. The cache holds pinned YuNet candidate-family landmarks for named matched faces. They are reference landmarks, not independent alignment truth.
- `scripts/eval_harness/face_metrics.py`: `detection_pr_strict` (~782) and `scripts/eval_harness/face_assignment.py` `associate_detections`. Reuse their one-to-one IoU ≥ 0.50 matching; do not write a new matcher.
- W2 inventory § "Leg pins" for model paths, weight sha256, OpenCV/ORT versions on the VM

## Build

1. `LegRuntime` Protocol with `detect(image_bgr)`, `align(image_bgr, landmarks)`, `embed(aligned) -> np.ndarray`, plus `leg_id(arm) -> LegId`. Adapters:
   - `FacePipelineLeg(kind=sface|auraface)`: built by an offline factory in `firbench_legs.py` from the pinned manifest (`sface_embedding_model_manifest()` or `auraface_embedding_model_manifest()`). Each leg gets its own pinned YuNet detector, a model-compatible five-point aligner and its own embedder. The factory does not call `get_shared_face_pipeline_runtime` and does not read the global pgvector or identity-embedding dimensions. Each leg checks only its own manifest dimension against its own embedder output. The production guard `assert_three_way_embedding_dimensions` stays unchanged, and the bench does not call it. If the factory cannot reuse the pinned pieces, stop and request a named upstream seam before dispatch. Do not bypass the guard.
   - `BuffaloLeg` (`leg_mode="fused"`): `detect`, `align` and `embed` are one `process_image_bgr_buffalo` call. The Protocol is satisfied by a single fused method. `stage_reached` for this leg is `missed`, `detected` or `embedded` only. Its alignment is internal to insightface and is recorded as `align_source = "fused_internal"` on each row. It is never recorded as `unaligned`.
   - `CanaryLeg(base, canary_identities, seed)`: wraps a leg. `canary_identities` is the declared set S (Build 2). Its `LegId.kind` is `canary`.
2. Arms. Arm names are the README `Arm` members.
   - `native`: the leg's own detections.
   - `gt_crop_redetect`: run the leg's detector on the GT box crop with margin, and take the detection with the highest IoU to the GT box. This changes crop scale, context and landmarks together. It is not a localization-only intervention.
   - `cached_yunet_landmark_replay`: align with landmarks from the frozen `LandmarkCache`. A face with no cached landmark records `unavailable` and does not fall back to other landmarks.
   - The two attribution arms apply to `sface` and `auraface` only. For `insightface` both arms record `unavailable_fused` per face and are excluded from the attribution comparison. The two arms score non-mated GT faces and mated faces only. They create no background units, and they never report FPIR. The verdict uses the native arm only.
   - Canary (`CanaryLeg`). `canary_identities` is a declared set S of k ≥ 2 gallery identities. Declare S in the run manifest before any leg runs. Each identity in S has at least one mated probe that the frozen baseline run accepts; that accepted set is fixed before the canary run. A seeded derangement relabels the gallery templates of S, so every selected label changes. Record the expected changed search ids (the accepted mated probes of S). Raise `CanaryConfigError` if k < 2 or if any selected label is fixed by the permutation. The same seed gives the same derangement.
3. `space_fingerprint`: sha256 over the model manifest (weights sha, input size, normalization, preprocessing parameters, metric). Together with the OpenCV and ORT versions read at runtime, it forms `LegId`.
4. Cache:
   - Stored at `legs/<leg_key>/cache.npz`, keyed per image sha.
   - A miss is any change to `LegId.key()` or image sha. A key mismatch on read raises `RuntimeMismatchError`; it never silently recomputes into the same file.
   - Per-leg wall times and per-face milliseconds go to `timings.json` (written by S6a). They never go into `cache.npz` or `searches.jsonl`.
5. Search:
   - Per leg and rotation, enrol each fold's gallery from the S1 gallery split. Record its `gallery_sha256`. `gallery_split` gives G1 and G2, not fit or test roles; roles come from `Frame.identity_fold` (S1 Build 8). For each top-k identity, record its fold.
   - Compute cosine top-k inside that leg's space only, and emit `FaceSearchRecord` rows to `searches.jsonl`.
   - Mated and non-mated GT faces both search.
   - For the native arm only, every detection that overlaps no GT face is a background detection of its image's background unit. It is searched like any other detection, and its record carries `unit_id = background:<image_id>` (README). It is written to `searches.jsonl`. There is no separate file for detector output.
   - Every detection in a source unit is scored as an outcome of that unit (S3). A detector false alarm whose top-k name clears the threshold is a false accept of its source unit.
   - Duplicate detections over a mated GT face, which are not its one-to-one match, are written to `searches.jsonl` with `unit_id` None and are scored only as additional spurious names (S3 Build 2). This interim rule is an open question in the task plan.
6. Ledger: one row per (GT face, leg, arm). `stage_reached` is a `LedgerStage`: separable legs write `missed`, `unaligned` or `embedded`; the fused leg writes `missed`, `detected` or `embedded`. S3 finishes the outcome. The ledger has no background rows.
7. `compare_guard(leg_a, leg_b)` raises `CrossSpaceComparisonError` for any vector-level operation across different `space_fingerprint`s, and `RuntimeMismatchError` for differing OpenCV/ORT versions within one leg kind.

## RED tests (fakes only; no model weights in tests)

- A fake runtime with deterministic embeddings yields one ledger row per GT face per leg per arm. A GT face with no matching detection is `missed`.
- The factory builds a 128-dim leg and a 512-dim leg in one process from fake pinned manifests. Each leg checks only its own dimension; no global dimension is read.
- Changing the fake's preprocessing parameter changes `LegId.key()` and causes a cache miss. A corrupted key raises `RuntimeMismatchError`.
- Vector comparison across two fingerprints raises `CrossSpaceComparisonError`.
- A native-arm detection that overlaps no GT face appears in `searches.jsonl` with `unit_id = background:<image_id>`, and it is searched.
- A duplicate detection over a mated face appears with `unit_id` None and is not a background unit.
- `cached_yunet_landmark_replay` marks faces without cached landmarks `unavailable`, and does not fall back.
- The fused leg emits no `unaligned` rows, records `align_source = "fused_internal"`, and both attribution arms record `unavailable_fused`.
- `CanaryLeg` with k ≥ 2 relabels every selected identity, and is reproducible from its seed. A permutation that leaves a selected label fixed, or k < 2, raises `CanaryConfigError`.
- Two runs on the same inputs produce byte-identical `searches.jsonl`.

## VM smoke (in the lane, after GREEN)

Run the three real legs on 5 synthetic numpy faces, or on 3 images from the VM corpus path that the W2 inventory names. Report the leg keys and runtime versions. Do not commit outputs.

## Done when

Tests pass on the VM and the smoke is reported. Owns AE-8 and parts of AE-7 and AE-9.

## Out of scope

Threshold choice and acceptance (S3); changing the detector; stack mode; a buffalo recognizer seam; an independent landmark or region alignment intervention (a later task).
