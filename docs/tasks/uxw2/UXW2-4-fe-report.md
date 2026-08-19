# UXW2-4 FE report

Lane cwd. Commits cited by **subject line**. Do not treat SHAs as portable.

R1 (prior lane) closed drawer shell, CTA band, review URL owner, and face-group copy. R2 below closes the 23 still-open frontend findings. PHP/Python items are a separate lane.

PHP section restore: the brief's `git cat-file -e <php-r1-sha>^{commit}` does **not** resolve here. Orchestrator-side action: the exact `git show …:REPORT.md | sed -n '1,63p'` command named in BRIEF.md (PHP SHA restore) into `docs/tasks/uxw2/UXW2-4-php-r1-lane-report.md`. Do not edit `docs/tasks/uxw2/UXW2-4-r1-fix-report.md`.

## R1 (prior)

Drawer `?cluster=` paints loading/error/Close. CTA lands `rq=all.all.0`. Review close uses functional prev + replace. Operator copy is face / face group / person. R1 synthesized ids in the old root `REPORT.md` are discarded; this table uses brief ids only.

## R2

TDD: RED first, then GREEN. One commit per finding (shared change named all ids). No Co-Authored-By.

### Decisions

- Heading is **Review these faces**. Extra X dropped; Back is the single exit. Back label kept (`← Back to Review Suggestions`).
- Workspace jargon rewritten (Data status / Last refreshed / Record version / Review queues), not allowlisted.
- `panel` legal values: `review` | `conflicts` | `dead-letter`. ClusterPanelContext writes review; WorkbenchNavContext overlay host ignores `review`. Close restores a prior overlay.
- History: open and close both `{replace: true}` (URL state, not a stack frame). Back after close cannot reopen. Same-tick open then close encodes `next` via `stateRef` (RR7 updater is the closure snapshot).
- `rq=` kept explicit; value derived from `DEFAULT_QUEUE_STATE` (serializeQueueState would omit the default band).
- Review deep link: `toWorkbench({panel:'review', cluster})` / `reviewPanelUrl`; reader `readReviewFromParams`.
- Count live region always `role="status"` (empty until settled). `_n` for 1 vs many. `useTopUnlabeledTotal` still mocked in page tests; IO seam is R2-16.
- Drawer faces region is loading / error-only / loaded-empty. Error heading: Face group unavailable. Focus trap keyed on `requestedClusterId`.
- Reassign picker boarded up on the shim; copy: `Face moves happen in the Workbench review queue.` Follow-up: scoped `reassignTargets` query (REF-25).
- Bulk merge/dismiss deleted. `useRecognitionClusters` kept (cooldown-gate poller).
- e2e not executed here (no live WP). Spec is runnable; vitest source guard covers the `acxAdmin` mutant.

### GREEN

From `apps/prototype-wp-alt-context`:

- `npx vitest run`: **Test Files  207 passed (207) / Tests  2337 passed (2337)** (346.86s)
- `npm run typecheck`: clean (`tsc --noEmit --project tsconfig.type-check.json`)
- `npm run lint`: pre-existing failures on untouched files (avatar, cropFaceFromImage, faceGeometry, other e2e specs). Changed-file eslint clean after the R2-14 array-type/optional-chain fix. Baseline vs `.lane/BASE`.
- Playwright e2e: **not run** (no live WordPress).

### Closure

