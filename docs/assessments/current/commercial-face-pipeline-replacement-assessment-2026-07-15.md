# Commercial Face Pipeline Replacement — Assessment (2026-07-15)

**Task**: FIR-1 · **Status**: assessment · **Scope doc**: [docs/scopes/commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md)
**Source research**: `~/Documents/research_papers/ACX/acx_commercial_face_recognition_replacement_guide.docx` (verified against official sources 2026-07-14), reviewed against the codemap-indexed codebase and the engineering-heuristics canon.

## 1. Verdict

InsightFace buffalo models are non-commercial even for private server-side inference in a paid product; non-distribution is not an exception. Replace the production harness with an ACX-owned **YuNet (2026may, MIT) + SFace (2021dec, Apache-2.0)** pipeline behind the existing adapter seams; retain InsightFace **benchmark-only**, fully separated from production (deps, images, DB). The research guide's recommendation survives codebase review with four material adaptations (§3). The principal open risk is accuracy on ACX data, not licensing — per intake, **no fixed accuracy gate is set yet**. This is a deliberate deviation from RLSE-03 (invariants belong *before* the audit), so it carries a structural compensation (RLSE-02: gates are not suggestions, and proximity makes the implementing agent the worst judge): the bake-off report proposes gate criteria, the **operator** records the gate as an MCP decision, and the FIR-6 switch-over slice is **blocked until that decision exists** — the implementing agent never judges its own gate.

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
| `pyproject.toml` | `insightface` leaves the `[face]` and `[gpu]` extras (no `[local]` extra exists); new `[bench]` extra holds it for eval only; `opencv-python` pin decision (4.12 `FaceDetectorYN` vs OpenCV 5 for YuNet 2026may dynamic input) resolved in FIR-3; mypy override cleanup |
| Docker/compose, `scripts/install_insightface_mac.sh`, model provisioning | Ship pinned ONNX files + license files in the artifact, provenance-manifested (source URL + sha256 per file); hashes verified **at image build and at boot** (extend `check_model_cache` to fail closed on hash mismatch, not just presence); **remove buffalo weights from production images** at switch-over |
| Observability | New pipeline emits per-scan metrics/logs: detection count, assignment vs unknown ratio, quality-gate rejection count, `embedding_model` id — the signals that make "more unknowns, not false assignments" falsifiable in production (OBS posture; RLSE-05 no silent failure) |
| Cutover sequencing | FIR-4 wires adapters **dark** behind a face-pipeline profile flag (production default stays on the current pipeline); the flag flips and buffalo leaves prod images only in the FIR-6 switch-over slice, after the operator-recorded gate |
| Tests | `test_adapter_surface_inventory`, circuit-breaker, generator-protocol, health-probe, retention-cache tests re-anchored; stub dims (512 default) centralized to settings (REF-19) |

### 4.2 Schema (direct edit in `001_identity_schema.py`, greenfield)

- `media_identities.embedding`, `identity_cluster_representatives.embedding`, `mv_identity_cluster_centroids.centroid`: `vector(512)` → `vector(128)`. **Two dimension surfaces must flip together**: the hardcoded `EMBEDDING_DIMENSION = 512` in `001_identity_schema.py:14` and the `PGVECTOR_DIM` env default in `db/settings.py:241`, plus every deploy config that sets it (`.env*`, `docker-compose*.yml`, `infra/oci` deploy env, reset scripts). FIR-2 only centralizes the constant; the **default flip lands in FIR-6's gated switch-over slice** together with the flag flip, so schema and active embedder never disagree and no FIR-4 slice is held unmergeable by a later gate (dev/eval exercise 128D earlier via the `PGVECTOR_DIM` env). Unit-norm CHECKs and ivfflat cosine index carry over unchanged (128D = 4× smaller vectors → distance ops and index get *faster*, not slower).
- Add `embedding_model` provenance column (text, e.g. `yunet-2026may+sface-2021dec@l2/cosine`) on `media_identities` — per-row provenance per guide §2.3/§16 without a registry service (REF-12 YAGNI).
- Drop `age`/`gender` columns. `pose_*` columns stay but store landmark-derived estimates (nullable already).
- Downstream: `sync_identity_schema.py`/`verify_identity_schema.py` (verify fails closed on column gaps), reset scripts, `.env`/compose `PGVECTOR_DIM`.

