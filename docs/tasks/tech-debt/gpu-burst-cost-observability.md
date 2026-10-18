# GPU Burst Cost Observability

> **Integration consumer, 2026-09-19:** [FIRDV-2 S7](../firdv/FIRDV-2-comparative-harness-and-bakeoff-task-plan.md#s7--burst-cost-instrumentation-and-gated-live-run) requires this sanctioned aggregation/burst ledger for the self-hosted description bake-off. Implement it once under coordinated ownership; estimated hourly-rate overlays do not close this debt.

## Problem

Cost per image description cannot be measured from any sanctioned surface. The description service persists per-run timing on `image_description_runs` (`queue_ms`, `ramp_up_ms`, `processing_ms_p50`, `processing_ms_max`, `server_elapsed_ms`, `items_timed`, `startup_id`), but:

- The API exposes one run at a time by id (`GET /describe/run/{run_id}`, `/items`). There is no list or aggregate endpoint.
- No make target or script reads the timing columns. `make logs-prod` is container logs only.
- `make gpu-cost-report` (`scripts/gpu_cost_report.py`) reconciles an OCI Usage export against a smoke evidence JSON. The only evidence files that exist are two dry-run fixtures (2026-09-04, `running_seconds=4`); no live burst has been captured.
- `make gpu-evidence-export` is operator-only on `acx-backend` (OCI binary + vaulted key).
- Billed RUNNING seconds per burst (START actuated → STOPPED: warm-up + processing + reaper idle tail) are recorded nowhere alongside the run.
- An agent `psql` read of the production database is denied by the permission classifier, by design. The gap is the missing sanctioned read path, not the denial.

## Impact

- On 2026-09-19 the cost-per-image question (N = 1, 5, 10, 50, 100) had to be extrapolated from one hand-recorded run (b1170558: 10 images, ramp-up 132.7 s, ~2.45 s/image warm, 300 s idle reap; handoff decision 12460 on `MAINT-RELEASE-0024-20260918`) at an assumed $2/hr.
- Fixed overhead per burst (~417 s ≈ $0.23) dominates small batches, so pricing, batching and idle-timer decisions rest on a single sample.
- The idle-timer default (`--idle-seconds 300`) and the $2/hr rate have never been reconciled against an OCI invoice.
- Warm-path reuse (second batch inside the idle window) is invisible: nothing ties runs to the burst that served them.

## Prerequisites

- None blocking. Best sequenced after GPUFLOW-3 lands (`infra-gpu-state-starting` publishes the `starting` state the burst ledger keys on).

## Solutions (ordered by recommendation)

### 1. Runs summary endpoint + make target + burst ledger (recommended)

- `GET /describe/runs?since=&limit=`: read-only, tenant-scoped, API-key authenticated; returns the timing columns, item count, result tier mix and `startup_id` per run. All envelope fields come from the request or the rows (rg-015).
- Persist one row per burst keyed by `startup_id`: START actuated, first ready, last job end, STOPPED, billed RUNNING seconds. Written by the GPU lifecycle/reaper path that already owns `gpu-state.json`.
- `make gpu-run-timings ENV=<env> [SINCE=...] [HOURLY_RATE=2.0]`: calls the endpoint and prints per-run and per-image cost, amortizing burst overhead across the runs that shared the burst.
- Teach `scripts/gpu_cost_report.py` to accept the burst ledger as input so reconciliation against the OCI Usage export no longer requires a live smoke.

**Pros**: Measured, repeatable, no database access needed; reuses the existing cost reporter and its tolerance check.
**Cons**: New table in `001_identity_schema.py` (greenfield, no migration) and a new contract entry in `docs/workbay/contracts/image-description-api.md`.

### 2. Operator-only SQL report

A `make` target that runs a fixed read-only query on `acx-backend` as the operator.

**Pros**: No service change.
**Cons**: Still no burst ledger, so the idle tail stays an assumption; not usable by agents or CI; couples tooling to internal table names.

### 3. Prometheus metrics

Export run and burst timings on `/metrics` and compute cost in Grafana.

**Pros**: Fits the dashboards already scoped in [correlation-dashboards.md](./correlation-dashboards.md).
**Cons**: Depends on that unbuilt stack; per-run attribution is lossy in histograms.

## Acceptance

- `make gpu-run-timings ENV=prod` prints measured cost per image for the last N runs without database credentials.
- A burst's billed seconds reconcile with the OCI Usage export within the reporter's tolerance (default 25%).
- Documented command runs as written (rg-006).

## Origin

GPUFLOW-3 orchestration session, 2026-09-19. Tracked in handoff as finding `GPUFLOW-3-OBS-01` (status lives in the handoff DB, not here).
