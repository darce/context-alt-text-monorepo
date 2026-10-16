# FIRBENCH-1 cell-only power design: v7 prospective proposal

**Status: proposal and evidence artifact. Not a frozen protocol, not an implementation, not acceptance.**
No outcome has been run for this design. Nothing here is a pass, a winner, or real-data evidence.
It is not an amendment to v6. Frozen v6 numerical acceptance remains **FAILED** (see [the v6 report](../reports/firbench-1-simulation-v6-20261015.md)), and its failed cell row is retained, not replaced.

The design is a candidate for review. It must be frozen in a separate reviewed revision, with its implementation, seeds and checks, before any replicate is drawn.

## 1. Question and non-claims

Question: how many independent PSUs and effective mated searches should a cell-only H1 check have, so that a planted within-cell effect of 0.10 is detectable at the sealed power, without changing the v6 global law, design family, or gate thresholds?

Non-claims:

- No full or new Monte Carlo run, no tuning of seeds, thresholds, bootstrap count (B) or replicate count (R), and no search for a passing size.
- The sizes below come from analytic planning arithmetic, fixed before outcomes.
- Canon sets no numeric project default. The 0.80 power, 0.10 effect, 0.77 empirical bar, 0.032 null bar, and 30-PSU cell floor are project policy carried from the tracked S9 brief and v6 fixture, not canon constants.
- No real images, real models, real ground truth, quality control, human observation, or capture-occasion evidence is involved.

## 2. Lineage (walkable)

Each claim below points to its parent. Pinned external context is named by basename and hash only; it is not tracked.

| Node | Source (tracked path or pinned basename) | Pin | What it establishes |
| --- | --- | --- | --- |
| Failed v6 run | `benchmarks/reports/firbench-1-simulation-v6-20261015.md` §1–4 | source `2ff389e7`, tree `943a9131`; acceptance SHA-256 `809b2ed1…51183` | 15 unique cases at R=2000, B=10000. AE-4 cell-only clear→mask 1113/2000 = 0.5565 < 0.77 fails. AE-2b step 2 also fails. |
| Gate wording, qualitative | `docs/tasks/firdv/firbench-1/S9-acceptance.md`, AE-4 row and Build 5 | tracked | Original plan: the cell-only effect is "detected in its own cell", with no numeric bar. |
| Gate wording, numeric | v6 fixture `apps/prototype-description-service/scene/tests/fixtures/firbench_sim_v1.json`, `acceptance.cell_clear_mask_min_rate` (0.77), `acceptance.cell_clear_clear_max_rate` (0.032), `acceptance.cell_clear_mask_rule_note` | tracked | Numeric cell bar, declared as the frozen interpretation of the plan. |
| Cell-power diagnosis | external diagnosis patch, basename `S9-cell-power-adj.patch` (hash not recorded here) | external, not tracked | Sizing mismatch: clear→mask n_eff 59.03 (35 PSUs). Concludes no algorithm fault was found in the audited path. Proposes a 120-per-cell candidate with analytic MDE 0.098081. The candidate is not validated. |
| Decision manifest | `benchmarks/manifests/fir-bench-decision-v1.json` | tracked | `planning_icc` 0.10, `p_d` 0.15, `power` 0.80, `alpha_family` 0.05, `min_n_independent` 50, `cell_floor_n_independent` 30, interval `n_boot` 10000 and `seed` 2429382368. Ratification and seal are null. |
| Simulator and scorer | `apps/prototype-description-service/scripts/eval_harness/firbench_selftest.py`; `firbench_score.py` | tracked | Code anchors in §4. |
| Canon | release manifest `heuristics-canon` 0.26.2 (date 2026-10-14); lexicon rows in §10 | pinned read-only mirror | Rule mechanisms, cited by stable ID with locators. |
| Supplement | `margin-and-design-effect-before-the-run.md` (CARD-27), SHA-256 `186c94c2…85aad` | external supplement, matches the S9 brief | Pre-sealing of margin, method class, harm direction and α; n_eff from design effect. |

## 3. What v6 established, and what it did not

Measured (from the tracked report and the fixture; the 2000-replicate counts are the v6 canonical rows):

| Quantity | v6 value | Note |
| --- | --- | --- |
| Global H1 detect, planted 0.10 at n_eff 115 | 1674/2000 = 0.837 | Passes the 0.77 bar. |
| Cell clear→mask detect (planted 0.10 in this cell only) | 1113/2000 = 0.5565 (MC SE 0.0111) | Fails the 0.77 bar in the fixture. |
| Cell clear→clear detect (no planted effect) | 45/2000 = 0.0225 | Null-like, below the 0.032 bar. |
| Cell clear→mask design | 71 faces, 35 PSUs (23 size-1, 12 size-4); n_eff 59.028103 | Recomputed exactly here. |
| Cell clear→clear design | 67 faces, 34 PSUs (23 size-1, 11 size-4); n_eff ≈ 55.97 | Computed here from the frozen composition. |
| Global design | 138 faces, 69 PSUs (46 size-1, 23 size-4); n_eff 115.0 | n_eff is an integer target rounded from the requirement in §4. |

What this does and does not establish:

- The failure is a sizing mismatch under the frozen numeric interpretation. The cell is underpowered at its own n_eff (≈59), so a cell-only pass at the global 115 target does not follow from the global pass at 0.837.
- The global 0.837 does not prove cell power, because the cell design is a different sample.
- The v6 sizing does not reach the bar even at the global level. Analytic MDE at n_eff 115.0 is 0.100148, just above 0.10. The rounded target sits at the requirement, so this was a disclosed integer choice, not a margin.
- The v6 cell rows stay FAILED. A v7 pass would be a new prospective run, not a rescue of AE-4.

