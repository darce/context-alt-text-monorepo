# R5 verdict: fail

Lens: POSIX/dash vs bash, locale/coreutils, unquoted `$adapters_blob`, exit-code resets, and the three-file concatenation contract. Can the merged smoke/describe gates PASS while published alt is still canned or identity-less? Yes: Unicode whitespace evades Gate B behind a trusted adapter (R5-01). Two further fail-opens need extra conditions (glob + cwd, unbound adapter scrape at `min_pct=50`).

## Findings

### R5-01 | severity: high | file: scripts/deploy/lib/fixture-denylist.sh:21

Evidence: `normalize_fixture_sample` folds and squeezes with GNU/POSIX `tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' '`. `tr` is single-byte. `[:space:]` does not match U+00A0 / U+200B / U+2003 under `LC_ALL=C`, `C.UTF-8`, or `en_US.UTF-8`. ASCII tab and CR still collapse. `describe-gate.sh` carries an identical copy; concatenation order does not change this. Verbatim:

```
$ bash -c '. scripts/deploy/lib/fixture-denylist.sh
. infra/oci/demo/lib/describe-gate.sh
. scripts/deploy/lib/smoke-gate.sh
# ascii / tab / cr / nbsp / zwsp / emsp against
# "A person standing outdoors near greenery."
# then fixture_sample_is_denied + classify_alt_provenance florence_small 1'
ascii denied=yes provenance=FAIL
tab   denied=yes provenance=FAIL
cr    denied=yes provenance=FAIL
nbsp  denied=no  provenance=PASS
zwsp  denied=no  provenance=PASS
emsp  denied=no  provenance=PASS
```

Gate A is independently PASS (`florence_small`). Gate B is the only canned-caption detector. AND therefore PASSes.

Failure scenario: publish the seeded fixture sentences with one NBSP (visually identical) behind a trusted adapter. Provenance prints PASS. Coverage counts them as usable. `smoke_fail` stays 0. Public alt is still the canned pool.

Canon: SECD-08, CLM-04, RLSE-08

Suggested fix: Unicode-aware whitespace squeeze (or reject non-ASCII space before the substring match). Pin NBSP/ZWSP/em-space rows in the shared corpus.

### R5-02 | severity: medium | file: scripts/deploy/lib/smoke-gate.sh:172

Evidence: `for adapter in $adapters_blob` is unquoted (word-split + pathname expansion). Command substitution in the blob is **not** evaluated (`$(whoami)` and backticks classify FAIL). A glob **is** expanded against cwd. The remote smoke is `{ cat libs; cat <<'EOF'; } | $SSH bash -se` with no `cd`, so cwd is the SSH login home. `set -f` is not set.

Trusted-only cwd + REST-shaped `"adapter":"*"`:

```
$ mkdir -p /tmp/demolive-r5-attacks/trustedonly
$ touch /tmp/demolive-r5-attacks/trustedonly/florence_small
$ # scrape loop over [{"acx_alt_provenance":{"adapter":"*","model_id":"x"}}]
scraped adapters=[* ]
identity=PASS
provenance=PASS
```

Mixed cwd (`florence_small`, `README`, `seeded`) → identity FAIL (exit 0 from the function, stdout FAIL). Empty cwd → unmatched glob stays literal `*` → FAIL.

Failure scenario: stored adapter `*` (PHP writers refuse empty, not glob characters) plus a login-home whose non-hidden files are only trusted profile names. Default Ubuntu homes with leftover files FAIL-close this glob. The hole is cwd collusion + hostile adapter string.

Canon: SECD-08

Suggested fix: `set -f` around the split, or `read` tokens without globbing. Reject adapter tokens containing metacharacters.

### R5-03 | severity: medium | file: scripts/deploy/lib/smoke-gate.sh:138

Evidence: `classify_alt_text_usable` documents “fewer than 15 characters” then uses `${#text}`. Bash `${#text}` is characters in a UTF-8 locale and bytes in `C`/`POSIX`. Dash is always bytes. Payload `abcde` + five `é` = 10 characters, 15 bytes, contains `[A-Za-z]`:

