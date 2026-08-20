# Lane F7 report

**DESCQUAL-2-BR-06.** `allocate()` takes per-stratum `cluster_params: Mapping[str, ClusterSpec]` (M is per-cell: B is 80/47, E is 407/109) and passes `(cluster_size, icc)` into `size_for_margin`; omitted entries keep the unclustered floor. Return is `Allocation` with `floors[name] -> SampleSize` so deff, `deff_order`, and `n_eff = n/deff` are readable. Test: `test_clustered_b_eyewear_precision_floor_is_47` (pins 47 vs unclustered 44; `DEFF_THEN_FPC`). Mutant `/tmp/dq2-f7-br06`: accept `cluster_params` but size with unclustered `size_for_margin` → `assert 44 == 47`.

**DESCQUAL-2-BR-09.** `HUMAN_CONFIRMATION_SOURCES` is the allowlist `{OPERATOR}`, not complement-of-AGENT. Test: `test_human_confirmation_sources_are_an_explicit_allowlist`. Mutant `/tmp/dq2-f7-br09`: add `DISTILLED` and restore complement → set equality fails with extra `DISTILLED`.
