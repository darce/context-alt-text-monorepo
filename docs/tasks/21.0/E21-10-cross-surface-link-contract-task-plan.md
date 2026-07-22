# E21-10. Cross-surface link contract + shim/spec migration

> **Metadata**
>
> - **Date**: 2026-07-22
> - **Author**: Claude (Fable 5)
> - **Epic**: [E21 Public-MVP UX polish](../../epics/v0.4.1/public-mvp-ux-polish-epic.md) · Phase 4
> - **Target Branch**: `feature/e21-10` · **Worktree**: `context-alt-text-monorepo-e21-10`
> - **Review Coverage Target**: 2
> - **Depends on**: E21-9 (person-first roster — epic decomposition table); **sequenced after E15-37-FE** (deferred sovereign-read frontend slices touch the same workbench pages — see Preconditions)
> - **Unblocks**: E21-2 CTA retargeting (epic table: "waits on E21-10")

## Objective

Make cross-surface navigation a **typed, single-owner link contract**: one TS module exports every hash-link builder and URL-param codec; consumers import, never re-declare hash strings (REF-19, sr-007). Extend the vocabulary to the Description History surface (`#/description-history?run=<id>`) per the epic's re-baseline amendment ("Workbench decides, Roster curates, Dashboard orients, **History audits & applies**"), move the media-table expand state into a URL param, migrate the e2e specs to canonical deep-links, then retire the legacy `?tab=confirm` shim the epic parked here.

## Problem Statement

Every page hand-writes its cross-surface links. Twelve call sites carry literal `#/...` strings (Current State table); the only typed builder that exists (`workbenchOverlayLinks.ts:5-6`) covers exactly one link shape. Consequences already visible in `main`:

- **Dead params ship silently**: `DashboardRecentActivitySection.tsx:177` links `#/workbench?advanced=open&jobId=${item.jobId}` — no code anywhere reads a `jobId` search param (verified by repo-wide grep), so the param is inert cargo a contract would have rejected at the type level.
- **Two grammars for one word**: roster reads `queue=` as `queue_memberships` ids (`RosterEntriesSection.tsx:98`) while the workbench review queue uses `rq=` precisely because of this collision (E21-5 plan §2). Nothing prevents the next collision.
- **Deep-link state is partial**: the media-table expand/collapse state is component-local (`ScanTabContent.tsx:80` `userExpandedMedia`), so a shared workbench URL cannot reproduce what the sender saw — a NAV-11 violation (shareable views must round-trip through the URL).
- **Shims have no retirement path**: the `?tab=confirm` redirect shim is annotated "shim owned by E21-10" (`WorkbenchNavContext.tsx:43`) and the epic's Hard Constraints keep `?tab=`/`?overlay=`/`?cluster=` shims alive "until e2e specs migrate (E21-10 owns the migration)" — but the specs deep-link only via WP `admin.php?page=` search params today, so the migration has never been specified.

## Constraints

- **Frontend-only**: all edits in `apps/prototype-wp-alt-context/js/admin/` + `tests/e2e/`. Zero backend/PHP/REST contract changes (rg-015 posture; no endpoint or schema is touched).
- **sr-007 / REF-19**: route ids, param names, and param value enums are `as const` objects in the contract module — the single vocabulary owner. Consumers (including tests) import; a guard test makes a re-declared hash literal a red build.
- **Back/forward + deep-link a11y must not regress**: URL-state writes follow the established `{ replace: true }` convention (`useWorkbenchFilters.ts:62` et al.) so filter/expand toggles do not pollute history; deep-link entry must not steal or drop focus and never triggers a surprise context change (A11Y-20); landing surfaces remain keyboard-walkable (A11Y-11) and route-level escape hatches stay intact (NAV-07: full admin nav is always present on every deep-link landing).
- **Coordination with E21-9 (both touch workbench/roster pages)**: E21-9 retires the roster Clusters tab and owns the person-first roster surface. E21-10 owns the *link side* only — the contract stops **emitting** legacy roster `tab=`/`cluster=` links; parser-side retirement of `cluster=`/`getLegacyTab` (`rosterRoute.ts:91-124`) executes in whichever task lands second (see Slice 4 gate). No double ownership of `RosterPage`/`rosterRoute` internals.
- **Greenfield policy**: shims are deleted, not flagged, once their last consumer migrates.
- **Banned vocabulary**: any new user-visible copy passes `banned-vocabulary.test.tsx`; link params never surface raw jargon in copy.

