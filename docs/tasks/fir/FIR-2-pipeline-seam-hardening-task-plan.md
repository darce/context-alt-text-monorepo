# FIR-2. Pipeline Seam Hardening + Provenance

> **Metadata**
>
> - **Date**: 2026-07-15
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `FIR-2`
> - **Target Branch**: `feature/fir-2`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Review Coverage Target**: 2

## Objective

Make the recognition pipeline's detection/embedding seam model-neutral so FIR-3 adapters drop in without touching consumers: strip InsightFace-shaped data from the protocol boundary, centralize the embedding dimension, add per-row `embedding_model` provenance, and land the age/gender contract removal behind a consumer audit. Verify the greenfield assumption before anything irreversible.

## Intake

- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) (FIR-2 row) · assessment §3.1/§4 · intake decisions `claude_fir1_scope_intake_commercial_face_replacement` (#2376)
- **Not-Doing here**: no YuNet/SFace code (FIR-3); no dimension flip (defaults flip in FIR-6's switch-over slice; dev/eval exercise 128D via the `PGVECTOR_DIM` env — this task only centralizes the constant); no runtime wiring changes beyond what the dataclass change forces.

## Problem Statement

`FaceDetectorProtocol`/`EmbeddingGeneratorProtocol` isolate the call seam (REF-15 satisfied), but the *data shape* leaks the buffalo decision (REF-19): `DetectedFace.embedding_512`, pose/age/gender fields sourced only by InsightFace, `512` hardcoded in stubs/tests (`StubEmbeddingGenerator(embedding_dim=512)`), and no record of which model produced a stored embedding. Age/gender are persisted (`media_identities.age/gender`), exported (`export_service.py:312`), and projected into an API payload (`stores.py:258`) despite being non-product (intake: inaccurate, dropped).

## Constraints

- **Two-hat rule (REF-05)**: the seam refactor (S2) and the age/gender contract change (S4) are separate slices — never mixed. S2 is behavior-preserving by definition; S4 is the only slice allowed to change observable payloads.
- Provenance column is a plain text column + typed manifest value (DOM-05) — **no** model-registry service, no multi-dim query layer (REF-12).
- Greenfield schema edits go directly into `001_identity_schema.py`; verify scripts (`sync_identity_schema.py`/`verify_identity_schema.py`) must stay green — verify fails closed on column gaps.
- InsightFace keeps working on this branch (production still runs it until FIR-6); the refactor renames/reshapes around it, never breaks it.

## Current State Analysis

- `recognition/infrastructure/embeddings/__init__.py` — `DetectedFace` (bbox, confidence, `embedding_512`, pose, age, gender, landmarks); `InsightFaceAdapter` returns it.
- `recognition/application/embedding/detector.py` — `FaceDetection` dataclass (embedding "512D or 1024D" comment, pose/age/gender fields); `generator.py` — `EmbeddingResult`, stub dim default 512.
- `recognition/application/assignment/quality.py` — `compute_identity_quality(pose_pitch/yaw/roll, ...)` consumed by detector quality scoring; returns `threshold_adjustment` (the seam FIR-6's occlusion-adaptive thresholds extend).
- `db/models/identity.py` — `MediaIdentity.age/gender` columns; `Vector(_DB_SETTINGS.pgvector_dimension)`; no model provenance.
- Consumers of age/gender: `scan/service.py:322/350` (writes), `export_service.py:312` (snapshot export), `stores.py:258` (API projection). WP-plugin/workbench readership unknown → audit.

## Target Outcome

**One neutral dataclass, not a third name (NAME-02/NAME-05)**: the existing application-layer `FaceDetection` becomes the single seam type (bbox, 5 landmarks, confidence, embedding: np.ndarray, model_id — insightface-only fields removed); infrastructure's `DetectedFace` is **deleted**, its adapter mapping directly into `FaceDetection`. Plus: `EmbeddingModelManifest` typed value (name, version, dimensions, normalization, metric) resolved from settings; `media_identities.embedding_model` populated on every write; age/gender gone from schema, exports, and API (or explicitly deferred by the S4 audit decision); embedding dim referenced from exactly one settings constant; recorded operator sign-off on tenant wipe/re-scan.

## Contract and Boundary Impact

- **API**: `stores.py` face payload drops `age`/`gender` keys — consumer audit (WP plugin `apps/prototype-wp-alt-context/`, workbench UI) decides remove-vs-deprecate; result recorded as a decision.
- **Export snapshots**: `export_service.py` schema change — bump snapshot schema marker if one exists; note in export docs.
- **DB**: `+ embedding_model TEXT NOT NULL` — **no DEFAULT** (a default would convert missing provenance into fake provenance, RLSE-05); the write path supplies it explicitly, `insightface-buffalo_l@512d/l2/cosine` while InsightFace remains wired. `- age`, `- gender`. Dimension defaults untouched (512 until FIR-6's switch-over; dev/eval may set `PGVECTOR_DIM=128`).
- **Rollback (RLSE-08)**: all FIR-2 schema edits are pre-switch-over and revert via branch revert + the standard greenfield reset — the provenance column is additive and the age/gender drops regenerate nothing that re-scan can't rebuild.

## Slice Delivery

| Slice | Content | Verification |
| --- | --- | --- |
| S1 Greenfield verification | Enumerate live tenants (demo/prod DB), record operator wipe/re-scan sign-off as MCP decision. **Refusal path defined**: operator declines → record blocker; S4 and the FIR-6 dimension flip are blocked on it; escalation = operator-owned re-scan comms plan before re-entry | verification = the recorded decision id (sign-off) or blocker id (refusal); no other exit |
| S2a Characterization first | Author + land characterization tests pinning current behavior BEFORE any refactor (AGT-03): API face payload (`stores.py`), export snapshot shape (`export_service.py`), adapter output fields, stub embedding shape | new tests green against unmodified code; committed separately |
| S2b Seam refactor (behavior-preserving) | `FaceDetection` becomes the single neutral seam type; `DetectedFace` deleted; dim centralized to settings; stubs/tests parametrized; `EmbeddingModelManifest` type; adapter maps InsightFace → `FaceDetection` | S2a characterization suite untouched and green; full suite via `make check-remote` |
| S3 Provenance column | `embedding_model TEXT NOT NULL` (no DEFAULT) + explicit write-path population (scan service, incumbent manifest value) + verify/sync scripts + tests | schema verify green; test proves an INSERT without provenance fails |
| S4 age/gender contract change | Consumer audit (grep WP plugin + workbench for `age`/`gender` on the face payloads; record findings) → **audit decision executes one of two paths**: remove columns/exports/projections now, or defer removal with a recorded consumer-migration decision | audit decision recorded naming the path taken; `make check-remote` green; S2a characterization updated intentionally (removal) or unchanged (deferral) |

## Files and Surfaces to Change

`recognition/infrastructure/embeddings/__init__.py` · `recognition/application/embedding/{detector,generator}.py` · `recognition/application/scan/service.py` · `recognition/application/services/export_service.py` · `recognition/interface_adapters/http/deps/stores.py` · `recognition/config/settings.py` + `recognition/application/settings/` · `db/models/identity.py` · `db/migrations/versions/001_identity_schema.py` · `scripts/{sync,verify}_identity_schema.py` · tests: `test_adapter_surface_inventory.py`, `test_embedding_generator.py`, circuit-breaker + health-probe suites, seed helpers.

## Verification Strategy

Scoped TDD per slice locally; `make check-remote` per slice close (never local full-suite). S2a's characterization tests are the refactor's bug detector and exist **before** S2b touches anything (AGT-03: observe current behavior first, then prove it unchanged); S4 later changes those pins deliberately and visibly.

## Consolidated Checklist

- [x] S1 tenant enumeration + operator sign-off decision (or blocker) recorded
- [x] S2a characterization tests landed green against unmodified code
- [x] S2b `FaceDetection` is the single seam type; `DetectedFace` deleted; characterization suite untouched
- [x] S2b dim referenced from a single settings constant (stubs/tests parametrized)
- [x] S3 `embedding_model` column (NOT NULL, no DEFAULT) + explicit write-path + INSERT-without-provenance failure test
- [x] S4 consumer audit decision recorded naming remove-now vs defer path
- [x] S4 executed per that decision (removal + test updates, or deferral decision with migration owner)
- [x] `make check-remote` green at branch end; `/review-parallel` run; zero open findings
- [ ] Handoff: decisions per slice, `update_task_status(done)` + archive at close

## Success Criteria

InsightFace still works through a model-neutral seam, proven by the untouched S2a characterization suite — not by grep alone. Mechanical checks (necessary, not sufficient): `DetectedFace` no longer exists; `rg "embedding_512|\.age\b|\.gender\b" recognition/ --type py` (application **and** infrastructure and interface_adapters, tests excluded per audit decision) returns nothing; a `512` literal audit in `recognition/` finds only the settings constant; the adapter-surface inventory test is extended to reject model-specific fields on the seam type. Every new `media_identities` row records `embedding_model`; scope success criterion 7 (greenfield sign-off) satisfied.