**Benchmark separation (decision per heuristics):** InsightFace embeddings never enter the production schema. A shared table with `model_id` is infeasible anyway — a pgvector column has one fixed dimension, and 512D buffalo cannot share a `vector(128)` column or its index. Bench embeddings live in **eval-harness run artifacts (npz/JSON) plus, if needed, a dedicated eval-tenant deployment** with buffalo-dimensioned schema, never the prod DB (ARCH-02 single writer; DOM-03 bounded contexts; license isolation for free). **Prod performance impact: none** — no per-query model filter, and smaller vectors.

### 4.3 Explicitly NOT touched

Clustering algorithms (cosine on unit vectors — dimension-agnostic), roster module, curation/workbench UX, scene/describe + VLM captioning, tenant/RLS machinery. The WP plugin never touches embeddings, but the age/gender **field removal is consumer-visible** (`stores.py` projection, `export_service.py` snapshots): FIR-2's consumer audit confirms whether the plugin/workbench read those fields before the contract change lands (DATA-03).

### 4.4 Thresholds (all recalibrated, never copied — guide §8.1)

`ClusteringSettings.similarity_threshold` (0.55) and `ClusteringLimitsSettings.similarity_threshold` (0.6) — two distinct knobs in `recognition/config/settings.py` — `IdentityDetectionSettings.default_threshold` (0.45), `QualitySettings` pose divisor / min face size, per-cluster `similarity_threshold`, curriculum/maturity adjustments. SFace geometry ≠ buffalo geometry; every one comes out of FIR-6 calibration.

## 5. Expected performance drop

