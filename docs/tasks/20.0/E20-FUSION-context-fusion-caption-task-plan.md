# E20-FUSION. Context-Fusion Caption Architecture

> **Metadata**
>
> - **Date**: 2026-07-07 EST
> - **Author**: claude-opus-4-8
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `E20-FUSION`
> - **Task Plan Status**: `proposed`
> - **Target Branch**: `feature/e20-fusion`
> - **Review Coverage Target**: 2

---

## E20-FUSION. Context-Fusion Caption Architecture

## Objective

Formalize a **staged fusion contract** — anchor-visual → reconcile-context → synthesize — that decides *which* supplied `ContextPack` fact attaches to *which* visual evidence, and at what altitude (object vs caption), so injected facts weave in faithfully and **pixels win for detector-backed conflicts**. Emit **per-fact attachment provenance**, and skip images marked decorative.

## Intake (new feature)

- **Scope one-pager**: `docs/scopes/context-fusion-caption-enrichment-scope.md`
- **Key Q&A decisions**: `decision #1586` (scope + tech sweep); plan-analyze findings `FUSION-PA-01..04` (fixed).
- **Not-Doing**: external-document/news RAG; trained fusion model; LLM-judge reconciler in MVP; generation-time faithfulness (that is VLM-4); new `ContextPack` fields (E20-9 owns); changing identity-prose-merge internals (E19-4a shipped).

## Problem Statement

Facts come from two sources — the VLM visual pass and the tenant's `ContextPack` (`requests.py:84`: identity/product/…, + brands from E20-BRAND-A) — combined ad-hoc today: context is passed to the adapter (`describe.py:266–268` → `VisualFactsService.describe` → `adapter.describe(context=)`), and the identity-prose merge (`merge_identities`, `merge.py:153`, via `_naming_preview` `describe.py:134`) reflows names into `phrase_boxes`. There is **no principled reconciliation** deciding whether a supplied fact is object-attachable, caption-level, or conflicting → supplied text can overpower the pixels (assessment §1; EVENTA). VLM-4 stops the model *inventing*; this governs how *given* facts are woven.

## Constraints

