# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `bakeoff` model(s): `CapRL-Qwen3VL-4B` version(s): `Q4_K_M`
- head_sha: `7537eca39b9d19782f432a1fa5759597983c604c`
- base_url: http://127.0.0.1:8099
- fetch manifest_sha256: `1701e471455afd740c5c1474d81dee9a0c470efe253a167f55f15202ea65952b`
- score manifest_sha256: `1701e471455afd740c5c1474d81dee9a0c470efe253a167f55f15202ea65952b` (matches fetch: True)
- started_at: 2026-07-07T16:33:42Z
- images: 10/10 scored, 0 failed

## Caption metrics (deterministic tier)

- insertion rate: 1.000
- Must-Right failed images (hard gate): 0 (rubric-defined images: 9)
- policy violations: 0
- mean gated score: 0.900

## Face detection (identity-agnostic)

- precision: null recall: 0.000 (tp=0 fp=0 fn=17)

## Face identification (named assertions)

- micro precision: null recall: 0.000
- macro precision: null recall: 0.000
- true rejections (strangers): 2

### Wrong-name errors (top product risk — every instance listed)

- none
- ignored (triaged): 0

### Per-identity (macro components)

- Bea Burke: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Caitlin Weaver: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Daniel Arce: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Erika Hansen Miller: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Kirstie Mccarrel: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Maria Correonero: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Ryann Wiseman: precision=null recall=0.000 (tp=0 fp=0 fn=2)

## Per-item failures

- none
