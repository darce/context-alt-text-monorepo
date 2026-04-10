# PostgreSQL 17 → 18 Upgrade Evaluation (v0.1)

## Objective

Evaluate and execute the upgrade from PostgreSQL 17 to PostgreSQL 18, leveraging new features to simplify the multitenancy layer, improve materialized-view workflows, strengthen authentication, and reduce application-level complexity.

## Problem Statement

The prototype-description-service relies on PostgreSQL 17 with pgvector for face-recognition clustering. Tenant isolation is enforced via RLS policies and manual `SET LOCAL` session variables. Materialized views require application-managed dirty-tracking queues and trigger scaffolding. Authentication uses a bespoke API-key hash-lookup mechanism. PostgreSQL 18 introduces native capabilities (UUIDv7, OAuth, AIO, virtual generated columns, improved MV support, enhanced pg_dump RLS tooling) that can reduce custom code, improve performance, and lower operational risk.

## Constraints

- pgvector extension must ship a PG18-compatible build (`pgvector/pgvector:pg18` image or equivalent) before upgrade can proceed.
- Zero-downtime migration is not required for the prototype; a maintenance-window `pg_upgrade` is acceptable.
- SQLAlchemy 2.x and asyncpg must support PG18 wire protocol 3.2 features; fallback to 3.0 is acceptable.
- WordPress plugin (PHP layer) has no direct PG dependency; only the Python backend is affected.

## Terminology

- **AIO**: PostgreSQL 18's asynchronous I/O subsystem, enabling concurrent read requests for scans and vacuums.
- **MV**: Materialized View — specifically `mv_identity_cluster_centroids`.
- **RLS**: Row-Level Security — PostgreSQL policy-based tenant isolation.
- **Dirty-tracking queue**: The `identity_cluster_refresh_queue` table + trigger system that marks stale clusters for MV refresh.
- **Skip scan**: PG18 btree optimisation that allows index use when leading columns lack equality predicates.

## Current State

- PostgreSQL 17 via `pgvector/pgvector:pg17` Docker image (port 55432).
- Extensions: `uuid-ossp`, `citext`, `pgcrypto`, `vector`.
- ORM: SQLAlchemy 2.x async (`asyncpg`) + sync (`psycopg`) for Alembic migrations.
- Pool: configurable — pool_size=10, max_overflow=5, pool_timeout=30, pool_recycle=3600.
- Multitenancy: shared-database, shared-schema with `tenant_id` UUID FK on every data table (13+ tables).
- RLS: `FORCE ROW LEVEL SECURITY` + `tenant_isolation_*` policies on all tenant tables; session vars `app.current_tenant` and `app.bypass_rls`; pool checkout listener resets both vars.
- Authentication: API-key SHA-256 hash lookup in `api_keys` table; no OAuth/JWT.
- Materialized view: `mv_identity_cluster_centroids` with IVFFlat cosine index; `REFRESH MATERIALIZED VIEW [CONCURRENTLY]`; trigger-based dirty-tracking via `identity_cluster_refresh_queue`.
- Concurrency: `FOR UPDATE SKIP LOCKED` CTE claim pattern for worker job items.
- UUID generation: `uuid-ossp` extension for `uuid_generate_v4()`.
- Data checksums: not enabled by default (PG17 initdb default).

## Target Architecture

After upgrade, the system leverages PG18-native capabilities to remove application scaffolding:

1. **UUIDv7 replaces uuid-ossp v4** — all new primary keys use `uuidv7()`, gaining temporal ordering without an additional `created_at` index for time-range queries on identity tables. The `uuid-ossp` extension can be dropped.
2. **OAuth authentication** — PG18's native `oauth` method in `pg_hba.conf` provides a path toward token-based auth at the database connection level, complementing the existing API-key mechanism and enabling future JWT-to-DB-role mapping.
3. **AIO subsystem** — sequential scans on `media_identities` (embedding table, largest table by row count) and `VACUUM` operations benefit from asynchronous I/O without code changes.
4. **Virtual generated columns** — computed columns (e.g., embedding dimension checks, centroid staleness flags) can be expressed as virtual generated columns instead of application-side derivations.
5. **`OLD`/`NEW` RETURNING** — the scan-job claim CTE in `scan_queue_repository.py` can return both pre-update and post-update state, eliminating a follow-up SELECT.
6. **Skip scan** — multi-column indexes keyed on `(tenant_id, ...)` benefit when queries filter on non-leading columns (e.g., status-only scans across tenants during maintenance bypass).
7. **`--no-policies` pg_dump** — schema-only exports for development/CI environments can strip RLS policies, simplifying test fixture creation and removing the `is_sqlite()` fallback path.
8. **pg_upgrade preserves statistics** — post-upgrade ANALYZE pass is no longer required; query plans are stable immediately.
9. **AFTER triggers fire as queuing role** — the dirty-tracking triggers on `identity_members` and `media_identities` now execute under the role that performed the DML, ensuring `app.current_tenant` is correct at trigger-fire time. This closes a subtle race in the current design.
10. **Data checksums enabled by default** — silent data corruption detection is on from initdb, no operational overhead to enable.
11. **pgcrypto SHA-256/512 crypt** — API key hashing can use stronger crypt algorithms natively if the hashing strategy evolves.
12. **Non-btree unique indexes on MVs** — potential to use HNSW or other index types supporting equality as the unique index on `mv_identity_cluster_centroids`, though IVFFlat's current btree unique index is already functional.

