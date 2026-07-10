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
| MiniCPM-V 4.5 | `openbmb/MiniCPM-V-4_5-gguf` + `mmproj-model-f16` | Q4_K_M | 72.8 | 231.5 | 11,165 | on 1 bench image only¹ |

> These are **single-image bench numbers on the uncapped serving config** (`ccqw-antartica.jpg`, one greedy caption). They are NOT the live-run profile — see Slice-4 corrections: the live protocol added `--image-max-tokens 1536`, and the golden-corpus live mean was ~206–208 s/img (the number the decision memo quotes). The two latency figures belong to two different configs; do not reconcile them.

¹ MiniCPM produced a sane caption on this one bench image, but the Slice-4 live run exposed a disqualifier: 4/10 golden images returned **empty captions** (hybrid thinking consumed the 512-token budget as `reasoning_content`; neither `--reasoning-budget 0` nor `/no_think` reliably disabled it). See the decision memo — the §13 "none disqualifies on feasibility" line reflects only the single-image bench, not the live run.

Prompt-eval dominates: the Qwen-family mmproj encodes the image to ~1,571 prompt tokens (MiniCPM: 703) and CPU prefill is the bottleneck; completion length barely moves the total.

## §13 estimate: resolved

The assessment's **1–3 min/img estimate is denied.** A single greedy caption of one bench image (`ccqw-antartica.jpg`, uncapped) measured ≈ **3.8–3.9 min/img**; this is an n=1 point estimate and image-token count scales with input size, so it is neither an upper bound (larger uncapped goldens exceeded 600 s) nor the eventual mean (the capped live run settled at ~3.4 min/img — memo quotes ~3.5). The directional verdict holds: no candidate runs in 1–3 min/img, and all three load and run. MiniCPM-V 4.5 needs ~11 GB peak RSS (8B params) — fits the 24 GB box alongside the demo stack, but only one candidate may be resident at a time.

## Per-request timeout ceiling

**Final: 900 s** (`--timeout 900`, the code default in `scripts.eval_harness.bakeoff`). The Slice-2 value of **600 s** was superseded in Slice 4: uncapped Qwen3-VL dynamic resolution pushed large golden images past 600 s and the first live run aborted via bounded-stall (rg-007 working as designed). The live protocol raised the ceiling to 900 s **and** added `--image-max-tokens 1536` (see Slice-4 corrections); with the cap, healthy items run ~206–208 s/img, well under the ceiling. Breaker + bounded-stall still apply. Full bake-off cost estimate: 10 images × ~3.5 min × 3 candidates ≈ **1.75 h serial**.

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

Serving for the Slice 4 live runs uses the bench flags **plus `--image-max-tokens 1536`** (required — without it Qwen3-VL dynamic resolution blows the timeout on large images; see Slice-4 corrections). The full live serving command is:

```bash
llama-server --threads 3 --parallel 1 --ctx-size 8192 --image-max-tokens 1536 \
  -m <model>.gguf --mmproj <mmproj>.gguf --host 127.0.0.1 --port 8099
```

### Driver (live bake-off)

Run from `apps/prototype-description-service` (the module path `scripts.eval_harness` only resolves there). Both env vars are required safety/corpus gates — `bakeoff` exits immediately without them:

```bash
cd apps/prototype-description-service
export ACX_EVAL_LIVE=1
export GOLDEN_IMAGES_DIR=/path/to/golden-fixtures   # rsync-bootstrapped copy; see scene/tests/seed/README.md
uv run python -m scripts.eval_harness.bakeoff \
  --endpoint http://127.0.0.1:8099 \
  --model-id <id> \
  --model-version Q4_K_M \
  --timeout 900 \
  --manifest scene/tests/seed/bakeoff_golden.json
```

For reasoning-tuned checkpoints, add the optional `--no-think` flag so the model does not burn the token budget on chain-of-thought before emitting a caption.

The laptop drives the endpoint through an SSH tunnel (`ssh -L 8099:127.0.0.1:8099 …`), so no candidate port is ever exposed off-box.
