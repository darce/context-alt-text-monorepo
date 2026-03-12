# PHP Plugin Context Map

> Quick reference for agents working on WordPress plugin PHP code.

## Critical Files (Read First)

| Priority | File                                                      | Purpose                                        |
| -------- | --------------------------------------------------------- | ---------------------------------------------- |
| 1        | `apps/prototype-wp-alt-context/alt-context.php`           | Plugin entry point                             |
| 2        | `apps/prototype-wp-alt-context/src/api/`                  | REST API controllers                           |
| 3        | `apps/prototype-wp-alt-context/src/sovereign/`            | Local state, sync, outbox, conflict resolution |
| 4        | `apps/prototype-wp-alt-context/src/media/`                | XMP metadata embedding                         |
| 5        | `apps/prototype-wp-alt-context/src/support/`              | Lifecycle, schema migrations                   |
| 6        | `docs/agentic/contracts/clustering-api.md`                | WP REST API contract                           |
| 7        | `docs/agentic/contracts/curation-sync-api.md`             | Outbox replay contract                         |

## Architecture Layers

### REST API (`src/api/`)

| Controller                        | Routes                                               | Purpose                                       |
| --------------------------------- | ---------------------------------------------------- | --------------------------------------------- |
| `Api`                             | --                                                   | Route registration orchestrator               |
| `RecognitionController`           | `POST .../analyze`                                   | Scan/recognition job submission               |
| `ClustersController`              | `GET .../clusters`, `GET .../clusters/{uuid}`        | Cluster listing/detail (local-first reads)    |
| `ClusterMutationsController`      | `POST .../clusters/{uuid}/label`, `/merge`, etc.     | Label, merge, split, dismiss, person binding  |
| `ConflictController`              | `GET/POST .../conflicts`, `GET/POST .../outbox/...`  | Conflict list/resolve, dead-letter retry/discard |
| `SyncStatusController`            | `GET/POST .../sync-status`                           | Sync health, trigger sync                     |
| `MediaIdentitiesController`       | `GET .../media-identities`                           | Local media-to-identity mappings              |
| `SuggestionsController`           | `GET .../suggestions`                                | Merge suggestion endpoints                    |
| `AnalysisJobsController`          | `GET .../jobs/{id}`                                  | Job status polling                            |
| `XmpEmbedController`              | `POST .../xmp-embed`                                 | XMP metadata write                            |

### Sovereign Sync (`src/sovereign/sync/`)

| Class                        | Purpose                                                    |
| ---------------------------- | ---------------------------------------------------------- |
| `SnapshotClient`             | HTTP client for backend snapshot fetch                     |
| `SnapshotProjector`          | Materializes snapshot into local tables with conflict detection |
| `SyncPullJob`                | Single incremental sync unit-of-work                       |
| `SyncPullJobFactory`         | Creates pull jobs from sync cursors                        |
| `SyncPullResult`             | Value object (`ok`, `failed`, `unreachable`, `skipped`)    |
| `OutboxWriter`               | Writes local curation mutations to durable outbox          |
| `OutboxDispatcher`           | Ships outbox entries to recognition service                |
| `OutboxDrain`                | Consumes outbox with bounded retry; dead-letter management |
| `ConflictRepository`         | Persists sync conflicts (`wp_acx_sync_conflicts`)          |
| `ConflictResolutionService`  | Source-aware resolution dispatch (accept/dismiss)          |
| `TopologyCommandRepository`  | Persists topology commands (`wp_acx_topology_commands`)    |
| `CrossPlaneSequencer`        | Sequences local + remote topology mutations                |
| `SplitTopologyCommandDrain`  | Drains split-topology commands                             |

### Repositories (`src/sovereign/repositories/`)

| Repository                   | Tables                                    | Key Methods                                      |
| ---------------------------- | ----------------------------------------- | ------------------------------------------------ |
| `ClustersRepository`         | `wp_acx_clusters`                         | CRUD, `reset_curation()`, `delete_cluster_with_members()` |
| `IdentityMembersRepository`  | `wp_acx_identity_members`                 | CRUD, `reset_curation()`, `delete_member()`, `accept_machine_cluster_assignment()` |
| `SyncStateRepository`        | `wp_acx_sync_state`                       | Sync metrics, `classify_sync_health()`           |

### Media / XMP (`src/media/`)

| Class                            | Purpose                                    |
| -------------------------------- | ------------------------------------------ |
| `ImageXmpWriter`                 | Reads/modifies XMP in image files          |
| `JpegXmpInjector`                | JPEG-specific XMP manipulation             |
| `PngXmpInjector`                 | PNG-specific XMP manipulation              |
| `XmpImageRegionPacketBuilder`    | Constructs XMP image region packets        |
| `LocalProjectionFaceMetricsSource` | Reads face metrics from local projection |

## Test Entry Points

| Scope       | Path                 | When to Use                           |
| ----------- | -------------------- | ------------------------------------- |
| Unit        | `tests/Unit/`        | Pure PHP logic, service/repo behavior |
| Integration | `tests/Integration/` | WordPress hooks, DB, cross-class      |

## Security Patterns (MANDATORY)

```php
// Every state-changing endpoint MUST:

// 1. Verify nonce
check_ajax_referer('acx_nonce', 'nonce');

// 2. Check capability
if (!current_user_can('manage_options')) {
    return new WP_Error('forbidden', 'Insufficient permissions', ['status' => 403]);
}

// 3. Sanitize input
$media_id = absint($request->get_param('media_id'));

// 4. Escape output
echo esc_html($value);
```

## Key Diagrams

- [../diagrams/sovereign-data-flow.mmd](../diagrams/sovereign-data-flow.mmd) — Sovereign sync data flow
- [frontend-uml/proxy-boundary.mmd](../diagrams/frontend-uml/proxy-boundary.mmd) — WP → Backend proxy flow
- [frontend-uml/plugin-core-classes.mmd](../diagrams/frontend-uml/plugin-core-classes.mmd) — Class relationships

## Common Tasks

### Add a new REST endpoint

1. Create controller in `src/api/`
2. Register route via `register_rest_route('acx/v1', ...)`
3. Add `manage_options` capability check
4. Write PHPUnit test in `tests/Unit/` or `tests/Integration/`

### Proxy to recognition service

1. Use `SnapshotClientTransport::request()`
2. Inject `tenant_id` (md5 of site URL) via `X-Tenant-ID` header
3. Forward response to frontend
4. Handle errors with `WP_Error`

### Add a new outbox operation type

1. Enqueue via `OutboxWriter::write()` with operation type and payload
2. Add dispatch route in `OutboxDispatcher::TOPOLOGY_ROUTES` (for topology) or handle in curation dispatch
3. Add conflict acceptance logic in `ConflictResolutionService` if the operation supports accept/dismiss
4. Write PHPUnit tests for drain dispatch and conflict resolution paths

### Resolve sync conflicts

1. `ConflictController` exposes `GET /conflicts` (list) and `POST /conflicts/{id}/resolve`
2. `ConflictResolutionService::resolve()` dispatches per source (outbox vs projection) and operation type
3. Outbox accept: clears curation flags, discards outbox row
4. Outbox dismiss: re-enqueues with updated base version
5. Projection accept: dispatches per `conflict_code` (delete cluster, delete member, reassign member)
6. Projection dismiss: no entity mutation
