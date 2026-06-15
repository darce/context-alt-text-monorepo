# E19-1 S10 — Local-CPU VLM Benchmark & Decision Memo

> **Date**: 2026-06-14
> **Adapter**: `LocalCpuDescriptionAdapter` (Florence-2-base-ft) · `scene/infrastructure/vlm/`
> **Harness**: `scripts/benchmark_local_vlm.py`
> **Status**: **Binding OCI A1 run complete (2026-06-15) — supersedes the Mac proxy.** A1 latency is **11–17 s/image (mean 13.8 s), under the 20 s interactive bar.** The earlier macOS numbers (27–118 s) were a *contended* proxy (run during/after a heavy local install) and badly over-estimated A1 — Apple-Silicon-faster-than-A1 was **wrong** here. Net: `local_cpu` on A1 is borderline interactive-viable; decision below revised.

## Setup

- Model: `microsoft/Florence-2-base-ft` (0.23B), `trust_remote_code`, CPU, fp32.
- transformers **pinned `>=4.44,<4.49`** — Florence-2's remote modeling code predates the ~4.50 attention refactor (4.57 fails with `'…' object has no attribute '_supports_sdpa'`). Resolved to 4.48.3.
- Tasks: `<MORE_DETAILED_CAPTION>` (caption + alt-text draft) + `<OD>` (object labels); `num_beams=3`; downsample longest edge → 1024px.
- Host: macOS-15.5 arm64 (4 torch threads). **Optimistic proxy** for the OCI A1 ARM target — Apple Silicon is materially faster than Ampere A1; treat these as a lower bound on A1 latency.

## Measured results (3 real photos)

| Metric | Value |
| --- | --- |
| Cold model load | 33.9 s (once per process) |
| Per-image latency | **27.3 / 47.1 / 65.9 s** (min / mean / max) |
| Peak RSS | ~1.04 GB |

Quality (caption / OD):

- **flower** (27.3s): "a large flower… light orange… many round petals… background blurry… sun shining" — accurate, accessibility-useful. OD: `['dining table']` — **hallucinated**.
- **Grace Hopper portrait** (65.9s): "an elderly **man** in a black uniform, white shirt, tie, glasses, hat, flag behind" — details accurate, **gender wrong**. OD: `flag, glasses, hat, human face, person, tie` — good.
- **temple/china** (48.1s): "tall red building, pointed roof, trees, water with boats" — accurate. OD: `['boat']`.

## Verification run (2026-06-14, second pass — pre-UI go/no-go)

Independent re-run on 2 real photos (china/temple, flower) before any UI work, same config (`beams=3`, `<MORE_DETAILED_CAPTION>,<OD>`, 1024px), torch 2.12.0 / transformers 4.48.3, **pinned model revision `f6c1a258…`** (validates the trust_remote_code revision pin live):

| Metric | Value |
| --- | --- |
| Cold model load | 38.4 s |
| Per-image latency | **55.7 / 87.1 / 118.5 s** (min / mean / max) |
| Peak RSS | 582 MB |

- **china/temple** (55.7s): "a tall red building with a pointed roof… trees surrounding… water in front with boats" — accurate, accessibility-useful. OD: `['boat']` — correct.
- **flower** (118.5s): "a large flower… light orange… many round petals… red center… background blurry… sun shining" — accurate, accessibility-useful. OD: `['dining table']` — **hallucinated**.

> ⚠️ **The two macOS runs above are a contended proxy and are superseded by the binding A1 run below.** Both Mac runs happened during/right after a heavy local `uv`/torch install (thermal + CPU contention), which inflated decode time. Captions are byte-identical to A1 (deterministic), so the **quality** notes hold; the **latency** numbers do not.

## Binding OCI A1 run (2026-06-15) — the real target host

Run on the deployed VM `acx-backend` (Ampere Altra **aarch64, 4 OCPU, 23 GB**, idle, load ~1.4), isolated scratch venv (`uv`), public PyPI deps only, scikit-learn's bundled `china.jpg`/`flower.jpg`, **identical config** (Florence-2-base-ft @ pinned revision `f6c1a258`, fp32 CPU, `<MORE_DETAILED_CAPTION>,<OD>`, `beams=3`, 512 tokens, 1024px). torch 2.12.0 / transformers 4.48.3. Live `/health` stayed `ok` throughout.

