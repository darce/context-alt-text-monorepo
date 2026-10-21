# UXREC-1 workbench recovery inventory

2026-10-21. **Proposed design. Not approved. No product implementation and no runtime acceptance.** The executable slices, symbols, tests and ownership are in the [task plan](../../tasks/uxrec/UXREC-1-workbench-recovery-task-plan.md). This inventory explains current and target states, the screens, and why each design choice was made.

**Sources of truth.**

- The three maps `apps/prototype-wp-alt-context/docs/ux-maps/{workbench-operator-loop,describe-gpu-tier,workbench-identity-chips}.uxmap.json` are the SSOT for screens and actions. One map writer owns those JSON files, their generated `.md` and their `render_ux_maps.visible.json` entries.
- This inventory uses the shared contract from decision 18920, amended by decision 18935 for guarded History row recovery and G1 DONE/result gating. Action IDs remain `act-edit-person-name` (primary, `IdentityClusterItem`) and `act-toggle-repeated-region-evidence` (secondary, in place), plus the source IDs `act-view-current-attention`, `act-view-audit-history`, `act-retry-dead-letter` and `act-discard-dead-letter`.
- If the joined maps rename an ID, the map JSON wins. No product code reads these IDs.

**Provenance.**

- Anchors were checked against exact source `077ea234f222dd74ecb6031ab0073b78b61ca80a`, including security documentation main `e08970cda`, in history-stripped sandbox base `d4693910b4908d71ae7feedc9c1c1670810f3a3a`. Native provenance establishes the source-to-sandbox tree correspondence. Original commit objects are absent by design, and that absence is not a source defect.
- No graph or handoff tool was available in this lane, so the supplied codemap anchors (`groupIdentitiesByClusters`, `gpuStateNotice`, `ClusterPanelProvider`, `fetchClusterMembers`, `_is_gpu_operator`) were checked by reading the files.
- The supplied semantic/ONNX decision packet is selected and verified. Missing finding vectors (`query_finding_not_embedded`) remain typed gaps; full prior finding texts are supplied. These gaps are not evidence that no prior art exists.
- The working tree's unrelated `uv.lock` change is preserved.

## Current and target inventory

Paths are relative to `apps/prototype-wp-alt-context/` unless they start with `apps/`. "Preserve" rows are integrated work that must not regress. They are not new work.

