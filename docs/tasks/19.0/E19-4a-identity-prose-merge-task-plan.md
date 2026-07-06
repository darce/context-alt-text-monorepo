# Task Plan Template

> **Metadata**
>
> - **Date**: 2026-07-06
> - **Author**: Claude Opus 4.8 (claude-opus-4-8)
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` (E19 Context-Aware Image Description, Phase 4 / D6)
> - **Epic Short ID**: E19
> - **Task ID**: `E19-4a`
> - **Target Branch**: `feature/e19-4a`
> - **Review Coverage Target**: 2
>
> **Review coverage note:** Review counts, finding totals, and run histories are not embedded here; query them live via `get_review_coverage(task_ref="E19-4a")` / `list_review_runs(task_ref="E19-4a")`.

---

## E19-4a. Identity→Prose Merge (Deterministic Named-Draft Layer)

## Objective

Add a deterministic, model-independent layer that turns a generated description plus confirmed roster identities into a **named** alt-text draft, server-side, reusing curation the operator already performed. The layer emits **both** a generic and a named draft plus provenance, gated by a tenant naming-agreement flag and a per-`roster_id` suppress list, and **never writes** `_wp_attachment_image_alt` (preview/draft only; the write path stays E19-2).

## Intake (scope intake completed)

- **Scope one-pager**: `docs/scopes/e19-4a-identity-prose-merge-scope.md`
- **Design source**: `docs/assessments/current/identity-prose-merge-design-2026-06-15.md`
- **Not-Doing (confirmed at intake)**: no on-box reflow LLM (Approach D — seam only); no write to `_wp_attachment_image_alt` (E19-2); no prompt-injection/instruction-VLM (Approach C); no per-person opt-in (suppress-list only); no WordPress post/product/SEO context pack or output modes (E19-4b+); no changes to the E19-1 description contract, schema, route, or Florence adapter internals beyond the additive grounding task in S4.

### Plan-Analyze findings folded in (explicit)

- **E19-4A-PA-01 (medium, harness-linkage)** — Named-draft acceptance is bound to the **golden manifest** (`apps/prototype-description-service/scene/tests/seed/golden.json`) and scored by the merged **VLM-2A eval harness**, not by ad-hoc LocalWP screenshots. Regression evidence uses `scripts/eval_harness/caption_metrics.py:score_caption` (fields `inserted_identities`, `missing_identities`, `must_right_failures`/`must_right_pass`, `policy_violation`, `gated_score`) with corpus `insertion_rate`, and `scripts/eval_harness/face_metrics.py:identification_pr` (`wrong_names`, `precision`, `per_identity`). Three acceptance gates: (a) **expected-identities match** — named draft inserts exactly the golden `present_identities`; (b) **insertion precision = never a guessed name** — `identification_pr.wrong_names == []` and `identification_pr.precision == 1.0`; (c) **Must-Right name-string/policy gate** — `score_caption(...).must_right_pass` True and `policy_violation` False on every scored entry. Wrong-name insertion is THE top product risk and is the primary gated metric (`gated_score` zeroes any Must-Right miss or policy violation). See Verification Strategy and Success Criteria.
- **E19-4A-PA-02 (medium, stale coordination blocker)** — The scope's "active `E19-1-REV-A/B/C/D`" coordination risk is **stale**: E19-1 is done and merged to `main`. S4 is therefore re-scoped from "wait for adapter work to settle / wire existing capability" to **adding the `<CAPTION_TO_PHRASE_GROUNDING>` capability that does not exist today** — grep confirms no `PHRASE_GROUNDING` token anywhere in `scene/`. S4 adds the task token + post-processing to `scene/infrastructure/vlm/florence_local_adapter.py::LocalCpuDescriptionAdapter` (named file/function below) and wires the resulting phrase boxes into the merge layer. No cross-agent sequencing dependency remains.
- **E19-4A-PA-03 (low, realizer specificity)** — S2's "grammar-aware NLG reflow" names a concrete **realizer module** (`scene/application/identity_merge/realizer.py::DeterministicNlgRealizer`, implementing the `ReflowRealizer` Protocol seam) and enumerates the reflow rules as **individually testable units**: (R1) article elision + case, (R2) subject vs. possessive/object form, (R3) list aggregation ("Daniel and Sarah"), (R4) repeated-mention coreference (pronoun on later mentions). Each rule is a named method with its own unit test; the positional fallback is a separate realizer behind the same seam.

## Problem Statement

The recognition/roster system already persists confirmed identities with face boxes (`MediaIdentity`, `IdentityCluster`, `IdentityMember`), and E19-1 already produces descriptions. Nothing today joins the two: a generated alt-text draft cannot name a confirmed person even though the operator curated that identity in WordPress. The merge is a spatial-join + grammar-aware string realization — pure Python/SQL, no model cost — but it is **absent**, so operators get only generic prose. The correctness crux is that naming the **wrong** person is a worse failure than not naming at all; the layer must degrade to generic on any ambiguity and prove it does with harness metrics.

## Constraints

- **Deterministic / model-independent** merge layer: a pure function `(caption, phrase_boxes, confirmed_faces, policy) → (generic_draft, named_draft, provenance)`. No VLM dependency in S1–S3.
- **Preview/draft only**: never write `_wp_attachment_image_alt`; that path is **E19-2**. Output is returned in the response, not persisted to WordPress alt text.
- **Consent gate**: a single tenant-level naming-agreement flag (default reflects the signed operator agreement) **plus** a per-`roster_id` suppress list. **No per-person opt-in.**
- **Both drafts + provenance always**: every result returns the generic draft alongside the named draft, and provenance recording which names were injected, from which `cluster_id`/`roster_id`, at what match confidence.
- **Build order**: merge layer first against **seeded/mock phrase boxes + existing recognition data** (S1–S3), Florence grounding added later (S4). S4 depends only on E19-1 (merged), not on any active review task.
- **Reflow is an LLM-ready seam**: the realizer is one implementation behind a `ReflowRealizer` Protocol shaped so a constrained on-box LLM (Qwen2.5-1.5B, Approach D) can drop in later without rework. **No LLM shipped in v1.**
- **No E19-1 contract/schema/route regressions**; S4's only adapter change is the additive `<CAPTION_TO_PHRASE_GROUNDING>` task token + parsing.
- **Harness-first regression evidence** (PA-01): golden manifest + eval harness metrics, not LocalWP screenshots (LocalWP is the S5 demo-diff artifact only).

## Workflow Principles

- **Never guess a name.** Name only when `user_confirmed=TRUE`, `label` present, cluster not dismissed, a single 1:1 high-confidence containment match, agreement active, and the person not suppressed. Any miss → generic phrasing. This is enforced as a gated metric, not a comment.
- **Single source of truth for roster names.** Names are WordPress-authoritative (ADR-003); the backend cluster carries the synced `label`/`roster_id`. Reuse `scripts/eval_harness/naming.py::display_name`/`entity_slug` where the harness needs name strings so golden, seeding, and scoring stay byte-identical.
- **Seam over inline.** Reflow is chosen via the `ReflowRealizer` Protocol, never an `if reflow_mode ==` ladder inside the merge function.
- **Deterministic tests before runtime parity.** S1–S3 land pure-Python unit/integration coverage; harness scoring (PA-01) is the regression gate; LocalWP is demo evidence only (S5).

## Terminology

- **Phrase box**: a `<CAPTION_TO_PHRASE_GROUNDING>` bounding box per noun phrase of the model's own caption, with its character span. Mocked/seeded in S1–S3; real in S4.
- **Face box**: `MediaIdentity` pixel bbox of a detected face (small); source for the confirmed-identity side of the match.
- **Containment match**: face-box center inside the smallest person-phrase box, `area(face) ≪ area(person)`, 1:1 only. IoU is explicitly wrong here.
- **Named draft / generic draft**: the two prose outputs always returned together.
- **Provenance**: the per-result record of injected names, source `cluster_id`/`roster_id`, and match confidence.
- **Reflow seam**: the `ReflowRealizer` Protocol; v1 impl is `DeterministicNlgRealizer` (+ positional fallback).
- **Suppress list**: per-`roster_id` do-not-name escape hatch (not a per-person opt-in).

## Current State Analysis

- **Works today**: recognition/roster persistence (`db/models/identity.py`: `MediaIdentity` lines 41–101, `IdentityCluster` lines 104–176, `IdentityMember` lines 279–306); E19-1 description pipeline (`scene/interface_adapters/http/routers/describe.py::describe_image_multipart`, `scene/application/description_adapter.py::AdapterResult`/`DescriptionAdapter`); the merged VLM-2A eval harness (`scripts/eval_harness/` — `manifest.py`, `remote_client.py`, `caption_metrics.py`, `face_metrics.py`, `report.py`, `schema.py`, plus `draft_labels.py`, `naming.py`, `seed_roster.py`, `cli.py`) with golden manifest `scene/tests/seed/golden.json` (roster + entries carrying `present_identities`, `must_right`, `easy_wrong`, `policy.recognition_enabled`).
- **Absent / to build**: no identity→prose merge module (`grep` for `named_prose`/`reflow`/`containment` in `scene/` returns nothing); no `<CAPTION_TO_PHRASE_GROUNDING>` in the Florence adapter (`grep PHRASE_GROUNDING` in `scene/` is empty — the adapter only runs `_CAPTION_TASK="<MORE_DETAILED_CAPTION>"` and `_OD_TASK="<OD>"`); no tenant naming-agreement flag (`db/models/tenant.py::Tenant` has no such column); no suppress-list model.
- **Misleading assumption to correct**: the scope note names "active `E19-1-REV-A/B/C/D`" as a coordination blocker for S4 — **stale** (E19-1 is done/merged). See PA-02; S4 has no cross-agent dependency.

## Target Outcome

Given a `media_id` with ≥1 `user_confirmed` identity and the agreement flag on, the describe path returns a preview payload containing a generic draft, a named draft where each named region maps 1:1 to a confirmed face, and provenance. Ambiguous/low-confidence/suppressed/agreement-off → the named draft is identical to generic (no name), **never a guessed name**. The merge layer is a pure function with unit/integration coverage against seeded + real recognition fixtures, passing with no VLM dependency (S1–S3), and its named-draft correctness is regression-gated by the eval harness against `golden.json` (PA-01). S4 adds real Florence phrase boxes; S5 captures a same-image generic-vs-named diff on LocalWP as demo evidence.

## Context Loading

- Scope: `docs/scopes/e19-4a-identity-prose-merge-scope.md`
- Design: `docs/assessments/current/identity-prose-merge-design-2026-06-15.md`
- Identity model: `apps/prototype-description-service/db/models/identity.py`
- Tenant model (consent flag home): `apps/prototype-description-service/db/models/tenant.py::Tenant`
- Describe surface: `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py`, `apps/prototype-description-service/scene/application/description_adapter.py`
- Florence adapter (S4): `apps/prototype-description-service/scene/infrastructure/vlm/florence_local_adapter.py`
- Eval harness + golden: `apps/prototype-description-service/scripts/eval_harness/{caption_metrics,face_metrics,manifest,report,schema,naming,draft_labels}.py`, `apps/prototype-description-service/scene/tests/seed/golden.json`
- Contract (do not change): `docs/workbay/contracts/image-description-api.md`
- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`
- Handoff/MCP: task ref `E19-4a`; open findings via `review_findings(review={"operation":"list","status":"open","task_ref":"E19-4a"})`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `POST /scene/describe/multipart` preview response | backend | `docs/workbay/contracts/image-description-api.md` (`VisualFactsResponse`) | **Additive** optional preview fields: `generic_draft`, `named_draft`, `naming_provenance`. No removal/rename of E19-1 fields. | yes — additive only; absent when agreement off/no confirmed identities | `scene/tests/test_describe_route.py` + response-schema parity test |
| Identity SQL join | backend | `db/models/identity.py` (`MediaIdentity`/`IdentityMember`/`IdentityCluster`) read-only | none (read-only join, filter `user_confirmed=TRUE`, `label IS NOT NULL`, `dismissed_at IS NULL`) | no | merge integration test on seeded fixtures |
| Tenant naming-agreement flag | backend | `db/models/tenant.py::Tenant` | **Additive** column `naming_agreement_enabled` (bool, default per signed agreement) | no (greenfield: edit `001_identity_schema.py` directly) | model/migration test |
| Per-`roster_id` suppress list | backend | none | **New** `IdentityNameSuppression` model (tenant_id, roster_id) | no (greenfield) | suppress-gate unit test |
| Florence adapter grounding (S4) | backend | `florence_local_adapter.py::LocalCpuDescriptionAdapter` | **Additive** `<CAPTION_TO_PHRASE_GROUNDING>` task token + parse; no change to existing `<MORE_DETAILED_CAPTION>`/`<OD>` behavior | no | `scene/tests/test_local_vlm_adapter.py` extension |

