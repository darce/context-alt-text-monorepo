---
title: GPU lifecycle controller
boundary_owner: infrastructure
status: draft
since: GPU-01
---

# GPU lifecycle controller

Out-of-band OCI burst-GPU start/stop. Not the describe HTTP API. Decision
tuples are `(action, instance_id)` with `action` ∈ `{START, STOP}`.
`FALLBACK` is a separate decision object, not an OCI power action.

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
- Stall counts probe ERROR / exception only. `NOT_READY` is pending boot and
  stays in the wait until `--ready-max-cycles` timeout; it does not increment
  the stall counter. Defaults `30 × 10s ≈ 5 min` cover a normal A10 boot;
  `--ready-stall-cycles` (default 3) trips only on consecutive probe errors.
- Per-instance no-progress cycles are tracked independently: one hung instance
  does not halt others in the same wait (rg-007).
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

## CPU fallback

When a started instance does not become ready within the bounded wait, the
controller emits `{action: FALLBACK, profile: florence_small, instance_id,
reason}` with `reason` ∈ `{readiness_timeout, readiness_stall}`. The decision
is logged only; no consumer is wired. Profile name is the given CPU floor
(`florence_small`), not imported from `scene.config.profiles`.
