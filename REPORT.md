# Lane E — PROV-01

## Result

gpu_qwen30b / gpu_qwen30b_ensemble pin a live-resolved GGUF hub revision. Opt-in `runtime-vlm` compose overlay selects `acx-backend-vlm`. GPU describe provenance names `served-id@pin`; llama.cpp still gets the unadorned served id.

Final HEAD: recorded by the integrator after transplant.

## Commits

- `feat(scene): PROV-01a pin gpu_qwen30b hub revision`
- `feat(scene): PROV-01b runtime-vlm provenance names pinned revision`

## PROV-01a

RED (verbatim short summary):

```
FAILED scene/tests/test_description_profiles.py::test_available_gpu_profiles_pin_a_non_none_hub_revision - AssertionError: gpu_qwen30b is available=True GPU but model_revision is None (unpinned hub pull; SEC-10)
```

Pin: `huggingface_hub.HfApi().model_info("unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF").sha` on 2026-08-25 (served Q4_K_M GGUF, not the unquantized transformers snapshot). Ensemble shares the same pin.

- `apps/prototype-description-service/scene/config/profiles.py:109` gpu_qwen30b `model_revision`
- `apps/prototype-description-service/scene/config/profiles.py:120` ensemble pin
- `apps/prototype-description-service/scene/tests/test_description_profiles.py:109` available-GPU pin test

TEST-15: set gpu_qwen30b `model_revision=None` → same RED line. Restore: production file matched pre-mutant.

GREEN: `36 passed` (`scene/tests/test_description_profiles.py`).

## PROV-01b

RED (verbatim short summaries):

```
FAILED scene/tests/test_description_profiles.py::test_resolve_gpu_qwen30b_provenance_names_pinned_revision - AssertionError: assert False
FAILED scene/tests/test_gpu_remote_adapter.py::test_gpu_remote_adapter_provenance_names_loaded_revision_not_payload_model - TypeError: GpuRemoteDescriptionAdapter.__init__() got an unexpected keyword argument 'model_revision'
FAILED recognition/tests/deploy/test_compose_image_variant_parity.py::test_compose_vlm_overlay_defaults_to_vlm_repo - AssertionError: docker-compose.vlm.yml overlay missing
```

- `apps/prototype-description-service/scene/interface_adapters/http/deps.py:97` passes `spec.model_revision`
- `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py:144` served id vs wire `model_id`
- `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py:183` payload uses served id
- `apps/prototype-description-service/docker-compose.vlm.yml:13` opt-in `acx-backend-vlm` default
- `apps/prototype-description-service/Dockerfile:189` existing `runtime-vlm` stage (still not default)
- `apps/prototype-description-service/recognition/tests/deploy/test_dockerfile_stage_topology.py:120` offline + not-default
- `apps/prototype-description-service/recognition/tests/deploy/test_compose_image_variant_parity.py:210` overlay vs slim default

TEST-15: drop `model_revision=` in `deps.py` → provenance test RED (`assert False`). Restore matched pre-mutant. Overlay synthetic: slim-repo default fails `compose_defaults_to_vlm_image_repo`.

GREEN: `108 passed` (profiles + gpu adapter + compose parity + dockerfile topology). Owning scene+deploy: `1437 passed, 4 skipped`.

Did not flip `ACX_DESCRIPTION_ADAPTER` (stays `seeded`). Did not build the VLM image.

## Undone

- Full `runtime-vlm` image was not built (brief: host constraints; stage is lint/parity tested only).
- GPU host GGUF bytes are not hashed per request; wire provenance names the configured hub pin, not a llama.cpp weight digest.
- Source transformers snapshot was resolved the same day and not used as the pin (served artifact is the GGUF).
- `infra/` / bootstrap-wp wiring left for the later integration lane.
- Default adapter remains `seeded`; non-seeded is viable, not the default.

## Canon cited

- SEC-10: unpinned hub pull is unauditable; available GPU profiles now pin a 40-char revision.
- SERVE-01: llama.cpp stays behind `GpuRemoteDescriptionAdapter`; served id is not the wire identity.
- SERVE-07: Q4_K_M was already the incumbent; this slice pins/names it, does not promote a new quant.
- evidence-before-commitment: pin written only after live `HfApi().model_info` this session.
- licence-provenance-is-transitive: pin is the Unsloth GGUF derivation, not a one-hop transformers SPDX glance.
- TEST-15: unpin / drop-revision mutants turned the new asserts red; overlay slim-default mutant too.
