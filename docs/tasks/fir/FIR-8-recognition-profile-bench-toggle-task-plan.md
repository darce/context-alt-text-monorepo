# FIR-8. Admin UI Toggle for Recognition Profile Benchmarking

> **Metadata**
>
> - **Date**: 2026-07-23
> - **Author**: Grok (docs-only plan authoring)
> - **Projects**: `apps/prototype-description-service`, `apps/prototype-wp-alt-context`
> - **Task ID**: `FIR-8`
> - **Target Branch**: `feature/fir-8`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-4 (shared `build_embedding_runtime` + `RECOGNITION_FACE_PIPELINE_PROFILE` seam, merged); FIR23-01 (`embedding_model` enforced on read paths + fail-closed readiness)
> - **House style note**: FIR-5 plan is not present in this checkout; structure follows FIR-4 (invariants, per-slice gates, consolidated checklist) plus junior-executable contracts
> - **Review Coverage Target**: 2

## Objective

Ship an **operator-facing** admin surface that lets a privileged operator compare recognition quality between InsightFace `buffalo_l` and the clean candidate `face_pipeline` (YuNet+SFace) on **live tenant media**, by reusing the existing profile selection seam — **not** by inventing a second pipeline.

Deliverables: server-side license/deployment gate, isolation rules that make a silent 512D/128D mix impossible, recognition-service REST contracts, WP `acx/v1` proxy, and an admin SPA control that is visibly labeled for internal non-commercial benchmarking only.

## Intake

