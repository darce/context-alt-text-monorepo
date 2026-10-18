# demolive-f3 — Gate B content-token denylist (DEMOLIVE-9-R2-01)

Lane `demolive-f3`. Task `DEMOLIVE-9`. Work order a1.

Substring matching after `tr -s '[:space:]' ' '` let a comma, NBSP (U+00A0), em-space (U+2003), or ZWSP (U+200B) inside a seeded caption evade Gate B. Both copies of the matcher now normalize to an alphanumeric skeleton (`LC_ALL=C tr -c 'a-z0-9' ' '`) and require every content token of a denylist arm.

Owned files: `scripts/deploy/lib/fixture-denylist.sh`, `infra/oci/demo/lib/describe-gate.sh`, `infra/oci/demo/tests/test-describe-gate.sh`, this report.

Sibling-lane files (`scripts/deploy/lib/smoke-gate.sh`, `scripts/deploy/sync-demo.sh`, `scripts/deploy/tests/test-smoke-gate.sh`) were not opened or edited. `test-smoke-gate.sh` still passed after the denylist change (drift checks on `normalize_fixture_sample` and `fixture_sample_is_denied` stayed green). It does **not** drift-check `_fixture_tokens_all_present`; `test-describe-gate.sh` now does. If that helper should be bound in the smoke-gate suite too, that is the sibling lane.

## Commits

| SHA | subject |
|---|---|
| `d4a262562583290ae6e855e6c7abcaff2b223a7e` | `fix(DEMOLIVE-9): match fixture captions by content token, not substring` |
| `292fdf1c447c0205b3457ee531f94f967d3ef065` | `test(DEMOLIVE-9): pin Gate B denylist evasion variants (TEST-15)` |

## Matcher

`normalize_fixture_sample`: lowercase, map every non `[a-z0-9]` byte to space, squeeze spaces, strip ends. That one `tr -c` pass kills punctuation, NBSP, ZWSP, em-space, non-breaking hyphen, and every non-ASCII byte. The old trailing-`.!?` strip loop is gone; it is subsumed.

`_fixture_tokens_all_present`: whole-token AND. `fixture_sample_is_denied` runs the eight arms as content-token sets (articles and prepositions dropped). False deny (real caption that uses every content word of an arm) is the safe direction; no softening heuristics.

Function bodies of `normalize_fixture_sample`, `_fixture_tokens_all_present`, and `fixture_sample_is_denied` are byte-identical across the two copies.

## Residual risk

A homoglyph inside a content word (Cyrillic "е" in "pеrson") still evades Gate B, because no token match can see through it. Gate A (trusted adapter identity) is the compensating control. Documented as one comment above the arm list. No homoglyph folding was added.

## Suites (post-fix, with TEST-15 assertions)

| suite | command | exit | `ok` lines | trailer |
|---|---|---|---|---|
| describe-gate | `bash infra/oci/demo/tests/test-describe-gate.sh` | `0` | `170` | `all assertions passed` |
| smoke-gate | `bash scripts/deploy/tests/test-smoke-gate.sh` | `0` | `132` | `all assertions passed` |

First-commit baseline (matcher only, before TEST-15 rows): both suites printed `all assertions passed` and exited 0. describe-gate was 130 `ok` before the new rows; 13 corpus rows × 3 classifiers + 1 helper identity check = 40 added → 170.

## TEST-15 evasion table

`classify_describe_provenance` and `classify_alt_provenance <sample> florence_small 1` (live-smoke Gate B) agree on every row.

| arm | variant | sample | describe | `classify_alt_provenance` |
|---|---|---|---|---|
| person | comma | `a person, standing outdoors near greenery` | FAIL | FAIL |
| person | U+00A0 NBSP for one space | `a person[U+00A0]standing outdoors near greenery` | FAIL | FAIL |
| person | U+2003 em-space for one space | `a person[U+2003]standing outdoors near greenery` | FAIL | FAIL |
| person | uppercase + trailing `!!` | `A PERSON STANDING OUTDOORS NEAR GREENERY!!` | FAIL | FAIL |
| plate | comma | `a plate of food, on a wooden table` | FAIL | FAIL |
| plate | U+00A0 NBSP for one space | `a plate of food[U+00A0]on a wooden table` | FAIL | FAIL |
| plate | U+2003 em-space for one space | `a plate of food[U+2003]on a wooden table` | FAIL | FAIL |
| plate | uppercase + trailing `!!` | `A PLATE OF FOOD ON A WOODEN TABLE!!` | FAIL | FAIL |
| close-up | comma | `a close-up of a small object, on a neutral background` | FAIL | FAIL |
| close-up | U+00A0 NBSP for one space | `a close-up of a small object[U+00A0]on a neutral background` | FAIL | FAIL |
| close-up | U+2003 em-space for one space | `a close-up of a small object[U+2003]on a neutral background` | FAIL | FAIL |
| close-up | uppercase + trailing `!!` | `A CLOSE-UP OF A SMALL OBJECT ON A NEUTRAL BACKGROUND!!` | FAIL | FAIL |
| (negative) | partial overlap, not all tokens | `A person seated at a wooden table beside a window.` | PASS | PASS |

Negative case shares `person` (arm 1) and `wooden`/`table` (arm 2) but not every content token of any arm, so the looser matcher does not swallow it.

## Mutation proof

Temporarily restored `tr -s '[:space:]' ' '` in place of the `LC_ALL=C tr -c 'a-z0-9' ' '` pass in **both** copies (lockstep, so the body-identity checks stayed green). Re-ran `bash infra/oci/demo/tests/test-describe-gate.sh`. Then restored the `tr -c` pass. Lib files had zero diff vs `d4a2625` after restore.

- exit code: `1`
- trailer: `66 assertion(s) failed`
- verbatim first new TEST-15 FAIL line:

```
FAIL corpus describe person comma evasion: expected FAIL, got PASS
```

Each new evasion assertion went red under the same mutant (describe, smoke-sem, and live-smoke). Representative lines:

```
FAIL corpus describe person comma evasion: expected FAIL, got PASS
FAIL corpus describe person nbsp evasion: expected FAIL, got PASS
FAIL corpus describe person em-space evasion: expected FAIL, got PASS
FAIL corpus describe person uppercase trailing-bang evasion: expected FAIL, got PASS
FAIL corpus describe plate comma evasion: expected FAIL, got PASS
FAIL corpus describe close-up comma evasion: expected FAIL, got PASS
```

The negative PASS row stayed PASS under the weaker normalizer (expected; that assertion did not go red). Hyphenated fixture rows (`close-up`) also went red because without `tr -c` the hyphen stays glued, so content tokens `close` and `up` are not found.

Working tree had no leftover mutant at report/commit time.
