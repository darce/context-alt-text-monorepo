# REFA-7. Decompose `class-clusters-controller.php`

> **Metadata**
>
> - **Date**: 2026-06-10
> - **Author**: Claude (claude-opus-4-8)
> - **Owning Epic**: `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
> - **Epic Short ID**: REFA
> - **Target Branch**: `feature/refa-7`
> - **Review Coverage Target**: 2
>
> **Review coverage note:** Finding/coverage state is DB-generated. Query with
> `review_findings(operation=list, task_ref=REFA-7)` / `review_runs(operation=coverage, task_ref=REFA-7)`.
> Claims verified vs `main` HEAD `14981dfe` (2026-06-10).

## Objective

Reduce `src/api/class-clusters-controller.php` (770 LOC, 23 declared methods, 5 `acx/v1` GET routes) to a thin composition root that delegates the read orchestration, the projection/bootstrap-sync seam, and the response-envelope shaping to focused services under `src/api/services/`, applying **Extract Class** — **without changing observable behavior**. Resolves the orphaned 8th target in the epic Current State table (new Phase 5).

## Problem Statement

The controller concentrates 5 read route handlers plus a recurring **dual-path read seam** (local projection vs. backend proxy, branched per route via `should_use_local_projection`), a **bootstrap/on-demand/targeted sync** orchestration, **proxy-response envelope normalization** (incl. `502` contract-violation guards), and lazy sync-pull-job composition in one 770-LOC class with 23 methods. Unlike REFA-1, it has **no inline DB transactions** (verified: zero `START TRANSACTION`/`COMMIT`/`ROLLBACK`), and unlike REFA-4 it has **no SSE route** — all 5 routes are JSON `GET`. The dominant risk is therefore the **dual local/proxy branch per route**, the **sync side effects** (scheduled events, cooldown-bypass inline sync, targeted projection repair, `do_action` failure signals), the **`perform_bootstrap_sync` WP-action callback**, and the **facade delegation + public repo getters** — all must survive extraction byte-for-byte.

The 5 routes (verified, all `GET` under `/recognition/clusters`):

| Method | Route | Handler |
| --- | --- | --- |
| GET | `/recognition/clusters` | `list_clusters` |
| GET | `/recognition/clusters/top-unlabeled` | `list_top_unlabeled_clusters` |
| GET | `/recognition/clusters/labels` | `list_cluster_labels` |
| GET | `/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)` | `get_cluster_detail` |
| GET | `/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/members` | `get_cluster_members` |

## Constraints

- **Behavior-preserving**; all 5 `acx/v1` response shapes unchanged (rg-002; no contract change).
- **Preserve the dual-path read seam (DP-01).** Every route branches on `should_use_local_projection($tenant_id)`: the **local** branch reads the projection (`ClustersRepository`/`IdentityMembersRepository` + `ClusterFacade`), maps via `ClusterResponseMapper`/`MemberResponseMapper`, and builds the envelope locally; the **proxy** branch calls the inherited `proxy_request(...)` and normalizes the upstream envelope. Both branches per route must return byte-identical responses pre/post extraction; the branch *decision* (gate + stale on-demand sync) must not move or reorder.
- **Preserve sync/bootstrap side effects exactly (SB-01).** `wp_schedule_single_event(time(), BOOTSTRAP_SYNC_HOOK, [$tenant_id])` scheduling (guarded by `wp_next_scheduled`), inline cooldown-bypass sync (`$sync_pull_job->perform_bypass_cooldown(...)`), on-demand stale sync (`$sync_pull_job->perform(...)`), targeted repair (`perform_targeted_snapshot(...)`), and the `do_action('acx_sync_pull_failed'|'acx_recognition_composition_failed', ...)` failure signals must move **with their operation** — none added, dropped, or re-ordered. The `try/catch → degrade to stale` semantics in `should_use_local_projection` and `repair_targeted_projection` are part of the contract.
- **`perform_bootstrap_sync` stays a controller-resident public method (CB-01).** It is wired in the constructor via `add_action(self::BOOTSTRAP_SYNC_HOOK, array($this, 'perform_bootstrap_sync'), 10, 1)`, so WordPress holds a `[$this, 'perform_bootstrap_sync']` callback reference — it must remain a public method *on the controller* (a thin delegate to the sync service if its body moves). The `add_action` registration stays in the constructor. Direct analog of REFA-4's `validate_media_ids` route-callback constraint (PA-02).
- **Preserve facade delegation + public repo getters (FC-01).** `class-recognition-controller.php` is a controller-of-controllers facade that injects `ClustersController` and delegates all 5 handlers (`getClustersController()->list_clusters($request)` … line 141-158); it also reads `$this->clustersController->get_clusters_repository()` and `->get_sync_state_repository()` (lines 318-319) to share those repositories with the cluster-mutations controller. The 5 public handler signatures **and** the two public getters must remain on the controller unchanged.
- **`can_manage_recognition` is inherited (CB-02).** It comes from `AbstractRecognitionProxyController` and is the `permission_callback` for all 5 routes; do not move or re-implement it.
- **Preserve the rg-015 resilience seam.** `proxy_request` stays on `AbstractRecognitionProxyController` (no change to parent or sibling proxy controllers). The proxy-path degradation contract — the `invalid_*_envelope` `WP_Error` `502` guards, the `DATA_SOURCE_UNAVAILABLE` + `PROJECTION_STATUS_BOOTSTRAPPING` fallback envelope, and the `maybe_bootstrap_after_proxy_read` schedule-on-failure — must be preserved verbatim.
- **No scattered status/source strings (sr-007); single canonical constant home (CN-01).** `data_source` (`backend_proxy`/`local_projection`/`unavailable`) and `projection_status` (`available`/`bootstrapping`) are already class constants (`DATA_SOURCE_*`, `PROJECTION_STATUS_*`), and `BOOTSTRAP_SYNC_HOOK` is a class constant too. These are each referenced from **more than one** future home: `DATA_SOURCE_*`/`PROJECTION_STATUS_*` by the read path (the `list_top_unlabeled_clusters` inline envelopes, both branches) **and** the envelope normalizers; `BOOTSTRAP_SYNC_HOOK` by the constructor `add_action` (stays on the controller) **and** the sync-service scheduling/`wp_next_scheduled`. Keep each constant in **one** canonical home (retain on the controller/host, or a small dedicated const holder) that every service references — do **not** let any one service "own" a constant another service also needs, and do not re-introduce magic string literals across the new services.
- **Autoload (rg-016).** New `class-*-service.php` + `interface-clusters-host.php` are loaded two ways in this repo: the composer `classmap` (`src/`) after `composer dump-autoload`, and — matching the **actual REFA-1/REFA-4 implementation** — an explicit `require_once __DIR__ . '/services/class-…-service.php'` from the consuming controller. Put the `require_once` in `class-clusters-controller.php` (where it already `require_once`s its mappers/repos/sync collaborators, lines 7-23), **not** `class-api.php`.
- **sr-008**: service constructors group >8 collaborators into typed objects. The controller already constructor-injects 8 deps via the nullable-default idiom (`?Dep $x = null` → `$x ?? new Dep()`); the read service inherits the largest collaborator set (repos + mappers + facade + sub-services + host) and must group them rather than accept a long flat list.
- **No inline transactions (verified).** Zero `START TRANSACTION`/`COMMIT`/`ROLLBACK` — simpler than REFA-1; the dominant risk is the dual-path read seam + sync side effects + facade, not commit timing.
- **Sequencing.** REFA-7 shares `src/api/`, `src/api/services/`, the facade (`class-recognition-controller.php`), and the `services/` autoload block with **merged** REFA-1/REFA-2/REFA-4 and **pending** REFA-5. Per the epic Git Workflow Assessment, no live PHP REFA task runs concurrently — sequence REFA-7 with REFA-5.

## Workflow Principles

- Safety net first: characterize every route on **both** branches (local-projection and backend-proxy, incl. the bootstrapping-fallback and targeted-repair sub-branches) before any extraction (Fowler Ch4) — golden-JSON for all 5 routes (no SSE here, unlike REFA-4).
- Two Hats; one cohesive service per extraction step; `composer test` + `phpstan` + `cs` green after each.
- Per-slice stop rule: any byte diff in a golden assertion, or 2 consecutive red steps with unclear cause → revert and re-plan smaller.
- Format before lint (`composer cs-fix`); never relax a gate (sr-001).
- Each slice decision cites `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler Ch7 Extract Class).

