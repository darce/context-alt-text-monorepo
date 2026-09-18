FINDINGS: [{"id":"GPUFLOW-2-CONTRACTSROSTER-R-01","severity":"high","file_path":"packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json","line":119,"summary":"The new sharpness contract rejects valid persisted quality components.","evidence":"Both changed schemas cap quality_components.sharpness at 1, but compute_sharpness returns raw variance-of-Laplacian values and the existing round-trip tests persist 42.5 and 77.0; a Draft7 validation of 42.5 fails with greater-than-maximum-of-1."},{"id":"GPUFLOW-2-CONTRACTSROSTER-R-02","severity":"medium","file_path":"packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json","line":96,"summary":"Representative quality and its components are independently optional.","evidence":"The snapshot and roster schemas permit representative_quality without quality_components (and vice versa), while the identity-merge contract and task specification require the composite to ship with all four parts."},{"id":"GPUFLOW-2-CONTRACTSROSTER-R-03","severity":"high","file_path":"docs/workbay/contracts/identity-merge.md","line":88,"summary":"Receipt revert lacks path, tenant, and current-membership ownership guards.","evidence":"The documented receipt shape has no explicit tenant binding; revert_merge accepts only receipt_id; the {id} route is not required to equal receipt.survivor_cluster_id; and the move algorithm has no precondition that every moved identity is still in the survivor cluster."},{"id":"GPUFLOW-2-CONTRACTSROSTER-R-04","severity":"high","file_path":"docs/workbay/contracts/identity-merge.md","line":19,"summary":"The existing arbitrary-identity revert endpoint is left as an unbounded second recognition undo surface.","evidence":"The new contract makes the receipt id the workbench undo handle, but curation-sync-api.md still dispatches revert_merge_cluster to /recognition/clusters/revert-merge with source/target identifiers, and the existing route accepts moved_identity_ids and source_label without a receipt or LIFO/expiry check."},{"id":"GPUFLOW-2-CONTRACTSROSTER-R-05","severity":"medium","file_path":"docs/workbay/contracts/identity-merge.md","line":38,"summary":"The stored source cluster identity is not tied to restoration semantics.","evidence":"Receipts persist source_cluster_id, but revert only promises a cluster with source_label or a generated restored label; it does not say whether the deleted source UUID is reused, how an occupied UUID is handled, or which restored id is returned."},{"id":"GPUFLOW-2-CONTRACTSROSTER-R-06","severity":"medium","file_path":"packages/shared-contracts/schemas/recognition-cluster-merge-candidates-response.schema.json","line":5,"summary":"The service candidate score has no defined merge operator for centroid and pending-suggestion values.","evidence":"The response exposes one similarity while describing it only as centroid cosine merged with pending ClusterMergeSuggestion similarity; no precedence, max/average rule, freshness/status filter, pair canonicalization, or post-merge band rule is specified."},{"id":"GPUFLOW-2-CONTRACTSROSTER-R-07","severity":"medium","file_path":"packages/shared-contracts/schemas/roster-merge-candidates-response.schema.json","line":5,"summary":"Person aggregation does not prohibit returning the loser as its own survivor candidate.","evidence":"The per-cluster calls exclude the probe cluster, not the probe person; a loser bound to multiple clusters can therefore map another candidate cluster back to the same person_id, and the schema accepts candidate person_id equal to the response person_id even though the person-merge contract requires distinct ids."},{"id":"GPUFLOW-2-CONTRACTSROSTER-R-08","severity":"medium","file_path":"docs/workbay/contracts/identity-merge.md","line":180,"summary":"operator_initial_choice is not declared required or tenant-validated on commit.","evidence":"The two-step text requires a step-1 pick, but the commit table only lists the field and says it is stored; it does not require a positive existing same-tenant person, reject the loser/self case, or define the missing-field error."},{"id":"GPUFLOW-2-CONTRACTSROSTER-R-09","severity":"low","file_path":"packages/shared-contracts/schemas/recognition-cluster-merge-candidates-response.schema.json","line":1,"summary":"The new contract schemas are not covered by the repository schema-document test registry.","evidence":"scene/tests/test_shared_schema_documents.py registers only image-description-response, scene-describe-multipart, and scene-describe-run, while the required composer-lock test checks only composer.lock; the delta adds no tests or fixtures for these four schemas and their examples."}]
Verdict: fail

# GPUFLOW-2 contracts-roster review

| base | tip | files |
| --- | --- | --- |
| `d980d817f` | `5f05f3df9` | `docs/workbay/contracts/identity-merge.md`; `packages/shared-contracts/schemas/recognition-cluster-merge-candidates-response.schema.json`; `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json`; `packages/shared-contracts/schemas/roster-entry.schema.json`; `packages/shared-contracts/schemas/roster-merge-candidates-response.schema.json` |

