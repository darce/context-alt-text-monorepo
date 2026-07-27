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

The E21 "Public MVP UX/UI Polish" epic is constrained to **no backend contract changes**. This direction **requires four new backend surfaces** (DEP-1 long-description field, DEP-2 2D cluster-map layout endpoint, DEP-3 media-request cluster-filter param, DEP-4 persisted pre-reveal judgments + multilevel undo — see Data Dependencies). WBUX-5 is therefore a **v0.5.0-candidate direction, not an E21 polish task**, even though it is filed alongside the WBUX series. Two things need an operator decision before backend slices are funded: (1) confirm the backend-change scope (all four deps), and (2) reconcile ownership with in-flight E21 roster/shell tasks (see Ownership Reconciliation).

## Grounding — verified code reality

The redesign is drawn against the current implementation, not an imagined one. Three findings reshape the plan:

- **Long descriptions have no FE field yet; storage is pinned.** `WorkbenchMediaItem` (`api/generated/workbench-media-item.ts`) exposes only `altText` — no `description` / `caption` / `longDescription` on the generated media type or detail model. Long-description **storage** maps to the WP attachment **description** (`post_content`), reusing the existing write path in `src/api/class-settings-controller.php` (the plugin already writes attachment description there) — not `post_excerpt` (caption) and not new post meta. DEP-1 still must expose that value on the workbench media REST read/write surface and regenerate `WorkbenchMediaItem` with a bindable field (see Data dependencies).
- **The cluster map has no data.** There is no UMAP / 2D-coordinate / scatter data in the frontend; `ClusterSummary` carries counts and sample identities but no `x/y`. The only spatial data is per-face `bbox` (image pixels) and 3D head pose (`debug_metrics.pose`, pitch/yaw/roll). "embeddings" is **banned UI vocabulary** (enforced by a banned-strings test) — user copy says "cluster map".
- **The endpoint is server-resolved.** `src/api/class-recognition-endpoint-resolver.php` resolves the URL by precedence (`ACX_RECOGNITION_URL` constant → `acx_recognition_base_url` filter → `acx_recognition_url` option → empty); local dev default is `:8000`, not `:10010`. There is **no UI toggle** (RECOG-1 retired the option-writing UI). Selecting InsightFace `:10010` is a constant/filter, not an operator control.

What is already healthy: the `--acx-*` design-token surface is complete across all six families the redesign needs (color/gray/text/shadow/radius/font-weight), asserted by `design-tokens.test.ts` (only `--acx-gray-800` is absent from the ramp).

## Decisions

- **Clusters live in the Workbench left pane; retired from Roster.** Cluster building/naming is an operator loop, not a people-directory concern. Roster becomes people-first; cluster review there is a drawer (`?cluster=`). Consistent with the golden fixture's retired clusters-tab and with E21-9's direction.
- **Recognition endpoint is read-only status, not a switcher.** Topbar and left-pane `z-endpoint` show the resolved target + health only (RECOG-1). The "change endpoint" affordance links to Settings (`act-view-endpoint-settings`), which documents the constant/filter — it does not write an option. Health includes an explicit **unreachable / degraded** state: disable the recognition-run control, surface retry + last-checked, and preserve last-good clusters/list (and later map) so an interim target such as InsightFace `:10010` failing is operable under `[INT-10]`/`[HAI-04]`, not a silent empty success. Invalidation-on-endpoint-switch remains a separate DEP-2 concern; this state is endpoint-down, not endpoint-switched.
- **Naming uses commit-before-reveal (enforced two-phase machine).** The name & curate form is a reveal-gate state machine, not a soft guideline: `judgment_pending` (operator enters/commits their independent name; model top candidate and confidence are **not mounted**) → `revealed` (top candidate + confidence shown for reconcile) `[HAI-15]`. A confirm-only screen that shows the model first logs agreement, not verification. Candidate shortlist is **bounded** with the count recorded `[HAI-16]`, every cluster/match links to its source frames `[HAI-01]`, and the reference set spans captures rather than one image `[HAI-17]`.
- **The cluster map ships list-first, scatter as a dependency-gated fast-follow.** Day-one left pane is a **cluster list** with URL-synced selection (`?cluster=` via the Slice-3 owner) and name/curate focus — **no new backend**. The **right-pane cluster-wide media filter** waits on DEP-3; **persisted pre-reveal judgments + multilevel undo** wait on DEP-4; the 2D scatter waits on DEP-2. This de-risks layout and selection ownership from the surfaces that need new contracts, without claiming full dual-effect coordination is backend-free.
- **AI output is a proposal, never the answer.** Alt-text / long-description suggestions ship the accept / edit / regenerate triad `[HAI-12]`/`[INT-11]`, disclose synthetic authorship `[HAI-14]`, and the operator remains the last error detector on the caption at risk `[HAI-13]`. AI-generated captions must themselves meet WCAG / ATAG `[A11Y-34]`.

## Data dependencies (gate the backend slices)