## Terminology

- **Composition root**: controller keeps route registration + request parsing + the public handler signatures the facade calls + the two public repo getters + the `perform_bootstrap_sync` WP-action callback, delegating logic to injected services. Mirror the nullable-constructor idiom (`?Dep $x = null` → `$x ?? new Dep()`) already used here and by `class-recognition-controller.php`.
- **Host interface (`ClustersHostInterface`)**: the seam through which extracted services reach the controller's inherited recognition-proxy capability. The controller `implements` it; services depend on the interface, not on `AbstractRecognitionProxyController`. Direct port of REFA-1's `ClusterMutationHostInterface` / REFA-4's `AnalysisJobsHostInterface`.
- **Dual-path read seam**: per-route branch between an authoritative **local projection** read and a **backend-proxy** read, selected by `should_use_local_projection` (which also performs on-demand stale sync).
- **Characterization**: all 5 routes — `WP_REST_Request` via `rest_do_request()`, response serialized to a committed fixture, asserted byte-equal pre/post, with volatile fields normalized. No SSE route here, so every route is fully `rest_do_request`-characterizable (simpler than REFA-4).

## Current State Analysis

- Works: all 5 routes function on both branches; `ClustersControllerTest.php` (~56 KB) exercises the controller substantially.
- Insufficient: the existing test's coverage of **each route × {local-projection, proxy-success, proxy-bootstrapping-fallback, targeted-repair}** sub-branch is not yet inventoried as a parity baseline; the sync/bootstrap side effects (scheduled events, `do_action` signals) are not pinned as golden assertions.
- Misleading: a large existing test file can give false "covered" confidence; Slice 1 must inventory branch coverage explicitly before extraction, not assume it.
- No inline transactions and no SSE (both verified) — the simplest of the REFA controllers structurally; risk is concentrated in the dual-path branching and the sync side effects.

