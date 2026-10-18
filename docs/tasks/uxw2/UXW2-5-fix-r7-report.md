# UXW2-5 fix lane r7 report

Kill the dead `is_proxy_endpoint_error` widening lever. Mark the r4 quoted mutant payload so a sibling SHA lint cannot fail a merge it was never meant to reject. PHP + docs. TDD.

Final HEAD: code commit `df9cd0913229` on `feature/uxw2-5` (transplanted by the integrator).

## GREEN (this checkout)

- PHP `composer test`: `OK (1786 tests, 8682 assertions)`. Exit 0.
- Targeted `--filter testIsProxyEndpointErrorPinsFiveHundredBoundary`: `OK (1 test, 4 assertions)`. Filter selected 1/1 (not zero).
- `git grep -n min_status -- apps/prototype-wp-alt-context` is empty.

## Closure

| ID | commit subject | test | mutant RED line | GREEN |
|---|---|---|---|---|
| R7-01 | `fix(api): UXW2-5-R7-01 drop dead min_status widening lever` | `testIsProxyEndpointErrorPinsFiveHundredBoundary` | Mutant `>= 400`: `status 499 must not be classified as endpoint error` / `Failed asserting that true is false.` Suite under mutant: `FAILURES! Tests: 1, Assertions: 3, Failures: 1.` TDD first RED (parameter still present): `is_proxy_endpoint_error must not expose a $min_status widening lever` / `Failed asserting that 2 is identical to 1.` `FAILURES! Tests: 1, Assertions: 1, Failures: 1.` | `OK (1 test, 4 assertions)` |
| R9-01 | `docs(uxw2): UXW2-2-R9-01 mark quoted mutant payload` | n/a — lint lives on the sibling branch; no test added here | n/a | `sed -n '22p'` holds both the quoted forty-zero token and `sha-lint:allow` |

Subjects above each match exactly one commit via `git log --format=%H --fixed-strings --grep="<subject>"` (hashes not copied here).

## Item 1 — UXW2-5-R7-01

Deleted `$min_status`. Inlined `>= 500`. Surviving ENDPOINT_ERROR-not-UNAVAILABLE docblock left intact.

TDD first RED (test committed before the production delete):

```
is_proxy_endpoint_error must not expose a $min_status widening lever
Failed asserting that 2 is identical to 1.
```

`FAILURES! Tests: 1, Assertions: 1, Failures: 1.`

TEST-15 mutant: production `>= 500` → `>= 400`. Same filter, 1/1. RED:

```
status 499 must not be classified as endpoint error
Failed asserting that true is false.
```

`FAILURES! Tests: 1, Assertions: 3, Failures: 1.` Restore: production diff is only the intended delete (`>= 500`, no parameter). Mutant not left in the tree.

`git grep -n min_status -- apps/prototype-wp-alt-context` is empty.

## Item 2 — UXW2-2-R9-01

Quoted mutant payload (not a commit citation). `sed -n '22p' docs/tasks/uxw2/UXW2-5-fix-r4-report.md`:

```
| R4-01 | `fix(docs): UXW2-5-R4-01 strip dead SHAs from r3 report` | gate loop + `grep -cE '\b[0-9a-f]{40}\b'` | `DEAD 0000000000000000000000000000000000000000` | loop silent; `grep -c` = `0` | <!-- sha-lint:allow verbatim mutant payload, not a commit citation -->
```

That line is the one permitted 40-hex token in this report. Payload unchanged. Table not reflowed. Other rows untouched.

## Line cites (re-derived after the last code commit)

- Predicate signature at `class-abstract-recognition-proxy-controller.php:336`: one argument, no threshold parameter.
- Inlined comparison at `:337`: `>= 500`.
- Docblock at `:331-335` still says 5xx → `ENDPOINT_ERROR`, not `UNAVAILABLE`.
- Pin test at `ProxyRequestTest.php:1403`. Parameter count at `:1409-1413`. Status 500 at `:1422-1425`. Status 499 at `:1428-1431`. `WP_Error` at `:1434-1437`.
- R4-01 marker row at `UXW2-5-fix-r4-report.md:22`.

## Canon

- TEST-01: boundary + arity pin written before the production delete.
- TEST-06: first run observed red on parameter count 2 vs 1.
- TEST-15: `>= 400` reddened the 499 case; restore verified.
- REF-25: dead widening lever deleted, not left as a trap.

## Undone

- `Uxw2ReportShaLintTest` is not on this branch. The `sha-lint:allow` marker is a merge-order contract for a lint this checkout cannot execute. No test added (lint-owning branch's job).
- MCP handoff not written: this throwaway lane has no workbay MCP tools.
- PHPCS / phpstan not run. Gate was `composer test` only.
- Existing `is_proxy_endpoint_error()` callers were not given new route-level cases. They stay green under the full suite; this pin is the predicate itself.
- FE `js/**` untouched (out of ownership).
