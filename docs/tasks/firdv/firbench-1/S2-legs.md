# S2 · In-process legs, arms, contract-keyed cache, per-face search records

- **Wave:** W3 batch B · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_legs.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_legs.py`

## Goal

Run detect → align → embed → search for each leg on identical image bytes, and record where every GT face ended. SFace-128 and AuraFace-512 share YuNet and the five-point aligner, so the embedder is the contrast. InsightFace buffalo_l is the judge-side reference. Each leg is its own embedding space (EMB-01), and a contract change invalidates its cache (IDX-02).

## Read first (bounded reads only)

- README shared names, `FaceSearchRecord` fields, run-artifact layout
- `recognition/infrastructure/embeddings/face_pipeline_adapter.py`:
  - `sface_embedding_model_manifest()` (line ~315), `auraface_embedding_model_manifest()` (~339)
  - `FacePipelineRuntime` (~295), `get_shared_face_pipeline_runtime` (~640), `FacePipelineFaceDetector` (~762), `decode_image_bytes`, `xywh_to_corner_bbox`
  - Read `sed -n '280,420p;640,800p'`; do not cat the file.
- `scripts/eval_harness/buffalo_bench.py`: `BuffaloFusedLeg`, `build_baseline_leg`, `process_image_bgr_buffalo`, `l2_normalize`
- `scripts/eval_harness/landmark_cache.py`: `build_landmark_cache`, `LandmarkCache`, `LandmarkCacheProvenance`. These give the `ref_landmarks` arm its fixed reference landmarks.
- `scripts/eval_harness/face_metrics.py`: `detection_pr_strict` (~782) and `scripts/eval_harness/face_assignment.py` `associate_detections`. Reuse their one-to-one IoU ≥ 0.50 matching; do not write a new matcher.
- W2 inventory § "Leg pins" for model paths, weight sha256, OpenCV/ORT versions on the VM

## Build

1. `LegRuntime` Protocol with `detect(image_bgr)`, `align(image_bgr, landmarks)`, `embed(aligned) -> np.ndarray`, plus `leg_id(arm) -> LegId`. Adapters:
   - `FacePipelineLeg(kind=sface|auraface)` over the face_pipeline runtime
   - `BuffaloLeg` over `buffalo_bench`
   - `CanaryLeg(base, permute_fraction, seed)`: wraps a leg and permutes that fraction of gallery template labels. Its `LegId.kind` is `canary`.
2. Arms:
   - `native`: the leg's own detections
   - `oracle_box`: run the leg's detector on the GT box crop with margin, take the detection with the highest IoU to the GT box
   - `ref_landmarks`: align with landmarks from the frozen `LandmarkCache`. The arm is "unavailable" for faces that have no cached landmark, and records that rather than falling back.
3. `space_fingerprint`: sha256 over the model manifest (weights sha, input size, normalization, preprocessing parameters, metric). Together with the OpenCV and ORT versions read at runtime, it forms `LegId`.
4. Cache:
   - Stored at `legs/<leg_key>/cache.npz`, keyed per image sha.
   - A miss is any change to `LegId.key()` or image sha. A key mismatch on read raises `RuntimeMismatchError`; it never silently recomputes into the same file.
5. Search:
   - Per leg and fold, enrol gallery templates from the S1 gallery split.
   - Compute cosine top-k inside that leg's space only, and emit `FaceSearchRecord` rows to `searches.jsonl`.
   - Mated and non-mated faces both search.
   - Detector false alarms (unmatched detections) are written to a separate `detector_unmatched.jsonl` and never become searches (EVAL-19).
6. Ledger: one row per (GT face, leg, arm). `stage_reached` is `missed`, `unaligned` or embedded. S3 finishes the outcome.
7. `compare_guard(leg_a, leg_b)` raises `CrossSpaceComparisonError` for any vector-level operation across different `space_fingerprint`s, and `RuntimeMismatchError` for differing OpenCV/ORT versions within one leg kind.

## RED tests (fakes only; no model weights in tests)

- A fake runtime with deterministic embeddings yields one ledger row per GT face per leg per arm. A GT face with no matching detection is `missed`.
- Changing the fake's preprocessing parameter changes `LegId.key()` and causes a cache miss. A corrupted key raises `RuntimeMismatchError`.
- Vector comparison across two fingerprints raises `CrossSpaceComparisonError`.
- Unmatched detections never appear in `searches.jsonl`.
- `ref_landmarks` marks faces without cached landmarks as unavailable.
- `CanaryLeg` permutes exactly ⌊fraction·n⌋ gallery labels, and is reproducible from its seed.
- Two runs on the same inputs produce byte-identical `searches.jsonl`.

## VM smoke (in the lane, after GREEN)

Run the three real legs on 5 synthetic numpy faces, or on 3 images from the VM corpus path that the W2 inventory names. Report the leg keys and runtime versions. Do not commit outputs.

## Done when

Tests pass on the VM and the smoke is reported. Owns AE-8 and parts of AE-7 and AE-9.

## Out of scope

Threshold choice and acceptance (S3); changing the detector; stack mode.
