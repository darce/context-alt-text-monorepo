# WBUX-5. Workbench 2-pane Redesign + Roster v1

> **Task:** `WBUX-5` · branch `feature/wbux-5` · worktree `context-alt-text-monorepo-wbux-1`
> **Date:** 2026-07-27
> **Grounding (read, do not duplicate):**
> - Assessments: WBUX-1 `docs/assessments/current/workbench-ui-refactor-assessment-2026-07-04.md`, WBUX-2 `docs/assessments/current/roster-dashboard-workbench-ux-assessment-2026-07-04.md`.
> - UX-map SSOT (this branch): `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json`, `roster-people.uxmap.json` (+ rendered `.md`), spatial preview `workbench-2pane.preview.md`.
> - Frontend code map + heuristics digest built for this task (scratch; conclusions folded in below).
> - Heuristic ids in `[XXX-nn]` are stable lexicon citations from `interaction-ux.md` / `engineering.md` / `accessibility.md`, verified present 2026-07-27.

## Goal

Turn the single-column Workbench into a **two-pane operator surface** — LEFT a control surface (recognition run · cluster map · name & curate), RIGHT the media library table gaining alt-text and long-description columns — with cluster selection **coordinating** both panes over one shared selection. Ship a **people-first Roster v1** where clusters are a drawer, not a tab. The recognition target is InsightFace on `:10010` (interim, until FIR stabilizes), surfaced **read-only** because it is server-resolved.

## Scope departure — needs operator sign-off

The E21 "Public MVP UX/UI Polish" epic is constrained to **no backend contract changes**. This direction **requires two new backend surfaces** (a 2D-projection endpoint and a long-description media field — see Data Dependencies). WBUX-5 is therefore a **v0.5.0-candidate direction, not an E21 polish task**, even though it is filed alongside the WBUX series. Two things need an operator decision before backend slices are funded: (1) confirm the backend-change scope, and (2) reconcile ownership with in-flight E21 roster/shell tasks (see Ownership Reconciliation).

## Grounding — verified code reality

The redesign is drawn against the current implementation, not an imagined one. Three findings reshape the plan:

- **Long descriptions have no field.** `WorkbenchMediaItem` (`api/generated/workbench-media-item.ts`) exposes only `altText` — no `description` / `caption` / `longDescription` anywhere in the media schema or detail model. The long-description column has nothing to bind to yet.
- **The cluster map has no data.** There is no UMAP / 2D-coordinate / scatter data in the frontend; `ClusterSummary` carries counts and sample identities but no `x/y`. The only spatial data is per-face `bbox` (image pixels) and 3D head pose (`debug_metrics.pose`, pitch/yaw/roll). "embeddings" is **banned UI vocabulary** (enforced by a banned-strings test) — user copy says "cluster map".
- **The endpoint is server-resolved.** `src/api/class-recognition-endpoint-resolver.php` resolves the URL by precedence (`ACX_RECOGNITION_URL` constant → `acx_recognition_base_url` filter → `acx_recognition_url` option → empty); local dev default is `:8000`, not `:10010`. There is **no UI toggle** (RECOG-1 retired the option-writing UI). Selecting InsightFace `:10010` is a constant/filter, not an operator control.

What is already healthy: the `--acx-*` design-token surface is complete across all six families the redesign needs (color/gray/text/shadow/radius/font-weight), asserted by `design-tokens.test.ts` (only `--acx-gray-800` is absent from the ramp).

## Decisions

- **Clusters live in the Workbench left pane; retired from Roster.** Cluster building/naming is an operator loop, not a people-directory concern. Roster becomes people-first; cluster review there is a drawer (`?cluster=`). Consistent with the golden fixture's retired clusters-tab and with E21-9's direction.
- **Recognition endpoint is read-only status, not a switcher.** Topbar and left-pane `z-endpoint` show the resolved target + health only (RECOG-1). The "change endpoint" affordance links to Settings (`act-view-endpoint-settings`), which documents the constant/filter — it does not write an option.
- **Naming uses commit-before-reveal.** The name & curate form takes the operator's independent judgment *before* revealing the model's top candidate, then reconciles `[HAI-15]`; a confirm-only screen logs agreement, not verification. Candidate shortlist is **bounded** with the count recorded `[HAI-16]`, every cluster/match links to its source frames `[HAI-01]`, and the reference set spans captures rather than one image `[HAI-17]`.
- **The cluster map ships list-first, scatter as a dependency-gated fast-follow.** The left pane is usable as a **cluster list** with coordinated selection on day one (no new backend); the 2D scatter is added only when the projection endpoint exists. This de-risks the whole redesign from the one surface that needs new data.
- **AI output is a proposal, never the answer.** Alt-text / long-description suggestions ship the accept / edit / regenerate triad `[HAI-12]`/`[INT-11]`, disclose synthetic authorship `[HAI-14]`, and the operator remains the last error detector on the caption at risk `[HAI-13]`. AI-generated captions must themselves meet WCAG / ATAG `[A11Y-34]`.

