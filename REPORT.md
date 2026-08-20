# Lane F10 — DESCQUAL-2 BR-14, BR-06 residual, BR-10, BR-12

Scope pins for the table: whole-frame clustered n=216 (Kish a=12.90, ICC=0.2, e=0.10, N=640); B_eyewear clustered floor n=49 (a=2.36); unclustered B remains 44.

- BR-14: `ClusterSpec.cluster_size` is the Kish effective size `a=Σm²/Σm` (WHY: `1+(M−1)·ICC` is the equal-size form); added `kish_effective_cluster_size`; whole-frame test pinned at 216 not 136. Tests: `test_kish_effective_cluster_size_is_not_the_mean`, `test_clustered_size_applies_deff_to_n0_before_fpc`, `test_clustered_b_eyewear_precision_floor_is_49`. Mutants (all RED): helper returns the mean; `design_effect` hardcodes M=4.9; allocate floor uses `80/47` instead of `spec.cluster_size`.
- BR-06: `project_strata_subject_image_counts(entries)` returns per-stratum per-subject size vectors that feed Kish `a`; empty `present_identities` add no cluster; `allocate(cluster_params=None)` stays deff-blind (`FPC_ONLY`). Tests: `test_subject_image_counts_feed_kish_a`, `test_empty_present_identities_contribute_no_cluster`, `test_subject_image_counts_reject_bare_string_identities`, `test_allocate_without_cluster_params_stays_deff_blind`. Mutants (RED): empty identities become a 0-count cluster; bare-string `present_identities` is accepted.
- BR-10: `ClusterSpec.__post_init__` rejects `cluster_size<1`, ICC outside `[0,1]`, and non-finite values; `allocate` rejects `cluster_params` keys with no precision floor; nan/inf raise `AuditSamplingError` not `math.ceil` `ValueError`. Tests: `test_cluster_spec_rejects_out_of_bounds`, `test_allocate_rejects_cluster_params_without_precision_floor`, `test_design_effect_rejects_non_finite_as_audit_error`. Mutants (RED): empty `__post_init__`; drop the unfloored-key check; drop the finite check so NaN hits `math.ceil`.
- BR-12: renamed the floor-loop binding to `floor_spec` (validation loop is `cluster`). `mypy --explicit-package-bases scripts/eval_harness/audit_sampling.py` is clean of the assignment/unreachable pair at the old :251/:253. No remaining errors in this file (the pre-existing `icc: float | None` arg-type on `design_effect` was closed by the `size_for_margin` if/elif narrowing we already owned). The pyproject unused-section note is not an error.

`PYTHONPATH=$PWD …/python -m pytest scene/tests/test_eval_harness_audit_sampling.py -q` → 27 passed.

# Lane F11 — DESCQUAL-2

- BR-07: `_judged_keys` raises `AmbiguousJudgmentError` (names the text + candidate keys; tells the caller to pass `PooledFact`/`CandidateFact`) when a bare string matches more than one pooled fact; unique bare strings and `PooledFact`/`CandidateFact` judgments are unchanged. Tests: `test_ambiguous_bare_string_judgment_raises`, `test_unique_bare_string_judgment_resolves`, `test_bare_string_pool_key_marks_one_polarity`, `test_candidate_fact_judgment_does_not_mark_complementary_polarity`. Mutant `/tmp/br07` restored `matched.update(by_text...)` → ambiguous test DID NOT RAISE; `/tmp/br07b` used `len(candidates) >= 1` → unique test RED (`AmbiguousJudgmentError` on `"BLUE COAT"`).
- BR-11: `Allocation.__post_init__` copies `counts`/`floors` into `MappingProxyType`; custom `__hash__` over sorted items. Tests: `test_allocation_source_dicts_cannot_mutate_constructed_object`, `test_allocation_hash_equal_for_equal_mappings`, `test_allocation_item_assignment_raises`. Mutant `/tmp/br11a` wrapped without `dict()` copy → `assert alloc["E_clean"] == 10` saw 0; `/tmp/br11b` dropped `__hash__` → `TypeError: unhashable type: 'dict'`; `/tmp/br11c` left a live dict → `alloc.counts["E_clean"] = 0` DID NOT RAISE.
- BR-13: Rewrote the `HUMAN_CONFIRMATION_SOURCES` comment as a rule about any future `ConfirmationSource` member; allowlist unchanged. No behaviour test (comment-only). Mutant `/tmp/br13` restored `DISTILLED/HEURISTIC`; original `manifest.py` grep has neither name.

