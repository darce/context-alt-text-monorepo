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

## Re-review r6 (529bf75aa..3aa601740)

VERIFIED: {"GPUFLOW-1-SVCCOLDGPU-R-10":"partially_fixed","GPUFLOW-1-SVCCOLDGPU-R-12":"fixed","GPUFLOW-1-SVCCOLDGPU-R-13":"fixed","GPUFLOW-1-SVCCOLDGPU-R-14":"fixed","GPUFLOW-1-SVCCOLDGPU-R-15":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCCOLDGPU-R-10 | partially_fixed | The preflight row is now authoritative for hits and the miss wrapper delegates later duplicate-key lookups (`.review/CHANGE.diff:49-66,214-220`), while the route attempts cleanup for timeout, generic, and non-lifecycle HTTP failures (`.review/CHANGE.diff:121-153`). However, the new cleanup classifier can skip terminalization for a completion-generated 502 and the unready path is not concurrency-safe (new R-17/R-19). |
| GPUFLOW-1-SVCCOLDGPU-R-12 | fixed | `_terminalize_accepted_operation` now routes operations with no readiness observation to `_release_unready_operation`, which completes only the lease and operation completion timestamp without calling `observe_ready` (`.review/CHANGE.diff:97-135`). The regression asserts `first_ready_at` remains null (`.review/CHANGE.diff:214-219`). |
| GPUFLOW-1-SVCCOLDGPU-R-13 | fixed | The route now handles post-accept `HTTPException` values before re-raising and the quota regression verifies the accepted lease is completed on a 429 (`.review/CHANGE.diff:139-153,254-285`). Lifecycle starting/unavailable errors remain intentionally retained. |
| GPUFLOW-1-SVCCOLDGPU-R-14 | fixed | The miss repository suppresses only its first lookup and delegates subsequent lookups to the inner repository, preserving duplicate-insert recovery (`.review/CHANGE.diff:49-66`). The added unit test verifies the first miss followed by delegated calls (`.review/CHANGE.diff:288-305`). |
| GPUFLOW-1-SVCCOLDGPU-R-15 | fixed | Multipart operation IDs are now rejected when empty or over 128 characters, and mismatch errors no longer echo an unverified token (`.review/CHANGE.diff:23-42,70-78`). The new tests cover empty, oversized, and bounded unknown IDs (`.review/CHANGE.diff:228-251`). |

### FINDINGS

FINDINGS: [
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-17","severity":"high","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py","line":808,"summary":"Completion-error sentinel can leave an accepted lease active","evidence":"The new `_http_exception_already_terminalized` helper treats any `HTTPException` with code `description_service_error` as already cleaned and the route skips `_terminalize_accepted_operation` for it (`.review/CHANGE.diff:91-95,139-153`). `_complete_operation` can emit that 502 after rolling back a failed readiness/completion write, so the accepted lease remains active while the request returns an error."},
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-18","severity":"high","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py","line":800,"summary":"Lifecycle-retention decision trusts an unscoped error code","evidence":"`_preserves_demand_lease` keeps the lease whenever any post-accept `HTTPException` detail has code `description_service_starting` or `description_service_unavailable`, without checking status, phase, or that the error came from `_ensure_gpu_ready` (`.review/CHANGE.diff:83-89,139-153`). A later dependency failure reusing either code therefore bypasses cleanup and can publish a non-lifecycle failure with active demand."},
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-19","severity":"high","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py","line":849,"summary":"Unready terminalization races a concurrent readiness transition","evidence":"The terminalizer branches on the caller's possibly stale `op.first_ready_at` before `_release_unready_operation` locks only the lease (`.review/CHANGE.diff:97-118,121-135`). Another retry can commit `first_ready_at` and proceed to adapter dispatch between those actions; the stale failure path then marks the lease completed, allowing compute to continue without active demand ([CON-02])."}
]

#### GPUFLOW-1-SVCCOLDGPU-R-17 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:808`.
- **Evidence:** `_http_exception_already_terminalized` classifies every `description_service_error` HTTP exception as already cleaned, and the route consequently skips `_terminalize_accepted_operation` (`.review/CHANGE.diff:91-95,139-153`). The completion helper can raise that same typed 502 after a rollback when its persistence write fails, leaving the accepted lease active while the client receives an error.
- **Impact:** A database failure during completion turns a cleanup attempt into a silent demand leak.
- **Fix:** Track whether terminalization committed successfully rather than using the response code as a sentinel; retry/fallback terminalization while preserving the original error.

#### GPUFLOW-1-SVCCOLDGPU-R-18 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:800`.
- **Evidence:** The new helper preserves demand solely from `detail.code`, with no status, origin, or lifecycle-phase check (`.review/CHANGE.diff:83-89,139-153`). Any post-accept dependency that emits one of the lifecycle strings is re-raised without terminalizing the lease, even if it is not the readiness gate's intentional 503.
- **Impact:** A non-lifecycle failure can leave GPU demand active until lease expiry and mislead retry/lifecycle consumers.
- **Fix:** Mark lifecycle exceptions at the readiness boundary (or require the expected 503 shape and operation identity) and clean up all other post-accept failures.

#### GPUFLOW-1-SVCCOLDGPU-R-19 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:849`.
- **Evidence:** The new unready branch tests `op.first_ready_at` before acquiring a lock, while `_release_unready_operation` locks only `DescribeDemandLease` and never refreshes the operation row (`.review/CHANGE.diff:97-118,121-135`). A concurrent retry can record readiness and begin compute after the stale test but before the lease is marked completed, so the failing request removes the only active demand lease from work that is still running ([CON-02]).
- **Impact:** Concurrent retries can execute GPU work after demand has been terminalized, breaking lifecycle admission accounting.
- **Fix:** Re-read/lock the operation and lease together and decide readiness under that lock before completing the lease.

Verdict: fail

## Re-review r8 (3aa601740..35d7a3b85)

VERIFIED: {"GPUFLOW-1-SVCCOLDGPU-R-10":"fixed","GPUFLOW-1-SVCCOLDGPU-R-17":"fixed","GPUFLOW-1-SVCCOLDGPU-R-18":"fixed","GPUFLOW-1-SVCCOLDGPU-R-19":"not_fixed","GPUFLOW-1-SVCCOLDGPU-R-20":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCCOLDGPU-R-10 | fixed | The route now carries the preflight cache row directly to the cached response and installs a miss wrapper that suppresses only the service's first lookup while delegating duplicate-insert recovery (`.review/CHANGE.diff:50-72,214-247`). Every post-accept exception class either cleans up or completes the operation (`.review/CHANGE.diff:265-357`). |
| GPUFLOW-1-SVCCOLDGPU-R-17 | fixed | The HTTP-code sentinel is removed; a completion-raised `HTTPException` now invokes `_cleanup_accepted()` before being re-raised, and the outer HTTP path also cleans non-lifecycle exceptions (`.review/CHANGE.diff:113-130,265-296`). |
| GPUFLOW-1-SVCCOLDGPU-R-18 | fixed | Lease retention is now tied to the private `_LifecycleHoldHTTPException` emitted only by `_ensure_gpu_ready` with status 503; downstream plain `HTTPException` values take cleanup (`.review/CHANGE.diff:21-42,89-110,116-130,285-296`). |
| GPUFLOW-1-SVCCOLDGPU-R-19 | not_fixed | The new cleanup locks the operation and lease and rereads `first_ready_at` (`.review/CHANGE.diff:132-175`), but if it obtains the operation lock first, a concurrent retry's `observe_ready()` sees the now-completed lease as a no-op; `_ensure_gpu_ready()` ignores that result, sets `observed_ready_here`, and dispatches (`.review/CHANGE.diff:219-231`). The added regression mutates and commits `first_ready_at` in the same cleanup session rather than interleaving a concurrent transaction (`.review/CHANGE.diff:543-585`), so it misses the reverse ordering ([CON-02]). |
| GPUFLOW-1-SVCCOLDGPU-R-20 | fixed | The success definition again composes the base `image-description-response` schema with a strict multipart overlay, keeps `operation_id` a non-null optional string, and omits it from the overlay's required list (`.review/CHANGE.diff:664-678,680-895`). The producer tests now accept absence and reject null (`.review/CHANGE.diff:629-641`); the focused schema checks pass. |

### FINDINGS

FINDINGS: [
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-21","severity":"high","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py","line":1137,"summary":"Post-accept typed-code HTTP errors bypass the required envelope","evidence":"The outer handler cleans a plain HTTPException and then re-raises it unchanged (`.review/CHANGE.diff:285-296`). The new regression deliberately raises a plain 503 whose detail code is `description_service_unavailable` and asserts the two-field raw body (`.review/CHANGE.diff:510-540`), although that code belongs to the multipart typed-error branch requiring operation_id, startup_id, and timing (`.review/CHANGE.diff:611-626`). A quota/dependency failure can therefore publish a schema-invalid response that looks like a lifecycle error."},
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-22","severity":"medium","file_path":"apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py","line":223,"summary":"Multipart model rejects the wire form with omitted operation_id","evidence":"The fix makes the serializer remove `operation_id` when it is None (`.review/CHANGE.diff:363-402`) and the shared success schema accepts that key as absent (`.review/CHANGE.diff:680-895`), but `MultipartDescribeResponse.operation_id` is redeclared with `Field(...)` and no default (`.review/CHANGE.diff:379-387`). Pydantic therefore still marks the field required, so `MultipartDescribeResponse.model_validate()` cannot round-trip the valid CPU/hosted no-session payload produced by this serializer ([API-09])."},
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-23","severity":"low","file_path":"packages/shared-contracts/schemas/scene-describe-multipart.schema.json","line":1,"summary":"Fix delta repeats edits to producer paths outside this lane's ownership","evidence":"The delta changes six files, including the response-model producer, its tests, and the shared contract schema (`.review/DIFFSTAT.txt:1-7`; `.review/CHANGE.diff:360-402,586-677`). The lane row identifies the schema and response models as read-only dependencies, while only the route and designated route/fixture test paths are owned by svc-cold-gpu."}
]

#### GPUFLOW-1-SVCCOLDGPU-R-21 — high

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:1137`.
- **Evidence:** The new outer handler performs cleanup for a plain `HTTPException` but re-raises its original detail unchanged (`.review/CHANGE.diff:285-296`). The added downstream regression raises `description_service_unavailable` with only `code` and `message`, and asserts that raw body (`.review/CHANGE.diff:510-540`). Because that code is one of the multipart operation-error codes whose detail requires `operation_id`, `startup_id`, and `timing` (`.review/CHANGE.diff:611-626`), a post-accept quota/dependency error can be schema-invalid while presenting as a lifecycle response.
- **Impact:** Typed-error consumers can receive an envelope they cannot validate or safely classify, violating the A1/B1 response contract.
- **Fix:** Normalize post-accept HTTP exceptions using the operation-error builder, or reject/rename dependency codes before re-raising; only lifecycle exceptions created by the readiness gate should pass through as lifecycle responses.

#### GPUFLOW-1-SVCCOLDGPU-R-22 — medium

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py:223`.
- **Evidence:** The serializer now intentionally removes `operation_id` when it is None (`.review/CHANGE.diff:391-402`), and the success schema permits the key to be absent (`.review/CHANGE.diff:680-895`). However, the subclass redeclares `operation_id` with `Field(...)` and no `default=None` (`.review/CHANGE.diff:379-387`), leaving it required to Pydantic input validation. A valid CPU/hosted no-session wire payload therefore cannot be parsed back into `MultipartDescribeResponse`.
- **Impact:** Internal response round-trips and any strict consumer reusing the server model reject the exact absent-operation form that the fix publishes.
- **Fix:** Give the subclass field an explicit `default=None` while retaining its non-null constraint when present, and add a model-validation test with the operation key omitted.

#### GPUFLOW-1-SVCCOLDGPU-R-23 — low

- **File:** `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:1`.
- **Evidence:** This fix delta changes the shared schema, response model, and their producer tests in addition to the route-owned files (`.review/DIFFSTAT.txt:1-7`; `.review/CHANGE.diff:360-402,586-677`). The lane plan marks contracts and response-models as read-only dependencies of svc-cold-gpu, so the commit still carries producer-path ownership drift.
- **Impact:** Merging the lane requires unrelated producer changes and can create cross-lane conflicts or bypass the intended artifact handoff.
- **Fix:** Land the schema/model/test changes in their owning producer lanes and consume the committed artifacts here.

Verdict: fail

## Re-review r9 (35d7a3b85..670740157)

VERIFIED: {"GPUFLOW-1-SVCCOLDGPU-R-21":"fixed","GPUFLOW-1-SVCCOLDGPU-R-22":"fixed","GPUFLOW-1-SVCCOLDGPU-R-04":"not_fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCCOLDGPU-R-21 | fixed | The new post-accept HTTPException path still exempts only `_LifecycleHoldHTTPException`, then rebuilds recognized typed-error codes with the accepted operation's operation_id, startup_id, and measured timing (`.review/CHANGE.diff:56-95,109-115`). The downstream regression now validates the rebuilt body against the multipart schema and checks all required metadata (`.review/CHANGE.diff:215-239`). |
| GPUFLOW-1-SVCCOLDGPU-R-22 | fixed | The redeclared multipart `operation_id` now has `default=None` while retaining its non-null constraints when supplied, and the new test round-trips a payload with the key omitted (`.review/CHANGE.diff:130-148,259-269`). |
| GPUFLOW-1-SVCCOLDGPU-R-04 | not_fixed | The delta has no behavior hunk for `DescriptionAdapterUnavailableError`; the route changes only the success constructor and generic `HTTPException` handling (`.review/CHANGE.diff:101-116`). The added unavailable-adapter test is coverage only (`.review/CHANGE.diff:197-213`), so it cannot establish a newly corrected GPU 503 path. |

### FINDINGS

FINDINGS: [
  {"id":"GPUFLOW-1-SVCCOLDGPU-R-24","severity":"low","file_path":"apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py","line":223,"summary":"Fix delta still edits producer paths outside the svc-cold-gpu lane","evidence":"The delta modifies the response-model producer and its dedicated producer test in addition to the route tests (`.review/CHANGE.diff:118-152,243-282`; `.review/DIFFSTAT.txt:1-5`). The lane row assigns response-models and those producer tests as read-only dependencies, while svc-cold-gpu owns the route plus its fixture/shared-schema test."}
]

#### GPUFLOW-1-SVCCOLDGPU-R-24 — low

- **File:** `apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py:223`.
- **Evidence:** This fix delta edits `responses.py` and `test_gpuflow_response_models.py` alongside the route/test changes (`.review/CHANGE.diff:118-152,243-282`; `.review/DIFFSTAT.txt:1-5`). The lane plan marks response-models and producer tests as read-only dependencies of svc-cold-gpu; its owned paths are the route and designated fixture/shared-schema test.
- **Impact:** The fix cannot be merged as a lane-local change without taking producer-owned edits, preserving cross-lane conflict and ownership drift.
- **Fix:** Move the response-model and producer-test edits to their owning lane and consume the committed artifact here.

Verdict: pass_with_findings
