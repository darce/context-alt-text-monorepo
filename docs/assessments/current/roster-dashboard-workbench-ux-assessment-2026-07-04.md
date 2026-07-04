# Roster, Dashboard & Workbench Integration — UX Assessment (2026-07-04)

> **Task**: WBUX-2 · `feature/wbux-2` · companion to [workbench-ui-refactor-assessment-2026-07-04.md](workbench-ui-refactor-assessment-2026-07-04.md) (WBUX-1)
> **Questions answered**: (1) Roster page assessment (current/target ASCII + flows); (2) is the clusters management surface redundant; (3) how Workbench integrates with Roster; (4) Dashboard cull/keep; (5) Workbench cull/keep.
> **Method**: same literature base as WBUX-1 (refactoring-ui primary) + direct reads of `pages/roster/**`, `pages/dashboard/**`, menu/routing PHP, plus prior-decision audit (2026-05-05 dashboard & roster-workflow assessments; E15-13 done, E15-15/16 done via E15-20, E15-17 slices 1–2 landed).
> **Sovereignty constraint unchanged**: person/cluster display works offline from local projection; compute stays remote.

---

## 1. Roster page — current state

Admin menu: Dashboard Overview · Workbench · Roster · Settings (Retention is route-only — reachable exclusively via dashboard link; no menu entry).

### 1.1 Current UI (ASCII)

```
WP Admin ▸ Alt Context ▸ Roster
┌───────────────────────────────────────────────────────────────────────┐
│ ALT CONTEXT                                                           │
│ h1 Roster Management                                                  │
│ "People are known identities you curate. Clusters are detected face   │
│  groups you review and assign."                                       │
├───────────────────────────────────────────────────────────────────────┤
│ [ Entries ] [ Clusters ]                                              │
├─ ENTRIES TAB (default) ───────────────────────────────────────────────┤
│ h2 "Entries"                                                          │
│ ┌ PersonWorkspacePanel — AUTO-OPENS alphabetically-first person ────┐ │
│ │ h3 <name> · "3 clusters assigned" · "Projection status: current"  │ │
│ │ "Projection refreshed: …" · "Source version: 7"                   │ │
│ │ h4 Grouped cluster detail  h4 Person evidence (tags)               │ │
│ │ h4 Assigned cluster evidence                                       │ │
│ │   h5 3f9a2c81-…-uuid  "12 projected instances"  [96px face]       │ │
│ │   "87% similarity" "Threshold 82%"  [instance thumbs…]            │ │
│ │ h4 Curriculum review queues                                        │ │
│ │   Singleton proposals / Hard examples / Needs confirmation        │ │
│ │   after merge — each: status line + "Open <queue> queue" link     │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│ (⚠ Managed Identities table + [Add Person] HIDDEN in this default    │
│    mode — person list only appears when a filter/gate is active)     │
├─ CLUSTERS TAB ────────────────────────────────────────────────────────┤
│ help card: "Clusters are groups of similar face identities…"          │
│ [☐ select all] h2 Clusters      「2 selected ✕ [Merge][Dismiss]」     │
│ "Showing 20 of 57 clusters. Refine the list…" (no refine UI exists)  │
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                      │
│ │☐(hover-only)│ │             │ │             │  card grid 280px     │
│ │ h3 Alice    │ │ Cluster 9f2e│ │ Cluster 41d0│  ← label or raw id   │
│ │ 7 identities│ │ 3 identities│ │ 1 identity  │                      │
│ │ (◯)(◯)(◯)(◯)│ │ (◯)(◯)(◯)   │ │ (◯)         │  ← 4 draggable faces │
│ └─────────────┘ └─────────────┘ └─────────────┘                      │
│ DRAWER (card click) ─────────────────────────────┐                    │
│ │ CLUSTER IDENTITY · h3 Alice · Faces: 7 ·       │                    │
│ │ Confidence: 91% · Found: 6/28/2026        [✕]  │                    │
│ │ [128px face strip, draggable, links to media]  │                    │
│ │ "Drop identities here to remove them…"         │                    │
│ │ [Rescan with sensitive settings]               │                    │
│ │ Assign to Identity: [Assign to… ▾ creatable]   │                    │
│ │ [Confirm Assignment] [Open person workspace]   │                    │
│ └────────────────────────────────────────────────┘                    │
└───────────────────────────────────────────────────────────────────────┘
```

