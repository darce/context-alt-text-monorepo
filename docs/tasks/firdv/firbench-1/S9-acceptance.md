# S9 · Simulator and acceptance suite (`fir-bench-acceptance`)

- **Wave:** W3 batch C · **Depends on:** S0–S3 and S6b merged. S6b must merge into `feature/firbench-1` before either S9 author starts.
- **Owned paths** (two authors share this contract):
  - S9-simulator: `apps/prototype-description-service/scripts/eval_harness/firbench_selftest.py` and `apps/prototype-description-service/scene/tests/fixtures/firbench_sim_v1.json`.
  - S9-checks: `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_acceptance.py` and one make target `fir-bench-acceptance` in `mk/evals.mk`, appended after the S6b targets. `mk/evals.mk` is edited serially: S6a, then S6b, then S9.
- **Policy basis:** Canon v0.26.2 rows EXP-12 (Power and practical significance, *Trustworthy Online Controlled Experiments*, ch. 2), EXP-13 (A/A before A/B, same source, ch. 19), EXP-22 (No circular analysis, *Statistics Done Wrong*, ch. 6), EXP-23 (Pseudoreplication check, same source, ch. 3) and AUDIT-11 (Account for cluster design effect, *Sampling: Design and Analysis*, ch. 5). CARD-27 is the exact supplement at the untracked context copy `canon-supplement/margin-and-design-effect-before-the-run.md` (SHA-256 `186c94c2b0ba88897cebea26c39752d6f0e87bbab8bff3ec1fa9aace79f85aad`, matching the v0.26.2 release manifest). These sources establish the mechanisms. They do not establish this project's numeric gates, or any simulated or real pass.
- **Declared status:** This brief resolves the reviewed S9 implementation choices as declared project policy, under the canon-first delegation. Those values are not canon constants, not measured ICCs, not ratification and not a simulated pass.

## Status

**Current (2026-10-15).** The S9 simulator, fixture, acceptance tests and `fir-bench-acceptance` target are present in the checked tree. The report author's source audit recorded the simulator and fixture matching the run receipt's source hashes; this is not a live checkout comparison. The software checks have completed (coordinator-recorded counts, not re-run in the documentation pass). The full v6 acceptance run (R = 2000, B = 10000) executed and **failed numerically**: 2 of 8 gated checks failed (AE-2b H2 boundary, AE-4 cell-only power). Numerical acceptance is FAILED and full AE1–12 is not passed. The slice is not complete; do not claim it complete. Pins, per-case results and the post-outcome assessment are in [`benchmarks/reports/firbench-1-simulation-v6-20261015.md`](../../../../benchmarks/reports/firbench-1-simulation-v6-20261015.md). The pre-outcome numeric protocol clauses, seeds, distributions and original pass rules in this brief are unchanged by that run. The frozen fixture separately imposes a cell-only ≥ 0.77 bar, stronger than the qualitative plan clause; AE-4 remains FAILED under that fixture (report §4, note 2). The independently pinned post-assembly synthetic AE-11 comprehension/browser component passes at `43522276` (report §9.1); it changes no canonical MC status or real-data gate.

- Present in the checked tree: `scripts/eval_harness/firbench_selftest.py`, `scene/tests/fixtures/firbench_sim_v1.json`, `scene/tests/test_eval_harness_firbench_acceptance.py`, `scene/tests/test_eval_harness_firbench_acceptance_reporting.py`, the S6a and S6b targets and the `fir-bench-acceptance` target in `mk/evals.mk`.
- The launch gate (S6b merged into `feature/firbench-1`) cannot be verified in this clone, which has a single history-stripped base commit.
- Superseded snapshot (tree `21408d43562ef2f49a3b27c53112bae0cc822605`, earlier review): "Not implemented in this tree." That described an older tree and is not current.

**Producers consumed (exact names; line numbers re-checked 2026-10-15).** S3 and the S0 contract are the only statistical producers. S9 must call them, not duplicate them.

| Name | Location |
| --- | --- |
| `finish_outcomes(records, tau, boundary)` | `firbench_score.py:253` |
| `calibrate_tau(records, *, units, calibration_folds, fpir_target, boundary, identity_folds=None)` | `firbench_score.py:460` |
| `paired_cluster_bootstrap(outcomes_a, outcomes_b, psu_of, *, n_boot, seed, level, weights=None)` | `firbench_score.py:650` |
| `decide(manifest, results)` | `firbench_score.py:844` |
| `build_nonmated_pool(...)`, `build_frame(*, spec, images, ...)` | `firbench_frames.py:469`, `:595` |
| `DecisionManifest`, `IntervalSpec`, `Hypothesis`, `InconclusiveReason`, `FrameContractError`, `NonPrivateOutputError`, `require_private_output_path` | `firbench_contract.py` (`:464`, `:418`, `:407`, `:155`, `:122`, `:102`, `:1049`) |
| `bootstrap_paired_delta(a, b, seed, *, metric, occasion_ids, occasion_full_size, accepted_mask, B, cell)` | `scripts/bench/score_report.py:185` |

