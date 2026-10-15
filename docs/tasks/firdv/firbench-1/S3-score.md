# S3 · Scoring, calibration folds, paired cluster bootstrap, verdict

- **Wave:** W3 batch B · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0 (codes against S1/S2 record shapes in the README)
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_score.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_score.py`

## Goal

Turn per-face search records into the frozen-τ answer: FNIR at the declared FPIR on a fixed non-mated denominator, end to end (EVAL-16, EVAL-18, EVAL-19). Produce paired cluster intervals, Holm decisions and guardrails, and a verdict that can be "inconclusive" (CARD-27, WRIT-81).

## Read first

- README shared names, `FaceSearchRecord`
- `scripts/eval_harness/open_set_identification.py`: `SearchResult`, `IETPoint`, `fnir_fpi_at_threshold(*, mated, nonmated, tau, n_enrolled_gallery_subjects)`, `iet_curve`. Reuse these where the face-level record maps onto `SearchResult`. If you write a face-level variant, it must equal `fnir_fpi_at_threshold` on single-face fixtures (parity test).
- `scripts/eval_harness/calibrate_face_thresholds.py`: `identity_fold_assignment`, `build_trials` (lines ~376–520, bounded)
- `scripts/bench/score_report.py`: `holm_bonferroni(pairs, alpha, *, family_size)`, `bootstrap_paired_delta` (image-level; your interval must resample PSUs instead)
- S0 `DecisionManifest` fields

## Build

1. `finish_outcomes(records, tau, boundary) -> per-face FaceOutcome`.
   - `legacy_v1`: a non-mated face is accepted iff score > τ; a mated face iff score ≥ τ.
   - `v2`: accept iff score ≥ τ for both.
   - The semantics are recorded in the output.
2. `curve(records, thresholds, boundary)`: FNIR and FPI, with FPIR = FPI / n_nonmated, where n_nonmated is the fixed pool from S1 and never a detector count. Also 1:1 FMR when pair scores are supplied.
3. `calibrate_tau(records, *, calibration_folds, fpir_target, boundary)`:
   - Uses only faces from calibration folds. Any test-fold face raises `CalibrationLeakError`.
   - Returns τ plus the per-fold spread (EXP-30).
4. `fpir_resolvable(target, n_nonmated_eff)`: n ≥ 3/target. When unresolvable, report the measured FPIR with its one-sided 95% Clopper–Pearson upper limit on n_eff (a designed unknown, CARD-03).
5. `paired_cluster_bootstrap(outcomes_a, outcomes_b, psu_of, *, n_boot, seed, level)`:
   - Resample PSUs with replacement and recompute ΔFNIR = FNIR_a − FNIR_b on the same faces.
   - Return the percentile interval, the bootstrap p-value by test inversion, n_psu, and the observed ICC/deff.
   - The probability arm uses inverse-probability weights from S1; the challenge arm is reported separately and never pooled.
6. `decide(manifest, results) -> Verdict`. Run Holm over the manifest hypotheses using `holm_bonferroni`.
   - Superiority: the CI lower bound > 0.
   - Non-inferiority: the upper confidence limit of (FNIR_inhouse − FNIR_reference) < δ.
   - A CI that spans the boundary gives `inconclusive`.
   - Any failed guardrail gives `guardrail_vetoed`.
   - Any decision while `require_verdict_allowed` fails gives `unratified` with full numbers but no verdict.
   - Verdict states come from `VerdictState`.
7. Pair cells:
   - Build the query occluder × enrolled occluder table with faces, identities, PSUs and FNIR per leg.
   - A cell is "not scored" below `cell_floor_n_independent`.
   - Real and synthetic cells are kept in separate tables.
8. Stage waterfall: counts per `FaceOutcome` per leg. Attribution shares come from the arm ladder (native vs oracle_box vs ref_landmarks), labelled "attribution, not causal".
9. Guardrails from the manifest:
   - per-cohort FPIR (each cohort with resolvability)
   - false names per 1k name mentions
   - worst pair-cell FNIR
   - p95 ms per face (from S2 timings)
   - cost per accepted description (nullable column)
10. `scores.json` writer: deterministic and sorted, with no clock reads.

## RED tests

- Analytic fixture: 10 mated faces with known top-1 and 20 non-mated; FNIR, FPI and FPIR at τ match hand counts exactly. The face-level result equals `fnir_fpi_at_threshold` on the same single-face data.
- Boundary: a score exactly equal to τ flips between `legacy_v1` and `v2` exactly as specified.
- `calibrate_tau` raises on a test-fold face.
- Adding detector false alarms does not change FPIR.
- Bootstrap: identical outcomes give Δ = 0 with a degenerate interval, and the verdict is `inconclusive`. Clustered fixture: the PSU interval is wider than the image-level interval.
- Holm: two hypotheses with p = 0.02 and 0.04 at α 0.05 are both rejected; with 0.01 and 0.06, only the first; with 0.03 and 0.04, neither (Holm stops at the first non-rejection, 0.03 > 0.025).
- An unratified manifest gives `unratified` and still returns the numbers.
- `fpir_resolvable(0.001, 207)` is false and reports the upper limit.

## Done when

Tests pass on the VM. Owns AE-1 (scoring known answers) and AE-6, and supplies the functions AE-2 to AE-4 call through S9.

## Out of scope

The simulator (S9); HTML (S5).
