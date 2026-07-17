# benchmarks/ — description & vision bake-off harness

Canonical home for all image-description / vision-model benchmarks: their
**results**, browser-openable **reports**, input **manifests**, **plans**, the
operational **runners**, and the **dashboard**. This directory holds the
*artifacts and orchestration*; the harness **code** lives in the service package
(see [Harness code](#harness-code)) because it is imported, tested, and shipped
with the service.

Open [`dashboard.html`](dashboard.html) in any browser — no server needed — for
the run index and headline metrics.

## Layout

| Dir | What | Notes |
| --- | --- | --- |
| `dashboard.html` | run index + headline metrics + report links | self-contained; regenerate as runs accumulate |
| `reports/` | generated HTML reports (image-embedded or text) | open directly in a browser; JS search built in |
| `results/` | scored report JSON + markdown (the benchmark data) | one per run/cell |
| `manifests/` | benchmark inputs: corpus, identities, subsets | data, not code |
| `plans/` | bake-off plans, candidate matrix, infra learnings | reference docs |
| `runners/` | `a10-*.sh` provisioning + run scripts | operational; also in `infra/oci/incidents/` |

## What's here now (2026-07-16)

- **golden-37 A/B matrix** (`results/run-altq-*-report.md`) — v1 / v2 / two-pass /
  dual-length × eval modes on the scored 37-image golden manifest (traps, rosters).
  Clean quality signal: two-pass cut context-distractor wrong-name rate 0.216 → 0.081.
- **646 three-surface interleave** (`results/run-altq-646-interleave-v3-report.*`,
  `reports/corpus646-three-surface-20260716.html`) — Qwen3-VL-30B-A3B, v3 weave
  (title + WCAG alt + evocative caption) with curated identities; 640/646 woven,
  p50 5.24 s/img. Corpus-level name metrics are **not** clean quality signal (celeb
  recognition + auto-strict rubric — see the report notes); golden-37 is the gate.
- **10-image multi-model bake-off** — staged, not yet run:
  [`reports/bakeoff-10img-20260716.html`](reports/bakeoff-10img-20260716.html)
  (control column populated), candidate matrix in
  [`plans/multi-model-bakeoff-plan-2026-07-16.md`](plans/multi-model-bakeoff-plan-2026-07-16.md).

## Harness code

The generator + drivers are in `apps/prototype-description-service/scripts/eval_harness/`
(imported as `scripts.eval_harness.*`, tested under `scene/tests/test_eval_harness_*`):

- `bakeoff.py` — the describe pipeline (prompt variants, two-pass, dual-length,
  v3 three-surface, face-gate, weave-bench) + `--eval-mode` context transforms.
- `build_bakeoff_report.py` — the report generator (image-embedded, N-model
  columns, media_id, per-image latency, offline search) that produced `reports/`.
- `cli.py` / `report.py` — fetch walker + pure scorer.
- `florence_describe.py` — on-box CPU Florence driver; `describe_baseline.py` —
  full-corpus driver.

## Regenerate a report

```
cd apps/prototype-description-service
python -m scripts.eval_harness.build_bakeoff_report \
  --manifest scripts/eval_harness/bakeoff10-manifest-20260716.json \
  --images-dir /Volumes/Butter/WP/vlm/app/public/wp-content/uploads \
  --media-ids 93,154,200,46,62,98,6,11,400,378 --embed-images \
  --run "Qwen3-VL-30B=out/run-altq-646-interleave-v3.json" \
  --title "10-image bake-off" --out <path>.html
```

## Conventions

- **Scored gate = golden manifest** (rubric + traps + rosters). Corpus runs are
  coverage/latency evidence, not adoption gates.
- **License matters** for the self-hosted product — prefer Apache-2.0 models.
- Every GPU run pairs with a terminate; reachability is Tailscale-jump, never a
  public IP (see `plans/oci-vm-reachability-tailscale-vcn-plan.md`).
