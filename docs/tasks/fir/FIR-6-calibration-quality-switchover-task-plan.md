# FIR-6. Calibration + Quality Rework + Hard-Case Recovery + Gated Switch-Over

> **Metadata**
>
> - **Date**: 2026-07-22
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `FIR-6`
> - **Target Branch**: `feature/fir-6`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-4 (dark runtime, merged) · FIR-5 (bake-off harness — implemented on `feature/fir-5`, **unmerged**; S4/S5 of this plan consume it, S1–S3 do not)
> - **Review Coverage Target**: 2 (≥1 remote grok HIGH + ≥1 local adversarial; findings in MCP, never pasted here)
> - **Heuristics canon**: `github.com/darce/heuristics-canon` @ v0.8.3, mirrored unfiltered at `.heuristics-canon/lexicons/` in every lane worktree. Implementing and reviewing agents read `engineering.md` and `ml-systems.md` wholesale; IDs cited below are verified present at v0.8.3.

## Objective

Turn the dark FIR-4 pipeline into a switchable one: add the quality signals the old pipeline lost (sharpness, embedding-magnitude, landmark pose proxies, occlusion severity), add Hungarian within-photo one-to-one assignment, tune representative aggregation, calibrate every threshold on ACX data via the FIR-5 harness, produce the bake-off report that **proposes** gate criteria, and — only after the **operator records the gate decision in MCP** — flip the switch: face-pipeline profile default, `PGVECTOR_DIM` 512→128, buffalo eviction from prod images.

Slices are ordered by what gates them. S1–S3 are **corpus-independent and dark** — implementable now, in parallel lanes, mergeable without any gate ([RLSE-07] dark-until-gated). S4–S5 are **corpus-gated** (need the operator's Golden-150 real corpus + FIR-5 merged). S6 is **operator-gated** (blocked until the gate decision row exists; [RLSE-02]/[RLSE-03]).

## Intake

- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) — FIR-6 row, Success criteria 2/4/7, §Rollback.
- **Assessment**: [commercial-face-pipeline-replacement-assessment-2026-07-15.md](../../assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md) §4.4 (thresholds recalibrated, never copied), §6 (AdaFace/MagFace magnitude signal, Cluster-and-Aggregate, Fair-SA).
- **Anchor drift corrected here** (verified 2026-07-22): FIR-2 already centralized the dimension SSOT. `db/migrations/versions/001_identity_schema.py:17` derives `EMBEDDING_DIMENSION` from `get_database_settings().pgvector_dimension`; the only default to flip at switch-over is `PGVECTOR_DIM` (`db/settings.py:216`, default `"512"`) plus deploy configs. Older docs citing `001_identity_schema.py:14` as a second edit surface are stale.
- **FIR-4 landed surfaces consumed here**: `RECOGNITION_FACE_PIPELINE_PROFILE` (`recognition/config/settings.py:26,42-47`, allowed `{insightface, face_pipeline}`, default `insightface`, fail-closed on unknown values); `FacePipelineSettings` (`recognition/config/settings.py:125`); observability surface (per-scan detection count, assign/unknown ratio, quality-gate rejections, `embedding_model` in logs).
- **Neutral seam type**: `FaceDetection` (`recognition/application/embedding/detector.py:126`) — model-agnostic; already carries `pose_pitch/pose_yaw/pose_roll` (pose-bucket/diversity only), `landmark_quality: float | None`, `landmarks: LandmarkSet | None`, `model_id`. S1 extends this type; it is the one place factor fields live ([REF-19]).
- **Quality seam today**: `compute_identity_quality` (`recognition/application/assignment/quality.py:28`) is **pose-neutral by decision FIR2-BR-03** — score = confidence × size only; `threshold_adjustment` from `compute_quality_adjustment` with maturity damping. S1 must preserve this split.
- **Assignment flow today** (verified): discovery builds `AssignmentCandidate`s per face (`recognition/application/discovery/centroid.py`, `representative.py`, `graph/discovery.py`); `AssignmentGate` (`recognition/application/assignment/gate.py`) runs ordered checks; decisions persist via `AssignmentWriter.persist_assignment` (`recognition/application/persistence/assignment_writer.py:253`); orchestration lives in `recognition/application/orchestration/clustering/orchestrator.py` + `decision_handler.py`. No within-photo joint assignment exists (verified: no `linear_sum_assignment` under `recognition/`).
- **Latent dependency gap** (found at plan time): `scipy` is imported by `recognition/application/clustering/hierarchical_clustering.py:19` and `constrained_hac.py` but is **not declared** in `pyproject.toml` (only numpy is). S2 declares it explicitly (rg-001: no transitive masking; new import ⇒ real dependency + real build).

