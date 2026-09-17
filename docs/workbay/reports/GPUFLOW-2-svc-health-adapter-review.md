VERIFIED: {"DIAGNO-H-06":"not_fixed","DIAGNO-b54e2b152c2135f4-H-5aa9f6692d839e169eee66bb":"not_fixed","DIAGNO-b54e2b152c2135f4-H-0b8d323dccc48fd331ee798e":"not_fixed"}
FINDINGS: [{"id":"GPUFLOW-2-SVCHEALTHADAPTER-R-01","severity":"high","file_path":"apps/prototype-description-service/api/main.py","line":205,"summary":"Readiness accepts a non-HTTP(S) GPU endpoint as usable.","evidence":"_endpoint_hostname() extracts only the hostname and _description_adapter_readiness() gates usable on nonempty URL, allowlist, private DNS, and freshness; it never checks the URL scheme. The existing adapter resolver rejects schemes other than http/https, so a value such as gpu.oraclevcn.com can produce usable=true for an adapter that will fail closed."},{"id":"GPUFLOW-2-SVCHEALTHADAPTER-R-02","severity":"high","file_path":"apps/prototype-description-service/api/main.py","line":236,"summary":"Readiness reports profiles marked unavailable as usable.","evidence":"The non-GPU branch unconditionally sets usable=True, and the GPU branch does not test ProfileSpec.available. The registry marks florence_large, gpu_phi4, and hosted_gpt4o unavailable while get_description_adapter() returns UnavailableDescriptionAdapter for them; the new health contract can therefore publish a false release-readiness signal."},{"id":"GPUFLOW-2-SVCHEALTHADAPTER-R-03","severity":"medium","file_path":"apps/prototype-description-service/api/main.py","line":142,"summary":"A real DNS gaierror is cached as a fresh non-private result instead of stale/pending evidence.","evidence":"_resolve_blocking() only preserves stale state when the imported helper raises, but scene/interface_adapters/http/deps.py catches socket.gaierror and returns False. The worker then stores value=False and checked_at, making fresh=true and reason=endpoint_not_private; the added gaierror test monkeypatches api.main._resolved_addresses_are_private to raise and bypasses this production path."},{"id":"GPUFLOW-2-SVCHEALTHADAPTER-R-04","severity":"medium","file_path":"apps/prototype-description-service/api/main.py","line":221,"summary":"Per-request readiness construction can perform blocking OCI Vault I/O on the event loop.","evidence":"Each /health/detailed request constructs DescriptionSettings(), whose gpu_endpoint_api_key default calls get_secret_provider().get_secret_optional(); an OCI provider cache miss performs synchronous get_secret_bundle calls and retry sleeps. The readiness hunk bounds DNS but leaves this unrelated external call inline, so the supposedly bounded diagnostic can stall well beyond the CARD-09/RES-02 timeout budget."}]
Verdict: fail

# GPUFLOW-2 svc-health-adapter re-review

## Re-review r1 (284616c05..63a79bcc3)

| finding | verdict | evidence |
| --- | --- | --- |
| DIAGNO-H-06 | not_fixed | The A1 hunk adds `profile` and `kind` plus endpoint/readiness fields to the return object (`apps/prototype-description-service/api/main.py:+251-260`), but no canonical `model_id` or `model_version`. The new tests resolve the profile spec and assert model constants (`scene/tests/test_health_detailed_adapter.py:+107-116`, `+153-171`) without asserting those identities in the health payload, so the release proof still cannot compare response identity to readiness. This violates the contract-metadata boundary in `[rg-015]` and the test discrimination requirement in `[TEST-15]`. |
| DIAGNO-b54e2b152c2135f4-H-5aa9f6692d839e169eee66bb | not_fixed | The fix still emits the profile token `gpu_qwen30b`/`gpu_qwen30b_ensemble` in `description_adapter.profile`; it adds no mapping or concrete model identity in the A1 return hunk (`api/main.py:+251-260`). The test's `get_profile_spec(...).model_id` assertions are local constants, not response-vs-model equality evidence. The vocabulary mismatch in the release gate therefore remains. |
| DIAGNO-b54e2b152c2135f4-H-0b8d323dccc48fd331ee798e | not_fixed | The delta changes the producer payload at `api/main.py:+787` and adds only the new adapter test; it does not touch the existing string consumers. `infra/oci/demo/lib/describe-gate.sh:84-115` still accepts `description_adapter` only when it is a JSON string, `scripts/gpu_burst_smoke.py:1549-1557,1654-1660` still compares the field to `"gpu_qwen30b"`, and `bootstrap-wp.sh:364-406` still routes through that string parser. The new object therefore blocks/rejects those consumers as previously found. |

