# Caption + Face Eval Report

> **SUPERSEDED (L6-baseline / EVAL-01 / P1-5(a)).** Caption-quality figures below were scored on a pre-L3 corpus (37-image reported set with selection contamination, a 10-image selection set, a 39-image stub, and/or the 646-image interleave) and/or a pre-PRIV-1 roster spelling. They are not Δ-comparable to the current 20-image held-out split (`golden.json` after `8b93c473`). Kept for provenance. Do not cite as current evidence.

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `bakeoff` model(s): `Qwen3-VL-4B-Instruct` version(s): `Q4_K_M`
- head_sha: `7537eca39b9d19782f432a1fa5759597983c604c`
- base_url: http://127.0.0.1:8099
- fetch manifest_sha256: `1701e471455afd740c5c1474d81dee9a0c470efe253a167f55f15202ea65952b`
- score manifest_sha256: `73cbe11306079262f3c97ddc620499e19cb85d432f9b7c87bf9c5b0911f86539` (matches fetch: False)
- started_at: 2026-07-07T15:58:56Z
- images: 10/10 scored, 0 failed
- notes: S2R4-14 F23-G re-score: docs/tasks/vlm/VLM-2B-bakeoff-Qwen3-VL-4B-Instruct-run-record.json against apps/prototype-description-service/scene/tests/seed/bakeoff_golden.json at code 896bd17d4277b83ba54993007cb8ae5bbe2e0de7. Identification was SCORED precision=None recall=0.0 per_identity=7; current scorer publishes REFUSED(identification_refuses_unboxed_identity_claims). Numbers are the scorer's output, not hand-edited.
- notes: Provenance: fetch manifest_sha256=1701e471455afd740c5c1474d81dee9a0c470efe253a167f55f15202ea65952b score_manifest_sha256=73cbe11306079262f3c97ddc620499e19cb85d432f9b7c87bf9c5b0911f86539 (matches fetch: False). The fetch-time manifest is a pre-v3 snapshot the current loader cannot load (manifest_version 3 only, e30a8ce0). This re-score uses the in-tree v3 descendant of the same file, not a different corpus. Previous published score SHA was 73cbe11306079262f3c97ddc620499e19cb85d432f9b7c87bf9c5b0911f86539.
- notes: Caption axes are unchanged versus the previously published report.
- notes: S2R4-15 S2R3-07 rebaseline (commit a90a091e) is still the published caption: must_right_defined_images 9→8; mean_gated_score 0.900→0.8889; a name_precision line was added (now 0.900). F23-G re-score left those caption axes unchanged versus a90a091e, so 'caption unchanged' does not mean they match the pre-S2R3-07 report.
- ⚠ produced by the throwaway `bakeoff` transport (VLM-2B) — face detection/identification sections below are **vacuous by design** (stub `analyze`/`media_identities`); 0% is expected, NOT a recognition regression.

## Caption metrics (deterministic tier)

- insertion rate: 1.000
- name precision: 0.900 (wrong-name images: 1, rate: 0.100)
- Must-Right failed images (hard gate): 0 (rubric-defined images: 8)
- policy violations: 0
- mean gated score: 0.889

## Quality axes (short surface, report-only signals)

- meta-framing images: 2
- mean context duplication: 0.044
- name front-loaded rate: 1.000
- sentence band [1, 4] ok rate: 1.000

## Face detection (identity-agnostic)

- REFUSED (detection_refuses_roster_only): detection P/R is not computed unless annotation_mode is exhaustive

## Face identification (named assertions)

- REFUSED (identification_refuses_unboxed_identity_claims): identification P/R is not computed from identity claims that carry no per-face box lineage

## Per-item failures

- none
