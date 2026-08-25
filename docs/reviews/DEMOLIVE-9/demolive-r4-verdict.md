# R4 verdict: fail

Lens: the merged DEMOLIVE-2/3/6/7/8/9 gates still exit 0 on canned fixture alt (one internal comma or NBSP) and on a library that is half empty.

## Findings

### R4-01 | severity: high | file: scripts/deploy/lib/fixture-denylist.sh:38

Evidence: Gate B is substring match after `tr '[:upper:]' '[:lower:]'`, `tr -s '[:space:]' ' '`, and a trailing `.!?` strip. Internal punctuation, NBSP (U+00A0), a non-breaking hyphen, a zero-width space, and a Cyrillic `а` in `neutral` all leave the fixture sentence off the denylist. Sourced the three libs in heredoc order and ran `classify_alt_provenance` with a trusted identity:

```
$ source infra/oci/demo/lib/describe-gate.sh
$ source scripts/deploy/lib/fixture-denylist.sh
$ source scripts/deploy/lib/smoke-gate.sh
$ classify_alt_provenance 'A close-up of a small object, on a neutral background.' florence_small 1
PASS
$ classify_alt_provenance 'A close-up of a small object; on a neutral background.' florence_small 1
PASS
$ classify_alt_provenance 'A close-up of a small object. on a neutral background.' florence_small 1
PASS
$ # NBSP between every word (UTF-8 C2 A0)
$ classify_alt_provenance "$(printf 'A\xc2\xa0close-up\xc2\xa0of\xc2\xa0a\xc2\xa0small\xc2\xa0object\xc2\xa0on\xc2\xa0a\xc2\xa0neutral\xc2\xa0background.')" florence_small 1
PASS
$ classify_alt_provenance "$(printf 'A close-up of a small object on a neutr\xd0\xb0l background.')" florence_small 1
PASS
$ classify_alt_provenance 'A close-up of a small object on a neutral background.' florence_small 1
FAIL
```

Replayed the sync-demo `emit_alt_gate` pipeline (`DEMO_ALT_GATE_ENFORCE=1`, `DEMO_ALT_MIN_COVERAGE_PCT=95`, 100/100 usable, 100 `florence_small` tokens):

```
# comma fixture
PASS demo alt population (header=100 body=100)
PASS demo alt coverage (100/100 = 100%, need 95%)
PASS demo alt provenance
smoke_fail=0

# exact fixture (control)
PASS demo alt population (header=100 body=100)
PASS demo alt coverage (100/100 = 100%, need 95%)
FAIL demo alt provenance
smoke_fail=1

# NBSP fixture
PASS demo alt population (header=100 body=100)
PASS demo alt coverage (100/100 = 100%, need 95%)
PASS demo alt provenance
smoke_fail=0
```

Prefix/suffix/wrap/case/trailing `.!?` still FAIL. The surviving mutant is an edit *inside* the sentence.

Failure scenario: 100 published alts equal to `A close-up of a small object, on a neutral background.` with `_fields` reporting `acx_alt_provenance.adapter=florence_small` (real or forged). Coverage 100%, Gate A trusted, Gate B misses the comma, `sync-demo.sh` exits 0. Public demo alt is the seeded fixture with one extra comma.

Canon: CLM-04, PROV-10, RLSE-08, TEST-15

Suggested fix: strip `[:punct:]` (and NBSP/ZWSP) inside `normalize_fixture_sample` before the substring arms, or deny by token-set / edit-distance against `_FIXTURE_POOL`.

### R4-02 | severity: high | file: scripts/deploy/lib/smoke-gate.sh:172

Evidence: `classify_alt_identity` word-splits `adapters_blob` (`for adapter in $adapters_blob`) and requires `trusted_count >= usable_count`. One REST `adapter` string that contains 100 copies of `florence_small` satisfies Gate A for 100 usable alts whose other rows have `acx_alt_provenance: null`.

```
$ classify_alt_identity "$(printf 'florence_small %.0s' {1..100})" 100
PASS
$ classify_alt_identity "$(printf 'florence_small %.0s' {1..100})" 101
FAIL
$ classify_alt_identity 'florence_small' 3
FAIL
```

