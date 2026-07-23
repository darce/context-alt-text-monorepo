# FIR-8. Operator Bench: Live-Tenant InsightFace vs Production face_pipeline

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok (docs-only plan authoring)
> - **Plan version**: v2 (resolves planning-review FAIL on v1; adversarial panel FIR8PR-* / FIR8PA-*)
> - **Projects**: `apps/prototype-description-service` (primary); WP plugin **out of MVP control path**
> - **Task ID**: `FIR-8` (operator-assigned bench surface; escalation ladder renumbered to **FIR-9** — see [ID collision](#id-collision-fir8pa-04))
> - **Target Branch**: `feature/fir-8`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-4 (shared `build_embedding_runtime` + `RECOGNITION_FACE_PIPELINE_PROFILE` seam, merged); FIR23-01 (`embedding_model` enforced on read paths + fail-closed readiness)
> - **House style note**: Structure follows FIR-4 (invariants, per-slice gates, consolidated checklist) plus junior-executable contracts
> - **Review Coverage Target**: 2
> - **Isolation track (LOCKED)**: **dedicated bench deployment only** — no process-wide dual-dim toggle, no Option B

## Objective

Ship an **operator-facing, recognition-side `/admin` surface** that lets a tailnet-bound operator compare recognition quality between InsightFace `buffalo_l` (bench deployment only) and the clean candidate `face_pipeline` **already measured on production**, using **live tenant media** samples — by reusing the existing profile selection seam, **not** inventing a second pipeline.

Deliverables: boot-coupled license/deployment gate, dedicated-bench isolation (own process + own DB/schema + `PGVECTOR_DIM=512` + `profile=insightface`), scan_worker-backed bounded run vehicle, media intake + retention contract, label-free metrics with honest nulls, and an `/admin` HTML console panel labeled for internal non-commercial benchmarking only.

## Intake

- **Operator ask**: admin control for InsightFace path as **internal benchmarking only**, so the operator can see the quality gap on real tenant media before model-strategy decisions.
- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) (license isolation + single-model prod DB intake) · E22 epic hard constraints · FIR-4 runtime factory
- **ID collision (FIR8PA-04)**: scope table + epic currently reserve “FIR-8” for the contingent **escalation ladder**. This plan **keeps `FIR-8` for the bench surface** (operator-assigned) and **renumbers the escalation ladder to `FIR-9`**. S1 checklist **requires** editing both the scope task table and the epic P4/rollback/Not-Doing references in the **same baseline** as gate code — not a follow-on. See [ID collision](#id-collision-fir8pa-04).
- **Not-Doing here**: listed under [Non-goals](#non-goals).

## Context Loading (read before implementation)

| Order | Path | Why |
| --- | --- | --- |
| 1 | This plan (v2) end-to-end | Locked isolation track, contracts, slices |
| 2 | `recognition/infrastructure/embeddings/runtime_factory.py` | Sole construction seam — reuse only |
| 3 | `recognition/config/settings.py` + `security.py` (`validate_admin_config`) | Boot validation patterns; extend for bench gate |
| 4 | `api/main.py` admin mount block | Bench router mounts **inside** env-gated `/admin` only |
| 5 | `recognition/interface_adapters/http/routers/admin.py` + `admin_console.py` | `require_admin` / `AdminAuditEvent` / HTML console patterns |
| 6 | `recognition/worker/scan_worker.py` + `db/models/jobs.py` | Execution vehicle: `IdentityScanJob` / items + clustering jobs |
| 7 | `db/migrations/versions/001_identity_schema.py` | Greenfield table for `recognition_bench_runs` (bench DB only) |
| 8 | `scripts/eval_harness/face_metrics.py` | Import metric helpers (decided: import, not duplicate) |
| 9 | Scope + epic FIR-8/FIR-9 rows | S1 renumber acceptance |

## Terminology

| Term | Meaning in this plan |
| --- | --- |
| **Production deployment** | Publishable (or publishable-adjacent) recognition host: `RECOGNITION_FACE_PIPELINE_PROFILE` eventually `face_pipeline` post-FIR-6; **never** enables bench flag; holds live tenant media + 128D (or transitional) index. |
| **Bench deployment** | Separate process + separate Postgres (or isolated schema/DB) with `RECOGNITION_DEPLOYMENT_CLASS=internal_bench`, `RECOGNITION_BENCH_PROFILE_ENABLED=1`, `RECOGNITION_FACE_PIPELINE_PROFILE=insightface`, `PGVECTOR_DIM=512`, admin enabled + tailnet-bound. Non-publishable. |
| **Bench tenant** | Tenant row **inside the bench deployment DB** that owns copied media + 512D embeddings for a run. Not a production tenant id reuse without enrollment mapping. |
| **Enrolled source tenant** | The **single** production tenant UUID bound via env on the bench host (`RECOGNITION_BENCH_SOURCE_TENANT_ID`). Server-derived; clients cannot free-form retarget. |
| **Prod baseline** | Label-free aggregates from **existing** production scan output for the selected media (detection counts, faces/image, embed success). Not a second insightface run on production. |
| **Bench leg** | Full detect→embed→cluster on the bench deployment under insightface for copied media. |
| **Label-free metrics** | Counts/distributions that need no identity ground truth. Label-dependent frames (purity, identification P/R, unknown-rejection vs roster labels) are **JSON `null`** on live-tenant bench. |
| **`admin_auth_ok_context`** | Server boolean: admin mount is active, request passed `require_admin` (or UI Basic path for HTML), and boot-coupled bench license gate is satisfied for this process. SPA/HTML never invents it. |

## Problem Statement

Golden-150 answers controlled corpus quality ([DIAG-08]). Operators still need: *on this tenant’s real media, how large is the buffalo_l vs face_pipeline gap right now?*

v1 proposed dual-profile APIs and a same-process Option B. That is **structurally impossible**: `PGVECTOR_DIM` is one process-wide dim root; one deployment cannot host 512D insightface and 128D face_pipeline against one store. A `dim_mismatch` preflight cannot be cleared via API without a second deployment (or destructive wipe + dim flip — rejected).

v2 therefore **locks one track**: compare **production’s existing face_pipeline output** to an **insightface full-pipeline run on a dedicated bench deployment**, with boot-coupled license gates, operator-principal on recognition `/admin` (not WP `manage_options`), bounded work so production `scan_worker` CPU is untouched, and label-honest metrics.

## Motivation / Context

### Why this exists ([DIAG-08])

Golden-150 / eval-harness bake-offs answer: *on a curated, labeled corpus under controlled conditions, which stack wins, and by how much?* That is necessary for an operator-recorded FIR-6 gate decision, but it does **not** answer:

> On **this tenant’s real media distribution** (roster density, occlusion mix, gallery size, long-tail portraits), how large is the quality gap between buffalo_l and face_pipeline *right now*, and does a candidate improvement (FIR-7 adapters / MediaPipe detector leg later) close that gap on *our* photos?

Live-tenant benching is **diagnostic for strategy**, not a substitute for Golden-150. If an implementation only re-runs Golden-150 from any admin UI, this task has no reason to exist — refuse that design.

### Measured gap that motivates the surface

Buffalo head-to-head on Golden-150 (manifest sha256 `fe2dbe79`, decision `fir1_buffalo_head_to_head_measured`):

| Metric | buffalo_l | candidate YuNet+SFace |
| --- | ---: | ---: |
| Detection R | 0.995 | 0.504 |
| Occlusion masked | 0.865 | 0.321 |
| Unknown-rejection | 0.986 | 0.910 |
| Clustering purity | 0.898 | 0.860 |

The operator surface exists so the operator can **observe this class of gap (and future candidate improvements) on live tenant data**, with comparable **label-free** numbers where labels do not exist ([EVAL-01]), not vibes.

### Existing selection seam (reuse only)

| Surface | Role today |
| --- | --- |
| `recognition/infrastructure/embeddings/runtime_factory.py` | Selects stub / insightface / face_pipeline once for scan_worker + inline tasks + HTTP deps. Production dark default remains `insightface` until FIR-6 ([RLSE-05], [SERVE-03], [RLSE-07] cited in-module). |
| `recognition/config/settings.py` | `RECOGNITION_FACE_PIPELINE_PROFILE` env; `_FACE_PIPELINE_PROFILES = {"insightface", "face_pipeline"}`; `FacePipelineSettings`; `InsightFaceSettings`. |
| `recognition/application/embedding/manifest.py` | `active_embedding_model_id()` resolves runtime embedding space from profile (FIR23-01). |
| `recognition/application/health.py` `check_active_embedding_model()` | Fail-closed readiness when active model_id cannot resolve. |
| Cluster/suggestion read paths | FIR23-01 filters to a single `embedding_model` space. |
| Admin mount | `RECOGNITION_ADMIN_ENABLED` + token; `/admin` mounted only when enabled (`api/main.py`); `validate_admin_config` + production tailnet bind. |
| Job machinery | `IdentityScanJob` / `IdentityScanJobItem` + `IdentityClusteringJob`; `scan_worker` claims via SKIP LOCKED. |

**This task does not re-plumb detection/embedding.** It adds the operator surface + isolation + run vehicle over the seam above.

---

## Invariants (hard constraints — non-negotiable)

### I1. License / non-commercial gate ([RLSE-05], [SERVE-03]) — boot-coupled

- InsightFace `buffalo_l` weights are **NON-COMMERCIAL** (WebFace-trained). The insightface path may exist for **INTERNAL BENCHMARKING ONLY**.
- **Transitional honesty (FIR-4 status quo)**: process env default for `RECOGNITION_FACE_PIPELINE_PROFILE` remains **`insightface`** until FIR-6 switch-over. That dark default is **not** a license for product surfaces to treat buffalo as a customer-facing commercial path. Post-FIR-6, the clean product default becomes `face_pipeline`; this plan’s gates must not assume FIR-6 has already landed.
- **Server-side boot-coupled gate — a flag alone is not a license gate (FIR8PR-02).**

  When `RECOGNITION_BENCH_PROFILE_ENABLED=1`, settings/security boot **must also** require **all** of:

  1. `RECOGNITION_ADMIN_ENABLED=1` (admin mount + token rules via existing `validate_admin_config`)
  2. `RECOGNITION_ADMIN_TAILNET_BOUND=1` (explicit acknowledgement; required whenever bench is on — not only when `runtime_mode=production`)
  3. `RECOGNITION_DEPLOYMENT_CLASS=internal_bench` (exact string; other values or unset → refuse)

  Otherwise the process **refuses to start** with a stable error class (extend `InsecureProductionConfigError` or add `BenchLicenseGateError`) and a stable machine code in the message / structured log: `bench_license_gate_failed`.

  When the flag is `0`/`false` (default): process boots normally; every bench mutation route is unmounted or returns **403** `{ "error": "bench_flag_off" }` if somehow hit; no insightface bench scheduling.

- **Insightface never tenant-facing**: no workbench control, no site-front toggle, no tenant API-key route, no WP mutation path that can enable insightface.
- UI copy must include: **“non-commercial weights — internal benchmarking only”**. Status indicators pair color with icon ([sr-004]). API responses that describe bench availability carry `license_notice` with that sense.

### I2. Reuse the selection seam ([SERVE-01], [RLSE-07])

- All runtime construction continues through `build_embedding_runtime(...)`.
- Profile vocabulary stays `_FACE_PIPELINE_PROFILES` / `Literal["insightface", "face_pipeline"]` — **no third profile name** for “bench”.
- **No fork of `scan_worker` glue** — bench runs use the same worker entrypoint and job tables in the **bench** process/DB, tenant-scoped to the bench tenant.
- No parallel detector factory, no second protocol.

### I3. Embedding-space integrity ([EMB-01], FIR23-01)

- insightface = **512D**; face_pipeline / SFace = **128D**.
- `PGVECTOR_DIM` remains the sole dimension root.
- **One dim per deployment.** Production keeps its dim; bench deployment is fixed at `PGVECTOR_DIM=512` with env profile `insightface`. Silent 512D/128D mix in one store is designed out by **deployment isolation**, not by dual-profile API preflight.
- Insightface embeddings **never** land in a publishable production index.

### I4. Operator principal (FIR8PR-09 / FIR8PA-01)

- **Human principal for all bench mutations** = recognition **operator** on the tailnet-bound `/admin` surface (existing admin token / Basic console family + `AdminAuditEvent` audit rows).
- **WP `manage_options` is NOT the bench principal.** Customer site admins are internet-facing and must not hold cross-tenant recognition-admin credentials.
- **WP MVP stance (pinned): nothing.** No `acx/v1/bench/*` proxy, no SPA bench panel, no WP-held recognition-admin token for bench. Operators use the recognition `/admin` HTML console on the bench (and production diagnostics for baseline export if needed). A future read-only site-scoped results panel is explicitly **out of this task**.

### I5. Boundary honesty ([rg-015])

- Adapters/controllers must not invent envelope metadata. Every field comes from request, upstream payload, or a **named** documented constant. Nullable metrics stay `null` — never invent `0.0` purity ([EVAL-01]).

### I6. Greenfield schema policy

- No Alembic add-on migrations. Schema edits go in `001_identity_schema.py` only.
- Bench run persistence: table `recognition_bench_runs` (and optional child artifact columns/JSON) in the **bench deployment’s** schema only. Production schema may gain a **read-only diagnostics** helper endpoint without a new table if counts are computable from existing identity rows.

### I7. Independent bench verdicts ([OBS-09], [EVAL-01], [TEST-08])

- Metrics produced by a **scorer outside either model path** (bench report builder), never by counters the path under test can self-tune.
- Metric *names* align with Golden-150 / eval-harness where sensible; every payload is tagged `source=live_tenant_bench` so it is never confused with Golden-150 publishable scores ([DIAG-08]).
- **Label honesty (FIR8PR-04)**: live tenant media has **no ground truth**. Scope metrics to **label-free frames only**; label-dependent frames are **always `null`** for this task. **No operator-labeling loop in MVP.** No invented purity.

### I8. Production CPU isolation (FIR8PA-03)

- Bench runs execute **only in the bench deployment**. Production `scan_worker` is **not** scheduled for insightface re-scan of live media for this feature. Production may answer cheap **read-only** label-free baseline queries.

---

## Design decision: embedding-space isolation (LOCKED)

### Chosen track — Dedicated bench deployment (only implementable path)

**Mechanism**

| Concern | Bench deployment | Production deployment |
| --- | --- | --- |
| Process | Own API + own `scan_worker` | Untouched for bench compute |
| DB | Own Postgres (or isolated DB name/schema) | Live tenant store |
| `PGVECTOR_DIM` | **512** | 128 post-FIR-6 (or current prod value) |
| `RECOGNITION_FACE_PIPELINE_PROFILE` | **`insightface`** | `face_pipeline` (target) / transitional per FIR-4 |
| `RECOGNITION_BENCH_PROFILE_ENABLED` | **1** | **0** (must stay off) |
| `RECOGNITION_DEPLOYMENT_CLASS` | **`internal_bench`** | `production` / unset / non-bench |
| Comparison | Full pipeline leg on copied media | **Existing** face_pipeline (or active prod profile) **output** for same media_ids — read-only baseline |

Operator workflow:

1. On **production** `/admin` (or existing diagnostics): select up to N media for enrolled tenant; export or query **label-free baseline** counts.
2. On **bench** `/admin` bench panel: start run with media id list (+ resolvable media URLs under host allowlist); server binds source tenant from env; pulls bytes; enqueues scan via existing job tables; worker processes on bench; scorer builds side-by-side report (prod baseline + bench leg).
3. On completion: delete-by-default copied media + derived embeddings (TTL safety net).

**Why this is the only track**

- pgvector fixed-width + single process-wide `PGVECTOR_DIM` makes dual-dim in one store impossible.
- Sequential same-process wipe/flip (old Option B) is not a side-by-side comparison, risks multi-tenant foot-guns, and is unnecessary given greenfield dedicated eval hosts already in the epic narrative.

### Rejected alternatives (appendix — do not implement)

| Id | Alternative | Why rejected |
| --- | --- | --- |
| R-B | **Option B — same-process profile override + wipe** | Cannot hold 512D and 128D simultaneously; sequential only; wipe foot-gun; process-wide flip hits all tenants on the instance; preflight `dim_mismatch` unresolvable without redeploy. |
| R-dual-POST | **Single-deployment `POST /runs` with `profiles: [face_pipeline, insightface]`** | Same dual-dim impossibility; “both profiles construct” gate contradicts I3. |
| R-ui-hide | UI-only hide of insightface | Not a license gate. |
| R-mixed-rows | Write both dims into production `media_identities` | pgvector width + clustering poison; FIR23-01 filters are not a storage fix. |
| R-wp-principal | WP `manage_options` as mutation principal | Wrong trust boundary; internet-facing customer admins; would require WP to hold recognition-admin credentials. |
| R-golden-spa | Re-host Golden-150 in admin UI | Violates [DIAG-08] reason this task exists. |

**MCP decision id (record at S1 start):** `fir8_isolation_mode_dedicated_bench_deployment` (locked; not a menu).

---

## Non-goals

- **No production switch-over logic** — FIR-6.
- **No new model legs** — FIR-7 / separate evals.
- **No public / tenant-facing** insightface path.
- **No Golden-150 re-host** as a substitute for live-tenant bench ([DIAG-08]).
- **No new embedding pipeline / protocol** — FIR-2 seam + FIR-4 factory only.
- **No commercial redistribution** of buffalo weights; insightface stays in `[bench]` extra narrative.
- **No WP control surface or WP proxy** in this task.
- **No dual-profile single-process runs**; no Option B.
- **No invented label-dependent metrics** on unlabeled live media.
- **No production scan_worker load** for bench insightface compute.
- **No escalation-ladder implementation** — that work is **FIR-9** after renumber.

---

## Current State Analysis

- Profile is **env-resolved only** at settings construction; no admin REST mutates it today — **and this plan does not add process-wide profile mutation**.
- Production dark default remains **`insightface`** (FIR-4) until FIR-6; document transitional state honestly in I1.
- Recognition operator admin: FastAPI `/admin` + hand-written HTML console (`admin_console.py`), env-gated, `AdminAuditEvent` on mutations, `validate_admin_config` at boot.
- Job path: `IdentityScanJob` / items + clustering jobs + `scan_worker` SKIP LOCKED claim — **reuse as bench execution vehicle** (no new job engine).
- Dim root defaults to **512** until FIR-6; face_pipeline dark exercise needs `PGVECTOR_DIM=128` + empty index — **bench host stays 512**.
- Eval metrics under `scripts/eval_harness/` — **import helpers** (decision pinned below).

---

## Target Outcome

1. Bench host boots only when boot-coupled license gate is complete; otherwise refuse start with `bench_license_gate_failed`.
2. Operator on bench `/admin` can start a **bounded** live-tenant bench run; production baseline is read-only label-free stats; bench leg is insightface full pipeline via existing scan_worker machinery.
3. Production tenant identity tables never receive insightface vectors; bench artifacts delete-by-default after run (+ TTL).
4. All construction still goes through `build_embedding_runtime`; no third profile name; no scan_worker fork.
5. Metrics are label-free or null; `source=live_tenant_bench`; `license_notice` always present on bench API payloads.
6. Scope + epic ID collision fixed (FIR-8 = this plan; FIR-9 = escalation ladder) in S1 baseline.

---

## Boot-coupled license gate (FIR8PR-02) — normative

Implement as `validate_bench_license_gate(settings, security_settings)` called from the same startup path as `validate_admin_config` (API process **and** worker process entrypoints that construct recognition settings).

```text
if not RECOGNITION_BENCH_PROFILE_ENABLED:
    return  # no-op

require:
  RECOGNITION_ADMIN_ENABLED == true
  RECOGNITION_ADMIN_TAILNET_BOUND == "1"
  RECOGNITION_DEPLOYMENT_CLASS == "internal_bench"   # exact
  existing validate_admin_config token length rules (admin is enabled)

else → raise BenchLicenseGateError / InsecureProductionConfigError
       stable code: bench_license_gate_failed
```

**Defense in depth:** even if boot were bypassed in tests, every bench mutation dependency re-checks `bench_enabled ∧ deployment_class == internal_bench ∧ admin_enabled` and returns 403 `bench_license_gate_failed` / `bench_flag_off`.

`admin_auth_ok_context` (response field component) ≔ request authenticated via `require_admin` **and** process passed boot gate (bench host) **or** admin enabled (production diagnostics). Never client-supplied.

---

## Media intake contract (FIR8PR-03) — normative

### Source binding

| Field | Source | Client may set? |
| --- | --- | --- |
| `source_tenant_id` | Env `RECOGNITION_BENCH_SOURCE_TENANT_ID` (UUID) on bench host | **No** — server-derived; if body includes a different value → **400** `source_tenant_mismatch` |
| Bench-side tenant for storage | Env `RECOGNITION_BENCH_TENANT_ID` (UUID of tenant row in **bench** DB) | **No** |
| Media host allowlist | Env `RECOGNITION_BENCH_MEDIA_HOST_ALLOWLIST` (comma-separated hostnames) | **No** |

### Named byte-transfer mechanism

**Bench-side HTTPS GET of media bytes** (“pull into bench”):

1. Operator POST includes `media_items: [{ "media_id": int, "media_url": "https://..." }, ...]` (URLs are the production media/blob URLs the operator is authorized to see as operator — not free-form third-party hosts).
2. Server validates each URL: scheme `https`, host ∈ allowlist, no redirects outside allowlist (max 2 redirects, re-check host).
3. Server GETs bytes with bounded size (`RECOGNITION_BENCH_MAX_BYTES_PER_MEDIA`, default **15 MiB**) and wall timeout per object (default **30s**).
4. Bytes stored under the **bench tenant** via existing media/blob persistence patterns (reuse store APIs; do not invent a second blob subsystem).
5. Each successful ingest writes an **audit row**: `AdminAuditEvent.BENCH_MEDIA_INGEST` with media_id, byte length, sha256, source_tenant_id, run_id.
6. Failed fetch → item marked failed; does not invent success counts ([rg-015]).

No WP credentials. No production DB write credentials on the bench host beyond optional **read-only** baseline HTTP client config:

- `RECOGNITION_BENCH_SOURCE_BASE_URL` + `RECOGNITION_BENCH_SOURCE_ADMIN_TOKEN` (server-held) to call production `GET /admin/diagnostics/label-free-media-stats` for the enrolled source tenant. If unset, prod baseline metrics are `null` and `baseline_status=unavailable` (honest).

### Retention / deletion (delete-by-default)

| Artifact | Policy |
| --- | --- |
| Copied media bytes on bench | **Delete on run terminal state** (`completed` / `failed` / `cancelled`) by default |
| Derived `media_identities` / embeddings on bench tenant for that run’s media | **Delete with media** (same cleanup transaction/job) |
| `recognition_bench_runs` row + metrics JSON | **Retain** for operator history; TTL purge after **30 days** (configurable `RECOGNITION_BENCH_RUN_RETENTION_DAYS`, default 30) |
| Safety net | If process crashes after complete-but-before-delete: startup sweeper deletes media for runs in terminal state with `artifacts_purged_at IS NULL`, and deletes any non-terminal run older than wall-clock timeout |

Optional override `retain_artifacts=true` on POST is **rejected in MVP** (400 `retain_not_supported`) to keep policy simple — delete-by-default only.

---

## Bounded work (FIR8PA-03 / ops R-2) — normative

| Bound | Value | Justification |
| --- | --- | --- |
| **Hard max sample size** | **`MAX_BENCH_SAMPLE = 20`** images | Buffalo_l CPU path historically ~**17 s/image** load+infer class (worker logs / latency notes). 20 × 17 s ≈ **5.7 min** pure embed budget before cluster; keeps interactive operator loops sane. Server rejects `media_count > 20` with **400** `sample_limit_exceeded`. |
| **UI / default N** | **`DEFAULT_BENCH_SAMPLE_N = 10`** | Half of max; default pre-fill only when operator uses “suggest last N” helper — never auto-starts. |
| **Empty selection** | **Empty means NOTHING** | Zero media_ids → **400** `empty_selection`. Never interpret empty as “all media”. |
| **Single concurrent run** | Global on bench deployment | If any run in `queued` or `running`, POST → **409** `bench_run_in_progress`. Enforce with DB unique partial index / transactional check + optional file flock on worker claim. |
| **Wall-clock timeout** | **`RECOGNITION_BENCH_RUN_TIMEOUT_SEC=900`** (15 min) | Covers 20×17s + cluster + I/O headroom. Exceed → mark `failed` with `error=run_timeout`; cancel outstanding scan items. |
| **CPU placement** | Bench deployment only | Production scan_worker never receives insightface bench jobs. |

---

## Label-free metrics contract (FIR8PR-04)

### Included (label-free)

Per leg (`prod_baseline`, `bench_insightface`):

- `images_requested`, `images_accepted`, `images_failed_ingest` (bench leg)
- `images_with_detections`, `detection_count_total`, `faces_per_image_mean`, `faces_per_image_p50`
- `embed_success_count`, `embed_failure_count` (when distinguishable)
- Bench-only after cluster: `cluster_count`, `cluster_size_hist` (sizes only), `singleton_cluster_count`
- Deltas: arithmetic differences for shared numeric fields where both sides non-null

### Always null on live-tenant bench (no ground truth)

- `cluster_purity`, `identification_precision`, `identification_recall`, `unknown_rejection`, any Fair-SA / labeled slice score

Do **not** emit `0.0` for those keys — emit JSON `null` or omit with explicit schema saying null. Scorer imports count/histogram helpers from `scripts/eval_harness/face_metrics.py` where import path is clean (**decision: import**, not duplicate — see [Small pins](#small-pins-fir8pr-07--ops-r-8r-10)).

---

## Run lifecycle (FIR8PR-05)

### State machine

```text
queued → running → completed
                 → failed
                 → cancelled
```

| State | Meaning |
| --- | --- |
| `queued` | Row inserted; media ingest not finished or scan job not claimed |
| `running` | Ingest done; scan and/or cluster in progress |
| `completed` | Metrics sealed; artifact purge scheduled/done |
| `failed` | Terminal error (`run_timeout`, ingest hard-fail threshold, worker error) |
| `cancelled` | Operator cancel **or** cancel-on-disable |

### Execution vehicle (FIR8PR-08) — named

**Reuse existing `scan_worker` job machinery in the BENCH deployment** (bench tenant scope):

1. POST creates `recognition_bench_runs` (`status=queued`).
2. Ingest media (sync, bounded) → on success create `IdentityScanJob` + items for **bench tenant** with stored media URLs/ids.
3. Existing `scan_worker` (bench process) claims items → detect/embed via `build_embedding_runtime` (env profile insightface).
4. On scan completion, enqueue clustering job as today’s scan path does.
5. Bench run supervisor (thin application service polled by worker loop **or** API background task that only transitions state — prefer **worker-side tick** to avoid second scheduler): when scan+cluster terminal, run scorer, set `completed`/`failed`, purge artifacts.

**Not in scope:** dual full-pipeline 202 without a job table (v1 gap). **Not in scope:** new distributed queue product.

Tests must cover: enqueue creates scan job rows; worker processes under bench tenant; second POST concurrent → 409; timeout → failed.

### Crash recovery

- API/worker startup: runs in `running` or `queued` older than timeout → `failed` / `error=stale_reclaim` (mirror describe-run reclaim pattern in `api/main.py` lifespan).
- Orphan scan jobs for bench tenant: existing worker stale reclaim paths apply; bench supervisor reconciles parent run status.

### Cancel-on-disable

- If process restarts with `RECOGNITION_BENCH_PROFILE_ENABLED=0`, boot succeeds **without** bench routes; any leftover DB rows are inert (no worker bench supervisor). Prefer: operator disables only by tearing down bench host.
- Soft path: `POST /admin/bench/runs/{id}/cancel` (admin auth) sets `cancelled`, attempts to mark pending scan items failed/cancelled, purge artifacts.
- If gate env flipped while process still up (config reload not supported today): document **restart required**; no hot reload.

### Preflight blockers — **chosen track only** (FIR8PR-06)

`activation_blockers` / preflight codes for GET availability (no Option B codes):

| Code | When |
| --- | --- |
| `bench_flag_off` | Flag false |
| `bench_license_gate_failed` | Flag true but admin/tailnet/deployment_class incomplete (should not serve if boot-coupled; still on mutation path) |
| `deployment_class_not_bench` | `RECOGNITION_DEPLOYMENT_CLASS != internal_bench` |
| `source_tenant_unconfigured` | `RECOGNITION_BENCH_SOURCE_TENANT_ID` missing/invalid |
| `bench_tenant_unconfigured` | `RECOGNITION_BENCH_TENANT_ID` missing |
| `media_allowlist_unconfigured` | Allowlist empty |
| `insightface_runtime_unavailable` | `build_embedding_runtime` / readiness cannot load insightface on this host |
| `pgvector_dim_not_512` | Bench host `PGVECTOR_DIM != 512` |
| `profile_not_insightface` | Env profile ≠ `insightface` on bench host |
| `bench_run_in_progress` | Concurrent run (POST only) |

**Removed from S1 matrix (v1):** `foreign_embedding_model_rows`, `confirm_wipe`, dual-profile construct checks, process-override effective profile flips.

---

## Contract and Boundary Impact

### Recognition service — bench host (authoritative mutations)

Mount **only** under the existing env-gated **`/admin`** router tree (FIR8PR-07): e.g. routes registered on `admin_router` or `include_router(bench_router, prefix=...)` **inside** the `if security_settings.admin_enabled` block in `api/main.py`. **Never** on the tenant API-key `/recognition` router.

Auth: `Depends(require_admin)` / `require_admin_header` for JSON; HTML forms use existing same-origin + Basic patterns.

Audit enum additions (`AdminAuditEvent`, sr-007):

- `BENCH_RUN_CREATE = "bench.run.create"`
- `BENCH_RUN_CANCEL = "bench.run.cancel"`
- `BENCH_MEDIA_INGEST = "bench.media.ingest"`

#### `GET /admin/bench/status`

**Response 200** (all server-derived):

```json
{
  "bench_enabled": true,
  "bench_available": true,
  "deployment_class": "internal_bench",
  "env_profile": "insightface",
  "effective_profile": "insightface",
  "embedding_model_id": "insightface-buffalo_l@512d/l2/cosine",
  "pgvector_dimension": 512,
  "isolation_mode": "dedicated_bench_deployment",
  "source_tenant_id": "uuid",
  "bench_tenant_id": "uuid",
  "max_sample_size": 20,
  "default_sample_size": 10,
  "active_run_id": null,
  "license_notice": "non-commercial weights — internal benchmarking only",
  "activation_blockers": []
}
```

- `bench_available` ≔ `bench_enabled && admin_auth_ok_context && activation_blockers == []` (server computes).
- `isolation_mode` is the **constant** `"dedicated_bench_deployment"` (not a client choice).

#### `POST /admin/bench/runs`

**Request**:

```json
{
  "media_items": [
    { "media_id": 101, "media_url": "https://cdn.example/…" }
  ],
  "sample_limit": 10
}
```

- `source_tenant_id` **not accepted** from client (server env). If present and ≠ enrolled → 400 `source_tenant_mismatch`.
- `sample_limit` optional; server applies `min(len(media_items), sample_limit, MAX_BENCH_SAMPLE)`; if `len==0` → 400 `empty_selection`.
- `profiles` array **not accepted** — bench leg is always insightface; prod baseline is separate read.

**Response 202**:

```json
{
  "run_id": "uuid",
  "status": "queued",
  "media_count": 10,
  "isolation_mode": "dedicated_bench_deployment",
  "license_notice": "non-commercial weights — internal benchmarking only"
}
```

- `media_count` = **accepted after validation**, not raw request length ([rg-015]).

#### `GET /admin/bench/runs/{run_id}`

```json
{
  "run_id": "uuid",
  "status": "completed",
  "media_count": 10,
  "metrics": {
    "source": "live_tenant_bench",
    "prod_baseline": {
      "status": "ok",
      "detection_count_total": 40,
      "images_with_detections": 9,
      "faces_per_image_mean": 4.0,
      "cluster_purity": null,
      "unknown_rejection": null
    },
    "bench_insightface": {
      "detection_count_total": 55,
      "images_with_detections": 10,
      "faces_per_image_mean": 5.5,
      "cluster_count": 12,
      "cluster_purity": null,
      "unknown_rejection": null
    },
    "deltas": {
      "detection_count_total": 15,
      "images_with_detections": 1
    }
  },
  "license_notice": "non-commercial weights — internal benchmarking only",
  "artifacts_purged_at": "2026-07-23T12:00:00Z"
}
```

#### `POST /admin/bench/runs/{run_id}/cancel`

→ 200 with status `cancelled` or 409 if already terminal.

### Recognition service — production host (read-only baseline)

#### `GET /admin/diagnostics/label-free-media-stats`

- Admin auth only; **no** bench flag required.
- Query: enrolled tenant via normal admin tenant context or explicit `tenant_id` that admin already may manage; `media_ids` list capped at 20.
- Returns label-free counts from **existing** identity rows only; never schedules work.
- Used by bench host’s optional baseline client; also usable from production HTML diagnostics.

### WordPress plugin

**No routes, no SPA panel, no proxy in this task.** (FIR8PR-09)

### Persistence (bench DB)

Table `recognition_bench_runs` in `001_identity_schema.py` (consumed by bench deployments; harmless if present on prod but unused):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | run_id |
| `status` | str | state machine |
| `source_tenant_id` | UUID | enrolled source |
| `bench_tenant_id` | UUID | local bench tenant |
| `media_ids` | int[] / JSON | accepted ids |
| `media_count` | int | accepted count |
| `scan_job_id` | UUID nullable | FK-ish to identity_scan_jobs |
| `metrics` | JSONB nullable | sealed on complete |
| `error_code` | text nullable | stable codes |
| `created_at` / `started_at` / `completed_at` | timestamptz | |
| `artifacts_purged_at` | timestamptz nullable | |

### Observability

- Log fields: `bench_run_id`, `embedding_model_id`, `isolation_mode=dedicated_bench_deployment`, `source=live_tenant_bench`.
- Do not emit onto production quality SLO dashboards without a `bench` label ([OBS-09]).

### Operator HTML UI (bench `/admin`)

Extend `admin_console.py` (or sibling) with a **Bench** section:

- License banner (non-commercial).
- Shows `activation_blockers` when `bench_available=false`.
- When available: media list input (ids+urls), default N display **10**, max **20**, empty submit → server error surfaced (empty means nothing).
- Primary control reachable at zero selection for **navigating to the form**, but **Run** requires non-empty validated items ([rg-003] = control visible; submit still validates non-empty).
- Status poll of active run; statuses as server strings mapped in one place (Python enum / const), not scattered magic compares.

---

## Small pins (FIR8PR-07 + ops R-8/R-10)

| Pin | Decision |
| --- | --- |
| Bench router mount | **Inside** env-gated `/admin` only (`api/main.py` admin branch). |
| eval_harness | **Import** `face_metrics` helpers from `scripts/eval_harness/`; if import packaging is awkward under app layout, add a thin re-export module under `recognition/application/bench/` that imports harness — **no formula fork**. Parity unit test only if a local wrapper transforms units. |
| I1 default | Transitional: dark env default still **insightface** until FIR-6; bench gate still required for operator bench surface / `internal_bench` class. |
| Default sample N | **10**; hard max **20**. |
| Empty selection | **Nothing** — 400 `empty_selection`; never “all”. |
| WP | **Nothing in MVP**. |

---

## ID collision (FIR8PA-04)

**Pick: keep task id `FIR-8` for this plan; renumber escalation ladder → `FIR-9`.**

S1 acceptance **must** edit in the same baseline:

1. `docs/scopes/commercial-face-identity-replacement.md` — task table row + Not-Doing bullets that say “FIR-8” for escalation → **FIR-9**; rollback sentence “Escalation then follows FIR-8” → **FIR-9**.
2. `docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md` — P4 row `FIR-8 (contingent escalation)` → **FIR-9**.

Do not leave “follow-on renumber” language.

---

## Slice Delivery

| Slice | Content | Acceptance gate | Primary tests |
| --- | --- | --- | --- |
| **S1** Boot gate + isolation lock + ID renumber | `RECOGNITION_BENCH_PROFILE_ENABLED` default false; `validate_bench_license_gate`; `RECOGNITION_DEPLOYMENT_CLASS`; preflight pure fn for **dedicated-bench codes only**; MCP decision `fir8_isolation_mode_dedicated_bench_deployment`; **edit scope + epic FIR-8→FIR-9 escalation** | Boot refuses incomplete bench license set; flag-off boots; scope+epic grep-clean for escalation id | Unit: boot matrix; preflight table; doc assertion or checklist evidence |
| **S2** Run vehicle + bounds + schema | `recognition_bench_runs` in `001_identity_schema.py`; create run → `IdentityScanJob` on bench tenant; single-flight 409; max 20; timeout; worker supervisor transitions; crash reclaim | Integration: job rows appear; concurrent POST 409; timeout fails run | Unit + API + worker tests |
| **S3** Media intake + retention + audit | Pull mechanism, allowlist, audit events, delete-by-default purge, optional prod baseline client | Ingest audit written; purge clears media+embeddings; bad host rejected | Unit + API |
| **S4** REST metrics + status | GET status/runs; scorer label-free + null purity; `license_notice`; import eval_harness | Contract tests null purity; 403 without admin; blockers codes | API tests under `recognition/tests/api/` |
| **S5** `/admin` HTML bench panel | Console section; banner; blockers; run form; empty≠all; default N=10 | HTML contains non-commercial notice; blocked state renders blockers | API/console tests (existing admin test style) |

S1 → S2 → S3 → S4 sequential; S5 after status/run JSON frozen (fixtures from S4).

---

## Junior-executable contracts (per slice)

### S1 — Boot gate + preflight + docs renumber

**Files**

- `recognition/config/security.py` or `settings.py`: `_bool_env("RECOGNITION_BENCH_PROFILE_ENABLED", False)`; `deployment_class` from `RECOGNITION_DEPLOYMENT_CLASS`; `validate_bench_license_gate`.
- `recognition/application/bench/preflight.py`: pure blockers for dedicated track only.
- `api/main.py` + worker entry: call validate at startup when constructing app/worker.
- Scope + epic markdown renumber (FIR-9).

**Preflight signature**

```text
preflight_bench_available(*, bench_enabled: bool, deployment_class: str,
  admin_enabled: bool, tailnet_bound: bool, source_tenant_configured: bool,
  bench_tenant_configured: bool, media_allowlist_configured: bool,
  pgvector_dimension: int, env_profile: str,
  insightface_runtime_ok: bool) -> list[str]
```

**Tests (red first, [TEST-06])**

1. Flag off → blockers include `bench_flag_off`; boot OK without deployment_class.
2. Flag on + missing tailnet → **boot raises** `bench_license_gate_failed`.
3. Flag on + `deployment_class=production` → boot raises.
4. Flag on + full license set + dim≠512 → blockers include `pgvector_dim_not_512`.
5. Flag on + profile `face_pipeline` → `profile_not_insightface`.
6. All clear → `[]`.
7. Scope/epic: escalation references are `FIR-9` not `FIR-8` (checklist evidence in slice decision).

**Mutation red-proof**: force validator to skip `deployment_class` check → test 3 fails.

### S2 — Run vehicle

**Rules**

- No second worker binary; start bench `scan_worker` against bench DSN as today.
- Single active run: transactional check on insert.
- Map run → one `IdentityScanJob` for bench tenant.
- Timeout task marks failed.

**Tests**

1. POST creates run + scan job with `media_count` matching accepted items.
2. Second POST while running → 409 `bench_run_in_progress`.
3. 21 media items → 400 `sample_limit_exceeded`.
4. 0 items → 400 `empty_selection`.
5. Simulated timeout → status `failed`, `error_code=run_timeout`.

### S3 — Intake + retention

**Tests**

1. Host not on allowlist → item rejected; no silent accept.
2. Successful ingest → audit `bench.media.ingest` + sha256 field present.
3. On complete → media + embeddings gone; `artifacts_purged_at` set; metrics retained.
4. Body `source_tenant_id` ≠ env → 400.

### S4 — REST + scorer

**Rules**

- Router under admin mount only.
- Scorer in `recognition/application/bench/score.py`; **import** harness helpers.
- Never call adapters to self-report quality ([OBS-09]).

**Tests**

1. Unauthenticated → 401/403.
2. Flag off → 403 `bench_flag_off`.
3. Completed unlabeled run → `cluster_purity` is JSON `null`.
4. `license_notice` contains `non-commercial`.
5. `isolation_mode` constant `dedicated_bench_deployment`.

### S5 — HTML console

**Tests**

1. `bench_available=false` → blockers visible; run submit absent or disabled.
2. Banner substring `non-commercial`.
3. Form does not default media selection to “all”.

---

## Files and Surfaces to Change (implementation map)

| Area | Likely paths |
| --- | --- |
| Gate / settings | `recognition/config/settings.py`, `recognition/config/security.py` |
| Preflight / score / supervisor | `recognition/application/bench/*` (new) |
| Factory | **call only** via existing `build_embedding_runtime` — no third profile |
| HTTP | `recognition/interface_adapters/http/routers/admin.py` (or `bench.py` included from admin), `admin_console.py`, `api/main.py` mount stays admin-gated |
| Worker | `recognition/worker/scan_worker.py` — **hooks only if needed** for supervisor tick; prefer application service called from existing loop without forking |
| Schema | `db/migrations/versions/001_identity_schema.py` + `db/models/` |
| Production diagnostics | small admin GET for label-free stats |
| WP | **none** |
| Docs | scope + epic renumber; short runbook under `docs/runbooks/` (bench deploy env template) |
| Tests | `recognition/tests/api/test_bench_*.py`, unit preflight/score/purge |

---

## Verification Strategy

- Per-slice scoped TDD; observe new tests fail first ([TEST-06]).
- Discriminating gate tests ([TEST-15]): boot license matrix × preflight blockers × bounds matrix.
- Determinism ([TEST-08]): scorer pure over fixtures; null purity locked.
- `make check-remote` for description-service surfaces touched.
- Manual smoke (close decision): bench compose/stack with flag+class+admin+tailnet; 10 real media URLs; insightface detection counts visible; prod baseline null or populated; purge verified; production worker CPU idle for bench jobs; license banner present.
- Adversarial review per slice; findings **only** in handoff MCP (not pasted into this plan).

---

## Consolidated Checklist

### Context and Ownership

- [ ] MCP decision `fir8_isolation_mode_dedicated_bench_deployment` recorded (locked track — not A/B menu)
- [ ] Plan accepted via planning-review before `make task-start TASK=FIR-8`
- [ ] Worktree: `feature/fir-8` via `make task-start`

### S1 — Boot gate + isolation + ID renumber

- [ ] `RECOGNITION_BENCH_PROFILE_ENABLED` default false
- [ ] Boot-coupled gate: admin + tailnet_bound + `deployment_class=internal_bench` or refuse start
- [ ] Pure preflight for **dedicated-bench codes only** + table-driven tests
- [ ] Red-proof on deployment_class / license checks
- [ ] **Scope + epic**: escalation ladder → **FIR-9**; this bench task remains **FIR-8** (same baseline)
- [ ] Slice decision recorded

### S2 — Run vehicle + bounds

- [ ] `recognition_bench_runs` in `001_identity_schema.py`
- [ ] scan_worker job machinery reused (bench tenant); no worker fork
- [ ] Max 20 / default 10 / empty=nothing / single-flight / 900s timeout
- [ ] State machine + crash reclaim + cancel path
- [ ] Slice decision recorded

### S3 — Media intake + retention

- [ ] Enrolled source tenant server-derived
- [ ] HTTPS pull + host allowlist + size/time bounds
- [ ] Ingest audit rows
- [ ] Delete-by-default media + embeddings; run row retention 30d
- [ ] Slice decision recorded

### S4 — REST + metrics

- [ ] Routes only under `/admin`
- [ ] Label-free metrics; null label-dependent frames
- [ ] Independent scorer; eval_harness **import**
- [ ] `license_notice` + `source=live_tenant_bench`
- [ ] Optional prod baseline client honesty (`unavailable` vs inventing zeros)
- [ ] Slice decision recorded

### S5 — Operator HTML UI

- [ ] Panel on recognition `/admin` console only
- [ ] Non-commercial banner; blockers zero-state
- [ ] No WP surfaces
- [ ] Slice decision recorded

### Review readiness

- [ ] `make check-remote` green at HEAD
- [ ] `/review-parallel` findings in MCP only
- [ ] Zero open findings; `handoff_close_check(enforce=True)`

---

## Success Criteria

1. Incomplete bench license env **cannot boot** a bench-enabled process; flag-off production boots and cannot schedule insightface bench runs.
2. Operator obtains comparable **label-free** live-tenant numbers: production baseline vs bench insightface leg, **without** mixing embedding spaces in production.
3. License notice is visible and API-carried; insightface remains non-public and non-WP.
4. Runtime construction still funnels through `build_embedding_runtime` and `_FACE_PIPELINE_PROFILES`; no scan_worker fork.
5. Live-tenant bench output is explicitly not Golden-150 ([DIAG-08]); null purity on unlabeled media ([EVAL-01], [rg-015]).
6. Bench compute never lands on production scan_worker; bounds enforced server-side.
7. Scope + epic IDs consistent: FIR-8 = bench surface; FIR-9 = escalation ladder.

---

## Rollback

- Tear down or stop the **bench deployment**; set `RECOGNITION_BENCH_PROFILE_ENABLED=0` on any misconfigured host (instant fail-closed).
- Production: no schema dependency for correct product behavior; optional diagnostics endpoint is read-only.
- Drop bench DB / greenfield reset clears 512D artifacts.
- No FIR-6 product default changes in this task — rollback must not reintroduce buffalo as a silent **commercial** production default ([RLSE-08] spirit).
- Escalation after a failed product gate is **FIR-9**, not a weight revert post-commercial-launch.

---

## Planning-review finding map (v2 resolution index)

| Finding | Severity | Resolution anchor in this plan |
| --- | --- | --- |
| **FIR8PR-01** dual-dim infeasibility | high | [Design decision: LOCKED dedicated bench](#design-decision-embedding-space-isolation-locked); [Rejected alternatives](#rejected-alternatives-appendix--do-not-implement) |
| **FIR8PR-08** no execution vehicle | high | [Execution vehicle](#execution-vehicle-fir8pr-08--named); Slice **S2** |
| **FIR8PR-02** license gate boot-coupled | high | [I1](#i1-license--non-commercial-gate-rlse-05-serve-03--boot-coupled); [Boot-coupled license gate](#boot-coupled-license-gate-fir8pr-02--normative) |
| **FIR8PR-09 / FIR8PA-01** wrong human principal | high | [I4](#i4-operator-principal-fir8pr-09--fir8pa-01); WP **nothing** in MVP; `/admin` console S5 |
| **FIR8PR-03** media intake | high | [Media intake contract](#media-intake-contract-fir8pr-03--normative); Slice **S3** |
| **FIR8PA-03 / ops R-2** bounded work | high | [Bounded work](#bounded-work-fir8pa-03--ops-r-2--normative); [I8](#i8-production-cpu-isolation-fir8pa-03) |
| **FIR8PR-04** label honesty | medium | [I7](#i7-independent-bench-verdicts-obs-09-eval-01-test-08); [Label-free metrics](#label-free-metrics-contract-fir8pr-04) |
| **FIR8PR-05 / FIR8PR-06** lifecycle + enforcement | medium | [Run lifecycle](#run-lifecycle-fir8pr-05); [Preflight blockers](#preflight-blockers--chosen-track-only-fir8pr-06); S1 test matrix rewrite |
| **FIR8PR-07 + ops R-8/R-10** small pins | low | [Small pins](#small-pins-fir8pr-07--ops-r-8r-10); I1 transitional default |
| **FIR8PA-04** ID collision | medium | [ID collision](#id-collision-fir8pa-04); S1 checklist edits scope+epic |
| **FIR8PA-05 / FIR8PA-06** wipe policy & loose ends | low | Option B wiped from implementable path; [Retention](#retention--deletion-delete-by-default); `admin_auth_ok_context` in Terminology; persistence table; Problem Statement / Terminology / Context Loading sections |

### Invariants preserved from v1

- Reuse `build_embedding_runtime`; no third profile name; no scan_worker fork.
- Non-commercial banner + `license_notice`; insightface never tenant-facing.
- rg-015 envelope honesty; greenfield `001_identity_schema.py` policy; house frontend rules (admin HTML console tokens/escape discipline).
- Golden-150 relationship per [DIAG-08] as diagnostic complement, not substitute.
