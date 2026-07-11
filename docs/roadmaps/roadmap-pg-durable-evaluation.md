# pg_durable Vendoring Evaluation (v0.1)

> **Status:** Decision document. Evaluated 2026-07-10 under task `pg-durable-eval`.
> **Question:** Should the monorepo vendor [pg_durable](https://microsoft.github.io/pg_durable/) (Microsoft's in-database durable-execution extension), possibly combined with the PG17→18 upgrade ([roadmap-pg18-upgrade.md](roadmap-pg18-upgrade.md)) or PG19?
> **Verdict:** **No — do not vendor now.** Close the identified durability gaps incrementally in the existing hand-rolled layer (~200–400 LOC), proceed with the PG18 upgrade unchanged, and re-evaluate pg_durable against the revisit triggers below. The juice is not worth the squeeze today.

---

## What pg_durable is

- PostgreSQL extension + background worker for in-database durable execution: workflows are graphs of SQL steps that Postgres checkpoints and resumes after crash. Built on Rust (`duroxide` orchestration runtime + `duroxide-pg` state provider, via cargo-pgrx).
- Features: sequential chaining (`~>`), fan-out/join (`&`), variable passing, conditionals (`df.if()`), timers/scheduled loops, `df.http()` calls, `df.wait_for_signal()`, built-in retries, deterministic replay, SQL-queryable state.
- **Version/maturity:** v0.2.3 (2026-06-17), explicitly **"preview"**; Docker image marked "do not use in production". PostgreSQL License. ~2.3k stars.
- **Platform support:** PG17 and PG18 only (no PG19). Prebuilt Debian packages and Docker images are **amd64-only**; "multi-arch (`linux/arm64`) images are not published yet".
- **Authoring surface:** SQL DSL only. Arbitrary logic must be wrapped in SQL functions or reached via HTTP endpoints.

## Current state (inventory, 2026-07-10)

The description service already implements a Postgres-backed job system — **~2,700 LOC core** (scan worker 555, handlers 512, application/scan 775, `scan_queue_repository.py` 561, job models/enums 312), **~4,200 LOC** including the scene-describe machinery, export runner, and curation replay states, plus 20+ test files covering claim/stall/retry/isolation semantics.

**Assets worth keeping** (working, tested):

- `FOR UPDATE SKIP LOCKED` claim CTE with attempt counting (`recognition/infrastructure/repositories/scan_queue_repository.py:344`).
- Terminal-guarded finalizer UPDATEs (`status NOT IN terminal` predicates) that give single-fire scan→clustering fan-out via rowcount checks.
- Transient-vs-deterministic retry classification for clustering jobs (`recognition/worker/scan_worker.py:387` — only `OSError/TimeoutError/ConnectionError` retry).
- Stale-`processing` reclaim with partial index (`scan_queue_repository.py:233`).
- Fail-closed embedding capability heartbeat (`scan_worker.py:204`).

**Gaps a durable-execution engine would close** (all confirmed in code):

| # | Gap | Where | Blast radius |
|---|---|---|---|
| G1 | No retry backoff — failed items immediately reclaimable [RES-06] | `handlers/scan.py:180` | Retry storms against a struggling dependency |
| G2 | No dead-letter surface — terminal failure is `status='failed'` + `last_error` | `db/models/jobs.py` | Operator triage only via ad-hoc SQL |
| G3 | No heartbeats/lease renewal — staleness inferred from `started_at` alone; a slow-but-alive item >600s gets double-claimed [RES-10] | `scan_queue_repository.py:233` | Duplicate image fetch + inference; dedup relies on downstream constraints, not the queue [RES-01, DATA-13] |
| G4 | No reaper for `running` clustering jobs — a crash mid-run leaves the row `running` permanently | `scan_worker.py:286` (claim commits before handler runs) | Wedged clustering pipeline until manual intervention |
| G5 | Export + scene-describe jobs run via FastAPI `BackgroundTasks` — server death loses them; describe store is process-local in-memory (flagged MVP-only) | `routers/retention.py:160`, `scene/application/describe_jobs.py:53` | No multi-worker deployment; restart loses jobs |
| G6 | Clustering retry counter lives in JSONB `payload["retry_count"]`, not a column | `scan_worker.py:330` | Unqueryable retry state |
| G7 | DB CHECK allows 4 clustering statuses while the enum has 6 | `db/models/jobs.py:134` vs `domain/job.py` | Latent insert failure on `rejected`/`completed_with_errors` |

## Decision analysis

### Why not vendor pg_durable now

1. **ARM blocker.** Production Postgres runs in Docker on OCI `VM.Standard.A1.Flex` (Ampere aarch64, `infra/oci/main.tf:204`). pg_durable ships no arm64 artifacts — vendoring means owning a Rust-nightly + cargo-pgrx source build cross-compiled into a custom pgvector-based image, re-verified on every PG minor and every pg_durable release. That is a permanent build-chain liability for a two-person prototype, against [ARCH-08] (*choose boring technology*: what problem does this solve that the boring option cannot?).
2. **Preview software on the launch-critical path.** v0.2.3, explicit preview warning, Docker image "do not use in production". E15 (public demo launch readiness) is the active epic; the portfolio-quadrant assessment already flagged even the PG18 upgrade as mistimed pre-launch. Adopting a preview workflow engine now is the opposite of launch de-risking.
3. **Language inversion.** The actual pipeline steps are Python — InsightFace embeddings, HDBSCAN clustering, Florence/Qwen VLM inference, ObjectStore I/O. pg_durable orchestrates **SQL steps**; the Python work would have to be exposed as HTTP endpoints and called via `df.http()`, moving orchestration logic into a SQL DSL that calls back into the service it came from. That is a rewrite of ~2,700 tested LOC into a less-expressive language for zero new capability the service needs, and it couples orchestration to the DB's lifecycle ([REF-15]: the engine would be a hard-coded dependency with no adapter seam; [ARCH-06]: the downside is structural, not incidental).
4. **Orchestration complexity doesn't justify an engine.** [ARCH-04]: orchestrator utility rises with workflow complexity. The workflows here are shallow — scan items fan out flat, one auto-fanout edge (scan→clustering), no compensation chains, no human-signal waits, no cross-service sagas. The hard parts (claim atomicity, terminal guards, retry classification) are already solved and tested.
5. **Unverified interactions.** pg_durable + pgvector coexistence is undocumented; interplay with `FORCE ROW LEVEL SECURITY` + `app.current_tenant` session GUCs (every table here is RLS-tenant-scoped) is unknown. The background worker executes steps outside the request session — tenant context propagation into `df.*` steps would need from-scratch validation.
6. **No PG19 path.** pg_durable supports 17/18 only. If PG19-at-GA (~Sep/Oct 2026) is adopted per the [caption-context assessment §8](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) (`ON CONFLICT DO SELECT`, `REPACK CONCURRENTLY`), a vendored pg_durable would block the major-version upgrade until Microsoft ships support — an inverted dependency on a preview project's roadmap.

### What pg_durable would genuinely buy

Honest accounting [ARCH-06]: deterministic replay + checkpointing would structurally eliminate G3/G4/G5 (crash-recovery becomes the engine's job, not per-job-type reaper code); built-in retry policies close G1/G2; `df.wait_for_signal()` would fit future human-in-the-loop curation gates; timers would replace the hand-rolled interval gating in the poll loop. If this service were amd64, post-launch, and the workflows were deepening (compensation, multi-day waits, cross-service sagas), the calculus would flip.

### Interaction with the PG18/19 upgrade

Independent decisions — bundling them adds nothing:

- **PG18**: proceed per [roadmap-pg18-upgrade.md](roadmap-pg18-upgrade.md), unchanged. `pgvector/pgvector:pg18` images now exist (0.8.4-pg18), unblocking Phase 1. pg_durable neither requires nor accelerates any phase. `RETURNING OLD/NEW` (Phase 5) already improves the claim CTE without any engine.
- **PG19**: beta-1 (2026-06-04, GA ~Sep 2026). Track, do not build — reaffirming the prior assessment. pg_durable's lack of PG19 support is an additional reason not to couple to it.

## Recommended alternative: close the gaps in place

Incremental hardening of the existing layer, ordered by blast radius (each is a bounded slice; G1–G4 fit the existing repository/worker patterns):

1. **G4** — extend `reclaim_stale_items`-style reaper to `running` clustering jobs (staleness off progress-checkpoint timestamps). Highest blast radius, smallest fix.
2. **G3** — per-attempt lease token or heartbeat column updated by the item handler; claim predicate checks lease expiry, completion UPDATE checks token ([RES-10] fencing: a stale holder's write must be rejected).
3. **G1** — `next_attempt_at` column + exponential backoff with jitter on requeue [RES-06].
4. **G5** — move export + describe-run dispatch from `BackgroundTasks` onto the existing scan-worker job-type dispatch (the clustering-family pattern already generalizes); delete the in-memory describe store when multi-worker matters.
5. **G7** — align the clustering `valid_status` CHECK with `JobStatus` (greenfield: edit `001_identity_schema.py` directly).
6. **G2/G6** — promote `retry_count` to a column; add a `failed`-rows operator view (dead-letter query surface, not a new table) [RES-07 exempt: bounded by job retention].

Estimated total: ~200–400 LOC + tests, spread across normal task slices — versus a multi-week rewrite onto a preview engine plus a permanent ARM build chain.

## Revisit triggers

Re-open this evaluation when **any** of:

- pg_durable exits preview (≥1.0) **and** publishes arm64 artifacts (or prod moves to amd64 / managed Postgres such as Azure HorizonDB).
- pg_durable ships support for the PG major version the service targets (PG19+).
- Workflow complexity crosses the [ARCH-04] threshold: compensation chains, multi-day human-signal waits, or cross-service sagas enter the roadmap (e.g., billing/payments orchestration post-launch).
- The gap-closure work above demonstrably fails — recurring crash-recovery incidents despite G1–G5 fixes would indicate the hand-rolled layer is a structural liability, mirroring the PostgREST D9 revisit logic in the PG18 roadmap.

## Sources

- [pg_durable docs](https://microsoft.github.io/pg_durable/) · [microsoft/pg_durable (GitHub)](https://github.com/microsoft/pg_durable) · [InfoQ coverage (2026-06)](https://www.infoq.com/news/2026/06/postgresql-pg-durable/)
- [PostgreSQL 19 Beta 1 announcement](https://www.postgresql.org/about/news/postgresql-19-beta-1-released-3313/) · [pgvector/pgvector Docker Hub](https://hub.docker.com/r/pgvector/pgvector)
- [roadmap-pg18-upgrade.md](roadmap-pg18-upgrade.md) · [caption-context-enrichment-assessment-2026-07-05.md §8](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md)
- Engineering heuristics: [docs/strategy/engineering-heuristics.md](../strategy/engineering-heuristics.md) — cited: ARCH-04, ARCH-06, ARCH-08, RES-01, RES-06, RES-07, RES-10, DATA-13, REF-15.
