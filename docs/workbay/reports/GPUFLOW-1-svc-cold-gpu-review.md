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
