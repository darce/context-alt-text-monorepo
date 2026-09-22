# APP-1 read-route census — `GET /recognition/jobs/{job_id}`

Date: 2026-09-22. Lane-owned receipt for the pending P02 FREE-POLL census in
`app1-offline-residual-scope-20260922.md`. This is contract verification, not a
metering or worker rereview. `[GRPH-09][GRPH-31][DDIA-TRANSACTIONS][DDIA-FENCING][RES-01]`

## Route classification

| Route | Handler | Dependencies / seams | Classification |
| --- | --- | --- | --- |
| `GET /recognition/jobs/{job_id}` | `recognition/interface_adapters/http/routers/analyze.py::get_job_status` (lines 486–538) | Router: `Depends(require_auth)`, `Depends(enforce_rate_limit)`. Handler: `get_job_service_dependency` then optional `SqlAlchemyJobRepository(session).get(job_id)` via `get_optional_session`; pipeline body is `_job_to_pipeline_response` / `_resolve_pipeline_job`. Query `tenant_id` is declared but unused in the handler. Session tenant context comes from `get_tenant_id_optional` (header or query). Usage admission is **not** on this path: compute admission remains `usage_admission.py::admit_usage`; terminal settlement remains `UsageSettlementService`. | **FREE-POLL**: authenticated, intended tenant-scoped status/pipeline read; zero customer usage units; per-key rate limit is the only metering. Status reads never charge. |

`get_job_service_dependency` calls `get_job_service(session=None, tenant_id=None)`
(in-memory repo). A miss falls through to SQL `get(job_id)` with no Python
`tenant_id` predicate. `[DATA-03]`

## Proof each test provides

Owned file:
`apps/prototype-description-service/recognition/tests/api/test_app1_read_route_census.py`.

Auth stays enabled (`RECOGNITION_AUTH_ENABLED=1`, `RECOGNITION_RUNTIME_MODE=production`).
`require_auth` is not overridden. External compute is not invoked. Valid-key tests
mock `_lookup_api_key` only; the invalid-key test uses the real lookup against an
empty FakeSession store.

| Test | Proof provided | Result |
| --- | --- | --- |
| `test_missing_api_key_denied_under_production_auth` | Production `require_auth` 401 before lookup; ledger spy empty | GREEN |
| `test_invalid_api_key_denied_under_production_auth` | Production `require_auth` + real `_lookup_api_key` 403 `invalid or missing API key`; ledger spy empty | GREEN |
| `test_owner_poll_returns_200_without_usage_admission` | Authenticated owner 200; `admit_usage` not entered; spy `reserves/commits/releases` empty | GREEN |
| `test_unknown_job_is_404_without_usage_charge` | Authenticated unknown job 404 `Job not found`; no admission | GREEN |
| `test_other_tenant_cannot_read_job_even_by_spoofing_query_tenant_id` | Handler/auth-boundary tenant fencing (in-memory job service). **Not** PostgreSQL RLS. | **RED** |
| `test_pipeline_followup_is_tenant_scoped_and_free` | Owner follow-up poll is 200 clustering/FREE-POLL; other tenant must 404 | Owner 200 GREEN; other-tenant **RED** |

Existing unit
`recognition/tests/unit/test_app1_usage_recognition_lifecycle.py::test_get_job_status_does_not_reserve`
covers read-semantics (one prior reservation after 202, status GET does not
reserve). It still 404s because that harness's job service has no job; it does
not prove successful poll or tenant privacy.

PostgreSQL was not available in this sandbox (`DATABASE_URL` unset; telemetry
background `record_api_key_use` logged `database "alt_context_service" does not
exist`). No RLS receipt is claimed. The in-memory handler leak is already
sufficient HIGH evidence.

## HIGH — tenant fencing absent on GET job-status

`get_job_status` authenticates the caller and then returns any job found by id.
It does not compare `job.tenant_id` to `auth.tenant_claim`, and it does not use
`get_authenticated_tenant_id`. `require_auth` only mismatches when both a key
claim and `X-Tenant-ID` are present; a second tenant can omit the header and
pass `?tenant_id=<owner>`.

Exact RED:

- `test_other_tenant_cannot_read_job_even_by_spoofing_query_tenant_id` expected
  404, got **200** with the owner's analyze job body (`type=analyze`,
  `status=running`).
- `test_pipeline_followup_is_tenant_scoped_and_free` owner poll returned 200
  clustering follow-up; the other tenant with a matching key and spoofed query
  `tenant_id` also got **200** clustering body.

Tests were not weakened. Source outside the two owned files was not edited.
Coordinator owns any handler fix (`analyze.py::get_job_status` plus tenant
predicate / `get_authenticated_tenant_id`). `[DDIA-FENCING]`

## Exact TEST_CMD

Environment: `UV_NO_SYNC=1` (lane interpreter
`/home/gate/grok-sandbox/.venv-lane-feature-app-1-read-route-census-28925ffd/bin/python3`;
`analyze.py` imported from this checkout). uv sync was not written.

```sh
UV_NO_SYNC=1 uv run --directory apps/prototype-description-service --extra dev python -m pytest recognition/tests/api/test_app1_read_route_census.py recognition/tests/unit/test_app1_usage_recognition_lifecycle.py -q -p no:randomly --timeout=60
```

Result: exit 1; **2 failed, 14 passed, 1 warning in 1.55s**.

- Census: 4 passed, 2 failed (tenant fencing HIGH above).
- Lifecycle file: all passed, including `test_get_job_status_does_not_reserve`.

Earlier census-only run: 2 failed, 4 passed in 0.89s (same two failures).

## Residual P02 / V boundary (unchanged)

This receipt enumerates the pending GET job-status census and records the
authenticated FREE-POLL / no-charge proofs plus the HIGH fencing gap. It does
**not** close whole `APP1-CONT-P02`.

OPEN-Q topology / suggestions / retention / tenant-naming budgets remain
policy decisions; no prices are assigned. `POST /roster/curation/sync` remains
outside the app-host customer allowlist; its API auth/exclusion decision is
still open. Host `HOST-RV01` and genuine Clerk / Polar / restore V gates remain
open. No new UX map. Existing usage admission and terminal settlement fixes
were not re-opened; no metering change is required for this GET.
