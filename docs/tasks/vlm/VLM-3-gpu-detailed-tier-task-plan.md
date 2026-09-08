# VLM-3. Bursty OCI-GPU Detailed-Description Tier

> **Metadata**
>
> - **Date**: 2026-07-07 EST
> - **Author**: claude-opus-4-8
> - **Realigned**: 2026-07-12 (VLM-REALIGN-01, Claude Fable 5) — slices 1–6 implemented and merged to `main` (`ca3304a4`…`b8847945`, hardening `4739a319`/`00413253`/`7e9dbe31`); all quality evidence is still **pending stubs**. The A10 burst instance is now provisioned by OCI, unblocking Slice 7 (live evidence + activation), which is the only remaining work. Anchor drift vs. current code is cataloged in `VLM-REALIGN-01-anchor-audit-20260712.md`; stale anchors below are corrected in place.
> - **Project**: `apps/prototype-description-service` (+ `infra/oci`)
> - **Task ID**: `VLM-3`
> - **Target Branch**: `feature/vlm-3` (merged; Slice 7 continues on `feature/vlm-3b-activation`)
> - **Review Coverage Target**: 2

---

## VLM-3. Bursty OCI-GPU Detailed-Description Tier

## Objective

Add a **bursty, scale-to-zero GPU serving path** for the detailed-description tier: pick the best GPU-served VLM by bake-off, expose it as a real `DescriptionAdapter` behind the existing profile protocol, and drive it via an async describe path on an on-demand OCI GPU instance that costs ~$0 between bursts. When the GPU is cold/unavailable, degrade to the CPU tier with a provisional answer.

## Intake (new feature)

- **Scope one-pager**: `docs/scopes/gpu-detailed-tier-oci-bursty-scope.md`
- **Key Q&A decisions**: `decision #1568` (`scope_intake_opencv5_and_oci_bursty_gpu_tier`); scope slice-complete `#1569`; plan-analyze findings `VLM3-PA-01..08` (all fixed).
- **Not-Doing**: hosted-API tier (E20-11 track); always-on GPU; snapshot/CUDA-checkpoint restore infra; OpenCV 5 incumbent dependency swap; context-fusion caption architecture; PG18/19; LLM-judge implementation; CPU Tier-A brand detection (E20-BRAND-A).

## Problem Statement

The detailed tier (VLM-2B winner **Qwen3-VL-4B-Instruct**) runs **~207 s/img on the A1 CPU** — a 100-image batch is ~5.75 h, and quality is capped by a 4B model on 4 ARM cores. We need a GPU tier that is fast for batch, privacy-preserving (in-tenancy), and cheap when idle.

**Realignment 2026-07-12 — what remains.** The serving path is built: `GpuRemoteDescriptionAdapter`, the async describe routes, the volatile job store/worker, the terraform `acx_gpu_burst` instance (provisioned `STOPPED`), and the `infra/oci/gpu_lifecycle/` controller + reaper are all on `main`. What does NOT exist is **evidence**: every Slice-1 spike measurement is `null` (`VLM-3-gpu-spike-2026-07-08.json`, `status=local_infra_scaffold_pending_live_oci_measurement`), all seven Slice-2 bake-off REPORTs are `kind=pending_report` stubs, and the Slice-3 memo is explicitly **provisional**. Treating those stubs as done would ship an unmeasured tier past a red gate [RLSE-02]. With the A10 now provisioned, Slice 7 turns the stubs into measurements and activates the tier end-to-end.

## Constraints

- **Data residency**: image bytes + identities must stay in the OCI tenancy (same VCN as the A1 service). No off-provider egress → OCI GPU, not serverless (serverless is the documented fallback only).
- **Bulkhead (Release-It)**: the GPU burst pool must be isolated so a spike cannot starve the always-on A1 recognition/description service.
- **Greenfield**: no migrations; schema changes go directly in `db/migrations/versions/001_identity_schema.py`. `extra="forbid"` response/request models require any new field to be declared explicitly.
- **Adapter protocol is the single seam**: the GPU model must satisfy `DescriptionAdapter` (`scene/application/description_adapter.py:35`) and return `AdapterResult` — no bespoke describe path.
- **Cost is not the deciding axis** (~$0.20–0.40/100-img batch either way); time + residency are. GPU per-img time (~5 s est) is unmeasured — a Slice-1 spike deliverable.
- **Concurrency 1**, one model resident at a time, off the demo path.

## Workflow Principles