Preserved distinction: the original plan's AE-4 clause is qualitative ("detected in its own cell"). The fixture's 0.77 is a stronger numeric bar, declared later as an interpretation. This proposal carries 0.77 forward as a **new prospective pre-registration** for the cell-only fixture. It does not claim the original plan contained that number.

## 4. Diagnosis read from source (verified by reading, not re-run)

| Behaviour | Anchor | Consequence for v7 |
| --- | --- | --- |
| Per-cell H1 uses the real paired PSU bootstrap, `lower > 0.0`, `level=0.95`, `n_boot` and `seed` from the manifest. It returns `False` below the 30-PSU floor. | `firbench_selftest.py:1457` (`_cell_decision`) | Reused in v7, but must be checked against the real `decide` route (§8). |
| Cell-only power counts every replicate for both cells, with no conditioning on global H1 or H2 state. | `firbench_selftest.py:1537` (`_cell_only_power`) | Keep: unconditional counts avoid selection. |
| Ordinary H1 power uses unforced real `decide` calls. The explicitly declared conditional H2 boundary/spanning/MDE controls force H1 to reach H2; `run_selection_control` also forces H1, but is labelled INVALID because it selects the H2 leg after observing estimates. | `firbench_selftest.py:1491–1495` (ordinary power), `1281–1289` (`_null_branch_b`), `1592–1600` (boundary/spanning), `1638–1652` (`run_mde_suite`), `1351–1389` (`run_selection_control`) | Keep these controls separate from unconditional cell H1; none rescues the original failed v6 H2 0.063 or cell 0.5565 rows. [GRPH-14], Record provenance as a walkable lineage graph (*Building Knowledge Graphs*, ch. 8; *Mental Models*, ch. 8). |
| Interval: face-weighted FNIR(SFace) − FNIR(AuraFace), resampling whole PSUs. | `firbench_score.py:650` (`paired_cluster_bootstrap`) | Interval class is sealed as-is. |
| Single decision rule with Holm steps and eligibility gates. | `firbench_score.py:844` (`decide`) | Real route for the cell check (§8). |
| Step-1 level is 1 − 2·α₁, with α₁ = α_family/(K) = 0.025, so level 0.95. | `firbench_score.py:768–777` (`_one_sided_alpha`, `step_levels`) | Matches the `level=0.95` used in `_cell_decision`. |
| Effective n uses design effect from mated sizes: deff = 1 + (M̃ − 1)·ICC, M̃ = Σm²/Σm, n_eff = n/deff. | `firbench_score.py:781–791` (`_design_effect`, `_n_eff`) | Same formula used in §5. |
| Minimum detectable effect: smallest Δ with [z_a√p_d + z_b√(p_d − Δ²)]²/Δ² ≤ n_eff. | `firbench_score.py:735` (`minimum_detectable_effect`) | Same formula used in §5. |
| Ratified decision for simulation comes from the fixture's `synthetic_decision`, not the unratified canonical manifest. | `firbench_selftest.py:713` (`_synthetic_decision`); fixture key `synthetic_decision` | Keep the same route. Canonical verdicts stay unratified. |
| Cell allocation: sort PSUs ascending by mated size (ties by PSU id), even-indexed to clear_mask, odd-indexed to clear_clear. | fixture `designs.cell_allocation_rule`; `firbench_selftest.py:559` | Keep for v7 because it reproduces the 2:1 composition exactly (§5). |

No code fault was found in the paths read here, and the diagnosis reports the same. It attributes v6 AE-4 to sizing, not to the simulator or scorer.

## 5. Analytic sizing (computed here; no outcomes)

Inputs, all from the manifest or the tracked brief: δ = 0.10 (planted effect), p_d = 0.15, power 0.80, one-sided α₁ = 0.025 (step-1 level), planning ICC 0.10.

Requirement, using the same formula as `minimum_detectable_effect`:

n_req = [z₀.₉₇₅·√0.15 + z₀.₈₀·√(0.15 − 0.10²)]² / 0.10² = **115.3469** (exact formula; z values from the standard normal).

Per-cell block, the composition from the global design (2 size-1 PSUs : 1 size-4 PSU), so the 2:1 fraction is preserved:

- One block = 2 PSUs of size 1 and 1 PSU of size 4: raw 6, PSUs 3, Σm² 18, M̃ = 3, deff = 1 + 2·0.10 = 1.2, n_eff = 5.
- k blocks per cell: raw 6k, PSUs 3k, Σm² 18k, M̃ = 3, deff 1.2, n_eff 5k exactly.

| Blocks per cell (k) | n_eff @ ICC 0.10 | Slack vs n_req | MDE @ 0.10 (α₁ 0.025) | Analytic power @ 0.10 | Raw/PSU per cell | n_eff @ ICC 0.20 | ICC break-even |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 24 | 120 | +4.0% | 0.098081 | 0.816 | 144 / 72 | 102.9 | 0.124 |
| **26 (candidate)** | **130** | **+12.7%** | **0.094305** | **0.846** | **156 / 78** | **111.4** | **0.176** |
| 28 | 140 | +21.4% | 0.090933 | 0.872 | 168 / 84 | 120.0 | 0.228 |

ICC break-even is the planning ICC above which the design falls below n_req, with the same composition. The k = 24 row reproduces the diagnosis's "120 per cell" candidate exactly.

Chosen rule (a reviewer decision, stated so it can be checked): choose the smallest k with n_eff ≥ 1.10 × n_req. Here 1.10 × 115.3469 = 126.88, so 5k ≥ 126.88 gives **k = 26**. This 10% margin is a proposal choice. It buffers planning-ICC uncertainty and the normal-approximation planning formula, which is not a validated bootstrap power. It is not a canon value.