`bootstrap_paired_delta` defaults `B` to `BOOTSTRAP_RESAMPLES = 2000` (`score_report.py:53`). The coverage suite must pass `B=10000` explicitly.

**Committed decision manifest** (`benchmarks/manifests/fir-bench-decision-v1.json`, verified): `planning_icc` 0.1; `p_d` 0.15; `power` 0.8; `alpha_family` 0.05; `min_n_independent` 50; `cell_floor_n_independent` 30; `interval` = paired cluster percentile bootstrap, PSU `image_identity_component`, `n_boot` 10000, `seed` 2429382368. H1 is superiority of `[sface, auraface]` with margin 0 and direction `lower_bound_above_margin`. H2 is non-inferiority of `[auraface, insightface]` with margin 0.05 and direction `upper_bound_below_margin`. `ratification` and `seal` are null, so every verdict from this manifest is unratified.

**Recomputed in this revision.** These are arithmetic checks on the packet values. They are not simulator results.

- Seeds: `int.from_bytes(SHA256('FIRBENCH-1/simulator/v1')[:4], 'big') = 2208172209`. The label-queue, folds, gallery and bootstrap seeds match the README values.
- Size table: every row's raw n, PSU count, Σm², M̃, deff and n_eff matches the table in Build 5.
- Miss-law theoretical FNIRs and pair discordances, computed with `fractions.Fraction`, match Build 3.
- `Binomial(200, 0.025)`: P(X ≤ 8) = 0.9344 and P(X ≤ 9) = 0.9700, so the 95% upper quantile is 9.
- Standard errors: `sqrt(0.025·0.975/2000) = 0.00349`; `sqrt(0.05·0.95/2000) = 0.00487`; `sqrt(0.8·0.2/2000) = 0.00894`. Thresholds before rounding: 0.03198, 0.05975 and 0.77317, consistent with the rounded pass rules (≤ 0.032, ≤ 0.060, ≥ 0.77).

## Frozen public API

This is the shared packet that both S9 authors implement and test against. It is declared here; the implementation is present in the checked tree (see Status).

Module `scripts.eval_harness.firbench_selftest`:

- **`SimulationParams`**: frozen dataclass with fields `decision: DecisionManifest`, `fixture: Mapping[str, Any]`, `suite: str = 'null'`, `icc: float = 0.10`. Independent designs are selected with `dataclasses.replace(params, suite=..., icc=...)`. Every public suite revalidates parameters, which rejects mutated or manually constructed invalid values. No module globals carry implicit policy.
- **`load_params(path: Path | str, *, decision: DecisionManifest) -> SimulationParams`**: strict unknown-key rejection. The fixture schema is `firbench-simulator/v1`. Every generator, design and numeric acceptance value lives in the committed fixture. The author chooses and documents the nested key layout. Callers depend only on the schema and the acceptance report. The loader validates complete keys and values, an exact `p_d` match with the manifest, manifest policy, and supported suite and ICC values.
- **`simulate(params: SimulationParams, *, seed: int) -> tuple[firbench_frames.Frame, tuple[SearchRecord, ...], tuple[SearchRecord, ...]]`**: returns the frame and two record packets, control and planted. Each packet contains all three native `LegKind` values (`sface`, `auraface`, `insightface`), plus explicit attribution rows where the scenario needs them. They are not the two in-house legs. The records are the real immutable types that S3 consumes. Every mated GT face is present, including upstream misses. A null packet has equal marginal laws, not forced equal observations across legs. Control and planted packets share latent draws and face/PSU identities; only the declared treatment changes. No model inference and no real pixels.
- **Suites**: `run_null_suite`, `run_selection_control`, `run_coverage_suite`, `run_power_suite`, `run_noninferiority_suite`, `run_mde_suite`, `run_floor_suite`, `run_stage_suite`. Each has the signature `(params, *, replicates: int, seed: int)` and returns JSON-serializable `{'semantic': ROW, 'timing': {'seconds': number}}`. R=1 or other small counts are software checks and are marked `full_acceptance_evidence=false`. `run_power_suite` includes cell-only planting.
- **ROW keys**: `suite` (`null`, `selection`, `coverage`, `power`, `noninferiority`, `mde`, `floor`, `stage`), `icc`, `replicates_requested`, `replicates_completed`, `n_boot`, `seed`, `full_acceptance_evidence`, `design`, `metrics`, `passed`.
- **`design`** contains the mated `raw_n`, `n_psu`, `size_counts`, `sum_squared_sizes`, `size_weighted_mean`, `deff` and `attained_n_eff`. Image and non-mated source-unit sizing are separately named. Multi-design suites label each branch's own design. Each per-cell design includes its own floor, size and n_eff. No cell is claimed to reach 115.
- **Metric keys**:
  - `null`: `h1_superior_count` and rate; `h2_boundary_reject_count` and rate (the meaningful-400 branch).
  - `selection`: `h2_postselection_reject_count` and rate.
  - `coverage`: `psu_coverage_count` and rate; `image_coverage_count` and rate.
  - `power`: `h1_detect_count` and rate; `cell_only` with `clear_mask` and `clear_clear` counts and rates; exact planted and observed contrasts.
  - `noninferiority`: `equal_reject_count` and rate; `boundary_reject_count` and rate; `spanning_noninferior_count`.
  - `mde`: `refusal_count` and `noninferior_count`.
  - `floor`: `below_floor_reason`, `below_floor_interval_count`, `at_floor_passed`, `cell_below_floor_scored`.
  - `stage`: control and planted `missed` and `embedded_wrong` counts and rates, plus `embedded` counts; exact `drop_count`; `native_attribution_gaps`.
  - Additional keys: Monte Carlo standard errors, theoretical versus empirical discordance and ICC, and failure details.
