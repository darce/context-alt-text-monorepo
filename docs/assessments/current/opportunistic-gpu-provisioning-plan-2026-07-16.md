# Plan: opportunistic GPU provisioning for production + testing (2026-07-16, r2)

> How the description service (and test/bake-off harnesses) opportunistically acquire an
> A10 GPU now that the tenancy holds limit slots in all three Ashburn ADs, without ever
> making production hostage to the capacity lottery. Extends
> [`cpu-tiered-serving-plan-2026-07-16.md`](cpu-tiered-serving-plan-2026-07-16.md) (tier
> ladder, T2 = GPU) and implements the constraints from
> [`gpu-availability-async-pool-adversarial-review-2026-07-16.md`](gpu-availability-async-pool-adversarial-review-2026-07-16.md).
> Reachability per the tailscale/VCN plan (vlm-6 branch). Implementation ownership: a new
> service-side task (not ALTQ-1); this doc is the reviewed design baseline.
> r2 closes grok review findings ALTQ-1-GPROV-01..10
> ([review](opportunistic-gpu-provisioning-plan-2026-07-16-grok-review.md), verdict
> conditional_pass → deltas 1–7 applied below).

## Measured facts (2026-07-16 session — all verified, not estimated)

- **Limits (post-grant)**: `gpu-a10-count` AD-1 = 1 (held by stopped `acx-gpu-burst`),
  **AD-2 = 2, AD-3 = 1** — three ADs of launch headroom, concurrent usage target stays 1.
- **AD-1 remains `OUT_OF_HOST_CAPACITY`** (21:24Z); its slot is unusable for fresh
  launches until Oracle frees hosts or the stopped instance is terminated.
- **Capacity windows observed minutes-scale on 2026-07-16** (open 18:18Z, closed by
  19:54Z, open again 20:20Z; 45 s-interval retry caught one in 9 attempts). **This is one
  day of observation — a hypothesis, not a distribution.** Tunables carry revisit
  criteria (§Tunables) and the breaker (§4) makes a week-long drought cheap [DIAG-03].
- **Window→serving ≈ 10 min**: launch 20:19:35Z → RUNNING ~3 min → baked
  `acx-gpu-vlm.service` (llama.cpp Qwen3-VL-30B-A3B Q4) active by ≈20:30Z.
- **GPU value (measured on the A10)**: p50 **2.6 s/img** single-pass, 5.8 s two-pass,
  3.6 s dual-length; the 646-corpus run held mean 2.71 s/img. CPU comparators:
  Florence-2 **14–39 s/img**, Qwen3-VL-4B **206 s/img** (A1, VLM-2B).
- **Cost**: ~$2/hr while RUNNING (including duds not yet serving); failed launch
  *attempts* are free; stop releases the host (no warm pool possible — verified).

## Design (constraints inherited from the adversarial review)

### 1. Acquisition lease (singleflight with fencing) [RES-10, DATA-13]

One DB row (`gpu_acquisition_lease`) is the sole authority:
`(id=1, generation, state, holder_id, heartbeat_at, ad_cursor, attempt_count,
window_started_at, instance_ocid, instance_ad, created_at)`.

- **Take/join**: a trigger takes the lease only via compare-and-swap on `generation`
  (state `idle→probing`, `generation+1`, `holder_id`=process identity). Losers **join**:
  they do not launch; they read state for UI/metrics.
- **Heartbeat + TTL**: holder heartbeats every 15 s; a lease with
  `heartbeat_at` older than 60 s is **expired** — any process may CAS-supersede it
  (`generation+1`). A superseded holder that wakes must observe the generation mismatch
  and abandon (fencing: every mutating step re-reads and validates its generation).
- **Idempotent launch**: each `LaunchInstance` carries
  `opc-retry-token = "acx-gpu-<generation>-<attempt_count>"`, persisted on the lease row
  *before* the call — a crashed-and-superseded holder's retry token can never collide
  with the new generation's, and a same-holder timeout retry reuses the same token
  (no double instance) [RES-01, DATA-13].
- **Crash recovery**: new generation first reconciles: list instances carrying the
  freeform tags `acx-opportunistic-gpu` + `acx-lease-generation=<generation>` (both
  stamped at launch — the generation lives on the instance, not only in the DB); adopt
  one whose generation tag predates the current generation and is healthy (readiness
  passes) or terminate it if not — before any new launch. The reaper (§3) uses the same
  generation tag to decide orphanhood.

### 2. Acquisition loop (bounded, probe-first) [RES-06]

- Trigger: describe-queue depth ≥ `N_up` or oldest-job age > `T_q`, or an explicit
  operator/test request. The queue itself is **bounded with a full policy** (inherited
  requirement — see Dependencies) [RES-14].
