# FIR-4 plan adversarial review (grok / fir-4-grok)

**Subject:** `docs/tasks/fir/FIR-4-runtime-integration-task-plan.md` @ `74ac23074cc4f9040108a4b2fe9c2ff33631c5ac` (`feature/fir-4`)  
**Role:** adversarial planning reviewer (external, independent)  
**Scope:** plan-only attack; no plan edits; claims verified against code in this worktree  

## VERDICT: pass_with_findings

Architecture (dark profile flag, shared factory intent, FIR-3 bridge composition, fail-closed model verify, license isolation, ORT bump as SERVE-07) is directionally sound. Implementation will still mis-fire unless the plan is corrected on: (1) S1 quality-gate vacuous pass when ONNX is absent, (2) dual dim sources (`PGVECTOR_DIM` vs `identity_detection.embedding_dimension`), (3) ScanService generate-path that never receives face crops, (4) S4 observability site/API names that do not exist, and (5) /ready remaining InsightFace-bound.

---

### GR-01 — high

**Plan section:** S1 Rider-1 ORT bump / Verification Strategy / Consolidated Checklist S1  
**Heuristic:** SERVE-07, TEST-06, RLSE-05  
**Code evidence:** `recognition/tests/unit/face_pipeline_support.py:27-35` (`MODELS_PRESENT` + skip string); dozens of `@pytest.mark.skipif(not MODELS_PRESENT, …)` in `test_face_pipeline_opencv_ref.py` / `test_face_pipeline_ort_parity.py`; models dir currently has LICENSE/README only (ONNX gitignored); plan L81 treats fetch as “prereq for any real-path run”, not S1/CI gate.

**Attack:** S1 gate is “FIR-3 parity suite (79 tests) green on bumped ORT”. Without model bytes, inference/parity tests **skip** (pytest still exits 0). S1 can merge ORT≥1.22 with zero ORT inference exercised — false quality gate for a behaviour-changing serving change.

**Fix:** Require model fetch (or fixture cache) before S1 and `make check-remote`; fail the gate if model-gated tests skip (e.g. `pytest -rs` + assert zero MODELS_SKIP, or CI step `fetch_face_pipeline_models.py` then re-run suite). State this in S1 verification explicitly.

---

### GR-02 — high

**Plan section:** Constraints “One embedding space” / Target Outcome / Not-Doing (PGVECTOR_DIM=128) / S2 dim guard  
**Heuristic:** EMB-01, PROV-08, DATA-03  
**Code evidence:** `db/settings.py:241` (`PGVECTOR_DIM` default 512); `recognition/config/settings.py:59` (`embedding_dimension: int = Field(default=512)` — **no env binding**); `recognition/shared/similarity.py:12-14` (`face_embedding_dim()` → settings embedding_dimension); `recognition/application/embedding/manifest.py:32-40` (incumbent manifest dims from settings, not pgvector); `recognition/application/scan/service.py:70,318-349` (writes `det.embedding.tolist()` with **no** length check); `db/models/identity.py:58` (`Vector(_DB_SETTINGS.pgvector_dimension)`).

**Attack:** Plan only requires factory `pgvector_dimension == manifest.dimensions`. Dark 128D eval via `PGVECTOR_DIM=128` leaves `identity_detection.embedding_dimension` at 512. Clustering/similarity still slice/compare as 512; ScanService never validates vector length before INSERT. Mixed-space rows or silent dimension skew are still possible if factory is the only guard, or if settings drift from env.

**Fix:** Single dim source of truth for face_pipeline path: bind/assert `embedding_dimension == pgvector_dimension == manifest.dimensions` at factory + settings load; reject writes when `len(embedding) != pgvector_dimension`; document that dark 128D requires both env (or a single env) and empty/recreated DB column (greenfield `001_identity_schema.py` still hardcodes 512 at L14).

---

### GR-03 — high

**Plan section:** S2 Bridge (`FacePipelineFaceDetector` + `FacePipelineEmbeddingGenerator`); Current State / Transform parity  
**Heuristic:** SERVE-01, SERVE-08, TEST-03  
**Code evidence:** `recognition/application/scan/service.py:277-282` fills missing embeddings via `self._generator.generate([str(det.media_id).encode(), …])` — **media_id bytes, not image/crop bytes**; InsightFace production path attaches embeddings inside `detect` (`infrastructure/embeddings/__init__.py:130-178` → `FaceDetection.embedding=face.normed_embedding`); generator is a backup path, not the primary crop embedder.

**Attack:** Plan composes YuNet→align→SFace on both detector and generator protocols without specifying that **detect must return populated embeddings** (incumbent contract). If detector leaves `embedding=None`, generator receives nonsense `media_id` bytes and cannot run SFace on crops — silent wrong embeddings or hard failures. Separate generator class implies a second full pipeline that ScanService cannot feed correctly today.

**Fix:** Decide and document: (a) `FacePipelineFaceDetector.detect` returns `FaceDetection` **with** embedding (mirror InsightFace one-pass), generator optional/Unavailable for this profile; or (b) change ScanService to pass real image/crop bytes (larger scope — call out as explicit S2/S3 work). Do not leave dual classes without a feedable generator contract.

