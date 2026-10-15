# S5 · Private static report (screens S1–S8)

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0–S4 merged (starts after S4 merges), W2 ux-map merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_report.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_report.py`
- **Policy basis:** Canon v0.26.2. Delegated project defaults from MCP 16732–16736 apply. They are declared before outcomes, are not canon-prescribed values, and are not ratification.

## Goal

One self-contained HTML file per run that answers the decision question first, shows the evidence path, and never shows a number without its frame admissibility, n_eff and interval (VIZ-23 for result display). WRIT-81 governs the summary prose the report writes itself, not verdict labels.

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
   - Tabs are anchor links reachable by keyboard. The skip link is the first focusable element and targets `#verdict`, the S1 verdict line. Tab then reaches the tabs in map order (Curves, Pair cells, Stages, Failures, Clusters, Compare, Frames and power). No positive `tabindex`.
   - Tables are used for exact lookup (VIZ-32).
   - Charts are inline SVG with direct labels instead of legends (VIZ-40). Inspect each actual rendered chart for [VIZ-35] Use a range-frame for observed extrema (The Visual Display of Quantitative Information, ch. 6): it applies when a scatterplot serves a stated bivariate-pattern task, decision-relevant measured extrema are hidden by round-number frame tails, and no task reference needs those tails. Trim only unneeded tails and label the measured endpoints; retain required references, scales, units, legibility and marginal views. A chart's screen or name does not establish this trigger. The S1 dot-range, S2 operating curves and S7 dendrogram do not trigger it merely by having axes; assess any rendered scatterplot, including a UMAP rendering, against its actual task and marks. A diagnostic projection does not make its coordinates measurements in the original leg space. This is neither a mandate nor a ban for all S1–S8 charts.
   - The S2 operating curves carry required reference lines at FPIR 0.001, 0.01 and 0.05, plus the frozen τ marker.
   - No decoration that carries no data (VIZ-27).
3. Screens follow the ux-map:
   - S1: verdict line with the state for each hypothesis. When an `InconclusiveReason` is set, its text is shown verbatim. The values are `primary_fpir_unresolvable`, `required_guardrail_unscored`, `margin_unreachable_mde_gt_delta`, `non_confirmatory_frame` and `insufficient_independent_psus`. Also shown: admissibility, n_eff, the MDE of each step, and each interval. A hypothesis that was not reached shows "not evaluated". Result display follows VIZ-23 and INT-22: the state is tied to its reason.
   - S2: curves, with the unresolvable region (below 3/n_eff) shaded and labelled, and the reference lines in Build 2.
   - S3: pair cells, with "no data → collect" cells. Cells below 30 independent units read "not scored".
   - S4: stage waterfall (rows are `SearchStage` values; the fused leg has no `unaligned` row) and joint-gap table. The judge row shows no arm deltas. Unavailable arm counts come from `arm_availability` in a separate column, never as a stage.
   - S5: failures, with the selection pool stated first (VIZ-41). Pool accounting reuses the exhaustive frame inventory and shows:
     - overall image count and GT-face count, with existing mated and non-mated counts and explicit unresolved identities;
     - eligible images and faces after the active frame, sampling arm, query/enrolled cell, leg, stage and outcome filters;
     - selected distinct images and faces in the displayed rows;
     - images actually shown as crops (0 when crops are off).
   - Eligible and selected GT-face counts exclude detector-only rows. Detection counts and background-unit counts are reported separately.
   - Active filters, sort, offset, limit and omitted counts are displayed. Default: all eligible failure rows, no hidden cap, stable pseudonymous `image_id` then `face_id` order. Any changed sort or limit is disclosed.
   - Missing exhaustive GT reads "pool not established". It never implies an admissible non-mated N. Disclosure does not establish unbiased selection.
   - Only pseudonymous IDs appear. Stage labels are `FaceOutcome` and `SearchStage` values. Crops appear only when `include_crops`.
   - S6: compare placeholder, filled by S6b
   - S7: clusters, in that leg's own space. Cluster evidence includes held-out chaining from `clusters.json` (GRPH-18). Per leg:
     - N = eligible held-out named-face pairs independently verified as different identities, with usable vectors in this leg;
     - D = those pairs linked by a cluster path, labelled "known-different path links" (D/N);
     - C = the subset linked through a third distinct verified identity, labelled "chaining_check" (C/N).
     - Each count shows its integer numerator, denominator and rate, plus the held-out scope and exclusions.
     - N=0 reads "not evaluated: no eligible held-out different-identity pairs". Missing evidence reads "not evaluated: chaining evidence unavailable". Malformed evidence is an error. None of these reads as zero risk.
     - Identity is never inferred from co-assignment. A selected pair opens its pseudonymous endpoints and ordered path (face, image and identity aliases, edge scores, production s threshold and link rule) in the neighbour table. Closing restores the selection.
     - The dendrogram is drawn at the production cut `d = 1 − s` from `clusters.json`, with the reference line labelled `acceptance τ (not a cluster cut)` at `d = 1 − τ`. When cut labels are null, the caption `no production cut recorded` is shown. The report displays the labels that `reference_threshold_cluster` wrote and never recomputes them. The UMAP caption "diagnostic projection · distances not meaningful" plus its parameters are shown beside the projection.
   - S8: frames and power
     - Per frame: units, identities, PSUs, deff, n_eff, admissibility tag and MDE per step.
     - deff uses planning ICC 0.10 as declared project policy, not observed ICC. Sensitivity at 0.05, 0.10 and 0.20 is shown.
     - The global floor (`DecisionManifest.min_n_independent` = 50 independent PSUs) is shown separately from the pair-cell floor (`cell_floor_n_independent` = 30). The global floor is checked before any FPIR interval.
     - Power scope values are shown as declared design assumptions: discordance `p_d` = 0.15 and power 0.80.
     - Floors do not establish power, MDE adequacy, FPIR resolvability or exhaustive GT.
     - Semantic manifest `created_at` follows MCP 16773: select `seal.sealed_at`, else `ratification.ratified_at`, else an explicit ISO8601 `created_at` literal. Seal and ratification are different events and may differ. Only a supplied explicit literal must match the highest-priority derived value, comparing parsed instants. Missing or invalid dates and a conflicting explicit literal raise the existing `FrameContractError` at the input boundary; do not turn a malformed semantic timestamp into a valid run. A display-only record with no semantic manifest may read "date not recorded" without creating one. Never fill a semantic date from the clock. Actual attempt/private unseal-ledger `consumed_at` belongs to the separate non-replayable receipt boundary and must not be replaced by the selected semantic date.
     - A frame not yet acquired reads "not acquired" and claims nothing.
