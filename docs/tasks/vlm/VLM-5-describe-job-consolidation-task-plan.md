# Task Plan: VLM-5 Describe Job Consolidation

> **Metadata**
>
> - **Date**: 2026-07-09 EST
> - **Author**: Claude (Fable 5)
> - **Realigned**: 2026-07-12 (VLM-REALIGN-01, Claude Fable 5) — design unchanged and premises re-verified (both job systems live on `main`); line anchors refreshed against current code per `VLM-REALIGN-01-anchor-audit-20260712.md`; launch framing added (the false-404 class this task deletes is a silent failure toward the user [RLSE-05], and the restart/interruption cases are the adversarial-user matrix [RLSE-06]). Runs parallel-safe alongside VLM-3 Slice 7 (activation touches infra/env/evidence only; this task touches service code).
> - **Project**: apps/prototype-description-service
> - **Task ID**: `VLM-5`
> - **Target Branch**: `feature/vlm-5`
> - **Review Coverage Target**: 2

---

## VLM-5. Consolidate the volatile async describe job store onto the durable describe-run system

## Objective

Delete the in-memory `InMemoryDescribeJobStore` job system and re-home the single-image CPU-provisional → GPU-final async describe lifecycle onto the DB-backed `describe_run` tables (WBUX-3/WBUX-4). One durable job system: GPU results cached and audited, no eviction-induced false 404s, restart reclaim covers accepted async jobs. Resolves deferred finding VLMRP-S4-05 (link ID only; body lives in handoff DB).

## Problem Statement

Two parallel job systems exist in `apps/prototype-description-service`:

1. **Volatile single-image async path** — `scene/application/describe_jobs.py` (`InMemoryDescribeJobStore`), worker `scene/application/description_worker.py` (`run_describe_job`), routes `POST /scene/describe/async` + `GET /scene/describe/jobs/{job_id}` in `scene/interface_adapters/http/routers/describe.py`. Process-local dict; FINAL results are evictable before the client polls (`_evict_over_capacity_locked`) → false 404; restart loses every accepted job; GPU output is never persisted to `image_descriptions` cache nor durably auditable.
2. **Durable bulk path** — `db/models/scene.py` `DescribeRun`/`DescribeRunItem` tables, repository `scene/application/describe_run_repository.py`, worker `scene/application/describe_run_worker.py` (also named `run_describe_job` — a live name collision, see [NAME-05]), routes in `scene/interface_adapters/http/routers/describe_run.py`, startup reclaim `run_startup_reclaim` (df91d140), per-item drafts exposure (9045904c).

Duplication violates single-system-of-record [DATA-14] and forfeits the durable system's reclaim [RES-07]. The user-visible failure class is the worst kind: a poll that 404s on a job the service accepted (eviction) or silently forgets (restart) leaves the caller believing the work never existed — silent failure toward the user, P0 by definition [RLSE-05]. The consolidation must preserve the VLMRP/VLMFIX hardening already landed on the volatile path: job timeout (`asyncio.wait_for` in `run_describe_job`, VLMFIX-S1-04), retained-image byte-budget backpressure → 503 (`_DEFAULT_MAX_RETAINED_IMAGE_BYTES` = 256 MiB at `describe_jobs.py:50` enforced at `describe_jobs.py:80-81`, plus `max_jobs=1000` at line 59; VLMRP-S4-07), tenant-scoped polling (VLMFIX-S1-06), and the GPU idle-reaper load snapshot (`write_load_snapshot`, VLMFIX-S2-01, consumed by `infra/oci/gpu_lifecycle/reaper.py` via `/run/acx/describe-load.json`).

## Constraints

