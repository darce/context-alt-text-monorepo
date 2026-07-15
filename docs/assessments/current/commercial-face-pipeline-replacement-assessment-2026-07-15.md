# Commercial Face Pipeline Replacement — Assessment (2026-07-15)

**Task**: FIR-1 · **Status**: assessment · **Scope doc**: [docs/scopes/commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md)
**Source research**: `~/Documents/research_papers/ACX/acx_commercial_face_recognition_replacement_guide.docx` (verified against official sources 2026-07-14), reviewed against the codemap-indexed codebase and the engineering-heuristics canon.

## 1. Verdict

InsightFace buffalo models are non-commercial even for private server-side inference in a paid product; non-distribution is not an exception. Replace the production harness with an ACX-owned **YuNet (2026may, MIT) + SFace (2021dec, Apache-2.0)** pipeline behind the existing adapter seams; retain InsightFace **benchmark-only**, fully separated from production (deps, images, DB). The research guide's recommendation survives codebase review with four material adaptations (§3). The principal open risk is accuracy on ACX data, not licensing — per intake, **no fixed accuracy gate is set yet**; the bake-off produces the numbers, then the gate is decided (heuristic RLSE-03: invariants recorded before the audit that enforces them).

## 2. Licensing position (from guide §2, operative rules)

- buffalo_l/s/m + antelopev2 weights: non-commercial research only unless licensed. Applies to auto-downloaded models. Fine-tuning does not launder the restriction.
- InsightFace **code** is MIT — the restriction is the weights. ArcFace/RetinaFace are algorithms, not licenses; clearance comes from specific weights + training-data provenance.
- Evaluation use is acceptable in a genuinely non-commercial environment: benchmark embeddings must never become or feed the production gallery, and buffalo weights must be **removed from production images before commercial launch**.
- Every production embedding row records the model/weight version that produced it (§6 provenance).

## 3. Guide vs codebase: four adaptations

The guide was written against a generic InsightFace deployment. The actual codebase changes its shape:

1. **The ACX-owned interface partially exists.** `FaceDetectorProtocol` / `EmbeddingGeneratorProtocol` (`recognition/application/embedding/{detector,generator}.py`) already isolate ScanService from InsightFace, with stub + fail-closed `Unavailable*` implementations and circuit breakers (REF-15 ports-and-adapters is already satisfied at the call seam). The real coupling is **data-shape leakage** (REF-19): `DetectedFace.embedding_512`, pose/age/gender fields, `InsightFaceSettings`, buffalo-bundle health checks, and 512 hardcoded in stubs/tests all leak the buffalo decision across modules.
2. **No video/track pipeline exists.** The guide's track-level medoid aggregation maps onto the existing multi-observation machinery: `IdentityClusterRepresentative` (quality + diversity scored) and `mv_identity_cluster_centroids`. "Track template" ≈ cluster representative set; this is an adaptation of existing code, not a new subsystem. (The second ACX doc, `acx_video_understanding_architecture_implementation_guide.docx`, covers a future video/tracks world — out of scope here.)
3. **Greenfield policy voids the migration plan.** Guide §9 (shadow mode, dual templates, rollback retention) assumes production data. This repo has none to preserve: `PGVECTOR_DIM` 512→128 goes directly into `001_identity_schema.py`, existing rows are dropped, tenants re-scan. Shadow comparison still happens — but in the eval harness, not in production tables (DATA-04 expand/contract explicitly not needed; recorded so nobody builds it).
4. **CPU is the production path** (intake decision). acx-backend is ARM CPU; acx-gpu-burst is stopped. Guide §7.2 (ONNX Runtime CUDA / TensorRT on A10) applies to the bake-off first and to a follow-on production task later, not the MVP (ARCH-08 boring-first).

## 4. Blast radius

### 4.1 Code (replace/rework)

| Surface | Change |
| --- | --- |
| `recognition/infrastructure/embeddings/__init__.py` | Replace `InsightFaceAdapter`/`DetectedFace` with YuNet+SFace adapters (OpenCV CPU reference + ONNX Runtime impls) emitting a model-neutral detection dataclass (bbox, 5 landmarks, confidence, embedding, model_id) |
| `recognition/application/embedding/detector.py`, `generator.py` | New protocol implementations; strip `embedding_512`/age/gender/pose fields from the seam; keep breaker/timeout/fail-closed shells as-is |
| `recognition/worker/scan_worker.py:_ensure_embedding_runtime`, `application/tasks/scan.py:process_scan_job_inline` | Swap adapter construction; capability heartbeat unchanged |
| `recognition/config/settings.py` | `InsightFaceSettings` → `FacePipelineSettings` (model paths + sha256 pins, thresholds, providers); cache-dir resolution for ONNX files |
| `recognition/application/health.py:check_model_cache`, `api/main.py:register_health_probes` | Model-cache probe checks pinned YuNet/SFace ONNX files instead of buffalo bundle |
| `recognition/application/assignment/quality.py` | Pose inputs become landmark-derived proxies (§6); add sharpness/embedding-magnitude signals |
| `recognition/application/scan/service.py`, `services/export_service.py`, `interface_adapters/http/deps/stores.py` | Remove age/gender writes/exports/API projection (intake: never product, wildly inaccurate; follow-up only after recognition is stable) |
| `pyproject.toml` | `insightface` leaves `[local]`/`[gpu]`; new `[bench]` extra holds it for eval only; `opencv-python` pin decision (4.12 `FaceDetectorYN` vs OpenCV 5 for YuNet 2026may dynamic input) resolved in FIR-3; mypy override cleanup |
| Docker/compose, `scripts/install_insightface_mac.sh`, model provisioning | Ship pinned ONNX files + license files in the artifact; **remove buffalo weights from production images** |
| Tests | `test_adapter_surface_inventory`, circuit-breaker, generator-protocol, health-probe, retention-cache tests re-anchored; stub dims (512 default) centralized to settings (REF-19) |

