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
`--intent-dir /run/acx-write`, it aggregates `*/gpu-intent.json`. Precedence is
by `sequence` first (a monotonically increasing publication counter, minimum
`1`), then by `requested_at`, and `stop` wins a remaining tie. `requested_at` is
an interoperability field and a tiebreak only: it can never move an expiry
later or re-arm a fenced publication (RES-10). A `requested_at` more than 120
seconds in the future is rejected.

```json
{
  "schema_version": 1,
  "action": "start | stop | auto",
  "requested_at": "2026-09-06T22:10:00Z",
  "expires_at": "2026-09-06T22:40:00Z",
  "ttl_seconds": 1800,
  "requested_by": "opaque operator label",
  "nonce": "uuid4",
  "sequence": 7
}
```

Lifecycle semantics:

| intent | START arm | STOP arm |
| --- | --- | --- |
| absent / expired / malformed / `auto` | unchanged: start when `has_work` | unchanged: idle reap, lease cap, boot-failure fallback |
| `start` (unexpired) | START allowed with no work; honoured at most once per nonce (RES-01) | idle reap suppressed; **lease cap still stops** (RES-10); boot-failure fallback unchanged |
| `stop` (unexpired) | START suppressed even with work | STOP when `has_work` is false; when work is in flight publish `intent_status = blocked_work_in_flight` and re-evaluate next cycle |

**Stop with arriving work (COST-10, GPUOPS-1-CANON-07).** A live `stop`
intent suppresses START even when `has_work` becomes true after the intent was
published, so queued describe items can sit undescribed for the whole intent
TTL (up to 7200 s) while the CPU tier is idle. C5's "STOP disabled while
`has_work`" guard only protects work that is already in flight. Required
behaviour: when a cycle observes `intent = stop` and `has_work` is true and no
GPU instance is running, the controller publishes
`intent_status = stopped_with_work` and emits
`{action: FALLBACK, profile: florence_small, reason: operator_stop_with_work}`
so the describe service can route the queue to the CPU floor instead of
stalling. `operator_stop_with_work` is added to the FALLBACK `reason` set
below. As of this revision the controller does not emit it; the implementation
is tracked on the GPU-LIFECYCLE-CODE lane of ISSUEDAG-1, and until it lands a
deliberate operator stop is a stall path, not a degrade path.

Malformed intent is logged at WARNING with the parse error and treated as
`auto` (AGT-10, CAL-02). A valid intent whose `expires_at` is more than 7200
seconds after `requested_at` is clamped to 7200 seconds. The service normally
enforces the default 1800-second TTL and the 60–7200-second service bounds;
the lifecycle clamp is a defensive backstop. Omitting `--intent-dir` disables
the optional reader and retains automatic lifecycle behavior.

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

### Durable intent state

`/run/acx-write` is tmpfs: it does not survive a reboot. An operator intent is a
write-ahead record for a durable external mutation that spends money, so the
controller keeps its own state under `/var/lib/acx-gpu` (systemd
`StateDirectory=acx-gpu`, `StateDirectoryMode=0700`), which both timer units
already mount (RES-17).

| path | purpose |
| --- | --- |
| `/var/lib/acx-gpu/intents/` | durable copy of the runtime publications |
| `/var/lib/acx-gpu/intent-authority.json` | fencing ledger: high-water wall clock, highest sequence, per-nonce expiry |
| `/var/lib/acx-gpu/deferred-stop.json` | a STOP that is waiting on in-flight work |
| `/var/lib/acx-gpu/decision-log.jsonl` | append-only audit trail of spend decisions |

Passing `--intent-dir` enables all four; omitting it disables the reader and all
durable intent state, retaining the legacy in-memory behavior. Every file is
written to a temporary inode, `fsync`ed, and renamed into place under a bounded
10-second `flock`; a lock that cannot be taken is an error, not a bypass.

