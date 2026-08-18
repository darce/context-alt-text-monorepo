# Scan Pipeline Trust & Data-Plane Canonicalization

> **Status**: Scope stub for review (no implementation yet)
> **Owning epic**: [E16. Public Demo Follow-Ons (v0.4.1)](../../epics/v0.4.1/public-demo-followons-epic.md) — proposed new **Theme E**
> **Drafted on**: `feature/e16-1`
> **Drafted**: 2026-05-03

## Problem

A live demo run on 2026-05-03 surfaced a class of correctness, observability, and UX defects across the scan pipeline. The user submitted two scans of 100 media items each. Neither completed correctly:

- **Job 1** (`676c07ef-3b27-49f7-b9b2-de3ee77596c5`) stalled at `Processed 95/100 · Phase: Queued · Queued 5 items…`. Spinner never resolved.
- **Job 2** (`ed877f4f-fb06-455d-93fe-a25a8dedf77e`) showed `Processed 11/11 · Phase: Complete · ✓ Scan complete 11 images` — silently dropping 89 of the 100 submitted items.
- "Review Suggestions" panel showed `No suggestions to review yet` after the "successful" run.
- A merge action against cluster `a60a64dc-132b-4e61-8810-fdd25d47b523` (label "Saffron Cypress") returned a raw 400: `{"code":"invalid_target_cluster_id","message":"Source and target cluster IDs must differ."}` — the UI offered to merge a cluster with itself.

These are downstream symptoms of one upstream cause (Section "Root Cause") plus a set of independent UX/observability gaps that compound the user's inability to recover. Quoting the operator: *"poor UI, observability, usability."*

## Evidence

All evidence below was captured live on `main @ c65ec6cf` against the running local stack.

### E1. Backend identity DB has no scan-job records for either submitted job

```sql
-- context_alt_text_service (legacy, the DB the running service is wired to via local .env)
SELECT count(*) FROM identity_scan_jobs;     -- 0
SELECT count(*) FROM identity_scan_job_items;-- 0
SELECT count(*) FROM identity_clusters;      -- 0
SELECT count(*) FROM identity_members;       -- 0
SELECT count(*) FROM identity_suggestions;   -- 0
SELECT count(*) FROM tenants;                -- 1

-- alt_context_service (canonical name per code default; never written to)
SELECT count(*) FROM identity_scan_jobs;     -- 0
SELECT count(*) FROM tenants;                -- 0
```

Both job UUIDs from the UI are absent. The recognition log corroborates: every minute since 22:29 UTC it emits `Refreshed mv_identity_cluster_centroids: before=0 after=0`. The backend has nothing to refresh because nothing reached it.

### E2. WordPress mirror holds 116 stale clusters / 214 stale members / 84 failed outbox events pointing at a backend that no longer has them

```
clusters          | 116
identity_members  | 214
sync_outbox       |  97  (84 failed, 10 acknowledged, 3 pending)
sync_conflicts    |   0
```

Members for the IDs the operator flagged as suspect:

| attachment_id | cluster_uuid | similarity | created_at | updated_at |
|---|---|---|---|---|
| 6622 | 23932c26… | 1 | 2026-05-03 21:26:59 | 21:35:34 |
| 6623 | c14c6c20… | 0.86 | 21:26:59 | 21:35:34 |
| 6624 | bf05ce91… | **1** | 21:26:59 | 21:35:34 |
| 6624 | fdcc7327… | **1** | 21:26:59 | 21:35:34 |
| 6624 | ab27da72… | **1** | 21:26:59 | 21:35:34 |
| 6624 | 68ee6bbe… | **1** | 21:26:59 | 21:35:34 |
| 6624 | c14c6c20… | 0.73 | 21:26:59 | 21:35:34 |
| 6624 | d80bb6a0… | **1** | 21:26:59 | 21:35:34 |
| 6625 | c14c6c20… | 0.93 | 21:26:59 | 21:35:34 |
| 6626 | c14c6c20… | 0.92 | 21:26:59 | 21:35:34 |
| 6626 | 7269b586… | 1 | 21:26:59 | 21:35:34 |

These cluster_uuids do not exist in either backend DB. Media 6624 alone has six simultaneous similarity=1.0 cluster assignments — almost certainly duplicate-sync, not real clustering.

### E3. Local `.env` points at the legacy DB; the rename was started but never finished

`apps/prototype-description-service/.env:25`
```
DB_NAME=context_alt_text_service
```

vs. canonical defaults already in code:

| Surface | Value | Path |
|---|---|---|
| `DEFAULT_DB_NAME` | `alt_context_service` | `apps/prototype-description-service/db/settings.py:15` |
| `db_shell.sh` default | `alt_context_service` | `apps/prototype-description-service/scripts/db_shell.sh:37` |
| `.env.example` / `.env.prod.example` | `alt_context_service` | per `docs/tasks/tech-debt/rename-database-context-alt-text-to-alt-context.md` checkbox 1 |

The rename tech-debt doc tracks 3 unchecked closure items (local `.env` drift, VM env files, pgdata wipe). The local `.env` drift is the smoking gun: every `make reset-local` resets `alt_context_service` while the running service writes to `context_alt_text_service`. The user's "DBs reset but state surprising" symptom is fully explained by this single line.

### E4. WP-side dashboard query uses a renamed column