- **`acceptance_report(results: Sequence[Mapping]) -> dict`** returns `{'semantic': {'schema': 'firbench-acceptance/v1', 'rows': [...], 'evals': {...}, 'full_acceptance_evidence': bool, ...}, 'timing': {...}}`. The semantic part is stable JSON for the same pinned implementation, protocol version, fixture, manifest and seed; identity across future protocol versions is not assumed. Timing is excluded from identity. AE-10 and real-data AE-5, AE-6 and AE-12 evidence stay pending unless supplied and verified separately. The report states which supplied suites ran. A partial, subset or small-R run never marks full acceptance passed. A suite that did not run is not a pass.
- **CLI**: `python -m scripts.eval_harness.firbench_selftest --params PATH --decision PATH --out PRIVATE_DIR [--replicates INT] [--seed INT] [--suites null,selection,coverage,power,noninferiority,mde,floor,stage]`. Defaults: fixture `R = 2000` and master seed `2208172209`. Full defaults run every required case. ICC 0.05, 0.10 and 0.20 run for null, coverage and power. Planning ICC 0.10 gates. 0.05 and 0.20 are report-only, and a failing sensitivity row is written as a finding. `--suites` supports independent remote shards with separate output directories. Never run two tests concurrently in one checkout. The CLI writes `acceptance.json` only below the canonical `benchmarks/private`. It never changes the decision, fixture or real inputs. Incomplete or failed evidence cannot return a full success claim.
- **Make target `fir-bench-acceptance`** invokes this CLI, then the actual AE-1 and AE-6 to AE-9 fixture modules only if the CLI succeeds. With the parallel CLI status correction, full numerical failure preserves JSON and returns nonzero, so make stops before fixture pytest; this documentation pass does not integrate that code fix. Fixture checks are separate from unsupported historical or real-data claims.

## Ownership and launch gate

- Two independent authors share this contract. S9-simulator owns `firbench_selftest.py` and `firbench_sim_v1.json`. S9-checks owns `test_eval_harness_firbench_acceptance.py` and `mk/evals.mk`. The latter follows S6a and then S6b.
- Tests may be RED until the other author's actual producer exists. Never substitute a fake for the simulator, the S0 gate, the S3 classifier, `decide` or the bootstrap.
- Use isolated native checkouts and separate basetemps. Run one test process per checkout, because fixtures write under `benchmarks/private`.
- Actual sources and the fixture are exchanged before the joined gate.
- Temporary RED test files on the VM are allowed for the simulator owner's TDD. Do not add unowned tracked paths.

## Build

1. **Parameters.** All simulator choices live in `firbench_sim_v1.json`, never in code:
   - PSU size distribution, in mated-face counts, declared per suite before outcomes. AE-2 and AE-3 default: face-count size-weighted mean M̃ ≈ 13. AE-4 uses the smaller distribution in Build 5. These are simulator choices, not the report's image-count M̃ = 12.925. The fixture records face-count and image-count values separately. S1 measures the real values.
   - ICC, default 0.10: the value of `DecisionManifest.planning_icc`, a design assumption and not an observed ICC. Sensitivity rows are in Build 10.
   - Target effective **mated searches** n_eff: 300 for the null suite, 115 for the power case, 400 for the H2 branch case. These are not PSU counts. For declared mated-face sizes m_j, compute raw n = Σm_j, M̃ = Σm_j² / Σm_j, deff = 1 + (M̃ − 1) × planning ICC, and n_eff = n / deff. Choose size counts before outcomes to attain the target and the global and cell PSU floors together. Report sizes, raw n, distinct PSU counts, deff and attained n_eff, globally and per tested cell. Integer sizing is disclosed, never hidden by rounding a materially larger n_eff down to the target. Keep the targets across ICC rows, recomputing size counts as needed.
   - Discordance `p_d`, default 0.15: equal to `DecisionManifest.p_d`, a design assumption and not observed. The suites read `p_d` from the manifest. A fixture value that differs refuses the run.
   - Per-leg base FNIR, default 0.15. Non-mated source-unit count: non-mated GT faces plus one background unit per image. Planted effects by pair cell and by stage.
   - Outcomes are generated per GT face from a PSU-level Dirichlet latent (Build 3), so the target ICC holds.