| Dep | What is missing | New surface required | Gates |
| --- | --- | --- | --- |
| DEP-1 | Long-description not on `WorkbenchMediaItem` (only `altText` today) | Map long-description to WP attachment **description** (`post_content`) via the existing `class-settings-controller.php` write path; workbench media REST read/write returns/accepts the field; regenerate `WorkbenchMediaItem` (`longDescription`) + generated-type parity | Slice 5 |
| DEP-2 | No 2D cluster-map layout data (`ClusterSummary` has no `x/y`) | Backend `clusterMapLayout` endpoint (per-cluster points → `x,y` + `member_count`), cached/incremental, keyed by recognition run + endpoint dimensionality; FE type + WP REST proxy | Slice 4 |
| DEP-3 | Media list cannot filter by cluster | `fetchWorkbenchMedia` / media REST: add a cluster (or identity-set) filter param beyond today's `page` / `per_page` / `status` / `search` / `ids[]` | Slice 3 full dual-effect (right-pane cluster filter) |
| DEP-4 | No persisted pre-reveal judgment or multilevel undo | mutation contracts for commit-before-reveal storage (operator judgment + bounded candidate count) and LIFO multilevel undo of name/merge/split | Slice 3 name/curate persistence + undo stack |

All four are **new backend contracts** and must be specced + owned before the slice that consumes them starts. Until DEP-3 the left pane is cluster-list + URL selection only (no right-pane cluster-wide filter); until DEP-1 the library carries the alt-text column only; until DEP-4 name/curate ships without persisted pre-reveal or multilevel undo. Do **not** name the layout concept "projection" in code or contracts — the FE already uses that word ~310× for sync-projection (`projectionSyncState`, `projectionSnapshotVersion`, job phase `projecting`). User-facing copy stays **"cluster map"**; data/staleness symbols are `clusterMapLayout` / `clusterMapVersion`.

**DEP-1 storage + contract (must be fixed before Slice 5 starts):** long-description is the WP attachment **description** (`post_content`), not caption (`post_excerpt`) and not new post meta. Writes reuse the plugin path already used for attachment description in `src/api/class-settings-controller.php`. Reads extend the workbench media list/detail responses that feed `WorkbenchMediaItem` (`api/generated/workbench-media-item.ts`); the FE regenerates that type with a long-description field (camelCase peer of `altText`) and asserts generated-type parity in the schema/contract test. Inline edit / AI long-desc suggest follow the same accept/edit/regenerate triad as alt `[HAI-12]`/`[INT-11]`.

**DEP-2 contract sketch (must be fixed before Slice 4 starts):**

- **Request (cache key).** Recognition run id + endpoint dimensionality. Switching endpoint (`:10010` InsightFace 512d ↔ FIR/SFace 128d) or re-running recognition **invalidates** the layout. The contract states whether layout is recomputed per run or incrementally cached.
- **Response shape.** `{ clusterMapVersion: string, points: Array<{ cluster_id: string, x: number, y: number, member_count: number }> }`. Points are server-capped/aggregated (representative point per cluster with a member-count badge, or downsampled/zoom-loaded); the contract names the cap and the aggregation rule. `[VIZ-09]` caps *colours* (~6–12), not *points* — an uncapped face set is an unbounded-result render (rg-007 spirit).
- **WP REST proxy.** New recognition-read route on the plugin, fetched the same way existing recognition cluster reads are (FE query in the `api/recognition/` pattern used by `useRecognitionClusters` / `useRecognitionCluster`). Generated type lives under `api/recognition/types/` with **generated-type parity** asserted beside the contract fixture.
- **Overplotting / occlusion discipline** (distinct from the point cap). Dense clusters still occlude members even under a hard cap; the contract and client must mitigate layered fusion `[VIZ-12]` — controlled opacity/alpha, small positional jitter, and/or aggregate-at-zoom (hull or density mark until the operator zooms) so individual marks stay assignable to a layer. Cap answers *how many*; this answers *how they remain separable when co-located*.
- **Consistency on invalidation.** A stale `?cluster=<id>` deep-link (and any coordinated selection over it) must resolve to an explicit empty state — never a silent mis-filter or an empty-looking success.
- **Failure-mode split (do not conflate).** A transport/fetch error is a **retryable degraded** state — keep last-good `clusterMapLayout` when present, offer retry, and do **not** treat the cluster as invalid. **Only** a true `clusterMapVersion` mismatch (run/endpoint invalidation) triggers the "this cluster no longer exists / re-run recognition" empty state. Collapsing fetch failure into that empty state would brick a still-valid Slice-3 list.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compat? | Verification |
| --- | --- | --- | --- | --- | --- |
| Recognition endpoint resolve | PHP plugin | `class-recognition-endpoint-resolver.php` | none (read-only surfacing) | n/a | existing resolver tests |
| Media item schema | backend + WP + FE type | `workbench-media-item.ts` (alt only); plugin already writes attachment description (`post_content`) via `class-settings-controller.php` | **add long-description field** on `WorkbenchMediaItem` bound to WP attachment description (`post_content`) — REST read/write + regenerate type (DEP-1); not caption/`post_excerpt`, not new post meta | no (greenfield field on existing media read) | schema/contract test + generated-type parity |
| Cluster map layout | backend + WP proxy + FE type | none (no `x/y` on `ClusterSummary`) | **new `clusterMapLayout` endpoint** returning `{ clusterMapVersion, points[{cluster_id,x,y,member_count}] }` via WP REST recognition-read proxy (DEP-2); symbols must not reuse sync-`projection*` vocabulary | no (new) | contract fixture + generated-type parity + viz a11y check; transport error ≠ version mismatch |
| Cluster read | backend | `ClusterSummary` / `ClusterListResponse` | none (list reuse) | n/a | existing recognition tests |
| Deep-link params | FE | `?cluster=`, `?person=`, `?panel=` (overlay only: `conflicts` \| `dead-letter` via `useOverlayParam`) | **add** `?panes=` (or `?collapse=`) for two-pane collapse/host state; **add** URL-synced `?cluster=` owner for workbench coordinated selection (see Slice 3); keep `?panel=` reserved for overlays — do not overload it | no (new FE params; owned here, no E21-10 shim) | e2e URL round-trip preserves overlay + pane state + cluster selection independently |

