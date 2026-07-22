# UXP-4. Copy & Disclosure Pass

> **Metadata**
>
> - **Date**: 2026-07-22
> - **Author**: Claude (Fable 5)
> - **Project**: prototype-wp-alt-context (admin SPA)
> - **Task ID**: `UXP-4`
> - **Target Branch**: `feature/uxp-4`
> - **Review Coverage Target**: 2

---

## Objective

One lexicon-governed pass over operator-facing strings and disclosure: every sync/status string names consequence + next action; ops jargon ("Delta sync", "Machine sync", "Sync backlog", sync-strip "Queued") leaves primary surfaces; `syncVocabulary.ts` becomes the *actual* single copy source (the banner duplicates it today); the retention card and advanced drawer stop presenting dead or tutorial-first states.

## Intake

- **Scope one-pager**: `docs/scopes/uxp-ux-pass-decomposition.md` § UXP-4 (UXA-06, UXA-11, UXA-12, UXA-16)
- **String inventory**: `docs/reviews/uxp-1/grok-ux-audit-findings.md` § C (copy table), § D UXG-07, UXG-11, UXG-13, UXG-15
- **Owning epic**: `docs/epics/v0.4.1/public-mvp-ux-polish-epic.md` (E21)
- **Not-Doing** (scope § UXP-4 + global): i18n extraction · visual redesign · new components beyond one help-disclosure · roster IA changes (E21-9) · retention feature work beyond copy + dead-card gating (RES-03 follow-up owns breaker gating) · media-table collapse persistence (UXA-12 mechanics live in the E21-10 amendment; UXP-4 owns only its copy) · server/PHP changes of any kind.

## Problem Statement

Four defects, each verified against the tree this session.

**1. The "single vocabulary source" is not single.** `SYNC_VOCABULARY` (`js/admin/pages/workbench/syncVocabulary.ts`) is the declared canonical copy module (its header says so), yet `degradedModeBannerLogic.ts` re-declares **ten** vocabulary strings as inline `__()` literals: `getDegradedBannerTitle`/`getDegradedBannerMessage` duplicate `'Working offline'`, `'Sync attention needed'`, and `'Showing your local copy; changes will sync when the service returns.'` (= `offlineBannerTitle` / `attentionBannerTitle` / `offlineDetail`), and `getDashboardSyncHealthSummary` re-declares the entire summary set inline — `'Machine sync is healthy…'` (= `healthySummary`), `'Local changes are waiting to sync.'` (= `queuedSummary`), `'Conflict resolution is blocking…'` (= `conflictsSummary`), `'Some sync operations failed…'` (= `failuresSummary`), `'The recognition backend is currently unreachable.'` (= `offlineSummary`), `'Machine state is stale…'` (= `staleSummary`), plus the `'Sync attention needed.'` fallback (= `attentionSummary`). The file's own comment admits the coupling ("Copy must stay in lockstep with getSyncPresentationSummary"), and `getDashboardSyncHealthSummary` renders on the dashboard (`DashboardSyncHealthSection.tsx`). One copy edit now fans out across modules or silently diverges ([REF-19]; UXG-15's lockstep risk realized) — a slice-2 rewrite of `staleSummary` alone would leave the inline `'Machine state is stale'` twin rendering old copy.

**2. The canonical vocabulary itself carries ops dialect.** Inside `syncVocabulary.ts`: `healthySummary` "Machine sync is healthy…" (L28), `staleSummary` "Machine state is stale…" (L34), `queuedBadge` "Queued" (L30), `syncModeDelta`/`syncModeFull` "Delta sync"/"Full sync" (L102–103), `syncBacklog`/`syncBacklogShort` "Sync backlog: pending %1$d, applied %2$d…" (L63–64), and the vague `offlineHeadline`/`resultsErrorHeadline` "Waiting for service…" (L21, L50) that never names *which* service ([WRIT-03]: abstract stand-in for a concrete referent). These render on the primary strip (`SyncStatusIndicator.tsx:226–290` — sync-mode badge, backlog meta line) and the dashboard (`DashboardSyncHealthSection.tsx:109` uses `syncBacklogShort`). "Delta sync" is an internal replication mode presented as if the operator had chosen it ([WRIT-27]: implementation label used as an established term). A fourth "Sync backlog" declaration site hides behind `hasTopologyStatus`: `DeadLetterPanel.tsx` (`__('Sync backlog: %1$d waiting, %2$d applied, %3$d failed, %4$d conflicts.')`) — unlisted in earlier drafts and unexercised by the sweep's Workbench fixture, exactly the fixture-coverage gap this plan diagnoses for the strip.

