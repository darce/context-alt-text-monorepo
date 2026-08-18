# UXW2-4-PHP — persons are the single label authority

## Result
`acx_persons` is the only human-label authority. Delete returns faces to the unlabeled queue; label writes bind a person; Library reads cannot show a name Roster cannot reach.

## RED
| Commit | Test | Failure |
| --- | --- | --- |
| 1 | `PersonCrudTest::testDeletePersonClearsHumanLabelAndReturnsClusterToUnlabeledQueue` | `Failed asserting that 'Tory Guzman' is null.` |
| 2 | `ClusterMergeServiceTest::testMergeClusterWithTargetLabelBindsPerson` | 0 person inserts |
| 2 | `ClusterSnapshotMergerTest::testLabelOnlyUpsertBindsPersonForHumanLabel` | empty person inserts |
| 2 | `ClusterLabelServiceTest::testProxyLabelWriteStillCreatesLocalPerson` | 0 person inserts |
| 3 | `IdentityMembersRepositoryTest::testListForMediaIdsDoesNotFallBackToRawHumanLabel` | still `COALESCE(p.name, c.label)` |
| 3 | `PersonLabelBackfillServiceTest` | class not found |

TEST-15: each assertion was watched fail on the old path before implementation.

## GREEN
`composer test` in `apps/prototype-wp-alt-context`: **1773 tests, 8568 assertions, OK**.

## Files
- `src/api/class-api.php` — delete clears `label`, `is_user_confirmed=0`, `curation_state=uncurated`; enqueues `cluster_person_unbound` + `cluster_label_updated`
- `src/api/services/class-cluster-merge-service.php` — target relabel `resolve_or_create` + bind
- `src/api/services/class-cluster-label-service.php` — proxy branch persists a local person
- `src/sovereign/repositories/class-cluster-snapshot-merger.php` — batch backfill
- `src/sovereign/repositories/class-identity-members-read-repository.php` — CASE, no COALESCE fallback
- `src/api/services/class-person-label-backfill-service.php` + `src/cli/class-bind-unbound-labels-command.php` (`wp acx bind-unbound-labels`)
- contracts: `clustering-api.md`, `cluster-snapshot-api.md`, `curation-sync-api.md`

## Canon (grepped)
| ID | File:line | How |
| --- | --- | --- |
| DATA-14 | `~/uxw2/canon/lexicons/engineering.md:202` | persons own the human name; cluster.label is derived/auto |
| ARCH-02 | `~/uxw2/canon/lexicons/engineering.md:552` | single writer for the label: person bind path |
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | Library no longer reads a mirrored raw cluster label |
| FLOW-06 | `~/uxw2/canon/lexicons/engineering.md:268` | snapshot + CLI backfill heal unbound human labels |
| HAI-17 | `~/uxw2/canon/lexicons/interaction-ux.md:226` | Roster can now reach every human label the store holds |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | RED captured before each implement |
| rg-007 | `docs/workbay/constitution.md:42` | backfill stall cap `MAX_STALLS=3` |
| sr-009 | `docs/workbay/constitution.md:26` | merge/label bind inside `run_transactional` |

## Decisions
- `curation_state='uncurated'` (column is NOT NULL), not SQL NULL.
- Reused `cluster_label_updated` (`label=null`) so the backend learns the name is gone; did not invent an op.
- Proxy label path creates a person row (schema allows person without projected clusters). No `roster_bound:false`.
- Snapshot/CLI heal uses a no-op person_created enqueue (persons are local-only).
- `delete_person` kept the existing Api transaction helpers (not converted to `run_transactional`).
- `docs/workbay/contracts/` is gitignored here; the three updated files were force-added.

## Undone
- FE copy `"Just label — don't add to roster"` (PHP-only lane).
- `delete_person` → `run_transactional` refactor.
- Heal of live #6731 (needs `wp acx bind-unbound-labels` on the site).

## Commits
- `2b850d3` `fix(api): UXW2-4 delete_person returns faces to the review queue`
- `4eb8a9b` `fix(sovereign): UXW2-4 label writes always bind a person`
- `2a6775a` `fix(sovereign): UXW2-4 media identities read no longer falls back to raw human labels`