## Data dependencies (gate the backend slices)

| Dep | What is missing | New surface required | Gates |
| --- | --- | --- | --- |
| DEP-1 | Long-description has no media field | media schema field + REST read/write + WP proxy + regenerated generated type | Slice 5 |
| DEP-2 | No 2D projection data exists | backend 2D-projection endpoint (cluster/face → `x,y`), cached/incremental | Slice 4 |

Both are **new backend contracts** and must be specced + owned before their slice starts. Until then the left pane is cluster-list-only and the library carries the alt-text column only.

**DEP-2 contract preconditions (must be fixed before Slice 4 starts):**

- **Consistency / invalidation model.** The projection is a derived cache keyed to a recognition run + endpoint dimensionality. Switching endpoint (`:10010` InsightFace 512d ↔ FIR/SFace 128d) or re-running recognition **invalidates** it. On invalidation a stale `?cluster=<id>` deep-link (and any coordinated selection over it) must resolve to an **explicit "this cluster no longer exists / re-run recognition" empty state — never a silent mis-filter or an empty-looking success**. The endpoint returns a `projection_version` (or run id) so the client can detect staleness; the contract states whether projection is recomputed per run or incrementally cached.
- **Bounded point count.** The scatter must not render an unbounded point set. `[VIZ-09]` caps *colours* (~6–12), not *points*; a projection of thousands of faces is an unbounded-result render (rg-007 spirit). The endpoint caps/aggregates server-side — representative points per cluster with a member-count badge, or downsampled/zoom-loaded points — and the contract names the cap and the aggregation rule.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compat? | Verification |
| --- | --- | --- | --- | --- | --- |
| Recognition endpoint resolve | PHP plugin | `class-recognition-endpoint-resolver.php` | none (read-only surfacing) | n/a | existing resolver tests |
| Media item schema | backend + WP + FE type | `workbench-media-item.ts` (alt only) | **add long-description field** (DEP-1) | no (greenfield) | schema/contract test + generated-type parity |
| Cluster projection | backend | none | **new 2D-projection endpoint** (DEP-2) | no (new) | contract fixture + viz a11y check |
| Cluster read | backend | `ClusterSummary` / `ClusterListResponse` | none (list reuse) | n/a | existing recognition tests |
| Deep-link params | FE | `?cluster=`, `?person=`, `?panel=` | extend for coordinated selection | shim per E21-10 | e2e URL round-trip |

## Heuristic map (per surface)

Full digest is in scratch; the load-bearing rules per redesign surface, with tier (**B**locker / **S**hould):

| Surface | Load-bearing rules | Notes |
| --- | --- | --- |
| (a) Two-pane IA | `[VIZ-15]` coordinate views · `[NAV-04/05]` IA + MECE split · `[NAV-06/08]` frequency + zero-state · `[NAV-11]` deep-link state · `[LAY-01]` one dominant region · `[A11Y-08]` reflow 200%/320px | VIZ-15 is the spine of the whole design |
| (b) Cluster map | `[VIZ-01]`/`[VIZ-07]`/`[A11Y-06]` categorical identity, redundant channel, survive greyscale (**B**) · `[VIZ-08]` no rainbow for ordered · `[VIZ-09]` cap ~6–12 colours · `[VIZ-06]` additive highlight · `[HAI-08]` uncertainty at decision granularity | colour-alone cluster identity is a Blocker |
| (c) Recognition loop | `[HAI-01]` evidence before label · `[HAI-02]` correction reaches source · `[HAI-11/13]` keep edit path, last error detector · `[INT-07]` preview merge/split · `[INT-09]` reversible · `[INT-10]`/`[HAI-04]` status-predict-stop / activate-operate-override (all **B**) · `[HAI-15/16/17]` commit-before-reveal, bounded set, every reference (**S**) | densest Blocker cluster |
| (d) Library table | `[A11Y-02]` alt serves purpose · `[A11Y-33/34]` authoring UI + auto-gen accessible · `[HAI-12/13]` proposal not answer · `[FORM-05]` inline errors (all **B**) · `[UI-04]`/`[LAY-06]`/`[TYPE-08]` weight+grey ramp, tabular numerals | filename-alts fail the column's whole reason to exist |
| (e) Roster v1 | `[COG-02]` recognition over recall · `[NAV-10]` feature+search+browse · `[NAV-05]` MECE person states · `[INT-06]` smart action labels + `[A11Y-04]` name every control (**B**) · `[HAI-01/17]` evidence + every reference · `[LAY-10]` designed zero-state · `[A11Y-14]` target size | no bespoke roster family — borrows NAV/COG/HAI |

