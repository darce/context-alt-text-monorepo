FINDINGS: [{"id":"GPUFLOW-1-TIMINGMODELS-R-01","severity":"high","file_path":"apps/prototype-description-service/db/migrations/versions/001_identity_schema.py","line":1677,"summary":"New timing checks are not healable on pre-existing run tables.","evidence":"The delta adds named checks to image_description_runs and image_description_run_items, but _ensure_table's existing-table branch sends every missing table constraint to _ensure_table_constraints; the call opts only the unrelated idempotency UNIQUE into heal_constraints. A deployed database therefore raises before the new nullable columns can be applied."},{"id":"GPUFLOW-1-TIMINGMODELS-R-02","severity":"medium","file_path":"apps/prototype-description-service/db/migrations/versions/001_identity_schema.py","line":1654,"summary":"Lease retention is independent of operation retention.","evidence":"describe_operations.retain_until and describe_demand_leases.retain_until are separate columns; the only lease check is expires_at <= retain_until, with no equality or upper bound against the parent operation retention deadline."},{"id":"GPUFLOW-1-TIMINGMODELS-R-03","severity":"medium","file_path":"apps/prototype-description-service/db/migrations/versions/001_identity_schema.py","line":1628,"summary":"Timing checks admit non-JSON positive infinity and semantically contradictory timing values.","evidence":"Each Float timing check is only >= 0, so positive infinity satisfies it; the local SQLite probe inserted inf successfully. The same tables also permit startup_ms/ramp_up_ms with no startup association, despite the shared contract requiring null/zero warm and unobserved-start values."},{"id":"GPUFLOW-1-TIMINGMODELS-R-04","severity":"low","file_path":"apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py","line":91,"summary":"The existing exact expected-table regression test was not updated for the three new tables.","evidence":"The test still asserts the pre-delta EXPECTED_SCHEMA_TABLES list, while the migration now prepends describe_startups, describe_operations, and describe_demand_leases; the full migration test file fails at this assertion."},{"id":"GPUFLOW-1-TIMINGMODELS-R-05","severity":"low","file_path":"docs/runbooks/prod-identity-rls-remediation.md","line":36,"summary":"The production RLS audit omits the two new tenant tables.","evidence":"The runbook's hard-coded unnest ARRAY predates describe_operations and describe_demand_leases, while TENANT_TABLES now includes them; the schema-truth test reports both as missing, so the prescribed audit cannot inspect their RLS state."}]
Verdict: fail

# GPUFLOW-1 timing-models review

