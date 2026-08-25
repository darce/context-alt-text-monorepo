# DEMOLIVE-9 y — raise-only coverage floor + pin the cat order

Closes R2-06 (DEMO_ALT_MIN_COVERAGE_PCT was sit-on-able at 50) and R2-04
(the three-library remote-heredoc order was unasserted).

Part 1 commit: `df1b0c8afc241f824d8fb587862f880f530568da`
(`fix(DEMOLIVE-9): coverage floor is the 95 default, raise-only`).

## What changed

`classify_alt_coverage` now uses `local floor=95`. The shipped default **is**
the floor: `DEMO_ALT_MIN_COVERAGE_PCT` may only raise the bar above 95, and
any value below 95 fails closed. `DEMO_ALT_MIN_COVERAGE_PCT=50` no longer
prints PASS for a half-empty library.

`test-smoke-gate.sh` pins the remote heredoc cat order by reading
`sync-demo.sh` (grep + sed + paste; the file is not sourced). Expected
sequence: `DESCRIBE_GATE_SRC FIXTURE_DENYLIST_LIB SMOKE_GATE_LIB`.

## Suite

| suite | command | exit | count |
| --- | --- | --- | --- |
| smoke-gate | `bash scripts/deploy/tests/test-smoke-gate.sh` | `0` | `133` `ok` lines, then `all assertions passed` |

## Flipped expectations

Existing assertions whose expected value changed. Labels were updated; tests
were not deleted.

| assertion (new label) | was | now | why |
| --- | --- | --- | --- |
| `alt coverage 2/3 min_pct 60 below default floor 95` | PASS | FAIL | min_pct 60 is below 95; the old integer-math PASS is unreachable |
| `alt coverage 100 100 50 below default floor 95, full coverage` | PASS | FAIL | 50 is no longer a legal floor |
| `alt coverage 50/100 min_pct 50 below default floor 95` | PASS | FAIL | 50/100 at min_pct=50 used to equal the old floor |
| `TEST-15 empty-alt mix coverage at min_pct=50` | PASS | FAIL | 10/20 at min_pct=50 used to PASS coverage; 50 now fails closed |

Still FAIL (labels only): min_pct 0, 49, `1/3` at 60, `49/100` at min_pct 50.

## TEST-15 mutation proof

Each mutation applied alone, suite re-run, file restored. `git status` after
restore was clean of mutations (only the intended R2-04 pin remained dirty).

| mutation | verbatim first FAIL line | failed | exit |
| --- | --- | --- | --- |
| M1 — `local floor=95` → `local floor=50` in `classify_alt_coverage` | `FAIL alt coverage 2/3 min_pct 60 below default floor 95: expected FAIL, got PASS` | 4 | `1` |
| M2 — swap `cat "$DESCRIBE_GATE_SRC"` and `cat "$SMOKE_GATE_LIB"` | `FAIL R2-04 remote heredoc cat order: expected DESCRIBE_GATE_SRC FIXTURE_DENYLIST_LIB SMOKE_GATE_LIB, got SMOKE_GATE_LIB FIXTURE_DENYLIST_LIB DESCRIBE_GATE_SRC` | 1 | `1` |

M1 also reddened:

- `FAIL alt coverage 100 100 50 below default floor 95, full coverage: expected FAIL, got PASS`
- `FAIL alt coverage 50/100 min_pct 50 below default floor 95: expected FAIL, got PASS`
- `FAIL TEST-15 empty-alt mix coverage at min_pct=50: expected FAIL, got PASS`

## Reversal assertion was not constructible

The second R2-04 assertion (concatenate the three libraries in reverse order,
source in a subshell, expect `fixture_sample_is_denied` on a known fixture
caption to give the **wrong** answer) is not constructible today.

Evidence: `cat smoke-gate.sh fixture-denylist.sh describe-gate.sh` then
`source` yields `DENIED` for
`A close-up of a small object on a neutral background.`, same as the shipped
order. The suite already pins
`drift: fixture_sample_is_denied bodies agree (comments/blanks stripped)`
between describe-gate and fixture-denylist. Reversal is observationally
equivalent. Only the file-order pin is kept. Do not fake a behavioral FAIL.
