# DEMOLIVE-6 — smoke alt-gate certify-a-lie holes

Lane `demolive-6`. Four holes closed. No existing assertion weakened.
Suite: `bash scripts/deploy/tests/test-smoke-gate.sh`
Post-revert: `all assertions passed`, exit 0. No mutation left in the tree.

## R1-01 provenance FAIL is non-overridable

### Files / lines
- `scripts/deploy/sync-demo.sh`
  - L179–189 header: override covers empty alt, never canned captions
  - L261–271 `emit_alt_gate` takes `overridable` (`${3:-0}`); WARN demotion only when `overridable=1` AND `DEMO_ALT_GATE_ENFORCE=0`
  - L300 population `emit_alt_gate ... 1`
  - L317 coverage `emit_alt_gate ... 1`
  - L332 provenance `emit_alt_gate ... 0`
- `scripts/deploy/tests/test-smoke-gate.sh` L183–233 call-site + behavioral pins

### New assertions
- Population/coverage call sites pass `overridable=1`
- Provenance call site passes `overridable=0`
- Header contains `The override covers empty alt, never canned captions.`
- `DEMO_ALT_GATE_ENFORCE=0` + coverage FAIL + overridable=1 → WARN, `smoke_fail=0`
- `DEMO_ALT_GATE_ENFORCE=0` + provenance FAIL + overridable=0 → FAIL, `smoke_fail=1`
- Missing third arg defaults fail-closed (`overridable=0`)

### TEST-15
- Mutation: restore old `emit_alt_gate` condition
  `if [ "$gate_verdict" = "FAIL" ] && [ "${DEMO_ALT_GATE_ENFORCE:-1}" = "0" ]; then`
  (drop the `overridable=1` conjunct so ENFORCE=0 silences every sub-gate, including provenance)
- Command: `bash scripts/deploy/tests/test-smoke-gate.sh`
- Exit: 1
- Verbatim FAIL:

```
FAIL R1-01 provenance FAIL non-overridable under DEMO_ALT_GATE_ENFORCE=0: expected FAIL demo alt provenance (seeded fixture caption detected in 100 published alt texts)
smoke_fail=1, got WARN demo alt provenance (seeded fixture caption detected in 100 published alt texts) (enforcement disabled via DEMO_ALT_GATE_ENFORCE=0)
smoke_fail=0
```

- Revert: restore `overridable=1` conjunct
- Re-green: `all assertions passed`, exit 0

## R1-02 min_pct floor fail-closed

### Files / lines
- `scripts/deploy/lib/smoke-gate.sh`
  - L17–22 header documents floor
  - L58–73 `classify_alt_coverage`: `DEMO_ALT_MIN_COVERAGE_FLOOR` default 50; non-numeric floor FAIL; `min_pct < floor` FAIL
- `scripts/deploy/sync-demo.sh` L195 ships `DEMO_ALT_MIN_COVERAGE_FLOOR` to the VM
- `scripts/deploy/tests/test-smoke-gate.sh` L65–79

### New assertions
- `classify_alt_coverage 100 0 0` → FAIL (was `0 >= 0` PASS)
- `classify_alt_coverage 100 100 49` → FAIL (100% coverage cannot launder a sub-floor threshold)
- `classify_alt_coverage 100 50 50` → PASS (inclusive floor)
- `classify_alt_coverage 100 49 50` → FAIL
- `DEMO_ALT_MIN_COVERAGE_FLOOR=80` then `classify_alt_coverage 100 70 70` → FAIL

### TEST-15
- Mutation: delete the `min_pct < floor` block in `classify_alt_coverage`
- Command: `bash scripts/deploy/tests/test-smoke-gate.sh`
- Exit: 1
- Verbatim FAIL:

```
FAIL alt coverage min_pct 0 below default floor (certify-a-lie): expected FAIL, got PASS
```

Also red (same mutation):
```
FAIL alt coverage 100/100 but min_pct 49 below floor 50: expected FAIL, got PASS
FAIL alt coverage custom floor 80 rejects min_pct 70: expected FAIL, got PASS
```

- Revert: restore the floor block
- Re-green: `all assertions passed`, exit 0

## R1-03 placeholder alt is not coverage; trivial denylist evasion closed

### Files / lines
- `scripts/deploy/lib/smoke-gate.sh`
  - L108–127 `classify_alt_text_usable`: FAIL empty-after-trim, `< 15` chars, no `[A-Za-z]`
  - L129–184 `classify_alt_provenance`: lowercase, collapse whitespace, strip trailing `.!?`; denylist arms lowercased without trailing punctuation
- `scripts/deploy/sync-demo.sh` L279–290 `with_alt` counts only `classify_alt_text_usable = PASS`
- `scripts/deploy/tests/test-smoke-gate.sh` L102–117 usable + evasion pins; L202–207 wiring pin

Adapter-identity meta is deferred (not attempted).

### New assertions
- usable: empty / whitespace / `.` / single space / 14 letters / 15 digits-no-alpha → FAIL
- usable: 15 letters / real caption → PASS
- provenance still FAIL after lowercase-first-letter, dropped trailing period, extra internal whitespace, trailing `!`
- `sync-demo.sh` contains `classify_alt_text_usable`

### TEST-15 (a) usable
- Mutation: `classify_alt_text_usable` body replaced with `echo PASS` (old: any non-empty JSON string counts)
- Command: `bash scripts/deploy/tests/test-smoke-gate.sh`
- Exit: 1
- Verbatim FAIL (placeholder the review replayed):

```
FAIL usable alt period placeholder: expected FAIL, got PASS
FAIL usable alt single space: expected FAIL, got PASS
```

Also red: empty, whitespace-only, 14 letters, 15 digits-no-alpha.

- Revert: restore trim / length / alphabetic checks
- Re-green: `all assertions passed`, exit 0

### TEST-15 (b) provenance normalize
- Mutation: remove sample normalization (lowercase / whitespace collapse / trailing `.!?` strip) and restore the first denylist arm to mixed-case with trailing period
- Command: `bash scripts/deploy/tests/test-smoke-gate.sh`
- Exit: 1
- Verbatim FAIL (evasions the review replayed):

```
FAIL alt provenance lowercase first letter still fixture: expected FAIL, got PASS
FAIL alt provenance dropped trailing period still fixture: expected FAIL, got PASS
```

- Revert: restore normalize + lowercase denylist arms
- Re-green: `all assertions passed`, exit 0

## R3-01 drift guard asserts full pool cardinality

### Files / lines
- `scripts/deploy/tests/test-smoke-gate.sh` L143–180
  - `python3` + `ast` on `_FIXTURE_POOL` (AnnAssign or Assign)
  - FAIL closed if parse fails
  - `extracted != true_pool_len` → `FAIL fixture-pool extraction count ${extracted} != pool length ${true_pool_len}`
- Extraction still uses `grep '"caption":'` so a `'caption'` key is a miss the new equality catches

### New assertions
- extracted count equals ast pool length (8 == 8 on current adapter)
- mismatch names both numbers
- existing `extracted -eq 0` FAIL kept

### TEST-15
- Mutation: first `_FIXTURE_POOL` key `"caption"` → `'caption'` in
  `apps/prototype-description-service/scene/application/seeded_adapter.py`
  (valid Python; old `-gt 0` guard would still pass)
- Command: `bash scripts/deploy/tests/test-smoke-gate.sh`
- Exit: 1
- Verbatim FAIL:

```
FAIL fixture-pool extraction count 7 != pool length 8
```

- Revert: restore `"caption"`
- Re-green: `all assertions passed`, exit 0
- Adapter file is unmodified in the final tree