## Not-Doing

- No operator-gate judgment by any agent, ever — the report proposes, the operator decides ([RLSE-02]/[RLSE-03]).
- No corpus expansion beyond Golden-150; slices below floor stay DIRECTIONAL (scope sizing table).
- No detector/embedder retraining, no SFIQA-class learned quality model, no commercial SDKs (FIR-8, behind a failed operator gate).
- No GPU path (FIR-7), no HNSW, no model-registry service ([REF-12]).
- No `age`/`gender` resurrection.
- No production writes from any bake-off leg; buffalo stays eval-only (license isolation per FIR-5 plan; buffalo run artifacts never promoted out of `out/`).
- No copying of buffalo-tuned thresholds into face_pipeline defaults ([DRIFT-03], [PERF-06] via calibration only).
- No DB schema change in S1–S3 (factor columns, if calibration proves them worth persisting, are an S4-decided greenfield edit).

## Problem Statement

FIR-4 wired YuNet+SFace dark with buffalo-era thresholds and a quality gate that lost the signals the old stack provided (insightface pose/quality). SFace geometry ≠ buffalo geometry: every similarity/unknown/ambiguity threshold is uncalibrated for 128D ([DRIFT-03]). Multi-face photos are assigned per-face independently, allowing duplicate identity assignments within one photo. Until calibration + quality rework land, the switch-over would ship a strictly worse product; until the operator records a gate decision, the switch-over must not land at all.

## Constraints

- **Dark until gated** ([RLSE-07]): every S1–S3 change is inert under the `insightface` profile default. Behavior changes activate only under `face_pipeline` profile (dev/eval) until S6 flips the default. Existing insightface-profile tests must pass unchanged — that is the per-slice regression gate.
- **Pose-neutral canonical quality stands** (FIR2-BR-03): new quality factors feed (a) enrollment/aggregation gating and (b) observability, not the canonical `score` formula, until S4 calibration explicitly decides otherwise with measurement ([EVAL-22]: an unvalidated proxy must not silently gate).
- **No gating on unvalidated floors** ([EVAL-22]): all S1/S3 factor floors ship as **permissive no-op defaults** (accept-everything). Active exclusion begins only when S4 records measured floors as an MCP decision. A test proves the no-op default excludes nothing.
- **Multi-dimensional quality, not one scalar** ([CAL-09]): factors carry a per-factor breakdown (sharpness, embedding_norm, occlusion_severity, pose proxies), never collapsed into a single opaque number.
- **Unknown is a valid result** ([CAL-02]): joint assignment and calibration preserve an explicit reject path; no forced nearest-name.
- **Calibration honesty** ([CAL-07]): Golden-150 serves both calibration and gate evaluation. S4 uses subject-disjoint K-fold cross-validation over roster identities (fit on K−1 folds, read on the held fold, aggregate); the S5 report states the protocol and residual overlap risk explicitly. The operator judges with eyes open.
- **Per-stratum calibration** ([CAL-01], [CAL-05]): thresholds are examined per quality stratum (occlusion/blur/low-res tags); any global-threshold elevation to fix one stratum reports its FNMR tax on the others. Demographic-conditioned thresholds are forbidden ([CAL-06]) — strata are quality strata, never demographic fields.
- **Threshold from matched non-mates** ([CAL-04]): impostor pairs for calibration come from the corpus's own hard negatives (similar-people stratum first), not zero-effort random pairs.
- **Aggregation is robust, not a raw mean** ([EMB-02], [EMB-07], [EMB-10]): representative/template tuning gates weak observations by quality factors and compares quality-weighted aggregates/medoids; per-source weighting is declared in code.
- **Magnitude signal is pre-normalization** ([EMB-03]): `OrtSFaceEmbedder` (`recognition/infrastructure/face_pipeline/ort_adapters.py:371`) L2-normalizes its output; ‖z‖ must be captured **before** normalization inside the adapter — after normalization it is identically 1 and vacuous. A test proves the captured norm varies across inputs (a constant-1.0 capture is the vacuous-assertion trap, [TEST-15]).
- **New settings knobs validate at load, fail-closed** (rg-008): every knob S1–S3 adds to `FacePipelineSettings` follows the `_resolve_face_pipeline_profile` pattern — malformed values raise at startup, never silently default.
- **Determinism**: the calibration CLI and any re-scoring are pure functions of run artifacts → re-runnable bit-identically (mirrors FIR-5 determinism layer 1); no wall-clock, no RNG without pinned seed.
- **Scoped TDD locally, full suite remotely**: per-slice `uv run --extra dev pytest <scoped>` in the lane; `make check-remote` green at every merge gate. No local full-suite runs.
- **Branch/merge discipline**: each slice lands on `feature/fir-6` only through an adversarial `/review-parallel` pass (≥1 local Claude + ≥1 remote grok reviewer), findings recorded in MCP, fixed in place; `handoff_close_check(enforce=True)` before `feature/fir-6` → `main`.

