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
# F14 — FIR-12 join-boundary hygiene (`strata_join.py`)

Lane `lane/f14`. Files owned: `strata_join.py` + `test_eval_harness_strata_join.py`.
Public signatures (`load_stratum_index`, `join_by_stratum`, `StratumIndex`, `StratumReport`) kept; `StratumIndex` gained a trailing `sha256_by_media_id` field used only by the join.

Gate: `scene/tests` 1278 passed / 4 failed. Failures are the known PGPASSWORD / `InsecureProductionConfigError` quartet (`test_describe_route.py::test_create_app_registers_route_and_upload_cap` + three `test_describe_run_reclaim.py` startup tests). Nothing else new.

---

## BR-20 CLOSED (prior commit)

`49291fa477b8e2fc58aeb9cc42dfbabfc012aca7` `fix(eval): reject str/dict identities on join-record subjects`

`_subjects_of` now raises `StratumJoinError` on `str` / `dict` identity fields, matching `_identities` / `_entry_identities`. Malformed input no longer yields a plausible `unique_subjects` count.

Tests: `test_subjects_of_rejects_str_and_dict_identities`, `test_join_record_subjects_reject_str_and_dict`. Canon: **rg-008**, **rg-015**. Not re-mutated this turn (already committed before this continuation).

---

## BR-23 CLOSED (prior commit)

`b01e7f915e18aa0cc80daf9170f628ba4321dd88` `fix(eval): reject entry strata missing from strata_counts`

Load raises when `entries[i].stratum` is absent from `strata_counts`. The `.get(name, 0)` denominator path is gone; undeclared cells cannot render as complete with a zero denominator.

Test: `test_load_rejects_entry_stratum_missing_from_strata_counts`. Canon: **rg-008**, **rg-015**. Not re-mutated this turn.

---

## BR-22 CLOSED (this turn)

`c2bb51c9033ab93b30ca3c01a31c7df3307cd5d0` `fix(eval): canonicalize mixed sha256/media_id records to one image`

### What changed

`image_key = sha256 if sha256 is not None else str(media_id)` let one still keyed by sha256 (caption) and once by media_id (`FaceRunItem`) count as two images, inflating `n_images` and flipping `incomplete` (MLDATA-07). `_as_media_id` also coerced digit strings (`"6"`), a dual envelope the frozen schema never produces (rg-015).

Fix:

- Index `sha256_by_media_id` at load. Join keys every record to that canonical sha256 before inserting into the image set.
- One record carrying both keys must agree on that sha256, or raise `disagree on image`.
- Load rejects one `media_id` mapped to two sha256s (the 1:1 map would otherwise be last-write-wins).
- `_as_media_id` accepts only `int` (bool still excluded first). Digit strings and JSON bools raise `must be an int`.

`join_by_stratum` / `load_stratum_index` signatures unchanged. `StratumIndex` keeps its existing fields in the same order; `sha256_by_media_id` is appended.

### New tests

| Test | Asserts |
|---|---|
| `test_sha256_and_media_id_of_same_image_count_once` | Frozen Pacino still (`media_id=6`): `{sha256}` + `{media_id: 6}` → `n_images=1` |
| `test_face_run_item_and_sha256_caption_of_same_image_count_once` | Mixed `FaceRunItem` + caption envelope, same still |
| `test_three_envelopes_of_same_image_count_once` | sha-only + media_id-only + both-on-one-record → 1 |
| `test_mixed_keys_of_two_images_still_count_twice` | Pacino sha + Winehouse media_id stay 2 |
| `test_mixed_keys_do_not_flip_incomplete` | Declared 2, mixed keys of image 1 only → `n_images=1`, `incomplete=True`, gap reported |
| `test_mixed_keys_covering_declared_cell_is_complete` | Declared 1, three envelopes of that image → complete, no gaps |
| `test_record_keys_disagree_on_image_identity` | sha of A + media_id of B on one record raises |
| `test_digit_string_media_id_is_rejected_on_join` | `"6"` and `"06"` raise |
| `test_digit_string_media_id_is_rejected_at_load` | Manifest `media_id: "6"` raises |
| `test_bool_media_id_is_rejected_even_when_one_is_indexed` | `True` cannot join as media_id 1 |
| `test_load_rejects_media_id_mapped_to_two_sha256s` | 1:1 canonical map is load-time, not last-write-wins |

### TEST-15 mutants

**Mutant A — restore `image_key = sha256 if sha256 is not None else str(media_id)`.**
RED (5 failed):

```
FAILED ...::test_sha256_and_media_id_of_same_image_count_once - assert 2 == 1
FAILED ...::test_face_run_item_and_sha256_caption_of_same_image_count_once - assert 2 == 1
FAILED ...::test_mixed_keys_do_not_flip_incomplete - assert 2 == 1
FAILED ...::test_mixed_keys_covering_declared_cell_is_complete - assert 2 == 1
FAILED ...::test_three_envelopes_of_same_image_count_once - assert 2 == 1
```

**Mutant B — restore digit-string coerce in `_as_media_id`.**
RED (2 failed):