## FINDINGS

### GPUFLOW-2-CONTRACTSROSTER-R-01 — high

File: `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json:119-123`; `packages/shared-contracts/schemas/roster-entry.schema.json:141-145`.

Evidence: Both changed schemas cap `quality_components.sharpness` at `1`. The producer computes sharpness as raw variance of the Laplacian (`apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py:47-61`), and the existing persistence round-trip uses `42.5` and `77.0` (`apps/prototype-description-service/recognition/tests/integration/test_factor_round_trip.py:25-27,97-99,169-197`). The changed snapshot schema rejects a representative component with `sharpness: 42.5` (`42.5 is greater than the maximum of 1`).

Impact: A valid stored component cannot cross the B2 service → snapshot → projection contract. Export validation or a strict downstream consumer will fail, or a producer will have to silently drop/alter the raw signal.

Fix: Remove the upper bound from `sharpness` in both schemas and document raw variance units, or introduce and test an explicit producer normalization before this wire contract. Do not imply a `[0,1]` ceiling without evidence.

### GPUFLOW-2-CONTRACTSROSTER-R-02 — medium

File: `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json:96-106`; `packages/shared-contracts/schemas/roster-entry.schema.json:120-130`.

Evidence: `representative_quality` and `quality_components` are separate optional properties. A cluster containing only `representative_quality` validates, even though `identity-merge.md:145-166` and the slice specification require the composite to ship with its four parts; the same one-sided omission is possible in the roster shape.

Impact: A downstream UI or generated client can receive a quality scalar with no provenance components (or components without a scalar), weakening UXR-15 and making it impossible to distinguish a complete quality record from a partial one.

Fix: Encode an all-or-neither relationship for the pair while preserving legacy payloads that omit both fields. Add positive and one-sided omission-negative fixtures for both schemas.

### GPUFLOW-2-CONTRACTSROSTER-R-03 — high

File: `docs/workbay/contracts/identity-merge.md:38-47,88-101,125-138`.

Evidence: The documented receipt shape has no explicit tenant binding; `revert_merge` accepts only `receipt_id`; the `{id}` route is not required to equal `receipt.survivor_cluster_id`; and the move algorithm has no precondition that every `moved_identity_ids` member is still in the survivor cluster. Existing merge code checks both cluster tenants before moving (`apps/prototype-description-service/recognition/application/orchestration/cluster_merge.py:308-314`), and the existing revert path checks each identity's current cluster (`apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters_topology.py:718-727`).

Impact: A wrong-cluster or cross-tenant receipt lookup can mutate the wrong topology, and a stale receipt can steal identities reassigned after the merge. Either path can cause silent membership loss and violates the exact-prior-partition/LIFO safety boundary.

Fix: Scope receipt lookup to the authenticated tenant and path survivor id (or explicitly join tenant-owned clusters), lock the receipt/members, and require every moved identity to remain in the survivor before any write. Return a documented `409` conflict problem without partial mutation when an ownership or membership precondition fails.

### GPUFLOW-2-CONTRACTSROSTER-R-04 — high

File: `docs/workbay/contracts/identity-merge.md:19-26,125-138,163-164`.

Evidence: The new contract makes `undoable_merge_receipt_id` the workbench undo handle and introduces receipt-based endpoints, but the existing `docs/workbay/contracts/curation-sync-api.md:222-230` still dispatches `revert_merge_cluster` to `/recognition/clusters/revert-merge` with source/target identifiers. The existing recognition route accepts arbitrary `moved_identity_ids` and `source_label` (`apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters_topology.py:697-737`) without a receipt, LIFO, or expiry check.

Impact: Unless explicitly retired, deployment exposes a second recognition undo path that bypasses the C3 receipt controls. Legacy replay or another caller can mutate cluster membership outside the receipt stack, defeating expiry and non-top refusal semantics.

Fix: Migrate the dispatcher, existing WP controller, security table, and callers to the receipt route and retire the arbitrary-ID endpoint, or document it as a separately authorized legacy operation with an explicit compatibility boundary and equivalent receipt/state guards. Add a route-level test proving the old path cannot bypass C3.

### GPUFLOW-2-CONTRACTSROSTER-R-05 — medium

File: `docs/workbay/contracts/identity-merge.md:38-41,93-100`.

Evidence: Receipts persist `source_cluster_id`, but revert only promises restoration to a cluster carrying `source_label` or a generated `"<name> (restored)"` label. It does not say whether the deleted source UUID is reused, how an occupied UUID is handled, or which restored cluster id is returned. The normal merge deletes the source cluster at the end (`apps/prototype-description-service/recognition/application/orchestration/cluster_merge.py:421-435`).

