# UXW2-2 R5 REPORT

PHP / contract / schema / report-lint lane. Branch `feature/uxw2-2` (this throwaway mirror commits on `master`). Cite by subject line only.

Suite: **OK (1817 tests, 8783 assertions)** (`cd apps/prototype-wp-alt-context && composer test`).

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Items

| Finding | Commit (subject) | New / changed tests | RED (first write / mutant) | GREEN |
|---|---|---|---|---|
| R6-01 | `fix(api): UXW2-2-R6-01 request truncation repair only when projection is stale-low` | `testMapTopUnlabeledHealthyOversizedTruncationDoesNotRequestRepair`; `testMapTopUnlabeledStaleLowTruncationRequestsRepair`; healthy-truncation pins now expect empty repair | first write + mutant: `healthy oversized cluster must not schedule truncation repair` / `Failed asserting that two arrays are identical.` | `OK (4 tests, 14 assertions)` targeted mapper |
| R8-05 | `fix(api): UXW2-2-R8-05 emit repair_pending on every top-unlabeled envelope` | `testListTopUnlabeledBootstrappingEnvelopeValidatesAgainstSchema`; `testListTopUnlabeledBackendProxyOmittingRepairPendingValidatesAgainstSchema`; TS required-set equality | first write + mutant: `UnexpectedValueException: $ required repair_pending` | `OK (4 tests, 18 assertions)` + vitest `Tests  2 passed` |
| R6-04 | `fix(api): UXW2-2-R6-04 enforce identity_count covers representatives at emit time` | glob-driven `testEveryGoldenSatisfiesIdentityCountInvariant`; `testIdentityCountBelowRepresentativesFailsInvariant` | glob first-write GREEN (fixtures exist). TEST-15 empty glob: `clusters-read response glob must match at least one fixture` / `Failed asserting that an array is not empty.` | `OK (2 tests, 65 assertions)` |
| R5-12 | already on tree: `fix(api): UXW2-2-R5-12 count repair schedule at the service seam` | `testListTopUnlabeledSchedulesRepairExactlyOncePerRead` (r4) | duplicate `schedule_repair_from_mapper` → `one read must emit exactly one repair schedule` / `Failed asserting that actual size 2 matches expected size 1.` | `OK (1 test, 4 assertions)` — no new commit |
| R8-07 / R6-03 | `fix(tests): UXW2-2-R8-07 R6-03 lint uxw2 report SHAs against git objects` | `Uxw2ReportShaLintTest` | first write: r4 report cites unresolved commit / `Failed asserting that false is true.` Mutant re-insert dead token: same. Empty-glob: `uxw2 report glob must match at least one markdown file` / `Failed asserting that an array is not empty.` | `OK (1 test, 1 assertion)` |

## Item 1

`resolve_identity_count` truncated branch (`class-cluster-response-mapper.php:311`) is again `$projected_count <= $preview_limit && '' !== $cluster_id`. Healthy oversized (projected=7, cap=4, 5 rows) keeps `identity_count` 7 and does not request repair (`ClusterResponseMapperTest.php:452`). Stale-low (projected=3, same fetch) still requests repair (`:489`) and still returns `max(projected, preview_limit)`.

Contract invariant bullet (`clustering-api.md:307`) no longer says "request repair including stale-high".

Existing healthy-truncation pins (`projected=9`) now assert empty repair. That is the r4 widening reversed, not a loosened assertion.

TEST-15: delete `$projected_count <= $preview_limit` → same RED as first write. Restore; mapper diff only the restored condition.

## Item 2

Bootstrapping/unavailable envelope now includes `repair_pending => false` (`class-cluster-read-service.php:167`). Backend_proxy leg normalizes a missing/non-bool key to `false` and does not invent `true` (`:150-151`).

Schema already required the key (`recognition-cluster-top-unlabeled-response.schema.json:7`). New PHP tests validate the **actual** service payloads against that schema (`ClusterReadServiceTest.php:884`, `:930`). TS contract test asserts the full required set by `Set` equality (`topUnlabeledClustersContract.test.ts:32-34`).

Contract bullets now match the schema required list (`clustering-api.md:296`, `:301`). Example envelope also carries `repair_pending`. Bootstrapping golden fixture and the controller exact-array pin updated in the same commit.

TEST-15: delete `'repair_pending' => false` from the unavailable envelope → `UnexpectedValueException: $ required repair_pending`. Restore; production diff only the intended two sites.

## Item 3

`testEveryGoldenSatisfiesIdentityCountInvariant` now globs `tests/fixtures/clusters-read/*/response.json` plus the contract golden (`ClusterTopUnlabeledSchemaConsistencyTest.php:93-97`) and fails if the glob is empty. Negative case mutates `identity_count` below `count(representatives)` (`:115`). Mapper emit-time clamp: `$identity_count = max( $identity_count, count( $representatives ) )` (`class-cluster-response-mapper.php:142`).

