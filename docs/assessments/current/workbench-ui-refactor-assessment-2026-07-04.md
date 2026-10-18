# Workbench UI Refactor Assessment — Usability Rework (2026-07-04)

> **Task**: WBUX-1 · `feature/wbux-1`
> **Goal**: what must be refactored on the plugin frontend for the Workbench to be *usable*, applying `literature/extracted/refactoring/distilled/` (primary: `refactoring-ui.md`; supporting: `refactoring-fowler-beck.md`, `refactoring-typescript.md`, `latency-reduce-delay-in-software-systems.md`, `modern-software-engineering.md`, `release-it.md`).
> **Hard constraint (must not regress)**: data sovereignty — computed clusters remain **displayable offline** from the local WP projection (`acx_clusters` / `acx_persons` / `acx_identity_members`); cluster **computation** stays on the remote recognition service.
> **Evidence**: codebase-graph index `Users-daniel-Development-context-alt-text-monorepo` (27,298 nodes / 81,875 edges; 480 workbench-matched symbols) + direct reads of `js/admin/pages/workbench/**`, `js/admin/styles/**`, API/hooks layers, and E15 epic UX Vision.

---

## 1. Current state (evidence summary)

Component inventory (codebase-graph + tree): Workbench = 2 tabs (`Scan`, `Confirm`) + 2 overlay panels (Conflict Inbox, Dead-Letter Queue) + 22 identity-cluster components + 15 job/sync hooks. Key metrics:

| Surface | Measure | Source |
| --- | --- | --- |
| `WorkbenchContextValue` | ~70 fields across 7 concerns in one context | `WorkbenchContext.tsx:51-123` |
| `WorkbenchProvider` | 285-line provider (127–411) | codebase-graph |
| `_workbench.scss` | 1,161 lines (next largest component sheet: 554) | `wc -l` |
| Raw hex literals | 67 in `_identity-cluster-list.scss`, 13 in `_combobox.scss` | grep |
| `box-shadow` declarations | 18 across 12 files; only 3 shadow tokens exist | grep |
| Type ramp | 6 tokens compressed into 0.68–1.0rem | `tokens/_typography.scss` |
| Hot spots (cognitive complexity) | `useClusterSaveAction` 32 · `buildMilestones` 26 · `buildStatusText` 24 · `useJobCoordination` 23 · `useJobProgressStream` 23 | codebase-graph complexity query |
| Job pipeline | phases `queued→detecting→clustering→retrying→awaiting_projection→failed/complete`, re-rendered by 4 independent status surfaces | `Panels.tsx`, `JobTimeline.tsx`, `SyncStatusIndicator.tsx`, page notices |

### 1.1 Current UI (ASCII, Scan tab as rendered)

