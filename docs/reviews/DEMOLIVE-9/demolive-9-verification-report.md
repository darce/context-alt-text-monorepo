# DEMOLIVE-9 verification report — `acx_alt_provenance`

Lane: `demolive-9` (verification, no source/test edits)  
Task: `DEMOLIVE-9`  
Verified tree: `cdc922fa32009fbd92e5ad790a5f70865c8c9c7c` (`master` in this history-stripped sandbox; work order named `feature/demolive-9` `3f60f3855`)  
Plugin cwd: `apps/prototype-wp-alt-context`

Lane-touched files (previous lane; not edited here):

- `src/api/class-api.php`
- `tests/Unit/AcxAltProvenanceRestFieldTest.php`
- `tests/stubs/wp.php`
- `tests/TestCase.php`

---

## Suites

Commands run from `apps/prototype-wp-alt-context` after `composer install --no-interaction --no-progress`.

### `composer test:unit` — exit 0

Verbatim final summary line:

```
OK (1955 tests, 9679 assertions)
```

PHPUnit also printed after that line (suite still exit 0):

```
fatal: Not a valid object name 0000000000000000000000000000000000000000^{commit}
```

Runtime: PHP 8.3.6, PHPUnit 10.5.64, Time 00:37.646, Memory 142.02 MB.

**Denominator finding (loud):** parent known-good was `OK (1955 tests, 9690 assertions)`. This run was expected to be that **plus the 8 new tests**. Observed:

| | Parent | This run | Expected |
| --- | --- | --- | --- |
| Tests | 1955 | **1955** | 1963 |
| Assertions | 9690 | **9679** | ≥ 9690 + new asserts |

Test count is **not lower than 1955**, but it is **not parent+8**. `--list-tests` shows all 8 new methods **are** in the Unit suite:

- `AcxAltProvenanceRestFieldTest::testRegisterRoutesExposesReadOnlyAltProvenanceField`
- `AcxAltProvenanceRestFieldTest::testAbsentMetaProjectsNull`
- `AcxAltProvenanceRestFieldTest::testArrayMetaProjectsAdapterAndModelIdOnly`
- `AcxAltProvenanceRestFieldTest::testJsonStringMetaDecodesThenProjects`
- `AcxAltProvenanceRestFieldTest::testEmptyAdapterProjectsNull`
- `AcxAltProvenanceRestFieldTest::testWhitespaceAdapterProjectsNull`
- `AcxAltProvenanceRestFieldTest::testMissingAdapterKeyProjectsNull`
- `AcxAltProvenanceRestFieldTest::testMissingModelIdKeepsAdapterAndNullModelId`

So 8 other tests are missing relative to a strict parent+8 expectation, **or** the parent 1955 already included a different mix. Assertion count is **11 below** parent 9690 even with the new file present. Nobody reached green by deleting this lane's tests; the new file is loaded. Net count still did not rise.

### `composer phpstan` — exit 0

Verbatim final line:

```
 [OK] No errors
```

146 files analysed. No offending files.

### `composer cs-check` — exit 2 (red)

PHPCS did not emit an `A TOTAL OF …` line. Verbatim trailing lines:

```
Time: 49.87 secs; Memory: 92MB

Script vendor/bin/phpcs --standard=phpcs.xml.dist handling the cs-check event returned with error code 2
```

18 errors across 6 files (listed in **Red files**). Suite is red. Not fixed in this lane.

---

## Red files

### Lane-touched

none

(`src/api/class-api.php`, `tests/Unit/AcxAltProvenanceRestFieldTest.php`, `tests/stubs/wp.php`, `tests/TestCase.php` are clean under phpstan and cs-check.)

### Pre-existing (cs-check only; phpstan none)

All six phpcs offenders are **pre-existing unrelated files**, not among the four previous-lane paths:

| File | Errors | Notes |
| --- | --- | --- |
| `src/api/class-media-identities-controller.php` | 1 | L37 blank line after last trait import (`[x]` phpcbf) |
| `tests/Support/TopUnlabeledSchemaValidator.php` | 8 | missing `@throws`; unescaped output (`$path`, `$required`, `$relative`) |
| `tests/Unit/PersonResolutionServiceTest.php` | 1 | L94 assignment to `$GLOBALS['wpdb']` |
| `tests/Unit/ClusterTopUnlabeledSchemaConsistencyTest.php` | 6 | missing `@throws`; unescaped output (`$path`, `$required`) |
| `tests/Unit/AbstractSpaPageTest.php` | 1 | L31 space after `class` in anonymous class (`[x]` phpcbf) |
| `tests/Unit/LoadingMessageVocabularyTest.php` | 1 | L103 short ternary |

---

## Adversarial read

Subject: `Api::get_attachment_alt_provenance` in `src/api/class-api.php` (L323–346), schema at L177–204, writers `DescribeMediaService::build_generated_provenance` (L787–806) and `DescriptionCommand::build_provenance` (L519–531; constants at L43–44 are the meta key names, not the writer).

### 1. Other return shapes?

Could not find one. Every path returns `null` or a newly constructed two-key array `['adapter' => <non-empty string>, 'model_id' => <string|null>]`.

- Missing/non-array provenance → `null`
- Missing / non-string / whitespace-only `adapter` → `null`
- Success always rebuilds the array (never returns the stored envelope)
- `model_id` is copied only when it is a string (not trimmed); non-strings become `null`. Empty-string `model_id` is still a string, so it stays inside the declared shape.

No input inspected returns extra keys, a `WP_Error`, or the raw `_acx_description_provenance` envelope.

### 2. Anonymous leak beyond `adapter` / `model_id`? [SECD-12]

No. The registered field does not leak other envelope keys to an anonymous `/wp-json/wp/v2/media` caller.

- `get_callback` returns only `adapter` and `model_id`.
- Schema: `additionalProperties: false`; `properties` lists only those two keys; `readonly: true`; no `update_callback`.
- Schema `context` is `view` / `embed` / `edit`, so anonymous **view** callers **can** see the projected identity — that is the intended smoke-gate surface — but not `image_hash`, `context_hash`, `alt_text_draft`, `backend_result_id`, `model_version`, `prompt_or_task_version`, or `generated_at`.
- Protected meta `_acx_description_provenance` is not itself registered as a REST field.

### 3. Do both writers always set `adapter`?

Both **always set the `adapter` key**. Neither writes an envelope that omits it.

- REST (`build_generated_provenance` L789): `'adapter' => $data['adapter']`. Upstream `validate_description_envelope` requires `array_key_exists('adapter', $data)` but does **not** require a non-empty string. Empty string or a non-string value that still has the key would be stamped.
- CLI (`build_provenance` L524): `'adapter' => (string) ( $data['adapter'] ?? '' )`. Key always present; missing/null becomes `''`.

An empty-string `adapter` is **not** a missing key, but `get_attachment_alt_provenance` treats it as `null` identity. That path would fail closed on the follow-up smoke gate even if alt text was generated. I did not find a happy-path writer that omits the key entirely. Not fixed in this lane.

---

## Confirmation that I edited no source or test file

`git status --short` **before** `git add` (report already written; no source/test paths):

```
?? docs/reviews/DEMOLIVE-9/demolive-9-verification-report.md
```

Ignored side effects of `composer install` (not staged): `apps/prototype-wp-alt-context/composer.lock`, `apps/prototype-wp-alt-context/vendor/`, phpunit/phpstan caches.