Empirical context, two points only, not a rule: the v6 empirical rate exceeded the analytic normal value by +0.038 at global n_eff 115 (0.837 vs 0.799) and by +0.047 at cell n_eff 59 (0.5565 vs 0.510). These offsets do not validate the candidate. They are read only as a reason to expect no large deficit, and §11 treats the empirical gate as unverified.

## 6. Candidate design C26 (proposal, not frozen)

Per cell: **52 PSUs of size 1 and 26 PSUs of size 4.** Raw 156, distinct PSUs 78, Σm² 468, M̃ 3, deff exactly 6/5, n_eff exactly 130. Both cells get the same composition.

Total cell-only fixture: 156 PSUs, 312 faces. The global floor (50 PSUs) and per-cell floor (30 PSUs) are both met with headroom. These floors are eligibility gates, not adequacy proof.

Allocation: all 156 PSUs sorted ascending by mated size, ties by PSU id. The first 104 are size-1, the last 52 are size-4. Even-indexed PSUs go to clear_mask and odd-indexed PSUs go to clear_clear, as in `cell_allocation_rule`. This reproduces 52 + 26 per cell. Whole PSUs only, no relabelled faces.

Independence: the cell-only fixture is a separate fixture and seed identity. It does not reuse the v6 global design, and the v6 global 69-PSU design is not changed.

## 7. Distribution, coupling and controls (unchanged law)

- PSU model: Dirichlet-equivalent latent per PSU, implemented as in v6, with ICC 0.10 and k_dir = 1/ICC − 1 = 9. Each PSU's probabilities are drawn once, and its faces draw patterns independently given that PSU.
- Miss-law weights over 400 (binary bits SFace, AuraFace, InsightFace, first bit most significant), from the S9 brief Build 3:
  - null: 300, 10, 10, 20, 10, 20, 20, 10 (000 … 111);
  - H1 power planted law: 285, 5, 5, 5, 25, 25, 25, 25.
- H1 coupling (from the S9 brief Build 4): transfer 15, 5, 5, 15 of the null masses at 000, 001, 010, 011 to 100, 101, 110, 111. Only the SFace bit changes; AuraFace and reference observations stay identical. The coupling preserves each packet's marginal law and ICC.
- **Cell-only treatment:** apply the coupling only to clear_mask PSUs. clear_clear observations stay identical to the control packet.
- **Cell control unchanged:** the unplanted control packet keeps the null law on both cells. The global H1 power row and its planted law are not modified or re-run.

## 8. Decision route and interval class (sealed before run)

The following is a prospective adapter requirement, not an implemented route or an observed result. It keeps the whole-fixture eligibility domain separate from the cell H1 estimand; neither manifest floor changes.

- Interval class: percentile paired PSU bootstrap of FNIR(SFace) − FNIR(AuraFace) on the same mated faces, resampling whole PSUs, with `n_boot` = 10000 and the manifest seed `2429382368`. Level 0.95, as step 1 gives (§4). Keep every bootstrap replicate. Cell H1 is superior iff its interval lower bound is greater than the sealed H1 margin, 0; H2 interval proposals do not change this class.
- Manifest input: use the same fixture `synthetic_decision` construction (`firbench_selftest.py:713–745`) for the whole cell-only fixture, with H2 declared as AuraFace versus InsightFace. Retain `min_n_independent=50`, `cell_floor_n_independent=30`, and the existing FPIR target and planning ICC. Its `SIM-G0` guardrail has role `report_only`; it supplies no measured veto reading. This synthetic mechanism establishes no real-data ratification or seal.
- Full `LegResults` input: start with `_results(design, decision, packet, auraface)` (`firbench_selftest.py:1139–1156`). Keep `frame=design.frame.spec` for the whole fixture; keep `unit_psu_ids=packet.background_psu` with every existing background source unit, in its original order and multiplicity; keep `h2_leg=auraface` and `guardrails={}`. Empty guardrail readings are appropriate to the synthetic report-only marker, not a measured pass. Do not filter background units to the cell, add nonmated units, or substitute mated faces for nonmated source units.
- Cell `legs` input: retain all three keys, `sface`, `auraface`, and `insightface`, each with its matching `LegArrays.leg`. Restrict each array to the identical ordered cell mated `face_ids` from the packet, preserving each face's leg-specific `outcomes`, `psu_ids` and `weights`. Use the existing synthetic weight 1.0 for every face. Assert identical face IDs, PSU assignments and weights across all three arrays; keep all cell mates, including upstream misses, without filtering by outcome. Only the mated arrays are cell-restricted. These are the complete `LegResults` fields (`firbench_score.py:108–150`).
- Whole-fixture eligibility: count the union of retained background `unit_psu_ids` and all restricted leg `psu_ids`, exactly as `decide` does (`firbench_score.py:861–874`). Assert that the existing round-robin background assignment covers every whole-fixture PSU, so that this union equals the whole-fixture PSU set (`firbench_selftest.py:580–586`). Require at least 50 distinct PSUs. Separately require whole-fixture nonmated `n_eff` from the complete background tuple to satisfy `fpir_resolvable`, i.e. at least `3 / fpir_target` (300 at target 0.01; `firbench_score.py:547–551`). The whole-frame field alone does not supply those PSU counts. Neither background count nor global `n_eff` is the cell's mated power denominator.
- Adapter order and output: validate the declared inputs, then apply the unchanged global PSU gate, then FPIR resolvability, then the separate cell count from distinct cell mated PSUs. Below 30 cell PSUs, do not call `decide`: return `scored=false`, no H1 interval, `reason=insufficient_independent_psus`, with adapter metadata `eligibility_scope=cell`. A global floor refusal uses the same reason with `eligibility_scope=whole_fixture`; an FPIR refusal uses `primary_fpir_unresolvable` with that whole-fixture scope. These scope labels are proposed adapter metadata, not new scorer reason enums. On eligible inputs, pass the complete mixed-scope `LegResults` above to the real `decide`, which retains its own eligibility checks (`firbench_score.py:844–945`), and read the H1 hypothesis row alone. `scored=true` means its interval exists; detection means its state is `superior`. An H1 non-rejection still has an interval and counts as scored. Never condition the H1 count on overall verdict, global H1, H2 state, H2 MDE or H2 interval presence; never force H1 for this route.