4. Every number on every screen links to the JSON path it came from, for traceability.
5. The unratified state shows the numbers and the text "unratified: no verdict", never a winner.
6. Tier-(a) labels in the report:
   - Failures and cells built from tier-(a) occluder labels show the label tier beside them.
   - Tier-(a) labels are nonexhaustive. They never establish GT-face counts for the pool.
   - Real tier-(a) labels feed analysis only with a genuine recorded bounded observation and a documented applicability assessment (MEAS-29, see S7). With no recorded reference, the report shows "tier-(a): observation not recorded" and does not treat those rows as analysis input. A missing/unresolved record or unsupported applicability also blocks analysis, with the reason shown. Fixture-only helper output cannot satisfy this gate.
   - No observation is invented. Reuse depends on whether the observation still covers how the current measurements are produced: label rule, instructions, operators, collection/adjudication workflow and relevant tool/UI behavior. Record the context comparison, changes, scope and limits. An unrelated version change alone does not require another human observation; a material change outside the observed scope, or uncertain applicability, requires a new bounded observation before those labels feed analysis. One sample never establishes unbiased measurement.

## RED tests

- The HTML contains no `src=` or `href=` with a scheme other than `#` and `data:`.
- The verdict line includes the admissibility, n_eff and interval for every leg row. An inconclusive fixture renders "INCONCLUSIVE" with the reason. A fixture with H1 inconclusive renders H2 as "not evaluated". A fixture with `primary_fpir_unresolvable` renders that reason verbatim and names no winner. A fixture with `insufficient_independent_psus` renders that reason verbatim and names no winner.
- A fixture with 49 independent PSUs fails the global floor before any FPIR interval is shown. A cell with 29 independent units reads "not scored".
- Every element with a state class also contains a glyph.
- A fused-leg waterfall fixture renders no `unaligned` row; unavailable attribution rows appear only in the `arm_availability` column.
- Pool accounting: the displayed selection reconciles with the pool. Omitted counts equal eligible rows minus shown rows. A fixture with no exhaustive GT renders "pool not established" and no non-mated N. Crop counts are 0 when `include_crops=False`.
- Chaining: N=0 renders "not evaluated: no eligible held-out different-identity pairs". Missing evidence renders "not evaluated: chaining evidence unavailable". Malformed evidence renders an error.
- Tier-(a): a fixture without a recorded observation renders "tier-(a): observation not recorded" and no exhaustive count.
- Planned timestamp contract cases (documentation only): differing valid seal and ratification dates select the seal; without a seal select ratification, then the explicit literal. An explicit literal denoting the same instant passes despite a different timezone representation. Missing/invalid semantic dates or an explicit mismatch raise `FrameContractError`. Only a display-only record without a semantic manifest reads "date not recorded". Receipt consumption time stays separate.
- Planned VIZ-35 checks (documentation only): inspect rendered chart/task pairs. A qualifying bivariate scatterplot trims unneeded frame tails and labels observed extrema; a nonqualifying chart has no range-frame requirement. Required task references survive either case. The S2 curves retain reference lines at FPIR 0.001, 0.01 and 0.05.
- The dendrogram with null cut labels renders `no production cut recorded`; the τ line is labelled `acceptance τ (not a cluster cut)` and sits at `d = 1 − τ`.
- Writing to `benchmarks/reports/` raises `NonPrivateOutputError`.
- `include_crops=False` output contains no `data:image` URI.
- The same run renders byte-identically twice.
- Planned, not yet written (documentation only): Tab order and skip link. The first focusable element is the skip link with `href="#verdict"`, and an element with `id="verdict"` exists. Tab then reaches each tab anchor in map order. Enter on a tab anchor moves focus to its section.

## Done when

Tests pass on the VM, and the AE-11 report task eval is runnable against the tracer run.
