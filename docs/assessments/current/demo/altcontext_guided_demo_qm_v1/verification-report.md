# GUIDEDQM-1 W04/W06 verification report

Lane: `guidedqm-1-verify`. Owned artifacts only. DOM checks are not WCAG conformance claims.

## status

`implemented_partially_verified`

Automated W04 checks exist in `GuidedA11y.test.tsx`. Twelve of sixteen assertions pass. Four are left failing as P13 repros (no component fix in this lane). The admitted tsc gate is red on files this lane does not own. Manual S7/screen-reader/paid-live evidence was not run.

## actual_repo_commit

`ad7a304041e2810b497bbc7c60e1e577ffdbc128` (`git rev-parse HEAD` on `feature/guidedqm-1-verify` after the W04 commit). Parent: `45cb8c3fc790e9cea782cc63a104aed5949abad2`.

## changed_files_and_symbols

- `apps/prototype-wp-alt-context/js/admin/pages/guided/__tests__/GuidedA11y.test.tsx` — new. Symbols: `liveClient` (hoisted rejecting stub), `assertHtmlElement`, `assertNonEmptyString`, `requireSample`, `controlKey`, `indexOfStop`, `politeSnapshot`, `changedPoliteTexts`, `chooseRadio`, `completeCoreDraft`, `describe('GuidedA11y (W04)')`.
- `docs/assessments/current/demo/altcontext_guided_demo_qm_v1/verification-report.md` — this file.

No component, state, copy, or style edits.

## fixture_provenance

- Scenario: `createGuidedScenario()` from `js/admin/guidedPrototype/state.ts` (`GUIDED_SCENARIO_SEED`, photo import `js/admin/assets/guided/guided-press-tribeca-2026.jpg`).
- Copy: generated `js/admin/guidedPrototype/copy.ts` via `guidedCopy(...)`.
- Live client: hoisted `vi.fn` stub that rejects with `Error('GUIDEDQM-1 live stub reject')`, injected by mocking `GuidedLiveDescriptionPanel` to pass `client: liveClient` and `mediaId: 4211` (the page itself calls `getGuidedLiveMediaId()`, which is `null` without `window.AltContextAdmin`).
- Network: `vi.spyOn(globalThis, 'fetch')` rejects with `Error('GUIDEDQM-1 network blocked')`.
- No MSW handlers. No paid GPU. No WordPress media writes.

## network_boundary_evidence

`GuidedA11y` spies `globalThis.fetch` and asserts `fetchSpy).not.toHaveBeenCalled()` after the core apply path and after a live submit that uses the rejecting stub (`liveClient.submit` called once with `4211`). The default `describeApi` client is not used because the panel mock supplies `client`. Zero mutating network calls were observed in this file.

## tests_run_with_results

Commands run on the sandbox VM from `apps/prototype-wp-alt-context`. P9: status below is the command output, not an intended run.

### 1. Lane gate — `npx tsc --noEmit --project tsconfig.type-check.json`

Exit code `2`. `GuidedA11y.test.tsx` is not in the error list. Errors are pre-existing on unowned files:

```
js/admin/api/describeApi.ts(418,88): error TS2345: Argument of type 'string' is not assignable to parameter of type '"status" | "reason" | "existing_alt_present" | "description_write"'.
js/admin/api/describeApi.ts(452,51): error TS2345: Argument of type 'string' is not assignable to parameter of type '"tenant_id" | "media_id" | "image_hash" | "context_hash" | "adapter" | "model_id" | "model_version" | "prompt_or_task_version" | "visual_facts" | "alt_text_draft" | "context_used" | ... 11 more ... | "alt_text_write"'.
js/admin/api/describeApi.ts(466,72): error TS2345: Argument of type 'string' is not assignable to parameter of type '"seeded" | "local_cpu" | "gpu" | "hosted_provider"'.
js/admin/api/describeApi.ts(514,25): error TS2345: Argument of type 'string' is not assignable to parameter of type '"local" | "none" | "hosted"'.
js/admin/api/describeApi.ts(527,77): error TS2345: Argument of type 'string' is not assignable to parameter of type '"retain_all" | "dispose_after_ack" | "purge_on_demand"'.
js/admin/api/describeApi.ts(530,93): error TS2345: Argument of type 'string' is not assignable to parameter of type '"provisional_cpu" | "final_gpu"'.
js/admin/guidedPrototype/state.ts(568,5): error TS2345: Argument of type '{ name: string; } | { name?: undefined; }' is not assignable to parameter of type 'Record<string, string | number> | undefined'.
js/admin/guidedPrototype/useGuidedLiveDescription.test.tsx(581,20): error TS2322: Type 'null' is not assignable to type 'number'.
js/admin/guidedPrototype/useGuidedLiveDescription.test.tsx(610,20): error TS2322: Type 'null' is not assignable to type 'number'.
js/admin/guidedPrototype/useGuidedLiveDescription.test.tsx(632,20): error TS2322: Type 'null' is not assignable to type 'number'.
js/admin/pages/guided/GuidedOutcome.tsx(4,31): error TS2395: Individual declarations in merged declaration 'GuidedOutcome' must be all exported or all local.
js/admin/pages/guided/GuidedOutcome.tsx(11,14): error TS2395: Individual declarations in merged declaration 'GuidedOutcome' must be all exported or all local.
js/admin/pages/guided/__tests__/GuidedFaceMatchCard.test.tsx(51,9): error TS2348: Value of type 'Mock<Procedure | Constructable>' is not callable. Did you mean to include 'new'?
js/admin/pages/guided/__tests__/GuidedFaceMatchCard.test.tsx(53,7): error TS2322: Type 'Mock<Procedure | Constructable>' is not assignable to type '() => void'.
js/admin/pages/guided/__tests__/GuidedLiveDescriptionPanel.test.tsx(63,45): error TS2345: Argument of type '(...args: Parameters<GuidedLiveDescriptionClient[K]>) => Promise<unknown>' is not assignable to parameter of type 'GuidedLiveDescriptionClient[K]'.
js/admin/pages/guided/__tests__/GuidedLiveDescriptionPanel.test.tsx(65,21): error TS2556: A spread argument must either have a tuple type or be passed to a rest parameter.
```

