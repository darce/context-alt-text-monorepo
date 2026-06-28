---
name: refactor-description-service
scope: project
description: Repo-tuned refactoring playbook for Python code in apps/prototype-description-service (FastAPI recognition/scene service, async ML inference, SQLAlchemy/Postgres, Docker/systemd self-host). Use when restructuring this app — extracting god modules (clusters.py, cluster_repository.py, assignment_writer.py, refresh_service.py), fixing async-correctness/stability/latency smells, or splitting concerns at service seams. Trigger phrases "refactor the recognition service", "this router/repository/service is too long", "blocking call in coroutine", "add timeouts/circuit breaker", "reduce p99/clustering latency", "split this god class", "extract pipeline stage". NOT for new features (use incremental-implementation), branch diff review (branch-review), bug hunts (investigate), or WP-plugin/TS refactors (refactor-wp-alt-context).
mode: execution
context_budget: 200
makefile_target: null
mcp_tools:
- get_handoff_state
- record_event
- review_findings
tdd_gate: false
---

## Global Instructions

- when reporting information back to user, be extremely concise. sacrifice grammar for the sake of concision

# Refactor: prototype-description-service

## Overview

Behavior-preserving restructure of the FastAPI async recognition/scene service. App: FastAPI (`api/main.py`) + uvicorn; hexagonal `recognition/{domain,application,infrastructure,interface_adapters}`; async (asyncio, SQLAlchemy async + asyncpg, Alembic); blocking InsightFace/onnxruntime quarantined via `run_in_executor`; separate-process worker `recognition/worker/scan_worker.py`. Deploy: `Dockerfile` (ARM64 CPU-only), `docker-compose.*.yml`, `systemd/`, Caddy. `scene/` is a ~8-LOC stub; `roster/` = idempotent curation-sync outbox replay. Consumer: WP plugin over HTTP (contracts `docs/workbay/contracts/`). Books distilled under `literature/extracted/refactoring/distilled/` (local-only; gitignored). Paths relative to `apps/prototype-description-service/` unless noted.

## Trigger

Use when:

- "refactor the recognition service", "this router/repository/service is too long"
- "blocking call in coroutine", "add timeouts/circuit breaker"
- "reduce p99/clustering latency", "split this god class", "extract pipeline stage"
- extracting god modules (`clusters.py`, `cluster_repository.py`, `assignment_writer.py`, `refresh_service.py`); fixing async-correctness/stability/latency smells; splitting concerns at service seams.

Do NOT use for:

- new features / behavior → `incremental-implementation`
- branch diff review before merge → `branch-review`
- bug hunt / root-cause → `investigate`
- WP plugin (PHP) or TS refactor → `refactor-wp-alt-context`

## Goal

Evidence-backed, smell-named, behavior-preserving refactor in small verified slices, MCP-recorded. Each move: named from the catalog, grounded in real file/lines (Phase A verified), gated green, decision recorded with distilled-doc citation. Two Hats — never add behavior + restructure same step. Don't tune perf during refactor; profile after on well-factored code (Fowler Ch2; Farley measure-don't-guess).

## Canonical Policy

Gates BEFORE any edit:

- **Branch isolation** — NEVER edit code on `main`. `make task-start TASK=<id> OBJECTIVE="..."` first (branch+worktree+MCP target); PreToolUse hook blocks code on main. Work from `target_worktree_path`.
- **Tests-first safety net** — no self-checking tests = mutation, not refactoring. Missing coverage → write **characterization test** (capture current behavior, even if "wrong") first. Entry `recognition/tests/{unit,api,integration}/`. Configurable in-memory fakes (`recognition/tests/fakes.py`), never always-None (false positives — testing-python.md).
- **Format before lint** — `make format` (= `ruff check --fix --unsafe-fixes` + `ruff format`) before hand-fixing lint.
- **MCP handoff (mandatory)** — after code changes: `record_event(event={event_kind:"decision",...})`, notify user "Handoff updated: decision `<id>` recorded.", then `render_handoff(kind='dashboard')`. Without both = incomplete.
- **Pre-merge gate** — no merge to main without `handoff_close_check(enforce=True)`: ≥1 review pass, zero open findings (or deferred w/ rationale), fresh `test_result` at HEAD SHA, slice-complete decision.
- **Greenfield** — NO migrations. Schema → directly into `db/migrations/versions/001_identity_schema.py` (single baseline) + `db/models.py`, then `alembic check`. Clean rewrites over compat shims. Delete-over-flag. No data to preserve.

