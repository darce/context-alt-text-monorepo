# FIR-6. Calibration + Quality Rework + Hard-Case Recovery + Gated Switch-Over

> **Metadata**
>
> - **Date**: 2026-07-22 (rev 2 — post plan-analyze + adversarial /planning-review, findings FIR-6-PA-01..06, FIR-6-GR-01..13, FIR-6-LC-01..12 in MCP)
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `FIR-6`
> - **Target Branch**: `feature/fir-6`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-4 (dark runtime, merged) · FIR-5 (bake-off harness — implemented on `feature/fir-5`, **unmerged**; S4/S5 consume it, S1–S3 do not)
> - **Review Coverage Target**: 2 (≥1 remote grok HIGH + ≥1 local adversarial; findings in MCP, never pasted here)
> - **Heuristics canon**: `github.com/darce/heuristics-canon` @ v0.8.3, mirrored unfiltered at `.heuristics-canon/lexicons/` in every lane worktree; implementers/reviewers read `engineering.md` + `ml-systems.md` wholesale. IDs cited below verified at v0.8.3.

## Objective

Turn the dark FIR-4 pipeline into a switchable one: persist the quality signals the old pipeline lost (sharpness, pre-norm embedding magnitude, landmark pose proxies, occlusion severity), scaffold the OACT occlusion-adaptive threshold channel dark, enforce within-photo one-to-one assignment, make representative aggregation quality-gated, calibrate every face_pipeline threshold on ACX data via the FIR-5 harness with a leak-proof protocol, produce the bake-off report that **proposes** gate criteria, and — only after the **operator records the gate decision in MCP** — flip the switch: face-pipeline profile default, `PGVECTOR_DIM` 512→128, buffalo eviction from prod images.

S1–S3 are **corpus-independent and dark** ([RLSE-07]). S4–S5 are **corpus-gated** (operator Golden-150 + FIR-5 merged). S6 is **operator-gated** ([RLSE-02]/[RLSE-03]).

## Intake

- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) — FIR-6 row, Success criteria 2/4/7, §Rollback.
- **Assessment**: [commercial-face-pipeline-replacement-assessment-2026-07-15.md](../../assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md) §4.4 (every threshold recalibrated, never copied), §6.
- **Anchor corrections (verified 2026-07-22)**: dimension SSOT is `PGVECTOR_DIM` (`db/settings.py:216`, default `"512"`); `db/migrations/versions/001_identity_schema.py:17` derives from it — older `001_identity_schema.py:14` citations are stale; do not double-edit `001`.
- **FIR-4 surfaces consumed**: `RECOGNITION_FACE_PIPELINE_PROFILE` (`recognition/config/settings.py:26,42-47`, `{insightface, face_pipeline}`, default `insightface`, fail-closed); `FacePipelineSettings` (`recognition/config/settings.py:125`); observability surface (per-scan detection count, assign/unknown ratio, quality-gate rejections, `embedding_model` in logs).
- **Neutral seam**: `FaceDetection` (`recognition/application/embedding/detector.py:126`) — carries `pose_*`, `landmark_quality`, `landmarks: LandmarkSet | None`, `model_id`. Constructed for the face_pipeline profile in `recognition/infrastructure/embeddings/face_pipeline_adapter.py` (align+embed at `:640-641`, `FaceDetection(...)` at `:656-666`) — **that adapter is the factor-computation site**.
- **Embed path**: both `OrtSFaceEmbedder` (`ort_adapters.py:371`) and `OpenCVSFaceEmbedder` (`opencv_ref.py`) delegate to `embed_batch` (`face_pipeline/_common.py:118-150`), which **already computes** `norm = float(np.linalg.norm(raw))` per face (`:144`) and then discards it, returning only `(N, dim)`.
- **Quality seam**: `compute_identity_quality` (`recognition/application/assignment/quality.py:28`) — score = confidence × size, pose-neutral (FIR2-BR-03); `threshold_adjustment` via `compute_quality_adjustment` (`quality.py:70+`) with maturity damping. **The `threshold_adjustment` channel is the OACT seam the scope names.**
- **Assignment flow (verified)**: discovery (`discovery/centroid.py:44-60`, `representative.py:87-126`, `graph/discovery.py`) emits **at most one candidate per face** (single best above threshold; `discovery_pipeline.py:115-155` dedups); `evaluate_chunk_candidates` gates candidates one at a time via `DecisionHandler.evaluate_only` (`decision_handler.py:123-172`); accepted decisions bulk-persist via `_persist_accepted_assignments` (`orchestrator.py:535-546`); `IdentityChunker` sorts identities by confidence and **can split one photo's faces across chunks** (`chunked_processor.py:42,79-90`).
- **Persistence**: enrollment/representative selection consumes `MediaIdentity` DB rows (`assignment_writer.py:189-233`, `representative_selector.py:50-70`) — scan-time `FaceDetection` objects are gone by clustering time. Pose fields already persist via `media_identities.pose_*` (`scan/service.py:472-474,504-506`).
- **Latent dependency gap**: `scipy` imported by `recognition/application/clustering/hierarchical_clustering.py:19` + `constrained_hac.py` but undeclared in `pyproject.toml`. S2 declares it (rg-001).