Boundary expectations below assume the declared synthetic manifest and valid paired inputs. At global 50, FPIR must also be resolvable; for global 49 the global floor takes precedence. These are requirements for future deterministic checks, not executed observations.

| Whole-fixture distinct PSUs | Cell distinct mated PSUs | Adapter scored / H1 interval | Refusal reason and scope |
| --- | --- | --- | --- |
| 49 | 29 or 30 | false / absent | `insufficient_independent_psus`, `whole_fixture` |
| 50 | 29 | false / absent | `insufficient_independent_psus`, `cell` |
| 50 | 30 | true / present | No eligibility refusal; H1 non-rejection may have state `inconclusive`, reason null, with its interval retained. |
| ≥50, FPIR unresolvable | 29 or 30 | false / absent | `primary_fpir_unresolvable`, `whole_fixture` |

- Parity domain: compare `_cell_decision` with the adapter's real-`decide` H1 interval only on known-answer packets with whole-fixture ≥50 PSUs, resolvable whole-fixture FPIR, cell ≥30 PSUs, the declared synthetic report-only guardrail, and identical ordered cell faces, PSU IDs, outcomes, unit weights, seed, B and level. Require exact interval equality (including both bounds) and the same H1 detection boolean. `_cell_decision` lacks the global eligibility gates, so interval parity outside this domain is not required; check the adapter refusals separately. This follows the distinct whole-fixture and cell floors in `firbench_score_io.py:508–526`, without claiming that `_cells` itself enforces FPIR resolvability or runs paired H1.
- Harm direction, fixed prospectively: clear_mask power protects against a false negative (an undetected cell-specific miss-rate defect); clear_clear's null bar protects against a false positive (a cell-specific claim without a planted cause). These are synthetic H1 detection harms, not a real-data FPIR qualification. [FAIR-04], Name the dominant-harm error type (*NIST FRVT Part 3 Demographic Effects*); CARD-27.

Named data edges above make eligibility inputs and cell interval inputs independently inspectable: [GRPH-32], An edge exists only where data moves (practice label: bootstrap). Cell power and adequacy still depend on its own independent PSUs and mated effective sample size: [EXP-12], Power and practical significance (*Trustworthy Online Controlled Experiments*, ch. 2); [EXP-23], Pseudoreplication check (*Statistics Done Wrong*, ch. 3); [AUDIT-11], Account for cluster design effect (*Sampling: Design and Analysis*, ch. 5). Freeze this contract before outcomes; a parity failure blocks freeze, and later numerical gates govern adoption, with no outcome-selected route change: [EXP-22], No circular analysis (*Statistics Done Wrong*, ch. 6); CARD-27 supplies no formula or project default.

## 9. Named fields (proposed, not an API)

These are proposed names for the reviewed freeze. The v6 names that already exist are reused. The file and key names are not implementation APIs until the freeze.

