# UXW2-2 R4 REPORT

PHP / contract / schema / report-truth lane. Branch `feature/uxw2-2` (this throwaway mirror commits on `master`). Cite by subject line only.

Suite: **OK (1811 tests, 8722 assertions)** (`cd apps/prototype-wp-alt-context && composer test`).

## Items

| Finding | Commit (subject) | New / changed tests | RED (first write / mutant) | GREEN |
|---|---|---|---|---|
| R4-01 / R4-06 / R4-07 | `docs(report): UXW2-2-R4-01 R4-06 R4-07 subject-line citations and honest Undone` | git greps (no unit test) | mutant re-add a 40-hex token that `git cat-file -e` rejects → `grep -cE '\b[0-9a-f]{40}\b'` printed `1` | printed `0`; no `Branch \`master\``; no `^(empty)` |
| R3-02 / R3-04 | `fix(api): UXW2-2-R3-02 R3-04 total does not shrink on proxy drops` + `fix(api): UXW2-2-R3-02 R3-04 update remaining subtracted-total pins` | `testNormalizeTopUnlabeledResponseDropsDoNotShrinkTotal`; flipped envelope / mapper / controller / golden pins | first write: `Failed asserting that 10 is identical to 12.` | `OK (55 tests, 203 assertions)` targeted; then full suite after remaining pins |
| R4-02 | `fix(api): UXW2-2-R4-02 require repair_pending on top-unlabeled schema` | `testGoldenWithoutRepairPendingFailsRequired` | `Failed asserting that exception of type "UnexpectedValueException" is thrown.` | `OK (7 tests, 34 assertions)` then +invariant |
| R4-03 | `fix(api): UXW2-2-R4-03 assert identity_count covers representatives` | `testEveryGoldenSatisfiesIdentityCountInvariant` | see before/after pair below | `OK (8 tests, 50 assertions)` |
| R5-12 | `fix(api): UXW2-2-R5-12 count repair schedule at the service seam` | `testListTopUnlabeledSchedulesRepairExactlyOncePerRead` (`makeService` `count_repair_calls` flag) | see before/after pair below | `OK (14 tests, 65 assertions)` ClusterReadServiceTest |

Stretch S1 / S2 not started. S3 verified in this report (no code).

## Item 1 greps (after rewrite)

```
$ grep -cE "\b[0-9a-f]{40}\b" docs/tasks/uxw2/UXW2-2-r1-fix-report.md
0
$ grep -n "Branch \`master\`" docs/tasks/uxw2/UXW2-2-r1-fix-report.md
$ grep -n "^(empty)" docs/tasks/uxw2/UXW2-2-r1-fix-report.md
```

TEST-15: re-add a known-dead 40-hex token (does not resolve via `git cat-file -e`) → printed `1`. Revert → printed `0`.

### Subject-resolution loop (verbatim)

This mirror flattened `feature/uxw2-2` into a sync commit whose object is not present on this tree. Subjects below were already in the transplanted report (not invented here). None resolve on this tree:

```
fix(api): UXW2-2-R2-02 R1-06 R1-09 R2-12 proxy goldens and repair_pending -> 
fix(api): UXW2-2-R2-06 truncated is total_count greater than fetched_page -> 
fix(api): UXW2-2-R2-09 mapper ids take the repair-batch ceiling -> 
fix(api): UXW2-2-R3-04 total is pre-filter qualifying count -> 
fix(contracts): UXW2-2-R2-07 restore truncated clustering-api.md tail -> 
fix(sovereign): UXW2-2 exclude memberless clusters from top-unlabeled -> 
fix(sovereign): UXW2-2 golden identity_count matches observed members -> 
fix(sovereign): UXW2-2 identity_count reflects observed members -> 
fix(sovereign): UXW2-2-R1-01 R1-05 member count is sole size predicate -> 
fix(sovereign): UXW2-2-R1-02 R1-14 bidirectional identity_count -> 
fix(sovereign): UXW2-2-R1-03 drop memberless top-unlabeled rows -> 
fix(sovereign): UXW2-2-R1-04 R1-07 R1-13 mapper-owned targeted repair -> 
fix(sovereign): UXW2-2-R1-06 schema minItems and golden validation -> 
fix(sovereign): UXW2-2-R1-07 R1-06 plugin-load targeted heal and minItems -> 
fix(sovereign): UXW2-2-R1-07 R1-13 targeted heal test follow-through -> 
fix(sovereign): UXW2-2-R1-10 resolve identity members table via prefix -> 
fix(sovereign): UXW2-2-R1-10 resolve identity members table via prefix trait -> 
fix(sovereign): UXW2-2-R1-12 cap-hit fetch limit plus one -> 
fix(sovereign): UXW2-2-R2-02 R1-06 R1-09 drop empty-rep proxy rows -> 
fix(sovereign): UXW2-2-R2-03 R2-10 R1-07 targeted bootstrap dispatch -> 
fix(sovereign): UXW2-2-R2-04 delete tautological schema golden test -> 
fix(sovereign): UXW2-2-R2-05 restore exact bootstrap event counts -> 
fix(sovereign): UXW2-2-R2-06 R2-09 R2-11 envelope total and repair cap -> 
fix(sovereign): UXW2-2-R2-07 R2-08 mapper drop lt2 and stale-truncation count -> 
fix(sovereign): UXW2-2-R2-07 truncated identity_count never below preview -> 
fix(sovereign): UXW2-2-R2-12 repair_pending drives resync not drain -> 
fix(sovereign): UXW2-2-R2-13 exact top-unlabeled WHERE clause -> 
fix(tests): UXW2-2-R2-05 prove bootstrap event ceiling via call log -> 
fix(tests): UXW2-2-R2-11 drop without mapper id sets repair_pending -> 
```

