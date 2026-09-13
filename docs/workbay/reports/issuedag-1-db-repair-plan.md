# ISSUEDAG-1: narrow `mv_identity_cluster_centroids` rebuild plan

Status: analysis only. This lane writes no source code, executes no database operation, and makes no production change.

## Decision

Do not use the current `scripts.sync_identity_schema` entry point for this repair. It is a full-schema healer, and its first table pass can stop on the unrelated missing `cluster_merge_survivor_in_pair` check constraint before it reaches the centroid materialized view.

The canonical narrow unit already exists as `ensure_matview(op)`. The implementation should expose that unit through an explicitly selected matview-only entry point, under the same transaction-scoped advisory lock as the normal healer. The entry point must not call the table, vector-typmod, RLS, refresh-queue, or trigger healers. A data refresh is a separate step: use the existing concurrent-refresh path only after structural repair and only on an autocommit connection with a headroom and lock-time budget.

## 1. Trace of the current paths

### Migration: canonical matview behavior

- `001_identity_schema.py:_matview_centroid_typmod` (`apps/prototype-description-service/db/migrations/versions/001_identity_schema.py:2072-2090`) reads `pg_attribute`, `pg_class`, `pg_namespace`, and `pg_type`, and only accepts a `vector` column. This is the type invariant that detects the old typmod-less centroid view.
- `_matview_owner_and_can_drop` (`.../001_identity_schema.py:2131-2153`) obtains the current owner and whether the current role can drop the existing materialized view; it fails closed if the relation disappears between probes.
- `_matview_create_privilege_gaps` (`.../001_identity_schema.py:2156-2193`) preflights schema `CREATE`, `SELECT` on `identity_clusters`, `identity_members`, and `media_identities`, plus `EXECUTE` on `l2_normalize`. The C-01 ratchet comment at `.../001_identity_schema.py:2157-2159` requires this list to stay synchronized with the view's `FROM`/`JOIN` tables and functions.
- `_matview_nonowner_grants` and `_missing_matview_grant_roles` (`.../001_identity_schema.py:2196-2238`) snapshot non-owner ACL entries and reject vanished grantee roles before any destructive operation.
- `_matview_owner_restore_blockers` (`.../001_identity_schema.py:2241-2262`) checks that the original owner still exists and can own an object in the schema. `_grant_target` (`.../001_identity_schema.py:2265-2269`) preserves the `PUBLIC` pseudo-role distinction.
- `_restore_matview_owner_and_grants` (`.../001_identity_schema.py:2272-2300`) replays the captured grants and then restores the original owner, turning replay failures into named operator errors.
- `ensure_matview` (`.../001_identity_schema.py:2303-2470`) is the narrow DDL unit. It rejects a non-matview relkind at `2312-2318`; on a wrong centroid typmod it preflights owner, privileges, grantees, and owner restoration at `2320-2361`, then drops only the materialized view at `2362`, recreates it from the canonical source query at `2373-2444`, recreates its three indexes at `2446-2466`, and restores owner/ACL at `2468-2470`. A matching typmod does not trigger a drop.
- `heal(connection)` (`.../001_identity_schema.py:2473-2490`) composes the broad sequence: extension, `ensure_tables`, table vector typmods, RLS, refresh queue, triggers, and finally `ensure_matview`. This is the path that must be bypassed for ISSUEDAG-1.

The unrelated blocker is declared on `cluster_merge_suggestions` as `CheckConstraint("survivor_cluster_id IS NULL OR survivor_cluster_id = cluster_a_id OR survivor_cluster_id = cluster_b_id", name="cluster_merge_survivor_in_pair")` at `.../001_identity_schema.py:938-1007`, specifically `998-1001`. `_ensure_table_constraints` (`.../001_identity_schema.py:312-356`) refuses an unhealed declared table-level CHECK/UNIQUE/FK constraint, and `ensure_tables` reaches that declaration before `heal` can call `ensure_matview`. It is not a centroid invariant.

### Sync entry point

- `sync_schema(engine)` (`apps/prototype-description-service/scripts/sync_identity_schema.py:33-58`) imports the migration, takes `_ADVISORY_LOCK_KEY` with `pg_advisory_xact_lock` at `43-45`, snapshots tables, and calls `migration.heal(conn)` at `49`. Therefore it cannot currently be used for a matview-only repair.
- `main()` (`.../scripts/sync_identity_schema.py:61-75`) creates the configured engine and always calls the broad `sync_schema(engine)` at `65`; there is no mode selector or CLI parser.

### Application refresh entry points

`ClusterRepository.refresh_centroids_view` and `refresh_centroids_view_concurrent` are interface operations at `apps/prototype-description-service/recognition/domain/repositories.py:106-112`. The PostgreSQL implementation (`.../recognition/infrastructure/repositories/cluster_repository.py:147-207`) refreshes an existing view; it does not repair a missing view, a plain-table impostor, or a wrong vector typmod. The concurrent branch also requires the unique `cluster_id` index that `ensure_matview` creates.