### 4.2 Schema (direct edit in `001_identity_schema.py`, greenfield)

- `media_identities.embedding`, `identity_cluster_representatives.embedding`, `mv_identity_cluster_centroids.centroid`: `vector(512)` → `vector(128)` via `PGVECTOR_DIM`. Unit-norm CHECKs and ivfflat cosine index carry over unchanged (128D = 4× smaller vectors → distance ops and index get *faster*, not slower).
- Add `embedding_model` provenance column (text, e.g. `yunet-2026may+sface-2021dec@l2/cosine`) on `media_identities` — per-row provenance per guide §2.3/§16 without a registry service (REF-12 YAGNI).
- Drop `age`/`gender` columns. `pose_*` columns stay but store landmark-derived estimates (nullable already).
- Downstream: `sync_identity_schema.py`/`verify_identity_schema.py` (verify fails closed on column gaps), reset scripts, `.env`/compose `PGVECTOR_DIM`.

**Benchmark separation (decision per heuristics):** InsightFace embeddings never enter the production schema. A shared table with `model_id` is infeasible anyway — a pgvector column has one fixed dimension, and 512D buffalo cannot share a `vector(128)` column or its index. Bench embeddings live in **eval-harness run artifacts (npz/JSON) plus, if needed, a dedicated eval-tenant deployment** with buffalo-dimensioned schema, never the prod DB (ARCH-02 single writer; DOM-03 bounded contexts; license isolation for free). **Prod performance impact: none** — no per-query model filter, and smaller vectors.

### 4.3 Explicitly NOT touched

Clustering algorithms (cosine on unit vectors — dimension-agnostic), roster module, curation/workbench UX, scene/describe + VLM captioning, WP plugin (consumes clusters/labels, not embeddings), tenant/RLS machinery, API contracts other than age/gender field removal.

### 4.4 Thresholds (all recalibrated, never copied — guide §8.1)

`ClusteringSettings.similarity_threshold` (0.6), `IdentityDetectionSettings.default_threshold` (0.45), `QualitySettings` pose divisor / min face size, per-cluster `similarity_threshold`, curriculum/maturity adjustments. SFace geometry ≠ buffalo geometry; every one comes out of FIR-6 calibration.

## 5. Expected performance drop

