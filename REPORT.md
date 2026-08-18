# UXW2-5-PY report

## Result
`GET /recognition/clusters/{id}/roster-candidates` ranks labelled clusters (python person stand-in) by max-cosine, same `embedding_model` only. Bands from live settings. PHP passthrough maps `cluster_id` → `roster_entry_id`. No raw-% UI contract.

## RED
- PY collect: `ModuleNotFoundError: recognition.application.suggestions.roster_candidates`
- PHP: `Call to undefined method SuggestionsController::get_roster_candidates()`; route list size 0≠1

## GREEN
- PY: `9 passed` (`test_roster_candidates` unit+api). Sibling: `53 passed` (roster + label_inference FIR23 + api suggestions + similarity_search)
- PHP: `composer test` **1767 tests, 8533 assertions, OK**
- TEST-15: `band_for` `>=` → `>` made `0.70` POSSIBLE not STRONG. PHP mapping forced `null` → assert 42 failed. Both restored.

## Files
**Commit 1** `f435918` feat(recognition): UXW2-5 GET /recognition/clusters/{cluster_id}/roster-candidates
- `recognition/application/suggestions/roster_candidates.py`
- `recognition/interface_adapters/http/routers/suggestions.py`
- `recognition/interface_adapters/http/schemas/responses.py`
- `recognition/tests/{unit,api}/test_roster_candidates.py`
- `recognition/tests/fakes.py`
- `packages/shared-contracts/schemas/roster-candidates-response.schema.json`
- (local only, gitignored) `docs/workbay/contracts/recognition-clustering.md`

**Commit 2** `c1251f9` feat(api): UXW2-5 PHP passthrough acx/v1/recognition/clusters/{id}/roster-candidates
- `src/api/class-suggestions-controller.php`
- `tests/Unit/SuggestionsControllerTest.php`

## Canon
| ID | file:line | how |
|---|---|---|
| PROV-06 | lexicons/ml-systems.md:423 | `model_id`, `embedding_model`, `computed_at`, `thresholds` |
| DRIFT-03 | lexicons/ml-systems.md:352 | bands from `resolve_effective_clustering_settings` |
| CAL-01 | lexicons/ml-systems.md:321 | quality flag from `fatal_quality_floor`; no per-stratum FAR yet |
| CAL-02 | lexicons/ml-systems.md:322 | empty roster → `candidates: []` 200; `band=none` |
| CAL-03 | lexicons/ml-systems.md:323 | cosine not published as frequency |
| EMB-01 | lexicons/ml-systems.md:167 | FIR23-01 same-model guard |
| EMB-02 | lexicons/ml-systems.md:168 | max over reps, not raw mean (partial) |
| EMB-09 | lexicons/ml-systems.md:175 | quality gates flag; score not uncertainty-penalized |
| EMB-11 | lexicons/ml-systems.md:177 | `occluded` reserved; not fabricated |
| HAI-08 | lexicons/interaction-ux.md:217 | band is the decision grain |
| HAI-05 | lexicons/interaction-ux.md:214 | payload typed for disclosure (FE lane) |
| MEAS-05 | lexicons/epistemics.md:206 | no % arithmetic |
| API-01 | lexicons/engineering.md:502 | `top_k` default 10, max 50, reject not clamp |
| TEST-15 | lexicons/engineering.md:396 | mutations above |
| rg-015 | docs/workbay/constitution.md:48 | PHP does not invent `total`/`limit` |

## Decisions
- Python has no person table → key by labelled `cluster_id` + `name`; PHP maps via `acx_clusters.person_id`.
- `similarity` stays on the wire (rank + tests); contract forbids new raw-% UI.
- Profile knobs via `resolve_effective_clustering_settings` (insightface → clustering floor/ceiling).

## Undone
- FE `PersonCommitControl` (out of lane)
- FIR-6 S4 calibrated knobs
- EMB-11 spatial occlusion; EMB-09 score penalty
- `docs/workbay/contracts/` is gitignored — schema is the tracked contract

## HEAD
`284ebdd9967ab24e3597317397deeb1400117293` (report). Code: `f435918` python, `c1251f9` php.
