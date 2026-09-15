FINDINGS: [{"id":"GPUFLOW-1-SVCDEMAND-R-01","severity":"high","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py","line":464,"summary":"The synchronous load publisher writes a revisioned snapshot before committing the transaction that produced it.","evidence":"The delta makes load_snapshot() allocate a revision and mutate expiry/ready observations, but the existing sync caller invokes load_snapshot() and write_load_snapshot() inside _with_bypass_session(); that helper commits only after the callback returns at describe.py:453. The new dump_load_snapshot() has the required commit-before-write order, but this caller bypasses it."},{"id":"GPUFLOW-1-SVCDEMAND-R-02","severity":"high","file_path":"apps/prototype-description-service/scene/application/describe_load.py","line":267,"summary":"The synchronous publisher bypasses authoritative STOP and max-lease policy flags.","evidence":"load_snapshot() defaults stop_requested and max_lease_reached to false and passes those values to active_demand_count(); only dump_load_snapshot() resolves the current STOP intent and lease-cap state. The sync caller invokes load_snapshot() without either flag, so active leases remain in in_flight during STOP or max-lease."},{"id":"GPUFLOW-1-SVCDEMAND-R-03","severity":"medium","file_path":"apps/prototype-description-service/scene/application/describe_load.py","line":149,"summary":"The revision counter is created by application DDL instead of a managed schema artifact.","evidence":"Each first publication executes CREATE TABLE IF NOT EXISTS describe_load_snapshot_revisions and then updates it. The canonical migration table lists and describe-table declarations contain no revision table or sequence, so deployment permissions, schema healing, and downgrade coverage do not provision this required publisher state."},{"id":"GPUFLOW-1-SVCDEMAND-R-04","severity":"medium","file_path":"apps/prototype-description-service/scene/application/describe_load.py","line":180,"summary":"An explicit null published revision is treated as a valid revision zero instead of failing closed.","evidence":"_published_revision() converts payload revision=None to 0, and write_load_snapshot() can then replace that malformed file with any positive candidate. The contract allows revision zero only for a missing initial file and requires malformed revisions to fail closed; the added test covers invalid JSON and a string but not null."},{"id":"GPUFLOW-1-SVCDEMAND-R-05","severity":"medium","file_path":"apps/prototype-description-service/scene/tests/test_describe_load.py","line":723,"summary":"The revision tests do not prove the required database-read/publication interleaving or the sync publisher path.","evidence":"The new revision test calls write_load_snapshot() sequentially with fixed revisions, and the dump test calls dump_load_snapshot() sequentially. Neither pauses publisher A after its demand read, publishes newer demand from B, resumes A across separate writers, nor exercises _maybe_dump_describe_load(), where the two high findings occur."}]
Verdict: fail

# GPUFLOW-1 svc-demand review

| scope | value |
| --- | --- |
| base | `1743d1c7c` |
| tip | `88832950b` |
| files | `apps/prototype-description-service/scene/application/describe_load.py`; `apps/prototype-description-service/scene/tests/test_describe_load.py` |

This review is limited to the inlined `1743d1c7c..88832950b` delta. The two changed paths exactly match the supplied svc-demand owned implementation/test paths; no sibling-lane path is changed. The lease aggregation and revision work is directionally aligned with the lifecycle contract, but the pre-existing synchronous publisher now calls the mutating snapshot function through a different transaction/publication choreography.

## FINDINGS

### GPUFLOW-1-SVCDEMAND-R-01 — high

- **File:line:** `apps/prototype-description-service/scene/application/describe_load.py:282-290`; consumer `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:448-466`.
- **Evidence:** The delta makes `load_snapshot()` stateful: revision allocation, expired-lease transitions, and first-ready persistence occur before it returns. The sync callback calls `load_snapshot()` and then `write_load_snapshot()` at `describe.py:464-466`, while `_with_bypass_session()` commits only at `describe.py:453`. The new `dump_load_snapshot()` follows the required order (`describe_load.py:407-414`), but this caller does not use it. This violates the commit-before-publication requirement and the consistent-snapshot/fencing concerns in `[DATA-19]` and `[RES-10]`.
- **Impact:** If the bypass-session commit fails after the file replacement, the lifecycle reader can consume expired/first-ready state and a revision that never became durable. A later transaction can reuse that revision and be dropped as equal, silently leaving the stale demand file in place.
- **Fix:** Route this synchronous path through `dump_load_snapshot()` (or move publication after the helper commits), then add a rollback/commit-failure regression that asserts the file is unchanged and the next successful revision is publishable.