### Design Decisions

| Decision | Rationale |
|---|---|
| Replace `uuid-ossp` with native `uuidv7()` | Eliminates extension dependency; gains temporal ordering for free; `uuid-ossp` is a C extension requiring maintenance across upgrades. |
| Keep RLS + session-variable pattern | PG18 does not change RLS fundamentals; the `SET LOCAL` pattern remains correct and is now safer with AFTER trigger role fix. |
| Adopt AIO via `io_method` configuration only | No code changes required; performance gain is pure infrastructure. |
| Defer OAuth DB-level auth | The API-key mechanism is sufficient for the prototype; OAuth support is an enabler for future phases. |
| Use `--no-policies` for test fixtures | Replaces the `is_sqlite()` dialect branching in tenant_context.py, reducing test complexity. |
| Adopt virtual generated columns incrementally | Only for new columns; existing stored columns are not migrated. |

### Data Model

No schema-breaking changes. Migration steps:

1. Replace `uuid_generate_v4()` default expressions with `uuidv7()` on all PK columns.
2. Drop `uuid-ossp` extension (after verifying no other callsites).
3. Add `io_method = 'io_uring'` (Linux) or `io_method = 'posix_aio'` (macOS) to `postgresql.conf`.
4. Optionally convert `identity_cluster_refresh_queue.flagged_at` default from `now()` to a virtual generated column (read-time computation).

## Phased Delivery

### Phase 0: PG17 Safety Parameter Configuration

**Goal**: Configure transaction safety parameters already available in the current PG17 deployment. These are not PG18 features — they are PG9.6+ and PG17 capabilities that are currently unconfigured and directly mitigate the `InFailedSQLTransactionError` cascading failure documented in [the session lifecycle assessment](../assessment/infailed-sql-transaction-investigation-2026-04-09.md).

**Motivation**: The session lifecycle assessment found that no `statement_timeout`, `idle_in_transaction_session_timeout`, or `transaction_timeout` is configured anywhere in the application or PostgreSQL server. A connection in a failed transaction state can sit idle indefinitely, poisoning the connection pool. These server-side defenses bound the damage automatically.

Deliverables:

- Configure `statement_timeout` at the session level via `SET LOCAL` in the session dependency (recommended: `10s` for prototype).
- Configure `idle_in_transaction_session_timeout` at the session level via `SET LOCAL` (recommended: `30s`). Available since PG9.6.
- Configure `transaction_timeout` at the PostgreSQL server level in `postgresql.conf` or Docker entrypoint (recommended: `60s`). Available since PG17. This parameter bounds total transaction duration including application processing time between SQL commands; `SET LOCAL` is not sufficient because the timeout applies to the transaction that sets it.
- Make values configurable via environment variables (`DB_STATEMENT_TIMEOUT`, `DB_IDLE_IN_TXN_TIMEOUT`, `DB_TRANSACTION_TIMEOUT`) with sensible defaults.
- Guard timeout configuration with `is_postgres()` so SQLite test sessions skip it.

Exit criteria:

- `SHOW statement_timeout` returns a non-zero value within an active session.
- `SHOW idle_in_transaction_session_timeout` returns a non-zero value within an active session.
- `SHOW transaction_timeout` returns a non-zero value at the server level.
- A deliberately stalled transaction is terminated by PostgreSQL after the configured timeout (verifiable via integration test).
- Existing test suite passes (SQLite sessions unaffected).

Code anchors:

