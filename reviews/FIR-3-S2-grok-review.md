# FIR-3 S2 adversarial review (grok / fir-3-grok)

**Target:** `443bfce739d80bec409ad5de12d676df9a3d9161` — FIR-3 S2 OpenCV ref + goldens  
**Role:** hostile / review-only (no implementation edits)  
**Host:** OpenCV `4.13.0`, models re-fetched via `scripts/fetch_face_pipeline_models.py`  
**Heuristics cited:** rg-015, TEST-06, TEST-08, AGT-02, AGT-06  

## VERDICT: pass_with_findings

`FivePointAligner` reproduces `cv2.FaceRecognizerSF.alignCrop` **bit-exactly** on the committed golden landmarks/image (max pixel abs diff 0; crop SHA match). YuNet landmark indices on the cartoon fixture map to the documented order (right eye → left eye → nose → right mouth → left mouth). Embedding goldens regenerate identically; cosine gate `≥ 0.9999` is tight, not tautological. Remaining issues: aligner goldens are circular (no CI oracle vs `alignCrop`), embedder silently accepts non-112 crops (poison path), and float`[0,1]` inputs are clipped to near-black without error.

---

### S2-GR-01 — high

**File:** `apps/prototype-description-service/recognition/tests/fixtures/face_pipeline/generate_goldens.py:119-126` + `recognition/tests/unit/test_face_pipeline_opencv_ref.py:80-92`  
**Rules:** TEST-06, TEST-08, rg-015  

**Evidence + failure scenario:** Aligner expected crop/affine are produced by `FivePointAligner().align(...)` itself. Unit tests compare live `FivePointAligner` output to those fixtures (`assert_array_equal` / crop sha256). Neither `generate_goldens.py` nor the unit suite imports `FaceRecognizerSF.alignCrop`. A wrong-but-deterministic aligner (e.g. `INTER_NEAREST`, wrong Umeyama rank branch, swapped canonical targets) that is used both to regenerate fixtures and under test still goes green. Task plan S2 names OpenCV `FaceRecognizerSF` as the semantic reference and treats alignment as the merge gate — CI does not lock that claim. **This session’s oracle check:** `alignCrop` vs `FivePointAligner` on `aligner_source_image.npy` + `aligner_landmarks.npy` → **exact equality** (so production path is currently correct). **Fix shape:** generate (or assert) aligner crop against `FaceRecognizerSF.alignCrop` once per golden regen/CI; keep `FivePointAligner` as the portable reimplementation under test, not as its own expected value.

---

### S2-GR-02 — high

**File:** `apps/prototype-description-service/recognition/infrastructure/face_pipeline/opencv_ref.py:169-189`  
**Rules:** rg-015  

**Evidence + failure scenario:** `embed` docstring explicitly allows “112×112 (or any)” crops. No shape gate before `_feature`. Adversarial probe on committed `synthetic_112_crop.npy`:

| crop size | accepted? | L2 after norm | cosine vs true 112 |
| --- | --- | --- | --- |
| 112×112 | yes | 1.0 | 1.0 |
| 64×64 | yes | 1.0 | ~0.909 |
| 224×224 | yes | 1.0 | ~0.969 |
| mixed batch `[112, 64]` | yes | 1.0 each | cross-cos ~0.909 |

SFace still returns 128-D finite vectors; L2==1 checks pass; silent semantic drift poisons every downstream identity/clustering step. Aligner’s only legal output is 112×112, but any caller (or S3 parity harness) that resizes wrong, center-crops wrong, or passes detector bboxes as “crops” gets plausible unit vectors. **Fix shape:** reject non-`(112,112,3)` with `FacePipelineInputError` (or document + implement a single explicit resize policy and golden it). Prefer fail-closed: alignment already owns size.

---

### S2-GR-03 — medium

**File:** `apps/prototype-description-service/recognition/infrastructure/face_pipeline/opencv_ref.py:59-75` (also `aligner.py:186-190`)  
**Rules:** rg-015, AGT-02  

**Evidence + failure scenario:** Float arrays are `clip(0, 255).astype(uint8)`. A common BGR float convention `[0,1]` therefore becomes `{0,1}` uint8 (probe: ~98% zeros, max=1). Embedding cosine vs correct uint8 crop ≈ **0.036** — near-orthogonal identity vectors, still L2-normalized, no error. Unit test even notes the trap (`test_face_pipeline_opencv_ref.py:193`: “float image in [0,1] would clip poorly”) then avoids it instead of failing closed. **Failure:** numpy pipeline / VLM preproc hands float images; detector/embedder “succeed”; all identities wrong. **Fix shape:** if dtype is floating, require max>1.5 (or mean in a documented range) else raise; or accept only uint8 at the public boundary.

---

### S2-GR-04 — medium

**File:** `apps/prototype-description-service/recognition/tests/unit/test_face_pipeline_opencv_ref.py:278-280`  
**Rules:** TEST-06, rg-015  

**Evidence + failure scenario:** Cartoon golden only asserts eye x-order `landmarks[0,0] < landmarks[1,0]` plus absolute landmark values within 2px of recorded JSON. That catches a full left/right eye swap on this frontal face, but a mouth-corner swap (indices 3↔4) or a plausible wrong mapping that preserves eye x-order still passes the order check. Manual adversarial mapping of YuNet outputs to **drawn** cartoon features (eye centers from `procedure.eye_sep`, nose, mouth_y) on this host:

| idx | documented name | nearest drawn feature |
| --- | --- | --- |
| 0 | right_eye | right_eye (image-left) |
| 1 | left_eye | left_eye (image-right) |
| 2 | nose_tip | nose |
| 3 | right_mouth_corner | mouth region (left of center) |
| 4 | left_mouth_corner | mouth region (right of center) |

