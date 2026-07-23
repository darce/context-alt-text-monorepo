# FIR-8. Cross-stack face-pipeline bench orchestration

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok (docs-only plan authoring)
> - **Plan version**: v6.1 — supersedes in-service bench supervisor (v5); re-scopes to cross-stack orchestration aligned with FIR23-STACK + QA v2; **changelog (v6→v6.1)**: real preflight contracts, explicit cluster phase, feasible public-export scoring scope, dual scoring frames, crossbench tier enum, ingest→analyze→cluster→export flow, pinned FIR23-STACK consumption table, single package root
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
- **Fixed denominators** ([EVAL-19]): both legs share the same accepted media set / labeled face denominators; do not shrink denominators per leg after partial detection failure.
- **Per-run provenance** ([PROV-01]): every report stamps stack identity (base URL / compose project name), model ids, `PGVECTOR_DIM`, corpus hash, CLI + harness code SHAs.
- **Canon**: heuristics v0.12.3; distilled refs `~/Development/heuristics-canon-research/distilled/ml-systems/janus-benchmark-c.md` (pooling-unit / cascade eval), `handbook-face-recognition.md`.

## Workflow Principles

- **Drive stacks as black boxes** via public HTTP APIs already used by `scripts/eval_harness/remote_client.py` (`analyze`, `wait_job`, `media_identities`, `clustering_job`, `clusters`, `cluster_members`). Prefer extending that client or a thin wrapper in the bench package over ad-hoc curl. **Note**: `RemoteSceneClient` exposes **no** health methods — preflight performs its own authenticated GETs (see [Real preflight contract](#real-preflight-contract)).
- **CLI is the supervisor.** Wall-clock budget + per-item / queued-age timeouts live in the CLI process. No service-side single-live-run index.
- **Idempotent resume.** Per-item ingest/analyze outcomes persist under the run directory so a crashed run continues without double-billing work that already succeeded.
- **Fail closed on preflight drift.** Dimension or profile mismatch on either stack aborts before any media write.
- **Explicit cluster phase.** After all analyze jobs for a leg succeed (within budget), call `RemoteSceneClient.clustering_job(tenant_id, mode="sync")`, persist the job outcome, and **gate export on cluster-job success**.
- **Stack gaps escalate out.** Missing ingress, wrong dim in compose, broken reset path → FIR23-STACK ticket / decision, not a FIR-8 code fork into deploy YAML.

## Terminology

| Term | Meaning in this plan |
| --- | --- |
| **Dev stack** | Existing recognition deployment: `RECOGNITION_FACE_PIPELINE_PROFILE=insightface`, `PGVECTOR_DIM=512`, public API base (operator-configured; typically `https://dev.api.altcontext.com`). **Internal bench only** for commercial product posture. |
| **`acx-dev-fir` stack** | FIR23-STACK profile-pinned isolated stack: compose project + network + DB `alt_context_dev_fir` @ `PGVECTOR_DIM=128`, profile `face_pipeline`, ingress `fir.api.altcontext.com`. FIR candidate leg. |
| **Stack pair** | Named config binding both base URLs, API keys / tenant ids, expected `(profile, dim)` pairs, and optional LAN override flag for private media hosts. Validated at load against the [FIR23-STACK consumption table](#fir23-stack-consumption-table-pinned) ([rg-008]); unknown `stack_id` values are refused. |
| **Corpus** | Fixed media set for a run (paths or resolvable HTTPS URLs). Accepted set = media that pass CLI validation before ingest. |
| **Leg** | Full **ingest → analyze → cluster → export** path against **one** stack. A head-to-head run has two legs: `insightface@512` and `face_pipeline@128`. |
| **Superset baseline / accepted set** | Any uploaded or declared baseline / label artifact's `media_id` (or sha256) set **must be a SUPERSET** of the run's accepted set. Partial intersection = **blocker** (do not silently score a subset). |
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
3. CLI **ingests** media (CLI-side fetch + pin), **analyzes** on both stacks (`analyze` + `wait_job`), runs **cluster** (`clustering_job(..., mode="sync")`), **exports** clusters/assignments; persists per-item + cluster outcomes; resumes safely.
4. CLI maps exports into FIR-5 `ImageDetection` / `ImageIdentities`, scores detection P/R + identification P/R under both frames (FIR-5-native + end-to-end), emits a tier-labeled head-to-head report under `benchmarks/results/crossbench-*/` with provenance + cascade-honest denominators.
5. Runbook documents license posture, preflight, run, score, and **stack-scoped teardown** via FIR23-STACK's documented reset path (not a new FIR-8 reset invention).
6. Zero recognition-service source edits land in this task's commits.

## Context Loading (read before implementation)

| Order | Path | Why |
| --- | --- | --- |
| 1 | This plan (v6.1) end-to-end | Locked scope, dependency boundary, carried invariants, slices |
| 2 | `apps/prototype-description-service/scripts/eval_harness/remote_client.py` | Existing HTTP client (`analyze`, `wait_job`, `media_identities`, `clustering_job`, `clusters`, …) — **no health methods** |
| 3 | `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` | Pure `ImageDetection` / `ImageIdentities` + `detection_pr` / `identification_pr` — scoring legs |
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

Import path used by tests and CLI:

```bash
# from apps/prototype-description-service (or with that dir on PYTHONPATH)
python -m scripts.bench.cross_stack_bench --help
python -m pytest scripts/bench/tests/ -q
```

```text
apps/prototype-description-service/scripts/bench/
  __init__.py
  cross_stack_bench.py          # CLI entry (argparse subcommands)
  stack_pair.py                 # load + validate stack-pair config against FIR23-STACK table
  preflight.py                  # own authenticated GETs; dim + profile fail-closed
  corpus.py                     # accept set, media source pin, per-item outcomes
  driver.py                     # ingest → analyze → cluster both stacks; resume
  export_map.py                 # pull clusters/assignments; map to ImageDetection/ImageIdentities
  score_report.py               # dual-frame scoring; crossbench tier enum; write report dir
  production_shaped_guard.py    # refuse non-named stacks with nonzero core tables
  tests/                        # unit + one mocked E2E
docs/runbooks/
  fir-8-cross-stack-bench.md    # operator runbook (S3)
benchmarks/results/crossbench-*/  # gitignored run outputs
```

**Operator flow**

1. Confirm FIR23-STACK has `acx-dev-fir` healthy next to dev.
2. `python -m scripts.bench.cross_stack_bench preflight --config stack-pair.yaml` → both sides green or abort.
3. `… run --config … --corpus … --out benchmarks/results/crossbench-<stamp>/` → ingest+analyze+cluster both legs with resume file.
4. `… score --run-dir …` → dual-frame FIR-5 pure metrics + head-to-head HTML/JSON (export aborts if cluster phase missing/failed).
5. Teardown: FIR23-STACK stack-scoped DB reset for the FIR stack (and optional dev-bench tenant wipe per runbook) — **not** a new recognition purge phase.

---

## Superseded: v5 in-service vehicle

v5 specified an **in-service** async single-live-run bench supervisor inside the recognition worker: state machine over `recognition_bench_runs`, `uq_bench_single_live`, purge-before-terminal, deployment marker rail, boot-coupled license gate, non-blocking tick contract, and `/admin` bench routes. That vehicle is **superseded** by **per-model isolated stacks** (FIR23-STACK): exclusivity, no mixed-space reads, and teardown via stack-scoped DB reset are structural properties of the deploy topology, not application supervisor features. Re-implementing them inside the worker would duplicate FIR23-STACK ownership and re-open dual-space foot-guns. **Do not delete git history** — v5 plan text is recoverable at commit **`bc97ff4b`**. Decision **#2951** records the supersession. The rest of this document is the v6 / v6.1 scope only.

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

**Rule**: if a needed field is absent from this table, the gap is a **FIR23-STACK** deliverable or an operator attestation — not a silent FIR-8 invention. `stack_pair.py` rejects any `stack_id` not in the allowlist and rejects config keys that claim deploy ownership (compose project, network, volume paths).

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

### Stable error codes (normative)

| Code | When |
| --- | --- |
| `preflight_auth_failed` | Authenticated `/health/detailed` returns 401/403 or auth dependency rejects the key |
| `preflight_endpoint_missing` | `/ready` or `/health/detailed` not reachable as that route (404 / connection refused treated as missing endpoint for this purpose) |
| `profile_or_dim_drift` | Profile missing/mismatch, database check not OK, dim token absent, or dim int ≠ expected |

Mock fixtures in tests must use these **real** payload shapes (not invented field names like top-level `pgvector_dimension` or `profile` outside `model_cache`).

---

## Feasible scoring scope

Public exports (media identities + cluster members) carry **bbox / cluster metadata only** — confirmed by `MediaIdentityService.list_by_media_ids` payload keys and `ClusterMemberResponse` (no embedding vector, no landmark coordinates on the public path).

**In scope for cross-stack scoring (Slice 2)**

- Map exports → `face_metrics.ImageDetection` (count-based detection P/R via `detection_pr`).
- Map exports → `face_metrics.ImageIdentities` (named identification P/R via `identification_pr`, using cluster labels / labeled assignments available on the public surface).
- Dual frames: FIR-5-native + end-to-end inclusive ([End-to-end scoring frames](#end-to-end-scoring-frames)).

**Explicitly OUT OF SCOPE for the cross-stack path**

- FIR-5 **score-face / run-record** surfaces that assume full describe/analyze run records with embedding-bearing fields.
- **Clustering purity sweeps** and any metric that requires raw embedding vectors or landmarks.
- Inventing an admin/diagnostic export of embeddings from FIR-8.

**OPTIONAL upstream ask** (separate service task, **not FIR-8**): an authenticated embedding-export diagnostic route (or opt-in debug field) for offline purity / embedding-space audits. Document the ask in the runbook residual section; do not block FIR-8 on it.

---

## End-to-end scoring frames

FIR-5 pure functions score **only the rows they are given** — they do not themselves inject detector-miss cascade. The adapter owns cascade honesty.

**Adapter construction (normative)**

1. Build the **detected set** from public export rows (per media: face counts, predicted identity labels from cluster labels).
2. **FIR-5-native frame** (`sampling_frame=SAMPLING_FRAME_FACE_ID`): call `detection_pr` / `identification_pr` on rows derived only from exported detections (FIR-5-native sampling — excludes pure detector misses from the identification accounting by construction of the input rows). Report under key `frame_fir5_native`.
3. **End-to-end frame** (`sampling_frame=SAMPLING_FRAME_E2E`): **before** calling the pure functions, inject labeled-but-undetected faces as FN rows (`ImageDetection` undershoot and/or `ImageIdentities` with empty predicted + labeled name present). Report under key `frame_e2e`. Detector miss → identification miss is accounted here ([EVAL-16]).
4. Head-to-head report prints **both frames side-by-side** per leg; never silently replace one with the other.

**Unit test (required)**: synthetic corpus where one labeled face is absent from export → `frame_e2e` identification FN increments and detection FN increments; `frame_fir5_native` identification denominator does not charge that miss the same way (pins detector-miss→ID-miss accounting).

Constants live in `score_report.py` (or `export_map.py`): `SAMPLING_FRAME_FACE_ID`, `SAMPLING_FRAME_E2E` — plan-level names for the two frames; not FIR-5 library enums.

---

## Tier vocabulary

The three-tier report label set **`CONFIRMATORY` / `DIRECTIONAL` / `DIAGNOSTIC`** is a **new crossbench report enum** defined in `score_report.py`, sourced from QA-digest / canon convention for head-to-head bench claims. It is **not** a FIR-5 enum and must not be attributed to FIR-5 modules.

Separately: FIR-5 / eval harness surfaces carry **per-metric DIRECTIONAL disclosure qualifiers** in the QA/canon sense (e.g. underpowered slices report directional-only and cannot enter a gate decision — see commercial-face-identity scope language) plus harness **`provider_disclosure`** stamps on describe responses. Those are **not** the three-tier crossbench enum. Crossbench reports may *reference* FIR-5 directional disclosure text when a leg is underpowered, but the tier stamp itself is owned by `score_report.py`.

---

## Carried-forward invariants (orchestration layer)

Adapt v5 review-hardened invariants; **do not re-litigate**. Enforcement lives in the **CLI**, not the recognition service.

### CF-1. Baseline / corpus ingest contract

- Uploaded or declared baseline / label artifact `media_id` (or content-sha) set **must be a SUPERSET** of the run's accepted set. **Partial intersection = blocker** (exit non-zero; do not score a silent subset).
- **Per-item ingest outcomes** persist under the run directory (`items.jsonl` or equivalent): `media_id`, outcome (`ok`/`failed`), optional `error_code`, `content_sha256` when ok — so resume never loses hard-fail tallies.
- **There is no stack-side enroll API.** Media bytes are obtained by the **CLI's own outbound fetches** (local paths or HTTPS URLs), then submitted via `RemoteSceneClient.analyze` multipart. The pinned-resolved-address set + public-unicast enforcement therefore constrain the **CLI's own outbound media fetches**, not a recognition-service enroll route.
- **Pinned resolved-address SET** for each media source host: at ingest, resolve full address set and persist; at fetch, connect only to pinned addresses (anti DNS-rebinding).
- **Public-unicast enforcement**: reject link-local, RFC1918, loopback unless explicit **`allow_private_source: true`** LAN override in stack-pair config (operator-acked residual).

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

### CF-4. Bounded runs

- Wall-clock budget per bench run (config: `wall_clock_timeout_sec`, default **3600**).
- Queued-age / per-job poll budget (config: `job_poll_timeout_sec`, default **600**; align with `RemoteSceneClient` poll bounds).
- Enforced by the **CLI** (cancel outstanding polls, write partial outcomes, exit non-zero) — **not** a service supervisor.

### CF-5. Scoring discipline (QA + canon)

- [EVAL-16] cascade honesty via end-to-end frame injection in the adapter.
- [EVAL-19] fixed denominators across stacks.
- [PROV-01] per-run provenance: stack identity, model ids, corpus hash, code SHAs.
- Tier labels: crossbench enum in `score_report.py` (`CONFIRMATORY` / `DIRECTIONAL` / `DIAGNOSTIC`) — see [Tier vocabulary](#tier-vocabulary). Do not invent additional tier names beyond that enum.

### CF-6. Cluster-before-export

- Per leg, after analyze jobs complete: `client.clustering_job(tenant_id, mode="sync")`.
- Persist outcome under run dir (e.g. `legs/<stack_id>/cluster_job.json` with status payload).
- `export_map.export_leg` / score path **aborts** if cluster outcome is missing or non-success (mocked test required).

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
| tooling (new) | `apps/prototype-description-service/scripts/bench/preflight.py` | Own GETs to `/ready` + `/health/detailed`; real field contracts; stable error codes |
| tooling (new) | `apps/prototype-description-service/scripts/bench/corpus.py` | Accept set, pin sets (CLI outbound fetches), superset check, per-item outcomes |
| tooling (new) | `apps/prototype-description-service/scripts/bench/driver.py` | Ingest → analyze → cluster driver with resume |
| tooling (new) | `apps/prototype-description-service/scripts/bench/export_map.py` | Export clusters/assignments; map to `ImageDetection` / `ImageIdentities`; gate on cluster success |
| tooling (new) | `apps/prototype-description-service/scripts/bench/score_report.py` | Dual-frame scoring; crossbench tier enum; write `benchmarks/results/crossbench-*/` |
| tooling (new) | `apps/prototype-description-service/scripts/bench/production_shaped_guard.py` | Named-stack allowlist + optional count attestation |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_preflight.py` | Fail-closed dim/profile/auth/missing-field with real payload shapes |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_corpus_superset.py` | Superset / partial-intersection blocker |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_resume.py` | Resume idempotency |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_cluster_gate.py` | Export aborts when clustering was not run / failed |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_e2e_frame.py` | Detector-miss → ID-miss accounting (dual frames) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_e2e_mocked.py` | One mocked end-to-end (both legs → report dir) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_export_map_rg015.py` | Export normalization invents no envelope metadata (rg-015) |
| docs (new) | `apps/prototype-description-service/scripts/bench/README.md` | Package README (S3) |
| docs (new) | `docs/runbooks/fir-8-cross-stack-bench.md` | Operator runbook + teardown + license |
| docs (edit) | this plan | v6.1 plan hardening (this commit) |

**Explicitly untouched:** `apps/prototype-description-service/recognition/**`, `db/migrations/**`, WP plugin, FIR23-STACK compose/deploy files.

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/remote_client.py` | Prefer reuse / thin wrap for analyze/cluster/export HTTP; **no health methods** |
| `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` | Face P/R pure functions (`ImageDetection`, `ImageIdentities`) |
| `apps/prototype-description-service/api/main.py` `register_health_probes` | `/ready` + `/health/detailed` payload shapes |
| `apps/prototype-description-service/recognition/application/health.py` | Database detail string with `pgvector_dimension=` |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/stores.py` | Public media identity export keys |
| `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Core identity-adjacent table list |
| git `bc97ff4b` | Recoverable v5 plan text (superseded) |

## Verification Strategy

### Deterministic tests (required)

```bash
# from apps/prototype-description-service
python -m pytest scripts/bench/tests/ -q
```

Must cover:

1. **Preflight fail-closed (real shapes)** — mock `/health/detailed` body with `model_cache.profile` and `/ready` body with `checks[{name:database,status,detail}]`; insightface leg with `detail` lacking `pgvector_dimension=` or dim≠512 → `profile_or_dim_drift`; missing auth → `preflight_auth_failed`; 404 → `preflight_endpoint_missing`. Same for fir leg (expect 128 / face_pipeline).
2. **Superset blocker** — accepted `{1,2,3}`, baseline `{1,2}` → blocker; accepted `{1,2}`, baseline `{1,2,3}` → pass.
3. **Resume idempotency** — after partial `items.jsonl`, re-run does not re-POST successful media; failed items retry once within budget.
4. **Cluster gate** — export/score aborts when `cluster_job.json` missing or non-success.
5. **Dual-frame cascade** — detector-miss synthetic pins e2e FN accounting vs FIR-5-native frame.
6. **One mocked E2E** — fake dual clients return fixed cluster payloads → report dir contains provenance + both legs + both frames + tier label; no network.

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

### Slice 1: Bench CLI skeleton — config, preflight, corpus driver (+ cluster phase)

**Goal**: Runnable CLI that validates a stack pair against the consumption table, fails closed on dim/profile drift using real health contracts, and drives corpus **ingest → analyze → cluster** on both stacks with durable per-item + cluster outcomes and resume.

**Files / functions (normative names)**

| Module | Symbols | Responsibility |
| --- | --- | --- |
| `scripts/bench/stack_pair.py` | `load_stack_pair(path) -> StackPairConfig`, `StackEndpoint` dataclass, `FIR23_STACK_ALLOWLIST` | Parse config; require keys: `stack_id`, `base_url`, `api_key` env ref, `tenant_id` env ref, `expected_profile`, `expected_pgvector_dim`; validate `stack_id` ∈ consumption table; reject unknown keys / unknown stacks (fail-closed, [rg-008]) |
| `scripts/bench/preflight.py` | `preflight_stack(endpoint) -> PreflightResult`, `preflight_pair(pair) -> None`, `PreflightError` | Own GETs: `/ready` + authenticated `/health/detailed`; parse profile + dim per [Real preflight contract](#real-preflight-contract); raise with stable codes |
| `scripts/bench/corpus.py` | `build_accepted_set(...)`, `assert_baseline_superset(accepted, baseline)`, `pin_media_hosts(...)`, `ItemOutcomeStore` | Superset blocker; CLI outbound pin + public-unicast; JSONL outcome store |
| `scripts/bench/driver.py` | `run_leg(endpoint, items, outcome_store, *, budgets)`, `run_pair(...)`, `run_cluster_phase(...)` | For each stack: CLI ingest (fetch bytes) → `RemoteSceneClient.analyze` + `wait_job` → `clustering_job(tenant_id, mode="sync")`; persist cluster outcome; respect budgets |
| `scripts/bench/production_shaped_guard.py` | `assert_named_bench_stack(endpoint, allowlist)` | Allow only configured stack_ids before writes |
| `scripts/bench/cross_stack_bench.py` | `main()`, subcommands `preflight` / `run` / `status` | argparse CLI (`python -m scripts.bench.cross_stack_bench`) |
| `scripts/bench/tests/test_preflight.py` | real payload shape cases | red first |
| `scripts/bench/tests/test_corpus_superset.py` | partial intersection | red first |
| `scripts/bench/tests/test_resume.py` | partial JSONL resume | red first |
| `scripts/bench/tests/test_cluster_gate.py` | missing cluster outcome | may land with S1 driver stub or S2 export; required before score path merges |

**Stack-pair config shape (normative)**

```yaml
# example only — not a committed secret file
wall_clock_timeout_sec: 3600
job_poll_timeout_sec: 600
allow_private_source: false
stacks:
  - stack_id: acx-dev-insightface
    role: insightface_judge
    base_url: https://dev.api.altcontext.com   # operator-local value
    expected_profile: insightface
    expected_pgvector_dim: 512
    api_key_env: ACX_BENCH_DEV_API_KEY
    tenant_id_env: ACX_BENCH_DEV_TENANT_ID
  - stack_id: acx-dev-fir
    role: face_pipeline_candidate
    base_url: https://fir.api.altcontext.com
    expected_profile: face_pipeline
    expected_pgvector_dim: 128
    api_key_env: ACX_BENCH_FIR_API_KEY
    tenant_id_env: ACX_BENCH_FIR_TENANT_ID
```

**Proof**

- `python -m pytest scripts/bench/tests/test_preflight.py scripts/bench/tests/test_corpus_superset.py scripts/bench/tests/test_resume.py -q` green (from package root parent).
- Red-proofs:
  1. Mock `/ready` with database check `detail: "reachable; pgvector_dimension=128"` on the insightface endpoint (expected 512) → preflight raises `profile_or_dim_drift`; strip the assertion → test fails.
  2. Mock `/health/detailed` without `model_cache.profile` → `profile_or_dim_drift`; mock 401 → `preflight_auth_failed`.
  3. Baseline partial set → test fails if superset check deleted.
  4. Resume re-POSTs completed ids if outcome store ignored.

**Dependencies**: FIR23-STACK not required for unit tests (mocked). Live `run` requires both stacks up.

---

### Slice 2: Export + score via FIR-5 pure metrics

**Goal**: After successful cluster phase, pull clusters/assignments from both stacks, map into `ImageDetection` / `ImageIdentities`, score detection P/R + identification P/R under both frames, emit tier-labeled head-to-head report under `benchmarks/results/crossbench-*/`.

**Files / functions**

| Module | Symbols | Responsibility |
| --- | --- | --- |
| `scripts/bench/export_map.py` | `export_leg(client, run_dir, stack_id) -> LegExport`, `to_face_metric_inputs(export, corpus) -> …`, `require_cluster_success(run_dir, stack_id)` | Use `clusters` / `cluster_members` / `media_identities`; gate on cluster outcome; preserve upstream pagination fields; no invented `total`; no embedding/landmark requirement |
| `scripts/bench/score_report.py` | `CrossbenchTier` enum (`CONFIRMATORY`/`DIRECTIONAL`/`DIAGNOSTIC`), `SAMPLING_FRAME_FACE_ID`, `SAMPLING_FRAME_E2E`, `score_head_to_head(run_dir) -> Path`, `write_provenance(...)`, `build_dual_frames(...)` | Call FIR-5 pure functions only; write JSON + HTML under `benchmarks/results/crossbench-<stamp>/` |
| `scripts/bench/cross_stack_bench.py` | subcommand `score` | Wire score path |
| `scripts/bench/tests/test_export_map_rg015.py` | fixture without `total` must not gain fabricated total | [rg-015] |
| `scripts/bench/tests/test_cluster_gate.py` | export aborts when clustering was not run | required |
| `scripts/bench/tests/test_e2e_frame.py` | detector-miss dual-frame pin | required |
| `scripts/bench/tests/test_e2e_mocked.py` | dual fake clients → report artifacts | one mocked E2E |

**Report must include**

- Both legs' **detection P/R** and **identification P/R** under **both frames** (`frame_fir5_native`, `frame_e2e`) side-by-side (null where labels absent — honest nulls, not `0.0` purity invention).
- Cascade-honest e2e treatment ([EVAL-16]): detector miss → identification miss on that face in `frame_e2e`.
- Shared denominators ([EVAL-19]).
- Provenance block ([PROV-01]): `stack_id`, `base_url`, `expected_profile`, `expected_pgvector_dim`, resolved profile from preflight, corpus sha256, CLI git SHA, harness identity.
- `license_notice` for the insightface leg.
- Crossbench tier label from `score_report.CrossbenchTier` (not attributed to FIR-5).

**Proof**

- Mocked E2E green; export mapper rg-015 test green; cluster gate test green; dual-frame test green.
- Red-proof: strip provenance writer → test asserting provenance keys fails; set `total=len(rows)` in mapper → rg-015 test fails; skip cluster phase → export gate test fails; remove FN injection → e2e frame test fails.

**Dependencies**: S1 complete. FIR-5 pure metrics on main (already).

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
3. **Preflight** — exact `python -m scripts.bench.cross_stack_bench preflight --config …` (from `apps/prototype-description-service`).
4. **Run** — `… run --config … --corpus … --out …` (ingest → analyze → cluster).
5. **Score** — `… score --run-dir …` (fails if cluster phase missing).
6. **Teardown** — **only** FIR23-STACK's documented stack-scoped DB reset for `acx-dev-fir` (and optional dev bench-tenant cleanup). Placeholder: `See FIR23-STACK runbook §reset` until that doc's command is stable — **do not invent** `DROP DATABASE` one-liners here that disagree with FIR23-STACK.
7. **Failure routing** — stack health / dim wrong in compose → FIR23-STACK; CLI logic / scoring → FIR-8; embedding-export needs → optional upstream task (not FIR-8).
8. **Verification checklist** — both preflights green; report path exists; both frames present; license_notice present; stacks reset.

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
- [ ] `StackPairConfig` validates against FIR23-STACK consumption table (dev: insightface/512; fir: face_pipeline/128; refuse unknown stacks)
- [ ] Preflight uses real `/ready` + authenticated `/health/detailed` contracts; stable codes `preflight_auth_failed` / `preflight_endpoint_missing` / `profile_or_dim_drift`
- [ ] Flow: ingest (CLI outbound fetch + pin) → analyze → cluster (`clustering_job(..., mode="sync")`); cluster outcome persisted
- [ ] Corpus accept set + baseline superset blocker + host pin set + public-unicast default (CLI fetches only)
- [ ] Per-item outcome store + resume
- [ ] Wall-clock + job-poll budgets enforced in CLI
- [ ] Named-stack allowlist guard before writes
- [ ] Unit tests: preflight (real shapes), superset, resume — each observed red first
- [ ] Handoff decision for S1 with verification commands

### Checklist for Slice 2: Export + score

- [ ] Export both legs via existing cluster/media APIs; gate on cluster success
- [ ] Mapper preserves upstream envelope fields ([rg-015]); no embedding/landmark requirement
- [ ] FIR-5 pure `detection_pr` / `identification_pr` only (no parallel scorer; score-face run records + purity sweeps OOS)
- [ ] Dual frames side-by-side (`SAMPLING_FRAME_FACE_ID` + `SAMPLING_FRAME_E2E`)
- [ ] Crossbench tier enum in `score_report.py` (not attributed to FIR-5)
- [ ] Report under `benchmarks/results/crossbench-*/` with provenance, cascade honesty, fixed denominators, license_notice, tier label
- [ ] Mocked E2E + rg-015 + cluster gate + dual-frame unit tests green
- [ ] Handoff decision for S2

### Checklist for Slice 3: Runbook + teardown

- [ ] `docs/runbooks/fir-8-cross-stack-bench.md` complete per outline
- [ ] License posture explicit; insightface non-exposure rule explicit
- [ ] Teardown cites FIR23-STACK reset only
- [ ] Failure routing table (stack gap → FIR23-STACK; CLI → FIR-8; embedding diagnostic → optional upstream)
- [ ] Commands match CLI help ([rg-006]); package root / import path documented
- [ ] Handoff decision for S3 / task close path prepared

## Review Readiness

- [ ] No recognition-service or deploy-YAML changes slipped into the branch.
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

- [ ] Operator can preflight + run + score a corpus against **both** stacks with **zero** recognition-service code changes in the FIR-8 diff.
- [ ] Preflight fails closed on dimension or profile drift / auth failure / missing endpoints with the three stable codes.
- [ ] Cluster phase runs per leg; export gated on success.
- [ ] Scoring uses public bbox/cluster metadata only → detection P/R + identification P/R; dual frames present.
- [ ] Superset / partial-intersection blocker enforced.
- [ ] Resume does not reprocess successful items.
- [ ] Head-to-head report exists under `benchmarks/results/crossbench-*/` with EVAL-16 / EVAL-19 / PROV-01 discipline and insightface license notice.
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

---

## Canon citations (index)

| ID | Use in this task |
| --- | --- |
| EMB-01 / IDX-02 | One vector space per (modality, model); isolated stacks |
| EVAL-16 | Cascade honesty in head-to-head (e2e frame) |
| EVAL-19 | Fixed denominators across legs |
| PROV-01 | Per-run provenance block |
| RLSE-05 / SERVE-03 | Insightface internal-bench only |
| rg-008 | Stack-pair config validated at load against consumption table |
| rg-015 | No invented envelope metadata |
| rg-006 | Documented commands run as written |
| DIAG-08 | Live/strategy bench ≠ Golden-150 substitute (corpus still explicit; do not re-host Golden as only path) |
| Heuristics canon v0.12.3 | Governing revision |
| Distilled: `janus-benchmark-c.md`, `handbook-face-recognition.md` | Cascade / face-eval discipline |
