# FIR-4 S1+S2 adversarial code review (grok / fir-4-grok)

**Subject:** `59972be7` (S1 ORT bump) + `4e7ca6ed` (S2 bridge) on `feature/fir-4`  
**Contract:** `docs/tasks/fir/FIR-4-runtime-integration-task-plan.md` Constraints + S1/S2 checklists  
**Role:** adversarial CODE reviewer (independent; did not author this code)  
**HEAD at review:** `4e7ca6ed68a8ce7458cf82de91546b30dbce660e`

## VERDICT: pass_with_findings

S1 is clean (pyproject+lock floor only). S2 implements the one-pass bridge, decode parity with the real incumbent helpers, dedicated executor + breaker + wait_for_adapter, process singleton with failed-load cache, three-way dim guard at load/construct, load-time profile validation, and MODEL_MANIFEST-derived `opencv-sface@128d/l2/cosine`. Residual findings are seam-parity gaps (phash/quality), golden-fixture discipline, sticky Unavailable for config-class errors, and thin coverage of timeout/breaker/zero-norm paths — not structural contract breakage.

### Test evidence (this session)

```text
cd apps/prototype-description-service && uv run pytest recognition/tests/unit/test_face_pipeline_adapter.py -q -rs
→ 17 passed in 0.80s, exit 0
```

(Models present on this machine → models-present E2E + atomicity tests executed, not skipped.)

---

## Findings

### S2R-01 — medium

**File:line:** `apps/prototype-description-service/recognition/infrastructure/embeddings/face_pipeline_adapter.py:323-334`  
**Heuristic:** SERVE-08, PROV-06  
**Failure scenario:** Incumbent `InsightFaceFaceDetector.detect` (`detector.py:241-273`) always stamps `image_phash` and `landmark_quality` (quality from confidence+pose+bbox). `FacePipelineFaceDetector` emits only bbox/confidence/embedding/model_id/pose=None. When S3 wires this detector into `ScanService._persist_identities` (`scan/service.py:323-354`), every face_pipeline row gets `quality_score=None` and `image_phash=None` — quality scoring, phash-based de-dupe, and export/clustering fields that depend on those columns stay empty even though confidence and corner bbox are available (quality can be computed with pose=None).

**Fix:** Mirror incumbent post-processing: compute phash from source bytes (off-loop or inside `_detect_sync`) and set `landmark_quality` via the same `_compute_detection_quality` path; leave pose=None as documented pose non-parity.

---

### S2R-02 — medium

**File:line:** `apps/prototype-description-service/recognition/tests/unit/test_face_pipeline_adapter.py:48-55,178-202`  
**Heuristic:** SERVE-08, TEST-06  
**Failure scenario:** Plan requires a bytes→array golden generated from the incumbent helper. The test defines `_incumbent_decode` as a **local reimplementation** of `_bytes_to_cv2`/`_pil_to_cv2` and compares `decode_image_bytes` against it. A coordinated edit of both the bridge and the test helper (or a future change only to `InsightFaceAdapter._pil_to_cv2`) keeps the test green while production decode drifts from the true incumbent. No committed fixture bytes/hash pins the transform.

**Fix:** Generate once from `InsightFaceAdapter._bytes_to_cv2` (or call the real method in the test), commit deterministic input bytes + expected array hash/array; assert bridge output against that fixture — not a duplicated inline decoder.

---

### S2R-03 — medium

**File:line:** `apps/prototype-description-service/recognition/infrastructure/embeddings/face_pipeline_adapter.py:153-161,238-244`  
**Heuristic:** RES-04, RLSE-05  
**Failure scenario:** Any load exception (including three-way dim mismatch, missing models, transient IO) is sticky-cached as `FacePipelineRuntimeUnavailableError` keyed only by `(profile, models_dir, score, nms, top_k)`. Dimensions are not in the key. Operator sets `RECOGNITION_EMBEDDING_DIMENSION=128` + `PGVECTOR_DIM=128` after a first failed activation (or fetches models after first miss) without process restart → still raises the **stale** cached Unavailable; no recovery without `reset_shared_face_pipeline_runtime_for_tests` or process recycle. Fine for anti-retry-storm on bad model bytes; wrong for config-correctable first-boot races in long-lived API/worker processes.

**Fix:** Either (a) include dim snapshot in the cache key and re-attempt when dims change, or (b) do not cache config-class failures (ValueError from dim guard / missing-file that is not a hash mismatch); keep sticky cache only for verified-load/tamper failures.

---

### S2R-04 — low

**File:line:** `apps/prototype-description-service/recognition/tests/unit/test_face_pipeline_adapter.py` (suite gap)  
**Heuristic:** RES-02, RES-04, TEST-06  
**Failure scenario:** No modelless test asserts (1) `wait_for_adapter` timeout → `DetectionTimeoutError`, (2) breaker open path, (3) `_detect_sync` runs on the dedicated executor (not default pool / not event-loop). A regression that moves decode back onto the loop or drops breaker wrapping can pass the full 17-test suite.

**Fix:** Add unit tests with a mock executor/fake slow `_detect_sync` + short timeout; assert breaker name `face_pipeline.detect` and executor identity.

---

### S2R-05 — low

**File:line:** `apps/prototype-description-service/recognition/infrastructure/embeddings/face_pipeline_adapter.py:389-391`  
**Heuristic:** RLSE-05  
**Failure scenario:** FIR-3 `ZeroNormEmbeddingError` from `embed_batch` is caught by the broad `except Exception` and re-wrapped as `DetectionAdapterError`. Fail-closed behaviour is preserved (scan fails), but callers/metrics that key on `ZeroNormEmbeddingError` lose type identity; ops cannot distinguish corrupt embedding vs generic adapter failure without string matching.

