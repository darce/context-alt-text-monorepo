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

## Operator intent

The description service is the single writer for
`/run/acx-write/<ACX_ENV>/gpu-intent.json`, where `ACX_ENV` is `dev`,
`staging`, or `prod`. The lifecycle controller is read-only. With
`--intent-dir /run/acx-write`, it aggregates `*/gpu-intent.json`; the newest
unexpired `requested_at` wins, and equal timestamps resolve to `stop`.

```json
{
  "schema_version": 1,
  "action": "start | stop | auto",
  "requested_at": "2026-09-06T22:10:00Z",
  "expires_at": "2026-09-06T22:40:00Z",
  "ttl_seconds": 1800,
  "requested_by": "opaque operator label",
  "nonce": "uuid4"
}
```

Lifecycle semantics:

| intent | START arm | STOP arm |
| --- | --- | --- |
| absent / expired / malformed / `auto` | unchanged: start when `has_work` | unchanged: idle reap, lease cap, boot-failure fallback |
| `start` (unexpired) | START allowed with no work; honoured at most once per nonce (RES-01) | idle reap suppressed; **lease cap still stops** (RES-10); boot-failure fallback unchanged |
| `stop` (unexpired) | START suppressed even with work | STOP when `has_work` is false; when work is in flight publish `intent_status = blocked_work_in_flight`, journal the deferral, and re-evaluate next cycle (see [Durable intent journal](#durable-intent-journal)) |

Malformed intent is logged at WARNING with the parse error and treated as
`auto` (AGT-10, CAL-02). A valid intent whose `expires_at` is more than 7200
seconds after `requested_at` is clamped to 7200 seconds. The service normally
enforces the default 1800-second TTL and the 60–7200-second service bounds;
the lifecycle clamp is a defensive backstop. Omitting `--intent-dir` disables
the optional reader and retains automatic lifecycle behavior.

### Durable intent journal

`/run/acx-write/<ACX_ENV>/gpu-intent.json` is tmpfs. The instance it starts is
not. A grant that spends money therefore cannot be a tmpfs-only fact (RES-17),
and its expiry cannot be a wall-clock fact on a host that takes NTP
corrections (RES-10). Both are settled by an append-only journal on the unit's
`StateDirectory`:

`--intent-journal-path` (default `/var/lib/acx-gpu/intent-journal.jsonl`,
`infra/oci/gpu_lifecycle/intent_journal.py`). It is enabled whenever
`--intent-dir` is; without `--intent-dir` there is no intent to journal. One
JSON object per line, `schema_version: 1`, required keys `schema_version`,
`kind`, `nonce`, `recorded_at`; optional `boot_id`, `monotonic`, `action`,
`requested_by`, `ttl_seconds`, `reason`. Appends take the same-file `flock`,
`fsync` before returning, and the file is truncated newest-first at 2000
records so an unattended host cannot fill its state directory (rg-007).

`kind` ∈ `observed | deferred | rearmed | dropped | burned | cycle`:

| kind | written when | consequence |
| --- | --- | --- |
| `observed` | first sight of a nonce, **before** it can be honoured | fixes the monotonic origin and `boot_id` for that grant (write-ahead) |
| `deferred` | a `stop` was blocked by work in flight | marks the grant eligible for re-arm past its wall-clock expiry |
| `rearmed` | a deferred `stop` outlived `expires_at` inside the re-arm budget | the STOP survives; logged at WARNING |
| `dropped` | a deferred `stop` exhausted the re-arm budget (default 3600 s past TTL) | terminal; logged at WARNING naming `requested_by` (FLOW-08) |
| `burned` | the grant is spent: monotonic TTL elapsed, clock ran backwards, or the host rebooted | terminal; no later clock value can re-arm it (RES-10) |
| `cycle` | end of every reap/start cycle that had a nonce | records effective intent, `intent_status`, actuations, lease expiry, `last_transition_reason`, errors (HAI-06) |

Expiry rules, in order:

- A nonce with a terminal record (`burned` / `dropped`) is spent. It is never
  honoured again regardless of what the intent file says.
- Elapsed time for a grant is `monotonic(now) - monotonic(observed)`, not
  `now - requested_at`. **Monotonic expiry wins even while the wall clock still
  says unexpired, and a backwards wall-clock correction cannot resurrect a
  grant whose monotonic TTL has elapsed.** A negative elapsed value is
  impossible on a working clock, so it burns the grant rather than trusting it.
- Wall-clock expiry alone refuses the grant for this cycle but does **not**
  burn it, so a `deferred` `stop` can still be re-armed.
- `boot_id` (`/proc/sys/kernel/random/boot_id`) mismatch means the monotonic
  origin is gone. The grant is burned and the revocation is logged at ERROR
  naming the original `requested_by` and the reboot. A reboot silently
  reverting the instance to `auto` is exactly the untraceable transition this
  journal exists to prevent (OBS-08, RLSE-05).
- A journal that cannot be read (structurally corrupt, unwritable, no boot
  identity) refuses the grant and says why; it never defaults open (rg-008,
  AGT-10). A torn trailing line — the one partial write a crash can leave — is
  tolerated and dropped.

The journal is the reconstructable record of every automated decision that
spends money: for any nonce, `requested_by`, the effective intent, the
`intent_status`, and the actuation outcome are replayable from durable storage
after the tmpfs intent file is gone (HAI-06). A journal append that fails is
logged and never aborts the cycle — the cost cap outranks its own audit trail
(rg-007).

### `gpu-state.json` additive intent fields

The existing writer and reader contract remains additive; existing readers
ignore unknown keys. The lifecycle publishes these fields on a single-instance
cycle:

| field | type | meaning |
| --- | --- | --- |
| `intent` | `start\|stop\|auto` | effective intent this cycle |
| `intent_expires_at` | iso8601 or null | from the winning intent |
| `intent_status` | `none\|pending\|honoured\|blocked_work_in_flight\|expired` | what the controller did with it |
| `honoured_nonce` | string or null | idempotency marker for START |
| `lease_expires_at` | iso8601 or null | `running_since + max_lease_seconds` |
| `instance_running_since` | iso8601 or null | from the running-since lease |
| `last_transition_reason` | `work\|operator\|idle\|lease_cap\|start_failed\|unknown` | why the last actuation happened |

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
producer writes this key.** A true value keeps bulk runs protected across
item-state gaps that do not increment `in_flight` or `queue_depth`. A STOP must
never fire while `has_work` is true (`queue_depth > 0` or `in_flight > 0` or
`batch_in_progress`).

Absent remains false for compatibility with older or alternate producers. The
consumer must not claim batch protection when the key is missing and warns
once so operators can identify an incomplete producer contract. Present but
not a bool is treated as busy (fail closed). `--load-json` help and
`JsonFileJobLoadSource` document these compatibility semantics.

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
  - **Host obligation:** a group entry must resolve for GID 10001. The chowns
    above are numeric and succeed without one, but both units pin
    `SupplementaryGroups=10001`, which systemd resolves through NSS *before*
    `ExecStart` — with no entry, each unit dies at `status=216/GROUP` and the
    burst GPU loses its stop path. The installer creates it (`acxapi`, or
    `acxgid10001` if that name is already taken at another GID) and
    `preflight-gpu-env.sh --check-reaper` asserts it before the flip. The name
    is arbitrary and deliberately not part of this contract; only the GID is.
    Note the API image pins the same GID as `acx`
    (`apps/prototype-description-service/Dockerfile`) — a separate namespace
    from the host, and every chown on both sides is numeric.
