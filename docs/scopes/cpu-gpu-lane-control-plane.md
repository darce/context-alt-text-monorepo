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
  **least-load** dispatch (MVP; on one GPU this degenerates to a concurrency
  semaphore — no worker registry/scoring until the pool slice; work-stealing also
  deferred) so fast GPUs take more and the slow worker never becomes the tail
  `[PERF-02]`, worker **health-check + circuit breaker** `[RES-15]` (liveness probe
  separate from the inference path — a loaded `/v1/models` is slow under full prefill;
  breaker thresholds sized to loaded VLM latency, with half-open recovery), and
  **timeout on every call** `[RES-02]`.
  **Retry taxonomy** `[RES-06][API-08][AGT-09]`: **retryable** = 429/408/5xx/timeouts
  with backoff + jitter + cap (honor `Retry-After`); **terminal 4xx** = dead-letter;
  **deterministic payload errors** (e.g. the webp/avif case) = format-fix path, never
  blind re-send unchanged. Items that exhaust the retry cap — and **poison items that
  kill workers** (after K worker-death attributions for the same `media_id`,
  dead-letter it and stop re-feeding it) — land in an explicit **dead-letter/errored
  terminal state that still appears in the run-record** (`status=error`), never
  silently dropped. Per constitution `rg-007`, the dispatcher loop tracks **per-item
  no-progress cycles with a bounded threshold** (a lease requeue does **not** reset an
  item's progress counter) and exits non-zero on global stall; one item's failure never
  halts the batch.
  **Deterministic — no LLM in the loop:** dispatch is a solved load-balancer; an LLM
  adds a boundary crossing `[PERF-09]` + nondeterminism for zero judgment benefit.
- **GPU workers (stateless):** one model, N lanes, behind the **OpenAI API** so the
  control plane is stack-agnostic `[SERVE-01]`. They do nothing but inference — keeps
  the GPU host's CPU dedicated to feeding the GPU (a co-located busy dispatcher can
  starve the feed → idle GPU).
  **Worker lifecycle (MVP): operator-owned.** Operators launch workers and run a
  terminate-on-queue-drain runbook; control-plane-driven OCI instance orchestration
  (instance-principal auth, launch/terminate from the CPU box) is a **later slice** —
  it is a materially larger security scope than dispatch.
  **Image transport:** images already sit on the CPU box (the `~/uploads` pattern,
  downscaled ≤1280px). Whether they ship base64-inline or via local HTTP fetch — and
  the payload size ceiling — is a named task-plan decision; lease/timeout budgets and
  CPU-box bandwidth depend on it.
- **Durable requeue = a two-part lease contract** (not bare `SKIP LOCKED`):
  1. **Claim:** a *short* transaction — `SELECT … FOR UPDATE SKIP LOCKED` for the
     atomic claim `[CON-11]`, stamp `leased_until`, **commit**. Inference never runs
     inside a DB transaction.
  2. **Reap:** a reaper requeues items whose lease expired (worker died/hung).
     **Lease TTL ≥ measured worst-case inference latency at the chosen N lanes × a
     safety factor** (or heartbeat renewal) — a too-short lease double-dispatches
     still-running items; duplicate inferences are counted and reported in the
     run-record as a cost metric.
  **Completion = write-result-then-ack**: the result row lands before the queue item is
  acked, so a crash between the two re-runs the item instead of losing it.
  **At-least-once is safe because describe is idempotent** `[RES-01]`: dedup key
  `UNIQUE(run_id, media_id)` with first-write-wins `[DATA-13]` — racing completions
  after a lease expiry are dropped at the constraint, not double-counted.
  The project already runs identity Postgres → natural fit. **MVP simplification:** the
  single dispatcher process is the *only* queue consumer — that is what makes a
  SQLite-backed MVP queue safe (`SKIP LOCKED` becomes necessary only when consumers
  multiply). No JSONL "queue" — it has no atomic claim or crash-safe requeue.
- **Concurrency ceiling = benchmarked, not assumed** `[PERF-04][PERF-06]`: sweep
  lanes/GPU (1→2→4→8) on a production-representative image-size distribution, watch
  throughput / p95 / VRAM. VLM is **prefill-heavy** → the ~2–4× per GPU expectation is
  a **hypothesis for the benchmark**, not a promise.
- **Pool > per-GPU lanes for wall-time:** M GPUs ≈ M × per-GPU throughput **only up to
  Amdahl's serial fraction** `[PERF-04]` — here the shared dispatcher and the Postgres
  claim/result-write path; the pool slice must name and measure them. Pool scale is
  **capacity-gated** (A10 scarcity) → the design must degrade to single-GPU-N-lanes.

