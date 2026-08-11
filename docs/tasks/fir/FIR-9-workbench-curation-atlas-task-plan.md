# FIR-9. Workbench UMAP Curation Atlas + Uncertainty Queues

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok 4.5 (xAI)
> - **Project**: `apps/prototype-description-service` + `apps/prototype-wp-alt-context`
> - **Task ID**: `FIR-9`
> - **Plan version**: `v3`
> - **Target Branch**: `feature/fir-9`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md) (`Epic Short ID`: FIR)
> - **Depends on**: live cluster + member embeddings with `embedding_model` provenance (FIR-2/FIR-4 path); Workbench mutation surfaces (`useClusterMutations`, `ClusterReviewPanel`) already shipping
> - **Review Coverage Target**: 2 _(intent only; live coverage via handoff DB — never paste findings here)_
> - **Changelog**: **v3** — Workbench placement rationale (NAV-05/VIZ-15/NAV-06) + S3 Roster-coordination lens (assignment color + Needs-assignment deep-link). **v2** — disposition schema + single write route; non-vacuous EMB-01 guard; deterministic build-time queue; thumb-join lifecycle; envelope/path pins (FIR9R1-01..08).

## Objective

Ship a **DIAGNOSTIC-only** curation-acceleration tool in two halves: (1) an admin Workbench **2-D UMAP face atlas** (zoomable thumbnail scatter colored by `cluster_id`) for spotting bad merges/splits/outliers at a glance; (2) **HIGH-D uncertainty-ranked curation queues** (pgvector cosines) that order what a human reviews first. Projection coords and plots **never** gate or mutate identity state — all mutations continue through existing Workbench mutation APIs. Runs on the A1.Flex **CPU** box (no GPU; batch UMAP only).

## Placement rationale (heuristic-validated)

