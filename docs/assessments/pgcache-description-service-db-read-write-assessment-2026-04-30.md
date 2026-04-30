# PgCache and Description-Service DB Read/Write Mechanics Assessment

**Status:** assessment / investigation outcome  
**Date:** 2026-04-30  
**Task:** `PGCACHE-DB-ASSESSMENT`  
**Scope:** `apps/prototype-description-service/recognition/` database and application read/write mechanics. Recognition pipeline algorithm changes are intentionally out of scope.

## Executive Summary

PgCache should **not** become a default production dependency for the description service immediately after [roadmap-pg18-upgrade.md](../roadmaps/roadmap-pg18-upgrade.md) is complete. It is most plausible as a **bounded benchmark pilot** for read-heavy WordPress projection endpoints, not for write paths, vector search, queue claiming, or materialized-view refresh.

The strongest reason is architectural fit: PgCache is a transparent CDC-backed SELECT cache, while the description service already uses PostgreSQL-native mechanics for the important write/read boundaries: RLS tenant context, partial indexes, `FOR UPDATE SKIP LOCKED` queue claims, and a materialized centroid view. The PG18 roadmap already targets the highest-value database improvements: AIO, `OLD`/`NEW RETURNING`, UUIDv7, better MV workflows, and timeout hardening.

A similar feature **is worth implementing for reads**, but not as a generic transparent SQL cache in application code. The better local shape is a purpose-built **tenant projection read model** for cluster snapshot/delta responses: precomputed, versioned, tenant-scoped, and invalidated at known write boundaries. That keeps consistency semantics explicit and avoids the RLS/session-state ambiguity of caching SQL below SQLAlchemy.

## Sources Reviewed

- PgCache public site and docs: transparent PostgreSQL wire proxy; CDC invalidation; logical replication prerequisite; cacheable SELECT patterns; uncacheable `FOR UPDATE`, non-SELECT, views, recursive CTEs; metrics and per-query hit/latency observability; current GitHub status reports active development and no published GitHub releases.
- [roadmap-pg18-upgrade.md](../roadmaps/roadmap-pg18-upgrade.md) — PG18 target architecture and performance phases.
- [cluster_repository.py](../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py) — cluster snapshots, deltas, centroid MV refresh, representative reads.
- [scan_queue_repository.py](../../apps/prototype-description-service/recognition/infrastructure/repositories/scan_queue_repository.py) — scan queue claim/reclaim write mechanics.
- [001_identity_schema.py](../../apps/prototype-description-service/db/migrations/versions/001_identity_schema.py) — indexes, dirty queue, MV, triggers, RLS.
- [db/session.py](../../apps/prototype-description-service/db/session.py) and [db/settings.py](../../apps/prototype-description-service/db/settings.py) — engine pools, timeouts, statement-cache settings.
- Local literature: `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt`, `Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt`, `Release-it--design-and-deploy-production-ready-software--Michael-T-Nygard.txt`, and the existing [clustering-pipeline-postgres-refactor-literature-2026-04-26.md](clustering-pipeline-postgres-refactor-literature-2026-04-26.md).
- `/Volumes/Chimay/___Books/_graph/topics/`: `Databases.md`, `Algorithms.md`, `System Design.md`, `Software Engineering.md`, and `Face Recognition.md` topic maps.

## PgCache Fit

PgCache is attractive where the app repeatedly issues the same or subsumable SELECTs, where freshness can tolerate CDC lag, and where the query surface is simple enough to cache safely. Its useful features for this service would be request coalescing, materialized aggregate results, per-query hit/miss observability, and CDC-driven invalidation without hand-written cache eviction.

The description service has only a few obvious candidate reads:

- Full tenant cluster snapshot: [cluster_repository.py](../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py) fetches all clusters, all members, and identities for WordPress projection sync.
- Version-filtered delta reads: [cluster_repository.py](../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py) fetches clusters updated after a snapshot version and then member rows for those clusters.
- Top unlabeled clusters and representative reads: [cluster_repository.py](../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py) issues repeated tenant-scoped list/read queries.
- Operational counts/statuses: [scan_queue_repository.py](../../apps/prototype-description-service/recognition/infrastructure/repositories/scan_queue_repository.py) has status summary and detected-count reads.

The poor-fit surfaces are more numerous:

- Queue claims use `FOR UPDATE SKIP LOCKED`, which PgCache forwards to origin.
- Non-SELECT writes, DDL, refreshes, `UPDATE ... RETURNING`, and `INSERT ... ON CONFLICT` are forwarded to origin.
- The centroid materialized view is already a database-managed read model with an IVFFlat vector index and dirty tracking in [001_identity_schema.py](../../apps/prototype-description-service/db/migrations/versions/001_identity_schema.py).
- PgCache docs say views are forwarded, so reads against `mv_identity_cluster_centroids` would not be an obvious cache win.
- SQLAlchemy `AsyncSession` uses implicit transactions, and the service relies on `SET LOCAL app.current_tenant`; if PgCache bypasses transaction-scoped queries or cannot include custom GUC state in cache identity, most current request-path SELECTs either will not cache or should not cache without explicit tenant predicates.

## Decision

Do **not** place PgCache in the primary production path as part of the PG18 upgrade. After PG18 is complete, run a limited benchmark only if production-like traffic shows repeated, read-heavy snapshot/delta access that remains slower than acceptable after native PG18 work lands.

Adoption criteria for a PgCache pilot:

