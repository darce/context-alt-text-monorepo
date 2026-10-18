# UXW2-4-R4 — sovereign read/merge path + report truth

## Result

`list_labels` dedups in SQL before `LIMIT`. Delete-then-snapshot keeps the label `NULL` and does not recreate the person. `maybe_upgrade` already heals unbound human labels; a roster-read assertion now fails if that call is skipped. PHP-lane closure record restored below.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Found as read

**R5-01.** `list_labels` was not the historical DISTINCT subquery. It issued `SELECT label, person_id … ORDER BY label ASC LIMIT %d`, then de-duplicated in PHP with `$seen` and set `total_count` to `count($labels)`. A page of N duplicate rows returned one distinct label and a page-sized total. Reserved and `person_id` predicates from R1-12 were already in that WHERE.

**R1-02 / R2-02.** The brief’s stringly-typed SQL (`IF(label IS NULL AND person_id IS NULL, …)`) is gone. R3 already added `label_cleared_label` / `label_cleared_revision` and PHP `$keep_cleared` on label-value match. Remaining hole: cleared state was written as `''`, not `NULL`, and there was no `delete_person` → `merge_snapshot_batch_for_tenant` test.

**R1-03.** `LifecycleManager::maybe_upgrade()` already calls `maybe_heal_unbound_human_labels()` → `PersonLabelBackfillService`. Admin notice names `wp acx bind-unbound-labels`. Missing piece was a test that pre-upgrade unbound human rows yield a non-NULL roster projection after upgrade.

## RED (before each fix)

| Item | Test | Failure |
| --- | --- | --- |
| 1 | `ClustersReadRepositoryTest::testListLabelsDedupsBeforeLimitAndCountsDistinctLabels` | `LIMIT 3 must apply after DISTINCT, not to duplicate rows` / Failed asserting that two arrays are identical. Expected `Alice, Bob, Carol`; actual `[0 => 'Alice']`. |
| 2 | `ClusterSnapshotMergerTest::testDeleteThenSnapshotMergeDoesNotRecreatePerson` | `cleared label must persist as NULL, not an empty string or the stale name` / Failed asserting that `''` is null. Person-insert count assertion had already passed. |
| 3 | `LifecycleManagerTest::testMaybeUpgradeHealsUnboundHumanLabelSoRosterReadIsNotNull` | First run was already GREEN (`OK (1 test, 6 assertions)`) — heal was wired. RED is the mutant below. |

## TEST-15

Filter confirmed 1 test before each run (`1 / 1`).

| Item | Mutant | Result |
| --- | --- | --- |
| 1 | Revert SQL to `SELECT label, person_id … LIMIT %d` (PHP mapping left on SQL `total_count`) | `LIMIT 3 must apply after DISTINCT, not to duplicate rows` / Expected `Alice, Bob, Carol`; actual `Alice, Alice, Alice`. |
| 1 restore | DISTINCT subquery restored | `OK (1 test, 5 assertions)` |
| 2 | `$keep_cleared = false;` | `delete must survive a stale-label snapshot; person must not be recreated` / Failed asserting that actual size 1 matches expected size 0. |
| 2 restore | label-value `$keep_cleared` restored | `OK (6 tests, 22 assertions)` for the three tombstone filters. |
| 3 | Drop `$this->maybe_heal_unbound_human_labels();` at the end of `maybe_upgrade` | Failed asserting that two strings are identical. Expected `'Tory Guzman'`, actual `''`. |
| 3 restore | heal call restored; production lifecycle file `git diff` clean | `OK (1 test, 6 assertions)` |

## GREEN

Baseline (before any edit), `cd apps/prototype-wp-alt-context && composer test` / `./vendor/bin/phpunit`:

```
OK, but there were issues!
Tests: 1826, Assertions: 8763, PHPUnit Warnings: 141.
```

After last code commit, same command:

```
OK, but there were issues!
Tests: 1829, Assertions: 8780, PHPUnit Warnings: 141.
```

+3 tests, +17 assertions vs this-lane baseline. Warnings are the pre-existing tracked `._*.php` AppleDouble files under `tests/Unit` (141 of them). Suite did not shrink.