## Proposed Solution

Build a new `scene/application/identity_merge/` package as a pure, model-independent merge layer, then gate and surface it, then wire real grounding, then demo it.

1. **Merge core** (`merge.py`): `merge_identities(caption, phrase_boxes, confirmed_faces, policy) -> MergeResult`. SQL join by `media_id` supplies `confirmed_faces` (`MediaIdentity` bbox/confidence + `IdentityCluster.label`/`roster_id`, filtered). Normalize all boxes to `[0,1]` fractions of original `W×H`; containment-match face-center→smallest person-phrase box, 1:1 only.
2. **Reflow seam** (`realizer.py`): `ReflowRealizer` Protocol; `DeterministicNlgRealizer` (R1–R4 rules) as v1 impl; `PositionalFallbackRealizer` when grounding absent/low-confidence. Shaped for a later constrained LLM realizer with no rework.
3. **Consent + provenance** (`policy.py`, models): tenant `naming_agreement_enabled` + `IdentityNameSuppression` (per `roster_id`); `NamingProvenance` on every result; always emit generic + named drafts.
4. **Florence grounding** (S4): add `<CAPTION_TO_PHRASE_GROUNDING>` to the adapter; feed real phrase boxes into the merge core; coordinate-fidelity check full-res recognition vs. downsampled description.
5. **Demo evidence** (S5): LocalWP same-image generic-vs-named diff.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend (new) | `apps/prototype-description-service/scene/application/identity_merge/__init__.py` | Package init; export `merge_identities`, `MergeResult`, `ReflowRealizer`. |
| backend (new) | `.../identity_merge/merge.py` | `merge_identities(...)`; `normalize_bbox(...)`; `containment_match(...)`; `MergeResult` dataclass. |
| backend (new) | `.../identity_merge/realizer.py` | `ReflowRealizer` Protocol; `DeterministicNlgRealizer` (R1–R4 methods); `PositionalFallbackRealizer`. |
| backend (new) | `.../identity_merge/policy.py` | `NamingPolicy` (agreement flag + suppress set + thresholds); `resolve_naming_allowed(...)`; `NamingProvenance` dataclass. |
| backend (new) | `.../identity_merge/join.py` | `load_confirmed_faces(session, tenant_id, media_id) -> list[ConfirmedFace]` — the read-only join. |
| backend | `apps/prototype-description-service/db/models/tenant.py` | Add `naming_agreement_enabled` bool column to `Tenant`. |
| backend (new) | `apps/prototype-description-service/db/models/identity.py` | Add `IdentityNameSuppression` model (tenant_id, roster_id, created_at) + `__all__` entry. |
| backend | `apps/prototype-description-service/db/migrations/001_identity_schema.py` | Schema changes directly (greenfield, no migration file). |
| backend | `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py` | Surface `generic_draft`/`named_draft`/`naming_provenance` in the preview response (no alt-text write). |
| backend | `apps/prototype-description-service/scene/infrastructure/vlm/florence_local_adapter.py` | S4: add `_PHRASE_GROUNDING_TASK="<CAPTION_TO_PHRASE_GROUNDING>"`, parse boxes in `_run_task`/`describe`, expose phrase boxes on `AdapterResult`. |
| backend | `apps/prototype-description-service/scene/application/description_adapter.py` | S4: add optional `phrase_boxes` field to `AdapterResult`. |
| tests (new) | `apps/prototype-description-service/scene/tests/test_identity_merge_*.py` | Unit + integration per slice (see checklists). |
| tests | `apps/prototype-description-service/scene/tests/test_describe_route.py` | Assert additive preview fields. |
| harness (regression) | reuse `scripts/eval_harness/caption_metrics.py`, `face_metrics.py`, `golden.json` | PA-01 acceptance scoring — no new metric code unless a gap is found; extend golden entries' `must_right`/`present_identities` only if fixtures require. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scene/application/seeded_adapter.py` | Seeded adapter provides mock captions/boxes for S1–S3 fixtures. |
| `apps/prototype-description-service/scripts/eval_harness/draft_labels.py::generate_draft_manifest` | Produces draft manifest the harness scores. |
| `apps/prototype-description-service/scripts/eval_harness/naming.py` | `entity_slug`/`display_name`/`IMAGE_EXTS` — reuse for byte-identical roster names. |
| `apps/prototype-description-service/scripts/eval_harness/schema.py` | `SCHEMA="acx-eval/v1"`, `DocKind` — eval-artifact identifiers. |
| `docs/workbay/contracts/image-description-api.md` | E19-1 contract — additive-only reference. |

