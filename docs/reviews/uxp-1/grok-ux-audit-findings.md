# UXP-1 Grok UX audit findings

**Lane:** `uxp-1-grok-audit` · **Task:** `UXP-1` · **Scope:** read-only sweep of `apps/prototype-wp-alt-context`  
**Code roots:** React admin at `js/admin/**` (brief said `js/src/**` — path does not exist; all anchors use real tree) · PHP REST at `src/**`  
**Heuristics:** vendored IDs from `docs/reviews/uxp-1/lexicons/{accessibility,design-aesthetics,writing,engineering}.md`; strategy twin at `docs/strategy/engineering-heuristics.md` (brief path `docs/workbay/rules/engineering-heuristics.md` is absent)

---

## A. Issue-to-code mapping

### 1. 429 storm — job / name-suggestions / identity-suggestions polling

| Surface | Owning code | Behavior |
| --- | --- | --- |
| Job poll | `js/admin/hooks/useRecognitionHooks.ts` `useScanStatus` L52–64, `useMultiScanStatus` L72–88, `useBatchRunStatus` L90–102; interval helpers L32–39 | Polls every **1500ms** while `status` is `running`/`pending` or phase is `awaiting_projection` (`getJobRefetchInterval`). `retry` allows up to **3** failures unless message includes `404`. **No 429-specific stop, no Retry-After, no terminal-on-rate-limit.** Global defaults in `js/admin/App.tsx` L15–22 set `retry: 1` and exponential `retryDelay` (1s→30s) but job hooks override `retry` without special-casing 429. |
| Job HTTP | `js/admin/api/recognition/scanApi.ts` `fetchScanStatus` L130–137 → `GET …/recognition/jobs/{id}`; PHP `src/api/class-analysis-jobs-controller.php` L172–179 | Proxies recognition job status to remote service. |
| Name suggestions queue | `js/admin/pages/workbench/identity-clusters/useSuggestionReviewQueries.ts` L34–39; API `identityQueriesApi.ts` `fetchPendingNameSuggestions` L114–140 → `GET /acx/v1/recognition/suggestions/name` | **`refetchInterval: false`, `retry: false`** — does **not** continuous-poll. Brief claim of endless name-queue polling is **overstated** for this hook; storm risk is mount storms + concurrent job polls + inline identity queries. |
| Identity suggestions `top_k=1` | `js/admin/pages/workbench/identity-clusters/InlineSuggestionPrompt.tsx` L39–44; API `identityQueriesApi.ts` `fetchIdentitySuggestions` L68–78 (`top_k` query param); PHP `src/api/class-suggestions-controller.php` L28– (identity suggestions route) | One query per visible unlabeled identity card; default RQ retry (1) + global backoff; **no 429 handling**; N cards ⇒ N concurrent GETs. |
| Cluster label typeahead suggestions | `useClusterSuggestionsLoader.ts` L63–68 (`top_k` via `fetchIdentitySuggestions(…, 5)`) | Mounts when labeling; staleTime 30s; default retry. |
| Rate limit producer | PHP proxy `src/api/class-abstract-recognition-proxy-controller.php` (forwards remote status including 4xx); overload helper treats **503** specially (`is_backend_overloaded` L270–272, `backend_overloaded_response` L292–306 with Retry-After). **No first-class 429 budget in WP plugin** for recognition job GETs — 429s come from **remote recognition service** (or shared proxy), while client keeps short-interval polls. Outbox treats 429 as retryable (`class-outbox-dispatcher.php` L281). Describe path emits local 429 (`class-describe-media-service.php` L129). |

**Note:** Active-job 1.5s polling + multi-job `useQueries` + multi-card identity suggestions amplify load; React Query will re-attempt failed polls (up to retry budget) without interpreting 429 as “stop / back off longer.”

### 2. “Working offline / Waiting for service” banner

