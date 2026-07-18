# FIR-4 S4 adversarial code review (grok / fir-4-grok)

**Subject:** `31c891d1` (S4 observability) + `750b8f5b` (test-stub fix) on `feature/fir-4`  
**Contract:** plan S4 row + Checklist for S4 in `docs/tasks/fir/FIR-4-runtime-integration-task-plan.md`  
**Role:** adversarial CODE reviewer (independent; attack)  
**HEAD at review:** `750b8f5b36cb0b111b77e4d58605381aec03fab3`  
**Pre-S4 baseline for characterization:** `cf2d7f48` (`service.py` return contract)

## VERDICT: pass_with_findings

S4 delivers `ReconcileResult(detected/matched/new)` from `_persist_identities` through `process_media_item`, preserves pre-S4 `identities_detected = matched + new` at every production caller, emits one `scan_media_reconciled` INFO event from `ScanService` only (no handler double-log), threads worker `job_id` + contextvar `correlation_id`, adds embedding-length `ValueError` with actual/expected dims, and publishes always-present zero-including counters on the capability heartbeat. Residual findings: `duration_ms` means detect+persist on the worker path and persist-only on HTTP/inline; HTTP/inline zero-detection media never emit; structured `matched` can over-count IoU pairs that skip write; failed process paths emit nothing (success-only).

### Test evidence (this session)

```text
cd apps/prototype-description-service && uv run pytest \
  recognition/tests/unit/test_scan_service_observability.py \
  recognition/tests/unit/test_scan_worker_correlation.py \
  recognition/tests/unit/test_scan_worker_isolation.py -q
→ 17 passed in 0.81s, exit 0
```

---

## Findings

### S4R-01 — medium

**File:line:** `apps/prototype-description-service/recognition/application/scan/service.py:287-308` (`process_media_item`) vs `199-214` (`save_job_results`)  
**Heuristic:** OBS-01  
**Failure scenario:** Same field `duration_ms` is measured from different start points. Worker path (`process_media_item`) starts the timer **before** blob open + `detect` + persist, so the value is end-to-end item latency. HTTP/inline path (`save_job_results`, used by `process_scan_job` / `process_scan_job_inline`) starts the timer only around `_persist_identities`, so `duration_ms` is **persist-only** (detect already finished in the three-phase `detect` step). Operators dashboards that compare or alert on `duration_ms` across worker vs inline/API jobs will mis-attribute latency (e.g. treat slow detect as "DB reconcile is fine" or the reverse). Label is not path-honest.

**Fix:** Split fields (`detect_ms` + `persist_ms`, or `phase=detect+persist|persist`) or document and set `duration_ms` to the same phase on both paths (prefer always labeling scope in the event, e.g. `duration_scope`).

---

### S4R-02 — medium

**File:line:** `apps/prototype-description-service/recognition/application/scan/service.py:181-215`  
**Heuristic:** OBS-02, OBS-08  
**Failure scenario:** `save_job_results` iterates `detections_by_media` only — media IDs present in `media_ids` but with **zero** detections never enter the loop, so **no** `scan_media_reconciled` event is emitted. Worker `process_media_item` always detect→persist→emit (including `detected=0`). Plan contract is one wide event per processed media across worker + HTTP + inline. Empty-face images on HTTP/inline are silent; ops cannot distinguish "job never reached persist for that media" from "reconciled with zero faces" from event volume alone.

**Fix:** Loop all `media_ids_list` (or union with `detections_by_media` keys) and emit with `detected=0, matched=0, new=0` (and still run orphan cleanup via `_persist_identities` with empty dets if that is desired re-scan semantics).

---

### S4R-03 — low

**File:line:** `apps/prototype-description-service/recognition/application/scan/service.py:367-369,427-430`  
**Heuristic:** OBS-01  
**Failure scenario:** `matched=len(matched)` counts every IoU match pair, but the update loop `continue`s when `det.embedding is None` (no row write). `new=len(new_rows)` correctly counts only inserted rows. Structured event + heartbeat `rows_matched` can therefore report a "match" that did not update the DB, while `total`/`identities_detected` still match pre-S4 `len(matched)+len(new_rows)` (characterization preserved, label honesty weaker for the new named field). Rare if the generator always fills embeddings; still a lying counter under partial-embed failure.

**Fix:** Count matched writes (pairs that pass the embedding/`model_id` guards), or emit `matched_written` vs `matched_iou` separately; keep `total` byte-compatible with pre-S4 if still required.

---

### S4R-04 — low

**File:line:** `apps/prototype-description-service/recognition/application/scan/service.py:294-309`; `recognition/worker/handlers/scan.py:88-130`  
**Heuristic:** OBS-02, OBS-08  
**Failure scenario:** Event emits only after successful `_persist_identities` (and only on the success path of the handler). Detect/persist/`ValueError` (dim guard, missing `embedding_model`) → **zero** `scan_media_reconciled` for that media; counters (`ScanWorkerCounters.record`) also skip on exception. Intentional success-only telemetry, but not asserted; a sustained fail class looks like event silence rather than explicit failure records. Capability counters stay present-at-zero (good for process liveness) but do not surface fail volume.

**Fix:** Optional sibling event `scan_media_reconcile_failed` (error class, no PII) or emit success event only after commit with a documented contract that absence means failure/retry; add a unit assertion for "no event on raise".