| ID | commit subject | test | mutant RED line |
| --- | --- | --- | --- |
| R1-15 | `fix(roster): drawer error/empty and board-up` | `ClusterDrawerPanel.offline` error/loading; no empty copy | error branch falls through to `No faces found in this face group.` |
| R1-16 | `fix(roster): drawer error/empty and board-up` | `RosterPage.container` Move to count 0 + honest reason | drop `reassignUnavailableReason` → `No other face groups available` lie |
| R1-17 | `fix(nav\|tests): panel owner` | `ScanTabContent.reviewUrl` history + same-tick | drop `{replace:true}` on close → `navigate(-1)` reopens |
| R1-18 | `fix(workbench): Review these faces heading` | `reviewUrl` + `controlPaneOrder` role+level matcher | h2 `__('Review this face group')` → Unable to find heading `/review these faces/i` |
| R1-19 | `fix(roster\|tests): member jargon and vocab sweep` | `banned-vocabulary` mounts ClusterReviewPanel + attrs | alt `Identity %d` → review leaked `"identity"` |
| R1-20 | `fix(roster): plural count and empty status` | `RosterPage.reviewCta` total=1 | `sprintf(__('%d face groups waiting'))` → `1 face group waiting` missing |
| R1-21 | `fix(nav): rq encoder from DEFAULT_QUEUE_STATE` | `rosterRoute` parseQueueState round-trip | emit `assignment.all.0` → not `DEFAULT_QUEUE_STATE` |
| R1-22 | `fix(nav\|tests): panel owner` | `reviewUrl` Review button `toHaveFocus` | delete `focusQueueRoot()` → Review not focused |
| R1-23 | `fix(roster\|tests): member jargon and vocab sweep` | `banned-vocabulary` SURFACE_BANNED + attrs | `Projection status: %s` → expected `data status` / leaked `"projection"` |
| R1-24 | `fix(tests): e2e reads AltContextAdmin` | `roster-keyboard-walk` + spec.guard | rename global to `acxAdmin` → guard `not.toMatch(/\bacxAdmin\b/)` |
| R1-25 | `fix(nav\|tests): panel owner` | `reviewUrl` createMemoryRouter, real filters/lifecycle | same RED as the history/stateRef row above |
| R1-26 | `fix(tests): drop vacuous List Person negative` | `RosterPage.container` competing-row test | resolve workspace by name → competing-row fails |
| R1-27 | `fix(roster): delete orphan bulk merge/dismiss` | banned-vocabulary source sweep | re-add `__('Merge failed for cluster %s.')` → `/for cluster %s/` |
| R1-28 | `fix(nav\|tests): panel owner` | `appLinks` `readReviewFromParams` round-trip | stop emitting `cluster` with `panel=review` → mode none |
| R1-29 | `fix(styles): Back hit target uses --acx-space-24` | e2e ≥24×24 (keyboard walk); grep `&__back` | raw `24px` under `&__back` |
| R1-30 | `docs(uxmap): workbench-review-panel screen` | JSON parses; screen id in json + md | missing `workbench-review-panel` |
| R1-31 | `docs: FE report R2` (this file) | `test ! -f REPORT.md`; no dead SHAs | n/a (artifact) |
| R2-14 | `fix(tests): e2e reads AltContextAdmin` | spec.guard + spec source | `window.acxAdmin` → guard fails (not skip) |
| R2-15 | `docs: FE report R2` (this file) | closure table ids verbatim | n/a (artifact) |
| R2-16 | `fix(tests): settled probe for top-unlabeled total` | `useTopUnlabeledTotal` isFetched + total:0 control | drop `COUNTED_SOURCES` → unavailable/endpoint_error after settle |
| R2-17 | `fix(roster): plural count and empty status` | `reviewCta` empty status then 7 | conditional `role` → null-state `getByRole('status')` throws |
| R2-19 | `docs(uxmap): person workspace labels without identities` | grep identities only in ids | operator-facing `identities` label |

Same-tick `stateRef.current = next` behaviour is unproven. Deleting that assignment does not fail `same-tick open then close does not leave panel=review in the URL` (ClusterPanelContext or ScanTabContent.reviewUrl). UXW2-4-R2-18 is still open.

### Canon (re-verified `~/uxw2/canon/lexicons/`)

NAV-13, NAV-14, NAV-11, NAV-05, NAV-02, NAV-07, A11Y-07, A11Y-02, A11Y-04, A11Y-11, A11Y-21, A11Y-20, A11Y-24, A11Y-14, A11Y-08, COG-01, INT-06, INT-01, TEST-15, TEST-19, TEST-06, REF-25, REF-09, REF-29, REF-19, REF-26, ARCH-02, DATA-14, RLSE-04, DBG-12.
