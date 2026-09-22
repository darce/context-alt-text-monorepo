# APP-1 usage/schema finding adjudication and fix groups

Document-only handoff for lane `usage-adjudicate`, checked against the exact
current checkout on 2026-09-22. This lane makes no production or test change.
The only intended delta is this assessment. The supplied feature commit IDs are
not resolvable in this checkout; the symbols and tests below are therefore
source anchors, not claims about an unseen commit.

## Disposition boundary

The four assigned HIGH findings are implementation gaps confirmed from source.
The focused baseline proves only existing usage-admission wiring; it does not
prove any finding fixed. Runtime PostgreSQL evidence for these findings is
absent. “Confirmed” below means the current code has a concrete path that
violates the stated contract, not that a live race receipt was produced.

| Finding | Disposition | Verified current state and concrete failure path | Required closure evidence |
| --- | --- | --- | --- |
| **15849 — global daily budget / in-flight / queue / stop admission** | **Confirmed** | `AsyncAdmissionGate` in `scene/interface_adapters/http/routers/describe.py:126-174` is process-local, starts counters at zero on every boot, and bounds only pending jobs and retained image bytes. `UsageReservation` in `db/models/portal_billing.py:130-156` and `recognition/infrastructure/repositories/usage_repository.py:131-234` serialize one tenant entitlement and sum tenant reservations, but define no durable global daily cost, global in-flight count, queue/byte state, stop epoch, or worker fence. `_stop_requested` reads a local GPU-intent file (`describe.py:703-705`) and is not the async enqueue admission authority. A second API process can see an empty local gate; a restart resets it while persisted jobs remain. `maybe_consume_demo_quota` also explicitly skips when its session is unavailable (`recognition/interface_adapters/http/deps/demo_quota.py:169-204`). | A real PostgreSQL concurrent multi-process reservation test must show global caps, queue bounds, and stop/fence state remain correct across duplicate settlement and restart/reclaim. Missing state or persistence must return stable 503/refusal. No raw APP-1 usage PG receipt was found; do not infer one from `/tmp/pg-backend.log` or the unrelated `/tmp/vlmheal-pg-gate.log`. |
| **15850 — scene multipart / async / run coverage** | **Confirmed, bounded to scene compute ingress** | The existing common helper is exercised by recognition routes (`recognition/interface_adapters/http/deps/usage_admission.py:110-155`), and the assigned baseline test covers that recognition wiring. The scene surfaces do not use it: `describe_image_multipart` calls `maybe_consume_demo_quota` from `_before_compute` (`scene/interface_adapters/http/routers/describe.py:1251-1382`); `enqueue_describe_image` calls demo quota plus the local gate (`describe.py:1630-1679`); `create_describe_run` uses the demo pre-check and demo quota (`scene/interface_adapters/http/routers/describe_run.py:508-643`). The bulk route has a tenant/idempotency-key replay guard, but that is not the common usage reservation and does not cover the async single-run route. | A route-census test must enumerate the three scene compute POSTs and prove each reaches the frozen admission contract before costly work, or returns an explicit beta denial before side effects. Repeated GET polling must remain free. Existing recognition wiring tests do not satisfy this scene census. |
| **15851 — HTTP 202 prematurely commits usage** | **Confirmed** | `enqueue_describe_image` durably consumes demo quota before queue admission (`describe.py:1657-1666`), then commits the run before its `BackgroundTasks` worker is scheduled (`describe.py:1671-1709`); a full queue or process death after 202 can leave a charge without work. `create_describe_run` commits the demo charge/run before scheduling `run_describe_job` (`describe_run.py:637-678`). The generic `admit_usage` context commits when the HTTP handler body exits (`usage_admission.py:138-155`), so a normal 202 is treated as terminal admission success rather than worker terminal settlement. | Tests must show HTTP 202, status reads, and result reads do not commit; queue rejection and pre-pickup restart release exactly once; worker success/failure and post-pickup cancellation commit exactly once; duplicate/stale worker callbacks cannot settle a newer reservation. The worker must own the settlement edge. |
| **15852 — content-hash / operation reuse** | **Confirmed** | The usage identity is only `(tenant_id, idempotency_key)`: `UsageTicket` has no operation or fingerprint (`recognition/domain/portal_contracts.py:72-78`), the protocol accepts only `idempotency_key`, `job_id`, and `cost_units` (`portal_contracts.py:146-165`), and the repository returns an existing row by key while ignoring new job/cost inputs (`usage_repository.py:97-111`, `131-234`). The scene bulk digest is intentionally only sorted media IDs plus `recognition_enabled` and explicitly excludes image bytes (`scene/domain/describe_run.py:125-161`); `create_single_run` has no idempotency or digest binding (`describe_run_repository.py:213-249`). The multipart operation ledger does hash image bytes/context (`describe.py:333-341`) and rejects a mismatched operation, but that identity is not bound to `UsageReservation`; async does not call `_accept_operation`. Thus a same operation/key with changed content can reuse a reservation/run, while the async path can create a second unbound single run. | Freeze `(tenant_id, operation_id, request_fingerprint)` as the retry identity. Same tuple replays one reservation/job; same operation with a different fingerprint is 409 with no new row; a new operation is independently chargeable. Add concurrent collision, tenant-isolation, equal-payload/new-operation, and changed-content tests for multipart, async, and run. The current test `test_same_key_and_media_ids_with_different_bytes_replays_by_contract` documents the weaker v1 contract; it is not proof against this finding. |

