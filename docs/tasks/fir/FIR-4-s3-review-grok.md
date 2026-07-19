# FIR-4 S3 adversarial code review (grok / fir-4-grok)

**Subject:** `910fb63c` (S3 wiring) + `0b570731` (gate-fix) on `feature/fir-4`  
**Contract:** `docs/tasks/fir/FIR-4-runtime-integration-task-plan.md` Constraints + S3 checklist  
**Role:** adversarial CODE reviewer (independent; did not author this code)  
**HEAD at review:** `0b570731cc92416e82df1f5b5bf5b0dbcffca4ef`  
**Pre-S3 baseline for characterization:** `99eaedd8`

## VERDICT: pass_with_findings

S3 delivers the shared `build_embedding_runtime` at all three construction sites, atomic face_pipeline fail-closed (both slots `Unavailable*`), test-mode stubs preserved, adapter_provider honored only on insightface, profile-aware `/ready` with eager sha256 + mtime/size re-verify (never OK without a process-local verified load), and capability heartbeat `profile=`. Characterization tests re-homed to the factory mock layer without deleting retry / fail-closed / non-stub assertions. Gate-fix modelless-ifies readiness without weakening status assertions; synthetic manifest still exercises real `load_verified_model` (license hash included). Residual findings: eager face_pipeline import on the dark default path, HTTP client creation moved before successful init, invalid-profile → probe 500 vs 503, and thin process-cache concurrency notes.

### Test evidence (this session)

```text
cd apps/prototype-description-service && uv run pytest \
  recognition/tests/unit/test_runtime_factory.py \
  recognition/tests/unit/test_face_pipeline_readiness.py \
  recognition/tests/unit/test_scan_worker.py -q
→ 35 passed in 1.94s, exit 0
```

---

## Findings

### S3R-01 — medium

**File:line:** `apps/prototype-description-service/recognition/infrastructure/embeddings/runtime_factory.py:29-34` (import); consumers e.g. `recognition/worker/scan_worker.py:36`  
**Heuristic:** COST-04, SERVE-01, rg-013 spirit (import surface)  
**Failure scenario:** `runtime_factory` **eagerly** imports `face_pipeline_adapter`, which module-level-imports `ort_adapters` (`onnxruntime`) and `aligner` (`cv2`). Every process that imports the factory (worker always; HTTP builder / inline task on first scan-service construction) pays the face_pipeline import graph even when `profile=insightface` (production dark default). Pre-S3 worker only imported `get_shared_insightface_adapter`. No worker/HTTP cycle (factory does not import those layers — cycle-safe), but the dark default path is no longer free of the new stack at import time; a broken/partial ORT install or import-time side effect can take down insightface-only processes before any profile selection.

**Fix:** Lazy-import `FacePipelineFaceDetector` / `get_shared_face_pipeline_runtime` / `face_pipeline_unavailable_generator` inside the `profile == "face_pipeline"` branch only.

---

### S3R-02 — medium

**File:line:** `apps/prototype-description-service/recognition/worker/scan_worker.py:208-218`  
**Heuristic:** TEST-03, RES-02 (resource lifecycle parity)  
**Failure scenario:** Pre-S3 (`99eaedd8`) created `httpx.AsyncClient(timeout=30.0)` **only after** `get_shared_insightface_adapter()` succeeded, inside the try block. Post-S3 creates the client **before** `build_embedding_runtime` and keeps it on the Unavailable failure path (retry-after-30s). Permanent/repeated init failure now opens a process-local HTTP client the old code never allocated until a successful adapter load; also changes ordering if factory construction itself depended on “no client yet” (today it does not, but default-path byte-identity of the worker init sequence is broken). `__aexit__` still closes the client — leak is bounded to worker lifetime, not unbounded.

**Fix:** Create/pass `http_client` only after a non-`UnavailableFaceDetector` result (or create inside factory when needed), matching pre-S3 “client exists iff runtime ready” semantics.

---

### S3R-03 — low

**File:line:** `apps/prototype-description-service/api/main.py:293-302` (`_model_probe` → `RecognitionSettings()`); `recognition/config/settings.py:125-132`  
**Heuristic:** RLSE-05, OBS-08  
**Failure scenario:** Invalid `RECOGNITION_FACE_PIPELINE_PROFILE` raises at settings load (`ValueError` / validation). `_model_probe` does not catch it, so `/ready` and `/health/detailed` throw → **HTTP 500** instead of aggregated UNHEALTHY **503**. Plan wants hard fail on bad config (correct for construction), but readiness probes lose LB-friendly 503 semantics and no longer return structured `checks[]` naming the bad profile. Scan/API builders similarly surface as 500 rather than fail-closed `Unavailable*` 503-style scan errors.