## Heuristic map (per surface)

Full digest is in scratch; the load-bearing rules per redesign surface, with tier (**B**locker / **S**hould):

| Surface | Load-bearing rules | Notes |
| --- | --- | --- |
| (a) Two-pane IA | `[VIZ-15]` coordinate views · `[NAV-04/05]` IA + MECE split · `[NAV-06/08]` frequency + zero-state · `[NAV-11]` deep-link state · `[LAY-01]` one dominant region · `[A11Y-08]` reflow 200%/320px | VIZ-15 is the spine of the whole design |
| (b) Cluster map | `[VIZ-01]`/`[VIZ-07]`/`[A11Y-06]` categorical identity, redundant non-colour channel, survive greyscale (**B**, **day-one Slice 3** list + linked-highlight — not deferred to Slice 4) · `[VIZ-08]` no rainbow for ordered · `[VIZ-09]` cap ~6–12 colours · `[VIZ-06]` additive highlight · `[HAI-08]` uncertainty at decision granularity | colour-alone cluster identity is a Blocker on the day-one list, not only the gated scatter |
| (c) Recognition loop | `[HAI-01]` evidence before label · `[HAI-02]` correction reaches source · `[HAI-11/13]` keep edit path, last error detector · `[INT-07]` preview merge/split · `[INT-09]` reversible · `[INT-10]`/`[HAI-04]` status-predict-stop / activate-operate-override (all **B**) · `[HAI-15/16/17]` commit-before-reveal, bounded set, every reference (**S**) | densest Blocker cluster |
| (d) Library table | `[A11Y-02]` alt serves purpose · `[A11Y-33/34]` authoring UI + auto-gen accessible · `[HAI-12/13]` proposal not answer · `[FORM-05]` inline errors (all **B**) · `[UI-04]`/`[LAY-06]`/`[TYPE-08]` weight+grey ramp, tabular numerals | filename-alts fail the column's whole reason to exist |
| (e) Roster v1 | `[COG-02]` recognition over recall · `[NAV-10]` feature+search+browse · `[NAV-05]` MECE person states · `[INT-06]` smart action labels + `[A11Y-04]` name every control (**B**) · `[HAI-01/17]` evidence + every reference · `[LAY-10]` designed zero-state · `[A11Y-14]` target size | no bespoke roster family — borrows NAV/COG/HAI |

## Ownership reconciliation (MECE)

WBUX-5 overlaps three E21 tasks; **resolution: EXTEND, not absorb** — verified against the branch base 2026-07-27, all three have substantially landed, so WBUX-5 owns net-new behavior on top of existing seams and does not re-own their scope:

- **E21-11** (workbench context decomposition) — **landed prerequisite**. `WorkbenchProvider` (`pages/workbench/WorkbenchContext.tsx`) already composes `WorkbenchNavProvider → WorkbenchMediaProvider → JobPipelineProvider → ClusterPanelProvider → MergeSurvivorProvider`, consumed via `useWorkbenchNav` / `useJobPipeline` / `useWorkbenchMediaContext` / `useClusterSelection`. Slice 1 builds the two-pane layout on this stack; it adds **no new provider** and does not re-litigate the decomposition.
- **E21-9** (person-first roster, clusters-tab retirement) and **E21-12** (roster zero-state) — **landed**. `RosterPage.tsx` already renders `PersonWorkspacePanel`, `RosterEntriesSection`, `NeedsAssignmentSection`, and a `ClusterDrawerPanel` overlay (clusters are already a drawer, not a tab). Slice 6 **extends** these components (evidence links, action-label a11y, target-size floor); it does not absorb their ownership.

Operator override: if any of these regress or are reverted before WBUX-5 starts, Slice 1/6 fall back to absorb (single owner). Absent that, extend stands.

## Slice delivery

