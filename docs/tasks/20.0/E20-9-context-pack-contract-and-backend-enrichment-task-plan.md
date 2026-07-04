# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-9`
> - **Review Coverage Target**: 2

---

## E20-9. Context-Pack Contract and Backend Enrichment

## Objective

Define and implement the first context pack that carries WordPress attachment, post, taxonomy, and product signals into the backend description service as typed, auditable context.

## Problem Statement

E19 transports inert `wp_context` and returns `context_used.applied=false`. To differentiate from generic captions, Alt Context needs a bounded context contract and backend enrichment path that can influence drafts while reporting what was used.

## Constraints

- Depends on E19 and should follow E20-7 governance for beta exposure.
- Do not expose raw prompt plumbing as product configuration.
- Context pack must be size-bounded and exclude private/unpublished content unless explicitly allowed.

## Workflow Principles

- Context sources are typed and listed in `context_used.sources`.
- Backend owns how context influences output; WordPress owns source collection.
- Missing context degrades to generic visual facts, not an error.

## Terminology

- **Context pack**: bounded JSON sent with the describe request containing attachment/post/site/product hints.
- **Applied context**: context that the adapter actually used to alter `alt_text_draft` or visual facts.

## Current State Analysis

- `class-describe-media-service.php` sends basic title/caption/description/filename context.
- `scene/interface_adapters/http/schemas/requests.py` validates the backend request.
- `scene/application/seeded_adapter.py` and `florence_local_adapter.py` can be extended behind the adapter protocol.
- No rich context contract or applied-source test exists.

## Target Outcome

WordPress builds a bounded context pack, backend validates it, adapters can consume it, and responses report `context_used.sources` with fixture-backed evidence that context changes the draft when available.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/backend-php-guidelines.md`
- Contracts: `docs/workbay/contracts/image-description-api.md`, `packages/shared-contracts/schemas/image-description-response.schema.json`
- Code: `apps/prototype-description-service/scene/interface_adapters/http/schemas/requests.py`, `apps/prototype-description-service/scene/application/visual_facts_service.py`, `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php`
- Handoff/MCP: task `E20-9`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WP to backend describe request | backend + WP | basic request context | Add typed context-pack object | yes; old minimal context accepted | Python/PHP contract tests |
| Backend response | backend | `context_used` exists | Populate applied/source fields accurately | yes; schema unchanged if shape already supports it | schema/route tests |

## Proposed Solution

Extend the request schema and WP service with a `context_pack` that includes attachment, parent post, taxonomy, SEO/product fields when available. Add adapter/service tests where seeded fixtures prove context-aware draft differences and `context_used` reporting.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Backend schema | `apps/prototype-description-service/scene/interface_adapters/http/schemas/requests.py` | Add bounded context-pack schema |
| Backend service | `apps/prototype-description-service/scene/application/visual_facts_service.py` | Normalize/pass context to adapters |
| Seeded adapter | `apps/prototype-description-service/scene/application/seeded_adapter.py` | Fixture-backed context-aware draft |
| WP service | `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php` | Build context pack |
| Contract | `docs/workbay/contracts/image-description-api.md` | Document context pack fields and privacy bounds |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scene/application/hashing.py` | Ensure context hash uses canonical normalized context |
| `apps/prototype-wp-alt-context/js/admin/pages/dashboard/DescribePanel.tsx` | May display context-used sources |

## Verification Strategy

- Deterministic tests: `uv run pytest apps/prototype-description-service/scene/tests/test_context_pack.py -q`
- PHP tests: `composer test -- --filter DescribeMediaService`
- Contract verification: sample response validates and `context_hash` changes only on normalized context changes

## Slice Delivery

### Slice 1: Contract and backend context use

**Goal**: Validate and consume a bounded context pack in the backend.

Changes:

- Add request schema and normalization.
- Add seeded adapter fixture that changes draft from context.

Proof:

- `uv run pytest apps/prototype-description-service/scene/tests/test_context_pack.py -q`

### Slice 2: WordPress context builder

**Goal**: Build the context pack from attachment/post/taxonomy/product data.

Changes:

- Add PHP context collection helpers and tests.
- Update contract docs and admin display if needed.

Proof:

- `composer test -- --filter DescribeMediaService`
- LocalWP evidence shows `context_used.applied=true` for seeded fixture.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded E19 schema/adapter code and WP describe service.
- [ ] Confirmed context pack is bounded and privacy-aware.

### Checklist for Slice 1: Contract and backend context use

- [ ] Backend request schema accepts typed context pack.
- [ ] Adapter reports `context_used.sources` accurately.
- [ ] `uv run pytest apps/prototype-description-service/scene/tests/test_context_pack.py -q` green.

### Checklist for Slice 2: WordPress context builder

- [ ] WordPress builds attachment/post/taxonomy/product context.
- [ ] Contract docs include size/privacy bounds.
- [ ] `composer test -- --filter DescribeMediaService` green.

## Review Readiness

- [ ] Raw prompts are not exposed as UI/API fields.
- [ ] Missing context degrades cleanly.
- [ ] Handoff decision records context ownership.

## Stretch Goals

- [ ] SEO plugin keyphrase extraction when a supported plugin is active.

## Success Criteria

- [ ] Context-aware seeded fixture produces a different, better draft than generic context.
- [ ] Response lists exactly which context sources were applied.
- [ ] Context hash remains canonical across key order changes.