2. **Generator and seeds.** Master seed `2208172209` is the first 32 bits, big-endian, of SHA-256 `FIRBENCH-1/simulator/v1`. Derived suite, ICC and replicate seeds use a documented fixed integer registry with `SeedSequence`. Never use Python `hash()`, reseed until a pass, drop replicates, or tune parameters after results. The bootstrap seed `2429382368` and `n_boot` 10000 are manifest-owned and must equal the manifest values.
3. **Miss laws and PSU model.** Three-leg miss bits are ordered SFace, AuraFace, InsightFace (first bit is most significant). The eight patterns are in binary 000 to 111 order, with integer weights over 400:

   | Law | Weights (000 … 111) | Theoretical FNIR SFace, AuraFace, InsightFace | Pairwise discordance (all three pairs) |
   | --- | --- | --- | --- |
   | Null | 300, 10, 10, 20, 10, 20, 20, 10 | .15, .15, .15 | .15 |
   | H1 power / H2 equal | 285, 5, 5, 5, 25, 25, 25, 25 | .25, .15, .15 | .15 |
   | H2 boundary | 270, 0, 10, 0, 30, 20, 30, 40 | .30, .20, .15 | .15 |
   | Unsealed selection control | 280, 10, 20, 10, 20, 10, 20, 30 | .20, .20, .15 | .15 |

   The theoretical FNIRs and discordances above were recomputed with `Fraction` and match exactly.

   - PSU random logits are `log(Gamma(k·q))`, normalised with softmax. This is equivalent to Dirichlet probabilities. `k = 1/ICC − 1`.
   - Exclude exactly-zero `q` categories before drawing. Do not invent an epsilon probability.
   - Conditional on a PSU's probabilities, its images and faces draw patterns independently.
   - The Dirichlet covariance gives exact ICC1 = 1/(k+1) for each binary leg and every linear paired contrast. Prove this with `Fraction` oracles, and report the theoretical cross-leg covariance, not just the declared `p_d`. Do not claim a Gaussian-logit result.
   - Each mated GT face has one image identity. Several images per PSU, so image resampling is an actual pseudoreplication control.
   - Use the actual S1 PSU components and session metadata. Use the actual S3 `finish_outcomes`, `paired_cluster_bootstrap` and `decide`. Do not duplicate the statistical decision.
   - Preserve the global and cell floors, FPIR and full-GT rules.
4. **Paired control and planted packets.** Use ONE latent Dirichlet on a declared joint control and planted categorical law. Its marginal category weights are the table in Build 3. Drawing two independent Gamma vectors with the same seed is not a paired experiment.
   - **H1 power.** An exact monotone coupling: of the /400 null masses at `000, 001, 010, 011`, transfer `15, 5, 5, 15` respectively to `100, 101, 110, 111` in the planted packet. The resulting planted law is the H1 row of the table. Only the SFace miss bit changes. AuraFace and reference observations remain identical. Dirichlet aggregation preserves each packet's exact marginal law and ICC.
   - **Cell-only treatment.** Apply this coupling on clear→mask PSUs only. Clear→clear observations stay identical.
   - Declare any additional multi-arm coupling explicitly in the fixture before outcomes, and preserve the unchanged reference bit. Do not silently redraw comparator outcomes.
5. **Sizing and allocation.** Frozen integer sizes, calculated before outcomes. Each row was recomputed in this revision:

   | Suite / ICC | Size counts (size:PSU count) | raw_n | n_PSU | M̃ | n_eff |
   | --- | --- | --- | --- | --- | --- |
   | power / .05 | 1:59, 7:4, 8:3, 9:3 | 138 | 69 | 5 | 115 |
   | power / .10 | 1:46, 4:23 | 138 | 69 | 3 | 115 |
   | power / .20 | 1:26, 2:14, 3:9, 4:20 | 161 | 69 | 3 | 115 |
   | null / coverage / .05 | 1:96, 16:24 | 480 | 120 | 13 | 300 |
   | null / coverage / .10 | 11:30, 15:22 | 660 | 52 | 13 | 300 |
   | null / coverage / .20 | 11:37, 12:2, 13:12, 14:2, 15:27 | 1020 | 80 | 13 | 300 |
   | H2 / .10 | 1:176, 16:44 | 880 | 220 | 13 | 400 |

   - **Power allocation.** Allocate whole sorted PSUs alternately to clear→mask and clear→clear, 35 and 34 PSUs. For .10 this reproduces 23 singletons plus 12 four-face PSUs (71 faces) and 23 singletons plus 11 four-face PSUs (67 faces). Each cell meets the 30-PSU floor. Other ICC allocations are frozen in the fixture, satisfy both cell floors, and report actual cell n_eff.
   - **Background units.** Additional, independently known empty-GT images supply exactly 3000 total background source units, distributed over existing PSUs using session metadata. They create no new independent units and no detector-derived denominator. Their count does not increase the mated effective size. Non-mated GT-face count is 0 by synthetic design. Negative images are known synthetic empty images, not inferred from absent detections. Disclose image and non-mated M̃ separately. For the 49 and 50 PSU floor cases, keep all negatives in those same PSUs.
   - The 115 target is global. Report each cell's own n_eff and power, and never claim 115 for a cell.
   - The sizing arithmetic supplies no coverage or power evidence. Freeze the chosen distribution and allocation in the fixture before outcomes. An under-floor design cannot serve as AE-4 evidence, and oversampling to a higher effective size cannot be reported as the n_eff 115 gate.
   - Why the AE-4 distribution differs: near-equal 13-face PSUs at ICC 0.10 would reach n_eff ≈ 115 with only about 20 PSUs, failing the global 50-PSU floor.