```
$ MIX=$(python3 -c 'print("abcde"+"é"*5)')
$ LC_ALL=C           bash …  → PASS  hash=15
$ LC_ALL=C.UTF-8     bash …  → FAIL  hash=10
$ LC_ALL=en_US.UTF-8 bash …  → FAIL  hash=10
$ LC_ALL=POSIX       bash …  → PASS  hash=15
$ LC_ALL=en_US.UTF-8 dash …  → PASS  hash=15
```

Remote smoke is `$SSH bash -se`. Host locale is not pinned. `C`/`POSIX` counts the 10-character string as usable coverage.

Failure scenario: demo host `LANG=C` treats short multibyte alt as 15-byte usable. Coverage numerator inflates. Combined with R5-01, a 15-byte NBSP-padded fixture can count as coverage AND pass provenance.

Canon: CLM-04, rg-006

Suggested fix: pin `LC_ALL` in the concatenated heredoc and measure with one rule (bytes or characters), then test both.

### R5-04 | severity: low | file: scripts/deploy/tests/test-smoke-gate.sh:6

Evidence: both characterization suites start with `set -euo pipefail`. Dash and `/bin/sh` (`/bin/sh -> dash`) reject it:

```
$ dash scripts/deploy/tests/test-smoke-gate.sh; echo exit=$?
# exit=2   (set: Illegal option -o pipefail)
$ sh  infra/oci/demo/tests/test-describe-gate.sh; echo exit=$?
# exit=2
```

The classifier files themselves (no `[[`, no arrays, no `${var,,}`, no `+=`, no process substitution, no `echo -n`/`-e`) source and run under dash via `.`: `classify_alt_identity florence_small 1` → PASS; `seeded` → FAIL; rc=0 either way. Production remote body is explicitly `bash -se` and uses `[[`, `==` inside `[[`, `local`, `seq`. `sync-demo.sh` / `bootstrap-wp.sh` are bash (`[[`, `seed_media_files+=`, `< <(find)`, `${!var}`, `<<<`, `source`, `BASH_SOURCE`).

Failure scenario: none on the shipped `$SSH bash -se` path. A “run with sh” rewrite of the heredoc would hit `[[` immediately (fail-closed).

Canon: rg-006

Suggested fix: keep the remote invocation on bash; do not advertise POSIX `sh` for the suites.

### R5-05 | severity: medium | file: scripts/deploy/sync-demo.sh:309

Evidence: `ADAPTERJSON` scrapes every `"adapter":"..."` with no join to usable alt. `trusted_count >= usable_count` can be satisfied by adapters sitting on **empty**-alt rows. At shipped `min_pct=95` that cannot also pass coverage (verification-2 already showed 19 usable-null + 1 empty-trusted: coverage PASS, identity FAIL). At the **legal floor** `min_pct=50` it can. Exact counting block + `emit_alt_gate` + `DEMO_ALT_GATE_ENFORCE=1`:

```
--- 10 usable-null + 10 empty-trusted, min=50 ---
PASS demo alt population (header=20 body=20)
PASS demo alt coverage (10/20 = 50%, need 50%)
PASS demo alt provenance (identity=PASS adapters=[florence_small x10] with_alt=10)
smoke_fail=0

--- same mix min=95 ---
FAIL demo alt coverage (1/2 = 50%, need 95%)   # 1+1 scale
smoke_fail=1

--- 19 usable-null + 1 empty-trusted, min=95 ---
PASS demo alt coverage (19/20 = 95%, need 95%)
FAIL demo alt provenance (identity=FAIL adapters=[florence_small ] with_alt=19)
smoke_fail=1
```

Algebra: need `e >= u` for unbound adapters to cover usable_count, and `u/(u+e) >= min_pct/100`. Those together force `min_pct <= 50`. The floor is 50, so `DEMO_ALT_MIN_COVERAGE_PCT=50` is the only legal threshold where this mix ships.

Failure scenario: operator sets the documented floor; half the library has real captions and null provenance, half has empty alt stamped `florence_small`. Identity PASSes from the empty half. The usable alts never presented an adapter.

Canon: SECD-08, CLM-04

