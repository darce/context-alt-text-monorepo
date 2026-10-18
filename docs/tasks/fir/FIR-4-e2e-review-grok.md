# FIR-4 end-to-end whole-branch adversarial review (grok / fir-4-grok)

**Role:** EXTERNAL adversarial whole-branch reviewer (final pre-merge)  
**Subject:** entire `feature/fir-4` @ `cdb1ada9` vs merge-base `da8488b1`  
**Diff:** `git diff da8488b1..HEAD` — 48 files, +5148/−233, 28 commits  
**Prior coverage:** 5 slices + per-slice dual reviews (30 code findings closed). This pass attacks **cross-slice integration only** — does not re-report resolved CR/BR items.  
**Lane:** `fir-4-grok` · actor `grok-4.5`

## VERDICT: pass_with_findings

Branch is **mergeable for dark-default production** (profile=`insightface`): shared factory at all three construction sites, fail-closed face_pipeline activation, S4 emit-after-commit on worker + HTTP/inline, license isolation with insightface retained via `[bench]`, dim default still 512, buffalo still in image. Residual defects are **integration honesty / operability gaps** that only bite when the dark profile is activated under load or mis-dimensioned env — not silent dark-default regressions. No high-severity data-integrity break found on the wired paths.

### Test evidence (this session)

```text
cd apps/prototype-description-service && uv run pytest \
  recognition/tests/unit/test_runtime_factory.py \
  recognition/tests/unit/test_scan_service_observability.py \
  recognition/tests/unit/test_face_pipeline_readiness.py \
  recognition/tests/unit/test_scan_worker.py -q
→ 53 passed in 2.02s, exit 0
```

Static proof (no runtime install): handler line order `counters.record` @98–105 → `session.commit` @111 → `emit_pending_scan_media_reconciled` @112.

---

## Findings

### E2E-01 — medium

**File:line:** `apps/prototype-description-service/recognition/worker/handlers/scan.py:98-112`  
**Heuristic:** OBS-01, OBS-08  
**Failure scenario:** S4-fix3 correctly moved `scan_media_reconciled` **after** the handler-owned durable commit, but `ScanWorkerCounters.record(...)` still runs **before** `await session.commit()`. If `mark_item_completed` or `commit` raises after a successful flush (DB timeout, connection drop, constraint), the exception path rolls back identity + queue rows (no durable reconcile) and **does not** emit the success event — yet cumulative heartbeat counters (`media_processed` / `faces_detected` / `rows_matched` / `rows_new`) already advanced. Capability reason then overstates reconcile health vs durable state; silence-vs-health ([OBS-08]) is compromised for the only cumulative face of S4 metrics. Per-slice happy-path tests commit successfully and never assert “no counter bump without commit”.  
**Fix:** Call `counters.record` only after successful `session.commit()` (same gate as `emit_pending_scan_media_reconciled`), or stash counts and apply post-commit in one block.

---

### E2E-02 — medium

**File:line:** `apps/prototype-description-service/recognition/application/health.py:121-140` (`check_face_pipeline_models`) vs `face_pipeline_adapter.py:159-170,207-209` (three-way dim guard) vs `api/main.py:327-329`  
**Heuristic:** EMB-01, OBS-08, SERVE-01, DRIFT-02  
**Failure scenario:** Plan contract: when profile=`face_pipeline`, three-way `manifest.dimensions == pgvector_dimension == identity_detection.embedding_dimension` fails closed and is **surfaced via profile-aware readiness**. Implementation: factory/runtime load enforces the three-way guard and yields `Unavailable*`, but `/ready` for `face_pipeline` only runs sha256/license verify of YuNet+SFace. Operator sets `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline` with defaults still 512/512 (or any non-128 pair that still pair-matches each other): models hash-OK → **`/ready` 200**, while worker factory returns Unavailable → heartbeat `available=false` → analyze intake 503. LB keeps the pod; ops sees green readiness + red dispatch with dim-mismatch only in worker reason. S2 dim guard and S3 readiness disagree on “128D dark operable.”  
**Fix:** In `check_face_pipeline_models` (or `_model_probe` face_pipeline branch), also assert the three-way dim equality (reuse `assert_three_way_embedding_dimensions(sface_embedding_model_manifest())`); UNHEALTHY detail names the dim mismatch.

---

### E2E-03 — medium

