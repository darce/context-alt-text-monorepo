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
- **Not-Doing here**: no YuNet/SFace code (FIR-3); no dimension flip (FIR-4 cutover slice — this task only centralizes the constant); no runtime wiring changes beyond what the dataclass change forces.

## Problem Statement

`FaceDetectorProtocol`/`EmbeddingGeneratorProtocol` isolate the call seam (REF-15 satisfied), but the *data shape* leaks the buffalo decision (REF-19): `DetectedFace.embedding_512`, pose/age/gender fields sourced only by InsightFace, `512` hardcoded in stubs/tests (`StubEmbeddingGenerator(embedding_dim=512)`), and no record of which model produced a stored embedding. Age/gender are persisted (`media_identities.age/gender`), exported (`export_service.py:312`), and projected into an API payload (`stores.py:258`) despite being non-product (intake: inaccurate, dropped).

## Constraints

- **Two-hat rule (REF-05)**: slice 1 is pure refactor (behavior-preserving), slice 2 is the contract change. Never mixed.
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

A `FaceObservation`-style neutral dataclass (bbox, 5 landmarks, confidence, embedding: np.ndarray, model_id) at the seam; `EmbeddingModelManifest` typed value (name, version, dimensions, normalization, metric) resolved from settings; `media_identities.embedding_model` populated on every write; age/gender gone from schema, exports, and API (or explicitly deferred with audit evidence if a consumer is found); embedding dim referenced from exactly one settings constant; recorded operator sign-off on tenant wipe/re-scan.

## Contract and Boundary Impact

- **API**: `stores.py` face payload drops `age`/`gender` keys — consumer audit (WP plugin `apps/prototype-wp-alt-context/`, workbench UI) decides remove-vs-deprecate; result recorded as a decision.
- **Export snapshots**: `export_service.py` schema change — bump snapshot schema marker if one exists; note in export docs.
- **DB**: `+ embedding_model TEXT NOT NULL DEFAULT` (backfill n/a, greenfield), `- age`, `- gender`. Dimension untouched (512 until FIR-4).

## Slice Delivery

| Slice | Content | Verification |
| --- | --- | --- |
| S1 Greenfield verification | Enumerate live tenants (demo/prod DB), record operator wipe/re-scan sign-off as MCP decision; blocker if curation-worth-keeping found | decision recorded; blocker path exercised in dry form |
| S2 Seam refactor (behavior-preserving) | Neutral observation dataclass; dim centralized to settings; stubs/tests parametrized; `EmbeddingModelManifest` type; adapter maps InsightFace → neutral shape | full suite green via `make check-remote`; no snapshot/API diffs (characterization asserts) |
| S3 Provenance column | `embedding_model` column + write-path population (scan service) + verify/sync scripts + tests | schema verify green; new rows carry manifest id |
| S4 age/gender contract change | Consumer audit (grep WP plugin + workbench for `age`/`gender` on the face payloads; record findings) → drop columns/exports/projections + test updates | audit decision recorded; `make check-remote` green; API characterization updated intentionally |

## Files and Surfaces to Change

`recognition/infrastructure/embeddings/__init__.py` · `recognition/application/embedding/{detector,generator}.py` · `recognition/application/scan/service.py` · `recognition/application/services/export_service.py` · `recognition/interface_adapters/http/deps/stores.py` · `recognition/config/settings.py` + `recognition/application/settings/` · `db/models/identity.py` · `db/migrations/versions/001_identity_schema.py` · `scripts/{sync,verify}_identity_schema.py` · tests: `test_adapter_surface_inventory.py`, `test_embedding_generator.py`, circuit-breaker + health-probe suites, seed helpers.

## Verification Strategy

Scoped TDD per slice locally; `make check-remote` per slice close (never local full-suite). Characterization tests pin the API/export payloads before S4 changes them deliberately (rg-006/AGT-03: observe the failure the contract change causes, then accept it explicitly).

## Consolidated Checklist

- [ ] S1 tenant enumeration + operator sign-off decision recorded
- [ ] S2 neutral dataclass at seam; `embedding_512` gone from protocol layer
- [ ] S2 dim referenced from a single settings constant (stubs/tests parametrized)
- [ ] S3 `embedding_model` column + write-path + verify scripts green
- [ ] S4 consumer audit decision recorded (WP plugin + workbench)
- [ ] S4 age/gender removed from schema, export, API projection + tests
- [ ] `make check-remote` green at branch end; `/review-parallel` run; zero open findings
- [ ] Handoff: decisions per slice, `update_task_status(done)` + archive at close

## Success Criteria

InsightFace still works through a model-neutral seam; a grep for `embedding_512|face\.age|face\.gender` in `recognition/application/` returns nothing; every new `media_identities` row records `embedding_model`; scope success criterion 7 (greenfield sign-off) satisfied.
