FINDINGS: [{"id":"GPUFLOW-1-CONTRACTS-R-01","severity":"medium","file_path":"packages/shared-contracts/schemas/scene-describe-multipart.schema.json","line":13,"summary":"The new multipart success branch does not require timing.","evidence":"Its required list contains only operation_id and startup_id; the document test also validates the accepted operation shape after removing timing."},{"id":"GPUFLOW-1-CONTRACTS-R-02","severity":"medium","file_path":"packages/shared-contracts/schemas/scene-describe-multipart.schema.json","line":62,"summary":"Typed error details do not require timing.","evidence":"The detail required list omits timing even though the API contract says typed errors carry it, so an error body without timing validates."},{"id":"GPUFLOW-1-CONTRACTS-R-03","severity":"medium","file_path":"docs/workbay/contracts/gpu-lifecycle.md","line":374,"summary":"Lease demand has no exact projection into the existing load snapshot contract.","evidence":"The new text requires lease aggregation but does not define whether leases contribute to queue_depth, in_flight, or a new reader-visible field; existing load readers only consume the former fields and batch_in_progress."},{"id":"GPUFLOW-1-CONTRACTS-R-04","severity":"medium","file_path":"docs/workbay/contracts/gpu-lifecycle.md","line":378,"summary":"The stale-publication guarantee lacks a linearizable revision protocol.","evidence":"The contract requires older snapshots not overwrite newer demand but defines no revision/compare-and-write field or fence scope covering the database read and file write; the existing writer lock only serializes replacement."},{"id":"GPUFLOW-1-CONTRACTS-R-05","severity":"medium","file_path":"docs/workbay/contracts/image-description-api.md","line":285,"summary":"Starting responses do not normatively require a Retry-After header.","evidence":"The section says Retry-After is an HTTP header and gives a ceiling, but neither the schema nor the prose requires it on description_service_starting; the plan requires the 503 start response to include it."},{"id":"GPUFLOW-1-CONTRACTS-R-06","severity":"medium","file_path":"packages/shared-contracts/schemas/image-description-response.schema.json","line":339,"summary":"The timing schema does not enforce warm/cache correlation invariants.","evidence":"It permits cached=true with a non-null startup_id and nonzero ramp_up_ms or processing_ms; the document test checks only negative timing values, while the API contract requires zero readiness, no startup association, and zero cache processing."},{"id":"GPUFLOW-1-CONTRACTS-R-07","severity":"medium","file_path":"packages/shared-contracts/schemas/scene-describe-run.schema.json","line":241,"summary":"Run items may omit processing_ms instead of carrying explicit null for untimed work.","evidence":"The item required list contains only media_id and status, and the minimal failed item validates without processing_ms; the API contract says untimed items remain null."}]
Verdict: pass_with_findings

# GPUFLOW-1 contracts review

| base | tip | files |
| --- | --- | --- |
| `eff8e6025` | `112f262cd` | `apps/prototype-description-service/scene/tests/test_shared_schema_documents.py`; `docs/workbay/contracts/gpu-lifecycle.md`; `docs/workbay/contracts/image-description-api.md`; `packages/shared-contracts/schemas/image-description-response.schema.json`; `packages/shared-contracts/schemas/scene-describe-multipart.schema.json`; `packages/shared-contracts/schemas/scene-describe-run.schema.json` |

## FINDINGS

### GPUFLOW-1-CONTRACTS-R-01 — medium

File: `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:13-16` (test coverage at `apps/prototype-description-service/scene/tests/test_shared_schema_documents.py:82`).

Evidence: The success branch requires only `operation_id` and `startup_id`; `timing` is optional through the referenced base schema. The test explicitly removes `timing` and validates the result against the multipart schema.

Impact: A newly accepted multipart operation can pass the canonical schema without the measured timing object, weakening the B1 requirement that describe responses carry phase timing and leaving downstream consumers without a stable field.

Fix: Require `timing` in the accepted multipart branch. Preserve any legacy omission rule through an explicitly distinguished legacy/base response path, and add a negative test for an accepted response missing timing.

### GPUFLOW-1-CONTRACTS-R-02 — medium

File: `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:58-67`.

Evidence: `detail.timing` is declared but omitted from the detail `required` list. The document test only validates errors containing timing, so a typed error without timing is accepted.

Impact: Starting, unavailable, adapter-failure, mismatch, and expired responses can omit the timing object despite `image-description-api.md:285` defining typed errors with it. Strict response models and PHP/SPA timing consumers cannot rely on the declared error shape.

