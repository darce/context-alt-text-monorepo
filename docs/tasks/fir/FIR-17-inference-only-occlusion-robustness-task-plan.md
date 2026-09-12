# Task Plan — FIR-17. Inference-only occlusion robustness: visible-support matching, pose head rescue, OACT direction fix

> **Metadata**
>
> - **Date**: 2026-09-11
> - **Author**: Claude Fable 5.1 (claude-fable-5-1) via sonnet drafting agent
> - **Owning Epic**: `docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md`
> - **Epic Short ID**: FIR
> - **Task ID**: FIR-17
> - **Target Branch**: `feature/fir-17`
> - **Review Coverage Target**: 2
> - **Status**: draft
>
> Review counts/finding totals live in the handoff DB, not this file.

---

## FIR-17. Inference-only occlusion robustness: visible-support matching, pose head rescue, OACT direction fix

## Branch Rule (read this first — every slice below is conditional on it)

FIR-15's D-02 decision (`firplan_d02_attribution_<date>`) names the leg identity error concentrates in (`verdict: EMBEDDER | DETECTOR | BOTH | INCONCLUSIVE`). **S0 (the OACT sign fix) is unconditional and ships before this decision is even read** — it is a latent-bug fix independent of attribution, per the Constraints section's dark-launch note. Every other slice runs per the verdict:

| D-02 `verdict` | Slices that run | Rationale |
| --- | --- | --- |
| `EMBEDDER` | S0, S4, and S1 **only if** the oracle-gap gate below is open | Sign fix always. Matching approach (visible-support masking, S1) targets the embedder-side error and is verified end-to-end via the eval-harness wiring (S4). |
| `DETECTOR` | S0, S3 | Sign fix always. S1's masking gives no ceiling headroom on an alignment/detector-side error (masking narrows embedding dims, it does not fix misdetected/misaligned crops). The pose-rescue ADR spike (S2) is NOT run here — a confirmed detector-side share is strong enough evidence to warrant a dedicated follow-up task rather than an in-task feasibility spike; S3 documents that hand-off boundary. |
| `BOTH` | S0, S3, S4, and S1 **only if** the oracle-gap gate below is open | Sign fix always. Embedder-side evidence still justifies shipping S1+S4; the detector-side share is handled the same way as a pure `DETECTOR` verdict (S3 hand-off, no S2). |
| `INCONCLUSIVE` (FIR-15's own rule: `n_units < MIN_ATTRIBUTABLE_UNITS`, or both shares' CIs include 0, or both point estimates fall below `MATERIAL_SHARE_FLOOR`) | S0, S2, S3 | Sign fix always. Neither leg has usable evidence, so no masking work ships; the only additional deliverable is the pose-rescue feasibility spike (S2) — worth doing precisely when no other intervention has a evidence-backed target — plus the S3 hand-off note. |

**Oracle-gap gate on S1 (independent of `verdict`).** FIR-15's D-02 `verdict` is derived from the attribution shares alone — the oracle gap never enters it — so a `verdict` of `EMBEDDER` or `BOTH` can co-occur with an oracle gap whose 95% CI includes 0. When it does, S1 is **PROVISIONALLY PARKED at $0 before any production code is written** (FIR-15 S2, and FIR-15's REPORT.md records the reason verbatim); the parked branch runs exactly as the `DETECTOR` row does. DIAGNOSTIC/DIRECTIONAL evidence parks the masking track; only ADMISSIBLE evidence post FIR-11 R1 can terminate it. Lane `L1` therefore reads two things before its first commit: the decision's `verdict` field and the oracle-gap CI.

**S3 is a one-line code comment** (see S3 below); it ships once, in S0's commit, regardless of branch. It is called out as its own row above only for `DETECTOR`/`INCONCLUSIVE`, where S1 does not run, so the comment is not otherwise bundled into a masking-slice commit.

**Dependency**: this task cannot start implementation until FIR-15's D-02 decision is recorded in MCP. Lane `L1` reads the decision's `verdict` field and the oracle-gap CI before its first commit (see the oracle-gap gate above). S0 is the exception — it does not wait on D-02 and may land first.

## Objective

Ship inference-only occlusion robustness gated by FIR-15's attribution verdict: an OACT sign fix that ships regardless of verdict (S0), masked (visible-support) cosine matching where the embedder leg has evidence (S1), and a pose-head-rescue feasibility spike where no leg has usable evidence (S2). No training; PEFT/adapter work stays out of scope and stays frozen behind FIR-7's existing D-01 gate.

## Problem Statement

FIR-7 v6.2 froze its PEFT-adapter slices (2, 3, 4) behind `TRAINING_DECISION`/D-01, reached only via QA v8's T-09→T-14 re-gate — that gate has not fired. Meanwhile `compute_occlusion_severity`'s two-eye-patch proxy (`recognition/infrastructure/embeddings/face_quality_factors.py:82-105`) already runs in production computing an occlusion quality factor, but nothing in the matching path uses occlusion-region information to mask the embedding comparison, and `compute_quality_adjustment`'s OACT term (`recognition/application/assignment/quality.py:80-138`, term at line ~136) applies the coefficient backwards relative to FIR-6 S4's calibration semantics: the calibration OACT block prices a nonzero coefficient by elevating `tau`, while the current `-(coeff * severity)` runtime term lowers the accept threshold as occlusion increases. This task ships the $0, inference-only interventions that do not require the frozen training track, and closes the OACT sign bug independent of whether masking or pose-rescue end up justified.

**Which FIR-7 slices stay frozen, and why**: FIR-7 v6.2 Slices 0a, 0, and 1 are unconditional and already shipped/shippable (data prep, baseline harness, non-training scaffolding). Slices 2, 3, and 4 are the PEFT adapter training slices and are explicitly CONDITIONAL on `TRAINING_DECISION` — gated behind QA v8's D-01 decision, which is reached only via the T-09 (face-label rule) → T-14 (union adjudication dead-zone kill rule) re-gate sequence. That re-gate has not fired as of this task's drafting. FIR-17 does not touch, unblock, or duplicate FIR-7 Slices 2-4; it is scoped entirely to inference-time interventions that need no adapter weights and no GPU training spend (A10 GPU spend stays unauthorized for this task).