HEAD: 2a6775a9ad94a6db1c50f64bc0cf9e77e81b2e4d (code) + this REPORT commit

---

# REPORT — LANE UXW2-4-FE

Roster: retire needs-assignment rail, plain wording, workbench review-panel legibility. All three commits on `master`, TDD (RED before implementation) throughout.

## Commits

| Commit | Message |
| --- | --- |
| `9ea1512` | fix(roster): UXW2-4 retire needs-assignment rail, link to workbench queue |
| `0bd168f` | fix(roster): UXW2-4 plain-language wording |
| `43ad0dc` | fix(workbench): UXW2-4 review panel is legible: back affordance + URL + status |

Final `git rev-parse HEAD`: `43ad0dc21289f63adbcfb37fa818408aa51f6ffa`

## RED evidence

- Commit 1: `RosterPage.reviewCta.test.tsx` (new) failed before implementation — CTA link href `#/workbench?tab=scan&rq=assignment.all.0` absent, rail still rendered. Also failed module resolution on `../roster/hooks/useTopUnlabeledTotal` (hook did not exist yet).
- Commit 2: `banned-vocabulary.test.tsx` › `roster surfaces render without cluster/identity jargon` failed: rendered drawer text contained `unresolved cluster … 2 identities … no other clusters available to move this identity into … drop identities here … assign to identity`.
- Commit 3: `ScanTabContent.reviewUrl.test.tsx` (new) — 3/3 failed: no `panel=review&cluster=` in URL on open, no panel restore from URL, no `← Back to Review Suggestions` button.

## GREEN evidence

- Commit 1 scope: roster + RosterPage suites pass; `RosterPage.reviewCta.test.tsx` 3/3.
- Commit 2 scope: 222/222 across banned-vocabulary, roster `__tests__`, RosterPage suites, RosterEntries.
- Commit 3 scope: 83 files / 1195 tests (workbench + navigation + banned-vocabulary) pass; new test 3/3.
- Full suite after all commits: **206 files / 2317 tests, all passed** (`npx vitest run`, 348s).
- `npm run typecheck` clean; `eslint` clean on all touched files; uxmap JSON parses.

## Files changed (46 total; highlights)

- Commit 1: `RosterPage.tsx` (rail removed, CTA card with server-reported count), new `roster/hooks/useTopUnlabeledTotal.ts` (reads `total` from `/clusters/top-unlabeled` envelope only — never invented), deleted `NeedsAssignmentSection.tsx` + test, `BulkActionBar.tsx` + test, `useRosterBulkConfirmation.ts`; `rosterRoute.ts` (`isUnlabeledCluster` removed); new `RosterPage.reviewCta.test.tsx`; updated `RosterZeroStateReachability`, `RosterPage.container/workspace`, `rosterRoute.test.ts`, e2e `roster-keyboard-walk.spec.ts` (rail walk → CTA assertion; member-fix loop gated on `E2E_ROSTER_CLUSTER_ID` deep link).
- Commit 2: copy pass in `RosterPage.tsx`, `ClusterDrawerPanel.tsx`, `RosterEntriesTable.tsx`, `RosterEntriesSection.tsx`, `PersonWorkspacePanel.tsx`, `PersonFaceFilmstrip.tsx`, `personFaces.ts`, `similarityCopy.ts` (faces / face group / person); `banned-vocabulary.test.tsx` now renders `PersonWorkspacePanel` + `ClusterDrawerPanel` and bans `cluster`, `identities`, `projected instances` on Roster surfaces; `docs/ux-maps/roster-people.md` gained a Vocabulary say/don't-say section and marks the rail retired.
- Commit 3: `ClusterPanelContext.tsx` (URL sync: `panel=review&cluster=<id>`, one `setSearchParams` write per transition, panel/cluster keys only), `appLinks.ts` (`APP_LINK_VALUES.panelReview`), `ClusterReviewPanel.tsx` (visible back button + `role="status"` announcement), `workbench-operator-loop.uxmap.json` (`panel`,`cluster` added to workbench-scan params), new `ScanTabContent.reviewUrl.test.tsx`, `ClusterReviewPanel.test.tsx` wrapped in `MemoryRouter` (provider now needs a router).

