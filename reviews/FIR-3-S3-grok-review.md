# FIR-3 S3 adversarial review (grok / fir-3-grok)

**Target:** `0a7cb7396a60acd0835cc50a4ed43db90d8e5558` — `ort_adapters.py` (402) + `test_face_pipeline_ort_parity.py` (562)  
**Role:** hostile / review-only (no implementation edits)  
**Host:** OpenCV `4.13.0`, ORT CPU; models re-fetched via `apps/prototype-description-service/scripts/fetch_face_pipeline_models.py`  
**Heuristics cited:** TEST-06, DIAG-08, TEST-08, AGT-02, RES-04, CON-12-adjacent, rg-015  

## VERDICT: pass_with_findings

End-to-end ORT vs OpenCV **FaceDetectorYN / FaceRecognizerSF** parity generalizes far beyond the single cartoon fixture: multi-face, non-multiple-of-32 canvases, border-clipped faces, mixed batches, and threshold sweeps keep **count parity** and **IoU ≥ 0.999998** / landmark max-dist ≪ 2px / score Δ ≪ 0.02 whenever either side detects. SFace preprocess is **bit-identical** to `blobFromImage(..., swapRB=true, scale=1)`. Decode math is pinned by modelless tests (not shape-only). Remaining issues: CI parity is still one-fixture (TEST-06), module docstring misstates score composition, pure `cv2.dnn.NMSBoxes` float-IoU / strict `>` score gate diverge from `nms_yunet` (int-cast path that FaceDetectorYN uses still matches), detector determinism test is empty-image-only, and ORT sessions do not pin thread counts.

---

### S3-GR-01 — medium

**File:** `apps/prototype-description-service/recognition/tests/unit/test_face_pipeline_ort_parity.py:439-487`  
**Rules:** TEST-06, DIAG-08  

**Evidence + failure scenario:** Models-present detector parity is **only** `test_detector_parity_cartoon_fixture` — one 480×480 golden cartoon, default score 0.9 / nms 0.3, primary (max-score) match only. No CI coverage for multi-face layouts, non-×32 sizes, border priors, low `top_k`, or threshold straddling.

Measured outside the suite (same host, golden face procedure / resizes):

| Attack | th | counts ocv/ort | primary IoU | lm max (px) | score Δ |
| --- | --- | --- | --- | --- | --- |
| baseline cartoon 480 | 0.9 | 1/1 | **0.9999997331** | 3.4e-5 | 3.1e-8 |
| 3 faces on 640×480 (non-×32) | 0.5 | 3/3 | ≥0.99999904 each | ≤2.8e-5 | ≤6e-7 |
| 3 faces on 640×480 | 0.9 | **0/0** | n/a (scores ~0.78–0.80) | — | — |
| 2 corners 600×800 | 0.5 | 2/2 | ≥0.99999989 | ≤6e-5 | ≤5e-7 |
| full resize sz∈{100,123,199,257,301,333,240,320,481} | 0.5 | 1/1 (65/97 empty both) | ≥0.99999899 | ≤2.3e-4 | ≤1.3e-6 |
| face in 481×479 canvas | 0.9 | 1/1 | 0.99999947 | 6e-5 | 6.6e-8 |
| border TL/TR/left clip | 0.5 | 1/1 | ≥0.99999924 | ≤6e-5 | ≤1.6e-7 |
| mixed batch [480,123,257×199,empty] | 0.5 | [1,1,1,0]/same | ≥0.99999952 | — | — |

**No count divergence** found on fine threshold sweeps (cartoon + multi at th∈[0.01,0.99]). Failure mode is **coverage**, not latent math: a future decode/NMS regression that only breaks multi-face or non-×32 padding can still green the suite. At default 0.9, multi-face resized cartoons return empty **both** sides — a naive “if both nonempty then IoU” gate would vacuous-pass; current test avoids that for the single fixture via `assert len >= 1`.