Each slice ships behavior + proof. Slices 1, 2, and 6 need **no new backend** and can land first. Slice 3 **day-one** (cluster list + URL-synced `?cluster=` selection + name/curate focus, no right-pane cluster-wide filter, no multilevel undo) is also backend-free; Slice 3 **full dual-effect** (right-pane cluster filter) is gated on **DEP-3**, and persisted pre-reveal + multilevel undo on **DEP-4**. Slices 4 and 5 remain gated on DEP-2 and DEP-1.

### Slice 1 — Two-pane shell scaffold

**Goal:** Split `WorkbenchPage` into a LEFT control host and RIGHT library host with a resizable, collapsible splitter; existing Scan content rehomed without behavior loss.

**Change sites:** `WorkbenchPageContent` (`pages/WorkbenchPage.tsx`) — **atomic** swap of the vestigial single-tab `Tabs`/`WORKBENCH_SECTIONS` shell for the two-pane layout (Scan content rehomed intact; no staged flag/adapter). The existing `WorkbenchProvider` stack (`WorkbenchContext.tsx`) already supplies nav/media/pipeline/cluster contexts, so **no new provider**. Pane collapse is a **new** URL param `?panes=` (parser/serializer sibling to `useOverlayParam`, plus an `appLinks` contract entry) — **not** `?panel=`, which stays the conflicts/dead-letter overlay. The layout consumes `useWorkbenchNav` (overlay via existing `?panel=`), the new panes-param hook (collapse/host state), `useJobPipeline`, `useWorkbenchMediaContext`; active-cluster URL ownership is Slice 3's `useClusterSelectionParam` (not this slice). `ScanTabContent` (`pages/workbench/ScanTabContent.tsx`) is rehomed into the left control host; **`MediaSelection` (`pages/workbench/MediaSelection.tsx`) moves to the right library host** — it owns the table, toolbar, pagination, filters, describe CTAs, and status surfaces; `MediaSelectionTableBody` is presentational rows only (moves as a child of `MediaSelection`, not the host boundary). **Shell-strip rehome** (today they mount in `.acx-workbench__panels` above `TabsContent` — none may be dropped): `SyncStatusIndicator` → workbench-level chrome above both panes; local-recognition notice (`recognitionSource === 'local'`) → same chrome, beside read-only endpoint status; offline notice (`useSyncOffline`) → workbench-level chrome; `detailTruncationNotice` → right library host (media-bound); synced-in-another-tab notice → workbench-level chrome; `?panel=conflicts|dead-letter` overlays (`ConflictInbox` / `DeadLetterPanel`) stay URL-gated above both panes via `useWorkbenchNav`; `AdvancedDrawer` remains workbench-level.

Changes: introduce `workbench-2pane-shell` layout (control host + library host + splitter); move recognition/cluster controls left, the media table right; drive collapse via `?panes=` and leave overlay on `?panel=` so both restore independently `[NAV-11]`; one dominant region via weight/size `[LAY-01]`; designed zero-state for each pane `[LAY-10]`/`[NAV-08]` (rg-003: primary controls reachable from zero selection). **Reflow / stack rule `[A11Y-08]`:** below a named breakpoint (320px / 200% zoom equivalent) the horizontal split **stacks vertically** with the **library host first** (dominant region `[LAY-01]`), the control host below it, and the splitter collapsing to a section toggle — no simultaneous 2-D scroll. `z-endpoint` / recognition-run chrome surfaces endpoint health: when the resolved target is unreachable or degraded, disable the run control, show retry + last-checked, and preserve last-good cluster/list state so a down interim target (e.g. InsightFace `:10010`) is an operable degraded mode `[INT-10]`/`[HAI-04]`, not a silent empty surface. Tokens only (`--acx-*`), no literals (sr-004).

Proof: RTL renders both hosts + splitter from zero state and asserts each rehomed shell strip still mounts; Playwright reflow at 200% zoom and 320px with no 2-D scroll `[A11Y-08]` (asserts library-first stack + section-toggle splitter); keyboard-only walk reaches both panes and the splitter has a keyboard resize + `role` wired `[A11Y-04]`.

### Slice 2 — Media library table + alt-text column (existing field)

**Goal:** Reshape the right-pane table with columns Select / thumb / title / status / **alt-text** / people, inline alt editing, a needs-alt filter, and the AI-suggest triad — using only today's `altText`.

**Change sites:** `MediaSelection` (`pages/workbench/MediaSelection.tsx`) is the right-pane **host** boundary (table, toolbar, pagination, status filter, `BulkDescribeCta` / describe status, selection wiring via `useWorkbenchMediaContext`); `MediaSelectionTableBody` (`pages/workbench/MediaSelectionTableBody.tsx`) remains presentational rows — the alt-text column + inline editor land at row level there. `useMediaSelectionState` (`hooks/useMediaSelectionState.ts`) for row edit state; `useWorkbenchFilters` for the needs-alt filter. Alt **write** + AI-suggest generate/overwrite use `describeApi.ts` mutations (`write_alt`, `force`, `overwrite_media_ids`; status via `AltTextWriteStatus`) — **not** `useWorkbenchMedia` / `workbenchMediaApi.ts`, which are read-only GET. After accept/edit, invalidate the React-Query keys backing `useWorkbenchMedia`'s 3-stage pipeline (media list → detail-by-ids → identities-by-media) so `useWorkbenchMediaContext` refreshes. Bind to existing `WorkbenchMediaItem.altText` (`api/generated/workbench-media-item.ts`) — no new field.