# Lane F15 — DESCQUAL-2 sampler

BR-26 and BR-27 were already committed on `lane/f15` before this continuation (`ec245fd4`, `a365e440`).

## BR-24 — whole-frame Kish `a` (AUDIT-11, TEST-15)

**Status:** closed.

**What changed.** `project_whole_frame_subject_image_counts` joins the same identity across strata into one cluster. Concatenating `project_strata_subject_image_counts` vectors splits a cross-stratum subject into two clusters and understates Kish `a` (7.41 over 231 clusters vs 12.90 over 130). The test pin is derived from that projector against the vendored FIR-12 frame (`benchmarks/manifests/fir12-selection-v1.json`), not a hardcoded `12.90`. The Kish-vs-mean contrast uses the actual cluster-vector mean `544/130 = 4.18` (not `640/130 = 4.92`).

**Tests.**
- `test_whole_frame_join_merges_identity_across_strata`
- `test_whole_frame_counts_unlabeled_and_multi_identity_images`
- `test_whole_frame_kish_a_joins_identities_across_strata`

**Mutant (TEST-15).** Join key `identity` → `f"{stratum}::{identity}"` (per-stratum split).

**RED.**
```
test_whole_frame_join_merges_identity_across_strata
  assert sorted(frame.sizes) == [1, 2]
  assert [1, 1, 1] == [1, 2]

test_whole_frame_kish_a_joins_identities_across_strata
  assert len(frame.sizes) == 130
  assert 231 == 130
```

**Canon.** AUDIT-11, TEST-15.

**Vendored frame.** `benchmarks/manifests/fir12-selection-v1.json` (421226 bytes). DESCQUAL-2 clone does not otherwise ship it; CI recomputes `a = 7020/544 = 12.904412` from this copy.

## BR-18 — subject-stage sampler + ICC estimator (AUDIT-11)

**Status:** closed.

**What changed.** `draw()` remains image-level SRS. New `draw_two_stage` draws subject PSUs then `n_within>=2` images inside each PSU, with two-stage inclusion probabilities. New `estimate_icc` is the one-way ANOVA ICC plus Fisher-Z interval (ICC transform, not Pearson artanh). On the honest G=65, k=3 design at ρ=0.2 the CI is [0.045, 0.360], which sizes n to 121..284 against the whole-frame Kish a.

**Tests.**
- `test_draw_two_stage_replicates_within_psu`
- `test_draw_two_stage_is_deterministic_and_order_invariant`
- `test_draw_two_stage_carries_two_stage_inclusion_probability`
- `test_draw_two_stage_refuses_n_within_below_2`
- `test_draw_two_stage_refuses_psu_smaller_than_n_within`
- `test_two_stage_census_of_m3_subjects_is_195_images`
- `test_fir12_icc_eligible_subject_counts` (76 with m≥2, 65 with m≥3)
- `test_estimate_icc_anova_known_fixture`
- `test_estimate_icc_fisher_z_ci_for_g65_k3_at_rho_02`
- `test_estimate_icc_recovers_rho_on_synthetic_clusters`
- `test_estimate_icc_rejects_singletons_and_too_few_psus`

**Mutant (TEST-15), two-stage → image SRS.** Flatten clusters and `rng.sample(flat, n_psu * n_within)` with `psu_id=None`.

**RED.**
```
test_draw_two_stage_replicates_within_psu
  assert unit.psu_id is not None
  AssertionError: assert None is not None

test_two_stage_census_of_m3_subjects_is_195_images
  assert len({u.psu_id for u in sample.units}) == 65
  assert 1 == 65
```

**Mutant (TEST-15), ICC CI → Pearson artanh.** `z = artanh(ρ)`, `SE = 1/√(G−3)`.

**RED.**
```
test_estimate_icc_fisher_z_ci_for_g65_k3_at_rho_02
  assert est.lower == pytest.approx(0.045, abs=5e-4)
  assert -0.030303697997921163 == 0.045 ± 5.0e-04
```

**Canon.** AUDIT-11, TEST-15.

`scene/tests/test_eval_harness_audit_sampling.py` → 46 passed. Full `scene/tests` → 1263 passed, 4 skipped; the 4 failures are the known pre-existing PGPASSWORD / `InsecureProductionConfigError` boots (`test_describe_route.py::test_create_app_registers_route_and_upload_cap` and the three `test_describe_run_reclaim.py` startup tests).

