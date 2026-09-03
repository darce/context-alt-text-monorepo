# OCIRV-1 P1 test-integrity report

## Change summary

- Kept the OCIR login suite's existing secret-hygiene text assertions and added execution of the emitted snippet under Bash with fake `oci`, `timeout`, and `docker` executables.
- The behavioral harness asserts the exact Docker argv, byte-for-byte token stdin, absence of the token from Docker argv and every test artifact except the stdin capture, and a non-zero exit before Docker when the required username variable is unset.
- Added `scripts/deploy/tests/test_ocir_auth_shell.py` so pytest executes the Bash suite and requires both exit zero and the `all assertions passed` sentinel.
- Pinned the complete exponential-backoff sequence and its timeout budget.
- Reworked the fake OCI clients around one fake Vault store. Consumer reads now return the content actually submitted through `create_secret` or `update_secret`, after a configurable propagation delay.
- Added the rotation path: an old version remains readable during propagation, `create_secret` is forbidden by assertion, the submitted update content is checked, and `main()` may return only after the new version is read.
- Production files were modified only temporarily to execute mutants and were restored byte-for-byte; the final diff contains no production change.

## Per-finding RED evidence

These are the pre-change green results under each hostile mutation. Per TEST-15/TEST-06, each demonstrates that the old suite could not go red.

### S-15a: login pipeline made unreachable

Before: **SURVIVED**, exit 0.

```text
ok   unreachable hint says it is transient
ok   ocir_rejected hint routes to rotation
ok   oci_cli_missing hint gives the install line
ok   only the revoked-token hint sends a human to the Console

all assertions passed
MUTANT_S15A_RC=0
```

### S-15b: nounset disabled after `set -eu`

Before: **SURVIVED**, exit 0.

```text
ok   unreachable hint says it is transient
ok   ocir_rejected hint routes to rotation
ok   oci_cli_missing hint gives the install line
ok   only the revoked-token hint sends a human to the Console

all assertions passed
MUTANT_S15B_RC=0
```

### S-16: retry delay never increases

Before: **SURVIVED**, exit 0.

```text
..............                                                           [100%]
14 passed in 0.12s
MUTANT_S16_RC=0
```

### S-17: submitted content is the wrong value

Before: **SURVIVED**, exit 0.

```text
..............                                                           [100%]
14 passed in 0.11s
MUTANT_S17_RC=0
```

### S-18: existing-secret update branch raises

Before: **SURVIVED**, exit 0.

```text
..............                                                           [100%]
14 passed in 0.11s
MUTANT_S18_RC=0
```

## tests_run

The interpreter for each Python command was selected immediately before execution with:

```bash
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi
```

Baseline before changes:

```bash
"$resolved_python" -m pytest scripts/test_ocirv1_vault_readiness.py -q
bash scripts/deploy/tests/test-ocir-auth.sh
```

```text
..............                                                           [100%]
14 passed in 0.19s
...
all assertions passed
BASELINE_PYTEST_RC=0 BASELINE_SHELL_RC=0
```

Final lane verification:

```bash
"$resolved_python" -m pytest scripts/test_ocirv1_vault_readiness.py scripts/deploy/tests/test_ocir_auth_shell.py -q
```

```text
................                                                         [100%]
16 passed in 0.17s
```

Direct Bash verification:

```bash
bash -n scripts/deploy/tests/test-ocir-auth.sh
bash scripts/deploy/tests/test-ocir-auth.sh
```

```text
ok   ocir_rejected hint routes to rotation
ok   oci_cli_missing hint gives the install line
ok   only the revoked-token hint sends a human to the Console

all assertions passed
FINAL_PYTEST_RC=0 FINAL_SHELL_RC=0
```

Diff hygiene:

```bash
git diff --check
git diff -- scripts/deploy/lib/ocir-auth.sh scripts/deploy/_vault_put_secret.py
```

```text
(no output)
```

## Mutants

All after-change classifications meet the guard: baseline was green first; each mutant returned 1 and pytest reported at least one `FAILED` test.

### S-15a — unreachable Docker login pipeline

Diff:

```diff
-  printf 'acx_t %s | docker login %s -u "${acx_ocir_user}" --password-stdin >/dev/null\n' \
+  printf 'if false; then acx_t %s | docker login %s -u "${acx_ocir_user}" --password-stdin >/dev/null; fi\n' \
```

Before: **SURVIVED** (`MUTANT_S15A_RC=0`, `all assertions passed`).

After command:

