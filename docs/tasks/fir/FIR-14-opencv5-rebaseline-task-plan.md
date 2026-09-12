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
- **Toolchain block**: the new `{opencv, opencv_major, onnxruntime, numpy}` fingerprint stamped into every face report, sourced field-by-field from `NumericRuntimeFingerprint` (`opencv_version`, `opencv_major`, `onnxruntime_version`, `numpy_version`); `NumericRuntimeFingerprint.compact` (a `@property`, no call parentheses) supplies the single-line log form used elsewhere, not the report schema.
- **A1″**: FIR-11 Slice 5's toolchain-isolation arm (golden150 full pixels, original labels, original scoring, OpenCV 5.x) — this task's re-baseline run is the CV5 measurement A1″ needs.

## Current State Analysis

- `pyproject.toml` base deps already pin `opencv-python==5.0.0.93`, `onnxruntime`, `scipy` — the toolchain upgrade is already live on this branch; only the withdrawal record and the re-scored artifacts are missing.
- `recognition/infrastructure/face_pipeline/provenance.py` already exposes `NumericRuntimeFingerprint` (333-379, fields verified: `opencv_version: str`, `opencv_major: int`, `onnxruntime_version: str`, `numpy_version: str`; `compact` is a `@property` at 371-379, returns `f"opencv={opencv_version};opencv_major={opencv_major};onnxruntime={onnxruntime_version};numpy={numpy_version}"` — **not** a method, callers write `fingerprint.compact`, never `fingerprint.compact()`) and `numeric_runtime_fingerprint()` (382-401, returns `NumericRuntimeFingerprint`) — verified via `get_code_snippet`. `scripts/eval_harness/landmark_cache.py` already imports from `recognition.infrastructure.face_pipeline` (verified via `search_code`), so a cross-directory import from `scripts/eval_harness/report.py` into that module is consistent with existing precedent, not a new coupling pattern.
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
| eval-harness | `scripts/eval_harness/cli.py` | `main()` (3067-3416, ~3267) score-face subparser gains `--allow-toolchain-drift`; `_check_expect_report` (1300-1345, comparison at 1341) gains `allow_toolchain_drift` and strips `toolchain` from both sides before re-comparing on mismatch; `_check_face_determinism_cross_process` (2236-2311, call site 2305) and `_cmd_score_face` (2316-2432, call site 2353) forward the flag. |
| tooling | `Makefile` | New `bakeoff-face-rebaseline` target near `bakeoff-face` (936-941). |
| results | `benchmarks/results/golden150-cv5-rebaseline-<date>/{candidate,buffalo}/` | New — re-baseline run + score artifacts. |
| results | `benchmarks/results/golden150-cv5-rebaseline-<date>/toolchain-arm.json` | New — FIR-11 S5 hand-off artifact (shape defined in Slice 3). |
| tests | `scene/tests/test_eval_harness_report.py` | New test(s) for the `toolchain` key shape. |
| tests | `scene/tests/test_eval_harness_cli.py` | New test(s) for `--allow-toolchain-drift` refusal/allow behavior. |
| fixtures | `docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-{manifest,run}-20260811*` (4 files) | Conditional (Slice 4 only, if `make eval-anchor-check` fails on CV5) — regenerated in place via `generate_face_determinism_anchor.py`. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/recognition/infrastructure/face_pipeline/provenance.py` | `NumericRuntimeFingerprint`'s four fields (`opencv_version`, `opencv_major`, `onnxruntime_version`, `numpy_version`) and its `compact` `@property` (371-379, no call parentheses) and `numeric_runtime_fingerprint()` (382-401) — source of the toolchain block's values. |
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

Implements: FIRG-030..032; stamps FIRG-003's `rubric_version` (owned by FIR-13 S1) into the re-baseline output.

**Goal**: The pre-CVUP-1 artifacts are named as withdrawn, and every future face report states the toolchain that scored it.

Changes:

- `benchmarks/results/WITHDRAWN.md` (new): lists `golden150-fir-{baseline,v2,final,buffalo,buffalo-baseline}-20260723/` plus M-12 (0.865/0.321), recall 0.504, and 2.73 faces/image, each with a one-line reason (pre-CVUP-1 toolchain / contaminated ground truth / apparent-not-prevalence framing) and canon citations [DRIFT-03], [EVAL-28].
- `scripts/eval_harness/report.py`: add `from recognition.infrastructure.face_pipeline import provenance` (module-level import, matching `landmark_cache.py`'s existing pattern) and insert into the dict `score_face_run_record` (4224-4987) returns the canonical four-field toolchain block (DD-08 — matches the spec's `toolchain: {"opencv": str, "onnxruntime": str, "numpy": str, "opencv_major": int}` shape verbatim; every field is read off the typed dataclass, `compact` is never invoked here):

```python
fingerprint = provenance.numeric_runtime_fingerprint()
scored["toolchain"] = {
    "opencv": fingerprint.opencv_version,
    "onnxruntime": fingerprint.onnxruntime_version,
    "numpy": fingerprint.numpy_version,
    "opencv_major": fingerprint.opencv_major,
}
```

  Exact insertion point inside `score_face_run_record` is `[UNVERIFIED — confirm via codemap]`; the implementer must locate where the function assembles its final return dict (grep for `return` near the end of the 4224-4987 range) before landing this change.
- `scripts/eval_harness/cli.py`: `main()` score-face subparser (~3267, alongside the `--manifest` default at that same block, verified `default="scene/tests/seed/golden.json"`) gains:

```python
sub.add_argument(
    "--allow-toolchain-drift",
    action="store_true",
    help="permit --expect-report comparison across a differing OpenCV major version",
)
```

  The drift override is implemented at the actual expected-report comparison boundary, not as a side-channel check in `_cmd_score_face` (C03 — a separate opencv-major comparison in `_cmd_score_face` cannot stop `_check_expect_report`'s `expected == base_json` byte-equality at `cli.py:1341` from still failing the whole comparison on any toolchain-only difference):
  - `_check_expect_report` (`cli.py:1300-1345`) gains a keyword-only `allow_toolchain_drift: bool = False` parameter. When the `expected == base_json` string compare at line 1341 fails, and `allow_toolchain_drift` is `True`, re-parse both `expected` and `base_json` as JSON, pop the `toolchain` key from each copy (`dict.pop("toolchain", None)` — tolerates a **missing** legacy toolchain block, e.g. a pre-Slice-1 frozen anchor, by treating "absent" the same as "present but ignored"), and re-compare the two dicts. Equal after stripping `toolchain` → PASS, printed as `determinism check passed [{label}]: ... (toolchain drift allowed: {old_block} -> {new_block})`, never silently identical to the unqualified pass message (auditable in CI logs). Still unequal after stripping → unchanged `ANCHOR_MISMATCH` behavior (a real scoring-code drift is never masked by the flag). When `allow_toolchain_drift` is `False` (default), behavior is byte-for-byte unchanged from today — including when the frozen JSON is malformed and can't even be re-parsed, in which case the flag is refused with the existing ERROR taxonomy (`--allow-toolchain-drift` requires JSON-well-formed input on both sides; a non-JSON legacy anchor falls back to the plain byte-compare path and cannot use the flag).
  - `_check_face_determinism_cross_process` (`cli.py:2236-2311`, call site at `cli.py:2305`) gains a keyword-only `allow_toolchain_drift: bool = False` parameter, forwarded unchanged into its `_check_expect_report(...)` call.
  - `_cmd_score_face` (`cli.py:2316-2432`) reads `args.allow_toolchain_drift` and forwards it into its `_check_face_determinism_cross_process(...)` call (call site at `cli.py:2353`, alongside the existing `expect_report=expect_report` keyword).
  - The caption-side `_check_expect_report` call (`cli.py:1500`) is unaffected — it omits the new keyword, so it keeps the default `False` and today's byte-exact behavior.

Proof:

- `scene/tests/test_eval_harness_report.py::test_face_report_carries_toolchain_block` (asserts the key and its four subfields — `opencv`, `onnxruntime`, `numpy`, `opencv_major` — exist and `opencv` matches `cv2.__version__` from the test process).
- `scene/tests/test_eval_harness_cli.py::test_score_face_refuses_toolchain_drift_without_flag`, `::test_score_face_allows_toolchain_drift_with_flag`, `::test_check_expect_report_allows_toolchain_only_diff_with_flag`, `::test_check_expect_report_still_fails_non_toolchain_diff_with_flag` (flag set, but a non-toolchain field also differs — still `ANCHOR_MISMATCH`), `::test_check_expect_report_tolerates_missing_legacy_toolchain_block`.

### Slice 2: Re-baseline run (both legs, CV5)

Supports: FIRG-030 (produces the re-baseline evidence rows; the requirement is implemented in Slice 1).

**Goal**: One DIAGNOSTIC-tier CV5 measurement for each leg, determinism-checked.

Changes:

- Root `Makefile`, new target near `bakeoff-face` (936-941). `benchmarks/manifests/golden150-draft-20260723.json` lives at the **repo root** (confirmed present there, absent under `apps/prototype-description-service/benchmarks/`), so from the `cd apps/prototype-description-service` working directory the manifest is `../../benchmarks/manifests/golden150-draft-20260723.json` (DD-19 — one working directory per fenced block, repo-root paths written relative to it):

```make
.PHONY: bakeoff-face-rebaseline
bakeoff-face-rebaseline:
	@cd apps/prototype-description-service && uv run python -m scripts.eval_harness.cli face-bakeoff --manifest ../../benchmarks/manifests/golden150-draft-20260723.json --leg candidate $(EVAL_ARGS)
	@cd apps/prototype-description-service && ACX_EVAL_BENCH=1 uv run --extra bench python -m scripts.eval_harness.cli face-bakeoff --manifest ../../benchmarks/manifests/golden150-draft-20260723.json --leg buffalo $(EVAL_ARGS)
