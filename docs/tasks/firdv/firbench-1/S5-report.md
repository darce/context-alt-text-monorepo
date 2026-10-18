# S5 · Private static report (screens S1–S8)

- **Wave:** W3 batch C · **Depends on:** S0–S4 merged, accepted ux map
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_report.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_report.py` (the report test surface is the `test_eval_harness_firbench_report*.py` family; see RED tests)
- **Policy basis:** Canon v0.26.2 rows cited below, with rule names and sources as printed in the canon mirror. Project defaults from MCP 16732–16736 apply. They are declared project policy, not canon constants, and they are not ratification.

## Status

Verified against the accepted source tree (tree `21408d43562ef2f49a3b27c53112bae0cc822605`). Static inspection and the named tests show what the code does. None of this is a real-data result.

**Implemented**

- `render_report(run_dir, *, out_dir, include_crops=False) -> Path` at `firbench_report.py:2628`. `out_dir` passes `require_private_output_path` (`firbench_contract.py:1049`), which raises `NonPrivateOutputError`. The report writes `index.html`, `report.json` and per-table CSV. It imports `firbench_contract` at module level and imports `fir_occ_labels` and `firbench_frames` only inside the functions that need them. It does not import S3 or S4 code.
- The CLI `report` command (`firbench_cli.py`, `report_run`) materializes the S4 clusters and then renders into `<run_dir>/report/`. The default collaborator loader (`firbench_runtime.default_collaborators`) constructs without raising `NotImplementedError`.
- One section per screen is rendered inside one page (`firbench_report.py:2267`, `<section id="{sid}">`). The verdict is `<section id="verdict">` (`:2285`). The S6 Compare section renders the S6b comparison payload or a named withheld reason (`:2840–2856`).
- **Keyboard and focus.** The skip link is `href="#verdict"` and is the first focusable element (`:2283`). Its target carries `tabindex="-1"` (`:2285`). Tabs are anchors in map order. The source has no positive `tabindex` (checked: zero matches for `tabindex="[1-9]`). A `:focus-visible` rule exists (`:1900`). Escape closes the τ explorer and the inspector (`:2215–2216` and the inspector close control at `:2289`).
- **Light and dark, glyphs, offline.** `prefers-color-scheme` drives the light and dark palettes (`:1889`). State elements carry a glyph; the named RED test checks this. The offline test named below covers external requests.
- **Source inspector, filter and sort (S5 failures).** Each failure row's source is a `button.source[data-source]` (`:109`) that opens the inspection panel (`inspector-title`, `:2288`). Filters are one `select[data-filter]` per field with `All` as the default (`:1962`). The sort select offers `image_id, face_id, leg_key` (default) and `face_id, image_id, leg_key` (`:1964`). A reset control clears the filters (`:1966`). Rows are sorted by `(image_id, face_id, leg_key, arm, fold)` before display (`:1469`).
- **Recorded-point τ explorer.** The explorer is enabled only for a development frame that is explicitly unsealed in the inline source (`:2201–2203`). It shows recorded descriptive points only, says "Nothing is saved", and restores the captured snapshot on exit. The frozen verdict above it is therefore unchanged (`:2195–2216`).
- **One shared evidence table for both leg curves.** The S2 curves render as one SVG with per-leg panels that share geometry (`_curves_svg`, `:434`). The at-τ readout is one table (`:635–636`). It has rows for every leg's curve points and one row for each leg with no curve point (loop at `:612–634`).
- **Pool accounting (S5 failures).** The pool block reports `inventory_rows/faces/images`, `eligible_rows/faces/images`, `selected_faces/images/rows`, `shown_rows`, `omitted_rows` and `outside_default_scope_rows` (`:832–846`). The default view sets `shown_rows = eligible_rows` and `omitted_rows = 0`. There is no hidden cap.
- **Join to the exact frame.** Real tier-(a) labels join to frame GT on `(image_id, image sha256, box, identity_status, annotation)`, one-to-one (`:1037–1049`). The join uses the canonical `image_id` and the exact frame `ImageUnit.sha256`. It does not use media_id aliases.
- **S7 requalification.** `_binding_label_evidence` (`:959`) calls the S7 `requalify_label_evidence` through `getattr` (`:1011–1018`). When the reader is missing, or requalification fails, analytics are withheld and the reason is shown.
- **Timestamp display.** `_semantic_created_at` (`:195–211`) shows `firbench.created_at` only when `created_at_source` is an allowed semantic source. A missing, non-ISO or timezone-less value raises `FrameContractError`. The CLI resolves the semantic instant from seal, else ratification, else an explicit literal (`firbench_cli.py:119–121`, with the mismatch check in the same function). A display-only record with no semantic manifest reads "date not recorded".