`apps/prototype-wp-alt-context/src/api/class-api.php:994`
```php
$wpdb->prepare( 'SELECT COUNT(DISTINCT media_id) FROM %i', $table_members )
```

The actual column is `attachment_id` (`apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php:499`, mysql `DESCRIBE` confirmed). WordPress debug.log shows the query failing on every dashboard load:

```
[02-May-2026 19:42:49 UTC] WordPress database error Unknown column 'media_id' in 'field list'
for query SELECT COUNT(DISTINCT media_id) FROM `wp_acx_identity_members`
made by ... AltContext\Api\Api->get_dashboard_stats
```

### E5. Multipart submission silently swallows failed batches

`apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:245` caps each multipart POST at 5 items / ~25 MiB. If a batch fails post-blob-store / pre-DB-commit, no marker is recorded against the job, and the frontend SSE stream simply trusts whichever `total` arrives last. WP debug.log shows ~20 `[acx] acx_recognition_transport=multipart` lines for the 21:25–21:27 window (= 100/5), so all batches *attempted* a network call, but only the row(s) the backend persisted appear in `progress.total`.

### E6. Frontend has no SSE-stall detection

`apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStreamHelpers.ts` and `jobStateMachineUtils.ts` have no heartbeat timeout. SSE silence with phase ≠ `Complete | Failed` displays the spinner indefinitely. Backend emits 15 s heartbeats (`class-analysis-jobs-controller.php:490`); frontend ignores absence.

### E7. "No suggestions to review yet" is the same string for empty / error / unwired states

`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx` returns the literal "No suggestions to review yet" without distinguishing zero-results, endpoint failure, or unconfigured backend. Zero diagnostic signal.

### E8. Self-merge offered when label search returns the source cluster

`IdentityClusterItem.tsx:184–215` runs `findClusterByLabel(trimmed)` while editing. The guard at line 193 only skips when `trimmed === currentLabel`. Once `useClusterSaveAction.ts:104` re-runs `findClusterByLabel` on save, the lookup returns the source cluster itself (it does not exclude `editableClusterId` from results); the UI sets `matchedCluster.id = sourceId`, renders "Merge with Saffron Cypress", and posts `target_cluster_id == source_id`. Backend rejects at `class-cluster-mutations-controller.php:473` with a 400 the user sees as a raw JSON dump.

```sql
-- mysql confirms only one cluster has this label
SELECT cluster_uuid, label FROM wp_acx_clusters WHERE label LIKE '%thistle%';
-- a60a64dc-132b-4e61-8810-fdd25d47b523 | Saffron Cypress
```

There ARE genuine duplicate-labeled clusters (`Slate Willow` ×3, `Burnished Ridgeway` ×2, `Pewter Hollow` ×2) where the same code path will work correctly; the bug is purely the self-match case.

## Root Cause

**One upstream cause + a set of layered failures that prevent the operator from noticing or recovering from it.**

The upstream cause is E3: the local `.env` `DB_NAME` was never updated when the rest of the codebase moved to `alt_context_service`. The running recognition service writes to the legacy DB; the `make reset-local` workflow resets the canonical DB. Every sync from WP loops through a backend whose state diverges from what the operator believes is "fresh", which is why an apparent post-reset run produces 116 ghost clusters and 84 failed outbox events.

The downstream UX/observability defects (E5–E8) then prevent recognition of the failure: stalls present as spinners, partial submissions present as "✓ Complete", and merge errors present as raw JSON. The result is an operator looking at a green checkmark over an empty backend.

## Proposed Scope: New E16 Theme E

Add to `docs/epics/v0.4.1/public-demo-followons-epic.md` after Theme D:

```markdown
### Theme E — Scan Pipeline Trust & Data-Plane Canonicalization

| Task | Status | Owning Doc | Why It's Here |
| ---- | ------ | ---------- | ------------- |
| **E16-1a** Complete DB rename (close rename tech-debt, fix local `.env`, wipe legacy DB, sync VMs) | Stub on `main` | rename-database-context-alt-text-to-alt-context.md | Closes 3 unchecked items in the existing rename tech-debt doc. Pre-req for everything else in Theme E because reset semantics break otherwise. |
| **E16-1b** Batch-run aggregate state + multipart submit failure surfacing | Stub (this doc) | (to be promoted) | Plugin must own a `BatchRun` aggregate keyed off the user submit, gate phase/clustering on *all* child jobs reaching terminal states, and promote new fields through a dedicated `wp-batch-run` shared-contracts schema + REST + SSE. No more "11/100 reported as 11/11 ✓" because the latest child happened to finish first. |
| **E16-1c** Frontend stall detection + recovery affordance | Stub (this doc) | (to be promoted) | SSE stall > 30 s ⇒ "Stuck — last update Xs ago" badge with Retry/Cancel. |
| **E16-1d** Suggestion-panel empty-state taxonomy | Stub (this doc) | (to be promoted) | Distinguish 0-results / endpoint-error / unconfigured / empty-backend. |
| **E16-1e** Self-merge guard + friendly merge-error surface | Stub (this doc) | (to be promoted) | Exclude source cluster from `findClusterByLabel`; surface 400s inline. |
| **E16-1f** WP dashboard `media_id`→`attachment_id` SQL fix + audit | Stub (this doc) | (to be promoted) | One-line fix; audit other queries in `class-api.php` for the same drift. |
| **E16-1g** WP-mirror reconciliation when backend is empty | Stub (this doc) | (to be promoted) | Detect mirror/backend divergence; offer (or auto-perform) a mirror reset; do not let stale clusters accumulate forever. |
| **E16-1h** Cluster-membership integrity check (separate, lower priority) | Stub (this doc) | (to be promoted) | Investigate media 6624's 6× similarity=1.0 assignments. Likely duplicate-sync ingestion bug. May fold into td-retry-attempt-observability. |

**Theme E ordering:** E16-1a is split into two parts: (1) the shipped guardrail slice that prevents stale local `DB_NAME=context_alt_text_service` values from silently rebinding reset/start flows, and (2) the still-open local operator foundation (`.env` rewrite, canonical reset, legacy DB drop, runtime verification). The operator foundation remains the prerequisite for end-to-end local scan/reset verification and for backend-dependent tasks such as E16-1b and E16-1g. Isolated UI/plugin slices such as E16-1d/e/f may continue on mocked or contract-backed paths while that operator work stays open. E16-1h remains exploratory and lowest priority.
```

