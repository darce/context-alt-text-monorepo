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
> - **Review Coverage Target**: 2 (≥1 remote HIGH + ≥1 local adversarial; findings in MCP, never pasted here)

## Objective

Extend `apps/prototype-description-service/scripts/eval_harness/` so it scores FIR-3 YuNet+SFace against an eval-only buffalo_l reference over Golden-150 and **proposes** (never decides) the numbers FIR-6's operator gate will rest on: identification P/R, false-merge/false-split, cluster purity, face-level unknown-rejection, occlusion-family slices, demographic Fair-SA rollups, and a pure detect+embed throughput/cost leg. Gate decision = FIR-6 only ([RLSE-02/03]).

The load-bearing deliverable is a **deterministic, fully specified scoring pipeline** (association → gallery → assignment → clustering) that a junior can implement without inventing an API or re-importing product thresholds — see [§Bake-off Scoring Architecture](#bake-off-scoring-architecture-normative).

## Intake

- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) — FIR-5 row, Success criterion 3, [FIR-5 slice sizing](../../scopes/commercial-face-identity-replacement.md#fir-5-slice-sizing-ci-target-driven), §Coordination with VLM-6.
- **Reuse mandate** (NAME-02/REF-10): consume VLM-6 S1 outputs (manifest v2 + roster + `face_boxes` + full-res originals). Reuse report/strata/face_metrics machinery and corpus. **Do not** put face embeddings through `cli.fetch_run_record` — that walker is caption-only (`describe` → `analyze` → `wait_job` → `media_identities`, records names + `face_count` only; `cli.py:123-270`, sequential loop, bounded stall `DEFAULT_STALL_LIMIT=5` at `cli.py:46`). Face bake-off uses a **new** walker + run-record kind (ARCH-06: walker fork is intentional and recorded here).
- **No fusion registry**: `fusion_runner.py` exposes `run_fusion_eval` / stubs only — no candidate registry. Legs are a new thin driver (modeled on `bakeoff.py` structure only, not its caption client).
- **Not-Doing here**: product threshold calibration (FIR-6); operator gate decision (FIR-6); switch-over / dim flip / buffalo eviction from prod images (FIR-6); production GPU path (FIR-7); SeetaFace/commercial SDK (FIR-8); runtime/scan-path changes (FIR-4); **full-scan p95 latency** (runtime-owned — see [§Scope amendment](#scope-amendment-p95--a10-deferral-normative)).

## Problem Statement

FIR-4 wired YuNet+SFace dark. Nothing yet measures whether it is good enough to switch. The gate cannot copy buffalo thresholds ([DRIFT-03], [PERF-06]); it needs ACX-domain measurement with falsifiable unknown-first behavior and floor-gated slices. Occlusion (masks vs sunglasses vs other) is the known product-frequency failure mode; n=150 cannot power real-tag floors, so synthetic-paired twins supply power and real tags check ecological validity.

## Constraints

- **Preprocessing parity**: each leg runs its own full detect→align→embed in-process. The candidate leg imports FIR-3 adapters (`recognition/infrastructure/face_pipeline/ort_adapters.py:OrtYuNetDetector` (class `:300-368`, `detect()` returns `list[list[RawDetection]]` with 5×2 landmarks), `OrtSFaceEmbedder` (`:371-404`, L2-normalized `(N,128)`, 112×112 BGR crops), `aligner.FivePointAligner.align(image, landmarks)` (`:164-208`, **requires** 5 YuNet-order landmarks) — no re-implemented align/normalize. SFace dim is resolved fail-closed via `resolve_sface_embedding_dim` (`_common.py:34-57` def; `:60` = `SFACE_EMBEDDING_DIM = resolve_sface_embedding_dim()`), never a hardcoded literal.
- **License isolation (hard rule, [SC-1])**:
  - Buffalo reference = **in-process** module `buffalo_bench.py` under `scripts/eval_harness/` that imports `insightface` **directly** only when `ACX_EVAL_BENCH=1` **and** the `[bench]` extra is installed (`pyproject.toml:70-72` `bench = ["insightface>=0.7.3,<1.0.0"]`; insightface ships in **no other extra** today).
  - The buffalo bench leg must **never** route through the production embedding stack — no import of `recognition.infrastructure.embeddings.InsightFaceAdapter` / `get_shared_insightface_adapter` (`embeddings/__init__.py:37-220`) or `recognition.infrastructure.embeddings.runtime_factory.build_embedding_runtime` (`embeddings/runtime_factory.py:37`); those are the prod dark-default 512D path and carry tenant/service wiring.
  - Path: detector+embedder → **JSON run artifacts only**. Never `RemoteSceneClient`, never `face_pass.py`, never `seed_roster` / analyze → `media_identities` against **any** tenant (including LIVE curation `4ddf8f36`).
  - **S2 negative-import gate** (two complementary checks — a module-graph check alone is always-green on symbol names): (a) **module import-graph** must contain none of `face_pass`, `seed_roster`, `remote_client`, nor **any module under the `recognition.infrastructure.embeddings` package prefix** (where the real production factory lives — `recognition.infrastructure.embeddings.runtime_factory`; there is **no** top-level `recognition.infrastructure.runtime_factory`); (b) **source-level symbol check** with an explicit symbol→module map for leaks that are symbols/methods (not modules): `RemoteSceneClient` (→`remote_client`), `media_identities` (a method on `remote_client`/`face_pass`/`seed_roster` — note `bakeoff.py` also defines a `media_identities` stub, the caption path, likewise out of scope for the face driver), `InsightFaceAdapter`/`get_shared_insightface_adapter` (→`embeddings.__init__`). (a) closes module leaks; (b) closes symbol leaks — a bare symbol name in a module-only graph check never matches (the always-green trap this rule exists to prevent).
  - **Buffalo artifact non-promotion (PROV-01)**: buffalo face run-records carry raw 512D InsightFace-derived embeddings — a non-commercially-licensed derived artifact. They stay in git-ignored `out/` (`cli.py:16-18` retention note) and are **never** promoted to `docs/tasks/**` or committed. Only candidate (128D, ACX-owned) run-records and the aggregate report (publishability-filtered, no raw buffalo vectors) may be promoted. A test asserts no `*.json` under `docs/tasks/**` contains a 512D `embedding` array.
  - **Publishability is a two-stage boundary — score the full corpus, then redact via a NEW post-score function (PROV-01)**: the existing `report._filter_for_public_audience` (`report.py:65-80`) drops non-publishable items **before** scoring in the `Audience.PUBLIC` path (`report.py:400-413`), and `PRIVATE_SOURCES={LOCALWP,OPERATOR}` (`manifest.py:137,253-254`) are hard non-publishable. Unknown-rejection is a **gating** slice whose strangers come from **unpublishable uploads** — so the face scorer must **not** reuse the `Audience.PUBLIC` pre-score branch (doing so zeros the gate). Instead the face path **always scores the full unfiltered corpus**, then produces the *published* artifact through a **new, separately-named** function `redact_face_report_for_public(report)` that runs **after** scoring and strips private-source crops/metadata while preserving aggregate rates. `redact_face_report_for_public` is a **distinct code path** from `_filter_for_public_audience` (do not overload the `Audience.PUBLIC` enum branch, whose only implementation is the pre-score filter). A test asserts a LOCALWP/OPERATOR stranger is **scored** into unknown-rejection yet **absent** from the redacted published artifact.
  - `is_publishable()` redacts published reports; it does **not** stop DB writes — the import/env guard above is the write prevention.
  - Assertion test: importing `buffalo_bench` with `ACX_EVAL_BENCH` unset (or `0`) raises; non-eval profiles cannot load it.
- **Floor-gated honesty**: every slice below its n-floor (sizing table) is **DIRECTIONAL ONLY** and barred from the gate proposal — including **headline identification P/R**. Until Golden-150 meets floors, **all** gating slices stay DIRECTIONAL even if the report builds. Demotion authority is operator-only — see [§Headline / floor policy](#headline--floor-policy-normative).
- **Determinism (three reconciled layers)** — see [§Determinism reconciliation](#determinism-reconciliation-normative) for the pinned kernels/thread counts/tolerances that make these non-vacuous and non-flaky:
  1. **Pure score re-run** on a fixed face run-record → bit-identical report JSON/MD (`--check-determinism`). All assignment/gallery/clustering/threshold selection lives here, so this layer covers the riskiest logic.
  2. **Synthetic occluder pixels** → hash-identical (uint8) under the pinned interpolation kernel + single-thread cv2 within one host profile (not cross-platform byte identity).
  3. **Embedding re-run** → cosine ≥ `EMB_DET_TAU=0.9999` on paired vectors (or hash of values rounded to 6 decimals) under pinned ORT/OpenCV thread counts. **Scoped to embedder-only on a frozen aligned crop** (feed identical 112×112 crops, re-run `embed`), **not** the full detect→align→embed: YuNet is instance-nondeterministic at the noise floor for tiny/degenerate inputs (`ort_adapters.py:16-19`), and heavily-occluded S4 faces sit in exactly that regime, so a full-pipeline re-run would jitter the bbox/crop and flake. Full-pipeline byte/cosine determinism is asserted **only** on real-signal faces at det threshold 0.9; occluded faces are excluded from this assertion.
- **Unknown-first is first-class**: face-level unknown-rejection is a gating slice (definition below).
- **No self-judged gate**: report proposes criteria; FIR-6 operator records the decision in MCP.
- **Product thresholds remain FIR-6**: the bake-off uses a **binary open-set** protocol (accept-name vs reject) with a score-time τ sweep — see [§Bake-off Scoring Architecture](#bake-off-scoring-architecture-normative). Do **not** copy or re-import `ClusteringSettings` (`recognition/application/settings/clustering.py`: `similarity_threshold=0.55` `:191`, `suggestion_floor=0.35` `:231`, `suggestion_ceiling=0.55` `:243`, `complete_link_threshold=0.45` `:195`) — those are buffalo-512D-tuned and are the PERF-06/DRIFT-03 failure mode. The product `accept|suggest|reject` ternary and any ambiguity `margin` are **out of scope here** (they do not exist in `ClusteringSettings` as a `margin` field anyway) — the bake-off decision is binary.

## Current State Analysis

| Surface | State | Gap for FIR-5 |
| --- | --- | --- |
| `manifest.py` | `Domain` StrEnum content strata (`manifest.py:51-67`); scalar `GoldenEntry.domain` (`:341`); `FaceBox` (`:301-317`) = centre x,y,w,h + optional `name` + `source` — **no landmarks** | No quality/occlusion tags; no landmark GT for synthetic placement |
| `export_identities.enrich_entry` | Writes **identity + detection GT** into a copy: `present_identities`, `face_count`, `spatial_facts`, `face_boxes`, `must_right` mirror (`:131-168`); gated on `provenance.source` | **Never writes `domain`/`tags`/cohort** — wrong surface for operator tags (correct; keep it that way) |
| `cli.fetch_run_record` | Caption walker → names + face_count only (`:123-270`) | Cannot carry embeddings/boxes/landmarks |
| `bakeoff.py` | Caption client; face methods intentional no-ops | Vacuous face metrics by design |
| `report.score_run_record` | Scores faces from image-level `item["face_count"]` int + name sets (`:127-287`); no bbox/IoU path; `_filter_for_public_audience` (`:65-80`) already uses `is_publishable` | No face-box score path, no association/merge/purity/unknown/floor fields |
| `schema.DocKind` | `RUN_RECORD`, `REPORT` only (`schema.py:16-20`) | Need a `FACE_RUN_RECORD` kind |
| `face_metrics.py` | `detection_pr` (count-based, `:87-94`) + `identification_pr` (name-set, image-level `true_rejections`, `:97-143`); no purity/merge/split/clustering helper (144 lines total) | Need face-level unknown-rejection + a defined clustering-metric family |
| `strata.py` | `OFFLINE_DOMAINS` (`:80-88`) / `OPERATOR_DOMAINS` (`:91-99`, includes `Domain.OCCLUSION`) single-bucket shortlists | Tag-based selection guidance only — do not multi-value Domain; do not wire slice rollups to `Domain.OCCLUSION` |
| golden.json (`scene/tests/seed/golden.json`) | 37 entries; `manifest_version=2`; roster len 10; **0 entries have `face_boxes`, `provenance`, or `domain`** | Headline n≥100 + all box-dependent metrics unreachable until Golden-150 |
| `[bench]` | `insightface` extra exists (`pyproject.toml:70-72`), only path | No eval-only import guard in harness yet |
| production buffalo | `InsightFaceAdapter`/`get_shared_insightface_adapter` (`embeddings/__init__.py`) is the 512D dark default via `runtime_factory` | Must be excluded from the bench import graph |

## Bake-off Scoring Architecture (normative)

This section is the single source of truth for every scoring mechanism. S2–S5 reference it; do not re-derive mechanics elsewhere. All symbols named here are defined here. **Coordinate conventions (§A0) are load-bearing — read them first.**

### A0. Coordinate conventions (read first)

Two box formats coexist and must never be conflated:

- **Detector output** (`RawDetection.bbox`, `_common.py:71-81`; `ort_adapters.py:172-184`): `[x,y,w,h]` in **image PIXELS, top-left-corner origin** (OpenCV FaceDetectorYN). Landmarks are `(5,2)` in **pixels**.
- **GT box** (`GoldenEntry.face_boxes[i]`, `manifest.py:301-317`): `[x,y,w,h]` **normalized 0..1, CENTRE origin**.

The run-record (§B) stores detector boxes **verbatim in pixel-corner form** (no relabeling) plus the image pixel size. All IoU/association (§C) runs in **pixel-corner space**: GT boxes are converted to pixel-corner using the stored image size; detector boxes are already pixel-corner. **Never** apply a centre→corner shift to a detector box (already corner-form), and never IoU a pixel box against a normalized box. This convention also governs S4's landmark cache, which associates via §C.

### A. Leg model

- Two legs: **candidate** (`OrtYuNetDetector` → `FivePointAligner` → `OrtSFaceEmbedder`, 128D, ACX-owned) and **buffalo reference** (`buffalo_bench.py`, insightface, 512D, eval-only). Each leg runs its **own** full detect→align→embed end-to-end; landmarks always come from the same leg that embeds. No cross-leg landmark borrowing for scoring.
- Cosine is computed **within a leg's own embedding space only** — never 128D↔512D. Every metric is reported per-leg; the bake-off compares the two per-leg reports, never a cross-space distance.

### B. Face run-record (walk-time output — raw pipeline output only, no decisions)

Per media item (JSON artifact, `DocKind.FACE_RUN_RECORD`):

```text
{ media_id, path, model_id, embedding_dim,
  image_size: [W, H],                    # PIXELS — required to normalize GT boxes at score time (§C)
  error?,
  faces: [ { bbox_px: [x,y,w,h],         # detector output VERBATIM: pixels, top-left corner (§A0)
             landmarks_px: [[x,y]*5],     # this leg's landmarks, pixels
             embedding: [float]*dim,      # L2-normalized in the leg's space
             det_score: float,
             quality?: float } ] }
```

The walker records **only what the pipeline produced**. It stores **no** assignment, no gallery, no threshold, no matched name. Association, gallery, assignment, clustering, and thresholding are **all** score-time functions (§C–§F) — this is what makes determinism layer 1 cover the gate-defining logic and resolves the walk-vs-score contradiction.

### C. Detected-face ↔ GT-box association (score-time, pixel-corner space)

For each image, match this leg's detected faces to GT boxes (`GoldenEntry.face_boxes`; normalized centre x,y,w,h + `name|None`):

- **Convert GT → pixel-corner** using stored `image_size=[W,H]`: `gt_px = [(cx − w/2)·W, (cy − h/2)·H, w·W, h·H]`. The detector `bbox_px` is **already** pixel-corner — apply **no** shift to it.
- **Metric**: IoU between `bbox_px` and `gt_px` (both pixel-corner).
- **Matcher (crisp, no overlap)**: image with **exactly 1 GT box** → assign the single highest-IoU detection; image with **≥2 GT boxes** → `scipy.optimize.linear_sum_assignment` (Hungarian) maximizing total IoU. There is no greedy path. Accept a pair only if `IoU ≥ IOU_MATCH_THRESHOLD = 0.5`.
- **Outcomes** per detected face: matched→named GT → **probe of that identity**; matched→GT `name=None` → **stranger**; unmatched detection → **false detection** (detection-P/R FP; excluded from identity scoring); unmatched GT box → **missed detection** (detection-P/R FN).

Association is a pure function of stored `bbox_px` + `image_size` + manifest GT boxes → re-derivable, determinism-checked.

### D. Gallery build (score-time, per leg, leave-one-out — every matched face is scored)

- Never embed a bare GT box (no landmarks). Enrol from **this leg's own detections** that associate (§C) to a **named** GT box — those detections carry the leg's own landmarks, so align→embed is well-defined. A named identity's **matched faces** = the faces this leg detected and §C-matched to that identity's named GT boxes.
- **Leave-one-out (LOO) protocol — there is NO enrollment/probe split; every matched named face is a scored probe.** Reported identification n therefore equals the **matched-named-face count** (this is exactly the basis the §Headline floor is sized on — it removes the earlier "reporting n ≈ half the faces" gap):
  - To score a probe face `f` of identity `X`: build the gallery **for this probe** with `prototype_X` = L2-normalized mean of `X`'s **other** matched faces (excluding `f`), and `prototype_Y` (Y≠X) = L2-normalized mean of **all** of `Y`'s matched faces. `f` is never in its own identity's prototype → no leakage.
  - **Definition of "enrolled" (the single definition used by §E and §F)**: identity `X` is **enrolled for probe `f`** iff it has ≥1 matched face other than `f` — i.e. a non-empty LOO `prototype_X`, equivalently `X` has **≥2 matched faces**. A single-face identity is **not enrolled** for its own face.
  - `X` has only the one face `f` → **not enrolled**; `X` has **no prototype** while scoring `f`; `f` can only correctly `reject` or false-accept another name. Counted in precision / false-accept accounting but **excluded from `X`'s recall denominator** (`excluded_single_face_recall`) — never a silent drop, never a `0/0` or zero-vector normalize (cf `_common.py:144-148`).
  - `n_matched == 0` for `X` (leg missed every appearance) → a detection-recall failure; `X` contributes no identification faces.
- Prototypes are **mean** (re-normalized), never "first-N". LOO gallery is a pure function of stored embeddings + §C association (no RNG).
- **Synthetic-occlusion is a SEPARATE, decoupled, THRESHOLD-FREE measurement (not the headline scoring)** — removes the round-4 circular dependency where twins depended on a score-time, per-leg probe set.
  - **Coverage (honest)**: S4 generates an occluded twin **offline** for **every roster face the fixed landmark-cache pass detected and §C-associated** — so the twin count is **candidate-detector-recall-dependent**, *not* structurally "every roster face". If a tag's eligible pairs fall below the ≥90 floor the slice is **DIRECTIONAL**; do not claim ≥90 is guaranteed. Shared pixels; both legs re-detect.
  - **Metric = closed-set top-1 argmax paired accuracy (threshold-free, NO reject/τ)**: occlusion measures recognition *degradation*, not open-set rejection, so it has no τ (twins are not in the k-fold pool and have no `τ_k`). Each twin is scored by whether `argmax_g cos == true_name` against a gallery = its identity's un-occluded matched faces **excluding the twin's source image** + other identities' un-occluded prototypes. **`a_s`** = this top-1 accuracy on the **synthetic-occluded** twins; **`a_r`** (§Synthetic↔real divergence) = the same top-1 accuracy on **real-tagged occlusion** faces — **not** the un-occluded original (the un-occluded original may be scored the same way as a separate *clean baseline* `a_clean`, distinct from `a_r`). **Re-detect miss**: if a leg's re-detect on the occluded pixels yields no §C-matched face for the pair, that pair scores **incorrect (accuracy 0), kept in n** — an occlusion-induced detection loss is a real degradation, not an exclusion.
  - **Min-gallery guard (distinct-image)**: an identity contributes an occlusion pair for twin `t` only if, after excluding `t`'s **source image (media_id)**, it still has **≥1 un-occluded matched face on a different media_id** — i.e. `prototype_X` is non-empty after the source-image LOO exclusion. Counting ≥2 matched *faces* is **insufficient** (two faces on the same media_id both vanish when that image is excluded). Ineligible identities are excluded from the occlusion slice; the ≥90 floor counts **eligible** pairs.
  - **≥2-distinct-identity guard**: if a pair's argmax gallery has `< 2` distinct identities (single-identity gallery → top-1 argmax ≡ true_name ≡ accuracy 1.0 vacuously), the slice is reported **DIRECTIONAL** — mirrors the §F `M==0` clustering guard.
  - **Walk-stability**: occluded detection sits in YuNet's noise-floor regime (excluded from the layer-3 determinism assertion), so the report must assert an aggregate-Δ stability bound over the ≥90 pairs across an independent re-run. **If that bound is not asserted or not met, the occlusion slice is DIRECTIONAL** — a merely "walk-sensitive" flag does **not** keep a gating number (mirrors "code prevents self-promotion").
  - Twins **never** enter the headline identification set; twin generation depends on **nothing score-time or leg-specific**. S4's firewall test asserts occluded faces are absent from the headline probe list and a twin's source image is excluded from its occlusion gallery.

### E. Assignment — binary open-set (score-time, k-fold τ selection, pooled)

For each matched probe face embedding `e` (named or stranger), scored against its LOO gallery (§D):

- `s_max = max_g cos(e, prototype_g)`, `name* = argmax_g`.
- **Decision**: `reject` if `s_max < τ`; else `accept name*`. Binary — no `suggest`, no `margin`.
- **Open-set F1 (the τ objective — defined explicitly, not invented)**: over a set of faces at threshold τ, using the §F count convention (a confusion is **both** FP and FN, **subject to the enrolled qualifier below** — a non-enrolled/single-face identity's confusion is FP-only):
  - **TP** = `accept` & `name* == true`; **FP** = `accept` & `name* != true` (confusion) **or** `accept` of a stranger (false-accept); **FN** = `reject` of an **enrolled** identity's face **or** a confusion **whose true identity is enrolled** (counted again as FN on the true name). A face of a **non-enrolled** (single-face) identity contributes **no FN** — consistent with §D `excluded_single_face_recall`.
  - `Precision = TP/(TP+FP)`, `Recall = TP/(TP+FN)`, `F1 = 2·P·R/(P+R)`, with the convention **`0/0 → 0`** for each of Precision, Recall, and F1 when its denominator is 0 (so `τ_k = argmax F1` stays well-defined even for an all-reject fold). A stranger correctly `reject`ed is a true-negative — not in any P/R denominator.
- **k-fold τ selection (K = 5, GLOBAL face-level fold key)**: assign every probe face (named + stranger) a fold by `fold = global_rank mod K`, where `global_rank` is the face's index in the list of **all** probe faces sorted by `(identity_name or "￿__stranger__", media_id, box_index)`. A global rank spreads each identity's faces **and** the strangers evenly across all K folds regardless of per-identity count (this replaces the round-4 per-identity-rank key, which collapsed every identity's first probe into fold 0 and left folds 2–4 empty of named faces). For each fold `k`: `τ_k = argmax open-set F1` over the union of the **other K−1 folds** (grid `τ ∈ {0.20,…,0.90}` step 0.05; **tie-break: the grid τ closest to the mean of the LARGEST contiguous max-F1 plateau** (max-margin; residual ties → the larger τ) — well-defined for non-contiguous or even-count max sets (pick the largest contiguous plateau first), and not the smallest/most-permissive τ, which would bias the unknown-first slice toward false-accepts on held-out faces); emit accept/reject for fold `k`'s faces at `τ_k`. **Pool the held-out decisions across all K folds** — every probe face is decided exactly once, at a τ **not fit on its own decision** (its embedding may still shape a training-fold prototype, but never enters the F1 objective that picks its own `τ_k`).
- **Identification and unknown-rejection consume the POOLED per-fold held-out decisions — no re-scoring of the whole set at a single threshold.** (`similar_people` is the **one exception**: it is a distinct per-photo Hungarian **re-assignment** diagnostic — §F — that reuses each face's per-fold `τ_k` only as a reject floor, not the pooled argmax `name*`.) `τ_op = median(τ_k)` is reported for **context only** and is used **only** by the (non-k-folded) clustering sweep's single operating cut (§F). Full ROC / P-R curves reported. `τ_k`/`τ_op` are **PROVISIONAL — not product defaults**.

### F. Identification P/R, unknown-rejection, and clustering metrics (score-time)

**Identification (1:N, LOO gallery)** over the **pooled per-fold held-out decisions** (§E) for probe faces matched to a **named** GT box — **not** re-scored at a single `τ_op`. Counts follow the existing `identification_pr` convention (`face_metrics.py:118-129`, a wrong prediction is **both** FP and FN, **subject to the enrolled qualifier below** — a single-face identity's confusion is FP-only) so recall drops on a mislabel (TEST-15). **Recall/detection coupling caveat (report-level)**: identification recall is computed only over faces this leg **detected and §C-matched** (enrolled), so a leg with weak *detection* recall on hard faces can post an inflated *identification* recall on the easy detected subset. The gate proposal therefore **reports each leg's identification recall alongside its detection recall (§C detection-P/R) and flags the coupling**, so the candidate-vs-buffalo headline is not read apples-to-oranges.

- `accept` and `name* == true_name` → **TP**.
- `accept` and `name* != true_name` (confusion) → **FP** on `name*`, **and FN** on `true_name` **iff `true_name` is enrolled** (§D — has a non-empty LOO prototype). A single-face identity's confusion contributes **FP only** (its face is `excluded_single_face_recall`, so it adds no FN).
- `reject` a probe face whose true identity is **enrolled** → **FN** on `true_name`.
- **Precision** = `TP/(TP+FP)`; **Recall** = `TP/(TP+FN)`, both with `0/0 → 0`. A leg that mislabels everyone has recall → 0 (the headline metric can go red; a can-fail recall/miss fixture is mandatory — S3).

**Face-level unknown-rejection** over stranger probe faces (GT `name=None`), using the **pooled per-fold held-out decisions** (§E):

- correct-reject = `reject`; false-accept = `accept` any name. Binary (no `suggest`).
- Metric = `correct_rejects / (correct_rejects + false_accepts)`; n floor ≥ 43 faces. Strangers are TN/FP in the §E open-set F1; never in identification P/R denominators.

**Clustering family** (bake-off substitute for product graph expansion; uses **no** `ClusteringSettings` value): operate on all faces matched to **named** GT boxes (strangers excluded — no identity ground truth to cluster), in the leg's own space.

- **Algorithm**: single-linkage agglomerative clustering on cosine **distance** (`d = 1 − cos`). The cut is swept in **distance units** `d_cut ∈ {1 − τ : τ in the §E grid} = {0.10, 0.15, …, 0.80}`; the headline clustering point is `d_cut = 1 − τ_op`. Single-linkage is the explicit connected-components analog — a diagnostic, not the product clusterer.
- Let `P_same`/`P_diff` = # same/different-true-identity unordered face pairs; `M` = # face pairs placed in the **same** cluster.
- **purity** = `(1/N) · Σ_clusters max_identity |cluster ∩ identity|` over the `N` clustered faces.
- **false-merge rate** = `#(different-identity pairs in the same cluster) / M` (= 1 − pairwise precision).
- **false-split rate** = `#(same-identity pairs in different clusters) / P_same` (= 1 − pairwise recall).
- **Local floor + degenerate guard (FIR-5 addition — scope has no clustering row)**: clustering metrics are reported **DIRECTIONAL** (never a bare gate number) whenever `P_same < 20` **or** `P_diff < 20` **or** `M == 0`. The `M == 0` (**all-singletons**: no two faces co-clustered) trigger is **separate** from the pair floors — it is what actually makes false-merge `0/0` and `purity ≡ 1.0` vacuous (single-*cluster* is **not** a 0-denominator case: there `M = C(N,2) > 0`). `M == 0` is clustering-dependent and can co-occur with `P_same, P_diff ≥ 20` (reached at a tight cut `d_cut = 1 − τ_op` when a poor leg pushes `τ_op` high), so the pair floors alone do not catch it. S3 ships a guard-fires fixture for the many-clusters all-singletons `purity=1.0` case.

**`similar_people` (multi-identity photo) — per-photo Hungarian identity assignment (DIRECTIONAL).** The default assignment (§E) is independent per-probe argmax, which on a photo with ≥2 roster identities can assign the same gallery name to two faces. Scope's sizing table specifies a **per-photo Hungarian eval** for the `similar_people` diagnostic, so for those photos the bake-off adds a **within-photo one-to-one** assignment: build the face×gallery cosine matrix for the photo's probe faces and solve `scipy.optimize.linear_sum_assignment` (maximizing total similarity) subject to the open-set reject rule at each face's **pooled per-fold threshold `τ_k`** (a face whose assigned similarity is below its fold's `τ_k` stays `reject`). This is distinct from §C (which matches detections↔GT boxes) and from product Hungarian (FIR-6). `similar_people` is **diagnostic/directional** per the sizing table (floor ≥10 photos, never gating), so it is reported separately and never enters the gate proposal.

All formulas above are pairwise-counting standard; no invented API, no product import.

### G. Fetch/score boundary + determinism

Walk time (§B) = raw pipeline output only. Score time (`score_face_run_record`, §C–§F) = everything else, a pure deterministic function of (stored `bbox_px`/`landmarks_px`/`embedding`/`image_size`, manifest GT boxes, the **LOO gallery + deterministic global-fold assignment**, fixed grids — **no RNG, no seeded split**). The scorer **sorts every nested list** it emits (wrong-name lists, cluster memberships, pairwise-count lists) before serialization, so output never depends on set/dict iteration order. `--check-determinism` re-runs §C–§F on a frozen record **in a fresh process under a varied `PYTHONHASHSEED`** (not a same-process double-call) and asserts bit-identical JSON/MD — exercising the LOO gallery, k-fold τ selection, and clustering, not a trivial re-serialization.

## Contract and Boundary Impact

**Locked schema (S1)** — do not fork this choice:

```text
GoldenEntry.domain: Domain | None                       # unchanged content stratum (manifest.py:341)
GoldenEntry.tags: list[SliceTag] = []                   # NEW additive image-slice tags; default []
# Fair-SA cohort is a PERSON attribute -> keyed by roster identity, on the REAL top-level model GoldenManifest:
GoldenManifest.roster_cohorts: dict[str, str] = {}      # NEW on GoldenManifest (manifest.py:375-380); roster-name -> cohort
GoldenEntry.demographic_cohort: str | None = None       # OPTIONAL image-level fallback; single-subject celebs01 ONLY
```

- Keep `Domain` enum as-is (content strata for `strata.py`). Do **not** add occlusion values to `Domain`; do **not** multi-value Domain. Slice rollups bind to `SliceTag`, never to `Domain.OCCLUSION` (which stays a coarse content stratum in `OPERATOR_DOMAINS`).
- New `SliceTag` StrEnum in `manifest.py`. Its values are the **per-slice strata named in scope Success criterion 3's slice list** (masked, sunglasses, occlusion_other, profile, low-res, blur, similar-people) — **seven** values: `masked`, `sunglasses`, `occlusion_other`, `profile`, `low_res`, `blur`, `similar_people`.
  - Scope's SC3 slice list also names **`demographic`** — it is **not** a `SliceTag`. Because a cohort is an attribute of a **person, not an image**, cohort labels live on the **real top-level manifest model `GoldenManifest`** (`manifest.py:375-380`, which holds `roster: list[str]` + `entries`, `extra="forbid"`) as `GoldenManifest.roster_cohorts: dict[roster_name, cohort]` — **there is no `Manifest` type** (the earlier draft's `Manifest.roster_cohorts` was a fabricated name). `load_manifest` (`manifest.py:456-460`) already fail-closes identities outside the roster; **extend that same invariant to validate every `roster_cohorts` key ∈ roster**. A probe face's cohort is resolved via its matched named GT box (§C). The image-level `GoldenEntry.demographic_cohort` is an **optional fallback for single-subject celebs01 entries only** and must not be read for multi-face entries (S3d asserts the exclusion) — this stops Fair-SA mis-attributing one identity's error to another's cohort on `similar_people` images.
  - The VLM-6 coordination-ask enum (scope §Coordination item 1) additionally lists `unknown`; it is deliberately **excluded** from `SliceTag`. Strangers are identified **structurally** by `face_boxes` with `name=None` (§F), not by an image tag, so an `unknown` tag would be an orphaned/undefined enum member (rg-009) and would collide with the unknown-rejection metric name. (Prior plan text claimed the eight values were verbatim "from scope"; that was inaccurate — this is the corrected mapping with rationale.)
- Unknown **tag strings** are rejected by `SliceTag` **enum validation** on `tags: list[SliceTag]`; `extra="forbid"` on `GoldenEntry` (`manifest.py:321`) is what rejects unknown **fields/keys** (the two mechanisms are distinct — do not conflate).
- Legacy entries with scalar `domain` and no `tags`/`demographic_cohort` still load (defaults).
- Operator mapping at curation: VLM-6 "low-light" → tag `blur` and/or `low_res` (documented; **not** a loader transform of `Domain.LOW_LIGHT`).
- Tags + cohort authored via **manifest JSON / curation export** (operator or post-pass), validated at load. **`enrich_entry` stays identity+detection-GT only** (it writes `present_identities`/`face_count`/`spatial_facts`/`face_boxes`/`must_right`, never tags/domain/cohort — `export_identities.py:131-168`).
- **GT landmarks for synthetic occlusion live in a run-artifact cache only** (keyed by `media_id` + GT-box index), **not** on `FaceBox`. `FaceBox` stays the locked centre-box schema; adding landmarks there would churn a locked contract and leaves a schema fork open. See S4 and [§Bake-off Scoring Architecture](#bake-off-scoring-architecture-normative).
- No runtime/service contract change. Harness imports face_pipeline adapters; face_pipeline never imports harness.

## Slice Delivery

| Slice | Content | Verification |
| --- | --- | --- |
| **S1 Tag + cohort schema** | Add `SliceTag` (7 values above) + `GoldenEntry.tags: list[SliceTag] = []` + roster-keyed `GoldenManifest.roster_cohorts: dict[str,str] = {}` (+ optional single-subject `GoldenEntry.demographic_cohort`). Leave `Domain`/`domain` alone. Document low-light→blur/low_res at tagging time. Strata: add **selection helpers** over `tags` — do not overload Domain shortlists, do not route occlusion rollups through `Domain.OCCLUSION`. Tag authoring path = manifest write / curation export / manual JSON; `load_manifest` validates (unknown tags + `roster_cohorts` keys ⊆ roster). | Loader tests: multi-tag round-trip; legacy domain+empty tags/cohort load; unknown tag string rejected **by SliceTag enum-validation** (not `extra="forbid"`, which rejects unknown fields); `roster_cohorts` key outside roster rejected; `enrich_entry` does not invent tags/domain/cohort |
| **S2 Face legs + run-record** | **New** modules: `face_run_record.py` (schema + builder) and `face_bakeoff.py` (walker). Per-item isolation + bounded stall (rg-007), modeled after `cli.fetch_run_record` control flow but calling **in-process detect→align→embed only**. Run-record item schema = **§B** (embeddings/bboxes/landmarks only — **no** assignment field). `DocKind.FACE_RUN_RECORD`. Candidate leg: `OrtYuNetDetector` + `FivePointAligner` + `OrtSFaceEmbedder`. Buffalo leg: `buffalo_bench.py`, `[bench]` module gated by `ACX_EVAL_BENCH=1`, insightface imported **directly** (never via prod `InsightFaceAdapter`/`runtime_factory`) → same face schema, 512D, JSON only. **ARCH-06**: caption walker not reused. | Unit: record validates; walker isolates item errors; stall aborts; buffalo import fails without env; **negative-import gate** (§Constraints) — assert the resolved import graph contains none of `RemoteSceneClient`/`media_identities`/`face_pass`/`seed_roster`/`InsightFaceAdapter`/`get_shared_insightface_adapter` nor **any module under the `recognition.infrastructure.embeddings` prefix** (covers `...embeddings.runtime_factory`). Embedding re-run: cosine≥`EMB_DET_TAU` (embedder-only on frozen crop), not raw float identity |
| **S3 Association + gallery + assignment + metrics** | Implement **§C–§F** in `face_assignment.py` (IoU/Hungarian association, **LOO gallery** + mean prototypes, **k-fold (global fold key) binary open-set τ selection + pooled decisions**, per-leg space) and `face_metrics.py` (face-level ID P/R, unknown-rejection, single-linkage clustering purity/false-merge/false-split with the exact formulas in §F). Product calibration remains FIR-6. | Can-fail fixtures per metric (TEST-15), each proven to go red: forced wrong-name (drops **both** precision and recall, §F), forced **recall miss** (reject an enrolled identity), forced merge, forced split, forced **impure cluster** (purity < 1), and a **mandatory failing stranger-label fixture** (candidate labels a stranger → unknown-rejection red). **Guard-fires fixture**: a **many-clusters all-singletons** slice (`M==0`, `purity=1.0`) **with `P_same,P_diff≥20`** is asserted **DIRECTIONAL** (proves the `M==0` degenerate guard fires independently of the pair floors), plus an under-pair (`P_same<20`) case. **k-fold τ test**: the **global** fold key spreads each identity's faces AND strangers across all K folds (no empty fold), and metrics consume the **pooled per-fold** decisions (no re-score at a single τ_op); pooled reporting n = full matched-named-face n (LOO). **similar_people test**: per-photo Hungarian yields one-to-one assignment (no double-assigned name) on a ≥2-identity fixture. IoU matcher unit tests incl. Hungarian on a 3-face fixture + the pixel-corner↔normalized-centre conversion (§A0/§C). `scipy` import verified against declared deps. Determinism: LOO gallery + k-fold pooled decisions + clustering re-derive identically cross-process |
| **S3d Demographic (Fair-SA)** | Per-cohort ID P/R macro keyed by **roster identity** (`GoldenManifest.roster_cohorts`, loader-validated keys ⊆ roster), resolving each probe face's cohort via its matched named GT box (§C); image-level `demographic_cohort` read **only** for single-subject celebs01 entries. Sizing table has **no demographic n-floor** → **DIRECTIONAL always** in this task. Fair-SA sensitivity: one person/cohort must not mask another. No gate role until a floor is scoped later. | Rollup renders per-cohort rates; a multi-face entry carrying only image-level cohort is **excluded** (asserted), never mis-attributed; missing cohorts → empty DIRECTIONAL section with header, not a silent skip |
| **S4 Synthetic occlusion + GT landmark cache** | **New** `landmark_cache.py`: a **fixed offline pass** that runs `OrtYuNetDetector` **once** at a **pinned model_id + weights sha256 (recorded in run provenance)** over the **un-occluded** originals, associates detections to named GT boxes (§C), and writes 5-point landmarks into a frozen artifact cache keyed by `media_id`+box index. **New** `synthetic_occlusion.py`: seeded generators `masked` / `sunglasses` / `occlusion_other` with fixed anatomy anchors (mask→lower face/mouth; sunglasses→eye pair; patch→cheek/forehead template) applied to **every roster face that has a cached landmark** (offline, decoupled from the score-time headline split; the occlusion Δ is its own LOO measurement per §D); placement = seed + affine from the **cached** landmarks. **Both legs then re-detect+embed on the identical occluded pixels** — the shared cache governs only *where* occluders are painted, so it biases neither leg (rationale: contamination would require a leg to consume the *other* leg's embeddings/landmarks; here each leg still detects independently on the occluded image). Calling any leg's detector live *during* synthetic generation is **forbidden** — the cache is frozen first, in its own pass. | Same seed → hash-identical occluder pixels (uint8, pinned kernel + single-thread cv2; see determinism layer 2); ≥90-pair floor check; placement unit tests pin anchor regions; landmark-cache test asserts model_id/sha recorded and no live leg call during generation; **decoupling + firewall test** asserts twins are generated offline for every **cache-detected** roster face (not from a score-time probe set), occluded faces are absent from the headline identification set, and a twin's source image is excluded from its occlusion LOO gallery (§D); **occlusion can-fail fixture (TEST-15)**: an occluded embedding that argmax must mis-assign drives `a_s` down so the gating occlusion Δ goes red; distinct-image min-gallery, ≥2-distinct-identity guard, and re-detect-miss=accuracy-0 cases each asserted |
| **S5 Score, floors, perf, report** | New pure scorer `score_face_run_record` (skips caption gates; implements §G). Report: floor-gated slice rollup; gate-criteria **proposal** only; synthetic↔real divergence rule (below); perf leg = **pure detect+embed throughput** (images/sec, embeddings/sec, sec/image) on declared host profiles, plus cost/1k from a written budget file `scripts/eval_harness/perf_budgets/face_bakeoff_budget.json`. **Explicitly not** full-scan p95 (see [§Scope amendment](#scope-amendment-p95--a10-deferral-normative)); label reports as detect+embed-only. Scoring runs on the **full unfiltered corpus**; the published artifact is produced by a **new `redact_face_report_for_public()`** (post-score, `is_publishable` celebs01-only, fail-closed) — a **distinct path** from the pre-score `_filter_for_public_audience` / `Audience.PUBLIC` branch, so the unknown-rejection gate keeps its unpublishable strangers (§Constraints two-stage). Host runbook: CPU A1 local/CI; A10 only if co-scheduled with VLM-6 S3 window or an operator-booked second window — record which in run provenance. | `--check-determinism` bit-identical on pure score, cross-process (exercises LOO gallery + k-fold pooled decisions + clustering); below-floor never in gate proposal (assert); divergence demotion tested with synthetic fixtures; publishability test: a LOCALWP/OPERATOR stranger is **scored** into unknown-rejection yet **redacted** from the published artifact (not dropped pre-score) |

### Face-level unknown-rejection (normative)

| Field | Definition |
| --- | --- |
| Unit | **Face** (not image) |
| GT strangers | Probe faces associated (§C) to a `face_boxes` entry with `name is None`. Face-level scoring **requires boxes**; if only `face_count`/`present_identities` exist, stranger count = `face_count - len(present_identities)` is used for **detection-only** accounting and the slice is flagged box-deficient (directional) |
| Decision | Binary open-set (§E): stranger face is **correct reject** if `decision=reject`; **false accept** if `accept` (any roster name). There is no `suggest` band to disambiguate |
| Metric | `correct_rejects / (correct_rejects + false_accepts)` over stranger faces; n floor ≥43 faces (sizing table) |
| Relation to `true_rejections` | The existing image-level `identification_pr.true_rejections` (`face_metrics.py:116-117`) stays for caption/legacy name-list scoring; the face bake-off report uses the face-level metric above and must ship the can-fail stranger-label fixture (no always-empty-prediction free pass) |

### Synthetic↔real divergence (normative)

Let \(a_s\) = paired accuracy (or 1 − error rate) on synthetic tag T, \(a_r\) on real-tagged T. Divergence \(d = |a_s - a_r|\). Real n floors are small (±20–23% Wilson) — **automatic demotion only when** \(d\) exceeds the real-slice Wilson half-width at the measured \(a_r\) (or a fixed ≥0.20 absolute floor, whichever is larger). If real n < floor, real is qualitative only; **do not** auto-demote synthetic on noise. Scope's "divergence >⅓" is replaced by this operational rule for implementability. **Because this changes the gate membership of the three synthetic occlusion slices, it is a recorded scope amendment** — flagged for the same operator acknowledgement as the p95/A10 deferral (§Scope amendment), not a silent implementer swap. The report still prints \(d\) and the threshold used.

### Headline / floor policy (normative)

Current golden = **37 entries**, **0 with `face_boxes`/`provenance`** (verified `scene/tests/seed/golden.json`). Sizing headline gate needs ≥100 celebs01 faces on Golden-150. **Floor unit (normative):** the ≥100 counts **matched-named celebs01 faces = the LOO reported n** (§D). Because LOO scores *every* matched face (no enrollment/probe halving), reported n equals faces-present, so the scope's face-basis floor (n≈96 → ±9.8% Wilson) applies **directly** to the reported set — no under-powering, no unreachable probe-only floor. **Precision-n vs recall-n**: precision counts all matched-named faces, but recall excludes single-face identities (`excluded_single_face_recall`, §D), so the ≥100 floor is applied to **recall-eligible faces** (those of ≥2-appearance identities) — the report prints precision-n and recall-n separately so the Wilson half-width is not overstated for recall. **Every gating slice including headline is DIRECTIONAL until floors are met on a real-corpus Golden-150 run.**

- The 37-entry golden exercises the harness plumbing and the can-fail unit fixtures (which stub boxes); it **cannot** produce any gating number.
- **Demotion authority is the human operator at the FIR-6 gate; FIR-5's in-code guarantee is that it cannot self-promote an under-floor slice.** What FIR-5 enforces **in-repo** (and tests in S5): the report may only label an under-floor slice `UNDER-FLOOR / DIRECTIONAL — awaiting operator demotion`, and the gate-proposal section **excludes every DIRECTIONAL slice** — there is no harness code path that emits a gating/`demoted` verdict for an under-floor slice. What this plan does **NOT** claim (correcting an earlier over-statement): it does **not** rely on `handoff_close_check` to verify decision authorship. `handoff_close_check` is the external `workbay-handoff-mcp` tool (out of bounds per the Plugin Boundary Rule; it audits findings-closed + fresh test evidence + a slice-complete decision) and **cannot** parse a decision-id namespace or assert `actor ≠ implementer`. The real demotion is therefore a **human-operator act at the FIR-6 gate**: the operator records the gate/deferral decision naming each demoted slice + achieved n vs floor, and FIR-5 **Blocks FIR-6** until that human decision exists. On the current 0-box corpus every gating slice is under-floor, so FIR-5 can only ever emit DIRECTIONAL numbers and is structurally incapable of self-declaring a passed gate (SC4). The seam is honest: **code prevents self-promotion; the human operator holds demotion authority** — no reliance on an authorship check the tooling does not perform.
- **Blocks FIR-6** until a bake-off report exists with floor assertions applied (gating **or** operator-recorded DIRECTIONAL demotion). S5 must not claim a gating report on under-floor data.

### Determinism reconciliation (normative)

The three layers in §Constraints differ deliberately; this pins the mechanics so none is vacuous or flaky:

- **Layer 1 (pure score)**: bit-identical because §C–§G are pure functions of the LOO gallery + deterministic global-fold assignment + fixed grids (**no RNG, no seeded split**). To catch set/dict iteration-order nondeterminism (`json.dumps(sort_keys=True)` at `report.py:416` sorts keys, **not** list element order), the scorer **explicitly sorts every nested list** (wrong-name lists, cluster memberships, pairwise-count lists), and `--check-determinism` runs the re-score in a **fresh process under a varied `PYTHONHASHSEED`** — not the same-process double-call of `cli.py:462-468`, which cannot surface cross-process ordering gaps. Strongest layer; covers the gate-defining logic.
- **Layer 2 (synthetic pixels)**: `cv2.warpAffine` interpolation is not bit-stable across OpenCV builds/threads, so byte identity is asserted only **within one host profile** with `cv2.setNumThreads(1)`, `flags=cv2.INTER_LINEAR`, fixed `borderMode`, and comparison by **hash of the uint8 pixel buffer**. Cross-platform CI compares against a per-profile recorded hash, not a single golden.
- **Layer 3 (embedding re-run)**: cosine ≥ `EMB_DET_TAU = 0.9999` (or hash of embeddings rounded to 6 decimals) with ORT/OpenCV thread counts pinned to FIR-3 parity settings. **Scoped to embedder-only on a frozen aligned 112×112 crop** (not the full detect→align→embed), and **occluded S4 faces are excluded** — YuNet is instance-nondeterministic at the noise floor for degenerate/occluded inputs (`ort_adapters.py:16-19`), so a full-pipeline re-run on occluded faces would flake. `τ=0` or "exact byte across platforms" are both rejected as test designs.

## Files and Surfaces to Change

All under `apps/prototype-description-service/` unless noted.

| Path | Change |
| --- | --- |
| `scripts/eval_harness/manifest.py` | `SliceTag` enum (7 values); `GoldenEntry.tags`; roster-keyed `GoldenManifest.roster_cohorts` (real model `:375-380`; `load_manifest` `:456-460` extended to validate keys ⊆ roster) + optional single-subject `GoldenEntry.demographic_cohort`; **no** landmark field on `FaceBox` (artifact-cache landmarks instead) |
| `scripts/eval_harness/schema.py` | `DocKind.FACE_RUN_RECORD` |
| `scripts/eval_harness/face_run_record.py` | **New** — §B face item/run schema builders + validation |
| `scripts/eval_harness/face_bakeoff.py` | **New** — offline walker (YuNet+SFace); per-item isolation; bounded stall; writes JSON only (§B) |
| `scripts/eval_harness/buffalo_bench.py` | **New** — buffalo reference; `ACX_EVAL_BENCH` guard; imports insightface directly; no prod-adapter/remote imports |
| `scripts/eval_harness/face_assignment.py` | **New** — §C IoU/Hungarian association, §D **LOO gallery** + prototypes, §E **k-fold (global face-level fold key)** binary open-set τ selection + **pooled per-fold decisions** + explicit open-set-F1 objective, §F `similar_people` per-photo Hungarian; per-leg space; imports `scipy.optimize.linear_sum_assignment` |
| `scripts/eval_harness/landmark_cache.py` | **New** — §S4 fixed offline GT-landmark pass; pins model_id+sha in provenance; artifact cache keyed by media_id+box index |
| `scripts/eval_harness/synthetic_occlusion.py` | **New** — seeded generators; landmark-affine placement from the cache |
| `scripts/eval_harness/face_metrics.py` | Face-level ID P/R, unknown-rejection, single-linkage clustering purity/false-merge/false-split (§F); keep existing image-level `detection_pr`/`identification_pr` helpers |
| `scripts/eval_harness/report.py` | `score_face_run_record` (scores the **full unfiltered corpus**) / face report builder; floor rollup; gate-proposal section (excludes DIRECTIONAL slices); **new `redact_face_report_for_public()`** = post-score redaction (distinct from the pre-score `_filter_for_public_audience`/`Audience.PUBLIC`); **do not** force caption path |
| `scripts/eval_harness/strata.py` | `SliceTag`-filter helpers for bake-off slice selection; `Domain` shortlists unchanged; occlusion rollups never bound to `Domain.OCCLUSION` |
| `scripts/eval_harness/cli.py` | `face-bakeoff` + `score-face` (or kind-dispatch) + `--check-determinism` on face score path |
| `scripts/eval_harness/export_identities.py` | **No tag/domain/cohort writes** in `enrich_entry` (identity + detection-GT only preserved) |
| `scripts/eval_harness/perf_leg.py` | **New** — detect+embed throughput; reads budget JSON |
| `scripts/eval_harness/perf_budgets/face_bakeoff_budget.json` | **New** — recorded device budgets + $/hr |
| `scripts/eval_harness/README.md` | Face bake-off runbook; env guard; no-tenant rule; buffalo-artifact-non-promotion; floor + demotion policy |
| Makefile (service or monorepo as existing eval targets) | `bakeoff-face` target |
| `pyproject.toml` | Ensure `[bench]` remains the only insightface path; document `ACX_EVAL_BENCH`; **declare `scipy`** as a direct dep (Hungarian matcher §C/§F; currently only transitive via hdbscan — rg-001) |
| `scene/tests/test_eval_harness_manifest.py` | tags + cohort + unknown-tag + legacy domain |
| `scene/tests/test_eval_harness_strata.py` | tag selection helpers only if strata API changes |
| `scene/tests/test_eval_harness_face_metrics.py` | new metrics + can-fail stranger-label + forced merge/split fixtures |
| `scene/tests/test_eval_harness_face_assignment.py` | **New** — IoU/Hungarian association, LOO gallery, k-fold (global fold key) τ selection + pooled decisions, open-set-F1 `0/0→0`, occlusion closed-set argmax + min-gallery, per-leg space |
| `scene/tests/test_eval_harness_report.py` | face score path; floor gating; determinism; publishability redaction |
| `scene/tests/test_eval_harness_face_bakeoff.py` | **New** — walker, env guard, negative-import gate |
| `scene/tests/test_eval_harness_landmark_cache.py` | **New** — pinned model_id/sha recorded; no live leg call during generation |
| `scene/tests/test_eval_harness_synthetic_occlusion.py` | **New** — seed identity (hash) + anatomy anchors |
| `scene/tests/seed/README.md` (if present) | tag/cohort authoring notes for operators |

**Out of scope / do not modify for this task**: `face_pass.py` (tenant-writing live pass), production clustering defaults (`ClusteringSettings`), production embedding stack (`recognition/infrastructure/embeddings/` incl. `embeddings/runtime_factory.py`), runtime scan path.

## Scope amendment (p95 + A10 deferral — normative)

Scope Success criterion 3 enumerates the throughput/cost leg as "embeddings/sec + sec/image on ARM A1 **and A10**, cost per 1k images, **p95 scan latency vs recorded budget**." FIR-5 intentionally narrows this and records the deviation here rather than silently dropping it:

- **FIR-5 emits**: pure detect+embed throughput (images/sec, embeddings/sec, sec/image) + cost/1k on **A1** (and **A10 only when co-scheduled** with VLM-6 S3 or an operator-booked window — otherwise A10 numbers are deferred, not faked). If the window never materializes, the **eval A10 throughput/cost number is owned by a named FIR-5 follow-up (`FIR-5a eval-A10 leg`)** — **not** FIR-7, which is the A10 *production* path — so the FIR-6 gate has a concrete owner for it, mirroring the p95 deferral instead of a nameless gap.
- **p95 full-scan latency is deferred**: scan = persist+cluster+job is the runtime path, not the offline harness. It is owned by **FIR-6 calibration/switch-over** (which touches the runtime) — recorded so **FIR-6's gate is not blocked on a number FIR-5 never emits**. The bake-off report's gate-proposal section must state "p95 scan latency: FIR-6-owned; not measured here."
- This narrowing requires an **operator acknowledgement** (the same operator who records the gate) — the report flags it as a scope deviation for sign-off, not an implementer decision.
- **Two further deviations are recorded here under the same operator-ack discipline**: (a) the synthetic↔real divergence rule replaces scope's ">⅓" with the operational Wilson rule (§Synthetic↔real divergence); (b) FIR-5 adds a **clustering-metric local floor** (`P_same ≥ 20 ∧ P_diff ≥ 20`, §F) because the scope sizing table has no clustering floor row. Both change gate membership, so both are flagged for operator sign-off rather than applied silently.

## Data-selection contract (normative)

- **celebs01 / headline membership**: an entry is celebs01 iff `provenance.source == ProvenanceSource.CELEB` (`manifest.py:127`). Headline ID P/R selects only these entries. On the current golden (0 provenance) headline is empty → DIRECTIONAL.
- **Box-dependent metrics** (association, gallery, unknown-rejection, clustering) require `face_boxes` populated by Golden-150 curation (VLM-6 S1 / operator post-pass). Until then they run only against stubbed unit fixtures and stay DIRECTIONAL — no silent gating on empty data.

## Verification Strategy

- Metrics: adversarial can-fail tests (TEST-15) before trusting green — especially stranger false-accept and forced merge/split fixtures; prove each assertion can go red.
- Determinism layers tested separately (see §Determinism reconciliation).
- Real-corpus smoke before close: run **offline** candidate leg over Golden-150 image bytes from the curation corpus; **do not** route buffalo or candidate embeddings through tenant `4ddf8f36`. Tenant holds curated assets for image export only.
- Scoped TDD locally; full suite `make check-remote` per slice.
- Cost: stamp detect+embed wall time + est. cost from budget file on every report.

## Coordination / Sequencing

- **VLM-6**: start harness against 37-entry golden immediately; **all gating conclusions** (not only occlusion) wait for Golden-150 floors + populated `face_boxes`/`provenance`. Cheapest tag+cohort window = S1 curation; fallback = ~1 h operator post-pass for occlusion/profile/blur tags + demographic cohort labels + missed faces.
- **Curation tenant `4ddf8f36`**: do not dispose; **image/source only** — never seed buffalo or write face embeddings into it.
- **GPU**: pure CPU A1 path is default; A10 only co-scheduled with VLM-6 or separately booked — record host in provenance; A10 numbers deferred otherwise (see §Scope amendment).
- **Blocks FIR-6** until a bake-off report exists with floor assertions applied (gating or operator-recorded DIRECTIONAL demotion).

## Consolidated Checklist

- [x] S1: `SliceTag` (7 values) + additive `tags` + roster-keyed `GoldenManifest.roster_cohorts` (loader validates keys ⊆ roster) (+ optional single-subject `demographic_cohort`); Domain unchanged; tags via manifest authoring; unknown tags rejected by SliceTag enum-validation (not `extra=forbid`); enrich_entry identity+detection-GT only (no tags/domain/cohort)
- [x] S2: new face walker + §B run-record (`bbox_px`/`landmarks_px` verbatim pixel + `image_size`, **no** assignment field); `DocKind.FACE_RUN_RECORD`; YuNet+SFace offline leg; buffalo `[bench]` + `ACX_EVAL_BENCH` importing insightface directly → JSON only; negative-import gate = `recognition.infrastructure.embeddings` **prefix** + `RemoteSceneClient`/`media_identities`/`face_pass`/`seed_roster`/`InsightFaceAdapter`; ARCH-06 walker fork recorded
- [x] S3: §A0/§C pixel-corner↔normalized-centre conversion + IoU/Hungarian (Hungarian for ≥2 boxes); §D **LOO gallery** (every matched face scored; **"enrolled" = ≥2 matched faces**; single-face → excluded_single_face_recall, no NaN); §E **k-fold (K=5, GLOBAL fold key)** binary open-set τ selection with **explicit open-set-F1 table** (`0/0→0`; ties→largest-contiguous-plateau mean, per §E), **pooled per-fold decisions** consumed by §F (no single-τ_op re-score); §F ID P/R where wrong-name hits precision & (enrolled-only) recall, unknown-rejection, single-linkage clustering (distance cut `1−τ`, floor `P_same≥20 ∧ P_diff≥20` **and** all-singletons `M==0` guard), `similar_people` per-photo Hungarian at per-fold τ_k (directional, exempt from the pooled-decisions rule); `scipy` declared dep; can-fail wrong-name/recall-miss/merge/split/purity/stranger + all-singletons guard-fires fixtures; product thresholds deferred to FIR-6
- [x] S3d: demographic Fair-SA rollups DIRECTIONAL (no floor); cohort keyed by roster identity (image-level only for single-subject); multi-face image-only-cohort excluded, not mis-attributed
- [x] S4: `landmark_cache.py` fixed offline pass (pinned model_id+sha, no live leg call); seed+affine masked/sunglasses/occlusion_other generators applied to **every cache-detected roster face** (offline, **decoupled**; coverage detector-recall-dependent — <90 eligible pairs → DIRECTIONAL, no ≥90 guarantee); both legs re-detect on identical occluded pixels; occlusion Δ = **closed-set top-1 argmax paired accuracy (threshold-free)**, own LOO measurement (gallery = identity's un-occluded faces minus the twin's source image); **distinct-image min-gallery guard** (≥1 un-occluded face on a media_id ≠ source) + **≥2-distinct-identity guard** (else DIRECTIONAL) + **re-detect-miss = accuracy-0 (kept in n)**; occluded faces absent from the headline set; occlusion Δ walk-stability bound asserted **else the slice is DIRECTIONAL** (flag alone insufficient); occlusion argmax **can-fail (TEST-15) fixture**; ≥90 **eligible**-pair floors; hash-identical pixels
- [x] S5: `score_face_run_record` (full unfiltered corpus) + floor-gated rollup; pure score `--check-determinism` (cross-process, sorted lists); detect+embed perf + budget JSON (not full-scan p95); **two-stage publishability** via new `redact_face_report_for_public()` (distinct from pre-score `_filter_for_public_audience`); operational synthetic↔real divergence; gate proposal reports each leg's identification recall **alongside its detection recall** + flags the coupling (recall is enrolled/detected-only); gate proposal only
- [x] Scope amendments recorded + flagged for operator acknowledgement: p95 (→FIR-6), A10 eval (→named `FIR-5a`), divergence-rule, clustering local floor
- [x] Demotion enforcement is honest: FIR-5 code cannot self-promote an under-floor slice (report marks DIRECTIONAL, gate-proposal excludes them — S5-tested); demotion authority = **human operator at FIR-6 gate** (no reliance on `handoff_close_check` parsing authorship, which it does not do)
- [x] Buffalo run-records stay in git-ignored `out/`, never promoted/committed (test asserts no 512D embedding under `docs/tasks/**`)
- [ ] Headline and all gating slices DIRECTIONAL until Golden-150 floors met; close only after real-corpus offline run with floors green **or** operator-recorded demotion
- [x] Per-slice adversarial review (≥1 remote HIGH + local adversarial), findings in MCP (not pasted into this plan)