- **Operator ask**: admin UI toggle for InsightFace path as **internal benchmarking only**, so the operator can see the quality gap on their own data before model-strategy decisions.
- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) (license isolation + single-model prod DB intake) · E22 epic hard constraints · FIR-4 runtime factory
- **ID note**: the scope task table still lists a contingent “FIR-8 Escalation ladder”. **This plan is the operator-assigned FIR-8** (admin bench toggle). Escalation-ladder work, if still needed after a failed gate, takes a later free id (e.g. FIR-9); renumbering the scope table is a one-line follow-on, not this plan’s implementation scope.
- **Not-Doing here**: listed under [Non-goals](#non-goals).

## Motivation / Context

### Why this exists ([DIAG-08])

Golden-150 / eval-harness bake-offs answer: *on a curated, labeled corpus under controlled conditions, which stack wins, and by how much?* That is necessary for an operator-recorded FIR-6 gate decision, but it does **not** answer:

> On **this tenant’s real media distribution** (roster density, occlusion mix, gallery size, long-tail portraits), how large is the quality gap between buffalo_l and face_pipeline *right now*, and does a candidate improvement (FIR-7 adapters / MediaPipe detector leg later) close that gap on *our* photos?

Live-tenant benching is therefore **diagnostic for strategy**, not a substitute for Golden-150. If an implementation only re-runs Golden-150 from the admin SPA, this task has no reason to exist — refuse that design.

### Measured gap that motivates the surface

Buffalo head-to-head on Golden-150 (manifest sha256 `fe2dbe79`, decision `fir1_buffalo_head_to_head_measured`):

| Metric | buffalo_l | candidate YuNet+SFace |
| --- | ---: | ---: |
| Detection R | 0.995 | 0.504 |
| Occlusion masked | 0.865 | 0.321 |
| Unknown-rejection | 0.986 | 0.910 |
| Clustering purity | 0.898 | 0.860 |

The admin toggle exists so the operator can **observe this class of gap (and future candidate improvements) on live tenant data**, with comparable numbers ([EVAL-01]), not vibes.

### Existing selection seam (reuse only)

| Surface | Role today |
| --- | --- |
| `recognition/infrastructure/embeddings/runtime_factory.py` | Selects stub / insightface / face_pipeline once for scan_worker + inline tasks + HTTP deps. Production dark default remains `insightface` ([RLSE-05], [SERVE-03], [RLSE-07] cited in-module). |
| `recognition/config/settings.py` | `RECOGNITION_FACE_PIPELINE_PROFILE` env; `_FACE_PIPELINE_PROFILES = {"insightface", "face_pipeline"}`; `FacePipelineSettings`; `InsightFaceSettings` + `INSIGHTFACE_CACHE_DIR` / `INSIGHTFACE_HOME` resolution. |
| `recognition/application/embedding/manifest.py` | `active_embedding_model_id()` resolves runtime embedding space from profile (FIR23-01). |
| `recognition/application/health.py` `check_active_embedding_model()` | Fail-closed readiness when active model_id cannot resolve. |
| Cluster/suggestion read paths | FIR23-01 filters to a single `embedding_model` space (majority + lex tie-break / active model). |
| Admin mount | `RECOGNITION_ADMIN_ENABLED` + token; `/admin` mounted only when explicitly enabled (`api/main.py`). |

**This task does not re-plumb detection/embedding.** It adds the operator surface + guard rails over the seam above.

---

## Invariants (hard constraints — non-negotiable)

### I1. License / non-commercial gate ([RLSE-05], [SERVE-03])

- InsightFace `buffalo_l` weights are **NON-COMMERCIAL** (WebFace-trained). The insightface path may exist for **INTERNAL BENCHMARKING ONLY**.
- Default is fail-closed to the **clean path** for any *publishable / production* surface. After FIR-6 switch-over that clean default is `face_pipeline`; until then document the transitional state honestly (dark default is still `insightface` per FIR-4) and still require the bench gate for any *operator-initiated* enablement of insightface on a surface that could be mistaken for production product behavior.
- **Server-side deployment flag is the gate**, not UI visibility. A CSS-hidden button is not a gate.
  - Proposed env: `RECOGNITION_BENCH_PROFILE_ENABLED` (bool, default `false`).
  - When `false`: any API that would activate or schedule the insightface path for bench **rejects** (HTTP 403/409 with stable error code); process continues on the non-bench profile from env.
  - When `true`: deployment is an acknowledged internal-bench environment (pair with existing admin tailnet binding pattern: production admin already requires `RECOGNITION_ADMIN_TAILNET_BOUND=1`).
- UI copy (when surface is shown) must include the literal sense of: **“non-commercial weights — internal benchmarking only”**. Status indicators pair color with icon ([sr-004]).

### I2. Reuse the selection seam ([SERVE-01], [RLSE-07])

- All runtime construction continues through `build_embedding_runtime(...)`.
- Profile vocabulary stays `_FACE_PIPELINE_PROFILES` / `Literal["insightface", "face_pipeline"]` — no third profile name for “bench”.
- No parallel detector factory, no second protocol, no fork of scan_worker glue.

### I3. Embedding-space integrity ([EMB-01], FIR23-01 prior art)

- insightface = **512D** (`insightface-buffalo_l@…`); face_pipeline / SFace = **128D** (`opencv-sface@128d/…`).
- `PGVECTOR_DIM` remains the sole dimension root (`db/settings.py` → `001_identity_schema.py` / `Vector(...)` columns).
- **Switching profiles must never mix embedding spaces in one tenant production index.** Silent 512D/128D mix is the failure mode this plan designs out.
- Prior art to extend, not replace:
  - Write path stamps `embedding_model` (NOT NULL, no DEFAULT).
  - FIR23-01 read-path filtering + centroid framing by `embedding_model`.
  - `check_active_embedding_model()` fail-closed readiness.
  - Three-way dim guard on face_pipeline construction (FIR-4).

### I4. Frontend house rules

- Admin SPA: `apps/prototype-wp-alt-context/js/admin/` (React/TS).
- Design tokens `--acx-*` only ([sr-004]); status as `as const` objects ([sr-007]); assertion helpers not `console.assert` ([sr-005]); primary controls reachable from zero state ([rg-003]); controlled dialogs wire `onOpenChange` ([rg-004]).
- REST namespace `acx/v1/`; WP options `acx_*` if any option is needed (prefer not storing license-critical gate client-side).

### I5. Boundary honesty ([rg-015])

- Adapters/controllers must not invent envelope metadata (`limit`, `offset`, `total`, `data_source`, readiness fields). Every field comes from request, upstream payload, or a documented constant fallback named in the contract section below.

### I6. Greenfield schema policy

- No Alembic add-on migrations for new tables/columns. Schema edits go in `001_identity_schema.py` only. Prefer zero schema if isolation option allows.

### I7. Independent bench verdicts ([OBS-09], [EVAL-01], [TEST-08])

- Bench metrics/verdicts are produced by a **scorer outside either model path** (bench orchestrator / report builder), never by counters the path under test can self-tune.
- Numbers use the same metric *names/frames* as Golden-150 / eval-harness where sensible (detection counts / P-R proxies, unknown-rejection, clustering purity when labels exist) and are labeled `source=live_tenant_bench` so they are never confused with Golden-150 publishable scores ([DIAG-08]).

---

## Design decision: embedding-space isolation (hardest choice)

Both options below satisfy I3. The implementing task picks **exactly one** primary path in S1 and records the decision id; do not ship a hybrid of both without a further decision.

### Option A — Dedicated bench tenant / eval deployment (full pipeline)

**Mechanism**

- Operator-facing toggle does **not** flip the production tenant’s process-wide profile onto insightface while that tenant holds face_pipeline rows (or vice versa).
- Instead, enabling “bench” provisions or selects a **non-publishable bench tenant** (or a dedicated eval recognition deployment) whose process runs `RECOGNITION_FACE_PIPELINE_PROFILE=insightface` + matching `PGVECTOR_DIM=512`, with `RECOGNITION_BENCH_PROFILE_ENABLED=1`.
- Live tenant media bytes are **read** (or re-uploaded by reference) into the bench tenant; scan → cluster runs entirely there; production `media_identities` untouched.
- Admin SPA shows side-by-side metrics (prod face_pipeline vs bench insightface) computed by an independent scorer on the dual run records.

**Pros**

- Full pipeline comparison (detect → embed → cluster → purity proxies).
- Matches scope intake: *buffalo embeddings live only in eval / dedicated deployment, not mixed into prod DB*.
- pgvector fixed-width remains single-model per DB.
- FIR23-01 stays a no-op per deployment (single model).

**Cons**

- Ops weight: second deployment or tenant bootstrap, media copy/reference strategy, auth pairing for bench tenant.
- Latency/cost of dual full scans.
- SPA must handle two data sources without inventing pagination metadata ([rg-015]).

### Option B — Same-process profile override with fail-closed index guard (lighter ops)

**Mechanism**

- Persist an **operator desired profile** (durable row or file) consulted only when `RECOGNITION_BENCH_PROFILE_ENABLED=1`.
- `build_embedding_runtime` continues to be the only constructor; settings resolve: `effective_profile = override if (bench_enabled ∧ override_allowed) else env_profile`.
- **Before activation**, server checks:
  1. Target profile’s manifest dimensions == `PGVECTOR_DIM`.
  2. Tenant has **zero** `media_identities.embedding_model` rows whose model_id/dim is incompatible with the target (or operator explicitly confirms wipe/re-scan — greenfield-compatible).
  3. Readiness re-runs `check_active_embedding_model` + vector typmod probe; mismatch → refuse toggle, leave previous profile active.
- Shared runtime singletons invalidated on successful flip.
- UI still labeled non-commercial; gate still server-side.

**Pros**

- One deployment; closer to a literal “toggle”.
- Reuses process-local factory with minimal new plumbing.

**Cons**

- Cannot hold 512D and 128D rows in one fixed-width column at once — comparison is **sequential** (run A, export metrics, wipe/reconfigure, run B), not simultaneous side-by-side in one index.
- Higher operator foot-gun risk if wipe acknowledgment is weak.
- Process-wide flip affects all tenants on that instance — multi-tenant prod hosting is a poor fit unless instance is single-tenant internal.

### Decision (plan recommendation)

**Primary: Option A** for any multi-tenant or publishable-adjacent host.

**Acceptable MVP shortcut: Option B** only when the deployment is a single-tenant **internal** bench host (`RECOGNITION_BENCH_PROFILE_ENABLED=1`, admin tailnet-bound, non-publishable), and the activation gate includes the dim + empty-or-wipe checks above.

**Rejected**

- UI-only hide of insightface.
- Writing both dims into `media_identities.embedding` and “hoping” FIR23-01 filters save you (filters prevent *read* pollution; they do not make pgvector accept wrong width, and mixed rows still poison clustering inputs if filters regress).
- Process-wide flip without readiness/dim checks ([RLSE-05]).

S1 records the chosen option as an MCP decision before code lands.

---

## Non-goals

- **No production switch-over logic** — that is FIR-6 (default flip, dimension default flip, buffalo eviction from prod images).
- **No new model legs** — FIR-7 owns GPU/adapters; MediaPipe detector leg is a separate eval.
- **No public / tenant-facing exposure** of the insightface path, ever (no workbench end-user control, no site-front toggle, no unauthenticated route).
- **No Golden-150 re-host inside the admin SPA** as a substitute for live-tenant bench ([DIAG-08]).
- **No new embedding pipeline / protocol** — reuse FIR-2 seam + FIR-4 factory only.
- **No commercial redistribution of buffalo weights** and no packaging change that moves insightface out of the `[bench]` extra narrative established in FIR-4.
- **No silent env mutation from the browser** without the server-side bench flag.

---

## Current State Analysis

- Profile is **env-resolved only** at settings construction (`_resolve_face_pipeline_profile`); no admin REST mutates it today.
- Production dark default remains **`insightface`** (FIR-4); face_pipeline is dark-selectable via env. FIR-6 will invert the product default later — this plan’s gates must not assume either world exclusively; tests cover both “env default insightface” and “env default face_pipeline” matrices for the bench gate.
- WP admin SPA already has Settings (`js/admin/pages/settings/`, `SettingsController` at `acx/v1/settings`) with capability `manage_options`, source labels, health pairing patterns (`settingsConstants.ts` uses `as const` status objects — mirror that style).
- Recognition operator admin is a separate FastAPI `/admin` mount (tenant/API-key lifecycle), env-gated — **pattern to mirror** for bench endpoints (dedicated auth, audit row on mutation, fail-closed boot validation).
- Dim root defaults to **512** (`PGVECTOR_DIM` default in `db/settings.py`) until FIR-6; face_pipeline requires `PGVECTOR_DIM=128` + matching empty index for dark exercise.
- Eval metrics live under `scripts/eval_harness/` (`face_metrics.py`, report builders). Live-tenant bench should **import metric helpers**, not reimplement formulas ([EVAL-01], NAME-02).

---

## Target Outcome

1. Deployment flag `RECOGNITION_BENCH_PROFILE_ENABLED` (default off) is the sole enabler for any operator-facing insightface bench control path.
2. Admin SPA (manage_options) shows a bench panel only when the recognition service reports `bench_available=true` (server-derived); panel is labeled non-commercial / internal only.
3. Operator can start a **comparable dual-path (or sequential) bench observation** on selected live media (or whole tenant sample) and see numbers framed like Golden-150 metrics, tagged `live_tenant_bench`.
4. Production tenant identity tables never contain mixed-dimension rows; insightface embeddings never land in a publishable production index (Option A) or only after explicit wipe + dim realign on an internal host (Option B).
5. All construction still goes through `build_embedding_runtime`.

---

## Contract and Boundary Impact

### Recognition service (authoritative)

Mount under the existing **admin-auth** boundary (same token/header family as `/admin`, or a dedicated dependency that reuses `require_admin` / `require_admin_header`). Do **not** put these on the tenant API-key path.

#### `GET /admin/bench/face-pipeline-profile`

**Purpose**: read effective profile + gate state for SPA.

**Response 200** (all fields server-derived; no client-invented totals):

```json
{
  "bench_enabled": false,
  "bench_available": false,
  "env_profile": "insightface",
  "effective_profile": "insightface",
  "override_profile": null,
  "embedding_model_id": "insightface-buffalo_l@512d/l2/cosine",
  "pgvector_dimension": 512,
  "license_notice": "non-commercial weights — internal benchmarking only",
  "isolation_mode": "dedicated_bench_tenant",
  "activation_blockers": []
}
```

- `bench_enabled`: raw deployment flag.
- `bench_available`: `bench_enabled && admin_auth_ok_context && isolation_preflight_ok` (server computes; SPA does not invent).
- `activation_blockers`: list of stable machine codes (`dim_mismatch`, `foreign_embedding_model_rows`, `bench_flag_off`, `insightface_runtime_unavailable`, …) — empty when available.
- `isolation_mode`: `"dedicated_bench_tenant"` | `"process_override_internal"` matching S1 decision.

#### `PUT /admin/bench/face-pipeline-profile` (Option B only; Option A may omit)

**Request**:

```json
{ "profile": "insightface", "confirm_wipe": false }
```

**Behavior**:

- If `RECOGNITION_BENCH_PROFILE_ENABLED` is false → **403** `{ "error": "bench_flag_off" }`.
- If profile ∉ `{insightface, face_pipeline}` → **400** `{ "error": "invalid_profile" }` (mirror settings validation, rg-008).
- If dim / foreign-row preflight fails and `confirm_wipe` is not accepted per policy → **409** with `activation_blockers`.
- Success → **200** same shape as GET after apply; audit_events row on same session (mirror admin router audit pattern).

#### `POST /admin/bench/runs` (Option A primary; also valid for dual sequential runs)

**Request**:

```json
{
  "source_tenant_id": "uuid",
  "media_ids": ["..."],
  "profiles": ["face_pipeline", "insightface"],
  "sample_limit": 50
}
```

**Response 202**:

```json
{
  "run_id": "uuid",
  "status": "queued",
  "profiles": ["face_pipeline", "insightface"],
  "media_count": 50,
  "isolation_mode": "dedicated_bench_tenant"
}
```

- `media_count` is **count of accepted media after server-side resolution**, not `len(request.media_ids)` if some were dropped — document drop reasons in run detail; do not silently claim request length ([rg-015]).

#### `GET /admin/bench/runs/{run_id}`

**Response 200**:

```json
{
  "run_id": "uuid",
  "status": "completed",
  "profiles": ["face_pipeline", "insightface"],
  "metrics": {
    "source": "live_tenant_bench",
    "per_profile": {
      "face_pipeline": { "detection_count": 0, "images_with_faces": 0, "unknown_rejection": null, "cluster_purity": null },
      "insightface": { "detection_count": 0, "images_with_faces": 0, "unknown_rejection": null, "cluster_purity": null }
    },
    "deltas": { "detection_count": 0 }
  },
  "license_notice": "non-commercial weights — internal benchmarking only"
}
```

- Nullable metrics stay `null` when labels are insufficient — **do not invent 0.0 purity** ([rg-015], [EVAL-01]).
- Scorer is independent of adapters ([OBS-09]).

### WordPress plugin (`acx/v1`)

Proxy only — no local re-scoring.

| Method | Path | Permission | Upstream |
| --- | --- | --- | --- |
| GET | `/acx/v1/bench/face-pipeline-profile` | `manage_options` | recognition GET above |
| PUT | `/acx/v1/bench/face-pipeline-profile` | `manage_options` | recognition PUT (if Option B) |
| POST | `/acx/v1/bench/runs` | `manage_options` | recognition POST |
| GET | `/acx/v1/bench/runs/{id}` | `manage_options` | recognition GET |

Envelope rules: pass through upstream JSON; on transport failure return WP_Error with stable codes (`bench_upstream_unreachable`, …). Do not synthesize `metrics` client-side.

### Persistence

- **Option A**: run records + metric artifacts (table or object store). If SQL: add to `001_identity_schema.py` only (e.g. `recognition_bench_runs`). Never write insightface vectors into production tenant `media_identities`.
- **Option B**: durable override record (DB row or env file) + optional last-run metrics artifact; wipe path uses existing greenfield reset/re-scan tools, not a new migration story.
- Prefer **no WP option** for the license gate (gate is recognition-service env). Optional WP UI preference (collapsed panel) may use `acx_bench_panel_dismissed` — cosmetic only, not a gate.

### Observability

- Structured log fields: `bench_run_id`, `effective_profile`, `embedding_model_id`, `isolation_mode`, `source=live_tenant_bench`.
- Do not emit bench metrics onto the production quality SLO dashboards without a `bench` label ([OBS-09]).

---

## Slice Delivery

| Slice | Content | Acceptance gate | Primary tests |
| --- | --- | --- | --- |
| **S1** Gate + isolation decision | Land `RECOGNITION_BENCH_PROFILE_ENABLED` (default false); record Option A vs B decision; implement server-side preflight (`dim`, foreign `embedding_model`, flag); refuse insightface bench activation when flag off | Flag-off rejects; flag-on + preflight fail rejects; settings still load-time validate profile set | Unit: gate matrix ([TEST-15]); preflight table-driven cases |
| **S2** Factory-facing effective profile | Effective profile resolution for runtime (override only if gate allows); still only `build_embedding_runtime`; singleton invalidation on flip (B) or dual construction for bench worker (A) | Characterization: production path unchanged when flag off ([TEST-03]); factory never called with insightface for bench when flag off | Unit + one integration: both profiles construct under flag-on internal env |
| **S3** Recognition REST + audit | GET/POST(+PUT) contracts above; admin auth; audit on mutations; metrics scorer skeleton importing eval_harness helpers where possible | Contract tests assert JSON shape + null purity when unlabeled; 403 without admin token | API tests under `recognition/tests/api/` |
| **S4** WP `acx/v1` proxy | PHP controller + pass-through; `manage_options`; no invented metrics | PHPUnit: permission denied for non-admin; pass-through body; transport error mapping | PHP unit + existing REST test patterns |
| **S5** Admin SPA panel | Settings (or Diagnostics) panel: zero-state CTA ([rg-003]), license banner, status `as const`, tokens only, controlled confirm dialog with `onOpenChange` ([rg-004]); primary control visible without prior selection | Vitest: flag-off hides enablement / shows blocked state from server `bench_available`; flag-on shows labeled toggle/run; no magic strings for status ([sr-007]) | Vitest + RTL |

S1 → S2 → S3 sequential; S4 after S3 contract frozen; S5 can start on mocked S3 fixtures once contract JSON is pinned (characterization fixtures committed in S3).

---

## Junior-executable contracts (per slice)

A competent junior implements each slice without product questions if they follow these contracts literally.

### S1 — Gate + isolation

**Files**

- `recognition/config/settings.py` or `security.py`: add `_bool_env("RECOGNITION_BENCH_PROFILE_ENABLED", False)` next to `admin_enabled` pattern.
- New small module e.g. `recognition/application/bench/preflight.py`: pure functions, no HTTP.
- MCP decision: `fir8_isolation_mode_{dedicated_bench_tenant|process_override_internal}`.

**API of preflight (pure)**

```text
preflight_bench_activation(*, bench_enabled: bool, target_profile: str,
  pgvector_dimension: int, target_manifest_dimensions: int,
  foreign_embedding_model_count: int, confirm_wipe: bool) -> list[str]
# returns activation_blockers codes; empty list means allowed
```

**Tests (must go red first, [TEST-06])**

1. `bench_enabled=False` → blockers include `bench_flag_off` even if dims match.
2. `target_manifest_dimensions != pgvector_dimension` → `dim_mismatch`.
3. `foreign_embedding_model_count > 0` and not `confirm_wipe` → `foreign_embedding_model_rows`.
4. All clear → `[]`.
5. Unknown `target_profile` rejected at settings/validator layer (existing profile validator).

**Mutation red-proof**: temporarily force preflight to ignore `bench_enabled`; test 1 must fail.

### S2 — Effective profile + factory

**Rules**

- Add `effective_face_pipeline_profile(settings) -> str` used by any new bench path; **do not** change the production dark default without FIR-6.
- When flag off: effective == env profile always (ignore any stored override).
- Option A: production factory call sites stay on env profile; only the bench worker process/deployment uses insightface.
- Option B: document singleton reset hook (mirror `get_shared_face_pipeline_runtime` test reset) called after successful PUT.

**Tests**

1. Flag off + stored override insightface → effective remains env (e.g. face_pipeline).
2. Flag on + override insightface + preflight ok → effective insightface.
3. `build_embedding_runtime` still returns stubs when `runtime_mode=="test"` (orthogonal).

### S3 — REST

**Rules**

- Router lives under `recognition/interface_adapters/http/routers/` (new `bench.py` or extend `admin.py` with clear section).
- Mutations: `Depends(require_admin_header)` + audit event type enum member (sr-007), e.g. `BENCH_PROFILE_PUT`, `BENCH_RUN_CREATE`.
- Metrics: compute in `recognition/application/bench/score.py` from run artifacts; **import** detection count helpers from eval harness if import path is clean; otherwise duplicate the **formula** with a comment pointing at the harness source and a parity unit test ([EVAL-01]).
- Never call adapter code to “self-report quality score” ([OBS-09]).

**Tests**

1. Unauthenticated → 401/403.
2. Flag off POST run → 403 `bench_flag_off`.
3. Completed run with no labels → `cluster_purity` is JSON `null`, not `0`.
4. Response includes `license_notice` string containing `non-commercial`.

### S4 — WP proxy

**Files**

- New `src/api/class-bench-controller.php` (or settings sibling).
- Register in the same bootstrap path as `SettingsController`.
- Use existing recognition HTTP client / endpoint resolver patterns; do not hardcode hosts.

**Tests**

1. User without `manage_options` → rest_forbidden.
2. Mock upstream 200 body equals WP response data (deep equality on metrics object).
3. Upstream down → WP_Error code `bench_upstream_unreachable` (exact code pinned in test).

### S5 — SPA

**Files**

- `js/admin/pages/settings/` (preferred: new `BenchProfilePanel.tsx` + constants) or dedicated diagnostics route registered in `App.tsx`.
- `js/admin/api/benchApi.ts` with `as const` status maps.
- Styles: only `--acx-*` variables.

**UX contract**

- Zero state: if `bench_available=false`, show server `activation_blockers` and license notice; primary action is “View requirements” / link to runbook, **not** a dead toggle ([rg-003]).
- If `bench_available=true`, primary action “Run live-tenant bench” (Option A) or “Enable insightface bench profile” (Option B) reachable without selecting media first; media sample may default to “last N workbench items” with explicit default N in UI.
- Confirm dialog: controlled, `onOpenChange` wired, copy includes non-commercial sentence.
- Status values: e.g. `BenchRunStatus = { QUEUED, RUNNING, COMPLETED, FAILED } as const` — no raw string compares in components ([sr-007]).

**Tests**

1. `bench_available=false` → enable/run button not active; blockers rendered.
2. `bench_available=true` → run control present from empty selection state.
3. License banner text assertion (substring `non-commercial`).

---

## Files and Surfaces to Change (implementation map)

| Area | Likely paths |
| --- | --- |
| Gate / settings | `recognition/config/settings.py`, `recognition/config/security.py` |
| Preflight / score | `recognition/application/bench/*` (new) |
| Factory consumer | `runtime_factory.py` (call-site only if Option B needs effective profile read — prefer settings property over editing factory logic) |
| HTTP | `recognition/interface_adapters/http/routers/bench.py` (new), `api/main.py` mount next to admin |
| Schema (if needed) | `db/migrations/versions/001_identity_schema.py` only |
| WP REST | `apps/prototype-wp-alt-context/src/api/class-bench-controller.php` (new) |
| SPA | `js/admin/api/benchApi.ts`, `js/admin/pages/settings/*`, maybe `App.tsx` |
| Tests | `recognition/tests/api/test_bench_*.py`, `recognition/tests/unit/test_bench_preflight.py`, PHPUnit bench controller, Vitest panel |
| Docs | short operator note under `docs/runbooks/` or operations (bench flag + isolation mode) |

---

## Verification Strategy

- Per-slice scoped TDD locally; observe new tests fail first ([TEST-06]).
- Discriminating gate tests ([TEST-15]): flag matrix × dim matrix × foreign-row matrix — not a single happy path.
- Determinism ([TEST-08]): metric fixtures use fixed detection lists; scorer pure.
- `make check-remote` (description-service) + plugin `make` test targets for PHP/TS surfaces touched.
- Manual smoke (recorded in close decision): internal host with flag on, sample of real tenant media, both profiles’ detection counts visible, license banner present, flag off returns 403.
- Adversarial review per slice citing heuristic IDs; findings only in handoff MCP (not pasted into this plan).

---

## Consolidated Checklist

### Context and Ownership

- [ ] Isolation mode decision recorded (`Option A` recommended; `Option B` only for single-tenant internal hosts)
- [ ] Plan accepted via planning-review before `make task-start TASK=FIR-8`
- [ ] Worktree: `feature/fir-8` via `make task-start`

### S1 — Gate + isolation preflight

- [ ] `RECOGNITION_BENCH_PROFILE_ENABLED` default false
- [ ] Pure preflight function + table-driven tests (flag / dim / foreign rows / wipe)
- [ ] Red-proof: mutating away flag check fails a test
- [ ] Slice decision recorded

### S2 — Effective profile / factory reuse

- [ ] No second factory; `build_embedding_runtime` remains sole constructor
- [ ] Flag-off ignores overrides
- [ ] Characterization: production behavior unchanged when flag off
- [ ] Slice decision recorded

### S3 — Recognition REST

- [ ] GET profile/status contract green
- [ ] POST runs (and PUT if Option B) auth + audit + license_notice
- [ ] Metrics nullability contract (no invented purity)
- [ ] Independent scorer ([OBS-09]); metric names aligned with eval-harness where applicable ([EVAL-01])
- [ ] Slice decision recorded

### S4 — WP proxy

- [ ] `acx/v1/bench/*` routes, `manage_options` only
- [ ] Pass-through envelope; transport error codes pinned
- [ ] Slice decision recorded

### S5 — Admin SPA

- [ ] Panel labeled non-commercial / internal only
- [ ] Zero-state primary control / blockers ([rg-003])
- [ ] Tokens `--acx-*`, statuses `as const`, dialog `onOpenChange`
- [ ] Vitest coverage for available/unavailable server states
- [ ] Slice decision recorded

### Review readiness

- [ ] `make check-remote` / plugin gates green at HEAD
- [ ] `/review-parallel` (or equivalent) with findings in MCP only
- [ ] Zero open findings; `handoff_close_check(enforce=True)`

---

## Success Criteria

1. With `RECOGNITION_BENCH_PROFILE_ENABLED=0`, no admin or SPA path can activate insightface benching (server 403; UI shows blocked state from server fields).
2. With flag on, an operator can obtain **comparable numeric** live-tenant metrics for buffalo_l vs face_pipeline without mixing embedding spaces in a production index.
3. License notice is visible and API-carried; insightface remains non-public.
4. Runtime construction still funnels through `build_embedding_runtime` and `_FACE_PIPELINE_PROFILES`.
5. Live-tenant bench output is explicitly not Golden-150 ([DIAG-08]) yet reuses metric frames ([EVAL-01]) and independent scoring ([OBS-09]).

---

## Rollback

- Set `RECOGNITION_BENCH_PROFILE_ENABLED=0` (instant fail-closed).
- Unmount/disable SPA panel is cosmetic only.
- Option A: drop bench tenant / stop bench deploy; production untouched.
- Option B: clear override + restart; re-scan if a wipe was performed.
- No FIR-6 product default changes in this task — rollback cannot and must not reintroduce buffalo as a silent production default under a commercial deployment story ([RLSE-08] spirit).