TEST-15: point `FIXTURE_RESPONSES_GLOB` at a directory with no matches → `Failed asserting that an array is not empty.` Restore.

## Item 4

Already present. Proof (`sed` after last code commit):

- `class-cluster-read-service.php:194` — single `schedule_repair_from_mapper( $tenant_id, $extra_ids )`
- `ClusterReadServiceTest.php:206` — `assertCount(1, $this->countingSync->repairCalls, 'one read must emit exactly one repair schedule')`

Duplicating the schedule line goes RED on that assertion. Filter selected `testListTopUnlabeledSchedulesRepairExactlyOncePerRead` (1 test). Restore left production clean. No new commit.

## Item 5

Deleted the dead 40-hex token and the second unresolved 40-hex token from `UXW2-2-r4-fix-report.md` (both fail `git cat-file -e` on this tree). Mutant described in prose. Deleted the sentence that `docs/workbay/contracts/clustering-api.md` is gitignored / not in git — the file is tracked and was updated in the R8-05 commit.

`Uxw2ReportShaLintTest.php` globs `docs/tasks/uxw2/*.md`, extracts `\b[0-9a-f]{40}\b`, and requires `git cat-file -e <sha>^{commit}`. Skips when `git` is missing. Empty glob fails. Lives in `composer test` (no Makefile target).

TEST-15: re-insert a known-dead 40-hex token into the r4 report → `Failed asserting that false is true.` Restore. Empty-glob mutant also RED as above.

## Design changes to existing assertions

| Location | Was | Now | Why |
|---|---|---|---|
| `ClusterResponseMapperTest::testMapTopUnlabeledKeepsProjectedCountWhenPreviewIsTruncated` | `assertContains('cluster-truncated-9-5', requested_repair)` | `assertSame([], requested_repair)` | r4 widening was the livelock; healthy oversized must not repair |
| `ClusterResponseMapperTest::testMapClusterListDoesNotLogExpectedPreviewTruncation` | `assertContains('cluster-truncated', …)` | `assertSame([], …)` | same |
| `ClustersControllerTest` bootstrap exact array | no `repair_pending` | `repair_pending => false` | schema required |
| `list_top_unlabeled_proxy_bootstrapping_fallback/response.json` | omitted key | `repair_pending: false` | same |
| `topUnlabeledClustersContract.test.ts` | `arrayContaining` five-key subset | exact `Set` of six required keys | addition/removal cannot pass silently |

No assertion deleted to go green.

## Suite

```
$ cd apps/prototype-wp-alt-context && composer test
OK (1817 tests, 8783 assertions)
```

Zero suite red presented as green.

## Cross-lane fallout

No other `js/` files touched. FE already treats missing `repair_pending` as false; the plugin now always emits the key. Parallel FE lane owns the optional `repair_pending?` TS field.

## Canon

| ID | file:line | how |
|---|---|---|
| TEST-06 | `~/uxw2/canon/lexicons/engineering.md:387` | new tests observed failing first (R6-01, R8-05, R8-07) |
| TEST-08 | `~/uxw2/canon/lexicons/engineering.md:389` | schema + glob + SHA lint are deterministic |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | each item's mutant went RED; R5-12 re-proved on the r4 test |
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | projected `identity_count` is not a live member count |
| OBS-08 | `~/uxw2/canon/lexicons/engineering.md:478` | empty glob / missing SHA must fail, not read as health |
| DATA-01 | `~/uxw2/canon/lexicons/engineering.md:189` | `repair_pending` required so the envelope contract is stated |
| RLSE-04 | `~/uxw2/canon/lexicons/engineering.md:695` | bootstrapping is a designed envelope, not a missing key |
| rg-005 | `docs/workbay/constitution.md:40` | schema / prose / runtime agree on required keys |
| rg-007 | `docs/workbay/constitution.md:42` | one read must not emit duplicate repair |
| rg-015 | `docs/workbay/constitution.md:48` | omitted `repair_pending` normalizes to false; never invent true |

## Undone

- UXW2-2-R4-04 (S1) — raw mapper-id array still drives the ceiling gate and `repair_pending`; scheduler normalizes later. Not started.
- UXW2-2-R4-05 (S2) — missing `total_count` still falls back to `count( $unlabeled_items )` (`class-cluster-read-service.php:196-201`). Not started.
- R6-04 emit-time clamp had no independent first-write RED: `resolve_identity_count` already published `max(projected, preview_limit)` on the truncated stale-low path. The glob empty-dir mutant is the item's TEST-15. The clamp is defense in depth so a later resolve regression cannot emit `identity_count < representatives.length`.
- R5-12 needed no production change on this tree. The r4 service-seam counter already kills the duplicate-schedule mutant.
- This mirror's `.gitignore` still lists `/docs/workbay/contracts`. The file is tracked (`git ls-files`) and was updated in the R8-05 commit. Do not treat the overlay ignore as "not in git".
- Flattened history still cannot resolve historical subjects from earlier rounds.
- FE `repair_pending?` remains optional on the TS type. Parallel lane.