### 2. `timeout 600 npx vitest run js/admin/guidedPrototype js/admin/pages/guided`

Exit code `1`. Tail:

```
 Test Files  1 failed | 9 passed (10)
      Tests  4 failed | 238 passed (242)
   Duration  34.65s
```

Passing files: `liveDescription.test.ts` (80), `state.test.ts` (62), `useGuidedLiveDescription.test.tsx` (40), `GuidedPrototypePage.test.tsx` (13), `GuidedLiveDescriptionPanel.test.tsx` (19), `GuidedFaceMatchCard.test.tsx` (4), `credits.contract.test.ts` (3), `GuidedUxMap.contract.test.ts` (4) — N4-owned; not edited — `GuidedDescriptionReview.blastRadius.test.tsx` (1).

`GuidedA11y.test.tsx`: 12 passed, 4 failed (see remaining_blockers). Later isolated rerun after eslint helper rewrite: `Tests  4 failed | 12 passed (16)`.

### 3. `npx eslint js/admin/pages/guided js/admin/guidedPrototype`

Exit code `1`. `✖ 219 problems (219 errors, 0 warnings)`. Dominant: `copy.ts` `quotes` (generated; not edited). Sibling tests also error. After converting assertion helpers to function expressions, `npx eslint js/admin/pages/guided/__tests__/GuidedA11y.test.tsx` exits `0`. Lint on unowned files was not fixed.

### 4. `npx prettier --check` on owned files

```
npx prettier --check js/admin/pages/guided/__tests__/GuidedA11y.test.tsx
Checking formatting...
All matched files use Prettier code style!
```

Exit `0`. The report markdown is formatted by the same Prettier config when checked with the test file.

## tests_not_run_with_reasons

| Check                                                            | Status  | Reason                                                                                      |
| ---------------------------------------------------------------- | ------- | ------------------------------------------------------------------------------------------- |
| Manual screen reader (T21 mode `manual_assistive_technology`)    | NOT RUN | No AT user/session in this sandbox lane.                                                    |
| Narrow-width / zoom with wp-admin toolbar (T20, ascii S7 ≤360px) | NOT RUN | jsdom has no WP admin chrome, computed CSS, or 320 CSS-pixel viewport with toolbar overlap. |
| Built-page screenshots of core steps and a failed live state     | NOT RUN | No production build + browser capture in this lane. None labeled as captures.               |
| Paid / live GPU smoke                                            | NOT RUN | Brief forbids live/paid generation; tests use the rejecting stub.                           |
| Authenticated WordPress apply/undo against media                 | NOT RUN | Core apply is browser-local; no WP_PATH session.                                            |

## screenshots_or_recording_paths

none

## patch_or_commit_ref

`ad7a304041e2810b497bbc7c60e1e577ffdbc128` — `GUIDEDQM-1 semantic, keyboard and announcement verification (W04)` on `feature/guidedqm-1-verify`. Parent: `45cb8c3fc790e9cea782cc63a104aed5949abad2`.

## remaining_blockers

Four failing `it`s in `GuidedA11y.test.tsx` (P13; not `it.fails`; not fixed here). Coordinator should record findings and route to a fix lane.

1. **Undo moves focus** — `would prove the page wrong if Undo moved focus away from the undo control`  
   `AssertionError: expected <section id="guided-section-apply" ...> to be <button data-testid="demo-undo">`  
   Cause: `GuidedPrototypePage` `onUndo` calls `focusGuidedSection(GUIDED_STEP.APPLY)` while the undo control stays enabled.

2. **Reset dialog missing `aria-modal`** — `would prove the page wrong if the reset dialog omitted aria-modal`  
   `Expected the element to have attribute: aria-modal="true"` / `Received: null`  
   `role=dialog`, labelled title, Escape, and focus return pass in a sibling test.