**3. The retention card is jargon-titled and renders dead.** `DashboardPage.tsx:228` titles the card "Retention posture" ([WRIT-03] enterprise abstraction); when `fetchRetentionStatus` (`api/recognition/retentionApi.ts:69–77`) finds no configured endpoint it resolves `{available:false, policy:null}` without error, and the card renders the heading plus "Retention status is unavailable right now." (`DashboardPage.tsx:230`) with no remediation and no action — an undesigned unavailable state ([RLSE-04]; UXG-11).

**4. The advanced drawer leads with a tutorial and lies in its zero state.** `ConfirmTabContent.tsx:15–23` renders the "What is Clustering?" help card — body copy includes "face embeddings" — unconditionally above the recovery tools ([WRIT-25]: pedagogical voice taxing the expert path; [LAY-04]: the explainer competes with the tools it precedes; UXG-07). Below it, `Panels.tsx:201–205` renders `Latest job — No job yet` / `Status — Pending`: with no job selected, "Pending" asserts a job state that does not exist — the zero state was rendered, never designed ([RLSE-04]).

### Enforcement seam that already exists

`js/admin/__tests__/banned-vocabulary.test.tsx` (E21-1) renders every `pages/` module under representative fixtures and fails on any `BANNED_STRINGS` hit; it also sweeps module-level copy constants that page mocks would otherwise hide (its "review-queue chip" pattern). This is the mechanical gate UXP-4 extends — each copy slice lands its banned/asserted strings there, so the sweep is falsifiable, not a prose promise ([TEST-15]: prove green can go red).

## Constraints

- **Greenfield** (CLAUDE.md): no compatibility shims; rename/rewrite vocabulary keys and their consumers in the same slice.
- **Frontend only.** No PHP, no recognition-service, no endpoint changes. `sync_mode` and `topology_commands` keep arriving in the payload; UXP-4 changes only what renders.
- **Collision policy (mandatory, file-granularity)**: E15-37-FE, E21-9, and E21-10 touch overlapping workbench/roster surfaces and merge separately. The policy is stated per file, not as a blanket ban. **Structural JSX changes are permitted only in files no concurrent task claims** (verified against their plans: E15-37-FE claims `useMediaIdentities`/`useWorkbenchMedia`/`IdentityClusterList`; E21-9 claims roster structure; E21-10 claims link surfaces): (1) `ConfirmTabContent.tsx` help-card → disclosure swap (slice 4); (2) `Panels.tsx` `ConfirmPanel` conditional `Status` row (slice 4); (3) the `syncModeDetails` block removal inside `SyncStatusIndicator.tsx` (slice 2); (4) the `DashboardPage` retention panel conditional unmount (slice 3). **Everything else is string-level and rebase-tolerant**: edits change `__()` literals, vocabulary keys, and copy constants only — no other JSX restructuring of `SyncStatusIndicator`, `DashboardPage` stat grids, roster tables, or media-table components. No tab/route id changes (`rosterRoute.ts` **ids** stay `entries`/`clusters`; only `label` strings may change) — E21-9 owns the Clusters-tab retirement.
- **Copy component styling** uses existing `--acx-*` tokens only (sr-004); the slice-4 disclosure reuses the existing `.acx-workbench-help-card` surface and adds no raw literals. Status badges keep their icon/glyph pairing — copy edits must not strip the non-color channel ([A11Y-06]).
- **Single vocabulary source** (sr-007 analog): after slice 1, no operator-facing sync/status string may be declared outside `SYNC_VOCABULARY` (or a page-local copy-constant module the banned-vocabulary test sweeps). No scattered literals.
- **E21-1 banned-strings discipline**: additions to `BANNED_STRINGS` must be exact operator-visible phrases ("Delta sync", "Machine sync", "Machine state", "Sync backlog", "Retention posture", "Managed Identities") — never bare common words ("Queued", "projection"-substring traps) that legitimate job-phase badges or code identifiers would trip. "Machine state" is banned alongside "Machine sync" because the stale summary's inline twin uses it; banning only "Machine sync" would let the old stale copy survive.
- **i18n intact**: every rewritten string stays inside `__(…, 'alt-context')` / `sprintf` with unchanged placeholder arity.
- Prefer symbol names over line numbers in change sites — line anchors drift.

