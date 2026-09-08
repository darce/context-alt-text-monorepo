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

---

# R1-01B

Make an all-empty demo un-shippable. Round 1 made provenance non-overridable for canned captions; this round closes the empty-library half. `DEMO_ALT_GATE_ENFORCE=0` can no longer certify 0/100 empty alt as green.

## Edits

### Edit 1 — nothing-measured must fail closed

`scripts/deploy/sync-demo.sh:347` (was L334 SKIP echo):

```
emit_alt_gate FAIL "demo alt provenance (no alt text published; nothing to certify)" 0
```

Non-overridable (`0`), same as the reached branch at L345. `classify_alt_provenance` already FAILs an empty sample; the caller no longer contradicts that with a silent SKIP.

### Edit 2 — entirely-empty library cannot be waived

`scripts/deploy/sync-demo.sh:325-330` (was L317 always-overridable coverage):

```
cov_overridable=1
case "$with_alt" in
  *[!0-9]*|'') cov_overridable=0 ;;
  0) cov_overridable=0 ;;
esac
emit_alt_gate "$verdict" "$cov_msg" "$cov_overridable"
```

`scripts/deploy/sync-demo.sh:188-197` header: hatch is for a PARTIALLY described demo. "we described nothing" / "we cannot count" fail closed even under `DEMO_ALT_GATE_ENFORCE=0`. Population at L308 stays overridable (header/body mismatch is a probe limitation).

### Edit 3 — pin the emit/override composition

`scripts/deploy/tests/test-smoke-gate.sh:308` `run_alt_pipeline` duplicates the three emit_alt_gate calls and `smoke_fail` accumulation from the remote heredoc. Not extracted by regex.

Pins:

- header=100 body=100 with_alt=0 ENFORCE=0 → smoke_fail=1, coverage FAIL not WARN, provenance FAIL not SKIP (L373-381)
- same, ENFORCE=1 → smoke_fail=1 (L385-387)
- with_alt=100 real caption → smoke_fail=0 (L391-393)
- with_alt=60 ENFORCE=0 → smoke_fail=0 (L397-399) — partial coverage still waivable
- with_alt=100 fixture caption ENFORCE=0 → smoke_fail=1 (L403-405) — provenance lock from R1-01

Source pins on `sync-demo.sh` itself: coverage emit uses `"$cov_overridable"`; no SKIP echo; `cov_overridable=1` present; header says PARTIALLY described.

**The harness duplicates `sync-demo.sh` composition.** That is the only option that does not parse the heredoc by regex. Drift risk is real: if the production composition changes and the harness does not, the five pipeline pins stay green. The source pins above are the only lock on the production file. Reviewer must weigh that cost. Do not pretend the test reads the real script.

Exit-status-only cannot independently red M1 vs M2: each edit alone fail-closes the empty library (`smoke_fail=1`). The suite therefore also pins the FAIL log lines (coverage not waived; provenance FAIL closed) so each hole has its own assertion.

## Green suites

Both from the worktree root after the three edits + mutant revert.

### `bash scripts/deploy/tests/test-smoke-gate.sh`

Exit code: **0**

Tail:

```
ok   R1-01B live empty library ENFORCE=0 exits non-zero
ok   R1-01B live empty library ENFORCE=0 coverage is FAIL (not waived)
ok   R1-01B live empty library ENFORCE=0 provenance is FAIL closed
ok   R1-01B live empty library ENFORCE=1 exits non-zero
ok   R1-01B full real captions exit zero
ok   R1-01B partial coverage 60/100 ENFORCE=0 still ships
ok   R1-01B fixture captions ENFORCE=0 still blocked (provenance locked)

all assertions passed
```

97 `ok` lines.

### `bash infra/oci/demo/tests/test-describe-gate.sh`

Exit code: **0**

Tail:

```
ok   bootstrap handles RUN_FORCE
ok   RUN_FORCE invokes --write --force --limit=100
ok   CLI --force flag exists before wiring

all assertions passed
```

118 `ok` lines. No regression of the round-1 smoke-gate bind.

## Mutants (TEST-15)

Each mutant applied to **both** `sync-demo.sh` and the duplicated harness (otherwise composition assertions would stay green — they do not read the production file). Owning suite re-run, exact FAIL line recorded, then **reverted**. Working tree after revert matches the green edits above.

| mutant | exact assertion that failed | exit code | reverted? |
| --- | --- | --- | --- |
| M1 restore `echo "SKIP demo alt provenance (no alt text published)"` | `FAIL R1-01B live empty library ENFORCE=0 provenance is FAIL closed: expected FAIL demo alt provenance (no alt text published; nothing to certify), got SKIP demo alt provenance (no alt text published)` (also `FAIL R1-01B empty provenance still a SKIP echo (must FAIL closed)`). Empty-library `exits non-zero` stayed green — Edit 2 still fail-closes coverage. | 1 | yes |
| M2 hardcode coverage overridable back to `1` | `FAIL R1-01B live empty library ENFORCE=0 coverage is FAIL (not waived): expected FAIL demo alt coverage (0/100 = 0%, need 95%), got WARN demo alt coverage (0/100 = 0%, need 95%) (enforcement disabled via DEMO_ALT_GATE_ENFORCE=0)` (also coverage emit/`cov_overridable` source pins). Empty-library `exits non-zero` stayed green — Edit 1 still fail-closes provenance. | 1 | yes |
| M3 coverage non-overridable unconditionally (`cov_overridable=0`) | `FAIL R1-01B partial coverage 60/100 ENFORCE=0 still ships: expected 0, got 1` (also `FAIL R1-01B coverage override is conditional (cov_overridable)`). | 1 | yes |

M3 proves the suite would catch a fix that breaks the legitimate use of the knob, not just one that leaves the hole open.

## Could not falsify

- Live `https://demo.altcontext.com` was not probed; composition used canned header/body/with_alt triples. The 0/100 ENFORCE=0 case is the live-demo shape, not a live HTTP call.
- Non-numeric `with_alt` fail-closed path in the `case` was not mutated separately from `with_alt=0`.
- Population overridable=1 (L308) was not mutated; work order says leave it.
- Mutating **only** `sync-demo.sh` (leaving the harness fixed) does **not** turn the five pipeline pins red. That is the duplicated-harness drift: source pins would still fail (SKIP echo / `cov_overridable`), but the named "exits non-zero" cases would not. Falsified only by mutating the harness in lockstep. Do not delete the source pins.