**Fix:** Catch settings/profile validation in `_model_probe` (and optionally factory) and return `CheckResult(..., UNHEALTHY, "invalid profile=...")` so probes stay 503 with a named reason; keep hard error at process boot / non-probe paths if desired.

---

### S3R-04 — low

**File:line:** `apps/prototype-description-service/recognition/application/health.py:28-29,89-114`  
**Heuristic:** EMB-05, DRIFT-02  
**Failure scenario:** `_FACE_PIPELINE_VERIFY_CACHE` is a process-global `dict` with **no lock**. Concurrent probe threads (sync work scheduled off the event loop, or multi-threaded ASGI) can interleave read-modify-write of the same key. Outcomes are immutable dataclasses so corruption risk is low on CPython, but a torn update could briefly serve a stale OK after mtime drift if one thread re-verifies while another returns a pre-drift cached OK. Not a cross-process issue (cache is per-process as required).

**Fix:** Guard cache get/set with a `threading.Lock` (same pattern as face_pipeline runtime `_SHARED_LOCK`).

---

### S3R-05 — low (intentional deviation; document)

**File:line:** `apps/prototype-description-service/api/main.py:382-386`; `recognition/worker/scan_worker.py:241-251`  
**Heuristic:** TEST-03, OBS-08  
**Failure scenario:** Default-path responses are **not** byte-identical to pre-S3: `/health/detailed` `model_cache` gains `"profile"`, and available capability heartbeats use `reason="profile=insightface"` instead of `reason=None`. Load-balancer `/ready` check shape for insightface remains the same function (`check_model_cache`) when profile default holds, but detailed/capability consumers that assert exact JSON or `reason is None` will break. S3 checklist explicitly requires profile on the heartbeat — treat as accepted contract expansion, not a silent regression, but call it out so FIR-6/ops clients update.

**Fix:** None required for S3 intent; note in close decision / API note that `reason` and detailed `model_cache.profile` are additive. Optionally keep `reason=None` when available and put profile in a separate field if strict byte-identity is mandated later.

---

## Attack surface results (checklist)

### 1. CHARACTERIZATION [TEST-03] — highest priority

Diffed vs `99eaedd8`:

| File | Change | Weakened? |
| --- | --- | --- |
| `test_scan_worker.py` | Mock moved from `get_shared_insightface_adapter` + InsightFace classes → `build_embedding_runtime` | **No.** Retry test still asserts `calls`, `_embedding_runtime_ready is False`, `_embedding_retry_after is not None`, non-stub handler, `DetectionAdapterError` message, second call after clearing retry. Reuse test still asserts single call + shared adapter identity via fake. Failure mock now returns `Unavailable*` (matches factory contract) instead of raising from adapter — equivalent to production post-S3. |
| `test_scan_tasks.py` | Same factory mock rewiring; `_prod_settings()` adds `face_pipeline.profile` | **No.** Breaker/init-fail/typed-failure assertions intact. `adapter_provider` failing path still uses real factory + provider (not mocked away). |
| `test_scan_service_phase_split.py` | Factory mock | **No.** Three-phase helper assertions unchanged. |

**Not high:** site tests no longer pin that *worker module* constructs `InsightFaceFaceDetector` directly — that construction moved into the factory and is covered by `test_runtime_factory.py` type tests. That is re-homing, not assertion deletion.

### 2. Default-path byte-identity (no env overrides)

| Site | Graph | Parity |
| --- | --- | --- |
| Factory insightface | `get_shared_insightface_adapter` → `InsightFaceFaceDetector(adapter, client=http_client)` + `InsightFaceEmbeddingGenerator(adapter)` | Classes + adapter singleton + default detector timeout 30s match. |
| Worker | Uses factory; client + timeout 30s | **S3R-02** client-before-success delta. Retry-after-30s on `UnavailableFaceDetector` preserved. |
| `tasks/scan.py` | `adapter_provider` → factory insightface branch | Honored; test mode via factory stubs. |
| HTTP `services.py` | factory, no client | Same as pre (no client on InsightFace detector). Settings now re-read **per builder call** (pre: once at builder creation) — behavior change only if env flips mid-process. |
| Install hint | still `[local]` extra string | Unchanged (S5 renames). |

### 3. Factory atomicity + import graph

