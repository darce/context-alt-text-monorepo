# UXREC-1 workbench recovery task plan

> **Metadata**
>
> - **Date**: 2026-10-21 17:30 EST
> - **Author**: PLAN3, codex-remote gpt-6.1-sol (xhigh); identity copy-equality correction by PLAN4, claude-remote claude-opus-5-5 (xhigh)
> - **Project**: `apps/prototype-wp-alt-context` (WordPress admin SPA)
> - **Task ID**: `UXREC-1`
> - **Task Plan Status**: `proposed`. Not approved, not running product work, not deployed, not accepted.
> - **Target Branch**: `feature/uxrec-1` (the UXREC integration branch). Each slice is authored on its own lane branch and merged into `feature/uxrec-1`.
> - **Review Coverage Target**: 1 independent planning review of the joined plan, inventory and maps before any slice starts.
> - **Anchors verified at**: exact source `077ea234f222dd74ecb6031ab0073b78b61ca80a` on 2026-10-21, including security documentation main `e08970cda`. Native provenance establishes the source-to-sandbox tree correspondence (history-stripped sandbox base `d4693910b4908d71ae7feedc9c1c1670810f3a3a`); original commit objects are absent by design. Existing change-site anchors were checked in this checkout; proposed symbols and tests are marked new.
> - **Upstream traceability**: decision 18935 amends shared contract decision 18920 (`uxrec_adjudication2_common_contract`) for guarded History row recovery and G1 DONE/result gating; map import decision 18886; map filename anchor correction decision 18916. Review coverage, finding status and run history live in the handoff DB. Query them with `get_review_coverage(task_ref="UXREC-1")` and `review_findings(review={"operation":"list","task_ref":"UXREC-1"})`.

Frontend paths below are relative to `apps/prototype-wp-alt-context/` unless they start with `apps/`.

## UXREC-1. Workbench recovery: needs-attention changes, evidence-bound GPU copy, repeated-region evidence

## Objective

Three independent frontend slices:

- **TIMELINE**: the Changes panel opens on **Needs attention › Failed**. A failed operation appears in only one list, and audit history moves to an explicit **History** view.
- **GPU_STATUS**: GPU toasts stop claiming CPU drafts that the server has not returned. DONE with zero returned drafts has neutral completion copy; review requires positive results and an available href. A received `endpoint_unconfigured` envelope gets configuration copy instead of the generic error.
- **IDENTITY**: a face-group card can disclose in place that the same exact photo region is also listed under another loaded group. The disclosure does not change grouping, naming targets or removal targets.

## Intake

- **Key decisions**: decision 18920, amended by decision 18935, fixes the shared bounded contract for TIMELINE, GPU and IDENTITY. This plan and the inventory follow it.
- **Inventory and screens**: [UXREC-1 UX inventory](../../assessments/current/UXREC-1-ux-inventory.md).
- **Map SSOT**: `docs/ux-maps/{workbench-operator-loop,describe-gpu-tier,workbench-identity-chips}.uxmap.json`. One map writer owns those maps, their generated `.md` and their three entries in `render_ux_maps.visible.json`. Product slice authors never write maps.
- **Not doing**:
  - No backend, PHP or Python change.
  - No change to `GpuStatusResponse` or any other response shape.
  - No GPU automation, actuation, auth bypass, billing or credential change.
  - No combined attention status and no aggregate unresolved total.
  - No clearing, hiding or age-only filtering of the four supplied July failed records.
  - No new route, tab, panel, review callback, `ClusterReviewPanel` change or "Review faces" navigation.
  - No new evidence crop or image.
  - No IoU or similarity matching, automatic merge or transitive identity closure.
  - No detector or recall repair claim, and no new identification of any person.
  - No change to WBTRUST-5-reserved composition files.
  - No map, render, projection or product-style edits by the authors of this plan.

## Problem Statement

- **TIMELINE.** `DeadLetterPanel` shows a failed operation twice, with recovery buttons both times. The panel always mounts the failed list (`useDeadLetterOperations`). It also mounts an all-status timeline (`useOutboxOperations`, default `timelineStatus: 'all'`), whose failed rows render Retry and Discard because `DeadLetterOperationRow` sets `showFailedRecovery` for any failed row. Current work and retained audit history share one screen, so an operator cannot tell what still needs action.
- **GPU_STATUS.** The visible toasts promise CPU work that the server may never do. `useGpuStateToasts` (mounted by `js/admin/App.tsx`) shows `GPU_STATE_VOCABULARY.warmingToast` ("GPU warming — CPU drafts first") and `degradedToast` ("GPU unavailable — CPU drafts kept"). The degraded toast always offers "Review results". DONE always offers "Review N drafts", including zero, and its click silently returns when `reviewDraftsHref` is null. `useActivityStatus` currently offers that href for any DONE with a non-null run id, without a completed-count guard. The worker continues on CPU only after a warm-up timeout, and only when a usable CPU adapter exists (`describe_run_worker.py:_apply_warmup_cpu_fallback`, `_usable_cpu_describe_one`). Otherwise the run fails with a typed terminal. Separately, `serviceUnavailable.ts:unavailableReasonCopy` has no entry for `endpoint_unconfigured`. That reason passes through the PHP GPU control proxy and falls back to "an unexpected error occurred (endpoint_unconfigured)" with a generic Retry hint.
- **IDENTITY.** A repeated region is invisible. `groupIdentitiesByClusters` groups by person, then cluster, then ungrouped. It removes same-face overlaps only inside one group, so the same photo region listed under two groups shows as two unrelated cards with no cue. The supplied case is three crops the operator identifies as one person. `ClusterPreview` can show a representative from another photo, so the thumbnail is not evidence of which observation matched.

## Constraints

