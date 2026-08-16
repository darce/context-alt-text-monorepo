# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `fusion-eval-adhoc-stub` version(s): `1`
- head_sha: `e4f1730f3c697f6abd6afefb817310de76f3f0c2`
- base_url: fusion-runner://adhoc
- fetch manifest_sha256: `2182b97628d855e7d7a7b2e8afbc73582dde59198d3030a66e6a1ea35fe9dbd9`
- score manifest_sha256: `73cbe11306079262f3c97ddc620499e19cb85d432f9b7c87bf9c5b0911f86539` (matches fetch: False)
- started_at: 2026-07-10T05:05:05Z
- images: 10/10 scored, 0 failed
- notes: S2R4-15 S2R3-08 (commit 8a9db2c2) re-scored this report against bakeoff_golden.json: faces.identification p=1.0 r=0.889 true_rejections=2 per_identity=7 → REFUSED(identification_refuses_unboxed_identity_claims); score_manifest 04d5712a→73cbe113 (matches fetch True→False). Caption axes were not rewritten. Run-record producer stamps were restored separately (S2R3-15).
- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline.

## Caption metrics (deterministic tier)

- insertion rate: 1.000
- name precision: 0.900 (wrong-name images: 1, rate: 0.100)
- Must-Right failed images (hard gate): 0 (rubric-defined images: 8)
- policy violations: 0
- mean gated score: 0.889

## Quality axes (short surface, report-only signals)

- meta-framing images: 2
- mean context duplication: 0.768
- name front-loaded rate: 1.000
- sentence band [1, 4] ok rate: 0.800

## Face detection (identity-agnostic)

- REFUSED (detection_refuses_roster_only): detection P/R is not computed unless annotation_mode is exhaustive

## Face identification (named assertions)

- REFUSED (identification_refuses_unboxed_identity_claims): identification P/R is not computed from identity claims that carry no per-face box lineage

## Per-item failures

- none

## Mis-attachment (E20-FUSION)

- labeled facts: 12
- mis-attachments: 4
- `mock_images/liam-maloney-painting.jpg` identity/Liam Maloney: expected dropped visible=False, actual object visible=True (decision_or_visible_mismatch)
- `mock_images/mcm-planecrash.jpg` identity/Maria Correonero: expected dropped visible=False, actual object visible=True (decision_or_visible_mismatch)
- `mock_images/mcm-planecrash.jpg` event/Garden picnic: expected caption visible=False, actual object visible=True (decision_or_visible_mismatch)
- `mock_images/mcm-planecrash.jpg` place/Summer garden: expected caption visible=False, actual object visible=True (decision_or_visible_mismatch)

