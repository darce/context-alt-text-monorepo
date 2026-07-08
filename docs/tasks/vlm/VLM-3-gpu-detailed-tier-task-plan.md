# VLM-3. Bursty OCI-GPU Detailed-Description Tier

> **Metadata**
>
> - **Date**: 2026-07-07 EST
> - **Author**: claude-opus-4-8
> - **Project**: `apps/prototype-description-service` (+ `infra/oci`)
> - **Task ID**: `VLM-3`
> - **Target Branch**: `feature/vlm-3`
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

The detailed tier (VLM-2B winner **Qwen3-VL-4B-Instruct**) runs **~207 s/img on the A1 CPU** — a 100-image batch is ~5.75 h, and quality is capped by a 4B model on 4 ARM cores. Describe today is **synchronous, in-process, CPU-only** (`get_description_adapter` resolves Florence/seeded; the `GPU` adapter kind exists but has no concrete adapter and falls through to `UnavailableDescriptionAdapter`). There is **no async describe path** and **no GPU host** (all OCI infra is `VM.Standard.A1.Flex`). We need a GPU tier that is fast for batch, privacy-preserving (in-tenancy), and cheap when idle.

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

## Current State Analysis

- **Works**: describe route (`describe.py:192 /describe/multipart`) → `get_description_adapter` (`deps.py:15`) → `VisualFactsService` → `VisualFactsResponse`; Florence CPU adapter; the full VLM-2A/2B eval harness (`scripts/eval_harness/`).
- **Missing / stub**: `DescriptionProfile.GPU_PHI4` (`profiles.py:87`, `available=False`); no `adapter_kind is GPU` branch in `deps.py` (GPU → Unavailable); **no async describe worker / job store** (only `recognition/worker/scan_worker.py`, clustering-only); **no GPU host** (`infra/oci/main.tf:114`, A1 only); no `ACX_GPU_ENDPOINT_URL`.
- **Misleading**: `vlm.py:29-30` `worker_concurrency`/`async_inline` knobs exist with no worker behind them — do not assume an async path exists.

## Target Outcome

A tenant opts a media item (or a batch) into detailed description → the request is **enqueued** → an OCI GPU instance **warm-starts from stopped**, serves the winning VLM via the GPU adapter, and results land as `final_gpu`. If warm-start exceeds budget, the client gets a `provisional_cpu` answer immediately, upgraded later. The instance **stops itself** when the queue drains; an idle-reaper guarantees no leak. The A1 service is never degraded by a GPU burst. OWLv2 Tier B reuses the same burst pool to enrich `ContextPack.brands`.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`; infra: `docs/epics/v0.3.1/self-hosting-epic.md`.
- Contracts: `docs/workbay/contracts/image-description-api.md`; scope: `docs/scopes/gpu-detailed-tier-oci-bursty-scope.md`.
- Handoff/MCP: task `VLM-3`; decision `#1568`; VLM-2B decision memo `docs/tasks/vlm/VLM-2B-detailed-tier-decision-memo.md`.
- Code seams: `scene/application/description_adapter.py`, `scene/config/profiles.py`, `scene/interface_adapters/http/routers/deps.py`, `scene/infrastructure/provider/hosted_provider_adapter.py`, `scripts/eval_harness/bakeoff.py`, `infra/oci/main.tf`.

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
| infra | `infra/oci/main.tf` | New `oci_core_instance` GPU resource (VM.GPU.A10/L40S), `variables.tf` shape var, GPU `cloud-init` (golden-image + weights bake) |
| infra | `infra/oci/gpu-lifecycle/` (new) | Spin-on-queue → warm-per-burst → stop-on-idle controller + idle-reaper (OCI SDK) |
| tooling | `scripts/eval_harness/bakeoff.py` | Reuse `BakeoffClient`/`main` against the GPU `--endpoint`; add candidate model ids; no fork |
| docs | `docs/tasks/vlm/VLM-3-gpu-detailed-tier-decision-memo.md` (new) | Bake-off winner + measured GPU latency/RSS + license |
| backend | `scene/infrastructure/vlm/gpu_remote_adapter.py` (new) | `GpuRemoteDescriptionAdapter(DescriptionAdapter)`; POSTs to `ACX_GPU_ENDPOINT_URL`; returns `AdapterResult`; models on `hosted_provider_adapter.py` |
| backend | `scene/config/profiles.py` | Flip/add a GPU `ProfileSpec` (`available=True`, endpoint, model id/version) for the winner |
| backend | `scene/interface_adapters/http/routers/deps.py` | Add `adapter_kind is GPU` branch in `get_description_adapter` (`:15`) + opt-in gate (mirror hosted `:38`) |
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

