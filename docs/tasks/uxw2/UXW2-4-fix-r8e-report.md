# UXW2-4 r8e — tenant/label_state residues

## Result

All three findings closed.

- **R8-01.** Legacy roster import resolves tenant once (`TenantIdentity::resolve()`, same as `Api::create_person`), scopes both existence SELECTs, writes `tenant_id` on both person INSERTs, and fail-closes with `acx_legacy_roster_tenant_unresolved` when tenant is empty. Never writes `''`.
- **R8-02.** `resolve_emitted_label_state` lives on `MapsResponseFields`. `MemberResponseMapper` copies `label_state` onto member and media-identities rows. Known-gap sentence in `clustering-api.md` deleted.
- **R8-03.** Cluster list, top-unlabeled, and members schemas require `label_state` with `enum: ["person", "unlabeled", "unbound"]`. Shared-contract goldens updated. `python3 scripts/check_shared_contract_fixtures.py` validates 4 fixtures.

`file:line` cites re-derived with `sed -n '<N>p' <file>` after last code commit subject `test(php): UXW2-4-R8-03 cluster schema label_state enum` (lane-local SHA was unresolvable in the merged tree).

## Closure

| Finding | Commit subject | Test | Verbatim mutant RED | GREEN |
| --- | --- | --- | --- | --- |
| R8-01 tenant INSERT | `fix(php): UXW2-4-R8-01 tenant-scope legacy roster import` | `LegacyRosterImportTenantScopeTest::testImportLegacyRosterCreatesDistinctPersonsPerTenant` | **M1** see below | **1 / 1** `OK (1 test, 8 assertions)` |
| R8-01 scoped SELECT | same | same | **M2** see below | **1 / 1** |
| R8-01 fail-closed | same | `LegacyRosterImportTenantScopeTest::testImportLegacyRosterFailsClosedWhenTenantUnresolved` | no required mutant | **1 / 1** `OK (1 test, 6 assertions)` |
| R8-02 member emit | `fix(php): UXW2-4-R8-02 emit member label_state` | `MemberResponseMapperTest::testMapClusterMembersAndMediaIdentitiesEmitLabelState` | **M3** see below | **1 / 1** `OK (1 test, 6 assertions)` |
| R8-03 schema enum | `docs(contracts): UXW2-4-R8-03 add label_state to cluster schemas` | `ClusterLabelStateSchemaTest::testClusterListAndTopUnlabeledSchemasRequireLabelStateEnumAndGoldensValidate` | **M4** see below | **1 / 1** `OK (1 test, 33 assertions)` |

Each mutant restored after RED. Production tree after restore matched the intended change.

## Tests

| Finding | File | Method |
| --- | --- | --- |
| R8-01 two-tenant | `apps/prototype-wp-alt-context/tests/Unit/LegacyRosterImportTenantScopeTest.php` | `testImportLegacyRosterCreatesDistinctPersonsPerTenant` |
| R8-01 fail-closed | same | `testImportLegacyRosterFailsClosedWhenTenantUnresolved` |
| R8-02 | `apps/prototype-wp-alt-context/tests/Unit/MemberResponseMapperTest.php` | `testMapClusterMembersAndMediaIdentitiesEmitLabelState` |
| R8-03 | `apps/prototype-wp-alt-context/tests/Unit/ClusterLabelStateSchemaTest.php` | `testClusterListAndTopUnlabeledSchemasRequireLabelStateEnumAndGoldensValidate` |

Pre-fix RED (combined filter, **4 / 4**): all four failed. Verbatim first failures:

1. `tenant B import must insert a distinct Jane Doe` / `Failed asserting that actual size 1 matches expected size 2.`
2. `Failed asserting that null is an instance of class WP_Error.`
3. `Failed asserting that an array has the key 'label_state'.`
4. `schemas/recognition-cluster-list-response.schema.json must require label_state`

## TEST-15 mutants

**M1** drop `tenant_id` from `import_legacy_roster_entry` INSERT. Filter **1 / 1**.