| Surface / trigger | Current source evidence | Target outcome |
| --- | --- | --- |
| Open the Changes panel | `js/admin/pages/workbench/DeadLetterPanel.tsx`: `INITIAL_STATE.timelineStatus: 'all'`. The failed list (`useDeadLetterOperations`) and the all-status timeline (`useOutboxOperations`) always both render. `DeadLetterOperationRow.showFailedRecovery` is true for failed timeline rows, so each failed row and its Retry/Discard appear twice. | The panel opens on **Needs attention › Failed**, which shows only the existing failed list and maintenance zone. Pending and Conflict show only the server-filtered timeline. **History** shows the existing all-status or filtered timeline with existing guarded recovery only on failed rows, once per view. Bulk Retry/Discard stay `attention_failed` only. |
| Counts | The failed list shows `Showing a-b of N failed changes.` from its server total. The timeline shows `Showing a-b of N changes (status).` from its own server total. | Unchanged per list. There is no combined attention count, and no locally filtered page is shown as a total. |
| Failed-list load error | An early return replaces the whole panel, timeline included. | The error stays inside the Failed region. History, Pending and Conflict remain reachable. |
| Four supplied July failed label updates | `src/sovereign/sync/class-outbox-maintenance-service.php` discards eligible superseded exhausted label rows. The rows' eligibility and processing are unverified. | They remain in **Needs attention › Failed** while their server status is `failed`. They leave only through existing reconciliation or a guarded operator action. There is no clearance claim and no age-only hiding. This slice improves classification and navigation, not the records themselves. |
| GPU warming (accepted run) | `js/admin/hooks/useGpuStateToasts.ts` shows `GPU_STATE_VOCABULARY.warmingToast` = "GPU warming — CPU drafts first". | "GPU warming — this run is waiting for the description service". It makes no CPU claim. |
| GPU degraded during a run | `degradedToast` = "GPU unavailable — CPU drafts kept", always with "Review results". | With `draftCount === 0`: "GPU unavailable — no descriptions returned yet" and no review action. With `draftCount > 0`: "GPU unavailable — N drafts ready to review" with "Review results". |
| GPU DONE review | `useGpuStateToasts.ts:DONE` always shows `doneToast(count)` and "Review N drafts", even at zero; the click returns without action when `reviewDraftsHref` is null. `useActivityStatus` offers that href for DONE with any non-null run id. | G1: zero results say exactly `Description run finished — no drafts returned.` with no review action. Positive results keep existing completion copy; review requires positive `draftCount` and a non-null href. The producer offers the href only for DONE + positive returned completed count + a run id accepted by existing `serializeRunParam`, using existing `toDescriptionHistoryRun`. |
| GPU ready / failed toasts; dormant unavailable | Existing ready ("Back to run") and failed (Retry only when retryable) toasts. A `GPU_STATUS_UNAVAILABLE` toast with no run is suppressed. | **Preserve** ready/Back to run, genuine errors/cancel/retry, dormant/progress/first-observation suppression and per-run edge memory unchanged. |
| Latent unknown and starting notices | `gpuStatePresentation.ts:gpuStateNotice` → `notReportedNotice` ("…can still continue on CPU") and `startingNotice` ("CPU drafts stay available…"). It has no production caller; only `gpuStatePresentation.test.ts` reads it. | Optional cleanup (plan Stretch Goal). This is not the visible fix and not required to close the GPU slice. |
| Settings: GPU telemetry stale or unknown | `pages/settings/GpuControlCard.tsx` maps `snapshot_fresh: false` to `GPU_STATE.UNKNOWN` ("Service: not reported") and hides Start/Stop. Refresh re-reads status. | **Preserve**. Unknown stays neutral and is never shown as "not configured". `/gpu/status` (`routers/gpu.py:GpuStatusResponse`) has no configuration or capability field. |
| Settings: received `endpoint_unconfigured` envelope | The PHP proxy passes the typed scene reason through (`class-gpu-control-controller.php:map_unavailable_reason`; shape pinned in `GpuControlControllerTest.php`). `utils/serviceUnavailable.ts:unavailableReasonCopy` has no entry, so it falls back to "an unexpected error occurred (endpoint_unconfigured)". | "Description service is unavailable because its GPU endpoint is not configured. An administrator must set the GPU endpoint for the Description service. Retry only checks again; it does not change the setting." Permission denial keeps its own `upstream_4xx` copy. |
| Navigation / reload during a run | `hooks/describeOperationStore.ts` and `useBulkDescribe.ts` resume the tenant-scoped `run_id` without resubmitting. | **Preserve**. Source persistence is not evidence of live warm-up or results. |
| Same exact photo region under two groups | `identity-clusters/utils.ts:groupIdentitiesByClusters` groups by person, then cluster, then ungrouped. Same-face dedup (IoU > 0.5) runs only within one group, so cross-group repeats stay as separate cards with no cue. | Each involved card gets a collapsed native disclosure, "Same photo region is also listed in N other group(s)". It lists `Photo <media_id>`, the exact box, each matching observation's group reference and face record reference, the limit statement, and loaded-pool counts. Grouping, order and targets are unchanged. |
| Naming / editing a group | `IdentityClusterItem.tsx` label button → `startEditing`. `ClusterActions` offers "Edit label" / "Name this person". `namingReady` does not wait for advisory suggestions. | **Preserve** as the one primary action (`act-edit-person-name`). |
| Group thumbnail | `ClusterPreview.tsx` prefers `representative_face`, which may come from another photo. It is non-interactive. | **Preserve**. It is context only. The disclosure never presents it as the matching observation. |
| Expanded person chip / person workspace from a chip | Pre-existing map intent in `workbench-identity-chips` (`act-expand-person-chip` and related). `IdentityClusterList` has no review callback, and `ClusterPanelContext.tsx:readReviewFromParams` needs `panel=review&cluster=<id>`. | Out of scope. It stays pre-existing map intent and is not promoted as a UXREC outcome. There is no new route, tab, panel or "Review faces" button. |
| Empty unlabeled faces | `api/recognition/clusterApiQueries.ts` accepts the object response with `clusters: []`. | **Preserve**. Real transport or auth failures stay errors. |
| Recognition URL / key | `pages/settings/SettingsForm.tsx`, `pages/SettingsPage.tsx`: commit on blur or Enter, acknowledged readback, health check after save. | **Preserve**. |
| Retention unavailable | `pages/RetentionPage.tsx` shows the service, cause, check time and a real refetch. | **Preserve**. Recovery from upstream 500 remains a runtime item. |

