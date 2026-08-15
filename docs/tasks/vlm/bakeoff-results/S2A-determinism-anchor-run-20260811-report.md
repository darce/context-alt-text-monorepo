# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `seeded-fixtures` version(s): `1`
- head_sha: `null`
- base_url: seeded-stub://offline
- fetch manifest_sha256: `4c67445152a933ecdc60914e45c75b7c580cf11ba3936e6ef46ebee996684bde`
- score manifest_sha256: `4c67445152a933ecdc60914e45c75b7c580cf11ba3936e6ef46ebee996684bde` (matches fetch: true)
- started_at: null
- images: 39/39 scored, 0 failed
- quality_floor_caveat: position_accuracy/placement floors are binary-chance (0.5); accuracy at the floor fails the gate
- verdict: **fail** (wrong_name_rate=0.103, floor=0.000)
- rubric_gate: `skip`
- verdict reason: wrong_name_rate=0.1026 exceeds floor=0.0 (wrong_names=4, wrong_name_images=4, assertions=4, ignored=0, scored=39)
- verdict reason: quality-floor: position_accuracy=0.0 <= floor=0.5 (critical scored slice total failure; EVAL-04 / S2-02)
- verdict reason: category-vacuity: placement — claim unit=asserted spatial_fact; claims=0 accuracy=None abstained=0 images_scored=39 (π=0 on spatial_facts; AUDIT-07)
- verdict reason: category-vacuity: fabricated_fact — claim unit=image with reference_facts trap; fabricated_fact_rate=None images_with_traps=0 (not measurable; AUDIT-07 / S2-01)
- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline.

## Caption metrics (deterministic tier)

- insertion rate: 0.000
- name precision: null (wrong-name images: 0, rate: 0.000)
- Must-Right failed images (hard gate): 34 (must_right-defined images: 34; easy_wrong-defined images: 37)
- policy violations: 0
- mean gated score: 0.000 (scored=36, excluded=3)
- fabricated-fact rate: null (caught=0/0 trap images; instances=0/0)
- fabricated by kind: none
- true-fact coverage: null
- placement accuracy: null (correct=0 wrong=0 claims=0 abstained=0)
- ⚠️ **placement is VACUOUS**: 0 asserted claims — every spatial fact was abstained or the corpus defines no `spatial_facts`. The accuracy above is not evidence of placement correctness.

### Strata (difficulty / domain)

- difficulty=easy: n=18 mean_gated=0.000 wrong_name_images=0 placement=null positional=0.000 (compared=1)
- difficulty=hard: n=11 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- difficulty=medium: n=10 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=art: n=2 mean_gated=null wrong_name_images=0 placement=null positional=null (compared=0)
- domain=crowds: n=6 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=faces: n=21 mean_gated=0.000 wrong_name_images=0 placement=null positional=0.000 (compared=1)
- domain=low_light: n=1 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=mirrors: n=2 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=occlusion: n=3 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=people: n=4 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)

## Quality axes (short surface, report-only signals)

- meta-framing images: 0
- mean context duplication: 0.000
- name front-loaded rate: 0.000
- sentence band [1, 4] ok rate: 1.000
- mean FKRE: 65.120
- mean repetition ratio: 0.057
- mean tag coverage: 0.684
- first-sentence gist ok rate: 1.000

## Face detection (identity-agnostic)

- precision: 0.948 recall: 0.902 (tp=55 fp=3 fn=6)

## Face identification (named assertions)

- micro precision: 0.892 recall: 0.825
- macro precision: 0.714 recall: 0.903
- true rejections (strangers): 7
- positional accuracy (L→R order): 0.000 (hits=0 / 2; exact-order images=0/1; swaps=1; status=scored; evaluable=True)
- ⚠ labeled L→R y-missing (order_degraded) on 1 image(s): `mock_images/y-missing-mixed-order.jpg`
- ⚠ identity order unknown (no face_boxes) on 38 image(s) — positional excluded

### Wrong-name errors (top product risk — every instance listed)

- `mock_images/ccqw-purple.jpg` → asserted **Fixture-Wrong-9**
- `mock_images/k.mcc-1.jpg` → asserted **Fixture-Wrong-18**
- `mock_images/maria-party.jpg` → asserted **Fixture-Wrong-27**
- `mock_images/ryann-party.jpg` → asserted **Fixture-Wrong-36**
- ignored (triaged): 0

### Per-identity (macro components)

- Bea Burke: precision=1.000 recall=1.000 (tp=2 fp=0 fn=0)
- Caitlin Weaver: precision=1.000 recall=0.812 (tp=13 fp=0 fn=3)
- Cristina Quintana: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Daniel Arce: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Ellyn Heald: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Erika Hansen Miller: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Fixture-Wrong-18: precision=0.000 recall=null (tp=0 fp=1 fn=0)
- Fixture-Wrong-27: precision=0.000 recall=null (tp=0 fp=1 fn=0)
- Fixture-Wrong-36: precision=0.000 recall=null (tp=0 fp=1 fn=0)
- Fixture-Wrong-9: precision=0.000 recall=null (tp=0 fp=1 fn=0)
- Kirstie Mccarrel: precision=1.000 recall=0.800 (tp=4 fp=0 fn=1)
- Liam Maloney: precision=1.000 recall=1.000 (tp=2 fp=0 fn=0)
- Maria Correonero: precision=1.000 recall=0.750 (tp=6 fp=0 fn=2)
- Ryann Wiseman: precision=1.000 recall=0.667 (tp=2 fp=0 fn=1)

## Per-item failures

- none

## Coverage gaps (sampling frame — AUDIT-07)

Face metrics in this freeze are **non-evidential** (predictions_source=ground_truth_derived_fixture; face_metrics_evidential=false).
This artifact certifies scoring-path byte-stability only.

- `demographic_cohort`: 0/39 entries populate it (threshold=5) — demographic/cohort fairness slices have no sampling frame
- `face_boxes`: 2/39 entries populate it (threshold=5) — positional_identification never runs; set-based identity scoring cannot catch right-names-on-wrong-faces
- `reference_facts`: 0/39 entries populate it (threshold=5) — no trap coverage for fabricated-fact scoring (rate is undefined)
- `spatial_facts`: 0/39 entries populate it (threshold=5) — placement accuracy is vacuous (0 asserted claims)

### Metric-backing refusals (require_metric_backing)

- `demographic_cohort`: cannot certify metric backed by 'demographic_cohort': 0/39 entries populate that field (vacuous corpus-wide; per-stratum gate would collapse to a single bucket). Declared coverage gap: owner=FIR-5; action=label roster_cohorts / demographic_cohort after operator cohort definitions land — no labelled source exists yet.
- `reference_facts`: cannot certify metric backed by 'reference_facts': 0/39 entries populate that field (vacuous corpus-wide; per-stratum gate would collapse to a single bucket). Declared coverage gap: owner=VLM-6-operator; action=author polarity-tagged reference_facts per image after a visual pass — cannot be derived from filename/face_count alone.
- `spatial_facts`: cannot certify metric backed by 'spatial_facts': 0/39 entries populate that field (vacuous corpus-wide; per-stratum gate would collapse to a single bucket). Declared coverage gap: owner=VLM-6-operator; action=author spatial relations from curated boxes — no box geometry is vendored for the full corpus.