## Verification Strategy

- **Deterministic tests** (S1–S3, no VLM):
  - `cd apps/prototype-description-service && uv run pytest scene/tests/test_identity_merge_merge.py scene/tests/test_identity_merge_realizer.py scene/tests/test_identity_merge_policy.py scene/tests/test_identity_merge_join.py -q`
- **Harness regression gate (PA-01)** — bind named-draft acceptance to `golden.json`:
  - Expected-identities match: for each entry, `score_caption(named_draft, present_identities=..., must_right=..., easy_wrong=..., recognition_enabled=...).inserted_identities == present_identities` and `missing_identities == []` for the confirmed set.
  - Insertion precision (never a guessed name): `identification_pr(items).wrong_names == []` and `identification_pr(items).precision == 1.0` (or `None` when no positives); assert no name appears in a draft whose entry lacks it.
  - Must-Right name-string/policy gate: `score_caption(...).must_right_pass is True` and `.policy_violation is False` on every scored entry; corpus `gated_score` never zeroed by a merge-injected name; `insertion_rate(scores)` reported as coverage (not a pass/fail gate).
  - Command: `cd apps/prototype-description-service && uv run pytest scene/tests/test_identity_merge_harness_gate.py -q` (new test that runs the merge over golden fixtures and asserts the three gates via `caption_metrics`/`face_metrics`).