## Target Outcome

`class-clusters-controller.php` shrinks to route registration + request parsing + delegation, keeping the 5 facade-facing public handlers (as thin delegates), the two public repo getters, the `perform_bootstrap_sync` callback, `register_routes`, and the constructor. The 13 remaining helper methods (sync/projection + envelope + `load_members_by_cluster`) plus the read **logic** inside the 5 route bodies move into 3 cohesive, unit-tested services under `src/api/services/` (`AltContext\Api\Services\`); the 10 public/registration shells (ctor, `register_routes`, 5 handlers, `perform_bootstrap_sync`, 2 getters) stay. Every route returns byte-identical `acx/v1` responses on both branches; the dual-path seam, bootstrap/sync side effects, facade delegation, and proxy-envelope `502` guards are unchanged; all existing + new tests green.

## Context Loading

- Rules: `docs/workstate/rules/backend-php-guidelines.md`, constitution (sr-007, sr-008, rg-002/rg-015/rg-016).
- Injection-idiom + facade precedent: `src/api/class-recognition-controller.php`; sibling pattern + host-interface precedent: `src/api/class-cluster-mutations-controller.php` + `src/api/interface-cluster-mutation-host.php` (REFA-1), `src/api/class-analysis-jobs-controller.php` + `src/api/interface-analysis-jobs-host.php` (REFA-4), and `src/api/services/`.
- Resilience seam: `src/api/class-abstract-recognition-proxy-controller.php` (rg-015) — provides `proxy_request`, `get_tenant_id`, `should_use_local_projection_gate`, `is_projection_stale`, `can_manage_recognition`.
- Technique: `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler Ch7).
- Handoff: epic `REFA`; this task `REFA-7`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `acx/v1` cluster-read routes (5) | backend | response shapes in this controller | **none** (behavior-preserving) | no | golden-JSON parity for all 5 routes via `rest_do_request`, both branches + bootstrapping-fallback + targeted-repair sub-branches; existing `ClustersControllerTest` |
| recognition-controller facade | backend | delegates to `ClustersController` 5 public handlers + reads `get_clusters_repository`/`get_sync_state_repository` | **none** — handler + getter signatures preserved | no | facade delegation + shared-repo injection tests green |
| recognition proxy resilience seam (rg-015) | backend/proxy | `proxy_request` + envelope-`502` + bootstrapping-fallback degradation | **none** | no | proxy-path golden fixtures incl. `invalid_*_envelope` `502` and `DATA_SOURCE_UNAVAILABLE` fallback |