- **Measure before adopting**: no model is picked without a bake-off REPORT (mirror VLM-2B).
- **Reuse the remote-adapter template**: model the GPU adapter on `HostedProviderDescriptionAdapter`, not a new pattern.
- **Provisional-before-perfect**: a CPU answer now beats a GPU answer in 90 s of cold-start; upgrade in place.
- **Steady-state reclaimer**: every spun-up GPU instance has a bounded idle-reaper; no unbounded billing/storage leak.

## Terminology

- **Burst**: one batch of detailed-description jobs served by a single GPU warm-up→drain→stop cycle.
- **Warm-start**: time from a *stopped* (not terminated) GPU instance to first-token-ready (target p95 ≤ 90 s).
- **Provisional / final**: describe-result `tier` — `provisional_cpu` (Florence/Qwen fallback) superseded by `final_gpu`.

## Current State Analysis (realigned 2026-07-12)

- **Landed on `main`** (slices 1–6): `GpuRemoteDescriptionAdapter` (`scene/infrastructure/vlm/gpu_remote_adapter.py:105`) with private-endpoint policy (`deps._is_private_gpu_endpoint`, `ACX_GPU_ENDPOINT_ALLOWLIST`); `GPU_QWEN30B` profile (`profiles.py:100`, `available=True`) resolved by `get_description_adapter` (`scene/interface_adapters/http/deps.py:155` — note: `http/deps.py`, not `routers/deps.py`); async routes `POST /describe/async` (`describe.py:553`) + `GET /describe/jobs/{job_id}` (`describe.py:623`) over `InMemoryDescribeJobStore` + `description_worker.run_describe_job`; `tier`/`result_generation` on `VisualFactsResponse` (`responses.py:129-130`) and optional `tier` hint on `DescribeImageEnvelope` (`requests.py:122`); terraform `oci_core_instance.acx_gpu_burst` (`main.tf:235`, shape var default `VM.GPU.A10.1`) with outputs `gpu_endpoint_url`/`gpu_private_ip`/`gpu_instance_id`; `infra/oci/gpu_lifecycle/` controller + idle reaper; llama.cpp `server-cuda` golden-image cloud-init serving port 8000.
- **Provisioned (new, 2026-07-12)**: the OCI A10 burst instance exists in the tenancy (quota granted after `MAINT-oci-a10-quota-request-20260710` unblocked). It has not yet served a live request from this stack.
- **Missing (Slice 7 scope)**: every measurement — spike artifact values are `null`, the seven `VLM-3-bakeoff-*-report.json` files are `kind=pending_report` stubs, the decision memo is provisional, the license verdict is open, and the activation preconditions (memo §Activation) have never been executed end-to-end.
- **Known debt routed elsewhere**: the volatile in-memory job store is consolidated onto the durable `describe_run` tables by **VLM-5** (deferred finding VLMRP-S4-05); do not extend `describe_jobs.py` here.

## Target Outcome

A tenant opts a media item (or a batch) into detailed description → the request is **enqueued** → an OCI GPU instance **warm-starts from stopped**, serves the winning VLM via the GPU adapter, and results land as `final_gpu`. If warm-start exceeds budget, the client gets a `provisional_cpu` answer immediately, upgraded later. The instance **stops itself** when the queue drains; an idle-reaper guarantees no leak. The A1 service is never degraded by a GPU burst. OWLv2 Tier B reuses the same burst pool to enrich `ContextPack.brands`.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`; infra: `docs/epics/v0.3.1/self-hosting-epic.md`.
- Contracts: `docs/workbay/contracts/image-description-api.md`; scope: `docs/scopes/gpu-detailed-tier-oci-bursty-scope.md`.
- Handoff/MCP: task `VLM-3`; decision `#1568`; VLM-2B decision memo `docs/tasks/vlm/VLM-2B-detailed-tier-decision-memo.md`.
- Code seams: `scene/application/description_adapter.py`, `scene/config/profiles.py`, `scene/interface_adapters/http/deps.py`, `scene/infrastructure/provider/hosted_provider_adapter.py`, `scripts/eval_harness/bakeoff.py`, `infra/oci/main.tf`, `infra/oci/gpu_lifecycle/`.
- Anchor audit: `docs/tasks/vlm/VLM-REALIGN-01-anchor-audit-20260712.md` (current line numbers for every seam above).
- GTM: `docs/gtm/altcontext-productization-launch-plan.md` — the GPU tier stays **off the demo path** (Phase 0 unaffected); it backs the paid detailed-tier claim and the ~$0-idle cost posture that keeps the OCI free-tier bootstrap honest. Launch-facing quality claims about the detailed tier are blocked on Slice 7 evidence, not on more code.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Describe response (`VisualFactsResponse`, `responses.py:75`) | backend | `docs/workbay/contracts/image-description-api.md` | Add `tier` (`provisional_cpu`/`final_gpu`) + `result_generation` fields (`extra="forbid"` → explicit) | No (greenfield; WP reads new field) | schema test + fixture |
| Describe request (`DescribeImageEnvelope`, `requests.py:100`) | backend/proxy | same | Add optional `tier` request hint (opt into GPU) | No | schema test |
| Describe adapter (`DescriptionAdapter`, `description_adapter.py:35`) | backend | protocol | New concrete GPU adapter; no protocol change | No | `isinstance`/`@runtime_checkable` test |
| GPU serving endpoint (new outbound base URL) | infra/backend | none | New `ACX_GPU_ENDPOINT_URL`; adapter POSTs to a GPU llama.cpp/vLLM server | N/A (new) | live spike + adapter unit test w/ MockTransport |
| OCI infra (`infra/oci/main.tf`) | infra | A1-only Terraform | New GPU instance resource + cloud-init + lifecycle controller | No | `terraform validate` + spike boot |