```
WP Admin ▸ Alt Context ▸ Workbench
┌───────────────────────────────────────────────────────────────────────┐
│ [ Scan ] [ Confirm ]                                                  │
├───────────────────────────────────────────────────────────────────────┤
│ SyncStatusIndicator (1 of 8+ render branches), e.g.:                  │
│  "Last sync: 6/30, 4:12 PM [Fresh] [Delta sync] [Retention: …]        │
│   Pending curation: 3 · Conflicts: 2 · Failed replay: 1 ·             │
│   Last curation acknowledgement: … · Last curation conflict: … ·      │
│   Topology backlog: pending 1, applied 4, failed 0, conflicts 0"      │
├───────────────────────────────────────────────────────────────────────┤
│ (conditional notices: local-service target / "Network connection      │
│  lost. Reconnecting…" / detail truncation / "processed in another     │
│  tab")   + App-level DegradedModeBanner when breaker is open          │
├─ SCAN TAB (single scrolling column) ──────────────────────────────────┤
│ h2 "Scan Media Queue" + intro paragraph                               │
│ ┌ ScanActionPanel ────────────────────────────────────────────┐       │
│ │ "Ready to analyze 4 media items."                           │       │
│ │ [ Analyze selected media ]   (Cancel scan)                  │  ←CTA │
│ │ "Job abc123: processing…"  "Phase: Clustering"              │       │
│ │ "Processed 8/24 identities"  ▓▓▓▓▓░░░░░  "Remaining: 2 min" │       │
│ │ ("Stuck – last update 90 seconds ago" [Retry][Cancel])      │       │
│ └─────────────────────────────────────────────────────────────┘       │
│ JobTimeline   ✓ Scan complete (24 images, 61 faces)                   │
│               ● Clustering… 8/24 identities                           │
│               ○ Syncing results…                                      │
│ ┌ Recognition findings ───────────────────────────────────────┐       │
│ │ "12 to review · 3 merge candidates · 2 suggested names ·    │       │
│ │  5 unlabeled groups"    [40px avatar strip]                 │       │
│ │ [ Review next → Confirm: Alice ]  [ View all findings ]     │  ←CTA │
│ └─────────────────────────────────────────────────────────────┘       │
│ ┌ Review Suggestions (12) ────────────────────────────────────┐       │
│ │ "Is this Alice?"  [Accept][Reject][Label][Review]  96%      │  ←CTA │
│ │ …more cards / grouped cards with [Accept all][Reject all]…  │       │
│ │ ▸ Merge Candidates (collapsible queue)                      │       │
│ │ "Suggested names" list  [Accept][Reject] per row            │       │
│ │ "Name These People" (top unlabeled clusters)                │       │
│ │ "Bulk accept"  confidence slider 60%                        │       │
│ │  [Bulk accept assignments][…names][…merges]                 │  ←CTA │
│ └─────────────────────────────────────────────────────────────┘       │
│ ┌ MediaSelection ─────────────────────────────────────────────┐       │
│ │ Search […] Status [All media ▾]  status msg     [Retry]     │       │
│ │ ‹ Prev  Page 1 of 12  Next ›   Images per page [50 ▾]       │       │
│ │ ☑ │ Preview │ Details │ Tags                                │       │
│ │ … rows …                                                    │       │
│ │ ‹ Prev  Page 1 of 12  Next ›   Images per page [50 ▾]       │       │
│ └─────────────────────────────────────────────────────────────┘       │
└───────────────────────────────────────────────────────────────────────┘

CONFIRM TAB: h2 "Confirm & Publish" ("Compare before/after states,
  spot-check compliance, and push updates…") → actual content:
  "What is Clustering?" help card · ConfirmPanel ("Latest job — id /
  Status — …" [Cluster the latest job results][Open clusters in
  roster]) · RecentJobsPanel (raw job-id list + statuses + Clear)

OVERLAYS (replace top of panel area, `?overlay=`): Conflict Inbox
  ("Keep local for selected"/"Accept backend for selected", outbox
  timeline pager) · Dead-Letter Queue ("Failed replay operations",
  [Retry][Discard])
```

### 1.2 Current UX flow (as-is)

```
select media (bottom of page) ──▲ scroll up ──▶ [Analyze selected media]
      │                                            │
      │                      scan job ─▶ cluster job ─▶ projection sync
      │                      (progress in 3 places at once)
      ▼
findings appear mid-page ──▶ "Review next" scrolls DOWN to a stacked
                             mega-panel (4 queues + bulk slider)
                                     │
     Confirm tab (manual re-cluster + job history — misnamed)
                                     │
sync problems ─▶ badge links ─▶ full-screen overlay (Conflict/Dead-letter)
```

The user starts at the bottom (table), acts at the top (analyze), reviews in the middle (findings → suggestion stack), and recovers in overlays — four vertical round-trips per session, all panels always visible.

---

## 2. Diagnosis — why the Workbench is hard to use

### 2.1 Information architecture (Refactoring UI: hierarchy, "don't design too much"; MSE: separation of concerns)