Changes: table hierarchy by weight + grey ramp and tabular numerals, not size/frames `[UI-04]`/`[LAY-06]`/`[TYPE-08]`; inline alt edit with inline actionable errors `[FORM-05]`; AI caption surfaced as accept / edit / regenerate `[HAI-12]`/`[INT-11]`, labelled synthetic `[HAI-14]`, verify cue localized to the row at risk `[HAI-13]`; **generation-failure state** on the suggest surface (inline error + retry; operator keeps the manual edit path and any good prefix — not full-restart-only) `[HAI-13]`/`[INT-11]`; describe/suggest async status owns a named **polite** `aria-live` region on the row (or table chrome) so load/success/failure are announced without a global toast; alt authored to serve purpose with explicit decorative path `[A11Y-02]`; editor keyboard-operable, no traps `[A11Y-33]`; AI-generated alt meets WCAG or prompts `[A11Y-34]`.

Proof: RTL for inline edit + needs-alt filter + suggest triad; axe + keyboard walk on the editor; banned-vocabulary test stays green (no "embeddings").

### Slice 3 — Cluster list + coordinated selection + name/curate

**Goal:** Left pane presents the cluster **list** (existing `ClusterSummary`); selecting a cluster writes the shared URL selection and focuses name/curate; **full** right-pane cluster-wide media filter lands only with DEP-3; name/curate persistence + multilevel undo land only with DEP-4.

**Coordinated-selection contract (fixed here, not an open question):**

**One URL-synced owner.** A new hook `useClusterSelectionParam` (sibling to `useOverlayParam`: parse/serialize `?cluster=`, `appLinks` entry) — or, equivalently, a `clusterId` field lifted into `WorkbenchNavContext` with the same URL binding — is the **single write-owner** both panes read. Today's `useClusterSelection` is an in-memory `useState<Set<string>>` multi-select (each call site gets its own Set) and must **not** be treated as this owner; `ClusterPanelContext` remains a local reducer `{ mode: 'none'|'label'|'review', clusterId }` for label/review panel mode only and does **not** read or write `?cluster=`.

**Write direction.** Left list (and later scatter) click → write `?cluster=<id>` via the owner. Right-pane media row or person-chip click → write the same `?cluster=<owningClusterId>` (symmetric, not a second store). Programmatic clear → write empty/absent `?cluster=`.

**Echo-suppression.** Subscribers derive highlight from the URL value; they do **not** re-write the param when the derived highlight matches the current value. Row→cluster highlight must not collapse the left pane or flip `ClusterPanelContext.mode`. Invalid/empty `?cluster=` → designed empty state on the name/curate surface, never a blank success table `[NAV-11]`/`[VIZ-15]`.

**Day-one vs DEP-gated dual effect.** Day-one dual effect is (1) focus left name/curate on the selected cluster and (2) reciprocal linked-highlight of owning cluster for rows already on the loaded page. **Cluster-wide right-pane media filter** is **out of day-one scope** — `fetchWorkbenchMedia` today accepts only `page` / `per_page` / `status` / `search` / `ids[]`, so a true cluster filter cannot be expressed client-side; it ships when **DEP-3** adds the media-request cluster-filter param and `useWorkbenchFilters` / `useWorkbenchMedia` pass it through. **Persisted pre-reveal judgments, recorded candidate counts, and multilevel undo** of name/merge/split are **out of day-one scope** until **DEP-4**; day-one name/curate still implements commit-before-reveal **UX** (prompt judgment before reveal) in session memory only `[HAI-15]`.

**Change sites:** new `useClusterSelectionParam` (or nav-lifted equivalent) owns `?cluster=` read/write; left list + right row/chip both call its writer; `ClusterPanelContext` stays mode-only; existing `useClusterSelection` is left for multi-select bulk actions if still needed, not coordination. `useWorkbenchFilters` / `useWorkbenchMedia` / `workbenchMediaApi.ts` gain the DEP-3 cluster filter when that dep lands. Name/curate form + cluster list are new components in the Slice-1 left control host; DEP-4 mutation clients attach when that dep lands.

