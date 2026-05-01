# Clustering Pipeline & Postgres Refactor — Literature Crosswalk

**Status:** assessment / source crosswalk · **Date:** 2026-04-26 · **Task:** `pds-litrev-26`
**Subject:** `apps/prototype-description-service/recognition/` (clustering pipeline + Postgres operations)

## Sources

- `Release-it--design-and-deploy-production-ready-software--Michael-T-Nygard.txt` (Nygard 2018, 2nd ed.) — chapters 4 (Stability Antipatterns) and 5 (Stability Patterns).
- `Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt` (Kleppmann 2017) — chapter 7 (Transactions), chapter 1 (latency tails).
- `Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt` (Enberg 2024) — chapters 2 (modeling/measuring), 3 (data colocation), 10 (asynchronous processing, hiding latency).
- `Using-Asyncio-in-Python-Understanding-Python-Hattingh.txt` (Hattingh 2020) — chapter 3 (event loop lifecycle, blocking calls, cancellation).
- `Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt` (Fowler/Beck 2018, 2nd ed.) — chapters 6, 7, 10 (mechanics).

Adjacent literature in `literature/extracted/recognition/` (chinese-whispers, RkCNN, Apple ML book) is in scope of clustering algorithm tuning — explicitly **out of scope** for this crosswalk, which targets pipeline architecture, transactions, and latency.

## Method

Two parallel reads: (a) full structural map of `recognition/application/` orchestration, persistence, and `db/` session/tenant code, with file:line anchors; (b) targeted grep-driven extraction of principles from the five source books, filtered to those that bear on Postgres + asyncio + external-API pipelines. Synthesis cross-walks each principle against the surface map and emits a finding only where a concrete code anchor exists. Every finding cites the source book, the code location, and a confidence level.

