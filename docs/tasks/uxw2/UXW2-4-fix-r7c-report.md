# UXW2-4-fix-r7c — review-URL suite: prove or close

## Result

R1-25 clauses 1 and 5 already had kill power. Clauses 2–4 did not; tests now kill the named mutants. R2-18 / the `stateRef` half of R1-17 was a false RED on `same-tick open then close`. A new same-tick identity dispatch in `ClusterPanelContext.test.tsx` kills `stateRef.current = next`. FE report rows updated. No production file in the final diff.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Item 1 — UXW2-4-R1-25

Header comment is not evidence. Mutants were applied to production, then restored (`git diff --stat` on those files empty).

| Clause | Disposition | Mutant | Verbatim RED |
| --- | --- | --- | --- |
| 1 `rq=` coexistence | already-closed | close path `params.delete(APP_LINK_PARAMS.rq)` | `AssertionError: expected 'tab=scan' to contain 'rq=assignment.all.0'` — `Back returns to the queue, restores focus, and keeps rq=/tab=` |
| 2 lifecycle retire | still-open → fixed | `onRetireClose?.()` commented out | `AssertionError: expected 'tab=scan&panel=review&cluster=cluster…' not to contain 'panel=review'` — `same-tick open then retire-close does not leave panel=review in the URL` |
| 3 history / replace | still-open → fixed | close `setSearchParams` uses `{ replace: false }` | `TestingLibraryElementError: Unable to find an element by: [data-testid="review-queue"]` — after `navigate(-1)` the review panel is back (`Review these faces`) |
| 4 one write per close | still-open → fixed | close split into two `setSearchParams` | `AssertionError: expected [ …(2) ] to have a length of 1 but got 2` — `expect(closeWrites).toHaveLength(1)` |
| 5 A11Y-21 role | already-closed (matcher tightened) | drop `role="status"` on the lifecycle announce `<p>` | `TestingLibraryElementError: Unable to find an accessible element with the role "status" and name \`(_accessibleName, element) => (element.textContent ?? "").trim() === text\`` — open and Back cases |

Clause 1 already asserted `rq=` on Back. The Back case now also mounts at the queue, opens, then Back (clause 3 needed that history stack). Mutant still RED on the same `toContain('rq=assignment.all.0')`.

Clause 2: the old `:253` case dispatched `open` then `close` via a driver. No-op `onRetireClose` stayed GREEN. It now opens against a 404 members probe so the real lifecycle retire path must write the close.

Clause 3: the old `navigate(-1)` after mounting *at* the review URL stayed GREEN on close-push (RouterProvider update not flushed). Now: queue → open → Back → `act(navigate(-1))` → queue must still be up.

Clause 4: spy existed; open asserted `writes.length >= 1`. Close now asserts exactly one functional write, and that updater deletes both `panel` and `cluster` while keeping `rq`/`tab`.

Clause 5: `getByRole('status')` already failed without the role. Matcher is now `getByRole('status', { name: statusNamed(...) })`. A string `name` cannot match: `role="status"` has an empty accessible name (contents are not the name). Callback pins the text. Production `aria-label` not added (no prod change).

## Item 2 — UXW2-4-R4-01 / `stateRef`

Mutant: delete `stateRef.current = next` at `ClusterPanelContext.tsx` (the assignment immediately after `clusterPanelReducer(stateRef.current, action)`).

`ScanTabContent.reviewUrl.test.tsx`: GREEN (8/8). The `:292` 404 retire-close case and the old same-tick open-then-close path do not observe the assignment. `ClusterPanelContext.test.tsx` open-then-close / close-then-open cases: GREEN. Reducer fully replaces for `open_review` / `open_label` / `close`, so last `next` does not depend on the first.

Missing test added: `same-tick second dispatch reads the first result via stateRef` — `open_review` then a default-branch identity action in one tick. The second write must encode the opened review.

Verbatim RED:

```
FAIL  js/admin/pages/workbench/__tests__/ClusterPanelContext.test.tsx > ClusterPanelContext same-tick URL writer (UXW2-4-R1-17) > same-tick second dispatch reads the first result via stateRef
AssertionError: expected 'tab=scan' to contain 'panel=review'
Expected: "panel=review"
Received: "tab=scan"
```

Filter `second dispatch reads` → **1 failed | 4 skipped (5)**.

FE report:

- **R1-17** test column no longer says "history + same-tick". It cites mount-queue → open → Back → `navigate(-1)`. Mutant line is close-push, which now RED.
- **R2-18** inserted as a closure row citing the identity-dispatch case and `delete stateRef.current = next`. The "unproven / still open" footnote is gone.

Restore: `stateRef.current = next` is back. `git diff --stat` on `ClusterPanelContext.tsx` / `ScanTabContent.tsx` / `useOpenReviewTargetLifecycle.ts` is empty.

## Gate

From `apps/prototype-wp-alt-context`:

- `npx vitest run`: **Test Files  208 passed (208) / Tests  2344 passed (2344)** (323.09s)
- `npm run typecheck`: clean (`tsc --noEmit --project tsconfig.type-check.json`)
- Targeted `-t`:
  - `ScanTabContent.reviewUrl.test.tsx` `-t 'Back returns|retire-close|opening review persists|mounting at panel'` → **4 passed | 4 skipped (8)**
  - `ClusterPanelContext.test.tsx` `-t 'second dispatch reads'` → **1 passed | 4 skipped (5)**
- PHP untouched. `composer test` skipped.

## file:line (re-derived with `sed -n` after subject `test(nav): UXW2-4-r7c review URL suite kill-power`)

| Claim | `sed -n` |
| --- | --- |
| `setSearchParamsSpy` | `ScanTabContent.reviewUrl.test.tsx:29` |
| `statusNamed` callback | `ScanTabContent.reviewUrl.test.tsx:163-166` |
| Open `getByRole('status', { name })` | `ScanTabContent.reviewUrl.test.tsx:228-232` |
| Open exactly one write | `ScanTabContent.reviewUrl.test.tsx:236` |
| Back keeps `rq=` | `ScanTabContent.reviewUrl.test.tsx:266` |
| Close exactly one write; updater drops `panel`+`cluster` | `ScanTabContent.reviewUrl.test.tsx:271-278` |
| `navigate(-1)` must not reopen | `ScanTabContent.reviewUrl.test.tsx:285-289` |
| 404 retire-close case | `ScanTabContent.reviewUrl.test.tsx:292-304` |
| `stateRef` chain case | `ClusterPanelContext.test.tsx:124-141` |
| Render sync of `stateRef` | `ClusterPanelContext.tsx:87` |
| Same-tick assignment | `ClusterPanelContext.tsx:113` |
| Retire path | `useOpenReviewTargetLifecycle.ts:139-142` |
| Announce `role="status"` | `ScanTabContent.tsx:205` |
| R1-17 row | `UXW2-4-fe-report.md:46` |
| R1-25 row | `UXW2-4-fe-report.md:54` |
| R2-18 row | `UXW2-4-fe-report.md:65` |

## Undone

- PHP not in ownership. `composer test` not run.
- No production change. None believed required. `role="status"` still has an empty accessible name; a string `{ name: '…' }` cannot match without an `aria-label` we were not allowed to add.
- Legal panel actions fully replace reducer state. The `stateRef` kill uses a default-branch identity action (`{ type: 'identity' }` via `unknown`). A future sequential action that reads previous state would be a clearer operator-facing pin; not added here.
- `ScanTabContent.reviewUrl.test.tsx` still stays GREEN if `stateRef.current = next` is deleted. Kill lives in `ClusterPanelContext.test.tsx` only.
- UX maps not edited (tests only; no user-facing surface change).
- Handoff MCP tools were unavailable in this harness. Python API import of `workbay_handoff_mcp` failed (`ModuleNotFoundError` / uvx pin unresolved). Decision write may need the integrator.
