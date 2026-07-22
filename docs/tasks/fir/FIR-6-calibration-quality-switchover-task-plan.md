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
- **Anchor drift corrected here** (verified 2026-07-22): FIR-2 already centralized the dimension SSOT. `001_identity_schema.py:17` now derives `EMBEDDING_DIMENSION` from `get_database_settings().pgvector_dimension`; the only default to flip at switch-over is `PGVECTOR_DIM` (`db/settings.py:216`, default `"512"`) plus deploy configs. Older docs citing `001_identity_schema.py:14` as a second edit surface are stale.
- **FIR-4 landed surfaces consumed here**: `RECOGNITION_FACE_PIPELINE_PROFILE` (`recognition/config/settings.py:26,42-47`, allowed `{insightface, face_pipeline}`, default `insightface`, fail-closed on unknown values); observability surface (per-scan detection count, assign/unknown ratio, quality-gate rejections, `embedding_model` in logs).
- **Quality seam today**: `compute_identity_quality` (`recognition/application/assignment/quality.py:28`) is **pose-neutral by decision FIR2-BR-03** — score = confidence × size only; `threshold_adjustment` comes from `compute_quality_adjustment` with maturity damping. Pose stays available on FaceDetection/MediaIdentity for pose-bucket/diversity logic only. S1 must preserve this split.
- **Assignment seam today**: `AssignmentGate` (`recognition/application/assignment/gate.py`) routes candidates through ordered checks (block/confidence/constraint); no within-photo joint assignment exists (verified: no `linear_sum_assignment` under `recognition/`).
- **Latent dependency gap** (found at plan time): `scipy` is imported by `recognition/application/clustering/hierarchical_clustering.py:19` and `constrained_hac.py` but is **not declared** in `pyproject.toml` (only numpy is). S2 declares it explicitly (rg-001: no type-shim/transitive masking; new import ⇒ real dependency + real build).

## Not-Doing

- No operator-gate judgment by any agent, ever — the report proposes, the operator decides ([RLSE-02]/[RLSE-03]).
- No corpus expansion beyond Golden-150; slices below floor stay DIRECTIONAL (scope sizing table).
- No detector/embedder retraining, no SFIQA-class learned quality model, no commercial SDKs (FIR-8, behind a failed operator gate).
- No GPU path (FIR-7), no HNSW, no model-registry service ([REF-12]).
- No `age`/`gender` resurrection.
- No production writes from any bake-off leg; buffalo stays eval-only (license isolation per FIR-5 plan; buffalo run artifacts never promoted out of `out/`).
- No copying of buffalo-tuned thresholds into face_pipeline defaults ([DRIFT-03], [PERF-06] via calibration only).

## Problem Statement

FIR-4 wired YuNet+SFace dark with buffalo-era thresholds and a quality gate that lost the signals the old stack provided (insightface pose/quality). SFace geometry ≠ buffalo geometry: every similarity/unknown/ambiguity threshold is uncalibrated for 128D ([DRIFT-03]). Multi-face photos are assigned greedily per-face, allowing duplicate identity assignments within one photo. Until calibration + quality rework land, the switch-over would ship a strictly worse product; until the operator records a gate decision, the switch-over must not land at all.

## Constraints

