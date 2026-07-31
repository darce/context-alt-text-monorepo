# OpenCV 5 Brand Detection Tier A (CPU) — Scope Note

> **Status:** Scope one-pager (decision input). Not an epic or task plan.
> **Date:** 2026-07-07
> **Proposed Task ID:** `E20-BRAND-A` (CPU brand detection) · **Feeds:** E20 (context-pack enrichment), sibling to E20-9 (context-pack contract). Independent of the GPU tier (`gpu-detailed-tier-oci-bursty-scope.md`).
> **Source of truth:** [caption-context-enrichment-assessment-2026-07-05.md](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) §4 (OpenCV 5 features module), §5 (user-defined brand detection design). Intake decision `scope_intake_opencv5_and_oci_bursty_gpu_tier` (MCP, `MAINT-opencv5-bursty-gpu-scope-20260707`). Grounded on `literature/extracted/refactoring/distilled/` — Modern SE (incrementalism, YAGNI), Refactoring UI (reuse existing patterns).

---

## 1. Problem

Captions can name **people** (curated identity clusters → `ContextPack` → identity-prose merge), but there is **no non-face entity detection** — a tenant cannot have "the Acme logo" or a product recognized and named in descriptions. The assessment (§5) proposes closing this with **user-defined brand/logo detection** that reuses the existing identity **curation loop** (confirm/reject, WP-authoritative naming) rather than a new pipeline. Tier A is the CPU-trivial, no-GPU, no-training first cut; OpenCV 5's features module (ORB/ALIKED + LightGlueMatcher) is the enabling layer.

## 2. MVP Scope

**Classical template-matching brand detection**, entirely on CPU, wired into the existing curation + context-pack surfaces.

**UX contract (reuses the identity workbench):**
- Tenant registers a brand: **upload a logo file** OR **draw/select a bbox** on an existing media item → names it.
- System auto-tags future uploads (and back-fills existing media) where the logo appears; instances surface in the **same confirm/reject workbench flow as faces**.
- Confirmed brand names become caption context (`ContextPack.brands`) and are named in the description exactly like a person ("…wearing an Acme jacket").

**Detection path (Tier A — CPU, no training, no GPU):**
1. **Template registration:** normalize crop → keypoints + descriptors (**ORB baseline, ALIKED upgrade** if the OpenCV 5 spike wins) stored as a blob; one global crop embedding in **pgvector** for candidate shortlisting.
2. **Per-image scan** (on upload / backfill): keypoint match template↔image via **LightGlue/BF + homography RANSAC** geometric verification → bbox + inlier-ratio confidence. Milliseconds per template.
3. **Persistence:** reuse identity tables — `media_identities.identity_type` **already permits `'brand'`** (`001_identity_schema.py:256` — `identity_type IN ('face','brand','pose','gait')`); **no enum change needed.** Net-new schema is only a tenant-scoped **`brand_templates`** table (RLS) holding template metadata + descriptor blob, plus `identity_type='brand'` instance rows. **Template-matching is classification against a known template — no HDBSCAN / clustering.** What is reused is the curation loop (`user_confirmed`, confirmation_source, review workbench) + WP-authoritative naming (ADR-003 symmetry).
4. **Context surface:** confirmed instances → a **net-new `brands` field on `scene/interface_adapters/http/schemas/requests.py:ContextPack`** (that model is `extra="forbid"`, so `brands` must be added explicitly, not passed through; a sibling `product: ProductContext` already exists → open design choice: `brands` as a sibling list vs nested under product). WordPress collects + policy-filters, mirroring `IdentityContext`; composition names the brand like a person.

**Deliverables:**
1. `brand_templates` schema + `identity_type='brand'` instance rows (in `001_identity_schema.py`).
2. CPU matcher (ORB/ALIKED + LightGlue + RANSAC) with a min-size floor + `review_reasons` on low-confidence.
3. Registration + confirm/reject wired into the existing workbench; brand name lives in WP.
4. `ContextPack.brands` field + policy filter, consumed by the caption composition stage.
5. A small precision benchmark on a synthetic logo set (ORB vs ALIKED+LightGlue) in the E19-1 JSON format.

## 3. Stated Assumptions

