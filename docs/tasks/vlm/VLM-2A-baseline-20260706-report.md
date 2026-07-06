# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `seeded-fixtures` version(s): `1`
- head_sha: `2fe574fac42acc260afd04ccfb2fdb68774459d8`
- base_url: https://api.altcontext.com
- fetch manifest_sha256: `9f9b134a71e5e1c2e5aa361d7139680081877841abefc0c4f3f7c55917e9927c`
- score manifest_sha256: `ee94088b7cc9d43532b8457c3787251877328f5f800375c942b245218bee5fe0` (matches fetch: False)
- started_at: 2026-07-06T20:11:45Z
- images: 37/37 scored, 0 failed
- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline.
- ⚠ no Must-Right/Easy-Wrong rubric entries in the corpus — the caption hard gate is vacuous.

## Caption metrics (deterministic tier)

- insertion rate: 0.000
- Must-Right failed images (hard gate): 0 (rubric-defined images: 0)
- policy violations: 0
- mean gated score: 0.081

## Face detection (identity-agnostic)

- precision: 0.762 recall: 0.941 (tp=48 fp=15 fn=3)

## Face identification (named assertions)

- micro precision: 1.000 recall: 0.306
- macro precision: 1.000 recall: 0.338
- true rejections (strangers): 6

### Wrong-name errors (top product risk — every instance listed)

- none
- ignored (triaged): 0

### Per-identity (macro components)

- Bea Burke: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Caitlin Weaver: precision=1.000 recall=0.071 (tp=1 fp=0 fn=13)
- Cristina Quintana: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Daniel Arce: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Ellyn Heald: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Erika Hansen Miller: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Kirstie Mccarrel: precision=1.000 recall=0.400 (tp=2 fp=0 fn=3)
- Liam Maloney: precision=1.000 recall=1.000 (tp=2 fp=0 fn=0)
- Maria Correonero: precision=1.000 recall=0.571 (tp=4 fp=0 fn=3)
- Ryann Wiseman: precision=1.000 recall=0.333 (tp=1 fp=0 fn=2)

## Per-item failures

- none
