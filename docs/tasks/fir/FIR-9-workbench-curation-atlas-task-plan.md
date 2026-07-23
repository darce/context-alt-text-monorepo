# FIR-9. Workbench UMAP Curation Atlas + Uncertainty Queues

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok 4.5 (xAI)
> - **Project**: `apps/prototype-description-service` + `apps/prototype-wp-alt-context`
> - **Task ID**: `FIR-9`
> - **Target Branch**: `feature/fir-9`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md) (`Epic Short ID`: FIR)
> - **Depends on**: live cluster + member embeddings with `embedding_model` provenance (FIR-2/FIR-4 path); Workbench mutation surfaces (`useClusterMutations`, `ClusterReviewPanel`) already shipping
> - **Review Coverage Target**: 2 _(intent only; live coverage via handoff DB — never paste findings here)_

## Objective

Ship a **DIAGNOSTIC-only** curation-acceleration tool in two halves: (1) an admin Workbench **2-D UMAP face atlas** (zoomable thumbnail scatter colored by `cluster_id`) for spotting bad merges/splits/outliers at a glance; (2) **HIGH-D uncertainty-ranked curation queues** (pgvector cosines) that order what a human reviews first. Projection coords and plots **never** gate or mutate identity state — all mutations continue through existing Workbench mutation APIs. Runs on the A1.Flex **CPU** box (no GPU; batch UMAP only).

## Intake

- **Scope lineage**: E22/FIR follow-on for operator curation acceleration after commercial face stack work (FIR-2…FIR-5). Not in the original P1–P4 table; this plan is the task definition.
- **Architecture is pre-decided** (do not re-litigate UMAP vs t-SNE, ParametricUMAP, or embedding-over-HTTP): batch server-side atlas job + relational atlas artifacts + admin/tenant read GETs + Workbench canvas scatter + HIGH-D queue mix.
- **Not-Doing**: ParametricUMAP / TensorFlow; GPU path; embedding vectors over HTTP; new cluster mutation APIs; eval-harness coupling; FiftyOne service integration; UI-triggered atlas build in v1 (CLI only — see S1/S3); changing Golden-150 sealed eval registration/freeze discipline.

## Problem Statement

Operators curate merges/splits via Workbench review queues without a global geometric overview of the tenant’s face embedding space, and without a principled **HIGH-D** ordering of which faces are most uncertain. Ad-hoc cosine scripts (`scripts/utilities/compare_media_embeddings.py`) and existing suggestion bands help locally but do not produce a shareable atlas run, pinned projection params, or an AUDIT-13-visible queue completion report. FIR-6’s model flip will change `embedding_model`; any projection tooling must refuse multi-model runs (**EMB-01**).

## Constraints

- **DIAGNOSTIC-only doctrine**: 2-D UMAP distances/sizes/densities are **not** similarity evidence (distill.pub *How to Use t-SNE Effectively* misread-tsne class of errors; Nature Methods Primer 2024 on dimensionality-reduction display — cite as in QA v4 §17). Atlas never gates accept/reject/merge. Params + package versions pinned on every stored run.
- **CAL-11 (quality gate, not decoration)**: the HIGH-D uncertainty queue **is** the below-threshold **route-to-human** action. It is not a decorative side panel — it is the primary ordered worklist that feeds existing review surfaces.
- **EVAL-10**: Golden-150 sealed eval split is untouched. If the atlas accelerates Golden-150 **labeling**, labeling may use the full corpus view, but sealed eval registration/freeze discipline (owned by the eval harness / VLM-6 + FIR-5 coordination — not altered by this task) stays as-is.
- **MLDATA-03/04**: labels applied after queue review keep lineage (who/when/what source). Existing mutation paths already write `audit_events` (`db/models/observability.py:AuditEvent`, table `audit_events` in `001_identity_schema.py`). **This task adds no new label-write path.**
- **AUDIT-13**: queue completion is reported (`reviewed` vs `skipped` counts per atlas run) so nonresponse is visible, not silently replaced.
- **EMB-01**: one atlas run = one `(tenant_id, embedding_model)` pair. Never mix models in one projection. After FIR-6 flip, prior-model runs remain listable and marked `stale` relative to the active model.
- **Multi-tenancy**: artifacts tenant-scoped; batch job uses admin-session BYPASS pattern with **explicit** `--tenant-id`; HTTP filters by tenant.
- **Privacy**: HTTP serves coords + cluster ids + thumb refs only — **no raw embeddings**. Atlas data is biometric-adjacent derived state; same retention/purge story as clusters (FK cascade + `TenantPurgeService` delete plan).
- **CPU / ARM**: `umap-learn` (BSD-3) + numba/llvmlite via optional `[atlas]` extra; aarch64 wheel smoke required; **no TensorFlow**.
- **Greenfield schema** (repo policy): additive tables land in `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` (sole revision today — do **not** invent a parallel data-migration story). Also mirror ORM models + `TENANT_TABLES` / RLS / purge hooks.
- **rg-015**: envelope fields (`limit`, `offset`, `total`, provenance) come from the request or stored artifact — never invent pagination from `len(points)`.
- **sr-004 / sr-005 / sr-007 / rg-003**: design tokens, assertion helpers for invariants, enums for status strings, primary controls reachable from empty state.

