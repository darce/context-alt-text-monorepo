# PHP Plugin Context Map

> Quick reference for agents working on WordPress plugin PHP code.

## Critical Files (Read First)

| Priority | File                                            | Purpose                                        |
| -------- | ----------------------------------------------- | ---------------------------------------------- |
| 1        | `apps/prototype-wp-alt-context/alt-context.php` | Plugin entry point                             |
| 2        | `apps/prototype-wp-alt-context/src/api/`        | REST API controllers                           |
| 3        | `apps/prototype-wp-alt-context/src/sovereign/`  | Local state, sync, outbox, conflict resolution |
| 4        | `apps/prototype-wp-alt-context/src/media/`      | XMP metadata embedding                         |
| 5        | `apps/prototype-wp-alt-context/src/support/`    | Lifecycle, schema migrations                   |
| 6        | `docs/agentic/contracts/clustering-api.md`      | WP REST API contract                           |
| 7        | `docs/agentic/contracts/curation-sync-api.md`   | Outbox replay contract                         |

## Architecture Layers

### REST API (`src/api/`)

| Controller                   | Routes                                                                                                                                                                                                                                                                                                                                                                         | Purpose                                                                 |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| `RecognitionController`      | --                                                                                                                                                                                                                                                                                                                                                                             | Composition root; delegates `register_routes()` to all sub-controllers  |
| `AnalysisJobsController`     | `POST .../analyze`, `GET .../jobs/{id}`, `GET .../jobs/{id}/stream`, `POST .../jobs/{id}/cancel`, `POST .../jobs/{id}/acknowledge-projection`                                                                                                                                                                                                                                  | Scan submission, job polling, SSE streaming, projection acknowledgement |
| `ClustersController`         | `GET .../clusters`, `GET .../clusters/top-unlabeled`, `GET .../clusters/labels`, `GET .../clusters/{uuid}`, `GET .../clusters/{uuid}/members`                                                                                                                                                                                                                                  | Cluster reads (local-first sovereign projection)                        |
| `ClusterMutationsController` | `PATCH .../clusters/{uuid}`, `POST .../clusters/{uuid}/dismiss`, `DELETE .../clusters/{uuid}/dismiss`, `POST .../clusters/{source}/merge`, `POST .../clusters/{uuid}/split`, `POST .../clusters/create-for-identity`, `POST .../clusters/reassign`, `POST .../clusters/revert-merge`, `POST .../clusters/{uuid}/assign`, `PATCH .../clusters/{uuid}/representatives/{rep}/pin` | Label, merge, split, dismiss, reassign, representative pinning          |
| `SuggestionsController`      | `GET .../suggestions`, `GET .../suggestions/merge`, `GET .../suggestions/name`, `POST .../suggestions/{id}/accept\|reject`, `POST .../suggestions/merge/{id}/accept\|reject`, `POST .../suggestions/name/{id}/accept\|reject`, `GET .../identities/{id}/suggestions`                                                                                                           | Assignment, merge, and name suggestion reads + accept/reject            |
| `ConflictController`         | `GET .../conflicts`, `GET .../conflicts/{id}`, `POST .../conflicts/{id}/resolve`, `GET .../outbox`, `GET .../outbox/failed`, `POST .../outbox/{id}/retry`, `POST .../outbox/{id}/discard`                                                                                                                                                                                      | Conflict list/resolve, dead-letter retry/discard                        |
| `SyncStatusController`       | `GET .../sync-status`, `POST .../sync/trigger`                                                                                                                                                                                                                                                                                                                                 | Sync health reads, manual sync trigger                                  |
| `MediaIdentitiesController`  | `GET .../media-identities`                                                                                                                                                                                                                                                                                                                                                     | Local media-to-identity mappings                                        |
| `XmpEmbedController`         | `POST .../xmp-embed`                                                                                                                                                                                                                                                                                                                                                           | XMP metadata write                                                      |

### Sovereign Sync (`src/sovereign/sync/`)