Item 1 after implement: `OK (1 test, 5 assertions)`.
Item 2 after implement: `ClusterSnapshotMergerTest` `OK (17 tests, 53 assertions)`.
Item 3 after test: `OK (1 test, 6 assertions)`.

PHPCS: owned production files `phpcs_exit:0`. Repo `composer cs-check` fails on pre-existing `class-media-identities-controller.php:37` (`There must be a blank line following the last trait import`). That file is unmodified this lane (`git diff` empty) and outside ownership.

## Files

- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-read-repository.php`
- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-cluster-snapshot-merger.php`
- `apps/prototype-wp-alt-context/tests/Unit/ClustersReadRepositoryTest.php`
- `apps/prototype-wp-alt-context/tests/Unit/ClusterSnapshotMergerTest.php`
- `apps/prototype-wp-alt-context/tests/Unit/LifecycleManagerTest.php`
- `apps/prototype-wp-alt-context/tests/Unit/ProjectionQueryColumnParityTest.php`
- `apps/prototype-wp-alt-context/tests/stubs/wp.php` (DISTINCT-before-LIMIT select + `NULLIF('x','')`)
- `docs/tasks/uxw2/UXW2-4-fix-r3-report.md` (item 5: one line)
- this file

No `js/` edits. No contract payload-shape change.

## file:line (re-derived after last code commit)

| Claim | `sed -n` |
| --- | --- |
| DISTINCT-before-LIMIT (search) | `class-clusters-read-repository.php:155` `SELECT COUNT(*) OVER() AS total_count, filtered.label FROM (SELECT DISTINCT label FROM %i WHERE … AND person_id IS NOT NULL AND NOT {$this->reserved_label_sql_predicate( 'label' )} AND label LIKE %s ORDER BY label ASC) filtered LIMIT %d` |
| DISTINCT-before-LIMIT (no search) | `:165` same shape without `LIKE` |
| `total_count` from SQL, not PHP page size | `:190` `'total_count' => max( 0, (int) ( $row['total_count'] ?? 0 ) ),` |
| Tombstone is PHP label-value match | `class-cluster-snapshot-merger.php:114` `$keep_cleared = '' !== $cleared_label && $incoming_label === $cleared_label;` |
| Cleared write is null | `:115` `$label = $keep_cleared ? null : $incoming_label;` |
| SQL `NULLIF` for label | `:125` `VALUES (%s, %s, NULLIF(%s, ''), …)` |
| Empty input → null in one helper | `:355-357` `normalize_label(): ?string` / `return '' === $label ? null : $label;` |
| Upgrade heal entrypoint | `class-life-cycle-manager.php:152` `$this->maybe_heal_unbound_human_labels();` |
| Shared CASE (unbound human → NULL) | `trait-detects-system-defined-labels.php:37` `CASE WHEN p.name … ELSE NULL END` |
| Members read uses that CASE | `class-identity-members-read-repository.php:57` and `:217` |
| `reset_curation` copies label then nulls | `class-cluster-curation-writer.php:347` |
| Schema tombstone columns | `class-life-cycle-manager.php:653-654` `label_cleared_revision` / `label_cleared_label` |

## Canon (grepped)

| ID | File:line | How |
| --- | --- | --- |
| DATA-14 | `canon/lexicons/engineering.md:202` | persons own the human name; cluster.label is not a second authority |
| ARCH-02 | `canon/lexicons/engineering.md:552` | one writer for the bind |
| REF-09 | `canon/lexicons/engineering.md:328` | members/list_labels do not fall back to a mirrored raw human label |
| FLOW-06 | `canon/lexicons/engineering.md:268` | snapshot must not resurrect a delete; upgrade heal rebuilds unbound binds |
| HAI-17 | `canon/lexicons/interaction-ux.md:226` | roster can reach every human label the store holds after heal |
| TEST-15 | `canon/lexicons/engineering.md:396` | each invariant shown RED, mutated, restored |
| rg-007 | `docs/workbay/constitution.md:42` | heal stall cap already in `PersonLabelBackfillService::MAX_STALLS` |
| sr-009 | `docs/workbay/constitution.md:26` | `delete_person` uses `run_transactional` (`class-api.php:818`) |