**Prior art carried into this brief.** Recorded from verified finding text. These identifiers are not located in this tree, and none is a fresh bug claim.

- FIR-12-BR-22 (superseded via EVAL-LANDING-1): mixed `media_id` and sha aliases counted one image twice. Joins use the declared canonical `image_id` plus the exact frame `ImageUnit.sha256`. The PSU duplicate-unit rule is preserved, and no extra units are minted.
- FIR-12 semantic reinjection (`gte-base-en-v1.5`, verified available): a GT face that the semantic path missed remains an FNIR miss. The miss is not reclassified.
- MAINT-FIR-DETECTION-20260919: exhaustive GT is detector-independent. A detector-only comparison is a separate check and cannot establish the pool.
- EMB-01 (*Foundations of Vector Retrieval*, ch. 1): one embedding space per comparison. Clusters and chaining stay in each leg's own space.

**Prior verification receipts.** Recorded by the coordinator at earlier revisions and not re-run for this document: 518 CLI tests; 178 report tests, including the actual Chrome light/dark browser run; and an earlier joined-label run of 284 tests. These suites overlap the current tree. Their counts are not evidence for any test named in this brief.

**Not established**

- No real run has been rendered from real data. No exhaustive GT is established for any real frame, so no admissible non-mated N is shown.
- No genuine human observation (MEAS-29) or QC evidence for real tier-(a) labels is in this tree. Real tier-(a) labels do not feed analysis.
- Ratification, seal and budget are not established. The committed decision manifest (`benchmarks/manifests/fir-bench-decision-v1.json`) has `ratification` and `seal` set to null. Any verdict it produces is unratified.
- Real source and template bindings are not established.

**Open checks**

- **VIZ-35 (range-frame)** for the rendered UMAP projection (`_projection_html`, `:1656`). No range-frame code exists in source, so this assessment is open. The brief does not treat the S2 curves, the S7 dendrogram or the S1 dot-range as triggers merely because they have axes.
- **Browser test.** `test_actual_browser_interactions` asserts that `FIR_REPORT_PLAYWRIGHT` is set (`test_eval_harness_firbench_report_interactions.py:304–306`). It fails without the variable. It does not skip.

| Item | Policy (declared) | Measured here | Unresolved |
| --- | --- | --- | --- |
| Planning ICC | 0.10 (`planning_icc`); sensitivity rows 0.05 and 0.20 | None | Observed ICC |
| Eligibility floors | 50 independent PSUs globally; 30 per pair cell (`min_n_independent`, `cell_floor_n_independent`) | None | Adequacy of power or FPIR resolvability |
| Design discordance | `p_d` 0.15; power 0.80 | None | Observed discordance |
| Failure pool | Displayed as declared | Counts from the rendered fixture only | Exhaustive GT for any real frame |
| Tier-(a) observation | Gate in place (`fir_occ_labels`) | None recorded | Genuine MEAS-29 observation |

## Goal

One self-contained HTML file per run that answers the decision question first, shows the evidence path, and never shows a number without its frame admissibility, n_eff and interval (VIZ-23 for result display). WRIT-81 governs the summary prose the report writes itself, not verdict labels.

## Read first

- `benchmarks/ux-maps/fir-bench.uxmap.json` and its rendered `benchmarks/ux-maps/fir-bench.md`. The accepted map has nine screens (S1–S8 and L1) and one exit-state entry (`exit-compare-refused`). It is reused as it stands; no new map is required. The map is the inventory; do not invent screens.
- The task plan's [§ Screens](../FIRBENCH-1-fir-benchmark-tool-task-plan.md) and [§ Canon checks](../FIRBENCH-1-fir-benchmark-tool-task-plan.md).
- The `scores-v1` and `clusters-v1` schemas (S0 Build 9) define every field the report reads. The report reads files only and never imports S3 or S4 code.

## Build