1. **Rigid printed logos are the favorable case** for classical keypoint matching; non-rigid/stylized marks (products, vehicles) are **out of Tier A** (they are the GPU OWLv2 Tier B in the sibling scope).
2. **Confirm-before-context** — a detected brand never enters a caption until a human confirms it (same human-in-the-loop stance as person naming). False positives on lookalike marks are mitigated by this, not by detector accuracy alone.
3. **OpenCV 5 features module is a dependency-additive win, not a swap** — Tier A adds net-new capability (no incumbent); ORB worked on the then-pinned OpenCV 4.x (**superseded by CVUP-1** — service now pins OpenCV `5.0.0.93`); ALIKED/LightGlue still require the OpenCV 5 spike to confirm ARM/A1 parity before adoption.
4. **`ContextPack.brands` sequences after `IdentityContext`** — the E20 context-pack contract (E20-9) must land first to avoid schema churn.
5. **Greenfield schema** — no migrations; brand rows go directly into `001_identity_schema.py` (project has no production data).

## 4. Not-Doing (explicit out-of-scope)

- **No OWLv2 / open-vocab detection** — that is GPU Tier B in `gpu-detailed-tier-oci-bursty-scope.md`.
- **No OpenCV 5 incumbent dependency swap** (replacing onnxruntime/torch) — spike-gated later, separate track, YAGNI.
- **No new clustering algorithm** — template matching only; HDBSCAN is untouched.
- **No non-rigid / product / scene-text brand recognition** — rigid logos only.
- **No brand analytics / dashboards / bulk-management UI** beyond the existing workbench confirm/reject.
- **No context-fusion caption architecture, no PG18/19 work** (uuidv7 PKs for `brand_templates` land opportunistically only if PG18 is already adopted).

## 5. Success Criteria

1. A tenant can register a logo (upload or bbox), and a later image containing it surfaces an unconfirmed brand instance in the workbench.
2. Confirming the instance makes the brand name available in `ContextPack.brands`; the caption composition names it like a roster person.
3. An unconfirmed/low-confidence detection **never** enters a caption; below the min-size floor it surfaces a `review_reason`, not a silent drop.
4. The synthetic-logo benchmark records ORB-vs-ALIKED+LightGlue precision, deciding the descriptor choice (and whether the OpenCV 5 dependency is pulled in at all).
5. `brand_templates` is tenant-scoped (RLS) and the matcher scan cost is bounded per tenant (pgvector shortlist before keypoint match).

## 6. Slice Outline (detail in the task plan)

1. **Schema + curation reuse** — `brand_templates` + `identity_type='brand'`; registration (upload/bbox) → template blob + pgvector embedding; workbench confirm/reject reuse.
2. **CPU matcher** — ORB baseline + LightGlue/BF + homography RANSAC → bbox + confidence; min-size floor + `review_reasons`.
3. **`ContextPack.brands`** — WP collection + policy filter + composition naming (after E20-9 context-pack contract).
4. **Descriptor benchmark** — ORB vs ALIKED+LightGlue on a synthetic logo set (gates the OpenCV 5 dependency).

## 7. Open Risks

- **False positives on lookalike marks** — mitigated by confirm-before-context; detector precision is secondary to the human gate.
- **Tiny/low-res logos** below keypoint density — declared min-size floor + `review_reasons`; do not silently drop. **Thresholds (PA-08):** the min-size floor (provisional ~48 px on the shorter logo edge) and the RANSAC inlier-ratio confidence threshold (provisional ~0.25) are **task-plan-to-pin**, tuned on the §6 synthetic-logo benchmark — not decided at scope stage.
- **Cross-scope dependency (PA-05):** the `ContextPack.brands` context surface is shared with the GPU scope's OWLv2 Tier B (`gpu-detailed-tier-oci-bursty-scope.md` slice 5). This scope **owns and must land `ContextPack.brands` first**; Tier B consumes it. Sequence Scope A's slice 3 before that GPU slice.
- **Per-template scan cost grows linearly** with template count — bound templates per tenant; pgvector shortlist before keypoint match.
- **ALIKED/LightGlue require OpenCV 5** — if the §4 spike shows no ARM/A1 parity, Tier A ships on ORB (OpenCV 4.x) and the ALIKED upgrade defers.
- **SFace/text-detection zoo-model license + engine questions** are irrelevant to Tier A (features-module only), but relevant if the dependency swap is later pursued.
