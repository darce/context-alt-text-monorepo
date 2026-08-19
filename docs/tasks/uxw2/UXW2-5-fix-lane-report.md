# UXW2-5 fix lane r3 report

Close remaining R2 + R3. TDD. Contract SSOT committed. PHP people-grain window pinned. `invalid_top_k` from the route callback.

## GREEN (this checkout)

- PY targeted (`recognition/tests/unit/test_roster_candidates.py` + `recognition/tests/api/test_roster_candidates.py`): `26 passed in 4.93s`
- PY full (`uv run --extra dev pytest -q recognition/tests`): `1 failed, 2165 passed, 61 skipped, 9 warnings in 288.30s` — fail is **pre-existing** `test_committed_fixtures_match_current_generator` `ModelMissingError` sface onnx absent. Diff does not touch `face_pipeline`.
- PHP (`composer test`): `OK (1778 tests, 8640 assertions)`

## Closure

| ID | commit subject | test | mutant RED line |
|---|---|---|---|
| R1-01 | `fix(recognition): UXW2-5-R1-01,04,05,09,10,12,13 ranking quality envelope` (earlier) | `test_quality_does_not_read_get_by_id_representatives`; fail-closed missing metrics | quality from ranking-row loader; missing metrics → `low_quality` |
| R1-02 | `fix(api): UXW2-5-R1-02,03,06,07,08,11 tenant lookup collapse errors top_k` (earlier) | `testLookupPersonIdsForClustersIsTenantScopedAndJoinsPersons` | `AND tenant_id` / `wp_acx_clusters` |
| R1-03 | same as R1-02 (earlier) | 503/502 tests | 200 degraded envelope |
| R1-04 | same as R1-01 (earlier) | `test_roster_candidates_ranks_labelled_excludes_foreign_tenant_and_validates_schema` | foreign tenant present / schema miss |
| R1-05 | same as R1-01 (earlier) | exact top ids; max-not-mean; OK + det/landmark-only LOW | insertion-order ids; mean sim |
| R1-06 | earlier PHP + `fix(api): UXW2-5-R2-02 UXW2-5-R1-06 max-similarity collapse and people-grain top_k` (earlier) | `testGetRosterCandidatesCollapseKeepsMaxSimilarityWhenLoserListedFirst` | `Failed asserting that 0.7 is identical to 0.91.` |
| R1-07 | same as R1-02 (earlier) | mapping timeout 10 | timeout 2≠10 |
| R1-08 | same as R1-02 (earlier) | mapping SQL + permission_callback | missing tenant SQL |
| R1-09 | same as R1-01 (earlier) | `test_low_quality_caps_band_at_possible` | Strong on low-quality probe |
| R1-10 | same as R1-01 (earlier) | negative cosine none; tie cluster_id ASC; dim skip | `min_similarity=0` dropped negatives |
| R1-11 | same as R1-02 (earlier) | route min/max; rejects -5/0 | absint sign-flip |
| R1-12 | same as R1-01 (earlier) | envelope `quality_flag`/`probe_face_count`/`reference_face_count` | candidate-stamped quality |
| R1-13 | same as R1-01 (earlier) | shared `same_space_vector` | SQL fallback invented |
| R1-14 | this file (relocated from root `REPORT.md`) | `test ! -f REPORT.md`; `git cat-file -e` loop | prior root REPORT; dead SHAs |
| R2-01 | this file | this file | prior REPORT cited dead SHAs / false GREEN |
| R2-02 | `fix(tests): UXW2-5-R2-02 UXW2-5-R3-02 collapse order and people-grain window` (this round; earlier max-sim collapse remains) | `testGetRosterCandidatesReordersAndSlicesOutOfOrderPythonWindow` | usort deleted: `Failed asserting that two arrays are identical.` `- 0 => 1,` `+ 0 => 4,` |
| R2-03 | `fix(recognition): UXW2-5-R2-03 wire-level quality_flag is not a literal ok` (earlier) | `test_roster_candidates_low_quality_flag_caps_strong_band_on_the_wire` | `AssertionError: assert 'ok' == 'low_quality'` |
| R2-04 | `fix(recognition): UXW2-5-R2-04 discriminate member-fallback quality loader` (earlier) | member-fallback quality tests | `AssertionError: assert 3 == 1` |
| R2-05 | `fix(recognition): UXW2-5-R2-05 protocol quality triple names match SELECT` (earlier) | protocol alias notes | `landmark_quality` as column |
| R2-06 | `fix(recognition): UXW2-5-R2-06 probe_face_count is dim-filtered length` (earlier) | `test_probe_face_count_equals_dim_filtered_length` | `AssertionError: assert 3 == 2` |
| R2-07 | `fix(contracts): UXW2-5-R2-07 single roster-candidates contract section` (this round) | `test_contract_roster_candidates_example_validates_against_schema` | `AssertionError: assert 2 == 1` |
| R2-08 | `fix(recognition): UXW2-5-R2-08 get_by_id fake returns fused_low representatives` (earlier) | `test_quality_does_not_read_get_by_id_representatives` | quality from `probe.representatives` |
| R2-09 | `fix(recognition): UXW2-5-R2-09 rank order is not insertion order; empty roster has a probe` (earlier) | ranking exact `[strong, possible]`; empty-roster probe reps | `At index 0 diff:` insertion-order id ≠ rank-order id |
| R2-10 | `fix(api): UXW2-5-R2-10 UXW2-5-R3-01 invalid_top_k from route callback` (this round) | `testDispatchRosterCandidatesInvalidTopKUsesSpecificError` | `-'invalid_top_k'` / `+'rest_invalid_param'` |
| R3-01 | same as R2-10 | dispatch `has_valid_params` wrap; no `validate_callback`; single `INVALID_TOP_K_*` literal | callback check removed: `Failed asserting that an object is an instance of class WP_Error.` |
| R3-02 | same as R2-02 | `testGetRosterCandidatesReordersAndSlicesOutOfOrderPythonWindow`; tie `testGetRosterCandidatesTieBreaksEqualSimilarityByClusterIdAsc` | array_slice removed: `Failed asserting that actual size 4 matches expected size 2.` |
| R3-03 | `fix(api): UXW2-5-R3-03 python window constant not forwarded verbatim` | register description + mapping query uses `ROSTER_CANDIDATES_PYTHON_WINDOW` | `does not contain "Forwarded verbatim"`; `Failed asserting that false is identical to 50.` |
| R3-04 | `fix(api): UXW2-5-R3-04 uncommittable rows rank after committable` | `testGetRosterCandidatesRanksUncommittableAfterCommittableForTopK` | `Failed asserting that two arrays are identical.` `- 0 => 1,` `- 1 => 2,` `+ 0 => null,` `+ 1 => 1,` |
| R3-05 | `fix(tests): UXW2-5-R3-05 empty-probe wire case` | `test_roster_candidates_empty_probe_when_all_reps_fail_quality_gate` | mutant empty-probe `quality_flag=ok`: `AssertionError: assert 'ok' == 'low_quality'` |

## Decisions (this round)

- One roster-candidates contract section: envelope `quality_flag` + `probe_face_count` + `reference_face_count`; people-grain collapse; PHP window coupled to `MAX_ROSTER_CANDIDATES_TOP_K`; uncommittable rows after committable; low_quality band cap.
- Option (a): WP `args` keep type/min/max only; callback returns `WP_Error('invalid_top_k', …, 400)`. Core `has_valid_params` would wrap a `validate_callback` error as `rest_invalid_param`.
- PHP fetches `ROSTER_CANDIDATES_PYTHON_WINDOW` (50), not client `top_k`.

## Undone

- FE `PersonCommitControl` (out of lane)
- FIR-6 S4 calibrated knobs
- EMB-11 spatial occlusion
- Pre-existing PY fail: missing sface onnx in this checkout