1. `render_report(run_dir, *, out_dir, include_crops=False)` (implemented; see Status). `out_dir` must pass `require_private_output_path`. The report writes `index.html`, `report.json` and per-table CSV.
2. HTML rules:
   - No external requests: inline CSS and SVG, no fonts or scripts from the network.
   - Light and dark via `prefers-color-scheme`.
   - Every state is shown by glyph plus colour (✓ ✗ ○ ▼).
   - Tabs are anchor links reachable by keyboard. The skip link is the first focusable element and targets `#verdict`, the S1 verdict line. Tab then reaches the tabs in map order (Curves, Pair cells, Stages, Failures, Clusters, Compare, Frames and power). No positive `tabindex`.
   - Tables are used for exact lookup (VIZ-32).
   - Charts are inline SVG with direct labels instead of legends (VIZ-40). Inspect each actual rendered chart for [VIZ-35] Use a range-frame for observed extrema (The Visual Display of Quantitative Information, ch. 6). It applies when a scatterplot serves a stated bivariate-pattern task, decision-relevant measured extrema are hidden by round-number frame tails, and no task reference needs those tails. Trim only unneeded tails and label the measured endpoints; retain required references, scales, units, legibility and marginal views. A chart's screen or name does not establish this trigger. The S1 dot-range, S2 operating curves and S7 dendrogram do not trigger it merely by having axes; assess any rendered scatterplot, including a UMAP rendering, against its actual task and marks. A diagnostic projection does not make its coordinates measurements in the original leg space. This is neither a mandate nor a ban for all S1–S8 charts.
   - The S2 operating curves carry required reference lines at FPIR 0.001, 0.01 and 0.05, plus the frozen τ marker (implemented: reference lines in `_curves_svg`, `:495`; τ marker in `_tau_markers`, `:586`).
   - No decoration that carries no data (VIZ-27).
3. Screens follow the ux-map:
   - **S1 verdict line.** The state for each hypothesis. When an `InconclusiveReason` is set, its text is shown verbatim. The values are `primary_fpir_unresolvable`, `required_guardrail_unscored`, `margin_unreachable_mde_gt_delta`, `non_confirmatory_frame` and `insufficient_independent_psus`. Also shown: admissibility, n_eff, the MDE of each step, and each interval. A hypothesis that was not reached shows "not evaluated". Result display follows VIZ-23 and INT-22: the state is tied to its reason.
   - **S2 curves.** The unresolvable region (below `3 / n_nonmated_eff`, the implemented term; `:475–478`) is shaded and labelled, with the reference lines from Build 2.
   - **S3 pair cells.** "no data → collect" for empty cells. Cells below 30 independent units read "not scored" (`_cells_html`, `:664`).
   - **S4 stages.** The waterfall rows are `SearchStage` values; the fused leg has no `unaligned` row (`:740`). The joint-gap table (`:772`) shows the judge row with no arm deltas. Unavailable arm counts come from `arm_availability` in a separate column, never as a stage.
   - **S5 failures.** The selection pool is stated first (VIZ-41). Pool accounting reuses the exhaustive frame inventory and shows:
     - overall image count and GT-face count, with existing mated and non-mated counts and explicit unresolved identities;
     - eligible images and faces after the active frame, sampling arm, query/enrolled cell, leg, stage and outcome filters;
     - selected distinct images and faces in the displayed rows;
     - images actually shown as crops (0 when crops are off).
     - Native summaries are reconciled against the full declared arm inventory. GT × leg rows carry nullable fit, unresolved and unavailable states, and an unknown is never shown as cleared (named tests below).
     - The overall exhaustive pool is established separately from eligibility. Filters never change the pool.
     - Pool and selection disclosure (VIZ-41, *Visual Explanations*, ch. 1) makes the selection inspectable. It does not prove that the selection is unbiased.
   - Eligible and selected GT-face counts exclude detector-only rows. Detection counts and background-unit counts are reported separately.
   - Active filters, sort, offset, limit and omitted counts are displayed. Default: all eligible failure rows, no hidden cap, stable pseudonymous `image_id` then `face_id` order. Any changed sort or limit is disclosed.
   - Missing exhaustive GT reads "pool not established". It never implies an admissible non-mated N.
   - Only pseudonymous IDs appear. Stage labels are `FaceOutcome` and `SearchStage` values. Crops appear only when `include_crops`.
   - **S6 compare.** Renders the S6b comparison payload (`compare`, `:2840–2856`) or the named withheld reason. The S6b compare command is `firbench_cli compare`.
   - **S7 clusters.** In that leg's own space. Cluster evidence includes held-out chaining from `clusters.json` (GRPH-18). Per leg:
     - N = eligible held-out named-face pairs independently verified as different identities, with usable vectors in this leg;
     - D = those pairs linked by a cluster path, labelled "known-different path links" (D/N);
     - C = the subset linked through a third distinct verified identity, labelled "chaining_check" (C/N).
     - Each count shows its integer numerator, denominator and rate, plus the held-out scope and exclusions.
     - N=0 reads "not evaluated: no eligible held-out different-identity pairs". Missing evidence reads "not evaluated: chaining evidence unavailable". Malformed evidence is an error. None of these reads as zero risk.
     - Identity is never inferred from co-assignment. A selected pair opens its pseudonymous endpoints and ordered path (face, image and identity aliases, edge scores, production s threshold and link rule) in the neighbour table. Closing restores the selection.
     - The dendrogram is drawn at the production cut `d = 1 − s` from `clusters.json`, with the reference line labelled `acceptance τ (not a cluster cut)` at `d = 1 − τ`. When cut labels are null, the caption `no production cut recorded` is shown. The report displays the labels that `reference_threshold_cluster` wrote and never recomputes them (`:1745`). The UMAP caption "diagnostic projection · distances not meaningful" and its parameters are shown beside the projection (`:79`, `:1656`).
   - **S8 frames and power.**
     - Per frame: units, identities, PSUs, deff, n_eff, admissibility tag and MDE per step (`_frames_html`, `:1803`).
     - deff uses planning ICC 0.10 as declared project policy, not observed ICC. Sensitivity at 0.05, 0.10 and 0.20 is shown (`:1849`).
     - The global floor (`DecisionManifest.min_n_independent` = 50 independent PSUs) is shown separately from the pair-cell floor (`cell_floor_n_independent` = 30). The global floor is checked before any FPIR interval.
     - Power scope values are shown as declared design assumptions: discordance `p_d` = 0.15 and power 0.80.
     - Floors do not establish power, MDE adequacy, FPIR resolvability or exhaustive GT.
     - Semantic `created_at` follows MCP 16773 (see Status, timestamp display). Seal and ratification are different events and may differ. Only a supplied explicit literal must match the highest-priority derived value, comparing parsed instants. Missing or invalid dates and a conflicting explicit literal raise `FrameContractError` at the input boundary; a malformed semantic timestamp never becomes a valid run. A display-only record with no semantic manifest may read "date not recorded" without creating one. Never fill a semantic date from the clock. Actual attempt or private unseal-ledger `consumed_at` belongs to the separate non-replayable receipt boundary and must not replace the selected semantic date.
     - A frame not yet acquired reads "not acquired" and claims nothing.