## Member-Task Sketches

Each member task below should be promoted to a full plan in `docs/tasks/15.0/` only when picked up. Stubs stay here.

### E16-1a — Complete DB rename (foundation)

- **Source of truth:** `docs/tasks/tech-debt/rename-database-context-alt-text-to-alt-context.md`
- **Action:** Close the local-environment items in that doc's Consolidated Triage Checklist (local `.env`, local pgdata). VM env-file drift moves to a separate operator-only sub-task that does **not** block the rest of Theme E.
- **Guardrail note:** The `copilot_slice_complete_e16_1_local_db_name_guardrails` slice is a preflight guardrail only. It prevents stale local `DB_NAME=context_alt_text_service` values from silently re-binding local reset/start flows, but it does **not** satisfy E16-1a on its own. E16-1a stays open until the local `.env`, reset, legacy-DB drop, and runtime verification steps below are completed.
- **Implementation split:** Treat E16-1a as `guardrail shipped` plus `operator foundation pending`. Commits `78d2b0e5` and `a3dd4e90` cover only the shipped guardrail portion. The checklist below tracks the remaining local operator work; downstream docs should not imply those steps were already executed on this branch.
- **Concrete step set (local only — VM deferred per operator instruction "work locally, once process is fixed push to remote vm"):**
  1. `feature/e16-1a` branch.
  2. Land and keep the local guardrail coverage in place until the local environment is rewritten (`db.settings` + local reset/start flows canonicalize the stale legacy DB name and surface a warning instead of silently trusting it).
  3. Update the active local `apps/prototype-description-service/.env` so `DB_NAME=alt_context_service` is the persisted value going forward.
  4. `make reset-local WP_PATH="$LOCAL_WP_ROOT/app/public" CONFIRM_LOCAL_RESET="RESET"` — wipes both WP and `alt_context_service`.
  5. `psql -h 127.0.0.1 -U context -d postgres -c 'DROP DATABASE IF EXISTS context_alt_text_service;'` — kills the legacy DB so no future env drift can re-bind to it locally.
  6. Restart the description service; confirm via `pg_stat_activity` that the only DB it touches is `alt_context_service`.
  7. Tick the local items in the rename doc's Consolidated Triage Checklist. Leave the VM checkbox open and re-target it from a follow-up operator runbook (E16-1a-vm) once the local process is proven.
- **VM follow-up (E16-1a-vm, deferred):** updates `/opt/acx-backend/<env>/secrets/.env` for prod/staging/dev, restarts the env compose stack, drops the legacy DB on each VM. Runs only after the local pipeline is observed clean end-to-end. No code in this monorepo depends on the VM step landing first.
- **Risk:** Low — greenfield policy applies; no prod data to preserve.
- **Done when (local):** No local process is connected to `context_alt_text_service`; the legacy DB is dropped locally; the rename doc's local checklist items are ticked. **Done when (VM follow-up):** same conditions verified on each VM; rename tech-debt doc archived.

### E16-1b — Batch-run aggregate state + multipart submit failure surfacing

> Originally scoped as per-batch failure surfacing only. Expanded after planning review (E16-1-PLAN-01, E16-1-PLAN-02): the existing frontend treats one user "scan" as a fan-out of N independent backend jobs (one per 5-image batch), but the state machine only consumes the latest child job — so a single completed tail batch can mask earlier stalls/failures, and `Processed 11/11 ✓` over 100 submitted items is the natural outcome. Aggregation must live above the per-job SSE stream, and any new fields must be promoted through the owning contract surfaces, not added ad hoc.

**Literature anchors for the promoted implementation plan:**

- Michael T. Nygard, *Release It!* (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt`): "your system will have a variety of failure modes." Treat stalled child jobs, rejected batches, and stale clusters as designed failure modes with explicit UI/status outcomes.
- Martin Kleppmann, *Designing Data-Intensive Applications* (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt`): "makes the provenance of data much clearer." `BatchRun` exists to preserve user-submit provenance, child-job lineage, and deterministic reconciliation.
- Martin Fowler and Kent Beck, *Refactoring* (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt`): "The key here is being able to catch an error quickly." The slice must land with focused aggregate/state-machine tests, not only manual UI inspection.
- Pekka Enberg, *Latency* (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt`): "latency increases as concurrency increases." The aggregate must expose queue/child progress clearly instead of hiding fan-out pressure behind the latest child job.
- David Farley, *Modern Software Engineering* (`literature/extracted/refactoring/modern-software-engineering.txt`): "use accurate measurement rather than waiting for something bad to happen." Add observable counters, timestamps, and terminal-state checks so the UI detects drift before an operator sees a false green check.