## Proposed Solution

Characterize all 5 routes on both branches first (golden JSON), then Extract Class into three `AltContext\Api\Services\` collaborators injected via the existing nullable-constructor idiom, keeping route registration, request parsing, the facade-facing public handlers, the public repo getters, and the `perform_bootstrap_sync` callback in the controller. Services reach the inherited proxy capability through a `ClustersHostInterface` the controller implements (HI-01; mirrors REFA-1/REFA-4), receiving `$this` as their first ctor arg. Each new service + the host interface is `require_once`-d from `class-clusters-controller.php` (rg-016) and verified.

Service grouping (covers all 5 routes + the 18 non-route methods):

| Service | Responsibility / methods |
| --- | --- |
| `ClusterResponseEnvelopeService` | Lowest-risk pure shaping for the **list / labels / members** routes only. Owns `build_cluster_list_envelope`, `build_cluster_members_envelope`, `build_cluster_labels_envelope`, and the proxy-path normalizers `normalize_cluster_list_response`, `normalize_cluster_members_response`, `normalize_cluster_labels_response` (incl. the `invalid_*_envelope` `WP_Error` `502` guards). Depends on `ClusterResponseMapper` (the labels normalizer calls `map_labels_list`). **Does NOT own `list_top_unlabeled_clusters`'s envelopes** — those are bespoke and inline (see TU-01). References the `DATA_SOURCE_*` constants from their canonical home (CN-01), does not declare them. |
| `ClusterProjectionSyncService` | The sync/bootstrap/repair seam (SB-01). Owns `should_use_local_projection`, `maybe_bootstrap_after_proxy_read`, the `perform_bootstrap_sync` body, `repair_targeted_projection`, `find_clusters_missing_projected_members`, `cluster_row_should_have_members`, and `resolve_sync_pull_job` (lazy `SyncPullJobFactory` + `SnapshotClient`). Collaborators: `SyncStateRepositoryInterface`, optional `SyncPullJobInterface`/`SyncPullJobFactory`, host (for `should_use_local_projection_gate` + `is_projection_stale`). Owns the `BOOTSTRAP_SYNC_HOOK` scheduling. |
| `ClusterReadService` | The 5 route read bodies + `load_members_by_cluster`. Per route: branch on the sync service's gate, then either read+map+envelope locally or `proxy_recognition_request` + normalize. Collaborators (sr-008 grouped): `ClustersRepositoryInterface`, `IdentityMembersRepositoryInterface`, `ClusterFacade`, `ClusterResponseMapper`, `MemberResponseMapper`, `ClusterProjectionSyncService`, `ClusterResponseEnvelopeService`, host. |

> **Proxy-capability access (HI-01).** Services reach the inherited recognition-proxy capability through a **`ClustersHostInterface`** that `ClustersController` implements — mirroring `ClusterMutationHostInterface`/`AnalysisJobsHostInterface`. Services are constructed `new XService($this /* host */, …collaborators)` via the nullable-default idiom. This keeps `proxy_request` on `AbstractRecognitionProxyController` (no change to parent or sibling proxy controllers) while giving services typed access.
>
> **Visibility resolution (HI-01a — mandatory).** Interface methods are implicitly **public**, but the four capabilities the services need are all **`protected`** on the parent (verified: `proxy_request` line 46, `get_tenant_id` line 192, `should_use_local_projection_gate` line 241, `is_projection_stale` line 301). Declaring the raw protected names on the interface would make `ClustersController implements ClustersHostInterface` **fatal** (`Access level must be public, as in interface`). Resolve exactly as REFA-1 did — the host exposes **public wrappers**, never the raw protected names:
> - `proxy_recognition_request(string $method, string $path, array $body, array $query): WP_REST_Response|WP_Error` → calls the protected `proxy_request` (mirrors REFA-1's `proxy_cluster_mutation`).
> - `get_tenant_id(): string` → controller **redeclares it public** (calling `parent::` is unnecessary since same class; matches REFA-1, whose interface also exposes `get_tenant_id` and whose controller redeclares it public).
> - `host_should_use_local_projection_gate(SyncStateRepositoryInterface $repo, string $tenant_id): bool` and `host_is_projection_stale(?string $updated_at): bool` → thin public wrappers over the protected parent methods.
>
> Slice 1 must verify `ClustersController implements ClustersHostInterface` actually compiles (`php -l` + `class_exists`) **before** any service extraction — a visibility fatal here blocks the whole task.

> **Shared-helper note (SH-01).** Two helpers are used across the read/sync seam — map ownership before Slice 4, do not copy into two services:
> - `cluster_row_should_have_members(array $cluster_row): bool` — called by `get_cluster_members` (read path) **and** `find_clusters_missing_projected_members` (sync path). Owned by `ClusterProjectionSyncService`; `ClusterReadService` calls through it (it is a pure predicate, so it may alternatively be exposed as a stateless method on the sync service the read service holds).
> - The three `build_*_envelope` helpers — used by both the **local** read path (list/labels/members) and the **proxy** normalizers. Owned by `ClusterResponseEnvelopeService`; the read service injects that service rather than duplicating the builders.

> **Top-unlabeled bespoke envelope (TU-01).** `list_top_unlabeled_clusters` does **not** use `build_*_envelope` or the `normalize_*` methods — it constructs its response envelope **inline in the route body on both branches**: the proxy branch (lines 234-274) emits `DATA_SOURCE_BACKEND_PROXY` / the `DATA_SOURCE_UNAVAILABLE` + `PROJECTION_STATUS_BOOTSTRAPPING` fallback, and the local branch (lines 297-308) emits `DATA_SOURCE_LOCAL_PROJECTION` + `PROJECTION_STATUS_AVAILABLE` with the extra `singleton_count` / `has_clusters` / `truncated` fields absent from the other routes. This bespoke shaping moves **with `ClusterReadService`** (its route body), not into `ClusterResponseEnvelopeService`. If the implementer wants symmetry, a dedicated `build_top_unlabeled_envelope` may be extracted, but it stays read-service-owned because it is route-specific, not a shared shape. Both inline envelopes must be golden-pinned in Slice 1 and re-verified after Slice 4.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `src/api/class-clusters-controller.php` | reduce to composition root; `implements ClustersHostInterface`; keep the 5 facade-facing public handlers, `get_clusters_repository`/`get_sync_state_repository`, and the `perform_bootstrap_sync` callback + its `add_action` registration; `require_once` host interface + each new service |
| backend (new) | `src/api/interface-clusters-host.php` | `ClustersHostInterface` exposing **public wrappers** `get_tenant_id` (redeclared public) + `proxy_recognition_request` + `host_should_use_local_projection_gate` + `host_is_projection_stale` over the protected parent methods (HI-01 / HI-01a) |
| backend (new) | `src/api/services/class-cluster-response-envelope-service.php`, `…-cluster-projection-sync-service.php`, `…-cluster-read-service.php` | extracted services (`AltContext\Api\Services\`), each taking the host as first ctor arg where it needs proxy/gate access |
| tests | `tests/Unit/ClustersControllerTest.php` (branch-coverage audit) + new per-service tests + golden fixtures | characterization + unit coverage |

## Related Files

| File | Note |
| --- | --- |
| `src/api/class-recognition-controller.php` | facade injecting this controller + reading its repo getters — delegation + shared-repo injection must stay green; do not refactor here |
| `src/api/class-abstract-recognition-proxy-controller.php` | rg-015 resilience seam — `proxy_request`/gate/stale-check stay here; host wraps them |
| `src/sovereign/class-cluster-facade.php`, `ClusterResponseMapper`, `MemberResponseMapper` | injected collaborators — move references, not behavior |
| `src/sovereign/sync/class-sync-pull-job-factory.php`, `class-snapshot-client.php`, `SyncPullJob(Interface)`, `TargetedSyncPullJobInterface` | sync collaborators — the lazy `resolve_sync_pull_job` composition moves into the sync service intact |

## Verification Strategy

- Deterministic: `cd apps/prototype-wp-alt-context && composer test && composer phpstan && composer cs-check`.
- Autoload (rg-016) per new service + interface: `composer dump-autoload && php -l <file> && php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\Api\\\\Services\\\\ClusterReadService'));"` (and `interface_exists('AltContext\\\\Api\\\\ClustersHostInterface')`).
- Contract (JSON, all 5 routes): golden-JSON fixtures asserted byte-equal before vs after each extraction, covering **both branches per route** plus the proxy bootstrapping-fallback and targeted-repair sub-branches, with volatile fields normalized (frozen clock / stubbed ids, or masked timestamps) so the assertion is deterministic.
- Side effects: assert the bootstrap-scheduling (`wp_schedule_single_event` for `BOOTSTRAP_SYNC_HOOK`) and `do_action` failure signals fire on the same branches pre/post (spy on the WP scheduler + action hooks in the characterization harness).
- Facade: `class-recognition-controller.php` delegation + `get_clusters_repository`/`get_sync_state_repository` shared-repo injection tests green.
- Full gate before review-ready: root `make check-all`.

