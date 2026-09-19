# UX Map — workbench review queue

**Product:** Alt Context operator workbench

**Source fixture:** `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx`, and the workbench components cited below. The SPA mounts this surface at `/workbench`; the description-history route redirects into the same draft-filtered queue (`apps/prototype-wp-alt-context/js/admin/App.tsx:29-90`, `apps/prototype-wp-alt-context/js/admin/App.tsx:93-123`).

## Goals

- Give unnamed face groups one review home. The roster explicitly sends unnamed groups to the Review Queue, and its primary CTA links back to the workbench queue (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:188-239`).
- Keep review suggestions MECE by kind and confidence band, with one visible position, one selection tray, and one review action (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1198-1342`).
- Keep generated descriptions in the media queue until the operator reviews each draft. The `hasDraft` filter and optional `run` filter are the queue’s deep-link contract (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:63-80`), while each draft exposes explicit Accept, Edit, Save, and Dismiss actions (`apps/prototype-wp-alt-context/js/admin/pages/workbench/QueueDraftCell.tsx:20-23`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/QueueDraftCell.tsx:73-101`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/QueueDraftCell.tsx:113-211`).
- Keep long-running work observable and interruptible: the persistent activity strip owns status, progress, ETA, Details, Retry, Review drafts, and Cancel; the cancel path confirms before stopping work (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx:111-209`).

## Jobs

| Job | Entry | Successful outcome |
| --- | --- | --- |
| Scan and identify media | Scan tab | The scan timeline and review queue expose the resulting identity groups; the scan CTA and timeline remain available below the queue (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx:289-318`). |
| Review an identity suggestion | Review Queue | The operator filters, selects, opens a card, and reviews or labels it; bulk review has approval, progress, Undo, and retry branches (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:921-975`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1325-1488`). |
| Describe selected media | Media queue footer | A run exposes its phase and terminal result, then links to the draft-filtered queue (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:210-336`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:982-1041`). |
| Recover a scan or prior job | Advanced drawer | The operator can inspect job history, cluster the latest results, retry, select a recent job, or open the roster (`apps/prototype-wp-alt-context/js/admin/pages/workbench/AdvancedDrawer.tsx:7-85`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:267-409`). |

## Screens

| Screen or region | Route / placement | Primary purpose |
| --- | --- | --- |
| Workbench review queue | `/workbench`, Scan tab | Review identity suggestions and keep the media queue available beside them (`apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx:130-232`). |
| Review these faces | In the Scan tab after a queue card is opened | Inspect the faces in one group, remove an incorrect face with confirmation, and return to the queue (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ClusterReviewPanel.tsx:119-248`). |
| Activity status strip | Persistent workbench chrome | Show the single activity status and its next action while scans or describe runs are active or terminal (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx:111-209`). |
| Advanced: jobs & recovery | Non-modal drawer from the workbench | Keep history, clustering, and recovery controls available without blocking the queue (`apps/prototype-wp-alt-context/js/admin/pages/workbench/AdvancedDrawer.tsx:7-85`). |
| Conflict Inbox / Failed Sync Queue | Workbench overlay host | Provide the existing recovery overlays and a Close action without changing the queue’s ownership of review work (`apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx:143-156`). |

### Workbench review queue

The workbench is a two-pane shell: the control pane contains the Scan tab and the library pane contains the media selection queue (`apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx:189-232`). The Scan tab names the review region, keeps a stable live announcement, and selects one of the review queue, review panel, or labeling panel states (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx:220-287`).

```text
+-- Review Queue / Workbench ------------------------------------------------+
| Scan | Confirm | Review                 [sync status] [Advanced]            |
|                                                                            |
| Activity strip: status · progress · ETA · [Details] [Retry] [Cancel]       |
|                                                                            |
| Review Suggestions                                                         |
| [kind filters] [confidence bands]       [Previous] [position] [Next]       |
| [suggestion cards: close match / possible duplicate / suggested name /    |
|  unlabeled group]                                                         |
| [selected count] [Review selection]                                       |
|                                                                            |
| Media queue: [search] [status] [Has draft] [run filter]                  |
| [select] [preview] [details + identity groups + draft] [tags]            |
| footer: [pagination] [Describe selected / Cancel / Review drafts]          |
+----------------------------------------------------------------------------+
```

The activity strip states are `idle`, `scanning`, `warming`, `describing`, `done`, and `failed`; its GPU vocabulary also distinguishes unknown, stopped, starting, warming, ready, and degraded (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx:25-105`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/gpuStatePresentation.ts:40-121`). Its live region exposes progress only for the waiting states and keeps terminal actions visible (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx:122-191`).

The review queue’s implemented data states are loading, service-not-configured, endpoint error, top-unlabeled error, filtered empty, all caught up, missing-face-data repair, and an active suggestion card (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1168-1234`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1527-1617`). Kind filters and confidence bands intersect rather than creating a second queue, and the position region reports a real position or an unavailable position while the queue is repairing or filtered (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1236-1323`).

The media queue states are initial loading, service error with Retry, no media, no search match, no status match, no draft match, and a populated row list (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelectionTableBody.tsx:105-198`). A row can show a thumbnail, media details, identity groups, tags, and an inline draft cell; its single polite region is reserved for row-level correction feedback (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelectionTableBody.tsx:235-410`).

### Review these faces

```text
+-- Review these faces ------------------------------------------------------+
| [← Back to Review Suggestions]                                             |
|                                                                            |
| face 1     face 2     face 3     ...                                      |
| [remove]   [remove]   [remove]                                             |
| [Show all faces]                                                           |
|                                                                            |
| [Remove face confirmation]                                                 |
+----------------------------------------------------------------------------+
```

The panel expands the selected group, reports member-query loading or error, and renders the face grid. Removing a face requires a confirmation dialog; Back returns to Review Suggestions (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx:119-248`).