Operator proposal: host the atlas on the Roster page. **Canon validation keeps it in Workbench** — handoff decision `fir9_atlas_placement_workbench_validated_20260723` (#3240). Grounds:

- **NAV-05 (MECE single-home).** E21-9 retired Roster’s Clusters tab to enforce the E21-10 contract: **Workbench decides [clusters], Roster curates [people]**. A cluster-inspection atlas on Roster re-opens that dual-home (two surfaces for the same cluster-topology inspection job).
- **VIZ-15 (Munzner Ch12.3; distilled `visualization-analysis-design-munzner.md`).** The atlas is the **OVERVIEW** view and must share encoding + linked highlighting with the **DETAIL** surface where selection acts. There are two selection destinations, both read-only from the atlas's side: the **primary** detail surface is the workbench/identity-clusters review queue (`rq=` flows, merge/label mutations via `ClusterReviewPanel` / `useClusterMutations`); the **secondary** destination is the Roster Needs-assignment rail for unlabeled/auto-labeled points (S3 lens deep-link) — a navigation hand-off, not a second cluster-curation home (NAV-05 holds: cluster mutations remain exclusively in the queue).
- **NAV-06.** The frequent task the atlas serves is **cluster triage** (bad merges/splits/outliers → act in the review queue), not person-record curation.

Concession without moving homes: S3 **Roster-coordination lens** (person-assignment color + Needs-assignment deep-links) — see Slice 3.

## Intake

- **Scope lineage**: E22/FIR follow-on for operator curation acceleration after commercial face stack work (FIR-2…FIR-5). Not in the original P1–P4 table; this plan is the task definition.
- **Architecture is pre-decided** (do not re-litigate UMAP vs t-SNE, ParametricUMAP, or embedding-over-HTTP): batch server-side atlas job + relational atlas artifacts + admin/tenant read GETs + Workbench canvas scatter + HIGH-D queue mix.
- **Not-Doing**: ParametricUMAP / TensorFlow; GPU path; embedding vectors over HTTP; new cluster mutation APIs; eval-harness coupling; FiftyOne service integration; UI-triggered atlas build in v1 (CLI only — see S1/S3); changing Golden-150 sealed eval registration/freeze discipline.

## Problem Statement

Operators curate merges/splits via Workbench review queues without a global geometric overview of the tenant’s face embedding space, and without a principled **HIGH-D** ordering of which faces are most uncertain. Ad-hoc cosine scripts (`scripts/utilities/compare_media_embeddings.py`) and existing suggestion bands help locally but do not produce a shareable atlas run, pinned projection params, or an AUDIT-13-visible queue completion report. FIR-6’s model flip will change `embedding_model`; any projection tooling must refuse multi-model runs (**EMB-01**).

## Constraints

- **DIAGNOSTIC-only doctrine**: 2-D UMAP distances/sizes/densities are **not** similarity evidence (distill.pub *How to Use t-SNE Effectively* misread-tsne class of errors; Nature Methods Primer 2024 on dimensionality-reduction display — cite as in QA v4 §17). Atlas never gates accept/reject/merge. Params + package versions pinned on every stored run.
- **CAL-11 (quality gate, not decoration)**: the HIGH-D uncertainty queue **is** the below-threshold **route-to-human** action. It is not a decorative side panel — it is the primary ordered worklist that feeds existing review surfaces.
- **EVAL-10**: Golden-150 sealed eval split is **never read or altered by this tooling**. If the atlas accelerates Golden-150 **labeling**, labeling may use the full corpus view; sealed eval registration/freeze discipline (owned by the eval harness / VLM-6 + FIR-5 coordination) is out of scope and remains untouched.
- **MLDATA-03/04**: labels applied after queue review keep lineage (who/when/what source). Existing mutation paths already write `audit_events` (`db/models/observability.py:AuditEvent`, table `audit_events` in `001_identity_schema.py`). **This task adds no new label-write path.** Labels flow only through the existing cluster mutation APIs; the atlas disposition POST is queue bookkeeping only (no label semantics).
- **AUDIT-13**: queue completion is reported (`reviewed` / `skipped` / `remaining` per atlas run) by reading `identity_atlas_queue_dispositions` so nonresponse is visible, not silently replaced.
- **EMB-01**: one atlas run = one `(tenant_id, embedding_model)` pair. Never mix models in one projection. After FIR-6 flip, prior-model runs remain listable and marked `stale` relative to the active model (computed at **list** time — no background job).
- **Multi-tenancy**: artifacts tenant-scoped; batch job uses admin-session BYPASS pattern with **explicit** `--tenant-id`; HTTP filters by tenant.
- **Privacy**: HTTP serves coords + cluster ids + thumb refs only — **no raw embeddings**. Atlas data is biometric-adjacent derived state; same retention/purge story as clusters.
- **CPU / ARM**: `umap-learn` (BSD-3) + numba/llvmlite via optional `[atlas]` extra; aarch64 wheel smoke required; **no TensorFlow**.
- **Greenfield schema** (repo policy): additive tables land in `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` (sole revision today — do **not** invent a parallel data-migration story). Also mirror ORM models + `TENANT_TABLES` / RLS / purge hooks.
- **rg-015**: envelope fields (`limit`, `offset`, `total`, provenance) come from the request or stored artifact — never invent pagination from `len(points)`.
- **sr-004 / sr-005 / sr-007 / rg-003**: design tokens, assertion helpers for invariants, backed enums for status strings, primary controls reachable from empty state.

## Workflow Principles

1. **Projection is display; HIGH-D is decision support.** UMAP for eyes; cosines for queue ranks.
2. **Reuse seams, do not fork mutation paths.** Click-through → existing `ClusterReviewPanel` + `useClusterMutations`.
3. **Pin reproducibility knobs on the run row** (`params` JSON: umap hyperparams, package versions, `random_state`, score recipe version, MV refresh timestamp).
4. **Operator-CLI builds runs in v1**; UI is read/navigate only for atlas build triggering.
5. **Single write route**: the only atlas-owned mutation is `POST …/dispositions` (queue bookkeeping). Everything else is GET or existing cluster mutations.

## Terminology

- **Atlas run**: one persisted projection + score artifact for a single `(tenant_id, embedding_model)` with backed `status` ∈ {`building`, `complete`, `failed`}.
- **Atlas point**: one face/identity row with `(x, y)` display coords, HIGH-D `uncertainty` JSON, and build-time `queue_rank` — never the raw vector.
- **Stale run**: run whose **`(embedding_model, cv_runtime_version)`** ≠ the current pair — active model id (`active_embedding_model_id()` in `recognition/application/embedding/manifest.py:71`) **and** the OpenCV major version the embeddings were produced under. Computed at list time; no background job. <span>**Amended 2026-07-28 (QA v8 re-gate):** keying on `embedding_model` alone marks a pre-CVUP-1 run FRESH, because CVUP-1 (OpenCV 4.x → 5.x) changes the embeddings without changing the model id. That also silently carries the `similarity_threshold` / `suggestion_floor` bands across the upgrade boundary, where they are not valid. This plan version-pins the projection stack (`umap-learn`, `numba`, `llvmlite`) and must equally pin the embedding-producing stack — add `cv_runtime_version` to the run-row `params` JSON next to the umap hyperparameters.</span>
- **Queue mix**: ordered list = uncertainty slice + diversity slice + random calibration slice (HITL active-learning practice), **materialized at build time** into `queue_rank`.
- **Disposition**: `reviewed` | `skipped` row in `identity_atlas_queue_dispositions` (AUDIT-13 bookkeeping only).
- **DIAGNOSTIC display**: UI that must not drive automated accept/merge thresholds.

## Current State Analysis

| Surface | Verified anchor | Gap for FIR-9 |
| --- | --- | --- |
| Member/rep embeddings | `SqlAlchemyClusterRepository.get_member_embeddings` / `get_representative_embeddings` (`cluster_repository.py:890–921`); silently majority-filters via `_filter_embedding_pairs_to_single_model` (`cluster_repository.py:59–72`) | No cross-cluster bulk export for UMAP; methods are per-`cluster_id`. **Atlas EMB-01 must not reuse the silent majority filter** — use a separate fail-closed COUNT/EXISTS guard |
| Centroids | `refresh_centroids_view` / `refresh_centroids_view_concurrent` (`cluster_repository.py:495`, `:580`); MV `mv_identity_cluster_centroids` (see `compare_media_embeddings.py:70`) | Need tenant-filtered MV read + mean-of-reps fallback; job records MV refresh timestamp, does not refresh per-tenant |
| Thumb projection | module-private `_face_thumb_url_for_identity` (`clusters_snapshot.py:77–86`) → public `build_face_thumb_path` (`blob_url.py:76`) | Extract a **shared** thumb-projection helper that wraps `build_face_thumb_path`; snapshot + atlas both call it — never import `_face_thumb_*` across routers |
| Admin HTTP | `admin_router` + `Depends(require_admin)` (`admin.py:148`); `get_admin_session` + `enable_rls_bypass` (`admin.py:67–89`); mount when `security_settings.admin_enabled` (`api/main.py:225–233`) | No atlas routes |
| Tenant assert | `assert_tenant_match` (`clusters_common.py:13`) | Needed on **tenant** read surface for Workbench |
| Workbench mutations | `useClusterMutations` (`identity-clusters/useClusterMutations.ts:37`); `ClusterReviewPanel` (`ClusterReviewPanel.tsx`); review queue driver (`reviewQueueDriver.ts`) | No atlas tab; `TAB_IDS` is scan-only (`WorkbenchNavContext.tsx:9–11`) |
| Deep-links | `APP_LINK_PARAMS` / `APP_LINK_VALUES` (`js/admin/navigation/appLinks.ts`); filter/queue URL state via `useWorkbenchFilters.ts` | Atlas deep-links must reuse these — not invent a parallel URL codec |
| Thumb UI | `FaceThumbnail` (`js/components/ui/FaceThumbnail.tsx`) | Atlas hover/zoom should reuse |
| Schema / purge | `001_identity_schema.py` + `TenantPurgeService._delete_dependency_rows` (`purge_service.py:195–261`); `TENANT_TABLES` list | No atlas tables; purge plan must gain rows |
| Optional deps | `pyproject.toml` `[project.optional-dependencies]` (`bench`, `gpu`, `vlm`, …) — no `[atlas]` | Add pinned umap-learn/numba/llvmlite |
| HITL distilled (repo) | `literature/extracted/business/distilled/building-ml-powered-applications.md` (active strategies: uncertainty + random sample test set — ch-4 ~L174); `designing-ai-interfaces.md` (HITL / annotation HCI defaults) | Brief name `human-in-the-loop-ml.md` is **not** present; cite these grounded distillations |

## Target Outcome

1. Operator runs `python -m scripts.atlas.build_atlas --tenant-id <uuid> --embedding-model <id>` on the A1 box (with `[atlas]` extra), producing a deterministic (pinned `random_state`) atlas run + points with `queue_rank` + HIGH-D scores.
2. Admin curl and Workbench (tenant auth) can **list runs**, **page points**, and **fetch the queue** without receiving embeddings; completion stats come from dispositions.
3. Workbench atlas page: plain Canvas2D scatter (no new FE dependency), pan/zoom, color-by-cluster, `FaceThumbnail` on hover/zoom-threshold, click → existing cluster review/mutation flow. Zero-state explains CLI build (no UI trigger in v1).
4. Queue mix surfaces as advisory ordering; disposition POST is the only atlas write; labels only via existing cluster mutation APIs; AUDIT-13 from dispositions table.
5. Runbook documents the operator loop; FiftyOne is optional **operator-local** for Golden-150 only — not integrated.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/testing-typescript.md`
- Epic: `docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md`
- Distilled HITL: `literature/extracted/business/distilled/building-ml-powered-applications.md`, `literature/extracted/business/distilled/designing-ai-interfaces.md`
- Pattern sources: `recognition/interface_adapters/http/routers/admin.py`, `clusters_snapshot.py`, `clusters_common.py`, `db/tenant_context.py` (`enable_rls_bypass`)
- Handoff: task ref `FIR-9`; findings live only in MCP

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility? | Verification |
| --- | --- | --- | --- | --- | --- |
| Admin HTTP `/admin` | backend | `admin_router` + `require_admin` (`admin.py`, `admin_auth.py`) | Admin GETs for runs/points/queue **+ one admin POST** (`…/dispositions`) for queue bookkeeping only | Additive | API tests (auth 401, happy path); spy that disposition never calls cluster mutations |
| Recognition HTTP `/recognition` | backend | tenant `require_auth` cluster routes | New tenant-scoped atlas **read** GETs (Workbench path); tenant disposition POST (required for the Workbench queue surface) with same bookkeeping-only semantics | Additive; same artifact as admin | `assert_tenant_match` tests |
| WP Workbench SPA | frontend | `TAB_IDS.scan` only | New `atlas` tab + API client + Canvas2D scatter | Additive URL `?tab=atlas` | component tests; mutation spy: no cluster-mutation calls; disposition POST expected |
| DB schema | backend | `001_identity_schema.py` | `identity_atlas_runs` + `identity_atlas_points` + `identity_atlas_queue_dispositions` + RLS + purge | Additive greenfield | schema verify + cascade unit tests |
| Optional Python extra | backend | `pyproject.toml` extras | `[atlas]` | Opt-in install | aarch64 smoke |
| Mutations | FE/BE existing | cluster rename/merge/split/reassign | **None new for labels** — disposition POST is queue bookkeeping only | n/a | S3: spy asserts **no** cluster-mutation calls; disposition POST is the expected atlas write |

**Boundary sentence (normative):** Admin GETs (runs, points, queue) plus **one** admin POST (`/admin/atlas/runs/{run_id}/dispositions`) own atlas I/O; that POST is queue bookkeeping only — no label semantics; labels flow only through the existing cluster mutation APIs.

### HTTP dual-surface decision (required for Workbench)

Workbench talks to recognition via **tenant API key** (WP proxy) — it never holds `RECOGNITION_ADMIN_TOKEN` (`admin_auth.py` is deliberately separate from tenant auth). Therefore:

- **S2a**: `admin_atlas_router` under `/admin` with `Depends(require_admin)` + `get_admin_session` (ops/curl/runbook; matches brief pattern).
- **S2b**: same handlers mounted under `/recognition/atlas/...` with `require_auth` + `assert_tenant_match(auth, tenant_id)` for Workbench.
- Shared pure read functions; **no** raw vectors; identical response envelopes.

## Proposed Solution

### 1. Batch atlas job — `apps/prototype-description-service/scripts/atlas/build_atlas.py`

**Entrypoint**: CLI module (new package dir `scripts/atlas/`).

**Session**: open DB like admin — `async_session_factory` + `enable_rls_bypass` (`db/tenant_context.py:109–123`) with **required** `--tenant-id`. Pattern comment must mirror `admin.get_admin_session` (`admin.py:67–89`) and the script pattern in `scripts/utilities/compare_media_embeddings.py:78` (`SET LOCAL app.bypass_rls`).

**Read path** (no new embedding HTTP):

1. Resolve clusters for tenant via `SqlAlchemyClusterRepository.get_snapshot(tenant_id)` (`cluster_repository.py:1318`).
2. Dedicated `AtlasRepository.iter_tenant_embeddings(tenant_id, embedding_model)` returning `(identity_id, media_id, cluster_id, embedding)` filtered to the requested model at the SQL boundary (not a silent majority filter on `SqlAlchemyClusterRepository`).
3. **EMB-01 guard (non-vacuous, fail-closed)** — separate from the silent majority filter:
   - Before UMAP, run a dedicated `COUNT`/`EXISTS` over tenant rows where `embedding IS NOT NULL AND embedding_model != :requested`.
   - If any such row exists → **fail closed** with an explicit error naming the foreign model(s).
   - Escape hatch: `--allow-partial` (documented in CLI flag table and runbook) proceeds using only rows whose `embedding_model = :requested`; still never mixes models in one fit.
   - **Must not** call or reuse `_filter_embedding_pairs_to_single_model` (`cluster_repository.py:59–72`), which keeps the majority model silently — that would make the guard vacuous.
   - **Unit test (must be able to go RED)**: inject a mixed-model fixture; assert the job fails without `--allow-partial`. Mutating the guard to reuse the majority filter (or to skip the COUNT) turns the assertion red.

**Centroid read path (S1)**:

- `AtlasRepository` read over `mv_identity_cluster_centroids` filtered by `tenant_id`, returning `(cluster_id, centroid)`.
- Fallback: mean-of-representatives when the MV lacks a given cluster.
- `refresh_centroids_view` is **GLOBAL** (`cluster_repository.py:495`) — the atlas job does **not** refresh per-tenant. Optional CLI `--refresh-centroids` may call the global refresh once before the read; regardless, the job reads **current** MV state and records the MV refresh timestamp into `params["centroids_mv_refreshed_at"]`. Default is read-current without forcing a refresh.

**UMAP** (optional import from `[atlas]` extra):

- `umap.UMAP(metric="cosine", n_neighbors∈[15,30], min_dist∈[0.05,0.1], random_state=<int>, n_components=2)`
- Optional secondary run with `densmap=True` stored as alternate params only if flag set (default off for v1 determinism budget).
- Pin versions of `umap-learn`, `numba`, `llvmlite` in `pyproject.toml` and record them in `params["package_versions"]`.

**HIGH-D uncertainty scores** (never from 2-D distances) per identity/face — pinned formulas:

| Signal | Formula / definition | Role |
| --- | --- | --- |
| `margin` | `cos(x, c_nearest) − cos(x, c_second)` | Primary rank key |
| `uncertainty_rank` | ascending `margin` (smallest margin = highest priority) | Ordering input |
| `intra_cluster_percentile` | percentile of the point’s cosine-to-own-centroid within the **per-cluster** cosine-to-centroid distribution | Secondary score in `uncertainty` JSON |
| `near_threshold` | `\|cos − similarity_threshold\| < ε` (`ClusteringSettings.similarity_threshold` and related band fields in `recognition/application/settings/clustering.py (symbols: `ClusteringSettings.similarity_threshold` / `suggestion_floor` / `suggestion_ceiling`)`) | **DIAGNOSTIC display flag only — EXCLUDED from ranking** |

Centroids source: MV read + mean-of-reps fallback (above). Threshold fields: `ClusteringSettings` in `recognition/application/settings/clustering.py (symbols: `ClusteringSettings.similarity_threshold` / `suggestion_floor` / `suggestion_ceiling`)` (`similarity_threshold`, `suggestion_floor`, `suggestion_ceiling`, …).

**Deterministic build-time queue** (pinned):

- **Mix**: 60% uncertainty (ascending margin) / 20% diversity (farthest-first among remaining) / 20% random calibration.
- Every stochastic step is seeded from the run’s pinned `random_state` / seed in `params`.
- Computed **at build time** into `identity_atlas_points.queue_rank` (integer column on points). Endpoints **never recompute** rank — they `ORDER BY queue_rank`.
- Cite: `building-ml-powered-applications.md` active data strategies; `designing-ai-interfaces.md` HITL control points (queue is advisory, human decides).
- **Unit test**: same fixtures + same seed ⇒ identical `queue_rank` sequence (bit-stable ordering of identity ids).

**CLI flags (normative)**:

```text
--tenant-id UUID                 # required
--embedding-model STR            # required; EMB-01 scope
--n-neighbors INT                # default 15
--min-dist FLOAT                 # default 0.1
--random-state INT               # default 42; seeds UMAP + queue stochastic steps
--densmap / --no-densmap         # default off
--refresh-centroids              # optional; calls global refresh_centroids_view once
--allow-partial                  # EMB-01 escape: use only matching-model rows; document in runbook
--dry-run                        # resolve + score + rank without persisting; print counts
```

S1 proof cites `--dry-run` (mocked repo or fixture DB returns planned `point_count` without write).

### 2. Persistence — **three tables** (chosen)

**Justification (one sentence):** Relational `identity_atlas_runs` + `identity_atlas_points` + `identity_atlas_queue_dispositions` enable paginated point GETs, build-time `queue_rank`, AUDIT-13 completion from disposition rows, and FK-cascade purge without loading a monolithic JSONB blob per page (rg-015-friendly `total` from SQL `COUNT`).

```text
identity_atlas_runs
  id UUID PK
  tenant_id UUID NOT NULL  → tenants(id) ON DELETE CASCADE
  embedding_model TEXT NOT NULL
  status TEXT NOT NULL            # backed enum: building | complete | failed (sr-007)
  params JSONB NOT NULL          # umap knobs, package_versions, score_recipe, random_state,
                                 # centroids_mv_refreshed_at
  point_count INT NOT NULL
  created_at TIMESTAMPTZ NOT NULL
  # NOTE: no reviewed_count/skipped_count columns — AUDIT-13 reads dispositions table

identity_atlas_points
  id UUID PK
  run_id UUID NOT NULL → identity_atlas_runs(id) ON DELETE CASCADE
  tenant_id UUID NOT NULL        # denormalized for RLS; → tenants(id) ON DELETE CASCADE
  identity_id UUID NOT NULL → media_identities(id) ON DELETE CASCADE
  media_id INTEGER NOT NULL      # matches media_identities.media_id (db/models/identity.py:49)
  cluster_id UUID NULL
  x FLOAT NOT NULL
  y FLOAT NOT NULL
  queue_rank INT NOT NULL         # build-time deterministic order; endpoints never recompute
  uncertainty JSONB NOT NULL     # margin, intra_cluster_percentile, near_threshold flag, composite
  UNIQUE(run_id, identity_id)
  INDEX (run_id, queue_rank)

identity_atlas_queue_dispositions
  id UUID PK
  run_id UUID NOT NULL → identity_atlas_runs(id) ON DELETE CASCADE
  point_id UUID NOT NULL → identity_atlas_points(id) ON DELETE CASCADE
  tenant_id UUID NOT NULL → tenants(id) ON DELETE CASCADE
  action TEXT NOT NULL           # backed enum: reviewed | skipped
  actor TEXT NOT NULL            # admin/tenant principal id string
  created_at TIMESTAMPTZ NOT NULL
  UNIQUE(run_id, point_id)       # one disposition per point per run; reject duplicate on conflict
```

- All three tables: FK `tenant_id → tenants(id) ON DELETE CASCADE` like siblings; added to `TENANT_TABLES` + RLS policies in `001_identity_schema.py` (same pattern as other identity tables).
- ORM models under `db/models/` (new atlas module); export from `db/models/__init__.py`.
- **Purge**: atlas tables FK `tenants.id ON DELETE CASCADE` like siblings **and** added to `TenantPurgeService` `delete_plan` (`purge_service.py:195–261`) so purge counts include them (belt-and-suspenders: explicit delete rows + FK cascade).
- **Cascade test**: delete a `media_identities` row → corresponding `identity_atlas_points` (and their dispositions) drop via `ON DELETE CASCADE`.

### 3. Admin + tenant routers — paths and envelopes pinned (rg-015)

**New file**: `recognition/interface_adapters/http/routers/admin_atlas.py`

```python
admin_atlas_router = APIRouter(
    tags=["admin-atlas"],
    dependencies=[Depends(require_admin)],
)
```

**Mount** in `api/main.py` inside `if security_settings.admin_enabled:` **alongside** existing `admin_router` (do not break `assert_admin_env_dsn` / `validate_admin_config` order).

**Pinned admin routes** (exact paths):

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/admin/atlas/runs` | List runs newest-first; envelope below; `stale` computed at list time |
| GET | `/admin/atlas/runs/{run_id}/points` | Paginated points; JOIN for thumbs |
| GET | `/admin/atlas/runs/{run_id}/queue` | Items ordered by stored `queue_rank`; completion from dispositions |
| POST | `/admin/atlas/runs/{run_id}/dispositions` | **Single write route** — insert disposition (`reviewed` \| `skipped`); queue bookkeeping only; uses `require_admin_header` (admin.py mutation rule) |

Tenant query: admin list/points/queue take `tenant_id` as **required query param** (path stays as pinned; no `{tenant_id}` segment).

**Pinned response envelopes** (rg-015 — never fabricate totals from `len`):

```text
# GET /admin/atlas/runs
{
  items: [
    {
      run_id,
      embedding_model,
      status,              # building | complete | failed (schema-backed)
      params,
      point_count,
      created_at,
      stale                 # run.embedding_model != active_embedding_model_id()  (manifest.py:71)
    }
  ],
  active_embedding_model   # from active_embedding_model_id()
}

# GET /admin/atlas/runs/{run_id}/points
{
  items: [ { identity_id, media_id, cluster_id, x, y, uncertainty, queue_rank, thumb_url, cluster_label, is_auto_label } ],  # cluster_label/is_auto_label feed the S3 assignment lens (fields verified in ClusterMemberResponse, responses.py:52-53)
  limit,                   # from request
  offset,                  # from request
  total                    # SQL COUNT(*) — never len(items)
}

# GET /admin/atlas/runs/{run_id}/queue
{
  items: [ … ordered by queue_rank … ],   # from stored column; no recompute
  completion: {
    reviewed,              # COUNT dispositions where action=reviewed
    skipped,               # COUNT dispositions where action=skipped
    remaining              # COUNT points with no disposition row for this run
  }
}
```

**Thumb lifecycle on points GET**:

- Endpoint performs a `media_identities` JOIN for `media_url` + bbox columns (`bbox_x/y/width/height`).
- Thumb URL via a **shared** thumb-projection helper extracted from the snapshot path; the helper wraps `build_face_thumb_path` (`interface_adapters/http/blob_url.py:76`). Do **not** import module-private `_face_thumb_url_for_identity` across routers.
- **Never** include `embedding` in the payload.

**Tenant mirror** (Workbench): same relative paths under `/recognition/atlas/...` (`/recognition/atlas/runs`, `…/runs/{run_id}/points`, `…/runs/{run_id}/queue`, `POST …/dispositions`) with `require_auth` + `assert_tenant_match`. Disposition mutation on tenant surface still only touches disposition rows, not clusters.

**Stale marking**: computed at **LIST** time only — `run.embedding_model != active_embedding_model_id()` (`manifest.py:71`). No background job. UI renders a stale badge with **color + icon** (sr-004).

### 4. Workbench UI — `apps/prototype-wp-alt-context/js/admin/pages/workbench/`

| New / changed | Role |
| --- | --- |
| `AtlasPage.tsx` container + `atlas/AtlasScatter.tsx` | **Plain Canvas2D** scatter (no new FE dependency); pan/zoom; color by `cluster_id` using `--acx-*` tokens (sr-004); stale badge = color **+** icon |
| `atlas/useAtlasRuns.ts`, `atlas/useAtlasPoints.ts`, `atlas/useAtlasQueue.ts` | React Query; keys under `queryKeys.atlas.*` (extend `api/queryKeys.ts`) |
| `atlas/atlasApi.ts` | Tenant recognition endpoints mirroring pinned paths (`/recognition/atlas/runs`, `…/points`, `…/queue`, `POST …/dispositions`) |
| `atlas/atlasTypes.ts` | Response types; boundary validation (no assertion helpers for API data — sr-005); `ATLAS_RUN_STATUS = { building, complete, failed } as const` mirroring schema-backed enum (sr-007) — **no invented FE-only status values**; `QUEUE_DISPOSITION_ACTION = { reviewed, skipped } as const` |
| `WorkbenchNavContext.tsx` | Add `TAB_IDS.atlas = 'atlas'`; allowlist in `useTabParam` |
| Wire into workbench shell | Render `AtlasPage` when `tab=atlas` |
| Click-through | Opens existing cluster detail / `ClusterReviewPanel` — **no** atlas-local label mutations; reuse `useClusterMutations` only inside existing panels |

**Zero-state (rg-003)**: when `runs.length === 0`, show primary copy + **operator instructions** to run the CLI (`build_atlas …`). **No “Build run” button that POSTs a job in v1** — run triggering stays operator-CLI (S1). Stretch: later slice may add admin-triggered job.

**Queue surface**: show HIGH-D ordered list (from GET queue, already ranked) beside/under scatter; “Open in review” deep-links reuse `js/admin/navigation/appLinks.ts` (`APP_LINK_PARAMS` / `APP_LINK_VALUES`) + `js/admin/hooks/useWorkbenchFilters.ts` and existing `reviewQueueDriver.ts` — without inventing a second mutation stack. Disposition buttons call the counters-only dispositions POST (AUDIT-13).

**S3 test contract**: component tests spy that Atlas page makes **no** cluster-mutation API calls; the disposition POST **is** expected when the operator marks reviewed/skipped.

### 5. Ops — `[atlas]` extra

In `apps/prototype-description-service/pyproject.toml`:

```toml
atlas = [
  "umap-learn==<pin>",
  "numba==<pin>",
  "llvmlite==<pin>",
]
```

- Smoke: import umap on aarch64 in CI or documented operator check; fail with clear InstallError if extra missing when job runs.
- No tensorflow; ParametricUMAP out of scope.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend job | `scripts/atlas/build_atlas.py` (+ `__init__.py`, scoring + queue-rank helpers) | NEW batch builder; EMB-01 COUNT guard; build-time `queue_rank` |
| backend repo | `recognition/infrastructure/repositories/atlas_repository.py` (new) | NEW `iter_tenant_embeddings`; NEW centroid MV read + mean-of-reps fallback |
| schema | `db/migrations/versions/001_identity_schema.py` | three atlas tables + RLS + TENANT_TABLES + status/action check constraints |
| models | `db/models/` (new atlas models) + `__init__.py` | ORM; `media_id: Integer`; FKs as above |
| purge | `recognition/application/services/purge_service.py` | delete_plan entries for atlas tables |
| thumb helper | extract shared helper next to `blob_url.py` / clusters snapshot | shared projection used by snapshot + atlas |
| admin HTTP | `recognition/interface_adapters/http/routers/admin_atlas.py` | NEW — pinned paths |
| tenant HTTP | same `admin_atlas.py` module (tenant router factory) | tenant GETs + disposition |
| app mount | `api/main.py` | include routers |
| deps | `pyproject.toml` | `[atlas]` extra |
| FE page | `js/admin/pages/workbench/atlas/*` | NEW Canvas2D scatter + hooks |
| FE nav | `WorkbenchNavContext.tsx`, workbench shell | `tab=atlas` |
| FE api | `js/admin/api/queryKeys.ts`, `atlasApi.ts` | keys + client mirroring pinned paths |
| FE deep-links | `appLinks.ts`, `useWorkbenchFilters.ts`, `reviewQueueDriver.ts` | reuse only |
| tests | `recognition/tests/...`, `js/admin/pages/workbench/atlas/__tests__/*` | unit/API/component including cascade + EMB-01 RED + queue_rank determinism |
| docs | `docs/runbooks/workbench-curation-atlas.md` | S4 operator runbook |

## Related Files

| File | Note |
| --- | --- |
| `recognition/interface_adapters/http/blob_url.py` | `build_face_thumb_path` (L76) — shared thumb projection |
| `recognition/interface_adapters/http/routers/clusters_snapshot.py` | private thumb helper to extract/share from |
| `recognition/interface_adapters/http/routers/admin.py` | admin session + auth pattern |
| `recognition/interface_adapters/http/deps/admin_auth.py` | `require_admin`, `require_admin_header` |
| `recognition/application/embedding/manifest.py` | `active_embedding_model_id()` L71 — stale + envelope |
| `recognition/application/settings/clustering.py` | `ClusteringSettings` threshold fields L191–278 |
| `recognition/infrastructure/repositories/cluster_repository.py` | `_filter_embedding_pairs_to_single_model` L59 (do **not** reuse); `refresh_centroids_view` L495 (global) |
| `db/models/identity.py` | `media_id: Integer` L49; `MediaIdentity.id` FK target |
| `recognition/application/services/purge_service.py` | `delete_plan` L195–261 |
| `js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx` | click-through target |
| `js/admin/pages/workbench/identity-clusters/useClusterMutations.ts` | sole label/mutation path |
| `js/admin/pages/workbench/identity-clusters/reviewQueueDriver.ts` | review queue driver (stays) |
| `js/admin/navigation/appLinks.ts` | `APP_LINK_PARAMS` / `APP_LINK_VALUES` deep-link contract |
| `js/admin/hooks/useWorkbenchFilters.ts` | workbench URL filter/queue state |
| `js/components/ui/FaceThumbnail.tsx` | hover thumbs |
| `scripts/utilities/compare_media_embeddings.py` | BYPASSRLS script precedent |
| `literature/extracted/business/distilled/building-ml-powered-applications.md` | uncertainty + random sampling |
| `literature/extracted/business/distilled/designing-ai-interfaces.md` | HITL / annotation HCI |

## Verification Strategy

- **Deterministic pytest (job/scores/schema)**:
  - Fixture embeddings → UMAP with fixed `random_state` → coords within tight tolerance (or hash of rounded coords).
  - EMB-01 non-vacuous: mixed `embedding_model` rows → job raises before fit; test can go RED if guard is removed or replaced with majority-filter. With `--allow-partial`, only matching-model rows are used.
  - Score unit tests: margin / intra-cluster percentile / near_threshold **flag** (excluded from rank) on hand-built vectors (no umap required).
  - Queue: same fixtures + seed ⇒ identical `queue_rank` ordering.
  - Schema: insert run+points+dispositions; cascade delete of `media_identities` drops points; RLS tenant isolation if suite supports it.
- **API tests**:
  - Pattern-match `recognition/tests/api/test_admin_router.py` / `test_admin_auth.py`: missing admin token → 401; valid token → 200.
  - Tenant mirror: wrong tenant → 403 via `assert_tenant_match`; envelope `total` matches DB count (rg-015).
  - Response JSON never contains embedding arrays (negative assertion).
  - Disposition POST increments completion counters derived from the dispositions table; never calls cluster mutation services.
  - Stale flag: list marks run stale when model ≠ `active_embedding_model_id()`.
- **Frontend**: `npm test` for zero-state, Canvas2D scatter props from fixture points, **mutation spy: no cluster-mutation calls**; disposition POST expected; stale badge color+icon; token classes present; `ATLAS_RUN_STATUS` matches schema enum only.
- **aarch64 smoke**: import `umap` with `[atlas]` installed (document command; run on A1 or CI arm where available).
- **Gate**: `make check-remote` per slice close.
- **Explicit non-coupling**: no imports from `scripts/eval_harness/`; sealed eval split never read or altered; no Golden-150 freeze edits.

## Slice Delivery

### Slice 1: Batch job + schema + HIGH-D scores + unit tests

**Goal**: Operator can build a deterministic atlas run artifact for one `(tenant, embedding_model)` on CPU.

Changes:

- Additive schema (three tables) + ORM + TENANT_TABLES/RLS + purge plan entries + identity CASCADE on points.
- Centroid MV repository read + mean-of-reps fallback; record MV refresh timestamp in params.
- `scripts/atlas/` builder + scoring module + non-vacuous EMB-01 COUNT/EXISTS guard + `--allow-partial` + `--dry-run`.
- Build-time queue mix (60/20/20) written to `queue_rank`.
- `[atlas]` extra pins.
- Unit tests: deterministic coords; EMB-01 fail-closed (RED-capable); score math; queue_rank stability; media_identities cascade.

Proof:

- `pytest` scoped to new atlas tests green.
- CLI `--dry-run` on fixture DB or mocked repository returns planned `point_count`.
- aarch64 import smoke documented/executed.

### Slice 2: Admin + tenant read endpoints + disposition POST + auth/tenant tests

**Goal**: Coords, cluster ids, thumbs, and queue are readable without embeddings; dual auth surfaces work; single write route is dispositions.

Changes:

- `admin_atlas.py` (+ tenant mirror routes) with **pinned paths**.
- Points GET: `media_identities` JOIN + shared thumb helper / `build_face_thumb_path`.
- Mount in `api/main.py` behind `admin_enabled` for admin router; recognition router always (when service up).
- Disposition POST (bookkeeping only) with `require_admin_header` on admin side; tenant-auth equivalent on mirror.
- Envelopes as pinned; stale at list time; completion from dispositions table.
- API tests for auth, tenant match, envelope, no-embedding, stale flag, disposition, cascade.

Proof:

- Admin 401/200 matrix; tenant isolation tests; envelope fixture assertions; completion math from dispositions.

### Slice 3: Workbench atlas page + queue ordering surface

**Goal**: Site admins inspect atlas and act via **existing** panels only.

Changes:

- Atlas page + hooks + `TAB_IDS.atlas`.
- Plain Canvas2D scatter; queue list UI + disposition → POST dispositions.
- Click-through to `ClusterReviewPanel` / cluster selection already used by scan tab.
- Deep-links via `appLinks.ts` + `useWorkbenchFilters.ts` + `reviewQueueDriver.ts`.
- Zero-state with CLI instructions (no build button).
- **Roster-coordination lens** (placement concession — atlas stays on Workbench; serves Roster intent without dual-home):
  - **Person-assignment color lens** toggle on the scatter: color points by assignment status — **named/committed-to-person** vs **unlabeled/auto-labeled**. Derive from cluster label / person-binding fields already available on the cluster read path that points GET joins (or must join for this lens). **Verified wire fields**: member/identity projection uses `cluster_label` + `is_auto_label` (`ClusterMemberResponse`, `recognition/interface_adapters/http/schemas/responses.py:53–54`); domain `IdentityCluster.is_auto_label` (`recognition/domain/cluster.py:34–36` = `not user_confirmed`); cluster list/top-unlabeled expose `label` + `is_auto_label` on `ClusterResponse` (`responses.py:132–134`). Atlas points payload for the lens must surface **`cluster_label` + `is_auto_label`** (member-shaped names). Classification: named/committed when `cluster_label` is set **and** `is_auto_label is False`; unlabeled/auto when `cluster_label` is null/empty **or** `is_auto_label is True`. Status colors pair **color + icon** (sr-004) — never color alone.
  - **Click-through for unassigned islands**: selecting an unlabeled/auto-labeled point offers **“Open in Roster → Needs assignment”** via `toRoster(...)` from `js/admin/navigation/appLinks.ts` (E21-10 single-owner link contract). Reuse `personFilter=unassigned` (`APP_LINK_VALUES.personFilterUnassigned`) when that lands the intended Roster surface; if Needs-assignment rail focus needs a dedicated param, **add it to `APP_LINK_PARAMS`** (and a typed builder option) — never a parallel URL codec. **v1 = single-point click only** — do **not** add lasso multi-select (not in v2 scope).
  - **VIZ-15 compliance**: the assignment lens shares the cluster-color encoding family with the review-queue chips; **linked highlighting** = selecting a point highlights its cluster in the queue when both are visible, or deep-links into the queue (`rq=` / existing workbench builders) when the queue is not on-screen.
- Component tests (zero-state, tokens, no cluster-mutation spy calls, disposition POST expected, stale badge, **lens toggle**, **Needs-assignment deep-link builder via `appLinks`**).

Proof:

- `npm test` targeted green; manual smoke: empty → CLI → points render → click opens panel; lens toggle recolors by assignment; unlabeled point → Roster Needs-assignment href from `toRoster`.

### Slice 4: Operator runbook (docs-only)

**Goal**: One-page operator flow; FiftyOne explicitly optional and external.

Changes:

- `docs/runbooks/workbench-curation-atlas.md` only (no service code).
- Sections: install `[atlas]` on A1 → build run (`--dry-run` then full) → open Workbench `?tab=atlas` → work queue → mutate labels via existing panels → interpret AUDIT-13 completion from dispositions → note DIAGNOSTIC doctrine + EMB-01 `--allow-partial`.
- **FiftyOne**: optional operator-local tool for Golden-150 curation only; **not** integrated into the description service; no deps added.
- EVAL-10: sealed eval split never read or altered by this tooling.

Proof:

- Runbook links to real CLI flags and real UI path; reviewed in planning/branch review as doc.

## Lane Decomposition (Multi-Agent)

Optional after S1 schema lands:

| Lane ID | Owned Paths | Upstream | Required Tests |
| --- | --- | --- | --- |
| `backend-atlas` | `scripts/atlas/**`, `db/**`, `recognition/**/admin_atlas.py`, purge, pyproject | none | pytest atlas + API |
| `frontend-atlas` | `js/admin/pages/workbench/atlas/**`, nav, queryKeys | S2 contract stable | npm test atlas |

Merge order: `backend-atlas` then `frontend-atlas`, then S4 docs on the feature branch after both lanes merge.

---

## Consolidated Checklist

> Checklist tracks work only — finding status lives in MCP (`review_findings`), never mirrored here.

### Context and Ownership

- [ ] Loaded backend/frontend rules, E22 epic, HITL distillations, and FIR-9 handoff identity before editing.
- [ ] Boundary table respected: no new label-write path; single disposition POST for queue bookkeeping; dual HTTP surfaces; schema additive in `001_identity_schema.py`.
- [ ] Recorded MCP decision at first implementation slice start (architecture pre-decided by this plan).

### Checklist for Slice 1: Batch job + schema + scores

- [ ] Add `identity_atlas_runs` + `identity_atlas_points` + `identity_atlas_queue_dispositions` to `001_identity_schema.py` with RLS + TENANT_TABLES; all `tenant_id → tenants(id) ON DELETE CASCADE`; points `identity_id → media_identities(id) ON DELETE CASCADE`; runs→points→dispositions cascade.
- [ ] `runs.status` check constraint / backed enum: `building` \| `complete` \| `failed`.
- [ ] `points.queue_rank INT NOT NULL` + index `(run_id, queue_rank)`; `points.media_id INTEGER` (matches `identity.py:49`).
- [ ] Add ORM models and export them from `db/models/__init__.py`.
- [ ] Extend `TenantPurgeService._delete_dependency_rows` delete_plan for atlas tables (`purge_service.py:195–261`) so purge counts include them.
- [ ] Implement centroid MV read (tenant-filtered) + mean-of-representatives fallback; record MV refresh timestamp in `params`; do not refresh per-tenant (global `refresh_centroids_view` only if `--refresh-centroids`).
- [ ] Implement `scripts/atlas/build_atlas.py` using `AtlasRepository.iter_tenant_embeddings` + `enable_rls_bypass` + required `--tenant-id` / `--embedding-model`.
- [ ] EMB-01: separate COUNT/EXISTS fail-closed guard; document `--allow-partial`; never reuse `_filter_embedding_pairs_to_single_model`.
- [ ] HIGH-D scores: `margin = cos(nearest) − cos(second)`; uncertainty rank ascending margin; `intra_cluster_percentile` from per-cluster cosine-to-centroid distribution; `near_threshold` display-only excluded from ranking; persist under `uncertainty` JSONB.
- [ ] Build-time queue mix 60% uncertainty / 20% diversity farthest-first / 20% random; all stochastic steps seeded from run seed; write `queue_rank`; endpoints never recompute.
- [ ] Pin UMAP params + package versions + MV timestamp into `params` JSONB on the run.
- [ ] Add `[atlas]` optional extra (`umap-learn`, `numba`, `llvmlite`) — no tensorflow.
- [ ] CLI supports `--dry-run`, `--allow-partial`, `--refresh-centroids` as specified.
- [ ] Tests: deterministic coords (`random_state`); EMB-01 mixed-model raises (RED-capable); score unit tests; identical fixtures+seed ⇒ identical `queue_rank`; media_identities delete cascades points.
- [ ] aarch64 import smoke for umap (or recorded blocker if wheel unavailable — do not ship unpinned).
- [ ] `make check-remote` (or scoped remote pytest) green for S1.

### Checklist for Slice 2: Admin + tenant endpoints

- [ ] Create `admin_atlas_router` with `Depends(require_admin)` and `get_admin_session` (or shared admin session helper extracted from `admin.py` if needed without behavior change to existing admin routes).
- [ ] Implement pinned paths: `GET /admin/atlas/runs`, `GET …/runs/{run_id}/points`, `GET …/runs/{run_id}/queue`, `POST …/runs/{run_id}/dispositions`.
- [ ] Envelopes: runs `{items, active_embedding_model}`; points `{items, limit, offset, total}` with SQL COUNT; queue `{items ordered by queue_rank, completion: {reviewed, skipped, remaining}}`.
- [ ] Points GET: JOIN `media_identities` for `media_url` + bbox; thumb via shared helper wrapping `build_face_thumb_path` (`blob_url.py:76`) — not private `_face_thumb_*` imports.
- [ ] Mark `stale` at list time when `run.embedding_model != active_embedding_model_id()` (`manifest.py:71`); no background job.
- [ ] Mount admin router under `/admin` inside `admin_enabled` block in `api/main.py`.
- [ ] Mount tenant mirror under `/recognition/atlas/...` with `require_auth` + `assert_tenant_match`.
- [ ] Disposition POST is the **single** atlas write route (bookkeeping only; no label semantics); `require_admin_header` on admin side.
- [ ] Tests: auth matrix, tenant isolation, envelope `total`, no embedding keys, stale flag, disposition rows drive completion, cascade.
- [ ] `make check-remote` green for S2.

### Checklist for Slice 3: Workbench atlas UI + queue surface

- [ ] Add `TAB_IDS.atlas` and tab routing allowlist.
- [ ] Implement **plain Canvas2D** scatter (no new FE dependency): pan/zoom, color by `cluster_id`, tokens `--acx-*`.
- [ ] `ATLAS_RUN_STATUS` TS const object mirrors schema enum only (`building` \| `complete` \| `failed`).
- [ ] Hover/zoom-threshold thumbs via `FaceThumbnail`.
- [ ] Click-through opens existing `ClusterReviewPanel` / cluster selection — atlas code path has **zero** calls to rename/merge/split APIs.
- [ ] Queue list from GET queue; disposition UI → POST dispositions (AUDIT-13).
- [ ] Deep-links reuse `appLinks.ts` (`APP_LINK_PARAMS`/`APP_LINK_VALUES`) + `useWorkbenchFilters.ts` + `reviewQueueDriver.ts`.
- [ ] Zero-state: primary “build first run via CLI” affordance (copy + command); **no** UI job trigger.
- [ ] Stale badge: color + icon (sr-004).
- [ ] **Roster-coordination lens**: toggle color-by-assignment using points JOIN fields `cluster_label` + `is_auto_label` (verified on cluster/member read path); named/committed vs unlabeled/auto; color + icon (sr-004).
- [ ] Unlabeled/auto point click offers “Open in Roster → Needs assignment” via `toRoster(...)` only; any new param lands in `APP_LINK_PARAMS` (no parallel codec); **no lasso** in v1.
- [ ] VIZ-15: lens shares cluster-color encoding with review-queue chips; linked highlight or `rq=` deep-link when queue not visible.
- [ ] Component tests: zero-state, fixture points render, mutation spy **not** called for cluster mutations, disposition POST expected, status uses color+icon; **lens toggle** recolors by assignment; **deep-link builder test** asserts `toRoster` / `APP_LINK_PARAMS` shape for Needs-assignment.
- [ ] `npm test` (targeted) + `make check-remote` as required by repo FE gate.

### Checklist for Slice 4: Runbook

- [ ] Write `docs/runbooks/workbench-curation-atlas.md`: build → review queue → act via existing panels → AUDIT-13 completion from dispositions.
- [ ] Document DIAGNOSTIC doctrine (do not trust 2-D distances for merge decisions).
- [ ] Document EMB-01 fail-closed + `--allow-partial` + `--dry-run`.
- [ ] Document FiftyOne as **optional operator-local** Golden-150 tool only — not a service dependency.
- [ ] Document EVAL-10: sealed eval split never read or altered by this tooling.
- [ ] Link CLI flags and Workbench `?tab=atlas` path.

## Review Readiness

- [ ] No boundary-touching implementation without matching API tests / FE tests / schema proof.
- [ ] EMB-01, DIAGNOSTIC doctrine, CAL-11, EVAL-10, MLDATA-03/04, AUDIT-13 stated in code comments only where non-obvious — and covered by tests where enforceable.
- [ ] Runtime-parity: aarch64 `[atlas]` smoke recorded; admin mount only when `admin_enabled`.
- [ ] Handoff decisions per slice; findings only in MCP; `handoff_close_check(enforce=True)` before merge.

## Stretch Goals

- [ ] UI-triggered atlas build (admin job enqueue) after CLI path is stable.
- [ ] Optional densmap secondary layer toggle in UI (still DIAGNOSTIC).
- [ ] Cluster hull overlays (still non-gating).

## Success Criteria
- Roster-coordination lens (v3): assignment-status color toggle renders from `cluster_label`/`is_auto_label` in the points payload; unlabeled-point click offers the Roster Needs-assignment deep-link built by `toRoster()` (`APP_LINK_VALUES.personFilterUnassigned`); lens performs no mutations.

- [ ] Operator builds an atlas run on A1 CPU for one `(tenant, embedding_model)` with pinned params; mixed-model input fails closed (EMB-01); `--allow-partial` documented.
- [ ] Admin and tenant GETs return coords + cluster ids + thumbs + queue **without** embeddings; pagination envelope honest (`total` from SQL COUNT).
- [ ] Single write route is disposition POST (bookkeeping only); labels only via existing cluster mutation APIs.
- [ ] Build-time `queue_rank` (60/20/20, seeded) is stable; endpoints never recompute.
- [ ] Workbench `?tab=atlas` renders Canvas2D scatter + queue; mutations only via existing `ClusterReviewPanel` / `useClusterMutations` (plus expected disposition POST).
- [ ] Uncertainty queue is the ordered route-to-human worklist (CAL-11); completion from dispositions table (AUDIT-13).
- [ ] Golden-150 sealed eval split never read or altered (EVAL-10); no new label-write path (MLDATA-03/04).
- [ ] Purge/tenant delete removes atlas rows (FK CASCADE + delete_plan); privacy: no embedding egress.
- [ ] Runbook published; FiftyOne not integrated.
- [ ] `make check-remote` green; review coverage target 2 met in handoff DB; zero open findings at close.
