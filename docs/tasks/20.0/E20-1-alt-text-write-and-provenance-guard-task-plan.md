# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-1`
> - **Review Coverage Target**: 2

---

## E20-1. Alt-Text Write and Provenance Guard

## Objective

Add an intentional single-attachment write path that can persist an E19 `alt_text_draft` into `_wp_attachment_image_alt` while preserving human-authored alt text by default. Store generated-description provenance in attachment meta so later review, refresh, and audit surfaces can explain the write.

## Problem Statement

E19 can describe one attachment but does not write alt text. Operators need a safe bridge from preview to persisted WordPress alt text, with a default non-overwrite policy and an explicit force path.

## Constraints

- Preserve non-empty alt text unless `force=true` is explicitly supplied by an authorized operator.
- Write provenance in WordPress attachment meta; do not add a backend dependency for the write.
- Keep `/scene/describe/multipart` unchanged; WordPress owns `_wp_attachment_image_alt`.

## Workflow Principles

- Preview remains the default command path.
- The write path is idempotent for the same `(media_id, image_hash, context_hash, model_version)`.
- Provenance is stored beside the WordPress attachment, not in transient UI state.

## Terminology

- **Generated provenance**: attachment meta recording adapter, model id/version, prompt/task version, image hash, context hash, generated timestamp, and backend result id if present.
- **Force write**: explicit operator override for non-empty existing alt text.

## Current State Analysis

- `apps/prototype-wp-alt-context/src/api/class-describe-controller.php` exposes the describe proxy.
- `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php` sends one attachment to `/scene/describe/multipart`.
- `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts` and `js/admin/hooks/useDescribeMedia.ts` support preview UI calls.
- No PHP service currently updates `_wp_attachment_image_alt` from description results or records generated provenance.

## Target Outcome

`POST /acx/v1/recognition/describe` accepts write intent fields, returns preview-only by default, and writes alt text only when requested. Successful writes store provenance meta and return `written`, `skipped_existing_alt`, or `forced_overwrite` state without fabricating backend fields.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/planning-review-guide.md`
- Contracts: `docs/workbay/contracts/image-description-api.md`
- Code: `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`, `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php`, `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts`
- Handoff/MCP: task `E20-1`; review findings and slice decisions.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WP REST describe proxy | WordPress plugin | `docs/workbay/contracts/image-description-api.md` | Add write intent/result fields for WP proxy response only | yes; preview callers keep working | PHPUnit envelope tests + TS API tests |
| WordPress attachment meta | WordPress plugin | `_wp_attachment_image_alt` + custom meta absent | Add generated provenance meta keys | no; greenfield meta | WordPress unit tests |
| Backend scene route | backend | `/scene/describe/multipart` | none | n/a | test asserts payload forwarded unchanged |

## Proposed Solution

Extend the WordPress describe service with a write coordinator that validates intent, reads current alt text, calls the existing describe host, and writes `_wp_attachment_image_alt` plus `_acx_description_provenance` only when policy allows. Update the admin describe API types to show write status without changing the backend scene schema.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| PHP service | `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php` | Add write policy, current-alt inspection, provenance meta write |
| PHP controller | `apps/prototype-wp-alt-context/src/api/class-describe-controller.php` | Validate `write_alt`/`force` request fields and response status |
| JS API | `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts` | Add write intent/result types |
| UI hook | `apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts` | Expose write mutation state |
| Contract | `docs/workbay/contracts/image-description-api.md` | Document WP proxy write fields and non-overwrite default |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/support/trait-runs-transactional.php` | Use if write + meta update needs a transaction wrapper |
| `apps/prototype-wp-alt-context/js/admin/pages/dashboard/DescribePanel.tsx` | Preview UI can add write controls after API semantics land |
| `apps/prototype-wp-alt-context/tests` | Add focused service/controller tests |

## Verification Strategy

- Deterministic tests: `composer test -- --filter DescribeMediaService`
- Runtime-parity checks: LocalWP smoke with one missing-alt attachment and one non-empty-alt attachment
- Contract verification: TS describe API tests and contract doc update
- Manual verification: inspect attachment alt text and `_acx_description_provenance` meta after write

## Slice Delivery

### Slice 1: Write policy and provenance meta

**Goal**: Implement missing-alt write and non-overwrite guard in PHP service tests first.

Changes:

- Add request parsing for `write_alt` and `force`.
- Write `_wp_attachment_image_alt` only when empty or forced.
- Store `_acx_description_provenance` with backend provenance and generated timestamp.

Proof:

- `composer test -- --filter DescribeMediaService` covers preview-only, missing-alt write, non-empty skip, forced overwrite, and provenance meta.

### Slice 2: REST/TS contract and UI API state

**Goal**: Expose the write result through REST and admin API types without changing backend scene response.

Changes:

- Update controller validation and response envelope.
- Update `describeApi.ts` and `useDescribeMedia.ts`.
- Document WP proxy response fields in `image-description-api.md`.

Proof:

- `npm test -- describeApi useDescribeMedia`
- Contract doc names every WP-only field and states backend scene response is unchanged.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded E19 image-description contract and WP describe service before editing.
- [ ] Confirmed WordPress owns `_wp_attachment_image_alt`; backend scene route unchanged.

### Checklist for Slice 1: Write policy and provenance meta

- [ ] PHP service supports preview, missing-alt write, skip, and force states.
- [ ] Provenance meta captures adapter/model/version/hash/context/generation time.
- [ ] `composer test -- --filter DescribeMediaService` green.

### Checklist for Slice 2: REST/TS contract and UI API state

- [ ] Controller validates write intent fields and returns write status.
- [ ] JS API/hook types expose write status.
- [ ] Contract docs updated and `npm test -- describeApi useDescribeMedia` green.

## Review Readiness

- [ ] No backend scene schema drift.
- [ ] Non-empty alt text protection has explicit tests.
- [ ] Handoff decision records write semantics and provenance keys.

## Stretch Goals

- [ ] Admin UI button for forced overwrite, behind a confirmation dialog.

## Success Criteria

- [ ] Missing-alt attachment receives generated alt text only when write intent is true.
- [ ] Non-empty alt text is skipped by default and overwritten only with force.
- [ ] Provenance meta survives a fresh attachment read.