## Not-Doing

- No agent ever judges the gate — report proposes, operator decides ([RLSE-02]/[RLSE-03]).
- No corpus expansion beyond Golden-150; below-floor slices stay DIRECTIONAL.
- No retraining, learned quality models, or commercial SDKs (FIR-8); no GPU path (FIR-7); no HNSW; no registry service ([REF-12]); no age/gender resurrection.
- No production writes from bake-off legs; buffalo eval-only; buffalo artifacts never leave `out/`.
- No copying buffalo-tuned thresholds into face_pipeline defaults ([DRIFT-03]/[PERF-06]).
- No top-k discovery rework in S2 (top-1 conflict-break semantics are explicit and tested; a top-k upgrade is an S4-informed follow-on decision, driven by the mirrors/similar-people diagnostics).
- No schema change outside the S1 factor columns (pre-decided below) and S6's dimension flip.

## Problem Statement

FIR-4 wired YuNet+SFace dark with buffalo-era thresholds, no persisted quality factors, no occlusion-adaptive thresholds, and per-face independent assignment that lets one cluster claim several faces in one photo. SFace geometry ≠ buffalo geometry ([DRIFT-03]). Until quality rework + calibration land, the switch-over ships a strictly worse product; until the operator records a gate decision, it must not land at all.

## Constraints