- **Dark until gated** ([RLSE-07]): every S1–S3 change is inert under the `insightface` profile default. Behavior changes activate only under `face_pipeline` profile (dev/eval) until S6 flips the default. Existing insightface-profile tests must pass unchanged — that is the per-slice regression gate.
- **Pose-neutral canonical quality stands** (FIR2-BR-03): new quality factors feed (a) enrollment/aggregation gating and (b) observability, not the canonical `score` formula, until S4 calibration explicitly decides otherwise with measurement ([EVAL-22]: an unvalidated proxy must not silently gate).
- **Multi-dimensional quality, not one scalar** ([CAL-09]): factors are stored/emitted with a per-factor breakdown (sharpness, magnitude, occlusion severity, pose proxies), never collapsed into a single opaque number.
- **Unknown is a valid result** ([CAL-02]): joint assignment and calibration must preserve an explicit reject path; no forced nearest-name.
- **Calibration honesty** ([CAL-07]): Golden-150 serves both calibration and gate evaluation. The calibration protocol must not fit thresholds on the same faces the gate metric is read from without disclosure: S4 uses subject-disjoint K-fold cross-validation over roster identities (fit on K−1 folds, read on the held fold, aggregate), and the S5 report states the protocol and residual overlap risk explicitly. The operator judges with eyes open.
- **Per-stratum calibration** ([CAL-01], [CAL-05]): thresholds are examined per quality stratum (occlusion/blur/low-res tags); any global-threshold elevation to fix one stratum reports its FNMR tax on the others. Demographic-conditioned thresholds are forbidden ([CAL-06] by exclusion — strata are quality strata, never demographic fields).
- **Threshold from matched non-mates** ([CAL-04]): impostor pairs for calibration come from the corpus's own hard negatives (similar-people stratum first), not zero-effort random pairs.
- **Aggregation is robust, not a raw mean** ([EMB-02], [EMB-07], [EMB-10]): representative/template tuning gates weak observations by quality factors and compares quality-weighted aggregates/medoids; per-source weighting is declared.
- **Magnitude signal is pre-normalization** ([EMB-03]): `OrtSFaceEmbedder` L2-normalizes its output; the ‖z‖ quality proxy must be captured **before** normalization inside the adapter and carried as an optional neutral field — after normalization it is identically 1 and vacuous. A test must prove the captured norm varies across inputs (a constant-1.0 capture is the vacuous-assertion trap, [TEST-15]).
- **Determinism**: the calibration CLI and any re-scoring are pure functions of run artifacts → re-runnable bit-identically (mirrors FIR-5 determinism layer 1); no wall-clock, no RNG without pinned seed.
- **Scoped TDD locally, full suite remotely**: per-slice `uv run --extra dev pytest <scoped>` in the lane; `make check-remote` green at every merge gate. No local full-suite runs.
- **Branch/merge discipline**: each slice lands on `feature/fir-6` only through an adversarial `/review-parallel` pass (≥1 local Claude + ≥1 remote grok reviewer), findings recorded in MCP, fixed in place; `handoff_close_check(enforce=True)` before `feature/fir-6` → `main`.

## Slices

### S1 — Quality-signal rework (dark; corpus-independent; lane-parallel)

**Deliverables**

1. **Pre-norm embedding magnitude** ([EMB-03]): capture ‖z‖ before L2-normalization in `OrtSFaceEmbedder` (`recognition/infrastructure/face_pipeline/ort_adapters.py`); surface as optional `embedding_norm: float | None` on the model-neutral detection dataclass ([REF-19]: neutral field, no SFace-specific naming leak). `insightface` profile leaves it `None`.
2. **Sharpness factor**: variance-of-Laplacian computed on the aligned 112×112 crop (the aligner output the embedder already consumes — no second decode).
3. **Landmark pose proxies**: yaw/roll proxies from 5-point landmark geometry (inter-ocular vector angle → roll; eye-midpoint↔nose horizontal offset normalized by inter-ocular distance → yaw proxy). Stored on the existing nullable pose fields; feeds pose-bucket/diversity logic only — canonical quality stays pose-neutral (FIR2-BR-03).
4. **Occlusion-severity proxy**: eye-region patch statistics on the aligned crop (per-eye patch variance + edge energy vs whole-crop baseline; YuNet emits no per-landmark confidence, so patch stats are the honest signal — the plan does not pretend a confidence exists). Emitted as a bounded [0,1] severity factor.
5. **Quality factor container** ([CAL-09]): a frozen dataclass `FaceQualityFactors` (sharpness, embedding_norm, occlusion_severity, pose proxies) attached alongside `IdentityQualityInfo` — canonical `score`/`threshold_adjustment` formula **unchanged**; factors persisted for observability + S3/S4 consumption (extend the FIR-4 log/metrics surface with the per-factor breakdown).

