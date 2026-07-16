# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `seeded-fixtures` version(s): `1`
- head_sha: `72d59b8ecdfddfe6927e072d01526953a37bd3f2`
- base_url: https://api.altcontext.com
- fetch manifest_sha256: `67040d4513998674151a48f49f59c7f19c59caf05d0949e7dffcb88199124332`
- score manifest_sha256: `67040d4513998674151a48f49f59c7f19c59caf05d0949e7dffcb88199124332` (matches fetch: True)
- started_at: 2026-07-14T21:47:35Z
- images: 37/37 scored, 0 failed
- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline.

## Caption metrics (deterministic tier)

- insertion rate: 0.000
- Must-Right failed images (hard gate): 34 (rubric-defined images: 37)
- policy violations: 0
- mean gated score: 0.081

## Face detection (identity-agnostic)

- precision: 0.857 recall: 0.947 (tp=54 fp=9 fn=3)

## Face identification (named assertions)

- micro precision: 1.000 recall: 0.333
- macro precision: 1.000 recall: 0.358
- true rejections (strangers): 10

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
- Kirstie Mccarrel: precision=1.000 recall=0.600 (tp=3 fp=0 fn=2)
- Liam Maloney: precision=1.000 recall=1.000 (tp=2 fp=0 fn=0)
- Maria Correonero: precision=1.000 recall=0.571 (tp=4 fp=0 fn=3)
- Ryann Wiseman: precision=1.000 recall=0.333 (tp=1 fp=0 fn=2)

## Per-item failures

- none
