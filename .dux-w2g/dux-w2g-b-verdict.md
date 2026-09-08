lane dux-w2g-b
STATUS: COMPLETE
LENS: MAP-TO-CODE TRUTH (DRIFT-03)
BASE: c994165aba25be6c8d1b78b4ac0eb68dbf77b689 (not in this sandbox; reviewed on-disk HEAD)
TESTS: cd apps/prototype-wp-alt-context && npx vitest run js/admin/__tests__/dashboard-uxmap-code-parity.test.ts js/admin/__tests__/uxmap-render-parity.test.ts
       → 2 files / 19 tests passed in 1.96s (GREEN while map claims are false — TEST-15 hole)

Canon verified present:
- TEST-06: docs/reviews/uxp-2/lexicons/engineering.md (watch it fail once)
- TEST-15: docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md (discrimination guard: prove the green can go red)
- DRIFT-03: apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.test.ts:13 (SSOT that cannot be loaded / map-to-code truth)
- A11Y-11 / A11Y-17 / A11Y-21 / A11Y-24: docs/reviews/uxp-2/lexicons/accessibility.md
- rg-005 / sr-001: docs/workbay/constitution.md

## high - Maximal Sync Health sketch fabricates relative recency ("12 minutes ago") that the component never renders
EVIDENCE: dashboard.md:292-293 draws `Last conflict: 12 minutes ago` / `Last failure: 4 minutes ago`. `python3` scan of non-test admin TS: those two literals are ABSENT. Shipped interpolation is `Last conflict: %s` / `Last failure: %s` (`syncVocabulary.ts:70-71`) with `%s` = `date.toLocaleDateString()` (`DashboardPage.tsx:47-53`), proven by `DashboardPage.test.tsx:814-849` (`Last conflict: ${expectedConflictDate}` where `expectedConflictDate = new Date('2026-03-07T02:15:00Z').toLocaleDateString()`).
IMPACT: Operators and reviewers treating the map as SSOT expect live relative timestamps; the UI shows a locale calendar date. DRIFT-03.

## high - Map bundles D/E as `count && lastDate` including the inbox/queue CTAs; code splits those gates
EVIDENCE: dashboard.md:271-272 claims `D :123 conflictCount && lastConflictDate  last-conflict line + [Open Conflict Inbox]` and `E :126 failedReplayCount && lastFailure  last-failure line + [Open Failed Sync Queue]`. Cited :123/:126 only gate the *lines*. The CTAs are separate: `conflictCount > 0` at :134 and `failedReplayCount > 0` at :140, neither requiring a date. Reachable composition with inbox+queue and *no* recency lines is the existing test `shows dashboard sync links for conflicts and dead-letter work` (`DashboardPage.test.tsx:761-810`: `conflict_count: 2`, `failed_curation_operations: 1`, no `last_curation_*_at`). So A/C/D/E are not four independent booleans covering the action row; D and E each hide a second boolean. The "16 compositions" count is false.
IMPACT: Map understates reachable UI. Conflict Inbox can appear without "Last conflict:" (and Failed Sync Queue without "Last failure:"). Pointer/AT users get a control the map says is tied to recency copy that is not there.

## high - Error Sync Health ships [Open settings] + body copy the map neither draws nor catalogs
EVIDENCE: `DashboardSyncHealthSection.tsx:59-63` EmptyState heading/body/action: "Sync health is unavailable right now." / "Check the recognition service connection in settings." / `Open settings` → `toSettings()`. Error sketch (`dashboard.md:202-204`) draws only the heading. `dashboard.uxmap.json` actions have no `Open settings` verb. `python3` scan: `Open settings` PRESENT in that component. EmptyState requires an action (`EmptyState.tsx:7-8`, NAV-08). A11Y-17 (errors name the field and the fix) and A11Y-24 (error state must keep a recovery path) fail in the map even though the component has both.
IMPACT: Reviewers following the error sketch miss the only recovery control in the error branch. Keyboard walk (A11Y-11) of the mapped error state is a dead end; the shipped state is not.

## high - B's "seven summary strings" invents resyncRequired and cites the wrong offline string
EVIDENCE: dashboard.md:274-276 lists `healthy, queued, stale, conflicts, failures, resyncRequired, plus the offline headline`. `SyncHealth` is `'healthy' | 'queued' | 'stale' | 'conflicts' | 'failures' | 'offline'` only (`types/sync.ts:1`) — no `resyncRequired`. `getDashboardSyncHealthSummary` (`degradedModeBannerLogic.ts:36-50`) has no `resyncRequired` case; unknown values hit `staleSummary`. Offline returns `SYNC_VOCABULARY.offlineSummary` ("The recognition backend is currently unreachable.") not `offlineHeadline` ("Recognition service unreachable — showing your local copy."). Reachable extra strings the map omits: warning overlay `Open sync conflicts exceed the configured warning threshold.` (`degradedModeBannerLogic.ts:32-33,66`) and `attentionSummary` fallback. rg-005: map claims a contract member the SyncHealth type does not have.
IMPACT: Default-branch summary copy in the map is not the function the section calls. A resync-required backend still shows stale copy; a reviewer looking for the headline/resync strings on the dashboard will not find them.

## medium - [Open Review Queue] is not the only unconditional action in the zone
EVIDENCE: Interactivity notes (`dashboard.md:312-315`) claim it is the only unconditional action. It is unconditional only inside the else branch (`:129-133`). Loading (`:56-57`) has none; error (`:59-63`) always mounts `[Open settings]`. Even inside default, every action card always renders a detail `<p>` (`openWorkbenchDetail` at :132). Reset mirror is gated by A, Inbox by `conflictCount>0`, Failed Queue by `failedReplayCount>0` — that part is true of the CTAs, but not of D/E as defined.
IMPACT: Zone-level "unconditional" is false; operators in error never see Open Review Queue. A11Y-24 state-matrix: loading/error are named zone states and do not share that CTA.