Exact `sync-demo.sh:315-316` scrape (`grep -o '"adapter": *"[^"]*"'`) on this body:

```
[{"id":1,"alt_text":"A close-up of a small object, on a neutral background.","acx_alt_provenance":{"adapter":"florence_small florence_small","model_id":"x"}},{"id":2,"alt_text":"A close-up of a small object, on a neutral background.","acx_alt_provenance":null}]
```

verbatim scrape result:

```
with_alt=2 blob=florence_small florence_small
identity=PASS
provenance=PASS
```

99-null + 1 unpadded trusted token still FAILs (`trusted_count 1 < usable 3`). Any `seeded` token in the blob FAILs. The pad only works when every scraped token is trusted — which a single space-padded meta value provides, because null provenance contributes zero tokens.

`get_attachment_alt_provenance` (`class-api.php:330-345`) `trim()`s the stored adapter and projects it verbatim. It does not split, sign, or compare against the producer. `wp post meta update` of `_acx_description_provenance` to `{"adapter":"florence_small florence_small ...","model_id":"x"}` is enough.

Failure scenario: describe with `seeded` (or hand-write canned alts), delete provenance on N-1 attachments, stamp one attachment with a space-padded trusted adapter string. Gate A counts N trusted tokens. Combined with R4-01 (comma/NBSP) Gate B also PASSes. Deploy exit 0. The gate proved "the scrape found >=N trusted words", not "each usable alt was produced by a trusted adapter".

Canon: PROV-10, SECD-08, RLSE-08, rg-015

Suggested fix: count at most one trusted adapter per media item (parse JSON, not word-split); reject adapter values containing whitespace; treat trusted_count != usable_count as FAIL (not `<`).

### R4-03 | severity: medium | file: scripts/deploy/lib/smoke-gate.sh:89

Evidence: env knobs the gates still read, and whether they flip FAIL→PASS/WARN.

| var | default | still flips a lie to ship? |
|---|---|---|
| `DEMO_ALT_GATE_ENFORCE` | `1` | YES. `=0` turns coverage FAIL into WARN when `with_alt>0`. Provenance and `with_alt=0` stay locked. |
| `DEMO_ALT_MIN_COVERAGE_PCT` | `95` | YES at the floor. `=50` is a real PASS (not WARN) for 50/100 empty. Values `<50`, non-numeric, whitespace, `08` FAIL closed. `050` is decimal 50 here (`[ 050 -lt 50 ]` rc=1). |
| `DEMO_ALT_MIN_COVERAGE_FLOOR` | (unset) | NO. No longer read. `FLOOR=0 PCT=0` on 0/100 still `smoke_fail=1`. |

Pipeline (functions copied from `sync-demo.sh` `emit_alt_gate` + counting block):

```
$ DEMO_ALT_GATE_ENFORCE=0 DEMO_ALT_MIN_COVERAGE_PCT=95
# 60 usable trusted real captions, 40 empty
PASS demo alt population (header=100 body=100)
WARN demo alt coverage (60/100 = 60%, need 95%) (enforcement disabled via DEMO_ALT_GATE_ENFORCE=0)
PASS demo alt provenance
smoke_fail=0

$ DEMO_ALT_GATE_ENFORCE=1 DEMO_ALT_MIN_COVERAGE_PCT=50
# 50 usable trusted real captions, 50 empty
PASS demo alt population (header=100 body=100)
PASS demo alt coverage (50/100 = 50%, need 50%)
PASS demo alt provenance
smoke_fail=0

$ DEMO_ALT_GATE_ENFORCE=0 DEMO_ALT_MIN_COVERAGE_PCT=0   # empty library, control
FAIL demo alt coverage (0/100 = 0%, need 0%)
FAIL demo alt provenance (no alt text published; nothing to certify)
smoke_fail=1
```

Command line that ships a half-empty demo without the hatch:

```
DEMO_ALT_MIN_COVERAGE_PCT=50 scripts/deploy/sync-demo.sh
```

Command line that ships 40 empty alts as WARN:

```
DEMO_ALT_GATE_ENFORCE=0 scripts/deploy/sync-demo.sh
```

