# S9 · Simulator and acceptance suite (`fir-bench-acceptance`)

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0–S3 and S6b merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_selftest.py`
  - `apps/prototype-description-service/scene/tests/fixtures/firbench_sim_v1.json`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_acceptance.py`
  - Plus one make target `fir-bench-acceptance` appended to `mk/evals.mk` after the S6b targets. `mk/evals.mk` is edited serially (S6a, then S6b, then this lane); S6b is merged before this lane starts (README dispatch).

## Goal

Prove the bench detects effects that exist and stays quiet when none exist, before anyone trusts a verdict. The deliberate canary is governed by EXP-13 (A/A before A/B: a null test before any test is trusted), not EXP-06 (investigate a surprising move): the planted effects here are designed inputs, not surprises. This slice implements the task plan's completion evals AE-2, AE-3 and AE-4, and the runner that executes the full AE table.

Sizing follows Canon v0.26.2: Account for cluster design effect (AUDIT-11, *Sampling: Design and Analysis*, ch. 5), Power and practical significance (EXP-12, *Trustworthy Online Controlled Experiments*, ch. 2), and Pseudoreplication check (EXP-23, *Statistics Done Wrong*, ch. 3); CARD-27 requires pre-run effective sizing and sealed margins. These sources establish the mechanisms, not this project's numeric gates or evidence of a simulated or real pass.

## Build

1. `simulate(params, *, seed) -> (Frame, records_a, records_b)`. Parameters live in `firbench_sim_v1.json`, never in code:
   - PSU size distribution in mated-face counts, declared per suite before outcomes (AE-2/AE-3 default: face-count size-weighted mean M̃ ≈ 13; AE-4 uses a smaller-size distribution to satisfy both its effective-search target and independent-PSU floors, as below). These are simulator choices, not the report's image-count M̃ = 12.925; the fixture records face-count and image-count values separately. S1 measures the real values; the report figure is not a measurement of the simulated or current real frame.
   - ICC (default 0.10: the value of `DecisionManifest.planning_icc`, a design assumption and not an observed ICC; sensitivity rows in item 10)
   - target effective **mated searches**, n_eff: 300 for the null suite, 115 for the power case, 400 for the H2 branch case. These are not PSU counts. For declared mated-face sizes m_j, compute raw n = Σm_j, M̃ = Σm_j² / Σm_j, deff = 1 + (M̃ − 1) × planning ICC, and n_eff = n / deff. Choose size counts before generating outcomes to attain the target and the global/cell PSU floors together; report the sizes, raw n, distinct PSU counts, deff and attained n_eff, globally and per tested cell. Keep the stated targets across ICC rows, recomputing size counts/distribution as needed; integer sizing must be disclosed, never hidden by rounding a materially larger n_eff down to the target. Use the frozen S1 sizing rules, without adding shared helpers or a reverse dependency from S0.
   - discordance p_d (default 0.15, equal to `DecisionManifest.p_d`, a design assumption and not observed) and the cross-leg covariance, generated from the fixture so the power design's assumptions are tested rather than assumed. The suites read p_d from the manifest, and a fixture value that differs from it refuses the run.
   - per-leg base FNIR (default 0.15)
   - non-mated source-unit count (non-mated GT faces plus one background unit per image)
   - planted effects by pair cell and by stage
   Outcomes are generated per GT face, with a PSU random effect on the logit scale so the target ICC holds.
2. `run_null_suite(params, *, replicates, seed)` (AE-2b): A and B are identical in distribution. Reports:
   - (a) the rate at which `decide()` returns `superior` (step 1, H1 at Δ = 0), with its Monte Carlo SE;
   - (b) the step-2 boundary rate: the rate at which step 2 rejects at Δ = δ with H1 forced to pass, with its Monte Carlo SE. The H2 leg is the one named in the manifest before the run.