### Adjacent schema finding verified during the bounded review

`001_identity_schema.py:102-149` includes `billing_checkout_attempt` in
`EXPECTED_SCHEMA_TABLES`, and `TENANT_TABLES` includes it at lines 31-39, so
`ensure_rls` applies enabled+forced tenant RLS. The checked-in assertion in
`recognition/tests/test_identity_schema_migration.py:90-137` omits
`billing_checkout_attempt`. The recognition SQLite fixture imports
`db.models.portal_billing` through `db.models`, but
`recognition/tests/conftest.py:47-69` neither creates nor excludes that mapped
table. This is a confirmed inventory/fixture drift, not evidence that checkout
RLS is absent. `recognition/tests/integration/test_app1_checkout_attempt_persistence.py:49-85`
contains the intended PostgreSQL table/index/RLS check, but no raw receipt for
that test is present in this checkout.

The existing migration is the upgrade authority: `upgrade()` calls
`ensure_tables`, `ensure_rls`, and related convergence helpers
(`db/migrations/versions/001_identity_schema.py:3150-3160`). Existing tables get
additive columns; missing table-level constraints fail loudly unless explicitly
listed as heal-additive (`001_identity_schema.py:390-452`). Any usage schema
change therefore needs an expand/backfill/validate sequence for existing rows,
an exact `EXPECTED_SCHEMA_TABLES`/`DOWNGRADE_TABLE_ORDER` update, explicit
indexes/constraints, and RLS classification. Do not run a production migration
as part of this lane.

## Frozen interface contract before implementation

The following is the minimum compatible boundary. It lets global ledger/schema
work proceed independently of scene/worker lifecycle while preventing an
incompatible ticket shape from landing first. This follows the supplied canon
constraints for disjoint ownership `[GRPH09]`, critical-path edges `[GRPH31]`,
and bounded headroom `[PERF13]`; the local source records for those canon IDs
are not present, so they are cited as design constraints rather than fresh
verification evidence.

1. Admission input is a canonical, tenant-scoped tuple
   `(tenant_id, operation_id, request_fingerprint)`. The fingerprint covers
   normalized route mode, media identifiers and bytes/digests, context,
   recognition/tier options, and every other input that changes work.
2. `reserve` receives that identity and a pre-generated job/run binding. Its
   transaction locks the tenant allowance and durable global state, validates
   all limits and stop/fencing state, inserts one reservation, and persists the
   reservation-to-job binding before dispatch. A unique collision reads the
   winner and compares the fingerprint; it must never silently accept a changed
   request.
3. `UsageTicket` carries reservation ID, tenant ID, operation ID, fingerprint,
   job/run ID, cost, and the pickup/fencing token required by settlement.
   `commit`/`release` (or one equivalent terminal-settlement method) are guarded
   by reservation ID plus fence and are idempotent. A stale fence cannot settle
   a newer retry.
4. Only the worker terminal path settles usage. A queue refusal or cancellation
   before pickup releases; any attempted compute commits; restart reclaim must
   release/expire a reservation with no work performed. 202 is pending only.
   Status/result reads are tenant-scoped and free.
5. Missing global rows, required configuration, database connectivity, or
   fencing state is fail-closed 503/refusal. No caller may convert unavailable
   persistence into an unmetered compute path.

## Complete disjoint fix groups