Spot-checked anchors: [orchestrator.py:54](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L54), [orchestrator.py:627](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L627), [generator.py:99](../../apps/prototype-description-service/recognition/application/embedding/generator.py#L99), and grep for hardcoded status strings.

## Surface map (compressed)

- **Orchestration entrypoint:** [orchestrator.py:54](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L54) — async, chunked, durable-per-chunk commits at L627.
- **Adaptive chunk sizing:** [chunked_processor.py:10](../../apps/prototype-description-service/recognition/application/orchestration/clustering/chunked_processor.py#L10) — EWMA targeting 500ms/chunk, bounds [5, 100].
- **Three-pool engine split:** [db/session.py:31,46,66](../../apps/prototype-description-service/db/session.py#L31) — business / observability / clustering pools (bulkhead).
- **Circuit breaker (admission-only):** [clustering_circuit_breaker.py](../../apps/prototype-description-service/recognition/interface_adapters/http/deps/clustering_circuit_breaker.py) — wraps the POST `/recognition/clustering/jobs` admission, opens on `QueryCanceledError`.
- **Tenant context (RLS):** [tenant_context.py:48](../../apps/prototype-description-service/db/tenant_context.py#L48) — `SET LOCAL app.current_tenant`; restored after every chunk commit at [orchestrator.py:634](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L634).
- **Observability decoupling (partial):** [orchestrator.py:639](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L639) — buffered events flushed via separate session factory if provided.
- **External-call surfaces:** embedding adapter at [generator.py:99](../../apps/prototype-description-service/recognition/application/embedding/generator.py#L99); scan adapter at [scan/service.py:100](../../apps/prototype-description-service/recognition/application/scan/service.py#L100); auto-labeler in `application/labeling/`.

The pipeline already implements several patterns Nygard recommends — bulkheaded pools, an admission-side circuit breaker, durable chunk boundaries, and adaptive batch sizing. The findings below focus on the gaps.

## Findings

Each finding: principle, source citation, concrete code anchor, recommended move, confidence (H/M/L), tier (1=ship-soon, 2=plan, 3=watch).

### F-1 · External-call timeout missing on embedding adapter — Tier 1, H

- **Principle:** *Use Timeouts.* "Anything you can do to dam off the integration point will keep the rest of the system safe." Without a timeout on a remote call, a hung peer holds a connection and a thread for as long as TCP allows. (Nygard, ch. 5.1.)
- **Code:** [generator.py:99-114](../../apps/prototype-description-service/recognition/application/embedding/generator.py#L99) — `await self._adapter.analyze(image_bytes)` is wrapped in `except Exception` only; no `asyncio.wait_for`, no per-call deadline, and the `except` swallows the failure with a log. Caller in [scan/service.py:100](../../apps/prototype-description-service/recognition/application/scan/service.py#L100) is inside an open `_session` scope.
- **Move:** wrap with `asyncio.wait_for(timeout=settings.embedding_timeout_s)` and surface a typed `EmbeddingTimeoutError`. Make timeout configurable per environment. Pair with F-2.
- **Why now:** an adapter hang today blocks both an asyncio task and an open Postgres transaction. Cheapest stability win in the file.

### F-2 · Transaction held across external HTTP call — Tier 1, H

- **Principle:** *Integration Points* / *Cascading Failures.* Mixing slow remote I/O with held resources is the canonical anti-pattern; the local pool gets sucked dry by remote latency. (Nygard, ch. 4.1, 4.3.)
- **Code:** [scan/service.py:100-101](../../apps/prototype-description-service/recognition/application/scan/service.py#L100) executes `await self._adapter.analyze(...)` after [scan/service.py:89](../../apps/prototype-description-service/recognition/application/scan/service.py#L89) has set `scan_job.status = "running"` and committed — but the **subsequent** `save_job_results` (L94+) does the same pattern around `_extract_media_id` and the per-detection processing. Verify before fixing whether any caller still wraps the analyze call in an outer transaction.
- **Move:** restructure as three explicit phases (Fowler — *Split Phase*): (1) reserve job in tx, commit; (2) external call, **no** open tx; (3) persist results in a fresh tx. The shape `commit → call → commit` is the stability rule for any external integration in our stack.
- **Risk note:** breaks idempotency guarantees if the call completes but step 3 fails. Use a deterministic `idempotency_key` derived from `(job_id, media_id)` and `ON CONFLICT DO NOTHING` on insertion (we already use this pattern at [assignment_writer.py:439](../../apps/prototype-description-service/recognition/application/persistence/assignment_writer.py#L439)).

### F-3 · No circuit breaker around embedding/labeling adapters — Tier 1, H

- **Principle:** *Circuit Breaker.* "Stop calling them when they're broken." A breaker turns a slow-fail into a fast-fail, which is what other layers can survive. (Nygard, ch. 5.2.)
- **Code:** the only breaker is on the clustering admission endpoint — there is no breaker around `InsightFaceEmbeddingGenerator.generate` ([generator.py:87](../../apps/prototype-description-service/recognition/application/embedding/generator.py#L87)) or the auto-labeler. A failing model server today degrades latency silently rather than shedding load.
- **Move:** factor a small `AdapterCircuitBreaker` reusing the state machine from `clustering_circuit_breaker.py` (closed→open→half-open) and wrap each external adapter at the application boundary, not at the HTTP boundary. Trip on a configurable failure-rate window; half-open probes one request.

### F-4 · No structured timeout/cancellation on long chunk operations — Tier 2, M

- **Principle:** *Steady State* + *Blocked Threads.* "If a system is not in steady state, it is degrading or healing." Operations that can outlast `idle_in_transaction_session_timeout` will eventually have their connection killed under load and emerge corrupted. (Nygard, ch. 4.5, 5.4.)
- **Code:** [orchestrator.py:448](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L448) — `_process_chunks` iterates without a per-chunk deadline. Adaptive sizing keeps the median fast, but a tail chunk doing graph fallback ([orchestrator.py:574](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L574)) or HAC refinement ([orchestrator.py:604](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L604)) has no upper bound enforced by the orchestrator itself; it relies on the Postgres `statement_timeout` set per request.
- **Move:** wrap the chunk body in `asyncio.timeout(per_chunk_budget_s)`. On timeout: cancel the chunk, log the offending chunk size + tenant + job, halve the EWMA's next-chunk target, retry once, then record the chunk as a finding for human review.
- **Why tier 2:** the bulkheaded pool already prevents a single slow chunk from cratering business traffic. The benefit here is observability and self-healing, not blast-radius reduction.

### F-5 · Tail-latency monitoring is implicit — Tier 2, M

- **Principle:** *Latency distribution, not a single value.* "The mean is a lie." P50 is uncorrelated with user pain at scale; P99 and P999 are the actionable metrics. (Enberg, ch. 2.2; reinforced in DDIA ch. 1.)
- **Code:** [orchestrator.py:644](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L644) logs a per-chunk `elapsed_ms`, and [chunked_processor.py:59](../../apps/prototype-description-service/recognition/application/orchestration/clustering/chunked_processor.py#L59) feeds a single EWMA. Neither captures distribution or tail; a 99th-percentile chunk that is 5× the mean is invisible to the controller.
- **Move:** keep the EWMA for sizing, but emit a P50/P95/P99 histogram per job (e.g., a fixed-bucket structured-log line at job end, or a Prometheus histogram if metrics infra is hooked up — defer infra choice to a follow-up). Use the P99 to decide whether to hold or shrink the chunk-size envelope, not the mean.

### F-6 · Magic-string status values across job/scan models — Tier 2, M (sr-007)

- **Principle:** *Replace Magic Number with Symbolic Constant* (Fowler, ch. 9). Reinforced in our own `sr-007`: "Centralize domain status values as enums."
- **Code:** confirmed via grep — production sites assigning bare strings include [routers/clusters.py:361](../../apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py#L361), [deps/stores.py:40,55](../../apps/prototype-description-service/recognition/interface_adapters/http/deps/stores.py#L40), [scan/service.py:89](../../apps/prototype-description-service/recognition/application/scan/service.py#L89), [analyze.py:266](../../apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py#L266), [retention.py:161,206](../../apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py#L161). Status comparisons by string also exist (`result.get("status") != "completed"`).
- **Move:** introduce `JobStatus(StrEnum)` in `recognition/domain/` (or expand an existing enum if present). Replace assignments and comparisons in one slice; keep DB column as `text` for now, but wire the enum into the model via SQLAlchemy `Enum(JobStatus, native_enum=False)` so the runtime validates the surface. This is also a precondition for any state-machine guard (you can't assert "running → completed only" with strings).

### F-7 · Long parameter list at orchestration entry — Tier 2, M (sr-008)

- **Principle:** *Introduce Parameter Object* (Fowler, ch. 6). Mirrors `sr-008`'s 8-parameter ceiling.
- **Code:** [orchestrator.py:54-72](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L54) takes 14 keyword args; the runner constructor at [orchestrator.py:96-113](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L96) duplicates them. `_persist_and_cache_new_clusters` at [assignment_writer.py:374](../../apps/prototype-description-service/recognition/application/persistence/assignment_writer.py#L374) takes 8.
- **Move:** group into 3 cohesive frozen dataclasses passed by composition: `ClusteringDependencies` (gate, three discoveries, writer, suggestion + merge services, constrained_hac), `ClusteringRuntimeConfig` (commit flag, hac_settings, session_factory, progress_callback), and `ClusteringContext` (tenant_id, job_id, session). Test surface stays the same; test fixtures get easier to compose.

### F-8 · Snapshot-isolation question for chunk consistency — Tier 3, L

- **Principle:** *Snapshot Isolation / Repeatable Read* (DDIA ch. 7). "Each transaction sees a consistent snapshot." If two concurrent clustering jobs ever run on the same tenant — even via worker reclaim — write skew on cluster membership becomes possible.
- **Code:** isolation is left at Postgres default (`READ COMMITTED`). The bulkheaded clustering pool with `with_for_update()` on Tenant at admission ([routers/clusters.py](../../apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py)) currently serializes per-tenant job startup, so write skew is bounded.
- **Move:** **do not** raise the isolation level globally — `REPEATABLE READ` would break the per-chunk commit cadence (each chunk would see a stale snapshot and fight on member writes). Instead, document the invariant ("per-tenant job startup is serialized via tenant lock; chunk-level commits run at READ COMMITTED") in an ADR that supersedes ADR-006 for the transactional contract. Re-evaluate only if we ever lift the per-tenant serialization.

### F-9 · `expire_on_commit=False` and tenant-context restore are coupled — Tier 3, L

- **Principle:** *Decoupling Middleware* (Nygard, ch. 5). The commit-then-restore dance at [orchestrator.py:627-635](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L627) is correct given Postgres `SET LOCAL` semantics, but it is a leaky abstraction — every future code path that introduces a chunk-level commit must remember it.
- **Move:** wrap chunk commit + tenant-context restore in a single async context manager (`@asynccontextmanager async def chunk_commit_boundary(session, tenant_uuid)`). Name the seam so the next contributor doesn't reinvent it. Optional: enforce via a unit test that asserts `app.current_tenant` is set after exiting the boundary.

### F-10 · Adaptive sizing is single-signal — Tier 3, L

- **Principle:** *Backpressure / Little's Law.* `Throughput = Concurrency / Latency`; tuning chunk size only on latency ignores the queue-depth lever. (Enberg, ch. 2.1.1, 10.5.)
- **Code:** [chunked_processor.py:59-77](../../apps/prototype-description-service/recognition/application/orchestration/clustering/chunked_processor.py#L59) — α=0.3 EWMA on `chunk_ms` only.
- **Move:** add a second signal (clustering pool utilization from `get_pool_stats()` at [db/session.py:99](../../apps/prototype-description-service/db/session.py#L99)). When pool utilization is high, shrink the chunk envelope even if latency is fine — that's the backpressure response. Defer until F-1 through F-3 land; piling controllers onto a not-yet-instrumented system is premature optimization.

## Confirmed non-issues (don't refactor)

- **No `assert` for runtime validation in production code.** sr-006 is clean across the recognition tree.
- **No raw `START TRANSACTION` / `COMMIT` SQL in Python.** All transaction boundaries go through `AsyncSession.commit()` / `rollback()` and the dependency wrapper at [deps/session.py:91](../../apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py#L91). sr-009's PHP analogue is satisfied.
- **No sync-blocking calls on the event loop.** numpy ops in [similarity/search.py:80](../../apps/prototype-description-service/recognition/application/similarity/search.py#L80) are CPU-microseconds, not I/O — leaving them inline is fine.
- **Pgvector is intentionally not used at the DB layer for KNN.** Representatives are cached in-memory by design ([similarity/search.py](../../apps/prototype-description-service/recognition/application/similarity/search.py)); switching to pgvector KNN would add round-trip latency. Not a refactor candidate.

## Recommended sequencing

1. **Slice 1 (F-1, F-2, F-3):** External-call hygiene. Adapter timeout + transaction-around-call split + adapter circuit breaker. Highest blast-radius reduction. Single feature task; estimated 2–3 slices.
2. **Slice 2 (F-6, F-7):** Mechanical refactors. `JobStatus` enum + parameter-object groupings. Low risk, large readability win, unblocks F-4's state-machine guard.
3. **Slice 3 (F-4, F-5):** Observability + per-chunk deadline. Depends on F-6 to express the timeout-recovery state cleanly.
4. **Defer (F-8, F-9, F-10):** ADR-only for F-8; minor seams for F-9 and F-10. Pick up as part of an integrity-of-the-pipeline sweep, not standalone work.

## Consolidated Checklist

- [ ] Add explicit timeout handling around embedding and other external adapter calls.
- [ ] Split database transaction boundaries away from remote adapter calls on the clustering path.
- [ ] Add application-level breaker coverage for embedding/labeling adapter failures.
- [ ] Add per-chunk timeout/latency instrumentation once the state surface is centralized enough to recover cleanly.
- [ ] Replace magic-string job statuses with a canonical enum surface.
- [ ] Group orchestration dependencies/config/context into parameter objects.
- [ ] Keep isolation-level, chunk-boundary, and backpressure refinements deferred until the Tier 1/Tier 2 slices land.

## Open questions for follow-up planning

1. Is the per-tenant `with_for_update()` lock at job admission *guaranteed* to be the only entry point, or can the worker path ([scan_worker.py:127](../../apps/prototype-description-service/recognition/application/scan/scan_worker.py#L127)) start a clustering job concurrently? If yes, F-8's serialization assumption is wrong.
2. Are auto-labeler calls already wrapped in something timeout-y inside `application/labeling/`? Not located in the structural map; verify before extending F-1's scope to labeling.
3. Does `clustering_engine`'s pool size in production equal the dev default at [db/settings.py](../../apps/prototype-description-service/db/settings.py#L1)? F-10's backpressure heuristic is only meaningful if the pool is appropriately narrow in prod.

## Out of scope for this assessment

- Algorithmic tuning of HDBSCAN, HAC, chinese-whispers (covered by `recognition/` literature, deferred).
- Frontend / WordPress plugin surfaces.
- Retention/export pipelines (mentioned briefly under F-6 only).
- Authentication, RLS policy correctness (already an ADR).

---

**Provenance:** Synthesized from two parallel Explore-agent investigations on 2026-04-26 against `feature/pds-litrev-26` HEAD. Code anchors spot-checked at the orchestrator entry, chunk-commit boundary, and embedding adapter; the remainder are reported as the investigating agent located them. Re-verify before turning a finding into a task plan.