## Workflow Principles

- **One copy source per surface.** The vocabulary module owns sync/status copy; consumers import, never re-declare ([REF-19]).
- **Consequence + action per state.** Every status sentence answers "what does this mean for me, and what do I do" — the scope's success bar.
- **Ban the phrase, not the word.** The mechanical sweep targets exact retired phrases so it cannot false-positive on legitimate uses.
- **Rename keys when meaning changes** ([NAME-01]): a key whose copy no longer says "backlog" should not be named `syncBacklog` — key names follow the new lexicon so the vocabulary reads truthfully.
- **Copy change and structure change are different hats** ([REF-05]): slice 1 is structural single-sourcing with zero copy change; slices 2–5 change copy on the single-sourced base.

## Terminology

- **Operator vocabulary**: people-first terms an editorial WP admin knows — people, faces, photos, changes waiting to save, the recognition service.
- **Internal-only string**: still exists in code/telemetry/types (`sync_mode: 'delta'`, `topology_commands`), never rendered to the operator.
- **Copy constant module**: an exported `as const` string map (pattern: `personCommitCopy.ts`) that the banned-vocabulary test imports and sweeps directly when page-level mocks hide the rendering component.

## Current State Analysis

**Works today:** `SYNC_VOCABULARY` exists, is a leaf module, and most of `syncPresentation.ts` / `phasePresentation.ts` / `SyncStatusIndicator.tsx` / `DashboardSyncHealthSection.tsx` already import from it. The E21-1 banned-vocabulary sweep enumerates all seven page modules and fails on registry drift. `AdvancedDrawer.tsx` has a correct focus contract (open → focus panel, Esc → restore). Person-commit copy is centralized (`personCommitCopy.ts`) and swept.

**Broken or drifting:** the banner/summary logic duplicates ten vocabulary strings (banner trio + full dashboard summary switch + fallback); `DeadLetterPanel.tsx` declares a fourth inline "Sync backlog" literal; six-plus vocabulary entries carry ops dialect onto primary surfaces; the retention card renders a dead jargon-titled state; the drawer's explainer is unconditional and its zero state shows "Pending" with no job; roster says "Entries", "Clusters", and "Managed Identities" (`RosterEntriesSection.tsx:169`) for overlapping concepts — three names, two referents ([WRIT-06]).

**Deliberately untouched:** `phaseQueued`/`describeQueued` ("Queued" as a *job phase* badge) — a queued job is plain language, not sync topology.

**Scope amendment (normative decision, supersedes the scope line).** The scope one-pager lists strip "Queued" among strings that "become internal-only". This plan decides otherwise: the strip `queuedBadge` is **rewritten to consequence copy ("Waiting to sync"), not hidden** — a silent strip would conceal real pending-work state from the operator, violating the scope's own "every status string names consequence" success bar. The scope's intent (no bare ops-jargon "Queued" on the strip) is satisfied by the rewrite. This is the single controlling decision; implementation lanes follow this table, not the scope line. Recorded here so review argues with the decision, not the omission.

## Target Outcome

