# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `seeded-fixtures` version(s): `1`
- head_sha: `0000000000000000000000000000000000000000`
- base_url: seeded-stub://offline
- fetch manifest_sha256: `859a083ee2594b993543e52d9a5c5c9b13e4b98c7c2b87bc390bff8b29c6f123`
- score manifest_sha256: `859a083ee2594b993543e52d9a5c5c9b13e4b98c7c2b87bc390bff8b29c6f123` (matches fetch: True)
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
- mean gated score: 0.081

## Quality axes (short surface, report-only signals)

- meta-framing images: 0
- mean context duplication: 0.000
- name front-loaded rate: 0.000
- sentence band [1, 4] ok rate: 1.000

## Face detection (identity-agnostic)

- precision: 1.000 recall: 1.000 (tp=57 fp=0 fn=0)

## Face identification (named assertions)

- micro precision: 1.000 recall: 1.000
- macro precision: 1.000 recall: 1.000
- true rejections (strangers): 10
- positional accuracy (L→R order): null (hits=0 / 0; exact-order images=0/0; swaps=0)

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
