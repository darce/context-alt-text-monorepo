# Durability Gap Fixes — Plan (v0.1)

> **Status:** Planning seed (pre-task-plan). Authored 2026-07-10 under `DURABILITY-UV-PLANNING`.
> **Source:** Gap inventory in [roadmap-pg-durable-evaluation.md](../../roadmaps/roadmap-pg-durable-evaluation.md) (decision: harden the hand-rolled job layer in place instead of vendoring pg_durable).
> **Heuristics basis:** [docs/strategy/engineering-heuristics.md](../../strategy/engineering-heuristics.md) — IDs cited per slice.

## Objective

Close the seven confirmed durability gaps (G1–G7) in the description-service job system with bounded slices, no framework adoption, no schema migrations beyond greenfield edits to `001_identity_schema.py`.

## Constraints

- Greenfield policy: schema changes go directly in `001_identity_schema.py`; no data migrations.
- Keep the proven assets untouched in behavior: SKIP LOCKED claim CTE, terminal-guarded finalizers, transient/deterministic retry classification.
- Every slice independently mergeable; each needs fresh `test_result` evidence per the pre-merge gate.
- SQLite test sessions must keep passing (`is_sqlite()` guards where SQL is PG-specific).

## Slices (blast-radius order)

### Slice 1 — G4: Reaper for crashed `running` clustering jobs

A clustering job whose worker dies mid-run stays `running` forever; recovery paths only touch `pending` rows. This is the highest-blast-radius gap: a wedged pipeline with no signal — [OBS-08] (silence is not success) and [RES-07] (anything that accumulates needs a same-rate reclaimer).

- Add `reclaim_stale_clustering_jobs()` to the queue repository mirroring `reclaim_stale_items` (`scan_queue_repository.py:233`): `running AND last_progress_at < now() - stale_after` → retry-or-fail through the existing `_record_clustering_job_failure` classification (`scan_worker.py:330`).
- Staleness source: progress checkpoints already committed per chunk (`handlers/clustering.py:94`) — add a `last_progress_at` column updated on each checkpoint commit rather than inferring from payload JSONB.
- Wire into the worker poll cycle next to `terminate_stalled_jobs` (`scan_worker.py:165`).
- Guard: reclaim must use the same terminal-guarded UPDATE predicate style so a concurrently-finishing job is not overwritten ([CON-11] check-then-act — the status check and the reclaim write must be one atomic UPDATE, not SELECT-then-UPDATE).
- Test: characterization first ([TEST-03]) — pin current behavior (crashed running job is never picked up), then the fix test: insert a `running` row with stale `last_progress_at`, run one poll cycle, assert retry-or-fail. Predict the failure message before first run ([TEST-06]). No sleeps — inject clock/staleness threshold ([TEST-08], the `test_key_rotation` flake is the cautionary precedent).

### Slice 2 — G3: Lease fencing for scan items

Stale-claim reclaim infers death from `started_at` age alone; a slow-but-alive worker past 600s gets double-claimed and both workers commit. [RES-10] is the governing rule: a paused holder must not be able to write with stale state — storage must reject old tokens.

- Add `lease_token UUID` + `lease_expires_at` to `identity_scan_job_items` (greenfield edit in `001_identity_schema.py`).
- Claim CTE sets a fresh token and `lease_expires_at = now() + lease_seconds`. **No mid-item renewal**: instead, `ScanItemHandler.process_items` wraps each `process_media_item` call in `asyncio.timeout(lease_seconds - margin)` so an item cannot outlive its lease ([RES-02] bounded wait beats a heartbeat sidecar, which would itself be an orphan-task risk [CON-04]). `lease_seconds` sized to worst-case item duration (config, default 600s = current staleness window).
- `mark_item_completed` / `_handle_item_failure` UPDATEs add `AND lease_token = :token` — a reclaimed item's original holder gets rowcount 0 and drops its result ([CON-05] lost update prevented by CAS-style predicate; [DATA-13] the token is the end-to-end request ID reaching the final store).
- Reclaim predicate switches from `started_at` age to `lease_expires_at < now()`.
- External side effects (image fetch, embedding inference) remain at-least-once — acceptable: DB writes are fenced, duplicated compute is bounded waste, consistent with [RES-01] (the retried op is now idempotent at the store).
- Test: two-claimant race — claim, expire lease, reclaim by second worker, first worker's completion UPDATE must affect 0 rows. Deterministic via injected expiry, no wall-clock waits ([TEST-08], [CON-17]).

### Slice 3 — G1: Retry backoff with jitter

Failed items are immediately reclaimable; a struggling dependency (VLM endpoint, ObjectStore) gets hammered at poll frequency — [RES-06] (retry needs backoff + ceiling; never amplify a partial outage).

- Add `next_attempt_at` to scan items; `_handle_item_failure` (`handlers/scan.py:180`) sets `now() + base * 2^attempts + jitter`, capped.
- Claim CTE adds `AND (next_attempt_at IS NULL OR next_attempt_at <= now())`.
- Same treatment for clustering-family retries: add `next_attempt_at` to `identity_clustering_jobs` too; `_record_clustering_job_failure` (`scan_worker.py:330`) sets it on transient-requeue, and the `_claim_next_clustering_job` SELECT (`scan_worker.py:286`) adds `AND (next_attempt_at IS NULL OR next_attempt_at <= :now)` to its pending-row predicate.
- Config on `ScanWorkerConfig` next to `max_attempts` (`scan_worker.py:62`); policy values externalized, not hardcoded ([OBS-05] externalize policy).
- Test: failure sets `next_attempt_at` in the future; claim skips it; time-travel (injected now) makes it claimable. Jitter bounds asserted, not exact values ([TEST-08]).