**Fix shape:** Add parity cases (multi-face at th=0.5, ≥1 non-×32 size, ≥1 border crop) with count equality + greedy IoU ≥ 0.99; keep primary match on golden.

---

### S3-GR-02 — medium

**File:** `apps/prototype-description-service/recognition/infrastructure/face_pipeline/ort_adapters.py:5` vs `:116,:145`  
**Rules:** AGT-02, rg-015  

**Evidence + failure scenario:** Module docstring claims YuNet post-process uses **“cls×obj score”**. Implementation (and OpenCV FaceDetectorYN) uses **`sqrt(clamp(cls)·clamp(obj))`**. Modelless test pins sqrt correctly (`cls=0.81,obj=1 → score≈0.9`). A reimplementer or FIR-4 consumer reading only the module header will compose product scores (0.81 vs 0.9 at the default threshold) and systematically drop/keep different faces near 0.9.

**Fix shape:** Change L5 to `sqrt(cls×obj)`; keep function docstring as source of truth.

---

### S3-GR-03 — medium

**File:** `apps/prototype-description-service/recognition/infrastructure/face_pipeline/ort_adapters.py:190-237`  
**Rules:** CON-12-adjacent, AGT-02  

**Evidence + failure scenario:** `nms_yunet` docstring claims match to `dnn::NMSBoxes` on integer xywh. Against **float** boxes passed to `cv2.dnn.NMSBoxes`, **3/20** random trials (seed 42) diverged; against **pre-int** boxes, **0/50** mismatches. Root cause measured on trial 11 pair (idx 10 vs 7): **float IoU = 0.3094** (suppress at thr 0.3) vs **int IoU = 0.2996** (keep). Across 5000 random box pairs, float/int IoU **straddled 0.3 in 72 cases**.

Additionally, score gate differs from pure NMSBoxes:

| score | `nms_yunet` (≥) | `cv2.dnn.NMSBoxes` |
| --- | --- | --- |
| 0.95 | keep | keep |
| **0.9 exact** | **keep** | **drop** (strict `>`) |
| 0.8999999 | drop | drop |

Equal-score heavy overlap: ours kept boxes at offsets 0 and 20; OpenCV float NMS kept indices `[0, 4]` — different suppress order under ties.

**End-to-end FaceDetectorYN still matches ORT** (int-cast path is what the reference detector uses). Failure scenario: callers or tests that validate `nms_yunet` against `cv2.dnn.NMSBoxes` on float boxes, or rely on dropping score==threshold, will disagree; comment overclaims NMSBoxes parity.

**Fix shape:** Docstring: “FaceDetectorYN postProcess NMS (int xywh IoU, score≥thr)”, not raw NMSBoxes float; optional unit test vs int boxes / vs live FaceDetectorYN counts only.

---

### S3-GR-04 — low

**File:** `apps/prototype-description-service/recognition/infrastructure/face_pipeline/ort_adapters.py:60-68,:298,:357`  
**Rules:** RES-04, TEST-08, PERF  

**Evidence + failure scenario:** `InferenceSession` is created **once per adapter instance** and reused across `detect`/`embed` (not per call — good). Separate instances always allocate separate sessions (no process-level cache). `_ort_session` sets only `log_severity_level=3`; **does not pin** `inter_op_num_threads` / `intra_op_num_threads` (ORT defaults 0 = “all cores”). `test_detector_and_embedder_determinism` only double-runs embed on one crop and **detector on a zero image** (`64×64` empty → both `[[]]`), so multi-thread ORT non-determinism on real YuNet graphs is not exercised.

**Fix shape:** Pin `intra_op_num_threads=1` (and inter_op=1) for parity/determinism builds or document ORT thread env; extend determinism test to cartoon face bbox/score equality.

---

### S3-GR-05 — low

**File:** `apps/prototype-description-service/recognition/tests/unit/test_face_pipeline_ort_parity.py:108-148,:234-255,:471-472`  
**Rules:** TEST-06  