## Canon IDs satisfied (verified by grep)

- NAV-05 — `~/uxw2/canon/lexicons/interaction-ux.md:132` (MECE: needs-assignment single-homed in Workbench queue)
- NAV-13 — `interaction-ux.md:140` (controlled vocabulary; say/don't-say published in roster-people.md)
- NAV-11 — `interaction-ux.md:138` (review panel deep-links via `panel=review&cluster=<id>`)
- NAV-07 — `interaction-ux.md:134` (visible escape hatch: Back button, not only X)
- NAV-02 — `interaction-ux.md:129` (queue remounts at lifted index; no silent re-cue-less swap — back affordance + status announce the move)
- COG-01 — `interaction-ux.md:111` (current state externalized: visible heading + URL)
- COG-02 — `interaction-ux.md:112` (CTA link + count instead of recall of queue location)
- HAI-01 — `interaction-ux.md:210` (CTA/deep link route to face evidence before label action; rail's face-less IDs removed)
- INT-06 — `interaction-ux.md:163` (back affordance names its target: "← Back to Review Suggestions")
- A11Y-21 — `accessibility.md:132` (`role="status"`: "Reviewing faces — press Back to return to suggestions")
- A11Y-14 — `accessibility.md:111` (noted: cited by DIAGNOSIS for thumbnail alt; actual canon row is target size 2.5.8 — no dense-target change in this lane)
- A11Y-19 — `accessibility.md:130` (noted: cited by DIAGNOSIS for alt; actual row is cognitive gate 3.3.7/3.3.8 — not exercised; the alt-purpose canon is A11Y-02, `accessibility.md:70`, satisfied by existing `IdentityThumbnail` alt copy)
- rg-015 — repo guard, `docs/workbay/constitution.md:48` (CTA count comes from the `top-unlabeled` envelope `total` only; unknown → fallback copy, never `count(payload)`)

## Decisions made

- CTA count source: new `useTopUnlabeledTotal` hook reusing the workbench queue's query key + limit so both surfaces share one cache entry; `null` while loading/error → "Unnamed faces are reviewed in the Workbench."
- `ClusterDrawerPanel` stays mounted only for `?cluster=` deep links; drawer data comes solely from `useRecognitionCluster(selectedClusterId)` and rendering is gated on `selectedClusterId` so close works without the retired list query.
- Bulk merge/dismiss reachability intentionally NOT re-added (brief: later task; E21-9 Q1).
- RosterEntriesTable column `Clusters` → `Face groups` (the number counts clusters), `Identity` → `Person`; delete copy → "Assigned faces return to the review queue."
- `Commit to roster entry` combobox aria-label left unchanged: no banned word, and the phrase is shared with workbench `personCommitCopy` (out of lane scope).
- URL sync lives in `ClusterPanelProvider` (wrapped dispatch writes; URL→state effect for back/forward; reducer initializer for reload). `useWorkbenchFilters.ts` and `rq=` handlers untouched per brief. `panel=review` coexists with overlay values: `useOverlayParam` whitelists `conflicts`/`dead-letter` and ignores `review` without rewriting.
- Status announcement placed inside `ClusterReviewPanel` so it travels with the panel mount; visible `h2` "Review Cluster" retained (SR-only region heading in `ScanTabContent` kept for `aria-labelledby` stability per L3R-08).

## Undone / partial

- E2E (`tests/e2e/**`) updated but not executed (needs LocalWP); unit/typecheck/lint all green.
- `?cluster=` parser retirement deferred per E21-10 (shim kept intentionally).
- PersonWorkspacePanel still renders "Projection status"/"Source version"/"Curriculum review queues" (globally banned strings that escape the page sweep behind `?person=`); out of this brief's three-word roster ban — flagged for a follow-up.