```
FAILED ...::test_digit_string_media_id_is_rejected_on_join - Failed: DID NOT RAISE StratumJoinError
FAILED ...::test_digit_string_media_id_is_rejected_at_load - Failed: DID NOT RAISE StratumJoinError
```

Both mutants reverted. File suite 25 passed after restore.

Canon: **rg-015** (no invented dual envelope; canonical id comes from the manifest, not `str(media_id)`), **rg-008** (reject digit-string / bool media_id at the boundary), **MLDATA-07** (mixed FaceRunItem + caption must not inflate `n_images` and hide `incomplete`).

---

## Not closed

Nothing. BR-20, BR-22, BR-23 all landed. Did not touch `fir_bakeoff_run.py`, `gallery_split.py`, or `open_set_identification.py`.

########## lane/f20

# FIR-12 BR-18 — probe identity survives the (probe image, gallery) seam — CLOSED

Canon: JANUS 2.2 (disjoint galleries), EVAL-18, sr-007.

- BR-18: `SearchResult` is now a `(probe image, gallery)` pair (`gallery: GalleryName | str`, `media_id: int`); `build_run_plan` stores `probes_for` on `RunPlan.probe_sets`; `score_run` classifies each `ProbeEntry` against `plan.split` / `probe_sets` (mated iff the still carries an identity enrolled in the declared gallery; otherwise foil). Tests: `test_search_result_requires_gallery_and_media_id`, `test_build_run_plan_consumes_probes_for`. Mutant: defaulted `gallery`/`media_id` → `test_search_result_requires_gallery_and_media_id` DID NOT RAISE TypeError.
- BR-18 undeclared gallery: `score_run` raises `FirBakeoffRunError` (not `assert`) when `SearchResult.gallery` is not a declared gallery of the split (`plan.probe_sets` keys). Test: `test_search_against_undeclared_gallery_raises`. Mutant: coerce unknown gallery to G1 → regex `'declared gallery'` missed (fell through as "filed as mated").
- BR-18 mated `true_name` must be enrolled in the declared gallery. Test: `test_mated_true_name_not_enrolled_in_declared_gallery_raises`. Mutant: skipped the `true_name not in identities` check → DID NOT RAISE.
- BR-18 failure mode 2 (silent drop of a co-present / enrolled identity): a non-mated filing whose probe *does* carry an enrolled identity in that gallery raises. Test: `test_nonmated_search_that_drops_enrolled_identity_raises`. Mutant: skipped the `elif identities` raise → DID NOT RAISE.
- BR-18 failure mode 1 (G1∪G2 as one closed set): a still enrolled in both galleries that appears with only one gallery in `searches` raises. Tests: `test_copresent_probe_with_one_gallery_raises`, `test_frozen_seed0_six_occluded_stills_are_enrolled_in_both_galleries`. Mutant: skipped the `seen != needed` raise → both DID NOT RAISE.
- BR-18 seed-0 fact (derived, not hardcoded in three places): `both_gallery_probe_entries(plan)` is 6 stills at seed 0; `both_gallery_search_count(plan)` is 12, not 6. Tests: `test_frozen_seed0_six_occluded_stills_are_enrolled_in_both_galleries`, `test_frozen_seed0_copresent_stills_yield_twelve_searches`, `test_copresent_probe_yields_two_searches`. Mutant: `both_gallery_search_count` returned `len(stills)` → `assert 6 == 12`.
- BR-18 failure mode 3 (stranger scored as FNIR miss): a probe-only stranger filed as mated raises. Test: `test_stranger_probe_filed_as_mated_raises`. Mutant: skipped the empty-identities mated check → error text no longer matched `'filed as mated'` (fell through to true_name-not-enrolled).

Did not touch FPI denominator / `n_enrolled_gallery_subjects` (FIR-12-BR-12), `gallery_split.py`, or `strata_join.py`.

Existing-test contract (not silent skips):
- `test_empty_search_lists_on_populated_probe_cell_are_incomplete` previously expected `search_shortfall == n_images` (32 on A). That encoded 1-search-per-still and counted strangers as expected mates. Shortfall is now expected mated `(probe, gallery)` units from `occluded_probes_for`; `n_images==32` stays pinned and `shortfall != 32` is pinned.
- `test_explicit_empty_overall_nonmated_is_unmeasured_fpi` `overall.n_mated` 4→3: stuffing Alice onto D_capture (Carol, a stranger) is now refused as a mated search.
- `test_mated_entry_with_true_name_none_raises` now `FirBakeoffRunError` at the seam (`true_name` not enrolled) instead of leaking scorer `ValueError`.

########## lane/f22

# FIR-12 BR-12 / BR-24 / BR-25 — FPI denominator + surviving mutants — CLOSED

Canon: JANUS 2.3.4, EVAL-19, MLDATA-07, MLDATA-09, rg-015, TEST-15.

