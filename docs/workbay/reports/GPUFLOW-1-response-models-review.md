# GPUFLOW-1 response-models review

Verdict: fail

| Base | Tip | Files |
| --- | --- | --- |
| `112f262cd` | `cd721a2e0` | `apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py`; `apps/prototype-description-service/scene/tests/test_gpuflow_response_models.py` |

## FINDINGS

### GPUFLOW-1-RESPONSEMODELS-R-01 — high

- File: `apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py:179-181, 226-228`
- Evidence: `operation_id`, `startup_id`, and `timing` are added with `default=None`. Existing multipart and run builders omit them (`visual_facts_service.py:88-115`; `describe_run.py:133-148`), so normal Pydantic/FastAPI serialization emits `operation_id: null` and `timing: null`. The shared response schemas type `operation_id` as a non-null string and `timing` as an object (`image-description-response.schema.json:326-340`, `scene-describe-run.schema.json:103-117`); multipart success additionally requires `operation_id` and `startup_id` (`scene-describe-multipart.schema.json:8-16`). The added test only checks omission under `model_dump(exclude_unset=True)` and never validates the normal wire output against either schema.
- Impact: Existing `/scene/describe/multipart` and `/scene/describe/run` responses become non-schema-conformant as soon as this model delta is applied, while the multipart success path also lacks the required service correlation ID. Consumers cannot reliably parse or retry these responses, and the contract's fail-closed boundary is broken.
- Fix: Populate real service-minted correlation and timing values on accepted multipart responses, and serialize legacy/unknown fields by omission rather than explicit nulls. For run responses, omit unset optional properties (or use a separate legacy response model); add builder-level schema-validation tests for normal serialization. Never substitute fabricated IDs or timings.

## Verification

- `scene/tests/test_gpuflow_response_models.py -q -p no:cacheprovider`: 26 passed.
- `scene/tests/test_shared_schema_documents.py -q -p no:cacheprovider`: 17 passed.
- `scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider`: 1 passed.

## Re-review r4 (cd721a2e0..c6e5f7aa2)

| finding | verdict | evidence |
| --- | --- | --- |
| `RESPON-H-01` | `partially_fixed` | `responses.py:178-184` and `230-235` remove the nullable defaults and require `operation_id`, explicit nullable `startup_id`, and `timing`, preventing an invalid null model from serializing. The delta does not populate the existing builders, so normal accepted responses still cannot be constructed. |
| `RESPON-L-01` | `partially_fixed` | The same required-field change removes the default-null wire path, but the fix does not update builders or exercise their normal serialization, so the harvested contract failure is not fully closed. |

### FINDINGS

#### GPUFLOW-1-RESPONSEMODELS-R-02 — high

- File: `apps/prototype-description-service/scene/application/visual_facts_service.py:88-115, 438-457, 473-493`; `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py:134-147`
- Evidence: The fix makes `VisualFactsResponse.operation_id`, `startup_id`, and `timing` required at `responses.py:178-184`, and makes the corresponding `DescribeRunResponse` fields required at `responses.py:230-235`. The unchanged multipart/cache/row builders and `_run_response` still omit all three fields. They now raise Pydantic `ValidationError` before returning a response instead of emitting the previously invalid null envelope. The new tests construct models with hand-supplied metadata at `test_gpuflow_response_models.py:61-65, 93-99`; they do not invoke these builders.
- Impact: Normal multipart, cached/row, and describe-run status paths fail at response construction, producing an endpoint error rather than a valid contract response. This is a release-blocking regression, not a safe migration to strict response models.
- Fix: Thread persisted operation/startup/timing values through every response builder and validate actual multipart and run builder output against their shared schemas after round trips.

#### GPUFLOW-1-RESPONSEMODELS-R-03 — medium

- File: `apps/prototype-description-service/scene/tests/test_gpuflow_response_models.py:92-100`
- Evidence: `test_serialized_accepted_response_matches_shared_contract` immediately returns for `DescribeRunResponse`, so the newly added serialization proof covers only `VisualFactsResponse`. It therefore does not validate the run response against `scene-describe-run.schema.json`, despite the same required-field change at `responses.py:230-235`; the test also does not exercise the actual builders.
- Impact: A broken run wire shape or builder regression can pass the new lane test and reach the downstream router lane undetected.
- Fix: Add actual multipart and run builder fixtures, serialize them with the ordinary response path, and validate each against its designated shared schema.

Verdict: fail

## Re-review r5b (c6e5f7aa2..38cd11e65)

| finding | verdict | evidence |
| --- | --- | --- |
| `RESPON-H-01` | `partially_fixed` | `OmitAbsentOperationMetadata` now strips null operation metadata (`responses.py:141-160`) and both response models default the fields to `None` (`responses.py:205-207, 257-259`), so the unchanged builders no longer raise `ValidationError`. The delta still does not thread real operation/startup/timing values into those builders, and the multipart success contract still requires `operation_id` and `startup_id`. |
| `GPUFLOW-1-RESPONSEMODELS-R-02` | `partially_fixed` | The optional defaults and serializer remove the construction failure, but no production builder is changed in the delta; the existing VisualFacts and run builders therefore still serialize accepted responses without the operation metadata that this slice promises. |
| `GPUFLOW-1-RESPONSEMODELS-R-03` | `partially_fixed` | The parameterized populated-metadata test now covers `DescribeRunResponse` and validates both dump forms against the run schema (`test_gpuflow_response_models.py:121-134`), removing the early return. The “builder-shaped” tests still call `model(**payload)` directly (`test_gpuflow_response_models.py:101-118`) and never invoke an actual service or router builder. |

### FINDINGS

#### GPUFLOW-1-RESPONSEMODELS-R-04 — high

- File: `apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py:141-160, 205-207`
- Evidence: The fix makes `operation_id` and `startup_id` optional and removes them from the serialized payload when they are absent. `VisualFactsResponse` is the `/scene/describe/multipart` response model, but the success branch of `scene-describe-multipart.schema.json` requires both fields (`scene-describe-multipart.schema.json:8-16`). The unchanged builders can now pass response-model serialization and return a contract-invalid success body instead of failing loudly. This violates [API-09]: a published API boundary must not be weakened in a way that callers can observe as a different shape.
- Impact: Accepted multipart responses can lose the opaque correlation identifiers required for retry binding and startup correlation while still looking successful to FastAPI; consumers validating the outer shared contract reject the body or cannot safely retry it. The fix converts the prior construction error into a silent release-level contract break.
- Fix: Keep the operation response strict at the multipart boundary and populate real service-minted metadata in every accepted builder. If legacy base-model payloads must remain readable, use a context-specific wrapper/adapter rather than globally omitting required success fields.

#### GPUFLOW-1-RESPONSEMODELS-R-05 — medium

- File: `apps/prototype-description-service/scene/tests/test_gpuflow_response_models.py:17-23, 101-118`
- Evidence: `_SCHEMAS` maps `VisualFactsResponse` to `image-description-response.schema.json`, and the omission tests explicitly assert that all three operation keys are absent before validating only that weaker schema. They never validate `scene-describe-multipart.schema.json`, whose success branch requires `operation_id` and `startup_id`. The green test therefore cannot detect the R-04 regression; [TEST-15] requires a passing invariant test to be able to go red for the production failure it claims to guard.
- Impact: Lane verification can report contract compliance while the actual multipart endpoint emits a body rejected by the designated shared schema, leaving downstream consumers and retry behavior untested.
- Fix: Validate the actual multipart success envelope (including its `$ref` registry) and exercise the production multipart builder; reserve the base image schema test for legacy/non-operation payloads.

Verdict: fail
