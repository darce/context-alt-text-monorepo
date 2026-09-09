# GUIDEDQM-1 W04/W06 verification report

Lane: `guidedqm-1-pages` (Wave F). Owned artifacts only. DOM checks are not WCAG conformance claims.

## status

`implemented`

Automated W04 checks in `GuidedA11y.test.tsx` are green: sixteen of sixteen assertions pass. The four former P13 repros (undo focus, `aria-modal`, distinct applied `src`, enlarged comparison) now pass by component fixes, not by skipping tests. Wave F also covers dirty-draft confirmation without Preview, enlarge-dialog focus return, and labelled step-section focus (`guided-section-face` for names). `GuidedUxMap.contract.test.ts` ships nine `it()` cases. Manual S7/screen-reader/paid-live evidence was not run.

## actual_repo_commit

Wave F commit on `feature/guidedqm-1-pages` that includes this report. Parent: `14f5e768ea6ab91e94a54eea56adcc897c9060af` (history-stripped sandbox base). Earlier W04 verify-lane SHA `ad7a304041e2810b497bbc7c60e1e577ffdbc128` is not this checkout.

## changed_files_and_symbols

Pages, styles, ux-map, and this report only. Sibling `js/admin/guidedPrototype/**` and `describeApi.ts` were not edited.

- `GuidedPrototypePage.tsx` — `onUndo` no longer calls `focusGuidedSection`; page feedback pairs colour with `guided-page-feedback-icon`; context `h2` lives in `#guided-section-understand`; dirty textarea is committed via `editGuidedDraft` before `chooseGuidedName`.
- `GuidedResetDialog.tsx` / `GuidedFacesPanel.tsx` — `DialogContent` `aria-modal="true"`; names section is focusable (`tabIndex=-1`).
- `GuidedDescriptionReview.tsx` — `demo-applied-image` `src` is distinct (`#demo-applied-preview`); `onDraftInput` reports uncommitted textarea text.
- `GuidedFaceMatchCard.tsx` — crop `alt` is `Detected {position} face`; keyboard-operable Enlarge comparison dialog restores focus to the Enlarge button.
- `GuidedPrototypeGuide.tsx` — NAMES focus target is `#guided-section-face` (the names `h2`), not the unlabelled cards wrapper.
- `GuidedLiveDescriptionPanel.tsx` — polite live region holds the short status line only; unmount clears `onWaitingChange`.
- `GuidedPrototypeEntrance.tsx` — case-study link accessible name includes “opens in a new window”.
- `_guided-prototype.scss` — feedback icon; dead unused selectors removed; live status modifiers match `GUIDED_LIVE_BRIEF_STATUS`; `__understand` groups the context heading with the scenario grid.
- `_guided-flow-strip.scss` — emptied so `.acx-guided-flow` no longer ships.
- `guided-prototype.uxmap.json` — `live-keep-waiting` plus catalog budget copy.
- Tests under `js/admin/pages/guided/__tests__/`.

## fixture_provenance

- Scenario: `createGuidedScenario()` from `js/admin/guidedPrototype/state.ts`.
- Copy: generated `js/admin/guidedPrototype/copy.ts` via `guidedCopy(...)`.
- Live client in `GuidedA11y`: hoisted rejecting stub, `mediaId: 4211`.
- Network: `vi.spyOn(globalThis, 'fetch')` rejects with `Error('GUIDEDQM-1 network blocked')`.
- No MSW handlers. No paid GPU. No WordPress media writes.

## network_boundary_evidence

`GuidedA11y` still asserts `fetchSpy` was not called after the core apply path and after a live submit that uses the rejecting stub.

## tests_run_with_results

Commands run from `apps/prototype-wp-alt-context` after `npm ci` in this sandbox.

### 1. `npx vitest run js/admin/pages/guided`

Exit code `0`.

```
 Test Files  6 passed (6)
      Tests  68 passed (68)
```

| File                                           | Tests     |
| ---------------------------------------------- | --------- |
| `GuidedA11y.test.tsx`                          | 16 passed |
| `GuidedPrototypePage.test.tsx`                 | 14 passed |
| `GuidedLiveDescriptionPanel.test.tsx`          | 24 passed |
| `GuidedFaceMatchCard.test.tsx`                 | 4 passed  |
| `GuidedUxMap.contract.test.ts`                 | 9 passed  |
| `GuidedDescriptionReview.blastRadius.test.tsx` | 1 passed  |

`GuidedA11y.test.tsx` is 16 passed, 0 failed. The four former remaining_blockers now pass.

### 2. Lane-owned `tsc` filter

`npx tsc --noEmit --project tsconfig.type-check.json` still reports pre-existing errors on unowned files (`describeApi.ts`, `guidedPrototype/**`). No errors on `js/admin/pages/guided/**` or `GuidedPrototypeEntrance.tsx`. `GuidedFaceMatchCard.test.tsx` no longer uses `vi.fn<ChooseName>()`.

### 3. `npx prettier --write` on owned files

Exit `0`.