**Evidence + failure scenario:** Modelless decode **does** pin math: synthetic prior → bbox `[-2,8,8,8]`, landmarks, score `sqrt` and clamp — not shape-only. Full `decode_yunet_outputs` synthetic only asserts `len==1` and score≈1 (weaker, but level test covers geometry). Empty-empty vacuous IoU is **blocked** on the cartoon path by `assert len(ocv_faces) >= 1` and `assert len(ort_faces) >= 1`. Residual honesty gap: no test asserts that “both empty” is treated as failure when a face is expected; multi-face at default 0.9 is both-empty in the wild (S3-GR-01).

**Fix shape:** Keep exact-value decode tests; add multi-face expected-count fixture at th=0.5.

---

## Attempted attacks that did **not** land (defeated)

| Attack | Result |
| --- | --- |
| Parity “too good” fails multi-face | **Holds**: 3-face 640×480 @ th=0.5 → 3/3 matches, IoU ≥ 0.99999904, lm ≤ 2.8e-5, score Δ ≤ 6e-7 |
| Non-×32 padding / stride rounding vs OpenCV | **Holds** on all detecting sizes; IoU ≥ 0.99999899; counts always equal |
| Border / partial face priors | **Holds** when either detects (TL/TR/left @0.5); BL/BR empty both |
| Score straddle 0.9 (ORT keeps, OCV drops) | **No count diverge** on cartoon (score≈0.90237 both) or multi fine sweep |
| High `top_k` interplay | top_k∈{1,2,3,5,10,50,5000} @ th=0.3 multi: count + IoU match |
| NMS heavy overlap end-to-end | 2-overlap 512 canvas → 1/1, IoU 0.99999931 |
| Decode formula vs FaceDetectorYN (exp w/h, grid priors, sqrt score) | Matches; modelless pins numbers |
| SFace “RGB NCHW scale=1 swapRB” false | **max abs vs `blobFromImage(swapRB=True,scale=1)` = 0** on synthetic, aligner, random crops; noswap/ /255 max abs ≥254 |
| Non-contiguous / float-255 crops break blob or emb | contig blob max abs 0; emb cos ≥ 0.99999999999 |
| Embedding cosine only on golden | synthetic cos **0.999999999998**, aligner **0.999999999995**, raw feature max abs ~1e-6 |
| Empty both sides vacuous IoU pass in cartoon test | Blocked by `len >= 1` |
| Modelless decode shape-only | Exact bbox/score/landmarks asserted |
| Session created per `detect` call | Cached on instance; stable across calls |
| Import purity / zero-norm / 112 gate / float01 gate | Covered by suite; 73 passed |
| Pre-pad then detect vs original | OCV orig≡pad bit-equal on 480; ORT matches both |

## Contract notes (safe / unsafe for FIR-4)

**Safe to build on (this host):** ORT YuNet post-process ≡ FaceDetectorYN for tested geometries; SFace blob ≡ `blobFromImage` swapRB scale=1; dim 128 L2; score `sqrt(cls·obj)`; pad divisor 32 bottom-right; session reuse per instance; empty batch shapes; zero-norm raise.

**Do not assume:** CI proves multi-face/non-×32/border; `nms_yunet` ≡ float `cv2.dnn.NMSBoxes`; score==threshold dropped; ORT multi-thread bit-determinism; module header “cls×obj” without sqrt.

## Tests run this session

```text
cd apps/prototype-description-service && uv run python scripts/fetch_face_pipeline_models.py
cd apps/prototype-description-service && uv run pytest \
  recognition/tests/unit/test_face_pipeline_provenance.py \
  recognition/tests/unit/test_face_pipeline_opencv_ref.py \
  recognition/tests/unit/test_face_pipeline_ort_parity.py -q
# → 73 passed in 2.11s
# + adversarial probe scripts (multi/non32/border/NMS/preprocess/session) — not committed
```
