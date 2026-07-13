# VLM-4 — Anti-Hallucination Generation Decision Memo

> **Metadata**
>
> - **Task**: VLM-4 (`docs/tasks/vlm/VLM-4-anti-hallucination-generation-task-plan.md`)
> - **Branch**: `feature/vlm-4`
> - **Status**: Slice 1 adoption note drafted; later slices (ensemble decode, bake-off) TBD

## Slice 1 adoption note

The shared Stage-1 component `scene/application/visual_facts_pass.py` (`VisualFactsPrior`, `VisualFactsPass`, `ASYNC_ISOLATION_PROFILES`, `is_fast_tier_profile`) was adopted from E20-FUSION without a fork. Slice 1 verifies GPU-tier behavior through a GPU-kind `DescriptionAdapter` stub (`DescriptionAdapterKind.GPU`) rather than only the seeded/fast-tier path: `VisualFactsPass.obtain` on a GPU profile runs a context-free isolation pass and maps the adapter payload into the landed prior shape (caption, objects list, OCR `text`, `source=isolation_pass`, contamination flag false). The Stage-1 prior contract does not carry separate attributes or spatial fields; those are not present on `AdapterResult` either, so no shape extension was made for them. One named gap was fixed in-place: production profile `DescriptionProfile.GPU_QWEN30B` was missing from `ASYNC_ISOLATION_PROFILES` (only `GPU_PHI4` and `FLORENCE_LARGE` were listed), so it incorrectly took the caption-derived fast-tier path; it is now an isolation tier with a dedicated regression test. Extension beyond that membership fix: none.