**Tests** (scoped): factor computation goldens on synthetic crops (blurred vs sharp, occluded vs clean — each factor must **discriminate**, [TEST-15]/[TEST-06]: assert the ordering, not mere presence); pre-norm capture varies across inputs and is `None` under insightface profile; insightface-profile regression suite untouched and green.

**Verify**: `uv run --extra dev pytest recognition/tests/unit/test_identity_quality.py recognition/tests/unit/test_face_quality_factors.py -q` (new file names indicative).

### S2 — Hungarian within-photo one-to-one assignment (dark; corpus-independent; lane-parallel)

**Deliverables**

1. Declare `scipy` in `pyproject.toml` (closes the latent undeclared-import gap; rg-001) and verify with a real build/import in the lane.
2. A pure function `assign_faces_one_to_one(candidates) -> assignments` using `scipy.optimize.linear_sum_assignment` maximizing total similarity over the (photo-local faces × candidate clusters) matrix, applied **after** the quality gate, with per-pair threshold floors: a pair below the accept threshold is never forced — unmatched faces fall to the existing unknown path ([CAL-02]). One cluster may win at most one face per photo; one face at most one cluster.
3. Wiring inside the `face_pipeline` profile assignment flow only (`AssignmentGate` consumers); `insightface` profile keeps today's per-face independent path bit-for-bit.
4. **Mirror/collage escape hatch**: a config flag (`FacePipelineSettings`) `joint_assignment_enabled` (default on within face_pipeline) plus a documented bypass condition left as a settings knob — the mirrors-stratum measurement (S5 report) decides the shipped default; S2 only guarantees the knob exists and both paths are tested. No heuristic mirror detector is built here ([ARCH-08] boring-first).

**Tests**: duplicate-identity photo resolves to one-to-one (the exact failure the greedy path allows today — regression-proof it, [TEST-15]); below-threshold pair stays unknown; single-face photo path unchanged; knob-off path identical to legacy; scipy import declared (a test importing the module under a clean env proves the dependency is real).

**Verify**: `uv run --extra dev pytest recognition/tests/unit/test_joint_assignment.py -q` + lane build check.

### S3 — Representative/medoid aggregation tuning + calibration CLI scaffold (dark; corpus-independent; lane-parallel)

**Deliverables**

1. **Aggregation rework** ([EMB-02]/[EMB-07]/[EMB-10]): quality-gated enrollment into `IdentityClusterRepresentative` selection — observations failing S1 factor floors (settings-defined, conservative defaults, dark) are excluded from representative/centroid updates; representative scoring gains quality-weighted terms; per-source weighting declared in code. Existing selection behavior preserved under insightface profile.
2. **Calibration CLI scaffold** (`scripts/eval_harness/` or service-local `scripts/`): consumes FIR-5 face-report artifacts (τ-sweep JSON) and emits a **proposed** threshold set per stratum ([CAL-01]) with subject-disjoint K-fold protocol ([CAL-07]), matched-non-mate impostor selection ([CAL-04]), and FNMR-tax reporting for any stratum-driven global elevation ([CAL-05]). Pure artifact→artifact, deterministic, re-runnable; **writes no product settings** — output is a proposal document for S4/S5 and the operator.
3. Unit-level goldens for the CLI on a small synthetic τ-sweep fixture (no corpus needed).

**Tests**: quality-gated enrollment excludes a below-floor observation and keeps the representative stable ([EMB-02] regression); CLI determinism (bit-identical re-run); K-fold subject-disjointness property test (no identity appears in both fit and read folds).

**Verify**: `uv run --extra dev pytest recognition/tests/unit/test_representative_quality_gate.py scripts/eval_harness/tests/test_calibration_cli.py -q` (paths indicative; harness test location follows FIR-5 conventions on merge).

### S4 — Calibration on real Golden-150 (**corpus-gated**; needs FIR-5 merged + operator corpus)

