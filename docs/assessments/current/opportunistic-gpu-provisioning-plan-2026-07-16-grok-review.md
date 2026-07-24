# Adversarial planning review: opportunistic GPU provisioning plan (2026-07-16)

**Verdict: conditional_pass.** Directionally correct — demand-triggered singleflight, capacity pre-check, readiness-before-serve, and CPU-as-default satisfy the adversarial review’s core reframing (bounded opportunistic GPU, never hang on the lottery) — but several load-bearing safeguards are named without implementable mechanisms (lease fencing/TTL, orphan-reaper scope vs open-ended hold, RES-15 circuit breaker, toast transition detection). Ship as design baseline only after the high findings below are closed; a junior engineer cannot implement lease + reaper + UI contract from the text alone without inventing semantics that will fail under crash, long backlog, or poll races.

## Constraint satisfaction vs prior adversarial review

Checked against `gpu-availability-async-pool-adversarial-review-2026-07-16.md` (present on companion branch; missing from this worktree’s tree at review time — plan cites it as implemented):

| Prior constraint / finding | Claimed in plan? | Actually specified? |
| --- | --- | --- |
| Images ≠ capacity | Yes (probe `ComputeCapacityReport`) | Yes — free pre-check before launch |
| Bound provisioning wait (RES-02) | Yes (W ≤ 30 min acquisition) | Partial — acquisition bounded; jobs never wait (good); hold while queue non-empty is **unbounded** |
| No per-request cold provision (RES-03) | Yes (demand trigger + readiness gate) | Yes for trigger shape; boot deadline present |
| CPU guaranteed fallback (RES-13) | Yes (T1d default path) | Yes — zero jobs wait on lottery |
| Retry backoff + cap (RES-06) | Yes (45–60 s + jitter, window) | Partial — spacing/ceiling stated; post-window re-trigger / cooldown not |
| Circuit breaker (RES-15) | Cited loosely via give-up | **No** — no trip/half-open/cooldown on persistent capacity miss |
| Bounded queue (RES-14) | Not addressed | **Gap** — CPU-tier plan requires it; this plan assumes “the queue” without bound/full policy |
| Steady-state reclaim (RES-07) | Idle terminate + orphan reaper | Partial — reaper predicate races active hold (finding #2) |
| Separate lean images | Not addressed | **Gap** — prior rec #4 ignored |
| Cost not 3× warm GPU | Steady $0; worst ~$480 | Partial — $480 is not true worst case (finding #4) |

Checked against `cpu-tiered-serving-plan-2026-07-16.md`: tier ladder T2=GPU / T1d=CPU fallback is consistent; RES-15 breaker + bounded queue + T1d p95 falsifiable budget from S5 are required there but not carried into this plan’s launcher contract. Toast “~40 s/image” on CPU contradicts measured Qwen CPU ~206 s and Florence ~14–39 s in the CPU plan.

## Findings

1. **SEVERITY high** | Acquisition lease has no TTL, heartbeat, or fencing token — a crashed/paused launcher can hold singleflight forever or double-launch after restart. | Launcher process dies after writing lease `launching` and before release; concurrent triggers “join the existing attempt” and spin until operator intervention; restart with a new `opc-retry-token` can LaunchInstance again while the first OCI instance is still booting → two billable A10s despite “concurrent usage target stays 1.” Plan cites RES-01/DATA-13 for the OCI token only, not lease fencing. | Resilience / RES-10 / DATA-13

2. **SEVERITY high** | Orphan reaper predicate (“tagged … older than the max window”) collides with hold-while-queue-non-empty, which has no max age. | Backlog drains slowly on GPU for 2+ hours (hold policy keeps instance); reaper uses acquisition W=30 min (or any fixed “max window”) and terminates a healthy serving instance mid-window; in-flight jobs fail or bounce to CPU while a new acquisition starts — thrash. If reaper instead never kills age>W when “in use,” the plan never defines the liveness signal that distinguishes orphan from active hold. | Resilience / RES-07

3. **SEVERITY high** | Prior-review RES-15 circuit breaker is not specified — only a one-shot acquisition window then “give up until the next trigger.” | Multi-day A10 drought: queue depth stays ≥ N permanently, so every trigger cadence re-enters probing/launching, re-hitting LaunchInstance (even with 45–60 s spacing) for the full W each time with no shared trip state, half-open probe, or cooldown that freezes acquisition and forces CPU-only routing until capacity recovers. CPU-tier plan §3.2 requires readiness probe **+** breaker; this plan only has the former. | Resilience / RES-15 / RES-06

4. **SEVERITY high** | Cost envelope “worst-case month ~$480 (8 h/day)” is not worst case — flapping demand, boot waste, and dud billing are unmodeled [PERF-07]. | Queue oscillates around the depth/age threshold every ~15–20 min: each cycle pays ~10 min boot-to-serve (~$0.33) plus up to 15 min dud billing on failed boots, then I=10 min idle before terminate; near-threshold flapping can approach continuous RUNNING hours **plus** repeated unpaid-work boot tax, exceeding 8 h/day steady hold. Failed launches are free; **dud RUNNING instances until boot deadline are not**. Double-launch from finding #1 doubles the bill. | Cost model / PERF-07

5. **SEVERITY medium** | “Capacity windows are minutes-scale” is generalized from one observed day (AD-2 open/closed windows on 2026-07-16) into default W=30 min and the opportunistic product shape. | A week-long drought is availability-safe (CPU path) but makes acquisition success rate ~0 while still burning probe/launch attempts each trigger; conversely multi-hour open windows make idle I=10 min and “minutes-scale” operational assumptions wrong (hold cost dominates). Defaults are not labeled as measurement-backed hypotheses with revisit criteria beyond the $1,400/mo reservation note. | Capacity math honesty / DIAG-03 (falsifiability)

6. **SEVERITY medium** | UI toast contract is not implementable from the stated tier-state resource alone — enum mismatch, poll races, and latency copy contradict measured facts. | (a) Toasts say `acquiring → serving` but server states are `idle \| probing \| launching \| serving \| degraded` — no `acquiring`/`released`. (b) “Toasts fire on TRANSITIONS only” with “existing job-status poll” and no transition cursor/event log: a poll that samples `idle` then later `serving` misses intermediate states and may skip the success toast; two transitions within one poll interval collapse. (c) Copy “~40 s/image” on CPU vs plan facts 206 s (Qwen T1d candidate) / ~14–39 s (Florence) — operators will distrust the notice system. Degraded-vs-error framing is good in prose; chip semantics for `degraded` vs return-to-`idle` after release are undefined. | UI/UX contract / OBS-01

7. **SEVERITY medium** | Launcher observability is almost absent — only job-tier provenance and “tier transitions logged.” | Ops cannot answer: lease holder identity, lease age, last capacity probe per AD, launch attempt count, boot-to-ready latency histogram, reaper terminate count, dud rate, acquisition give-up rate, or test-vs-prod tag split — so silent stuck lease (finding #1) and reaper misfires (finding #2) have no symptom metrics [OBS-05, OBS-08]. | Consistency / OBS-05

8. **SEVERITY medium** | Idempotency-token and migration semantics underspecified for a junior implementer. | (a) `opc-retry-token` scope: per process lifetime? per lease generation? stored where for retry after timeout? (b) “Jobs simply migrate to the GPU endpoint when it comes up” — in-flight CPU jobs finish on CPU? queued-only redispatch? at-most-once describe under tier switch needs end-to-end request ID at the job layer [DATA-13], not only OCI launch. (c) Trigger thresholds N, T_q, W, I, boot deadline are “e.g./default” without config-at-load validation [rg-008]. (d) Prior recommendation to keep description vs face images separate is omitted — fat image risk returns if someone bakes both. | Resilience / unimplementable / DATA-13

9. **SEVERITY low** | Bounded-queue and full-queue policy from the CPU-tier plan are not restated; opportunistic plan can be read as assuming an infinite describe queue. | Under CPU-only drought + high submit rate, queue grows without the RES-14/API-07 full policy the companion plan requires; GPU acquisition success then faces a multi-hour backlog that extends hold (cost) and confuses “idle timer starts when it drains.” | Consistency / RES-14

10. **SEVERITY low** | Reachability and ownership are externalized without a failure contract. | “Reachability per the tailscale/VCN plan (vlm-6)” — if overlay is down, readiness `/v1/models` fails for full boot deadline → dud terminate loop while capacity exists; no distinct “network path unhealthy” state vs capacity miss, and no owner for that interaction beyond “new service-side task (not ALTQ-1).” | Consistency / RES-03

## What is solid (do not regress)

- Demand-triggered acquisition (never per-request launch) correctly kills the thundering-herd finding.
- Free `ComputeCapacityReport` pre-check before mutating launch is the right probe economics.
- RUNNING ≠ serving readiness gate with dud terminate is essential [RES-03].
- CPU path as default, GPU never blocks dispatch — matches steelman and CPU-tier ladder.
- Explicit not-doing: warm stopped pool, default reservations, cross-region, public IP.
- Adoption gated on ALTQ-1 S5 bake-off — avoids shipping opportunistic cost for no quality win.
- Toast framing that CPU is designed default (info, not error) is product-correct.

## Required deltas before implementation (conditional gate)

1. Specify lease row: owner, generation/fencing token [RES-10], TTL + heartbeat, crash recovery, and singleflight join protocol.
2. Define reaper in terms of **lease state + last-heartbeat**, not wall-clock age alone; cap max hold hours for cost [RES-07, PERF-07].
3. Add explicit capacity circuit breaker: trip after K give-ups or consecutive capacity misses, half-open probe via ComputeCapacityReport only, no LaunchInstance while open [RES-15].
4. Replace $480 “worst case” with a cost model that includes boot tax, dud billing, flapping, and a hard monthly kill-switch metric.
5. Specify client transition detection (last_state + server `state_generation` or event cursor), align enum names with toast copy, and fix CPU latency numbers to measured/S5 budgets.
6. Publish launcher metrics + alert on lease age / stuck `launching` [OBS-05, OBS-08].
7. Carry bounded queue + job-level idempotency from the CPU-tier plan into this launcher’s dependency list.
