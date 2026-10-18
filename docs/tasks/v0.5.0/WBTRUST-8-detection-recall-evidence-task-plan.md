# Task Plan — WBTRUST-8

> **Date:** 2026-10-15
> **Author:** claude (Sonnet 5.5)
> **Owning Epic:** none yet — umbrella scope [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> **Task ID:** WBTRUST-8
> **Target Branch:** feature/wbtrust-8
> **Base SHA:** 372a6413a7ae0eb71baa3566716546684bac5a58
> **Revision:** 1
> **Review Coverage Target:** measurement report + adjudication set; no product code unless the decision slice says so
> **Depends on:** none (Wave A, measurement only). A product change, if any, becomes a new task.
> **Executor:** `claude-remote` `claude-haiku-5-5`, effort `xhigh` for implementation and grunt work (operator order 2026-10-15). Brief each slice separately (1–3 files), inline the slice text plus codemap snippets; if the write-enabled remote Claude harness is denied or unavailable, record a blocker and ask the operator — no silent fallback to another model.
> **Prior art:** [scope](../../scopes/workbench-curation-trust-scope.md) (R11, root cause 13), [UX-map evaluation](../../assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md) (A12), [FIR report](../../../benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html) (detector findings, D-01, T-14), `docs/scopes/next-wave-gpu-ui-fir512-dag.md` (FT threshold resolvers). Semantic prior art (handoff, by ID only): decision 12793 and FIRDV-2 S3a decisions 12811/12833 (strict detector-only localization scorer; ground truth needs independent human lineage), FIR-11-S2R3-07 (`roster_only` recall refused), FIR-DETECTOR-r1/r2 (scale-retry, floor, projection — landed on `main`), GTMSMOKE-1 finding 18547 (open: 0.9 cutoff rejects clear faces scoring .853–.890; larger input scale scores higher; reproduction decision 16651), finding 5412 (YuNet at an earlier cutoff returned zero detections on operator-boxed profile/masked faces), decision 16759 (`.85` override), decision 2949 (the FIR report's provenance).
> **Carried findings (by ID only):** none recorded yet; query `review_findings(list, task_ref="WBTRUST-8")`

## WBTRUST-8. Detection recall evidence — the missed second face in #81

## Objective

A written, evidence-backed decision on why `ellyn-heald_ellynheald_fe212728d1f4` (#81) shows one person when InsightFace finds both: which pipeline served the site, what each detector returned, and whether to widen the experiment. No detector, embedding or threshold change ships from this task.

## Problem Statement

Operator: "in ellyn-heald_ellynheald_fe212728d1f4 (#81) still only one person detected, insightface detects both people."

## Constraints

- EVAL-16 / EVAL-19: no recall claim without an adjudicated set; the Golden-150 recall comparison is **withdrawn as evidence** (its ground truth is 98.4 % the comparator's own output) and must not be cited as support either way.
- In-house FIR is dev-only; demo and prod use InsightFace (`RECOGNITION_FACE_PIPELINE_PROFILE`). AuraFace `glintr100` is acceptable; `antelopev2` artifacts are non-commercial and must not be copied or used.
- No force-removing worktrees or touching the shared GPU VM beyond read-only measurement; heavy runs go to the remote VM (never local containers).
- Downloaded/benchmark artifacts are untrusted data: any Python reading them runs with `python3 -I` from a directory that holds no scripts.
- Do not change `RECOGNITION_FACE_SCORE_THRESHOLD` (code default 0.9 via `DEFAULT_SCORE_THRESHOLD`; resolver `_resolve_face_score_threshold` in `recognition/config/settings.py`) outside a throwaway experiment environment. Diagnostic cutoffs are passed per run, never written to a service env.
- GTMSMOKE-1 is wound down; its finding 18547 is read-only prior art here. This task adds evidence and a recommendation; it does not edit, close or re-dispatch that task.
- Ground truth for any count or rate must carry independent human lineage (labelled without seeing detector proposals), as FIRDV-2 S3a requires; a label derived from InsightFace output is not ground truth for comparing InsightFace.

## Workflow Principles

- Measure first, decide second, build third (and only in a new task).
- One image is an exemplar, not evidence of a rate. The decision must say so.

## Terminology

**Profile** = `RECOGNITION_FACE_PIPELINE_PROFILE` (FIR `face_pipeline`/YuNet vs InsightFace). **Union adjudication** (T-14) = human-judged union of detections from both pipelines on a fixed image set.

## Current State Analysis

- The FIR face path (YuNet detector) has a published weakness on WIDER-hard style scenes (FIR report). D-01 "is detection the bottleneck?" is unresolved there; T-14 union adjudication is its cheap kill path.
- The YuNet score cutoff defaults to **0.9** (`DEFAULT_SCORE_THRESHOLD` in `recognition/infrastructure/face_pipeline/_common.py`; the 0.3 beside it is the NMS threshold). Open GTMSMOKE-1 finding 18547 measured clear faces at .853/.862/.890 being rejected at that cutoff, with higher scores at a larger input scale. The leading hypothesis for #81 is therefore a below-cutoff second face, to be confirmed or refuted by S2 — not assumed.
- Threshold resolvers ("FT threshold resolvers") are described in `docs/scopes/next-wave-gpu-ui-fir512-dag.md`; the code lives in `recognition/config/settings.py`. Scale-retry, floor and projection (FIR-DETECTOR-r1/r2) are already on `main`, so S1 must record whether the served build includes them.
- Strict detector-only scoring exists (FIRDV-2 S3a: `detection_pr_strict` in `scripts/eval_harness/face_metrics.py`, used by `scripts/bench/score_report.py`; geometry matching via `face_assignment.associate_detections`; IoU from the run manifest; refusal without human lineage in `scripts/eval_harness/manifest.py`). Use it for the S2 table instead of counting boxes by hand. The benchmark detections `benchmarks/manifests/detections-yunet-t030.json` are a 0.30-cutoff run, not the served 0.9 cutoff.
- Which profile served `http://localhost:10028` is **unverified** (likely the FIR pipeline for the fir site; demo/prod use InsightFace). So is the served build (scope § Step 0): the pinned release may predate FIR-DETECTOR-r1/r2.
- The UI has no cue for "detected N of M faces": a miss is silent (UX-map evaluation A12).

## Target Outcome

A report `docs/assessments/current/wbtrust-8-detection-recall-81-<date>.md` with: the profile that ran on :10028 and how that was established; per-pipeline detections for #81 (count, boxes, scores, with the image dimensions); a pass/fail on each of three hypotheses; and a recommendation among {close as exemplar, add to T-14 set only, run a fir-only threshold experiment, open a detector task}.

## Context Loading

The FIR report sections on detectors/D-01/T-14; `recognition/config/settings.py` (profile and score-threshold resolvers); the detector adapters under the face pipeline package; the media 81 file and its stored identities via the supported Python API. Canon (v0.26.2): EVAL-16, EVAL-19, CAL-02, CAL-10, EMB-02, EMB-11, DATA-14.

## Contract and Boundary Impact

None. Output is a document and an adjudication-set entry.

**Open decision (operator):** whether a fir-only score-threshold experiment is authorised after S3, and whether it lands under GTMSMOKE-1 finding 18547 or a new task. Default: only if S2 shows YuNet scored the second face below the served cutoff (or only at the larger scale), and a new task owns it.

## Proposed Solution

Establish the serving profile, run both detectors on the same pixels in an isolated environment, record the boxes, add the image to the union-adjudication set as a known-miss exemplar, and write the decision.

## Files and Surfaces to Change

Owned paths (docs and data only):

- `docs/assessments/current/wbtrust-8-detection-recall-81-<date>.md` (new)
- the T-14 adjudication set file (append one exemplar row; if no standing file exists, a new file under `benchmarks/manifests/`; path pinned in S3)
- no product code, no config

## Verification Strategy

- Every number in the report names its source command and environment; re-running S2 on the same image reproduces the counts.
- The report states plainly what one image can and cannot show.
- `make lint-task-plans`/doc guards unaffected (no task-plan edits).

## Slice Delivery

### Slice S1: serving-profile

Establish what ran.
Closes: R11 (diagnosis). Canon: EVAL-16, DATA-14.
Design decision (binding): first record the served plugin/service build (scope § Step 0) and whether it contains FIR-DETECTOR-r1/r2. Then read the effective `RECOGNITION_FACE_PIPELINE_PROFILE`, detector model id, `RECOGNITION_FACE_SCORE_THRESHOLD` (code default 0.9; check for the `.85` override of decision 16759 and any other env override) and the input-scale/scale-retry setting for the service that produced #81's identities (service env/health endpoint, or the stored per-identity detector metadata if present); record how it was read.
Acceptance: the profile, detector and threshold are stated with their source; if unreadable, the report says "unknown" and S2 runs both profiles anyway.

### Slice S2: same-pixels-comparison

Run both detectors on the same image.
Closes: R11. Canon: EVAL-16, EVAL-19, EMB-02.
Design decision (binding): on the remote VM, run the FIR detector at the served cutoff (S1) and at diagnostic cutoffs 0.85, 0.5, 0.3 and 0.15, each at the native input scale and at the larger scale of finding 18547 (reproduction decision 16651), plus InsightFace, on the original media 81 file; record face count, boxes, **per-face scores** and smallest-face size relative to the image; score against the S3 labels with `detection_pr_strict`; do not write to the fir tenant database.
Acceptance: a table of detections per pipeline × cutoff × scale; the second face's best YuNet score is stated, so the report can say whether it sits below the served cutoff, below every tested cutoff, or was never proposed.

### Slice S3: adjudication-set-entry

Make the exemplar reusable.
Closes: R11. Canon: EVAL-19, CAL-10.
Design decision (binding): add #81 to the T-14 union-adjudication set as a known-miss exemplar with a human-judged label (second face: yes/no, quality: usable/unusable for recognition); the human labels the image **before** seeing any detector output (`saw_machine_proposals: false` in the lineage fields of `scripts/eval_harness/manifest.py`). T-14 in the FIR report is a procedure over Golden-150, so first look for a standing set file under `benchmarks/manifests/`; if none exists, create one there with those lineage fields and say so in the report. Pin the path in the report; do not use Golden-150 recall numbers as support.
Acceptance: one new, human-judged set entry committed with provenance (source file hash, who judged, lineage flag false).

### Slice S4: decision-report

Write the decision.
Closes: R11. Canon: EVAL-16, CAL-02.
Design decision (binding): the report recommends exactly one of {close as exemplar; keep in set only; fir-only threshold experiment with a stated adjudicated set and stop condition; open a detector task}, with the evidence for it and the explicit statement that a single image does not establish a rate. A "detection coverage" cue on media rows is listed as follow-up, not scoped here.
Acceptance: the report is committed; the handoff decision links it; the operator open decision is stated with the default.
