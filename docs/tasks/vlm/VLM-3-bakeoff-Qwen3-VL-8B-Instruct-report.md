# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `bakeoff` model(s): `Qwen3-VL-8B-Instruct` version(s): `F16`
- head_sha: `2cf7898a449e5ecb3275e89ef868193680f38a7d`
- base_url: http://localhost:18000
- fetch manifest_sha256: `670e257aef0c4eabb6480241be8c38521a494ae24d356e1fdcaa1bb49601b6ca`
- score manifest_sha256: `670e257aef0c4eabb6480241be8c38521a494ae24d356e1fdcaa1bb49601b6ca` (matches fetch: True)
- started_at: 2026-07-14T08:05:34Z
- images: 10/10 scored, 0 failed
- ⚠ produced by the throwaway `bakeoff` transport (VLM-2B) — face detection/identification sections below are **vacuous by design** (stub `analyze`/`media_identities`); 0% is expected, NOT a recognition regression.

## Caption metrics (deterministic tier)

- insertion rate: 0.222
- Must-Right failed images (hard gate): 7 (rubric-defined images: 8)
- policy violations: 0
- mean gated score: 0.222

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