## Proposed Solution

Deliver in six slices: (1) prove the OCI GPU host + golden-image warm-start and measure it; (2) bake-off the candidates through the existing eval harness pointed at the GPU endpoint; (3) decision memo; (4) wire the winner as a real GPU `DescriptionAdapter` behind the profile resolver (synchronous first, endpoint-backed, mirroring `HostedProviderDescriptionAdapter`); (5) add the net-new async describe path + OCI bursty lifecycle controller + CPU-provisional degrade + idle-reaper + A1 bulkhead; (6) OWLv2 Tier B on the burst pool → `ContextPack.brands` (gated on E20-BRAND-A). Slices 1–4 ship value independently; slice 6 carries the cross-scope edge.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| infra | `infra/oci/main.tf` | New `oci_core_instance` GPU resource defaulting to **`VM.GPU.A10.1` (24 GB)**, `variables.tf` shape var (override to `VM.GPU.A100.1`/`VM.GPU.A10.2` for headroom), GPU `cloud-init` (golden-image + weights bake) |
| infra | `infra/oci/gpu_lifecycle/` (landed) | Spin-on-queue → warm-per-burst → stop-on-idle controller + idle-reaper (OCI SDK) |
| tooling | `scripts/eval_harness/bakeoff.py` | Reuse `BakeoffClient`/`main` against the GPU `--endpoint`; add candidate model ids; no fork |
| docs | `docs/tasks/vlm/VLM-3-gpu-detailed-tier-decision-memo.md` (new) | Bake-off winner + measured GPU latency/RSS + license |
| backend | `scene/infrastructure/vlm/gpu_remote_adapter.py` (new) | `GpuRemoteDescriptionAdapter(DescriptionAdapter)`; POSTs to `ACX_GPU_ENDPOINT_URL`; returns `AdapterResult`; models on `hosted_provider_adapter.py` |
| backend | `scene/config/profiles.py` | Flip/add a GPU `ProfileSpec` (`available=True`, endpoint, model id/version) for the winner |
| backend | `scene/interface_adapters/http/deps.py` | Add `adapter_kind is GPU` branch in `get_description_adapter` (`:155`) + opt-in gate (landed) |
| backend | `scene/config/settings.py` | Add `ACX_GPU_ENDPOINT_URL` (+ opt-in flag) to `DescriptionSettings` (`:19`) |
| backend | `scene/interface_adapters/http/schemas/responses.py` | Add `tier` + `result_generation` to `VisualFactsResponse` (`:75`) |
| backend | `scene/interface_adapters/http/schemas/requests.py` | Add optional `tier` hint to `DescribeImageEnvelope` (`:100`) |
| backend | `scene/interface_adapters/http/routers/describe.py` | New async routes `POST /describe/async` (enqueue → `job_id`) + `GET /describe/jobs/{job_id}` (poll → `DescribeJobResult`) |
| backend | `scene/interface_adapters/http/schemas/responses.py` | New `DescribeJobResult` model (`job_id`, `status`, `tier`, `result_generation`, optional `visual_facts`) |
| backend | `scene/application/describe_jobs.py` (new) | Describe job store + enqueue + retrieval (net-new; no describe queue exists) |
| backend | `scene/application/description_worker.py` (new) | Async describe worker draining the job store to the GPU adapter; CPU-provisional supersede |
| tests | `scene/tests/test_gpu_remote_adapter.py`, `test_describe_jobs.py`, `test_describe_tier_degrade.py` (new) | Adapter (MockTransport), job store, provisional→final supersede |

