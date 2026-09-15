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

## Re-review r2b (88832950b..cd3d66908)

VERIFIED: {"GPUFLOW-1-SVCDEMAND-R-01":"fixed","GPUFLOW-1-SVCDEMAND-R-02":"fixed","GPUFLOW-1-SVCDEMAND-R-03":"fixed","GPUFLOW-1-SVCDEMAND-R-04":"fixed","GPUFLOW-1-SVCDEMAND-R-05":"partially_fixed"}
FINDINGS: [{"id":"GPUFLOW-1-SVCDEMAND-R-06","severity":"high","file_path":"apps/prototype-description-service/scene/application/describe_load.py","line":281,"summary":"Explicit false policy arguments still bypass authoritative STOP and max-lease blocks.","evidence":"The fix resolves policy only when stop_requested or max_lease_reached is None; an explicit False is forwarded to active_demand_count(), so a caller can publish eligible demand while STOP or lease_cap is live. The A1 contract requires those policies to remain authoritative. [RES-10]"},{"id":"GPUFLOW-1-SVCDEMAND-R-07","severity":"medium","file_path":"apps/prototype-description-service/scene/application/describe_load.py","line":176,"summary":"An explicit published revision of zero is still accepted as a current revision.","evidence":"The new validator rejects negative values but accepts revision == 0, although the contract reserves zero for a missing initial file and starts allocated revisions at one; a positive candidate can overwrite {revision:0}. The malformed regression loop omits zero. [TEST-15]"},{"id":"GPUFLOW-1-SVCDEMAND-R-08","severity":"medium","file_path":"apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py","line":90,"summary":"The schema fix is not protected by a local upgrade/heal/downgrade regression assertion.","evidence":"The changed migration test only adds the table name to EXPECTED_SCHEMA_TABLES, while the scene fixture creates the revision table directly with SQL. Removing the new ensure_tables call could therefore pass the changed non-Postgres assertions; the managed schema path is left to optional PG tests. [TEST-15]"}]
Verdict: fail

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCDEMAND-R-01 | fixed | `.review/CHANGE.diff:102-144` makes `load_snapshot()` commit before returning; the existing sync caller writes only after awaiting it (`describe.py:464-466`), and `.review/CHANGE.diff:294-325` adds a commit-failure/file-preservation regression. |
| GPUFLOW-1-SVCDEMAND-R-02 | fixed | `.review/CHANGE.diff:91-127` changes the defaults to `None` and resolves `_demand_policy_flags()` inside `load_snapshot()`, so the unchanged sync caller no longer defaults both policy bits to false; `.review/CHANGE.diff:222-291` covers STOP and lease-cap default-policy snapshots. The explicit-false escape hatch is a separate new R-06. |
| GPUFLOW-1-SVCDEMAND-R-03 | fixed | `.review/CHANGE.diff:4-37` registers `describe_load_snapshot_revisions` in migration truth and downgrade order, `.review/CHANGE.diff:27-37` declares it in `ensure_tables()`, and `.review/CHANGE.diff:55-73` removes runtime `CREATE TABLE`. |
| GPUFLOW-1-SVCDEMAND-R-04 | fixed | `.review/CHANGE.diff:77-90` distinguishes a missing key from an explicit value and rejects null/bool/non-integer/negative revisions; `.review/CHANGE.diff:193-215` adds null, bool, list, object, and negative cases plus the missing-key case. Explicit zero remains a new R-07 gap. |
| GPUFLOW-1-SVCDEMAND-R-05 | partially_fixed | `.review/CHANGE.diff:327-361` now barriers publisher A after its read, lets B publish a higher revision, and verifies A is dropped; `.review/CHANGE.diff:222-325` adds sync-shaped STOP/lease-cap and commit-failure checks. It does not change the test to invoke `_maybe_dump_describe_load()`, does not alter demand between A and B, and does not repeat the fence across separate processes as required by the contract. [CON-05] [TEST-15] |

### FINDINGS

#### GPUFLOW-1-SVCDEMAND-R-06 — high

- **File:line:** `apps/prototype-description-service/scene/application/describe_load.py:260-282`; `.review/CHANGE.diff:91-127`.
- **Evidence:** The fix computes `policy_stop, policy_max_lease`, but then chooses `policy_stop if stop_requested is None else stop_requested` and the analogous max-lease expression. `dump_load_snapshot()` forwards its explicit arguments at `describe_load.py:407-411`. A caller passing `False` can therefore count and publish active leases while an unexpired STOP intent or lifecycle lease cap is active. The contract says STOP/max-lease remain authoritative and blocked leases contribute zero (`gpu-lifecycle.md:333-336,364,374-378`). This is a stale-authority write path covered by `[RES-10]`.
- **Impact:** An explicit false override can reintroduce `has_work` after the operator has requested STOP or the controller has reached its max lease, allowing the lifecycle controller to act on demand that must be excluded.
- **Fix:** Make policy blocks monotonic (`policy_stop or bool(stop_requested)` and `policy_max_lease or bool(max_lease_reached)`) or remove the override from the publisher API; keep only a test seam that cannot disable live policy.

