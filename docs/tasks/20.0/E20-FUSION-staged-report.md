# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `fusion-eval-stub` version(s): `1`
- head_sha: `4ffc1a0af916b452f20eb207136e0d5ab4163b55`
- base_url: fusion-runner://staged
- fetch manifest_sha256: `e234340721c7cf8c12376dbe566e0a28c1d88562371d19b10eb4f6e996635117`
- score manifest_sha256: `e234340721c7cf8c12376dbe566e0a28c1d88562371d19b10eb4f6e996635117` (matches fetch: True)
- started_at: 2026-07-10T03:27:23Z
- images: 10/10 scored, 0 failed
- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline.

## Caption metrics (deterministic tier)

- insertion rate: 1.000
- Must-Right failed images (hard gate): 0 (rubric-defined images: 8)
- policy violations: 0
- mean gated score: 0.900

## Face detection (identity-agnostic)

- precision: 1.000 recall: 0.941 (tp=16 fp=0 fn=1)

## Face identification (named assertions)

- micro precision: 1.000 recall: 1.000
- macro precision: 1.000 recall: 1.000
- true rejections (strangers): 2

### Wrong-name errors (top product risk — every instance listed)

- none
- ignored (triaged): 0

### Per-identity (macro components)

- Bea Burke: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Caitlin Weaver: precision=1.000 recall=1.000 (tp=2 fp=0 fn=0)
- Daniel Arce: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Erika Hansen Miller: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Kirstie Mccarrel: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Maria Correonero: precision=1.000 recall=1.000 (tp=1 fp=0 fn=0)
- Ryann Wiseman: precision=1.000 recall=1.000 (tp=2 fp=0 fn=0)

## Per-item failures

- none

## Mis-attachment (E20-FUSION)

- labeled facts: 12
- mis-attachments: 0
- none