**Current behaviour the fix must replace:**

- Submit splits into 5-image multipart POSTs (`class-analysis-jobs-controller.php:245`); each accepted POST yields one `scan_jobs` row + one SSE channel. The plugin currently has no per-user-scan aggregate.
- Phase derivation, SSE subscription, and completion gating all run off `latestScanJob` / `sseStatus` from a *single* child job (`useJobStateMachine.ts:93-110`, `jobStateMachineUtils.ts:46-60`, `useJobStateMachineEffects.ts:92-107`). `useCombinedScanStatus` polls every batch but its data is not consumed by the state machine (`useRecognitionHooks.ts:97-100`).
- SSE bridge forwards an explicit allowlist of progress fields (`class-analysis-jobs-controller.php:578-623`); generated TS `JobProgress` is derived from `packages/shared-contracts/schemas/recognition-job.schema.json`. Anything not in those two surfaces is silently dropped.

**Plugin-side aggregate (the new concept):** introduce a `BatchRun` (or equivalently named) record keyed off the user-initiated submit, owning:

- `submitted_total` — count of media ids the user originally submitted.
- `submitted_media_ids` — the set, for later reconciliation against the "accepted"/"completed" sets.
- `child_job_ids[]` — every backend `scan_job` UUID created for this run (one per accepted batch).
- Per-child counters rolled up: `accepted_total`, `completed_total`, `failed_total`, `cancelled_total`, plus the set of `unreadable_media_ids` reported back per batch.
- `failed_batches[]` — `{ child_job_id?, http_status, error_code, media_ids }` for batches that fail before producing a `scan_job` row (transport / oversize / 4xx / 5xx) and for child jobs that terminate in `failed`/`cancelled`.
- `terminal_state` — derived: every `child_job_id` is in `{completed, failed, cancelled}` AND `submitted_total - (completed_total + failed_total + cancelled_total + unreadable_total) === 0`.

The plugin storage surface and admin REST shape for this record must be picked explicitly (transient vs `wp_acx_*` table). State the choice in the promoted plan; do not leave it implicit.

**Frontend state machine:** stop deriving phase / SSE id / completion from `latestScanJob` alone. Subscribe (or aggregate the existing per-batch poll in `useCombinedScanStatus`) so that:

- Phase = `scanning` while any child job is non-terminal.
- Phase = `complete` only when *all* child jobs are terminal AND `terminal_state` per above.
- Clustering trigger and `removeJob` cleanup gate on aggregate terminal state, not on `sseStatus === 'completed'` of the last child (`useJobStateMachineEffects.ts:92-107`).
- Status text consumes aggregate counters: `Processed completed_total / submitted_total — failed_total failed`, with a separate dropdown listing failed batches and unreadable media.

**Contract promotion (E16-1-PLAN-02):** every new field that crosses a wire must be promoted through the owning surface in the same slice that introduces it. None of the new fields fit `recognition-job.schema.json` (which describes a single backend job); they belong to a new plugin-owned aggregate. Required surfaces:

1. **Aggregate contract** — add a new schema, e.g. `packages/shared-contracts/schemas/wp-batch-run.schema.json`, defining `submitted_total | accepted_total | completed_total | failed_total | cancelled_total | unreadable_media_ids | failed_batches[] | child_job_ids[] | terminal_state`. Regenerate TS + PHP types via the existing `make schemas` (or equivalent) target.
2. **REST surface** — explicit `acx/v1/recognition/batch-runs/<run_id>` endpoint returning the aggregate, with controller wired to the storage chosen above. Existing per-job status endpoints stay unchanged.
3. **SSE bridge** — extend `build_stream_progress_payload` (`class-analysis-jobs-controller.php:578-623`) to include a `batch_run_id` reference on every per-child event, OR add a sibling SSE topic (`/batch-runs/<run_id>/stream`) that fans aggregate updates. Pick one in the promoted plan; do not silently widen the per-job allowlist.
4. **Frontend types** — `JobProgress` is per-child and stays. Aggregate consumed via the new generated `BatchRunStatus` type; the state machine reads aggregate, the existing `useJobProgressStream` keeps its narrow per-child contract.
5. **Tests** — at minimum: (a) earlier child fails while latest child completes ⇒ aggregate non-terminal until both reach terminal, no clustering trigger; (b) latest child completes while an earlier child is still queued ⇒ phase stays `scanning`, no `Processed N/N ✓` shown; (c) one batch rejected pre-`scan_job` (oversize / 4xx) ⇒ counted in `failed_total`, surfaced in failed-batch dropdown; (d) all child jobs terminal AND counts reconcile ⇒ aggregate `terminal_state=true`, clustering triggered exactly once.

**UI surface:** `Processed N/N images` is replaced by `Processed completed/submitted (X failed)` whenever `failed_total + cancelled_total + unreadable_total > 0`; otherwise just `Processed completed/submitted`. Failed-batches dropdown lists `{ batch_index, media_ids, error_code, http_status }`.