3. `run_selection_control` (sealing control): both in-house legs at δ against InsightFace. The H2 leg is chosen after the run as the leg with the smaller estimate. Reports the step-2 boundary rate under that post-run choice, with H1 forced to pass, the same definition as Build 2 (b). It checks the fixture, not the tool: it shows that the fixture can detect the inflation an unsealed choice causes. The acceptance table fails the suite when the rate stays within the bound, because a fixture that cannot show the inflation proves nothing about sealing. The post-run choice is circular by construction (EXP-22).
4. `run_coverage_suite` (AE-3): reports the fraction of replicates whose 95% interval covers the true Δ, for the PSU bootstrap and, on the same replicates, for the image-level bootstrap from `score_report.bootstrap_paired_delta`. The PSU is the independent unit (AUDIT-11 design effect; EXP-23 pseudoreplication check).
5. `run_power_suite` (AE-4): planted Δ 0.10 at n_eff 115 gives the H1 detection rate, reported against the declared minimum effect Δ 0.10 and power 0.80 (EXP-12). It must also have ≥50 independent PSUs globally and ≥30 in every tested cell, including clear→mask and clear→clear. The default M̃ ≈ 13 cannot simply be carried into AE-4: near-equal 13-face PSUs at ICC 0.10 would reach n_eff ≈ 115 with only about 20 PSUs, failing the global floor.
   - A feasible **sizing illustration**, not a simulated pass or observed result: 46 singleton PSUs and 23 four-face PSUs give raw n = 138, Σm_j² = 414, M̃ = 3, deff = 1.2 and n_eff = 115 at ICC 0.10, with 69 independent PSUs. Allocate whole PSUs to clear→mask (23 singletons + 12 four-face PSUs: 35 PSUs) and clear→clear (23 + 11: 34 PSUs); both cells meet the floor. Declare a suitable allocation for every additional tested cell. The 115 target is global; report each cell's own n_eff and power rather than claiming 115 for each cell.
   - Freeze the chosen distribution and allocation in the fixture before outcomes; this sizing arithmetic supplies no coverage or power evidence. A cell-only effect gives per-cell detection. A stage defect gives the stage counts and the joint gaps against native. Keep every pass rule below. An under-floor design cannot serve as AE-4 evidence, and oversampling to a higher effective size cannot be reported as the n_eff 115 gate.
6. `run_noninferiority_suite` (H2 branches, S3 Build 6):
   - (a) H1 planted at Δ 0.10; the H2 leg equal to InsightFace; n_eff 400. H2 rejects in ≥ 0.77 of replicates.
   - (b) H1 planted; the H2 leg at δ. H2 false rejection is measured with the same rule as `run_null_suite` (b).
   - (c) An H2 leg whose 90% interval spans δ gives `inconclusive`, never `non_inferior`.
7. MDE refusal: at n_eff 300 and δ 0.05, a truly equal in-house leg gives `margin_unreachable_mde_gt_delta` for H2 in every replicate, and never `non_inferior`.
8. `acceptance_report(results) -> dict`: pass or fail per AE with the numbers, written to the run dir. `make fir-bench-acceptance` runs the simulated suites (replicates from the fixture, default 2,000) and the fixture evals (AE-1, AE-6 to AE-9 test modules). Every full replicate uses `DecisionManifest.interval.n_boot` (delegated default 10,000); never reduce full replicate or bootstrap counts, stop early, or drop failing replicates to force a pass. Use chunked/vectorized paired PSU sufficient statistics (weighted miss totals and denominators per PSU, leg and cell) where needed, preserving the paired PSU resampling, face-weighted estimand and declared seeded draw order. Bound memory by bootstrap chunks rather than materializing all face rows for every draw. Preserve image-level resampling for the coverage comparator. The report records requested/completed replicate and bootstrap counts. It has a `semantic` part, byte-identical across reruns, and a `timing` part for runtime, excluded from identity as in S6a item 5. AE-10 is not computed here (see the pass-rule table).
9. **Eligibility floors (MCP 16736).** Before any FPIR eligibility or interval, each replicate counts distinct independent PSUs. Fewer than `DecisionManifest.min_n_independent` (50) gives `inconclusive` with `InconclusiveReason.insufficient_independent_psus`, and no interval is computed. A pair cell with fewer than `cell_floor_n_independent` (30) independent PSUs is not scored, so the AE-4 cell-only check is valid only where its cell passes that floor. The floors are project policy and prove no adequacy: power, MDE, FPIR resolvability and exhaustive GT still gate separately. Consume S0's frozen `min_n_independent`, `cell_floor_n_independent`, `p_d` and `InconclusiveReason.insufficient_independent_psus`; do not redefine them locally.
10. **Planning ICC sensitivity.** AE-2, AE-3 and AE-4 also run at planning ICC 0.05 and 0.20 with the same stated n_eff. These rows are reported beside the 0.10 rows. They are not gated. A failing sensitivity row is written as a finding; it does not change the 0.10 gate or the pass rules.
11. **Numeric comparison rules.** These apply to every check the target runs, including AE-1 and AE-6 to AE-9. Counts are integers compared with `==`, with no tolerance. An analytic rate's oracle is a `fractions.Fraction`, and the float output must satisfy `abs(value - float(oracle)) <= 1e-12`. That is the only tolerance in this lane. AE-1's "no tolerance" holds on the oracle side: the Fraction is exact, and the 1e-12 bound covers float rounding only. Monte Carlo rates are never compared with a tolerance; they are judged by the bounds in the pass-rule table.
12. **Policy and source record.** Each value is recorded with its status. Policy values are declared project choices, not canon constants.

    | Value | Status | Basis |
    | --- | --- | --- |
    | Planning ICC 0.10; sensitivity 0.05, 0.20 | Project policy; design assumption, not observed | `DecisionManifest.planning_icc`; MCP 16733 |
    | Design effect deff ≈ 1 + (M − 1) × ICC | Source-established | AUDIT-11 |
    | Face-count M̃ ≈ 13 (AE-2/AE-3); suite-specific AE-4 distribution; image-count M̃ = 12.925 (report) | Simulator choices; historical report figure, not current measurement | Items 1 and 5; S1 measures the real values |
    | Discordance p_d 0.15; power 0.80; minimum effect Δ 0.10 | Project policy; design assumption, not observed | `DecisionManifest.p_d`; FIRBENCH-1-scope.md, Power; EXP-12 |
    | One-sided α 0.05; nominal 0.025 and 0.05 | Project policy | `alpha_family`; AE-2 |
    | Standard error sqrt(p(1 − p)/R), R = 2,000: 0.00349, 0.00487, 0.0089 | Source-established arithmetic (binomial) | AE-2, AE-4 |
    | 2 MC SE (AE-2), 3 SE (AE-4) tolerances | Project policy | Pass-rule table |
    | Bound 9 of 200 = 95% upper quantile of Binomial(200, 0.025) | Computed: P(X ≤ 8) = 0.934, P(X ≤ 9) = 0.970; carried in the fixture | Build RED tests |
    | Eligibility floors: 50 distinct PSUs globally, 30 per pair cell | Project policy; not canon-prescribed; prove no adequacy | MCP 16736 |
    | Interval on delta; A/A before A/B; no circular selection; count the independent unit | Source-established | EXP-12, EXP-13, EXP-22, EXP-23 |

