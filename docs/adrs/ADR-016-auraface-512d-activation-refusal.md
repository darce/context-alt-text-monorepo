# ADR-016: Refuse AuraFace 512D activation while preprocessing or provenance is unverified

- **Status:** Accepted policy; readiness refusal integrated, serving enforcement and composed parity still pending.
- **Date:** 2026-09-22
- **Deciders:** FIR512-2 docs lane (records the policy already implied by FIRDV-3 S1 / FIR512-1 plumbing)
- **Context task:** FIR512-2
- **Related:** `recognition/infrastructure/face_pipeline/provenance.py`, `recognition/application/health.py`, `recognition/config/settings.py`, `db/settings.py`, `apps/prototype-description-service/.env.fir.example`
- **Heuristics:** [OBS-08] (readiness must observe the loaded artifacts, not a stale cache of intent), [EXP-14] (do not treat an unverified experimental path as the production path)

## Status

Accepted as **activation policy**. AuraFace readiness now refuses unverified metadata before model I/O. FIR512-2 still owns the shared serving-path guard, verified external preprocessing, and ORT composed parity. This development change has not been deployed or quality-qualified.

## Date

2026-09-22

## Context

FIR512-1 merged dimension and provenance plumbing for a declarable AuraFace-v1 512D space (`dd2f1e5b64dbe14a5fa6797d2450f14df9de3838`). That plumbing is not permission to serve, enroll, or quality-qualify the space.

AuraFace-v1 is a **separate model space** from unchanged SFace 128D. It is also not InsightFace/buffalo: the in-house path is YuNet + the in-house five-point aligner + ONNX Runtime on a pinned Apache-2.0 `glintr100.onnx` artifact, with L2/cosine vectors written only to an isolated fresh 512D store after re-extraction from pixels.

The live AuraFace `InputPreprocessing` record is still marked **UNVERIFIED** in `provenance.py` (alignment template, input scale, output L2). Hash pins and graph/raw-output measurements exist; external preprocessing and composed parity remain unverified. Activating on those assumptions would mint a 512D gallery that later measurement cannot replay.

This ADR freezes the **refusal rule**, not the numeric pins. Current hashes, sizes, template ids, and scale comments live in source and will move when FIR512-2 measures them. Do not copy those constants into this document as if they were the contract.

### Constraints from prior review

- Do not claim AuraFace 512D is usable, deployed, or quality-qualified.
- Do not treat own-weight retraining as the only 512D path; it remains conditional research (FIRDV-3 S3–S5).
- Do not reuse SFace 128D or buffalo 512D vectors, centroids, or cluster ids in the AuraFace store.
- Do not load InsightFace runtime or buffalo weights on the AuraFace path, and do not silently fall back to either.
- Dimension alone is not a quality improvement. Withdrawn detector comparisons stay withdrawn.
- Operator configuration is read from `settings.py`, `.env.fir.example`, and the runtime contracts those files name. Do not invent compose names, DSNs, or env values here.

## Current State Inventory

| Surface | What it does today | Enforcement? |
| --- | --- | --- |
| `MODEL_MANIFEST["auraface"]` | Declarable 512D pin: artifact name, license id, embedding_dim/normalization/metric, UNVERIFIED preprocessing comments | Pins exist; preprocessing is explicitly unverified |
| `assert_space_activatable` | Raises while AuraFace preprocessing/provenance is unverified | Called by AuraFace `check_model_space` and API readiness before model I/O |
| `check_face_pipeline_models` | Eager YuNet+SFace verify + three-way dim + shared ORT runtime | **SFace 128D base only.** Does not consult AuraFace or `assert_space_activatable` |
| `check_model_space(AURAFACE)` | Refusal, cached file/hash verification, dimension guard, runtime construct | Unverified AuraFace fails closed before I/O; model-ID and separate detector-directory routing are implemented; shared serving refusal and real-artifact parity remain under review |
| `ort_adapters._blob_builder_for_model` | Declared-preprocessing blob path, currently SFace-template gated | AuraFace composed ORT parity is **pending** (FIR512-2) |
| `FacePipelineSettings.profile` | `RECOGNITION_FACE_PIPELINE_PROFILE` in `{insightface, face_pipeline, auraface}` | Selecting `auraface` is not an activation grant |
| `RecognitionSettings.auraface_models_dir` | `RECOGNITION_AURAFACE_MODELS_DIR` or package `DEFAULT_MODELS_DIR` | Store path only |
| `DatabaseSettings.pgvector_dimension` | `PGVECTOR_DIM` is the sole dimension root | A 512 value does not select AuraFace and must not be applied to the 128D comparator DB |
| `.env.fir.example` | Isolated **128D SFace** comparator: `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline`, `PGVECTOR_DIM=128`, `RECOGNITION_FACE_PIPELINE_MODELS_DIR=/data/cache/face_pipeline` | Rollback/comparator source. There is no committed AuraFace 512D env template in that file |

### Downstream surfaces that must migrate together

- Ready/serve: readiness refusal is integrated and has 20 passing VM tests. Active embedding-model resolution and separate detector-directory routing are implemented; verify the shared serving guard and real-artifact composed path before declaring functional activation.
- ORT composed path: YuNet + in-house aligner + AuraFace session must match **measured** preprocessing before enrollment.
- Store: isolated 512D database/centroids; fresh pixel enrollment; no cross-space import.
- Comparator: keep the 128D `.env.fir.example` stack explicitly selectable; rollback is a stack switch, not a mixed-space fallback.
- Docs: `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` v12 section; FIRDV-3 S1/S6; the 512D roadmap.

