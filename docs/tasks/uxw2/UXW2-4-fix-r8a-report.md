# UXW2-4-R6-01 — tenant-scope persons unique name (r8a)

## Result

`acx_persons` uniqueness is `UNIQUE KEY idx_tenant_normalized_name (tenant_id, normalized_name)`. `create_person` existence lookup is tenant-scoped. Two tenants can both hold "Jane Doe"; a second create in the same tenant still 409s. Existing installs DROP the old global `idx_normalized_name` on upgrade (dbDelta never drops/alters same-name indexes).

This tree already had r6's composite columns under the old name `idx_normalized_name`. dbDelta does not rewrite an existing unique key's columns when the name stays the same, so that shape never applied on an existing install. r8a renames the key so dbDelta ADDs the composite unique, and explicitly DROPs `idx_normalized_name`.

`ACX_VERSION` was **not** bumped. Fingerprint gating on `build_projection_schema_statements` re-runs dbDelta; the DROP is the extra path dbDelta cannot do. Verified: `maybe_upgrade` stamps only when version **or** fingerprint mismatches; `testMaybeUpgradeDropsLegacyGlobalNormalizedNameUniqueIndex` **1 / 1**.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Closure

| Clause | Commit subject | Test | Mutant RED (verbatim) | GREEN |
| --- | --- | --- | --- | --- |
| (1) DDL composite unique | `fix(php): UXW2-4-R6-01 tenant-scope persons unique name` | `PersonTenantScopedUniquenessTest::testCreatePersonAllowsSameNormalizedNameAcrossTenantsAndDedupesWithinTenant` | **M1** revert DDL to `UNIQUE KEY idx_normalized_name (normalized_name)`: `UNIQUE(normalized_name) alone would reject tenant B Jane Doe after tenant A created it` / `Failed asserting that 'CREATE TABLE wp_acx_persons (… UNIQUE KEY idx_normalized_name (normalized_name), …)' matches PCRE pattern "/UNIQUE\s+KEY\s+idx_tenant_normalized_name\s*\(\s*tenant_id\s*,\s*normalized_name\s*\)/i".` (`FAILURES! Tests: 1, Assertions: 15, Failures: 1.` **1 / 1**) | `OK (1 test, 15 assertions)` **1 / 1** |
| (2) `create_person` tenant-scoped precheck | same (already on tree; re-verified, no `class-api.php` edit) | same | **M2** revert precheck to `WHERE normalized_name = %s`: `tenant B creating Jane Doe must not 409 against tenant A (cross-tenant existence oracle)` / `Failed asserting that an object is an instance of class WP_REST_Response.` (`FAILURES! Tests: 1, Assertions: 5, Failures: 1.` **1 / 1**) | `OK (1 test, 15 assertions)` **1 / 1** |
| (3) Parity pin | same commit as DDL | `testPersonsDdlHasUniqueIndexOnNormalizedName` | **M3** revert expectation to `['normalized_name']`: `UNIQUE KEY idx_tenant_normalized_name must be composite (tenant_id, normalized_name)` / `Failed asserting that two arrays are identical.` expected `['normalized_name']` actual `['tenant_id', 'normalized_name']` (`FAILURES! Tests: 1, Assertions: 9, Failures: 1.` **1 / 1**) | `OK (1 test, 9 assertions)` **1 / 1** |

Each mutant restored after the RED. Production `git diff` after restore was the intended change only.

Unmutated filter counts (non-zero, so a zero-selected run cannot read as green): two-tenant **1 / 1**; parity **1 / 1**.

wpdb stub does not enforce UNIQUE keys. M1 is killed by the composite-key regex in the new two-tenant test, not by a stub duplicate-key on insert.

## Gate

`cd apps/prototype-wp-alt-context && composer test`:

```
OK (1849 tests, 8956 assertions)
```

Baseline on this tree before the first code commit: `OK (1847 tests, 8933 assertions)`. +2 tests, +23 assertions.

`npx vitest run` skipped — FE untouched. See `## Undone`.