### FINDINGS

#### GPUFLOW-2-SVCHEALTHADAPTER-R-01 — high

`_endpoint_hostname()` (`apps/prototype-description-service/api/main.py:205-208`) parses only `.hostname`; `_description_adapter_readiness()` treats any nonempty URL as configured and computes `usable` from allowlisting, privacy, and freshness (`:223-240`) without validating `http`/`https`. The actual GPU adapter predicate rejects other schemes (`scene/interface_adapters/http/deps.py:65-83`). Thus `ACX_GPU_ENDPOINT_URL=gpu.oraclevcn.com` can resolve as private and publish `usable: true` while the describe adapter returns its fail-closed unavailable adapter. This is a release-facing false readiness signal under `[CARD-09]` and `[rg-015]`; scheme and URL validity must be part of the same fail-closed predicate.

#### GPUFLOW-2-SVCHEALTHADAPTER-R-02 — high

The new readiness branch sets every non-GPU profile `usable=True` (`api/main.py:236-238`) and the GPU branch does not consult `spec.available` (`:239-250`). However, the profile registry marks `florence_large`, `gpu_phi4`, and `hosted_gpt4o` unavailable (`scene/config/profiles.py:79-103,131-141`), and the adapter resolver returns `UnavailableDescriptionAdapter` for unavailable profiles (`scene/interface_adapters/http/deps.py:200-232`). Those configurations can therefore pass a consumer's readiness check despite being deliberately fail-closed, violating the release invariant that `usable` describe the active adapter.

#### GPUFLOW-2-SVCHEALTHADAPTER-R-03 — medium

The fix intends a `gaierror` to leave the prior result stale (`api/main.py:142-152`), but the imported `_resolved_addresses_are_private()` catches `socket.gaierror` and returns `False` (`scene/interface_adapters/http/deps.py:40-47`). The worker consequently records `checked_at` for a DNS failure, and the handler reports `fresh=true`, `endpoint_private=false`, and `reason=endpoint_not_private` (`api/main.py:234-250`) for up to the 60-second attempt window. The new test at `scene/tests/test_health_detailed_adapter.py:282-298` replaces the helper with a raising stub, so it does not discriminate this production behavior. This loses the required pending/stale distinction and can unnecessarily delay recovery; it is a `[TEST-15]`/`[RES-13]` failure-mode gap.

#### GPUFLOW-2-SVCHEALTHADAPTER-R-04 — medium

The per-request call to `DescriptionSettings()` (`api/main.py:219-227`) is not configuration-only: its `gpu_endpoint_api_key` field calls `get_secret_provider().get_secret_optional()` (`scene/config/settings.py:105-110`). With the OCI backend, a cache miss performs synchronous Vault network calls (`shared/secrets.py:164-172,190-213`) and blocking retry sleeps on the event-loop thread. The fix bounds the DNS worker but leaves this new health-path I/O unbounded relative to the stated sub-second diagnostic behavior, violating `[CARD-09]`/`[RES-02]`; readiness should read only the needed non-secret config or isolate/bound secret access.

Verdict: fail

