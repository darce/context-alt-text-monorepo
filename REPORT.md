# Lane E — PROV-01

## Result

gpu_qwen30b / gpu_qwen30b_ensemble pin a live-resolved GGUF hub revision. Opt-in `runtime-vlm` compose overlay selects `acx-backend-vlm`. GPU describe provenance names `served-id@pin`; llama.cpp still gets the unadorned served id.

Final HEAD: recorded by the integrator after transplant.

## Commits

- `feat(scene): PROV-01a pin gpu_qwen30b hub revision`
- `feat(scene): PROV-01b runtime-vlm provenance names pinned revision`
- `fix(vlm-prov): W3-E-01 overlay-hardcodes-vlm-repo`
- `fix(vlm-prov): W3-E-02 walkable-hub-repo-model-id`
- `fix(vlm-prov): W3-E-04 pin-in-cache-key`
- `fix(vlm-prov): W3-E-05 drop-boolean-provenance-test`

## PROV-01a

RED (verbatim short summary):

```
FAILED scene/tests/test_description_profiles.py::test_available_gpu_profiles_pin_a_non_none_hub_revision - AssertionError: gpu_qwen30b is available=True GPU but model_revision is None (unpinned hub pull; SEC-10)
```

Pin: `huggingface_hub.HfApi().model_info("unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF").sha` on 2026-08-25 (served Q4_K_M GGUF, not the unquantized transformers snapshot). Ensemble shares the same pin.

- `apps/prototype-description-service/scene/config/profiles.py:113` gpu_qwen30b `model_revision`
- `apps/prototype-description-service/scene/config/profiles.py:125` ensemble pin
- `apps/prototype-description-service/scene/tests/test_description_profiles.py:111` available-GPU pin test

TEST-15: set gpu_qwen30b `model_revision=None` → same RED line. Restore: production file matched pre-mutant.

GREEN: `37 passed` (`scene/tests/test_description_profiles.py`).

## PROV-01b

RED (verbatim short summaries):

```
FAILED scene/tests/test_description_profiles.py::test_resolve_gpu_qwen30b_provenance_names_pinned_revision - AssertionError: assert False
FAILED scene/tests/test_gpu_remote_adapter.py::test_gpu_remote_adapter_provenance_names_loaded_revision_not_payload_model - TypeError: GpuRemoteDescriptionAdapter.__init__() got an unexpected keyword argument 'model_revision'
FAILED recognition/tests/deploy/test_compose_image_variant_parity.py::test_compose_vlm_overlay_defaults_to_vlm_repo - AssertionError: docker-compose.vlm.yml overlay missing
```

- `apps/prototype-description-service/scene/interface_adapters/http/deps.py:97` passes `spec.model_revision`
- `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py:145` served id vs wire `model_id`
- `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py:189` payload uses served id
- `apps/prototype-description-service/docker-compose.vlm.yml:14` opt-in `acx-backend-vlm` image
- `apps/prototype-description-service/Dockerfile:189` existing `runtime-vlm` stage (still not default)
- `apps/prototype-description-service/recognition/tests/deploy/test_dockerfile_stage_topology.py:120` offline + not-default
- `apps/prototype-description-service/recognition/tests/deploy/test_compose_image_variant_parity.py:286` overlay vs slim default

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

## Fix round

Adversarial panel: conditional pass. Commits:

- `fix(vlm-prov): W3-E-01 overlay-hardcodes-vlm-repo`
- `fix(vlm-prov): W3-E-02 walkable-hub-repo-model-id` (includes W3-E-03 contract/schema)
- `fix(vlm-prov): W3-E-04 pin-in-cache-key`
- `fix(vlm-prov): W3-E-05 drop-boolean-provenance-test`

### W3-E-01

RED (verbatim):

```
FAILED recognition/tests/deploy/test_compose_image_variant_parity.py::test_compose_vlm_overlay_defaults_to_vlm_repo - AssertionError: docker-compose.vlm.yml must hard-pin api/worker/fix-blob-ownership to iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm without interpolating ACX_IMAGE_REPO
assert False
FAILED recognition/tests/deploy/test_compose_image_variant_parity.py::test_compose_vlm_overlay_wins_over_sticky_slim_image_repo - AssertionError: api resolved 'iad.ocir.io/idu2kqqe2jxy/acx-backend:latest' under sticky ACX_IMAGE_REPO=iad.ocir.io/idu2kqqe2jxy/acx-backend; overlay must hard-pin acx-backend-vlm
```

- `apps/prototype-description-service/docker-compose.vlm.yml:14` api hard-pin
- `apps/prototype-description-service/docker-compose.vlm.yml:16` worker hard-pin
- `apps/prototype-description-service/docker-compose.vlm.yml:18` fix-blob-ownership hard-pin
- `apps/prototype-description-service/recognition/tests/deploy/test_compose_image_variant_parity.py:111` named-service guard
- `apps/prototype-description-service/recognition/tests/deploy/test_compose_image_variant_parity.py:306` sticky-slim merge
- `apps/prototype-description-service/recognition/tests/deploy/test_compose_image_variant_parity.py:399` api-only / slim / interpolating mutants

