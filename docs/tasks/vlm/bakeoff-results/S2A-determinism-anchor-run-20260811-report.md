# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `seeded-fixtures` version(s): `1`
- head_sha: `0000000000000000000000000000000000000000`
- base_url: seeded-stub://offline
- fetch manifest_sha256: `83bfdc4e50b441dd60f4d7b6613dac57f42e8bb1e216f53cfeab147984cfd737`
- score manifest_sha256: `83bfdc4e50b441dd60f4d7b6613dac57f42e8bb1e216f53cfeab147984cfd737` (matches fetch: True)
- started_at: 2026-08-11T00:00:00Z
- images: 37/37 scored, 0 failed
- verdict: **pass_ungated** (wrong_name_rate=0.000, floor=0.000)
- rubric_gate: `skip`
- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline.

## Caption metrics (deterministic tier)

- insertion rate: 0.000
- name precision: null (wrong-name images: 0, rate: 0.000)
- Must-Right failed images (hard gate): 34 (must_right-defined images: 34; easy_wrong-defined images: 37)
- policy violations: 0
- mean gated score: 0.000 (scored=34, excluded=3)
- fabricated-fact rate: 0.000 (caught=0/0 trap images; instances=0/0)
- fabricated by kind: none
- true-fact coverage: null
- placement accuracy: null (correct=0 wrong=0 claims=0 abstained=0)

### Strata (difficulty / domain)

- difficulty=easy: n=16 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- difficulty=hard: n=11 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- difficulty=medium: n=10 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=art: n=2 mean_gated=null wrong_name_images=0 placement=null positional=null (compared=0)
- domain=crowds: n=6 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=faces: n=19 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=low_light: n=1 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=mirrors: n=2 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=occlusion: n=3 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)
- domain=people: n=4 mean_gated=0.000 wrong_name_images=0 placement=null positional=null (compared=0)

## Quality axes (short surface, report-only signals)

- meta-framing images: 0
- mean context duplication: 0.000
- name front-loaded rate: 0.000
- sentence band [1, 4] ok rate: 1.000
- mean FKRE: 64.900
- mean repetition ratio: 0.056
- mean tag coverage: 0.685
- first-sentence gist ok rate: 1.000

## Face detection (identity-agnostic)

- precision: 1.000 recall: 1.000 (tp=57 fp=0 fn=0)

## Face identification (named assertions)

- micro precision: 1.000 recall: 1.000
- macro precision: 1.000 recall: 1.000
- true rejections (strangers): 10
- positional accuracy (L→R order): null (hits=0 / 0; exact-order images=0/0; swaps=0)
- ⚠ identity ordering degraded on 37 image(s) (missing/malformed bbox → not pure L→R): `mock_images/Breiðamerkurjökull.jpg`, `mock_images/bea-nye.jpg`, `mock_images/ccqw-antartica.jpg`, `mock_images/ccqw-bar.jpg`, `mock_images/ccqw-erika.jpg`, `mock_images/ccqw-flowers.jpg`, `mock_images/ccqw-hair.jpg`, `mock_images/ccqw-occlusion-2.jpg`, `mock_images/ccqw-occlusion.jpg`, `mock_images/ccqw-purple.jpg`, `mock_images/ccqw-running-2.jpg`, `mock_images/ccqw-running.jpg`, `mock_images/ccqw-sunglasses-flowers.jpg`, `mock_images/ccqw-sunglasses.jpg`, `mock_images/ccqw-underexposed.jpg`, `mock_images/ccqw.blurry.jpg`, `mock_images/cristina-1.jpg`, `mock_images/example-ellynheald-goldleaf.jpeg`, `mock_images/k.mcc-1.jpg`, `mock_images/kirstie-1.jpeg`, `mock_images/kirstie-boat.jpg`, `mock_images/kirstie-daniel-sunglasses.jpg`, `mock_images/kirstie-pool.jpg`, `mock_images/liam-maloney-2.jpg`, `mock_images/liam-maloney-home.jpg`, `mock_images/liam-maloney-painting.jpg`, `mock_images/maria-cocktail.jpg`, `mock_images/maria-party.jpg`, `mock_images/maria-pool.jpg`, `mock_images/mcm-eye-blocked.jpg`, `mock_images/mcm-icecave.jpg`, `mock_images/mcm-planecrash.jpg`, `mock_images/nina-machiavelli.jpeg`, `mock_images/rrw-mirror.jpg`, `mock_images/ryann-bar.jpg`, `mock_images/ryann-group-party.jpg`, `mock_images/ryann-party.jpg`

### Wrong-name errors (top product risk — every instance listed)

- none
- ignored (triaged): 0

### Per-identity (macro components)

- Bea Burke: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Caitlin Weaver: precision=1.000 recall=1.000 (tp=14 fp=0 fn=0)
- Cristina Quintana: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Daniel Arce: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Ellyn Heald: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Erika Hansen Miller: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Kirstie Mccarrel: precision=1.000 recall=1.000 (tp=5 fp=0 fn=0)
- Liam Maloney: precision=1.000 recall=1.000 (tp=2 fp=0 fn=0)
- Maria Correonero: precision=1.000 recall=1.000 (tp=7 fp=0 fn=0)
- Ryann Wiseman: precision=1.000 recall=1.000 (tp=3 fp=0 fn=0)

## Per-item failures

- none
