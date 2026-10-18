# FIR-3. YuNet + SFace Adapters

> **Metadata**
>
> - **Date**: 2026-07-15
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `FIR-3`
> - **Target Branch**: `feature/fir-3`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-2 (neutral seam)
> - **Review Coverage Target**: 2

## Objective

Implement the commercially licensed detection/embedding adapters behind FIR-2's neutral seam: YuNet 2026may (MIT) detection + 5 landmarks → OpenCV-SFace-compatible five-point affine alignment → SFace 2021dec (Apache-2.0) 128D embedding → L2 normalization. Two implementations with provably identical semantics: an OpenCV reference (CPU, golden source-of-truth) and ONNX Runtime CPU adapters (production path).

## Intake

- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) (FIR-3 row) · assessment §3/§4.1 · guide §6 (functional mapping, §6.4 reference impl semantics)
- **Not-Doing here**: no runtime wiring into scan_worker (FIR-4); no GPU/CUDA providers (FIR-7; bake-off GPU legs live in FIR-5); no threshold calibration (FIR-6); no SeetaFace/alternative candidates (FIR-8).

## Problem Statement

The production embedder is license-blocked. The guide's verdict: YuNet is not a drop-in SCRFD replacement and SFace preprocessing must not be assumed ArcFace-compatible — a fork of the InsightFace harness buys nothing (guide §6.2). The replacement must be ACX-owned code whose preprocessing semantics are pinned by golden tests, because alignment/normalization drift silently poisons every downstream embedding (rg-015-adjacent: adapters must not invent contract behavior).

## Constraints

- **Reference-first**: the OpenCV `FaceDetectorYN`/`FaceRecognizerSF` implementation is the semantic reference; the ORT path must reproduce its detector post-processing, landmark order, affine transform, channel order, scaling, and output normalization bit-comparably (within float tolerance) on the golden set.
- **Pin everything**: model ONNX files pinned by sha256 with source URLs + license-file hashes in a provenance manifest shipped with the artifact (guide §16); manifest is the single source for `EmbeddingModelManifest` values.
- **OpenCV pin decision made here**: current `opencv-python>=4.12,<4.15` vs OpenCV 5 (new DNN engine, ARM KleidiCV, YuNet 2026may dynamic input). Assessment §10.3 tips toward OpenCV 5 for the reference path with ORT primary; decide with a build+parity spike, record as ADR (ARCH-07).
- Zero-norm embeddings raise (guide reference impl); never silently zero-fill.
- Batch APIs from the start (detector takes image batch; embedder takes crop batch) — the A10 path (FIR-7) must not need signature changes.

## Current State Analysis

