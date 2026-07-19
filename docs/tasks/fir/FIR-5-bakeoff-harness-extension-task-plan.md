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

- **Preprocessing parity**: each leg runs its own full detect→align→embed in-process. The candidate leg imports FIR-3 adapters (`recognition/infrastructure/face_pipeline/ort_adapters.py:OrtYuNetDetector` (class `:300-368`, `detect()` returns `list[list[RawDetection]]` with 5×2 landmarks), `OrtSFaceEmbedder` (`:371-404`, L2-normalized `(N,128)`, 112×112 BGR crops), `aligner.FivePointAligner.align(image, landmarks)` (`:164-208`, **requires** 5 YuNet-order landmarks) — no re-implemented align/normalize. SFace dim is resolved fail-closed via `resolve_sface_embedding_dim` (`_common.py:60`), never a hardcoded literal.
- **License isolation (hard rule, [SC-1])**:
  - Buffalo reference = **in-process** module `buffalo_bench.py` under `scripts/eval_harness/` that imports `insightface` **directly** only when `ACX_EVAL_BENCH=1` **and** the `[bench]` extra is installed (`pyproject.toml:70-72` `bench = ["insightface>=0.7.3,<1.0.0"]`; insightface ships in **no other extra** today).
  - The buffalo bench leg must **never** route through the production embedding stack — no import of `recognition.infrastructure.embeddings.InsightFaceAdapter` / `get_shared_insightface_adapter` (`embeddings/__init__.py:37-220`) or `runtime_factory.build_embedding_runtime`; those are the prod dark-default 512D path and carry tenant/service wiring.
  - Path: detector+embedder → **JSON run artifacts only**. Never `RemoteSceneClient`, never `face_pass.py`, never `seed_roster` / analyze → `media_identities` against **any** tenant (including LIVE curation `4ddf8f36`).
  - **S2 negative-import gate** (assert + grep in test): the face driver’s import graph must contain none of `RemoteSceneClient`, `media_identities`, `face_pass`, `seed_roster`, `InsightFaceAdapter`, `get_shared_insightface_adapter`, `recognition.infrastructure.embeddings`, `recognition.infrastructure.runtime_factory`.
  - **Buffalo artifact non-promotion (PROV-01)**: buffalo face run-records carry raw 512D InsightFace-derived embeddings — a non-commercially-licensed derived artifact. They stay in git-ignored `out/` (`cli.py:16-18` retention note) and are **never** promoted to `docs/tasks/**` or committed. Only candidate (128D, ACX-owned) run-records and the aggregate report (publishability-filtered, no raw buffalo vectors) may be promoted. A test asserts no `*.json` under `docs/tasks/**` contains a 512D `embedding` array.
  - **Report/gallery publishability (PROV-01)**: the face report builder and any published gallery artifact route every source through `Provenance.is_publishable` (`manifest.py:242-257`; `PRIVATE_SOURCES={LOCALWP,OPERATOR}` at `:137`) via the existing `report._filter_for_public_audience` (`report.py:65-80`) — fail-closed, celebs01-only. Unknown-rejection strangers come from unpublishable uploads and must be redacted from any shared artifact even though no tenant DB write occurs.
  - `is_publishable()` redacts published reports; it does **not** stop DB writes — the import/env guard above is the write prevention.
  - Assertion test: importing `buffalo_bench` with `ACX_EVAL_BENCH` unset (or `0`) raises; non-eval profiles cannot load it.
- **Floor-gated honesty**: every slice below its n-floor (sizing table) is **DIRECTIONAL ONLY** and barred from the gate proposal — including **headline identification P/R**. Until Golden-150 meets floors, **all** gating slices stay DIRECTIONAL even if the report builds. Demotion authority is operator-only — see [§Headline / floor policy](#headline--floor-policy-normative).
- **Determinism (three reconciled layers)** — see [§Determinism reconciliation](#determinism-reconciliation-normative) for the pinned kernels/thread counts/tolerances that make these non-vacuous and non-flaky:
  1. **Pure score re-run** on a fixed face run-record → bit-identical report JSON/MD (`--check-determinism`). All assignment/gallery/clustering/threshold selection lives here, so this layer covers the riskiest logic.
  2. **Synthetic occluder pixels** → hash-identical (uint8) under the pinned interpolation kernel + single-thread cv2 within one host profile (not cross-platform byte identity).
  3. **Embedding re-run** → cosine ≥ `EMB_DET_TAU=0.9999` on paired vectors (or hash of values rounded to 6 decimals) under pinned ORT/OpenCV thread counts. Raw float byte identity only if a single-thread CPU path is mandated **and** tested.
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

This section is the single source of truth for every scoring mechanism. S2–S5 reference it; do not re-derive mechanics elsewhere. All symbols named here are defined here.

### A. Leg model

- Two legs: **candidate** (`OrtYuNetDetector` → `FivePointAligner` → `OrtSFaceEmbedder`, 128D, ACX-owned) and **buffalo reference** (`buffalo_bench.py`, insightface, 512D, eval-only). Each leg runs its **own** full detect→align→embed end-to-end; landmarks always come from the same leg that embeds. No cross-leg landmark borrowing for scoring.
- Cosine is computed **within a leg's own embedding space only** — never 128D↔512D. Every metric is reported per-leg; the bake-off compares the two per-leg reports, never a cross-space distance.

### B. Face run-record (walk-time output — embeddings only, no decisions)

Per media item (JSON artifact, `DocKind.FACE_RUN_RECORD`):

```text
{ media_id, path, model_id, embedding_dim, error?,
  faces: [ { bbox: [x,y,w,h],          # detector output, normalized
             landmarks: [[x,y]*5],      # this leg's landmarks
             embedding: [float]*dim,    # L2-normalized in the leg's space
             det_score: float,
             quality?: float } ] }
```

The walker records **only what the pipeline produced**. It stores **no** assignment, no gallery, no threshold, no matched name. Association, gallery, assignment, clustering, and thresholding are **all** score-time functions (§C–§F) — this is what makes determinism layer 1 cover the gate-defining logic and resolves the walk-vs-score contradiction.

### C. Detected-face ↔ GT-box association (score-time)

GT boxes come from the manifest (`GoldenEntry.face_boxes`; centre x,y,w,h + `name|None`). For each image, match this leg's detected faces to GT boxes:

- **Metric**: IoU between detected bbox and GT box (both converted centre→corner first).
- **Matcher**: one-to-one. Single-/few-face images use greedy max-IoU; multi-face images (`similar_people`, ≥2 GT boxes) use `scipy.optimize.linear_sum_assignment` (Hungarian) maximizing total IoU. A pair is accepted only if `IoU ≥ IOU_MATCH_THRESHOLD = 0.5`.
- **Outcomes** per detected face: matched-to-named-GT → **probe of that identity**; matched-to-GT-with-`name=None` → **stranger**; unmatched detection → **false detection** (detection-P/R FP; excluded from identity scoring); unmatched GT box → **missed detection** (detection-P/R FN).

Association is a pure function of stored bboxes + manifest GT boxes → re-derivable, determinism-checked.

### D. Gallery build (score-time, per leg, seeded holdout)

- Never embed a bare GT box (it has no landmarks). Instead, enrol from **this leg's own detections** that associate (via §C) to a **named** GT box — those detections carry the leg's own landmarks, so align→embed is well-defined.
- **Enrollment/probe split** (deterministic, no RNG): for each identity, sort its images by `media_id` ascending; the first `n_enroll = max(1, floor(n_images/2))` images are **enrollment**, the rest **probe**. Identities with `n_images == 1` enrol but contribute **zero probe faces** → excluded from identification P/R and reported as `excluded_single_image` (never silently dropped).
- **Prototype** per identity = L2-normalized mean of that identity's enrollment-face embeddings (re-normalized to unit length). Choice is fixed to **mean** (not "first-N").

### E. Assignment — binary open-set (score-time)

For each **probe** face embedding `e` in a leg's space:

- `s_max = max_g cos(e, prototype_g)`, `name* = argmax_g`.
- **Decision**: `reject` (predict stranger/unknown) if `s_max < τ`; else `accept name*`.
- No `suggest` band, no `margin` — the decision is binary.
- **τ selection**: sweep a fixed grid `τ ∈ {0.20, 0.25, …, 0.90}` over the probe set; at each τ compute open-set F1 (identification over enrolled identities + correct-reject of strangers). `τ_op = argmax F1`; ties → smallest τ (determinism). Report full ROC / P-R curves + `τ_op`, labelled **PROVISIONAL — not a product default**.

### F. Identification P/R, unknown-rejection, and clustering metrics (score-time)

**Identification (1:N, gallery)** over probe faces matched to a **named** GT box, at `τ_op`:

- TP = `accept` and `name* == true_name`.
- **wrong-name** = `accept` and `name* != true_name` (face-level confusion).
- miss (FN) = `reject` a probe face whose true identity is enrolled in the gallery.
- P/R computed with the existing `PrResult`/`IdentityPr` machinery (`face_metrics.py:43-84`), extended for the face-level counts.

**Face-level unknown-rejection** over stranger probe faces (GT `name=None`):

- correct-reject = `reject`; false-accept = `accept` any name. Binary — the three-value collapse ambiguity is gone because there is no `suggest`.
- Metric = `correct_rejects / (correct_rejects + false_accepts)`; n floor ≥ 43 faces.

**Clustering family** (bake-off substitute for product graph expansion; uses **no** `ClusteringSettings` value): operate on all faces matched to **named** GT boxes (strangers excluded — no identity ground truth to cluster), in the leg's own space.

- **Algorithm**: single-linkage agglomerative clustering on cosine **distance** (`1 - cos`), cut at a swept threshold `d_cut` over the same grid as §E (reported as a curve; headline reported at the `d_cut` corresponding to `τ_op`). Single-linkage is the explicit connected-components analog; it is a diagnostic, not the product clusterer.
- Let `P_same` = # unordered face pairs with the **same** true identity, `P_diff` = pairs with **different** identities.
- **purity** = `(1/N) · Σ_clusters max_identity |cluster ∩ identity|` over the `N` clustered faces.
- **false-merge rate** = `#(different-identity pairs placed in the same cluster) / #(all pairs placed in the same cluster)` (= 1 − pairwise precision).
- **false-split rate** = `#(same-identity pairs placed in different clusters) / P_same` (= 1 − pairwise recall).

All formulas above are pairwise-counting standard; no invented API, no product import.

### G. Fetch/score boundary + determinism

Walk time (§B) = embeddings only. Score time (`score_face_run_record`, §C–§F) = everything else, a pure deterministic function of (stored embeddings/bboxes/landmarks, manifest GT boxes, fixed split rule, fixed grids). `--check-determinism` re-runs §C–§F on a frozen record and asserts bit-identical JSON/MD — which exercises the gallery split, τ sweep, and clustering, not just a trivial re-serialization.

## Contract and Boundary Impact

**Locked schema (S1)** — do not fork this choice:

```text
GoldenEntry.domain: Domain | None                       # unchanged content stratum (manifest.py:341)
GoldenEntry.tags: list[SliceTag] = []                   # NEW additive field; default []
GoldenEntry.demographic_cohort: str | None = None       # NEW additive Fair-SA cohort (S3d)
```

- Keep `Domain` enum as-is (content strata for `strata.py`). Do **not** add occlusion values to `Domain`; do **not** multi-value Domain. Slice rollups bind to `SliceTag`, never to `Domain.OCCLUSION` (which stays a coarse content stratum in `OPERATOR_DOMAINS`).
- New `SliceTag` StrEnum in `manifest.py`. Its values are the **per-slice strata named in scope Success criterion 3's slice list** (masked, sunglasses, occlusion_other, profile, low-res, blur, similar-people) — **seven** values: `masked`, `sunglasses`, `occlusion_other`, `profile`, `low_res`, `blur`, `similar_people`.
  - Scope's SC3 slice list also names **`demographic`** — it is **not** a `SliceTag`; cohort labels live in `demographic_cohort` (S3d), because a cohort is an attribute of a person, not an image slice.
  - The VLM-6 coordination-ask enum (scope §Coordination item 1) additionally lists `unknown`; it is deliberately **excluded** from `SliceTag`. Strangers are identified **structurally** by `face_boxes` with `name=None` (§F), not by an image tag, so an `unknown` tag would be an orphaned/undefined enum member (rg-009) and would collide with the unknown-rejection metric name. (Prior plan text claimed the eight values were verbatim "from scope"; that was inaccurate — this is the corrected mapping with rationale.)
- `extra="forbid"` on `GoldenEntry` (`manifest.py:321`) rejects unknown tag strings (Pydantic enum validation).
- Legacy entries with scalar `domain` and no `tags`/`demographic_cohort` still load (defaults).
- Operator mapping at curation: VLM-6 "low-light" → tag `blur` and/or `low_res` (documented; **not** a loader transform of `Domain.LOW_LIGHT`).
- Tags + cohort authored via **manifest JSON / curation export** (operator or post-pass), validated at load. **`enrich_entry` stays identity+detection-GT only** (it writes `present_identities`/`face_count`/`spatial_facts`/`face_boxes`/`must_right`, never tags/domain/cohort — `export_identities.py:131-168`).
- **GT landmarks for synthetic occlusion live in a run-artifact cache only** (keyed by `media_id` + GT-box index), **not** on `FaceBox`. `FaceBox` stays the locked centre-box schema; adding landmarks there would churn a locked contract and leaves a schema fork open. See S4 and [§Bake-off Scoring Architecture](#bake-off-scoring-architecture-normative).
- No runtime/service contract change. Harness imports face_pipeline adapters; face_pipeline never imports harness.

## Slice Delivery

| Slice | Content | Verification |
| --- | --- | --- |
| **S1 Tag + cohort schema** | Add `SliceTag` (7 values above) + `GoldenEntry.tags: list[SliceTag] = []` + `GoldenEntry.demographic_cohort: str \| None = None`. Leave `Domain`/`domain` alone. Document low-light→blur/low_res at tagging time. Strata: add **selection helpers** over `tags` — do not overload Domain shortlists, do not route occlusion rollups through `Domain.OCCLUSION`. Tag authoring path = manifest write / curation export / manual JSON; loader validates. | Loader tests: multi-tag round-trip; legacy domain+empty tags/cohort load; unknown tag string rejected (`extra="forbid"`); `enrich_entry` does not invent tags/domain/cohort |
| **S2 Face legs + run-record** | **New** modules: `face_run_record.py` (schema + builder) and `face_bakeoff.py` (walker). Per-item isolation + bounded stall (rg-007), modeled after `cli.fetch_run_record` control flow but calling **in-process detect→align→embed only**. Run-record item schema = **§B** (embeddings/bboxes/landmarks only — **no** assignment field). `DocKind.FACE_RUN_RECORD`. Candidate leg: `OrtYuNetDetector` + `FivePointAligner` + `OrtSFaceEmbedder`. Buffalo leg: `buffalo_bench.py`, `[bench]` module gated by `ACX_EVAL_BENCH=1`, insightface imported **directly** (never via prod `InsightFaceAdapter`/`runtime_factory`) → same face schema, 512D, JSON only. **ARCH-06**: caption walker not reused. | Unit: record validates; walker isolates item errors; stall aborts; buffalo import fails without env; **negative-import gate** (§Constraints) — assert none of `RemoteSceneClient`/`media_identities`/`face_pass`/`seed_roster`/`InsightFaceAdapter`/`get_shared_insightface_adapter`/`recognition.infrastructure.embeddings`/`runtime_factory` in the face driver import graph. Embedding re-run: cosine≥`EMB_DET_TAU` (or rounded-hash), not raw float identity |
| **S3 Association + gallery + assignment + metrics** | Implement **§C–§F** in `face_assignment.py` (IoU/Hungarian association, seeded gallery split, mean prototypes, binary open-set τ sweep, per-leg space) and `face_metrics.py` (face-level ID P/R, unknown-rejection, single-linkage clustering purity/false-merge/false-split with the exact formulas in §F). Product calibration remains FIR-6. | Can-fail fixtures per metric (TEST-15): forced wrong-name (false-merge), forced split, and a **mandatory failing stranger-label fixture** (candidate labels a stranger → unknown-rejection red). IoU matcher unit tests incl. Hungarian on a 3-face fixture. Determinism: gallery split + τ sweep re-derive identically |
| **S3d Demographic (Fair-SA)** | Per-cohort ID P/R macro from `GoldenEntry.demographic_cohort`. Sizing table has **no demographic n-floor** → **DIRECTIONAL always** in this task. Fair-SA sensitivity: one person/cohort must not mask another. No gate role until a floor is scoped later. | Rollup renders per-cohort rates; missing cohorts → empty DIRECTIONAL section with header, not a silent skip |
| **S4 Synthetic occlusion + GT landmark cache** | **New** `landmark_cache.py`: a **fixed offline pass** that runs `OrtYuNetDetector` **once** at a **pinned model_id + weights sha256 (recorded in run provenance)** over the **un-occluded** originals, associates detections to named GT boxes (§C), and writes 5-point landmarks into a frozen artifact cache keyed by `media_id`+box index. **New** `synthetic_occlusion.py`: seeded generators `masked` / `sunglasses` / `occlusion_other` with fixed anatomy anchors (mask→lower face/mouth; sunglasses→eye pair; patch→cheek/forehead template); placement = seed + affine from the **cached** landmarks. **Both legs then re-detect+embed on the identical occluded pixels** — the shared cache governs only *where* occluders are painted, so it biases neither leg (rationale: contamination would require a leg to consume the *other* leg's embeddings/landmarks; here each leg still detects independently on the occluded image). Calling any leg's detector live *during* synthetic generation is **forbidden** — the cache is frozen first, in its own pass. | Same seed → hash-identical occluder pixels (uint8, pinned kernel + single-thread cv2; see determinism layer 2); ≥90-pair floor check; placement unit tests pin anchor regions; landmark-cache test asserts model_id/sha recorded and no live leg call during generation |
| **S5 Score, floors, perf, report** | New pure scorer `score_face_run_record` (skips caption gates; implements §G). Report: floor-gated slice rollup; gate-criteria **proposal** only; synthetic↔real divergence rule (below); perf leg = **pure detect+embed throughput** (images/sec, embeddings/sec, sec/image) on declared host profiles, plus cost/1k from a written budget file `scripts/eval_harness/perf_budgets/face_bakeoff_budget.json`. **Explicitly not** full-scan p95 (see [§Scope amendment](#scope-amendment-p95--a10-deferral-normative)); label reports as detect+embed-only. Report + gallery routed through `_filter_for_public_audience` (celebs01-only, fail-closed). Host runbook: CPU A1 local/CI; A10 only if co-scheduled with VLM-6 S3 window or an operator-booked second window — record which in run provenance. | `--check-determinism` bit-identical on pure score (exercises split+sweep+clustering); below-floor never in gate proposal (assert); divergence demotion tested with synthetic fixtures; publishability filter test with a LOCALWP/OPERATOR source redacted |

### Face-level unknown-rejection (normative)

| Field | Definition |
| --- | --- |
| Unit | **Face** (not image) |
| GT strangers | Probe faces associated (§C) to a `face_boxes` entry with `name is None`. Face-level scoring **requires boxes**; if only `face_count`/`present_identities` exist, stranger count = `face_count - len(present_identities)` is used for **detection-only** accounting and the slice is flagged box-deficient (directional) |
| Decision | Binary open-set (§E): stranger face is **correct reject** if `decision=reject`; **false accept** if `accept` (any roster name). There is no `suggest` band to disambiguate |
| Metric | `correct_rejects / (correct_rejects + false_accepts)` over stranger faces; n floor ≥43 faces (sizing table) |
| Relation to `true_rejections` | The existing image-level `identification_pr.true_rejections` (`face_metrics.py:116-117`) stays for caption/legacy name-list scoring; the face bake-off report uses the face-level metric above and must ship the can-fail stranger-label fixture (no always-empty-prediction free pass) |

### Synthetic↔real divergence (normative)

Let \(a_s\) = paired accuracy (or 1 − error rate) on synthetic tag T, \(a_r\) on real-tagged T. Divergence \(d = |a_s - a_r|\). Real n floors are small (±20–23% Wilson) — **automatic demotion only when** \(d\) exceeds the real-slice Wilson half-width at the measured \(a_r\) (or a fixed ≥0.20 absolute floor, whichever is larger). If real n < floor, real is qualitative only; **do not** auto-demote synthetic on noise. Scope's "divergence >⅓" is replaced by this operational rule for implementability; the report still prints \(d\) and the threshold used.

### Headline / floor policy (normative)

Current golden = **37 entries**, **0 with `face_boxes`/`provenance`** (verified `scene/tests/seed/golden.json`). Sizing headline gate needs ≥100 celebs01 faces on Golden-150. **Every gating slice including headline is DIRECTIONAL until floors are met on a real-corpus Golden-150 run.**

- The 37-entry golden exercises the harness plumbing and the can-fail unit fixtures (which stub boxes); it **cannot** produce any gating number.
- **Demotion authority is operator-only.** The bake-off report may *propose* demotion of an under-floor slice; task close requires **either** floor assertions green **or** an **operator-recorded MCP decision** naming each demoted slice + its evidence (achieved n vs floor). An implementer checkbox is not sufficient — this preserves "the implementing agent never judges its own gate" (SC4).
- **Blocks FIR-6** until a bake-off report exists with floor assertions applied (gating **or** operator-recorded DIRECTIONAL demotion). S5 must not claim a gating report on under-floor data.

### Determinism reconciliation (normative)

The three layers in §Constraints differ deliberately; this pins the mechanics so none is vacuous or flaky:

- **Layer 1 (pure score)**: bit-identical because §C–§G are pure functions with fixed split rule + fixed grids + no RNG. This is the strongest layer and covers the gate-defining logic.
- **Layer 2 (synthetic pixels)**: `cv2.warpAffine` interpolation is not bit-stable across OpenCV builds/threads, so byte identity is asserted only **within one host profile** with `cv2.setNumThreads(1)`, `flags=cv2.INTER_LINEAR`, fixed `borderMode`, and comparison by **hash of the uint8 pixel buffer**. Cross-platform CI compares against a per-profile recorded hash, not a single golden.
- **Layer 3 (embedding re-run)**: cosine ≥ `EMB_DET_TAU = 0.9999` (or hash of embeddings rounded to 6 decimals) with ORT/OpenCV thread counts pinned to the FIR-3 parity settings. `τ=0` or "exact byte" are both rejected as test designs.

## Files and Surfaces to Change

All under `apps/prototype-description-service/` unless noted.

| Path | Change |
| --- | --- |
| `scripts/eval_harness/manifest.py` | `SliceTag` enum (7 values); `GoldenEntry.tags`; `GoldenEntry.demographic_cohort`; **no** landmark field on `FaceBox` (artifact-cache landmarks instead) |
| `scripts/eval_harness/schema.py` | `DocKind.FACE_RUN_RECORD` |
| `scripts/eval_harness/face_run_record.py` | **New** — §B face item/run schema builders + validation |
| `scripts/eval_harness/face_bakeoff.py` | **New** — offline walker (YuNet+SFace); per-item isolation; bounded stall; writes JSON only (§B) |
| `scripts/eval_harness/buffalo_bench.py` | **New** — buffalo reference; `ACX_EVAL_BENCH` guard; imports insightface directly; no prod-adapter/remote imports |
| `scripts/eval_harness/face_assignment.py` | **New** — §C IoU/Hungarian association, §D gallery split+prototypes, §E binary open-set τ sweep; per-leg space |
| `scripts/eval_harness/landmark_cache.py` | **New** — §S4 fixed offline GT-landmark pass; pins model_id+sha in provenance; artifact cache keyed by media_id+box index |
| `scripts/eval_harness/synthetic_occlusion.py` | **New** — seeded generators; landmark-affine placement from the cache |
| `scripts/eval_harness/face_metrics.py` | Face-level ID P/R, unknown-rejection, single-linkage clustering purity/false-merge/false-split (§F); keep existing image-level `detection_pr`/`identification_pr` helpers |
| `scripts/eval_harness/report.py` | `score_face_run_record` / face report builder; floor rollup; gate proposal section; route through `_filter_for_public_audience`; **do not** force caption path |
| `scripts/eval_harness/strata.py` | `SliceTag`-filter helpers for bake-off slice selection; `Domain` shortlists unchanged; occlusion rollups never bound to `Domain.OCCLUSION` |
| `scripts/eval_harness/cli.py` | `face-bakeoff` + `score-face` (or kind-dispatch) + `--check-determinism` on face score path |
| `scripts/eval_harness/export_identities.py` | **No tag/domain/cohort writes** in `enrich_entry` (identity + detection-GT only preserved) |
| `scripts/eval_harness/perf_leg.py` | **New** — detect+embed throughput; reads budget JSON |
| `scripts/eval_harness/perf_budgets/face_bakeoff_budget.json` | **New** — recorded device budgets + $/hr |
| `scripts/eval_harness/README.md` | Face bake-off runbook; env guard; no-tenant rule; buffalo-artifact-non-promotion; floor + demotion policy |
| Makefile (service or monorepo as existing eval targets) | `bakeoff-face` target |
| `pyproject.toml` | Ensure `[bench]` remains the only insightface path; document `ACX_EVAL_BENCH` |
| `scene/tests/test_eval_harness_manifest.py` | tags + cohort + unknown-tag + legacy domain |
| `scene/tests/test_eval_harness_strata.py` | tag selection helpers only if strata API changes |
| `scene/tests/test_eval_harness_face_metrics.py` | new metrics + can-fail stranger-label + forced merge/split fixtures |
| `scene/tests/test_eval_harness_face_assignment.py` | **New** — IoU/Hungarian association, gallery split, τ sweep, per-leg space |
| `scene/tests/test_eval_harness_report.py` | face score path; floor gating; determinism; publishability redaction |
| `scene/tests/test_eval_harness_face_bakeoff.py` | **New** — walker, env guard, negative-import gate |
| `scene/tests/test_eval_harness_landmark_cache.py` | **New** — pinned model_id/sha recorded; no live leg call during generation |
| `scene/tests/test_eval_harness_synthetic_occlusion.py` | **New** — seed identity (hash) + anatomy anchors |
| `scene/tests/seed/README.md` (if present) | tag/cohort authoring notes for operators |

**Out of scope / do not modify for this task**: `face_pass.py` (tenant-writing live pass), production clustering defaults (`ClusteringSettings`), production embedding stack (`embeddings/`, `runtime_factory.py`), runtime scan path.

## Scope amendment (p95 + A10 deferral — normative)

Scope Success criterion 3 enumerates the throughput/cost leg as "embeddings/sec + sec/image on ARM A1 **and A10**, cost per 1k images, **p95 scan latency vs recorded budget**." FIR-5 intentionally narrows this and records the deviation here rather than silently dropping it:

- **FIR-5 emits**: pure detect+embed throughput (images/sec, embeddings/sec, sec/image) + cost/1k on **A1** (and **A10 only when co-scheduled** with VLM-6 S3 or an operator-booked window — otherwise A10 numbers are deferred, not faked).
- **p95 full-scan latency is deferred**: scan = persist+cluster+job is the runtime path, not the offline harness. It is owned by **FIR-6 calibration/switch-over** (which touches the runtime) — recorded so **FIR-6's gate is not blocked on a number FIR-5 never emits**. The bake-off report's gate-proposal section must state "p95 scan latency: FIR-6-owned; not measured here."
- This narrowing requires an **operator acknowledgement** (the same operator who records the gate) — the report flags it as a scope deviation for sign-off, not an implementer decision.

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

- [ ] S1: `SliceTag` (7 values) + additive `tags` + `demographic_cohort`; Domain unchanged; tags via manifest authoring; loader rejects unknown tags; enrich_entry identity+detection-GT only (no tags/domain/cohort)
- [ ] S2: new face walker + §B run-record (embeddings/bboxes/landmarks, **no** assignment field); `DocKind.FACE_RUN_RECORD`; YuNet+SFace offline leg; buffalo `[bench]` + `ACX_EVAL_BENCH` importing insightface directly → JSON only; negative-import gate (incl. `InsightFaceAdapter`/`runtime_factory`/`face_pass`/`seed_roster`); ARCH-06 walker fork recorded
- [ ] S3: §C IoU/Hungarian association + §D seeded gallery split/prototypes + §E binary open-set τ sweep (per-leg space); §F face-level ID P/R, unknown-rejection, single-linkage purity/false-merge/false-split with exact formulas + can-fail stranger-label/merge/split fixtures; product thresholds deferred to FIR-6
- [ ] S3d: demographic Fair-SA rollups DIRECTIONAL (no floor); `demographic_cohort` authored with tags
- [ ] S4: `landmark_cache.py` fixed offline pass (pinned model_id+sha, no live leg call); seed+affine masked/sunglasses/occlusion_other generators from the cache; both legs re-detect on identical occluded pixels; ≥90-pair floors; hash-identical pixels
- [ ] S5: `score_face_run_record` + floor-gated rollup; pure score `--check-determinism`; detect+embed perf + budget JSON (not full-scan p95); operational synthetic↔real divergence; report+gallery publishability-filtered; gate proposal only
- [ ] Scope amendment recorded (p95 + A10 deferral) and flagged for operator acknowledgement
- [ ] Buffalo run-records stay in git-ignored `out/`, never promoted/committed (test asserts no 512D embedding under `docs/tasks/**`)
- [ ] Headline and all gating slices DIRECTIONAL until Golden-150 floors met; close only after real-corpus offline run with floors green **or** operator-recorded demotion
- [ ] Per-slice adversarial review (≥1 remote HIGH + local adversarial), findings in MCP (not pasted into this plan)
