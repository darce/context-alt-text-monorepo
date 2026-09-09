# VLM6-lc3-face: face_metrics / face_pass / florence_describe findings

Lane: `vlm6-lc3-face` · Task: `VLM-6` · Actor: `grok-4.5`

## Summary

Fixed all 4 inlined findings in lane-owned files: shared `latency_summary` schema (RH-04), wire-bbox→normalized-centre L→R helpers + face_pass re-sort (RH-03), malformed-GT exclude + predicted leftmost-wins dedup (R4-08), large-ft fail-fast before model load (RH-09).

## Per-finding table

| ID | Severity | Status | What changed |
| --- | --- | --- | --- |
| **VLM6-RH-04** | medium | **fixed** (lane scope) | `latency_summary()` + `nearest_rank_percentile()` in `face_metrics.py`. `face_pass.summarize` and `florence_describe.run` emit one nested `latency` block (`unit/n/mean/min/p50/p95/p99/max` + optional throughput). Dropped face_pass `latency_ms` and florence flat `*_latency_s` keys. **Residual:** `describe_baseline.py` not owned — still has its own `_pct` / `describe_latency_s`; sibling lane must call the shared helper. |
| **VLM6-RH-03** | medium | **fixed** (helpers + face_pass) | Added `wire_bbox_normalized_centre`, `predicted_left_to_right`, `sort_identity_rows_by_normalized_centre`. `face_pass.run_face_pass` re-sorts identity rows by normalized centre using `_image_dimensions` from image bytes. **Residual:** `cli._extract_identities` / `report.py` not owned — caption score path still uses corner-x order from cli until report wires `predicted_left_to_right(..., image_width/height)`. Helpers + tests land here for that wiring. |
| **VLM6-R4-08** | low | **fixed** | `labeled_left_to_right`: named boxes all missing `x` → `None` (exclude from positional), all-anonymous still `[]`. `predicted_left_to_right` mirrors leftmost-wins name dedup. |
| **VLM6-RH-09** | low | **fixed** | `florence_describe.main` rejects `MODEL_SPECS[model].revision is None` at argparse time before `load_captioner`. Profiles parity kept (`large-ft` still unpinned); runbook path fails cheap until a pin is added. |

## Gate

Command:
```bash
cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_face_metrics.py \
  scene/tests/test_eval_harness_face_pass.py \
  scene/tests/test_florence_describe.py \
  -q -p no:randomly
```

**GREEN-after:** `97 passed in 2.49s`

Related broader filter (sanity): `66 passed` for labeled/latency/face_pass/florence keywords.

## Owned paths touched

| Path | Action |
| --- | --- |
| `scripts/eval_harness/face_metrics.py` | latency_summary, wire bbox normalize, predicted L→R, labeled_left_to_right R4-08 |
| `scripts/eval_harness/face_pass.py` | shared latency schema; re-sort identities by centre |
| `scripts/eval_harness/florence_describe.py` | shared latency block; RH-09 parse-time pin check |
| `scene/tests/test_eval_harness_face_metrics.py` | RH-03/R4-08/RH-04 unit tests |
| `scene/tests/test_eval_harness_face_pass.py` | latency schema assertions |
| `scene/tests/test_florence_describe.py` | latency nest + large-ft fail-fast |
| `.s2a/vlm6-lc3-face-report.md` | this report |

## What we did NOT do

- Did **not** edit `cli.py`, `report.py`, `describe_baseline.py`, `manifest.py`, or profiles.
- Did **not** invent a large-ft commit pin (no verified large-ft SHA in repo).
- Did **not** xfail/skip/weaken existing tests.
- Did **not** touch bakeoff-results freezes.

## Residual for orchestrator

1. **RH-04 complete:** have describe_baseline lane call `face_metrics.latency_summary`.
2. **RH-03 complete:** in report score path, replace bare `identity_names(...)` with `predicted_left_to_right(identities, image_width=..., image_height=...)` (or fix `cli._extract_identities` to accept dims and sort by centre).
3. When large-ft is enablement-ready, pin `MODEL_SPECS["large-ft"].revision` (and profiles) to a benchmarked commit so RH-09 gate lifts.

## Canon

- sr-001: no weakened tests
- sr-007: one latency definition (lane runners)
- rg-005 / rg-015: centre vs corner coords not guessed; normalize with captured size or exclude
- A-05 / AGT-10: null model_revision fails closed, now before download