6. **Suites.**
   - **`run_null_suite(params, *, replicates, seed)` (AE-2b).** A and B are identical in distribution. Reports:
     - (a) the rate at which `decide()` returns `superior` at step 1 (H1 at Δ = 0), with its Monte Carlo SE;
     - (b) the step-2 boundary rate: the rate at which step 2 rejects at Δ = δ with H1 forced to pass, with its Monte Carlo SE. The H2 leg is the one named in the manifest before the run.
   - **`run_selection_control`.** Both in-house legs at δ against InsightFace. The H2 leg is chosen after the run as the leg with the smaller estimate. Reports the step-2 boundary rate under that post-run choice, with H1 forced to pass, as in (b). It checks the fixture, not the tool: it shows that the fixture can detect the inflation an unsealed choice causes. The acceptance table fails the suite when the rate stays within the bound, because a fixture that cannot show the inflation proves nothing about sealing. The post-run choice is circular by construction (EXP-22).
   - **`run_coverage_suite` (AE-3).** Reports the fraction of replicates whose 95% interval covers the true Δ, for the PSU bootstrap and, on the same replicates, for the image-level bootstrap from `score_report.bootstrap_paired_delta`. The PSU is the independent unit (AUDIT-11; EXP-23).
   - **`run_power_suite` (AE-4).** Planted Δ 0.10 at n_eff 115 gives the H1 detection rate, reported against the planted and sizing alternative Δ 0.10 and power 0.80 (EXP-12). `alternativeDelta` = 0.10 is prose shorthand, not a manifest field. The decision margins stay the sealed `hypotheses[].margin` values, H1 0 and H2 0.05 (S0 Build 2; CARD-27). No minimum-effect field is added. The suite must also have at least 50 independent PSUs globally and at least 30 in every tested cell, including clear→mask and clear→clear. A cell-only effect gives per-cell detection. A stage defect gives the stage counts and the joint gaps against native.
   - **`run_noninferiority_suite` (H2 branches; S3 Build 6).**
     - (a) H1 planted at Δ 0.10; the H2 leg equal to InsightFace; n_eff 400. H2 rejects in at least 0.77 of replicates.
     - (b) H1 planted; the H2 leg at δ. H2 false rejection is measured with the same rule as `run_null_suite` (b).
     - (c) An H2 leg whose 90% interval spans δ gives `inconclusive`, never `non_inferior`.
   - **`run_mde_suite` and MDE refusal (Build 7).** At n_eff 300 and δ 0.05, a truly equal in-house leg gives `margin_unreachable_mde_gt_delta` for H2 in every replicate, and never `non_inferior`.
   - **`run_floor_suite`.** Item 9 below.
   - **`run_stage_suite`.** Item 8 below.
7. **Acceptance report and CLI.** `acceptance_report(results)` gives pass or fail per AE with the numbers, written to the run directory. `make fir-bench-acceptance` runs the simulated suites, with replicates from the fixture (default 2000), then the fixture evals (AE-1, AE-6 to AE-9 test modules) only on CLI success. With the parallel CLI status correction, full numerical failure leaves the JSON available and stops make before fixture pytest. Every full replicate uses `DecisionManifest.interval.n_boot` (10,000). Never reduce full replicate or bootstrap counts, stop early, or drop failing replicates to force a pass.
   - Use chunked or vectorised paired PSU sufficient statistics (weighted miss totals and denominators per PSU, leg and cell) where needed. Preserve the paired PSU resampling, the face-weighted estimand and the declared seeded draw order. Bound memory by bootstrap chunks, not by materialising all face rows for every draw. Preserve image-level resampling for the coverage comparator.
   - The report records requested and completed replicate and bootstrap counts. Its `semantic` part is byte-identical across reruns with the same pinned implementation, protocol version and inputs; this is not an identity claim across future versions. Its `timing` part records runtime and is excluded from identity.
   - The simulator's semantic branch reads no timings receipt and carries no receipt SHA or p95 state. The full AE runner still executes the receipt-dependent AE-7 score and report checks. Byte replay requires the same pinned receipt, and changed timing evidence must be able to change the real veto (MCP 16777, FLOW-18).
   - AE-10 is not computed here (see the pass-rule table).
8. **Stage planting.** A predeclared `floor(0.10 · n_mated)` upstream detection drops, stratified between the already generated embedded-correct and embedded-wrong classes, with the integer rounding disclosed. The drops are shared between the in-house native arms and leave reference and latent identities fixed.
   - Actual `finish_outcomes` and stage counts must show exactly those new missed rows.
   - Both separable attribution arms restore baseline on the same GT IDs. InsightFace attribution remains `unavailable_fused`.
   - Embedded wrong-identity rate, control versus planted absolute difference ≤ 0.05. Use the actual paired-gap implementation where applicable. No fabricated cached outcomes or intervals.
   - Cell-only planting changes only the predeclared clear→mask PSUs and keeps clear→clear identical. Report both cell detection rates and contrasts, without claiming the global 115 applies to either cell alone.