- **Everything renders at once.** The Scan tab stacks 6 major panels in one column with no progressive disclosure. Findings queue, 4 suggestion queues, bulk-accept controls, and a 100-row media table compete equally. *RUI: "deliberately de-emphasize secondary content" — nothing is secondary here.*
- **The Confirm tab lies.** Its header promises "Compare before/after states, spot-check compliance, and push updates to WordPress media" — none of that UI exists. Actual content is a manual re-cluster button (a recovery affordance), an explainer card, and raw job-id history. *RUI: "don't imply features you aren't ready to build."*
- **Two-tab split is a false workflow.** Clustering auto-follows scanning in the state machine (`detecting→clustering→awaiting_projection`); the tab boundary suggests a manual step users must discover. The one real manual action (re-cluster after failure) is buried as the tab's primary CTA.
- **Four competing primary CTAs on one screen**: "Analyze selected media", "Review next", per-card "Accept", "Bulk accept ×3". *RUI action pyramid: one primary per screen; secondary/tertiary for the rest.*
- **CTA is separated from its object.** "Analyze selected media" sits ~4 panels above the table where selection happens; both paginators duplicate.

### 2.2 Status communication (Nygard: transparency; Fowler: duplicated state)

- **Job status is displayed 4 ways simultaneously**: ScanActionPanel text lines, JobTimeline milestones, SyncStatusIndicator branches, and page-level notices — with different vocabularies for the same phase ("Syncing results…" vs "awaiting_projection" vs "Projecting").
- **`SyncStatusIndicator` is a state soup**: 8+ early-return render branches over `isLoading × isError × is_stale × syncTrigger.{isPending,isSuccess,isError} × projectionState × pipelinePhase × syncHealth`. Every branch re-declares the same four meta blocks. This is the *Deceptive Booleans* smell (refactoring-typescript); it guarantees inconsistent states.
- **Internal jargon leaks to operators**: "Topology backlog: pending 1, applied 4, failed 0, conflicts 0", "Curation replay needs attention", "Acknowledging projected results…", "Payload label", "Entity: %1$s (%2$s)". *MSE bounded contexts: sync-internals vocabulary must be translated at the UI boundary.*
- **Offline is communicated 4 different ways**: `navigator.onLine` notice, App-level DegradedModeBanner, sync badge `Offline`, and per-panel `EmptyStateWarning` ("Suggestion service not configured") — the last one misdiagnoses an outage as misconfiguration.

### 2.3 Visual hierarchy & design tokens (Refactoring UI throughout)

- **Type scale is not a scale**: `2xs 0.68 / xs 0.75 / sm 0.875 / md 0.9 / lg 0.95 / base 1.0rem` — six sizes within 5px, adjacent steps of 0.4–0.8px (invisible), and *no sizes above 16px* for headings. The file itself documents it as a "snap map" of legacy raw values. *RUI: hand-crafted scale 12/14/16/18/20/24/30…, no two adjacent values closer than ~25%.*
- **No color system**: single-value semantic tokens only; no grey ramp (RUI: 8–10 shades), no primary/accent shade scales. The `REFA-3` comment in `_colors.scss` records tokens invented post-hoc by aliasing because components referenced undefined variables. 80+ raw hex literals persist in component sheets (67 in `_identity-cluster-list.scss`).
- **No elevation system**: 3 ad-hoc shadow tokens, 18 scattered `box-shadow` declarations. Panels separate with borders everywhere. *RUI: define a 5-level shadow scale; prefer spacing/background/shadow over borders.*
- **Label-heavy data display**: "Status — Pending", "Latest job — No job yet", "Phase: Clustering", "Last curation acknowledgement: …". *RUI: labels are a last resort; format/context should communicate type.*
- **Status pills are color-only** (`Fresh`/`Stale`/`Offline` badges) — violates repo rule sr-004 (color must pair with an icon) and RUI "don't rely on color alone". JobTimeline (✓ ● ○ ✕) already does this right.
- **Ambiguous spacing**: each panel supplies its own margins; spacing *between* unrelated panels ≈ spacing *within* a panel's groups, so the column reads as one undifferentiated stack. Spacing tokens include near-duplicates (8/10/12) that enable this.

### 2.4 Code structure blocking UI change (Fowler/Beck; refactoring-typescript)

