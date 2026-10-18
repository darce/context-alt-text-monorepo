# APP-1 read-route census — `GET /recognition/jobs/{job_id}`

Date: 2026-09-22. Lane-owned receipt for the pending P02 FREE-POLL census in
`app1-offline-residual-scope-20260922.md`. This is contract verification plus
the minimal handler tenant fence. Not a metering or worker rereview.
`[GRPH-09][GRPH-31][DDIA-TRANSACTIONS][DDIA-FENCING][RES-01][DATA-03]`

## Route classification

| Route | Handler | Dependencies / seams | Classification |
| --- | --- | --- | --- |
| `GET /recognition/jobs/{job_id}` | `recognition/interface_adapters/http/routers/analyze.py::get_job_status` (lines 571–640) | Router: `Depends(require_auth)`, `Depends(enforce_rate_limit)`. Handler: `get_job_service_dependency` then optional `SqlAlchemyJobRepository(session).get(job_id)` via `get_optional_session`; pipeline body is `_job_to_pipeline_response` / `_resolve_pipeline_job`. Query `tenant_id` is accepted for compatibility and is **not** tenant authority. Session tenant context still comes from `get_tenant_id_optional` (header or query) and is not bound to the API-key claim. Usage admission is **not** on this path: compute admission remains `usage_admission.py::admit_usage`; terminal settlement remains `UsageSettlementService`. | **FREE-POLL**: authenticated, tenant-scoped status/pipeline read; zero customer usage units; per-key rate limit is the only metering. Status reads never charge. |

`get_job_service_dependency` calls `get_job_service(session=None, tenant_id=None)`
and returns `JobService(repository=get_mem_job_repo())`. A miss falls through to
SQL `get(job_id)` with no SQL `tenant_id` predicate; the handler now applies a
Python owner fence using authenticated tenant authority before returning.
`[DATA-03][DDIA-FENCING]`

## Producer path (actual, not FakeJobService)

Census tests no longer override `get_job_service_dependency`. They isolate the
module singleton `_MEM_JOB_REPO` and seed `InMemoryJobRepository.jobs`.

Verified signatures from this checkout:

- `get_job_service_dependency()` → `await get_job_service(session=None, tenant_id=None)`
- `get_job_service(None, None)` → `JobService(repository=get_mem_job_repo(), …)`
- `JobService.get_job_status(job_id)` → `repository.get(job_id)` (unscoped by id)
- `InMemoryJobRepository` has `save`/`get`/`update` only. It does **not**
  implement `get_followup_clustering_job`. Pipeline follow-up on this path is
  resolved in `analyze.py::_load_followup_clustering_job` by scanning the mem
  `jobs` map after `JobService.get_followup_clustering_job` raises
  `AttributeError`. SQL repositories keep their existing follow-up query.

`require_auth` mismatches only when both a key claim and `X-Tenant-ID` are
present. `get_tenant_id_optional` still takes header **or** query and does not
bind auth. The handler therefore uses `_poll_tenant_authority`: key
`tenant_claim` wins; admin may use `X-Tenant-ID`; query `tenant_id` never
overrides; enabled auth without a tenant fails closed (403). Auth-disabled
returns `caller_tenant=None` so existing contract tests stay unfenced.
`JobStatusResponse` has no `tenant_id`; under enabled auth that unscoped
shape is 404.

## Proof each test provides

Owned file:
`apps/prototype-description-service/recognition/tests/api/test_app1_read_route_census.py`.

Auth stays enabled (`RECOGNITION_AUTH_ENABLED=1`, `RECOGNITION_RUNTIME_MODE=production`).
`require_auth` is not overridden. External compute is not invoked. Valid-key tests
mock `_lookup_api_key` only; the invalid-key test uses the real lookup against an
empty FakeSession store.

| Test | Proof provided | Result |
| --- | --- | --- |
| `test_get_job_service_dependency_uses_shared_mem_repo` | `get_job_service_dependency()` and `get_job_service(None, None)` share `get_mem_job_repo()`; loaded job is the seeded domain `Job` | GREEN |
| `test_missing_api_key_denied_under_production_auth` | Production `require_auth` 401 before lookup; ledger spy empty | GREEN |
| `test_invalid_api_key_denied_under_production_auth` | Production `require_auth` + real `_lookup_api_key` 403 `invalid or missing API key`; ledger spy empty | GREEN |
| `test_owner_poll_returns_200_without_usage_admission` | Authenticated owner 200 on real mem JobService; `admit_usage` not entered; spy `reserves/commits/releases` empty | GREEN |
| `test_unknown_job_is_404_without_usage_charge` | Authenticated unknown job 404 `Job not found`; no admission | GREEN |
| `test_other_tenant_cannot_read_job_even_by_spoofing_query_tenant_id` | Handler/auth-boundary tenant fencing on shared in-memory JobService. Query `tenant_id` spoof 404. **Not** PostgreSQL RLS. | GREEN (was RED 200 leak on this same producer) |
| `test_pipeline_followup_is_tenant_scoped_and_free` | Owner follow-up poll is 200 clustering/FREE-POLL; other tenant 404 | GREEN (owner was 500 `AttributeError` on mem repo before handler follow-up load; other tenant was also unfenced) |
| `test_pipeline_followup_foreign_tenant_is_not_returned` | Linked clustering job for another tenant is not substituted; owner sees original analyze | GREEN |
| `test_sql_fallback_job_is_tenant_fenced_without_rls` | FakeSession `IdentityScanJob` SQL `get(job_id)` fallback: owner 200, other tenant 404. **Not** PostgreSQL RLS. | GREEN (was RED 200 leak) |
| `test_admin_header_can_read_job_query_cannot_override_key_tenant` | Tenant key ignores spoofed query tenant; admin without `X-Tenant-ID` is 403; admin header reads the job | GREEN |