- Probe-first: `ComputeCapacityReport` (free, read-only) for AD-2 → AD-3 (→ AD-1 when its
  slot frees); `LaunchInstance` only in ADs reporting `AVAILABLE` — a blind launch burns a
  rate-limited mutating call.
- Bounds: attempts spaced 45–60 s + jitter; acquisition window ≤ `W` per lease
  generation; on window exhaustion the lease records a **give-up** and state returns to
  `idle` (jobs were never waiting — they are draining on CPU throughout).

### 3. Readiness, hold, release [RES-03, RES-07]

- **RUNNING ≠ serving**: dispatch only after `/v1/models` answers. Boot deadline
  `D_boot` (default 15 min): a RUNNING instance that never becomes ready is a **dud** —
  terminated, billed for up to `D_boot` (modeled in §Cost), and counted (metric).
  **Network-unhealthy is distinguished from capacity-miss**: if the jump/overlay path
  itself is down (gate unreachable), the launcher sets state `net_unhealthy`, does NOT
  terminate a possibly-healthy instance on readiness timeout, alerts, and freezes
  acquisition — a dud verdict requires the network path to be provably up [GPROV-10].
- **Hold**: keep the instance while the queue is non-empty; idle timer `I` (default
  10 min) after drain → terminate. **Max hold cap `H_max`** (default 6 h per acquisition)
  bounds cost even under an endless backlog — at the cap, terminate, force a fresh
  acquisition decision (which re-reads breaker/cost state) [PERF-07].
- **Reaper (lease-aware, never wall-clock-only)**: terminates only instances that are
  (a) tagged `acx-opportunistic-gpu` AND (b) orphaned — their lease generation is not the
  current one, or the lease heartbeat is expired. A healthy heartbeating hold is never
  reaped regardless of age (`H_max` is the holder's own job); the reaper is the safety
  net for dead holders [RES-07].
- Hysteresis against flapping: `N_down < N_up` (release threshold below acquire
  threshold) plus minimum hold `I` — a queue oscillating around `N_up` cannot
  launch/terminate-cycle faster than one boot + one idle window; the cost model still
  prices that worst case (§Cost).

### 4. Capacity circuit breaker [RES-15]

- **Trip**: `K` consecutive give-ups (default 3) or a rolling capacity-miss rate over
  the last 24 h above a threshold → breaker **open**.
- **Open**: no `LaunchInstance` at all; routing is CPU-only; state surface says
  `breaker_open` (UI shows the steady "CPU mode" chip, no toast churn).
- **Half-open**: the breaker enters half-open automatically on its probe cadence (every
  30 min while open); half-open performs one free `ComputeCapacityReport` sweep only.
  Observing `AVAILABLE` closes the breaker; the *next trigger* may launch. Anything else
  re-opens for another cadence interval.
- The consecutive-give-up counter `K` resets to zero on any successful acquisition
  (instance reached `serving`).
- Breaker state is persisted next to the lease row and exported (metrics + status
  resource).

### 5. Serving provenance + job idempotency

- Every response records the tier/model that actually served it (existing
  `adapter_kind`/`model_id` envelope) [rg-015].
- **Tier switch is redispatch-only**: in-flight CPU jobs finish on CPU; only queued jobs
  route to the GPU endpoint when it becomes ready. Every describe job carries an
  end-to-end request ID; the job store enforces at-most-once completion per request ID
  regardless of tier switches [DATA-13].

### 6. Operator/user-facing state (UI toasts) [OBS-01]

- **Server truth**: tier-state resource
  `{state: idle|probing|launching|serving|net_unhealthy|breaker_open, since,
  queue_depth, state_generation, last_transition: {from, to, at}}` — read directly from
  the lease/breaker rows; nothing fabricated [rg-015]. `state_generation` increments on
  every transition.
- **Client transition detection**: the WP admin keeps `last_seen_generation`; on each
  poll, if `state_generation` advanced, it renders a toast from `last_transition`
  (collapsed transitions show the latest — acceptable: toasts are advisories, chips show
  current state). No transition is *silently* lost: the chip always reflects current
  state even when an intermediate toast collapsed.
- **Toast copy uses measured numbers** (from this doc / S5 budgets, not invented):
  - `launching → serving`: "GPU acceleration active — descriptions now ~3 s/image."
  - `serving → idle` (released/degraded): "GPU released — descriptions continue on CPU
    (Florence ~15–40 s/image)." (info, not error — CPU is the designed default; if S5
    selects the 4B (~206 s/img) as T1d, the copy and the queue-time estimate MUST be
    regenerated from the S5 measurement, not hand-edited.)
  - give-up / `breaker_open`: one info toast, then steady chip only.
  - Status chips pair color with an icon [sr-004]; polling reuses the existing job-status
    poll — **never a gated `refetchInterval` returning `false`** (permanent-freeze
    gotcha).
