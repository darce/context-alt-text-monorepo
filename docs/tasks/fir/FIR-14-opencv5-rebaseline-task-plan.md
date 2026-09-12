# Task Plan

> **Metadata**
>
> - **Date**: 2026-09-11
> - **Author**: Claude Fable 5.1 (claude-fable-5-1) via sonnet drafting agent
> - **Status**: draft
> - **Owning Epic**: [docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Epic Short ID**: FIR
> - **Task ID**: `FIR-14`
> - **Target Branch**: `feature/fir-14`
> - **Review Coverage Target**: 2

---

## FIR-14. OpenCV-5 re-baseline and pre-CVUP-1 artifact withdrawal

## Objective

Formally withdraw the five pre-CVUP-1 (OpenCV 4.x) `golden150-fir-*-20260723/` result directories and the M-12/recall/faces-per-image figures, stamp every future face report with a toolchain fingerprint so this cannot recur silently, and produce one CV5 DIAGNOSTIC-tier re-baseline run (both legs) that FIR-11 Slice 5's toolchain arm (`A1″ − A1`) consumes.

## Intake

- **Scope one-pager**: none new — decomposed from the 2026-09-11 program re-plan (decision #10843).
- **Key Q&A decisions**: decision #10843 (D3 = FNIR@FPIR; withdrawn numbers never cited as evidence).
- **Not-Doing**: re-running with the FIR-11 S5 remediated corpus (that is FIR-11 S5's job, not this task's); any GPU leg; any threshold calibration (FIR-6 S4 owns `oact_coefficient`/threshold selection).

## Problem Statement

Five result directories under `benchmarks/results/golden150-fir-{baseline,v2,final,buffalo,buffalo-baseline}-20260723/` and the M-12 figures (0.865/0.321), recall 0.504, and 2.73 faces/image were produced on a pre-CVUP-1 (OpenCV 4.x) toolchain and have already been the subject of withdrawal language across FIR-11's revisions — but nothing in the tree records the withdrawal as a durable artifact, and no report emitted by `score-face` states which toolchain scored it, so a stale pre-CVUP-1 number could silently resurface in a later comparison. `pyproject.toml` now pins `opencv-python==5.0.0.93`; no run has been scored against it and published as such.

## Constraints

- CPU-only, $0. No A10/GPU spend.
- FIR-13's `GateContract`/rubric must exist before this task's re-baseline rows are considered gate-relevant (dependency: FIR-13).
- The re-baseline is DIAGNOSTIC tier only — Golden-150 is not yet FIR-11-R1-remediated at the time this task runs, so no conclusion about candidate-vs-incumbent quality may be drawn from it.
- Withdrawn numbers may be *named* (for the withdrawal register) but never cited as evidence anywhere else in this task's artifacts.
- `sr-007`: any new toolchain-major comparison is a structured comparison (major-version equality), not a magic string compare.

## Workflow Principles

- [DRIFT-03]: a toolchain change that silently reuses old numbers is a drift bug; this task's `--allow-toolchain-drift` gate makes the drift explicit and opt-in only.
- [EVAL-28]: withdrawn artifacts are named with cause, not deleted — deletion would erase the audit trail FIR-11 already references them from.
- [PRINCIPLE #15]: re-baseline before any calibration or comparison decision — this task produces no gate verdict.

## Terminology

- **Pre-CVUP-1**: any artifact produced before the OpenCV 4→5 toolchain upgrade (CVUP-1). The five withdrawn result dirs and M-12/recall-0.504/2.73-faces-per-image are all pre-CVUP-1.
- **Toolchain block**: the new `{opencv, opencv_major, onnxruntime, numpy}` fingerprint (via `NumericRuntimeFingerprint.compact()`) stamped into every face report.
- **A1″**: FIR-11 Slice 5's toolchain-isolation arm (golden150 full pixels, original labels, original scoring, OpenCV 5.x) — this task's re-baseline run is the CV5 measurement A1″ needs.

## Current State Analysis

- `pyproject.toml` base deps already pin `opencv-python==5.0.0.93`, `onnxruntime`, `scipy` — the toolchain upgrade is already live on this branch; only the withdrawal record and the re-scored artifacts are missing.
- `recognition/infrastructure/face_pipeline/provenance.py` already exposes `NumericRuntimeFingerprint` (333-379, fields verified: `compact()` method at 372-379 returns `f"opencv={opencv_version};opencv_major={opencv_major};onnxruntime={onnxruntime_version};numpy={numpy_version}"`) and `numeric_runtime_fingerprint()` (382-401, returns `NumericRuntimeFingerprint`) — verified via `get_code_snippet`. `scripts/eval_harness/landmark_cache.py` already imports from `recognition.infrastructure.face_pipeline` (verified via `search_code`), so a cross-directory import from `scripts/eval_harness/report.py` into that module is consistent with existing precedent, not a new coupling pattern.
- `report.py` has no `toolchain` key anywhere today (verified via `search_code` — zero matches for the literal `toolchain` in `report.py`). `score_face_run_record` (`report.py:4224-4987`) builds the scored dict that `build_face_reports` (`report.py:5609-5637`) serialises to JSON/Markdown — the toolchain block belongs in the dict `score_face_run_record` returns, but the exact line inside that 763-line function where the top-level dict is finalized is `[UNVERIFIED — confirm via codemap]` (only the function's start/end and its consumption by `build_face_reports` were verified this session).
- `cli.py`'s `score-face` subcommand is parsed in `main()` (`cli.py:3067-3416`, subparser registration at line 3267) and handled in `_cmd_score_face` (`cli.py:2316-2432`, verified via `get_code_snippet`) — it already has `--expect-report`, `--check-determinism`, `--freeze-certification`, `--public`, `--allow-overwrite-report`, `--allow-refused`. No `--allow-toolchain-drift` flag exists.
- `generate_face_determinism_anchor.py` exists (943 lines, verified via `search_graph` and `check_index_coverage`: `no_recorded_issue`) with `main()` (873-938), `write_face_anchor()` (777-870), `build_face_anchor_run_record()` (493-637) — the anchor regenerator this task's Slice 4 may need is real, not a packet assumption.
- `make eval-anchor-check` (`Makefile:857-885`, `.PHONY` at 857) runs `cli.py score --check-determinism` and `cli.py score-face --check-determinism` against fixed manifests/run-records under `docs/tasks/vlm/bakeoff-results/S2A-*-20260811*`, then `cli.py draw-eval-split --check`. It does not itself run `face-bakeoff`; it only re-scores pinned anchor artifacts.
- `make bakeoff-face` / `make bakeoff-face-score` exist at `Makefile:936-941` (`.PHONY` at 936); `bakeoff-face-score` exits 2 without `FACE_RUN` set.

## Target Outcome

`benchmarks/results/WITHDRAWN.md` names the five pre-CVUP-1 result dirs and the three withdrawn figures with cause. Every face report gains a `toolchain` block, and `score-face --expect-report` refuses a comparison across a toolchain-major mismatch unless `--allow-toolchain-drift` is passed. One CV5 re-baseline run (both legs) lands under `benchmarks/results/golden150-cv5-rebaseline-<date>/`, DIAGNOSTIC tier, carrying the toolchain block and a determinism check. A `toolchain-arm.json` artifact in that same directory is the CV5 A1″-equivalent measurement FIR-11 Slice 5 will read when it builds the 6-arm table. The face determinism anchor is confirmed live (or regenerated) on CV5.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Contracts: none cross-service.
- Handoff/MCP state: task ref `FIR-14`; depends on `FIR-13` (gate contract must exist before this task's rows are gate-relevant); FIR-11 rev 7 Slice 5 (lines 590-628) for the arm-table shape this task's toolchain-arm artifact feeds.

## Proposed Solution

Land the withdrawal register first (pure docs, no code dependency). Add the toolchain block to `report.py`'s scored dict and the `--allow-toolchain-drift` refusal to `cli.py`'s `score-face` path. Run the CV5 re-baseline via a new `bakeoff-face-rebaseline` make target that composes the existing `face-bakeoff --leg candidate` / `--leg buffalo` and `score-face` commands. Emit the FIR-11-consumable toolchain-arm artifact. Confirm or regenerate the determinism anchor.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| docs | `benchmarks/results/WITHDRAWN.md` | New — withdrawal register. |
| eval-harness | `scripts/eval_harness/report.py` | `score_face_run_record` (4224-4987) return dict gains a `toolchain` key; new import of `recognition.infrastructure.face_pipeline.provenance`. |
| eval-harness | `scripts/eval_harness/cli.py` | `main()` (3067-3416, ~3267) score-face subparser gains `--allow-toolchain-drift`; `_cmd_score_face` (2316-2432) refuses on major-version mismatch against `--expect-report` unless the flag is passed. |
| tooling | `Makefile` | New `bakeoff-face-rebaseline` target near `bakeoff-face` (936-941). |
| results | `benchmarks/results/golden150-cv5-rebaseline-<date>/{candidate,buffalo}/` | New — re-baseline run + score artifacts. |
| results | `benchmarks/results/golden150-cv5-rebaseline-<date>/toolchain-arm.json` | New — FIR-11 S5 hand-off artifact (shape defined in Slice 3). |
| tests | `scene/tests/test_eval_harness_report.py` | New test(s) for the `toolchain` key shape. |
| tests | `scene/tests/test_eval_harness_cli.py` | New test(s) for `--allow-toolchain-drift` refusal/allow behavior. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/recognition/infrastructure/face_pipeline/provenance.py` | `NumericRuntimeFingerprint.compact()` (372-379) and `numeric_runtime_fingerprint()` (382-401) — source of the toolchain block's values. |
| `apps/prototype-description-service/scripts/eval_harness/landmark_cache.py` | Existing precedent for `scripts/eval_harness/` importing from `recognition/infrastructure/face_pipeline/`. |
| `docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md:590-628` | Slice 5 arm table — `A1″` row ("golden150 (full) / original / original / 5.x / toolchain change") is the arm this task's `toolchain-arm.json` feeds; `A1″ − A1` delta defined at line 609. |
| `apps/prototype-description-service/scripts/eval_harness/generate_face_determinism_anchor.py` | Anchor regenerator, used only if Slice 4's `make eval-anchor-check` fails on CV5. |
| `apps/prototype-description-service/pyproject.toml` | `opencv-python==5.0.0.93` (base deps), `bench` extra (insightface + opencv-python-headless) with the "Dockerfile installs `.[bench]` ... until FIR-6" comment. |

## Verification Strategy

- Deterministic tests:
  - `uv run --extra dev pytest scene/tests/test_eval_harness_report.py -k toolchain -q`
  - `uv run --extra dev pytest scene/tests/test_eval_harness_cli.py -k toolchain_drift -q`
- Runtime-parity / environment checks:
  - `make eval-anchor-check` (`Makefile:857-885`) — must pass on CV5 as a precondition for Slice 4's checklist item.
- Contract/fixture verification:
  - `make bakeoff-face-rebaseline` produces both leg directories with a `toolchain` block whose `opencv_major` matches the installed `opencv-python==5.0.0.93`.
- Manual verification: none.

## Slice Delivery

### Slice 1: Withdrawal register and toolchain fingerprint

**Goal**: The pre-CVUP-1 artifacts are named as withdrawn, and every future face report states the toolchain that scored it.

Changes:

- `benchmarks/results/WITHDRAWN.md` (new): lists `golden150-fir-{baseline,v2,final,buffalo,buffalo-baseline}-20260723/` plus M-12 (0.865/0.321), recall 0.504, and 2.73 faces/image, each with a one-line reason (pre-CVUP-1 toolchain / contaminated ground truth / apparent-not-prevalence framing) and canon citations [DRIFT-03], [EVAL-28].
- `scripts/eval_harness/report.py`: add `from recognition.infrastructure.face_pipeline import provenance` (module-level import, matching `landmark_cache.py`'s existing pattern) and insert into the dict `score_face_run_record` (4224-4987) returns:

```python
fingerprint = provenance.numeric_runtime_fingerprint()
scored["toolchain"] = {
    "opencv": fingerprint.opencv_version,
    "onnxruntime": fingerprint.onnxruntime_version,
    "numeric_runtime_fingerprint": fingerprint.compact(),
}
```

  Exact insertion point inside `score_face_run_record` is `[UNVERIFIED — confirm via codemap]`; the implementer must locate where the function assembles its final return dict (grep for `return` near the end of the 4224-4987 range) before landing this change.
- `scripts/eval_harness/cli.py`: `main()` score-face subparser (~3267) gains:

```python
sub.add_argument(
    "--allow-toolchain-drift",
    action="store_true",
    help="permit --expect-report comparison across a differing OpenCV major version",
)
```

  `_cmd_score_face` (2316-2432): when `expect_report_raw` is set, load the expected report's `toolchain.opencv` major-version prefix and compare it against the freshly-scored `toolchain.opencv` major; if they differ and `--allow-toolchain-drift` is not passed, exit via the existing `_score_gate_fail` path with a new prefix (e.g. `SCORE_GATE_PREFIX_TOOLCHAIN_DRIFT`, following the existing `SCORE_GATE_PREFIX_*` naming convention visible at `_cmd_score_face`'s other gate calls).

Proof:

- `scene/tests/test_eval_harness_report.py::test_face_report_carries_toolchain_block` (asserts the key and its three subfields exist and `opencv` matches `cv2.__version__` from the test process).
- `scene/tests/test_eval_harness_cli.py::test_score_face_refuses_toolchain_drift_without_flag`, `::test_score_face_allows_toolchain_drift_with_flag`.

### Slice 2: Re-baseline run (both legs, CV5)

**Goal**: One DIAGNOSTIC-tier CV5 measurement for each leg, determinism-checked.

Changes:

- Root `Makefile`, new target near `bakeoff-face` (936-941):

```make
.PHONY: bakeoff-face-rebaseline
bakeoff-face-rebaseline:
	@cd apps/prototype-description-service && uv run python -m scripts.eval_harness.cli face-bakeoff --manifest benchmarks/manifests/golden150-draft-20260723.json --leg candidate $(EVAL_ARGS)
	@cd apps/prototype-description-service && ACX_EVAL_BENCH=1 uv run --extra bench python -m scripts.eval_harness.cli face-bakeoff --manifest benchmarks/manifests/golden150-draft-20260723.json --leg buffalo $(EVAL_ARGS)
```

  Both runs use seed 0. Each run's output run-record is then scored via the existing `make bakeoff-face-score FACE_RUN=<path>`, writing to `benchmarks/results/golden150-cv5-rebaseline-<date>/{candidate,buffalo}/`.
- Every published stratum table in this run's report carries a DIAGNOSTIC-tier banner ("corpus not yet FIR-11-R1-remediated") — same convention as FIR-8's existing tier banners.
- Determinism check: run `--check-determinism` twice per leg; walk-stability bound is `synthetic_occlusion.WALK_STABILITY_DELTA_BOUND = 0.05`.

Proof:

- `make bakeoff-face-rebaseline` exits 0 for both legs; `scripts/eval_harness/tests/test_calibrate_face_thresholds.py`-style manual check that the resulting reports carry `toolchain.opencv` starting with `5.`.
- Two `--check-determinism` runs on each leg produce byte-identical certified reports (existing `score-face --check-determinism` gate, no new test needed — this is an operator runbook step).

### Slice 3: Toolchain arm for FIR-11 S5

**Goal**: Emit the CV5 A1″-equivalent artifact FIR-11 Slice 5 will read when it assembles the 6-arm table.

FIR-11 rev 7 lines 590-628 describe the `A1″` arm ("golden150 (full) / original (merge-only) labels / original scoring / 5.x toolchain / isolates: toolchain change against A1") and the delta `A1″ − A1 = toolchain` (line 609) only as a conceptual table row inside a report `bias-audit` builds later — it pins **no machine-readable JSON schema** for a hand-off file between this task and that one. This plan therefore defines the shape:

Changes:

- `benchmarks/results/golden150-cv5-rebaseline-<date>/toolchain-arm.json` (new), written by the same `bakeoff-face-rebaseline` runbook step as Slice 2's buffalo leg (this is the buffalo_l leg only — `A1″` in FIR-11's table is a buffalo_l arm, never a candidate leg):

```python
{
    "arm": "A1_double_prime",
    "manifest": "benchmarks/manifests/golden150-draft-20260723.json",
    "manifest_sha256": "<sha256 of the manifest file>",
    "labels": "original",       # merge-only, unmodified — no FIR-11 audit relabeling applied
    "scoring_code": "original", # current-tree scorer, not the pinned original_scoring_sha driver
    "toolchain": {"opencv": "<cv2.__version__>", "onnxruntime": "<ort.__version__>"},
    "seed": 0,
    "run_record_path": "benchmarks/results/golden150-cv5-rebaseline-<date>/buffalo/<run-record>.json",
    "report_path": "benchmarks/results/golden150-cv5-rebaseline-<date>/buffalo/<report>-face-report.json",
}
```

  Note for the FIR-11 S5 implementer: this artifact only supplies the CV5-toolchain *measurement*; FIR-11 S5's `original_scoring_sha`-pinned driver reads `A1` itself from the tracked pre-CVUP-1 QA report, never from this file.

Proof:

- Manual verification: `toolchain-arm.json` parses as JSON and its `manifest_sha256` matches `sha256sum benchmarks/manifests/golden150-draft-20260723.json`.

### Slice 4: Face determinism anchor on CV5

**Goal**: Confirm (or regenerate) the shipped determinism anchor now that the default toolchain is CV5.

Changes:

- Run `make eval-anchor-check` (`Makefile:857-885`) as-is first. If it passes, this slice is a verification-only checklist item — no file changes.
- If it fails: regenerate via `scripts/eval_harness/generate_face_determinism_anchor.py main()` (873-938), which calls `write_face_anchor()` (777-870) to rewrite the anchor fixtures under `docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-*-20260811*`. `[drafter note: whether the anchor's existing fixtures already encode an OpenCV-version-independent contract, or whether they will fail on CV5, is not knowable without actually running the CV5 toolchain — this is deliberately a conditional slice.]`

Proof:

- `make eval-anchor-check` exits 0 after this slice, regardless of which branch (pass-as-is or regenerate) was taken.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `fir-14` | `apps/prototype-description-service/benchmarks/results/WITHDRAWN.md`, `apps/prototype-description-service/scripts/eval_harness/report.py`, `apps/prototype-description-service/scripts/eval_harness/cli.py`, `Makefile` (rebaseline target only), `apps/prototype-description-service/benchmarks/results/golden150-cv5-rebaseline-*/`, `apps/prototype-description-service/scene/tests/test_eval_harness_report.py`, `apps/prototype-description-service/scene/tests/test_eval_harness_cli.py` | FIR-13 | `python3 -m pytest scene/tests/test_eval_harness_report.py scene/tests/test_eval_harness_cli.py -q` |

### Merge Order

`fir-14` (single lane; depends on `fir-13` landing first).

### Manifest

```bash
make lane-manifest-init TASK=FIR-14 LANE_IDS='fir-14' TASK_PLAN=docs/tasks/fir/FIR-14-opencv5-rebaseline-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

---

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried from the handoff DB via `review_findings(review={"operation":"list","status":"open","task_ref":"FIR-14"})` or read from `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded FIR-13's `GateContract`/rubric artifacts (this task's re-baseline rows reference the rubric version they were scored under).
- [ ] Confirmed no cross-service boundary is touched (internal to `scripts/eval_harness/` + `benchmarks/`).

### Checklist for Slice 1: Withdrawal register and toolchain fingerprint

- [ ] `benchmarks/results/WITHDRAWN.md` lists all five result dirs and all three withdrawn figures with cause.
- [ ] `score_face_run_record` return dict carries a `toolchain` block on every call.
- [ ] `--allow-toolchain-drift` flag added; `_cmd_score_face` refuses a major-version mismatch without it.
- [ ] Toolchain block and drift-refusal tests pass.

### Checklist for Slice 2: Re-baseline run (both legs, CV5)

- [ ] `bakeoff-face-rebaseline` make target added and runs both legs at seed 0.
- [ ] `benchmarks/results/golden150-cv5-rebaseline-<date>/{candidate,buffalo}/` populated with run records + reports carrying the CV5 toolchain block.
- [ ] Every stratum table in the new reports carries the DIAGNOSTIC-tier banner.
- [ ] Determinism check passes twice per leg within the 0.05 walk-stability bound.

### Checklist for Slice 3: Toolchain arm for FIR-11 S5

- [ ] `toolchain-arm.json` emitted in the defined shape, `manifest_sha256` verified against the source manifest.

### Checklist for Slice 4: Face determinism anchor on CV5

- [ ] `make eval-anchor-check` passes on CV5 (as-is or after regeneration).

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] The `report.py` insertion point for the toolchain block is confirmed by the implementer (resolving this plan's one `[UNVERIFIED]` marker) before merge.
- [ ] Handoff decision records the change, verification, and that no withdrawn number was cited as evidence anywhere in this task's own artifacts.

## Stretch Goals

- [ ] A `make` target that diffs two `toolchain` blocks and prints a human-readable drift summary.

## Success Criteria

- [ ] `benchmarks/results/WITHDRAWN.md` exists and names every pre-CVUP-1 artifact with cause.
- [ ] Every face report emitted by `score-face` carries a `toolchain` block.
- [ ] `score-face --expect-report` refuses a cross-toolchain-major comparison unless `--allow-toolchain-drift` is passed.
- [ ] A CV5 DIAGNOSTIC-tier re-baseline exists for both legs with a passing determinism check.
- [ ] `toolchain-arm.json` is available for FIR-11 Slice 5 to consume.
- [ ] `make eval-anchor-check` passes on CV5.
