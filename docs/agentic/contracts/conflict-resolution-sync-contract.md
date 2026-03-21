# Conflict Resolution and Sync Contract

## Purpose

This note defines the workbench conflict-resolution vocabulary and the sync-status shape that the PHP backend and React frontend share.

## Conflict codes

The backend may emit these `conflict_code` values:

- `curated_cluster_deleted`
- `curated_member_deleted`
- `member_cluster_reassignment`
- `person_name_conflict`
- `version_conflict`
- `drift_conflict`

## Resolution choices

`allowed_resolutions` and `ResolveConflictRequest.resolution_status` use these values:

- `accepted`
- `accept_backend`
- `dismissed`
- `merge`

Notes:

- `accepted` remains valid for generic backend acceptance flows.
- `accept_backend` is the explicit backend-preferring choice used by person-name and drift conflicts.
- `merge` is the explicit merge path for person-name conflicts.
- `dismissed` keeps local state.
- `person_name_conflict` is only expected when the curated cluster is linked to a `person_id`; that guard is intentional unless the backend contract changes.

## Sync status

`SyncStatusResponse` includes:

- `sync_health`
- `last_sync_result`
- `last_snapshot_version`
- `last_synced_at`
- `sync_mode`

`sync_mode` is derived from the current snapshot state:

- `delta` when a tenant already has a local snapshot version
- `full` when no local snapshot version exists yet

This is an inferred runtime label, not a persisted source-of-truth field.

## Frontend guidance

- Prefer `accept_backend` and `merge` when rendering person-name conflict actions.
- Keep `accepted` available for generic machine-accept flows where the backend still returns that spelling.
- Treat `sync_mode` as informational UI metadata only.
