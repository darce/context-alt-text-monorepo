# UXW2-4-R8D — drawer a11y walk is coverage only where it runs

## Result

jsdom now owns the boarded-up drawer contract (named Close, honest Move copy, Move-to count 0, focusable set from Close). The e2e spec follows the Review in Workbench CTA onto `.acx-workbench` + `.acx-review-queue`. The drawer walk still `test.skip`s without a live unlabeled group — left honest. ≥24×24 Close is not claimed (jsdom has no layout).

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Already closed by r7d

Finding text about `E2E_ROSTER_CLUSTER_ID` and `listbox`/`option`/`title` locators is stale. Verified on this tree after the code commits:

```
$ grep -n 'E2E_ROSTER_CLUSTER_ID' tests/e2e/a11y/roster-keyboard-walk.spec.ts
NO E2E_ROSTER_CLUSTER_ID

$ grep -n "getByRole('listbox')\|getByRole('option')\|toHaveAttribute('title'" tests/e2e/a11y/roster-keyboard-walk.spec.ts
NO bad locators
```

`sed -n` (same tree):

| Claim | `sed -n` |
| --- | --- |
| Walk discovers via fixture, not env | `roster-keyboard-walk.spec.ts:85` `const clusterId = await discoverUnlabeledClusterId(page);` |
| Producer exists | `seeded-state.ts:62` `export const discoverUnlabeledClusterId` |
| Close named button still in e2e | `roster-keyboard-walk.spec.ts:99` `drawer.getByRole('button', { name: /^Close$/i })` |
| Move to count 0 already the post-UXW2-4 contract | `roster-keyboard-walk.spec.ts:106` `getByRole('button', { name: /Move to/i })).toHaveCount(0)` |

Did not “fix” any of the above.

## Closure

| Clause | Commit subject | Test | Verbatim mutant RED | GREEN selected/total |
| --- | --- | --- | --- | --- |
| Named Close button | `test(a11y): port boarded-up drawer walk to ClusterDrawerPanel jsdom` | `Close is a named button, honest Move copy is shown, and Move to count is 0` | M1 title Close→Dismiss. `TestingLibraryElementError: Unable to find an accessible element with the role "button" and name `/^Close$/i`` (dump also: `Name "Dismiss"`). **1 failed / 12** | **1 passed / 12** (`1 passed \| 11 skipped (12)`) |
| Honest Move copy | same | same | M2 drop `{reassignUnavailableReason}` paint. `TestingLibraryElementError: Unable to find an element with the text: /Face moves happen in the Workbench review queue/i. This could be because the text is broken up by multiple elements. In this case, you can provide a function for your text matcher to make your matcher more flexible.` **1 failed / 12** | **1 passed / 12** |
| No Move to button | same | same (`toHaveLength(0)`) | M3 `{hideReassign ? null : (` → `{false ? null : (`. `AssertionError: expected [ Array(1) ] to have a length of +0 but got 1` **1 failed / 12** | **1 passed / 12** |
| Focusable set from Close, no tabindex=-1 trap | same | `focusable set starts at Close and no control is tabindex=-1 trapped` | no required mutant | included in file **12 / 12**; `-t "UXW2-4-R1-24"` **3 / 15** (2 jsdom + 1 guard) |
| CTA follow-through (hash + queue on screen) | `test(e2e): follow roster CTA onto the workbench review queue` | spec + `roster-keyboard-walk.spec.guard.test.ts` | n/a (Playwright not run) | guard **3 / 3** in that file; static only |
| Skip when unlabeled seed missing | none (left in place) | `test.skip(true, '… drawer walk needs a live face group')` | n/a | n/a |

Unmutated `-t "Close is a named button"` before the first mutant: **1 / 12** (non-zero). Each mutant restored; `git diff` on `ClusterDrawerPanel.tsx` empty.

`(C)` chose **leave the skip**. `discoverUnlabeledClusterId` still needs `window.acxE2eSeed.unlabeledClusterId` or a live `/top-unlabeled` row, and opening `cluster=` still needs REST cluster detail. A planted fake id without a database would fail the drawer-visible assertion. Skip-with-reason is honest; a vacuous pass is not. `seeded-state.ts` unchanged.

## Gate

From `apps/prototype-wp-alt-context`:

**Baseline (stash, before first code commit)**

```
 Test Files  208 passed (208)
      Tests  2340 passed (2340)
```

**After both code commits**

```
 Test Files  208 passed (208)
      Tests  2344 passed (2344)
```

Delta: **+4 tests**, same file count. `ClusterDrawerPanel.offline.test.tsx` 10→12; `roster-keyboard-walk.spec.guard.test.ts` 1→3.

`npm run typecheck`: clean (`tsc --noEmit --project tsconfig.type-check.json`).

PHP untouched. `composer test` not run.

## file:line

Re-derived with `sed -n '<N>p' <file>` after the last code commit (`test(e2e): follow roster CTA onto the workbench review queue`).

| Claim | `sed -n` |
| --- | --- |
| jsdom Close `/^Close$/i` | `ClusterDrawerPanel.offline.test.tsx:236` `const close = within(drawer).getByRole('button', { name: /^Close$/i });` |
| jsdom honest copy | `ClusterDrawerPanel.offline.test.tsx:240` `expect(within(drawer).getByText(HONEST_MOVE_COPY)).toBeInTheDocument();` |
| jsdom Move to count 0 | `ClusterDrawerPanel.offline.test.tsx:241` `expect(within(drawer).queryAllByRole('button', { name: /Move to/i })).toHaveLength(0);` |
| jsdom first focusable is Close | `ClusterDrawerPanel.offline.test.tsx:253` `expect(focusables[0]).toBe(close);` |
| Production Close name | `ClusterDrawerPanel.tsx:378` `title={__('Close', 'alt-context')}` |
| Production hide Move | `ClusterDrawerPanel.tsx:438` `{hideReassign ? null : (` |
| e2e skip still present | `roster-keyboard-walk.spec.ts:88` `test.skip(` |
| e2e ≥24×24 left in spec | `roster-keyboard-walk.spec.ts:102` `expect(box, 'Close target ≥24×24').not.toBeNull();` |
| e2e CTA click | `roster-keyboard-walk.spec.ts:134` `await page.getByRole('link', { name: /Review in Workbench/i }).click();` |
| e2e hash | `roster-keyboard-walk.spec.ts:136` `…window.location.hash)).toBe('#/workbench?tab=scan&rq=all.all.0')` |
| e2e queue on screen | `roster-keyboard-walk.spec.ts:139` `await expect(page.locator('.acx-review-queue')).toBeVisible();` |

## Undone

- **≥24×24 Close not closed in jsdom.** Layout is not computed. Did not assert a style string. Clause stays on the e2e spec (`boundingBox` at `:101-104`) and did not execute here.
- **e2e not executed.** No Playwright browser, no LocalWP. Spec + guard changes are static only. Do not read this as an e2e result.
- **Drawer walk still skips** without a seeded unlabeled face group. Replacement: run `npx playwright test tests/e2e/a11y/roster-keyboard-walk.spec.ts --project=a11y` against a seeded LocalWP.
- **PHP untouched.** `composer test` not run.
- **UX maps untouched.** Tests only; no user-facing surface change.
- **Handoff.** `workbay_handoff_mcp` is not importable in this overlay (`ModuleNotFoundError`). Decision recorded in this report only.