## Workflow Principles

1. **Projection is display; HIGH-D is decision support.** UMAP for eyes; cosines for queue ranks.
2. **Reuse seams, do not fork mutation paths.** Click-through → existing `ClusterReviewPanel` + `useClusterMutations`.
3. **Pin reproducibility knobs on the run row** (`params` JSON: umap hyperparams, package versions, `random_state`, score recipe version).
4. **Operator-CLI builds runs in v1**; UI is read/navigate only for atlas build triggering.

## Terminology

- **Atlas run**: one persisted projection + score artifact for a single `(tenant_id, embedding_model)`.
- **Atlas point**: one face/identity row with `(x, y)` display coords + HIGH-D `uncertainty` JSON — never the raw vector.
- **Stale run**: run whose `embedding_model` ≠ current active model id (`active_embedding_model_id()` in `recognition/application/embedding/manifest.py`).
- **Queue mix**: ordered list = uncertainty slice + diversity slice + random calibration slice (HITL active-learning practice).
- **DIAGNOSTIC display**: UI that must not drive automated accept/merge thresholds.

## Current State Analysis

| Surface | Verified anchor | Gap for FIR-9 |
| --- | --- | --- |
| Member/rep embeddings | `SqlAlchemyClusterRepository.get_member_embeddings` / `get_representative_embeddings` (`cluster_repository.py:890–921`); already single-model filtered via `_filter_embedding_pairs_to_single_model` (FIR23-01 / EMB-01 family) | No cross-cluster bulk export for UMAP; methods are per-`cluster_id` |
| Centroids | `refresh_centroids_view` / `refresh_centroids_view_concurrent` (`cluster_repository.py:495`, `:580`); MV `mv_identity_cluster_centroids` (see `compare_media_embeddings.py:70`) | No nearest-vs-second margin score surface |
| Thumb projection | `clusters_snapshot._face_thumb_url_for_identity` (`clusters_snapshot.py:77–86`) → `build_face_thumb_path` (`blob_url.py:76`) | Atlas must reuse, not invent, thumb refs |
| Admin HTTP | `admin_router` + `Depends(require_admin)` (`admin.py:148`); `get_admin_session` + `enable_rls_bypass` (`admin.py:67–89`); mount when `security_settings.admin_enabled` (`api/main.py:225–233`) | No atlas routes |
| Tenant assert | `assert_tenant_match` (`clusters_common.py:13`) | Needed on **tenant** read surface for Workbench |
| Workbench mutations | `useClusterMutations` (`identity-clusters/useClusterMutations.ts:37`); `ClusterReviewPanel` (`ClusterReviewPanel.tsx`); review queue driver (`reviewQueueDriver.ts`) | No atlas tab; `TAB_IDS` is scan-only (`WorkbenchNavContext.tsx:9–11`) |
| Thumb UI | `FaceThumbnail` (`js/components/ui/FaceThumbnail.tsx`) | Atlas hover/zoom should reuse |
| Schema / purge | `001_identity_schema.py` + `TenantPurgeService._delete_dependency_rows` (`purge_service.py:195–261`); `TENANT_TABLES` list | No atlas tables; purge plan must gain rows |
| Optional deps | `pyproject.toml` `[project.optional-dependencies]` (`bench`, `gpu`, `vlm`, …) — no `[atlas]` | Add pinned umap-learn/numba/llvmlite |
| HITL distilled (repo) | `literature/extracted/business/distilled/building-ml-powered-applications.md` (active strategies: uncertainty + random sample test set — ch-4 ~L174); `designing-ai-interfaces.md` (HITL / annotation HCI defaults) | Brief name `human-in-the-loop-ml.md` is **not** present; cite these grounded distillations |