## GPU run outcomes (distinct; evidence-gated)

Source: `apps/prototype-description-service/scene/application/describe_run_worker.py`. Frontend evidence fields: `js/admin/api/describeApi.ts`.

| Outcome | Worker path | Evidence the UI can read | What copy may say |
| --- | --- | --- | --- |
| GPU success | `_wait_for_gpu_ready` returns and describing proceeds with the GPU policy | `DescribeRunResponse.status` completed or completed_with_errors; item `tier: 'final_gpu'`; `fallback_reason: null`; `completed` count | Ready, then "N drafts ready to review". Review appears only when N > 0. |
| Usable-CPU completion after warm-up timeout | `TimeoutError` → `_apply_warmup_cpu_fallback` returns a continuation. The caller sets `gpu_policy = None`, and `_persist_warmup_cpu_fallback_reason` records the fallback. | `fallback_reason` non-null; item `tier: 'provisional_cpu'`; `completed` count | Only after this evidence arrives may copy name CPU results. There is no automatic CPU-to-GPU upgrade of those drafts. |
| Typed failure without CPU | `TimeoutError` with no usable adapter (`_usable_cpu_describe_one` returns `None`) → run FAILED, terminal code `gpu_warmup_timeout` | `status: 'failed'`; `terminal.code`; `terminal.retryable` | "GPU warm-up timed out. Retry to continue." Retry appears only when retryable. No drafts or review are implied. |
| No warm-up at all | `gpu_run_policy` returns `None` when no endpoint URL is configured. Describe readiness reports `endpoint_unconfigured`. | Typed `unavailable.reason` on describe or readiness paths. Nothing on `/gpu/status`. | Configuration copy, and only where that envelope is actually received. |

The UI cannot know before a run returns whether a usable CPU adapter exists, so no pre-result copy may promise CPU work ([HAI-05] **Imperceptible AI is not ethical**, *Human-Centered AI*; [INT-10] **Status–predict–stop**, *Human-Centered AI*). DONE with zero completed results is a neutral completion, with no review action. Positive results require an available href for review; a null href never produces a no-op control.

## Screens and interaction contract

These are content sketches, not runtime screenshots. Wide is 90 text columns and narrow is 40; they are checked mechanically. In the sketches, `*` marks `aria-pressed="true"` and `<…>` marks a placeholder for actual server data. No live IDs, titles or counts were invented. Copy is the plan's exact copy. Routine updates add no toast, sound or spinner.

### Needs attention › Failed (default)

```text
WIDE
+----------------------------------------------------------------------------------------+
| Failed Sync Queue (overlay title, WBTRUST-5 owned)                             Close   |
| Changes view:  [Needs attention*]  [History]                                           |
| Needs attention status:  [Failed*]  [Pending]  [Conflict]                              |
+----------------------------------------------------------------------------------------+
| Failed changes                                                                         |
| Showing 1-<n> of <total> failed changes.                                               |
| [Retry all failed (<total>)]  [Discard <k> eligible]                                   |
| Cluster label update                                         [Retry]  [Discard]        |
| Entity: <entity_key> (cluster)   Attempts: <n>   Age: <n> days                         |
| Last attempted: <time>   Error: <code>: <message>                                      |
| [Previous]  [Next]                                                                     |
+----------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| Failed Sync Queue              Close |
| [Needs attention*]  [History]        |
| [Failed*] [Pending] [Conflict]       |
+--------------------------------------+
| Failed changes                       |
| Showing 1-<n> of <total> failed      |
| changes.                             |
| [Retry all failed (<total>)]         |
| [Discard <k> eligible]               |
| Cluster label update                 |
| Entity: <entity_key> (cluster)       |
| Attempts: <n>   Age: <n> days        |
| Error: <code>: <message>             |
| [Retry]  [Discard]                   |
| [Previous]  [Next]                   |
+--------------------------------------+
```