TEST-15: restore `${ACX_IMAGE_REPO:-*-vlm}` on overlay image lines → same merge RED (`api resolved '…/acx-backend:latest'`). Restore matched pre-mutant.

GREEN: `18 passed` (`recognition/tests/deploy/test_compose_image_variant_parity.py`).

### W3-E-02 / W3-E-03

RED (verbatim):

```
FAILED scene/tests/test_gpu_remote_adapter.py::test_gpu_remote_adapter_provenance_names_loaded_revision_not_payload_model - TypeError: GpuRemoteDescriptionAdapter.__init__() got an unexpected keyword argument 'hub_repo'
FAILED scene/tests/test_description_profiles.py::test_gpu_qwen30b_profile_is_available_endpoint_profile - AttributeError: 'ProfileSpec' object has no attribute 'hub_repo'
FAILED scene/tests/test_response_schema_parity.py::test_schema_model_id_documents_gpu_hub_pin_format - AssertionError: assert '<hub-repo>@' in ''
```

- `apps/prototype-description-service/scene/config/profiles.py:52` `hub_repo` field
- `apps/prototype-description-service/scene/config/profiles.py:112` gpu_qwen30b hub repo
- `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py:150` wire `{hub_repo}@{revision}`
- `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py:189` payload still served id
- `apps/prototype-description-service/scene/interface_adapters/http/deps.py:98` passes `spec.hub_repo`
- `docs/workbay/contracts/image-description-api.md:45` GPU `model_id` format + pin bump = new idempotence identity
- `packages/shared-contracts/schemas/image-description-response.schema.json:54` same `description`
- `apps/prototype-description-service/scene/tests/test_description_profiles.py:212` equality `hub_repo@revision`

TEST-15: drop `hub_repo=spec.hub_repo` in deps.py → equality RED (`Qwen3-VL-30B-A3B-Instruct@…` vs `unsloth/…-GGUF@…`). Restore matched pre-mutant.

GREEN: provenance + profiles + schema-format tests passed (profiles file then `37 passed`; W3-E-05 drops one).

Digest-linkage of the baked GGUF (cloud-init sha256 manifest) stays deferred to the integration lane.

### W3-E-04

RED (verbatim):

```
FAILED scene/tests/test_visual_facts_service.py::test_model_revision_pin_bump_misses_cache - AssertionError: pin bump must miss-cache, not reuse the prior caption
assert True is False
```

- `apps/prototype-description-service/scene/application/visual_facts_service.py:201` lookup includes `model_id`
- `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py:1456` unique constraint column
- `apps/prototype-description-service/db/models/scene.py:76` ORM unique constraint
- `docs/workbay/contracts/image-description-api.md:49` cache-key tuple includes `model_id`
- `apps/prototype-description-service/scene/tests/test_visual_facts_service.py:175` two pins, two cache rows

TEST-15: drop `ImageDescription.model_id == model_id` filter → same RED (`cached is True`). Restore matched pre-mutant.

GREEN: `21 passed` (visual_facts_service + description_repository + fusion_response_provenance).

### W3-E-05

Dropped boolean-only `test_resolve_gpu_qwen30b_provenance_names_pinned_revision`. Kept equality at `apps/prototype-description-service/scene/tests/test_description_profiles.py:212`.

PROV-01a GREEN corrected 36→37 (re-run of that file before this drop). After the drop: `36 passed` (`scene/tests/test_description_profiles.py`).

Owning scene+deploy re-run: `1439 passed, 4 skipped`.

## Undone

- Baked-GGUF digest linkage (cloud-init sha256 manifest) deferred to the integration lane (W3-E-02).
- Full `runtime-vlm` image still not built; overlay/stage are lint/parity tested only.
- `infra/` / bootstrap-wp wiring still later.
- GPU host GGUF bytes are not hashed per request; wire names the configured hub pin.
- Adapter still falls back to served-id@pin if `hub_repo` is omitted (`hub_repo or model_id`); deps always passes the spec field.
- Greenfield unique-constraint edit in `001_identity_schema.py` assumes rebuild, not a live ALTER.
- Overlay merge test is interpolation-aware YAML merge, not a `docker compose config` subprocess (compose confirmed the slim-sticky bug before the hard-pin).

## Canon cited

- SEC-10: GPU wire identity is now a walkable hub-repo@revision, not served-id@sha.
- WRIT-41: citation without hub repo could not be followed.
- SERVE-01: llama.cpp payload stays the unadorned served id behind the adapter.
- REF-09: pin stored only in non-key `model_id` would desync from cache identity.
- DATA-14: cache unique constraint is the single authority; pin belongs in that key.
- TEST-15: overlay interpolation, dropped `hub_repo`, and dropped `model_id` filter each went red then restored.
- TEST-17: boolean-only provenance asserts replaced by the remaining equality.
- TEST-06: each fix was observed failing with the predicted message before the production change.
- evidence-before-commitment: profiles GREEN 36→37 from a re-run; owning suite 1439/4 from this session.