1. `pg_stat_statements` or app metrics show at least one stable SELECT family with high frequency, high origin latency, and low mutation churn.
2. The query is outside `FOR UPDATE`, DML, MV refresh, and transaction-sensitive paths.
3. The query includes an explicit tenant predicate in SQL, not only RLS via `app.current_tenant`.
4. Cache freshness SLO can tolerate sub-second CDC lag.
5. PgCache can be configured with an allowlist limited to projection tables and validated with hit-rate plus p95/p99 latency metrics.
6. Logical replication overhead and WAL retention risk are acceptable in the production topology.

If those criteria are not met, PgCache adds a proxy hop, logical replication slot, cache database, CDC operational surface, and a new failure mode without a clear benefit.

## Should We Implement a Similar Read Feature?

Yes, but the local version should be explicit and projection-oriented:

- Add a tenant-scoped `cluster_projection_snapshots` or equivalent read-model table that stores the serialized WordPress projection payload, `snapshot_version`, `generated_at`, and a generation id.
- Refresh it at known write boundaries: clustering job completion, curation sync, cluster label changes, representative changes, retention purge, and split/merge operations.
- Serve `GET /tenants/{tenant_uuid}/clusters/snapshot` from the projection when fresh; rebuild synchronously only when missing or stale.
- Keep `GET /tenants/{tenant_uuid}/clusters/delta` as the first-class incremental path, but make tombstones/deletions explicit so clients do not need fallback full snapshots for destructive changes.
- Add request coalescing per `(tenant_id, projection_kind)` so concurrent cold reads share one rebuild.
- Use HTTP validators (`ETag` or `If-None-Match`) around `snapshot_version` so the WordPress side can avoid body transfer when unchanged.

This is close in spirit to PgCache's materialized results, but it is safer here because it aligns with the domain contract instead of caching arbitrary SQL below RLS/session state.

## Write-Path Assessment

PgCache does not improve writes; it forwards them and adds CDC work after the origin commit. For this service, write-path effort should remain in PostgreSQL/application mechanics already identified by the PG18 roadmap:

- Keep `FOR UPDATE SKIP LOCKED` claim paths and benchmark them under PG18 AIO.
- Use PG18 `OLD`/`NEW RETURNING` where it removes a follow-up read from queue claim or state-transition flows.
- Measure write amplification from current indexes before adding more. DDIA's index tradeoff applies directly: secondary indexes speed reads but add storage and write cost.
- Keep the centroid dirty queue and MV refresh path as the write-to-read boundary, then benchmark whether PG18 AIO reduces refresh latency enough before adding another cache layer.
- Preserve pool bulkheads and timeouts from [db/session.py](../../apps/prototype-description-service/db/session.py) and [db/settings.py](../../apps/prototype-description-service/db/settings.py); these are higher-confidence production protections than a cache proxy.

## PG18 Roadmap Interaction

After [roadmap-pg18-upgrade.md](../roadmaps/roadmap-pg18-upgrade.md) is complete, the PgCache value proposition gets narrower, not broader:

- PG18 AIO should reduce the read-scan and MV-refresh pressure PgCache might otherwise hide.
- `OLD`/`NEW RETURNING` can remove round trips in write flows that PgCache cannot cache.
- UUIDv7 may improve locality for newly inserted rows and time-range access patterns.
- Better MV workflows reduce the need to push aggregate/materialized read optimization into an external proxy.
- PG18 improves protocol/session metadata that PgCache can use, but the service's own RLS custom-GUC model still needs explicit validation before proxy caching can be trusted.

The right sequence is therefore: finish PG18, capture query/latency evidence, build the domain projection read model if snapshots remain hot, and only then run PgCache as an A/B benchmark against those same reads.

## Literature Crosswalk

- DDIA supports the existing MV/dirty-queue direction: materialized views are denormalized read copies that make reads cheaper while increasing write/update cost. That maps to `mv_identity_cluster_centroids` and argues for explicit read models over hidden cache layers.
- DDIA's read-your-writes discussion is the main caution for PgCache: a CDC-backed cache is eventually consistent. That is fine for background projection reads, but not for post-write API responses that must reflect the just-accepted curation change.
- Enberg's latency book points to measuring p95/p99 and using caching only when the latency distribution justifies it. The service should gather query families and tail latency before adding infrastructure.
- Nygard's `Release It!` guidance favors bulkheads, timeouts, and avoiding resource-pool coupling. The service already moved in this direction with business/observability/clustering pools; those remain priority protections.
- The `/Volumes/Chimay` topic maps did not reveal a better DB-specific source than the local extracted refactoring books for this particular question. `Databases.md` is sparse; `Algorithms.md` and `Face Recognition.md` are more useful for future recognition-pipeline algorithm work than for DB read/write mechanics.

## Recommended Follow-Up Work

1. Add a post-PG18 benchmark plan for `snapshot`, `delta`, top-unlabeled, queue claim, MV refresh, and representative reads. Record p50/p95/p99, rows scanned/returned, buffers, and query count per request.
2. Design the tenant projection read model as a small task plan if snapshot/delta reads remain hot.
3. Add instrumentation around snapshot/delta request coalescing and response bytes, even before a projection table exists.
4. Keep PgCache as an external benchmark option, configured with a strict table allowlist and telemetry disabled unless explicitly accepted.
5. Do not cache SQL that relies only on `SET LOCAL app.current_tenant` for tenant isolation; require explicit tenant predicates for every cacheable projection query.

## Final Recommendation

Use PG18-native mechanics and an explicit tenant projection read model first. Treat PgCache as a measured, opt-in accelerator for a small set of projection SELECTs only after the PG18 roadmap is complete and real query metrics show that native Postgres plus domain projections are not enough.
