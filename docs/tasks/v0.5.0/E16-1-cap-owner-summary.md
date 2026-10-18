# E16-1 Cap-Owner Summary

Single-page reference for the bounded-iteration cap owners landed on `feature/e16-1`. This is the compact summary the eventual E16 epic doc can cite instead of rediscovering the constants across controllers, repositories, and lifecycle flows.

## REST List Surfaces

| Surface | Cap owner | Owning file | Notes |
| --- | --- | --- | --- |
| `GET /recognition/clusters` | `LIST_CLUSTERS_MAX_LIMIT = 500` | `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php` | Controller envelope returns `clusters`, `limit`, `total`, `truncated`. Shared schema: `recognition-cluster-list-response.schema.json`. |
| `GET /recognition/clusters/labels` | `LIST_CLUSTER_LABELS_MAX_LIMIT = 500` | `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php` | Local projection delegates bounded search/limit handling into `ClustersRepository::list_labels()`. Shared schema: `recognition-cluster-labels-response.schema.json`. |
| `GET /recognition/clusters/top-unlabeled` | `LIST_TOP_UNLABELED_CLUSTERS_MAX_LIMIT = 500` | `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php` | Request clamp is owned by the controller; response envelope reports the effective capped `limit`. Shared schema: `recognition-cluster-top-unlabeled-response.schema.json`. |
| `GET /recognition/clusters/{cluster_id}/members` | `GET_CLUSTER_MEMBERS_MAX_LIMIT = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT` | `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php` | The controller keeps the response envelope canonical and rejects partial proxy metadata. The repository-side limit owner remains `DEFAULT_CLUSTER_MEMBER_LIMIT = 500`. Shared schema: `recognition-cluster-members-response.schema.json`. |

## Repository Seams

| Seam | Cap owner | Owning file | Notes |
| --- | --- | --- | --- |
| `ClustersRepository::merge_snapshot_for_tenant()` upsert batches | `MAX_SNAPSHOT_MERGE_BATCH = 500` | `apps/prototype-wp-alt-context/src/sovereign/repositories/interface-clusters-repository.php` | Stale-row pruning still runs once per payload; row upserts execute in bounded chunks through `merge_snapshot_batch_for_tenant()`. |
| `IdentityMembersRepository::list_for_cluster()` | `DEFAULT_CLUSTER_MEMBER_LIMIT = 500` | `apps/prototype-wp-alt-context/src/sovereign/repositories/interface-identity-members-repository.php` | The repository boundary stays typed at the interface, while the owning callers surface `total` and `truncated` in their envelopes. |

## Lifecycle Migration

| Surface | Cap owner | Owning file | Notes |
| --- | --- | --- | --- |
| `LifecycleManager::migrate_legacy_roster_data()` | `MAX_LEGACY_MIGRATION_CHUNK = 100` | `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | Chunked activation migration persists the resume cursor and schedules `acx_continue_legacy_roster_migration` until the migration clears its remaining work. |

## Multipart Owner Note

`AltContext\Api\AnalysisJobsController::MULTIPART_MAX_IMAGES = 5` remains the canonical multipart upload cap for the WordPress boundary. The admin scanner mirrors that cap in `apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts` and computes `Math.min(getConfig().maxMediaPerBatch, MULTIPART_MAX_IMAGES)` so `maxMediaPerBatch` cannot widen the multipart request size above the owner.

`maxMediaPerBatch` still exists in `apps/prototype-wp-alt-context/js/admin/api/config.ts`, so the naming cleanup remains an explicit follow-up for `E16-2`. E16-1 verifies the effective owner and documents the subordinate relationship; it does not rename or remove the config knob.