9. **Eligibility floors (MCP 16736).** Before any FPIR eligibility or interval, each replicate counts distinct independent PSUs. Fewer than `DecisionManifest.min_n_independent` (50) gives `inconclusive` with `InconclusiveReason.insufficient_independent_psus`, and no interval is computed. A pair cell with fewer than `cell_floor_n_independent` (30) independent PSUs is not scored. The AE-4 cell-only check is valid only where its cell passes that floor. These floors are project policy and prove no adequacy: power, MDE, FPIR resolvability and exhaustive GT still gate separately. Consume S0's frozen `min_n_independent`, `cell_floor_n_independent`, `p_d` and `InconclusiveReason.insufficient_independent_psus`. Do not redefine them locally.
10. **Planning ICC sensitivity.** AE-2, AE-3 and AE-4 also run at planning ICC 0.05 and 0.20 with the same stated n_eff. These rows are reported beside the 0.10 rows. They are not gated. A failing sensitivity row is written as a finding. It does not change the 0.10 gate or the pass rules.
11. **Numeric comparison rules.** These apply to every check the target runs, including AE-1 and AE-6 to AE-9.
    - Counts are integers compared with `==`, with no tolerance.
    - An analytic rate's oracle is a `fractions.Fraction`. The float output must satisfy `abs(value - float(oracle)) <= 1e-12`. That is the only tolerance in this lane. AE-1's "no tolerance" holds on the oracle side: the Fraction is exact, and the 1e-12 bound covers float rounding only.
    - Monte Carlo rates are never compared with a tolerance. They are judged by the bounds in the pass-rule table.
12. **Coverage comparator (B = 10000).** The coverage suite calls the actual `score_report.bootstrap_paired_delta` on the same replicate image arrays, with `B=10000` passed explicitly. It also calls the actual PSU interval with the manifest `n_boot`.
    - A measured performance problem is reported with timings before any optimisation.
    - No smaller B, no alternate lookalike comparator, no vectorisation that changes draw order, no silent fast backend, and no mocked method.
    - Every full case uses all 2000 replicates and 10,000 draws. Requested and completed counts, and any omitted cases, are explicit.
    - Failures become findings, not new pass limits.
    - The deliberately broken interval (image-level bootstrap on a clustered fixture at ICC 0.3) is a separate declared negative-control case with multiple images per PSU, not a gated sensitivity row.
    - **Measured pre-run exception (declared).** The actual image comparator at n = 660 and B = 10000 took 23.590922 s at 0.25 CPU for one replicate, projecting 13.1 h for 2000 replicates at that allocation. This is a prior measurement, not re-run in this revision. The draw loop calls `rng.randrange` once per resampled unit, so `k` calls per replicate (`score_report.py:245–252` in the earlier tree). The 2026-10-15 author audit found the reuse path present in its checked tree (`score_report.py:317–347`); the original loop remains the fallback (`score_report.py:263–266`).
    - Owner `S9-comparator-perf` (an independent owner) implements bounded reuse of the identical `random.Random(seed).randrange(n)` draw counts for repeated `fixed(n, B, seed)` binary-mean calls, with parity tests against the actual function.
    - S9 may use that accepted implementation of the same public comparator if and only if its parity, source and memory gate passes.
    - Every replicate still evaluates all 10,000 statistics with the same logical draws, order, quantiles and return fields. No new RNG, reduced count or changed estimand. All other modes retain the original slow fallback.
    - Cold draw construction and warm repeated timing are reported explicitly. This declared, measured optimisation is not the silent alternate-backend exemption prohibited above.
13. **Decision branches and negative controls.**
    - Record the H1 hypothesis state and the overall state. Overall H2 ineligibility is not a reason to drop H1 rows. The AE-2 required 300 case stays, including the actual H2 MDE refusal.
    - The meaningful H2 boundary and selection control uses the already reviewed 400 H2 design (n 880, 220 PSUs). The .05 margin and the .060 false-positive bound are unchanged.
    - Every boundary H1-forced case changes ONLY the nonselected in-house arm. If the H2 leg is AuraFace, make SFace all miss. If the H2 leg is SFace, make AuraFace all correct. The selected arm and the reference observations are preserved. Real `decide` is invoked, and the assertion is that H1 passes without discarding any replicate.
    - **Selection control (INVALID postselection).** Selection deliberately chooses the smaller estimate before the H1 forcing. It is a labelled INVALID postselection negative control. The selected H2 leg uses a separately self-consistent synthetic decision. The actual product never allows postselection or unknown H2.
    - **Synthetic decisions.** Use synthetic-only, correctly hashed and sealed S0 decisions derived from the supplied statistical policy:
      - correct generated frame and template hashes;
      - literal synthetic reference and timestamps;
      - unchanged margins, alpha, bootstrap, floors, `p_d` and FPIR;
      - every required real S0 validator.
      - Include a named, report-only simulation-scope guardrail with a non-null declared rule. No fabricated p95 measurements and no veto passes. NEVER mutate or ratify the real decision manifest. This tests the inference mechanism. The full AE-7 and AE-9 real CLI fixture tests still exercise the actual receipt-dependent veto behaviour and fail-closed unscored guardrails.
    - **H2-spanning branch.** A fixed 880-face design with 220 PSUs (176 singletons and 44 sixteen-face PSUs). Each sixteen-face PSU has 2 positive contrasts (H2 miss, reference correct), 1 negative (H2 correct, reference miss), 2 both-miss and 11 both-correct. All singletons are both-correct. This gives H2 misses 176/880 = 0.20, reference misses 132/880 = 0.15, discordance 132/880 = 0.15 and delta 0.05 (verified arithmetic). The actual 10,000-draw 90% interval must span the margin, and no bounds are fabricated. H1 is forced with the same unchanged mechanism. Report the actual interval and state.
    - **MDE branch clarification (MCP 16945).** `run_mde_suite` also forces H1 with the same declared synthetic mechanism and preserves equal H2 and reference observations. A finite planted H1 effect has power below 1 and sometimes stops before H2. Those replicates are never dropped and H2 state is never fabricated. Ordinary power and noninferiority suites retain the actual H1 probability. No gate, count or seed changes, and no simulated pass is inferred.