- Own only the paths in [Files and Surfaces to Change](#files-and-surfaces-to-change). The slices share no file. Other shared surfaces have exactly one writer (see [Lane Decomposition](#lane-decomposition-multi-agent)).
- WBTRUST-5 reserves `pages/workbench/MediaSelection.tsx`, `ActivityStatusStrip.tsx`, `AdvancedDrawer.tsx`, `pages/WorkbenchPage.tsx`, `WorkbenchTwoPaneLayout.tsx`, `mediaFooterCtaState.ts`, `GpuTierStatus.tsx` and `styles/components/_workbench.scss` (`docs/tasks/v0.5.0/WBTRUST-5-control-placement-task-plan.md`, Files and Surfaces to Change). UXREC slices read them and never edit them.
- WBTRUST-4 lists `identity-clusters/IdentityClusterList.tsx` and `identity-clusters/utils.ts` as owned paths (`docs/tasks/v0.5.0/WBTRUST-4-request-budget-task-plan.md`). Confirm there is no actual concurrent author on those shared files. This is file exclusivity, not a dependency on an absent WBTRUST-4 worker (see [Conflict graph](#conflict-graph)).
- Product styles: only IDENTITY may edit `js/admin/styles/components/_identity-cluster-list.scss`, and only for narrow wrapping and disclosure layout. TIMELINE and GPU reuse existing classes. Nobody edits `_cluster-panels.scss`.
- `js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts` is a read-only localization guard. It scans every non-test `.ts`/`.tsx` under `identity-clusters/` and fails on a non-literal first argument to `__`/`_n`/`_x`/`_nx`. All new copy in every slice uses literal first arguments.
- `js/admin/__tests__/banned-vocabulary.test.tsx` is a read-only guard. Its page sweep bans words such as `projection` and `dead-letter`, and bans UUIDs in rendered page text. It also bans `cluster`/`identity` words on review surfaces. New visible copy avoids those words (use "face group" and "face record"). Exact UUID references appear only inside the collapsed IDENTITY disclosure body. They never appear in a summary, heading, accessible name or toast.
- Tests run on the VM only, from `apps/prototype-wp-alt-context`, with existing offline dependencies. Use `npm test -- <files> [-t '<name>']` (`vitest run`). Do not use `test:agent`: it swallows failures (`vitest run "$@" || true`).
- Preserve the operator-tenant GPU authorization (`routers/gpu.py:_is_gpu_operator`, `authorize_operator_control`) and the `encodeURIComponent` run-path encoding in `js/admin/api/describeApi.ts`. No slice edits these files.

## Workflow Principles

- **RED before GREEN.** Add the named assertion, predict its failure message, and watch it fail against unchanged production source ([TEST-06] **Watch it fail once / predict the failure**, *Modern Software Engineering, ch. 8*). Then make the smallest owned change and rerun the same selector GREEN.
- **One home per action.** A failed operation's Retry and Discard render in one list per view, never two at once ([INT-19] **One outcome per interaction**, *Microinteractions, ch. 1* + *Microinteractions, ch. 3*).
- **Claims follow returned evidence.** Copy states what the server returned, not what might happen ([HAI-05] **Imperceptible AI is not ethical**, *Human-Centered AI*).
- **Abstain rather than force.** The identity projection abstains on malformed or conflicting input, including loaded copies of one face record that disagree. It never picks a winning copy and never classifies a person.
- **Reuse, then add.** Reuse the existing queries, mutations, guarded confirmations, vocabulary and native `<details>` pattern. New symbols are marked **(new)**.
- **Source completion is not runtime acceptance.** Every slice closes on source tests. Deployed behaviour is accepted only in a separately granted runtime window (see [Verification Strategy](#verification-strategy)).

## Terminology

- **Needs attention**: the default Changes view. Its status choices are **Failed** (default), **Pending** and **Conflict**. The view has no combined status or total.
- **History**: the existing all-status or single-status outbox timeline. Only failed rows retain their existing guarded row recovery, once per view. It does not show the bulk maintenance zone.
- **Maintenance zone**: the bulk controls `Retry all failed (N)` and `Discard N eligible` / `Discard eligible failed changes` (`data-testid="acx-zone-z-dl-actions"`), with their armed confirmations and results list.
- **Returned drafts**: `ActivityStatus.draftCount`, which is `run.completed ?? 0` (`useActivityStatus.ts:describeDraftCount`). It counts results without tier proof.
- **Observation**: one loaded `DetectedIdentity` record (`identity_id`, `media_id`, `bbox`, `person_id`, `cluster_id`), read before same-face dedup.
- **Retained tuple**: every field a `RepeatedRegionObservation` keeps: `identityId`, `mediaId`, `groupKey`, `personId`, `clusterId` and the `bbox` numbers `x`/`y`/`width`/`height`. Loaded copies of one `identity_id` collapse only when the whole tuple is equal.
- **Group key**: `person:<person_id>`, else `cluster:<cluster_id>`, else `ungrouped`. These are the keys `groupIdentitiesByClusters` already uses.
- **Repeated region**: two or more eligible observations with the same positive `media_id` and exactly equal `x`/`y`/`width`/`height` under at least two different group keys.
- **Loaded pool**: the identities passed to `IdentityClusterList` for one media row. No corpus total, completeness, title or hash field exists.

## Current State Analysis

### TIMELINE (`js/admin/pages/workbench/DeadLetterPanel.tsx`)

- `TIMELINE_STATUSES` is `['all','pending','acknowledged','conflict','failed','discarded']`. `DeadLetterPanelState` has `offset` (failed list), `timelineOffset` and `timelineStatus`. `INITIAL_STATE.timelineStatus` is `'all'`.
- `deadLetterPanelReducer` handles `setOffset`, `setTimelineOffset`, `setTimelineStatus` and the armed and discard actions. `handleTimelineStatusChange` sets the status and resets `timelineOffset` to 0.
- `DeadLetterPanel` always calls three queries:
  - `operationsQuery = useDeadLetterOperations({ limit: PAGE_SIZE (20), offset })`;
  - `bulkDiscardPageQuery = useDeadLetterOperations({ limit: BULK_DISCARD_PAGE_SIZE (50), offset: 0 })`;
  - `timelineQuery = useOutboxOperations({ limit: TIMELINE_PAGE_SIZE (10), offset: timelineOffset, status })`.
- `useOutboxOperations` (`js/admin/hooks/useOutboxOperations.ts`) has no `enabled` option. It wraps `fetchOutboxOperations` (`js/admin/api/recognition/conflictApi.ts`), which sends a single optional `status`.
- Render order: maintenance zone, then "Pending changes timeline" (h4, status buttons, rows with `variant="timeline"`), then the failed list (`variant="failed-list"`). Rows come from `DeadLetterOperationRow`. Its `showFailedRecovery = variant === 'failed-list' || isFailedOperation(operation)`, so failed timeline rows show Retry and Discard too.
- When `operationsQuery` is loading or errors, the component returns early. The whole panel, timeline included, is then replaced by loading or error copy.
- Mount: `js/admin/pages/WorkbenchPage.tsx` (WBTRUST-5-reserved) renders the panel under the overlay h2 "Failed Sync Queue".
- Already integrated and kept: server-anchored failure age, the 7-day eligibility pages, armed bulk confirmations that disarm on timeout or total change, halt-on-4xx bulk discard, and row-identity announcements.
- The four supplied July failed label-update records stay failed until existing reconciliation (`src/sovereign/sync/class-outbox-maintenance-service.php`) or an operator action changes their status. Unit fixtures cannot prove their eligibility.

### GPU_STATUS

- `js/admin/pages/workbench/gpuStatePresentation.ts:GPU_STATE_VOCABULARY` holds the visible strings `warmingToast` and `degradedToast`, and the latent strings `notReportedNotice` and `startingNotice`.
- `gpuStateNotice` has no production caller. It is referenced only by `pages/workbench/__tests__/gpuStatePresentation.test.ts`. `ActivityStatusStrip.tsx:idleHeadline` uses only `readyNotice`, `degradedNotice` and `stoppedNotice`.
- `js/admin/hooks/useGpuStateToasts.ts:useGpuStateToasts` has these branches:
  - DEGRADED edge: `error(degradedToast)` with a "Review results" action to `/workbench`, whatever `draftCount` is;
  - WARMING: `info(warmingToast)`;
  - WARMING to DESCRIBING: `readyToast` with "Back to run";
  - DONE: `doneToast` with "Review N drafts" even at zero; a null `actions.reviewDraftsHref` leaves a visible no-op action;
  - FAILED: reason copy with Retry only when retryable, and dormant `GPU_STATUS_UNAVAILABLE` suppressed when `runId === null`.
- Worker outcomes (`apps/prototype-description-service/scene/application/describe_run_worker.py`):
  1. GPU ready: `_wait_for_gpu_ready` returns and describing proceeds on GPU.
  2. Warm-up `TimeoutError` with a usable CPU adapter: `_apply_warmup_cpu_fallback` returns a continuation and the caller sets `gpu_policy = None`. `_persist_warmup_cpu_fallback_reason` records the fallback, and no later upgrade to GPU occurs.
  3. Timeout without a usable adapter: the run fails with terminal code `gpu_warmup_timeout`.
  4. `gpu_run_policy` returns `None` when no endpoint URL is set, so no warm-up runs.
- Frontend evidence types (`js/admin/api/describeApi.ts`): `DescribeRunResponse.fallback_reason`, `DescribeRunResponse.terminal` (`DescribeRunTerminal.code` / `.retryable`), and item tiers `DESCRIBE_RESULT_TIER.PROVISIONAL_CPU` / `FINAL_GPU`.
- `js/admin/utils/serviceUnavailable.ts`:
  - `UNAVAILABLE_REASON` has 7 members with no `endpoint_unconfigured`.
  - `unavailableReasonCopy` returns the generic fallback for unknown reasons.
  - Consumers are `pages/settings/GpuControlCard.tsx` (it reads `readUnavailable(data) ?? readUnavailable(intentError) ?? readUnavailable(error)` and renders "%s is unavailable because %s." plus the fix) and `pages/RetentionPage.tsx`.
- `src/api/class-gpu-control-controller.php:map_unavailable_reason` passes typed scene reasons through. The envelope shape is pinned by `tests/Unit/GpuControlControllerTest.php:testGetStatusPassesThroughUnknownServiceUnavailableReason`: `{reason:'endpoint_unconfigured', service:'scene', http_status:503, retry_after_seconds:null, checked_at:'2026-09-18T14:03:22Z'}`.
- `scene/interface_adapters/http/routers/gpu.py:GpuStatusResponse` (`extra="forbid"`) has no configuration or capability field. The scene `/gpu/status` handler never emits `endpoint_unconfigured`. That reason comes from describe paths (`routers/describe.py`). `GpuControlCard` maps stale telemetry to `GPU_STATE.UNKNOWN` (`displayedState`). Unknown or stale telemetry therefore cannot be read as "not configured".
- `useActivityStatus.ts:describeDraftCount` reads `run.completed ?? 0`; `useActivityStatus` derives `actions.reviewDraftsHref` inside its actions `useMemo`. Consumers traced: `useGpuStateToasts` uses the href for DONE; `ActivityStatusStrip` renders a review link only when the href is non-null. `MediaSelection.tsx:PendingDescribeRecovery` uses cancel/retry only. `navigation/appLinks.ts:serializeRunParam` rejects null/empty/whitespace ids; `toDescriptionHistoryRun` uses that codec and currently builds `#/workbench?hasDraft=1&run=<encoded-id>`. Reuse that builder; its name does not license a new history route.

### IDENTITY (`js/admin/pages/workbench/identity-clusters/`)

- `utils.ts:groupIdentitiesByClusters` builds the group key inline (`identity.person_id || null`, then `cluster_id != null`, then `UNGROUPED_GROUP_KEY`). It records `identityClusterIds` and `clusterIds`, then drops a member only when `isSameFaceInMedia` matches an existing member of the same group (same `media_id`, both boxes usable with width and height > 1, IoU > `SAME_FACE_BBOX_IOU` 0.5).
- `getEditableClusterId(cluster)` is the naming target. `IdentityClusterItem` removes with `mutations.reassign([representative.identity_id])`, where `representative = cluster.members[0]`.
- `js/admin/api/recognition/types/identity.ts:DetectedIdentity` has `identity_id`, `media_id`, `bbox: BoundingBox {x,y,width,height}`, `cluster_id`, `person_id?` and `cluster_label`. It has no content hash, source title or corpus total.
- `IdentityClusterList` (props `identities`, `dataSource`, `isLoading`, `onRetry`) is mounted only by `MediaSelectionTableBody.tsx` with `item.identities` for one media row. It memoizes `groupIdentitiesByClusters(identities)`, renders one `IdentityClusterItem` per non-ungrouped group, and renders `UngroupedResidueSection` ("Not yet grouped (N)").
- `IdentityClusterItem` renders `ClusterPreview` and a label button that calls `startEditing` (the existing primary naming action). It also renders `ClusterActions` ("Edit label" / "Name this person", "Remove from group") and a native `<details className="acx-identity-cluster__not-same-person">` for Split.
- `ClusterPreview` prefers `representative_face` (possibly from another photo) over the row member. It is a thumbnail only and is non-interactive.
- `ClusterPanelContext.tsx:readReviewFromParams` needs `panel=review&cluster=<id>`. `IdentityClusterList` has no review callback, and this plan adds none.
- Existing list and item test fixtures default to 1×1 boxes (`identity()` / `member()` helpers), which are unusable regions. Existing tests therefore never produce a repeated region.

## Target Outcome

| Mode / surface | What renders | Query | Count shown | Offset | Actions |
| --- | --- | --- | --- | --- | --- |
| Needs attention › Failed (default) | Existing failed list, maintenance zone, bulk results, age notice, topology notice | Existing `useDeadLetterOperations` 20-row page and 50-row eligibility page | Existing "Showing %1$d-%2$d of %3$d failed changes." from `operationsQuery.data.total` | `offset` (step 20), kept across view changes | Existing guarded row Retry/Discard and armed bulk Retry all / Discard eligible |
| Needs attention › Pending | Timeline section only | `useOutboxOperations({limit:10, offset:timelineOffset, status:'pending'})` | Existing timeline count line from that query's server `total` | `timelineOffset` reset to 0 on entry | None (non-failed rows already render none) |
| Needs attention › Conflict | Timeline section only | Same query with `status:'conflict'` | As above | As above | None in this panel |
| History | Timeline section with existing status filters (All default) | `useOutboxOperations({limit:10, offset:timelineOffset, status: timelineStatus==='all' ? undefined : timelineStatus})` | Existing timeline count line | `timelineOffset` reset to 0 on entry and on filter change | Existing guarded row Retry/Discard on rows whose status is `failed`. No maintenance zone. |

- The failed timeline is never mounted alongside the failed list, so no row or action is duplicated.
- No count is computed by filtering a page locally.
- A view change never sends a mutation. It disarms bulk confirmations and clears a pending row discard.
- A failed-list load error is confined to the Failed region, so History, Pending and Conflict stay reachable.
- Old failed rows stay listed until the server changes their status. Nothing is hidden by age.
- GPU toasts:
  - The warming toast says the run is waiting for the description service.
  - The degraded toast says no descriptions have been returned when `draftCount === 0`, with no review action.
  - With `draftCount > 0` it names the count and keeps "Review results".
  - DONE with `draftCount === 0` says exactly `Description run finished — no drafts returned.` with no review action. DONE with positive results keeps `doneToast(count)`; its existing "Review N drafts" action appears only when `reviewDraftsHref !== null`.
  - The producer offers `reviewDraftsHref` only for DONE, positive returned `draftCount` and a run id accepted by `serializeRunParam`. Ready/Back to run, genuine failures, cancellation/retry, dormant suppression and edge memory are preserved.
- `GpuControlCard` renders configuration copy for a received `endpoint_unconfigured` envelope. Stale or unknown telemetry never shows that copy.
- Identity cards stay exactly as grouped. A card whose observation shares an exact region with another loaded group shows one collapsed native `<details>`, "Same photo region is also listed in N other group(s)". Expanding it shows the limit statement, `Photo <media_id>` with the exact box, each matching observation's group reference and face record reference, and the loaded-pool accounting. Naming (`act-edit-person-name`) stays the primary action. The disclosure is the secondary in-place action `act-toggle-repeated-region-evidence`.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/templates/TASK_PLAN.template.md`. The repo-local `docs/workbay/rules/planning-review-guide.md` is absent in this checkout. Use the WorkBay payload copy `/home/gate/wb/agentic-protocol-monorepo/packages/workbay-system/workbay_system/payload/docs/workbay/rules/planning-review-guide.md`.
- Design: [UXREC-1 UX inventory](../../assessments/current/UXREC-1-ux-inventory.md) and the three map JSON files named in Intake.
- Reservations: `docs/tasks/v0.5.0/WBTRUST-5-control-placement-task-plan.md` and `docs/tasks/v0.5.0/WBTRUST-4-request-budget-task-plan.md` (Files and Surfaces to Change).
- Slice anchors: the files in [Files and Surfaces to Change](#files-and-surfaces-to-change) and their current tests.
- Canon v0.26.2, pinned at `/home/gate/heuristics-canon-v0.26.2` (project <https://github.com/darce/heuristics-canon>). Verify `meta/release-manifest.json` digests before citing rows.
- Handoff state: `UXREC-1` decisions (18920 contract, amended by 18935) and open findings via `review_findings(review={"operation":"list","status":"open","task_ref":"UXREC-1"})`.

## Contract and Boundary Impact

| Boundary | Owner | Current contract | Expected change | Compatibility needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET /acx/v1/recognition/outbox` (single `status`) | PHP `src/api/class-conflict-controller.php` route `/recognition/outbox` / frontend `conflictApi.ts:fetchOutboxOperations` | `OutboxListParams {limit, offset, status?}` → `OutboxListResponse {items,total,limit,offset}` | none. TIMELINE only changes which status the panel requests per mode. | no (unchanged) | `toHaveBeenLastCalledWith` assertions in `DeadLetterPanel.test.tsx` |
| Failed outbox list (`/recognition/outbox/failed`) | `useDeadLetterOperations` / `fetchFailedOutboxOperations` | 20-row page plus 50-row eligibility page | none | no | existing bulk discard tests, `dw2-deadletter-1.test.tsx` |
| Typed `unavailable` envelope | `class-gpu-control-controller.php:map_unavailable_reason` → `utils/http.ts` → `serviceUnavailable.ts:parseUnavailable` | `{reason, service, http_status, retry_after_seconds, checked_at}`; scene reasons pass through | none to shape. Frontend adds copy for the existing `endpoint_unconfigured` reason. | no | `serviceUnavailable.test.ts`, `GpuControlCard.test.tsx` with the PHP-pinned envelope |
| `GET /scene/gpu/status` | description service `routers/gpu.py:GpuStatusResponse` | no configuration field (`extra="forbid"`) | none. A configuration or capability field is **deferred** to a separate status-contract task. | n/a | grep-level check that no slice touches `routers/gpu.py` |
| Describe-run status | `describeApi.ts:DescribeRunResponse` | `completed`, `fallback_reason`, `terminal`, item `tier` | none to schema. GPU copy reads existing `draftCount`; the frontend review href requires DONE + positive completed count + valid run id. | no | `useGpuStateToasts.test.tsx`, `useActivityStatus.test.ts` |
| Media identities | `js/admin/api/recognition/types/identity.ts:DetectedIdentity` | fields listed in Current State | none. IDENTITY reads existing fields only. | no | `repeatedRegionEvidence.test.ts` |

There is no replicated, cached or cross-service write, and no schema change. TanStack Query caching is unchanged.

## Proposed Solution

### TIMELINE

Add panel-local view state with a file-local timeline section in `DeadLetterPanel.tsx`.

- The failed list stays the only source of failed-row recovery in Needs attention.
- The timeline section mounts only for Pending, Conflict and History. Its `useOutboxOperations` call therefore runs only when the section renders, and no failed timeline exists in the default view.
- The early loading and error returns become a region-scoped state inside the Failed region.
- **Trade-off**: this sacrifices an at-a-glance combined attention count. Producing one needs either several queries or a backend aggregate (deferred). History keeps existing recovery beside the inspected failed row, so the operator need not switch view and find it again ([NAV-19] **Keep related work adjacent**, *About Face, ch. 12*). The History title adds no capability restriction. Row actions appear once per view, preserve confirmation/capability/age and terminal guards (terminal failed rows still have Discard but no Retry), and introduce no new action or endpoint. Bulk controls stay `attention_failed` only.

### GPU_STATUS

- Change two vocabulary strings, add one plural function and one neutral zero-DONE literal. In the DEGRADED branch of `useGpuStateToasts`, choose copy and attach the "Review results" action only when `status.draftCount > 0`. In DONE, use neutral copy at zero and attach the existing review action only for positive count plus non-null href ([INT-01] **Affordance match**, *Designing Interfaces, 3rd ed.*).
- G1 owns only the `useActivityStatus.ts` review-href derivation and its focused tests. Add `reviewDraftsHrefForStatus` (new) and call it from the actions `useMemo`; reuse `serializeRunParam` and `toDescriptionHistoryRun`. Keep `describeDraftCount`, response shapes, cooldowns, budgets, scheduling, retry/cancel and layout unchanged. The reserved strip consumes the narrower href without a composition-file edit.
- Add `ENDPOINT_UNCONFIGURED` to `UNAVAILABLE_REASON` with configuration copy. `GpuControlCard` already renders the copy, so no product change is needed there.
- **Trade-off**: the warming toast no longer previews a possible CPU continuation. The UI cannot know whether a usable CPU adapter exists until the run returns `fallback_reason` or item tiers.

### IDENTITY

- Add a named shared group-key helper so grouping and evidence cannot drift.
- Add a pure projection over the raw `identities` array, before dedup.
- Add a small presentational native-`<details>` component, rendered by `IdentityClusterItem` and by `UngroupedResidueSection`.
- **Trade-off**: exact numeric equality misses near-identical regions, such as re-scans with a one-pixel offset. That is deliberate. A threshold would be similarity tuning, so a miss is acceptable and a false link is not.

### New symbol contracts

```ts
// js/admin/pages/workbench/DeadLetterPanel.tsx (file-local, all new)
const PANEL_VIEW = { ATTENTION: 'attention', HISTORY: 'history' } as const;
type PanelView = (typeof PANEL_VIEW)[keyof typeof PANEL_VIEW];
const ATTENTION_STATUSES = ['failed', 'pending', 'conflict'] as const;
type AttentionStatus = (typeof ATTENTION_STATUSES)[number];
// DeadLetterPanelState gains: panelView: PanelView (INITIAL 'attention'); attentionStatus: AttentionStatus (INITIAL 'failed').
// DeadLetterPanelAction gains: { type: 'setPanelView'; view: PanelView } | { type: 'setAttentionStatus'; status: AttentionStatus }.
// Both reducer cases also set: timelineOffset: 0, pendingDiscardId: null, bulkRetryArmed: false, bulkDiscardArmed: false.
interface DeadLetterTimelineSectionProps {
  heading: string;                      // 'Pending changes' | 'Conflicted changes' | 'Change history'
  status: Exclude<TimelineStatusFilter, 'all'> | undefined;  // value sent to useOutboxOperations
  statusLabel: string;                  // %4$s of the existing count line
  emptyCopy: string;
  offset: number;
  onOffsetChange: (offset: number) => void;
  filters?: { selected: TimelineStatusFilter; onChange: (status: TimelineStatusFilter) => void }; // History only
  displayNowMs: number;
  pendingDiscardId: number | null;
  mutationPending: boolean;
  onRetry: (operation: OutboxOperation) => void;
  onDiscard: (operation: OutboxOperation) => void;
}
const DeadLetterTimelineSection: (props: DeadLetterTimelineSectionProps) => React.JSX.Element; // calls useOutboxOperations({limit: TIMELINE_PAGE_SIZE, offset, status})
```

```ts
// js/admin/pages/workbench/gpuStatePresentation.ts
GPU_STATE_VOCABULARY.warmingToast            // value: 'GPU warming — this run is waiting for the description service'
GPU_STATE_VOCABULARY.degradedToast           // value: 'GPU unavailable — no descriptions returned yet'
GPU_STATE_VOCABULARY.degradedToastWithDrafts // (new) (draftCount: number) => string
//   sprintf(_n('GPU unavailable — %d draft ready to review', 'GPU unavailable — %d drafts ready to review', draftCount, 'alt-context'), draftCount)
GPU_STATE_VOCABULARY.doneToastWithoutDrafts  // (new) __('Description run finished — no drafts returned.', 'alt-context')
// Existing doneToast(count), reviewDrafts(count) and reviewDraftsAltText stay unchanged for positive results.

// js/admin/hooks/useActivityStatus.ts (new pure derivation; no status/action shape change)
export const reviewDraftsHrefForStatus: (
  status: Pick<ActivityStatus, 'kind' | 'draftCount' | 'runId'>,
) => string | null;
// Return null unless kind === ACTIVITY_KIND.DONE && draftCount > 0
// and serializeRunParam(runId) !== null. Otherwise return toDescriptionHistoryRun(validRunId).
// useActivityStatus's actions useMemo sets reviewDraftsHref: reviewDraftsHrefForStatus(status).
// js/admin/hooks/useGpuStateToasts.ts DONE branch:
// success(draftCount > 0 ? doneToast(draftCount) : doneToastWithoutDrafts,
//   { action: draftCount > 0 && reviewHref !== null ? existingReviewAction : undefined, durationMs: null });
// Retain the existing emit(GPU_TOAST_EDGE.DONE, ...) wrapper and pathFromAppHref navigation.

// js/admin/utils/serviceUnavailable.ts
UNAVAILABLE_REASON.ENDPOINT_UNCONFIGURED     // (new) 'endpoint_unconfigured'
UNAVAILABLE_REASON_COPY[ENDPOINT_UNCONFIGURED] = {
  why: __('its GPU endpoint is not configured', 'alt-context'),
  fix: __('An administrator must set the GPU endpoint for the Description service. Retry only checks again; it does not change the setting.', 'alt-context'),
};
```

```ts
// js/admin/pages/workbench/identity-clusters/utils.ts
export const identityGroupKey: (identity: Pick<DetectedIdentity, 'person_id' | 'cluster_id'>) => string; // (new)
//   person_id || null → `person:${person_id}`; else cluster_id != null → `cluster:${cluster_id}`; else UNGROUPED_GROUP_KEY.
//   groupIdentitiesByClusters must call it instead of its inline key expression (pure refactor).

// js/admin/pages/workbench/identity-clusters/repeatedRegionEvidence.ts (new module)
// The retained tuple. Copies of one identityId collapse only when every field below is equal (Rule 2).
export interface RepeatedRegionObservation {
  identityId: string;            // DetectedIdentity.identity_id, verbatim (the copy partition)
  mediaId: number;               // DetectedIdentity.media_id
  bbox: Readonly<BoundingBox>;   // new { x, y, width, height } with DetectedIdentity.bbox's numbers verbatim; no other bbox property
  groupKey: string;              // identityGroupKey(identity)
  personId: string | null;       // identity.person_id || null
  clusterId: string | null;      // identity.cluster_id ?? null (retained even when person_id wins groupKey)
}
export interface RepeatedRegion {
  regionKey: string;             // `${mediaId}|${x}|${y}|${width}|${height}` (String(n) per number)
  mediaId: number;
  bbox: Readonly<BoundingBox>;   // observations[0].bbox (sorted order, never first input arrival)
  groupKeys: readonly string[];  // ≥ 2 distinct, ascending code-unit order
  observations: readonly RepeatedRegionObservation[]; // sorted by groupKey, then identityId (code-unit order)
}
export interface RepeatedRegionPool {
  loadedObservationCount: number;     // distinct non-empty identity_id values in the input; an abstained id counts once
  eligibleObservationCount: number;   // distinct identity_ids whose copies all agree (Rule 2) and whose geometry is supported (Rule 3)
  abstainedIdentityIds: readonly string[]; // identity_ids whose loaded copies disagree in any retained field; ascending code-unit order
}
export interface RepeatedRegionEvidence {
  regions: readonly RepeatedRegion[]; // sorted by mediaId, x, y, width, height (numeric ascending)
  byGroupKey: ReadonlyMap<string, readonly RepeatedRegion[]>; // each group key → its regions, in region order
  pool: RepeatedRegionPool;
}
export interface RepeatedRegionEvidenceView {
  groupKey: string;
  regions: readonly RepeatedRegion[];             // non-empty
  pool: RepeatedRegionPool;
  groupLabels: ReadonlyMap<string, string | null>; // formatClusterLabel(...) per ClusterGroup.key
}
export const buildRepeatedRegionEvidence: (identities: readonly DetectedIdentity[]) => RepeatedRegionEvidence;
export const repeatedRegionViewForGroup: (
  evidence: RepeatedRegionEvidence,
  groupKey: string,
  groupLabels: ReadonlyMap<string, string | null>,
) => RepeatedRegionEvidenceView | undefined; // undefined when the group has no region

// js/admin/pages/workbench/identity-clusters/RepeatedRegionEvidenceDisclosure.tsx (new)
export const RepeatedRegionEvidenceDisclosure: (props: { view: RepeatedRegionEvidenceView }) => React.JSX.Element;
```

**`buildRepeatedRegionEvidence` rules** (the slice tests pin each one):

1. **Input stage.** Read the same raw `identities` array that `IdentityClusterList` passes to `groupIdentitiesByClusters`, before any dedup. Never mutate it.
2. **Accounting.** Ignore records whose `identity_id` is not a non-empty string after `trim()`, and do not count them. Partition the rest by verbatim `identity_id`. Compare copies of one id with a structural comparison of the complete retained tuple (a module-private helper, for example `sameRetainedTuple(left, right)` (new)). The tuple fields are `mediaId` (`media_id`), `groupKey` (`identityGroupKey(identity)`), `personId` (`identity.person_id || null`), `clusterId` (`identity.cluster_id ?? null`) and the geometry. The geometry is `null` when `bbox` is not a non-null object; otherwise it is its `x`, `y`, `width` and `height`.
   - Two copies agree only when every corresponding field satisfies `Object.is`, with both geometries `null` or all four numbers `Object.is`-equal. `Object.is` keeps the retained value independent of input order. `NaN` equals `NaN`, and Rule 3 still makes it ineligible. `0` and `-0` differ, so copies that differ only in signed zero abstain rather than retaining whichever arrived first.
   - Compare fields, never a joined string and never `groupKey` alone. Person precedence hides `cluster_id` from `groupKey`, and ids may contain any delimiter. Fields that the observation does not retain (`confidence`, labels, URLs, extra `bbox` properties) do not participate.
   - Equal copies collapse to one observation. Because every retained field is equal, the kept observation does not depend on which copy came first.
   - If any two copies of an id disagree in any field, add the id to `abstainedIdentityIds` once. Count it once in `loadedObservationCount`, never in `eligibleObservationCount`, and keep it out of every region. Never choose a winning copy (first, last, lowest, newest or sorted-first).
   - Abstention is local to this projection. `groupIdentitiesByClusters` still receives every record unchanged, and its existing grouping and mutation targets are not altered.
3. **Supported geometry.** `Number.isInteger(media_id) && media_id > 0`. `bbox` is a non-null object. `x`, `y`, `width` and `height` are numbers and `Number.isFinite`. `x >= 0`, `y >= 0`, `width > 1` and `height > 1`. Anything else is loaded but not eligible.
4. **Predicate.** Eligible observations fall in the same region only when `mediaId` and all four box numbers are strictly equal. Exact equality is an equivalence on coordinates, not a similarity chain. A region is emitted only when it holds at least two distinct group keys. There is no IoU, no similarity, no cross-photo matching and no merge.
5. **Ordering.** Regions, group keys and observations use the orderings in the type comments. A region's `bbox`, and so its region-line numbers, comes from `observations[0]` in that order, never from the first input arrival. Distinct ids with `0` and `-0` in the same position are strictly equal under Rule 4 and share one region; the sorted-first observation fixes which number is kept. Permuting the input must produce deep-equal output, with numbers compared by `Object.is`.
6. **Claim limit.** The output describes loaded records with matching coordinates. It carries no person-identity, completeness or corpus claim.

### Exact copy

| Slice | Key / location | String (gettext literal, domain `alt-context`) |
| --- | --- | --- |
| TIMELINE | section `aria-label` (replaces "Failed changes panel") | `Changes panel` |
| TIMELINE | view group `aria-label` / buttons | `Changes view` / `Needs attention`, `History` |
| TIMELINE | attention group `aria-label` / buttons | `Needs attention status` / `Failed`, `Pending`, `Conflict` |
| TIMELINE | region headings (h3) | `Failed changes` (existing), `Pending changes`, `Conflicted changes`, `Change history` (replaces h4 `Pending changes timeline`) |
| TIMELINE | timeline loading / error | `Loading changes…` / `Unable to load changes.` (replace the "pending changes" variants) |
| TIMELINE | timeline empty | `No pending changes.` / `No conflicted changes.` / `No changes found for this filter.` (History; replaces `No pending changes found for this filter.`) |
| TIMELINE | count, filters, pager | unchanged: `Showing %1$d-%2$d of %3$d changes (%4$s).`, `All` + `formatStatusLabel(status)`, `Previous timeline page` / `Next timeline page` |
| GPU | toasts | see New symbol contracts |
| GPU | Settings card (rendered by existing `GpuControlCard`) | `Description service is unavailable because its GPU endpoint is not configured.` + fix sentence |
| IDENTITY | `<summary>` | `_n('Same photo region is also listed in %d other group', 'Same photo region is also listed in %d other groups', n)`. `n` = distinct group keys in the view's regions, minus the current group. |
| IDENTITY | limit statement | `Matching uses exact box coordinates in the face records loaded for this photo. It does not show that these faces are the same person, and nothing is merged or moved.` |
| IDENTITY | region line | `Photo %1$d — box x %2$s, y %3$s, width %4$s, height %5$s` (`String(n)` per number) |
| IDENTITY | observation line | `%1$s — face record %2$s`. `%2$s` is the verbatim `identity_id` inside `<code>`. |
| IDENTITY | group display (`%1$s`) | `Person %s`; with a human label `%1$s (person %2$s)`; `Face group %s`; with a human label `%1$s (face group %2$s)`; ungrouped `Not yet grouped`. The id is verbatim inside `<code>`, and the label comes from `formatClusterLabel`. |
| IDENTITY | pool line | `Checked %1$d of %2$d loaded face records with usable box coordinates.` |
| IDENTITY | abstention line (only when > 0) | `_n('%d face record was skipped because its loaded copies disagree.', '%d face records were skipped because their loaded copies disagree.', n)` |

## Files and Surfaces to Change

| Surface | File | Symbol / Function | Change |
| --- | --- | --- | --- |
| frontend | `js/admin/pages/workbench/DeadLetterPanel.tsx` | `PANEL_VIEW`, `ATTENTION_STATUSES`, `PanelView`, `AttentionStatus` (new) | View and attention-status constants (`as const`) |
| frontend | same | `DeadLetterPanelState`, `DeadLetterPanelAction`, `INITIAL_STATE`, `deadLetterPanelReducer` | Add `panelView` / `attentionStatus` and two actions. The reducer resets `timelineOffset`, `pendingDiscardId` and both armed flags on either action. `INITIAL_STATE.timelineStatus` stays `'all'` (History default). |
| frontend | same | `handlePanelViewChange`, `handleAttentionStatusChange` (new); `handleTimelineStatusChange` (reuse) | Dispatch the new actions. History filters keep the existing handler. |
| frontend | same | `DeadLetterTimelineSection` (new, file-local) | Move the existing timeline JSX (status line, rows, pager) here. It calls `useOutboxOperations` and wraps loading, error and count in one `aria-live="polite"` container (`data-testid="acx-dead-letter-timeline-status"`). History filter buttons switch from `disabled={selected}` to `aria-pressed={selected}`, so they match the new groups and stay focusable. Activating the already-selected filter does nothing. |
| frontend | same | `DeadLetterPanel` | Remove the top-level `timelineQuery`. Render native `<button type="button" aria-pressed>` view and status groups (`role="group"` + `aria-label`). Mount exactly one region per mode (Target Outcome table). Move the loading and error early returns into the Failed region, keeping `aria-busy="true"` on the section while Needs attention › Failed is shown and `operationsQuery.isLoading`. Rename the section `aria-label` to `Changes panel`. |
| frontend | same | `DeadLetterOperationRow` | **No change**. `showFailedRecovery` keeps current behaviour. |
| tests | `js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx` | `describe('UXREC-1 needs attention')` (new); `getTimelinePanel` helper; listed existing tests | New RED tests; adapt existing timeline tests (see Slice T1) |
| frontend | `js/admin/pages/workbench/gpuStatePresentation.ts` | `GPU_STATE_VOCABULARY.warmingToast`, `.degradedToast`, `.degradedToastWithDrafts`, `.doneToastWithoutDrafts` (last two new) | Copy per contracts; existing positive `doneToast` and review labels unchanged |
| frontend | `js/admin/hooks/useGpuStateToasts.ts` | `useGpuStateToasts` (DEGRADED and DONE branches only) | DEGRADED chooses count-bound copy/action. DONE uses neutral zero copy, and the review action requires `draftCount > 0 && reviewHref !== null`. Keep `durationMs: null`, edge memory and other branches. |
| frontend | `js/admin/hooks/useActivityStatus.ts` | `reviewDraftsHrefForStatus` (new); `useActivityStatus` actions `useMemo` | Bounded grant: add the pure review-href derivation, import existing `serializeRunParam`, and replace only the `reviewDraftsHref` expression. No cooldown, budget, lifecycle, cancel/retry or layout change. |
| frontend | `js/admin/utils/serviceUnavailable.ts` | `UNAVAILABLE_REASON`, `UNAVAILABLE_REASON_COPY` | Add `ENDPOINT_UNCONFIGURED` and its copy |
| tests | `js/admin/hooks/__tests__/useGpuStateToasts.test.tsx` | `describe('UXREC-1 GPU toast evidence')` (new); `it.each(...)('always toasts %s to degraded with Review results even while mounted')` | New RED tests. The existing degraded case gets `draftCount: 1` and expects `degradedToastWithDrafts(1)`. |
| tests | `js/admin/hooks/__tests__/useActivityStatus.test.ts` | `describe('UXREC-1 review href evidence')` (new, nested in existing hook setup) | Real completed-run hook fixtures plus pure derivation boundary cases, as named in G1 |
| tests | `js/admin/utils/__tests__/serviceUnavailable.test.ts` | `CLOSED_REASON_COPY`; `it('UXREC-1 endpoint_unconfigured maps to configuration copy')` (new) | Add the closed-set row (TypeScript `Record` requires it) and the RED test |
| tests | `js/admin/pages/settings/__tests__/GpuControlCard.test.tsx` | `it('UXREC-1 endpoint_unconfigured envelope shows configuration copy')`, `it('UXREC-1 stale snapshot never shows configuration copy')` (new) | Consumer test with the PHP-pinned envelope via the existing `unavailableError` helper, plus a stale-telemetry guard |
| frontend | `js/admin/pages/workbench/identity-clusters/utils.ts` | `identityGroupKey` (new); `groupIdentitiesByClusters` | Extract the key; call it from grouping |
| frontend | `js/admin/pages/workbench/identity-clusters/repeatedRegionEvidence.ts` (new) | `buildRepeatedRegionEvidence`, `repeatedRegionViewForGroup` and the types above | Pure projection |
| frontend | `js/admin/pages/workbench/identity-clusters/RepeatedRegionEvidenceDisclosure.tsx` (new) | `RepeatedRegionEvidenceDisclosure` | Native `<details className="acx-identity-cluster__repeated-region" data-testid="acx-repeated-region-evidence">`, closed by default. Renders `<summary>`, limit, regions (`<ul>`), observations (`<ul>`), pool and abstention lines with the exact copy. Renders no image, button or link. |
| frontend | `js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx` | `IdentityClusterItemProps.repeatedRegionEvidence?: RepeatedRegionEvidenceView` (new); `IdentityClusterItem` | In display mode, render the disclosure last inside `acx-identity-cluster__info`, after the inline suggestion prompt and outside the `clusteringPending` guard. Never inside the label button. |
| frontend | `js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx` | `IdentityClusterList`, `UngroupedResidueSection` (prop `repeatedRegionEvidence?: RepeatedRegionEvidenceView`) | `useMemo(() => buildRepeatedRegionEvidence(identities), [identities])`. Build `groupLabels` from `clusters`. Pass `repeatedRegionViewForGroup(evidence, cluster.key, groupLabels)` to each item and the `ungrouped` view to the residue section, which renders the disclosure under its heading. |
| styles | `js/admin/styles/components/_identity-cluster-list.scss` | `.acx-identity-cluster__repeated-region` (new rules) | `flex-basis: 100%; min-width: 0`, token spacing, and `code { overflow-wrap: anywhere; }` so references wrap at 320 px |
| tests | `js/admin/pages/workbench/identity-clusters/__tests__/repeatedRegionEvidence.test.ts` (new) | `describe('UXREC-1 buildRepeatedRegionEvidence')` | Pure projection fixtures |
| tests | `.../__tests__/utils.test.ts` | `describe('UXREC-1 identityGroupKey')` (new) | Key parity |
| tests | `.../__tests__/IdentityClusterItem.test.tsx` | `describe('UXREC-1 repeated region disclosure')` (new) | Render and keyboard |
| tests | `.../__tests__/IdentityClusterList.test.tsx` | `describe('UXREC-1 repeated region wiring')` (new) | Wiring and unchanged targets |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/hooks/useOutboxOperations.ts`, `useDeadLetterOperations.ts`, `api/recognition/conflictApi.ts` | Reused unchanged; single-status contract |
| `js/admin/pages/WorkbenchPage.tsx` | WBTRUST-5-reserved. Its overlay h2 "Failed Sync Queue" remains. A later WorkbenchPage owner may retitle it; this plan does not. |
| `js/admin/App.tsx` | Mounts `useGpuStateToasts`; unchanged |
| `js/admin/hooks/useActivityStatus.ts` | G1's exact write grant is the review-href derivation/import and actions expression above; `describeDraftCount`, `resolveActivityStatus`, `ACTIVITY_KIND`, `ACTIVITY_REASON` and every other path remain read-only |
| `js/admin/navigation/appLinks.ts` | `serializeRunParam`, `toDescriptionHistoryRun`; read-only reuse. No new route or codec. |
| `js/admin/pages/workbench/ActivityStatusStrip.tsx` | WBTRUST-5-reserved consumer of `readyNotice`, `degradedNotice` and `stoppedNotice`, none of which change. `degradedNotice` ignores its count; this is recorded as a follow-up for the strip owner. |
| `js/admin/pages/settings/GpuControlCard.tsx`, `js/admin/pages/RetentionPage.tsx` | Consumers of `unavailableReasonCopy`; no production change |
| `js/admin/api/describeApi.ts` | `fallback_reason`, `terminal`, `DESCRIBE_RESULT_TIER`, `encodeURIComponent` run paths; read-only |
| `apps/prototype-description-service/scene/application/describe_run_worker.py`, `apps/prototype-description-service/scene/interface_adapters/http/routers/gpu.py` | Producer evidence; read-only |
| `src/api/class-gpu-control-controller.php`, `tests/Unit/GpuControlControllerTest.php` | Envelope passthrough evidence; read-only |
| `js/admin/pages/workbench/identity-clusters/ClusterPreview.tsx`, `ClusterActions.tsx`, `ClusterReviewPanel.tsx`, `pages/workbench/ClusterPanelContext.tsx` | Unchanged. The thumbnail is context only and is never the matching observation. |
| `js/admin/pages/workbench/MediaSelectionTableBody.tsx` | WBTRUST-5 area; passes `item.identities`; unchanged |
| `js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts`, `js/admin/__tests__/banned-vocabulary.test.tsx` | Read-only guards run as regressions. The page-sweep fixture renders `identities: []`, so it does not render the disclosure. |

## Verification Strategy

All selectors below are **future product-author commands**. This planning lane ran none of them. Run from `apps/prototype-wp-alt-context`.

- Deterministic tests, per slice. The RED selectors are in Slice Delivery. Full-file GREEN commands:
  - TIMELINE: `npm test -- js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx js/admin/pages/workbench/__tests__/dw2-deadletter-1.test.tsx`
  - GPU: `npm test -- js/admin/hooks/__tests__/useGpuStateToasts.test.tsx js/admin/hooks/__tests__/useActivityStatus.test.ts js/admin/hooks/__tests__/useActivityStatus.recognitionIdle.test.tsx js/admin/utils/__tests__/serviceUnavailable.test.ts js/admin/pages/settings/__tests__/GpuControlCard.test.tsx js/admin/pages/settings/__tests__/useGpuControl.test.tsx js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts js/admin/pages/workbench/__tests__/ActivityStatusStrip.test.tsx js/admin/pages/__tests__/RetentionPage.test.tsx`
  - IDENTITY: `npm test -- js/admin/pages/workbench/identity-clusters/__tests__/repeatedRegionEvidence.test.ts js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.provenance.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.twinChip.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.twinChip.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts js/admin/__tests__/banned-vocabulary.test.tsx`
  - Every slice: `npm run typecheck` and `npm run lint`. Lint findings follow the repo lint-deferral rule; they do not block.
- Ownership check per slice: `git diff --name-only <slice-base>..HEAD` lists only that slice's owned paths. It never lists `docs/ux-maps/**`, `routers/gpu.py`, `describeApi.ts`, `gpuApi.ts`, `class-gpu-control-controller.php` or any WBTRUST-5-reserved file.
- G1 symbol check: `git diff <slice-base>..HEAD -- apps/prototype-wp-alt-context/js/admin/hooks/useActivityStatus.ts` contains only the existing codec import, new `reviewDraftsHrefForStatus` and the `reviewDraftsHref` expression. The other hook internals remain read-only. `ActivityStatusStrip.test.tsx` and `useActivityStatus.recognitionIdle.test.tsx` are regression-only; the strip source is reserved and untouched.
- Contract and fixture checks: the TIMELINE `toHaveBeenLastCalledWith` status params, the GPU PHP-pinned envelope fixture, and the IDENTITY permutation and no-mutation tests.
- Map join (run by the single map writer, not by slice authors): `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/gate/wb/agentic-protocol-monorepo/packages/mcp-workbay-canvas/src python3 docs/ux-maps/render_ux_maps.py --check workbench-operator-loop describe-gpu-tier workbench-identity-chips` and `npm test -- js/admin/__tests__/uxmap-one-primary.test.ts js/admin/__tests__/uxmap-parity.test.ts js/admin/__tests__/uxmap-render-parity.test.ts`.
- Manual verification (later, in a browser, not a slice gate):
  - Keyboard walk of the view and status groups and the disclosure (Tab, Enter/Space, visible focus, no trap).
  - Reflow at 320 px and 200 % zoom with long `identity_id` values.
  - Screen-reader check that the timeline count is announced once per view change.
- Runtime acceptance (needs a returned runtime grant plus exact deployed build and tenant; **none is present**, and unit tests cannot substitute):
  - Inspect the four July records' status and reconciliation eligibility without blanket deletion.
  - Observe a real describe run reaching each of the three worker outcomes. Confirm the toasts match the returned `draftCount`, `fallback_reason` and terminal.
  - Confirm the deployed GPU status path, and whether `endpoint_unconfigured` ever reaches the Settings card.
  - Confirm a repeated region on real loaded rows, using only operator-supplied IDs.
  - Retention upstream recovery stays a separate runtime item.

## Slice Delivery

### Slice T1: TIMELINE — Needs attention default and separate History

**Goal**: one list per mode. A failed row and its actions never appear twice, and audit history sits behind History.

Files/functions:

- `js/admin/pages/workbench/DeadLetterPanel.tsx:PANEL_VIEW`, `ATTENTION_STATUSES` (new); `DeadLetterPanelState`, `DeadLetterPanelAction`, `INITIAL_STATE`, `deadLetterPanelReducer`, `handlePanelViewChange` (new), `handleAttentionStatusChange` (new), `DeadLetterTimelineSection` (new), `DeadLetterPanel`.
- `js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx`.

Fixtures, added to the test file with the existing `buildOperation`. All IDs are synthetic; these are not the live July records.

- `OLD_FAILED`: id 701, `status: 'failed'`, `operation_type: 'cluster_label_updated'`, `entity_key: 'cluster-701'`, `created_at` and `first_failed_at: '2026-07-14T09:00:00Z'`, attempts 5, `last_error_code: 'dispatch_failed'`.
- `PENDING_OP`: id 702, `status: 'pending'`, null error fields.
- `CONFLICT_OP`: id 703, `status: 'conflict'`.
- `ACKNOWLEDGED_OP`: id 704, with `acknowledged_at`.
- `DISCARDED_OP`: id 705, `status: 'discarded'`, `last_error_code: 'auto_retry_exhausted'`.

RED tests in `describe('UXREC-1 needs attention')`, each with its predicted failure:

1. `defaults to Needs attention › Failed with the failed list only`
   - Expect `Needs attention` and `Failed` to have `aria-pressed="true"`, `OLD_FAILED`'s entity text exactly once, `mockedUseOutboxOperations` not called, no `Change history` heading, and `Retry all failed (1)` present.
   - Predicted RED: `Unable to find an accessible element with the role "button" and name "Needs attention"`.
2. `Pending and Conflict render only the server-filtered timeline`
   - After clicking `Pending`, expect `toHaveBeenLastCalledWith({limit:10, offset:0, status:'pending'})`, the `Pending changes` heading, no `Showing 1-1 of 1 failed changes.`, and no maintenance-zone buttons. Repeat for `Conflict`.
3. `History renders the all-status timeline with guarded failed-row recovery and no bulk controls`
   - Expect `{limit:10, offset:0, status:undefined}`, acknowledged and discarded rows visible, no `Retry all failed` or `Discard … eligible` button, and no failed list.
   - With the History filter `failed`, `OLD_FAILED` renders once with its guarded row Retry/Discard; each calls the same existing mutation with that operation id, and Discard still needs confirmation. A terminal failed fixture keeps Discard but no Retry; acknowledged/discarded/pending/conflict rows have neither. Preserve capability/pending and age/eligibility guards. The title supplies no additional capability contract.
4. `view changes reset the timeline offset and disarm confirmations`
   - History Next page sends `offset:10`. Switching to Needs attention › Pending sends `offset:0`.
   - Arm a row discard in Failed (`Confirm discard`), switch to History and back, and expect the button to read `Discard`. Arm `Retry all`, switch view, and expect it to be disarmed.
5. `failed-list load error keeps History reachable`
   - With `operationsQuery` erroring, the alert "Unable to load failed changes." shows in the Failed region, `History` is enabled, and clicking it renders `Change history`.
6. `old failed rows stay in Needs attention until the server status changes`
   - `OLD_FAILED` stays listed. No age-only filter applies. Bulk discard remains the existing armed, eligibility-based action.
7. `view changes never send a mutation`
   - After toggling every view and status, the retry, discard and bulk retry `mutateAsync` mocks have zero calls.
8. `History filters expose pressed state and stay focusable`
   - In History, `All` has `aria-pressed="true"` and is not disabled. After activating `failed`, that button is pressed and `All` is not.
   - Activating the already-pressed `failed` again leaves the request offset unchanged.

Intentional updates to existing tests (setup changes; assertions are preserved unless stated):

- `getTimelinePanel`: look up the heading `Change history`.
- `renders failed operations with metadata and payload summary`: `getAllByText('Cluster label update')`, `getAllByText('Entity: cluster-1 (cluster)')` and `getAllByText(/Last attempted:/)` change from length 2 to 1, because the default view no longer mounts the timeline.
- Click `History` first in: `renders outbox timeline entries with status and acknowledgement metadata` (heading text becomes `Change history`), `updates the timeline filter and pagination controls`, `keeps non-failed timeline rows without error, attempts, or recovery actions`, `shows error code, attempts, and Retry/Discard on failed timeline rows`, `retries a failed timeline row through the shared retry mutation`, `discards a failed timeline row through the shared discard mutation`, `hides Retry on terminal failed timeline rows and keeps Discard` and `shows Will not retry for discarded timeline rows`.
- `shows age per failed row and timeline entry`: assert `Age: 8 days` once in the default view and once after `History`.
- `mounts the empty failed-changes status before announcing loading on the same node` and any other region query: use `{ name: 'Changes panel' }`.

Proof:

- Each RED selector fails as predicted on unchanged source: `npm test -- js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx -t 'UXREC-1 needs attention'`.
- The same selector passes after the change. The full-file TIMELINE command, `npm run typecheck` and the ownership check pass.

**Source-complete when** all of the above pass, with History row recovery once per failed row and bulk controls only in `attention_failed`. **Not proven here**: the four live July records' state or clearance, or the deployed panel.

### Slice G1: GPU_STATUS — evidence-bound toasts and `endpoint_unconfigured` copy

**Goal**: no visible GPU copy claims CPU drafts or results that the server has not returned, and a received configuration error explains itself.

Files/functions:

- `js/admin/pages/workbench/gpuStatePresentation.ts:GPU_STATE_VOCABULARY` (`warmingToast`, `degradedToast`, `degradedToastWithDrafts`, `doneToastWithoutDrafts` (last two new)).
- `js/admin/hooks/useGpuStateToasts.ts:useGpuStateToasts`.
- `js/admin/hooks/useActivityStatus.ts:reviewDraftsHrefForStatus` (new) and only the actions `useMemo` review-href expression/import; other internals read-only.
- `js/admin/utils/serviceUnavailable.ts:UNAVAILABLE_REASON`, `UNAVAILABLE_REASON_COPY`.
- Tests: `js/admin/hooks/__tests__/{useGpuStateToasts.test.tsx,useActivityStatus.test.ts}`, `serviceUnavailable.test.ts`, `GpuControlCard.test.tsx`. These tests and symbols are proposed, not implemented by this plan.

RED tests (assert literal strings, so RED is a clean assertion failure):

1. In `describe('UXREC-1 GPU toast evidence')`:
   - `warming toast makes no CPU draft claim`: the kind change to WARMING gives info text `GPU warming — this run is waiting for the description service`, which does not match `/CPU/`. Predicted RED: `expected 'GPU warming — CPU drafts first' to be …`.
   - `degraded toast without returned drafts offers no review`: READY → DEGRADED with `draftCount: 0` gives error text `GPU unavailable — no descriptions returned yet`, `options.action` undefined and `durationMs` null. Predicted RED: text mismatch, with the action present.
   - `degraded toast with returned drafts names the count and keeps Review results`: `draftCount: 2` gives `GPU unavailable — 2 drafts ready to review` and action label `Review results`.
   - `DONE zero returned drafts has neutral completion copy and no review action`: use existing `observeSequence`, `hookResult`, `runStatus` and `idleActions` (real `UseActivityStatusResult` shape). DESCRIBING → DONE with `draftCount: 0`; parameterize `reviewDraftsHref: null` and a stale non-null href. Expect exactly one success toast, literal `Description run finished — no drafts returned.`, `options.action` undefined, `durationMs: null`, no navigation and no error/info toast. Predicted RED: `expected '0 drafts ready to review' to be 'Description run finished — no drafts returned.'`.
   - `DONE positive drafts with null href has no review action`: same sequence with `draftCount: 2`, `reviewDraftsHref: null`. Expect existing `doneToast(2)` and no action, unchanged location `/people`. Predicted RED: `expected { label: 'Review 2 drafts', ... } to be undefined`.
   - `DONE positive drafts with href keeps review navigation`: same sequence with `draftCount: 2`, `reviewDraftsHref: '#/workbench?hasDraft=1&run=run-1'`. Expect existing `doneToast(2)`, `reviewDrafts(2)`, alt text, `durationMs: null`; invoke `onClick` inside `act` and expect `/workbench?hasDraft=1&run=run-1`. This guard passes before and after; also retain the existing four-draft review test.
   - Guards that pass before and after: `never toasts an unknown GPU state into degraded`, `does not toast a GPU status poll failure with no active run`, existing genuine failed/cancel/retry and ready/Back to run cases, first-observation and progress-mounted suppression, repeated-poll suppression and edge memory per run/new run id. Repeated DONE polls or a later href alone must not emit a second DONE edge.
2. `serviceUnavailable.test.ts: UXREC-1 endpoint_unconfigured maps to configuration copy`: `unavailableReasonCopy('endpoint_unconfigured')` equals the contract copy, and `why` does not match `/unexpected error/`. Predicted RED: `{ why: 'an unexpected error occurred (endpoint_unconfigured)', … }`.
3. In `GpuControlCard.test.tsx`:
   - `UXREC-1 endpoint_unconfigured envelope shows configuration copy`: `mockControl(statusResponse(), { data: undefined, isError: true, error: unavailableError('2026-09-18T14:03:22Z', { reason: 'endpoint_unconfigured', http_status: 503, retry_after_seconds: null }), refetch })`. Expect the text `Description service is unavailable because its GPU endpoint is not configured.`, the fix sentence, no `/unexpected error/`, and the existing `Retry` button enabled.
   - Guard: `UXREC-1 stale snapshot never shows configuration copy`: `mockControl({ ...statusResponse({ state: 'ready' }), snapshot_age_seconds: 240, snapshot_fresh: false })`, the same shape as the existing test `hides Start and Stop when the snapshot is stale and keeps Refresh`, renders no `/not configured/`.
4. In `useActivityStatus.test.ts`, add nested `describe('UXREC-1 review href evidence')` under the existing tenant/store/query-client setup:
   - `DONE zero completed items offers no review href`: reuse `describeRun`, `fetchBulkDescribeRunMock`, `buildTestQueryClient`, `createQueryWrapper`, `renderHook` and `waitFor`. Poll `useActivityStatus({ describeRunId: 'run-1' })` with a real-shaped completed run (`status: COMPLETED`, `phase: COMPLETE`, `completed: 0`, `skipped: 4`, `total: 4`, `eta_seconds: null`). Wait for DONE, assert `draftCount === 0` and `reviewDraftsHref === null`. Predicted RED: `expected '#/workbench?hasDraft=1&run=run-1' to be null`.
   - `DONE positive completed items keeps the canonical review href`: use the same hook fixture with `completed: 2`, `skipped: 2`; parameterize COMPLETED and COMPLETED_WITH_ERRORS (the latter with `failed: 2`, `skipped: 0`). Assert DONE, count 2 and equality to existing `toDescriptionHistoryRun('run-1')`. No submit/cancel mutation is sent. This guard passes before and after.
   - `review href rejects missing ids and non-DONE states`: call new `reviewDraftsHrefForStatus` with typed `ActivityStatus` fixtures, DONE/count 2 and `runId: null`, `''` or whitespace → null; DONE/count 0 with valid id → null; each non-DONE kind with positive count/id → null. A trimmed non-empty id returns the existing builder's href. Predict initial RED `reviewDraftsHrefForStatus is not a function`; keep the zero-count hook test as the behavioral reproduction, rather than accepting this missing-symbol failure as the only proof.

Intentional updates to existing tests:

- `always toasts %s to degraded with Review results even while mounted`: add `draftCount: 1` to the DEGRADED status and expect `GPU_STATE_VOCABULARY.degradedToastWithDrafts(1)`.
- `CLOSED_REASON_COPY`: add the `ENDPOINT_UNCONFIGURED` row. The distinct-`why` test then covers it.

Proof:

- RED selectors fail as predicted: `npm test -- js/admin/hooks/__tests__/useGpuStateToasts.test.tsx -t 'UXREC-1 GPU toast evidence'`, `npm test -- js/admin/hooks/__tests__/useActivityStatus.test.ts -t 'UXREC-1 review href evidence'`, `npm test -- js/admin/utils/__tests__/serviceUnavailable.test.ts -t 'UXREC-1 endpoint_unconfigured'` and `npm test -- js/admin/pages/settings/__tests__/GpuControlCard.test.tsx -t 'UXREC-1'`. Positive-result and suppression guards must pass before and after; only the named defect assertions are expected RED.
- After the change they pass, and so do the full GPU command, typecheck and the ownership check. The check confirms no change to `routers/gpu.py`, `describeApi.ts`, `gpuApi.ts`, PHP or `ActivityStatusStrip.tsx`.

**Source-complete when** all of the above pass, including DONE zero/positive-null/positive-href hook cases, the producer's completed-count/id guard and the bounded symbol ownership diff. **Not proven here**: live warm-up, CPU continuation availability, result delivery, or whether any deployed path emits `endpoint_unconfigured` to the card.

### Slice I1: IDENTITY — repeated-region evidence disclosure

**Goal**: show, in place and as text, that loaded face records in different groups share an exact photo region. Grouping, primary naming and removal targets are unchanged.

Files/functions:

- `identity-clusters/utils.ts:identityGroupKey` (new), `groupIdentitiesByClusters`.
- `identity-clusters/repeatedRegionEvidence.ts` (new): `buildRepeatedRegionEvidence`, `repeatedRegionViewForGroup`.
- `identity-clusters/RepeatedRegionEvidenceDisclosure.tsx` (new).
- `IdentityClusterItem.tsx:IdentityClusterItem`.
- `IdentityClusterList.tsx:IdentityClusterList`, `UngroupedResidueSection`.
- `styles/components/_identity-cluster-list.scss`.
- The four test files.

Fixtures (pure; synthetic IDs; `R = {x: 12, y: 20, width: 40, height: 48}`):

- `P1A`: `identity_id 'face-a'`, `person_id '1'`, `cluster_id 'c-1'`, media 10, R.
- `P1A2`: `{...P1A, cluster_id: 'c-2'}`. It is the same `face-a` in the same `person:1` group key, media and box, so the old `media_id|groupKey|box` signature collided while `clusterId` differs.
- `P2B`: `'face-b'`, `person_id '2'`, media 10, R.
- `C3C`: `'face-c'`, `person_id null`, `cluster_id 'c-3'`, media 10, R.
- `UND`: `'face-u'`, `person_id null`, `cluster_id null`, media 10, R.

RED tests in `repeatedRegionEvidence.test.ts` (`describe('UXREC-1 buildRepeatedRegionEvidence')`). Predicted RED: `Failed to resolve import "../repeatedRegionEvidence"`.

- **Positive**: `[P1A, P2B]` gives one region with `groupKeys ['person:1','person:2']` and observation ids `['face-a','face-b']`.
- **Three groups**: `[P1A, P2B, C3C]` gives one region whose group keys are ascending (`cluster:c-3`, `person:1`, `person:2`).
- **Ungrouped participates**: `[C3C, UND]` gives `['cluster:c-3', 'ungrouped']`.
- **Negatives** (zero regions; `eligibleObservationCount` as stated):
  - same group, two ids, R;
  - media 10 vs 11 with R;
  - R vs `{x:13,…}` (IoU above 0.5, still no region);
  - width 1, height 1, `x: -1`, `NaN`, `Infinity`, missing `bbox`, `media_id` 0, −3 or 1.5, and empty `identity_id` (excluded from `loadedObservationCount`).
- **No chaining**: A and B share R, and C overlaps R without being equal. Only {A, B} form a region.
- **Duplicates (identical copy positive)**: `[P1A, {...P1A}, P2B]` counts `face-a` once. It still gives one region with observation ids `['face-a','face-b']`, and the pool is `{loadedObservationCount: 2, eligibleObservationCount: 2, abstainedIdentityIds: []}`. A copy that differs only in a non-retained field (`confidence`, `cluster_label`, `thumb_url`, or an extra `bbox` property) also collapses. The retained observation's keys are exactly `identityId`, `mediaId`, `bbox`, `groupKey`, `personId` and `clusterId`, and its `bbox` keys are exactly `x`, `y`, `width` and `height`.
- **Existing person-ref conflict**: `face-a` with two different boxes, or with two different `person_id` values, goes to `abstainedIdentityIds` and joins no region.
- **Conflicting cluster reference, all permutations**: each of the 6 permutations of `[P1A, P1A2, P2B]` gives `pool` `toEqual` `{loadedObservationCount: 2, eligibleObservationCount: 1, abstainedIdentityIds: ['face-a']}`, `regions` `[]` and `byGroupKey.size === 0`. The 6 outputs are `toEqual` each other. No observation for `face-a` with `clusterId` `'c-1'` or `'c-2'` appears anywhere, so no copy wins.
  - For each permutation, the `groupIdentitiesByClusters(permutation)` value and each group's `getEditableClusterId(group)` and `members[0].identity_id` are identical before and after `buildRepeatedRegionEvidence(permutation)`.
  - The existing grouping of this pair is input-order-dependent: the `person:1` `clusterId` follows the first copy and `identityClusterIds['face-a']` the last. The slice does not change that and does not assert it is permutation-invariant.
- **Conflict beside a region**: every permutation of `[P1A, P1A2, P2B, C3C]` gives one region with `groupKeys ['cluster:c-3','person:2']` and observation ids `['face-c','face-b']`. The pool is `{loadedObservationCount: 3, eligibleObservationCount: 2, abstainedIdentityIds: ['face-a']}`.
- **Every retained field participates**: pair `P2B` with two `face-a` copies that differ in exactly one retained field. Each pair abstains `face-a` (`abstainedIdentityIds ['face-a']`, `eligibleObservationCount 1`, no region) in both input orders:
  - `media_id` 10 vs 11;
  - `person_id` `'1'` vs `'3'` (`personId` and `groupKey`);
  - `cluster_id` `'c-1'` vs `'c-2'` under `person_id '1'` (`clusterId` only; `groupKey` stays `person:1`);
  - `person_id null` with `cluster_id` `'c-1'` vs `'c-9'` (`clusterId` and `groupKey`);
  - each of `x`, `y`, `width` and `height` changed by 1;
  - `bbox: null` vs R;
  - `person_id` `'1'` vs the runtime number `1` (cast through `unknown`). `groupKey` stays `person:1`, but `Object.is` separates the retained `personId`, which would otherwise depend on input order.
  - For string ids, `personId` and `groupKey` determine each other, and `groupKey` is a function of `personId` and `clusterId`. The number case is therefore the only input that isolates `personId`, and no input isolates `groupKey`. `groupKey` is still compared explicitly.
- **Normalized references agree**: `person_id` `''`, `null` and absent are the same `personId` (`null`), and `cluster_id` `null` and absent are the same `clusterId`. Such copies collapse.
- **No joined string**: `face-d` copies `{person_id: '1|1', cluster_id: 'c-1'}` and `{person_id: '1', cluster_id: '1|1|c-1'}`, both media 10 and R, abstain in both orders. Their `groupKey` values differ (`person:1|1` vs `person:1`), but a `|`-joined string of all retained fields would be identical for both.
- **Signed zero** (`Z = {x: 0, y: 20, width: 40, height: 48}`; assert numbers with `toBe`, which uses `Object.is`):
  - `face-a` copies with `x: 0` and `x: -0` abstain in both orders.
  - Two identical `x: -0` copies collapse, and the kept `bbox.x` is `-0`.
  - Distinct ids `{...P1A, bbox: {...Z, x: -0}}` and `{...P2B, bbox: Z}` form one region (Rule 4 is unchanged). In both orders `regionKey` is `'10|0|20|40|48'` and `region.bbox.x` is `-0`, because `face-a` under `person:1` is `observations[0]`. With the signs swapped, `region.bbox.x` is `0` in both orders.
- **Partial pool**: the counts equal the distinct ids passed in. No field implies a total beyond the input.
- **Determinism**: every permutation of `[P1A, P2B, C3C]` gives `toEqual` output. So does every permutation of the conflict fixtures above.
- **Purity**: a deep-frozen input does not throw. `groupIdentitiesByClusters(input)` deep-equals its value from before the call, including `members`, `identityClusterIds` and `clusterId` for every group. `getEditableClusterId(group)` and `group.members[0].identity_id` (naming and removal targets) are unchanged.

Other RED tests:

- `utils.test.ts`, `describe('UXREC-1 identityGroupKey')`:
  - person precedence;
  - cluster fallback;
  - `ungrouped`;
  - `person_id: ''` falls back like null;
  - for every member, `groupIdentitiesByClusters(...).key === identityGroupKey(member)`.
  - Predicted RED: `identityGroupKey is not a function` (import undefined).
- `IdentityClusterItem.test.tsx`, `describe('UXREC-1 repeated region disclosure')`:
  - With a view for `person:1`, the `<details>` is present and not `open`. The summary reads `Same photo region is also listed in 1 other group`.
  - After `fireEvent.click(summary)`, `details.open` is true and the region line `Photo 10 — box x 12, y 20, width 40, height 48` shows.
  - The observation list items (`within(details).getAllByRole('listitem')`) have `toHaveTextContent` `Person 1 — face record face-a` and `Person 2 — face record face-b`. Use `toHaveTextContent` because the ids sit in `<code>` children, which `getByText` does not join. The limit statement and `Checked 2 of 2 loaded face records with usable box coordinates.` are also present.
  - With `groupLabels` mapping `person:1` to `bob`, the first item reads `bob (person 1) — face record face-a`.
  - The label button keeps its accessible name and comes before the summary in DOM order. The disclosure contains no `img`, `button` or `a`.
  - Without the prop, no `[data-testid="acx-repeated-region-evidence"]` renders.
  - Predicted RED: `Unable to find an element with the text: Same photo region is also listed in 1 other group`.
- `IdentityClusterList.test.tsx`, `describe('UXREC-1 repeated region wiring')`:
  - `renderList([P1A, P2B])` gives two cards, each with one disclosure. The count of `Edit label` / `Name this person` buttons and of label buttons equals the count for the same two records with 1×1 boxes, which produce no disclosure.
  - `[P1A, {...P1A, identity_id:'face-a2'}]` (same group) gives no disclosure.
  - `[C3C, UND]` gives the disclosure under `Not yet grouped (1)`.
  - Every permutation of `[P1A, P1A2, P2B]` gives no disclosure. Every permutation of `[P1A, P1A2, P2B, C3C]` gives disclosures only on the `person:2` and `cluster:c-3` cards, none on the `person:1` card. Each disclosure shows `Checked 2 of 3 loaded face records with usable box coordinates.` and `1 face record was skipped because its loaded copies disagree.`. The label buttons and the `Edit label` / `Name this person` / `Remove from group` buttons match, by name and order, a control render of the same permutation with `P2B` on media 11 and `C3C` on media 12. That control has the same groups and members but no region. (A 1×1-box control is not used here, because same-face dedup ignores unusable boxes and would change the `person:1` members.)
  - Existing 1×1 fixtures render no disclosure.

Keep green unchanged: the `groupIdentitiesByClusters same-face dedup (GPUFLOW-3 R1)` block, the twin-chip, provenance and suggestion-recovery suites, `gettext-literals.test.ts` and `banned-vocabulary.test.tsx`.

Proof:

- RED selectors fail as predicted:
  - `npm test -- js/admin/pages/workbench/identity-clusters/__tests__/repeatedRegionEvidence.test.ts`
  - `npm test -- js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts -t 'UXREC-1 identityGroupKey'`
  - `npm test -- js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx -t 'UXREC-1 repeated region disclosure'`
  - `npm test -- js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx -t 'UXREC-1 repeated region wiring'`
- After the change they pass, and so do the full IDENTITY command, typecheck and the ownership check.

**Source-complete when** all of the above pass. **Not proven here**: whether the supplied same-person crops are same-photo exact regions, cross-photo duplicates or recall fragmentation. That diagnosis belongs to a separately granted CORPUS probe. Rendered browser reflow and assistive-technology behaviour are also unproven.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned paths (repo-relative) | Upstream dependencies | Required tests |
| --- | --- | --- | --- |
| `uxrec-1-timeline` | `apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx`, `.../workbench/__tests__/DeadLetterPanel.test.tsx` | Joined plan + maps pass independent review | TIMELINE full-file command, typecheck |
| `uxrec-1-gpu-status` | `.../workbench/gpuStatePresentation.ts`, `.../hooks/{useGpuStateToasts.ts,useActivityStatus.ts}`, `.../utils/serviceUnavailable.ts`, `.../hooks/__tests__/{useGpuStateToasts.test.tsx,useActivityStatus.test.ts}`, `.../utils/__tests__/serviceUnavailable.test.ts`, `.../pages/settings/__tests__/GpuControlCard.test.tsx` | Same; `useActivityStatus.ts` grant is review-href derivation only | GPU full command, typecheck, bounded symbol diff |
| `uxrec-1-identity` | `.../identity-clusters/{utils.ts,repeatedRegionEvidence.ts,RepeatedRegionEvidenceDisclosure.tsx,IdentityClusterItem.tsx,IdentityClusterList.tsx}`, `.../identity-clusters/__tests__/{repeatedRegionEvidence.test.ts,utils.test.ts,IdentityClusterItem.test.tsx,IdentityClusterList.test.tsx}`, `.../styles/components/_identity-cluster-list.scss` | Same; no actual concurrent author on WBTRUST-4-shared files; no absent-worker dependency | IDENTITY full command, typecheck |

Single writers outside these lanes:

- **Map writer**: the three maps, their `.md` files and their `render_ux_maps.visible.json` entries. After slices merge, this writer alone updates map statuses.
- **WBTRUST-5**: its reserved composition files.
- **Plan and inventory**: this plan's owner.

### Merge Order

1. Planning gate: the joined plan, inventory and maps pass independent review ([GRPH-01] **Model the work as a DAG, then topological-sort**, *The Algorithm Design Manual, ch. 7*).
2. `uxrec-1-timeline`, `uxrec-1-gpu-status` and `uxrec-1-identity` share no data or file edge and merge in any order. The second and third merge after a rebase and a rerun of their full commands.
3. Branch review per slice, then the map writer's status update, then runtime acceptance under a separate grant.

```text
plan+inventory (this lane) --+
map writer (maps) -----------+--> independent planning review --+--> T1 timeline --+
                                                                +--> G1 gpu ------+--> per-slice branch review --> map status update
                                                                +--> I1 identity -+
CORPUS probe (separate grant) ---------------------------------------------------------> identity-repair claims (not in this plan)
RUNTIME grant + exact deployed build/config ----------------------------------------------> runtime acceptance
```

### Conflict graph

[GRPH-09] **Colour the conflict graph**, *Graph Theory with Applications, ch. 8*. The vertices are lanes and plans, and an edge means a shared writable path.

- T1, G1 and I1 share no edges. One colour covers all three, so they run in parallel.
- I1 and an actual concurrent WBTRUST-4 author would share `IdentityClusterList.tsx` and `utils.ts`. If both are active on those files, serialize those writers and rebase/rerun whichever merges second. An absent or completed worker adds no dependency or wait.
- G1 edits no WBTRUST-5-reserved file, so there is no shared-write edge. The narrower producer href changes when the unchanged `ActivityStatusStrip` offers its existing review link; its read-only regression suite must pass. No strip copy, cooldown/budget or layout edit is granted.
- The map writer has no edge with any slice.

No capacity-limited assignment is made here, so GRPH-07 does not fire.

### Manifest

```bash
make lane-manifest-init TASK=UXREC-1 LANE_IDS='uxrec-1-timeline uxrec-1-gpu-status uxrec-1-identity' TASK_PLAN=docs/tasks/uxrec/UXREC-1-workbench-recovery-task-plan.md
```

### Orchestration Mode

- **Subagent or remote author**: brief each lane with its slice block, its owned paths and this plan's Constraints. Do not let lanes edit maps, other lanes' paths or reserved files.
- **Shell fallback**: one worktree per lane branch with the same ownership, commands and evidence.

## Decomposition

```json
{
  "version": 1,
  "items": [
    {
      "id": "s1",
      "title": "TIMELINE: Needs attention default, separate History, no duplicate failed rows",
      "independent": true,
      "owns": [
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx",
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx"
      ],
      "depends": [],
      "blast": "none"
    },
    {
      "id": "s2",
      "title": "GPU_STATUS: evidence-bound toasts and endpoint_unconfigured copy",
      "independent": true,
      "owns": [
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/gpuStatePresentation.ts",
        "apps/prototype-wp-alt-context/js/admin/hooks/useGpuStateToasts.ts",
        "apps/prototype-wp-alt-context/js/admin/hooks/useActivityStatus.ts",
        "apps/prototype-wp-alt-context/js/admin/utils/serviceUnavailable.ts",
        "apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useGpuStateToasts.test.tsx",
        "apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useActivityStatus.test.ts",
        "apps/prototype-wp-alt-context/js/admin/utils/__tests__/serviceUnavailable.test.ts",
        "apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/GpuControlCard.test.tsx"
      ],
      "depends": [],
      "blast": "none"
    },
    {
      "id": "s3",
      "title": "IDENTITY: repeated-region evidence disclosure",
      "independent": true,
      "owns": [
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/utils.ts",
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/repeatedRegionEvidence.ts",
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/RepeatedRegionEvidenceDisclosure.tsx",
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx",
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx",
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/repeatedRegionEvidence.test.ts",
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts",
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx",
        "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx",
        "apps/prototype-wp-alt-context/js/admin/styles/components/_identity-cluster-list.scss"
      ],
      "depends": [],
      "blast": "none"
    }
  ]
}
```

---

## Consolidated Checklist

## Context and Ownership

- [ ] Verified the Canon v0.26.2 manifest digests and read this plan, the inventory, the three maps and the WBTRUST-4/5 reservation lists.
- [ ] Confirmed the lane owns exactly its Decomposition `owns` paths. Map JSON/MD/projection, WBTRUST-5-reserved files, backend, PHP and `ClusterReviewPanel.tsx` are untouched.
- [ ] For I1, confirmed no actual concurrent author is editing `IdentityClusterList.tsx` or `utils.ts`; no dependency on an absent WBTRUST-4 worker is invented.
- [ ] Ran tests on the VM from `apps/prototype-wp-alt-context` with `npm test --`, never `test:agent`.

### Checklist for Slice T1: TIMELINE

- [ ] Added the fixtures `OLD_FAILED`, `PENDING_OP`, `CONFLICT_OP`, `ACKNOWLEDGED_OP` and `DISCARDED_OP`, and the eight `UXREC-1 needs attention` tests. Recorded each predicted message and saw each one fail against unchanged `DeadLetterPanel.tsx`.
- [ ] Added `PANEL_VIEW`, `ATTENTION_STATUSES`, the new state fields and actions, and reducer cases that reset `timelineOffset`, `pendingDiscardId`, `bulkRetryArmed` and `bulkDiscardArmed`.
- [ ] Added `handlePanelViewChange` and `handleAttentionStatusChange`, and kept `handleTimelineStatusChange` for History filters.
- [ ] Moved the timeline JSX into `DeadLetterTimelineSection`, which owns the `useOutboxOperations` call and one polite live container. History filters use `aria-pressed` and ignore re-selection. Removed the top-level `timelineQuery`.
- [ ] Rendered the `aria-pressed` view and status groups and mounted one region per mode as the Target Outcome table specifies. The maintenance zone renders only in Failed.
- [ ] History retains guarded recovery only on failed rows, once per view, with confirmation/capability/age and terminal guards preserved. No bulk control appears in History; no age-only hiding or July-record clearance claim.
- [ ] Scoped the failed-list loading and error states to the Failed region, kept `aria-busy` while loading, and renamed the section label to `Changes panel`.
- [ ] Applied the exact copy table, with literal gettext first arguments.
- [ ] Made the listed intentional edits to existing tests and left `DeadLetterOperationRow` unchanged.
- [ ] Captured GREEN for the RED selector and the TIMELINE full-file command, `npm run typecheck`, and the ownership `git diff --name-only`.

### Checklist for Slice G1: GPU_STATUS

- [ ] Added the `UXREC-1 GPU toast evidence`, `UXREC-1 review href evidence`, `UXREC-1 endpoint_unconfigured` and `UXREC-1 stale snapshot` tests; saw each defect assertion fail as predicted and the preservation guards pass before and after.
- [ ] Changed `warmingToast` and `degradedToast`, added `degradedToastWithDrafts` with `_n`, and added `doneToastWithoutDrafts` with the exact neutral literal.
- [ ] In DEGRADED, chose copy and attached "Review results" only when `status.draftCount > 0`. In DONE, zero results have neutral completion copy and no action, positive results with null href have no action, and positive results with href keep existing review copy/navigation. Preserved all other branches, ready/Back to run, real errors/cancel/retry, dormant/progress/first-observation suppression and per-run edge memory.
- [ ] Added `useActivityStatus.ts:reviewDraftsHrefForStatus` and used it only for the actions `reviewDraftsHref` expression. The href requires DONE, positive returned completed count and an id accepted by existing `serializeRunParam`; existing `toDescriptionHistoryRun` owns the destination. No status schema, cooldown, budget, lifecycle, cancel/retry or layout change.
- [ ] Added `UNAVAILABLE_REASON.ENDPOINT_UNCONFIGURED`, its `UNAVAILABLE_REASON_COPY` entry, and the `CLOSED_REASON_COPY` test row.
- [ ] Updated the existing degraded test to `draftCount: 1`.
- [ ] Captured GREEN for the RED selectors, producer and consumer preservation guards, GPU full command and typecheck. The ownership diff lists only the eight owned paths, and the `useActivityStatus.ts` symbol diff matches the narrow grant. Reserved strip source and all read-only regression files remain untouched.

### Checklist for Slice I1: IDENTITY

- [ ] Added `repeatedRegionEvidence.test.ts` plus the `UXREC-1 identityGroupKey`, `UXREC-1 repeated region disclosure` and `UXREC-1 repeated region wiring` tests, and saw each fail as predicted.
- [ ] Added `identityGroupKey` and switched `groupIdentitiesByClusters` to it. The existing utils and same-face dedup tests stay green.
- [ ] Implemented `buildRepeatedRegionEvidence` and `repeatedRegionViewForGroup` to rules 1–6 and the types above. No IoU, no similarity, no image fields.
- [ ] Rule 2 compares copies field by field over the complete retained tuple with `Object.is`. It uses no joined string, no `groupKey`-only signature and no winning copy. The `[P1A, P1A2, P2B]` and `[P1A, P1A2, P2B, C3C]` permutations, every-field participation, `face-d` delimiter and signed-zero fixtures pass. A region's `bbox` comes from its sorted `observations[0]`.
- [ ] Implemented `RepeatedRegionEvidenceDisclosure` as native `<details>`/`<summary>`, closed by default, using text only and the exact copy. Exact references appear only inside the body.
- [ ] Wired `IdentityClusterList`: a memoized evidence value, `groupLabels`, a per-item `repeatedRegionEvidence`, and the residue-section disclosure. `IdentityClusterItem` renders it last in display mode.
- [ ] Added `.acx-identity-cluster__repeated-region` rules to `_identity-cluster-list.scss` using tokens and `overflow-wrap: anywhere` for `code`.
- [ ] Captured GREEN for the RED selectors and the IDENTITY full command (including `gettext-literals.test.ts` and `banned-vocabulary.test.tsx`), typecheck, and the ownership diff.

## Review Readiness

- [ ] No slice changes a boundary. Each boundary row's verification evidence is attached: status params, the PHP-pinned envelope, and permutation and purity tests.
- [ ] Each RED test's predicted and observed failure is recorded in the slice handoff decision, not in this file.
- [ ] The runtime-acceptance items stay listed as unproven. No slice report claims deployed behaviour, July-record clearance, CPU availability or an identity diagnosis.
- [ ] The map writer has reconciled map action IDs (`act-edit-person-name`, `act-toggle-repeated-region-evidence`, `act-view-current-attention`, `act-view-audit-history`, `act-retry-dead-letter`, `act-discard-dead-letter`) with the merged code references.
- [ ] Joined maps and documents agree: History has existing failed-row recovery with guards and no bulk zone; review requires returned results, and DONE with zero/null href offers no review action. No read-only History promise or deferred zero-DONE bug remains. An independent planning gate follows; this document does not approve itself.
- [ ] Each handoff decision records the change, its verification and "no contract change".

## Stretch Goals

- [ ] **Cleanup, not the visible fix.** Delete the unused `gpuStatePresentation.ts:gpuStateNotice` and the entries only it reads (`notReportedNotice`, `startingNotice`, `warmingNotice`). Rewrite `gpuStatePresentation.test.ts` "owns the stopped and degraded consequence copy" and "returns notice copy for every canonical GPU state" to assert `stoppedNotice` and `degradedNotice` directly. This would add `gpuStatePresentation.test.ts` to G1's owned paths, which is still the single writer. Proof: `grep -rn gpuStateNotice js/admin` returns nothing, and the GPU full command passes.

## Success Criteria

- [ ] On first render, the Changes panel shows Needs attention › Failed. Each failed operation renders exactly once, with its guarded Retry/Discard, and no outbox timeline query runs.
- [ ] Pending, Conflict and History each send exactly one server-filtered `useOutboxOperations` request with offset 0 on entry. Their count line uses that query's `total`. Only Failed shows the maintenance zone.
- [ ] History failed rows keep guarded Retry/Discard once per view; terminal failed rows have no Retry, and non-failed rows have no recovery actions. Bulk Retry/Discard render only in `attention_failed`.
- [ ] No view change sends a mutation, and a failed-list error leaves History reachable.
- [ ] No GPU toast string contains "CPU". The degraded toast offers "Review results" only when `draftCount > 0`.
- [ ] DONE with zero results says `Description run finished — no drafts returned.` and has no review action. Positive DONE keeps existing copy and offers review only with a non-null href. The producer emits that href only for DONE + positive returned completed count + valid run id; ready/errors/suppression/edge memory remain green.
- [ ] `unavailableReasonCopy('endpoint_unconfigured')` returns configuration copy, and `GpuControlCard` renders it for the PHP-pinned envelope. Stale telemetry never renders "not configured".
- [ ] A repeated exact region across two loaded groups renders one collapsed native disclosure per involved card, with the region, references and pool counts. Same-group, cross-photo, overlapping, degenerate and conflicting inputs render none.
- [ ] Copies of one face record that disagree in any retained field, including only `cluster_id` under a winning `person_id`, abstain in every input order. Each counts once as loaded and never as eligible, joins no region and is reported by the conditional skipped line. Identical copies still count once and still match.
- [ ] `groupIdentitiesByClusters` output, `getEditableClusterId` and `members[0].identity_id` are identical with and without the projection.
- [ ] Every slice's full command and `npm run typecheck` pass on the VM, and each lane's diff lists only its owned paths.

## Canon authority (Canon v0.26.2)

Pinned at `/home/gate/heuristics-canon-v0.26.2`, from <https://github.com/darce/heuristics-canon>. All 53 manifest digests were verified (12 lexicons, 6 docs, 35 reasoning cards). Each row below cites the published rule name and its Source cell.

| Decision | Rule |
| --- | --- |
| GPU copy states only returned evidence; unknown never becomes "not configured" | [HAI-05] **Imperceptible AI is not ethical**, `lexicons/interaction-ux.md#hai-05`, *Human-Centered AI* |
| An accepted run keeps visible status, next step and existing cancel/retry | [INT-10] **Status–predict–stop**, `lexicons/interaction-ux.md#int-10`, *Human-Centered AI* |
| Separate backlog maintenance (Needs attention › Failed) from audit navigation (History), each with a named end state | [INT-19] **One outcome per interaction**, `#int-19`, *Microinteractions, ch. 1* + *Microinteractions, ch. 3* |
| Retain guarded recovery beside an inspected failed History row; no switch-and-refind step | [NAV-19] **Keep related work adjacent**, `lexicons/interaction-ux.md#nav-19`, *About Face, ch. 12* |
| Toast text names the resulting state ("no descriptions returned yet", "N drafts ready") | [INT-22] **Explain the result**, `#int-22`, *Microinteractions, ch. 4* |
| One disclosure per card; no new banner or toast for evidence | [PERC-10] **Least useful feedback**, `#perc-10`, *Microinteractions, ch. 4* |
| A review action only where results exist; the thumbnail stays non-interactive | [INT-01] **Affordance match**, `#int-01`, *Designing Interfaces, 3rd ed.* |
| Evidence shows data, comparison basis (exact box) and limit; each listed face record is one whose loaded copies agree on every retained field, and disagreeing copies are counted as skipped, not resolved | [VIZ-23] **Show the evidence path**, `#viz-23`, *Richard Feynman's Mental Models, ch. 5* + *Envisioning Information, ch. 4* |
| If a selected image becomes consequential evidence, expose its selection pool. Here the thumbnail is context only; the unchanged loaded-pool contract supports the text comparison, not an image-selection claim. | Conditional [VIZ-41] **Reveal the image-selection pool**, `#viz-41`, *Visual Explanations, ch. 1*; its image-evidence trigger is absent in this slice |
| Exact equality only; no merge or transitive similarity closure | [GRPH-18] **Never trust the transitive closure of a raw similarity threshold**, `lexicons/graph-theory.md#grph-18`, *Introduction to Information Retrieval, § 17.2* |
| Loading, empty, error and unknown states are designed per mode | [RLSE-04] **Undesigned state is a bug**, `lexicons/engineering.md#rlse-04`, bootstrap (practice label) |
| Work order is a DAG | [GRPH-01] **Model the work as a DAG, then topological-sort**, `graph-theory.md#grph-01`, *The Algorithm Design Manual, ch. 7* |
| File collisions are conflict edges (I1 and WBTRUST-4); the plan/inventory writer and the map writer hold disjoint files | [GRPH-09] **Colour the conflict graph**, `graph-theory.md#grph-09`, *Graph Theory with Applications, ch. 8* |
| Every boundary has one ownership path | [TEAM-01] **Align org communication with intended architecture**, `lexicons/planning.md#team-01`, *Team Topologies* |
| RED predicted before GREEN | [TEST-06] **Watch it fail once / predict the failure**, `lexicons/engineering.md#test-06`, *Modern Software Engineering, ch. 8* |
| Keyboard reachability of view groups and disclosure | [A11Y-11] **Keyboard walk (2.1.1/2.1.2/2.4.3/2.4.7)**, `#a11y-11`, *Web Content Accessibility Guidelines 2.2, SC 2.1.1* |
| Timeline count announced politely on view change | [A11Y-21] **Announce status (4.1.3)**, `#a11y-21`, *Web Content Accessibility Guidelines 2.2, SC 4.1.3* |
| Long references wrap at 320 px | [A11Y-08] **Reflow and resize (1.4.4/1.4.10/1.4.12)**, `#a11y-08`, *Web Content Accessibility Guidelines 2.2, SC 1.4.4* |
| Discard stays confirmed | [A11Y-18] **Reversible, checked, or confirmed (3.3.4)**, `#a11y-18`, *Web Content Accessibility Guidelines 2.2, SC 3.3.4* |

Matching cards checked against their full triggers and verification sections:

- `designed-unknown` (CARD-03, via RLSE-04): zero-DONE, empty and partial-evidence states are explicit; invalid observations abstain without a person classification.
- `falsification-disconfirmers` (CARD-08, via TEST-06): each defect has a predicted RED assertion; positive and suppression guards cannot be counted as RED.
- `measurement-integrity` (CARD-11, via TEST-06): real-shaped completed-count fixtures and unchanged regression cases constrain the test instrument; a docs check proves no product behavior.
- `perceived-enforced-boundaries` (CARD-12, via HAI-05, INT-01, GRPH-18 and TEAM-01; Principle 10): the views, disclosure and toasts imply only boundaries that the data, actions and ownership enforce. One listed face record reference implies one record only when its loaded copies agree; a repeated region identifies no person.

The candidate cards `bounded-role-lets-a-small-model-be-safe` (CARD-19), `constrained-domains-have-solved-it` (CARD-22) and `controlled-vocabulary-caps-hallucination` (CARD-24) were checked and are inert here: no model-tier choice, custom widget or generated closed-class attribute is proposed. A11Y-12's custom-widget and CAL-02's forced-classification triggers are absent, so neither is an applied citation. Native controls and deterministic abstention remain explicit implementation requirements. Principle 2's cross-domain disconfirmers and Principle 10's security/architecture siblings check the same boundaries without adding a new security workstream. GRPH-18 constrains the explicitly rejected similarity-chaining alternative; it does not claim that this exact-coordinate projection clusters identities. VIZ-23 applies to the text finding and its alternative account; VIZ-41 remains conditional on consequential image evidence.

LAY-27's trigger (repeated print pages) does not fire on this UI. GRPH-07 does not fire because no capacity-limited assignment is made.