## Preconditions

- **E15-37-FE sequencing**: E15-37 closed with frontend slices 3–4 deferred; if that deferred work is re-activated it edits the same workbench pages (`ScanTabContent`, sync surfaces). This task starts only after confirming E15-37-FE is either still parked or merged — re-verify at `task-start` and record the check as a decision.
- **E21-9 status check**: epic decomposition orders E21-10 after E21-9. If E21-9 has not merged when this task starts, Slices 1–3 may proceed (they do not touch roster internals); Slice 4's roster-parser retirement gate defers per the coordination rule above.

## Terminology

- **Link contract**: the new module `js/admin/navigation/appLinks.ts` — typed builders (`toWorkbench(...)`, `toDescriptionHistoryRun(runId)`, …) returning `#/`-prefixed hrefs, plus param-name constants and value codecs.
- **Builder**: a function producing a canonical href from typed args. **Codec**: a paired serialize/parse for a param a consumer reads back (precedent: `workbenchQueueUrl.ts` `parseQueueState`/`serializeQueueState` — malformed → defaults, never a crash).
- **Shim**: a runtime redirect that rewrites a legacy URL shape to the canonical one (`WorkbenchNavContext.tsx:44-57` `tab=confirm` → `tab=scan&advanced=open`).
- **Entry forwarding**: `ensureHashInitialized` (`routeHelpers.ts:35-51`) copying WP `admin.php` search params into the initial hash. **Not a legacy shim** — it is the canonical WP-menu entry path and stays.

## Current State Analysis (ground truth, verified 2026-07-22 on `feature/e21-10` @ `4b326c54`)

**Routing spine** — `HashRouter` (`App.tsx:25`); `RoutePath` union of 6 routes (`utils/routeHelpers.ts:1`); `extractRouteFromHash` (`routeHelpers.ts:4-33`); WP page-slug → route map (`App.tsx:84-114`); entry forwarding `routeHelpers.ts:35-51` (drops `page`, forwards the rest into the hash — the mechanism e2e deep-links ride today).

**Existing typed surfaces (the seeds, kept/absorbed)** — `workbenchOverlayLinks.ts:5-9` (`buildWorkbenchOverlayHref` + 2 const hrefs); `hooks/workbenchQueueUrl.ts` (`rq=` codec, E21-5); `hooks/useTabParam.ts` / `hooks/useOverlayParam.ts` (validated param state hooks); `pages/roster/rosterRoute.ts:11` `ROSTER_ROUTE_PARAM_KEYS = ['person','queue','face','cluster']` + `parseRosterRoute` (`:96-124`).

**Literal hash-link call sites (12, the migration set)**:

| Call site | Literal |
| --- | --- |
| `pages/DashboardPage.tsx:212` | `#/workbench?status=missing` |
| `pages/DashboardPage.tsx:258` | `#/retention` |
| `pages/dashboard/OrientationCard.tsx:76` | `#/workbench?tab=scan` |
| `pages/dashboard/GuidanceCard.tsx:21` | `#/workbench?advanced=open` |
| `pages/dashboard/GuidanceCard.tsx:50` | `#/roster?tab=entries&personFilter=unassigned` |
| `pages/dashboard/GuidanceCard.tsx:65` | `#/workbench?tab=scan` |
| `pages/dashboard/DashboardRecentActivitySection.tsx:177` | `#/workbench?advanced=open&jobId=…` (dead `jobId`) |
| `pages/dashboard/DashboardSyncHealthSection.tsx:123` | `#/workbench?tab=scan` |
| `pages/roster/RosterEntriesSection.tsx:22` | `#/workbench?tab=scan` |
| `pages/roster/ClusterGrid.tsx:171` | `#/workbench?tab=scan` |
| `pages/workbench/SyncStatusIndicator.tsx:231` | `#/retention` |
| `pages/workbench/identity-clusters/personCommitCopy.ts:16` | `#/roster` (`VIEW_IN_ROSTER_HREF`) |
| `pages/workbench/BulkDescribeReviewLink.tsx:28` | `#/description-history?run=…` |
| `pages/DescribeRunApplyView.tsx:54` | `#/description-history` |