### Verification path

- `_collect_matview_create_privilege_gaps` and `_collect_matview_vanished_grantees` (`apps/prototype-description-service/scripts/verify_identity_schema.py:320-330`) reuse the migration's matview preflight helpers through `_BindOp`; they do not repair anything.
- `_collect_unique_constraint_gaps` (`.../scripts/verify_identity_schema.py:332-352`) iterates `HEAL_UNIQUE_CONSTRAINTS`. In this checkout that tuple contains only `uq_image_description_runs_idempotency_key` (`.../001_identity_schema.py:61-71`), so the missing `cluster_merge_survivor_in_pair` CHECK is not collected by this verifier.
- `collect_and_validate` (`.../verify_identity_schema.py:355-434`) collects relkind, owner/drop capability, vector typmods, matview privilege/ACL facts, and unique gaps. `_validate_schema_state` (`.../verify_identity_schema.py:148-215`) classifies a matview as healthy only when relkind is `m` and centroid typmod equals `EMBEDDING_DIMENSION`; it treats collected unique gaps as heal-repairable.
- `main()` (`.../verify_identity_schema.py:437-495`) has no `argparse` or other CLI flags. The current command is a full-schema verification, not a scoped matview verifier. On success it prints `matview=m centroid_typmod=...` (`453-457`); on failure it reports the matview facts and any collected gaps (`460-491`).

## 2. Narrow operation to implement later

The smallest safe public surface is a migration wrapper plus an explicit sync dispatch; neither is implemented in this analysis lane:

1. Add `repair_centroids_matview(connection) -> None` in `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`. It should construct Alembic `Operations` for the supplied connection and call only the existing `ensure_matview(ops)`. It must not create the `vector` extension, call `ensure_tables`, or call any other `ensure_*` function; requiring those objects as preconditions keeps the scope to the matview and its matview-owned indexes.
2. Add `sync_centroids_matview(engine: Engine) -> None` in `apps/prototype-description-service/scripts/sync_identity_schema.py`, using the same `_ADVISORY_LOCK_KEY` and transaction-scoped lock as `sync_schema`, then calling the migration wrapper. Add an explicit `--matview-only` dispatch in `main`; leave the default broad path unchanged. The flag must never silently weaken or skip the existing full-heal behavior.

The operation's invariants are:

- Operate only in PostgreSQL's intended schema, with the `vector` extension, source tables/columns, and `l2_normalize` already present. Do not create or alter any source table, constraint, RLS policy, queue, trigger, or unrelated index.
- Run `ensure_matview`'s relkind and typmod checks first. A plain table/view under the matview name is an operator error; never drop it as if it were derived data.
- Before a wrong-typmod drop, retain the existing owner and non-owner ACL, verify all grantee roles and owner-restoration privileges, and verify source `CREATE`/`SELECT`/function privileges. Any preflight failure occurs before `DROP MATERIALIZED VIEW`.
- Keep drop/create/index/ACL/owner work in one transaction. A grant or owner replay error must roll back the rebuild, leaving the original relation available for operator remediation.
- A missing view is created from the canonical `ensure_matview` definition and receives the unique `cluster_id`, tenant, and vector indexes. A valid existing view is not dropped. If the requirement is fresh rows rather than structural repair, commit this step first and run `REFRESH MATERIALIZED VIEW CONCURRENTLY` through the existing autocommit refresh path; do not issue concurrent refresh inside the structural transaction.
- Serialize the narrow operation with boot healing via the existing advisory lock. Allow only a small, named retry budget for transient lock contention, with backoff/jitter; privilege, relkind, source-shape, and data-integrity failures are terminal and must fail closed.

This reuses the migration as the single schema/derived-view authority (DATA-14) and avoids creating a second hand-maintained view definition. It also preserves the model-selection, normalization, and outer `vector(EMBEDDING_DIMENSION)` cast in the existing definition (`.../001_identity_schema.py:2388-2442`), which is important to the embedding-space risks referenced by SVCEMB-M-04 and B-06.

## 3. Preconditions, postconditions, and verification

### Preconditions

- Target the intended database and schema with an explicit operator connection; this lane does not connect to production.
- Confirm the source-of-truth tables and columns used by the canonical definition exist, `vector` and `l2_normalize` are available, and the configured embedding dimension is the expected one.
- The current role must be able to create in the schema and drop the existing matview when a rebuild is required. It must have the source `SELECT`/function privileges, and every captured ACL grantee plus the captured owner must still be restorable.
- Confirm enough disk headroom for the rebuilt view and indexes. The existing concurrent path measures the current matview size and requires at least `max(min_bytes, 2 * mv_bytes)` before refreshing (`.../cluster_repository.py:173-189`); a maintenance window may require a larger operational margin for DROP/CREATE/index build.
- Set bounded lock and statement timeouts for the operator session. An AccessExclusive lock from DROP/CREATE and the refresh's locks must not wait without a deadline.
- Explicitly acknowledge `cluster_merge_survivor_in_pair` as out of scope. Do not weaken its declared definition or invoke the full healer to make the centroid repair appear green.