## Target Outcome

1. Operator runs `python -m scripts.atlas.build_atlas --tenant-id <uuid> --embedding-model <id>` on the A1 box (with `[atlas]` extra), producing a deterministic (pinned `random_state`) atlas run + points + HIGH-D scores.
2. Admin curl and Workbench (tenant auth) can **list runs**, **page points**, and **fetch the queue** without receiving embeddings.
3. Workbench atlas page: canvas scatter, pan/zoom, color-by-cluster, `FaceThumbnail` on hover/zoom-threshold, click → existing cluster review/mutation flow. Zero-state explains CLI build (no UI trigger in v1).
4. Queue mix surfaces as advisory ordering in the existing review flow; disposition counts satisfy AUDIT-13.
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
| Admin HTTP `/admin` | backend | `admin_router` + `require_admin` (`admin.py`, `admin_auth.py`) | New read-only atlas GETs | Additive | API tests (auth 401, happy path) |
| Recognition HTTP `/recognition` | backend | tenant `require_auth` cluster routes | New tenant-scoped atlas **read** GETs (Workbench path) | Additive; same artifact as admin | `assert_tenant_match` tests |
| WP Workbench SPA | frontend | `TAB_IDS.scan` only | New `atlas` tab + API client | Additive URL `?tab=atlas` | component tests |
| DB schema | backend | `001_identity_schema.py` | `identity_atlas_runs` + `identity_atlas_points` + RLS + purge | Additive greenfield | schema verify + unit tests |
| Optional Python extra | backend | `pyproject.toml` extras | `[atlas]` | Opt-in install | aarch64 smoke |
| Mutations | FE/BE existing | cluster rename/merge/split/reassign | **None** | n/a | atlas performs zero mutation calls |

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

1. Resolve clusters for tenant via `SqlAlchemyClusterRepository.get_snapshot(tenant_id)` (`cluster_repository.py:1318`) or equivalent list of cluster ids.
2. For each cluster, call `get_member_embeddings(cluster_id)` and/or join identities with embeddings + membership (prefer a **new repository method** `iter_tenant_embeddings(tenant_id, embedding_model)` that returns `(identity_id, media_id, cluster_id, embedding)` filtered to the requested model — keeps EMB-01 at the SQL boundary; do not rely on majority filter of mixed rows for a multi-cluster atlas).
3. **EMB-01 guard**: if any selected row’s `embedding_model` ≠ requested model → fail closed before UMAP. Unit test with mixed fixtures.

**UMAP** (optional import from `[atlas]` extra):

- `umap.UMAP(metric="cosine", n_neighbors∈[15,30], min_dist∈[0.05,0.1], random_state=<int>, n_components=2)`
- Optional secondary run with `densmap=True` stored as alternate params only if flag set (default off for v1 determinism budget).
- Pin versions of `umap-learn`, `numba`, `llvmlite` in `pyproject.toml` and record them in `params["package_versions"]`.

**HIGH-D uncertainty scores** (never from 2-D distances) per identity/face:

| Signal | Definition | Source |
| --- | --- | --- |
| `centroid_margin` | `cos(e, c_nearest) − cos(e, c_second)` | Centroids from refreshed MV / `get_representative_embeddings` mean fallback |
| `intra_cluster_percentile` | percentile of distance to own centroid within cluster | member embeddings of same cluster |
| `near_threshold_pair` | bool: max foreign-centroid or pair cosine within band of product thresholds | `ClusteringSettings.similarity_threshold` / `suggestion_floor` / `suggestion_ceiling` (`clustering.py:191–245`) **as diagnostic flags only** — do not change thresholds |

Composite uncertainty rank = higher risk first (small margin, high intra percentile, near-threshold pairs).

**Queue mix** (persist order indices or recompute on GET from stored scores + seed):

- **Uncertainty slice** (~70%): top composite scores.
- **Diversity slice** (~20%): farthest-first / cluster-coverage pick among remaining (avoid pure uncertainty tunnel vision — Ameisen active strategies + diversity).
- **Random slice** (~10%): calibration / nonresponse visibility (Ameisen: always random-sample to avoid over-focus on one failure mode).
- Cite: `building-ml-powered-applications.md` active data strategies; `designing-ai-interfaces.md` HITL control points / annotation HCI defaults (clear, verifiable, adjustable — queue is advisory, human decides).