Every status string on Workbench/Dashboard/Roster names its consequence and next action; "Delta sync", "Machine sync", "Sync backlog", "Retention posture", and "Managed Identities" cannot re-enter any page surface without a red test; the banner provably renders vocabulary-module strings; the retention card either helps or is absent; the clustering explainer is on demand; the no-job zero state tells the truth.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`
- Heuristics: `heuristics-canon` `writing.md` ([WRIT-02], [WRIT-03], [WRIT-06], [WRIT-25], [WRIT-27]), `engineering.md` ([REF-05], [REF-19], [NAME-01], [RLSE-04], [TEST-06], [TEST-15]), `accessibility.md` ([A11Y-06], [A11Y-21], [A11Y-24]), `design-aesthetics.md` ([LAY-04]). Every ID verified present in `~/Development/heuristics-canon/lexicons/` before citation.
- Handoff/MCP: task ref `UXP-4`; intake decision `claude_uxp1_scope_intake_v1`.

## Contract and Boundary Impact

None. No REST, schema, or PHP boundary changes. The only "contract" touched is the internal `SYNC_VOCABULARY` key set (renames land with all consumers in-slice, greenfield) and the E21-1 `BANNED_STRINGS` registry (additive).

## Proposed Solution

Five slices, each a bounded string-or-single-file unit with a test that goes red before the change and green after. No slice requires operator judgment mid-slice: final copy strings are specified in-plan (implementation lanes transcribe, not compose).

**Copy specification.** Rewrites below are the deliverable strings. Reviewers challenge them here, at plan review — not mid-lane. Standing rewrite rule ([WRIT-02]): every new string uses the word an operator would say out loud — "saved", "waiting", "up to date" — never AI/enterprise diction ("robust", "seamless", "leverage", "posture").

| Key (current → new name) | Current | New copy |
| --- | --- | --- |
| `healthySummary` | "Machine sync is healthy and local changes are caught up." | "Everything is saved and up to date." |
| `staleSummary` | "Machine state is stale and should be refreshed." | "This view may be out of date — sync now to refresh it." |
| `queuedBadge` | "Queued" | "Waiting to sync" |
| `queuedHeadline`/`queuedSummary` | "Local changes are waiting to sync." | "Your changes are saved here and will sync when the service is available." |
| `offlineHeadline`, `resultsErrorHeadline` | "Waiting for service…" | "Recognition service unreachable — showing your local copy." |
| `syncBacklog` → `pendingWorkSummary` | "Sync backlog: pending %1$d, applied %2$d, failed %3$d, conflicts %4$d" | "%1$d waiting, %2$d synced, %3$d failed, %4$d need review" |
| `syncBacklogShort` → `pendingWorkSummaryShort` | "Sync backlog: pending %1$d, failed %2$d, conflicts %3$d" | "%1$d waiting, %2$d failed, %3$d need review" |
| `syncModeDelta`/`syncModeFull` | "Delta sync"/"Full sync" | **deleted** — the mode badge stops rendering (internal detail; `formatSyncModeLabel` and the `syncModeDetails` meta block in `SyncStatusIndicator` are removed) |
| `DashboardPage` retention heading | "Retention posture" | "Your data & retention" |
| retention unavailable body | "Retention status is unavailable right now." | endpoint configured but errored (`useRetentionStatus().isError` — `fetchRetentionStatus` throws on fetch failure): "Retention status could not load. Check the connection on the Settings page." + existing `#/retention` link retained; endpoint **not configured** (query resolves `{available:false}` without error): card not rendered |
| `RosterEntriesSection` heading | "Managed Identities" | "People" |
| `Panels.tsx` no-job zero state | "Status — Pending" | when `jobId == null`: "No scan has run yet — run a scan from the Media step first."; `Status` row renders only when a job exists |
| `ConfirmTabContent` explainer | always-on card | `<details>`-style disclosure, closed by default, summary "What does clustering do?"; body drops "embeddings": "Clustering groups similar faces found during a scan so you can name a whole group at once instead of labeling every photo." |

**Why deletion for the mode badge**: an unrequested internal replication mode has no operator consequence; plain-language relabeling ("Partial update") still surfaces an unactionable detail ([LAY-04]: it competes with actionable meta). The value stays in the payload for debugging.