### 1.2 Current flows (click counts)

| Job | Path | Cost |
| --- | --- | --- |
| Name a cluster (roster path) | Clusters tab → card → drawer → combobox → create-option → Confirm Assignment | 5 clicks + typing; label-only rename impossible here (Workbench-only) |
| Merge two clusters | tab → hover-checkbox ×2 → Merge → confirm | 5 clicks; target = first-selected, undisclosed; no label |
| Fix wrong member | drag card thumbnail → other card (best) / drawer → discard-only (worst) | 1 drag best; dead-end worst — drawer can't drop onto grid (backdrop blocks) |
| Create a person | Entries → Add Person → Create | 2 clicks — **but unreachable in the default view** (table hidden by auto-workspace) |

### 1.3 Roster diagnosis

1. **Primary controls unreachable from zero state (rg-003).** The default Entries view auto-selects one person and hides the entire Managed Identities table including `Add Person`. Person management — the page's title job — requires a URL param or a detour through the Clusters drawer.
2. **Five names for two concepts.** Person = "Entries" / "Managed Identities" / "People" / "roster entry" / "person workspace"; face-group = "Cluster Identity" / "identities" / "Faces". The drawer's "Assign to Identity" actually means *bind to person*. (RUI: labels communicate type — impossible when the type has no stable name.)
3. **Cluster grid is a capped, unfilterable management surface.** Hardcoded `limit: 20` with a truncation notice telling users to "refine the list" — no search/filter/pagination rendered (API supports `search`/`labeled_only`/`offset`, unused). Hover-only checkboxes are invisible on touch.
4. **Pipeline internals rendered verbatim.** Raw cluster UUIDs as headings, "Source version: 7", "projected instances", five distinct "…after the next projection refresh." wait-states with no refresh action, "Curriculum review queues". (MSE: translate at the boundary.)
5. **Hard-examples queue is a designed dead end** — filterable, actions "unavailable … until the dedicated review contract lands", and no Workbench hand-off link (the other two queues have one).
6. **Bulk merge is a sequential client loop** (N−1 requests, non-atomic on failure) — rg-002-adjacent risk surface.

---

## 2. Is the clusters management page redundant? — Yes, as a *management* surface

Capability matrix (evidence: `clusterApiMutations.ts` consumers):

| Operation | Workbench | Roster Clusters tab | Verdict |
| --- | --- | --- | --- |
| Merge | suggestion accept + queue, carries `target_label` | bulk-select, implicit target, no label | duplicate, divergent semantics |
| Dismiss | TopClustersSection | bulk bar | duplicate |
| Reassign/remove member | with `blockFromCluster` ("not this person") | drag-drop, no block flag | duplicate, roster loses information |
| Name | label-only (`updateClusterLabel`) | person-commit only (`clusters/{id}/commit`) | **split across pages** — the two halves of one job |
| Split / revert merge / pin representative / create-for-identity | ✓ | — | Workbench-only |
| Bind cluster → person, inline person create | — | ✓ (only surface anywhere) | Roster-only |
| Sensitive rescan per cluster | — | ✓ drawer | Roster-only (recovery) |
| Suggestion review ("Is this X?"), bulk-by-confidence | ✓ | — | Workbench-only |

**Verdict**: the Roster ▸ Clusters tab duplicates every routine curation op the Workbench already owns, with *worse* semantics (undisclosed merge target, no block-from-cluster, label-less merge), while hoarding the one op the Workbench needs most (person-commit). The 2026-05-05 roster assessment already ruled the operator mental model is **person-centric, not cluster-centric**, and E15-17 (in progress) demotes clusters to "evidence mode". This assessment concurs and goes one step further:

> **Retire Roster ▸ Clusters as a management tab.** Clusters remain visible only as *evidence inside a person workspace* (E15-17) and as *review items inside the Workbench queue*. Its unique ops relocate: person-commit + creatable person combobox → Workbench review card (primary) and person workspace (secondary); drag-drop member fix → the E15-17 face scrubber; sensitive rescan → Workbench "Advanced: jobs & recovery" drawer; bulk merge/dismiss → Workbench bulk disclosure (made atomic server-side or clearly progressive).