**CLI flags (normative)**:

```text
--tenant-id UUID                 # required
--embedding-model STR            # required; EMB-01 scope
--n-neighbors INT                # default 15
--min-dist FLOAT                 # default 0.1
--random-state INT               # default 42
--densmap / --no-densmap         # default off
--refresh-centroids              # optional; calls refresh_centroids_view
```

### 2. Persistence — **two tables** (chosen)

**Justification (one sentence):** Relational `identity_atlas_runs` + `identity_atlas_points` enable paginated point GETs, per-point queue indexes, and FK-cascade purge without loading a monolithic JSONB blob per page (rg-015-friendly `total` from SQL `COUNT`).

```text
identity_atlas_runs
  id UUID PK
  tenant_id UUID NOT NULL  → tenants(id) ON DELETE CASCADE
  embedding_model TEXT NOT NULL
  params JSONB NOT NULL          # umap knobs, package_versions, score_recipe, random_state
  point_count INT NOT NULL
  reviewed_count INT NOT NULL DEFAULT 0   # AUDIT-13
  skipped_count INT NOT NULL DEFAULT 0    # AUDIT-13
  created_at TIMESTAMPTZ NOT NULL

identity_atlas_points
  id UUID PK
  run_id UUID NOT NULL → identity_atlas_runs(id) ON DELETE CASCADE
  tenant_id UUID NOT NULL        # denormalized for RLS
  identity_id UUID NOT NULL
  media_id TEXT/BIGINT NOT NULL  # match media_identities.media_id type
  cluster_id UUID NULL
  x FLOAT NOT NULL
  y FLOAT NOT NULL
  uncertainty JSONB NOT NULL     # signals + composite + queue_bucket enum
  UNIQUE(run_id, identity_id)
```

- Add both to `TENANT_TABLES` + RLS policies in `001_identity_schema.py` (same pattern as other identity tables).
- ORM models under `db/models/` (new module or identity-adjacent); export from `db/models/__init__.py`.
- **Purge**: extend `TenantPurgeService._delete_dependency_rows` delete_plan to delete atlas points then runs for tenant (or rely on tenant CASCADE if `tenant_id` FK is ON DELETE CASCADE — still list in purge counts for observability). Prefer explicit purge rows **and** FK cascade as belt-and-suspenders.

### 3. Admin + tenant read routers

**New file**: `recognition/interface_adapters/http/routers/admin_atlas.py`

```python
admin_atlas_router = APIRouter(
    tags=["admin-atlas"],
    dependencies=[Depends(require_admin)],
)
```

**Mount** in `api/main.py` inside `if security_settings.admin_enabled:` **alongside** existing `admin_router` (do not break `assert_admin_env_dsn` / `validate_admin_config` order).

