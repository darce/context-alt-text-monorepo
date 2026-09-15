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
