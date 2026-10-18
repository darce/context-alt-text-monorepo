# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-7`
> - **Review Coverage Target**: 2

---

## E20-7. Error Logs, Usage Accounting, and Budget Controls

## Objective

Add operator-visible error logs, usage accounting, and per-site budget/rate controls for description generation. This is the governance prerequisite for public beta and hosted providers.

## Problem Statement

Bulk generation and provider mode are unsafe without visible failures and usage limits. Operators need to know what failed, what was retried, and how much generation activity occurred.

## Constraints

- Depends on E20-4 run ledger.
- Provider cost fields are optional placeholders until E20-11.
- Controls must fail closed when a budget/rate limit is exceeded.

## Workflow Principles

- Every failed generation has an error code, message, retryability, and source.
- Usage counters are updated on successful and failed attempts.
- Budget controls are checked before backend/provider calls.

## Terminology

- **Usage event**: one attempted description generation with adapter/provider, latency, cache/write status, and optional cost.
- **Budget gate**: per-site rate/count/cost policy that can deny generation before work begins.

## Current State Analysis

- E19 backend emits description metrics, but WordPress lacks operator-facing usage accounting.
- E20-4 plans run/item state but not cross-run usage budgets.
- Existing settings/admin surfaces can host budget controls.

## Target Outcome

WordPress records description usage/error rows, exposes status via REST/CLI/admin, and enforces configurable per-site limits before generation.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`
- Contracts: `docs/workbay/contracts/image-description-api.md`
- Code: `apps/prototype-wp-alt-context/src/api/class-settings-controller.php`, `apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx`
- Prior-task surfaces: E20-1 single generation service; E20-4 `class-description-bulk-run-service.php` and run ledger; E20-3 CLI command
- Handoff/MCP: task `E20-7`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WordPress usage ledger | WordPress plugin | none | New usage/error records | no | repository/service tests |
| Settings API/UI | WordPress plugin | existing settings | Add budget/rate controls | yes | PHPUnit + Vitest |
| Generation services | WordPress plugin | E20-1/E20-4 | Pre-call budget gate | yes | service tests |

## Proposed Solution

Add usage/error repositories and a budget policy service. Integrate the gate into single and bulk generation, then surface usage/errors in settings or a compact dashboard panel.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Repository | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-description-usage-repository.php` | Usage/error persistence |
| Service | `apps/prototype-wp-alt-context/src/api/services/class-description-budget-service.php` | Limit checks and usage recording |
| Settings | `apps/prototype-wp-alt-context/src/api/class-settings-controller.php` | Budget settings |
| UI | `apps/prototype-wp-alt-context/js/admin/pages/settings/**` | Budget controls and usage summary |
| CLI | `apps/prototype-wp-alt-context/src/cli/class-description-command.php` | Usage/error status output |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/support/class-telemetry.php` | Existing telemetry surface to evaluate for reuse |
| `apps/prototype-wp-alt-context/js/admin/pages/dashboard/DashboardRecentActivitySection.tsx` | Possible compact usage summary pattern |

## Verification Strategy

- Deterministic tests: `composer test -- --filter DescriptionBudgetService`
- Frontend tests: `npm test -- SettingsPage`
- Runtime checks: budget-exceeded LocalWP generation exits without backend call

## Slice Delivery

### Slice 1: Usage/error ledger and budget gate

**Goal**: Record usage/errors and block generation when limits are exceeded.

Changes:

- Add repository and budget service.
- Integrate pre-call checks into single/bulk generation services.

Proof:

- `composer test -- --filter DescriptionBudgetService`

### Slice 2: Settings/UI/CLI visibility

**Goal**: Surface limits, usage, and recent errors to operators.

Changes:

- Add settings API/UI fields.
- Add CLI usage/error status.

Proof:

- `composer test -- --filter SettingsController`
- `npm test -- SettingsPage`

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded E20-4 run ledger and settings surfaces.
- [ ] Confirmed budget gate runs before backend/provider calls.

### Checklist for Slice 1: Usage/error ledger and budget gate

- [ ] Usage/error rows record attempts, outcomes, adapter/provider, latency, and cost placeholder.
- [ ] Budget gate denies over-limit generation.
- [ ] `composer test -- --filter DescriptionBudgetService` green.

### Checklist for Slice 2: Settings/UI/CLI visibility

- [ ] Settings API/UI exposes limits and usage summary.
- [ ] CLI reports recent usage/errors.
- [ ] `npm test -- SettingsPage` green.

## Review Readiness

- [ ] Provider tasks have a concrete cost/budget hook.
- [ ] Failure states are visible and retryability is explicit.
- [ ] Handoff decision records budget semantics.

## Stretch Goals

- [ ] CSV export of usage rows.

## Success Criteria

- [ ] Over-budget generation fails closed before work starts.
- [ ] Operators can inspect recent errors and usage counts.
- [ ] Usage ledger can carry provider cost fields later without schema churn.