**Action phrases are pinned to real controls.** `staleSummary`'s "sync now" is backed by the strip's existing stale-state action (`getSyncPresentationSummary` stale case renders `SYNC_VOCABULARY.syncNow` with `kind: 'sync_now'` — `syncPresentation.ts`); no new component. The dashboard health section renders the same summary without its own button — acceptable because the instruction is executable one click away on the Workbench strip; no copy fork.

**Falsifiability mechanics.** Two instruments per slice: (a) `BANNED_STRINGS` additions that are red against the pre-slice tree under fixtures that actually render the phrase — where current sweep fixtures don't exercise a phrase (backlog needs `topology_commands` counts > 0, mode badge needs `sync_mode: 'delta'`), the slice adds a targeted fixture test in the component's own suite (`SyncStatusIndicator.test.tsx`, `DegradedModeBanner.test.tsx`, existing files) so the ban is enforced where the string renders; (b) positive copy assertions on the new strings, written failing first ([TEST-06]).

## Files and Surfaces to Change

| Surface | File : symbol | Change |
| --- | --- | --- |
| vocabulary | `pages/workbench/syncVocabulary.ts` : `SYNC_VOCABULARY` | Copy rewrites + key renames per spec; delete `syncModeDelta`/`syncModeFull` |
| banner + dashboard summary | `pages/workbench/degradedModeBannerLogic.ts` : `getDegradedBannerTitle`, `getDegradedBannerMessage`, `getDashboardSyncHealthSummary` | Replace **all ten** inline literals with `SYNC_VOCABULARY` reads (banner trio + full summary switch + `attentionSummary` fallback) |
| dead-letter overlay | `pages/workbench/DeadLetterPanel.tsx` : topology-status notice | Replace inline "Sync backlog:" literal with renamed `pendingWorkSummary`-family vocabulary key |
| strip | `pages/workbench/SyncStatusIndicator.tsx` : `syncModeDetails`, `backlogDetails` | Remove mode badge + `formatSyncModeLabel` import; consume renamed backlog keys |
| view-model | `pages/workbench/syncPresentation.ts` : `formatSyncModeLabel`, key consumers | Delete `formatSyncModeLabel`; follow key renames |
| dashboard | `pages/dashboard/DashboardSyncHealthSection.tsx` | Consume `pendingWorkSummaryShort` |
| dashboard | `pages/DashboardPage.tsx` : `retentionPosture` panel | Heading, unavailable-state remediation copy, `available:false` → no card |
| drawer | `pages/workbench/ConfirmTabContent.tsx` | Explainer → closed-by-default disclosure; new body copy |
| drawer | `pages/workbench/Panels.tsx` : `ConfirmPanel` | Honest no-job zero state |
| roster | `pages/roster/RosterEntriesSection.tsx`, `pages/roster/rosterRoute.ts` | "Managed Identities" → "People"; tab `label` strings only, ids untouched |
| gate | `__tests__/banned-vocabulary.test.tsx` : `BANNED_STRINGS` | Add "Delta sync", "Machine sync", "Sync backlog", "Retention posture", "Managed Identities" |
| tests | `pages/workbench/__tests__/{SyncStatusIndicator,DegradedModeBanner,degradedModeBannerLogic,syncPresentation,Panels}.test.*`, `pages/roster` + dashboard suites | Per slice, below |

## Related Files

| File : symbol | Note |
| --- | --- |
| `pages/workbench/phasePresentation.ts` | Consumes vocabulary phase keys ("Queued" job-phase badges) — deliberately unmodified |
| `hooks/useRemoteActionGate.ts` : `offlineActionReason` | Already single-sourced, copy acceptable — unmodified |
| `api/recognition/retentionApi.ts` : `fetchRetentionStatus` | The `available:false` producer — read-only dependency, unmodified |
| `pages/workbench/identity-clusters/personCommitCopy.ts` | Copy-constant + sweep pattern slices 3–4 follow |

## Verification Strategy