## Re-review r3 (63a79bcc3..b2f35ea73)

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-2-SVCHEALTHADAPTER-R-01 | fixed | `_gpu_endpoint_url_is_valid()` now requires an `http`/`https` scheme and a hostname (`apps/prototype-description-service/api/main.py:228-230`); the readiness path gates DNS and usability on `url_valid` and returns `endpoint_invalid_url` otherwise (`:253-254`, `:278-280`). The added parameterized test covers a bare hostname and `ftp://` and asserts DNS is skipped (`scene/tests/test_health_detailed_adapter.py:265-281`). |
| GPUFLOW-2-SVCHEALTHADAPTER-R-02 | fixed | The new `not spec.available` branch precedes the non-GPU/GPU usability branches and returns `usable: false` with `profile_unavailable` (`apps/prototype-description-service/api/main.py:269-271`); the added test enumerates every unavailable registry profile (`scene/tests/test_health_detailed_adapter.py:246-262`). |
| GPUFLOW-2-SVCHEALTHADAPTER-R-03 | fixed | `_resolve_blocking()` now owns the `socket.getaddrinfo()` call and returns on `socket.gaierror` before changing cached value or timestamp (`apps/prototype-description-service/api/main.py:143-149`), preserving stale/pending evidence. The new test patches that exact resolver (`scene/tests/test_health_detailed_adapter.py:284-299`). |
| GPUFLOW-2-SVCHEALTHADAPTER-R-04 | fixed | `_description_adapter_readiness()` reads the profile, endpoint, and allowlist directly from environment/spec data without constructing `DescriptionSettings` (`apps/prototype-description-service/api/main.py:248-255`); the added test makes both secret-provider entry points raise and still exercises health successfully (`scene/tests/test_health_detailed_adapter.py:302-312`). |
| DIAGNO-H-06 | partially_fixed | The delta adds `wire_model_id()` and emits `model_id`/`model_version` from the active profile (`apps/prototype-description-service/api/main.py:241-245`, `:267-304`), with schema/test coverage (`packages/shared-contracts/schemas/scene-health-detailed.schema.json:210-221`, `scene/tests/test_health_detailed_adapter.py:116-126`). However, the task plan and GPU smoke/release comparison are not changed in this delta, so the newly available identity is not yet wired into the stated proof. |
| DIAGNO-b54e2b152c2135f4-H-5aa9f6692d839e169eee66bb | not_fixed | The added identity fields make a correct comparison possible, but the delta does not change the release proof from the profile token to `description_adapter.model_id`/`model_version`; `profile` remains `gpu_qwen30b`-style vocabulary (`apps/prototype-description-service/api/main.py:293-304`, `packages/shared-contracts/schemas/scene-health-detailed.schema.json:306-317`). The hardcoded smoke/plan mismatch therefore remains. |

### FINDINGS

#### GPUFLOW-2-SVCHEALTHADAPTER-R-05 — high

The schema fix makes `model_id` and `model_version` required (`packages/shared-contracts/schemas/scene-health-detailed.schema.json:210-221`), but the existing shared-schema `HEALTH` fixture still contains only the old readiness keys (`apps/prototype-description-service/scene/tests/test_shared_schema_documents.py:75-85`). `test_health_detailed_adapter_readiness_document` consequently fails with `'model_id' is a required property`. This is a release-contract regression left by the fix delta.

#### GPUFLOW-2-SVCHEALTHADAPTER-R-06 — high

`wire_model_id()` falls back to `ProfileSpec.model_id` for non-GPU profiles (`apps/prototype-description-service/api/main.py:241-245`); the seeded spec has `model_id=None` (`apps/prototype-description-service/scene/config/profiles.py:62-67`), and readiness then forces `model_version=None` when that identity is absent (`api/main.py:267-268`). The actual `SeededDescriptionAdapter` stamps `model_id="seeded-fixtures"` and a non-null configured model version (`apps/prototype-description-service/scene/application/seeded_adapter.py:39-45`). The new seeded test asserts the incorrect null identity (`scene/tests/test_health_detailed_adapter.py:381-392`), so health provenance cannot reliably match seeded responses.

#### GPUFLOW-2-SVCHEALTHADAPTER-R-07 — high

The non-GPU branch still sets `usable=True` for every registry profile whose `available` flag is true (`apps/prototype-description-service/api/main.py:272-274`). `florence_small` is marked available, but its resolver explicitly raises when the optional VLM dependencies are missing (`apps/prototype-description-service/scene/interface_adapters/http/deps.py:122-132`) and converts that failure into `UnavailableDescriptionAdapter` (`:234-248`). The new CPU test only asserts the readiness boolean (`scene/tests/test_health_detailed_adapter.py:227-243`) and does not resolve the adapter, leaving a false release-readiness signal for an available-but-unresolvable deployment.

#### GPUFLOW-2-SVCHEALTHADAPTER-R-08 — high

`_gpu_endpoint_url_is_valid()` calls `urlparse()` without handling parse errors and validates only scheme plus hostname (`apps/prototype-description-service/api/main.py:228-230`). An unmatched IPv6 authority such as `http://[` raises `ValueError` instead of returning `endpoint_invalid_url`, while `http://gpu.oraclevcn.com:bad` has a valid hostname and passes this predicate even though its port is malformed. The added invalid-URL test covers only a missing scheme and `ftp://` (`scene/tests/test_health_detailed_adapter.py:265-281`), so malformed endpoint configuration can still crash health or publish readiness for an unusable adapter.

#### GPUFLOW-2-SVCHEALTHADAPTER-R-09 — low

The fix delta edits `packages/shared-contracts/schemas/scene-health-detailed.schema.json`, while the lane row assigns `api/main.py` and the new scene test to `svc-health-adapter` and assigns that schema to `contracts-service`. This crosses the declared lane ownership boundary and should be routed to the schema owner.

