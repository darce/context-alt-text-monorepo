# FIR-8. Operator Bench: Live-Tenant InsightFace vs Production face_pipeline

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok (docs-only plan authoring)
> - **Plan version**: v5 (resolves round-4 findings FIR8R4-01…04 — supervisor/lifecycle semantics; preserves v4 structure + v1 structural invariants)
> - **Projects**: `apps/prototype-description-service` (primary); WP plugin **out of MVP control path**
> - **Task ID**: `FIR-8` (operator-assigned bench surface; escalation ladder renumbered to **FIR-9** — see [ID collision](#id-collision-fir8pa-04))
> - **Target Branch**: `feature/fir-8`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-4 (shared `build_embedding_runtime` + `RECOGNITION_FACE_PIPELINE_PROFILE` seam, merged); FIR23-01 (`embedding_model` enforced on read paths + fail-closed readiness)
> - **House style note**: Structure follows FIR-4 (invariants, per-slice gates, consolidated checklist) plus junior-executable contracts
> - **Review Coverage Target**: 2
> - **Isolation track (LOCKED)**: **dedicated bench deployment only** — no process-wide dual-dim toggle, no Option B
> - **Baseline credential (LOCKED, FIR8R2-03)**: **option (b)** — operator uploads label-free baseline artifact via bench `/admin` (zero new prod credentials on bench host)
> - **Execution mode (LOCKED, FIR8R2-01)**: **fully async** — POST validates + inserts + 202; bench `scan_worker` supervisor owns ingest→scan→score→seal→purge→completed (non-blocking ticks)

## Objective

Ship an **operator-facing, recognition-side `/admin` surface** that lets a tailnet-bound operator compare recognition quality between InsightFace `buffalo_l` (bench deployment only) and the clean candidate `face_pipeline` **already measured on production**, using **live tenant media** samples — by reusing the existing profile selection seam, **not** inventing a second pipeline.

Deliverables: boot-coupled license/deployment gate, dedicated-bench isolation (own process + own DB/schema + `PGVECTOR_DIM=512` + `profile=insightface`) with **data-plane isolation proof**, **fully async** scan_worker-backed bounded run vehicle, media intake + retention contract (IDs only; server-derived URLs), label-free metrics with honest nulls, operator-uploaded production baseline artifact, and an `/admin` HTML console panel labeled for internal non-commercial benchmarking only.

## Intake

- **Operator ask**: admin control for InsightFace path as **internal benchmarking only**, so the operator can see the quality gap on real tenant media before model-strategy decisions.
- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) (license isolation + single-model prod DB intake) · E22 epic hard constraints · FIR-4 runtime factory
- **ID collision (FIR8PA-04)**: scope table + epic currently reserve “FIR-8” for the contingent **escalation ladder**. This plan **keeps `FIR-8` for the bench surface** (operator-assigned) and **renumbers the escalation ladder to `FIR-9`**. S1 checklist **requires** editing both the scope task table and the epic P4/rollback/Not-Doing references in the **same baseline** as gate code — not a follow-on. See [ID collision](#id-collision-fir8pa-04).
- **Not-Doing here**: listed under [Non-goals](#non-goals).

## Context Loading (read before implementation)

| Order | Path | Why |
| --- | --- | --- |
| 1 | This plan (v5) end-to-end | Locked isolation track, async vehicle, contracts, slices |
| 2 | `recognition/infrastructure/embeddings/runtime_factory.py` | Sole construction seam — reuse only |
| 3 | `recognition/config/settings.py` + `security.py` (`validate_admin_config`) | Boot validation patterns; extend for bench gate + denylist |
| 4 | `api/main.py` admin mount block | Bench router mounts **inside** env-gated `/admin` only |
| 5 | `recognition/interface_adapters/http/routers/admin.py` + `admin_console.py` | `require_admin` / `AdminAuditEvent` / HTML console patterns |
| 6 | `recognition/worker/scan_worker.py` + `db/models/jobs.py` | Execution vehicle: supervisor tick + `IdentityScanJob` / items + clustering |
| 7 | `recognition/application/storage/filesystem.py` | Ingest persistence: `FilesystemObjectStore.put` |
| 8 | `db/migrations/versions/001_identity_schema.py` | Greenfield table for `recognition_bench_runs` + markers (bench DB) |
| 9 | `scripts/eval_harness/face_metrics.py` | Formula **source of truth for parity fixture only** — runtime uses in-tree duplicate (FIR8R2-07) |
| 10 | Scope + epic FIR-8/FIR-9 rows | S1 renumber acceptance |

## Terminology

| Term | Meaning in this plan |
| --- | --- |
| **Production deployment** | Publishable (or publishable-adjacent) recognition host: `RECOGNITION_FACE_PIPELINE_PROFILE` eventually `face_pipeline` post-FIR-6; **never** enables bench flag; holds live tenant media + 128D (or transitional) index. |
| **Bench deployment** | Separate process + separate Postgres (or isolated schema/DB) with `RECOGNITION_DEPLOYMENT_CLASS=internal_bench`, `RECOGNITION_BENCH_PROFILE_ENABLED=1`, `RECOGNITION_FACE_PIPELINE_PROFILE=insightface`, `PGVECTOR_DIM=512`, admin enabled + tailnet-bound. Non-publishable. Own `DATABASE_URL` and blob root, proven distinct via denylist + marker ([Data-plane isolation](#data-plane-isolation-proof-fir8r2-04--normative)). |
| **Bench tenant** | Tenant row **inside the bench deployment DB** that owns copied media + 512D embeddings for a run. Not a production tenant id reuse without enrollment mapping. |
| **Enrolled source tenant** | The **single** production tenant UUID bound via env on the bench host (`RECOGNITION_BENCH_SOURCE_TENANT_ID`). Server-derived; clients cannot free-form retarget. |
| **Source media catalog** | Bench-side rows mapping `media_id → media_url` (+ optional metadata) for the enrolled source tenant. Populated by **operator upload/enrollment**, not by free-form per-run client URLs. POST run supplies **media_ids only**; ingest resolves URLs server-side from this catalog. |
| **Prod baseline artifact** | Operator-uploaded JSON of label-free aggregates from production for the selected media set (detection counts, faces/image, embed success, per-item sha256 join keys when available). **Not** fetched with a production admin token on the bench host. |
| **Bench leg** | Full detect→embed→cluster on the bench deployment under insightface for copied media. |
| **Label-free metrics** | Counts/distributions that need no identity ground truth. Label-dependent frames (purity, identification P/R, unknown-rejection vs roster labels) are **JSON `null`** on live-tenant bench. |
| **Join key** | **Media content sha256** stamped at bench ingest; sealed metrics aggregate per-item by this key when comparing legs. |
| **`admin_auth_ok_context`** | **Single definition (FIR8R2-06):** server boolean ≔ (1) the `/admin` mount is active for this process (`RECOGNITION_ADMIN_ENABLED`), **and** (2) the current request passed `require_admin` / HTML Basic console auth. On a bench-enabled process, readiness for **bench mutations** additionally requires the boot-coupled license gate to have passed at process start; that is a separate predicate (`bench_license_gate_ok`), not folded into inventing auth from the client. SPA/HTML never invents either flag. |

## Problem Statement

Golden-150 answers controlled corpus quality ([DIAG-08]). Operators still need: *on this tenant’s real media, how large is the buffalo_l vs face_pipeline gap right now?*

v1 proposed dual-profile APIs and a same-process Option B. That is **structurally impossible**: `PGVECTOR_DIM` is one process-wide dim root; one deployment cannot host 512D insightface and 128D face_pipeline against one store. A `dim_mismatch` preflight cannot be cleared via API without a second deployment (or destructive wipe + dim flip — rejected).

v2 locked the dedicated-bench track and boot-coupled gates, but introduced **contradictory run-path machinery** (202 `queued` **and** sync ingest on the API thread), a **partial** mutation re-check, a **prod admin token** on the bench host, unproven data-plane separation, soft truncation, and residual pins left open. **v3 resolves those defects** while keeping the v1 structural invariants v2 already fixed. **v4 keeps v3 structure** and fixes remaining **SQL/bootstrap-level** defects only (single-live constant-expression index, fail-closed marker rail, split preflight blocker sets, re-entrant supervisor + honest timeout, one-clause residual pins). **v5 keeps v4 structure** and fixes remaining **supervisor/lifecycle semantics** only (purge-before-terminal, non-blocking tick contract, runtime gate preamble + claim re-verify + marker idempotency, residual pin sharpening).

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
| Blob store | `recognition.application.storage.FilesystemObjectStore.put(job_id=..., media_id=..., data=...)` → `file://` URI under `<blob_root>/<tenant_id>/<job_id>/<media_id>.bin`. |

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
  4. Data-plane isolation checks pass ([Data-plane isolation](#data-plane-isolation-proof-fir8r2-04--normative))

  Otherwise the process **refuses to start** with a stable error class (extend `InsecureProductionConfigError` or add `BenchLicenseGateError`) and a stable machine code in the message / structured log: `bench_license_gate_failed` (or `bench_data_plane_collision` for denylist/marker failures).

  When the flag is `0`/`false` (default): process boots normally; every bench mutation route is unmounted or returns **403** `{ "error": "bench_flag_off" }` if somehow hit; no insightface bench scheduling. **Artifact purge sweeper still runs** ([Lifecycle pins](#lifecycle-pins-fir8r2-06--fir8r3-01--fir8r3-04--fir8r3-05--fir8r4-0104--normative)).

- **Insightface never tenant-facing**: no workbench control, no site-front toggle, no tenant API-key route, no WP mutation path that can enable insightface.
- UI copy must include: **“non-commercial weights — internal benchmarking only”**. Status indicators pair color with icon ([sr-004]). API responses that describe bench availability carry `license_notice` with that sense.

### I2. Reuse the selection seam ([SERVE-01], [RLSE-07])

- All runtime construction continues through `build_embedding_runtime(...)`.
- Profile vocabulary stays `_FACE_PIPELINE_PROFILES` / `Literal["insightface", "face_pipeline"]` — **no third profile name** for “bench”.
- **No fork of `scan_worker` glue** — bench runs use the same worker entrypoint and job tables in the **bench** process/DB, tenant-scoped to the bench tenant; supervisor is a **named tick** inside that process, not a second binary.
- No parallel detector factory, no second protocol.

### I3. Embedding-space integrity ([EMB-01], FIR23-01)

- insightface = **512D**; face_pipeline / SFace = **128D**.
- `PGVECTOR_DIM` remains the sole dimension root.
- **One dim per deployment.** Production keeps its dim; bench deployment is fixed at `PGVECTOR_DIM=512` with env profile `insightface`. Silent 512D/128D mix in one store is designed out by **deployment isolation**, not by dual-profile API preflight.
- Insightface embeddings **never** land in a publishable production index.

### I4. Operator principal (FIR8PR-09 / FIR8PA-01)

- **Human principal for all bench mutations** = recognition **operator** on the tailnet-bound `/admin` surface (existing admin token / Basic console family + `AdminAuditEvent` audit rows).
- **WP `manage_options` is NOT the bench principal.** Customer site admins are internet-facing and must not hold cross-tenant recognition-admin credentials.
- **WP MVP stance (pinned): nothing.** No `acx/v1/bench/*` proxy, no SPA bench panel, no WP-held recognition-admin token for bench. Operators use the recognition `/admin` HTML console on the bench. A future read-only site-scoped results panel is explicitly **out of this task**.

### I5. Boundary honesty ([rg-015])

- Adapters/controllers must not invent envelope metadata. Every field comes from request, upstream payload, or a **named** documented constant. Nullable metrics stay `null` — never invent `0.0` purity ([EVAL-01]).

### I6. Greenfield schema policy

- No Alembic add-on migrations. Schema edits go in `001_identity_schema.py` only.
- Bench run persistence: table `recognition_bench_runs` (and catalog/baseline/marker tables as needed) in the **bench deployment’s** schema. Production gains **no** new baseline-export API in this task (option b).

### I7. Independent bench verdicts ([OBS-09], [EVAL-01], [TEST-08])

- Metrics produced by a **scorer outside either model path** (bench report builder), never by counters the path under test can self-tune.
- Metric *names* align with Golden-150 / eval-harness where sensible; every payload is tagged `source=live_tenant_bench` so it is never confused with Golden-150 publishable scores ([DIAG-08]).
- **Label honesty (FIR8PR-04)**: live tenant media has **no ground truth**. Scope metrics to **label-free frames only**; label-dependent frames are **always `null`** for this task. **No operator-labeling loop in MVP.** No invented purity.

### I8. Production CPU isolation (FIR8PA-03)

- Bench runs execute **only in the bench deployment**. Production `scan_worker` is **not** scheduled for insightface re-scan of live media for this feature. Production is not polled by the bench host for baseline or media bytes via admin credentials.

### I9. Fully async run path (FIR8R2-01) — non-negotiable

- **API thread work on POST is only:** auth → `RUN_CREATE_SET` preflight → sample validation → single-flight insert of `recognition_bench_runs` → 202.
- **No media GET, no blob put, no scan-job create, no scoring** on the API request thread.
- A **named supervisor loop** in the **bench deployment’s `scan_worker` process** owns the rest, ticking on the worker’s existing poll cadence.

---

## Design decision: embedding-space isolation (LOCKED)

### Chosen track — Dedicated bench deployment (only implementable path)

**Mechanism**

| Concern | Bench deployment | Production deployment |
| --- | --- | --- |
| Process | Own API + own `scan_worker` | Untouched for bench compute |
| DB | Own Postgres (or isolated DB name/schema); marker row `internal_bench` | Live tenant store; must not appear on bench denylist endpoints |
| Blob store | Own `blob_root` / endpoint | Own production blob endpoint |
| `PGVECTOR_DIM` | **512** | 128 post-FIR-6 (or current prod value) |
| `RECOGNITION_FACE_PIPELINE_PROFILE` | **`insightface`** | `face_pipeline` (target) / transitional per FIR-4 |
| `RECOGNITION_BENCH_PROFILE_ENABLED` | **1** | **0** (must stay off) |
| `RECOGNITION_DEPLOYMENT_CLASS` | **`internal_bench`** | `production` / unset / non-bench |
| Comparison | Full pipeline leg on copied media | **Operator-uploaded** label-free baseline artifact from existing prod output |

Operator workflow:

1. On **production** (existing diagnostics / SQL / operator tooling **outside this task’s new prod API**): select up to N media for enrolled tenant; export **label-free baseline** JSON (and media catalog rows: `media_id` + HTTPS URL).
2. On **bench** `/admin` bench panel: upload source media catalog (if not already enrolled) + baseline artifact; start run with **`media_ids` only**; server resolves URLs from catalog; inserts run row; returns 202.
3. Bench `scan_worker` supervisor: ingest → scan → cluster → score → seal → purge (delete-by-default).
4. Operator views side-by-side sealed metrics (prod baseline + bench leg), joined by media sha256 where present.

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
| R-sync-ingest | Sync bounded ingest on POST before 202 | Contradicts 202 `queued`; blocks API; rejected by FIR8R2-01. |
| R-prod-admin-token | Bench holds production admin token for baseline pull | Credential blast radius on bench host; rejected by FIR8R2-03 (option a not chosen). |
| R-client-media-url | Client supplies `media_url` per run item | SSRF / free-form host risk; forbidden — server catalog only (FIR8R2-03). |

**MCP decision id (record at S1 start):** `fir8_isolation_mode_dedicated_bench_deployment` (locked; not a menu).

**MCP decision id (record at S1 start):** `fir8_baseline_delivery_operator_upload` (option b locked).

**MCP decision id (record at S1 start):** `fir8_run_path_fully_async_supervisor` (async-only locked).

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
- **No production admin token or baseline HTTP client on the bench host.**
- **No client-supplied `media_url` on run create.**
- **No sync ingest / scan / score work on the API request thread.**
- **No silent sample truncation** (`min(...)` accept paths).
- **No escalation-ladder implementation** — that work is **FIR-9** after renumber.
- **No production `GET /admin/diagnostics/label-free-media-stats` in this task** — option (b) replaces it with bench-side upload (FIR8R2-03/05).

---

## Current State Analysis

- Profile is **env-resolved only** at settings construction; no admin REST mutates it today — **and this plan does not add process-wide profile mutation**.
- Production dark default remains **`insightface`** (FIR-4) until FIR-6; document transitional state honestly in I1.
- Recognition operator admin: FastAPI `/admin` + hand-written HTML console (`admin_console.py`), env-gated, `AdminAuditEvent` on mutations, `validate_admin_config` at boot.
- Job path: `IdentityScanJob` / items + clustering jobs + `scan_worker` SKIP LOCKED claim — **reuse as bench execution vehicle** (no new job engine); **add named bench supervisor tick** in the same worker process.
- Dim root defaults to **512** until FIR-6; face_pipeline dark exercise needs `PGVECTOR_DIM=128` + empty index — **bench host stays 512**.
- Eval metrics under `scripts/eval_harness/` — **not importable as a runtime dependency in the image**; formula parity via in-tree duplicate + fixture test (FIR8R2-07).
- Blob path: `FilesystemObjectStore.put` already used by multipart scan intake.

---

## Target Outcome

1. Bench host boots only when boot-coupled license gate **and** data-plane isolation checks pass; otherwise refuse start with stable codes.
2. Operator on bench `/admin` can start a **bounded, fully async** live-tenant bench run (202 + supervisor); production baseline is an **uploaded** label-free artifact; bench leg is insightface full pipeline via existing scan_worker machinery.
3. Production tenant identity tables never receive insightface vectors; bench artifacts delete-by-default (**purge before `completed`** on happy path; sweeper for failed/cancelled + TTL); purge runs even if flag is off.
4. All construction still goes through `build_embedding_runtime`; no third profile name; no scan_worker fork (hooks only).
5. Metrics are label-free or null; join key = media sha256; both legs stamp profile/model/dim/code SHA; `source=live_tenant_bench`; `license_notice` always present on bench API payloads.
6. Scope + epic ID collision fixed (FIR-8 = this plan; FIR-9 = escalation ladder) in S1 baseline.
7. No production admin credentials on the bench host; client cannot supply media URLs.

---

## Boot-coupled license gate (FIR8PR-02) — normative

Implement as `validate_bench_license_gate(settings, security_settings)` called from the same startup path as `validate_admin_config` (API process **and** worker process entrypoints that construct recognition settings).

```text
if not RECOGNITION_BENCH_PROFILE_ENABLED:
    # still run artifact purge sweeper (FIR8R2-06)
    return  # no license gate

require:
  RECOGNITION_ADMIN_ENABLED == true
  RECOGNITION_ADMIN_TAILNET_BOUND == "1"
  RECOGNITION_DEPLOYMENT_CLASS == "internal_bench"   # exact
  existing validate_admin_config token length rules (admin is enabled)
  data-plane isolation checks (denylist + deployment marker) pass

else → raise BenchLicenseGateError / InsecureProductionConfigError
       stable code: bench_license_gate_failed | bench_data_plane_collision
```

**Defense in depth (FIR8R2-02 / FIR8R3-03):** every bench mutation dependency re-evaluates the **correct named preflight set** via the **same shared function** as GET status — never a hand-rolled subset. Enrollment + baseline-upload use `BOOT_AUTH_SET`; run create uses `RUN_CREATE_SET`. See [Full preflight mutation gate](#full-preflight-mutation-gate-fir8r2-02--normative).

---

## Data-plane isolation proof (FIR8R2-04 / FIR8R3-02) — normative

Bench deployment must prove it is not accidentally pointed at production storage.

### Env denylist

| Env | Meaning |
| --- | --- |
| `RECOGNITION_PROD_ENDPOINT_DENYLIST` | **Required** when bench flag is on. Comma-separated exact endpoint strings (normalized) that the bench process must **not** use. Deploy config sets this to **every** production external endpoint the recognition process can be configured to touch: production `DATABASE_URL` values, production blob-store endpoints / roots, **and** any production cache/queue DSNs (Redis, broker URLs, etc.) that appear in recognition settings. Empty/unset with bench flag on → boot fail `bench_data_plane_collision` / `prod_denylist_unconfigured`. |

**Boot check (API + worker) — every configured external endpoint:**

1. Resolve this process’s **complete** set of configured external endpoints: effective `DATABASE_URL` (or equivalent DSN), blob-store endpoint/root (`blob_root` absolute path or configured object-store endpoint), **and** any configured cache/queue/broker DSN present in settings (skip only endpoints that are unset/disabled).
2. Normalize each (strip credentials for comparison if needed; compare host+dbname / absolute path / normalized DSN).
3. If **any** process endpoint equals **any** denylist entry → **refuse start** with `bench_data_plane_collision`.
4. Denylist must be non-empty when bench flag is on (else `prod_denylist_unconfigured`).

When bench flag is off, denylist is optional (no collision check required for ordinary production boots).

**Attestation residual:** denylist membership and `RECOGNITION_DEPLOYMENT_CLASS=internal_bench` are **operator self-attestation** (env-configured), not infrastructure-enforced topology proofs — same residual class as `RECOGNITION_ADMIN_TAILNET_BOUND`. See [Residual risks](#residual-risks-fir8r2-07--fir8r3-02--fir8r4-04d--pinned-now).

### First-boot deployment_class marker (fail-CLOSED — FIR8R3-02 / FIR8R4-03c / FIR8R4-04a)

Table `recognition_deployment_markers` (in `001_identity_schema.py`):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | smallint PK fixed `1` | singleton row |
| `deployment_class` | text | e.g. `internal_bench` or `production` |
| `set_at` | timestamptz | first write |

**Production-shaped data (FIR8R4-04a) — normative definition:**

A DB is **production-shaped** when **any** of the following core identity-adjacent tables from `001_identity_schema.py` has `COUNT(*) > 0` (no `persons` table exists in this schema; person-like entities are `identity_clusters` + `identity_members`):

| Table | Role |
| --- | --- |
| `tenants` | tenant root |
| `media_identities` | embedding/identity media rows |
| `identity_clusters` | cluster/person-like entities |
| `identity_members` | cluster membership edges |

Empty means **all four** counts are 0. (Do not expand this set to every `TENANT_TABLES` job/audit table — only these core identity-adjacent roots.)

**Rules (bench-enabled boot):**

| Marker row | Production-shaped data present? | Action |
| --- | --- | --- |
| exists, `deployment_class=production` | (any) | **Refuse start** `bench_data_plane_collision` / `production_marker_present` |
| exists, `deployment_class=internal_bench` | (any) | OK |
| **absent** | **Yes** — any core identity-adjacent table nonzero (table above) | **Refuse start** `bench_data_plane_collision` / `unmarked_db_has_production_shaped_data` — **do not stamp** |
| **absent** | **No** — all four counts = 0 | First-stamp singleton `deployment_class=internal_bench` (only safe first stamp) |

**First-stamp idempotency (FIR8R4-03c) — normative:**

```text
-- concurrent API + worker boots must converge
INSERT INTO recognition_deployment_markers (id, deployment_class, set_at)
  VALUES (1, 'internal_bench', now())
  ON CONFLICT (id) DO NOTHING;
-- MANDATORY read-back:
SELECT deployment_class FROM recognition_deployment_markers WHERE id = 1;
-- if missing or deployment_class ≠ 'internal_bench' → refuse boot
--   (bench_data_plane_collision / marker_stamp_failed | production_marker_present)
```

Two concurrent stampers: both may attempt insert; at most one row exists; both read-backs must observe the same `internal_bench` value or refuse.

**Fail-closed invariant:** bench boot may stamp `internal_bench` **only** into a DB that is empty of production-shaped data **and** has no marker. Unmarked DBs that already hold tenant/identity rows are treated as hostile/ambiguous — refuse, never auto-promote.

- Production deployments **must not** set `internal_bench` markers; they may leave the table empty or set `production` if they opt in later. Bench refuse-on-production-marker **and** refuse-on-unmarked-with-data are the hard safety rails.

### Acceptance tests (S1)

1. Bench flag on + `DATABASE_URL` ∈ denylist → process **fails boot** with `bench_data_plane_collision`.
2. Bench flag on + blob root/endpoint ∈ denylist → same.
3. Bench flag on + cache/queue DSN ∈ denylist → same.
4. Bench flag on + marker row `deployment_class=production` → fails boot.
5. Bench flag on + empty denylist → fails boot `prod_denylist_unconfigured`.
6. Bench flag on + **no marker** + any core identity-adjacent table (`tenants` / `media_identities` / `identity_clusters` / `identity_members`) count > 0 → fails boot `unmarked_db_has_production_shaped_data` (does **not** stamp).
7. Bench flag on + clean denylist + no marker + empty production-shaped tables → boots; marker stamped `internal_bench`.
8. Bench flag on + existing `internal_bench` marker → boots (data may exist from prior bench runs).
9. **[TEST-15] concurrent stampers (FIR8R4-03c):** two concurrent first-stamp attempts on an empty unmarked DB → both converge on one `internal_bench` row; neither stamps over a production marker; failed read-back refuses boot.

---

## Full preflight mutation gate (FIR8R2-02 / FIR8R3-03) — normative

**One shared pure function** evaluates a **named blocker set** selected by the caller (not a single undifferentiated “full” bag that deadlocks bootstrap).

```text
# recognition/application/bench/preflight.py
evaluate_bench_preflight(ctx: BenchPreflightContext, *, blocker_set: BenchBlockerSet) -> list[str]
# BenchBlockerSet = BOOT_AUTH_SET | RUN_CREATE_SET
# GET /admin/bench/status reports both: boot_auth_blockers + run_create_blockers (or union + partition)
```

### Named blocker sets (FIR8R3-03) — split to break bootstrap deadlock

Enrollment (`POST /admin/bench/source-catalog`) and baseline upload (`POST /admin/bench/baselines`) must succeed while the catalog is still empty and before dim/profile readiness is required for a run. Run create remains strict.

#### `BOOT_AUTH_SET` — enrollment + baseline-upload + boot-class gates

| Code | When |
| --- | --- |
| `bench_flag_off` | Flag false |
| `bench_license_gate_failed` | Flag true but admin/tailnet/deployment_class incomplete (should not serve if boot-coupled; still on mutation path) |
| `deployment_class_not_bench` | `RECOGNITION_DEPLOYMENT_CLASS != internal_bench` |
| `admin_not_enabled` | Admin mount off |
| `source_tenant_unconfigured` | `RECOGNITION_BENCH_SOURCE_TENANT_ID` missing/invalid |
| `bench_tenant_unconfigured` | `RECOGNITION_BENCH_TENANT_ID` missing |
| `media_allowlist_unconfigured` | Allowlist empty (catalog write needs it; baseline upload may share the check or skip if not URL-bound — if allowlist unused for baseline body, still require configured for host consistency) |
| `data_plane_unverified` | Denylist/marker state not verified for this process (should not happen post-boot) |

**Applied to:** `POST /admin/bench/source-catalog`, `POST /admin/bench/baselines` (after auth). **Not** blocked by `source_catalog_empty`, `baseline_missing`, dim/profile, or concurrent-run codes.

#### `RUN_CREATE_SET` — run creation only

`RUN_CREATE_SET` = **`BOOT_AUTH_SET` ∪**:

| Code | When |
| --- | --- |
| `source_catalog_empty` | No enrolled catalog rows for source tenant |
| `baseline_missing` | No usable baseline artifact for the run **or** uploaded baseline’s `media_id` set is **not a superset** of the run’s accepted `media_ids` (FIR8R4-04b; partial intersection = missing) |
| `insightface_runtime_unavailable` | `build_embedding_runtime` / readiness cannot load insightface on this host |
| `pgvector_dim_not_512` | Bench host `PGVECTOR_DIM != 512` |
| `profile_not_insightface` | Env profile ≠ `insightface` on bench host |
| `bench_run_in_progress` | Concurrent live run (POST only; single-live unique index also enforces → **409**) |

**Applied to:** `POST /admin/bench/runs` (after auth, before insert). Cancel may use `BOOT_AUTH_SET` (or `RUN_CREATE_SET` minus `bench_run_in_progress` / catalog / baseline as appropriate for cancel-only).

**Removed from S1 matrix (v1):** `foreign_embedding_model_rows`, `confirm_wipe`, dual-profile construct checks, process-override effective profile flips.

### Mutation-time re-check

- POST `/admin/bench/runs` **must call `evaluate_bench_preflight(..., blocker_set=RUN_CREATE_SET)`** after auth and **before** insert. Any non-empty list (except treating `bench_run_in_progress` as **409**) → **403** with the blocker codes (or 400 for request-shape errors).
- POST catalog / baselines **must call `evaluate_bench_preflight(..., blocker_set=BOOT_AUTH_SET)`** — never `RUN_CREATE_SET` (would deadlock empty-catalog enrollment).
- Do **not** implement a hand-rolled “lite” subset outside these named sets. Boot gate is necessary but **not sufficient** against post-boot drift.

### Discriminating tests [TEST-15]

**`test_mutation_catches_post_boot_profile_drift`:**

1. Boot (or construct app) with full-clear `RUN_CREATE_SET` (profile `insightface`, dim 512, catalog + baseline present, …).
2. Mutate the live settings/preflight context so `env_profile` becomes `face_pipeline` (simulate drift **after** boot validation was satisfied).
3. POST `/admin/bench/runs` with valid media_ids → **403** and blockers include `profile_not_insightface`.
4. Red-proof: if mutation path skips calling `evaluate_bench_preflight` and only checks `bench_enabled`, this test fails.

**`test_enrollment_succeeds_while_source_catalog_empty` (FIR8R3-03):**

1. Bench host with `BOOT_AUTH_SET` clear and **zero** catalog rows (`source_catalog_empty` would fire under `RUN_CREATE_SET`).
2. POST `/admin/bench/source-catalog` with a valid allowlisted row → **2xx**; catalog non-empty afterward.
3. Red-proof: if enrollment mistakenly uses `RUN_CREATE_SET`, `source_catalog_empty` blocks the first enroll forever.

**`test_single_live_index_rejects_queued_while_running` (FIR8R3-01):**

1. Insert a `recognition_bench_runs` row with `status=running`.
2. Insert (or POST) a second row with `status=queued` → **unique violation** / API **409** `bench_run_in_progress`.
3. Red-proof: a partial unique index on `(status)` alone allows one `queued` **and** one `running` concurrently — this test must fail that broken index.

Analogous cases may cover dim drift and source-tenant unset; profile drift + single-live + enrollment-vs-empty-catalog are the required discriminating cases.

---

## Media intake contract (FIR8PR-03 / FIR8R2-03) — normative

### Source binding

| Field | Source | Client may set? |
| --- | --- | --- |
| `source_tenant_id` | Env `RECOGNITION_BENCH_SOURCE_TENANT_ID` (UUID) on bench host | **No** — server-derived; if body includes a different value → **400** `source_tenant_mismatch` |
| Bench-side tenant for storage | Env `RECOGNITION_BENCH_TENANT_ID` (UUID of tenant row in **bench** DB) | **No** |
| Media host allowlist | Env `RECOGNITION_BENCH_MEDIA_HOST_ALLOWLIST` (comma-separated hostnames) | **No** |
| Media URLs | **Source media catalog** rows on bench (operator-enrolled) | **No** — `media_url` in run body → **400** `media_url_not_accepted` |
| Media ids | Client POST `media_ids: int[]` | **Yes** (only selection surface) |

### Source media catalog enrollment

- Operator uploads catalog via `POST /admin/bench/source-catalog` (`require_admin_header` only — FIR8R3-05a): list of `{ "media_id": int, "media_url": "https://..." }` for the enrolled source tenant.
- Preflight: **`BOOT_AUTH_SET` only** (FIR8R3-03) — must succeed when catalog is empty.
- Server validates each URL: scheme `https`, host ∈ allowlist, no redirects outside allowlist (max 2 redirects, re-check host) **at catalog write** and again at ingest.
- **DNS pin (FIR8R3-05d / FIR8R4-04d):** at catalog write, resolve the object host to its **full set of addresses** and **persist the pinned SET** (with the host) on the catalog row — not a single A-record pick. At ingest, the fetch **must connect to one of the pinned addresses**; re-resolve is used only to validate connectivity against that set (closes DNS-rebinding / multi-A drift). Redirect targets must also re-verify allowlist host **and** re-resolve into a pin set before follow.
  - **Public-unicast pin rule (FIR8R4-04d):** every address in the pinned set **must** be public unicast. **Reject** link-local, RFC1918 private, loopback, and other non-public ranges at enroll (and re-check at ingest). **Exception:** if `RECOGNITION_BENCH_ALLOW_PRIVATE_SOURCE=1`, private/LAN addresses are permitted for a LAN-internal media store — **documented residual** (operator-acked; not a topology proof). Default is **off** (public unicast only).
- Rows stored server-side (table `recognition_bench_source_media` or equivalent in `001_identity_schema.py`) including `pinned_host_ips` (JSON/array of addresses; supersedes single `pinned_host_ip` wording).
- Run create resolves `media_ids` → URLs **only** from this catalog for `source_tenant_id`. Unknown id → 400 `media_ids_unknown`.

### Named byte-transfer mechanism (async — supervisor only)

**Bench-side HTTPS GET of media bytes** (“pull into bench”), executed by the **supervisor**, never the API thread:

1. Supervisor loads accepted `media_ids` for the run; resolves URLs from source catalog.
2. For each item (one item per tick while in ingest — [non-blocking tick](#non-blocking-tick-contract-fir8r4-02--normative)): re-verify connect target ∈ **pinned address set** (FIR8R4-04d); GET bytes with bounded size (`RECOGNITION_BENCH_MAX_BYTES_PER_MEDIA`, default **15 MiB**) and wall timeout per object (`RECOGNITION_BENCH_PER_OBJECT_FETCH_TIMEOUT_SEC`, default **30**). Target not in pin set → item fail (not silent redirect to a new A-record). **Intra-phase wall-clock re-check** before each item ([timeout](#timeout-arithmetic-fir8r2-01--fir8r3-04--fir8r4-02--normative)).
3. Bytes stored under the **bench tenant** via:

   **Module + function (FIR8R2-07):** `recognition.application.storage.FilesystemObjectStore.put(job_id=..., media_id=..., data=...)`  
   (construct store with `root=settings.blob_root`, `tenant_id=str(bench_tenant_id)`).

4. Stamp **content sha256** of raw bytes on the run’s per-item ingest record (join key).
5. **Persist per-item ingest outcome (FIR8R4-04c)** alongside `item_cursor` on the run (child table `recognition_bench_run_items` preferred, or durable JSON on the run row): each item records `media_id`, outcome (`ok`/`failed`), optional `error_code`, `content_sha256` when ok. **`failed_ingest_count` / `successful_ingest_count` are derived from durable per-item outcomes** so crash/resume mid-ingest never loses the hard-fail tally.
6. Create `IdentityScanJob` + `IdentityScanJobItem` rows for the **bench tenant** only after ingest phase completes successfully (hard-fail not triggered). Fields the worker needs on each item (FIR8R2-07):

   | Field | Source after ingest |
   | --- | --- |
   | `media_id` | Operator-selected id (preserved) |
   | `media_url` | Bench-local resolvable URL / `file://` blob URI returned by `FilesystemObjectStore.put` (scan path already reads blob URIs) |
   | `tenant_id` | `RECOGNITION_BENCH_TENANT_ID` |
   | `job_id` | New scan job id |
   | `status` | `pending` |

7. Each successful ingest writes an **audit row**: `AdminAuditEvent.BENCH_MEDIA_INGEST` with media_id, byte length, sha256, source_tenant_id, run_id.
8. Failed fetch → item marked failed in durable outcomes; does not invent success counts ([rg-015]).

### Ingest hard-fail threshold (FIR8R2-01 / FIR8R4-04c)

| Constant | Value | Unit |
| --- | --- | --- |
| `INGEST_HARD_FAIL_MAX_FAILED` | **3** | count of media items whose fetch/persist failed |
| Also hard-fail if | `successful_ingest_count == 0` | count |

Semantics: after the ingest phase attempts all accepted items, if durable `failed_ingest_count >= 3` **or** `successful_ingest_count == 0`, supervisor sets run `failed` with `error_code=ingest_hard_fail`, does **not** enqueue scan (or cancels empty job). Failed runs release live status; **artifact purge for failed/cancelled is via the flag-independent sweeper** ([purge-before-terminal](#run-lifecycle-fir8pr-05--fir8r2-01--fir8r2-06--fir8r3-04--fir8r4-01--fir8r4-02--fir8r4-03)), which claims terminal rows with pending artifacts.

**Test:** 10 media_ids, mock 3 fetch failures → run `failed` / `ingest_hard_fail`; 10 media_ids, 2 failures → continue to scan with 8 items; 5 media_ids, all fail → `ingest_hard_fail` via zero-success rule; crash after 2 failures then resume → durable `failed_ingest_count` still 2 (not reset).

### Baseline delivery — option (b) locked (FIR8R2-03 / FIR8R2-05 / FIR8R3-05b)

- **No** `RECOGNITION_BENCH_SOURCE_BASE_URL` / `RECOGNITION_BENCH_SOURCE_ADMIN_TOKEN` on the bench host.
- Operator uploads baseline via:

  `POST /admin/bench/baselines` (or `.../baseline-artifacts`) — `require_admin_header` only; preflight **`BOOT_AUTH_SET`**.

#### Normative baseline upload JSON schema (FIR8R3-05b)

```json
{
  "schema_version": 1,
  "source_tenant_id": "uuid",
  "effective_profile": "face_pipeline|insightface|unknown",
  "embedding_model_id": "string|null",
  "pgvector_dimension": 128,
  "code_sha": "40-char hex|null",
  "items": [
    {
      "media_id": 101,
      "content_sha256": "64-char hex",
      "detection_count": 4,
      "embed_success": true
    }
  ]
}
```

| Rule | Contract |
| --- | --- |
| Required root fields | `schema_version` (int, =1 for MVP), `items` (non-empty array) |
| Per-item required | `media_id` (int), `content_sha256` (64-char lowercase hex of production export bytes or documented export hash) |
| Per-item optional label-free | `detection_count`, `embed_success`, other label-free scalars already in metrics contract |
| Max body size | **5 MiB** raw request body — over → **413** / **422** `baseline_too_large` |
| Unknown fields | **Reject** entire body → **422** `baseline_unknown_field` (no silent drop) |
| sha256 format | Non-hex / wrong length → **422** `baseline_sha_invalid` |
| sha mismatch | If upload includes a separately transported byte payload or dual hash fields and they disagree → **422** `baseline_sha_mismatch` (reject; never store mismatched join keys) |
| Provenance optional | `effective_profile`, `embedding_model_id`, `pgvector_dimension`, `code_sha`, `source_tenant_id` — when present must type-check; `source_tenant_id` if present must equal enrolled env tenant or → **400** `source_tenant_mismatch` |

- Stored on bench; referenced by `baseline_artifact_id` on run create **or** auto-matched by media_id set.
- **Run create** (`RUN_CREATE_SET` / FIR8R4-04b): `baseline_missing` blocks POST unless an uploaded baseline’s **`media_id` set is a SUPERSET of the run’s accepted `media_ids`**. Partial intersection (baseline covers some but not all accepted ids) **is missing** — blocker fires. Sealed metrics still use honest nulls for any **partial** per-field gaps inside a covering artifact (`prod_baseline.status = "ok"` with null frames as needed).
- **Slice ownership:** **S3** owns catalog + baseline upload endpoints + retention of artifacts; **S4** owns scorer join/seal that consumes them.

### Retention / deletion (delete-by-default)

| Artifact | Policy |
| --- | --- |
| Copied media bytes on bench | **Delete-by-default:** happy path purges in the first-class `purge` phase **before** `completed` (FIR8R4-01); `failed`/`cancelled` purge via flag-independent sweeper on terminal rows with pending artifacts |
| Derived `media_identities` / embeddings on bench tenant for that run’s media | **Delete with media** (same cleanup transaction/job) |
| `recognition_bench_runs` row + metrics JSON | **Retain** for operator history; TTL purge after **30 days** (configurable `RECOGNITION_BENCH_RUN_RETENTION_DAYS`, default 30) |
| Source catalog + baseline artifacts | Retain until operator delete or same 30d TTL (configurable) |
| `AdminAuditEvent` bench rows | **Retain 90 days** (`RECOGNITION_BENCH_AUDIT_RETENTION_DAYS`, default **90**) then purge (FIR8R2-06 / FIR8R3-05c) |
| Safety net | **Purge sweeper** runs at API/worker **startup and each worker tick** regardless of bench flag (FIR8R2-06 / FIR8R4-01): **claims terminal** (`failed`/`cancelled`/`completed` if ever left pending) rows with `artifacts_purged_at IS NULL`, deletes media + embeddings, stamps purge time; also fails non-terminal runs older than wall-clock timeout; purges expired audit rows **only** for bench audit enum values (below) |

**Audit-row purge filter (FIR8R3-05c) — ONLY these `AdminAuditEvent` values:**

- `BENCH_RUN_CREATE` (`bench.run.create`)
- `BENCH_RUN_CANCEL` (`bench.run.cancel`)
- `BENCH_MEDIA_INGEST` (`bench.media.ingest`)
- `BENCH_CATALOG_UPSERT` (`bench.catalog.upsert`)
- `BENCH_BASELINE_UPLOAD` (`bench.baseline.upload`)

Sweeper **must not** delete `tenant.create` / `api_key.*` or any non-bench audit rows.

Optional override `retain_artifacts=true` on POST is **rejected in MVP** (400 `retain_not_supported`) — delete-by-default only.

---

## Bounded work (FIR8PA-03 / ops R-2) — normative

| Bound | Value | Justification |
| --- | --- | --- |
| **Hard max sample size** | **`MAX_BENCH_SAMPLE = 20`** images | Buffalo_l CPU path historically ~**17 s/image** load+infer class. Server **rejects** `len(media_ids) > 20` with **400** `sample_limit_exceeded`. |
| **UI / default N** | **`DEFAULT_BENCH_SAMPLE_N = 10`** | Half of max; default pre-fill only when operator uses “suggest last N” helper — never auto-starts. |
| **Empty selection** | **Empty means NOTHING** | Zero media_ids → **400** `empty_selection`. Never interpret empty as “all media”. |
| **Truncation rule (FIR8R2-05)** | **Reject over-cap only** | **One rule:** if `len(media_ids) > MAX_BENCH_SAMPLE` → 400 `sample_limit_exceeded`. **No** `min(len, sample_limit, MAX)` silent truncation. Optional `sample_limit` if present must be ≥ `len(media_ids)` and ≤ 20 or → 400 `sample_limit_inconsistent`; it does **not** slice the list. |
| **Single concurrent run** | Global on bench deployment | **Only** mechanism: constant-expression unique partial index (below). POST conflict → **409** `bench_run_in_progress`. At most **one** live row total (`queued` **or** `running`), never one of each. |
| **Wall-clock timeout (claimed)** | **`RECOGNITION_BENCH_RUN_TIMEOUT_SEC = 1650`** | Measured **from claim** (`started_at`) while `status=running`. Exceed → mark `failed` with `error_code=run_timeout`; cancel outstanding scan items. Enforced **every supervisor tick** with **intra-phase re-check per item** (FIR8R3-04 / FIR8R4-02). |
| **Queued-age timeout** | **`RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC`** (default **300**) | Separate clock for `status=queued` age from `created_at`. Exceed → `failed` / `error_code=queued_timeout` (never starts claim). Not folded into the claimed-run formula. |
| **CPU placement** | Bench deployment only | Production scan_worker never receives insightface bench jobs. |

### Timeout arithmetic (FIR8R2-01 / FIR8R3-04 / FIR8R4-02) — normative

Named caps:

| Cap | Symbol | Default |
| --- | --- | --- |
| Max sample | `MAX_BENCH_SAMPLE` | 20 |
| Per-object fetch timeout | `RECOGNITION_BENCH_PER_OBJECT_FETCH_TIMEOUT_SEC` | 30 s |
| Per-image scan budget | `PER_IMAGE_SCAN_BUDGET_SEC` | **17** s (buffalo load+infer class; planning constant, not a separate env unless ops later wants it) |
| Clustering budget | `CLUSTER_BUDGET_SEC` | 120 s |
| Seal + purge margin | `SEAL_MARGIN_SEC` | 60 s |
| Model cold-start | `COLD_START_BUDGET_SEC` | **90** s (buffalo `FaceAnalysis` prepare on 4-core ARM; once per process/run claim) |
| Blob put + sha256 budget | `BLOB_IO_BUDGET_SEC` | **100** s (planning constant for put+hash across max sample after fetch) |
| One worker poll interval | `WORKER_POLL_INTERVAL_SEC` | **1** s (`scan_worker` default `poll_interval_seconds`) |
| Supervisor phase count | **`N_PHASES`** | **7** — ordered work phases after claim: `ingest`, `enqueue_scan`, `await_scan`, `cluster`, `score`, `seal`, `purge` (one bounded step / tick minimum) |
| Queued-age timeout | `RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC` | **300** s (separate from claimed-run formula) |

```text
# Claimed-run timeout only (from started_at). Does NOT include queued wait.
formula_floor =
  MAX_BENCH_SAMPLE × (PER_OBJECT_FETCH_TIMEOUT_SEC + PER_IMAGE_SCAN_BUDGET_SEC)
    + CLUSTER_BUDGET_SEC
    + SEAL_MARGIN_SEC
    + COLD_START_BUDGET_SEC
    + BLOB_IO_BUDGET_SEC
    + N_PHASES × WORKER_POLL_INTERVAL_SEC

  = 20 × (30 + 17) + 120 + 60 + 90 + 100 + 7 × 1
  = 20 × 47 + 377
  = 940 + 377
  = 1317 s

≥25% slack over floor:
  1317 × 1.25 = 1646.25 s

→ set RECOGNITION_BENCH_RUN_TIMEOUT_SEC = 1650  # ~25.3% slack over 1317

# Queued age (separate env; not in formula_floor):
RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC = 300  # default
```

**Clocks (FIR8R4-02):**

| Run state | Clock start | Cap env | Error code |
| --- | --- | --- | --- |
| `queued` | `created_at` | `RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC` | `queued_timeout` |
| `running` (incl. purge phase) | `started_at` (set once on claim) | `RECOGNITION_BENCH_RUN_TIMEOUT_SEC` | `run_timeout` |

**Invariant:** changing `MAX_BENCH_SAMPLE`, fetch timeout, cold-start, blob-IO, `N_PHASES`, or poll interval **requires** recomputing this inequality in the same change; unit test locks `TIMEOUT_SEC >= ceil(formula_floor * 1.25)` (or `TIMEOUT_SEC > formula_floor` with documented ≥25% slack) so a regression that lowers timeout without adjusting caps fails.

---

## Label-free metrics contract (FIR8PR-04 / FIR8R2-05)

### Included (label-free)

Per leg (`prod_baseline`, `bench_insightface`):

- `images_requested`, `images_accepted`, `images_failed_ingest` (bench leg)
- `images_with_detections`, `detection_count_total`, `faces_per_image_mean`, `faces_per_image_p50`
- `embed_success_count`, `embed_failure_count` (when distinguishable)
- Bench-only after cluster: `cluster_count`, `cluster_size_hist` (sizes only), `singleton_cluster_count`
- Deltas: arithmetic differences for shared numeric fields where both sides non-null
- **Per-item aggregate entries** keyed by **`content_sha256`** (join key), with `media_id` secondary

### Always null on live-tenant bench (no ground truth)

- `cluster_purity`, `identification_precision`, `identification_recall`, `unknown_rejection`, any Fair-SA / labeled slice score

Do **not** emit `0.0` for those keys — emit JSON `null`.

### Provenance stamps on sealed metrics (FIR8R2-05)

Sealed `metrics` JSON **must** include:

```json
{
  "source": "live_tenant_bench",
  "join_key": "content_sha256",
  "code_sha": "<40-char git SHA of bench process build/revision>",
  "prod_baseline": {
    "status": "ok|unavailable",
    "effective_profile": "face_pipeline|insightface|unknown",
    "embedding_model_id": "...|null",
    "pgvector_dimension": 128,
    "code_sha": "<from artifact or null>",
    "...": "label-free fields"
  },
  "bench_insightface": {
    "effective_profile": "insightface",
    "embedding_model_id": "insightface-buffalo_l@512d/l2/cosine",
    "pgvector_dimension": 512,
    "code_sha": "<same as root code_sha>",
    "...": "label-free fields"
  },
  "items": [
    { "media_id": 101, "content_sha256": "…", "prod": {}, "bench": {} }
  ]
}
```

Both sides’ effective profile, embedding_model_id, dim, and code SHA are stamped even when baseline is partially unavailable (use nulls + `status`).

### face_metrics placement (FIR8R2-07)

- **Decision NOW:** **parity-tested duplicate** of needed label-free helpers lives in `recognition/application/bench/score.py` (or `recognition/application/bench/face_metrics.py` imported by score).
- **Do not** rely on `scripts/eval_harness/` being importable inside the runtime image.
- **Unit test** (S4): load a frozen fixture of inputs → assert formula equality between the in-tree functions and a **vendored expected-output fixture** generated offline from `scripts/eval_harness/face_metrics.py` (or dual-call in dev-only test if scripts path exists, but CI path must not require scripts on `PYTHONPATH` for the app image). Prefer golden JSON fixture committed under `recognition/tests/fixtures/bench/`.

---

## Run lifecycle (FIR8PR-05 / FIR8R2-01 / FIR8R2-06 / FIR8R3-04 / FIR8R4-01 / FIR8R4-02 / FIR8R4-03)

### State machine

```text
queued → running (… → score → seal → purge) → completed
       → failed
       → cancelled
```

| State | Meaning |
| --- | --- |
| `queued` | Row inserted by POST; **no** ingest yet; waiting for supervisor claim; subject to **queued-age** timeout |
| `running` | Supervisor claimed; phases through **ingest → … → score → seal → purge** still hold **`uq_bench_single_live`**; **phase + item_cursor + durable ingest outcomes** persisted. **Purge is first-class while still `running`** (FIR8R4-01) |
| `completed` | **Terminal only after purge succeeds** (FIR8R4-01): metrics sealed **and** `artifacts_purged_at` set; artifacts gone |
| `failed` | Terminal error (`run_timeout`, `queued_timeout`, `ingest_hard_fail`, claim/resume config drift, worker error, stale reclaim, cancel-on-disable gate failure). Releases single-live; **purge via sweeper** (claims terminal rows with pending artifacts) |
| `cancelled` | Operator cancel **or** runtime-gate cancel-on-disable (FIR8R4-03a). Releases single-live; **purge via sweeper** |

**Happy-path phase order (normative, FIR8R4-01):**

```text
… → score → seal → purge → completed
```

- **`score`:** compute label-free metrics; join baseline; **do not** flip status yet.
- **`seal`:** persist sealed `metrics` JSON + provenance stamps on the run row; **status remains `running`**.
- **`purge`:** delete-by-default blobs + embeddings for this run; set `artifacts_purged_at`; **only then** set `status=completed`.
- While `phase=purge` (and all prior running phases), the row still matches `uq_bench_single_live` → **new run cannot start while purge is pending**.

**Failed/cancelled purge path (FIR8R4-01):** on `failed`/`cancelled`, status is terminal immediately (releases live slot). The **flag-independent boot/tick sweeper** (already normative) **claims terminal rows with `artifacts_purged_at IS NULL`**, deletes pending artifacts, stamps purge time. Supervisor happy-path purge does **not** depend on the sweeper; the sweeper is the sole cleanup path for failed/cancelled (and a safety net if a process dies mid-purge before `completed`).

### Execution vehicle — fully async (FIR8R2-01) — named

**Reuse existing `scan_worker` in the BENCH deployment** with a **named supervisor tick**:

**Name:** `bench_run_supervisor_tick` (module: `recognition/application/bench/supervisor.py`, invoked once per worker poll cycle from `scan_worker`’s existing loop — **not** a second process, **not** an API BackgroundTask for ingest/scan/score).

#### POST path (API thread only)

1. Auth (`require_admin_header` only — FIR8R3-05a; Basic rejected for JSON mutations).
2. `evaluate_bench_preflight(..., blocker_set=RUN_CREATE_SET)`; non-empty → 403/409 as mapped (`baseline_missing` = baseline media_id set not a superset of accepted ids — FIR8R4-04b).
3. Validate body: `media_ids` non-empty, ≤ 20, all known in source catalog; reject any `media_url` field; reject over-cap (no truncation).
4. Insert `recognition_bench_runs` with `status=queued`, `phase=queued_pending_claim`, `item_cursor=0` (single-live unique index enforces at most one live row).
5. Audit `BENCH_RUN_CREATE`.
6. Return **202** `{ run_id, status: "queued", media_count, ... }` immediately.

#### Re-entrant supervisor (FIR8R3-04 / FIR8R4-01 / FIR8R4-02) — phase + item cursor + non-blocking tick

**Persisted columns on `recognition_bench_runs`:**

| Column | Type | Role |
| --- | --- | --- |
| `phase` | text / enum | Current supervisor phase (see below) |
| `item_cursor` | int | Next media index (0-based) within the current phase’s item loop; 0 when phase has no per-item loop |
| `started_at` | timestamptz | Set once on first successful claim — **claimed-run timeout clock** |
| durable ingest outcomes | child table / JSON | Per-item ok/failed (+ sha256); source of `failed_ingest_count` across resume (FIR8R4-04c) |

**Phase enum (ordered; `N_PHASES = 7` work phases after claim):**

```text
queued_pending_claim → ingest → enqueue_scan → await_scan → cluster → score → seal → purge → terminal
```

(Terminal is represented by `status ∈ {completed,failed,cancelled}`. Happy path reaches `completed` **only after** `purge` succeeds.)

#### Non-blocking tick contract (FIR8R4-02) — normative

| Rule | Contract |
| --- | --- |
| **One step per tick** | Each `bench_run_supervisor_tick` performs **at most ONE bounded phase step**, then **returns**. Persist `phase` + `item_cursor` (+ durable outcomes) **before** return. |
| **Bounded step** | Per-item phases (`ingest`): advance **one** media item (or no-op progress check) then return. Non-item phases (`enqueue_scan`, `cluster`, `score`, `seal`, `purge`): perform one discrete unit of work (enqueue once, one status observation, one seal write, one purge transaction) then return. |
| **Never poll-until-terminal inside a tick** | **Forbidden:** loops that wait on scan/cluster completion, sleep-retry, or “while not done” inside one tick. `await_scan` / cluster-wait: **single observation** of job state; if not terminal, leave `phase` unchanged and return so the worker loop can run other work. |
| **Production-job interleaving** | Because the tick returns every poll interval, **production-shaped job processing on the same worker must interleave between ticks**. Discriminating test below. |
| **Intra-phase wall-clock re-check** | Before each per-item step (and at tick entry), re-check claimed-run / queued-age timeouts; do not rely on a single check only at phase entry. |

**Discriminating test (FIR8R4-02):** with a bench run mid-`await_scan` (scan items still pending), enqueue a non-bench production-style `IdentityScanJob` on the same worker; assert that job is **processed before the bench run reaches `completed`**. Red-proof: a tick that poll-until-terminals the bench scan starves the production job → test fails.

#### Each tick (steady-state reclaimer discipline — release-it / DDIA distilled)

1. **Runtime gate preamble (FIR8R4-03a) — every tick first:** re-evaluate `BOOT_AUTH_SET` via `evaluate_bench_preflight(..., blocker_set=BOOT_AUTH_SET)`. On **any** blocker (including flag flipped off mid-run): **no-op all phase work** for this tick **and** cancel any live run (`status=cancelled`, `error_code=bench_gate_disabled` or the specific blocker code); cancel outstanding scan items. **Purge via sweeper** (terminal + pending artifacts). **Test:** flip `RECOGNITION_BENCH_PROFILE_ENABLED` off mid-run → next tick cancels; sweeper purges artifacts.
2. **Timeout second (every tick, FIR8R4-02 clocks):**
   - `queued` and `now - created_at > RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC` → `failed` / `queued_timeout`; sweeper purges any partial artifacts (none expected).
   - `running` and `now - started_at > RECOGNITION_BENCH_RUN_TIMEOUT_SEC` → `failed` / `run_timeout`; cancel outstanding scan items; sweeper purges. **Do not** wait for startup-only reclaim.
3. **Claim once (FIR8R4-03b):** if no `running` run, attempt conditional `queued → running` with `phase=ingest`, `item_cursor=0`, `started_at=now()`. **Before any phase work after claim (and on every resume):** re-verify `RECOGNITION_FACE_PIPELINE_PROFILE=insightface` **and** `PGVECTOR_DIM=512`. Config drift → set run `failed` with stable `error_code=profile_not_insightface` or `pgvector_dim_not_512` (match preflight codes); do not advance phases. Single-live index guarantees at most one claimer wins.
4. **Resume idempotently:** load the single `running` run (if any); re-verify profile+dim (step 3); **switch on persisted `phase`** — never restart from ingest if already mid-scan. Advance `item_cursor` after each successfully persisted per-item step so a crash mid-phase resumes at the next item, not from zero. Durable ingest outcomes keep `failed_ingest_count` honest across resume (FIR8R4-04c).
5. **Phase work — exactly one bounded step (FIR8R4-02), then return:**
   - **ingest:** one item from `item_cursor`: resolve URL + connect to **pinned address set**; HTTPS GET; `FilesystemObjectStore.put`; stamp sha256; persist per-item outcome; audit; increment cursor. When all items attempted → apply **ingest hard-fail** or `phase=enqueue_scan`.
   - **enqueue_scan:** create `IdentityScanJob` + items (`media_id`, `media_url`/blob URI, bench `tenant_id`); set `scan_job_id`; `phase=await_scan`; return.
   - **await_scan:** **single** observation of scan job/items; if not terminal → return unchanged; if terminal → `phase=cluster` (or skip toward `score` if no-faces path). **Never** loop until terminal in-tick.
   - **cluster:** enqueue clustering if needed **or** single observation of clustering job; when terminal → `phase=score`.
   - **score:** scorer; join baseline by **content_sha256** / media_id; hold result for seal; `phase=seal`.
   - **seal:** persist sealed metrics + provenance on run row; **status stays `running`**; `phase=purge`.
   - **purge:** delete-by-default blobs + embeddings; set `artifacts_purged_at`; set `status=completed`. (Still held single-live until this status flip.)
6. **Flag-independent sweeper step (same tick or sibling hook):** claim terminal rows with `artifacts_purged_at IS NULL` and purge (FIR8R4-01 failed/cancelled path + mid-purge crash safety).
7. **Crash mid-phase:** process death leaves `status=running` + last persisted `phase`/`item_cursor`/outcomes. Next tick: gate preamble → timeout check → either terminal error or resume at that phase (idempotent side effects: skip already-ingested items via cursor / durable outcomes).

**Not in scope:** dual full-pipeline 202 without a job table. **Not in scope:** new distributed queue product. **Not in scope:** sync ingest on POST. **Not in scope:** poll-until-terminal inside `bench_run_supervisor_tick`.

Tests must cover: POST returns 202 with `queued` and **zero** scan job rows yet; supervisor tick creates jobs without starving other jobs; worker processes under bench tenant; second POST concurrent → 409; **queued insert while running exists → unique violation / 409** (FIR8R3-01); **new POST while `phase=purge` still `running` → 409** (FIR8R4-01); **completed ⇒ artifacts gone + `artifacts_purged_at` set**; timeout enforced on a mid-phase running row without restart; queued-age timeout separate; crash mid-ingest resumes at `item_cursor` with durable failure count; ingest hard-fail → failed without successful seal of fake metrics; production job interleaves mid-bench-scan (FIR8R4-02); flag-off mid-run cancels next tick (FIR8R4-03a); claim/resume profile/dim drift fails run (FIR8R4-03b).

### Concurrency — ONE mechanism (FIR8R2-06 / FIR8R3-01 / FIR8R4-01)

**Wrong (v3):** `UNIQUE (status) WHERE status IN ('queued','running')` — permits **one queued AND one running** concurrently (different `status` values).

**Required (constant-expression unique partial index → at most ONE live row total):**

```sql
CREATE UNIQUE INDEX uq_bench_single_live
  ON recognition_bench_runs ((1))
  WHERE status IN ('queued', 'running');
```

- Expression `(1)` is constant for every live row → uniqueness admits **at most one** row matching the predicate, regardless of whether it is `queued` or `running`.
- **Purge-before-terminal (FIR8R4-01):** happy-path `purge` executes while `status=running`, so the index **blocks a new run until purge finishes and status becomes `completed`**.
- No second flock/file lock as a required mechanism.
- Transactional insert catches unique violation → **409** `bench_run_in_progress`.
- Application pre-check may exist for friendlier errors but is **not** the source of truth.
- Discriminating tests: [TEST-15] `test_single_live_index_rejects_queued_while_running`; `test_no_new_run_while_purge_pending`.

### Crash recovery

- **Every supervisor tick** (not only startup): gate preamble + timeout reclaim as above (FIR8R3-04 / FIR8R4-02 / FIR8R4-03).
- API/worker **startup** additionally: same timeout fail for live runs older than the applicable clock → `failed` / `error_code=stale_reclaim` (or `run_timeout` / `queued_timeout` — prefer the clock-specific code for age breaches; `stale_reclaim` only if a separate reclaim path needs distinction); **always** run purge sweeper on terminal pending-artifact rows.
- Orphan scan jobs for bench tenant: existing worker stale reclaim paths apply; bench supervisor reconciles parent run status from persisted phase.

### Cancel-on-disable

- Soft path: `POST /admin/bench/runs/{id}/cancel` (`require_admin_header` + `BOOT_AUTH_SET` preflight; not blocked by `bench_run_in_progress`) sets `cancelled`, attempts to mark pending scan items failed/cancelled; **purge via sweeper** (terminal + pending artifacts).
- **Runtime path (FIR8R4-03a):** every tick preamble re-evaluates `BOOT_AUTH_SET`; flag/gate failure cancels live run without requiring process restart for the cancel effect. Routes may still require restart to unmount; cancellation is tick-driven.
- If process restarts with `RECOGNITION_BENCH_PROFILE_ENABLED=0`, boot succeeds without bench routes; **purge sweeper still runs** so leftover artifacts do not linger.
- Config reload not fully supported for route mount: document **restart required** to flip gate env for HTTP surface; supervisor cancel-on-disable is the in-process safety rail.

---

## Lifecycle pins (FIR8R2-06 / FIR8R3-01 / FIR8R3-04 / FIR8R3-05 / FIR8R4-01…04) — normative

| Pin | Single definition |
| --- | --- |
| Concurrency | `CREATE UNIQUE INDEX uq_bench_single_live ON recognition_bench_runs ((1)) WHERE status IN ('queued','running')` only — **not** `UNIQUE (status)`; holds through happy-path `purge` |
| Supervisor resume | Persisted `phase` + `item_cursor` + durable ingest outcomes; claim once; timeout every tick |
| Non-blocking tick | **One** bounded phase step per tick then return; never poll-until-terminal; production jobs interleave (FIR8R4-02) |
| Purge-before-terminal | Happy path: `score → seal → purge → completed` while live; failed/cancelled: sweeper claims terminal rows with pending artifacts (FIR8R4-01) |
| Timeout clocks | Claimed run from `started_at` (`RECOGNITION_BENCH_RUN_TIMEOUT_SEC`); queued from `created_at` (`RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC`); `N_PHASES=7` in formula_floor (FIR8R4-02) |
| Tick preamble | Re-eval `BOOT_AUTH_SET` every tick; fail → cancel live run + no-op (FIR8R4-03a) |
| Claim/resume config | Re-verify profile=`insightface` + `PGVECTOR_DIM=512` before phase work (FIR8R4-03b) |
| Marker stamp | `INSERT … ON CONFLICT DO NOTHING` + mandatory read-back (FIR8R4-03c) |
| Purge sweeper | Runs at API **and** worker startup **and** each tick **regardless of** `RECOGNITION_BENCH_PROFILE_ENABLED`; claims terminal rows with pending artifacts; audit purge filters **only** bench `AdminAuditEvent` values listed under retention |
| JSON bench mutations auth | `require_admin_header` **only** (Basic rejected) — same rule as existing admin JSON mutations |
| `admin_auth_ok_context` | See [Terminology](#terminology) — single definition; not redefined per route |
| Audit retention | **90 days** default (`RECOGNITION_BENCH_AUDIT_RETENTION_DAYS=90`) |
| Production-shaped | ANY of `tenants`, `media_identities`, `identity_clusters`, `identity_members` nonzero (FIR8R4-04a) |
| Baseline cover | Baseline media_id set **superset** of accepted run set (FIR8R4-04b) |
| DNS pin | Pinned **set** of addresses; public unicast unless `RECOGNITION_BENCH_ALLOW_PRIVATE_SOURCE=1` (FIR8R4-04d) |

---

## Contract and Boundary Impact

### Recognition service — bench host (authoritative mutations)

Mount **only** under the existing env-gated **`/admin`** router tree (FIR8PR-07): e.g. routes registered on `admin_router` or `include_router(bench_router, prefix=...)` **inside** the `if security_settings.admin_enabled` block in `api/main.py`. **Never** on the tenant API-key `/recognition` router.

Auth (FIR8R3-05a) — match existing admin router rule **verbatim**:

- Router-level: `Depends(require_admin)` (header **or** Basic) for the `/admin` tree.
- **JSON bench mutations** (`POST` catalog / baselines / runs / cancel): **additionally** `dependencies=[Depends(require_admin_header)]` — **Basic rejected** for programmatic JSON (browser credential replay cannot authorize cross-site JSON mutation). Same pattern as existing admin JSON mutations in `admin.py`.
- HTML console forms: Basic + `require_same_origin` (not `require_admin_header`).

Audit enum additions (`AdminAuditEvent`, sr-007) — also the **only** values audit purge may delete (FIR8R3-05c):

- `BENCH_RUN_CREATE = "bench.run.create"`
- `BENCH_RUN_CANCEL = "bench.run.cancel"`
- `BENCH_MEDIA_INGEST = "bench.media.ingest"`
- `BENCH_CATALOG_UPSERT = "bench.catalog.upsert"`
- `BENCH_BASELINE_UPLOAD = "bench.baseline.upload"`

#### `GET /admin/bench/status`

**Response 200** (all server-derived):

```json
{
  "bench_enabled": true,
  "bench_available": true,
  "admin_auth_ok_context": true,
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
  "run_timeout_sec": 1650,
  "active_run_id": null,
  "license_notice": "non-commercial weights — internal benchmarking only",
  "boot_auth_blockers": [],
  "run_create_blockers": [],
  "activation_blockers": []
}
```

- `boot_auth_blockers` / `run_create_blockers` ≔ results of `evaluate_bench_preflight` for each named set (FIR8R3-03).
- `activation_blockers` ≔ union of both lists (compat for UI “any blocker”); `bench_available` for **starting a run** ≔ `run_create_blockers == []` **and** `admin_auth_ok_context`. Catalog/baseline UI may enable when only `boot_auth_blockers == []`.
- `isolation_mode` is the **constant** `"dedicated_bench_deployment"` (not a client choice).

#### `POST /admin/bench/source-catalog`

Enroll/replace catalog rows for env source tenant. Auth: `require_admin_header`. Preflight: **`BOOT_AUTH_SET`**. Validates allowlist; **pins object host address set** (public unicast unless private-source override — FIR8R3-05d / FIR8R4-04d). Audit `BENCH_CATALOG_UPSERT`.

#### `POST /admin/bench/baselines`

Upload label-free baseline artifact JSON per [normative schema](#normative-baseline-upload-json-schema-fir8r3-05b). Auth: `require_admin_header`. Preflight: **`BOOT_AUTH_SET`**. Audit `BENCH_BASELINE_UPLOAD`. Returns `baseline_artifact_id`.

#### `POST /admin/bench/runs`

**Request**:

```json
{
  "media_ids": [101, 102, 103],
  "baseline_artifact_id": "uuid-optional",
  "sample_limit": 10
}
```

- `source_tenant_id` **not accepted** from client (server env). If present and ≠ enrolled → 400 `source_tenant_mismatch`.
- `media_url` **anywhere in body** → 400 `media_url_not_accepted`.
- `sample_limit` optional consistency check only; **does not truncate**. `len(media_ids) == 0` → 400 `empty_selection`. `len > 20` → 400 `sample_limit_exceeded`.
- `profiles` array **not accepted**.

**Response 202** (run is queued; **no** ingest side effects yet):

```json
{
  "run_id": "uuid",
  "status": "queued",
  "media_count": 3,
  "isolation_mode": "dedicated_bench_deployment",
  "license_notice": "non-commercial weights — internal benchmarking only"
}
```

- `media_count` = accepted id count after validation ([rg-015]).
- Observability assertion in tests: after POST, `identity_scan_jobs` count for this run is **0** until a supervisor tick.

#### `GET /admin/bench/runs/{run_id}`

```json
{
  "run_id": "uuid",
  "status": "completed",
  "media_count": 3,
  "metrics": {
    "source": "live_tenant_bench",
    "join_key": "content_sha256",
    "code_sha": "0123456789abcdef0123456789abcdef01234567",
    "prod_baseline": {
      "status": "ok",
      "effective_profile": "face_pipeline",
      "embedding_model_id": "…",
      "pgvector_dimension": 128,
      "code_sha": "…",
      "detection_count_total": 40,
      "images_with_detections": 9,
      "faces_per_image_mean": 4.0,
      "cluster_purity": null,
      "unknown_rejection": null
    },
    "bench_insightface": {
      "effective_profile": "insightface",
      "embedding_model_id": "insightface-buffalo_l@512d/l2/cosine",
      "pgvector_dimension": 512,
      "code_sha": "0123456789abcdef0123456789abcdef01234567",
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
    },
    "items": [
      {
        "media_id": 101,
        "content_sha256": "…",
        "prod": { "detection_count": 4 },
        "bench": { "detection_count": 6 }
      }
    ]
  },
  "license_notice": "non-commercial weights — internal benchmarking only",
  "artifacts_purged_at": "2026-07-23T12:00:00Z"
}
```

#### `POST /admin/bench/runs/{run_id}/cancel`

→ 200 with status `cancelled` or 409 if already terminal.

### Recognition service — production host

**No new production admin routes required for FIR-8 MVP** (option b). Operators export baseline/catalog via existing operator tooling / ad-hoc queries outside this task’s deliverables. A future production export helper may land under another task; do not block FIR-8 on it.

### WordPress plugin

**No routes, no SPA panel, no proxy in this task.** (FIR8PR-09)

### Persistence (bench DB)

#### `recognition_bench_runs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | run_id |
| `status` | str | state machine |
| `phase` | text | supervisor phase (FIR8R3-04 / FIR8R4-01); includes first-class `purge` before `completed` |
| `item_cursor` | int | next media index within phase; default 0 |
| `source_tenant_id` | UUID | enrolled source |
| `bench_tenant_id` | UUID | local bench tenant |
| `media_ids` | int[] / JSON | accepted ids |
| `media_count` | int | accepted count |
| `baseline_artifact_id` | UUID nullable | uploaded baseline (must cover accepted set as superset) |
| `scan_job_id` | UUID nullable | set by supervisor after ingest |
| `metrics` | JSONB nullable | sealed in `seal` phase; status still `running` until purge |
| `error_code` | text nullable | stable codes |
| `created_at` / `started_at` / `completed_at` | timestamptz | `started_at` = claim clock; `completed_at` only after purge→completed |
| `artifacts_purged_at` | timestamptz nullable | required non-null for happy-path `completed` |

**Index (FIR8R3-01):** 

```sql
CREATE UNIQUE INDEX uq_bench_single_live
  ON recognition_bench_runs ((1))
  WHERE status IN ('queued', 'running');
```

#### Supporting tables (same greenfield file)

- `recognition_bench_source_media` — catalog (`source_tenant_id`, `media_id`, `media_url`, **`pinned_host_ips`** address set, timestamps)
- `recognition_bench_baseline_artifacts` — uploaded JSON + metadata
- `recognition_deployment_markers` — singleton deployment_class marker (stamp: `ON CONFLICT DO NOTHING` + read-back)
- `recognition_bench_run_items` (preferred) — per-item sha256, durable ingest outcome (FIR8R4-04c); or JSON on run row

**Slice ownership of `001_identity_schema.py` (FIR8R3-05e):** schema lands **where its tests live** — S1 owns marker table + fail-closed stamp tests (incl. concurrent `ON CONFLICT` stamp); S2 owns `recognition_bench_runs` (+ `phase`/`item_cursor` + durable ingest outcomes + `uq_bench_single_live`) + concurrency/supervisor tests; S3 owns catalog/baseline tables (+ `pinned_host_ips`) + intake tests. All still edit the single greenfield file `db/migrations/versions/001_identity_schema.py` (no add-on migrations).

### Observability

- Log fields: `bench_run_id`, `embedding_model_id`, `isolation_mode=dedicated_bench_deployment`, `source=live_tenant_bench`, `content_sha256` (per item).
- Do not emit onto production quality SLO dashboards without a `bench` label ([OBS-09]).

### Operator HTML UI (bench `/admin`)

Extend `admin_console.py` (or sibling) with a **Bench** section:

- License banner (non-commercial).
- Shows `activation_blockers` when `bench_available=false`.
- Catalog upload + baseline upload forms.
- When available: **media id** list input (no URL fields), default N display **10**, max **20**, empty submit → server error surfaced.
- Primary control reachable at zero selection for **navigating to the form**, but **Run** requires non-empty validated items ([rg-003]).
- Status poll of active run; statuses as server strings mapped in one place (Python enum / const).

---

## Small pins (FIR8PR-07 + ops R-8/R-10 + FIR8R2-* + FIR8R3-05 + FIR8R4-*)

| Pin | Decision |
| --- | --- |
| Bench router mount | **Inside** env-gated `/admin` only (`api/main.py` admin branch). |
| JSON bench mutations auth (FIR8R3-05a) | **`require_admin_header` only** (Basic rejected) — match existing admin JSON mutation rule in `admin.py` verbatim |
| face_metrics | **Duplicate** in `recognition/application/bench/score.py` (+ optional `face_metrics.py`); parity unit test vs fixture. **Not** runtime import of `scripts/`. |
| Blob API | `FilesystemObjectStore.put` in `recognition/application/storage/filesystem.py` |
| Scan item fields | `media_id`, `media_url` (blob URI), `tenant_id`, `job_id`, `status` |
| Baseline (FIR8R3-05b / FIR8R4-04b) | Operator upload on bench (option b); normative schema; run create requires baseline media_id set **⊇** accepted run set; **no** prod admin token on bench |
| Catalog DNS pin (FIR8R3-05d / FIR8R4-04d) | Catalog write resolves + **pins address set**; ingest connects only to pinned set; public unicast unless `RECOGNITION_BENCH_ALLOW_PRIVATE_SOURCE=1` |
| Run path | Fully async; **re-entrant non-blocking** supervisor (`phase` + `item_cursor`; one step/tick) |
| Happy-path purge (FIR8R4-01) | `score → seal → purge → completed` while still live; completed implies artifacts gone |
| Truncation | Reject >20 only; no silent `min` |
| Join key | `content_sha256` stamped at ingest |
| Concurrency (FIR8R3-01) | `uq_bench_single_live` on `((1)) WHERE status IN ('queued','running')` only (includes purge phase) |
| Purge sweeper | Boot **and tick** sweeper **always** (flag on or off); claims terminal rows with pending artifacts; audit purge **only** bench `AdminAuditEvent` values (FIR8R3-05c) |
| Audit retention | 90 days |
| I1 default | Transitional: dark env default still **insightface** until FIR-6; bench gate still required for operator bench surface / `internal_bench` class |
| Default sample N | **10**; hard max **20** |
| Empty selection | **Nothing** — 400 `empty_selection`; never “all” |
| Wall timeout default | **1650** s (≥25% slack over cold-start-inclusive floor **1317** s with `N_PHASES=7`) |
| Queued-age timeout | **`RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC=300`** (separate clock) |
| WP | **Nothing in MVP** |

---

## Residual risks (FIR8R2-07 / FIR8R3-02 / FIR8R4-04d) — pinned now

| Residual | Class | Operator-ack |
| --- | --- | --- |
| **`RECOGNITION_ADMIN_TAILNET_BOUND=1`** | Operator attestation, not a network-enforced control-plane check inside this service. Mis-set flag claims tailnet binding without infrastructure proof; network policy remains deploy/ops responsibility. | **Operator-acked** residual for FIR-8. |
| **`RECOGNITION_DEPLOYMENT_CLASS=internal_bench`** | Env self-attestation of deployment role, not an infrastructure topology proof. A mislabeled host can claim bench class without platform-level isolation guarantees; process gates still enforce the string + data-plane checks when the flag is on. | **Operator-acked** residual for FIR-8 (same treatment as `TAILNET_BOUND`). |
| **`RECOGNITION_PROD_ENDPOINT_DENYLIST`** | Operator-supplied denylist of production endpoints; collision checks are exact-string/normalized comparisons against configured endpoints, not continuous topology discovery. Incomplete denylist entries are an ops config risk. | **Operator-acked** residual for FIR-8 (same treatment as `TAILNET_BOUND`). |
| **`RECOGNITION_BENCH_ALLOW_PRIVATE_SOURCE=1` (FIR8R4-04d)** | Opt-in override that permits non-public (RFC1918 / link-local / loopback) addresses in the DNS pin set for a LAN-internal media store. Default off (public unicast only). Mis-set allows SSRF-class pulls to private infrastructure the allowlist hostname maps to. | **Operator-acked** residual for FIR-8 when private-source mode is enabled. |
| **Buffalo / insightface on non-bench deployments** | **FIR-6-owned residual** (transitional dark default + commercial switch-over). This task’s gates keep the **operator bench surface** off production; they do not complete the product default flip. | Tracked under FIR-6; not re-opened here. |

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
| **S1** Boot gate + isolation lock + data-plane proof + ID renumber | Flag default false; `validate_bench_license_gate`; denylist (all external endpoints); **fail-closed** marker with **`ON CONFLICT DO NOTHING` + read-back** (FIR8R4-03c); production-shaped = four core tables (FIR8R4-04a); `BOOT_AUTH_SET` / `RUN_CREATE_SET`; marker schema in `001_identity_schema.py`; MCP decisions; scope+epic FIR-9 | Boot refuses incomplete license, denylist collision, production marker, **or unmarked DB with production-shaped data**; concurrent stampers converge; flag-off boots **with purge still registered**; docs renumber | Unit: boot matrix; denylist/marker fail-closed; concurrent stamp; split preflight; [TEST-15] profile drift + enrollment-while-empty |
| **S2** Async run vehicle + bounds + run schema | `recognition_bench_runs` + `phase`/`item_cursor` + durable ingest outcomes + **`uq_bench_single_live ((1))`**; POST = validate+insert+202 only; **non-blocking** re-entrant `bench_run_supervisor_tick` (one step/tick; FIR8R4-02); purge-before-terminal (FIR8R4-01); tick preamble `BOOT_AUTH_SET` (FIR8R4-03a); claim profile/dim re-verify (FIR8R4-03b); timeout formula with `N_PHASES=7` + queued-age env; hard-fail | POST leaves 0 scan jobs; tick resumes phase without poll-until-terminal; concurrent 409 including purge-pending; completed ⇒ artifacts gone; production job interleaves mid-bench; flag-off mid-run cancels; timeout/hard-fail codes | Unit + API + worker tests |
| **S3** Catalog + baseline upload + intake + retention | Source catalog + **pinned address set** (public unicast / private override); baseline upload schema + **superset cover** (FIR8R4-04b); async ingest + pin re-verify; durable per-item outcomes; allowlist; audit 90d **bench enums only**; delete-by-default; purge-always sweeper claims terminal pending rows | Catalog rejects bad host / non-public pins (default); pin-set miss fails ingest; baseline partial cover → `baseline_missing`; unknown-field/sha/size reject; purge clears media; flag-off purge still runs; non-bench audit rows untouched | Unit + API + supervisor |
| **S4** REST metrics + status + scorer | GET status/runs; scorer label-free + null purity; join by sha256; dual-side provenance stamps; face_metrics parity fixture | Contract tests; parity test; no scripts import in app path | API + unit score |
| **S5** `/admin` HTML bench panel | Console section; banner; blockers; catalog/baseline upload; media **ids** form; empty≠all; default N=10 | HTML non-commercial notice; no media_url fields | API/console tests |

S1 → S2 → S3 → S4 sequential; S5 after status/run JSON frozen (fixtures from S4).

**Schema ownership (FIR8R3-05e):** `db/migrations/versions/001_identity_schema.py` is edited by S1 (markers), S2 (bench runs + single-live index + phase/cursor), S3 (catalog/baseline tables). Tests for each table live in the owning slice.

---

## Junior-executable contracts (per slice)

### S1 — Boot gate + preflight + data-plane + docs renumber

**Files**

- `recognition/config/security.py` or `settings.py`: `_bool_env("RECOGNITION_BENCH_PROFILE_ENABLED", False)`; `deployment_class`; denylist parse (**all** external endpoints); `validate_bench_license_gate`; data-plane checks; fail-closed marker stamp.
- `recognition/application/bench/preflight.py`: **`evaluate_bench_preflight(ctx, blocker_set=...)`** — sole blocker function; `BOOT_AUTH_SET` / `RUN_CREATE_SET`.
- `db/migrations/versions/001_identity_schema.py`: **`recognition_deployment_markers`** (and any marker-only helpers) — schema lands with S1 marker tests (FIR8R3-05e).
- `api/main.py` + worker entry: validate at startup; **always** register purge sweeper (audit filter = bench enums only).
- Scope + epic markdown renumber (FIR-9).

**Preflight signature**

```text
evaluate_bench_preflight(ctx: BenchPreflightContext, *, blocker_set: BenchBlockerSet) -> list[str]
# BenchBlockerSet = BOOT_AUTH_SET | RUN_CREATE_SET
# ctx carries: bench_enabled, deployment_class, admin_enabled, tailnet_bound,
#   source_tenant_configured, bench_tenant_configured, media_allowlist_configured,
#   source_catalog_nonempty, baseline_present, pgvector_dimension, env_profile,
#   insightface_runtime_ok, active_run_present, data_plane_ok
```

**Tests (red first, [TEST-06])**

1. Flag off → `BOOT_AUTH_SET` blockers include `bench_flag_off`; boot OK without deployment_class.
2. Flag on + missing tailnet → **boot raises** `bench_license_gate_failed`.
3. Flag on + `deployment_class=production` → boot raises.
4. Flag on + dim≠512 → `RUN_CREATE_SET` includes `pgvector_dim_not_512`; **not** required to block catalog enroll.
5. Flag on + profile `face_pipeline` → `profile_not_insightface` under `RUN_CREATE_SET`.
6. All clear → `[]` for the selected set.
7. Denylist collision (DB / blob / cache-queue) / production marker / empty denylist → boot `bench_data_plane_collision` / `prod_denylist_unconfigured`.
8. Unmarked DB with any of `tenants` / `media_identities` / `identity_clusters` / `identity_members` count > 0 → boot refuse; **no** `internal_bench` stamp (FIR8R4-04a).
9. Unmarked empty DB → stamp `internal_bench` and boot (`ON CONFLICT DO NOTHING` + read-back).
10. **[TEST-15]** post-boot profile drift → POST runs 403 `profile_not_insightface`.
11. **[TEST-15]** enrollment succeeds while `source_catalog_empty` would fire under `RUN_CREATE_SET`.
12. **[TEST-15]** two concurrent first-stampers converge on one `internal_bench` row (FIR8R4-03c).
13. Scope/epic: escalation references are `FIR-9` not `FIR-8`.

**Mutation red-proof**: force POST runs to skip `evaluate_bench_preflight` → test 10 fails; force enroll to use `RUN_CREATE_SET` → test 11 fails; force stamp without read-back / use plain INSERT without ON CONFLICT → test 12 fails under concurrency.

### S2 — Async run vehicle

**Rules**

- No second worker binary; start bench `scan_worker` against bench DSN as today.
- POST never calls ingest/scan/score.
- Supervisor name: `bench_run_supervisor_tick` — **re-entrant + non-blocking** via `phase` + `item_cursor` + durable ingest outcomes (one bounded step per tick — FIR8R4-02).
- Single live run: `uq_bench_single_live` on `((1))` through happy-path `purge`.
- Happy path: `score → seal → purge → completed` (purge while still live — FIR8R4-01).
- Tick preamble re-evals `BOOT_AUTH_SET`; claim/resume re-verifies profile+dim (FIR8R4-03).
- Timeout env default **1650** with `N_PHASES=7` floor **1317**; queued-age **`RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC=300`**; unit test locks arithmetic + ≥25% slack.
- Timeout enforced **every tick** + per-item re-check; clocks: claimed from `started_at`, queued from `created_at`.
- Ingest hard-fail: ≥3 durable failures or 0 successes.
- Schema in `001_identity_schema.py`: `recognition_bench_runs` + index (tests live in S2).

**Tests**

1. POST → 202 `queued`; **no** `IdentityScanJob` row yet.
2. After supervisor ticks with mocked GETs → scan job + items exist; `phase` advances **one step per tick** (no multi-phase drain in one call).
3. Second POST while queued/running → 409 `bench_run_in_progress` (unique index path).
4. **[TEST-15]** insert `queued` while `running` exists → unique violation / 409 (broken `(status)` index must fail this).
5. 21 media_ids → 400 `sample_limit_exceeded` (not silent truncate).
6. Body with `media_url` → 400 `media_url_not_accepted`.
7. 0 ids → 400 `empty_selection`.
8. Simulated timeout mid-phase (without process restart) → `failed` / `run_timeout` (from `started_at`).
9. Crash mid-ingest: next tick resumes at `item_cursor` with durable `failed_ingest_count` preserved (or times out).
10. 3 ingest failures of 10 → `failed` / `ingest_hard_fail`.
11. Timeout constant test: `1650 >= ceil(1317 * 1.25)` and `1650 > 20*(30+17)+120+60+90+100+7*1`.
12. **[TEST-15] purge-before-terminal (FIR8R4-01):** completed run has artifacts gone + `artifacts_purged_at` set; POST while `phase=purge`/`status=running` → 409.
13. **[TEST-15] non-blocking interleave (FIR8R4-02):** bench mid-`await_scan` + enqueued production-style job → production job processed before bench `completed`.
14. **[TEST-15] flag-off mid-run (FIR8R4-03a):** next tick cancels live run; sweeper purges artifacts.
15. Claim/resume with profile or dim drift → run `failed` with stable code (FIR8R4-03b).
16. Queued row older than `RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC` → `failed` / `queued_timeout` without claim.

### S3 — Catalog + baseline + intake + retention

**Tests**

1. Catalog URL host not on allowlist → rejected.
2. Catalog write stores **pinned_host_ips** set; ingest targeting an address outside the set → item fail / no fetch.
3. Non-public pin (RFC1918) rejected by default; accepted only when `RECOGNITION_BENCH_ALLOW_PRIVATE_SOURCE=1` (FIR8R4-04d).
4. Successful ingest → audit `bench.media.ingest` + sha256 present; uses `FilesystemObjectStore.put`; durable per-item outcome row.
5. On complete → media + embeddings gone; `artifacts_purged_at` set; metrics retained.
6. Body `source_tenant_id` ≠ env → 400.
7. Baseline upload stores artifact; unknown field / sha mismatch / >5 MiB → 422 reject.
8. Baseline covering a **strict subset** of accepted media_ids → run create `baseline_missing` (FIR8R4-04b); superset → clear.
9. Process start with flag **off** still purges terminal run with null `artifacts_purged_at` (sweeper claims terminal pending).
10. Audit rows older than 90d **with bench enum values** purged by sweeper; `tenant.create` rows **not** purged (unit with frozen clock).

### S4 — REST + scorer

**Rules**

- Router under admin mount only; JSON mutations `require_admin_header`.
- Scorer in `recognition/application/bench/score.py`; **in-tree** metrics helpers; **no** `scripts` import at runtime.
- Join key `content_sha256`; stamp both legs’ profile/model/dim/code_sha.
- Never call adapters to self-report quality ([OBS-09]).

**Tests**

1. Unauthenticated → 401/403.
2. JSON mutation with Basic only (no admin header) → 401 (FIR8R3-05a).
3. Flag off → 403 `bench_flag_off`.
4. Completed unlabeled run → `cluster_purity` is JSON `null`.
5. `license_notice` contains `non-commercial`.
6. `isolation_mode` constant `dedicated_bench_deployment`.
7. Sealed metrics include both legs’ provenance stamps + item sha256 keys.
8. **face_metrics parity**: fixture vectors match expected golden outputs.

### S5 — HTML console

**Tests**

1. `bench_available=false` → blockers visible; run submit absent or disabled.
2. Banner substring `non-commercial`.
3. Form has media **id** inputs; **no** media_url fields in bench run form.
4. Form does not default media selection to “all”.

---

## Files and Surfaces to Change (implementation map)

| Area | Likely paths |
| --- | --- |
| Gate / settings | `recognition/config/settings.py`, `recognition/config/security.py` |
| Preflight / score / supervisor | `recognition/application/bench/*` (new): `preflight.py`, `supervisor.py`, `score.py`, optional `face_metrics.py` |
| Storage | **call** `recognition.application.storage.FilesystemObjectStore.put` — no second blob subsystem |
| Factory | **call only** via existing `build_embedding_runtime` — no third profile |
| HTTP | `recognition/interface_adapters/http/routers/admin.py` (or `bench.py` included from admin), `admin_console.py`, `api/main.py` mount stays admin-gated |
| Worker | `recognition/worker/scan_worker.py` — **hook** to call `bench_run_supervisor_tick` once per poll; no fork |
| Schema | `db/migrations/versions/001_identity_schema.py` + `db/models/` |
| Production diagnostics | **none** for FIR-8 MVP (option b) |
| WP | **none** |
| Docs | scope + epic renumber; short runbook under `docs/runbooks/` (bench deploy env template including denylist) |
| Tests | `recognition/tests/api/test_bench_*.py`, unit preflight/score/purge/supervisor |

---

## Verification Strategy

- Per-slice scoped TDD; observe new tests fail first ([TEST-06]).
- Discriminating gate tests ([TEST-15]): boot license matrix × fail-closed marker + concurrent stamp × denylist all endpoints × split preflight (enroll while empty) × profile drift at run mutation × single-live index (queued-while-running + purge-pending) × non-blocking interleave × flag-off mid-run cancel × baseline superset × bounds reject (not truncate) × async POST creates no jobs.
- Determinism ([TEST-08]): scorer pure over fixtures; null purity locked; face_metrics parity fixture.
- Timeout arithmetic unit lock (cold-start + blob IO + `N_PHASES=7` poll; ≥25% slack → 1650; separate queued-age env).
- `make check-remote` for description-service surfaces touched.
- Manual smoke (close decision): bench compose/stack with flag+class+admin+tailnet+denylist; catalog+baseline upload; 10 media_ids; 202 then poll to complete; insightface detection counts visible; purge verified; production worker CPU idle; license banner present; no prod token env on bench.
- Adversarial review per slice; findings **only** in handoff MCP (not pasted into this plan).

---

## Consolidated Checklist

### Context and Ownership

- [ ] MCP decisions recorded: `fir8_isolation_mode_dedicated_bench_deployment`, `fir8_baseline_delivery_operator_upload`, `fir8_run_path_fully_async_supervisor`
- [ ] Plan accepted via planning-review before `make task-start TASK=FIR-8`
- [ ] Worktree: `feature/fir-8` via `make task-start`

### S1 — Boot gate + isolation + data-plane + ID renumber

- [ ] `RECOGNITION_BENCH_PROFILE_ENABLED` default false
- [ ] Boot-coupled gate: admin + tailnet_bound + `deployment_class=internal_bench` or refuse start
- [ ] Denylist covers **every** configured external endpoint (DB, blob, cache/queue) + tests
- [ ] Fail-closed marker: refuse unmarked DB with production-shaped rows (four core tables); stamp only empty DBs via `ON CONFLICT DO NOTHING` + read-back
- [ ] `evaluate_bench_preflight` with **`BOOT_AUTH_SET` / `RUN_CREATE_SET`** (not one deadlocking bag)
- [ ] [TEST-15] post-boot profile drift caught at run mutation; enrollment succeeds while catalog empty; concurrent stampers converge
- [ ] Purge sweeper registered even when flag off; audit purge filters bench enums only
- [ ] `001_identity_schema.py` marker table lands with S1 tests
- [ ] **Scope + epic**: escalation ladder → **FIR-9**; this bench task remains **FIR-8** (same baseline)
- [ ] Slice decision recorded

### S2 — Async run vehicle + bounds

- [ ] `recognition_bench_runs` + `phase`/`item_cursor` + durable ingest outcomes + `uq_bench_single_live ON ((1))` in `001_identity_schema.py`
- [ ] POST = validate + insert + 202 only (no ingest); `require_admin_header`
- [ ] Non-blocking re-entrant `bench_run_supervisor_tick` (one step/tick); timeout every tick + per-item re-check
- [ ] Happy path `score → seal → purge → completed` while live; failed/cancelled purge via sweeper
- [ ] Tick preamble `BOOT_AUTH_SET`; claim/resume profile+dim re-verify
- [ ] Max 20 reject / default 10 / empty=nothing / timeout **1650** (`N_PHASES=7` floor) + queued-age **300**
- [ ] Ingest hard-fail: ≥3 durable failures or 0 successes
- [ ] [TEST-15] queued-while-running + purge-pending 409; production-job interleave; flag-off mid-run cancel
- [ ] State machine + crash resume + cancel path
- [ ] Slice decision recorded

### S3 — Catalog + baseline + intake + retention

- [ ] Enrolled source tenant server-derived
- [ ] Catalog + baseline upload endpoints (option b); `BOOT_AUTH_SET`; `require_admin_header`
- [ ] Catalog pins host **address set**; ingest connects only to pinned set; public-unicast default
- [ ] Baseline normative schema (5 MiB, sha256, unknown-field reject); **superset** cover for run create
- [ ] Async HTTPS pull + host allowlist + size/time bounds; durable per-item ingest outcomes
- [ ] `FilesystemObjectStore.put`; sha256 join key stamped
- [ ] Client `media_url` rejected
- [ ] Ingest audit rows; audit retention 90d; purge **only** bench `AdminAuditEvent` values
- [ ] Delete-by-default media + embeddings; run row retention 30d
- [ ] Flag-off purge still runs (sweeper claims terminal pending)
- [ ] Slice decision recorded

### S4 — REST + metrics

- [ ] Routes only under `/admin`; JSON mutations header-only
- [ ] Label-free metrics; null label-dependent frames
- [ ] Independent scorer; in-tree face_metrics + parity fixture
- [ ] Join by content_sha256; both legs’ profile/model/dim/code_sha stamped
- [ ] `license_notice` + `source=live_tenant_bench`
- [ ] `baseline_missing` blocks run create unless baseline media_id set ⊇ accepted set; partial field nulls still honest when covering artifact present
- [ ] Slice decision recorded

### S5 — Operator HTML UI

- [ ] Panel on recognition `/admin` console only
- [ ] Non-commercial banner; blockers zero-state
- [ ] Catalog + baseline upload; media ids only (no URL fields)
- [ ] No WP surfaces
- [ ] Slice decision recorded

### Review readiness

- [ ] `make check-remote` green at HEAD
- [ ] `/review-parallel` findings in MCP only
- [ ] Zero open findings; `handoff_close_check(enforce=True)`

---

## Success Criteria

1. Incomplete bench license env, denylist collision, production marker, **or unmarked DB with production-shaped data** (four core identity-adjacent tables) **cannot boot** a bench-enabled process; concurrent marker stamps converge; flag-off production boots and cannot schedule insightface bench runs; purge still runs.
2. Operator obtains comparable **label-free** live-tenant numbers: uploaded production baseline vs bench insightface leg, **without** mixing embedding spaces in production and **without** prod admin credentials on the bench host.
3. POST is fully async (202 + **non-blocking** re-entrant supervisor); happy path **purge-before-terminal**; cold-start-inclusive timeout arithmetic (`N_PHASES=7`) holds with ≥25% slack; separate queued-age timeout; ingest hard-fail durable; timeout enforced every tick + per item.
4. Enrollment/baseline use **`BOOT_AUTH_SET`**; run create uses **`RUN_CREATE_SET`**; tick preamble + claim re-verify catch post-boot drift; single-live index admits at most one live row through purge ([TEST-15]).
5. License notice is visible and API-carried; insightface remains non-public and non-WP.
6. Runtime construction still funnels through `build_embedding_runtime` and `_FACE_PIPELINE_PROFILES`; no scan_worker fork.
7. Live-tenant bench output is explicitly not Golden-150 ([DIAG-08]); null purity on unlabeled media ([EVAL-01], [rg-015]); join key sha256; dual provenance stamps.
8. Bench compute never lands on production scan_worker; worker interleaves production jobs between bench ticks; bounds enforced server-side with **reject-over-cap** only.
9. Scope + epic IDs consistent: FIR-8 = bench surface; FIR-9 = escalation ladder.

---

## Rollback

- Tear down or stop the **bench deployment**; set `RECOGNITION_BENCH_PROFILE_ENABLED=0` on any misconfigured host (instant fail-closed for routes; purge still cleans artifacts).
- Production: no schema dependency for correct product behavior; no new prod baseline API in this task.
- Drop bench DB / greenfield reset clears 512D artifacts and markers.
- No FIR-6 product default changes in this task — rollback must not reintroduce buffalo as a silent **commercial** production default ([RLSE-08] spirit).
- Escalation after a failed product gate is **FIR-9**, not a weight revert post-commercial-launch.

---

## Planning-review finding map

### v2 resolution index (preserved)

| Finding | Severity | Resolution anchor in this plan |
| --- | --- | --- |
| **FIR8PR-01** dual-dim infeasibility | high | [Design decision: LOCKED dedicated bench](#design-decision-embedding-space-isolation-locked); [Rejected alternatives](#rejected-alternatives-appendix--do-not-implement) |
| **FIR8PR-08** no execution vehicle | high | [Execution vehicle](#execution-vehicle--fully-async-fir8r2-01--named); Slice **S2** |
| **FIR8PR-02** license gate boot-coupled | high | [I1](#i1-license--non-commercial-gate-rlse-05-serve-03--boot-coupled); [Boot-coupled license gate](#boot-coupled-license-gate-fir8pr-02--normative) |
| **FIR8PR-09 / FIR8PA-01** wrong human principal | high | [I4](#i4-operator-principal-fir8pr-09--fir8pa-01); WP **nothing** in MVP; `/admin` console S5 |
| **FIR8PR-03** media intake | high | [Media intake contract](#media-intake-contract-fir8pr-03--fir8r2-03--normative); Slice **S3** |
| **FIR8PA-03 / ops R-2** bounded work | high | [Bounded work](#bounded-work-fir8pa-03--ops-r-2--normative); [I8](#i8-production-cpu-isolation-fir8pa-03) |
| **FIR8PR-04** label honesty | medium | [I7](#i7-independent-bench-verdicts-obs-09-eval-01-test-08); [Label-free metrics](#label-free-metrics-contract-fir8pr-04--fir8r2-05) |
| **FIR8PR-05 / FIR8PR-06** lifecycle + enforcement | medium | [Run lifecycle](#run-lifecycle-fir8pr-05--fir8r2-01--fir8r2-06--fir8r3-04--fir8r4-01--fir8r4-02--fir8r4-03); [Full preflight](#full-preflight-mutation-gate-fir8r2-02--fir8r3-03--normative); S1 test matrix |
| **FIR8PR-07 + ops R-8/R-10** small pins | low | [Small pins](#small-pins-fir8pr-07--ops-r-8r-10--fir8r2-); I1 transitional default |
| **FIR8PA-04** ID collision | medium | [ID collision](#id-collision-fir8pa-04); S1 checklist edits scope+epic |
| **FIR8PA-05 / FIR8PA-06** wipe policy & loose ends | low | Option B wiped from implementable path; [Retention](#retention--deletion-delete-by-default); `admin_auth_ok_context` in Terminology |

### Round-2 resolution index (v3)

| Finding | Severity | Resolution anchor in this plan |
| --- | --- | --- |
| **FIR8R2-01** execution mode contradiction + timeout math | high | [I9](#i9-fully-async-run-path-fir8r2-01--non-negotiable); [Execution vehicle](#execution-vehicle--fully-async-fir8r2-01--named); [Timeout arithmetic](#timeout-arithmetic-fir8r2-01--fir8r3-04--fir8r4-02--normative); [Ingest hard-fail](#ingest-hard-fail-threshold-fir8r2-01--fir8r4-04c); S2 tests |
| **FIR8R2-02** mutation gate incomplete | high | [Full preflight mutation gate](#full-preflight-mutation-gate-fir8r2-02--normative); S1 [TEST-15] |
| **FIR8R2-03** prod admin token + client media_url | high | [Baseline delivery option b](#baseline-delivery--option-b-locked-fir8r2-03--fir8r2-05); [Media intake](#media-intake-contract-fir8pr-03--fir8r2-03--normative); Non-goals; R-prod-admin-token / R-client-media-url rejected |
| **FIR8R2-04** data plane not proven distinct | high | [Data-plane isolation proof](#data-plane-isolation-proof-fir8r2-04--normative); S1 acceptance tests |
| **FIR8R2-05** comparison integrity | medium | [Label-free metrics + join key + stamps](#label-free-metrics-contract-fir8pr-04--fir8r2-05); [Truncation rule](#bounded-work-fir8pa-03--ops-r-2--normative); baseline upload in **S3** |
| **FIR8R2-06** lifecycle pins | medium | [Lifecycle pins](#lifecycle-pins-fir8r2-06--fir8r3-01--fir8r3-04--fir8r3-05--fir8r4-0104--normative); concurrency index; purge-always; audit 90d; single `admin_auth_ok_context` |
| **FIR8R2-07** residuals unpinned | medium | [face_metrics](#face_metrics-placement-fir8r2-07); blob `FilesystemObjectStore.put` + scan item fields in media intake; [Residual risks](#residual-risks-fir8r2-07--fir8r3-02--fir8r4-04d--pinned-now) |

### Round-3 resolution index (v4)

| Finding | Severity | Resolution anchor in this plan |
| --- | --- | --- |
| **FIR8R3-01** unique index wrong (`UNIQUE (status)` permits queued+running) | high | [Concurrency — ONE mechanism](#concurrency--one-mechanism-fir8r2-06--fir8r3-01--fir8r4-01); `uq_bench_single_live ON ((1))`; 409 contract; [TEST-15] `test_single_live_index_rejects_queued_while_running` |
| **FIR8R3-02** marker rail fail-open + narrow denylist | high | [Data-plane isolation](#data-plane-isolation-proof-fir8r2-04--fir8r3-02--normative) fail-CLOSED stamp rules; denylist covers every external endpoint; [Residual risks](#residual-risks-fir8r2-07--fir8r3-02--fir8r4-04d--pinned-now) operator-ack for deployment_class + denylist |
| **FIR8R3-03** single blocker bag deadlocks bootstrap | high | [Named blocker sets](#named-blocker-sets-fir8r3-03--split-to-break-bootstrap-deadlock) `BOOT_AUTH_SET` / `RUN_CREATE_SET`; enrollment-while-empty [TEST-15] |
| **FIR8R3-04** non-re-entrant supervisor + timeout only at startup | medium | [Re-entrant supervisor](#re-entrant-supervisor-fir8r3-04--fir8r4-01--fir8r4-02--phase--item-cursor--non-blocking-tick); `phase` + `item_cursor`; timeout every tick; [Timeout arithmetic](#timeout-arithmetic-fir8r2-01--fir8r3-04--fir8r4-02--normative) cold-start floor 1317 → default **1650** |
| **FIR8R3-05** one-clause residual pins | medium | [Small pins](#small-pins-fir8pr-07--ops-r-8r-10--fir8r2---fir8r3-05--fir8r4-): (a) `require_admin_header` only; (b) baseline schema; (c) bench-only audit purge enums; (d) catalog IP pin; (e) S1 Files + schema ownership of `001_identity_schema.py` |

### Round-4 resolution index (v5)

| Finding | Severity | Resolution anchor in this plan |
| --- | --- | --- |
| **FIR8R4-01** purge after terminal / race with single-live | high | [State machine + purge-before-terminal](#run-lifecycle-fir8pr-05--fir8r2-01--fir8r2-06--fir8r3-04--fir8r4-01--fir8r4-02--fir8r4-03); happy path `score → seal → purge → completed` while `running`; failed/cancelled purge via sweeper claiming terminal pending rows; tests: completed ⇒ artifacts gone; no new run while purge pending |
| **FIR8R4-02** blocking tick / poll-until-terminal / timeout clocks | high | [Non-blocking tick contract](#non-blocking-tick-contract-fir8r4-02--normative); one bounded step per tick; production-job interleave [TEST-15]; claimed timeout from `started_at` + `RECOGNITION_BENCH_QUEUED_TIMEOUT_SEC`; [Timeout arithmetic](#timeout-arithmetic-fir8r2-01--fir8r3-04--fir8r4-02--normative) `N_PHASES=7` floor **1317** → **1650** |
| **FIR8R4-03** runtime gates missing mid-run / stamp races | high | Tick preamble re-evals `BOOT_AUTH_SET` ([Each tick](#each-tick-steady-state-reclaimer-discipline--release-it--ddia-distilled)); claim/resume profile+dim re-verify; marker [first-stamp idempotency](#first-boot-deployment_class-marker-fail-closed--fir8r3-02--fir8r4-03c--fir8r4-04a) `ON CONFLICT DO NOTHING` + read-back; concurrent-stamper test |
| **FIR8R4-04** residual pins underspecified | medium | Production-shaped four-table set (FIR8R4-04a) in [marker section](#first-boot-deployment_class-marker-fail-closed--fir8r3-02--fir8r4-03c--fir8r4-04a); baseline media_id **superset** (FIR8R4-04b) in `RUN_CREATE_SET`; durable per-item ingest outcomes (FIR8R4-04c); DNS **pinned address set** + public-unicast / private-source residual (FIR8R4-04d); [Lifecycle pins](#lifecycle-pins-fir8r2-06--fir8r3-01--fir8r3-04--fir8r3-05--fir8r4-0104--normative); [Residual risks](#residual-risks-fir8r2-07--fir8r3-02--fir8r4-04d--pinned-now) |

### Invariants preserved from v1 (must survive all plan revs)

- Single dedicated-bench isolation track (no Option B / dual-dim).
- Boot-coupled license gate (flag alone insufficient).
- Operator principal on recognition `/admin` (not WP `manage_options`).
- Label-free metrics with honest nulls for label-dependent frames.
- Non-goals: no WP control path, no Golden-150 re-host, no third profile, no production scan_worker bench compute, no commercial buffalo product path.
- Reuse `build_embedding_runtime`; no scan_worker fork; rg-015 envelope honesty; greenfield `001_identity_schema.py`; [DIAG-08] complementarity.