#### GPUFLOW-1-SVCDEMAND-R-07 — medium

- **File:line:** `apps/prototype-description-service/scene/application/describe_load.py:169-178`; `.review/CHANGE.diff:77-90,193-205`.
- **Evidence:** `_published_revision()` now rejects explicit `None`, booleans, non-integers, and negatives, but the condition is `revision < 0`, so an explicit JSON `{"revision": 0}` is accepted as the published revision. The lifecycle contract says a missing initial file has revision zero and allocated revisions start at one (`gpu-lifecycle.md:390-400`). The added malformed loop covers strings, null, booleans, list/object, and `-1`, but not `0`, so a malformed zero file can still be overwritten instead of failing closed. `[TEST-15]` applies.
- **Impact:** A corrupt or legacy-reset file carrying an explicit zero can pass the write fence and be replaced by a positive candidate, weakening the fail-closed publication boundary.
- **Fix:** Treat explicit zero as malformed (or distinguish a validated legacy format explicitly) and add a zero regression that asserts the target remains untouched.

#### GPUFLOW-1-SVCDEMAND-R-08 — medium

- **File:line:** `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py:90-128`; `apps/prototype-description-service/scene/tests/test_describe_load.py:70-93`; `.review/CHANGE.diff:41-51,179-190`.
- **Evidence:** The changed migration test only updates the expected-table list. The changed scene fixture independently executes `CREATE TABLE describe_load_snapshot_revisions`, so the lane tests do not prove that `upgrade()`/`heal()` actually create the table or that `downgrade()` removes it. A regression removing the new `ensure_tables()` call can pass these local assertions; only optional Postgres tests exercise the managed DDL path. This is a missing-green-to-red guard under `[TEST-15]`.
- **Impact:** A schema declaration can drift from the application fixture while SQLite/local verification remains green, leaving first publication to fail on a deployment that skipped or partially applied the migration.
- **Fix:** Add a migration recorder assertion for the revision table's columns/check constraint and downgrade position, plus a non-Postgres test that runs the migration helper against a scratch schema or explicitly include this table in an always-on migration regression.

Verdict: fail

## Re-review r3b (cd3d66908..973fc1028)

VERIFIED: {"SVCDEM-H-01":"fixed","SVCDEM-M-02":"partially_fixed","SVCDEM-M-03":"partially_fixed","SVCDEM-M-05":"not_fixed","GPUFLOW-1-SVCDEMAND-R-05":"partially_fixed","GPUFLOW-1-SVCDEMAND-R-06":"fixed","GPUFLOW-1-SVCDEMAND-R-07":"fixed","GPUFLOW-1-SVCDEMAND-R-08":"fixed"}
FINDINGS: [{"id":"GPUFLOW-1-SVCDEMAND-R-09","severity":"high","file_path":"apps/prototype-description-service/scene/application/describe_load.py","line":319,"summary":"Policy flags and GPU state are read from separate lifecycle snapshot generations.","evidence":"The fix reads last_transition_reason through _max_lease_reached() and then calls read_gpu_state() independently in _gpu_excludes_lease_demand(); a lifecycle write between those reads can leave a lease-cap transition unobserved while the second read returns an allowlisted stopped state, so has_work is republished after max-lease. This violates authoritative policy and the single-generation fencing requirement. [CON-11] [RES-10]"},{"id":"GPUFLOW-1-SVCDEMAND-R-10","severity":"low","file_path":"apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py","line":144,"summary":"The fix delta changes a recognition migration test outside the svc-demand lane paths.","evidence":"The inlined delta adds the migration recorder tests in .review/CHANGE.diff:1-44, while the lane row assigns svc-demand scene/application/describe_load.py and its scene test proof. The migration change may be needed for R-08, but it is an out-of-lane path that requires explicit owner coordination."}]
Verdict: fail

