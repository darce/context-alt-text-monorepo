---
title: GPU lifecycle controller
boundary_owner: infrastructure
status: draft (GPUUX-1 adds gpu-state snapshot)
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

## GPU state snapshot (GPUUX-1)

Single writer, single file, one vocabulary (DATA-14, sr-007). The lifecycle
controller writes `/run/acx/gpu-state.json` atomically (tmp + rename, same
pattern as the load snapshot) at the end of **every** `reap` and `start`
cycle, including cycles that take no action. The describe API only reads it;
no API process ever writes it.

```json
{"state": "warming", "instance_id": "<ocid>", "written_at": 1788390000.0,
 "reason": null, "since": 1788389900.0}
```

`state` ∈ `unknown | stopped | starting | warming | ready | degraded`:

| state | meaning | source of truth |
| --- | --- | --- |
| `stopped` | OCI `STOPPED`, no START in flight | OCI probe |
| `starting` | START actuated, OCI not yet `RUNNING` | actuator + OCI probe |
| `warming` | OCI `RUNNING`, readiness probe not yet 200 | readiness probe |
| `ready` | readiness probe 200 | readiness probe |
| `degraded` | FALLBACK emitted (`readiness_timeout`, `readiness_stall`, `start_failed`) or probe failing after `ready` | controller decision |
| `unknown` | snapshot missing, unreadable, or stale | reader fail-closed |

Rules:

- The controller never writes `unknown`; only the reader derives it. Corrupt
  or partial JSON on the writer side means the previous file stays in place
  (rename is atomic).
- `reason` is set only for `degraded` (the FALLBACK reason). `since` is the
  epoch seconds of the last state change; both optional.
- Reader freshness: `written_at` older than `ACX_GPU_STATE_STALE_SECONDS`
  (default 180 s, ≥ 2 × the slowest timer interval) → `unknown` (OBS-08: log
  once per transition, never per poll). Path via `ACX_GPU_STATE_PATH`
  (default `/run/acx/gpu-state.json`) resolved through one helper (rg-008).
- `unknown` is honest, not an error: the API keeps serving CPU-tier results
  and the UI shows no GPU chip. `ready` is the only state that may promote a
  run's expected tier to `final_gpu` in the UI.
- `DescribeRunResponse.gpu_state` carries this value verbatim on every poll
  (`packages/shared-contracts/schemas/scene-describe-run.schema.json`). PHP
  and the SPA pass it through; neither derives GPU state locally (rg-015).
- File ownership, two directories with opposite write direction (verified
  against `scripts/deploy/gpu-lifecycle-install.sh` lines 181-198):
  - `/run/acx` is `ubuntu:ubuntu 0755`, written only by the lifecycle units and
    bind-mounted **read-only** into the api container. `gpu-state.json` is
    written `0644` so the api container (uid 10001) can read it, and the
    single-writer lock `/run/acx/gpu-state.json.lock` is `ubuntu:ubuntu 0600`.
  - `/run/acx-write` is `root:10001 0775`, with per-environment subdirectories
    `/run/acx-write/{dev,staging,prod}` at the same `root:10001 0775`. Write
    access comes from the **group** (gid 10001), not from ownership. Each api
    container bind-mounts only its own `/run/acx-write/${ACX_ENV}` read-write
    and publishes `describe-load.json` there; the lifecycle units aggregate the
    `/run/acx-write` parent (`--load-dir /run/acx-write`).
