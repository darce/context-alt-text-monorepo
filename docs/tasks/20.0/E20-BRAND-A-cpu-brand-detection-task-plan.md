# E20-BRAND-A. CPU Brand/Logo Detection Tier A

> **Metadata**
>
> - **Date**: 2026-07-07 EST
> - **Author**: claude-opus-4-8
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `E20-BRAND-A`
> - **Target Branch**: `feature/e20-brand-a`
> - **Review Coverage Target**: 2

---

## E20-BRAND-A. CPU Brand/Logo Detection Tier A

## Objective

Let a tenant register a brand/logo (upload or bbox), then auto-detect and surface its instances in the existing confirm/reject curation workbench, and — once confirmed — name the brand in generated captions via a new `ContextPack.brands` surface. Detection is **CPU-only classical template matching** (OpenCV features + LightGlue + homography), no training, no GPU.

## Intake (new feature)

- **Scope one-pager**: `docs/scopes/opencv5-brand-detection-tier-a-scope.md`
- **Key Q&A decisions**: `decision #1568` (`scope_intake_opencv5_and_oci_bursty_gpu_tier`); plan-analyze findings `VLM3-PA-06/07/08` (all fixed) refined this scope.
- **Not-Doing**: OWLv2 / open-vocab detection (GPU Tier B, VLM-3 slice 6); OpenCV 5 incumbent dependency swap; new clustering algorithm (HDBSCAN untouched); non-rigid/product/scene-text brands; brand analytics/bulk-UI beyond confirm/reject; PG18/19 work.

## Problem Statement

Captions can name **people** (curated identity clusters → `ContextPack.identity` → identity-prose merge), but there is **no non-face entity detection** — no way to have "the Acme logo" recognized and named. The data model is already brand-ready (`media_identities.identity_type` permits `'brand'`), but nothing populates brand rows, no template store exists, and `ContextPack` has no `brands` field. Tier A closes this with the cheapest correct mechanism, reusing the human-in-the-loop curation loop rather than trusting a detector.

## Constraints

- **Confirm-before-context**: a detected brand never enters a caption until a human confirms it (same stance as person naming).
- **Reuse the curation loop, not a new pipeline**: template matching is classification against a known template — **no HDBSCAN / clustering**. Reuse `user_confirmed` / `confirmation_source` / the workbench.
- **Greenfield schema**: no migrations; new tables/columns go directly in `db/migrations/versions/001_identity_schema.py`. `media_identities.identity_type` **already permits `'brand'`** (`001_identity_schema.py:256`) — no enum change.
- **Sequencing**: the `ContextPack.brands` context surface depends on the E20-9 context-pack contract (`docs/tasks/20.0/E20-9-context-pack-contract-and-backend-enrichment-task-plan.md`); land it after E20-9's contract, before VLM-3 slice 6 consumes it.
- **OpenCV pin**: `opencv-python>=4.12,<4.15` today. ORB works on 4.x; ALIKED/LightGlue require OpenCV 5 — **gated on a separate spike**, so Tier A ships on ORB and treats ALIKED as an upgrade.
- **RLS / tenant scoping**: `brand_templates` is tenant-scoped like every identity table.

## Workflow Principles

- **Human gate over detector accuracy**: precision matters less than confirm-before-context.
- **Bound per-tenant scan cost**: pgvector shortlist before keypoint match; cap templates per tenant.
- **Fail loud on low confidence**: below the min-size floor, surface a `review_reason`, never silently drop.

## Terminology

- **Template**: a registered logo crop → keypoints + descriptors (blob) + a global crop embedding (pgvector).
- **Instance**: a detected occurrence — a `media_identities` row with `identity_type='brand'`, bbox, confidence.
- **Confirmed brand**: an instance a human accepted; its name (WP-authoritative) is eligible for `ContextPack.brands`.

## Current State Analysis

- **Works**: `media_identities` (`001_identity_schema.py:212`) with bbox (`:228`), `embedding Vector` (`:233`), `identity_type IN ('face','brand','pose','gait')` (`:256`); `identity_clusters` (`:296`) with `user_confirmed` (`:332`), `confirmation_source` (`:334`, values `label/merge/assignment/split/reject`); the confirm/reject workbench + REST (`recognition/interface_adapters/http/routers/clusters_admission.py`, `suggestions.py`); `ContextPack` (`scene/interface_adapters/http/schemas/requests.py:84`) with `identity`, `product` fields.
- **Missing**: no `brand_templates` table; no brand template registration (upload/bbox); no CPU matcher; no `ContextPack.brands` field; no brand rows populated.
- **Misleading**: `identity_type` enum already lists `'brand'` — do not "add" it (VLM3-PA-06); it is unused today.

## Target Outcome

