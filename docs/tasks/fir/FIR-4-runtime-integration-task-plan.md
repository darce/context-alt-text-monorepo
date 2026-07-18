# FIR-4. Runtime Integration (Dark) + License Isolation

> **Metadata**
>
> - **Date**: 2026-07-18
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `FIR-4`
> - **Target Branch**: `feature/fir-4`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-3 (adapters, merged @ad67afaa)
> - **Review Coverage Target**: 2 (≥1 remote grok HIGH adversarial reviewer per slice)

## Objective

Wire the FIR-3 face_pipeline (YuNet+SFace ORT adapters) into the runtime behind the FIR-2 seam, **dark**: a `FacePipelineSettings` profile flag whose production default stays on the incumbent InsightFace path until FIR-6's operator-gated switch-over ([RLSE-07]). Ship boot-time sha256 fail-closed model verification, the observability surface FIR-6's calibration needs, dependency/license isolation (insightface → `[bench]` extra), and Rider-1: `onnxruntime>=1.22` bump with the FIR-3 parity suite re-run as its quality gate ([SERVE-07]).

## Intake

- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) (FIR-4 row) · E22 epic P2 · FIR-3 plan Not-Doing list (runtime wiring = here)
- **Not-Doing here**: no dimension-default change (`EMBEDDING_DIMENSION`/`PGVECTOR_DIM` defaults flip only in FIR-6's gated switch-over; dev/eval exercise 128D via the `PGVECTOR_DIM` env); no threshold calibration ([DRIFT-03] — YuNet `score_threshold=0.9` etc. stay FIR-3 defaults, re-fit in FIR-6); no GPU/CUDA (FIR-7); no bake-off legs (FIR-5); no buffalo removal from prod images (FIR-6 switch-over does that — here we only isolate it to `[bench]`).

## Problem Statement

FIR-3 landed parity-proven adapters that nothing constructs at runtime. The runtime has three symmetric construction sites (`scan_worker._ensure_embedding_runtime`, `tasks/scan.py`, HTTP `deps/services.py get_scan_service_builder`) that hardwire InsightFace with no backend-selector setting — swapping backends today means editing glue at every site ([SERVE-01]). The FIR-3 adapters also do not implement the FIR-2 protocols (numpy-BGR batch I/O + `RawDetection` vs `Iterable[bytes|str]` → `FaceDetection`), so a bridge is required, and it must reuse FIR-3's exact preprocessing — re-implementing decode/align in the bridge would silently break the golden parity contract ([SERVE-08]). Meanwhile `check_model_cache` only counts `.onnx` files; a corrupted or swapped model passes /ready ([EMB-05], [DRIFT-02]).

## Constraints

- **Dark by construction**: production default = incumbent. The flag is the only entry to the new path; both branches of the flag are tested live matrix, and the flag inventory is explicit — one flag, documented, removed at FIR-6 switch-over or FIR-8 abandonment ([SERVE-03], [RLSE-07]).
- **One embedding space per comparison** ([EMB-01]): the face_pipeline path emits 128D under manifest `opencv-sface@128d/l2/cosine`; incumbent rows are 512D `insightface-buffalo_l@512d/l2/cosine`. When the flag selects face_pipeline, startup must verify `pgvector_dimension == manifest.dimensions` and fail closed on mismatch — never write a 128D vector into a 512D index or vice versa. Rows always stamp `embedding_model` ([PROV-01], [PROV-06]); the existing NOT-NULL + `ValueError` guard in `ScanService` stays load-bearing.
- **Fail closed, loudly**: model file missing / sha256 mismatch / license-hash mismatch → `UnavailableFaceDetector`/`UnavailableEmbeddingGenerator` with a recorded reason + UNHEALTHY /ready, never a silent stub fallback in production mode ([RLSE-05], [AGT-10]). Stub remains test-mode-only, as today.
- **Transform parity**: the bridge composes `OrtYuNetDetector → FivePointAligner → OrtSFaceEmbedder` exactly as the FIR-3 parity tests do; no re-implemented preprocessing, no bbox/landmark math beyond the xywh→corner conversion at the seam boundary ([SERVE-08], rg-015: adapters must not invent contract metadata).
- **Timeouts + breaker parity with incumbent**: the new path gets the same timeout and circuit-breaker treatment `InsightFaceFaceDetector` has ([RES-02], [RES-03]); in-process ORT calls are wrapped with the executor/timeout pattern already used by the incumbent.
- **Rollback is the flag** ([RLSE-08]): flag off returns to incumbent instantly; no schema change in this task, `embedding_model` column exists since FIR-2, so old-path code reads new-path rows and vice versa ([DATA-03] — no migration, greenfield policy).
- **ORT bump is behaviour-changing until proven otherwise** ([SERVE-07]): `onnxruntime>=1.16` → `>=1.22` (and `onnxruntime-gpu` mirror) merges only with the FIR-3 parity suite green on the bumped runtime; any parity deviation is an implementation defect to investigate, not a tolerance to widen.

## Current State Analysis

- Seam (FIR-2): `FaceDetectorProtocol.detect(Iterable[bytes|str]) -> list[FaceDetection]` (corner bbox, `model_id` stamp), `EmbeddingGeneratorProtocol.generate(Iterable[bytes]) -> list[EmbeddingResult]`, `EmbeddingModelManifest.model_id`. Implementations: Stub / Unavailable / InsightFace. No DI container; three inline construction sites gated on `runtime_mode == "test"`.
- FIR-3: `recognition/infrastructure/face_pipeline/` — `OrtYuNetDetector.detect(Sequence[np.ndarray]) -> list[list[RawDetection]]` (xywh + 5×2 landmarks), `OrtSFaceEmbedder.embed(crops) -> (N,128)` L2-normalized, `FivePointAligner`, `load_verified_model` (sha256+license fail-closed), `MODEL_MANIFEST` (opencv_zoo pin). Package exports provenance only; adapters not re-exported; ONNX bytes gitignored — `scripts/fetch_face_pipeline_models.py` fetches+verifies.
- No backend-selector setting exists. `check_model_cache(cache_dir, model_name="buffalo_l")` counts `.onnx` files only. `pyproject.toml`: `onnxruntime>=1.16.0` (L32), `insightface` in `[face]` and `[gpu]` extras. `scripts/install_insightface_mac.sh` + Dockerfile + docs reference buffalo/insightface broadly.

## Target Outcome

`RECOGNITION_FACE_PIPELINE__PROFILE` (or equivalent nested-settings env) selects `insightface` (default) | `face_pipeline` | `stub`(test). All three construction sites branch through one shared factory ([SERVE-01], [REF-15]) so the selection logic lives once. The face_pipeline path is fully operable dark in dev/eval: fetch models → boot verifies sha256 fail-closed → scans stamp `opencv-sface@128d/l2/cosine` → observability shows per-scan detection count, assignment/unknown ratio, quality-gate rejections, `embedding_model` in logs/metrics ([OBS-01], [OBS-02]). insightface imports survive only behind the `[bench]` extra; ORT ≥1.22 everywhere.

## Contract and Boundary Impact

- New `FacePipelineSettings` on `RecognitionSettings` (profile, models_dir, score/nms thresholds pass-through, timeout) — config is a reviewed, asserted artifact: validated at load ([PROV-08], rg-008).
- New bridge module inside `face_pipeline` (or `infrastructure/embeddings`) implementing the FIR-2 protocols; `face_pipeline` package still imports nothing from worker/HTTP layers (existing import-purity test extends to the bridge if it lives in-package; if the bridge needs seam types, it lives beside the incumbent adapter instead — decide in S2, record in the slice decision).
- `/ready` semantics extended: profile-aware model verification (sha256, not file count) — DEGRADED/UNHEALTHY reasons name the failing artifact ([OBS-05]).
- `pyproject.toml`: extras re-cut (`[face]` loses insightface → new `[bench]`), `onnxruntime>=1.22`. Docker build gains build-time model verification for the dark path (fetch script `--verify-only` mode or equivalent).
- No REST/DB/wire schema change. No WP-plugin impact.

## Slice Delivery

| Slice | Content | Verification |
| --- | --- | --- |
| S1 Rider-1 ORT bump | `onnxruntime>=1.22` (+ `onnxruntime-gpu` mirror in `[gpu]`); lockfile/venv refresh | FIR-3 parity suite (79 tests) green on bumped ORT ([SERVE-07]); `make check-remote` green |
| S2 Bridge + settings | `FacePipelineSettings` (validated at load, rg-008); bridge classes implementing `FaceDetectorProtocol`/`EmbeddingGeneratorProtocol` composing FIR-3 adapters + aligner; manifest → `EmbeddingModelManifest` mapping; dim-mismatch fail-closed guard ([EMB-01]); timeout wrapper ([RES-02]) | TDD unit tests: bytes→FaceDetection E2E on golden fixtures, corner-bbox conversion, model_id stamp ([PROV-06]), dim guard raises, zero-face/decode-failure paths, timeout behaviour; characterization: incumbent path untouched ([TEST-03]) |
| S3 Wiring behind flag | Shared factory; three construction sites branch on profile; Unavailable fail-closed on missing/tampered models; boot `check_model_cache` extension → profile-aware sha256 verification ([EMB-05]) | Both flag branches tested at every site ([SERVE-03]); tampered-model boot test → UNHEALTHY; test-mode still stubs; scan_worker capability heartbeat reflects profile |
| S4 Observability | Per-scan wide event: detection count, assignment/unknown ratio, quality-gate rejections, `embedding_model`, profile, correlation id ([OBS-01], [OBS-02], [OBS-03]); counters/gauges exposed ([OBS-05]); silence-detectable (scan events present when scans ran, [OBS-08]) | Unit tests assert event shape/fields on both profiles; log-capture integration test on a dark-profile scan |
| S5 License isolation + deps sweep | insightface → `[bench]` extra (out of `[face]`/`[gpu]`); Dockerfile rework (no insightface in default target; build-time model verification for dark path); `install_insightface_mac.sh` replaced with face_pipeline fetch flow; repo-wide docs/runbooks sweep for buffalo/insightface references | Import guard test: default install path never imports insightface; `uv sync` matrix (default, `[bench]`) resolves; docs sweep grep-clean or explicitly annotated (bench-only) |

S1 first (de-risks the base every later slice runs on); S2→S3→S4 sequential; S5 last (touches the most surfaces, benefits from a stable tree).

## Files and Surfaces to Change

`pyproject.toml` (ORT bump, extras re-cut) · `recognition/config/settings.py` (+`FacePipelineSettings`) · new bridge module + factory (`recognition/infrastructure/face_pipeline/bridge.py` or `recognition/infrastructure/embeddings/face_pipeline_adapter.py` — S2 decision) · `recognition/worker/scan_worker.py` `_ensure_embedding_runtime` · `recognition/application/tasks/scan.py` · `recognition/interface_adapters/http/deps/services.py` · `recognition/application/health.py` `check_model_cache` + `api/main.py` call site · observability: scan event emission in `ScanService`/`ScanItemHandler` · `Dockerfile`, `scripts/install_insightface_mac.sh` (replacement), `scripts/setup.sh`, `scripts/fetch_face_pipeline_models.py` (`--verify-only` if needed) · docs/runbooks sweep · tests under `recognition/tests/unit/` + integration.

## Verification Strategy

Scoped TDD per slice locally (never local full-suite); `make check-remote` green per slice (baseline 2084 passed). S1's gate is the FIR-3 parity suite unchanged and green on ORT≥1.22. S2/S3 lean on FIR-3 golden fixtures as inputs so bridge tests are deterministic ([TEST-08]); every new test observed failing first ([TEST-06]). Before close: real-corpus dark smoke — flag on in a dev env (`PGVECTOR_DIM=128`), scan the 56-image eval-fixture corpus end-to-end, verify row stamps, detection counts vs FIR-3 smoke (0 count mismatches baseline), and the S4 observability output; record numbers in the close decision. Per-slice adversarial `/review-parallel` with ≥1 remote grok HIGH reviewer, findings cite heuristic IDs, batch-recorded in MCP.

## Consolidated Checklist

- [ ] S1: ORT≥1.22 landed; FIR-3 parity suite green on bumped runtime; check-remote green
- [ ] S2: bridge implements both FIR-2 protocols over FIR-3 adapters; dim-mismatch fail-closed; model_id stamped from manifest; unit suite green
- [ ] S3: profile flag wired at all three sites via shared factory; production default = incumbent (verified by test); tampered/missing model → Unavailable + UNHEALTHY; sha256 boot verification profile-aware
- [ ] S4: wide per-scan event with detection count, assignment/unknown ratio, quality-gate rejections, embedding_model, profile; both profiles asserted
- [ ] S5: insightface only in `[bench]`; default install imports clean; Dockerfile + mac script + docs sweep done
- [ ] Real-corpus dark smoke run recorded (56 imgs, stamps + counts + observability verified)
- [ ] Per-slice adversarial review (≥1 remote grok HIGH), zero open findings; handoff decisions per slice; check-remote green at HEAD

## Success Criteria

FIR-6 can flip one flag default to switch production to YuNet+SFace; until then production behaviour is byte-identical to today. A tampered model byte can not boot. Every scan row names its embedding space, and an operator can read detection/unknown/rejection rates per scan without a redeploy. The repo's default dependency surface carries no non-commercial license.
