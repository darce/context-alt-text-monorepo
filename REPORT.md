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

# Lane F16 — DESCQUAL-2 provenance (BR-21, BR-25 code, BR-20)

## AdjudicationRule enum (carry this into the scope doc)

Closed set on `scripts.eval_harness.manifest.AdjudicationRule`. Doc lane must name **these exact tokens**, not free text:

- `disagreement-escalate-to-sme`
- `majority_vote`
- `unanimous`

Required whenever `adjudicated_by` is set. Free text (`coin-flip`) is refused.

## BR-21 (already on branch: `331bb53f`) — closed

`build_pool` now refuses non-independent contributors (distinct model families + a human pass), not just `len < 2`. `bind_gold` refuses gold with no `source_pool`. EVAL-25.

Tests: `test_same_model_family_prompt_variants_are_not_independent`, `test_pool_without_human_contributor_raises`, `test_gold_facts_without_source_pool_cannot_be_bound`.

## BR-25 code half (already on branch: `5fcb93fd`) — closed

`adjudication_rule` is `AdjudicationRule` (see tokens above), required when `adjudicated_by` is set. MLDATA-03.

Tests: `test_adjudication_rule_rejects_free_text`, `test_adjudicated_by_requires_written_rule`, `test_named_adjudication_rule_is_accepted`.

Doc half (gold-item rate, provenance, per-annotator gold-accuracy threshold) is out of scope here.

## BR-20 — closed in owned files

Human-confirmed facts (`confirmed_by` in `HUMAN_CONFIRMATION_SOURCES`) now require non-blank `annotator_id`, `annotation_batch`, `annotated_at`, and `source_pool`. `adjudicated_by` now requires a non-empty `pre_adjudication` list so a disagreement is stored, not erased. MLDATA-03, MLDATA-04, HITL-07. TEST-15.

Owned tests (all raise `ValidationError` on the under-populated variant):

- `test_human_confirmed_fact_missing_lineage_field_raises` (param: `annotation_batch` / `annotated_at` / `source_pool` = None)
- `test_human_confirmed_fact_blank_lineage_field_raises` (same fields = `"   "`)
- `test_operator_gold_with_no_lineage_raises` (M9 constructor: operator + annotator_id, all other lineage omitted)
- `test_adjudicated_fact_with_empty_pre_adjudication_raises` (M10: `adjudicated_by='sme-03'`, `pre_adjudication=[]`)

`test_named_adjudication_rule_is_accepted` fixture now carries two pre-adjudication labels so it still constructs after the M10 check.

### Mutants (both RED)

**M9** — `required = ("annotator_id",)` only (lineage optional again):

```
FAILED test_human_confirmed_fact_missing_lineage_field_raises[annotation_batch]
FAILED test_human_confirmed_fact_missing_lineage_field_raises[annotated_at]
FAILED test_human_confirmed_fact_missing_lineage_field_raises[source_pool]
FAILED test_human_confirmed_fact_blank_lineage_field_raises[...]
FAILED test_operator_gold_with_no_lineage_raises
Failed: DID NOT RAISE ValidationError
```

**M10** — `_adjudication_requires_pre_labels` short-circuited with `if False and ...`:

```
FAILED test_adjudicated_fact_with_empty_pre_adjudication_raises
Failed: DID NOT RAISE ValidationError
```

Mutants restored. Owned files: `scene/tests/test_eval_harness_manifest.py` + `test_eval_harness_judgment_pool.py` → 79 passed, 1 skipped.

## Could not close (unowned fixtures)

Did not edit files outside the exclusive set. Coordinator must add the three lineage fields by hand:

1. `scene/tests/test_eval_harness_manifest_reference_fact_lineage.py::test_disagreement_survives_adjudication` — operator fact has `annotator_id` + pre-labels but omits `annotation_batch`, `annotated_at`, `source_pool`. Add the same three strings used in `_full_payload()` in that file.
2. `benchmarks/manifests/golden150-draft-20260723.json` entries[149] (media_id 648) — two operator facts have only `annotator_id="pre-program-operator"`. Same three fields need a backfill (same pattern as the earlier annotator_id backfill). Until then `test_golden150_draft_parses_with_backfilled_fact_annotators` fails via `load_legacy_manifest`.

Full `scene/tests` (excluding known PGPASSWORD boot failures): **2 failed, 1213 passed, 4 skipped** — those two unowned fixtures only. No back-compat shim on the model; v2 load still goes through `ReferenceFact`.

# Lane F18 — DESCQUAL-2 lineage backfill (BR-20 leftover fixtures)

Do not redo BR-21 / BR-25(code) / BR-20. This lane only backfills the two fixtures BR-20 correctly left broken, plus the `majority_vote` → `majority-vote` token rename.

## 1. `test_disagreement_survives_adjudication`

Operator fact already had `annotator_id` + both pre-adjudication labels; BR-20 made `annotation_batch`, `annotated_at`, `source_pool` required on human-confirmed facts (MLDATA-04). Backfilled those three from `_full_payload()` in the same file (`batch-2026-08-20`, `2026-08-20T12:00:00Z`, `golden-646-pool`) — no second set of magic strings. Model not relaxed.

Test: `test_disagreement_survives_adjudication` (existing; now also asserts the three fields equal `_full_payload()`).

Mutant: omit `annotation_batch=` from the constructor. RED:

```
FAILED scene/tests/test_eval_harness_manifest_reference_fact_lineage.py::test_disagreement_survives_adjudication
Value error, human-confirmed reference_fact requires annotation_batch
(confirmed_by=<ConfirmationSource.OPERATOR: 'operator'>; MLDATA-04)
```

Canon: MLDATA-03, MLDATA-04, HITL-07, TEST-15. Mutant restored.