## Ownership reconciliation (MECE)

WBUX-5 overlaps three E21 tasks; **resolution: EXTEND, not absorb** — verified against the branch base 2026-07-27, all three have substantially landed, so WBUX-5 owns net-new behavior on top of existing seams and does not re-own their scope:

- **E21-11** (workbench context decomposition) — **landed prerequisite**. `WorkbenchProvider` (`pages/workbench/WorkbenchContext.tsx`) already composes `WorkbenchNavProvider → WorkbenchMediaProvider → JobPipelineProvider → ClusterPanelProvider → MergeSurvivorProvider`, consumed via `useWorkbenchNav` / `useJobPipeline` / `useWorkbenchMediaContext` / `useClusterSelection`. Slice 1 builds the two-pane layout on this stack; it adds **no new provider** and does not re-litigate the decomposition.
- **E21-9** (person-first roster, clusters-tab retirement) and **E21-12** (roster zero-state) — **landed**. `RosterPage.tsx` already renders `PersonWorkspacePanel`, `RosterEntriesSection`, `NeedsAssignmentSection`, and a `ClusterDrawerPanel` overlay (clusters are already a drawer, not a tab). Slice 6 **extends** these components (evidence links, action-label a11y, target-size floor); it does not absorb their ownership.

Operator override: if any of these regress or are reverted before WBUX-5 starts, Slice 1/6 fall back to absorb (single owner). Absent that, extend stands.

## Slice delivery

Each slice ships behavior + proof. Slices 1–3 and 6 need **no new backend** and can land first; 4 and 5 are dependency-gated.

### Slice 1 — Two-pane shell scaffold

**Goal:** Split `WorkbenchPage` into a LEFT control host and RIGHT library host with a resizable, collapsible splitter; existing Scan content rehomed without behavior loss.

**Change sites:** `WorkbenchPageContent` (`pages/WorkbenchPage.tsx`) — replace the single `Tabs`/`WORKBENCH_SECTIONS` shell with the two-pane layout; the existing `WorkbenchProvider` stack (`WorkbenchContext.tsx`) already supplies nav/media/pipeline/cluster contexts, so **no new provider** — the layout consumes `useWorkbenchNav` (collapse + `?panel=`), `useJobPipeline`, `useWorkbenchMediaContext`. `ScanTabContent` (`pages/workbench/ScanTabContent.tsx`) is rehomed into the left control host; `MediaSelectionTableBody` moves to the right library host.

Changes: introduce `workbench-2pane-shell` layout (control host + library host + splitter); move recognition/cluster controls left, the media table right; drive collapse + active-cluster via URL params `[NAV-11]`; one dominant region via weight/size `[LAY-01]`; designed zero-state for each pane `[LAY-10]`/`[NAV-08]` (rg-003: primary controls reachable from zero selection). Tokens only (`--acx-*`), no literals (sr-004).

Proof: RTL renders both hosts + splitter from zero state; Playwright reflow at 200% zoom and 320px with no 2-D scroll `[A11Y-08]`; keyboard-only walk reaches both panes and the splitter has a keyboard resize + `role` wired `[A11Y-04]`.

### Slice 2 — Media library table + alt-text column (existing field)

**Goal:** Reshape the right-pane table with columns Select / thumb / title / status / **alt-text** / people, inline alt editing, a needs-alt filter, and the AI-suggest triad — using only today's `altText`.

**Change sites:** `MediaSelectionTableBody` (`pages/workbench/MediaSelectionTableBody.tsx`) — add the alt-text column + inline editor; `useMediaSelectionState` (`hooks/useMediaSelectionState.ts`) for row edit state; `useWorkbenchFilters` for the needs-alt filter; `useWorkbenchMedia` (`hooks/useWorkbenchMedia.ts`) / `workbenchMediaApi.ts` for the alt write. Bind to the existing `WorkbenchMediaItem.altText` (`api/generated/workbench-media-item.ts`) — no new field.

