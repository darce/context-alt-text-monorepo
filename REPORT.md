# Lane F17 — DESCQUAL-2 scope doc redesign (prose and arithmetic only)

Owned file: `docs/scopes/descqual-2-fact-annotation-pilot.md`.
No production code. Frozen frame: `/home/ubuntu/l1/fir12-n3/benchmarks/manifests/fir12-selection-v1.json`.
Shipped module: `scripts.eval_harness.audit_sampling`.
Python: `/home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python`.

This lane has no pytest of its own. Evidence for every published number is the
exact call against the shipped module and frozen frame, pasted below.
TEST-15 for prose: OLD vs NEW numbers, and a mutant that would republish the
rejected design.

---

## BR-17 (GATE-BLOCKING) — demote the ~30-image draw; pre-register planning ICC

**Canon:** AUDIT-11, AUDIT-09.

**What changed.** The ~30-image draw is now a **cost and instrument pilot**
(minutes per image, rubric α, gold-item QC). It is not the source of `deff`.
Full-study n is a **pre-registered planning ICC of 0.20 → n = 216**, with the
**0.30 → n = 261** sensitivity row printed beside it. A **subject-stage draw
over the 65 subjects with m ≥ 3 (195 images)** is a named conditional follow-on,
not the baseline; that design reports the Fisher-Z **upper** CI bound.

OLD success criterion: "the pilot outputs a measured ICC and a design effect,
and the full-sample n is derived from them rather than chosen."
NEW: pilot does not output a measured ICC; n = 216 (planning) / 261 (sensitivity).

OLD table (HEAD `9879c2e8`, arithmetic-mean M=4.9): ICC 0.1/0.2/0.3 → n 117/150/183,
and "ICC is measured, not assumed."
NEW table (Kish a=12.90, N=640): 84/124/159/**216**/**261**/327.

**Calls (frame + module).**

Frame facts used in the redesign (not `size_for_margin` outputs):

```
N=640, labeled subjects=130, Σm=544, empty present_identities=115
sum m(m-1)=6476
m≥2: 76 subjects; m≥3: 65 subjects
E[within-subject pairs at n=30] = C(30,2)*6476/(640*639) = 6.888350938967136
```

```
>>> from scripts.eval_harness.audit_sampling import size_for_margin, design_effect
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=0.2).n
216
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=0.3).n
261
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=0.045).n
121
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=0.360).n
284
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=1.0).n
423
```

Fisher-Z 95% CI at ρ=0.20, k=65, m=3: **[0.0449, 0.3595]** → published **[0.045, 0.360]**.
Implied n on a=12.90: **121..284**.
k=4, m=2, ρ=0.20: **[−0.828, 0.920]** → published [−0.83, 0.92]; implied n 84..423.

**Mutant (TEST-15).** Restore the OLD success criterion and plug a 30-image ICC
point estimate into `size_for_margin`. Fisher-Z 95% CI at true ρ=0.2 with k=4
clusters of size 2 is [−0.83, 0.92] (effectively [0, 1]). Implied n over that
CI is 84..423 — the entire planning table plus the ICC=1 cap. That is the RED:
the published n is not identified at this pilot size.

**Could not close.** Nothing. Partition (`a` vs `N`) is BR-22; grain is BR-19;
hand-typed cells are BR-23.

---

## BR-22 (high) — one PSU partition for both Kish `a` and `N`

**Canon:** AUDIT-11.

**What changed.** Declared a single image-level PSU partition used for both `a`
and `N`: unlabeled images stay in N=640 as singleton clusters; a multi-identity
image is assigned to its **first-listed** `present_identities` name. Planning
table regenerated on that partition.

| quantity | OLD | NEW |
| --- | --- | --- |
| Kish `a` (whole frame) | 12.90 (130 labeled subjects, Σm=544, applied to N=640) | **10.846875** = 6942/640 (241 PSUs, Σm=N=640) |
| planning n (ICC=0.20) | 216 | **198** |
| sensitivity n (ICC=0.30) | 261 | **239** |
| ICC table n | 84/124/159/216/261/327 | **84/118/148/198/239/302** |
| B_eyewear Kish `a` | 2.36 (75 memberships / 47 subjects, applied to N_h=80) | **2.1** = 168/80 |
| B_eyewear clustered floor | 49 | **48** |
| follow-on ICC draw | 65 subjects × 3 = 195; CI [0.045, 0.360]; n 121..284 | **64 PSUs × 3 = 192**; CI [0.044, 0.361]; n **114..261** |