### Postconditions

- `mv_identity_cluster_centroids` exists in the intended schema with `relkind = 'm'`; `centroid` is a `vector` with `atttypmod = EMBEDDING_DIMENSION`.
- The matview-owned unique `cluster_id`, tenant, and vector indexes exist; in particular, the unique `cluster_id` index is present before any concurrent refresh.
- For a rebuild, the pre-existing owner and non-owner grants are unchanged after replay. For a newly created view, the operator records and verifies the intended owner/ACL rather than relying on an undocumented default.
- If a fresh-data step was requested, the committed concurrent refresh completed and its outcome was observed. A failure or headroom skip is surfaced; it is not swallowed and must not be reported as fresh.
- No source-table rows, columns, constraints, RLS state, queue, or trigger were changed. The known missing CHECK remains a separately tracked schema gap.

### Verification command and current flag limitation

With the current checkout, the only available verifier invocation (there are no flags) is:

```text
cd apps/prototype-description-service
lane_root="$(git rev-parse --show-toplevel)"
resolved_python="$lane_root/.venv/bin/python"
"$resolved_python" -m scripts.verify_identity_schema
```

Its successful summary proves the verifier's relkind and centroid-typmod checks, but it does not explicitly print owner/ACL equality. The known missing `cluster_merge_survivor_in_pair` CHECK is tolerated only because `_collect_unique_constraint_gaps` does not inspect CHECK constraints; there is no explicit `--ignore-constraint` or `--matview-only` flag today. If a future verifier expands that collector to include the known CHECK, the current verifier cannot tolerate it: any collected gap drives exit code `1` and the script has no allowlist mode. The implementation should therefore add a narrowly scoped `--matview-only` verifier mode (with an explicit, named allowance only for this known constraint) or a dedicated matview-state verifier that checks relkind, vector typmod, unique index, owner, and ACL without turning a global schema waiver into a health signal. Do not document a not-yet-existing flag as runnable.

The existing regression surfaces to preserve when implementing this plan are `recognition/tests/schema/test_identity_schema_heal_pg.py` (typmod rebuild, owner refusal, and grant/owner restoration), `recognition/tests/unit/test_refresh_centroids_view_fail_fast.py` (refresh errors propagate), and `recognition/tests/unit/test_mv_refresh_headroom.py` (headroom skip, concurrent-refresh precondition, and bypass cleanup).

## 4. Canonical risks and controls

| Risk / canon | Control in this plan |
| --- | --- |
| DATA-14 — two authorities for one logical view | Keep the view body, casts, and indexes in `001_identity_schema.py`; the new entry point delegates to `ensure_matview` and contains no alternate DDL. Source tables remain authoritative. |
| REF-09 — derived-data drift | Treat the matview as disposable derived state. Rebuild or refresh only from committed `identity_clusters`, `identity_members`, and `media_identities`; verify type, indexes, and observed refresh outcome rather than editing rows in the view. |
| RES-06 — retry storm | Serialize with the existing advisory lock; use bounded attempts plus backoff/jitter only for transient lock contention. Never retry privilege, relkind, missing-source, or invalid-data errors. |
| RES-14 — unbounded repair fan-out | Make the CLI a single explicit operation, not a per-boot/per-row queue. A concurrent caller waits once behind the advisory lock or fails at the configured timeout; no unbounded repair backlog is created. |
| DDIA ch. 11 — derived views rebuilt from source of truth | Use the existing canonical materialized-view query and its vector normalization/model-selection rules. Do not copy data from the old view or introduce a second projection writer. |
| Release It ch. 5 — unbounded lock waits | Set lock/statement deadlines, schedule destructive rebuilds for a controlled window, and use the existing autocommit concurrent-refresh path. `REFRESH MATERIALIZED VIEW CONCURRENTLY` is allowed only after the non-partial unique `cluster_id` index exists. |

## 5. Disposition of `cluster_merge_survivor_in_pair`

Keep this constraint change separate from ISSUEDAG-1. The constraint is unrelated to centroid derivation, and adding it in the repair would expand the lock, data-validation, and rollback surface while the known production gap is explicitly outside the incident. First audit/remediate any rows whose `survivor_cluster_id` is not null and is not one of `cluster_a_id`/`cluster_b_id`; then apply the constraint in a separately reviewed schema-reconciliation change. Under the repository's greenfield policy, that schema declaration/reconciliation belongs directly in `001_identity_schema.py` at the existing `cluster_merge_suggestions` definition, not in a new migration revision. The centroid-only operation must neither add it nor make the full healer ignore it.