```
imported person must not have empty tenant_id
Failed asserting that two strings are not identical.
```

**M2** remove `AND tenant_id = %s` from `import_legacy_roster_entry` existence SELECT. Filter **1 / 1**. First assertion (cross-tenant remap; id_map assert not reached):

```
tenant B import must insert a distinct Jane Doe
Failed asserting that actual size 1 matches expected size 2.
```

**M3** drop `label_state` from the member emit array. Filter **1 / 1**.

```
Failed asserting that an array has the key 'label_state'.
```

**M4** change list schema enum to `["person", "unlabeled"]`. Filter **1 / 1**.

```
schemas/recognition-cluster-list-response.schema.json label_state enum must be person|unlabeled|unbound
Failed asserting that two arrays are identical.
--- Expected
+++ Actual
@@ @@
 Array &0 [
     0 => 'person',
     1 => 'unlabeled',
-    2 => 'unbound',
 ]
```

## Gate

Baseline (before first code commit): `OK (1853 tests, 9017 assertions)`

Final: `OK (1857 tests, 9070 assertions)`

Delta: **+4 tests, +53 assertions**.

`npx vitest run` skipped — FE untouched.

`python3 scripts/check_shared_contract_fixtures.py`: `Validated 4 shared contract fixture(s).`

`UPDATE_CLUSTERS_READ_FIXTURES=1` regenerated `tests/fixtures/clusters-read/get_cluster_members_local_projection/response.json` only. The six cluster-list/detail/top-unlabeled goldens already carried `label_state`.

## Files + line ranges (post last code commit)

| Surface | `sed -n` |
| --- | --- |
| Tenant resolver (same as `class-api.php:592`) | `class-life-cycle-manager.php:253-259` |
| Fail-closed import | `:278-285` `acx_legacy_roster_tenant_unresolved` |
| Entry SELECT scoped | `:373` `AND tenant_id = %s` |
| Entry INSERT `tenant_id` | `:391` |
| Assignment SELECT (legacy name) | `:428` |
| Assignment SELECT (new name) | `:441` |
| Assignment INSERT `tenant_id` | `:456` |
| Persons DDL | `:697` `tenant_id varchar(64) NOT NULL`; `:707` composite unique |
| Shared resolver | `trait-maps-response-fields.php:365` `resolve_emitted_label_state` |
| Member emit | `class-member-response-mapper.php:100` |
| Proxy authority copy | `:44` |
| Cluster list/detail still emit | `class-cluster-response-mapper.php:110`, `:158` |
| Contract gap sentence gone | `clustering-api.md:449` now names both mappers |
| List schema required + enum | `recognition-cluster-list-response.schema.json:17`, `:35` |
| Top-unlabeled schema | `recognition-cluster-top-unlabeled-response.schema.json:18`, `:37` |
| Members schema (rg-005, field now ships) | `recognition-cluster-members-response.schema.json:25`, `:89` |

## Commits

Lane-local SHAs from that lane clone are unresolvable on the merged tree; cite subjects only.

- `fix(php): UXW2-4-R8-01 tenant-scope legacy roster import`
- `test(php): UXW2-4-R8-01 tenant-scope legacy roster import`
- `fix(php): UXW2-4-R8-02 emit member label_state`
- `test(php): UXW2-4-R8-02 emit member label_state`
- `docs(contracts): UXW2-4-R8-03 add label_state to cluster schemas`
- `test(php): UXW2-4-R8-03 cluster schema label_state enum`

## Undone

- FE untouched; `npx vitest run` not run. UX maps not in ownership; no user-facing FE surface in this lane.
- `check_shared_contract_fixtures.py` still does not validate `enum`. PHP test 4 does. Not owned.
- Legacy assignment `UPDATE wp_acx_clusters` is still keyed only by `cluster_uuid` (persons path was the finding). Not one of the three required residues.
- `workbay_handoff_mcp` is not importable in this lane clone; no handoff write. Integrator records HEAD.
