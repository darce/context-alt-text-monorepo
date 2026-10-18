# Scope · PDS Pipeline Stability (F-1, F-2, F-3, F-6, F-7)

**Status:** scoped · **Date:** 2026-04-27 · **Task:** `pds-pipeline-stability-26`
**Source assessment:** [docs/assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md](../assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md)
**Branch / worktree:** `feature/pds-pipeline-stability-26` · `/Users/daniel/Development/context-alt-text-monorepo-pds-pipeline-stability-26`

## MVP scope

Apply five findings from the literature crosswalk in one bundled feature task. The bundle pairs Slice 1 (external-call hygiene) with Slice 2 (mechanical refactors) so the JobStatus enum can express the new timeout-recovery states cleanly, and so the parameter-object refactor can be done before any new dependencies are added to the orchestration entrypoint.

### In-scope changes

| Finding | Intent | Concrete deliverable |
|---|---|---|
| **F-1** External-call timeout missing on embedding adapter | Bound every external adapter call with a configurable per-call deadline. | Wrap `InsightFaceEmbeddingGenerator.generate` ([generator.py:99](../../apps/prototype-description-service/recognition/application/embedding/generator.py#L99)) and the auto-labeler call site in `asyncio.wait_for(..., timeout=settings.<adapter>_timeout_s)`. New typed `AdapterTimeoutError` raised from a small helper. Per-adapter timeouts in `db/settings.py` (or a sibling settings module). |
| **F-2** Transaction held across external HTTP call | Enforce `commit → call → commit` as the integration-point shape. | Refactor `scan/service.py` (`mark_job_running` + `save_job_results`, [scan/service.py:83-114+](../../apps/prototype-description-service/recognition/application/scan/service.py#L83)) into three explicit phases: reserve+commit, external call (no open tx), persist+commit. Persistence step uses `ON CONFLICT DO NOTHING` keyed on `(job_id, media_id)` for idempotency. Audit other call sites that touch `_session.commit()` then call an adapter. |
| **F-3** No circuit breaker around embedding/labeling adapters | Slow-fail → fast-fail at the application boundary. | Extract `AdapterCircuitBreaker` from `clustering_circuit_breaker.py` (or share its core state machine) and wrap each external adapter at the application boundary. Trip on a configurable failure-rate window; half-open probes one request. Surface breaker-open as a typed error caught by the orchestrator/scan paths. |
| **F-6** Magic-string status values | Reuse the existing enum; satisfy sr-007. | `JobStatus(StrEnum)` already exists at [domain/job.py:12](../../apps/prototype-description-service/recognition/domain/job.py#L12) (`PENDING`/`RUNNING`/`COMPLETED`/`FAILED`). The work is to **replace remaining bare-string sites** in clustering + scan paths with imports from that enum — e.g. [routers/clusters.py:361](../../apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py#L361), [deps/stores.py:40,55](../../apps/prototype-description-service/recognition/interface_adapters/http/deps/stores.py#L40), [scan/service.py:89](../../apps/prototype-description-service/recognition/application/scan/service.py#L89), and any string comparisons (`result.get("status") != "completed"`). Also widen the enum if grep turns up values it doesn't yet cover (`retrying`, `awaiting_projection` already live on `JobPhase` — confirm whether they belong on `JobStatus` too or stay on `JobPhase`). DB column stays `text`; SQLAlchemy `Enum(JobStatus, native_enum=False)` is opt-in for the columns we touch. |
| **F-7** Long parameter list at orchestration entry | Satisfy sr-008's 8-parameter ceiling. | Group `cluster_unclustered_identities` and `IncrementalClusteringRunner.__init__` ([orchestrator.py:54-113](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L54)) into 3 frozen dataclasses: `ClusteringDependencies`, `ClusteringRuntimeConfig`, `ClusteringContext`. Same surface, three values instead of fourteen. Apply the same move to `_persist_and_cache_new_clusters` ([orchestrator.py:374](../../apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py#L374)) — the helper lives in `orchestrator.py`, not `assignment_writer.py`. |

### Suggested implementation slices

1. **F-7 first** (parameter-object groupings): no behavior change, lowest risk, makes F-1/F-3 wiring cleaner because new dependencies (timeout config, breaker) flow through the new dataclasses instead of as N+1th positional args.
2. **F-6 next** (adopt existing `JobStatus` enum at remaining string sites): unblocks F-2's phase rename ("running" → "reserved" → "completed" or similar — possibly via a `JobPhase` extension instead of `JobStatus`) and F-3's breaker-open status without re-touching call sites later. The enum already exists at [domain/job.py:12](../../apps/prototype-description-service/recognition/domain/job.py#L12); this slice is "import + replace literals", not "introduce".
3. **F-1 + F-3 together** (timeout + breaker on the same adapter): they share the wrapping helper; lands as one slice.
4. **F-2 last** (tx phase split): largest design surface; benefits from F-6's enum to express the new states. Greenfield policy means in-flight job semantics may break — acceptable.
5. **ADR + tests fold into each slice**, with the ADR landing alongside F-2 since it codifies the `commit → call → commit` rule the whole bundle is built on.

## Success criteria

1. **Behavioral tests** (pytest, recognition test suite):
   - F-1: monkeypatched slow adapter triggers `AdapterTimeoutError` within `embedding_timeout_s ± tolerance`; no `_session.commit()` waits on the slow call.
   - F-2: `scan/service.py` proven to commit before the adapter call (assert via session-level spy or by inspecting `session.in_transaction()` at adapter-call time).
   - F-3: 3 consecutive adapter failures trip the breaker; subsequent calls fail-fast without invoking the adapter; half-open probe restores closed state on success.
   - F-6: type-check (mypy) and runtime grep prove no remaining bare `"running" | "completed" | "failed" | "pending"` literals in clustering + scan paths.
   - F-7: orchestrator entry function takes ≤4 positional/keyword args (the three dataclasses + tenant/job context).
2. **Branch-review**: `make review-run` lands a `pass` or `pass_with_findings` verdict; all open findings either fixed or explicitly deferred with rationale before merge.
3. **ADR landed**: `docs/adrs/ADR-NNN-external-adapter-stability-pattern.md` documents (a) the `commit → external-call → commit` invariant, (b) `AdapterCircuitBreaker` as the reusable seam, (c) per-adapter timeout settings convention, (d) `JobStatus` enum location and SQLAlchemy wiring choice.
4. **Pre-merge gate** (`handoff_close_check(enforce=True)`) passes against the merge SHA.

## Hard constraints

- **No new infra dependencies.** No Prometheus client, no OpenTelemetry SDK, no Redis-backed breaker, no new sidecars. Stay inside FastAPI + asyncpg + SQLAlchemy + stdlib.
- **No DB schema changes in this task.** Status column stays `text`; the enum lives in Python only and validates on the way in. An alembic migration to native enum is a separate task if ever wanted.
- **No worker/scan_worker concurrency changes.** F-2's phase split touches `scan/service.py`'s transaction boundaries only; reclaim semantics, admission lock, and pool-size knobs are untouched.

## Assumptions (record-and-proceed; flag if wrong)

1. The auto-labeler call surface lives under `recognition/application/labeling/` and is reachable from a small number of call sites — F-1/F-3 wrapping there is mechanical. (**Open question 2** in the assessment: verify.)
2. The clustering admission `with_for_update()` lock is the only entrypoint that starts a clustering job; `scan_worker` does not concurrently launch a clustering job for the same tenant. (**Open question 1** in the assessment: verify before claiming F-8 stays deferred.)
3. `JobStatus` already covers `PENDING`/`RUNNING`/`COMPLETED`/`FAILED` ([domain/job.py:12](../../apps/prototype-description-service/recognition/domain/job.py#L12)) and `JobPhase` already covers `RETRYING`/`AWAITING_PROJECTION` ([domain/job.py:30](../../apps/prototype-description-service/recognition/domain/job.py#L30)). The slice's job is to *replace bare string literals at the remaining call sites*, not to introduce the enum. If grep turns up a status value not on either enum, expand the appropriate one and call it out in the slice note.
4. `AdapterCircuitBreaker` can share enough of `clustering_circuit_breaker.py`'s state machine that we extract a base class rather than copy-paste. If the existing breaker is too HTTP-coupled to share, the slice-1 implementation may instead introduce a new minimal breaker and refactor `clustering_circuit_breaker` to use it — that's still in scope.
5. Greenfield policy applies — no production users have in-flight scan jobs we must not break. Confirmed by the user via /scope intake.

## Not-doing list

- **F-4** (per-chunk asyncio.timeout) — deferred to a follow-up that depends on F-6.
- **F-5** (P50/P95/P99 chunk-latency histogram) — would require either Prometheus/OTel deps (excluded) or a structured-log convention not yet established.
- **F-8** (snapshot-isolation ADR) — defer; doc-only, low urgency.
- **F-9** (`chunk_commit_boundary` async context manager) — defer; mechanical wrap, low value until a second commit site appears.
- **F-10** (pool-utilization signal in adaptive sizing) — defer per the assessment; premature without F-1..F-3.
- **Retention/export pipeline status enum sites** ([retention.py:161,206](../../apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py#L161), [analyze.py:266](../../apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py#L266)) — left as bare strings for now. F-6 confines the enum migration to clustering + scan paths to keep the diff bounded.
- **Algorithmic clustering tuning** (HDBSCAN, HAC, chinese-whispers) — already declared out of scope by the assessment.
- **Schema migration to native Postgres enum** — not in this task; explicitly opt-out.
- **Frontend / WordPress plugin** — out of scope.

## Open questions to resolve during planning, not now

1. Per-adapter vs single shared breaker: is `InsightFace` failure correlated with auto-labeler failure? If they're independent backends, separate breakers; if they're the same upstream, one breaker. Implementer decides at slice 3 with a short note.
2. Where does the timeout settings module live — extend `db/settings.py`, add a sibling `recognition/application/settings/adapters.py`, or land it inside an existing settings package? Defer to the planning step for that slice.
3. Does the existing `clustering_circuit_breaker` already have unit tests we can lift into the new shared helper? Verify before deciding extract-vs-rewrite.

## Convergence

- **3+ targeted intake questions answered:** ✓ (4 questions via `AskUserQuestion`).
- **Answers recorded as MCP decision:** ✓ (`pds_pipeline_stability_intake_answers`).
- **Scope framing has explicit success criteria + Not-Doing:** ✓ (above).
- **Ready for planning artifact:** task plan should be drafted at `docs/tasks/pds-pipeline-stability-26-task-plan.md` (or similar) using this scope as the input.

## Next step

Hand off to the planning step. Suggested entry: `/planning-review` after a task-plan draft, or invoke a planner skill to turn this scope into a `docs/tasks/` task plan with concrete file changes per slice.

---

**Provenance:** Intake via `/scope` skill on 2026-04-27 against `feature/pds-pipeline-stability-26`. Source assessment merged to main as `97d1c9de` on 2026-04-26. Intake answers recorded as MCP decision on this branch (rev 1).