## Constraints

- **No training.** Zero GPU spend, zero adapter weights touched. This task is a pure inference-path change: masking dimensions, computing a per-region visibility signal, flipping the OACT term's sign, threading a new aggregate metric.
- **FIR-7 Slices 2-4 stay frozen.** See Problem Statement. This task must not read from or write to any FIR-7 adapter checkpoint path, and must not alter `TRAINING_DECISION` state.
- **Dark-launch/no-op-default discipline.** Every new knob defaults to the behavior-neutral value (disabled/0.0) so merging this task changes nothing in production until an operator flips a knob, mirroring `oact_coefficient`'s existing `default_factory` pattern (`settings.py:265-267`, `377-384`).
- **OACT sign fix is behaviour-neutral at the default coefficient value.** `oact_coefficient` defaults to `0.0` (`_resolve_face_oact_coefficient`, `settings.py:265-267`, `_env_or_default_nonneg`). `compute_quality_adjustment`'s OACT term (`quality.py:134-138`) is `0.0` at the coefficient's default regardless of sign: `-(0.0 * severity) == +(0.0 * severity) == 0.0`. The sign fix therefore changes behavior only once an operator sets `oact_coefficient` to a nonzero value at rollout (a separate, explicit act) — it is a latent-bug fix, not a behavior change, at merge time.
- **Masked-cosine and the FIR-15 eval-only version must converge on one shared pure function.** FIR-15 defines `masked_cosine(a, b, mask) -> float` in `recognition/infrastructure/embeddings/masked_similarity.py` as the single, settings-independent shared definition (FIR-15's eval-only `occlusion_ladder.py` imports it from there rather than defining it locally). This task's S1/S2 reuse that same import; S4 confirms there is exactly one definition and adds an import-isolation test. **Settings-independence must be checked transitively, not just at the host file's own import lines**: the pre-existing `recognition/shared/similarity.py` (verified, e.g. `face_embedding_dim()`) late-binds `recognition.config.settings` via a function-body `from recognition.config.settings import ...` rather than a module-level import — an AST/grep check that only scans `masked_similarity.py`'s top-level imports would miss a settings dependency reintroduced by importing helpers from `recognition/shared/similarity.py`. `masked_cosine`/`masked_similarity.py` must therefore not import from `recognition/shared/similarity.py` (implement its own minimal normalize/dot helpers instead), and S4's isolation test must walk the real import graph, not just the host file. See S1 and S4 below.
- **No pgvector re-rank needed.** Verified: the cosine similarity `ConfidenceCheck.evaluate` consumes (`confidence.py:91-242`, reading `candidate.discovery_similarity`) is NOT the result of a database `<=>` query. It is computed entirely in-process via numpy dot products against in-memory centroids in `CentroidDiscovery._find_best_centroid_match` (`centroid.py:62-87`), invoked from `CentroidDiscovery.discover` (`centroid.py:30-60`). This is a confirmed deviation from the program packet's speculative framing ("if the similarity comes from the pgvector `<=>` query, masked cosine must be applied as a re-rank over the top-K candidates after the DB query") — no DB re-rank stage exists or is needed; the interception point is the in-process similarity computation itself. See S1 below.
- **No pose/keypoint/person model exists anywhere in the service** (verified: `search_graph`/`search_code` sweep for `keypoint|pose|yolo|person` across the runtime found no model — all "pose"-adjacent hits are landmark-derived proxy metrics such as `compute_occlusion_severity`'s eye-patch heuristic, or test-only fakes). S2 ("pose head rescue") is therefore an ADR/spike deliverable, not an implementation slice — see S2.

## Workflow Principles

- Ship the cheap, reversible fix first: the OACT sign fix (S0) runs regardless of the D-02 verdict because it costs nothing and is behaviour-neutral at default.
- No shared logic forks between eval and runtime [dedupe pressure applies to correctness-critical math, not just style] — `masked_cosine` lives once, imported everywhere it is used.
- Dark-launch every new knob; a merge must never itself change production behavior [PRINCIPLE #15 counterpart: measure before shipping non-neutral defaults].
- A spike that finds "no model exists" is a valid, complete deliverable — it is not deferred work.
- Region-visibility must be an inference-time texture proxy, never an oracle occlusion mask — production has no ground-truth occlusion labels at match time (see S1).

## Terminology

- **OACT**: see the [FIR specification's Terminology block](../../specs/fir-open-set-gate-and-occlusion-spec.md#terminology) for the canonical expansion (single source of truth); here, the existing `oact_coefficient` scaffold adjusts the confidence threshold using occlusion severity in `compute_quality_adjustment` (`quality.py:80-138`).
- **Visible-support matching / masked cosine**: cosine similarity computed only over embedding dimensions attributed to unoccluded landmark regions (support mask), via the shared `masked_cosine(a, b, mask) -> float` pure function and the versioned support-map asset `sface-support-map-v1.json`.
- **Region visibility**: a per-region visibility estimate in `[0,1]` for each of the 5 SFace landmark regions, in FIR-15's pinned `REGION_NAMES` order (`right_eye`, `left_eye`, `nose`, `mouth_right`, `mouth_left`) — the order of `aligner.SFACE_CANONICAL_LANDMARKS_112`, not alphabetical and not image-left-first, produced at inference time from image texture alone (no oracle occlusion mask) by `estimate_region_visibility`.
- **Pose head rescue**: a hypothetical fallback that would use head-pose estimation to recover matchable regions under occlusion — **no model for this exists in the service today** (verified negative); S2 is scoped to determine feasibility, not to ship one.
- **`visible_support_applied`**: per-face boolean metadata set on an `AssignmentCandidate` when the masked-cosine path was used for that candidate's match; aggregated per clustering run as `visible_support_applied_count: int` (see S1/S2's runtime-integration note below and the event-tag fix in S4).
- **Branch rule**: the table at the top of this document, keyed to FIR-15's D-02 `verdict`.

## Current State Analysis

- **Works**: `ConfidenceCheck.evaluate` (`confidence.py:91-242`) consumes `discovery_similarity`; `CentroidDiscovery` (`centroid.py:17-87`) computes it in-process via `discover` (30-60) and `_find_best_centroid_match` (62-87); `compute_occlusion_severity` (`recognition/infrastructure/embeddings/face_quality_factors.py:82-105`) already produces a scalar occlusion signal from canonical eye-patch positions; `compute_face_quality_factors` (`face_quality_factors.py:139-158`) is the existing per-face entry point that already threads optional `landmarks` through to `compute_pose_proxies`; `oact_coefficient` scaffold (`settings.py:377-384`, `TestOactDarkScaffold`) already exists dark-launched at `0.0`; `resolve_face_pipeline_knobs` (`settings.py:549-599`) already profile-gates knobs between `insightface` and `face_pipeline` profiles; `_persist_identities` (`recognition/application/scan/service.py:409-550`) already writes `occlusion_severity` onto the persisted `MediaIdentity` row (line ~529), and the domain `MediaIdentity` (`recognition/domain/identity.py:14-57`) / ORM `MediaIdentity` (`db/models/identity.py:41-105`) already carry that quality-factor precedent (NULL under `insightface`, populated under `face_pipeline`).
- **Broken/missing**: no masked-cosine path exists anywhere in the matching code; no support-map asset or loader exists (this task ships the first version behind a knob, per FIR-15 S2's recipe); `compute_quality_adjustment`'s OACT term applies the coefficient backwards relative to calibration — `oact_term = -(coeff * severity)` (`quality.py:136`) lowers the accept threshold as occlusion rises while the calibration harness prices the coefficient as a positive tau elevation; no pose/keypoint model exists (verified negative — S2 here is a spike, not an implementation).
- **Misleading if untouched**: the packet's conditional framing ("if similarity comes from a pgvector query...") reads as though a DB re-rank stage might be needed — it is not; the correct interception point is the in-process numpy computation, confirmed above. An earlier draft of this plan also misnamed the quality-factor module path (`recognition/application/scan/face_quality_factors.py`, which does not exist) and proposed emitting `visible_support_applied` from `_emit_scan_media_reconciled` (`recognition/application/scan/service.py:583-641`), which only ever receives `result: ReconcileResult` (row-recycling counts) and `detections: list[FaceDetection]` — no `AssignmentCandidate`, no assignment/clustering data, by the class's own docstring ("Assignment/unknown metrics live in clustering (FIR-6)"). The correct emission site is the clustering-discovery layer (see S4).
- **Adjacent**: FIR-6 S4 owns writing the final calibrated `oact_coefficient` value into face_pipeline-scoped knobs after real-corpus calibration — this task's S0 fixes the *sign* the coefficient is applied with, not its calibrated magnitude; FIR-6 S4's apply step is the value hand-off target (see S3). `run_discovery_pipeline` (`recognition/application/orchestration/clustering/discovery_pipeline.py:476-527`) is the actual per-chunk clustering orchestrator that calls `CentroidDiscovery.discover` and already logs plain (non-structured) per-stage `logger.info` lines — the natural home for the new aggregate count (see S4).

## Target Outcome

Under every verdict, the OACT coefficient's sign is corrected (S0) and remains behaviour-neutral until an operator sets it nonzero, at which point FIR-6 S4's calibration apply step is the sanctioned place to set that nonzero value (S3 documents this boundary). Under `EMBEDDER`/`BOTH` verdicts, matching applies a versioned visible-support mask to the in-process cosine computation when occlusion is detected, tagging affected candidates with `visible_support_applied=True` and surfacing an aggregate `visible_support_applied_count` on the clustering-run log line (S1, S4). Under `INCONCLUSIVE`, an ADR records whether pose-head-rescue is feasible at all (it likely is not, absent an existing model) and what it would cost to build (S2).

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Contracts: none new; the clustering-run aggregate count addition is an internal structured-log/event schema, not a cross-service contract — no `docs/workbay/contracts/` entry exists for it today and none is added (informational-only).
- Prior plans (read, do not restate): `docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md` v6.2 (Slices 0a/0/1 unconditional, 2/3/4 CONDITIONAL on `TRAINING_DECISION`/D-01), `docs/tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md` (S4 — quoted below), `docs/tasks/fir/FIR-15-attribution-split-and-oracle-ladder-task-plan.md` (D-02 decision this task branches on; `masked_cosine` and `sface-support-map-v1.json` this task imports/loads — confirm FIR-15's `masked_similarity.py` has landed before starting S1/L2; if it has not, L2 defines it there per the Constraints section's shared-module note, and records that as a deviation in the slice-complete decision).
- Handoff/MCP: FIR-15's `firplan_d02_attribution_<date>` decision (read before L1's D-02-gated commits — not required before S0); this task's own slice-complete decisions per lane.
- Heuristics: EMB-01/11/12, CAL-01/04, EVAL-19, AUDIT-04 — https://github.com/darce/heuristics-canon.

**FIR-6 S4 (cited verbatim, the OACT value hand-off target)**:

> Run the FIR-5 harness on the real corpus; run S3a's CLI; select thresholds per the pre-registered rule; record the calibration decision + artifacts in MCP. Apply step: one code commit writing calibrated values into the face_pipeline-scoped knobs (table above) + the `oact_coefficient` + factor floors, citing the MCP decision id — shared insightface settings untouched.

S0 fixes the sign `oact_coefficient` is applied with; FIR-6 S4's apply step remains the sole place a nonzero, calibrated value is written. This task never sets `oact_coefficient` away from its `0.0` default.

## Contract and Boundary Impact

None. All changes are internal to `apps/prototype-description-service/recognition/` (plus the greenfield schema edit in `db/models/identity.py` / `db/migrations/versions/001_identity_schema.py` for the new persisted `region_visibility` column, S1); the clustering-run aggregate count addition is an internal structured-log field, not a versioned cross-service contract.

## Proposed Solution

Four numbered slices (S0-S4, S3 folded into S0's commit): S0 fixes the OACT sign unconditionally. S1 computes per-region visibility at detection time, persists it alongside the existing `occlusion_severity` quality factor (mirroring that precedent), threads it through `AssignmentCandidate`, and builds the actual masked-cosine matching path in `CentroidDiscovery._find_best_centroid_match` using the versioned support-map asset. S2 (pose rescue) is an out-of-lane spike, not a lane, because it produces an ADR, not code. S4 confirms the shared `masked_cosine` definition, wires the eval harness through it, and fixes the event-tag emission site to the clustering-discovery layer where assignment data actually lives.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| OACT sign fix | `apps/prototype-description-service/recognition/application/assignment/quality.py` | flip `oact_term` from `-(coeff * severity)` to `+(coeff * severity)` in `compute_quality_adjustment` (line ~136) |
| quality factors | `apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py` | add `estimate_region_visibility(crop: np.ndarray, landmarks: np.ndarray \| None) -> RegionVisibility`; thread it through `compute_face_quality_factors` (139-158) |
| domain/schema | `apps/prototype-description-service/recognition/domain/identity.py`, `apps/prototype-description-service/db/models/identity.py`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | add nullable `region_visibility` (5-float array, NULL under `insightface`) mirroring the existing `occlusion_severity` quality-factor pattern; greenfield edit directly in `001_identity_schema.py` per the repo's no-migration-chain policy — no incremental Alembic revision |
| detection/persistence | `apps/prototype-description-service/recognition/application/embedding/detector.py` (`_compute_detection_quality`), `apps/prototype-description-service/recognition/application/scan/service.py` (`_persist_identities`, line ~529) | thread `region_visibility` from `compute_face_quality_factors` onto the domain identity and the persisted row, same call sites that already thread `occlusion_severity` |
| settings | `apps/prototype-description-service/recognition/config/settings.py` | add `visible_support_matching: bool` knob mirroring `oact_coefficient`'s `default_factory` pattern (265-267, 377-384); extend `ResolvedFacePipelineKnobs` (522-546) and `resolve_face_pipeline_knobs` (549-599). **`pose_head_rescue`/`RECOGNITION_FACE_POSE_HEAD_RESCUE` are NOT added** — S2 is ADR-only (may propose the knob name as a future follow-up, never implements it here) |
| shared math | `apps/prototype-description-service/recognition/infrastructure/embeddings/masked_similarity.py` | shared `masked_cosine(a, b, mask) -> float` pure function (settings-independent); defined by FIR-15 if it has landed first, otherwise defined here (see Context Loading) |
| support-map asset + loader | `apps/prototype-description-service/recognition/infrastructure/face_pipeline/assets/sface-support-map-v1.json` (new), `apps/prototype-description-service/recognition/infrastructure/face_pipeline/support_map.py` (new) | versioned support-map asset from FIR-15 S2's recipe; `load_support_map(path: Path, *, expected_sha256: str) -> SupportMap` loader validated against the existing model-manifest sha256 scheme (`provenance.py`'s `MODEL_MANIFEST`/`load_verified_model`, 71-182) |
| matching | `apps/prototype-description-service/recognition/application/discovery/centroid.py` | `CentroidDiscovery.discover` (30-60) copies `identity.region_visibility` onto the `AssignmentCandidate` it constructs; `_find_best_centroid_match` (62-87) builds a per-identity dimension mask from the loaded `SupportMap` + the candidate's `region_visibility` (never from a static mask alone) and calls `masked_cosine` when `visible_support_matching` is enabled and a mask is available |
| candidate transport | `apps/prototype-description-service/recognition/application/assignment/candidate.py` | add `region_visibility: tuple[float, float, float, float, float] \| None = None` to `AssignmentCandidate` (25-33); add `visible_support_applied: bool = False` metadata field |
| event/metric | `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py` | extend `run_discovery_pipeline`'s existing `CentroidDiscovery` stage `logger.info` line (~500-505) with a structured `extra=` payload carrying `visible_support_applied_count` aggregated over `centroid_candidates` |
| eval hooks | `apps/prototype-description-service/scripts/eval_harness/` | thin adapter routing harness similarity calls through `masked_similarity.masked_cosine` when `visible_support_matching` is enabled (L3) |
| tests | see per-slice Proof sections below | cover OACT sign, region visibility, support-map loader, masked cosine, event aggregation |
| ADR | `docs/adrs/ADR-016-pose-head-rescue-feasibility-spike.md` (confirm next free number at implementation time — `docs/adrs/` currently ends at `ADR-015`) | S2 pose-head-rescue feasibility spike |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py` | `ConfidenceCheck.evaluate` (91-242) — consumes `discovery_similarity`, unchanged by this task |
| `apps/prototype-description-service/recognition/application/discovery/centroid.py` | `CentroidDiscovery.discover` (30-60), `_find_best_centroid_match` (62-87) — masked-cosine interception point |
| `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py` | `run_discovery_pipeline` (476-527) — actual per-chunk clustering orchestrator; correct home for the aggregate event metric |
| `apps/prototype-description-service/recognition/infrastructure/face_pipeline/provenance.py` | `MODEL_MANIFEST` (71-100), `load_verified_model` (120-182), `_file_sha256` (109-117) — existing sha256 manifest scheme the support-map loader reuses |
| `apps/prototype-description-service/scripts/eval_harness/synthetic_occlusion.py` | `anatomy_region_stats` (762-784) — visibility-scoring input shared with FIR-15 |
| `apps/prototype-description-service/recognition/tests/unit/test_centroid_discovery.py` | existing `CentroidDiscovery.discover` unit tests; extend rather than fork |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_face_quality_factors.py recognition/tests/unit/test_identity_quality.py -q` (S0)
  - `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_face_quality_factors.py recognition/tests/unit/test_settings_face_pipeline_knobs.py -q` (S1 — L1 half)
  - `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_support_map.py recognition/tests/unit/test_masked_similarity.py recognition/tests/unit/test_centroid_discovery.py -q` (S1 — L2 half)
  - `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_discovery_pipeline_visible_support.py -q` (S4 — event-tag fix)
  - `cd apps/prototype-description-service && python3 -m pytest scene/tests/test_eval_harness_fir17_hooks.py -q` (S4 — eval hooks)
- Runtime-parity / environment checks: none beyond existing dark-launch parity tests (`TestOactDarkScaffold`), since every new knob defaults off.
- Contract/fixture verification: none — no external contract file to update (see Contract and Boundary Impact).
- Manual verification: operator reviews the S2 ADR before any pose-rescue implementation work is considered (out of this task's scope regardless).

## Slice Delivery

### Slice 0: OACT sign fix (unconditional, runs before D-02)

Implements: FIRG-054 (unconditional; runs before D-02 in every branch).
**Goal**: Correct `compute_quality_adjustment`'s OACT term based on the calibration/runtime sign contradiction, not on the docstring's return-value convention. Its `Returns:` text ("positive = stricter") defines the sign of the returned adjustment; it does not require a positive OACT term, and its Design notes deliberately give COLD clusters a "0.25x band adjustment but full OACT leniency," attributed to FIR-6 S1 / FIR6S1-M-09. The load-bearing evidence is `scripts/eval_harness/calibrate_face_thresholds.py::calibrate`'s OACT block (~965–1020), which computes `elevated = base_tau + oact_coefficient` and `tax = fnmr_at(g_scores, elevated) - fnmr_at(g_scores, base_tau)`, documenting the tax as the FNMR impact of elevating tau by the coefficient (uniform additive proxy). FIR-6 S4 selects the coefficient with that harness, while runtime currently spends it as loosening; a nonzero calibrated value is therefore applied backwards. This S0 change supersedes FIR-6 S1's leniency intent as a ratified policy reversal, not a typo correction; FIR-6 S1 / FIR6S1-M-09 must be recorded as superseded.

Changes:

- `apps/prototype-description-service/recognition/application/assignment/quality.py::compute_quality_adjustment` (80-138): change line ~136 from `oact_term = -(coeff * severity)` to `oact_term = +(coeff * severity)`. No other line in the function changes; maturity dampening of the base band is untouched.
- Add a one-line code comment at the `oact_coefficient` field declaration (`settings.py:377-384`, S3's deliverable, folded into this commit): "sign convention corrected by FIR-17 S0; calibrated nonzero value is set only by FIR-6 S4's apply step, never by this field's default."

Proof:

- `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_face_quality_factors.py -q` — update the existing leniency assertions in `TestOactDarkScaffold` to the tightening direction: `test_nonzero_coefficient_moves_adjustment` (141-153) currently asserts `assert on == pytest.approx(off - 0.1)` and `assert on < off`; change to `assert on == pytest.approx(off + 0.1)` and `assert on > off`. `test_oact_moves_gate_time_threshold_adjustment` (156-207) currently asserts `assert on.metadata["quality_adj"] < off.metadata["quality_adj"]` and `assert on.metadata["final_threshold"] < off.metadata["final_threshold"]` (~206-207); change both to `>`.
- `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_identity_quality.py -q` — `TestComputeQualityAdjustment` (113-134) exercises `compute_quality_adjustment` directly; add/adjust any case that passes a nonzero `occlusion_severity` to assert the tightening direction.

### Slice 1: Region visibility, support-map matching, and settings knob (runs under `EMBEDDER`/`BOTH`)

Implements: FIRG-050, FIRG-051, FIRG-052 (reuses FIRG-044's `masked_cosine` from FIR-15 S2).
**Goal**: Produce a per-region visibility signal at detection time, persist and transport it to the discovery path, load a versioned support-map asset, and apply masked cosine in the real matching call site — all behaviour-neutral at the `visible_support_matching` knob's default (`False`).

Changes:

- `apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py`: add

  ```python
  def estimate_region_visibility(
      crop: np.ndarray,
      landmarks: np.ndarray | None,
  ) -> RegionVisibility:
      """Per-region visibility in [0,1] for the 5 SFace landmark regions:
      right_eye, left_eye, nose, mouth_right, mouth_left (REGION_NAMES order) — a texture proxy,
      never an oracle occlusion mask. Extends compute_occlusion_severity's
      (82-105) canonical-eye-patch approach; when landmarks is None, falls
      back to the same canonical eye positions for the two eye regions and
      returns visibility=1.0 (no-op) for nose/mouth_left/mouth_right, since
      no canonical positions exist for those regions without landmarks."""
  ```

  and thread it through `compute_face_quality_factors` (139-158) alongside the existing `landmarks`-gated `compute_pose_proxies` call, adding a `region_visibility: RegionVisibility` field to `FaceQualityFactors`.
- `apps/prototype-description-service/recognition/domain/identity.py` (14-57) and `apps/prototype-description-service/db/models/identity.py` (41-105): add `region_visibility: tuple[float, float, float, float, float] | None = None` (domain) and a matching nullable 5-element float array column (ORM), mirroring the existing `occlusion_severity` quality-factor precedent (NULL under `insightface`, populated under `face_pipeline`).
- `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`: add the new column directly in this file (greenfield policy — no incremental Alembic revision).
- `apps/prototype-description-service/recognition/application/embedding/detector.py::_compute_detection_quality` (93-127) and `apps/prototype-description-service/recognition/application/scan/service.py::_persist_identities` (409-550, write site ~529): thread `region_visibility` from `compute_face_quality_factors` onto the domain identity and the persisted row, same call sites that already thread `occlusion_severity`.
- `apps/prototype-description-service/recognition/config/settings.py`: add one module-level resolver mirroring `_resolve_face_oact_coefficient` (265-267) / `_resolve_face_joint_assignment_enabled` (282-283):

  ```python
  def _resolve_face_visible_support_matching() -> bool:
      return _env_or_default_bool("RECOGNITION_FACE_VISIBLE_SUPPORT_MATCHING", default=False)
  ```

  and one new `FacePipelineSettings` field mirroring `oact_coefficient`'s `Field(default_factory=...)` pattern (377-384):

  ```python
  visible_support_matching: bool = Field(default_factory=_resolve_face_visible_support_matching)
  ```

  Default `False` — dark-launched, no-op until an operator sets the env var. Extend `ResolvedFacePipelineKnobs` (522-546) with the new field, and extend `resolve_face_pipeline_knobs` (549-599) to force it `False` under the `insightface` profile branch (mirroring how the function already force-disables face_pipeline-only knobs under that profile). **Do not add `pose_head_rescue`/`RECOGNITION_FACE_POSE_HEAD_RESCUE`** — S2 is ADR-only.
- `apps/prototype-description-service/recognition/infrastructure/face_pipeline/assets/sface-support-map-v1.json` (new): versioned support-map asset shipped from FIR-15 S2's recipe, registered in the existing `MODEL_MANIFEST` sha256 scheme (`provenance.py:71-100`).
- `apps/prototype-description-service/recognition/infrastructure/face_pipeline/support_map.py` (new): `load_support_map(path: Path, *, expected_sha256: str) -> SupportMap`. Validates: region names are exactly the five regions in `REGION_NAMES` order (`right_eye`, `left_eye`, `nose`, `mouth_right`, `mouth_left`, FIR-15 / DD-15); 128-D index bounds (SFace embedding dimension); no duplicate dims across regions. Fail-closed (raise, do not silently degrade) on sha256 mismatch or any malformed/out-of-range/duplicate entry, reusing the sha256 comparison already implemented by `provenance.py::_file_sha256`/`load_verified_model` (109-182).
- `apps/prototype-description-service/recognition/application/assignment/candidate.py::AssignmentCandidate` (25-33): add `region_visibility: tuple[float, float, float, float, float] | None = None` and `visible_support_applied: bool = False`.
- `apps/prototype-description-service/recognition/application/discovery/centroid.py`: `CentroidDiscovery.discover` (30-60) copies `identity.region_visibility` onto each constructed `AssignmentCandidate`. `_find_best_centroid_match` (62-87) — when `settings.visible_support_matching` is `True` and both a loaded `SupportMap` and a non-`None` `region_visibility` are available — builds a per-identity boolean dimension mask (a dim is included if its owning region's visibility is above threshold, or if `region_visibility` is `None` the mask is all-ones, i.e. a no-op) and calls `masked_similarity.masked_cosine(face_vector, centroid_vec, mask)` instead of the current unmasked `np.dot`; sets `visible_support_applied=True` on the resulting candidate only when the mask actually excluded at least one dimension. The mask is built fresh per identity from `SupportMap` + `region_visibility` together — never from a static support mask alone.

Proof:

- `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_face_quality_factors.py -q` — new cases for `estimate_region_visibility`: all-visible crop, one-region-occluded crop, `landmarks=None` fallback (asserts eyes computed, nose/mouth default to `1.0`).
- New `apps/prototype-description-service/recognition/tests/unit/test_settings_face_pipeline_knobs.py`: asserts `visible_support_matching` defaults `False`, is settable via its env var, and is force-disabled under the `insightface` profile in `resolve_face_pipeline_knobs`; asserts `pose_head_rescue` is NOT present on `FacePipelineSettings`/`ResolvedFacePipelineKnobs`.
- New `apps/prototype-description-service/recognition/tests/unit/test_support_map.py`: `test_rejects_bad_sha256`, `test_rejects_out_of_range_dim`, `test_rejects_unknown_region` (all fail-closed, per DD-13).
- New `apps/prototype-description-service/recognition/tests/unit/test_masked_similarity.py::test_single_definition_no_settings_import`: this test's real assertion in S1 is scoped to `masked_similarity.py`'s own top-level imports (no `recognition.config.settings` symbol). The transitive check (walking every module `masked_similarity.py` imports, including function-body/late-bound imports) is deferred to, and required by, S4 below — see S4's Proof section.
- Extend `apps/prototype-description-service/recognition/tests/unit/test_centroid_discovery.py`: assert `_find_best_centroid_match` returns the unmasked result when `visible_support_matching=False` or `region_visibility=None` (no-op parity with the pre-existing behavior), and returns a masked result with `visible_support_applied=True` when both are present and at least one region is below the visibility threshold.

### Slice 2: Pose-head-rescue feasibility spike (ADR only, no implementation, runs under `INCONCLUSIVE`)

Implements: FIRG-053 (ADR-only; no runtime code).
**Goal**: Determine whether a pose-head-rescue intervention is buildable at all, since no keypoint/pose/person model exists in the service today (verified negative via `search_graph`/`search_code` sweep for `keypoint|pose|yolo|person`).

Changes:

- New ADR at `docs/adrs/ADR-016-pose-head-rescue-feasibility-spike.md` (confirm the next free number via `ls docs/adrs/` at implementation time — `docs/adrs/` currently runs `ADR-001`..`ADR-015` plus `ADR-ARCH-07`), recording: (1) the verified-negative finding (no model exists), (2) the two build options this implies — vendor a lightweight head-pose model (new dependency, new inference cost) vs. approximate pose from the existing 5-point landmark geometry alone (cheap, likely low-fidelity), (3) a recommendation gated on FIR-15's D-02 verdict: only worth prototyping under an `INCONCLUSIVE` re-run with fresh evidence, or as a named follow-up task if a later `DETECTOR`/`BOTH` verdict ships without one. May name `RECOGNITION_FACE_POSE_HEAD_RESCUE` as a *proposed* future knob — this task never implements it.
- No code changes. This slice's only proof artifact is the ADR document itself.

Proof:

- ADR exists at the recorded path and states a clear recommendation; reviewed by the operator (manual verification — no automated test, since no code ships).

### Slice 3: OACT coefficient value hand-off boundary (documentation-only, folded into S0's commit)

Supports: FIRG-054 (documents the coefficient hand-off to FIR-6 S4; no new gate ids).
**Goal**: Make explicit, in code comments and in this plan, that this task never sets a nonzero `oact_coefficient` — FIR-6 S4 owns that.

Changes:

- The comment itself is added in S0's commit (see S0 above) at the `oact_coefficient` field declaration (`settings.py:377-384`). This slice exists as a separate row in the Branch Rule table only because `DETECTOR`/`INCONCLUSIVE` branches run S0 without S1 — the comment still ships in those branches since it lives in S0's commit, not S1's.
- No new tests beyond S0's.

Proof:

- Comment present at the field declaration; reviewed alongside S0.

### Slice 4: Confirm shared masked-cosine definition, fix the event-tag emission site, wire eval-harness runs

Implements: FIRG-055.
**Goal**: Confirm `masked_cosine` has exactly one definition (settings-independent) reused by both runtime and eval harness; move the `visible_support_applied` aggregate metric to the layer where assignment data actually exists; let FIR-15's ladder/attribution harness exercise the new production knob end-to-end.

Changes:

- `apps/prototype-description-service/recognition/infrastructure/embeddings/masked_similarity.py`: confirm (or, if FIR-15 has not landed it yet, define) exactly one `masked_cosine(a, b, mask) -> float`, with no import of any settings module, direct or transitive. In particular, `masked_similarity.py` must implement its own minimal L2-normalize/dot-product helpers rather than importing `recognition/shared/similarity.py`'s `normalize_vector`/`extract_face_embedding` — that module's `face_embedding_dim()` late-binds `recognition.config.settings` via a function-body import (`from recognition.config.settings import resolve_effective_detection_settings`, not a module-level import), so reusing its helpers would silently reintroduce a settings dependency invisible to a top-of-file import scan.
- `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py::run_discovery_pipeline` (476-527): extend the existing `CentroidDiscovery` stage `logger.info` call (~500-505, currently a plain `"[clustering] CentroidDiscovery: %d candidates, %d remaining"` message with no `extra=`) to also emit a structured `extra={"visible_support_applied_count": sum(1 for c in centroid_candidates if c.visible_support_applied), ...}` payload. This replaces the earlier draft's incorrect proposal to tag `_emit_scan_media_reconciled` (`service.py:583-641`), which has no access to `AssignmentCandidate` data (see Current State Analysis).
- `apps/prototype-description-service/scripts/eval_harness/`: add a thin adapter that, when `visible_support_matching` is enabled via env var, routes the harness's similarity calls through `masked_similarity.masked_cosine` (the same function S1's runtime change imports) instead of any eval-only copy.

Proof:

- `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_masked_similarity.py -q` — extend `test_single_definition_no_settings_import` in this slice to a transitive check: recursively walk `masked_similarity.py`'s imports (module-level AST `Import`/`ImportFrom` nodes, resolved recursively into each imported first-party module's own AST — not merely `sys.modules` after a normal import, since a late-bound/function-body import like `recognition/shared/similarity.py::face_embedding_dim`'s `from recognition.config.settings import ...` only appears in `sys.modules` after that function actually executes, and would falsely pass a naive "was `recognition.config.settings` imported" check run before any call) and assert `recognition.config.settings` (or any submodule of it) never appears in that closure. This is the confirmation gate that S1's shallower host-file-only check was insufficient on its own.
- New `apps/prototype-description-service/recognition/tests/unit/test_discovery_pipeline_visible_support.py`: asserts `run_discovery_pipeline`'s log call carries `visible_support_applied_count` equal to the number of `centroid_candidates` with `visible_support_applied=True`, and is `0` when the knob is disabled (no candidate ever has the flag set).
- New `apps/prototype-description-service/scene/tests/test_eval_harness_fir17_hooks.py`: asserts the harness adapter calls `masked_similarity.masked_cosine` (not a local eval-only copy) when the knob is enabled, and falls back to unmasked cosine when disabled.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `fir17-l1-oact-and-visibility` | `apps/prototype-description-service/recognition/application/assignment/quality.py`, `apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py`, `apps/prototype-description-service/recognition/domain/identity.py`, `apps/prototype-description-service/db/models/identity.py`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`, `apps/prototype-description-service/recognition/application/embedding/detector.py`, `apps/prototype-description-service/recognition/application/scan/service.py` (`_persist_identities` only, not `_emit_scan_media_reconciled`), `apps/prototype-description-service/recognition/config/settings.py`, `apps/prototype-description-service/recognition/tests/unit/test_face_quality_factors.py`, `apps/prototype-description-service/recognition/tests/unit/test_identity_quality.py`, `apps/prototype-description-service/recognition/tests/unit/test_settings_face_pipeline_knobs.py` | FIR-15 D-02 decision recorded (S1 only; S0 has no upstream) | `python3 -m pytest recognition/tests/unit/test_face_quality_factors.py recognition/tests/unit/test_identity_quality.py recognition/tests/unit/test_settings_face_pipeline_knobs.py -q` |
| `fir17-l2-support-map-matching` | `apps/prototype-description-service/recognition/infrastructure/embeddings/masked_similarity.py`, `apps/prototype-description-service/recognition/infrastructure/face_pipeline/support_map.py`, `apps/prototype-description-service/recognition/infrastructure/face_pipeline/assets/sface-support-map-v1.json`, `apps/prototype-description-service/recognition/application/discovery/centroid.py`, `apps/prototype-description-service/recognition/application/assignment/candidate.py`, `apps/prototype-description-service/recognition/tests/unit/test_support_map.py`, `apps/prototype-description-service/recognition/tests/unit/test_masked_similarity.py`, `apps/prototype-description-service/recognition/tests/unit/test_centroid_discovery.py` | `fir17-l1-oact-and-visibility` | `python3 -m pytest recognition/tests/unit/test_support_map.py recognition/tests/unit/test_masked_similarity.py recognition/tests/unit/test_centroid_discovery.py -q` |
| `fir17-l3-event-and-eval-hooks` | `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py`, `apps/prototype-description-service/scripts/eval_harness/` (adapter file only), `apps/prototype-description-service/recognition/tests/unit/test_discovery_pipeline_visible_support.py`, `apps/prototype-description-service/scene/tests/test_eval_harness_fir17_hooks.py` | `fir17-l2-support-map-matching` | `python3 -m pytest recognition/tests/unit/test_discovery_pipeline_visible_support.py -q && python3 -m pytest scene/tests/test_eval_harness_fir17_hooks.py -q` |

S2 (pose-head-rescue spike) is intentionally not a lane — it produces an ADR, not code, and has no `owned_paths`/`test_cmd` shape to lane.

### Merge Order

`fir17-l1-oact-and-visibility` → `fir17-l2-support-map-matching` → `fir17-l3-event-and-eval-hooks` → `feature/fir-17` → `main`.

### Manifest

```bash
make lane-manifest-init TASK=fir-17 LANE_IDS='fir17-l1-oact-and-visibility fir17-l2-support-map-matching fir17-l3-event-and-eval-hooks' TASK_PLAN=docs/tasks/fir/FIR-17-inference-only-occlusion-robustness-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: sequential dispatch per the depends_on chain via `dispatch_lane_work`.
- **Shell fallback**: direct implementation in `feature/fir-17` worktree, lane order enforced manually.

---

## Consolidated Checklist

> **Checklist scope rule:** describes work being delivered, not finding status. Finding status is queried from the handoff DB.

## Context and Ownership

- [ ] S0 (OACT sign fix) landed before, or independent of, FIR-15's `firplan_d02_attribution_<date>` decision.
- [ ] Read FIR-15's `firplan_d02_attribution_<date>` decision and recorded which branch-rule row applies before starting S1/S2.
- [ ] Confirmed FIR-7 Slices 2-4 remain untouched and `TRAINING_DECISION` state is not read or written by this task.
- [ ] Confirmed no external contract is touched (the aggregate-metric addition is internal).

### Checklist for Slice 0: OACT sign fix

- [ ] `compute_quality_adjustment`'s `oact_term` corrected to `+(coeff * severity)`.
- [ ] `TestOactDarkScaffold`'s leniency assertions (`test_nonzero_coefficient_moves_adjustment`, `test_oact_moves_gate_time_threshold_adjustment`) updated to the tightening direction; the default-`0.0` no-op case still passes unchanged.
- [ ] `test_identity_quality.py::TestComputeQualityAdjustment` reviewed/updated for the sign flip.
- [ ] Hand-off comment (S3) added at the `oact_coefficient` field declaration.

### Checklist for Slice 1: Region visibility, support-map matching, and settings knob

- [ ] `estimate_region_visibility` implemented for all 5 SFace landmark regions with a documented `landmarks=None` fallback.
- [ ] `region_visibility` persisted on `MediaIdentity` (domain + ORM + `001_identity_schema.py`) mirroring the `occlusion_severity` precedent.
- [ ] `visible_support_matching` knob added mirroring `oact_coefficient`'s `default_factory` pattern, defaulting `False`; `pose_head_rescue` NOT added.
- [ ] `ResolvedFacePipelineKnobs` and `resolve_face_pipeline_knobs` extended; the new knob force-disabled under the `insightface` profile.
- [ ] Support-map asset + `load_support_map` loader implemented, fail-closed on bad sha256/out-of-range dim/unknown region, verified against the existing model-manifest sha256 scheme.
- [ ] `AssignmentCandidate.region_visibility`/`visible_support_applied` added; `CentroidDiscovery.discover`/`_find_best_centroid_match` wired to build the mask and call `masked_cosine`.

### Checklist for Slice 2: Pose-head-rescue feasibility spike

- [ ] ADR recorded at `docs/adrs/ADR-0NN-pose-head-rescue-feasibility-spike.md` (number confirmed at implementation time) documenting the verified-negative model search and a D-02-gated recommendation.
- [ ] No production code shipped in this slice.

### Checklist for Slice 3: OACT coefficient value hand-off boundary

- [ ] Comment added at `oact_coefficient`'s field declaration citing FIR-6 S4 as the sole place a nonzero calibrated value is set (delivered as part of S0's commit).

### Checklist for Slice 4: Shared masked-cosine confirmation, event-tag fix, eval-harness wiring

- [ ] Confirmed exactly one `masked_cosine` definition, settings-independent (verified transitively, not just at its own top-level imports), imported by both runtime and eval harness.
- [ ] `run_discovery_pipeline`'s `CentroidDiscovery` stage log line carries `visible_support_applied_count`; `_emit_scan_media_reconciled` is left untouched (wrong layer — no assignment data available there).
- [ ] Eval-harness adapter routes through `masked_similarity.masked_cosine` when `visible_support_matching` is enabled, and falls back to unmasked cosine otherwise.
- [ ] `test_discovery_pipeline_visible_support.py` and `test_eval_harness_fir17_hooks.py` cover both enabled/disabled branches.

## Review Readiness

- [ ] Masked-cosine logic exists in exactly one shared pure function (`masked_similarity.py`), imported by both runtime (`centroid.py`) and eval harness — no forked copy.
- [ ] Every new knob verified dark-launched (default off) with a runtime-parity test proving merge-time behavioral neutrality.
- [ ] `visible_support_applied_count` is emitted from the clustering-discovery layer, not scan reconcile.
- [ ] Handoff decision records which branch-rule row applied, which slices ran, and cites the FIR-15 D-02 decision id (S0's landing decision may cite "pre-D-02" instead).

## Stretch Goals

- [ ] If S2's ADR recommends prototyping landmark-geometry-only pose approximation, scope that as a follow-on task (not part of this task).

## Success Criteria

- [ ] OACT sign fix (S0) ships and is behaviour-neutral at `oact_coefficient=0.0` (proven by the unchanged default-case test); every verdict runs S0.
- [ ] Under `EMBEDDER`/`BOTH` verdicts, `visible_support_matching` knob exists, defaults off, and when enabled routes real matching through the shared masked-cosine function with `visible_support_applied`/`visible_support_applied_count` tagged at the clustering-discovery layer.
- [ ] Under `INCONCLUSIVE`, the pose-head-rescue ADR is recorded with a clear build/no-build recommendation.
- [ ] Eval harness can exercise the shipped knob through the same code path production uses.
- [ ] `handoff_close_check(enforce=True)` passes; task `done` + archived.