| Layer | File | Note |
|---|---|---|
| DB | `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | `SET LOCAL` after probe succeeds |
| DB | `apps/prototype-description-service/db/settings.py` | New timeout settings with env-var defaults |
| Infra | `apps/prototype-description-service/docker-compose.db.yml` | Server-level `transaction_timeout` in PG config |

### Phase 1: Compatibility Verification & Upgrade

**Goal**: Upgrade the development database from PG17 to PG18 with zero data loss and passing test suite.

Deliverables:

- Verify `pgvector` PG18-compatible image availability (or build custom).
- Update `docker-compose.db.yml` to `pgvector/pgvector:pg18`.
- Run `pg_upgrade --check` against current schema.
- Execute upgrade (dump/restore or `pg_upgrade --swap`).
- Run full test suite against PG18; fix any asyncpg/SQLAlchemy wire-protocol issues.
- Confirm `REFRESH MATERIALIZED VIEW CONCURRENTLY` still functions with existing unique btree index.
- Validate RLS policies and `SET LOCAL` session variables behave identically.

Exit criteria:

- All existing tests pass on PG18.
- `docker-compose up` starts PG18 container and seeds schema without errors.
- `EXPLAIN ANALYZE` on critical queries (centroid search, job claim, cluster listing) shows no plan regressions.

### Phase 2: UUIDv7 Migration

**Goal**: Replace `uuid-ossp` v4 generation with PG18-native `uuidv7()`, gaining temporal ordering on all primary keys.

Deliverables:

- Alembic migration: `ALTER COLUMN ... SET DEFAULT uuidv7()` for all UUID PK columns (18 tables).
- Remove `CREATE EXTENSION IF NOT EXISTS "uuid-ossp"` from `001-extensions.sql`.
- Add `uuidv4()` alias awareness for any explicit v4 callsites.
- Update SQLAlchemy model defaults if any use Python-side UUID generation.
- Verify IVFFlat index on MV centroid column is unaffected (UUID is PK, not the vector column).

Exit criteria:

- `uuid-ossp` extension is absent from the database; `SELECT * FROM pg_extension` shows no `uuid-ossp`.
- Newly inserted rows have UUIDv7 PKs (verifiable via `uuid_extract_timestamp()`).
- Existing UUIDv4 rows coexist without constraint violations.

### Phase 3: AIO & Performance Configuration

**Goal**: Enable PG18's AIO subsystem and skip-scan optimizer for measurable performance improvement on large-table scans.

Deliverables:

- Configure `io_method` in Docker entrypoint or custom `postgresql.conf`.
- Set `effective_io_concurrency = 16` and `maintenance_io_concurrency = 16` (PG18 defaults).
- Benchmark `REFRESH MATERIALIZED VIEW CONCURRENTLY` with AIO enabled vs. PG17 baseline.
- Benchmark `FOR UPDATE SKIP LOCKED` claim query on `identity_scan_job_items` (1K+ pending rows).
- Benchmark cosine-similarity centroid search on `mv_identity_cluster_centroids`.
- Document results.

Exit criteria:

- MV refresh latency is equal or better than PG17 baseline on identical dataset.
- No increase in p99 latency for centroid search queries.
- Benchmark results documented in `docs/` directory.

### Phase 4: Test Infrastructure Simplification

**Goal**: Use `--no-policies` pg_dump to eliminate the `is_sqlite()` branching in test infrastructure.

Deliverables:

- Generate RLS-free schema dump for test fixtures via `pg_dump --no-policies`.
- Evaluate replacing SQLite test backend with PG18 test database (using `--no-policies` schema).
- Remove or reduce `is_sqlite()` checks in `recognition/shared/db/dialect.py` and `db/tenant_context.py`.
- Update CI pipeline to use PG18 test container.

Exit criteria:

- `is_sqlite()` function has zero callsites (or is documented as deprecated).
- Test suite runs against PG18 with RLS-free test schema.
- CI pipeline green on PG18.

### Phase 5: Exploit RETURNING OLD/NEW & Virtual Generated Columns

**Goal**: Reduce application-side query count by using PG18 DML RETURNING enhancements and virtual generated columns.

Deliverables:

- Refactor `scan_queue_repository.py` claim CTE to use `RETURNING OLD.status, NEW.status, NEW.updated_at` — eliminate follow-up SELECT.
- Identify candidate computed columns for virtual generation (e.g., `identity_count > 0` flags, embedding dimension validation).
- Add virtual generated columns via Alembic migration for selected candidates.
- Update SQLAlchemy ORM mappings to mark virtual generated columns as `server_default` / read-only.

Exit criteria:

- Claim query issues a single round-trip (UPDATE … RETURNING OLD/NEW) instead of CTE + implicit re-read.
- At least one virtual generated column is in production use.

## External Dependencies

| Dependency | Owner | Status | Blocks |
|---|---|---|---|
| `pgvector/pgvector:pg18` Docker image | pgvector maintainers | Check — PG18 GA was 2025-09-25; image likely available | Phase 1 |
| asyncpg PG18 wire protocol 3.2 support | MagicStack (asyncpg) | Check — asyncpg ≥0.31 should negotiate 3.0 fallback | Phase 1 |
| SQLAlchemy PG18 dialect compatibility | SQLAlchemy project | Likely transparent (dialect is version-agnostic) | Phase 1 |
| psycopg PG18 support | psycopg project | Check — psycopg ≥3.1 | Phase 1 |

## Code Anchors

| Layer | File | Note |
|---|---|---|
| Infra | `apps/prototype-description-service/docker-compose.db.yml` | Image tag `pgvector/pgvector:pg17` → `pg18` |
| Infra | `apps/prototype-description-service/db/docker-init/001-extensions.sql` | Drop `uuid-ossp`; keep `citext`, `pgcrypto`, `vector` |
| Infra | `apps/prototype-description-service/db/docker-init/010-create-test-role.sql` | Verify test role works under PG18 |
| DB | `apps/prototype-description-service/db/settings.py` | DSN construction; pool config; pgvector dimension |
| DB | `apps/prototype-description-service/db/session.py` | Async engine creation; verify asyncpg compatibility |
| DB | `apps/prototype-description-service/db/tenant_context.py` | RLS session var management; `is_sqlite()` checks |
| DB | `apps/prototype-description-service/db/models/tenant.py` | Tenant model; UUID PK default |
| DB | `apps/prototype-description-service/db/models/identity.py` | ClusterCentroid MV mapping; UUID PKs |
| DB | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Baseline schema (1087 lines); RLS policies; MV creation; triggers |
| Repo | `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | `refresh_centroids_view()` / `refresh_centroids_view_concurrent()` |
| Repo | `apps/prototype-description-service/recognition/infrastructure/repositories/scan_queue_repository.py` | `FOR UPDATE SKIP LOCKED` claim CTE; RETURNING refactor target |
| Shared | `apps/prototype-description-service/recognition/shared/db/dialect.py` | `is_sqlite()` detection; removal target |
| Auth | `apps/prototype-description-service/recognition/config/security.py` | Auth settings; future OAuth integration point |
| Auth | `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py` | `require_auth` FastAPI dependency |

