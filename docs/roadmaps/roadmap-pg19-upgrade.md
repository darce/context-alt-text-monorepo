# PostgreSQL 17 → 19 Upgrade Evaluation (v0.2)

> **FIR follow-up, 2026-09-19:** the [FIR development assessment](../assessments/current/fir-development-wave-assessment-2026-09-19.md#would-postgresql-19-help-fir) finds no PG19 dependency for 128D SFace or occlusion work. E24 retains PG17 with a supported patched minor; §11 below remains the canonical major-upgrade policy.

> **Status:** Evaluation re-run 2026-09-16 under task `PG19-1`. Supersedes [roadmap-pg18-upgrade.md](roadmap-pg18-upgrade.md) (v0.1, PG17→18, April 2026).
> **Target:** PostgreSQL 19 — beta 3 released 2026-08-13; GA not yet dated. PG18 GA'd 2025-09-25 and is skipped as an intermediate hop.
> **Verdict:** **Skip 18. Upgrade 17 → 19 in one hop.** Hard gates: PG19 GA, PG19 minor **≥ 19.1** (never `19.0`), a **pinned** arm64 `pgvector/pgvector:pg19` image digest that passed the dump/restore rehearsal, and one product trigger (§11). Build nothing against the beta. This document's §11 is the **only** canonical timing/trigger policy. Now: take the 17.11 minor (28 CVEs), finish the PG-independent items already half-done (§7 "Now"), keep the demo-launch freeze from the portfolio-quadrant assessment intact.

Paths below are relative to `apps/prototype-description-service/` unless they start with `infra/` or `docs/`.

---

## 0. What changed since v0.1

| v0.1 (April 2026) | Now (2026-09-16) |
|---|---|
| PG18 was the only shipped major above 17 | PG19 beta 3; every PG18 feature v0.1 planned around is carried into 19 (UUIDv7, AIO, skip scan, RETURNING OLD/NEW, virtual generated columns, `--no-policies`, non-btree MV unique index, OAuth, temporal PK) |
| Phase 0 (session timeouts) planned | **Done**: `_apply_postgres_session_safety_settings` issues `SET LOCAL statement_timeout` / `idle_in_transaction_session_timeout` from `DB_STATEMENT_TIMEOUT` / `DB_IDLE_IN_TXN_TIMEOUT` (`recognition/interface_adapters/http/deps/session.py:46-59`; `DatabaseSettings.statement_timeout` / `idle_in_txn_timeout` at `db/settings.py:42-43`, env reads at `db/settings.py:286-287`). Server-level `transaction_timeout` still unset |
| Phase 2 UUIDv7 via `uuidv7()` server default | **Half done app-side**: `recognition/shared/ids.py::generate_id` emits UUIDv7 (`test_generate_id_is_uuidv7`). `uuid_generate_v4()` has **zero** call sites; `uuid-ossp` is created by both `001-extensions.sql` files and used by nothing. In-scope `uuid.uuid4()` migrations are the named get-or-insert sites only (§6 rows 4, 7; §14). Remaining `uuid.uuid4` call sites stay out of scope |
| PG tests were a future phase | `pg` marker exists in 6 files (`test_identity_schema_heal_fakeop.py`, `test_identity_schema_heal_pg.py`, `test_identity_schema_pg.py`, `test_provision_customer_pg.py`, `test_scan_queue_claim_backoff_pg.py`, `test_identity_suggestions_batch_pg.py`). Grep: `is_sqlite(` 17 hits, `is_postgres(` 23 hits including tests |
| Upgrade timing open | Frozen by product docs: portfolio-quadrant cut list "PG18 upgrade → Phase 0 only, until any production data exists"; local-AI roadmap §4.2 defers "PG18 upgrade" until after Phase 0–1 GTM gates. **This evaluation changes the target and the trigger set, not the freeze.** Triggers do not bypass that freeze except a PG17-unavailable security fix (§11 / P2 exception) |
| pg_durable evaluated separately | Its reason 6 ("No PG19 path") and "PG19: track, do not build" now point here |

Why one hop, not two: 17→18→19 is two major-hop windows, two pgvector image waits, two compatibility sweeps, for zero feature PG19 does not also give. [CARD-15] *"Prefer the cheap reversible option while the irreversible path is underpriced"* — the cheap option is to stay on 17.11 and wait; the underpriced one is a major upgrade onto a beta or onto `19.0`.

## 1. Inputs

- PostgreSQL 19 documentation ([docs/19](https://www.postgresql.org/docs/19/index.html)), release notes, and the [18.6 / 17.11 / 16.15 / 15.19 / 14.24 + 19 beta 3 announcement](https://www.postgresql.org/about/news/postgresql-186-1711-1615-1519-1424-and-19-beta-3-released-3365/).
- Prior art from the handoff DB (keyword + semantic, 15 hits). Relevant: E15-33 #1775 advisory-lock PG-only gap; GPUFLOW-1 #14244 `SKIP LOCKED` sqlite-only gap; E15-34 `pg` marker / `pg_migrated_engine` / `acx_identity_test` / `IDENTITY_PG_ADMIN_URL`; xdist-unsafe scratch DB names; UXP-2 `DISTINCT ON` portability; AP-7 RLS-bypass tests; MAINT-FIR-FINAL2 `enable_rls_bypass` after rollback.
- Codemap (`codebase-memory-mcp`) symbol graph for the impact map (§6); line ranges below were re-verified with `grep -n` on 2026-09-16.
- Heuristics canon `~/Development/heuristics-canon-research` (`lexicons/engineering.md`, `reasoning/*.md`); citations in §8 carry id + path + verbatim line. Release It! (rollback before rollout, bulkheads) and DDIA (schema/encoding evolution, restore-as-proof) change the Phase 1 method.
- Planned-feature roadmaps: [local-ai-managed-default-roadmap-2026-07-31.md](local-ai-managed-default-roadmap-2026-07-31.md) §4.2/§5, [context-aware-image-description-roadmap-2026-06-13.md](context-aware-image-description-roadmap-2026-06-13.md), [portfolio-quadrant assessment](../assessments/current/portfolio-quadrant-mvp-strategy-assessment-2026-06-11.md) (video = Oyster, one-week probe post-demo), commercial-face assessment (track-level medoid aggregation, video companion guide), [caption-context assessment §8](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md).

## 2. Current state (2026-09-16)

- Image `pgvector/pgvector:pg17` in `docker-compose.db.yml:3`, `docker-compose.env.yml:22`, `docker-compose.prod.yml:22`. Extensions `uuid-ossp`, `citext`, `pgcrypto`, `vector` in `db/docker-init/001-extensions.sql` and `db/docker-prod-init/001-extensions.sql`. Neither init file nor any compose `command:` enables `pg_stat_statements` or `shared_preload_libraries`.
- Pins: `sqlalchemy[asyncio]>=2.0.44` (lock 2.0.49), `asyncpg>=0.31.0,<0.33.0` (lock 0.31.0), `psycopg[binary]>=3.1.0` (lock 3.3.4), `pgvector>=0.5.0` (lock 0.5.0), `alembic>=1.17.0`.
- Prod: OCI `VM.Standard.A1.Flex`, 4 OCPU / 24 GB, aarch64 (`infra/oci/main.tf:204-208`). Disk healthcheck is **not** universal: only `docker-compose.env.yml:29` checks `ACX_PG_DISK_MAX_USED_PCT`; `docker-compose.db.yml:12` and `docker-compose.prod.yml:29` run `pg_isready` only. That compose check is **not** the REPACK guard.
- Tenancy: `FORCE ROW LEVEL SECURITY` + `app.current_tenant` / `app.bypass_rls` GUCs (`db/tenant_context.py`), pool-checkout reset listener.
- Queue: `FOR UPDATE SKIP LOCKED` claim CTE (`scan_queue_repository.py:353-410`). MV `mv_identity_cluster_centroids` (ivfflat cosine, `001_identity_schema.py:2637-2691`) refreshed concurrently under a disk-headroom probe (`cluster_repository.py:147-207`, `required_bytes = max(min_bytes, 2 * mv_bytes)`).
- Bloat reclaim: **none**. No `VACUUM FULL`, `CLUSTER`, `REPACK`, or `pg_repack` anywhere in app code, ops docs, or runbooks. Retention purge deletes rows; nothing returns space.
- No `LISTEN`/`NOTIFY`, no `inet`/`cidr` columns, no `postgres_fdw`, no logical replication, no `wal_level` override in compose.
- PG-side config: none beyond image defaults (no `postgresql.conf` overlay, no `POSTGRES_INITDB_ARGS`). JIT, autovacuum, io workers all at defaults.

## 3. PG19 beta 3 feature ingest → fit

Legend: **S** simplifies code that exists · **O** ops/observability gain, config only · **F** free (no change) · **P** planned-feature option (§5) · **N** not applicable.

Every PG19-specific interface in this table is **PG19 beta 3 — verify against final release notes at the GA gate**. No phase may rely on the name or default until the matching §13 GA-gate item is ticked.

| Feature (PG19) | Fit | Where it lands | Note |
|---|---|---|---|
| `INSERT … ON CONFLICT DO SELECT [FOR …] … RETURNING` | **S** | `description_repository.py:50-69` `insert_or_get_existing`; `member_repository.py:80-120` `add_member_if_not_exists`, `:152-229` `bulk_add_members_if_not_exists`; `assignment_writer.py:284-517` `persist_assignment` / `persist_assignments_chunk` / `_apply_joint_uniqueness_guard`; `describe_run_repository.py:151-211` `create_run` + `describe_run.py:375` `_replay_or_conflict` (IntegrityError on `uq_image_description_runs_idempotency_key`) | Get-or-insert sites collapse from 2–3 statements to one. Needs SQLAlchemy construct or `text()`; not in 2.0.49. **Not a site:** `routers/describe.py:717` `DescribeOperationRepository.accept` (`describe_operation_repository.py:67`) inserts a new UUID and has no conflict / get-or-insert path. `create_single_run` (`describe_run_repository.py:213`) has no idempotency unique path. **PG19 beta 3 — verify against final release notes at the GA gate** |
| `REPACK` / `REPACK CONCURRENTLY` (`max_repack_replication_slots`) | **S/O** | `media_identities`, `image_descriptions`, `identity_scan_job_items`, `identity_members`, `recognition_events`, `audit_events` | First online bloat-reclaim path. Needs `wal_level=logical` set **persistently at the PG19 cutover restart** (Phase 1) + one slot + free space ≥ 2× (table + indexes); the REPACK Make target does its own precheck and refuses otherwise. **PG19 beta 3 — verify against final release notes at the GA gate** |
| Parallel autovacuum (`autovacuum_max_parallel_workers`, per-table `autovacuum_parallel_workers`) + `pg_stat_autovacuum_scores` | **O** | `media_identities`, `identity_scan_job_items` | 4 OCPU host; scan bursts write then idle. Scores view answers "is autovacuum keeping up" without guessing. **PG19 beta 3 — verify against final release notes at the GA gate** (`pg_stat_autovacuum_scores`) |
| I/O worker auto-scaling (`io_min_workers`, `io_max_workers`, `io_worker_idle_timeout`, `io_worker_launch_interval`) | **F** | image defaults | Removes the v0.1 Phase 3 tuning question; burst/idle pattern handled by defaults. **PG19 beta 3 — verify against final release notes at the GA gate** |
| Faster FK checks, `NOT IN` → anti-join, VM marking during scans, radix sort, SIMD `COPY` | **F** | MV refresh aggregate, tenant FK fan-out on every table | Measure, don't assume [PERF-06] |
| `log_lock_waits` default **on**, `pg_stat_lock`, `log_min_messages` per process type | **O** | `clusters_admission.py:164-199` `_acquire_tenant_lock_fast_fail` (`SET LOCAL statement_timeout` + `FOR UPDATE` → 503); `gpu_intent.py:174` `_acquire_gpu_intent_lock` (file lock); `sync_identity_schema.py:49,79` `pg_advisory_xact_lock`; claim CTE | Supersedes v0.1 D8 (`log_lock_failures` never applied to `SKIP LOCKED`). **PG19 beta 3 — verify against final release notes at the GA gate** |
| Online data-checksum enable/disable | **O** | post-upgrade | Enable after the hop; dump/restore does not inherit the v0.1 "checksum mismatch on pg_upgrade" window |
| `EXPLAIN ANALYZE` IO stats, `pg_stat_statements` FETCH sizes + plan counts, `pg_stat_recovery`, `stats_reset` | **O** | Phase 1 baseline diff **after** the §7 Now enablement | Plan-count column makes the JIT-default flip auditable. Extension is not loaded today |
| `pg_plan_advice` / `pg_stash_advice` | **N** now | — | Revisit only if a plan regression appears post-hop |
| `WAIT FOR` (read-your-writes on standby) | **N** | D10 | No replica |
| `FOR PORTION OF` (temporal `UPDATE`/`DELETE`) | **P** | D2 + video track segments | First concrete consumer would be video tracks |
| SQL/PGQ property graphs | **P** | `discovery/graph/discovery.py`, `constraint_repository.py`, `clusters_topology.py`, future track↔identity graph | Park until ≥2 consumers [REF-12] |
| `CHECK … NOT ENFORCED` | **N** | D6 | Unchanged rationale |
| `COPY TO … (FORMAT json)`, `ON_ERROR SET_NULL` | **P** | D7 export, description-run export | Management/export surface |
| Logical replication: sequences, `ALL SEQUENCES`, `EXCEPT`, `retain_dead_tuples`, `effective_wal_level` | **N** | D10 | |
| OAuth: validator-module chapter, hba options, libpq `oauth_ca_file` | **N** | D1 | Deferral unchanged |
| `pg_get_role_ddl` / `pg_get_tablespace_ddl` / `pg_get_database_ddl`, `pg_dump` extended stats, `vacuumdb --dry-run`, pg_upgrade LO/tablespace | **O** | Phase 1 probe | `pg_upgrade --check` and `vacuumdb --dry-run` are compatibility probes only; they are not the hop |
| jsonpath string methods, `bytea`↔`uuid` casts, base64url, `error_on_null()`, `oid8`, `btree_gin` cross-type | **N** | — | Nice-to-have; no caller |
| `NOTIFY` wakes only listeners | **N** | — | No `LISTEN`/`NOTIFY` in code |
| Server-side SNI (`pg_hosts.conf`), libpq `servicefile` | **N** | — | Single host behind Caddy |
| `GROUP BY ALL` | — | — | Reverted before beta 3 |
| `RETURNING OLD/NEW` | **S** | `scan_queue_repository.py:353-410, 412-455` claim CTEs | Claim returns prior `status`/`attempts` without a re-read (Phase 5). **PG19 beta 3 — verify against final release notes at the GA gate** |

`default_toast_compression=lz4` is **not** a PG19 benefit. It is available on PG17 and is independent "Now" config (§7). It affects **newly written values only**; there is no recompression plan for existing TOAST.

## 4. Incompatibility checklist against this codebase

| PG19 change | Exposure here | Action |
|---|---|---|
| RADIUS auth removed | none (API-key + SCRAM image default) | — |
| `standard_conforming_strings` forced on; `escape_string_warning` removed | SQLAlchemy binds parameters; raw SQL in `001_identity_schema.py` uses no `E'…'` literals (grep clean) | Re-grep `text()` bodies in Phase 1 |
| CR/LF banned in db/role/tablespace names | plain names (`acx_identity_test`, …) | — |
| `inet`/`cidr` default opclass → GiST; `btree_gist` inet blocks pg_upgrade | no `inet`/`cidr` columns (codemap 0 hits) | — |
| `CREATE SCHEMA` no longer reorders sub-commands | schema built by ordered `op.execute` | — |
| `COPY FROM … WHERE` no system columns; `json_array()` returns `[]`; `postgres_fdw` READ ONLY | no callers | — |
| `max_locks_per_transaction` 64 → 128 | slightly more shared memory | check `shared_buffers` headroom on A1 (24 GB, fine) |
| JIT disabled by default | MV refresh aggregate + pgvector plans may re-cost | capture `EXPLAIN (ANALYZE, BUFFERS)` baselines on 17 first; enable `jit` only with a measured win [PERF-06] |
| `sync_error_count` → `sync_table_error_count`; `BUFFERPIN` → `BUFFER` wait event | no logical replication; no wait-event dashboards | — |
| MD5 password warnings, `password_expiration_warning_threshold` | image initialises SCRAM | verify `10-create-test-role.sql` sets no MD5 password |
| `MULE_INTERNAL` encoding removed | UTF-8 | — |
| C11 compiler required | only if pgvector is built from source for arm64 (second exit, §8 CARD-16) | keep a `Dockerfile` recipe ready |
| Protocol 3.2 (from PG18) | asyncpg negotiates 3.0 | pin note carried from v0.1 |

## 5. Planned-feature fit — video description & management, description cache, tracks

Product stance (unchanged by this evaluation): video/scene description is an **Oyster** — "one-week timeboxed probe, post-demo. No epic until probe data exists" (portfolio quadrant); local-AI roadmap §4.2 defers the video epic until after still-image context-caption proof; the commercial-face assessment keeps the video/track pipeline as a separate future epic with a companion guide. [CARD-03] *"When evidence runs out, ship a first-class unknown"* — the probe's outcome is the unknown. PG19 features are therefore **options the video epic would exercise**, listed so the epic can price them; none of them is a reason to upgrade earlier. Triggers in §11 do not bypass the portfolio product freeze except a security fix per the P2 exception.

| Planned need (source) | Today's shape | PG19 option | What it replaces |
|---|---|---|---|
| Keyframe/scene description cache at N stills per minute of video (portfolio probe: scenes/minute; context-aware roadmap: cache keyed tenant + image hash + adapter/model version + context hash) | `uq_image_descriptions_cache_key` + savepoint/`IntegrityError`/re-select (`description_repository.py:50-69`) | `ON CONFLICT DO SELECT … RETURNING` (GA-gate verify) | 3 statements → 1 per keyframe; near-duplicate frames hit the cache on the first round trip |
| Per-scene rows purged by `retention_class` (context-aware roadmap; RES-07) | `DELETE` via retention purge; no reclaim | `REPACK CONCURRENTLY` after purge; parallel autovacuum during ingest (GA-gate verify) | the "VACUUM FULL downtime" answer noted in caption-context §8 |
| `visual_facts` + per-scene provenance JSONB volume | `_json_col()` JSONB, pglz | **Now (PG17):** `default_toast_compression=lz4` for newly written values only; no recompression of existing TOAST | storage/decompress cost on new writes; does **not** fix document growth — [MODEL-02] extract per-frame arrays before video |
| Identity persistence across frames: track segments `[t_start, t_end)` per identity per video (portfolio probe; commercial-face medoid aggregation onto `IdentityClusterRepresentative` + `mv_identity_cluster_centroids`) | point-in-time `identity_members` (delete+insert reassignment) | range column + `WITHOUT OVERLAPS` (PG18, D2) + `FOR PORTION OF` (PG19) | hand-written split/merge-at-time-t logic; D2 gets its first concrete consumer |
| "Who co-occurs in which scenes", continuity across cuts, track↔identity↔cluster↔constraint queries | Python graph in `discovery/graph/discovery.py`, recursive CTEs | SQL/PGQ `GRAPH_TABLE` | [ALG-01] *"Graph in disguise"* — name vertices/edges first; PGQ only once two consumers exist |
| Long describe runs with many items, GPU demand leases (`describe_demand_leases`, `gpu_intent.py`) | advisory locks, `lock_timeout` → 503 | `pg_stat_lock`, `log_lock_waits` on by default (GA-gate verify) | ad-hoc lock debugging |
| Run/description export for management UI | Python serialisation, `BackgroundTasks` (pg_durable G5) | `COPY … TO … (FORMAT json)` | custom serialisers for bulk export |
| Tenant provisioning reproducibility (`customer_provision_service.py`, `demo_provisioning_service.py`) | hand-built DDL | `pg_get_role_ddl` / `pg_get_database_ddl` | speculative; [REF-12] |

Net: PG19 lowers the DB cost of the video epic in cache, reclaim, and temporal tracks. lz4 TOAST is independent PG17 config, not a hop benefit. The epic's gate stays the probe.

## 6. Codemap impact map

Change class: **Simplified** (code shrinks) · **Improved** (behaviour better, no code change) · **Config** · **Verify** (unaffected but on the upgrade test path) · **External**.

Anchors re-verified with `grep -n` 2026-09-16. Paths relative to `apps/prototype-description-service/` unless noted.

| # | Anchor | Symbol / fan-in | PG19 lever | Class |
|---|---|---|---|---|
| 1 | `recognition/interface_adapters/http/deps/session.py:46-59` | `_apply_postgres_session_safety_settings` | none (Phase 0 done) | Verify |
| 2 | `db/settings.py:28-67` class fields; `:249` `get_database_settings`; `:286-287` timeout env | `DatabaseSettings` | add `DB_TRANSACTION_TIMEOUT` → server `transaction_timeout` (PG17 feature, still unset) | Config |
| 3 | `recognition/infrastructure/repositories/scan_queue_repository.py:353-410, 412-455, 234-280` | `_claim_pending_items_postgres`, `_claim_pending_items_any_postgres`, `reclaim_stale_items` | `RETURNING OLD/NEW` (GA-gate verify); `SKIP LOCKED` waits visible in `pg_stat_lock` (GA-gate verify) | Simplified |
| 4 | `recognition/infrastructure/repositories/member_repository.py:80-120` | `add_member_if_not_exists` (`uuid.uuid4()` at `:94` + `on_conflict_do_nothing` + rowcount + `session.get`) | `ON CONFLICT DO SELECT` (GA-gate verify); swap `uuid4` → `generate_id` now (in-scope UUID) | Simplified |
| 5 | `member_repository.py:152-229` | `bulk_add_members_if_not_exists` (`uuid.uuid4()` at `:179`) | same; in-scope UUID | Simplified |
| 6 | `recognition/application/persistence/assignment_writer.py:284-353, 355-468, 470-517` | `persist_assignment`, `persist_assignments_chunk`, `_apply_joint_uniqueness_guard` | `DO SELECT` returns the winning row for the guard [DATA-18]. (`uuid.uuid4()` at `:241` is **out of scope**) | Simplified |
| 7 | `scene/application/description_repository.py:22-43, 50-69` | `get_by_cache_key`, `insert_or_get_existing` (`begin_nested` + `IntegrityError` + re-select); `ImageDescription.id default=uuid.uuid4` (`db/models/scene.py:65`) | `DO SELECT` on `uq_image_descriptions_cache_key`; `uuid4` → `generate_id` now (in-scope UUID) | Simplified |
| 8 | `scene/application/describe_run_repository.py:47` `_release_idempotency_key_if_barren`; `:151-211` `create_run`; `scene/interface_adapters/http/routers/describe_run.py:375` `_replay_or_conflict` (IntegrityError replay ~`:555`) | idempotency reservation on `uq_image_description_runs_idempotency_key` | `DO SELECT` for get-or-replay. **Excluded:** `routers/describe.py:717` `DescribeOperationRepository.accept` — not a conflict/get-or-insert path. `create_single_run` (`:213`) is not a DO SELECT site | Simplified |
| 9 | `recognition/infrastructure/repositories/cluster_repository.py:147-207, 542, 627`; `recognition/worker/scan_worker.py:645` | `_refresh_mv_concurrent_with_bypass` (headroom = `max(min_bytes, 2 * mv_bytes)` via `shared/disk_headroom.py::probe_disk_headroom` / `has_headroom`), `refresh_centroids_view*`, `_refresh_mv_if_needed` | headroom **helpers** reused by the REPACK Make target; the target's precheck is free ≥ 2× (table + indexes) and is **not** the compose healthcheck | Improved / reuse |
| 10 | `db/migrations/versions/001_identity_schema.py:2637-2691` MV DDL; `:2133` `ensure_refresh_queue`; `:2152` `ensure_triggers`; `:2528` `ensure_matview`; `:2708` `heal` | MV DDL (`l2_normalize`, ivfflat `vector_cosine_ops` at `:2690-2691`) | AFTER-trigger role semantics (PG18, kept) fix `app.current_tenant` at fire time; no PG19 DDL change. Vector-index smoke target after restore | Verify |
| 11 | `db/models/scene.py:76,81,82,85,219,358,360`; `db/models/observability.py:50,55,98,206`; `db/models/jobs.py:123-124` payload; `db/models/tenant.py:110` `demo_instances` / `:123-124` `branding_json`; `db/models/atlas.py:51` `_jsonb_compatible` | JSONB columns | **Now (PG17):** `default_toast_compression=lz4` on newly written values only; no recompression | Config |
| 12 | `db/tenant_context.py:57-84, 109-123, 152-167` | `set_tenant_context`, `enable_rls_bypass`, `_register_checkout_listener` | RLS semantics unchanged in 19 | Verify |
| 13 | `recognition/shared/db/dialect.py:19-26` | `is_sqlite`, `is_postgres` | `DO SELECT` lands behind `is_postgres()` so sqlite keeps the fallback [REF-15]; `is_sqlite` removal is a test-strategy decision, not an upgrade phase | Verify |
| 14 | `recognition/interface_adapters/http/routers/clusters_admission.py:164-199`; `scene/application/gpu_intent.py:174`; `scripts/sync_identity_schema.py:49,79` | `_acquire_tenant_lock_fast_fail`; `_acquire_gpu_intent_lock`; `pg_advisory_xact_lock` | `log_lock_waits` on, `pg_stat_lock` (GA-gate verify) | Improved |
| 15 | `recognition/shared/ids.py:16` `generate_id` | app-side UUIDv7 | `uuidv7()` server default optional; drop `uuid-ossp` now (0 callers) | Config |
| 16 | `docker-compose.db.yml:3`, `docker-compose.env.yml:22`, `docker-compose.prod.yml:22`, `db/docker-init/001-extensions.sql`, `db/docker-prod-init/001-extensions.sql` | image tag, extension list | hop uses a **new volume** + pinned `pg19` digest, not an in-place tag flip; remove `uuid-ossp` | Config |
| 17 | REPACK Make target (planned; not present today) | free-space precheck | target measures `pg_total_relation_size` of the table **plus indexes** and refuses unless free space ≥ 2× that sum (`probe_disk_headroom` / `has_headroom`). `ACX_PG_DISK_MAX_USED_PCT` on `docker-compose.env.yml` is unrelated | Config |
| 18 | `infra/oci/main.tf:204-208` | A1.Flex 4 OCPU / 24 GB arm64 | arm64 `pgvector:pg19` **digest** | External |
| 19 | `recognition/interface_adapters/http/routers/retention.py:179` | `trigger_export` via `BackgroundTasks` (pg_durable G5) | `COPY TO (FORMAT json)` option only | Verify |
| 20 | `recognition/application/discovery/graph/discovery.py`, `constraint_repository.py`, `routers/clusters_topology.py` | Python graph traversal | SQL/PGQ candidates | Park |

Not impacted: WordPress plugin (PHP, no PG dependency); `apps/prototype-wp-alt-context/`.

## 7. Phase re-plan (v0.2)

### Now (PG17, no upgrade)

- Pull the current `pgvector/pgvector:pg17` image on next deploy and verify `SELECT version()` ≥ 17.11 — the minor release fixes 28 CVEs (CVE-2026-6464 8.1, CVE-2026-6471 7.2, fourteen at 8.8 incl. CVE-2026-14662/-14664/-14669/-14670/-14671/-14676/-14677/-14680/-15741/-15742/-16238/-16239/-18408/-19385, CVE-2026-14668 8.1, CVE-2026-14679 8.2). Staying on 17 is only safe on 17.11.
- Drop `uuid-ossp` from both `001-extensions.sql` files (zero callers).
- Replace in-scope `uuid.uuid4()` with `generate_id`: `member_repository.add_member_if_not_exists` (`:94`), `bulk_add_members_if_not_exists` (`:179`), `ImageDescription.id` (`db/models/scene.py:65`). Remaining `uuid.uuid4` sites are out of scope (§14).
- Set server-level `transaction_timeout` (PG17) via compose `command: postgres -c transaction_timeout=…`, env-driven; add `DB_TRANSACTION_TIMEOUT` to `DatabaseSettings`. Closes the last Phase 0 item.
- **lz4 TOAST (independent of PG19):** set `default_toast_compression=lz4` in the db service `command:` on PG17. Affects newly written values only. **No recompression plan** for existing TOAST. Do not wait for the hop.
- **`pg_stat_statements` enablement (required before any gate or exit uses it):**
  1. Add `shared_preload_libraries=pg_stat_statements` to the db service `command:` in `docker-compose.db.yml`, `docker-compose.env.yml`, and `docker-compose.prod.yml`.
  2. Restart postgres.
  3. `CREATE EXTENSION pg_stat_statements` (init SQL or one-shot).
  4. Grant a least-privilege read role (SELECT on `pg_stat_statements` only).
  5. Capture a baseline. Only then may Phase 3 exit or §11 trigger 3 consult it.
- Capture `EXPLAIN (ANALYZE, BUFFERS)` baselines on 17 for: MV refresh, claim CTE, centroid cosine search, cache get-or-insert. Without them the JIT-default flip in 19 cannot be judged [PERF-06].

### Phase 1 — Compatibility & hop (17 → 19)

Entry gates (all required). A §11 trigger does **not** authorize `19.0`.

- PG19 GA.
- PG19 minor **≥ 19.1**. Never upgrade on `19.0`. The only exception is a security fix unavailable on PG17, recorded as an explicit risk decision before the hop.
- Pinned `pgvector/pgvector:pg19` image **digest** (not merely a tag) that passed the dump/restore rehearsal below.
- One §11 trigger, subject to the product freeze (security exception only).
- Dump/restore **rehearsal on a copy of the production dump** — this rehearsal is itself an entry gate. Measured dump+restore wall time is the downtime budget.
- GA-gate name/default verification for every PG19-specific interface in §3 (checklist in §13) before any later phase relies on it.

`pg_upgrade --check` (and `vacuumdb --dry-run`) stay as **early compatibility probes only**. They are not the migration method. Do **not** flip the image tag onto the existing PG17 data directory.

Forward path — dump/restore into a **new** named volume [Release It! bulkheads / rollback-before-rollout; DDIA ch-4 encoding rewrite + ch-12 restore-as-proof]:

1. Stop writers (maintenance mode: stop `api` and `worker`; no new writes).
2. `pg_dumpall` from the PG17 container.
3. Record `SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'` on PG17.
4. Start a PG19 container from the **pinned digest** on a **fresh** named volume / data directory. Local: new volume beside `prototype_description_pgdata` (`docker-compose.db.yml:24-25`). Env/prod: a sibling of `${ACX_PGDATA_PATH}` / `/opt/acx-backend/data/pgdata`. Leave the PG17 volume / bind mount **untouched**.
5. Restore the dump into PG19.
6. `ALTER EXTENSION vector UPDATE`. Record post-update `extversion`.
7. Vector-index smoke query on restored data against `mv_identity_cluster_centroids` (ivfflat `vector_cosine_ops`, `001_identity_schema.py:2690-2691`).
8. Smoke + revoked-key / tenant probes: `pg`-marked suite; `recognition/tests/scripts/test_manage_api_keys.py::test_revoke_sets_revoked_at`; `recognition/tests/api/test_tenant_isolation.py`; `/health/detailed` (`api/main.py:543`, `shared/health.py`) shows 19.x ≥ 19.1.
9. Point the api at PG19 (compose image digest + the new volume).

Persistent settings at this PG19 cutover restart (not later, not per Make target):

- `wal_level=logical` — restart-only, cluster-wide. Measure WAL volume overhead (`pg_stat_wal`) during the rehearsal.
- Replication-slot lifecycle for REPACK: `max_repack_replication_slots=1` once the GA gate confirms the name; one slot per REPACK; orphan-slot check and drop in the runbook. Never create slots outside that target. **Never toggle `wal_level` per Make-target run.**

Rollback: point compose back to the PG17 image and the **untouched** PG17 volume. No data is written to the PG17 volume after the dump. Writes made after cutover are **lost on rollback**; the runbook must say so. [RLSE-08], [CARD-15], Release It! bulkheads (the PG17 volume is the blast-radius wall).

Downtime = the measured dump+restore time from the rehearsal. Drill rollback once on the dev VM before prod [RES-16].

Exit: suite green on 19; no plan regression vs baseline; RLS + GUC reset listener behave identically; version string 19.x (≥ 19.1) in `/health/detailed`; vector extension version recorded before/after; rehearsal duration filed.

### Phase 2 — Autovacuum / TOAST / IO config

lz4 TOAST moved to "Now (PG17)". This phase is autovacuum + io only, and only after the GA-gate name/default ticks.

- `autovacuum_max_parallel_workers=2`; per-table `autovacuum_parallel_workers` on `media_identities`, `identity_scan_job_items`; accept io-worker autoscaling defaults (`io_min_workers` / `io_max_workers` / `io_worker_idle_timeout` / `io_worker_launch_interval` — GA-gate verify).
- Exit: `pg_stat_autovacuum_scores` (GA-gate verify) shows no table starved after a scan burst; `pg_stat_io` documented before/after.

### Phase 3 — `ON CONFLICT DO SELECT` adoption

- Rows 4–8 of §6, behind `is_postgres()`; sqlite path keeps the current fallback. Row 8 is the describe-run idempotency reservation, **not** `DescribeOperationRepository.accept`.
- Exit: `pg_stat_statements` (enabled in Now) shows one statement per get-or-insert; `pg`-marked tests cover the race (two writers, same key) [TEST-09].

### Phase 4 — `REPACK CONCURRENTLY` reclaim runbook

- `wal_level=logical` is already on from the Phase 1 cutover; do not toggle it here.
- Planned Make target (not present today): compute `pg_total_relation_size` of the target table **plus its indexes**; require free space ≥ 2× that sum via `shared/disk_headroom.py::probe_disk_headroom` / `has_headroom`; **refuse** otherwise. Then `REPACK CONCURRENTLY` per churny table. Wire after retention purge [RES-07]. Slot lifecycle: max slots as gated in Phase 1; orphan-slot check and drop after the run.
- Exit: repack of `media_identities` under a live claim workload on dev with zero 5xx; the target's own disk precheck is what clears, not a compose healthcheck.

### Phase 5 — `RETURNING OLD/NEW` claim CTE (carried from v0.1)

- Row 3; exit: claim returns prior `status`/`attempts` without a re-read. GA-gate verify the syntax first.

Dropped from v0.1: Phase 3 AIO tuning (defaults now self-scale, pending GA-gate verify); Phase 4 `--no-policies`/`is_sqlite()` removal (test strategy, not upgrade; keep in backlog); virtual generated columns (no candidate column; → D11).

## 8. Heuristics-canon assessment

Canon: `~/Development/heuristics-canon-research` — `lexicons/engineering.md` (FAM-NN rows), `reasoning/*.md` (CARD-NN). Verbatim excerpts, then application. Distillations: `literature/extracted/refactoring/distilled/release-it.md`, `designing-data-intensive-applications.md`.

| Id · path | Verbatim | Applied |
|---|---|---|
| ARCH-08 · `lexicons/engineering.md:558` | "**Choose boring technology / single machine first**: well-understood edge cases beat novel infrastructure" | PG19 at GA **and ≥ 19.1** is boring; PG19 beta and `19.0` are not |
| ARCH-06 · `:556` | "**Everything is a trade-off**: if you haven't found the downside, you haven't found it yet" | Downsides named: JIT default-off re-costs plans; persistent `wal_level=logical` means more WAL on a 24 GB box for the life of the 19 cluster; lz4 ratio can be worse than pglz on some JSONB; GA undated; pgvector is a second vendor on the critical path; dump/restore downtime is the full dump+restore window |
| ARCH-07 · `:557` | "**Why beats how (write the ADR)**: context, decision, consequences must outlive the author" | This document + handoff decision under `PG19-1` |
| ARCH-09 · `:559` | "**Quantify load before scaling**: … a scale-out proposal must state concrete load parameters" | Zero production users, free-tier A1; no throughput claim is made. Benefits claimed are statement-count and reclaim, not RPS |
| PERF-06 · `:291` | "**Measure, don't guess (perf)**: profile first, tune hot spots after; back out changes with no measured win" | 17 baselines before the hop; `jit` and parallel-autovacuum settings need before/after |
| RES-02 · `:113` | "**Timeout on every blocking call**: every socket/pool/RPC/`wait()` needs a bounded timeout" | Session-level done; server `transaction_timeout` still unset → "Now" list |
| RES-07 · `:118` | "**Steady-state reclaimer**: anything that grows needs same-rate purge, shipped in the same release" | Retention purge exists; reclaim half missing. `REPACK CONCURRENTLY` (Phase 4) is that half; video ingest makes it non-optional |
| RES-16 · `:127` | "**Exercise the tolerance path**: a claimed fault-tolerance mechanism must be exercised before the claim ships" | Dump/restore rehearsal + rollback drill on a copy of the production dump are Phase 1 **entry** criteria |
| RLSE-08 · `:699` | "**Rollback written before ship**: … must answer whether the old build can read the new build's data" | Answer: no (17 cannot read 19). Rollback = retained untouched 17 volume. Post-cutover writes are lost; the runbook says so |
| RLSE-07 · `:698` | "**Phased rollout is instrumentation**: … stop criteria … named before launch" | rehearsal copy → dev → CI → demo VM; stop = plan regression, `pg`-suite red, vector smoke fail, or extversion unexpected |
| DATA-03 · `:191` / DATA-04 · `:192` | "**Schema evolution compat**: rolling upgrades coexist old+new code" / "**Expand→migrate→contract**" | Greenfield policy waives in-place data migration; dump/restore is an encoding rewrite onto a new volume (DDIA ch-4). The `DO SELECT` change is expand (PG path) → contract (sqlite fallback stays until the test strategy changes) |
| DATA-17 · `:205` / DATA-18 · `:206` / CON-11 · `:158` | "**Isolation names are not guarantees**: … record the database engine, storage engine, version, isolation level" / "**Snapshot-isolation check-then-act gap**: … prefer a database constraint" / "**Atomicity violation (check-then-act)**" | Rows 4–8 are check-then-act today, protected by unique constraints plus a re-read. `DO SELECT` makes them one atomic statement; record "PG19, READ COMMITTED, unique constraint" per invariant |
| MODEL-02 · `:226` / MODEL-03 · `:227` | "**Document locality cuts both ways**: keep documents small and extract high-churn or unbounded collections" / "**Schema-on-read is a deferred schema**" | lz4 relieves storage on new writes, not modeling debt: `visual_facts`/`phrase_boxes` need per-frame extraction before video volumes |
| STOR-01 · `:243` / STOR-07 · `:249` | "**Every index taxes writes**" / "**Precompute is an optimization, not the source**" | No new index proposed; MV freshness SLO unchanged by parallel autovacuum or `REPACK` |
| REF-12 · `:331` | "**YAGNI / speculative-generality gate**: reject hooks/abstract layers with one consumer" | Virtual generated columns, SQL/PGQ, `pg_get_*_ddl` parked (D11–D13) |
| REF-15 · `:334` | "**Ports & adapters**: … every hard-coded library call is a forfeited seam" | `is_postgres()` seam is where PG19-only SQL lands |
| TEST-09 · `:390` | "**Hard test = design defect**: … needs a real DB … keep it out of the fast suite" | PG19-only behaviour in `pg`-marked integration tests only |
| ALG-01 · `:629` | "**Graph in disguise**: most messy applied problems reduce to a classical graph problem once vertices/edges are designed" | Identity/cluster/constraint/track graph — design vertices/edges in the video probe before choosing PGQ vs Python |
| CARD-06 · `reasoning/evidence-before-commitment.md` | "Durable state (deploy, merge, buy, label, "done") requires inspectable evidence *before* the commit, not after the harm." | Hop only after: pinned digest, rehearsal green, `pg` suite green on 19, vector smoke, EXPLAIN diff reviewed |
| CARD-15 · `reasoning/reversible-commitments.md` | "Prefer the cheap reversible option while the irreversible path is underpriced; write the soft side and the rollback before freeze." | Stay on 17.11; skip 18; skip `19.0`; rollback written here before any freeze |
| CARD-16 · `reasoning/second-exit-hostile-landlord.md` | "Assume a single external control point will turn; keep a second exit cheap enough to throw before you need it." | pgvector's image is the single control point for the DB image. Second exit: a from-source pgvector `Dockerfile` on the official `postgres:19` arm64 image (C11 toolchain) |
| CARD-03 · `reasoning/designed-unknown.md` | "When evidence runs out, ship a first-class unknown or abstention state; forced certainty is a false answer." | GA date, arm64 digest date, video-probe outcome are unknowns → §11 uses triggers, not dates; names/defaults are beta-3 until the GA gate |
| Release It! ch-5 Bulkheads / Fail Fast · `literature/extracted/refactoring/distilled/release-it.md` | Isolate failure; fail before burning the old system; recycle accumulators | New PG19 volume is a bulkhead around the untouched PG17 volume. Do not in-place `pg_upgrade`. Refuse the hop on `19.0` (unbounded blast radius of a first minor) |
| DDIA ch-4 / ch-12 · `literature/extracted/refactoring/distilled/designing-data-intensive-applications.md` | Data outlives code; encodings must be proven; untested backups do not exist | Dump/restore is an encoding rewrite. Rehearsal on a **copy** of the production dump is the compatibility proof. Record vector `extversion` before/after `ALTER EXTENSION vector UPDATE`; ivfflat smoke on restored rows |

## 9. External dependencies

| Dependency | Status 2026-09-16 | Blocks |
|---|---|---|
| PostgreSQL 19 GA **and** minor ≥ 19.1 | beta 3 (2026-08-13); GA undated; `19.0` is a hard no | Phase 1 |
| `pgvector/pgvector:pg19` (arm64) **digest** | **absent** — Docker Hub tag query `name=pg19` returns 0; pgvector CHANGELOG latest 0.8.6 (2026-07-29) has no PG19 entry | Phase 1. Pin the digest that passed rehearsal; tag-only is not a gate |
| pgvector 17.11-based `pg17` image | verify digest carries 17.11 on next pull | Now |
| asyncpg 0.31.0 (pin `<0.33`) | no PG19-specific release notes; protocol negotiation covers 3.0/3.2 | Phase 1 verify |
| psycopg 3.3.4 | no PG19 note found | Phase 1 verify |
| SQLAlchemy 2.0.49 | no `ON CONFLICT DO SELECT` construct in 2.0.x; use `text()` or wait for dialect support | Phase 3 |
| pg_durable | PG17/18 only, amd64 only — still "do not vendor" per its evaluation | none |

## 10. Risks

- **pgvector lag on arm64.** Mitigation: pin a tested digest; second-exit `Dockerfile` (CARD-16); do not build it until the GA gate opens [REF-12].
- **JIT default flip regresses a plan.** Mitigation: 17 baselines; `jit=on` in compose if measured; `pg_stat_statements` plan counts (after Now enablement).
- **`REPACK CONCURRENTLY` doubles disk transiently.** Mitigation: the REPACK Make target's own precheck (free ≥ 2× table+indexes) refuses when tight. Do not treat `ACX_PG_DISK_MAX_USED_PCT` as that guard.
- **`wal_level=logical` inflates WAL on the 24 GB host for the life of the 19 cluster.** Mitigation: set it once at the Phase 1 cutover; measure `pg_stat_wal` in rehearsal; document slot max / orphan drop. Do not toggle per run.
- **Upgrading onto a `.0` release.** Mitigation: hard gate ≥ 19.1 plus pinned digest. Exception only for a PG17-unavailable security fix, recorded as an explicit risk decision.
- **In-scope UUID migrations leave other `uuid.uuid4` sites in place.** Mitigation: §14 names the migrated sites and lists the remainder as out of scope; no repo-wide zero claim.
- **Dump/restore downtime and post-cutover write loss on rollback.** Mitigation: rehearsal on a copy of the production dump sets the downtime number; runbook states that post-cutover writes are lost if compose is pointed back at the PG17 volume.

## 11. Decision and revisit triggers

**This section is the only canonical timing/trigger policy.** Older PG18 documents keep PG18 text only as historical context and must point here; they are not a second trigger list.

**Decision:** stay on PG17.11; skip PG18; move to PG19 in one hop when **all** hard gates hold:

1. PG19 GA.
2. PG19 minor **≥ 19.1** (never `19.0`).
3. Pinned arm64 `pgvector/pgvector:pg19` image digest that passed the Phase 1 dump/restore rehearsal (vector `extversion` before/after, ivfflat smoke).
4. Dump/restore rehearsal on a copy of the production dump completed; downtime number filed.

**and any one** of the following product triggers. Triggers (bloat, hot path, video, CVE) **do not bypass the portfolio product freeze** except a security fix unavailable on PG17, which is recorded as an explicit risk decision (P2 exception) and may hop without waiting for the freeze to lift:

1. Production data exists (portfolio-quadrant gate for the DB upgrade) **and** the freeze has lifted, or the P2 security exception applies.
2. Table bloat after a retention purge has no online reclaim answer on 17 without downtime — still subject to the freeze except the P2 exception. (The trip is **not** defined as "the disk-usage healthcheck"; REPACK's own precheck is the reclaim guard.)
3. `pg_stat_statements` (after the Now enablement) shows a get-or-insert path (rows 4–8) in the top-10 by calls.
4. The video probe produces data and an epic opens (tracks/temporal, keyframe cache rate) **and** the freeze has lifted.
5. A PG17-only CVE / security fix unavailable on PG17 forces a major hop (P2 exception). That hop still requires ≥ 19.1 unless the fix exists only on a specific 19.x that is recorded in the risk decision.

Re-open this document at PG19 GA regardless, to re-verify §3/§4 names and defaults against final release notes (`GROUP BY ALL` already reverted between betas; other items may move). The §13 GA-gate checklist must be completed before Phase 2–5 rely on those names.

## 12. Deferred (post-v0.2)

| Id | Item | Change vs v0.1 |
|---|---|---|
| D1 | OAuth DB-level auth | PG19 adds an "OAuth Validator Modules" chapter, new hba options, libpq `oauth_ca_file`; deferral rationale unchanged (JWT-to-role design spans WP → API → DB) |
| D2 | Temporal membership (`WITHOUT OVERLAPS`, `PERIOD` FKs) | PG19 adds `FOR PORTION OF` `UPDATE`/`DELETE`; first concrete consumer = video track segments (§5). Still a product decision, not an upgrade consequence |
| D3 | Non-btree unique index on MV | unchanged; `cluster_id` needs no ANN index |
| D4 | SCRAM passthrough / `postgres_fdw` | PG19 adds `READ ONLY` foreign servers; still no FDW usage |
| D5 | NUMA | unchanged; single-socket A1 |
| D6 | `NOT ENFORCED` constraints | PG19 extends to `CHECK`; unchanged rationale |
| D7 | `COPY TO` from MV / exports | PG19 adds `FORMAT json`, `ON_ERROR SET_NULL`; candidate for description-run export |
| D8 | `log_lock_failures` | **closed** — superseded by `log_lock_waits` default on + `pg_stat_lock` (§3), pending GA-gate verify |
| D9 | PostgREST read path | unchanged (see v0.1 for the endpoint tables); PG19 adds nothing decisive |
| D10 | Logical replication / read replica | PG19: sequence replication, `EXCEPT`, `retain_dead_tuples`, `WAIT FOR`; still no replica need. `wal_level=logical` at cutover is for REPACK slots, not a replica |
| D11 | Virtual generated columns | moved from v0.1 Phase 5; no candidate column identified [REF-12] |
| D12 | SQL/PGQ property graphs | new; park until two consumers (§5) |
| D13 | `pg_plan_advice` / `pg_stash_advice` | new; only on a plan regression |

## 13. Consolidated checklist

### Now (PG17)

- [ ] Verify deployed image is 17.11 (`SELECT version()`); redeploy if not
- [ ] Remove `uuid-ossp` from `db/docker-init/001-extensions.sql` and `db/docker-prod-init/001-extensions.sql`
- [ ] `uuid.uuid4()` → `generate_id` in `member_repository.add_member_if_not_exists`, `bulk_add_members_if_not_exists`, and `ImageDescription.id` default
- [ ] Server `transaction_timeout` via compose command + `DB_TRANSACTION_TIMEOUT`
- [ ] `default_toast_compression=lz4` in db `command:` (newly written values only; no recompression)
- [ ] `pg_stat_statements`: `shared_preload_libraries` in db `command:` → restart → `CREATE EXTENSION pg_stat_statements` → least-privilege read role → baseline
- [ ] EXPLAIN baselines (MV refresh, claim CTE, centroid search, cache get-or-insert) stored under `docs/`

### GA gate (before any phase relies on the name/default)

- [ ] `INSERT … ON CONFLICT DO SELECT` — name and semantics vs final release notes
- [ ] `REPACK` / `REPACK CONCURRENTLY` / `max_repack_replication_slots` — name, default, slot behaviour
- [ ] `pg_stat_autovacuum_scores` — name
- [ ] `pg_stat_lock` — name
- [ ] adaptive `io_min_workers` / `io_max_workers` / `io_worker_idle_timeout` / `io_worker_launch_interval` — names and defaults
- [ ] `log_lock_waits` default-on — confirm default
- [ ] `RETURNING OLD/NEW` — name and claim-CTE applicability

### Phase 1 — hop

- [ ] Gates: PG19 GA · minor ≥ 19.1 · pinned arm64 `pgvector:pg19` **digest** · dump/restore rehearsal on a copy of the production dump · §11 trigger (freeze unless P2 exception)
- [ ] §4 checklist re-run against final release notes
- [ ] `pg_upgrade --check` and `vacuumdb --dry-run` as probes only
- [ ] Stop writers; `pg_dumpall` from PG17; start PG19 on a **new** volume from the pinned digest; restore; leave the PG17 volume untouched
- [ ] Record vector `extversion` before; `ALTER EXTENSION vector UPDATE`; record after
- [ ] ivfflat smoke query on restored `mv_identity_cluster_centroids`
- [ ] `pg`-marked suite + full suite; revoked-key (`recognition/tests/scripts/test_manage_api_keys.py::test_revoke_sets_revoked_at`) and tenant (`recognition/tests/api/test_tenant_isolation.py`) probes; `/health/detailed` (`api/main.py:543`) shows 19.x ≥ 19.1
- [ ] Persist `wal_level=logical` at this restart; measure `pg_stat_wal`; document slot max / orphan-slot check and drop
- [ ] Switch api to PG19 (digest + new volume)
- [ ] EXPLAIN diff; `jit` decision recorded
- [ ] Data checksums enabled online
- [ ] Rollback drill: compose back to PG17 image + untouched 17 volume; runbook states post-cutover writes are lost

### Phase 2 — config

- [ ] GA-gate ticks for autovacuum / `io_*` / `pg_stat_autovacuum_scores`
- [ ] `autovacuum_max_parallel_workers`, per-table `autovacuum_parallel_workers`
- [ ] `pg_stat_autovacuum_scores` / `pg_stat_io` before/after documented
- [ ] lz4 is **not** in this phase (done in Now)

### Phase 3 — `ON CONFLICT DO SELECT`

- [ ] GA-gate tick for `DO SELECT`
- [ ] Rows 4–8 behind `is_postgres()` (`accept` excluded)
- [ ] Two-writer race tests under `pg` marker
- [ ] `pg_stat_statements` shows 1 statement per get-or-insert

### Phase 4 — `REPACK CONCURRENTLY`

- [ ] GA-gate tick for `REPACK` / `max_repack_replication_slots`
- [ ] `wal_level=logical` already persistent from Phase 1 (do not toggle)
- [ ] Make target: free space ≥ 2× (table + indexes) or refuse; wired after retention purge; orphan-slot check/drop
- [ ] Live-workload repack on dev with zero 5xx

### Phase 5 — `RETURNING OLD/NEW`

- [ ] GA-gate tick
- [ ] Claim CTE returns prior state without re-read

## 14. Success criteria

- [ ] Prod on PG17.11 until the hop; no PG19-dependent code merged before Phase 1 gates open (including ≥ 19.1 and pinned digest).
- [ ] `uuid-ossp` gone.
- [ ] In-scope UUID migrations done: `member_repository.add_member_if_not_exists`, `bulk_add_members_if_not_exists`, `ImageDescription.id`. **No** "zero `uuid.uuid4()` repo-wide" claim.
- [ ] Remaining `uuid.uuid4` call sites, **out of scope**: `scan_queue_repository.py:101`, `constraint_repository.py:75`, `cluster_repository.py:1546`, `assignment_writer.py:241`, `describe_operation_repository.py:76`, `analyze_multipart.py:348`, `constrained_hac.py:112`, `demo_provisioning_service.py:276`, `customer_provision_service.py:118`, `discovery.py:116`, `worker/handlers/scan.py:71`, `describe_run_worker.py:362`, `gpu_intent.py:153`, eval-harness tokens, and model defaults in `db/models/{observability,scene (other than ImageDescription.id),constraints,atlas,identity,jobs,tenant}.py`.
- [ ] After the hop: suite green on 19.x ≥ 19.1, EXPLAIN diff shows no regression, dump/restore rehearsal + rollback drill passed, vector `extversion` recorded before/after, ivfflat smoke passed.
- [ ] Named get-or-insert sites (rows 4–8) at one statement each. `DescribeOperationRepository.accept` is not in that set.
- [ ] A documented, tested online reclaim path whose disk guard is the REPACK target's own 2× (table+indexes) precheck.
- [ ] Video epic (if opened) can price cache/reclaim/temporal from §5, and lz4 as PG17-now config, without re-deriving.

## Sources

- [PostgreSQL 19 documentation](https://www.postgresql.org/docs/19/index.html) · [Release notes 19](https://www.postgresql.org/docs/19/release-19.html) · [18.6/17.11/…/19 beta 3 announcement (2026-08-13)](https://www.postgresql.org/about/news/postgresql-186-1711-1615-1519-1424-and-19-beta-3-released-3365/)
- [pgvector Docker Hub tags](https://hub.docker.com/v2/repositories/pgvector/pgvector/tags?name=pg19) (0 results, 2026-09-16) · [pgvector CHANGELOG](https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md) (0.8.6, 2026-07-29)
- [roadmap-pg18-upgrade.md](roadmap-pg18-upgrade.md) (v0.1, superseded; historical context only — this document's §11 is the canonical trigger policy) · [roadmap-pg-durable-evaluation.md](roadmap-pg-durable-evaluation.md) · [caption-context assessment §8](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) · [portfolio-quadrant assessment](../assessments/current/portfolio-quadrant-mvp-strategy-assessment-2026-06-11.md) · [local-AI roadmap](local-ai-managed-default-roadmap-2026-07-31.md) · [context-aware description roadmap](context-aware-image-description-roadmap-2026-06-13.md)
- Heuristics canon: `~/Development/heuristics-canon-research/lexicons/engineering.md`, `reasoning/*.md` (mirror: `docs/workbay/rules/engineering-heuristics.md`) — cited: ARCH-06/07/08/09, PERF-06, RES-02/07/16, RLSE-07/08, DATA-03/04/17/18, CON-11, MODEL-02/03, STOR-01/07, REF-12/15, TEST-09, ALG-01, CARD-03/06/15/16.
- Release It! distillation: `literature/extracted/refactoring/distilled/release-it.md` (bulkheads, Fail Fast, rollback-before-rollout). DDIA distillation: `literature/extracted/refactoring/distilled/designing-data-intensive-applications.md` (ch-4 encoding evolution, ch-12 restore-as-proof).
