# GPUFLOW-2 svc-unavailable-reason review

Verdict: fail

| Base | Tip | Files |
| --- | --- | --- |
| `284616c05` | `720af8ab8` | `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py`; `apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py`; `apps/prototype-description-service/scene/tests/fixtures/gpuflow2-unavailable.json`; `apps/prototype-description-service/scene/tests/test_describe_route.py` (outside declared owned list); `apps/prototype-description-service/scene/tests/test_shared_schema_multipart.py` (outside declared owned list) |

## FINDINGS

### GPUFLOW-2-SVCUNAVAILABLEREASON-R-01 — high

- File: `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:523-546,1133-1139,907-925`; adapter resolver `apps/prototype-description-service/scene/interface_adapters/http/deps.py:91-119`.
- Evidence: The new `_unavailable_from_gpu_gate()` treats an endpoint as configured whenever `settings.gpu_endpoint_url` is truthy; it never checks endpoint privacy or whether the selected GPU adapter is `UnavailableDescriptionAdapter`. `get_gpu_description_adapter()` returns that unavailable GPU-kind adapter for a non-private endpoint. Therefore an explicit GPU request with a stopped snapshot and `ACX_GPU_ENDPOINT_URL=http://8.8.8.8:8000` has `gpu_compute=True`, `blocked=False`, and enters the `description_service_starting` branch. The later `DescriptionAdapterUnavailableError` mapping to `endpoint_not_private` at `:1327-1343` is reached only after the service has waited/retried and invoked the unusable adapter.
- Impact: A known-invalid endpoint is advertised as starting and its demand can cause the lifecycle controller to start/wait for a GPU that cannot serve requests. The SPA receives a warmup promise instead of the actionable `endpoint_not_private` failure, so the fail-closed endpoint boundary is bypassed.
- Fix: Carry the effective adapter’s availability/endpoint-readiness decision into `_ensure_gpu_ready()` (or reject the unavailable GPU adapter before accepting lifecycle demand), returning `endpoint_not_private`/`endpoint_resolution_pending` before any starting response. Add a stopped-snapshot regression with a non-private or invalid-scheme endpoint.

### GPUFLOW-2-SVCUNAVAILABLEREASON-R-02 — high

- File: `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:405-415,1315-1320`; contract `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:125-150`.
- Evidence: `_plain_typed_error_missing_operation_fields()` triggers `_rebuild_post_accept_typed_error()` only when one of `operation_id`, `startup_id`, or `timing` is absent. A downstream/upstream `HTTPException` with a complete operation envelope but a `description_service_unavailable` detail lacking `reason` (or a `description_service_starting` detail lacking `startup_budget_seconds`) returns `False` from this predicate, and the outer handler re-raises the original detail unchanged. The schema requires `reason` for unavailable and `startup_budget_seconds` for starting. The new tests cover an upstream unavailable detail with missing operation fields plus `reason`, not the full-envelope case.
- Impact: A typed post-accept failure can cross the service boundary with a schema-invalid detail and no machine-readable unavailable reason (or no service-owned warmup budget). PHP/SPA consumers cannot safely classify or resume it, violating the release response contract.
- Fix: Normalize every recognized typed code after acceptance, not only details missing operation metadata; validate code-specific required fields and closed-key/value shape before preserving an upstream exception. Add regressions for full envelopes with missing, null, and invalid reason/budget fields, while preserving only contract-valid source metadata.

### GPUFLOW-2-SVCUNAVAILABLEREASON-R-03 — low

- File: `apps/prototype-description-service/scene/tests/test_describe_route.py:1073-1118,1145-1246`; `apps/prototype-description-service/scene/tests/test_shared_schema_multipart.py:1-16,103-128`.
- Evidence: The supplied delta changes both test files, while the declared `svc-unavailable-reason` owned list contains only `describe.py`, `responses.py`, and the new `scene/tests/fixtures/gpuflow2-unavailable.json`. The two test paths are not in that list.
- Impact: The delta crosses the lane boundary and can be merged with sibling-owned test changes, obscuring ownership and creating avoidable merge conflicts even though the assertions are relevant.
- Fix: Move these test edits to their owning lane or update the orchestration ownership before landing; enforce the changed-path allow-list mechanically.

## VERIFICATION

- The required lock verification passed with the lane interpreter: `.venv/bin/python -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` — `1 passed`.
- Focused fixture/schema coverage passed: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest apps/prototype-description-service/scene/tests/test_shared_schema_multipart.py -k 'fixture or typed_error_envelopes' -q -p no:cacheprovider` — `3 passed, 5 deselected`.
- Direct probes confirmed the full-envelope normalizer predicate is false for a typed unavailable detail without `reason`, and the readiness gate returns `(None, None)` for a configured non-private endpoint with a stopped snapshot.
- The complete lane-row route-suite invocation was attempted with the resolved lane interpreter. Collection/initial execution hit the documented DB-backed sandbox hang (the unconstrained attempt also hit OpenBLAS thread creation limits), so it was interrupted; no pass is claimed for that suite.