- Greenfield: schema changes go directly in `db/migrations/versions/001_identity_schema.py`; no data migrations, no compatibility shims. Delete `describe_jobs.py`/`description_worker.py` outright (delete-over-flag).
- The 17-field response envelope (`packages/shared-contracts/schemas/image-description-response.schema.json`; `VisualFactsResponse` core fields + `tier` + `result_generation`) must not change. `DescribeJobResult` poll shape (`job_id`, `status`, `tier`, `result_generation`, `visual_facts`, `error`) stays wire-identical.
- Single-process worker assumption stands (documented in `reclaim_interrupted_runs` S5-05); this task does not add multi-replica ownership guards.
- Plugin boundary: only files under `apps/prototype-description-service/`, `infra/oci/` docs, and `docs/` change. Reaper CLI contract (`--load-json` JSON keys `queue_depth`/`in_flight`/`written_at`) is unchanged.
- Tests follow `docs/workbay/rules/testing-python.md` (pytest, `pytest-asyncio`, spec'd mocks [TEST-13], SQLite session fixtures as in `scene/tests/test_describe_run_repository.py`).

## Workflow Principles

- One system of record for job state; memory holds only per-process operational concerns (admission counters) [DATA-14], [ARCH-02].
- Growth needs a purge shipped in the same release [RES-07]; replace eviction with retention.
- HTTP layer projects DB rows into the existing poll contract; storage shape never leaks into the wire shape [API-10].
- Every done-claim in slices carries the command and decisive output line [AGT-04].

## Terminology

- **Async job**: one single-image describe accepted at `POST /scene/describe/async`, polled at `GET /scene/describe/jobs/{job_id}`.
- **Bulk run**: multi-item `POST /scene/describe/run` lifecycle (unchanged in semantics).
- **Supersede lifecycle**: CPU adapter produces a `provisional_cpu` result (generation 1), GPU adapter supersedes with `final_gpu` (generation 2); GPU failure after a provisional yields `degraded`.

## Current State Analysis

- Works: bulk runs persist, reclaim at startup (`run_startup_reclaim` wired in `api/main.py` `_lifespan`, lines ~118–134), per-item drafts endpoint, cancel; volatile path has timeout/backpressure/tenant fixes and atomic load-snapshot writes.
- Broken/drifting: async results are uncached (never written through `ImageDescriptionRepository`) and evictable; restart drops accepted jobs silently (violates [RES-07]); audit events for async jobs exist but the result payload itself is volatile; two functions named `run_describe_job` in sibling modules ([NAME-05]).
- Misleading: `describe_jobs.py` docstring claims "replace this class with a shared DB/Redis store" as future work — the DB store already exists one directory over.

## Target Outcome

`POST /scene/describe/async` creates a one-item `DescribeRun` (`run_kind='single'`) whose item carries the full visual-facts envelope per tier. A new DB-backed worker `run_async_describe_job` in `scene/application/describe_async_worker.py` executes the supersede lifecycle with the same timeout/audit/metrics behavior as today's `description_worker.run_describe_job`, which is deleted along with `InMemoryDescribeJobStore`; the GPU-final envelope is additionally written through to the `image_descriptions` cache in the same commit. Poll status is a pure, total projection from item state. Backpressure is an in-memory per-process admission gate preserving today's retained-byte budget and job cap → 503, with structurally paired acquire/release (try/finally) so a crashed worker or failed enqueue can never leak a slot. The GPU reaper load snapshot is written from DB-derived counts by a small dedicated module, preserving the atomic tmp+rename write. Startup reclaim covers async jobs: an interrupted job with a persisted provisional lands `degraded` (result preserved), otherwise `failed`. A retention purge deletes terminal single-item runs after a bounded age — no eviction, no false 404 inside the retention window.

### Design tensions resolved

**(a) Migrate async routes onto describe_run tables vs a supersede-tier extension as a second table.** Chosen: migrate onto the existing tables, extending `DescribeRunItem` with result columns (`visual_facts` JSON, `tier`, `result_generation`) and `DescribeRun` with `run_kind` (`'bulk'|'single'`). The volatile store's `result_fetched` flag is NOT carried forward: its only consumer today is the eviction preference for fetched terminal jobs (`_evict_over_capacity_locked`, `describe_jobs.py:220`), and design (d)'s age-only retention deletes that consumer — a `result_fetched_at` column would ship with zero readers (delete-over-flag, [REF-12]); reintroduce it only if a concrete consumer (e.g. fetched-aware early purge) is scheduled. One writer, one schema, one reclaim path [ARCH-02], [DATA-14]; the poll contract is met by projection, so the extra run-level counters a single-item run carries are dead weight but harmless. Counter-case: a dedicated `describe_jobs` table would avoid widening the shared item row and keep bulk-run rows lean; rejected because it re-creates a second lifecycle (own reclaim, own retention, own tenant scoping) — exactly the duplication being removed, and the split fails the disintegrator test [ARCH-01].

**(b) What stays in memory vs DB.** Chosen: DB owns results, audit linkage, status, reclaim, retention (durable facts); memory owns only the admission gate. The gate preserves today's backpressure semantics with the real symbols [AGT-02]: a per-process retained-image-bytes counter capped at `ACX_ASYNC_MAX_RETAINED_IMAGE_BYTES` (default 256 MiB = `_DEFAULT_MAX_RETAINED_IMAGE_BYTES`, `describe_jobs.py:50`, enforced today at `describe_jobs.py:80-81`) plus a non-terminal job-count cap `ACX_ASYNC_MAX_PENDING_JOBS` (default 1000 = the store's `max_jobs`, `describe_jobs.py:59`). Both defaults equal the current store's, so the wire-visible 503 threshold does not move (recorded in the Contract and Boundary Impact table) and design goal "503 before the DB accumulates unbounded `image_bytes`" holds byte-for-byte [RES-14].

