# FIR-4 plan adversarial review (grok / fir-4-grok)

**Subject:** `docs/tasks/fir/FIR-4-runtime-integration-task-plan.md` @ `c93b4459b432813801173e96273493b76cfa0b49` (blob after BR-01..15 revision; branch `feature/fir-4` HEAD also carries S1 ORT bump `59972be7`)  
**Role:** adversarial planning reviewer (external, independent)  
**Scope:** plan-only attack; no plan edits; every claim below re-verified against code in this worktree  

## VERDICT: pass_with_findings

Post-BR-01..15 plan is substantially hardened: models-present S1 gate, incumbent ORT co-gate, one-pass bridge, three-way dim guard, atomic profile activation, ScanService-level observability, factory DI surface, executor+breaker parity language, profile-aware `/ready` intent, and `[face]`→`[bench]` keep-insightface-in-image are all coherent with the code. Residual defects are factual mis-specs and incomplete process-lifecycle design that can still ship wrong decode semantics or pre-first-request readiness holes.

---

### GR-01 — high

**Plan section:** Constraints “Transform parity” / S2 decode golden  
**Heuristic:** SERVE-08, TEST-03  
**Code evidence:** `recognition/infrastructure/embeddings/__init__.py:117-128` — methods are `_pil_to_cv2` / `_bytes_to_cv2`: `Image.open` → optional `convert("RGB")` → `np.array` → `cv2.cvtColor(..., COLOR_RGB2BGR)`. **No** `ImageOps.exif_transpose`, **no** method named `_decode_image`. Repo-wide `rg exif_transpose` under the service is empty.

**Attack:** Plan claims the bridge must decode “identically to the incumbent — PIL open → **EXIF-transpose** → RGB → BGR (`InsightFaceAdapter._decode_image` semantics, embeddings/__init__.py:117-128)”. That is a **false code citation**. Implementing EXIF transpose “because the plan said so” creates decode drift vs buffalo, which is the opposite of SERVE-08. A golden fixture that embeds EXIF orientation would pin the *wrong* incumbent.

**Fix:** Rewrite the decode spec to match real `_bytes_to_cv2` (open → RGB → BGR, no EXIF). Name the real methods. Golden fixture must be generated from the incumbent helper (or a byte-identical reimplementation of those two methods only).

---

### GR-02 — high

**Plan section:** Contract Impact `/ready` / S3 profile-aware probes  
**Heuristic:** EMB-05, DRIFT-02, OBS-08  
**Code evidence:** `api/main.py:279-335` — `register_health_probes` binds cache paths at registration and calls `check_model_cache` (file count only today: `health.py:65-77`); probes never construct detectors. Detector construction is lazy: worker `_ensure_embedding_runtime` (`scan_worker.py:204-224`), HTTP builder on first use (`deps/services.py:388-412`), inline task at job start (`tasks/scan.py:94-121`). Worker and API are **separate processes**.

**Attack:** Plan says face_pipeline `/ready` “reflects the construction-time `load_verified_model` outcome … with staleness caught by an mtime+size check; full sha256 runs at load, not per probe.” Before any construction in the API process, there is no construction outcome. mtime+size-only readiness reintroduces the exact EMB-05 hole (present bytes ≠ verified bytes) for every pod between boot and first face_pipeline scan. A tampered ONNX that still has the expected size can keep the LB green until traffic hits.

**Fix:** Require **eager** profile-aware verification at API process boot (or first probe if prior outcome is missing): run `load_verified_model` once, cache (ok|reason, mtime, size); probes re-check mtime/size against that cache and flip UNHEALTHY on drift without re-hashing unless stale. Do not allow mtime+size alone to green-light never-verified models. Worker path already constructs; state the API-process boot path explicitly.

---

### GR-03 — medium

**Plan section:** S2/S3 shared factory / Target Outcome  
**Heuristic:** SERVE-01, RES-03, COST-04  
**Code evidence:** Incumbent is a process singleton: `get_shared_insightface_adapter` (`embeddings/__init__.py:204-213`) with double-checked lock + `ensure_loaded`. HTTP and worker both go through it. Plan’s factory signature returns `(detector, generator)` but never requires an equivalent process-wide cache for YuNet/SFace ORT sessions (~tens of MB + session init).

