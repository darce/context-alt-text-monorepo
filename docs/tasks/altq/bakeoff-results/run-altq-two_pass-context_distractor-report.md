# Caption + Face Eval Report

> **SUPERSEDED (L6-baseline / EVAL-01 / P1-5(a)).** Caption-quality figures below were scored on a pre-L3 corpus (37-image reported set with selection contamination, a 10-image selection set, a 39-image stub, and/or the 646-image interleave) and/or a pre-PRIV-1 roster spelling. They are not Δ-comparable to the current 20-image held-out split (`golden.json` after `8b93c473`). Kept for provenance. Do not cite as current evidence.

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `bakeoff` model(s): `Qwen3-VL-30B-A3B-Instruct` version(s): `Q4_K_M`
- head_sha: `c6dfc1fcb2fd252c8947d6409b5fb0d69b35c7a1`
- base_url: http://localhost:8000
- fetch manifest_sha256: `747e603176269cedbdfc376d5f8cff794179c378f9fd219247907db59cb0aa4f`
- score manifest_sha256: `fc7ce54817e521460c38a2034c84c6537f9a13e78c18b080d5f78f80ae2a8d1d` (matches fetch: False)
- started_at: 2026-07-16T21:53:47Z
- images: 37/37 scored, 0 failed
- notes: S2R4-14 F23-G re-score: docs/tasks/altq/bakeoff-results/run-altq-two_pass-context_distractor.json against apps/prototype-description-service/scene/tests/seed/golden.json at code 896bd17d4277b83ba54993007cb8ae5bbe2e0de7. Identification was SCORED precision=None recall=0.0 per_identity=10; current scorer publishes REFUSED(identification_refuses_unboxed_identity_claims). Numbers are the scorer's output, not hand-edited.
- notes: Provenance: fetch manifest_sha256=747e603176269cedbdfc376d5f8cff794179c378f9fd219247907db59cb0aa4f score_manifest_sha256=fc7ce54817e521460c38a2034c84c6537f9a13e78c18b080d5f78f80ae2a8d1d (matches fetch: False). The fetch-time manifest is a pre-v3 snapshot the current loader cannot load (manifest_version 3 only, e30a8ce0). This re-score uses the in-tree v3 descendant of the same file, not a different corpus. Previous published score SHA was fc7ce54817e521460c38a2034c84c6537f9a13e78c18b080d5f78f80ae2a8d1d.
- notes: Caption axes are unchanged versus the previously published report.
- ⚠ produced by the throwaway `bakeoff` transport (VLM-2B) — face detection/identification sections below are **vacuous by design** (stub `analyze`/`media_identities`); 0% is expected, NOT a recognition regression.
- ⚠ eval_mode: **context_distractor** — context was transformed at fetch time; metrics are mode-specific, NOT comparable to standard runs.
- prompt variant: `v2` pipeline: two_pass
- latency: per-image wall-clock p50 5.799s p95 17.932s (37 timed) · model calls/image: 2.0 (total 74)

## Caption metrics (deterministic tier)

- insertion rate: 1.000
- name precision: 0.923 (wrong-name images: 3, rate: 0.081)
- Must-Right failed images (hard gate): 0 (rubric-defined images: 37)
- policy violations: 0
- mean gated score: 0.919

## Quality axes (short surface, report-only signals)

- meta-framing images: 1
- mean context duplication: 0.133
- name front-loaded rate: 0.971
- sentence band [1, 4] ok rate: 0.973

## Context-distractor resistance

- injected: 37 taken: 3 resistance: 0.919

## Face detection (identity-agnostic)

- REFUSED (detection_refuses_roster_only): detection P/R is not computed unless annotation_mode is exhaustive

## Face identification (named assertions)

- REFUSED (identification_refuses_unboxed_identity_claims): identification P/R is not computed from identity claims that carry no per-face box lineage

## Per-item failures

- none