Admission lifecycle [RES-04], [CON-11]: `try_acquire(image_len)` reserves bytes+slot at enqueue; release is structurally paired, never best-effort — (1) the enqueue path wraps `create_single_run` + commit in try/except and releases on any raise before re-raising; (2) the worker task body runs inside try/finally whose `finally` always releases (the exact pattern of today's `_run_describe_job_and_dump_load`, `describe.py:616-620`), which covers the `CancelledError` path after `set_item_failed` and any bug/session-factory failure before the worker's own try block. **Invariant: a reservation is held only for the lifetime of an in-process enqueue-or-worker task and is never derived from DB rows.** Consequently the counter starts at 0 on every boot with no DB seeding; startup reclaim independently drives orphaned non-terminal rows terminal, so a failed (best-effort) reclaim cannot wedge admission at permanent 503 — orphaned rows hold no reservations by construction. Counter-case A: DB-count-seeded admission (`count_active_single_runs()` at boot) looks crash-consistent but is not — reclaim is best-effort and never blocks boot, so on reclaim failure the seed counts orphaned rows no worker will ever release, and `purge_expired_single_runs` only deletes terminal runs; leaked slots then 503 every enqueue until a lucky restart. Rejected. Counter-case B: per-enqueue DB `SELECT count(*)`/`sum(bytes)` survives multi-process deployment; rejected — single-process by documented assumption, adds hot-path latency, and inherits the same orphaned-row wedge. Queue ordering disappears: BackgroundTasks already executes per-request; there is no cross-request queue to preserve. Counter mutations under a `threading.Lock` [CON-16].

**(c) Reaper load-snapshot source.** Chosen: DB-derived counts. New module `scene/application/describe_load.py` exposes `load_snapshot(session) -> dict` (queued = items with `status='queued'` on non-terminal `run_kind='single'` runs; in_flight = `status='running'`) and `write_load_snapshot(payload, path)` preserving the atomic tmp-write + `os.replace` and `written_at` staleness key from `describe_jobs.py:write_load_snapshot` [DATA-16]. Callers (`enqueue`, worker-terminal, terminal poll) write after commit, matching today's trigger points. Counter-case: keeping in-memory counters is cheaper per write; rejected because post-restart the memory counters read 0 while reclaim may still be flushing — DB counts and the reaper's stale-file-is-busy rule stay mutually honest [DIAG-02]. Bulk-run items are intentionally excluded (current snapshot never counted them; widening reaper semantics is out of scope — recorded as a stretch goal).

**RLS session discipline for global ops** (applies to `load_snapshot` counts here and `purge_expired_single_runs` in design (d)): these are cross-tenant operations, but every request/worker session is tenant-scoped — `set_tenant_context` RESETs `app.bypass_rls` and `SET LOCAL`s `app.current_tenant` (`db/tenant_context.py:65-66`), and bypass is itself a transaction-scoped `SET LOCAL app.bypass_rls = 'true'` (`db/tenant_context.py:77`, `enable_rls_bypass` at line 109). A global op must therefore run on a **dedicated short-lived session** opened from `async_session_factory` with `enable_rls_bypass` applied, committed/closed inside the call — **never the tenant-scoped request or worker-phase session**. Reusing the request session either trips `_require_rls_bypass` (fail-closed) or, if the guard were skipped, silently scopes counts/purge to one tenant — a busy GPU reads as idle and purge leaks other tenants' rows [DIAG-02], [SEC-01]. This applies at every snapshot trigger (enqueue, worker-terminal, terminal poll) and at the per-enqueue purge. Proof: two-tenant tests assert `load_snapshot` counts and `purge_expired_single_runs` deletions span tenants on a bypass session, and fail closed on a tenant-scoped one (Slices 1 and 3).

**(d) Eviction semantics → retention policy.** Chosen: delete `_evict_over_capacity_locked` semantics entirely; add `purge_expired_single_runs(now, retention)` to `DescribeRunRepository` deleting terminal `run_kind='single'` runs older than `ACX_ASYNC_JOB_RETENTION_HOURS` (default 24) — run at startup after reclaim and opportunistically per enqueue, each on a dedicated short-lived bypass session per design (c)'s RLS session discipline (the purge is cross-tenant; the enqueue request session is tenant-scoped) [RES-07]. Schema change lands directly in `001_identity_schema.py` (greenfield). Within retention, a terminal result is always pollable — the S1-05 "evicted between get and mark" race ceases to exist. Counter-case: unbounded retention would maximize pollability but violates steady-state reclaim; 24h is far beyond any real poll interval.

**(e) Restart reclaim for in-flight GPU jobs.** Chosen: extend `reclaim_interrupted_runs` — for a `run_kind='single'` item that is non-terminal but has persisted provisional `visual_facts`, mark it `completed` with `last_error='interrupted by service restart'` (projection → `degraded`, provisional result preserved and pollable); with no provisional, mark `failed` as today. No auto-re-enqueue. Counter-case: re-enqueueing at boot would deliver the FINAL tier, but re-runs GPU inference without an idempotency key on the client contract ([RES-01], [DATA-13]) and contradicts the bulk path's fail-honest reclaim; the client's remedy is resubmission, which the cache row written by the worker (Slice 2 cache-write item) makes cheap.

**(f) `ACX_ASYNC_ALLOW_EMPTY_TENANT_CLAIM` bypass (`describe.py:575-576`).** Chosen: delete the env bypass (greenfield, delete-over-flag); an empty tenant claim always 400s on both enqueue (today `describe.py:575-576`) and poll (today `describe.py:628-630`). The DB path makes the bypass incoherent: `image_description_runs.tenant_id` is NOT NULL, enqueue must `set_tenant_context`/`require_tenant_record` (`describe.py:578-579`), and RLS scopes reads — an empty-claim job would need a fabricated tenant, producing rows that are unfetchable or wrongly tenant-attributed. Counter-case: a sentinel "system" tenant would preserve the admin opt-in; rejected — it pollutes `image_descriptions` cache and audit rows with a fake tenant and re-opens the unfetchable-work hole VLMFIX-S1-06 closed. Wire-visible change recorded in the Contract and Boundary Impact table; existing 400-rejection tests are the proof.

**(g) Single runs reachable via bulk-run endpoints.** Chosen: `GET /scene/describe/run/{run_id}`, `GET .../items`, and `DELETE .../{run_id}` (cancel) in `describe_run.py` return 404 for `run_kind='single'` runs — the two wire surfaces stay disjoint, and external cancel of an async job (which would drive items to `skipped`/run to `cancelled` and interact undefinedly with the admission counter) becomes unreachable [REF-20]. Defense in depth: `describe_job_status(item)` is still **total** over every `DescribeItemStatus` — `skipped` projects to `failed` with `error='cancelled'` — so no future path into cancel can crash the poll handler. Counter-case: mapping cancelled/skipped into the poll contract instead would let the WBUX UI cancel async jobs through the bulk API; rejected as an unrequested capability that couples the admission counter to an external writer.

## Context Loading

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/backend-python-guidelines.md`
- Contracts: `packages/shared-contracts/schemas/image-description-response.schema.json`; reaper JSON contract in `infra/oci/gpu_lifecycle/reaper.py` module docstring
- Handoff/MCP: task ref `VLM-5`; deferred finding VLMRP-S4-05 (query via `review_findings`, do not restate here)
- Code anchors (all verified): `scene/application/describe_jobs.py`, `scene/application/description_worker.py`, `scene/application/describe_run_repository.py`, `scene/application/describe_run_worker.py`, `scene/domain/describe_run.py`, `scene/interface_adapters/http/routers/describe.py`, `scene/interface_adapters/http/routers/describe_run.py`, `db/models/scene.py`, `db/migrations/versions/001_identity_schema.py`, `api/main.py` (lifespan reclaim block)

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `POST /scene/describe/async` + `GET /scene/describe/jobs/{job_id}` | backend | `DescribeJobResult` in `scene/interface_adapters/http/schemas/responses.py` | none on the wire; `job_id` now a run UUID string | yes — sole current consumers are the service's own tests (`scene/tests/test_describe_route.py`); the WP plugin does NOT call these routes today — it uses sync `/scene/describe/multipart` (`class-describe-media-service.php:181`, reached via the controller's `describe_media` delegation) and bulk `/scene/describe/run` (`class-describe-controller.php:342`). WP async adoption is future work scoped to the E19-1 headless-description proxy, so the shape is frozen for that consumer-to-be | `scene/tests/test_describe_route.py` async cases kept green unmodified where they assert wire shape |
| visual_facts envelope | shared-contracts | `image-description-response.schema.json` (15 core + tier + result_generation) | none | yes | existing contract test `scene/tests/test_describe_run_contract.py` + envelope assertions in new worker tests |
| GPU reaper load file | infra | JSON `{queue_depth,in_flight,written_at}` at `ACX_DESCRIBE_LOAD_PATH` | none on format; producer module changes | yes — `infra/oci/gpu_lifecycle/reaper.py` parses it | new `scene/tests/test_describe_load.py` asserts keys + atomic write |
| DB schema | backend | `image_description_runs` / `image_description_run_items` in `001_identity_schema.py` | additive columns (`run_kind`; item `visual_facts`, `tier`, `result_generation`) | no (greenfield) | schema-parity test: ORM create_all vs migration columns [rg-005] |
| async 503 backpressure threshold | backend | byte budget `_DEFAULT_MAX_RETAINED_IMAGE_BYTES` (256 MiB) + `max_jobs=1000` in `InMemoryDescribeJobStore` | none — identical defaults via `ACX_ASYNC_MAX_RETAINED_IMAGE_BYTES` / `ACX_ASYNC_MAX_PENDING_JOBS` | yes — threshold frozen for the future E19-1 WP async consumer (no WP code calls this route today); service tests are the only current consumer | admission tests assert 503 at byte budget and at job cap with the same defaults |
| empty tenant claim on async routes | backend | 400 unless `ACX_ASYNC_ALLOW_EMPTY_TENANT_CLAIM=1` (`describe.py:434`) | env bypass deleted; always 400 (design (f)) | breaking only for the undocumented admin opt-in; no known consumer | existing 400-rejection tests kept; grep proves env var gone |
| bulk-run endpoints vs single runs | backend | `GET/DELETE /scene/describe/run/{run_id}`, `GET .../items` serve any run_id | 404 for `run_kind='single'` (design (g)) | yes — WBUX UI only ever holds bulk run_ids, so no consumer change | Slice 3 route tests: single-run id → 404 on all three endpoints |

## Proposed Solution

Extend the describe_run schema/repository to host single-image supersede jobs; port the CPU→GPU worker to write through the repository, additionally upserting the FINAL-tier envelope into the `image_descriptions` cache via `ImageDescriptionRepository.insert_or_get_existing` (`scene/application/description_repository.py:48`) in the same session/commit as `set_item_final` (single commit — no dual-write window; see Slice 2); swap the two async routes onto it behind an unchanged wire contract; move the load snapshot to DB-derived counts; extend reclaim and add retention; delete the volatile store, its worker, and their tests.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| schema | `db/migrations/versions/001_identity_schema.py` | Add `run_kind` (String(8), server_default `'bulk'`, CHECK `run_kind IN ('bulk','single')`) to `image_description_runs`; add `visual_facts` (JSONB), `tier` (String(32), nullable), `result_generation` (Integer, server_default 0) to `image_description_run_items` (no `result_fetched_at` — design (a)); partial index `idx_image_description_runs_single_active` on (`status`) WHERE `run_kind='single' AND status IN ('pending','running')` — keyed status-only because its consumers (purge scan, global load-snapshot counts) are tenant-less RLS-bypassed queries, not per-tenant lookups |
| ORM | `db/models/scene.py` | Mirror the three item columns + `run_kind` on `DescribeRun`/`DescribeRunItem` classes (keep CHECK/index parity with migration) |
| domain | `scene/domain/describe_run.py` | Add `RunKind` StrEnum (`BULK`,`SINGLE`) and pure **total** projection `describe_job_status(item) -> DescribeJobStatus` mapping every `DescribeItemStatus` (queued→queued; running w/o result→running; running+provisional visual_facts→provisional; completed+tier final_gpu→final; completed+tier provisional_cpu+last_error→degraded; failed→failed; skipped→failed with `error='cancelled'` per design (g)); move `DescribeJobStatus` StrEnum here from `describe_jobs.py` (sr-007 single canonical enum) |
| application | `scene/application/describe_run_repository.py` | Add `create_single_run(...) -> uuid` (one item, `run_kind=SINGLE`, stores image bytes); `set_item_provisional/set_item_final/set_item_degraded/set_item_failed` (write `visual_facts`/`tier`/`result_generation`, drive item status via existing `mark_item` semantics, clear `image_bytes` on final/terminal); `get_single_run_item(tenant_id, run_id)`; `purge_expired_single_runs(now, retention)` — **cross-tenant delete, gated by `_require_rls_bypass()` (`describe_run_repository.py:179`) exactly like `reclaim_interrupted_runs`**; extend `reclaim_interrupted_runs` per design (e). No `count_active_single_runs` — boot seeding is removed by design (b)'s process-local invariant |
| application | `scene/application/describe_async_worker.py` (new) | `run_async_describe_job(...)` — port of `description_worker.run_describe_job` supersede flow onto the repository: own session per phase commit, `asyncio.wait_for` timeout, CancelledError re-raise after marking failed ([CON-03]), audit sink + metrics calls preserved verbatim, envelope built by `build_visual_facts_envelope`; on GPU success, upsert the FINAL-tier envelope into `image_descriptions` via `ImageDescriptionRepository.insert_or_get_existing` **in the same session/commit as `set_item_final`** (FINAL tier only; provisional/degraded are never cached; crash before the commit loses item-final and cache row atomically — item reclaims to degraded, cache stays absent, consistent) |
| application | `scene/application/describe_load.py` (new, **created in Slice 3** so the snapshot writer exists before `describe_jobs.py` is deleted) | `load_snapshot(session)` (DB counts; **global tenant-less queries — callers open a dedicated short-lived bypass session per design (c) session discipline, verified via the `_require_rls_bypass` pattern**, else RLS silently hides rows and the reaper reads a busy GPU as idle [DIAG-02]) + `write_load_snapshot(payload, path)` (atomic tmp+`os.replace`, `written_at`) — lifted from `describe_jobs.py:113-144` (store methods `load_snapshot` :113-131, `write_load_snapshot` :133-144) |
| routes | `scene/interface_adapters/http/routers/describe.py` | `enqueue_describe_image`: `_ASYNC_ADMISSION.try_acquire(len(image_bytes))` → 503 on refusal; `create_single_run` + commit wrapped in try/except that releases the reservation on any raise; schedule `run_async_describe_job` via BackgroundTasks with `_worker_session_factory` (reuse from `describe_run.py`) inside a try/finally wrapper that always releases (pattern of `_run_describe_job_and_dump_load`, `describe.py:471-475`); delete the `ACX_ASYNC_ALLOW_EMPTY_TENANT_CLAIM` branch (design (f)); opportunistic `purge_expired_single_runs` + snapshot write, each on a dedicated short-lived bypass session (design (c) session discipline — the request session is tenant-scoped); return projected `DescribeJobResult`. `get_describe_job`: repository lookup by run UUID + tenant claim (404 on mismatch, unchanged), load-snapshot write on terminal (dedicated bypass session; no `mark_result_fetched` — design (a)). New module-level `_ASYNC_ADMISSION` (byte budget + job cap, design (b)) replacing `_ASYNC_JOBS`; `_maybe_dump_describe_load` now opens a bypass session and calls `describe_load` |
| routes | `scene/interface_adapters/http/routers/describe_run.py` | `get_describe_run`, `list_describe_run_items`, `cancel_describe_run`: return 404 when the resolved run has `run_kind='single'` (design (g)) |
| deletion | `scene/application/describe_jobs.py`, `scene/application/description_worker.py` | Delete files (delete-over-flag); resolves the `run_describe_job` name collision [NAME-05] |
| startup | `api/main.py` | After `run_startup_reclaim`: call `purge_expired_single_runs` on a dedicated RLS-bypassed session (design (c) session discipline), write initial load snapshot. **No admission-counter seeding** — the counter is process-local and starts at 0 (design (b) invariant), so a failed best-effort reclaim cannot wedge admission |
| tests | `scene/tests/` | Delete `test_describe_jobs.py` AND `test_describe_tier_degrade.py` (the latter imports both to-be-deleted modules — `InMemoryDescribeJobStore`/`DescribeJobStatus` from `describe_jobs` and `run_describe_job` from `description_worker`; its two cases are ported to `test_describe_async_worker.py` in Slice 2 before deletion in Slice 3); add `test_describe_async_repository.py`, `test_describe_async_worker.py`, `test_describe_load.py`; extend `test_describe_run_reclaim.py` (single-run reclaim cases) and `test_describe_route.py` (async route on DB store, 503 admission, terminal-poll persistence across simulated restart) |
| docs | `infra/oci/README.md` | One-line update: snapshot now DB-derived (same file format) |

## Related Files

| File | Note |
| --- | --- |
| `scene/application/visual_facts_service.py` | `build_visual_facts_envelope` reused by the new worker; do not fork it |
| `scene/application/description_repository.py` | `ImageDescriptionRepository.insert_or_get_existing` (line 48) is the cache write path the new worker calls on GPU final (Slice 2) |
| `scene/interface_adapters/http/schemas/responses.py` | `DescribeJobResult` unchanged and untouched — class at `responses.py:139`, its `status` field a plain `str` (`responses.py:143`); **no `DescribeJobStatus` import exists here**, so no import move happens. New work, not current fact: tightening `status` to the relocated enum is a possible follow-up, out of scope |
| `infra/oci/gpu_lifecycle/reaper.py` | Read-only consumer; verify key parity, no code change |
| `scene/tests/test_describe_run_repository.py` | Fixture patterns (SQLite async session) to copy for new repo tests |
| `db/tenant_context.py` | `set_tenant_context` / `enable_rls_bypass` used by worker + reclaim, unchanged |

## Verification Strategy

- Deterministic tests: `cd apps/prototype-description-service && make test` (full), per-slice scoped `uv run pytest <files>` below
- Contract/fixture: existing envelope contract tests stay green; schema-parity check ORM vs `001_identity_schema.py` columns [rg-005]
- Runtime-parity: `uv run pytest scene/tests/test_describe_route.py -k async` exercises the full route→worker→poll loop over SQLite; manual smoke against LocalWP is out of scope (seeded adapter path is deterministic)
- Lint/type: `make -C apps/prototype-description-service check` before close

## Slice Delivery

### Slice 1: Schema, domain projection, repository surface

**Goal**: The describe_run tables can represent a single-image supersede job end-to-end, with retention and reclaim semantics, before any route changes.

TEST_CMD: `cd apps/prototype-description-service && uv run pytest scene/tests/test_describe_async_repository.py scene/tests/test_describe_run_repository.py scene/tests/test_describe_run_reclaim.py`

Changes:

- `001_identity_schema.py` + `db/models/scene.py`: columns/indexes per Files table (kept in the same slice so parity is testable [rg-005]).
- `scene/domain/describe_run.py`: `RunKind`, relocated `DescribeJobStatus`, `describe_job_status(item)` projection — pure and total over every `DescribeItemStatus` including `skipped`→`failed`/`error='cancelled'` (design (g)); exhaustively tested with one case per enum member.
- `scene/application/describe_run_repository.py`: `create_single_run`, `set_item_provisional`, `set_item_final`, `set_item_degraded`, `set_item_failed`, `get_single_run_item`, `purge_expired_single_runs` (RLS-bypass-gated via `_require_rls_bypass`); `reclaim_interrupted_runs` single-run branch (provisional→completed+last_error, else failed). Two-tenant test proves purge deletes expired terminal single runs across tenants under bypass and refuses without it.

Proof (RED→GREEN): new `test_describe_async_repository.py` written first — expect `AttributeError: ... has no attribute 'create_single_run'` on RED; GREEN shows all repo lifecycle + projection + purge + reclaim-preserves-provisional tests passing; existing bulk-run suites unchanged and green.

### Slice 2: DB-backed supersede worker

**Goal**: `run_async_describe_job` reproduces the volatile worker's behavior (provisional→final, degraded-on-GPU-failure, timeout, cancellation, audit, metrics) against the repository.

TEST_CMD: `cd apps/prototype-description-service && uv run pytest scene/tests/test_describe_async_worker.py`

Changes:

- New `scene/application/describe_async_worker.py::run_async_describe_job(tenant_id, run_id, session_factory, cpu_adapter, gpu_adapter, job_timeout_seconds, audit_sink, metrics)`: mark item running → CPU describe (`asyncio.to_thread`) → `set_item_provisional` + commit + audit → GPU describe → `set_item_final` + commit + audit; exception after provisional → `set_item_degraded`; before → `set_item_failed`; `asyncio.wait_for` wrapper with the existing don't-double-write-FAILED guard (port of `description_worker.py:163-174`); CancelledError marks failed then re-raises [CON-03].
- Envelope per tier via `build_visual_facts_envelope` with `result_generation` 1/2 — keeps the 17-field contract byte-compatible with today's `_result_payload` (`description_worker.py:32-53`).
- Cache write-through (PA-scope: the Objective's "GPU results cached" claim): in the GPU-final phase, build an `ImageDescription` row from the FINAL-tier envelope and call `ImageDescriptionRepository.insert_or_get_existing` on the **same session, before the same commit** as `set_item_final` — item-final and cache row land atomically; provisional and degraded tiers are never cached (only FINAL output is authoritative enough to serve future sync `describe` cache hits); a crash pre-commit loses both writes together (item reclaims to degraded, no stale cache) [DATA-14].
- Port the tier-degrade coverage from `scene/tests/test_describe_tier_degrade.py` (which imports both to-be-deleted modules): its two cases — `test_worker_records_cpu_provisional_then_gpu_final` (supersede ordering, tier/`result_generation` 1→2, envelope keys incl. `image_hash`/`provider_disclosure`) and `test_worker_keeps_cpu_provisional_when_gpu_fails` (degraded preserves provisional) — are rewritten against `run_async_describe_job` inside `test_describe_async_worker.py`; the old file is deleted in Slice 3.

Proof (RED→GREEN): tests ported from deleted-in-slice-3 `test_describe_jobs.py` + `test_describe_tier_degrade.py` semantics (supersede ordering, degraded path, timeout marks failed once, cancellation) fail on RED with `ModuleNotFoundError: scene.application.describe_async_worker`; GREEN shows all passing with spec'd fake adapters [TEST-13]; assert persisted `visual_facts` validates against the shared-contracts schema; assert an `image_descriptions` row exists after GPU-final (and does not after degraded/failed).

### Slice 3: Load-snapshot module, route migration + volatile-system deletion

**Goal**: Async routes run on the DB system with an unchanged wire contract; the DB-derived snapshot writer exists **before** the old writer is deleted, so the reaper `ACX_DESCRIBE_LOAD_PATH` contract holds at every intermediate commit; `describe_jobs.py` and `description_worker.py` no longer exist.

TEST_CMD: `cd apps/prototype-description-service && uv run pytest scene/tests/test_describe_load.py scene/tests/test_describe_route.py scene/tests/test_describe_run_routes.py`

Changes:

- **First, before any deletion**: new `scene/application/describe_load.py` (`load_snapshot`, `write_load_snapshot` per Files table) + `scene/tests/test_describe_load.py` — key set exactly `{queue_depth,in_flight,written_at}`, tmp file replaced atomically, counts reflect only `run_kind='single'` non-terminal items; two-tenant test proves `load_snapshot` counts across tenants on an RLS-bypassed session and fails closed on a tenant-scoped one (design (c) session discipline [DIAG-02]). Ordering rationale: the deleted `describe_jobs.py` hosts today's `write_load_snapshot` (`describe_jobs.py:113-143`), so the replacement writer must land in the same slice, ahead of the deletion, or the intermediate state ships without a snapshot producer.
- `describe.py`: replace `_ASYNC_JOBS` with `_ASYNC_ADMISSION` (lock-guarded byte-budget + job-count gate per design (b): `ACX_ASYNC_MAX_RETAINED_IMAGE_BYTES` default 256 MiB, `ACX_ASYNC_MAX_PENDING_JOBS` default 1000; `try_acquire(image_len)` False → 503) [RES-14], [CON-16]; release paired via try/except around `create_single_run`+commit and try/finally around the worker task (design (b) lifecycle) [RES-04]; delete the `ACX_ASYNC_ALLOW_EMPTY_TENANT_CLAIM` branch — empty claim always 400 (design (f)); `enqueue_describe_image` requires a DB session (503 `database session unavailable` when absent, mirroring `describe_run.py:222-223` — the async path can no longer run DB-less); poll handler loads by run UUID, non-UUID `job_id` → 404, tenant-claim mismatch → 404 (unchanged), terminal poll triggers a snapshot write.
- `describe_run.py`: `get_describe_run` / `list_describe_run_items` / `cancel_describe_run` return 404 for `run_kind='single'` runs (design (g)).
- `_maybe_dump_describe_load` rewired to `describe_load.write_load_snapshot(load_snapshot(session), path)` — every call site (enqueue, worker-terminal, terminal poll) and the opportunistic per-enqueue `purge_expired_single_runs` opens a dedicated short-lived `enable_rls_bypass` session, never the tenant-scoped request/worker session (design (c) session discipline).
- Delete `scene/application/describe_jobs.py`, `scene/application/description_worker.py`, `scene/tests/test_describe_jobs.py`, `scene/tests/test_describe_tier_degrade.py` (coverage already ported in Slice 2); fix imports in `describe.py` (`responses.py` needs no change — see Related Files).
- Update async route tests to the DB fixture pattern; keep every wire-shape assertion (`DescribeJobResult` fields, 400 tenant-claim-required, 503 backpressure) textually intact so the contract is proven unchanged. New leak-safety tests: worker crashes before terminal → reservation released; enqueue commit failure → reservation released and 500 surfaced. New disjointness tests: single-run id → 404 on all three bulk endpoints.

Proof (RED→GREEN): `test_describe_load.py` RED on `ModuleNotFoundError: scene.application.describe_load`, GREEN once the module lands; route tests fail on RED while routes still target the deleted store (ImportError), GREEN after migration; `grep -rn "InMemoryDescribeJobStore\|description_worker\|ACX_ASYNC_ALLOW_EMPTY_TENANT_CLAIM" apps/prototype-description-service --include='*.py'` returns nothing; 503 admission tests pass at both the byte budget and the job cap (refusal → 503, release → subsequent 200).

### Slice 4: Startup wiring, retention, full-suite close

**Goal**: Retention purge and the initial DB-derived load snapshot run at boot after reclaim; whole service green.

TEST_CMD: `cd apps/prototype-description-service && uv run pytest scene/tests/test_describe_load.py scene/tests/test_describe_run_reclaim.py && make test`

Changes:

- `api/main.py` lifespan: after `run_startup_reclaim` → `purge_expired_single_runs` (dedicated RLS-bypassed session, design (c) session discipline) → initial snapshot write; all best-effort/never block boot (matches existing reclaim block style). No admission seeding — the counter is process-local, starts at 0, and reservations exist only while an in-process task holds them (design (b) invariant), so reclaim failure cannot wedge admission.
- `infra/oci/README.md` one-line producer note.
- Run `make -C apps/prototype-description-service check` (format-all first per repo rule) and record `test_result` evidence in handoff.

Proof: full `make test` passing line captured verbatim [AGT-04]; reclaim test proves a RUNNING single item with provisional facts polls as `degraded` after simulated restart (new session, reclaim, poll projection); startup-order test (or lifespan unit) shows reclaim → purge → snapshot each logged best-effort.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried live from the handoff DB.

## Context and Ownership

- [ ] Loaded `testing-python.md`, the shared-contracts response schema, reaper docstring contract, and handoff state for `VLM-5` before editing.
- [ ] Recorded boundary ownership: wire contracts (poll shape, envelope, load JSON) frozen; DB schema additive-greenfield.

### Checklist for Slice 1: Schema, domain projection, repository surface

- [ ] Add `run_kind` + item result columns + `idx_image_description_runs_single_active` in `001_identity_schema.py` (in `_ensure_table`/`_ensure_index` style used at lines ~1299–1395).
- [ ] Mirror columns on `DescribeRun`/`DescribeRunItem` in `db/models/scene.py` with matching CHECK constraints.
- [ ] Move `DescribeJobStatus` into `scene/domain/describe_run.py`; add `RunKind`; implement `describe_job_status(item)` total over every `DescribeItemStatus` (incl. `skipped`→`failed`/`error='cancelled'`), one test case per member.
- [ ] Implement the new/extended `DescribeRunRepository` methods named in Files table (no `mark_result_fetched` — design (a) dropped it with the eviction consumer); `purge_expired_single_runs` gated by `_require_rls_bypass` with a two-tenant test proving deletions span tenants under bypass and fail closed on a tenant-scoped session (design (c) session discipline); extend `reclaim_interrupted_runs` for single runs (provisional-preserving degraded path).
- [ ] Write `scene/tests/test_describe_async_repository.py` first (RED observed), then implement to GREEN; capture both outputs.
- [ ] Schema-parity assertion (ORM metadata vs migration columns) included in the new test file.

### Checklist for Slice 2: DB-backed supersede worker

- [ ] Create `scene/application/describe_async_worker.py::run_async_describe_job` with the signature in Files table; reuse `build_visual_facts_envelope`; port timeout + cancellation + degraded semantics from `description_worker.py` exactly.
- [ ] Per-phase commit so a crash between CPU and GPU leaves a durable provisional row.
- [ ] Cache write-through: `ImageDescriptionRepository.insert_or_get_existing` called with the FINAL-tier envelope on the same session/commit as `set_item_final`; test asserts the `image_descriptions` row exists after GPU-final and is absent after degraded/failed.
- [ ] Write `scene/tests/test_describe_async_worker.py` (supersede order, degraded, failed, timeout-single-write, cancellation re-raise, audit/metrics call assertions with `spec=` mocks); include the two cases ported from `test_describe_tier_degrade.py` (provisional→final envelope assertions; degraded preserves provisional); RED then GREEN captured.
- [ ] Persisted `visual_facts` validated against `image-description-response.schema.json` in-test.

### Checklist for Slice 3: Load-snapshot module, route migration + deletion

- [ ] Create `scene/application/describe_load.py` (`load_snapshot`, `write_load_snapshot`) preserving atomic write + `written_at`, BEFORE deleting `describe_jobs.py` (its `write_load_snapshot` is today's reaper-snapshot producer — the `ACX_DESCRIBE_LOAD_PATH` contract must never lack a writer).
- [ ] Two-tenant `load_snapshot` test: global counts under a dedicated bypass session; tenant-scoped session fails closed (design (c) session discipline).
- [ ] Implement `_ASYNC_ADMISSION` gate (lock-guarded byte budget + job cap, defaults 256 MiB / 1000 matching `describe_jobs.py:50,59`) in `describe.py`; 503 on `try_acquire(image_len)` refusal; release in try/except around enqueue create/commit AND try/finally around the worker task (incl. CancelledError path).
- [ ] Leak-safety tests: worker crash before terminal releases the reservation; enqueue commit failure releases the reservation.
- [ ] Delete the `ACX_ASYNC_ALLOW_EMPTY_TENANT_CLAIM` branch; empty-claim 400 tests kept as proof; grep-verify env var gone.
- [ ] Rewrite `enqueue_describe_image` onto `create_single_run` + BackgroundTasks `run_async_describe_job` with `_worker_session_factory` (import from `describe_run.py` or hoist to a shared module — hoisting preferred to avoid router-to-router import [REF-19]).
- [ ] Rewrite `get_describe_job` as repository lookup + `describe_job_status` projection + terminal snapshot write via a dedicated bypass session (design (c)); non-UUID job_id → 404.
- [ ] Per-enqueue opportunistic purge + every snapshot trigger open dedicated short-lived `enable_rls_bypass` sessions — never the tenant-scoped request/worker session.
- [ ] Bulk endpoints (`describe_run.py` get/items/cancel) 404 on `run_kind='single'`; route tests added.
- [ ] Delete `describe_jobs.py`, `description_worker.py`, `test_describe_jobs.py`, `test_describe_tier_degrade.py`; grep-verify zero remaining references.
- [ ] Async route tests migrated to DB fixtures with wire-shape assertions unchanged; RED/GREEN captured; existing `test_describe_run_routes.py` bulk cases stay green.

### Checklist for Slice 4: Startup wiring, retention, full-suite close

- [ ] Wire `api/main.py` lifespan: reclaim → purge → initial snapshot, purge/snapshot on a dedicated RLS-bypassed session (design (c)), each best-effort with logged failure ([AGT-10]); no admission seeding (design (b) invariant).
- [ ] Extend `test_describe_run_reclaim.py` with the interrupted-provisional→degraded poll case and the purge-retention case.
- [ ] Update `infra/oci/README.md` producer sentence; confirm reaper key contract by test.
- [ ] `make format-all` variant, then `make -C apps/prototype-description-service check` green; full-suite output line recorded in handoff `test_result`.

## Review Readiness

- [ ] All three frozen boundaries (poll shape, envelope schema, load JSON) have explicit test evidence in the diff.
- [ ] Runtime-parity: route-level async test covers enqueue→worker→poll on the real FastAPI app fixture, not just repository units [TEST-10 kept supplementary].
- [ ] Handoff decision recorded per slice (`record_event`) with 40-char SHAs; dashboard re-rendered; no finding bodies pasted into this plan.
- [ ] Deleted-file check: no import of `scene.application.describe_jobs` or `scene.application.description_worker` anywhere, including tests and docs snippets.

## Stretch Goals

- [ ] Include bulk-run items in the reaper load snapshot (widens GPU-busy signal; needs reaper-side review).
- [ ] Client idempotency key on `POST /scene/describe/async` to enable safe resubmit-after-restart ([DATA-13]); requires WP plugin coordination — out of scope here.

## Success Criteria

- [ ] `scene/application/describe_jobs.py` and `scene/application/description_worker.py` no longer exist; exactly one job system remains.
- [ ] A terminal async result polled within the retention window always returns 200 with the persisted envelope — including after a process restart (test-proven).
- [ ] An async job interrupted mid-GPU reclaims to `degraded` with its provisional result intact (test-proven).
- [ ] Burst beyond the retained-byte budget or job cap returns 503 at today's thresholds (test-proven); a crashed worker or failed enqueue releases its reservation — no permanent-503 wedge (test-proven).
- [ ] A GPU-final async result is present in the `image_descriptions` cache in the same commit as the item result (test-proven).
- [ ] `/run/acx/describe-load.json` format unchanged, DB-derived, atomically written (test-proven).
- [ ] `make -C apps/prototype-description-service check` fully green; `handoff_close_check(enforce=True)` passes at merge time.