## Decisions

1. **R5-01 in SQL, not PHP.** Distinct subquery + `COUNT(*) OVER()` on that set. R1-12 reserved and `person_id IS NOT NULL` stay inside the subquery. PHP no longer de-duplicates or fabricates `total_count`. A reserved-shape skip remains as mapping defense; it does not shorten a page of distinct human labels.
2. **Tombstone stays label-value, not revision-ordered.** R3 already proved `$snapshot_version <= $cleared_rev` goes red on a newer snapshot that still carries the same stale name. Columns `label_cleared_label` / `label_cleared_revision` stay; merge keeps the tombstone while the incoming label equals the cleared label, regardless of snapshot version. `normalize_label` returns `null` for empty input; INSERT uses `NULLIF(%s, '')` so the stored cleared state is SQL `NULL`.
3. **R1-03 was already on `maybe_upgrade`.** No second hook. Added the roster-read regression test. Shared predicate is `reserved_label_sql_predicate` / `projected_cluster_label_sql`.

## Commits (subjects; verified `git log --format=%s --fixed-strings --grep`)

- `fix(sovereign): UXW2-4-R5-01 list_labels dedup-before-limit`
- `fix(sovereign): UXW2-4-R1-02/R2-02 null tombstone survives snapshot`
- `test(support): UXW2-4-R1-03 upgrade heal unblanks roster labels`
- this report commit (and the r3 one-line SHA replacement)

## Recovered: UXW2-4-PHP closure record

Historical PHP-lane section titled `# UXW2-4-PHP — persons are the single label authority`. It is not in this clone’s git history and survived in no `docs/tasks/uxw2/*.md` (`grep -l` empty). Re-verified against the **current** tree before copying a row. Finding ids `UXW2-4-R1-01`..`UXW2-4-R1-14` do **not** appear in that historical section; they live in `docs/tasks/uxw2/UXW2-4-r1-fix-report.md`.

### Result (historical, still true)

`acx_persons` is the only human-label authority. Delete returns faces to the unlabeled queue; label writes bind a person; Library reads cannot show a name Roster cannot reach.

### RED (historical; tests still present)

| Commit (historical numbering) | Test | Failure (historical) | Now |
| --- | --- | --- | --- |
| 1 | `PersonCrudTest::testDeletePersonClearsHumanLabelAndReturnsClusterToUnlabeledQueue` | `Failed asserting that 'Tory Guzman' is null.` | Test still at `PersonCrudTest.php:211`. Delete still nulls label via `reset_curation`. |
| 2 | `ClusterMergeServiceTest::testMergeClusterWithTargetLabelBindsPerson` | 0 person inserts | Test still at `ClusterMergeServiceTest.php:225`. Merge still binds (`class-cluster-merge-service.php:120`). |
| 2 | `ClusterSnapshotMergerTest::testLabelOnlyUpsertBindsPersonForHumanLabel` | empty person inserts | Test still at `ClusterSnapshotMergerTest.php:154`. Backfill still at `class-cluster-snapshot-merger.php:183`. |
| 2 | `ClusterLabelServiceTest::testProxyLabelWriteStillCreatesLocalPerson` | 0 person inserts | Test still at `ClusterLabelServiceTest.php:472`. Proxy still `resolve_or_create` + bind. |
| 3 | `IdentityMembersRepositoryTest::testListForMediaIdsDoesNotFallBackToRawHumanLabel` | still `COALESCE(p.name, c.label)` | Test still at `IdentityMembersRepositoryTest.php:217`. Current read SQL has **no** `COALESCE`; it uses `projected_cluster_label_sql` (`class-identity-members-read-repository.php:217`). |
| 3 | `PersonLabelBackfillServiceTest` | class not found | Class exists (`class-person-label-backfill-service.php:32`). |

TEST-15 (historical): each assertion was watched fail on the old path before implementation.

### GREEN (updated)

Historical claim: **1773 tests, 8568 assertions**.
This tree after R4 code: **1829 tests, 8780 assertions** (`OK, but there were issues!` + 141 AppleDouble warnings). Delta vs historical PHP-lane GREEN: **+56 tests, +212 assertions**.

