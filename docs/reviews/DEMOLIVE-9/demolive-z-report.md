# DEMOLIVE-9 z — per-caption fixture matching + classifier exit codes

Closes R3V-01 (corpus-wide token-AND false-denied genuine libraries) and
R2-13 (`classify_*` FAIL paths printed FAIL but returned 0).

Part 1 was already in this tree (`load_alt_counts_from_media_body` /
`classify_alt_provenance` signature). This lane did not rewrite it.
Part 2 + this report are the new work.

## Suite

| suite | command | exit | count |
| --- | --- | --- | --- |
| smoke-gate | `bash scripts/deploy/tests/test-smoke-gate.sh` | `0` | `173` `ok` lines, then `all assertions passed` |

## Part 1 — R3V-01 (already committed; described, not redone)

`classify_alt_provenance` signature:

```
classify_alt_provenance <denied_count> <adapters_blob> <usable_count> [usable_normalized_count]
```

First positional arg is the per-caption fixture signal (count of usable
alts that matched a denylist arm individually), not a concatenated alt
blob. Argument order is unchanged: fixture signal, adapters blob, usable
count, optional usable-normalized count.

`load_alt_counts_from_media_body` evaluates `fixture_sample_is_denied`
on each usable alt as it is read, and sets caller-visible `denied_count`
and `usable_normalized_count` next to `body_total` / `with_alt` /
`adapters` / `sample`. ANY denied caption is a FAIL. A library whose
usable alts are all empty after normalize still FAILs closed (the one
intentional difference from describe-gate UNKNOWN).

### Call sites updated (Part 1)

| file | site | change |
| --- | --- | --- |
| `scripts/deploy/lib/smoke-gate.sh` | `classify_alt_provenance` | first arg is `denied_count` |
| `scripts/deploy/lib/smoke-gate.sh` | `load_alt_counts_from_media_body` | per-caption `denied_count` / `usable_normalized_count` |
| `scripts/deploy/sync-demo.sh` | production heredoc `prov=$(classify_alt_provenance ...)` | passes `"$denied_count"` `"$adapters"` `"$with_alt"` `"$usable_normalized_count"` |
| `scripts/deploy/tests/test-smoke-gate.sh` | every `classify_alt_provenance` call | first arg is `denied_count` or `$(caption_denied_count ...)` |

`caption_denied_count` in the test file keeps the old fixture-caption
assertions load-bearing against the matcher after the argument change.

### Genuine-library regression

Ten genuine captions, none a fixture caption, collectively contain every
content token of the **person / standing / outdoors / greenery** denylist
arm. Token-AND over the concatenated `sample` blob still fires that arm
(`fixture_sample_is_denied "$sample"` returns 0). Per-caption
`denied_count` is 0, so `classify_alt_provenance` PASSes.

The concatenated blob trips the person-standing-outdoors-greenery arm;
the per-caption path does not, because no single caption contains all of
those tokens.

Mirror: the same library plus one real fixture caption
(`A close-up of a small object on a neutral background.`) asserts
`denied_count=1` and provenance FAIL.

## Part 2 — R2-13

Every `classify_*` FAIL path in `smoke-gate.sh` now `return 1`. Every
PASS path `return 0`. `classify_api_probe` WARN returns 0 (WARN is not a
failure). No UNKNOWN verdict exists in this file;
`classify_describe_provenance` is not defined here.

Stdout is unchanged: callers still compare the printed word.

The inner `trusted_out=$(... echo FAIL; exit 0)` in
`classify_alt_identity` is a stdout protocol for that assignment, not a
public FAIL path. It still exits 0 so `set -e` does not abort before the
outer function returns 1.

### Call-site audit (`set -e`)

Verified on GNU bash 5.2.21: `var=$(false)` under `set -euo pipefail`
**aborts**. Command substitution as a function argument does **not**.
`if [ "$(classify_...)" = ... ]` does **not**.