**Goal**: Prove an OCI GPU instance can warm-start from stopped within budget and measure one candidate's s/img.

Changes:
- New `oci_core_instance` GPU resource (`infra/oci/main.tf`) + shape var (`variables.tf`) + GPU cloud-init. This slice's golden image bakes **one measurement candidate's** weights only, to time warm-start (VLM3-PR-03); the **production golden image (the bake-off winner)** is built in Slice 4/5 after the decision memo.
- Bench script (E19-1 JSON format) capturing cold-boot, stopped→warm-start, model-load, and one-candidate s/img; confirm OCI GPU shape/quota in-region + note serverless-GPU availability.

Proof:
- Committed spike artifact `docs/tasks/vlm/VLM-3-gpu-spike-<date>.json`; `terraform validate` passes; warm-start p95 recorded vs the 90 s target.

### Slice 2: GPU bake-off

**Goal**: Score every GPU candidate on the VLM-2B corpus via the existing harness.

Changes:
- Serve each candidate (Qwen3-VL-8B/-32B, InternVL3-8B/-14B, Molmo-7B-D, Llama-3.2-Vision-11B) on the GPU; run `scripts/eval_harness/bakeoff.py --endpoint <gpu-url>` per candidate (reuse `BakeoffClient`/`fetch_run_record`, no fork); score via `report.build_reports`.

Proof:
- Per-candidate `acx-eval/v1` REPORT artifacts under `docs/tasks/vlm/`; deterministic re-score bit-identical; comparison table assembled.

### Slice 3: Decision memo

**Goal**: Pick one GPU detailed-tier model with evidence.

Changes:
- `docs/tasks/vlm/VLM-3-gpu-detailed-tier-decision-memo.md` — winner + insertion/Must-Right/Easy-Wrong + measured GPU latency/RSS + CPU→GPU speedup + license verdict.

Proof:
- Memo names exactly one winner, cites the Slice-2 REPORTs and Slice-1 latency artifact.

### Slice 4: GPU adapter + profile/resolver wiring (synchronous)

**Goal**: Serve the winning model through the profile protocol, synchronously, endpoint-backed.

Changes:
- New `GpuRemoteDescriptionAdapter` (`scene/infrastructure/vlm/gpu_remote_adapter.py`) implementing `DescriptionAdapter`, POSTing to `ACX_GPU_ENDPOINT_URL`, returning `AdapterResult` (model on `hosted_provider_adapter.py`).
- Add a GPU `ProfileSpec` (`profiles.py`, `available=True`, winner id/version) + `adapter_kind is GPU` branch + opt-in gate in `get_description_adapter` (`deps.py`); add `ACX_GPU_ENDPOINT_URL` to `DescriptionSettings`.
- Add `tier`/`result_generation` to `VisualFactsResponse` and optional `tier` hint to `DescribeImageEnvelope`.

Proof:
- `pytest test_gpu_remote_adapter.py` (MockTransport) green; `isinstance(..., DescriptionAdapter)` true; schema fixture asserts new fields; a describe call with `ACX_DESCRIPTION_ADAPTER=<gpu profile>` returns `tier=final_gpu`.

### Slice 5: Bursty async path + lifecycle + degrade

**Goal**: Enqueue describe jobs, warm the GPU per burst, degrade to CPU-provisional, and reap idle instances.

> **May split into reviewable sub-slices (VLM3-PR-04):** (5a) job store + async worker; (5b) OCI lifecycle controller + reaper; (5c) CPU-provisional degrade + supersede. Each has a separable proof.

Changes:
- **Async describe API surface (net-new — describe is synchronous today, describe.py:192):** an enqueue route `POST /describe/async` → returns `{job_id}`; a poll route `GET /describe/jobs/{job_id}` → returns a `DescribeJobResult` (`job_id`, `status` ∈ `queued|running|provisional|final|failed`, `tier`, `result_generation`, `visual_facts?`). The synchronous `VisualFactsResponse.tier` (Slice 4) stays for inline calls; the async job-result model is distinct.
- Net-new describe job store + enqueue + retrieval (`scene/application/describe_jobs.py`) and async worker (`scene/application/description_worker.py`) draining to the GPU adapter.
- **OCI lifecycle controller (`infra/oci/gpu-lifecycle/`) runs out-of-band (VLM3-PR-02):** a small OCI-SDK process/cron on the **A1 host** (or OCI Functions) — never on the GPU instance it stops, and decoupled from the synchronous request path so it cannot block or starve the A1 service. Spin-on-queue-depth → warm-per-burst → stop-on-idle; bounded **idle-reaper** + orphaned-instance/boot-volume GC.
- CPU-provisional degrade + supersede contract: `tier` transitions `provisional_cpu`→`final_gpu` by `media_id`, monotonic `result_generation`, delivered via the `GET /describe/jobs/{job_id}` poll channel; GPU pool bulkheaded from the A1 service.

