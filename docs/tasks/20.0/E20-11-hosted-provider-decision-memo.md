# E20-11 — Hosted Provider Benchmark & Governance Decision Memo

> **Metadata**
>
> - **Date**: 2026-07-06
> - **Owning task**: E20-11 (`docs/tasks/20.0/E20-11-hosted-provider-benchmark-and-governance-decision-task-plan.md`)
> - **Status**: FINAL (boundary refined 2026-07-07 — see [§ Amendment](#amendment-2026-07-07--boundary-is-third-party-model-providers-not-self-hosted-gpu))
> - **Disposition enum (canonical)**: `ship | benchmark_only | defer_byok | reject`

## Decision

**Disposition: `reject`.**

Operator governance decision (2026-07-06): the product uses **only self-hosted,
CPU-run models** (Florence-2 via the `local_cpu` adapter, OpenCV/InsightFace on
the recognition side). Image bytes must not leave the Alt Context service
boundary. No hosted third-party provider will be enabled, no provider API key
exists in any deployment, and no paid benchmark run was performed — the
rejection is a boundary/governance posture, not a quality verdict, so paid
evidence would not have changed it.

## What this means in the codebase

- The default profile remains `seeded`/`florence_small`; nothing changed for
  the runtime path.
- The `hosted_gpt4o` profile and `HostedProviderDescriptionAdapter` (E20-11
  Slice 1) remain registered **fail-closed** (`available=False`; resolves to a
  503 `UnavailableDescriptionAdapter` unless `ACX_HOSTED_PROVIDER_OPTIN=1` is
  set server-side). Under `reject`, that opt-in env is never set in any
  environment; the adapter is retained as tested boundary infrastructure so any
  future re-evaluation starts from a fail-closed seam instead of ad-hoc code.
- The eval harness keeps `--provider` / `--cost-per-image` / `--max-cost`
  (benchmark-only capability, spend-capped, eval-tenant-gated). See
  `scripts/eval_harness/README.md` § "Hosted provider matrix (E20-11)".

## Benchmark evidence

None — deliberately. A hosted matrix run requires a provider key and sends the
golden corpus to a third-party subprocessor; both are excluded by the
disposition itself. The measurable-metric scoping analysis (context-independent
caption metrics + latency + cost; `insertion_rate`/`tag_coverage`/`must_right`
structurally inert until VLM-2C populates the golden manifest) is preserved in
the task plan § Proposed Solution for any future re-evaluation.

## Privacy, subprocessor, and retention

- **Boundary**: with `reject`, no code path sends image bytes off-boundary; the
  wire contract still discloses `provider_disclosure.left_service_boundary`
  and would surface any future change.
- **Subprocessor disclosure**: not required — no subprocessor is engaged.
- **BYOK**: not implemented and not deferred-for-later; under `reject` there is
  no BYOK follow-on task.

## Follow-on scope

- **None for hosted providers.** Re-opening requires a new epic-level decision
  that supersedes this memo; the fail-closed seam and the harness `--provider`
  flag are the prepared starting points.
- **E20-7 ledger integration**: moot for provider cost; the harness's
  `latency_s`/cost provenance fields remain available to the ledger follow-on
  for local-profile runs.
- **VLM-2C** golden-manifest population still owns making insertion/named-entity
  metrics measurable for local-profile evals.

## Amendment (2026-07-07) — boundary is third-party model providers, not self-hosted GPU

Operator governance clarification (2026-07-07). The original decision phrased the
posture as "only self-hosted, **CPU-run** models," which conflated two separate
things: **who controls the model** and **what hardware runs it**. The governing
concern is the former. This amendment refines the boundary:

- **The prohibition is on sending image bytes to a third-party-*hosted model* /
  model-provider inference API** (e.g. GPT-4o, Gemini, or any service where a
  third party operates the model, sees the image, and may retain or train on it).
  That remains `reject` — unchanged. `hosted_gpt4o` / `HostedProviderDescriptionAdapter`
  stay registered **fail-closed**; `ACX_HOSTED_PROVIDER_OPTIN` is never set.
- **Running our own self-hosted model (our weights, our code, our control) on a
  GPU is PERMITTED** — whether an on-prem GPU or rented serverless GPU compute
  (e.g. Modal, RunPod Serverless) that executes *our* container running *our*
  Florence-2 weights. The "CPU-run" wording is superseded: GPU execution of a
  self-hosted model is allowed. The model is not a subprocessor's model; the
  provider supplies raw compute, not inference.

**Caveat — rented-GPU infrastructure is still a data subprocessor.** Sending
image bytes to rented GPU infra means bytes transit a third party's hardware,
so a self-hosted-on-rented-GPU deployment MUST: (a) disclose that infra
subprocessor, (b) prefer no-retention / ephemeral-storage terms, and (c) keep
the `provider_disclosure.left_service_boundary` wire field truthful. Wholly
on-prem GPU has no such subprocessor. This caveat does not block the path; it
scopes the controls.

**What this unblocks:** scale-to-zero GPU offload of the *self-hosted* Florence
path (see the WBUX-3 research: ZeroGPU is unusable server-to-server, but
Modal / RunPod Serverless can run our own container). The GPU-procurement
work that WBUX-3 defers is now a **governance-permitted** future rather than a
governance-blocked one, subject to the subprocessor caveat above.

**What is still unchanged / out of scope:** third-party *model-provider* APIs
(`reject`, as above); BYOK (not implemented, not deferred); any actual GPU-offload
implementation (still requires its own scoped task with the subprocessor controls).