| Field (proposed path) | Proposed value | Basis |
| --- | --- | --- |
| Fixture / schema (new, not implemented) | `apps/prototype-description-service/scene/tests/fixtures/firbench_sim_cell_v7.json` / `firbench-cell-simulator/v7` | Separate strict fixture/runner contract; never overwrite `firbench_sim_v1.json`. |
| `seeds.suite_registry.cell_power` / `cell_null` | 9 / 10 | Current v1 registry uses exactly 1–8. Keep those eight entries unchanged; new suites use disjoint streams. |
| `seeds.master_seed` / `master_seed_derivation` (new fixture only) | 1113108719 / `int.from_bytes(hashlib.sha256(b'FIRBENCH-1/cell-power/v7').digest()[:4], 'big')` | Deterministic label, not selected from outcomes. Original v1 master 2208172209 and its derivation remain unchanged. |
| `seeds.icc_registry_percent` | Retain `{"0.05":5,"0.10":10,"0.20":20,"0.30":30}` | Existing mapping; the frozen grid uses only 5, 10 and 20. |
| `seeds.suite_seed_derivation` / `replicate_seed_derivation` | Existing `SeedSequence` rules, specified in §12 | `firbench_selftest.py:380–388`. |
| `designs.power_cell_only.0.10.size_counts` | `{"1":104,"4":52}` | Whole-design composition; both cells together. |
| `designs.power_cell_only.0.10.raw_n` / `n_psu` / `sum_squared_sizes` | 312 / 156 / 936 | Whole-design totals, not per-cell values. |
| `designs.power_cell_only.0.10.target_n_eff` | 260 | Exact attained whole-design bookkeeping at ICC 0.10; never a replacement global-115 power claim. |
| `designs.power_cell_only.0.10.cells` | `"alternate_sorted"` | String allocation rule consumed by `_build_design:557–559`. |
| `designs.power_cell_only.0.10.expected_cells` | `{"clear_mask":{"1":52,"4":26},"clear_clear":{"1":52,"4":26}}` | Separate composition map checked by `_check_design:270–296`; no `cells.<cell>` fixture object. |
| `designs.power_cell_only.0.05` / `.0.20` | Same `size_counts`, raw/PSU/squares, `cells` and `expected_cells` as `.0.10`; `target_n_eff=null` in both | Fixed C26 composition; noninteger attained sizing reported exactly in §12, avoiding a rounded equality target. |
| `suite_designs.cell_power` / `suite_designs.cell_null` | Both `{"0.05":"power_cell_only/0.05","0.10":"power_cell_only/0.10","0.20":"power_cell_only/0.20"}` | Complete new suite-to-design mapping; original `suite_designs` entries unchanged. |
| Output `design.cells.<cell>` sizing record (each cell separately) | `size_counts={"1":52,"4":26}`, `raw_n=156`, `n_psu=78`, `sum_squared_sizes=468`, `attained_n_eff=130`, `attained_n_eff_exact="130/1"` at ICC 0.10 | Separate output record using `_public_sizing` conventions. Never add these fields to the strict fixture design node. Sensitivity values in §12. |
| `acceptance.cell_clear_mask_min_rate` / `cell_clear_clear_max_rate` | 0.77 / 0.032, unchanged | Both apply to CELL-POWER-10; CELL-NULL-10 separately requires each cell ≤ 0.032. |
| `cell_floor_n_independent` / `min_n_independent` | 30 / 50 | Manifest-owned, mirrored in `policy_mirror`; eligibility scopes are §8's contract. |
| Manifest `interval.n_boot` / `interval.seed`; fixture `policy_mirror.n_boot` / `bootstrap_seed` | 10000 / 2429382368 | Exact proposed freeze inputs from the current synthetic fixture and dated S9 evidence. Canonical manifest bytes are unavailable here; freeze must read and verify the approved manifest against these values, failing on mismatch. No seed substitution or v1 mutation. |
| `acceptance.full_replicates` / `gated_icc` / `sensitivity_icc` | 2000 / 0.10 / [0.05, 0.20] | Existing limits; sensitivity rows report-only. |
| `laws.h1_power_joint_coupling` | Unchanged v1 triples; transfer 15, 5, 5, 15, clear_mask only | Actual producer reads `laws`, not a top-level `coupling` node. `laws.null` and `laws.h1_power` unchanged. |
| `metrics.cell_only.<cell>.detect_count` / `detect_rate` / `scored_count` / `n_psu` | Per cell: unconditional `detect_count/2000`; require `scored_count=2000`, `n_psu=78` | Missing required interval or replicate gives failed/incomplete evidence; never drop a replicate or filter by global H1/H2. |
| Output `identity.parent_failed_run` | `frozen-v6-2ff389e7` (historical reference only) | Preserve original failed v6 rates 0.063 / 0.5565 and global n_eff 115; no old output overwritten. |

The new fixture keeps the current top-level sections and strict design-node keys. The proposed versioned runner must explicitly support the new schema, `cell_power`/`cell_null` suite/scenario dispatch, registry entries, suite-design mapping and output identity (§12); the current v1 loader/CLI does not implement them. No top-level sizing or coupling extension is proposed. Principle 1, **Author the contract before the components**, and [GRPH-32] **An edge exists only where data moves** (practice label `bootstrap`) require these named inputs before execution. Per-cell power uses 78 independent PSUs and attained n_eff 130, not raw 156 faces or pooled 260 ([EXP-12] **Power and practical significance**, *Trustworthy Online Controlled Experiments*, ch. 2; [EXP-23] **Pseudoreplication check**, *Statistics Done Wrong*, ch. 3; [AUDIT-11] **Account for cluster design effect**, *Sampling: Design and Analysis*, ch. 5).

## 10. Canon mapping (stable IDs, locators, release)

Release: heuristics-canon 0.26.2, release date 2026-10-14, read from the pinned read-only mirror. Full SHA-256 pins, each matched to `meta/release-manifest.json` and the local file: `lexicons/epistemics.md` = `866f67e6fe626671999bc9debd3774188c23f7b82905ea7d5e008a08dd5f7f07`; `lexicons/ml-systems.md` = `1dfbd751c2d52d223b0ae617da7f709dd29970f37ddd9bcdc0eb09a7e839cf20`; `lexicons/graph-theory.md` = `23bdbc8262cbd3577e4fd5ef3e49c6ad1f50fdfd1472ba3990497ef57e3eb61c`. CARD-27 supplement `margin-and-design-effect-before-the-run.md` SHA-256 = `186c94c2b0ba88897cebea26c39752d6f0e87bbab8bff3ec1fa9aace79f85aad`; it supplies neither a formula nor project defaults. Row locators are anchors in those files. [GRPH-14] **Record provenance as a walkable lineage graph** (*Building Knowledge Graphs*, ch. 8; *Mental Models*, ch. 8) applies to these pins. The read-only mirror lacks the relevant full reasoning cards; the supplied supplement and applicable lexicon rows/principles are the bounded evidence. No unavailable card or original book is claimed read. Source per rule, from each row's source tag (chapter as tagged in the row):

- *Trustworthy Online Controlled Experiments*: EXP-10 ch. 3; EXP-12 ch. 2; EXP-13 ch. 19.
- *Statistics Done Wrong*: EXP-18 ch. 2; EXP-19 ch. 5; EXP-22 ch. 6; EXP-23 ch. 3; EXP-24 ch. 1.
- *Sampling: Design and Analysis*: AUDIT-07 ch. 1; AUDIT-11 ch. 5.

Principle 2 is "Specify what would prove you wrong" (`PRINCIPLES.md`, section 2).

