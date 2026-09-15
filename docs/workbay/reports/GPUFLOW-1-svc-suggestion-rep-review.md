# GPUFLOW-1 svc-suggestion-rep review

Verdict: pass_with_findings

FINDINGS: [{"id":"GPUFLOW-1-SVCSUGGESTIONREP-R-01","severity":"medium","file_path":"apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py","line":202,"summary":"Per-row representative lookup creates an N+1 query fan-out","evidence":"list_pending_with_details iterates every returned suggestion at lines 336-338, while _to_details executes a new SELECT at lines 202-216; the prior eager load fetched the representative with the page query.","impact":"A page of N suggestions now performs one representative query per card, increasing review-endpoint latency and database load for the SPA consumer.","fix":"Batch-load tenant-scoped members for all returned cluster/candidate pairs, or eager-load the filtered member identities and select the primary/quality winner in memory."},{"id":"GPUFLOW-1-SVCSUGGESTIONREP-R-02","severity":"low","file_path":"apps/prototype-description-service/recognition/tests/integration/test_suggestion_repository.py","line":51,"summary":"The candidate-is-member fixture reports an inconsistent cluster identity count","evidence":"The case at fixture line 2 sets candidate_is_member=true, so lines 56-65 create membership rows for every identity, but line 51 always stores identity_count=len(identities)-1.","impact":"The test exercises representative selection with a count that disagrees with the target membership rows and never asserts cluster_identity_count, weakening downstream card-count coverage.","fix":"Set identity_count to the number of inserted members and assert detail.cluster_identity_count for the candidate-is-member case."}]

## Scope

| Field | Value |
| --- | --- |
| Base | `eff8e6025` |
| Tip | `00afd2c19` |
| Files | `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py`; `apps/prototype-description-service/recognition/tests/fixtures/gpuflow-suggestion-representatives.json`; `apps/prototype-description-service/recognition/tests/integration/test_suggestion_repository.py` |

The changed paths are all within the svc-suggestion-rep owned-path list. The repository delta supplies null representative fields for the downstream SPA placeholder and preserves the API’s existing optional representative fields; the SPA rendering and vitest proof remain outside this lane’s delta.

## FINDINGS

### GPUFLOW-1-SVCSUGGESTIONREP-R-01 — medium

File: `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py:202`

Evidence: `list_pending_with_details` loops over the page at lines 336-338 and calls `_to_details`; the new `_to_details` issues a separate member/identity `SELECT` at lines 202-216 for every row. The old path eager-loaded the representative from the page query. This is the per-item I/O pattern covered by [RES-12].

Impact: A page of N suggestions now performs N additional database round trips. The SPA review queue and any min-confidence page collection will pay the fan-out in request latency and database connection/query load.

Fix: Fetch all tenant-scoped member identities for the returned `(cluster_id, candidate_id)` pairs in one query, then choose the valid primary or quality-ranked alternative in memory; alternatively use a filtered eager-load strategy that retains the same tenant and candidate exclusions.

### GPUFLOW-1-SVCSUGGESTIONREP-R-02 — low

File: `apps/prototype-description-service/recognition/tests/integration/test_suggestion_repository.py:51`

Evidence: The `pending-candidate-is-member` fixture sets `candidate_is_member: true` at fixture line 2. The test therefore inserts `identities[0:]` into `identity_members` at lines 56-65, but always sets `identity_count=len(identities)-1` at line 51. It asserts representative fields but never checks `detail.cluster_identity_count`.

Impact: The case models a cluster whose stored count disagrees with its membership rows, so it does not prove the downstream card count for the stale-candidate scenario and can hide a count regression.

Fix: Derive `identity_count` from the inserted member slice and assert the returned `cluster_identity_count` for both candidate-member and candidate-not-member cases. [TEST-15]

## Verification

- `scripts/tests/test_composer_lock_tracked.py`: passed (`1 passed`).
- The lane integration command was started with the lane-root `.venv` but produced no output for roughly two minutes during collection/fixture setup and was interrupted; no pass/fail result is claimed for that suite.