## Risks and Mitigations

- **Risk**: pgvector extension not yet packaged for PG18.
  Mitigation: Build from source against PG18 dev headers; pgvector has historically shipped PG-major-version images within weeks of GA.

- **Risk**: asyncpg incompatibility with PG18 wire protocol 3.2 changes (256-bit cancel keys).
  Mitigation: asyncpg negotiates protocol version; 3.0 fallback is automatic. Pin asyncpg ≥0.31 which handles unknown protocol messages gracefully.

- **Risk**: `AFTER` trigger role-change semantics break dirty-tracking queue inserts.
  Mitigation: This change actually *fixes* a latent bug — triggers now fire as the DML-issuing role, which has `app.current_tenant` set. Test with explicit role switching.

- **Risk**: `uuidv7()` temporal ordering changes index-scan behavior on existing UUIDv4 data.
  Mitigation: UUIDv7 and UUIDv4 coexist in the same column; btree ordering is unchanged (lexicographic on 128 bits). Mixed v4/v7 rows are harmless.

- **Risk**: Data checksum enforcement on `pg_upgrade` requires matching checksum settings.
  Mitigation: Use `initdb --no-data-checksums` if upgrading from non-checksum PG17 cluster, or enable checksums on PG17 first via `pg_checksums`.

## Success Metrics

- Transaction safety parameters configured — **server-side defense** against `InFailedSQLTransactionError` cascading failure class (Phase 0, PG17).
- `uuid-ossp` extension eliminated — **1 fewer C extension** to maintain across upgrades.
- `is_sqlite()` branching removed — estimated **~40 LOC** removed from `tenant_context.py` and `dialect.py`.
- Scan-job claim query reduced from **2 round-trips to 1** via `RETURNING OLD/NEW`.
- MV refresh latency **equal or improved** vs. PG17 baseline (AIO benefit).
- `docker-compose.db.yml` image tag updated — **1 line change** for core upgrade.
- Test suite passes on PG18 with **zero** RLS-specific SQLite workarounds.
- Post-upgrade `ANALYZE` pass eliminated — **~30s saved** per deployment (pg_upgrade preserves stats).
- Data checksums enabled — **silent corruption detection** with no runtime overhead.

---

# Consolidated Checklist

## Phase 0: PG17 Safety Parameter Configuration

- [ ] Add `statement_timeout` to session dependency via `SET LOCAL` (default: `10s`)
- [ ] Add `idle_in_transaction_session_timeout` to session dependency via `SET LOCAL` (default: `30s`)
- [ ] Add `transaction_timeout` to PostgreSQL server config (default: `60s`)
- [ ] Add env-var overrides (`DB_STATEMENT_TIMEOUT`, `DB_IDLE_IN_TXN_TIMEOUT`, `DB_TRANSACTION_TIMEOUT`)
- [ ] Guard timeout configuration with `is_postgres()` for SQLite test sessions
- [ ] Verify with integration test: deliberately stalled transaction is terminated after timeout
- [ ] Existing test suite passes

