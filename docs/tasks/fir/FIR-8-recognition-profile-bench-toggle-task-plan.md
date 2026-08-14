# FIR-8. Cross-stack face-pipeline bench orchestration

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok (docs-only plan authoring)
> - **Plan version**: v6.7 — **changelog (v6.6→v6.7, adversarial-gate remediation)**: fractional `accepted_set_floor` resolves against `|manifest entries loaded for this run|` as corpus denominator N (`resolved_floor_count = max(2, ceil(accepted_set_floor × N))`), with worked example and stamps `resolved_floor_count` / `accepted_set_size` / `manifest_entry_count`; CI field renamed `ci_half_width_pp` → `ci_half_width` on the unitless 0..1 metric scale (no field carries a percentage-point encoding); bootstrap interval pinned as equal-tailed 95% percentile with linear interpolation, `ci_half_width = (upper − lower) / 2`, and per-cell stamps `ci_level` / `ci_lower` / `ci_upper` / `bootstrap_resamples` / `bootstrap_seed` / `resampling_unit`; Holm–Bonferroni on secondaries pinned under Secondary-endpoint significance (H0 Δ = 0, two-sided bootstrap p from the same B = 2000 replicates, α = 0.05, empty family allowed); precision RED/GREEN fixtures inverted to a discriminating pair (identical legs → half-width 0; discordant ±1 pattern → half-width ≫ δ/2) with threshold assert on RED; two scoring populations named — `accepted_set` for identification/primary, `detection_scoring_set` for detection endpoints — with separate size stamps; box-less / non-exhaustive detection cells are **DIRECTIONAL** with reason `detection_exhaustiveness_unasserted` (DIAGNOSTIC reserved for hard-precondition failures); prediction export `bbox` keys pinned to `{x, y, width, height}` with producer cites `stores.py:220-235` / `scan/service.py:517-520` (GT `FaceBox` keeps `{x, y, w, h}`); `box_convention_unknown` is set-equality on the prediction key set; `image_dimensions_missing` is the disjoint missing/non-positive dimension code; post-conversion boxes clamped componentwise to [0, 1] with `degenerate_box_dropped` provenance; `image_width` / `image_height` produced at ingest by Pillow after `ImageOps.exif_transpose` in `corpus.py` `ItemOutcomeStore`, rejected at load when missing/non-positive, with `image_decode_failed` on open failure; Hungarian assignment reproducibility pinned to `scipy.optimize.linear_sum_assignment` on `-IoU` (`face_assignment.py:188-196`) without a uniqueness claim; stable error-code table closed for body fail-closed / reason codes including `deploy_ownership_key_rejected`, `cluster_gate_refused`, `max_differential_attrition_invalid`, `base_url_invalid`, `base_url_not_allowlisted`, `config_endpoint_invalid`, `export_media_not_in_roster`, `image_dimensions_missing`, `image_decode_failed`, `accepted_set_below_floor`, `ci_half_width_above_precision_floor`, `detection_exhaustiveness_unasserted` (error-code counts referenced via the table rather than a fixed numeral); `load_bench_manifest(..., require_detection_exhaustiveness: bool = False)` gates `gt_box_count_mismatch` vs non-exhaustive marking; `v2_boxed_detection.json` specified as a literal loadable fixture with required Golden fields; localization [TEST-15] red-proof pinned to exact 1000×1000 geometry (GT centre 0.5/0.5/0.2/0.2; GREEN pred 400/400/200/200; RED pred 700/400/200/200); `matched_faces` bounds table enumerates five cases including the load-bearing upper bound; retired-subtraction assertion scoped to `scripts/bench/` with `report.py:454-461` recorded as read-not-edited divergence; matching threshold is existing `IOU_MATCH_THRESHOLD` at `face_assignment.py:29` (no second `BOX_IOU_MATCH` constant); zero detections vs absent media resolved via `items.jsonl` roster membership with `zero_detection_media_count`, `ingest_asymmetric_media`, and `export_media_not_in_roster`; `to_face_metric_inputs(..., frame: Literal["native", "e2e"])` makes identification-row construction frame-parameterized (detection rows identical across frames; primary uses `e2e`); `baseline_superset_checked` moved to score-side provenance (never written by preflight); proof bar adds `uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py` from `apps/prototype-description-service`; body references to retired percentage-point field names (`mde_pp`) rephrased to prose; error-code table rows added for remaining body reason codes; in-document link targets use GitHub heading slugs (punctuation dropped, spaces to hyphens, including double hyphens where punctuation sat between words); Verification Strategy item 2 rewritten to manifest-level `assert_baseline_superset(manifest_ids, baseline_ids)` matching the S1 pin and `baseline_manifest_path`; localization [TEST-15] adds centre-in-box/containment RED case (pred `{100,100,800,800}` → IoU 0.0625, `matched_faces = 0`) alongside the translation RED; occasion-level resampling pinned with full-acceptance / paired-unit / mixed-`resampling_unit` rules (a)–(c), `partial_occasions` stamp, and media-vs-occasion [TEST-15] discrimination; dual-frame unit test requires whole-image zero-export accepted media in the recall denominator on both frames; `native`/`e2e` rows derived from the accepted set with zero-export as a zero-detection row; DIRECTIONAL tier semantics name join-phase attrition alongside ingest/analyze failures; provenance stamps `attrition_ingest_analyze` and `attrition_join`; S1 ingest wiring writes terminal ingest outcome to `items.jsonl` at analyze return (missing outcome = failure for condition (i)); floor persist keys pinned to `floor_config` (raw) and `resolved_floor_count` (integer used); third floor name removed; integer `accepted_set_floor` > `|manifest entries|` fails closed at `run`/`score` after manifest load with `accepted_set_floor_exceeds_corpus`; `stack_pair` validates form only; `opencv_major_drift` removed from the stable error-code table; residual-risks prose records that OpenCV major drift is undetectable until the upstream model-cache field lands; S1 Files-and-functions table gains `scripts/bench/__init__.py` package marker row; `test_export_map_rg015.py` moved to Slice 1 (Files table, proof commands, checklist) with red condition on synthesised envelope fields; removed from Slice 2. — **changelog (v6.5→v6.6, validators / commands / mechanical sweep)**: operator commands prefixed with `uv run` and `--out`/`--run-dir` resolved to repository-level `benchmarks/`; load-time contracts pinned for `base_url`, `primary_endpoint`/`secondary_endpoints`, and `max_differential_attrition`; `opencv_major` / `opencv_major_source` flattened with `opencv_major_unattested` as the sole reachable failure path and `opencv_major_drift` reserved; deploy-ownership reject keys enumerated by exact name; package-bootstrap rows reconciled; `export_map` S1/S2 symbol split made exclusive; Files-to-Change completeness confirmed (`test_eval_harness_face_metrics.py`, `report.py` read-not-edited, `v2_boxed_detection.json`, `test_cluster_gate.py`); version stamps to v6.6; retired statistical vocabulary / `annotation_mode` / `manifest_loader_unavailable` survivors swept; S2 checklist `power` renamed to `test_precision_precondition`. Carries forward the v6.5 corrections: normalized-centre GT + absolute-pixel predictions into normalized top-left scoring space; v2 detection fixture replacing v3/`annotation_mode` (S2 decoupled from FIR-11); capability-detection loader rule and `manifest_loader_unavailable` deleted; optional config keys `baseline_manifest_path` + `media_url_map_path`; `stack_media_id` as int; accepted-set three-condition propagation; cluster-gate move to S1 completed; `head_to_head_delta` and `accepted_set_floor` contracts; attrition ordering. — **changelog (v6.5 structural decoupling, pass 1)**: coordinate convention rewritten to real GT (normalized centre `FaceBox`) + absolute-pixel predictions, both converted to normalized top-left scoring space; `items.jsonl` persists `image_width`/`image_height`; `box_convention_unknown` no longer fires on normalized/centre-form boxes; `BOX_IOU_MATCH = 0.5` introduced as a **new** constant sole-declared in `scripts/bench/score.py`; detection fixture renamed to `v2_boxed_detection.json` (`manifest_version: 2`); all `annotation_mode` / v3 / capability-detection loader branching deleted (no unavailable-loader error code) — FIR-8 loads via `load_manifest` against v2, full stop; exhaustiveness is FIR-8's own `face_count == len(face_boxes)` assertion (`gt_box_count_mismatch`); FIR-11 Slice 2 decoupled from every S1/S2 code path and fixture (relevant only as a later larger boxed corpus); optional config keys `baseline_manifest_path` and `media_url_map_path` added (schema 21 → 23 keys); `stack_media_id` is int with int-to-int join and no coercion; join failure redefined as export-side absence. — **changelog (v6.4→v6.5, sequencing corrections; the 12 slice-ordering findings the v6.4 pass did not touch)**: export ownership pinned to a single symbol `export_map.export_leg` created in S1 where it is called from (`export_and_persist_leg` never existed), with `test_cluster_gate.py` moved to S1; a normative key schema added for the stack-pair config ([rg-008]), which the shipped example previously failed; compose project name explicitly excluded from [PROV-01] stack identity (`stack_id` + `base_url` instead); accepted set redefined on **three** conditions including the int `stack_media_id` join key, so a zero-detection image is a scored miss and not a silently deleted join failure; the baseline-superset blocker moved to `run` start against the **manifest** set when `baseline_manifest_path` is set (strictly stronger, and fails in seconds); the cluster gate re-specified as *all analyze jobs terminal and ≥1 success* (an all-succeed gate is unreachable the moment one item fails, contradicting `accepted_set_floor: 0.90`); no centre-in-box *match-predicate* fallback for detection matching (the asymmetry with the label map is deliberate; centre-form *coordinate encoding* is the expected GT); the `matched_faces` claim downgraded from *byte-identical* to *numerically identical*; floor-policy slice ownership split (S1 config surface / S2 resolution) with three new S1 red-proofs (`accepted_set_floor` load forms, `opencv_major_unattested`, and the cluster gate); the zero-edit claim scoped to *recognition-service* source and both harness files named; and `differential_attrition_exceeded` ordered to write the accepted-set and attrition artifacts **before** refusing to emit P/R. — **changelog (v6.3→v6.4, adversarial-review corrections; 42 findings from four independent reviewers, verdict FAIL on v6.3)**: the v6.3 "power precondition" is **retired as a category error** and replaced by a [precision precondition](#precision-precondition-normative) — image-level cluster bootstrap on the shared accepted set (pairing and within-image correlation handled by the resampling unit, no McNemar, no Wilson, no `ρ`/`DEFF`, no FIR-11 Slice 4 dependency), CI half-width ≤ δ/2 in place of post-hoc `mde_pp`, one pre-declared primary endpoint plus Holm across declared secondaries, seeded and reproducible; the fictitious `floor_below_power_floor` code removed and `accepted_set_floor` resolved to an item count before any comparison; localization pin corrected — Hungarian (not greedy) matching, pinned box coordinate convention, `max(0, ·)` clamps restored on the `matched_faces` arithmetic, and a hard `0 ≤ matched ≤ min(pred, labeled)` bounds check; the double-counting detection FN injection removed from `frame_e2e`; `golden.json` (37 entries, all carrying `face_count`, zero `face_boxes`) explicitly disqualified as a detection fixture; `report.py` inventoried as the second `ImageDetection` consumer with a required regression assertion; the exhaustiveness downgrade row added to the cell→tier table so the plan's own eligibility ceiling is machine-enforced; `face_metrics.py` no longer described as unmodified. — supersedes in-service bench supervisor (v5); re-scopes to cross-stack orchestration aligned with FIR23-STACK + QA v2; **changelog (v6→v6.1)**: real preflight contracts, explicit cluster phase, feasible public-export scoring scope, dual scoring frames, crossbench tier enum, ingest→analyze→cluster→export flow, pinned FIR23-STACK consumption table, single package root; **changelog (v6.1→v6.2)**: ground-truth wiring + label mapping, S1 executable granularity (run-dir/resume/credentials/status/PROV-01), concrete CrossbenchTier assignment rules, EVAL-19 accepted-set operationalization, proof-suite + dual-frame FIR-5 signature pins; **changelog (v6.2→v6.3, planning-review corrections)**: `opencv_major` given a real source (operator attestation + upstream ask, local `cv2` forbidden); CONFIRMATORY gains a power precondition (declared δ, exact-binomial McNemar on the paired legs, per-cell MDE, pool-conditional Wilson, ρ gate) and the previously-unassignable underpowered row; detection P/R made localization-aware via IoU matching + one scoped additive `face_metrics` change, with a [TEST-15] count-preserving red-proof; the `stranger_faces` subtraction retired; `accepted_set_floor` re-defaulted to a fraction with a power floor and a differential-attrition bias check; `frame_e2e` pinned as the sole CONFIRMATORY sampling frame; `labeled_faces` denominator pinned to `len(face_boxes)`
> - **Projects**: `apps/prototype-description-service/scripts/bench/` (primary, new — single package root); consumes `apps/prototype-description-service/scripts/eval_harness/` (FIR-5, merged); **no** recognition-service code changes
> - **Task ID**: `FIR-8`
> - **Target Branch**: `feature/fir-8`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on (BLOCKING)**: **FIR23-STACK** delivers the running `acx-dev-fir` stack (compose project, network, DB `alt_context_dev_fir` @ `PGVECTOR_DIM=128`, ingress `fir.api.altcontext.com`) standing next to the existing dev stack (512-D insightface). FIR-4 (runtime factory + profile seam, merged). FIR-5 harness (face metrics / remote client / cluster export helpers, merged to main @`07f9a5d1`).
> - **House style note**: Structure follows the TASK_PLAN template (objective → constraints → slices with named files/functions + proof). Junior-executable contracts; no finding lists; no status trailers.
> - **Review Coverage Target**: 2
> - **Isolation track (LOCKED)**: **per-model isolated stacks** (FIR23-STACK) — not a runtime profile toggle, not an in-service supervisor
> - **Execution mode (LOCKED)**: **operator CLI** drives both stacks over public APIs; wall-clock + queued-age budgets enforced by the CLI (not a service supervisor)

## Objective

Score **InsightFace** (dev stack, 512-D buffalo_l) vs **FIR candidate** (`acx-dev-fir` stack, 128-D face_pipeline / SFace) head-to-head on the **same corpus** by driving **both** stacks over their public APIs and scoring public exports with the merged FIR-5 pure face-metric functions.

Deliverable: a **bench-orchestration CLI** + **scoring path** + **operator runbook**. **No recognition-service code changes.** Stack deploy/compose/Caddy/systemd ownership stays with FIR23-STACK.

## Intake

- **Operator ask**: measure the quality gap between buffalo_l (internal-bench only) and the commercial candidate face_pipeline on a fixed corpus, with honest cascade denominators and per-run provenance — without mixing embedding spaces in one DB.
- **Ground truth (operator-accepted)**:
  1. **One vector space per (modality, model)** — canon EMB-01 / IDX-02 + QA doc digest (`benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` §per-modality tables): buffalo_l=512-D and SFace=128-D **cannot share a DB**; each DB is dimension-pinned by `PGVECTOR_DIM` (three-way guard in `face_pipeline_adapter.py`); clusters are model-specific materialized outputs. Cross-model reads = mixed-space garbage.
  2. **FIR23-STACK already owns the deployment answer**: profile-pinned isolated stacks side-by-side, **not** a per-request profile header or in-process dual-dim toggle.
  3. Therefore v5's in-service async bench supervisor is the **wrong layer** — it duplicates exclusivity/teardown that stack isolation already provides and collides with FIR23-STACK ownership. Supersession: [Superseded: v5 in-service vehicle](#superseded-v5-in-service-vehicle).