**Fix:** `except ZeroNormEmbeddingError: raise DetectionAdapterError(..., error_message=...) from exc` with a stable message prefix, or re-raise ZeroNorm after logging; do not silently normalize to a generic exception without provenance in the message.

---

### S2R-06 — low

**File:line:** `apps/prototype-description-service/recognition/infrastructure/embeddings/face_pipeline_adapter.py:317-322`  
**Heuristic:** SERVE-08  
**Failure scenario:** After xywh→corner + clamp to image bounds, a box fully outside or zero-width/height (rounding/clamp) still produces a `FaceDetection` with a full embedding from the **aligner crop** (landmarks), not the clamped bbox. Downstream IoU match / quality size terms see degenerate corner boxes while embeddings come from valid crops — silent mismatch between stored bbox and embedding geometry.

**Fix:** Drop or flag detections where `x2 <= x1` or `y2 <= y1` after clamp; optionally clamp before align or derive bbox from aligned crop policy documented for FIR-6.

---

## Attack angles exercised — no finding

1. **Decode parity (SERVE-08):** `decode_image_bytes` is byte-identical to `InsightFaceAdapter._bytes_to_cv2`/`_pil_to_cv2` (open → convert RGB if needed → array → RGB2BGR; no EXIF). Modes P/LA covered by convert("RGB"); same path as incumbent for CMYK/I;16. Residual is test golden discipline (S2R-02), not production code divergence.

2. **One-pass embedding contract:** `_detect_sync` always embeds every returned face (`zip(..., strict=True)`); empty detect → `[]`; no `embedding=None` path. Generator slot is `UnavailableEmbeddingGenerator("face_pipeline embeds in detect()")`. Landmark handoff is `face.landmarks` into `FivePointAligner.align` (YuNet 5×2 order — matches FIR-3). Multi-source batch is sequential per-image (same shape as incumbent); multi-face single image is one embed batch.

3. **Async safety (RES-02/04):** Decode + detect + align + embed all inside `_detect_sync` → `run_in_executor(self._executor, ...)` on module dedicated `ThreadPoolExecutor(max_workers=2)`; awaited via `wait_for_adapter` inside `breaker.call`. Better than incumbent (incumbent decodes on the event loop before executor). Reset hook clears singleton only (executor intentionally process-lifetime) — not a reset leak.

4. **Singleton atomicity:** Double-checked lock correct; failure path stores Unavailable then re-raises; half-open YuNet-only state is not memoized (failed load never assigns a partial `FacePipelineRuntime`). YuNet may GC-leak one abandoned session on SFace failure — acceptable residual. Profile string is key-only (loader always face_pipeline) — OK if factory is sole caller.

5. **Dim guard (EMB-01):** Checked in `_load_face_pipeline_runtime` and `FacePipelineFaceDetector.__init__` against live `get_database_settings().pgvector_dimension` and `get_settings().identity_detection.embedding_dimension`; clear ValueError reason. Sticky-cache interaction is S2R-03.

6. **Settings (PROV-08, rg-008):** Invalid `RECOGNITION_FACE_PIPELINE_PROFILE` raises at `RecognitionSettings()` load (`default_factory` + validator). `RECOGNITION_EMBEDDING_DIMENSION` uses same env `default_factory` pattern as `runtime_mode`; default 512 unchanged. Consumers of `embedding_dimension` (similarity, generator, tests) keep reading settings — binding is additive. score/nms/top_k are code defaults (not env); timeout defaults via embedding timeout — consistent with incumbent timeout source; not a contract fail for S2 checklist.

7. **model_id / zero-norm (PROV-06, RLSE-05):** `sface_embedding_model_manifest()` builds from `MODEL_MANIFEST["sface"]` → `opencv-sface@128d/l2/cosine` via `EmbeddingModelManifest.model_id` (no duplicated literal in detector stamp path). Zero-norm fails closed (wrapped — S2R-05).

8. **URL/str sources:** Matches `InsightFaceFaceDetector`: empty skip, http(s) fetch + drop on failure, non-URL string warn+continue, bytes → sha256 media_id. No silent extra drop.

9. **Tests (TEST-06):** No vacuous tests (all assert or pytest.raises). Import of `face_pipeline_adapter` does not call `load_verified_model` (0 calls). Module imports onnxruntime but does not open sessions until runtime load. Modelless helpers (settings, xywh, dim guard, decode, decode-fail, zero-face with mocks) do not require ONNX files.

10. **S1 rider (59972be7):** Touches only `apps/prototype-description-service/pyproject.toml` + `uv.lock`; floors `onnxruntime>=1.22.0` and `onnxruntime-gpu>=1.22.0` (Linux). Nothing else in the commit.

---

## S1 rider sanity

| Check | Result |
| --- | --- |
| Files | `pyproject.toml`, `uv.lock` only |
| Floor | `>=1.22.0` (cpu + gpu mirror) |
| Behaviour surface | none (lock/deps only) |

## S2 summary vs checklist

| Checklist item | Status |
| --- | --- |
| FacePipelineSettings + invalid profile at load | OK |
| RECOGNITION_EMBEDDING_DIMENSION default 512 | OK |
| One-pass detect→align→embed + model_id from manifest | OK |
| Decode = incumbent (no EXIF) | OK in code; golden discipline weak (S2R-02) |
| Singleton + dedicated executor + breaker/timeout | OK; timeout/breaker tests thin (S2R-04) |
| Three-way dim guard at construction | OK; sticky Unavailable edge (S2R-03) |
| pose_*=None | OK |
| phash / landmark_quality parity | Gap (S2R-01) |
| Modelless suite green | 17 passed (this host models-present) |