Suggested fix: scrape `adapter` only from items whose `alt_text` classified usable, or require `trusted_count == body_total` of probed items rather than `>= usable_count`.

### R5-06 | severity: low | file: scripts/deploy/lib/smoke-gate.sh:183

Evidence: every `classify_*` FAIL path is `echo FAIL; return` (no argument). `return` takes `echo`'s 0. Verbatim:

```
$ classify_alt_identity seeded 1 >/dev/null; echo rc=$?        # rc=0
$ classify_alt_identity florence_small 1 >/dev/null; echo rc=$? # rc=0
$ classify_alt_coverage 100 0 95 >/dev/null; echo rc=$?         # rc=0
$ classify_alt_provenance '' florence_small 1 >/dev/null; echo rc=$?  # rc=0
$ is_trusted_describe_profile seeded; echo rc=$?               # rc=1  (predicate, correct)
$ fixture_sample_is_denied 'A pet animal…'; echo rc=$?         # rc=0  (denied, correct)
```

Production heredoc keys off stdout (`if [ "$(classify_…)" != "PASS" ]`) and `smoke_fail`, then `exit "$smoke_fail"`. Bootstrap BLOCK is `exit 1` (last statement of that arm). No trailing `echo` after a failing command in the heredoc that resets `smoke_fail`.

Failure scenario: a future caller writes `classify_alt_identity … || smoke_fail=1`. That `||` never fires. Not the current call sites.

Canon: CLM-04

Suggested fix: `echo FAIL; return 1` / `echo PASS; return 0` on classifiers, or leave stdout-only and keep using stdout at every call site.

## Concatenation contract

Production cat order (`scripts/deploy/sync-demo.sh:209-211`): describe-gate.sh, then fixture-denylist.sh, then smoke-gate.sh. Later definition wins.

(a) Copies of `normalize_fixture_sample` / `fixture_sample_is_denied` are behaviour-identical on the ASCII corpus (tab/CR included). They are also identical on the Unicode misses (R5-01): both fail-open the same way.

(b) Reverse source order with **identical** copies: pet-animal still FAIL. Reverse order with a **drifted** describe-gate sourced last: `rev_order pet=PASS` (canonical lost). Order is load-bearing only when copies drift.

(c) Drift assertion:

| mutation | smoke suite | describe suite | live classifier (prod order) |
|---|---|---|---|
| describe-gate pet-animal `return 0`→`1` | `FAIL drift: fixture_sample_is_denied bodies diverged` exit 1 | same FAIL | still FAIL (canonical wins) |
| canonical fixture-denylist same arm | live pet-animal expected FAIL got PASS; body-drift FAIL; pool-caption drift FAIL; exit 1 | body-drift FAIL | PASS (canonical broken) |
| full-line `#` comment inside describe-gate `normalize_fixture_sample` | **exit 0** (`extract_fn_stripped` drops `#` lines) | FAIL bodies drifted | unchanged |

Behaviour-changing edits trip both suites. Comment-only edits can green `test-smoke-gate.sh`; `test-describe-gate.sh` still red. Tests do **not** grep the `cat` order in `sync-demo.sh`. A swap is a no-op until copies drift.

`describe-gate.sh` is **not** side-effect free at source time. Top-level `ACX_TRUSTED_DESCRIBE_PROFILES="florence_small gpu_qwen30b gpu_qwen30b_ensemble"` runs on `.` / concatenation. No stdout (`wc -c` of captured source stdout = 0). No other top-level commands. Intentional and load-bearing.

Every mutation above was reverted before commit. `git diff --stat` on sources is empty.

## Checks I ran

