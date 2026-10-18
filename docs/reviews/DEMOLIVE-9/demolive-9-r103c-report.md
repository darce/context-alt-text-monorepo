# DEMOLIVE-9 R1-03C — reject empty adapter at the provenance write boundary

Lane: `demolive-9`
Finding: `DEMOLIVE-9-R1-03C`
Code checkpoint: `ad1a9373430f25c0107b8947753dbb83faa17d00`
Did not touch `scripts/deploy/`, `infra/oci/`, or `src/api/class-api.php`. Did not change `REQUIRED_RESPONSE_FIELDS` membership. Did not trim/normalise adapter on the happy path [rg-015].

## Root cause

Instrumented `validate_description_envelope` after the `REQUIRED_RESPONSE_FIELDS` loop. HTTP `json_encode` → `json_decode($body, true)` (via `queueHttpResponse` / proxy rewrite) preserves the test's adapter type. Captured at the check:

| dataset | reached check | decoded type | value |
| --- | --- | --- | --- |
| missing | no | — | `array_key_exists` fails first (L254-257) |
| empty | yes | string | `''` |
| whitespace | yes | string | `' '` |
| int | yes | integer | `42` |
| array | yes | array | `['nope']` |
| null | yes | NULL | `null` |

`describe_media` (L213-216) returns that `WP_Error` to the controller unchanged. It does not wrap it as `WP_REST_Response`. `record_success_from_response`'s `'description'` fallback (L834) runs only after validation succeeds — it is not rewriting adapter before the check.

The prior RED (`Tests: 20, Assertions: 93, Failures: 5`) is exactly M1: without the L271 check, the five present-but-unusable datasets pass the key-exists loop and `alt_text_draft` string check, then `apply_alt_text_write_policy` returns a `WP_REST_Response`. `'missing'` stays green because `REQUIRED_RESPONSE_FIELDS` already 502s. The envelope is not re-keyed; the check was simply not refusing present unusable values.

## (a) or (b)

**(a) The implementation is wrong** (when the L271 check is absent). Tests as written are the real contract.

Same error channel as `alt_text_draft` (L262-264): `invalid_envelope_error` → `WP_Error` code `invalid_description_envelope`, status 502. Load-bearing meta asserts (`_wp_attachment_image_alt` and `_acx_description_provenance` stay `''`) remain. Not (b): the caller really does see `WP_Error`, matching `testNonStringAltTextDraftReturns502`.

## Edits

- `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php:266-273` — refuse non-string / empty / whitespace-only `adapter` via `invalid_envelope_error` (comment documents the JSON-decoded types).
- `apps/prototype-wp-alt-context/src/cli/class-description-command.php:319-327` — catch `InvalidArgumentException` from `build_provenance` as a per-item `adapter_error`.
- `apps/prototype-wp-alt-context/src/cli/class-description-command.php:394-400` — if this item would write, return `AltTextWriteStatus::FAILED` with the adapter message; skip/empty arms still do not stamp.
- `apps/prototype-wp-alt-context/src/cli/class-description-command.php:542,557-562` — `require_usable_adapter()`; happy path returns `$adapter` unchanged (no trim).
- `apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServiceTest.php:489-551` — REST 502 + passthrough.
- `apps/prototype-wp-alt-context/tests/Unit/DescriptionCommandGenerateTest.php:117-243` — CLI reject + passthrough + [rg-007] batch pin.

## Rejection contract

Refused at both writers: missing key, `''`, whitespace-only (`' '`), non-string (`int`, `array`, `null`). Valid `'florence_small'` writes unchanged.

- **REST:** caller gets `WP_Error` (`invalid_description_envelope`, 502, message names `adapter`). No alt write, no provenance stamp.
- **CLI:** per-item `status=failed` + `error` containing `adapter`. `generate()` still iterates the rest of the batch; WP-CLI then `error()`s the summary so a single-item reject exits non-zero (`RuntimeException` in the stub). No alt write, no provenance stamp on the rejected id.

## Batch behaviour

`generate()` L165-166: `foreach ( $media_ids as $id ) { $rows[] = $this->generate_one(...); }`. Item 7's `FAILED` is one row. Items 8-100 still run. Pin: `testGenerateWriteRejectedAdapterDoesNotAbortBatch` — id 801 failed (empty adapter, no meta), id 802 written (`florence_small`). [rg-007]

## Green suite

Filtered only, not the full unit suite:

```
cd apps/prototype-wp-alt-context && composer test:unit -- --filter Adapter
```

Verbatim final line:

```
OK (20 tests, 118 assertions)
```

Did **not** run bare `composer test:unit`, `composer phpstan`, or `composer cs-check`.

## TEST-15

Both mutants applied, filtered suite re-run, then reverted. `git status --short` clean after revert.

### M1 — remove the REST adapter check in `validate_description_envelope`

Empty-string (and the other present unusable values) pass validation.

Exit code: `1`

Verbatim:

```
1) AltContext\Tests\Unit\DescribeMediaServiceTest::testUnusableAdapterReturns502 with data set "empty" ('', false)
Failed asserting that an object is an instance of class WP_Error.

5) AltContext\Tests\Unit\DescribeMediaServiceTest::testUnusableAdapterReturns502 with data set "null" (null, false)
Failed asserting that an object is an instance of class WP_Error.

FAILURES!
Tests: 20, Assertions: 93, Failures: 5.
```

`'missing'` stayed green (REQUIRED_RESPONSE_FIELDS). Reverted with `git checkout --` on the service file.

### M2 — restore CLI `(string) ( $data['adapter'] ?? '' )` in `build_provenance`

Exit code: `1`

Verbatim:

```
1) AltContext\Tests\Unit\DescriptionCommandGenerateTest::testGenerateWriteRejectsUnusableAdapter with data set "missing" (null, true)
Failed asserting that null is an instance of class RuntimeException.

7) AltContext\Tests\Unit\DescriptionCommandGenerateTest::testGenerateWriteRejectedAdapterDoesNotAbortBatch
Failed asserting that null is an instance of class RuntimeException.

FAILURES!
Tests: 20, Assertions: 76, Failures: 7, Warnings: 1.
```

Reverted with `git checkout --` on the CLI file.

## Could not falsify

- `'florence_small'` still writes; stored adapter is exactly `'florence_small'` (no trim).
- Rejected REST/CLI items leave `_wp_attachment_image_alt` and `_acx_description_provenance` as `''`.
- One CLI reject does not skip the next valid item.
- M1/M2 both went red; pins are not vacuous.
- JSON round-trip does not stringify `null`/`42`/`['nope']`.