Literature-derived expectation — **the bake-off is the real answer** (PERF-06 measure-don't-guess; the guide: "the principal unresolved question is accuracy on ACX data"):

- **Recognition (SFace 2021dec vs buffalo_l ArcFace-R50):** near-parity on easy/frontal faces (LFW-class: ~99.6% vs ~99.8%); the gap widens on hard slices — expect roughly **3–7 points TAR at fixed FAR** worse on profile/low-res/occluded faces (IJB-C-class protocols), which is exactly the WP-media long tail. 128D vs 512D also means less headroom for very large galleries; irrelevant at current tenant roster sizes.
- **Detection (YuNet vs SCRFD-10GF):** WIDER-hard AP ~0.81 vs ~0.83–0.85 — expect a few percent more **missed small/blurry/extreme-pose faces**; near-parity on medium/large faces. YuNet is dramatically cheaper on ARM CPU, which the production path needs.
- **Recoverable:** multi-observation aggregation (cluster representatives/medoid templates), quality-gated enrollment, per-tenant threshold calibration, and the curation loop absorb part of the single-image gap. Net product-level effect plausibly lands at a **small increase in unassigned faces and curation corrections** rather than wrong-identity assignments — provided the unknown threshold + ambiguity margin are calibrated conservatively (§8.1 of the guide).
- **Throughput is measured, not assumed** (PERF-01/06/07): the bake-off carries a perf leg — embeddings/sec and sec/image on the ARM A1 (and A10), cost per 1k images, p95 scan latency — and a recorded perf budget (≥ parity with the buffalo CPU path, or an explicit operator-accepted budget) is part of the gate inputs. "YuNet is dramatically cheaper" stays a hypothesis until this leg reports.

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

`scripts/eval_harness/` (VLM-2A) **already scores face-recognition P/R** — detection + identification, micro + per-identity macro — against the golden manifest via the live service (`analyze`/`wait_job`/`media_identities`), with seeded eval roster (`seed_roster.py`), deterministic re-scoring, and bounded-stall discipline. Golden manifest v2 is populated (88d5d820); VLM-6's Golden-150 curation extends the corpus (locked at 150 per VLM-6 continuity artifact — earlier docs say "Golden-100").

Gaps to close for this bake-off (FIR-5):

1. **Candidate swapping**: harness benchmarks *the deployed service*, one model stack at a time. Need either an env-selected face-pipeline profile on an eval instance (mirroring the hosted-provider pattern) or an offline in-process leg that runs detector+embedder candidates directly over the golden corpus.
2. **Cluster-level metrics**: identification P/R exists; **false-merge/false-split rates, cluster purity, unknown-rejection at fixed FAR** (guide §12.2) do not. Neither does per-slice aggregation: golden manifest entries (37, verified) carry no hard-case tags — FIR-5 reads VLM-6's per-entry `domain` tags (`masked`, `sunglasses`, `occlusion_other`, `profile`, `low_res`, `blur`, `similar_people`, `unknown`) and adds per-slice metric rollups, with **the occlusion family first-class and split three ways** — masks and sunglasses are distinct, product-frequent failure modes in user uploads and cheap to separate at tagging time. Slice floors: scope doc §FIR-5 slice sizing.
3. **buffalo_l reference leg** must run in the non-commercial eval environment only (`[bench]` extra), embeddings confined to run artifacts (§4.2 separation).
4. **Corpus breadth**: the 37-entry golden manifest (harness README says "38-image"; count verified 37) is thin for threshold calibration; extend with Golden-150 + hard-slice additions (profile/low-res/blur/similar-people/unknowns, demographic slices).

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

1. **SFace accuracy on ACX hard slices** — top risk; escalation ladder pre-agreed: SFIQA-class learned quality model → SeetaFace6 → licensed InsightFace hosted-service quote → commercial SDK → custom training (last).
2. **OpenCV 4.12-pin vs OpenCV 5** for YuNet 2026may dynamic-input support — resolve in FIR-3 (ORT-first inference makes OpenCV version mostly a reference-impl concern).
3. **Quality scoring without native pose** — landmark-derived roll/yaw proxies + sharpness + embedding magnitude; validate against curation outcomes in FIR-6.
4. **Eval-tenant isolation** — buffalo embeddings must be provably absent from prod (image audit + `[bench]` extra + run-artifact-only storage).
5. **Threshold cold-start** — until calibration lands, defaults must fail toward "unknown" rather than false assignment.
6. **Greenfield is an assumption until FIR-2 verifies it** — live demo/prod tenants exist; wiping rosters/curation at re-scan needs recorded operator sign-off and, if any tenant's curation matters, a communicated re-scan plan (RLSE-04/05).
7. **Rollback** — see the scope doc's Rollback section (RLSE-08): full revert is possible only pre-launch while buffalo remains lawful in non-commercial envs; post-switch-over the embedder is roll-forward-only, with the pipeline flag degrading recognition to fail-closed intake rather than reverting weights.

## 10. Addendum (2026-07-15): occlusion dimension + 11-paper technique sweep

**The occlusion family is first-class and split into three tags** (§7 gap 2): `masked` and `sunglasses` — the two product-frequent occluders in user uploads — plus `occlusion_other` (hands, hair, objects, partial framing). Each gets tagged real examples in the extended golden corpus **and** a **synthetic-paired protocol** — deterministic mask/sunglasses/patch overlays applied to existing golden faces so every occluded measurement has an unoccluded twin (isolates the occlusion effect per candidate and carries the statistical power; same trick OccFace uses to generate visibility pseudo-labels). Real tags stay small and validate the synthetic slices (scope §FIR-5 slice sizing).

Eleven user-supplied papers ingested (2512.11683 … 2607.05702). Per-paper verdicts:

| Paper | Technique class | Verdict for ACX |
| --- | --- | --- |
| 2607.05702 FASR++ (diffusion face SR + multi-embedding Feature Combiner) | GPU diffusion at inference | SR impractical CPU-first; **borrow: multi-embedding aggregation** (training-free with SFace) |
| 2607.03581 PLGSA (periocular attention + occlusion-adaptive cosine threshold) | new embedder + inference trick | Model unusable (no code, 858-image eval, AUC 1.0 — credibility flag); **borrow: OACT concept** — occlusion-severity-modulated match threshold |
| 2607.03073 (EfficientNet-B0+CBAM, hybrid loss) | full retrain, replaces SFace | Skip — generic architecture paper, unverifiable venue, no weights |
| 2606.23230 (privacy ReID, transformer + Hungarian assignment) | body ReID, not faces | **Borrow: Hungarian one-to-one within-photo assignment** — pure post-processing, zero retraining |
| 2605.19821 LaCoVL-FER (landmark-gated sparse attention + CLIP) | expression, heavy (CLIP) | Skip for MVP; architectural reference only if we ever train an occlusion-aware embedder |
| 2602.10728 OccFace (100-pt landmarks + per-point visibility) | new landmark model, no weights released | **Borrow: per-point visibility as occlusion gate/weight** — cheap proxy version from YuNet's 5 landmarks + patch statistics |
| 2602.07403 SFIQA (lightweight 6-dim surveillance face IQA, EdgeNeXt) | small auxiliary quality model | Closest to adoptable as a model (CPU-feasible XXS/XS), but weights/license unconfirmed — heuristic quality gate first, SFIQA-class model only if measured gap |
| 2601.12736 KaoLRM (LRM→FLAME 3D reconstruction) | heavy transformer, 3D output | Skip — wrong output type for identity, GPU-class |
| 2602.00635 S3POT (occlusion segmentation via GAN inversion + SAM) | GPU stack | Skip for live path; at most offline GPU curation/labeling of the golden corpus's occlusion slice |
| 2601.06239 (classical FR survey) | survey, pre-CNN methods | Noise — skip |
| 2512.11683 Depth-Copy-Paste (depth-aware compositing augmentation) | detector retraining | Only helps if bake-off shows occlusion losses are *detection misses*; then a YuNet retrain candidate (escalation, not MVP) |

### 10.1 Commonalities (heuristics-clustered)

Four patterns recur; they compose into one ordered strategy — **gate → weight → aggregate → constrain** — all operating *around* a fixed embedder:

1. **Degradation-aware gating** (SFIQA, OccFace, S3POT, PLGSA — 4/11): don't repair bad crops, *detect* them and gate/down-weight before they pollute the gallery. REF-20 (define errors out of existence): an occluded face becomes a normal, handled input class ("observed, low-confidence"), not a silent false assignment.
2. **Multi-observation aggregation** (FASR++, plus Cluster-and-Aggregate from §6): fuse several embeddings per identity. ALG-06 (catalog before code): plain mean/medoid of L2-normalized SFace vectors is the zero-cost version and is already our cluster-representative machinery.
3. **Degradation-conditioned thresholds** (PLGSA OACT): raise the match threshold as occlusion severity rises. Maps directly onto existing code — `compute_identity_quality()` already returns `threshold_adjustment`; occlusion severity becomes one more input, not a new subsystem (REF-15 seam reuse).
4. **Constraint-based assignment** (2606.23230): within one photo, each roster identity appears at most once — greedy per-face nearest-neighbor ignores this; Hungarian assignment over the face×candidate cosine matrix enforces it. ALG-01 (graph in disguise): it's a textbook assignment problem (`scipy.optimize.linear_sum_assignment`), zero model cost, and directly attacks the guide's "multiple similar-looking people in one image" slice. **Caveats** (RLSE-06): the one-to-one premise is false for mirrors, collages, and photo-in-photo; it runs *after* the quality gate (never rescues gated crops), and the mirrors/reflections bake-off stratum measures whether it must be disabled per-image or per-tenant.

Everything else in the sweep (diffusion SR, GAN inversion, SAM, CLIP, LRM, detector retraining) fails ARCH-08 + the CPU-first intake decision and moves to the escalation ladder or offline curation.

### 10.2 Answer: "a new CNN method?"

**No.** None of the 11 provides a commercially licensed, CPU-viable, occlusion-robust *embedder* (2/11 release code, 0/11 release usable weights+license). The evidence across the sweep is that hard-case recovery in our regime comes from pipeline intelligence around SFace: quality/occlusion gating (heuristic signals first: YuNet landmark confidence, eye-region sharpness/Laplacian, embedding magnitude per AdaFace/MagFace), OACT-style threshold adjustment, representative aggregation, and Hungarian within-photo assignment. If the occlusion slice still fails the (post-bake-off) gate after those land, the escalation is FIR-8: SFIQA-class learned quality model → SeetaFace6/licensed-InsightFace → occlusion-aware embedder training (LaCoVL/OccFace as design references) — training last, per the guide's data-governance warning.

Credibility triage (PERF-06 measure-don't-guess; AGT-04 evidence discipline): 2607.03581 and 2607.03073 have weak-rigor signals; their reported metrics must not seed thresholds or gate arguments.

### 10.3 OpenCV 5 / new libraries

OpenCV 5.0 (June 2026, Apache-2.0) helps **speed, not accuracy**: rewritten graph-based DNN engine (ONNX op coverage ~22%→80%+, dynamic shapes — what YuNet 2026may wants), **ARM KleidiCV acceleration for AArch64** (exactly our acx-backend CPU), FP16/BF16 Mat types. Costs: C++17 floor, 4.x→5 API migration. This tips open question §9-2 toward **pin OpenCV 5 in FIR-3** for the reference/CPU path while ONNX Runtime stays the primary inference route; re-run the golden parity tests after the pin (rg-010-adjacent: verify, don't assume). New libraries beyond that: **scipy** (or a ~40-line Hungarian implementation if we don't want the dependency) for assignment; explicitly *not* adopting SAM/CLIP/diffusion stacks in the MVP.