Changes: linked selection with shared highlight + aligned partitions `[VIZ-15]`; cluster list rows and the reciprocal row→cluster linked-highlight each carry a **non-colour** identity channel — a stable per-cluster label/number/glyph plus a non-hue selection treatment (leading marker or weight change), never hue alone — so day-one list + highlight survive greyscale and CVD `[VIZ-07]`/`[A11Y-06]`; recognition run exposes status + next step + cancel/undo `[INT-10]`/`[HAI-04]`, and when `z-endpoint` / health reports unreachable or degraded the run control is **disabled**, the surface shows retry + last-checked, and last-good cluster list state is preserved (no silent empty success); naming form implements the two-phase reveal-gate (`judgment_pending` → `revealed`) so no candidate or confidence node mounts before the operator commits `[HAI-15]` (session-local day-one; persisted under DEP-4), bounded candidate set with count recorded `[HAI-16]` (persist count under DEP-4), evidence link to source frames in one action `[HAI-01]`, reference set spanning captures `[HAI-17]`; merge/split preview with commit + back-out on the same surface `[INT-07]`, multilevel undo `[INT-09]` **when DEP-4 lands**; name / merge / split corrections write through the existing recognition write path (cluster label / merge-survivor / outbox ops such as `cluster_label_updated` / `cluster_merged` / `identity_reassigned`) onto the underlying cluster or identity record and retain a provenance stamp (source + run id / `source_version`) so the next recognition recompute re-projects the human decision rather than resurrecting the pre-correction label `[HAI-02]`; keep an edit path over accept/reject `[HAI-11]`; cluster uncertainty shown where the operator acts `[HAI-08]`.

Proof: RTL for list-select → name/curate focus + URL round-trip of `?cluster=` with reciprocal row→cluster highlight and **no** write-loop; reveal-gate RTL asserts **no** candidate/confidence node in the tree while `judgment_pending`, only after the commit transition to `revealed`; HAI-02 discrimination test names a cluster, re-runs recognition, and **fails** if the written label/provenance is gone or the pre-correction auto-label returns (prove green can go red) `[HAI-02]`; greyscale/CVD check on the day-one cluster list + linked-highlight `[VIZ-07]`/`[A11Y-06]`; endpoint-unreachable acceptance (run disabled, retry + last-checked, last-good list retained); Playwright e2e for the day-one path, with separate e2e for the DEP-3 filter path (select cluster → right pane filters) and DEP-4 undo/redo reverses a name assignment; keyboard alt for any drag `[A11Y-15]`.

### Slice 4 — Cluster map (2D scatter) · gated on DEP-2

**Goal:** Replace/augment the cluster list with a 2D scatter fed by the new `clusterMapLayout` endpoint (user copy: "cluster map"); lasso/click a region → same `?cluster=` coordinated selection. Point set is **bounded per the DEP-2 cap** and rendered under the DEP-2 **overplotting discipline** (opacity/jitter/aggregate-at-zoom) `[VIZ-12]`. Failure modes stay split per DEP-2: transport/fetch error → retryable degraded (keep last-good layout, offer retry); **only** a true `clusterMapVersion` mismatch falls back to the Slice-3 list with the "re-run recognition" empty state — never treat a failed fetch as cluster-invalid.

**Change sites:** new scatter component in the left control host, reading the DEP-2 `clusterMapLayout` query (WP REST recognition-read proxy + generated type under `api/recognition/types/`); reuses the Slice-3 `useClusterSelectionParam` owner for the shared `?cluster=` selection (same seam as Slice 3, so lasso, list, and keyboard selection are interchangeable writes into one URL SSOT). No change to the right-pane filter path beyond DEP-3 — the scatter is an alternate *input* to the same coordinated selection. Avoid `projection*` symbols for this layout (those names already mean sync-projection in the FE).

Changes: cluster identity encoded categorically (hue) with a **redundant** separable channel (shape/glyph) and a capped palette `[VIZ-01]`/`[VIZ-07]`/`[VIZ-09]`/`[A11Y-06]`; sequential-luminance ramp reserved for any ordered field, never rainbow `[VIZ-08]`; selection marked additively (halo/size-up), not by dimming the rest `[VIZ-06]`; per-cluster boundary/membership uncertainty at the decision granularity `[HAI-08]`; small multiples over animation for before/after merge `[VIZ-14]`; **lasso/marquee is pointer-primary only** — keyboard/non-pointer path is required `[A11Y-15]`: roving focus across points (or cluster group targets) with Space/Enter to add/toggle selection, plus the Slice-3 cluster **list as a multi-select fallback** so selection never depends on drag alone (colour+shape already cover greyscale identity `[A11Y-06]`); overplotting mitigations from DEP-2 applied client-side on the rendered set `[VIZ-12]`.

Proof: contract fixture for the `clusterMapLayout` endpoint (request/response + `clusterMapVersion` + generated-type parity); **greyscale + CVD** check proves cluster structure survives desaturation `[VIZ-07]`/`[A11Y-06]`; e2e lasso → coordinated filter; **keyboard-only** scatter selection (roving focus + Space/Enter, or list multi-select fallback) reaches the same `?cluster=` coordinated filter `[A11Y-15]`; retryable degraded on fetch error; Slice-3 list empty state only on `clusterMapVersion` mismatch or absent layout after invalidation; visual check that co-located marks remain separable under the overplotting rules `[VIZ-12]`.

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
- Correction-survives-recompute (Slice 3, `[HAI-02]`): a discrimination test writes a name/merge/split correction through the recognition write path, stamps provenance (source + run id / `source_version`), re-runs recognition, and **must fail** if the human decision is lost or the pre-correction auto-label resurrects — a green that cannot go red is vacuous.
- Contract/parity: schema + generated-type parity for DEP-1; `clusterMapLayout`-endpoint fixture for DEP-2 (rg-001, rg-005).
- Runtime-parity / a11y: Playwright reflow (200% / 320px), keyboard-only walkthrough per changed flow; **SR live-region contract** — recognition-run status (`useJobPipeline` / left-pane run chrome) owns a named **assertive** `aria-live` region for start/progress/cancel/failure, and describe/suggest status (Slice 2 AI triad) owns a named **polite** region for load/success/generation-failure, so every async status surface is announced by name rather than a generic "aria-live somewhere" check `[A11Y-08]`/`[INT-10]`/`[HAI-13]`; axe is the floor, not the gate.
- Viz-specific: greyscale + CVD screenshot check for the cluster map `[VIZ-07]`/`[A11Y-06]`.
- Full suite runs on the remote gate (`make check-remote`), not local.