## Related Files

| File | Note |
| --- | --- |
| `scene/infrastructure/provider/hosted_provider_adapter.py` | Template for the remote/endpoint-backed GPU adapter |
| `scene/infrastructure/vlm/unavailable_adapter.py:23` | Current placeholder the GPU branch replaces |
| `scene/domain/description.py:12` | `DescriptionAdapterKind.GPU` already exists |
| `scripts/eval_harness/remote_client.py:54` | `RemoteSceneClient` base for the bake-off transport |
| `scene/application/settings/vlm.py:29` | `worker_concurrency`/`async_inline` knobs (no worker yet) |
| `docs/tasks/19.0/E19-1-florence-large-async-worker-impl-notes.md` | Prior async-describe-worker design notes |

## Verification Strategy

- Deterministic tests:
  - `.venv/bin/python -m pytest scene/tests/test_gpu_remote_adapter.py scene/tests/test_describe_jobs.py scene/tests/test_describe_tier_degrade.py -q`
  - `.venv/bin/python -m pytest scene/tests/test_eval_harness_bakeoff.py -q` (harness reuse unaffected)
- Runtime-parity / environment checks:
  - Slice 1 spike: warm-start p95 + one-candidate s/img on a live OCI GPU instance; emit E19-1-format JSON artifact.
  - `cd infra/oci && terraform validate` for the GPU resource.
- Contract/fixture verification:
  - `VisualFactsResponse` schema fixture asserts `tier`/`result_generation` present; `@runtime_checkable` `isinstance(GpuRemoteDescriptionAdapter(), DescriptionAdapter)`.
- Manual verification:
  - Opt a media item into GPU tier → confirm `final_gpu` result; kill/cold GPU → confirm `provisional_cpu` then upgrade; confirm instance stops + idle-reaper leaves nothing running.

## Slice Delivery

### Slice 1: OCI GPU spike + golden image

> **Status (2026-07-12): scaffold landed (`ca3304a4`) — terraform GPU resource, cloud-init, spike artifact schema. All measurement values are `null`; live measurement moved to Slice 7a.**

**Goal**: Prove an OCI GPU instance can warm-start from stopped within budget and measure one candidate's s/img.

Changes:
- New `oci_core_instance` GPU resource (`infra/oci/main.tf`, default **`VM.GPU.A10.1` / 24 GB**) + shape var (`variables.tf`) + GPU cloud-init. This slice's golden image bakes **one measurement candidate** — **Qwen3-VL-30B-A3B-Instruct @ Q4 GGUF** (the a-priori favorite, ~18 GB, proves the 24 GB fit) — to time warm-start (VLM3-PR-03); the **production golden image (the bake-off winner)** is built in Slice 4/5 after the decision memo.
- Bench script (E19-1 JSON format) capturing cold-boot, stopped→warm-start, model-load, and s/img; **confirm A10-24 GB fit + in-region A10 quota** (and whether A100/L40S is reachable for the headroom candidates) + note serverless-GPU availability.

Proof:
- Committed spike artifact `docs/tasks/vlm/VLM-3-gpu-spike-<date>.json`; `terraform validate` passes; warm-start p95 recorded vs the 90 s target.

### Slice 2: GPU bake-off

> **Status (2026-07-12): seven `kind=pending_report` stubs committed (`a3bcb718`). No candidate has been scored on real hardware; the live bake-off is Slice 7b.**

**Goal**: Score the GPU candidates on the VLM-2B corpus via the existing harness.

**Hardware target (the binding constraint is VRAM/"space"):** the bursty scale-to-zero shape is **`VM.GPU.A10.1` — a single NVIDIA A10, 24 GB VRAM** (cheapest OCI GPU VM, easy start/stop). Budget ~20 GB usable after KV-cache + image tokens. Headroom option if the bake-off demands it: **`VM.GPU.A100.1` (40 GB)** or `VM.GPU.A10.2` (48 GB), at higher $/hr. Every candidate below is annotated for A10-24 GB fit; anything that only fits a bigger shape is flagged.

**Candidate slate (refreshed + hardware-constrained 2026-07-07; prune to a runnable set at spike time):**

