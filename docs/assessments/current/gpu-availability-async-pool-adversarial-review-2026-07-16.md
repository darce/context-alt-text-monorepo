# Adversarial review: "async pool of prebaked GPU images" for production availability

> Design idea pressure-tested against the engineering-heuristics canon
> (`darce/heuristics-canon/lexicons/engineering.md`, IDs verified live). Companion to the
> GPU procurement decomposition
> ([`gpu-procurement-reachability-decomposition-2026-07-16.md`](gpu-procurement-reachability-decomposition-2026-07-16.md))
> and the batch-compute runbook
> ([`../../runbooks/oci-vlm-batch-compute-learnings.md`](../../runbooks/oci-vlm-batch-compute-learnings.md)).

## The proposal (as stated)

> An async pool of 3 pre-baked prod images with all description + face-recognition dependencies.
> They rotate when a request comes in and try all AD regions until a GPU becomes available.
> Increases disk storage and up-time, but increases the chance a GPU is available.

## Verdict

The instinct is directionally right, but **as stated the design fails on availability's own terms**:
it has no bound, no fallback, and rests on a false premise about what a machine *image* provides.
It survives only if reframed as an **async, bounded, CPU-fallback autoscaler**.

## Findings (each grounded in a verified heuristic)

| # | Flaw | Heuristic | Concrete failure |
| --- | --- | --- | --- |
| 1 | **Images don't create capacity** | (domain fact: OCI capacity is per shape+AD host pool, not per image) | 3 images ≠ 3 GPUs. Any launch draws from the same pool already returning "out of host capacity." All 3 ADs dry (today's state) → the image pool provisions nothing. An image only lets baked weights *travel* to an AD that has a free host. |
| 2 | **Unbounded provisioning wait** | **RES-02** timeout on every blocking call | "try all ADs *until* a GPU is available" never returns during sustained scarcity → the plugin/user hangs forever. |
| 3 | **Slow failure worse than fast** | **RES-03** | cold-provision per request ≈ 90 s boot + 2–5 min model load; a user waits minutes for a caption, then may still fail on capacity. |
| 4 | **No crumple zone / fallback** | **RES-13** bugs are survived, not eliminated | assumes provisioning eventually succeeds; a multi-day A10 drought = total outage. |
| 5 | **Retry storm, no backoff/cap** | **RES-06** | every request × every AD × every concurrent caller hammers the OCI launch API, amplified, risking rate-limits. |
| 6 | **No circuit breaker** | **RES-15** | "out of capacity" is persistent, not a blip; the design keeps trying on every request instead of failing fast to a fallback. |
| 7 | **Unbounded queue / unbalanced tiers** | **RES-14 / RES-09** | front (request rate) ≫ back (GPU availability ≈ 0), no bounded queue → backlog → latency growth → crash. |
| 8 | **Cost of "uptime" + reclaim** | **RES-07** steady-state reclaimer | 3 warm GPUs 24/7 ≈ **$4,300/mo** (3 × $2 × 730 h) — defeats the burst model; image-only "uptime" is cheap but buys no availability. The idea conflates the two. |
| 9 | **Async only helps async work** | **CON-06** concurrency only helps independent I/O | async hides provisioning latency only for job-based work. **Redeeming:** face recognition here already *is* async (`analyze → wait_job`) — the escape hatch. |

## The steelman (what it becomes once fixed)

An **async job queue** + a **bounded pool of GPU workers** that autoscale from prebaked images,
rotating ADs **with a bounded timeout + shared backoff + a circuit breaker (RES-02/06/15)**, and —
the critical addition — **falling back to CPU-Florence workers** whenever no GPU is claimable
within the timeout. That is robust: GPU when available (quality/speed), CPU always (reliability),
never a hang. The prebaked-image + AD-rotation mechanics are a valid *component* of that
autoscaler — not a standalone availability strategy, and not "images = availability."

## Recommendation

Keep the async-queue + AD-rotation + prebaked-image mechanics, but:

1. **Drop "images = availability."** If a hard GPU floor is needed, add a warm-min (N running
   workers) or a capacity reservation — those cost money but actually guarantee capacity; images
   do not.
2. **Bound + circuit-break provisioning** (RES-02/06/15): a per-request GPU-claim timeout, shared
   backoff across callers, and a breaker that trips on repeated capacity failures and routes
   straight to CPU until it half-opens.
3. **Make CPU-Florence the guaranteed fallback** (RES-13) so there is never an unbounded wait.
4. **Separate the images.** Bundling description (torch/VLM) + face-recognition (onnx) deps into
   one fat prod image couples two services' lifecycles and bloats disk; keep them lean and
   separate (matches how prod ships today).

Net: this lands exactly where the procurement decomposition did — **CPU baseline (reliable,
privacy-safe) + GPU as an opportunistic / reservation-backed quality tier**, now with the
async-autoscaler shape to exploit GPUs opportunistically without ever hanging on their absence.