| site | context | verdict |
| --- | --- | --- |
| `smoke-gate.sh` `if [ "$(classify_alt_text_usable "$alt")" = "PASS" ]` | `if` test | SAFE |
| `smoke-gate.sh` `if [ "$(classify_alt_identity ...)" != "PASS" ]` | `if` test | SAFE |
| `smoke-gate.sh` `trusted_out=$(... echo FAIL; exit 0)` | inner stdout protocol | SAFE by design |
| `test-smoke-gate.sh` `assert_eq ... "$(classify_*)"` | function argument | SAFE |
| `test-smoke-gate.sh` `assert_verdict_rc` | `actual_verdict=$("$@") \|\| actual_rc=$?` | SAFE |
| `test-smoke-gate.sh` `run_empty_alt_floor_override` `pop=$(classify_alt_population ...)` | bare assignment, `set -e` | was UNSAFE; `\|\| true` added |
| `test-smoke-gate.sh` `run_empty_alt_floor_override` `verdict=$(classify_alt_coverage ...)` | bare assignment, `set -e` | was UNSAFE; `\|\| true` added |
| `test-smoke-gate.sh` `run_alt_pipeline` `pop=$(classify_alt_population ...)` | bare assignment, `set -e` | was UNSAFE; `\|\| true` added |
| `test-smoke-gate.sh` `run_alt_pipeline` `verdict=$(classify_alt_coverage ...)` | bare assignment, `set -e` | was UNSAFE; `\|\| true` added |
| `test-smoke-gate.sh` `run_alt_pipeline` `prov=$(classify_alt_provenance ...)` | bare assignment, `set -e` | was UNSAFE; `\|\| true` added |
| `test-smoke-gate.sh` `run_alt_pipeline` `identity=$(classify_alt_identity ...)` | bare assignment, `set -e` | was UNSAFE; `\|\| true` added |
| `sync-demo.sh` heredoc `verdict=$(classify_api_probe ...)` (loop) | bare assignment, `set -euo pipefail` | was UNSAFE; `\|\| true` added |
| `sync-demo.sh` heredoc `verdict=$(classify_api_probe ...)` (resample) | bare assignment, `set -euo pipefail` | was UNSAFE; `\|\| true` added |
| `sync-demo.sh` heredoc `verdict=$(classify_demo_probe ...)` | bare assignment, `set -euo pipefail` | was UNSAFE; `\|\| true` added |
| `sync-demo.sh` heredoc `pop=$(classify_alt_population ...)` | bare assignment, `set -euo pipefail` | was UNSAFE; `\|\| true` added |
| `sync-demo.sh` heredoc `verdict=$(classify_alt_coverage ...)` | bare assignment, `set -euo pipefail` | was UNSAFE; `\|\| true` added |
| `sync-demo.sh` heredoc `prov=$(classify_alt_provenance ...)` | **hardest case** — bare assignment, `set -euo pipefail` | was UNSAFE; `\|\| true` added |
| `sync-demo.sh` heredoc `identity=$(classify_alt_identity ...)` | bare assignment, `set -euo pipefail` | was UNSAFE; `\|\| true` added |

`|| true` is not a silent workaround: without it the remote smoke
heredoc aborts on the first FAIL classifier and never reaches later
gates or `exit "$smoke_fail"`. Stdout comparison is the live contract;
the `|| true` keeps that comparison reachable. Named here on purpose.

Dual-channel assertions pin at least one PASS and one FAIL per
classifier (plus api WARN rc=0): printed verdict AND `$?`.

## TEST-15 mutation proof

Each mutation applied alone, suite re-run, file restored. `git status`
after restore was clean of mutations (only the intended R2-13 / report
files remained dirty).

| mutation | verbatim first FAIL line | failed | exit |
| --- | --- | --- | --- |
| M1 — coverage else-arm `echo FAIL; return 1` → `echo FAIL; return` | `FAIL R2-13 coverage FAIL rc: expected 1, got 0` | 1 | `1` |
| M2 — `denied_count` arm → `fixture_sample_is_denied "${sample-}"` (concatenated blob) | `FAIL alt provenance live seeded draft on demo media id 5: expected FAIL, got PASS` | 25 | `1` |

M2 also reddened the load-bearing genuine-library pin (this is the R3V-01 proof):

- `FAIL R3V-01 genuine library provenance PASS: expected PASS, got FAIL`

Bare `"$sample"` under `set -u` aborted early tests with empty stdout
(`got `). `${sample-}` is the same blob match with unset-safe expansion
so the R3V-01 assertion is the one that fires.

M1 proves the new rc pin is load-bearing: stdout still says FAIL, `$?`
goes back to 0, suite exits 1. M2 proves the per-caption arm is
load-bearing: the concatenated blob false-denies the genuine library.