**Param readers (the vocabulary the contract must own)** — workbench: `s,p,perPage,status,rq` (`useWorkbenchFilters.ts:35-46`), `tab,panel,advanced` (`WorkbenchNavContext.tsx:36-59`); description-history: `run` (`DescriptionHistoryPage.tsx:53-58` — non-empty `run` switches the page to `DescribeRunApplyView` keyed by run id); roster: `personFilter` (`RosterPage.tsx:90`, `RosterEntriesSection.tsx:97,101` — only value read: `unassigned`), `queue` (`RosterEntriesSection.tsx:98`), `person/queue/face/cluster` + legacy `tab` (`rosterRoute.ts:96-124`).

**Legacy shim** — `WorkbenchNavContext.tsx:43-57`: `tab=confirm` → `tab=scan` + `advanced=open`, comment-tagged "shim owned by E21-10". Roster side: `getLegacyTab` (`rosterRoute.ts:91-94`) accepts `tab=clusters|entries`; `cluster=` selects the Clusters tab (`:109-116`). No `overlay=` param exists anywhere — the epic constraint's "`?overlay=`" is today spelled `panel=` (`useOverlayParam` in `WorkbenchNavContext.tsx:37`); the constraint is satisfied by the contract owning `panel`.

**Media-table expand state** — `ScanTabContent.tsx:80` `userExpandedMedia` (local `useState`); reset-to-collapsed when findings first appear (`:104-109`); `isMediaCollapsed` derivation (`:111-112`); `onExpand` wired at `:234` → `MediaSelection.tsx:103` (`MediaSummaryBar onExpand`). Not URL-visible; a reload or shared link always re-collapses.

**E2E deep-linking** — specs navigate via `getAcxAdminRouteUrlWithParams` (`tests/e2e/fixtures/acx-routes.ts`) with WP search params only; 4 specs pass `{ status: 'missing' }` (`first-visitor-walkthrough.spec.ts:162`, `workbench-evidence.spec.ts:105`, `bulk-describe-apply-evidence.spec.ts:87`, `demo-walkthrough.spec.ts:139`). Zero specs use `#/` hash links (verified by grep); zero specs exercise `tab=confirm`, `cluster=`, or `run=`. The fixture's route table (`acx-routes.ts`) also lacks the `description-history` and `retention` slugs.

## Target Outcome

One module owns the cross-surface link vocabulary. Every navigation href in `js/admin` is built by it; a guard test fails on any literal `#/` outside it. `#/description-history?run=<id>` is a first-class contract entry. A shared workbench URL reproduces the media-table expand state. E2E specs deep-link through the contract's canonical shapes, and the `tab=confirm` shim is deleted with proof nothing consumes it. Back/forward and keyboard/AT behavior are unchanged except where the URL now honestly restores state.

## Contract and Boundary Impact