---

## Attack surface results (checklist)

### 1. Return-contract integrity [TEST-03]

Diffed vs `cf2d7f48` `service.py`:

| Surface | Pre-S4 | Post-S4 | External semantics |
| --- | --- | --- | --- |
| `_persist_identities` return | `len(matched) + len(new_rows)` int | `ReconcileResult(detected, matched, new)`; `.total == matched+new` | **Identical** int meaning |
| `process_media_item` | returns that int | returns `ReconcileResult`; `__int__` / `.total` | Same when coerced |
| `ScanItemHandler` `identities_detected` | raw return into `mark_item_completed` | `_identities_detected_count` → `.total` | **Identical** DB field |
| `save_job_results` `scan_job.identities_detected` | sum of int returns | sum of `result.total` | **Identical** |
| API progress / queue sums | sum item `identities_detected` ints | unchanged storage type | **Identical** |

No production caller sums a different number. Not high.

### 2. Event emission correctness [OBS-02]

- Emit site is **only** `ScanService` (`process_media_item` + `save_job_results`). Handler does not log a second reconcile event.
- Worker / HTTP / inline share `_emit_scan_media_reconciled` shape.
- Double-emission via both paths: no — worker uses `process_media_item` only; inline uses `save_job_results` only.
- **S4R-02** zero-detection gap on `save_job_results`.
- **S4R-04** exception → no event.
- **S4R-01** duration scope split.

### 3. Correlation [OBS-03]

- Event uses `get_correlation_id()` contextvar — does **not** invent a new id.
- Worker binds `item.correlation_id or generate_correlation_id()` before `process_media_item` (`handlers/scan.py:67-72`); tests still capture binding (750b8f5b).
- HTTP middleware sets the same contextvar for request-scoped inline/API work.
- `job_id` **kept** (not removed) in 750b8f5b rationale: ScanService has no other job scope; worker passes `item.job_id`; `save_job_results` always has `job_id`; bare `process_media_item` callers (tests only in prod graph) get `job_id=None` — acceptable, not silent rot on the worker path.

### 4. capability.py counters [OBS-05][OBS-08][RES-07]

- `ScanWorkerCounters`: four ints + `record` / `format_suffix`; no per-tenant dict → **no RES-07 leak**.
- Heartbeat reason always includes zeros via `format_capability_reason` even when counters empty.
- Concurrency: worker is asyncio; `record()` is sync and does not await, so increments run to completion without task switch mid-`+=` — safe under the async worker model. No thread lock; not used from OS threads.
- Counters only update on success (**S4R-04**).

### 5. Test-stub fix `750b8f5b`

- Root cause: S4 added optional `job_id=` to `process_media_item`; fakes still declared only `tenant_id/media_id/media_url` → `TypeError` on call.
- Fix: explicit `job_id=None` on correlation (2) + isolation (1) fakes — **not** a `**kwargs` blanket (good: future required kwargs still fail loud).
- Assertions preserved: contextvar capture before process; poison-tenant raise + non-poison return `1` unchanged.

### 6. Embedding-length guard [EMB-01]

- Present at both write sites in `_persist_identities` via `_assert_embedding_dimension`.
- Error names dims: `embedding length {actual} != pgvector_dimension {expected_dim}`.
- Test: `test_embedding_length_guard_names_dims` (regex on both numbers).

### 7. `test_embedding_model_provenance.py` / `test_runtime_factory.py`

- Provenance: `assert count == 1` → `assert int(count) == 1` — adapts to `ReconcileResult.__int__`; still asserts one identity written. **Not weakened.**
- Runtime factory heartbeat: exact `reason == "profile=face_pipeline"` → `startswith` + zero-counter substrings. **Strengthened** for OBS-08.

### 8. Log hygiene [OBS-04]

- Level: `logger.info` — not ERROR business noise.
- Payload: ids, counts, model, profile, duration — no image bytes, no media_url, no embeddings.
- `embedding_model` key always present; value `str | None` (null when no `model_id` on any det) — consistent null-vs-absent (always present key).

---

## No-finding attack list

Attacks attempted that **did not** yield a finding:

1. **Caller-side identities_detected inflation/deflation** — handler and `save_job_results` both use `.total` / pre-S4 `matched+new` formula.
2. **Double emit (handler + service)** — only service emits `scan_media_reconciled`.
3. **Event invents correlation_id** — reads contextvar only; may be `None` if unbound, never a fresh random in the emit helper.
4. **job_id kwarg removed in 750b8f5b** — kept; worker threads `item.job_id`.
5. **`**kwargs` stub masking** — explicit `job_id=None` only.
6. **Per-tenant counter map / unbounded growth** — four scalar ints only.
7. **Counters missing when zero** — format always includes `media_processed=0` etc.
8. **Embedding guard without dim names** — both actual and expected in message; unit-tested.
9. **Assertion deletion in provenance/runtime tests** — adapted/strengthened, not deleted.
10. **PII / embedding vectors in the wide event** — not present.
11. **ERROR-level reconcile success noise** — INFO only.
12. **Async counter corruption under gather** — sync `record()` without await is task-atomic on the asyncio event loop.
13. **process_media_item return type breaking mark_item_completed** — explicit int coercion before repo write.
14. **quality-gate rejection metric invented** — correctly deferred (no scan-time gate).