- **Key Q&A decisions**: decision **#2951** (supersede in-service supervisor; re-scope to cross-stack orchestration). Isolation mode locked by FIR23-STACK deployment design, not re-litigated here.
- **Not-Doing**: [Non-goals](#non-goals).

## Problem Statement

Operators need a head-to-head score of insightface (512-D) vs face_pipeline (128-D) on one corpus. Same-process dual-profile and same-DB dual-dim are structurally impossible ([EMB-01], [IDX-02]). Isolated stacks (FIR23-STACK) solve space separation. What remains is **orchestration**: **ingest → analyze → cluster → export** the same media on both endpoints, score with FIR-5 pure functions (`detection_pr` / `identification_pr`), emit a tier-labeled report — without inventing a parallel scorer or mutating recognition service code.

## Constraints

- **No recognition-service code changes** in this task. No new `/admin/bench/*` routes, no `recognition_bench_runs` table, no scan_worker supervisor tick, no boot-coupled bench license gate inside the worker/API process.
- **FIR23-STACK owns deploy surfaces.** Compose projects, networks, DB names, Caddy/ingress, systemd units, and stack-scoped DB reset paths are FIR23-STACK. If a stack gap blocks a bench run, **route to FIR23-STACK** — do not expand this plan into infra ownership. The CLI only consumes the pinned [FIR23-STACK consumption table](#fir23-stack-consumption-table-pinned); anything not listed there is FIR23-STACK-owned.
- **One vector space per stack** ([EMB-01], [IDX-02]). CLI preflight **fails closed** when either stack drifts from its pinned `(profile, dim)` pair — see [Real preflight contract](#real-preflight-contract).
- **Reuse FIR-5 pure face metrics** (merged @`07f9a5d1`). Map public exports into `face_metrics.ImageDetection` / `ImageIdentities` → `detection_pr` / `identification_pr` under `scripts/eval_harness/face_metrics.py`. Do not invent a parallel scorer. Do **not** require embedding vectors or landmarks from the public API (they are not present on the public media/cluster export surface — see [Feasible scoring scope](#feasible-scoring-scope)).
- **License**: insightface / buffalo_l stack is **INTERNAL BENCH ONLY** (NC weights). Outputs never become training data; never user-facing/commercial ([RLSE-05], QA digests §buffalo-as-judge).
- **Boundary honesty** ([rg-015]): when normalizing the two stacks' API payloads, every envelope field (`limit`, `offset`, `total`, status/projection metadata) comes from the request, the upstream payload, or a **named** documented constant — never `count(payload)` invention.
- **Cascade honesty** ([EVAL-16]): a face a stack's detector missed counts as an identification error end-to-end in the head-to-head report — enforced by the adapter dual-frame construction (see [End-to-end scoring frames](#end-to-end-scoring-frames)).
- **Fixed denominators** ([EVAL-19]): two scoring populations, both computed once and written under `score/`. **`accepted_set`** — manifest items that, on **both** legs, satisfy all three conditions: (i) terminal-success ingest, (ii) terminal-success analyze with int `stack_media_id`, (iii) the media id is present on that leg's `items.jsonl` roster (the authoritative submitted-media roster — zero export rows means zero detections, not a join miss) — written to `score/accepted_set.json`, asserted identical across legs before any metric; population for identification endpoints and the primary endpoint. **`detection_scoring_set`** — `accepted_set` minus every entry that does not carry exhaustive `face_boxes` (`face_count == len(face_boxes)`, boxes present); population for all detection endpoints (detection precision/recall, FP counts); a subset of `accepted_set` by construction. Attrition of one-sided failures is reported, not silently dropped (see [EVAL-19 operationalized](#eval-19-operationalized-accepted-set)).
- **Per-run provenance** ([PROV-01]): every report and run-dir stamps the full field inventory in [PROV-01 via `preflight.json`](#s1-executable-contracts-normative) — that section is the **single normative list** (leg-disambiguating fields, run-disambiguating fields, and per-item `items.jsonl` fields including `image_width`/`image_height`). Do not re-list a partial subset elsewhere as if it were complete. Compose project name is **not** stamped (see the note under the consumption table). <span>The `cv2` / `opencv_major` field was added 2026-07-28 (QA v8 re-gate): CVUP-1 moves the stack 4.x → 5.x and changes embeddings without changing any model id, so without it a pre- and a post-upgrade crossbench run are indistinguishable in the artifact and silently comparable in the report.</span>
  > **This field has no source yet, so the plan names its source rather than assuming one.** No service surface reports it: the preflight contract below reads `model_cache.profile` and the `/ready` database detail only, and neither `api/main.py` `register_health_probes` nor `recognition/application/health.py` returns an OpenCV version (a `cv2` search across both files returns zero hits). **A locally-read `cv2.__version__` is forbidden** — the CLI runs on the operator laptop, so it would stamp the laptop's toolchain onto a remote stack's run and produce a provenance field that is worse than absent because it looks authoritative. Resolution routes through the [consumption-table rule](#fir23-stack-consumption-table-pinned) verbatim — *a needed field absent from the table is a FIR23-STACK deliverable or an operator attestation, never a silent FIR-8 invention*: S1 takes it as a **required per-stack operator attestation** (`opencv_major` in the stack-pair config), fails closed when absent, and stamps it into `preflight.json` as flat keys `opencv_major` (int) and `opencv_major_source: operator_attested`. The **upstream ask** — add `opencv_version` to the `/health/detailed` `model_cache` block so the value is service-reported and unfalsifiable — is filed against the recognition service and recorded in the runbook residual section; when it lands, preflight reads it, compares it to the attestation, and fails closed on disagreement. Until then the attestation is a declared weak link, not a verified stamp.
- **Canon**: heuristics v0.12.3; distilled refs `~/Development/heuristics-canon-research/distilled/ml-systems/janus-benchmark-c.md` (pooling-unit / cascade eval), `handbook-face-recognition.md`.

## Workflow Principles

- **Drive stacks as black boxes** via public HTTP APIs already used by `scripts/eval_harness/remote_client.py` (`analyze`, `wait_job`, `media_identities`, `clustering_job`, `clusters`, `cluster_members`). Prefer extending that client or a thin wrapper in the bench package over ad-hoc curl. **Note**: `RemoteSceneClient` exposes **no** health methods — preflight performs its own authenticated GETs (see [Real preflight contract](#real-preflight-contract)).
- **CLI is the supervisor.** Wall-clock budget + per-item / queued-age timeouts live in the CLI process. No service-side single-live-run index.
- **Idempotent resume.** Per-item ingest/analyze outcomes persist under the run directory so a crashed run continues without double-billing work that already succeeded.
- **Fail closed on preflight drift.** Dimension or profile mismatch on either stack aborts before any media write.
- **Explicit cluster phase.** Once every analyze job for a leg has reached a **terminal** outcome — success, or failure with `item_max_attempts` exhausted — **and at least one succeeded**, within budget, call `RemoteSceneClient.clustering_job(tenant_id, mode="sync")`, persist the job outcome, and **gate export on cluster-job success**. *Terminal*, not *successful*: an "all analyze jobs succeed" gate is unreachable the moment one item fails, which would block clustering on every run the `accepted_set_floor` of 0.90 is explicitly designed to tolerate, and would contradict the resume rule that re-runs the cluster phase only when `cluster_job.json` is missing or non-success **and** the leg still satisfies this same gate. **All-fail leg outcome (executable contract):** when a leg has zero analyze successes, `run` does **not** cluster, does **not** export, and records terminal leg outcome `cluster_gate_refused` under `legs/<stack_id>/leg_outcome.json` (status reports phase `failed`). One condition, stated identically in all **five** places: Workflow Principles (here), the [resume rule](#s1-executable-contracts-normative), [CF-6](#cf-6-cluster-before-export), the S1 checklist, and `test_cluster_gate.py`.
- **Stack gaps escalate out.** Missing ingress, wrong dim in compose, broken reset path → FIR23-STACK ticket / decision, not a FIR-8 code fork into deploy YAML.

## Terminology

| Term | Meaning in this plan |
| --- | --- |
| **Dev stack** | Existing recognition deployment: `RECOGNITION_FACE_PIPELINE_PROFILE=insightface`, `PGVECTOR_DIM=512`, public API base (operator-configured; typically `https://dev.api.altcontext.com`). **Internal bench only** for commercial product posture. |
| **`acx-dev-fir` stack** | FIR23-STACK profile-pinned isolated stack: compose project + network + DB `alt_context_dev_fir` @ `PGVECTOR_DIM=128`, profile `face_pipeline`, ingress `fir.api.altcontext.com`. FIR candidate leg. |
| **Stack pair** | Named config binding both base URLs, API keys / tenant ids, expected `(profile, dim)` pairs, and optional LAN override flag for private media hosts. Validated at load against the [FIR23-STACK consumption table](#fir23-stack-consumption-table-pinned) ([rg-008]); unknown `stack_id` values are refused. |
| **Corpus / manifest** | Golden-schema corpus loaded via `scripts.eval_harness.manifest.load_manifest` (CLI `--manifest`). Media bytes from manifest-relative local paths (under `--images-dir` / corpus root) or pinned remote URLs. |
| **Leg** | Full **ingest → analyze → cluster → export** path against **one** stack. A head-to-head run has two legs: `insightface@512` and `face_pipeline@128`. |
| **Accepted set** | Manifest items that, on **both** legs, satisfy (i) terminal-success ingest, (ii) terminal-success analyze with int `stack_media_id`, and (iii) presence on that leg's `items.jsonl` roster (zero export rows = zero detections, not a join miss). Scoring population for identification endpoints and the primary endpoint ([EVAL-19]); written to `score/accepted_set.json`. Distinct from pre-ingest validation. |
| **Detection scoring set** | `accepted_set` minus every entry that does not carry exhaustive `face_boxes` (`face_count == len(face_boxes)`, boxes present). Scoring population for all detection endpoints (detection precision/recall, FP counts); a subset of `accepted_set` by construction. Stamped as `detection_scoring_set_size` in provenance. |
| **Superset baseline** | Any uploaded or declared baseline / label artifact's `media_id` (or sha256) set **must be a SUPERSET** of the run's accepted set. Partial intersection = **blocker** (do not silently score a subset). |
| **Crossbench report** | Tier-labeled head-to-head artifact under `benchmarks/results/crossbench-<stamp>/`. Tier labels are a **new** crossbench report enum in `score_report.py` (`CONFIRMATORY` / `DIRECTIONAL` / `DIAGNOSTIC`) sourced from QA-digest/canon convention — **not** a FIR-5 enum (see [Tier vocabulary](#tier-vocabulary)). |
| **Named bench stacks** | Exactly the two stack identities listed in the stack-pair config (dev + `acx-dev-fir`). Production-shaped-data guard allows nonzero identity tables **only** on these two named stacks. |
| **Package root** | Single root: `apps/prototype-description-service/scripts/bench/`. Tests import via `scripts.bench.*` with `apps/prototype-description-service` on `PYTHONPATH` (same convention as `scripts.eval_harness`). |

## Current State Analysis

- **FIR23-STACK (parallel session, `feature/fir23-stack`)** owns isolated stack deploy: per-model stacks, not runtime toggles. That design **supersedes** per-request profile headers and the v5 in-service bench vehicle.
- **FIR-5 harness is on main** (`07f9a5d1`): pure face metrics (`face_metrics.py`), remote client (`remote_client.py`), cluster export helpers under `apps/prototype-description-service/scripts/eval_harness/`. Reuse; do not fork.
- **Health / ready endpoints** (verified in `api/main.py` `register_health_probes` + `recognition/application/health.py`):
  - `GET /ready` returns `{status, checks: [{name, status, detail}, ...], timestamp}`. The database check (`name=="database"`) OK detail is literally `reachable; pgvector_dimension={configured_dim}` (from `validate_identity_vector_dimensions` / `check_database`).
  - `GET /health/detailed` is **auth-gated** (`Depends(require_auth)`). Returns `model_cache: {model_name, cache_dir, bundle_files, status, detail, profile}` where `profile` is the active `RECOGNITION_FACE_PIPELINE_PROFILE` (`insightface` \| `face_pipeline`).
  - `RemoteSceneClient` has **no** health helpers — confirmed method set: `describe`, `analyze`, `wait_job`, `media_identities`, `clustering_job`, `clusters`, `cluster_members`, `patch_cluster`. Preflight must issue its own HTTP GETs.
- **Public export surface** (`MediaIdentityService.list_by_media_ids` top-level keys; characterization test `API_FACE_PAYLOAD_TOP_LEVEL_KEYS`): `identity_id`, `media_id`, `cluster_id`, `cluster_label`, `is_auto_label`, `clustering_pending`, `bbox` (`x/y/width/height`), `confidence`, `media_url`. Cluster members add similarity/confidence/bbox — **no embedding vectors, no landmarks** on the public path.
- **Three-way dim guard** lives in `face_pipeline_adapter.py` / factory construction — each stack is already fail-closed on dim/profile mismatch **internally**. Cross-stack orchestration still needs an **external** preflight that both stacks match the **expected pair** for this bench (dev=512/insightface, fir=128/face_pipeline).
- **No `scripts/bench/` package yet.** This task creates it under the single package root above.
- **v5 plan** (recoverable at git `bc97ff4b`) specified an in-service async supervisor, `uq_bench_single_live`, purge-before-terminal, marker rail, boot-coupled license gate, tick contract. **Superseded** — see below. Do not re-implement.

## Target Outcome

1. Operator configures a stack-pair file pointing at dev + `acx-dev-fir` endpoints (validated against the pinned consumption table).
2. CLI preflight proves both stacks are healthy and match pinned `(profile, dim)` via the real health contracts; fails closed on drift / auth / missing fields with distinct stable error codes.
3. CLI loads golden-schema **manifest** GT, **ingests** media (local-then-remote + CF-1 pin), **analyzes** on both stacks (`analyze` + `wait_job`), runs **cluster** (`clustering_job(..., mode="sync")`), **exports** clusters/assignments into the run-dir; persists per-item + cluster outcomes; resumes safely.
4. CLI maps GT + exports into FIR-5 `ImageDetection` / `ImageIdentities` (with label-space mapping), scores detection P/R + identification P/R under dual sampling and label-map frames offline (`score` needs no credentials), emits a tier-labeled head-to-head report under `benchmarks/results/crossbench-*/` with `accepted_set.json`, attrition, `preflight.json` provenance, and cascade-honest denominators.
5. Runbook documents license posture, preflight, run, score, and **stack-scoped teardown** via FIR23-STACK's documented reset path (not a new FIR-8 reset invention).
6. Zero **recognition-service** source edits land in this task's commits. This is not "zero edits outside `scripts/bench/`": the diff also carries two offline-harness files — `scripts/eval_harness/face_metrics.py` and `scene/tests/test_eval_harness_face_metrics.py` — enumerated in [Files and Surfaces to Change](#files-and-surfaces-to-change). Neither is recognition-service code, so the constraint holds; reading item 6 as a no-edits-anywhere claim does not.

## Context Loading (read before implementation)

| Order | Path | Why |
| --- | --- | --- |
| 1 | This plan (v6.7) end-to-end | Locked scope, dependency boundary, carried invariants, slices |
| 2 | `apps/prototype-description-service/scripts/eval_harness/remote_client.py` | Existing HTTP client (`analyze`, `wait_job`, `media_identities`, `clustering_job`, `clusters`, …) — **no health methods** |
| 3 | `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` | Pure `ImageDetection` / `ImageIdentities` + `detection_pr` / `identification_pr` — scoring legs; receives the scoped additive `matched_faces` edit (default `None` → **numerically identical** existing `detection_pr` output) |
| 3b | `apps/prototype-description-service/scripts/eval_harness/manifest.py` | `load_manifest` → `GoldenManifest` / `GoldenEntry` / `FaceBox` — GT source + schema |
| 4 | `apps/prototype-description-service/api/main.py` `register_health_probes` + `recognition/application/health.py` | Real preflight field sources from `/ready` and `/health/detailed` |
| 5 | `apps/prototype-description-service/recognition/interface_adapters/http/deps/stores.py` `MediaIdentityService.list_by_media_ids` | Public export keys (bbox/cluster metadata only) |
| 6 | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Production-shaped-data table set (`tenants`, `media_identities`, `identity_clusters`, `identity_members`) |
| 7 | FIR23-STACK runbook / compose docs (when present on that branch) | Stack endpoints, reset path, network names — **consume, do not fork** |
| 8 | QA digest (authoritative for this lane): one space per (modality, model); buffalo = internal judge only; EVAL-16 / EVAL-19 / PROV-01 discipline | Ground truth that forced v6 re-scope |
| 9 | Distilled canon: `janus-benchmark-c.md`, `handbook-face-recognition.md` | Cascade / pooling-unit eval discipline |

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Recognition public API | description-service | existing analyze / clusters / media / health routes | **none** (read + existing write paths only) | n/a — consumer only | CLI integration uses recorded fixtures / mocks |
| FIR-5 eval harness | `scripts/eval_harness/` | pure face metrics + remote client | **thin adapter** in package root mapping stack exports → `ImageDetection` / `ImageIdentities`; no harness fork unless a documented gap is fixed upstream with rationale | yes — adapter must not invent envelope fields ([rg-015]) | unit tests + one mocked E2E |
| Stack deploy / reset | **FIR23-STACK** | isolated compose + DB + ingress | **none in FIR-8** | n/a | runbook cites FIR23-STACK commands only |
| WP plugin | WP | n/a | **none** | n/a | grep-clean of plugin paths in this task |

## Proposed Solution

**Single package root** (mandatory): `apps/prototype-description-service/scripts/bench/`.

**Package bootstrap (reconciled).** Parent `scripts/` is the **existing** package namespace already used by `scripts.eval_harness` — this task does **not** add `scripts/__init__.py`. The new package marker is **`scripts/bench/__init__.py`** only (listed in [Files and Surfaces to Change](#files-and-surfaces-to-change)). Tests import via `scripts.bench.*` with `apps/prototype-description-service` on `PYTHONPATH` (same convention as `scripts.eval_harness`). `scripts/bench/tests/` is collected by path (`pytest scripts/bench/tests/`) and does **not** require its own `__init__.py`.

Import path used by tests and CLI:

```bash
# from apps/prototype-description-service (or with that dir on PYTHONPATH)
# --out / --run-dir use ../../benchmarks/results/crossbench-<stamp>/ so artifacts land at the repo-level benchmarks/ root
# (`.gitignore` anchors `/benchmarks/`; app-local benchmarks/ is not ignored)
uv run python -m scripts.bench.cross_stack_bench --help
uv run --extra dev pytest scripts/bench/tests/ -q
uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py
```

```text
apps/prototype-description-service/scripts/bench/
  __init__.py
  cross_stack_bench.py          # CLI entry (preflight/run/status/score)
  stack_pair.py                 # load + validate stack-pair config against FIR23-STACK table
  preflight.py                  # own authenticated GETs; write preflight.json (PROV-01)
  corpus.py                     # load_manifest wrap, media resolve order, pin, items.jsonl
  driver.py                     # ingest → analyze → cluster → export both stacks; resume
  export_map.py                 # S1: export_leg/require_cluster_success/load_leg_exports; S2: map_*/to_face_metric_inputs/match_detection_boxes
  score.py                      # IoU / assignment helpers; threshold is IOU_MATCH_THRESHOLD from face_assignment.py
  score_report.py               # dual frames; CrossbenchTier rules; accepted_set; report
  production_shaped_guard.py    # refuse non-named stacks with nonzero core tables
  tests/                        # unit + one mocked E2E
docs/runbooks/
  fir-8-cross-stack-bench.md    # operator runbook (S3)
benchmarks/manifests/golden150-*.json  # operator/VLM-6 corpus (not invented in FIR-8)
benchmarks/results/crossbench-*/       # gitignored run outputs (run-dir layout)
```

**Operator flow**

1. Confirm FIR23-STACK has `acx-dev-fir` healthy next to dev.
2. `uv run python -m scripts.bench.cross_stack_bench preflight --config stack-pair.yaml` → both sides green or abort (writes per-leg `preflight.json` under `--out` when run-dir known, or dry-check without run-dir). Working directory: `apps/prototype-description-service`.
3. `uv run python -m scripts.bench.cross_stack_bench run --config stack-pair.yaml --manifest <golden-schema.json> --images-dir <corpus-root> --out ../../benchmarks/results/crossbench-<stamp>/` → ingest+analyze+cluster+export both legs; resume via append-only `items.jsonl`. Working directory: `apps/prototype-description-service` (so `--out` resolves to repository-level `benchmarks/results/`).
4. `uv run python -m scripts.bench.cross_stack_bench status --run-dir ../../benchmarks/results/crossbench-<stamp>/` → per-leg progress + phase (optional operator check). Working directory: `apps/prototype-description-service`.
5. `uv run python -m scripts.bench.cross_stack_bench score --run-dir ../../benchmarks/results/crossbench-<stamp>/` → reads run-dir only (no credentials); dual-frame FIR-5 pure metrics + head-to-head HTML/JSON (aborts if cluster phase missing/failed). Working directory: `apps/prototype-description-service`.
6. Teardown: FIR23-STACK stack-scoped DB reset for the FIR stack (and optional dev-bench tenant wipe per runbook) — **not** a new recognition purge phase.

---

## Superseded: v5 in-service vehicle

v5 specified an **in-service** async single-live-run bench supervisor inside the recognition worker: state machine over `recognition_bench_runs`, `uq_bench_single_live`, purge-before-terminal, deployment marker rail, boot-coupled license gate, non-blocking tick contract, and `/admin` bench routes. That vehicle is **superseded** by **per-model isolated stacks** (FIR23-STACK): exclusivity, no mixed-space reads, and teardown via stack-scoped DB reset are structural properties of the deploy topology, not application supervisor features. Re-implementing them inside the worker would duplicate FIR23-STACK ownership and re-open dual-space foot-guns. **Do not delete git history** — v5 plan text is recoverable at commit **`bc97ff4b`**. Decision **#2951** records the supersession. The rest of this document is the v6.7 scope (v6.1 structure, v6.2 grounding, v6.3 fixes, v6.4 review corrections, v6.5 structural decoupling, v6.6 validator/command/mechanical sweep, v6.7 adversarial-gate remediation).

---

## FIR23-STACK consumption table (pinned)

CLI config **validates against this table at load** ([rg-008]) and **refuses unknown stacks**. Anything not listed here is **FIR23-STACK-owned** (compose project names, networks, Caddyfile stanzas, systemd units, image tags, secret rotation, DB volume lifecycle). Values marked “operator-configured” are supplied via stack-pair YAML / env; the table pins the **identity** and **auth surface**, not secret material.

| Field | Dev stack (`acx-dev-insightface`) | FIR stack (`acx-dev-fir`) |
| --- | --- | --- |
| **stack_id** (allowlist key) | `acx-dev-insightface` | `acx-dev-fir` |
| **role** | `insightface_judge` (INTERNAL BENCH ONLY) | `face_pipeline_candidate` |
| **Base URL / ingress name** | Operator-configured; typical public ingress `https://dev.api.altcontext.com` (or operator LAN override). Ingress name is FIR23-STACK-owned; CLI only stores the configured `base_url`. | Operator-configured; typical public ingress `https://fir.api.altcontext.com` (FIR23-STACK ingress name). |
| **Expected profile** | `insightface` | `face_pipeline` |
| **Expected `PGVECTOR_DIM`** | `512` | `128` |
| **Tenant-id source** | Env ref `ACX_BENCH_DEV_TENANT_ID` (scratch/bench tenant; never a production customer tenant) | Env ref `ACX_BENCH_FIR_TENANT_ID` |
| **Auth env keys** | `ACX_BENCH_DEV_API_KEY` (API key for `require_auth` / `X-API-Key` as used by `RemoteSceneClient`) | `ACX_BENCH_FIR_API_KEY` |
| **Health endpoints used by preflight** | `GET {base_url}/ready` (unauthenticated readiness); authenticated `GET {base_url}/health/detailed` (same key as API key env) | same pair against FIR `base_url` |
| **DB-reset entrypoint** | Documented FIR23-STACK path for the **dev bench tenant / stack** (cite exact command from FIR23-STACK runbook when stable; placeholder until that doc lands — **do not invent** reset SQL here) | Documented FIR23-STACK path for **`acx-dev-fir` / `alt_context_dev_fir`** stack-scoped reset (same rule: cite FIR23-STACK only) |
| **CLI write policy** | Named bench stack allowlist only (CF-2) | Named bench stack allowlist only (CF-2) |

**Rule**: if a needed field is absent from this table, the gap is a **FIR23-STACK** deliverable or an operator attestation — not a silent FIR-8 invention. `stack_pair.py` rejects any `stack_id` not in the allowlist and rejects the exact deploy-ownership key set in [Key schema](#s1-executable-contracts-normative) (`compose_project`, `network`, `volume_path`, `volumes`, `image_tag`, `image`, `caddyfile`, `systemd_unit`, `db_volume`, `secret_rotation`) with **`deploy_ownership_key_rejected`**.

**Stack identity for [PROV-01] is part of the full inventory** in [PROV-01 via `preflight.json`](#s1-executable-contracts-normative): `stack_id` + `base_url` disambiguate the **leg**; `run_stamp` + `manifest.sha` + CLI/harness SHAs disambiguate the **run**. The compose project name is deliberately not stamped. An earlier revision listed "compose project name" in the PROV-01 constraint, which the rule directly above forbids from three directions at once: it is not in this table, the config schema has no field for it, no health endpoint reports it, and `stack_pair.py` is specified to *reject* config keys claiming deploy ownership — so the only ways to obtain it were the three this plan bans. If FIR23-STACK later exposes the compose project name on a diagnostic surface, it is consumed like any other table field — not invented here.

---

## Real preflight contract

`preflight.py` performs its **own** HTTP GETs (httpx or equivalent). It does **not** call methods on `RemoteSceneClient` for health — that client has none.

### Profile source

- **Authenticated** `GET {base_url}/health/detailed` with the stack's API key (same auth surface as `require_auth` on the service; `RemoteSceneClient` uses `X-API-Key` header — preflight must present a key the service accepts, typically `X-API-Key` and/or `Authorization` per deploy `api_key_header` setting).
- Read **`body["model_cache"]["profile"]`** (string: `insightface` or `face_pipeline`). Verified shape in `register_health_probes` → `health_detailed` return value.
- Fail closed if HTTP 401/403 → stable code **`preflight_auth_failed`**.
- Fail closed if HTTP 404 or transport/connection failure that indicates the route is absent → **`preflight_endpoint_missing`**.
- Fail closed if `model_cache` object or `profile` key is missing/empty → **`profile_or_dim_drift`** (missing profile is treated as drift, not a soft skip).

### Dimension source

- `GET {base_url}/ready` (readiness probe; no auth required for the probe itself).
- Locate `checks` entry where `name == "database"`.
- Require that check's `status` is OK (service uses `HealthStatus.OK.value`; fail closed on any non-OK, including UNHEALTHY/DEGRADED and missing check) → otherwise **`profile_or_dim_drift`**.
- Parse `detail` with a token-search regex `pgvector_dimension=(\d+)` (re.search over the detail string — the live form is `reachable; pgvector_dimension={dim}`, so a full-string anchor would never match) (must match the live detail form produced by `check_database` / `validate_identity_vector_dimensions`: e.g. `reachable; pgvector_dimension=512`). If the token is absent → **`profile_or_dim_drift`**.
- Compare captured int to `expected_pgvector_dim` from stack-pair config; mismatch → **`profile_or_dim_drift`**.

### Profile compare

- Compare `model_cache.profile` to `expected_profile`; mismatch → **`profile_or_dim_drift`**.

### OpenCV major source (attested, not probed)

The [PROV-01 constraint](#constraints) requires an OpenCV runtime major per leg and **no endpoint reports one**. Preflight therefore does not probe it:

- Read `opencv_major` (int) from the stack's stack-pair config entry. **Required at load and at preflight.** Absence (missing key) or unparseable value raises **`opencv_major_unattested`** — and that is the **only** failure path for this field today. There is no separate "required-at-load but soft-at-preflight" path; a missing attestation never produces a partial `preflight.json`.
- Never call `cv2.__version__` in the CLI process. The CLI runs on the operator laptop; its `cv2` is not the stack's `cv2`. A test asserts the bench package imports no `cv2` at all.
- Write into `preflight.json` as **two flat keys** — `opencv_major` (int) and `opencv_major_source` (string: `operator_attested` \| `service_reported`) — never a nested object `{"opencv_major": <int>, "source": "..."}` and never a bare `source: "..."` key. The report renders the value with the `operator_attested` / `service_reported` qualifier visible, never as a bare version string.
- **Forward path (upstream ask, not FIR-8 scope)**: when `/health/detailed` `model_cache.opencv_version` exists, preflight reads it, sets `opencv_major_source` to `service_reported`, and compares it to the attestation. Until that upstream field lands, OpenCV major-version drift between legs is not detectable as a fail-closed code — see [Residual risks](#residual-risks-pinned).

### Stable error codes (normative)

| Code | When | Operator remedy |
| --- | --- | --- |
| `preflight_auth_failed` | Authenticated `/health/detailed` returns 401/403 or auth dependency rejects the key | Fix the stack-pair API key / auth env so the authenticated health call is accepted. |
| `preflight_endpoint_missing` | `/ready` or `/health/detailed` not reachable as that route (404 / connection refused treated as missing endpoint for this purpose) | Bring the stack up and confirm both routes are served at the configured `base_url`. |
| `profile_or_dim_drift` | Profile missing/mismatch, database check not OK, dim token absent, or dim int ≠ expected | Align the live stack's profile and pgvector dim with the stack-pair `expected_profile` / `expected_pgvector_dim`, or correct the config if the expectation is wrong. |
| `opencv_major_unattested` | Stack-pair entry has no parseable `opencv_major` (absent or unparseable) — **the only reachable failure path for this field today** | Set a parseable integer `opencv_major` on the stack-pair entry (operator attestation). |
| `gt_box_count_mismatch` | `load_bench_manifest(..., require_detection_exhaustiveness=True)` and an entry has `face_count != len(face_boxes)` | fix the fixture/corpus so every detection-scoring entry carries a complete `face_boxes` list matching `face_count`; this is FIR-8's own gate under the flag, not an inherited v3 flag. |
| `box_convention_unknown` | a prediction `bbox` object's key set is not exactly `{x, y, width, height}` (set comparison — corner-form, renamed keys, extra keys, or any other shape) | the export contract changed; re-pin the conversion against the current envelope before scoring. |
| `image_dimensions_missing` | a record whose prediction boxes require conversion has `image_width` or `image_height` absent, non-integer, or ≤ 0 (also raised by the items.jsonl reader at load under [rg-008]) | re-run ingest for the affected media ids so each ok record carries positive int dimensions. |
| `image_decode_failed` | Pillow cannot open an image at ingest when decoding dimensions | the media id is excluded from the run and named in provenance; it does not silently become a zero-dimension record. |
| `matched_faces_out_of_bounds` | the adapter produced a `matched_faces` violating `0 <= matched <= min(pred_faces, labeled_faces)` | this is an adapter bug, not a config error; fix the matcher — do not clamp it away. |
| `differential_attrition_exceeded` | one-sided attrition skew exceeds `max_differential_attrition` | the surviving pool is biased toward the failing leg; repair that leg and re-run, do not score the subset. |
| `media_unresolvable` | an ingest item's media cannot be resolved | fix or drop the manifest entry; it is counted in attrition. |
| `deploy_ownership_key_rejected` | stack-pair config contains any deploy-ownership key by exact name (`compose_project`, `network`, `volume_path`, `volumes`, `image_tag`, `image`, `caddyfile`, `systemd_unit`, `db_volume`, `secret_rotation`) at root or under a stack entry | remove the key; that field is FIR23-STACK-owned — see the consumption table and [Key schema](#s1-executable-contracts-normative). |
| `cluster_gate_refused` | a leg has zero analyze successes, so the cluster phase is not entered | repair analyze failures on that leg (or accept the leg as failed); no cluster and no export run for the leg. |
| `max_differential_attrition_invalid` | stack-pair `max_differential_attrition` is outside closed range [0.0, 1.0] or non-numeric at load | set a float fraction in [0.0, 1.0]; see [floor policy](#floor-policy-normative). |
| `base_url_invalid` | stack `base_url` fails scheme/path/parse rules (scheme not `http`/`https`, path/query/fragment after normalize, or unparseable) | supply an absolute `http`/`https` URL with empty path or `/` only; trailing slash is normalized away. |
| `base_url_not_allowlisted` | stack `base_url` host is not in the consumption-table ingress identity (host-only, case-insensitive compare) | point `base_url` at a host named in the [FIR23-STACK consumption table](#fir23-stack-consumption-table-pinned). |
| `config_endpoint_invalid` | `primary_endpoint` is not the pinned primary string, or `secondary_endpoints` has duplicates / unknown ids / overlap with primary, or either key has the wrong type | set `primary_endpoint` to `detection_recall@frame_e2e/label_map_primary` and list only legal distinct secondaries; see [Key schema](#s1-executable-contracts-normative). |
| `export_media_not_in_roster` | an export row's media id is absent from that leg's `items.jsonl` roster | fail closed — the export surface returned a media id this leg never submitted; repair the export/ingest pairing, do not silently score the extra. |
| `accepted_set_below_floor` | `\|accepted_set\| < resolved_floor_count` after the floor is resolved to an item count (`resolved_floor_count = max(2, ceil(accepted_set_floor × N))` with `N = \|manifest entries\|` for a fractional floor, or the absolute int ≥ 2) | all P/R cells are **DIRECTIONAL** with this reason; report still emits metrics with the disclosure — expand the corpus or repair leg failures so the accepted set clears the floor. |
| `accepted_set_floor_exceeds_corpus` | integer `accepted_set_floor` > `\|manifest entries\|` at `run`/`score` after the manifest loads (form already passed `stack_pair`) | lower the absolute floor or enlarge the corpus; this is a config error, not a data property — fail closed before scoring. |
| `ci_half_width_above_precision_floor` | bootstrap CI half-width on Δ exceeds `head_to_head_delta / 2` for the cell | cell is **DIRECTIONAL** with this reason; the interval cannot resolve δ — enlarge the corpus, reduce between-leg noise, or accept a directional claim. |
| `detection_exhaustiveness_unasserted` | a detection endpoint cell whose corpus dropped any accepted entry from `detection_scoring_set` for unasserted exhaustiveness (box-less or incomplete `face_boxes`) | cell is **DIRECTIONAL** with this reason; load a corpus that passes `face_count == len(face_boxes)` (or set `require_detection_exhaustiveness=True` on the detection path) before treating the cell as headline-quotable. |
| `stack_media_id_missing` | analyze job payload is not an object, or has no integer `media_id` / `stack_media_id`; the join domain never echoes the manifest id | repair the analyze payload so it carries the stack's own media id; the item is recorded failed and does not enter the accepted set. |
| `provenance_sha_unavailable` | `init_run_dir` cannot resolve a git SHA for `scripts/bench` or `scripts/eval_harness` (no checkout, git missing, or empty `git log`) | run the CLI from a git checkout of the monorepo; packaged / tarball / CI-artifact trees cannot create a run-dir. |
| `join_row_missing` | a detection or identification metric row's path is absent from the manifest, or an accepted/detection population media_id has no metric row | fail closed — do not zero-pad a hole in the join; repair the export/manifest pairing and re-score. |
| `bootstrap_series_mismatch` | a named primary/secondary cell's paired bootstrap series is missing or length-mismatched across legs | both legs must emit the same scoring population for that cell; repair attrition/export so the paired series align. |
| `bootstrap_status` | per-cell stamp (`ok`, `partial`, or a fail-closed code such as `bootstrap_series_mismatch` / `not_computed`); `assign_tier` demotes CONFIRMATORY when the primary or a Holm-significant secondary is not `ok`. This is the **demotion reason** and the **cell field**, not a BenchError code. | inspect `bootstrap_n_used` vs `bootstrap_resamples`; a `partial` bootstrap (undefined micro-ratios treated as Δ = 0 over the B-draw space) cannot mint CONFIRMATORY. |
| `bootstrap_status_missing` | `assign_tier` raises when a named confirmatory-eligible cell's ctx omits the `bootstrap_status` key (malformed ctx; not a demoted-partial). Unreachable on the production score path, which stamps the key unconditionally. | repair the caller that built ctx; do not treat this code as a demotion reason. |
| `export_envelope_invalid` | a persisted export is not a **bare JSON array**, a dict export is missing the required `media_identities` / `clusters` key, or an array row is not an object. Object envelopes (`{"data": [...]}`) are rejected — there is no second accepted shape | persist the live-stack array as-is; do not wrap rows in a pagination object and do not drop non-object rows. |
| `preflight_missing` | `score` found a leg directory without `preflight.json` | re-run `preflight --config <stack-pair.yaml> --out <run-dir>`, or copy the PROV-01 artifact into each `legs/<stack_id>/`. |
| `preflight_invalid` | `score` found a `preflight.json` that is unreadable (including non-UTF-8 bytes), not a JSON object, or missing required PROV-01 keys. Score-time validation is **key-presence only** — values (null `opencv_major`, expected≠resolved) are not re-checked. `frames.json` stamps `preflight_present: true` to mean present-and-structurally-valid (`_require_prov01_preflights` returns True or raises). | rewrite the artifact from a successful `preflight --config <stack-pair.yaml> --out <run-dir>` (or copy a complete PROV-01 file into `legs/<stack_id>/`); an empty object is not sufficient. |
| `leg_outcome_unreadable` | `leg_outcome.json` exists but is unreadable or not JSON | delete or rewrite the latch; a torn file raises `leg_outcome_unreadable` and aborts the run — it is not treated as absence. |

**Provenance counters (not failure codes):** `degenerate_box_dropped` counts boxes whose clamped area is zero after the [localization pin](#b-constructing-metric-inputs) componentwise clamp; they are dropped from the assignment matrix and stamped in provenance. `zero_detection_media_count` counts accepted-set media whose export yielded zero face rows (roster-present, `pred_faces = 0`). `ingest_asymmetric_media` counts media present in one leg's `items.jsonl` but not the other (excluded from `accepted_set`). These counters are not stable error codes and do not abort the run.

Mock fixtures in tests must use these **real** payload shapes (not invented field names like top-level `pgvector_dimension` or `profile` outside `model_cache`).

---

## Feasible scoring scope

Public exports (media identities + cluster members) carry **bbox / cluster metadata only** — confirmed by `MediaIdentityService.list_by_media_ids` payload keys and `ClusterMemberResponse` (no embedding vector, no landmark coordinates on the public path).

**In scope for cross-stack scoring (Slice 2)**

- Map exports + GT → `face_metrics.ImageDetection` (**IoU-matched** detection P/R via `detection_pr` per the [localization pin](#b-constructing-metric-inputs); the count-only variant is retained as a DIAGNOSTIC companion, not as the metric).
- Map exports + GT + label-space mapping → `face_metrics.ImageIdentities` (named identification P/R via `identification_pr`).
- Dual sampling frames: FIR-5-native + end-to-end inclusive ([End-to-end scoring frames](#end-to-end-scoring-frames)).
- Dual label-mapping frames: primary string-match + disclosed optimistic Hungarian ([Ground truth & label mapping](#ground-truth--label-mapping)).

**Explicitly OUT OF SCOPE for the cross-stack path**

- FIR-5 **score-face / run-record** surfaces that assume full describe/analyze run records with embedding-bearing fields.
- **Clustering purity sweeps** and any metric that requires raw embedding vectors or landmarks.
- Inventing an admin/diagnostic export of embeddings from FIR-8.
- Treating raw predicted `cluster_label` strings as GT identity names without the label-space mapping step.

**OPTIONAL upstream ask** (separate service task, **not FIR-8**): an authenticated embedding-export diagnostic route (or opt-in debug field) for offline purity / embedding-space audits. Document the ask in the runbook residual section; do not block FIR-8 on it.

---

## Ground truth & label mapping

Scoring is invalid if predicted cluster labels are compared to GT as if they shared a name space. This section pins **where GT comes from**, **how metric inputs are built**, and **how cluster labels map into GT identity space**.

### (a) GT source + loader

| Pin | Value |
| --- | --- |
| **Schema** | **`manifest_version: 2` only.** FIR-8 loads via `load_manifest` against the v2 schema, full stop. `FaceBox` / `face_boxes` already exist on `GoldenEntry` under version 2 (verified); no alternate manifest schema and no exhaustiveness flag from another task are required or referenced by any FIR-8 path. |
| **Loader** | `scripts.eval_harness.manifest.load_manifest(path: str, images_dir: str \| None = None) -> GoldenManifest` |
| **Types** | `GoldenManifest` (`roster`, `entries`); `GoldenEntry` (`path`, `sha256`, `media_id`, `face_count`, `present_identities`, `face_boxes`, `policy`, …); `FaceBox` (`x`, `y`, `w`, `h`, `name: str \| None`, `source`) — normalized centre form, see [localization pin](#b-constructing-metric-inputs) |
| **Errors** | `ManifestError` on structural/hash/label failures (fail-closed, [rg-008]); FIR-8 additionally raises `gt_box_count_mismatch` only when `load_bench_manifest(..., require_detection_exhaustiveness=True)` and an entry has `face_count != len(face_boxes)` — see [Manifest load & detection exhaustiveness](#manifest-load--detection-exhaustiveness-no-fir-11-coupling) |
| **File pattern** | CLI `--manifest` accepts any path loadable by `load_manifest`. **Convention** for the Golden-150 face bench corpus: `benchmarks/manifests/golden150-*.json` (e.g. `golden150-draft-YYYYMMDD.json`). Smoke / identification fixtures may use `apps/prototype-description-service/scene/tests/seed/golden.json` (identification only — zero `face_boxes`; loads under `require_detection_exhaustiveness=False`). Detection tests use `scripts/bench/tests/fixtures/v2_boxed_detection.json` (literal required-field content under [Manifest load & detection exhaustiveness](#manifest-load--detection-exhaustiveness-no-fir-11-coupling); load with `require_detection_exhaustiveness=True`). |
| **In-tree status (plan-author check)** | `benchmarks/manifests/golden150-draft-20260723.json` is **not** present in this checkout; operators (or VLM-6 curation) supply the curated Golden-150 path. Do not invent a vendored 150-entry file in FIR-8. |
| **Content hash pin** | At `run` start, write `manifest.sha` = sha256 of the manifest file bytes. Optional stack-pair / run config key `manifest_sha256` fails closed if it mismatches the loaded file. Score path re-reads the hash for provenance. |
| **Image bytes root** | `--images-dir` (or config `images_dir`) is the local corpus root; when set, `load_manifest(..., images_dir=...)` verifies per-entry `sha256` against files under that root (same as harness). |

CLI (illustration of required flags, not a full copy-paste invocation): `run --manifest <path> --images-dir <root>` (both required for production head-to-head; tests may inject a synthetic `GoldenManifest` without disk images).

### Manifest load & detection exhaustiveness (no FIR-11 coupling)

FIR-8 loads via `load_manifest` against the v2 schema, full stop. Verified against the current harness: `SUPPORTED_MANIFEST_VERSION = 2`, `GoldenEntry.face_boxes` already exists, `ConfigDict(extra="forbid")` rejects unknown fields, and there is no `load_legacy_manifest` symbol. No FIR-8 step calls a symbol or fixture that FIR-11 has not yet created.

**Exhaustiveness is FIR-8's own local gate**, not an inherited manifest flag and not gated on FIR-11. It is controlled by one parameter on one function:

- `load_bench_manifest(path, images_dir, require_detection_exhaustiveness: bool = False) -> GoldenManifest`
- **`require_detection_exhaustiveness=False` (default; identification path, including `scene/tests/seed/golden.json`)**: an entry with `face_count != len(face_boxes)` (or empty `face_boxes` while `face_count > 0`) **loads normally** and is marked **non-exhaustive**, which removes it from `detection_scoring_set`. **No error.**
- **`require_detection_exhaustiveness=True` (detection fixture path and any detection-scoring load)**: the same condition **fails closed** with `gt_box_count_mismatch`. The detection fixture `scripts/bench/tests/fixtures/v2_boxed_detection.json` is loaded under this flag.

There is exactly one rule, stated here; other sections point here rather than restating a second outcome.

| Corpus | `stranger_faces` | Detection FP / ID-precision claims |
| --- | --- | --- |
| **Entry that is exhaustive** (`face_count == len(face_boxes)`, boxes present; under either flag value when the equality holds) | derived: count of `face_boxes` with `name is None` | **CONFIRMATORY-eligible** (subject to the rest of the tier table) — every face in frame has a box, so an unmatched predicted box is a real FP; entry is in `detection_scoring_set` |
| **Non-exhaustive entry under default flag** (`require_detection_exhaustiveness=False`; no `face_boxes`, or `face_count != len(face_boxes)`) | **not derived — `0`** | entry leaves `detection_scoring_set` entirely (counted, printed exclusion); a detection endpoint cell whose corpus dropped any accepted entry for unasserted exhaustiveness is **DIRECTIONAL** with reason `detection_exhaustiveness_unasserted` — directionally usable, not headline-quotable; DIAGNOSTIC is reserved for cells that fail a hard precondition. Under `require_detection_exhaustiveness=True` this row does not apply: the load raises `gt_box_count_mismatch` instead (see the flag rule above). |

The retired arithmetic was `stranger_faces ← max(0, face_count − len(present_identities))`. It manufactures a stranger count out of a roster gap. **No module under `scripts/bench/` derives a face count by subtracting `len(present_identities)` from `face_count`.** When exhaustiveness holds, `stranger_faces` comes from the boxes (`name is None`); otherwise it does not come at all.

- **Known divergence (read-not-edited harness path):** `scripts/eval_harness/report.py:454-461` retains the legacy subtraction `stranger_faces = max(face_count - len(entry["present_identities"]), 0)` and the `labeled_faces=face_count` denominator; it serves the existing eval-harness report path and is out of scope for FIR-8. Figures produced by that path are not comparable to FIR-8 detection figures, which use the pinned `len(face_boxes)` denominator.

**FIR-11 Slice 2 is not a dependency of any FIR-8 S1/S2 code path or fixture.** It remains relevant only as a later source of a larger boxed production corpus. Until a production corpus carries complete `face_boxes`, detection unit tests run against `v2_boxed_detection.json`, and a production run without complete boxes is a **DIRECTIONAL** orchestration dry run (reason `detection_exhaustiveness_unasserted`) — real value, executable today, not a head-to-head gate number. `score` prints whether the loaded corpus passed the exhaustiveness assertion and the resulting eligibility ceiling in the provenance block.

**`v2_boxed_detection.json` fixture content (literal; loads under `GoldenManifest` / `GoldenEntry` / `FaceBox` with `extra="forbid"`).** Required fields: `GoldenManifest` — `manifest_version`, `roster`, `entries` (`roster_cohorts` optional, default `{}`); `GoldenEntry` — `path`, `sha256`, `media_id`, `face_count`, `present_identities`, `must_right`, `easy_wrong`, `policy` (`recognition_enabled`), and `base_caption` (key required on every v2 entry; empty string allowed); `FaceBox` — `x`, `y`, `w`, `h`, `source` (`name` optional). Models: `scripts/eval_harness/manifest.py` `FaceBox` L318-335, `GoldenEntry` L337-393, `GoldenManifest` L396-420. Localization-proof geometry (shared with the [TEST-15] pin): GT centre box `x=0.5, y=0.5, w=0.2, h=0.2` on a 1000×1000 image space.

```json
{
  "manifest_version": 2,
  "roster": ["Alice Q", "Bob Z"],
  "entries": [
    {
      "path": "fixtures/multi_face.jpg",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "media_id": 1,
      "face_count": 2,
      "present_identities": ["Alice Q", "Bob Z"],
      "base_caption": "",
      "must_right": [],
      "easy_wrong": [],
      "policy": {"recognition_enabled": true},
      "face_boxes": [
        {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2, "name": "Alice Q", "source": "iptc"},
        {"x": 0.25, "y": 0.3, "w": 0.15, "h": 0.15, "name": "Bob Z", "source": "iptc"}
      ]
    },
    {
      "path": "fixtures/zero_face.jpg",
      "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "media_id": 2,
      "face_count": 0,
      "present_identities": [],
      "base_caption": "",
      "must_right": [],
      "easy_wrong": [],
      "policy": {"recognition_enabled": true},
      "face_boxes": []
    },
    {
      "path": "fixtures/count_mismatch.jpg",
      "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "media_id": 3,
      "face_count": 2,
      "present_identities": ["Alice Q"],
      "base_caption": "",
      "must_right": [],
      "easy_wrong": [],
      "policy": {"recognition_enabled": true},
      "face_boxes": [
        {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2, "name": "Alice Q", "source": "iptc"}
      ]
    }
  ]
}
```

Entry `media_id: 1` is exhaustive multi-face (localization-proof GT geometry on the first box). Entry `media_id: 2` is exhaustive zero-face (`face_count: 0`, `face_boxes: []`). Entry `media_id: 3` trips `gt_box_count_mismatch` under `require_detection_exhaustiveness=True` (`face_count: 2` vs one box).

### (b) Constructing metric inputs

Frame construction happens **entirely in `scripts/bench`** (`export_map.py` / `score_report.py`). FIR-5 `detection_pr` / `identification_pr` remain pure functions of the rows the adapter builds; `identification_pr` is **unmodified**, while `detection_pr` and `ImageDetection` take the one scoped additive change described in the [localization pin](#b-constructing-metric-inputs) below. Nothing in this plan describes `face_metrics.py` as untouched.

| Side | Source | Fields used for FIR-5 rows |
| --- | --- | --- |
| **GT (labeled)** | Manifest entry | `ImageDetection.labeled_faces` ← **`len(entry.face_boxes)`** (single pinned rule — see the denominator pin below; detection rows built only for entries in `detection_scoring_set`); `ImageIdentities.labeled` ← `entry.present_identities` (roster names; identification rows over `accepted_set`); `recognition_enabled` ← `entry.policy.recognition_enabled`; `stranger_faces` ← per [manifest load & detection exhaustiveness](#manifest-load--detection-exhaustiveness-no-fir-11-coupling) (boxes with `name is None` when exhaustiveness holds; otherwise `0` and the entry is outside `detection_scoring_set`) |
| **Predicted** | Per-leg public exports under `legs/<stack_id>/exports/` | `ImageDetection.pred_faces` ← count of exported face rows for that media; **`ImageDetection.matched_faces` ← count of IoU-matched pairs** (see localization pin below); `ImageIdentities.predicted` ← **mapped** identity names (never raw unmapped cluster ids as if they were GT names) |
| **Image key** | Join key | Stable string: manifest `path` or `str(entry.media_id)` — same `image` field on both `ImageDetection` and `ImageIdentities` for a media unit |

Detection P/R does not require identity name mapping. Identification P/R **requires** [label-space mapping](#c-label-space-mapping) before filling `predicted`.

**Denominator pin (one rule, not two).** An earlier revision wrote `labeled_faces ← entry.face_count` *"or `len(entry.face_boxes)` when boxes are complete and preferred"* — inside a table this plan labels **normative**. Two denominators yield two different detection P/R values for the same run with no rule selecting between them, which is the same post-hoc-selection defect as the unpinned sampling frame above. `len(entry.face_boxes)` is the pin, for one reason: the localization pin below requires per-box GT geometry anyway, so a `face_count` that disagrees with the box list would mean the metric's denominator and its matching evidence disagree. Consequences are explicit rather than tolerated:

- `face_count != len(face_boxes)` → outcome is gated solely by `require_detection_exhaustiveness` on `load_bench_manifest` (see [Manifest load & detection exhaustiveness](#manifest-load--detection-exhaustiveness-no-fir-11-coupling)): default `False` → load and mark non-exhaustive (leaves `detection_scoring_set`); `True` → **fail closed** (`gt_box_count_mismatch`). The denominator pin and the localization pin both require per-box GT geometry on detection-scoring rows; a `face_count` that disagrees with the box list must not silently enter that set.
- **`scene/tests/seed/golden.json` is not a detection fixture.** It has **37 entries, all 37 carrying `face_count` (35 with a non-zero value), and zero carrying `face_boxes`**. It loads under the default `require_detection_exhaustiveness=False` and is unaffected by the gate. It is a valid identification-frame smoke fixture, but under the box-based denominator every entry is box-less, so it cannot serve detection tests. Slice 2's detection tests therefore require the purpose-built **`v2_boxed_detection.json`** fixture, loaded with `require_detection_exhaustiveness=True`, authored in `scripts/bench/tests/fixtures/`, and the localization red-proof is written against that fixture.
- An entry with **zero** `face_boxes` cannot be scored for detection at all: it is excluded from `detection_scoring_set` (and therefore from every detection frame) with a counted, printed exclusion — the same treatment the optimistic label rule already gives box-less entries. It stays in `accepted_set` and in the identification frames.

**Localization pin ([TEST-15]).** Detection P/R was cardinality-only: `labeled_faces` from a count and `pred_faces` from `len(exported rows)`, fed to `detection_pr`, whose per-image arithmetic is `TP = min(pred, labeled)`. A detector emitting the **right number of boxes in entirely the wrong places scores perfect detection P/R** — precisely the plausible-wrong-implementation-still-passes pattern, and it is the metric the whole head-to-head rests on. The signal was available and discarded: exports carry `bbox` geometry, GT carries `face_boxes`, and matching uses the existing `IOU_MATCH_THRESHOLD` (0.5) at `scripts/eval_harness/face_assignment.py:29` (already the default of the assignment function at line 136 and already exported in `__all__` at line 908) — on both the detection pin and the optimistic label map. Do **not** declare a second constant for the same quantity.

- **Coordinate convention (pinned before any IoU is computed).** Canonical scoring space is **normalized top-left** boxes in 0..1. The two input sides use different encodings, units, **and key names**; both convert into that space before IoU. **Key-set distinction (one sentence):** ground-truth `FaceBox` uses `{x, y, w, h}`; prediction export `bbox` uses `{x, y, width, height}` — never `w`/`h` on the prediction side.
  - **Ground truth** (`FaceBox` on the manifest): normalized **centre** form `(x, y)` plus size `(w, h)` in 0..1. Convert to scoring space with `x1 = x − w/2`, `y1 = y − h/2`, keeping `w`, `h`. Centre-form is the expected GT encoding — it is **not** a convention error.
  - **Prediction** (detector / export `bbox`): absolute-pixel top-left integers under keys `x`, `y`, `width`, `height` (public envelope built at `recognition/interface_adapters/http/deps/stores.py:220-235`; pixel values written at `recognition/application/scan/service.py:517-520` as `int(det.bbox[2] - det.bbox[0])` etc.). Convert with `x1 = x / image_width`, `y1 = y / image_height`, `w = width / image_width`, `h = height / image_height`. Therefore `items.jsonl` **must** persist `image_width` and `image_height` (positive ints produced at ingest by decoding each image once with Pillow in `scripts/bench/corpus.py` `ItemOutcomeStore` — the ingest path otherwise passes bytes opaquely and does **not** already know dimensions). Scoring must **not** need filesystem access to the images.
  - After both sides are in scoring space, the adapter forms `(x1, y1, x2, y2) = (x1, y1, x1 + w, y1 + h)`. **After conversion, every box is clamped componentwise to [0, 1] — x1 and y1 to [0, 1], and x2 = x1 + w and y2 = y1 + h to [0, 1] — before any IoU is computed. Clamping applies identically to ground-truth and prediction boxes. A box whose clamped area is zero is dropped from the assignment matrix and counted as `degenerate_box_dropped` in provenance.** (A detector box may extend past the image edge; the same clamp applies.) IoU is then `|∩| / |∪|` on the clamped rectangles.
  - It **fails closed** with **disjoint** codes: `box_convention_unknown` when a prediction `bbox` object's key set is not exactly `{x, y, width, height}` (set comparison — any unrecognised shape trips it, including corner-form, renamed keys, or extra keys); `image_dimensions_missing` when a record whose prediction boxes require conversion has `image_width` or `image_height` absent, non-integer, or ≤ 0. Ground-truth centre-form boxes with `{x, y, w, h}` are the expected GT inputs and do **not** trip `box_convention_unknown`. An IoU computed across two different conventions silently reads ≈ 0 on every pair, which would make the matched cell collapse for reasons that have nothing to do with detector quality — indistinguishable from the very failure the pin exists to detect.
- The adapter computes an **optimal one-to-one assignment (Hungarian)** over the IoU matrix at `IOU_MATCH_THRESHOLD` (0.5) from `scripts/eval_harness/face_assignment.py:29`, discards assigned pairs below that threshold, and reports `matched_faces` per image. **Hungarian, not greedy:** greedy-by-descending-IoU is not optimal (it can strand a GT box whose only above-threshold partner was consumed by a higher-scoring pair) and, more decisively, the [optimistic label rule](#c-label-space-mapping) already specifies Hungarian — two different matching algorithms on the same box geometry in the same plan is the "two denominators" defect in another costume. Assignment is `scipy.optimize.linear_sum_assignment` on the cost matrix `-IoU`, matching the existing implementation at `scripts/eval_harness/face_assignment.py:188-196`. The solver is deterministic for a fixed cost matrix, and the cost matrix is fixed because both axes have a pinned order: ground-truth boxes in manifest `face_boxes` order, predictions in export order sorted by ascending `identity_id`. The selected assignment is therefore reproducible across runs. It is NOT claimed to be unique: an IoU matrix with tied optima admits several assignments of equal total cost, and which one the solver returns is an implementation detail of SciPy pinned by the lockfile. Every such assignment yields the same matched-pair count, so `matched_faces` is invariant under the tie even though the pairing is not.
- `detection_pr` as it stands **cannot express this** — `ImageDetection` has no TP slot, so a single mislocalized box (1 pred, 1 GT, 0 matched) is scored `TP = min(1,1) = 1`. This is a real expressiveness gap in the shared metric, not a FIR-8 inconvenience, so it is fixed **upstream once**: add `matched_faces: int | None = None` to `ImageDetection`, and in `detection_pr` use `TP = matched`, `FP = max(pred − matched, 0)`, `FN = max(labeled − matched, 0)` when it is present — **the same clamps the existing count-only branch already applies** (`fp += max(pred − labeled, 0)`, `fn += max(labeled − pred, 0)`). v6.3 wrote the three terms unclamped, which lets a bad `matched_faces` drive FP or FN negative and *inflate* precision or recall past 1.0 — a metric that can exceed its own bound is worse than the gap it was replacing.
- **Validate `matched_faces` at construction, fail closed.** `0 ≤ matched_faces ≤ min(pred_faces, labeled_faces)` is a hard invariant, checked in `detection_pr` when the field is present and raising `ValueError` (`matched_faces_out_of_bounds`) rather than clamping silently. Clamps defend the arithmetic; the bounds check defends against the adapter shipping a matcher bug into a gate number. Both are required — a clamp alone turns an out-of-range matcher into a plausible-looking metric, which is exactly [TEST-15]'s failure mode.
- Omitted → **numerically identical** `detection_pr` output on every existing input, and source-compatible for both positional and keyword construction of the frozen dataclass. It is **not** *byte-identical*, and the plan should not claim so: a trailing field changes `dataclasses.fields()` arity, `astuple()` length, `repr()`, `__match_args__`, and the pickle payload. A consumer that unpacks `astuple()` into a fixed-arity target, pattern-matches positionally, or compares `repr` strings would observe it. That is precisely why the [consumer inventory](#dual-frame-adapter-contract-fir-5-signatures-pinned) exists and why the field is **optional with a default, added last** — so keyword construction and the `None` path stay numerically identical without a before/after golden. This is the "documented gap fixed upstream with rationale" the [Contract and Boundary Impact](#contract-and-boundary-impact) table already permits, and it supersedes the blanket *do not modify* note in the [dual-frame contract](#dual-frame-adapter-contract-fir-5-signatures-pinned).
- **Match-predicate rule (not a coordinate-encoding rule): no centre-in-box FALLBACK for detection matching.** The coordinate convention above *accepts* centre-form GT boxes as inputs and converts them into scoring space; that is unrelated to whether a *match* may be awarded when a prediction's centre merely lies inside a GT box. The [optimistic label rule](#c-label-space-mapping) admits a centre-in-box match when GT boxes lack size parity; detection matching does **not**, at the same `IOU_MATCH_THRESHOLD` (0.5) from `face_assignment.py:29`. Detection P/R exists *to measure localization*, so admitting a localization-tolerant match predicate into it would restore exactly the mislocalization blindness this pin was written to remove — a box centred on the right face but sized wrong would score as matched. The label map has the opposite job (recover *identity* despite imperfect geometry), so tolerance there costs nothing it is measuring, and it is already disclosed DIRECTIONAL. Consequence, stated so no one cross-quotes the two: the optimistic frame's match count is computed under a looser predicate than `matched_faces` and **the report must never compare them or reuse one as the other**.
- **Count-only detection P/R is retained as a DIAGNOSTIC cell**, printed beside the matched cell. The gap between them *is* the localization-quality signal, and on a cross-stack comparison between two different detectors it is one of the more interesting numbers in the report.
- **Discrimination red-proof (mandatory, [TEST-15])**: pin exact geometry so a quarter-width shift cannot still clear `IOU_MATCH_THRESHOLD` (0.5). Shared image space: `image_width = 1000`, `image_height = 1000`. Ground truth `FaceBox` (normalized centre form): `x = 0.5`, `y = 0.5`, `w = 0.2`, `h = 0.2` → converted top-left `(0.4, 0.4)` with size `(0.2, 0.2)`, spanning x in `[0.4, 0.6]`.
  - **GREEN (match):** prediction bbox `{x: 400, y: 400, width: 200, height: 200}` → normalized `(0.4, 0.4, 0.2, 0.2)` → IoU = 1.0 ≥ 0.5 → matched, `matched_faces = 1`. Count-only cell also perfect.
  - **RED (miss, translation):** prediction bbox `{x: 700, y: 400, width: 200, height: 200}` → normalized `(0.7, 0.4, 0.2, 0.2)`, spanning x in `[0.7, 0.9]`. x-overlap with `[0.4, 0.6]` is empty → intersection area 0 → IoU = 0.0 < 0.5 → unmatched, `matched_faces = 0`; the entry contributes one false positive and one false negative. Count-only cell still reads perfect P/R (`TP = min(1, 1) = 1`).
  - **RED (miss, centre-in-box / containment):** same GT top-left `(0.4, 0.4)` size `(0.2, 0.2)` — centre at `(0.5, 0.5)`. Prediction on 1000×1000: `{x: 100, y: 100, width: 800, height: 800}` → normalized `(0.1, 0.1)` size `(0.8, 0.8)`. The GT centre `(0.5, 0.5)` lies inside the prediction and the GT box is entirely contained in it, so any centre-in-box or containment predicate **matches**; IoU = `0.04 / 0.64 = 0.0625` < `IOU_MATCH_THRESHOLD` (0.5), so the pinned IoU predicate must **not** match: `matched_faces = 0`. This case separates an IoU predicate from a centre-in-box or containment predicate, which the translation case cannot.
  - **[TEST-15] single-line flip that turns the RED case green:** dropping the divide-by-`image_width` normalization on the prediction side leaves the translation RED prediction at `(700, 400)` in a 0..1 space and is still non-matching — so that omission alone does not flip RED. The sharper conversion bug — swapping the centre-to-top-left conversion for an identity mapping on the ground-truth side — moves GT to span `[0.5, 0.7]` and is the conversion defect the GREEN assertion fails on (`IoU` with the GREEN prediction falls below 0.5). The named single-line change that **flips the translation RED miss assertion** (matched cell becomes perfect while count is preserved) is **removing the IoU threshold and awarding the match by count alone** (`TP = min(pred, labeled)`): under that change translation RED yields `matched_faces = 1` and the test fails. The named change that **flips the centre-in-box RED** is awarding a match when the GT centre lies inside the prediction (or when the GT box is contained), without requiring IoU ≥ 0.5.

### (c) Label-space mapping

Predicted `cluster_label` values are **cluster-scoped** (stack-local cluster ids / operator labels), not automatically GT roster names. Never pass raw `cluster_label` into `ImageIdentities.predicted` without mapping.

**Normalization** (shared by both rules): Unicode NFC, strip, collapse internal whitespace, casefold.

| Rule | When | How | Report frame |
| --- | --- | --- | --- |
| **Primary — string match (pinned primary)** | Cluster has an operator-assigned label (`is_auto_label == false` **or** non-empty human `cluster_label` that is not a pure auto id) | Map predicted label → GT name if normalized strings equal a roster / `present_identities` name; else unmapped (omit from `predicted` for primary frame; count under unmapped-cluster DIAGNOSTIC stats) | `label_map_primary` — **default** for CONFIRMATORY identification cells |
| **Optimistic — Hungarian (disclosed)** | Unlabeled / auto-labeled clusters (`is_auto_label == true` or empty label) **or** residual after primary | Optimal one-to-one assignment (Hungarian) maximizing **overlap counts** between cluster member boxes and GT `face_boxes` (IoU ≥ `IOU_MATCH_THRESHOLD` (0.5) from `face_assignment.py:29`, or centre-in-box fallback when GT boxes lack size parity — a *match-predicate* tolerance, not a coordinate-encoding rule). **Labeled-wins:** a pred that already has a primary name is excluded from the assignment matrix on both the native per-pred path and the e2e media-level path — geometry must not union a second GT name onto that pred. One pred claims at most one GT; the e2e name list is deduped. Assigned GT names fill `predicted` for this frame only. Entries with **no `face_boxes`** are ineligible for the optimistic rule — their unlabeled clusters stay unmapped (DIAGNOSTIC) and the report states the count of box-less entries so an empty optimistic frame is legible, not silent. | `label_map_optimistic` — always **DIRECTIONAL**; never CONFIRMATORY |

**Disclosure (mandatory in report)**: primary and optimistic frames print side-by-side for identification; optimistic cells carry tier `DIRECTIONAL` and a one-line note that assignment is overlap-optimal, not operator-confirmed. Unmapped residual clusters after both rules are DIAGNOSTIC counts only.

### (d) Media identity join

Manifest `media_id` (synthetic golden id) ≠ stack `media_id` (per-tenant DB id after analyze). Join is **only** via the per-item outcome record:

```text
legs/<stack_id>/items.jsonl  # one JSON object per line, append-only
{
  "manifest_media_id": 12,          # GoldenEntry.media_id
  "manifest_path": "…",             # GoldenEntry.path
  "content_sha256": "…",            # GoldenEntry.sha256 when verified
  "stack_media_id": 42,             # CLIENT-SUPPLIED media id (int) used in the image_<media_id> multipart part name (analyze returns only a job id; media_identities export rows echo this id as int)
  "image_width": 1920,              # positive int; Pillow-decoded at ingest by ItemOutcomeStore after ImageOps.exif_transpose (required for prediction-box conversion)
  "image_height": 1080,             # positive int; same producer; missing/non-int/≤0 → image_dimensions_missing at items.jsonl load
  "phase": "ingest|analyze|…",
  "outcome": "ok|failed",
  "error_code": null,
  "attempt": 1
}
```

Score path: for each accepted-set item, resolve `stack_media_id` (int) per leg from that leg's `items.jsonl`, then select export rows whose `media_id` (int) equals it — **both sides are ints; there is no string coercion**. A client-supplied `stack_media_id` is always an int on an analyze-success record — missing/null is not a defined state.

**`items.jsonl` is the authoritative roster of media ids submitted for this leg.** The public export is a batched opaque GET returning identity rows (`remote_client.py:212-218`) — a media id with zero detections contributes no row, which is byte-for-byte the same observation as a media id that was never processed. Resolve the distinction from the ingest side:

- A media id **present in `items.jsonl`** with **zero export rows** is **ZERO DETECTIONS**. It is accepted (subject to conditions (i) and (ii) on both legs) and contributes `pred_faces = 0`. Stamped in score provenance as `zero_detection_media_count`.
- A media id **present in `items.jsonl` for one leg but not the other** is an **INGEST ASYMMETRY**. It fails the both-legs condition, is excluded from `accepted_set`, and is counted in provenance as `ingest_asymmetric_media`.
- An **export row whose media id is absent from `items.jsonl`** is a **contract violation**, not a silent extra: fail closed with `export_media_not_in_roster`.

---

## End-to-end scoring frames

FIR-5 pure functions score **only the rows they are given** — they do not themselves inject detector-miss cascade or label mapping. The adapter in `scripts/bench` owns cascade honesty and label-space mapping; FIR-5's **frame semantics** are unchanged, and its code changes only by the additive `matched_faces` field pinned in the [localization pin](#b-constructing-metric-inputs).

### Dual-frame adapter contract (FIR-5 signatures pinned)

Verified in `apps/prototype-description-service/scripts/eval_harness/face_metrics.py`:

```python
@dataclass(frozen=True)
class ImageDetection:
    image: str
    pred_faces: int
    labeled_faces: int
    matched_faces: int | None = None   # ADDED by this task — see localization pin

@dataclass(frozen=True)
class ImageIdentities:
    image: str
    predicted: Sequence[str]       # mapped GT-space names only
    labeled: Sequence[str]         # from manifest present_identities
    recognition_enabled: bool = True
    stranger_faces: int = 0

def detection_pr(items: Sequence[ImageDetection]) -> PrResult: ...
def identification_pr(items: Sequence[ImageIdentities]) -> PrResult: ...
```

- **Construction site**: `export_map.to_face_metric_inputs(..., frame: Literal["native", "e2e"])` / `score_report.build_dual_frames(...)` only. Two calls, one per frame; no single call serves both.
- **Call sites**: `detection_pr(seq_of_ImageDetection)`, `identification_pr(seq_of_ImageIdentities)` — no other FIR-5 face scorer on the cross-stack path.
- **One scoped exception to "do not modify `face_metrics.py`"**: the optional `ImageDetection.matched_faces` field plus its branch in `detection_pr`, per the [localization pin](#b-constructing-metric-inputs). No existing signature changes and the field defaults to `None`. Rationale: the alternative — a bench-local localization scorer — is exactly the "parallel scorer" the [Constraints](#constraints) forbid, and it would leave the shared metric blind to localization for every other consumer. Extend the shared metric once; do not fork it and do not shadow it.
- **Consumer inventory (complete, verified 2026-07-29).** Exactly three files reference `ImageDetection` anywhere in the repo: `scripts/eval_harness/face_metrics.py` (the definition), `scripts/eval_harness/report.py`, and `scene/tests/test_eval_harness_face_metrics.py`. **`report.py` is a second existing consumer** — it imports `ImageDetection` (L47) and `detection_pr` (L51), constructs rows at L457, and calls `detection_pr` at L519. v6.3 asserted `face_metrics.py` was the "only edit outside `scripts/bench/`" while leaving this consumer uninventoried, which is precisely the boundary-blindness [rg-015] forbids. `report.py` needs **no code change** — it never sets `matched_faces`, so it takes the `None` path and its numbers are **numerically identical** (not byte-identical at the dataclass level). **`report.py` is READ, NOT EDITED.** Expressible proofs live in `apps/prototype-description-service/scene/tests/test_eval_harness_face_metrics.py`: (1) a **parametrized bounds table** — five cases, not a single in-range smoke; (2) the new field is **OPTIONAL with a default**, added **last**, because any consumer constructing the dataclass positionally would be a breaking change. A before/after `report.py` golden is **not** expressible (one test tree only ever contains the after-state) and is not required.

  **`matched_faces` bounds cases (parametrized; `pred = 3`, `labeled = 2` except where noted):**

  | # | `matched_faces` | Outcome | Expected FP | Expected FN |
  | --- | --- | --- | --- | --- |
  | (i) | `0` | accepted | `FP = 3` | `FN = 2` — neither negative |
  | (ii) | `2` | accepted at the **upper bound** (`matched == min(pred, labeled)`) | `FP = 1` | `FN = 0` — **load-bearing**: an implementation using `<` instead of `<=` fails only here |
  | (iii) | `3` | rejected, `matched_faces_out_of_bounds` (exceeds `labeled`, the smaller of the two) | n/a | n/a |
  | (iv) | `-1` | rejected, `matched_faces_out_of_bounds` | n/a | n/a |
  | (v) | omitted entirely | accepted; falls through to the existing count-only branch — the new field is optional-last and does not change the legacy result | count-only: `FP = max(3 − 2, 0) = 1` | count-only: `FN = max(2 − 3, 0) = 0` |

  Cases (i) and (ii) also prove FP and FN cannot go negative under a legal `matched_faces`.
- **Ownership.** `scripts/eval_harness/face_metrics.py` is FIR-5-owned shared offline-harness code. This task edits it under the documented-gap exception above; the FIR-5 owner is named in the Slice 2 checklist as a required reviewer on that one file, and the change does not land without that review.
- Everything else in this task remains a pure consumer.

**Adapter construction (normative)**

1. Join accepted-set media via [media identity join](#d-media-identity-join); load GT from the pinned manifest; load predicted rows from `legs/<stack_id>/exports/`.
2. Apply [label-space mapping](#c-label-space-mapping) → primary and (separately) optimistic predicted name lists.
3. Call `to_face_metric_inputs(..., frame="native")` and `to_face_metric_inputs(..., frame="e2e")` — **two calls, one per frame**. Report keys: `frame_fir5_native` (`frame="native"`) and `frame_e2e` (`frame="e2e"`).
4. **DETECTION rows are identical across frames** — built once from the join, unmodified. With the localization pin in force, `FN = max(labeled_faces − matched_faces, 0)` already charges every labeled GT box that no predicted box matched — a detector miss and a mislocalized box are both unmatched GT, and both land in FN by construction. v6.3 said to inject "`ImageDetection` undershoot" FN rows *in addition*, which **double-counts every missed face**. The "built once, from the join, unmodified" rule applies to **detection rows only**.
5. **IDENTIFICATION rows differ by `frame`:**
   - **`native`**: identification rows are derived from the **accepted set**, with detection counts taken from the export — a media id with no export rows contributes a **zero-detection row**, it is not absent from the frame. On that accepted-set population, `native` scores only faces the detector proposed, so a ground-truth name with no proposed face is absent from both the labeled and predicted vectors (excludes pure detector misses from identification accounting by construction).
   - **`e2e`**: also derived from the **accepted set** (same media population as `native`); scores the full ground-truth roster, so a ground-truth name with no predicted counterpart counts as a false negative — detector miss → identification miss ([EVAL-16]), whether lost at detection, clustering, or label mapping. A media id with no export rows still contributes a zero-detection row (`pred_faces = 0`), not an absent media id.
6. **Consequence:** `e2e` recall is ≤ `native` recall by construction, and the gap is exactly the detector-miss mass, so reporting only `native` would understate end-to-end error.
7. **Primary endpoint frame:** the single pre-declared primary endpoint uses **`e2e`** — it is the frame that cannot be gamed by a detector that proposes fewer faces.
8. Head-to-head report prints sampling frames **and** label-mapping frames as a grid per leg; never silently replace one with another.

**Unit test (required)**:
- **Partial miss:** synthetic corpus where one labeled face is absent from export → `frame_e2e` identification FN increments and detection FN increments; `frame_fir5_native` identification denominator does not charge that miss the same way (pins detector-miss→ID-miss accounting).
- **Whole-image zero-detection:** an accepted media id with **zero export rows** and one labeled face remains in the recall denominator on **both** frames, contributing `pred_faces = 0` and one false negative — it is a zero-detection row, not an absent media id (same join distinction as [media identity join](#d-media-identity-join) / [EVAL-19](#eval-19-operationalized-accepted-set)).

Constants live in `score_report.py` (or `export_map.py`): `SAMPLING_FRAME_CROSSBENCH_NATIVE`, `SAMPLING_FRAME_E2E`, `LABEL_MAP_PRIMARY`, `LABEL_MAP_OPTIMISTIC` — plan-level names; not FIR-5 library enums. Do NOT import `face_metrics.SAMPLING_FRAME_FACE_ID` on the cross-stack path — that existing FIR-5 constant names the pooled k-fold face-level frame, which is out of scope here.

---

## Tier vocabulary

The three-tier report label set **`CONFIRMATORY` / `DIRECTIONAL` / `DIAGNOSTIC`** is a **new crossbench report enum** defined in `score_report.py` as `CrossbenchTier`, sourced from QA-digest / canon convention for head-to-head bench claims. It is **not** a FIR-5 enum and must not be attributed to FIR-5 modules.

Separately: FIR-5 / eval harness surfaces carry **per-metric DIRECTIONAL disclosure qualifiers** in the QA/canon sense (e.g. underpowered slices report directional-only and cannot enter a gate decision — see commercial-face-identity scope language) plus harness **`provider_disclosure`** stamps on describe responses. Those are **not** the three-tier crossbench enum. Crossbench reports may *reference* FIR-5 directional disclosure text when a leg is underpowered, but the tier stamp itself is owned by `score_report.py`.

### CrossbenchTier semantics (normative)

| Tier | Meaning |
| --- | --- |
| **CONFIRMATORY** | Full-corpus fixed-denominator metric over the pinned **accepted set**, both legs' clustering complete (`cluster_job.json` success), **primary** label-mapping only, accepted-set size ≥ the [floor](#floor-policy-normative), the cell **pre-declared** as `primary_endpoint` or in `secondary_endpoints`, **and the [precision precondition](#precision-precondition-normative) satisfied for the cell's own δ** (Holm-adjusted for secondaries). Eligible for gate-style claims. |
| **DIRECTIONAL** | Any cell whose denominator lost items below the pre-stated floor (`|accepted_set| < resolved_floor_count`, reason `accepted_set_below_floor`) — accepted-set shrinkage has **two** distinct causes, both of which count toward the floor comparison: **ingest/analyze failures** (conditions (i)/(ii)) and **join-phase attrition** (condition (iii) / roster membership, including `ingest_asymmetric_media` and other join-side losses) — **or** any cell using the **optimistic** label-mapping frame, **or** any cell that fails the precision precondition (reason `ci_half_width_above_precision_floor` when half-width fails), **or** any cell not on the pinned primary sampling frame, **or** any detection endpoint cell whose corpus dropped accepted entries for unasserted exhaustiveness (reason `detection_exhaustiveness_unasserted`). Not gate-eligible. Provenance stamps the two causes separately as `attrition_ingest_analyze` and `attrition_join`. |
| **DIAGNOSTIC** | Context cells that fail a hard precondition or are non-claim surfaces: per-stack raw face/cluster counts, unmapped-cluster stats, attrition-by-phase tables, ingest asymmetries / roster exclusions, license banner echo — plus **any cell absent from both `primary_endpoint` and `secondary_endpoints`**, which can never be promoted. Never used as a quality gate. Exhaustiveness-unasserted detection claims are **DIRECTIONAL**, not DIAGNOSTIC. |

### Precision precondition (normative)

Size is not precision. An earlier revision made a cell CONFIRMATORY on accepted-set **size** alone and declared it gate-eligible, while the plan contained no variance or interval concept anywhere — so a two-point P/R gap between legs on ~150 images would have been stamped gate-eligible. That contradicts the sibling discipline this programme already accepted (FIR-11 plan: cells under-powered for δ = 10pp are *"not a ship gate"*), and it is the failure mode [EVAL-17] names.

**The v6.3 replacement was itself wrong and is retired here.** It declared the head-to-head an **exact-binomial McNemar** test on discordant media, gated on a post-hoc percentage-point MDE, labeled cells with **Wilson** intervals, and blocked face-level cells behind an unmeasured intra-occasion `ρ` via `DEFF = 1 + (m − 1)·ρ`. Three defects, all disqualifying:

- **McNemar does not apply to a micro-averaged ratio.** McNemar tests a paired *binary* outcome on a fixed set of units. Recall's denominator (labeled GT faces) is shared across legs, so a paired per-face test is at least well-defined there — but **precision's denominator (predicted boxes) is leg-specific**, so leg A and leg B are not two measurements of one unit and there is no discordant pair to count. Applying one test to both is a category error, and the tested quantity (a per-unit win/loss split) is not the quantity the report prints (a difference of pooled ratios).
- **A percentage-point MDE computed at the observed `n_discordant` is post-hoc power.** An MDE evaluated after seeing the data is a re-expression of the observed standard error, not an independent precondition; gating on it adds no information the interval does not already carry.
- **The `ρ` gate blocks the whole plan on a nuisance parameter that never needs estimating.** Choosing the resampling unit to be the correlated group makes clustering vanish by construction — no `ρ`, no `DEFF`, no dependency on FIR-11 Slice 4.

**Estimand (pinned).** For each cell the reported quantity is the **difference between legs of the micro-averaged ratio the report prints** — `Δ = metric(A) − metric(B)` — over the scoring population of the endpoint being estimated:

- **Identification endpoints and the primary endpoint** use the shared **`accepted_set`** — the set of media that satisfy, on **both** legs, the three membership conditions in [EVAL-19 operationalized](#eval-19-operationalized-accepted-set): (i) terminal-success ingest, (ii) terminal-success analyze with int `stack_media_id`, (iii) presence on that leg's `items.jsonl` roster. Zero-detection items (roster-present, zero export rows) that clear those conditions **remain in `accepted_set`** and are scored as misses (`pred_faces = 0`).
- **Detection endpoints** (detection precision/recall, FP counts) use **`detection_scoring_set`** — `accepted_set` minus every entry that does not carry exhaustive `face_boxes`. A subset of `accepted_set` by construction.

Bootstrap resampling is over the population of the endpoint being estimated: `accepted_set` for identification and primary, `detection_scoring_set` for detection endpoints. The uncertainty statement must be about that quantity and nothing else.

**Scale (pinned).** All effect sizes, confidence bounds, and thresholds in this document are on the metric's own 0..1 fraction scale. `head_to_head_delta: 0.10` means ten percentage points expressed as 0.10. No field carries a percentage-point encoding.

A cell is CONFIRMATORY only when **all** of the following hold, each computed and printed next to the cell:

1. **Uncertainty comes from an image-level cluster bootstrap.** `score` resamples **whole media units** with replacement from the endpoint's scoring population (`accepted_set` or `detection_scoring_set` as above), `B = 2000` (pinned constant `BOOTSTRAP_RESAMPLES`), recomputes **both legs** on the *same* resample, and forms an equal-tailed 95% percentile interval of the resulting Δ distribution (definition below). Two properties come for free and are the reason this design is chosen: the pairing is preserved *by construction* (both legs always see the identical resample, so shared-corpus variance cancels without a paired test), and within-image correlation between faces is absorbed *by construction* (the resampling unit is the image, not the face), so no intra-cluster coefficient is estimated or assumed. Ratio denominators may differ between legs — the bootstrap is indifferent to that.
2. **The resampling unit is the coarsest declared grouping.** If the pinned manifest declares an occasion / session / capture-event id, resample at **that** level when the unit is fully accepted (rules below); otherwise the media unit is the coarsest grouping the corpus offers and the report states so in the provenance block. This is the honest form of the retired `ρ` item: correlation is handled by the resampling unit, and where the corpus cannot name the group the report discloses the residual rather than gating on an unmeasured parameter. When the resampling unit is declared at occasion/session level, three rules pin partial membership:
   - **(a) Full-acceptance only.** An occasion is a resampling unit only if it is **fully accepted** — every one of its images is in the endpoint's scoring population (`accepted_set` or `detection_scoring_set` as applicable). A partly-accepted occasion is split: its accepted images resample individually at image level, and provenance stamps `partial_occasions` with the count of occasions so split.
   - **(b) Paired at the unit level.** Legs are paired at the unit level. An occasion whose membership differs between legs is not a shared unit and falls to rule (a) on both legs.
   - **(c) Stamp what was used.** `resampling_unit` records the unit **actually** used, and when rule (a) split any occasion it records the mixed form (e.g. `occasion+image`) rather than claiming a clean occasion-level resample.
3. **δ is declared before the run**, in the stack-pair config as `head_to_head_delta` (**required**, no default — must be declared before the run). A non-binding example used by sibling FIR plans is **0.10** (ten percentage points on the 0..1 fraction scale); declaring the same value makes FIR-8 and FIR-11 claims comparable, but the loader never supplies a fallback. A δ chosen after seeing the split is a post-hoc threshold, not a gate.
4. **The interval is precise enough to resolve δ.** The bootstrap CI **half-width on Δ must be ≤ δ/2**. This is a precision criterion on the interval actually reported, not a power calculation replayed at the observed split: an interval wider than δ cannot distinguish "the legs differ by δ" from "the legs are equivalent", whatever the point estimate says. `score` stamps `ci_half_width` on every cell; `ci_half_width > δ/2` → **DIRECTIONAL**, no exception. Note what binds: two stacks that agree on almost everything still produce a *narrow* interval around Δ ≈ 0 and legitimately clear this criterion as an equivalence result — the retired discordant-pair gate wrongly failed that case.
5. **Exactly one primary endpoint is pre-declared.** The primary is **detection recall on `frame_e2e` under `label_map_primary`**, named in the config as `primary_endpoint` and fixed before the run. It alone may carry an unadjusted gate claim. Every other cell is a **pre-declared secondary**, listed in the config as `secondary_endpoints`; secondaries reach CONFIRMATORY only after **Holm–Bonferroni** adjustment across that declared list (see [Secondary-endpoint significance](#secondary-endpoint-significance) below). A cell absent from both config keys is **DIAGNOSTIC** and can never be promoted — this is what stops the report's ~20-cell grid from being a multiplicity farm in which some cell always clears any threshold.
6. **The interval is labeled for what it covers.** Every cell's interval is labeled **conditional on this pool** — golden150 is a convenience corpus, not a probability sample of deployment traffic, so the interval bounds resampling noise within the pool and says nothing about generalisation.

**Bootstrap interval (pinned).** The interval on Δ is fully specified so two implementations cannot disagree legally:

- **Equal-tailed 95% percentile interval:** `lower` = 2.5th percentile of the B Δ replicates, `upper` = 97.5th percentile, computed with **linear interpolation between order statistics**.
- **`ci_half_width = (upper − lower) / 2`** (same unitless 0..1 fraction scale as the metric; not a percentage-point field).
- **Zero-imputed sample space.** An undefined micro-ratio resample is treated as `Δ = 0` (no evidence of a signed difference) so p and the percentile CI share the full B-draw space: percentiles run over `defined + [0] * n_undefined`, not over survivors alone. A heavily-partial cell can therefore collapse both tails onto the zero mass (`ci_half_width == 0`). `bootstrap_status = "partial"` then refuses CONFIRMATORY; the emitted cell stamps `ci_level` / `ci_lower` / `ci_upper` / `ci_half_width` as `null` rather than publishing that collapsed interval as a real CI. The interval object used for p / the precision floor still uses the padded space.
- Stamp on every reported endpoint, in provenance: `ci_level: 0.95`, `ci_lower`, `ci_upper`, `ci_half_width`, `bootstrap_resamples` (= B), `bootstrap_seed`, and `resampling_unit`.
- `bootstrap_seed` is a **required run input**, not a default, so a rerun reproduces the interval bit-for-bit.

**Determinism ([PROV-05]).** The bootstrap is seeded from `bootstrap_seed` in the stack-pair config (required key, no default — an unset seed is a config error, not a random run). `score` stamps `bootstrap_seed`, `bootstrap_resamples`, `ci_level`, and the resampling unit in the provenance block, so a reported interval is reproducible from the artifact alone.

#### Secondary-endpoint significance

Secondaries that clear the precision half-width gate still require a significance test before CONFIRMATORY. The procedure is pinned as follows:

- **H0** for each secondary endpoint: `Δ = 0`.
- **Two-sided bootstrap p-value** from the **same** B = 2000 paired replicates already computed for the interval — no second resampling pass:
  - `p_raw = 2 * min( (#replicates ≤ 0) / B , (#replicates ≥ 0) / B )`
  - `p = min(1.0, max(p_raw, 1 / (B + 1)))`
  - The lower clamp names the resolution floor: with B = 2000 no endpoint can report `p < 1/2001`.
- **α = 0.05**; **family** = the ordered `secondary_endpoints` list for this run. The single pre-declared primary endpoint is **not** in the family and is not Holm-adjusted.
- **Holm–Bonferroni step-down:** sort ascending by p; the endpoint at 1-based rank *i* is significant iff `p_(j) ≤ α / (m − j + 1)` holds for every *j* ≤ *i*, where `m = |family|`.
- Stamp per endpoint: `p_value`, `holm_rank`, `holm_threshold`, `holm_significant`.
- A run with an empty `secondary_endpoints` list performs **no** Holm adjustment and stamps an empty family; that is not an error.

**Discrimination red-proof (mandatory, [TEST-15]).** Two fixtures pin the precision precondition arithmetic. Both use 6 images and `head_to_head_delta = 0.10` (so `δ/2 = 0.05`):

- **GREEN (precondition satisfied):** both legs identical on every image. Every paired replicate gives `Δ = 0`, interval `[0, 0]`, `ci_half_width = 0 ≤ 0.05`. Tier is not downgraded by the half-width gate.
- **RED (precondition violated):** the per-image metric is 1 on leg A and 0 on leg B for images 1–3, and 0 on leg A and 1 on leg B for images 4–6. The point estimate `Δ` is 0, but the per-image paired differences are `{+1, +1, +1, −1, −1, −1}`, so image-level resamples spread Δ across roughly `[−1, +1]` and `ci_half_width` is on the order of 0.7–1.0, far above `δ/2 = 0.05`. The cell is downgraded to **DIRECTIONAL** with reason `ci_half_width_above_precision_floor`. The RED fixture must pin `bootstrap_seed` and assert `ci_half_width > 0.05` (a **threshold** assertion), **not** an exact float — the exact value is seed- and interpolation-dependent.

**Resampling-unit discrimination (also [TEST-15]).** Two additional fixtures pin the unit rules above:

- **Media-level vs face-level:** the RED half-width fixture above is load-bearing for image-level resampling — resampling individual faces instead of whole media units would shrink the interval and can turn RED green.
- **Media-level vs occasion-level:** six images in two fully-accepted occasions of three images each, with the same paired per-image differences `{+1, +1, +1, −1, −1, −1}` arranged so each occasion is internally uniform (occasion A: three `+1`; occasion B: three `−1`). Occasion-level resampling yields only two distinct unit outcomes (`+1` and `−1`) and a different `ci_half_width` than media-level resampling of the six images. The fixture asserts the stamped `resampling_unit` is `occasion` when both occasions are fully accepted on both legs, and asserts the half-width matches the occasion-level computation — swapping the unit to media (or to face) fails the fixture. A companion case with one occasion only partly accepted asserts rule (a): split to image-level for that occasion's accepted images, `partial_occasions ≥ 1`, and `resampling_unit` records the mixed form (e.g. `occasion+image`).

[TEST-15] load-bearing implementation changes:

- The change that turns the RED case green: **removing the half-width gate from the tier resolver**.
- The change that turns the GREEN case red: **computing the interval on unpaired rather than paired resamples**.
- The change that collapses the media-vs-occasion discrimination: **always resampling at media level when an occasion id is declared and fully accepted**.

Infrastructure cost is ~60 lines: a resample loop over the endpoint's scoring population, a percentile helper, and a Holm helper. **No `scipy` dependency, no interval helper from a named parametric family, and no dependency on FIR-11 Slice 4** — the retired intra-occasion `ρ` gate was the only thing that coupled FIR-8's statistics to FIR-11.

### Cell → tier assignment (normative)

Rules are evaluated **top to bottom; first match wins**. A cell reaches CONFIRMATORY only by falling through every downgrade above it.

| Report cell | Tier rule |
| --- | --- |
| Any P/R cell when either leg cluster phase missing/failed | **not scored** (score aborts; no silent tier downgrade that invents a metric) |
| Any P/R cell when `differential_attrition_exceeded` | **no P/R cells** — order: (1) write accepted-set + attrition artifacts to disk FIRST; (2) emit NO precision/recall cells; (3) exit non-zero with `differential_attrition_exceeded` (surviving pool biased toward the failing leg; no tier is honest) |
| Per-stack raw detection counts, export row counts, count-only detection P/R | **DIAGNOSTIC** (`count_only` is the first `assign_tier` match) |
| Any cell named in neither `primary_endpoint` nor `secondary_endpoints` | **DIAGNOSTIC** (never promotable — see precision precondition item 5) |
| **Detection endpoint cell when any accepted entry was dropped from `detection_scoring_set` for unasserted exhaustiveness** (box-less or incomplete `face_boxes` on an otherwise-accepted entry) | **DIRECTIONAL**, reason `detection_exhaustiveness_unasserted` (a detection claim over a corpus whose exhaustiveness is unasserted is directionally usable but not headline-quotable; DIAGNOSTIC is reserved for cells that fail a hard precondition. Dropped entries leave `detection_scoring_set` entirely; this row tiers the *cell*.) |
| Any P/R cell when `\|accepted_set\| < resolved_floor_count`, where `resolved_floor_count = max(2, ceil(accepted_set_floor × N))` and `N = \|manifest entries loaded for this run\|` for a fractional floor (or the absolute int ≥ 2 for an integer floor) — never below 2; reason `accepted_set_below_floor` | **DIRECTIONAL** |
| Any P/R cell with `ci_half_width > head_to_head_delta / 2` | **DIRECTIONAL**, reason `ci_half_width_above_precision_floor` |
| Identification P/R with `label_map_optimistic` | **DIRECTIONAL** (always) |
| Detection P/R on `frame_fir5_native` | **DIRECTIONAL** (always — secondary frame, see the frame pin below) |
| Named confirmatory-eligible cell (primary, or Holm-significant secondary) whose `bootstrap_status` is not `ok` | **DIRECTIONAL**, reason `bootstrap_status` (a missing ctx key raises `bootstrap_status_missing` instead of defaulting to `ok`) |
| Detection recall on **`frame_e2e`** with `label_map_primary` (the pre-declared `primary_endpoint`), IoU-matched, accepted set, clusters OK, floor, precision, and `bootstrap_status == ok` | **CONFIRMATORY** (unadjusted — the sole primary) |
| Any other cell listed in `secondary_endpoints` meeting the same conditions **and** surviving Holm adjustment **and** `bootstrap_status == ok` | **CONFIRMATORY** |
| Named secondary that is not Holm-significant (status already `ok`) | **DIRECTIONAL**, reason `holm` |
| Unmapped-cluster counts / residual after mapping | **DIAGNOSTIC** |
| Attrition table (per-leg failure counts by phase) | **DIAGNOSTIC** |
| Provenance / license banner fields | **DIAGNOSTIC** (metadata, not a quality claim) |

**Primary sampling frame is pinned to `frame_e2e`.** An earlier revision marked *"Detection P/R (`frame_e2e` **or** `frame_fir5_native`)"* CONFIRMATORY, which produced **two** gate-eligible detection numbers per leg with no rule for which one the head-to-head claim uses — so whichever frame flattered the preferred stack could be selected after the fact. The label-map frames were already pinned one line earlier (`label_map_primary` is "**default** for CONFIRMATORY identification cells"); the sampling frames were not, and that asymmetry was the defect. `frame_e2e` is the primary because cascade honesty ([EVAL-16], already a locked constraint) says a face the detector missed is an end-to-end error — a frame that excludes detector misses cannot carry the headline claim. `frame_fir5_native` stays in the report as the always-DIRECTIONAL companion that isolates *post-detection* quality; both print side by side, and neither may be substituted for the other.

---

## EVAL-19 operationalized (accepted set)

[EVAL-19] is not only “share a denominator” — the denominator is a concrete artifact:

1. **Definition (three conditions, not two).** `accepted_set` = set of manifest items (`manifest_media_id` / path / sha256) for which, on **both** legs, `legs/<stack_id>/items.jsonl` records (i) terminal-success for **ingest** — read from the explicit **terminal ingest outcome** field written at analyze return (`success`; any other value, or a missing field, is failure — fail closed on missing evidence), (ii) terminal-success for **analyze** with an int `stack_media_id` recorded on the analyze-success record (client-supplied; always written on the success path — missing/null is not a defined state), and (iii) the media id is present on that leg's **`items.jsonl` roster** (the authoritative submitted-media list for the leg). Condition (iii) is roster membership, not export-row presence: the public export is a batched opaque GET of identity rows, so a media id with zero detections contributes no export row — byte-for-byte identical to an unprocessed media id. Resolve that distinction from the ingest roster ([media identity join](#d-media-identity-join)). `accepted_set` is the scoring population for **identification endpoints and the primary endpoint**.
   - **`detection_scoring_set`** = `accepted_set` minus every entry that does not carry exhaustive `face_boxes` (`face_count == len(face_boxes)`, boxes present). Scoring population for **all detection endpoints** (detection precision/recall, FP counts). A subset of `accepted_set` by construction. Entries excluded for unasserted exhaustiveness leave this set entirely and are counted/printed; a detection cell whose corpus dropped any such entry is **DIRECTIONAL** with reason `detection_exhaustiveness_unasserted`.
   - **Zero detections are not the same as an absent media id, and conflating them corrupts recall.** A media id present in `items.jsonl` with zero export rows is **ZERO DETECTIONS** — accepted (subject to (i)+(ii) on both legs), `pred_faces = 0`, stamped in provenance as `zero_detection_media_count`. A media id present in one leg's `items.jsonl` but not the other is an **INGEST ASYMMETRY** — excluded from `accepted_set`, counted as `ingest_asymmetric_media`. An export row whose media id is absent from `items.jsonl` is a **contract violation** (`export_media_not_in_roster`), not a silent extra. Treating zero-export-row as a join failure would silently delete every image the detector missed entirely from the denominator — inflating that leg's recall by exactly its worst failures. Both join sides are ints with **no** coercion.
2. **Compute once** at the start of `score` (after both legs finished run): intersection of the per-leg sets satisfying all three conditions → `accepted_set`; then `detection_scoring_set` as the exhaustive-boxes subset.
3. **Persist**: write `score/accepted_set.json` (`manifest_media_ids`, `paths`, `content_sha256s`, `accepted_set_size`, `detection_scoring_set_size`, `manifest_entry_count` (= N, the corpus denominator for the floor), `floor_config` (the raw configured value), `resolved_floor_count` (the item count actually compared against — see [floor policy](#floor-policy-normative)), `resampling_unit`, `computed_at`). Stamping `floor_config`, `resolved_floor_count`, `accepted_set_size`, and `manifest_entry_count` makes the floor comparison reconstructible from the artifact alone.
4. **Assert before metrics**: both legs' success sets, when intersected, match the file; re-derive and fail closed if a leg's items.jsonl was mutated after the file was written.
5. **Attrition (reported, not silent)**: items in the manifest but missing from the accepted set appear in `score/attrition.json` (and the report DIAGNOSTIC table). For each missing item the `phase` names **which of the three membership conditions failed** — `ingest` (condition i), `analyze` (condition ii), or `roster` (condition iii — media id not on both legs' `items.jsonl` rosters; includes `ingest_asymmetric_media`) — plus one-sided success counts (satisfied all three conditions on A only / B only). Operational cluster/export failures that are not membership conditions may appear as DIAGNOSTIC context but do not redefine accepted-set membership. Exhaustiveness exclusions from `detection_scoring_set` are a separate counted print, not pre-accept attrition. Provenance stamps `zero_detection_media_count` for roster-present media with zero export face rows, and stamps the two shrinkage causes separately as `attrition_ingest_analyze` (conditions (i)/(ii)) and `attrition_join` (condition (iii) / join-phase).
6. **Detection failure after accept**: a media that satisfies all three membership conditions on both legs stays in the accepted set even if detection count is zero — that is a scored miss, not attrition. Attrition is **pre-accept** failure only. Arithmetically: the item contributes to the recall **denominator** (`labeled_faces` / labeled GT boxes) with **zero true positives** (`matched_faces = 0`, so `FN = labeled`); dropping it from the denominator is a silent recall inflation and is forbidden. Red-proof in `test_attrition_floor.py` (zero-detection accepted item): if the scorer excludes the item from the recall denominator, the fixture goes red.
7. **Floor**: if `|accepted_set| < resolved_floor_count` (the count, never the raw fraction — see [floor policy](#floor-policy-normative)), all P/R cells downgrade to **DIRECTIONAL** with reason `accepted_set_below_floor` (see tier table); report still emits metrics with the disclosure.

---

## Carried-forward invariants (orchestration layer)

Adapt v5 review-hardened invariants; **do not re-litigate**. Enforcement lives in the **CLI**, not the recognition service.

### CF-1. Baseline / corpus ingest contract

- Uploaded or declared baseline / label artifact `media_id` (or content-sha) set **must be a SUPERSET** of the run's accepted set. **Partial intersection = blocker** (exit non-zero; do not score a silent subset).
- **Where the check runs, and against what (ordering pin).** The accepted set is first computed by `score` (S2), so an S1 blocker cannot compare against it. It does not need to: accepted ⊆ manifest always holds, so `baseline ⊇ manifest` **implies** `baseline ⊇ accepted`. When the optional config key **`baseline_manifest_path`** is present, S1 loads that manifest, derives `baseline_ids`, and asserts the **stronger** condition — `assert_baseline_superset(manifest_ids, baseline_ids)` at `run` start, **before any media write** — which is both runnable at that point and strictly better, since it fails the operator in seconds instead of after a full two-leg ingest. When `baseline_manifest_path` is **absent**, the assertion is **skipped**. **`baseline_superset_checked` is stamped by `score`, true only if `baseline_manifest_path` was set and the superset assert executed and passed; false if the path was unset or the assert was skipped. It is never written by `preflight`.** S1 fully covers the superset contract via the stronger condition when the key is present; there is no separate S2 re-assert.
- **Per-item outcomes** append to `legs/<stack_id>/items.jsonl` (see [Ground truth & label mapping](#d-media-identity-join)) using the per-item field list from the [PROV-01 field inventory](#s1-executable-contracts-normative) — resume never loses hard-fail tallies. `image_width` / `image_height` are positive ints produced at ingest by `scripts/bench/corpus.py` `ItemOutcomeStore` so scoring never re-opens image bytes. **Dimensions are read with Pillow after `ImageOps.exif_transpose`, so they match the orientation the detector sees. An image whose EXIF orientation implies a 90/270-degree rotation therefore records the transposed dimensions.** A Pillow open failure is `image_decode_failed` (media id excluded and named in provenance; it does not silently become a zero-dimension record). The items.jsonl reader rejects any record whose dimensions are missing, non-integer, or ≤ 0 with `image_dimensions_missing` ([rg-008], fail at load not at use).
- **There is no stack-side enroll API.** Media bytes resolution order (normative):
  1. **Local path first**: resolve `GoldenEntry.path` under `--images-dir` / corpus root (NFC/NFD tolerant, same idea as `manifest._resolve_image`); read bytes; verify sha256 against entry when present.
  2. **Remote URL second**: if local file is missing and the entry (or corpus overlay via optional config key **`media_url_map_path`**) provides an HTTPS URL (`provenance.url` or operator URL map), fetch via CLI outbound HTTP. The red-proof in `test_media_pin_public_unicast.py` exercises this overlay path.
  3. Else mark item `failed` with `error_code=media_unresolvable`.
- **CF-1 pinning applies to the remote case**: pinned resolved-address SET per media host at first resolve; subsequent fetches connect only to pinned addresses (anti DNS-rebinding). **Public-unicast enforcement**: reject link-local, RFC1918, loopback unless explicit **`allow_private_source: true`** LAN override in stack-pair config. Local filesystem reads skip network pin rules.

### CF-2. Production-shaped-data guard

Refuse to run against a stack whose core identity-adjacent tables are **nonzero** unless the stack is one of the **two named bench stacks** in the stack-pair config.

Enumerate from `001_identity_schema.py` (same set as v5):

| Table | Role |
| --- | --- |
| `tenants` | tenant root |
| `media_identities` | embedding/identity media rows |
| `identity_clusters` | cluster/person-like entities |
| `identity_members` | cluster membership edges |

Implementation note: the CLI does **not** open a raw production DB URL for arbitrary hosts. Prefer an **operator-exported** table-count snapshot endpoint **only if already present**; otherwise the runbook requires FIR23-STACK / operator attestation that the target is a named bench stack, and the CLI checks a **stack identity allowlist** (configured `stack_id` from the consumption table) before any write. If a future stack admin diagnostic exposes counts, consume it without inventing envelope fields ([rg-015]). **Do not** query `handoff.db` or invent SQL against unknown DSNs.

### CF-3. License posture

- Insightface / buffalo_l leg: **INTERNAL BENCH ONLY** (NC weights; QA §buffalo-as-judge — judge / acceptance-bar use only).
- Outputs **never** become training data.
- Runbook **forbids** exposing the insightface stack to any commercial or user-facing path (no public product ingress, no customer tenant keys on that stack for product traffic).
- Reports always carry `license_notice` with that sense.
- **Intermediate artifacts** (`run.json`, per-leg export JSON, `score/frames.json`) and the HTML report stamp the same internal-bench-only banner (one-sentence field `license_banner` + human-readable report header).

### CF-4. Bounded runs

- Wall-clock budget per bench run (config: `wall_clock_timeout_sec`, default **3600**).
- Queued-age / per-job poll budget (config: `job_poll_timeout_sec`, default **600**; align with `RemoteSceneClient` poll bounds).
- Enforced by the **CLI** (cancel outstanding polls, write partial outcomes, exit non-zero) — **not** a service supervisor.

### CF-5. Scoring discipline (QA + canon)

- [EVAL-16] cascade honesty via end-to-end frame injection in the adapter.
- [EVAL-19] fixed denominators = accepted set artifact — see [EVAL-19 operationalized](#eval-19-operationalized-accepted-set).
- [PROV-01] provenance is the full field inventory in [PROV-01 via `preflight.json`](#s1-executable-contracts-normative) (not a partial re-list); report consumes both legs' artifacts + the run-level fields from that inventory.
- Tier labels: `CrossbenchTier` assignment rules — see [Tier vocabulary](#tier-vocabulary). Do not invent additional tier names beyond that enum.
- Label mapping: primary string-match is default; optimistic Hungarian is disclosed DIRECTIONAL only — see [Ground truth & label mapping](#ground-truth--label-mapping).

### CF-6. Cluster-before-export

- Per leg, after analyze jobs complete: `client.clustering_job(tenant_id, mode="sync")`.
- Persist outcome under run dir (`legs/<stack_id>/cluster_job.json` with status payload).
- Gate for entering the phase (identical wording): every analyze job for a leg has reached a **terminal** outcome — success, or failure with `item_max_attempts` exhausted — **and at least one succeeded** — see [Workflow Principles](#workflow-principles). Not "all successful." Zero analyze successes → no cluster, no export, terminal leg outcome `cluster_gate_refused` in `legs/<stack_id>/leg_outcome.json`.
- `export_map.export_leg` / score path **aborts** if cluster outcome is missing or non-success (mocked test required, `test_cluster_gate.py`, S1).

### CF-7. Score credential flow (pinned)

**Pick one path — locked**: `run` persists **all** public exports needed for scoring under `legs/<stack_id>/exports/` during the leg. `score` reads the run directory only and requires **no** API credentials / network. Re-export is not part of `score` (operator re-runs `run` if exports are incomplete).

---

## Non-goals

- **No recognition-service code changes** (API, worker, schema, admin console).
- **No compose / Caddy / systemd / ingress ownership** — FIR23-STACK.
- **No in-service bench supervisor**, `recognition_bench_runs`, marker rail, or purge-before-terminal phases.
- **No same-process dual-profile toggle**; no Option B wipe/flip.
- **No parallel scorer** replacing FIR-5 pure metrics.
- **No embedding-export / landmark-export implementation** in FIR-8 (optional upstream ask only).
- **No score-face run-record or clustering purity sweep** on the cross-stack path (see [Feasible scoring scope](#feasible-scoring-scope)).
- **No WP control surface**.
- **No commercial / user-facing exposure** of the insightface stack.
- **No training-data export** from bench outputs.
- **No escalation-ladder implementation** (scope/epic contingent ladder remains a separate task id if still reserved — out of this plan's code path).

---

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tooling (new) | `apps/prototype-description-service/scripts/bench/cross_stack_bench.py` | CLI entry: `preflight`, `run`, `score`, `status` subcommands |
| tooling (new) | `apps/prototype-description-service/scripts/bench/stack_pair.py` | Load/validate YAML/JSON against FIR23-STACK consumption table ([rg-008]) |
| tooling (new) | `apps/prototype-description-service/scripts/bench/preflight.py` | Own GETs to `/ready` + `/health/detailed`; real field contracts; stable error codes; write `preflight.json` |
| tooling (new) | `apps/prototype-description-service/scripts/bench/corpus.py` | Manifest load via `load_bench_manifest` / `load_manifest`; media resolution order; pin sets; superset check; **`ItemOutcomeStore`** — the ingest writer that emits `legs/<stack_id>/items.jsonl`: decode each image once with Pillow at ingest after `ImageOps.exif_transpose` and record decoded pixel `image_width`/`image_height` alongside the existing item fields (transposed dims when EXIF implies 90/270° rotation); append **terminal ingest outcome** (`success` or failure reason) per media id at the point analyze returns so condition (i) is evaluable from the roster alone (missing outcome = failure, fail closed); `image_decode_failed` on open failure; items.jsonl reader rejects bad dimensions with `image_dimensions_missing` |
| tooling (new) | `apps/prototype-description-service/scripts/bench/driver.py` | Ingest → analyze → cluster → **export** driver with resume; run-dir layout; drives `ItemOutcomeStore` to write the terminal ingest outcome field on each analyze return |
| tooling (new) | `apps/prototype-description-service/scripts/bench/export_map.py` | **S1 symbols:** `export_leg`, `require_cluster_success`, `load_leg_exports` (gate + persist public exports, preserve envelopes). **S2 symbols:** `map_cluster_labels_primary`, `map_cluster_labels_optimistic`, `to_face_metric_inputs(..., frame: Literal["native", "e2e"])`, `match_detection_boxes` (GT + label map → metric rows; two frame calls, detection rows identical, identification rows differ). No symbol is owned by both slices. |
| tooling (new) | `apps/prototype-description-service/scripts/bench/score.py` | IoU/assignment helpers imported by `export_map` / `score_report`; matching threshold is `IOU_MATCH_THRESHOLD` from `scripts/eval_harness/face_assignment.py:29` (not re-declared) |
| tooling (new) | `apps/prototype-description-service/scripts/bench/score_report.py` | Dual sampling + label-map frames; `CrossbenchTier` rules; `accepted_set.json` / attrition; write report; uses `IOU_MATCH_THRESHOLD` from `face_assignment.py:29` |
| tooling (new) | `apps/prototype-description-service/scripts/bench/production_shaped_guard.py` | Named-stack allowlist + optional count attestation |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_preflight.py` | Fail-closed dim/profile/auth/missing-field with real payload shapes |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_corpus_superset.py` | Superset / partial-intersection blocker |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_resume.py` | Resume idempotency |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_stack_pair_consumption.py` | Base URL / stack_id not in pinned table → load fails |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_media_pin_public_unicast.py` | RFC1918 remote without LAN override → ingest refuses (mocked resolver) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_cluster_gate.py` | **S1.** Gate wording: every analyze job for a leg has reached a terminal outcome — success, or failure with `item_max_attempts` exhausted — and at least one succeeded. Three fixtured legs: (a) all analyze terminal with ≥1 success → gate ADMITS; (b) all terminal, zero successes → gate REFUSES (`cluster_gate_refused`, no cluster/export); (c) a non-terminal analyze still in flight → gate REFUSES. Export aborts when `cluster_job.json` missing/non-success. |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_e2e_frame.py` | Detector-miss → ID-miss accounting (dual frames) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_e2e_mocked.py` | One mocked end-to-end (both legs → report dir) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_export_map_rg015.py` | **S1.** Export normalization invents no envelope metadata (rg-015): red if `export_map` synthesises `limit`/`offset`/`total`/`data_source` from convenience derivations such as `len(payload)` instead of the upstream payload |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_detection_localization.py` | [TEST-15] pinned geometry (GT centre `0.5/0.5/0.2/0.2` on 1000×1000; GREEN pred `{400,400,200,200}` → `matched_faces = 1`; RED translation `{700,400,200,200}` → `matched_faces = 0`, one FP + one FN; RED centre-in-box/containment pred `{100,100,800,800}` → IoU 0.0625, `matched_faces = 0`); count-only cell stays perfect on translation RED |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_precision_precondition.py` | `ci_half_width > δ/2` → DIRECTIONAL; GREEN/RED discrimination fixtures; image-level cluster bootstrap red-proofs; Holm on declared secondaries |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_manifest_version_seam.py` | exhaustiveness-asserted boxed fixture (`require_detection_exhaustiveness=True`) → `stranger_faces` from `name is None` + CONFIRMATORY-eligible; box-less / non-exhaustive under default flag → `stranger_faces == 0`, entry leaves `detection_scoring_set`, cell **DIRECTIONAL** with reason `detection_exhaustiveness_unasserted`; `face_count != len(face_boxes)` under `require_detection_exhaustiveness=True` → `gt_box_count_mismatch`; under default `False` the same condition loads as non-exhaustive with no error; no module under `scripts/bench/` derives a face count by subtracting `len(present_identities)` from `face_count` |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_attrition_floor.py` | fractional + absolute floor forms (reject `1`); `resolved_floor_count = max(2, ceil(accepted_set_floor × N))` with `N = \|manifest entries\|`; `differential_attrition_exceeded` artifacts-then-refuse; zero-detection accepted item stays in recall denominator (goes red if dropped) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/fixtures/v2_boxed_detection.json` | Purpose-built v2 detection fixture — full required-field JSON under [fixture content](#manifest-load--detection-exhaustiveness-no-fir-11-coupling); `scene/tests/seed/golden.json` has zero boxes and cannot serve as a detection fixture |
| tooling (new) | `apps/prototype-description-service/scripts/bench/__init__.py` | Package marker required for `uv run python -m scripts.bench.*` and documented import/test paths (`scripts.bench.*`); parent `scripts/` is the existing package shared with `eval_harness` |
| harness (**edit**) | `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` | Scoped to the optional `ImageDetection.matched_faces` field, the **clamped** `TP/FP/FN` branch that honours it, and the `0 <= matched <= min(pred, labeled)` bounds check. Default `None` → numerically identical existing behaviour (not byte-identical at the dataclass level — see the [localization pin](#b-constructing-metric-inputs)). Rationale + scope: [localization pin](#b-constructing-metric-inputs) |
| harness (**read, not edited**) | `apps/prototype-description-service/scripts/eval_harness/report.py` | Consumer under the additive `matched_faces` field; **READ, NOT EDITED** — takes the `None` path → numerically identical numbers. Also retains the legacy `stranger_faces = max(face_count - len(present_identities), 0)` and `labeled_faces=face_count` at L454-461 (existing eval-harness report path; figures not comparable to FIR-8's `len(face_boxes)` denominator) |
| tests (**edit**) | `apps/prototype-description-service/scene/tests/test_eval_harness_face_metrics.py` | (1) parametrized `matched_faces` bounds table — five cases: (i) `matched=0` accepted FP=3 FN=2; (ii) `matched=2` accepted at upper bound FP=1 FN=0 (load-bearing for `<=` vs `<`); (iii) `matched=3` → `matched_faces_out_of_bounds`; (iv) `matched=-1` → `matched_faces_out_of_bounds`; (v) omitted → count-only legacy path; (2) field is optional with default, added last (positional construction would break) |
| docs (new) | `apps/prototype-description-service/scripts/bench/README.md` | Package README (S3) |
| docs (new) | `docs/runbooks/fir-8-cross-stack-bench.md` | Operator runbook + teardown + license; carries the `opencv_version` upstream ask in the residual section |
| docs (edit) | this plan | v6.7 plan grounding (this commit) |

**Explicitly untouched:** `apps/prototype-description-service/recognition/**`, `db/migrations/**`, WP plugin, FIR23-STACK compose/deploy files.

**Edits outside `scripts/bench/` — the complete list is two files, not one.** `scripts/eval_harness/face_metrics.py` (the additive optional-with-default `matched_faces` field, added last, and its `detection_pr` branch) and `scene/tests/test_eval_harness_face_metrics.py` (parametrized five-case bounds table + optional-last-field assertions; proof command: `uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py` from `apps/prototype-description-service`). Both are offline harness code, so the "no recognition-service code changes" constraint is intact. `scripts/eval_harness/report.py` is a **consumer that is READ, NOT EDITED** — see the [consumer inventory](#dual-frame-adapter-contract-fir-5-signatures-pinned); it retains the legacy subtraction at L454-461. Any claim elsewhere in this plan that `face_metrics.py` is the *single* edit outside `scripts/bench/` is superseded by this paragraph.

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/remote_client.py` | Prefer reuse / thin wrap for analyze/cluster/export HTTP; **no health methods** |
| `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` | Face P/R pure functions (`ImageDetection`, `ImageIdentities`, `detection_pr`, `identification_pr`). Consumed as-is except for **one scoped additive change** — optional `matched_faces` — listed in [Files and Surfaces to Change](#files-and-surfaces-to-change) |
| `apps/prototype-description-service/scripts/eval_harness/manifest.py` | `load_manifest` / `GoldenManifest` / `GoldenEntry` / `FaceBox` — GT schema |
| `apps/prototype-description-service/api/main.py` `register_health_probes` | `/ready` + `/health/detailed` payload shapes |
| `apps/prototype-description-service/recognition/application/health.py` | Database detail string with `pgvector_dimension=` |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/stores.py` | Public media identity export keys |
| `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Core identity-adjacent table list |
| git `bc97ff4b` | Recoverable v5 plan text (superseded) |

## Verification Strategy

### Deterministic tests (required)

```bash
# from apps/prototype-description-service
uv run --extra dev pytest scripts/bench/tests/ -q
uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py
```

Must cover:

1. **Preflight fail-closed (real shapes)** — mock `/health/detailed` body with `model_cache.profile` and `/ready` body with `checks[{name:database,status,detail}]`; insightface leg with `detail` lacking `pgvector_dimension=` or dim≠512 → `profile_or_dim_drift`; missing auth → `preflight_auth_failed`; 404 → `preflight_endpoint_missing`. Same for fir leg (expect 128 / face_pipeline).
2. **Superset blocker** — when `baseline_manifest_path` is set, `assert_baseline_superset(manifest_ids, baseline_ids)` at `run` start: manifest `{1,2,3}`, baseline `{1,2}` → blocker; manifest `{1,2}`, baseline `{1,2,3}` → pass. When the key is absent, the assert is skipped.
3. **Resume idempotency** — after partial `items.jsonl`, re-run does not re-POST terminal-success media; failed items re-attempt up to bounded retry.
4. **Consumption-table cross-check** (`test_stack_pair_consumption.py`) — stack_pair config with a `base_url` / `stack_id` not in the pinned table → `load_stack_pair` fails.
5. **Pin / public-unicast** (`test_media_pin_public_unicast.py`) — remote media URL resolving to RFC1918 without `allow_private_source` → ingest refuses (deterministic mocked resolver).
6. **Cluster gate (`test_cluster_gate.py`, S1)** — gate admits only when every analyze job for a leg has reached a terminal outcome — success, or failure with `item_max_attempts` exhausted — and at least one succeeded; export/score aborts when `cluster_job.json` missing or non-success; zero-success leg records `cluster_gate_refused`.
7. **Dual-frame cascade** — detector-miss synthetic pins e2e FN accounting vs FIR-5-native frame; accepted media with zero export rows stays in the recall denominator on both frames (`pred_faces = 0`, one FN); frames call only `detection_pr` / `identification_pr` with pinned input types.
8. **One mocked E2E** — fake dual clients return fixed cluster payloads → report dir contains provenance (`preflight.json`), `accepted_set.json`, both legs + both sampling frames + label-map frames + tier label + license banner; no network; `score` uses no credentials.
9. **Detection localization ([TEST-15], `test_detection_localization.py`)** — the pinned geometry from the [localization pin](#b-constructing-metric-inputs): GT centre `0.5/0.5/0.2/0.2` on 1000×1000; GREEN pred `{400,400,200,200}` → `matched_faces = 1`; RED translation pred `{700,400,200,200}` → `matched_faces = 0` (one FP + one FN), count-only cell perfect; RED centre-in-box/containment pred `{100,100,800,800}` → IoU 0.0625 < 0.5, `matched_faces = 0` (separates IoU from centre-in-box/containment). Removing the IoU threshold (count-only match) → translation RED matched cell becomes perfect and the test fails; awarding centre-in-box without IoU ≥ 0.5 → centre-in-box RED matches and the test fails. Bounds / optional-last-field proofs for `matched_faces` live in `scene/tests/test_eval_harness_face_metrics.py` (not a before/after `report.py` golden); see that file's parametrized bounds table.
10. **Precision precondition (`test_precision_precondition.py`)** — a cell whose bootstrap `ci_half_width > head_to_head_delta / 2` is stamped DIRECTIONAL even when the accepted set clears the floor (this is the case a size-only rule got wrong); GREEN fixture (identical legs, `ci_half_width = 0`) does not downgrade; RED fixture (paired differences `{+1,+1,+1,−1,−1,−1}`, threshold assert `ci_half_width > 0.05`) does; the image-level resampling unit is load-bearing (face-level would shrink the RED interval); media-level vs occasion-level discrimination fixture (fully-accepted occasions + partial-occasion split with `partial_occasions` / mixed `resampling_unit`); Holm adjustment is applied across declared secondaries. Strip the half-width comparison → the RED cell reads CONFIRMATORY and the test fails; unpaired resampling → the GREEN cell fails its half-width bound.
11. **Detection exhaustiveness (`test_manifest_version_seam.py`)** — the `v2_boxed_detection.json` fixture loaded with `require_detection_exhaustiveness=True` (exhaustive entries pass `face_count == len(face_boxes)`) derives `stranger_faces` from boxes, enters `detection_scoring_set`, and is CONFIRMATORY-eligible; a box-less / non-exhaustive load under default `require_detection_exhaustiveness=False` yields `stranger_faces == 0`, the entry leaves `detection_scoring_set`, and a detection cell on that corpus is **DIRECTIONAL** with reason `detection_exhaustiveness_unasserted`; `face_count != len(face_boxes)` under `require_detection_exhaustiveness=True` → `gt_box_count_mismatch` (under default `False` the same condition loads as non-exhaustive with no error); a box-less entry is excluded from detection frames with a counted exclusion. Assert no module under `scripts/bench/` derives a face count by subtracting `len(present_identities)` from `face_count` (the whole-codebase form of this assertion is false on arrival — `report.py:454-461` retains the legacy subtraction and is READ, NOT EDITED).
12. **Attrition and floor (`test_attrition_floor.py`)** — fractional (`0.90`) and absolute (`135`) floor forms both resolve to an item count before any comparison (`resolved_floor_count = max(2, ceil(accepted_set_floor × N))` with `N = |manifest entries loaded for this run|`); value `1` is load-rejected. On `differential_attrition_exceeded` (even when the accepted set is large — bias check, not size check), the test asserts **all three**: (1) accepted-set + attrition artifacts exist on disk; (2) exit is non-zero with `differential_attrition_exceeded`; (3) **no** precision/recall cells were emitted. Artifacts-without-exit or exit-without-artifacts cannot pass — a crash is not a correct refusal.
13. **No local `cv2` (`test_preflight.py`)** — the bench package imports no `cv2`, and a stack-pair entry lacking `opencv_major` raises `opencv_major_unattested`.

### Runtime-parity / operator checks (S3 runbook)

- Live preflight against real dev + `acx-dev-fir` when stacks are up (operator session; not CI-blocking if stacks absent).
- Stack-scoped reset via **FIR23-STACK documented command** after a run (cite exact command from that plan/runbook when available; placeholder section until FIR23-STACK docs land — **do not invent** reset SQL).

### Contract / fixture

- Export mapper unit test: fixture payloads with pagination fields only from upstream; assert adapter does not set `total=len(data)` unless upstream provided `total` ([rg-015]).
- Export mapper must not require embedding/landmark fields.

### Manual

- Operator opens head-to-head report; confirms `license_notice` present; confirms insightface stack not referenced as product path; confirms both scoring frames present.

---

## Slice Delivery

### Slice 1: Bench CLI skeleton — config, preflight, corpus driver (+ cluster phase + export persist)

**Goal**: Runnable CLI that validates a stack pair against the consumption table, fails closed on dim/profile drift using real health contracts, loads golden-schema GT via `load_manifest`, and drives corpus **ingest → analyze → cluster → export** on both stacks with durable per-item + cluster outcomes, resume, and run-dir layout. Score credentials are not required later because exports land during `run` ([CF-7](#cf-7-score-credential-flow-pinned)).

**Files / functions (normative names)**

| Module | Symbols | Responsibility |
| --- | --- | --- |
| `scripts/bench/stack_pair.py` | `load_stack_pair(path) -> StackPairConfig`, `StackEndpoint` dataclass, `FIR23_STACK_ALLOWLIST` | Parse and validate the complete key schema below; validate `stack_id` ∈ consumption table and base_url host against allowlist identity; reject unknown keys / unknown stacks (fail-closed, [rg-008]) |
| `scripts/bench/preflight.py` | `preflight_stack(endpoint) -> PreflightResult`, `preflight_pair(pair) -> None`, `PreflightError`, `write_preflight_json(path, result)` | Own GETs: `/ready` + authenticated `/health/detailed`; parse profile + dim per [Real preflight contract](#real-preflight-contract); raise with stable codes; persist **PROV-01** artifact |
| `scripts/bench/corpus.py` | `load_bench_manifest(path, images_dir, require_detection_exhaustiveness: bool = False) -> GoldenManifest` (calls `load_manifest` against the v2 schema; when `require_detection_exhaustiveness=True`, fails closed on `face_count != len(face_boxes)` with `gt_box_count_mismatch`; default `False` marks non-exhaustive and does not error — see [Manifest load & detection exhaustiveness](#manifest-load--detection-exhaustiveness-no-fir-11-coupling)), `resolve_media_bytes(entry, images_dir, …)`, `assert_baseline_superset(manifest_ids, baseline_ids)`, `pin_media_hosts(...)`, `ItemOutcomeStore` (Pillow decode → `image_width`/`image_height`; terminal ingest outcome field at analyze return; `image_decode_failed` / `image_dimensions_missing`) | GT load via `load_manifest`; local-then-remote media resolution (optional `media_url_map_path`); pin + public-unicast on remote; append-only JSONL outcomes including Pillow-decoded `image_width`/`image_height` and terminal ingest outcome (`success` or failure reason; missing = failure for condition (i)); optional `baseline_manifest_path` → `assert_baseline_superset` at `run` start; after manifest load, integer `accepted_set_floor` > `\|manifest entries\|` → `accepted_set_floor_exceeds_corpus` |
| `scripts/bench/driver.py` | `run_leg(...)`, `run_pair(...)`, `run_cluster_phase(...)`, `init_run_dir(...)` | Per stack: resolve bytes → `analyze` + `wait_job` → `clustering_job(..., mode="sync")` → call `export_map.export_leg`; resume; budgets. **Owns no export symbol of its own** — see the export-ownership pin below |
| `scripts/bench/export_map.py` (**created in S1, extended in S2**) | `export_leg(client, run_dir, stack_id) -> LegExport`, `require_cluster_success(run_dir, stack_id)`, `load_leg_exports(run_dir, stack_id)` | S1 half only: gate on cluster outcome, fetch and persist the public exports under `exports/`, preserve upstream envelope fields ([rg-015] — never synthesise `limit`/`offset`/`total`/`data_source` from `len(payload)` etc.). The GT-mapping half (`map_cluster_labels_*`, `to_face_metric_inputs`) lands in S2 |
| `scripts/bench/production_shaped_guard.py` | `assert_named_bench_stack(endpoint, allowlist)` | Allow only configured stack_ids before writes |
| `scripts/bench/cross_stack_bench.py` | `main()`, subcommands `preflight` / `run` / `status` / (`score` wired in S2) | argparse CLI (`uv run python -m scripts.bench.cross_stack_bench` from `apps/prototype-description-service`) |
| `scripts/bench/tests/test_preflight.py` | real payload shape cases | red first |
| `scripts/bench/tests/test_corpus_superset.py` | partial intersection | red first |
| `scripts/bench/tests/test_resume.py` | partial JSONL resume | red first |
| `scripts/bench/tests/test_stack_pair_consumption.py` | unknown base_url / stack_id | red first |
| `scripts/bench/tests/test_media_pin_public_unicast.py` | RFC1918 without override | red first; mocked resolver |
| `scripts/bench/tests/test_cluster_gate.py` | gate: every analyze job for a leg has reached a terminal outcome — success, or failure with `item_max_attempts` exhausted — and at least one succeeded; (a) all terminal + ≥1 success → ADMITS; (b) all terminal + zero successes → REFUSES; (c) non-terminal analyze in flight → REFUSES; missing cluster outcome → `export_leg` aborts | red first; **S1**, because `require_cluster_success` is an S1 symbol |
| `scripts/bench/tests/test_export_map_rg015.py` | fixture without `total` / `limit` / `offset` / `data_source` must not gain fabricated envelope fields from convenience derivations such as `len(payload)` | **[rg-015]** — red if `export_map` synthesises any of `limit`, `offset`, `total`, `data_source` instead of taking them from the upstream payload; **S1**, because `export_map` owns the preserve-envelope duty in S1 |
| `scripts/bench/__init__.py` | package marker | required for `uv run python -m scripts.bench.*` and documented `scripts.bench.*` import/test paths; without it the S1 tree is not an importable package |

#### S1 executable contracts (normative)

**(0) Export ownership — one symbol, and it lives where it is called from**

An earlier revision put `export_and_persist_leg` in S1's `driver.py` while assigning `export_map.py` and `export_leg` wholly to S2, then had S2 declare "S1 complete" as a dependency and assume the exports already existed. That is two names for one job on opposite sides of a slice boundary, and it made S1 unbuildable as written: [CF-7](#cf-7-score-credential-flow-pinned) requires `run` (S1) to persist every export, but the module that persists them was not scheduled until S2.

The pin: **`export_map.export_leg` is the only export symbol**, `export_map.py` is created in Slice 1 with its persist half, and Slice 2 extends the same module with the GT-mapping half. `export_and_persist_leg` does not exist. A module spanning two slices is fine and is stated here rather than discovered at implementation time; what is not fine is two symbols for one responsibility. `test_cluster_gate.py` consequently lands in **S1** (it tests `require_cluster_success`, an S1 symbol), not "S1 stub or S2".

**(a) Ingest wiring — media bytes + terminal ingest outcome**

Resolution order (per manifest entry):

1. Local file under `--images-dir` / `images_dir` + `entry.path` (sha256 verify when possible).
2. Else remote HTTPS URL from entry provenance / operator URL map — **CF-1 pin + public-unicast apply**.
3. Else `outcome=failed`, `error_code=media_unresolvable`.

Bytes are then POSTed via `RemoteSceneClient.analyze` multipart (no stack enroll API). **At the point analyze returns**, `ItemOutcomeStore` appends to `legs/<stack_id>/items.jsonl` an explicit **terminal ingest outcome** field for that media id — `success`, or the failure reason (`media_unresolvable`, `image_decode_failed`, analyze/transport failure code, etc.). Condition (i) of the accepted set is evaluated from this field on the roster alone. A media id with **no terminal ingest outcome recorded** is treated as a **failure**, not as a success — the accepted set fails closed on missing evidence.

**(b) Run-dir layout**

```text
benchmarks/results/crossbench-<stamp>/          # --out (repo-level; from app dir pass ../../benchmarks/results/crossbench-<stamp>/)
  run.json                    # stamp, CLI SHA, budgets, phase, license_banner
  stack_pair.json             # redacted copy of validated config (no secrets)
  manifest.sha                # sha256 of --manifest file bytes
  legs/<stack_id>/
    preflight.json            # PROV-01: profile, dim, stack identity, timestamps, response excerpts
    items.jsonl               # append-only per-item outcomes (see ground-truth §d)
    cluster_job.json          # clustering_job result payload
    exports/                  # all public exports needed for score (no creds later)
      media_identities.json
      clusters.json
      cluster_members.json
  score/                      # written by `score` (S2); absent until then
    accepted_set.json
    attrition.json
    frames.json
    report.html
```

**(c) Resume**

- `items.jsonl` is **append-only**. Latest record per `(manifest_media_id, phase)` wins when reading.
- On resume: skip items whose latest outcome is **terminal-success** for the phases already completed; **re-attempt** failures up to `item_max_attempts` (default **2**, config) while wall-clock budget remains.
- Cluster phase re-runs only if `cluster_job.json` is missing or non-success **and** the leg satisfies the same gate the first pass used — every analyze job for a leg has reached a **terminal** outcome — success, or failure with `item_max_attempts` exhausted — **and at least one succeeded** ([Workflow Principles](#workflow-principles)). Resume must not use a looser condition than the initial run, or a resumed run clusters on a partial leg that the first pass would have waited on.
- Export re-runs only if cluster success and export files incomplete.

**(d) Score / export credential flow**

Locked by [CF-7](#cf-7-score-credential-flow-pinned): `run` persists exports; `score` is offline on the run-dir.

**(e) `status` subcommand (kept in S1)**

- Reads `run.json` + each leg's `items.jsonl` (+ presence of `cluster_job.json` / `exports/`).
- Prints per-leg: counts by phase outcome, current phase estimate (`ingest|analyze|cluster|export|done|failed`), wall-clock elapsed if stamped.
- Exit 0 when parseable; non-zero if run-dir missing/corrupt. No network.

**(f) PROV-01 field inventory (single normative list — every other site references this section instead of re-listing)**

This is the **complete** [PROV-01] inventory. Partial restatements elsewhere are non-normative pointers only. Fields that disambiguate the **leg**: `stack_id`, `base_url`. Fields that disambiguate the **run**: `run_stamp`, `manifest.sha`, `cli_sha`, `harness_sha`, `bootstrap_seed` (when score has run). Compose project name is **not** in this inventory.

**Run-level** (written under the run-dir root — `run.json`, `manifest.sha`, `stack_pair.json`):
- `run_stamp` — crossbench output directory stamp / run identity
- `cli_sha` — CLI / bench package code SHA
- `harness_sha` — eval-harness code SHA
- `manifest.sha` — sha256 of the `--manifest` file bytes (corpus hash)
- `bootstrap_seed` — from stack-pair config (stamped into the score provenance block; required key)
- `license_banner` / budgets / phase as already required on `run.json`

**Per-leg** (`legs/<stack_id>/preflight.json` — written in S1 at preflight; refreshed if preflight re-runs into the same run-dir):
- `stack_id` — allowlist key (**leg** disambiguator)
- `base_url` — endpoint actually contacted (**leg** disambiguator)
- `expected_profile`, `expected_pgvector_dim`
- `resolved_profile`, `resolved_pgvector_dim` (model / dim identity for the leg)
- `opencv_major`, `opencv_major_source` (`operator_attested` \| `service_reported`)
- `checked_at`
- `ready_excerpt`, `health_detailed_excerpt` (redact secrets)

`opencv_major` is **required** and satisfies the [PROV-01 constraint](#constraints) via the [attested source](#opencv-major-source-attested-not-probed). Writing `preflight.json` without it is a preflight failure, not a partial write: a run whose provenance cannot distinguish a 4.x from a 5.x stack is exactly the silent-comparability failure the field exists to prevent.

**Per-item** (each `legs/<stack_id>/items.jsonl` record; see [media identity join](#d-media-identity-join)):
- `manifest_media_id`, `stack_media_id` (int)
- `image_width` (positive int), `image_height` (positive int) — Pillow-decoded at ingest by `ItemOutcomeStore` after `ImageOps.exif_transpose` so scoring converts prediction boxes without re-opening image files; reader fails closed with `image_dimensions_missing` when absent, non-integer, or ≤ 0
- `content_sha256` when ok
- `phase`, `outcome`, optional `error_code`
- **terminal ingest outcome** — explicit field written at the point analyze returns: `success` or the failure reason; condition (i) of the accepted set is read from this field alone. A media id with no terminal ingest outcome recorded is a **failure** (fail closed on missing evidence)

**Score provenance** (written by `score` under `score/` — never by `preflight`):
- `baseline_superset_checked` (bool) — stamped by `score` only: true only if `baseline_manifest_path` was set **and** the superset assert executed and passed; false if the path was unset or the assert was skipped. **Never written by `preflight`.**
- `zero_detection_media_count` (int) — accepted-set media present on the `items.jsonl` roster with zero export face rows (`pred_faces = 0`)
- `ingest_asymmetric_media` (int) — media present in one leg's `items.jsonl` but not the other (excluded from `accepted_set`)
- `attrition_ingest_analyze` (int) — manifest items excluded from `accepted_set` because condition (i) or (ii) failed on at least one leg (ingest/analyze terminal failure)
- `attrition_join` (int) — manifest items excluded from `accepted_set` because condition (iii) failed on at least one leg (join-phase / roster membership, including `ingest_asymmetric_media`)
- `bootstrap_seed`, `bootstrap_resamples`, `ci_level`, `resampling_unit` (and per-cell interval fields) as required by the [precision precondition](#precision-precondition-normative); when rule (a) under the resampling-unit pin splits any occasion, also `partial_occasions`

Report (S2) **consumes** these artifacts; does not re-call health endpoints.

**Stack-pair config shape (normative)**

```yaml
# example only — not a committed secret file
wall_clock_timeout_sec: 3600
job_poll_timeout_sec: 600
item_max_attempts: 2
accepted_set_floor: 0.90       # fraction of manifest entries; see the floor policy below
max_differential_attrition: 0.05
allow_private_source: false
images_dir: /path/to/corpus-root   # optional; --images-dir overrides when both are given
# statistical contract — see the precision precondition; all four keys are REQUIRED
head_to_head_delta: 0.10       # δ, declared before the run
bootstrap_seed: 20260729       # no default; an unset seed is a config error
primary_endpoint: detection_recall@frame_e2e/label_map_primary
secondary_endpoints:           # Holm-adjusted; a cell in neither list is DIAGNOSTIC
  - detection_precision@frame_e2e/label_map_primary
  - identification_recall@frame_e2e/label_map_primary
  - identification_precision@frame_e2e/label_map_primary
# optional: fail closed if --manifest bytes disagree
# manifest_sha256: "<64 hex>"
stacks:
  - stack_id: acx-dev-insightface
    role: insightface_judge
    base_url: https://dev.api.altcontext.com   # operator-local value
    expected_profile: insightface
    expected_pgvector_dim: 512
    opencv_major: 5            # REQUIRED operator attestation; no endpoint reports it
    api_key_env: ACX_BENCH_DEV_API_KEY
    tenant_id_env: ACX_BENCH_DEV_TENANT_ID
  - stack_id: acx-dev-fir
    role: face_pipeline_candidate
    base_url: https://fir.api.altcontext.com
    expected_profile: face_pipeline
    expected_pgvector_dim: 128
    opencv_major: 5
    api_key_env: ACX_BENCH_FIR_API_KEY
    tenant_id_env: ACX_BENCH_FIR_TENANT_ID
```

**Key schema (normative, [rg-008] — this list is the loader's contract; 23 keys: 15 root + 8 stack).** The loader rejects unknown keys, so every key referenced anywhere in this plan must appear here or the config fails closed on a key the plan itself told the operator to set. Two keys previously had exactly that defect: `images_dir` was referenced in prose but absent from the example, and `role` was in the example but absent from the loader's declared key list — under the reject-unknown-keys rule the shipped example would have failed its own loader.

| Scope | Key | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| root | `wall_clock_timeout_sec` | no | `3600` | [CF-4](#cf-4-bounded-runs) |
| root | `job_poll_timeout_sec` | no | `600` | [CF-4](#cf-4-bounded-runs) |
| root | `item_max_attempts` | no | `2` | resume retry bound |
| root | `accepted_set_floor` | no | `0.90` | float in **(0, 1)** = fraction of **manifest entries loaded for this run** (corpus denominator N — how much of the corpus must survive the three-condition accept); int **≥ 2** = absolute minimum accepted count; value `1` (int or float) is **rejected at load** (form only); integer floor > `\|manifest entries\|` fails at `run`/`score` after manifest load with **`accepted_set_floor_exceeds_corpus`** — see [floor policy](#floor-policy-normative) |
| root | `max_differential_attrition` | no | `0.05` | **float in closed range [0.0, 1.0]** — a **fraction** of `\|manifest\|` (not percentage points); compared at score time as `|one-sided-A − one-sided-B| / |manifest|`; value outside [0.0, 1.0] or non-numeric → load error **`max_differential_attrition_invalid`**; see [floor policy](#floor-policy-normative) |
| root | `allow_private_source` | no | `false` | CF-1 LAN override |
| root | `images_dir` | no | — | corpus root; CLI `--images-dir` wins when both are set |
| root | `manifest_sha256` | no | — | fail closed on manifest byte mismatch |
| root | `baseline_manifest_path` | no | — | optional path to a baseline/label manifest; when present, `run` loads it and calls `assert_baseline_superset(manifest_ids, baseline_ids)` before any media write; when absent, the assertion is skipped; `score` stamps `baseline_superset_checked` in the score provenance block (never in `preflight.json`) |
| root | `media_url_map_path` | no | — | optional operator URL map / corpus overlay; remote-resolution second step and the `test_media_pin_public_unicast.py` red-proof exercise this path |
| root | `head_to_head_delta` | **yes** | — | δ; no default, must be declared before the run |
| root | `bootstrap_seed` | **yes** | — | no default; unset is a config error ([PROV-05]) |
| root | `primary_endpoint` | **yes** | — | string; **exactly one** member of the legal endpoint set (below); must equal `detection_recall@frame_e2e/label_map_primary` (the pinned primary); violation → **`config_endpoint_invalid`** |
| root | `secondary_endpoints` | **yes** | — | list of **distinct** members of the legal endpoint set (below); may be empty, but the key must be present so "declared none" is distinguishable from "forgot to declare"; **must not** contain `primary_endpoint`; duplicates or unknown ids or overlap with primary → **`config_endpoint_invalid`** |
| root | `stacks` | **yes** | — | exactly two entries |
| stack | `stack_id` | **yes** | — | ∈ consumption-table allowlist |
| stack | `role` | **yes** | — | must equal the consumption table's **role** for that `stack_id` |
| stack | `base_url` | **yes** | — | absolute URL; **schemes** accepted: `http`, `https` only; trailing slash **normalized away**; **no path component** permitted after normalize (empty path or `/` only — query/fragment rejected); allowlist compared on **host only** (case-insensitive; default ports 80/443 not part of the identity; non-default port is allowed on the URL but is not an allowlist axis); host not in the consumption-table ingress identity → **`base_url_not_allowlisted`**; scheme/path/parse failure → **`base_url_invalid`** |
| stack | `expected_profile` | **yes** | — | compared at preflight |
| stack | `expected_pgvector_dim` | **yes** | — | compared at preflight |
| stack | `opencv_major` | **yes** | — | operator attestation; absent → `opencv_major_unattested` (see [OpenCV major source](#opencv-major-source-attested-not-probed)) |
| stack | `api_key_env` | **yes** | — | env **reference**, never the secret |
| stack | `tenant_id_env` | **yes** | — | env **reference**, never the id |

**Legal endpoint identifiers (closed set for `primary_endpoint` / `secondary_endpoints`).** Derived from the plan's own metric × frame × label-map grid; form `{metric}@{frame}/{label_map}` where:
- **metric** ∈ {`detection_recall`, `detection_precision`, `identification_recall`, `identification_precision`}
- **frame** ∈ {`frame_e2e`, `frame_fir5_native`}
- **label_map** ∈ {`label_map_primary`, `label_map_optimistic`}

That is sixteen legal strings. The pinned primary is the single string `detection_recall@frame_e2e/label_map_primary`. Any other string, a non-string, a non-list `secondary_endpoints`, a duplicate within `secondary_endpoints`, or `primary_endpoint` also appearing in `secondary_endpoints` fails load with **`config_endpoint_invalid`**.

**Deploy-ownership keys — reject by exact name (executable set).** The loader rejects **any** of the following keys, at root or under a stack entry, by **exact name** with error **`deploy_ownership_key_rejected`** (message routes the operator to FIR23-STACK). This set is the machine form of the ownership narrative above (compose / network / volumes / image tags / Caddy / systemd / secret rotation / DB volume lifecycle are FIR23-STACK-owned and must not appear in stack-pair config). Rejection is distinct from the generic unknown-key error, because the operator's intent is legible and the answer is "that field is not FIR-8's to hold." Asserted by `test_stack_pair_consumption.py` (one case per key, plus a control that an allowed key still loads).

| Exact key name | Ownership narrative it covers |
| --- | --- |
| `compose_project` | compose project name |
| `network` | compose / docker network |
| `volume_path` | DB / media volume path (singular) |
| `volumes` | volume map / list |
| `image_tag` | container image tag |
| `image` | container image reference |
| `caddyfile` | Caddy / ingress stanza |
| `systemd_unit` | systemd unit name |
| `db_volume` | DB volume lifecycle |
| `secret_rotation` | secret-rotation config |

The [consumption-table rule](#fir23-stack-consumption-table-pinned) and this list must not disagree: if a key claims deploy ownership, it is either in this table (rejected by name) or it is not a FIR-8 config key at all.

#### Floor policy (normative)

**Slice ownership (this section spans two slices — stated here, not discovered later).** The *config surface* — parsing and load-time validation of `accepted_set_floor` and `max_differential_attrition`, including the fraction-vs-absolute form check — is **Slice 1** (`stack_pair.py`, [rg-008]). The *resolution and enforcement* — `resolved_floor_count`, the DIRECTIONAL downgrade, `differential_attrition_exceeded`, and the write-diagnostics-then-refuse ordering — is **Slice 2** (`score_report.py`). The section lives under Slice 1 because that is where the keys are declared; `test_attrition_floor.py` is an S2 test, and S1 carries only a load-time validation case (a floor of `1`, `1.5`, `-1`, or a non-numeric fails at load, not at score time).

The default is a **fraction**, not the corpus size. An earlier revision defaulted `accepted_set_floor` to the manifest entry count, i.e. **zero tolerated attrition**. That made the plan's headline deliverable unreachable: on a live 150-image run against two independent HTTP stacks, one transient ingest or analyze failure on **either** leg downgrades **every** P/R cell to DIRECTIONAL, so no gate-eligible head-to-head number is obtainable and the deliverable in [Target Outcome](#target-outcome) item 4 cannot be produced. The floor's job is not to detect that a run was imperfect — the attrition table already does that, in full, per phase.

- `accepted_set_floor` accepts a **float in the open interval (0, 1)** read as a **fraction of the corpus** — how much of the loaded manifest must survive the three-condition accept — or an **int ≥ 2** read as an **absolute minimum accepted count**. Default **0.90**. The value **`1` (int or float) is rejected at load** with an explicit message naming both accepted forms (`float in (0, 1)` or `int ≥ 2`) — `1` sits at the closed top of the old fraction range and below the absolute range, so it is unimplementable, and a floor of 1 makes the bootstrap meaningless. **`stack_pair` validates form only** (type and range: float in (0, 1) or int ≥ 2; reject `1`, non-numeric, out-of-range). **Corpus-relative validation is deferred to manifest load** at `run`/`score` time — that split is deliberate because `stack_pair` does not load the manifest. Immediately after the manifest loads, an integer `accepted_set_floor` greater than `|manifest entries|` fails closed with **`accepted_set_floor_exceeds_corpus`** (an absolute floor larger than the corpus would make every run DIRECTIONAL for a config error, not a data property).
- **Resolve before comparing.** `score` converts the configured value to an item count **once**: for a fraction, `resolved_floor_count = max(2, ceil(accepted_set_floor × N))` where **`N = |manifest entries loaded for this run|`** (the corpus denominator, **not** `|accepted_set|`); for an absolute, `resolved_floor_count = int(accepted_set_floor)` (already ≥ 2 by the load rule — an absolute minimum accepted count). The `max(2, ·)` clamp means **no configuration can resolve below 2**. Persist two keys only: **`floor_config`** holds the raw configured value (integer or fraction); **`resolved_floor_count`** holds the integer the comparison actually uses. Stamp `floor_config`, `resolved_floor_count`, `accepted_set_size`, and `manifest_entry_count` (= N) in `accepted_set.json` / provenance so the comparison is reconstructible from the artifact alone. Every downstream comparison — the tier table row, `resolved_floor_count`, this section — is against `resolved_floor_count`, an item count: **DIRECTIONAL** when `|accepted_set| < resolved_floor_count` (reason `accepted_set_below_floor`). There is no third persisted name for the floor.
- **Worked example (fractional floor):**
  - manifest N = 150, `accepted_set_floor = 0.90` → `resolved_floor_count = max(2, ceil(135.0)) = 135`
  - `|accepted_set| = 135` → `135 < 135` is false → floor **not** tripped
  - `|accepted_set| = 134` → `134 < 135` is true → **DIRECTIONAL**, reason `accepted_set_below_floor`
- **There is no pre-computable "power floor", and v6.3's was fiction.** The retired revision had `score` compute a floor "required by the power precondition" and fail closed with `floor_below_power_floor`. No such N exists a priori: the interval width depends on the between-leg disagreement pattern, which is unknown until the run completes. That error code is **removed**. The floor is an operator convenience that bounds attrition; the binding statistical gate is the [precision precondition](#precision-precondition-normative), evaluated on the interval actually obtained. A run may clear the floor and still yield only DIRECTIONAL cells — that is the correct and expected outcome when the corpus cannot resolve δ, not a configuration error.
- **Differential attrition is a separate and stricter check.** Size loss shared by both legs shrinks precision; loss concentrated on **one** leg is a *bias* — the surviving accepted set is enriched for media the weaker stack happens to handle, which flatters exactly the leg that failed. One-sided success is counted with the **same three-condition predicate** the scorer uses for accepted-set membership ((i) terminal-success ingest, (ii) terminal-success analyze with int `stack_media_id`, (iii) presence on that leg's `items.jsonl` roster) — a bias gate that used a looser two-condition predicate could disagree with the scoring denominator. `score` fails closed with `differential_attrition_exceeded` when |one-sided-A − one-sided-B| / |manifest| exceeds `max_differential_attrition` (default **0.05**), regardless of accepted-set size. A run can clear the floor and still be unscoreable on this ground.
- **Fail closed on the *metric*, not on the *report* — ordering is normative.** Aborting `score` outright would destroy the artifact that diagnoses the abort and would contradict this plan's own rule that attrition is [reported, not silently dropped](#constraints): the operator would be told their run is biased and handed nothing showing *where*. The order is fixed and stated identically in the [cell → tier table](#cell--tier-assignment-normative) and in `test_attrition_floor.py`: (1) write the accepted-set and attrition artifacts to disk **FIRST**; (2) then emit **NO** precision/recall cells; (3) then exit non-zero with `differential_attrition_exceeded`. Not DIRECTIONAL cells either — the defect is bias and a biased number is not made safe by a weaker label. Stamp `differential_attrition_exceeded` in the report header. Nothing is dropped, nothing biased is published, and the diagnosis survives the failure. The same ordering rule applies to any future scoring abort: diagnostics are written before the refusal, never after it.

**Proof**

- `uv run --extra dev pytest scripts/bench/tests/test_preflight.py scripts/bench/tests/test_corpus_superset.py scripts/bench/tests/test_resume.py scripts/bench/tests/test_stack_pair_consumption.py scripts/bench/tests/test_media_pin_public_unicast.py scripts/bench/tests/test_cluster_gate.py scripts/bench/tests/test_export_map_rg015.py -q` green (from `apps/prototype-description-service`).
- Red-proofs:
  1. Mock `/ready` with database check `detail: "reachable; pgvector_dimension=128"` on the insightface endpoint (expected 512) → preflight raises `profile_or_dim_drift`; strip the assertion → test fails.
  2. Mock `/health/detailed` without `model_cache.profile` → `profile_or_dim_drift`; mock 401 → `preflight_auth_failed`.
  3. Baseline partial set → test fails if superset check deleted.
  4. Resume re-POSTs terminal-success ids if outcome store ignored.
  5. Stack-pair with foreign `stack_id` or base_url outside allowlist identity → load fails; delete the check → test fails.
  6. Mock DNS/resolver returning `10.0.0.5` for a remote media URL with `allow_private_source=false` → ingest refuses; strip enforcement → test fails.
  7. Stack entry without `opencv_major` → preflight raises `opencv_major_unattested` and writes **no** `preflight.json`; delete the required-field check → test fails. A second case asserts the bench package imports no `cv2` (see [OpenCV major source](#opencv-major-source-attested-not-probed)).
  8. `accepted_set_floor` load forms: value `1` (int or float) is **rejected at load** with a message naming both accepted forms; `0.9` (fraction) and `2` (absolute) are **accepted**; `1.5`, `-1`, and `"ninety"` also fail at load. A missing `bootstrap_seed`, `head_to_head_delta`, `primary_endpoint`, or `secondary_endpoints` key likewise fails at load ([rg-008]). After manifest load, an integer floor greater than `|manifest entries|` fails closed with `accepted_set_floor_exceeds_corpus`.
  9. Cluster gate ([TEST-06], `test_cluster_gate.py`) — three fixtured legs, not one exhausted-retry case: (a) all analyze terminal with ≥1 success → gate **ADMITS** and clustering runs; (b) all analyze terminal, zero successes → gate **REFUSES** (no cluster, no export, `cluster_gate_refused` in `legs/<stack_id>/leg_outcome.json`); (c) a non-terminal analyze still in flight → gate **REFUSES**. Loosen the gate to "any analyze attempted" or drop the ≥1-success conjunct → (b) or (c) fails the discrimination.
  10. [rg-015] (`test_export_map_rg015.py`) — `export_map` synthesises any of `limit`, `offset`, `total`, `data_source` from a convenience derivation such as `len(payload)` instead of taking it from the upstream payload → test goes red.

**Dependencies**: FIR23-STACK not required for unit tests (mocked). Live `run` requires both stacks up.

---

### Slice 2: Export + score via FIR-5 pure metrics

**Goal**: Consume exports already persisted by `run` (offline), map GT + exports into `ImageDetection` / `ImageIdentities` with label-space mapping, score detection P/R + identification P/R under sampling frames × label-map frames, emit tier-labeled head-to-head report under `benchmarks/results/crossbench-*/` with accepted-set + attrition artifacts.

**Files / functions**

| Module | Symbols | Responsibility |
| --- | --- | --- |
| `scripts/bench/score.py` | IoU / assignment helpers as needed | Matching threshold is `IOU_MATCH_THRESHOLD` from `scripts/eval_harness/face_assignment.py:29` — do **not** re-declare a second constant |
| `scripts/bench/export_map.py` (**extended**, created in S1) | S2 half only: `map_cluster_labels_primary(...)`, `map_cluster_labels_optimistic(...)`, `to_face_metric_inputs(export, manifest, join, label_map, frame: Literal["native", "e2e"]) -> tuple[list[ImageDetection], list[ImageIdentities]]`, `match_detection_boxes(...)` | `export_leg` / `require_cluster_success` / `load_leg_exports` already exist from S1 — see the [export-ownership pin](#s1-executable-contracts-normative). No embedding/landmark requirement; **all** `ImageDetection`/`ImageIdentities` construction here or in `score_report` — never inside FIR-5; uses `IOU_MATCH_THRESHOLD` from `face_assignment.py:29`; `frame` selects identification-row construction (see [End-to-end scoring frames](#end-to-end-scoring-frames)) |
| `scripts/bench/score_report.py` | `CrossbenchTier` enum, `SAMPLING_FRAME_*`, `LABEL_MAP_*`, `compute_accepted_set(run_dir) -> AcceptedSet`, `write_accepted_set(...)`, `write_attrition(...)`, `score_head_to_head(run_dir) -> Path`, `build_dual_frames(...)`, `assign_tier(cell, ctx) -> CrossbenchTier` | Call **only** `detection_pr` / `identification_pr` with pinned signatures; tier rules; offline on run-dir; uses `IOU_MATCH_THRESHOLD` from `face_assignment.py:29` |
| `scripts/bench/cross_stack_bench.py` | subcommand `score` | Wire offline score path (**no credentials**) |
| `scripts/bench/tests/test_e2e_frame.py` | detector-miss dual-frame pin; whole-image zero-export accepted media stays in denominator on both frames | required |
| `scripts/bench/tests/test_e2e_mocked.py` | dual fake clients → report artifacts | one mocked E2E |
| `scripts/bench/tests/test_detection_localization.py` | pinned GREEN/RED geometry (1000×1000; GT centre `0.5/0.5/0.2/0.2`; GREEN `{400,400,200,200}`; RED translation `{700,400,200,200}`; RED centre-in-box `{100,100,800,800}`) | **[TEST-15]** — GREEN `matched_faces = 1`; translation RED `matched_faces = 0` + one FP + one FN; centre-in-box RED IoU 0.0625 → `matched_faces = 0`; count-only perfect on translation RED |
| `scripts/bench/tests/test_precision_precondition.py` | bootstrap half-width / Holm / resampling-unit gates | required |
| `scripts/bench/tests/test_manifest_version_seam.py` | exhaustiveness / `stranger_faces` + eligibility ceiling on `v2_boxed_detection.json` | required |
| `scripts/bench/tests/test_attrition_floor.py` | floor forms (reject `1`; accept `0.9` / `2`); resolved item-count floor; on `differential_attrition_exceeded`: artifacts-exist AND non-zero-exit AND no-P/R-cells | required |
| `scripts/eval_harness/face_metrics.py` | optional `ImageDetection.matched_faces` + clamped `TP/FP/FN` branch + bounds check | one of **two** edits outside `scripts/bench/` (the other is `scene/tests/test_eval_harness_face_metrics.py`); default `None` preserves current behaviour |

**Report must include**

- Both legs' **detection P/R** and **identification P/R** under **both sampling frames** (`frame_fir5_native`, `frame_e2e`) and **both label-map frames** (`label_map_primary`, `label_map_optimistic`) (null where labels absent — honest nulls, not `0.0` purity invention).
- Cascade-honest e2e treatment ([EVAL-16]): detector miss → identification miss on that face in `frame_e2e`.
- Fixed denominators via `score/accepted_set.json` + attrition table ([EVAL-19 operationalized](#eval-19-operationalized-accepted-set)).
- Provenance block ([PROV-01]) from the full inventory in [PROV-01 field inventory](#s1-executable-contracts-normative) (per-leg `preflight.json` + run-level + per-item fields + score provenance including `baseline_superset_checked`, `zero_detection_media_count`, `ingest_asymmetric_media`).
- `license_notice` / `license_banner` for the insightface leg on intermediate JSON and HTML.
- Per-cell `CrossbenchTier` from the assignment table (not attributed to FIR-5).

**Proof**

```bash
# from apps/prototype-description-service
uv run --extra dev pytest scripts/bench/tests/test_e2e_frame.py scripts/bench/tests/test_e2e_mocked.py scripts/bench/tests/test_detection_localization.py scripts/bench/tests/test_precision_precondition.py scripts/bench/tests/test_manifest_version_seam.py scripts/bench/tests/test_attrition_floor.py -q
uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py
```

- Mocked E2E green; dual-frame test green; harness `matched_faces` bounds + optional-last proofs green. (Cluster gate and `test_export_map_rg015.py` are S1 proofs — not re-run as S2 gates.)
- Red-proof: strip provenance consumer → test asserting preflight keys fails; remove FN injection → e2e frame test fails; zero-export accepted media dropped from denominator → dual-frame test fails; pass raw unmapped `cluster_label` as `predicted` without mapping → identification unit test fails; mutate accepted set differently per leg → score assert fails; drop IoU threshold → localization translation RED matches and fails; centre-in-box fallback without IoU → centre-in-box RED matches and fails; omit case (ii) from the bounds table → a `<`-instead-of-`<=` bounds check ships undetected.

**Dependencies**: S1 complete. FIR-5 pure metrics on main (already). **Not** FIR-11: S2 is implementable and green against today's v2 harness — loads via `load_manifest`, detection tests against `v2_boxed_detection.json`; FIR-11 Slice 2 is not required for any code path or fixture and remains relevant only as a later source of a larger boxed production corpus.

---

### Slice 3: Runbook + teardown

**Goal**: Operator-facing runbook covering license, preflight, run, score, and stack-scoped teardown via FIR23-STACK; verification commands copy-pasteable ([rg-006]).

**Files**

| File | Change |
| --- | --- |
| `docs/runbooks/fir-8-cross-stack-bench.md` | Full operator path (below) |
| `apps/prototype-description-service/scripts/bench/README.md` | One-page pointer to runbook + CLI help |

**Runbook sections (normative outline)**

1. **Purpose + license posture** — insightface stack INTERNAL BENCH ONLY; never commercial/user-facing; outputs not for training.
2. **Prerequisites** — FIR23-STACK `acx-dev-fir` up; dev stack up; `ACX_BENCH_*` API keys + tenant ids for both scratch/bench tenants; corpus path; package root / PYTHONPATH note.
3. **Preflight** — exact `uv run python -m scripts.bench.cross_stack_bench preflight --config stack-pair.yaml` (from `apps/prototype-description-service`).
4. **Run** — `uv run python -m scripts.bench.cross_stack_bench run --config stack-pair.yaml --manifest <manifest.json> --images-dir <corpus-root> --out ../../benchmarks/results/crossbench-<stamp>/` (from `apps/prototype-description-service`; `--out` resolves to repository-level `benchmarks/results/`; ingest → analyze → cluster → export persist).
5. **Status** — `uv run python -m scripts.bench.cross_stack_bench status --run-dir ../../benchmarks/results/crossbench-<stamp>/` (from `apps/prototype-description-service`; optional; per-leg progress + phase).
6. **Score** — `uv run python -m scripts.bench.cross_stack_bench score --run-dir ../../benchmarks/results/crossbench-<stamp>/` (from `apps/prototype-description-service`; offline; fails if cluster phase missing; writes `score/accepted_set.json` + report).
7. **Teardown** — **only** FIR23-STACK's documented stack-scoped DB reset for `acx-dev-fir` (and optional dev bench-tenant cleanup). Placeholder: `See FIR23-STACK runbook §reset` until that doc's command is stable — **do not invent** `DROP DATABASE` one-liners here that disagree with FIR23-STACK.
8. **Failure routing** — stack health / dim wrong in compose → FIR23-STACK; CLI logic / scoring → FIR-8; embedding-export needs → optional upstream task (not FIR-8).
9. **Verification checklist** — both preflights green; report path exists; both frames present; license_notice present; stacks reset.

**Proof**

- Runbook paths resolve (`test` or `make` doc link check if repo has one; else manual path exists check in S3).
- Commands match CLI `--help` (no broken copy-paste — [rg-006]).

**Dependencies**: S1–S2 CLI surface stable; FIR23-STACK reset command available or explicitly stubbed with "blocked on FIR23-STACK" note.

---

## Lane Decomposition

Single-lane work. No multi-agent lane split required.

---

## Consolidated Checklist

> Checklist describes **work**, not finding status. Query open findings via handoff DB.

### Context and Ownership

- [x] Loaded this plan, eval_harness remote client, health probes, media identity export keys, 001 schema table list, FIR23-STACK endpoint/reset docs.
- [x] Confirmed no recognition-service files in the intended diff.
- [x] FIR23-STACK dependency recorded as BLOCKING for live runs (unit tests unblocked).
- [x] Package root pinned: `apps/prototype-description-service/scripts/bench/`.

### Checklist for Slice 1: Bench CLI skeleton

- [x] Package under `apps/prototype-description-service/scripts/bench/` + `cross_stack_bench.py` subcommands `preflight` / `run` / `status`
- [x] `StackPairConfig` validates the full [key schema](#s1-executable-contracts-normative) at load ([rg-008]) against the FIR23-STACK consumption table (dev: insightface/512; fir: face_pipeline/128; refuse unknown stacks / foreign base URLs / deploy-ownership keys)
- [x] Preflight uses real `/ready` + authenticated `/health/detailed` contracts; stable codes; `opencv_major` required (`opencv_major_unattested` when absent); writes per-leg `preflight.json` (PROV-01) with flat `opencv_major` / `opencv_major_source`
- [x] Manifest via `load_manifest` (`--manifest` + `--images-dir`); `manifest.sha` written
- [x] Flow: media resolve (local then remote+CF-1 pin) → analyze → cluster (every analyze job for a leg has reached a terminal outcome — success, or failure with `item_max_attempts` exhausted — and at least one succeeded) → **S1 `export_map` symbols only** (`export_leg` / `require_cluster_success` / `load_leg_exports` — persist; no GT mapping); zero analyze successes → no cluster/export, `cluster_gate_refused` in `legs/<stack_id>/leg_outcome.json`; run-dir tree as specified; package marker `scripts/bench/__init__.py` present
- [x] Terminal ingest outcome written to `items.jsonl` at analyze return (`success` or failure reason); missing outcome = failure for condition (i) (fail closed)
- [x] When config key `baseline_manifest_path` is present, baseline superset blocker (`assert_baseline_superset(manifest_ids, baseline_ids)`) asserted against the **manifest** set at `run` start, before any media write; when absent, skipped; `score` stamps `baseline_superset_checked` in the score provenance block (never written by `preflight`); public-unicast default on remote fetches; optional `media_url_map_path` for operator URL map / corpus overlay
- [x] Append-only `items.jsonl` resume (skip terminal-success; bounded retry on failures); each ok record carries int `stack_media_id`, `image_width`, `image_height`, terminal ingest outcome
- [x] `status` reads run.json + items.jsonl (no network)
- [x] Wall-clock + job-poll budgets enforced in CLI
- [x] Named-stack allowlist guard before writes
- [x] Unit tests: preflight, superset, resume, consumption-table, public-unicast, cluster-gate, **rg-015 (`test_export_map_rg015.py`)** — each observed red first
- [x] Handoff decision for S1 with verification commands

### Checklist for Slice 2: Export + score

- [x] Score offline on run-dir only (exports already persisted by S1; no credentials)
- [x] Accepted set = ingest + analyze + int `stack_media_id` + presence on both legs' `items.jsonl` rosters, computed once; roster-present + zero export rows = zero detections (`pred_faces = 0`, `zero_detection_media_count`); one-leg roster only = `ingest_asymmetric_media`; export row absent from roster → `export_media_not_in_roster`; both join sides are ints with no coercion; primary + optimistic label-space mapping
- [x] **S2 `export_map` symbols only** (`map_cluster_labels_primary` / `map_cluster_labels_optimistic` / `to_face_metric_inputs(..., frame: Literal["native", "e2e"])` / `match_detection_boxes`); two frame calls; detection rows identical across frames, identification rows differ; S1 persist symbols already exist — not re-owned; mapper preserves upstream envelope fields already written by S1 ([rg-015]); no embedding/landmark requirement
- [x] FIR-5 pure `detection_pr` / `identification_pr` only on constructed `ImageDetection` / `ImageIdentities`; the harness edits are the optional-with-default `matched_faces` field (added last) and `scene/tests/test_eval_harness_face_metrics.py` bounds + optional-last assertions; `report.py` is READ, NOT EDITED
- [x] Dual sampling frames + dual label-map frames side-by-side; **`frame_e2e` pinned as the sole CONFIRMATORY sampling frame** (primary endpoint uses `e2e`; native identification is scored only on IoU-matched faces — predicted and labeled names plus stranger counts come from matched boxes, not the full media-level mapper)
- [x] `score/accepted_set.json` + attrition table ([EVAL-19]); `CrossbenchTier` cell rules applied first-match-wins
- [x] Detection P/R is **IoU-matched**; count-only retained as a DIAGNOSTIC companion; [TEST-15] pinned GREEN/RED geometry red-proof observed red first (translation + centre-in-box/containment cases)
- [x] Precision precondition implemented: declared δ, image-level cluster bootstrap, equal-tailed 95% percentile interval, `ci_half_width` stamped per cell on the 0..1 fraction scale, half-width ≤ δ/2, Holm across declared secondaries (empty list stamps empty family); partial-occasion resampling rules (a)–(c) with `partial_occasions` / mixed `resampling_unit`; media-vs-occasion discrimination fixture
- [x] Floor policy: `floor_config` = raw configured value; `resolved_floor_count = max(2, ceil(accepted_set_floor × N))` with `N = |manifest entries|`; stamps `floor_config`, `resolved_floor_count`, `accepted_set_size`, `manifest_entry_count`; integer floor > N → `accepted_set_floor_exceeds_corpus` at manifest load; `differential_attrition_exceeded` order: (1) write accepted-set + attrition artifacts FIRST; (2) emit NO P/R cells; (3) exit non-zero with `differential_attrition_exceeded`; provenance stamps `attrition_ingest_analyze` and `attrition_join`
- [x] Detection exhaustiveness gated by `require_detection_exhaustiveness` on `load_bench_manifest`; `v2_boxed_detection.json` loaded with the flag `True`; no module under `scripts/bench/` derives a face count by subtracting `len(present_identities)` from `face_count` (`report.py:454-461` retains the legacy form and is out of scope)
- [x] Report under `benchmarks/results/crossbench-*/` with preflight provenance (incl. `opencv_major` + its source), cascade honesty, license banner, tier labels, and the exhaustiveness eligibility ceiling
- [x] Mocked E2E + dual-frame (partial miss + whole-image zero-export) + localization + `test_precision_precondition` + exhaustiveness + attrition tests green (cluster gate and rg-015 are S1); harness edit proofs green via `uv run --extra dev pytest scene/tests/test_eval_harness_face_metrics.py` from `apps/prototype-description-service`
- [x] Handoff decision for S2

### Checklist for Slice 3: Runbook + teardown

- [x] `docs/runbooks/fir-8-cross-stack-bench.md` complete per outline
- [x] License posture explicit; insightface non-exposure rule explicit
- [x] Teardown cites FIR23-STACK reset only
- [x] Failure routing table (stack gap → FIR23-STACK; CLI → FIR-8; embedding diagnostic → optional upstream)
- [x] Commands match CLI help ([rg-006]); package root / import path documented
- [x] Handoff decision for S3 / task close path prepared

## Review Readiness

- [x] No recognition-service or deploy-YAML changes slipped into the branch. The two expected offline-harness edits (`face_metrics.py`, `test_eval_harness_face_metrics.py`) are present and are the **only** files outside `scripts/bench/`; a third such file is a review stop.
- [x] Boundary adapters do not invent pagination/provenance metadata ([rg-015]).
- [x] Preflight field claims match `register_health_probes` + `health.py` (no invented top-level dim fields).
- [x] Live run path blocked in docs until FIR23-STACK delivers `acx-dev-fir` (not silently mocked as success).
- [x] Handoff decisions record verification + dependency status.
- [x] Review findings recorded in MCP only (never pasted into this plan).

## Stretch Goals

- [ ] Optional HTML index linking multiple historical crossbench runs.
- [ ] Prometheus/log-free local progress TUI — only if it does not expand scope past one slice.
- [ ] Optional upstream embedding-export diagnostic (separate service task) if purity sweeps become required later.

## Success Criteria

- [x] Operator can preflight + run + score a corpus against **both** stacks with **zero** recognition-service code changes in the FIR-8 diff (two offline-harness files are in scope and enumerated; see [Target Outcome](#target-outcome) item 6).
- [x] S1 and S2 are implementable and green against **today's** v2 harness — no FIR-8 step calls a symbol FIR-11 has not yet created; detection fixture is `v2_boxed_detection.json` (`manifest_version: 2`); no alternate manifest schema, no `load_legacy_manifest`.
- [x] Preflight fails closed on dimension or profile drift / auth failure / missing endpoints / unattested `opencv_major` with the codes in the [stable error codes table](#stable-error-codes-normative).
- [x] Cluster phase runs per leg; export gated on success.
- [x] Scoring uses public bbox/cluster metadata + manifest GT + label mapping → detection P/R + identification P/R; dual sampling and label-map frames present, with `frame_e2e` + `label_map_primary` pinned as the only CONFIRMATORY combination.
- [x] Detection P/R is localization-aware (IoU-matched), and the [TEST-15] pinned GREEN/RED geometry fixtures (translation + centre-in-box/containment) prove the metric can go red under an IoU-only predicate.
- [x] No cell reaches CONFIRMATORY without a stamped `ci_half_width ≤ head_to_head_delta / 2` from the image-level cluster bootstrap on the endpoint's scoring population (`accepted_set` for identification/primary, `detection_scoring_set` for detection).
- [x] The head-to-head gate number is explicitly **withheld** until a production corpus passes FIR-8's own exhaustiveness assertion (`face_count == len(face_boxes)` on detection-scoring entries); a box-less production run ships as a **DIRECTIONAL** orchestration dry run (reason `detection_exhaustiveness_unasserted`) and says so in the artifact. FIR-11 Slice 2 may later supply a larger boxed corpus but is not required for any FIR-8 code path.
- [x] Superset / partial-intersection blocker enforced.
- [x] Resume does not reprocess terminal-success items; bounded retry on failures.
- [x] Head-to-head report exists under `benchmarks/results/crossbench-*/` with EVAL-16 / EVAL-19 (`accepted_set.json`) and insightface license banner; `score` refuses a run-dir whose legs lack `preflight.json` (PROV-01).
- [x] Runbook forbids commercial exposure of the insightface stack and points teardown at FIR23-STACK.
- [x] v5 in-service vehicle explicitly superseded (decision #2951; history at `bc97ff4b`).
- [x] Single package root `apps/prototype-description-service/scripts/bench/` documented and used by tests.

## Residual risks (pinned)

| Risk | Residual | Mitigation |
| --- | --- | --- |
| FIR23-STACK delayed | Live E2E blocked | Unit/mocked path still merges; live run is operator gate |
| Health payload shape differs across deploys | Preflight false fail/pass | Pin field names to real `/ready` + `/health/detailed` contracts; fail closed on missing fields |
| Public-unicast pin vs LAN media store | Operator needs private fetch | Explicit `allow_private_source` only; documented residual; constrains CLI outbound fetches only |
| Production-shaped guard without DB counts API | Weaker than v5 marker rail | Named stack allowlist + operator attestation; escalate if FIR23-STACK adds a count diagnostic |
| Insightface NC misuse | License | Runbook + report `license_notice`; stack must not sit on product ingress |
| No public embeddings | Purity sweeps impossible on cross-stack path | Explicit OOS; optional upstream diagnostic ask |
| **`opencv_major` is operator-attested, not service-reported** | A wrong attestation produces a confident-looking but false provenance stamp — the exact silent-comparability failure the field exists to prevent, now merely relocated from absent to unverified | Required field, fail closed when absent, `opencv_major_source: operator_attested` rendered in the report; upstream ask filed for `model_cache.opencv_version`. **This is a declared weak link, not a solved problem.** OpenCV major-version drift between legs (`opencv_major_drift`) is not detectable until the upstream model-cache payload carries a version field; until then a drifted pair is scored as if matched — no reserved code sits in the stable error-code table for an unreachable path. |
| **Golden150 cannot power a small head-to-head gap** | Even at full corpus, the image-level bootstrap interval on Δ may stay wider than δ, so the honest output is "no resolvable difference" rather than a winner | Precision precondition fails such cells closed to DIRECTIONAL rather than reporting them as gate-eligible. If the operator needs a resolvable answer at δ = 10pp, the corpus must grow — that is a **corpus decision, not a scoring-code decision**, and FIR-8 must not paper over it |
| **Detection FP eligibility depends on a boxed exhaustive corpus** | FIR-8 can be fully implemented and merged while its headline number stays unavailable until production media carry complete `face_boxes` | Exhaustiveness is FIR-8's own assertion (not an FIR-11 flag); detection unit tests use `v2_boxed_detection.json`; non-exhaustive detection cells are **DIRECTIONAL** with reason `detection_exhaustiveness_unasserted`. FIR-11 Slice 2 may later supply a larger boxed corpus but is not a code-path dependency. Do **not** let a box-less DIRECTIONAL number get quoted as the head-to-head result |
| **IoU threshold is a single fixed 0.5** | A stack whose boxes are systematically tighter or looser than GT is penalised by the threshold, not by its detection quality | Matching uses existing `IOU_MATCH_THRESHOLD` (0.5) at `scripts/eval_harness/face_assignment.py:29` (detection pin and optimistic label map share that one threshold — do not re-declare). Report the matched-vs-count gap per leg so a threshold artifact is visible as a *both-legs* shift; a sweep over IoU is a stretch goal, not a gate input |

---

## Canon citations (index)

| ID | Use in this task |
| --- | --- |
| EMB-01 / IDX-02 | One vector space per (modality, model); isolated stacks |
| EVAL-16 | Cascade honesty in head-to-head (e2e frame) |
| EVAL-19 | Fixed denominators = accepted set (`score/accepted_set.json`) + attrition |
| PROV-01 | Full field inventory (leg + run + per-item) — see [PROV-01 field inventory](#s1-executable-contracts-normative) |
| RLSE-05 / SERVE-03 | Insightface internal-bench only |
| rg-008 | Stack-pair config validated at load against consumption table |
| rg-015 | No invented envelope metadata |
| rg-006 | Documented commands run as written |
| DIAG-08 | Live/strategy bench ≠ Golden-150 substitute (corpus still explicit; do not re-host Golden as only path) |
| Heuristics canon v0.12.3 | Governing revision |
| Distilled: `janus-benchmark-c.md`, `handbook-face-recognition.md` | Cascade / face-eval discipline |
