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

## Re-review r3c (0a19a3eed..106d5b743)

VERIFIED: {"GPUFLOW-2-SVCMERGECANDIDATES-R-02":"partially_fixed","GPUFLOW-2-SVCMERGECANDIDATES-R-03":"fixed","GPUFLOW-2-SVCMERGECANDIDATES-R2-04":"fixed","GPUFLOW-2-SVCMERGECANDIDATES-R2-06":"not_fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-2-SVCMERGECANDIDATES-R-02 | partially_fixed | The delta carries `refreshed_at` and representative identity ids through `MergeSuggestionDetails` and `_to_details()` (`suggestion_details.py:53-67`; `merge_suggestion_repository.py:227-242`), then checks live counts and representative ids (`merge_candidates.py:207-241`). `_latest_mutation()` still reads only `created_at` plus `getattr(cluster, "updated_at", None)` (`merge_candidates.py:243-251`); the delta does not add or map `updated_at` on `IdentityCluster`, so same-count membership or centroid changes with an unchanged representative can still admit stale pending evidence. |
| GPUFLOW-2-SVCMERGECANDIDATES-R-03 | fixed | The endpoint no longer applies a lower clamp: `display_similarity = min(1.0, float(similarity))` (`merge_candidates.py:143-155`). The new regression test expects `[-0.2, -1.0]` and the `none` band (`test_merge_candidates.py:453-469`), so valid negative cosine values are now returned and ordered distinctly. |
| GPUFLOW-2-SVCMERGECANDIDATES-R2-04 | fixed | `_rank_candidates()` now uses the returned merged score as its primary key (`-row.candidate.similarity`) before raw cosine (`merge_candidates.py:116-123`), and the added test places a fresh pending `0.91` candidate ahead of a raw `0.80` candidate (`test_merge_candidates.py:208-251`). |
| GPUFLOW-2-SVCMERGECANDIDATES-R2-06 | not_fixed | The supplied brief gives this identifier with no finding text or acceptance criterion. The fix delta therefore contains no evidence that can establish a behavioral change for this unspecified item; treating it as fixed would fabricate an acceptance claim ([AGT-02]). |

### FINDINGS

FINDINGS: [{"id":"GPUFLOW-2-SVCMERGECANDIDATES-R-07","severity":"medium","file_path":"apps/prototype-description-service/recognition/application/suggestions/merge_candidates.py","line":116,"summary":"Equal returned scores are tie-broken by raw cosine and cluster ID before the required name ordering.","evidence":"The sort key is (-row.candidate.similarity, -row.raw_similarity, row.candidate.cluster_id) at lines 116-123, while B6 requires name ASC within a band. The changed test at lines 182-199 is renamed to cluster_id ordering and asserts UUID order, codifying the contract regression ([API-09])."},{"id":"GPUFLOW-2-SVCMERGECANDIDATES-R-08","severity":"low","file_path":"apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py","line":406,"summary":"The post-mutation freshness test does not model a cluster mutation timestamp.","evidence":"The test declares mutation at lines 409-410 and puts refreshed_at after it at lines 438-442, but the _cluster fixture only adds representative_identity_id and never accepts or assigns updated_at at lines 27-49. The assertion therefore proves only that a newer refreshed suggestion is accepted; it cannot prove the intended cluster-mutation freshness behavior ([TEST-03])."}]

#### GPUFLOW-2-SVCMERGECANDIDATES-R-07 — medium

- **File:line:** `apps/prototype-description-service/recognition/application/suggestions/merge_candidates.py:116-123`; `apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py:182-199`.
- **Evidence:** The fix sorts equal returned scores by raw cosine, then cluster ID, before considering name. B6 requires similarity descending with name ASC within a band. The changed test is explicitly renamed to `test_ranks_similarity_desc_then_cluster_id_asc` and asserts UUID order, making the wrong tie-break executable ([API-09]).
- **Impact:** Two candidates with the same displayed similarity and band can appear in non-name order, changing the operator-visible result order and violating the merge-candidate response contract.
- **Fix:** Keep merged similarity as the primary key, then sort by `name.casefold()` (and use cluster ID only as the final deterministic tie-break); do not place raw cosine ahead of name for equal returned scores.

#### GPUFLOW-2-SVCMERGECANDIDATES-R-08 — low

- **File:line:** `apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py:27-49,406-450`.
- **Evidence:** The test creates `mutation` and sets `refreshed_at` after it, but the `_cluster` helper has no `updated_at` parameter or assignment. It therefore verifies only that a refreshed suggestion newer than `created_at` is accepted; it does not exercise the cluster mutation timestamp that `_latest_mutation()` claims to use ([TEST-03]).
- **Impact:** The regression suite can stay green while the intended stale-after-mutation gate is absent or wired to a field that production clusters do not expose.
- **Fix:** Populate a real `updated_at`/centroid-refresh timestamp in the fixture, assert an older pending observation is rejected, and separately assert a refresh after that timestamp is accepted.

Verdict: pass_with_findings

## Re-review r5b (10a3ec875..c9ce1ef83)

VERIFIED: {"GPUFLOW-2-SVCMERGECANDIDATES-R-02":"partially_fixed","GPUFLOW-2-SVCMERGECANDIDATES-R-07":"fixed","GPUFLOW-2-SVCMERGECANDIDATES-R2-05":"not_fixed","SVCMER-ee943e85afad694a-H-f0701f57bc4831012d5c19cc":"partially_fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-2-SVCMERGECANDIDATES-R-02 | partially_fixed | The delta adds `IdentityCluster.updated_at` (`domain/cluster.py:76-78`), compares it with `created_at` in `_latest_mutation()` (`merge_candidates.py:243-250`), and maps `ClusterModel.updated_at` into the domain (`cluster_repository.py:1581-1599`). It does not map the materialized centroid's `refreshed_at`, and the production member-repository write paths remain unstamped, so same-count membership or centroid changes can still admit stale pending evidence. |
| GPUFLOW-2-SVCMERGECANDIDATES-R-07 | fixed | The ranking key is now returned similarity, case-folded candidate name, then cluster id (`merge_candidates.py:117-122`), and the replacement test asserts `Best`, `Ada`, `Zed` order (`test_merge_candidates.py:184-201`). |
| GPUFLOW-2-SVCMERGECANDIDATES-R2-05 | not_fixed | The supplied brief gives this identifier without a finding statement or acceptance criterion. No hunk in the fix delta can establish a behavioral change for it, so claiming fixed would fabricate evidence. |
| SVCMER-ee943e85afad694a-H-f0701f57bc4831012d5c19cc | partially_fixed | The delta now carries a cluster `updated_at` through the domain and repository conversion (`domain/cluster.py:76-78`; `cluster_repository.py:1436-1443,1581-1599`), but the conversion still discards `centroid_data.refreshed_at` and membership writes in `member_repository.py` do not update the cluster timestamp. The repository-to-domain freshness contract therefore remains incomplete. |

### FINDINGS

FINDINGS: [{"id":"GPUFLOW-2-SVCMERGECANDIDATES-R-09","severity":"high","file_path":"apps/prototype-description-service/recognition/infrastructure/repositories/member_repository.py","line":61,"summary":"The new cluster freshness timestamp is not updated on the production membership repository path.","evidence":"The delta calls `_touch_cluster_updated_at()` from `cluster_repository.py:1388` and representative paths `1409-1433`, while `_to_domain()` consumes only `ClusterModel.updated_at` at `1581-1599`. The production `SqlAlchemyMemberRepository` used by assignment and merge writes membership through `add_member`, `add_member_if_not_exists`, both bulk-add variants, `move_members`, `remove_member`, and `remove_by_identity_id` (`member_repository.py:61-313`); none calls that helper. A same-count member replacement can therefore pass `_latest_mutation()` (`merge_candidates.py:243-250`) and still blend stale pending similarity."},{"id":"GPUFLOW-2-SVCMERGECANDIDATES-R-10","severity":"medium","file_path":"apps/prototype-description-service/recognition/domain/cluster.py","line":76,"summary":"The fix delta edits shared domain and persistence files outside the svc-merge-candidates lane plan.","evidence":"The lane plan names the merge-candidates router, `application/suggestions/merge_candidates.py`, and its unit test, but the delta additionally changes `domain/cluster.py:76-78` and `infrastructure/repositories/cluster_repository.py:1388-1443,1581-1599`. Those shared paths alter repository snapshot/version semantics and require ownership/routing review beyond the declared lane fence."},{"id":"GPUFLOW-2-SVCMERGECANDIDATES-R-11","severity":"low","file_path":"apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py","line":291,"summary":"Freshness tests cover only in-memory fixtures and do not prove persistence or centroid-refresh propagation.","evidence":"The new tests set `updated_at` directly on `_cluster()` (`test_merge_candidates.py:31-54,291-322,407-451`) and exercise fake repositories; the delta adds no repository test that verifies membership writes stamp `ClusterModel.updated_at` or that `centroid_data.refreshed_at` reaches `IdentityCluster`. The suite can therefore pass while the production freshness sources remain disconnected."}]

#### GPUFLOW-2-SVCMERGECANDIDATES-R-09 — high

- **File:line:** `apps/prototype-description-service/recognition/infrastructure/repositories/member_repository.py:61-313`; freshness consumer `recognition/application/suggestions/merge_candidates.py:243-250`.
- **Evidence:** The delta wires `_touch_cluster_updated_at()` into `cluster_repository.py:1388` and representative CRUD, but production assignment and merge use `SqlAlchemyMemberRepository` for all add, bulk-add, move, and removal operations. Those methods do not touch the cluster row, while `_to_domain()` reads only `ClusterModel.updated_at`.
- **Impact:** A same-count membership replacement or move can leave the freshness timestamp unchanged, allowing an old high pending score to be blended into the live merge-candidate response.
- **Fix:** Stamp every successful membership mutation (including bulk and move paths), or expose and compare the authoritative member/centroid refresh timestamp instead.

#### GPUFLOW-2-SVCMERGECANDIDATES-R-10 — medium

- **File:line:** `apps/prototype-description-service/recognition/domain/cluster.py:76-78`; `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py:1388-1443,1581-1599`.
- **Evidence:** The B6 lane row declares the router, merge-candidates application module, and unit test as its changed paths. The fix delta also changes the shared domain model and cluster repository, which are outside that declared ownership list and affect snapshot/version behavior.
- **Impact:** The fix cannot be reviewed or merged under the stated lane fence without a shared-path ownership decision, and uncoordinated changes can conflict with the owning repository lane.
- **Fix:** Route the shared model/repository changes through their owner or update the lane plan and add cross-lane integration proof.

#### GPUFLOW-2-SVCMERGECANDIDATES-R-11 — low

- **File:line:** `apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py:31-54,291-322,407-451`.
- **Evidence:** The added tests inject `updated_at` directly into in-memory `_cluster()` fixtures and use fake repositories. No test exercises the actual member repository writes or the materialized centroid refresh field that production conversion omits.
- **Impact:** The targeted unit suite can stay green while the persistence wiring required for stale-evidence protection is absent.
- **Fix:** Add repository-level coverage for each membership mutation path and a conversion test asserting centroid refresh timestamps reach the domain freshness check.

Verdict: fail