Serving-stack choice is deferred to a benchmark slice (per intake): **vLLM continuous
batching** (higher ceiling) vs **llama.cpp `--parallel`/`--cont-batching`** (reuses the
warm image). Both are OpenAI-compatible, so the *control plane* is indifferent
`[SERVE-01]` — but the **benchmark is not apples-to-apples by default**: the pinned
production artifact is Qwen3-VL-30B-A3B **Q4 GGUF** baked into the llama.cpp warm image
(`benchmarks/HARDWARE.md`), and vLLM does not serve GGUF vision models — it needs a
safetensors requant (AWQ/FP8), a **new image bake**, and quality re-validation against
the DESCQUAL-validated pinned model. The benchmark slice must state its quant-parity
policy and budget the vLLM image bake, or accept quality re-validation as part of the
slice.

## MVP — smallest shippable cut (pessimist / YAGNI)

1. **Pool-feasibility gate:** A10 concurrent-instance service limit + free
   `compute-capacity-report` probe → max concurrent A10s. The probe is a *planning*
   gate (point-in-time — capacity can vanish between probe and launch); the existing
   `benchmarks/runners/a10-launch-retry.sh` multi-AD rotation stays the *runtime*
   fallback.
2. **Stack benchmark (1 GPU):** concurrency sweep on vLLM and llama.cpp `--parallel`
   under the quant-parity policy above → pick lanes-per-GPU N and the stack.
3. **Control plane v1:** durable queue of `media_id` items + async dispatcher keeping
   N lanes busy on **one** GPU; the lease contract, retry taxonomy, and dead-letter
   path above; results dedup on `UNIQUE(run_id, media_id)`. **Reuses the run-record
   JSON *shape*** (per-item rows: `media_id`, status `ok`/`error`, latency, model —
   anchor: `scripts/eval_harness/build_bakeoff_report.py` + the driver run-record
   contract, currently on the unmerged `altq-1` branch; **ordering dependency:**
   altq-1 merges first, or this slice vendors exactly that field list).
   **Per-item incremental persistence is *new work* in this slice** — the current
   driver writes the record once at the end (partial only on stall-abort; the
   646-corpus run lost 5 items that way). The dispatcher is crash-safe: on restart it
   **resumes from the durable queue** (leases expire → in-flight items requeue); no
   batch state lives only in process memory.
4. **Pool fan-out (only if the limit allows):** worker registry + health + breaker;
   dispatcher spreads across M warm workers; a dead worker is replaced via the
   operator/launch-retry path (control-plane-driven replacement is the later
   lifecycle slice).

## Success criteria

- **Speed:** batch wall-time matches the **benchmarked concurrency knee ± tolerance**
  on a timed 646-image run `[DIAG-08]` — knee ≥2× vs single-lane is the *goal*, not a
  gate that fails a correctly-built control plane if the knee measures lower.
  **If** the pool gate grants ≥2 GPUs: aggregate throughput **≥0.8×M**.
- **Resilience:** kill a worker mid-batch **and** kill/restart the dispatcher mid-batch →
  **0 unaccounted images** (every `media_id` present in the final run-record as `ok` or
  an explicit `error`/dead-letter row); the batch finishes on the survivors. Duplicate
  inferences (lease-expiry re-runs) are reported, not silent.
- **Cost:** per-image cost = batch wall-time × hourly rate ÷ images, reported via the
  existing `--hourly-rate` column, compared against the single-lane baseline; adding a
  pool worker requires enough remaining batch to amortize its boot + model-load warmup.
- **Determinism:** the **dispatch path** is deterministic and LLM-free; inference
  outputs are not reproducible (sampling, batching numerics) and are not claimed to be.

## Assumptions

Describe is idempotent (safe at-least-once). Warm custom image + multi-AD launch-retry
exist **for llama.cpp/GGUF**; a vLLM stack choice requires a new bake. All workers
expose the OpenAI `/v1/chat/completions` API.

## Not-Doing (MVP)

- Interactive / priority scheduling + latency SLOs (later slice).
- Control-plane-driven OCI instance lifecycle (launch/terminate from the CPU box) —
  operator-owned in MVP; later slice.
- CPU as an **inference** worker (ruled out — too slow for the GPU models).
- Autoscale-to-zero, cross-region beyond multi-AD.
- A bespoke queue broker if single-consumer SQLite / Postgres `SKIP LOCKED` suffices.
- MIG GPU partitioning (A10 does not support it).

## Open / feasibility gates

- OCI **A10 concurrent-instance limit + capacity** (gates pool scale).
- **Stack + lanes-per-GPU** (benchmark output, under the quant-parity policy).
- **Image transport choice** (base64-inline vs local fetch) + payload size ceiling.
- **Full-queue policy** for `[RES-14]` — moot for a fixed batch, load-bearing the
  moment the queue fronts a stream; name it before any streaming use.
- **Runtime VRAM-OOM response** at the benchmarked N (e.g. shed lanes), distinct from
  the benchmark-time VRAM axis.

**Ready for assessment → task-plan now.** MVP steps 1–2 *are* the open gates: the
task-plan's first slices run them, and their outputs (pool limit, stack, N)
parameterize steps 3–4.