### GPUFLOW-1-SVCDEMAND-R-02 — high

- **File:line:** `apps/prototype-description-service/scene/application/describe_load.py:267-289`; consumer `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:464-466`.
- **Evidence:** `load_snapshot()` defaults `stop_requested=False` and `max_lease_reached=False` and passes those values directly to `active_demand_count()`. Only `dump_load_snapshot()` resolves `_demand_policy_flags()` from the current operator intent and lifecycle state. The sync publisher calls `load_snapshot()` with no policy flags, so active leases contribute to both `in_flight` and `lease_demand` while STOP or `last_transition_reason=lease_cap` is active, contrary to the contract's STOP/max-lease authority and fail-closed rule `[AGT-10]`.
- **Impact:** The reaper can see `has_work` for demand that the authoritative policy says must contribute zero, delaying or defeating operator STOP and allowing max-lease demand to keep the lifecycle fence busy.
- **Fix:** Use the one policy-aware publisher entry point for every sync publication, or make policy resolution mandatory inside `load_snapshot()`. Add a sync-caller test for active STOP and lease-cap state that verifies demand remains durable but contributes zero.

### GPUFLOW-1-SVCDEMAND-R-03 — medium

- **File:line:** `apps/prototype-description-service/scene/application/describe_load.py:141-169`; schema comparison `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py:75-87,1635-1704`.
- **Evidence:** The first snapshot executes application-side `CREATE TABLE IF NOT EXISTS describe_load_snapshot_revisions`, followed by an insert/update counter. The canonical migration's `RAW_SQL_TABLES`/`EXPECTED_SCHEMA_TABLES` and its describe-table declarations contain no revision table or sequence. This leaves the required publisher state outside migration permissions, schema healing, and downgrade coverage.
- **Impact:** A production application role without DDL privilege cannot publish the first load snapshot; default best-effort handling suppresses that error and leaves the lifecycle with missing/stale load evidence. Runtime catalog DDL also makes first-use publication dependent on an unmeasured deployment side effect.
- **Fix:** Provision a managed sequence or canonical revision table in the schema migration, register its permissions/expected-table metadata and downgrade/heal behavior, and remove runtime `CREATE TABLE` from the publisher.

### GPUFLOW-1-SVCDEMAND-R-04 — medium

- **File:line:** `apps/prototype-description-service/scene/application/describe_load.py:176-185,339-345`.
- **Evidence:** `_published_revision()` converts an explicit `revision: null` to zero. `write_load_snapshot()` can then replace that malformed file with any positive candidate. The lifecycle contract reserves revision zero for a missing initial file and requires malformed revisions to fail closed; the added regression at `test_describe_load.py:748-756` checks invalid JSON and a string but not null.
- **Impact:** A malformed published snapshot can bypass the writer fence and be overwritten, potentially discarding newer demand evidence instead of preserving the fail-closed busy state.
- **Fix:** Distinguish a missing `revision` key from an explicit null and reject null, booleans, non-integers, and invalid ranges; add null/list/bool regression cases.

### GPUFLOW-1-SVCDEMAND-R-05 — medium

- **File:line:** `apps/prototype-description-service/scene/tests/test_describe_load.py:723-781`.
- **Evidence:** The revision test invokes `write_load_snapshot()` sequentially with fixed dictionaries, and the dump test invokes `dump_load_snapshot()` sequentially. Neither pauses publisher A after its database demand read, lets publisher B publish newer demand, resumes A across separate writer processes, or exercises `_maybe_dump_describe_load()`, the production caller implicated by R-01/R-02. The lifecycle contract explicitly requires this interleaving and separate-process proof.
- **Impact:** The tests can pass while the database/file transaction ordering, sync policy handling, or cross-process stale-publication guarantee remains broken.
- **Fix:** Add a barrier-controlled two-publisher test with a real shared database/file fence, plus a sync-caller regression that injects commit failure and active STOP/max-lease state.

## Verification

- Changed-path ownership: mechanically verified from `.review/CHANGE.diff`; both paths are in the supplied owned list.
- Repository lock test: passed (`1 passed`).
- Import-origin check: `scene` resolves to this lane worktree at `apps/prototype-description-service/scene/__init__.py`.
- Lane test: blocked in this sandbox. Collection succeeds, but the declared `test_describe_load.py` invocation hangs while opening the `sqlite+aiosqlite` in-memory fixture before the first test body; it was bounded and interrupted. No implementation files were changed by verification.