**Backend side:** the recognition service does not need to know about `BatchRun`; the aggregate is plugin-owned. The recognition service only needs to keep returning per-job status accurately. If reconciliation reveals existing per-job fields that lie about completion (e.g. `total` updated mid-flight before all media commit), open a follow-up against the recognition service rather than papering over it in the plugin.

**Done when:**

1. A 100-item submit produces one `BatchRun` row covering all child jobs.
2. Forcing one batch to fail (corrupt blob, oversize, mid-flight `scan_job` failure) leaves `terminal_state=false` until the failure is recorded, then `terminal_state=true` with `failed_total >= 1` and the UI shows a non-✓ status with the failed-batch dropdown populated.
3. Forcing the *latest* batch to complete while an earlier batch is still queued no longer triggers clustering or shows `✓ Complete`. Phase stays `scanning`.
4. Aggregate fields are visible in the generated TS types under their canonical names; SSE traffic carries the agreed `batch_run_id` reference; the new REST endpoint returns the same shape as the schema.
5. Tests above pass and the existing `useJobStateMachine` tests are updated, not deleted, to cover the aggregate path.

### E16-1c — Frontend stall detection

- Add a per-stream `lastEventAt` timestamp in `useJobProgressStream`.
- If `now - lastEventAt > STALL_THRESHOLD_MS` (default 30 000) **and** phase ∉ {`Complete`, `Failed`, `Cancelled`}, render a "Stuck — last update Xs ago" badge with `Retry` (re-subscribe) and `Cancel` (issue cancel mutation).
- Tests: simulate stream silence; assert badge appears; assert clicking Retry re-subscribes.

### E16-1d — Suggestion-panel empty-state taxonomy

- Distinguish:
  - **`unconfigured`** — backend DSN unreachable (network error from controller).
  - **`endpoint_error`** — 5xx or schema mismatch.
  - **`empty_backend`** — clusters table is empty (no scans have ever produced clusters).
  - **`zero_pending`** — clusters exist but no pending suggestions.
- Render distinct copy + a remediation action per state.
- **Incremental implementation status:** naming-queue `empty_backend` landed on `354da7f5`; naming-queue `zero_pending` landed on `6defb7c8`; assignment-panel `zero_pending` landed on `85cc1bc8`; suggestion-review `unconfigured` landed on `a949dfa8`; suggestion-review `endpoint_error` discriminator landed on `cc8c30c7`.

### E16-1e — Self-merge guard + friendly merge-error surface

- `findClusterByLabel` (or its callers in `IdentityClusterItem.tsx` / `useClusterSaveAction.ts`) excludes `editableClusterId` from candidate results.
- When candidates are empty after exclusion, treat the input as a pure rename, not a merge.
- Cluster-mutations 4xx responses are caught and re-rendered as inline messages, not raw JSON. (`invalid_target_cluster_id` ⇒ "That cluster is already named X - nothing to merge.")
- **Incremental implementation status:** self-match rename guard landed on `1c4acd83`; the adjacent friendly inline `invalid_target_cluster_id` merge-error surface is green on this branch and was re-verified against `IdentityClusterList.test.tsx` on `1c4acd83`.

### E16-1f — `media_id` → `attachment_id` SQL fix

- One-line change at `apps/prototype-wp-alt-context/src/api/class-api.php:994`.
- Grep `class-api.php` for any other `media_id` references against `wp_acx_identity_members`; fix in the same diff.
- Add a smoke test that `get_dashboard_stats` returns `200 OK` against a populated mirror.
- **Incremental implementation status:** the dashboard stats query now counts `DISTINCT attachment_id` in `wp_acx_identity_members`, no other `media_id` references remain against that table in `class-api.php`, and `DashboardApiTest.php` is green on this branch.

### E16-1g — WP-mirror reconciliation when backend is empty

- Detect backend-empty divergence: on dashboard load, if `last_snapshot_version === 0` and WP still has local assigned/pending clusters, emit a single banner: "Mirror is out of sync with the backend — N stale clusters, M failed sync events. [Reset mirror]". Broader UUID-by-UUID divergence detection remains a follow-up.
- The reset action truncates `wp_acx_clusters | wp_acx_identity_members | wp_acx_sync_outbox`, zeroes the local snapshot state, and re-arms a fresh sync.
- Optional: schedule a cron that auto-detects > 50 % outbox-failure-rate and surfaces the same banner without requiring a dashboard load. This remains out of scope for v0.4.1.

### E16-1h — Cluster-membership integrity check (lower priority)

- Add a tenant-scoped integrity summary that flags suspicious `similarity >= 0.999` attachments linked to more than one projected cluster and surfaces sample attachment IDs through `GET /acx/v1/recognition/sync-status` for operator follow-up.
- Add an operator-facing integrity command (`wp acx mirror-integrity`, plus the repo-local `make localwp-mirror-integrity` wrapper) so operators can block on suspicious local mirror rows before trusting the projection again.
- Investigate why media 6624 (and likely others) accumulated 6× similarity=1.0 cluster assignments.
- Likely candidates: duplicate sync_outbox replay; missing dedupe on `(attachment_id, cluster_uuid)` upsert; clustering job re-run without idempotency.
- May fold into existing td-retry-attempt-observability if root cause is replay-related.
- **Incremental implementation status:** sync-status now returns a `cluster_membership_integrity` summary with a suspicious-attachment count plus sample attachment IDs for perfect-similarity attachments linked to more than one cluster. Operators can also run `wp acx mirror-integrity` (or `make localwp-mirror-integrity`) to print the offending attachment IDs, cluster counts, and cluster UUIDs before trusting the local mirror. The command now supports `--attachment-id=<id>` / `ATTACHMENT_ID=<id>` for the remaining E16-1h drill-down path, so attachment `6624` can be spot-checked directly from the worktree root. Current retained evidence still does not confirm direct replay of attachment 6624 itself: the live backend and live mirror no longer contain 6624 rows, the `wp_acx_sync_outbox` window from `21:26:59` to `21:35:34` contains 30 cluster-only rows with zero payload hits for `6624`, the retained `debug.log` window scan found zero matching lines for `6624`, `sync`, `cluster`, or `identity_members`, and the new attachment-scoped command currently returns a clean local result for `6624` at `similarity >= 0.999`.