- **God context**: `WorkbenchContextValue` exposes ~70 fields spanning navigation, job history, selection, filters, state machine, cluster panels, and env config. Any consumer re-renders on any change; any UI regroup requires touching it. *Large Class → Extract Class; sr-008 → group into per-concern providers/selector hooks (Encapsulate Variable).*
- **Shotgun surgery on pipeline phases**: adding/renaming a phase touches `jobStateMachineUtils`, `jobStateMachineProgress.buildStatusText` (cognitive 24), `JobTimeline.buildMilestones` (26), `Panels.formatJobPhase`, and `SyncStatusIndicator`. *Repeated Switches → phase→presentation strategy map (enum + record), one module.*
- **Long parameter lists**: `ScanActionPanel` takes 14 props (progress + batch + stall + eta + synced…). *Introduce Parameter Object: one `ScanRunViewModel`.*
- **Mega-component**: `SuggestionReviewPanel` orchestrates 4 queues + bulk mutations inline (`Promise.all` loops, shared `bulkActionRef`). *Extract Function/Move Function into the owning hooks; Split Phase (derive view-model → render).*
- **Mutation UX is all-or-nothing**: `isAnyMutationPending` disables every card while one Accept is in flight.

### 2.5 Perceived latency (Enberg)

- Text-only loading states ("Loading suggestions...", "Checking recognition findings…") that pop in/out as 5+ independent queries resolve → layout shift; page readiness = slowest query (parallel-compounding tail).
- No optimistic updates: accept/reject waits on the round-trip and freezes the whole queue (safe here: per-item suggestion ops are single atomic backend calls, rg-002-compatible).
- Good foundations to keep: progress phases with ETA, stall detection ("Stuck – last update …" + Retry), bounded polling.

### 2.6 Stability & sovereignty (Release It!; epic UX Vision)

Foundation is genuinely strong and must be preserved: circuit breaker surfaced to the UI (`breaker.state === 'open'` → `isSyncOffline`), DegradedModeBanner ("Working offline — Showing your local copy; changes will sync when the service returns"), per-response `data_source` markers (`local_projection | backend_proxy | endpoint_error | unavailable`), local projection tables, outbox → conflicts → dead-letter queues, `browser_local_fallback` labeling for job history.

Gaps:

- **No fail-fast on compute actions**: "Analyze selected media" stays enabled with the breaker open → spinner-then-error. *Nygard Fail Fast: disable with reason while the circuit is open; local browsing stays enabled.*
- **Degraded messaging is per-panel and inconsistent** (see 2.2). One `ConnectivityModel` should drive all of it.
- **Read-only mode exists but is quiet**: findings panel disables curation during projection catch-up with a wordy notice; the same read-only concept should be the single, visible offline mode.

---

## 3. Target UI (ASCII)

One surface, three regions, one primary CTA per state. Tabs are replaced by a pipeline header that reflects the state machine instead of asking the user to operate it.

```
WP Admin ▸ Alt Context ▸ Workbench
┌───────────────────────────────────────────────────────────────────────┐
│ ● Connected · Synced 4:12 PM              3 queued · 2 conflicts ▸    │ ← single status strip
│   (offline: "◐ Offline — showing your local copy   [Details ▸]")     │   icon+color+text
├───────────────────────────────────────────────────────────────────────┤
│   ① Select  ─────────▶  ② Analyze  ─────────▶  ③ Review people        │ ← pipeline header
│   24 selected           ✓ scanned · ● clustering 8/24 · ○ sync        │   (read-only state,
├───────────────────────────────────────────────────────────────────────┤    ETA + stall/retry)
│ ┌ REVIEW QUEUE — the primary surface once findings exist ───────────┐ │
│ │  ┌────────┐   Is this Alice?                        96%           │ │
│ │  │ face   │   from cluster of 7 faces · 3 photos                  │ │
│ │  │ 96px   │   [ Confirm ]   [ Not Alice ]   [ Skip ⋯ ]            │ │ ← ONE item at a
│ │  └────────┘                                                       │ │   time, one primary
│ │  Up next: 11 to review · 3 merges · 2 names · 5 unnamed groups    │ │   [Confirm]
│ │  (chips filter the queue)                [ View all ] [ Bulk ▾ ]  │ │ ← bulk = secondary
│ └───────────────────────────────────────────────────────────────────┘ │   disclosure w/slider
│ ┌ MEDIA — expanded in step ①, collapses to a bar during review ─────┐ │
│ │ Search […]  [Missing alt ▾]           142 items · 24 selected     │ │
│ │ ☑ │ thumb │ details │ tags   … rows …                             │ │
│ │ ‹ 1 / 12 ›  ·  50/page          [ Analyze 24 selected ]           │ │ ← CTA lives with
│ └───────────────────────────────────────────────────────────────────┘ │   the table
│ ▸ Advanced: jobs & recovery                                           │ ← collapsed drawer:
│    (job history, re-run clustering, conflicts, failed replays)        │   absorbs Confirm
└───────────────────────────────────────────────────────────────────────┘    tab + overlays
```

