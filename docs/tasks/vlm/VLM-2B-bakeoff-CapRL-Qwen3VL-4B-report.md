# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `bakeoff` model(s): `CapRL-Qwen3VL-4B` version(s): `Q4_K_M`
- head_sha: `7537eca39b9d19782f432a1fa5759597983c604c`
- base_url: http://127.0.0.1:8099
- fetch manifest_sha256: `1701e471455afd740c5c1474d81dee9a0c470efe253a167f55f15202ea65952b`
- score manifest_sha256: `73cbe11306079262f3c97ddc620499e19cb85d432f9b7c87bf9c5b0911f86539` (matches fetch: False)
- started_at: 2026-07-07T16:33:42Z
- images: 10/10 scored, 0 failed
- ⚠ produced by the throwaway `bakeoff` transport (VLM-2B) — face detection/identification sections below are **vacuous by design** (stub `analyze`/`media_identities`); 0% is expected, NOT a recognition regression.

## Caption metrics (deterministic tier)

- insertion rate: 1.000
- name precision: 0.900 (wrong-name images: 1, rate: 0.100)
- Must-Right failed images (hard gate): 0 (rubric-defined images: 8)
- policy violations: 0
- mean gated score: 0.889

## Quality axes (short surface, report-only signals)

- meta-framing images: 2
- mean context duplication: 0.061
- name front-loaded rate: 1.000
- sentence band [1, 4] ok rate: 1.000

## Face detection (identity-agnostic)

- REFUSED (detection_refuses_roster_only): detection P/R is not computed unless annotation_mode is exhaustive

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
