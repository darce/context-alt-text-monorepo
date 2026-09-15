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