- **Trigger**: the Changes panel opens. `panelView: 'attention'`, `attentionStatus: 'failed'`.
- **Behaviour**: only `useDeadLetterOperations` runs (20-row page plus 50-row eligibility). No outbox timeline query runs.
- **Actions**: existing guarded row Retry/Discard (Discard needs "Confirm discard"). Armed bulk "Retry all failed (N)" and "Discard eligible" auto-disarm. None is the screen's primary.
- **Keyboard and announcements**: Tab reaches the view group, the status group, the bulk zone, then rows. Activating a toggle keeps focus on it, so focus never jumps. The existing polite status region announces loading and outcomes, and errors stay inline ([A11Y-11] **Keyboard walk (2.1.1/2.1.2/2.4.3/2.4.7)**, *Web Content Accessibility Guidelines 2.2, SC 2.1.1*; [A11Y-21] **Announce status (4.1.3)**, *Web Content Accessibility Guidelines 2.2, SC 4.1.3*).
- **Failure**: an error shows the alert "Unable to load failed changes." inside this region only.
- **Empty**: the existing "No failed changes." with "Refresh failed changes". This never implies that history is empty.

### Needs attention › Pending / Conflict

```text
WIDE
+----------------------------------------------------------------------------------------+
| Changes view:  [Needs attention*]  [History]                                           |
| Needs attention status:  [Failed]  [Pending*]  [Conflict]                              |
+----------------------------------------------------------------------------------------+
| Pending changes                                                                        |
| Showing 1-<n> of <total> changes (pending).          (polite live region)              |
| Cluster label update   Status: pending   Created: <time>   Age: <n> minutes            |
| Entity: <entity_key> (cluster)                                                         |
| [Previous timeline page]  [Next timeline page]                                         |
| Empty result: No pending changes.   (Conflict: No conflicted changes.)                 |
+----------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| [Needs attention*]  [History]        |
| [Failed] [Pending*] [Conflict]       |
+--------------------------------------+
| Pending changes                      |
| Showing 1-<n> of <total> changes     |
| (pending).                           |
| Cluster label update                 |
| Status: pending                      |
| Entity: <entity_key> (cluster)       |
| [Previous timeline page]             |
| [Next timeline page]                 |
+--------------------------------------+
```

- **Behaviour**: exactly one `useOutboxOperations({limit:10, offset:0, status:'pending'|'conflict'})`. The count is that query's server total, announced through one polite container.
- **Actions**: no maintenance zone and no row recovery, because non-failed rows already render none. Conflicts are still resolved in the Conflict Inbox (`act-open-conflicts`).
- **View changes**: switching resets `timelineOffset` to 0, disarms bulk confirmations, clears a pending row discard and sends no mutation ([INT-19] **One outcome per interaction**, *Microinteractions, ch. 1* + *Microinteractions, ch. 3*).

### History

```text
WIDE
+----------------------------------------------------------------------------------------+
| Changes view:  [Needs attention]  [History*]                                           |
+----------------------------------------------------------------------------------------+
| Change history                                                                         |
| [All*] [pending] [acknowledged] [conflict] [failed] [discarded]                        |
| Showing 1-<n> of <total> changes (all statuses).     (polite live region)              |
| Cluster label update   Status: acknowledged   Acknowledged: <time>                     |
| Cluster label update   Status: failed   Error: <code>: <message>                       |
|                                                              [Retry]  [Discard]        |
| Cluster dismiss        Status: discarded   Will not retry                              |
| [Previous timeline page]  [Next timeline page]                                         |
+----------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| [Needs attention]  [History*]        |
+--------------------------------------+
| Change history                       |
| [All*] [pending] [acknowledged]      |
| [conflict] [failed] [discarded]      |
| Showing 1-<n> of <total> changes     |
| (all statuses).                      |
| Cluster label update                 |
| Status: failed                       |
| Error: <code>: <message>             |
| [Retry]  [Discard]                   |
| [Previous timeline page]             |
| [Next timeline page]                 |
+--------------------------------------+
```

- **Trigger**: `act-view-audit-history` (History).
- **Behaviour**: the existing status filters, now `aria-pressed` and focusable, drive the existing single-status query. `All` sends no status.
- **Actions**: only rows whose status is `failed` keep their existing guarded row Retry/Discard, once per view. Terminal failed rows keep Discard but no Retry; acknowledged/discarded/pending/conflict rows have neither. Preserve confirmation/capability/age and eligibility guards. The maintenance zone and bulk Retry/Discard are absent; no new action or endpoint is added.
- **Empty**: "No changes found for this filter."
- **Limit**: the WBTRUST-5-owned overlay title "Failed Sync Queue" is out of scope here.