## Contract and Boundary Impact

- **External contracts: none.** WP plugin REST surface, workbench API, and export projections are untouched (age/gender already dropped in FIR-2; no new projection fields in S1–S5).
- **Internal seam (additive only)**: `FaceDetection` gains optional factor fields defaulting to `None` (S1). Every existing producer (insightface adapter, stubs) remains valid without edits; consumers treat `None` as "factor unavailable". No constructor-signature break.
- **Settings (additive)**: new `FacePipelineSettings` knobs with validated, fail-closed parsing (rg-008); no renames of existing keys.
- **DB schema**: unchanged through S1–S5. S6 flips `PGVECTOR_DIM` default (greenfield reset semantics per scope §Rollback); any factor-persistence columns are decided in S4 and would land as a greenfield `001` edit with `sync/verify_identity_schema` parity ([rg-005]).
- **Deploy configs**: touched only in S6 (enumerated flip of `PGVECTOR_DIM` + profile default + image contents).

## Slices

### S1 — Quality-signal rework (dark; corpus-independent; lane-parallel)

**Deliverables**

1. **Pre-norm embedding magnitude** ([EMB-03]): in `OrtSFaceEmbedder.embed` capture `float(np.linalg.norm(z))` per face **before** the L2-normalize step; return it alongside the normalized embedding (extend the adapter's return path — `_common.py` result shape — without breaking existing callers).
2. **Sharpness factor**: variance-of-Laplacian on the aligned 112×112 crop the embedder already consumes (compute in the adapter where the crop exists — no second decode, no re-alignment).
3. **Landmark pose proxies**: yaw/roll proxies from the 5-point `LandmarkSet` (inter-ocular vector angle → roll; eye-midpoint↔nose horizontal offset normalized by inter-ocular distance → yaw). Written to the existing `pose_yaw`/`pose_roll` fields on `FaceDetection` under the face_pipeline profile; feeds pose-bucket/diversity logic only — canonical quality stays pose-neutral (FIR2-BR-03).
4. **Occlusion-severity proxy**: per-eye patch statistics on the aligned crop (patch variance + edge energy vs whole-crop baseline; YuNet emits no per-landmark confidence, so patch stats are the honest signal — do not pretend a confidence exists). Bounded [0,1] severity.
5. **Factor plumbing (the load-bearing part — exact path)**: extend `FaceDetection` (`detector.py:126`) with `sharpness: float | None = None`, `embedding_norm: float | None = None`, `occlusion_severity: float | None = None`. The face_pipeline adapter path populates them at detection/embed time; the insightface path leaves them `None`. Consumers: (a) FIR-4's observability emit site logs the per-factor breakdown ([CAL-09]); (b) `representative_selector.py` / `AssignmentWriter._create_and_add_representative` (`assignment_writer.py:189`) reads them for S3's enrollment gating. **No DB write in S1** — factors live on the in-process `FaceDetection` and in logs/metrics only.
6. New settings: factor-floor knobs on `FacePipelineSettings` with **permissive no-op defaults** ([EVAL-22] constraint above), validated fail-closed (rg-008).

**Tests** (exact paths): `recognition/tests/unit/test_face_quality_factors.py` — factor discrimination goldens on synthetic crops (blurred < sharp on sharpness; occluded > clean on severity; **ordering asserted**, [TEST-15]/[TEST-06]); pre-norm capture varies across inputs; all factors `None` under insightface profile; no-op floors exclude nothing. Existing `recognition/tests/unit/test_identity_quality.py` green unchanged.

**Verify**: `uv run --extra dev pytest recognition/tests/unit/test_face_quality_factors.py recognition/tests/unit/test_identity_quality.py -q`

### S2 — Hungarian within-photo one-to-one assignment (dark; corpus-independent; lane-parallel)

**Deliverables**

1. Declare `scipy` in `pyproject.toml` (closes the latent undeclared-import gap; rg-001) and prove with a real build/import in the lane.
2. Pure function `assign_faces_one_to_one` in a new module `recognition/application/assignment/joint.py`: input = per-photo mapping `{face_id: [gate-passed AssignmentCandidate, ...]}` (candidates come from the existing discovery modules — `discovery/centroid.py`, `discovery/representative.py`, `discovery/graph/discovery.py` — **already similarity-pre-filtered per face**, so the matrix is `n_faces × n_distinct_candidate_clusters` over the union of those short lists — bounded by discovery's own limits, never all-clusters). `scipy.optimize.linear_sum_assignment` maximizes total similarity; any pair below the accept threshold is struck **before** solving (padded with −∞/invalid), so unmatched faces fall to the existing unknown path ([CAL-02]). One cluster wins at most one face per photo.
3. Wiring: inside `recognition/application/orchestration/clustering/decision_handler.py` (the point where per-face `AssignmentDecision`s are formed), applied **after** `AssignmentGate` checks, only under the face_pipeline profile; `insightface` profile keeps today's per-face independent path bit-for-bit.
4. **Mirror/collage escape hatch**: `FacePipelineSettings.joint_assignment_enabled: bool` (default `True` within face_pipeline; validated rg-008). The mirrors-stratum measurement (S5 report) decides the shipped default; S2 guarantees the knob and tests both paths. No heuristic mirror detector here ([ARCH-08] boring-first).

**Tests** (exact path): `recognition/tests/unit/test_joint_assignment.py` — duplicate-identity photo resolves one-to-one (the exact failure the independent path allows today, [TEST-15]); below-threshold pair stays unknown; single-face photo unchanged; knob-off path identical to legacy; matrix-bound property (candidates only from provided lists). Dependency proof: importing `recognition.application.assignment.joint` in a `uv sync`-fresh lane env succeeds.

**Verify**: `uv run --extra dev pytest recognition/tests/unit/test_joint_assignment.py -q`

### S3 — Representative/medoid aggregation tuning + calibration CLI scaffold (dark; corpus-independent; lane-parallel)

**Deliverables**

1. **Aggregation rework** ([EMB-02]/[EMB-07]/[EMB-10]): quality-gated enrollment in `representative_selector.py` + `AssignmentWriter._create_and_add_representative` — observations failing S1 factor floors are excluded from representative/centroid updates; representative scoring gains quality-weighted terms; per-source weighting declared in code. **Floors default permissive no-op** ([EVAL-22]); behavior under insightface profile bit-identical.
2. **Calibration CLI scaffold**: `scripts/eval_harness/calibrate_face_thresholds.py` — consumes FIR-5 face-report τ-sweep JSON artifacts **by documented schema** (no import of `feature/fir-5` code; artifact-schema coupling only, so S3 does not depend on the FIR-5 merge) and emits a **proposed** per-stratum threshold set ([CAL-01]) with subject-disjoint K-fold protocol ([CAL-07]), matched-non-mate impostor selection ([CAL-04]), and FNMR-tax reporting for stratum-driven global elevation ([CAL-05]). Pure artifact→artifact, deterministic; **writes no product settings**.
3. Synthetic τ-sweep fixture + goldens (no corpus needed).

**Tests** (exact paths): `recognition/tests/unit/test_representative_quality_gate.py` — below-floor observation excluded when floors are active, nothing excluded at no-op defaults ([EMB-02] regression + [EVAL-22] proof); `scripts/eval_harness/tests/test_calibrate_face_thresholds.py` — CLI determinism (bit-identical re-run), K-fold subject-disjointness property (no identity in both fit and read folds).

**Verify**: `uv run --extra dev pytest recognition/tests/unit/test_representative_quality_gate.py scripts/eval_harness/tests/test_calibrate_face_thresholds.py -q`

### S4 — Calibration on real Golden-150 (**corpus-gated**; needs FIR-5 merged + operator corpus)

Run the FIR-5 harness on the real corpus; run the S3 CLI over its artifacts; select proposed thresholds per stratum; record the calibration decision + artifacts in MCP. Any promotion of an S1 factor into canonical quality scoring — and any activation of factor floors — happens here, with measured before/after slice deltas ([EVAL-08]/[EVAL-22]), never by default. If calibration proves factor persistence is needed, the greenfield `001` column addition is decided and executed here with schema parity ([rg-005]).

### S5 — Bake-off report proposing gate criteria (**corpus-gated**)

FIR-5 report machinery + S3/S4 outputs → a report that **proposes** gate criteria: headline identification P/R, three synthetic-paired occlusion slices, unknown-rejection ([EVAL-18] non-mated probes at score threshold), false-merge/false-split, throughput/cost leg ([PERF-01]/[PERF-07]), per-slice rollups with floor status honestly marked DIRECTIONAL where under floor, mirrors-stratum measurement → S2 knob recommendation, calibration protocol disclosure ([CAL-07]). End-to-end units: detection failures count against identification ([EVAL-16]); template-level evaluation mirrors the deployed aggregation path ([EVAL-17]). Report lands as artifact + MCP decision; **no gate verdict anywhere in it**.

### S6 — Switch-over (**operator-gated**; blocked until the MCP gate decision row exists)

Preconditions, verified in-slice before any edit: (a) operator gate decision id exists in MCP with a pass verdict and is cited in the slice decision; (b) FIR-2's tenant wipe/re-scan sign-off decision cited.

1. Flip `RECOGNITION_FACE_PIPELINE_PROFILE` default `insightface` → `face_pipeline` (`recognition/config/settings.py:44`).
2. Flip `PGVECTOR_DIM` default `"512"` → `"128"` (`db/settings.py:216`) + every deploy config that pins it: `.env*`, `docker-compose*.yml`, `infra/oci/**`, reset scripts (enumerate by grep at implementation time; the enumeration lands in the slice decision).
3. Evict buffalo weights + insightface from production images (Dockerfiles/provisioning); `[bench]` extra untouched for eval.
4. Greenfield reset path exercised per scope §Rollback; previous release image stays tagged (rollback = redeploy + reset).
5. Repo-wide sweep: no remaining prod-path reference to buffalo/insightface outside `[bench]`/eval-harness (rides FIR-4's sweep; re-verify).

**Verify**: `make check-remote` green at flipped defaults; boot-time `check_model_cache` fail-closed proof against a tampered hash (existing FIR-4 test re-anchored to the new default).

## Files and Surfaces to Change

| Slice | Files (all under `apps/prototype-description-service/` unless noted) |
| --- | --- |
| S1 | `recognition/infrastructure/face_pipeline/ort_adapters.py` (`OrtSFaceEmbedder.embed`, sharpness/occlusion at crop site), `recognition/infrastructure/face_pipeline/_common.py` (result shape), `recognition/application/embedding/detector.py` (`FaceDetection` fields), `recognition/config/settings.py` (`FacePipelineSettings` knobs), FIR-4 observability emit site, new `recognition/tests/unit/test_face_quality_factors.py` |
| S2 | `pyproject.toml` (scipy), new `recognition/application/assignment/joint.py`, `recognition/application/orchestration/clustering/decision_handler.py`, `recognition/config/settings.py` (knob), new `recognition/tests/unit/test_joint_assignment.py` |
| S3 | `recognition/application/persistence/representative_selector.py`, `recognition/application/persistence/assignment_writer.py` (`_create_and_add_representative`), new `scripts/eval_harness/calibrate_face_thresholds.py` + tests |
| S4–S5 | eval-harness run configs + MCP artifacts (no runtime code unless S4 decides factor persistence) |
| S6 | `recognition/config/settings.py:44`, `db/settings.py:216`, `.env*`, `docker-compose*.yml`, `infra/oci/**`, reset scripts, Dockerfiles |

## Verification Strategy

Per-slice scoped pytest (commands above, exact paths committed). Regression gate per slice: full existing insightface-profile unit suites for touched modules green unchanged. `make check-remote` green on `feature/fir-6` after each lane merge and before the `main` merge. Calibration CLI: determinism re-run bit-identical. S6: `make check-remote` at flipped defaults + fail-closed hash proof. Full suite never runs locally.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane | Slice | Branch | Backend | test_cmd |
| --- | --- | --- | --- | --- |
| `fir6-s1` | S1 | `feature/fir6-s1` | grok-remote (HIGH) | `cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/unit/test_face_quality_factors.py recognition/tests/unit/test_identity_quality.py -q` |
| `fir6-s2` | S2 | `feature/fir6-s2` | grok-remote (HIGH) | `cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/unit/test_joint_assignment.py -q` |
| `fir6-s3` | S3 | `feature/fir6-s3` | grok-remote (HIGH) | `cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/unit/test_representative_quality_gate.py scripts/eval_harness/tests/test_calibrate_face_thresholds.py -q` |

Every lane worktree carries `.heuristics-canon/lexicons/` (unfiltered mirror) + a brief citing the relevant canon IDs + a semantic-reinjection packet from handoff.db for cold-start context.

### Merge Order

S1 → S2 → S3 into `feature/fir-6` (S3 reads S1's factor fields; S2 is independent of both but merges second to keep rebase cost low). Coordinator rebases later lanes on collision. Each merge gated by adversarial `/review-parallel` (≥1 local Claude + ≥1 remote grok), findings fixed in place before merge.

### Orchestration Mode

`dispatch_wave` over the three lanes (grok-remote, HIGH effort); coordinator (this session) reviews, gates, merges. S4–S6 are single-lane/coordinator work, not wave work.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded scope §FIR-6, assessment §4.4/§6, canon v0.8.3 lexicons, and the anchors above before editing.
- [ ] No external contract touched (S1–S5); S6 deploy-config ownership stays with this task and cites the operator gate decision.

### Checklist for S1: Quality-signal rework

- [ ] `FaceDetection` factor fields + adapter capture (pre-norm ‖z‖, sharpness, occlusion severity, pose proxies) implemented dark
- [ ] Observability emits per-factor breakdown; no DB writes
- [ ] Discriminating tests green (`test_face_quality_factors.py`); insightface-profile regression green

### Checklist for S2: One-to-one assignment

- [ ] scipy declared + build-proven; `joint.py` pure solver with reject path
- [ ] `decision_handler.py` wiring dark; knob validated fail-closed
- [ ] `test_joint_assignment.py` green incl. knob-off parity

### Checklist for S3: Aggregation + calibration CLI

- [ ] Quality-gated enrollment with permissive no-op floors; insightface parity
- [ ] `calibrate_face_thresholds.py` deterministic, subject-disjoint K-fold, writes no settings
- [ ] Both test files green

### Checklist for S4–S6 (gated)

- [ ] [corpus-gated] S4 calibration recorded in MCP with protocol disclosure
- [ ] [corpus-gated] S5 report artifact recorded; proposes criteria; no verdict
- [ ] [operator-gated] Gate decision row cited; S6 flips executed; `make check-remote` green at flipped defaults

### Review Readiness

- [ ] Each lane merge passed adversarial `/review-parallel` (≥1 remote grok + ≥1 local); findings fixed/closed in MCP, never pasted into this plan
- [ ] Slice decisions recorded via `close_slice` with full 40-char SHAs
- [ ] `make check-remote` green on `feature/fir-6` before the `main` merge

### Success Criteria

- [ ] Dark pipeline carries validated quality factors, one-to-one assignment, robust aggregation — all inert at prod defaults until S6
- [ ] Calibration + report exist as MCP-recorded artifacts proposing (not judging) the gate
- [ ] Switch-over lands only after the operator gate decision, flipping profile + dimension + image contents together
- [ ] Pre-merge gate `handoff_close_check(enforce=True)` passes; task `done` + archived
