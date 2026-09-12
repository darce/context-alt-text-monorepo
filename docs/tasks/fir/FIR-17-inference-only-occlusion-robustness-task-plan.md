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

FIR-15's D-02 decision (`firplan_d02_attribution_<date>`) names the leg identity error concentrates in. This task's slices run per that verdict:

| D-02 `verdict` | Slices that run | Rationale |
| --- | --- | --- |
| `EMBEDDER` | S1, S3 | Matching approach (visible-support masking) targets the embedder-side error; pose rescue (S2) has no evidence behind it. |
| `DETECTOR` | S2 (spike only — see S2), S3 | Alignment-side error implicates the detector/landmark path; S1's masking gives no ceiling headroom (oracle gap CI must be checked). |
| `BOTH` | S1, S2 (spike only), S3 | Both legs contribute measurably. |
| `INCONCLUSIVE` (oracle-gap CI from FIR-15 S2 includes 0, or the attribution shares' CIs both include 0) | S3 only | No masking or pose intervention has evidence of headroom; only the OACT sign fix ships. Record the exit explicitly in the handoff decision — this is not a failure, it is FIR-15 doing its job. |

S3 (OACT sign fix + settings knobs) runs under every verdict because it is a bug fix independent of the attribution outcome — see S3 below for why it is behaviour-neutral regardless of branch.

**Dependency**: this task cannot start implementation until FIR-15's D-02 decision is recorded in MCP. Lane `L1` reads the decision's `verdict` field before its first commit.

## Objective

Ship inference-only occlusion robustness gated by FIR-15's attribution verdict: masked (visible-support) cosine matching where the embedder leg has evidence, a pose-head-rescue spike where the detector leg has evidence, and an OACT (occlusion-adaptive confidence threshold) sign fix that ships regardless of verdict. No training; PEFT/adapter work stays out of scope and stays frozen behind FIR-7's existing D-01 gate.

## Problem Statement

FIR-7 v6.2 froze its PEFT-adapter slices (2, 3, 4) behind `TRAINING_DECISION`/D-01, reached only via QA v8's T-09→T-14 re-gate — that gate has not fired. Meanwhile `compute_occlusion_severity`'s two-eye-patch proxy (`face_quality_factors.py:82-105`) already runs in production computing an occlusion quality factor, but nothing in the matching path uses occlusion-region information to mask the embedding comparison, and the OACT coefficient's sign has not been checked against the direction its penalty is supposed to apply. This task ships the $0, inference-only interventions that do not require the frozen training track, and closes the OACT sign bug independent of whether masking or pose-rescue end up justified.

**Which FIR-7 slices stay frozen, and why**: FIR-7 v6.2 Slices 0a, 0, and 1 are unconditional and already shipped/shippable (data prep, baseline harness, non-training scaffolding). Slices 2, 3, and 4 are the PEFT adapter training slices and are explicitly CONDITIONAL on `TRAINING_DECISION` — gated behind QA v8's D-01 decision, which is reached only via the T-09 (face-label rule) → T-14 (union adjudication dead-zone kill rule) re-gate sequence. That re-gate has not fired as of this task's drafting. FIR-17 does not touch, unblock, or duplicate FIR-7 Slices 2-4; it is scoped entirely to inference-time interventions that need no adapter weights and no GPU training spend (A10 GPU spend stays unauthorized for this task).

## Constraints

- **No training.** Zero GPU spend, zero adapter weights touched. This task is a pure inference-path change: masking dimensions, computing a rescue pose feature, flipping a coefficient's sign application, threading a new event tag.
- **FIR-7 Slices 2-4 stay frozen.** See Problem Statement. This task must not read from or write to any FIR-7 adapter checkpoint path, and must not alter `TRAINING_DECISION` state.
- **Dark-launch/no-op-default discipline.** Every new knob defaults to the behavior-neutral value (disabled/0.0) so merging this task changes nothing in production until an operator flips a knob, mirroring `oact_coefficient`'s existing `default_factory` pattern (settings.py 265-267, 377-384).
- **OACT sign fix is behaviour-neutral at the default coefficient value.** `oact_coefficient` defaults to `0.0` (`_resolve_face_oact_coefficient`, settings.py 265-267, `_env_or_default_nonneg`). Any formula in which the coefficient is a multiplicative or additive term collapses to the same output at `0.0` regardless of the sign convention applied to it — `0.0 * severity == -0.0 * severity == 0.0`, `x + 0.0 == x - 0.0 == x`. The sign fix therefore changes behavior only once an operator sets `oact_coefficient` to a nonzero value at rollout (a separate, explicit act) — it is a latent-bug fix, not a behavior change, at merge time.
- **Masked-cosine and the FIR-15 eval-only version must converge on one shared pure function.** FIR-15 defined `occlusion_ladder.masked_cosine` as an eval-only diagnostic. This task's S1 must not fork that logic — it moves the dimension-masking math into a shared pure module both the eval harness and the runtime import, so the two never drift (see S1's shared-module note).
- **No pgvector re-rank needed.** Verified: the cosine similarity `ConfidenceCheck.evaluate` consumes (`confidence.py:91-242`, reading `candidate.discovery_similarity`) is NOT the result of a database `<=>` query. It is computed entirely in-process via numpy dot products against in-memory centroids in `CentroidDiscovery._find_best_centroid_match` (`centroid.py:62-87`), invoked from `CentroidDiscovery.discover` (`centroid.py:30-60`), which wraps `centroid_utils.compute_similarity` (`centroid_utils.py:51-66`, itself wrapping `compute_face_similarity` and clamping to `[0,1]`). This is a confirmed deviation from the program packet's speculative framing ("if the similarity comes from the pgvector `<=>` query, masked cosine must be applied as a re-rank over the top-K candidates after the DB query") — no DB re-rank stage exists or is needed; the interception point is the in-process similarity computation itself. See S1 below.
- **No pose/keypoint/person model exists anywhere in the service** (verified: `search_graph`/`search_code` sweep for `keypoint|pose|yolo|person` across the runtime found no model — all "pose"-adjacent hits are landmark-derived proxy metrics such as `compute_occlusion_severity`'s eye-patch heuristic, or test-only fakes). S2 ("pose head rescue") is therefore an ADR/spike deliverable, not an implementation slice — see S2.

## Workflow Principles

- Ship the cheap, reversible fix first: the OACT sign fix (S3) runs regardless of the D-02 verdict because it costs nothing and is behaviour-neutral at default.
- No shared logic forks between eval and runtime [dedupe pressure applies to correctness-critical math, not just style] — `masked_cosine` lives once, imported twice.
- Dark-launch every new knob; a merge must never itself change production behavior [PRINCIPLE #15 counterpart: measure before shipping non-neutral defaults].
- A spike that finds "no model exists" is a valid, complete deliverable — it is not deferred work.

## Terminology

- **OACT**: occlusion-adaptive confidence threshold — an existing scaffold (`oact_coefficient`, `TestOactDarkScaffold`) that adjusts the confidence threshold by a coefficient scaled against an occlusion severity signal.
- **Visible-support matching / masked cosine**: cosine similarity computed only over embedding dimensions attributed to unoccluded landmark regions (support mask), per the recipe FIR-15 S2 defines and versions as `sface-support-map-v1.json`.
- **Pose head rescue**: a hypothetical fallback that would use head-pose estimation to recover matchable regions under occlusion — **no model for this exists in the service today** (verified negative); this task's S2 is scoped to determine feasibility, not to ship one.
- **`visible_support_applied`**: new boolean event-tag key on the scan-media-reconciled event, `True` when the masked-cosine path was used for a given match.
- **Branch rule**: the table at the top of this document, keyed to FIR-15's D-02 `verdict`.

## Current State Analysis

- **Works**: `ConfidenceCheck.evaluate` (`confidence.py:91-242`) consumes `discovery_similarity`; `CentroidDiscovery` (`centroid.py`) computes it in-process; `compute_occlusion_severity` (`face_quality_factors.py:82-105`) already produces an occlusion signal; `oact_coefficient` scaffold (`settings.py:377-384`, `TestOactDarkScaffold`) already exists dark-launched at `0.0`; `resolve_face_pipeline_knobs` (`settings.py:549-599`) already profile-gates knobs between `insightface` and `face_pipeline` profiles; `_emit_scan_media_reconciled` (`service.py:583-641`) already emits a structured event-tag payload.
- **Broken/missing**: no masked-cosine path exists anywhere in the matching code; no support-map asset exists (FIR-15 S2 produces the first version, this task ships it behind a knob); OACT's coefficient sign has not been verified against its intended penalty direction (this task's S3 fixes it); no pose/keypoint model exists (verified negative — S2 here is a spike, not an implementation).
- **Misleading if untouched**: the packet's conditional framing ("if similarity comes from a pgvector query...") reads as though a DB re-rank stage might be needed — it is not; the correct interception point is the in-process numpy computation, confirmed above.
- **Adjacent**: FIR-6 S4 owns writing the final calibrated `oact_coefficient` value into face_pipeline-scoped knobs after real-corpus calibration — this task's S3 fixes the *sign* the coefficient is applied with, not its calibrated magnitude; FIR-6 S4's apply step is the value hand-off target (see S3).

## Target Outcome

Under `EMBEDDER`/`BOTH` verdicts, matching applies a versioned visible-support mask to the in-process cosine computation when occlusion is detected, tagging affected scans with `visible_support_applied=True`. Under `DETECTOR`/`BOTH` verdicts, an ADR records whether pose-head-rescue is feasible at all (it likely is not, absent an existing model) and what it would cost to build. Under every verdict, the OACT coefficient's sign is corrected and remains behaviour-neutral until an operator sets it nonzero, at which point FIR-6 S4's calibration apply step is the sanctioned place to set that nonzero value.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Contracts: none new; `_emit_scan_media_reconciled`'s payload is an internal event schema, not a cross-service contract — no `docs/workbay/contracts/` entry exists for it today and none is added (informational-only event-tag addition).
- Prior plans (read, do not restate): `docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md` v6.2 (Slices 0a/0/1 unconditional, 2/3/4 CONDITIONAL on `TRAINING_DECISION`/D-01), `docs/tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md` (S4 — quoted below), `docs/tasks/fir/FIR-15-attribution-split-and-oracle-ladder-task-plan.md` (D-02 decision this task branches on; `sface-support-map-v1.json` asset this task's L2 loads).
- Handoff/MCP: FIR-15's `firplan_d02_attribution_<date>` decision (read before L1's first commit); this task's own slice-complete decisions per lane.
- Heuristics: EMB-01/11/12, CAL-01/04, EVAL-19, AUDIT-04 — https://github.com/darce/heuristics-canon.

**FIR-6 S4 (cited verbatim, the OACT value hand-off target)**:

> Run the FIR-5 harness on the real corpus; run S3a's CLI; select thresholds per the pre-registered rule; record the calibration decision + artifacts in MCP. Apply step: one code commit writing calibrated values into the face_pipeline-scoped knobs (table above) + the `oact_coefficient` + factor floors, citing the MCP decision id — shared insightface settings untouched.

This task's S3 fixes the sign `oact_coefficient` is applied with; FIR-6 S4's apply step remains the sole place a nonzero, calibrated value is written. This task never sets `oact_coefficient` away from its `0.0` default.

## Contract and Boundary Impact

None. All changes are internal to `apps/prototype-description-service/recognition/`; the `_emit_scan_media_reconciled` payload addition is an internal structured-log/event-tag field, not a versioned cross-service contract.

## Proposed Solution

Three lanes, strictly ordered: L1 computes visibility and adds the two settings knobs (plus the OACT sign fix, since it lives in the same settings/quality-factor surface); L2 wires the masked-cosine re-rank into the actual in-process similarity call site, ships the support-map asset, and adds the event tag; L3 updates the eval-harness hooks so FIR-15's already-built ladder/attribution machinery can exercise the new production knobs end-to-end. S2 (pose rescue) is an out-of-lane spike, not a lane, because it produces an ADR, not code.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| quality factors | `apps/prototype-description-service/recognition/application/scan/face_quality_factors.py` | extend occlusion severity into a per-landmark-region visibility vector; fix OACT sign application |
| settings | `apps/prototype-description-service/recognition/config/settings.py` | add `visible_support_matching` + `pose_head_rescue` knobs mirroring `oact_coefficient`'s pattern; extend `ResolvedFacePipelineKnobs` |
| matching | `apps/prototype-description-service/recognition/application/discovery/centroid.py` | apply masked cosine in `_find_best_centroid_match` when a support mask is available |
| shared math | `apps/prototype-description-service/recognition/application/clustering/centroid_utils.py` | add shared `masked_cosine` pure function (imported by both runtime and eval harness) |
| asset | `apps/prototype-description-service/recognition/config/assets/sface-support-map-v1.json` (new) | versioned support-map asset shipped from FIR-15 S2's recipe |
| event tag | `apps/prototype-description-service/recognition/application/scan/service.py` | add `visible_support_applied` key to `_emit_scan_media_reconciled` payload |
| eval hooks | `apps/prototype-description-service/scripts/eval_harness/` | wire new knobs into harness runs (L3) |
| tests | `test_face_quality_factors.py`, `test_identity_quality.py`, `test_confidence_check.py`, plus new lane-scoped test files (below) | cover new knobs, masked cosine, OACT sign, event tag |
| ADR | `docs/adr/` (new, exact filename per repo ADR numbering convention) | S2 pose-head-rescue feasibility spike |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py` | `ConfidenceCheck.evaluate` (91-242) — consumes `discovery_similarity`, unchanged by this task |
| `apps/prototype-description-service/recognition/application/discovery/centroid.py` | `CentroidDiscovery.discover` (30-60), `_find_best_centroid_match` (62-87) — masked-cosine interception point |
| `apps/prototype-description-service/recognition/application/clustering/centroid_utils.py` | `compute_similarity` (51-66), `compute_centroid` (33-48) |
| `apps/prototype-description-service/scripts/eval_harness/occlusion_ladder.py` | FIR-15's eval-only `masked_cosine` — L1/L2 must converge with this, not fork it |
| `apps/prototype-description-service/scripts/eval_harness/synthetic_occlusion.py` | `anatomy_region_stats` (762-784) — visibility-scoring input shared with FIR-15 |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_face_quality_factors.py recognition/tests/unit/test_settings_face_pipeline_knobs.py -q` (L1)
  - `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_confidence_check.py recognition/tests/unit/test_centroid_masked_cosine.py recognition/tests/unit/test_scan_service_event_tags.py -q` (L2)
  - `cd apps/prototype-description-service && python3 -m pytest scene/tests/test_eval_harness_fir17_hooks.py -q` (L3)
- Runtime-parity / environment checks: none beyond existing dark-launch parity tests (`TestOactDarkScaffold`), since every new knob defaults off.
- Contract/fixture verification: `_emit_scan_media_reconciled` payload schema asserted by `test_scan_service_event_tags.py`; no external contract file to update (see Contract and Boundary Impact).
- Manual verification: operator reviews the S2 ADR before any pose-rescue implementation work is considered (out of this task's scope regardless).

## Slice Delivery

### Slice 1: Landmark visibility computation + settings knobs + OACT sign fix

**Goal**: Produce a per-region visibility signal, add the two new dark-launched knobs, and correct the OACT coefficient's sign application — all behaviour-neutral at defaults.

Changes:

- `apps/prototype-description-service/recognition/application/scan/face_quality_factors.py`: extend `compute_occlusion_severity` (82-105) with a new function:

  ```python
  def compute_landmark_visibility(
      landmarks_px: "np.ndarray",   # (5,2) detector landmarks
      occlusion_mask: "np.ndarray", # boolean image mask
  ) -> dict[str, float]:
      """Per-region visibility in [0,1] for the 5 SFace landmark regions:
      left_eye, right_eye, nose, mouth_left, mouth_right. Extends the
      existing two-eye-patch proxy (compute_occlusion_severity, 82-105) to
      all 5 regions using the same patch-sampling approach."""
  ```

  and fix the OACT sign bug: locate the existing coefficient application (wherever `oact_coefficient` multiplies/adds into a threshold or quality-factor formula in this file or `confidence.py`), and correct the sign so a higher occlusion severity moves the threshold in the direction that *tightens* acceptance (not loosens it) — the current polarity is inverted relative to the scaffold's documented intent in `TestOactDarkScaffold`. Cite the exact call site with a `[UNVERIFIED — confirm via codemap]` marker if the current sign-application line is not already covered by the packet's verified anchor inventory at the moment of implementation; the implementer must re-run `search_code("oact_coefficient")` to pin the exact line before editing.
- `apps/prototype-description-service/recognition/config/settings.py`: add two module-level resolver functions mirroring `_resolve_face_oact_coefficient` (265-267) and `_resolve_face_joint_assignment_enabled` (282-283):

  ```python
  def _resolve_face_visible_support_matching() -> bool:
      return _env_or_default_bool("RECOGNITION_FACE_VISIBLE_SUPPORT_MATCHING", default=False)

  def _resolve_face_pose_head_rescue() -> bool:
      return _env_or_default_bool("RECOGNITION_FACE_POSE_HEAD_RESCUE", default=False)
  ```

  and two new `FacePipelineSettings` fields (mirroring `oact_coefficient`'s `Field(default_factory=...)` pattern at 377-384):

  ```python
  visible_support_matching: bool = Field(default_factory=_resolve_face_visible_support_matching)
  pose_head_rescue: bool = Field(default_factory=_resolve_face_pose_head_rescue)
  ```

  Both default `False` — dark-launched, no-op until an operator sets the env var.
- Extend `ResolvedFacePipelineKnobs` (`settings.py:522-546`) with the two new fields, and extend `resolve_face_pipeline_knobs` (`settings.py:549-599`) to force both to `False` under the `insightface` profile branch (mirroring how the function already force-disables face_pipeline-only knobs under that profile) — the shared insightface settings must stay untouched per this task's constraints and per FIR-6 S4's stated boundary.

Proof:

- `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_face_quality_factors.py -q` — existing suite, extended with new cases for `compute_landmark_visibility` and the corrected OACT sign; specifically extend `TestOactDarkScaffold` (`test_face_quality_factors.py:156-207`, confirmed present via `check_index_coverage`) with a case asserting the corrected sign direction while the default-`0.0` case (already covered) continues to pass unchanged.
- New `apps/prototype-description-service/recognition/tests/unit/test_settings_face_pipeline_knobs.py`: asserts both new knobs default `False`, are settable via their env vars, and are force-disabled under the `insightface` profile in `resolve_face_pipeline_knobs`.

### Slice 2: Pose-head-rescue feasibility spike (ADR only, no implementation)

**Goal**: Determine whether a pose-head-rescue intervention is buildable at all, since no keypoint/pose/person model exists in the service today (verified negative via `search_graph`/`search_code` sweep for `keypoint|pose|yolo|person`).

Changes:

- New ADR at `docs/adr/` (numbered per the repo's existing ADR sequence — confirm the next free number before creating; `[UNVERIFIED — confirm via codemap/ls of docs/adr/ for next number]`), recording: (1) the verified-negative finding (no model exists), (2) the two build options this implies — vendor a lightweight head-pose model (new dependency, new inference cost) vs. approximate pose from the existing 5-point landmark geometry alone (cheap, likely low-fidelity), (3) a recommendation gated on FIR-15's D-02 verdict: only worth prototyping under `DETECTOR`/`BOTH` verdicts, and only after S1's visibility signal is shipped and measured.
- No code changes. This slice's only proof artifact is the ADR document itself.

Proof:

- ADR exists at the recorded path and states a clear recommendation; reviewed by the operator (manual verification — no automated test, since no code ships).

### Slice 3: OACT coefficient value hand-off boundary (documentation-only cross-reference)

**Goal**: Make explicit, in code comments and in this plan, that this task never sets a nonzero `oact_coefficient` — FIR-6 S4 owns that.

Changes:

- Add a one-line code comment at the `oact_coefficient` field declaration (`settings.py:377-384`) noting: "sign convention corrected by FIR-17 S1; calibrated nonzero value is set only by FIR-6 S4's apply step, never by this field's default."
- No new tests beyond S1's — this slice is a documentation/comment addition co-located with S1's commit, not a separate code change, and is listed separately here only because the packet's slice skeleton calls it out as its own step; the implementer may fold it into S1's commit if the reviewer agrees, since splitting it would produce a scaffold-only slice with no independent proof.

Proof:

- Comment present at the field declaration; reviewed alongside S1.

### Slice 4 (L3 eval hooks — see FIR-15 for the harness itself): Wire new knobs into eval-harness runs

**Goal**: Let FIR-15's already-built attribution/ladder harness exercise `visible_support_matching` end-to-end against the real matching code path (not just its own eval-only `masked_cosine`).

Changes:

- `apps/prototype-description-service/scripts/eval_harness/`: add a thin adapter that, when `visible_support_matching` is enabled via env var, routes the harness's similarity calls through the shared `centroid_utils.masked_cosine` (the same function S1/S2's runtime change imports) instead of its own eval-only copy — closing the loop FIR-15 flagged as an obligation ("FIR-17 S4 later moves the production equivalent into a shared pure module so both read the same code path").
- This slice does not re-run FIR-15's ladder; it only ensures the harness *can* exercise the shipped knob for any future re-measurement (e.g. FIR-16's remediated-corpus re-run).

Proof:

- New `apps/prototype-description-service/scene/tests/test_eval_harness_fir17_hooks.py`: asserts the harness adapter calls `centroid_utils.masked_cosine` (not a local eval-only copy) when the knob is enabled, and falls back to unmasked cosine when disabled.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `fir17-l1-quality-settings` | `apps/prototype-description-service/recognition/application/scan/face_quality_factors.py`, `apps/prototype-description-service/recognition/config/settings.py`, `apps/prototype-description-service/recognition/tests/unit/test_face_quality_factors.py`, `apps/prototype-description-service/recognition/tests/unit/test_settings_face_pipeline_knobs.py` | FIR-15 D-02 decision recorded | `python3 -m pytest recognition/tests/unit/test_face_quality_factors.py recognition/tests/unit/test_settings_face_pipeline_knobs.py -q` |
| `fir17-l2-matching-asset-event` | `apps/prototype-description-service/recognition/application/discovery/centroid.py`, `apps/prototype-description-service/recognition/application/clustering/centroid_utils.py`, `apps/prototype-description-service/recognition/config/assets/sface-support-map-v1.json`, `apps/prototype-description-service/recognition/application/scan/service.py`, `apps/prototype-description-service/recognition/tests/unit/test_confidence_check.py`, `apps/prototype-description-service/recognition/tests/unit/test_centroid_masked_cosine.py`, `apps/prototype-description-service/recognition/tests/unit/test_scan_service_event_tags.py` | `fir17-l1-quality-settings` | `python3 -m pytest recognition/tests/unit/test_confidence_check.py recognition/tests/unit/test_centroid_masked_cosine.py recognition/tests/unit/test_scan_service_event_tags.py -q` |
| `fir17-l3-eval-hooks` | `apps/prototype-description-service/scripts/eval_harness/` (adapter file only), `apps/prototype-description-service/scene/tests/test_eval_harness_fir17_hooks.py` | `fir17-l2-matching-asset-event` | `python3 -m pytest scene/tests/test_eval_harness_fir17_hooks.py -q` |

S2 (pose-head-rescue spike) is intentionally not a lane — it produces an ADR, not code, and has no `owned_paths`/`test_cmd` shape to lane.

### Merge Order

`fir17-l1-quality-settings` → `fir17-l2-matching-asset-event` → `fir17-l3-eval-hooks` → `feature/fir-17` → `main`.

### Manifest

```bash
make lane-manifest-init TASK=fir-17 LANE_IDS='fir17-l1-quality-settings fir17-l2-matching-asset-event fir17-l3-eval-hooks' TASK_PLAN=docs/tasks/fir/FIR-17-inference-only-occlusion-robustness-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: sequential dispatch per the depends_on chain via `dispatch_lane_work`.
- **Shell fallback**: direct implementation in `feature/fir-17` worktree, lane order enforced manually.

---

## Consolidated Checklist

> **Checklist scope rule:** describes work being delivered, not finding status. Finding status is queried from the handoff DB.

## Context and Ownership

- [ ] Read FIR-15's `firplan_d02_attribution_<date>` decision and recorded which branch-rule row applies before starting L1.
- [ ] Confirmed FIR-7 Slices 2-4 remain untouched and `TRAINING_DECISION` state is not read or written by this task.
- [ ] Confirmed no external contract is touched (event-tag addition is internal).

### Checklist for Slice 1: Landmark visibility computation + settings knobs + OACT sign fix

- [ ] `compute_landmark_visibility` implemented for all 5 SFace landmark regions.
- [ ] OACT sign application corrected; `TestOactDarkScaffold` extended with a sign-direction case while the default-`0.0` no-op case still passes unchanged.
- [ ] `visible_support_matching` and `pose_head_rescue` knobs added mirroring `oact_coefficient`'s `default_factory` pattern, both defaulting `False`.
- [ ] `ResolvedFacePipelineKnobs` and `resolve_face_pipeline_knobs` extended; both new knobs force-disabled under the `insightface` profile.

### Checklist for Slice 2: Pose-head-rescue feasibility spike

- [ ] ADR recorded at `docs/adr/` documenting the verified-negative model search and a D-02-gated recommendation.
- [ ] No production code shipped in this slice.

### Checklist for Slice 3: OACT coefficient value hand-off boundary

- [ ] Comment added at `oact_coefficient`'s field declaration citing FIR-6 S4 as the sole place a nonzero calibrated value is set.

### Checklist for Slice 4: Wire new knobs into eval-harness runs

- [ ] Eval-harness adapter routes through the shared `centroid_utils.masked_cosine` when `visible_support_matching` is enabled, and falls back to unmasked cosine otherwise.
- [ ] `test_eval_harness_fir17_hooks.py` covers both branches.

## Review Readiness

- [ ] Masked-cosine logic exists in exactly one shared pure function, imported by both runtime (`centroid_utils.py`) and eval harness — no forked copy.
- [ ] Every new knob verified dark-launched (default off) with a runtime-parity test proving merge-time behavioral neutrality.
- [ ] Handoff decision records which branch-rule row applied, which slices ran, and cites the FIR-15 D-02 decision id.

## Stretch Goals

- [ ] If S2's ADR recommends prototyping landmark-geometry-only pose approximation, scope that as a follow-on task (not part of this task).

## Success Criteria

- [ ] OACT sign fix ships and is behaviour-neutral at `oact_coefficient=0.0` (proven by the unchanged default-case test).
- [ ] Under `EMBEDDER`/`BOTH` verdicts, `visible_support_matching` knob exists, defaults off, and when enabled routes real matching through the shared masked-cosine function with `visible_support_applied` tagged on the reconciled-scan event.
- [ ] Under `DETECTOR`/`BOTH` verdicts, the pose-head-rescue ADR is recorded with a clear build/no-build recommendation.
- [ ] Eval harness can exercise the shipped knob through the same code path production uses.
- [ ] `handoff_close_check(enforce=True)` passes; task `done` + archived.