No subject was invented. Empty SHA = flattened history, not a fabricated citation.

## Item 2 mutants

Restore subtraction at `class-cluster-response-envelope-service.php:153-156`:

```
Failed asserting that 10 is identical to 12.
```

Restore `if ( $projected_count <= $preview_limit && '' !== $cluster_id )` at mapper `:303`:

```
Failed asserting that an array contains 'cluster-truncated-9-5'.
```

(PHPUnit 10 wording; same assertion.)

## Item 4 before/after (prover GREEN → now RED)

Corrupt `list_top_unlabeled_proxy_success` first cluster `identity_count` to `0`.

**Before** (no cross-field assertion): `OK (7 tests, 34 assertions)` — GREEN. That green is the defect.

**After** (`testEveryGoldenSatisfiesIdentityCountInvariant`):

```
proxy-success cluster 0: identity_count must cover representatives
Failed asserting that 0 is equal to 1 or is greater than 1.
```

TEST-15 recorrupt (helper kept): same RED line. Fixture reverted.

## Item 5 before/after (prover GREEN → now RED)

Duplicate `$this->schedule_repair_from_mapper( $tenant_id, $extra_ids );` at `class-cluster-read-service.php:188`.

**Before** (`testListTopUnlabeledSchedulesRepairFromMapperRequestedIds` only): `OK (1 test, 5 assertions)` — GREEN. Cron map key-overwrites; `__ac_scheduled` count stays 1.

**After** (`testListTopUnlabeledSchedulesRepairExactlyOncePerRead`):

```
one read must emit exactly one repair schedule
Failed asserting that actual size 2 matches expected size 1.
```

Shape: `makeService(..., bool $count_repair_calls = false)` builds an anonymous `ClusterProjectionSyncService` subclass and stores it on `$this->countingSync`.

## Design changes to existing assertions

Only item 2's discarded rule. None deleted.

| Location | Was | Now | Why |
|---|---|---|---|
| `ClusterResponseEnvelopeServiceTest.php:125` | `assertSame(1, $data['total'])` | `assertSame(2, …)` | input `total => 2`, one drop; adopted rule does not shrink |
| `ClusterResponseMapperTest::testMapClusterListDoesNotLogExpectedPreviewTruncation` | `assertSame([], requested_repair…)` | `assertContains('cluster-truncated', …)` | widened truncation repair gate |
| `ClusterResponseMapperTest::testMapTopUnlabeledKeepsProjectedCountWhenPreviewIsTruncated` | `assertSame([], requested_repair…)` | `assertContains('cluster-truncated-9-5', …)` | same |
| `ClustersControllerTest.php:417` | `'total' => 0` | `'total' => 1` | one empty-rep drop, upstream `total` 1 |
| `ClustersControllerTest.php:490` | `assertSame(1, $data['total'])` | `assertSame(2, …)` | one empty-rep drop, upstream `total` 2 |
| `list_top_unlabeled_proxy_success/response.json` | `"total":1` | `"total":2` | characterization of the same proxy drop |
| `list_top_unlabeled_proxy_canonical_envelope/response.json` | `"total":1` | `"total":2` | same |

`assertTrue($data['repair_pending'])` kept on the envelope and controller drop cases.

## Contract decision

Adopted `:307` / schema `:113`: `total` is the pre-filter qualifying count. Drops set `repair_pending` and do **not** shrink `total`. Reasons: schema already publishes it; local-projection (primary path) already implements it; FE `total > served.length` repair fallback is only meaningful under this rule. `:296` was the outlier; the proxy envelope is what moved (`class-cluster-response-envelope-service.php:153` — `$total = max( 0, (int) $data['total'] );` only). Widened the mapper gate (`class-cluster-response-mapper.php:303`) so every preview truncation requests repair, including stale-high projected. Schema `:113` description left unchanged.

