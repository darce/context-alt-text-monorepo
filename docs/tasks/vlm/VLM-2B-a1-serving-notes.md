# VLM-2B — A1 Candidate Serving Notes (Slice 2)

> **Metadata**
>
> - **Date**: 2026-07-07 EST
> - **Host**: OCI A1 (`acx-backend`, aarch64, 4 cores Neoverse-N1, 24 GB RAM, CPU-only)
> - **Runtime**: llama.cpp release `b9893` prebuilt `ubuntu-arm64` (`~/vlm2b/bin`), `libgomp1` installed
> - **Serving config**: `llama-server --threads 3 --parallel 1 --ctx-size 8192`, `nice -n 10`, bound to `127.0.0.1:8099` (concurrency 1, off the demo path; demo/prod containers untouched)
> - **Bench**: `~/vlm2b/bench.sh` — cold load to `/health`, one greedy 512-max-token caption of `ccqw-antartica.jpg` via `/v1/chat/completions`, peak RSS from `VmHWM`

## Latency / RSS table

| Candidate | GGUF (official repo) | Quant | Cold load (s) | 1-image latency (s) | Peak RSS (MB) | Caption sane? |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen3-VL-4B-Instruct | `Qwen/Qwen3-VL-4B-Instruct-GGUF` + `mmproj-…-Q8_0` | Q4_K_M | 27.2 | 229.8 | 7,029 | yes |
| CapRL-Qwen3VL-4B | `internlm/CapRL-Qwen3VL-4B-GGUF` + `…-mmproj-Q8_0` | Q4_K_M | 37.3 | 236.4 | 6,935 | yes |
| MiniCPM-V 4.5 | `openbmb/MiniCPM-V-4_5-gguf` + `mmproj-model-f16` | Q4_K_M | 72.8 | 231.5 | 11,165 | yes |

Prompt-eval dominates: the Qwen-family mmproj encodes the image to ~1,571 prompt tokens (MiniCPM: 703) and CPU prefill is the bottleneck; completion length barely moves the total.

## §13 estimate: resolved

The assessment's **1–3 min/img estimate is denied** — measured ≈ **3.8–3.9 min/img** for all three candidates at Q4_K_M, 3 threads, greedy, single 512-token caption. All three load and run; none disqualifies on feasibility. MiniCPM-V 4.5 needs ~11 GB peak RSS (8B params) — fits the 24 GB box alongside the demo stack, but only one candidate may be resident at a time.

## Per-request timeout ceiling

**600 s** (`--timeout 600` on `scripts.eval_harness.bakeoff`): ~2.5× the measured worst case (236 s), absorbing shared-box jitter without letting a hung request stall the run unboundedly (rg-007; breaker + bounded-stall still apply). Full bake-off cost estimate: 10 images × ~4 min × 3 candidates ≈ **2 h serial**.

## Slice-4 corrections (live-run findings)

- **`--image-max-tokens 1536` is required.** The bench image encoded to ~1.5 k prompt tokens, but Qwen3-VL dynamic resolution scales image tokens with input size: larger golden images blew past 600 s and the first Qwen run aborted via bounded-stall (rg-007 behaving as designed). Capping image tokens at 1536 restores the bench profile (mean 206–208 s/img) identically for all candidates; the ceiling was raised to **900 s** for headroom.
- **MiniCPM-V 4.5 hybrid thinking**: neither `--reasoning-budget 0` (ignored by the GGUF chat template) nor `/no_think` reliably disables it — 4/10 images returned empty captions with the 512-token budget consumed by `reasoning_content`. See the decision memo.
- **Tailscale SSH quirks** (driver plumbing): `pkill -f` patterns match the SSH session's own `--cmd` string (kill and launch must be separate calls), and launch sessions never exit even for `setsid`-daemonized children (background the local `ssh` and kill it explicitly).

## Reproduce

```bash
ssh ubuntu@acx-backend.tail1a44b8.ts.net
cd ~/vlm2b
./bench.sh Qwen3VL-4B-Instruct-Q4_K_M.gguf mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf qwen3vl-4b
./bench.sh CapRL-Qwen3VL-4B-Q4_K_M.gguf CapRL-Qwen3VL-4B-mmproj-Q8_0.gguf caprl-4b
./bench.sh MiniCPM-V-4_5-Q4_K_M.gguf mmproj-model-f16.gguf minicpm-v45
```

Serving for the Slice 4 live runs uses the same flags; the laptop drives the endpoint through an SSH tunnel (`ssh -L 8099:127.0.0.1:8099 …`), so no candidate port is ever exposed off-box.
