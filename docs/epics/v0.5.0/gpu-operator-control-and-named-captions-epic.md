# E23. GPU Operator Control and Named Captions

> **Metadata**
>
> - **Date**: 2026-09-06
> - **Author**: Claude Fable 5.1 (claude-fable-5-1)
> - **Epic Short ID**: GPUOPS
> - **Target Version**: v0.5.0
> - **Status**: in_progress — GPUOPS-1 task plan authored same day; live-defect precondition (OPSGPU-H-01/H-02/H-03/R3-01) is operator-only and tracked in handoff under MAINT-reap-20260906 (query, do not mirror)
> - **Grounding**: [gpu-lifecycle contract](../../workbay/contracts/gpu-lifecycle.md) · [describe-gpu-tier ux-map](../../../apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md) (open question HAI-04) · E19-4a identity merge layer (`scene/application/identity_merge/`) · live audit decision `clau_live_gpu_audit_20260906`

## Goal

The A10 burst GPU on OCI starts and stops correctly for image description, and the WordPress operator at demo.altcontext.com can see its state and explicitly start, stop, or return it to automatic from the admin SPA. Captions produced on either tier carry the names of labelled face-cluster people, with an operator-visible toggle and provenance.

## Hard Constraints

1. **One writer per file** (DATA-14): the lifecycle unit is the only writer of `/run/acx/gpu-state.json`; the description service is the only writer of `/run/acx-write/<ACX_ENV>/gpu-intent.json`. Nothing else touches either.
2. **Cost backstop always wins** (RES-10, COST-10): an operator `start` intent never overrides `--max-lease-seconds`. Intents expire (RES-07); an expired or malformed intent is `auto`, never `start`.
3. **Out-of-band control only** (VLM-3 finding 2185): the lifecycle controller runs on acx-backend (A1), never on the GPU instance. No agent or SPA path calls OCI directly.
4. **Verbatim boundary pass-through** (rg-015): PHP and SPA never invent lifecycle metadata; every field shown comes from `gpu-state.json` or the intent file via the service.
5. **Names are gated by one authority**: the service tenant flag `naming_agreement_enabled` is the single source of truth for person names in captions. The PHP-side option is removed, not mirrored (REF-09, greenfield delete-over-flag).
6. **Adversarial gate before merge**: every lane merge passes `/wb-review-slice` (1 local + N remote codex-remote gpt-5.6-luna effort max) against the canon lenses named in the task plan, then `handoff_close_check(enforce=True)`.
7. **No live GPU actuation from agents**: live smoke (start → describe → stop) is operator-run after the operator reinstalls the lifecycle units.

## Phases

| Phase | Tasks | Outcome |
| --- | --- | --- |
| P0 Operator precondition | MAINT-reap-20260906 H-01/H-02/H-03/R3-01 | Lifecycle units on acx-backend reinstalled with the aggregate load path, flock and running-since lease; prod compose mounts the load path |
| P1 Control plane + naming (this epic's single task) | GPUOPS-1 lanes L1–L8 in one parallel wave | Intent file contract, lifecycle honouring it, installer path unit + single reaper owner, service and PHP REST, SPA Burst GPU card, naming toggle, naming on GPU tier, naming provenance UI |
| P2 Live verification | GPUOPS-1 N13 | Operator-run smoke: Start from SPA → ready → named describe → Stop; evidence bundle via EVID-1 exporter |

## Exit Criteria

- Operator can start, stop and return the GPU to automatic from Settings › Burst GPU, and every state transition is visible within one poll interval.
- Idle reap, lease cap and boot-failure fallback behave exactly as before when the intent is `auto` (pinned by existing lifecycle tests, TEST-03).
- Exactly one reaper unit is enabled on acx-backend; enabling both fails a test.
- A describe run on the GPU tier yields alt text containing labelled people when the tenant flag is on, and none when it is off; provenance names the realizer.
- All lanes reviewed and closed through the pre-merge gate; live smoke recorded as a `test_result` on the merge SHA.

## Verification

- Per-lane: scoped TDD (`make slice-start`), lane test commands in `config/lane-orchestration/GPUOPS-1.json`.
- Branch: `/wb-review-slice` with canon lenses `batch_or_stream_worker`, `concurrency_or_async_code`, `release_or_deploy_change`, `ui_or_frontend_change`, `php_or_wordpress_change`, `ai_review_or_curation_ui`, `image_description_or_alt_text_change`.
- Live: operator smoke with the EVID-1 evidence bundle; never agent-initiated.
