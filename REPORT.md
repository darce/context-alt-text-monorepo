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

## BR-15 (high) — empty foil set scored as measured overall IET — CLOSED

**What changed.** Bakeoff publication now uses `BakeoffIETPoint` with `fpi: int | None`. Empty foil lists (`n_nonmated == 0`) publish `fpi=None` and `fpi_per_enrolled_subject=None` unless the caller sets `closed_set=True`. `overall_nonmated=()` is no longer a silent FPI of zero. `closed_set=True` with any foil list raises. Unowned `IETPoint.fpi: int` in `open_set_identification.py` is unchanged; `_publish_point` maps the scorer onto the bakeoff contract.

**Tests.** `test_explicit_empty_overall_nonmated_is_unmeasured_fpi`, `test_omitted_foils_do_not_score_perfect_open_set_rejection`, `test_closed_set_fpi_zero_requires_explicit_flag`. Existing `test_declared_empty_cells_stay_in_the_table` now expects `fpi is None` (no foil workload on those cells) — contract correction, not a skip.

**AFTER reproductions (frozen seed 0):**
```
overall_nonmated=() with 1 foil on each of A/B/C/D:
  overall fpi=None n_nonmated=0 measured=True fnir=0.0
  points['A_true_occluder'].fpi=1
no foils anywhere (mated hits so FNIR is measured):
  overall fnir=0.0 fpi=None n_nonmated=0 measured=True fpi_per_enrolled_subject=None
closed_set=True, no foils: overall fpi=0
```
Second reproduction no longer prints `measured=True` with `fpi=0`.

**Mutant.** `_publish_point` always passed through `point.fpi` (empty foil list still publishes 0).

**RED output:**
```
FAILED test_explicit_empty_overall_nonmated_is_unmeasured_fpi
  AssertionError: assert 0 is None  (BakeoffIETPoint.fpi=0, measured=True)
FAILED test_omitted_foils_do_not_score_perfect_open_set_rejection
  AssertionError: assert 0 is None
FAILED test_closed_set_fpi_zero_requires_explicit_flag
  AssertionError: assert 0 is None  (omitted.overall.fpi)
```

**Canon.** EVAL-18 (JANUS IET: FPI is an integer count over a declared non-mated set; no FPI of zero over an undeclared one). EVAL-19 (do not publish a rate/count whose denominator the run never declared).

**Could not close.** Did not edit `open_set_identification.py` (`IETPoint.fpi` stays `int` there). The bakeoff layer is the publication surface this lane owns.

---

---

# FIR-12 round-3 fix merge (F8 + F9)
# F13 — FIR-12 split + scorer boundary hygiene

## BR-19 (medium) — CLOSED (commit `00693367`)

Non-finite IET inputs no longer score as a clean measurement.

- `fnir_fpi_at_threshold` now requires finite `tau` (`_require_finite`) so `iet_curve` and direct callers cannot skip the bakeoff `score_run` gate.
- `_is_fnir_miss` / `_is_fpi` reject a non-finite `top1_score` on a detected search instead of letting IEEE NaN comparisons count as a mate hit.

Tests: `test_non_finite_tau_is_not_a_clean_measurement`, `test_non_finite_detected_score_is_not_a_hit`.
Canon: EVAL-18 / EVAL-16.
Landed on a previous turn; not re-mutated here.

## BR-21 (medium) — CLOSED

String convenience templates no longer default `media_ids=()`. `_as_template` parses `'{media}:{subject}'` (the form this module generates) or raises `GallerySplitError`. Existing string-id fixtures now go through `Template(..., media_ids=(n,))` so independent-subject tests stay independent.

Tests: `test_string_templates_parse_media_ids_and_coassign_shared_still`, `test_string_template_without_media_id_raises`.
Mutant: restored `return Template(template_id=value, subject_id=subject_id)` (empty media default).
RED:
- `test_string_templates_parse_media_ids_and_coassign_shared_still` — `assert ('alice' in split.g1) == ('bob' in split.g1)` failed; alice and bob sharing still 99 landed in different galleries with `media_ids=()`.
- `test_string_template_without_media_id_raises` — `DID NOT RAISE GallerySplitError`.
Canon: JANUS 2.2 / MLDATA-09.

## BR-13 (medium) — CLOSED

`_assert_invariants` now refuses an empty G1 or G2. Component co-assignment puts a single connected component entirely in G1; that cannot support a 1:N search. `build_disjoint_galleries` raises `GallerySplitError` instead of returning the split. `test_shared_still_coassigns_subjects_and_keeps_probe_media_disjoint` gained an independent third subject so co-assignment is still asserted on a legal two-gallery split (the original two-subject fixture *was* a single component).

Tests: `test_single_component_roster_refuses_empty_gallery` (single-subject and two-subject shared-still rosters), `test_frozen_frame_both_galleries_nonempty_across_seeds` (seeds 0–63; passed on the frozen frame before the invariant, as the brief said — latent, not live).
Mutant: removed the empty-G1/G2 check from `_assert_invariants`.
RED: `test_single_component_roster_refuses_empty_gallery` — `DID NOT RAISE GallerySplitError`.
Canon: EVAL-18 (open-set 1:N needs the other gallery as the non-mated source).

Gate: `scene/tests` 1268 passed, 4 skipped. The four failures are the known PGPASSWORD / `InsecureProductionConfigError` boot tests (`test_create_app_registers_route_and_upload_cap` and the three `test_describe_run_reclaim.py` startup tests).

Nothing left open.
