# FIR-8. Cross-stack face-pipeline bench orchestration

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok (docs-only plan authoring)
> - **Plan version**: v6.2 — supersedes in-service bench supervisor (v5); re-scopes to cross-stack orchestration aligned with FIR23-STACK + QA v2; **changelog (v6→v6.1)**: real preflight contracts, explicit cluster phase, feasible public-export scoring scope, dual scoring frames, crossbench tier enum, ingest→analyze→cluster→export flow, pinned FIR23-STACK consumption table, single package root; **changelog (v6.1→v6.2)**: ground-truth wiring + label mapping, S1 executable granularity (run-dir/resume/credentials/status/PROV-01), concrete CrossbenchTier assignment rules, EVAL-19 accepted-set operationalization, proof-suite + dual-frame FIR-5 signature pins
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
- **Fixed denominators** ([EVAL-19]): the scoring denominator is the **accepted set** — manifest items successfully ingested+analyzed on **both** legs — computed once, written to `score/accepted_set.json`, asserted identical across legs before any metric; attrition of one-sided failures is reported, not silently dropped (see [EVAL-19 operationalized](#eval-19-operationalized-accepted-set)).
- **Per-run provenance** ([PROV-01]): every report stamps stack identity (base URL / compose project name), model ids, `PGVECTOR_DIM`, corpus hash, CLI + harness code SHAs; per-leg `preflight.json` is the primary provenance artifact written in S1 and consumed by the report.
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
| **Corpus / manifest** | Golden-schema corpus loaded via `scripts.eval_harness.manifest.load_manifest` (CLI `--manifest`). Media bytes from manifest-relative local paths (under `--images-dir` / corpus root) or pinned remote URLs. |
| **Leg** | Full **ingest → analyze → cluster → export** path against **one** stack. A head-to-head run has two legs: `insightface@512` and `face_pipeline@128`. |
| **Accepted set** | Manifest items that **succeeded ingest+analyze on both legs**. Fixed scoring denominator ([EVAL-19]); written to `score/accepted_set.json`. Distinct from pre-ingest validation. |
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
6. Zero recognition-service source edits land in this task's commits.

## Context Loading (read before implementation)

| Order | Path | Why |
| --- | --- | --- |
| 1 | This plan (v6.2) end-to-end | Locked scope, dependency boundary, carried invariants, slices |
| 2 | `apps/prototype-description-service/scripts/eval_harness/remote_client.py` | Existing HTTP client (`analyze`, `wait_job`, `media_identities`, `clustering_job`, `clusters`, …) — **no health methods** |
| 3 | `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` | Pure `ImageDetection` / `ImageIdentities` + `detection_pr` / `identification_pr` — scoring legs (unmodified consumers) |
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

Import path used by tests and CLI:

```bash
# from apps/prototype-description-service (or with that dir on PYTHONPATH)
python -m scripts.bench.cross_stack_bench --help
python -m pytest scripts/bench/tests/ -q
```

```text
apps/prototype-description-service/scripts/bench/
  __init__.py
  cross_stack_bench.py          # CLI entry (preflight/run/status/score)
  stack_pair.py                 # load + validate stack-pair config against FIR23-STACK table
  preflight.py                  # own authenticated GETs; write preflight.json (PROV-01)
  corpus.py                     # load_manifest wrap, media resolve order, pin, items.jsonl
  driver.py                     # ingest → analyze → cluster → export both stacks; resume
  export_map.py                 # persist exports; GT+label map → ImageDetection/ImageIdentities
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
2. `python -m scripts.bench.cross_stack_bench preflight --config stack-pair.yaml` → both sides green or abort (writes per-leg `preflight.json` under `--out` when run-dir known, or dry-check without run-dir).
3. `… run --config … --manifest <golden-schema.json> --images-dir <corpus-root> --out benchmarks/results/crossbench-<stamp>/` → ingest+analyze+cluster+export both legs; resume via append-only `items.jsonl`.
4. `… status --run-dir …` → per-leg progress + phase (optional operator check).
5. `… score --run-dir …` → reads run-dir only (no credentials); dual-frame FIR-5 pure metrics + head-to-head HTML/JSON (aborts if cluster phase missing/failed).
6. Teardown: FIR23-STACK stack-scoped DB reset for the FIR stack (and optional dev-bench tenant wipe per runbook) — **not** a new recognition purge phase.

---

## Superseded: v5 in-service vehicle

v5 specified an **in-service** async single-live-run bench supervisor inside the recognition worker: state machine over `recognition_bench_runs`, `uq_bench_single_live`, purge-before-terminal, deployment marker rail, boot-coupled license gate, non-blocking tick contract, and `/admin` bench routes. That vehicle is **superseded** by **per-model isolated stacks** (FIR23-STACK): exclusivity, no mixed-space reads, and teardown via stack-scoped DB reset are structural properties of the deploy topology, not application supervisor features. Re-implementing them inside the worker would duplicate FIR23-STACK ownership and re-open dual-space foot-guns. **Do not delete git history** — v5 plan text is recoverable at commit **`bc97ff4b`**. Decision **#2951** records the supersession. The rest of this document is the v6 / v6.2 scope (v6.1 structure + v6.2 grounding).

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

- Map exports + GT → `face_metrics.ImageDetection` (count-based detection P/R via `detection_pr`).
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
| **Schema** | Golden manifest v2 (`manifest_version == 2`) — same schema as FIR-5 eval |
| **Loader** | `scripts.eval_harness.manifest.load_manifest(path: str, images_dir: str \| None = None) -> GoldenManifest` |
| **Types** | `GoldenManifest` (`roster`, `entries`); `GoldenEntry` (`path`, `sha256`, `media_id`, `face_count`, `present_identities`, `face_boxes`, `policy`, …); `FaceBox` (`x`, `y`, `w`, `h`, `name: str \| None`, `source`) |
| **Errors** | `ManifestError` on structural/hash/label failures (fail-closed, [rg-008]) |
| **File pattern** | CLI `--manifest` accepts any path loadable by `load_manifest`. **Convention** for the Golden-150 face bench corpus: `benchmarks/manifests/golden150-*.json` (e.g. `golden150-draft-YYYYMMDD.json`). Smoke / unit fixtures may use `apps/prototype-description-service/scene/tests/seed/golden.json`. |
| **In-tree status (plan-author check)** | `benchmarks/manifests/golden150-draft-20260723.json` is **not** present in this checkout; operators (or VLM-6 curation) supply the curated Golden-150 path. Do not invent a vendored 150-entry file in FIR-8. |
| **Content hash pin** | At `run` start, write `manifest.sha` = sha256 of the manifest file bytes. Optional stack-pair / run config key `manifest_sha256` fails closed if it mismatches the loaded file. Score path re-reads the hash for provenance. |
| **Image bytes root** | `--images-dir` (or config `images_dir`) is the local corpus root; when set, `load_manifest(..., images_dir=...)` verifies per-entry `sha256` against files under that root (same as harness). |

CLI: `run --manifest <path> --images-dir <root> …` (both required for production head-to-head; tests may inject a synthetic `GoldenManifest` without disk images).

### (b) Constructing metric inputs

Frame construction happens **entirely in `scripts/bench`** (`export_map.py` / `score_report.py`). FIR-5 `detection_pr` / `identification_pr` are pure consumers of the rows the adapter builds — **unmodified**.

| Side | Source | Fields used for FIR-5 rows |
| --- | --- | --- |
| **GT (labeled)** | Manifest entry | `ImageDetection.labeled_faces` ← `entry.face_count` (or `len(entry.face_boxes)` when boxes are complete and preferred); `ImageIdentities.labeled` ← `entry.present_identities` (roster names); `recognition_enabled` ← `entry.policy.recognition_enabled`; `stranger_faces` ← max(0, `face_count - len(present_identities)`) or count of `face_boxes` with `name is None` when boxes present |
| **Predicted** | Per-leg public exports under `legs/<stack_id>/exports/` | `ImageDetection.pred_faces` ← count of exported face rows for that media; `ImageIdentities.predicted` ← **mapped** identity names (never raw unmapped cluster ids as if they were GT names) |
| **Image key** | Join key | Stable string: manifest `path` or `str(entry.media_id)` — same `image` field on both `ImageDetection` and `ImageIdentities` for a media unit |

Detection P/R does not require identity name mapping (counts only). Identification P/R **requires** [label-space mapping](#c-label-space-mapping) before filling `predicted`.

### (c) Label-space mapping

Predicted `cluster_label` values are **cluster-scoped** (stack-local cluster ids / operator labels), not automatically GT roster names. Never pass raw `cluster_label` into `ImageIdentities.predicted` without mapping.

**Normalization** (shared by both rules): Unicode NFC, strip, collapse internal whitespace, casefold.

| Rule | When | How | Report frame |
| --- | --- | --- | --- |
| **Primary — string match (pinned primary)** | Cluster has an operator-assigned label (`is_auto_label == false` **or** non-empty human `cluster_label` that is not a pure auto id) | Map predicted label → GT name if normalized strings equal a roster / `present_identities` name; else unmapped (omit from `predicted` for primary frame; count under unmapped-cluster DIAGNOSTIC stats) | `label_map_primary` — **default** for CONFIRMATORY identification cells |
| **Optimistic — Hungarian (disclosed)** | Unlabeled / auto-labeled clusters (`is_auto_label == true` or empty label) **or** residual after primary | Optimal one-to-one assignment (Hungarian) maximizing **overlap counts** between cluster member boxes and GT `face_boxes` (IoU ≥ plan constant `BOX_IOU_MATCH=0.5`, or centre-in-box fallback when GT boxes lack size parity). Assigned GT names fill `predicted` for this frame only. | `label_map_optimistic` — always **DIRECTIONAL**; never CONFIRMATORY |

**Disclosure (mandatory in report)**: primary and optimistic frames print side-by-side for identification; optimistic cells carry tier `DIRECTIONAL` and a one-line note that assignment is overlap-optimal, not operator-confirmed. Unmapped residual clusters after both rules are DIAGNOSTIC counts only.

### (d) Media identity join

Manifest `media_id` (synthetic golden id) ≠ stack `media_id` (per-tenant DB id after analyze). Join is **only** via the per-item outcome record:

```text
legs/<stack_id>/items.jsonl  # one JSON object per line, append-only
{
  "manifest_media_id": 12,          # GoldenEntry.media_id
  "manifest_path": "…",             # GoldenEntry.path
  "content_sha256": "…",            # GoldenEntry.sha256 when verified
  "stack_media_id": "…",            # id returned by analyze / media export on this stack
  "phase": "ingest|analyze|…",
  "outcome": "ok|failed",
  "error_code": null,
  "attempt": 1
}
```

Score path: for each accepted-set item, resolve `stack_media_id` per leg from that leg's `items.jsonl`, then select export rows with matching stack media id. Missing join → item excluded from accepted set + counted in attrition (phase=`join`).

---

## End-to-end scoring frames

FIR-5 pure functions score **only the rows they are given** — they do not themselves inject detector-miss cascade or label mapping. The adapter in `scripts/bench` owns cascade honesty and label-space mapping; **FIR-5 is unmodified**.

### Dual-frame adapter contract (FIR-5 signatures pinned)

Verified in `apps/prototype-description-service/scripts/eval_harness/face_metrics.py`:

```python
@dataclass(frozen=True)
class ImageDetection:
    image: str
    pred_faces: int
    labeled_faces: int

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
- **Do not modify** `face_metrics.py` in this task.

**Adapter construction (normative)**

1. Join accepted-set media via [media identity join](#d-media-identity-join); load GT from the pinned manifest; load predicted rows from `legs/<stack_id>/exports/`.
2. Apply [label-space mapping](#c-label-space-mapping) → primary and (separately) optimistic predicted name lists.
3. **FIR-5-native sampling frame** (`sampling_frame=SAMPLING_FRAME_FACE_ID`): call `detection_pr` / `identification_pr` on rows derived only from exported detections (excludes pure detector misses from identification accounting by construction of the input rows). Report under key `frame_fir5_native`.
4. **End-to-end sampling frame** (`sampling_frame=SAMPLING_FRAME_E2E`): **before** calling the pure functions, inject labeled-but-undetected faces as FN rows (`ImageDetection` undershoot and/or `ImageIdentities` with empty `predicted` + labeled name present). Report under key `frame_e2e`. Detector miss → identification miss is accounted here ([EVAL-16]).
5. Head-to-head report prints sampling frames **and** label-mapping frames as a grid per leg; never silently replace one with another.

**Unit test (required)**: synthetic corpus where one labeled face is absent from export → `frame_e2e` identification FN increments and detection FN increments; `frame_fir5_native` identification denominator does not charge that miss the same way (pins detector-miss→ID-miss accounting).

Constants live in `score_report.py` (or `export_map.py`): `SAMPLING_FRAME_FACE_ID`, `SAMPLING_FRAME_E2E`, `LABEL_MAP_PRIMARY`, `LABEL_MAP_OPTIMISTIC` — plan-level names; not FIR-5 library enums.

---

## Tier vocabulary

The three-tier report label set **`CONFIRMATORY` / `DIRECTIONAL` / `DIAGNOSTIC`** is a **new crossbench report enum** defined in `score_report.py` as `CrossbenchTier`, sourced from QA-digest / canon convention for head-to-head bench claims. It is **not** a FIR-5 enum and must not be attributed to FIR-5 modules.

Separately: FIR-5 / eval harness surfaces carry **per-metric DIRECTIONAL disclosure qualifiers** in the QA/canon sense (e.g. underpowered slices report directional-only and cannot enter a gate decision — see commercial-face-identity scope language) plus harness **`provider_disclosure`** stamps on describe responses. Those are **not** the three-tier crossbench enum. Crossbench reports may *reference* FIR-5 directional disclosure text when a leg is underpowered, but the tier stamp itself is owned by `score_report.py`.

### CrossbenchTier semantics (normative)

| Tier | Meaning |
| --- | --- |
| **CONFIRMATORY** | Full-corpus fixed-denominator metric over the pinned **accepted set**, both legs' clustering complete (`cluster_job.json` success), **primary** label-mapping only, accepted-set size ≥ configured floor (`accepted_set_floor`, default = min(manifest entry count, operator pin; tests use explicit small floor)). Eligible for gate-style claims. |
| **DIRECTIONAL** | Any cell whose denominator lost items below the pre-stated floor (ingest/analyze failures shrank the accepted set), **or** any cell using the **optimistic** label-mapping frame, **or** underpowered slice cells the report still shows for trend. Not gate-eligible. |
| **DIAGNOSTIC** | Context cells: per-stack raw face/cluster counts, unmapped-cluster stats, attrition-by-phase tables, join failures, license banner echo. Never used as a quality gate. |

### Cell → tier assignment (normative)

| Report cell | Tier rule |
| --- | --- |
| Detection P/R (`frame_e2e` or `frame_fir5_native`) on accepted set, both clusters OK, size ≥ floor | **CONFIRMATORY** |
| Identification P/R with `label_map_primary`, same conditions | **CONFIRMATORY** |
| Identification P/R with `label_map_optimistic` | **DIRECTIONAL** (always) |
| Any P/R cell when `\|accepted_set\| < accepted_set_floor` | **DIRECTIONAL** |
| Any P/R cell when either leg cluster phase missing/failed | **not scored** (score aborts; no silent tier downgrade that invents a metric) |
| Per-stack raw detection counts, export row counts | **DIAGNOSTIC** |
| Unmapped-cluster counts / residual after mapping | **DIAGNOSTIC** |
| Attrition table (per-leg failure counts by phase) | **DIAGNOSTIC** |
| Provenance / license banner fields | **DIAGNOSTIC** (metadata, not a quality claim) |

---

## EVAL-19 operationalized (accepted set)

[EVAL-19] is not only “share a denominator” — the denominator is a concrete artifact:

1. **Definition**: `accepted_set` = set of manifest items (`manifest_media_id` / path / sha256) for which **both** legs recorded terminal-success for **ingest and analyze** phases in `legs/<stack_id>/items.jsonl`.
2. **Compute once** at the start of `score` (after both legs finished run): intersection of per-leg success sets.
3. **Persist**: write `score/accepted_set.json` (`manifest_media_ids`, `paths`, `content_sha256s`, `size`, `floor`, `computed_at`).
4. **Assert before metrics**: both legs' success sets, when intersected, match the file; re-derive and fail closed if a leg's items.jsonl was mutated after the file was written.
5. **Attrition (reported, not silent)**: items in the manifest but missing from the accepted set appear in `score/attrition.json` (and the report DIAGNOSTIC table): per-leg failure counts by phase (`ingest`, `analyze`, `cluster`, `export`, `join`) plus one-sided success counts (succeeded on A only / B only).
6. **Detection failure after accept**: a media that analyzed on both legs stays in the accepted set even if detection count is zero — that is a scored miss, not attrition. Attrition is **pre-accept** failure only.
7. **Floor**: if `size < accepted_set_floor`, all P/R cells downgrade to **DIRECTIONAL** (see tier table); report still emits metrics with the disclosure.

---

## Carried-forward invariants (orchestration layer)

Adapt v5 review-hardened invariants; **do not re-litigate**. Enforcement lives in the **CLI**, not the recognition service.

### CF-1. Baseline / corpus ingest contract

- Uploaded or declared baseline / label artifact `media_id` (or content-sha) set **must be a SUPERSET** of the run's accepted set. **Partial intersection = blocker** (exit non-zero; do not score a silent subset).
- **Per-item outcomes** append to `legs/<stack_id>/items.jsonl` (see [Ground truth & label mapping](#d-media-identity-join)): `manifest_media_id`, `stack_media_id`, phase, outcome (`ok`/`failed`), optional `error_code`, `content_sha256` when ok — resume never loses hard-fail tallies.
- **There is no stack-side enroll API.** Media bytes resolution order (normative):
  1. **Local path first**: resolve `GoldenEntry.path` under `--images-dir` / corpus root (NFC/NFD tolerant, same idea as `manifest._resolve_image`); read bytes; verify sha256 against entry when present.
  2. **Remote URL second**: if local file is missing and the entry (or corpus overlay) provides an HTTPS URL (`provenance.url` or operator URL map), fetch via CLI outbound HTTP.
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
- [PROV-01] per-leg `preflight.json` is the provenance artifact (profile, dim, stack identity, timestamps, response excerpts); report aggregates both legs + `manifest.sha` + CLI/harness SHAs.
- Tier labels: `CrossbenchTier` assignment rules — see [Tier vocabulary](#tier-vocabulary). Do not invent additional tier names beyond that enum.
- Label mapping: primary string-match is default; optimistic Hungarian is disclosed DIRECTIONAL only — see [Ground truth & label mapping](#ground-truth--label-mapping).

### CF-6. Cluster-before-export

- Per leg, after analyze jobs complete: `client.clustering_job(tenant_id, mode="sync")`.
- Persist outcome under run dir (`legs/<stack_id>/cluster_job.json` with status payload).
- `export_map.export_leg` / score path **aborts** if cluster outcome is missing or non-success (mocked test required).

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
| tooling (new) | `apps/prototype-description-service/scripts/bench/export_map.py` | Persist exports in `run`; map GT+exports → `ImageDetection` / `ImageIdentities`; label mapping; gate on cluster success |
| tooling (new) | `apps/prototype-description-service/scripts/bench/score_report.py` | Dual sampling + label-map frames; `CrossbenchTier` rules; `accepted_set.json` / attrition; write report |
| tooling (new) | `apps/prototype-description-service/scripts/bench/production_shaped_guard.py` | Named-stack allowlist + optional count attestation |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_preflight.py` | Fail-closed dim/profile/auth/missing-field with real payload shapes |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_corpus_superset.py` | Superset / partial-intersection blocker |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_resume.py` | Resume idempotency |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_stack_pair_consumption.py` | Base URL / stack_id not in pinned table → load fails |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_media_pin_public_unicast.py` | RFC1918 remote without LAN override → ingest refuses (mocked resolver) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_cluster_gate.py` | Export aborts when clustering was not run / failed |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_e2e_frame.py` | Detector-miss → ID-miss accounting (dual frames) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_e2e_mocked.py` | One mocked end-to-end (both legs → report dir) |
| tests (new) | `apps/prototype-description-service/scripts/bench/tests/test_export_map_rg015.py` | Export normalization invents no envelope metadata (rg-015) |
| docs (new) | `apps/prototype-description-service/scripts/bench/README.md` | Package README (S3) |
| docs (new) | `docs/runbooks/fir-8-cross-stack-bench.md` | Operator runbook + teardown + license |
| docs (edit) | this plan | v6.2 plan grounding (this commit) |

**Explicitly untouched:** `apps/prototype-description-service/recognition/**`, `db/migrations/**`, WP plugin, FIR23-STACK compose/deploy files.

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/remote_client.py` | Prefer reuse / thin wrap for analyze/cluster/export HTTP; **no health methods** |
| `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` | Face P/R pure functions (`ImageDetection`, `ImageIdentities`, `detection_pr`, `identification_pr`) — **unmodified** consumers |
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
python -m pytest scripts/bench/tests/ -q
```

Must cover:

1. **Preflight fail-closed (real shapes)** — mock `/health/detailed` body with `model_cache.profile` and `/ready` body with `checks[{name:database,status,detail}]`; insightface leg with `detail` lacking `pgvector_dimension=` or dim≠512 → `profile_or_dim_drift`; missing auth → `preflight_auth_failed`; 404 → `preflight_endpoint_missing`. Same for fir leg (expect 128 / face_pipeline).
2. **Superset blocker** — accepted `{1,2,3}`, baseline `{1,2}` → blocker; accepted `{1,2}`, baseline `{1,2,3}` → pass.
3. **Resume idempotency** — after partial `items.jsonl`, re-run does not re-POST terminal-success media; failed items re-attempt up to bounded retry.
4. **Consumption-table cross-check** (`test_stack_pair_consumption.py`) — stack_pair config with a `base_url` / `stack_id` not in the pinned table → `load_stack_pair` fails.
5. **Pin / public-unicast** (`test_media_pin_public_unicast.py`) — remote media URL resolving to RFC1918 without `allow_private_source` → ingest refuses (deterministic mocked resolver).
6. **Cluster gate** — export/score aborts when `cluster_job.json` missing or non-success.
7. **Dual-frame cascade** — detector-miss synthetic pins e2e FN accounting vs FIR-5-native frame; frames call only `detection_pr` / `identification_pr` with pinned input types.
8. **One mocked E2E** — fake dual clients return fixed cluster payloads → report dir contains provenance (`preflight.json`), `accepted_set.json`, both legs + both sampling frames + label-map frames + tier label + license banner; no network; `score` uses no credentials.

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
| `scripts/bench/stack_pair.py` | `load_stack_pair(path) -> StackPairConfig`, `StackEndpoint` dataclass, `FIR23_STACK_ALLOWLIST` | Parse config; require keys: `stack_id`, `base_url`, `api_key` env ref, `tenant_id` env ref, `expected_profile`, `expected_pgvector_dim`; validate `stack_id` ∈ consumption table and base_url host against allowlist identity; reject unknown keys / unknown stacks (fail-closed, [rg-008]) |
| `scripts/bench/preflight.py` | `preflight_stack(endpoint) -> PreflightResult`, `preflight_pair(pair) -> None`, `PreflightError`, `write_preflight_json(path, result)` | Own GETs: `/ready` + authenticated `/health/detailed`; parse profile + dim per [Real preflight contract](#real-preflight-contract); raise with stable codes; persist **PROV-01** artifact |
| `scripts/bench/corpus.py` | `load_bench_manifest(path, images_dir) -> GoldenManifest` (wraps `load_manifest`), `resolve_media_bytes(entry, images_dir, …)`, `assert_baseline_superset(accepted, baseline)`, `pin_media_hosts(...)`, `ItemOutcomeStore` | GT load; local-then-remote media resolution; pin + public-unicast on remote; append-only JSONL outcomes |
| `scripts/bench/driver.py` | `run_leg(...)`, `run_pair(...)`, `run_cluster_phase(...)`, `export_and_persist_leg(...)`, `init_run_dir(...)` | Per stack: resolve bytes → `analyze` + `wait_job` → `clustering_job(..., mode="sync")` → persist exports under `exports/`; resume; budgets |
| `scripts/bench/production_shaped_guard.py` | `assert_named_bench_stack(endpoint, allowlist)` | Allow only configured stack_ids before writes |
| `scripts/bench/cross_stack_bench.py` | `main()`, subcommands `preflight` / `run` / `status` / (`score` wired in S2) | argparse CLI (`python -m scripts.bench.cross_stack_bench`) |
| `scripts/bench/tests/test_preflight.py` | real payload shape cases | red first |
| `scripts/bench/tests/test_corpus_superset.py` | partial intersection | red first |
| `scripts/bench/tests/test_resume.py` | partial JSONL resume | red first |
| `scripts/bench/tests/test_stack_pair_consumption.py` | unknown base_url / stack_id | red first |
| `scripts/bench/tests/test_media_pin_public_unicast.py` | RFC1918 without override | red first; mocked resolver |
| `scripts/bench/tests/test_cluster_gate.py` | missing cluster outcome | may land with S1 driver stub or S2 export; required before score path merges |

#### S1 executable contracts (normative)

**(a) Ingest wiring — media bytes**

Resolution order (per manifest entry):

1. Local file under `--images-dir` / `images_dir` + `entry.path` (sha256 verify when possible).
2. Else remote HTTPS URL from entry provenance / operator URL map — **CF-1 pin + public-unicast apply**.
3. Else `outcome=failed`, `error_code=media_unresolvable`.

Bytes are then POSTed via `RemoteSceneClient.analyze` multipart (no stack enroll API).

**(b) Run-dir layout**

```text
benchmarks/results/crossbench-<stamp>/          # --out
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
- Cluster phase re-runs only if `cluster_job.json` missing or non-success and analyze successes exist.
- Export re-runs only if cluster success and export files incomplete.

**(d) Score / export credential flow**

Locked by [CF-7](#cf-7-score-credential-flow-pinned): `run` persists exports; `score` is offline on the run-dir.

**(e) `status` subcommand (kept in S1)**

- Reads `run.json` + each leg's `items.jsonl` (+ presence of `cluster_job.json` / `exports/`).
- Prints per-leg: counts by phase outcome, current phase estimate (`ingest|analyze|cluster|export|done|failed`), wall-clock elapsed if stamped.
- Exit 0 when parseable; non-zero if run-dir missing/corrupt. No network.

**(f) PROV-01 via `preflight.json`**

- Written per leg in S1 at preflight (and refreshed if preflight re-run into the same run-dir).
- Required fields: `stack_id`, `base_url`, `expected_profile`, `expected_pgvector_dim`, `resolved_profile`, `resolved_pgvector_dim`, `checked_at`, `ready_excerpt`, `health_detailed_excerpt` (redact secrets).
- Report (S2) **consumes** these files; does not re-call health endpoints.

**Stack-pair config shape (normative)**

```yaml
# example only — not a committed secret file
wall_clock_timeout_sec: 3600
job_poll_timeout_sec: 600
item_max_attempts: 2
accepted_set_floor: 1          # production pin: operator sets floor (e.g. 100 for Golden-150 claims)
allow_private_source: false
# optional: fail closed if --manifest bytes disagree
# manifest_sha256: "<64 hex>"
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

- `python -m pytest scripts/bench/tests/test_preflight.py scripts/bench/tests/test_corpus_superset.py scripts/bench/tests/test_resume.py scripts/bench/tests/test_stack_pair_consumption.py scripts/bench/tests/test_media_pin_public_unicast.py -q` green (from package root parent).
- Red-proofs:
  1. Mock `/ready` with database check `detail: "reachable; pgvector_dimension=128"` on the insightface endpoint (expected 512) → preflight raises `profile_or_dim_drift`; strip the assertion → test fails.
  2. Mock `/health/detailed` without `model_cache.profile` → `profile_or_dim_drift`; mock 401 → `preflight_auth_failed`.
  3. Baseline partial set → test fails if superset check deleted.
  4. Resume re-POSTs terminal-success ids if outcome store ignored.
  5. Stack-pair with foreign `stack_id` or base_url outside allowlist identity → load fails; delete the check → test fails.
  6. Mock DNS/resolver returning `10.0.0.5` for a remote media URL with `allow_private_source=false` → ingest refuses; strip enforcement → test fails.

**Dependencies**: FIR23-STACK not required for unit tests (mocked). Live `run` requires both stacks up.

---

### Slice 2: Export + score via FIR-5 pure metrics

**Goal**: Consume exports already persisted by `run` (offline), map GT + exports into `ImageDetection` / `ImageIdentities` with label-space mapping, score detection P/R + identification P/R under sampling frames × label-map frames, emit tier-labeled head-to-head report under `benchmarks/results/crossbench-*/` with accepted-set + attrition artifacts.

**Files / functions**

| Module | Symbols | Responsibility |
| --- | --- | --- |
| `scripts/bench/export_map.py` | `export_leg(client, run_dir, stack_id) -> LegExport` (called from **run**), `load_leg_exports(run_dir, stack_id)`, `map_cluster_labels_primary(...)`, `map_cluster_labels_optimistic(...)`, `to_face_metric_inputs(export, manifest, join, label_map) -> tuple[list[ImageDetection], list[ImageIdentities]]`, `require_cluster_success(run_dir, stack_id)` | Gate on cluster outcome; preserve upstream pagination fields; no invented `total`; no embedding/landmark requirement; **all** `ImageDetection`/`ImageIdentities` construction here or in `score_report` — never inside FIR-5 |
| `scripts/bench/score_report.py` | `CrossbenchTier` enum, `SAMPLING_FRAME_*`, `LABEL_MAP_*`, `compute_accepted_set(run_dir) -> AcceptedSet`, `write_accepted_set(...)`, `write_attrition(...)`, `score_head_to_head(run_dir) -> Path`, `build_dual_frames(...)`, `assign_tier(cell, ctx) -> CrossbenchTier` | Call **only** `detection_pr` / `identification_pr` with pinned signatures; tier rules; offline on run-dir |
| `scripts/bench/cross_stack_bench.py` | subcommand `score` | Wire offline score path (**no credentials**) |
| `scripts/bench/tests/test_export_map_rg015.py` | fixture without `total` must not gain fabricated total | [rg-015] |
| `scripts/bench/tests/test_cluster_gate.py` | export aborts when clustering was not run | required |
| `scripts/bench/tests/test_e2e_frame.py` | detector-miss dual-frame pin | required |
| `scripts/bench/tests/test_e2e_mocked.py` | dual fake clients → report artifacts | one mocked E2E |

**Report must include**

- Both legs' **detection P/R** and **identification P/R** under **both sampling frames** (`frame_fir5_native`, `frame_e2e`) and **both label-map frames** (`label_map_primary`, `label_map_optimistic`) (null where labels absent — honest nulls, not `0.0` purity invention).
- Cascade-honest e2e treatment ([EVAL-16]): detector miss → identification miss on that face in `frame_e2e`.
- Fixed denominators via `score/accepted_set.json` + attrition table ([EVAL-19 operationalized](#eval-19-operationalized-accepted-set)).
- Provenance block ([PROV-01]) from per-leg `preflight.json` + `manifest.sha` + CLI/harness SHAs.
- `license_notice` / `license_banner` for the insightface leg on intermediate JSON and HTML.
- Per-cell `CrossbenchTier` from the assignment table (not attributed to FIR-5).

**Proof**

- Mocked E2E green; export mapper rg-015 test green; cluster gate test green; dual-frame test green.
- Red-proof: strip provenance consumer → test asserting preflight keys fails; set `total=len(rows)` in mapper → rg-015 test fails; skip cluster phase → export gate test fails; remove FN injection → e2e frame test fails; pass raw unmapped `cluster_label` as `predicted` without mapping → identification unit test fails; mutate accepted set differently per leg → score assert fails.

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
4. **Run** — `… run --config … --manifest … --images-dir … --out …` (ingest → analyze → cluster → export persist).
5. **Status** — `… status --run-dir …` (optional; per-leg progress + phase).
6. **Score** — `… score --run-dir …` (offline; fails if cluster phase missing; writes `score/accepted_set.json` + report).
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
- [ ] `StackPairConfig` validates against FIR23-STACK consumption table (dev: insightface/512; fir: face_pipeline/128; refuse unknown stacks / foreign base URLs)
- [ ] Preflight uses real `/ready` + authenticated `/health/detailed` contracts; stable codes; writes per-leg `preflight.json` (PROV-01)
- [ ] Manifest via `load_manifest` (`--manifest` + `--images-dir`); `manifest.sha` written
- [ ] Flow: media resolve (local then remote+CF-1 pin) → analyze → cluster → **export persist**; run-dir tree as specified
- [ ] Baseline superset blocker + public-unicast default on remote fetches
- [ ] Append-only `items.jsonl` resume (skip terminal-success; bounded retry on failures)
- [ ] `status` reads run.json + items.jsonl (no network)
- [ ] Wall-clock + job-poll budgets enforced in CLI
- [ ] Named-stack allowlist guard before writes
- [ ] Unit tests: preflight, superset, resume, consumption-table, public-unicast — each observed red first
- [ ] Handoff decision for S1 with verification commands

### Checklist for Slice 2: Export + score

- [ ] Score offline on run-dir only (exports already persisted; no credentials)
- [ ] GT + export join via items.jsonl; primary + optimistic label-space mapping
- [ ] Mapper preserves upstream envelope fields ([rg-015]); no embedding/landmark requirement
- [ ] FIR-5 pure `detection_pr` / `identification_pr` only on constructed `ImageDetection` / `ImageIdentities` (FIR-5 unmodified)
- [ ] Dual sampling frames + dual label-map frames side-by-side
- [ ] `score/accepted_set.json` + attrition table ([EVAL-19]); `CrossbenchTier` cell rules
- [ ] Report under `benchmarks/results/crossbench-*/` with preflight provenance, cascade honesty, license banner, tier labels
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
- [ ] Scoring uses public bbox/cluster metadata + manifest GT + label mapping → detection P/R + identification P/R; dual sampling and label-map frames present.
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

---

## Canon citations (index)

| ID | Use in this task |
| --- | --- |
| EMB-01 / IDX-02 | One vector space per (modality, model); isolated stacks |
| EVAL-16 | Cascade honesty in head-to-head (e2e frame) |
| EVAL-19 | Fixed denominators = accepted set (`score/accepted_set.json`) + attrition |
| PROV-01 | Per-leg `preflight.json` provenance artifact |
| RLSE-05 / SERVE-03 | Insightface internal-bench only |
| rg-008 | Stack-pair config validated at load against consumption table |
| rg-015 | No invented envelope metadata |
| rg-006 | Documented commands run as written |
| DIAG-08 | Live/strategy bench ≠ Golden-150 substitute (corpus still explicit; do not re-host Golden as only path) |
| Heuristics canon v0.12.3 | Governing revision |
| Distilled: `janus-benchmark-c.md`, `handbook-face-recognition.md` | Cascade / face-eval discipline |