## Slice Delivery

### Slice 1: Characterization safety net + host interface

**Goal**: Pin current behavior of all 5 routes on both branches before touching structure; declare the host seam.

Changes:
- Inventory `ClustersControllerTest.php` coverage of each route × {local-projection, proxy-success, proxy-bootstrapping-fallback, targeted-repair} sub-branch; add golden-JSON fixtures via `rest_do_request()` for every gap, including the sync side effects (scheduled `BOOTSTRAP_SYNC_HOOK` events + `acx_sync_pull_failed`/`acx_recognition_composition_failed` signals). **Normalize non-determinism**: freeze the clock + stub ids, or mask volatile fields before byte-equal assertion.
- Map shared helpers (`cluster_row_should_have_members`, `build_*_envelope` — SH-01) and confirm callback/getter ownership: `perform_bootstrap_sync` stays a controller-resident WP-action callback (CB-01); `get_clusters_repository`/`get_sync_state_repository` stay public (FC-01); `can_manage_recognition` inherited (CB-02).
- **Define `ClustersHostInterface` (HI-01)**: enumerate the inherited methods each service needs (`get_tenant_id`, `proxy_recognition_request` wrapper, `should_use_local_projection_gate`, `is_projection_stale`); `ClustersController implements` it. Precedes the first extraction.