- **Testing mode**: test acquisitions set a `test` tag; prod metrics and prod toasts
  exclude them.

### 7. Launcher observability [OBS-05, OBS-08]

Exported at write time (not bolted on later): lease holder + generation + age; heartbeat
staleness; per-AD last probe result + timestamp; launch attempts / give-ups / duds /
reaper terminations / adoption events (counters); boot-to-ready latency histogram;
breaker state + trip count; per-tier serve counts + fallback rate; month-to-date
opportunistic-GPU spend estimate (RUNNING-hours × rate) with an **alert + forced breaker
open at the monthly budget cap `B_month`** (default $150).

## Tunables (config-validated at load [rg-008]; all defaults are hypotheses)

| Knob | Default | Basis | Revisit when |
| --- | --- | --- | --- |
| `N_up` / `N_down` | 10 / 2 jobs | hysteresis vs flapping | measured flap rate > 2 cycles/day |
| `T_q` | 10 min | CPU T1d wait tolerance | S5 budget lands |
| `W` (acquisition window) | 30 min | 2026-07-16 window cadence (1 day!) | capacity-miss rate ≥ 0.5 over a week |
| `D_boot` | 15 min | measured ~10 min window→serving | dud rate > 10% |
| `I` (idle) | 10 min | guess | idle-hours vs re-acquisition cost |
| `H_max` | 6 h | cost bound | backlog regularly > 6 h of GPU work |
| `K` (breaker) | 3 give-ups | guess | drought/recovery data |
| `B_month` | $150 | 1/10 reservation cost | product decision |

Config is structurally validated at service start; malformed/missing keys fail fast
[rg-008].

## Cost envelope (honest worst cases) [PERF-07]

- Steady state (no demand): **$0** — no reservations, no warm pool.
- Active hold: ~$2/hr, bounded per-acquisition by `H_max` (default cap $12/acquisition).
- **Boot tax**: every acquisition pays ~10 min unserving RUNNING (~$0.33); **duds** pay up
  to `D_boot` (~$0.50) with zero work.
- **Flapping worst case**: with hysteresis + `I`, the fastest possible cycle is
  ~(boot 10 m + serve ≥0 + idle 10 m) ≈ 3 cycles/hr ⇒ still ≤ $2/hr — flapping cannot
  exceed steady-hold cost (one instance bills ≤ 1 RUNNING-hr/hr), but at the degenerate
  serve≈0 cycle up to **50%** of the spend is boot tax; the flap-rate metric exists to
  catch it.
- **Hard ceiling**: `B_month` (default $150/mo) forces the breaker open — the true
  worst-case monthly spend is `B_month`, by construction, not an estimate. (Reference:
  8 h/day steady hold ≈ $480/mo would trip the cap long before month-end; a reservation
  at $1,400/mo is revisited only if the cap is deliberately raised past ~$700 with
  sustained hold-hours to justify it.)

## Dependencies (carried from companion plans, restated as launcher prerequisites)

- **Bounded describe queue + full-queue policy** (cpu-tiered-serving plan §3) [RES-14,
  API-07] — the launcher assumes it exists; it is not optional.
- **Job-level end-to-end request ID / at-most-once completion** [DATA-13].
- **Lean images**: the opportunistic GPU image carries the description stack only; the
  face-pipeline image stays separate (prior adversarial rec — fat-image rebuild ripple).
- **Network-path health check** (jump/overlay) as a first-class input to the readiness
  verdict (§3) — owned by the tailscale/VCN plan.

## Decision rule for adoption

Ship the opportunistic tier only if the bake-off decision memo confirms the GPU model
materially beats the CPU tier on the expanded rubric (ALTQ-1 S5 gates); otherwise the
launcher remains a test-harness tool and prod stays CPU-only. Interim signal
(2026-07-16): two-pass on GPU cut distractor wrong-name rate 0.216→0.081 at p50 5.8 s —
if that survives S5, the GPU tier has a real quality case. Either way the CPU tier
remains the availability guarantee — toast copy must never imply degraded = broken.

## Not-doing

- Warm pools of stopped instances (reserve nothing — verified) and per-request launches
  (adversarial review, dominated).
- Capacity reservations by default (cost; revisit per `B_month` rule above).
- Cross-region rotation (image copy + privacy review first).
- Public-IP reachability (tailscale/VCN plan owns the network path).
