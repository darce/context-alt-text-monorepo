# Task Plan

> **Metadata**
>
> - **Date**: 2026-10-28 20:49 EDT
> - **Author**: Claude Opus 5.5 (`claude-opus-5-5`)
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
> - **Epic Short ID**: E15
> - **Task Plan Status**: `proposed`
> - **Target Branch**: `feature/e15-39`
> - **Review Coverage Target**: 2
> - **Scope Brief**: `docs/scopes/descpick-gtm-beta-readiness-scope.md`
> - **Anchors verified at**: `43366e5d25` (2026-10-28); unchanged at main `8eece0358f`.

---

## E15-39. Description default, trusted set and serve pin

Source paths below are relative to `apps/prototype-description-service/` unless they begin with `apps/`, `infra/`, `scripts/`, `config/` or `docs/` (repo root). Checklists, JSON and commands use full repo-relative paths.

## Objective

Make the description service's defaults explicit and the served model reproducible. An unset `ACX_DESCRIPTION_ADAPTER` resolves to `seeded` (no model call) instead of Florence. `florence_small` leaves the trusted describe set, so no demo or deploy gate can accept Florence output as a live result. The GPU serve unit pins the llama.cpp image by digest and passes every decode-relevant flag explicitly. Tests pin the decided quota semantics: an unavailable GPU charges no demo quota, and cancelling a run keeps its charge.

## Intake

> Include this section when a P0 scope intake pass was conducted before assessment. Omit for bug fixes, tech debt tasks, and spec-derived tasks.

- **Scope one-pager**: `docs/scopes/descpick-gtm-beta-readiness-scope.md`; eval cases GTM-SC-08 … GTM-SC-11 and GTM-SC-20 in `docs/scopes/descpick-gtm-beta-readiness-evals.json`.
- **Key Q&A decisions**: #20474 (Florence is benchmark-only and its CPU fallback stays dormant; demo quota is charged at run creation; GPU unavailable consumes nothing; cancel keeps the charge), #20471 (canon; no `--kv-unified`), #20472 (llama.cpp defaults are build-dependent), #20420 (the evaluated A10 decision profile), all on `MAINT-descpick-gtm-scope-20261028`.
- **Not-Doing**: deleting the Florence enum member or adapter; changing the dormant CPU fallback; server-side cancel refunds.

## Problem Statement