## Open questions

Operator-reserved (fund/scope decisions), remaining after plan-analyze:

- Confirm the backend-change scope and owners for **DEP-1** (long-description field), **DEP-2** (2D cluster-map layout endpoint), **DEP-3** (media-request cluster-filter param), and **DEP-4** (persisted pre-reveal judgments + multilevel undo) before the slices that consume them are funded. Slices 1, 2, 6, and Slice-3 day-one (list + URL selection + session name/curate) do not depend on these; Slice-3 full dual-effect needs DEP-3; name/curate persistence + undo need DEP-4; Slices 4–5 need DEP-2/DEP-1.
- Bulk-describe cost preview granularity: per-image cost surfaced before start `[INT-07]`.

Resolved during plan-analyze (recorded in-plan, no longer open): absorb-vs-extend → **extend** (Ownership reconciliation); endpoint-switch cluster invalidation + recompute-vs-cache → **DEP-2 consistency model**; coordinated-selection dual-effect semantics + URL owner (`useClusterSelectionParam`) + day-one vs DEP-3/DEP-4 split → **Slice 3 contract**; pane-collapse param → **`?panes=`** (keep `?panel=` for overlays; no E21-10 shim); cluster-map point bound → **DEP-2 point cap**.

## Not doing

- No recognition-endpoint UI toggle (server-resolved per RECOG-1; read-only status only).
- No "embeddings" in user-facing copy (banned vocabulary; the surface is "cluster map").
- No pixel/token *values* invented here (references `--acx-*`; token direction owned by E21-4).
- No staged dual-shell period: Slice 1's Tabs→two-pane swap is **atomic** (vestigial single-tab shell replaced in one step) with `ScanTabContent`, media table, overlays, and status strips rehomed intact — not a long-lived adapter/flag migration, and not a silent strip drop (see Slice 1 rehome list).
- No new bulk-describe backend batch endpoint (progressive client UI per E21 constraint, where backend is untouched).

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded the authoritative anchors before editing: the two UX-map SSOTs + spatial preview, the frontend change-site symbols (verified 2026-07-27), and the heuristic lexicon ids cited inline.
- [ ] Recorded boundary ownership: recognition-resolve (read-only, no change), media-item schema (DEP-1 new field), cluster-map layout (DEP-2 `clusterMapLayout` endpoint), media cluster-filter (DEP-3), pre-reveal/undo mutations (DEP-4), deep-link params (`?panes=` for collapse; `?panel=` overlay-only; `?cluster=` via `useClusterSelectionParam`) — with compatibility noted in the Contract table.
- [ ] Operator sign-off obtained on the funded decisions: backend-change scope (DEP-1 through DEP-4) and the extend-not-absorb ownership resolution.

### Checklist for Slice 1 — Two-pane shell scaffold

- [ ] `WorkbenchPageContent` renders LEFT control host + RIGHT library host + resizable/collapsible splitter on the existing `WorkbenchProvider` stack (no new provider); atomic Tabs→two-pane swap with Scan content intact; pane collapse via `?panes=` (not `?panel=`).
- [ ] `ScanTabContent` rehomed left and the media table rehomed right with no behavior loss; `?panel=` still opens conflicts/dead-letter overlays independently of `?panes=` collapse state; every prior shell strip rehomed (`SyncStatusIndicator`, local-recognition, offline, `detailTruncationNotice`, synced-in-another-tab, `?panel=` overlays, `AdvancedDrawer`) per the Slice 1 list `[LAY-10]`; below the named reflow breakpoint panes stack library-first with splitter→section toggle and no 2-D scroll `[A11Y-08]`/`[LAY-01]`.
- [ ] `z-endpoint` / run chrome handles unreachable/degraded: run disabled, retry + last-checked, last-good cluster/list retained `[INT-10]`/`[HAI-04]`.
- [ ] Proof captured: RTL both-hosts-from-zero + each rehomed strip still mounts; Playwright reflow 200%/320px (library-first stack); keyboard walk + splitter keyboard-resize.

### Checklist for Slice 2 — Library table + alt-text column

