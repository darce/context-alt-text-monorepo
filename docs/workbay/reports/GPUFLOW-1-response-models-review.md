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
