# E15-14. LocalWP Batch Smoke Argument Plumbing

> **Metadata**
>
> - **Date**: 2026-05-05 22:00 EST (re-anchored 2026-05-08)
> - **Author**: GitHub Copilot
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-14
> - **Target Branch**: `feature/e15-14-localwp-batch-smoke-argument-plumbing`
> - **Status**: Implementation landed. Argument fix, parser hardening, and effective-parameter payload shipped on `main` via commits `9eeba809` (implement), `6ade6c22` (runtime proof), and `5936d9ea` (diagnostics review fixes). Plan is retained as a record of the slice and as the verification recipe for re-running the LocalWP smoke after WP-CLI / Makefile changes.
> - **Review Coverage Target**: 2

---

## Objective

Make `make localwp-batch-run-smoke` prove the operator-requested LocalWP batch size, limit, timeout, and polling settings. The smoke harness must reject malformed positional arguments instead of silently scanning one image while reporting a pass.

## Execution Priority

Priority 1 among the generated assessment task plans. The repaired harness is required before any public-demo or LocalWP verification flow treats `localwp-batch-run-smoke` as evidence; the previous harness could produce false-positive smoke results.

## Problem Statement (historical)

The original LocalWP batch smoke assessment found that the plugin Makefile passed a literal `--` to WP-CLI `eval-file`, and WP-CLI exposed that separator to `scripts/localwp/batch-run-smoke.php` as `$args[0]`. The PHP script coerced `--` to zero and clamped it to `1`, so a smoke request for 10 attachments could submit only one attachment while appearing successful. See `docs/assessments/current/localwp-batch-smoke-argument-plumbing-2026-05-05.md` for the full evidence trail.

## Constraints

- Preserve the existing LocalWP operator entrypoint and required `WP_PATH` contract.
- Do not broaden the smoke harness into a full E2E automation suite; CI automation remains deferred outside this slice.
- The script must fail loudly on invalid smoke arguments instead of coercing them.
- Keep documented commands copy-paste runnable and avoid hardcoded user-local absolute paths.

## Workflow Principles

- A smoke command that accepts operator parameters must echo or prove the effective parameters it used.
- Test harnesses should fail closed when wrapper argument plumbing changes.
- Local smoke proof is only useful when it exercises the same batch size and timeout the operator requested.

## Terminology

- **Smoke argument vector**: The positional values passed from `make localwp-batch-run-smoke` through WP-CLI into `batch-run-smoke.php`.
- **Effective smoke parameters**: The parsed `limit`, `batch_size`, `timeout_seconds`, and `poll_interval_ms` values actually used by the PHP script.

## Current State Analysis

Post-fix state on `main` (re-anchored 2026-05-08):

- `apps/prototype-wp-alt-context/Makefile` (line 320) passes the four positional smoke values directly to WP-CLI `eval-file` with no `--` separator: `_run_wp ... eval-file "$(CURDIR)/scripts/localwp/batch-run-smoke.php" "$(if $(SMOKE_LIMIT),$(SMOKE_LIMIT),100)" "$(if $(BATCH_SIZE),$(BATCH_SIZE),5)" "$(if $(TIMEOUT_SECONDS),$(TIMEOUT_SECONDS),240)" "$(if $(POLL_INTERVAL_MS),$(POLL_INTERVAL_MS),1000)"`.
- `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php` delegates parsing to `acx_parse_batch_run_smoke_args()` in the sibling `batch-run-smoke-args.php`. The parser requires either zero or four arguments, rejects the WP-CLI `--` separator with a `RuntimeException`, requires each value to match `/^\d+$/`, and enforces per-field minimums (`limit>=1`, `batch_size>=1`, `timeout_seconds>=2`, `poll_interval_ms>=100`).
- The final JSON payload echoes `limit`, `batch_size`, `submitted_total`, `timeout_seconds`, and `poll_interval_ms`, plus accepted/completed/failed/cancelled totals and a `reconciled` flag.
- Timeout diagnostics live in `batch-run-smoke-diagnostics.php` (`acx_format_batch_run_timeout_message`) and are unit-tested in `apps/prototype-wp-alt-context/tests/Unit/BatchRunSmokeDiagnosticsTest.php`.