- **Contract/fixture verification**:
  - `uv run pytest scene/tests/test_describe_route.py scene/tests/test_response_schema_parity.py -q` — additive preview fields present when eligible, absent otherwise.
- **Runtime-parity (S4 only)**:
  - `uv run pytest scene/tests/test_local_vlm_adapter.py -q` for the grounding task; coordinate-fidelity assertion that normalized boxes align across full-res recognition and downsampled description.
- **Manual verification (S5 demo evidence only, not the regression gate)**:
  - LocalWP media: same image, capture generic vs. identity-named preview draft as a context-diff artifact.

## Slice Delivery

### Slice 1: Merge core — join + normalize + containment match

**Goal**: A pure `merge_identities(...)` that, given seeded phrase boxes + confirmed faces, produces 1:1 name↔region associations (no reflow yet).

Changes:
- `identity_merge/join.py::load_confirmed_faces` — read-only SQL join (`MediaIdentity`→`IdentityMember`→`IdentityCluster`), filter `user_confirmed=TRUE`, `label IS NOT NULL`, `dismissed_at IS NULL`.
- `identity_merge/merge.py::normalize_bbox` (pixels→`[0,1]` of orig `W×H`), `containment_match` (face-center in smallest person box, 1:1), `merge_identities` returning association list + `MergeResult` skeleton.
- Unit tests: normalization resolution-independence; containment picks smallest box; ambiguous many-to-one → no match; area-ratio guard.