- `bash scripts/deploy/tests/test-smoke-gate.sh` → exit 0 (`all assertions passed`) before mutations, after each revert, and at the end.
- `bash infra/oci/demo/tests/test-describe-gate.sh` → exit 0 (`all assertions passed`) same cadence.
- `dash` / `sh` both suites → exit 2 (`Illegal option -o pipefail`).
- dash/sh `.` of the three libs: ASCII identity/coverage/provenance matched bash.
- Arithmetic: `classify_alt_coverage 08 0 50` → empty stdout, bash `08: value too great for base` (line 101). `set -euo pipefail` **aborts** (outer exit 1). `+10` / `-1` / `''` → FAIL. `999999999999999999999` → `integer expression expected` then FAIL. `|| true` swallow of the octal error leaves `emit_alt_gate ""` with `smoke_fail=0` (not the production call site).
- `classify_alt_identity` usable_count `08` → FAIL (`[ 1 -lt 08 ]` octal 8). `+1`/`-1`/`''` → FAIL via `*[!0-9]*`. `00` with adapters present → PASS (octal 0; not a production `with_alt`).
- python3 PATH-wrapper exiting 127: `FAIL fixture-pool ast parse failed for .../seeded_adapter.py`, suite exit 1 (fail-closed, not a skip).
- `set +o pipefail` then `set -o pipefail` in `sync-demo.sh:294,318` does **not** restore prior state; it force-enables. Production heredoc starts with `set -euo pipefail`. After restore there are no pipelines, only classify/emit/`exit "$smoke_fail"`. Starting with pipefail off, the block turns it on (`false | true` then dies under `set -e`).
- Missing `x-wp-total` under `set +o pipefail`: `header_total=[]` → `classify_alt_population` FAIL.
- Truncated JSON: 80-byte prefix of a 2-item body → 0 `alt_text` matches, 0 `adapter` matches. Mid-object cut after one complete `alt_text` → 1 alt / 0 adapter; header 2 → population FAIL.
- Live `curl -sS -D … -o … --max-time 15 'https://demo.altcontext.com/wp-json/wp/v2/media?per_page=2&_fields=id,alt_text,acx_alt_provenance'` → exit 0, `HTTP/2 200`, `x-wp-total: 100`, body `[{"id":104,"alt_text":""},{"id":103,"alt_text":""}]` (no `acx_alt_provenance` key; plugin field not on the live stack yet). Empty alt → current live library still fail-closes coverage/provenance.
- No `grep -P` / `sed -i` in the five gate files. `grep -o` is GNU+BSD (Ubuntu demo host + macOS laptop). `head -1` and `seq` are in `sync-demo.sh` / `bootstrap-wp.sh` (Ubuntu has both; not POSIX).
- Function last statements: classifiers end in `echo PASS`/`fi`/`esac`; predicates `return 1`. Bootstrap BLOCK arm last statement is `exit 1`.

## What I could NOT falsify

- `$(...)` / backticks inside `adapters_blob` do not execute; they classify FAIL.
- Empty / whitespace `adapters_blob` with `usable_count>0` FAILs closed.
- Unmatched glob `*` with default `nullglob` off FAILs closed.
- Extra trusted adapters on empty-alt rows cannot satisfy `trusted_count >= usable_count` at shipped `min_pct=95` (need `min_pct<=50`; R5-05).
- `python3` missing in the drift guard does not skip; suite goes red.
- Octal `08` in `classify_alt_coverage` under production `set -e` aborts the smoke (fail-closed), does not print PASS.
- Pipeline miss under `set +o pipefail` yielded empty/`0` counts, which classify FAIL. Could not construct a grep/sed/wc miss that prints PASS.
- Truncated / missing-header / no-`-L` 301 media bodies FAIL population or coverage. Could not construct a truncated body that still PASSes unless truncation happens after a fully consistent countable page (the gate then sees a complete page).
- `curl --max-time` + `|| true` leaves empty/partial files; those fail-close. Chunked decoding is curl’s job; a truncated chunk is a curl error, same path.
- Exact ASCII `_FIXTURE_POOL` sentences, including tab/CR variants, still FAIL Gate B.
- Classifier FAIL paths communicate via stdout; production does not use their `$?`. No trailing-echo reset of `smoke_fail` after a real FAIL in the heredoc. Bootstrap no longer falls through BLOCK without `exit 1`.
- Copies of the denylist helpers still match on ASCII behaviour; the drift assertion fires on behaviour edits (c). `describe-gate.sh` source-time side effect is only the allowlist assignment.
- Live demo still has 100 empty `alt_text` and no `acx_alt_provenance` in the `_fields` projection — the new Gate A is not what is currently shipping that library; coverage/provenance-empty would FAIL it.