- Deterministic: `npm --prefix apps/prototype-wp-alt-context test` (full) before close; scoped per-slice TEST_CMDs below.
- Gate: `banned-vocabulary.test.tsx` additions demonstrated red against the pre-slice tree (run before the copy change lands in the same lane; noted in each slice's evidence) — [TEST-15].
- Lint/format: `npm --prefix apps/prototype-wp-alt-context run lint` per slice.
- Runtime parity: `make check-remote` on the committed HEAD before merge.
- Manual (**non-gating** — a demo pass, not merge evidence; every merge-required behavior above has a component test): Workbench strip through healthy/queued/offline states, dashboard with and without a configured retention endpoint, drawer open/close with keyboard. One pass, post-slices, not mid-slice.

## Slice Delivery

### Slice 1: Single-source the banner + dashboard summary (structure only, zero copy change)

**Goal**: `SYNC_VOCABULARY` is provably the only declaration site for every string `degradedModeBannerLogic.ts` renders.

Changes: `getDegradedBannerTitle` returns `SYNC_VOCABULARY.offlineBannerTitle` / `.attentionBannerTitle`; `getDegradedBannerMessage` returns `SYNC_VOCABULARY.offlineDetail`; `getDashboardSyncHealthSummary`'s switch returns `SYNC_VOCABULARY.healthySummary` / `.queuedSummary` / `.conflictsSummary` / `.failuresSummary` / `.offlineSummary` / `.staleSummary` and its fallback returns `SYNC_VOCABULARY.attentionSummary`. All ten inline `__()` literals are deleted; the "lockstep" comment is removed because the coupling it warned about no longer exists. Rendered output is byte-identical (the vocabulary values are byte-duplicates today).

**TEST_CMD**: `npm --prefix apps/prototype-wp-alt-context test -- degradedModeBannerLogic DegradedModeBanner DashboardSyncHealthSection`

Proof — **module-mock sentinel discrimination is the primary evidence** ([TEST-15]): the new unit `vi.mock`s `./syncVocabulary` with sentinel values (e.g. `offlineBannerTitle: 'SENTINEL_OFFLINE_TITLE'`) and asserts `getDegradedBannerTitle(offlineHealth)` (and each `getDashboardSyncHealthSummary` branch) returns the sentinel. This is red against the pre-slice tree — the inline literals ignore the module — and green only when the functions actually read the export. (A plain `===` comparison against the real export cannot go red: JS `===` is value equality and the duplicated literals are already equal byte-for-byte, so it proves nothing.) Existing `DegradedModeBanner.test.tsx` and dashboard snapshot assertions stay green unmodified (no copy change).

### Slice 2: Sync vocabulary rewrite + mode-badge removal

**Goal**: The strip and dashboard speak operator language; "Delta sync", "Machine sync", "Sync backlog" cannot re-enter.

Changes: copy spec rows 1–8 (rewrites, `syncBacklog*` → `pendingWorkSummary*` key renames with all consumers — `SyncStatusIndicator.tsx`, `DashboardSyncHealthSection.tsx`, **and `DeadLetterPanel.tsx`**, whose topology-status notice re-declares its own inline "Sync backlog:" literal behind `hasTopologyStatus` and switches to the renamed vocabulary key; delete `syncModeDelta`/`syncModeFull`, `formatSyncModeLabel`, and the `syncModeDetails` block). Placeholder arity preserved (`%1$d…%4$d`).

**TEST_CMD**: `npm --prefix apps/prototype-wp-alt-context test -- syncVocabulary syncPresentation SyncStatusIndicator DashboardSyncHealthSection DeadLetterPanel banned-vocabulary`

Proof: `BANNED_STRINGS` gains "Delta sync", "Machine sync", "Machine state", "Sync backlog". Targeted fixture tests render `SyncStatusIndicator` with `sync_mode: 'delta'` and `topology_commands: {pending:2, applied:1, failed:1, conflict:1}` and assert no banned phrase and the new counts copy — red pre-change (badge renders "Delta sync" today); a sibling fixture renders `DeadLetterPanel` with `topologyStatus` counts > 0 and asserts no "Sync backlog" and the new vocabulary string — red pre-change (the sweep's Workbench fixture supplies no topology status, so without this fixture the panel's literal would survive unswept). A vocabulary unit test asserts no `SYNC_VOCABULARY` value matches `/machine sync|machine state|delta sync|sync backlog/i`, so the module itself is swept, not just page fixtures. `phasePresentation.test.ts` stays green (job-phase "Queued" untouched).

### Slice 3: Retention card — operator heading, remediation, no dead card

**Goal**: The dashboard retention panel helps or disappears.

Changes: heading "Your data & retention"; state discrimination via `useRetentionStatus()` (react-query): `data.available === false` (endpoint not configured — `fetchRetentionStatus` resolves without error) → panel not rendered; `isError` (endpoint configured, fetch threw) → remediation copy per spec (settings pointer + retained `#/retention` link — the failure state keeps a designed action, [RLSE-04]). Strings live in a `retentionCardCopy.ts` copy-constant module (sweep pattern) since `DashboardPage` renders it conditionally.

**State matrix ([A11Y-24]: a state isn't designed until its focus and announcements are):** loading → panel absent, no new UI (query resolves before first meaningful dashboard interaction; no spinner added); `available:false` → panel absent from initial render — nothing is removed mid-session, so no focus move and no announcement are required; `isError` → static remediation text + link rendered at initial load — no focus steal, no live region ([A11Y-21] not triggered: nothing updates asynchronously after render). No disappearing-content transition exists in any row, which is why no focus-management work is in scope.

**TEST_CMD**: `npm --prefix apps/prototype-wp-alt-context test -- DashboardPage banned-vocabulary`

Proof: `BANNED_STRINGS` gains "Retention posture" — red pre-change (the sweep's retention fixture is `available:true`, heading renders). Unit (gating, not manual): `available:false` fixture → `Retention` panel absent from the DOM; `isError` fixture → remediation copy present **and** the link's `href` equals `#/retention`. Copy constants swept via `import *` like `personCommitCopy`.

### Slice 4: Advanced drawer — on-demand explainer + honest zero state

**Goal**: Recovery tools first; no fabricated "Pending".

Changes: `ConfirmTabContent.tsx` explainer becomes a native-`details`-pattern disclosure (closed by default, summary "What does clustering do?", body per spec, no "embeddings"); reuses `.acx-workbench-help-card` styling, any new rule uses `--acx-*` tokens only (sr-004). `ConfirmPanel` (`Panels.tsx`): `jobId == null` → single zero-state line per spec, `Status` row rendered only with a job. Disclosure is a real `<details>/<summary>` (native keyboard + semantics; no ARIA invention); the zero state is static text, no live-region change ([A11Y-21] not triggered — nothing updates asynchronously here).

**TEST_CMD**: `npm --prefix apps/prototype-wp-alt-context test -- ConfirmTabContent Panels AdvancedDrawer`

Proof: component tests — explainer body absent from the accessible tree until the summary is toggled (red today: always rendered); the recovery tools render with the disclosure closed (gating assertion for "recovery tools first" — not left to the manual pass); `ConfirmPanel` with `jobId=null` shows the zero-state line and no "Pending" (red today); with a job id, `Status` row renders as before. New/updated copy exported as constants and added to the sweep's constant sweep so page-level mocks can't hide it.

### Slice 5: People-first roster labels

**Goal**: One name per referent on the roster surface.

Changes: `RosterEntriesSection.tsx` heading "Managed Identities" → "People"; `rosterRoute.ts` tab **labels** `Entries` → `People`, `Clusters` → `Face groups` (ids, routes, and deep-link params untouched — E21-9 owns structure). No other roster JSX changes.

**TEST_CMD**: `npm --prefix apps/prototype-wp-alt-context test -- RosterPage RosterEntriesSection rosterRoute banned-vocabulary`

Proof: `BANNED_STRINGS` gains "Managed Identities" — red pre-change (RosterPage sweep fixture renders the entries section heading). Unit asserts tab ids still `entries`/`clusters` while labels read per spec (rebase-tolerance guard for E21-9/E21-10). Existing roster tests updated only where they assert the old label text.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded frontend/testing rules; confirmed the four enumerated structural files are unclaimed by E15-37-FE / E21-9 / E21-10 and all other overlap is string-level per the collision policy.

### Checklist for Slice 1: Single-source the banner + dashboard summary

- [ ] All ten inline literals deleted; `getDegradedBannerTitle`/`getDegradedBannerMessage`/`getDashboardSyncHealthSummary` (switch + fallback) read `SYNC_VOCABULARY`.
- [ ] Module-mock sentinel tests bind every branch's output to the vocabulary exports (red pre-change); rendered copy byte-identical.

### Checklist for Slice 2: Sync vocabulary rewrite

- [ ] Copy spec rows applied; `syncBacklog*` keys renamed with all consumers incl. `DeadLetterPanel.tsx`; `syncModeDelta`/`Full` + `formatSyncModeLabel` + mode badge deleted.
- [ ] `BANNED_STRINGS` += "Delta sync", "Machine sync", "Machine state", "Sync backlog"; demonstrated red pre-change under rendering fixtures incl. the new `DeadLetterPanel` topology fixture.
- [ ] Vocabulary-module regex sweep test; placeholder arity unchanged; `phasePresentation` job-phase badges untouched.

### Checklist for Slice 3: Retention card

- [ ] Heading replaced; `available:false` renders no card; `isError` state carries remediation + `#/retention` href asserted in a component test.
- [ ] State matrix (loading/absent/error) implemented as specified — no focus or live-region changes introduced.
- [ ] `BANNED_STRINGS` += "Retention posture" (red pre-change); copy constants swept via `import *`.

### Checklist for Slice 4: Advanced drawer

- [ ] Explainer is a closed-by-default `<details>` disclosure; body drops "embeddings"; token-only styling.
- [ ] `ConfirmPanel` no-job zero state per spec; no "Pending" without a job; `Status` row conditional.
- [ ] Component tests red-then-green for both behaviors.

### Checklist for Slice 5: Roster labels

- [ ] "Managed Identities" → "People"; tab labels per spec with ids/routes untouched and pinned by test.
- [ ] `BANNED_STRINGS` += "Managed Identities" (red pre-change).

### Review Readiness

- [ ] Full `npm test` + `lint` green; `make check-remote` on committed HEAD.
- [ ] Every `BANNED_STRINGS` addition has recorded red-run evidence ([TEST-15]).
- [ ] Handoff decision per slice records change, verification, and the deliberate exclusions (job-phase "Queued", mode-badge deletion rationale).

## Success Criteria

- [ ] No page surface renders "Delta sync", "Machine sync", "Machine state", "Sync backlog", "Retention posture", or "Managed Identities" — enforced by the banned-vocabulary sweep plus the targeted `SyncStatusIndicator`/`DeadLetterPanel` fixtures, each addition proven capable of failing.
- [ ] Single-source gate (mechanical): every string `degradedModeBannerLogic.ts` renders is bound to a `SYNC_VOCABULARY` export by the slice-1 sentinel tests, and each rewritten key's exact new string is positively asserted on a fixture that renders that state. ("Every state string names consequence + next action" is the copy-spec's design bar — reviewed by humans against the table above, **non-gating**: no automation can measure it.)
- [ ] Dashboard with no retention endpoint configured (`available:false`) shows no retention card; with a configured-but-failing endpoint (`isError`) it shows remediation and a link whose `href` is `#/retention` — both asserted in component tests.
- [ ] Advanced drawer opens to recovery tools (asserted: tools render with the disclosure closed); the clustering explainer appears only on demand and contains no "embeddings"; keyboard toggling works via native `<details>` semantics.
- [ ] With no job run, the drawer states that plainly and shows no fabricated "Pending" status.
- [ ] Roster tab ids and deep links unchanged (pinned by test) — the E21-9/E21-10 rebase surface is labels only.
- [ ] Job-phase "Queued" badges still render — the sweep bans phrases, not the word.
