# OCIRV-1 N2 rotation-wrapper report

## Change summary

- Added `test-ocir-rotate.sh` and a pytest entry point. The contract executes
  the complete wrapper with fake OCI, Python, Docker, SSH, and timeout process
  boundaries and requires an end-of-workflow sentinel (TEST-01, TEST-06,
  TEST-15).
- Restricted rotation writes to `OCIR_AUTH_TOKEN` and `OCIR_USERNAME`, rejected
  inherited alternate names before input or mutation, and disclosed the Vault
  OCID plus secret name before each write (SECD-01, SECD-04, SECD-08).
- Changed rotation to prove the freshly supplied username/token pair directly
  against OCIR before durable state, then write token before optional username.
  `--skip-verify` now skips only the production SSH leg (RLSE-08, Principle 3,
  sr-001).
- Repaired routine rotation after the shared helper API change by reading the
  existing username with a directly bounded OCI call. Its stdout and stderr
  stay separate, and empty/whitespace-only values fail before Docker or writes.
- Moved the fresh-token proof into a trap-cleaned private Docker config and
  buffered the remote stdin program before executing the shared watchdog, so
  operator credentials are not persisted and unread shell source cannot be
  consumed as watchdog stdin.
- Added and validated `--readable-timeout`, including zero and decimal values,
  and forwarded it to every helper invocation (RES-13).
- Added an explicit remote-session marker so failures before the marker are
  `ssh_unreachable` while failures after it use the OCIR/Vault classifier.
  Captured diagnostics are stripped of C0/C1 terminal controls before display
  (DIAG-01, DIAG-07, SECD-05).
- Disabled inherited xtrace before any token input, replaced fixed-range help
  extraction with bounded markers, and documented the live IAM statement,
  target-state migration, deployed `pg-password` name, contacted hosts, timeout
  invocation, and non-atomic username update ordering (SECD-04, rg-006, rg-015,
  Principle 4, Principle 10).

## RED evidence per defect

- OCIRV1-N2B-01: after the shared auth helper changed its fetch builder to a
  zero-argument fragment, routine rotation without `--set-username` failed
  before proof. The new case executes that routine path and verifies the Vault
  username reaches Docker exactly.
- OCIRV1-N2B-02: the former `2>&1` username capture admitted successful OCI
  diagnostics into Docker's `-u` value. The fake OCI CLI now emits a notice on
  stderr and the contract proves it is absent from Docker arguments.
- OCIRV1-N2B-03: the fresh proof formerly used the operator's default Docker
  config. The fake Docker now writes a credential marker; the contract proves
  the proof uses a non-default directory, removes it on exit, and leaves the
  pre-existing operator config byte-for-byte unchanged.
- OCIRV1-N2B-04: empty and whitespace-only Vault usernames formerly reached
  `docker login`. The contract now requires classified rejection before either
  a Docker login or Vault write.
- OCIRV1-N2B-05: the replacement direct OCI read is held to the shared Vault
  watchdog contract. A deliberately slow username read must be killed and
  classified as `vault_unreachable` before Docker or Vault mutation.

- OCIRV-1-S-01: the supplied pre-change `exit 0` experiment survived all
  existing gates. With this suite, the same mutant returned 1 with 38 failed
  assertions and no success sentinel.
- OCIRV-1-S-11: the supplied pre-change fake-helper execution accepted the
  alternate name. The validation-removal mutant returned 1 with two failed
  allowlist assertions.
- OCIRV-1-L-06 and OCIRV-1-S-08: supplied pre-change execution showed mutation
  before proof. The proof-bypass mutant returned 1 with two failures; the
  username-first mutant returned 1 with the ordered-write assertion failing.
- OCIRV-1-S-04 and OCIRV1-M-06: supplied pre-change execution rejected the
  documented option. The forwarding-removal mutant returned 1 with six helper
  argument assertions failing.