## medium - "Only live region / nothing nests" is false of the error host markup
EVIDENCE: Mirror banner is `role="status"` without `aria-live` (`DashboardSyncHealthSection.tsx:69`). Error EmptyState does not pass `announceState={false}`, so it mounts its own live region (`EmptyState.tsx:122-125`: `role="status"` + `aria-live="polite"`) inside a nested `<section>` (`EmptyState.tsx:121`) inside the host `<section class="acx-dashboard__panel">` (`DashboardSyncHealthSection.tsx:54`). Branches are exclusive, so the two status regions do not stack — that half is true — but "nothing nests" is false: error is a live region nested in two landmarks. Loading (`:56-57`) is a named zone state with no live region at all (A11Y-24). Map cites [A11Y-24] for action-row reflow (`dashboard.md:315`); A11Y-24 is "every state accessible (state-matrix join)", not a moving-target rule (A11Y-11 is the keyboard/focus-order walk).
IMPACT: AT users in error hear EmptyState's "Could not load" inside a nested section; loading announces nothing. Reviewers applying the cited A11Y-24 ID to reflow will audit the wrong failure.

## medium - Recent Activity empty/error/degraded sketches omit required [Run a scan]
EVIDENCE: `DashboardRecentActivitySection.tsx:152-166` both EmptyStates require `action={{ label: __('Run a scan', ...) }}`. First-time (`dashboard.md:155-157`), Error (`:212-215`), and Degraded (`:246-249`) draw heading+body only. `dashboard.uxmap.json` has no `Run a scan` action. `python3` scan: `Run a scan` PRESENT in that section. Caught-up populated sketch (`:117-119`) matches `Scan finished · …` / `Durable batch run` / `[View Results]` (`verbForStatus` + `buildActivitySummary` + provenance). GuidanceCard caught-up heading/body/CTA (`dashboard.md:109-111`) match `GuidanceCard.tsx:75-80` exactly.
IMPACT: Empty/error Recent Activity is mapped as copy-only; shipped UI always has a front door. Same EmptyState-required-action hole as Sync Health error. TEST-15: `dashboard-uxmap-code-parity.test.ts` `allSketches` never extracts `#### Caught up` or the Sync Health fences (`:141-146`), so deleting `[Run a scan]` or changing caught-up copy cannot go red.

## medium - act-reset-mirror.preview_required is not true of the shipped button
EVIDENCE: `dashboard.uxmap.json:275-283` sets `preview_required: true`, `costly: true`. `DashboardSyncHealthSection.tsx:86-93` is `onClick={onResetMirror}` with no confirm/preview. `DashboardSyncHealthSection.test.tsx:130-155` clicks Reset mirror and expects `onResetMirror` immediately.
IMPACT: Map tells reviewers the destructive control is preview-gated; production fires on first click.

## low - Line cites :56/:58/:66/:68/:96/:113 are the conditions; :123/:126 do not contain the inbox/queue strings the map attaches
EVIDENCE: `nl` on DashboardSyncHealthSection.tsx: :56 `isLoading ? (` (string is :57); :58 `isError || !syncStatus` (heading :61); :66 else; :68 `showMirrorDivergenceBanner`; :96 summary `<p>`; :113 topology predicate. :123 is last-conflict line only; Open Conflict Inbox is :136. :126 is last-failure line only; Open Failed Sync Queue is :142.
IMPACT: Future drift hunts that trust the map's line numbers will patch the wrong predicates.

## low - Parity tests cannot catch the new Sync Health / caught-up claims (TEST-06 / TEST-15 / sr-001)
EVIDENCE: `dashboard-uxmap-code-parity.test.ts:141-146` extracts Default/First-time/Loading/Error/Degraded only. RV-13 comment (`:307-309`) still says Open Review Queue is at `:122-126`; it is at `:129-133`. Maximal/minimal Sync Health fences and the caught-up fence are untested. Leaving `[Open settings]` / `[Run a scan]` out of sketches keeps RV-05 green (unmatched sketch controls) without cataloging the shipped verbs — the map was relaxed so the test would not fail (sr-001 spirit).
IMPACT: Green vitest is not evidence the new prose is true. Observed: both assigned suites passed (8 + 11) against the same HEAD that fabricates "12 minutes ago" and omits [Open settings] / [Run a scan].

z-sync-health three exclusive states: NOT REFUTED. `isLoading ? loading : isError || !syncStatus ? error : default` is exhaustive (`DashboardSyncHealthSection.tsx:56-66`). `isLoading && isError` still renders loading. Mirror/offline/degraded modifiers stay in default. No reachable fourth branch found.

Quoted-string audit (Sync Health section, non-test source):
PRESENT: Loading sync health…; Sync health is unavailable right now.; Mirror is out of sync with the backend — %1$d…; Reset mirror; Resetting…; Some sync operations failed…; Everything is saved and up to date.; Open Review Queue; Open Conflict Inbox; Open Failed Sync Queue; Pending changes; Conflicts; Failed operations; %1$d waiting, %2$d failed, %3$d need review; Last conflict: %s; Last failure: %s.
ABSENT or paraphrased: "12 minutes ago"; "4 minutes ago"; resyncRequired as a dashboard summary; offline headline as B's offline copy; the pipe-joined stats line (DOM is a stats grid, not one string).

VERDICT: fail
