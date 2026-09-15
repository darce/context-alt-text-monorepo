FINDINGS: [{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-01","severity":"high","file_path":"apps/prototype-wp-alt-context/js/admin/api/describeApi.ts","line":453,"summary":"Single-image describe rejects the operation metadata that this delta forwards","evidence":"The PHP service forwards the multipart success body, whose fixture includes operation_id, startup_id, and timing, but validateVisualFactsResponse rejects any top-level key outside its legacy allow-list."},{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-02","severity":"high","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts","line":5,"summary":"Single-image Suggest cannot retain or retry the typed operation envelope","evidence":"The mutation input carries only mediaId/writeAlt/force and retries call mutate(mediaId); the error helpers read top-level code/message while the PHP typed envelope nests them under detail and carries detail.operation_id."},{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-03","severity":"high","file_path":"apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php","line":564,"summary":"The locally generated open-breaker response is not a valid typed operation error","evidence":"open_circuit_response emits only detail.code and detail.message, while scene-describe-multipart.schema.json requires detail.operation_id, startup_id, and timing as well."},{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-04","severity":"high","file_path":"apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php","line":556,"summary":"Warming exemption validates only status and code, so malformed warming fails open","evidence":"is_validated_warming_response receives only the status and an allow-listed code; it never validates the required message, IDs, timing, ETA shape, or Retry-After before suppressing failure accounting."},{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-05","severity":"high","file_path":"apps/prototype-wp-alt-context/src/api/class-settings-controller.php","line":522,"summary":"The settings health probe mutates GPU lifecycle state and can report a 202 intent as connected","evidence":"test_connection calls maybe_start_description_service after health; that method POSTs action=start for 404 or typed unavailable, and build_probe_payload classifies every 2xx lifecycle response as CONNECTED."},{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-06","severity":"medium","file_path":"apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php","line":309,"summary":"The retry token is accepted from query/default request parameters and is trimmed","evidence":"WP_REST_Request::get_param searches non-body sources, although the shared contract permits only an opaque multipart form field; trim changes the value before forwarding it."},{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-07","severity":"low","file_path":"apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServiceTest.php","line":1,"summary":"The delta changes four PHPUnit files outside the declared lane-owned path set","evidence":"The complete diff has eight paths; the declared source/fixture ownership lists four, while DescribeMediaServiceTest.php, ProxyRequestTest.php, RetentionControllerTest.php, and SettingsControllerTest.php are additional changed paths."}]
Verdict: fail

# GPUFLOW-1 php-breaker-passthrough review

| scope | value |
| --- | --- |
| base | `8f87fe48f25a6889e7d8f257291bd7f5ab4e33ef` |
| tip | `0adafea11fe057db54bd02a03be98e653f099189` |
| files | 8 changed paths in the inlined delta: three PHP production files, one JSON fixture, and four PHPUnit files; the four declared production/fixture paths are listed in R-07. |

## FINDINGS

### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-01 — high

File: `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php:198-210`; downstream `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts:116-143,445-457,911-932`

Evidence: The delta deliberately forwards the upstream success body. Its `success_warm` fixture contains top-level `operation_id`, nullable `startup_id`, and `timing`. The single-image SPA response type and `VISUAL_FACTS_RESPONSE_KEYS` do not declare those fields, and `validateVisualFactsResponse()` rejects the first unexpected top-level key before `describeMedia()` returns.

Impact: A normal GPUFLOW-1 single Suggest success is raised as `MalformedVisualFactsResponseError` instead of reaching the Suggest UI. B2 timing cannot be displayed, and the PHP passthrough contract is unusable for the primary single-image consumer.

Fix: Extend the single-image wire type, allow-list, and runtime validator for the operation metadata and timing shape, with tests covering present and explicitly nullable values. Keep absent-vs-null semantics aligned with the shared multipart contract.

### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-02 — high

File: `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php:198-210`; downstream `apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts:5-24`, `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts:1249-1284`, `apps/prototype-wp-alt-context/js/admin/api/wpErrorMessage.ts:27-47`

Evidence: The PHP change adds the opaque retry field and emits typed errors as `detail.code`, `detail.message`, and `detail.operation_id`. The SPA mutation input has no operation ID, its retry path calls `mutate(mediaId)`, `resolveDescribeErrorCode()` reads only top-level `payload.code`, and `resolveWpErrorMessage()` does not read `detail.message`.

Impact: A pending Suggest cannot retain the service-minted operation ID, so “Try again” omits the token and cannot renew the same operation. The SPA also cannot branch on `description_service_starting` or show its typed message/ETA, causing new operations or generic fallback errors instead of the documented retry behavior.

Fix: Store the per-Suggest operation ID from success and typed errors, pass it as the multipart retry field on the same request, and parse `detail.code`, `detail.message`, `detail.operation_id`, and timing through the shared typed-error helpers. Add a starting-then-retry regression.

### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-03 — high

File: `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:564-574`; contract `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:22-94`

Evidence: When the describe breaker is open, `open_circuit_response()` returns HTTP 503 with only `detail.code` and `detail.message`. The typed operation-error schema requires `code`, `message`, `operation_id`, `startup_id`, and `timing`, and the contract requires PHP to preserve the typed envelope rather than emit a generic/incomplete replacement.

Impact: Once the breaker opens, the response is contract-invalid and cannot be consumed by schema-validating downstream clients. It also provides no timing or operation correlation for the unavailable state. The added test asserts only the code and absence of `Retry-After`, so it does not catch this boundary break.

Fix: Generate the contract-approved pre-accept typed envelope with every required metadata key and the contract-approved nullability for IDs/timing; never mint an ID locally. Validate the generated response against the shared schema and test the open-breaker path independently.

### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-04 — high

File: `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:214-224,530-558`; regression `apps/prototype-wp-alt-context/tests/Unit/ProxyRequestTest.php:1563-1582`

Evidence: `typed_operation_error_code()` only extracts an allow-listed code, and `is_validated_warming_response()` treats any HTTP 503 carrying `description_service_starting` as valid. It does not validate the required nested message, operation/startup/timing fields, ETA constraints, or the required `Retry-After`. The test calls malformed warming a body without any typed code, so it misses an incomplete body that still has the code.

Impact: A malformed 503 can be classified as warming, skip failure accounting and retry, and keep the describe breaker closed indefinitely. This is a fail-open response classification and can silently strand requests behind an invalid envelope.

Fix: Validate the complete 503 starting envelope and header before exempting it from accounting; any invalid or incomplete warming response must follow the real 5xx failure path. Add code-only, missing-metadata, and invalid-header regressions.

### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-05 — high

File: `apps/prototype-wp-alt-context/src/api/class-settings-controller.php:519-522,802-826,850-853`; backend contract `docs/workbay/contracts/gpu-lifecycle.md:10-12,54-60,327-336`

Evidence: `test_connection()` invokes `maybe_start_description_service()` after the authenticated health request. The new helper POSTs `{"action":"start"}` when health is 404 or when the service reports `description_service_unavailable`, including STOP/stopping states. The lifecycle endpoint returns 202, and `classify_http_status()` maps every 2xx response to `ProbeOutcome::CONNECTED`, without a health re-probe.

Impact: A read-only “Check health” action can override an operator STOP/unavailable decision and start GPU lifecycle work. A successful intent acknowledgement is then presented as a healthy service connection, so the settings UI and pairing flow may claim readiness before the description service is ready. This violates the explicit-intent and fail-closed lifecycle boundary.

Fix: Remove lifecycle mutation from the health probe. Keep the probe outcome/status/code/ETA as observed, and route start through the explicit GPU-control action; if a separate recovery workflow is required, re-probe health after the intent and never label a 202 intent acknowledgement as service connectivity.

### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-06 — medium

File: `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php:304-323`; contract `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:5` and `docs/workbay/contracts/image-description-api.md:299-303,340-343`

Evidence: `resolve_operation_id()` starts with `$request->get_param('operation_id')`, which searches URL/query/default sources as well as body parameters, then applies `trim()` before adding the value to the multipart body. The shared contract permits this opaque token only as a multipart form field and explicitly forbids query transport.

Impact: A query/default parameter can be promoted into the durable retry identity, and whitespace-bearing opaque values are silently changed. That can produce operation mismatches, weaken request-digest binding, and make the PHP boundary differ from the service’s token semantics.

Fix: Read the token only from the endpoint’s permitted body/form source, reject or report disallowed transport rather than falling through, and forward the validated opaque value without mutation.

### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-07 — low

File: `apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServiceTest.php:1`, `ProxyRequestTest.php:1`, `RetentionControllerTest.php:1`, `SettingsControllerTest.php:1`

Evidence: Mechanical enumeration of `.review/CHANGE.diff` yields eight changed paths. The lane row’s declared owned list contains only the three production PHP files and the new JSON fixture; the four PHPUnit files above are outside that list.

Impact: The delta violates the lane-owned-path boundary and makes test ownership/merge conflict resolution ambiguous, even though the test additions are relevant to the implementation.

Fix: Move these tests to the lane that owns them or update the orchestration ownership before landing; enforce the changed-path allow-list in review automation.

## VERIFICATION

- Changed-path audit: 8 paths in the delta; 4 are in the declared production/fixture owned list and 4 are PHPUnit files outside it.
- Required lock verification passed with the lane interpreter: `.venv/bin/python -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` — `1 passed`.
- The lane-row PHPUnit command was not executable in this sandbox because neither `apps/prototype-wp-alt-context/vendor/bin/phpunit` nor repository `vendor/bin/phpunit` exists. The diff does add the requested Proxy/DescribeMedia/Settings tests and fixture, but no PHPUnit pass is claimed.