Offline rendering of the same layout: status strip flips to `◐ Offline`, pipeline header hides ②'s CTA ("Analyze" disabled — "recognition service unreachable"), the review queue stays fully browsable from the local projection with write actions queued to the outbox (or read-only where the payload is proxy-only), media table works normally (local WP data).

Design-token targets backing this layout:

- Type: `12 / 14 / 16 / 18 / 20 / 24 / 30px` ramp; headings finally exist; kill `md`/`lg` 0.9/0.95 near-duplicates.
- Greys: 9-shade ramp; primary: 9-shade ramp; keep existing semantic aliases pointing into the ramps; purge the 80+ raw hex literals (extend `workbench-tokenization.test.ts` to all component sheets).
- Elevation: 5-level shadow scale (`--acx-shadow-1..5`); panels separated by background + spacing, borders reserved for tables/inputs.
- Status = icon + color + word everywhere (JobTimeline pattern generalized).

---

## 4. Target UX logical flow

```
                          ┌─────────────────┐
                          │ open Workbench  │
                          └────────┬────────┘
                                   ▼
                    ┌──────────────────────────────┐
              ┌─────│ findings pending? (local     │─────┐
           no │     │ projection — works offline)  │     │ yes
              ▼     └──────────────────────────────┘     ▼
   ┌─────────────────────┐                   ┌──────────────────────────┐
   │ STEP ① select media │                   │ STEP ③ review queue      │
   │ search/filter table │                   │ one card at a time:      │
   └──────────┬──────────┘                   │  confirm match / merge / │
              ▼                              │  accept name / name group│
   [ Analyze n selected ]                    │ chips switch sub-queues; │
      │  disabled+reason if                  │ optimistic accept, undo  │
      │  breaker open (fail fast)            └───────────┬──────────────┘
      ▼                                                  │ queue empty
   STEP ② one pipeline action                            ▼
   scan ─▶ cluster ─▶ project                ┌──────────────────────────┐
   (auto-sequenced; progress +               │ done: "9 people named,   │
    ETA + stall/retry in the                 │ 61 faces covered" →      │
    pipeline header ONLY)                    │ next: Roster / Describe  │
      │ findings stream in as ready          └──────────────────────────┘
      └────────────────▶ STEP ③ (auto-focus)

 ambient, non-blocking:
   sync strip: Fresh / Syncing / Offline / Needs attention (n)
        └─ "Needs attention" ▸ Advanced drawer: conflicts (keep local /
           accept backend), failed replays (retry/discard), job history,
           manual re-cluster
 offline invariant:
   reads ← local projection (clusters, persons, members, findings counts)
   writes → outbox, replayed on reconnect; conflicts surface in drawer
   compute (scan/cluster) ← remote only, fail-fast when breaker open
```

---

## 5. Data-sovereignty invariants (redesign must keep)