### GPU toasts during an accepted run

```text
WIDE
+----------------------------------------------------------------------------------------+
| (i) GPU warming — this run is waiting for the description service                      |
+----------------------------------------------------------------------------------------+
| (!) GPU unavailable — no descriptions returned yet                       [Dismiss]     |
+----------------------------------------------------------------------------------------+
| (!) GPU unavailable — <n> drafts ready to review       [Review results]  [Dismiss]     |
+----------------------------------------------------------------------------------------+
| (+) Description run finished — no drafts returned.                       [Dismiss]     |
+----------------------------------------------------------------------------------------+
| (+) <n> drafts ready to review                  [Review <n> drafts]      [Dismiss]     |
+----------------------------------------------------------------------------------------+
| (+) <n> drafts ready to review                                           [Dismiss]     |
+----------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| (i) GPU warming — this run is        |
| waiting for the description service  |
+--------------------------------------+
| (!) GPU unavailable — no             |
| descriptions returned yet            |
|                            [Dismiss] |
+--------------------------------------+
| (!) GPU unavailable — <n> drafts     |
| ready to review                      |
| [Review results]           [Dismiss] |
+--------------------------------------+
| (+) Description run finished — no    |
| drafts returned.                     |
|                            [Dismiss] |
+--------------------------------------+
| (+) <n> drafts ready to review       |
| [Review <n> drafts]        [Dismiss] |
+--------------------------------------+
| (+) <n> drafts ready to review       |
|                            [Dismiss] |
+--------------------------------------+
```

- **Trigger**: run activity edges from `useActivityStatus`. Each edge fires at most once per run (existing edge memory).
- **Copy rules**: copy names only returned state ([INT-22] **Explain the result**, *Microinteractions, ch. 4*). "Review results" appears only when `draftCount > 0`. DONE zero has the exact neutral completion copy and no action; positive DONE keeps existing `doneToast(count)` and review appears only with a non-null href ([INT-01] **Affordance match**, *Designing Interfaces, 3rd ed.*). The last two sketches show positive DONE with and without that href.
- **Warming toast**: an info toast that auto-dismisses.
- **Degraded toasts**: error toasts with `durationMs: null`, so they persist until dismissed (existing behaviour).
- **DONE toasts**: success toasts keep `durationMs: null` and existing per-run DONE edge memory. G1's proposed hook tests use real `UseActivityStatusResult` shapes for DONE zero, positive/null href and positive/href, plus existing ready/errors/suppression guards. `useActivityStatus.test.ts` checks real completed-run counts and the new `reviewDraftsHrefForStatus` boundary cases; none of these future tests ran in this documentation lane.

### Settings › Description Service: received configuration error vs stale telemetry

```text
WIDE
+----------------------------------------------------------------------------------------+
| Settings › Description Service                                                         |
| (!) Description service is unavailable because its GPU endpoint is not configured.     |
| An administrator must set the GPU endpoint for the Description service. Retry only     |
| checks again; it does not change the setting.   Last checked <time>                    |
| [Retry] -> Fetching…                                                                   |
+----------------------------------------------------------------------------------------+
| Stale telemetry (different state): Service: not reported   [Refresh]                   |
| (never shows 'not configured')                                                         |
+----------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| Settings › Description Service       |
| (!) Description service is           |
| unavailable because its GPU endpoint |
| is not configured.                   |
| An administrator must set the GPU    |
| endpoint for the Description         |
| service. Retry only checks again; it |
| does not change the setting.         |
| Last checked <time>                  |
| [Retry]                              |
+--------------------------------------+
```

- **Trigger**: a typed `unavailable` envelope with `reason: 'endpoint_unconfigured'` from status, intent or error, read through `readUnavailable`. Stale telemetry is a different state with neutral copy ([RLSE-04] **Undesigned state is a bug**, bootstrap (practice label)).
- **Retry**: an existing read-only refetch. The copy says it cannot configure anything.
- **Scope**: no Start, configuration or credential control is added.

### Identity card with repeated-region evidence (`act-toggle-repeated-region-evidence`)

