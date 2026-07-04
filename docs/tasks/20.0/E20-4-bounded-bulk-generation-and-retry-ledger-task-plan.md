# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-4`
> - **Review Coverage Target**: 2

---

## E20-4. Bounded Bulk Generation and Retry Ledger

## Objective

Add a bounded bulk-generation runner that processes missing-alt candidates in small batches and records per-attachment status for retry and review.

## Problem Statement

Single writes and CLI commands do not solve backlog processing. Bulk generation needs bounded execution, retry state, and failure visibility before a review/history UI can rely on it.

## Constraints

- Depends on E20-1, E20-2, and E20-3.
- No unbounded queue or hidden background worker.
- Retry ledger lives in WordPress storage and uses same-rate cleanup controls.

## Workflow Principles

- Bulk runs are explicit and bounded by `limit` and `batch_size`.
- Per-item failures are recorded, not swallowed.
- Retrying uses ledger state and candidate service filters.

## Terminology

- **Bulk run**: one bounded operator-triggered generation session.
- **Retry ledger**: WordPress table or option-backed durable record of per-item status and error codes.

## Current State Analysis

- Recognition batch patterns exist in `class-batch-run-service.php` and LocalWP batch smoke scripts.
- Description has no durable run ledger or retry state.
- E19 service-level cache exists backend-side, but WordPress needs operator-facing run status.

## Target Outcome

A bulk runner processes candidates with bounded concurrency/size, records `pending/running/succeeded/skipped/failed/retryable` item states, and exposes a read-only status surface for CLI/UI reuse.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`
- Contracts: `docs/workbay/contracts/image-description-api.md`
- Code: `apps/prototype-wp-alt-context/src/api/services/class-batch-run-service.php`, `apps/prototype-wp-alt-context/src/support/trait-batch-limits.php`
- Prior-task surfaces: E20-1 `DescribeMediaService` write policy; E20-2 `DescriptionCandidateService`; E20-3 `class-description-command.php`
- Handoff/MCP: tasks `E20-1` through `E20-4`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WordPress bulk ledger | WordPress plugin | none for descriptions | New durable run/item state | no | DB install + PHPUnit |
| WP-CLI/UI status | WordPress plugin | E20-3 CLI status | Add run id and item status | yes | CLI tests |

## Proposed Solution

Create description bulk run tables through the plugin lifecycle manager, a repository/service pair for run/item state, and a bounded runner that invokes E20-1 write logic per candidate. Add CLI status/generate options for run tracking and retrying failed items.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| DB lifecycle | `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | Create description run/item tables |
| Repository | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-description-run-repository.php` | New run/item persistence |
| Service | `apps/prototype-wp-alt-context/src/api/services/class-description-bulk-run-service.php` | Bounded runner and retry logic |
| CLI | `apps/prototype-wp-alt-context/src/cli/class-description-command.php` | Add run/retry/status options |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/api/services/class-batch-run-service.php` | Existing bounded batch patterns |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php` | Repository precedent |

## Verification Strategy

- Deterministic tests: `composer test -- --filter DescriptionBulkRunService`
- Runtime-parity checks: LocalWP bounded run with failures and retry
- Contract verification: run states documented in image-description contract

## Slice Delivery

### Slice 1: Durable run ledger

**Goal**: Add tables/repository for bulk run and item status.

Changes:

- Add lifecycle table creation/update.
- Add repository with create/update/query methods.

Proof:

- `composer test -- --filter DescriptionRunRepository`

### Slice 2: Bounded runner and retry

**Goal**: Process candidates in bounded batches and expose retryable state.

Changes:

- Add bulk run service and CLI integration.
- Record per-item result/error code.

Proof:

- `composer test -- --filter DescriptionBulkRunService`
- LocalWP smoke proves bounded run and retry failed item.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded recognition batch precedents and E20 service contracts.
- [ ] Confirmed WordPress owns operator run ledger.

### Checklist for Slice 1: Durable run ledger

- [ ] Description run/item tables or equivalent durable store installed.
- [ ] Repository covers create/update/query states.
- [ ] `composer test -- --filter DescriptionRunRepository` green.

### Checklist for Slice 2: Bounded runner and retry

- [ ] Runner enforces limit and batch size.
- [ ] Per-item failures are recorded and retryable.
- [ ] `composer test -- --filter DescriptionBulkRunService` green.

## Review Readiness

- [ ] No unbounded queue or silent failure path.
- [ ] Ledger cleanup/retention plan documented.
- [ ] Handoff decision records run-state contract.

## Stretch Goals

- [ ] Resume interrupted run from last pending item.

## Success Criteria

- [ ] A bounded missing-alt backlog run produces durable per-item statuses.
- [ ] Failed items can be retried without reprocessing successes.
- [ ] Operator can inspect run status via CLI JSON.