| Surface | Offline behavior | Backing |
| --- | --- | --- |
| Cluster/person/member display, findings counts | **Must render** from local projection | `acx_clusters`, `acx_persons`, `acx_identity_members`; `data_source=local_projection` |
| Curation actions (label, merge accept, dismiss) | Queue to outbox, visible as "queued"; replay on reconnect | `acx_sync_outbox`, `acx_topology_commands` |
| Conflicts / failed replay | Reviewable offline; resolution replays later | `acx_sync_conflicts`, dead-letter UI |
| Scan / cluster compute, bulk accept, suggestion generation | Remote-only; **fail fast** with visible reason when breaker open | recognition service; `sync-health.breaker` |
| Media table, WP alt text | Fully local (WP REST `acx/v1/workbench/media*`) | WP DB |

The redesign consolidates *how* offline is communicated (one strip + one read-only pattern) without changing *what* is available offline. `resolveEffectiveSyncHealth` already computes the single source of truth; the refactor makes it the only input to connectivity UI.

---

## 6. Prioritized refactor backlog (small, shippable slices — MSE)

Each slice is independently mergeable, behavior-preserving unless stated, and verified against existing harnesses: `tests/e2e/a11y/workbench-axe.spec.ts`, `tests/e2e/visual/workbench-visual.spec.ts`, `tests/e2e/evidence/workbench-evidence.spec.ts`, `js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts`, unit suites per component.

1. **S1 — Status view-model consolidation** *(unblocks everything visual)*. Split Phase: derive one `SyncPresentation` (state enum + message + counts + action) from `useSyncStatus`/`useSyncHealth`/`projectionState`/`pipelinePhase`; render one strip; delete the 8-branch component, the duplicate meta blocks, and 3 of 4 job-status surfaces. Translate jargon at this boundary (topology/curation → "n changes waiting to sync"). Fixes 2.2 wholesale.
2. **S2 — Review queue unification**. Fold assignment/merge/name/unlabeled queues into one card-at-a-time queue with filter chips (the E15-23 findings panel already computes `nextAction` — promote it from "scroll helper" to the queue driver). Per-item optimistic accept/reject with undo toast; bulk accept becomes a disclosure. Fixes 2.1's CTA competition and 2.5.
3. **S3 — Kill the Confirm tab**. Single pipeline action (scan→cluster→project auto-sequenced — already true in the state machine); move manual re-cluster + job history + overlays into an "Advanced: jobs & recovery" drawer; delete the unfulfilled "Confirm & Publish" copy. Route `?overlay=` params to the drawer for link-compat.
4. **S4 — Media step compaction**. CTA co-located with the table; collapse table to a summary bar during review; one paginator. Fixes 2.1 scroll round-trips.
5. **S5 — Token system rework**. Type ramp, grey/primary 9-shade ramps, 5-level elevation; purge raw hex; extend the tokenization test to every component sheet; split `_workbench.scss` (1,161 lines) per component. Pure CSS slice, visual-regression-gated (sr-004 compliance included).
6. **S6 — Context decomposition**. Extract per-concern providers (selection, media-query, job-pipeline, cluster-panels) behind selector hooks; `WorkbenchContextValue` shrinks from ~70 fields to composition of 4 objects (sr-008). Phase→presentation strategy map replaces the four phase switches. Prep refactor for any later feature work.
7. **S7 — Offline hardening**. Fail-fast disabled states on compute actions when breaker open; unify per-panel `EmptyStateWarning` variants under the S1 connectivity model; explicit read-only mode chip on the review queue when curation is proxy-only or projection is catching up.

Sequencing note (Fowler): S1 and S5 are preparatory refactorings — do them before S2–S4 so the visual re-grouping lands on a coherent status model and token system. S6 can proceed in parallel behind unchanged behavior; S7 rides on S1.

## 7. Out of scope / risks

- No backend contract changes required; every slice consumes existing endpoints and `data_source` markers (rg-015: adapters must not invent metadata).
- Roster/Retention/Dashboard pages untouched (Roster remains the deep person-management workspace; the workbench queue links into it).
- Risk: `?tab=`/`?overlay=` deep links are exercised by e2e specs — S3 must keep URL-param compat shims until specs migrate.
- Risk: visual-regression baselines invalidate wholesale at S5; regenerate once, then S2–S4 diffs stay reviewable.