## Phase 1: Compatibility Verification & Upgrade

- [ ] Verify pgvector PG18 image availability
- [ ] Update `docker-compose.db.yml` image tag to `pg18`
- [ ] Run `pg_upgrade --check` against current schema
- [ ] Execute upgrade and validate data integrity
- [ ] Run full test suite on PG18
- [ ] Validate RLS policies and session variable behavior
- [ ] Benchmark critical queries (centroid search, job claim, cluster list)

## Phase 2: UUIDv7 Migration

- [ ] Alembic migration: replace `uuid_generate_v4()` defaults with `uuidv7()` on all PK columns
- [ ] Remove `uuid-ossp` from `001-extensions.sql`
- [ ] Verify no Python-side UUID generation bypasses DB defaults
- [ ] Confirm IVFFlat and btree indexes are unaffected
- [ ] Validate coexistence of UUIDv4 and UUIDv7 rows

## Phase 3: AIO & Performance Configuration

- [ ] Configure `io_method` in PostgreSQL configuration
- [ ] Set I/O concurrency parameters to PG18 defaults
- [ ] Benchmark MV refresh (concurrent) on representative dataset
- [ ] Benchmark claim query throughput
- [ ] Benchmark centroid cosine-similarity search
- [ ] Document benchmark results

## Phase 4: Test Infrastructure Simplification

- [ ] Generate RLS-free test schema via `pg_dump --no-policies`
- [ ] Migrate test backend from SQLite to PG18 test container
- [ ] Remove `is_sqlite()` checks from `dialect.py` and `tenant_context.py`
- [ ] Update CI pipeline to PG18

## Phase 5: RETURNING OLD/NEW & Virtual Generated Columns

- [ ] Refactor claim CTE in `scan_queue_repository.py` with `RETURNING OLD/NEW`
- [ ] Identify virtual generated column candidates
- [ ] Alembic migration for virtual generated columns
- [ ] Update ORM mappings for virtual columns

## Deferred (Post-v0.1)

### D1: OAuth DB-Level Authentication

- [ ] Configure `pg_hba.conf` with `oauth` authentication method
- [ ] Implement `oauth_validator_libraries` token validation module
- [ ] Map JWT claims to PostgreSQL roles for per-tenant DB sessions
- [ ] Replace or augment API-key auth with OAuth bearer flow end-to-end

**PG18 feature**: Native `oauth` method in `pg_hba.conf` + `oauth_validator_libraries` server variable.

**Rationale for deferral**: The current API-key hash-lookup mechanism (`auth.py` → `api_keys` table → `SET LOCAL app.current_tenant`) is functional and well-tested. OAuth DB-level auth requires designing a JWT-to-DB-role mapping strategy, which has implications for the WordPress plugin's authentication flow (PHP → Python API → DB). That design work spans multiple layers and is out of scope for a database-version upgrade. Additionally, `oauth_validator_libraries` requires a custom shared library for token validation — a non-trivial build/deploy dependency.

**When to revisit**: When the plugin layer adopts OAuth/OIDC for user authentication and a JWT is available at the API boundary, enabling direct claim-to-role passthrough.

**Affected code**: `recognition/config/security.py`, `recognition/interface_adapters/http/deps/auth.py`, `db/docker-init/` (pg_hba.conf template).

---

### D2: Temporal Constraints (WITHOUT OVERLAPS)

- [ ] Add validity range columns (`valid_from`, `valid_to`) to `identity_members`
- [ ] Apply `PRIMARY KEY (cluster_id, identity_id, valid_range) WITHOUT OVERLAPS`
- [ ] Migrate join/leave history from event log to temporal membership table
- [ ] Add `PERIOD` foreign key from `identity_members` to `identity_clusters`

**PG18 feature**: Temporal `PRIMARY KEY` and `UNIQUE` constraints with `WITHOUT OVERLAPS`; `PERIOD` foreign keys.

**Rationale for deferral**: The `identity_members` table currently models point-in-time membership (an identity belongs to exactly one cluster; reassignment is a delete+insert). There is no temporal dimension — no `valid_from`/`valid_to` range tracking membership history. Adopting temporal constraints requires a fundamental data-model change (from current-state to bi-temporal) that is a feature decision, not an upgrade consequence. The constraint infrastructure is valuable but blocked on a product decision about whether membership history needs to be queryable.

**When to revisit**: When cluster-membership audit trails or undo/redo of clustering decisions are required.

**Affected code**: `db/models/identity.py` (`IdentityMember` model), `001_identity_schema.py`, `cluster_repository.py`.

---

### D3: Non-Btree Unique Indexes on Materialized Views

