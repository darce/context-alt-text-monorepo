# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `seeded` model(s): `seeded-fixtures` version(s): `1`
- head_sha: `72d59b8ecdfddfe6927e072d01526953a37bd3f2`
- base_url: https://api.altcontext.com
- fetch manifest_sha256: `67040d4513998674151a48f49f59c7f19c59caf05d0949e7dffcb88199124332`
- score manifest_sha256: `fc7ce54817e521460c38a2034c84c6537f9a13e78c18b080d5f78f80ae2a8d1d` (matches fetch: False)
- started_at: 2026-07-14T21:47:35Z
- images: 37/37 scored, 0 failed
- notes: S2R4-15 F23-G disclosure at code 896bd17d4277b83ba54993007cb8ae5bbe2e0de7: S2R4-18: S2R3-06 republish substituted today's golden (fc7ce548) for the fetch-time manifest (67040d45, matches fetch was True). The original was not roster_only-ambiguous. Current faces.identification is REFUSED(identification_refuses_unboxed_identity_claims); this wave did not re-score the run-record (already an honest refusal).
- notes: S2R4-18 provenance: fetch=67040d4513998674151a48f49f59c7f19c59caf05d0949e7dffcb88199124332 score=fc7ce54817e521460c38a2034c84c6537f9a13e78c18b080d5f78f80ae2a8d1d (matches fetch: False). S0-era golden.json is v2; current loader is v3-only so matches fetch cannot be restored without a scorer change.
- ⚠ produced by the model-free `seeded` stub adapter — harness-shakedown numbers, NOT a caption-model baseline.
- latency: per-image wall-clock p50 0.06s p95 0.416s (37 timed) · model calls/image: 1.0 (total 37)

## Caption metrics (deterministic tier)

- insertion rate: 0.000
- name precision: null (wrong-name images: 0, rate: 0.000)
- Must-Right failed images (hard gate): 34 (rubric-defined images: 37)
- policy violations: 0
- mean gated score: 0.081

## Quality axes (short surface, report-only signals)

- meta-framing images: 0
- mean context duplication: 0.004
- name front-loaded rate: 0.000
- sentence band [1, 4] ok rate: 1.000

## Face detection (identity-agnostic)

- REFUSED (detection_refuses_roster_only): detection P/R is not computed unless annotation_mode is exhaustive

## Face identification (named assertions)

- REFUSED (identification_refuses_unboxed_identity_claims): identification P/R is not computed from identity claims that carry no per-face box lineage

## Per-item failures

- none
