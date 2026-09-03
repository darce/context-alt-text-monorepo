# VLM-3 Slice 7a — Live GPU Spike Bench Findings (2026-07-14)

Measured evidence replacing the null Slice-1 stub. Model: **Qwen3-VL-30B-A3B-Instruct
Q4_K_M GGUF** (~18.6 GB + ~1 GB F16 mmproj) on **VM.GPU.A10.1** (1× A10 24 GB),
served by `ghcr.io/ggml-org/llama.cpp:server-cuda` on `:8000`. Artifacts:
`VLM-3-gpu-spike-2026-07-14{,-400gb,-400gb-60vpu,-750gb-balanced}.json`.
The 750 GB Balanced artifact's warm-start p50/p95 values have **n=3 warm starts**;
its throughput p50/p95 has **n=1 image** and is not a distribution estimate.

## Headline results

- **The A10 serves the model.** Qwen3-VL-30B Q4 fits 24 GB VRAM and serves an
  OpenAI-compatible endpoint. Core VLM-3 premise proven.
- **Throughput is excellent: ~0.58 s/image** (n=1 image in each configuration;
  plan assumed ~5 s — 9× better). Inference was never the bottleneck.
- **Cold-start = model reload, and it is boot-volume-throughput-bound.** A scale-to-zero
  STOP clears VRAM + page cache, so every warm-start reloads the full ~18.6 GB from disk.

## Boot-volume latency/cost frontier (warm-start p95 vs the 90 s target)

Standing $/mo is the boot volume, which **bills continuously even while STOPPED** (the
real scale-to-zero cost; compute is $0 between bursts).

| Boot volume | disk throughput | model_load | warm-start p95 (n=3 warm starts) | ~$/mo | verdict |
| --- | --- | --- | --- | --- | --- |
| 100 GB @ 10 VPU (Balanced) | ~44 MB/s | 426 s | 443.9 s | ~$4 | ❌ |
| 400 GB @ 30 VPU | ~175 MB/s | 107 s | 111 s | ~$31 | ❌ |
| 750 GB @ 10 VPU (Balanced) | ~212 MB/s | 88 s | 106 s | ~$32 | ❌ |
| 400 GB @ 60 VPU | ~264 MB/s | 70 s | 92.5 s | ~$51 | ❌ (by 2.5 s) |
| **400 GB @ 120 VPU** | ~326 MB/s | 57 s | **85.1 s** | ~$92 | ✅ **only strict pass** |

Costs approximate — verify against the OCI price list. Formula:
`GB × ($0.0255 storage + VPU × $0.0017 perf) / month`.

## Analysis

- **VPU returns are sublinear** (~5.8 / 4.4 / 2.7 MB/s per VPU at 30 / 60 / 120), so the
  load stays disk-bound across the range; only 120 VPU clears 90 s.
- **"Big Balanced volume" does NOT beat high-VPU** (disproven): 750 GB Balanced = 212 MB/s
  and 106 s p95 (n=3 warm starts), versus 400 GB @ 60 VPU = 264 MB/s.
  Balanced is not cheaper-per-MB/s at scale.
- **Diminishing returns:** $32 → $92/mo (3×) buys only 106 s → 85 s (~20%).

## Recommendation (7c boot-volume spec)

- **Strict 90 s SLO →** `gpu_boot_volume_size_in_gbs=400`, `gpu_boot_volume_vpus_per_gb=120`
  (~$92/mo). The only clean pass.
- **Relaxed target (recommended) →** `400 @ 30 VPU` or `750 Balanced` (~$31-32/mo,
  ~106-111 s p95, n=3 warm starts per configuration). Justified because **warm-start is NOT user-facing** — the
  `provisional_cpu → final_gpu` async supersede returns a CPU answer instantly and
  upgrades it later. The 90 s target is likely too strict for a hidden warm-up.
- **The biggest lever is the model, not the volume (→ 7b):** load time ∝ model bytes.
  A smaller Tier-2 dense candidate (~8 GB) loads in ~⅓ the time → sub-30 s warm-start on
  a cheap volume. 7b must weight **load-time alongside quality**.

## Reducing warm-start further WITHOUT an always-on instance

The reload is unavoidable (OCI has no VRAM snapshot; keep-warm is off the table
pre-revenue). Levers, cheapest first:

1. **Smaller/faster model (7b)** — free, biggest win.
2. **Start-on-enqueue pipelining** — START the GPU when the first item enqueues so the
   ~85 s warm-up overlaps queue build-up + CPU provisionals (async, $0 extra).
3. **Batch amortization** — warm-up cost ÷ N images.
4. **Faster/bigger volume** — buy speed only when paying load justifies the standing $.
5. **Async supersede (already built)** — users never wait.

## Provisioning + bench topology (how this was run — reuse for 7b/7c)

- **Golden image** `acx-gpu-qwen3vl30b-golden` = `<golden-image-ocid>`
  (AVAILABLE; identifier operator-held, not in repo). Reprovision a serving A10
  in ~2 min from it — no re-bake.
- **NSG** `acx-gpu-bench-nsg`
  (`<gpu-nsg-ocid>`)
  opens `:8000`/`:22` intra-VCN only (per-vNIC, no shared-SL change). Attach it to a new
  GPU vNIC.
- **Bench path:** run `scripts/gpu_spike_bench.py` from the operator laptop (has oci-CLI +
  admin key for STOP/START) with an SSH tunnel
  `localhost:18000 → acx-backend(tailscale) → <gpu-private-ip>:8000`. The subnet SL blocks
  `:8000`/`:22` from all but one operator IP, so this tunnel + NSG is the way in.
- Bake cloud-init: `infra/oci/gpu-bake-cloud-init.yaml` (resilient curl download, serial
  console heartbeat, self-STOP on completion). The narrative map is
  `infra/oci/INFRA-TOPOLOGY.md`; live identifiers are operator-held and not in repo.

## Gotchas the next agent must know

- **`hf_xet` Python backend hangs mid-file** (~9.5 GB) — use resilient `curl -C -
  --retry-all-errors --speed-limit/--speed-time` for HF Xet GGUFs, not `hf_hub_download`.
- **Guest `poweroff` is unreliable** from cloud-init — stop instances via **control-plane
  STOP**, never trust guest self-poweroff for billing safety.
- **GPU hosts are unobservable via SSH** (SL) and the **OCI agent run-command sticks at
  ACCEPTED** — self-report via **serial console** (`oci compute console-history`) + a
  periodic heartbeat; the ring buffer only shows the latest line.
- **A10.1 has no local NVMe** (`local-disks: 0`) — the model must live on the boot volume.
- Boot-volume **VPU/size resize is online** (`oci bv boot-volume update`) and lets you
  re-bench configs without re-downloading the model.
