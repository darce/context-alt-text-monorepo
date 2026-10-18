# E21-18 — Workbench Control-Pane Rework Design

Surface: `#alt-context-admin-app … .acx-workbench__two-pane > section.acx-workbench__two-pane-control`
(left pane of `WorkbenchTwoPaneLayout`, populated by `ScanTabContent`).

Scope: (1) queue-first ordering, (2) FindingsPreview fallback chain, (3) 0-faces dead-end card,
(4) avatar state system. All heuristic IDs cited below were verified against
`heuristics-canon/lexicons/*.md` (interaction-ux, accessibility, engineering, ml-systems, design-aesthetics).

---

## A. Current-state inventory

Control-slot render order today (`ScanTabContent.tsx`, top→bottom):

| # | Component | File | Role | Issues |
|---|-----------|------|------|--------|
| 1 | `ScanActionPanel` | `js/admin/pages/workbench/Panels.tsx` | Start/cancel scan CTA | Occupies prime top position even when idle; scan is a per-session action, review is per-item work (NAV-06 frequency inversion) |
| 2 | `JobTimeline` | `js/admin/pages/workbench/JobTimeline.tsx` | Scan/cluster phase progress | Full-height even when no job is active |
| 3 | `WorkbenchFindingsPanel` | `js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx` | Counts summary + preview chips + "Review next" | Sits ABOVE the queue it summarizes; its error state is a bare `<p>` with no retry (chain incomplete); `FindingsPreview` last-resort branch renders `Avatar src=""` |
| 4 | `NoMediaPanel` | `js/admin/pages/workbench/ScanTabContent.tsx` | Zero-media hint | OK |
| 5 | `ReviewQueue` / `ClusterReviewPanel` / `ClusterLabelingPanel` (exclusive) | `js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx`, `ClusterReviewPanel.tsx`, `ClusterLabelingPanel.tsx` | The actual work surface: one card at a time (`TopClusterCard`, `SuggestionCards`, `MergeSuggestionCard`) + chips/nav/selection tray | Buried at the bottom; operator scrolls past summary chrome to reach every card |

Data-layer facts grounding items 3–4 of the rework:

- `reviewQueueDriver.ts:buildReviewQueue` maps **every** `sortedClusters` entry to a
  `CLUSTER` queue item — no evidence gate. `useWorkbenchFindings.ts:sortClustersBySize`
  only sorts by `identity_count`; a cluster with `identity_count === 0` and
  `representatives: []` is admitted.
- `TopClusterCard.tsx` then renders: empty placeholder `<span class="…__thumb--placeholder">`,
  meta line "0 faces in cluster" (line 236), and live **Review / Name this person / Skip**
  buttons. Review opens a member panel with no members; Name asks the operator to assert an
  identity with zero face evidence.
- `Avatar` (`js/components/ui/avatar.tsx`) has exactly two visual states: image, or a
  300 ms-delayed fallback containing only a `screen-reader-text` span — sighted users see an
  empty box; no loading/missing distinction, no icon (violates A11Y-06 / sr-004).

---

## B. Reworked control pane

### B.1 Overview mockup (order + hierarchy)

```
┌─ Control ────────────────────────────────────────────┐
│ [▸ Scanning… 42% · phase: clustering       (Cancel)] │  ← (a) ACTIVE-JOB STRIP
│                                                      │     conditional: only while a job runs
│ ┌─ Review Suggestions ────────────────── (12) ─────┐ │
│ │ [Matches] [Duplicates]   [Strong] [Weaker]       │ │  ← (b) REVIEW QUEUE promoted to top
│ │  3 of 12                  [Previous] [Next]      │ │
│ │ ┌──────────────────────────────────────────────┐ │ │
│ │ │ [face] [face]   Is this Ada Boyer?           │ │ │
│ │ │ [face] [face]   4 faces in cluster           │ │ │
│ │ │            [Yes] [No] [Review] [Skip]        │ │ │
│ │ └──────────────────────────────────────────────┘ │ │
│ │  0 selected            [Review selection]        │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ ┌─ Recognition findings ───────────────────────────┐ │
│ │ 5 to review · 2 merge candidates · 1 suggested   │ │  ← (c) FINDINGS PANEL demoted below
│ │ name · 4 unlabeled groups                        │ │     summary/triage, no longer gatekeeps
│ │ [◫][◫][◫][◫][◫][◫]  ← preview chips              │ │     the queue
│ │ ⚠ 2 groups awaiting face data      [Resync]      │ │  ← (c') aggregate 0-evidence row (§B.3)
│ │ [Review next: Confirm Ada Boyer] [View all]      │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ ┌─ Scan ───────────────────────────────────────────┐ │
│ │ Scan your library for images that still need …   │ │  ← (d) scan CTA + full JobTimeline
│ │ [Start scan]      Timeline: ▣▣▣▢▢                 │ │     demoted to bottom; still reachable
│ └──────────────────────────────────────────────────┘ │     from zero state (rg-003)
└──────────────────────────────────────────────────────┘
```

