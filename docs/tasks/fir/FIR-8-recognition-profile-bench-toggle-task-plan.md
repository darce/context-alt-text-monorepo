# FIR-8. Cross-stack face-pipeline bench orchestration

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok (docs-only plan authoring)
> - **Plan version**: v6.6 — **changelog (v6.5→v6.6, validators / commands / mechanical sweep)**: operator commands prefixed with `uv run` and `--out`/`--run-dir` resolved to repository-level `benchmarks/`; load-time contracts pinned for `base_url`, `primary_endpoint`/`secondary_endpoints`, and `max_differential_attrition`; `opencv_major` / `opencv_major_source` flattened with `opencv_major_unattested` as the sole reachable failure path and `opencv_major_drift` reserved; deploy-ownership reject keys enumerated by exact name; package-bootstrap rows reconciled; `export_map` S1/S2 symbol split made exclusive; Files-to-Change completeness confirmed (`test_eval_harness_face_metrics.py`, `report.py` read-not-edited, `v2_boxed_detection.json`, `test_cluster_gate.py`); version stamps to v6.6; retired statistical vocabulary / `annotation_mode` / `manifest_loader_unavailable` survivors swept; S2 checklist `power` renamed to `test_precision_precondition`. Carries forward the v6.5 corrections: normalized-centre GT + absolute-pixel predictions into normalized top-left scoring space; v2 detection fixture replacing v3/`annotation_mode` (S2 decoupled from FIR-11); capability-detection loader rule and `manifest_loader_unavailable` deleted; optional config keys `baseline_manifest_path` + `media_url_map_path`; `stack_media_id` as int; accepted-set three-condition propagation; cluster-gate move to S1 completed; `head_to_head_delta` and `accepted_set_floor` contracts; attrition ordering. — **changelog (v6.5 structural decoupling, pass 1)**: coordinate convention rewritten to real GT (normalized centre `FaceBox`) + absolute-pixel predictions, both converted to normalized top-left scoring space; `items.jsonl` persists `image_width`/`image_height`; `box_convention_unknown` no longer fires on normalized/centre-form boxes; `BOX_IOU_MATCH = 0.5` introduced as a **new** constant sole-declared in `scripts/bench/score.py`; detection fixture renamed to `v2_boxed_detection.json` (`manifest_version: 2`); all `annotation_mode` / v3 / capability-detection loader branching deleted (no unavailable-loader error code) — FIR-8 loads via `load_manifest` against v2, full stop; exhaustiveness is FIR-8's own `face_count == len(face_boxes)` assertion (`gt_box_count_mismatch`); FIR-11 Slice 2 decoupled from every S1/S2 code path and fixture (relevant only as a later larger boxed corpus); optional config keys `baseline_manifest_path` and `media_url_map_path` added (schema 21 → 23 keys); `stack_media_id` is int with int-to-int join and no coercion; join failure redefined as export-side absence. — **changelog (v6.4→v6.5, sequencing corrections; the 12 slice-ordering findings the v6.4 pass did not touch)**: export ownership pinned to a single symbol `export_map.export_leg` created in S1 where it is called from (`export_and_persist_leg` never existed), with `test_cluster_gate.py` moved to S1; a normative key schema added for the stack-pair config ([rg-008]), which the shipped example previously failed; compose project name explicitly excluded from [PROV-01] stack identity (`stack_id` + `base_url` instead); accepted set redefined on **three** conditions including the int `stack_media_id` join key, so a zero-detection image is a scored miss and not a silently deleted join failure; the baseline-superset blocker moved to `run` start against the **manifest** set when `baseline_manifest_path` is set (strictly stronger, and fails in seconds); the cluster gate re-specified as *all analyze jobs terminal and ≥1 success* (an all-succeed gate is unreachable the moment one item fails, contradicting `accepted_set_floor: 0.90`); no centre-in-box *match-predicate* fallback for detection matching (the asymmetry with the label map is deliberate; centre-form *coordinate encoding* is the expected GT); the `matched_faces` claim downgraded from *byte-identical* to *numerically identical*; floor-policy slice ownership split (S1 config surface / S2 resolution) with three new S1 red-proofs (`accepted_set_floor` load forms, `opencv_major_unattested`, and the cluster gate); the zero-edit claim scoped to *recognition-service* source and both harness files named; and `differential_attrition_exceeded` ordered to write the accepted-set and attrition artifacts **before** refusing to emit P/R. — **changelog (v6.3→v6.4, adversarial-review corrections; 42 findings from four independent reviewers, verdict FAIL on v6.3)**: the v6.3 "power precondition" is **retired as a category error** and replaced by a [precision precondition](#precision-precondition-normative) — image-level cluster bootstrap on the shared accepted set (pairing and within-image correlation handled by the resampling unit, no McNemar, no Wilson, no `ρ`/`DEFF`, no FIR-11 Slice 4 dependency), CI half-width ≤ δ/2 in place of post-hoc `mde_pp`, one pre-declared primary endpoint plus Holm across declared secondaries, seeded and reproducible; the fictitious `floor_below_power_floor` code removed and `accepted_set_floor` resolved to an item count before any comparison; localization pin corrected — Hungarian (not greedy) matching, pinned box coordinate convention, `max(0, ·)` clamps restored on the `matched_faces` arithmetic, and a hard `0 ≤ matched ≤ min(pred, labeled)` bounds check; the double-counting detection FN injection removed from `frame_e2e`; `golden.json` (37 entries, all carrying `face_count`, zero `face_boxes`) explicitly disqualified as a detection fixture; `report.py` inventoried as the second `ImageDetection` consumer with a required regression assertion; the exhaustiveness downgrade row added to the cell→tier table so the plan's own eligibility ceiling is machine-enforced; `face_metrics.py` no longer described as unmodified. — supersedes in-service bench supervisor (v5); re-scopes to cross-stack orchestration aligned with FIR23-STACK + QA v2; **changelog (v6→v6.1)**: real preflight contracts, explicit cluster phase, feasible public-export scoring scope, dual scoring frames, crossbench tier enum, ingest→analyze→cluster→export flow, pinned FIR23-STACK consumption table, single package root; **changelog (v6.1→v6.2)**: ground-truth wiring + label mapping, S1 executable granularity (run-dir/resume/credentials/status/PROV-01), concrete CrossbenchTier assignment rules, EVAL-19 accepted-set operationalization, proof-suite + dual-frame FIR-5 signature pins; **changelog (v6.2→v6.3, planning-review corrections)**: `opencv_major` given a real source (operator attestation + upstream ask, local `cv2` forbidden); CONFIRMATORY gains a power precondition (declared δ, exact-binomial McNemar on the paired legs, per-cell MDE, pool-conditional Wilson, ρ gate) and the previously-unassignable underpowered row; detection P/R made localization-aware via IoU matching + one scoped additive `face_metrics` change, with a [TEST-15] count-preserving red-proof; the `stranger_faces` subtraction retired; `accepted_set_floor` re-defaulted to a fraction with a power floor and a differential-attrition bias check; `frame_e2e` pinned as the sole CONFIRMATORY sampling frame; `labeled_faces` denominator pinned to `len(face_boxes)`
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
- **Fixed denominators** ([EVAL-19]): the scoring denominator is the **accepted set** — manifest items that, on **both** legs, satisfy all three conditions: (i) terminal-success ingest, (ii) terminal-success analyze with int `stack_media_id`, (iii) non-null export-side join on that key — computed once, written to `score/accepted_set.json`, asserted identical across legs before any metric; attrition of one-sided failures is reported, not silently dropped (see [EVAL-19 operationalized](#eval-19-operationalized-accepted-set)).
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
| **Accepted set** | Manifest items that, on **both** legs, satisfy (i) terminal-success ingest, (ii) terminal-success analyze with int `stack_media_id`, and (iii) a non-null export-side join on that key. Fixed scoring denominator ([EVAL-19]); written to `score/accepted_set.json`. Distinct from pre-ingest validation. |
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
| 1 | This plan (v6.6) end-to-end | Locked scope, dependency boundary, carried invariants, slices |
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
  score.py                      # BOX_IOU_MATCH = 0.5 (sole declaration) + scoring helpers
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

v5 specified an **in-service** async single-live-run bench supervisor inside the recognition worker: state machine over `recognition_bench_runs`, `uq_bench_single_live`, purge-before-terminal, deployment marker rail, boot-coupled license gate, non-blocking tick contract, and `/admin` bench routes. That vehicle is **superseded** by **per-model isolated stacks** (FIR23-STACK): exclusivity, no mixed-space reads, and teardown via stack-scoped DB reset are structural properties of the deploy topology, not application supervisor features. Re-implementing them inside the worker would duplicate FIR23-STACK ownership and re-open dual-space foot-guns. **Do not delete git history** — v5 plan text is recoverable at commit **`bc97ff4b`**. Decision **#2951** records the supersession. The rest of this document is the v6.6 scope (v6.1 structure, v6.2 grounding, v6.3 fixes, v6.4 review corrections, v6.5 structural decoupling, v6.6 validator/command/mechanical sweep).

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
- **Forward path (upstream ask, not FIR-8 scope)**: when `/health/detailed` `model_cache.opencv_version` exists, preflight reads it, sets `opencv_major_source` to `service_reported`, and fails closed with **`opencv_major_drift`** if it disagrees with the attestation. Add the branch behind a presence check now so the flip is config-free. Until that upstream field lands, **`opencv_major_drift` is unreachable** — no operator can hit it today.

### Stable error codes (normative)

| Code | When | Operator remedy |
| --- | --- | --- |
| `preflight_auth_failed` | Authenticated `/health/detailed` returns 401/403 or auth dependency rejects the key | Fix the stack-pair API key / auth env so the authenticated health call is accepted. |
| `preflight_endpoint_missing` | `/ready` or `/health/detailed` not reachable as that route (404 / connection refused treated as missing endpoint for this purpose) | Bring the stack up and confirm both routes are served at the configured `base_url`. |
| `profile_or_dim_drift` | Profile missing/mismatch, database check not OK, dim token absent, or dim int ≠ expected | Align the live stack's profile and pgvector dim with the stack-pair `expected_profile` / `expected_pgvector_dim`, or correct the config if the expectation is wrong. |
| `opencv_major_unattested` | Stack-pair entry has no parseable `opencv_major` (absent or unparseable) — **the only reachable failure path for this field today** | Set a parseable integer `opencv_major` on the stack-pair entry (operator attestation). |
| `opencv_major_drift` | Service-reported `model_cache.opencv_version` major ≠ attested `opencv_major` — **unreachable until the upstream `model_cache.opencv_version` ask lands; no operator can hit it today** | **Reserved** — no operator remedy until the upstream field exists. |
| `gt_box_count_mismatch` | FIR-8's detection fixture (or any detection-scoring load that asserts exhaustiveness) has an entry with `face_count != len(face_boxes)` | fix the fixture/corpus so every detection-scoring entry carries a complete `face_boxes` list matching `face_count`; this is FIR-8's own gate, not an inherited v3 flag. |
| `box_convention_unknown` | a box carries `x2`/`y2` corner keys instead of `w`/`h`, or `image_width`/`image_height` is missing or non-positive on a record whose prediction boxes must be converted | supply `w`/`h` boxes and positive `image_width`/`image_height` on the outcome record; do **not** treat normalized or centre-form boxes as this error — those are the expected inputs. |
| `matched_faces_out_of_bounds` | the adapter produced a `matched_faces` violating `0 <= matched <= min(pred_faces, labeled_faces)` | this is an adapter bug, not a config error; fix the matcher — do not clamp it away. |
| `differential_attrition_exceeded` | one-sided attrition skew exceeds `max_differential_attrition` | the surviving pool is biased toward the failing leg; repair that leg and re-run, do not score the subset. |
| `media_unresolvable` | an ingest item's media cannot be resolved | fix or drop the manifest entry; it is counted in attrition. |

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
| **Errors** | `ManifestError` on structural/hash/label failures (fail-closed, [rg-008]); FIR-8 additionally raises `gt_box_count_mismatch` when its detection fixture fails the exhaustiveness assertion below |
| **File pattern** | CLI `--manifest` accepts any path loadable by `load_manifest`. **Convention** for the Golden-150 face bench corpus: `benchmarks/manifests/golden150-*.json` (e.g. `golden150-draft-YYYYMMDD.json`). Smoke / identification fixtures may use `apps/prototype-description-service/scene/tests/seed/golden.json` (identification only — zero `face_boxes`). Detection tests use `scripts/bench/tests/fixtures/v2_boxed_detection.json`. |
| **In-tree status (plan-author check)** | `benchmarks/manifests/golden150-draft-20260723.json` is **not** present in this checkout; operators (or VLM-6 curation) supply the curated Golden-150 path. Do not invent a vendored 150-entry file in FIR-8. |
| **Content hash pin** | At `run` start, write `manifest.sha` = sha256 of the manifest file bytes. Optional stack-pair / run config key `manifest_sha256` fails closed if it mismatches the loaded file. Score path re-reads the hash for provenance. |
| **Image bytes root** | `--images-dir` (or config `images_dir`) is the local corpus root; when set, `load_manifest(..., images_dir=...)` verifies per-entry `sha256` against files under that root (same as harness). |

CLI (illustration of required flags, not a full copy-paste invocation): `run --manifest <path> --images-dir <root>` (both required for production head-to-head; tests may inject a synthetic `GoldenManifest` without disk images).

### Manifest load & detection exhaustiveness (no FIR-11 coupling)

FIR-8 loads via `load_manifest` against the v2 schema, full stop. Verified against the current harness: `SUPPORTED_MANIFEST_VERSION = 2`, `GoldenEntry.face_boxes` already exists, `ConfigDict(extra="forbid")` rejects unknown fields, and there is no `load_legacy_manifest` symbol. No FIR-8 step calls a symbol or fixture that FIR-11 has not yet created.

**Exhaustiveness is FIR-8's own local assertion**, not an inherited manifest flag and not gated on FIR-11: the detection fixture `scripts/bench/tests/fixtures/v2_boxed_detection.json` (`manifest_version: 2`, explicit `face_boxes` entries) must satisfy `face_count == len(face_boxes)` for every entry, asserted by FIR-8 at load of its own fixture. A violation raises `gt_box_count_mismatch`.

| Corpus | `stranger_faces` | Detection FP / ID-precision claims |
| --- | --- | --- |
| **Detection fixture / any entry that passes exhaustiveness** (`face_count == len(face_boxes)`, boxes present) | derived: count of `face_boxes` with `name is None` | **CONFIRMATORY-eligible** (subject to the rest of the tier table) — every face in frame has a box, so an unmatched predicted box is a real FP |
| **Box-less or incomplete entry** (no `face_boxes`, or not under the exhaustiveness-asserted detection path) | **not derived — `0`, and the cell is DIAGNOSTIC** | not eligible for detection frames: unannotated bystanders are indistinguishable from detector FPs; entry excluded from detection frames with a counted, printed exclusion |

The retired arithmetic was `stranger_faces ← max(0, face_count − len(present_identities))`. It manufactures a stranger count out of a roster gap. **Deriving `stranger_faces` by subtraction is removed from this plan entirely** — when exhaustiveness holds it comes from the boxes (`name is None`); otherwise it does not come at all.

**FIR-11 Slice 2 is not a dependency of any FIR-8 S1/S2 code path or fixture.** It remains relevant only as a later source of a larger boxed production corpus. Until a production corpus carries complete `face_boxes`, detection unit tests run against `v2_boxed_detection.json`, and a production run without complete boxes is a DIRECTIONAL/DIAGNOSTIC orchestration dry run — real value, executable today, not a head-to-head gate number. `score` prints whether the loaded corpus passed the exhaustiveness assertion and the resulting eligibility ceiling in the provenance block.

### (b) Constructing metric inputs

Frame construction happens **entirely in `scripts/bench`** (`export_map.py` / `score_report.py`). FIR-5 `detection_pr` / `identification_pr` remain pure functions of the rows the adapter builds; `identification_pr` is **unmodified**, while `detection_pr` and `ImageDetection` take the one scoped additive change described in the [localization pin](#b-constructing-metric-inputs) below. Nothing in this plan describes `face_metrics.py` as untouched.

| Side | Source | Fields used for FIR-5 rows |
| --- | --- | --- |
| **GT (labeled)** | Manifest entry | `ImageDetection.labeled_faces` ← **`len(entry.face_boxes)`** (single pinned rule — see the denominator pin below); `ImageIdentities.labeled` ← `entry.present_identities` (roster names); `recognition_enabled` ← `entry.policy.recognition_enabled`; `stranger_faces` ← per [manifest load & detection exhaustiveness](#manifest-load--detection-exhaustiveness-no-fir-11-coupling) (boxes with `name is None` when exhaustiveness holds; otherwise `0` + DIAGNOSTIC) |
| **Predicted** | Per-leg public exports under `legs/<stack_id>/exports/` | `ImageDetection.pred_faces` ← count of exported face rows for that media; **`ImageDetection.matched_faces` ← count of IoU-matched pairs** (see localization pin below); `ImageIdentities.predicted` ← **mapped** identity names (never raw unmapped cluster ids as if they were GT names) |
| **Image key** | Join key | Stable string: manifest `path` or `str(entry.media_id)` — same `image` field on both `ImageDetection` and `ImageIdentities` for a media unit |

Detection P/R does not require identity name mapping. Identification P/R **requires** [label-space mapping](#c-label-space-mapping) before filling `predicted`.

**Denominator pin (one rule, not two).** An earlier revision wrote `labeled_faces ← entry.face_count` *"or `len(entry.face_boxes)` when boxes are complete and preferred"* — inside a table this plan labels **normative**. Two denominators yield two different detection P/R values for the same run with no rule selecting between them, which is the same post-hoc-selection defect as the unpinned sampling frame above. `len(entry.face_boxes)` is the pin, for one reason: the localization pin below requires per-box GT geometry anyway, so a `face_count` that disagrees with the box list would mean the metric's denominator and its matching evidence disagree. Consequences are explicit rather than tolerated:

- `face_count != len(face_boxes)` on an entry of FIR-8's detection fixture (or any detection-scoring load that asserts exhaustiveness) → **fail closed** (`gt_box_count_mismatch`). This is **FIR-8's own gate** at load of its boxed fixture — not scoped to an external exhaustiveness flag. The denominator pin and the localization pin both require per-box GT geometry; a `face_count` that disagrees with the box list means the metric's denominator and its matching evidence disagree.
- **`scene/tests/seed/golden.json` is not a detection fixture.** It has **37 entries, all 37 carrying `face_count` (35 with a non-zero value), and zero carrying `face_boxes`** (verified 2026-07-29). It is a valid identification-frame smoke fixture, but under the box-based denominator every entry is box-less, so it cannot serve detection tests. Slice 2's detection tests therefore require the purpose-built **`v2_boxed_detection.json`** fixture (`manifest_version: 2`, explicit `face_boxes`), authored in `scripts/bench/tests/fixtures/`, and the localization red-proof is written against that fixture.
- An entry with **zero** `face_boxes` cannot be scored for detection at all and is excluded from the detection frames with a counted, printed exclusion — the same treatment the optimistic label rule already gives box-less entries. It stays in the identification frames.

**Localization pin ([TEST-15]).** Detection P/R was cardinality-only: `labeled_faces` from a count and `pred_faces` from `len(exported rows)`, fed to `detection_pr`, whose per-image arithmetic is `TP = min(pred, labeled)`. A detector emitting the **right number of boxes in entirely the wrong places scores perfect detection P/R** — precisely the plausible-wrong-implementation-still-passes pattern, and it is the metric the whole head-to-head rests on. The signal was available and discarded: exports carry `bbox` geometry, GT carries `face_boxes`, and this plan **defines** a new constant `BOX_IOU_MATCH = 0.5` in `scripts/bench/score.py` (the sole declaration; every other site imports it) for IoU matching on both the detection pin and the optimistic label map.

- **Coordinate convention (pinned before any IoU is computed).** Canonical scoring space is **normalized top-left** boxes in 0..1. The two input sides use different encodings and units; both convert into that space before IoU:
  - **Ground truth** (`FaceBox` on the manifest): normalized **centre** form `(x, y)` plus size `(w, h)` in 0..1. Convert to scoring space with `x1 = x − w/2`, `y1 = y − h/2`, keeping `w`, `h`. Centre-form is the expected GT encoding — it is **not** a convention error.
  - **Prediction** (detector / export `bbox`): absolute-pixel top-left `x`, `y`, `w`, `h`. Convert with `x1 = x / image_width`, `y1 = y / image_height`, `w = w / image_width`, `h = h / image_height`. Therefore `items.jsonl` **must** persist `image_width` and `image_height` (positive ints, read from the image at ingest — the harness already opens the bytes to POST them). Scoring must **not** need filesystem access to the images.
  - After both sides are in scoring space, the adapter forms `(x1, y1, x2, y2) = (x1, y1, x1 + w, y1 + h)` and computes IoU as `|∩| / |∪|` on those rectangles.
  - It **fails closed** (`box_convention_unknown`) when a box carries `x2`/`y2` corner keys instead of `w`/`h`, or when `image_width`/`image_height` is missing or non-positive on a record whose prediction boxes must be converted. It **must not** fire on a normalized box and **must not** fire on a centre-form box — those are the expected inputs. An IoU computed across two different conventions silently reads ≈ 0 on every pair, which would make the matched cell collapse for reasons that have nothing to do with detector quality — indistinguishable from the very failure the pin exists to detect.
- The adapter computes an **optimal one-to-one assignment (Hungarian)** over the IoU matrix at `BOX_IOU_MATCH` (imported from `scripts/bench/score.py`, where it is defined as `0.5`), discards assigned pairs below that threshold, and reports `matched_faces` per image. **Hungarian, not greedy:** greedy-by-descending-IoU is not optimal (it can strand a GT box whose only above-threshold partner was consumed by a higher-scoring pair) and, more decisively, the [optimistic label rule](#c-label-space-mapping) already specifies Hungarian — two different matching algorithms on the same box geometry in the same plan is the "two denominators" defect in another costume. Ties are broken by a **total** order so the result is reproducible: descending IoU, then ascending GT box index, then ascending prediction row index as it appears in the leg's export file. GT box order alone is not a total order — two predictions tying against the *same* GT box are still unordered under it.
- `detection_pr` as it stands **cannot express this** — `ImageDetection` has no TP slot, so a single mislocalized box (1 pred, 1 GT, 0 matched) is scored `TP = min(1,1) = 1`. This is a real expressiveness gap in the shared metric, not a FIR-8 inconvenience, so it is fixed **upstream once**: add `matched_faces: int | None = None` to `ImageDetection`, and in `detection_pr` use `TP = matched`, `FP = max(pred − matched, 0)`, `FN = max(labeled − matched, 0)` when it is present — **the same clamps the existing count-only branch already applies** (`fp += max(pred − labeled, 0)`, `fn += max(labeled − pred, 0)`). v6.3 wrote the three terms unclamped, which lets a bad `matched_faces` drive FP or FN negative and *inflate* precision or recall past 1.0 — a metric that can exceed its own bound is worse than the gap it was replacing.
- **Validate `matched_faces` at construction, fail closed.** `0 ≤ matched_faces ≤ min(pred_faces, labeled_faces)` is a hard invariant, checked in `detection_pr` when the field is present and raising `ValueError` (`matched_faces_out_of_bounds`) rather than clamping silently. Clamps defend the arithmetic; the bounds check defends against the adapter shipping a matcher bug into a gate number. Both are required — a clamp alone turns an out-of-range matcher into a plausible-looking metric, which is exactly [TEST-15]'s failure mode.
- Omitted → **numerically identical** `detection_pr` output on every existing input, and source-compatible for both positional and keyword construction of the frozen dataclass. It is **not** *byte-identical*, and the plan should not claim so: a trailing field changes `dataclasses.fields()` arity, `astuple()` length, `repr()`, `__match_args__`, and the pickle payload. A consumer that unpacks `astuple()` into a fixed-arity target, pattern-matches positionally, or compares `repr` strings would observe it. That is precisely why the [consumer inventory](#dual-frame-adapter-contract-fir-5-signatures-pinned) exists and why the field is **optional with a default, added last** — so keyword construction and the `None` path stay numerically identical without a before/after golden. This is the "documented gap fixed upstream with rationale" the [Contract and Boundary Impact](#contract-and-boundary-impact) table already permits, and it supersedes the blanket *do not modify* note in the [dual-frame contract](#dual-frame-adapter-contract-fir-5-signatures-pinned).
- **Match-predicate rule (not a coordinate-encoding rule): no centre-in-box FALLBACK for detection matching.** The coordinate convention above *accepts* centre-form GT boxes as inputs and converts them into scoring space; that is unrelated to whether a *match* may be awarded when a prediction's centre merely lies inside a GT box. The [optimistic label rule](#c-label-space-mapping) admits a centre-in-box match when GT boxes lack size parity; detection matching does **not**, at the same `BOX_IOU_MATCH` (imported from `scripts/bench/score.py`). Detection P/R exists *to measure localization*, so admitting a localization-tolerant match predicate into it would restore exactly the mislocalization blindness this pin was written to remove — a box centred on the right face but sized wrong would score as matched. The label map has the opposite job (recover *identity* despite imperfect geometry), so tolerance there costs nothing it is measuring, and it is already disclosed DIRECTIONAL. Consequence, stated so no one cross-quotes the two: the optimistic frame's match count is computed under a looser predicate than `matched_faces` and **the report must never compare them or reuse one as the other**.
- **Count-only detection P/R is retained as a DIAGNOSTIC cell**, printed beside the matched cell. The gap between them *is* the localization-quality signal, and on a cross-stack comparison between two different detectors it is one of the more interesting numbers in the report.
- **Discrimination red-proof (mandatory, [TEST-15])**: a fixture where every predicted box is translated off its GT box while the per-image **count** is preserved. The count-only cell must still read perfect P/R and the matched cell must collapse to `TP = 0`. Deleting the IoU matching makes the matched cell read perfect and the test fail. A green run that cannot go red here certifies nothing.

### (c) Label-space mapping

Predicted `cluster_label` values are **cluster-scoped** (stack-local cluster ids / operator labels), not automatically GT roster names. Never pass raw `cluster_label` into `ImageIdentities.predicted` without mapping.

**Normalization** (shared by both rules): Unicode NFC, strip, collapse internal whitespace, casefold.

| Rule | When | How | Report frame |
| --- | --- | --- | --- |
| **Primary — string match (pinned primary)** | Cluster has an operator-assigned label (`is_auto_label == false` **or** non-empty human `cluster_label` that is not a pure auto id) | Map predicted label → GT name if normalized strings equal a roster / `present_identities` name; else unmapped (omit from `predicted` for primary frame; count under unmapped-cluster DIAGNOSTIC stats) | `label_map_primary` — **default** for CONFIRMATORY identification cells |
| **Optimistic — Hungarian (disclosed)** | Unlabeled / auto-labeled clusters (`is_auto_label == true` or empty label) **or** residual after primary | Optimal one-to-one assignment (Hungarian) maximizing **overlap counts** between cluster member boxes and GT `face_boxes` (IoU ≥ `BOX_IOU_MATCH` imported from `scripts/bench/score.py` where it is defined as `0.5`, or centre-in-box fallback when GT boxes lack size parity — a *match-predicate* tolerance, not a coordinate-encoding rule). Assigned GT names fill `predicted` for this frame only. Entries with **no `face_boxes`** are ineligible for the optimistic rule — their unlabeled clusters stay unmapped (DIAGNOSTIC) and the report states the count of box-less entries so an empty optimistic frame is legible, not silent. | `label_map_optimistic` — always **DIRECTIONAL**; never CONFIRMATORY |

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
  "image_width": 1920,              # positive int; read from image bytes at ingest (required for prediction-box conversion)
  "image_height": 1080,             # positive int; read from image bytes at ingest (required for prediction-box conversion)
  "phase": "ingest|analyze|…",
  "outcome": "ok|failed",
  "error_code": null,
  "attempt": 1
}
```

Score path: for each accepted-set item, resolve `stack_media_id` (int) per leg from that leg's `items.jsonl`, then select export rows whose `media_id` (int) equals it — **both sides are ints; there is no string coercion**. A client-supplied `stack_media_id` is always an int on an analyze-success record — missing/null is not a defined state. A **join failure** is an **export-side absence**: the export leg produced no row for that `stack_media_id`. That item is counted in attrition (phase=`join`) and does not enter the accepted set (condition (iii) of the [accepted-set definition](#eval-19-operationalized-accepted-set) requires a successful export-side join on the int key). When the export query succeeds and the media is present with an empty face list (detector found nothing), the item stays in the accepted set and scores as a miss — that is not a join failure.

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

- **Construction site**: `export_map.to_face_metric_inputs(...)` / `score_report.build_dual_frames(...)` only.
- **Call sites**: `detection_pr(seq_of_ImageDetection)`, `identification_pr(seq_of_ImageIdentities)` — no other FIR-5 face scorer on the cross-stack path.
- **One scoped exception to "do not modify `face_metrics.py`"**: the optional `ImageDetection.matched_faces` field plus its branch in `detection_pr`, per the [localization pin](#b-constructing-metric-inputs). No existing signature changes and the field defaults to `None`. Rationale: the alternative — a bench-local localization scorer — is exactly the "parallel scorer" the [Constraints](#constraints) forbid, and it would leave the shared metric blind to localization for every other consumer. Extend the shared metric once; do not fork it and do not shadow it.
- **Consumer inventory (complete, verified 2026-07-29).** Exactly three files reference `ImageDetection` anywhere in the repo: `scripts/eval_harness/face_metrics.py` (the definition), `scripts/eval_harness/report.py`, and `scene/tests/test_eval_harness_face_metrics.py`. **`report.py` is a second existing consumer** — it imports `ImageDetection` (L47) and `detection_pr` (L51), constructs rows at L457, and calls `detection_pr` at L519. v6.3 asserted `face_metrics.py` was the "only edit outside `scripts/bench/`" while leaving this consumer uninventoried, which is precisely the boundary-blindness [rg-015] forbids. `report.py` needs **no code change** — it never sets `matched_faces`, so it takes the `None` path and its numbers are **numerically identical** (not byte-identical at the dataclass level). **`report.py` is READ, NOT EDITED.** Expressible proofs live in `apps/prototype-description-service/scene/tests/test_eval_harness_face_metrics.py`: (1) bounds assertion `0 <= matched_faces <= min(pred_faces, labeled_faces)` — a violation raises `matched_faces_out_of_bounds`; (2) the new field is **OPTIONAL with a default**, added **last**, because any consumer constructing the dataclass positionally would be a breaking change. A before/after `report.py` golden is **not** expressible (one test tree only ever contains the after-state) and is not required.
- **Ownership.** `scripts/eval_harness/face_metrics.py` is FIR-5-owned shared offline-harness code. This task edits it under the documented-gap exception above; the FIR-5 owner is named in the Slice 2 checklist as a required reviewer on that one file, and the change does not land without that review.
- Everything else in this task remains a pure consumer.

**Adapter construction (normative)**

1. Join accepted-set media via [media identity join](#d-media-identity-join); load GT from the pinned manifest; load predicted rows from `legs/<stack_id>/exports/`.
2. Apply [label-space mapping](#c-label-space-mapping) → primary and (separately) optimistic predicted name lists.
3. **FIR-5-native sampling frame** (`sampling_frame=SAMPLING_FRAME_CROSSBENCH_NATIVE`): call `detection_pr` / `identification_pr` on rows derived only from exported detections (excludes pure detector misses from identification accounting by construction of the input rows). Report under key `frame_fir5_native`.
4. **End-to-end sampling frame** (`sampling_frame=SAMPLING_FRAME_E2E`): Report under key `frame_e2e`. Detector miss → identification miss is accounted here ([EVAL-16]), but **the two frames account for it in different places and neither injects rows into detection**:
   - **Detection** needs no injection at all. With the localization pin in force, `FN = max(labeled_faces − matched_faces, 0)` already charges every labeled GT box that no predicted box matched — a detector miss and a mislocalized box are both unmatched GT, and both land in FN by construction. v6.3 said to inject "`ImageDetection` undershoot" FN rows *in addition*, which **double-counts every missed face**: once in the injected row and once in the `labeled − matched` residue of the real row. Detection rows are built once, from the join, unmodified.
   - **Identification** does need the injection, because `identification_pr` has no geometry and cannot see that a name was unreachable: for each accepted-set media, every `present_identities` name with no mapped predicted counterpart is charged as an identification FN, whether it was lost at detection, at clustering, or at label mapping. That is the whole difference between `frame_e2e` and `frame_fir5_native`, and it is an operation on the *identification* rows only.
5. Head-to-head report prints sampling frames **and** label-mapping frames as a grid per leg; never silently replace one with another.

**Unit test (required)**: synthetic corpus where one labeled face is absent from export → `frame_e2e` identification FN increments and detection FN increments; `frame_fir5_native` identification denominator does not charge that miss the same way (pins detector-miss→ID-miss accounting).

Constants live in `score_report.py` (or `export_map.py`): `SAMPLING_FRAME_CROSSBENCH_NATIVE`, `SAMPLING_FRAME_E2E`, `LABEL_MAP_PRIMARY`, `LABEL_MAP_OPTIMISTIC` — plan-level names; not FIR-5 library enums. Do NOT import `face_metrics.SAMPLING_FRAME_FACE_ID` on the cross-stack path — that existing FIR-5 constant names the pooled k-fold face-level frame, which is out of scope here.

---

## Tier vocabulary

The three-tier report label set **`CONFIRMATORY` / `DIRECTIONAL` / `DIAGNOSTIC`** is a **new crossbench report enum** defined in `score_report.py` as `CrossbenchTier`, sourced from QA-digest / canon convention for head-to-head bench claims. It is **not** a FIR-5 enum and must not be attributed to FIR-5 modules.

Separately: FIR-5 / eval harness surfaces carry **per-metric DIRECTIONAL disclosure qualifiers** in the QA/canon sense (e.g. underpowered slices report directional-only and cannot enter a gate decision — see commercial-face-identity scope language) plus harness **`provider_disclosure`** stamps on describe responses. Those are **not** the three-tier crossbench enum. Crossbench reports may *reference* FIR-5 directional disclosure text when a leg is underpowered, but the tier stamp itself is owned by `score_report.py`.

### CrossbenchTier semantics (normative)

| Tier | Meaning |
| --- | --- |
| **CONFIRMATORY** | Full-corpus fixed-denominator metric over the pinned **accepted set**, both legs' clustering complete (`cluster_job.json` success), **primary** label-mapping only, accepted-set size ≥ the [floor](#floor-policy-normative), the cell **pre-declared** as `primary_endpoint` or in `secondary_endpoints`, **and the [precision precondition](#precision-precondition-normative) satisfied for the cell's own δ** (Holm-adjusted for secondaries). Eligible for gate-style claims. |
| **DIRECTIONAL** | Any cell whose denominator lost items below the pre-stated floor (ingest/analyze failures shrank the accepted set), **or** any cell using the **optimistic** label-mapping frame, **or** any cell that fails the precision precondition, **or** any cell not on the pinned primary sampling frame, **or** any cell whose eligibility ceiling is capped because the loaded corpus did not pass the [detection exhaustiveness](#manifest-load--detection-exhaustiveness-no-fir-11-coupling) assertion. Not gate-eligible. |
| **DIAGNOSTIC** | Context cells: per-stack raw face/cluster counts, unmapped-cluster stats, attrition-by-phase tables, join failures, license banner echo — plus **any cell absent from both `primary_endpoint` and `secondary_endpoints`**, which can never be promoted. Never used as a quality gate. |

### Precision precondition (normative)

Size is not precision. An earlier revision made a cell CONFIRMATORY on accepted-set **size** alone and declared it gate-eligible, while the plan contained no variance or interval concept anywhere — so a two-point P/R gap between legs on ~150 images would have been stamped gate-eligible. That contradicts the sibling discipline this programme already accepted (FIR-11 plan: cells under-powered for δ = 10pp are *"not a ship gate"*), and it is the failure mode [EVAL-17] names.

**The v6.3 replacement was itself wrong and is retired here.** It declared the head-to-head an **exact-binomial McNemar** test on discordant media, gated on a post-hoc `mde_pp`, labeled cells with **Wilson** intervals, and blocked face-level cells behind an unmeasured intra-occasion `ρ` via `DEFF = 1 + (m − 1)·ρ`. Three defects, all disqualifying:

- **McNemar does not apply to a micro-averaged ratio.** McNemar tests a paired *binary* outcome on a fixed set of units. Recall's denominator (labeled GT faces) is shared across legs, so a paired per-face test is at least well-defined there — but **precision's denominator (predicted boxes) is leg-specific**, so leg A and leg B are not two measurements of one unit and there is no discordant pair to count. Applying one test to both is a category error, and the tested quantity (a per-unit win/loss split) is not the quantity the report prints (a difference of pooled ratios).
- **`mde_pp` computed at the observed `n_discordant` is post-hoc power.** An MDE evaluated after seeing the data is a re-expression of the observed standard error, not an independent precondition; gating on it adds no information the interval does not already carry.
- **The `ρ` gate blocks the whole plan on a nuisance parameter that never needs estimating.** Choosing the resampling unit to be the correlated group makes clustering vanish by construction — no `ρ`, no `DEFF`, no dependency on FIR-11 Slice 4.

**Estimand (pinned).** For each cell the reported quantity is the **difference between legs of the micro-averaged ratio the report prints** — `Δ = metric(A) − metric(B)`, computed over the shared **accepted set** — the single set of media that satisfy, on **both** legs, the three membership conditions in [EVAL-19 operationalized](#eval-19-operationalized-accepted-set): (i) terminal-success ingest, (ii) terminal-success analyze with int `stack_media_id`, (iii) non-null export-side join. Zero-detection items that clear those three conditions **remain in the set** and are scored as misses (they are not excluded from the bootstrap population). The uncertainty statement must be about that quantity and nothing else.

A cell is CONFIRMATORY only when **all** of the following hold, each computed and printed next to the cell:

1. **Uncertainty comes from an image-level cluster bootstrap.** `score` resamples **whole media units** with replacement from that pinned three-condition accepted set, `B = 2000` (pinned constant `BOOTSTRAP_RESAMPLES`), recomputes **both legs** on the *same* resample, and takes the percentile interval of the resulting Δ distribution. Two properties come for free and are the reason this design is chosen: the pairing is preserved *by construction* (both legs always see the identical resample, so shared-corpus variance cancels without a paired test), and within-image correlation between faces is absorbed *by construction* (the resampling unit is the image, not the face), so no intra-cluster coefficient is estimated or assumed. Ratio denominators may differ between legs — the bootstrap is indifferent to that.
2. **The resampling unit is the coarsest declared grouping.** If the pinned manifest declares an occasion / session / capture-event id, resample at **that** level; otherwise the media unit is the coarsest grouping the corpus offers and the report states so in the provenance block. This is the honest form of the retired `ρ` item: correlation is handled by the resampling unit, and where the corpus cannot name the group the report discloses the residual rather than gating on an unmeasured parameter.
3. **δ is declared before the run**, in the stack-pair config as `head_to_head_delta` (**required**, no default — must be declared before the run). A non-binding example used by sibling FIR plans is **0.10** (10pp); declaring the same value makes FIR-8 and FIR-11 claims comparable, but the loader never supplies a fallback. A δ chosen after seeing the split is a post-hoc threshold, not a gate.
4. **The interval is precise enough to resolve δ.** The bootstrap CI **half-width on Δ must be ≤ δ/2**. This is a precision criterion on the interval actually reported, not a power calculation replayed at the observed split: an interval wider than δ cannot distinguish "the legs differ by δ" from "the legs are equivalent", whatever the point estimate says. `score` stamps `ci_half_width_pp` on every cell; `ci_half_width_pp > δ/2` → **DIRECTIONAL**, no exception. Note what binds: two stacks that agree on almost everything still produce a *narrow* interval around Δ ≈ 0 and legitimately clear this criterion as an equivalence result — the retired discordant-pair gate wrongly failed that case.
5. **Exactly one primary endpoint is pre-declared.** The primary is **detection recall on `frame_e2e` under `label_map_primary`**, named in the config as `primary_endpoint` and fixed before the run. It alone may carry an unadjusted gate claim. Every other cell is a **pre-declared secondary**, listed in the config as `secondary_endpoints`; secondaries reach CONFIRMATORY only after **Holm–Bonferroni** adjustment across that declared list. A cell absent from both config keys is **DIAGNOSTIC** and can never be promoted — this is what stops the report's ~20-cell grid from being a multiplicity farm in which some cell always clears any threshold.
6. **The interval is labeled for what it covers.** Every cell's interval is labeled **conditional on this pool** — golden150 is a convenience corpus, not a probability sample of deployment traffic, so the interval bounds resampling noise within the pool and says nothing about generalisation.

**Determinism ([PROV-05]).** The bootstrap is seeded from `bootstrap_seed` in the stack-pair config (required key, no default — an unset seed is a config error, not a random run). `score` prints `bootstrap_seed`, `BOOTSTRAP_RESAMPLES`, and the resampling unit in the provenance block, so a reported interval is reproducible from the artifact alone.

**Discrimination red-proof (mandatory, [TEST-15]).** Two fixtures, both required to fail if the criterion is deleted: (a) two legs with **identical** exports over a deliberately small accepted set — Δ = 0 exactly, but the half-width exceeds δ/2, so the cell must read DIRECTIONAL; deleting the half-width check makes it read CONFIRMATORY. (b) two legs differing by a large, wide-margin gap over the full accepted set — the cell must read CONFIRMATORY; a bootstrap that resamples *faces* instead of media units must be shown to produce a narrower (anticonservative) interval on fixture (a) than the media-unit bootstrap, which pins item 1's resampling unit as load-bearing rather than decorative.

Infrastructure cost is ~60 lines: a resample loop over the accepted set, a percentile helper, and a Holm helper. **No `scipy` dependency, no interval helper from a named parametric family, and no dependency on FIR-11 Slice 4** — the retired intra-occasion `ρ` gate was the only thing that coupled FIR-8's statistics to FIR-11.

### Cell → tier assignment (normative)

Rules are evaluated **top to bottom; first match wins**. A cell reaches CONFIRMATORY only by falling through every downgrade above it.

| Report cell | Tier rule |
| --- | --- |
| Any P/R cell when either leg cluster phase missing/failed | **not scored** (score aborts; no silent tier downgrade that invents a metric) |
| Any P/R cell when `differential_attrition_exceeded` | **no P/R cells** — order: (1) write accepted-set + attrition artifacts to disk FIRST; (2) emit NO precision/recall cells; (3) exit non-zero with `differential_attrition_exceeded` (surviving pool biased toward the failing leg; no tier is honest) |
| Any cell named in neither `primary_endpoint` nor `secondary_endpoints` | **DIAGNOSTIC** (never promotable — see precision precondition item 5) |
| **Detection-FP-bearing or identification-precision cell when the loaded corpus did not pass the [detection exhaustiveness](#manifest-load--detection-exhaustiveness-no-fir-11-coupling) assertion** (no complete `face_boxes`, or not the exhaustiveness-asserted detection path) | **DIRECTIONAL** (this row makes the exhaustiveness ceiling machine-enforced instead of prose-only: `stranger_faces` is `0` by fiat when boxes are incomplete, so an unmatched predicted box cannot be distinguished from an unannotated bystander. Without this row such a cell fell through to CONFIRMATORY and the plan's own eligibility ceiling was unenforced.) |
| Any P/R cell when the accepted-set size is below the [resolved floor](#floor-policy-normative) — i.e. `\|accepted_set\| < resolved_floor_count`, where `resolved_floor_count = max(2, ceil(fraction × N))` for a fraction (or the absolute int ≥ 2) — never below 2 | **DIRECTIONAL** |
| Any P/R cell failing the [precision precondition](#precision-precondition-normative) — `ci_half_width_pp > head_to_head_delta / 2`, or (for a secondary) failing Holm adjustment across `secondary_endpoints` | **DIRECTIONAL** (this is the row that was missing; without it "underpowered" was named as a DIRECTIONAL trigger in the prose but was unassignable in the table, so nothing could ever receive it) |
| Detection P/R on `frame_fir5_native` | **DIRECTIONAL** (always — secondary frame, see the frame pin below) |
| Identification P/R with `label_map_optimistic` | **DIRECTIONAL** (always) |
| Detection recall on **`frame_e2e`** with `label_map_primary` (the pre-declared `primary_endpoint`), IoU-matched, accepted set, clusters OK, floor and precision satisfied | **CONFIRMATORY** (unadjusted — the sole primary) |
| Any other cell listed in `secondary_endpoints` meeting the same conditions **and** surviving Holm adjustment | **CONFIRMATORY** |
| Per-stack raw detection counts, export row counts, count-only detection P/R | **DIAGNOSTIC** |
| Unmapped-cluster counts / residual after mapping | **DIAGNOSTIC** |
| Attrition table (per-leg failure counts by phase) | **DIAGNOSTIC** |
| Provenance / license banner fields | **DIAGNOSTIC** (metadata, not a quality claim) |

**Primary sampling frame is pinned to `frame_e2e`.** An earlier revision marked *"Detection P/R (`frame_e2e` **or** `frame_fir5_native`)"* CONFIRMATORY, which produced **two** gate-eligible detection numbers per leg with no rule for which one the head-to-head claim uses — so whichever frame flattered the preferred stack could be selected after the fact. The label-map frames were already pinned one line earlier (`label_map_primary` is "**default** for CONFIRMATORY identification cells"); the sampling frames were not, and that asymmetry was the defect. `frame_e2e` is the primary because cascade honesty ([EVAL-16], already a locked constraint) says a face the detector missed is an end-to-end error — a frame that excludes detector misses cannot carry the headline claim. `frame_fir5_native` stays in the report as the always-DIRECTIONAL companion that isolates *post-detection* quality; both print side by side, and neither may be substituted for the other.

---

## EVAL-19 operationalized (accepted set)

[EVAL-19] is not only “share a denominator” — the denominator is a concrete artifact:

1. **Definition (three conditions, not two).** `accepted_set` = set of manifest items (`manifest_media_id` / path / sha256) for which, on **both** legs, `legs/<stack_id>/items.jsonl` records (i) terminal-success for **ingest**, (ii) terminal-success for **analyze** with an int `stack_media_id` recorded on the analyze-success record (client-supplied; always written on the success path — missing/null is not a defined state), and (iii) a successful export-side join on that int key — the export leg produced at least a presence for that `stack_media_id` (empty face list allowed). Condition (iii) is part of the definition, not a later filter: an earlier revision defined the set from (i)+(ii), asserted it immutable, and *then* had the [media join](#d-media-identity-join) drop items from it, which is a contradiction (the set cannot be both fixed at step 2 and shrunk at step 4) and would have made `score` non-deterministic in the order its own steps ran.
   - **A join failure is not the same as zero detections, and conflating them corrupts recall.** Join failure means the export leg produced **no row** for that `stack_media_id` (export-side absence) — the correspondence itself is absent, so the item is unscoreable and is pre-accept attrition (phase `join`). An item with a valid int `stack_media_id` whose export query succeeds with an **empty face list** detected nothing; it stays in the accepted set and is a scored miss (item 6). Treating the second case as a join failure would silently delete every image the detector missed entirely, from the denominator, on the leg that missed it — inflating that leg's recall by exactly its worst failures. Both sides of the join are ints with **no** coercion.
2. **Compute once** at the start of `score` (after both legs finished run): intersection of the per-leg sets satisfying all three conditions.
3. **Persist**: write `score/accepted_set.json` (`manifest_media_ids`, `paths`, `content_sha256s`, `size`, `floor_config` (the raw configured value), `resolved_floor_count` (the item count actually compared against — see [floor policy](#floor-policy-normative)), `resampling_unit`, `computed_at`).
4. **Assert before metrics**: both legs' success sets, when intersected, match the file; re-derive and fail closed if a leg's items.jsonl was mutated after the file was written.
5. **Attrition (reported, not silent)**: items in the manifest but missing from the accepted set appear in `score/attrition.json` (and the report DIAGNOSTIC table). For each missing item the `phase` names **which of the three membership conditions failed** — `ingest` (condition i), `analyze` (condition ii), or `join` (condition iii) — plus one-sided success counts (satisfied all three conditions on A only / B only). Operational cluster/export failures that are not membership conditions may appear as DIAGNOSTIC context but do not redefine accepted-set membership.
6. **Detection failure after accept**: a media that satisfies all three membership conditions on both legs stays in the accepted set even if detection count is zero — that is a scored miss, not attrition. Attrition is **pre-accept** failure only. Arithmetically: the item contributes to the recall **denominator** (`labeled_faces` / labeled GT boxes) with **zero true positives** (`matched_faces = 0`, so `FN = labeled`); dropping it from the denominator is a silent recall inflation and is forbidden. Red-proof in `test_attrition_floor.py` (zero-detection accepted item): if the scorer excludes the item from the recall denominator, the fixture goes red.
7. **Floor**: if `size < resolved_floor_count` (the count, never the raw fraction — see [floor policy](#floor-policy-normative)), all P/R cells downgrade to **DIRECTIONAL** (see tier table); report still emits metrics with the disclosure.

---

## Carried-forward invariants (orchestration layer)

Adapt v5 review-hardened invariants; **do not re-litigate**. Enforcement lives in the **CLI**, not the recognition service.

### CF-1. Baseline / corpus ingest contract

- Uploaded or declared baseline / label artifact `media_id` (or content-sha) set **must be a SUPERSET** of the run's accepted set. **Partial intersection = blocker** (exit non-zero; do not score a silent subset).
- **Where the check runs, and against what (ordering pin).** The accepted set is first computed by `score` (S2), so an S1 blocker cannot compare against it. It does not need to: accepted ⊆ manifest always holds, so `baseline ⊇ manifest` **implies** `baseline ⊇ accepted`. When the optional config key **`baseline_manifest_path`** is present, S1 loads that manifest, derives `baseline_ids`, and asserts the **stronger** condition — `assert_baseline_superset(manifest_ids, baseline_ids)` at `run` start, **before any media write** — which is both runnable at that point and strictly better, since it fails the operator in seconds instead of after a full two-leg ingest. When `baseline_manifest_path` is **absent**, the assertion is **skipped** and that fact is stamped in `preflight.json` (e.g. `baseline_superset_checked: false`). S1 fully covers the superset contract via the stronger condition when the key is present; there is no separate S2 re-assert.
- **Per-item outcomes** append to `legs/<stack_id>/items.jsonl` (see [Ground truth & label mapping](#d-media-identity-join)) using the per-item field list from the [PROV-01 field inventory](#s1-executable-contracts-normative) — resume never loses hard-fail tallies. `image_width` / `image_height` are positive ints read from the image at ingest so scoring never re-opens image bytes.
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
| tooling (new) | `apps/prototype-description-service/scripts/bench/corpus.py` | Manifest load via `load_manifest`, media resolution order, pin sets, superset check, `ItemOutcomeStore` |
| tooling (new) | `apps/prototype-description-service/scripts/bench/driver.py` | Ingest → analyze → cluster → **export** driver with resume; run-dir layout |
| tooling (new) | `apps/prototype-description-service/scripts/bench/export_map.py` | **S1 symbols:** `export_leg`, `require_cluster_success`, `load_leg_exports` (gate + persist public exports, preserve envelopes). **S2 symbols:** `map_cluster_labels_primary`, `map_cluster_labels_optimistic`, `to_face_metric_inputs`, `match_detection_boxes` (GT + label map → metric rows). No symbol is owned by both slices. |
| tooling (new) | `apps/prototype-description-service/scripts/bench/score.py` | Sole declaration of `BOX_IOU_MATCH = 0.5`; IoU/assignment helpers imported by `export_map` / `score_report` |
| tooling (new) | `apps/prototype-description-service/scripts/bench/score_report.py` | Dual sampling + label-map frames; `CrossbenchTier` rules; `accepted_set.json` / attrition; write report; imports `BOX_IOU_MATCH` from `score.py` |
| tooling (new) | `apps/prototype-description-service/scripts/bench/production_shaped_guard.py` | Named-stack allowlist + optional count attestation |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_preflight.py` | Fail-closed dim/profile/auth/missing-field with real payload shapes |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_corpus_superset.py` | Superset / partial-intersection blocker |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_resume.py` | Resume idempotency |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_stack_pair_consumption.py` | Base URL / stack_id not in pinned table → load fails |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_media_pin_public_unicast.py` | RFC1918 remote without LAN override → ingest refuses (mocked resolver) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_cluster_gate.py` | **S1.** Gate wording: every analyze job for a leg has reached a terminal outcome — success, or failure with `item_max_attempts` exhausted — and at least one succeeded. Three fixtured legs: (a) all analyze terminal with ≥1 success → gate ADMITS; (b) all terminal, zero successes → gate REFUSES (`cluster_gate_refused`, no cluster/export); (c) a non-terminal analyze still in flight → gate REFUSES. Export aborts when `cluster_job.json` missing/non-success. |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_e2e_frame.py` | Detector-miss → ID-miss accounting (dual frames) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_e2e_mocked.py` | One mocked end-to-end (both legs → report dir) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_export_map_rg015.py` | Export normalization invents no envelope metadata (rg-015) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_detection_localization.py` | [TEST-15] count-preserving box translation: count-only cell stays perfect, matched cell collapses to `TP = 0` |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_precision_precondition.py` | `ci_half_width_pp > δ/2` → DIRECTIONAL; image-level cluster bootstrap red-proofs; Holm on declared secondaries |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_manifest_version_seam.py` | exhaustiveness-asserted boxed fixture → `stranger_faces` from `name is None` + CONFIRMATORY-eligible; box-less / non-exhaustive → `stranger_faces == 0` + DIAGNOSTIC ceiling; `face_count != len(face_boxes)` → `gt_box_count_mismatch`; the retired subtraction is absent |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_attrition_floor.py` | fractional + absolute floor forms (reject `1`); floor resolves to item count before compare; `differential_attrition_exceeded` artifacts-then-refuse; zero-detection accepted item stays in recall denominator (goes red if dropped) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/fixtures/v2_boxed_detection.json` | Purpose-built v2 detection fixture (`manifest_version: 2`) with explicit `face_boxes` (`scene/tests/seed/golden.json` has zero boxes and cannot serve as a detection fixture) |
| tooling (new) | `apps/prototype-description-service/scripts/bench/__init__.py` | Package marker required for `uv run python -m scripts.bench.*` and documented import/test paths (`scripts.bench.*`); parent `scripts/` is the existing package shared with `eval_harness` |
| harness (**edit**) | `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` | Scoped to the optional `ImageDetection.matched_faces` field, the **clamped** `TP/FP/FN` branch that honours it, and the `0 <= matched <= min(pred, labeled)` bounds check. Default `None` → numerically identical existing behaviour (not byte-identical at the dataclass level — see the [localization pin](#b-constructing-metric-inputs)). Rationale + scope: [localization pin](#b-constructing-metric-inputs) |
| harness (**read, not edited**) | `apps/prototype-description-service/scripts/eval_harness/report.py` | Consumer under the additive `matched_faces` field; **READ, NOT EDITED** — takes the `None` path → numerically identical numbers |
| tests (**edit**) | `apps/prototype-description-service/scene/tests/test_eval_harness_face_metrics.py` | (1) bounds assertion `0 <= matched_faces <= min(pred_faces, labeled_faces)` → `matched_faces_out_of_bounds` on violation; (2) field is optional with default, added last (positional construction would break) |
| docs (new) | `apps/prototype-description-service/scripts/bench/README.md` | Package README (S3) |
| docs (new) | `docs/runbooks/fir-8-cross-stack-bench.md` | Operator runbook + teardown + license; carries the `opencv_version` upstream ask in the residual section |
| docs (edit) | this plan | v6.6 plan grounding (this commit) |

**Explicitly untouched:** `apps/prototype-description-service/recognition/**`, `db/migrations/**`, WP plugin, FIR23-STACK compose/deploy files.

**Edits outside `scripts/bench/` — the complete list is two files, not one.** `scripts/eval_harness/face_metrics.py` (the additive optional-with-default `matched_faces` field, added last, and its `detection_pr` branch) and `scene/tests/test_eval_harness_face_metrics.py` (bounds-check + optional-last-field assertions). Both are offline harness code, so the "no recognition-service code changes" constraint is intact. `scripts/eval_harness/report.py` is a **consumer that is READ, NOT EDITED** — see the [consumer inventory](#dual-frame-adapter-contract-fir-5-signatures-pinned). Any claim elsewhere in this plan that `face_metrics.py` is the *single* edit outside `scripts/bench/` is superseded by this paragraph.

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
```

Must cover:

1. **Preflight fail-closed (real shapes)** — mock `/health/detailed` body with `model_cache.profile` and `/ready` body with `checks[{name:database,status,detail}]`; insightface leg with `detail` lacking `pgvector_dimension=` or dim≠512 → `profile_or_dim_drift`; missing auth → `preflight_auth_failed`; 404 → `preflight_endpoint_missing`. Same for fir leg (expect 128 / face_pipeline).
2. **Superset blocker** — accepted `{1,2,3}`, baseline `{1,2}` → blocker; accepted `{1,2}`, baseline `{1,2,3}` → pass.
3. **Resume idempotency** — after partial `items.jsonl`, re-run does not re-POST terminal-success media; failed items re-attempt up to bounded retry.
4. **Consumption-table cross-check** (`test_stack_pair_consumption.py`) — stack_pair config with a `base_url` / `stack_id` not in the pinned table → `load_stack_pair` fails.
5. **Pin / public-unicast** (`test_media_pin_public_unicast.py`) — remote media URL resolving to RFC1918 without `allow_private_source` → ingest refuses (deterministic mocked resolver).
6. **Cluster gate (`test_cluster_gate.py`, S1)** — gate admits only when every analyze job for a leg has reached a terminal outcome — success, or failure with `item_max_attempts` exhausted — and at least one succeeded; export/score aborts when `cluster_job.json` missing or non-success; zero-success leg records `cluster_gate_refused`.
7. **Dual-frame cascade** — detector-miss synthetic pins e2e FN accounting vs FIR-5-native frame; frames call only `detection_pr` / `identification_pr` with pinned input types.
8. **One mocked E2E** — fake dual clients return fixed cluster payloads → report dir contains provenance (`preflight.json`), `accepted_set.json`, both legs + both sampling frames + label-map frames + tier label + license banner; no network; `score` uses no credentials.
9. **Detection localization ([TEST-15], `test_detection_localization.py`)** — the count-preserving translation fixture from the [localization pin](#b-constructing-metric-inputs): count-only cell perfect, matched cell `TP = 0`. Delete the IoU matching → the test fails. Bounds / optional-last-field proofs for `matched_faces` live in `scene/tests/test_eval_harness_face_metrics.py` (not a before/after `report.py` golden).
10. **Precision precondition (`test_precision_precondition.py`)** — a cell whose bootstrap `ci_half_width_pp > head_to_head_delta / 2` is stamped DIRECTIONAL even when the accepted set clears the floor (this is the case a size-only rule got wrong); the image-level resampling unit is load-bearing; Holm adjustment is applied across declared secondaries. Strip the half-width comparison → an under-precise cell reads CONFIRMATORY and the test fails.
11. **Detection exhaustiveness (`test_manifest_version_seam.py`)** — the `v2_boxed_detection.json` fixture (passing `face_count == len(face_boxes)`) derives `stranger_faces` from boxes and is CONFIRMATORY-eligible; a box-less / non-exhaustive load yields `stranger_faces == 0` with a DIAGNOSTIC ceiling; `face_count != len(face_boxes)` on the detection fixture → `gt_box_count_mismatch`; a box-less entry is excluded from detection frames with a counted exclusion. Assert no code path performs `face_count − len(present_identities)`.
12. **Attrition and floor (`test_attrition_floor.py`)** — fractional (`0.90`) and absolute (`135`) floor forms both resolve to an item count before any comparison (`resolved_floor_count = max(2, ceil(fraction × N))`); value `1` is load-rejected. On `differential_attrition_exceeded` (even when the accepted set is large — bias check, not size check), the test asserts **all three**: (1) accepted-set + attrition artifacts exist on disk; (2) exit is non-zero with `differential_attrition_exceeded`; (3) **no** precision/recall cells were emitted. Artifacts-without-exit or exit-without-artifacts cannot pass — a crash is not a correct refusal.
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
| `scripts/bench/corpus.py` | `load_bench_manifest(path, images_dir) -> GoldenManifest` (calls `load_manifest` against the v2 schema; asserts exhaustiveness on the detection fixture), `resolve_media_bytes(entry, images_dir, …)`, `assert_baseline_superset(manifest_ids, baseline_ids)`, `pin_media_hosts(...)`, `ItemOutcomeStore` | GT load via `load_manifest`; local-then-remote media resolution (optional `media_url_map_path`); pin + public-unicast on remote; append-only JSONL outcomes including `image_width`/`image_height`; optional `baseline_manifest_path` → `assert_baseline_superset` at `run` start |
| `scripts/bench/driver.py` | `run_leg(...)`, `run_pair(...)`, `run_cluster_phase(...)`, `init_run_dir(...)` | Per stack: resolve bytes → `analyze` + `wait_job` → `clustering_job(..., mode="sync")` → call `export_map.export_leg`; resume; budgets. **Owns no export symbol of its own** — see the export-ownership pin below |
| `scripts/bench/export_map.py` (**created in S1, extended in S2**) | `export_leg(client, run_dir, stack_id) -> LegExport`, `require_cluster_success(run_dir, stack_id)`, `load_leg_exports(run_dir, stack_id)` | S1 half only: gate on cluster outcome, fetch and persist the public exports under `exports/`, preserve upstream envelope fields ([rg-015]). The GT-mapping half (`map_cluster_labels_*`, `to_face_metric_inputs`) lands in S2 |
| `scripts/bench/production_shaped_guard.py` | `assert_named_bench_stack(endpoint, allowlist)` | Allow only configured stack_ids before writes |
| `scripts/bench/cross_stack_bench.py` | `main()`, subcommands `preflight` / `run` / `status` / (`score` wired in S2) | argparse CLI (`uv run python -m scripts.bench.cross_stack_bench` from `apps/prototype-description-service`) |
| `scripts/bench/tests/test_preflight.py` | real payload shape cases | red first |
| `scripts/bench/tests/test_corpus_superset.py` | partial intersection | red first |
| `scripts/bench/tests/test_resume.py` | partial JSONL resume | red first |
| `scripts/bench/tests/test_stack_pair_consumption.py` | unknown base_url / stack_id | red first |
| `scripts/bench/tests/test_media_pin_public_unicast.py` | RFC1918 without override | red first; mocked resolver |
| `scripts/bench/tests/test_cluster_gate.py` | gate: every analyze job for a leg has reached a terminal outcome — success, or failure with `item_max_attempts` exhausted — and at least one succeeded; (a) all terminal + ≥1 success → ADMITS; (b) all terminal + zero successes → REFUSES; (c) non-terminal analyze in flight → REFUSES; missing cluster outcome → `export_leg` aborts | red first; **S1**, because `require_cluster_success` is an S1 symbol |

#### S1 executable contracts (normative)

**(0) Export ownership — one symbol, and it lives where it is called from**

An earlier revision put `export_and_persist_leg` in S1's `driver.py` while assigning `export_map.py` and `export_leg` wholly to S2, then had S2 declare "S1 complete" as a dependency and assume the exports already existed. That is two names for one job on opposite sides of a slice boundary, and it made S1 unbuildable as written: [CF-7](#cf-7-score-credential-flow-pinned) requires `run` (S1) to persist every export, but the module that persists them was not scheduled until S2.

The pin: **`export_map.export_leg` is the only export symbol**, `export_map.py` is created in Slice 1 with its persist half, and Slice 2 extends the same module with the GT-mapping half. `export_and_persist_leg` does not exist. A module spanning two slices is fine and is stated here rather than discovered at implementation time; what is not fine is two symbols for one responsibility. `test_cluster_gate.py` consequently lands in **S1** (it tests `require_cluster_success`, an S1 symbol), not "S1 stub or S2".

**(a) Ingest wiring — media bytes**

Resolution order (per manifest entry):

1. Local file under `--images-dir` / `images_dir` + `entry.path` (sha256 verify when possible).
2. Else remote HTTPS URL from entry provenance / operator URL map — **CF-1 pin + public-unicast apply**.
3. Else `outcome=failed`, `error_code=media_unresolvable`.

Bytes are then POSTed via `RemoteSceneClient.analyze` multipart (no stack enroll API).

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
- `baseline_superset_checked` (bool — whether `baseline_manifest_path` was set and the superset assert ran)

`opencv_major` is **required** and satisfies the [PROV-01 constraint](#constraints) via the [attested source](#opencv-major-source-attested-not-probed). Writing `preflight.json` without it is a preflight failure, not a partial write: a run whose provenance cannot distinguish a 4.x from a 5.x stack is exactly the silent-comparability failure the field exists to prevent.

**Per-item** (each `legs/<stack_id>/items.jsonl` record; see [media identity join](#d-media-identity-join)):
- `manifest_media_id`, `stack_media_id` (int)
- `image_width` (positive int), `image_height` (positive int) — so scoring converts prediction boxes without re-opening image files
- `content_sha256` when ok
- `phase`, `outcome`, optional `error_code`

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
| root | `accepted_set_floor` | no | `0.90` | float in **(0, 1)** = fraction of accepted set; int **≥ 2** = absolute item count; value `1` (int or float) is **rejected at load** — see [floor policy](#floor-policy-normative) |
| root | `max_differential_attrition` | no | `0.05` | **float in closed range [0.0, 1.0]** — a **fraction** of `\|manifest\|` (not percentage points); compared at score time as `|one-sided-A − one-sided-B| / |manifest|`; value outside [0.0, 1.0] or non-numeric → load error **`max_differential_attrition_invalid`**; see [floor policy](#floor-policy-normative) |
| root | `allow_private_source` | no | `false` | CF-1 LAN override |
| root | `images_dir` | no | — | corpus root; CLI `--images-dir` wins when both are set |
| root | `manifest_sha256` | no | — | fail closed on manifest byte mismatch |
| root | `baseline_manifest_path` | no | — | optional path to a baseline/label manifest; when present, `run` loads it and calls `assert_baseline_superset(manifest_ids, baseline_ids)` before any media write; when absent, the assertion is skipped and stamped in `preflight.json` |
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

- `accepted_set_floor` accepts a **float in the open interval (0, 1)** read as a **fraction of the accepted set**, or an **int ≥ 2** read as an absolute item count. Default **0.90**. The value **`1` (int or float) is rejected at load** with an explicit message naming both accepted forms (`float in (0, 1)` or `int ≥ 2`) — `1` sits at the closed top of the old fraction range and below the absolute range, so it is unimplementable, and a floor of 1 makes the bootstrap meaningless.
- **Resolve before comparing.** `score` converts the configured value to an item count **once**: for a fraction, `resolved_floor_count = max(2, ceil(floor × N))` where `N = |accepted_set|`; for an absolute, `resolved_floor_count = int(floor)` (already ≥ 2 by the load rule). The `max(2, ·)` floor means **no configuration can resolve below 2**. Print `resolved_floor_count` in `accepted_set.json` alongside the raw config value. Every downstream comparison — the tier table row, the `accepted_set.json` `floor` field, this section — is against `resolved_floor_count`, an item count. Comparing a size against a fraction is a unit error that silently downgrades every cell (`150 < 0.90` is false, `150 < 135` is the intended test), so the resolved count is the only form allowed past the loader.
- **There is no pre-computable "power floor", and v6.3's was fiction.** The retired revision had `score` compute a floor "required by the power precondition" and fail closed with `floor_below_power_floor`. No such N exists a priori: the interval width depends on the between-leg disagreement pattern, which is unknown until the run completes. That error code is **removed**. The floor is an operator convenience that bounds attrition; the binding statistical gate is the [precision precondition](#precision-precondition-normative), evaluated on the interval actually obtained. A run may clear the floor and still yield only DIRECTIONAL cells — that is the correct and expected outcome when the corpus cannot resolve δ, not a configuration error.
- **Differential attrition is a separate and stricter check.** Size loss shared by both legs shrinks precision; loss concentrated on **one** leg is a *bias* — the surviving accepted set is enriched for media the weaker stack happens to handle, which flatters exactly the leg that failed. One-sided success is counted with the **same three-condition predicate** the scorer uses for accepted-set membership ((i) terminal-success ingest, (ii) terminal-success analyze with int `stack_media_id`, (iii) non-null export-side join) — a bias gate that used a looser two-condition predicate could disagree with the scoring denominator. `score` fails closed with `differential_attrition_exceeded` when |one-sided-A − one-sided-B| / |manifest| exceeds `max_differential_attrition` (default **0.05**), regardless of accepted-set size. A run can clear the floor and still be unscoreable on this ground.
- **Fail closed on the *metric*, not on the *report* — ordering is normative.** Aborting `score` outright would destroy the artifact that diagnoses the abort and would contradict this plan's own rule that attrition is [reported, not silently dropped](#constraints): the operator would be told their run is biased and handed nothing showing *where*. The order is fixed and stated identically in the [cell → tier table](#cell--tier-assignment-normative) and in `test_attrition_floor.py`: (1) write the accepted-set and attrition artifacts to disk **FIRST**; (2) then emit **NO** precision/recall cells; (3) then exit non-zero with `differential_attrition_exceeded`. Not DIRECTIONAL cells either — the defect is bias and a biased number is not made safe by a weaker label. Stamp `differential_attrition_exceeded` in the report header. Nothing is dropped, nothing biased is published, and the diagnosis survives the failure. The same ordering rule applies to any future scoring abort: diagnostics are written before the refusal, never after it.

**Proof**

- `uv run --extra dev pytest scripts/bench/tests/test_preflight.py scripts/bench/tests/test_corpus_superset.py scripts/bench/tests/test_resume.py scripts/bench/tests/test_stack_pair_consumption.py scripts/bench/tests/test_media_pin_public_unicast.py scripts/bench/tests/test_cluster_gate.py -q` green (from `apps/prototype-description-service`).
- Red-proofs:
  1. Mock `/ready` with database check `detail: "reachable; pgvector_dimension=128"` on the insightface endpoint (expected 512) → preflight raises `profile_or_dim_drift`; strip the assertion → test fails.
  2. Mock `/health/detailed` without `model_cache.profile` → `profile_or_dim_drift`; mock 401 → `preflight_auth_failed`.
  3. Baseline partial set → test fails if superset check deleted.
  4. Resume re-POSTs terminal-success ids if outcome store ignored.
  5. Stack-pair with foreign `stack_id` or base_url outside allowlist identity → load fails; delete the check → test fails.
  6. Mock DNS/resolver returning `10.0.0.5` for a remote media URL with `allow_private_source=false` → ingest refuses; strip enforcement → test fails.
  7. Stack entry without `opencv_major` → preflight raises `opencv_major_unattested` and writes **no** `preflight.json`; delete the required-field check → test fails. A second case asserts the bench package imports no `cv2` (see [OpenCV major source](#opencv-major-source-attested-not-probed)).
  8. `accepted_set_floor` load forms: value `1` (int or float) is **rejected at load** with a message naming both accepted forms; `0.9` (fraction) and `2` (absolute) are **accepted**; `1.5`, `-1`, and `"ninety"` also fail at load. A missing `bootstrap_seed`, `head_to_head_delta`, `primary_endpoint`, or `secondary_endpoints` key likewise fails at load ([rg-008]).
  9. Cluster gate ([TEST-06], `test_cluster_gate.py`) — three fixtured legs, not one exhausted-retry case: (a) all analyze terminal with ≥1 success → gate **ADMITS** and clustering runs; (b) all analyze terminal, zero successes → gate **REFUSES** (no cluster, no export, `cluster_gate_refused` in `legs/<stack_id>/leg_outcome.json`); (c) a non-terminal analyze still in flight → gate **REFUSES**. Loosen the gate to "any analyze attempted" or drop the ≥1-success conjunct → (b) or (c) fails the discrimination.

**Dependencies**: FIR23-STACK not required for unit tests (mocked). Live `run` requires both stacks up.

---

### Slice 2: Export + score via FIR-5 pure metrics

**Goal**: Consume exports already persisted by `run` (offline), map GT + exports into `ImageDetection` / `ImageIdentities` with label-space mapping, score detection P/R + identification P/R under sampling frames × label-map frames, emit tier-labeled head-to-head report under `benchmarks/results/crossbench-*/` with accepted-set + attrition artifacts.

**Files / functions**

| Module | Symbols | Responsibility |
| --- | --- | --- |
| `scripts/bench/score.py` | `BOX_IOU_MATCH = 0.5` (sole declaration), IoU / assignment helpers as needed | **Home of `BOX_IOU_MATCH`** — every other module (`export_map`, `score_report`, tests) **imports** it from here rather than re-declaring it |
| `scripts/bench/export_map.py` (**extended**, created in S1) | S2 half only: `map_cluster_labels_primary(...)`, `map_cluster_labels_optimistic(...)`, `to_face_metric_inputs(export, manifest, join, label_map) -> tuple[list[ImageDetection], list[ImageIdentities]]`, `match_detection_boxes(...)` | `export_leg` / `require_cluster_success` / `load_leg_exports` already exist from S1 — see the [export-ownership pin](#s1-executable-contracts-normative). No embedding/landmark requirement; **all** `ImageDetection`/`ImageIdentities` construction here or in `score_report` — never inside FIR-5; imports `BOX_IOU_MATCH` from `score.py` |
| `scripts/bench/score_report.py` | `CrossbenchTier` enum, `SAMPLING_FRAME_*`, `LABEL_MAP_*`, `compute_accepted_set(run_dir) -> AcceptedSet`, `write_accepted_set(...)`, `write_attrition(...)`, `score_head_to_head(run_dir) -> Path`, `build_dual_frames(...)`, `assign_tier(cell, ctx) -> CrossbenchTier` | Call **only** `detection_pr` / `identification_pr` with pinned signatures; tier rules; offline on run-dir; imports `BOX_IOU_MATCH` from `score.py` |
| `scripts/bench/cross_stack_bench.py` | subcommand `score` | Wire offline score path (**no credentials**) |
| `scripts/bench/tests/test_export_map_rg015.py` | fixture without `total` must not gain fabricated total | [rg-015] |
| `scripts/bench/tests/test_e2e_frame.py` | detector-miss dual-frame pin | required |
| `scripts/bench/tests/test_e2e_mocked.py` | dual fake clients → report artifacts | one mocked E2E |
| `scripts/bench/tests/test_detection_localization.py` | count-preserving translation fixture | **[TEST-15]** — count-only perfect, matched `TP = 0` |
| `scripts/bench/tests/test_precision_precondition.py` | bootstrap half-width / Holm / resampling-unit gates | required |
| `scripts/bench/tests/test_manifest_version_seam.py` | exhaustiveness / `stranger_faces` + eligibility ceiling on `v2_boxed_detection.json` | required |
| `scripts/bench/tests/test_attrition_floor.py` | floor forms (reject `1`; accept `0.9` / `2`); resolved item-count floor; on `differential_attrition_exceeded`: artifacts-exist AND non-zero-exit AND no-P/R-cells | required |
| `scripts/eval_harness/face_metrics.py` | optional `ImageDetection.matched_faces` + clamped `TP/FP/FN` branch + bounds check | one of **two** edits outside `scripts/bench/` (the other is `scene/tests/test_eval_harness_face_metrics.py`); default `None` preserves current behaviour |

**Report must include**

- Both legs' **detection P/R** and **identification P/R** under **both sampling frames** (`frame_fir5_native`, `frame_e2e`) and **both label-map frames** (`label_map_primary`, `label_map_optimistic`) (null where labels absent — honest nulls, not `0.0` purity invention).
- Cascade-honest e2e treatment ([EVAL-16]): detector miss → identification miss on that face in `frame_e2e`.
- Fixed denominators via `score/accepted_set.json` + attrition table ([EVAL-19 operationalized](#eval-19-operationalized-accepted-set)).
- Provenance block ([PROV-01]) from the full inventory in [PROV-01 field inventory](#s1-executable-contracts-normative) (per-leg `preflight.json` + run-level + per-item fields).
- `license_notice` / `license_banner` for the insightface leg on intermediate JSON and HTML.
- Per-cell `CrossbenchTier` from the assignment table (not attributed to FIR-5).

**Proof**

- Mocked E2E green; export mapper rg-015 test green; dual-frame test green. (Cluster gate is an S1 proof — not re-run as an S2 gate.)
- Red-proof: strip provenance consumer → test asserting preflight keys fails; set `total=len(rows)` in mapper → rg-015 test fails; remove FN injection → e2e frame test fails; pass raw unmapped `cluster_label` as `predicted` without mapping → identification unit test fails; mutate accepted set differently per leg → score assert fails.

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

- [ ] Loaded this plan, eval_harness remote client, health probes, media identity export keys, 001 schema table list, FIR23-STACK endpoint/reset docs.
- [ ] Confirmed no recognition-service files in the intended diff.
- [ ] FIR23-STACK dependency recorded as BLOCKING for live runs (unit tests unblocked).
- [ ] Package root pinned: `apps/prototype-description-service/scripts/bench/`.

### Checklist for Slice 1: Bench CLI skeleton

- [ ] Package under `apps/prototype-description-service/scripts/bench/` + `cross_stack_bench.py` subcommands `preflight` / `run` / `status`
- [ ] `StackPairConfig` validates the full [key schema](#s1-executable-contracts-normative) at load ([rg-008]) against the FIR23-STACK consumption table (dev: insightface/512; fir: face_pipeline/128; refuse unknown stacks / foreign base URLs / deploy-ownership keys)
- [ ] Preflight uses real `/ready` + authenticated `/health/detailed` contracts; stable codes; `opencv_major` required (`opencv_major_unattested` when absent); writes per-leg `preflight.json` (PROV-01) with flat `opencv_major` / `opencv_major_source`
- [ ] Manifest via `load_manifest` (`--manifest` + `--images-dir`); `manifest.sha` written
- [ ] Flow: media resolve (local then remote+CF-1 pin) → analyze → cluster (every analyze job for a leg has reached a terminal outcome — success, or failure with `item_max_attempts` exhausted — and at least one succeeded) → **S1 `export_map` symbols only** (`export_leg` / `require_cluster_success` / `load_leg_exports` — persist; no GT mapping); zero analyze successes → no cluster/export, `cluster_gate_refused` in `legs/<stack_id>/leg_outcome.json`; run-dir tree as specified
- [ ] When config key `baseline_manifest_path` is present, baseline superset blocker (`assert_baseline_superset(manifest_ids, baseline_ids)`) asserted against the **manifest** set at `run` start, before any media write; when absent, skipped and stamped in `preflight.json`; public-unicast default on remote fetches; optional `media_url_map_path` for operator URL map / corpus overlay
- [ ] Append-only `items.jsonl` resume (skip terminal-success; bounded retry on failures); each ok record carries int `stack_media_id`, `image_width`, `image_height`
- [ ] `status` reads run.json + items.jsonl (no network)
- [ ] Wall-clock + job-poll budgets enforced in CLI
- [ ] Named-stack allowlist guard before writes
- [ ] Unit tests: preflight, superset, resume, consumption-table, public-unicast, cluster-gate — each observed red first
- [ ] Handoff decision for S1 with verification commands

### Checklist for Slice 2: Export + score

- [ ] Score offline on run-dir only (exports already persisted by S1; no credentials)
- [ ] Accepted set = ingest + analyze + int `stack_media_id` + successful export-side join on both legs, computed once; export-side absence is join attrition (`phase=join`); empty face list is a scored miss, not a join failure; both join sides are ints with no coercion; primary + optimistic label-space mapping
- [ ] **S2 `export_map` symbols only** (`map_cluster_labels_primary` / `map_cluster_labels_optimistic` / `to_face_metric_inputs` / `match_detection_boxes`); S1 persist symbols already exist — not re-owned; mapper preserves upstream envelope fields already written by S1 ([rg-015]); no embedding/landmark requirement
- [ ] FIR-5 pure `detection_pr` / `identification_pr` only on constructed `ImageDetection` / `ImageIdentities`; the harness edits are the optional-with-default `matched_faces` field (added last) and `scene/tests/test_eval_harness_face_metrics.py` bounds + optional-last assertions; `report.py` is READ, NOT EDITED
- [ ] Dual sampling frames + dual label-map frames side-by-side; **`frame_e2e` pinned as the sole CONFIRMATORY sampling frame**
- [ ] `score/accepted_set.json` + attrition table ([EVAL-19]); `CrossbenchTier` cell rules applied first-match-wins
- [ ] Detection P/R is **IoU-matched**; count-only retained as a DIAGNOSTIC companion; [TEST-15] translation red-proof observed red first
- [ ] Precision precondition implemented: declared δ, image-level cluster bootstrap, `ci_half_width_pp` stamped per cell, half-width ≤ δ/2, Holm across declared secondaries
- [ ] Floor policy: resolved item-count floor (`max(2, ceil(fraction × N))`); `differential_attrition_exceeded` order: (1) write accepted-set + attrition artifacts FIRST; (2) emit NO P/R cells; (3) exit non-zero with `differential_attrition_exceeded`
- [ ] Detection exhaustiveness asserted on `v2_boxed_detection.json`; the `face_count − len(present_identities)` subtraction is absent from the codebase
- [ ] Report under `benchmarks/results/crossbench-*/` with preflight provenance (incl. `opencv_major` + its source), cascade honesty, license banner, tier labels, and the exhaustiveness eligibility ceiling
- [ ] Mocked E2E + rg-015 + dual-frame + localization + `test_precision_precondition` + exhaustiveness + attrition tests green (cluster gate is S1)
- [ ] Handoff decision for S2

### Checklist for Slice 3: Runbook + teardown

- [ ] `docs/runbooks/fir-8-cross-stack-bench.md` complete per outline
- [ ] License posture explicit; insightface non-exposure rule explicit
- [ ] Teardown cites FIR23-STACK reset only
- [ ] Failure routing table (stack gap → FIR23-STACK; CLI → FIR-8; embedding diagnostic → optional upstream)
- [ ] Commands match CLI help ([rg-006]); package root / import path documented
- [ ] Handoff decision for S3 / task close path prepared

## Review Readiness

- [ ] No recognition-service or deploy-YAML changes slipped into the branch. The two expected offline-harness edits (`face_metrics.py`, `test_eval_harness_face_metrics.py`) are present and are the **only** files outside `scripts/bench/`; a third such file is a review stop.
- [ ] Boundary adapters do not invent pagination/provenance metadata ([rg-015]).
- [ ] Preflight field claims match `register_health_probes` + `health.py` (no invented top-level dim fields).
- [ ] Live run path blocked in docs until FIR23-STACK delivers `acx-dev-fir` (not silently mocked as success).
- [ ] Handoff decisions record verification + dependency status.
- [ ] Review findings recorded in MCP only (never pasted into this plan).

## Stretch Goals

- [ ] Optional HTML index linking multiple historical crossbench runs.
- [ ] Prometheus/log-free local progress TUI — only if it does not expand scope past one slice.
- [ ] Optional upstream embedding-export diagnostic (separate service task) if purity sweeps become required later.

## Success Criteria

- [ ] Operator can preflight + run + score a corpus against **both** stacks with **zero** recognition-service code changes in the FIR-8 diff (two offline-harness files are in scope and enumerated; see [Target Outcome](#target-outcome) item 6).
- [ ] S1 and S2 are implementable and green against **today's** v2 harness — no FIR-8 step calls a symbol FIR-11 has not yet created; detection fixture is `v2_boxed_detection.json` (`manifest_version: 2`); no alternate manifest schema, no `load_legacy_manifest`.
- [ ] Preflight fails closed on dimension or profile drift / auth failure / missing endpoints / unattested `opencv_major` with the codes in the [stable error codes table](#stable-error-codes-normative).
- [ ] Cluster phase runs per leg; export gated on success.
- [ ] Scoring uses public bbox/cluster metadata + manifest GT + label mapping → detection P/R + identification P/R; dual sampling and label-map frames present, with `frame_e2e` + `label_map_primary` pinned as the only CONFIRMATORY combination.
- [ ] Detection P/R is localization-aware (IoU-matched), and the [TEST-15] count-preserving translation fixture proves the metric can go red.
- [ ] No cell reaches CONFIRMATORY without a stamped `ci_half_width_pp ≤ head_to_head_delta / 2` from the image-level cluster bootstrap on the paired accepted set.
- [ ] The head-to-head gate number is explicitly **withheld** until a production corpus passes FIR-8's own exhaustiveness assertion (`face_count == len(face_boxes)` on detection-scoring entries); a box-less production run ships as a DIRECTIONAL orchestration dry run and says so in the artifact. FIR-11 Slice 2 may later supply a larger boxed corpus but is not required for any FIR-8 code path.
- [ ] Superset / partial-intersection blocker enforced.
- [ ] Resume does not reprocess terminal-success items; bounded retry on failures.
- [ ] Head-to-head report exists under `benchmarks/results/crossbench-*/` with EVAL-16 / EVAL-19 (`accepted_set.json`) / PROV-01 (`preflight.json`) discipline and insightface license banner.
- [ ] Runbook forbids commercial exposure of the insightface stack and points teardown at FIR23-STACK.
- [ ] v5 in-service vehicle explicitly superseded (decision #2951; history at `bc97ff4b`).
- [ ] Single package root `apps/prototype-description-service/scripts/bench/` documented and used by tests.

## Residual risks (pinned)

| Risk | Residual | Mitigation |
| --- | --- | --- |
| FIR23-STACK delayed | Live E2E blocked | Unit/mocked path still merges; live run is operator gate |
| Health payload shape differs across deploys | Preflight false fail/pass | Pin field names to real `/ready` + `/health/detailed` contracts; fail closed on missing fields |
| Public-unicast pin vs LAN media store | Operator needs private fetch | Explicit `allow_private_source` only; documented residual; constrains CLI outbound fetches only |
| Production-shaped guard without DB counts API | Weaker than v5 marker rail | Named stack allowlist + operator attestation; escalate if FIR23-STACK adds a count diagnostic |
| Insightface NC misuse | License | Runbook + report `license_notice`; stack must not sit on product ingress |
| No public embeddings | Purity sweeps impossible on cross-stack path | Explicit OOS; optional upstream diagnostic ask |
| **`opencv_major` is operator-attested, not service-reported** | A wrong attestation produces a confident-looking but false provenance stamp — the exact silent-comparability failure the field exists to prevent, now merely relocated from absent to unverified | Required field, fail closed when absent, `opencv_major_source: operator_attested` rendered in the report; upstream ask filed for `model_cache.opencv_version` with the drift-compare branch pre-written. **This is a declared weak link, not a solved problem.** |
| **Golden150 cannot power a small head-to-head gap** | Even at full corpus, the image-level bootstrap interval on Δ may stay wider than δ, so the honest output is "no resolvable difference" rather than a winner | Precision precondition fails such cells closed to DIRECTIONAL rather than reporting them as gate-eligible. If the operator needs a resolvable answer at δ = 10pp, the corpus must grow — that is a **corpus decision, not a scoring-code decision**, and FIR-8 must not paper over it |
| **Detection FP eligibility depends on a boxed exhaustive corpus** | FIR-8 can be fully implemented and merged while its headline number stays unavailable until production media carry complete `face_boxes` | Exhaustiveness is FIR-8's own assertion (not an FIR-11 flag); detection unit tests use `v2_boxed_detection.json`. FIR-11 Slice 2 may later supply a larger boxed corpus but is not a code-path dependency. Do **not** let a box-less DIRECTIONAL number get quoted as the head-to-head result |
| **IoU threshold is a single fixed 0.5** | A stack whose boxes are systematically tighter or looser than GT is penalised by the threshold, not by its detection quality | `BOX_IOU_MATCH = 0.5` is declared once in `scripts/bench/score.py` and imported everywhere else (detection pin and optimistic label map share one threshold). Report the matched-vs-count gap per leg so a threshold artifact is visible as a *both-legs* shift; a sweep over IoU is a stretch goal, not a gate input |

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
