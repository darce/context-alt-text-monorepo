# Lane F19 — DESCQUAL-2-BR-29

## DESCQUAL-2-BR-29 (high) — closed

Planning n = 198 cannot be regenerated from the shipped module: Kish `a`
was `WHOLE_FRAME_KISH_A = 12.904412` over the labeled-subject vector
(130 clusters, Σm = 544), then applied to `population=640`. That vector
is not a PSU partition of the 640-image frame.

### What changed

- `project_frame_psu_image_counts` in `audit_sampling.py` returns a frozen
  `FramePsuPartition` (`sizes`, `n_entries`, `n_psus`,
  `n_unlabeled_singletons`, `never_first_identities`).
- PSU rule: first-listed `present_identities`; empty → singleton
  `unlabeled:{media_id}`.
- `FramePsuPartition.__post_init__` raises `AuditSamplingError` unless
  `sum(sizes) == n_entries` (and `n_psus == len(sizes)`).
- `_parse_selection_entries` now returns `(stratum, media_id, identities)`.
  `media_id` is required (non-bool int or non-empty str).
- `FRAME_PSU_KISH_A` is derived from the projector on
  `benchmarks/manifests/fir12-selection-v1.json`: 241 PSUs, Σm = 640,
  Σm² = 6942, a = 10.846875. Never-first: Auburn Hollow, Tidal Quarry,
  Vellum Warren, Verdant Beacon.
- `test_clustered_size_applies_deff_to_n0_before_fpc` kept (deff-then-fpc
  ordering 216 vs 284) and renamed
  `test_deff_then_fpc_ordering_on_labeled_subject_a_not_planning_n` so 216
  cannot be read as the study n. Planning pin is 198 on `FRAME_PSU_KISH_A`.
- `project_whole_frame_subject_image_counts` and its tests kept.
- Scope doc snippet now calls `project_frame_psu_image_counts`. Published
  numbers unchanged. 64-vs-65 PSU distinction untouched.

### New tests

- `test_frame_psu_partition_assigns_first_listed_or_unlabeled_singleton`
- `test_frame_psu_partition_requires_sizes_sum_to_n_entries`
- `test_frame_psu_partition_requires_media_id`
- `test_frame_psu_kish_a_is_partition_of_640`
- `test_planning_n_on_frame_psu_kish_a` (ICC 0/0.05/0.1/0.2/0.3/0.5 →
  n = 84/118/148/198/239/302, deff 1.000/1.492/1.985/2.969/3.954/5.923)

### Mutants (TEST-15)

**Mutant 1** — drop unlabeled singletons (skip `counts[unlabeled:{media_id}]`).

RED (collection, `FRAME_PSU = project_frame_psu_image_counts(...)`):

```
AuditSamplingError: PSU sizes must partition the frame: sum(sizes)=525 != n_entries=640
```

**Mutant 2** — last-listed identity (`identities[-1]`) instead of first.

RED:

```
test_frame_psu_kish_a_is_partition_of_640
  AssertionError: assert 243 == 241  (n_psus; never_first becomes
  Dappled Meadow, Vellum Meadow)

test_frame_psu_partition_assigns_first_listed_or_unlabeled_singleton
  AssertionError: assert ('cara', 'dana') == ('bob', 'erin')

test_planning_n_on_frame_psu_kish_a[0.2-198-2.969]
  AssertionError: assert 195 == 198  (a=10.540625, not 10.846875)
```

Restored first-listed + unlabeled singleton. 56/56 in
`test_eval_harness_audit_sampling.py`. Full `scene/tests`: 1290 passed,
4 skipped, 4 failed — the known PGPASSWORD /
`InsecureProductionConfigError` boot failures, not new.

### Canon

AUDIT-09, AUDIT-10, AUDIT-11, TEST-15, rg-005, sr-007.

### Not closed

Nothing in this finding. Did not touch `manifest.py`, lineage fixtures,
or FIR-12 files.