Ordering rationale: the queue card is the highest-frequency interaction (accept/reject per
item); scan runs once per session (NAV-06). The queue's single accept/confirm keeps the
pane's one accent primary (existing §7 single-accent machinery, INT-05/UI-06 — unchanged).
While a job is active the compact strip keeps progress + cancel visible without surrendering
the top slot (INT-08, NAV-09). The findings panel keeps its live-region announcements
(A11Y-21) but becomes a summary that *follows* the work surface instead of preceding it —
its "Review next" / "View all findings" targets now scroll *up*; the existing
`findingsDetailRef` anchor mechanism in `ScanTabContent` is direction-agnostic and survives.

Panel labeling: each of (b), (c), (d) becomes a named region (`aria-labelledby` on existing
`h3`s) so the reordering stays navigable by AT (A11Y-04 for the section names).

### B.2 FindingsPreview / findings-panel fallback chain

Two levels, each with an explicit terminal state — nothing falls through to a bare failure.

Panel-level chain (in `WorkbenchFindingsPanel`), first match wins:

```
loading (no data)   → skeleton row + "Checking recognition findings…"     role=status
error (no data)     → ⚠ icon + "Could not load recognition findings."
                      + [Retry] button (NEW — today this state is a dead <p>)
unavailable         → ◌ icon + "Recognition findings are unavailable right now."
                      + hint naming the recognition-service setting (NEW)
degraded (partial)  → render loaded counts; per-source inline chip:
                      "⚠ Unlabeled groups unavailable [Retry]" (extends existing
                      isTopUnlabeledError copy with an action)
empty (success)     → "No findings yet. Run a scan…" (unchanged, UI-04-style true drain)
data                → counts + previews + actions
```

```
┌─ Recognition findings ─────────────┐  ┌─ Recognition findings ─────────────┐
│ ⚠  Could not load recognition      │  │ 5 to review · 2 merge candidates   │
│    findings.                       │  │ ⚠ Unlabeled groups unavailable     │
│    [Retry]                         │  │   [Retry]                          │
└────────────────────────────────────┘  └─ (degraded: partial data kept) ────┘
```

Per-chip chain (in `FindingsPreview`), first match wins — replaces the current
`Avatar src={thumbUrl ?? mediaUrl ?? ''}` terminal branch:

```
1. dedicated face thumb        → Avatar(thumbUrl)            (unchanged)
2. croppable bbox + mediaUrl   → FaceThumbnail crop          (unchanged)
3. mediaUrl or thumbUrl only   → Avatar(uncropped, hedged alt)(unchanged)
4. NO usable url               → data-missing chip (NEW): never Avatar src=""
   ┌────────┐
   │  ▨ ⃠   │   72px chip, --acx-gray-* bg, image-off icon +
   │no image│   visible "No image" text; role=img,
   └────────┘   aria-label "Preview image unavailable"
```

Retry buttons wire to the existing refetch functions already exposed by
`useSuggestionReviewQueries` (the ReviewQueue error branches use them today); the panel gains
no new data paths.

### B.3 The 0-faces cluster card — decision