## Decision

**Refuse to activate, enroll, or declare ready the AuraFace-v1 512D space while artifact provenance or input preprocessing is unverified.** FIR512-1 plumbing does not override this. FIR512-2 must close the gap by measuring preprocessing, failing closed at readiness, and proving ORT composed parity. Until those land, AuraFace remains a declarable candidate, not a serving profile.

### Chosen design rules

1. **Unverified means refuse, not warn.** Missing bytes, hash mismatch, `PENDING_OPERATOR_FETCH`, or an `-unverified` / unmeasured preprocessing record are activation blockers. A healthy SFace 128D check must not green-light AuraFace.
2. **Do not freeze soon-superseded constants in this ADR.** Cite `provenance.py` / `settings.py` / `.env.fir.example` / `health.py`. Hashes, byte sizes, template ids, and scale comments are source-owned and will change when measurement replaces UNVERIFIED assumptions.
3. **Spaces stay disjoint.** SFace 128D is unchanged. AuraFace 512D is a different model/preprocessing/normalization identity even though both use in-house YuNet/aligner. Equal length never licenses cosine across spaces. No SFace, buffalo, or InsightFace vector reuse; no implicit fallback.
4. **Runtime is in-house ORT, not InsightFace.** The manifest `framework` field names pack family metadata; it is not permission to load InsightFace runtime or buffalo weights.
5. **Enforce the same policy on ready and serve.** AuraFace readiness calls `assert_space_activatable` before model I/O. The shared serving-path guard and composed ORT parity remain under review in FIR512-2; readiness refusal alone is not full activation.
6. **128D rollback is explicit.** Return the comparator to the committed `.env.fir.example` 128D SFace stack. Do not mix 128D and 512D in one database.

### Target outcome

No AuraFace enrollment or `/ready` success until measured preprocessing, verified provenance, fail-closed readiness, and composed ORT parity agree. Own-weight 512D retraining stays a later, conditional FIRDV-3 research path — not a prerequisite and not the only 512D route.

## Why This Decision

### A 512D gallery minted on guessed preprocessing is unrecoverable

Re-embedding after a later scale/template correction is a new space. Serving now would create an isolated DB that cannot be compared to the measured model.

### Tests that refuse are not production enforcement

A helper raised only from unit tests does not protect boot, `/ready`, or a mistaken `RECOGNITION_FACE_PIPELINE_PROFILE=auraface`. OBS-08 requires the ready path to observe the candidate artifacts.

### Dimension plumbing is not quality or deployment

FIR512-1 made the space describable. Quality comparison is FIRDV-3 S2. LocalWP 512D delivery is FIRDV-3 S6. Neither is this ADR, and neither is complete.

## Alternatives Considered

### 1. Activate on hash pins alone; measure preprocessing later

Rejected.

File integrity is necessary and insufficient. Unverified alignment/scale/L2 would still emit vectors. Later measurement would silently invalidate the gallery.

### 2. Treat own-weight retraining as the only 512D path

Rejected.

Retraining is conditional research. The current 512D candidate is pinned AuraFace-v1 through the in-house ORT path. This ADR does not authorize that candidate either, until verification closes.

### 3. Warn in docs but allow ready/serve

Rejected.

Documentation cannot stop a profile flag. Refusal belongs on the activation path. Readiness now refuses the unverified AuraFace profile before I/O; complete serving support and composed parity are still FIR512-2 work.

### 4. Copy current sha256 / template / scale values into this ADR as frozen contract

Rejected.

FIR512-2 may replace UNVERIFIED declarations only when independent measurements and composed parity support the change. Freezing today's numbers here would fork the source of truth from `provenance.py`.

## Consequences

### Positive

- Activation policy is citable without implying the space is live.
- FIR512-2 has an explicit closure target: measurement, fail-closed ready/serve, ORT composed parity.
- 128D comparator and rollback stay defined from committed env, not invented 512D compose names.

### Negative

- Readiness refusal does not establish complete AuraFace serving support. Model-ID routing, detector-store handling, preprocessing, and composed parity still require verification.
- Operators reading hashes from `provenance.py` may assume pins equal permission. The v12 report and this ADR exist to contradict that.

### Guardrails for the follow-on implementation task

- Call `assert_space_activatable` (or a stricter successor) from the AuraFace ready/serve path before enrollment.
- Replace UNVERIFIED preprocessing in source after measurement; do not “fix” this ADR’s omitted constants.
- Keep YuNet + in-house aligner; do not pull InsightFace/buffalo into the AuraFace runtime.
- Provision a fresh 512D DB; never `PGVECTOR_DIM=512` on the 128D comparator from `.env.fir.example`.
- Do not mark usable/deployed/quality-qualified from dimension or hash presence.

## References

- Report (current v12 status): [fir-embeddings-dims-detectors-qa-20260723.html](../../benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html)
- Roadmap: [fir-localwp-512d-implementation-roadmap-2026-09-19.md](../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md)
- Plans: [FIRDV-3](../tasks/firdv/FIRDV-3-embedder-capacity-and-training-feasibility-task-plan.md), [FIRDV-1](../tasks/firdv/FIRDV-1-isolated-development-install-task-plan.md), [FIRDV-2](../tasks/firdv/FIRDV-2-comparative-harness-and-bakeoff-task-plan.md)
- Scope: [fir-development-and-measurement-wave.md](../scopes/fir-development-and-measurement-wave.md)
