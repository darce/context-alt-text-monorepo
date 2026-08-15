# Caption + Face Eval Report

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `bakeoff` model(s): `Qwen3-VL-30B-A3B-Instruct` version(s): `Q4_K_M`
- head_sha: `4be31eae6967cebddc04c6a0234d583600450662`
- base_url: http://localhost:8000
- fetch manifest_sha256: `747e603176269cedbdfc376d5f8cff794179c378f9fd219247907db59cb0aa4f`
- score manifest_sha256: `fc7ce54817e521460c38a2034c84c6537f9a13e78c18b080d5f78f80ae2a8d1d` (matches fetch: False)
- started_at: 2026-07-16T20:58:00Z
- images: 37/37 scored, 0 failed
- ⚠ produced by the throwaway `bakeoff` transport (VLM-2B) — face detection/identification sections below are **vacuous by design** (stub `analyze`/`media_identities`); 0% is expected, NOT a recognition regression.
- prompt variant: `v1`
- latency: per-image wall-clock p50 2.595s p95 8.942s (37 timed) · model calls/image: 1.0 (total 37)

## Caption metrics (deterministic tier)

- insertion rate: 1.000
- name precision: 1.000 (wrong-name images: 0, rate: 0.000)
- Must-Right failed images (hard gate): 0 (rubric-defined images: 37)
- policy violations: 0
- mean gated score: 1.000

## Quality axes (short surface, report-only signals)

- meta-framing images: 0
- mean context duplication: 0.281
- name front-loaded rate: 1.000
- sentence band [1, 4] ok rate: 0.973

## Face detection (identity-agnostic)

- REFUSED (detection_refuses_roster_only): detection P/R is not computed unless annotation_mode is exhaustive

## Face identification (named assertions)

- micro precision: null recall: 0.000
- macro precision: null recall: 0.000
- true rejections (strangers): 10

### Wrong-name errors (top product risk — every instance listed)

- none
- ignored (triaged): 0

### Per-identity (macro components)

- Bea Burke: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Caitlin Weaver: precision=null recall=0.000 (tp=0 fp=0 fn=14)
- Cristina Quintana: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Daniel Arce: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Ellyn Heald: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Erika Hansen Miller: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Kirstie Mccarrel: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Liam Maloney: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Maria Correonero: precision=null recall=0.000 (tp=0 fp=0 fn=7)
- Ryann Wiseman: precision=null recall=0.000 (tp=0 fp=0 fn=3)

## Per-item failures

- none
