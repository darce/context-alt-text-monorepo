# UXW2-2 R10A REPORT

PHP / lint lane. Branch `feature/uxw2-2` (this throwaway mirror commits on `master`). Cite by subject line only.

Suite: **OK (1821 tests, 8798 assertions)** (`cd apps/prototype-wp-alt-context && composer test`).

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

file:line cites below were re-derived with `sed -n '<N>p' <file>` after the last code commit (`test(api): UXW2-2-R4-05 retarget targeted-repair golden total`).

## Items

| Finding | Commit (subject) | New / changed tests | RED (mutant, verbatim) | GREEN |
|---|---|---|---|---|
| R9-01 | `fix(tests): UXW2-2-R9-01 allow sha-lint:allow marker on report SHA lint` | `testShaLintAllowMarkerExemptsTokensOnThatLineOnly` | `unmarked forty-hex token must still be collected` / `Failed asserting that an array is not empty.` | `--filter testShaLintAllowMarkerExemptsTokensOnThatLineOnly` → `OK (1 test, 4 assertions)` (1/1). Class `--filter Uxw2ReportShaLintTest` → `OK (2 tests, 5 assertions)` (2/2) |
| R4-05 | `fix(api): UXW2-2-R4-05 missing total_count falls back to fetched-row count` + `test(api): UXW2-2-R4-05 retarget targeted-repair golden total` | `testListTopUnlabeledMissingTotalCountDoesNotShrinkOnDrop` | `missing total_count must fall back to pre-drop fetched-row count` / `Failed asserting that 1 is identical to 2.` | `--filter testListTopUnlabeledMissingTotalCountDoesNotShrinkOnDrop` → `OK (1 test, 5 assertions)` (1/1). Existing R3-04 `--filter testListTopUnlabeledTotalIsPreFilterQualifyingCount` → `OK (1 test, 4 assertions)` (1/1) |
| R4-04 | `fix(api): UXW2-2-R4-04 normalize mapper repair ids once` | `testListTopUnlabeledDuplicateMapperIdsStillRunDriftScan`; `testListTopUnlabeledAllBlankMapperIdsDoNotSetRepairPending` | Mutant A: `duplicate-bearing 25 raw mapper ids must still run the off-page drift scan` / `Failed asserting that 0 is identical to 1.` Mutant B: `all-blank mapper ids must not publish repair_pending` / `Failed asserting that true is false.` | `--filter testListTopUnlabeledDuplicateMapperIdsStillRunDriftScan` → `OK (1 test, 3 assertions)` (1/1). `--filter testListTopUnlabeledAllBlankMapperIdsDoNotSetRepairPending` → `OK (1 test, 3 assertions)` (1/1) |
| R8-08 | none (already absent) | `git ls-files --error-unmatch docs/workbay/contracts/clustering-api.md` | n/a — sentence already gone | printed `docs/workbay/contracts/clustering-api.md`; grep of `gitignor` / `workbay overlay` / `not in git` in the r4 report is empty |

## Item 1 — R9-01 (chose the shipped marker)

`collectFortyHexTokens` (`Uxw2ReportShaLintTest.php:85`) walks lines. A line containing the literal `sha-lint:allow` is skipped in full (`:89`). Tokens on unmarked lines are still asserted. Repo-wide glob sweep (`testEveryFortyHexTokenInUxw2ReportsResolvesToACommit`) is unchanged except that it now consumes the helper.

Allowlist test drives the helper directly: marked line + unresolvable token collects nothing; the same token without the marker still collects. Does not point at another branch's report.

TEST-15: unconditional `continue` (skip every forty-hex token whether or not the marker is present) → RED quoted above on the no-marker `assertNotEmpty`. Restore.

## Item 2 — R4-05 (chose (a))

Specified and tested the missing-column fallback so it cannot shrink on a drop. Did **not** fail closed.

When `total_count` is absent, `$total = $fetched_page` (`class-cluster-read-service.php:205`), the pre-drop fetched-row count, not `count( $unlabeled_items )`. Documented on `clustering-api.md:308`. Existing R3-04 test (`ClusterReadServiceTest.php:427`, seeds `total_count => 2`) is unchanged.

New case (`:492`) omits `total_count` and mapper-drops a row; published `total` is 2.

TEST-15: revert the else-branch to `count( $unlabeled_items )` → RED quoted above. Restore.

Characterization pin `list_top_unlabeled_targeted_repair` had `total: 0` on a one-row drop with no `total_count`. That was the old shrink. Retargeted to `total: 1` so the suite stays honest. Fixture is outside the lane ownership list; required for `composer test` GREEN.

## Item 3 — R4-04

Normalize once at the top via `normalize_repair_cluster_ids` (`class-cluster-read-service.php:189`, helper `:424`). That same array drives the ceiling gate (`:193`), `schedule_repair_from_mapper( …, $mapper_ids )` (`:196`, `:442`), and `repair_pending` (`:207`). Other callers still pass `mapper_ids=null` and the helper fetches+normalizes.

Tests inject a mapper stub (drive the service directly; mapper empty-id skip is irrelevant).

TEST-15 A: gate on the raw array again → duplicate-bearing 25-id case RED quoted above. Restore.
TEST-15 B: `repair_pending` from the raw array again → all-blank-ids case RED quoted above. Restore.

## Item 4 — R8-08

The gitignored-overlay sentence is already absent from `UXW2-2-r4-fix-report.md` (r5 recorded the deletion). Did not re-explain. Did not replace it.

```
$ git ls-files --error-unmatch docs/workbay/contracts/clustering-api.md
docs/workbay/contracts/clustering-api.md
```

## Design changes to existing assertions

| Location | Was | Now | Why |
|---|---|---|---|
| `list_top_unlabeled_targeted_repair/response.json` | `"total":0` | `"total":1` | missing `total_count` + one mapper drop; (a) publishes fetched-row count |

R3-04 `assertSame(2, $data['total'])` kept. No assertion deleted to go green.

## Suite

```
$ cd apps/prototype-wp-alt-context && composer test
OK (1821 tests, 8798 assertions)
```

Zero suite red presented as green. After (a), the targeted-repair golden was the one pin that moved (first full run `Failures: 1` on that fixture); retarget → the GREEN line.

## Cross-lane fallout

No `js/` edit. FE already treats `total` as the qualifying count. Missing-column pages now publish fetched-row `total` instead of served length, so `total > served.length` can become true on a local-projection drop that omitted `total_count`.

## Canon

| ID | file:line | how |
|---|---|---|
| TEST-06 | `~/uxw2/canon/lexicons/engineering.md:387` | each new test observed failing first |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | each mutant went RED; restored |
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | `total` is not a post-filter shrink |
| rg-015 | `docs/workbay/constitution.md:48` | missing `total_count` fallback is specified; `repair_pending` matches normalized ids |

## Undone

- FE untouched; skipped `npx vitest run`.
- Overlay `.gitignore` still lists `/docs/workbay/contracts`, so a force-add is required to stage the tracked contract file. The false r4 integrator sentence is gone; this overlay ignore is the residual R8-08 noted in r5.
- `repair_pending` still ORs the raw drift-id array (`extra_ids`) rather than a normalized copy. Out of this brief.
- MCP `workbay_handoff_mcp` Python API is not importable in this lane worktree (`ModuleNotFoundError`). No handoff write.
- Flattened mirror still cannot resolve historical subjects from earlier rounds.
