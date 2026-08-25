# DEMOLIVE-9 verification #2 — R1-03B/R1-03C stack

Lane: `demolive-9` (verification #2, no source/test edits)
Task: `DEMOLIVE-9`
Work-order HEAD: `526d8f976` (`feature/demolive-9`)
Verified tree: `dd7f0005c6353f08c91ae3aa4c5f3cb03c9fc5a0` (`master` in this history-stripped sandbox)
Plugin cwd: `apps/prototype-wp-alt-context`

Since last verification (`77f00b562`, `OK (1955 tests, 9679 assertions)`, phpstan `[OK] No errors`):

- `6761483c5` — shell: `scripts/deploy/lib/smoke-gate.sh`, `scripts/deploy/sync-demo.sh`, `scripts/deploy/tests/test-smoke-gate.sh`, `infra/oci/demo/tests/test-describe-gate.sh`
- `c1cb198ec` + `526d8f976` — PHP: `src/api/services/class-describe-media-service.php`, `src/cli/class-description-command.php`, `tests/Unit/DescribeMediaServiceTest.php`, `tests/Unit/DescriptionCommandGenerateTest.php`

---

## Suites

Commands run from `apps/prototype-wp-alt-context` after `composer install --no-interaction --no-progress` (php/phpstan/cs-check) and from repo root (shell gates).

### `composer test:unit` — exit 0

Verbatim final summary line:

```
OK (1970 tests, 9773 assertions)
```

PHPUnit also printed after that line (suite still exit 0):

```
fatal: Not a valid object name 0000000000000000000000000000000000000000^{commit}
```

Runtime: PHP 8.3.6, PHPUnit 10.5.64, Time 00:37.824, Memory 142.02 MB.

### `composer phpstan` — exit 0

Verbatim final line:

```
 [OK] No errors
```

146 files analysed. No errors. No regression from the PHP commits.

### `composer cs-check` — exit 2 (red)

Verbatim trailing lines:

```
Time: 50.19 secs; Memory: 94MB

Script vendor/bin/phpcs --standard=phpcs.xml.dist handling the cs-check event returned with error code 2
```

19 errors across 7 files (was 18 across 6). Split in **cs-check split**. Suite is red. Not fixed in this lane.

### `bash scripts/deploy/tests/test-smoke-gate.sh` — exit 0

Verbatim final line:

```
all assertions passed
```

### `bash infra/oci/demo/tests/test-describe-gate.sh` — exit 0

Verbatim final line:

```
all assertions passed
```

---

## Denominator check

Baseline at `77f00b562`: `OK (1955 tests, 9679 assertions)`.

| | `77f00b562` | this run | delta |
| --- | --- | --- | --- |
| Tests | 1955 | **1970** | **+15** |
| Assertions | 9679 | **9773** | **+94** |

`--list-tests | wc -l` printed `1973` (= 1970 tests + 3 PHPUnit banner lines). Cross-check agrees with the summary count.

`--list-tests` also lists 94 methods on `DescribeMediaServiceTest` and 60 on `DescriptionCommandGenerateTest` (154 in those two files). Both files are loaded.

**Verdict:** strictly up on both counts. Nothing was removed. The two PHP commits added tests; the suite did not reach green by deleting coverage.

---

## cs-check split

19 errors / 7 files. Last verification: 18 errors / 6 files, all pre-existing.

### Pre-existing (same 6 files, same 18 errors)

| File | Errors |
| --- | --- |
| `src/api/class-media-identities-controller.php` | 1 |
| `tests/Support/TopUnlabeledSchemaValidator.php` | 8 |
| `tests/Unit/PersonResolutionServiceTest.php` | 1 |
| `tests/Unit/ClusterTopUnlabeledSchemaConsistencyTest.php` | 6 |
| `tests/Unit/AbstractSpaPageTest.php` | 1 |
| `tests/Unit/LoadingMessageVocabularyTest.php` | 1 |

These were already red at the last verification and are unrelated to `6761483c5` / `c1cb198ec` / `526d8f976`.

### New (touched by the PHP commits)

| File | Errors | Message |
| --- | --- | --- |
| `src/cli/class-description-command.php` | 1 | L556 `Missing @throws tag in function comment` (`require_usable_adapter`) |

This file was touched by `c1cb198ec` / `526d8f976`. It is a **NEW** offender. `require_usable_adapter` throws `\InvalidArgumentException` and the docblock has `@param mixed $adapter` but no `@throws`.

Not in cs-check (touched files that stayed clean):

- `src/api/services/class-describe-media-service.php`
- `tests/Unit/DescribeMediaServiceTest.php`
- `tests/Unit/DescriptionCommandGenerateTest.php`
- all four `6761483c5` shell paths (not in the phpcs scan)

phpstan: no new (or old) errors.

---

## Adversarial read

Subjects: `classify_alt_identity` / `classify_alt_provenance` in `scripts/deploy/lib/smoke-gate.sh`, adapter scrape loop in `scripts/deploy/sync-demo.sh` (`ADAPTERJSON` heredoc, `grep -o '"adapter": *"[^"]*"'` over the `_fields=id,alt_text,acx_alt_provenance` body).

### 1. Can any key other than `acx_alt_provenance.adapter` produce a `"adapter":` match?

I could not find another **key**.

Requested `_fields` are `id` (int), `alt_text` (string), `acx_alt_provenance` (`{adapter, model_id}|null`). `get_attachment_alt_provenance` rebuilds a two-key array or returns `null`; schema `additionalProperties: false`. WP core media schema has no `adapter` field. `_links` (still typically emitted under `_fields`) uses `href` / `embeddable`, not `adapter`. The URL does not request `_embed`.

The grep is whole-body, so a *value* containing the exact bytes `"adapter": "..."` could theoretically match. JSON-encoded `alt_text` escapes inner quotes; the resulting `\"adapter\":` does **not** satisfy `"adapter":` (backslash between `adapter` and the quote that would precede the colon). `id` cannot. I did not find a second key on this surface that inflates the blob.

### 2. Cheapest live-demo state: provenance PASS, alt still useless to a screen-reader user

Constructed.

One attachment:

- `alt_text` = `abcdefghijklmno` (15 letters; `classify_alt_text_usable` already pins this as PASS)
- `acx_alt_provenance.adapter` = `florence_small`
- `x-wp-total` = 1 (population 1==1)

Gates on that library:

- coverage `1/1 = 100% >= 95` → PASS
- identity: one trusted adapter, `trusted_count=1 >= usable_count=1` → PASS
- Gate B: normalized sample `abcdefghijklmno` is not a fixture-denylist arm → PASS

`classify_alt_provenance` therefore PASSes. A screen-reader user hears fifteen nonsense letters. Usable-alt is only “trim non-empty, length ≥ 15, has `[A-Za-z]`”; it never asks whether the text describes the image. Anything below 15 letters fails usable, sets `with_alt=0`, and never reaches provenance (hard FAIL “no alt text published”). 15 gibberish letters is the floor.

Not fixed in this lane.

### 3. Empty-alt + trusted adapter: does `trusted_count >= usable_count` certify a mostly-empty library?

No — not on the shipped path. Extra empty-alt adapters inflate `trusted_count` (which only helps `>=`) but coverage fail-closes first.

Actual loops in `sync-demo.sh`:

1. `with_alt` loop: only increments when `classify_alt_text_usable` is PASS. Empty alt → FAIL → not in `usable_count` / `sample`.
2. `ADAPTERJSON` scrape: every `"adapter": "..."` is appended with **no** alt check. Empty-alt + `florence_small` **does** join the blob and increment `trusted_count`.
3. `body_total` is `grep -o '"alt_text": *"[^"]*"'` (empty `""` still matches) and is the coverage denominator.
4. `classify_alt_coverage "$body_total" "$with_alt" "$min"` runs **before** provenance. Default `min=95`, fixed floor 50. A library where most images have no alt is `< 50%` usable and FAILs coverage.
5. Provenance is only invoked when `with_alt > 0`. If every alt is empty, the `else` arm is `FAIL "demo alt provenance (no alt text published; nothing to certify)"` and `classify_alt_identity` is never called. Empty-alt adapters cannot pass identity on a fully empty library.

So: the inequality **would** pass on `1` usable + `99` empty-with-trusted-adapter (`trusted_count=100 >= usable_count=1`), but coverage `1/100` already FAILed and set `smoke_fail`. Identity is not what ships that library.

Hatch only: `DEMO_ALT_GATE_ENFORCE=0` turns coverage FAIL into WARN when `with_alt > 0` (not when `with_alt=0`). Then that 1+99 library WARNs coverage and PASSes identity. Default enforce is `1`; that is not the shipped path.

Opposite direction also holds: 95 usable-without-adapter + 5 empty-with-trusted-adapter → coverage `95/100` PASS, identity `5 >= 95` FAIL. Empty-alt adapters cannot substitute for missing adapters on the usable items.

Not fixed in this lane.

---

## Confirmation that I edited no source or test file

`git status --short` **before** `git add` (report already written; no source/test paths):

```
?? docs/reviews/DEMOLIVE-9/demolive-9-verification-2-report.md
```

Ignored side effects of `composer install` (not staged): `apps/prototype-wp-alt-context/composer.lock`, `apps/prototype-wp-alt-context/vendor/`, phpunit/phpstan caches.
