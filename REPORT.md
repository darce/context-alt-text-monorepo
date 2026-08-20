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