| Boundary | Today | After E21-10 | Contract change? |
| --- | --- | --- | --- |
| REST / PHP / schema | — | untouched | none |
| Hash routes (`RoutePath`) | 6 routes | same 6 | none |
| Workbench params `s,p,perPage,status,tab,panel,advanced,rq` | scattered literals | names owned by contract constants; same wire shapes | none (wire-compatible) |
| `media` expand param | absent | additive `media=expanded` (absent = collapsed-per-heuristic, today's behavior) | additive |
| `jobId` on dashboard activity link | emitted, never read | dropped from the builder (dead param; decision recorded at implementation) | removal of an inert param |
| `tab=confirm` legacy shape | runtime shim | deleted after spec migration (Slice 4) | legacy removal, gated |
| Roster `tab=`/`cluster=` legacy shapes | parsed + emitted | contract stops emitting; parser retirement deferred to E21-9 coordination gate | emission-side only |
| `#/description-history?run=<id>` | ad-hoc literal | canonical builder + codec | none (formalization) |

## Proposed Solution

**1. Contract module** — new `js/admin/navigation/appLinks.ts` (+ `appLinkParams.ts` if size warrants a split):

- `APP_LINK_PARAMS` `as const` object naming every cross-surface param (`status`, `tab`, `panel`, `advanced`, `personFilter`, `run`, `person`, `media`, `rq`, …) — the one place a param name may be spelled (sr-007).
- Typed builders returning hrefs: `toDashboard()`, `toWorkbench({status?, tab?, advanced?, panel?})`, `toRetention()`, `toRoster({personFilter?})`, `toRosterPerson(personUuid)` (the deep-link E21-5 Slice 3 explicitly deferred here: "no `?person=` deep-link — E21-10 owns that"; `parseRosterRoute:97-104` already recognizes `person=` behind its projection gate notice, so emitting it is safe today and lights up when E21-9's workspace lands), `toDescriptionHistory()`, `toDescriptionHistoryRun(runId)`. Builders take typed value unions imported from their owning enums (`WorkbenchMediaStatus`, `WorkbenchTab`, `WorkbenchOverlay`) — a builder cannot emit a value no reader accepts, and cannot emit a param no reader reads (the `jobId` class of bug becomes unrepresentable).
- Codecs for params consumers read back where no validated hook exists yet (`run`, `media`), following the `workbenchQueueUrl.ts` malformed→default pattern.
- `workbenchOverlayLinks.ts` becomes a thin re-export (or is deleted and its 3 importers repointed) — one owner, no second builder.

**2. Consumer migration + single-owner guard** — repoint all 12+2 literal call sites (table above) to builders; delete the dead `jobId` param with a recorded decision. Guard: a Vitest source-scan (`navigation/__tests__/appLinks.guard.test.ts`) globs `js/admin/**/*.{ts,tsx}` (excluding `navigation/` and test files where fixtures legitimately assert literal shapes) and fails on `#/` string literals — the enforcement that keeps REF-19 true after this task closes. TEST-15: the guard's PR must include a demonstration commit-note that planting `'#/workbench'` in a page file turns it red.

**3. Media expand state → URL** — `useWorkbenchFilters` gains `mediaExpanded`/`setMediaExpanded` over `media=expanded` (absent = collapsed default; `{ replace: true }` like every sibling writer so toggling never pollutes back/forward). `ScanTabContent` replaces `userExpandedMedia` local state with the hook value; the findings-arrival auto-collapse effect (`:104-109`) writes the param off (URL stays honest — NAV-11: what the URL says is what renders). Deep-link entry with `media=expanded` renders the full table with no focus theft (A11Y-20); Back after an in-page navigation restores the pre-navigation expand state because the param travels with the history entry.

**4. Shim/spec migration + retirement** — extend `acx-routes.ts` with the missing `description-history`/`retention` slugs and a `getAcxAdminHashUrl(baseUrl, slug, hashHref)` helper that composes contract builders into spec navigation; add spec coverage for the canonical deep-link shapes (workbench `status=missing` via builder; `run=<id>` history entry; `media=expanded`). Then delete the `tab=confirm` shim (`WorkbenchNavContext.tsx:43-57`) and its `LEGACY_CONFIRM_TAB` export — greenfield, no production bookmarks; the epic's "keep shims until e2e specs migrate" condition is discharged by this slice's ordering (specs first, deletion second, same slice, separate commits). Roster parser legacy (`getLegacyTab`, `cluster=`) is **not** deleted here unless E21-9 has already merged its Clusters-tab retirement — otherwise the contract merely stops emitting those shapes and a coordination note is recorded on both task refs.

## Files and Surfaces to Change

| Kind | Path | Change |
| --- | --- | --- |
| new | `js/admin/navigation/appLinks.ts` | Contract: param constants, typed builders, `run`/`media` codecs |
| new | `js/admin/navigation/__tests__/appLinks.test.ts` | Builder/codec round-trips; malformed-param defaults |
| new | `js/admin/navigation/__tests__/appLinks.guard.test.ts` | Source-scan single-owner guard (no `#/` literals outside contract) |
| edit | `js/admin/pages/workbench/workbenchOverlayLinks.ts` | Fold into contract (re-export or delete + repoint 3 importers) |
| edit | 12 literal call sites (Current State table) | Import builders; drop dead `jobId` param |
| edit | `js/admin/hooks/useWorkbenchFilters.ts` | `media=expanded` state (`mediaExpanded`/`setMediaExpanded`, replace-writes) |
| edit | `js/admin/pages/workbench/ScanTabContent.tsx` | Replace `userExpandedMedia` local state (`:80,104-112,234`) with URL-backed state |
| edit | `js/admin/pages/workbench/WorkbenchNavContext.tsx` | Delete `tab=confirm` shim (`:43-57`) + `LEGACY_CONFIRM_TAB` (Slice 4, after specs) |
| edit | `tests/e2e/fixtures/acx-routes.ts` | Add `description-history`/`retention` slugs; hash-href navigation helper |
| edit/new | `tests/e2e/` spec(s) touching deep-links | Canonical deep-link coverage (`status`, `run`, `media`); no spec references `tab=confirm` |
| test | `js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx` | Extend for `media` param (parse/write/absent-default) |
| test | `js/admin/pages/workbench/__tests__/` (ScanTabContent or extracted logic) | Expand/auto-collapse via URL state; reset-on-findings-arrival preserved |

Related, read-only: `utils/routeHelpers.ts` (entry forwarding stays), `hooks/workbenchQueueUrl.ts` (`rq` codec stays E21-5-owned; contract re-exports its param name only), `pages/roster/rosterRoute.ts` (E21-9 coordination boundary), `DescriptionHistoryPage.tsx` (reader of `run` — unchanged wire shape).

## Verification Strategy

- **Unit (Vitest)**: builder↔reader round-trip for every contract entry (build href → parse hash query with the owning reader's logic → identical typed state); codec malformed-input defaults; guard test red on planted literal (TEST-15 — prove the green can go red before trusting it; TEST-06 — watch each new test fail once against a stubbed/broken builder before wiring it up).
- **E2E (Playwright, LocalWP)**: canonical deep-links land on the right surface with state applied (`status=missing` filter active; `run=<id>` renders the run-apply surface; `media=expanded` renders the full table); back/forward across an expand-toggle + navigate sequence restores state; keyboard walk on a deep-link landing reaches primary controls without focus theft (A11Y-11/A11Y-20). Existing `workbench-axe.spec.ts` and keyboard/live-region suites stay green.
- **Behavioral non-regression**: `App.test.tsx`, `routeHelpers.test.ts`, `useWorkbenchFilters.test.tsx`, `useTabParam.test.tsx` green; full `npm run test` in `apps/prototype-wp-alt-context` per slice; `make check-remote` before merge.
- **Shim-retirement proof**: before deleting the `tab=confirm` shim, a repo grep recorded in the slice decision shows zero emitters of `tab=confirm` (code, specs, docs-served UI copy); after deletion, a spec asserts `tab=confirm` now resolves to the default scan view (graceful unknown-param behavior, not a crash).
- Every slice merges through the pre-merge gate (`handoff_close_check(enforce=True)`); findings live in handoff by ID only.

## Slice Delivery

Sized for remote grok-4.5 HIGH lanes: each slice is a bounded file set with a scoped TEST_CMD and a falsifiable exit.

### Slice 1: Link-contract module + codecs (no consumer changes)
Build `navigation/appLinks.ts` (+ tests): param constants, builders for all shapes in the Contract table, `run`/`media` codecs; `workbenchOverlayLinks` fold decided and implemented (re-export keeps its 3 importers compiling — zero rendered diff). REF-05: contract lands alone, no consumer migration in this diff.
**TEST_CMD**: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/navigation/`
**Exit (falsifiable)**: every builder has a round-trip test that failed once against a deliberately wrong shape (TEST-06 noted in the lane report); `npm run test` green; zero rendered-UI diff.

### Slice 2: Consumer migration + single-owner guard
Repoint the 12 literal call sites + `personCommitCopy.ts`/`DescribeRunApplyView.tsx`; drop dead `jobId` (decision recorded); land `appLinks.guard.test.ts`.
**TEST_CMD**: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/navigation/ js/admin/__tests__/App.test.tsx js/admin/__tests__/banned-vocabulary.test.tsx`
**Exit (falsifiable)**: guard test red when a `#/` literal is planted in a page file (demonstrated, then reverted — TEST-15); repo grep for `'#/` under `js/admin` matches only the contract module and allowed test fixtures; all emitted hrefs byte-identical to before except the removed `jobId` param.

### Slice 3: Media-table expand state as URL param
`useWorkbenchFilters` `media=expanded` + `ScanTabContent` migration; unit tests for parse/write/auto-collapse; e2e deep-link + back/forward assertions.
**TEST_CMD**: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx js/admin/pages/workbench/`
**Exit (falsifiable)**: reload with `media=expanded` renders expanded (fails on today's code by construction); findings-arrival still auto-collapses and clears the param; toggle uses replace-writes (asserted: history length unchanged after N toggles); axe + keyboard suites green.

### Slice 4: Spec migration + shim retirement
`acx-routes.ts` extension + canonical deep-link spec coverage; then delete `tab=confirm` shim + `LEGACY_CONFIRM_TAB`; roster emission-side cleanup; E21-9 coordination gate applied (parser retirement only if E21-9 merged, else coordination note recorded on both refs).
**TEST_CMD**: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/ && npm run e2e:localwp`
**Exit (falsifiable)**: specs navigate via contract shapes (no spec constructs a raw legacy param); `tab=confirm` emitter-grep clean before deletion; post-deletion spec proves `tab=confirm` degrades to default scan view without crash; a11y project (`npm run a11y:localwp`) green on touched surfaces.

## Consolidated Checklist

### Slice 1: Contract module
- [ ] `APP_LINK_PARAMS` + typed builders cover every shape in the Contract table (incl. `toDescriptionHistoryRun`, `toRosterPerson`)
- [ ] `run`/`media` codecs follow malformed→default (never throw)
- [ ] `workbenchOverlayLinks.ts` folded (single owner; importers compiling)
- [ ] Round-trip tests per builder; each observed failing once (TEST-06)

### Slice 2: Migration + guard
- [ ] All literal call sites repointed; emitted hrefs unchanged except `jobId` removal
- [ ] `jobId` drop decision recorded in handoff
- [ ] Guard test lands; red-on-planted-literal demonstrated (TEST-15)
- [ ] banned-vocabulary + App tests green

### Slice 3: Media expand URL state
- [ ] `media=expanded` additive param; absent = today's collapsed-on-findings behavior
- [ ] `ScanTabContent.tsx:80` local state removed; auto-collapse effect writes param off
- [ ] Replace-write semantics asserted (back/forward not polluted); deep-link renders expanded without focus theft (A11Y-20)
- [ ] e2e deep-link + back/forward assertions green

### Slice 4: Specs + shim retirement
- [ ] `acx-routes.ts` gains missing slugs + hash-href helper; specs use contract shapes
- [ ] `tab=confirm` shim + `LEGACY_CONFIRM_TAB` deleted; emitter-grep recorded; graceful-degrade spec green
- [ ] Roster legacy emission stopped; parser retirement executed or explicitly deferred to E21-9 with cross-ref decision
- [ ] Full `npm run test` + `make check-remote` green at HEAD

## Review Readiness

Per-slice: review pass with findings recorded in handoff (by ID), zero open findings, fresh `test_result` at HEAD, `handoff_close_check(enforce=True)`, slice-complete decision. Guards in scope: sr-007 (centralized vocab), rg-003 (deep-link landings keep zero-state reachability), rg-006 (documented TEST_CMDs run as written), REF-19/REF-05 seams above.

## Success Criteria

- [ ] One module owns every cross-surface href; guard test enforces it and is proven falsifiable (TEST-15)
- [ ] `#/description-history?run=<id>` is a first-class typed link; History is a named destination in the cross-surface model
- [ ] A shared workbench URL round-trips media-table expand state (NAV-11); back/forward semantics unchanged for toggles
- [ ] `tab=confirm` shim deleted with recorded proof of zero emitters; legacy roster shapes no longer emitted
- [ ] Dead `jobId` param gone; no builder can emit a reader-less param
- [ ] E2E specs deep-link via contract shapes only; a11y/keyboard/axe suites green on all touched surfaces

## Heuristic IDs cited

- **REF-19** — no information leakage: the link vocabulary is a design decision; today it leaks across 12+ modules — the contract makes one owner.
- **REF-05** — two hats: contract (Slice 1) and consumer migration (Slice 2) are separate diffs.
- **NAV-11** — deep links encode place and state: expand state and run scoping round-trip through the URL.
- **NAV-07** — escape hatch: every deep-link landing keeps full navigation; degraded legacy URLs fall back to the default view, never a dead end.
- **TEST-03** — characterization before change: emitted-href byte-parity asserted before the shim/param deletions flip behavior.
- **TEST-06** — watch each new test fail once before trusting it.
- **TEST-15** — prove the green can go red: the single-owner guard ships with its red demonstration.
- **A11Y-11** — keyboard walk on deep-link landing surfaces.
- **A11Y-20** — no surprise context change on deep-link entry or param restoration.
- Local guards: **sr-007** (centralized enums/params), **rg-003** (zero-state reachability of landing surfaces), **rg-006** (TEST_CMDs run as written), **rg-015** posture (no backend metadata invented — frontend-only task).

All IDs verified against heuristics-canon @`65eefb5` (`~/Development/heuristics-canon/lexicons/`): engineering (REF-05, REF-19, TEST-03, TEST-06, TEST-15), interaction-ux (NAV-07, NAV-11), accessibility (A11Y-11, A11Y-20).