| Piece | Location | Behavior |
| --- | --- | --- |
| App banner | `js/admin/pages/workbench/DegradedModeBanner.tsx` L19–67 | Renders when `shouldShowDegradedBanner(health)`; offline title from `getDegradedBannerTitle` → **“Working offline”**. |
| Offline predicate | `js/admin/pages/workbench/degradedModeBannerLogic.ts` L14–15, L54–58 | **`isSyncOffline` = `health.breaker.state === 'open'` only** — not a remote OCI VM health ping, not job/GPU status. Comments L7–13 explicitly reject using `last_pull.ok` as offline (false positives). |
| Health poll | `js/admin/hooks/useSyncHealth.ts` L6–15; API `syncApi.ts` `fetchSyncHealth`; PHP `src/api/class-sync-health-controller.php` L42–88 | **`GET /acx/v1/recognition/sync/health` every 15s.** Response builds **local** breaker state from WordPress transient (`get_transient($circuit_key)`), outbox counts, conflict counts, last pull latch — **does not HTTP-probe the remote VM** on this path. |
| “Waiting for service…” copy | `js/admin/pages/workbench/syncVocabulary.ts` L21, L50; used by `syncPresentation.ts` offline/results-error headlines | Sync strip headline when presentation resolves offline / results error — same breaker-driven story, different surface. |
| Gating | `js/admin/hooks/useSyncOffline.ts` L10–13; `useRemoteActionGate.ts` | Mirrors breaker open for remote-compute CTA disable. |

### 3. Bulk-accept panel (confidence slider)

| Piece | Location | Behavior |
| --- | --- | --- |
| UI | `js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx` L306–365 | Section “Bulk accept”; range input `min=0 max=1 step=0.05`; three buttons: assignments / names / merges with `min_confidence: bulkConfidenceThreshold`. |
| Mutation | `useSuggestionReviewMutations.ts` L121+; API `identityActionsApi.ts` `bulkAcceptSuggestions` L65–72 | `POST` bulk-accept body `{ suggestion_type, min_confidence }`. |
| PHP | `src/api/class-suggestions-controller.php` L166–176, L406–436 | Proxies to remote `/recognition/suggestions/bulk-accept` with tenant_id, suggestion_type, min_confidence. |

**Threshold semantics:** Filters **existing pending suggestions** of the chosen type by confidence at accept time — **retroactive accept of queued suggestions**, not a knob that changes next clustering membership thresholds. Clustering similarity thresholds live elsewhere (e.g. cluster debug metrics / backend config), not this slider.

### 4. Media table disappears after clustering / findings appear

| Piece | Location | Behavior |
| --- | --- | --- |
| Collapse condition | `js/admin/pages/workbench/ScanTabContent.tsx` L43–54, L114 | `isMediaCollapsed = findings.hasFindings && !userExpandedMedia && !loading/error/unavailable`. When workbench findings appear (typical after scan/cluster produces reviewable work), full table swaps to summary. |
| Collapsed UI | `MediaSelection.tsx` L94–96 → `MediaSummaryBar.tsx` | Summary counts + “Show media table”; expand sets `userExpandedMedia=true`. |

Collapse is driven by **findings presence**, not a dedicated “job completed” flag — clustering completion that populates findings triggers the same path.

### 5. “Analyze selected media” button placement

| Piece | Location | Behavior |
| --- | --- | --- |
| CTA | `js/admin/pages/workbench/MediaAnalyzeCta.tsx` L28–53 | Button label “Analyze selected media”; disabled when scanning / none selected / offline gate. |
| Placement | Rendered from `MediaSelection.tsx` footer (`acx-media-selection__analyze` / table footer region L140+) under the media table | Only lives at **bottom of the media selection block**. When collapsed (`MediaSummaryBar`), **analyze CTA is hidden** — expand required. No sticky/header twin. |

### 6. “Advanced: jobs & recovery” + always-visible clustering explainer

