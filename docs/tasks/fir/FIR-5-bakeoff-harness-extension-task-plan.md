# FIR-5. Bake-off Harness Extension

> **Metadata**
>
> - **Date**: 2026-07-18
> - **Author**: Claude Opus 4.8 (claude-opus-4-8)
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `FIR-5`
> - **Target Branch**: `feature/fir-5`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-2 (neutral seam) · FIR-3 (candidate legs) — both `done`
> - **Review Coverage Target**: 2

## Objective

Extend `apps/prototype-description-service/scripts/eval_harness/` so it scores FIR-3 YuNet+SFace against an eval-only buffalo_l reference over Golden-150 and **proposes** (never decides) the numbers FIR-6's operator gate will rest on: identification P/R, false-merge/false-split, cluster purity, face-level unknown-rejection, occlusion-family slices, demographic Fair-SA rollups, and a pure detect+embed throughput/cost leg. Gate decision = FIR-6 only ([RLSE-02/03]).

## Intake

- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) — FIR-5 row, Success criterion 3, [FIR-5 slice sizing](../../scopes/commercial-face-identity-replacement.md#fir-5-slice-sizing-ci-target-driven), §Coordination with VLM-6.
- **Reuse mandate** (NAME-02/REF-10): consume VLM-6 S1 outputs (manifest v2 + roster + `face_boxes` + full-res originals). Reuse report/strata/face_metrics machinery and corpus. **Do not** put face embeddings through `cli.fetch_run_record` (that walker is caption-only: `describe` → `analyze` → `wait_job` → `media_identities`, records names + `face_count` only — see `cli.py:123-270`). Face bake-off uses a **new** walker + run-record kind (ARCH-06: walker fork is intentional and recorded here).
- **No fusion registry**: `fusion_runner.py` exposes `run_fusion_eval` / stubs only — no candidate registry. Legs are a new thin driver (modeled on `bakeoff.py` structure only, not its caption client).
- **Not-Doing here**: product threshold calibration (FIR-6); operator gate decision (FIR-6); switch-over / dim flip / buffalo eviction from prod images (FIR-6); production GPU path (FIR-7); SeetaFace/commercial SDK (FIR-8); runtime/scan-path changes (FIR-4).

## Problem Statement

FIR-4 wired YuNet+SFace dark. Nothing yet measures whether it is good enough to switch. The gate cannot copy buffalo thresholds ([DRIFT-03], [PERF-06]); it needs ACX-domain measurement with falsifiable unknown-first behavior and floor-gated slices. Occlusion (masks vs sunglasses vs other) is the known product-frequency failure mode; n=150 cannot power real-tag floors, so synthetic-paired twins supply power and real tags check ecological validity.

## Constraints

- **Preprocessing parity**: candidate leg imports FIR-3 adapters in-process (`recognition/infrastructure/face_pipeline/ort_adapters.py:OrtYuNetDetector`, `OrtSFaceEmbedder`, `aligner.FivePointAligner`) — no re-implemented align/normalize.
- **License isolation (hard rule, [SC-1])**:
  - buffalo reference = **in-process** module under `scripts/eval_harness/` that imports `insightface` only when `ACX_EVAL_BENCH=1` **and** the `[bench]` extra is installed (`pyproject.toml` `bench = ["insightface>=0.7.3,<1.0.0"]`).
  - Path: detector+embedder → **JSON run artifacts only**. Never `RemoteSceneClient`, never `face_pass.py`, never `seed_roster` / analyze → `media_identities` against **any** tenant (including LIVE curation `4ddf8f36`).
  - `is_publishable()` only redacts published reports — it does **not** stop DB writes; the import/env guard is the write prevention.
  - Assertion test: importing the buffalo bench module with `ACX_EVAL_BENCH` unset (or `0`) raises; non-eval profiles cannot load it.
- **Floor-gated honesty**: every slice below its n-floor (sizing table) is **DIRECTIONAL ONLY** and barred from the gate proposal — including **headline identification P/R**. Until Golden-150 meets floors, **all** gating slices stay DIRECTIONAL even if the report builds.
- **Determinism (split claims)**:
  1. Pure score re-run on a fixed face run-record → bit-identical report JSON/MD (`--check-determinism`).
  2. Synthetic occluder pixels → seed-identical under fixed seed + pinned affine templates.
  3. Embedding re-run → **not** raw float byte identity by default; require cosine ≥ τ on paired vectors (or hash of values rounded to fixed decimals) under pinned ORT/OpenCV thread counts. Byte-identity only if a single-thread CPU path is mandated **and** tested.
- **Unknown-first is first-class**: face-level unknown-rejection is a gating slice (definition in S3).
- **No self-judged gate**: report proposes criteria; FIR-6 operator records the decision in MCP.
- **Product thresholds remain FIR-6**: bake-off assignment uses a bake-off-only protocol (S3). Do **not** copy `ClusteringSettings` defaults (`similarity_threshold=0.55`, `suggestion_floor=0.35` in `recognition/application/settings/clustering.py:191-246`) — those are buffalo-512D-tuned and are exactly the PERF-06/DRIFT-03 failure mode.

## Current State Analysis

| Surface | State | Gap for FIR-5 |
| --- | --- | --- |
| `manifest.py` | `Domain` StrEnum content strata (`people`…`low_light`); scalar `GoldenEntry.domain`; `FaceBox` = centre x,y,w,h + optional `name` + `source` (no landmarks) | No quality/occlusion tags; no landmark GT for synthetic placement |
| `export_identities.enrich_entry` | Fills identities / face_count / spatial_facts / face_boxes from XMP policy only | Never reads/writes domain or tags — wrong surface for operator tags |
| `cli.fetch_run_record` | Caption walker → names + face_count only | Cannot carry embeddings/clusters/assignment |
| `bakeoff.py` | Caption client; face methods intentional no-ops | Vacuous face metrics by design |
| `report.score_run_record` | Always `score_caption`; faces from image-level names/`face_count` | No face bake-off score path, no merge/purity/unknown/floor fields |
| `schema.DocKind` | `run_record`, `report` only | Need face bake-off kinds or face-specific schema discriminator |
| `face_metrics.identification_pr` | Image-level P/R + `true_rejections` (image has strangers and no wrong name) | Need face-level unknown-rejection distinct from `true_rejections` |
| `strata.py` | Single-bucket `Domain` shortlists (`OFFLINE_DOMAINS` / `OPERATOR_DOMAINS`) | Tag-based selection guidance only — do not multi-value Domain |
| golden.json | 37 entries, no celeb provenance floors | Headline n≥100 unreachable until Golden-150 |
| `[bench]` | `insightface` extra exists | No eval-only import guard in harness yet |

## Target Outcome

`make bakeoff-face` runs offline YuNet+SFace + eval-only buffalo_l over the golden/Golden-150 corpus and writes a deterministic, re-scorable **face** bake-off report:

- Face run-record per leg (boxes, embeddings, model_id, bake-off assignment decisions) in JSON artifacts only.
- Metrics: headline ID P/R, false-merge/false-split, cluster purity, face-level unknown-rejection, occlusion synthetic-paired + real validity, demographic Fair-SA (DIRECTIONAL), pure detect+embed throughput + cost/1k vs recorded budget file.
- Floor gating: any under-floor slice (incl. headline) is DIRECTIONAL; gate-proposal section excludes them.
- Buffalo never touches a tenant DB.

## Contract and Boundary Impact

**Locked schema (S1)** — do not fork this choice:

```text
GoldenEntry.domain: Domain | None          # unchanged content stratum
GoldenEntry.tags: list[SliceTag] = []      # NEW additive field; default []
```

- Keep `Domain` enum as-is (content strata for `strata.py`). Do **not** add `masked`/`sunglasses`/… to `Domain`; do **not** multi-value Domain.
- New `SliceTag` StrEnum in `manifest.py` with exactly the eight gating values from scope: `masked`, `sunglasses`, `occlusion_other`, `profile`, `low_res`, `blur`, `similar_people`, `unknown`. Optional later: `demographic` is **not** a SliceTag value — cohort labels live under a separate additive field (S3d).
- `extra="forbid"` on `GoldenEntry` rejects unknown tag strings (Pydantic enum validation).
- Legacy entries with scalar `domain` and no `tags` still load.
- Operator mapping at curation: VLM-6 "low-light" → tag `blur` and/or `low_res` (documented; **not** a loader transform of `Domain.LOW_LIGHT`).
- Tags authored via **manifest JSON / curation export** (operator or post-pass), validated at load. **`enrich_entry` stays identity-only** — no tag writes.
- Optional additive on `FaceBox` (or parallel run-artifact map keyed by media_id+box index): offline landmarks for synthetic occlusion — **independent of any leg under test** (see S4). Prefer run-artifact cache first if schema churn is costly; if extended on `FaceBox`, field is optional so legacy boxes load.
- No runtime/service contract change. Harness imports face_pipeline adapters; face_pipeline never imports harness.

## Slice Delivery

| Slice | Content | Verification |
| --- | --- | --- |
| **S1 Tag schema** | Add `SliceTag` + `GoldenEntry.tags: list[SliceTag] = []`. Leave `Domain`/`domain` alone. Document low-light→blur/low_res at tagging time. Strata: add **selection helpers** over `tags` (e.g. filter entries by tag) — do not overload Domain shortlists. Tag authoring path = manifest write / curation export / manual JSON; loader validates. | Loader tests: multi-tag round-trip; legacy domain+empty tags load; unknown tag string rejected; `enrich_entry` does not invent tags |
| **S2 Face legs + run-record** | **New** modules (not `fetch_run_record`): `face_run_record.py` (schema + builder) and `face_bakeoff.py` (walker). Per-item isolation + bounded stall (rg-007), modeled after `cli.fetch_run_record` control flow but calling in-process detect→align→embed only. **Face run-record item schema** (JSON artifact): `media_id`, `path`, `model_id`, `embedding_dim`, `error`, `faces: [{box, landmarks_used?, embedding: list[float], quality?}]`, plus post-assign `assignment: [{face_index, decision: accept\|suggest\|reject, matched_roster_name\|null, score}]`. DocKind: extend `schema.DocKind` with `face_run_record` (and face report kind if reports stay separate). Candidate leg: `OrtYuNetDetector` + `FivePointAligner` + `OrtSFaceEmbedder` (FIR-3). Buffalo leg: `[bench]` module gated by `ACX_EVAL_BENCH=1` → same face schema, 512D embeddings, JSON only. **ARCH-06**: caption walker not reused for face embeddings (no embeddings→names adapter; no DB). | Unit: record validates; walker isolates item errors; stall aborts; buffalo import fails without env; no call path to `media_identities` / `RemoteSceneClient` in face driver (grep/assert). Embedding re-run: cosine≥τ (or rounded-hash), not raw float identity |
| **S3 Assignment + identity metrics** | **Bake-off-only assignment protocol** (not product `ClusteringSettings`): (1) **Roster gallery**: mean (or first-N) L2-normalized embedding per roster name from named `face_boxes` / present_identities in the leg's own space. (2) **Per-leg embedding space**: score 128D SFace and 512D buffalo **separately** — never cross-space cosine. (3) **Threshold schedule**: cosine similarity sweep (grid, e.g. 0.20–0.90 step 0.05) producing ROC / P-R curves; primary operating point reported at a **provisional** bake-off point chosen as the knee or max-F1 on gallery holdout — recorded in the report, **not** promoted to product defaults. (4) **Open-set rule**: face is `reject` if max gallery cosine < τ_op (or argmax is below margin); strangers = GT `face_boxes` with `name is None` (and images with `face_count > len(present_identities)`). (5) Metrics in `face_metrics.py`: false-merge / false-split, cluster purity, **face-level unknown-rejection** (see definition below), headline ID P/R on celebs01 faces. Product calibration remains FIR-6. | Can-fail fixtures per metric (TEST-15). Unknown-rejection: mandatory failing fixture where candidate **labels** a stranger → metric red. Relation to `true_rejections` documented (image-level legacy vs face-level new) |
| **S3d Demographic (Fair-SA)** | Scope Success criterion 3 + FIR-5 deliverables require demographic slices. Sizing table has **no demographic n-floor** — treat as **DIRECTIONAL** always in this task. Cohort source: optional additive `GoldenEntry.demographic_cohort: str \| None` (or parallel cohort map JSON next to manifest) authored in curation/post-pass; report per-cohort ID P/R macro (Fair-SA sensitivity: one person/cohort must not mask another). No gate role until a floor is scoped later. | Rollup renders per-cohort rates; missing cohorts → empty DIRECTIONAL section, not a silent skip of the section header |
| **S4 Synthetic occlusion** | Generator module `synthetic_occlusion.py`. **Landmark source independent of leg under test**: offline landmark cache written once into run artifacts (or optional extended `FaceBox` landmarks) from a **fixed** offline pass — not from the candidate under score, not from buffalo live service. Occluders: separate generators `masked` / `sunglasses` / `occlusion_other` with fixed anatomy anchors (mask→lower face/mouth; sunglasses→eye pair; patch→cheek/forehead template). Placement = seed + affine from landmarks (not bbox-center heuristics alone). Paired twins of every roster face; paired accuracy Δ per tag. | Same seed → identical occluder pixels; ≥90-pair floor check; placement unit tests pin anchor regions |
| **S5 Score, floors, perf, report** | New pure scorer `score_face_run_record` (skips caption gates). Report: floor-gated slice rollup; gate-criteria **proposal** only; synthetic↔real divergence rule (below); perf leg = **pure detect+embed throughput** (images/sec, embeddings/sec, sec/image) on declared host profiles, plus cost/1k from a written budget file `scripts/eval_harness/perf_budgets/face_bakeoff_budget.json` (device, $/hr, budget embeddings/sec). **Not** full p95 scan latency (scan = persist+cluster+job — out of offline harness scope); label reports clearly as detect+embed-only. Host runbook: CPU A1 local/CI; A10 only if co-scheduled with VLM-6 S3 window or operator books a second window (scope Coordination item 6) — record which in run provenance. | `--check-determinism` bit-identical on pure score; below-floor never in gate proposal (assert); divergence demotion tested with synthetic fixtures |

### Face-level unknown-rejection (normative)

| Field | Definition |
| --- | --- |
| Unit | **Face** (not image) |
| GT strangers | `face_boxes` with `name is None`; if only `face_count`/`present_identities` exist, stranger count = `face_count - len(present_identities)` and faces without boxes are counted as unmatched GT for detection only — unknown-rejection **requires** boxes for face-level scoring |
| Decision | After bake-off assignment: stranger face is **correct reject** if `decision=reject` (no roster name); **false accept** if any roster name assigned |
| Metric | `correct_rejects / (correct_rejects + false_accepts)` over stranger faces; n floor ≥43 faces (sizing table) |
| Relation to `true_rejections` | Existing `identification_pr` image-level true_rejections stays for caption/legacy face name lists; face bake-off report uses the face-level metric above and must not treat always-empty predictions as a free pass without a can-fail fixture |

### Synthetic↔real divergence (normative)

Let \(a_s\) = paired accuracy (or 1 − error rate) on synthetic tag T, \(a_r\) on real-tagged T. Divergence \(d = |a_s - a_r|\). Real n floors are small (±20–23% Wilson) — **automatic demotion only when** \(d\) exceeds the real-slice Wilson half-width at the measured \(a_r\) (or a fixed ≥0.20 absolute floor, whichever is larger). If real n < floor, real is qualitative only; **do not** auto-demote synthetic on noise. Scope's "divergence >⅓" is replaced by this operational rule for implementability; report still prints \(d\) and the threshold used.

### Headline / floor policy (normative)

Current golden = **37 entries**. Sizing headline gate needs ≥100 celebs01 faces on Golden-150. **Every gating slice including headline is DIRECTIONAL until floors are met on a real-corpus Golden-150 run.** Task close requires that run with floor assertions green **or** explicit demotion recorded; S5 must not claim a gating report on under-floor data.

## Files and Surfaces to Change

All under `apps/prototype-description-service/` unless noted.

| Path | Change |
| --- | --- |
| `scripts/eval_harness/manifest.py` | `SliceTag` enum; `GoldenEntry.tags`; optional landmark fields on `FaceBox` **or** document artifact-only landmarks; optional `demographic_cohort` |
| `scripts/eval_harness/schema.py` | `DocKind.FACE_RUN_RECORD` (+ face report kind if needed) |
| `scripts/eval_harness/face_run_record.py` | **New** — face item/run schema builders + validation |
| `scripts/eval_harness/face_bakeoff.py` | **New** — offline walker (YuNet+SFace); per-item isolation; bounded stall; writes JSON only |
| `scripts/eval_harness/buffalo_bench.py` | **New** — buffalo reference; `ACX_EVAL_BENCH` guard; no remote client imports |
| `scripts/eval_harness/face_assignment.py` | **New** — gallery build, cosine sweep/ROC, open-set reject; per-leg space |
| `scripts/eval_harness/face_metrics.py` | false-merge/split, purity, face-level unknown-rejection; keep existing image-level helpers |
| `scripts/eval_harness/synthetic_occlusion.py` | **New** — seeded generators; landmark-affine placement |
| `scripts/eval_harness/report.py` | `score_face_run_record` / face report builder; floor rollup; gate proposal section; **do not** force caption path |
| `scripts/eval_harness/strata.py` | Tag-filter helpers for bake-off slice selection; Domain shortlists unchanged |
| `scripts/eval_harness/cli.py` | `face-bakeoff` + `score-face` (or kind-dispatch) + `--check-determinism` on face score path |
| `scripts/eval_harness/export_identities.py` | **No tag writes** in `enrich_entry` (identity-only preserved) |
| `scripts/eval_harness/perf_leg.py` | **New** — detect+embed throughput; reads budget JSON |
| `scripts/eval_harness/perf_budgets/face_bakeoff_budget.json` | **New** — recorded device budgets + $/hr |
| `scripts/eval_harness/README.md` | Face bake-off runbook; env guard; no-tenant rule; floor policy |
| Makefile (service or monorepo as existing eval targets) | `bakeoff-face` target |
| `pyproject.toml` | Ensure `[bench]` remains the only insightface path; document `ACX_EVAL_BENCH` |
| `scene/tests/test_eval_harness_manifest.py` | tags + unknown-tag + legacy domain |
| `scene/tests/test_eval_harness_strata.py` | tag selection helpers only if strata API changes |
| `scene/tests/test_eval_harness_face_metrics.py` | new metrics + can-fail stranger-label fixture |
| `scene/tests/test_eval_harness_report.py` | face score path; floor gating; determinism |
| `scene/tests/test_eval_harness_face_bakeoff.py` | **New** — walker, env guard, no remote import |
| `scene/tests/test_eval_harness_synthetic_occlusion.py` | **New** — seed identity + anatomy anchors |
| `scene/tests/seed/README.md` (if present) | tag authoring notes for operators |

**Out of scope / do not modify for this task**: `face_pass.py` (tenant-writing live pass), production clustering defaults, runtime scan path.

## Verification Strategy

- Metrics: adversarial can-fail tests (TEST-15) before trusting green — especially stranger false-accept and forced merge/split fixtures.
- Determinism layers tested separately (Constraints).
- Real-corpus smoke before close: run **offline** candidate leg over Golden-150 image bytes from the curation corpus; **do not** route buffalo or candidate embeddings through tenant `4ddf8f36`. Tenant may still hold curated assets for image export only.
- Scoped TDD locally; full suite `make check-remote` per slice.
- Cost: stamp detect+embed wall time + est. cost from budget file on every report.

## Coordination / Sequencing

- **VLM-6**: start harness against 37-entry golden immediately; **all gating conclusions** (not only occlusion) wait for Golden-150 floors. Cheapest tag window = S1 curation; fallback = ~1 h operator post-pass for occlusion/profile/blur + demographic cohort labels + missed faces.
- **Curation tenant `4ddf8f36`**: do not dispose; **image/source only** — never seed buffalo or write face embeddings into it.
- **GPU**: pure CPU path is default; A10 only co-scheduled with VLM-6 or separately booked — record host in provenance.
- **Blocks FIR-6** until a bake-off report exists with floor assertions applied (gating or explicit DIRECTIONAL demotion).

## Consolidated Checklist

- [ ] S1: `SliceTag` + additive `tags: list[SliceTag] = []`; Domain unchanged; tags via manifest authoring; loader rejects unknown tags; enrich_entry identity-only
- [ ] S2: new face walker + face run-record schema (boxes, embeddings, model_id, assignment); DocKind extension; YuNet+SFace offline leg; buffalo `[bench]` + `ACX_EVAL_BENCH` → JSON only; never RemoteSceneClient/face_pass/tenant write; ARCH-06 walker fork recorded
- [ ] S3: bake-off gallery + cosine sweep/ROC + open-set reject in each leg's space; false-merge/split, purity, face-level unknown-rejection with can-fail stranger-label fixture; product thresholds deferred to FIR-6
- [ ] S3d: demographic Fair-SA rollups DIRECTIONAL (sizing table has no floor); cohort field or map authored with tags
- [ ] S4: landmark source independent of leg; seed+affine masked/sunglasses/occlusion_other generators; ≥90-pair floors; seed-identical pixels
- [ ] S5: `score_face_run_record` + floor-gated rollup; pure score `--check-determinism`; detect+embed perf + budget JSON (not full scan p95); operational synthetic↔real divergence; gate proposal only
- [ ] Headline and all gating slices DIRECTIONAL until Golden-150 floors met; close only after real-corpus offline run with floors green or demoted
- [ ] Per-slice adversarial review (≥1 remote HIGH + local adversarial), findings in MCP (not pasted into this plan)
