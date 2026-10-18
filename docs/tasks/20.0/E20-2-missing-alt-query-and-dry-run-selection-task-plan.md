# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-2`
> - **Review Coverage Target**: 2

---

## E20-2. Missing-Alt Query and Dry-Run Selection

## Objective

Create a deterministic missing-alt selection surface for one-site description work. Operators can preview the exact attachments that would be described or written before any mutation happens.

## Problem Statement

Bulk and CLI workflows need a stable source of candidate media. Existing media APIs expose alt text, but E20 needs a dry-run selection contract that shares the same filters as later generation commands.

## Constraints

- Dry-run must not call the backend description route.
- Selection order must be stable and paginated to avoid long requests.
- Reuse existing media status logic instead of a parallel SQL interpretation of "missing alt" where possible.

## Workflow Principles

- Selection is read-only and cheap.
- All later write/bulk commands consume this selection contract.
- Human-authored non-empty alt text is excluded unless an explicit include/force filter is requested.

## Terminology

- **Candidate**: an image attachment eligible for preview/write under current filters.
- **Dry-run**: a read-only response listing candidate ids, file names, current alt state, and reason.

## Current State Analysis

- `apps/prototype-wp-alt-context/src/api/class-media-detail-controller.php` and `class-media-identities-controller.php` expose media details for UI workflows.
- `packages/shared-contracts/schemas/workbench-media-item.schema.json` includes `altText`.
- No dedicated dry-run endpoint returns a write-candidate set for description generation.

## Target Outcome

A WordPress REST endpoint and service return stable missing-alt candidates with limit/offset filters, MIME/type guards, and a machine-readable exclusion reason for skipped attachments. Later CLI/bulk work can call the same service.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`
- Contracts: `docs/workbay/contracts/workbench-media-api.md`, `docs/workbay/contracts/image-description-api.md`
- Code: `apps/prototype-wp-alt-context/src/api/class-media-detail-controller.php`, `apps/prototype-wp-alt-context/src/api/services/class-analyze-media-service.php`
- Handoff/MCP: task `E20-2`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WP REST missing-alt dry-run | WordPress plugin | none | New read-only candidate endpoint under recognition namespace | no | PHPUnit + shared schema if promoted |
| CLI/bulk selection service | WordPress plugin | none | Shared PHP service consumed by future commands | yes; stable method signature | service unit tests |

## Proposed Solution

Add a `DescriptionCandidateService` that queries image attachments with missing alt text, applies deterministic filters, and returns candidate/exclusion rows. Expose it through a read-only REST endpoint and document the response as the canonical selection source for E20-3/E20-4.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| PHP service | `apps/prototype-wp-alt-context/src/api/services/class-description-candidate-service.php` | New candidate query and filter service |
| PHP controller | `apps/prototype-wp-alt-context/src/api/class-describe-controller.php` | Add dry-run/list route or sub-action |
| PHP API wiring | `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php` | Register service/controller dependency |
| JS API | `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts` | Add dry-run response types |
| Contract | `docs/workbay/contracts/image-description-api.md` | Document selection semantics |

## Related Files

| File | Note |
| --- | --- |
| `packages/shared-contracts/schemas/workbench-media-item.schema.json` | Existing `altText` shape to align with |
| `apps/prototype-wp-alt-context/src/support/trait-batch-limits.php` | Reuse limit validation patterns |

## Verification Strategy

- Deterministic tests: `composer test -- --filter DescriptionCandidateService`
- Runtime checks: LocalWP dry-run returns candidate ids without backend calls
- Contract verification: response schema/doc includes sort order and exclusion reasons

## Slice Delivery

### Slice 1: Candidate service

**Goal**: Implement read-only missing-alt candidate selection with stable ordering.

Changes:

- Add candidate service with limit/offset, MIME filtering, and exclusion reasons.
- Reuse existing attachment/alt helpers where available.

Proof:

- `composer test -- --filter DescriptionCandidateService` covers missing alt, non-empty exclusion, unsupported MIME, ordering, and limit bounds.

### Slice 2: REST and API contract

**Goal**: Expose dry-run candidates to UI/CLI callers through one contract.

Changes:

- Add read-only REST action.
- Add TypeScript API types.
- Document the response and that no backend describe call occurs.

Proof:

- `composer test -- --filter DescribeController`
- `npm test -- describeApi`

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded existing media API and image-description contract.
- [ ] Confirmed dry-run is WordPress-owned and backend-read-free.

### Checklist for Slice 1: Candidate service

- [ ] Candidate service returns stable missing-alt rows.
- [ ] Exclusion reasons are machine-readable.
- [ ] `composer test -- --filter DescriptionCandidateService` green.

### Checklist for Slice 2: REST and API contract

- [ ] REST endpoint/action exposes dry-run candidate response.
- [ ] TypeScript API types added.
- [ ] Contract docs and `npm test -- describeApi` green.

## Review Readiness

- [ ] Dry-run cannot mutate attachment meta.
- [ ] Later CLI/bulk tasks can reuse the same PHP service.
- [ ] Handoff decision records selection semantics.

## Stretch Goals

- [ ] Optional filter for media uploaded after a supplied date.

## Success Criteria

- [ ] Operator can list the exact missing-alt attachments eligible for generation.
- [ ] Non-empty alt text is excluded by default with explicit reason.
- [ ] Selection is deterministic across repeated calls.
