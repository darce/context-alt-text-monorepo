# Tech Debt Plan: Contract Metadata Guardrails

## Problem Statement

We already fixed one dangerous boundary bug where a wrapper inferred pagination metadata from payload length instead of preserving the real contract. The deeper risk is broader: any controller, proxy, or client that normalizes remote payloads can accidentally invent `limit`, `offset`, `total`, `data_source`, or similar fields when the upstream shape is incomplete or unexpected.

That creates silent correctness drift. The code still “works,” but the contract is no longer truthful.

## Goal

Prevent future contract-shape trespasses by making boundary metadata explicit, testable, and reviewable.

## Principles

- One layer owns shape adaptation at each boundary.
- Envelope metadata must come from the request, the upstream payload, or a documented fallback.
- Unexpected upstream shapes should fail explicitly instead of being silently normalized.
- Downstream layers should consume the canonical shape only.

## Suggested Safeguards

1. Add table-driven tests for every boundary adapter that wraps remote payloads.
   - Assert the exact source of `limit`, `offset`, `total`, and provenance fields.
   - Include malformed payload cases that must return explicit errors.

2. Add runtime validation at adapter boundaries.
   - Reject contradictory payloads instead of supporting both array and envelope shapes in downstream consumers.
   - Treat envelope violations as contract errors, not convenience defaults.

3. Keep a single contract owner per boundary.
   - Backend returns one shape.
   - WordPress proxy adapts once.
   - TypeScript consumes the canonical envelope only.

4. Add reviewer checklists for boundary provenance.
   - Verify that metadata fields are not fabricated from list length or guessed defaults.
   - Verify that `data_source`, `projection_status`, and similar fields have a traceable source.

5. Add lint or static-analysis rules for suspicious adapter patterns.
   - Flag `count(payload)` used to populate pagination fields.
   - Flag dual-shape compatibility code when the contract is meant to be greenfield and canonical.

6. Add shared contract fixtures for envelope responses.
   - Keep examples in sync across PHP, TypeScript, and docs.
   - Use the fixtures as review anchors when shapes change.

## Implementation Path

### Phase 0: Test Coverage

- [ ] Add focused adapter tests for assignment suggestions, merge suggestions, name suggestions, top-unlabeled, and media identities.
- [ ] Add malformed-shape tests that verify explicit failure for unexpected upstream payloads.

### Phase 1: Boundary Validation

- [ ] Introduce a small validator/helper for envelope wrappers.
- [ ] Require explicit handling for pagination and provenance fields.
- [ ] Remove any remaining downstream raw-array fallback support.

### Phase 2: Review Automation

- [ ] Add a branch-review checklist item for boundary metadata preservation.
- [ ] Add a heuristic for envelope wrappers that checks provenance, pagination, and contract ownership.
- [ ] Add a lint/static-analysis rule if a reliable pattern emerges.

## Success Criteria

- [ ] No adapter invents pagination or provenance metadata from payload length or ad hoc defaults.
- [ ] Unexpected upstream payload shapes fail loudly.
- [ ] Tests and review checklists make contract drift obvious before merge.
- [ ] Downstream code only consumes one canonical contract shape.