Failure scenario: 50/100 published images have empty alt; operator sets `DEMO_ALT_MIN_COVERAGE_PCT=50` (documented as "operators may raise this bar"; the floor is also a lower bound they can sit on). Coverage prints PASS. Deploy exit 0. Public demo has empty alt on half the library.

Canon: SECD-08, RLSE-08, CLM-04

Suggested fix: keep the floor as a hard constant *and* stop injecting `DEMO_ALT_MIN_COVERAGE_PCT` below the shipped default 95 (raise-only); or drop the ENFORCE hatch for coverage entirely.

### R4-04 | severity: medium | file: apps/prototype-wp-alt-context/src/api/class-api.php:323

Evidence: `register_rest_field('attachment','acx_alt_provenance')` is read-only (`no update_callback`, schema `readonly`, properties exactly `adapter` + `model_id`, `additionalProperties: false`, context `view`/`embed`/`edit`). The getter projects stored `_acx_description_provenance` with no signature, no allowlist, no comparison to the live producer:

```
$adapter = trim($provenance['adapter'])   # class-api.php:330-332
return array('adapter' => $adapter, 'model_id' => $model_id);
```

Absent/empty/whitespace adapter → `null`. Extra envelope keys (`image_hash`, `alt_text_draft`, …) are dropped. JSON-string meta is `json_decode`d then projected. A hand-written meta row `adapter=florence_small` is indistinguishable from a real florence_small write.

Anonymous live GET already works (no auth on `/wp/v2/media`):

```
$ curl -sS --max-time 15 'https://demo.altcontext.com/wp-json/wp/v2/media?per_page=2&_fields=id,alt_text,acx_alt_provenance'
HTTP/2 200
x-wp-total: 100
[{"id":104,"alt_text":""},{"id":103,"alt_text":""}]
```

The live plugin does not yet emit `acx_alt_provenance` (field omitted, not `null`). After this branch deploys, a forged meta write would appear on that same unauthenticated GET. PHPUnit for `AcxAltProvenanceRestFieldTest` could not be run here (`vendor/bin/phpunit` missing).

Failure scenario: site owner (or any process with `update_post_meta`) stamps trusted adapter names onto canned or empty-provenance alts. Gate A believes the REST field. Combined with R4-01/R4-02 this is the write path that ships the lie. What the gate actually proves: "the public media payload *claims* a trusted adapter name", not "the caption was produced by that adapter".

Canon: PROV-10, rg-015, SECD-08

Suggested fix: Gate A should require adapter ∈ trusted *and* byte-equal to the live `/health/detailed` producer, one token per item, no whitespace; treat postmeta as a claim.

### R4-05 | severity: medium | file: infra/oci/demo/lib/describe-gate.sh:65

Evidence: `extract_probed_description_adapter` accepts any 2xx and takes the last `"description_adapter"\s*:\s*"..."` substring in the body. It is not a JSON top-level parse.

```
$ extract_probed_description_adapter 200 '{"status":"ok","description_adapter":"florence_small"}'
florence_small
$ extract_probed_description_adapter 401 '{"description_adapter":"florence_small"}'
<empty>    # then classify_describe_gate '' 100 0 => BLOCK
$ extract_probed_description_adapter 000 ''
<empty>    # BLOCK
$ extract_probed_description_adapter 200 '{"description_adapter":null}'
<empty>    # BLOCK
$ extract_probed_description_adapter 200 '{"status":"ok"}'
<empty>    # BLOCK
$ extract_probed_description_adapter 200 'not-json'
<empty>    # BLOCK
$ extract_probed_description_adapter 301 '{"description_adapter":"florence_small"}'
<empty>    # BLOCK (bootstrap curl has no -L)
$ extract_probed_description_adapter 200 '<html>"description_adapter": "florence_small"</html>'
florence_small
$ extract_probed_description_adapter 200 '{"description_adapter":"seeded","meta":{"description_adapter":"florence_small"}}'
florence_small
$ extract_probed_description_adapter 200 'not json but "description_adapter": "florence_small" appears'
florence_small
```

Live curl against a closed port and a 2s sleeper, using the same `curl --max-time` / `|| code=000` shape as `bootstrap-wp.sh:181-184`:

```
# connection refused 127.0.0.1:1
refused code=000 extracted=  gate=BLOCK
# --max-time 2 against a 30s sleeper
timeout code=000 elapsed=2s extracted=  gate=BLOCK
# 301, no -L
redirect-no-L code=301 extracted=   # BLOCK
```

`bootstrap-wp.sh:245` `exit 1` on BLOCK. Unexpected name `seeded` BLOCKs. HTML *without* the quoted pattern BLOCKs.

Failure scenario: any 2xx body that contains the quoted pattern anywhere (WAF/HTML error page, nested key, comment) makes `ADAPTER_PROFILE=florence_small` and `classify_describe_gate` RUN/RUN_FORCE even when the real producer is `seeded`. Exact pool captions then have to get past smoke (R4-01 is that path). The describe gate's comment claims "top-level JSON string field" and "NEVER invents a fallback"; the sed invents a profile from a substring.

Canon: RLSE-08, CLM-04, rg-015

Suggested fix: parse JSON (python/jq on the bootstrap host, or a tighter `^`/`$` top-level pattern) and BLOCK unless the top-level value is exactly one trusted token.

## Checks I ran

- `bash scripts/deploy/tests/test-smoke-gate.sh` → exit 0, `all assertions passed`
- `bash infra/oci/demo/tests/test-describe-gate.sh` → exit 0, `all assertions passed`
- Direct `classify_alt_coverage` matrix: floor 50 inclusive PASS; 49 FAIL; `0` FAIL; non-numeric/`+50`/`50.5`/`1e2`/whitespace FAIL; `08` FAIL; `050`/`095`/`0100` treated as decimal on this bash; 999999 FAIL; `100 50 50` PASS
- Direct `classify_alt_identity` matrix: empty/whitespace blob + usable>0 FAIL; usable `''`/`-5`/`+5`/`08`/`1e3`/` 3 ` FAIL; glob `*`/`?`/`[a-z]` FAIL; mixed `florence_small seeded` FAIL; pad x100 PASS; n=0 + trusted blob PASS (unused: sync-demo does not call provenance at with_alt=0)
- Undefined `is_trusted_describe_profile` (source fixture-denylist + smoke-gate only, `set -euo pipefail`): `command not found` on line 173, function prints FAIL, script continues (`still_running=1`). Fail-closed, not fail-open.
- ADAPTERJSON scrape bodies: compact, pretty, `"adapter":null`, missing key, provenance null, seeded, JSON-escaped `"adapter"` inside `alt_text`, nested extra `adapter`, `\u0065` escape, escaped quote, padded value, 99-null+1 trusted, comma-fixture+pad
- Gate B corpus: exact/lower/spaces/prefix/suffix/wrap/ellipsis/trailing `?`/`!`/tab/newline/CRLF still denied; comma/semicolon/emdash/internal period/NBSP/ZWSP/homoglyph/non-breaking hyphen not denied
- Drift guard against temp copies of `seeded_adapter.py` (tree not mutated): R3 `'caption':` now `extracted=7 true_pool=8`; 9th `"caption":` → 9==9 then classify of sentinel would be PASS (suite red); append-built pool `true_pool=0`; dict comprehension `NOT_TUPLE:Call`; nested list `8 != 1`; f-string sed-fails that line; implicit concat extracted first literal (fixture) while AST value is fixture+suffix (live Gate B still substring-denies); duplicate keys: sed greedy last = fixture, count 8==8; homoglyph in pool classifies PASS (suite would go red — guard catches source drift, not live homoglyph alts)
- Probe: refused/timeout/401/500/null/missing/invalid JSON/empty/array/boolean/301-no-L BLOCK; 200 HTML-with-quotes / nested-last / non-JSON substring extract florence_small
- `apps/prototype-description-service/scripts/docker-entrypoint.sh:107` `exec uvicorn api.main:app --host 0.0.0.0 --port 8000` (no `--workers`). Caddy `reverse_proxy prod-api:8000` / `demo-wp:80`. No cache directive on `/wp-json`. Live media response: `via: 1.1 Caddy`, no `cache-control`
- `register_health_probes` closes over `DescriptionSettings().profile.value` once (`api/main.py:356-357,492`). `get_description_adapter()` constructs `DescriptionSettings()` per call (`deps.py:169`) from `os.environ.get("ACX_DESCRIPTION_ADAPTER", "seeded")`. No in-process `os.environ["ACX_DESCRIPTION_ADAPTER"] =` write in the service. Default topology is 1 worker / 1 replica
- `sync-demo.sh` order: bootstrap (if `PLUGIN_ZIP`) → pre-promote probe → Caddy promote → smoke. Describe cannot run after the smoke sample. Smoke `_fields=id,alt_text,acx_alt_provenance`
- `bootstrap-wp.sh` BLOCK path contains `exit 1`. Message names "description SERVICE profile", does not contain `Set ACX_DESCRIPTION_ADAPTER to one of`. `env_get ACX_DESCRIPTION_ADAPTER` is absent
- Live `https://demo.altcontext.com/wp-json/wp/v2/media?per_page=2&_fields=id,alt_text,acx_alt_provenance` → HTTP 200, `x-wp-total: 100`, body `[{"id":104,"alt_text":""},{"id":103,"alt_text":""}]` (empty alt, field not deployed yet). Today's library would FAIL these gates on coverage + provenance-empty