Proof:
- `pytest test_describe_jobs.py test_describe_tier_degrade.py` green (enqueue, provisional-then-final supersede, reaper stops instance with no in-flight work); manual: cold GPU → provisional then upgrade; queue drains → instance stopped, reaper leaves nothing.

### Slice 6: OWLv2 Tier B (open-vocab brand detection)

**Goal**: Enrich `ContextPack.brands` from GPU open-vocab detection.

Changes:
- OWLv2 served on the burst pool; confirmed instances → `ContextPack.brands` (the field is **owned by E20-BRAND-A / Scope A**).

Proof:
- Detection instances flow to `ContextPack.brands` and name a brand in a caption; **gated on `ContextPack.brands` landing (Scope A)** — deferred until then.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the scope note, VLM-2B decision memo, adapter protocol, and profile resolver before editing.
- [ ] Recorded the describe response/request contract change (`tier`/`result_generation`) and its WP-read compatibility.

### Checklist for Slice 1: OCI GPU spike + golden image

- [ ] GPU `oci_core_instance` + shape var + GPU cloud-init (golden image, weights baked); `terraform validate` passes.
- [ ] Spike bench captures cold-boot, stopped→warm-start, model-load, one-candidate s/img; OCI GPU quota + serverless availability confirmed.
- [ ] Committed E19-1-format spike artifact; warm-start p95 compared to the 90 s target.

### Checklist for Slice 2: GPU bake-off

- [ ] Each candidate served on GPU and run through `bakeoff.py --endpoint` (harness reused, not forked).
- [ ] Per-candidate `acx-eval/v1` REPORT committed; deterministic re-score bit-identical.

### Checklist for Slice 3: Decision memo

- [ ] Decision memo names one winner, cites REPORTs + latency artifact, states license verdict.

### Checklist for Slice 4: GPU adapter + resolver wiring

- [ ] `GpuRemoteDescriptionAdapter` implements `DescriptionAdapter`, returns `AdapterResult`, POSTs to `ACX_GPU_ENDPOINT_URL`.
- [ ] GPU `ProfileSpec` + `adapter_kind is GPU` branch + opt-in gate in `get_description_adapter`; `ACX_GPU_ENDPOINT_URL` in settings.
- [ ] `tier`/`result_generation` on `VisualFactsResponse`; optional `tier` hint on `DescribeImageEnvelope`; schema fixtures updated.
- [ ] Adapter + schema tests green.

### Checklist for Slice 5: Bursty async path + lifecycle + degrade

- [ ] Describe job store + enqueue + retrieval + async worker (net-new).
- [ ] OCI lifecycle controller (spin-on-queue, warm-per-burst, stop-on-idle) + bounded idle-reaper + orphan GC.
- [ ] CPU-provisional degrade + `provisional_cpu`→`final_gpu` supersede (tier + monotonic generation); GPU pool bulkheaded from A1.
- [ ] Degrade + job-store + reaper tests green; manual burst verified.

### Checklist for Slice 6: OWLv2 Tier B

- [ ] OWLv2 on the burst pool → `ContextPack.brands` (gated on Scope A landing `ContextPack.brands`).

## Review Readiness

- [ ] No boundary-touching change (describe response/request, adapter, GPU endpoint, OCI infra) left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity: the live GPU warm-start + s/img spike is captured (tests alone cannot prove GPU latency/lifecycle).
- [ ] Handoff decision records the change, verification, and the response-contract implication per slice.

## Stretch Goals

- [ ] Snapshot / CUDA-checkpoint warm-start to approach serverless sub-minute start (deferred DIY; Not-Doing in MVP).
- [ ] OKE GPU node-pool scale-to-zero as an alternative to the stop-not-terminate controller.

## Success Criteria

- [ ] A GPU candidate is picked by a committed bake-off memo backed by deterministic REPORTs + a measured latency/RSS artifact.
- [ ] A describe request routed to the GPU profile returns `tier=final_gpu` through the unchanged `DescriptionAdapter` protocol.
- [ ] A burst warm-starts an OCI GPU instance from stopped within the stated budget, then stops it; the idle-reaper leaves no running/orphaned instance or boot volume.
- [ ] Cold/unavailable GPU yields a `provisional_cpu` answer that is later superseded by `final_gpu` without failing the request; a GPU burst never degrades the A1 service.