## Reset Procedure (proposed for E16-1a)

**Local only.** Per operator instruction: work locally first, push the same procedure to the VMs once the local pipeline is observed clean end-to-end. The VM block lives in the deferred sub-task E16-1a-vm and is reproduced at the bottom of this section as a reference, **not** to be run as part of E16-1a's primary slice.

```bash
# --- Local ---
# 1. Stop description service
cd apps/prototype-description-service && make stop  # or equivalent

# 2. Fix the .env
sed -i '' 's/^DB_NAME=context_alt_text_service$/DB_NAME=alt_context_service/' .env

# 3. Drop legacy DB
PSQL=/opt/homebrew/opt/postgresql@17/bin/psql
$PSQL -h 127.0.0.1 -U context -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='context_alt_text_service' AND pid<>pg_backend_pid();"
$PSQL -h 127.0.0.1 -U context -d postgres -c "DROP DATABASE IF EXISTS context_alt_text_service;"

# 4. Reset the canonical DB + WP mirror in one shot (per [sr-010])
cd /Users/daniel/Development/context-alt-text-monorepo
make reset-local WP_PATH="$LOCAL_WP_ROOT/app/public" CONFIRM_LOCAL_RESET="RESET"
# Repo-local LocalWP admin base: http://localhost:10010/wp-admin/
# `wp-context-alt-text.local` is not a valid address for this install.
# Provenance note: this LocalWP address correction, the matching runbook update,
# and the OCI reset-doc example belong to E16-1a operator guidance on
# `feature/e16-1`. They are not a standalone main-branch maintenance patch.

# 5. Restart description service; verify
make start
$PSQL -h 127.0.0.1 -U context -d postgres -c \
  "SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;"
# Expect: only alt_context_service in the list.
```

### Deferred — VM follow-up (E16-1a-vm)

Run only after the local pipeline is observed clean end-to-end (a 100-item scan completes with `100/100`, no stale clusters, no failed outbox events). Operator authorization required at each step.

```bash
# For each VM env (prod | staging | dev):
#   - SSH to the VM
#   - Update /opt/acx-backend/<env>/secrets/.env: POSTGRES_DB=alt_context_service (+ DSN strings)
#   - docker compose -f docker-compose.env.yml down
#   - sudo rm -rf /opt/acx-backend/data/<env>-pgdata/*   # discards legacy data — confirm before running
#   - docker compose -f docker-compose.env.yml up -d
#   - psql into the new DB; run a smoke health check
```

## Risk

- **E16-1a:** Low (local) — greenfield, well-trodden path, doc already exists.
- **E16-1a-vm:** Low but operator-gated — runs only after local pipeline is verified clean.
- **E16-1b:** **Medium** — touches a new shared-contracts schema, generated TS + PHP types, the SSE bridge, and the frontend state machine simultaneously. The state-machine change is the riskiest piece; existing `useJobStateMachine` tests must be updated to cover aggregate gating, not deleted.
- **E16-1c/d/e/f/g:** Low individually; each is a small, contained change.
- **E16-1h:** Unknown until investigated.
- **Combined risk:** Medium — Theme E touches WP plugin, recognition service contract surface, shared schemas, and WP DB schema. Recommend landing in the order specified, not parallel.

## Out of Scope

- **Re-architecting the scan queue.** Submitter / queue / worker decoupling is a future epic, not a v0.4.1 fix.
- **Identity-clustering correctness work** beyond the lightweight integrity check in E16-1h.
- **Cross-tenant correlation dashboards** (already owned by Theme A).

## Resolved Decisions

Closed during planning review on 2026-05-03 with operator authorization. These are no longer open for discussion; future deviation requires reopening the relevant decision in MCP.