- [ ] Evaluate HNSW or other equality-supporting index types as MV unique index
- [ ] Benchmark HNSW unique index vs. btree unique index on `mv_identity_cluster_centroids`
- [ ] Test `REFRESH MATERIALIZED VIEW CONCURRENTLY` with non-btree unique index

**PG18 feature**: Non-btree unique indexes (any index type supporting equality) can now serve as the required unique index for `REFRESH MATERIALIZED VIEW CONCURRENTLY` and as partition keys.

**Rationale for deferral**: The current btree unique index on `cluster_id` is functionally correct and performant. The IVFFlat cosine index on the `centroid` column serves vector search. Replacing the btree unique index with an HNSW unique index would only be beneficial if the unique-index column itself needed approximate nearest-neighbor search — which `cluster_id` (a UUID) does not. The feature is architecturally interesting but has no concrete use case in the current schema.

**When to revisit**: If a future MV requires a unique index on a column that also benefits from a non-btree access method (e.g., a GiST range-type unique index for spatial clustering MVs).

**Affected code**: `001_identity_schema.py` (MV index definitions), `cluster_repository.py` (concurrent refresh).

---

### D4: SCRAM Passthrough for Federated Authentication

- [ ] Configure `postgres_fdw` with `use_scram_passthrough` option
- [ ] Evaluate `dblink` SCRAM passthrough for cross-database queries
- [ ] Remove stored credentials from foreign server definitions

**PG18 feature**: SCRAM authentication passthrough from client to `postgres_fdw` and `dblink` servers, avoiding stored credentials in the database.

**Rationale for deferral**: The current architecture has no `postgres_fdw` or `dblink` usage. All data resides in a single PostgreSQL instance with a shared-schema multitenancy model. Federated authentication is irrelevant until the architecture splits into multiple databases (e.g., per-tenant databases, read replicas with foreign data wrappers, or cross-service DB queries).

**When to revisit**: If the architecture adopts database-per-tenant isolation or cross-service database federation.

**Affected code**: None currently; would require new `postgres_fdw` infrastructure.

---

### D5: NUMA Awareness

- [ ] Build PostgreSQL with `--with-libnuma`
- [ ] Monitor shared memory distribution via `pg_shmem_allocations_numa`
- [ ] Monitor buffer cache distribution via `pg_buffercache_numa`
- [ ] Tune memory allocation for NUMA topology

**PG18 feature**: `--with-libnuma` configure option; `pg_numa_available()` function; `pg_shmem_allocations_numa` and `pg_buffercache_numa` system views.

**Rationale for deferral**: The prototype runs in Docker containers, typically on single-socket developer machines or small cloud instances where NUMA topology is either absent or irrelevant. NUMA optimisation yields measurable gains on multi-socket bare-metal servers with large shared_buffers (32GB+). The current `shared_buffers` configuration is modest (Docker default) and NUMA-unaware allocation has negligible performance impact.

**When to revisit**: If the service is deployed on bare-metal multi-socket servers or large cloud instances (e.g., `x2idn.metal`) where NUMA-local memory access matters.

**Affected code**: `docker-compose.db.yml` (would require custom PostgreSQL build), `db/settings.py` (monitoring queries).

---

### D6: NOT ENFORCED Constraints for Soft Validation

- [ ] Identify candidate constraints for `NOT ENFORCED` (e.g., cross-tenant referential integrity)
- [ ] Add `NOT ENFORCED` CHECK constraints as documentation of data expectations
- [ ] Add `NOT ENFORCED` foreign keys for query planner hints without enforcement overhead

**PG18 feature**: `CHECK` and `FOREIGN KEY` constraints can be declared `NOT ENFORCED`, providing query-planner hints and schema documentation without runtime validation cost.

**Rationale for deferral**: The current schema uses enforced constraints throughout, and the data integrity guarantees are intentional. `NOT ENFORCED` constraints are most valuable in data-warehouse or ETL scenarios where constraints serve as planner hints but data arrives pre-validated. The prototype's insert patterns are low-volume and benefit from strict enforcement. Adopting `NOT ENFORCED` would require a deliberate shift in validation strategy (move to application-layer validation) that is not motivated by current performance or design needs.

**When to revisit**: If bulk-import pipelines (e.g., batch face-detection results from external systems) need to bypass FK validation for throughput, then `NOT ENFORCED` FKs with application-level validation become attractive.

**Affected code**: `001_identity_schema.py` (constraint definitions), any future bulk-import scripts.

---

### D7: `COPY TO` from Materialized Views

- [ ] Use `COPY mv_identity_cluster_centroids TO ...` for centroid export
- [ ] Replace Python-side CSV serialisation of centroid data with server-side COPY

**PG18 feature**: `COPY TO` can now copy rows directly from populated materialized views.