The brief's overlapping-plus-singletons construction (a=10.827, n=198) keeps the
16-image overlap and is cited as a contrast, not the partition. First-listed
assignment changes `a` (10.846875 vs 10.827) but not n at ICC=0.2.

**Calls.**

```
# PSU = first present_identity, else unlabeled:{media_id}
sizes = tuple(partition_counts.values())   # 241 PSUs, sum 640, sum_sq 6942
a = kish_effective_cluster_size(sizes)     # 10.846875
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.2).n  # 198
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.3).n  # 239
size_for_margin(margin=0.10, population=80,  cluster_size=2.1, icc=0.2).n       # 48
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=1.0).n  # 397
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.044).n # 114
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.361).n # 261
```

Frame: 16 multi-identity images, 19 extra memberships, 115 empty
`present_identities`. Four identities never appear first and are not PSUs:
Auburn Hollow, Tidal Quarry, Vellum Warren, Verdant Beacon.

**Mutant (TEST-15).** Restore labeled-only `a=12.90` against N=640:
`size_for_margin(..., cluster_size=12.90, icc=0.2).n` → **216** (RED against
the published 198). Same hole at B: `cluster_size=2.36` → 49, not 48.

**Could not close.** Grain of the estimand (image vs fact) is BR-19. Display
rounding of deff (1.98 vs 1.985 → n 147 vs 148) is BR-28.

---

## BR-19 (high) — estimand grain is the image

**Canon:** AUDIT-11.

**What changed.** The doc mixed three grains: n and `fabricated_fact_rate` are
image-level, Kish `a` is images per subject, but the (now-removed) pilot
language measured "ICC on fact-level correctness". Picked **image-level** and
defined Y_i as the image's fabricated-fact indicator (caught / not), matching
`fabricated_fact_rate` (`over='all'`). Planning ICC 0.20 is image-within-subject
correlation of that Y. Fact-within-image correlation is absorbed into the
image-level aggregate and is not a second `deff` term. A fact-level n would
need a facts-per-image cluster size and composed design effects; that is not
this study.

**Why image, not fact.** n is already an image count; the PSU partition from
BR-22 is images-within-subject; `fabricated_fact_rate` is documented as
"Fraction of IMAGES caught fabricating". Facts-per-image is unknown before
annotation, so a fact-level `a` would be another assumed input the 30-image
pilot is not sized to estimate.

**Calls.** None new — this finding does not change a number. The table from
BR-22 still holds because it already sized an image-level proportion.

**Mutant (TEST-15).** Restore "intra-subject ICC on fact-level correctness"
as the quantity plugged into `deff = 1+(a−1)ρ` with a = images/subject.
That multiplies a fact-level ρ by an image-cluster `a` — the wrong `deff`.
RED against the grain paragraph.

**Could not close.** Nothing.

---

## BR-23 (high) — regenerate cells from the shipped module

**Canon:** AUDIT-09, AUDIT-10.

**What changed.** Three published cells did not reproduce. Replaced with
`allocate()` / `size_for_margin()` output. The 640/130 "arithmetic mean" contrast
was already dropped in BR-22 (the partition cluster-vector mean is 640/241 ≈ 2.66,
not 4.18). Did not touch the sibling-owned test literal.

| cell | OLD (hand-typed) | NEW (module) |
| --- | --- | --- |
| proportional n=84 | A=4, **B=10, C=4**, D=11, E=53 (Hamilton floors, sum 82) | A=4, **B=11, C=5**, D=11, E=53 (sum 84) |
| B ±12.5 pp | 35 (trunc of 35.007) | **36** (`math.ceil`) |
| B ±15 pp | 28 (trunc of 28.062) | **29** (`math.ceil`) |
| "arithmetic mean" | 640/130 ≈ 4.9 | dropped; not the mean of any cluster vector used for `a` |

**Calls.**

```
>>> sizes = project_strata_image_counts(frame["strata_counts"])
>>> dict(allocate(strata_sizes=sizes, n=84).counts)
{'A_true_occluder': 4, 'B_eyewear': 11, 'C_pose': 5, 'D_capture': 11, 'E_clean': 53}
>>> size_for_margin(margin=0.10,  population=80).n
44
>>> size_for_margin(margin=0.125, population=80).n
36
>>> size_for_margin(margin=0.15,  population=80).n
29
```