Proof: new/inventoried characterization tests green against the current controller (both branches per route + side-effect assertions); host interface declared + controller implements it; existing tests green; `composer test` green.

### Slice 2: Extract `ClusterResponseEnvelopeService`

**Goal**: Move the lowest-risk, pure response-shaping group first (no sync coupling).

Changes:
- `ClusterResponseEnvelopeService` owning `build_*_envelope` (3) + `normalize_*` (3, incl. the `invalid_*_envelope` `502` guards + `DATA_SOURCE_*` constants); controller proxy paths delegate to it; `require_once` added + verified (rg-016).

Proof: proxy-path golden fixtures byte-identical (incl. the `502` invalid-envelope and `DATA_SOURCE_UNAVAILABLE` fallback shapes); per-service unit tests; phpstan/cs green.

### Slice 3: Extract `ClusterProjectionSyncService`

**Goal**: Move the sync/bootstrap/repair seam, preserving every side effect and the degrade-to-stale semantics.

Changes:
- `ClusterProjectionSyncService` owning `should_use_local_projection`, `maybe_bootstrap_after_proxy_read`, `perform_bootstrap_sync` body, `repair_targeted_projection`, `find_clusters_missing_projected_members`, `cluster_row_should_have_members`, `resolve_sync_pull_job` + the `BOOTSTRAP_SYNC_HOOK` scheduling; the controller's public `perform_bootstrap_sync` becomes a thin delegate (CB-01); takes the host as first ctor arg for gate/stale access (HI-01).

Proof: golden fixtures for the bootstrapping-fallback + targeted-repair sub-branches byte-identical; scheduled-event + `do_action` signals fire identically (spy assertions); per-service tests; phpstan/cs green.