```diff
- Dropped rows are subtracted from `total`; `truncated` is not set from that filter. Any dropped invariant row sets `repair_pending: true` (same rule as the local-projection leg).
+ Dropped rows set `repair_pending: true` and do not shrink `total`; `truncated` is not set from that filter (same rule as the local-projection leg).

- When `observed > cap` the fetch is truncated: `identity_count = max(projected, representatives.length)` and request repair — do not publish `observed` as an exact count.
+ When `observed > cap` the fetch is truncated: `identity_count = max(projected, representatives.length)` and request repair (including when projected is stale-high) — do not publish `observed` as an exact count.
```

## Suite

```
$ cd apps/prototype-wp-alt-context && composer test
OK (1811 tests, 8722 assertions)
```

First full run after items 1–5 (before remaining pins): `FAILURES! Tests: 1811, Assertions: 8714, Failures: 4.` — the four discarded-rule pins listed above. After updating them: the GREEN line. No new failures besides those four. Zero suite red presented as green.

## Cross-lane fallout

No FE edit required. FE reads `total`; it does not compute it. After this change both legs publish the same pre-filter `total`, so `total > served.length` becomes true on proxy drops (it was previously false because the proxy subtracted). That matches the existing Resync fallback. If any TS helper assumed proxy `total === clusters.length` after the empty-rep filter, that assumption is now false — do not change it in this lane.

## Canon

| ID | file:line | how |
|---|---|---|
| TEST-06 | `~/uxw2/canon/lexicons/engineering.md:387` | every new test observed failing first |
| TEST-08 | `~/uxw2/canon/lexicons/engineering.md:389` | required-key + invariant checks are deterministic |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | each item's mutant went RED; items 4/5 were GREEN on the prover |
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | `total` is not a post-filter derived shrink; identity_count covers reps |
| OBS-08 | `~/uxw2/canon/lexicons/engineering.md:478` | empty Undone / cron-map silence were false health |
| RLSE-04 | `~/uxw2/canon/lexicons/engineering.md:695` | honest Undone is a designed residual state |
| DATA-01 | `~/uxw2/canon/lexicons/engineering.md:189` | `repair_pending` required so the envelope contract is stated |
| rg-005 | `docs/workbay/constitution.md:40` | schema `:113` / both legs / tests agree on `total` |
| rg-007 | `docs/workbay/constitution.md:42` | one read must not emit unbounded duplicate repair |
| rg-015 | `docs/workbay/constitution.md:48` | envelope `total` is the upstream qualifying count, not `count(kept)` |

## S3 (`UXW2-2-R1-07`) — verify only

- *"singleton_count still trusts the stale identity_count column"* — **false now.** `ClustersReadRepository::count_top_unlabeled_singletons` (`class-clusters-read-repository.php:336-374`) uses `( SELECT COUNT(*) FROM %i m WHERE m.cluster_uuid = c.cluster_uuid ) <= 1`.
- *"the only page-local repair scan"* — **false now.** `list_unlabeled_identity_count_drift` (`:278-317`) is wired at `class-cluster-read-service.php:186`.
- *"`repair_targeted_projection` ignores ids → un-targeted full bootstrap"* — **scoped when the job is targeted.** `repair_targeted_projection` (`class-cluster-projection-sync-service.php:176-192`) passes normalized ids into `schedule_bootstrap_sync_event` (`:122-129`). `perform_bootstrap_sync` (`:134-156`) calls `perform_targeted_snapshot` when ids are non-empty **and** the job implements `TargetedSyncPullJobInterface` (`:150-152`); otherwise it runs `perform_bypass_cooldown` (`:155`) — residual only if the wired job is not targeted.
- *"passing `PREVIEW_IDENTITIES_PER_CLUSTER` as third arg is a no-op"* — **stale.** Fourth argument at `class-cluster-read-service.php:177-181`; mapper uses it as the truncation cap.

## Undone

- UXW2-2-R4-04 (S1) — raw mapper-id array still drives the ceiling gate and `repair_pending`; scheduler normalizes later. Not started (budget).
- UXW2-2-R4-05 (S2) — missing `total_count` still falls back to `count( $unlabeled_items )` (`class-cluster-read-service.php:190-195`). Not started (budget).
- UXW2-2-R1-07 — targeted snapshot residual above if the pull job is not `TargetedSyncPullJobInterface`. No code change this lane.
- UXW2-2-R3-01 / R2-01 / R1-08 — still open on the task ref; outside both lanes' remaining code scope. R4-01 rewrote the SHA-citation form only. This flattened mirror still cannot resolve historical subjects.
