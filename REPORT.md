# UXW2-5-R1 report

Close all 14 round-1 findings. TDD. Quality from ranking rows. PHP tenant-scoped lookup + collapse. 502/503 degraded. Schema: probe-level `quality_flag`, `probe_face_count`, `reference_face_count`.

## RED

PY (16 failed, 6 passed): `quality_flag`/`probe_face_count` missing; `min_similarity=0` dropped negative cosine; dim mismatch `ValueError` matmul; `FakeClusterRepository.seed` no `representatives`; no `get_representative_embeddings_with_quality`.

PHP (1 error, 6 failures): `lookup_person_ids_for_clusters` missing; `minimum` null; timeout 2≠10; collapse 2≠1; `-5` not WP_Error; 200 degraded not 502/503.

## GREEN

- PY targeted roster: `30 passed`
- PY full: `3662 passed, 65 skipped, 1 failed` — fail is **pre-existing** (stash+rerun): `test_committed_fixtures_match_current_generator` `ModelMissingError` sface onnx absent; our diff does not touch `face_pipeline`.
- PHP: `1772 tests, 8591 assertions, OK` (was 1767 / 8533)
- TEST-15: `band_for` `>=` → `>` made `0.70` POSSIBLE not STRONG. PHP collapse skip → `count 2≠1`. Both restored.

## Closure

| ID | commit | test | killed |
|---|---|---|---|
| R1-01 | `40367066fcb93392fdecd5f6a2a9a153c22bda6b` | `test_quality_does_not_read_get_by_id_representatives`, `test_quality_flag_fail_closed_when_metrics_missing`, `test_member_fallback_quality_fail_closed_when_metrics_missing`, `test_get_representative_embeddings_with_quality_returns_aligned_metrics` | quality from ranking-row loader; missing metrics → `low_quality` |
| R1-02 | `b528e9567397cc1901960268d89893dc51f3a84e` | `testLookupPersonIdsForClustersIsTenantScopedAndJoinsPersons` | `AND tenant_id`, `wp_acx_clusters`, `guard_query_error` |
| R1-03 | `b528e9567397cc1901960268d89893dc51f3a84e` | `testGetRosterCandidatesUnavailableIs503WithoutFabricatedEnvelope`, `testGetRosterCandidatesEndpointErrorIs502WithoutFabricatedEnvelope` | 503/502 WP_Error; no fabricated `total`/`limit`/`candidates` |
| R1-04 | `40367066fcb93392fdecd5f6a2a9a153c22bda6b` | `test_roster_candidates_ranks_labelled_excludes_foreign_tenant_and_validates_schema` | ranked ids, live thresholds 0.40/0.80/0.77, foreign tenant absent, jsonschema |
| R1-05 | `40367066fcb93392fdecd5f6a2a9a153c22bda6b` | `test_top_k_returns_exact_ids_from_out_of_rank_seed`, `test_multi_rep_cluster_uses_max_not_mean_or_first`, `test_quality_flag_ok_when_metrics_above_floor`, `test_quality_flag_low_from_single_metric` | exact top ids; max 0.9; OK + det/landmark-only LOW |
| R1-06 | `b528e9567397cc1901960268d89893dc51f3a84e` | `testGetRosterCandidatesCollapsesDuplicateRosterEntryIds`, mapping test name | one row/person; `acx_persons.name`; null uncommittable kept |
| R1-07 | `b528e9567397cc1901960268d89893dc51f3a84e` | mapping test timeout 10 | `REQUEST_CLASS_POST_SCAN_READ` |
| R1-08 | `b528e9567397cc1901960268d89893dc51f3a84e` | mapping test `$wpdb->queries`; `permission_callback === can_manage_recognition` | SQL table/cols/IN/tenant; second candidate null |
| R1-09 | `40367066fcb93392fdecd5f6a2a9a153c22bda6b` | `test_low_quality_caps_band_at_possible` | sim≥ceiling + LOW → band `possible` |
| R1-10 | `40367066fcb93392fdecd5f6a2a9a153c22bda6b` | `test_negative_similarity_returned_as_none_band`, `test_tiebreak_is_cluster_id`, `test_dimension_mismatched_reps_are_skipped` | none band; id ASC; skip mismatch |
| R1-11 | `b528e9567397cc1901960268d89893dc51f3a84e` | route `minimum 1`/`maximum 50`; `testGetRosterCandidatesRejectsInvalidTopKWithoutSignFlip` | `-5`/`0` 400; no absint |
| R1-12 | `40367066fcb93392fdecd5f6a2a9a153c22bda6b` | schema + API jsonschema; envelope `quality_flag`/`probe_face_count`/`reference_face_count` | candidate no longer stamps quality |
| R1-13 | `40367066fcb93392fdecd5f6a2a9a153c22bda6b` | `embedding_space.py` used by roster + `label_inference` | documented narrowing: no SQL MediaIdentity fallback |
| R1-14 | this file | `git cat-file -e` on code SHAs | real SHAs; contract edited in place (gitignored `/docs/workbay/contracts`) |

