# E20-FUSION — Staged Fusion vs Ad-Hoc Decision Memo

> **Metadata**
>
> - **Date**: 2026-07-09 EST
> - **Task**: E20-FUSION (`docs/tasks/20.0/E20-FUSION-context-fusion-caption-task-plan.md` Slice 4)
> - **Corpus**: `scene/tests/seed/bakeoff_golden.json` — 10 images, `expected_attachments` mis-attachment labels
> - **Protocol**: stub/seeded adapters only (no live VLM, no network); `scripts/eval_harness/fusion_runner.py` → acx-eval/v1 run records; scored by **unchanged** `report.build_reports`; re-score bit-identical
> - **Artifacts**: `E20-FUSION-{staged,adhoc}-{run-record,report}.{json,md}` + `*-misattachment.json` (this directory)

## Decision

**Adopt staged fusion** as the describe composition path (already wired in Slices 1–3).

Adoption gate (scope §5 / success criteria): lower **mis-attachment** + Easy-Wrong **without** lowering Must-Right / insertion.

| Metric | **Staged fusion** | Ad-hoc injection baseline |
| --- | --- | --- |
| Items scored | **10/10** | **10/10** |
| Insertion rate | **1.000** | **1.000** |
| Must-Right failures | **0 / 8** rubric-defined | **0 / 8** |
| Policy violations | **0** | **0** |
| Mean gated score | **0.900** | **0.900** |
| **Mis-attachments** (labeled facts) | **0 / 12** | **4 / 12** |
| Easy-Wrong (caption tier) | *vacuous* — `caption_metrics` stubs Easy-Wrong (LLM-judge tier) | same |

Mis-attachment drops **4 → 0** with Must-Right and insertion unchanged → **adopt**.

## What the 4 ad-hoc mis-attachments are

Ad-hoc baseline object-attaches / asserts-visible every expected fact (naive injection):

| Image | Fact | Expected | Ad-hoc actual |
| --- | --- | --- | --- |
| `liam-maloney-painting` | identity Liam Maloney | dropped / non-visible (`unconfirmed_identity`) | object + visible |
| `mcm-planecrash` | identity Maria Correonero | dropped / non-visible (`face_not_detected`) | object + visible |
| `mcm-planecrash` | event Garden picnic | caption / non-visible | object + visible |
| `mcm-planecrash` | place Summer garden | caption / non-visible | object + visible |

Staged fusion matches labels on all 12 labeled facts.

## Success criterion: `mcm-planecrash`

Staged run-record (and `test_mcm_planecrash_success_criterion`):

1. **Identity** `Maria Correonero` → `decision=dropped`, `altitude=none`, `review_reason=face_not_detected` (not object-attached).
2. **Event** Garden picnic → `decision=caption`, `altitude=caption`, `visible=false`.
3. **Place** Summer garden → same caption-level / non-visible pattern.

Semantic event/place *drop* remains the LLM-judge stretch; MVP keeps unsupported event/place caption-level and non-asserted.

## Protocol notes

- Runner is **not** `bakeoff.py` (FUSION-PR-01): fusion_runner drives `VisualFactsService` + Stage-2 reconcile; bakeoff is raw single-VLM captions.
- Face detection/identification REPORT sections use stub identities from labels (same harness pattern as other offline stubs) — not used as fusion discriminators.
- Easy-Wrong is intentionally not scored in the caption hard gate today; product risk for wrong-altitude facts is covered by the **mis-attachment** metric.
- Deterministic re-score: identical run record + entries → bit-identical `build_reports` JSON/MD (covered by `test_build_reports_deterministic_on_fusion_records`).

## Follow-ons (out of this slice)

- LLM-judge reconciler for semantic event/place conflict-drop (stretch).
- Live bake-off against a real detailed-tier adapter once VLM detailed-tier wiring lands (optional corroboration; not required for this adopt gate).
