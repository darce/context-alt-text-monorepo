# E20-11 — Hosted Provider Benchmark & Governance Decision Memo

> **Metadata**
>
> - **Date**: 2026-07-06
> - **Owning task**: E20-11 (`docs/tasks/20.0/E20-11-hosted-provider-benchmark-and-governance-decision-task-plan.md`)
> - **Status**: FINAL
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