- OCIRV-1-S-13 and OCIRV-1-S-14: supplied pre-change executions showed the
  incorrect classification and byte replay. The leg-collapse mutant returned
  1 with two failures; the sanitizer-removal mutant returned 1 with three
  failures.
- OCIRV-1-S-03: the supplied pre-change xtrace reproduction exposed its
  sentinel. The `set +x` removal mutant returned 1 with the secrecy assertion
  failing.
- OCIRV-1-L-13: supplied pre-change help output included executable lines. The
  fixed-range mutant returned 1 with two help assertions failing.
- OCIRV-1-L-09 and OCIRV-1-S-09: supplied pre-change runbook inspection showed
  both mismatches. Restoring both claims returned 1 with two runbook contract
  assertions failing.

## tests_run

Direct syntax and behavioral checks:

```text
bash -n scripts/deploy/ocir-token-rotate.sh
bash -n scripts/deploy/tests/test-ocir-rotate.sh
bash scripts/deploy/tests/test-ocir-rotate.sh
...
ok   runbook discloses production SSH contact
all assertions passed
```

Required lane verification (interpreter selected from the lane immediately
before invocation):

```text
lane_root="$(git rev-parse --show-toplevel)"
if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi
"$resolved_python" -m pytest scripts/deploy/tests -q
..                                                                       [100%]
2 passed in 0.78s
```

The literal gate command was also run earlier in the session:

```text
python3 -m pytest scripts/deploy/tests -q
..                                                                       [100%]
2 passed in 0.79s
```

Each mutant used:

```text
python3 -m pytest scripts/deploy/tests/test_ocir_rotate_shell.py -q
```

and returned non-zero. Source was restored after every run.

Additional checks:

```text
"$resolved_python" -m ruff check scripts/deploy/tests/test_ocir_rotate_shell.py
All checks passed!

git diff --check
(no output; exit 0)

bash scripts/deploy/ocir-token-rotate.sh --help | tail -8
Options:
    --readable-timeout SECONDS  Consumer read-back deadline (0 skips the wait)
    --skip-verify              Skip production-VM SSH verification only
    -h, --help                 Show this help
```

`shellcheck` was unavailable in this lane environment.

## Mutant matrix

All “before” results refer to the pre-change gate, which had no wrapper or
runbook contract and therefore could not observe these changes. All “after”
results were executed against the new suite and killed.

| Defect | Temporary diff | Before | After |
| --- | --- | --- | --- |
| D1 | `set -euo pipefail` followed by `exit 0` | SURVIVED; existing green tail ended in `all assertions passed`, `14 passed`, and parse rc 0 | KILLED; rc 1, 38 assertions failed |
| D2 | replace both allowlist comparisons with an unreachable value | SURVIVED; no wrapper suite | KILLED; rc 1, 2 assertions failed |
| D3a | continue after a failed fresh-token proof | SURVIVED; no wrapper suite | KILLED; rc 1, 2 assertions failed |
| D3b | write username before token | SURVIVED; no wrapper suite | KILLED; rc 1, 1 assertion failed |
| D4 | omit `--readable-timeout "$READABLE_TIMEOUT"` from helper argv | SURVIVED; no wrapper suite | KILLED; rc 1, 6 assertions failed |
| D5a | classify every remote failure as SSH transport | SURVIVED; no wrapper suite | KILLED; rc 1, 2 assertions failed |
| D5b | replace control-byte filter with `cat` | SURVIVED; no wrapper suite | KILLED; rc 1, 3 assertions failed |
| D6 | remove `set +x` | SURVIVED; no wrapper suite | KILLED; rc 1, 1 assertion failed |
| D7 | replace sentinel extraction with `sed -n '2,45p'` | SURVIVED; no wrapper suite | KILLED; rc 1, 2 assertions failed |
| D8 | restore the compartment statement as live and the no-host claim | SURVIVED; no runbook contract | KILLED; rc 1, 2 assertions failed |

No mutants survived (TEST-15, TEST-06).

## Blockers

None.

## Findings outside ownership

- OCIRV1-H-01
- OCIRV1-H-02
