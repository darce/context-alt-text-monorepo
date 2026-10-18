# FSSHARD1-SES-01: root cause of the stray :memory:.ses sidecar

## Verdict

**Writer narrowed to ONNX Runtime 1.29.0 native telemetry/session analytics.** The sandbox was clean at baseline. Importing onnxruntime in a clean temporary cwd created the same 51-byte :memory:.ses sidecar; importing with ORT_DISABLE_TELEMETRY=1 did not. Its bundled libonnxruntime contains the :memory: cache-path literal, the .ses suffix, session-analytics write strings, and the telemetry disable flag. This directly reproduces the finding without SQLite or pytest. The exact internal MATSDK.PAL file-writing method is not exposed by the installed binary’s symbol table, so this report does not claim a method name. This follows DBG-01 and DBG-02.

## Evidence

1. Baseline before tests:

   Command: date +%s%3N && find . -maxdepth 5 -name ':memory:*' -printf '%TY-%Tm-%Td %TT %s %p\n'

   Output: 1790739238684; find returned no paths.

2. Environment and repository search:

   Command: env | grep -n ':memory:'; grep -rn ':memory:' apps/prototype-description-service --include='*.toml' --include='*.ini' --include='*.cfg' --include='conftest.py' | head -40

   Output: no matching environment variable; one project match at recognition/tests/conftest.py:99, the test URL sqlite+aiosqlite:///:memory:.

   Command: rg -n '\.ses\b' apps/prototype-description-service --glob '!*.md' --glob '!*.lock' | head -40

   Output: no matches in service text sources.

3. The service pyproject declares onnxruntime>=1.28.0,<2.0.0. Import-origin check resolved recognition to this worktree’s apps/prototype-description-service/recognition/__init__.py. The selected lane interpreter loaded onnxruntime from its own site-packages and reported version 1.29.0.

4. Tracing limitations and test batch:

   Command: strace -f -e trace=openat,creat,rename -o /tmp/fsshard1-ses-trace/taudit-stdio.strace env -u VIRTUAL_ENV PYTHONPATH=/tmp/fsshard1-ses-trace uv run --offline --directory apps/prototype-description-service --locked --extra dev pytest -p no:cacheprovider -q scene/tests/test_eval_harness_cli_stdio.py scene/tests/test_eval_harness_cli_gate_wire_format.py scene/tests/test_eval_harness_cli_determinism_paths.py scene/tests/test_eval_harness_cli_operator_paths_w19.py scene/tests/test_eval_harness_cli_stdout.py

   Output: strace stopped before pytest with PTRACE_TRACEME: Operation not permitted.

   Command: env -u VIRTUAL_ENV PYTHONPATH=/tmp/fsshard1-ses-trace uv run --offline --directory apps/prototype-description-service --locked --extra dev pytest -p no:cacheprovider -q scene/tests/test_eval_harness_cli_stdio.py scene/tests/test_eval_harness_cli_gate_wire_format.py scene/tests/test_eval_harness_cli_determinism_paths.py scene/tests/test_eval_harness_cli_operator_paths_w19.py scene/tests/test_eval_harness_cli_stdout.py

   Output: uv could not run offline because pytz==2026.2 was missing from its cache.

   Working directory for the provisioned-interpreter retry: apps/prototype-description-service.

   Command: lane_root="$(git rev-parse --show-toplevel)"; resolved_python="$lane_root/.venv/bin/python"; PYTHONPATH=/tmp/fsshard1-ses-trace "$resolved_python" -m pytest -p no:cacheprovider -q scene/tests/test_eval_harness_cli_stdio.py scene/tests/test_eval_harness_cli_gate_wire_format.py scene/tests/test_eval_harness_cli_determinism_paths.py scene/tests/test_eval_harness_cli_operator_paths_w19.py scene/tests/test_eval_harness_cli_stdout.py

   Output: 83 passed, 5 failed. Pytest emitted the ONNX Runtime warning “Failed to persist telemetry device ID; using an in-memory identifier”. The run created ./:memory:.ses in the service cwd. stat reported 51 bytes and mtime 2026-09-30 03:35:27.954759886; the first line was 1790739327955 and the second was a 36-character UUID-formatted hex string. The Python audit hook emitted no matching open/rename event.

5. Clean-cwd minimal repro:

   Working directory: apps/prototype-description-service.

   Command sequence: lane_root="$(git rev-parse --show-toplevel)"; resolved_python="$lane_root/.venv/bin/python"; clean_dir=/tmp/fsshard1-ort-clean; mkdir -p "$clean_dir"; PYTHONPATH=/tmp/fsshard1-ses-trace "$resolved_python" -c 'import os; os.chdir("/tmp/fsshard1-ort-clean"); import onnxruntime as ort; print(ort.__file__); print(ort.__version__)'; find "$clean_dir" -maxdepth 1 -name ':memory:*' -printf '%TY-%Tm-%Td %TT %s %p\n'; stat -c '%s bytes, mtime=%y, path=%n' "$clean_dir/:memory:.ses"; od -An -tx1c "$clean_dir/:memory:.ses"

   Output: the same telemetry warning; onnxruntime/__init__.py from the lane venv; version 1.29.0. It created /tmp/fsshard1-ort-clean/:memory:.ses, 51 bytes, mtime 2026-09-30 03:40:38.815328459. The first line was 1790739638815; the second line was UUID-formatted.

