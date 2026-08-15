# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `fusion-eval-adhoc-stub` version(s): `1`
- head_sha: `6688d4c904f4fa8031952dc5bae12582fcfee2c9`
- base_url: fusion-runner://adhoc
- fetch manifest_sha256: `04d5712a8c8163d14e2fbed084739f1a701b112d96db95fb648ebfc096e78cfd`
- score manifest_sha256: `04d5712a8c8163d14e2fbed084739f1a701b112d96db95fb648ebfc096e78cfd` (matches fetch: True)
- started_at: 2026-08-15T01:32:34Z
- images: 10/10 scored, 0 failed
- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline.

## Caption metrics (deterministic tier)

- insertion rate: 1.000
- name precision: 0.900 (wrong-name images: 1, rate: 0.100)
- Must-Right failed images (hard gate): 0 (rubric-defined images: 8)
- policy violations: 0
- mean gated score: 0.889

## Quality axes (short surface, report-only signals)

- meta-framing images: 2
- mean context duplication: null
- name front-loaded rate: 1.000
- sentence band [1, 4] ok rate: 0.800

## Face detection (identity-agnostic)

- REFUSED (detection_refuses_roster_only): detection P/R is not computed unless annotation_mode is exhaustive

## Face identification (named assertions)

- micro precision: 1.000 recall: 0.889
- macro precision: 1.000 recall: 0.857
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
- Maria Correonero: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Ryann Wiseman: precision=1.000 recall=1.000 (tp=2 fp=0 fn=0)

## Per-item failures

- none

## Mis-attachment (E20-FUSION)

- labeled facts: 12
- mis-attachments: 4
- `mock_images/liam-maloney-painting.jpg` identity/Liam Maloney: expected dropped visible=False, actual object visible=True (decision_or_visible_mismatch)
- `mock_images/mcm-planecrash.jpg` identity/Maria Correonero: expected dropped visible=False, actual object visible=True (decision_or_visible_mismatch)
- `mock_images/mcm-planecrash.jpg` event/Garden picnic: expected caption visible=False, actual object visible=True (decision_or_visible_mismatch)
- `mock_images/mcm-planecrash.jpg` place/Summer garden: expected caption visible=False, actual object visible=True (decision_or_visible_mismatch)

