# UXW2-2 post-merge integration repair

Gate is GREEN. No findings left unfixed.

Chose **production backfill** of `label_state` on the plugin-owned top-unlabeled proxy envelope (not a fixture-only patch). Local mapping already emits the key; `repair_pending` already gets the same guarantee; the schema requires both.

## P1. `ClusterReadServiceTest::testListTopUnlabeledBackendProxyOmittingRepairPendingValidatesAgainstSchema`

**Root cause.** Main made per-cluster `label_state` required. The UXW2-2 proxy mock omits it. `list_top_unlabeled_clusters` already backfills `repair_pending` but did not walk clusters.

**Fix.** `ClusterResponseMapper::ensure_emitted_label_state()` reuses `resolve_emitted_label_state()`. `ClusterResponseEnvelopeService::normalize_top_unlabeled_response()` applies it to kept rows. Null `label` → `unlabeled`. Test now asserts that value.

**Can-it-fail.** Replaced the keep line with `$kept[] = $cluster;` (skip backfill). RED: `Failed asserting that null is identical to 'unlabeled'.` Restored; GREEN.

## P2. `ClusterTopUnlabeledSchemaConsistencyTest::testProxySuccessGoldenValidatesAgainstSchema`

**Root cause.** Fixture `list_top_unlabeled_proxy_success/response.json` was recorded before `label_state` was required.

**Fix.** Production backfill (P1) plus `UPDATE_CLUSTERS_READ_FIXTURES=1 ./vendor/bin/phpunit --filter ClustersControllerCharacterizationTest`. Recorder added `"label_state":"unlabeled"`. Not hand-edited.

**Can-it-fail.** Same schema path as the original RED (`$.clusters[0] required label_state`). P1 mutant also fails schema validation if the new unlabeled assertion is removed.

## P3. `testProxyCanonicalEnvelopeGoldenValidatesAgainstSchema`

**Root cause.** Same as P2 for `list_top_unlabeled_proxy_canonical_envelope/response.json`.

**Fix.** Same recorder run. Fixture now carries `label_state: unlabeled`.

**Can-it-fail.** Same required-key failure as P2 when the key is absent.

## P4. `ClustersReadRepositoryTest::testListTopUnlabeledExcludesMemberlessClusterWhenSeeded`

**Root cause.** `expectedTopUnlabeledWhereClause()` still used `c.label LIKE 'cluster-%%'` (law B is main’s case-insensitive two-pattern form).

**Fix.** Literal updated to `(LOWER(c.label) LIKE 'cluster-%%' OR LOWER(c.label) LIKE 'cluster\_%%')`. Not a call into the trait.

**Can-it-fail.** Mutated `reserved_label_sql_predicate()` to `$column . " LIKE 'cluster-%%'"`. RED: expected LOWER two-pattern, actual old LIKE. Restored; GREEN.

## P5. `PersonCrudTest` `c.identity_count >= 2`

**Root cause.** Assertion pinned the projected column. Law A uses the observed-member subquery `) >= 2`.

**Fix.** Assert `FROM \`wp_acx_identity_members\` m`, `m.cluster_uuid = c.cluster_uuid`, `) >= 2`, and **not** `c.identity_count >= 2`.

**Can-it-fail.** Replaced the list_top_unlabeled bound with `AND c.identity_count >= 2`. RED: SQL does not contain `) >= 2`. Restored; GREEN.

## P6. `PersonCrudTest` `c.identity_count <= 1`

**Root cause.** Same projected-column pin on `count_top_unlabeled_singletons`.

**Fix.** Same subquery pins with `) <= 1` and **not** `c.identity_count <= 1`.

**Can-it-fail.** Replaced singleton bound with `AND c.identity_count <= 1`. RED: SQL does not contain `FROM \`wp_acx_identity_members\` m`. Restored; GREEN.

## P7. `Uxw2ReportShaLintTest::testEveryFortyHexTokenInUxw2ReportsResolvesToACommit`

**Root cause.** `docs/tasks/uxw2/UXW2-4-fix-r8e-report.md` cited `d9d20ce2da7908d3c72e73ec8e953479fb9d4ae2` (lines 11 and 120) plus five other lane-local SHAs. None resolve in this tree (`git cat-file -e` fails). Did **not** use `sha-lint:allow`.

**Fix.** Cite commit subjects only. Line 11 now names `test(php): UXW2-4-R8-03 cluster schema label_state enum`. The Commits list dropped all 40-hex tokens (otherwise the next SHA after d9d20ce2 would fail the same lint).

**Can-it-fail.** Re-inserted `d9d20ce2…` on line 11. RED: `UXW2-4-fix-r8e-report.md cites unresolved commit d9d20ce2…`. Restored; GREEN.

## T1. `deep link rq=merge.all.1 survives Prev …`

**Root cause.** Position chrome is no longer `"2 of 2"`. Merged `ReviewQueue` renders `"%1$d of %2$d shown"` when a kind/band filter is active.

**Fix.** Query `'2 of 2 shown'`. Counter is present; wording changed. Did not restore the deleted ScanTabContent `<h3 id="acx-workbench-queue-heading">`.

**Can-it-fail.** Mutated filtered copy to `'%1$d of %2$d'`. RED: unable to find `2 of 2 shown`. Restored; GREEN.

## T2. `Strong chip from rq=assignment.all.1 …`

**Root cause.** Same as T1 (`rq=assignment.all.1` ⇒ filters active).

**Fix.** `'2 of 2 shown'`.