Proof:
- `uv run pytest scene/tests/test_identity_merge_merge.py scene/tests/test_identity_merge_join.py -q` green on seeded fixtures.

### Slice 2: Grammar-aware NLG reflow behind the seam (PA-03)

**Goal**: Names read naturally in prose via a deterministic realizer behind the `ReflowRealizer` seam, with a positional fallback.

Changes:
- `identity_merge/realizer.py::ReflowRealizer` Protocol (the LLM-ready seam) + `DeterministicNlgRealizer` implementing enumerated, individually-tested rules: **R1** article elision + case, **R2** subject vs. possessive/object form, **R3** list aggregation ("Daniel and Sarah"), **R4** repeated-mention coreference (pronoun on later mentions).
- `PositionalFallbackRealizer` (order faces left→right, prepend/append) selected when grounding absent/low-confidence — Approach B.
- `merge_identities` calls the injected realizer to produce the named draft; generic draft is the untouched caption.
- Unit tests: one per rule R1–R4 + fallback; seam swap (fake realizer) proves no inline mode ladder.

Proof:
- `uv run pytest scene/tests/test_identity_merge_realizer.py -q` green; each of R1–R4 has a named failing-then-passing assertion.

### Slice 3: Consent gate + provenance + both-drafts output

**Goal**: Naming is allowed only under the resolved consent model, provenance is recorded, and both drafts always return — surfaced on the describe preview.

