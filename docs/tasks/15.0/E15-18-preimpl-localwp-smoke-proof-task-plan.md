# E15-18. Preimplementation LocalWP Smoke Proof

> **Metadata**
>
> - **Date**: 2026-05-06 16:10 EST
> - **Author**: Codex
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-18
> - **Target Branch**: `feature/e15-18-preimpl-localwp-smoke-proof`
> - **Review Coverage Target**: 2
> - **Start Command**: `make task-start TASK=E15-18 OBJECTIVE="Implement PREIMPL-001 LocalWP smoke proof"`

---

## Objective

Implement PREIMPL-001 from [docs/specs/e15-app-refactoring-preimplementation-spec.md](../../specs/e15-app-refactoring-preimplementation-spec.md). When this task is complete, `make localwp-batch-run-smoke` rejects malformed arguments, proves the effective operator-requested values, and can be trusted as a preimplementation proof gate for later E15 work.

## Problem Statement

The current LocalWP smoke harness can accept a literal `--` separator as a PHP argument and silently coerce it into a one-image smoke pass. That makes later LocalWP/public-demo validation evidence unreliable before any roster, dashboard, or curation work starts.

This plan supersedes [E15-14](E15-14-localwp-batch-smoke-argument-plumbing-task-plan.md) as the canonical PREIMPL-001 implementation track. Before Slice 1 code edits, record the superseding handoff decision for E15-18 so reviews have an explicit retirement link. Leave E15-14 on its documented lifecycle while its existing branch/worktree remains active, then retire it through the normal done/archive flow after that branch/worktree is actually closed.

## Constraints

- Preserve the existing LocalWP operator entrypoint and `WP_PATH` contract.
- Keep the smoke harness scoped to LocalWP batch proof; do not turn it into broad E2E automation.
- Invalid argument input must fail closed before any batch work is submitted.
- Documented commands must remain copy-paste runnable under rg-006.

## Workflow Principles

- Verification commands that accept operator parameters must report the effective parameters they used.
- Harness refactors should be behavior-preserving except for explicit validation and reporting.
- Runtime smoke evidence is useful only after deterministic parser/command tests pass.

## Terminology

- **Smoke argument vector**: Positional values passed from the Makefile through WP-CLI into `batch-run-smoke.php`.
- **Effective smoke parameters**: Parsed `limit`, `batch_size`, `timeout_seconds`, and `poll_interval_ms` values reported by the smoke script.

## Current State Analysis

- `apps/prototype-wp-alt-context/Makefile` currently forwards a literal separator into the smoke invocation.
- `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php` casts positional values instead of validating them.
- The smoke payload lacks enough effective-parameter detail for an operator to catch argument shifting.

## Target Outcome