- BR-12: `score_run` no longer defaults `n_enrolled_gallery_subjects` to `len(g1)+len(g2)`. Each IET point takes the unique declared `SearchResult.gallery` of the searches that compose it (`_enrolled_for` / `_roster_size`). Caller-supplied 53 at seed 0 is accepted; 109 is rejected. Rows carry `gallery`. A pooled overall point that spans both galleries has `n_enrolled_gallery_subjects is None` (no synthesized union). Tests: `test_honest_per_gallery_count_is_accepted_at_seed_0`, `test_enrolled_gallery_follows_declared_search_gallery` (replaces `test_enrolled_gallery_defaults_to_split_size`), `test_report_names_searched_gallery`, `test_overall_pooled_point_has_unmeasured_enrolled_denominator`, `test_enrolled_gallery_mismatch_raises`. Mutant: restore union default + `!= len(g1)+len(g2)` guard. RED:
```
FAILED test_honest_per_gallery_count_is_accepted_at_seed_0
  FirBakeoffRunError: n_enrolled_gallery_subjects=53 does not match gallery size 109 (len(g1)+len(g2))
FAILED test_enrolled_gallery_follows_declared_search_gallery
  AssertionError: assert 4 == 3
FAILED test_overall_pooled_point_has_unmeasured_enrolled_denominator
  AssertionError: assert 4 is None
FAILED test_report_names_searched_gallery
  AssertionError: assert 4 == 3
```

- BR-24 m12: `test_overall_point_pools_injected_searches` now uses two A hits + one C miss so search-weighted FNIR is 1/3 and the unweighted cell mean is 0.5. Mutant: `object.__setattr__(overall, "fnir", mean(cell FNIRs))`. RED: `assert 0.5 == 0.3333333333333333`.

- BR-24 m6: skip-E_clean-when-pooling is the correct source (BR-16). Inverse mutant (drop the `GALLERY_STRATUM` continue) is now RED: `test_gallery_searches_are_not_pooled_into_overall_fnir` (`search media_id=10 is not a probe in stratum 'E_clean'`) and `test_gallery_stratum_renders_enrolled_not_probed` (`assert 'E_clean' not in report.points`).

- BR-24 union-only-when-omitted: `test_overall_nonmated_is_declared_once_not_pooled` now also calls `score_run` without `overall_nonmated` and expects `FirBakeoffRunError`. Mutant: union stratum foils when the kwarg is omitted. RED: `DID NOT RAISE FirBakeoffRunError`.

- BR-24 strip-media_ids in `_templates_from_e_clean`: `test_group_photo_subjects_are_not_dropped` now asserts Dale/Eve `media_ids==(5,)`. Mutant: `media_ids = ()`. RED: `assert () == (5,)`.

- BR-24 drop finite-tau + enrolled-mismatch guards: `test_to_rows_carries_tau_and_enrolled_normalization` now expects empty-search `n_enrolled is None` (not the deleted union default), union count raises, and non-finite tau raises. Mutant: delete both guards. RED: `DID NOT RAISE FirBakeoffRunError` (union 4).

- BR-25 m3: `test_mated_identities_for_unknown_gallery_raises` — `mated_identities_for(..., gallery="banana")` raises `FirBakeoffRunError`. Mutant: swallow `ValueError` and substitute `GalleryName.G1`. RED: `DID NOT RAISE FirBakeoffRunError`.

- BR-25 m5: kept the `if name not in declared` branch (reachable: public `RunPlan` with `probe_sets` omitting G2). Test: `test_search_against_omitted_declared_gallery_raises`. Mutant: delete that branch. RED: `DID NOT RAISE FirBakeoffRunError`.

Did not touch `gallery_split.py`, `strata_join.py`, or `open_set_identification.py`. Did not add a second gallery concept beside BR-18 `SearchResult.gallery`.

########## lane/f25

# FIR-12 BR-30 — Template | str gallery split must agree — CLOSED

Chose **canonical co-assignment key**, not "require media_ids on Template". Empty `media_ids` on a still with no `{media}:{subject}` id is independence (a legal open-set split), not a missing-id error. Requiring media_ids would reject that roster in both forms and re-create the too-strict guard (MLDATA-09). Both forms now run through `_canonical_template`: explicit `media_ids` win; otherwise parse `'{media}:{subject}'`; otherwise `()`.

- BR-30 object path: `Template(template_id='99:alice')` / `'99:bob'` with default `media_ids=()` now co-assign like the string form, seeds 0–15. Test: `test_shared_still_coassigns_in_both_forms_across_seeds`. Mutant: `_as_template` returned Template objects without `_canonical_template`. RED: 16/16 seeds unequal; seed 0 alice/bob not co-assigned (`coassign`).
- BR-30 string guard: `{"alice": ["a1"], "bob": ["b1"]}` is accepted, matching empty-media Template objects. Test: `test_independent_single_still_roster_accepted_in_both_forms` (replaces `test_string_template_without_media_id_raises`). Mutant: string branch re-raised when parse yielded `()`. RED: `GallerySplitError: string template 'a1' cannot supply media ids`; object path still accepted.

Frozen seed 0 (explicit): **g1=53, g2=56, overlap=0**. Pinned by `test_frozen_frame_seed_0_gallery_sizes`.

Canon: JANUS 2.2, MLDATA-09, rg-015. Did not touch `fir_bakeoff_run.py`, `strata_join.py`, or `open_set_identification.py`.

