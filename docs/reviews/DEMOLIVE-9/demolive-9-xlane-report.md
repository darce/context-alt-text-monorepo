# DEMOLIVE-9 XLANE-02/03 report

Lane `demolive-9` on `feature/demolive-9`. Trial-merge tree. Four specified edits plus one guard fix so M2 is actually red.

## Edits

### Edit 1 — concatenate canonical denylist ahead of smoke-gate

`scripts/deploy/sync-demo.sh:45` defines `FIXTURE_DENYLIST_LIB`.
`scripts/deploy/sync-demo.sh:47` adds it to the source existence-check loop.
`scripts/deploy/sync-demo.sh:196-197` emit it immediately before the smoke-gate lib:

```
cat "$FIXTURE_DENYLIST_LIB"
cat "$SMOKE_GATE_LIB"
```

Remote heredoc cannot `source` a sibling; concatenation is the ship path.

### Edit 2 — smoke-gate delegates; tests source denylist first

`scripts/deploy/lib/smoke-gate.sh:7-10` header: arms live in `fixture-denylist.sh`; `sync-demo.sh` concatenates it ahead of this file.
`scripts/deploy/lib/smoke-gate.sh:136-156` `classify_alt_provenance` keeps FAIL-on-empty, then delegates to `normalize_fixture_sample` / `fixture_sample_is_denied`. Eight inline `case` arms and the inline normalizer deleted.

`scripts/deploy/tests/test-smoke-gate.sh:9-15` sources `fixture-denylist.sh` first; missing file `exit 1` (never skip).
`infra/oci/demo/tests/test-describe-gate.sh:170-175` same hard-FAIL source before `smoke-gate.sh`.

### Edit 3 — no third copy may grow back

`scripts/deploy/tests/test-smoke-gate.sh:140-141`:

```
assert_eq "smoke-gate.sh has no inline fixture-caption case arms" \
    "0" "$(grep -c 'a close-up of a small object' ... || true)"
```

Existing R1-02B floor pins and `seeded_adapter.py` drift guard left in place.

### Edit 4 — cross-gate bind is unconditional

`infra/oci/demo/tests/test-describe-gate.sh:221-222`: `assert_eq "corpus live-smoke ${label}"` with no `else` deferred hatch.
`smoke_gate_normalizes` helper deleted.

**Guard fix (M2 would otherwise stay green).** Restoring the `else` hatch still prints `ok ... deferred` and would exit 0. Pins sit *outside* `assert_corpus_row`:

- `infra/oci/demo/tests/test-describe-gate.sh:181-182` live `classify_alt_provenance` on a lowercased close-up must be FAIL.
- `infra/oci/demo/tests/test-describe-gate.sh:185-186` this test file must not contain the DEMOLIVE-6-era hatch phrase.

## Green suites

Both from the worktree root after the four edits + guard fix. Mutants below were applied, recorded, and reverted before these runs.

### `bash scripts/deploy/tests/test-smoke-gate.sh`

Exit code: **0**

Tail:

```
ok   R1-02B sync-demo.sh does not inject DEMO_ALT_MIN_COVERAGE_FLOOR
ok   R1-02B classify_alt_coverage does not read DEMO_ALT_MIN_COVERAGE_FLOOR
ok   R1-02B counting block FLOOR=0 PCT=0 empty-alt 0/100 leaves smoke_fail=1

all assertions passed
```

88 `ok` lines, including `smoke-gate.sh has no inline fixture-caption case arms` and `drift: extracted 8 == pool length 8`.

### `bash infra/oci/demo/tests/test-describe-gate.sh`

Exit code: **0**

Tail:

```
ok   bootstrap handles RUN_FORCE
ok   RUN_FORCE invokes --write --force --limit=100
ok   CLI --force flag exists before wiring

all assertions passed
```

118 `ok` lines, including unconditional `corpus live-smoke *` rows (no `deferred`) and both XLANE-02 pins.

## Mutants (TEST-15)

Each mutant applied, owning suite(s) re-run, exact FAIL line recorded, then **reverted**. Working tree after revert matches the green edits above.

| mutant | suite | exact assertion that failed | reverted? |
| --- | --- | --- | --- |
| M1 delete `*"a close-up of a small object on a neutral background"*` arm from `fixture-denylist.sh` | `test-smoke-gate.sh` exit 1 | `FAIL alt provenance live seeded draft on demo media id 5: expected FAIL, got PASS` (also `FAIL alt provenance fixture: close-up object` and `FAIL drift: pool caption classified FAIL (A close-up of a small object on a neutral background.)`) | yes |
| M1 same | `test-describe-gate.sh` exit 1 | `FAIL corpus describe punctuated fixture: expected FAIL, got PASS` (29 failures; also `FAIL fixture_sample_is_denied bodies drifted between describe-gate.sh and fixture-denylist.sh` and `FAIL corpus live-smoke punctuated fixture: expected FAIL, got PASS`) | yes |
| M2 restore `else` deferral in `test-describe-gate.sh` **and** regress `classify_alt_provenance` to `case "$1" in *"A close-up of a small object on a neutral background."*)` | `test-describe-gate.sh` exit 1 | `FAIL XLANE-02 live-smoke lowercased close-up is FAIL: expected FAIL, got PASS` **and** `FAIL XLANE-02 live-smoke bind has no deferral hatch: expected 0, got 1` | yes |
| M3 re-add one literal fixture-caption `case` arm (`*"a close-up of a small object on a neutral background"*`) to `smoke-gate.sh` | `test-smoke-gate.sh` exit 1 | `FAIL smoke-gate.sh has no inline fixture-caption case arms: expected 0, got 1` | yes |

M2 note: corpus `live-smoke` rows still printed `ok ... deferred` under the restored hatch (the original XLANE-02 leak). The two pins outside `assert_corpus_row` are what turned the suite red. Without those pins, M2 exited 0.

## Could not falsify

- The remaining two copies (`fixture-denylist.sh` canonical vs inlined bodies in `describe-gate.sh`) are still bound by the existing `extract_fn` comparison. That guard was not re-mutated here.
- `describe-gate.sh` still ships an inlined copy (SCP standalone). That is the designed second copy, not a third.
- M2 as specified (restore `else` + exact-match arm) does **not** fail `assert_eq "corpus live-smoke ..."` — the hatch swallows it. Falsified only via the extra pins. Do not delete those pins.
- Empty-sample policy difference (smoke FAIL vs describe UNKNOWN) was not mutated; corpus empty-sample row stayed green.