1. **Theme E placement** — **Resolved: Theme E inside E16** (v0.4.1 Public Demo Follow-Ons). No sibling epic E17 created. Promotion of E16-1b–h to full task plans goes under `docs/tasks/15.0/` per the existing E15/E16 stub-vs-plan convention.
2. **Reset procedure** — **Resolved: local only now.** E16-1a ships a local `.env` fix + local pgdata wipe + legacy DB drop. VM env-file updates move to deferred sub-task **E16-1a-vm**, run only after the local pipeline is observed clean end-to-end. Theme E does not block on the VM step.
3. **E16-1g scope** — **Resolved: backend-empty banner + button for v0.4.1.** Mirror reconciliation surfaces a banner with an explicit "Reset mirror" button when the backend snapshot is empty but WP still has local clusters. Broader UUID-by-UUID divergence detection plus any auto-detect cron / >50 % outbox-failure-rate threshold are explicitly **out of scope** for v0.4.1 and tracked as v0.4.2+ follow-ons.
4. **E16-1h placement** — **Resolved: keep exploratory** inside E16 at the lowest priority. Promote to a standalone cluster-correctness task plan only if investigation reveals the 6× similarity=1.0 ingestion is a deeper replay/dedupe bug rather than a one-time artifact of the broken DB-rename state.
5. **LocalWP address docs provenance** — **Resolved: branch-owned E16-1a operator guidance.** The LocalWP admin-base correction in [apps/prototype-wp-alt-context/docs/localwp-development-runbook.md](apps/prototype-wp-alt-context/docs/localwp-development-runbook.md) and the matching `ACX_RESET_SITE_URL` localhost example in [infra/oci/README.md](infra/oci/README.md) ship as part of E16-1a's operator foundation. Historical decision `codex_doc_update_e16_1_localwp_admin_address` (id 2724) mis-attributed that slice to `main`; treat the superseding E16-1 branch decision as the authoritative provenance for those doc lines.

## Acceptance Criteria for the Theme as a Whole

- A 100-item scan produces a single `BatchRun` aggregate that reaches `terminal_state=true` only after every child job is terminal. Completion shows `100/100` or fails with a visible per-batch error count and failed-batch dropdown. No more silent truncation, no more "✓ Complete" off the latest child while earlier batches are still queued.
- A stalled SSE stream surfaces a stall badge within 30 s and offers Retry / Cancel.
- The dashboard SQL error stops appearing in `wp-content/debug.log`.
- "No suggestions" copy distinguishes empty / error / unconfigured.
- A merge action against a cluster's own label produces an inline "already named X" message, not a 400 JSON dump.
- `pg_stat_activity` confirms `context_alt_text_service` is dropped and no local process is connected to it (local). VM follow-up (E16-1a-vm) verifies the same on each VM and archives the rename tech-debt doc.

## Appendix: Symptom → Evidence → Bug ID

| Symptom (from operator session) | Evidence | Member task |
|---|---|---|
| Job 1 stalls 95/100 in `Queued` | E1, E5 | E16-1b, E16-1c |
| Job 2 reports 11/11 of 100 submitted | E1, E5 | E16-1b |
| "No suggestions to review yet" after green ✓ | E1, E7 | E16-1d |
| Stale clusters for media 6622–6626 | E2 | E16-1a (root cause), E16-1g (cleanup) |
| Media 6624 has 6× similarity=1.0 assignments | E2 | E16-1h |
| Dashboard SQL error in debug.log | E4 | E16-1f |
| Indigo-merge offered on Saffron Cypress cluster | E8 | E16-1e |
| `make reset-local` does not produce expected clean state | E3 | E16-1a |