The Makefile passes exactly the four intended smoke values to WP-CLI. The PHP smoke script rejects separators, missing values, non-integers, and out-of-range values, and the final JSON payload reports all effective parameters.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/testing-php.md`
- Constitution: `docs/agentic/constitution.md`
- Spec: `docs/specs/e15-app-refactoring-preimplementation-spec.md`
- Related task: `docs/tasks/15.0/E15-14-localwp-batch-smoke-argument-plumbing-task-plan.md`
- Handoff/MCP state: active task `E15-18`, open findings for PREIMPL smoke/planning artifacts
- External docs via `ctx7` only if: WP-CLI `eval-file` argument behavior cannot be reproduced from local tests.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Makefile -> WP-CLI eval-file | tooling | Smoke values may be shifted by a leaked separator | Pass only the intended smoke values | Existing variable names/defaults remain | command-generation test |
| PHP smoke payload | tooling | Result omits some effective parameters | Add effective `limit`, `batch_size`, `timeout_seconds`, `poll_interval_ms` | Additive JSON fields | parser/script test |

## Proposed Solution

Patch the Makefile invocation, harden the PHP argument parser, and add a focused Python regression test that proves the command has no leaked separator and that the smoke payload reports the effective values.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| LocalWP Make target | `apps/prototype-wp-alt-context/Makefile` | Remove leaked separator and preserve variable defaults |
| PHP smoke script | `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php` | Validate positional args and include effective parameters |
| Tests | `scripts/test_localwp_batch_smoke.py` | Add command/parser regression coverage |
| Docs verification | `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md` | Update only if the documented smoke invocation drifted |

## Related Files

| File | Note |
| --- | --- |
| `scripts/localwp-wp.sh` | WP-CLI wrapper invoked by LocalWP Make targets |
| `scripts/test_localwp_wp.py` | Adjacent wrapper testing pattern |
| `apps/prototype-wp-alt-context/Makefile` | Help text may mention the smoke command |

## Verification Strategy

- Deterministic tests:
  - `pyenv exec python -m pytest scripts/test_localwp_batch_smoke.py -q`
  - `pyenv exec python -m pytest scripts/test_localwp_wp.py -q`
- Runtime-parity / environment checks:
  - `cd apps/prototype-wp-alt-context && make localwp-batch-run-smoke WP_PATH="${LOCAL_WP_ROOT:-$HOME/Development/wp-context-alt-text}/app/public" SMOKE_LIMIT=10 BATCH_SIZE=5 TIMEOUT_SECONDS=60 POLL_INTERVAL_MS=500`
- Contract/fixture verification:
  - Assert final payload reports effective values `10`, `5`, `60`, and `500`.
- Manual verification:
  - Confirm malformed arguments fail with clear errors before submission.

## Slice Delivery

### Slice 1: Command and Parser Proof

**Goal**: Prove and fix the argument vector without changing smoke semantics beyond validation/reporting.

Changes:

- Add regression coverage for the generated smoke command.
- Remove the leaked separator from the Makefile invocation.
- Replace positional coercion with explicit parser validation.
- Add effective parameter fields to the smoke payload.

Proof:

- `pyenv exec python -m pytest scripts/test_localwp_batch_smoke.py -q`

### Slice 2: Runtime LocalWP Confirmation

**Goal**: Confirm the repaired harness against a real LocalWP site when available.

Changes:

- Run the smoke command with explicit operator values.
- Record the runtime payload in handoff.
- Verify adjacent docs/help text and update only drifted references.

Proof:

- LocalWP smoke command reports the requested effective values and expected submitted count.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the PREIMPL spec, E15-14 related plan, LocalWP wrapper tests, and handoff state before editing.
- [ ] Recorded the disposition of E15-14 (superseded by E15-18 with a handoff decision id) before Slice 1 implementation starts.
- [ ] Confirmed no broad E2E automation is added.
- [ ] Confirmed WP-CLI docs are only needed if local reproduction is inconclusive.

### Checklist for Slice 1: Command and Parser Proof

- [ ] Regression test proves `--` is not passed to the PHP smoke script.
- [ ] PHP argument parser rejects separators, missing values, non-integers, and out-of-range values.
- [ ] JSON payload reports effective smoke parameters.

### Checklist for Slice 2: Runtime LocalWP Confirmation

- [ ] Runtime smoke uses explicit operator values.
- [ ] Runtime payload proves effective values.
- [ ] Handoff records runtime proof or explains why LocalWP was unavailable.

## Review Readiness

- [ ] Deterministic test passes before runtime proof is claimed.
- [ ] Documented commands remain runnable as written.
- [ ] Handoff decision records parser changes, command changes, and verification.

## Stretch Goals

- [ ] Add a tiny fixture mode for parser-only PHP execution if it avoids needing WordPress bootstrap for invalid-argument tests.

## Success Criteria

- [ ] `SMOKE_LIMIT=10 BATCH_SIZE=5` cannot become a one-image pass because of argument shifting.
- [ ] Invalid smoke arguments fail before batch submission.
- [ ] The final smoke payload contains effective values an operator can verify.