```text
WIDE
+----------------------------------------------------------------------------------------+
| [current thumbnail]  <group label>   [Edit label]  [Remove from group]                 |
|                      > Same photo region is also listed in 1 other group               |
+----------------------------------------------------------------------------------------+
| [current thumbnail]  <group label>   [Edit label]                                      |
|                      v Same photo region is also listed in 1 other group               |
|                        Matching uses exact box coordinates in the face records         |
|                        loaded for this photo. It does not show that these faces        |
|                        are the same person, and nothing is merged or moved.            |
|                        Photo <media_id> — box x <x>, y <y>, width <w>, height <h>      |
|                        - <label> (person <person_id>) — face record <identity_id>      |
|                        - Face group <cluster_id> — face record <identity_id>           |
|                        Checked <e> of <n> loaded face records with usable box          |
|                        coordinates.                                                    |
+----------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| [thumb] <group label>                |
| [Edit label]                         |
| v Same photo region is also          |
|   listed in 1 other group            |
|   Matching uses exact box            |
|   coordinates in the face records    |
|   loaded for this photo. It does not |
|   show that these faces are the same |
|   person, and nothing is merged or   |
|   moved.                             |
|   Photo <media_id> — box x <x>,      |
|   y <y>, width <w>, height <h>       |
|   - <label> (person <person_id>)     |
|     — face record                    |
|     <identity_id, wraps anywhere>    |
|   - Face group <cluster_id, wraps>   |
|     — face record <identity_id>      |
|   Checked <e> of <n> loaded face     |
|   records with usable box            |
|   coordinates.                       |
+--------------------------------------+
```

- **Trigger**: the loaded identities for this media row contain eligible observations with the same positive `media_id` and exactly equal `x`/`y`/`width`/`height` under two or more different group keys.
- **Display**: the disclosure is native `<details>`/`<summary>`, closed by default, and comes after the naming control in DOM and visual order ([PERC-10] **Least useful feedback**, *Microinteractions, ch. 4*). "Remove from group" still appears only for single-member groups (existing gate).
- **Keyboard**: Tab reaches the summary, and Enter or Space toggles it natively. Expanding does not move focus.
- **Content**: the disclosure is text only, with no image, button or link. Ids are verbatim inside `<code>` and wrap anywhere at 320 px ([A11Y-08] **Reflow and resize (1.4.4/1.4.10/1.4.12)**, *Web Content Accessibility Guidelines 2.2, SC 1.4.4*). In the narrow layout the thumbnail, label and disclosure stack in one column.
- **Ungrouped residue**: the same disclosure appears under "Not yet grouped (N)" when a residue face is involved.
- **Limits**: nothing in the disclosure mutates data. Naming targets `getEditableClusterId(group)` and removal targets `members[0].identity_id`, both unchanged.

## Stable design choices

