# GPUFLOW-1 timing-repository review

Verdict: pass_with_findings

| base | tip | files |
| --- | --- | --- |
| `c83b0594f` | `b690b1b40` | `apps/prototype-description-service/scene/application/describe_run_repository.py`; `apps/prototype-description-service/scene/domain/describe_run.py`; `apps/prototype-description-service/scene/application/describe_operation_repository.py`; `apps/prototype-description-service/scene/tests/test_gpuflow_operation_repository.py`; `apps/prototype-description-service/scene/tests/test_describe_run_repository.py` |

The supplied delta changes only the five paths in the timing-repository owned list; no sibling-lane path is included.

## FINDINGS

### GPUFLOW-1-TIMINGREPOSITORY-R-01 — medium

- **File:** `apps/prototype-description-service/scene/application/describe_run_repository.py:74-78,101-109`; `apps/prototype-description-service/scene/application/describe_operation_repository.py:150-165`
- **Evidence:** The new run pickup/readiness paths assign caller-supplied `now` directly to `started_at` and `first_ready_at`, and startup association assigns `started_at` directly. `utc_observation()` is used for arithmetic and operation renewal, but not before these persisted assignments. SQLite drops timezone metadata, while `utc_observation()` interprets a naive value as UTC; an aware non-UTC fake clock can therefore reload as a different instant after restart.
- **Impact:** Cross-process queue, readiness, startup, and server-elapsed timings can be offset by the original timezone or become negative on a later observation, violating the contract that stored observations are UTC and making retry/run timing unreliable.
- **Fix:** Normalize every persisted observation with `utc_observation()` before assignment, including run pickup/readiness and startup `started_at`; apply the same rule to terminal timestamp writes that now feed `elapsed_ms()`.

### GPUFLOW-1-TIMINGREPOSITORY-R-02 — medium

- **File:** `apps/prototype-description-service/scene/application/describe_operation_repository.py:46-60,257-265`
- **Evidence:** Renewal/complete paths lock the operation row first (`get(...with_for_update())`) and then the lease row (`_lease_for(...with_for_update=True)`). `purge_expired()` acquires/deletes qualifying lease rows first and only then acquires/deletes operation rows. On PostgreSQL, a retry racing retention purge can hold the operation while waiting for the lease while purge holds the lease while waiting for the operation.
- **Impact:** Concurrent retry and retention cleanup can deadlock and turn an expiry/replay into a transaction failure instead of the required typed result; repeated races can also leave cleanup and demand publication transiently unavailable.
- **Fix:** Use one lock order for both paths (operation then lease), or lock the expired operation set before deleting through the parent `ON DELETE CASCADE`; keep the session identity map synchronized after the ordered delete.

### GPUFLOW-1-TIMINGREPOSITORY-R-03 — medium

- **File:** `apps/prototype-description-service/scene/application/describe_run_repository.py:113-135,173-195,758-793`
- **Evidence:** `record_item_processing()` is the only new path that assigns `items_timed`, p50, and max. `create_run()` does not initialize `items_timed`, and `_recompute_run_totals()` updates status counters and `server_elapsed_ms` without recomputing the timing aggregate. A run whose items all fail, skip, or remain untimed therefore never enters `record_item_processing()` and retains `items_timed = NULL` despite the repository knowing its complete item set.
- **Impact:** The run contract cannot distinguish a known zero measured-item count from an unknown count; downstream summaries can report missing coverage for a completed failed/cancelled/untimed run instead of the required `items_timed: 0` with null p50/max.
- **Fix:** Initialize new runs with `items_timed = 0` and recompute the measured-item aggregate whenever item/run state is finalized, while retaining `NULL` only for genuinely legacy or unavailable counts.

### GPUFLOW-1-TIMINGREPOSITORY-R-04 — low

- **File:** `apps/prototype-description-service/scene/application/describe_operation_repository.py:66-68`
- **Evidence:** `accept()` checks only `len(request_digest) == 64`; a non-hex string such as `"!" * 64` is persisted as a purported SHA-256 digest, and a non-string can fail with an untyped `TypeError` at `len()`.
- **Impact:** The repository does not fail closed on malformed digest input, so operation binding can be based on a value that is not the canonical request digest and callers may receive an unexpected generic error.
- **Fix:** Require a string matching the canonical lowercase 64-hex SHA-256 form (prefer the shared digest-length/validation constant) before inserting or comparing the operation.

## Re-review r5 (b690b1b40..ce1053796)

