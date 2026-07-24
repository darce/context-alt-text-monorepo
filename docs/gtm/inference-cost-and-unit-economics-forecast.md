# Inference cost & unit-economics forecast (2026-07-17)

> **Purpose (GTM):** forecast the **per-image inference cost** of the shipped
> description service so pricing and unit economics rest on measured data, not
> guesses. Companions: [`altcontext-productization-launch-plan.md`](altcontext-productization-launch-plan.md),
> [`../assessments/current/cpu-tiered-serving-plan-2026-07-16.md`](../assessments/current/cpu-tiered-serving-plan-2026-07-16.md),
> [`../../benchmarks/`](../../benchmarks/). Cost data provenance: VLM-6 bake-offs
> (handoff decisions `cc_vlm6_*`, 2026-07-17).

## TL;DR

- **Production per-image inference cost is forecast at ~$0.0005–$0.003.** Warm GPU
  single-stream ≈ **$0.003/img**; with continuous batching ≈ **$0.0005/img**;
  CPU fallback (A1) ≈ **$0.002/img**.
- The **$0.10–$0.25/image** seen in the bake-offs is **not a production number** —
  it is ~99% model-**download tax**, an artifact of renting a GPU to pull many
  models one-off. Production serves **one** model from a **warm pre-baked image**,
  so downloads cost ~$0.
- **Utilization — not downloads — is the real cost lever.** cost/image = `$/hr ÷ images/hr`.
  An idle GPU is the expensive failure mode.

## Measured anchors (VLM-6, 2026-07-17)

| host | rate | model | latency/img | note |
| --- | --- | --- | --- | --- |
| **A10 GPU** (VM.GPU.A10.1) | **$2.00/hr** | Qwen3-VL 8B/30B-A3B | **~6 s** (warm) | bake-off means 5.7–6.8 s |
| **A1.Flex CPU** (8 OCPU/48 GB) | **$0.152/hr** | Qwen3-VL-4B Q4 | **~48 s** | full-corpus run, images ≤1280 px |

Rates are flat time-based (billed regardless of load). Per-image cost is therefore
deterministic: `rate × inference-seconds` (no billing API needed — the harness
records per-image latency; see the `--hourly-rate` column in bake-off reports).

## Why the bake-off number is not the product number

The bake-offs paid a **download tax**: each candidate model (5–17 GB GGUF, or an
11 GB vLLM download) was pulled onto a freshly-rented GPU that then described only
4–10 images. The GPU spent ~30 min billed but only ~2–5 min inferencing → **amortized
$0.10–$0.25/image**, ~99% of it download/serve overhead.

**Production removes this entirely.** The service boots from a **warm custom image**
with the chosen model + runtime pre-installed on the boot/block volume — instance is
ready-to-serve with **zero download**. This pattern is already built here: the
bake-offs booted from `acx-gpu-vlm-multiad-20260716` (weights baked in), and
`benchmarks/runners/a10-launch-retry.sh` **rotates AD-2 → AD-3** to beat A10 capacity
scarcity. Image storage/replication is a one-time, negligible-when-amortized snapshot.

## Cost model & forecast

**`cost/image = instance $/hr ÷ throughput (images/hr)`.** On a warm GPU the only
variables are inference speed and utilization:

| config | rate | throughput | **$/image** | basis |
| --- | --- | --- | --- | --- |
| bake-off (cold, download-bound) | $2/hr | ~8–20 eff. | $0.10–0.25 | measured |
| **warm A10, single-stream** (~6 s/img) | $2/hr | ~600/hr | **~$0.003** | measured latency |
| **warm A10 + vLLM continuous batching** (4–8×) | $2/hr | ~2,400–4,800/hr | **~$0.0004–0.0008** | forecast |
| A1 CPU fallback (Qwen-4B, ~48 s/img) | $0.152/hr | ~75/hr | **~$0.002** | measured |

→ **Forecast: ~$0.003/image single-stream, ~$0.0005/image batched** — a **100–500×**
reduction vs the cold bake-off, almost entirely from (a) warm images and (b) keeping
the GPU busy.

## Utilization sensitivity (the dominant lever)

`$/image = $2/hr ÷ images/hr`, so cost/image is set by how busy the GPU is:

| effective throughput | $/image (A10) |
| --- | --- |
| 3,000/hr (batched, saturated) | $0.0007 |
| 600/hr (single-stream, saturated) | $0.0033 |
| 100/hr (light traffic, GPU idle 83%) | $0.020 |
| 20/hr (trickle on an always-on GPU) | $0.10 |

A GPU idle 50% of the time **doubles** cost/image. Cost is won by **continuous
batching (vLLM) + request queueing + right-sizing**, and — for spiky/low volume —
**autoscale-to-zero or a CPU-fallback tier** so we never pay $2/hr to describe a trickle.

## CPU/GPU crossover

- **Low volume:** the cheap always-warm **A1 CPU (~$0.002/img)** can beat an
  under-utilized GPU — no capacity lottery, no idle-GPU tax. This is the
  [tiered-serving](../assessments/current/cpu-tiered-serving-plan-2026-07-16.md) T1d fallback.
- **High volume:** the **batched GPU (~$0.0005/img)** wins decisively on both cost
  and latency (~6 s vs ~48 s/img).
- Per-image *inference* cost is similar single-stream ($0.003 GPU vs $0.002 CPU) —
  the A10's 13× rate and ~8× speed roughly cancel; batching + volume is what separates them.

## Unit-economics implication

At **≤$0.003/image**, inference is a rounding error against any plausible per-image
or per-seat price. Even a conservative single-stream GPU leaves **>99% gross margin**
on inference for a product priced in cents-per-image or a monthly plan. The unit-economics
risks are **not** inference cost — they are (1) **GPU capacity availability** (mitigated
by multi-AD warm-image rotation), (2) **idle-GPU spend under low/spiky load** (mitigated
by autoscale-to-zero + CPU fallback), and (3) **egress/storage** (small). Pricing can
be set on value, not COGS.

## Caveats & next steps

- **Measured vs forecast:** rates and per-image latencies are measured; the *batched*
  throughput (4–8×) is a forecast — confirm with a vLLM continuous-batching load test
  on a warm A10 before quoting the $0.0005 figure externally.
- **Model choice** shifts latency (30B-A3B MoE ≈ 8B dense in practice); re-anchor when
  the VLM-6 winner is chosen.
- **Next:** (1) warm-image + multi-AD rotation runbook (extends `a10-launch-retry.sh`);
  (2) vLLM batching load test → replace the batched forecast with a measured number;
  (3) fold cost/image into the pricing model in the launch plan.