Existing unit
`recognition/tests/unit/test_app1_usage_recognition_lifecycle.py::test_get_job_status_does_not_reserve`
covers read-semantics (one prior reservation after 202, status GET does not
reserve). It still 404s because that harness's job service has no job; it does
not prove successful poll or tenant privacy. It remained GREEN.

## HIGH — tenant fencing (closed on the in-memory producer)

v6 used `FakeJobService` and still showed the leak. Strengthened reproduction
used the production `get_job_service_dependency` path. Exact RED on that path
before the handler fence:

- `test_other_tenant_cannot_read_job_even_by_spoofing_query_tenant_id` expected
  404, got **200** with the owner's analyze job body (`type=analyze`,
  `status=running`).
- `test_pipeline_followup_is_tenant_scoped_and_free` raised
  `AttributeError: 'InMemoryJobRepository' object has no attribute
  'get_followup_clustering_job'` (actual mem producer; FakeJobService had hidden
  this).
- `test_sql_fallback_job_is_tenant_fenced_without_rls` expected other-tenant
  404, got **200** from `SqlAlchemyJobRepository.get(job_id)` on FakeSession.
- `test_admin_header_can_read_job_query_cannot_override_key_tenant` expected
  admin-without-header 403, got **200**.

Handler fence (owned `analyze.py` only; no shared dependency rewrite):

- `_poll_tenant_authority` uses key tenant, then admin `X-Tenant-ID`.
- Mem `Job` and SQL fallback `Job` must match caller tenant or 404.
- Linked clustering follow-up is loaded and tenant-checked before return.
- Unscoped `JobStatusResponse` under enabled auth is 404.
- Auth-disabled compatibility is intentional (`caller_tenant is None`).

Tests were not weakened. Source outside the three owned files was not edited.

## Memory versus PostgreSQL

This sandbox has no usable PostgreSQL (`DATABASE_URL` unset; background
`record_api_key_use` logged `database "alt_context_service" does not exist`).
Evidence is:

1. **Shared in-memory JobService** (`get_mem_job_repo`) — executed, GREEN after
   fence.
2. **FakeSession SQL `get(job_id)`** — Python fence on the ORM-shaped scan row,
   executed, GREEN after fence.
3. **PostgreSQL RLS** — **not executed**. No RLS receipt is claimed.

The in-memory handler leak was already sufficient HIGH evidence; the fence is
proven on that producer and on FakeSession SQL fallback only.

## Exact TEST_CMD

Environment: `UV_NO_SYNC=1` (lane interpreter
`/home/gate/grok-sandbox/.venv-lane-feature-app-1-read-route-census-28925ffd/bin/python3`;
`analyze.py` imported from this checkout). uv sync was not written.

RED (census only, after producer-path test strengthening, before handler fence):

```sh
UV_NO_SYNC=1 uv run --directory apps/prototype-description-service --extra dev python -m pytest recognition/tests/api/test_app1_read_route_census.py -q -p no:randomly --timeout=60
```

Result: exit 1; **4 failed, 5 passed in 1.70s** (tenant leak, mem follow-up
`AttributeError`, FakeSession SQL leak, admin-unscoped 200).

GREEN (census only, after handler fence):

```sh
UV_NO_SYNC=1 uv run --directory apps/prototype-description-service --extra dev python -m pytest recognition/tests/api/test_app1_read_route_census.py -q -p no:randomly --timeout=60
```

Result: exit 0; **10 passed in 1.31s**.

Registered scope:

```sh
UV_NO_SYNC=1 uv run --directory apps/prototype-description-service --extra dev python -m pytest recognition/tests/api/test_app1_read_route_census.py recognition/tests/api/test_api_analyze.py recognition/tests/unit/test_app1_usage_recognition_lifecycle.py -q -p no:randomly --timeout=60
```

Result: exit 1; **2 failed, 34 passed, 1 warning, 6 errors in 16.52s**.

- Census: 10 passed.
- Lifecycle file: all passed, including `test_get_job_status_does_not_reserve`.
- `test_api_analyze.py` job-status / pipeline / unknown-job / projection tests:
  passed (auth-disabled compatibility held). Focused rerun of those plus census
  plus lifecycle: **26 passed, 16 deselected in 11.24s**.
- Unowned pre-existing failures in the same file, **not** caused by this fence:
  - `test_analyze_creates_job` and `test_analyze_job_starts_with_correct_progress`
    500 because `FakeScanQueueService.create_scan_job_record` does not accept
    `job_id` (`recognition/tests/api/conftest.py`; read-only in this lane).
  - six `test_apply_disposal_after_acknowledgement_*` errors:
    `db_session did not create all mapped SQLite tables; missing:
    billing_known_item_lease, billing_reconciliation_cursor,
    billing_reconciliation_item_progress, billing_reconciliation_quarantine`
    (`recognition/tests/conftest.py`; same fixture drift noted in
    `app1-usage-schema-fix-groups-20260922.md`).

## Residual P02 / V boundary (unchanged)

This receipt enumerates the GET job-status census, records FREE-POLL /
no-charge proofs, and closes the handler/auth-boundary HIGH fencing gap on the
in-memory producer and FakeSession SQL fallback. It does **not** close whole
`APP1-CONT-P02`. PostgreSQL RLS, Clerk, Polar, and live operations were not
available.

OPEN-Q topology / suggestions / retention / tenant-naming budgets remain
policy decisions; no prices are assigned. `POST /roster/curation/sync` remains
outside the app-host customer allowlist; its API auth/exclusion decision is
still open. Host `HOST-RV01` and genuine Clerk / Polar / restore V gates remain
open. No new UX map. Existing usage admission and terminal settlement fixes
were not re-opened; no metering change is required for this GET.