VERIFIED: {"GPUFLOW-1-TIMINGREPOSITORY-R-01": "fixed", "GPUFLOW-1-TIMINGREPOSITORY-R-02": "fixed", "GPUFLOW-1-TIMINGREPOSITORY-R-03": "fixed", "GPUFLOW-1-TIMINGREPOSITORY-R-04": "fixed", "GPUFLOW-1-TIMINGREPOSITORY-SV-01": "fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-TIMINGREPOSITORY-R-01 | fixed | `.review/CHANGE.diff:129-146, 248-256` routes run pickup/readiness and startup `started_at` through `as_utc`; the helper rejects naive caller observations and converts aware non-UTC values to UTC before persistence. |
| GPUFLOW-1-TIMINGREPOSITORY-R-02 | fixed | `.review/CHANGE.diff:91-116` locks expired parent operations first, derives their identities, then deletes leases and operations with `synchronize_session="fetch"`, matching the renewal operation→lease order ([CON-13]). |
| GPUFLOW-1-TIMINGREPOSITORY-R-03 | fixed | `.review/CHANGE.diff:147-160, 226-241` initializes `items_timed=0` for both run constructors and recomputes it from persisted item processing values in reclaim and `_recompute_run_totals`. |
| GPUFLOW-1-TIMINGREPOSITORY-R-04 | fixed | `.review/CHANGE.diff:7-13, 33-40` adds a type guard and full-match lowercase hexadecimal SHA-256 validation before operation creation or lookup. |
| GPUFLOW-1-TIMINGREPOSITORY-SV-01 | fixed | `.review/CHANGE.diff:93-116` normalizes the caller clock with `as_utc`, selects parent identities, and uses `synchronize_session="fetch"` for both bulk deletes, avoiding Python evaluation of SQLite-naive identity-map timestamps; the pre-existing three-row purge assertion remains unchanged. |

### FINDINGS

#### GPUFLOW-1-TIMINGREPOSITORY-R-05 — medium

- **File:** `apps/prototype-description-service/scene/application/describe_operation_repository.py:264-279`
- **Evidence:** The fix replaces set-based retention deletes with an unbounded `SELECT ... .all()` of every expired operation (`.review/CHANGE.diff:98-103`), then interpolates the complete identity list into two composite `IN` predicates (`.review/CHANGE.diff:105-115`). A sufficiently large backlog can exhaust worker memory or hit PostgreSQL/SQLite bind or statement-size limits, aborting purge and leaving retained rows behind ([RES-05]).
- **Impact:** Retention cleanup no longer scales with the database's set-based delete and can fail precisely when backlog pressure is highest.
- **Fix:** Process bounded parent-key batches (with a deterministic keyset/limit), delete each batch in parent-lock then lease/operation order, and continue until no candidates remain.

#### GPUFLOW-1-TIMINGREPOSITORY-R-06 — medium

- **File:** `apps/prototype-description-service/scene/application/describe_operation_repository.py:266-274`
- **Evidence:** `with_for_update(skip_locked=True)` skips an expired operation held by a concurrent transaction (`.review/CHANGE.diff:98-103`), and the method performs only one candidate pass before returning `result.rowcount` (`.review/CHANGE.diff:103-116`). There is no retry/continuation or signal that skipped expired rows remain.
- **Impact:** A one-shot startup/manual purge can report success while leaving an expired operation and its lease beyond the retention window; the lock-order fix does not require `SKIP LOCKED`, so this silently weakens cleanup completeness.
- **Fix:** Use the ordered parent lock without skipping, or loop/retry skipped identities with a bounded backoff and expose incomplete cleanup to the caller.

#### GPUFLOW-1-TIMINGREPOSITORY-R-07 — low

- **File:** `apps/prototype-description-service/scene/tests/test_describe_run_repository.py:307-308`; `apps/prototype-description-service/scene/tests/test_gpuflow_operation_repository.py:182-183`
- **Evidence:** `ruff check` reports `I001` for both new local import blocks added at `.review/CHANGE.diff:271-273` and `.review/CHANGE.diff:314-316`; `ruff format --check` also reports unformatted production/test hunks at `.review/CHANGE.diff:91-116, 292-300, 331-375`.
- **Impact:** The fix delta fails the repository's configured lint/format gates ([AGT-06]).
- **Fix:** Run the configured Ruff import organizer and formatter on the changed files, then rerun both checks.

#### GPUFLOW-1-TIMINGREPOSITORY-R-08 — low

- **File:** `apps/prototype-description-service/scene/tests/test_gpuflow_operation_repository.py:314-375`
- **Evidence:** The new lock-order test uses `sqlite+aiosqlite` and only checks that emitted statements start with `SELECT` and that DELETE text lists lease before operation (`.review/CHANGE.diff:319-375`). SQLite does not exercise PostgreSQL `FOR UPDATE SKIP LOCKED` row-lock semantics, so removing the actual lock or changing concurrent behavior would leave this test green ([TEST-15]).
- **Impact:** The test provides shape coverage but not evidence that the reported PostgreSQL deadlock scenario is prevented under concurrent transactions.
- **Fix:** Keep the SQLite ordering assertion, and add a PostgreSQL integration/concurrency test that holds each lock in turn and verifies the retry/purge outcome and no deadlock.

Verdict: pass_with_findings