**Rationale for deferral**: There is currently no export/backup workflow for materialized view data. The MV is refreshed on-demand and consumed via ORM queries. A `COPY TO` path would be useful for offline analysis or data-science pipelines that need centroid snapshots, but no such pipeline exists yet.

**When to revisit**: When centroid data needs to be exported for external analysis, model training, or cross-environment data transfer.

**Affected code**: Would require new export scripts; `cluster_repository.py` could gain a `export_centroids()` method.

---

### D8: `log_lock_failures` for Concurrency Observability

- [ ] Enable `log_lock_failures` in PostgreSQL configuration
- [ ] Monitor `NOWAIT` lock failures on `FOR UPDATE SKIP LOCKED` queries
- [ ] Correlate lock failure logs with claim-queue contention metrics

**PG18 feature**: `log_lock_failures` server variable logs `SELECT ... NOWAIT` lock acquisition failures.

**Rationale for deferral**: The current `FOR UPDATE SKIP LOCKED` pattern does not use `NOWAIT` — it uses `SKIP LOCKED`, which silently skips locked rows rather than failing. `log_lock_failures` is therefore not directly applicable. If the concurrency model evolves to use `NOWAIT` semantics (fail-fast instead of skip), this becomes a valuable observability tool.

**When to revisit**: If worker claim patterns change from `SKIP LOCKED` to `NOWAIT`, or if advisory locks are introduced for other contention scenarios.

**Affected code**: `scan_queue_repository.py` (claim CTE), PostgreSQL configuration.

---

### D9: PostgREST for Read-Path Backend Simplification

- [ ] Evaluate PostgREST compatibility with existing RLS policies and `SET LOCAL app.current_tenant` pattern
- [ ] Identify read-only endpoints that can be served directly from PostgreSQL views via PostgREST
- [ ] Prototype a single read endpoint (e.g., `GET /clusters`) via PostgREST and compare with Python/SQLAlchemy equivalent
- [ ] Evaluate JWT-to-PostgreSQL-role mapping for PostgREST auth integration with existing API-key mechanism
- [ ] Benchmark read-path latency: PostgREST direct vs. Python/SQLAlchemy/asyncpg

**What PostgREST is**: A standalone Haskell server that auto-generates a RESTful API from PostgreSQL schema (tables, views, stored functions). It uses PostgreSQL's own RLS for row-level security, manages its own connection pool with proper transaction boundaries, and authenticates via JWT claims mapped to PostgreSQL roles.

**What it would replace**: For read-path endpoints, PostgREST would eliminate the entire Python session lifecycle layer (`db/session.py`, `deps/session.py`, `db/tenant_context.py`) — the exact surface that produced the `InFailedSQLTransactionError` cascading failure documented in the [session lifecycle assessment](../assessment/infailed-sql-transaction-investigation-2026-04-09.md). PostgREST does not use an ORM; it issues SQL directly against views and functions, with transaction boundaries managed by PostgreSQL itself.

**Why PG18 makes PostgREST more attractive:**

| PG18 Feature | PostgREST Benefit |
|---|---|
| `--no-policies` pg_dump | Test/CI schema generation for PostgREST-served views without RLS complexity |
| AFTER trigger role semantics | PostgREST-initiated DML through writable views fires triggers under the correct tenant role |
| UUIDv7 | Time-ordered PKs enable efficient cursor-based pagination in PostgREST without `ORDER BY created_at` |
| Virtual generated columns | Computed fields (e.g., cluster staleness, identity counts) are exposed by PostgREST automatically without application code |
| Skip scan | Multi-column indexes on `(tenant_id, ...)` benefit PostgREST reads that filter on non-leading columns |
| RETURNING OLD/NEW | Writable PostgREST endpoints (if adopted) can return pre/post state in a single round-trip |

**Candidate read-path endpoints for PostgREST:**

| Current Python Endpoint | PostgREST Equivalent | Complexity |
|---|---|---|
| `GET /recognition/clusters` | PostgreSQL view `v_clusters` with RLS | Low — direct table/view read |
| `GET /recognition/identities` | PostgreSQL view `v_identities` with joins | Low — view with identity_members join |
| `GET /recognition/jobs/{id}` | PostgreSQL view `v_scan_jobs` | Low — single-row lookup |
| `GET /recognition/clusters/{id}/members` | PostgreSQL view `v_cluster_members` | Low — filtered view |
| `GET /recognition/tenants/{id}` | Direct table read with RLS | Trivial |

**Endpoints that CANNOT move to PostgREST:**

| Python Endpoint | Reason |
|---|---|
| `POST /recognition/analyze` | Complex business logic: face recognition, embedding generation, scan job creation, file handling |
| `POST /recognition/scan` | Background task scheduling, worker dispatch |
| `POST /recognition/clusters/refresh` | Materialized view refresh orchestration |
| `POST /recognition/identities/merge` | Multi-step clustering mutation with constraint validation |

