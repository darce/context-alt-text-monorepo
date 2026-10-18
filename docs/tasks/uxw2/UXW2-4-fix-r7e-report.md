# UXW2-4-R1-03 — upgrade heal for unbound human labels

## Result

Existing installs no longer lose human cluster names on deploy. Upgrade/activate runs a bounded person-label backfill before operators hit the new read CASE. Shared reserved-label SQL was already closed. Identity-member reads now emit `label_state`.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

`file:line` cites below were re-derived with `sed -n '<N>p' <file>` after the code commit.

## Closure

| Clause | Disposition | Mutant RED (verbatim) |
| --- | --- | --- |
| 1 Heal on upgrade | **Closed.** `activate()` and `maybe_upgrade()` already called `maybe_heal_unbound_human_labels()`. This lane bound the inner loop (`MAX_HEAL_BATCHES_PER_LOAD = 5` → 500 rows) and refused to stamp `acx_label_heal_complete` on cap/stall so the remainder resumes. Tenant is the single WP-install value from `TenantIdentity::resolve()` — same assumption as the rest of this file and `wp acx bind-unbound-labels`. Schema stamp (`acx_version`) stays independent of heal so a long backfill does not re-run dbDelta every request. Heal success is its own stamp, mirroring schema-apply retry. | A: remove the trailing heal call in `maybe_upgrade`. `testMaybeUpgradeHealsUnboundHumanLabelSoRosterReadIsNotNull` **1 / 1** RED: `Failed asserting that two strings are identical.` / expected `'Tory Guzman'` / actual `''`. |
| 2 Shared predicate | **Already closed.** No production change. Search evidence below. Added a read-path pin so a hyphen-only `LIKE 'cluster-%'` still goes red. | C: hand-roll the tenant `list_for_cluster` CASE to `LIKE 'cluster-%'`. `testReadPathsEmitLabelStateAndSharedReservedPredicateIncludingUnderscore` **1 / 1** RED: `Failed asserting that 'SELECT … LIKE 'cluster-%' …' contains "LIKE 'cluster\_%%'"`. |
| 3 `label_state` | **Closed on owned reads.** Trait emits `person \| unlabeled \| unbound`; all four identity-members SELECTs use `projected_cluster_label_select_sql()`. Mapper / clusters-read / contract / FE are not owned this round. | No required mutant. `testResolveClusterLabelStateNamesAuthority` with `cluster_ab12` → `unlabeled` is **6 / 6**. Same C mutant also drops `AS label_state` / `THEN 'person'` on that query. |

Mutant B (stamp success on failed heal): `testMaybeUpgradeDoesNotMarkHealCompleteWhenStalledAndRetries` **1 / 1** RED: `Failed asserting that two strings are not identical.` Plus `testMaybeUpgradeDoesNotStampHealCompleteWhenCappedAndPassesBatchBound` **1 / 1** RED: `capped heal must not stamp success (remainder must resume)` / `Failed asserting that two strings are not identical.`

Each mutant restored after the RED. Production `git diff` after restore was the intended change only.

## GREEN

`cd apps/prototype-wp-alt-context && composer test`:

```
OK (1845 tests, 8855 assertions)
```

R6 baseline on this tree was `OK (1834 tests, 8814 assertions)`. +11 tests, +41 assertions.

Targeted `--filter` (selected / total):

| Filter | Result |
| --- | --- |
| `testMaybeUpgradeHealsUnboundHumanLabelSoRosterReadIsNotNull` | **1 / 1** `OK (1 test, 6 assertions)` |
| `testMaybeUpgradeDoesNotMarkHealCompleteWhenStalledAndRetries` | **1 / 1** `OK (1 test, 4 assertions)` |
| `testMaybeUpgradeDoesNotStampHealCompleteWhenCappedAndPassesBatchBound` | **1 / 1** `OK (1 test, 2 assertions)` |
| `testBackfillHonorsMaxBatchesAndReportsCapped` | **1 / 1** `OK (1 test, 5 assertions)` |
| `testReadPathsEmitLabelStateAndSharedReservedPredicateIncludingUnderscore` | **1 / 1** `OK (1 test, 21 assertions)` |
| `testResolveClusterLabelStateNamesAuthority` | **6 / 6** `OK (6 tests, 6 assertions)` |
| `testProjectedLabelStateSqlNamesUnboundUnlabeledAndPerson` | **1 / 1** `OK (1 test, 4 assertions)` |
| union of the new/heal filters | **15 / 15** `OK (15 tests, 55 assertions)` |
| `LifecycleManagerTest\|PersonLabelBackfillServiceTest\|DetectsSystemDefinedLabelsTest\|IdentityMembersReadRepositoryTest\|IdentityMembersRepositoryTest\|BindUnboundLabelsCommandTest` | **104 / 104** `OK (104 tests, 417 assertions)` |

