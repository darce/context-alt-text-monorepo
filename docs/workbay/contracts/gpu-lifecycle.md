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

Instance states:

- `STOPPED` + work → START.
- `STARTING` + work → in-flight boot: never re-START; probe/wait and emit
  FALLBACK on bound breach.
- `STOPPING` / `UNKNOWN` + work → fail closed (no START), loud error log.

## Actuators

`OciCliStartActuator` / `OciCliStopActuator` are twins: same `oci compute
instance action` argv except `--action START|STOP` and `--wait-for-state
RUNNING|STOPPED`.

START subprocess timeout is `max(--oci-timeout-seconds, --max-wait-seconds)`
so the waiter cannot be killed mid-boot (default max-wait 600s). A START
exception emits `FALLBACK` with `reason=start_failed` even when `actuated`
is empty.

Auth: `~/.oci/config` or `--oci-auth` / `OCI_CLI_AUTH`.

## Readiness probe

After START, `--ready-url` polls an HTTP health endpoint with a bounded wait
(`--ready-max-cycles`, `--ready-stall-cycles`, `--ready-sleep-seconds`).
Include `{instance_id}` in the URL for per-instance endpoints. A URL without
that placeholder is a single shared endpoint: multi-id waits are refused so a
healthy sibling cannot mask a dead instance. Missing HTTP status is
`NOT_READY` (never invented as 200).

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

Additive optional: `batch_in_progress` (bool). **The current describe-service
producer does not write this key.** Absent → false. The consumer must not
claim batch protection when the key is missing. Present but not a bool →
treat the snapshot as busy (fail closed). A STOP must never fire while
`has_work` is true (`queue_depth > 0` or `in_flight > 0` or
`batch_in_progress`).

Bulk / multi-job runs that never increment `in_flight`/`queue_depth` for the
whole batch are **unprotected until the producer writes `batch_in_progress`**.
`--load-json` help and `JsonFileJobLoadSource` document this loudly.

Unreadable / stale / missing load JSON is an **untrustworthy** sentinel
(`untrustworthy=true`, busy counts). STOP path: fail closed (no STOP). START
path: treat as no-work, refuse START, log an error. Corrupt JSON must never
actuate START or STOP.

## Fence

The fence covers only what the snapshot proves:

- the re-sample has work (`queue_depth`, `in_flight`, or explicit
  `batch_in_progress: true`), or
- `fence_expired=true` (re-sample failed / window elapsed without a
  trustworthy idle confirmation).

An absent `batch_in_progress` key is not a batch fence. Fence expiry falls
back closed: no STOP.

## CPU fallback

When a started instance does not become ready within the bounded wait, the
controller emits `{action: FALLBACK, profile: florence_small, instance_id,
reason}` with `reason` ∈ `{readiness_timeout, readiness_stall, start_failed}`. The decision
is logged only; no consumer is wired. Profile name is the given CPU floor
(`florence_small`), not imported from `scene.config.profiles`.