---

### GR-04 — high

**Plan section:** S4 Observability  
**Heuristic:** OBS-01, OBS-02, OBS-03, OBS-08  
**Code evidence:** No `ScanService._reconcile` anywhere (`rg` empty); match/new logic is inline in `_persist_identities` (`scan/service.py:284-365`); `ScanItemHandler` only used by worker (`worker/handlers/scan.py:30-102`); HTTP path builds `ScanService` via `get_scan_service_builder` (`deps/services.py:365-418`) and never touches the handler; inline task path is `tasks/scan.py` + `run_scan_three_phase`; scan path stores `quality_score` but does **not** reject faces via assignment quality gating (`compute_identity_quality` is assignment/clustering — `assignment/quality.py:25+`, used from detector quality helper and stores, not as scan-time reject counter).

**Attack:** (1) Plan cites a non-existent `_reconcile` API. (2) Emitting only at `ScanItemHandler` makes S4 **worker-only**; HTTP/inline scans (two of three construction sites) get no wide event — coverage hole vs Target Outcome “per-scan detection count … in logs/metrics”. (3) “quality-gate rejection count from assignment path” is not a scan-time signal today; inventing it at handler completion will be zero/undefined without new gating.

**Fix:** Emit from `ScanService.process_media_item` / `_persist_identities` (shared by all paths) or require explicit dual emission; name real counters (matched / new / orphaned from `_persist_identities`); redefine “quality-gate rejections” as either detection-time quality thresholds (new behaviour — SERVE-03) or drop until assignment instrumentation exists.

---

### GR-05 — medium

**Plan section:** S3 Wiring / shared factory; Problem Statement “three symmetric sites”  
**Heuristic:** SERVE-01, REF-15  
**Code evidence:** `scan_worker.py:211-216` — `InsightFaceFaceDetector(adapter, client=self._http_client)`; `tasks/scan.py:105-113` — optional `adapter_provider`, no httpx client; `deps/services.py:398-401` — shared adapter only, no client. face_pipeline needs `FacePipelineSettings`/models_dir, not InsightFace adapter.

**Attack:** Sites are **not** symmetric. A single factory without an explicit DI surface for `http_client`, `adapter_provider`, and profile-specific deps will either re-fork glue or drop URL-fetch / custom-adapter behaviour on one site (worker vs task).

**Fix:** Specify factory signature (e.g. `build_embedding_runtime(*, settings, http_client=None, adapter_provider=None) -> (detector, generator)`) and map each call site’s extra args; face_pipeline branch ignores adapter_provider and uses verified model load.

---

### GR-06 — medium

**Plan section:** Constraints timeouts/breaker; S2 timeout wrapper  
**Heuristic:** RES-02, RES-03  
**Code evidence:** Incumbent is **two-layer**: `run_in_executor` in `InsightFaceAdapter.detect_faces` (`embeddings/__init__.py:146-148`) + `wait_for_adapter` + circuit breaker in `InsightFaceFaceDetector` (`detector.py:187-189,250-256`); ORT adapters are **sync** (`ort_adapters.py:350-368,398-404`); `wait_for_adapter` only wraps awaitables (`integrations/timeouts.py:21-32`) — does not itself offload CPU.

**Attack:** Plan says “executor/timeout pattern” but omits breaker parity and the fact that timeout-alone on a sync call still blocks the event loop unless work is executor-wrapped first. Incomplete bridge = event-loop stall or missing open-breaker fail-closed behaviour vs incumbent.

**Fix:** Require bridge: `run_in_executor` (or equivalent) for decode/detect/align/embed **and** `wait_for_adapter` + `create_adapter_circuit_breaker` with named adapters; mirror timeout source (`FacePipelineSettings.timeout` / `DB_EMBEDDING_TIMEOUT_SECONDS`).

---

### GR-07 — medium

**Plan section:** S3 boot `check_model_cache`; Contract Impact `/ready`  
**Heuristic:** EMB-05, DRIFT-02, OBS-08, PROV-01  
**Code evidence:** `health.py:65-77` — counts `*.onnx` under buffalo dir only; `api/main.py:285-311,335` — `register_health_probes` hardcodes `cache_dir = settings.insightface.model_cache_dir`, `model_name = settings.insightface.model_name`; face_pipeline uses `load_verified_model` + `DEFAULT_MODELS_DIR` / `MODEL_MANIFEST` (`face_pipeline/provenance.py`).

**Attack:** Extending `check_model_cache` without rewiring call-site inputs leaves `/ready` verifying the **wrong** tree when profile=`face_pipeline` (buffalo present → OK while YuNet/SFace missing/tampered, or vice versa). OBS-08: readiness success ≠ pipeline health.

**Fix:** Profile-aware probe inputs in `register_health_probes` / both `/ready` and `/health/detailed`; face_pipeline branch must call sha256 path via `load_verified_model` (or shared helper) against `FacePipelineSettings.models_dir`; incumbent branch keeps buffalo count or also upgrades.