- **Dark until gated** ([RLSE-07]): every S1–S3 change is inert under the `insightface` default. New columns are written only by the face_pipeline scan path (NULL under insightface). Existing insightface-profile tests green unchanged, plus the new end-to-end characterization golden (below).
- **Insightface characterization golden (anti-regression for shared modules)**: a committed fixture drives a multi-face chunk through discovery→gate→persist under `insightface` profile; its decision/representative output must remain field-identical after each of S1–S3. Runs in **every** lane's verify command ([TEST-15]; finding LC/GR-10).
- **Pose-neutral canonical score stands** (FIR2-BR-03): factors feed enrollment gating, observability, and the **`threshold_adjustment` channel only** — never the `score` formula — until S4 measures otherwise ([EVAL-08]).
- **No gating on unvalidated floors** ([EMB-03] validated-proxy discipline; EVAL-22-adjacent — live degradation validation is infeasible pre-launch): factor floors and the OACT coefficient ship as permissive no-ops (floors accept everything; `oact_coefficient=0.0` ⇒ zero adjustment). Activation happens only via S4-recorded measured values. Tests prove the no-op defaults change nothing.
- **Multi-dimensional quality** ([CAL-09]): per-factor breakdown everywhere; never one opaque scalar.
- **Unknown is a valid result** ([CAL-02]): conflict losers and below-threshold faces go to the existing unknown path; no forced nearest-name.
- **Calibration honesty** ([CAL-07], pair-level): thresholds fit and gate metrics read **out-of-fold only**, subject-disjoint K-fold over roster identities; **read-fold impostor pairs must have both identities in the held fold** (cross-fold pairs excluded); anonymous strangers (`name=None`) are read-only probes, never inform fitting; threshold-selection rule pre-registered on fit folds before the final fold is read. The S5 report quantifies residual overlap.
- **Impostor construction** ([CAL-04] **adapted, declared**: demographically matched non-mates are excluded by our [CAL-06] posture — no demographic fields; the matched-non-mate proxy is the corpus's own hard negatives, similar-people stratum first, supplemented by cross-identity same-stratum pairs; the S5 report names the pair sources and n).
- **Per-stratum calibration** ([CAL-01], [CAL-05]): thresholds examined per quality stratum; any global elevation reports its FNMR tax. No demographic conditioning ([CAL-06]).
- **Aggregation robust, not raw mean** ([EMB-02]/[EMB-07]/[EMB-10]): quality-gated enrollment; representative scoring multiplier `f(sharpness, embedding_norm, occlusion_severity)` with **`f ≡ 1.0` whenever factors are `None` or floors are no-op** — bit-identical legacy behavior by construction.
- **Magnitude pre-norm** ([EMB-03]): captured in `embed_batch` where the norm already exists (`_common.py:144`); a mutation-style test asserts capture-after-normalize (constant 1.0) fails.
- **New knobs validate at load, fail-closed** (rg-008), following `_resolve_face_pipeline_profile`.
- **Determinism**: calibration CLI is a pure artifact→artifact function; bit-identical re-runs; no wall-clock/RNG without pinned seed.
- **Scoped TDD locally; `make check-remote` at every merge gate; never local full-suite.**
- **Merge discipline**: every lane merge passes adversarial `/review-parallel` (≥1 local Claude + ≥1 remote grok), findings in MCP, fixed in place; `handoff_close_check(enforce=True)` before `feature/fir-6` → `main`.

## Contract and Boundary Impact

- **External contracts: none** (WP plugin/API/exports untouched through S5).
- **DB schema (S1, greenfield, pre-decided — resolves LC-03/GR-11)**: three nullable REAL columns on `media_identities`: `sharpness`, `embedding_norm`, `occlusion_severity` — added directly in `001_identity_schema.py` with `sync_identity_schema.py`/`verify_identity_schema.py` parity (rg-005). Written only by the face_pipeline scan persist path; NULL under insightface. `MediaIdentity` (`recognition/domain/identity.py`) gains matching optional fields.
- **Internal seams (additive)**: `FaceDetection` gains `sharpness | embedding_norm | occlusion_severity: float | None`; `embed_batch` return type changes (below) — a **breaking internal signature** whose full caller list is enumerated in S1.
- **Settings (additive)**: face_pipeline-scoped knobs on `FacePipelineSettings` (below); shared `ClusteringSettings`/`QualitySettings`/`IdentityDetectionSettings` values are **never mutated before S6** (resolves GR-03 dark-break risk).
- **Deploy configs**: S6 only.

## Face_pipeline-scoped threshold surface (resolves GR-03 — the calibration apply path)

Buffalo-era knobs stay untouched for insightface. The face_pipeline profile reads its own overrides on `FacePipelineSettings`, seeded with the legacy values as placeholders and **replaced by S4's calibrated values via a code commit citing the MCP calibration decision**:

| New knob (FacePipelineSettings) | Replaces (insightface anchor, untouched) |
| --- | --- |
| `face_similarity_threshold` | `ClusteringSettings.similarity_threshold` (`application/settings/clustering.py:191`) |
| `face_complete_link_threshold` | `ClusteringSettings.complete_link_threshold` (`:195`) |
| `face_suggestion_floor` / `face_suggestion_ceiling` | `ClusteringSettings.suggestion_floor` (`:231`) / `suggestion_ceiling` (`:243`) |
| `face_limits_similarity_threshold` | `ClusteringLimitsSettings.similarity_threshold` (`config/settings.py:247`) |
| `face_detection_default_threshold` | `IdentityDetectionSettings.default_threshold` (`config/settings.py:232`) |
| `oact_coefficient` (default 0.0) | — (new OACT channel) |
| `factor_floor_sharpness` / `factor_floor_embedding_norm` / `factor_ceiling_occlusion` (no-op defaults) | — (new) |
| `joint_assignment_enabled` (default True) | — (new) |

S1 lands the knob surface + a profile-resolution helper (consumers select the face_pipeline value only when the profile is active); S2/S3 consume it; S4 fills in calibrated values. Wiring sites are the existing consumers of the legacy settings — enumerated per-slice below.

## Slices

### S1 — Quality signals + OACT scaffold (dark; corpus-independent; lane `fir6-s1`)

1. **`embed_batch` return contract**: `(N, dim) ndarray` → `EmbedBatchResult` frozen dataclass `{vectors: (N,dim) float32, norms: (N,) float32}` (norm already computed at `_common.py:144` — stop discarding it). Update **both** embedders (`OrtSFaceEmbedder.embed` `ort_adapters.py:398-404`, `OpenCVSFaceEmbedder` in `opencv_ref.py`) and **every** `embed`/`embed_batch` caller (enumerate by grep at implementation; at minimum `face_pipeline_adapter.py:640-641`, FIR-5-independent harness callers do not exist on this branch). Mutation test: reconstructing norms post-normalize (all ≈1.0) must fail the capture test ([EMB-03]/[TEST-15]).
2. **Factor computation in `face_pipeline_adapter.py` (`:640-666`)** — the one site where crop + landmarks + FaceDetection construction coexist (resolves LC-05): sharpness = variance-of-Laplacian on the aligned 112×112 crop; occlusion_severity ∈ [0,1] from per-eye patch stats (patch variance + edge energy vs whole-crop baseline; YuNet has no per-landmark confidence — patch stats are the honest signal); pose yaw/roll proxies from the 5-point `LandmarkSet` (inter-ocular angle → roll; eye-midpoint↔nose offset / inter-ocular distance → yaw) written to existing `pose_yaw`/`pose_roll`.
3. **Plumbing**: `FaceDetection` gains the three factor fields; scan persist path (`scan/service.py` identity-write sites `:472-474,504-506` vicinity) stores them to the three **new nullable `media_identities` columns** (001 greenfield edit + sync/verify parity); `MediaIdentity` gains the optional fields. **No NEW DB surface beyond these three columns; pose proxies flow through the existing nullable `pose_*` columns by design** (resolves LC-10). Insightface path: fields stay `None`/NULL everywhere.
4. **OACT dark scaffold** (resolves LC-04/GR-02): `compute_quality_adjustment` (`quality.py`) gains an additive occlusion term `- oact_coefficient * occlusion_severity`-style channel (exact form chosen in-slice; monotone, bounded), active only when the face_pipeline profile is on **and** `oact_coefficient != 0.0`; default 0.0 ⇒ bitwise-identical adjustments. S4 calibrates the coefficient per stratum ([CAL-01]/[CAL-05]).
5. **Settings surface** from the table above (knobs + profile-resolution helper), rg-008 fail-closed validation.
6. **Observability**: FIR-4 emit site logs the per-factor breakdown ([CAL-09]).

**Tests** (`recognition/tests/unit/test_face_quality_factors.py`, new): factor discrimination on synthetic crops (blurred<sharp, occluded>clean — orderings asserted); norms vary across inputs and post-norm capture fails; factors None + columns NULL under insightface; OACT zero-coefficient bitwise parity; no-op floors exclude nothing; knob validation fail-closed. Existing suites in the lane gate (LC-09): `test_identity_quality.py`, `test_face_pipeline_adapter.py`, `test_face_pipeline_opencv_ref.py`, `test_face_pipeline_readiness.py`, `test_face_pipeline_provenance.py`, + the insightface characterization golden (new, `test_insightface_characterization_golden.py`, shared by all lanes).

**Verify**: `cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/unit/test_face_quality_factors.py recognition/tests/unit/test_identity_quality.py recognition/tests/unit/test_face_pipeline_adapter.py recognition/tests/unit/test_face_pipeline_opencv_ref.py recognition/tests/unit/test_face_pipeline_readiness.py recognition/tests/unit/test_face_pipeline_provenance.py recognition/tests/unit/test_insightface_characterization_golden.py -q`

### S2 — Within-photo one-to-one conflict resolution (dark; corpus-independent; lane `fir6-s2`)

**Honest semantics (resolves LC-01/GR-06)**: discovery emits ≤1 candidate per face, so the solver's job is **conflict resolution, not reassignment** — when ≥2 faces in one photo hold accepted candidates for the same cluster, exactly one (highest similarity) keeps it; losers go to the existing unknown/new-cluster path ([CAL-02]). `linear_sum_assignment` over the (faces × distinct candidate clusters) matrix implements this and generalizes unchanged if discovery ever emits top-k. A top-k upgrade is explicitly deferred to an S4-informed decision (Not-Doing).

1. Declare `scipy` in `pyproject.toml` (rg-001) + clean-env import proof.
2. Pure solver `recognition/application/assignment/joint.py::resolve_photo_conflicts(decisions_by_media)` — input: accepted `AssignmentDecision`s grouped by `identity.media_id`; **faces whose every pair is below threshold are dropped from the matrix before solving** (straight to unknown — a −∞-padded infeasible matrix raises `ValueError`, LC-11); finite-sentinel + post-filter for partial rows.
3. **Wiring (resolves LC-02/GR-04)**: in `orchestrator.py` between `evaluate_chunk_candidates` and `_persist_accepted_assignments` (`:535-546`), face_pipeline profile only. Plus two invariant guards:
   - **Photo-atomic chunking**: `IdentityChunker.iter_chunks` (`chunked_processor.py:79-90`) never splits one `media_id` across chunks (small keyed-grouping change; insightface path preserved bit-identically — the grouping applies only under face_pipeline, keeping the characterization golden green).
   - **Persistent same-photo uniqueness guard** in `AssignmentWriter.persist_assignment` (`assignment_writer.py:253`): before insert, reject (→ unknown path) an assignment whose (media_id, cluster_id) already holds a member from a prior batch/scan — covers cross-batch duplicates chunk-atomicity cannot see.
4. `joint_assignment_enabled` knob (default True within face_pipeline; rg-008): off ⇒ today's per-face path bit-for-bit. Mirror/collage cases ride this knob; the shipped default is decided by S5's mirrors-stratum measurement.

**Tests** (`recognition/tests/unit/test_joint_assignment.py`, new): duplicate-identity photo resolves one-to-one with loser→unknown ([TEST-15] — fails on the pre-S2 path); all-below-threshold photo does not crash and routes to unknown (LC-11); knob-off parity; single-face photo unchanged; photo-atomic chunking property (multi-face media never split, face_pipeline profile); **orchestrator-level test: duplicate-identity photo whose faces would previously split across chunks ends one-to-one**; persistent-guard test: second-batch duplicate rejected. Plus the characterization golden.

**Verify**: `cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/unit/test_joint_assignment.py recognition/tests/unit/test_insightface_characterization_golden.py -q`

### S3 — Aggregation gating + calibration CLI (dark; S3a corpus-independent, S3b needs S1 merged)

**S3a — calibration CLI (lane `fir6-s3a`, wave 1; no S1 dependency)**
`scripts/eval_harness/calibrate_face_thresholds.py`, consuming the **pinned face_bakeoff report schema v1** (extracted from `feature/fir-5` `report.py:1028-1052`, committed as fixture `scripts/eval_harness/tests/fixtures/face_bakeoff_report.v1.json` — resolves LC-06/GR-08). Contract (minimum required keys, versioned in the fixture): top-level `report_kind == "face_bakeoff"`, `tau: {tau_k: [float; K], tau_op: float}`, `slices: {stratum: {metrics...}}`, `decisions: [{media_id, box_index, true, pred, tau_k, ...}]`, `counts`. The CLI: validates schema fail-fast (rg-008 analog; missing keys ⇒ non-zero exit), applies the pair-level K-fold protocol from Constraints, emits a per-stratum proposed threshold set + FNMR-tax table + protocol disclosure. Deterministic; writes no settings. FIR-5 side owes a conformance test before S4 (recorded as a coordination note on the FIR-5 task, not here).
**Tests**: `scripts/eval_harness/tests/test_calibrate_face_thresholds.py` — determinism (bit-identical re-run); schema-violation exits non-zero; pair-level disjointness property (no read-pair touches a fit-fold identity; strangers never in fit); golden on the committed fixture.

**S3b — enrollment gating + representative scoring (lane `fir6-s3b`, wave 2 — branches after S1 merges; resolves LC-08)**
Quality-gated enrollment in `representative_selector.py` + `AssignmentWriter._create_and_add_representative` (`assignment_writer.py:189`), reading the S1 factor fields **from `MediaIdentity`** (persisted by S1 — resolves LC-03): observations failing active floors are excluded from representative/centroid updates; representative scoring gains multiplier `f(sharpness, embedding_norm, occlusion_severity)` with **`f ≡ 1.0` when any factor is `None` or floors are no-op** (GR-09); per-source weighting declared in code ([EMB-10]).
**Tests**: `recognition/tests/unit/test_representative_quality_gate.py` — below-floor exclusion when active; nothing changes at no-op defaults; `f≡1` parity on factor-less identities; characterization golden.

**Verify (S3a)**: `cd apps/prototype-description-service && uv run --extra dev pytest scripts/eval_harness/tests/test_calibrate_face_thresholds.py -q`
**Verify (S3b)**: `cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/unit/test_representative_quality_gate.py recognition/tests/unit/test_insightface_characterization_golden.py -q`

### S4 — Calibration on real Golden-150 (**corpus-gated**; FIR-5 merged + operator corpus; propose-and-apply only)

Run the FIR-5 harness on the real corpus; run S3a's CLI; select thresholds per the pre-registered rule; record the calibration decision + artifacts in MCP. **Apply step**: one code commit writing calibrated values into the face_pipeline-scoped knobs (table above) + the `oact_coefficient` + factor floors, citing the MCP decision id — shared insightface settings untouched. Any factor promotion into the canonical score formula requires measured before/after slice deltas ([EVAL-08]) and its own decision. **No schema edits in S4** (persistence landed in S1 — resolves GR-11).

### S5 — Bake-off report proposing gate criteria (**corpus-gated**)

FIR-5 report machinery (`report.py` face_bakeoff path; required entrypoints: the face scorer + `redact_face_report_for_public`) + S3a/S4 outputs → report **proposing**: headline identification P/R, three synthetic-paired occlusion slices, unknown-rejection ([EVAL-18]), false-merge/false-split, throughput/cost leg ([PERF-01]/[PERF-07]), per-slice rollups with DIRECTIONAL floors honest, mirrors-stratum measurement → S2 knob recommendation, pair-level protocol disclosure with quantified residual overlap ([CAL-07]). End-to-end units ([EVAL-16]); template-level eval mirrors deployed aggregation ([EVAL-17]). **Skip/fail criterion (resolves GR-11): if FIR-5 is not merged when S4/S5 open, this slice hard-blocks — no re-implementation of harness pieces on this branch.** No gate verdict anywhere.

### S6 — Switch-over (**operator-gated**; blocked until the MCP gate decision row exists)

Preconditions verified in-slice: operator gate decision id (pass verdict) cited; FIR-2 tenant wipe/re-scan sign-off cited; S4 apply-commit present.

1. Flip `RECOGNITION_FACE_PIPELINE_PROFILE` default → `face_pipeline` (`recognition/config/settings.py:44`).
2. Flip `PGVECTOR_DIM` default `"512"` → `"128"` (`db/settings.py:216`) + every pinning deploy config: `.env*`, `docker-compose*.yml`, `infra/oci/**`, reset scripts (grep-enumerated; list lands in the slice decision).
3. Evict buffalo weights + insightface from production images; `[bench]` extra untouched.
4. Greenfield reset per scope §Rollback; previous image stays tagged.
5. Repo-wide prod-path sweep for buffalo/insightface references (re-verify FIR-4's sweep).
6. **Post-flip soak (resolves GR-13)**: for the first re-scan window, watch the FIR-4 observability signals — assignment-vs-unknown ratio, quality-gate rejection count, p95 scan latency — against the S5 report's expected bands; a breach pauses rollout and triggers the documented rollback (redeploy previous image + reset). Watch thresholds copied into the slice decision from the S5 report.

**Verify**: `make check-remote` green at flipped defaults; `check_model_cache` fail-closed tamper test re-anchored to the new default.

## Files and Surfaces to Change

| Slice | Files (under `apps/prototype-description-service/`) |
| --- | --- |
| S1 | `recognition/infrastructure/face_pipeline/_common.py` (embed_batch → EmbedBatchResult), `ort_adapters.py`, `opencv_ref.py`, `recognition/infrastructure/embeddings/face_pipeline_adapter.py` (`:640-666`), `recognition/application/embedding/detector.py` (FaceDetection fields), `recognition/domain/identity.py` (MediaIdentity fields), `recognition/application/scan/service.py` (persist sites), `db/migrations/versions/001_identity_schema.py` (+3 nullable REAL columns), `db/sync_identity_schema.py`/`db/verify_identity_schema.py`, `recognition/application/assignment/quality.py` (OACT channel), `recognition/config/settings.py` (knob surface), FIR-4 observability emit site, new tests |
| S2 | `pyproject.toml` (scipy), new `recognition/application/assignment/joint.py`, `recognition/application/orchestration/clustering/orchestrator.py` (wiring), `chunked_processor.py` (photo-atomic), `recognition/application/persistence/assignment_writer.py` (uniqueness guard), `recognition/config/settings.py` (knob), new tests |
| S3a | new `scripts/eval_harness/calibrate_face_thresholds.py`, fixture `scripts/eval_harness/tests/fixtures/face_bakeoff_report.v1.json`, tests |
| S3b | `recognition/application/persistence/representative_selector.py`, `assignment_writer.py` (`_create_and_add_representative`), tests |
| S4 | `recognition/config/settings.py` (calibrated values apply-commit) + MCP artifacts |
| S5 | eval-harness run configs + MCP artifacts only |
| S6 | `recognition/config/settings.py:44`, `db/settings.py:216`, `.env*`, `docker-compose*.yml`, `infra/oci/**`, reset scripts, Dockerfiles |

## Verification Strategy

Per-slice scoped pytest exactly as written in each Verify line. The insightface characterization golden runs in every lane gate and at every merge. `make check-remote` green on `feature/fir-6` after each lane merge and before the `main` merge. Calibration CLI: bit-identical re-run. S6: check-remote at flipped defaults + tamper test + post-flip soak watch. Full suite never runs locally.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane | Slice | Wave | Branch | Backend | test_cmd |
| --- | --- | --- | --- | --- | --- |
| `fir6-s1` | S1 | 1 | `feature/fir6-s1` | grok-remote (HIGH) | S1 Verify line |
| `fir6-s2` | S2 | 1 | `feature/fir6-s2` | grok-remote (HIGH) | S2 Verify line |
| `fir6-s3a` | S3a | 1 | `feature/fir6-s3a` | grok-remote (HIGH) | S3a Verify line |
| `fir6-s3b` | S3b | 2 (after S1 merges) | `feature/fir6-s3b` | grok-remote (HIGH) | S3b Verify line |

Every lane worktree carries `.heuristics-canon/lexicons/` (unfiltered) + an Assignment message citing relevant canon IDs + a semantic-reinjection packet from handoff.db.

### Merge Order

Wave 1: S1 → S2 → S3a into `feature/fir-6` (coordinator rebases on collision; S1 and S2 both touch `config/settings.py` — additive, distinct knobs). Wave 2: S3b after S1 is merged (resolves LC-08). Each merge gated by adversarial `/review-parallel` (≥1 local Claude + ≥1 remote grok), findings fixed in place first.

### Orchestration Mode

`dispatch_wave` (grok-remote, HIGH) for wave 1; `fir6-s3b` dispatched singly after the S1 merge. S4–S6 are coordinator/single-lane work.

## Consolidated Checklist

### Context and Ownership

- [ ] Scope §FIR-6, assessment §4.4/§6, canon v0.8.3, and all Intake anchors loaded before editing.
- [ ] No external contract touched (S1–S5); S6 cites the operator gate decision + FIR-2 sign-off.

### Checklist for S1: Quality signals + OACT scaffold

- [ ] EmbedBatchResult contract + both embedders + all callers; factor computation in face_pipeline_adapter
- [ ] FaceDetection/MediaIdentity fields + 001 columns + sync/verify parity; NULL under insightface
- [ ] OACT channel with 0.0 default; knob surface validated fail-closed; observability breakdown
- [ ] S1 Verify line green incl. characterization golden

### Checklist for S2: One-to-one conflict resolution

- [ ] scipy declared + import proof; solver with below-threshold drop; loser→unknown
- [ ] Orchestrator wiring + photo-atomic chunking + persistent uniqueness guard; knob-off parity
- [ ] S2 Verify line green incl. orchestrator-level split-photo test + characterization golden

### Checklist for S3a: Calibration CLI

- [ ] Schema v1 fixture committed; CLI validates fail-fast; pair-level K-fold; determinism
- [ ] S3a Verify line green

### Checklist for S3b: Aggregation gating

- [ ] MediaIdentity-sourced factor gating; `f≡1` parity; per-source weighting declared
- [ ] S3b Verify line green incl. characterization golden

### Checklist for S4–S6 (gated)

- [ ] [corpus-gated] S4 calibration decision + apply-commit into face_pipeline knobs only
- [ ] [corpus-gated] S5 report artifact; proposes criteria; hard-blocks if FIR-5 unmerged; no verdict
- [ ] [operator-gated] S6 flips + soak watch executed citing the gate decision; check-remote green

### Review Readiness

- [ ] Each lane merge passed adversarial `/review-parallel` (≥1 remote grok + ≥1 local); findings closed in MCP, never pasted here
- [ ] Slice decisions recorded via `close_slice` with full 40-char SHAs
- [ ] `make check-remote` green on `feature/fir-6` before the `main` merge

### Success Criteria

- [ ] Dark pipeline: persisted quality factors, OACT seam, one-to-one photo assignment, gated aggregation — all inert at prod defaults until S6
- [ ] Calibration lands in face_pipeline-scoped knobs via an MCP-cited apply-commit; insightface values untouched pre-S6
- [ ] Report proposes (never judges) the gate; switch-over cites the operator decision and flips profile + dimension + images together with a soak watch
- [ ] `handoff_close_check(enforce=True)` passes; task `done` + archived