Literature-derived expectation — **the bake-off is the real answer** (PERF-06 measure-don't-guess; the guide: "the principal unresolved question is accuracy on ACX data"):

- **Recognition (SFace 2021dec vs buffalo_l ArcFace-R50):** near-parity on easy/frontal faces (LFW-class: ~99.6% vs ~99.8%); the gap widens on hard slices — expect roughly **3–7 points TAR at fixed FAR** worse on profile/low-res/occluded faces (IJB-C-class protocols), which is exactly the WP-media long tail. 128D vs 512D also means less headroom for very large galleries; irrelevant at current tenant roster sizes.
- **Detection (YuNet vs SCRFD-10GF):** WIDER-hard AP ~0.81 vs ~0.83–0.85 — expect a few percent more **missed small/blurry/extreme-pose faces**; near-parity on medium/large faces. YuNet is dramatically cheaper on ARM CPU, which the production path needs.
- **Recoverable:** multi-observation aggregation (cluster representatives/medoid templates), quality-gated enrollment, per-tenant threshold calibration, and the curation loop absorb part of the single-image gap. Net product-level effect plausibly lands at a **small increase in unassigned faces and curation corrections** rather than wrong-identity assignments — provided the unknown threshold + ambiguity margin are calibrated conservatively (§8.1 of the guide).

## 6. Extra dimensions from the literature (user-supplied corpora)

Directly usable, in priority order:

| Source | Adds |
| --- | --- |
| `AdaFace` (research_papers + ___Books) & MagFace (guide refs) | **Embedding-norm ≈ image quality**: quality-adaptive signals; use feature magnitude as a free per-face quality score to gate enrollment/aggregation — replaces part of the lost InsightFace pose signal |
| `Cluster and Aggregate` (___Books, 2210.10864) | Learned/weighted aggregation over large probe sets — upgrade path beyond medoid templates for cluster-representative fusion |
| `SFace: Privacy-friendly… Synthetic Data` (research_papers) | Distinct from OpenCV-SFace: synthetic-training route with clean data provenance — candidate escalation dimension if OpenCV-SFace fails the bake-off (before commercial SDKs) |
| `Fair-SA` + `FORML` (literature/recognition/apple) | Fairness sensitivity analysis → implements the guide's demographic-slice metric (§12.2) concretely |
| Apple "Recognizing People in Photos" (literature/recognition/apple) | Production blueprint for on-device/private galleries: quality gating, iterative clustering, unknown handling — closest published analog to the ACX product shape |
| IJB-B/IJB-C protocol papers (___Books) | Template-based (multi-observation) evaluation protocol — the correct metric design for the bake-off, vs single-image verification |
| `CurricularFace`, `AirFace`, SV-Softmax (apple dir) | Loss/backbone survey if custom training is ever escalated to (last resort per guide §13) |
| `chinese-whispers.pdf` (literature/recognition) | Graph clustering alternative if recalibrated cosine clustering shows purity issues at 128D |
| `RetinaFace`, SCRFD papers | Detector context for the bake-off's buffalo reference leg |

`acx_video_understanding_architecture_implementation_guide.docx` is the companion doc for the future video/tracks epic; not consumed here.

## 7. Benchmark harness readiness

`scripts/eval_harness/` (VLM-2A) **already scores face-recognition P/R** — detection + identification, micro + per-identity macro — against the golden manifest via the live service (`analyze`/`wait_job`/`media_identities`), with seeded eval roster (`seed_roster.py`), deterministic re-scoring, and bounded-stall discipline. Golden manifest v2 is populated (88d5d820); VLM-6's Golden-100 curation extends the corpus.

Gaps to close for this bake-off (FIR-5):

1. **Candidate swapping**: harness benchmarks *the deployed service*, one model stack at a time. Need either an env-selected face-pipeline profile on an eval instance (mirroring the hosted-provider pattern) or an offline in-process leg that runs detector+embedder candidates directly over the golden corpus.
2. **Cluster-level metrics**: identification P/R exists; **false-merge/false-split rates, cluster purity, unknown-rejection at fixed FAR** (guide §12.2) do not.
3. **buffalo_l reference leg** must run in the non-commercial eval environment only (`[bench]` extra), embeddings confined to run artifacts (§4.2 separation).
4. **Corpus breadth**: 38 golden images is thin for threshold calibration; extend with Golden-100 + hard-slice additions (profile/low-res/blur/similar-people/unknowns, demographic slices).

Unit/integration test harness: protocol-based stubs mean existing suites survive the swap with re-anchoring only; goldens for landmark order, alignment affine, and normalization parity (guide checklist) are new and CPU-only — they fit the existing scoped-TDD + `make check-remote` gate flow.

## 8. Heuristics review (canon IDs verified against `darce/heuristics-canon` lexicons/engineering.md)

- **REF-15 / REF-19**: adapter seam exists; the violation is information leakage (512-dim, buffalo metadata shapes) — FIR-2 centralizes it. 
- **ARCH-02 / DOM-03**: bench vs prod embedding stores get separate owners; no shared multi-writer table.
- **ARCH-06 / ARCH-07**: trade-offs recorded here; model selection lands as an ADR after the bake-off.
- **ARCH-08**: OpenCV/ORT CPU baseline before GPU/TensorRT novelty.
- **REF-12**: provenance column, not a model-registry service; no speculative multi-model query layer.
- **DATA-03/04**: consciously exempted via greenfield policy (recorded, not skipped).
- **DOM-05**: embedding model identity (name+version+dim+metric+normalization) as one typed manifest value, not scattered primitives.
- **PERF-06 / AGT-03**: no accuracy claim ships without bake-off evidence; thresholds only from measured calibration.
- **RLSE-02/03**: bake-off verdict is a real gate; intake explicitly deferred the pass/fail criteria to post-measurement — the gate must be recorded in MCP before the switch-over slice.
- **RES-01..04 posture already present** (breakers, fail-closed adapters, timeouts) — preserve shells unchanged.

## 9. Risks & open questions

1. **SFace accuracy on ACX hard slices** — top risk; escalation ladder pre-agreed: SeetaFace6 → licensed InsightFace hosted-service quote → commercial SDK → custom training (last).
2. **OpenCV 4.12-pin vs OpenCV 5** for YuNet 2026may dynamic-input support — resolve in FIR-3 (ORT-first inference makes OpenCV version mostly a reference-impl concern).
3. **Quality scoring without native pose** — landmark-derived roll/yaw proxies + sharpness + embedding magnitude; validate against curation outcomes in FIR-6.
4. **Eval-tenant isolation** — buffalo embeddings must be provably absent from prod (image audit + `[bench]` extra + run-artifact-only storage).
5. **Threshold cold-start** — until calibration lands, defaults must fail toward "unknown" rather than false assignment.