14. **Policy and source record.** Each value is recorded with its status. Policy values are declared project choices, not canon constants.

    | Value | Status | Basis | Recomputed or measured here | Unresolved |
    | --- | --- | --- | --- | --- |
    | Planning ICC 0.10; sensitivity 0.05, 0.20 | Policy; design assumption, not observed | `DecisionManifest.planning_icc`; MCP 16733 | Manifest value matches | Observed ICC |
    | Design effect deff ≈ 1 + (M − 1) × ICC | Source-established | AUDIT-11 | Size table arithmetic | Empirical deff of a run |
    | Face-count M̃ ≈ 13 (AE-2, AE-3); AE-4 distribution; image-count M̃ = 12.925 | Simulator choices; historical report figure | Items 1 and 5; S1 measures the real values | Table arithmetic | Real frame values |
    | Discordance `p_d` 0.15; power 0.80 | Policy; design assumption, not observed | `DecisionManifest.p_d`, `power`; FIRBENCH-1-scope, Power; EXP-12 | Manifest values match | Observed discordance |
    | Sizing and planted alternative Δ 0.10 (prose `alternativeDelta`; no manifest field) | Policy; planted and sizing only | FIRBENCH-1-scope, Power; EXP-12 | Not a field | MDE is computed, not declared |
    | Hypothesis margins: H1 0, H2 0.05 | Sealed before the run | `hypotheses[].margin`; S0 Build 2; CARD-27 | Manifest values match | Seal (null) |
    | One-sided α 0.05; nominal 0.025 and 0.05 | Policy | `alpha_family`; AE-2 | Manifest value matches | — |
    | Standard errors sqrt(p(1 − p)/R), R = 2000: 0.00349, 0.00487, 0.00894 | Source-established arithmetic | AE-2, AE-4 | Recomputed | — |
    | Tolerances 2 MC SE (AE-2), 3 SE (AE-4) | Policy | Pass-rule table | Recomputed thresholds | — |
    | Bound 9 of 200 (95% upper quantile of Binomial(200, 0.025)) | Computed; carried in the fixture | Build RED tests | Recomputed: P(X ≤ 8) = 0.9344, P(X ≤ 9) = 0.9700 | — |
    | Eligibility floors: 50 PSUs globally, 30 per pair cell | Policy; not canon-prescribed; prove no adequacy | MCP 16736 | Manifest values match | Adequacy |
    | Master seed 2208172209 | Declared packet value | Build 2 | Derivation recomputed | — |
    | Bootstrap seed 2429382368; `n_boot` 10000 | Manifest-owned | `interval.seed`, `interval.n_boot` | Manifest values match | — |
    | Coverage comparator `B` = 10000 | Declared | Build 12 | Default in source is 2000 (`score_report.py:53`); S9 passes 10000 | Per-case coverage runtimes recorded in the report (§3); no separate timing study |
    | Comparator reuse | Declared, measured exception | Build 12; prior timing receipt | Present in the checked tree (`score_report.py:317–347`; parity tests in `scripts/bench/tests/test_firbench_bootstrap_reuse.py`) | Parity-gate result and reuse timings are not in the canonical JSON |
    | Miss-law weights and couplings | Declared packet values | Build 3 and 4 | Fraction oracle arithmetic | Empirical law |
    | Interval on delta; A/A before A/B; no circular selection; count the independent unit | Source-established | EXP-12, EXP-13, EXP-22, EXP-23 | — | — |

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
| Eligibility floors (Build 9) | Fewer than 50 distinct PSUs gives `insufficient_independent_psus` with no interval. Pair cells below 30 PSUs are not scored. |
| ICC sensitivity (Build 10) | Rows at 0.05 and 0.20 are reported beside the 0.10 gate. They are not gated. |
| AE-10 (coordinator-recorded; not run by S9) | The read-only laptop static scan records the alias-map hit count (pass: 0), scanned paths and scope, the scan's code SHA (must equal the run SHA), and the scanner implementation SHA and digest. The scanner digest identifies the scanner; it is distinct from the scanned code and run SHA. The alias map never goes to the VM or any lane, and no S9 code or fixture reads it. The branch-diff checks are as written in the plan's AE-10 row. Missing laptop evidence stays pending, never passed by a VM substitute. |

