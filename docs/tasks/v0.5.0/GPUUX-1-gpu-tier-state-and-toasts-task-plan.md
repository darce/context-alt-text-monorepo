# Task Plan — GPUUX-1

> - **Date**: 2026-09-02
> - **Project**: context-alt-text-monorepo (description-service + WP plugin)
> - **Task ID**: `GPUUX-1`
> - **Design source**: `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.{json,md}`

## GPUUX-1. Surface burst-GPU lifecycle state in the describe UI

## Objective

Replace the `gpu_state: null` placeholder on `DescribeRunResponse` with a live,
single-writer GPU state (`unknown|stopped|starting|warming|ready|degraded`) and
render it in the Workbench describe flow: a tier chip on the progress zone, an
upgrade notice on apply, and edge-triggered toasts. Nothing in the UI derives
GPU state locally; the lifecycle controller is the only writer.

## Problem statement

A cold GPU can take roughly 104 seconds to return health 200. Without lifecycle
state, the operator sees a stalled progress bar with no explanation. GPUUX-1
makes this bounded wait visible without treating a timeout, missing snapshot,
or untrusted wire value as evidence that the GPU is unavailable.

## Constraints

- **Single writer** (DATA-14): only `infra.oci.gpu_lifecycle` writes
  `/run/acx/gpu-state.json`; the API reads it, while PHP and the SPA pass the
  value through (rg-015).
- **Fail closed to `unknown`** (OBS-08, RLSE-05): missing, stale, corrupt, or
  invalid snapshots become `unknown`, logged once per transition.
- **Validate configuration at startup** (rg-008):
  `ACX_GPU_STATE_STALE_SECONDS` is parsed once when the service loads. An unset
  variable uses the documented default; malformed explicit configuration
  fails startup.
- **Central vocabulary** (sr-007): Python uses `StrEnum`, TypeScript uses an
  `as const` vocabulary, and PHP performs no narrowing or synthesis.
- **Edge-triggered toasts** (PERC-05/07, A11Y-21): one toast per supported state
  edge and run, with informational toasts suppressed while the progress zone
  is visible. `unknown` never emits a toast.
- **Design tokens only** in CSS (sr-004); status colour is paired with an icon.
- The VM end-to-end run remains outside this task.

## Contract and service components

### Snapshot and shared response contract

- `docs/workbay/contracts/gpu-lifecycle.md` defines the lifecycle vocabulary,
  freshness rule, file ownership, and producer/consumer boundaries.
- `packages/shared-contracts/schemas/scene-describe-run.schema.json` defines the
  `gpu_state` response enum.
- `scene/tests/test_describe_run_contract.py` builds a real response and
  validates it against the shared schema, including `gpu_state`.

### Describe-service producer and reader

- `scene/application/describe_load.py` publishes `batch_in_progress` alongside
  `queue_depth`, `in_flight`, and `written_at`; this protects bulk runs across
  item-state gaps.
- `scene/application/gpu_state.py` owns `GpuState`, path resolution, immutable
  freshness settings, fail-closed snapshot parsing, and transition-only
  logging.
- `DescribeRunResponse.gpu_state` defaults to `unknown`, and the submit, status,
  and cancel response builder reads the current snapshot.

### Lifecycle writer and deployment

- `infra/oci/gpu_lifecycle/state_snapshot.py` owns `GpuLifecycleState`, maps OCI
  observations conservatively, and publishes snapshots through
  `write_gpu_state_snapshot(...)` using a same-directory temporary file and
  atomic rename. The writer never publishes `unknown`.
- Reap and start cycles serialize snapshot publication, preserve `since` only
  for the same instance and state, and publish a result at the end of every
  non-dry-run cycle.
- `scripts/deploy/gpu-lifecycle-install.sh` provisions the reader/writer
  directories with opposite mount permissions. `check-gpu-snapshots.sh`
  validates path, permissions, and freshness at deployment boundaries.

## WordPress and SPA components

### Wire passthrough and presentation

- The PHP submit, status, and cancel proxies pass `gpu_state` through verbatim.
  A missing key remains missing: adapters do not invent contract metadata
  (rg-015).
- `describeApi.ts` keeps the wire value untrusted. `isGpuState` narrows it at
  the consumer, and `gpuStatePresentation.ts` owns labels, icons, tones, and
  user-facing vocabulary.
- `MediaSelection.tsx` renders the tier chip and calm waiting notice;
  `useDescribeRunProgress` exposes the narrowed state and defaults invalid or
  absent values to `unknown`.

### Toast transitions

- `hooks/useGpuStateToasts.ts` observes the active describe run and emits only
  supported edges: stopped/starting to warming, warming to ready, and any
  known non-degraded state to degraded.
- Informational warming/ready toasts are suppressed while describe progress is
  mounted. Degraded remains visible because it requires operator attention.
- Edge memory is scoped to a run, repeated polls do not emit duplicates, and
  first observations or transitions involving `unknown` do not emit events.
- `App.tsx` mounts one observer inside `ToastProvider`; the hook and provider
  suites cover edge policy, suppression, actions, accessibility, and timer
  cleanup.

## Acceptance and verification

- Reader unit tests cover every enum value, stale/future/corrupt input,
  producer-shape invariants, transition logging, and startup configuration.
- Lifecycle tests cover state reduction, atomic publication, bounded waits,
  failure reporting, and the single-writer lock.
- The shared-schema test validates the actual API response builder.
- PHP tests cover passthrough for every enum member plus unknown, `null`, and
  absent wire values.
- Frontend tests cover state narrowing and presentation, progress visibility,
  edge-only toasts, suppression, deduplication, and actions.
- Deployment tests cover snapshot configuration, mounts, permissions,
  freshness, and macOS `/bin/bash` 3.2-compatible shell behavior.

Primary backend/deployment gate:

```text
python -m pytest scripts/deploy/tests apps/prototype-description-service/scene/tests -q
```

Frontend and PHP suites remain the authoritative gates for their respective
components.

## References

- Contract: `docs/workbay/contracts/gpu-lifecycle.md`
- UX map: `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.md`
- Rules: `docs/workbay/rules/backend-python-guidelines.md`,
  `docs/workbay/rules/frontend-guidelines.md`, and
  `docs/workbay/rules/backend-php-guidelines.md`