**Can-it-fail.** Shares T1’s production copy; T1 mutant is the proof.

## T3. `deep link rq=assignment.strong.1 Prev …`

**Root cause.** Same as T1 (kind + band filters).

**Fix.** `'2 of 2 shown'`.

**Can-it-fail.** Shares T1’s production copy.

## T4. `oversized rq index clamps …`

**Root cause.** URL clamp to `rq=assignment.all.1` worked; assertion still expected `"2 of 2"`.

**Fix.** `'2 of 2 shown'`.

**Can-it-fail.** Shares T1’s production copy.

## T5. `kind chip on ScanTabContent dispatch writes rq=assignment.all.0 …`

**Root cause.** Unfiltered start is `"3 of 3 on this page"`; after Close matches, `"1 of 3 shown"`.

**Fix.** Updated both queries. Heading stays in `ReviewQueue` (`Review Suggestions`). `useOpenReviewTargetLifecycle` mock keeps `reviewClusterId: null` so `ClusterReviewPanel`’s `Review these faces` h2 does not duplicate the id.

**Can-it-fail.** Shares T1’s filtered copy (`shown`) and the unfiltered `"on this page"` string. Mutating the unfiltered sprintf in `ReviewQueue.tsx` would miss `3 of 3 on this page`.

## T6. `two synchronous Next clicks advance index by 2`

**Root cause.** Unfiltered queue now says `"1 of 3 on this page"` / `"3 of 3 on this page"`.

**Fix.** Updated both queries.

**Can-it-fail.** Same unfiltered production string as T5.

## T7. `header count decrements after a label commit remount …`

**Root cause.** Merge added file-level `vi.mock('../ClusterLabelingPanel')` (stub `<div data-testid="label-panel" />`). ScanTabContent imports the barrel, so the mock did not isolate ScanTabContent; it only replaced the **direct** import this test renders. Combobox `Name` never mounted.

**Fix.** Removed the direct-module stubs for `ClusterLabelingPanel`, `WorkbenchFindingsPanel`, and `ClusterReviewPanel`. Kept `useOpenReviewTargetLifecycle` → `reviewClusterId: null` (prevents duplicate `#acx-workbench-queue-heading`).

**Can-it-fail.** Mutated `ariaLabel={__('Name')}` to `'Person'`. RED: unable to find role=combobox name `Name`. Restored; GREEN.

## T8. `R1-22: queue header and findings unlabeled count agree after a drop`

**Root cause.** Same over-broad `vi.mock('../WorkbenchFindingsPanel')`. Test renders the real panel; mock hid `"2 unlabeled groups"`.

**Fix.** Removed the findings-panel stub (T7). Production copy unchanged.

**Can-it-fail.** Mutated `_n('%d unlabeled group', '%d unlabeled groups', …)` to `cluster(s)`. RED: unable to find `2 unlabeled groups`. Restored; GREEN.

## T9. `R5-09: findings Resync and queue Resync have distinct accessible names`

**Root cause.** Stubbed findings panel has no `Resync findings` button.

**Fix.** Real panel (T7). `aria-label="Resync findings"` vs queue `Resync review queue` unchanged.

**Can-it-fail.** Mutated findings `aria-label` to `'Resync'`. RED: unable to find `/^Resync findings$/`. Restored; GREEN.

## T10. `R8-01: zero-evidence-only page panel and queue announce the same non-elsewhere claim`

**Root cause.** Stubbed findings panel never mounts `#acx-findings-panel-repair-copy`. Queue already announced `'3 groups missing face data'`.

**Fix.** Real panel (T7). Copy still from `gatedClusterCopy`.

**Can-it-fail.** Mutated `_n('%d group missing face data', …)` to `missing faces`. RED: `toHaveTextContent('3 groups missing face data')` failed. Restored; GREEN.

## Also committed

Three pre-existing regenerated goldens (law D), as recorded — not hand-edited:

- `get_cluster_detail_local_projection` (`identity_count` 2 → 1)
- `list_top_unlabeled_local_projection` (two representatives, `repair_pending: false`)
- `list_top_unlabeled_targeted_repair` (empty clusters, `repair_pending: true`)

Added PHP pins (counts went **up**, not down):

- `testNormalizeTopUnlabeledResponseBackfillsOmittedLabelState`
- `testNormalizeTopUnlabeledResponsePreservesUpstreamLabelState`
- `testEnsureEmittedLabelStateBackfillsUnlabeledWhenOmitted`

## Final gate

All four commands from `apps/prototype-wp-alt-context` (and contracts from repo root via `../../scripts/…`):

| Command | Summary | Exit |
| --- | --- | --- |
| `./vendor/bin/phpunit` | `OK (1939 tests, 9534 assertions)` | 0 |
| `./node_modules/.bin/vitest run` | `Test Files  219 passed (219)` / `Tests  2460 passed (2460)` | 0 |
| `npm run typecheck` | `tsc --noEmit --project tsconfig.type-check.json` (no errors) | 0 |
| `python3 ../../scripts/check_shared_contract_fixtures.py` | `Validated 4 shared contract fixture(s).` | 0 |

Baseline was 1936 tests / 9522 assertions (PHP) and 2460 tests / 219 files (vitest). PHP **+3 tests / +12 assertions** from the new pins. Vitest count unchanged.

`fatal: Not a valid object name 0000000000000000000000000000000000000000^{commit}` during PHPUnit is the sha-lint allow-marker fixture proving that token is unresolvable — not a failure. <!-- sha-lint:allow -->
