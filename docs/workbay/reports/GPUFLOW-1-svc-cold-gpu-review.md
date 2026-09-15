# GPUFLOW-1 svc-cold-gpu review

## Re-review r3 (ecefefc9b..783260180)

VERIFIED: {"GPUFLOW-1-SVCCOLDGPU-R-03":"not_fixed","GPUFLOW-1-SVCCOLDGPU-R-06":"partially_fixed","GPUFLOW-1-SVCCOLDGPU-R-07":"fixed","GPUFLOW-1-SVCCOLDGPU-R-08":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCCOLDGPU-R-03 | not_fixed | `.review/CHANGE.diff:87-109` changes the non-GPU persistence-failure log from DEBUG to WARNING but still returns `None, operation_id or _mint_operation_id()` as a successful path; the delta does not establish durable operation correlation before that response. |
| GPUFLOW-1-SVCCOLDGPU-R-06 | partially_fixed | `.review/CHANGE.diff:34-65,124-145` probes the GPU cache before acceptance and skips the lease for the first observed hit/error, but it only stores a boolean and leaves the service's later cache lookup in place. A miss followed by an exception in that second lookup can still occur after `_accept_operation`, before `_complete_operation`; the added exception test only fails the first lookup (`.review/CHANGE.diff:239-257`). |
| GPUFLOW-1-SVCCOLDGPU-R-07 | fixed | `.review/CHANGE.diff:71-85,87-102` removes minted IDs from the no-session and GPU accept-failure 503 branches, and `.review/CHANGE.diff:214-229,260-274` asserts that those errors omit operation metadata and can be retried without reusing a non-durable token. |
| GPUFLOW-1-SVCCOLDGPU-R-08 | fixed | `.review/CHANGE.diff:71-102,149-164` removes `retry_after` from the non-starting unavailable branches while retaining it only on the starting path; the updated route tests assert its absence (`.review/CHANGE.diff:205-223,239-274`). |

The supplied delta changes only the owned route and route-test paths; no out-of-scope path is present.

### FINDINGS

#### GPUFLOW-1-SVCCOLDGPU-R-09 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:825-837`.
- **Evidence:** `.review/CHANGE.diff:124-145` initializes `op = None`, mints or echoes `operation_id`, and bypasses `_accept_operation` whenever the preflight GPU cache lookup returns a row. The unchanged completion path therefore receives no operation to terminalize, while the response still uses that ID. A fresh cache success advertises an ID with no durable `DescribeOperation`/lease; a retry carrying an existing active ID also bypasses validation/renewal and completion, leaving its prior lease active. The revised test deliberately checks the first generated operation at `.review/CHANGE.diff:200-201` instead of asserting that the cached response ID is durable. This violates the persisted correlation/token invariant ([API-09], [RES-08]).
- **Impact:** Cache responses can publish unbound correlation tokens and retain abandoned GPU demand across a cache-hit retry, so downstream retries and load aggregation cannot trust operation state.
- **Fix:** Preserve the cache bypass for fresh compute eligibility, but validate/resolve a supplied operation token and terminalize its persisted lease; for a fresh cache response either persist a completed operation before returning its ID or use a response contract that does not advertise an operation token.

Verdict: fail

## Re-review r4 (783260180..2927c23fb)

VERIFIED: {"GPUFLOW-1-SVCCOLDGPU-R-03":"not_fixed","GPUFLOW-1-SVCCOLDGPU-R-06":"partially_fixed","GPUFLOW-1-SVCCOLDGPU-R-09":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCCOLDGPU-R-03 | not_fixed | `.review/CHANGE.diff:47-63,107-115` stops returning the submitted token from the non-GPU persistence-failure branch, but the success builder still mints an `operation_id` when `_accept_operation` returned `None`; the response remains correlated to no durable operation. |
| GPUFLOW-1-SVCCOLDGPU-R-06 | partially_fixed | `.review/CHANGE.diff:67-105` moves acceptance after a preflight lookup and completes a preflight cache hit, but keeps only a boolean and still calls the service's second cache lookup after acceptance; a miss followed by that lookup failing can leak the active lease. The added exception test only exercises the preflight lookup (`.review/CHANGE.diff:161-171`). |
| GPUFLOW-1-SVCCOLDGPU-R-09 | fixed | `.review/CHANGE.diff:67-105` always passes the submitted token through `_accept_operation`, then terminalizes cache hits with `_complete_operation`; fresh cache hits therefore get a persisted completed operation and retries validate/complete the supplied lease. The new mismatch and retry tests cover these paths (`.review/CHANGE.diff:222-262`). |

### FINDINGS

#### GPUFLOW-1-SVCCOLDGPU-R-10 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:824-858`.
- **Evidence:** `.review/CHANGE.diff:67-105` stores only `cached_gpu = cached_row is not None`, accepts the operation, and then unconditionally invokes `VisualFactsService.describe`. That service performs its own cache query (`apps/prototype-description-service/scene/application/visual_facts_service.py:246-269`). If the preflight misses and the second query raises a generic database exception, the route has already accepted an active lease but its generic exception path does not call `_complete_operation`, so the request becomes an untyped 500 and demand remains active. If a preflight hit disappears before the second query, the new code can complete the lease as cached and then perform real adapter work without an active demand lease. The added exception regression only raises in the preflight query (`.review/CHANGE.diff:161-171`).
- **Impact:** A cache race can either leak GPU demand indefinitely or run GPU compute after the operation was terminalized, violating the admission/lease invariant.
- **Fix:** Carry the preflight row into the service or make one cache lookup authoritative; ensure every post-accept failure completes/rejects the operation before returning a typed error.

#### GPUFLOW-1-SVCCOLDGPU-R-11 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:309-328`.
- **Evidence:** `.review/CHANGE.diff:13-28` removes the persisted-only guard and unconditionally sets `operation_id` to `operation_id or _mint_operation_id()` in every typed error. The no-session GPU branch still has no accepted operation (`.review/CHANGE.diff:35-43`), and the GPU accept-failure path can pass `None` after persistence fails (`.review/CHANGE.diff:47-53`); both now return a fresh token that cannot be renewed or correlated. The success fallback likewise mints after a non-GPU accept failure (`.review/CHANGE.diff:107-115`). The revised tests assert these fabricated IDs rather than durable binding (`.review/CHANGE.diff:149-195`).
- **Impact:** Clients receive opaque-looking operation IDs that do not exist in the durable operation/lease tables; retrying them produces mismatch instead of renewing the same operation, and downstream consumers cannot trust error correlation.
- **Fix:** Do not mint operation metadata unless an operation was durably accepted; either make the schema permit absent IDs for pre-accept failures or persist the operation before publishing the typed error.

Verdict: fail

## Re-review r5 (2927c23fb..529bf75aa)

VERIFIED: {"GPUFLOW-1-SVCCOLDGPU-R-01":"fixed","GPUFLOW-1-SVCCOLDGPU-R-02":"fixed","GPUFLOW-1-SVCCOLDGPU-R-03":"fixed","GPUFLOW-1-SVCCOLDGPU-R-04":"fixed","GPUFLOW-1-SVCCOLDGPU-R-05":"fixed","GPUFLOW-1-SVCCOLDGPU-R-06":"fixed","GPUFLOW-1-SVCCOLDGPU-R-07":"fixed","GPUFLOW-1-SVCCOLDGPU-R-08":"fixed","GPUFLOW-1-SVCCOLDGPU-R-10":"partially_fixed","GPUFLOW-1-SVCCOLDGPU-R-11":"fixed"}

FINDINGS: [
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-12","severity":"high","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py","line":796,"summary":"Failure cleanup fabricates a readiness observation","evidence":"The new terminalizer calls _complete_operation(..., cached=False) (.review/CHANGE.diff:167-190), while that routine observes ready whenever first_ready_at is null; the generic cleanup is invoked for a service exception before adapter dispatch (.review/CHANGE.diff:451-466,715-734)."},
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-13","severity":"high","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py","line":1042,"summary":"Post-accept HTTPException paths bypass lease cleanup","evidence":"The route keeps `except HTTPException: raise` ahead of the new timeout/generic terminalizer (.review/CHANGE.diff:378-394,451-466). GPU before_compute performs readiness before quota consumption (.review/CHANGE.diff:297-306), and the quota gate can raise HTTPException, leaving the accepted lease active."},
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-14","severity":"medium","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py","line":396,"summary":"Miss-cache proxy breaks duplicate-insert recovery","evidence":"_PreflightMissCacheRepository.get_by_cache_key always returns None (.review/CHANGE.diff:33-43) and is installed for every GPU preflight miss (.review/CHANGE.diff:261-267). ImageDescriptionRepository.insert_or_get_existing uses get_by_cache_key after an IntegrityError, so a concurrent identical GPU miss re-raises instead of returning the winner's cache row and becomes a 502."},
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-15","severity":"high","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py","line":621,"summary":"Mismatch errors echo unvalidated client operation IDs","evidence":"The r5 hunk changes OperationMismatchError handling to return operation_id=operation_id (.review/CHANGE.diff:67-80). _optional_operation_id accepts arbitrary length strings, while the repository rejects values over 128 and the shared error schema caps operation_id at 128 (.review/CHANGE.diff:983-992); unknown IDs are also not service-minted or durably bound."},
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-16","severity":"low","file_path":"packages/shared-contracts/schemas/scene-describe-multipart.schema.json","line":1,"summary":"Delta changes dependency/producer paths outside the lane-owned list","evidence":"The delta changes responses.py, the shared multipart schema, and several producer/schema tests in addition to the route/test paths (.review/CHANGE.diff:507-526,784-873,951-996; .review/DIFFSTAT.txt:1-9), although the lane row lists contracts and response-models as read-only dependencies."}
]

Verdict: fail

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCCOLDGPU-R-01 | fixed | The resulting `_ensure_gpu_ready` keeps startup association behind the waiting-state guard and the READY branch only observes readiness; the r5 hunk changes only the snapshot publisher (`.review/CHANGE.diff:132-160`). |
| GPUFLOW-1-SVCCOLDGPU-R-02 | fixed | The route now carries the preflight row into `_response_from_cached_row`, bypasses the service cache read on hits, then completes the accepted operation with `cached=True` (`.review/CHANGE.diff:193-220,226-377`). |
| GPUFLOW-1-SVCCOLDGPU-R-03 | fixed | Accept persistence failures now roll back and raise a typed 503 for both adapter classes instead of returning success, and post-service failures are translated rather than silently succeeding (`.review/CHANGE.diff:67-129,378-466`). |
| GPUFLOW-1-SVCCOLDGPU-R-04 | fixed | The resulting route retains a separate GPU `DescriptionAdapterUnavailableError` 503 path and the GPU remote-error 502 path; the tail replacement does not recombine them (`.review/CHANGE.diff:391-394,451-466`). |
| GPUFLOW-1-SVCCOLDGPU-R-05 | fixed | The rejected expiry transition is committed/rescoped before the typed exception is raised (`.review/CHANGE.diff:81-93`). |
| GPUFLOW-1-SVCCOLDGPU-R-06 | fixed | Acceptance follows the single preflight lookup; cache hits use the fetched row and misses install a repository wrapper that prevents a second pre-compute lookup (`.review/CHANGE.diff:193-220,226-306`). The duplicate-insert consequence is reported as new R-14. |
| GPUFLOW-1-SVCCOLDGPU-R-07 | fixed | The mint helper and all no-session/accept-failure minting are removed; pre-accept errors and no-session CPU success carry null operation metadata (`.review/CHANGE.diff:17-43,47-64,67-129,359-370`). |
| GPUFLOW-1-SVCCOLDGPU-R-08 | fixed | Non-starting unavailable paths do not add `Retry-After`; only the starting branch retains the retry header (`.review/CHANGE.diff:47-64,132-160`). |
| GPUFLOW-1-SVCCOLDGPU-R-10 | partially_fixed | The authoritative row and miss wrapper resolve the stated second-read miss/hit race (`.review/CHANGE.diff:193-220,226-306`), and generic/timeout failures attempt cleanup (`.review/CHANGE.diff:378-466`); however, HTTPException paths still bypass cleanup, and the cleanup itself observes readiness on an unready operation (new R-12/R-13). |
| GPUFLOW-1-SVCCOLDGPU-R-11 | fixed | `_typed_describe_error` now preserves nullable operation metadata, `_mint_operation_id` is deleted, and no-session/accept-failure success/error paths explicitly use null (`.review/CHANGE.diff:17-43,47-64,121-129,359-370`). |

### FINDINGS

#### GPUFLOW-1-SVCCOLDGPU-R-12 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:796`.
- **Evidence:** The new `_terminalize_accepted_operation` calls `_complete_operation` with `cached=False` (`.review/CHANGE.diff:167-190`). `_complete_operation` first calls `repo.observe_ready` whenever the accepted operation has no `first_ready_at`; therefore a generic exception before `_before_compute` or adapter dispatch is recorded as readiness and then completed. The new service-exception test deliberately raises before adapter work (`.review/CHANGE.diff:715-734`) but checks only completed lease state, not the false `first_ready_at`/startup timing.
- **Impact:** A failed request can persist a fabricated first-ready transition and ramp-up/startup timing, violating the durable readiness and phase-timing contract ([API-09]).
- **Fix:** Terminalize pre-readiness failures through a state transition that does not call `observe_ready` (or retain them as rejected/active according to the error class), and assert no readiness observation on a pre-dispatch failure.

#### GPUFLOW-1-SVCCOLDGPU-R-13 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:1042`.
- **Evidence:** `except HTTPException: raise` remains before the new cleanup handlers (`.review/CHANGE.diff:378-394,451-466`). For a GPU miss, `_before_compute` runs `_ensure_gpu_ready` and then `_charge_demo_quota` (`.review/CHANGE.diff:297-306`); the quota gate can raise a 422/429 `HTTPException` after the operation was accepted, so the active lease is returned without terminalization. The same gap applies to any non-lifecycle HTTPException raised after acceptance.
- **Impact:** Rejected requests can keep GPU demand active until expiry, skewing `has_work`/lifecycle state and making cleanup depend on lease timeout rather than the request outcome.
- **Fix:** Distinguish lifecycle 503s that intentionally retain demand from post-accept quota/HTTP failures and terminalize the latter before re-raising.

#### GPUFLOW-1-SVCCOLDGPU-R-14 — medium

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:396`.
- **Evidence:** `_PreflightMissCacheRepository.get_by_cache_key` unconditionally returns `None` (`.review/CHANGE.diff:33-43`) and is attached whenever the preflight misses (`.review/CHANGE.diff:261-267`). The unchanged `ImageDescriptionRepository.insert_or_get_existing` calls `get_by_cache_key` after catching a duplicate-key `IntegrityError`; the wrapper returns `None`, causing it to re-raise and the route to return a typed 502 instead of using the concurrently inserted cache row.
- **Impact:** Concurrent identical GPU requests fail spuriously despite a valid cache result, so normal duplicate-work races become user-visible errors.
- **Fix:** Make only the initial service cache read authoritative, while preserving the repository’s duplicate-insert recovery lookup, or pass the fetched row/result through an explicit service API.

#### GPUFLOW-1-SVCCOLDGPU-R-15 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:621`.
- **Evidence:** The r5 change replaces the fabricated mismatch ID with the raw submitted token (`.review/CHANGE.diff:67-80`). The form parser does not enforce the 128-character bound, and the repository rejects overlong tokens before any durable operation is found; the resulting error can therefore carry an operation_id longer than the shared schema’s maxLength 128 (`.review/CHANGE.diff:983-992`). Even within the bound, an unknown client token is not service-minted or tenant/request-bound.
- **Impact:** Operation-mismatch errors can violate the strict multipart schema and publish correlation metadata that callers cannot renew or correlate ([API-09]).
- **Fix:** Return null for an operation ID that the repository did not verify as durable, or validate/canonicalize the token before constructing the typed error; never echo an unbound token into the service-minted field.

#### GPUFLOW-1-SVCCOLDGPU-R-16 — low

- **File:** `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:1`.
- **Evidence:** The complete delta changes eight files (`.review/DIFFSTAT.txt:1-9`), including `scene/interface_adapters/http/schemas/responses.py`, the shared schema, and producer/schema tests (`.review/CHANGE.diff:507-526,784-873,951-996`). Those are dependency/producer paths marked read-only in the lane row; only the route and designated lane tests/fixture are lane-owned.
- **Impact:** The fix cannot be cleanly merged as a lane-local change without taking unrelated producer changes or resolving ownership conflicts.
- **Fix:** Move producer/schema edits to their owning lanes and leave this lane consuming the committed artifacts.

Verdict: fail