---

### GR-08 — medium

**Plan section:** S1 ORT bump under dark default  
**Heuristic:** SERVE-07, TEST-03, RLSE-07  
**Code evidence:** `pyproject.toml:32` `onnxruntime>=1.16.0` is a **core** dep used by production InsightFace today (`embeddings/__init__.py` FaceAnalysis/ORT providers); production default profile remains insightface until FIR-6.

**Attack:** S1 ships a behaviour-changing ORT bump into the **live** incumbent path, while the named quality gate is the face_pipeline parity suite. Incumbent characterization under ORT 1.22 is unspecified — dark flag does not isolate the ORT upgrade.

**Fix:** Add incumbent smoke/characterization (or existing InsightFace unit suite with mocked adapter + one real-path smoke where available) as S1 co-gate; document rollback (`onnxruntime` pin revert) if buffalo regressions appear.

---

### GR-09 — low

**Plan section:** S5 license isolation / Contract extras matrix  
**Heuristic:** RLSE-05, rg-006  
**Code evidence (consumers of `[face]` / insightface install):** `pyproject.toml:69-73`; `README.md:24`; `scripts/setup.sh:36-39`; `scripts/install_insightface_mac.sh:23`; `Dockerfile:32-38` (`pip install ".[face]"`); docs/runbooks/epics referencing `--extra face`. Plan S5 lists the sweep — direction correct.

**Attack residual:** S1 bumps ORT before S5 rewires Dockerfile/`setup.sh`; interim docs still say `--extra face`. Low risk if S5 is mandatory before any deploy claiming license isolation; state ordering dependency (S5 before release artifact claims).

**Fix:** Explicit “no production image rebuild claiming FIR-4 complete until S5”; keep interim install docs annotated.

---

### GR-10 — low

**Plan section:** S2 transform parity / quality metadata  
**Heuristic:** SERVE-08, PROV-06  
**Code evidence:** YuNet `RawDetection` is xywh + landmarks + score (`ort_adapters` / FIR-3 types) — **no pose pitch/yaw/roll**; InsightFace fills pose (`embeddings/__init__.py:155-172`); detector quality uses pose (`detector.py:40-72`).

**Attack:** face_pipeline detections will systematically score quality differently (pose=None → weaker penalties). Not a plan contradiction, but FIR-6 calibration and S4 “quality” fields will not be comparable across profiles unless documented.

**Fix:** Stamp pose nulls explicitly; document quality non-parity; avoid treating cross-profile quality metrics as interchangeable in S4 events.

---

## Attack angles that produced no finding

1. **Three construction sites exist** — claim accurate (`scan_worker._ensure_embedding_runtime`, `tasks/scan.py`, `get_scan_service_builder`). Shared factory is the right SERVE-01 move; only the DI surface is under-specified (GR-05).
2. **FIR-2 async protocol vs FIR-3 sync numpy APIs** — claim accurate; plan correctly requires a bridge and names executor/timeout (detail gap only → GR-06).
3. **`check_model_cache` is file-count only** — claim accurate (`health.py:65-77`); extension to sha256 is the right EMB-05 fix if call sites follow (GR-07).
4. **`onnxruntime` core pin + insightface in `[face]`/`[gpu]`** — claim accurate (`pyproject.toml:32,69-73`); S5 consumer sweep list matches real scripts/Docker/docs.
5. **Dark default / single flag / rollback-is-flag / no schema flip in FIR-4** — consistent with code and RLSE-07/08; Not-Doing list coherent.
6. **`Unavailable*` fail-closed on adapter load** — already pattern at all three sites; plan extends it correctly in spirit.
7. **Import placement of bridge beside incumbent** (`infrastructure/embeddings/face_pipeline_adapter.py`) — preserves face_pipeline purity tests; no conflict found.
8. **Flat env vars on plain pydantic `BaseModel`** — matches `RECOGNITION_RUNTIME_MODE` pattern (`config/settings.py:111`); no nested pydantic-settings delimiter in codebase.

---

## Summary for plan authors

| ID | Sev | One-liner |
| --- | --- | --- |
| GR-01 | high | S1 ORT gate vacuous without model fetch / non-skip enforcement |
| GR-02 | high | Dual dim knobs; factory-only guard insufficient for EMB-01 |
| GR-03 | high | Bridge must attach embeddings in detect or fix ScanService crop feed |
| GR-04 | high | S4 cites `_reconcile`; worker-only emission misses HTTP/inline |
| GR-05 | medium | Factory must name http_client / adapter_provider differences |
| GR-06 | medium | Need executor **and** wait_for_adapter **and** breaker, not “timeout” alone |
| GR-07 | medium | /ready call sites still InsightFace cache_dir/model_name |
| GR-08 | medium | ORT bump hits live buffalo path; gate only face_pipeline suite |
| GR-09 | low | S5 consumer sweep real; order vs release claims |
| GR-10 | low | Pose/quality non-parity across profiles |

**Recommended re-review:** after plan amendments for GR-01..04 (high); mediums can ride the same pass.