Run the FIR-5 harness on the real corpus; run the S3 CLI over its artifacts; select proposed thresholds per stratum; record the calibration decision + artifacts in MCP. Any promotion of an S1 factor into canonical quality scoring happens here, with measured before/after slice deltas ([EVAL-08]/[EVAL-22]), never by default.

### S5 — Bake-off report proposing gate criteria (**corpus-gated**)

The FIR-5 report machinery + S3/S4 outputs → a report that **proposes** gate criteria: headline identification P/R, three synthetic-paired occlusion slices, unknown-rejection ([EVAL-18] non-mated probes at score threshold), false-merge/false-split, throughput/cost leg ([PERF-01]/[PERF-07]), per-slice rollups with floor status honestly marked DIRECTIONAL where under floor, mirrors-stratum measurement → S2 knob recommendation, calibration protocol disclosure ([CAL-07]). End-to-end units: detection failures count against identification ([EVAL-16]); template-level evaluation mirrors the deployed aggregation path ([EVAL-17]). Report lands as artifact + MCP decision; **no gate verdict anywhere in it**.

### S6 — Switch-over (**operator-gated**; blocked until the MCP gate decision row exists)

Preconditions, verified in-slice before any edit: (a) operator gate decision id exists in MCP with a pass verdict and is cited in the slice decision; (b) FIR-2's tenant wipe/re-scan sign-off decision cited.

1. Flip `RECOGNITION_FACE_PIPELINE_PROFILE` default `insightface` → `face_pipeline` (`recognition/config/settings.py:44`).
2. Flip `PGVECTOR_DIM` default `"512"` → `"128"` (`db/settings.py:216`) + every deploy config that pins it: `.env*`, `docker-compose*.yml`, `infra/oci/**`, reset scripts (enumerate by grep at implementation time; the enumeration lands in the slice decision).
3. Evict buffalo weights + insightface from production images (Dockerfiles/provisioning); `[bench]` extra untouched for eval.
4. Greenfield reset path exercised per scope §Rollback; previous release image stays tagged (rollback = redeploy + reset).
5. Repo-wide sweep: no remaining prod-path reference to buffalo/insightface outside `[bench]`/eval-harness (rides FIR-4's earlier sweep; re-verify).

**Verify**: `make check-remote` green at the flipped defaults; boot-time `check_model_cache` fail-closed proof against a tampered hash (existing FIR-4 test re-anchored to the new default).

## Sequencing & lane map

- S1, S2, S3 dispatch **now** as three parallel remote grok lanes off `feature/fir-6` (lane worktrees, lane branches, merged back one-by-one through `/review-parallel`). Cross-lane file contention is low (S1: adapters+quality; S2: assignment+pyproject; S3: representatives+CLI); the coordinator merges in S1→S2→S3 order and rebases lanes on collision.
- S4–S5 wait on: operator Golden-150 curation → FIR-5 pre-merge gate → FIR-5 merge → then a single lane (or coordinator-local run) per slice.
- S6 waits on the operator's recorded gate decision; it is a single small slice with an outsized blast radius — implement solo, review with full coverage.

## Consolidated Checklist

- [ ] S1 quality factors implemented dark + discriminating tests green (scoped)
- [ ] S2 one-to-one assignment implemented dark + scipy declared + tests green (scoped)
- [ ] S3 aggregation gating + calibration CLI scaffold + determinism tests green (scoped)
- [ ] S1–S3 each merged to `feature/fir-6` through adversarial `/review-parallel` (≥1 remote grok + ≥1 local), findings fixed/closed in MCP
- [ ] `make check-remote` green on `feature/fir-6` after S1–S3
- [ ] [corpus-gated] S4 calibration run recorded in MCP with protocol disclosure
- [ ] [corpus-gated] S5 report artifact recorded; proposes criteria; no verdict
- [ ] [operator-gated] Gate decision row exists; S6 implemented citing it; `make check-remote` green at flipped defaults
- [ ] Pre-merge gate `handoff_close_check(enforce=True)` passes; `feature/fir-6` merged; task `done` + archived