**Attack:** Without a named singleton (or factory-level memo), `get_scan_service_builder`’s per-request path can re-open ORT sessions / re-read model files every scan under load. Worker would load once; HTTP would thrash. That is both a latency/resource footgun and a partial-failure surface (load errors mid-traffic vs boot).

**Fix:** Specify `get_shared_face_pipeline_runtime()` (or factory memo keyed by profile+models_dir+thresholds) parallel to `get_shared_insightface_adapter`, with a test reset hook. Atomic activation stays: failed load → cached Unavailable*, not half-open sessions.

---

### GR-04 — medium

**Plan section:** Constraints “Timeouts + breaker parity” / S2 executor wording  
**Heuristic:** RES-02, RES-03  
**Code evidence:** Incumbent offloads with `loop.run_in_executor(None, self._app.get, cv2_image)` (`embeddings/__init__.py:146-148`) then `wait_for_adapter` + named breaker (`detector.py:187-189,250-256`). `wait_for_adapter` is pure `asyncio.wait_for` (`integrations/timeouts.py:21-32`) — cannot cancel a running thread. Worker bounds concurrency via `max_concurrency` (`handlers/scan.py` semaphore); HTTP/inline scan paths have **no** equivalent inference concurrency cap.

**Attack:** Plan correctly admits timeout cannot cancel ORT, but the alternative “documented reliance on the worker's `max_concurrency` bound” **does not cover** HTTP builder / inline task paths. Default-executor ORT under concurrent `/analyze` can stall the event loop pool for the whole API process (shared with InsightFace if both profiles coexist during dark rollout tests).

**Fix:** Require a **dedicated** bounded executor (max_workers explicit) shared by the face_pipeline bridge in every process that runs it; do not accept “worker max_concurrency alone” as sufficient. Document that wait_for_adapter bounds the await, not the thread, and that pool saturation is the residual RES-03 risk with a named metric/log.

---

### GR-05 — medium

**Plan section:** S1 incumbent co-gate  
**Heuristic:** SERVE-07, TEST-03  
**Code evidence:** Core dep `onnxruntime` drives live buffalo today via InsightFace FaceAnalysis (`embeddings/__init__.py`, providers from settings). Face_pipeline suite never imports buffalo. Plan co-gate: scratch venv + insightface extra, **one** fixed-image embedding, cosine ≥ 0.999999.

**Attack:** Single-vector cosine on one image is a weak characterization of a behaviour-changing ORT minor-line bump (1.16→1.22+; resolved 1.26 on arm64 in S1). Detection count / multi-face / det_thresh edge cases can still move while one embedding stays nearly identical. Gate can pass while production detect behaviour shifts.

**Fix:** Expand co-gate minimally: ≥1 multi-face fixture + assert detection count stable and per-face embedding cosine ≥ threshold; record ORT version pair and fixture IDs in the slice decision. Keep pin-revert as rollback.

---

### GR-06 — low

**Plan section:** Constraints dim guard / ScanService write path  
**Heuristic:** EMB-01, PROV-08  
**Code evidence:** `scan/service.py:308-349` writes `det.embedding.tolist()` with **no** `len(embedding)` check; only `model_id` NOT-NULL `ValueError`. Column width is `Vector(_DB_SETTINGS.pgvector_dimension)` (`db/models/identity.py:58`). Two dim knobs remain real: `PGVECTOR_DIM` (`db/settings.py:241`) vs unbound `identity_detection.embedding_dimension` (`config/settings.py:59`).

**Attack:** Plan’s three-way factory assert (when profile=face_pipeline) plus S2 env binding largely closes the dual-knob hole for the new path. Residual: any future non-factory construction or a buggy bridge that emits wrong-length vectors still reaches INSERT without an application-level length guard; DB error text may not map cleanly to `Unavailable*` /ready. Low because greenfield + factory is the intended choke point.

**Fix:** One-line write-time assert `len(det.embedding) == pgvector_dimension` in `_persist_identities` (or shared helper) with a clear `ValueError` — defense in depth, cheap, EMB-01.

---

### GR-07 — low

**Plan section:** S1 ORT bump / Docker duality note  
**Heuristic:** SERVE-07, RLSE-05  
**Code evidence:** S1 regenerates `uv.lock` (repo path). `Dockerfile:32-38` still `pip install ".[face]"` with **no** lockfile pin — pip resolves `onnxruntime>=1.22` independently of `uv.lock`. Plan states pip-vs-uv duality is “untouched beyond extras rename.”