4. Every number on every screen links to the JSON path it came from, for traceability (`_jp`, `_code`; test named below).
5. The unratified state shows the numbers and the text "unratified: no verdict", never a winner.
6. Tier-(a) labels in the report:
   - Failures and cells built from tier-(a) occluder labels show the label tier beside them.
   - Tier-(a) labels are nonexhaustive. They never establish GT-face counts for the pool.
   - Real tier-(a) labels feed analysis only with a genuine recorded bounded observation and a documented applicability assessment (MEAS-29, see S7). The report shows "tier-(a): observation not recorded" and does not treat those rows as analysis input when no reference is recorded. A missing or unresolved record, or unsupported applicability, also blocks analysis, with the reason shown. Fixture-only helper output cannot satisfy this gate. Real tier-(a) use before a genuine production observation (MEAS-29, *Seeing with Fresh Eyes*, ch. 4) is not established by this report.
   - No observation is invented. Reuse depends on whether the observation still covers how the current measurements are produced: label rule, instructions, operators, collection/adjudication workflow and relevant tool/UI behaviour. Record the context comparison, changes, scope and limits. An unrelated version change alone does not require another human observation; a material change outside the observed scope, or uncertain applicability, requires a new bounded observation before those labels feed analysis. One sample never establishes unbiased measurement.

## RED tests

Present by name in `test_eval_harness_firbench_report*.py`. Not re-run for this document.