**File:line:** `apps/prototype-description-service/recognition/infrastructure/embeddings/face_pipeline_adapter.py:478-493` + `recognition/worker/scan_worker.py:61` (`max_concurrency: int = 5`)  
**Heuristic:** RES-02, OBS-05  
**Failure scenario:** Plan Constraints required a dedicated pool and stated pool saturation residual gets a **named log/metric**. `detect()` does unbounded `await self._submit_semaphore.acquire()` **before** `wait_for_adapter` starts the timeout clock. Under worker default `max_concurrency=5` and face_pipeline `max_workers=2`, three of five concurrent media items can wait indefinitely for a semaphore slot while two ORT threads run (or residual after timeout). `DetectionTimeoutError` only applies post-acquire; queue-wait is invisible (no log, no metric). Unit test `test_semaphore_timeout_queues_third` documents the queue-on-semaphore behavior for the third call — integration with worker concurrency amplifies it when the dark profile is load-tested. Not a deadlock (async acquire is cancel-friendly if the task is cancelled), but job latency / stale reclaim can fire without a face_pipeline saturation signal.  
**Fix:** Bound acquire with `asyncio.wait_for(sem.acquire(), timeout=…)` (map to `DetectionTimeoutError` or a distinct queue-timeout), and/or emit a counter/log on wait > N ms; recommend `max_concurrency <= face_pipeline max_workers` (or document and default-align) for face_pipeline profile.

---

### E2E-04 — low

**File:line:** `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py:376-387` vs `recognition/worker/scan_worker.py:219-234` vs `recognition/application/tasks/scan.py:94-97`  
**Heuristic:** SERVE-01, SERVE-08  
**Failure scenario:** All three sites call `build_embedding_runtime` (good symmetry). Residual asymmetry: only the worker eventually attaches a long-lived `httpx.AsyncClient` to the detector after successful init; HTTP builder and inline task pass `http_client=None`, so URL-source face_pipeline (and insightface) paths open a fresh client per image via `_fetch_image`. Blob/file:// worker path and byte-fed tests hide this. Not a wrong embedding result, but connection/timeout behavior can diverge under HTTP URL media vs worker multipart bytes.  
**Fix:** Optional request-scoped or app-scoped shared client into `get_scan_service_builder` / inline detect (parity with worker), or document URL-fetch only on worker-owned client.

---

## Explicit no-finding attack angles

| # | Attack angle | Result |
| --- | --- | --- |
| 1 | Whole wired path: factory → FacePipelineFaceDetector → `_persist_identities` + `_emit_scan_media_reconciled` across worker / HTTP / inline | **Pass.** All three construction sites use `build_embedding_runtime`. Persist + model_id stamp shared. Worker: flush → commit → emit; HTTP/inline: `save_job_results` commit → emit. No pre-commit event emit; telemetry try/except cannot fail scan (S4CR-06). |
| 2 | Cross-slice contract: S2 dim guard + S4 ReconcileResult + S3 readiness meaning of “128D dark” | **Partial — E2E-02.** Stamp `opencv-sface@128d/l2/cosine` consistent (manifest → FaceDetection.model_id → DB `embedding_model` → event). Settings pair + factory three-way + persist length assert coherent when runtime loads; readiness does not include dim three-way. |
| 3 | Transaction + telemetry ordering (S4-fix3) | **Pass for events.** Handler-owned commit boundary restored; no double-emit; no emit on exception/rollback. **Counters not gated — E2E-01.** |
| 4 | Async/executor/breaker/semaphore interplay | **No deadlock found.** Sticky only `ModelIntegrityError`; config failures non-sticky. Release-on-worker-done prevents slot leak on asyncio cancel. Residual: unbounded pre-timeout acquire under concurrency — **E2E-03.** |
| 5 | Dark-default byte-identity (profile=insightface) | **Pass.** Default profile insightface; factory lazy-imports face_pipeline only on that branch; readiness uses `check_model_cache` for insightface; capability reason additive (`profile=` + counters); dim default 512 unchanged; image still installs insightface via `[bench]`. |
| 6 | Fail-closed completeness | **Pass.** sha256+license never OK without verify; atomic YuNet+SFace load unit; dim/missing/tamper → Unavailable*; `[face]`→`[bench]`; image keeps insightface (FIR-6 not done). |
| 7 | Test-suite integrity | **Pass (sampled).** Model-gated tests skip without models; characterization tests rewired to factory fakes without vacating assertions; observability tests assert event field **values** (`embedding_model`, profile, matched/new); counter naming = row recycling. Scoped suite 53 passed. |
| 8 | Mergeable-but-wrong / Not-Doing | **Pass.** No dimension-default flip; buffalo not removed from image; no live TODO in new bridge; no accidental FIR-6 scope. |

---

## Summary for orchestrator

Ship-quality dark wiring with three medium integration residuals (counter pre-commit honesty, readiness missing dim three-way, semaphore queue wait under worker concurrency) and one low client-asymmetry note. Recommend fix E2E-01/02 before trusting dark-profile ops dashboards; E2E-03 before load-testing face_pipeline with default worker concurrency. **Does not block dark-default merge** if residual risk is accepted.