| scope | value |
| --- | --- |
| base | `112f262cd` |
| tip | `c83b0594f` |
| files | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`, `apps/prototype-description-service/db/models/scene.py`, `apps/prototype-description-service/scene/tests/test_gpuflow_timing_models.py` |

Review is limited to the supplied `112f262cd..c83b0594f` delta. The changed paths are within the lane-owned list. The lane-local storage test passes, but the migration cannot safely heal an existing deployment and the broader schema checks expose stale integration artifacts.

## FINDINGS

### GPUFLOW-1-TIMINGMODELS-R-01 — high

- **File:** `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py:1677`
- **Evidence:** The delta adds named timing `CheckConstraint`s to the already-existing `image_description_runs` and `image_description_run_items` tables. `_ensure_table` routes an existing table through `_ensure_table_constraints`, which refuses missing checks; the call site's `heal_constraints` opt-in covers only the pre-existing idempotency `UNIQUE`, not these new checks. The boot healer calls this same path, so an older production schema reaches `RuntimeError` after attempting the nullable column expansion.
- **Impact:** `sync_identity_schema` cannot converge a deployed database to B1. The new timing columns remain unapplied (the transaction rolls back), causing a boot/schema-heal failure instead of a usable release.
- **Fix:** Add an explicit, idempotent additive path for these timing checks to the canonical healer (with existing-data validation), and exercise healing from a pre-B1 run/item schema. Keep strict refusal for unapproved non-additive drift.

### GPUFLOW-1-TIMINGMODELS-R-02 — medium

- **File:** `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py:1654`
- **Evidence:** The operation and lease each store `retain_until`, but the lease only checks `expires_at <= retain_until`; there is no relationship enforcing the lease retention deadline to be the operation's retention deadline. The model comment says the repository snapshots and renews both atomically, but the database accepts a lease retained beyond its parent operation.
- **Impact:** A stale or incorrectly written lease can continue to renew and count as GPU demand after the async-operation retention window, so `svc-demand` can keep a startup alive beyond the bounded retention contract.
- **Fix:** Derive the lease deadline from the operation at read/write time and enforce the upper bound (for example, a parent-keyed constraint/schema design), with a test that rejects a lease retention deadline beyond its operation.

### GPUFLOW-1-TIMINGMODELS-R-03 — medium

- **File:** `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py:1628`
- **Evidence:** Timing columns use only `CHECK (... >= 0)`. Positive infinity satisfies that predicate (the local SQLite persistence probe inserted `inf`), yet it cannot be represented by the JSON schemas' `number` values. The independent nullable timing/ID columns also allow `startup_ms` or nonzero `ramp_up_ms` while `startup_id` is null, a combination that contradicts the warm/cache and unobserved-start contract.
- **Impact:** A corrupted or bad producer value can be stored and later make a strict builder emit invalid JSON or publish fabricated startup timing; downstream response and UI consumers cannot distinguish it from a persisted measurement.
- **Fix:** Validate finite durations at the write boundary and add dialect-safe storage checks. Add consistency checks for startup timing/association and tests for warm/cache, unknown-start, and non-finite values.

### GPUFLOW-1-TIMINGMODELS-R-04 — low

- **File:** `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py:91`
- **Evidence:** The exact-list assertion still contains the pre-delta `EXPECTED_SCHEMA_TABLES`; it does not include `describe_startups`, `describe_operations`, or `describe_demand_leases`. Running the full migration test file fails this assertion.
- **Impact:** The repository's existing schema migration test suite is red after the timing-models delta, blocking CI until its expected contract is updated.
- **Fix:** Update the exact expected list in the owning migration-test lane, preserving the migration's canonical order.

### GPUFLOW-1-TIMINGMODELS-R-05 — low

- **File:** `docs/runbooks/prod-identity-rls-remediation.md:36`
- **Evidence:** The production RLS pre-audit SQL hard-codes the old tenant-table array and omits `describe_operations` and `describe_demand_leases`, even though the delta adds both to `TENANT_TABLES`. The schema-truth consistency test fails on this mismatch.
- **Impact:** The prescribed production audit reports no row for the new tenant tables and can miss an RLS/policy gap during remediation.
- **Fix:** Add both tables to the runbook's audit array (or generate the list from the migration source) and rerun the schema-truth check.

## Re-review r5 (c83b0594f..853aafcdc)

| finding | verdict | evidence |
| --- | --- | --- |
| TIMING-H-01 | fixed | `001_identity_schema.py:320-335` adds an idempotent PostgreSQL CHECK-healing path with live-row validation; the existing run and item declarations opt the timing checks into it at `:1793-1805` and `:1880`. |
| TIMING-M-03 | partially_fixed | The delta rejects non-finite/nonnegative violations with `_TimingFloat` (`db/models/scene.py:45-54`) and finite CHECKs (`001_identity_schema.py:1656-1674`), and disallows timing without a non-null startup id at `:1652-1655`/`:1721-1724`; however `DescribeStartup.started_at` remains nullable (`db/models/scene.py:106-117`), so a non-null startup id can still point to an unobserved start while `startup_ms` is persisted. |
| TIMING-L-05 | fixed | `test_identity_schema_declares_expected_table_set` now includes `describe_startups`, `describe_operations`, and `describe_demand_leases` in the exact expected order (`test_identity_schema_migration.py:90-92`). |
| TIMING-L-06 | fixed | The production audit array now includes `describe_operations` and `describe_demand_leases` (`docs/runbooks/prod-identity-rls-remediation.md:36-38`). |

### FINDINGS

#### GPUFLOW-1-TIMINGMODELS-R-06 — medium

- **File:** `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py:320-324, 1793-1805, 1880`
- **Evidence:** `_ensure_check_constraint` returns `False` for every non-PostgreSQL dialect, and `_ensure_table_constraints` then appends the opted-in CHECK to `unhealed` and raises. Both existing-table timing declarations opt their new checks into `heal_constraints`, so a pre-timing SQLite schema cannot be healed even though the existing non-PostgreSQL contract expects no ALTER/constraint exception.
- **Impact:** Test/development databases that already contain the run tables fail schema synchronization rather than converging, and the existing dialect abstraction has a new unsupported-dialect failure mode.
- **Fix:** Define an explicit non-PostgreSQL policy for additive CHECKs (dialect-specific rebuild or a tested no-op when the dialect already materializes the constraint), and cover a pre-timing SQLite table with the same healer path.

#### GPUFLOW-1-TIMINGMODELS-R-07 — low

- **File:** `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py:562-575`
- **Evidence:** The new PostgreSQL non-finite test imports `db.models.scene` and iterates ORM model constraints; it never instantiates the separate `sa.CheckConstraint` declarations emitted by `ensure_tables`. A future model/migration drift could therefore make the deployed migration accept infinity while this regression test remains green.
- **Impact:** The proof does not pin the actual upgrade/healing schema that production uses.
- **Fix:** Build the probe from the migration declarations (or apply `ensure_tables` to a scratch schema) and exercise the exact database constraints.

#### GPUFLOW-1-TIMINGMODELS-R-08 — low

- **File:** `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py` and `docs/runbooks/prod-identity-rls-remediation.md`
- **Evidence:** The lane ownership row names the migration, `db/models/scene.py`, and the scene timing test, but this fix delta also changes the recognition migration test and the production runbook. Those paths are outside the declared `timing-models` owned list, so the fix commit crosses lane ownership without an ownership/merge update.
- **Impact:** Parallel merge review cannot attribute or safely reconcile these edits from the lane manifest alone.
- **Fix:** Add both paths to the lane ownership/dependency manifest or split the test/runbook repairs into their owning lane before merge.

Verdict: pass_with_findings