Fix: Require `timing` in typed details, with its fields nullable for unknown/untimed values, and add omission-negative coverage for every error class.

### GPUFLOW-1-CONTRACTS-R-03 — medium

File: `docs/workbay/contracts/gpu-lifecycle.md:374-377`.

Evidence: The delta says every publisher aggregates unexpired leases with async GPU work but does not specify the resulting load-snapshot projection. The existing contract exposes `queue_depth`, `in_flight`, and `batch_in_progress`, while current readers consume those fields only; no lease-specific field or counting rule is defined.

Impact: Implementations can persist leases yet publish a snapshot with zero `has_work`, or count demand inconsistently across periodic, async, and sync publishers. A stopped GPU may therefore remain unstarted or be stopped while eligible demand exists.

Fix: Define the exact JSON projection and arithmetic (including tenant scope and eligibility), or add a named lease-demand field and update every reader contract. Add cross-tenant and publisher-path tests that assert the projected snapshot and `has_work` result.

### GPUFLOW-1-CONTRACTS-R-04 — medium

File: `docs/workbay/contracts/gpu-lifecycle.md:378-379`.

Evidence: The contract requires serialization so an older snapshot cannot overwrite newer demand, but it specifies no monotonic revision, compare-and-write rule, or fence held across the database snapshot read and file publication. The existing file writer lock serializes replacement only; a publisher can read old DB state, pause, then write it after a newer publisher.

Impact: A stale snapshot can carry a fresh publication timestamp while erasing demand, causing silent lifecycle under-actuation and violating the A1 retained-demand guarantee across processes.

Fix: Specify an atomically assigned snapshot revision and write-if-newer protocol, or hold the existing cross-process service fence across the DB read and publication. Test the interleaving where an older read completes after a newer publication.

### GPUFLOW-1-CONTRACTS-R-05 — medium

File: `docs/workbay/contracts/image-description-api.md:285-290`.

Evidence: The contract says `Retry-After` is an HTTP header and that its maximum is at most 120 seconds, but it never requires the header on `description_service_starting` responses or defines its exact delta-seconds value/range. The schema cannot validate headers, and the document tests do not cover this transport obligation.

Impact: A valid-looking starting response may omit the retry schedule required by the SPA and by the lease-lifetime inequality, forcing an unbounded or divergent client retry gap while warming.

Fix: Make `Retry-After` mandatory for starting 503 responses, define its bounded delta-seconds encoding (at or below 120 seconds), state its absence on non-starting typed errors, and add an HTTP-level fixture/test.

### GPUFLOW-1-CONTRACTS-R-06 — medium

File: `packages/shared-contracts/schemas/image-description-response.schema.json:339-385`.

Evidence: The timing properties independently enforce only nonnegative numbers or null. The schema therefore accepts `cached: true` with a non-null `startup_id`, nonzero `ramp_up_ms`, or nonzero `processing_ms`; the document test checks negative values but not these cross-field constraints. The API contract at `docs/workbay/contracts/image-description-api.md:300-303` requires zero readiness, no startup association, and zero cache processing.

Impact: Builders can emit semantically contradictory cache/warm timing and downstream clients can display a startup or processing phase that did not occur.

Fix: Encode the cache/warm conditional invariants in the accepted response schema where practical, and add valid/invalid fixtures for cached and warm non-GPU responses. Keep unknown values null rather than deriving zeroes for paths that were not measured.

### GPUFLOW-1-CONTRACTS-R-07 — medium

File: `packages/shared-contracts/schemas/scene-describe-run.schema.json:233-245`.

Evidence: The item definition requires only `media_id` and `status`; `processing_ms` is optional. A failed item with no `processing_ms` validates, although the API contract at `docs/workbay/contracts/image-description-api.md:316-319` says failed, skipped, and untimed items preserve timing and leave untimed values null.

Impact: Consumers cannot distinguish an explicitly untimed item from an omitted field, and item timing coverage can be undercounted or handled inconsistently after database round trips.

Fix: Require `processing_ms` as a nullable property for the new item response shape, or provide an explicit legacy item shape/version with tests so omission cannot silently represent a new untimed result.

## Verification

- `/home/gate/grok-sandbox/review-gpuflow-1-contracts-72efbeb2/.venv/bin/python -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` — 1 passed.
- `/home/gate/grok-sandbox/review-gpuflow-1-contracts-72efbeb2/.venv/bin/python -m pytest apps/prototype-description-service/scene/tests/test_shared_schema_documents.py -q -p no:cacheprovider` — 17 passed.
- All six paths in the supplied delta are within the contracts lane owned-path list.