Changes: table hierarchy by weight + grey ramp and tabular numerals, not size/frames `[UI-04]`/`[LAY-06]`/`[TYPE-08]`; inline alt edit with inline actionable errors `[FORM-05]`; AI caption surfaced as accept / edit / regenerate `[HAI-12]`/`[INT-11]`, labelled synthetic `[HAI-14]`, verify cue localized to the row at risk `[HAI-13]`; alt authored to serve purpose with explicit decorative path `[A11Y-02]`; editor keyboard-operable, no traps `[A11Y-33]`; AI-generated alt meets WCAG or prompts `[A11Y-34]`.

Proof: RTL for inline edit + needs-alt filter + suggest triad; axe + keyboard walk on the editor; banned-vocabulary test stays green (no "embeddings").

### Slice 3 — Cluster list + coordinated selection + name/curate

**Goal:** Left pane presents the cluster **list** (existing `ClusterSummary`); selecting a cluster sets `?cluster=` and **filters the right library pane** to that cluster's media (coordinated views); name & curate operates on the selection.

**Coordinated-selection contract (fixed here, not an open question):** selecting a cluster has a **dual effect** — it (1) filters the right library pane to that cluster's media *and* (2) focuses the left-pane name/curate form on that cluster. Selection is **reciprocal and symmetric**: selecting a media row (or its person chip) in the right pane linked-highlights the owning cluster in the left `[VIZ-15]`. One shared selection drives both panes; `?cluster=` is the single source of truth, so the state survives reload and deep-link `[NAV-11]`. An empty/invalid `?cluster=` renders the designed empty state, not a blank filtered table.

**Change sites:** `useClusterSelection` (`hooks/useClusterSelection.ts`) + `ClusterPanelContext`/`ClusterPanelProvider` own the shared `?cluster=` selection; `useWorkbenchFilters` (`hooks/useWorkbenchFilters.ts`) applies the cluster filter to the right-pane query; `useMediaSelectionState` reflects the reciprocal row→cluster highlight; the cluster list + name/curate form are new components in the Slice-1 left control host.

Changes: linked selection with shared highlight + aligned partitions `[VIZ-15]`; recognition run exposes status + next step + cancel/undo `[INT-10]`/`[HAI-04]`; naming form is commit-before-reveal `[HAI-15]`, bounded candidate set with count recorded `[HAI-16]`, evidence link to source frames in one action `[HAI-01]`, reference set spanning captures `[HAI-17]`; merge/split preview with commit + back-out on the same surface `[INT-07]` and multilevel undo `[INT-09]`; corrections reach the underlying record + preserve provenance `[HAI-02]`; keep an edit path over accept/reject `[HAI-11]`; cluster uncertainty shown where the operator acts `[HAI-08]`.

Proof: RTL for list-select → library-filter wiring; Playwright coordinated-selection e2e (select cluster → right pane filters → name → people column updates); undo/redo reverses a name assignment; keyboard alt for any drag `[A11Y-15]`.

### Slice 4 — Cluster map (2D scatter) · gated on DEP-2

**Goal:** Replace/augment the cluster list with a 2D scatter fed by the new projection endpoint; lasso/click a region → same `?cluster=` coordinated selection. Point set is **bounded per the DEP-2 cap**; on stale/invalid `projection_version` it falls back to the Slice-3 list with the "re-run recognition" empty state (DEP-2 consistency model).

**Change sites:** new scatter component in the left control host, reading the DEP-2 projection query; reuses `useClusterSelection` for the shared `?cluster=` selection (same seam as Slice 3, so lasso and list selection are interchangeable). No change to the right-pane filter path — the scatter is an alternate *input* to the same coordinated selection.

Changes: cluster identity encoded categorically (hue) with a **redundant** separable channel (shape/glyph) and a capped palette `[VIZ-01]`/`[VIZ-07]`/`[VIZ-09]`/`[A11Y-06]`; sequential-luminance ramp reserved for any ordered field, never rainbow `[VIZ-08]`; selection marked additively (halo/size-up), not by dimming the rest `[VIZ-06]`; per-cluster boundary/membership uncertainty at the decision granularity `[HAI-08]`; small multiples over animation for before/after merge `[VIZ-14]`.

Proof: contract fixture for the projection endpoint; **greyscale + CVD** check proves cluster structure survives desaturation `[VIZ-07]`/`[A11Y-06]`; e2e lasso → coordinated filter; falls back to Slice-3 list when projection data is stale/absent.