| finding | verdict | evidence |
| --- | --- | --- |
| SVCDEM-H-01 | fixed | `.review/CHANGE.diff:187-229` changes malformed/unreadable max-lease state to fail closed and adds a live `read_gpu_state()` gate; `.review/CHANGE.diff:766-871` covers missing, stale, unreadable, lease-cap-then-unknown, and stopped/Auto snapshots. The separate-generation race is a new R-09. |
| SVCDEM-M-02 | partially_fixed | `.review/CHANGE.diff:96-161` adds finite/inequality checks and `.review/CHANGE.diff:279-286` gates the initial snapshot. It does not wire the bound into `DescribeOperationRepository` construction (`scene/application/describe_operation_repository.py:35-44` still accepts caller-supplied lease seconds), uses a hardcoded retention constant while the repository reads an environment value, falls back from invalid refresh configuration (`scene/application/describe_load.py:196-214`), and the periodic loop (`:545-560`) does not validate. Those gaps violate the contract's explicit-deployed-bound/fail-closed requirement. |
| SVCDEM-M-03 | partially_fixed | `.review/CHANGE.diff:270-275` changes `dump_load_snapshot()` to WARNING and `.review/CHANGE.diff:421-444` asserts that log level. The production synchronous `_maybe_dump_describe_load()` still catches broad exceptions and logs DEBUG at `scene/interface_adapters/http/routers/describe.py:457-470`; the added sync test (`.review/CHANGE.diff:627-681`) covers stale-drop only, so the original failed sync publication remains weakly observable. [AGT-10] |
| SVCDEM-M-05 | not_fixed | `.review/CHANGE.diff:463-493` replaces the old global STOP assertion with all-two-counted/global-zero assertions, but `DescribeOperationRepository.active_demand_count()` still returns zero for any global block (`scene/application/describe_operation_repository.py:232-258`). No behavior or regression holds one of two leases while the other remains counted; the added test is therefore insufficient by itself. [TEST-15] |
| GPUFLOW-1-SVCDEMAND-R-05 | partially_fixed | `.review/CHANGE.diff:627-681` now pauses publisher A after its read, changes demand through B, exercises `_maybe_dump_describe_load()`, and verifies A's older revision is dropped. It remains a same-process SQLite test with no equal-revision or separate-process repeat required by `gpu-lifecycle.md:410-413`. [CON-05] [TEST-15] |
| GPUFLOW-1-SVCDEMAND-R-06 | fixed | `.review/CHANGE.diff:219-229` ORs explicit overrides with live STOP/max-lease policy, and `.review/CHANGE.diff:684-736` verifies both `False` override cases retain the active lease while publishing zero demand. |
| GPUFLOW-1-SVCDEMAND-R-07 | fixed | `.review/CHANGE.diff:170-184` rejects explicit revision zero by changing the lower bound to one; `.review/CHANGE.diff:549-557` adds zero to the malformed revision loop and `.review/CHANGE.diff:856-866` asserts the malformed target remains untouched. |
| GPUFLOW-1-SVCDEMAND-R-08 | fixed | `.review/CHANGE.diff:8-39` adds recorder assertions for the migration-created columns, primary key, named singleton check, and downgrade order; the test calls `identity_schema.upgrade()`/`downgrade()` rather than only listing the table. |

### FINDINGS

#### GPUFLOW-1-SVCDEMAND-R-09 — high

- **File:line:** `apps/prototype-description-service/scene/application/describe_load.py:276-322`; `.review/CHANGE.diff:187-229`.
- **Evidence:** `_max_lease_reached()` reads and parses the lifecycle file to extract `last_transition_reason`, then `_gpu_excludes_lease_demand()` performs a separate `read_gpu_state()` call. The producer publishes the policy fields in one atomic snapshot, but this consumer does not carry a generation or lock across both reads. If the lifecycle writes a fresh `lease_cap` snapshot after the first read and before the second, the second read can still be the allowlisted `stopped` state; `active_demand_count()` then counts active leases and publishes `has_work` after the max-lease transition. This is a check-then-act authority violation under `[CON-11]` and stale distributed state under `[RES-10]`.
- **Impact:** A controller max-lease stop can be followed by one demand publication that immediately re-arms automatic START, defeating the cost backstop and the contract's “STOP and lifecycle max-lease remain authoritative” rule.
- **Fix:** Read one validated lifecycle snapshot generation and derive state plus transition reason from it, coordinating with the existing lifecycle publication fence or exposing one atomic reader API; add a barrier regression that interleaves a lease-cap write between the policy fields.

#### GPUFLOW-1-SVCDEMAND-R-10 — low

- **File:line:** `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py:144-175`; `.review/CHANGE.diff:1-44`.
- **Evidence:** The fix delta changes a recognition migration test path in addition to the svc-demand implementation and scene test paths named by the lane plan. This is needed to prove the R-08 schema repair, but it is outside this lane's owned path set and should be coordinated with the recognition/migration owner rather than silently carried by the svc-demand lane.
- **Impact:** The lane can merge a sibling-owned path or conflict with the migration lane's concurrent changes, making ownership and review provenance ambiguous.
- **Fix:** Land the migration assertion in its owning lane or record an explicit cross-lane ownership handoff before merging this delta.

Verdict: fail