### Slice 4 — G5: Export + describe jobs onto the durable worker queue

`BackgroundTasks` dies with the server ([CON-04] fire-and-forget orphan; [DATA-10] async-ack durability — job loss on restart is currently silent), and the in-memory describe store blocks multi-worker deployment by design.

- Route export runs and describe runs as new job types through the existing clustering-family dispatch in `scan_worker.py:286` — the dispatch map already generalizes; this is reuse, not new machinery ([REF-23] stay strategic; [ARCH-08] the boring option — one more job type — beats a second queue system).
- **Job-type CHECK**: `valid_job_type` currently allows only `('clustering','curation','split')` (`db/models/jobs.py:139`) — new job types require extending it; done via the Slice 5 derive-from-enum treatment (a `JobType` enum becomes the single source for the CHECK) so this slice depends on Slice 5 landing first ([rg-005]).
- **Ownership boundary** ([ARCH-02] single writer): the queue tables stay recognition-owned; recognition's worker owns all status transitions. Scene contributes only an execution *handler* registered into the dispatch map (same pattern as clustering handlers) — scene code never writes job rows directly. The existing DB-backed `DescribeItemStatus` run machinery (`scene/application/describe_run_worker.py`) is the surviving describe execution path; the in-memory `describe_jobs.py` store is the deletion target, not a third machine.
- HTTP handlers change from `BackgroundTasks.add_task(...)` to enqueue-and-return-job-id; polling endpoints already exist for scan jobs and the export/describe status endpoints keep their shapes ([DATA-03] API compat: response schema unchanged, only execution moves).
- Delete the process-local `describe_jobs.py` in-memory store once DB-backed rows carry the same states (delete-over-flag per greenfield policy). The GPU idle-reaper's JSON load-snapshot input must be preserved or re-sourced from the DB rows — verify before deleting ([AGT-02] resolve the consumer before removing its producer).
- Largest slice; sequence after 1–3 (new job types inherit reaper + lease + backoff for free) **and after Slice 5** (needs the `JobType`-derived CHECK).
- Test: enqueue export → worker processes → status endpoint reflects terminal state; kill-worker-mid-run case covered by the Slice 1 reaper test pattern.

### Slice 5 — G7: Clustering status CHECK/enum parity

DB CHECK allows 4 clustering statuses while `JobStatus` has 6 (`rejected`, `completed_with_errors` missing) — a latent insert failure the moment application code uses the full enum. [rg-005] (schema/contract parity — validate against real schema before merge); [sr-007] (single canonical status definition).

- Regenerate the CHECK in `001_identity_schema.py` from the `JobStatus` enum values — derive, don't duplicate, so the two cannot drift again ([REF-19] one module owns the decision).
- Apply the same derivation to `valid_job_type` (`db/models/jobs.py:139`): introduce a `JobType` StrEnum ([sr-007]) and generate the CHECK from it — prerequisite for Slice 4's new job types.
- Test: insert a clustering job in every `JobStatus` and `JobType` value against real PG (not SQLite, where the CHECK differs) — this is the [rg-005] verification.

### Slice 6 — G2 + G6: Retry-state observability

Terminal failure is invisible except by ad-hoc SQL, and clustering retry counts live in JSONB payload. [OBS-05] (expose state, counts, high-water marks) without building new infrastructure.

- Promote clustering `payload["retry_count"]` to a real `attempts` column (parity with scan items).
- Add a `failed`-rows operator view (SQL view, not a table — dead-letter *query surface*; the rows already exist).
- **Terminal-row purge** ([RES-07]): no time-based job-row retention exists today (the retention router is tenant-purge/export only) — job tables grow without bound. Add a bounded purge of terminal job + item rows older than `job_retention_days` (config, default 30) to the worker poll cycle next to the Slice 1 reaper, shipped in the same slice as the view that makes the backlog visible.
- Surface failed/stalled counts in the existing capability-heartbeat row so the API layer can expose them ([OBS-01] instrument at write time).
- Test: view returns terminal-failure rows with `last_error`; attempts column increments across the Slice 3 backoff path.

## Explicitly out of scope

- No workflow engine, no Celery/arq, no pg_cron — rejected in the pg_durable evaluation ([ARCH-08]).
- No exactly-once guarantee for external side effects (HTTP fetch, inference) — fencing bounds the damage; full idempotency keys for external calls are deferred until a consumer requires them ([REF-12] YAGNI: no second concrete consumer today).
- No changes to the scene-describe VLM adapters' retry behavior (currently zero-or-once; adding retries there without idempotency would violate [RES-01]).

## Verification strategy

Per slice: scoped pytest module (never full suite in-loop), against PG for schema-dependent slices (Slice 5 requires real PG). Known-red baseline: `test_key_rotation` full-suite flake is pre-existing — record it in the test_result baseline so it is not re-diagnosed. Integration determinism: all staleness/expiry/backoff tests use injected clocks, zero `sleep()` ([TEST-08]).

## Sizing

| Slice | Est. LOC (src+test) | Risk |
|---|---|---|
| 1 (G4 reaper) | ~60 + 80 | Low — mirrors existing reclaim pattern |
| 2 (G3 lease) | ~80 + 120 | Medium — touches claim CTE (proven asset) |
| 3 (G1 backoff) | ~50 + 80 | Low |
| 4 (G5 queue move) | ~150 + 150 | Medium — deletes in-memory store; GPU-reaper input dependency |
| 5 (G7 parity) | ~10 + 40 | Low |
| 6 (G2/G6 observability) | ~50 + 60 | Low |

Total ≈ 400 src + 530 test LOC across six independently-mergeable slices; consistent with the 200–400 src estimate in the evaluation doc.