**Cost/benefit assessment:**

Benefits:
- **Eliminates session lifecycle bugs on read paths.** The `InFailedSQLTransactionError` bug class is structurally impossible in PostgREST because it manages its own connection pool with single-owner transaction boundaries.
- **Reduces Python backend feature surface.** ~5 read controllers, their dependencies, and their test infrastructure can be replaced by PostgreSQL views + PostgREST configuration.
- **Reduces infrastructure complexity long-term.** PostgREST serves read traffic without Python process overhead (no asyncio event loop, no SQLAlchemy ORM, no greenlet bridge for async). Read scaling becomes a PostgreSQL + PostgREST scaling problem, separate from the Python compute service.
- **Performance.** PostgREST issues SQL directly without ORM overhead. For simple reads, latency is bounded by PostgreSQL query execution, not by Python/asyncpg/SQLAlchemy layers.
- **PG18 synergy.** Multiple PG18 features (virtual generated columns, skip scan, UUIDv7 pagination, trigger role semantics) make PostgREST-served views richer without application code changes.

Costs:
- **Split architecture.** The API surface would be served by two backends: PostgREST for reads, Python for writes. The WordPress plugin must route requests to the correct backend (or a reverse proxy/API gateway must route based on method + path).
- **Auth integration.** PostgREST uses JWT; the current backend uses API-key hash lookup. A JWT bridge or shared auth layer is required. PG18's native OAuth support (D1) could simplify this but is itself deferred.
- **Two API conventions.** PostgREST uses its own URL query syntax (e.g., `?tenant_id=eq.{uuid}&select=id,name`) which differs from the current REST conventions. The frontend would need adapter code or the reverse proxy would need to translate.
- **Operational overhead.** A new service (PostgREST binary + config) must be deployed, monitored, and version-managed alongside the Python service.
- **View maintenance.** PostgreSQL views must be created and maintained (via Alembic migrations or separate DDL) to serve the read endpoints. Schema changes require updating both the views and any PostgREST configuration.

**Rationale for deferral**: The session lifecycle assessment's P0 fix (flatten session lifecycle to single-owner pattern) resolves the `InFailedSQLTransactionError` root cause in ~100 LOC without architectural upheaval. The prototype has no production users and no read-traffic scaling pressure. PostgREST adoption is a significant architecture change that should be evaluated after: (a) the session lifecycle fix is verified, (b) read traffic patterns are understood from real usage, and (c) PG18 is deployed (to benefit from the synergies listed above).

**When to revisit**: When the prototype transitions to production use and read traffic dominates write traffic, OR when the Python session lifecycle continues to produce connection-management bugs despite the P0 fix, indicating that the ORM layer itself is a structural liability.

**Affected code**: All files in `recognition/interface_adapters/http/routers/` (read endpoints), `recognition/interface_adapters/http/deps/session.py` (read-path session management), `db/models/` (view definitions), `docker-compose.db.yml` (PostgREST service), `recognition/config/security.py` (JWT auth bridge).

---

### D10: PostgreSQL Logical Replication for Read/Write Pool Separation

- [ ] Evaluate `CREATE PUBLICATION` / `CREATE SUBSCRIPTION` for streaming read replicas
- [ ] Configure PostgREST (if adopted, see D9) to connect to read replica
- [ ] Evaluate `synchronous_commit = off` for write-heavy scan-job paths

**PG18 feature**: Logical replication improvements (subscription failover, improved slot management).

**Rationale for deferral**: The current architecture uses a single PostgreSQL instance. Read/write separation via logical replication only becomes valuable when read traffic exceeds what a single instance can serve, or when read availability must be isolated from write-path failures. Neither condition exists for the prototype.

**When to revisit**: When the PostgREST evaluation (D9) is underway and read-path scaling is a concrete concern, or when write-heavy operations (batch clustering, MV refresh) need to be isolated from read latency.

**Affected code**: `docker-compose.db.yml` (replica instance), `db/settings.py` (read-replica DSN), PostgREST configuration (if D9 is adopted).

## Success Criteria

- [ ] PG17 safety parameters (`statement_timeout`, `idle_in_transaction_session_timeout`, `transaction_timeout`) are configured and verified (Phase 0).
- [ ] All services run on PostgreSQL 18 with pgvector in development and CI.
- [ ] `uuid-ossp` extension is fully removed.
- [ ] Test suite runs against PG18 without SQLite RLS workarounds.
- [ ] Benchmark data shows no performance regressions; MV refresh and claim queries are equal or faster.
- [ ] At least one `RETURNING OLD/NEW` refactor is merged and reduces round-trips.
