# demolive-f3 — JSON parse the describe probe

Lane `demolive-f3`. Task `DEMOLIVE-9`.

`extract_probed_description_adapter` no longer takes the last `"description_adapter": "..."` substring in a 2xx body. It parses the body as JSON with `python3` and returns a value only when the **top-level** `description_adapter` is a string. Missing `python3` fail-closes (empty → BLOCK). Nested keys, HTML, and non-JSON substring hits no longer mint `florence_small`.

Owned files: `infra/oci/demo/lib/describe-gate.sh`, `infra/oci/demo/tests/test-describe-gate.sh`. `normalize_fixture_sample`, `fixture_sample_is_denied`, and the top-level `ACX_TRUSTED_DESCRIBE_PROFILES=` assignment were not edited.

## Commits

| SHA | subject |
|---|---|
| `326122c25ecdf1463cb3ed4c3f1b84aae5d7604a` | `fix(DEMOLIVE-9): parse the describe probe response as JSON` |
| `d3b252502f0c461280643604b81e0ab3cfd27daf` | `test(DEMOLIVE-9): pin JSON describe-probe extractor (TEST-15)` |

## What changed

`extract_probed_description_adapter` still requires HTTP 2xx. After that it:

1. Returns empty if `command -v python3` fails (fail closed; same shape as the smoke-gate fixture-pool guard).
2. `json.load`s the body. Invalid JSON, non-object root, missing key, or non-string value → empty.
3. Writes only a top-level JSON **string**. Nested `"description_adapter"` keys are ignored.

`test-describe-gate.sh` pins the false-trust shapes from R4-05 / R6 S1 and greps `apps/prototype-description-service/api/main.py` for `"description_adapter": description_adapter` so deleting the producer field goes red in this suite.

## Suites

Baseline (work order, pre-change): describe-gate 118 `ok`, smoke-gate 110 `ok`, both `all assertions passed`, both exit 0.

### After step 1 (extractor only; original 118 assertions)

```
$ bash infra/oci/demo/tests/test-describe-gate.sh; echo "exit=$?"
...
ok   CLI --force flag exists before wiring

all assertions passed
exit=0
```

```
$ bash scripts/deploy/tests/test-smoke-gate.sh; echo "exit=$?"
...
ok   R1-01B fixture captions ENFORCE=0 still blocked (provenance locked)

all assertions passed
exit=0
```

Smoke-gate stayed at 110 `ok` (drift guard on denylist copies did not trip).

### After step 2 (12 new assertions)

| suite | command | exit | count |
|---|---|---|---|
| describe-gate | `bash infra/oci/demo/tests/test-describe-gate.sh` | `0` | `130` `ok` lines, then `all assertions passed` |
| smoke-gate | `bash scripts/deploy/tests/test-smoke-gate.sh` | `0` | `110` `ok` lines, then `all assertions passed` |

118 + 12 = 130. Smoke-gate unchanged.

## TEST-15

Every mutation was applied, observed, then reverted. Working tree had no leftover mutants at commit time.

### Mutant A — restore substring `sed`

Replaced the `python3` JSON parse with:

```sh
body=$(printf '%s' "$body" | tr '\n' ' ')
value=$(printf '%s' "$body" | sed -n 's/.*"description_adapter"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | sed -n '1p')
```

Command: `bash infra/oci/demo/tests/test-describe-gate.sh`. Exit: `1`. `7 assertion(s) failed`.

| assertion | verbatim FAIL line |
|---|---|
| probe 200 array of objects empty | `FAIL probe 200 array of objects empty: expected , got florence_small` |
| probe 200 HTML page empty | `FAIL probe 200 HTML page empty: expected , got florence_small` |
| probe 200 HTML page classify BLOCK | `FAIL probe 200 HTML page classify BLOCK: expected BLOCK, got RUN` |
| probe 200 nested key keeps top-level seeded | `FAIL probe 200 nested key keeps top-level seeded: expected seeded, got florence_small` |
| probe 200 nested key classify BLOCK | `FAIL probe 200 nested key classify BLOCK: expected BLOCK, got RUN` |
| probe 200 nested-only key empty | `FAIL probe 200 nested-only key empty: expected , got florence_small` |
| probe 200 substring in non-json empty | `FAIL probe 200 substring in non-json empty: expected , got florence_small` |

Previously-BLOCKing shapes stayed `ok` under `sed` (401, 500, 000 refused, 000 timeout, 301, null, missing key, object, invalid JSON, empty body). Genuine `{"description_adapter":"florence_small", ...}` still extracted. Boolean stayed `ok` under `sed` because the regex only matches a quoted string; see mutant B.

Reverted.

