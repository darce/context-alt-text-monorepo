# S5 · Private static report (screens S1–S8)

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0–S3 merged, W2 ux-map merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_report.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_report.py`

## Goal

One self-contained HTML file per run that answers the decision question first, shows the evidence path, and never shows a number without its frame admissibility, n_eff and interval (VIZ-23, WRIT-81).

## Read first

- `benchmarks/ux-maps/fir-bench.uxmap.json` and its rendered `.md`: screens, zones, states and flows. That map is the inventory; do not invent screens.
- Task plan § Screens (ASCII drafts) and § "Canon checks"
- `scores.json` and `clusters.json` shapes from S3/S4

## Build

1. `render_report(run_dir, *, out_dir, include_crops=False)`. `out_dir` must pass `require_private_output_path`. Writes `index.html`, `report.json` and per-table CSV.
2. HTML rules:
   - No external requests: inline CSS and SVG, no fonts or scripts from the network.
   - Light and dark via `prefers-color-scheme`.
   - Every state is shown by glyph plus colour (✓ ✗ ○ ▼).
   - Tabs are anchor links reachable by keyboard, with a skip link.
   - Tables are used for exact lookup (VIZ-32).
   - Charts are inline SVG with range-frame axes and direct labels instead of legends (VIZ-35, VIZ-40).
   - No decoration that carries no data (VIZ-27).
3. Screens follow the ux-map:
   - S1: verdict line with the state for each hypothesis, the `InconclusiveReason` text verbatim when one is set, admissibility, n_eff, the MDE of each step, and each interval. A hypothesis that was not reached shows "not evaluated".
   - S2: curves, with the unresolvable region shaded and labelled
   - S3: pair cells, with "no data → collect" cells
   - S4: stage waterfall and attribution ladder
   - S5: failures, with the selection pool stated (VIZ-41); crops only when `include_crops`
   - S6: compare placeholder, filled by S6b
   - S7: clusters, with the UMAP caption "diagnostic projection · distances not meaningful" plus its parameters
   - S8: frames and power
4. Every number on every screen links to the JSON path it came from (MEAS-29).
5. The unratified state shows the numbers and the text "unratified: no verdict", never a winner.

## RED tests

- The HTML contains no `src=` or `href=` with a scheme other than `#` and `data:`.
- The verdict line includes the admissibility, n_eff and interval for every leg row. An inconclusive fixture renders "INCONCLUSIVE" with the reason. A fixture with H1 inconclusive renders H2 as "not evaluated". A fixture with `primary_fpir_unresolvable` renders that reason verbatim and names no winner.
- Every element with a state class also contains a glyph.
- Writing to `benchmarks/reports/` raises `NonPrivateOutputError`.
- `include_crops=False` output contains no `data:image` URI.
- The same run renders byte-identically twice.

## Done when

Tests pass on the VM, and the AE-11 report task eval is runnable against the tracer run.
