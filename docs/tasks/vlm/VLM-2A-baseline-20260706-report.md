# Caption + Face Eval Report

- schema: `acx-eval/v1`
- head_sha: `2fe574fac42acc260afd04ccfb2fdb68774459d8`
- base_url: https://api.altcontext.com
- manifest_sha256: `9f9b134a71e5e1c2e5aa361d7139680081877841abefc0c4f3f7c55917e9927c`
- started_at: 2026-07-06T20:11:45Z
- images: 38/38 scored, 0 failed

## Caption metrics (deterministic tier)

- insertion rate: 0.000
- Must-Right failed images (hard gate): 0
- policy violations: 0
- mean gated score: 0.079

## Face detection (identity-agnostic)

- precision: 0.545 recall: 0.973 (tp=36 fp=30 fn=1)

## Face identification (named assertions)

- micro precision: 1.000 recall: 0.297
- macro precision: 1.000 recall: 0.331
- true rejections (strangers): 0

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
- Kirstie Mccarrel: precision=1.000 recall=0.333 (tp=2 fp=0 fn=4)
- Liam Maloney: precision=1.000 recall=1.000 (tp=2 fp=0 fn=0)
- Maria Correonero: precision=1.000 recall=0.571 (tp=4 fp=0 fn=3)
- Ryann Wiseman: precision=1.000 recall=0.333 (tp=1 fp=0 fn=2)

## Per-item failures

- none
