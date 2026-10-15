# Task Plan — WBTRUST-4

> **Date:** 2026-10-15
> **Author:** claude (Sonnet 5.5)
> **Owning Epic:** none yet — umbrella scope [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> **Task ID:** WBTRUST-4
> **Target Branch:** feature/wbtrust-4
> **Base SHA:** 372a6413a7ae0eb71baa3566716546684bac5a58
> **Revision:** 1
> **Review Coverage Target:** frontend request behavior; no service or limiter change
> **Depends on:** none (Wave A; ships first so the 429 storm stops contaminating WBTRUST-1/3 repros)
> **Executor:** `claude-remote` `claude-haiku-5-5`, effort `xhigh` for implementation and grunt work (operator order 2026-10-15). Brief each slice separately (1–3 files), inline the slice text plus codemap snippets; if the write-enabled remote Claude harness is denied or unavailable, record a blocker and ask the operator — no silent fallback to another model.
> **Prior art:** [scope](../../scopes/workbench-curation-trust-scope.md) (R14, root cause 8), [UXP-NET-1 scope](../../scopes/uxp-net-1-429-fanout-scope.md) (shipped partly; tier changes ruled out), [UX-map evaluation](../../assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md) (A6, A7, C3), [workbench-operator-loop map](../../../apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.md)
> **Carried findings (by ID only):** none recorded yet; query `review_findings(list, task_ref="WBTRUST-4")`

## WBTRUST-4. Request budget — end the 429 storm

Frontend paths are relative to `apps/prototype-wp-alt-context/js/admin/`.

## Objective

An idle workbench with 20 active jobs issues ≤ 40 recognition-bound requests per minute; a scan-complete burst issues ≤ 10; a 5-minute replay on the fir tenant records zero 429.

## Problem Statement

The console shows `429 (Too Many Requests)` on `recognition/suggestions`, `suggestions/merge`, `suggestions/name`, one `identities/suggestions?identity_ids=<uuid>&top_k=5` per identity, `clusters/<id>/roster-candidates`, and repeated `recognition/jobs/<uuid>` polls (~16 job ids). The stacks run through TanStack Query `invalidateQueries`/`refetchQueries` after `assignToCluster`/`onConfirm` and after scan `onSubmit`. Downstream effects: "Could not load name suggestions" (R9) and saves that look unsaved (R10).

## Constraints

- Limiter is 60 requests/min per API key, burst 10 (`recognition/config/security.py`). **No tier change or exemption** (UXP-NET-1). Flag the question to the operator; do not decide it.
- Keep `recognitionCooldown.ts` semantics: `gateRefetchInterval` never returns `false` mid-cooldown; `runAfterCooldown` re-checks on wake.
- No new endpoint in the required slices. rg-007: bounded stall detection in any new loop. sr-008: ≤ 8 destructured params.
- Tests run on the remote VM lane; no local containers.

## Workflow Principles

- Measure first (S1). The four drivers named in the scope are hypotheses until the harness counts them.
- One owner for "how often may the page poll": the registry (S2). Call sites declare a base interval; they do not compute their own backoff.
- Prefer removing a request to rate-shaping it.

## Terminology

**Poller** = any TanStack `refetchInterval` or `setInterval` that hits the recognition API. **Budget** = requests/min the page may spend on pollers.

## Current State Analysis

- `utils/recognitionCooldown.ts`: module singleton — `openCooldown`, `openCooldownFromError`, `isCoolingDown`, `cooldownRemainingMs`, `DEFAULT_COOLDOWN_SECONDS` 30, `MIN_GATED_INTERVAL_MS` 1000, `gateRefetchInterval(baseMsOrFn)`, `runAfterCooldown(fn)`, `_resetCooldownForTests`. Gated pollers today: useScanStatus, useMultiScanStatus, useBatchRunStatus, useDescribeRunProgress, useMediaIdentities, useRecognitionClusters, useExportJobStatus.
- `hooks/useRecognitionHooks.ts`: `getJobRefetchInterval` 1500 ms while running/pending/`awaiting_projection`; `getBatchRunRefetchInterval` 1500 ms; `useMultiScanStatus(jobIds)` runs one `useQueries` poller per id (20 jobs ≈ 800 req/min against a 60 limit); a further 30 000 ms gated poll exists.
- Ungated or separately cadenced: `useSyncStatus` (120 000), `useRosterHooks` (60 000), `useMediaIdentities` (3000 while `hasPendingClustering`), `useRetentionStatus`, `useGpuServiceStatus`, `useSyncHealth`, `useDescribeRunProgress`, `pages/settings/useGpuControl.ts`.
- `hooks/useJobStateMachineEffects.ts`: scan success → `runAfterCooldown` → invalidate `media.identities()`, `clusters.all`, `suggestions.all`; batch-run terminal → `media.identities()` + `clusters.all`; the SSE clustering-completed branch invalidates **without** `runAfterCooldown`. `hooks/useJobProgressStream.ts` ticks every second.
- Suggestion fan-out: `useInlineSuggestionBatch(identityIds)` makes one batched `fetchIdentitiesSuggestions` per ≤ `IDENTITY_SUGGESTIONS_MAX_BATCH_SIZE` (100) ids (≤ 4 workers) under `identityBatchIdsKey(ids)` and seeds single-id keys (`seedIdentityBatchSingles`). Hypothesis: the batch key changes whenever the id set changes, so each membership change refetches the whole set. Single-id queries come from `useClusterSuggestionsLoader` (mounted by `IdentityClusterItem` with `enabled: editState.isEditing`, and `UngroupedResidueEditor` with `enabled: true`) in `IdentityClusterList.tsx`; they take `initialData` from the batch cache but a mount that races the batch fires its own request. `unlabeledSuggestionBatchIds(groups)` (`utils.ts`) builds the batch list; `invalidateSuggestionProjection` invalidates `suggestions.projection.all`; `PROJECTION_TOP_K` 5; `IDENTITY_BATCH_STALE_MS` 60 000.
- Save path: `utils/invalidateLabelSurfaces.ts` invalidates eight families on every label save (`media.identities()`, `clusters.labels()`, `clusters.all`, `roster.entries()`, `suggestions.projection.all`, `suggestions.mergePending()`, `suggestions.namePending()`, `roster.all`) via `useClusterMutations.ts`.

## Target Outcome

| Measure | Target |
| --- | --- |
| Idle, 20 active jobs | ≤ 40 recognition-bound requests/min |
| Scan-complete burst | ≤ 10 requests in the 10 s after completion |
| 5-minute replay, fir tenant | 0 × 429 |
| During a cooldown | one "Busy — resuming in Ns" status line; no per-card errors |

## Context Loading

`recognitionCooldown.ts`, `hooks/useRecognitionHooks.ts`, `hooks/useJobStateMachineEffects.ts`, `hooks/useJobProgressStream.ts`, `pages/workbench/identity-clusters/IdentityClusterList.tsx`, `useClusterSuggestionsLoader.ts`, `useInlineSuggestionBatch*`, `utils/invalidateLabelSurfaces.ts`. Canon (v0.26.2): RES-05, RES-06, RES-12, RES-13, RES-15, PERF-02, INT-08, PERC-07, API-08.

## Contract and Boundary Impact

- None in required slices. Optional S6 adds `GET recognition/jobs?ids=` (contract extension, rg-015 pass-through).
- **Open decision (operator, flagged not made):** limiter tier for the workbench key. UXP-NET-1 ruled out tier changes; record the measured request profile in the S1 decision so the operator can revisit with numbers.

## Proposed Solution

A single poller registry computes each poller's effective interval from the number of active pollers: `interval = max(base, activePollers × 60000 / BUDGET_RPM)` (e.g. 40 rpm and 20 pollers ⇒ 30 s each). SSE-covered jobs stop polling while the stream is open. Post-event invalidation becomes targeted (refetch the batch and re-seed singles rather than invalidating `suggestions.all`) and coalesced through `runAfterCooldown`. Cooldown is shown once.

## Files and Surfaces to Change

Owned paths:

- `utils/recognitionCooldown.ts`, new `utils/pollBudget.ts` (registry via `useSyncExternalStore`), `hooks/useRecognitionHooks.ts`, `hooks/useJobStateMachineEffects.ts`, `hooks/useJobProgressStream.ts`
- `pages/workbench/identity-clusters/IdentityClusterList.tsx`, `useClusterSuggestionsLoader.ts`, `useInlineSuggestionBatch*`, `utils.ts` (batch ids), `utils/invalidateLabelSurfaces.ts` (call-site narrowing only; WBTRUST-3 owns its save-path use)
- `hooks/useMediaIdentities.ts`, `useRetentionStatus`, `useGpuServiceStatus`, `useSyncStatus`, `useRosterHooks` (declare base interval to the registry)
- New tests: `__tests__/requestBudget.*.test.tsx` and a shared counting harness under the test helpers directory

## Verification Strategy

- Harness: fake timers + a fetch mock that counts by route family; scenarios "20 running jobs, 5 min idle", "30 identities, membership changes", "scan completes", "429 on one route".
- Browser (fir tenant, operator or Chrome tier): 5-minute network panel capture with the real 20-job state; zero 429.
- `npm run typecheck`, `npm run lint`, `vitest run` on the VM.

## Slice Delivery

### Slice S1: request-counting-harness

Count before changing anything.
Closes: R14 (diagnosis). Canon: PERF-02, EVAL-16.
Design decision (binding): a reusable harness (fake timers + route-family counter) lands first with RED budget tests per scenario; the decision records requests/min per family and ranks the drivers (a)–(d) from the scope by measured share. Drivers that measure < 10 % of traffic are dropped from later slices.
Acceptance: harness committed; per-family numbers recorded in the handoff decision; RED tests fail on the base SHA.

### Slice S2: aggregate-poll-budget

One owner for polling cadence.
Closes: R14. Canon: RES-05, RES-12, RES-15, PERC-07.
Design decision (binding): `pollBudget` registry counts mounted pollers and returns each one's interval from the formula; `BUDGET_RPM` default 40 (headroom under 60). All listed pollers register with a base interval; `useMultiScanStatus` shares one registration per poller. `gateRefetchInterval` stays the cooldown gate and composes with the registry (never `false`). Unmount deregisters.
Acceptance: "20 jobs idle" scenario ≤ 40 requests/min; registering/deregistering a poller changes the others' intervals within one tick; cooldown tests unchanged.

### Slice S3: sse-short-circuit

Stop polling what a stream already reports.
Closes: R14. Canon: RES-13, API-08.
Design decision (binding): while `useJobProgressStream` is open for a job, that job's poller registers as `paused` (kept for stall detection with a 60 s floor, rg-007); the SSE clustering-completed branch goes through `runAfterCooldown` like the polled branches.
Acceptance: stream-open scenario issues ≤ 1 status request/min per streamed job; the SSE branch no longer invalidates during cooldown.

### Slice S4: targeted-invalidation

Refresh what changed, not every family.
Closes: R14, R10 (read-your-writes dependency). Canon: RES-06, RES-13.
Design decision (binding): scan success/batch terminal refetch `media.identities()` and the suggestion batch, then re-seed singles; `suggestions.all` and `clusters.all` are no longer invalidated together. The `batchIdsKey` is made stable across membership changes (page-based key or incremental diff) so adding one identity does not refetch the other 29. `invalidateLabelSurfaces` keeps its family list; each family call goes through `runAfterCooldown` and de-duplicates within one tick. Coordinate with WBTRUST-3 S4: this slice provides the primitive, WBTRUST-3 uses it for the save path.
Acceptance: "30 identities, one membership change" ≤ 2 suggestion requests; "scan complete" ≤ 10 requests in 10 s.

### Slice S5: single-wait-state

Say it once.
Closes: R14. Canon: INT-08, PERC-07, A11Y-21.
Design decision (binding): while the cooldown is open, per-card/per-query errors from rate limiting are suppressed in favour of one `role="status"` line "Busy — resuming in Ns" in the activity strip (countdown from `cooldownRemainingMs`), then a single retry wave through the registry.
Acceptance: a 429 on `identities/suggestions` shows no "Could not load name suggestions" while cooling down; the line is announced once, not per tick.

### Slice S6: batch-jobs-status (optional)

Only if the S2–S5 numbers still miss the targets.
Closes: R14. Canon: API-08, RES-12, rg-015.
Design decision (binding): `GET recognition/jobs?ids=` returns the same envelope per id; PHP proxy passes it through verbatim; the client replaces N pollers with one registration.
Acceptance: contract doc, PHP controller test, service test, and the "20 jobs" scenario at ≤ 6 requests/min.

### Slice S7: replay-and-docs

Prove it on the real tenant.
Closes: R14. Canon: EVAL-16.
Design decision (binding): record a 5-minute browser capture on the fir tenant (route-family table before/after) in the decision; update `workbench-operator-loop` map text if the wait-state line becomes a named zone; run `make lint-ux-maps`.
Acceptance: 0 × 429 in the capture; operator-visible limiter-tier question restated with the final numbers.