- **Offline and escaping:** `test_offline_inline_ui_has_no_external_network_and_escapes_data`, `test_page_inline_data_is_inert_and_round_trips`.
- **Skip link and tab order:** `test_skip_link_is_first_focusable_and_targets_verdict`, `test_tab_anchors_follow_map_order_and_each_targets_a_section`, `test_controls_and_focus_targets_are_visible_in_static_html`.
- **Verdict and reasons:** `test_verdict_line_shows_admissibility_n_eff_and_interval_for_each_leg`, `test_inconclusive_fixture_renders_reason_verbatim_and_no_winner`, `test_h1_inconclusive_renders_h2_as_not_evaluated`, `test_named_inconclusive_reasons_render_verbatim_without_winner`, `test_unratified_shows_numbers_and_no_verdict_text`, `test_numbers_link_to_their_json_path`.
- **Floors and cells:** `test_global_floor_fails_before_any_fpir_interval_is_shown`, `test_cell_with_29_independent_units_reads_not_scored`, `test_empty_cell_reads_collect_not_error`, `test_frame_absent_reads_not_acquired_and_floors_stay_separate`, `test_pair_cell_interval_withheld_even_if_present_below_floor`.
- **Glyphs:** `test_every_state_element_contains_a_glyph`.
- **Waterfall:** `test_fused_leg_waterfall_has_no_unaligned_row`, `test_unavailable_attribution_counts_sit_in_arm_availability_column`.
- **Pool accounting:** `test_pool_accounting_reconciles_selection_with_pool`, `test_missing_exhaustive_gt_reads_pool_not_established`, `test_pool_distinguishes_inventory_selection_and_fixed_background`, `test_unresolved_inventory_does_not_hide_scored_native_cohort`, `test_unresolved_face_is_never_nonmated_or_qualified`, `test_crop_counts_are_zero_and_no_data_uri_without_include_crops`, `test_failure_rows_use_only_pseudonymous_ids_and_stage_labels`.
- **Native summary against arm inventory:** `test_native_summary_and_declared_context_refusals`, `test_all_arm_outcome_corruptions_refuse`, `test_legacy_missing_searches_retain_full_gt_with_null_outcomes`.
- **Tier-(a) and S7 join:** `test_tier_a_labels_without_recorded_observation_block_analysis`, `test_reference_strings_and_metadata_cannot_qualify_tier_a`, `test_real_tier_a_reference_alone_withholds_analytics`, `test_invalid_evidence_is_refused_before_report_writes`, `test_actual_s7_join_requires_one_to_one_frame_annotations`, `test_actual_frozen_software_wire_requalifies_offline_and_displays`.
- **Chaining:** `test_chaining_zero_eligible_pairs_reads_not_evaluated_not_zero_risk`, `test_chaining_missing_evidence_reads_unavailable`, `test_chaining_malformed_evidence_is_an_error`.
- **Dendrogram and τ:** `test_dendrogram_without_production_cut_states_it_and_draws_tau_at_one_minus_tau`, `test_tau_is_visible_exact_and_zero_is_not_a_positive_log_measurement`, `test_exact_serialized_tau_above_one_is_kept_on_curve`.
- **Timestamp contract:** `test_missing_semantic_timestamp_on_manifest_is_refused`, `test_display_only_record_without_manifest_reads_date_not_recorded`, `test_seal_is_selected_over_ratification_and_equivalent_offset_accepted`, `test_ratification_is_selected_when_unsealed`, `test_explicit_created_at_without_derived_source_is_used`, `test_explicit_matching_only_ratification_is_refused_when_sealed`, `test_no_created_at_source_raises_and_writes_nothing`, `test_naive_or_malformed_created_at_refused_before_writes`.
- **Output:** `test_writing_to_benchmarks_reports_is_refused`, `test_same_run_renders_byte_identically_twice`, `test_end_to_end_fake_run_writes_every_artifact_and_no_pixels`, `test_default_cli_materializes_files_only_report`.
- **Browser (env-gated):** `test_actual_browser_interactions`, parametrized light and dark. It requires `FIR_REPORT_PLAYWRIGHT`.

Open (documentation only; no test yet):

- VIZ-35 range-frame assessment of the rendered UMAP projection, as in Build 2. Required task references must survive either outcome.
- The S2 curve reference lines at FPIR 0.001, 0.01 and 0.05 are drawn by `_curves_svg` (`:495`). No named test for them is yet identified in the report test family.

## Done when

Tests pass on the VM, using the test command in the firbench-1 README with an isolated basetemp. The AE-11 report task eval is runnable against the tracer run. The VIZ-35 assessment is recorded, one way or the other, for each rendered scatterplot.