Tenant registers "Acme" (logo upload or a bbox on existing media) → a template is stored → on later upload/backfill the matcher finds Acme, writes an unconfirmed `identity_type='brand'` instance with bbox + confidence → it appears in the workbench → tenant confirms → the brand name flows into `ContextPack.brands` → the caption names it ("…in front of the Acme logo"). Low-confidence/tiny detections surface a `review_reason` instead of a silent drop.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Contracts: `docs/tasks/20.0/E20-9-context-pack-contract-and-backend-enrichment-task-plan.md`; ADR-003 (WP-authoritative naming).
- Handoff/MCP: task `E20-BRAND-A`; decision `#1568`; scope `docs/scopes/opencv5-brand-detection-tier-a-scope.md`.
- Code seams: `db/migrations/versions/001_identity_schema.py`, `recognition/interface_adapters/http/routers/clusters_admission.py`, `scene/interface_adapters/http/schemas/requests.py`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `ContextPack` (`requests.py:84`) | backend/proxy | E20-9 context-pack contract | Add `brands` field (`extra="forbid"` → explicit); decide sibling-list vs under `product` | No (greenfield) | schema test + fixture |
| Identity schema (`001_identity_schema.py`) | backend | brand-ready enum | New `brand_templates` table + `identity_type='brand'` instance rows (no enum change) | No | migration load test |
| Curation REST (recognition routers) | backend | confirm/reject for faces | Brand instances reuse confirm/reject; registration endpoint net-new | No | route test |
| WordPress brand naming | proxy/WP | roster-person naming (ADR-003) | Brand name authored in WP like a person | No | manual |

## Proposed Solution

Four slices: (1) schema + registration + curation reuse — `brand_templates`, template registration (upload/bbox), instances surfaced in the existing confirm/reject workbench; (2) the CPU matcher — ORB keypoints + LightGlue/BF + homography RANSAC → bbox + confidence, min-size floor + `review_reasons`; (3) `ContextPack.brands` context surface + composition naming (after E20-9); (4) descriptor benchmark (ORB vs ALIKED+LightGlue) that gates whether the OpenCV 5 dependency is pulled in. Slices 1–2 stand alone; slice 3 carries the E20-9 dependency; slice 4 is the spike that gates the ALIKED upgrade.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| schema | `db/migrations/versions/001_identity_schema.py` | New `brand_templates` table (tenant-scoped, RLS, descriptor blob + crop embedding); no `identity_type` enum change |
| backend | `recognition/application/brand/template_store.py` (new) | Register/list/delete templates; pgvector shortlist |
| backend | `recognition/application/brand/matcher.py` (new) | ORB + LightGlue/BF + homography RANSAC → bbox + inlier-ratio confidence; min-size floor |
| backend | `recognition/interface_adapters/http/routers/brands.py` (new) | Registration endpoint (upload/bbox); brand instances reuse confirm/reject from `clusters_admission.py` |
| backend | `scene/interface_adapters/http/schemas/requests.py` | Add `brands` to `ContextPack` (`:84`) |
| backend | `scene/application/description_adapter.py` / composition | Consume `ContextPack.brands` in caption composition (name like a person) |
| tests | `tests/test_brand_matcher.py`, `test_brand_templates.py`, `test_contextpack_brands.py` (new) | Matcher precision, template CRUD, context surface |
| docs | `docs/tasks/20.0/E20-BRAND-A-descriptor-benchmark-<date>.json` (new) | ORB vs ALIKED+LightGlue precision on a synthetic logo set |

## Related Files

| File | Note |
| --- | --- |
| `db/migrations/versions/001_identity_schema.py:296` | `identity_clusters` `user_confirmed`/`confirmation_source` — curation-state pattern to mirror |
| `recognition/interface_adapters/http/routers/suggestions.py` | Existing confirm/reject surface |
| `scene/interface_adapters/http/schemas/requests.py:74` | `IdentityContext` — the pattern `ContextPack.brands` mirrors |
| `pyproject.toml` (`opencv-python>=4.12,<4.15`) | ORB available now; ALIKED needs OpenCV 5 (spike) |

## Verification Strategy

- Deterministic tests:
  - `.venv/bin/python -m pytest tests/test_brand_matcher.py tests/test_brand_templates.py tests/test_contextpack_brands.py -q`
- Contract/fixture verification:
  - `ContextPack` schema fixture asserts `brands` present and `extra="forbid"` still holds.
  - Migration load test: `brand_templates` created; a `identity_type='brand'` row inserts under the existing unique constraint.
- Runtime-parity:
  - Descriptor benchmark (Slice 4) over a synthetic logo set; emit E19-1-format JSON.
- Manual verification:
  - Register a logo → upload an image containing it → unconfirmed brand instance appears in the workbench → confirm → caption names the brand; tiny logo → `review_reason`, not a drop.