Runtime order is correct today; the unit assertion is weaker than the silent-bug class named in the slice brief. **Fix shape:** assert each landmark nearest to known drawn coordinates (or fixture “expected nearest name” list) with a px budget, not only eye x-order.

---

### S2-GR-05 — low

**File:** `apps/prototype-description-service/recognition/infrastructure/face_pipeline/opencv_ref.py:114-132,134-143`  
**Rules:** rg-015, AGT-02  

**Evidence + failure scenario:** `self.score_threshold` / `self.nms_threshold` are public instance attributes but only passed into `FaceDetectorYN.create(...)`. Mutating `det.score_threshold = 0.5` after construction does **not** reconfigure the native detector. Probe: create with `0.95` → 0 faces on cartoon; set attr to `0.5` → still 0 faces; fresh create `0.5` → 1 face. Callers (or future FIR-4 wiring) that treat thresholds as live knobs get a silent no-op. **Fix shape:** make attrs read-only; or re-apply via OpenCV setters if available; or document constructor-only and hide attributes.

---

### S2-GR-06 — low

**File:** `apps/prototype-description-service/recognition/tests/unit/test_face_pipeline_opencv_ref.py:90-92,100`  
**Rules:** TEST-08  

**Evidence + failure scenario:** Aligner crop golden uses bit-exact `assert_array_equal` + sha256 of raw bytes. Embedding golden correctly uses cosine `≥ 0.9999` (not bit-exact floats). On this host, aligner crop SHA is stable across 3 processes and matches committed `c508c8f6…`. Cross-OpenCV-build / BLAS-SIMD drift could still flake bit-exact crop equality while semantics remain fine. Affine already uses `atol=1e-4`. **Fix shape:** prefer small pixel atol/MAE (or SHA of a quantized crop) for cross-host aligner crop; keep tight affine + optional `alignCrop` oracle (S2-GR-01).

---

## Attempted attacks that did **not** land (defeated or non-issues)

| Attack | Result |
| --- | --- |
| `FivePointAligner` ≠ `FaceRecognizerSF.alignCrop` on golden image/landmarks | **Exact match** (diff 0) on OpenCV 4.13.0 |
| Wrong similarity vs full affine (Umeyama port) | Port matches `alignCrop`; `estimateAffinePartial2D` diverges (max affine ~2.6) — confirms custom port is required |
| INTER_LINEAR / BORDER_CONSTANT wrong | Bit-identical to `alignCrop`; INTER_NEAREST diverges (max pixel 182) |
| Canonical target landmarks wrong | Match OpenCV face_recognize.cpp values; hardcoded dst mean matches array mean to 1e-4 |
| YuNet landmark order swapped on cartoon | Indices map to drawn RE/LE/nose/mouth; lm0.x < lm1.x |
| Swapped eye/mouth landmarks still produce identical crop | Swapped order → max pixel diff 255 vs correct crop (detectable if oracle exists) |
| Embedding L2 ≠ 1 | L2 == 1.0 float32 after norm |
| float64 crop dtype path | Coerced; embedding equal to uint8 path |
| Non-contiguous crop view | Contiguity fixed; embedding equal |
| Empty embed batch | Returns `(0, 128)` float32 |
| Empty detect batch / `faces is None` | `[]` / `_parse_faces(None)==[]` |
| Mixed-size detect batch setInputSize pollution | Detect 320 then 480 equals solo 480 (bbox/lm maxdiff 0) |
| score/nms threshold plumbing ignored | `score_threshold=1.0` → 0 faces; `0.1`/`0.5` → ≥1 on cartoon |
| Short FaceDetectorYN row (<15) silent parse | Raises `FacePipelineInputError` |
| Zero-norm only via unrealistic path | Black/white 112 crops still nonzero; monkeypatch `_feature` → zeros/NaN raises `ZeroNormEmbeddingError` (tested honestly) |
| `generate_goldens.py` drifts from committed fixtures | Full regen: all `.npy`/`.json` **IDENTICAL** to pre-regen copy |
| Embedding golden tautological (loose cosine) | `+0.01` renorm → cos ~0.994 **fails** 0.9999; random unit cos ~0.08 |
| Embedding golden host bit-flake | Cosine gate, not bit-exact float compare for cross-run golden |
| Detector golden missing / skip-lie | `detector_faces.json` status=recorded; rebuild from procedure sha matches; tolerances 2px/0.02 used |
| Import purity (worker/HTTP into opencv_ref) | Subprocess purity tests pass; package root still cv2-free |

## Contract notes for S3 (rg-015)

Safe to build on (this host, verified): YuNet order RE/LE/nose/RM/LM; `FivePointAligner` ≡ `alignCrop` on golden; SFace dim 128 L2-normalized float32; BGR uint8; empty-batch shapes; zero-norm raise; detector per-image `setInputSize`; default score 0.9 / nms 0.3.  
Do not assume: embedder rejects non-112; float`[0,1]` is safe; aligner CI proves OpenCV parity (only self-consistency); mutating detector threshold attrs after init works.

## Tests run this session

```text
cd apps/prototype-description-service && uv run python scripts/fetch_face_pipeline_models.py
# ok: fetched 2 model(s)

cd apps/prototype-description-service && uv run python recognition/tests/fixtures/face_pipeline/generate_goldens.py
# Wrote embedding/aligner goldens; detector status=recorded (byte-identical to committed)

cd apps/prototype-description-service && uv run pytest \
  recognition/tests/unit/test_face_pipeline_provenance.py \
  recognition/tests/unit/test_face_pipeline_opencv_ref.py -q
# 31 passed in 0.79s
```