- **Tier 1 — headline: 30B-class quality *inside* 24 GB via MoE-A3B + quant.** MoE weights size to **total** params (all experts resident), but only ~3.3B activate per token → low s/img at 30B quality.
  - **Qwen3-VL-30B-A3B-Instruct @ Q4 GGUF** (~18 GB — **fits A10 24 GB** ✅; 30.5B total / 3.3B active; llama.cpp + vLLM; strong grounding + agentic; same family as the CPU winner) — **the a-priori favorite for the A10 bursty tier.**
  - **Kimi-VL-A3B-2506 @ Q4/Q8** (~16B total; Q4 ~10 GB / Q8 ~17 GB — **fits** ✅; Moonshot, MIT).
  - *InternVL3.5-30B-A3B @ Q4 (~18 GB, fits ✅) — include only if the spike shows GGUF/vLLM support is mature; else defer.*
- **Tier 2 — dense models that fit A10 24 GB at bf16/light quant.**
  - **Qwen3-VL-8B-Instruct** (bf16 ~16 GB ✅ / Q8 ~9 GB) — Apache-2.0; strongest dense name-weaving in-family.
  - **InternVL3.5-8B** (bf16 ~16 GB ✅), **InternVL3.5-14B @ Q8** (~15 GB ✅; bf16 ~28 GB ❌ needs A100).
  - **Molmo-7B-D** (bf16 ~15 GB ✅; AllenAI; best-in-class pointing/grounding → phrase-box name placement).
  - **Llama-3.2-Vision-11B @ Q8** (~12 GB ✅; bf16 ~22 GB tight — ⚠ Llama license, non-OSI, flag for a public demo).