## Files

Python: `roster_candidates.py`, `embedding_space.py`, `label_inference.py`, `cluster_repository.py`, `responses.py`, `suggestions.py` router, `fakes.py`, `stubs.py`, tests, `roster-candidates-response.schema.json`.

PHP: `class-clusters-read-repository.php`, `class-suggestions-controller.php`, tests.

Contract (untracked): `docs/workbay/contracts/recognition-clustering.md`.

## Canon

| ID | file:line | how |
|---|---|---|
| PROV-06 | lexicons/ml-systems.md:423 | `model_id`, `embedding_model`, `computed_at`, `thresholds`, probe `quality_flag` |
| DRIFT-03 | lexicons/ml-systems.md:352 | bands from live settings |
| CAL-01 | lexicons/ml-systems.md:321 | quality from `fatal_quality_floor` / `fatal_confidence_floor` |
| CAL-02 | lexicons/ml-systems.md:322 | empty roster 200; `band=none`; 502/503 ≠ empty |
| CAL-03 | lexicons/ml-systems.md:323 | cosine not a frequency |
| CAL-11 | lexicons/ml-systems.md:331 | low quality caps Strong |
| EMB-01 | lexicons/ml-systems.md:167 | shared FIR23-01 same-space helper |
| EMB-02 | lexicons/ml-systems.md:168 | max over reps, not mean |
| EMB-09 | lexicons/ml-systems.md:175 | quality gates flag; score not uncertainty-penalized |
| EMB-11 | lexicons/ml-systems.md:177 | `occluded` reserved |
| HAI-08 | lexicons/interaction-ux.md:217 | band is the decision grain |
| HAI-05 | lexicons/interaction-ux.md:214 | typed payload for disclosure |
| MEAS-05 | lexicons/epistemics.md:206 | no % arithmetic |
| API-01 | lexicons/engineering.md:502 | `top_k` 1–50 reject-not-clamp |
| TEST-15 | lexicons/engineering.md:396 | mutations above |
| rg-015 | docs/workbay/constitution.md:48 | PHP does not invent `total`/`limit`; degraded is 502/503 |

## Decisions

- Quality from `get_*_embeddings_with_quality` (same SQL rows as ranking), not `get_by_id` reps.
- Degraded path = 502/503 error envelope (not fabricated PROV 200).
- PHP collapse by `roster_entry_id`; null rows kept flagged.
- R1-13: extract `representative_embedding_model` / `same_space_vector`; SQL fallback stays in label_inference (eager-loaded identity on labelled reps).

## Undone

- FE `PersonCommitControl` (out of lane)
- FIR-6 S4 calibrated knobs
- EMB-11 spatial occlusion; EMB-09 score penalty
- Pre-existing PY fail: missing sface onnx in this checkout

## HEAD

report `1d49665134195fd04e9e85fb83b33186d014afa7`
python `40367066fcb93392fdecd5f6a2a9a153c22bda6b`
php `b528e9567397cc1901960268d89893dc51f3a84e`