1. **Failed is the default attention status, and no combined count exists.** The outbox API takes one `status` per request (`conflictApi.ts:fetchOutboxOperations`). A combined unresolved total needs several queries or a backend aggregate. Filtering one page locally would present a partial page as a global total. The failed list already has its own server total and the existing guarded recovery, so it is the safe default.
2. **History keeps row-level recovery but not the maintenance zone.** The existing guarded, identity-announced actions target the same failed operation id in either view. Acting beside the inspected row avoids switching mode and finding it again ([NAV-19] **Keep related work adjacent**, *About Face, ch. 12*). A History title adds no capability restriction. Only one list is mounted per view. Bulk maintenance belongs only to Needs attention › Failed; confirmation/capability/age and terminal guards remain.
3. **Mount, don't hide.** The timeline section calls its query only when mounted. That guarantees no failed timeline in the default view without adding an `enabled` option to the shared hook.
4. **GPU copy follows returned evidence.** `draftCount` (`run.completed ?? 0`) is the returned-results signal and carries no tier proof. Copy therefore never says "CPU". DONE review additionally requires an available href. G1's bounded producer derivation feeds both the toast and the unchanged reserved `ActivityStatusStrip`; `PendingDescribeRecovery` consumes cancel/retry only. No cooldown, budget, status schema or composition-file change is granted. CPU provenance (`fallback_reason`, `provisional_cpu` tier) lives in run and item data, which the review surfaces already show.
5. **`endpoint_unconfigured` copy goes where the envelope can arrive.** The status schema stays unchanged. Telling unknown telemetry apart from configuration needs a status-contract field, which is deferred to a separate task.
6. **Exact coordinates, before dedup, by shared key.** `identityGroupKey` is shared by grouping and evidence, so the two cannot drift. Reading before dedup is necessary because dedup can drop the very observation that repeats. Exact equality is an equivalence, so it cannot chain borderline matches. A missed near-duplicate is preferable to the rejected similarity-chain alternative ([GRPH-18] **Never trust the transitive closure of a raw similarity threshold**, *Introduction to Information Retrieval, § 17.2*). No person classification is forced.
7. **Text evidence, not crops.** Cached corpus research reports boxes that overhang the listed image size, so crop geometry and coordinate transforms are unverified. `ClusterPreview` may show a representative from another photo. Text references show the actual matching observation without relying on either ([VIZ-23] **Show the evidence path**, *Richard Feynman's Mental Models, ch. 5* + *Envisioning Information, ch. 4*).
8. **Exact references stay inside the disclosure.**
   - `js/admin/__tests__/banned-vocabulary.test.tsx` keeps rendered page text free of UUIDs and review surfaces free of "cluster"/"identity" words.
   - The disclosure body is where verbatim references belong. Summaries, headings, accessible names and toasts carry none.
   - Visible wording uses "face group" and "face record".
   - The page sweep's fixture renders `identities: []`, so the disclosure is never part of that sweep.
9. **Loaded pool only.** The pool line counts unique loaded face records and eligible ones. No title, hash, completeness or corpus total field exists, so none is implied. This is the text comparison's explicit accounting contract. The representative thumbnail is context only; if a selected image is later offered as consequential evidence, [VIZ-41] **Reveal the image-selection pool**, *Visual Explanations, ch. 1*, would require its inspectable selection pool. No such image is introduced here.

## Deferred, with boundaries

- **Status-contract configuration or capability field** on `GpuStatusResponse`: a backend contract change for a separate task.
- **Copy for other scene unavailable reasons** (`endpoint_not_private`, `endpoint_resolution_pending`, `state_missing`, `state_stale`, `degraded`, `operator_stop`, `auth_rejected`): they keep the generic fallback.
- **`degradedNotice(count)` ignores its count** in `ActivityStatusStrip` idle copy. The strip is WBTRUST-5-reserved, so this is a follow-up for that owner.
- **Worker warm-up short-circuit, boot-time settings validation, and fallback provenance in a typed field**: backend items outside UXREC slices.
- **Identity**: corpus diagnosis of the supplied same-person crops, cross-photo duplicate content (no content-hash field), detector or recall repair, and any merge flow. These need a separately granted CORPUS probe or other tasks. The operator's identification of the supplied crops as one person is supplied ground truth. No new identification is made.
- **Overlay title "Failed Sync Queue"** (`pages/WorkbenchPage.tsx`): owned by WBTRUST-5.

Inherited structural map critique stays typed and outside these slices: HAI-01 on `workbench-operator-loop` `z-review-suggestions-group-card` and INT-07 on the `describe-gpu-tier` dashboard `describe-single` action. No `evidence_linked` or `preview_required` field may be set to silence them without evidence.

Source-known visible-projection drift in unrelated sibling maps is outside scope. The joined gate uses scoped parity for the three UXREC maps; it must not rebaseline those unrelated artifacts. Documentation checks here establish neither map-render parity nor browser or runtime acceptance.

## Pinned authority

Canon v0.26.2 is pinned at `/home/gate/heuristics-canon-v0.26.2` (project <https://github.com/darce/heuristics-canon>), and all 53 manifest digests match. The routed UI, AI-review and planning rows were checked whole, including triggers, exemptions and sources. The plan records the matching-card pass, including inert candidates. CARD-03 `designed-unknown` checks the zero/empty/partial states; CARD-08 `falsification-disconfirmers` and CARD-11 `measurement-integrity` check future RED/GREEN proof; CARD-12 `perceived-enforced-boundaries` and Principle 10's security/architecture siblings check each implied grouping against an enforced cut:

- The view toggles match mounted queries.
- The disclosure matches unchanged data and action targets.
- The toast copy and review affordance match returned run data and an available destination.
- The lanes match single-writer file ownership.

| Decision | Stable row authority |
| --- | --- |
| No CPU or result claim before evidence | [HAI-05] **Imperceptible AI is not ethical**, `lexicons/interaction-ux.md#hai-05`, *Human-Centered AI* |
| Run status, next step and existing stop/retry stay visible | [INT-10] **Status–predict–stop**, `#int-10`, *Human-Centered AI* |
| Backlog maintenance and audit navigation have separate end states | [INT-19] **One outcome per interaction**, `#int-19`, *Microinteractions, ch. 1* + *Microinteractions, ch. 3* |
| Guarded failed-row recovery stays beside the row being inspected | [NAV-19] **Keep related work adjacent**, `#nav-19`, *About Face, ch. 12* |
| Messages name the resulting state | [INT-22] **Explain the result**, `#int-22`, *Microinteractions, ch. 4* |
| Smallest signal; disclosure collapsed; no new banner | [PERC-10] **Least useful feedback**, `#perc-10`, *Microinteractions, ch. 4* |
| A review action only when results exist; thumbnail non-interactive | [INT-01] **Affordance match**, `#int-01`, *Designing Interfaces, 3rd ed.* |
| Data, comparison basis, mechanism limit and alternatives inspectable | [VIZ-23] **Show the evidence path**, `#viz-23`, *Richard Feynman's Mental Models, ch. 5* + *Envisioning Information, ch. 4* |
| Conditional on a selected image being offered as consequential evidence; the current thumbnail remains context only | [VIZ-41] **Reveal the image-selection pool**, `#viz-41`, *Visual Explanations, ch. 1*; no new image-evidence trigger here |
| No transitive similarity closure or merge | [GRPH-18] **Never trust the transitive closure of a raw similarity threshold**, `lexicons/graph-theory.md#grph-18`, *Introduction to Information Retrieval, § 17.2* |
| Unknown, empty, error and loading designed per state | [RLSE-04] **Undesigned state is a bug**, `lexicons/engineering.md#rlse-04`, bootstrap (practice label) |
| Content-and-frame fit for 90/40-column layouts | [LAY-24] **Content-and-frame grid**, `lexicons/design-aesthetics.md#lay-24`, *Thinking with Type, ch. 3* |
| Keyboard; status; reflow; confirmed discard | [A11Y-11] **Keyboard walk (2.1.1/2.1.2/2.4.3/2.4.7)**, *Web Content Accessibility Guidelines 2.2, SC 2.1.1*; [A11Y-21] **Announce status (4.1.3)**, *Web Content Accessibility Guidelines 2.2, SC 4.1.3*; [A11Y-08] **Reflow and resize (1.4.4/1.4.10/1.4.12)**, *Web Content Accessibility Guidelines 2.2, SC 1.4.4*; [A11Y-18] **Reversible, checked, or confirmed (3.3.4)**, *Web Content Accessibility Guidelines 2.2, SC 3.3.4*. All in `lexicons/accessibility.md`. |

The sketches use actual copy in measured 90/40-column frames (LAY-24), not arbitrary marks requiring a proportional-thumbnail citation. LAY-27's repeated-print-page and LAY-23's column-count triggers are absent. A11Y-12's custom-widget and CAL-02's forced-classification triggers are also absent; native controls and deterministic abstention stay required without those citations. GRPH-18 bounds the rejected similarity-chaining alternative; VIZ-23 supports the text comparison, while VIZ-41 applies only if image selection becomes consequential evidence. No crop or image rule is added. Planning-side rules (GRPH-01, GRPH-09, TEAM-01, TEST-06) are applied in the task plan.

## FIR prior research boundary

`benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` (sections `#v13-caption`, `#v12`, `#v12-space`, `#v12-config`) is dated research. It is not current service readiness and not rule authority.

- **Caption comparator**: Qwen3-VL-30B-A3B-Instruct Q4_K_M.
- **SFace**: an isolated 128D space with L2/cosine.
- **AuraFace-v1**: `glintr100.onnx`, revision `af6d057c9b0ec4071d4c49c80e3539258798b609`. 512D raw output, ArcFace-112 alignment, RGB NCHW `(pixel-127.5)/127.5`, then in-house L2 normalization. Runtime identity includes `cv5.0.0/ort1.29`.
- **Namespaces**: weights, preprocessing, normalization, metric, runtime and store each define a separate namespace. Equal dimension never licenses cross-space comparison.
- **Scope**: none of this establishes activation, enrollment or description readiness. None of it feeds the UXREC slices, which use no similarity, embedding or threshold.