6. Telemetry-disabled control:

   Working directory: apps/prototype-description-service.

   Command sequence: lane_root="$(git rev-parse --show-toplevel)"; resolved_python="$lane_root/.venv/bin/python"; clean_dir=/tmp/fsshard1-ort-disabled; mkdir -p "$clean_dir"; ORT_DISABLE_TELEMETRY=1 PYTHONPATH=/tmp/fsshard1-ses-trace "$resolved_python" -c 'import os; os.chdir("/tmp/fsshard1-ort-disabled"); import onnxruntime as ort; print(ort.__file__); print(ort.__version__)'; find "$clean_dir" -maxdepth 1 -name ':memory:*' -printf '%TY-%Tm-%Td %TT %s %p\n'

   Output: onnxruntime/__init__.py from the lane venv and version 1.29.0; no telemetry warning and no :memory:* file in that cwd.

7. Native-library inspection:

   Command: lane_root="$(git rev-parse --show-toplevel)"; strings -a -t x "$lane_root/.venv/lib/python3.12/site-packages/onnxruntime/capi/libonnxruntime.so.1.29.0" | grep -n -C 16 -E ':memory:|\.ses|session analytics|ORT_DISABLE_TELEMETRY'

   Bounded output included cacheFilePath next to :memory:, Unable to save session analytics to %s, .ses, MATSDK.PAL, the UUID and timestamp format strings, onnxruntime::PosixTelemetry, ORT_DISABLE_TELEMETRY, /onnxruntime.db, and the telemetry.cc source path. Searches of the codex executable and uv tool tree found no .ses string; the repo JS/TS source search found none. No strace syscall trace was available.

8. Lane gate:

   Command: lane_root="$(git rev-parse --show-toplevel)"; resolved_python="$lane_root/.venv/bin/python"; "$resolved_python" -m pytest scripts/test_check_lane_manifest_overlaps.py -q

   Output: 26 passed.

## Writer

The creating process is a Python process loading onnxruntime 1.29.0. Its native library logs from telemetry.cc:800 operator() and contains onnxruntime::PosixTelemetry plus Microsoft::Applications::Events telemetry/session-analytics strings. In that same binary, cacheFilePath and :memory: appear near the telemetry SDK configuration strings, while .ses appears beside “Unable to save session analytics” and MATSDK.PAL. Together with the clean import repro and the ORT_DISABLE_TELEMETRY control, this narrows the writer to ONNX Runtime’s bundled telemetry/session-analytics subsystem treating :memory: as a sidecar basename. The exact internal writer method could not be recovered: nm/readelf searches returned no telemetry writer symbol.

## Trigger

Importing onnxruntime with telemetry enabled is sufficient; no SQLite URL or test is needed. The process cwd determines where :memory:.ses appears. Setting ORT_DISABLE_TELEMETRY=1 before the interpreter imports onnxruntime prevents both the warning and the sidecar in the controlled reproduction. The test batch also loaded ONNX Runtime, as shown by the same warning in child stderr.

## Repro

From the service directory, create a clean scratch cwd and run:

~~~sh
mkdir -p /tmp/fsshard1-ort-clean
lane_root="$(git rev-parse --show-toplevel)"
resolved_python="$lane_root/.venv/bin/python"
"$resolved_python" -c 'import os; os.chdir("/tmp/fsshard1-ort-clean"); import onnxruntime'
find /tmp/fsshard1-ort-clean -maxdepth 1 -name ':memory:*' -printf '%s %p\n'
~~~

With telemetry enabled, this produces a 51-byte :memory:.ses. Repeating the import in a separate clean cwd with ORT_DISABLE_TELEMETRY=1 produces no sidecar.

## Fix proposal

- Follow-up implementation files: set ORT_DISABLE_TELEMETRY=1 at the start of apps/prototype-description-service/conftest.py so it is in effect before service imports and inherited by test subprocesses. Add a regression test under apps/prototype-description-service/scripts/eval_harness/tests that starts a fresh interpreter with a temporary cwd, imports onnxruntime using the test bootstrap environment, and asserts that :memory:.ses does not exist. The assertion must fail if the file appears (TEST-15).
- The flag is experimentally verified to prevent this sidecar. Decide separately whether production service launches should also disable ONNX Runtime telemetry or retain it with a supported writable telemetry cache path; the latter path was not identified here.
- The test makes absence explicit so a broken/no-op capture is not mistaken for success (OBS-08). Preventing the file at its source also satisfies the same-rate purge concern in RES-07.

## Open questions

- What exact MATSDK.PAL function constructs and writes the .ses file? The installed native library exposed strings and the ORT warning location but no matching writer symbol. Upstream source or a symbolized build is needed to name it.
- Should ORT_DISABLE_TELEMETRY=1 apply only to tests, or to service runtime too? The minimal repro shows that any process importing onnxruntime can produce a cwd sidecar when telemetry is enabled.
- The original sibling-lane artifacts were not modified or traced in this sandbox. Their observed format is consistent with the controlled reproductions, but their individual process ancestry remains unverified here.
