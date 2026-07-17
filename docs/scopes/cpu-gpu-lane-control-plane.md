# Scope: CPU control plane for GPU inference lanes (2026-07-17)

> `/scope` intake note — intent + heuristics-grounded **direction**; detailed design
> belongs to the downstream assessment/task-plan. Intake decision:
> `cc_scope_gpu_lanes_intake` (handoff, task `gpu-lanes-scope`). Perf/cost context:
> [inference-cost forecast](../gtm/inference-cost-and-unit-economics-forecast.md)
> (*pending-landing — drafted under MAINT `gtm-cost-forecast`, not yet committed; land it
> before or with this note or the link 404s*), VLM-6 bake-offs. Heuristics cited by
> stable ID from `github.com/darce/heuristics-canon`.

## Problem

Image batch description is bottlenecked by **single-lane** GPU serving (one request
in flight; the bake-off ran `--parallel 1` behind a sequential driver). A GPU has spare
parallelism, and a cheap always-on CPU can drive concurrent lanes **and** hold a durable
queue — cutting batch wall-time and surviving GPU churn. Goal: **effective
parallelization for batch speed + resilience.**

## Intake (recorded — `cc_scope_gpu_lanes_intake`)

| Question | Answer |
| --- | --- |
| Scope | **Batch throughput only** (MVP); interactive-priority deferred |
| Scale | **GPU pool (multi-AD) if Oracle allows** — verify limit + capacity first; degrade to single-GPU |
| Resilience | **Durable requeue — no lost images** |
| Serving stack | **Benchmark** vLLM vs llama.cpp `--parallel` before committing |

## Heuristics-grounded direction (the decision)

The canon converges on a **control-plane / data-plane split**:

- **CPU control plane (cheap, always-on):** durable **bounded** work queue `[RES-14]`,
  **least-load** dispatch (MVP; work-stealing deferred to the pool slice) so fast GPUs
  take more and the slow worker never becomes the tail `[PERF-02]`, worker
  **health-check + circuit breaker** `[RES-15]`, **timeout on every call** `[RES-02]`,
  retry **backoff/jitter/cap** `[RES-06]`, and **never blind-retry a 4xx** `[AGT-09]`
  (today's webp/avif case → format-fix path). Items that exhaust the retry cap land in
  an explicit **dead-letter/errored terminal state that still appears in the run-record**
  (`status=error`) — never silently dropped. Per constitution `rg-007`, the dispatcher
  loop tracks **per-item no-progress cycles with a bounded threshold** and exits non-zero
  on global stall; one item's failure never halts the batch.
  **Deterministic — no LLM in the loop:** dispatch is a solved load-balancer; an LLM
  adds a boundary crossing `[PERF-09]` + nondeterminism for zero judgment benefit.
- **GPU workers (stateless):** one model, N lanes, behind the **OpenAI API** so the
  control plane is stack-agnostic `[SERVE-01]`. They do nothing but inference — keeps
  the GPU host's CPU dedicated to feeding the GPU (a co-located busy dispatcher can
  starve the feed → idle GPU `[RES-09]`).
- **Durable requeue = lease / visibility-timeout:** an item is leased to a worker;
  if not ack'd within a timeout (worker died/hung) it returns to the queue. **At-least-once
  is safe because describe is idempotent** `[RES-01][DATA-13]` (dedup on `media_id` at
  write). Postgres `SELECT … FOR UPDATE SKIP LOCKED` is the classic durable-lease queue
  with an atomic claim `[CON-11]`; the project already runs identity Postgres → natural
  fit. MVP may start on SQLite/JSONL on the CPU box (YAGNI a broker).
- **Concurrency ceiling = benchmarked, not assumed** `[PERF-04][DIAG-08]`: sweep
  lanes/GPU (1→2→4→8), watch throughput / p95 / VRAM. VLM is **prefill-heavy** →
  expect **~2–4× per GPU**, not 8×.
- **Pool > per-GPU lanes for wall-time** `[PERF-04]`: M GPUs ≈ M × per-GPU throughput,
  while per-GPU lanes cap at ~2–4×. But pool scale is **capacity-gated** (A10 scarcity)
  → the design must degrade to single-GPU-N-lanes.

Serving-stack choice is deferred to a benchmark slice (per intake): **vLLM continuous
batching** (higher ceiling) vs **llama.cpp `--parallel`/`--cont-batching`** (reuses the
warm image). Both are OpenAI-compatible, so the control plane is indifferent `[SERVE-01]`.

## MVP — smallest shippable cut (pessimist / YAGNI)

1. **Pool-feasibility gate:** A10 concurrent-instance service limit + free
   `compute-capacity-report` probe → max concurrent A10s.
2. **Stack benchmark (1 GPU):** concurrency sweep on vLLM and llama.cpp `--parallel`
   → pick lanes-per-GPU N and the stack.
3. **Control plane v1:** durable queue of `media_id` items + async least-load dispatcher
   keeping N lanes busy on **one** GPU; timeout + idempotent retry + **lease-requeue on
   failure**; retry-cap exhaustion → dead-letter row in the run-record; results dedup by
   `media_id`; reuses the incremental, partial-report-safe run-record shape
   (**anchor:** `scripts/eval_harness/build_bakeoff_report.py` + the driver run-record
   JSON contract — currently on the unmerged `altq-1` branch; **ordering dependency:**
   altq-1 merges first, or this slice vendors the record shape).
   The dispatcher itself is crash-safe: on restart it **resumes from the durable queue**
   (leases expire → in-flight items requeue); no batch state lives only in process memory.
4. **Pool fan-out (only if the limit allows):** worker registry + health + breaker;
   dispatcher spreads across M warm workers; multi-AD launch-retry replaces a dead one.

## Success criteria

- **Speed:** batch wall-time cut to the measured concurrency knee — target **≥2×** vs
  single-lane on one GPU, and near-linear across a pool — proven by a **timed 646-image
  run**, not a local guess `[DIAG-08]`.
- **Resilience:** kill a worker mid-batch **and** kill/restart the dispatcher mid-batch →
  **0 unaccounted images** (every `media_id` present in the final run-record as `ok` or
  an explicit `error`/dead-letter row); the batch finishes on the survivors.
- **Cost:** per-image cost stays at the inference floor (no idle-GPU tax), reported via
  the existing `--hourly-rate` column.
- **Determinism:** no LLM in the dispatch path; reproducible.

## Assumptions

Describe is idempotent (safe at-least-once). Warm custom images + multi-AD launch-retry
already exist. All workers expose the OpenAI `/v1/chat/completions` API.

## Not-Doing (MVP)

- Interactive / priority scheduling + latency SLOs (later slice).
- CPU as an **inference** worker (ruled out — too slow for the GPU models).
- Autoscale-to-zero, cross-region beyond multi-AD.
- A bespoke queue broker if Postgres `SKIP LOCKED` / SQLite suffices.
- MIG GPU partitioning (A10 does not support it).

## Open / feasibility gates

- OCI **A10 concurrent-instance limit + capacity** (gates pool scale).
- **Stack + lanes-per-GPU** (benchmark output).

Ready for assessment → task-plan → planning-review once the pool-limit and benchmark
gates return.
