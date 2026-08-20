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

## BR-13 (medium) — OPEN

Empty-gallery invariant not yet added.
