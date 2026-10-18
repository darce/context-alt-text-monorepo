# GPUOPS-1 lane L7 — names in captions on the GPU tier, with provenance

Branch `feature/gpuops-1-naming-gpu-tier`, worktree `context-alt-text-monorepo-gpuops-1-naming-gpu-tier`. Owns `apps/prototype-description-service/scene/application/describe_run_worker.py`, `scene/application/naming_preview_service.py`, `scene/application/identity_merge/**`, and their tests.

## Goal

Prove and, where needed, fix that labelled face-cluster names are fused into `alt_text_draft` for `final_gpu` items exactly as for CPU drafts, bounded by the naming budget, and that `provenance.naming` reports what happened (contract C7).

## Current anchors

- `describe_run_worker.py`: `_naming_provenance_payload` :318 (pydantic `model_dump`), `_apply_naming_preview` :329-380 (`replace(outcome, alt_text_draft=named, provenance=merged)`, `merged["naming"]`), `naming_enabled` :446, call site :502, `NAMING_BUDGET_SECONDS` from `ACX_NAMING_BUDGET_SECONDS` (default 10).
- `naming_preview_service.py` :100-175: empty `phrase_boxes` → positional fallback; `faces_for_naming_preview` (HARM-02).
- `identity_merge/merge.py` :217-227 selects `PositionalFallbackRealizer` when no phrase boxes; `policy.py`, `realizer.py`, `join.py`.
- The GPU remote adapter yields no phrase boxes, so today the GPU tier can only ever use the positional realizer.
- Prior art in handoff (query with `review_findings(operation="get")`): E19-4A findings 2036 and 2040 report provenance dedup keyed by label that under-reports names; 1994 reports span `(-1, -1)` phrase boxes. Verify whether each is fixed at HEAD; write the failing test first.

## Deliverables

1. Test with a fake GPU adapter (no phrase boxes) and two labelled faces: the `final_gpu` outcome's `alt_text_draft` contains both names via the positional realizer; the same run with `naming_enabled = False` contains neither.
2. `provenance.naming` gains `status ∈ {applied, disabled, skipped_budget, no_faces}`, `realizer ∈ {grounded, positional_fallback, null}`, `names_applied: list[str]` (order of appearance). Use `StrEnum`s (sr-007). These field names are frozen (C7); L8 renders them.
3. Budget: when naming exceeds `NAMING_BUDGET_SECONDS`, the item keeps its un-named draft with `status = skipped_budget` and a WARNING; the item never fails (RES-02, RES-13). Test with a slow fake.
4. Dedup: if findings 2036/2040 reproduce (two different people, one shared label token, or two faces of one person), fix so `names_applied` lists each distinct person once and no name is dropped; pin with a test.
5. If a grounded realizer is feasible for GPU outputs without new model calls, describe it in the report; do not build it in this lane.

## Tests

`cd apps/prototype-description-service && python -m pytest <worker and identity_merge test files> -q -p no:cacheprovider` — find them with `grep -rl "_apply_naming_preview\|identity_merge" tests/`.

## Non-goals

Tenant flag setter (L6), UI (L8), any adapter or model change.