### Activity and recovery

The status strip is the persistent status surface. Toasts are only edge feedback: they are suppressed while the strip is mounted, deduplicated per run and edge, and carry persistent Review, Back to run, or Retry actions for the relevant terminal transition (`apps/prototype-wp-alt-context/js/admin/hooks/useGpuStateToasts.ts:48-169`). The strip’s Cancel button is the only destructive run action and opens a confirm dialog; a cancelled run leaves completed drafts intact (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx:161-209`).

The non-modal Advanced drawer contains the Confirm panel and Recent Jobs panel. Confirm exposes the latest job, clustering progress, Retry clustering, and Open roster; Recent Jobs distinguishes unavailable history, browser-local fallback, an empty history, and selectable jobs (`apps/prototype-wp-alt-context/js/admin/pages/workbench/AdvancedDrawer.tsx:13-85`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:267-409`).

## Actions

| Surface | Action | Result, next step, or stop |
| --- | --- | --- |
| Review Suggestions | Toggle kind or confidence filters; Clear filters; Previous / Next | The filtered queue and position update in place; an empty filtered result offers Clear filters (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:921-975`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1527-1578`). |
| Review Suggestions | Select cards; Review selection | Opens the selection review surface and keeps approval/truncation gates visible before commit (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1325-1434`). |
| Suggestion card | Review or label the current suggestion | Opens the face review or labeling path; successful person naming offers View in roster (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1617-1790`). |
| Review these faces | Remove face; Back to Review Suggestions | Remove is confirmed before mutation; Back returns to the queue (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx:119-248`). |
| Media queue | Search, status filter, Has draft, optional run filter, pagination | Changes the visible media set; draft/run filter empty states offer Show all media or Clear run filter (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:399-533`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelectionTableBody.tsx:115-198`). |
| Draft cell | Accept, Edit draft, Save alt text, Cancel edit, Dismiss | The operator explicitly commits or discards one draft; no bulk auto-apply is offered (`apps/prototype-wp-alt-context/js/admin/pages/workbench/QueueDraftCell.tsx:20-23`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/QueueDraftCell.tsx:73-211`). |
| Media footer | Describe selected | Holds for offline, settings-loading, identity-in-progress, or zero-selection states; otherwise it either starts describe directly or identifies people first and then starts describe (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:210-336`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:583-669`). |
| Active run | Cancel run, Retry polling, Details | Cancel is confirmed; Retry resumes polling; Details opens the non-modal run drawer (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx:161-209`). |
| Terminal run | Review drafts, Dismiss, Retry | Review drafts lands on `hasDraft=1` (and preserves a valid `run`); Dismiss removes terminal chrome; retry is available for retryable failures (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:63-80`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:1010-1041`). |
| Confirm / Recent Jobs | Cluster latest job, Retry clustering, Open roster, select a job, Clear local history, Run a scan | Recovery stays in the Advanced drawer; unavailable history has a Run a scan escape hatch (`apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:267-409`). |

## Flows

### Review an identity suggestion

1. The operator enters the Scan tab and chooses a kind or confidence band; filters intersect in one Review Suggestions list (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx:220-287`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1236-1323`).
2. The operator selects one or more cards and chooses Review selection, or opens the current card. Approval and truncation checks remain visible before a bulk mutation (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1325-1434`).
3. The operator reviews the faces, removes an incorrect face only after confirmation, or returns to the queue (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx:119-248`).
4. A successful person-label path offers View in roster; unnamed groups otherwise remain owned by the Review Queue (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1491-1524`, `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:188-239`).

### Describe, then review drafts

1. The operator selects media rows. When recognition is enabled, the workbench identifies people first; when recognition is off or unavailable, it proceeds directly to describe. Offline, unresolved settings, identification, and zero selection hold the action (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:210-336`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:583-757`).
2. The strip reports queued, warming, describing, stalled, terminal, or failed state with the available ETA, Retry, Cancel, Details, and Review actions (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:876-1095`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx:122-209`).
3. On completion, the operator follows Review drafts to the `hasDraft` queue. Each row presents a draft disclosure and requires Accept, Edit/Save, or Dismiss before the media record changes (`apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:1010-1041`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/QueueDraftCell.tsx:113-211`).

### Recover a run

1. The operator opens Details without leaving the queue; the drawer is non-modal and restores focus when closed (`apps/prototype-wp-alt-context/js/admin/pages/workbench/AdvancedDrawer.tsx:13-85`).
2. The operator selects a recent job, retries a stream or clustering step, or opens the roster. If history is unavailable, the drawer offers Run a scan (`apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:267-409`).
3. If the run is still active, Cancel opens the explicit confirmation and stops the appropriate people-identification or describe operation; finished drafts remain available (`apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx:193-209`).

### Wire and authority boundaries

The map keeps the frozen wave contract additive: a warm-up timeout is a failed/retryable run while CPU drafts remain reviewable, `starting` is a visible GPU presentation, thumbnails remain row data, and activity status comes from the single `useActivityStatus()` authority rather than a second poller (`docs/tasks/v0.5.0/GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md:69-91`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/gpuStatePresentation.ts:84-145`, `apps/prototype-wp-alt-context/js/admin/hooks/useGpuStateToasts.ts:48-169`). Unknown unavailable reasons stay in the existing neutral service-error/unavailable branches; this map does not invent a second queue or a new wire state (`docs/tasks/v0.5.0/GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md:69-78`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx:1527-1578`).