## Target Outcome

Met by the landed implementation. The Makefile passes the smoke values directly to WP-CLI without a separator. The PHP script validates every positional argument, rejects unexpected separators or non-integers, and emits the effective smoke parameters in the final JSON payload.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/testing-php.md`
- Assessment: `docs/assessments/current/localwp-batch-smoke-argument-plumbing-2026-05-05.md`
- Adjacent task: `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md`
- Adjacent task: `docs/tasks/15.0/E15-5-manual-remote-e2e-task-plan.md`
- External docs via `ctx7` only if: WP-CLI `eval-file` argument behavior cannot be reproduced locally.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Makefile -> WP-CLI eval-file | tooling | `make localwp-batch-run-smoke` forwards smoke parameters through `_run_wp` | Drop the literal `--` so WP-CLI does not surface it as `$args[0]` | Yes; existing variables keep the same names and defaults | `scripts/test_localwp_batch_run_smoke.py` regression |
| PHP smoke output | tooling | JSON reports smoke result but not all effective parameters | Include effective `limit`, `batch_size`, `timeout_seconds`, and `poll_interval_ms` | Additive payload fields only | PHPUnit (`BatchRunSmokeArgsTest`) + script-level smoke run |

## Proposed Solution (landed)

Patched the Makefile target so the WP-CLI `eval-file` invocation passes only the four positional values expected by the smoke script. Extracted and hardened the PHP argument parser so it rejects `--`, missing values where required, and non-integer input before any batch work is submitted. Added regression coverage for both the generated command and the parser mapping.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| LocalWP Make target | `apps/prototype-wp-alt-context/Makefile` | Pass the four positional smoke values directly to `eval-file`; preserve defaults |
| PHP smoke script | `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php` | Delegate to the parser and emit effective parameters in JSON output |
| PHP smoke parser | `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke-args.php` | Validate positional arguments; reject `--` and non-integers; enforce minimums |
| PHP timeout diagnostics | `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke-diagnostics.php` | Format the timeout error message used when no terminal state is reached |
| Python regression test | `scripts/test_localwp_batch_run_smoke.py` | Assert the generated command has no `--` separator and forwards the four positional values |
| PHP unit test (parser) | `apps/prototype-wp-alt-context/tests/Unit/BatchRunSmokeArgsTest.php` | Cover happy path, separator rejection, non-integer rejection, and per-field minimums |
| PHP unit test (diagnostics) | `apps/prototype-wp-alt-context/tests/Unit/BatchRunSmokeDiagnosticsTest.php` | Cover timeout diagnostic formatting |
| Docs verification | `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md`, plugin Makefile help text | Verify they still match the repaired `make localwp-batch-run-smoke` invocation; update only if a mismatch is found |

## Related Files

| File | Note |
| --- | --- |
| `scripts/localwp-wp.sh` | Wrapper used by LocalWP Make targets |
| `scripts/test_localwp_wp.py` | Existing LocalWP wrapper testing style |
| `scripts/test_localwp_runtime.py` | Adjacent local runtime test conventions |

## Verification Strategy

- Deterministic tests:
  - `pyenv exec python -m pytest scripts/test_localwp_batch_run_smoke.py -q`
  - `pyenv exec python -m pytest scripts/test_localwp_wp.py -q`
  - `cd apps/prototype-wp-alt-context && composer test -- --filter BatchRunSmokeArgsTest`
  - `cd apps/prototype-wp-alt-context && composer test -- --filter BatchRunSmokeDiagnosticsTest`
- Runtime-parity / environment checks:
  - `cd apps/prototype-wp-alt-context && make localwp-batch-run-smoke WP_PATH="${LOCAL_WP_ROOT:-$HOME/Development/wp-context-alt-text}/app/public" SMOKE_LIMIT=10 BATCH_SIZE=5 TIMEOUT_SECONDS=60 POLL_INTERVAL_MS=500`
- Contract/fixture verification:
  - Assert payload keys map to operator-requested values: `limit==10`, `batch_size==5`, `timeout_seconds==60`, `poll_interval_ms==500`.
- Manual verification:
  - Confirm a site with fewer than the requested limit fails with a clear attachment-count error rather than scanning one item.

## Slice Delivery

### Slice 1: Command and Parser Regression (landed)

**Goal**: Prove and fix the argument shift without changing smoke behavior beyond validation and reporting.

Changes:

- Add a regression test for the generated LocalWP smoke command.
- Pass the four positional smoke values directly from the Makefile to WP-CLI `eval-file`.
- Extract and harden PHP positional argument validation into `batch-run-smoke-args.php`.
- Add effective smoke parameters to the JSON payload.
- Add PHPUnit coverage for the parser and timeout diagnostics.

Proof:

- `pyenv exec python -m pytest scripts/test_localwp_batch_run_smoke.py -q`
- `cd apps/prototype-wp-alt-context && composer test -- --filter BatchRunSmokeArgsTest`

### Slice 2: Runtime Smoke Confirmation (landed)

**Goal**: Verify the repaired harness against a real LocalWP site when available.

Changes:

- Run the LocalWP smoke command with explicit limit, batch size, timeout, and poll interval.
- Capture the resulting payload in the task handoff.

Proof:

- `cd apps/prototype-wp-alt-context && make localwp-batch-run-smoke WP_PATH="${LOCAL_WP_ROOT:-$HOME/Development/wp-context-alt-text}/app/public" SMOKE_LIMIT=10 BATCH_SIZE=5 TIMEOUT_SECONDS=60 POLL_INTERVAL_MS=500`

## Consolidated Checklist

> **Checklist scope rule:** Describes work delivered, not finding status. Finding status is queried from the handoff DB.

## Context and Ownership

- [x] Loaded the LocalWP smoke assessment and adjacent E15 demo verification plans before editing.
- [x] Confirmed the smoke target remains a LocalWP proof, not a public-demo CI replacement.
- [x] Confirmed no external dependency docs are needed unless WP-CLI argument behavior is disputed.

### Checklist for Slice 1: Command and Parser Regression

- [x] Regression coverage proves the Makefile invocation does not pass `--` to the PHP script.
- [x] PHP argument parsing rejects separators and non-integer values.
- [x] JSON output reports the effective smoke parameters.
- [x] PHPUnit unit tests cover the parser and timeout diagnostics.

### Checklist for Slice 2: Runtime Smoke Confirmation

- [x] LocalWP smoke run uses explicit operator parameters.
- [x] Output confirms the effective parameters and expected submitted count.

## Review Readiness

- [x] The deterministic test proves the wrapper no longer shifts positional arguments.
- [x] Runtime-parity evidence is recorded in the handoff (commits `6ade6c22`, `5936d9ea`).
- [x] Handoff decision records the command fix, parser hardening, and verification evidence.

## Success Criteria

- [x] `SMOKE_LIMIT=10 BATCH_SIZE=5` no longer submits one image because of argument shifting; payload reports `submitted_total==10` and `accepted_total==10`.
- [x] Invalid smoke arguments fail with `RuntimeException` from `acx_parse_batch_run_smoke_args` before any batch is submitted (covered by `BatchRunSmokeArgsTest`).
- [x] The smoke payload includes `limit`, `batch_size`, `timeout_seconds`, and `poll_interval_ms` matching the operator-requested values.

## Follow-ups (out of scope)

- Doc-drift sweep: verify `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md` and the plugin Makefile help text still match the repaired `make localwp-batch-run-smoke` invocation. Track separately if drift is found.