Raw after fpc before ceil: ±12.5 pp → 35.006777; ±15 pp → 28.062384.
Hamilton floors: B=10.5→10, C=4.4625→4, sum 82.

**Mutant (TEST-15).** Publish B=10, C=4, 35, 28 again. RED against the calls
above (allocate returns 11 and 5; ceil returns 36 and 29).

**Could not close.** Nothing. Sibling lane owns the matching test literal.

---

## BR-25 (doc half) — gold items and a written disagreement rule

**Canon:** HITL-03, HITL-05, HITL-07, MLDATA-03.

**What changed.** Gold items were named with no rate, provenance, or
per-annotator bar. The disagreement rule was "a written disagreement rule"
with no writing. Specified:

- Gold rate **10% of the queue** (3 images on the ~30-image pilot), mix
  random + batch-matched + hard, injected *in addition to* the probability
  sample.
- Provenance: known answers exist before the batch; not from annotators under
  test; not from the judged caption pool; operator-confirmed `reference_facts`
  or SME-arbitrated gold.
- Per-annotator gold-fact accuracy bar **≥ 0.80**; below it, hold live labels
  and retrain/replace; do not drop annotators to chase α (HITL-05).
- Written rule: agree → store shared label, keep both in `pre_adjudication`;
  disagree → SME escalation, token **`disagreement-escalate-to-sme`**; gold
  known-answers are never overwritten. Sibling enum must match that token.
  This lane did not edit the model.

**Calls.** None — no sampling number in this finding.

