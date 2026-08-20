# Lane N4 — FIR-12 Phase 1 steps 3–4 (`fir_bakeoff_run`)

Composed `gallery_split` + injected `SearchResult`s + `strata_join` into
`scripts/eval_harness/fir_bakeoff_run.py`. Did not edit upstream modules.
Did not run detect→embed→search.

- **Unmeasured FNIR (MLDATA-09, EVAL-18).** `to_rows()` uses `IETPoint.format_fnir()`; a zero-mated stratum stays `"not measured"` with FPI still counted (`test_zero_mated_stratum_renders_unmeasured_fnir_and_keeps_fpi`). Mutant `/tmp/fir12-n4-coerce-fnir.py` (`fnir=0.0` when `None`) → `0.0 == 'not measured'` RED.
- **Coverage gaps (MLDATA-07, rg-015).** `RunReport.coverage_gaps()` delegates to `StratumReport.coverage_gaps()` (no module-level function exists). Partial A (1 joined / 4 declared) yields a non-empty gap list (`test_partial_stratum_run_reports_coverage_gaps`). Mutant `/tmp/fir12-n4-empty-gaps.py` (`return []`) RED.
- **`manifest_images` pass-through (rg-015).** Rows copy `base["manifest_images"]` verbatim (`test_manifest_images_passed_through_not_recomputed`). Mutant `/tmp/fir12-n4-recompute-manifest.py` (`n_images`) → `1 == 4` RED.
- **Mated `true_name is None`.** Upstream `_is_fnir_miss` already raises `ValueError("mated SearchResult requires true_name")`; no duplicate guard. Composition test `test_mated_entry_with_true_name_none_raises`. Mutant `/tmp/fir12-n4-swallow-none.py` (drop those entries before scoring) → DID NOT RAISE RED.
- **EVAL-16 not undone.** Injected undetected mated probes remain FNIR misses (`test_undetected_mated_probe_counts_as_fnir_miss`). Mutant `/tmp/fir12-n4-drop-undetected.py` (filter `detected`) → `fnir 0.0 == 0.5` RED.
- **EVAL-19 FPI is an integer count.** Rows carry `point.fpi` (int), not `fpi/n_nonmated`; enrolled-gallery normalization stays on `IETPoint.fpi_per_enrolled_subject` (`test_fpi_is_integer_count_not_rate_over_nonmated`). Mutant `/tmp/fir12-n4-fpi-rate.py` → `0.5 == 1` RED.
- **Declared-empty cells stay in the table (MLDATA-09).** `mask_sufficient_n` / `veil` / `goggles` / `hair_occl` appear with `declared_empty=True` and `"not measured"` (`test_declared_empty_cells_stay_in_the_table`). Mutant `/tmp/fir12-n4-drop-empty-cells.py` RED.
- **Unique-subject count on every cell (MLDATA-07).** `test_unique_subjects_on_every_row` (E_clean=4 including group-photo subjects). Mutant `/tmp/fir12-n4-drop-group-photos.py` drops Dale/Eve → `test_group_photo_subjects_are_not_dropped` RED.
- **Seed recorded, not only consumed.** `RunPlan.seed` / `RunReport.seed` (`test_seed_is_recorded_and_reproducible`). Mutant `/tmp/fir12-n4-unrecorded-seed.py` (`RunPlan(..., seed=0)`) → `0 == 11` RED.

Group-photo E_clean templates omit `media_ids` (shared media_id fails `gallery_split` G1/G2 disjointness on every seed of the frozen 640); subjects are still enrolled. Frozen-frame plan: 109 gallery subjects, probes 32/80/34/87.

15 tests green after restore.
