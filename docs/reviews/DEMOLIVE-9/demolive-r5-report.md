# demolive-r5 — R2-09 locale-stable alt length, R2-11 loud non-bash guard

Lane `demolive-fr5`. Task `DEMOLIVE-9`. Work order R5.

Owned files touched: `scripts/deploy/lib/smoke-gate.sh`, `scripts/deploy/tests/test-smoke-gate.sh`, `infra/oci/demo/tests/test-describe-gate.sh`. `infra/oci/demo/lib/describe-gate.sh` needed no edit (no `classify_*` signature change; denylist copies untouched).

## Characters vs bytes

**Decision: UTF-8 characters, not bytes.**

`classify_alt_text_usable` already documented a 15-character minimum. `${#text}` does not implement that unit: bash counts characters under a UTF-8 locale and bytes under C/POSIX; dash always counts bytes. `'abcde'` + five U+00E9 is 10 characters / 15 bytes, so the same caption PASS-es on a C/POSIX demo host and FAIL-s on C.UTF-8.

Bytes fail open. They inflate the usable-coverage numerator for short multibyte strings, including the NBSP-padded denylist evasions Gate B already fights. Characters fail closed and match the documented unit.

Measurement lives in `_utf8_character_count` (library helper): `LC_ALL=C awk` counts non-continuation UTF-8 bytes (`not 10xxxxxx`). Independent of ambient `LANG`/`LC_ALL` and of bash vs dash `${#}`. Locale pinning only in the test suite would not fix the production path (`ssh ... bash -se` with no locale in `sync-demo.sh`, which this lane does not own).

`classify_alt_text_usable` signature, argument order, and return codes are unchanged.

## Baseline (before any change)

| suite | command | exit | `ok` count |
|---|---|---|---|
| smoke-gate | `bash scripts/deploy/tests/test-smoke-gate.sh` | `0` | `173` |
| describe-gate | `bash infra/oci/demo/tests/test-describe-gate.sh` | `0` | `182` |

Both printed `all assertions passed`. Matched the work-order expected counts, so this tree is the one the order describes.

## Post-change

| suite | command | exit | `ok` count |
|---|---|---|---|
| smoke-gate | `bash scripts/deploy/tests/test-smoke-gate.sh` | `0` | `178` |
| describe-gate | `bash infra/oci/demo/tests/test-describe-gate.sh` | `0` | `183` |

173 + 5 (3× R2-09 + 2× R2-11) = 178. 182 + 1 (R2-11 self-pin) = 183. Both still `all assertions passed`.

## Finding 1 (R2-09) mutation proof

Mutation: in `classify_alt_text_usable`, replace `n=$(_utf8_character_count "$text"); if [ "$n" -lt 15 ]` with `if [ "${#text}" -lt 15 ]`. Restored after the run.

Command: `bash scripts/deploy/tests/test-smoke-gate.sh`. Exit: `1`. `2 assertion(s) failed`. `176` ok / `2` FAIL.

| assertion | verbatim FAIL line |
|---|---|
| R2-09 10-char/15-byte under LC_ALL=C | `FAIL R2-09 10-char/15-byte under LC_ALL=C: expected FAIL, got PASS` |
| R2-09 locale-independent verdict | `FAIL R2-09 locale-independent verdict: expected PASS, got FAIL` |

`R2-09 10-char/15-byte under LC_ALL=C.UTF-8` stayed `ok` (UTF-8 `${#}` still counts 10 characters → FAIL). The C vs UTF-8 split is the bug; both new pins that require locale-stable FAIL went red. Reverted; helper restored.

## Finding 2 (R2-11) mutation proof

Mutation: delete the `BASH_VERSION` interpreter-guard `if` block from both suites (leave `set -euo pipefail` as the first executable). Restored after the runs.

### `sh` without the guard (the original silent-abort)

```
$ sh scripts/deploy/tests/test-smoke-gate.sh ; echo "sh exit=$?"
scripts/deploy/tests/test-smoke-gate.sh: 6: set: Illegal option -o pipefail
sh exit=2

$ sh infra/oci/demo/tests/test-describe-gate.sh ; echo "sh exit=$?"
infra/oci/demo/tests/test-describe-gate.sh: 7: set: Illegal option -o pipefail
sh exit=2
```

No `ok` / `FAIL` assertion lines. Exit 2 at `set -o pipefail` before any assertion runs.

### `bash` without the guard (the new pins)

`bash scripts/deploy/tests/test-smoke-gate.sh` → exit `1`, `2 assertion(s) failed`:

| assertion | verbatim FAIL line |
|---|---|
| R2-11 smoke suite guards BASH_VERSION before pipefail | `FAIL R2-11 smoke suite guards BASH_VERSION before pipefail: expected guard-before-pipefail, got missing-guard` |
| R2-11 describe suite guards BASH_VERSION before pipefail | `FAIL R2-11 describe suite guards BASH_VERSION before pipefail: expected guard-before-pipefail, got missing-guard` |

`bash infra/oci/demo/tests/test-describe-gate.sh` → exit `1`, `1 assertion(s) failed`:

| assertion | verbatim FAIL line |
|---|---|
| R2-11 describe suite guards BASH_VERSION before pipefail | `FAIL R2-11 describe suite guards BASH_VERSION before pipefail: expected guard-before-pipefail, got missing-guard` |

Guards restored. Both suites green again under bash.

## sh path after the fix (caller-visible message)

```
$ sh scripts/deploy/tests/test-smoke-gate.sh ; echo "sh exit=$?"
FAIL scripts/deploy/tests/test-smoke-gate.sh must run under bash, not sh/dash. Example: bash scripts/deploy/tests/test-smoke-gate.sh
sh exit=2

$ sh infra/oci/demo/tests/test-describe-gate.sh ; echo "sh exit=$?"
FAIL infra/oci/demo/tests/test-describe-gate.sh must run under bash, not sh/dash. Example: bash infra/oci/demo/tests/test-describe-gate.sh
sh exit=2
```

Loud non-zero failure, message on stderr, no assertion output that could be read as a green empty run. Under bash both suites still run normally.

## Could not do

Nothing in scope. `infra/oci/demo/lib/describe-gate.sh` was left unchanged on purpose. `sync-demo.sh` was not edited (lane does not own it); determinism is in the library helper the remote heredoc already concatenates.
