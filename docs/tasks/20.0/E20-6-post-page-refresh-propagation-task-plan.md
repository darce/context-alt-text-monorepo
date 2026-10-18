# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-6`
> - **Review Coverage Target**: 2

---

## E20-6. Post/Page Refresh Propagation

## Objective

Add a safe refresh path that helps existing posts, pages, and WooCommerce content reflect updated Media Library alt text after generation or human correction.

## Problem Statement

Updating Media Library alt text does not always update existing serialized blocks, classic content, or product galleries. Operators need a dry-run-first refresh that identifies affected content and applies safe updates.

## Constraints

- Depends on E20-1 and benefits from E20-5 history state.
- Refresh must be dry-run-first and bounded.
- Do not mutate content where the attachment reference cannot be matched confidently.

## Workflow Principles

- Media Library remains the source of truth for current alt text.
- Content refresh reports every changed post id and skipped reason.
- WooCommerce support is optional unless plugin functions are available.

## Terminology

- **Refresh candidate**: post/page/product content referencing an attachment with updated alt text.
- **Propagation**: applying current attachment alt text into content markup or block attributes.

## Current State Analysis

- WordPress media alt write is planned in E20-1.
- No refresh service exists for syncing attachment alt text into existing content.
- Existing code has admin/API registration patterns but no content rewrite helper.

## Target Outcome

A refresh service and CLI/REST action can dry-run impacted content, then apply bounded updates for safe block/image references. It returns changed/skipped counts and reasons.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`
- Contracts: `docs/workbay/contracts/image-description-api.md`
- Code: `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`
- Prior-task surfaces: E20-1 alt write/provenance; E20-3 `class-description-command.php`; E20-5 history UI if REST-triggered refresh is added
- Handoff/MCP: task `E20-6`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WordPress content | WordPress plugin | post content/product metadata | Dry-run/apply refresh of attachment alt text | yes; preserve unrelated content | PHPUnit fixtures |
| WP-CLI/REST | WordPress plugin | E20 CLI/history surfaces | Add refresh dry-run/apply action | yes | CLI/REST tests |

## Proposed Solution

Implement a `DescriptionContentRefreshService` that discovers attachment references in block/classic content, computes replacements using current attachment alt text, and applies only unambiguous changes. Wire it through WP-CLI first, then REST if needed by the review workspace.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| PHP service | `apps/prototype-wp-alt-context/src/api/services/class-description-content-refresh-service.php` | Discover/dry-run/apply refresh |
| CLI | `apps/prototype-wp-alt-context/src/cli/class-description-command.php` | Add `refresh` command |
| REST | `apps/prototype-wp-alt-context/src/api/class-describe-controller.php` | Optional review UI refresh action |
| Tests | `apps/prototype-wp-alt-context/tests` | Block/classic/product fixtures |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/support/trait-batch-limits.php` | Reuse bounded limit validation |
| `apps/prototype-wp-alt-context/js/admin/pages/description-history/**` | E20-5 UI may trigger refresh |

## Verification Strategy

- Deterministic tests: `composer test -- --filter DescriptionContentRefreshService`
- Runtime-parity checks: LocalWP dry-run/apply for one post fixture
- Manual verification: post content diff shows only intended alt update

## Slice Delivery

### Slice 1: Dry-run discovery

**Goal**: Identify refresh candidates and skipped reasons without mutation.

Changes:

- Add discovery for block/classic image references.
- Add bounded CLI dry-run output.

Proof:

- `composer test -- --filter DescriptionContentRefreshDryRun`

### Slice 2: Apply safe refreshes

**Goal**: Apply unambiguous refreshes and report changed/skipped content.

Changes:

- Add apply mode and optional REST hook.
- Add fixtures for ambiguous/skipped references.

Proof:

- `composer test -- --filter DescriptionContentRefreshApply`
- LocalWP smoke shows dry-run then apply.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded E20-1 write semantics and content refresh fixtures.
- [ ] Confirmed refresh mutates content only after dry-run proof.

### Checklist for Slice 1: Dry-run discovery

- [ ] Service identifies block/classic candidates.
- [ ] Skipped reasons are returned for ambiguous references.
- [ ] `composer test -- --filter DescriptionContentRefreshDryRun` green.

### Checklist for Slice 2: Apply safe refreshes

- [ ] Apply mode updates only unambiguous references.
- [ ] CLI/REST report changed and skipped counts.
- [ ] `composer test -- --filter DescriptionContentRefreshApply` green.

## Review Readiness

- [ ] Content rewrite is bounded and reversible through normal WP revisions.
- [ ] WooCommerce handling is guarded when unavailable.
- [ ] Handoff decision records refresh semantics.

## Stretch Goals

- [ ] Admin UI button to refresh content for one reviewed item.

## Success Criteria

- [ ] Operator can dry-run impacted posts/pages for generated alt text.
- [ ] Apply mode updates only safe references.
- [ ] Skipped references include actionable reasons.