| Rule | Locator | Use in this proposal |
| --- | --- | --- |
| EXP-12 power and practical significance | `lexicons/epistemics.md#exp-12` | Pre-declared minimum effect 0.10, power 0.80, CI on the delta. Sizes are analytic, not run. |
| EXP-13 A/A before A/B | `lexicons/epistemics.md#exp-13` | Requires the cell null calibration (§12, CELL-NULL-10) before the cell power claim. |
| EXP-18 type-M inflation | `lexicons/epistemics.md#exp-18` | The v6 observed cell rate (0.5565) is not used as a planning effect. Planning uses the pre-declared 0.10. |
| EXP-19 paired contrast | `lexicons/epistemics.md#exp-19` | The cell estimand is the paired within-cell contrast, not two one-arm significance calls. |
| EXP-22 no circular analysis | `lexicons/epistemics.md#exp-22` | The candidate size is chosen by analytic rule before outcomes. The failed v6 row is not replaced by re-selection. |
| EXP-23 pseudoreplication | `lexicons/epistemics.md#exp-23` | N is the PSU, not faces or images inside a PSU. |
| EXP-24 interval over bare p | `lexicons/epistemics.md#exp-24` | Report the cell-level interval on the effect with each pass or fail. |
| EXP-10 pre-allocated α over K candidates | `lexicons/epistemics.md#exp-10` | α allocation across the two cells is a reviewer decision (§14). |
| AUDIT-07 name frame and units | `lexicons/ml-systems.md#audit-07` | Frame: synthetic cell design. Sampling unit: PSU. Observation unit: mated face. |
| AUDIT-11 cluster design effect | `lexicons/ml-systems.md#audit-11` | deff = 1 + (M̃ − 1)·ICC, n_eff = n/deff, per tested cell. |
| CARD-27 margin and design effect before the run | `canon-supplement/margin-and-design-effect-before-the-run.md`; manifest `card_ids` entry `CARD-27` (active) | Seal margin, method class, harm direction and α before the run. CARD-27 does not select an interval formula or prescribe project numbers. |
| FAIR-04 dominant harm per floor | `lexicons/ml-systems.md#fair-04` | Harm direction declared per floor (§8). |
| MEAS-29 contextual observation | `lexicons/epistemics.md#meas-29` | **Not satisfied and not claimed.** No human observation is in this proposal. |
| GRPH-14 walkable lineage | `lexicons/graph-theory.md#grph-14` | Lineage table in §2. |

Principle 2 is applied through the disconfirmers in §13.

## 11. Limitations

- The empirical power is unvalidated for this composition. The analytic normal planning formula is only a sizing aid. The v6 empirical offsets (+0.038, +0.047) are two points, not a calibration.
- ICC 0.10 is an assumption, not an observed ICC. At ICC 0.20 the candidate's analytic n_eff is 111.4, below n_req. That is expected to show up as a report-only finding, not a gate.
- Sizes 1 and 4 only. The composition does not include 16-face PSUs, where the v6 H2 boundary failure concentrated its variance. Whether the percentile bootstrap is calibrated for this composition is unknown until CELL-NULL-10 runs.
- Synthetic fixture only. Real PSU structure may differ, so no real-data power transfers from this design. Real-frame sizing belongs to the separate real-data gates.
- The compute estimate in §12 is an order-of-magnitude estimate, not a measurement.
- Two cells are both tested at the step-1 level, so their family-wise error is not corrected. The α decision is in §14.

## 12. Future MC cases and estimated compute (none run)

Recommended frozen grid: exactly the six rows below, all specified before outcomes, with R = 2000 and `n_boot` = 10000. No optional MC cases are included: CELL-NEG-30 and CELL-CONFIRM-10 are omitted. Any addition requires a new pre-outcome revision, including its stream, predicate and output identity. Freeze fixture, runner, manifest inputs, gates and seed lineage before drawing any replicate; adoption requires the frozen numerical gates after the run. Null outcomes never feed back into this design's freeze ([EXP-22] **No circular analysis (double-dipping)**, *Statistics Done Wrong*, ch. 6).

All rows use proposed fixture `apps/prototype-description-service/scene/tests/fixtures/firbench_sim_cell_v7.json` (schema `firbench-cell-simulator/v7`) and new runner module `scripts.eval_harness.firbench_cell_selftest_v7`, selected with `--params <that fixture> --suites cell_power,cell_null`. These are proposed interfaces requiring implementation/review before freeze, not commands supported by today's v1 runner. Its two dedicated cell branches use §8's H1 route on each named packet/cell, never `run_power_suite` or an old null/global branch. The versioned runner retains strict fixture validation and original sections/entries, adds only the stated schema/suite dispatch and new design family, and emits cell-specific evidence; it cannot imply full S9 acceptance. All rows use whole-PSU total `size_counts={"1":104,"4":52}`, raw 312, PSU 156, Σm² 936; each cell has `{"1":52,"4":26}`, raw 156, PSU 78, Σm² 468. `cells="alternate_sorted"` and the distinct `expected_cells` map in §9 apply to every row.