- [ ] `MediaSelectionTableBody` gains the alt-text column + inline editor bound to existing `WorkbenchMediaItem.altText`; needs-alt filter via `useWorkbenchFilters`.
- [ ] AI-suggest triad (accept/edit/regenerate) surfaced with synthetic-authorship disclosure, row-local verify cue, and a **generation-failure** state (error + retry; manual edit retained) `[HAI-13]`/`[INT-11]`; describe/suggest status wired to a named polite live region.
- [ ] Proof captured: RTL inline-edit + filter + triad + failure/retry; axe + keyboard on editor; banned-vocabulary test green; SR announcement of suggest load/fail via the named region.

### Checklist for Slice 3 — Cluster list + coordinated selection + name/curate

- [ ] `useClusterSelectionParam` (or nav-lifted equivalent) is the sole URL-synced `?cluster=` owner both panes read; list/scatter and row/chip writes go through it with echo-suppression; `useClusterSelection` / `ClusterPanelContext` are not claimed as that owner; cluster list + reciprocal highlight carry a non-colour identity channel (label/number/glyph + non-hue marker/weight) `[VIZ-07]`/`[A11Y-06]`.
- [ ] Day-one: cluster list + name/curate focus + reciprocal highlight on loaded rows, with session-local `judgment_pending`→`revealed` reveal-gate `[HAI-15]`, bounded candidate set, one-action evidence link; right-pane cluster-wide filter only with DEP-3; persisted pre-reveal + multilevel undo only with DEP-4; corrections write through the recognition path with provenance that survives recompute `[HAI-02]`; run control disabled under endpoint-unreachable with retry + last-checked + last-good list.
- [ ] Proof captured: RTL list-select→URL→name/curate focus + no write-loop; reveal-gate RTL (no candidate/confidence before commit); HAI-02 discrimination test fails if correction lost after re-run; greyscale/CVD on day-one list; Playwright day-one coordinated highlight; DEP-3 filter e2e and DEP-4 undo e2e when those deps land; keyboard alt for any drag.

### Checklist for Slice 4 — Cluster map (2D scatter) · gated on DEP-2

- [ ] DEP-2 contract fixed before implementation: `clusterMapLayout` request/response (`clusterMapVersion` + capped points), WP REST recognition-read proxy, generated-type parity, failure-mode split (fetch error = retryable degraded; version mismatch only → re-run empty state), and point cap; scatter reuses `useClusterSelectionParam` (same `?cluster=` owner as Slice 3).
- [ ] Cluster identity encoded with redundant non-colour channel; selection additive; overplotting mitigations (opacity/jitter/aggregate-at-zoom) applied per DEP-2 `[VIZ-12]`; keyboard/list path available for scatter selection (not lasso-only) `[A11Y-15]`; no `projection*` layout symbols (reserved for sync-projection elsewhere); stale `clusterMapVersion` falls back to Slice-3 list empty state.
- [ ] Proof captured: `clusterMapLayout` endpoint fixture + parity; greyscale + CVD structure-survives check; e2e lasso→coordinated filter; keyboard-only (or list multi-select) path hits the same filter; overplotting separability check; degraded-vs-stale paths both covered.

### Checklist for Slice 5 — Long-description column · gated on DEP-1

- [ ] DEP-1 media field specced end-to-end (schema + REST + WP proxy + regenerated type) before implementation; second column + needs-desc filter added distinct from needs-alt.
- [ ] Same proposal-not-answer + inline-error + synthetic-disclosure rules as Slice 2; generated-type parity verified.
- [ ] Proof captured: schema/contract test; generated-type parity; RTL second column + filter; axe/keyboard on long-desc editor.

### Checklist for Slice 6 — Roster v1 (extend E21-9/E21-12)

- [ ] Extend `RosterPage` children (directory, person workspace, needs-assignment, cluster drawer) — evidence + every-reference, MECE person states, smart disable-on-empty action labels.
- [ ] Designed zero-state with always-visible person list + Add Person (rg-003); target-size floor; click/keyboard alternative for drag reassignment.
- [ ] Proof captured: RTL directory + workspace + drawer; zero-state e2e; axe + keyboard walk; drag-alternative test.

## Review Readiness

- [ ] No boundary-touching slice (DEP-1 field, DEP-2 endpoint, DEP-3 media cluster-filter, DEP-4 pre-reveal/undo mutations, deep-link params `?panes=` / `?cluster=`) is left without matching contract/fixture/generated-type evidence in the same slice.
- [ ] Runtime-parity checks (Playwright reflow, keyboard/SR walk, greyscale+CVD viz check) are included where RTL can mask real behavior; full suite runs on `make check-remote`.
- [ ] Handoff decision records the change, verification, and the DEP-1/DEP-2 contract implications; open findings are fixed or explicitly deferred with rationale.

## Success Criteria

- Operator runs recognition, selects a cluster in the left pane, and the right library pane filters to that cluster's media over one shared selection — no context switch, no lost place.
- Alt-text (and, post-DEP-1, long-description) are separately scannable columns with inline edit and an AI proposal the operator can accept / edit / regenerate.
- Naming captures the operator's judgment before revealing the model's, with evidence one action away and the action reversible.
- Roster is a people directory reachable and useful from zero state; cluster review is a drawer, not a tab.
- Every changed flow passes a keyboard-only + screen-reader walkthrough; the cluster map survives greyscale.