---

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(PLAN-01 closed)` or "resolve E16-1-PLAN-XX"; finding status is queried from the handoff DB via `review_findings(review={"operation":"list","status":"open","task_ref":"E16-1"})` or read from `DASHBOARD.txt`. See [`branch-review-guide.md` § Review Findings Placement](../../agentic/rules/branch-review-guide.md#review-findings-placement-mandatory).

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [x] Confirmed whether external dependency context requires `ctx7`.
- [x] Recorded boundary ownership and compatibility expectations for E16-1b's new shared-contracts schema, REST surface, and SSE bridge change.

### Checklist for E16-1a: Complete local DB rename (foundation)

- [x] Guardrail-only code slice landed (`78d2b0e5` + `a3dd4e90`); local `.env` now points at `alt_context_service`. Remaining items below are still operator verification steps, not branch-local code changes.
- [x] Update `apps/prototype-description-service/.env:25` to `DB_NAME=alt_context_service`.
- [x] Run `make reset-local WP_PATH="$LOCAL_WP_ROOT/app/public" CONFIRM_LOCAL_RESET="RESET"` against the canonical DB.
- [x] Drop legacy DB: `psql -h 127.0.0.1 -U context -d postgres -c 'DROP DATABASE IF EXISTS context_alt_text_service;'`.
- [x] Restart description service; confirm via `pg_stat_activity` that only `alt_context_service` is bound.
- [x] Tick the local items in `docs/tasks/tech-debt/rename-database-context-alt-text-to-alt-context.md`.
- [ ] Verification: 100-item scan persists rows in `alt_context_service` (legacy DB no longer exists locally).
  Supported smoke retry from this branch still fails locally: `make localwp-batch-run-smoke WP_PATH="$HOME/Development/wp-context-alt-text/app/public" SMOKE_LIMIT="100" BATCH_SIZE="5"` exits with `BatchRun status could not be loaded.`, and the post-smoke canonical DB probe still shows `identity_scan_jobs=0`.

### Checklist for E16-1b: BatchRun aggregate + multipart submit failure surfacing

- [x] Add `packages/shared-contracts/schemas/wp-batch-run.schema.json` defining the aggregate fields.
- [x] Regenerate TS + PHP types via `make schemas` (or equivalent).
- [x] Add `acx/v1/recognition/batch-runs/<run_id>` REST surface returning the aggregate.
- [x] Choose and implement `batch_run_id` embedded on every per-child SSE event; the frontend hydrates the aggregate via the dedicated REST surface rather than a sibling aggregate stream.
- [x] Plugin storage decision recorded and implemented via the plugin-owned `wp_acx_batch_runs` / `wp_acx_batch_run_failures` tables.
- [x] Frontend state machine consumes aggregate; phase / clustering / `removeJob` gated on aggregate `terminal_state`.
- [x] UI shows `Processed completed/submitted (X failed)` with a failed-batch dropdown when failures > 0.
- [x] Tests cover earlier child fails while latest completes (no clustering), latest completes while earlier queued (no ✓), pre-`scan_job` 4xx batch surfaced in `failed_batches`, and aggregate terminal triggering clustering exactly once.

### Checklist for E16-1c: Frontend stall detection

- [x] Add `lastEventAt` per stream in `useJobProgressStream`.
- [x] Stall threshold (default 30 000 ms) + non-terminal phase ⇒ "Stuck - last update Xs ago" badge with Retry / Cancel.
- [x] Tests simulate stream silence, assert the badge appears, and assert Retry re-subscribes.

### Checklist for E16-1d: Suggestion-panel empty-state taxonomy

- [x] Naming queue `empty_backend` state landed (`354da7f5`) with explicit scan guidance.
- [x] Naming queue `zero_pending` state landed (`6defb7c8`) with explicit already-labeled guidance.
- [x] Assignment panel `zero_pending` state landed (`85cc1bc8`) with explicit review-next guidance.
- [x] Assignment/suggestion panel `unconfigured` state landed (`a949dfa8`) with explicit recognition-service connection guidance.
- [x] Assignment/suggestion panel `endpoint_error` state landed (`cc8c30c7`) with distinct backend-error copy + remediation.
- [x] Tests cover each variant.

### Checklist for E16-1e: Self-merge guard + friendly merge-error surface

- [x] `findClusterByLabel` (or its callers) excludes `editableClusterId` from candidates.
- [x] Empty post-exclusion result treated as rename, not merge.
- [x] Cluster-mutations 4xx responses rendered inline (`invalid_target_cluster_id` ⇒ "That cluster is already named X — nothing to merge.").

### Checklist for E16-1f: Dashboard `media_id` → `attachment_id` SQL fix

- [x] Fix `apps/prototype-wp-alt-context/src/api/class-api.php:994`.
- [x] Audit `class-api.php` for other `media_id` references against `wp_acx_identity_members`; fix in the same diff.
- [x] Smoke test: `get_dashboard_stats` returns `200 OK` against a populated mirror.

### Checklist for E16-1g: WP-mirror reconciliation when backend is empty

- [x] Detect divergence on dashboard load (banner landed on `09ed04f8` via the `last_snapshot_version === 0 && localClusterCount > 0` heuristic; UUID-by-UUID divergence comparison remains a follow-up — see review finding `E16-1G-BR-01`).
- [x] "Reset mirror" button truncates `wp_acx_clusters | wp_acx_identity_members | wp_acx_sync_outbox`, zeroes the local snapshot state, and re-arms sync (`e5256e1c`).
- [ ] Auto-detect cron deferred to v0.4.2+ per Resolved Decisions §3.

### Checklist for E16-1h: Cluster-membership integrity check

- [x] Add a tenant-scoped integrity summary that flags suspicious `similarity >= 0.999` attachments linked to more than one projected cluster and surfaces sample attachment IDs through `GET /acx/v1/recognition/sync-status`.
- [x] Add an operator-facing integrity command (`wp acx mirror-integrity` and `make localwp-mirror-integrity`) that reports attachments with `COUNT(DISTINCT cluster_uuid) > 1` at `similarity >= 0.999` before the mirror is trusted.
- [x] Investigate media 6624's 6× similarity=1.0 cluster assignments. Current retained evidence does not confirm direct replay of attachment `6624`; the live backend and live mirror are clean, the historical outbox window contains only cluster-level rows with zero payload hits for `6624`, and the attachment-scoped mirror-integrity command currently reports no suspicious local row for `6624` at `similarity >= 0.999`.
- [ ] Decide: standalone cluster-correctness task plan vs. fold into `td-retry-attempt-observability`.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence (especially the new `wp-batch-run` schema, REST surface, and SSE bridge change in E16-1b).
- [ ] Runtime-parity checks are included where tests can mask real behavior (a 100-item end-to-end scan against the canonical DB after E16-1a lands).
- [ ] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- [ ] None — Theme E sticks to the demo-blocking minimum; ambition expansions (auto-detect cron, deeper cluster-integrity work) are tracked as v0.4.2+ follow-ons.

## Success Criteria

See [`## Acceptance Criteria for the Theme as a Whole`](#acceptance-criteria-for-the-theme-as-a-whole) above. Each bullet maps to an observable outcome and is restated here as a checklist:

- [ ] 100-item scan produces a single `BatchRun` aggregate that reaches `terminal_state=true` only after every child job is terminal; UI shows `100/100` or a visible per-batch failure count.
- [x] Stalled SSE stream surfaces a stall badge within 30 s with Retry / Cancel.
- [ ] Dashboard SQL error stops appearing in `wp-content/debug.log`.
- [ ] "No suggestions" copy distinguishes empty / error / unconfigured / zero-pending.
- [ ] Self-merge against a cluster's own label produces inline "already named X" message, not a 400 JSON dump.
- [ ] `pg_stat_activity` confirms `context_alt_text_service` is dropped locally; rename tech-debt doc local items ticked.