Changes:
- `Tenant.naming_agreement_enabled` (default per signed agreement) in `tenant.py` + `001_identity_schema.py`.
- `IdentityNameSuppression` model (tenant_id, roster_id) in `identity.py` + `__all__`.
- `identity_merge/policy.py::NamingPolicy` + `resolve_naming_allowed(...)` enforcing: `user_confirmed` + `label` present + 1:1 high-confidence containment + detection/grounding thresholds + agreement active + not suppressed; any miss → generic. `NamingProvenance` (injected names, `cluster_id`/`roster_id`, match confidence) on every result.
- `describe.py` surfaces additive `generic_draft`/`named_draft`/`naming_provenance` (preview only — **no** `_wp_attachment_image_alt` write).
- Tests: agreement-off suppresses; suppress-list by `roster_id` suppresses; provenance present on every named result; generic always returned; route additive-fields test.

Proof:
- `uv run pytest scene/tests/test_identity_merge_policy.py scene/tests/test_describe_route.py -q` green.
- **Harness gate (PA-01)**: `uv run pytest scene/tests/test_identity_merge_harness_gate.py -q` — expected-identities match, `wrong_names==[]`/`precision==1.0`, `must_right_pass`/no `policy_violation` across `golden.json`.

### Slice 4: Florence `<CAPTION_TO_PHRASE_GROUNDING>` grounding (re-scoped per PA-02)

**Goal**: Add the phrase-grounding capability the adapter lacks today and feed real phrase boxes into the merge core.

Changes:
- `florence_local_adapter.py`: add `_PHRASE_GROUNDING_TASK="<CAPTION_TO_PHRASE_GROUNDING>"`; run it in `_run_task`/`describe`; parse `post_process_generation` phrase spans + boxes; expose them on `AdapterResult`.
- `description_adapter.py::AdapterResult`: add optional `phrase_boxes` field (default empty — E19-1 callers unaffected).
- Merge core consumes real phrase boxes; `PositionalFallbackRealizer` engages when grounding absent/low-confidence.
- Coordinate-fidelity check: normalized boxes align across full-res recognition and downsampled description.
- **No cross-agent sequencing** — E19-1 is merged; the stale `E19-1-REV-A/B/C/D` blocker does not apply.

Proof:
- `uv run pytest scene/tests/test_local_vlm_adapter.py -q` green (grounding task parses; existing caption/OD unchanged); coordinate-fidelity assertion passes.

### Slice 5: Context-diff demo evidence on LocalWP

**Goal**: Capture the same-image generic-vs-named preview draft as demo evidence (not the regression gate).

Changes:
- Run the describe preview on a LocalWP image with ≥1 confirmed identity, agreement on; capture generic vs. named draft + provenance.
- Record the artifact reference in the handoff decision (evidence path), not pasted into this plan.

Proof:
- Context-diff artifact captured; the PA-01 harness gate (S3) remains the pass/fail regression evidence.

## Consolidated Checklist

