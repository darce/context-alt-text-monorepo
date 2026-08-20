# FIR-12 F12 — measurement honesty in `fir_bakeoff_run.py`

Through-line: an absent workload must not render as a confident measurement of zero.

## BR-14 (low) — withheld probe templates — CLOSED (prior commit `90203524`)

Not re-done this lane. Seed 0 still publishes `n_withheld_probe_templates=2`. Canon: MLDATA-07 / MLDATA-09.

## BR-17 (high) — empty search lists on a populated probe cell — CLOSED (prior commit `c0036631`)

Not re-done this lane. Seed 0 A/B/C/D keys with empty lists: `search_shortfall` equals plan probe-entry count, `incomplete=True`, `fnir='not measured'`. Canon: EVAL-16 / EVAL-19.

## BR-16 (high) — `E_clean` scored as a probe cell and pooled into overall FNIR — CLOSED

**What changed.** `score_run` skips `GALLERY_STRATUM` when building `points` and `all_mated`. `to_rows()` renders `E_clean` as `fnir='enrolled, not probed'` (not `'not measured'`). An injected `E_clean` search key is ignored, not pooled.

**Tests.** `test_gallery_stratum_renders_enrolled_not_probed`, `test_gallery_searches_are_not_pooled_into_overall_fnir`.

**AFTER (seed 0, A/B/C/D keys only):**
```
E_clean in points: False
E_clean row: n_images=342 declared_empty=False measured=False fnir='enrolled, not probed'
```
Pooling mutant from the brief (`A fnir=1.0`, three enrolled hits on `E_clean`): AFTER `overall.n_mated=1` `overall.fnir=1.0` (not `0.25` over `n_mated=4`).

**Mutant.** Deleted the `if name == GALLERY_STRATUM: continue` skip in `score_run`.

**RED output:**
```
FAILED test_gallery_stratum_renders_enrolled_not_probed
  AssertionError: assert 'E_clean' not in report.points
FAILED test_gallery_searches_are_not_pooled_into_overall_fnir
  AssertionError: assert 'E_clean' not in report.points
```

**Canon.** MLDATA-09 (a populated, deliberately-not-probed enrollment stratum must not look like an untested probe cell; pooling it dilutes the occluded-probe claim).

## BR-15 (high) — empty foil set scored as measured overall IET — OPEN

Next.

---

# FIR-12 round-3 fix merge (F8 + F9)

BR-07: `score_run(..., overall_nonmated=)` scores the overall IET point from that list; per-stratum foils are never pooled, and omitting it while any stratum has non-mated searches raises `FirBakeoffRunError`. Tests: `test_overall_nonmated_is_declared_once_not_pooled`, `test_omitting_overall_nonmated_with_stratum_nonmated_raises`, `test_mated_searches_still_pool_across_strata`. Mutant `/tmp/fir12-f8-mutants/br07.py` restored `extend` pooling → `overall.fpi==4` / `n_nonmated==8` (wanted 1 / 2) and omit no longer raised.
BR-09: every populated `PROBE_STRATA` name with `manifest_images > 0` (not declared-empty, not `E_clean`) must appear as a `searches` key; missing keys raise listing them; explicit `{"mated": [], "nonmated": [...]}` stays legal and unmeasured. Tests: `test_missing_populated_probe_stratum_raises`, `test_empty_searches_raises_for_populated_probe_strata`, `test_explicit_empty_mated_list_is_unmeasured_not_missing`. Mutant `/tmp/fir12-f8-mutants/br09.py` dropped the missing-key check → omit `B_eyewear` / `searches={}` did not raise.
BR-10: `n_enrolled_gallery_subjects` defaults to `len(g1)+len(g2)` and mismatches raise naming both counts; non-finite `tau` raises; `to_rows()` carries `tau`, `fpi_per_enrolled_subject`, `n_enrolled_gallery_subjects`. Tests: `test_enrolled_gallery_mismatch_raises`, `test_enrolled_gallery_defaults_to_split_size`, `test_non_finite_tau_raises`, `test_to_rows_carries_tau_and_enrolled_normalization`. Mutant `/tmp/fir12-f8-mutants/br10.py` skipped the checks and stripped those columns → mismatch/nan did not raise, `KeyError: 'tau'`.

# FIR-12 F9

- BR-08: `build_disjoint_galleries` now co-assigns subject×media connected components, `_templates_from_e_clean` restores real group `media_ids`, and colliding leftovers land on `GallerySplit.withheld_probe_templates`. Covered by `test_shared_still_coassigns_subjects_and_keeps_probe_media_disjoint`, `test_only_shared_still_subject_is_enrolled_not_dropped`, `test_frozen_manifest_galleries_media_disjoint_across_seeds`, `test_frozen_manifest_withholds_shared_probe_stills_at_seed_0`. Mutant `/tmp/mut-br08-media` restored `media_ids=()` → seed-0 sweep RED `{353,554,632} != set()`; mutant `/tmp/mut-br08-assign` restored per-subject assignment → unit RED `gallery media ids are not disjoint: [7]`. Seed 0: G1=53 / G2=56 (skew 3); withheld=2 (`353:Pewter Hollow`, `632:Burnished Ridgeway`); Tidal Quarry and Dappled Meadow both enrolled in G2.
- BR-11: `_identities` and `_entry_identities` raise on non-list/non-tuple `present_identities` (`FirBakeoffRunError` / `StratumJoinError`); list, tuple, empty list, and missing key stay legal. Covered by `test_present_identities_rejects_str_and_dict` and `test_present_identities_list_and_absent_are_legal`. Mutant `/tmp/mut-br11` restored the bare-string wrap → RED `DID NOT RAISE FirBakeoffRunError`.
