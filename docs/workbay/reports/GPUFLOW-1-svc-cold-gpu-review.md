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
