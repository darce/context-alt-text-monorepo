# Plan: opportunistic GPU provisioning for production + testing (2026-07-16)

> How the description service (and test/bake-off harnesses) opportunistically acquire an
> A10 GPU now that the tenancy holds limit slots in all three Ashburn ADs, without ever
> making production hostage to the capacity lottery. Extends
> [`cpu-tiered-serving-plan-2026-07-16.md`](cpu-tiered-serving-plan-2026-07-16.md) (tier
> ladder, T2 = GPU) and implements the constraints from
> [`gpu-availability-async-pool-adversarial-review-2026-07-16.md`](gpu-availability-async-pool-adversarial-review-2026-07-16.md).
> Reachability per the tailscale/VCN plan (vlm-6 branch). Implementation ownership: a new
> service-side task (not ALTQ-1); this doc is the reviewed design baseline.

## Measured facts (2026-07-16 session — all verified, not estimated)

- **Limits (post-grant)**: `gpu-a10-count` AD-1 = 1 (held by stopped `acx-gpu-burst`),
  **AD-2 = 2, AD-3 = 1** — three ADs of launch headroom, concurrent usage target stays 1.
- **AD-1 remains `OUT_OF_HOST_CAPACITY`** (21:24Z); its slot is unusable for fresh
  launches until Oracle frees hosts or the stopped instance is terminated.
- **Capacity windows are real and minutes-scale**: AD-2 open at 18:18Z, closed by 19:54Z,
  open again 20:20Z; a 45 s-interval launch-retry loop caught it in 9 attempts (~7 min).
  `ComputeCapacityReport` is a **free, read-only, authoritative** detector (no launch
  needed to probe).
- **Window→serving ≈ 10 min**: launch 20:19:35Z → RUNNING ~3 min → baked
  `acx-gpu-vlm.service` (llama.cpp Qwen3-VL-30B-A3B Q4) active and answering by ≈20:30Z.
- **GPU value**: p50 **2.6 s/img** single-pass (golden-37, measured) vs 206 s/img CPU —
  ~80×. Two-pass 5.7 s, dual-length 3.5 s.
- **Cost**: ~$2/hr while RUNNING; failed launch attempts are free; stop releases the host
  (no warm pool possible — adversarial review finding, confirmed by Oracle docs).

## Design (constraints inherited from the adversarial review)

### Acquisition (demand-triggered, never per-request)

1. **Trigger**: GPU acquisition starts when the describe queue crosses a depth/age
   threshold (e.g. ≥ N jobs queued or oldest job > T_q), or an operator/test harness
   requests a window explicitly. Never one launch per request (thundering-herd finding).
2. **Singleflight launcher**: one launcher process per deployment holds an acquisition
   lease (DB row / advisory lock); concurrent triggers join the existing attempt. Every
   `LaunchInstance` call carries an idempotency token (`opc-retry-token`) so a timeout
   retry cannot double-launch [RES-01, DATA-13].
3. **AD rotation with capacity pre-check**: probe `ComputeCapacityReport` for AD-2 → AD-3
   (→ AD-1 when its slot frees); only attempt `launch` in ADs reporting `AVAILABLE`
   (probe is free; a blind launch burns a rate-limited mutating call). Bounded retry:
   45–60 s spacing + jitter, acquisition window ≤ W (default 30 min), then give up until
   the next trigger [RES-06].
4. **Readiness gate**: RUNNING ≠ serving. Dispatch to the box only after the model
   endpoint answers (`/v1/models`), with a boot deadline (default 15 min) before the
   instance is declared dud and terminated [RES-03].

### Serving + release

5. **Hold policy**: keep the instance while the queue is non-empty; start an idle timer
   when it drains; terminate after I idle minutes (default 10). The on-image 300 s
   idle-reaper stays as backstop. Every launch pairs with a terminate; a reconciler sweeps
   for orphans (instances tagged `acx-opportunistic-gpu` older than the max window)
   [RES-07].
6. **Fallback is the default path, not the exception**: jobs run on the CPU tier (T1d)
   whenever no GPU is held. GPU acquisition never blocks a job — the queue drains on CPU
   at CPU pace while the launcher works; jobs simply migrate to the GPU endpoint when it
   comes up. Zero jobs ever wait on the lottery [RES-14, RES-03].
7. **Provenance**: every response records the tier/model that actually served it
   (existing `adapter_kind`/`model_id` envelope); tier transitions are logged and counted
   [rg-015, OBS-01].

### Operator/user-facing state (UI toasts)

8. **Server truth**: the service exposes a small tier-state resource (current tier,
   since-when, queue depth, acquisition state: `idle | probing | launching | serving |
   degraded`) via the existing status surface — no fabricated metadata; the state comes
   from the launcher's lease row [rg-015].
9. **WP admin toasts fire on TRANSITIONS only** (not steady state):
   - `acquiring → serving`: "GPU acceleration active — descriptions now ~3 s/image."
   - `serving → degraded/released`: "GPU released — descriptions continue on CPU
     (~40 s/image)." (info, not error — CPU is the designed default).
   - acquisition gave up (window exhausted): one info toast, queue continues on CPU.
   - Status chips on the jobs panel pair color with an icon [sr-004]; toasts come from the
     existing notice system; polling uses the existing job-status poll — **never a gated
     `refetchInterval` returning `false`** (permanent-freeze gotcha).
10. **Testing mode**: the same launcher + state surface drives bake-off/test windows (the
    harness requests a window explicitly); test acquisitions are tagged distinctly so
    prod metrics exclude them.

## Cost envelope

- Steady state (no demand): $0 — no reservations, no warm pool.
- Active window: ~$2/hr, bounded by hold policy (I idle-minutes) + reaper.
- Worst-case month (window held 8 h/day): ~$480 — still 1/3 of one reservation; revisit a
  reservation only if sustained hold-hours × rate approaches $1,400/mo [PERF-07, ARCH-06].

## Decision rule for adoption

Ship the opportunistic tier only if the bake-off decision memo confirms the GPU model
materially beats the CPU tier on the expanded rubric (ALTQ-1 S5 gates); otherwise the
launcher remains a test-harness tool and prod stays CPU-only. Either way the CPU tier
remains the availability guarantee — the toast copy must never imply degraded = broken.

## Not-doing

- Warm pools of stopped instances (reserve nothing — verified) and per-request launches
  (adversarial review, dominated).
- Capacity reservations by default (cost; revisit on measured hold-hours).
- Cross-region rotation (image copy + privacy review first).
- Public-IP reachability (tailscale/VCN plan owns the network path).