Each group owns the listed paths only. Cross-group behavior is an interface edge,
not shared-file ownership. Tests listed under a group are the minimum scoped
receipts for that group; they are not claims that those tests currently pass.

| Group | Exclusive owned paths | Contract and exact scoped tests |
| --- | --- | --- |
| **G1 — durable ledger/global admission** | `recognition/domain/portal_contracts.py`; `recognition/application/services/usage_admission_service.py`; `recognition/infrastructure/repositories/usage_repository.py`; `recognition/interface_adapters/http/deps/usage_admission.py`; `db/models/portal_billing.py`; `db/migrations/versions/001_identity_schema.py` | Add operation/fingerprint/fence to the ticket and reservation; add durable global period/limit state for daily cost, in-flight, queue bounds, stop state, and fencing. Preserve tenant scope and idempotent settlement. Current unit scope: `recognition/tests/unit/test_app1_usage_admission_service.py` and `recognition/tests/unit/test_app1_usage_admission_wiring.py`; required new PG race scope: `recognition/tests/integration/test_app1_usage_admission_postgres.py` (new path). |
| **G2 — scene ingress/admission** | `scene/domain/describe_run.py`; `scene/application/describe_operation_repository.py`; `scene/interface_adapters/http/routers/describe.py`; `scene/interface_adapters/http/routers/describe_run.py` | Generate operation/job ID, canonical fingerprint, and reservation binding before costly reads/queue dispatch. Remove handler-side terminal settlement; keep decorative/cache-hit and polling paths free. Scope: `scene/tests/test_describe_route.py`, `scene/tests/test_describe_run_idempotency.py`, `scene/tests/test_describe_run_quota.py`, plus a new scene admission route-census test covering multipart/async/run. |
| **G3 — worker lifecycle/settlement** | `scene/application/describe_run_repository.py`; `scene/application/describe_run_worker.py`; `scene/application/describe_async_worker.py`; `recognition/worker/scan_worker.py` | Persist pickup fence, route success/failure/cancel/reclaim through one settlement, and reconcile persisted reservations/jobs on restart. Scope: `scene/tests/test_describe_async_repository.py`, `scene/tests/test_describe_async_worker.py`, `scene/tests/test_describe_run_worker_phases.py`, and `recognition/tests/unit/test_app1_usage_sweeper.py`. |
| **G4 — operator route census** | `scene/interface_adapters/http/routers/gpu.py`; `recognition/interface_adapters/http/routers/clusters_admission.py`; `recognition/interface_adapters/http/routers/cluster_revert.py` | Every compute/mutation operator surface must use G1 or beta-deny before side effects; status routes remain free. Scope: a new route-census test for `/gpu/intent`, clustering/recovery/revert mutations, and free `/gpu/status` polling. This group is independent of G3 and must not acquire worker-file ownership. |
| **G5 — schema fixtures and PostgreSQL evidence** | `recognition/tests/test_identity_schema_migration.py`; `recognition/tests/conftest.py`; `recognition/tests/schema/test_identity_schema_pg.py`; `recognition/tests/schema/test_identity_schema_heal_pg.py`; `recognition/tests/integration/test_app1_checkout_attempt_persistence.py` | Mirror migration table inventory exactly (including existing `billing_checkout_attempt` and any new global table), add checkout to SQLite exclusions or explicitly provision it, assert usage columns/constraints/indexes and RLS classification, and require a non-privileged PG role. This group owns test/fixture paths only; G1 owns migration/model paths. |

No group owns a sibling lane path. In particular, this lane owns only this
assessment, not any of the paths above.

## Dependency DAG and path-conflict edges

```text
I0: freeze G1 ticket/reservation/fence interface
 ├──► G1 durable ledger + migration ──► G5 schema/PG receipts
 ├──► G2 scene ingress ──► G3 worker binding/settlement
 └──► G4 operator route census

G1 ──► G2 and G4 (shared admission contract only)
G2 ──► G3 (persisted job binding and terminal callback edge)
G5 ──► release decision for G1 schema; it does not serialize G2/G3 code work
```

G1 and G5 may execute independently of scene/worker lifecycle after I0. G2 and
G4 may run in parallel once the interface is frozen. G3 needs the persisted
binding shape from G1/G2, but worker implementation and scene route edits do not
need to be serialized with G4. The only path-conflict edges are the explicit
file owners above; no false precedence should serialize the entire repository.

## Schema/fixture repair checklist