| Metric | A1 value | (contended Mac proxy) |
| --- | --- | --- |
| Cold model load | **10.9 s** | 33.9–38.4 s |
| Per-image latency | **11.1 / 13.8 / 16.6 s** (min/mean/max) | 27–118 s |
| Peak RSS | 2.48 GB¹ | 0.58–1.04 GB |

¹ inflated by the `torch+cu130` wheel loading unused CUDA libs; a CPU-only build is ~1 GB. Fits 23 GB easily.

- **china/temple** (11.1s): same accurate caption ("tall red building, pointed roof, trees, water with boats"). OD `['boat']` — correct.
- **flower** (16.6s): same accurate caption (orange flower, round petals, red center, blurry background). OD `['dining table']` — **hallucinated**.

**VLM wiring confirmed on the target**: model loads at the pinned revision, runs CPU inference, returns the expected typed caption + OD on A1. (Adapter↔scene-package integration is separately covered by unit tests; this run validates model load + inference on the deployed host.)

## Assessment (revised)

- **Latency is acceptable on A1: ~11–17 s/image, mean 13.8 s — under the 20 s interactive bar** for both photos. The earlier "fails by 1.5–3×" conclusion was an artifact of a contended Mac proxy; the binding A1 number reverses it. Headroom is modest, not large — a longer/denser image (more caption tokens) could approach or cross 20 s, so an **async/worker path with a progress affordance** is still the safe UX, but a synchronous request is now plausible for typical inputs.
- **Caption quality is a good accessibility *draft*** (scene/object/colour/composition), with the known VLM failure modes: occasional gender misattribution (reinforces human-in-the-loop / roster-bound naming) and **OD hallucination** (`dining table` on a flower). Captions usable; raw OD not trustworthy standalone.
- Memory is a non-constraint (≤2.5 GB vs 23 GB).

## Decision (revised)

> **Update (2026-06-15, S11):** the `ACX_DESCRIPTION_ADAPTER` switch was generalized to a 4-option profile — `local_cpu` is now **`florence_small`** (Florence-2-base-ft), alongside `florence_large` (stub, async-only) and `gpu_phi4` (stub, GPU-only). See `docs/tasks/19.0/E19-1-florence-large-async-worker-impl-notes.md` and `scene/config/profiles.py`. References to `ACX_DESCRIPTION_ADAPTER=local_cpu` below read as `=florence_small`.

1. **`local_cpu` on A1 is viable as a real-description path** at ~11–17 s — **no GPU is required for an MVP**. GPU/hosted-GPU becomes a *quality/headroom* upgrade, not a latency necessity.
2. **Run it async (worker), not inline**, with a progress indicator — latency is interactive-range but variable; protects the event loop and the shared recognition service on the 4-OCPU box.
3. **Keep `seeded` as the zero-latency default** for the demo loop/contract; `local_cpu` is the opt-in real path (`ACX_DESCRIPTION_ADAPTER=local_cpu`).
4. **Model-swap priority is QUALITY, not speed** (speed is already adequate): the weak point is OD hallucination, not latency. Options: drop `<OD>` (caption-only — also ≈½ time, more headroom), or evaluate a stronger caption model. `num_beams=1` (~3× faster) is available if more latency headroom is wanted but costs quality.
5. **Hosted-provider tier (roadmap Phase 6 / E19-5)** remains the path for best-in-class quality, now a quality play rather than a latency rescue.

## Reproduce

```bash
cd apps/prototype-description-service
uv sync --extra dev --extra vlm
uv run python scripts/benchmark_local_vlm.py IMAGE [IMAGE ...] \
  --num-beams 3 --tasks "<MORE_DETAILED_CAPTION>,<OD>" --json-out bench.json
```

Artifact schema: `model_id`, `model_version`, `device`, `num_beams`, `cold_load_s`, `peak_rss_mb`, per-image `latency_s` + `caption` + `objects`, and summary `latency_s.{min,mean,max}`.

**Binding A1 run (on the deployed VM, no private source shipped):** install `uv` + public deps (`transformers>=4.44,<4.49 torch>=2.2 einops timm accelerate pillow scikit-learn`) into a `/tmp` scratch venv on `acx-backend`, then run a standalone script that loads `microsoft/Florence-2-base-ft@f6c1a258` (fp32 CPU, `beams=3`, `<MORE_DETAILED_CAPTION>,<OD>`, 1024px) over scikit-learn's bundled `china.jpg`/`flower.jpg`. The script replicates `LocalCpuDescriptionAdapter` exactly; only public packages + public sample images touch the host (the private tree is never rsynced). Tear down `/tmp` scratch after; watch `/health` during the run.