## RED tests (small replicate counts for CI speed; not full acceptance evidence)

The acceptance modules are present in the checked tree: `test_eval_harness_firbench_acceptance.py` (34 test functions) and `test_eval_harness_firbench_acceptance_reporting.py` (5). Function names cover the replay, negative control, 9-of-200, loader and floor/refusal cases below; the Build 3 Fraction oracles and ICC1 covariance checks were not located by name in these modules. Software checks completed (coordinator-recorded, not re-run in this documentation pass); this is not a claim that every declared obligation below is verified. The full v6 baseline **FAILED numerically**. See the [report §8](../../../../benchmarks/reports/firbench-1-simulation-v6-20261015.md#8-assembly-and-software-notes) for recorded checks and [§4](../../../../benchmarks/reports/firbench-1-simulation-v6-20261015.md#4-gated-checks) for the failed baseline.

- With 50 replicates and a fixed seed, the simulator semantic results are byte-identical across two runs. The `timing` part is excluded. This check does not exempt the full AE runner from AE-7's pinned-receipt checks (Build 7).
- A deliberately broken interval (the image-level bootstrap on a clustered fixture at ICC 0.3) fails the coverage rule. This proves the check can fail.
- A planted Δ of 0 gives `superior` in at most 9 of 200 replicates with a fixed seed. The bound 9 is the 95% upper quantile of Binomial(200, 0.025), and it is written in the fixture, not in code.
- The fixture loads and rejects unknown keys.
- The numeric rule (Build 11): a count off by one fails. A float rate 1e-13 from its `Fraction` oracle passes, and one 1e-9 away fails.
- A 49-PSU fixture gives `insufficient_independent_psus` with no interval. A 50-PSU fixture passes the floor. A fixture whose `p_d` differs from `DecisionManifest.p_d` refuses the run.
- The miss-law Fraction oracles (Build 3) and the exact ICC1 = 1/(k+1) covariance (Build 3) are proven by tests, not by this document.
- The joint coupling preserves each packet's marginal law and ICC (Build 4).

## Done when

Tests pass on the VM, using the command in the firbench-1 README with isolated basetemps and one test process per checkout. The full `make fir-bench-acceptance` (2,000 replicates, full manifest bootstrap count in each replicate) result is reported with its runtime and the attained sizing and floor counts. Runtime goes in the report's `timing` part, not the semantic part. The result is recorded as a `test_result` at HEAD by the run's recorder. AE-10 is recorded separately, and the S9 report does not mark it passed. Synthetic suite results do not supply real GT exhaustiveness, human observation or ratification evidence.

**Status (2026-10-15): not met.** Software checks completed. The full run failed numerically at AE-2b step 2 (H2 boundary, 0.063 against ≤ 0.060) and at AE-4 cell-only power (clear→mask, 0.5565 against the stronger frozen fixture bar of 0.77; the original plan remains qualitative). AE-10 and real-data evidence are pending. Details are in [`benchmarks/reports/firbench-1-simulation-v6-20261015.md`](../../../../benchmarks/reports/firbench-1-simulation-v6-20261015.md).

## Policy, measured and unresolved

| Item | Policy (declared) | Measured here | Unresolved |
| --- | --- | --- | --- |
| Simulator | Declared contract (this brief) | Implemented in the checked tree; software checks completed (coordinator-recorded); full v6 run numerically FAILED (report) | Full AE pass; real-data gates; run-revision alignment |
| Sizing and floors | Declared before outcomes | Arithmetic checked; frozen v6 attained n_eff and PSU counts recorded in [report §2–3](../../../../benchmarks/reports/firbench-1-simulation-v6-20261015.md#2-configuration) | Real-frame sizing and adequacy |
| Miss laws and couplings | Declared packet values | Fraction oracle arithmetic | Empirical law of any run |
| Coverage and power | Original declared thresholds unchanged; fixture cell bar ≥ 0.77 is stronger than the qualitative plan | Frozen v6: PSU coverage 0.9445 PASS; global H1 power 0.837 PASS; cell-only power 0.5565 FAIL under fixture; overall numerical acceptance FAILED (AE-2b boundary 0.063 also FAIL). [Report §4](../../../../benchmarks/reports/firbench-1-simulation-v6-20261015.md#4-gated-checks) | Failed baseline unresolved; prospective cell-120/studentized-bootstrap proposals are not implemented or validated; real-data evidence pending |
| Real decision | Committed manifest, unratified and unsealed | Values match the policy | Ratification, seal, budget |
| Real GT, observation and ratification | — | — | All unestablished; S9 supplies none. Exhaustive GT must be detector-independent (MAINT-FIR-DETECTION-20260919, prior art; not located in this tree). |