```

  Both runs use seed 0. `face-bakeoff` writes its run-record under `apps/prototype-description-service/scripts/eval_harness/out/face-run-<stamp>.json` (`OUT_DIR`, `cli.py:105` and the write at `cli.py:2199-2205`; gitignored, PROV-01) — it never writes directly into `benchmarks/results/`. Each leg's printed run-record path (the `_printable_path(path)` line `face-bakeoff` echoes to stdout) must then be captured and passed explicitly:

  ```
  cd apps/prototype-description-service
  make bakeoff-face-score FACE_RUN=scripts/eval_harness/out/face-run-<candidate-stamp>.json \
    EVAL_ARGS="--manifest ../../benchmarks/manifests/golden150-draft-20260723.json"
  make bakeoff-face-score FACE_RUN=scripts/eval_harness/out/face-run-<buffalo-stamp>.json \
    EVAL_ARGS="--manifest ../../benchmarks/manifests/golden150-draft-20260723.json"
  ```

  (`bakeoff-face-score`, `Makefile:940-941`, forwards `$(EVAL_ARGS)` verbatim into `cli.py score-face`; without an explicit `--manifest`, `score-face`'s `--manifest` argument defaults to `scene/tests/seed/golden.json`, `cli.py:~3272`, not Golden-150 — the manifest must be passed on every scoring invocation, never assumed from the run-record.) `score-face` writes its JSON/Markdown reports beside the run-record via `_score_report_base(record_path)` (`cli.py:1554`, used at the `score-face` call site `cli.py:2363`) — i.e. also into `scripts/eval_harness/out/`, still not `benchmarks/results/`. The runbook step therefore ends with an **explicit copy**, staging exactly the permitted artifacts into the promised result directories:

  ```
  mkdir -p ../../benchmarks/results/golden150-cv5-rebaseline-<date>/{candidate,buffalo}
  cp scripts/eval_harness/out/face-run-<candidate-stamp>.json \
     scripts/eval_harness/out/face-run-<candidate-stamp>-face-report.{json,md} \
     ../../benchmarks/results/golden150-cv5-rebaseline-<date>/candidate/
  cp scripts/eval_harness/out/face-run-<buffalo-stamp>.json \
     scripts/eval_harness/out/face-run-<buffalo-stamp>-face-report.{json,md} \
     ../../benchmarks/results/golden150-cv5-rebaseline-<date>/buffalo/
  ```
- Repeated scoring during iteration passes `--allow-overwrite-report` (existing `score-face` flag) so re-running the runbook step doesn't hit `_refuse_report_overwrite` (`cli.py`, called from `_cmd_score_face`).
- Every published stratum table in this run's report carries a DIAGNOSTIC-tier banner ("corpus not yet FIR-11-R1-remediated") — same convention as FIR-8's existing tier banners.
- Determinism check: run `--check-determinism` twice per leg; walk-stability bound is `synthetic_occlusion.WALK_STABILITY_DELTA_BOUND = 0.05`.

Proof:

- `make bakeoff-face-rebaseline` exits 0 for both legs; the staged reports under `benchmarks/results/golden150-cv5-rebaseline-<date>/{candidate,buffalo}/` carry `toolchain.opencv` starting with `5.` and `toolchain.opencv_major == 5` (manual check — no new automated test, this is an operator runbook step producing DIAGNOSTIC-tier artifacts, not a merge gate).
- Two `--check-determinism` runs on each leg produce byte-identical certified reports (existing `score-face --check-determinism` gate, no new test needed — this is an operator runbook step).

### Slice 3: Toolchain arm for FIR-11 S5

Supports: FIRG-032 (toolchain arm for the FIR-11 attribution table; implemented in Slice 1).

**Goal**: Emit the CV5 A1″-equivalent artifact FIR-11 Slice 5 will read when it assembles the 6-arm table.

FIR-11 rev 7 lines 590-628 describe the `A1″` arm ("golden150 (full) / original (merge-only) labels / original scoring / 5.x toolchain / isolates: toolchain change against A1") and the delta `A1″ − A1 = toolchain` (line 609) only as a conceptual table row inside a report `bias-audit` builds later — it pins **no machine-readable JSON schema** for a hand-off file between this task and that one. This plan therefore defines the shape.

**Scoring path (C02 / DD-17 — the isolation FIR-11 line ~615 requires):** FIR-11 rev 7 line ~615 states "Every 'original scoring' arm (A1″, A1′, A2) runs through that driver" — the `original_scoring_sha`-pinned scorer (a temporary `git worktree` checked out at the pinned commit) invoked by a **current-tree driver** at function level, never the plain current-tree `score-face` path used for Slice 2's own DIAGNOSTIC-tier legs. Scoring `A1″` with the ordinary `make bakeoff-face-score` current-tree scorer would change *two* things at once relative to `A1` (toolchain **and** scoring code), which defeats the "isolates: toolchain change" claim in FIR-11's own table. This task's Slice 3 therefore invokes FIR-11's pinned-scorer-through-current-tree-driver mechanism against this task's own CV5 buffalo run-record (not FIR-11's `A1` run-record — this task supplies the CV5 *measurement* only), recording the resolved `original_scoring_sha` on the artifact so FIR-11 S5 can confirm it is the same pin FIR-11 itself resolved (today `a5f2bde52da245ca919c69cc3f503e78532fb724`, per FIR-11 line ~615's stated commit). The buffalo run-record itself still comes from this task's ordinary `bakeoff-face-rebaseline` `--leg buffalo` run (Slice 2) — only the *scoring* step for this one artifact swaps drivers.

Changes:

- `benchmarks/results/golden150-cv5-rebaseline-<date>/toolchain-arm.json` (new), scored via the `original_scoring_sha`-pinned driver against Slice 2's buffalo-leg run-record (this is the buffalo_l leg only — `A1″` in FIR-11's table is a buffalo_l arm, never a candidate leg):

```python
{
    "arm": "A1_double_prime",
    "manifest": "benchmarks/manifests/golden150-draft-20260723.json",
    "manifest_sha256": "<sha256 of the manifest file>",
    "labels": "original",       # merge-only, unmodified — no FIR-11 audit relabeling applied
    "scoring_code": "original_scoring_sha_pinned",
    "original_scoring_sha": "<40-hex sha the pinned-scorer worktree was checked out at>",
    "toolchain": {
        "opencv": "<cv2.__version__>",
        "onnxruntime": "<ort.__version__>",
        "numpy": "<numpy.__version__>",
        "opencv_major": "<int major>",
    },
    "seed": 0,
    "run_record_path": "benchmarks/results/golden150-cv5-rebaseline-<date>/buffalo/<run-record>.json",
    "report_path": "benchmarks/results/golden150-cv5-rebaseline-<date>/buffalo/<report>-face-report.json",
}
```

  `toolchain` uses the same DD-08 four-field schema as the `report.py` block, so `toolchain-arm.json` and every face report are diffable with the same key set. Note for the FIR-11 S5 implementer: this artifact supplies the CV5-toolchain *measurement*, scored through the same pinned-scorer mechanism FIR-11 S5 itself uses for `A1′`/`A2` — FIR-11 S5 reads `A1` itself from the tracked pre-CVUP-1 QA report, never from this file.

Proof:

- Manual verification: `toolchain-arm.json` parses as JSON, its `manifest_sha256` matches `sha256sum benchmarks/manifests/golden150-draft-20260723.json`, and its `original_scoring_sha` matches the SHA FIR-11's pin resolution documents (`git log --until=2026-07-23T23:59:59Z -1 --format=%H -- apps/prototype-description-service/scripts/eval_harness/face_metrics.py`, per FIR-11 line ~615).

### Slice 4: Face determinism anchor on CV5

Supports: FIRG-031 (anchor regeneration under the CV5 toolchain block; implemented in Slice 1).

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
| `fir-14` | `apps/prototype-description-service/benchmarks/results/WITHDRAWN.md`, `apps/prototype-description-service/scripts/eval_harness/report.py`, `apps/prototype-description-service/scripts/eval_harness/cli.py`, `Makefile` (rebaseline target only), `apps/prototype-description-service/benchmarks/results/golden150-cv5-rebaseline-*/`, `apps/prototype-description-service/scene/tests/test_eval_harness_report.py`, `apps/prototype-description-service/scene/tests/test_eval_harness_cli.py`, `docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json`, `docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json`, `docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json`, `docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.md` (Slice 4, conditional regeneration only) | FIR-13 | `python3 -m pytest scene/tests/test_eval_harness_report.py scene/tests/test_eval_harness_cli.py -q` |

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
- [ ] `--allow-toolchain-drift` flag added; `_check_expect_report`'s `expected == base_json` comparison (`cli.py:1341`) refuses a toolchain-only mismatch without the flag, and passes with it (non-toolchain differences still refuse either way).
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
- [ ] `score-face --expect-report` refuses a cross-toolchain comparison at the `_check_expect_report` boundary (`cli.py:1341`) unless `--allow-toolchain-drift` is passed; a non-toolchain scoring difference still refuses with the flag set.
- [ ] A CV5 DIAGNOSTIC-tier re-baseline exists for both legs with a passing determinism check.
- [ ] `toolchain-arm.json` is available for FIR-11 Slice 5 to consume.
- [ ] `make eval-anchor-check` passes on CV5.