**Attack:** Local/models-present gate and image ORT can diverge (different 1.22.x). S1 evidence does not bind the deploy artifact.

**Fix:** Either pin ORT exactly in `pyproject.toml` for FIR-4, or add a deploy smoke that prints `onnxruntime.__version__` and fails outside an allowed band; record image ORT version in the S1/S5 close decision.

---

## Attack angles that produced no finding

1. **Three construction sites** — confirmed: `scan_worker._ensure_embedding_runtime` (`scan_worker.py:204`), `process_scan_job_inline` (`tasks/scan.py:70+`), `get_scan_service_builder` (`deps/services.py:365`). Asymmetry (http_client / adapter_provider / neither) is real; plan’s factory signature maps them — residual is singleton (GR-03), not site inventory.
2. **FIR-2 async protocol vs FIR-3 sync numpy adapters** — confirmed (`detector.py:119` async `Iterable[bytes|str]`; `ort_adapters.py:350` sync ndarray batch). Plan one-pass bridge + executor + wait_for_adapter + breaker matches incumbent layering intent (detail residual → GR-04).
3. **ScanService generate path is media_id bytes, not crops** — confirmed (`scan/service.py:277-282`). Plan’s one-pass detect→align→embed + `UnavailableEmbeddingGenerator` for the generator slot correctly avoids inventing a feedable crop pipeline.
4. **Dual dim knobs** — confirmed; plan three-way assert + `RECOGNITION_EMBEDDING_DIMENSION` + fresh-DB note for 128D addresses the high-severity dual-source hole (residual write assert → GR-06).
5. **`check_model_cache` is onnx-count only; call sites InsightFace-bound** — confirmed (`health.py:65-77`, `api/main.py:285-311`). Plan’s profile-aware rewiring is the right direction (lifecycle residual → GR-02).
6. **`[face]` / insightface install consumers** — confirmed: `pyproject.toml`, `README.md:24`, `setup.sh:39`, `install_insightface_mac.sh:23`, `Dockerfile:38`. S5 rename-to-`[bench]` while keeping image insightface matches dark default + `scan_worker` unconditional imports.
7. **MODELS_PRESENT skips** — confirmed (`face_pipeline_support.py:27-35`; dozens of `@skipif` in opencv_ref + ort_parity). Plan now requires fetch + zero `MODELS_SKIP` for models-present gates and correctly demotes `make check-remote` to inventory — closes prior GR-01 vacuous-gate finding.
8. **S4 observability site** — plan now emits from `ScanService` (not `ScanItemHandler`), renames `_reconcile` → structured result from `_persist_identities` (`scan/service.py:259-365` returns `int` today), drops invented quality-gate rejection metric. Worker/HTTP/inline coverage hole closed on paper; no residual finding.
9. **Dark default / single flag / rollback-is-flag / no schema flip** — consistent with RLSE-07/08 and greenfield policy; Not-Doing list matches code.
10. **Atomic activation + pose null non-parity** — correctly specified relative to `RawDetection` (no pose) and quality scoring in `detector.py`.
11. **Flat `RECOGNITION_*` env on plain pydantic `BaseModel`** — matches `runtime_mode` pattern (`config/settings.py:111`); no nested settings delimiter in codebase.
12. **Prior review GR-01..10 against pre-BR plan** — largely fixed by `c93b4459`; this document replaces that attack surface rather than re-litigating closed items.

---

## Summary for plan authors

| ID | Sev | One-liner |
| --- | --- | --- |
| GR-01 | high | Decode “EXIF-transpose / `_decode_image`” claim is false; match real `_bytes_to_cv2` |
| GR-02 | high | `/ready` must eager-verify face_pipeline models in API process; mtime+size alone is not EMB-05 |
| GR-03 | medium | Require process-wide face_pipeline runtime singleton like InsightFace |
| GR-04 | medium | Dedicated bounded executor for all processes; worker max_concurrency insufficient for HTTP |
| GR-05 | medium | Incumbent ORT co-gate needs multi-face / count stability, not one cosine only |
| GR-06 | low | Optional write-time embedding length assert as EMB-01 depth |
| GR-07 | low | Docker pip vs uv.lock can ship different ORT than S1 evidence |

**Recommended re-review:** after plan amendments for GR-01..02 (high); GR-03..05 can ride the same pass. Architecture is merge-ready as a plan once those two high findings are corrected in the plan text.