**Read-only GETs** (admin prefix `/admin`):

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/atlas/tenants/{tenant_id}/runs` | List runs newest-first; each row includes `embedding_model`, `created_at`, `point_count`, `stale: bool` vs active model, `reviewed_count`, `skipped_count` |
| GET | `/atlas/tenants/{tenant_id}/runs/{run_id}/points` | Paginated points: `limit`/`offset` from query; envelope `{data, limit, offset, total}` from SQL — **no** fabricated totals |
| GET | `/atlas/tenants/{tenant_id}/runs/{run_id}/queue` | Ordered queue mix (identity_id, cluster_id, scores, bucket); optional `limit` |
| POST | `/atlas/tenants/{tenant_id}/runs/{run_id}/queue/disposition` | **Counters only** (`reviewed` \| `skipped`) + optional point status — **not** a label write; uses `require_admin_header` because it mutates counters (admin.py mutation rule) |

Point payload fields: `identity_id`, `media_id`, `cluster_id`, `x`, `y`, `uncertainty`, `thumb_url` via same projection as `_face_thumb_url_for_identity` / `build_face_thumb_path`. **Never** include `embedding`.

**Tenant mirror** (Workbench): same paths under `/recognition/atlas/...` with `require_auth` + `assert_tenant_match`. Disposition mutation on tenant surface must still only touch atlas counters, not clusters.

### 4. Workbench UI — `apps/prototype-wp-alt-context/js/admin/pages/workbench/`

| New / changed | Role |
| --- | --- |
| `AtlasPage.tsx` (or `atlas/AtlasScatter.tsx` + container) | Canvas 2-D scatter; pan/zoom; color by `cluster_id` using `--acx-*` tokens (sr-004); status chips = color **+** icon |
| `atlas/useAtlasRuns.ts`, `atlas/useAtlasPoints.ts`, `atlas/useAtlasQueue.ts` | React Query; keys under `queryKeys.atlas.*` (extend `api/queryKeys.ts`) |
| `atlas/atlasApi.ts` | Tenant recognition endpoints only |
| `atlas/atlasTypes.ts` | Response types; boundary validation (no assertion helpers for API data — sr-005); `ATLAS_RUN_STATUS` / `QUEUE_BUCKET` as `as const` (sr-007) |
| `WorkbenchNavContext.tsx` | Add `TAB_IDS.atlas = 'atlas'`; allowlist in `useTabParam` |
| Wire into workbench shell (ScanTabContent / main tab switch) | Render `AtlasPage` when `tab=atlas` |
| Click-through | Opens existing cluster detail / `ClusterReviewPanel` — **no** atlas-local mutations; reuse `useClusterMutations` only inside existing panels |

**Zero-state (rg-003)**: when `runs.length === 0`, show primary copy + **operator instructions** to run the CLI (`build_atlas …`). **No “Build run” button that POSTs a job in v1** — run triggering stays operator-CLI (S1). Stretch: later slice may add admin-triggered job.

**Queue surface**: show HIGH-D ordered list beside/under scatter; “Open in review” deep-links into existing `rq=` / cluster panel flows (`workbenchQueueUrl.ts` / `reviewQueueDriver.ts`) without inventing a second mutation stack. Disposition buttons call counters-only endpoint (AUDIT-13).

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
| backend job | `scripts/atlas/build_atlas.py` (+ `__init__.py`, scoring helpers) | NEW batch builder |
| backend repo | `recognition/infrastructure/repositories/cluster_repository.py` | NEW `iter_tenant_embeddings(tenant_id, embedding_model)` (or sibling atlas repository) |
| schema | `db/migrations/versions/001_identity_schema.py` | `identity_atlas_runs` / `identity_atlas_points` + RLS + TENANT_TABLES |
| models | `db/models/` (new atlas models) + `__init__.py` | ORM |
| purge | `recognition/application/services/purge_service.py` | delete_plan entries |
| admin HTTP | `recognition/interface_adapters/http/routers/admin_atlas.py` | NEW |
| tenant HTTP | same module or `recognition/.../routers/atlas.py` | tenant GETs + disposition |
| app mount | `api/main.py` | include routers |
| deps | `pyproject.toml` | `[atlas]` extra |
| FE page | `js/admin/pages/workbench/atlas/*` | NEW |
| FE nav | `WorkbenchNavContext.tsx`, workbench shell | `tab=atlas` |
| FE api | `js/admin/api/queryKeys.ts`, `atlasApi.ts` | keys + client |
| tests | `recognition/tests/...`, `js/admin/pages/workbench/atlas/__tests__/*` | unit/API/component |
| docs | `docs/runbooks/workbench-curation-atlas.md` | S4 operator runbook |

## Related Files

| File | Note |
| --- | --- |
| `recognition/interface_adapters/http/routers/clusters_snapshot.py` | thumb URL projection to reuse |
| `recognition/interface_adapters/http/routers/admin.py` | admin session + auth pattern |
| `recognition/interface_adapters/http/deps/admin_auth.py` | `require_admin`, `require_admin_header` |
| `js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx` | click-through target |
| `js/admin/pages/workbench/identity-clusters/useClusterMutations.ts` | sole mutation path |
| `js/components/ui/FaceThumbnail.tsx` | hover thumbs |
| `scripts/utilities/compare_media_embeddings.py` | BYPASSRLS script precedent |
| `literature/extracted/business/distilled/building-ml-powered-applications.md` | uncertainty + random sampling |
| `literature/extracted/business/distilled/designing-ai-interfaces.md` | HITL / annotation HCI |

## Verification Strategy

- **Deterministic pytest (job/scores/schema)**:
  - Fixture embeddings → UMAP with fixed `random_state` → coords within tight tolerance (or hash of rounded coords).
  - EMB-01: mixed `embedding_model` rows → job raises before fit.
  - Score unit tests: margin / percentile / near-threshold flags on hand-built vectors (no umap required).
  - Schema: insert run+points; cascade delete; RLS tenant isolation if suite supports it.
- **API tests**:
  - Pattern-match `recognition/tests/api/test_admin_router.py` / `test_admin_auth.py`: missing admin token → 401; valid token → 200.
  - Tenant mirror: wrong tenant → 403 via `assert_tenant_match`; envelope `total` matches DB count (rg-015).
  - Response JSON never contains embedding arrays (negative assertion).
- **Frontend**: `npm test` for zero-state, scatter props from fixture points, no mutation spy calls from Atlas page, token classes present.
- **aarch64 smoke**: import `umap` with `[atlas]` installed (document command; run on A1 or CI arm where available).
- **Gate**: `make check-remote` per slice close.
- **Explicit non-coupling**: no imports from `scripts/eval_harness/`; no Golden-150 freeze edits.

## Slice Delivery

### Slice 1: Batch job + schema + HIGH-D scores + unit tests

**Goal**: Operator can build a deterministic atlas run artifact for one `(tenant, embedding_model)` on CPU.

Changes:

- Additive schema + ORM + TENANT_TABLES/RLS + purge plan entries.
- `scripts/atlas/` builder + scoring module + EMB-01 guard.
- `[atlas]` extra pins.
- Unit tests: deterministic coords; EMB-01 fail-closed; score math; cascade.

Proof:

- `pytest` scoped to new atlas tests green.
- CLI dry-run on fixture DB or mocked repository returns run id + `point_count`.
- aarch64 import smoke documented/executed.

### Slice 2: Admin + tenant read endpoints + auth/tenant tests

**Goal**: Coords, cluster ids, thumbs, and queue are readable without embeddings; dual auth surfaces work.

Changes:

- `admin_atlas.py` (+ tenant mirror routes).
- Mount in `api/main.py` behind `admin_enabled` for admin router; recognition router always (when service up).
- Disposition counters endpoint (AUDIT-13).
- API tests for auth, tenant match, envelope, no-embedding, stale flag.

Proof:

- Admin 401/200 matrix; tenant isolation tests; envelope fixture assertions.

### Slice 3: Workbench atlas page + queue ordering surface

**Goal**: Site admins inspect atlas and act via **existing** panels only.

Changes:

- Atlas page + hooks + `TAB_IDS.atlas`.
- Queue list UI + disposition → counters only.
- Click-through to `ClusterReviewPanel` / cluster selection already used by scan tab.
- Zero-state with CLI instructions (no build button).
- Component tests (zero-state, tokens, no mutation from scatter).

Proof:

- `npm test` targeted green; manual smoke: empty → CLI → points render → click opens panel.

### Slice 4: Operator runbook (docs-only)

**Goal**: One-page operator flow; FiftyOne explicitly optional and external.

Changes:

- `docs/runbooks/workbench-curation-atlas.md` only (no service code).
- Sections: install `[atlas]` on A1 → build run → open Workbench `?tab=atlas` → work queue → mutate via existing panels → interpret AUDIT-13 counts → note DIAGNOSTIC doctrine.
- **FiftyOne**: optional operator-local tool for Golden-150 curation only; **not** integrated into the description service; no deps added.

Proof:

- Runbook links to real CLI flags and real UI path; reviewed in planning/branch review as doc.

## Lane Decomposition (Multi-Agent)

Optional after S1 schema lands:

| Lane ID | Owned Paths | Upstream | Required Tests |
| --- | --- | --- | --- |
| `backend-atlas` | `scripts/atlas/**`, `db/**`, `recognition/**/admin_atlas.py`, purge, pyproject | none | pytest atlas + API |
| `frontend-atlas` | `js/admin/pages/workbench/atlas/**`, nav, queryKeys | S2 contract stable | npm test atlas |

Merge order: `backend-atlas` then `frontend-atlas`, then S4 docs on either.

---

## Consolidated Checklist

> Checklist tracks work only — finding status lives in MCP (`review_findings`), never mirrored here.

## Context and Ownership

- [ ] Loaded backend/frontend rules, E22 epic, HITL distillations, and FIR-9 handoff identity before editing.
- [ ] Boundary table respected: no new label-write path; dual HTTP surfaces; schema additive in `001_identity_schema.py`.
- [ ] Recorded MCP decision at first implementation slice start (architecture pre-decided by this plan).

### Checklist for Slice 1: Batch job + schema + scores

- [ ] Add `identity_atlas_runs` + `identity_atlas_points` to `001_identity_schema.py` with RLS + TENANT_TABLES + ON DELETE CASCADE from runs→points and tenant→runs.
- [ ] Add ORM models and export them from `db/models/__init__.py`.
- [ ] Extend `TenantPurgeService._delete_dependency_rows` for atlas tables (counts appear in purge result).
- [ ] Implement `scripts/atlas/build_atlas.py` using repository embedding reads (extend `SqlAlchemyClusterRepository` or dedicated atlas repository) + `enable_rls_bypass` + required `--tenant-id` / `--embedding-model`.
- [ ] Implement HIGH-D scores: `centroid_margin`, `intra_cluster_percentile`, `near_threshold_pair`; persist under `uncertainty` JSONB.
- [ ] Implement queue mix weights (uncertainty/diversity/random) with documented seed.
- [ ] Pin UMAP params + package versions into `params` JSONB on the run.
- [ ] Add `[atlas]` optional extra (`umap-learn`, `numba`, `llvmlite`) — no tensorflow.
- [ ] Tests: deterministic coords (`random_state`); EMB-01 mixed-model raises; score unit tests; schema cascade.
- [ ] aarch64 import smoke for umap (or recorded blocker if wheel unavailable — do not ship unpinned).
- [ ] `make check-remote` (or scoped remote pytest) green for S1.

### Checklist for Slice 2: Admin + tenant endpoints

- [ ] Create `admin_atlas_router` with `Depends(require_admin)` and `get_admin_session` (or shared admin session helper extracted from `admin.py` if needed without behavior change to existing admin routes).
- [ ] Implement GETs: list runs, paginated points, queue; thumbs via `_face_thumb_url_for_identity` / `build_face_thumb_path`.
- [ ] Mark `stale` when `run.embedding_model != active_embedding_model_id()`.
- [ ] Mount admin router under `/admin` inside `admin_enabled` block in `api/main.py`.
- [ ] Mount tenant mirror under `/recognition` with `require_auth` + `assert_tenant_match`.
- [ ] Disposition POST (counters only) with `require_admin_header` on admin side; tenant-auth equivalent on mirror; **no** cluster/label writes.
- [ ] Tests: auth matrix, tenant isolation, envelope `total`, no embedding keys, stale flag, disposition increments `reviewed_count`/`skipped_count`.
- [ ] `make check-remote` green for S2.

### Checklist for Slice 3: Workbench atlas UI + queue surface

- [ ] Add `TAB_IDS.atlas` and tab routing allowlist.
- [ ] Implement canvas scatter (pan/zoom, color by `cluster_id`, tokens `--acx-*`).
- [ ] Hover/zoom-threshold thumbs via `FaceThumbnail`.
- [ ] Click-through opens existing `ClusterReviewPanel` / cluster selection — atlas code path has **zero** calls to rename/merge/split APIs.
- [ ] Queue list from GET queue; disposition UI updates counters (AUDIT-13).
- [ ] Zero-state: primary “build first run via CLI” affordance (copy + command); **no** UI job trigger.
- [ ] Component tests: zero-state, fixture points render, mutation spy not called, status uses color+icon.
- [ ] `npm test` (targeted) + `make check-remote` as required by repo FE gate.

### Checklist for Slice 4: Runbook

- [ ] Write `docs/runbooks/workbench-curation-atlas.md`: build → review queue → act via existing panels → AUDIT-13 counts.
- [ ] Document DIAGNOSTIC doctrine (do not trust 2-D distances for merge decisions).
- [ ] Document FiftyOne as **optional operator-local** Golden-150 tool only — not a service dependency.
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

- [ ] Operator builds an atlas run on A1 CPU for one `(tenant, embedding_model)` with pinned params; mixed-model input fails closed (EMB-01).
- [ ] Admin and tenant GETs return coords + cluster ids + thumbs + queue **without** embeddings; pagination envelope honest.
- [ ] Workbench `?tab=atlas` renders scatter + queue; mutations only via existing `ClusterReviewPanel` / `useClusterMutations`.
- [ ] Uncertainty queue is the ordered route-to-human worklist (CAL-11); disposition counts visible per run (AUDIT-13).
- [ ] Golden-150 sealed eval discipline unchanged (EVAL-10); no new label-write path (MLDATA-03/04).
- [ ] Purge/tenant delete removes atlas rows; privacy: no embedding egress.
- [ ] Runbook published; FiftyOne not integrated.
- [ ] `make check-remote` green; review coverage target 2 met in handoff DB; zero open findings at close.
