# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `seeded-fixtures` version(s): `1`
- head_sha: `b9fe952f2be5f5070025d881e2b040f5feeac57b`
- base_url: seeded://stub
- fetch manifest_sha256: `003b4a52cbaceee8ef7e931917cb12ad7a41c42389dd967a14d781eca1c3bd64`
- score manifest_sha256: `003b4a52cbaceee8ef7e931917cb12ad7a41c42389dd967a14d781eca1c3bd64` (matches fetch: True)
- started_at: 2026-07-07T00:00:00Z
- images: 37/37 scored, 0 failed
- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline.

## Caption metrics (deterministic tier)

- insertion rate: 1.000
- Must-Right failed images (hard gate): 0 (rubric-defined images: 37)
- policy violations: 0
- mean gated score: 1.000

## Face detection (identity-agnostic)

- precision: 1.000 recall: 1.000 (tp=57 fp=0 fn=0)

## Face identification (named assertions)

- micro precision: 1.000 recall: 1.000
- macro precision: 1.000 recall: 1.000
- true rejections (strangers): 10

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
