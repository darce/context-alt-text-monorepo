# S3 · Scoring, calibration folds, paired cluster intervals, verdict

- **Wave:** W3 batch B · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0 (codes against S1/S2 record shapes in the README)
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_score.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_score.py`

## Goal

Turn per-face search records into the frozen-τ answer: FNIR at the declared FPIR on a fixed non-mated source-unit denominator, end to end (EVAL-16, EVAL-18, EVAL-19). Produce paired PSU-cluster intervals, the sealed step-down decision, guardrails, and a verdict that can be "inconclusive" (CARD-27, WRIT-81).

## Read first

- README shared names, non-mated source unit, `FaceSearchRecord`, `VerdictState`, `InconclusiveReason`, `TauInfeasibleError`, `CalibrationLeakError`, `UndeclaredH2LegError`
- `scripts/eval_harness/open_set_identification.py`: `SearchResult`, `IETPoint`, `fnir_fpi_at_threshold(*, mated, nonmated, tau, n_enrolled_gallery_subjects)`, `iet_curve`. Reuse these where the face-level record maps onto `SearchResult`. If you write a face-level variant, it must equal `fnir_fpi_at_threshold` on single-face fixtures (parity test).
- `scripts/eval_harness/calibrate_face_thresholds.py`: `identity_fold_assignment`, `select_fit_trials`, `build_trials` (lines ~376–525, bounded). `select_fit_trials` requires both the probe and the impostor-gallery identities to be in the fit set. Mirror it.
- `scripts/bench/score_report.py`: `holm_bonferroni` is not called by `decide()`. `bootstrap_paired_delta` is image-level and is not used for verdicts; your interval resamples PSUs instead.
- S0 `DecisionManifest` fields; S1 `Frame` fields (`identity_fold`, `n_units`, `n_nonmated_eff`). In this brief N_units denotes `Frame.n_units`.

## Build

1. `finish_outcomes(records, tau, boundary) -> per-record FaceOutcome` (S0 Build 10). A record is a mated GT face or a non-mated record (a non-mated GT face or a background detection). A record with `arm_availability` other than `available` is not an outcome: it is excluded and counted per arm. A fused-leg record with stage `detected` (no embedding) finishes as `missed`; its stage stays `detected` in the waterfall.
   - `legacy_v1`: a non-mated record is accepted iff score > τ; a mated record iff score ≥ τ.
   - `v2`: accept iff score ≥ τ for both.
   - The semantics are recorded in the output.
2. `curve(records, units, thresholds, boundary)`: FNIR over mated GT faces, and FPI and FPIR over non-mated source units.
   - A unit is a false-accept unit at τ when any of its non-mated records is `false_accept`.
   - FPI = the number of false-accept units. It is an integer and counts units, not searches.
   - N_units is the fixed count from S1 `build_nonmated_pool` for the scored pool. It is never a detector count.
   - FPIR = FPI / N_units. It is at most 1 by construction.
   - Additional spurious names are reported separately as an integer. They are every above-threshold non-mated name beyond the first in a unit, and every above-threshold name on a duplicate detection over a mated face (S2 Build 5). They are reported per 1,000 frame images in their own field. They never enter FPI or FPIR.
   - 1:1 FMR is also reported when pair scores are supplied.
   - Verdict and FPIR use the native arm only (S2 Build 2).
3. `calibrate_tau(records, *, units, calibration_folds, fpir_target, boundary)`:
   - Uses only units and records from calibration folds. Any test-fold unit or test-fold probe raises `CalibrationLeakError`. Any top-k gallery identity whose fold is not in `calibration_folds` raises `CalibrationLeakError`, which mirrors `select_fit_trials`.
   - **Unit score.** Each unit's score is the maximum top-1 non-mated score over its records. For a non-mated GT face this is its one score. For a background unit it is the maximum over its detections.
   - **Selection rule (the only one).** Pool the calibration units. Match them on sex, age and origin where the frame allows (CAL-04). Background units have no demographic field and form their own stratum. Let N be the pooled unit count and m = floor(fpir_target × N).
     - `legacy_v1` (accept iff score > τ): τ is the (m+1)-th largest pooled unit score. It is the smallest τ with FPI ≤ m.
     - `v2` (accept iff score ≥ τ): let w be the (m+1)-th largest pooled unit score and u the smallest pooled unit score strictly greater than w. τ is the midpoint of w and u. If no pooled score is greater than w, τ is the next representable float above w. This keeps the cut strictly above w, so it stays feasible when scores tie.
     - If N = 0, raise `TauInfeasibleError`. Never return +inf or −inf.
   - Per-fold τ is computed the same way per fold and reported as the spread (EXP-30). It never feeds the test read.
   - `scores.json` records the chosen τ, the pooled FPI at τ (unit count), and the FPI and FNIR at the next lower candidate threshold.
4. `fpir_resolvable(target, n_nonmated_eff)`: true iff n_nonmated_eff ≥ 3/target (300 at 0.01, 3,000 at 0.001). n_nonmated_eff counts non-mated source units divided by their PSU deff (S1 Build 7). This is the conservative floor; the exact zero-event floor at 0.01 is about 298. When unresolvable, report the measured FPIR with its upper limit as a designed unknown (CARD-03).
   - The FPIR upper limit uses the exact one-sided 95% Clopper–Pearson bound on the integer FPI and the integer unit count N_units, labelled as an iid approximation. For the clustered pool, report the PSU-resampled percentile bound when FPI > 0. When FPI = 0, report the rule-of-three bound 3/n_nonmated_eff, labelled approximate.
   - Never pass a fractional n_eff as the binomial n.
   - Validate FPIR-UCL coverage separately from FNIR-delta coverage (zero events, unequal cluster sizes, weighted probability arm).
5. `paired_cluster_bootstrap(outcomes_a, outcomes_b, psu_of, *, n_boot, seed, level)`:
   - Resample PSUs with replacement and recompute ΔFNIR = FNIR_a − FNIR_b on the same faces.
   - `level` is the two-sided interval level that `decide()` sets for the step: 0.95 for step 1, 0.90 for step 2. Callers do not choose it.
   - Return the percentile interval, n_psu, and the observed ICC/deff. The observed ICC is null when all outcomes are equal; it does not change n_eff, which uses the manifest ICC (S1).
   - No p-value and no test inversion.
   - Unit of resampling: PSU (image–identity component). Unit of estimand: mated GT faces, weighted per face. Interval: percentile, two-sided at the step level.
   - The `probability` sampling arm weights each record by 1 / `inclusion_probability` (S1 Build 1; the IPW weight). The `challenge` arm is reported separately and never pooled; its weight is 1.
6. `decide(manifest, results) -> Verdict`. This is the only verdict rule. It uses confidence intervals only. It computes no p-values and does not call `holm_bonferroni`.
   - **Step order and levels.** The manifest's `hypotheses` list is the Holm step order: H1, then H2. K = 2, and `alpha_family` = 0.05 is one-sided. Step k tests at one-sided level α_family / (K − k + 1): step 1 = 0.025, step 2 = 0.05. The two-sided interval level is 1 − 2 × one-sided level: 0.95 for step 1, 0.90 for step 2.
   - **H1 (superiority)**, Δ = FNIR_SF − FNIR_AF: rejects iff the step-1 percentile lower bound is > 0 and every veto guardrail holds.
   - **H2 (non-inferiority)**, Δ = FNIR_leg − FNIR_IF: tested only if H1 rejected. Rejects iff the step-2 percentile upper bound is < δ (δ = 0.05) and every veto guardrail holds. The leg is the single in-house leg named in H2's `legs` in the sealed manifest. `decide()` raises `UndeclaredH2LegError` if `results` lack that leg or carry results built for any other in-house leg as H2.
   - **Stop rule.** Stop at the first non-rejection. A hypothesis that is not reached has no state. A non-rejection is `inconclusive`, whether the interval spans the boundary or lies entirely on the other side. The verdict prints the interval and the side.
   - **Check order.** Apply these checks in order and stop at the first that applies:
     1. Not ratified or not sealed: `unratified`, numbers only (`require_verdict_allowed`).
     2. Eligibility, before any interval is read:
        - Primary FPIR unresolvable (`fpir_resolvable` false at the frame's n_nonmated_eff): `inconclusive` with reason `primary_fpir_unresolvable`, applied to every hypothesis, and no winner is named regardless of the FNIR interval.
        - A veto guardrail is null or unscored, or a per-cohort FPIR has n_eff under 3/FPIR: `inconclusive` with reason `required_guardrail_unscored`. A resolvable per-cohort FPIR above its limit is a failure, not an unscored value.
     3. Veto: a veto guardrail with a measured value outside its limit gives `guardrail_vetoed` for the hypothesis being decided.
     4. The step-level tests above.
   - **MDE** (shown before unseal, for each step). MDE is the smallest Δ > 0 for which the scope §Power formula gives a required n ≤ n_eff. Use z_{α/2} = 1.96 for H1 (one-sided 0.025) and 1.645 for H2 (one-sided 0.05), z_β = 0.8416 (power 0.80), and p_d from the manifest. The unit is effective mated searches (n_eff). Solve by bisection; the required n is monotone in Δ. Write MDE to `scores.json`. If H2 is reached and its MDE > δ, H2 is `inconclusive` with reason `margin_unreachable_mde_gt_delta`, whatever its interval says.
   - **Verdict states.** Each evaluated hypothesis carries one `VerdictState`. H1 rejected gives `superior`. H2 rejected gives `non_inferior` only on a frame whose registry entry is `confirmatory`; on any other frame H2 is `inconclusive` with reason `non_confirmatory_frame`, and its numbers stay on the report. H1 may give `superior` on a development frame.
   - The `Verdict` stores the state per hypothesis id, the reason, the step levels, the interval and MDE for each step, and the decision path.
7. Pair cells:
   - Build the query occluder × enrolled occluder table with faces, identities, PSUs and FNIR per leg.
   - A cell is "not scored" below `cell_floor_n_independent` independent PSUs.
   - Real and synthetic cells are kept in separate tables.
8. Stage waterfall and joint gaps.
   - Counts per `SearchStage` per leg, over mated GT faces on the native arm. The fused leg has no `unaligned` count.
   - For each attribution arm (`gt_crop_redetect`, `cached_yunet_landmark_replay`), report the joint gap: ΔFNIR = FNIR(arm) − FNIR(native) over the mated faces where both the arm and native records are `available`, with its paired PSU interval. Faces with `arm_availability` `unavailable` or `unavailable_fused` are counted per arm and excluded from that gap. They are never imputed as misses.
   - No percentage shares are apportioned to localization, alignment or the embedder. No arm is named as a cause. The gap is a joint intervention effect.
9. Guardrails from the manifest. Each guardrail has a `role` set in the sealed manifest: `veto` gates the verdict; `report_only` is written to `scores.json` and the report and never gates.
   - per-cohort FPIR (each cohort with resolvability, over that cohort's non-mated source units; background units count only in the all-cohort FPIR) — veto
   - false names per 1k name mentions — veto
   - worst pair-cell FNIR, over the cells named in the guardrail's `cohort_scope`; unscored if any named cell is not scored — veto
   - p95 ms per face — veto. It reads `timings.json` (Build 10), and its measured value is not written to `scores.json`.
   - cost per accepted description (nullable column) — report-only until its source (S2 timings plus the retry and abstention ledger) is wired
10. Output files.
    - `scores.json` is the semantic output only, validated against `scores-v1` (S0 Build 9). It is deterministic and sorted, with no clock reads. It records τ and the calibration spread, the pooled FPI at τ, N_units, the FPI at the next lower candidate, n_eff, deff, MDE and step levels per step, each interval, the state and reason per hypothesis, and each guardrail value with its role. For the p95 veto it records the state only (`pass`, `fail` or `unscored`) and the sha256 of the `timings.json` it read. A rerun on the same run directory reads the same receipt, so the bytes match.
    - `timings.json` is written by the run (S6a), never by `score`. `score` reads it and never rewrites it. Its contents are non-replayable and are excluded from the byte-identity rule.

## RED tests

- Analytic fixture: 10 mated faces with known top-1 and 20 non-mated source units; FNIR, FPI and FPIR at τ match hand counts exactly. The face-level result equals `fnir_fpi_at_threshold` on the same single-face data.
- Boundary: a score exactly equal to τ flips between `legacy_v1` and `v2` exactly as specified.
- `calibrate_tau` raises `CalibrationLeakError` on a test-fold unit, on a test-fold probe, and on a calibration probe whose top-k contains a test-fold identity.
- τ selection: a hand-computed calibration fixture yields exactly the expected τ under `legacy_v1` and under `v2`, including a fixture with tied unit scores at the boundary. An empty pool raises `TauInfeasibleError`.
- A no-face source image carrying an above-threshold spurious name raises the FPI numerator by one and leaves N_units unchanged.
- A duplicate detection over a mated face with an above-threshold name increases additional spurious names and leaves FPI unchanged.
- Bootstrap: identical outcomes give Δ = 0 with a degenerate interval, the observed ICC is null, and the verdict is `inconclusive`. Clustered fixture: the PSU interval is wider than the image-level interval.
- Joint gap: a fixture with two `unavailable` replay faces reports the gap on the remaining faces only, and the two faces appear in the per-arm count, not as misses.
- A fused record with stage `detected` finishes as `missed`, and the waterfall still counts it under `detected`.
- Step levels: a fixture whose 95% lower bound is ≤ 0 is not `superior`, even when its 90% lower bound is > 0. A fixture that rejects H1 at the step-1 level reaches H2; one that does not leaves H2 without a state.
- `decide()` never calls `holm_bonferroni` (a mock that raises fails the test).
- An H2 leg not named in the manifest raises `UndeclaredH2LegError`.
- Primary resolvability: `fpir_resolvable(0.01, 207)` and `fpir_resolvable(0.001, 207)` are false, with 207 as n_nonmated_eff in non-mated source units. `decide()` at that n_nonmated_eff with a favorable FNIR interval returns `inconclusive` with `primary_fpir_unresolvable` and names no winner. The FPI = 0 case reports the rule-of-three bound labelled approximate, not a resolved 0.01 point.
- Guardrails: a null veto guardrail gives `required_guardrail_unscored`; a null `report_only` cost does not block a verdict.
- MDE: at n_eff = 300 and δ = 0.05, a truly equal in-house leg gives `margin_unreachable_mde_gt_delta` for H2 and never `non_inferior`.
- Development frame: a fixture in which H2's interval would reject gives `inconclusive` with `non_confirmatory_frame`, not `non_inferior`.
- An unratified manifest gives `unratified` and still returns the numbers.
- The p95 veto reads `timings.json`, and `scores.json` contains no p95 millisecond value.

## Done when

Tests pass on the VM. This slice owns AE-1 (scoring known answers) and AE-6, and supplies the functions AE-2 to AE-4 call through S9.

## Out of scope

The simulator (S9); HTML (S5).
