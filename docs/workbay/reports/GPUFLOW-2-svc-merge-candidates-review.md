VERIFIED: {"GPUFLOW-2-SVCMERGECANDIDATES-R-01":"fixed","GPUFLOW-2-SVCMERGECANDIDATES-R-02":"partially_fixed","GPUFLOW-2-SVCMERGECANDIDATES-R-03":"partially_fixed"}
FINDINGS: [{"id":"GPUFLOW-2-SVCMERGECANDIDATES-R-04","severity":"medium","file_path":"apps/prototype-description-service/recognition/application/suggestions/merge_candidates.py","line":116,"summary":"The merged pending score is ignored by the final ranking order.","evidence":"The fix raises similarity to max(raw_similarity, pending_similarity) at lines 142-147, but ranked.sort() keys only on -row.raw_similarity at lines 116-123. A candidate with raw cosine 0.10 and fresh pending score 0.91 can therefore appear below a candidate with raw cosine 0.80 while displaying the lower score first."},{"id":"GPUFLOW-2-SVCMERGECANDIDATES-R-05","severity":"medium","file_path":"apps/prototype-description-service/recognition/application/suggestions/merge_candidates.py","line":100,"summary":"The fix keeps a second ranking implementation instead of reusing the roster ranking path required by B6.","evidence":"The delta retains _rank_candidates() and adds _raw_cosine_similarity() (lines 100-123 and 281-291); it does not call list_roster_candidates() or SimilaritySearch. The two paths can diverge in representative selection, thresholds, and score semantics, and this fix already introduces raw-centroid ordering separately from the roster path."},{"id":"GPUFLOW-2-SVCMERGECANDIDATES-R-06","severity":"low","file_path":"apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py","line":310,"summary":"The negative-cosine regression test accepts non-discriminating display scores instead of proving the contract value.","evidence":"The new test asserts both negative candidates return similarity [0.0, 0.0] at lines 310-312. It proves raw ordering only; it does not fail when the API still clamps valid negative cosine values, so the test encodes the remaining display-contract gap."}]
Verdict: pass_with_findings

# GPUFLOW-2 svc-merge-candidates review

The review is limited to the supplied fix delta `d55cc2fa5..0a19a3eed` for the `svc-merge-candidates` B6 slice. The aggregate router mount is owned by `svc-route-registry` and is not reassigned here.

## Re-review r2 (d55cc2fa5..0a19a3eed)

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-2-SVCMERGECANDIDATES-R-01 | fixed | The delta removes the `clustering_settings` import and the `SUGGESTION_BAND_CUTS` fallback with literal provisional thresholds. `band_for(display_similarity, settings)` remains the only band decision in the changed implementation (`merge_candidates.py:142-155`), and the added test verifies the shim symbols are absent (`test_merge_candidates.py:128-130`). |
| GPUFLOW-2-SVCMERGECANDIDATES-R-02 | partially_fixed | The delta adds `_membership_matches_live()` and rejects pending rows whose two stored identity counts do not equal the live counts (`merge_candidates.py:174-177,204-232`); the new stale-membership test exercises that rejection (`test_merge_candidates.py:257-288`). It still treats freshness as `max(probe.created_at, other.created_at)` (`merge_candidates.py:199-201,235-237`), while `_suggestion_observed_at()` can only see `refreshed_at` through `getattr` and `MergeSuggestionDetails`/`_to_details()` do not carry it (`merge_candidates.py:240-243`; `suggestion_details.py:45-61`; `merge_suggestion_repository.py:222-243`). Same-count membership or representative/centroid mutations can therefore still admit stale evidence. |
| GPUFLOW-2-SVCMERGECANDIDATES-R-03 | partially_fixed | The fix computes an unclamped raw cosine and sorts negative candidates by that value (`merge_candidates.py:116-123,142,281-291`), closing the original all-zero ordering tie; the added test proves `less_negative` precedes `more_negative` (`test_merge_candidates.py:292-312`). However, `display_similarity` still clamps every negative merged score to `0.0` (`merge_candidates.py:143-154`), and the test explicitly accepts `[0.0, 0.0]`, so the contract-visible score remains non-discriminating. |

### FINDINGS

#### GPUFLOW-2-SVCMERGECANDIDATES-R-04 — medium

- **File:line:** `apps/prototype-description-service/recognition/application/suggestions/merge_candidates.py:116-123,142-150`.
- **Evidence:** `_score_candidate()` computes the merged score with `max(raw_similarity, pending_similarity)`, but `_rank_candidates()` sorts on `raw_similarity` alone. The fix therefore ranks by a different value than it returns. A fresh pending score can be higher than the centroid score while its candidate remains below a candidate with a lower returned score.
- **Impact:** The endpoint can present a lower-scored candidate ahead of the best merged candidate, defeating the ranked merge-candidate contract and downstream operator ordering.
- **Fix:** Store the merged score as the primary ranking key while preserving the unclamped raw cosine as a deterministic secondary key for none-band ties, or route the merged score through the shared ranking implementation.

#### GPUFLOW-2-SVCMERGECANDIDATES-R-05 — medium

- **File:line:** `apps/prototype-description-service/recognition/application/suggestions/merge_candidates.py:100-123,281-291`.
- **Evidence:** The fix retains a private `_rank_candidates()` loop and adds a private `_raw_cosine_similarity()` implementation. It does not reuse the mandated `list_roster_candidates()`/`SimilaritySearch` ranking path. The duplicated path has independent representative/centroid selection, score handling, and ordering rules; the raw-centroid sort versus merged pending score is already a concrete divergence.
- **Impact:** B6 consumers can receive ranking semantics different from the existing roster surface, and future changes to the accepted ranking path can silently leave merge candidates inconsistent.
- **Fix:** Extract or call one shared ranking primitive that accepts the pending-evidence merge policy, then use it from both surfaces rather than maintaining a second ranker.

#### GPUFLOW-2-SVCMERGECANDIDATES-R-06 — low

- **File:line:** `apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py:292-312`.
- **Evidence:** The new negative-cosine test asserts `[0.0, 0.0]` for the two returned similarities. It proves only that raw ordering differs; it would stay green if valid negative values were silently clamped, so it does not protect the response contract or the user-visible match score.
- **Impact:** The regression suite can report the negative-cosine fix as complete while preserving a non-discriminating score payload.
- **Fix:** Assert the returned negative cosine values (and the none band) or explicitly amend the contract to prohibit negative output before accepting the clamp.

Verdict: pass_with_findings

## Verification

- `.venv/bin/python -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` — 1 passed.
- `.venv/bin/python -m pytest apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py -q -p no:cacheprovider` — 15 passed.
- Import-origin control was skipped because this lane owns only the report artifact, not an importable Python package.