| Piece | Location | Behavior |
| --- | --- | --- |
| Drawer | `js/admin/pages/workbench/AdvancedDrawer.tsx` L7, L53–85 | Trigger “Advanced: jobs & recovery”; panel mounts `ConfirmTabContent` when open; Esc + focus management. |
| Explainer | `js/admin/pages/workbench/ConfirmTabContent.tsx` L15–23 | **“What is Clustering?”** help card is **always rendered** at top of advanced content (not collapsible). |
| Body | Confirm panel + recent jobs via `Panels.tsx` (`ConfirmPanel`, `RecentJobsPanel`) | Recovery/cluster-now controls sit under the explainer. |

### 7. Pin / “Pinned” toggle on avatar

| Piece | Location | Behavior |
| --- | --- | --- |
| Control | `js/admin/pages/workbench/identity-clusters/ClusterPreview.tsx` L58–70 | WordPress `button button-small` with classes `acx-identity-cluster__pin-toggle` / `--pinned`; text “Pin” / “Pinned”; sits **inside** `.acx-identity-cluster__preview` beside the 40×40 thumbnail. |
| Mutation | `useClusterActionMutations.ts` pin mutation; API `clusterApiMutations.ts` `pinRepresentative` | POSTs pin state for representative. |
| Styles | `_identity-cluster-list.scss` `__preview` L13–18 (`position: relative`); `_workbench.scss` `__preview` ~L444–446 fixed 40×40 | **No rules for `__pin-toggle` anywhere in styles/** (grep only hits TSX). Unstyled WP button in a 40×40 relative box ⇒ overlaps avatar / count badge (issue root). |

### 8. “Name this person” search / typeahead data source

| Piece | Location | Behavior |
| --- | --- | --- |
| Panel title + combobox | `ClusterLabelingPanel.tsx` L210, L250–267 | Combobox options from **`useRosterEntries()`** → `persons.map` L110–114 (`id`/`name` of local roster people). |
| Duplicate / merge lookup | `findClusterByLabel` L138–162 | Separate path: `listRecognitionClusters({ search, labeled_only: true })` — **labeled clusters**, not persons table. |
| Related typeahead | `useClusterSuggestionsLoader.ts` L70–82 | Debounced label search against **clusters** (`labeled_only: true`); identity similarity suggestions via `fetchIdentitySuggestions`. |

**Answer:** Primary “Search people…” options are **curated roster persons** (`GET` roster entries / `acx_persons` projection). Cluster label search is an additional source for merge-on-duplicate, not the combobox list itself.

### 9. Roster duplicate person entries (same label twice)

| Piece | Location | Behavior |
| --- | --- | --- |
| List | `useRosterHooks.ts` `useRosterEntries` L13–18; PHP `class-api.php` `get_roster_entries` L331–333 → `RosterEntryProjectionRepository::list_entries` | Renders **one row per `acx_persons` row**, ordered by name — **no client-side merge/dedupe by label**. |
| Create guard | `class-api.php` `create_person` ~L495–520 | Exact-match `WHERE name = %s` → 409 if exists. |
| Other ingress | Cluster commit / label paths can create or bind persons; collation may allow case variants; remote projection/sync can reintroduce rows if history diverged |

**Answer:** UI groups by person id, not display label. Duplicate “Flaxen Yarrow” rows imply **two person rows** (or projection rows), not a roster grouping bug that fails to collapse equals. No merge-on-display logic exists.

### 10. Roster “Entries” vs “Clusters” tabs

| Tab | Component | Data source |
| --- | --- | --- |
| Entries | `RosterPage.tsx` L264–269 → `RosterEntriesSection` + optional `PersonWorkspacePanel` | `useRosterEntries` → `GET /acx/v1/roster/entries` → **local** `acx_persons` projection (`RosterEntryProjectionRepository`). Empty zero-state when `entries.length === 0` (`RosterEntriesSection.tsx` L163–284). |
| Clusters | `RosterPage.tsx` L272+ → `RosterClustersTab` | `useRecognitionClusters` → recognition **cluster list** proxy (`useRecognitionHooks.ts` L134–139, 30s poll). |

Tabs defined in `rosterRoute.ts` L5–6 (`Entries` / `Clusters`). Entries can render empty while Clusters is populated when **local person projection is empty** but remote/local cluster mirror still has groups — different stores, not a shared filter bug.

### 11. Dashboard stale counts + retention posture

| Metric | Source | Notes |
| --- | --- | --- |
| People / Assigned / Pending Review | `DashboardPage.tsx` L139–165; `useIdentityStats.ts` → `fetchDashboardStats` → PHP `class-api.php` `get_dashboard_stats` L944–988 | Counts from **local WP tables**: `acx_persons` COUNT; `acx_clusters` with `person_id IS NOT NULL`; pending = `person_id IS NULL AND curation_state = 'uncurated'`. Can read 0/0/N while remote workbench shows different inventory if projection lag. |
| Retention card | `DashboardPage.tsx` L226–265 | Title **“Retention posture”**; if `!retentionPolicy` → **“Retention status is unavailable right now.”** |
| Retention data | `useRetentionStatus.ts` L28–33; `retentionApi.ts` `fetchRetentionStatus` L69–78 | If endpoint missing from boot config → `{ available: false, policy: null }` without error — surfaces unavailable copy. |

### 12. Workbench media table collapsed state not persisted

| Piece | Location | Behavior |
| --- | --- | --- |
| State | `ScanTabContent.tsx` L43: `useState(false)` for `userExpandedMedia` | In-memory only. Navigation remount resets; findings re-collapse on new findings edge (effect L46–51). |
| Contrast | Merge queue uses `localStorage` (`CollapsibleMergeQueue.tsx`); scroll uses `sessionStorage` (`useScrollRestoration.ts`) | Media expand intentionally **not** persisted. |

### 13. Sync status banner strings

| String | Source | State machine |
| --- | --- | --- |
| “Local changes are waiting to sync.” / “Queued” | `syncVocabulary.ts` L29–31; `degradedModeBannerLogic.ts` L38–39 | `legacySyncHealth === 'queued'` via `buildSyncPresentation` / dashboard summary. |
| “Delta sync” | `syncVocabulary.ts` L102; `SyncStatusIndicator.tsx` L227–240 via `formatSyncModeLabel` | Meta badge from `data.sync_mode`. |
| “Pending changes: %d” | `syncVocabulary.ts` L57; `SyncStatusIndicator.tsx` L243–249 | When `pending_curation_operations > 0`. |
| Presentation core | `syncPresentation.ts` `buildSyncPresentation` + `SYNC_PRESENTATION_STATUS` | Combines pipeline phase, projection state, legacy `sync_health`, breaker envelope, trigger mutation flags into headline/badge/detail/action. |
| Data | `useSyncStatus` (120s poll) + `useSyncHealth` (15s) + `useSyncTrigger` | Strip in `SyncStatusIndicator.tsx` L177+. |

---

## B. Polling/retry inventory

Global defaults (`App.tsx` L15–22): queries `retry: 1`, `retryDelay` exponential capped 30s, `refetchOnWindowFocus: false`.

| Hook / site | Query key (pattern) | Endpoint / effect | refetchInterval | retry | enabled | 429 / failure backoff |
| --- | --- | --- | --- | --- | --- | --- |
| `useScanStatus` | `queryKeys.jobs.status(jobId)` | `GET /acx/v1/recognition/jobs/{id}` | 1500ms while active / awaiting_projection; else false | &lt;3 unless 404 | jobId set | **No 429 stop**; interval can resume after success; default delay only on RQ retries |
| `useMultiScanStatus` | per job status key | same | same | same | activeJobIds | Same multi-poller risk |
| `useBatchRunStatus` | `jobs.batchRun(runId)` | batch-run status | 1500ms until `terminal_state` | &lt;3 unless 404 | runId set | Same |
| `useRecognitionClusters` | `clusters.list(params)` | cluster list proxy | **30_000** fixed | default (1) | always when used | Continuous; no 429 policy |
| `useRecognitionCluster` | `clusters.detail` | cluster detail | none (staleTime 30s) | default | clusterId | OK |
| `useMediaIdentities` | `media.identitiesByIds` | media identities | **3000** while any `clustering_pending` | **false** | mediaIds | Stops on error; no 429 special-case |
| `useSyncHealth` | `sync.health` | `GET …/sync/health` | **15_000** forever | default | always | Unbounded poll; local-only payload |
| `useSyncStatus` | `sync.status` | sync status | **120_000** | default | always | Slow poll |
| `useRosterEntries` | `roster.entries` | roster entries | **60_000** | default | always | Continuous |
| `useIdentityStats` | `dashboard.stats` | dashboard stats | none (stale 30s, refetch on focus) | default | dashboard | OK |
| `useRetentionStatus` | `retention.status` | retention status | none (stale 60s) | default | always | Soft-fail if endpoint missing |
| `useExportJobStatus` | `retention.exportJob` | export job | 2000 until completed/failed | default | jobId | Has terminal stop |
| `useDescribeRunProgress` | `['bulkDescribeRun', runId]` | describe run | 2000 until terminal; stops on error | 3 + exp delay ≤8s | runId | Better than job pollers |
| `useSuggestionReviewQueries` assignment/merge/name | `suggestions.pending|merge|name` | suggestion queues | **false** | **false** | always when panel mounted | No poll; manual refetch |
| `topUnlabeledQuery` | `clusters.topUnlabeled` | top unlabeled | none (stale 60s, refetchOnMount always) | default | tenantId | Mount storms possible |
| `InlineSuggestionPrompt` | `suggestions.inlineFor(id)` | identity suggestions `top_k=1` | none | default | identityId | **N concurrent** cards |
| `useClusterSuggestionsLoader` | identity + labelSearch | suggestions + clusters search | none | default | panel open | Debounced search |
| `useWorkbenchMedia` media/detail | workbench page / details | WP media list | none | default | enabled | Prefetches next page once |
| `useJobProgressStream` | n/a | SSE/stream helpers | `setInterval` 1s stall clock | manual retry API | active stream | Local stall timer only |
| `useDescribeRunProgress` stall | n/a | local | `setInterval` 1s | n/a | while polling | Local |
| `useJobCoordination` | n/a | tab heartbeat | `setInterval` heartbeats | n/a | multi-tab | Not HTTP |

**Flagged (no 429 backoff and/or no terminal stop while hot):** job status pollers (1.5s), batch run poller, media identities 3s while pending, sync health 15s forever, roster 60s forever, clusters list 30s forever, multi-card inline suggestions.

---

## C. UI copy inventory

| String | File:line (approx) | Lexicon note |
| --- | --- | --- |
| Working offline | `degradedModeBannerLogic.ts:58`, `syncVocabulary.ts:24` | Accurate if breaker-open; users may read as “no network” ([WRIT-06] consistency with “Waiting for service…”) |
| Waiting for service… | `syncVocabulary.ts:21,50` | Jargon-light; still vague about *what* service ([WRIT-03] abstract) |
| Local changes are waiting to sync. / Queued | `syncVocabulary.ts:29–31` | “Queued” is ops jargon for some admins ([WRIT-02]/product plain-language tension) |
| Delta sync / Full sync | `syncVocabulary.ts:102–103` | **Implementation jargon** on primary strip ([WRIT-27] invented/ops label; design LAY-10 unchosen detail) |
| Pending changes: %d | `syncVocabulary.ts:57` | OK if “changes” = curation ops; else ambiguous |
| Retention posture | `DashboardPage.tsx:228` | **Enterprise jargon** for non-compliance users ([WRIT-03]) |
| Retention status is unavailable right now. | `DashboardPage.tsx:230` | Clear; pairs poorly with “posture” heading |
| Bulk accept / Bulk accept assignments\|names\|merges | `SuggestionReviewPanel.tsx:307–362` | “assignments/merges” are domain jargon ([WRIT-06] — keep terms but define once) |
| Minimum confidence | `SuggestionReviewPanel.tsx:312` | Technical; no plain “how sure” gloss |
| What is Clustering? | `ConfirmTabContent.tsx:16` | Capitalized product term; explainer body uses “embeddings” ([WRIT-25] pedagogical + jargon) |
| Advanced: jobs & recovery | `AdvancedDrawer.tsx:7` | OK progressive disclosure label |
| Analyze selected media | `MediaAnalyzeCta.tsx:50` | Clear action |
| Name this person / Search people… | `ClusterLabelingPanel.tsx:210,264` | Clear; good |
| Entries / Clusters | `rosterRoute.ts:5–6` | “Clusters” is core domain jargon — subtitle on roster helps (`RosterPage.tsx:248–250`) |
| Managed Identities | `RosterEntriesSection.tsx:169` | Slight synonym drift vs “People/Entries” ([WRIT-06]) |
| People / Assigned / Pending Review | `DashboardPage.tsx:146–164` | Clear labels; tooltips help |
| Pin / Pinned | `ClusterPreview.tsx:69` | Clear; layout issue is visual not copy |
| Show media table | `MediaSummaryBar.tsx:35` | Clear recover path |
| Unavailable while the recognition service is offline | `useRemoteActionGate.ts:10–11` | Long but specific |
| Machine sync is healthy… | `syncVocabulary.ts:28` | “Machine” is abstract for WP admins ([WRIT-03]) |
| Sync backlog: pending/applied/failed/conflicts | `syncVocabulary.ts:63` | Heavy ops dialect |

---

## D. Heuristics sweep findings

**UXG-01 — Active job polling amplifies overload (RES-06, RES-15).**  
`useRecognitionHooks.ts` L32–36, L52–64 polls `GET /recognition/jobs/{id}` every 1.5s for all active jobs and retries non-404 failures up to 3 times without interpreting HTTP 429/503 Retry-After. Under remote rate limits this sustains a request storm rather than opening a circuit on the client. Impact: worsens 429s and latency for the whole admin SPA.

**UXG-02 — Sync “offline” is breaker-local, not VM health (RES-15, A11Y-24).**  
`degradedModeBannerLogic.ts` L14–15 and `class-sync-health-controller.php` L54–68 mark offline when a **WordPress transient breaker** is open for the configured base URL; the health endpoint does not ping OCI. Impact: banner copy “Working offline” / “Waiting for service…” can fire after proxy failures or stale breaker state even when operators expect a live GPU/service check.

**UXG-03 — Media table auto-collapse hides primary analyze CTA (LAY-01, A11Y-24).**  
`ScanTabContent.tsx` L53–54, L114 collapses `MediaSelection` when findings exist; collapsed `MediaSummaryBar` omits `MediaAnalyzeCta`. Impact: after a successful clustering/findings load, “Analyze selected media” vanishes until expand — feels like the table “disappeared” and blocks the primary scan action.

**UXG-04 — Analyze CTA only at table foot (LAY-04, A11Y-14).**  
`MediaAnalyzeCta.tsx` is only composed under the media table footer. Impact: long queues force scroll; no sticky/header twin for the primary control.

**UXG-05 — Pin control unstyled over avatar (LAY-10, A11Y-14).**  
`ClusterPreview.tsx` L58–70 places a full WP button in a 40×40 `position: relative` preview (`_workbench.scss` ~L444–446) with **zero** `__pin-toggle` CSS. Impact: “Pin/Pinned” paints over the face crop, tiny hit target, fails target-size and visual hierarchy.

**UXG-06 — Bulk-accept confidence is suggestion-queue only (REF-16, WRIT-06).**  
`SuggestionReviewPanel.tsx` L306–363 + PHP bulk-accept proxy pass `min_confidence` to accept **pending suggestions**, not to re-cluster. Impact: operators may believe the slider changes clustering membership for the next scan.

**UXG-07 — Advanced drawer always leads with clustering essay (LAY-04, WRIT-25).**  
`ConfirmTabContent.tsx` L15–23 always shows “What is Clustering?” with embedding jargon before recovery tools. Impact: recovery path feels tutorial-first; experts pay a permanent tax.

**UXG-08 — Roster Entries vs Clusters dual store confusion (DATA-02, WRIT-06).**  
Entries = local persons projection (`RosterEntryProjectionRepository`); Clusters = recognition cluster list with 30s poll. Impact: empty Entries + full Clusters looks like a bug; duplicates by name are separate person rows with no UI merge.

**UXG-09 — Name typeahead mixes person roster with cluster search (WRIT-06).**  
`ClusterLabelingPanel.tsx` L110–114 options from roster persons; duplicate recovery L138–162 searches labeled clusters. Impact: user thinks they search one “people” index; merge path is a second ontology.

**UXG-10 — Dashboard identity stats are local SQL only (REF-09, DATA-02).**  
`get_dashboard_stats` L951–986 counts `acx_*` tables; UI shows People/Assigned/Pending without remote reconciliation. Impact: stale zeros vs workbench activity erodes trust.

**UXG-11 — Retention posture unavailable is silent config miss (A11Y-24, WRIT-03).**  
`fetchRetentionStatus` returns `available: false` when endpoint missing; dashboard shows jargon title + unavailable. Impact: no remediation (“open settings / enable retention”) in the empty state.

**UXG-12 — Collapse expand state not durable (A11Y-16 state matrix).**  
`userExpandedMedia` is React state only (`ScanTabContent.tsx` L43). Impact: every navigation re-hides the table when findings remain; unlike merge-queue localStorage.

**UXG-13 — Sync strip still leaks ops lexicon (WRIT-02, WRIT-27).**  
Despite E21-1 “plain language” intent in `syncVocabulary.ts` header comments, “Delta sync”, “Queued”, “Sync backlog…”, “Machine sync” remain on the primary indicator (`SyncStatusIndicator.tsx` meta). Impact: WP media managers must learn internal topology vocabulary.

**UXG-14 — Status often color/tone + glyph but some badges rely on short words alone (A11Y-06).**  
`SyncStatusIndicator` pairs badge mark (✓ / … / !) with labels (good). Risk areas: confidence percent coloring (`SuggestionReviewPanel` low-confidence class) and dashboard highlight stats — verify icon/text pairing in CSS for low-confidence chips.

**UXG-15 — Magic status strings for sync health (sr-007 / eng NAME consistency).**  
`SyncHealth` union in `types/sync.ts` is centralized, but user-facing maps are large switch tables in `syncPresentation.ts` / `degradedModeBannerLogic.ts`. Impact: easy copy drift between dashboard summary and workbench strip (partially mitigated by comments demanding lockstep).

**UXG-16 — Inline suggestion fan-out (RES-12, RES-06).**  
Each identity card mounts `InlineSuggestionPrompt` → independent `top_k=1` query. Impact: large unlabeled sets create chatty parallel traffic that collides with job polling under rate limits.

---

## Overrides vs brief (verification)

1. **Source path:** `js/src/**` does not exist → real tree is `js/admin/**`.  
2. **Heuristics path:** `docs/workbay/rules/engineering-heuristics.md` missing → used `docs/reviews/uxp-1/lexicons/*.md` + `docs/strategy/engineering-heuristics.md`.  
3. **Name suggestions continuous 429 retry:** `useSuggestionReviewQueries` name query has `retry: false` and `refetchInterval: false` — storm is **not** primarily that poller; job pollers + multi identity `top_k` queries are the stronger amplifiers.  
4. **Offline banner:** not job/GPU-coupled; **breaker state** on local sync/health, not a remote OCI healthcheck.  
5. **Media disappear:** tied to **findings presence**, not solely “clustering job completed” event.

---

## Out of scope / not changed

No product code under `apps/` was modified. Documentation-only deliverable for lane `uxp-1-grok-audit`.