### Slice 5 — Long-description column · gated on DEP-1

**Goal:** Add the long-description column + needs-desc filter + inline edit + AI long-desc suggest, backed by the new media field.

Changes: alt-text and long-description are **separate columns** so a scanning operator sees which rows still need each field (needs-alt ≠ needs-desc) `[PERC-01]`/`[UI-04]`; same proposal-not-answer + inline-error + synthetic-disclosure rules as Slice 2; generated-type parity with the new backend field (rg-001, rg-005).

Proof: schema/contract test for the new field end-to-end; generated-type parity check; RTL for the second column + filter; axe/keyboard on the long-desc editor.

### Slice 6 — Roster v1 (people-first) · reconcile with E21-9/E21-12

**Goal:** Extend the existing people-first Roster (E21-9/E21-12 landed) — person directory with a person workspace (`?person=`) and a cluster drawer (`?cluster=`) overlay already present; this slice hardens evidence, a11y, and zero-state.

**Change sites:** `RosterPage.tsx` and its existing children — `RosterEntriesSection` / `RosterEntriesTable` (directory + MECE person states), `PersonWorkspacePanel` (evidence + every-reference), `NeedsAssignmentSection` (needs-review state), `ClusterDrawerPanel` (drawer, already not a tab), `BulkActionBar` / `useRosterBulkConfirmation` (smart action labels, disable-on-empty), `IdentityThumbnail` (target-size floor). `useRosterHooks.ts` / `rosterApi.ts` back the reads. Extend, do not re-create (see Ownership reconciliation).

Changes: recognition-over-recall person picker (face thumbnail + name) `[COG-02]`; find a person by search **and** browse `[NAV-10]`; MECE person states named/unnamed/needs-review `[NAV-05]` with a distinctive status feature `[PERC-02]`; smart action labels that name the person and disable on empty selection `[INT-06]`/`[A11Y-04]`; evidence + every-reference on the person view `[HAI-01]`/`[HAI-17]`; designed zero-state `[LAY-10]` with always-visible person list + Add Person (rg-003); target size floor `[A11Y-14]`; drag reassignment ships a click/keyboard alternative `[A11Y-15]`.

Proof: RTL for directory + person workspace + drawer; zero-state e2e (rg-003); axe + keyboard walk; drag alternative test.

## Verification strategy

- Deterministic: `npm test` (RTL unit for each pane/table/form), token test stays green, banned-vocabulary test stays green.
- Contract/parity: schema + generated-type parity for DEP-1; projection-endpoint fixture for DEP-2 (rg-001, rg-005).
- Runtime-parity / a11y: Playwright reflow (200% / 320px), keyboard-only walkthrough per changed flow, aria-live coverage for every async status surface `[A11Y-08]`; axe is the floor, not the gate.
- Viz-specific: greyscale + CVD screenshot check for the cluster map `[VIZ-07]`/`[A11Y-06]`.
- Full suite runs on the remote gate (`make check-remote`), not local.

## Open questions

Operator-reserved (fund/scope decisions), remaining after plan-analyze:

- Confirm the backend-change scope (DEP-1 long-description field, DEP-2 projection endpoint) and their owners before Slices 4–5 are funded. This is the one true blocker on the gated slices; Slices 1–3 and 6 do not depend on it.
- Bulk-describe cost preview granularity: per-image cost surfaced before start `[INT-07]`.

Resolved during plan-analyze (recorded in-plan, no longer open): absorb-vs-extend → **extend** (Ownership reconciliation); endpoint-switch cluster invalidation + recompute-vs-cache → **DEP-2 consistency model**; coordinated-selection dual-effect semantics → **Slice 3 contract**; cluster-map point bound → **DEP-2 point cap**.

## Not doing

- No recognition-endpoint UI toggle (server-resolved per RECOG-1; read-only status only).
- No "embeddings" in user-facing copy (banned vocabulary; the surface is "cluster map").
- No pixel/token *values* invented here (references `--acx-*`; token direction owned by E21-4).
- No big-bang removal of the current tabbed shell (migration path, not a rip-out).
- No new bulk-describe backend batch endpoint (progressive client UI per E21 constraint, where backend is untouched).

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded the authoritative anchors before editing: the two UX-map SSOTs + spatial preview, the frontend change-site symbols (verified 2026-07-27), and the heuristic lexicon ids cited inline.
- [ ] Recorded boundary ownership: recognition-resolve (read-only, no change), media-item schema (DEP-1 new field), cluster projection (DEP-2 new endpoint), deep-link params (extend per E21-10) — with compatibility noted in the Contract table.
- [ ] Operator sign-off obtained on the two funded decisions: backend-change scope (DEP-1/DEP-2) and the extend-not-absorb ownership resolution.

