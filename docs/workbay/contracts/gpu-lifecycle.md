---
title: GPU lifecycle controller
boundary_owner: infrastructure
status: draft
since: GPU-01
---

# GPU lifecycle controller

Out-of-band OCI burst-GPU start/stop. Not the describe HTTP API. Decision
tuples are `(action, instance_id)` with `action` ∈ `{START, STOP}`.

## CLI

`python -m infra.oci.gpu_lifecycle --mode reap|start` (default `reap`).

`--mode start` emits START for STOPPED instances when the load snapshot has
work (`queue_depth > 0` or `in_flight > 0`). `--mode reap` remains the idle
STOP path.

## Actuators

`OciCliStartActuator` / `OciCliStopActuator` are twins: same `oci compute
instance action` argv except `--action START|STOP` and `--wait-for-state
RUNNING|STOPPED`.

Auth: `~/.oci/config` or `--oci-auth` / `OCI_CLI_AUTH`.

## Readiness probe

After START, `--ready-url` polls an HTTP health endpoint with a bounded wait
(`--ready-max-cycles`, `--ready-stall-cycles`, `--ready-sleep-seconds`).

- Timeout and stall fail loudly (non-zero process exit, errors on the result).
- Per-instance no-progress cycles are tracked independently: one hung instance
  does not halt others in the same wait (rg-007).
- Default budget is 30 cycles × 10s ≈ 5 min (A10 boot+load amortization).
- Omitting `--ready-url` skips the wait.

## Load snapshot JSON

Existing keys: `queue_depth`, `in_flight`, `written_at`.

Additive optional: `batch_in_progress` (bool). Absent → false. Present but
not a bool → treat the snapshot as busy (fail closed). A STOP must never fire
while `has_work` is true (`queue_depth > 0` or `in_flight > 0` or
`batch_in_progress`).

## Fence

`fence_stop_actions` drops every STOP when:

- the re-sample has work (including an in-flight batch), or
- `fence_expired=true` (re-sample failed / window elapsed without a
  trustworthy idle confirmation).

Fence expiry falls back closed: no STOP.