| Case / output identity | `suite_designs` selector → design key | Scenario / packet / runner branch | Registry / ICC key (spawn value) | Per-cell attained n_eff / whole-design attained n_eff | Role / complete predicate |
| --- | --- | --- | --- | --- | --- |
| CELL-POWER-05 | `cell_power["0.05"]` → `power_cell_only/0.05` | `h1_power_cell_only` / planted / `cell_power` | `cell_power=9` / `"0.05"` (5) | 1560/11 = 141.818182 / 3120/11 = 283.636364 | Report-only sensitivity; both cell rates and completeness reported. |
| CELL-NULL-05 | `cell_null["0.05"]` → `power_cell_only/0.05` | `null` / control / `cell_null` | `cell_null=10` / `"0.05"` (5) | 1560/11 = 141.818182 / 3120/11 = 283.636364 | Report-only sensitivity; both cell rates and completeness reported. |
| CELL-POWER-10 | `cell_power["0.10"]` → `power_cell_only/0.10` | `h1_power_cell_only` / planted / `cell_power` | `cell_power=9` / `"0.10"` (10) | 130 / 260 | Gate: clear_mask `detect_rate >= 0.77` **AND** untreated clear_clear `detect_rate <= 0.032`; both `scored_count=2000`. |
| CELL-NULL-10 | `cell_null["0.10"]` → `power_cell_only/0.10` | `null` / control / `cell_null` | `cell_null=10` / `"0.10"` (10) | 130 / 260 | Separate all-null gate: each cell `detect_rate <= 0.032`; both `scored_count=2000`. |
| CELL-POWER-20 | `cell_power["0.20"]` → `power_cell_only/0.20` | `h1_power_cell_only` / planted / `cell_power` | `cell_power=9` / `"0.20"` (20) | 780/7 = 111.428571 / 1560/7 = 222.857143 | Report-only sensitivity; both cell rates and completeness reported. |
| CELL-NULL-20 | `cell_null["0.20"]` → `power_cell_only/0.20` | `null` / control / `cell_null` | `cell_null=10` / `"0.20"` (20) | 780/7 = 111.428571 / 1560/7 = 222.857143 | Report-only sensitivity; both cell rates and completeness reported. |

Seed identity for **every row**: master label `FIRBENCH-1/cell-power/v7`, SHA-256 first four bytes big-endian → master 1113108719. Derive `suite_seed = int(numpy.random.SeedSequence(1113108719, spawn_key=(registry, icc_percent)).generate_state(1, dtype=numpy.uint64)[0])` with the row's registry and ICC value. For each integer `r=0..1999`, `replicate_seed = int(numpy.random.SeedSequence(suite_seed, spawn_key=(r,)).generate_state(1, dtype=numpy.uint64)[0])`. Draw the row's scenario with that seed. `cell_null` has its own stream, not the control packet from `cell_power`; power/null and ICC streams are disjoint SeedSequence identities. Within a planted replicate the original control/planted coupling and untreated clear_clear equality remain intact. Bootstrap seed is separately manifest-owned 2429382368, reused as specified in §8, not drawn from this generator seed tree. No numeric SeedSequence states or new outcomes are claimed computed here.

Each new case output is `<new-output-root>/cell-power-v7/<CASE-ID>/acceptance.json`, with the six literal CASE-IDs above. The new root must be an explicit freeze input satisfying the existing output-path validator and must not overwrite v6. Each case records its case ID, schema, fixture path/digest, runner digest, current source-tree identity, manifest digest, design key, scenario, packet/branch, suite registry value, master label/value, ICC key/value, suite seed, replicate-index rule, bootstrap seed/count, requested/completed replicates and both per-cell records. These are proposed output fields, not present APIs. Preserve original v1 global design/laws/seed registry/master and historical failed results unchanged. [GRPH-32] **An edge exists only where data moves** (practice label `bootstrap`) requires the case selector to consume these named fixture and stream fields.

For every row, both rates are unconditional `detect_count/2000`, never divided by scored-only counts and never filtered by global H1 or H2. C26 requires 2000 completed replicates and `scored_count=2000` for each cell. A missing required interval, malformed output or incomplete replicate count is failed/incomplete evidence and cannot pass either gate; report-only rows remain visibly incomplete too. Retain all 10000 bootstrap resamples per required interval; no dropped resamples. H1 keeps the percentile paired whole-PSU interval and original laws; no H2 method change is introduced. CELL-NULL-10 is an additional calibration gate, not a substitute for the untreated-cell predicate in CELL-POWER-10 ([EXP-13] **A/A before A/B**, *Trustworthy Online Controlled Experiments*, ch. 19).

Compute estimate (unvalidated analytic extrapolation, not a measurement):

- The dated review evidence records the historical v6 whole power suite as 334.1 s at R=2000, including global decides. Its original receipt/report bytes are intentionally absent here; this is historical context, not a verified present-environment timing.
- Each proposed case needs two cell H1 intervals: 2 × 78 = 156 sampled PSU positions per bootstrap resample. If the §8 `decide` route also computes one H2 interval per cell, that route instead needs up to 312 such positions. Relative to the earlier rough v6 207–276-position comparison, a linear extrapolation is approximately 190–500 s per case, or 19–50 min for all six. This models bootstrap work only; eligibility, packet construction and memory/VM overhead are unquantified. It is not a budget or runtime bound.
- Execute the frozen grid once in one VM process, single-threaded (`OMP_NUM_THREADS=1` and corresponding library thread limits); record measured timings with those outcomes. No MC timing probe or optional case is part of this proposal. Timing cannot select seeds, size, gate or method, and no rerun may improve a failed rate.

## 13. Alternatives and disconfirmers

Alternatives:

| Option | Effect | Assessment |
| --- | --- | --- |
| C24 (k = 24) | n_eff 120; slack +4.0%; MDE 0.098081 | Minimum integer that meets n_req at ICC 0.10. Too thin: a planning ICC above the 0.124 break-even already falls below the bar. Not recommended. |
| **C26 (k = 26), recommended** | n_eff 130; slack +12.7%; MDE 0.094305; ICC break-even 0.176 | Chosen by the §5 rule. Costs 78 PSUs and 156 faces per cell. |
| C28 (k = 28) | n_eff 140; slack +21.4%; ICC break-even 0.228 | Analytically covers the report-only ICC 0.20 row. Choose if reviewers want that row inside the bar. Costs about 8% more per cell than C26. |
| Two-cell α split (α₁ = 0.0125 each) | n_req rises to 139.95 | C28 would have essentially zero slack (MDE 0.099982). A 10% margin needs k = 31 (n_eff 155). Only if the reviewer chooses a split (§14). |
| Non-2:1 PSU composition (e.g. near-equal 13-face PSUs) | Changes deff and PSU count | Rejected: the brief requires the old fractions preserved. A different law would need its own sealed design. |
| Unequal cell sizes | Smaller clear_clear | Rejected for now: the clear_clear arm is the matched null calibration, so it must match clear_mask's n_eff. |
| Studentized paired interval | Different interval class | Out of scope. Needs its own preregistration and validation, as v6 notes. Not used here. |