### Checklist for Slice 1 — Two-pane shell scaffold

- [ ] `WorkbenchPageContent` renders LEFT control host + RIGHT library host + resizable/collapsible splitter on the existing `WorkbenchProvider` stack (no new provider).
- [ ] `ScanTabContent` rehomed left and the media table rehomed right with no behavior loss; collapse/active state driven by URL params.
- [ ] Proof captured: RTL both-hosts-from-zero, Playwright reflow 200%/320px, keyboard walk + splitter keyboard-resize.

### Checklist for Slice 2 — Library table + alt-text column

- [ ] `MediaSelectionTableBody` gains the alt-text column + inline editor bound to existing `WorkbenchMediaItem.altText`; needs-alt filter via `useWorkbenchFilters`.
- [ ] AI-suggest triad (accept/edit/regenerate) surfaced with synthetic-authorship disclosure and row-local verify cue.
- [ ] Proof captured: RTL inline-edit + filter + triad; axe + keyboard on editor; banned-vocabulary test green.

### Checklist for Slice 3 — Cluster list + coordinated selection + name/curate

- [ ] Cluster list drives the dual-effect coordinated selection (filter right pane + focus name/curate) with reciprocal row→cluster highlight, `?cluster=` as SSOT.
- [ ] Name/curate implements commit-before-reveal, bounded candidate set, one-action evidence link, corrections reaching the record, multilevel undo.
- [ ] Proof captured: RTL list-select→filter wiring; Playwright coordinated-selection e2e; undo reverses a name assignment; keyboard alt for any drag.

### Checklist for Slice 4 — Cluster map (2D scatter) · gated on DEP-2

- [ ] DEP-2 contract fixed (consistency/invalidation model + point cap) before implementation; scatter reuses `useClusterSelection`.
- [ ] Cluster identity encoded with redundant non-colour channel; selection additive; stale `projection_version` falls back to Slice-3 list empty state.
- [ ] Proof captured: projection-endpoint fixture; greyscale + CVD structure-survives check; e2e lasso→coordinated filter.

### Checklist for Slice 5 — Long-description column · gated on DEP-1

- [ ] DEP-1 media field specced end-to-end (schema + REST + WP proxy + regenerated type) before implementation; second column + needs-desc filter added distinct from needs-alt.
- [ ] Same proposal-not-answer + inline-error + synthetic-disclosure rules as Slice 2; generated-type parity verified.
- [ ] Proof captured: schema/contract test; generated-type parity; RTL second column + filter; axe/keyboard on long-desc editor.

### Checklist for Slice 6 — Roster v1 (extend E21-9/E21-12)

- [ ] Extend `RosterPage` children (directory, person workspace, needs-assignment, cluster drawer) — evidence + every-reference, MECE person states, smart disable-on-empty action labels.
- [ ] Designed zero-state with always-visible person list + Add Person (rg-003); target-size floor; click/keyboard alternative for drag reassignment.
- [ ] Proof captured: RTL directory + workspace + drawer; zero-state e2e; axe + keyboard walk; drag-alternative test.

## Review Readiness

- [ ] No boundary-touching slice (DEP-1 field, DEP-2 endpoint, deep-link params) is left without matching contract/fixture/generated-type evidence in the same slice.
- [ ] Runtime-parity checks (Playwright reflow, keyboard/SR walk, greyscale+CVD viz check) are included where RTL can mask real behavior; full suite runs on `make check-remote`.
- [ ] Handoff decision records the change, verification, and the DEP-1/DEP-2 contract implications; open findings are fixed or explicitly deferred with rationale.

## Success Criteria

- Operator runs recognition, selects a cluster in the left pane, and the right library pane filters to that cluster's media over one shared selection — no context switch, no lost place.
- Alt-text (and, post-DEP-1, long-description) are separately scannable columns with inline edit and an AI proposal the operator can accept / edit / regenerate.
- Naming captures the operator's judgment before revealing the model's, with evidence one action away and the action reversible.
- Roster is a people directory reachable and useful from zero state; cluster review is a drawer, not a tab.
- Every changed flow passes a keyboard-only + screen-reader walkthrough; the cluster map survives greyscale.