3. **Applied preview reuses evidence `src`** — `would prove the page wrong if demo-applied-image reused the evidence photo src`  
   `AssertionError: expected '/js/admin/assets/guided/guided-press-tribeca-2026.jpg' not to be '/js/admin/assets/guided/guided-press-tribeca-2026.jpg'`  
   Distinct elements and alt-tracking pass. Both `img` nodes use `scenario.pressPhoto.src`.

4. **No keyboard-operable enlarged comparison** — `would prove the page wrong if the face comparison had no keyboard-operable enlarged view of the crop or references`  
   `Unable to find an accessible element with the role "button" and name /enlarg|larger|full.?size|expand comparison/i`  
   Native `<details>` comparison and coverage copy pass.

Also open until coordinator adjudicates (not wontfix):

- Admitted tsc gate red on unowned files listed above (`not_reproduced` as a lane regression; observed on this checkout).
- Folder eslint 219 errors, mostly generated `copy.ts` double quotes.

## acceptance tests T01–T25

Never upgraded from DOM/jsdom to conformance.

| ID  | Coverage          | Covering test / note                                                                                                                           |
| --- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| T01 | partially_covered | `GuidedA11y` core walkthrough + fetch spy; `GuidedPrototypePage` journey. Not a full destination matrix.                                       |
| T02 | run               | `GuidedA11y` one h1=`page.title` and four step h2s; `GuidedPrototypePage` shell.                                                               |
| T03 | partially_covered | `GuidedA11y` native fieldset/legend, none preselected, checked + decision text. Combinations in `GuidedPrototypePage` / `GuidedFaceMatchCard`. |
| T04 | run (existing)    | `state.test.ts` fixture_missing cases (passed this session). Not re-asserted in `GuidedA11y`.                                                  |
| T05 | partially_covered | `GuidedA11y` applied alt byte-for-byte; `GuidedPrototypePage` apply exact text. No WP write probe.                                             |
| T06 | run (existing)    | `GuidedPrototypePage` `previews then applies ... and undoes twice` (passed).                                                                   |
| T07 | run (existing)    | `GuidedPrototypePage` replace-cancel/confirm; `GuidedA11y` restore/cancel-reset focus.                                                         |
| T08 | run (existing)    | `state.test.ts` stale preview; `GuidedPrototypePage` stale UI.                                                                                 |
| T09 | run (existing)    | `GuidedPrototypePage` omit/omit and include/include.                                                                                           |
| T10 | run               | `GuidedA11y` hash stays `#/guided-prototype`; `GuidedPrototypePage` hash test.                                                                 |
| T11 | partially_covered | `GuidedA11y` tab order, no positive tabindex, dialog trap, focus stay/move. Manual toolbar/obscured-focus NOT RUN.                             |
| T12 | partially_covered | Keyboard open comparison + honest counts pass; enlarged-view repro fails.                                                                      |
| T13 | partially_covered | `GuidedA11y` restore focus after matching revision; reducer coverage in `state.test.ts`.                                                       |
| T14 | run (existing)    | `GuidedLiveDescriptionPanel` T14; page mounts live last, closed.                                                                               |
| T15 | run (existing)    | `GuidedLiveDescriptionPanel` isolated request. This lane uses reject stub, not a successful live result.                                       |
| T16 | run (existing)    | `GuidedLiveDescriptionPanel` pending/failure/timeout.                                                                                          |
| T17 | run (existing)    | `GuidedLiveDescriptionPanel` remount; page reset confirm.                                                                                      |
| T18 | partially_covered | fetch spy zero calls on core+rejecting live. Not a full storage/network inventory.                                                             |
| T19 | partially_covered | Distinct elements + alt tracking pass; src-reuse repro fails.                                                                                  |
| T20 | not_run           | S7 narrow/zoom/toolbar/text-spacing. Sandbox jsdom cannot.                                                                                     |
| T21 | partially_covered | One polite update per choice/preview/apply/undo/live-fail; live region excludes draft/history. Manual SR NOT RUN.                              |
| T22 | run (existing)    | `GuidedPrototypePage` apply and keep outcomes.                                                                                                 |
| T23 | partially_covered | Core completes with rejecting live stub; panel T23 unverified `mediaId=null`. No backend contract change.                                      |
| T24 | partially_covered | Case-study `href` in `GuidedPrototypePage`. Credits in face tests. No HTTP resolve.                                                            |
| T25 | partially_covered | Shell test forbids old hero/Coachella/GPU/match-strength strings. Not a full all-states copy audit.                                            |
| T26 | not_run           | Formative study is W07.                                                                                                                        |

## notes

- `GuidedUxMap.contract.test.ts` passed (4). Owned by the uxmap lane; not edited.
- jsdom tabs into closed `<details>` internals; tab-order test therefore asserts landmark order, not a browser-perfect closed-details skip.
- Passing DOM tests do not establish WCAG 2.2 conformance (`notes.scope`, brief prohibited claims).