Verdict: fail

## Re-review r4 (b2f35ea73..f07634674)

VERIFIED: {"SVCHEA-0feee8f56b32d713-H-c1256b829ad577bd18c7693c":"fixed","SVCHEA-0feee8f56b32d713-H-f6bf1fc4861d3c8a95432829":"fixed","SVCHEA-0feee8f56b32d713-H-2bcba9707a7bea22ae8efc9d":"fixed","SVCHEA-0feee8f56b32d713-H-4c7afde184e3acbfdde31a78":"fixed"}
FINDINGS: [{"id":"GPUFLOW-2-SVCHEALTHADAPTER-R-10","severity":"low","file_path":"apps/prototype-description-service/scene/tests/test_shared_schema_documents.py","line":82,"summary":"The fix delta edits a shared-schema fixture outside the svc-health-adapter lane ownership.","evidence":"The delta adds model_id/model_version to HEALTH and its required-key assertion in scene/tests/test_shared_schema_documents.py (+82-89, +144-152), but the A1 lane row owns only api/main.py and scene/tests/test_health_detailed_adapter.py; the shared contract fixture should remain with contracts-service."}]
Verdict: pass_with_findings

| finding | verdict | evidence |
| --- | --- | --- |
| SVCHEA-0feee8f56b32d713-H-c1256b829ad577bd18c7693c (high) | fixed | The shared `HEALTH.description_adapter` fixture now supplies `model_id` and `model_version` (`apps/prototype-description-service/scene/tests/test_shared_schema_documents.py:+82-89`), and the expected-key assertion includes both fields (`:+144-152`), so the required schema document can validate. |
| SVCHEA-0feee8f56b32d713-H-f6bf1fc4861d3c8a95432829 (high) | fixed | `wire_model_id()` returns `SeededDescriptionAdapter.model_id` for the seeded profile and `_wire_model_version()` reads the configured seeded model version (`apps/prototype-description-service/api/main.py:+256-270`); the readiness payload uses both values (`:+291-292`), with a matching configured-version test (`scene/tests/test_health_detailed_adapter.py:+383-401`). |
| SVCHEA-0feee8f56b32d713-H-2bcba9707a7bea22ae8efc9d (high) | fixed | Readiness now checks `spec.available` and, for available local-CPU profiles, `_missing_vlm_dependencies()` before setting `usable` (`apps/prototype-description-service/api/main.py:+293-304`); missing VLM dependencies produce `vlm_dependencies_missing`, pinned by the added test (`scene/tests/test_health_detailed_adapter.py:+409-415`). |
| SVCHEA-0feee8f56b32d713-H-4c7afde184e3acbfdde31a78 (high) | fixed | `_parse_endpoint_url()` catches malformed `urlparse()`/port errors and `_gpu_endpoint_url_is_valid()` requires HTTP(S) plus a hostname (`apps/prototype-description-service/api/main.py:+223-245`); the new cases cover an unmatched bracket and malformed port and assert DNS is skipped (`scene/tests/test_health_detailed_adapter.py:+263-281`). |

### FINDINGS

#### GPUFLOW-2-SVCHEALTHADAPTER-R-10 — low

The fix delta edits `apps/prototype-description-service/scene/tests/test_shared_schema_documents.py` (`+82-89`, `+144-152`) to repair the shared `HEALTH` fixture. The A1 lane row assigns `api/main.py` and `scene/tests/test_health_detailed_adapter.py` to `svc-health-adapter`, while the shared schema is assigned to `contracts-service`; this additional fixture path crosses the declared one-owner boundary and should be routed to the contract owner (`[sr-007]`).

Verdict: pass_with_findings

## Re-review r5 (cab42a114..607994cea)

| finding | verdict | evidence |
| --- | --- | --- |
| SVCHEA-0feee8f56b32d713-H-e773a7622485644b567bfd6f (high) | fixed | `extract_probed_description_adapter()` now requires a top-level `description_adapter` object and returns its profile (`infra/oci/demo/lib/describe-gate.sh:+84-122`); the demo-gate tests replace string fixtures and reject a legacy string (`infra/oci/demo/tests/test-describe-gate.sh:+154-198`), while the GPU smoke path reads object identity and checks the expected profile/model ID/version (`scripts/gpu_burst_smoke.py:+1574-1612,+1708-1733`). |

### FINDINGS

#### GPUFLOW-2-SVCHEALTHADAPTER-R-11 — high

