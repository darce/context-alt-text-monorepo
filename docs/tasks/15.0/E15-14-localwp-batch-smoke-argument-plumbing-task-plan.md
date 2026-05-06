# E15-14. LocalWP Batch Smoke Argument Plumbing

> **Metadata**
>
> - **Date**: 2026-05-05 22:00 EST
> - **Author**: GitHub Copilot
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-14
> - **Target Branch**: `feature/e15-14-localwp-batch-smoke-argument-plumbing`
> - **Review Coverage Target**: 2

---

## Objective

Make `make localwp-batch-run-smoke` prove the operator-requested LocalWP batch size, limit, timeout, and polling settings. When this task is complete, the smoke harness rejects malformed positional arguments instead of silently scanning one image while reporting a pass.

## Execution Priority

Priority 1 among the generated assessment task plans. Land this before any public-demo or LocalWP verification flow treats `localwp-batch-run-smoke` as evidence, because the current harness can produce false-positive smoke results.

## Problem Statement

The LocalWP batch smoke assessment shows that the plugin Makefile currently passes a literal `--` to WP-CLI `eval-file`, and WP-CLI exposes that separator to `scripts/localwp/batch-run-smoke.php` as `$args[0]`. The PHP script coerces `--` to zero and clamps it to `1`, so a smoke request for 10 attachments can submit only one attachment while appearing successful.

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

- `apps/prototype-wp-alt-context/Makefile` passes a literal `--` before the positional smoke values.
- `scripts/localwp/batch-run-smoke.php` reads raw `$args[0]` through `$args[3]` and coerces them with integer casts.
- A requested `SMOKE_LIMIT=10 BATCH_SIZE=5` can become `limit=1`, `batch_size=10`, `timeout_seconds=5`, and `poll_interval_ms=240`.
- The final JSON payload does not include enough effective-parameter detail for an operator to catch the mismatch.

## Target Outcome

The Makefile passes the smoke values directly to WP-CLI without a separator that reaches the PHP script. The PHP script validates every positional argument, rejects unexpected separators or non-integers, and emits the effective smoke parameters in the final JSON payload.

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
| Makefile -> WP-CLI eval-file | tooling | `make localwp-batch-run-smoke` forwards smoke parameters through `_run_wp` | Remove the literal separator that becomes a PHP argument | Yes; existing variables keep the same names and defaults | Makefile/script regression test |
| PHP smoke output | tooling | JSON reports smoke result but not all effective parameters | Include effective `limit`, `batch_size`, `timeout_seconds`, and `poll_interval_ms` | Additive payload fields only | PHP parser/unit or script-level test |

## Proposed Solution

Patch the Makefile target so the final WP-CLI `eval-file` invocation passes only the four positional values expected by the smoke script. Extract or harden the PHP argument parser so it rejects `--`, missing values where required, and non-integer input before any batch work is submitted. Add regression coverage around both the generated command and parser mapping.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| LocalWP Make target | `apps/prototype-wp-alt-context/Makefile` | Remove the literal `--` from the smoke invocation and preserve defaults |
| PHP smoke script | `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php` | Validate positional arguments and include effective parameters in JSON output |
| Tests | `scripts/test_localwp_batch_smoke.py` (new) | Assert the generated command has no separator and maps values directly |
| Docs verification | `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md`, `apps/prototype-wp-alt-context/Makefile` help text | Verify they still match the repaired `make localwp-batch-run-smoke` invocation; update only if a mismatch is found |

## Related Files

| File | Note |
| --- | --- |
| `scripts/localwp-wp.sh` | Wrapper used by LocalWP Make targets |
| `scripts/test_localwp_wp.py` | Existing LocalWP wrapper testing style |
| `scripts/test_localwp_runtime.py` | Adjacent local runtime test conventions |

## Verification Strategy

- Deterministic tests:
  - `pyenv exec python -m pytest scripts/test_localwp_batch_smoke.py -q`
  - `pyenv exec python -m pytest scripts/test_localwp_wp.py -q`
- Runtime-parity / environment checks:
  - `cd apps/prototype-wp-alt-context && make localwp-batch-run-smoke WP_PATH="${LOCAL_WP_ROOT:-$HOME/Development/wp-context-alt-text}/app/public" SMOKE_LIMIT=10 BATCH_SIZE=5 TIMEOUT_SECONDS=60 POLL_INTERVAL_MS=500`
- Contract/fixture verification:
  - Assert effective payload values match `10`, `5`, `60`, and `500`.
- Manual verification:
  - Confirm a site with fewer than the requested limit fails with a clear attachment-count error rather than scanning one item.

## Slice Delivery

### Slice 1: Command and Parser Regression

**Goal**: Prove and fix the argument shift without changing smoke behavior beyond validation and reporting.

Changes:

- Add a regression test for the generated LocalWP smoke command.
- Remove the leaked `--` separator from the Makefile invocation.
- Harden PHP positional argument validation.
- Add effective smoke parameters to the JSON payload.

Proof:

- `pyenv exec python -m pytest scripts/test_localwp_batch_smoke.py -q`

### Slice 2: Runtime Smoke Confirmation

**Goal**: Verify the repaired harness against a real LocalWP site when available.

Changes:

- Run the LocalWP smoke command with explicit limit, batch size, timeout, and poll interval.
- Capture the resulting payload in the task handoff.
- Verify `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md` and the plugin Makefile help text still match the repaired invocation; update only if either surface drifted.

Proof:

- `cd apps/prototype-wp-alt-context && make localwp-batch-run-smoke WP_PATH="${LOCAL_WP_ROOT:-$HOME/Development/wp-context-alt-text}/app/public" SMOKE_LIMIT=10 BATCH_SIZE=5 TIMEOUT_SECONDS=60 POLL_INTERVAL_MS=500`

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the LocalWP smoke assessment and adjacent E15 demo verification plans before editing.
- [ ] Confirmed the smoke target remains a LocalWP proof, not a public-demo CI replacement.
- [ ] Confirmed no external dependency docs are needed unless WP-CLI argument behavior is disputed.

### Checklist for Slice 1: Command and Parser Regression

- [ ] Regression coverage proves the Makefile invocation does not pass `--` to the PHP script.
- [ ] PHP argument parsing rejects separators and non-integer values.
- [ ] JSON output reports the effective smoke parameters.

### Checklist for Slice 2: Runtime Smoke Confirmation

- [ ] LocalWP smoke run uses explicit operator parameters.
- [ ] Output confirms the effective parameters and expected submitted count.
- [ ] `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md` and plugin Makefile help text were verified against the repaired invocation, and only drifted text was updated.

## Review Readiness

- [ ] The deterministic test proves the wrapper no longer shifts positional arguments.
- [ ] Runtime-parity evidence is recorded when a LocalWP site is available.
- [ ] Handoff decision records the command fix, parser hardening, and verification evidence.

## Success Criteria

- [ ] `SMOKE_LIMIT=10 BATCH_SIZE=5` no longer submits one image because of argument shifting.
- [ ] Invalid smoke arguments fail with clear errors before batch submission.
- [ ] The smoke payload includes effective parameter values an operator can verify.