These are the concrete documentation outputs for the next implementation owner;
this lane does not apply them.

- Extend `001_identity_schema.py` through its existing `ensure_tables` authority:
  usage reservation fingerprint/operation/job/fence fields, global admission
  state, indexes, checks, downgrade order, and `EXPECTED_SCHEMA_TABLES`. Decide
  explicitly whether the global state is non-tenant (no tenant RLS policy) or a
  tenant table; do not accidentally apply tenant policy to a singleton global
  row.
- For existing installations, add nullable/expand columns first, backfill and
  validate before tightening nullability/uniqueness. Use named
  `heal_constraints` only for declared additive constraints; duplicate live rows
  must fail with an operator-readable repair path. Do not treat a fresh SQLite
  `create_all` as an existing-DB upgrade proof.
- Update `test_identity_schema_migration.py` so its literal expected list matches
  migration `EXPECTED_SCHEMA_TABLES` (it currently omits
  `billing_checkout_attempt`) and add assertions for the usage/global table
  columns, constraints, indexes, and downgrade order.
- Update `recognition/tests/conftest.py::SQLITE_TEST_TABLE_EXCLUSIONS` for every
  portal/billing table intentionally outside `db_session` (currently
  `billing_checkout_attempt` is imported into metadata but is neither created nor
  excluded). Keep usage unit fixtures explicit; SQLite is not the global-race
  proof.
- Preserve checkout RLS authority: `billing_checkout_attempt` is already in
  `TENANT_TABLES`; the existing PG checkout test must run under the required
  non-superuser/non-`BYPASSRLS` role. A skipped or privileged run is not a green
  RLS receipt.

## Exact verification commands and evidence status

The lane baseline requested by the coordinator is:

```bash
uv run --directory apps/prototype-description-service --extra dev \
  python -m pytest recognition/tests/unit/test_app1_usage_admission_wiring.py \
  -q -p no:randomly --timeout=60
```

The exact wrapper attempted in this checkout could not sync its shared
environment because it tried to remove `/home/gate/grok-sandbox/.venv-.../bin/alembic`
on a read-only filesystem. The same test passed with the lane-root interpreter;
that is the only baseline receipt recorded for this document. Import-origin
control resolved `recognition` to this checkout's
`apps/prototype-description-service/recognition/__init__.py` before the run.

The actual scoped PostgreSQL schema/RLS command for the next owner is:

```bash
IDENTITY_PG_REQUIRED=1 uv run --directory apps/prototype-description-service --extra dev \
  python -m pytest \
  recognition/tests/test_identity_schema_migration.py \
  recognition/tests/schema/test_identity_schema_pg.py \
  recognition/tests/schema/test_identity_schema_heal_pg.py \
  recognition/tests/integration/test_app1_checkout_attempt_persistence.py \
  -q -p no:randomly --timeout=60
```

It uses the scratch-DB fixtures in `recognition/tests/conftest.py`; it must not
be pointed at a production database. The broader repository target is
`IDENTITY_PG_REQUIRED=1 uv run pytest -m "integration or pg or timing"`, as
declared by `apps/prototype-description-service/Makefile:327-332`, but it is
not the minimum scoped receipt for this lane. The required future usage proof
adds `recognition/tests/integration/test_app1_usage_admission_postgres.py` to
the same command and records database identity, role/RLS state, scenario result,
commit, and artifact digest.

No raw APP-1 usage PostgreSQL receipt exists in this checkout. The generic
`/tmp/pg-backend.log` is server logging, not a test receipt; the only similarly
named test log, `/tmp/vlmheal-pg-gate.log`, is for an unrelated schema-heal run
and reports a skipped privilege case. Neither supports a claim about 15849–15852.

## Minimum named fix wave

**Wave 1 (parallel after I0):** G1 implements the durable ticket/global ledger
and existing-DB schema contract; G5 repairs inventory/exclusion assertions and
starts the required PG schema/RLS receipt. G2 wires all three scene compute
POSTs to the frozen contract, while G4 completes the operator route census.

**Wave 2:** G3 binds reservations to persisted jobs and moves settlement to
worker terminal/reclaim paths. Run the scene lifecycle tests plus the real PG
concurrency/restart evidence, then perform one bounded integration review.

The minimum release bar is not the current nine-test baseline: all four HIGH
contracts must have the route/lifecycle assertions above, and global/race/RLS
claims require genuine PostgreSQL receipts rather than SQLite or skipped tests.