---

## 3. How Workbench integrates with Roster — the model

One sentence: **Workbench decides, Roster curates, Dashboard orients.** Machine proposals get accepted/rejected in the Workbench queue; the accepted result (people + their evidence) lives in Roster; Dashboard routes to whichever needs attention.

```
                 ┌────────────────────────────────────────────┐
                 │ DASHBOARD — orient & triage                │
                 │ health strip · review counts · coverage    │
                 └──────┬──────────────────────┬──────────────┘
        "n to review"   │                      │  "person needs attention"
                        ▼                      ▼
   ┌────────────────────────────┐   ┌───────────────────────────────┐
   │ WORKBENCH — decide         │   │ ROSTER — curate the result    │
   │ select→analyze→review queue│   │ person list + person workspace│
   │ cards: confirm / merge /   │──▶│ (evidence: clusters,instances,│
   │ name→person-commit         │   │  scrubber, tags)              │
   │ [Assign to person… ▾]      │◀──│ queue chips re-enter the      │
   │  creatable, from roster    │   │ Workbench queue FILTERED, not │
   │  drawer pattern            │   │ a page bounce                 │
   └────────────┬───────────────┘   └───────────────┬───────────────┘
                │ confirm w/ person → "View person"  │
                └──────────── #/roster?person=<uuid> ┘

 contract: E15-17 route vocabulary (?person= ?queue= ?face=) is the ONLY
 cross-surface link currency; E15-13 queue projections (singleton /
 hard-example / needs-confirmation) render as Workbench queue chips AND
 roster workspace sections — same rows, two lenses. All reads offline-
 capable (local projection); person-commit queues to outbox when offline.
```

Integration rules:

1. **Naming = person-commit, everywhere.** The Workbench "name this cluster" action adopts the roster drawer's creatable combobox (bind existing person or create inline). Label-only rename survives as a tertiary action for non-person clusters (pets, logos). This heals the split naming path (§2 table).
2. **Queues are chips, not page-hops.** Today: roster queue link → Workbench scan tab (context lost) → "Open clusters in roster" → back. Target: the three E15-13 queues are filter chips on the single Workbench review queue; the person workspace shows the same memberships read-only with a "Review in Workbench" chip-link carrying `?queue=`.
3. **Every Workbench confirm that touches a person emits a `View <name> →` deep link** (`#/roster?person=<uuid>`), and the roster workspace's evidence header links back to the source media.
4. **Roster keeps zero curation-queue UI of its own** beyond chips — no accept/reject in the workspace. One decision surface (Nygard: one place to look; Fowler: remove duplicated state machines).

### 3.1 Roster target UI (ASCII)

```
WP Admin ▸ Alt Context ▸ Roster
┌───────────────────────────────────────────────────────────────────────┐
│ ● Connected · Synced 4:12 PM                    [status strip, shared]│
├──────────────┬────────────────────────────────────────────────────────┤
│ PEOPLE       │  Alice ▸                                    [Edit][⋯] │
│ [+ Add]      │  7 faces · 3 clusters · tags: family                   │
│ [Search…]    │  ┌ evidence ─────────────────────────────────────────┐ │
│ ▸ Alice    3 │  │ [96px face][face][face][face][face] → scrubber    │ │
│   Bob      2 │  │ cluster “Alice” 87% match ▸  (drag out = remove,  │ │
│   Carol    1 │  │ drop here = assign)   [Rescan ▸ Advanced]         │ │
│ ─ filters ─  │  └───────────────────────────────────────────────────┘ │
│ Unassigned 2 │  Needs review: ◇ 1 singleton · ◇ 2 hard examples       │
│ Queues:      │  [Review in Workbench →]        ← chips, not a bounce  │
│ ◇ single. 4  │                                                        │
│ ◇ hard ex. 2 │  (empty state: "No people yet — confirm findings in    │
│ ◇ post-merge │   the Workbench or [+ Add] one manually.")             │
└──────────────┴────────────────────────────────────────────────────────┘
  No Clusters tab. Person list ALWAYS visible (fixed-width sidebar, RUI
  "sidebars get fixed width, content flexes"). Workspace = evidence +
  scrubber (E15-17 slices 3-4), plain-language projection states with a
  single "Refreshing…" pattern + retry.
```