Repo short/regression rules that gate moves (don't refactor *into* a violation):

| Rule | Constraint | App anchor |
|---|---|---|
| sr-006 | `assert` only for internal invariants/tests; request/external-data validation raises explicit exceptions/HTTP errors | — |
| sr-007 | status/domain values are `StrEnum`/`IntEnum`, single canonical def; don't scatter `== "pending"` | canon: `domain/job.py`, `domain/suggestion.py`, `domain/maturity.py`, `shared/health.py`; live smell `application/suggestions/label_inference.py:132`, `cluster_repository.py:1205` compare `resolution == "pending"` raw |
| sr-008 | >8 destructured params → 2–3 typed objects | model `ScanWorkerConfig` |
| sr-009 | transactions via shared `run_transactional(callable)`, not inline START/COMMIT/ROLLBACK | — |
| rg-002 | preserve atomic write paths; don't split a backend atomic op into multiple steps | — |
| rg-007 | long loops: bounded stall detection, one unit's failure ≠ halt others, exit non-zero after no-progress threshold | `scan_worker.run_forever`/`_main` |
| rg-008 | multi-module config validated at load, not silent defaults | — |
| rg-009 | no `if task_ref == ...` / hardcoded domain strings in generic modules → config/policy | — |
| rg-015 | boundary adapters never fabricate contract metadata (`limit/offset/total`, `data_source`, projection status); every envelope field from request/upstream/documented-fallback | snapshot/delta/members in `schemas/responses.py` + cluster router |

Hexagonal layer rules (backend-python-guidelines.md): no raw SQL outside `infrastructure/repositories/`; no `contextlib.suppress(Exception)`; no `getattr` duck-typing on Protocols; no presentation DTOs in domain/application; inject settings (no default-instantiated `ClusteringSettings()`); functions <40 lines.

## Core Process

Ordered loop. Two Hats: never add behavior + restructure same step.

1. **Identify the smell** — name from catalog; locate real file/lines. Cross-check terminal `grep -n`/`wc -l` if IDE output stale (rg-010).
2. **Verify test coverage** — run touching tests. Absent → write **characterization test** in `recognition/tests/{unit,api,integration}/`. Configurable fakes, not always-None.
3. **Small reversible change** — one Fowler move. Remove blocking temps before extracting. Green-able in minutes.
4. **Run gates** — `make test` (pytest, fast loop). Before review: `make format` then `make check` (= lint+typecheck+test = ruff+mypy+pytest); `alembic check` if schema touched.
5. **Record handoff** — `record_event(event={event_kind:"decision",...})`, pass full 40-char SHA from `git rev-parse HEAD`; notify user; `render_handoff(kind='dashboard')`.
6. **Next** — smallest next step. Test fails + cause not obvious in <2 min → revert to last green, redo smaller.

### Smell catalog — structural / cohesion

Each: where it lives · sign · fix (book §).

- **God router** — `interface_adapters/http/routers/clusters.py` (1679 LOC, ~30 endpoints). Sign: one file changes for cluster CRUD + topology + snapshots + deltas + maintenance + admission. → Divergent Change: Extract Function on fat handlers (<40 lines), then Move Function / Split Phase into cohesive routers (topology / snapshot / maintenance); register in `api/main.py` (Fowler Divergent Change, Split Phase, Move Function).
- **God repository** — `infrastructure/repositories/cluster_repository.py` (1439). Sign: UUID coercion, media-identity bootstrap, inline+duplicated query-building. → Extract shared utils to `infrastructure/repositories/_helpers.py` (hex rule 10); Extract Class for query groups (Fowler Large Class).
- **God service / large class** — `application/persistence/assignment_writer.py` (1097, `AssignmentWriter` ~30 methods: persist / centroid recompute / rep selection / curriculum-T / MV refresh); `application/suggestions/refresh_service.py` (835). Sign: method/field clusters by responsibility. → Extract Class per cluster; module-level pure helpers (`_compute_identity_quality`, `_select_diverse_representatives`) already extracted — continue (Fowler Large Class; Modern-SWE Ch10).
- **Mixed abstraction at a seam** — handler doing business logic + raw persistence + HTTP shaping in one scope. → Ports & Adapters: domain/application return domain types, translate at `interface_adapters` boundary (Modern-SWE Ch11/12; "and" in a description = SoC violation).
- **Repeated switch / scattered status string** — status compared as literals across files. → Replace Conditional with Polymorphism or import the `StrEnum` (sr-007; Fowler Repeated Switches).
- **Primitive obsession** — bbox tuples, bare `np.ndarray` embeddings, confidence floats threaded through signatures. → Replace Primitive with Object / Introduce Parameter Object where behavior accretes (sr-008).
- **Broad except (deodorant)** — ~95 `except Exception` / `contextlib.suppress` under `recognition/`. Sign: swallowed errors, no log. → narrow `except`, log ≥WARNING (hex rules 2 & 11); distinguish system vs app failure so breakers don't falsely trip (Nygard §5.5).

### Smell catalog — async-correctness (Hattingh — HIGH)

- **Blocking call in coroutine** — sync CPU/IO (InsightFace `.get`, PIL/cv2 decode, blocking DNS, `subprocess`) awaited directly stalls the loop. Sign: coroutine calls sync ML/IO fn with no `run_in_executor`/`to_thread`. Model `infrastructure/embeddings/__init__.py:156`. NOTE `_bytes_to_cv2`/`_pil_to_cv2` decode runs sync inside `detect_faces` before the executor hop — fold into the offloaded callable. → executor quarantine (Hattingh "Running Blocking Code").
- **Missing timeout on outbound call** — `httpx.AsyncClient` / `await` on network/DB with no deadline. Tool: `application/integrations/timeouts.py` `wait_for_adapter(coro, timeout_s, adapter_name)` → `AdapterTimeoutError`. Worker is good (`scan_worker.py:193` `timeout=30.0`); audit every other outbound path. → wrap (Nygard §5.1).
- **Fire-and-forget task** — `create_task(...)` whose exception is never awaited → "Task destroyed but pending" or silent swallow. Sign: bare `create_task`/`ensure_future` (`ensure_future` is framework-only). Correct pattern `worker/handlers/scan.py:119` `gather(*..., return_exceptions=True)`. → await or track+gather (Hattingh Pitfalls).
- **Unsafe shutdown/cancellation** — `except CancelledError: pass` without cleanup+re-raise; executor jobs outliving the loop. Models `domain/services/purge_service.py:run_forever` (`wait_for(shield(stop_event.wait()), timeout=)`), `scan_worker._main`. → cancellation-safe cleanup, `gather(return_exceptions=True)`, drain executor (Hattingh Startup/Shutdown). Uvicorn `--timeout-graceful-shutdown` (`make serve`).
- **Unbounded queue / no back-pressure** — producers outrun consumers. App bounds via `claim_batch_size`/`max_concurrency` + Postgres `SKIP LOCKED`. Sign: new `asyncio.Queue()` without `maxsize`, or unbounded claim. → bounded queue + drop/throttle (Hattingh Queues; Enberg §10.5).
- **Default-instantiated settings in async fn** — `RecognitionSettings()`/`ClusteringSettings()` inside a coroutine bypasses DI, reloads per call. → inject (hex rule 6; rg-008).

### Smell catalog — stability (Nygard — HIGH)

- **Integration point without breaker** — InsightFace runtime / DB session / embedding HTTP call unwrapped. Breakers exist: `interface_adapters/http/deps/circuit_breaker.py`, `clustering_circuit_breaker.py`, `application/integrations/circuit_breaker.py`. → Circuit Breaker, pair with Timeouts (Nygard §5.2).
- **Unbounded result set** — cluster/member/snapshot `select(...)` without LIMIT → OOM at scale (`list_clusters`, `list_cluster_members`, snapshot/delta). → LIMIT at caller + honest pagination (Nygard §4.11 Black Monday; rg-015).
- **Missing fail-fast on startup** — traffic before deps ready. App does it: `_check_dev_key_guard`, `validate_production_security`, worker `wait_for_database`. → Fail Fast (Nygard §5.5); helpers in `application/health.py`+`shared/health.py` (`/health`,`/ready`,`/health/detailed`).
- **No bulkhead between stages** — scan/clustering/split share one budget; one stall starves others. → separate concurrency per stage (Nygard §5.3); build on `_clustering_admission_probe` + `_acquire_tenant_lock_fast_fail`.
- **Steady-state leak** — unbounded cache / unrotated log / un-purged table. App handles via `make logs-rotate`+`WatchedFileHandler`, `purge_service`, `recognition/config/cache.py`. → bound size/TTL, purge, rotate (Nygard §5.4).
- **Aggressive retry / no backoff** — tight retry hammers a struggling dep. App: exponential backoff `scan_worker._main` (`min(backoff*2, 60)`). → backoff + breaker (Nygard §4.3).

### Smell catalog — latency (Enberg — HIGH)

- **Averages not percentiles** — mean latency of analyze/clustering. → p50/p95/p99; beware fan-out tail amplification (snapshot over many members), coordinated omission in benchmarks (Enberg §2.2, §2.5).
- **N+1 / chatty queries** — `await repo.get(x)` inside a `for` (enrich-labels, member responses). → one coarse batched query (Enberg §7; Nygard §9.9).
- **Per-image inference, no batching** — detector per image when model can batch. App batches at claim level; push batching into the executor call (Enberg §10.2.2).
- **Recompute of derived data** — centroids/reps recomputed on read instead of read from MV (`refresh_centroids_view`, `_refresh_mv_if_needed`, `centroid-health`). → incremental/MV (Enberg §6.8, §11.4.1).
- **Missing/uninvalidated cache** — repeated identical DB/compute for hot keys (`recognition/config/cache.py`). → cache-aside/read-through, TTL+size bound, negative caching, memoize pure transforms (Enberg §6).
- **O(n²) clustering/similarity** — nested loops in `application/{clustering,similarity,discovery}`. → cut complexity before parallelizing (Enberg §7.2; Amdahl §2.1.2 — serial section dominates).

### Smell catalog — data-contract (Kleppmann — MEDIUM)

- **Breaking API/DB schema change** — removing/renaming a field the WP plugin consumes; reusing a column/tag. → additive-only, new fields nullable/defaulted, never repurpose; backward-compat requests + forward-compat responses (Kleppmann Ch4; `docs/workbay/contracts/{recognition-clustering,curation-sync-api}.md`).
- **Non-idempotent replay** — curation-sync / topology command applied twice. App keys it: `_load_topology_replay`/`_store_topology_replay`, idempotency_key. → dedupe (Kleppmann Ch11; roster/).
- **Lost update / write skew on topology** — concurrent merge/split/reassign without version guard. App guards: `_get_cluster_backend_version` + `_raise_if_cluster_stale` (optimistic CAS). → CAS / `SELECT FOR UPDATE` (Kleppmann Ch7).
- **Source-of-truth vs derived confusion** — treating centroid MV / snapshots as authoritative; they're *derived* (recreatable). Keep the distinction (Kleppmann Part III).

Move-set, grouped by source (catalog above names smells+fixes inline; this is the toolbox).

### Playbook — async (Hattingh)

Executor quarantine: wrap blocking inference/decode in `await loop.run_in_executor(None, fn, *args)`/`to_thread`, fold sync decode into the offloaded callable (model `infrastructure/embeddings/__init__.py`). Cancellation-safe shutdown: propagate `CancelledError` after cleanup, `gather(*pending, return_exceptions=True)`, dispose executor+engine. Bounded queues: every `asyncio.Queue` gets `maxsize` + drop/block policy; honor `max_concurrency`; per-unit queue so one slow item ≠ stalled batch. `create_task` only (never `ensure_future`); no task creation in `CancelledError` handlers.

### Playbook — stability (Nygard)

Timeouts on every outbound call (`wait_for_adapter`, httpx timeout). Breaker around each integration point (reuse the three; distinct open-exception; log+query state). Bulkheads = separate concurrency budget per stage (scan/clustering/split). Fail fast: check deps at transaction start, surface via `/ready`; distinguish system vs input failure. Steady state: bound caches (size+TTL), purge tables, keep log rotation.

### Playbook — latency (Enberg)

p50/p95/p99 not means (watch fan-out tail amplification, coordinated omission). Eliminate work: kill N+1 via batched queries, drop quadratic similarity, cut redundant serialization. Bounded cache-aside/read-through + keep centroid MV as derived fast path, incremental over full recompute. Batch inference in the executor call where the model supports multi-image.

### Playbook — data (Kleppmann)

Schema evolution additive/nullable/defaulted, never reuse columns/tags (backward-compat requests, forward-compat responses for WP contract). Idempotent: dedupe by key (roster replay, topology commands). Derived-data: clusters/identities/roster = source of truth; MV/snapshots/suggestions = recreatable derived — rebuild, don't mutate in place.

### Playbook — structural (Fowler/Farley)

Extract Function (Long Function, <40 lines); Extract Class (god-class clusters); Split Phase (inference → persistence → HTTP shaping); Move Function (Feature Envy/Divergent Change); Replace Conditional with Polymorphism (model assignment `checks/` Strategy); Introduce Parameter Object (sr-008, model `ScanWorkerConfig`); Replace Derived Variable with Query (MV/source drift); Separate Query from Modifier (CQS repo reads). Testability via DI at seams: inject Protocols (`FaceDetectorProtocol`, `EmbeddingGeneratorProtocol`) — DI is the "caliper" (Farley Ch14); Null Object adapters (`Stub*`/`Unavailable*`) model graceful-degradation — reuse, don't null-check at call sites.

## Common Rationalizations

- "it's async already" → blocking sync call inside a coroutine still stalls the loop; quarantine via `run_in_executor`/`to_thread` (Hattingh).
- "mean latency is fine" → p99 governs UX; fan-out amplifies tail, coordinated omission hides it. Measure percentiles (Enberg §2.2).
- "just add a compat shim" → greenfield: rewrite the module, delete-over-flag. No backward-compat layers, no data to preserve.
- "broad except keeps it running" → masks failure, no log, falsely trips breakers. Narrow + log ≥WARNING, distinguish system vs app (Nygard fail-fast §5.5).
- "I'll batch the perf fix into this extract" → Two Hats violation. Restructure first, green, then tune separately (Fowler Ch2).
- "this status string is obvious" → scattered literals drift (sr-007 live smell at `label_inference.py:132`, `cluster_repository.py:1205`). Import the `StrEnum`.

## Red Flags

Do NOT refactor when:

- **No tests + no time for a characterization test** — refactoring untested code is mutation. Stop; add the test or defer.
- **Out of task scope** — change unrelated to active `task_ref`. Note it (litter-pickup only if trivial + same file); don't scope-creep.
- **Would break the WP-plugin contract** — any change to `recognition-clustering` / `curation-sync-api` response shape consumed downstream needs additive evolution + contract review, not a refactor (Kleppmann Ch4; rg-015).
- **Greenfield says rewrite, not shim** — module needs a backward-compat shim to evolve → clean rewrite, delete-over-flag.
- **Code you don't need to change** — Fowler: don't refactor off-path code. `scene/` stubs: leave until there's real behavior to structure.
- **Atomic write path** — don't split a backend atomic op into multiple steps (rg-002). Preserve transaction boundaries (`run_transactional`, sr-009).

In-flight warning signs (stop, reassess):

- red test more than one step back — revert to last green, re-slice smaller.
- a WP-plugin-facing contract change creeping into the diff.
- editing on `main` (hook should block; if not, stop and branch).
- unbounded result set introduced (`select(...)` without LIMIT).
- new scattered status literals instead of the `StrEnum` (sr-007).

## Recovery

- **Broken mid-refactor** — revert to last green commit, re-slice smaller. Test fails + cause not obvious in <2 min → don't debug forward, revert.
- **Provenance/context-drift warning on a handoff write** — `cd` to the task's canonical `target_worktree_path` and retry there; Bash Python-API fallback writes must begin `cd <target_worktree_path> &&` and pass `task_ref='<ref>'`.
- **Gate fails** (lint/format) — `make format` first, then hand-fix remaining; re-run `make check`.
- **Smell needs feature-scale work** (contract evolution, cross-module rewrite) — out of refactor scope. Record a finding via `review_findings(review={"operation":"record",...})` and defer; don't expand the slice.

## Convergence Criteria

Done when:

- `make check` green at HEAD (ruff+mypy+pytest; `alembic check` if schema touched).
- behavior unchanged — tests prove it (characterization/unit/api/integration pass, no new behavior added).
- decision recorded via `record_event(event={event_kind:"decision",...})` with full 40-char SHA, AND user notified ("Handoff updated: decision `<id>` recorded."), AND `render_handoff(kind='dashboard')`.
- no unrelated diff hunks (single-smell, scoped to active `task_ref`).
- decision rationale cites the distilled doc / book § driving the move.

## See Also

Source map — all docs under `literature/extracted/refactoring/distilled/` (local-only reference: `literature/` is gitignored and absent on fresh clones/CI — the skill is self-contained without it; consult the docs when present):

| Book (doc) | Sections used | Rating / applicability |
|---|---|---|
| Hattingh `using-asyncio-in-python.md` | Ch3 Startup/Shutdown, Running Blocking Code, Queue back-pressure, Decision Rules, Pitfalls | **HIGH** — executor quarantine, cancellation-safe shutdown, bounded queues, `create_task` discipline |
| Nygard `release-it.md` | Ch4 Integration Points/Cascading/Slow Responses/Unbounded Result Sets/Blocked Threads; Ch5 Timeouts/Breaker/Bulkheads/Steady State/Fail Fast; Ch14.3; Ch17 logging | **HIGH** — app already has breakers/timeouts/health/rotation; extend per stage |
| Enberg `latency-reduce-delay-in-software-systems.md` | Ch2 percentiles/coordinated omission; Ch6 caching/MV; Ch7 eliminating work; Ch10 batching/backpressure; Ch11.4.1 incremental | **HIGH** — inference latency, centroid MV, N+1, batching, fan-out tail |
| Kleppmann `designing-data-intensive-applications.md` | Ch4 Encoding/Evolution; Ch7 Transactions (lost update/write skew/CAS); Ch11 idempotent processing; Part III system-of-record vs derived | **MEDIUM** — contract evolution, idempotent replay, version guards; consensus chapters N/A (single-node PG) |
| Fowler/Beck `refactoring-fowler-beck.md` | Ch1 process; Ch2 Two Hats; Ch3 smells; Ch6–8 Extract/Move/Split Phase; Ch10 polymorphism; Smells→Refactoring table | **HIGH (core)** — language-agnostic moves |
| Farley `modern-software-engineering.md` | Ch10 Cohesion; Ch11 SoC/Ports & Adapters; Ch12 abstraction; Ch13 coupling; Ch14 testability via DI | **MEDIUM** — cohesion/coupling rubric for *where* to cut |
| De Sousa `refactoring-typescript.md` | Null Object/Special Case; Strategy over enum switch; Guard Clauses; CQRS | **LOW** — only language-agnostic patterns (better from Fowler); reinforcement only |
| Wathan/Schoger `refactoring-ui.md` | — | **NONE** — visual design only; headless service has no UI |

Related skills: `branch-review`, `investigate`, `tdd`, `refactor-wp-alt-context`.