`extract_probed_description_adapter()` validates `model_id` and `model_version` only when those keys are present (`infra/oci/demo/lib/describe-gate.sh:+110-122`). An object containing only a nonempty `profile`, or empty identity strings, is therefore accepted and reduced to a profile; the changed tests cover non-string identity values but not omitted or empty values (`infra/oci/demo/tests/test-describe-gate.sh:+164-174`). The demo/bootstrap gate can consequently accept a schema-invalid or non-identifiable readiness payload even though the GPU smoke consumer now requires nonempty exact identity fields (`scripts/gpu_burst_smoke.py:+1588-1604`), leaving inconsistent release checks and a fail-open path for required metadata (`[rg-015]`, `[CARD-09]`).

#### GPUFLOW-2-SVCHEALTHADAPTER-R-12 — low

The fix delta changes `infra/oci/demo/lib/describe-gate.sh`, `infra/oci/demo/tests/test-describe-gate.sh`, `scripts/deploy/tests/test-smoke-gate.sh`, and `scripts/gpu_burst_smoke.py` (`:+84-122`, `:+154-198`, `:+923-926`, `:+73-82`, `:+1574-1733`), but the lane row assigns `svc-health-adapter` only `api/main.py` and `apps/prototype-description-service/scene/tests/test_health_detailed_adapter.py`. These consumer and fixture edits cross the declared single-owner boundary and should be routed to their owning lanes (`[sr-007]`).

Verdict: fail

## Re-review r6 (607994cea..db5eb118d)

VERIFIED: {"SVCHEA-0feee8f56b32d713-H-1ab3ae3ba4b23b879dba88f2":"fixed","SVCHEA-0feee8f56b32d713-H-e773a7622485644b567bfd6f":"not_fixed"}
FINDINGS: [{"id":"GPUFLOW-2-SVCHEALTHADAPTER-R-13","severity":"high","file_path":"infra/oci/demo/lib/describe-gate.sh","line":118,"summary":"The adapter extractor accepts a payload that is not valid detailed-health schema.","evidence":"The fix hunk validates only profile plus model_id/model_version presence and value shape (infra/oci/demo/lib/describe-gate.sh:112-120), while descriptionAdapterReadiness also requires kind, endpoint_configured, endpoint_allowlisted, endpoint_private, checked_at, fresh, usable, and reason (packages/shared-contracts/schemas/scene-health-detailed.schema.json:218-231). The new null-identity test passes only profile/model_id/model_version and calls it schema-valid (infra/oci/demo/tests/test-describe-gate.sh:176), so a malformed 2xx health body can still be admitted by the bootstrap gate [RLSE-05][TEST-15]."}]

| finding | verdict | evidence |
| --- | --- | --- |
| SVCHEA-0feee8f56b32d713-H-1ab3ae3ba4b23b879dba88f2 (high) | fixed | The extractor now rejects either missing identity key and rejects non-null values unless they are non-empty strings (`infra/oci/demo/lib/describe-gate.sh:116-120`); the added cases cover missing keys and an empty model_id (`infra/oci/demo/tests/test-describe-gate.sh:173-176`). Null remains allowed by the schema's identity types, so the claimed omitted/empty acceptance path is closed. |
| SVCHEA-0feee8f56b32d713-H-e773a7622485644b567bfd6f (high) | not_fixed | This delta only adds identity validation to the already-object extractor (`infra/oci/demo/lib/describe-gate.sh:112-120`); it does not change the health producer or the other consumers from string handling to object handling. The direct extractor tests (`infra/oci/demo/tests/test-describe-gate.sh:173-176`) do not prove the cross-consumer contract, so the listed object/string release break is not fixed by this diff. |

### FINDINGS

#### GPUFLOW-2-SVCHEALTHADAPTER-R-13 — high

The fix validates only `profile`, `model_id`, and `model_version` (`infra/oci/demo/lib/describe-gate.sh:112-120`), but the shared `descriptionAdapterReadiness` definition requires the complete readiness block, including `kind`, endpoint evidence, freshness, usability, and reason (`packages/shared-contracts/schemas/scene-health-detailed.schema.json:218-231`). The new test explicitly accepts `{"profile":"seeded","model_id":null,"model_version":null}` as “schema-valid” (`infra/oci/demo/tests/test-describe-gate.sh:176`), although that object omits every other required readiness field. A malformed HTTP-2xx health response can therefore still yield a trusted profile and pass the bootstrap gate, violating fail-closed release behavior (`[RLSE-05]`, `[TEST-15]`).

Verdict: fail