1. **Unstated default** [REF-27]. `scene/config/settings.py:80` and `api/main.py:288` both default an unset `ACX_DESCRIPTION_ADAPTER` to `florence_small`. FIR report v13 (`#v13-caption`, decision 15953) calls Florence on an unset host "configuration drift, not the operating baseline". A misconfigured host silently serves CPU Florence captions.
2. **Florence is trusted.** `infra/oci/demo/lib/describe-gate.sh:25` lists `florence_small` in `ACX_TRUSTED_DESCRIBE_PROFILES`, so the demo describe gate, the smoke gate (`scripts/deploy/lib/smoke-gate.sh` `classify_alt_identity`, which reads the same list) and GPU env preflight accept Florence output as live.
3. **The served model is not pinned** [SERVE-07]. `infra/oci/gpu-cloud-init.yaml:330-341` runs `ghcr.io/ggerganov/llama.cpp:server-cuda` by mutable tag with only `--ctx-size 8192` set. A re-pull or a llama.cpp default change silently changes the model DESCPICK evaluated (decision 20420: image id `fc26b60b…`, ctx 8192, image token cap 1536, parallel 1, f16 KV cache).
4. **Quota semantics are decided but unpinned.** No test proves that a GPU-unavailable describe charges nothing, or that cancelling a run keeps its charge (#20474).

## Constraints

- Greenfield: no compatibility flag for the old default; delete the Florence arm of `_describe_profile_kind` instead of disabling it.
- `florence_small` stays a `DescriptionProfile` member, adapter and benchmark profile (the dormant CPU fallback in `infra/oci/gpu_lifecycle/controller.py:26` and benchmark scripts use it). Only the default and the trusted set change.
- The image digest comes from operator step S0 on the GPU host. No lane invents or looks up a digest; lanes `e15-39-r3` and `e15-39-i3` dispatch only after the S0 decision is recorded, and their briefs embed it.
- No `--kv-unified` (#20471).
- Generated env examples (`apps/prototype-description-service/.env.prod.example`, `infra/oci/demo/.env.example`) change only through `make env-examples`.
- RED lanes edit tests only; guard lanes prove each guard with a TEST-15 mutation (temporary edit → red → `git checkout -- <file>` → `git status --short` shows only owned paths).
- Shell tests run with `LC_ALL=C` (macOS bash 3.2). Never run the env and deploy pytest suites in one invocation (conftest clash).
- `docs/workbay/contracts/gpu-lifecycle.md` is unchanged: no lifecycle state or transition changes here.

## Workflow Principles

- One owner per default: `DEFAULT_DESCRIPTION_PROFILE` is read by both settings and the API resolver.
- One owner per trusted list: `ACX_TRUSTED_DESCRIBE_PROFILES` in `infra/oci/demo/lib/describe-gate.sh`; every other gate reads it.
- The served build equals the evaluated build: digest plus explicit flags, no reliance on llama.cpp defaults.
- RED first; fixture moves that stay green on both sides go in the RED lane so the implementation lane cannot break unrelated tests.

## Terminology

| Term | Meaning |
|---|---|
| Seeded | `DescriptionProfile.SEEDED`: deterministic fixture captions, no model call; forbidden for demo publish. |
| Trusted describe set | `ACX_TRUSTED_DESCRIBE_PROFILES` in `infra/oci/demo/lib/describe-gate.sh`: the adapters whose output a gate may accept as live. |
| Serve pin | The llama.cpp image referenced as `ghcr.io/ggerganov/llama.cpp@sha256:<digest>` plus every decode-relevant flag set explicitly. |
| S0 digest | The RepoDigest recorded by the operator in step S0 for the image whose id is `sha256:fc26b60b30836e5a12fdb28823a3d4bda984c9386a4b04200c78e5a5150067fb`. |
| Decision profile | The A10 serving profile evaluated under decision 20420. |

## Current State Analysis

| Site | Today |
|---|---|
| `scene/config/settings.py:78-80` | `DescriptionSettings.profile` default factory: `os.environ.get("ACX_DESCRIPTION_ADAPTER", "florence_small")` |
| `api/main.py:286-293` | `_resolve_description_profile`: `os.environ.get("ACX_DESCRIPTION_ADAPTER", DescriptionProfile.FLORENCE_SMALL.value)` |
| `scene/config/profiles.py` | `DescriptionProfile` StrEnum (`SEEDED`, `FLORENCE_SMALL`, …, `GPU_QWEN30B`, `GPU_QWEN30B_ENSEMBLE`, `HOSTED_GPT4O`); no default constant |
| `scene/tests/test_description_profiles.py` | :133 `test_settings_default_profile_is_florence_small`; :146 `test_resolve_defaults_to_florence_small` (expects `DescriptionAdapterKind.LOCAL_CPU`); :152 `test_api_profile_resolver_defaults_to_florence_small`; :371 `test_default_profile_unaffected_by_hosted_optin` (expects `LOCAL_CPU`) |
| `scene/tests/test_settings.py:12-18` | `test_description_settings_defaults` expects `FLORENCE_SMALL` |
| `infra/oci/demo/lib/describe-gate.sh:25` | `ACX_TRUSTED_DESCRIBE_PROFILES="florence_small gpu_qwen30b gpu_qwen30b_ensemble"` |
| `infra/oci/demo/lib/describe-gate.sh:39-40` | WHY comment uses the substrings of `florence_small` as its example |
| `infra/oci/demo/lib/describe-gate.sh:370-376` | `_describe_profile_kind`: `florence_small) printf '%s' local_cpu ;;` |
| `scripts/deploy/preflight-gpu-env.sh:927-928` | `acx_is_trusted_describe_profile` (defined in `scripts/deploy/lib/gpu-env-contract.sh:90`, no list of its own); error text names `florence_small` |
| `scripts/deploy/lib/smoke-gate.sh:306`, `:374` | `classify_alt_identity` / `classify_alt_provenance` read `ACX_TRUSTED_DESCRIBE_PROFILES`; no Florence literal, no edit needed |
| `config/env/manifest.d/21-service-vm.toml:126`, `config/env/manifest.d/40-demo.toml:147` | `ACX_DESCRIPTION_ADAPTER` docs list `florence_small` as an allowed live value |
| `infra/oci/gpu-cloud-init.yaml` | :20 doc line names the tag; :49 `docker image inspect ghcr.io/ggerganov/llama.cpp:server-cuda`; :330-341 `docker run … ghcr.io/ggerganov/llama.cpp:server-cuda … --ctx-size 8192 --api-key-file …`; model digests :29-31 already pinned |
| `infra/oci/INFRA-TOPOLOGY.md:113` | "Served by `ghcr.io/ggerganov/llama.cpp:server-cuda`" |
| `scripts/test_vlm3_oci_gpu_infra.py:187-197` | `test_gpu_cloud_init_bakes_qwen_measurement_candidate` asserts the tag-based inspect line (:195) |
| `recognition/tests/scripts/test_gtmr_gpu_runtime_receipts.py:82` | `IMAGE_REF = "ghcr.io/ggerganov/llama.cpp:server-cuda"`; `_cmdline` (~:484-503) builds the expected container argv |
| `scene/interface_adapters/http/routers/describe.py` | `_ensure_gpu_ready` (:1189); nested `_charge_demo_quota` (:1561) |
| `scene/interface_adapters/http/routers/describe_run.py:687` | `await maybe_consume_demo_quota(auth, session, units=len(unique_media_ids))` at run creation; `cancel_describe_run` (:807) |
| `recognition/interface_adapters/http/deps/demo_quota.py:169` | `maybe_consume_demo_quota` |

## Target Outcome

- Unset `ACX_DESCRIPTION_ADAPTER` → `seeded`, through one constant, `DEFAULT_DESCRIPTION_PROFILE`.
- Trusted describe set = `gpu_qwen30b gpu_qwen30b_ensemble`. A `florence_small` claim BLOCKs the describe gate and FAILs alt provenance.
- Serve argv:

```text
docker run --rm --gpus all --name acx-gpu-vlm -p 8000:8000 \
  -v /opt/acx-gpu/models:/models:ro \
  -v "$KEY_PATH:/run/secrets/acx-gpu-api-key:ro" \
  ghcr.io/ggerganov/llama.cpp@sha256:<S0 digest> \
  --host 0.0.0.0 --port 8000 \
  --model /models/qwen3-vl-30b-a3b-instruct-q4.gguf \
  --mmproj /models/qwen3-vl-30b-a3b-instruct-mmproj.gguf \
  --ctx-size 8192 --parallel 1 --image-max-tokens 1536 \
  --n-gpu-layers all --cache-type-k f16 --cache-type-v f16 \
  --api-key-file /run/secrets/acx-gpu-api-key
```

- Quota: GPU-unavailable describe → 503 and zero quota consumed; cancelled run → charge kept. Both pinned by tests.

## Context Loading

> List the minimum authoritative context an agent should load before implementation.
> Prefer small, role-specific surfaces over broad repo ingestion.

- **Rules**: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/testing-principles.md`; `docs/workbay/constitution.md#short-rules` (sr-007; rg-006, rg-008).
- **Contracts**: `docs/workbay/contracts/gpu-lifecycle.md` (read only; unchanged); the env manifest under `config/env/manifest.d/`.
- **Handoff/MCP state**: the `E15-39` row; decisions #20474, #20471, #20420 and the S0 digest decision.
- **External docs via `ctx7` only if**: a llama.cpp flag's meaning is in doubt after reading `--help` from the pinned image.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `ACX_DESCRIPTION_ADAPTER` unset | `scene/config/profiles.py` | `florence_small` | `seeded` | No (greenfield; deploy manifests set it explicitly) | R1 tests |
| Trusted describe set | `infra/oci/demo/lib/describe-gate.sh` | includes `florence_small` | `gpu_qwen30b gpu_qwen30b_ensemble` | No | R2a, R2b, `infra/oci/demo/tests/test_dw2_describega_1.py` |
| GPU serve unit | `infra/oci/gpu-cloud-init.yaml` | tag + default flags | digest + explicit flags | No: a host whose image does not match the digest fails closed at the inspect check | R3 tests; operator S4 receipt |
| Demo quota | `describe.py`, `describe_run.py` | charge after GPU readiness; charge at run creation | unchanged, now pinned | No | Q1 tests |

Non-functional notes:

- **Latency**: explicit flags remove the risk of a silent latency regression from changed llama.cpp defaults. The S4 receipt records one cold start end to end; percentiles across real traffic come from E15-40 [PERF-01].
- **Degraded behaviour**: GPU unavailable → 503 with a configuration-fault reason and no quota charge. An unset adapter → seeded captions, which every gate already refuses to publish.
- **Load and spikes**: unchanged; `--parallel 1` matches the evaluated profile, and the inflight bulkhead stays the admission control.

## Proposed Solution

1. **Slice 1**: add `DEFAULT_DESCRIPTION_PROFILE = DescriptionProfile.SEEDED` and read it in both default sites.
2. **Slice 2**: pin the quota semantics with two guard tests.
3. **Slice 3**: drop `florence_small` from the trusted set, its kind mapping and the preflight message; move test fixtures that need a trusted adapter to `gpu_qwen30b`.
4. **Slice 4**: update the env manifest docs and regenerate the examples.
5. **Slice 5**: pin the serve image by digest and set the flags explicitly (after S0).
6. **Operator S0 and S4**: record the digest before Slice 5; run one cold start after deploy and file the receipt.

## Files and Surfaces to Change

> Name the exact symbol(s) per file — the implementer should not have to grep for the edit site. Mark new symbols `(new)`. Prefer symbol names over line numbers.

| Surface | File | Symbol / Function | Change |
|---|---|---|---|
| Profile default | `scene/config/profiles.py` | `DEFAULT_DESCRIPTION_PROFILE` (new) | Slice 1 |
| Settings | `scene/config/settings.py` | `DescriptionSettings.profile` | read the constant |
| API | `api/main.py` | `_resolve_description_profile` | read the constant |
| Default tests | `scene/tests/test_description_profiles.py`, `scene/tests/test_settings.py` | tests listed in Slice 1; `test_default_description_profile_has_one_owner` (new) | RED |
| Quota guards | `scene/tests/test_describe_route.py`, `scene/tests/test_describe_run_quota.py` | `test_gpu_unavailable_does_not_consume_demo_quota` (new), `test_cancelling_a_demo_run_keeps_its_charge` (new) | guards |
| Describe gate | `infra/oci/demo/lib/describe-gate.sh` | `ACX_TRUSTED_DESCRIBE_PROFILES`, `_describe_profile_kind` | Slice 3 |
| Preflight | `scripts/deploy/preflight-gpu-env.sh` | trusted-adapter error message | Slice 3 |
| Infra README | `infra/oci/README.md` | trusted/live adapter statements | Slice 3 |
| Gate tests | `infra/oci/demo/tests/test-describe-gate.sh`; `scripts/deploy/tests/test_preflight_gpu_env.py`, `scripts/deploy/tests/test-smoke-gate.sh`, `scripts/deploy/tests/test_sync_demo_preflight.py` | fixtures + new assertions | RED |
| Env manifest | `config/env/manifest.d/21-service-vm.toml`, `config/env/manifest.d/40-demo.toml` | `ACX_DESCRIPTION_ADAPTER` docs | Slice 4 |
| Serve unit | `infra/oci/gpu-cloud-init.yaml`, `infra/oci/INFRA-TOPOLOGY.md` | serve block, inspect check | Slice 5 |
| Serve tests | `scripts/test_vlm3_oci_gpu_infra.py`, `apps/prototype-description-service/recognition/tests/scripts/test_gtmr_gpu_runtime_receipts.py` | `test_gpu_cloud_init_pins_runtime_image_by_digest_and_explicit_flags` (new), `IMAGE_REF`, `_cmdline` | RED |

## Related Files

| File | Note |
|---|---|
| `scripts/deploy/lib/gpu-env-contract.sh:90` | `acx_is_trusted_describe_profile`; reads the shared list; no change |
| `scripts/deploy/lib/smoke-gate.sh` | Reads the shared list; no change |
| `infra/oci/demo/tests/test_dw2_describega_1.py:46-49` | Expects `florence_small` → BLOCK; stays green |
| `infra/oci/gpu_lifecycle/controller.py:26` | `CPU_FALLBACK_PROFILE = "florence_small"`; dormant; reconciled in S4 |
| `infra/oci/gpu_lifecycle/tests/` | CPU-fallback tests use `florence_small`; unaffected |
| `scene/interface_adapters/http/deps.py` | Builds the adapter from settings; no default of its own |
| `scripts/seed_vlm_cache.py:157` | Help text mentions the Florence pin; benchmark tooling; unchanged |
| `docs/workbay/contracts/gpu-lifecycle.md` | Lifecycle contract; unchanged |

## Verification Strategy

> Define the evidence bundle before implementation.
> Include deterministic tests first; add runtime-parity or manual verification when they are genuinely required.

- **Deterministic tests**: pytest for the service, the deploy scripts and the GPU infra; bash suites for both gates.
- **Runtime-parity / environment checks**: `make env-examples` then `make env-check`; operator S4 cold-start receipt on the real GPU.
- **Contract/fixture verification**: the generated env examples change only through the generator; `git diff` on them after Slice 4 shows only the doc text.
- **Failure-mode / SLA prompts**: State p99 latency target (not average), degraded behavior when dependency X is down/slow, and spike/peak load assumptions — see planning-review-guide § Non-Functional & Failure-Mode Realism. Answered in Contract and Boundary Impact.
- **Manual verification**: operator S4 only.

```bash
uv run --directory apps/prototype-description-service python -m pytest scene/tests/test_description_profiles.py scene/tests/test_settings.py -q
```

```bash
uv run --directory apps/prototype-description-service python -m pytest scene/tests/test_describe_route.py scene/tests/test_describe_run_quota.py -q
```

```bash
LC_ALL=C bash infra/oci/demo/tests/test-describe-gate.sh
```

```bash
LC_ALL=C bash scripts/deploy/tests/test-smoke-gate.sh
```

```bash
LC_ALL=C uv run --no-project --with pytest python -m pytest scripts/deploy/tests/test_preflight_gpu_env.py scripts/deploy/tests/test_sync_demo_preflight.py -q -p no:cacheprovider
```

```bash
LC_ALL=C uv run --no-project --with pytest python -m pytest infra/oci/demo/tests/test_dw2_describega_1.py -q -p no:cacheprovider
```

```bash
uv run --no-project --with pytest --with pyyaml python -m pytest scripts/test_vlm3_oci_gpu_infra.py -q
```

```bash
uv run --directory apps/prototype-description-service python -m pytest recognition/tests/scripts/test_gtmr_gpu_runtime_receipts.py -q
```

## Slice Delivery

> Each slice must name the **files and functions** it touches (`path:symbol`) and the **proof** that closes it — enough for a junior agent to implement the slice from this block alone.

### Slice 1: Seeded default

Lanes: `e15-39-r1` (RED) then `e15-39-i1`.

**Goal**: an unset `ACX_DESCRIPTION_ADAPTER` resolves to `seeded` everywhere, through one constant.

Files/functions: `scene/tests/test_description_profiles.py`, `scene/tests/test_settings.py` (lane `e15-39-r1`); `scene/config/profiles.py:DEFAULT_DESCRIPTION_PROFILE` (new), `scene/config/settings.py:DescriptionSettings`, `api/main.py:_resolve_description_profile` (lane `e15-39-i1`).

Changes — lane `e15-39-r1`:

1. `test_description_profiles.py`:
   - :133 rename to `test_settings_default_profile_is_seeded`; expect `DescriptionProfile.SEEDED`.
   - :138 `test_settings_reads_profile_from_env`: keep (explicit env still wins).
   - :146 rename to `test_resolve_defaults_to_seeded`; expect `DescriptionAdapterKind.SEEDED`.
   - :152 rename to `test_api_profile_resolver_defaults_to_seeded`; expect `DescriptionProfile.SEEDED`.
   - :371 `test_default_profile_unaffected_by_hosted_optin`: expect `DescriptionAdapterKind.SEEDED`.
   - Add `test_default_description_profile_has_one_owner`. Import `DEFAULT_DESCRIPTION_PROFILE` inside the test body (the module must still collect) and assert it is `DescriptionProfile.SEEDED`. Then, with `ast`, parse `ROOT / "scene/config/settings.py"` and `ROOT / "api/main.py"` (`ROOT = Path(__file__).resolve().parents[2]`). Collect every call whose function unparses to `os.environ.get` and whose first argument is the constant `"ACX_DESCRIPTION_ADAPTER"`. Assert exactly two such calls, one per file, and that `ast.unparse` of each second argument is `"DEFAULT_DESCRIPTION_PROFILE.value"`.
2. `test_settings.py:12-18` `test_description_settings_defaults`: expect `DescriptionProfile.SEEDED`.

Changes — lane `e15-39-i1`:

1. `scene/config/profiles.py`, directly after `class DescriptionProfile`:

   ```python
   # Unset means no model call: Florence is benchmark-only (decision 15953, E15-39).
   DEFAULT_DESCRIPTION_PROFILE = DescriptionProfile.SEEDED
   ```

2. `scene/config/settings.py`: import `DEFAULT_DESCRIPTION_PROFILE` in the existing `from scene.config.profiles import …` (:16); the default factory becomes `os.environ.get("ACX_DESCRIPTION_ADAPTER", DEFAULT_DESCRIPTION_PROFILE.value)`; the :78 comment becomes `# The operator switch; unset resolves to seeded (no model call).`
3. `api/main.py`: add `DEFAULT_DESCRIPTION_PROFILE` to the :77 import; `_resolve_description_profile` reads `os.environ.get("ACX_DESCRIPTION_ADAPTER", DEFAULT_DESCRIPTION_PROFILE.value)`.

Proof: the RED run fails the renamed and new tests (and nothing errors at collection); after `e15-39-i1` both files pass. Also run `scene/tests/test_describe_route.py`; if a test outside the two RED files fails because it relied on the Florence default, stop and report it rather than editing it.

### Slice 2: Quota guards

Lane: `e15-39-q1` (guard tests, green on arrival; no implementation lane follows).

**Goal**: the decided quota semantics (#20474) cannot regress silently.

Files/functions: `scene/tests/test_describe_route.py:test_gpu_unavailable_does_not_consume_demo_quota` (new); `scene/tests/test_describe_run_quota.py:test_cancelling_a_demo_run_keeps_its_charge` (new).

Changes:

1. `test_gpu_unavailable_does_not_consume_demo_quota`: reuse the file's `_UnavailableGpuAdapter` (:1393, used at :1734) and `_gpu_env(state="stopped")` helper, with `ACX_GPU_ENDPOINT_URL=http://8.8.8.8:8000` (public address → `endpoint_not_private`). Patch `maybe_consume_demo_quota` where the describe router imports it with a counting spy. Post one demo describe. Assert status 503 with reason `endpoint_not_private`, `adapter.calls == 0` and zero spy calls.
2. `test_cancelling_a_demo_run_keeps_its_charge`: with the file's existing fixtures, create a demo describe run over N unique media (charged at creation, `scene/interface_adapters/http/routers/describe_run.py:687`), cancel it through `DELETE /describe/run/{run_id}` (`cancel_describe_run`), and assert the consumed quota is still N.

Proof: both pass on arrival. TEST-15: in `scene/interface_adapters/http/routers/describe.py`, move the `_charge_demo_quota()` call above the `_ensure_gpu_ready(...)` call → test 1 red; revert. Comment out the `maybe_consume_demo_quota` call at `describe_run.py:687` → test 2 red; revert. `git status --short` shows only the two test files.

### Slice 3: Florence leaves the trusted set

Lanes: `e15-39-r2a` and `e15-39-r2b` (RED, parallel), then `e15-39-i2`.

**Goal**: no gate accepts `florence_small` output as live, and every gate still reads one list.

Files/functions: `infra/oci/demo/tests/test-describe-gate.sh` (lane `e15-39-r2a`); `scripts/deploy/tests/test_preflight_gpu_env.py`, `scripts/deploy/tests/test-smoke-gate.sh`, `scripts/deploy/tests/test_sync_demo_preflight.py` (lane `e15-39-r2b`); `infra/oci/demo/lib/describe-gate.sh:ACX_TRUSTED_DESCRIBE_PROFILES`, `:_describe_profile_kind`, `scripts/deploy/preflight-gpu-env.sh`, `infra/oci/README.md` (lane `e15-39-i2`).

Fixture rule for both RED lanes: a fixture that uses `florence_small` as a trusted live adapter moves to `gpu_qwen30b`. If the fixture also carries a producer kind, change `local_cpu` to `gpu` (`_describe_profile_kind` blocks a kind mismatch). Keep each moved test's expected verdict unchanged, and run the suite before and after the move to show it stays green.

Changes — lane `e15-39-r2a` (`test-describe-gate.sh`):

- Move fixtures at :83-88, :93-100, :111, :127, :154-167, :367 and :524.
- Keep the Florence references at :73, :117, :145, :150, :222-258, :263-273 and :314 (substring, mismatch and untrusted cases).
- Add (RED):

  ```bash
  assert_exit "is_trusted florence_small (benchmark-only)" 1 is_trusted_describe_profile florence_small
  assert_eq "florence_small 100 0 (untrusted) BLOCK" BLOCK "$(classify_describe_gate florence_small 100 0 UNKNOWN "$ready_florence")"
  ```

Changes — lane `e15-39-r2b`:

- `test_preflight_gpu_env.py`: the cases at :497 and :506 that accept `florence_small` now expect exit 1 and the message "must be gpu_qwen30b or gpu_qwen30b_ensemble" (RED). Any other `florence_small` fixture in the file follows the fixture rule.
- `test-smoke-gate.sh`: move the fixtures at :37, :189, :191, :195, :583, :706, :714, :719, :760, :783, :802 and :937. Add (RED):

  ```bash
  assert_eq "alt provenance florence_small is benchmark-only (untrusted)" FAIL "$(classify_alt_provenance 0 florence_small 1)"
  ```

- `test_sync_demo_preflight.py`: the media stubs at :136 and :376 claim `"acx_alt_provenance":{"adapter":"florence_small"}` on a passing path; change them to `gpu_qwen30b` (green before and after).

Changes — lane `e15-39-i2`:

1. `describe-gate.sh:25`: `ACX_TRUSTED_DESCRIBE_PROFILES="gpu_qwen30b gpu_qwen30b_ensemble"`, with `# florence_small is benchmark-only (E15-39, decision #20474).` above it.
2. `describe-gate.sh:39-40` WHY comment: use `"gpu" and "qwen30b" are substrings of gpu_qwen30b and must not count as trusted.`
3. `_describe_profile_kind`: delete the `florence_small) printf '%s' local_cpu ;;` arm.
4. `preflight-gpu-env.sh:928`: "ACX_DESCRIPTION_ADAPTER must be gpu_qwen30b or gpu_qwen30b_ensemble." (keep the rest of the message).
5. `infra/oci/README.md`: where it lists `florence_small` as a trusted or live demo adapter, say it is benchmark-only; leave CPU-fallback descriptions alone.

Proof: RED runs fail only on the new assertions and the flipped preflight cases; after `e15-39-i2`, `test-describe-gate.sh`, `test-smoke-gate.sh`, the deploy pytest command and `test_dw2_describega_1.py` all pass.

### Slice 4: Env manifest docs

Lane: `e15-39-d2`, after Slice 3.

**Goal**: operator-facing docs match the trusted set and the default.

Files: `config/env/manifest.d/21-service-vm.toml` (`ACX_DESCRIPTION_ADAPTER` override for `svc-vm`), `config/env/manifest.d/40-demo.toml` (override for `demo`); generated `apps/prototype-description-service/.env.prod.example` and `infra/oci/demo/.env.example`.

Changes: in the svc-vm doc, mark `florence_small` "benchmark-only CPU captions; never trusted for demo publish" and add "Unset resolves to seeded (no model call)."; in the demo doc, the allowed values become `gpu_qwen30b | gpu_qwen30b_ensemble`. Then run `make env-examples` and `make env-check`. Do not hand-edit the generated examples.

Proof: `make env-check` passes; `git diff --stat` shows only the two TOMLs and the two generated examples.

### Slice 5: Serve pin

Lanes: `e15-39-r3` (RED) then `e15-39-i3`. Both dispatch only after operator S0 is recorded; the brief embeds the S0 digest and any flag correction S0 records.

**Goal**: the GPU host serves exactly the evaluated build.

Files/functions: `scripts/test_vlm3_oci_gpu_infra.py`, `apps/prototype-description-service/recognition/tests/scripts/test_gtmr_gpu_runtime_receipts.py` (lane `e15-39-r3`); `infra/oci/gpu-cloud-init.yaml`, `infra/oci/INFRA-TOPOLOGY.md` (lane `e15-39-i3`).

Changes — lane `e15-39-r3`:

1. `test_vlm3_oci_gpu_infra.py`: in `test_gpu_cloud_init_bakes_qwen_measurement_candidate`, the :195 assertion expects `docker image inspect ghcr.io/ggerganov/llama.cpp@sha256:<S0 digest>`; keep :154. Add `test_gpu_cloud_init_pins_runtime_image_by_digest_and_explicit_flags`: assert `":server-cuda"` does not occur anywhere in the cloud-init; take the lines from `exec /usr/bin/docker run` through the `--api-key-file` line, join the backslash continuations, `shlex.split` them, and assert the image token equals the digest reference, each pair `--ctx-size 8192`, `--parallel 1`, `--image-max-tokens 1536`, `--n-gpu-layers all`, `--cache-type-k f16`, `--cache-type-v f16` appears as adjacent tokens, and `--kv-unified` is absent.
2. `test_gtmr_gpu_runtime_receipts.py`: :82 `IMAGE_REF` becomes the digest reference; `_cmdline` (~:484-503) adds the five new flags in cloud-init order.

Changes — lane `e15-39-i3`:

1. `gpu-cloud-init.yaml`: replace the tag with the digest reference at :20 (doc line), :49 (inspect check) and the `docker run` image (:335); after `--ctx-size 8192 \` add one line each for `--parallel 1`, `--image-max-tokens 1536`, `--n-gpu-layers all`, `--cache-type-k f16`, `--cache-type-v f16`, each ending with ` \`. Keep the model digests (:29-31).
2. `INFRA-TOPOLOGY.md:113`: "Served by `ghcr.io/ggerganov/llama.cpp@sha256:<S0 digest>` (image id `sha256:fc26b60b…`) on `:8000` with explicit `--ctx-size 8192 --parallel 1 --image-max-tokens 1536 --n-gpu-layers all --cache-type-k f16 --cache-type-v f16`".

Proof: RED fails on the digest and flag assertions; after `e15-39-i3`, both test commands pass.

### Operator S0: record the image digest

Before Slice 5. On the GPU golden-image host:

```bash
docker image inspect --format '{{.Id}} {{json .RepoDigests}}' ghcr.io/ggerganov/llama.cpp:server-cuda
```

The id must be `sha256:fc26b60b30836e5a12fdb28823a3d4bda984c9386a4b04200c78e5a5150067fb`; if it is not, stop: the host does not serve the evaluated build. Then run `--help` from the digest reference and confirm `--parallel`, `--image-max-tokens`, `--n-gpu-layers`, `--cache-type-k` and `--cache-type-v` exist. If `--n-gpu-layers` does not accept `all`, record the accepted value (for example 999). Record the RepoDigest and any flag correction as a decision on `E15-39`.

### Operator S4: cold-start receipt

After Slices 1, 3 and 5 are deployed. With the GPU stopped, run one demo describe and record: time from submit to description, image digest and container args (`docker inspect`), quota counter before and after, and the gate verdicts. Reconcile decision #10035 with `infra/oci/gpu_lifecycle/controller.py:26` (`CPU_FALLBACK_PROFILE`): with Florence untrusted, a CPU fallback result must BLOCK at the gate. Write `docs/runbooks/evidence/e15-39-cold-start-receipt.json` (new directory).

## Not Doing

- Deleting `DescriptionProfile.FLORENCE_SMALL`, the Florence adapter or the service README's Florence section.
- Changing the dormant CPU fallback (`infra/oci/gpu_lifecycle/controller.py`, `reaper.py`); S4 only reconciles it.
- Pinning the bake pull in `infra/oci/gpu-bake-cloud-init.yaml`: a re-bake that pulls a different image fails the serve unit's digest inspect closed; pin it with the next bake.
- `--kv-unified` or any flag not in the decision profile.
- Refunds on cancel.

## Decomposition

Machine-checked by `plan_decomposer`; ids map to lanes in the table below.

```json
{
  "version": 1,
  "items": [
    {"id": "s1", "title": "R1 RED: seeded default", "independent": true, "owns": ["apps/prototype-description-service/scene/tests/test_description_profiles.py", "apps/prototype-description-service/scene/tests/test_settings.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s2", "title": "I1: DEFAULT_DESCRIPTION_PROFILE", "independent": false, "owns": ["apps/prototype-description-service/scene/config/profiles.py", "apps/prototype-description-service/scene/config/settings.py", "apps/prototype-description-service/api/main.py"], "depends": ["s1"], "blast": "full", "anchors": ["DescriptionProfile", "DescriptionSettings", "_resolve_description_profile"]},
    {"id": "s3", "title": "Q1 guards: demo quota semantics", "independent": true, "owns": ["apps/prototype-description-service/scene/tests/test_describe_route.py", "apps/prototype-description-service/scene/tests/test_describe_run_quota.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s4", "title": "R2a RED: describe gate drops Florence", "independent": true, "owns": ["infra/oci/demo/tests/test-describe-gate.sh"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s5", "title": "R2b RED: preflight and smoke gate drop Florence", "independent": true, "owns": ["scripts/deploy/tests/test_preflight_gpu_env.py", "scripts/deploy/tests/test-smoke-gate.sh", "scripts/deploy/tests/test_sync_demo_preflight.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s6", "title": "I2: trusted describe set without Florence", "independent": false, "owns": ["infra/oci/demo/lib/describe-gate.sh", "scripts/deploy/preflight-gpu-env.sh", "infra/oci/README.md"], "depends": ["s4", "s5"], "blast": "full", "anchors": ["ACX_TRUSTED_DESCRIBE_PROFILES", "is_trusted_describe_profile", "_describe_profile_kind"]},
    {"id": "s7", "title": "D2: env manifest docs and generated examples", "independent": false, "owns": ["config/env/manifest.d/21-service-vm.toml", "config/env/manifest.d/40-demo.toml", "apps/prototype-description-service/.env.prod.example", "infra/oci/demo/.env.example"], "depends": ["s6"], "blast": "none", "anchors": []},
    {"id": "s8", "title": "R3 RED: serve pin by digest and explicit flags", "independent": true, "owns": ["scripts/test_vlm3_oci_gpu_infra.py", "apps/prototype-description-service/recognition/tests/scripts/test_gtmr_gpu_runtime_receipts.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s9", "title": "I3: serve pin in cloud-init", "independent": false, "owns": ["infra/oci/gpu-cloud-init.yaml", "infra/oci/INFRA-TOPOLOGY.md"], "depends": ["s8"], "blast": "none", "anchors": []}
  ]
}
```

## Lane Decomposition (Multi-Agent)

> Include this section only when the task naturally splits into independent lanes.
> Omit for single-lane work that one agent can complete in a bounded session.
> Prefer the machine-checked `## Decomposition` JSON block above when lanes will
> be compiled through `plan_decomposer` → `work_graph_compiler`.

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
|---|---|---|---|
| `e15-39-r1` | `scene/tests/test_description_profiles.py`, `scene/tests/test_settings.py` | None | Service pytest on both (red) |
| `e15-39-i1` | `scene/config/profiles.py`, `scene/config/settings.py`, `api/main.py` | `e15-39-r1` | Service pytest on both + `test_describe_route.py` |
| `e15-39-q1` | `scene/tests/test_describe_route.py`, `scene/tests/test_describe_run_quota.py` | None | Service pytest on both + two mutations |
| `e15-39-r2a` | `infra/oci/demo/tests/test-describe-gate.sh` | None | `LC_ALL=C bash` on the file (new asserts red) |
| `e15-39-r2b` | `scripts/deploy/tests/test_preflight_gpu_env.py`, `scripts/deploy/tests/test-smoke-gate.sh`, `scripts/deploy/tests/test_sync_demo_preflight.py` | None | Smoke suite + deploy pytest (new asserts red) |
| `e15-39-i2` | `infra/oci/demo/lib/describe-gate.sh`, `scripts/deploy/preflight-gpu-env.sh`, `infra/oci/README.md` | `e15-39-r2a`, `e15-39-r2b` | Both gate suites, deploy pytest, `test_dw2_describega_1.py` |
| `e15-39-d2` | `config/env/manifest.d/21-service-vm.toml`, `config/env/manifest.d/40-demo.toml` (+ two generated examples) | `e15-39-i2` | `make env-examples`, `make env-check` |
| `e15-39-r3` | `scripts/test_vlm3_oci_gpu_infra.py`, `recognition/tests/scripts/test_gtmr_gpu_runtime_receipts.py` | Operator S0 | Both serve tests (red) |
| `e15-39-i3` | `infra/oci/gpu-cloud-init.yaml`, `infra/oci/INFRA-TOPOLOGY.md` | `e15-39-r3` | Both serve tests |

### Merge Order

A lane dispatches once every lane it depends on has merged.

1. Wave 1: `e15-39-r1`, `e15-39-q1`, `e15-39-r2a`, `e15-39-r2b`.
2. Wave 2: `e15-39-i1`, `e15-39-i2`.
3. Wave 3: `e15-39-d2`; `e15-39-r3` once S0 is recorded.
4. Wave 4: `e15-39-i3`.
5. Operator: S0 any time before wave 3; S4 after deploy.

### Manifest

```bash
make lane-manifest-init TASK=E15-39 LANE_IDS='e15-39-r1 e15-39-i1 e15-39-q1 e15-39-r2a e15-39-r2b e15-39-i2 e15-39-d2 e15-39-r3 e15-39-i3' TASK_PLAN=docs/tasks/15.0/E15-39-description-default-trusted-set-and-serve-pin-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries. Implementation and RED lanes run on remote codex `gpt-6.1-sol`, high effort, FAST tier; one lane per dispatch; each brief embeds its slice block from this plan.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

---

## Consolidated Checklist

**Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried from the handoff DB via `review_findings(review={"operation":"list","status":"open","task_ref":"E15-39"})` or read from `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership and compatibility expectations if any contract is touched.

### Checklist for Slice 1: Seeded default

- [ ] RED lane updates `apps/prototype-description-service/scene/tests/test_description_profiles.py` and `apps/prototype-description-service/scene/tests/test_settings.py`; the renamed and new tests fail and the modules collect.
- [ ] `apps/prototype-description-service/scene/config/profiles.py` defines the seeded default constant; `apps/prototype-description-service/scene/config/settings.py` and `apps/prototype-description-service/api/main.py` read it.
- [ ] `uv run --directory apps/prototype-description-service python -m pytest scene/tests/test_description_profiles.py scene/tests/test_settings.py -q` passes.

### Checklist for Slice 2: Quota guards

- [ ] `apps/prototype-description-service/scene/tests/test_describe_route.py` pins that an unavailable GPU charges no demo quota.
- [ ] `apps/prototype-description-service/scene/tests/test_describe_run_quota.py` pins that a cancelled run keeps its charge.
- [ ] Both mutations were shown red and reverted.

### Checklist for Slice 3: Florence leaves the trusted set

- [ ] RED lanes move trusted-adapter fixtures to gpu_qwen30b and add the untrusted-Florence assertions in `infra/oci/demo/tests/test-describe-gate.sh`, `scripts/deploy/tests/test_preflight_gpu_env.py` and `scripts/deploy/tests/test-smoke-gate.sh`; `scripts/deploy/tests/test_sync_demo_preflight.py` stays green.
- [ ] `infra/oci/demo/lib/describe-gate.sh` trusts only the two GPU profiles and has no Florence kind mapping.
- [ ] `scripts/deploy/preflight-gpu-env.sh` and `infra/oci/README.md` name only the GPU profiles as live adapters.
- [ ] `LC_ALL=C bash infra/oci/demo/tests/test-describe-gate.sh` passes.
- [ ] `LC_ALL=C bash scripts/deploy/tests/test-smoke-gate.sh` passes.
- [ ] `LC_ALL=C uv run --no-project --with pytest python -m pytest scripts/deploy/tests/test_preflight_gpu_env.py scripts/deploy/tests/test_sync_demo_preflight.py -q -p no:cacheprovider` passes.

### Checklist for Slice 4: Env manifest docs

- [ ] `config/env/manifest.d/21-service-vm.toml` and `config/env/manifest.d/40-demo.toml` describe the seeded default and the GPU-only live set.
- [ ] `make env-examples` regenerated the examples and `make env-check` passes.

### Checklist for Slice 5: Serve pin

- [ ] Operator S0 recorded the digest (and any flag correction) as a decision before dispatch.
- [ ] RED lane updates `scripts/test_vlm3_oci_gpu_infra.py` and `apps/prototype-description-service/recognition/tests/scripts/test_gtmr_gpu_runtime_receipts.py`; they fail on the digest and flags.
- [ ] `infra/oci/gpu-cloud-init.yaml` and `infra/oci/INFRA-TOPOLOGY.md` reference the image by digest with explicit flags and no mutable tag.
- [ ] `uv run --no-project --with pytest --with pyyaml python -m pytest scripts/test_vlm3_oci_gpu_infra.py -q` passes.
- [ ] `uv run --directory apps/prototype-description-service python -m pytest recognition/tests/scripts/test_gtmr_gpu_runtime_receipts.py -q` passes.
- [ ] Operator S4 filed `docs/runbooks/evidence/e15-39-cold-start-receipt.json`.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included where tests can mask real behavior.
- [ ] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- Pin the bake pull in `infra/oci/gpu-bake-cloud-init.yaml` to the same digest.

## Success Criteria

| Eval case | Proof |
|---|---|
| GTM-SC-08 | `test_settings_default_profile_is_seeded` and the one-owner test pass |
| GTM-SC-09 | Untrusted-Florence assertions pass in the describe gate, smoke gate (alt provenance) and preflight suites |
| GTM-SC-10 | `test_gpu_cloud_init_pins_runtime_image_by_digest_and_explicit_flags` passes |
| GTM-SC-11 | Operator S4 receipt filed |
| GTM-SC-20 | `test_gpu_unavailable_does_not_consume_demo_quota` and `test_cancelling_a_demo_run_keeps_its_charge` pass, with mutations shown red |

## Canon authority (Canon v0.26.2)

| ID | Rule | Applied in |
|---|---|---|
| SERVE-07 | Gate the served quantization on the evaluated one | Slice 5 digest and explicit flags |
| REF-27 | No unstated environment assumptions or defaults | Slice 1 seeded default; Slice 5 explicit flags |
| PERF-01 | Report latency as percentiles, not averages | S4 records the cold start; E15-40 owns percentiles |
| TEST-15 | Prove a green test can go red | Slice 2 mutations |