- **Fusion is a service-layer composition stage in `VisualFactsService`, NOT a new adapter** — it slots between the adapter call (`visual_facts_service.py` `describe()` @ line 113, adapter invoked ~line 148) and `_result_to_response()` (line 201). Ports & adapters; no bespoke route.
- **Deterministic reconciliation first** (heuristic: *measure, don't guess*) — detector-backed pixels-win + altitude rules are code; the LLM-judge reconciler is a later, separately-gated upgrade.
- **Object-attachment is detector-backed only** (FUSION-PA-02) — identities via `merge_identities` (face↔phrase_box `containment_match`, `merge.py:116`), brands via E20-BRAND-A; **no new grounding model**. Events/places → caption-level.
- **Stage-1 cost is tier-shaped** (FUSION-PA-01) — a *separate* visual-in-isolation pass runs only on the async GPU/Qwen tiers; on the fast Florence tier derive visual facts from the single caption (or skip staged fusion). Never double the interactive path.
- **Shared Stage-1 with VLM-4** — the `visual_facts_pass.py` component; whoever of VLM-4/E20-FUSION lands first owns it (FUSION-PA-03).
- **Depends on E20-9 landed** (context-pack contract) + `ContextPack.brands` (E20-BRAND-A).
- **Greenfield / additive** — `VisualFactsResponse` (`responses.py:75`) is `extra="forbid"`; the provenance field is **additive-optional** (mirrors the E19-4a preview trio ~lines 103–105), never `required`.

## Workflow Principles

- **Provenance over prose** — per-fact attachment is a surfaced contract field, not hidden in the caption (heuristic: *leaky abstraction*).
- **Pixels win — scoped to what the deterministic rule can prove (FUSION-PR-03)**: MVP drops/withholds only **detector-backed** conflicts — a name whose face isn't detected is not object-attached (via `merge_identities`); a brand whose logo isn't matched is not attached. Detecting a **semantic** conflict between a caption-level event/place fact and the visual prior (e.g. "garden picnic" vs a wreck) needs the **LLM-judge reconciler (stretch)**, not deterministic code. In MVP an unsupported event/place fact stays caption-level (not asserted as visible), it is not auto-dropped.
- **Reuse the merge** — Stage 3 *calls* `merge_identities`; it does not reimplement E19-4a.

## Terminology

- **Attachment** — a reconciliation decision per supplied fact: `object` (bound to a detected region) / `caption` (scene-level, not asserted visible) / `dropped` (conflicts or unconfirmed).
- **Altitude** — object-level vs caption-level placement of a fact.
- **Visual prior** — structured visual facts from Stage 1 (no `ContextPack`).

## Current State Analysis

- **Works**: describe route `describe_image_multipart` (`describe.py:193`) → context @ `describe.py:266–268` → `VisualFactsService.describe` (`visual_facts_service.py:113`) → `adapter.describe(context=)` → `_result_to_response` (line 201) → `VisualFactsResponse` (`responses.py:75`). Identity-prose merge shipped (`merge_identities` `merge.py:153`; `_naming_preview` `describe.py:134`; `MergeResult` `merge.py:79`; `NamingProvenance` `responses.py:62`).
- **Missing**: any staged reconciliation between visual facts and `ContextPack`; per-fact attachment provenance; a **describe-eligibility / "mark as decorative" gate** (confirmed absent on `describe.py:193` and in the WP `DescribeMediaService`); a shared `visual_facts_pass.py` (VLM-4 Slice 1).
- **`AdapterResult`** (`description_adapter.py:20`) carries `context_sources`/`context_applied`/`phrase_boxes` but **no `context_pack`** — context is input-only; fusion output needs the new response field or the composition stage.

## Target Outcome

A describe request runs: Stage 1 visual prior (separate pass on async tiers; caption-derived on fast tier) → Stage 2 reconciles each `ContextPack` fact to object/caption/dropped (policy veto first, detector-backed attach, detector-backed conflicts dropped, unsupported event/place facts kept caption-level and non-visible) → Stage 3 composes via `merge_identities`, emitting a `VisualFactsResponse` with **per-fact attachment provenance**. A decorative image is skipped before any inference.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Scope: `docs/scopes/context-fusion-caption-enrichment-scope.md`; deps: `docs/tasks/20.0/E20-9-context-pack-contract-and-backend-enrichment-task-plan.md`, `docs/tasks/20.0/E20-BRAND-A-cpu-brand-detection-task-plan.md`.
- Code seams: `scene/application/visual_facts_service.py`, `scene/application/identity_merge/merge.py`, `scene/interface_adapters/http/routers/describe.py`, `scene/interface_adapters/http/schemas/responses.py`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `VisualFactsResponse` (`responses.py:75`) | backend | E19-4a preview trio | Add **additive-optional** per-fact attachment-provenance field (~line 105); `extra="forbid"` → declared, never required | No (greenfield) | schema fixture |
| `VisualFactsService.describe` (`visual_facts_service.py:113`) | backend | adapter→`_result_to_response` | Insert fusion stage between adapter call (~148) and `_result_to_response` (201) | No | service test |
| Identity merge (`merge_identities` `merge.py:153`) | backend | shipped | Stage 3 **calls** it; no internal change | No | reuse test |
| Describe route (`describe.py:193`) | backend/proxy | validation guards only | New **decorative/eligibility gate** (skip before `service.describe`). **Signal path (FUSION-PR-02):** the WP-authoritative "mark as decorative" flag arrives as a new optional `decorative: bool` on `DescribeImageEnvelope` (`requests.py:100`); the **WP plugin (`DescribeMediaService`) is the primary skip** (never POSTs a decorative image), the server gate is the backstop. | No | route + envelope test |
| `ContextPack` (E20-9 + brands) | backend | E20-9 contract | **Consumed**, not defined | must land first | fixture parity |

## Proposed Solution

Four slices: (1) the **shared Stage-1 visual-facts component** (consume VLM-4's `visual_facts_pass.py`, or build it if this lands first); (2) the **Stage-2 reconciliation rule** (detector-backed pixels-win + altitude + detector-backed attach + provenance); (3) **Stage-3 synthesis** — slot the fusion stage into `VisualFactsService.describe`, compose via the existing `merge_identities` path, add the describe-eligibility "mark as decorative" gate; (4) **mis-attachment labels + bake-off + memo**. Sequenced after E20-9 + E20-BRAND-A.

## Files and Surfaces to Change

| Surface | File | Symbol / Function | Change |
| --- | --- | --- | --- |
| backend | `scene/application/visual_facts_pass.py` (new, shared w/ VLM-4) | `VisualFactsPrior`, `VisualFactsPass.describe` (new) | Stage-1 visual facts in isolation (no `ContextPack`) |
| backend | `scene/application/fusion/reconcile.py` (new) | `Attachment`, `AttachmentDecision`, `reconcile_context_facts` (new) | Stage-2 rule → per-fact `Attachment{fact, decision: object\|caption\|dropped, altitude, review_reason}`; detector-backed pixels-win/object attach |
| backend | `scene/application/visual_facts_service.py` | `VisualFactsService.describe`, `VisualFactsService._result_to_response` | Insert fusion stage in `describe()` (between adapter call ~148 and `_result_to_response` 201); thread attachment provenance into `_result_to_response` (201) |
| backend | `scene/interface_adapters/http/schemas/responses.py` | `VisualFactsResponse`, `NamingProvenance` | Additive-optional attachment-provenance field on `VisualFactsResponse` (~line 105), mirroring the existing provenance pattern |
| backend | `scene/interface_adapters/http/schemas/requests.py` | `DescribeImageEnvelope` | Add optional `decorative: bool = False` envelope signal as server backstop |
| backend | `scene/interface_adapters/http/routers/describe.py` | `describe_image_multipart` | Decorative/eligibility gate at top of `describe_image_multipart` (~line 200, before `service.describe`) |
| tests | `scene/tests/test_fusion_reconcile.py`, `scene/tests/test_describe_eligibility.py`, `scene/tests/test_fusion_response_provenance.py` (new) | `test_*` cases (new) | Reconciliation cases, decorative skip, response provenance |
| docs | `docs/tasks/20.0/E20-FUSION-decision-memo.md` (new) | decision memo (new) | Staged-fusion vs ad-hoc, mis-attachment deltas |

## Related Files

| File | Note |
| --- | --- |
| `scene/application/identity_merge/merge.py:153` | `merge_identities` — Stage-3 call target (do not modify) |
| `scene/interface_adapters/http/routers/describe.py:134` | `_naming_preview` — existing merge invocation path |
| `scene/interface_adapters/http/schemas/responses.py:62` | `NamingProvenance` — the provenance-field pattern to mirror |
| `scripts/eval_harness/report.py:318` | `build_reports` — bake-off scorer; corpus `bakeoff_golden.json` |

## Verification Strategy

- Deterministic tests: `.venv/bin/python -m pytest scene/tests/test_fusion_reconcile.py scene/tests/test_describe_eligibility.py scene/tests/test_fusion_response_provenance.py -q` (attach/caption/dropped decisions; detector-backed pixels-win drop with `review_reason`; unsupported event/place facts stay caption-level/non-visible; decorative skip; `extra="forbid"` preserved).
- Contract/fixture: `VisualFactsResponse` fixture asserts the provenance field present + optional.
- Bake-off: `report.build_reports` over `bakeoff_golden.json` for staged-fusion vs ad-hoc; deterministic re-score; new mis-attachment count.
- Manual: the `mcm-planecrash` entry keeps the garden-picnic event/place fact caption-level and non-visible in MVP; detector-backed conflicts such as an unconfirmed face/name are not object-attached and carry `review_reason`; a decorative image returns no description.

## Slice Delivery

### Slice 1: Shared Stage-1 visual-facts component

**Goal**: Structured visual prior in isolation (shared with VLM-4).

Files/functions:

- `scene/application/visual_facts_pass.py:VisualFactsPrior` (new) — typed structured facts for objects/attributes/spatial/text.
- `scene/application/visual_facts_pass.py:VisualFactsPass.describe` (new) — call a `DescriptionAdapter` without `ContextPack`; support caption-derived fast-tier facts.
- `scene/tests/test_visual_facts_pass.py:test_*` (new) — stub-adapter and caption-derived variant coverage.

Changes: consume `visual_facts_pass.py` if VLM-4 landed it; else build it here (owner = first to land). On the fast tier, provide the caption-derived variant.

Proof: `pytest test_visual_facts_pass.py`; structured facts from a stubbed adapter.

### Slice 2: Stage-2 reconciliation rule

**Goal**: Decide attachment + altitude per `ContextPack` fact.

Files/functions:

- `scene/application/fusion/reconcile.py:Attachment` (new) — carries fact id/source, decision, altitude, target evidence, and `review_reason`.
- `scene/application/fusion/reconcile.py:AttachmentDecision` (new) — typed `object` / `caption` / `dropped` decisions.
- `scene/application/fusion/reconcile.py:reconcile_context_facts` (new) — policy veto → detector-backed object attach (identities/brands) → detector-backed conflict drop → otherwise caption-level/non-visible.
- `scene/application/identity_merge/merge.py:merge_identities` — reused by Slice 3, not reimplemented here.
- `scene/tests/test_fusion_reconcile.py:test_*` (new) — object/caption/dropped, detector-backed conflict, unsupported event/place, and policy-veto cases.

Changes: emit `Attachment` records without introducing a new grounding model; only detector-backed conflicts are dropped in MVP, while unsupported event/place facts remain caption-level/non-visible.

Proof: `pytest test_fusion_reconcile.py` (object/caption/dropped cases; detector-backed conflict drop; unsupported event/place stays caption-level; unconfirmed veto).

### Slice 3: Stage-3 synthesis + eligibility gate

**Goal**: Compose the final response with provenance; skip decorative.

Files/functions:

- `scene/application/visual_facts_service.py:VisualFactsService.describe` — insert fusion after adapter generation and before response mapping/persist.
- `scene/application/visual_facts_service.py:VisualFactsService._result_to_response` — include optional attachment provenance on generated responses.
- `scene/interface_adapters/http/schemas/responses.py:VisualFactsResponse` — add optional attachment provenance field while preserving `extra="forbid"`.
- `scene/interface_adapters/http/schemas/requests.py:DescribeImageEnvelope` — add optional `decorative` envelope flag.
- `scene/interface_adapters/http/routers/describe.py:describe_image_multipart` — skip decorative requests before `service.describe`.
- `scene/interface_adapters/http/routers/describe.py:_naming_preview` and `scene/application/identity_merge/merge.py:merge_identities` — reuse existing identity synthesis path.
- `scene/tests/test_fusion_response_provenance.py:test_*`, `scene/tests/test_describe_eligibility.py:test_*` (new) — response provenance and decorative skip coverage.

Changes: insert the fusion stage in `visual_facts_service.py:describe` (between adapter call and `_result_to_response`); compose via the existing `merge_identities` path; add the additive-optional provenance field to `VisualFactsResponse`; add the decorative/eligibility gate at `describe.py:~200`.

Proof: `pytest test_fusion_response_provenance.py test_describe_eligibility.py` (provenance surfaced; decorative → skipped; `extra="forbid"` holds).

### Slice 4: Mis-attachment labels + bake-off + memo

**Goal**: Measure staged fusion vs ad-hoc.

Files/functions:

- `scripts/eval_harness/fusion_runner.py` (new) — drive `VisualFactsService`/fusion stage over `bakeoff_golden.json` and emit acx-eval/v1 run records.
- `scripts/eval_harness/report.py:build_reports` — unchanged scorer for report generation.
- `scene/tests/seed/bakeoff_golden.json` — extend labels with expected attachment altitude/mis-attachment fields.
- `docs/tasks/20.0/E20-FUSION-decision-memo.md` (new) — verdict and measured deltas.

Changes: author mis-attachment labels (which fact should attach where; extend VLM-2B `present_identities`/`must_right` with event/place altitude); a **fusion eval runner** (new — drives `VisualFactsService`/the fusion stage over `bakeoff_golden.json` to emit acx-eval/v1 run-records; **distinct from `bakeoff.py`**, which produces a raw single-VLM caption, not the fusion output — FUSION-PR-01), then score via `build_reports`; `E20-FUSION-decision-memo.md`.

Proof: committed REPORTs + memo with `Must-Right`/insertion/`Easy-Wrong`/mis-attachment deltas; deterministic re-score.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the scope, E20-9 + E20-BRAND-A deps, and the merge/service/response anchors before editing.
- [ ] Confirmed shared Stage-1 ownership vs VLM-4; confirmed E20-9 landed.

### Checklist for Slice 1: Shared Stage-1 component

- [ ] `visual_facts_pass.py` (consumed or built) returns structured visual facts; fast-tier caption-derived variant; test green.

### Checklist for Slice 2: Reconciliation rule

- [ ] `reconcile.py` emits per-fact `Attachment` (object/caption/dropped + altitude + review_reason); detector-backed pixels-win; detector-backed object attach; policy veto first.
- [ ] Reconciliation tests (object/caption/dropped/detector-backed conflict/unsupported event-place/unconfirmed) green.

### Checklist for Slice 3: Synthesis + eligibility

- [ ] Fusion stage inserted in `VisualFactsService.describe`; composes via `merge_identities`.
- [ ] Additive-optional provenance field on `VisualFactsResponse` (`extra="forbid"` preserved).
- [ ] Decorative/eligibility gate at `describe.py:~200`; decorative image skipped.
- [ ] Provenance + eligibility tests green.

### Checklist for Slice 4: Labels + bake-off + memo

- [ ] Mis-attachment labels authored; staged-fusion vs ad-hoc REPORTs committed; memo names the verdict + deltas.

## Review Readiness

- [ ] No boundary-touching change (`VisualFactsResponse`, service stage, describe gate) left without contract/doc/test evidence.
- [ ] Runtime-parity: the fast-tier caption-derived Stage-1 path measured (no interactive-latency regression).
- [ ] Handoff decision records the change, verification, and E20-9/E20-BRAND-A/VLM-4 dependencies per slice.

## Stretch Goals

- [ ] LLM-judge reconciler (separately gated) for event/place altitude decisions.

## Success Criteria

- [ ] One committed bake-off REPORT compares staged fusion vs ad-hoc on `bakeoff_golden.json`, re-score bit-identical.
- [ ] Adopted **iff** it lowers mis-attachment + `Easy-Wrong` without lowering `Must-Right`/insertion.
- [ ] Every description carries per-fact attachment provenance (object/caption/dropped + reason).
- [ ] A **detector-backed** conflict (`mcm-planecrash`: `Slate Willow`'s face not confirmed → the name is **not object-attached**; caption-level stays non-asserted) is handled deterministically with a `review_reason`; semantic event/place conflict-drop is the LLM-judge stretch. A decorative image is skipped.
