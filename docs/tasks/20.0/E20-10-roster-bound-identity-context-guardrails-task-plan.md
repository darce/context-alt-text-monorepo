# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-10`
> - **Review Coverage Target**: 2

---

## E20-10. Roster-Bound Identity Context Guardrails

## Objective

Allow description generation to use roster-confirmed identity context only when policy permits it, while preventing automatic naming of people from unreviewed recognition output.

## Problem Statement

Context-aware descriptions are more useful when a site knows who appears in images, but naming people in alt text is sensitive. The system must distinguish roster-confirmed identity context from machine-only face recognition and make "needs human review" reasons explicit.

## Constraints

- Depends on E20-9 context pack.
- No automatic naming from clusters, suggestions, or machine labels without roster-confirmed identity.
- Roster context must be local/tenant-scoped and auditable in `context_used`.

## Workflow Principles

- Human-reviewed roster labels are the only source for person names.
- Policy can disable person naming entirely.
- Ambiguous or unconfirmed identities produce a review reason, not a guessed name.

## Terminology

- **Roster-confirmed identity**: person/label accepted by an operator in the roster workflow.
- **Review reason**: machine-readable reason why generated alt text should be reviewed before publishing.

## Current State Analysis

- Roster and identity surfaces exist under `apps/prototype-wp-alt-context/src/sovereign/repositories/class-roster-entry-projection-repository.php` and React roster pages.
- Description context pack does not include identity context yet.
- Backend response schema has `visual_facts` and `context_used`, but no explicit review-reason contract may be present.

## Target Outcome

WordPress context builder can include roster-confirmed names/roles under policy, backend adapters can use that context, and responses include review reasons when identity context is absent, ambiguous, or policy-blocked.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/backend-php-guidelines.md`
- Contracts: `docs/workbay/contracts/image-description-api.md`, `docs/workbay/contracts/workbench-media-api.md`
- Code: `apps/prototype-wp-alt-context/src/sovereign/repositories/class-roster-entry-projection-repository.php`, `apps/prototype-wp-alt-context/js/admin/pages/roster/**`, `apps/prototype-description-service/scene/domain/description.py`
- Handoff/MCP: task `E20-10`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Context pack identity section | WP + backend | E20-9 context pack | Add roster-confirmed identity context | yes; optional section | PHP/Python tests |
| Description response | backend | visual facts + alt draft | Add or populate review reasons | yes; schema migration if new field | schema tests |

## Proposed Solution

Add a roster identity collector in WordPress that only emits confirmed identities and policy state. Extend backend context handling to consume that section and return review reasons for blocked/ambiguous cases. Keep all machine-only recognition labels out of alt-text naming.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| WP context | `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php` | Include roster-confirmed identity context |
| WP repository | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-roster-entry-projection-repository.php` | Add read helper if needed |
| Backend domain | `apps/prototype-description-service/scene/domain/description.py` | Review reason type if missing |
| Backend adapter | `apps/prototype-description-service/scene/application/seeded_adapter.py` | Fixture-backed identity context behavior |
| Contract | `docs/workbay/contracts/image-description-api.md` | Person-naming policy and review reasons |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx` | Roster-confirmation terminology |
| `packages/shared-contracts/schemas/image-description-response.schema.json` | Update only if review reasons require schema extension |

## Verification Strategy

- Deterministic tests: `composer test -- --filter RosterDescriptionContext`, `uv run pytest apps/prototype-description-service/scene/tests/test_identity_context.py -q`
- Contract verification: schema includes review reasons if added
- Manual verification: seeded fixture with confirmed roster name uses name; unconfirmed does not

## Slice Delivery

### Slice 1: Roster context collection

**Goal**: Emit only confirmed roster identities into context pack.

Changes:

- Add WP collector/helper.
- Add tests for confirmed, unconfirmed, disabled, and ambiguous states.

Proof:

- `composer test -- --filter RosterDescriptionContext`

### Slice 2: Backend guardrails and review reasons

**Goal**: Consume roster context safely and report review reasons.

Changes:

- Update backend schema/domain/adapter as needed.
- Update contract docs and shared schema if response shape changes.

Proof:

- `uv run pytest apps/prototype-description-service/scene/tests/test_identity_context.py -q`
- schema validation green.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded roster repository/UI terminology and E20-9 context-pack contract.
- [ ] Confirmed machine-only labels cannot produce names in alt text.

### Checklist for Slice 1: Roster context collection

- [ ] WordPress emits confirmed roster identity context only.
- [ ] Policy-disabled and ambiguous states are represented.
- [ ] `composer test -- --filter RosterDescriptionContext` green.

### Checklist for Slice 2: Backend guardrails and review reasons

- [ ] Backend consumes roster context without guessing names.
- [ ] Review reasons are returned for blocked/ambiguous cases.
- [ ] `uv run pytest apps/prototype-description-service/scene/tests/test_identity_context.py -q` green.

## Review Readiness

- [ ] Person naming is roster-bound and policy-gated.
- [ ] Contract docs explain privacy behavior.
- [ ] Handoff decision records guardrail semantics.

## Stretch Goals

- [ ] UI badge explaining why a person name was or was not used.

## Success Criteria

- [ ] Confirmed roster identity can improve the draft.
- [ ] Unconfirmed identity never appears as a name in alt text.
- [ ] Response explains review-needed reasons.
