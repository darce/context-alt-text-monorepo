# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `bakeoff` model(s): `Qwen3-VL-30B-A3B-Instruct` version(s): `Q4_K_M`
- head_sha: `4be31eae6967cebddc04c6a0234d583600450662`
- base_url: http://localhost:8000
- fetch manifest_sha256: `747e603176269cedbdfc376d5f8cff794179c378f9fd219247907db59cb0aa4f`
- score manifest_sha256: `fc7ce54817e521460c38a2034c84c6537f9a13e78c18b080d5f78f80ae2a8d1d` (matches fetch: False)
- started_at: 2026-07-16T21:03:18Z
- images: 37/37 scored, 0 failed
- notes: S2R4-14 F23-G re-score: docs/tasks/altq/bakeoff-results/run-altq-v1-name_ablation.json against apps/prototype-description-service/scene/tests/seed/golden.json at code 896bd17d4277b83ba54993007cb8ae5bbe2e0de7. Identification was SCORED precision=None recall=0.0 per_identity=10; current scorer publishes REFUSED(identification_refuses_unboxed_identity_claims). Numbers are the scorer's output, not hand-edited.
- notes: Provenance: fetch manifest_sha256=747e603176269cedbdfc376d5f8cff794179c378f9fd219247907db59cb0aa4f score_manifest_sha256=fc7ce54817e521460c38a2034c84c6537f9a13e78c18b080d5f78f80ae2a8d1d (matches fetch: False). The fetch-time manifest is a pre-v3 snapshot the current loader cannot load (manifest_version 3 only, e30a8ce0). This re-score uses the in-tree v3 descendant of the same file, not a different corpus. Previous published score SHA was fc7ce54817e521460c38a2034c84c6537f9a13e78c18b080d5f78f80ae2a8d1d.
- notes: Caption axes are unchanged versus the previously published report.
- ⚠ produced by the throwaway `bakeoff` transport (VLM-2B) — face detection/identification sections below are **vacuous by design** (stub `analyze`/`media_identities`); 0% is expected, NOT a recognition regression.
- ⚠ eval_mode: **name_ablation** — context was transformed at fetch time; metrics are mode-specific, NOT comparable to standard runs.
- prompt variant: `v1`
- latency: per-image wall-clock p50 2.721s p95 9.109s (37 timed) · model calls/image: 1.0 (total 37)

## Caption metrics (deterministic tier)

- insertion rate: 0.000
- name precision: null (wrong-name images: 0, rate: 0.000)
- Must-Right failed images (hard gate): 0 (rubric-defined images: 37)
- policy violations: 0
- mean gated score: 1.000

## Quality axes (short surface, report-only signals)

- meta-framing images: 2
- mean context duplication: 0.211
- name front-loaded rate: 0.000
- sentence band [1, 4] ok rate: 0.973

## Name-ablation leak check

- eligible: 37 leaks: 0 leak-free rate: 1.000

## Face detection (identity-agnostic)

- REFUSED (detection_refuses_roster_only): detection P/R is not computed unless annotation_mode is exhaustive

## Face identification (named assertions)

- REFUSED (identification_refuses_unboxed_identity_claims): identification P/R is not computed from identity claims that carry no per-face box lineage

## Per-item failures

- none
