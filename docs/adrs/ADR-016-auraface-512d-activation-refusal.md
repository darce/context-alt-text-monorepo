# ADR-016: Refuse AuraFace activation while preprocessing or provenance is unverified

- **Status:** Accepted policy; shared ready/serve enforcement and VM implementation validation complete. Development-site deployment and real-photo enrollment remain pending.
- **Date:** 2026-09-22
- **Context task:** FIR512-2
- **Heuristics:** OBS-08 (readiness observes loaded artifacts), EXP-14 (experimental evidence does not establish production readiness).

## Context

FIR512-1 merged dimension and provenance plumbing for AuraFace-v1 at `dd2f1e5b64dbe14a5fa6797d2450f14df9de3838`. Its preprocessing declarations were initially unverified. File hashes and a 512D setting alone could not justify enrollment.

FIR512-2 now implements a separate AuraFace space through in-house YuNet detection, five-point alignment, and ONNX Runtime on the pinned `glintr100.onnx`. The graph produces raw vectors; the in-house embedder applies L2 normalization. SFace 128D remains an unchanged comparator. Neither SFace nor buffalo vectors, centroids, or cluster IDs can be reused in the AuraFace store.

The publisher's pinned example selects the ArcFace reference path. Independent preprocessing and composed ORT replay now support that recipe. A standalone check of the exact pinned upstream alignment source matches production affine matrices and crop bytes for both float64 fixture landmarks and actual float32 YuNet landmarks. This validation does not import the InsightFace package into the candidate runtime.

## Decision

**Refuse AuraFace activation, readiness, and enrollment while artifact provenance or preprocessing is unverified.** The implementation now enforces this policy through the shared infrastructure helper `assert_space_activatable`, called by readiness, runtime construction, and the shared runtime loader before artifact/cache/model I/O.

1. Missing metadata, pending hashes, and unverified preprocessing fail closed. Missing or mismatched artifact/license bytes prevent construction.
2. Model identity includes the numeric runtime fingerprint. Source-owned artifact pins and preprocessing metadata remain canonical; this ADR does not duplicate their constants.
3. Keep model spaces separate. Use a fresh isolated 512D database and re-extract enrollment from pixels; equal dimension does not make buffalo and AuraFace vectors comparable.
4. Keep the serving implementation in-house: YuNet, the in-house aligner, and ORT. The provenance `framework` field describes model-family metadata and is not permission to load InsightFace runtime or buffalo weights.
5. Preserve SFace's existing alignment arithmetic, model files, and ORT settings. Rollback selects the explicit 128D comparator stack, with no mixed-space reads or automatic fallback.
6. Implementation parity does not establish recognition quality, calibration, deployment, or latency qualification. Own-weight retraining remains conditional FIRDV-3 research, not a prerequisite for every 512D path.

## Current implementation

| Surface | Behavior |
| --- | --- |
| `MODEL_MANIFEST["auraface"]` | Pinned model/license bytes and reference-supported, replayed preprocessing. |
| `face_pipeline/activation.py` | Shared refusal policy, re-exported by `application/health.py` for compatibility. |
| AuraFace ready/serve | Dimension checks, verified artifacts, separate YuNet/AuraFace directories, cached artifact identity and replacement invalidation. |
| Aligner → embedder → quality | ArcFace dtype-preserving similarity; crops stay BGR; only blob construction converts to RGB and applies mean/scale. |
| Model identity | AuraFace name plus OpenCV/ORT numeric runtime token, width, normalization, and metric. |
| `PGVECTOR_DIM` | Sole dimension root; must agree with the selected model and the isolated store. |
| `.env.fir.example` | Existing 128D SFace comparator, not an AuraFace deployment template. |

## Verification and limits

The combined VM suite passed **253 tests**, including ready/serve refusal, artifact cache recovery, model routing, BGR consumer behavior, composed goldens, and existing OpenCV/ORT parity checks. The live synthetic YuNet → AuraFace probe returned one finite normalized 512D vector with readiness OK; independent reference cosine was `0.9999999999994835` against a `0.99999999` floor. InsightFace runtime imports were explicitly blocked during that probe.

The [validation receipt](../../benchmarks/reports/fir-auraface-512d-vm-validation-20260922.json) records tested revisions and boundaries. The [measurement JSON](../../apps/prototype-description-service/recognition/tests/fixtures/face_pipeline/auraface_alignment_measurement.json) preserves the original graph measurements separately from later preprocessing evidence.

No isolated AuraFace development database or LocalWP endpoint was deployed by this recovery. Real-photo enrollment awaits the original corpus location. Identity accuracy and operating thresholds require the later controlled comparison; synthetic compatibility checks cannot supply those results.

## Alternatives rejected

- **Activate on hashes alone:** verified bytes do not establish preprocessing or a compatible store.
- **Warn only in documentation:** refusal must execute on both readiness and serving paths.
- **Reuse existing 128D or buffalo galleries:** vectors from different spaces are incompatible.
- **Require retraining for every 512D route:** the pinned AuraFace candidate is independently implementable; a training campaign needs separate evidence.

## References

- [Current FIR report](../../benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html#v12)
- [512D development roadmap](../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md)
- [FIRDV-3 plan](../tasks/firdv/FIRDV-3-embedder-capacity-and-training-feasibility-task-plan.md)
- [FIRDV-1 isolated development install](../tasks/firdv/FIRDV-1-isolated-development-install-task-plan.md)
- [FIRDV-2 comparative harness](../tasks/firdv/FIRDV-2-comparative-harness-and-bakeoff-task-plan.md)