### Slice 4: Extract `ClusterReadService` + thin controller

**Goal**: Move the 5 route read bodies; controller becomes thin registration + parsing + delegation.

Changes:
- `ClusterReadService` owning the 5 route bodies + `load_members_by_cluster`, injecting the sync + envelope services + host (sr-008 grouped collaborators); controller reduced to route registration, request parsing, the 5 delegating public handlers, the two public getters, and the `perform_bootstrap_sync` callback.

Proof: all 5 routes byte-identical on both branches; facade delegation + shared-repo injection green; all routes characterized green; `make check-all` green.

---

## Consolidated Checklist

> Describe work delivered, not finding status (query `review_findings(operation=list, status=open, task_ref=REFA-7)`).

## Context and Ownership

- [ ] Loaded backend-php guidelines + constitution (sr-007, sr-008, rg-002/rg-015/rg-016) and the Fowler evaluation.
- [ ] Confirmed `ctx7` not required.
- [ ] Recorded `acx/v1` cluster-read + facade (handlers + getters) + proxy-seam boundary ownership = backend, expected change = none.

### Checklist for Slice 1: Characterization safety net + host interface

- [ ] Branch-coverage inventory of `ClustersControllerTest.php` (each route × local/proxy/bootstrapping-fallback/targeted-repair) completed; golden-JSON fixtures added for every gap, volatile fields normalized.
- [ ] Sync side effects pinned (scheduled `BOOTSTRAP_SYNC_HOOK` events + `acx_sync_pull_failed`/`acx_recognition_composition_failed` signals).
- [ ] Shared helpers mapped (SH-01) + callback/getter ownership confirmed (CB-01/CB-02/FC-01).
- [ ] `ClustersHostInterface` defined as **public wrappers** over the protected parent methods (HI-01a); `ClustersController implements` it and **compiles** (`php -l` + `class_exists` — guards the visibility fatal) before any extraction (HI-01).
- [ ] Characterization + existing tests green against the current controller.

### Checklist for Slice 2: Extract response-envelope service

- [ ] `ClusterResponseEnvelopeService` under `src/api/services/` (build + normalize + `502` guards + `DATA_SOURCE_*`); controller delegates; `require_once` added + verified (rg-016).
- [ ] proxy-path golden fixtures byte-identical (incl. `502` + unavailable fallback); per-service tests green.

### Checklist for Slice 3: Extract projection-sync service

- [ ] `ClusterProjectionSyncService` extracted (gate + bootstrap scheduling + on-demand/targeted sync + `resolve_sync_pull_job`); controller `perform_bootstrap_sync` delegates (CB-01); host injected (HI-01).
- [ ] bootstrapping-fallback + targeted-repair golden fixtures byte-identical; scheduled-event + `do_action` signals identical via spies; per-service tests green.

### Checklist for Slice 4: Extract read service; thin controller

- [ ] `ClusterReadService` extracted (5 route bodies + `load_members_by_cluster`, sr-008-grouped collaborators); controller reduced to composition root keeping handlers + getters + callback.
- [ ] all 5 routes byte-identical on both branches; facade delegation + shared-repo injection green; `make check-all` green.

## Review Readiness

- [ ] Every route has golden-JSON evidence on both branches (+ bootstrapping-fallback + targeted-repair); no behavior-touching change without proof.
- [ ] rg-016 autoload checks run for each new service + the host interface.
- [ ] Facade delegation, public repo getters, and `perform_bootstrap_sync` callback verified intact.
- [ ] Handoff decision records moves, verification, citation, and confirms no `acx/v1` shape change.

## Stretch Goals

- [ ] Note any `run_transactional` opportunity for the epic's deferred wrapper slice (none expected — controller has no inline transactions; record if found).

## Success Criteria

- [ ] Controller reduced to a thin composition root implementing `ClustersHostInterface`; all 5 routes delegated to 3 unit-tested services; the 5 facade-facing handlers, 2 public getters, and the `perform_bootstrap_sync` callback preserved.
- [ ] All 5 `acx/v1` routes return byte-identical responses on both branches (local-projection + backend-proxy, incl. bootstrapping-fallback + targeted-repair); sync side effects unchanged.
- [ ] `make check-all` green at HEAD.