---

## 4. Dashboard — first pass: cull / keep

Current shape: hero → DescribePanel (full-width) → 6-panel grid (priority model orders; sync health usually first) → OrientationCard (dismissible). 7 independent data hooks, no unified loading model.

```
┌ current ──────────────────────────────────────────────────────────────┐
│ h1 Alt Context Dashboard                                              │
│ ┌ AI Image Description (preview): [Attachment ID:__] [Describe] ────┐ │
│ ┌Sync Health┐┌Identity Rec.┐┌Library Cov.┐┌Recent Act.┐┌Retention┐   │
│ │summary+3  ││4 tiles +    ││3 tiles +   ││UUID rows  ││3 tiles +│   │
│ │tiles+CTAs ││GuidanceCard ││progress,   ││"View      ││CTA      │   │
│ │           ││CTA          ││ NO CTA     ││ Results"  ││         │   │
│ ┌Batch Operations: 3 nav cards duplicating everything above ───────┐ │
│ ┌Getting Started (3 steps) — always until localStorage dismissed ──┐ │
└───────────────────────────────────────────────────────────────────────┘
```

**CULL** (each already endorsed by the 2026-05-05 assessment or by dead-code evidence):

| Item | Why | Disposition |
| --- | --- | --- |
| **Batch Operations panel** | Pure nav duplication (its 3 cards repeat Sync Health CTAs + guidance links); "operations" that contain no operations. Endorsed F6, never done | Delete; keep only "latest batch: status + View results" line merged into Recent Activity |
| **OrientationCard always-on** | Not state-aware; contradicts endorsed F4 | Render only when `people_count === 0` and no scan history; drop localStorage dismissal |
| **DescribePanel as hero** | Raw attachment-ID input, display-only draft, no apply, provenance `<dl>` (Adapter/Model/Latency) — a dev preview squatting on the primary slot | Demote below grid behind "Preview" disclosure OR relocate next to media context in Workbench; keep the 180s-timeout mutation intact |
| **`before_grid` orientation branch** | Dead code (model hardcodes `after_grid`) | Delete |
| **Jargon tiles/lines** | "Pending Replay", "Failed Replay", "Topology backlog", "Dead-Letter Queue", raw job UUIDs, "Current browser memory" | Translate: "n changes waiting to sync", "n sync problems", relative timestamps + status words; UUIDs → "Batch · 24 items · 2m ago" |
| **Heading case drift** | "Retention posture" vs "Sync Health" | Normalize |

**KEEP** (must stay — with the one fix each needs):

| Item | Why it stays | Required fix |
| --- | --- | --- |
| **Sync Health panel** | Hierarchy contract: blocking health first (R-MISS-1); deep links to conflicts/dead-letter are the recovery entry | Wording translation only; new diagnostic fields stay gated behind the E15-16/E15-20 rubric |
| **Identity Recognition + GuidanceCard** | The only contextual-CTA engine; correct pattern | Point CTAs at E15-17 route vocabulary (`?queue=`, `?person=`) instead of raw tabs; surface E15-13 queue counts (projection-backed, already available) |
| **Library Coverage** | The product's core metric | **Give it a CTA** — "Missing Alt Text: n" → Workbench media table pre-filtered `status=missing`; today it's the only panel with zero affordance |
| **Recent Activity (durable + fallback label)** | E15-16 contract; honest provenance | Humanize rows (drop raw UUIDs) |
| **Retention posture** | Governance surface; sole route to `#/retention` (no menu entry!) | Make `unavailable` actionable (endorsed F5) or demote to a footer link; consider a Retention menu item |
| **`buildDashboardPriorityModel`** | Sanctioned ordering seam | Extend: missing-alt backlog should influence order; stop counting loading states as "attention" (first-paint jitter); add a unified page-loading model |

---

## 5. Workbench — cull / keep

(Extends WBUX-1 §6 backlog with the roster integration decisions above.)

**CULL:**