## Pass rules (from the task plan)

| Eval | Rule |
| --- | --- |
| AE-2b, step 1 | `superior` rate ≤ 0.032 at 2,000 replicates (nominal 0.025 + 2 MC SE, SE = 0.00349) |
| AE-2b, step 2 | step-2 boundary rate ≤ 0.060 at 2,000 replicates (nominal 0.05 + 2 MC SE, SE = 0.00487) |
| Selection control | `non_inferior` rate under post-run selection > 0.060. A value within the bound means the fixture cannot show the inflation, and the suite fails. |
| AE-3 | PSU-bootstrap coverage in [0.93, 0.97] |
| AE-4 | Planted Δ 0.10 at n_eff 115 detected by H1 in ≥ 0.77 of 2,000 replicates (0.80 power minus 3 SE, SE = 0.0089). The cell-only effect is detected in its own cell and in clear→clear no more often than the null rate. The stage defect appears in the `missed` stage count, and the wrong-identity rate among embedded faces changes by at most 0.05 (absolute) between planted and control runs. |
| H2 branches | Build 6 (a) ≥ 0.77; (b) ≤ 0.060; (c) zero `non_inferior` states |
| MDE refusal | Build 7: every replicate gives `margin_unreachable_mde_gt_delta`; zero `non_inferior` |
| Eligibility floors (item 9) | Fewer than 50 distinct PSUs gives `insufficient_independent_psus` with no interval. Pair cells below 30 PSUs are not scored. |
| ICC sensitivity (item 10) | Rows at 0.05 and 0.20 are reported beside the 0.10 gate. They are not gated. |
| AE-10 (coordinator-recorded; not run by S9) | The read-only laptop static scan records the alias-map hit count (pass: 0), scanned paths/scope, the scan's code SHA (must equal the run SHA), and scanner implementation SHA/digest. The scanner digest identifies the scanner; it is distinct from the scanned code/run SHA. The alias map never goes to the VM or any lane, and no S9 code or fixture reads it. The branch-diff checks are as written in the plan's AE-10 row. Missing laptop evidence stays pending, never passed by a VM substitute. |

## RED tests (small replicate counts for CI speed; not full acceptance evidence)

- With 50 replicates and a fixed seed, the suite output is byte-identical across two runs.
- A deliberately broken interval (the image-level bootstrap on a clustered fixture at ICC 0.3) fails the coverage rule. This proves the check can fail.
- A planted Δ of 0 gives `superior` in at most 9 of 200 replicates with a fixed seed. The bound 9 is the 95% upper quantile of Binomial(200, 0.025), and it is written in the fixture, not in code.
- The fixture loads and rejects unknown keys.
- The numeric rule (item 11): a count off by one fails. A float rate 1e-13 from its `Fraction` oracle passes, and one 1e-9 away fails.
- A 49-PSU fixture gives `insufficient_independent_psus` with no interval. A 50-PSU fixture passes the floor. A fixture whose p_d differs from `DecisionManifest.p_d` refuses the run.

## Done when

Tests pass on the VM, and the full `make fir-bench-acceptance` (2,000 replicates, full manifest bootstrap count in each replicate) result is reported with its runtime and attained sizing/floor counts. Runtime goes in the report's `timing` part, not the semantic part. The coordinator records the result as a `test_result` at HEAD. AE-10 is recorded separately by the coordinator; the S9 report does not mark it passed. Synthetic suite results do not supply real GT exhaustiveness, human observation or ratification evidence.
