# UXW2-4-R6-01 — tenant-scope persons unique name

## Result

`acx_persons` uniqueness is now `(tenant_id, normalized_name)`. `create_person` existence lookup is tenant-scoped. Two tenants can both hold "Jane Doe"; a second create in the same tenant still 409s.

Updating `testPersonsDdlHasUniqueIndexOnNormalizedName` is not weakening an assertion. The old pin was `['normalized_name']` only — that **encoded the defect** (a global unique that permanently grants the first tenant the name). The new pin is strictly stronger: `['tenant_id', 'normalized_name']`.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Gate

`cd apps/prototype-wp-alt-context && composer test`:

```
OK (1834 tests, 8814 assertions)
```

R5 baseline on this tree was `OK (1833 tests, 8799 assertions)`. +1 test, +15 assertions.

## RED (before the fix)

Filter `testCreatePersonAllowsSameNormalizedNameAcrossTenantsAndDedupesWithinTenant|testPersonsDdlHasUniqueIndexOnNormalizedName` → **2 / 2**.

| Test | Failure |
| --- | --- |
| `testCreatePersonAllowsSameNormalizedNameAcrossTenantsAndDedupesWithinTenant` | `tenant B creating Jane Doe must not 409 against tenant A (cross-tenant existence oracle)` / `Failed asserting that an object is an instance of class WP_REST_Response.` |
| `testPersonsDdlHasUniqueIndexOnNormalizedName` | `UNIQUE KEY idx_normalized_name must be composite (tenant_id, normalized_name)` / expected `['tenant_id', 'normalized_name']`, actual `['normalized_name']` |

## TEST-15

Filter `testCreatePersonAllowsSameNormalizedNameAcrossTenantsAndDedupesWithinTenant` → **1 / 1** on each mutant.

| Mutant | Result |
| --- | --- |
| **A** revert DDL to `UNIQUE KEY idx_normalized_name (normalized_name)` | RED: `UNIQUE(normalized_name) alone would reject tenant B Jane Doe after tenant A created it` / PCRE failed on `(normalized_name)` vs `(tenant_id, normalized_name)` |
| **A restore** | `git diff` on production files: only the intended composite UNIQUE remains |
| **B** revert `create_person` lookup to `WHERE normalized_name = %s` (DDL left fixed) | RED: `tenant B creating Jane Doe must not 409 against tenant A (cross-tenant existence oracle)` / `Failed asserting that an object is an instance of class WP_REST_Response.` (409 / `acx_person_exists` path) |
| **B restore** | `git diff` on production files: only the intended scoped lookup remains |

Mutant A cannot turn the 201 assertion red here: the wpdb stub does not enforce UNIQUE keys (that stub is outside Ownership). The same behavioral test therefore pins the composite UNIQUE from `build_projection_schema_statements` after the three create cases. Mutant B is killed by the controller 409, not by a SQL-string assert.

## GREEN

Same filter after implement: `OK (2 tests, 23 assertions)`.
`PersonCrudTest` + `PersonDedupeSchemaParityTest`: `OK (19 tests, 168 assertions)`.

## What changed

- DDL in place (greenfield, no migration): `UNIQUE KEY idx_normalized_name (tenant_id, normalized_name)` — same tenant-first composite shape as `uq_projection_conflict`.
- `create_person` resolves tenant **before** the existence probe and scopes `WHERE normalized_name = %s AND tenant_id = %s`, matching `update_person` and `PersonResolutionService::find_by_normalized_name`.
- 409 body / status unchanged. No contract edit.

## file:line (re-derived after the code commit)

| Claim | `sed -n` |
| --- | --- |
| Composite unique | `class-life-cycle-manager.php:637` `UNIQUE KEY idx_normalized_name (tenant_id, normalized_name)` |
| Shape match | `class-life-cycle-manager.php:867` `UNIQUE KEY uq_projection_conflict (tenant_id, …)` |
| Tenant before lookup | `class-api.php:592-595` resolve; empty tenant → 500 |
| Scoped create probe | `class-api.php:597-606` `WHERE normalized_name = %s AND tenant_id = %s` then `acx_person_exists` 409 |
| Scoped update probe | `class-api.php:708-710` `AND id != %d AND tenant_id = %s` |
| Scoped resolve-or-create | `class-person-resolution-service.php:293` `AND tenant_id = %s` |
| Parity stronger pin | `PersonDedupeSchemaParityTest.php:44-47` `['tenant_id', 'normalized_name']` |
| Two-tenant behaviour | `PersonCrudTest.php:127` three cases: A 201, B 201 distinct id, B-again 409 |

## Other `normalized_name` lookups

| Site | Scoped? |
| --- | --- |
| `class-api.php:599` `create_person` | **yes** (this fix) |
| `class-api.php:710` `update_person` | yes |
| `class-person-resolution-service.php:293` `find_by_normalized_name` | yes |
| `class-life-cycle-manager.php:318` `import_legacy_roster_entry` | **no** |
| `class-life-cycle-manager.php:368` `import_legacy_roster_assignment` (legacy name) | **no** |
| `class-life-cycle-manager.php:379` `import_legacy_roster_assignment` (new name) | **no** |

No fourth unscoped SQL lookup exists outside Ownership. PHP grouping in `RosterEntryProjectionRepository` is not a SQL lookup.

## Canon (grepped)

| ID | File | How |
| --- | --- | --- |
| WEB-08 | `security.md:110` | tenant on the create existence query, not just the route |
| WEB-28 | `security.md:130` | unscoped 409 was a cross-tenant existence oracle |
| PG-02 | `security.md:223` | isolation must not live only in some handlers' WHERE |
| ARCH-13 | `engineering.md:563` | unique key makes same-name-across-tenants representable; global unique made it unrepresentable |
| DATA-18 | `engineering.md:206` | keep a UNIQUE constraint; do not "fix" by deleting it |
| TEST-15 | `engineering.md:396` | mutants A/B seen red |

## Decisions

1. **Index name kept `idx_normalized_name`.** Column list changed; SchemaVerificationTest keys on the name via stub-injected `tableIndexes`.
2. **Tenant resolve hoisted above the probe.** Missing tenant is 500 before any name lookup, so a missing identity cannot 409 against another tenant's row.
3. **Legacy import lookups left unscoped.** Different path (activation migration); inserts there also omit `tenant_id`. One user-visible path per commit.

## Undone

- `import_legacy_roster_entry` / `import_legacy_roster_assignment` still SELECT by `normalized_name` only (`class-life-cycle-manager.php:318`, `:368`, `:379`) and INSERT without `tenant_id`. Same file, different path (legacy option → table). Not one of the three required halves; not fixed.
- `RosterEntryProjectionRepository::list_entries` (`class-roster-entry-projection-repository.php:37`) is `SELECT * FROM persons` with no `tenant_id`. Not a `normalized_name` lookup; outside Ownership.
- wpdb stub still does not enforce UNIQUE. Mutant A is killed by the composite-key regex in `PersonCrudTest.php:178-181`, not by a stub duplicate-key on insert. Enforcing unique keys in the stub is outside Ownership.

## Commits (subjects)

- `fix(api): UXW2-4-R6-01 tenant-scope persons unique name`
- this report commit