- **Tier 3 — reference baselines (per operator request; both fit A10 24 GB).**
  - **MiMo-VL-7B-RL** (8B; bf16 ~16 GB tight ✅ / AWQ-INT4 safer; Xiaomi; E19-1's retained GPU-tier reference — beats Phi-4, MMMU 70.6, MIT, Qwen2.5-VL arch → vLLM-native; run `/no_think`).
  - **Phi-4-multimodal** (5.6B; ~11 GB ✅; Microsoft; the original `gpu_phi4` stub baseline — MMMU 55.1, mid-tier; anchors the "why we moved past the stub" comparison).
- **Explicitly OUT for the A10-24 GB bursty tier (too big even quantized — revisit only on A100/L40S):** **GLM-4.6V** (GLM-4.5V-class ~106B-A12B MoE ≈ ~55 GB @ Q4), **Qwen3-VL-32B** (Q4 ~18–20 GB fits but leaves no context headroom → A100 only for bf16), and all 78B/235B/241B giants.

Changes:
- Serve each selected candidate on the GPU; run `scripts/eval_harness/bakeoff.py --endpoint <gpu-url> --model-id <id> [--no-think]` per candidate (reuse `BakeoffClient`/`fetch_run_record`, no fork); score via `report.build_reports`. Reasoning-tuned/Thinking variants run with `/no_think` for alt-text shape, identical decoding across candidates.

Proof:
- Per-candidate `acx-eval/v1` REPORT artifacts under `docs/tasks/vlm/`; deterministic re-score bit-identical; comparison table (incl. license + MoE-vs-dense serving cost) assembled.

### Slice 3: Decision memo

> **Status (2026-07-12): provisional memo landed (`e8cb8a1e`) naming Qwen3-VL-30B-A3B-Instruct Q4 GGUF. Promotion to final + license verdict is gated on Slice 7b measured REPORTs — a provisional memo is a red gate, not a soft yellow [RLSE-02].**

**Goal**: Pick one GPU detailed-tier model with evidence.

Changes:
- `docs/tasks/vlm/VLM-3-gpu-detailed-tier-decision-memo.md` — winner + insertion/Must-Right/Easy-Wrong + measured GPU latency/RSS + CPU→GPU speedup + license verdict.

Proof:
- Memo names exactly one winner, cites the Slice-2 REPORTs and Slice-1 latency artifact.

### Slice 4: GPU adapter + profile/resolver wiring (synchronous)

> **Status (2026-07-12): implemented & merged (`ced38052`; endpoint policy hardened `4739a319`). Adapter, `GPU_QWEN30B` profile, resolver branch, schema fields, and tests are on `main`.**

**Goal**: Serve the winning model through the profile protocol, synchronously, endpoint-backed.

Changes:
- New `GpuRemoteDescriptionAdapter` (`scene/infrastructure/vlm/gpu_remote_adapter.py`) implementing `DescriptionAdapter`, POSTing to `ACX_GPU_ENDPOINT_URL`, returning `AdapterResult` (model on `hosted_provider_adapter.py`).
- Add a GPU `ProfileSpec` (`profiles.py`, `available=True`, winner id/version) + `adapter_kind is GPU` branch + opt-in gate in `get_description_adapter` (`deps.py`); add `ACX_GPU_ENDPOINT_URL` to `DescriptionSettings`.
- Add `tier`/`result_generation` to `VisualFactsResponse` and optional `tier` hint to `DescribeImageEnvelope`.

Proof:
- `pytest test_gpu_remote_adapter.py` (MockTransport) green; `isinstance(..., DescriptionAdapter)` true; schema fixture asserts new fields; a describe call with `ACX_DESCRIPTION_ADAPTER=<gpu profile>` returns `tier=final_gpu`.

### Slice 5: Bursty async path + lifecycle + degrade

> **Status (2026-07-12): implemented & merged (`7856c302`; reaper/NAT hardened `00413253`). The job store is the volatile in-memory one by design; its consolidation onto the durable `describe_run` tables is VLM-5's whole scope.**

**Goal**: Enqueue describe jobs, warm the GPU per burst, degrade to CPU-provisional, and reap idle instances.

> **May split into reviewable sub-slices (VLM3-PR-04):** (5a) job store + async worker; (5b) OCI lifecycle controller + reaper; (5c) CPU-provisional degrade + supersede. Each has a separable proof.

Changes:
- **Async describe API surface (net-new — describe is synchronous today, describe.py:192):** an enqueue route `POST /describe/async` → returns `{job_id}`; a poll route `GET /describe/jobs/{job_id}` → returns a `DescribeJobResult` (`job_id`, `status` ∈ `queued|running|provisional|final|failed`, `tier`, `result_generation`, `visual_facts?`). The synchronous `VisualFactsResponse.tier` (Slice 4) stays for inline calls; the async job-result model is distinct.
- Net-new describe job store + enqueue + retrieval (`scene/application/describe_jobs.py`) and async worker (`scene/application/description_worker.py`) draining to the GPU adapter.
- **OCI lifecycle controller (`infra/oci/gpu_lifecycle/`) runs out-of-band (VLM3-PR-02):** a small OCI-SDK process/cron on the **A1 host** (or OCI Functions) — never on the GPU instance it stops, and decoupled from the synchronous request path so it cannot block or starve the A1 service. Spin-on-queue-depth → warm-per-burst → stop-on-idle; bounded **idle-reaper** + orphaned-instance/boot-volume GC.
- CPU-provisional degrade + supersede contract: `tier` transitions `provisional_cpu`→`final_gpu` by `media_id`, monotonic `result_generation`, delivered via the `GET /describe/jobs/{job_id}` poll channel; GPU pool bulkheaded from the A1 service.

Proof:
- `pytest test_describe_jobs.py test_describe_tier_degrade.py` green (enqueue, provisional-then-final supersede, reaper stops instance with no in-flight work); manual: cold GPU → provisional then upgrade; queue drains → instance stopped, reaper leaves nothing.

### Slice 6: OWLv2 Tier B (open-vocab brand detection)

> **Status (2026-07-12): explicitly deferred (`b8847945`) — still gated on Scope A landing `ContextPack.brands`. No change.**

**Goal**: Enrich `ContextPack.brands` from GPU open-vocab detection.

Changes:
- OWLv2 served on the burst pool; confirmed instances → `ContextPack.brands` (the field is **owned by E20-BRAND-A / Scope A**).

Proof:
- Detection instances flow to `ContextPack.brands` and name a brand in a caption; **gated on `ContextPack.brands` landing (Scope A)** — deferred until then.

### Slice 7 (added 2026-07-12): Live evidence + tier activation on the provisioned A10

**Goal**: Convert every pending stub into a measured artifact and prove the whole bursty pipeline end-to-end on the real instance — the vertical slice that makes the GPU tier launch-claimable. This slice is evidence + configuration + bench tooling only; it requires no service code changes (any service-code gap it exposes is a finding, not silent scope growth).

**Execution identity**: Slice 7 runs as task **`VLM-3B`** on branch `feature/vlm-3b-activation` (`make task-start TASK=VLM-3B OBJECTIVE="VLM-3 Slice 7 live evidence + GPU tier activation"`) — VLM-3 itself is archived; the pre-merge gate attaches to VLM-3B.

**7a — Live spike bench.** Start `acx_gpu_burst`; write and commit the bench script (new, `scripts/gpu_spike_bench.py` — no bench exists today; `scripts/test_vlm3_oci_gpu_infra.py` is an infra test, not a bench) capturing cold-boot, stopped→warm-start (p95 vs the 90 s target — report percentiles, not means [PERF-01]), model-load, and s/img for the baked candidate, emitting the E19-1 JSON fields of the spike artifact; fill `VLM-3-gpu-spike-2026-07-08.json` (or a dated successor) with real values and flip its `status`; record A10 quota fields as confirmed.

Proof: bench script committed; spike artifact has zero `null` measurement values; warm-start p95 stated vs target with an explicit pass/fail.

**7b — Live bake-off + final memo.** Serve a pruned candidate slate (the a-priori favorite plus the strongest Tier-2 dense fit and the two Tier-3 baselines is sufficient; name any slate cut explicitly — a silent prune reads as full coverage) through `bakeoff.py --endpoint` against the live instance; replace the `kind=pending_report` stubs with measured `acx-eval/v1` REPORTs; deterministic re-score bit-identical; promote the decision memo provisional→final, including the downloaded-artifact license verdict (public-demo distribution is blocked on it). **Bench budget (the A10 bills while running):** cap each candidate at a stated wall-clock (default 2 h) and the whole bake-off at one operator-approved budget line (default ≤ 12 h GPU-on time); on overrun, stop, commit partial REPORTs with the cut named, and decide from what was measured [PERF-07], [RES-07]; the OB-8 budget alarm (GTM launch plan §9) is the backstop, not the bound.

Proof: winner named from measured REPORTs; memo cites the 7a latency artifact; license verdict recorded; GPU-on wall-clock reported vs the budget.

**7c — Activation runbook + burst E2E proof.** The canonical activation steps are the memo's §Activation preconditions plus `infra/oci/GPU-BURST-PROVISIONING.md` — follow them, don't restate them here [REF-19]. In order: terraform outputs → `ACX_GPU_ENDPOINT_URL` (private IP form), `ACX_DESCRIPTION_ADAPTER=gpu_qwen30b`, allowlist behavior verified fail-closed, reaper wired on a timer with `--load-dir /run/acx-write` (WBUX6-MRG-02 replaced the single-file `--load-json` flag with a directory of per-environment `<load-dir>/<environment>/describe-load.json` snapshots; the old flag no longer parses). Then the burst proof: enqueue one media item cold → observe `provisional_cpu` → GPU warm-start → `final_gpu` supersede → queue drains → instance `STOPPED` by the reaper with nothing orphaned. Define the stop criteria before activation (warm-start p95 budget, error-rate floor) and the rollback (unset the adapter env → tier reverts to CPU; no data migration involved) [RLSE-07], [RLSE-08]. A GPU burst must leave A1 `/health` green throughout (bulkhead). Sequencing note: if VLM-5 merges first, the load-JSON producer becomes the `describe_load` module (file format unchanged) — verify the memo §Activation item 5 wording is updated by whichever task lands second.

Proof: one recorded end-to-end burst transcript (timestamps: enqueue → provisional → final → STOPPED); reaper leaves no running instance or orphaned boot volume (billing-leak check is part of done, not ops folklore); rollback exercised once (unset env, describe still serves CPU tier).

---

## Consolidated Checklist

### Context and Ownership

- [x] Loaded the scope note, VLM-2B decision memo, adapter protocol, and profile resolver before editing.
- [x] Recorded the describe response/request contract change (`tier`/`result_generation`) and its WP-read compatibility.

### Checklist for Slice 1: OCI GPU spike + golden image (scaffold landed `ca3304a4`)

- [x] GPU `oci_core_instance` + shape var + GPU cloud-init (golden image, weights baked); `terraform validate` passes.
- [x] Committed E19-1-format spike artifact schema.
- [ ] ~~Spike bench live values~~ → moved to Slice 7a.

### Checklist for Slice 2: GPU bake-off (stubs landed `a3bcb718`)

- [x] Stub REPORT artifacts + candidate slate committed.
- [ ] ~~Live candidate scoring~~ → moved to Slice 7b.

### Checklist for Slice 3: Decision memo (provisional landed `e8cb8a1e`)

- [x] Provisional memo names the implementation target with A10-fit rationale.
- [ ] ~~Final promotion + license verdict~~ → moved to Slice 7b.

### Checklist for Slice 4: GPU adapter + resolver wiring (merged `ced38052`, `4739a319`)

- [x] `GpuRemoteDescriptionAdapter` implements `DescriptionAdapter`, returns `AdapterResult`, POSTs to `ACX_GPU_ENDPOINT_URL`.
- [x] GPU `ProfileSpec` + `adapter_kind is GPU` branch + opt-in gate in `get_description_adapter`; `ACX_GPU_ENDPOINT_URL` in settings.
- [x] `tier`/`result_generation` on `VisualFactsResponse`; optional `tier` hint on `DescribeImageEnvelope`; schema fixtures updated.
- [x] Adapter + schema tests green.

### Checklist for Slice 5: Bursty async path + lifecycle + degrade (merged `7856c302`, `00413253`)

- [x] Describe job store + enqueue + retrieval + async worker (net-new).
- [x] OCI lifecycle controller (spin-on-queue, warm-per-burst, stop-on-idle) + bounded idle-reaper + orphan GC.
- [x] CPU-provisional degrade + `provisional_cpu`→`final_gpu` supersede (tier + monotonic generation); GPU pool bulkheaded from A1.
- [x] Degrade + job-store + reaper tests green.
- [ ] ~~Manual burst verified~~ → moved to Slice 7c (never ran on real hardware).

### Checklist for Slice 6: OWLv2 Tier B (deferred `b8847945`)

- [ ] OWLv2 on the burst pool → `ContextPack.brands` (gated on Scope A landing `ContextPack.brands`).

### Checklist for Slice 7: Live evidence + tier activation

- [ ] 7a: bench script `scripts/gpu_spike_bench.py` committed; spike artifact fully populated on the live A10 (cold-boot, warm-start p95 vs 90 s, model-load, s/img); quota fields confirmed.
- [ ] 7b: pruned slate served live through `bakeoff.py --endpoint`; stub REPORTs replaced by measured `acx-eval/v1` REPORTs; re-score bit-identical; any slate cut named explicitly; GPU-on wall-clock reported vs the stated budget.
- [ ] 7b: decision memo promoted provisional→final; downloaded-artifact license verdict recorded.
- [x] 7c: activation preconditions activated on the spike host 2026-07-14 (endpoint env, adapter profile, allowlist fail-closed, and manual reaper actuation); production activation pending GPUSMOKE-1 S4 (reaper timer install + backend deploy).
- [x] 7c: one recorded spike-host E2E burst — enqueue → `provisional_cpu` → warm-start → `final_gpu` → drain → reaper `STOPPED`; no orphaned instance/boot volume; A1 `/health` green throughout. Production activation pending S4.
- [x] 7c: stop criteria + rollback stated and exercised on the spike host (unset adapter env → CPU tier serves) [RLSE-07], [RLSE-08]; production activation pending S4.

## Review Readiness

- [ ] No boundary-touching change (describe response/request, adapter, GPU endpoint, OCI infra) left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity: the live GPU warm-start + s/img spike is captured (tests alone cannot prove GPU latency/lifecycle).
- [ ] Handoff decision records the change, verification, and the response-contract implication per slice.

## Stretch Goals

- [ ] Snapshot / CUDA-checkpoint warm-start to approach serverless sub-minute start (deferred DIY; Not-Doing in MVP).
- [ ] OKE GPU node-pool scale-to-zero as an alternative to the stop-not-terminate controller.

## Success Criteria

- [ ] A GPU candidate is picked by a committed bake-off memo backed by **measured** (not stub) REPORTs + a measured latency/RSS artifact (Slice 7b) [RLSE-02].
- [x] A describe request routed to the GPU profile returns `tier=final_gpu` through the unchanged `DescriptionAdapter` protocol (test-proven on `main`; activated on the spike host 2026-07-14; production activation pending S4).
- [x] A burst warm-started the provisioned OCI GPU instance from stopped within the stated spike-host budget, then stopped it; the manual idle-reaper proof left no running/orphaned instance or boot volume (activated on the spike host 2026-07-14; production reaper timer install pending S4).
- [x] Cold/unavailable GPU yielded a `provisional_cpu` answer later superseded by `final_gpu` without failing the request, while A1 remained healthy (activated on the spike host 2026-07-14; production backend deploy pending S4).
- [x] Rollback is stated and was exercised on the spike host (adapter env unset → CPU tier), with named stop criteria [RLSE-07], [RLSE-08]; production activation pending S4.
