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

## Re-review r2 (0adafea11..872dcb23b)

VERIFIED: {"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-03":"fixed","GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-04":"partially_fixed","GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-05":"partially_fixed","GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-06":"fixed","GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-07":"not_fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-03 | fixed | `class-abstract-recognition-proxy-controller.php:646-669` adds `operation_id`, `startup_id`, and all five timing fields to the locally generated describe unavailable envelope; `ProxyRequestTest.php:1715-1749` checks the complete key set and pre-accept null IDs. |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-04 | partially_fixed | `class-abstract-recognition-proxy-controller.php:567-611` now checks status, nested code/message, ID presence/types, timing array presence, ETA numeric/nonnegative shape, and an integer Retry-After. It still accepts an empty/wrong-shaped timing object, does not enforce ID bounds or Retry-After [1,120], and rejects the contract-permitted null ETA; `ProxyRequestTest.php:1598-1637` does not cover those cases. |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-05 | partially_fixed | `class-settings-controller.php:866-902` stops treating every 2xx as connected and requires `ready:true` for a 200 health response; however `:810-839` still POSTs `{"action":"start"}` for 404 or typed unavailable health results, and `SettingsControllerTest.php:1233-1266` asserts the unavailable path makes that lifecycle call. |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-06 | fixed | `class-describe-media-service.php:308-319` reads only `get_body_params()` and returns the string without trimming; `DescribeMediaServiceTest.php:1423-1483` covers query exclusion, byte-for-byte body forwarding, and non-string omission. |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-07 | not_fixed | The fix delta still changes the four PHPUnit paths outside the four declared production/fixture paths: `DescribeMediaServiceTest.php`, `ProxyRequestTest.php`, `RetentionControllerTest.php`, and `SettingsControllerTest.php`. |

### FINDINGS

#### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-08 — high

File: `apps/prototype-wp-alt-context/src/api/class-settings-controller.php:870-871`; downstream `apps/prototype-wp-alt-context/js/admin/api/settingsApi.ts:122-141` and `js/admin/pages/settings/testConnectionBanner.ts:38-43`

Evidence: The fix introduces the new wire outcome `starting` via `PROBE_OUTCOME_STARTING` and returns it for HTTP 202 or typed starting responses, but the SPA's `TestConnectionOutcome` object and `KNOWN_TEST_CONNECTION_OUTCOMES` contain no `starting` member. `renderBanner()` therefore routes the valid response to `unknownOutcomeBanner()` instead of a starting state. This is a published enum change with a strict consumer and violates [API-09].

#### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-09 — medium

File: `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php:308-319`; contract `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:98-109`

Evidence: The replacement resolver returns every string present in the body, but removes the previous empty-string and 128-character upper-bound checks. The request contract requires a nonempty opaque `operation_id` of at most 128 characters, so empty or overlong body fields are now forwarded as contract-invalid retry tokens.

#### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-10 — medium

File: `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:646-665`; regression `apps/prototype-wp-alt-context/tests/Unit/ProxyRequestTest.php:1715-1745`

Evidence: A locally generated open-breaker error has no accepted operation and no measured upstream work, yet `open_circuit_local_timing()` reports `queue_ms`, `ramp_up_ms`, `processing_ms`, and `server_elapsed_ms` as zero. The timing contract says unknown/untimed values are null and zeroes must not be invented; the new test codifies the fabricated zeroes instead of catching them.

Verdict: fail

## Re-review r3 (872dcb23b..cfb38fc79)

VERIFIED: {"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-04":"partially_fixed","GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-09":"fixed","GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-10":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-04 | partially_fixed | `.review/CHANGE.diff:4-87` now validates the 503 status, nested starting code/message, required ID fields, exact timing keys/value shape, ETA presence/range, and Retry-After range. However `is_nullable_opaque_id()` still admits a null operation_id, and the validator does not enforce the envelope's closed key set; schema-invalid warming can still be exempted. |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-09 | fixed | `.review/CHANGE.diff:106-127` keeps body-only/verbatim forwarding and drops empty or overlong strings; `.review/CHANGE.diff:132-194` adds empty, 129-character, and 128-character coverage. |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-10 | fixed | `.review/CHANGE.diff:90-104` changes every locally fabricated queue/ramp-up/processing/server-elapsed zero to null, and `.review/CHANGE.diff:290-305` updates the regression assertions accordingly. |

### FINDINGS

FINDINGS: [{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-11","severity":"high","file_path":"apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php","line":586,"summary":"The warming exemption accepts a null operation_id even though typed errors require a service-minted ID","evidence":"The fix calls is_nullable_opaque_id() for operation_id, and that helper returns true for null (`.review/CHANGE.diff:8-17,39-51`; source :586-615). scene-describe-multipart.schema.json requires detail.operation_id to be a non-empty string (schema :39-47), so a 503 starting body with operation_id:null is contract-invalid but still skips breaker accounting."},{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-12","severity":"high","file_path":"apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php","line":572,"summary":"The warming validator does not reject additional top-level or detail properties","evidence":"The new checks inspect selected fields but never compare decoded/detail keys against the closed schema (`.review/CHANGE.diff:4-37,54-87`; source :572-607). The typed envelope sets additionalProperties:false at scene-describe-multipart.schema.json :23-70, so a body with valid required fields plus an extra property is returned as warming and bypasses breaker accounting despite failing the published boundary schema [API-09]."},{"id":"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-13","severity":"high","file_path":"apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php","line":649,"summary":"Timing and ETA validation admits positive infinity from JSON-decoded numbers","evidence":"The fix accepts every nonnegative PHP int/float but never calls is_finite() (`.review/CHANGE.diff:54-87`; source :601-603 and :645-651). PHP json_decode converts a JSON number such as 1e400 to INF, which passes the comparison; the shared timing/ETA contract permits finite nonnegative JSON numbers only, so malformed warming can again bypass failure accounting."}]

#### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-11 — high

File: `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:586-615`; contract `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:39-47`.

Evidence: The fix routes both operation_id and startup_id through `is_nullable_opaque_id()`, whose first branch accepts null (`.review/CHANGE.diff:8-17,39-51`). The typed error schema permits nullable startup_id but requires operation_id to be a non-empty string. Because this helper is used before breaker accounting, a starting response with `operation_id:null` is treated as validated warming rather than as a malformed 503.

Impact: A schema-invalid response can suppress failure accounting and remain outside the describe breaker, while downstream schema validation rejects the body and no service-minted retry identity exists.

Fix: Use a non-null opaque-ID validator for operation_id and retain nullable validation only for startup_id; add a null-operation regression that proves the response counts as a real failure.

#### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-12 — high

File: `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:572-607`; contract `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:23-70`.

Evidence: The fix checks selected required members but never asserts that the decoded response has only `detail` or that `detail` has only the typed-error members (`.review/CHANGE.diff:4-37,54-87`). The shared schema marks both objects `additionalProperties:false`. A valid-looking starting envelope with an extra key therefore returns through the warming exemption and bypasses failure accounting even though it is not a valid typed response [API-09].

Impact: An upstream contract drift or malformed payload can be silently classified as warming, so the circuit remains closed while strict consumers reject the same response.

Fix: Enforce the exact top-level and starting-detail key sets before exempting the response, with an extra-property regression.

#### GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-13 — high

File: `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:601-603,645-651`; timing contract `packages/shared-contracts/schemas/image-description-response.schema.json:339-385`.

Evidence: Numeric validation accepts any nonnegative PHP int/float and does not reject non-finite values (`.review/CHANGE.diff:54-87`). PHP `json_decode()` represents a JSON number such as `1e400` as `INF`; `INF < 0` is false, so it passes both timing and ETA validation. The shared wire contract allows only nonnegative JSON numbers or null, not an infinite internal float.

Impact: A malformed upstream 503 can be accepted as validated warming and skip breaker accounting with unusable timing/ETA metadata.

Fix: Require `is_finite()` for every non-null timing and ETA number; add an oversized-exponent regression.

Verdict: fail

## Re-review r4 (cfb38fc79..983471fc1)

VERIFIED: {"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-04":"partially_fixed","GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-12":"fixed","GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-13":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-04 | partially_fixed | The fix now checks the 503 starting envelope's closed key sets, message, timing, ETA, and Retry-After (`.review/CHANGE.diff:61-89,90-125,130-149`), but the existing `operation_id` path still calls the nullable helper, whose null branch remains accepted (`class-abstract-recognition-proxy-controller.php:635-636,662-665`). A schema-invalid starting body can therefore still bypass breaker accounting. |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-12 | fixed | `TYPED_ERROR_TOP_LEVEL_KEYS` and `TYPED_ERROR_DETAIL_KEYS` plus `has_closed_key_set()` reject unknown envelope/detail properties before exemption (`.review/CHANGE.diff:16-56,61-79,116-125`); the provider adds both extra-key regressions (`.review/CHANGE.diff:179-200`). |
| GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-13 | fixed | ETA and every non-null timing value now pass through `is_finite_number()`, which calls `is_finite()` (`.review/CHANGE.diff:81-89,103-125`); oversized-exponent ETA and timing regressions are included (`.review/CHANGE.diff:201-210`). |

### FINDINGS

FINDINGS: []

Verdict: fail