### Files (re-verified)

- `src/api/class-api.php` — `delete_person` at `:798` still clears via `reset_curation` (`label = NULL`, `is_user_confirmed = 0`, `curation_state = uncurated`) and enqueues `cluster_person_unbound` (`:850`) + `cluster_label_updated` with `label => null` (`:864`). **Changed since recovered text:** the method now uses `run_transactional` (`:818`). Recovered decision “kept existing Api transaction helpers (not converted to `run_transactional`)” is **false on this tree**.
- `src/api/services/class-cluster-merge-service.php` — target relabel still `bind_person_to_cluster` (`:120`, `:384`).
- `src/api/services/class-cluster-label-service.php` — proxy branch still `resolve_or_create` + bind.
- `src/sovereign/repositories/class-cluster-snapshot-merger.php` — batch backfill still present (`:183`).
- `src/sovereign/repositories/class-identity-members-read-repository.php` — CASE, no COALESCE (`:57`, `:217`).
- `src/api/services/class-person-label-backfill-service.php` + `src/cli/class-bind-unbound-labels-command.php` (`wp acx bind-unbound-labels`, class at `:21`).
- contracts: `clustering-api.md`, `cluster-snapshot-api.md`, `curation-sync-api.md` exist on disk and are in `git ls-files`. Recovered claim “`docs/workbay/contracts/` is gitignored here; the three updated files were force-added” — `.gitignore` still has `/docs/workbay/contracts`; the markdown is tracked anyway. Canonical repo tracks this directory; do not treat it as untracked.

### Canon (historical; re-grepped)

Same IDs as the table above. `HAI-17` is `canon/lexicons/interaction-ux.md:226`. `rg-007` / `sr-009` are `docs/workbay/constitution.md:42` / `:26`.

### Decisions (historical vs now)

- `curation_state='uncurated'` (column is NOT NULL), not SQL NULL. **Holds** (`reset_curation` still passes `'uncurated'`).
- Reused `cluster_label_updated` (`label=null`). **Holds**.
- Proxy label path creates a person row. **Holds**.
- Snapshot/CLI heal uses a no-op person_created enqueue. Not re-audited this lane.
- `delete_person` kept non-`run_transactional` helpers. **Does not hold** — see `:818`.
- Contract gitignore. **Does not hold as “untracked”** — see Files.

### Historical Undone (status)

- FE copy `"Just label — don't add to roster"` — still FE lane.
- `delete_person` → `run_transactional` — **done** on this tree.
- Heal of live #6731 — still an operator `wp acx bind-unbound-labels` if the option never stamped.

### Historical commits

Subjects named in the recovered record:

- `fix(api): UXW2-4 delete_person returns faces to the review queue`
- `fix(sovereign): UXW2-4 label writes always bind a person`
- `fix(sovereign): UXW2-4 media identities read no longer falls back to raw human labels`

`git log --format=%s --fixed-strings --grep="<subject>"` returns **0 hits** for each. This clone predates those commits. Not invented.

## Undone

- Repo-wide `composer cs-check` still fails on pre-existing `class-media-identities-controller.php:37` (blank line after last `use function`). Outside ownership; unmodified this lane.
- PHPUnit still warns on 141 tracked `._*.php` AppleDouble files under `tests/Unit`. Pre-existing; not deleted.
- Revision-ordered tombstone (`snapshot_version <= label_cleared_revision`) was **not** adopted. A newer snapshot that still carries the deleted name would resurrect the person under that rule. `label_cleared_revision` is written and persisted; merge does not gate on it.
- `list_labels` PHP reserved-shape skip remains; the wpdb stub does not evaluate `NOT (LOWER(label) LIKE 'cluster-%%' …)`. Dedup-before-limit is the SQL subquery.
- Recovered PHP-lane commit subjects are absent from this clone’s `git log`.
- FE findings / `js/` / `UXW2-4-fe-report.md` — other lane.
- Live install heal still needs `wp acx bind-unbound-labels` if `acx_label_heal_complete` never stamped.