## Slice Delivery

### Slice 1: Schema + registration + curation reuse

**Goal**: Register a brand template and surface detected instances in the existing confirm/reject workbench.

Changes:
- `brand_templates` table (`001_identity_schema.py`): tenant-scoped, RLS, descriptor blob + crop embedding; instance rows use `identity_type='brand'` (no enum change).
- `template_store.py` (register/list/delete) + `brands.py` registration endpoint (upload or bbox on existing media); brand instances reuse `clusters_admission.py` confirm/reject.

Proof:
- `pytest test_brand_templates.py` green; a registered template + a seeded brand instance appears as unconfirmed in the workbench REST; confirm/reject flips `user_confirmed`.

### Slice 2: CPU matcher

**Goal**: Detect a registered logo in an image on CPU and write an instance with bbox + confidence.

Changes:
- `matcher.py`: ORB keypoints + LightGlue/BF match + homography RANSAC → bbox + inlier-ratio confidence; **min-size floor (provisional ~48 px shorter edge)** and inlier-ratio threshold (**provisional ~0.25**, tuned in Slice 4); below-floor → `review_reason`, not a drop; pgvector shortlist bounds per-tenant scan cost.

Proof:
- `pytest test_brand_matcher.py` green (positive match on a planted logo, no-match on a clean image, tiny-logo → `review_reason`); scan cost bounded by template count.

### Slice 3: `ContextPack.brands` + composition naming

**Goal**: Confirmed brands reach the caption.

Changes:
- Add `brands` to `ContextPack` (`requests.py:84`), WP-collected + policy-filtered, mirroring `IdentityContext`; caption composition names the brand like a person. **Depends on E20-9 context-pack contract.**

Proof:
- `pytest test_contextpack_brands.py` green (schema `extra="forbid"` holds; a confirmed brand renders into the composed caption); fixture parity with WP payload.

### Slice 4: Descriptor benchmark (ORB vs ALIKED+LightGlue)

**Goal**: Decide the descriptor + whether to pull in OpenCV 5.

Changes:
- Synthetic logo set + benchmark harness (E19-1 JSON format) measuring ORB vs ALIKED+LightGlue precision; pin the min-size floor + inlier threshold from Slice 2.

Proof:
- Committed benchmark artifact; a recorded decision on ORB-only (ship on OpenCV 4.x) vs ALIKED upgrade (gated on the OpenCV 5 spike).

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the scope note, E20-9 context-pack contract, and identity-schema/curation anchors before editing.
- [ ] Recorded the `ContextPack` contract change (add `brands`) and its E20-9 sequencing.

### Checklist for Slice 1: Schema + registration + curation reuse

- [ ] `brand_templates` table (tenant-scoped, RLS, descriptor blob + embedding); no `identity_type` enum change.
- [ ] Template register/list/delete + registration endpoint (upload/bbox); brand instances reuse confirm/reject.
- [ ] Migration load + workbench route tests green.

### Checklist for Slice 2: CPU matcher

- [ ] ORB + LightGlue/BF + homography RANSAC → bbox + confidence; min-size floor + `review_reasons`.
- [ ] pgvector shortlist bounds per-tenant scan cost.
- [ ] Matcher tests (positive/negative/tiny) green.

### Checklist for Slice 3: ContextPack.brands + composition

- [ ] `brands` on `ContextPack` (`extra="forbid"` preserved); composition names the brand.
- [ ] Depends on E20-9; context-surface test green.

### Checklist for Slice 4: Descriptor benchmark

- [ ] Synthetic-logo benchmark artifact (ORB vs ALIKED+LightGlue); min-size/inlier thresholds pinned.
- [ ] Recorded ORB-only vs ALIKED-upgrade decision (OpenCV 5 gated).

## Review Readiness

- [ ] No boundary-touching change (`ContextPack.brands`, schema, curation REST) left without contract/doc/fixture evidence.
- [ ] Confirm-before-context invariant covered by a test (unconfirmed brand never enters a caption).
- [ ] Handoff decision records the change, verification, and E20-9 sequencing per slice.

## Stretch Goals

- [ ] ALIKED + LightGlue descriptor upgrade (gated on the OpenCV 5 spike).
- [ ] Back-fill scan over existing media on template registration.

## Success Criteria

- [ ] A registered logo is detected in a new image and surfaces as an unconfirmed `identity_type='brand'` instance in the workbench.
- [ ] Confirming the instance makes the brand name available in `ContextPack.brands`; the caption names it like a roster person.
- [ ] An unconfirmed/low-confidence/below-floor detection never enters a caption; it surfaces a `review_reason`.
- [ ] The descriptor benchmark records ORB-vs-ALIKED precision and a pinned min-size/inlier threshold, deciding the OpenCV-5 dependency question.
