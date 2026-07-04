# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-5`
> - **Review Coverage Target**: 2

---

## E20-5. Review History Workspace

## Objective

Build an admin review/history workspace for generated descriptions, write status, provenance, and inline correction. Operators can inspect what was generated and adjust alt text after bulk or single-image runs.

## Problem Statement

Generated alt text needs human review. E19's dashboard describe panel and E20's CLI/bulk surfaces do not provide a durable operator workspace for corrections and provenance.

## Constraints

- Depends on E20-1 and E20-4.
- UI must use existing design tokens and avoid adding logic to already large components when a subcomponent/hook is clearer.
- Inline edits must preserve generated provenance and record human edit state separately.

## Workflow Principles

- History is read-first; edits are explicit.
- Provenance remains visible whenever generated text is shown.
- Correction writes use E20-1 overwrite policy or a documented human-edit path.

## Terminology

- **Review item**: one generated description result joined to attachment and provenance state.
- **Human correction**: operator-authored alt text update after generation.

## Current State Analysis

- `js/admin/pages/dashboard/DescribePanel.tsx` shows one-result preview.
- `js/admin/pages/WorkbenchPage.tsx` and workbench components handle dense review workflows.
- No description history API or admin page exists.

## Target Outcome

An admin page or workbench tab lists generated-description history with filters, provenance, current alt text, generated draft, write status, and inline edit action. Tests cover loading, error, empty, edit, and provenance display states.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`, frontend guidance in system instructions
- Contracts: `docs/workbay/contracts/image-description-api.md`
- Code: `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/dashboard/DescribePanel.tsx`, `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`
- Prior-task surfaces: E20-1 provenance meta; E20-4 description run/item ledger
- Handoff/MCP: task `E20-5`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WP REST description history | WordPress plugin | none | New read/edit history endpoint | no | PHPUnit + TS contract tests |
| React admin | WordPress plugin | dashboard/workbench pages | Add review/history workspace | yes; no route regression | Vitest + Playwright optional |

## Proposed Solution

Expose a description history endpoint backed by E20 provenance/run state, then add a focused React page or tab with reusable hooks/components. Inline edits call a narrow REST action that updates alt text and records human correction metadata.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| PHP controller | `apps/prototype-wp-alt-context/src/api/class-describe-controller.php` | Add history/list and correction actions |
| PHP service | `apps/prototype-wp-alt-context/src/api/services/class-description-history-service.php` | Join provenance, run state, and attachment alt text |
| JS API | `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts` | Add history/correction calls |
| React UI | `apps/prototype-wp-alt-context/js/admin/pages/description-history/**` | New page/components/hooks |
| Styles | `apps/prototype-wp-alt-context/js/admin/styles/components/_describe.scss` | Token-based review history styles |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx` | Dense table pattern |
| `apps/prototype-wp-alt-context/js/admin/context/ToastContext.tsx` | User feedback pattern |

## Verification Strategy

- Deterministic tests: `composer test -- --filter DescriptionHistoryService`, `npm test -- description-history`
- Runtime-parity checks: history page shows a generated result from LocalWP smoke
- Manual verification: inline correction updates visible alt text and retains provenance

## Slice Delivery

### Slice 1: History API

**Goal**: Return generated-description history with attachment and provenance state.

Changes:

- Add history service and REST action.
- Add correction action that records human edit metadata.

Proof:

- `composer test -- --filter DescriptionHistoryService`

### Slice 2: React review workspace

**Goal**: Render history, provenance, filters, errors, and inline correction UI.

Changes:

- Add API calls, hooks, components, and styles.
- Add tests for load/empty/error/edit/provenance states.

Proof:

- `npm test -- description-history`

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded existing dashboard/workbench component patterns.
- [ ] Confirmed human corrections do not erase generated provenance.

### Checklist for Slice 1: History API

- [ ] History API returns attachment, draft, current alt, provenance, and run status.
- [ ] Correction action records human edit state.
- [ ] `composer test -- --filter DescriptionHistoryService` green.

### Checklist for Slice 2: React review workspace

- [ ] Review/history UI supports list, filter, empty, error, and edit states.
- [ ] Styles use existing tokens.
- [ ] `npm test -- description-history` green.

## Review Readiness

- [ ] No generated/human provenance ambiguity.
- [ ] UI text fits compact admin layouts.
- [ ] Handoff decision records review workspace contract.

## Stretch Goals

- [ ] Keyboard shortcut for saving an inline correction.

## Success Criteria

- [ ] Operator can review generated descriptions with provenance.
- [ ] Operator can correct alt text inline.
- [ ] Corrected items remain distinguishable from generated-only items.