### Mutant B — stringify non-string JSON values

Kept JSON parse, dropped the `isinstance(..., str)` guard:

```python
if value is not None:
    sys.stdout.write(value if isinstance(value, str) else json.dumps(value))
```

Exit: `1`. `2 assertion(s) failed`.

| assertion | verbatim FAIL line |
|---|---|
| probe 200 boolean field empty | `FAIL probe 200 boolean field empty: expected , got true` |
| probe 200 object field empty (existing) | `FAIL probe 200 object field empty: expected , got {"name": "florence_small"}` |

Reverted.

### Mutant C — delete producer field (R6 S1)

Deleted `"description_adapter": description_adapter,` from `apps/prototype-description-service/api/main.py` `/health/detailed` return dict. File restored immediately after the suite run. Sibling-lane source was not left dirty.

Exit: `1`. `1 assertion(s) failed`.

| assertion | verbatim FAIL line |
|---|---|
| service /health/detailed payload includes description_adapter | `FAIL service /health/detailed payload includes description_adapter: expected /home/gate/grok-sandbox/feature-demolive-f3-593bdda8/infra/oci/demo/tests/../../../../apps/prototype-description-service/api/main.py to match /"description_adapter": description_adapter/` |

Reverted.

### New assertions that already BLOCKed under `sed`

These are characterization of the existing fail-closed HTTP / type cases. Restoring `sed` did not turn them red (they already returned empty). They are still in the suite so the BLOCK list from R4-05 cannot silently regress:

- `probe 301 without -L empty`
- `probe 000 timeout with body empty`
- `probe 200 boolean field empty` (killed by mutant B, not A)

## Extractor matrix after the change

`extract_probed_description_adapter <code> <body>` → value (empty shown as `''`).

| case | code | body | value |
|---|---|---|---|
| genuine quoted | 200 | `{"status":"ok","description_adapter":"florence_small"}` | `florence_small` |
| seeded top-level | 200 | `{"description_adapter":"seeded","status":"ok"}` | `seeded` |
| spaced json | 200 | multiline JSON, `gpu_qwen30b` | `gpu_qwen30b` |
| health-like payload | 200 | `status` + `embedding_runtime` + top-level `florence_small` | `florence_small` |
| nested key (old last-match hole) | 200 | `{"description_adapter":"seeded","meta":{"description_adapter":"florence_small"}}` | `seeded` |
| 500 | 500 | field present | `''` |
| 401 | 401 | field present | `''` |
| 000 refused | 000 | empty | `''` |
| 000 timeout with body | 000 | field present | `''` |
| 301 without `-L` | 301 | field present | `''` |
| missing key | 200 | `{"status":"ok"}` | `''` |
| null | 200 | `{"description_adapter":null}` | `''` |
| object | 200 | `{"description_adapter":{"name":"florence_small"}}` | `''` |
| boolean | 200 | `{"description_adapter":true}` | `''` |
| number | 200 | `{"description_adapter":1}` | `''` |
| array of objects | 200 | `[{"description_adapter":"florence_small"}]` | `''` |
| unparseable | 200 | `not-json` | `''` |
| empty body | 200 | empty | `''` |
| HTML page | 200 | `<html>"description_adapter": "florence_small"</html>` | `''` |
| nested-only key | 200 | `{"meta":{"description_adapter":"florence_small"}}` | `''` |
| substring in non-json | 200 | `not json but "description_adapter": "florence_small" appears` | `''` |
| python3 missing (`PATH=/nonexistent`) | 200 | genuine JSON | `''` |

Classify on the extracted profile (`100 0`):

| extract | classify |
|---|---|
| HTML → `''` | `BLOCK` |
| nested → `seeded` | `BLOCK` |
| genuine → `florence_small` | `RUN` |

## Unfinished

None in this lane. R6 S2 (sync-demo heredoc `cat` order) and S3 (ADAPTERJSON scrape) are sibling-lane files (`scripts/deploy/**`).

No suite assertion wraps `PATH` to force missing `python3`; fail-closed was proven out-of-band (`PATH=/nonexistent` → empty). Adding that would be a PATH-wrapper test, not a production change.

## Tree state

After mutants reverted, before this report's commit:

```
$ git status --short
 M infra/oci/demo/tests/test-describe-gate.sh
?? docs/reviews/DEMOLIVE-9/demolive-f3-report.md

$ git diff --stat
 infra/oci/demo/tests/test-describe-gate.sh | 14 ++++++++++++++
 1 file changed, 14 insertions(+)
```

`git diff apps/prototype-description-service/api/main.py` is empty. `infra/oci/demo/lib/describe-gate.sh` matches `326122c` (JSON parser; denylist copies untouched).