Targeted filters (selected/total):

| Filter | Result |
| --- | --- |
| `PersonTenantScopedUniquenessTest::testCreatePersonAllowsSameNormalizedNameAcrossTenantsAndDedupesWithinTenant` | **1 / 1** `OK (1 test, 15 assertions)` |
| `testPersonsDdlHasUniqueIndexOnNormalizedName` | **1 / 1** `OK (1 test, 9 assertions)` |
| `PersonTenantScopedUniquenessTest::testMaybeUpgradeDropsLegacyGlobalNormalizedNameUniqueIndex` | **1 / 1** `OK (1 test, 5 assertions)` |
| `PersonDedupeSchemaParityTest` | **4 / 4** `OK (4 tests, 37 assertions)` |
| `SchemaVerificationTest` | **24 / 24** `OK (24 tests, 237 assertions)` |

## file:line (re-derived with `sed -n '<N>p' <file>` after last code commit)

| Claim | `sed -n` |
| --- | --- |
| Composite unique, new name | `class-life-cycle-manager.php:665` `UNIQUE KEY idx_tenant_normalized_name (tenant_id, normalized_name)` |
| Shape match | `class-life-cycle-manager.php:895` `UNIQUE KEY uq_projection_conflict (tenant_id, entity_type, entity_key, conflict_code, backend_version)` |
| Legacy unique drop list | `:85-88` `idx_name`, `idx_normalized_name` |
| Fingerprint re-runs dbDelta | `:133-135` any `build_projection_schema_statements` change hashes; `:140-148` version **or** fingerprint mismatch → apply |
| Fingerprint source | `:919-920` sha1 of normalised projection DDL |
| Drop after dbDelta | `:991` `drop_legacy_persons_unique_indexes`; `:1155-1162` loop |
| Tenant before lookup | `class-api.php:592-594` resolve; empty tenant → 500 |
| Scoped create probe | `:599-606` `WHERE normalized_name = %s AND tenant_id = %s` then `acx_person_exists` 409 |
| Scoped update probe | `:710` `AND id != %d AND tenant_id = %s` |
| Scoped resolve-or-create | `class-person-resolution-service.php:303` `AND tenant_id = %s` (not edited) |
| Parity stronger pin | `PersonDedupeSchemaParityTest.php:40-48` `idx_tenant_normalized_name` → `['tenant_id', 'normalized_name']`; old name absent |
| Two-tenant behaviour | `PersonTenantScopedUniquenessTest.php:57` B must not 409; `:81-84` composite UNIQUE regex |

## TEST-15 restores

| Mutant | Restore |
| --- | --- |
| M1 global unique DDL | intended `idx_tenant_normalized_name (tenant_id, normalized_name)` remains |
| M2 unscoped `WHERE normalized_name = %s` | intended `AND tenant_id = %s` remains |
| M3 parity `['normalized_name']` | intended `['tenant_id', 'normalized_name']` remains |

## Undone

- FE untouched; `npx vitest run` not run. UX maps not in ownership; no user-facing surface in this lane.
- `class-api.php` production body not edited this round — create probe was already tenant-scoped on this tree. M2 still kills the unscoped revert.
- `PersonCrudTest.php` one-line regex pin updated so the r6 two-tenant test matches the required index name. Outside the ownership list; without it `composer test` fails on the rename. No other `PersonCrudTest` edits.
- `import_legacy_roster_entry` / `import_legacy_roster_assignment` still SELECT by `normalized_name` only and INSERT without `tenant_id`. Same file, different path. Not one of the three required halves.
- wpdb stub still does not enforce UNIQUE. Enforcing unique keys in the stub is outside Ownership.
- `ACX_VERSION` not bumped (fingerprint + explicit DROP is the existing mechanism).
- `workbay_handoff_mcp` is not importable in this overlay (`make context` has no target). Decision recorded in this report only.

## Commits (subjects)

- `fix(php): UXW2-4-R6-01 tenant-scope persons unique name`
- this report commit