**Copy before evaluate.** Each cycle copies the valid runtime publications from
the tmpfs intent dir into `/var/lib/acx-gpu/intents/` and then evaluates from the
durable dir. A failed copy is logged at WARNING and evaluation continues from
whatever the durable dir already holds.

**Fencing.** Before an intent is eligible, the authority ledger checks it:

- A `sequence` below the persisted `highest_sequence` is fenced, even for a
  nonce that was previously honoured. This is what stops an old publication from
  being reintroduced after a newer one superseded it.
- Different nonces at the same sequence reject that sequence durably, including
  any deferred STOP carrying the rejected token. The ledger's duplicated expiry
  and sequence fields must agree with its immutable publication; malformed
  numeric deadlines and inconsistent records make authority unavailable.
- Expiry is evaluated against `max(now, last_wall_time)`, so a backwards NTP
  correction cannot extend a grant, and additionally against a per-boot
  monotonic deadline recorded when the nonce was first seen.
- Once expired, the nonce's ledger record is written `expired: true` and that
  state is terminal. No later reading of any clock re-arms a spent grant.
- Across a host reboot, an existing grant is revoked rather than falling back
  to wall-clock expiry: its monotonic deadline cannot be compared across boots.
  The ledger persists `expired: true`, `revocation_reason`, and
  `revoked_in_boot_id`, retaining the original publication and `requested_by`;
  an ERROR log identifies that requester and both boot identities. A new
  operator publication is required. A process restart within the same boot
  preserves the original deadline. Legacy grants without a boot identity are
  also revoked when next observed; this deliberately replaces the previous
  logical-wall fallback policy (GPUOPS-LANDING-1).
- If the ledger cannot be read or the monotonic clock or boot identity is unavailable, the cycle
  logs at ERROR and uses `auto`. An unreadable authority never honours an
  intent.

**Deferred STOP.** When a `stop` intent arrives while work is in flight, the
STOP is not dropped. It is persisted to `deferred-stop.json` with its
`requested_at`, `nonce`, `sequence`, and a `deferred_until` extension of
`ttl_seconds` clamped to 60-7200 seconds, and the cycle publishes
`intent_status = blocked_work_in_flight` (FLOW-08). Later cycles rehydrate the
record and re-arm it - the deferral, not the original `expires_at`, is the
authority for the effective expiry, so a STOP that waited out its own TTL is
still honoured when the work drains. A record whose intent lacks `requested_at`,
`nonce`, or `sequence` cannot be persisted; that is reported as a cycle error, not
silently deferred. A higher `sequence`, a rejected sequence, or another nonce
owning its sequence clears the deferral and records the drop with the original
requester. Rejection is checked before re-arming the deferred deadline.
The fencing decision is appended with `phase = before_clear` under the deferred
record lock before removing that record. If audit persistence fails, the record
remains and the cycle reports an error and blocks automatic intent actuation;
the hard lease cap remains active. A crash between append and removal can leave
the fenced record for the next cycle to clear, so this phase is not proof that
the file was removed.

**Decision log.** Every cycle that decides, actuates, hits the lease cap, or
blocks a STOP appends one JSON object to `decision-log.jsonl` (HAI-06):

| field | meaning |
| --- | --- |
| `timestamp` | cycle time, iso8601 Z |
| `mode` | `reap` or `start` |
| `requested_by`, `nonce`, `sequence` | provenance of the effective intent |
| `effective_intent`, `intent_status`, `intent_expires_at` | what the controller resolved |
| `decided`, `lease_expired`, `actuated` | `(action, instance_id)` pairs |
| `actuation_outcome` | `honoured\|partial\|deferred\|failed\|fenced_off\|not_actuated` |
| `errors` | cycle errors, verbatim |

An append failure is logged at ERROR **and** added to the cycle's `errors`. The
audit trail is not best-effort: a cycle that spent money without being able to
record that it did so reports itself as failed.

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
reason}` with `reason` ∈ `{readiness_timeout, readiness_stall, start_failed,
operator_stop_with_work}` (the last is contract-required, not yet emitted; see
"Stop with arriving work" above). The decision
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