| Item | Why | Disposition |
| --- | --- | --- |
| **Confirm tab** | Header promises unbuilt compare/publish; content is recovery affordances | Delete tab; manual re-cluster + RecentJobsPanel + explainer → "Advanced: jobs & recovery" drawer (WBUX-1 S3) |
| **SuggestionReviewPanel mega-stack** | 4 stacked queues + bulk sliders, equal weight | One card-at-a-time queue with chips (WBUX-1 S2); bulk accept → disclosure |
| **3 of 4 job-status surfaces** | Duplicated state, divergent vocab | One strip + pipeline header (WBUX-1 S1) |
| **`ClusterLabelingPanel` label-only naming as the primary name path** | Splits naming from person-binding (§2) | Primary naming = person-commit combobox on the review card; label-only demoted to tertiary |
| **Duplicate paginator, `NoMediaPanel` + empty-state overlap, per-panel `EmptyStateWarning` variants** | Redundant surfaces | Single paginator; one connectivity-driven empty/degraded pattern (S7) |
| **Topology/curation meta rows in sync indicator** | Operator jargon | Behind "Details ▸" disclosure, translated |
| **DebugMetricsPanel** | Debug UI in user surface | Dev-flag gate |

**KEEP** (must stay):

| Item | Why |
| --- | --- |
| **Media selection table + search/status filter** | Only media-picking surface; step ① of the pipeline; gains the dashboard's `status=missing` deep-link |
| **Scan pipeline action + progress/ETA/stall-retry/cancel** | Real recovery affordances (Nygard: fast feedback, retry discipline); keep monotonic progress + batch failure details |
| **JobTimeline milestone language (✓●○✕ icon+color+word)** | The one status pattern done right — becomes the sitewide status vocabulary (sr-004) |
| **WorkbenchFindingsPanel / `useWorkbenchFindings` next-action driver** | E15-23 investment; already computes the queue's "review next" — promote to queue driver |
| **Conflict Inbox + Dead-Letter panels** | Unique recovery surfaces (keep-local/accept-backend, retry/discard); relocate into Advanced drawer, preserve `?overlay=`-compatible deep links |
| **Sync status strip (single instance) + DegradedModeBanner semantics** | Sovereignty surface: breaker state, "showing your local copy", data_source-driven read-only handling |
| **Offline read path** | Findings counts, suggestion queues (`local_projection`), media table all render offline; curation writes queue to outbox — non-negotiable invariant |

---

## 6. Sequencing addendum (extends WBUX-1 backlog)

The WBUX-1 slices S1–S7 stand. This assessment adds/refines:

- **S2′ (review queue)** absorbs person-commit combobox (roster drawer pattern) and E15-13 queue chips → supersedes the roster Clusters tab's routine ops.
- **S8 — Roster person-first completion**: finish E15-17 slices 3–4 (face scrubber, cluster drawer → "Open person review"), then delete the Clusters tab, keeping `?cluster=` deep links resolving into the owning person's workspace (or the Workbench queue for unassigned clusters). Restore always-visible person list + `Add Person` (fixes rg-003 violation).
- **S9 — Dashboard cull pass**: delete Batch Operations, state-aware orientation, coverage CTA, jargon translation, demote DescribePanel. Small, independently shippable, mostly deletion (Fowler: Remove Dead Code is the cheapest refactoring there is).
- **S10 — Cross-surface link contract**: all CTAs move to `?person=/?queue=/?face=` vocabulary; add redirect shims for `?tab=clusters` and `?overlay=` (e2e specs depend on them).

Dependency order: S1 (status model) → S2′ (queue + person-commit) → S8 (roster) → S9 (dashboard) → S10 sweeps last. S9 can start any time; only its CTA retargeting waits on S10 vocabulary.

## 7. Risks / open questions

- E15-17 slices 3–4 are open; S8 must not fork its design — the scrubber action matrix (real API rows only) and conservative similarity copy (pre-RCL-009) bind this assessment too.
- Hard-examples queue stays a labeled dead end until its review contract lands; the queue chip should carry a "coming soon" state rather than hide.
- Bulk merge atomicity: either a server-side batch endpoint or an explicit progressive UI ("merging 2 of 5…") — silent sequential loops violate rg-002's spirit.
- Retention discoverability (route-only page) is out of scope here but noted: one menu item or one dashboard footer link decision needed.