```bash
"$resolved_python" -m pytest scripts/deploy/tests/test_ocir_auth_shell.py -q
```

After: **KILLED**.

```text
E         FAIL docker receives exact login registry/user/password-stdin argv
E         FAIL docker stdin equals the Vault token byte-for-byte: file bytes differ or /tmp/ocir-auth-test.4STFGC/docker.stdin was not created
E         FAIL required unset variable makes emitted snippet fail: exit 0
E         3 assertion(s) failed
FAILED scripts/deploy/tests/test_ocir_auth_shell.py::test_ocir_auth_shell_suite
1 failed in 0.15s
MUTANT_S15A_AFTER_RC=1
```

### S-15b — `set +u` disables nounset

Diff:

```diff
-  printf 'set -eu\n'
+  printf 'set -eu\nset +u\n'
```

Before: **SURVIVED** (`MUTANT_S15B_RC=0`, `all assertions passed`).

After command:

```bash
"$resolved_python" -m pytest scripts/deploy/tests/test_ocir_auth_shell.py -q
```

After: **KILLED**.

```text
E         FAIL required unset variable makes emitted snippet fail: exit 0
E         FAIL nounset aborts before docker is invoked
E         2 assertion(s) failed
FAILED scripts/deploy/tests/test_ocir_auth_shell.py::test_ocir_auth_shell_suite
1 failed in 0.17s
MUTANT_S15B_AFTER_RC=1
```

### S-16 — constant retry delay

Diff:

```diff
-        delay = min(delay * 1.5, 5.0)
+        delay = delay
```

Before: **SURVIVED** (`14 passed`, `MUTANT_S16_RC=0`).

After command:

```bash
"$resolved_python" -m pytest scripts/test_ocirv1_vault_readiness.py -q
```

After: **KILLED**.

```text
E       assert [1.0, 1.0, 1....1.0, 1.0, ...] == [1.0, 1.5, 2....5.0, 5.0, ...]
E         At index 1 diff: 1.0 != 1.5
FAILED scripts/test_ocirv1_vault_readiness.py::test_returns_once_the_written_value_reads_back
FAILED scripts/test_ocirv1_vault_readiness.py::test_main_rotation_waits_for_the_new_submitted_version
2 failed, 13 passed in 0.12s
MUTANT_S16_AFTER_RC=1
```

### S-17 — wrong content submitted

Diff:

```diff
-        content=base64.b64encode(value).decode("ascii"),
+        content=base64.b64encode(b"MUTANT-WRONG-VALUE").decode("ascii"),
```

Before: **SURVIVED** (`14 passed`, `MUTANT_S17_RC=0`).

After command:

```bash
"$resolved_python" -m pytest scripts/test_ocirv1_vault_readiness.py -q
```

After: **KILLED**.

```text
E   _vault_put_secret.SecretNotReadable: OCIR_AUTH_TOKEN was written but did not become readable within 120s (last: read back 18 bytes that do not match what was written)
FAILED scripts/test_ocirv1_vault_readiness.py::test_main_does_not_return_until_the_secret_reads_back
FAILED scripts/test_ocirv1_vault_readiness.py::test_main_reports_the_byte_count_but_never_the_token
FAILED scripts/test_ocirv1_vault_readiness.py::test_main_strips_a_trailing_newline_before_storing
FAILED scripts/test_ocirv1_vault_readiness.py::test_main_rotation_waits_for_the_new_submitted_version
4 failed, 11 passed in 0.18s
MUTANT_S17_AFTER_RC=1
```

### S-18 — update branch disabled

Diff:

```diff
     else:
-        secret = vaults.update_secret(
-            existing.id,
-            oci.vault.models.UpdateSecretDetails(secret_content=content),
-        ).data
-        action = "new version"
+        raise RuntimeError("MUTANT update branch disabled")
```

Before: **SURVIVED** (`14 passed`, `MUTANT_S18_RC=0`).

After command:

```bash
"$resolved_python" -m pytest scripts/test_ocirv1_vault_readiness.py -q
```

After: **KILLED**.

```text
E   RuntimeError: MUTANT update branch disabled
FAILED scripts/test_ocirv1_vault_readiness.py::test_main_rotation_waits_for_the_new_submitted_version
1 failed, 14 passed in 0.11s
MUTANT_S18_AFTER_RC=1
```

## Blockers

None.

## Findings outside ownership

None. The requested behavior was testable through existing seams; no production defect or additional seam was needed, and no production file remains changed.
