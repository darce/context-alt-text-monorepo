# E19-1 S10 — Local-CPU VLM Benchmark & Decision Memo

> **Date**: 2026-06-14
> **Adapter**: `LocalCpuDescriptionAdapter` (Florence-2-base-ft) · `scene/infrastructure/vlm/`
> **Harness**: `scripts/benchmark_local_vlm.py`
> **Status**: dev-host proxy run complete + independently re-verified (2026-06-14, 2nd pass) — non-viability for interactive use confirmed; binding OCI A1 run pending (remote).

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

Confirms the first pass: latency is **2.8–6× the <20s interactive bar** (the longer the caption, the worse — flower generated 8 sentences → 118s of beam-search decode). Caption quality holds (scene/colour/composition); OD remains untrustworthy standalone. Decision below is **unchanged and reinforced**: do not put `local_cpu` on the interactive request path.

## Assessment

- **Latency fails the <20s interactive bar by 1.5–3×** on a host *faster* than A1; on A1 ARM CPU it will be worse. Local-CPU Florence-2 at `beams=3` + 2 tasks is **not viable for an interactive demo**.
- **Caption quality is good enough** for an accessibility *draft* (scene/object/colour detail), but exhibits known VLM failure modes: occasional gender misattribution (reinforces the human-in-the-loop / roster-bound naming policy) and OD hallucination. Captions are usable; raw OD is not trustworthy standalone.
- Memory (~1GB) fits A1 (24GB) comfortably; latency, not memory, is the constraint.

## Decision

1. **Keep `seeded` as the default demo adapter** (instant, deterministic) — proves the loop + contract without latency risk.
2. **Ship `local_cpu` as an opt-in "real description" path** (`ACX_DESCRIPTION_ADAPTER=local_cpu`) for evaluation, accepting ~30–60s latency; **must run async (worker), not inline on the request path** before any non-eval use — the inline path here is POC-only.
3. **Faster-config levers to test next**: `num_beams=1` (≈3× faster, lower quality), caption-only (drop `<OD>`, ≈½ time), smaller `max-new-tokens`. Re-run the harness with these on the **OCI A1 host** for the binding number (S10 remote).
4. **Evaluate a hosted-provider tier (roadmap Phase 6 / E19-5)** for production quality+latency; local-CPU is a sovereignty/eval option, not the demo default.

## Reproduce

```bash
cd apps/prototype-description-service
uv sync --extra dev --extra vlm
uv run python scripts/benchmark_local_vlm.py IMAGE [IMAGE ...] \
  --num-beams 3 --tasks "<MORE_DETAILED_CAPTION>,<OD>" --json-out bench.json
```

Artifact schema: `model_id`, `model_version`, `device`, `num_beams`, `cold_load_s`, `peak_rss_mb`, per-image `latency_s` + `caption` + `objects`, and summary `latency_s.{min,mean,max}`.
