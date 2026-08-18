# REPORT — LANE UXW2-4-FE-FIX

Close 4-FE review findings. `.lane/BRIEF.md` was missing; R1 ids synthesized from `uxw2-4-fe/.review/*-grok.json` + `*-grok2.json` (BRIEF/CORRECT/TESTS/UX). Two commits on `master`. TDD: new assertions failed on old code, then GREEN.

## Result
`?cluster=` drawer paints loading/error/Close. CTA count matches `rq=all.all.0` and ignores unavailable `total:0`. Review close deletes `panel=review` from the functional prev snapshot. Operator copy is face / face group / person.

## Closure

| ID | Defect | Commit | Test | Mutant |
| --- | --- | --- | --- | --- |
| R1-15 | drawer `cluster=null` hides loading/error/Close | `87350a8` | `RosterPage.container` loading/error; `ClusterDrawerPanel.offline` requestedClusterId | drop `requestedClusterId` → shell gone |
| R1-16 | CTA count is top-unlabeled, href was `rq=assignment` | `87350a8` | `reviewCta` + `rosterRoute` href `#/workbench?tab=scan&rq=all.all.0` | revert href → red |
| R1-17 | unavailable/bootstrapping `total:0` treated as known | `87350a8` | `useTopUnlabeledTotal` unavailable/endpoint_error → null | drop `data_source` gate → 0 |
| R1-18 | empty `reassignTargets` lies "no other face groups" | `87350a8` | container + drawer: Move hidden, Workbench copy | omit `reassignUnavailableReason` → lie returns |
| R1-19 | close skipped URL delete on stale `searchParams` | `7091f71` | `reviewUrl` Back keeps `tab`/`rq`, drops panel/cluster | close without functional prev → params stick |
| R1-20 | `toWorkbench` could not emit `panel=review` | `7091f71` | `appLinks.test` `panel:'review', cluster` | drop union → type/href fail |
| R1-21 | leftover cluster/identity copy (toasts, alt, review panel) | both | banned-vocab + `IdentityThumbnail` + `ClusterReviewPanel` | revert toast/alt/heading → red |
| R1-22 | UX map JSON still modeled the rail; md still said cluster | `7091f71` | map JSON `z-review-cta`; md face-group drawer | grep `z-needs-assignment` |
| R1-23 | e2e env-gated + `role=listbox` | `7091f71` | `roster-keyboard-walk` discovers unlabeled via API; no Move on shim | env-var gate gone |
| R1-24 | hook mocked in every page test | `87350a8` | `useTopUnlabeledTotal.test` envelope 99 ≠ length 2 | `clusters.length` → red |
| R1-25 | test holes: rq persist, role=status, banned-vocab guard, List Person | both | `reviewUrl` rq=; `getByRole('status')`; drawer contains "unnamed face group"; competing List Person | listed asserts go red |
| R1-26 | open/close focus | `7091f71` | Back autofocus; close calls `focusQueueRoot` | — |
| R1-27 | CTA heading always "Unnamed faces waiting" | `87350a8` | unknown/zero headings | heading always-waiting → red |
| R1-28 | Back unstyled / <24px | `7091f71` | `_cluster-panels.scss` `__back` min 24px tokens | — |
| R1-29 | delete copy vs `delete_person` | already closed | PHP `reset_curation` (R1-13) makes "Assigned faces return to the review queue" true | no FE change |
| R1-30 | hook omitted `refetchOnMount:'always'` | `87350a8` | hook copies workbench observer | — |

## RED
- Drawer: `requestedClusterId` + loading/error Close absent; Move still claimed "No other face groups".
- CTA: href still `assignment.all.0`; hook returned `0` for unavailable envelope.
- Review URL: `getByRole('status')` and `rq=` persist added against the old path.

## GREEN
`npx vitest run` in `apps/prototype-wp-alt-context`: **207 files, 2333 tests, OK** (310s).
`npm run typecheck` clean. eslint clean on touched TS.

## Files
- `RosterPage.tsx` — URL-owned `selectedClusterId`; drawer shell props; CTA states
- `ClusterDrawerPanel.tsx` — `requestedClusterId`, `reassignUnavailableReason`
- `useTopUnlabeledTotal.ts` + test — counted sources only; `refetchOnMount:'always'`
- `rosterRoute.ts` — `rq=all.all.0`
- `ClusterPanelContext.tsx` — `stateRef=next`; close from functional prev + `{replace:true}`
- `appLinks.ts` — `WorkbenchPanelValue` includes `review` + `cluster`
- `ClusterReviewPanel.tsx` / `ScanTabContent.tsx` — face-group heading, owner status, Back focus
- `useClusterActions.ts`, `IdentityThumbnail.tsx` — face/person copy
- UX maps + e2e + `_cluster-panels.scss` + `_roster.scss`

## Canon (grepped)
| ID | File:line | How |
| --- | --- | --- |
| NAV-05 | `~/uxw2/canon/lexicons/interaction-ux.md:132` | unnamed faces single-homed in Workbench `rq=all` |
| NAV-07 | `interaction-ux.md:134` | drawer Close on load/404 |
| NAV-11 | `interaction-ux.md:138` | `panel=review&cluster=` restore; close clears |
| NAV-13 | `interaction-ux.md:140` | face / face group / person |
| NAV-02 | `interaction-ux.md:129` | Back + status re-cue queue |
| COG-01 | `interaction-ux.md:111` | CTA heading/body by known/zero/unknown |
| INT-06 | `interaction-ux.md:163` | Move not lying; Close names review |
| HAI-02 | `interaction-ux.md:211` | delete copy matches PHP reset (R1-29) |
| RLSE-04 | `engineering.md:695` | drawer loading/error designed |
| REF-09 | `engineering.md:328` | CTA count = landing filter |
| DATA-14 | `engineering.md:202` | URL owns drawer id |
| CAL-02 | `ml-systems.md:322` | unavailable total is unknown |
| TEST-15 | `engineering.md:396` | RED then mutant |
| A11Y-21 | `accessibility.md:132` | owner `role=status` |
| A11Y-11 | `accessibility.md:108` | Back focused on open |
| A11Y-14 | `accessibility.md:111` | Back ≥24px |
| A11Y-24 | `accessibility.md:154` | load/error keep Close |
| rg-015 | `docs/workbay/constitution.md:48` | envelope total + data_source only |

## Decisions
- Hide Move on the shim (no target list) rather than invent a second cluster list.
- Land CTA on `rq=all.all.0` so the unlabeled total is reachable (original assignment href was the defect).
- Keep `panel=review` (brief) ; overlay values survive close because we only delete when `prev.panel==='review'`. Opening review still overwrites an overlay — one place.
- Close uses `{replace:true}` so history.back does not reopen the panel.
- R1-29 already true after PHP `reset_curation`; left copy as-is.

## Undone
- `createMemoryRouter` `navigate(-1)` after close (R1-25/TESTS-01 grok2). `replace:true` is the production fix; no POP test.
- `reviewUrl` still mocks `useOpenReviewTargetLifecycle` (404 retire covered in `ClusterReviewPanel.test`).
- E2E not executed (needs LocalWP).
- PersonWorkspacePanel "Projection status" / "Source version" still out of this brief.

## Commits
- `87350a87a3f341d10140b06cbbb2a66f257d99b5` `fix(roster): UXW2-4-FE-R1 drawer shell, honest CTA, leftover jargon`
- `7091f711930193f20a7040284eb24d0d3aec1081` `fix(workbench): UXW2-4-FE-R1 review URL owner and face-group copy`

HEAD: 1fdfc8f7bcbc9b484fe14090da9a619dd8d20f83
