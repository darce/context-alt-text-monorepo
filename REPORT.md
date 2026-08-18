# UXW2-5-R2 report

Close R1-06, R1-14, and R2-01..10. TDD. PHP people-grain collapse. Probe-level quality on the wire.

## RED

| ID | failing line |
|---|---|
| R2-02 / R1-06 | `Failed asserting that 0.7 is identical to 0.91.` |
| R2-02 | `Failed asserting that two strings are identical. '50' vs '2'` |
| R2-03 | `AssertionError: assert 'ok' == 'low_quality'` |
| R2-04 | `AssertionError: assert 3 == 1` (`quality_score` selected twice / `quality_score__1`) |
| R2-05 | docstring only — `landmark_quality` was a slot name, not a column |
| R2-06 | `AssertionError: assert 3 == 2` (`probe_face_count`) |
| R2-07 | `AssertionError: assert 2 == 1` (duplicate roster-candidates headings) |
| R2-08 | mutant: `assert QualityFlag.LOW_QUALITY is QualityFlag.OK` |
| R2-09 | `At index 0 diff:` insertion-order id `!=` rank-order id |
| R2-10 | `-'invalid_top_k'` / `+'rest_invalid_param'` |
| R2-01 / R1-14 | prior REPORT cited SHAs that fail `git cat-file -e` here; false GREEN "30 passed" |

## GREEN

- PY targeted (`test_roster_candidates.py` unit+api + `test_cluster_repository_provenance.py`): `31 passed in 3.98s`
- PY full: `1 failed, 3667 passed, 65 skipped, 23 warnings in 323.56s` — fail is **pre-existing** `test_committed_fixtures_match_current_generator` `ModelMissingError` sface onnx absent. Our diff does not touch `face_pipeline`.
- PHP: `OK (1775 tests, 8635 assertions)`

## Closure

| ID | commit (40-char, this repo) | test | TEST-15 mutant killed |
|---|---|---|---|
| R1-06 | `9e324879f5d5b3b3ca0fc6d6d54c21dfcbc5a450` `fix(api): UXW2-5-R2-02 UXW2-5-R1-06 max-similarity collapse and people-grain top_k` | `testGetRosterCandidatesCollapseKeepsMaxSimilarityWhenLoserListedFirst` | first-wins: `0.7 is identical to 0.91` |
| R2-02 | same commit | `testGetRosterCandidatesSlicesPeopleGrainAfterCollapseFromWiderPythonWindow` | skip-collapse: `actual size 2 matches expected size 1` |
| R2-03 | `e57b138b9a2aa68d8e7375bc0717970af5a3f2ed` `fix(recognition): UXW2-5-R2-03 wire-level quality_flag is not a literal ok` | `test_roster_candidates_low_quality_flag_caps_strong_band_on_the_wire` | `quality_flag="ok"` → `assert 'ok' == 'low_quality'` |
| R2-04 | `a96ff5466ae785494fc8f5464b9759f2e934aa40` `fix(recognition): UXW2-5-R2-04 discriminate member-fallback quality loader` | `test_member_fallback_prefers_quality_loader`, `test_get_member_fallback_embeddings_with_quality_filters_then_limits` | `fallback_quality=None` → `assert []` |
| R2-05 | `f3e46ed901df9cebbd82a1e3cee5a260a187b620` `fix(recognition): UXW2-5-R2-05 protocol quality triple names match SELECT` | grep `landmark_quality` in `repositories.py` is alias notes only | n/a (docstring) |
| R2-06 | `46afcfd92ef059f98bfe39f9d73bfaffaa8b3cf6` `fix(recognition): UXW2-5-R2-06 probe_face_count is dim-filtered length` | `test_probe_face_count_equals_dim_filtered_length` | count 3 vs filtered 2 |
| R2-07 | `e16775f9a75842a963a1e9ac598fe9929a230892` `fix(contracts): UXW2-5-R2-07 single roster-candidates contract section` | `test_contract_roster_candidates_example_validates_against_schema` | two headings → `assert 2 == 1` |
| R2-08 | `8953ee64447f2838256d37a7933ab409a7e9d335` `fix(recognition): UXW2-5-R2-08 get_by_id fake returns fused_low representatives` | `test_quality_does_not_read_get_by_id_representatives` | quality from `probe.representatives` → LOW_QUALITY |
| R2-09 | `1cd5835ee6aa48f64a739edb736551d0c00c84a8` `fix(recognition): UXW2-5-R2-09 rank order is not insertion order; empty roster has a probe` | ranking exact `[strong, possible]`; empty-roster probe reps | drop-sort: insertion order ≠ rank order |
| R2-10 | `cd27813b3ca27b1c3cdc99ef6cd75e22b30f23ed` `fix(api): UXW2-5-R2-10 validate_callback returns invalid_top_k WP_Error` | `testDispatchRosterCandidatesInvalidTopKUsesSpecificError` | bool-false dispatch → `rest_invalid_param` |
| R1-14 | HEAD (this commit) `docs: UXW2-5-R2-01 UXW2-5-R1-14 REPORT` | `git cat-file -e` loop after commit | n/a |
| R2-01 | same as R1-14 | this file | n/a |

