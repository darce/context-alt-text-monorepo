# GPUUX-1 CO-02 lane report

## Change summary

- Replaced the fourteen parse-time `LANE_* := $(call lane_field,...)` evaluations with GNU Make memoized-lazy variables. A field is resolved only on first dereference and is then rewritten to a simple variable for the rest of that make process.
- Narrowed the global export to values that do not resolve task/lane metadata. `lane-report`, the only recipe found by `rg` to read the removed values through `$$TASK`, `$$LANE`, `$$SESSION`, `$$SUMMARY`, `$$SUBJECT`, or `$$LANE_TEST_CMD_*`, now has target-specific exports.
- Added a hermetic startup-cost regression test. Its fake `uvx` records invocations, and both a dry run and a real recipe that materializes its environment have an absolute bound of zero launches.
- Added a value/memoization contract covering all fourteen lane fields. The same sentinel values passed before and after the Makefile change, and every field is fetched exactly once even when dereferenced twice.
- GNU Make on the execution host is 4.3. The `$(eval ...)` memoization used here is supported by the required GNU Make 3.80 and later.

## Measured before/after

The wrapper prepended to `PATH` logged argv and then executed the real `/home/gate/.local/bin/uvx`. These are warm-cache measurements, so the launch-count assertion—not elapsed time—is the hardware-independent acceptance gate.

| Invocation | Before uvx / elapsed | After uvx / elapsed |
| --- | ---: | ---: |
| `make -n check-gpu-snapshots` | 3 / 0.17s | 0 / 0.01s |
| `make check-gpu-snapshots` | 4 / 0.22s | 0 / 0.07s |
| `make -n help` | 3 / 0.17s | 3 / 0.18s |
| `make help` | 4 / 0.28s | 3 / 0.27s |

`help` itself dereferences `SUPPORTED_TASKS` and `TASK_LANES` in its recipe, so three launches remain intentional in this checkout. Export narrowing removes the extra real-run launch. The task-irrelevant `check-gpu-snapshots` goal demonstrates the zero-launch fast path.

## Export-narrowing analysis

`rg` found environment-style reads in two recipes. `worker-daemon` assigns `SESSION` from a Make expansion before using the shell variable, so it does not require an exported value. `lane-report` directly reads `$$TASK`, `$$LANE`, `$$SESSION`, `$$SUMMARY`, `$$STATUS`, `$$LANE_TEST_CMD_1`, `$$LANE_TEST_CMD_2`, `$$MERGE_READY`, `$$DRY_RUN`, `$$MESSAGE`, and `$$SUBJECT`; its task/lane-dependent values therefore received target-specific exports. Static report controls remain globally exported and do not invoke `uvx`. No recipe reads exported `LANE_WORKTREE`, so it was removed from the export list.

## RED evidence

Command:

```text
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest scripts/tests/test_makefile_startup_cost.py -q
```

Tail before the Makefile fix:

```text
FAILED scripts/tests/test_makefile_startup_cost.py::test_task_irrelevant_goal_does_not_launch_uvx[dry-run]
FAILED scripts/tests/test_makefile_startup_cost.py::test_task_irrelevant_goal_does_not_launch_uvx[real-run]
2 failed, 1 passed in 0.46s
```

Each failed assertion observed three fake `uvx` launches instead of the required absolute zero. The lane-field value/memoization test passed before the implementation change, establishing the semantic baseline.

## tests_run

- Exact command: `lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest scripts/tests/test_makefile_startup_cost.py -q`

  Tail: `3 passed in 0.14s`

- Exact command: `lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m ruff check scripts/tests/test_makefile_startup_cost.py`

  Tail: `All checks passed!`

- Exact command: `lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m ruff format --check scripts/tests/test_makefile_startup_cost.py`

  Tail: `1 file already formatted`

- Exact command: `make help`

  Tail: `Supported task manifests:` / `Enumerated lanes for the active task:`; exit 0.

- Exact command: `make context`

  Tail: `make: *** No rule to make target 'context'. Stop.`

- Exact command: `make check-all`

  Tail:

  ```text
  error: Could not acquire lock
    Caused by: Could not create temporary file
    Caused by: Read-only file system (os error 30) at path "/home/gate/.cache/uv/.tmphqlXlb"
  make[2]: *** [Makefile:274: lint] Error 2
  make[1]: *** [Makefile:403: lint-all] Error 2
  make: *** [Makefile:330: check-all] Error 2
  ```

- Exact measurement commands used the form `GPUUX_CO02_COUNT_FILE=<unique-/tmp-file> PATH=/tmp/gpuux-co02-bin:$PATH /usr/bin/time -f 'elapsed=%e' make <goal>`, for `-n check-gpu-snapshots`, `check-gpu-snapshots`, `-n help`, and `help`, both before and after the implementation. Counts and elapsed times are in the table above.

## Mutants

### Mutant A: restore one eager lane field — KILLED

```diff
-LANE_BRANCH = $(eval LANE_BRANCH := $(_LANE_BRANCH_CMD))$(LANE_BRANCH)
+LANE_BRANCH := $(_LANE_BRANCH_CMD)
```

Pytest tail:

```text
FAILED scripts/tests/test_makefile_startup_cost.py::test_task_irrelevant_goal_does_not_launch_uvx[dry-run]
FAILED scripts/tests/test_makefile_startup_cost.py::test_task_irrelevant_goal_does_not_launch_uvx[real-run]
2 failed, 1 passed in 0.45s
```

### Mutant B: restore the global export — KILLED

```diff
-export ORCHESTRATOR_ROOT MESSAGE STATUS MERGE_READY DRY_RUN
+export ORCHESTRATOR_ROOT TASK LANE SESSION SUMMARY MESSAGE SUBJECT STATUS MERGE_READY DRY_RUN LANE_WORKTREE LANE_TEST_CMD_1 LANE_TEST_CMD_2
```

Pytest tail:

```text
FAILED scripts/tests/test_makefile_startup_cost.py::test_task_irrelevant_goal_does_not_launch_uvx[real-run]
1 failed, 2 passed in 0.31s
```

The dry-run case passed while the real-run case observed four launches, proving the export narrowing is load-bearing.

## Blockers

- The lane-local pytest gate passes.
- Full `make check-all` verification is sandbox-blocked because `uv` cannot create a temporary lock file under the read-only `/home/gate/.cache/uv` path.

## Findings outside ownership

- `make context` is documented in the root Makefile, but this checkout has no `context` target. The nearby comment assigns it to a canonical `Makefile.d/lifecycle.mk`, while the local `Makefile.d` contains only `demo-auth.mk`. This lane did not add or repair that external lifecycle fragment.
- `help` dereferences task metadata in recipe lines outside the frozen ownership region, so it cannot be a zero-`uvx` task-irrelevant probe without a separate owner changing its displayed task/lane section. This lane left those lines unchanged.