Impact: Implementations can produce a new cluster identity for an undo that is supposed to restore the prior topology. WP projections, deep links, pending candidates, and subsequent recovery runs can then retain or create stale references even when membership happens to be restored.

Fix: Specify deterministic source-id reuse with same-tenant/collision failure semantics, or explicitly choose a new id and define the response, projection reconciliation, and recovery exclusion behavior. Test the source-present, source-deleted, and id-collision cases.

### GPUFLOW-2-CONTRACTSROSTER-R-06 — medium

File: `packages/shared-contracts/schemas/recognition-cluster-merge-candidates-response.schema.json:5,15-39`; `docs/workbay/contracts/identity-merge.md:140-141`.

Evidence: The response exposes one `similarity` while describing it only as centroid cosine “merged with” pending `ClusterMergeSuggestion` similarity. No precedence or operator (maximum, average, pending override), freshness/status filter, pair canonicalization, or rule for applying the band after the merge is defined.

Impact: `svc-merge-candidates` implementations can emit different scores, bands, and order for the same pair. PHP aggregation and SPA labels then cease to be reproducible, and a policy band can be cut from a value different from the one the service intended.

Fix: Define one canonical pair merge operator and its inputs (tenant, pending status/expiry, embedding-space validity), compute the band from the resulting score, and specify deterministic ties. Cover centroid-only, pending-only, and conflicting-score fixtures.

### GPUFLOW-2-CONTRACTSROSTER-R-07 — medium

File: `packages/shared-contracts/schemas/roster-merge-candidates-response.schema.json:5,17-26`.

Evidence: The person algorithm makes one service call per loser-bound cluster and maps candidate clusters back to persons. The per-cluster ranking excludes the probe cluster, not all clusters bound to the probe person, so a loser with multiple bindings can map a candidate cluster back to the loser itself. The new schema accepts equal root and candidate `person_id`; the existing person-merge contract requires the two ids to differ (`docs/workbay/contracts/clustering-api.md:846-854`).

Impact: The UI can offer a person as its own survivor, producing an invalid merge request or exposing a self-merge path to downstream mutation code.

Fix: Drop candidates whose mapped `person_id` equals the response `person_id` before aggregation, and add a multi-cluster loser regression test. Keep the final person-merge distinct-id guard as a second line of defense.

### GPUFLOW-2-CONTRACTSROSTER-R-08 — medium

File: `docs/workbay/contracts/identity-merge.md:170-188`.

Evidence: The two-step text requires a step-1 pick, but the commit table only lists `operator_initial_choice` and says it is stored. It does not require a positive existing same-tenant person, reject the loser/self case, or define the missing-field error. The prior canonical commit contract still documents only `survivor_id` and `loser_id` (`docs/workbay/contracts/clustering-api.md:852-861`).

Impact: A caller can omit, forge, or submit a foreign/self initial choice while still completing a merge, so the HAI-15 audit field is not guaranteed to represent the operator's actual first choice.

Fix: Declare the field required, validate it against the tenant-scoped step-1 roster and distinct loser id, preserve it verbatim even when the final survivor changes, and define the fail-closed validation response.

### GPUFLOW-2-CONTRACTSROSTER-R-09 — low

File: `packages/shared-contracts/schemas/recognition-cluster-merge-candidates-response.schema.json:1-8`; `apps/prototype-description-service/scene/tests/test_shared_schema_documents.py:11-21`.

Evidence: The repository schema-document test registers only `image-description-response`, `scene-describe-multipart`, and `scene-describe-run`; the required composer-lock test checks only `apps/prototype-wp-alt-context/composer.lock`. The delta adds no tests or fixtures for the four new schemas and their examples.

Impact: CI can report green while these new cross-boundary schemas drift or lose their examples/invariants. The current test command is therefore not evidence of B2/B6 contract coverage.

Fix: Add the four schemas and representative valid/invalid examples to the owning contract test suite, including the all-or-neither quality rule and candidate aggregation exclusions.

## Verification

- `/home/gate/grok-sandbox/review-gpuflow-2-contracts-roster-f0ee2cd0/.venv/bin/python -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` — 1 passed.
- `/home/gate/grok-sandbox/review-gpuflow-2-contracts-roster-f0ee2cd0/.venv/bin/python -m pytest apps/prototype-description-service/scene/tests/test_shared_schema_documents.py -q -p no:cacheprovider` — 28 passed (the test's registry does not include these four new schemas).
- Draft-07 schema checks and all checked-in examples passed for the four changed JSON schemas; the targeted raw `sharpness: 42.5` case was rejected by the new snapshot schema, confirming R-01.
- The five paths in the supplied delta were mechanically checked against the five-path owned list; no sibling-lane path was changed.