## Files

Python: `roster_candidates.py`, `cluster_repository.py`, `repositories.py`, unit/api roster tests, `test_cluster_repository_provenance.py`.

PHP: `class-suggestions-controller.php`, `SuggestionsControllerTest.php`.

Schema: `packages/shared-contracts/schemas/roster-candidates-response.schema.json`.

Contract (`docs/workbay/contracts/recognition-clustering.md`) — replacement section (one heading; example validates):

~~~~
### GET /recognition/clusters/{cluster_id}/roster-candidates

Query params:

- `tenant_id` (header or query; same tenant scoping as sibling cluster reads)
- `top_k` (default 10, min 1, max 50; rejected with 400 when out of range — never clamped)

Ranks labelled clusters against an unlabeled probe. Comparison is max-cosine over same-`embedding_model` representative sets only (FIR23-01 / EMB-01). Python has no person table: each candidate is keyed by labelled `cluster_id` + `name` (cluster label). Schema: `packages/shared-contracts/schemas/roster-candidates-response.schema.json`.

Python `top_k` is cluster-grain. PHP `top_k` is people-grain after collapse (see PHP passthrough below).

200 body is PROV-06 typed:

```json
{
  "model_id": "opencv-sface+cv5@128d/l2/cosine",
  "embedding_model": "opencv-sface+cv5@128d/l2/cosine",
  "computed_at": "2026-08-18T12:00:00+00:00",
  "probe_face_count": 1,
  "reference_face_count": 3,
  "quality_flag": "ok",
  "thresholds": {
    "suggestion_floor": 0.35,
    "suggestion_ceiling": 0.55,
    "similarity_threshold": 0.55
  },
  "candidates": [
    {
      "cluster_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      "name": "Ada",
      "similarity": 0.81,
      "band": "strong"
    }
  ]
}
```

- `quality_flag` is probe-level; no per-candidate `quality_flag`. Low quality caps band at `possible`.
- Three empties: no usable probe (`probe_face_count` 0 / `reference_face_count` 0 / `low_quality`); empty labelled roster (`probe_face_count` > 0 / `reference_face_count` 0 / `ok` / `candidates` []); low-quality probe (bands capped).
- PHP fetches Python max window 50, collapses max-similarity, re-sorts, slices people-grain `top_k`.
~~~~

Delete the second `### GET /recognition/clusters/{cluster_id}/roster-candidates` heading later in the same file.

## Canon

| ID | file:line | how |
|---|---|---|
| REF-25 | lexicons/engineering.md:344 | R1-06 / R1-14 left open; closed this round |
| DIAG-01 | lexicons/engineering.md:446 | REPORT cites observed RED/GREEN lines, not memory |
| TEST-15 | lexicons/engineering.md:396 | mutants in closure table |
| TEST-06 | lexicons/engineering.md:387 | each new test observed failing first |
| TEST-13 | lexicons/engineering.md:394 | repo test uses `AsyncMock` + real `SqlAlchemyClusterRepository` |
| HAI-16 | lexicons/interaction-ux.md:225 | people-grain `top_k` after collapse |
| NAME-02 | lexicons/engineering.md:649 | triple slots `representative_quality` / `identity_quality` / `detection_confidence` |
| REF-26 | lexicons/engineering.md:345 | one roster-candidates section + schema + code |
| PERC-04 | lexicons/interaction-ux.md:94 | three empties distinguished |
| CAL-02 | lexicons/ml-systems.md:322 | empty roster is 200 + `ok`; no-probe is `low_quality` |
| A11Y-17 | lexicons/accessibility.md:128 | `invalid_top_k` names field + fix |
| FORM-05 | lexicons/interaction-ux.md:189 | validate_callback carries the same message |
| API-05 | lexicons/engineering.md:506 | machine-actionable `invalid_top_k` |

## Decisions

- PHP `top_k` is people-grain: always fetch Python max (50), collapse max-sim (keep winner band+name), re-sort, slice.
- Member-fallback quality SELECT: `NULL` representative_quality, `MediaIdentity.quality_score`, `MediaIdentity.confidence` (no second `quality_score`).
- Fake `get_by_id` returns the probe (fused_low visible); quality still from ranking-row loaders.

## Undone

- FE `PersonCommitControl` (out of lane)
- FIR-6 S4 calibrated knobs
- EMB-11 spatial occlusion
- Pre-existing PY fail: missing sface onnx in this checkout

## HEAD

`HEAD` after this commit. Follow-up pins the 40-char SHA.