**Mutant (TEST-15).** Restore "gold-embedded items seeded into each batch"
with no rate/provenance/threshold, and "with a written disagreement rule"
with no rule. RED against HITL-03 ("What fraction of tasks are gold, and is
per-annotator gold accuracy tracked?") and MLDATA-03 ("What is the written
rule when annotators disagree?").

**Could not close.** The `adjudication_rule` enum lives in a sibling-owned
file (`manifest.py`). Prose pins the token; the enum must match.

---

## BR-28 (low) — print deff to three decimals so n is reproducible from the table

**Canon:** AUDIT-09.

**What changed.** Two-decimal deff was display-rounded independently of the n
beside it. On the BR-22 partition, ICC=0.1 printed deff 1.98 recomputes to
n=147, not the table's 148. Printed deff to **three decimals**; n is still
from unrounded `a=10.846875` via `size_for_margin` (ceil). The old
`a=12.90` → 327 vs exact 12.904412 → 328 defect is gone because the table
no longer uses that pin.

| ICC | OLD deff (2dp) | NEW deff (3dp) | n (unchanged, from unrounded a) |
| --- | --- | --- | --- |
| 0.05 | 1.49 | **1.492** | 118 |
| 0.1 | 1.98 | **1.985** | 148 |
| 0.2 | 2.97 | **2.969** | 198 |
| 0.3 | 3.95 | **3.954** | 239 |
| 0.5 | 5.92 | **5.923** | 302 |

**Calls.**

```
>>> a = 10.846875
>>> for icc in (0.05, 0.1, 0.2, 0.3, 0.5):
...     ss = size_for_margin(margin=0.10, population=640, cluster_size=a, icc=icc)
...     print(icc, round(ss.deff, 3), ss.n)
0.05 1.492 118
0.1 1.985 148
0.2 2.969 198
0.3 3.954 239
0.5 5.923 302
```

Recomputing n from the printed 3dp deff matches every cell. Mutant: print
ICC=0.1 deff as 1.98 → n_from_printed=147, table n=148 (RED).

**Could not close.** Nothing.

---

## Summary

Six findings, six commits, all inside `docs/scopes/descqual-2-fact-annotation-pilot.md`.
No production code. No sibling-owned files.

| finding | commit subject | closed |
| --- | --- | --- |
| BR-17 | demote 30-image draw to cost-and-instrument pilot | yes |
| BR-22 | one image-level PSU partition; planning n 216→198 | yes |
| BR-19 | estimand grain = image-level fabricated_fact_rate | yes |
| BR-23 | allocate B=11 C=5; B parentheticals 36/29 | yes |
| BR-25 | gold 10%/0.80 + written `disagreement-escalate-to-sme` | yes (enum is sibling) |
| BR-28 | deff to three decimals | yes |





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

# Lane F16 — DESCQUAL-2 provenance (BR-21, BR-25 code, BR-20)

## AdjudicationRule enum (carry this into the scope doc)

Closed set on `scripts.eval_harness.manifest.AdjudicationRule`. Doc lane must name **these exact tokens**, not free text:

- `disagreement-escalate-to-sme`
- `majority-vote`
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

## 2. `golden150-draft-20260723.json` entries[149] (media_id 648)

Two operator facts had only `annotator_id="pre-program-operator"`. No existing convention for batch/at/pool (the earlier backfill stopped at annotator_id). Established honest pre-program placeholders — **not** `_full_payload()` values, which would imply `batch-2026-08-20` / `golden-646-pool` ran:

- `annotation_batch`: `"pre-program"`
- `annotated_at`: `"1970-01-01T00:00:00Z"` (epoch sentinel; same unknown-time convention as `LEGACY_IMPORT_LABELED_AT`)
- `source_pool`: `"pre-program"`

Prefix matches `pre-program-operator`. Did not weaken `load_legacy_manifest`. Greenfield: fix the data.

Test: `test_golden150_draft_parses_with_backfilled_fact_annotators` (extended to assert the three fields).

Mutant: drop `annotation_batch` on entries[149].reference_facts[0]. RED:

```
FAILED scene/tests/test_eval_harness_manifest_reference_fact_lineage.py::test_golden150_draft_parses_with_backfilled_fact_annotators
legacy manifest schema violation: ... entries.149.reference_facts.0
Value error, human-confirmed reference_fact requires annotation_batch
(confirmed_by=<ConfirmationSource.OPERATOR: 'operator'>; MLDATA-04)
```

Canon: MLDATA-04, TEST-15, rg-008. Mutant restored. No back-compat shim.

## 3. `AdjudicationRule.MAJORITY_VOTE` token style

Scope-doc lane pinned `disagreement-escalate-to-sme` (hyphens). `majority_vote` (underscore) was the mixed-separator outlier. `UNANIMOUS = "unanimous"` has no separator. Value change only: `majority_vote` → `majority-vote`. sr-007.

Grep **before**: `MAJORITY_VOTE = "majority_vote"` in `manifest.py` plus this report and `.lane/PROMPT.txt`. No test or fixture used the underscore literal.

Grep **after**: `MAJORITY_VOTE = "majority-vote"` in `manifest.py`; leftover `majority_vote` only in this report's mutant notes / prompt.

Tests: `test_majority_vote_token_is_hyphenated`, `test_underscore_majority_vote_token_is_rejected`.

Mutant: restore `MAJORITY_VOTE = "majority_vote"`. RED:

```
FAILED ...::test_majority_vote_token_is_hyphenated
AssertionError: assert 'majority_vote' == 'majority-vote'
FAILED ...::test_underscore_majority_vote_token_is_rejected
Failed: DID NOT RAISE ValidationError
```

Canon: sr-007, TEST-15, MLDATA-03. Mutant restored. Did not touch `audit_sampling.py` or the scope doc.

## Gate

```
4 failed, 1264 passed, 4 skipped, 10 warnings in 48.33s
```

Exactly the known PGPASSWORD boot quartet (`test_create_app_registers_route_and_upload_cap` + three `test_describe_run_reclaim` startup tests). The two BR-20 leftover fixtures are green. Nothing left unclosed in owned files.

---

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

########## F21

# Lane F21 — DESCQUAL-2-BR-30

## DESCQUAL-2-BR-30 (low) — closed

Published cells `n=114` / `n=261` cited `FRAME_PSU_KISH_A`, a test-module
name at `scene/tests/test_eval_harness_audit_sampling.py:94`. Importing
from `scripts.eval_harness.audit_sampling` raised `ImportError`. The
documented command did not run as written (rg-006); the cell was not
regenerable from shipped code (AUDIT-09).

Did **not** add `FRAME_PSU_KISH_A = 10.846875` to the shipped module.

### What changed

- Scope-doc fences now load `benchmarks/manifests/fir12-selection-v1.json`,
  call `project_frame_psu_image_counts`, `kish_effective_cluster_size`,
  then `size_for_margin`. Repo-root REPL with
  `PYTHONPATH=apps/prototype-description-service`.
- Every `KISH_A` citation in the doc is gone (planning table, ICC=1 cap
  `n=397`, Fisher-Z CI `n=114`/`n=261`). They use derived `a`.
- `WHOLE_FRAME_KISH_A` / `FRAME_PSU_KISH_A` stay as test fixtures.
- `audit_sampling.py` unchanged: existing four calls suffice; no Kish-a
  literal.

Published numbers unchanged: `a=10.846875`, `n=114`, `n=261`, ICC CI
`[0.044, 0.361]`, planning `n=198`/`239`, ICC=1 cap `n=397`. 64-vs-65
untouched.

### Tests

- `test_published_cells_regenerate_from_fir12_selection_manifest` — frozen
  manifest → shipped path → `114`/`261`/`198`/`239`/`397`.
- `test_scope_doc_ci_n_fence_runs_as_written` — execs the doc fence;
  asserts no `FRAME_PSU_KISH_A` / `WHOLE_FRAME_KISH_A`.

58/58 in `test_eval_harness_audit_sampling.py`.

### Mutants (TEST-15)

**Mutant 1** — `/tmp/br30-mutant`: `kish_effective_cluster_size` returns
the arithmetic mean (`total/len(sizes)`) instead of `Σm²/Σm`.

RED: `assert 2.6556016597510372 == 10.846875 ± 1.1e-05` on both new tests.

**Mutant 2** — `/tmp/br30-mutant-floor`: `math.ceil` → `math.floor` in
`size_for_margin`.

RED: `assert 113 == 114`.

**Mutant 3** — `/tmp/br30-doc-mutant.md`: restore
`cluster_size=FRAME_PSU_KISH_A` in the CI fence.

RED: `FRAME_PSU_KISH_A` present; `cluster_size=a` missing.

Mutants restored. Real module untouched.

### Canon

AUDIT-09, rg-006, TEST-15.

### Not closed

Nothing in this finding.

########## F23

# Lane F23 — DESCQUAL-2-BR-31

## DESCQUAL-2-BR-31 (medium) — closed

`test_scope_doc_ci_n_fence_runs_as_written` exec'd the CI fence but discarded
bare `size_for_margin(...).n` expressions; trailing `# 114` / `# 261` were
compared to nothing. The test then re-asserted 114/261 from its own literals.
Same hole on the planning-n fence (`# 198` / `# 239` / `# 48`).

### What changed

- Helper `_assert_fence_published_n_matches_eval` walks each fence line,
  regex-matches trailing `# <int>` (optional parenthetical so
  `# 48  (B_eyewear)` counts), `eval`s the annotated expression in the
  exec'd namespace, and compares. Numbers are read from the doc, not
  transcribed into the test.
- Existing CI exec test kept and extended with that helper (hand-transcribed
  114/261 asserts removed).
- New sibling `test_scope_doc_planning_n_fence_runs_as_written` execs the
  planning-n fence and pins 198/239/48 the same way.
- `audit_sampling.py` untouched. Doc comments already matched shipped
  `size_for_margin` (114, 261, 198, 239, 48); no number correction.

### Tests

- `test_scope_doc_ci_n_fence_runs_as_written` — exec + pin `# 114`/`# 261`
- `test_scope_doc_planning_n_fence_runs_as_written` — exec + pin `# 198`/`# 239`/`# 48`

59/59 in `test_eval_harness_audit_sampling.py`.

### Mutants (TEST-15)

**Mutant 1** — `/tmp/br31-ci-mutant.md`: `# 114` → `# 999` in the CI fence.

RED: `test_scope_doc_ci_n_fence_runs_as_written` — `assert 114 == 999`.
Planning-n test stayed GREEN (fence isolation).

**Mutant 2** — `/tmp/br31-planning-mutant.md`: `# 198` → `# 999` in the
planning-n fence.

RED: `test_scope_doc_planning_n_fence_runs_as_written` — `assert 198 == 999`.
CI test stayed GREEN.

**Mutant 3** — `/tmp/br31-b-eyewear-mutant.md`: `# 48  (B_eyewear)` → `# 999`.

RED: `test_scope_doc_planning_n_fence_runs_as_written` — `assert 48 == 999`.

Doc restored from `/tmp/br31-orig.md`. Coordinator pre-fix mutant
(`# 114` → `# 999` left both tests GREEN) is now RED.

### Canon

rg-006, AUDIT-09, TEST-15.

### Not closed

Nothing in this finding. Allocation fence (`# 44` / `# 36` / `# 29`) is a
third fence and was not in the brief.

########## F26

# Lane F26 — DESCQUAL-2-BR-33 and BR-32

Owned files: `apps/prototype-description-service/scene/tests/test_eval_harness_audit_sampling.py`,
`docs/scopes/descqual-2-fact-annotation-pilot.md`. `audit_sampling.py` untouched.

## DESCQUAL-2-BR-33 (high) — closed

B_eyewear floor was 48 in the doc (frame-PSU a=2.1 over 80 images) and 49 in the
test (labeled-membership a=2.36=177/75 applied to population=80). AUDIT-11:
a must be a PSU partition of the frame being sized.

**What changed.** Deleted `B_EYEWEAR_KISH_A`. B-cell `a` now comes from
`project_frame_psu_image_counts` over the `B_eyewear` slice (55 PSUs, Σm=80,
Σm²=168, a=2.1). Four 49 pins are 48; allocation is B=48, E_clean=26.
Renamed `test_clustered_b_eyewear_precision_floor_is_49` → `_is_48`.
Labeled a=2.36 kept only as a diagnostic sized against its own frame
(population=75 → n=47), never against 80.
`test_estimate_icc_fisher_z_ci_for_g65_k3_at_rho_02` renamed to
`..._labeled_g65_...` and named as a labeled-`a` diagnostic (k=65 overlapping
m≥3, WHOLE_FRAME_KISH_A → 121/284), not published CI n (114/261 on
FRAME_PSU_KISH_A at k=64). Kept, not removed.

**Test.** `test_clustered_b_eyewear_precision_floor_is_48`;
`test_b_eyewear_labeled_subject_a_is_sized_against_its_own_frame`;
`test_estimate_icc_fisher_z_ci_for_labeled_g65_k3_at_rho_02`.

**Mutant.** `/tmp/br33-mutant-test.py`: restore `cluster_size = 2.36`.
RED: `assert 2.36 == 2.1 ± 2.1e-06`. Extra: four `== 48` → `== 49` with
derived a kept. RED: `assert math.ceil(n_raw) == 49` (got 48).

## DESCQUAL-2-BR-32 (low) — closed

Third fence (doc ~80–85) published `# 44` / `# 36` / `# 29` with no pin, no
imports, unbound `strata_counts` (rg-006). Mutating `# 44` → `# 999` left
both BR-31 fence tests GREEN.

**What changed.** Fence is self-contained (imports + `strata_counts` from
`fir12-selection-v1.json`). New
`test_every_scope_doc_size_for_margin_fence_published_n_matches_eval`
execs every fence containing `size_for_margin(`, not a per-fence allowlist.

**Test.** `test_every_scope_doc_size_for_margin_fence_published_n_matches_eval`
(existing CI/planning identity tests kept).

**Mutants.** `/tmp/br32-ci-mutant.md` `# 114`→`# 999` RED `assert 114 == 999`.
`/tmp/br32-planning-mutant.md` `# 198`→`# 999` RED `assert 198 == 999`.
`/tmp/br32-bfloor-mutant.md` `# 44`→`# 999` RED `assert 44 == 999` on the
general test; named CI+planning tests stayed GREEN (old hole).

61/61 in `test_eval_harness_audit_sampling.py`.

### Canon

AUDIT-11, AUDIT-09, rg-006, TEST-15.

### Not closed

Nothing in this finding.

########## N8

# Lane N8 — DESCQUAL-2 pilot draw and annotation packet

New `scripts/eval_harness/pilot_draw.py` + `scene/tests/test_eval_harness_pilot_draw.py`.
Cost-and-instrument pilot only (BR-17): no ICC, no deff, no full-study n.

- **draw_pilot** — `allocate` then `draw`; every unit keeps `inclusion_probability`; same seed+manifest → identical sha256 list. Test: `test_draw_pilot_is_reproducible_under_seed`. Mutant `/tmp/pilot_draw_mutant_ignore_seed.py`: `draw(..., seed=0)` ignoring caller seed. RED: `assert first_ids != other_ids` (lists equal).
- **emit_annotation_packet** — one packet per drawn image; two `annotator_slots`; `reference_facts: []`; skeleton `ReferenceFact(confirmed_by=operator, annotator_id=slot)` constructs. Tests: `test_emit_annotation_packet_is_one_dual_annotator_row_per_drawn_image`, `test_packet_reference_fact_skeleton_requires_annotator_id`.
- **select_gold_items** — 10% of n (3 on the ~30-image pilot), from the frozen frame *outside* the drawn sample, mix random + batch-matched + hard. Test: `test_gold_items_are_outside_the_drawn_sample`. Mutant `/tmp/pilot_draw_mutant_gold_from_sample.py`: remaining = sample unit ids. RED: `assert gold_ids.isdisjoint(sampled)`.
- **GoldItem provenance** — constructor refuses caption-pool source and a live-queue author (HITL-03). Tests: `test_gold_item_refuses_caption_pool_source`, `test_gold_item_refuses_live_queue_author`.
- **report_rows** — per-stratum `N_h`/`n_h`/`inclusion_probability` plus `declared_empty_cells` passed through verbatim (MLDATA-09, rg-015). Test: `test_report_rows_do_not_recompute_declared_empty_cells`. Mutant `/tmp/pilot_draw_mutant_recompute_empty.py`: emit empty-count strata instead of the JSON list. RED: `[] == ['never-recompute-me', 'mask_sufficient_n']`.
- **No replacement draws** (AUDIT-13). Test: `test_public_surface_has_no_replacement_draw_path`.
- **No ICC/deff** (BR-17). Test: `test_pilot_module_does_not_estimate_icc_or_deff`.

`scene/tests/test_eval_harness_pilot_draw.py`: **23 passed**.
Full `scene/tests`: **4 failed, 1316 passed, 4 skipped** (four PGPASSWORD boot failures pre-existing).

########## N10a

# Lane N10a — DESCQUAL-2-BR-36 / BR-41 / BR-42

Owned files: `apps/prototype-description-service/scripts/eval_harness/pilot_draw.py`, `apps/prototype-description-service/scene/tests/test_eval_harness_pilot_draw.py`.

- **DESCQUAL-2-BR-36 (high)** — `select_gold_items` no longer prefix-slices the HITL-03 mix; `gold_n < 3` raises `PilotDrawError` naming `hard, batch_matched, random` and `n=23`. Remainder after one-of-each is round-robin over `GOLD_MIX_ORDER`. Tests: `test_gold_mix_refuses_truncation_when_gold_n_below_three` (n=14 → gold_n=2), `test_gold_mix_round_robin_remainder_not_dumped_on_one_kind` (n=84 → 3 of each). Mutant `/tmp/n10a-proof` prefix slice `mix[: min(3, gold_n)]` + drop mix raise: RED `DID NOT RAISE PilotDrawError` at gold_n=2. Mutant remainder `mix[0]` (HARD): RED `{HARD: 7, BATCH_MATCHED: 1, RANDOM: 1} != {3,3,3}`.

- **DESCQUAL-2-BR-41 (medium)** — loader guards unchanged; pinned by parametrized `test_draw_pilot_rejects_loader_guard_violations` (12 cases: missing strata_counts/entries/sha256/media_id/source_path/present_identities, duplicate sha256, present_identities type, empty source_path, empty entries, unknown strata_counts key, declared_empty_cells type `"veil"`). Mutant: delete each guard in turn under `/tmp/n10a-proof`; parametrized case RED **12/12**.

- **DESCQUAL-2-BR-42 (medium)** — (1) `_gold_count` is `round(n * rate / (1 - rate))` so gold is `GOLD_RATE_PERCENT` of the annotation queue `n+g` (n=30→3, 84→9, 198→22). (2) Rate pinned by `test_gold_count_is_rate_of_annotation_queue` plus `g/(n+g)` within half an item of 10%; `test_three_gold_items_become_available_at_n_23`. Mutant `if n < 10: return n * GOLD_RATE_PERCENT // 100; return 3`: RED `assert 3 == 9` at n=84 and `assert 3 == 22` at n=198 (n=30 stayed GREEN). (3) `PilotDraw.frame_sha256s` carried from the FIR-12 frame; `select_gold_items` hard-errors on any caller sha not in that set. Test: `test_select_gold_items_rejects_sha_outside_frozen_frame`. Mutant drop the foreign-sha check: RED `DID NOT RAISE PilotDrawError`.

`scene/tests/test_eval_harness_pilot_draw.py`: **42 passed** (was 23).
