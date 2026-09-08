# R6 verdict: mutations survive

Lens: Green is not correct; for every new assertion, reintroduce the old behaviour and prove the suite goes red [TEST-15].

Every mutation below was applied, observed, then reverted. Working tree had no mutations at commit time.

## Baseline

| suite | command | exit | count |
|---|---|---|---|
| smoke-gate | `bash scripts/deploy/tests/test-smoke-gate.sh` | `0` | `110` `ok` lines, then `all assertions passed` |
| describe-gate | `bash infra/oci/demo/tests/test-describe-gate.sh` | `0` | `118` `ok` lines, then `all assertions passed` |
| PHP unit | `cd apps/prototype-wp-alt-context && composer test:unit` | `0` | `OK (1970 tests, 9773 assertions)` |

PHP delta vs last recorded 1970 / 9773: **0 tests, 0 assertions**. No drop.

PHP mutants below were re-run as `vendor/bin/phpunit --filter <covering test>` (those tests are in `composer test:unit`). Full 1970-test suite was not re-executed per PHP mutant.

## Mutants killed

| mutation | suite | verbatim FAIL line | exit |
|---|---|---|---|
| M1 restore ENFORCE early-return (drop `overridable=1` conjunct in `emit_alt_gate`) | test-smoke-gate.sh | `FAIL R1-01 provenance FAIL non-overridable under DEMO_ALT_GATE_ENFORCE=0: expected FAIL demo alt provenance (seeded fixture caption detected in 100 published alt texts)` (`6 assertion(s) failed`) | `1` |
| M2 remove `min_pct` floor (`if [ "$min_pct" -lt "$floor" ]` deleted) | test-smoke-gate.sh | `FAIL alt coverage min_pct 0 below fixed floor (certify-a-lie): expected FAIL, got PASS` (`4 assertion(s) failed`) | `1` |
| M3 usable-alt classifier accepts empty string (`echo PASS` on empty-after-trim) | test-smoke-gate.sh | `FAIL usable alt empty: expected FAIL, got PASS` (`3 assertion(s) failed`) | `1` |
| M4 skip normalization before denylist matching (`sample="$1"` in `fixture-denylist.sh`) | test-smoke-gate.sh | `FAIL alt provenance live seeded draft on demo media id 5: expected FAIL, got PASS` (`23 assertion(s) failed`) | `1` |
| M5 `_FIXTURE_POOL` key `'caption':` (R3-01 survivor) | test-smoke-gate.sh | `FAIL fixture-pool extraction count 7 != pool length 8` | `1` |
| M6 9th fixture caption without a denylist arm | test-smoke-gate.sh | `FAIL drift: pool caption classified FAIL (R6-SENTINEL a caption that is not in the shell gate.): expected FAIL, got PASS` | `1` |
| M7 delete pet-animal `case` arm from canonical `fixture_sample_is_denied` | test-smoke-gate.sh | `FAIL alt provenance fixture: pet animal: expected FAIL, got PASS` (`3 assertion(s) failed`) | `1` |
| M8 describe-gate BLOCK branch does not `exit 1` | test-describe-gate.sh | `FAIL config-fault BLOCK exits 1: expected .../bootstrap-wp.sh to match /exit 1/` | `1` |
| M9 `/health/detailed` probe falls back to `env_get ACX_DESCRIPTION_ADAPTER` | test-describe-gate.sh | `FAIL bootstrap does not env_get ACX_DESCRIPTION_ADAPTER: expected .../bootstrap-wp.sh NOT to match /env_get ACX_DESCRIPTION_ADAPTER/` | `1` |
| M11a `classify_alt_identity` `-lt` → `-le` | test-smoke-gate.sh | `FAIL alt provenance real caption (not a fixture): expected PASS, got FAIL` (`5 assertion(s) failed`) | `1` |
| M11b `classify_alt_identity` `-lt` → `-gt` | test-smoke-gate.sh | `FAIL alt provenance trusted fewer than usable_count: expected FAIL, got PASS` | `1` |
| M11c empty blob returns PASS when `usable_count > 0` | test-smoke-gate.sh | `FAIL alt provenance empty adapters blob usable 1 (fail closed): expected FAIL, got PASS` (`2 assertion(s) failed`) | `1` |
| M11d drop `is_trusted_describe_profile` check | test-smoke-gate.sh | `FAIL alt provenance untrusted adapter seeded: expected FAIL, got PASS` (`2 assertion(s) failed`) | `1` |
| M12a Gate A PASS short-circuits, skipping Gate B | test-smoke-gate.sh | `FAIL alt provenance empty sample (cannot prove): expected FAIL, got PASS` (`24 assertion(s) failed`) | `1` |
| M12b skip Gate A (denylist only) | test-smoke-gate.sh | `FAIL alt provenance untrusted adapter seeded: expected FAIL, got PASS` (`7 assertion(s) failed`) | `1` |
| M13a `class-api.php` project a third key `image_hash` | PHPUnit `AcxAltProvenanceRestFieldTest` | `Failed asserting that two arrays are identical.` (`Tests: 8, Assertions: 28, Failures: 3`; Actual adds `'image_hash' => 'abc123'`) | `1` |
| M13b return the whole provenance array | PHPUnit `AcxAltProvenanceRestFieldTest` | `Failed asserting that two arrays are identical.` (Actual adds `model_version`, `image_hash`, `context_hash`, `alt_text_draft`, …) | `1` |
| M13c drop the `null` return for an empty adapter | PHPUnit `AcxAltProvenanceRestFieldTest` | `Failed asserting that Array &0 [ 'adapter' => '', 'model_id' => 'seeded-v1',` is null (`testEmptyAdapterProjectsNull`; `Failures: 3`) | `1` |
| M13d remove `readonly` from the REST field schema | PHPUnit `testRegisterRoutesExposesReadOnlyAltProvenanceField` | `Failed asserting that false is true.` (`AcxAltProvenanceRestFieldTest.php:38`) | `1` |
| M13e add `update_callback` | PHPUnit `testRegisterRoutesExposesReadOnlyAltProvenanceField` | `Failed asserting that an array does not have the key 'update_callback'.` (`AcxAltProvenanceRestFieldTest.php:36`) | `1` |
| M14 delete non-empty-`adapter` check in `validate_description_envelope` | PHPUnit `testUnusableAdapterReturns502` | `Failed asserting that an object is an instance of class WP_Error.` (data set `"empty"`; `Failures: 5` of 6 — missing key still 502 via `REQUIRED_RESPONSE_FIELDS`) | `1` |
| M15 `require_usable_adapter` coerce with `(string)` instead of throw | PHPUnit `testGenerateWriteRejectsUnusableAdapter` | `Failed asserting that null is an instance of class RuntimeException.` (data set `"missing"`; `Failures: 6`) | `1` |
| M16a drop `acx_alt_provenance` from `_fields` | test-smoke-gate.sh | `FAIL R1-03B _fields= in sync-demo.sh missing acx_alt_provenance` | `1` |
| M17 mutate one `normalize_fixture_sample` copy (drop `tr '[:upper:]' '[:lower:]'` in describe-gate.sh only) | test-smoke-gate.sh | `FAIL drift: normalize_fixture_sample bodies diverged between describe-gate.sh and fixture-denylist.sh` | `1` |
| M17 (same mutation) | test-describe-gate.sh | `FAIL alt provenance fixture FAIL: expected FAIL, got PASS` (`2 assertion(s) failed`) | `1` |