Disconfirmers (what would change the recommendation):

- Pre-outcome evidence that the planning ICC assumption 0.10 is unsuitable defeats this proposal's sizing premise; record it and revise prospectively before any draw. Real-data ICC is unverified here. After outcomes, do not resize or promote the report-only ICC rows into gates ([EXP-22] **No circular analysis (double-dipping)**, *Statistics Done Wrong*, ch. 6).
- CELL-NULL-10 gives either cell `detect_count/2000 > 0.032`, with both `scored_count=2000`: the required calibration gate fails. This blocks a validated cell-power claim without diagnosing the cause from that rate alone. Keep the failure; no seed retry or calibration-to-freeze feedback loop.
- CELL-POWER-10 gives clear_mask `detect_count/2000 < 0.77` **OR** untreated clear_clear `detect_count/2000 > 0.032`, with both `scored_count=2000`: the complete mixed planted/null predicate fails. Preserve this failure even if CELL-NULL-10 passes. No global-H1/H2 filtering, outcome-selected size change or replacement of the original v6 0.5565 result.
- Any required interval missing, any `scored_count != 2000`, any requested/completed replicate mismatch, or a dropped bootstrap resample: failed/incomplete evidence, never a reduced denominator or a passing gate. Preserve the unconditional 2000 denominator for every row.
- The §8 route/interval parity check fails on its explicitly eligible known-answer domain, or the whole-fixture/per-cell eligibility scopes disagree: stop before outcomes and resolve the implementation in a reviewed pre-outcome revision. Missing canonical manifest inputs also block freeze, not this bounded analytic proposal.
- Fixture shape, six-row case/design/scenario selector, seed lineage, composition or output identity differs from §9/§12: the result cannot support this pre-registration. Sensitivity retains C26 composition; there is no optional case in the recommended frozen grid. Any different design/grid needs its own pre-outcome revision.

## 14. Decisions for review before freeze

1. Approve the §5 rule (10% n_eff slack) and C26, or choose C24, C28, or the α-split variant.
2. Decide whether the two cells need an α split (§5, §13). The default here is no split, with the family disclosed, because the only claim is clear_mask.
3. Carry the explicit §8 eligibility adapter and declared per-floor harm directions into the prospective freeze: whole-fixture ≥50 plus resolvable FPIR, separate cell ≥30, and unconditional cell H1. These routine choices are resolved here; verify them before drawing outcomes, and assess adoption only after the numerical gates.
4. Decide whether CELL-CONFIRM-10 is required, optional, or omitted.
5. Freeze the new seed label and record its derived master seed at freeze.

## 15. Deterministic checks (to implement with the freeze; none run here)

- Arithmetic: exact rational check that raw, PSUs, Σm², M̃, deff and n_eff match §5–6 for the chosen composition, and that the requirement n_req = 115.3469 is reproduced by the real `minimum_detectable_effect`.
- Reproduction: the v6 cells reproduce clear_mask n_eff 59.028103 and MDE 0.138425, as in §3.
- Composition: exactly 52 and 26 per cell from the alternate-sorted rule. All PSU IDs are distinct and whole.
- Floors: check the §8 boundary table on valid synthetic inputs: global49/cell29 and global49/cell30 both have no H1 interval and `insufficient_independent_psus` scoped to `whole_fixture`; global50/cell29 with resolvable FPIR has no H1 interval and the same reason scoped to `cell`; global50/cell30 with resolvable FPIR has an H1 interval and no eligibility refusal, even for H1 non-rejection. At global≥50 with unresolvable whole-fixture FPIR, both cell sizes have no interval and `primary_fpir_unresolvable` scoped to `whole_fixture`. Neither manifest floor is lowered.
- Coupling: the planted law is the H1 row, only the SFace bit changes, clear_clear packets are identical to control, and ICC1 = 1/(k+1) holds in `Fraction` oracles.
- Seeds: the new registry value is unused and the derivation reproduces the frozen value.
- Route: on the §8 eligible parity domain only, `_cell_decision` equals the real-`decide` adapter H1 interval exactly (both bounds and interval fields) and yields the same detection boolean. Assert whole-fixture frame retention, complete background tuple including multiplicities and coverage of the whole-fixture PSU set, all three cell leg arrays aligned on identical ordered faces/PSUs/unit weights, `h2_leg=auraface`, `SIM-G0` report-only with empty readings, and unchanged bootstrap seed/B/level. Check refusals separately outside the parity domain. Confirm H1 scoring/counting ignores H2 and overall state, retains non-rejections and every replicate, and never forces H1 or changes the H1 percentile interval for an H2 proposal.
- Negative control: the image-level comparator fails the coverage rule on the clustered fixture.

## 16. Verification of this document

Checked here (static only; no tests exist for prose):

- Every cited code anchor and fixture key was grep-checked against the checkout.
- Every arithmetic number was recomputed with the real scorer function or exact rationals (scripts kept outside the repository).
- Relative links, anchors and `git diff --check` are checked before commit.

Not checked: any statistical claim about the candidate's empirical power, bootstrap calibration, or compute time. Those are §11–12 open items.