## What I could NOT falsify

- Empty 0/100 library cannot ship. `DEMO_ALT_GATE_ENFORCE=0` and `DEMO_ALT_MIN_COVERAGE_PCT=0` still leave `smoke_fail=1` (coverage non-overridable at `with_alt=0` + provenance FAIL closed). R1-01/R1-02 as originally reported are closed.
- Exact `_FIXTURE_POOL` sentences, including `antonio_banderas_10.` prefix, lowercase, dropped period, extra internal ASCII spaces, trailing `.!?`, and prefix/suffix wrappers, still FAIL Gate B.
- `adapter=seeded` (or any untrusted token) in the scrape blob FAILs Gate A. Provenance `emit_alt_gate` is hard-coded overridable=0.
- Missing `acx_alt_provenance` / `"adapter":null` / empty blob with `usable_count>0` FAILs Gate A (plugin-predate path is fail-closed).
- Deleting or reordering the `cat describe-gate.sh` so `is_trusted_describe_profile` is undefined FAILs Gate A (`command not found` → `if !` → FAIL). Not fail-open.
- Coverage `min_pct` below 50, non-numeric, negative, `+50`, whitespace, `08` FAIL closed. `DEMO_ALT_MIN_COVERAGE_FLOOR` cannot override.
- Probe connection refused, timeout, 401, 500, missing field, null, object, array, boolean, invalid JSON, empty body, 301 without `-L` all BLOCK, and bootstrap `exit 1`s on BLOCK.
- R3-01 `'caption':` survivor is dead: extracted count must equal `len(_FIXTURE_POOL)`. Append / comprehension / nested-list / extra 9th `"caption":` go red. I could not construct a silent pool mutation whose extracted strings still FAIL provenance while the live Python caption would PASS smoke.
- Default demo topology cannot split-brain the probe vs producer: one uvicorn worker, one Caddy upstream. Closed-over probe vs per-call `DescriptionSettings()` would diverge only if `ACX_DESCRIPTION_ADAPTER` were mutated in-process; I found no such write. A restart re-registers both.
- Caddy does not cache `/wp-json`. Smoke runs after bootstrap. No path where describe runs after the smoke sample.
- Bootstrap no longer prints `Set ACX_DESCRIPTION_ADAPTER to one of`. Following `secrets/.env` `ACX_DESCRIPTION_ADAPTER=` does not change the probe (bootstrap does not `env_get` it).
- REST getter does not leak extra provenance keys. `alt_text` containing JSON-escaped `"adapter": "florence_small"` did not inject a trusted token (backslash breaks the grep). Unicode-escaped adapter values FAIL closed (false FAIL, not false PASS).
- Live anonymous media list returns all 100 ids; unauthenticated hiding is not the current demo.
- `classify_alt_text_usable` still PASSes 15-letter gibberish (`abcdefghijklmno`). No new interaction: gibberish still needs Gate A trusted identity *and* Gate B non-fixture to ship, same as any other 15+ letter string. Not re-reported (DEMOLIVE-9-R1-03D).
