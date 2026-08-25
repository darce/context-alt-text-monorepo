# DEMOLIVE-9 R1-03B part 1 — `acx_alt_provenance`

Lane: `demolive-9`  
Finding: `DEMOLIVE-9-R1-03B`  
Checkpoint: `1b27d4cc8ab392bad133c9dc119b6ae2503b21f6`  
Did not touch `scripts/deploy/`, `infra/oci/`, or the smoke gate.

## Edits

- `apps/prototype-wp-alt-context/src/api/class-api.php:67` — import `register_rest_field`
- `apps/prototype-wp-alt-context/src/api/class-api.php:177-204` — register read-only `acx_alt_provenance` on `attachment` (`get_callback` + readonly schema only; no `update_callback`)
- `apps/prototype-wp-alt-context/src/api/class-api.php:323-346` — `get_attachment_alt_provenance` two-key projection
- `apps/prototype-wp-alt-context/src/api/class-api.php:351-373` — attachment id from REST object
- `apps/prototype-wp-alt-context/src/api/class-api.php:380-391` — decode copied from `DescriptionCandidateService::read_provenance`
- `apps/prototype-wp-alt-context/tests/stubs/wp.php:527-538` — `register_rest_field` capture stub
- `apps/prototype-wp-alt-context/tests/TestCase.php:59` — reset `__ac_rest_fields`
- `apps/prototype-wp-alt-context/tests/Unit/AcxAltProvenanceRestFieldTest.php` — 8 pins

## Projection contract

Exact key set when identity is present: `adapter`, `model_id`. Nothing else from `_acx_description_provenance`.

Null (not `{}`, not `""`) when:

- no stored provenance
- stored envelope is present but `adapter` is missing, empty, or whitespace-only
- JSON string fails decode / is not an object

JSON-string meta is decoded with the same array-or-`json_decode` shape as `DescriptionCandidateService::read_provenance`. Missing `model_id` keeps `adapter` and sets `model_id` to `null`. Field is get-only.

## Green suite

Filtered file only, not the full unit suite:

```
cd apps/prototype-wp-alt-context && composer test:unit -- --filter AcxAltProvenanceRestFieldTest
```

Verbatim final line:

```
OK (8 tests, 38 assertions)
```

Did **not** run bare `composer test:unit`, `composer phpstan`, or `composer cs-check`.

## TEST-15

Both mutants applied to `get_attachment_alt_provenance`, filtered suite re-run, then reverted.

### M1 — return the whole stored envelope

Change: `return $provenance;` instead of the two-key array.

Exit code: `1`

Verbatim:

```
1) AltContext\Tests\Unit\AcxAltProvenanceRestFieldTest::testArrayMetaProjectsAdapterAndModelIdOnly
Failed asserting that two arrays are identical.
--- Expected
+++ Actual
@@ @@
 Array &0 [
     'adapter' => 'seeded',
     'model_id' => 'seeded-v1',
+    'model_version' => '1.0',
+    'prompt_or_task_version' => 'task-3',
+    'image_hash' => 'abc123',
+    'context_hash' => 'def456',
+    'generated_at' => '2026-08-25T00:00:00+00:00',
+    'alt_text_draft' => 'A photograph of a lake.',
+    'backend_result_id' => 'res-1',
 ]

/home/gate/grok-sandbox/feature-demolive-9-442e3dd2/apps/prototype-wp-alt-context/tests/Unit/AcxAltProvenanceRestFieldTest.php:56
```

Also failed `testJsonStringMetaDecodesThenProjects` (same extra keys) and `testMissingModelIdKeepsAdapterAndNullModelId` (`model_id` key dropped).

### M2 — return `array()` when no stored provenance

Change: `return array();` instead of `return null;` on absent meta.

Exit code: `1`

Verbatim:

```
1) AltContext\Tests\Unit\AcxAltProvenanceRestFieldTest::testAbsentMetaProjectsNull
Failed asserting that Array &0 [] is null.

/home/gate/grok-sandbox/feature-demolive-9-442e3dd2/apps/prototype-wp-alt-context/tests/Unit/AcxAltProvenanceRestFieldTest.php:47
```

### Revert proof

`git checkout -- apps/prototype-wp-alt-context/src/api/class-api.php`

`git status --short` empty (clean). HEAD still `1b27d4cc8ab392bad133c9dc119b6ae2503b21f6` plus this report file.

## Could not falsify

- Returning the full envelope still satisfies “adapter and model_id are present” — exact `array_keys` / `assertSame` on the two-key payload is required; presence-only asserts would stay green (M1).
- Returning `[]` for never-described attachments is distinguishable from `null` only if the consumer asserts `null` (M2).
- Smoke-gate rewrite is out of scope; this field is the identity surface the follow-up lane should key off.