FIR-2 leaves: a single neutral `FaceDetection` seam type, `EmbeddingModelManifest`, dim centralized (defaults still 512; adapters here produce 128 and declare it via manifest — the default flip is FIR-6's switch-over; dev/eval use the `PGVECTOR_DIM` env). `InsightFaceAdapter` remains the wired production implementation. No YuNet/SFace code exists anywhere in the repo.

## Target Outcome

`recognition/infrastructure/face_pipeline/` package: `OpenCVYuNetDetector`, `OpenCVSFaceEmbedder` (reference), `OrtYuNetDetector`, `OrtSFaceEmbedder` (production), a shared `FivePointAligner`, model provenance manifest + loader that verifies sha256 on load, and golden tests. All implement FIR-2's protocols; none is wired into the runtime yet.

## Contract and Boundary Impact

None at runtime (nothing wired). New package boundary: `face_pipeline` depends only on cv2/onnxruntime/numpy + FIR-2's seam types — no imports from worker/HTTP layers (rg-013-style purity, enforced by an import-linter test like the existing adapter-surface inventory).

## Slice Delivery

| Slice | Content | Verification |
| --- | --- | --- |
| S1 Models + manifest | Fetch/pin YuNet 2026may + SFace 2021dec ONNX + license files; sha256 provenance manifest; loader verifies hash, fails closed | manifest test: tampered file → load refuses |
| S2 OpenCV reference | `FaceDetectorYN`/`FaceRecognizerSF` wrappers per guide §6.4; golden fixtures (deterministic images incl. known landmark order + alignment outputs) | golden tests: landmark order, affine matrix, crop bytes, embedding norm==1, dim==128 |
| S3 ORT adapters | ORT CPU detector post-processing (YuNet output decode + NMS) + embedder with identical preprocessing | parity tests vs S2 goldens (cosine ≥ 0.999 per embedding — tightened, see [§ S3 parity-budget amendment](#s3-parity-budget-amendment-2026-07-29-cvup-1); boxes IoU ≥ 0.99); zero-norm raise test |
| S4 OpenCV pin ADR | Build+parity spike on OpenCV 5 vs 4.12 pin; record ADR; land chosen pin | both parity suites green on chosen pin; ADR committed |

## Files and Surfaces to Change

New `recognition/infrastructure/face_pipeline/` (detectors, embedder, aligner, manifest, models/README with licenses) · `pyproject.toml` (opencv pin per ADR; onnxruntime already present) · golden fixtures under `recognition/tests/fixtures/face_pipeline/` · tests `recognition/tests/unit/test_face_pipeline_*.py` · ADR via `manage_adr`/docs.

### S3 parity-budget amendment (2026-07-29, CVUP-1)

The S3 budget above (`cosine ≥ 0.999`) was assigned before the parity spread had
been measured. It is superseded by `cosine ≥ 0.99999999` (`_COSINE_MIN` /
`_GOLDEN_COSINE_MIN` in `test_face_pipeline_ort_parity.py`), a **tightening**
under [sr-001], never a relaxation. Evidence:

- Measured spread, OpenCV 5.0.0 / ORT 1.28.0 / numpy 2.5.1: ORT↔OpenCV cosine
  ≥ 0.999999999997 on both the synthetic and aligner crops (1−cos ≤ 5e-12);
  same figure against the `synthetic_112_embedding` golden.
- Noise floor over 20 repeats: 1 distinct crop hash, composed-embedding max
  absolute spread 0.0, minimum pairwise cosine 1.0000000000000002.
- Holds cross-architecture: the same tightened assertions pass on the aarch64
  remote gate, so this is not an x86-local budget.
- 0.999 admitted a 1−cos slack band ~2e8× the measured
  spread — a bound that wide cannot discriminate a real regression ([TEST-06]).
  The new floor still sits ~10× above a 1e-9 slack band.

Re-measure before touching it again; do not loosen to silence a failure.

## Verification Strategy

Golden tests are the heart of this task (guide checklist: landmark order, affine alignment, normalization — these three are the merge gate). Fixtures are synthetic + a few consented `mock_entities` crops (never uploads). Scoped TDD locally; `make check-remote` per slice. Real-corpus smoke before close: run both impls over `GOLDEN_IMAGES_DIR` and eyeball detection distribution (VLM-6 lesson: green synthetic tests miss real-corpus pathologies).

## Consolidated Checklist

- [x] S1 models pinned (sha256 + license hashes + source URLs), loader fail-closed test
- [x] S2 OpenCV reference + golden fixtures committed
- [x] S3 ORT parity: embeddings cosine ≥ 0.99999999 vs reference (see [§ S3 parity-budget amendment](#s3-parity-budget-amendment-2026-07-29-cvup-1)), boxes IoU ≥ 0.99, zero-norm raises
- [x] S4 OpenCV pin ADR recorded; chosen pin lands with both suites green
- [x] Import-purity test: `face_pipeline` imports nothing from worker/HTTP layers
- [x] Real-corpus smoke run + distribution eyeballed, result recorded
- [x] `make check-remote` green; `/review-parallel`; zero open findings; handoff decisions per slice

## Success Criteria

A YuNet+SFace pipeline exists that FIR-4 can wire with one settings change; its semantics are pinned by goldens strong enough that any future preprocessing regression fails CI; every model byte in the artifact is hash-verified and license-documented.