> **Checklist scope rule:** describes work delivered, not finding status. Finding status is queried live via `review_findings(review={"operation":"list","status":"open","task_ref":"E19-4a"})` or `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded scope, design, identity/tenant models, describe surface, and eval-harness anchors before editing.
- [ ] Recorded boundary ownership: additive preview response fields + additive Tenant column + new suppress model + additive Florence task (compatibility expectations in the table above).

### Checklist for Slice 1: Merge core

- [ ] `load_confirmed_faces` join implemented with the four filters (`user_confirmed`, `label` present, not dismissed, `media_id`).
- [ ] `normalize_bbox` + `containment_match` + `merge_identities` skeleton implemented (1:1, smallest-box, area-ratio guard).
- [ ] Unit tests: normalization resolution-independence, smallest-box selection, ambiguous→no-match; green.

### Checklist for Slice 2: NLG reflow behind the seam (PA-03)

- [ ] `ReflowRealizer` Protocol + `DeterministicNlgRealizer` with methods for R1 (article/case), R2 (subject/possessive), R3 (aggregation), R4 (coreference).
- [ ] `PositionalFallbackRealizer` implemented and selected on absent/low-confidence grounding.
- [ ] One unit test per rule R1–R4 + fallback + seam-swap; green.

### Checklist for Slice 3: Consent gate + provenance

- [ ] `Tenant.naming_agreement_enabled` + `IdentityNameSuppression` added (schema edited directly, greenfield).
- [ ] `NamingPolicy`/`resolve_naming_allowed` enforces the full name-only-when-all-hold rule; degrades to generic otherwise.
- [ ] `NamingProvenance` on every named result; both drafts always returned; describe preview surfaces additive fields (no alt-text write).
- [ ] Policy + route tests green.
- [ ] **PA-01 harness gate** `test_identity_merge_harness_gate.py` asserts expected-identities match, `wrong_names==[]`/`precision==1.0`, `must_right_pass`/no `policy_violation` over `golden.json`.

### Checklist for Slice 4: Florence grounding (PA-02)

- [ ] `<CAPTION_TO_PHRASE_GROUNDING>` task token added to `LocalCpuDescriptionAdapter`; boxes parsed and exposed on `AdapterResult.phrase_boxes`.
- [ ] Existing `<MORE_DETAILED_CAPTION>`/`<OD>` behavior unchanged; E19-1 callers unaffected (optional field default).
- [ ] Coordinate-fidelity check (full-res vs. downsampled) passes; adapter test green.

### Checklist for Slice 5: LocalWP demo evidence

- [ ] Same-image generic-vs-named preview draft + provenance captured on LocalWP.
- [ ] Evidence path recorded in the handoff decision (not pasted into the plan).

## Review Readiness

- [ ] No boundary-touching change (preview response, Tenant column, suppress model, Florence task) lacks matching contract-note/test evidence.
- [ ] Named-draft correctness is regression-gated by the eval harness against `golden.json` (PA-01), not by LocalWP screenshots.
- [ ] Runtime-parity S4 coordinate-fidelity check included where unit tests could mask real box misalignment.
- [ ] Handoff decision records the change, verification (harness gate + deterministic tests), and the additive contract implications.

## Stretch Goals

- [ ] Report the corpus `insertion_rate` trend in the harness `report.py` output as a coverage signal (non-blocking).
- [ ] Golden fixtures gain a mixed roster+stranger entry to exercise `identification_pr.true_rejections`.

## Success Criteria

- [ ] Given a `media_id` with ≥1 `user_confirmed` identity and agreement on, the describe preview returns a named draft where each named region maps 1:1 to a confirmed face, plus the generic draft and provenance.
- [ ] Ambiguous / low-confidence / suppressed / agreement-off → named draft carries **no** name (identical to generic); **never a guessed name**.
- [ ] **PA-01 harness gate passes** on `golden.json`: expected-identities match; `identification_pr.wrong_names == []` and `precision == 1.0`; `score_caption(...).must_right_pass` True and `policy_violation` False on every scored entry (no `gated_score` zeroed by a merge-injected name).
- [ ] Merge layer unit/integration tests pass with **no VLM dependency** (S1–S3).
- [ ] S4 adds `<CAPTION_TO_PHRASE_GROUNDING>` to the Florence adapter with existing caption/OD behavior intact and coordinate fidelity verified.
- [ ] S5 context-diff demo artifact (same image, generic vs. named) captured on LocalWP and referenced from the handoff decision.