M5 (quote-style) is **no longer a survivor**. R3-01's ast pool-length pin killed it.

## Mutants that SURVIVED

These are the high findings. Each suite printed `all assertions passed` after the mutation.

### S1 | high | `apps/prototype-description-service/api/main.py` `/health/detailed`

Mutation: delete `description_adapter` from the detailed-health payload.

```diff
         return {
             ...
             "embedding_runtime": embedding_runtime,
-            "description_adapter": description_adapter,
         }
```

| suite | exit | output |
|---|---|---|
| `bash scripts/deploy/tests/test-smoke-gate.sh` | `0` | `all assertions passed` |
| `bash infra/oci/demo/tests/test-describe-gate.sh` | `0` | `all assertions passed` |

Describe-gate greps `bootstrap-wp.sh` for the string `description_adapter` and pins `extract_probed_description_adapter` against **synthetic JSON**. It never loads `api/main.py`. Smoke never sees it. PHP unit never sees it.

A Python test exists outside the three named suites (`recognition/tests/api/test_health_probes.py::test_health_detailed_reports_description_adapter`) but could not be executed here (`ModuleNotFoundError: No module named 'numpy'`). The mandated suites cannot go red for this regression.

### S2 | high | `scripts/deploy/sync-demo.sh` heredoc `cat` order

Mutation: reverse the three concatenations (later definition still wins on the VM).

```diff
-  cat "$DESCRIBE_GATE_SRC"
-  cat "$FIXTURE_DENYLIST_LIB"
-  cat "$SMOKE_GATE_LIB"
+  cat "$SMOKE_GATE_LIB"
+  cat "$FIXTURE_DENYLIST_LIB"
+  cat "$DESCRIBE_GATE_SRC"
```

`bash scripts/deploy/tests/test-smoke-gate.sh` → exit `0`, `all assertions passed`.

Tests source the three files in the documented order. They never grep, concatenate, or execute the remote heredoc. Comments call the order load-bearing (canonical denylist must overwrite describe-gate copies). The production `cat` sequence is decoration.

### S3 | high | `scripts/deploy/sync-demo.sh` ADAPTERJSON scrape (extra)

Mutation: stop scraping `"adapter"` out of the media body.

```diff
- $(grep -o '"adapter": *"[^"]*"' "$media_body" || true)
+ $(grep -o '"NO_SUCH_ADAPTER_FIELD": *"[^"]*"' "$media_body" || true)
```

`bash scripts/deploy/tests/test-smoke-gate.sh` → exit `0`, `all assertions passed`.

The `_fields=...acx_alt_provenance` grep pin (M16a) went red. The live scrape that actually fills `adapters` for Gate A is unexecuted. A deploy can request the field and still classify identity against an empty blob.

## Not attempted

None of the work-order minimum list. Extra mutant S3 (ADAPTERJSON scrape) was run and survived.

Frontend DEMOLIVE-4 (`js/admin/**`, `DashboardSyncHealthSection.tsx`) was not mutated: none of the three named suites exercise it.

## Coverage gaps (behaviour with no assertion at all)

1. **Producer `/health/detailed` payload** — see S1. Bootstrap probe + JSON extractor are tested; the service field that feeds them is not in the three suites.
2. **Remote heredoc concatenation order** — see S2. No assertion that `sync-demo.sh` cats describe-gate, then fixture-denylist, then smoke-gate.
3. **ADAPTERJSON scrape loop** — see S3. Requesting `_fields=acx_alt_provenance` is pinned; parsing `"adapter"` out of the body is not.
4. **DEMOLIVE-4 dashboard/frontend** — no characterization in the three named suites.

R1-03D (`abcdefghijklmno` usable) not re-reported: no new interaction found. Empty-alt still fail-closes coverage (M3) independently of the 15-char gibberish PASS.

## Tree state at exit

Mutations reverted before commit. After this file:

```
$ git status --short
(empty)

$ git diff --stat
(empty)
```