| Class                       | Purpose                                                         |
| --------------------------- | --------------------------------------------------------------- |
| `SnapshotClient`            | HTTP client for backend snapshot fetch                          |
| `SnapshotProjector`         | Materializes snapshot into local tables with conflict detection |
| `SyncPullJob`               | Single incremental sync unit-of-work                            |
| `SyncPullJobFactory`        | Creates pull jobs from sync cursors                             |
| `SyncPullResult`            | Value object (`ok`, `failed`, `unreachable`, `skipped`)         |
| `OutboxWriter`              | Writes local curation mutations to durable outbox               |
| `OutboxDispatcher`          | Ships outbox entries to recognition service                     |
| `OutboxDrain`               | Consumes outbox with bounded retry; dead-letter management      |
| `ConflictRepository`        | Persists sync conflicts (`wp_acx_sync_conflicts`)               |
| `ConflictResolutionService` | Source-aware resolution dispatch (accept/dismiss)               |
| `TopologyCommandRepository` | Persists topology commands (`wp_acx_topology_commands`)         |
| `CrossPlaneSequencer`       | Sequences local + remote topology mutations                     |
| `SplitTopologyCommandDrain` | Drains split-topology commands                                  |

### Repositories (`src/sovereign/repositories/`)

| Repository                  | Tables                    | Key Methods                                                                        |
| --------------------------- | ------------------------- | ---------------------------------------------------------------------------------- |
| `ClustersRepository`        | `wp_acx_clusters`         | CRUD, `reset_curation()`, `delete_cluster_with_members()`                          |
| `IdentityMembersRepository` | `wp_acx_identity_members` | CRUD, `reset_curation()`, `delete_member()`, `accept_machine_cluster_assignment()` |
| `SyncStateRepository`       | `wp_acx_sync_state`       | Sync metrics, `classify_sync_health()`                                             |

### Media / XMP (`src/media/`)

| Class                              | Purpose                                  |
| ---------------------------------- | ---------------------------------------- |
| `ImageXmpWriter`                   | Reads/modifies XMP in image files        |
| `JpegXmpInjector`                  | JPEG-specific XMP manipulation           |
| `PngXmpInjector`                   | PNG-specific XMP manipulation            |
| `XmpImageRegionPacketBuilder`      | Constructs XMP image region packets      |
| `LocalProjectionFaceMetricsSource` | Reads face metrics from local projection |

## Test Entry Points

| Scope       | Path                 | When to Use                           |
| ----------- | -------------------- | ------------------------------------- |
| Unit        | `tests/Unit/`        | Pure PHP logic, service/repo behavior |
| Integration | `tests/Integration/` | WordPress hooks, DB, cross-class      |

## Security Patterns (MANDATORY)

All REST controllers extend `AbstractRecognitionProxyController` which provides:

```php
// Permission callback used by all route registrations:
'permission_callback' => array( $this, 'can_manage_recognition' ),
// Internally checks: current_user_can('manage_options')

// Proxy requests add authentication headers automatically:
// X-Tenant-ID: <md5 of site URL>
// X-API-Key: <stored API key>

// Input sanitization is done via WP REST schema validation (args array)
// and manual sanitization in controller callbacks:
$media_id = absint($request->get_param('media_id'));
$label    = sanitize_text_field($request->get_param('label'));
```

Notes:

- Controllers use WP REST API permission callbacks; NOT `check_ajax_referer()` or `echo`-style output.
- Backend requests go through `AbstractRecognitionProxyController::proxy_request()` with circuit breaker and timeout policies.
- `RecognitionController` is a composition root (not a proxy subclass); it delegates `register_routes()` to all sub-controllers.

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

1. Extend `AbstractRecognitionProxyController` and use `$this->proxy_request()` (see `class-abstract-recognition-proxy-controller.php`)
2. `proxy_request()` injects `tenant_id` (md5 of site URL) via `X-Tenant-ID` header automatically
3. Forward response to frontend
4. Handle errors with `WP_Error`

Note: `SnapshotClientTransport::request()` is a non-public sovereign sync transport adapter; it is not the proxy surface for public REST controllers.

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