- `profile=="face_pipeline"` failures: `except Exception` → both `UnavailableFaceDetector` + `UnavailableEmbeddingGenerator` with shared reason (`runtime_factory.py:76-79`). Covered by `test_factory_face_pipeline_failure_atomic_both_unavailable`.
- Runtime load is atomic unit in `_load_face_pipeline_runtime` / sticky integrity errors in `get_shared_face_pipeline_runtime`.
- Factory does **not** import worker or HTTP layers → no cycle. **S3R-01** eager face_pipeline import remains.

### 4. Eager readiness (BR-17 / EMB-05)

- `check_face_pipeline_models` / `_cached_verify_outcome`: miss or mtime/size drift → `verify_face_pipeline_model` → `load_verified_model` (full sha256 + license). Early return only when cache hit **and** mtime/size match on an existing file — never OK from mtime/size alone without a prior verify in-process.
- Cache is process-local (`_FACE_PIPELINE_VERIFY_CACHE`); test reset hook present. **S3R-04** no lock.
- insightface branch still calls `check_model_cache` — logic-identical; profile read **per probe** (not frozen at `register_health_probes` registration) — good for env flip; registration-time capture removed.
- Plan documents intentional readiness cache (not silent PA-10 violation of request-path caching): probe optimization after one verified load. Acceptable deviation vs “no cache OK for unverified bytes.”

### 5. `face_pipeline/provenance.py` +70

- Additive only: `ModelVerifyOutcome`, `verify_face_pipeline_model`, `verify_face_pipeline_models`. Still stdlib-only (hashlib/pathlib/dataclasses). No worker/HTTP imports.
- `load_verified_model` body and `MODEL_MANIFEST` pins unchanged vs `99eaedd8` (FIR-3 parity suite remains valid).
- Package root `__init__` still exports provenance load surface only (verify helpers optional on submodule).

### 6. Gate-fix `0b570731` vs `910fb63c`

- Real-model happy path: `@skipif(not MODELS_PRESENT)`.
- Tamper / missing half / drift / never-OK / probe branch: synthetic `MODEL_MANIFEST` + small files; still go through `verify_face_pipeline_model` → `load_verified_model` (size, sha256, **license_sha256**). Does not bypass license-hash checks.
- Status assertions (`ok` / `unhealthy`, artifact names, verify call counts) preserved or strengthened with an extra synthetic happy path. **No assertion weakening.**

### 7. `tasks/scan.py` + `services.py` error semantics

- Test mode: factory returns stubs; worker still short-circuits on `_runtime_mode == "test"` before factory (stubs from `__init__`).
- Invalid profile: validation error at settings load → **S3R-03** (500 vs fail-closed Unavailable / 503).
- Valid profile load failures: factory returns Unavailable* → detectors raise `DetectionAdapterError` on use (same fail-closed family as pre-S3), not silent stubs.

---

## No-finding attack list

Attacks attempted that **did not** yield a finding:

1. **Deleted retry-after-30s** — still set on Unavailable; test still clears and re-calls.
2. **Stub fallback in prod** — factory never returns stubs unless `runtime_mode=="test"`.
3. **Half-activation emitting detections** — face_pipeline failure yields both Unavailable; generator slot on success is intentional Unavailable for embed-in-detect.
4. **adapter_provider ignored on insightface** — factory uses provider when set; test proves shared singleton not called.
5. **adapter_provider used on face_pipeline** — ignored; test proves zero provider calls.
6. **mtime/size green-light without sha256** — empty cache always verifies; tests assert call counts.
7. **Gate-fix bypasses license hash** — synthetic entries set `license_sha256` and write license files; `load_verified_model` still checks them.
8. **Factory imports worker/HTTP** — does not; import graph clean of cycles.
9. **load_verified_model behavior change** — body identical; only append after the function.
10. **InsightFace detector timeout drop** — still default 30s; worker still passes shared client on success path (ordering issue is S3R-02 only).
11. **Characterization assertion removal on DetectionAdapterError message / non-stub handler** — still present.
12. **Process-wide readiness cache shared across profiles incorrectly** — insightface does not use the face_pipeline verify cache.

---

## S3 checklist mapping (reviewer view)

| Checklist item | Status |
| --- | --- |
| Shared factory at three sites | Met |
| Production default insightface | Met (factory + tests) |
| test mode stubs | Met |
| Atomic activation | Met |
| Eager profile-aware readiness + mtime drift | Met (S3R-03/04 residual) |
| Both profiles at every site tested | Met (`test_runtime_factory` site matrix) |
| Capability heartbeat profile | Met (S3R-05 additive reason) |
