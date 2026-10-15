# S5 · Private static report (screens S1–S8)

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0–S4 merged (starts after S4 merges), W2 ux-map merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_report.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_report.py`

## Goal

One self-contained HTML file per run that answers the decision question first, shows the evidence path, and never shows a number without its frame admissibility, n_eff and interval (VIZ-23, WRIT-81).

## Read first

- `benchmarks/ux-maps/fir-bench.uxmap.json` and its rendered `.md`: screens, zones, states and flows. That map is the inventory; do not invent screens.
- Task plan § Screens (ASCII drafts) and § "Canon checks"
- The `scores-v1` and `clusters-v1` schemas (S0 Build 9) define every field the report reads. The report reads files only and never imports S3 or S4 code.

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
   - S4: stage waterfall (rows are `SearchStage` values; the fused leg has no `unaligned` row) and joint-gap table. The judge row shows no arm deltas. Unavailable arm counts come from `arm_availability` in a separate column, never as a stage.
   - S5: failures, with the selection pool stated (VIZ-41); stage labels are `SearchStage` values; crops only when `include_crops`
   - S6: compare placeholder, filled by S6b
   - S7: clusters. The dendrogram is drawn at the production cut `d = 1 − s` from `clusters.json`, with the reference line labelled `acceptance τ (not a cluster cut)` at `d = 1 − τ`. When cut labels are null, the caption `no production cut recorded` is shown. The report displays the labels that `reference_threshold_cluster` wrote and never recomputes them. The UMAP caption "diagnostic projection · distances not meaningful" plus its parameters are shown beside the projection.
   - S8: frames and power
4. Every number on every screen links to the JSON path it came from (MEAS-29).
5. The unratified state shows the numbers and the text "unratified: no verdict", never a winner.

## RED tests

- The HTML contains no `src=` or `href=` with a scheme other than `#` and `data:`.
- The verdict line includes the admissibility, n_eff and interval for every leg row. An inconclusive fixture renders "INCONCLUSIVE" with the reason. A fixture with H1 inconclusive renders H2 as "not evaluated". A fixture with `primary_fpir_unresolvable` renders that reason verbatim and names no winner.
- Every element with a state class also contains a glyph.
- A fused-leg waterfall fixture renders no `unaligned` row; unavailable attribution rows appear only in the `arm_availability` column.
- The dendrogram with null cut labels renders `no production cut recorded`; the τ line is labelled `acceptance τ (not a cluster cut)` and sits at `d = 1 − τ`.
- Writing to `benchmarks/reports/` raises `NonPrivateOutputError`.
- `include_crops=False` output contains no `data:image` URI.
- The same run renders byte-identically twice.

## Done when

Tests pass on the VM, and the AE-11 report task eval is runnable against the tracer run.