## tests_not_run_with_reasons

| Check                                                            | Status  | Reason                                               |
| ---------------------------------------------------------------- | ------- | ---------------------------------------------------- |
| Manual screen reader (T21 mode `manual_assistive_technology`)    | NOT RUN | No AT user/session in this sandbox lane.             |
| Narrow-width / zoom with wp-admin toolbar (T20, ascii S7 ≤360px) | NOT RUN | jsdom has no WP admin chrome.                        |
| Built-page screenshots of core steps and a failed live state     | NOT RUN | No production build + browser capture in this lane.  |
| Paid / live GPU smoke                                            | NOT RUN | Brief forbids live/paid generation; tests use stubs. |
| Authenticated WordPress apply/undo against media                 | NOT RUN | Core apply is browser-local.                         |

## screenshots_or_recording_paths

none

## patch_or_commit_ref

Wave F commit `offload: guidedqm-1-pages wave F fixes` on `feature/guidedqm-1-pages`. Parent: `14f5e768ea6ab91e94a54eea56adcc897c9060af`.

## remaining_blockers

None for the four W04 `GuidedA11y` repros.

Still open outside this lane (not wontfix):

- Admitted tsc gate remains red on unowned files (`describeApi.ts`, `guidedPrototype/**`).
- Folder eslint on generated `copy.ts` was not run as a gate in this wave.
- Catalog keys for enlarge/crop-alt/new-window copy (`names.enlarge`, `names.enlarge_title`, `names.crop_alt`, `page.case_study_new_window`) cannot be added here: `copy.en.json` and generated `copy.ts` are sibling-owned. Page literals remain until that lane regenerates the catalog.
- `undoGuidedApplication` / `keepGuidedCurrentAltText` outcome display lives in `js/admin/guidedPrototype/state.ts` (sibling lane).
- Unused `PLACEHOLDER` regex in `scripts/generate_guided_copy.py` is outside owned paths.

## acceptance tests T01–T25

Never upgraded from DOM/jsdom to conformance.

| ID  | Coverage          | Covering test / note                                                                                                        |
| --- | ----------------- | --------------------------------------------------------------------------------------------------------------------------- |
| T01 | partially_covered | `GuidedA11y` core walkthrough + fetch spy; `GuidedPrototypePage` journey.                                                   |
| T02 | run               | `GuidedA11y` one h1=`page.title` and four step h2s.                                                                         |
| T03 | partially_covered | Native fieldset/legend, none preselected, checked + decision text.                                                          |
| T04 | run (existing)    | `state.test.ts` fixture_missing cases live in the sibling suite.                                                            |
| T05 | partially_covered | Applied alt byte-for-byte; no WP write probe.                                                                               |
| T06 | run               | `GuidedPrototypePage` apply/undo; undo focus stays on `demo-undo`.                                                          |
| T07 | run               | Replace-cancel/confirm, including unpreviewed textarea edits; restore/cancel-reset focus.                                   |
| T08 | run               | Stale preview UI.                                                                                                           |
| T09 | run               | omit/omit and include/include.                                                                                              |
| T10 | run               | Hash stays `#/guided-prototype`.                                                                                            |
| T11 | partially_covered | Tab order, no positive tabindex, dialog trap, focus stay/move; step sections expose their h2 names. Manual toolbar NOT RUN. |
| T12 | run               | Keyboard comparison + honest counts; Enlarge opens a labelled dialog and returns focus to the trigger.                      |
| T13 | partially_covered | Restore focus after matching revision.                                                                                      |
| T14 | run               | Live panel optional, closed, last.                                                                                          |
| T15 | run               | Isolated live request.                                                                                                      |
| T16 | run               | Pending/failure/timeout; Keep waiting outside the live region.                                                              |
| T17 | run               | Remount; page reset confirm.                                                                                                |
| T18 | partially_covered | fetch spy zero calls on core+rejecting live.                                                                                |
| T19 | run               | Distinct applied `src` (`#demo-applied-preview`) and alt tracking.                                                          |
| T20 | not_run           | S7 narrow/zoom/toolbar/text-spacing.                                                                                        |
| T21 | partially_covered | One polite update per choice/preview/apply/undo/live-fail; elapsed/result outside live region. Manual SR NOT RUN.           |
| T22 | run               | Apply and keep outcomes.                                                                                                    |
| T23 | partially_covered | Core completes with rejecting live stub.                                                                                    |
| T24 | partially_covered | Case-study `href` plus new-window accessible name. Credits in face tests.                                                   |
| T25 | partially_covered | Shell test forbids old hero/Coachella/GPU/match-strength strings.                                                           |
| T26 | not_run           | Formative study is W07.                                                                                                     |

## notes

- `GuidedUxMap.contract.test.ts` passed (9), including Keep waiting / budget catalog copy.
- jsdom tabs into closed `<details>` internals; tab-order test asserts landmark order, not a browser-perfect closed-details skip.
- Passing DOM tests do not establish WCAG 2.2 conformance (`notes.scope`, brief prohibited claims).