**Recommendation: filter zero-evidence clusters out of the review queue, and surface them as
one aggregate repair row in the findings panel (mockup B.1 line c').** This is the
"filter out" option, hardened so the failure stays loud rather than silently swallowed.

Definition: a cluster is *zero-evidence* iff `identity_count === 0` **or**
`representatives` is empty/absent (either alone already breaks the card: no meta count or no
thumbs). Gate lives in the pure driver (`buildReviewQueue`) plus the counts model
(`buildWorkbenchFindings` — `counts.unlabeledClusters` and previews must exclude them too, or
the summary advertises work the queue no longer contains).

Why filter rather than render a per-card "members missing / repairing" state:

- Naming a person with zero face evidence is an uninspectable machine claim — the reviewer
  cannot examine any evidence, so the card cannot legitimately offer Name/Review at all
  (HAI-01). A "repairing" card would keep a card-shaped object whose every primary action is
  disabled — chrome that looks actionable but is not (INT-01), occupying the queue's
  one-card-at-a-time position and blocking flow with an item the operator cannot advance
  except by skipping (COG-03).
- Repeatedly skipping broken cards trains the skip reflex that later swallows a real
  ambiguous card (PERC-07).
- De-emphasising the identity-void sample instead of forcing a face decision is exactly the
  EMB-04 / CAL-02 posture: "unknown/not-reviewable-yet" is a designed state, not a forced
  review item.
- BUT plain filtering alone would be a silent wrong answer — the projection produced an
  inconsistent row and nobody would ever learn (RLSE-05, AGT-10 "degrade loudly"). Hence the
  mandatory aggregate row: the findings panel (the summary surface) shows
  `⚠ N groups awaiting face data [Resync]`, icon-paired (A11Y-06), announced via the panel's
  existing live region (A11Y-21). Resync triggers `refetchTopUnlabeled` (and is the natural
  seam for a future projection-repair endpoint); the affordance gives the operator an
  operate/repair path instead of a dead end (HAI-04). One aggregate row for N broken
  clusters keeps the signal rare and proportionate instead of N alarm cards (PERC-07).

Per-state mockups:

```
QUEUE (zero-evidence filtered)            FINDINGS PANEL (aggregate repair row)
┌─ Review Suggestions ──── (11) ─┐        ┌─ Recognition findings ──────────────┐
│  1 of 11    [Previous] [Next]  │        │ … counts …                          │
│ ┌────────────────────────────┐ │        │ ⚠ 2 groups have no face data yet.   │
│ │ [face] Is this Ada Boyer?  │ │        │   They are hidden from review until │
│ │ …only reviewable cards…    │ │        │   their faces sync.      [Resync]   │
│ └────────────────────────────┘ │        └─────────────────────────────────────┘
└────────────────────────────────┘

TODAY (rejected): placeholder card         REJECTED ALT: per-card repair state
┌────────────────────────────────┐        ┌────────────────────────────────┐
│ ▨ (blank)  Name this person    │        │ ▨⏳  Members missing            │
│            0 faces in cluster  │        │     Repairing…                 │
│   [Review]        [Skip]       │        │   [Retry]         [Skip]       │
└─ dead buttons, fake work item ─┘        └─ blocks queue position; trains ─┘
                                             skip reflex (PERC-07)
```

Edge rule: if filtering drains the queue to 0 while the aggregate row shows N>0, the queue
renders the existing drain copy but the findings row still shows the ⚠ repair state — a
zero-evidence-only backlog must not read as "all caught up" (same principle as the existing
UI-03/RLSE-05 top-unlabeled-outage handling in `useWorkbenchFindings`).

### B.4 Avatar state system

`Avatar` (js/components/ui/avatar.tsx) gains an explicit four-state contract, replacing the
binary image/invisible-fallback. Every non-image state pairs a shape/icon with text or an
accessible name — color is never the sole channel (A11Y-06, sr-004). States are driven by
data shape + Radix load status, exposed as `data-avatar-state` for styling/tests (sr-007:
one canonical `as const` state object).

```
state       trigger                        rendering (all --acx-* tokens)
─────────────────────────────────────────────────────────────────────────────
loading     src present, image not yet     ┌╌╌╌╌╌╌┐  shimmer skeleton block,
            loaded (Radix delayMs window)  ╎ ▒▒▒▒ ╎  aria-hidden (transient,
                                           └╌╌╌╌╌╌┘  <300ms usually never seen)

real        src present, load succeeded    ┌──────┐  the face crop/thumb;
                                           │ face │  alt per existing hedged-
                                           └──────┘  claim rules (A11Y-02/HAI-01)

data-       src known-absent (caller has   ┌──────┐  neutral bg + image-off icon
missing     no URL to offer; new explicit  │ ▨ ⃠  │  + visible "No image" label
            prop/branch, replaces src="")  │no img│  role=img, named (A11Y-04)
                                           └──────┘

error       src present, load FAILED       ┌──────┐  neutral bg + broken-image
            (Radix fallback after image    │ ⚠ ▨  │  icon + sr-text "Image
            error)                         └──────┘  failed to load"
```

Distinction that matters: *data-missing* (the record has no thumb — expected, quiet, gray)
vs *error* (the record claims a thumb that failed — a real fault, ⚠ icon). Collapsing them,
as today, is the silent-failure smell (RLSE-05) at chip scale. `TopClusterCard`'s existing
"No image" span and bare `__thumb--placeholder` span both migrate onto the same component
states so the pane has one avatar vocabulary (PERC-06: uniform field lets the real anomaly
pop). Non-interactive chips stay display-only (A11Y-14 target floor applies to controls only
— matches the existing FindingsPreview comment).

---

## C. Heuristics validation table

| Decision | Heuristic (verified in heuristics-canon/lexicons) | Verdict |
|---|---|---|
| Queue promoted to top of control pane | NAV-06 frequency elevates chrome; COG-03 design to the goal filter | Current UI violates NAV-06 (highest-frequency surface at bottom); rework complies |
| One dominant surface per pane (queue card dominates) | LAY-01 contrast engine / one dominant; PERC-06 make it pop | Rework complies; today three sibling panels compete |
| Scan CTA still reachable when queue empty | rg-003 (repo guard: primary controls reachable from zero state) | Complies — scan section always rendered |
| Active-job strip while scanning | INT-08 wait state and cancel; NAV-09 progress indicator; A11Y-21 announce status | Complies; keeps progress+cancel visible after demotion |
| Findings "Review next"/"View all" keep one labeled route into the queue | NAV-07 escape hatch; INT-06 smart action labels (hint names the target) | Complies (existing behavior preserved under new order) |
| Panel error state gains Retry; unavailable names the cause | FORM-05 inline actionable errors; RLSE-05 silent failure is the worst failure | Current UI violates (dead `<p>` error); rework complies |
| Degraded partial-data rendering with per-source retry chip | HAI-13 user is the last error detector (localized cue, not standing banner); RLSE-05 | Complies |
| Chip chain terminal state: explicit no-image chip, never `src=""` | A11Y-06 second channel always; A11Y-02 alt serves purpose; INT-01 affordance match | Current UI violates A11Y-06 (blank box, sr-only text); rework complies |
| Zero-evidence clusters filtered from review queue | HAI-01 evidence before label; CAL-02 unknown is a valid result; EMB-04 de-emphasize identity-void samples; INT-01 (no dead buttons); COG-03 | Current UI violates HAI-01/INT-01 ("0 faces" card with live Name/Review/Skip); rework complies |
| …but surfaced as aggregate repair row, not silently dropped | RLSE-05; AGT-10 degrade loudly; HAI-04 activate–operate–override (Resync affordance); PERC-07 don't habituate alarms (one aggregate row, not N cards) | Complies |
| Zero-evidence-only backlog ≠ "all caught up" | RLSE-05 (mirrors existing UI-03 outage handling in `useWorkbenchFindings`) | Complies |
| Avatar states pair icon+text with color; missing ≠ error | A11Y-06; A11Y-04 name every control/graphic; sr-004 (repo rule: status pairs color with icon) | Current UI violates (invisible fallback); rework complies |
| Hedged alt on machine-suggested labels retained | A11Y-02; HAI-01; HAI-08 uncertainty at the decision granularity | Complies (existing rule, preserved through avatar refactor) |
| Single accent primary preserved across reorder | UI-06 hierarchy over semantics; INT-05 prominent done | Complies (existing §7 accent machinery untouched) |

---

## D. Implementation slices

All paths relative to `apps/prototype-wp-alt-context/`.

**S1 — Queue-first reorder (layout only).**
Reorder render in `js/admin/pages/workbench/ScanTabContent.tsx` (queue block above
`WorkbenchFindingsPanel`; wrap scan CTA + `JobTimeline` in a demoted section; add
conditional compact active-job strip reusing `useJobPipeline` status). Touches
`js/admin/pages/workbench/Panels.tsx` (ScanActionPanel compact variant),
`js/admin/pages/workbench/JobTimeline.tsx` (compact mode), SCSS for section order/tokens.
Tests: `js/admin/pages/workbench/__tests__/` (ScanTabContent order + focus-anchor direction).

**S2 — Zero-evidence cluster gate.**
Add evidence predicate + filter in
`js/admin/pages/workbench/identity-clusters/reviewQueueDriver.ts` (`buildReviewQueue`);
exclude from counts/previews and expose `zeroEvidenceClusterCount` in
`js/admin/pages/workbench/identity-clusters/useWorkbenchFindings.ts`; aggregate repair row +
Resync (wired to `refetchTopUnlabeled` from
`js/admin/pages/workbench/identity-clusters/useSuggestionReviewQueries.ts`) in
`js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx`.
Tests: `identity-clusters/__tests__/reviewQueueDriver*.test.ts`,
`__tests__/WorkbenchFindingsPanel.test.tsx`.

**S3 — Findings fallback chain.**
Retry on error state, unavailable hint, degraded per-source retry chip, and chip
data-missing terminal (drop `src=""` branch) in
`js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx`.
Tests: `__tests__/WorkbenchFindingsPanel.test.tsx`.

**S4 — Avatar state system.**
Four-state contract + `data-avatar-state` + icons in `js/components/ui/avatar.tsx`; migrate
`js/admin/pages/workbench/identity-clusters/TopClusterCard.tsx` (placeholder span + "No
image" span) and `js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx` /
`MergeSuggestionCard.tsx` consumers; tokens in the shared SCSS (`--acx-gray-*`,
`--acx-radius-*`, no hex literals per sr-004).
Tests: `js/components/ui/__tests__/avatar.test.tsx` (new states),
`identity-clusters/__tests__/TopClusterCard*.test.tsx`.

S1 and S4 are independent; S2 precedes S3 only for the repair-row copy. Deferred scope:
a real projection-repair endpoint behind Resync (backend; out of E21-18).