## Clause 2 search (already closed)

`LIKE 'cluster-%'` / `cluster-%` under `apps/prototype-wp-alt-context/src/**/*.php`:

- only hit: `trait-detects-system-defined-labels.php:32` — the shared predicate, which is **both** `cluster-%%` and `cluster\_%%`.

Every read uses that helper, not a hand-rolled hyphen-only LIKE:

- identity-members: `:57`, `:75`, `:136`, `:217` via `projected_cluster_label_select_sql` → `reserved_label_sql_predicate`
- clusters-read (sibling, not edited): `projected_cluster_label_sql` / `reserved_label_sql_predicate`
- backfill list: `class-person-label-backfill-service.php` `NOT reserved_label_sql_predicate('label')`

PHP `is_reserved_label_shape()` is `/^cluster[-_]/i` after unicode trim (`:17`).

## Bound

`MAX_HEAL_BATCHES_PER_LOAD = 5` × `BATCH_SIZE = 100` = **500 clusters per request**.

Rationale: `activate()` / `maybe_upgrade()` run inside a WP request. An unbounded `while (true)` over every unbound row would blow `max_execution_time` on a labelled library. 500 binds (≈ 2k queries) stays inside a 30s budget. Remainder: `acx_label_heal_complete` stays unset; next load resumes. CLI `wp acx bind-unbound-labels` still constructs the service with no cap.

## Tenant

Single-tenant, already baked in. `heal_unbound_human_labels()` uses `TenantIdentity::resolve()['value']` (`class-life-cycle-manager.php:198`). There is no tenant loop anywhere in this file. Unresolved tenant sets `acx_label_heal_blocked_reason=tenant_unresolved` and the admin notice names `wp acx bind-unbound-labels`.

## file:line (re-derived after the code commit)

| Claim | `sed -n` |
| --- | --- |
| Activate heal | `class-life-cycle-manager.php:107` `$this->maybe_heal_unbound_human_labels();` |
| Upgrade heal (schema-fail path + success path) | `:150`, `:157` |
| Schema apply still refuses to stamp `acx_version` | `:143-151` |
| Batch cap | `:44` `MAX_HEAL_BATCHES_PER_LOAD = 5` |
| Single-tenant resolve | `:198` `TenantIdentity::resolve()['value']` |
| Cap / stall do not stamp heal-complete | `:207-224` early `return`; stamp only at `:226` |
| Service constructed with the cap | `:239` `new PersonLabelBackfillService( self::MAX_HEAL_BATCHES_PER_LOAD )` |
| Admin notice | `:86` `admin_notices` → `:160-174` |
| Uninstall clears heal options | `:561-563` |
| Shared predicate | `trait-detects-system-defined-labels.php:32` |
| Label CASE still nulls unbound humans (heal is the fix) | `:41` |
| `label_state` SQL | `:48-54` `'person'` / `'unlabeled'` / `'unbound'` |
| Members SELECT | `class-identity-members-read-repository.php:57`, `:75`, `:136`, `:217` |
| Backfill cap loop | `class-person-label-backfill-service.php:41-44`, `:80-84`, `:149` `'capped'` |

## What changed

- `PersonLabelBackfillService` accepts a constructor batch cap; upgrade passes `5`; CLI stays uncapped.
- Heal does not stamp `acx_label_heal_complete` when `capped` or `stalled`.
- Trait adds `projected_cluster_label_state_sql` + `resolve_cluster_label_state`.
- Four identity-members reads select `cluster_label` and `label_state` from one helper.

## Commits (subjects)

- `fix(support): UXW2-4-R1-03 bound upgrade heal and label_state`
- this report commit

## Undone

- **Contract.** `docs/workbay/contracts/clustering-api.md` (not owned) needs a cluster/member payload bullet: `label_state` is `person` when a bound person name is present; `unlabeled` when the cluster label is empty/null or reserved (`/^cluster[-_]/i`); `unbound` when a human label exists but no person is bound. FE must render **Unlabeled identity** for `unlabeled` and must not synthesize `cluster-<hex>` from a null label. `unbound` is the pre-heal upgrade state and becomes `person` after backfill.
- **Sibling surfaces.** `class-clusters-read-repository.php` should SELECT the same `label_state`. `class-cluster-response-mapper.php` / `class-member-response-mapper.php` must copy the field onto the REST payload (they currently drop extra SQL columns). `js/` `formatClusterLabel` must consume `label_state` so null no longer becomes `cluster-<hex>`.
- **FE tests.** `npx vitest run` skipped — this lane did not touch `js/` or `docs/ux-maps/`.
- **Handoff.** Isolated lane clone has no `workbay_handoff_mcp`; integrator records the decision after transplant.
