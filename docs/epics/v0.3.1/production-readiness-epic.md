# Production Readiness (v0.2.0)

## Objective

Bring the tagged v0.1.0 sovereign system to a reliable production baseline: deployable, secure, observable, and operationally testable -- with frontend reliability and UX clarity as the first priority.

## Audit Summary (This Revision)

This epic was revised using:

- [roadmap-v3.hybrid.md](../../roadmaps/roadmap-v3.hybrid.md)
- [current-debt.md](../../tasks/tech-debt/current-debt.md)
- [e2e-smoke-automation-path.md](../../tasks/tech-debt/e2e-smoke-automation-path.md)
- Frontend codebase audit (Feb 2026): pattern/antipattern analysis across WorkbenchPage, RosterPage, identity-clusters module, and state management layer.

Key corrections:

1. **Promoted UX reliability to Phase 1** (was Phase 4). Frontend fixes have zero backend dependency and the highest user-facing impact.
2. Promoted debt item **#12** (deterministic E2E/smoke path) from deferred debt to a production release gate.
3. Removed scope creep: dashboard/alt-text product expansion and v0.2 sync re-architecture are not release blockers.
4. Corrected obsolete endpoint path assumptions:
   - Snapshot endpoint is `GET /recognition/tenants/{tenant_uuid}/clusters/snapshot`.
5. Replaced speculative UX work with reliability-focused UX acceptance criteria grounded in confirmed codebase antipatterns.

## Phase Ordering Rationale

UX reliability (Phase 1) is sequenced first because:

- Every identified fix is frontend-only; no backend API changes, no schema changes, no deployment changes.
- The "Saving..." hang, force-navigation on scan complete, and missing error boundaries are the most visible defects to operators.
- Fixing these early provides a stable UX surface for subsequent E2E smoke tests (Phase 2) to assert against.
- Backend phases (deployment, security, observability) require external decisions (VPS, DNS, key policy) that are not yet started.

## Scope for v0.2.0

### In Scope

- **Frontend reliability and UX clarity** (no backend dependency).
- Deterministic E2E/smoke automation for sovereign flows (local + outage + recovery).
- Production backend deployment path (containers, envs, persistence, restart behavior).
- **Production server provisioning** (Oracle Cloud PAYG, ARM instance, DNS/TLS, WP demo).
- Internet-facing security baseline (auth hardening, origin policy, rate limiting, key rotation).
- Observability baseline (structured logs, health/readiness, correlation IDs, latency metrics).
- Future account-system storage is out of scope for this release epic and must be planned separately before implementation.

### Explicitly Out of Scope (Post-v0.2.0)

- Dashboard analytics/coverage product surface (roadmap Epic D expansion).
- LLM alt-text generation workflow.
- Sync architecture rewrite (outbox, Action Scheduler migration, delta ingest, drift reconciliation).

## Constraints

- **Greenfield policy**: no production users/data to preserve; clean rewrites are acceptable.
- **Self-hostable backend**: must run on low-cost CPU-first VPS; GPU remains optional.
- **No LocalWP private API dependency**: CI and required smoke flows must run without Local internals.
- **Plugin boundary rule**: only monorepo-managed code/config changes are in scope.
- **Sovereign model preservation**: local-read behavior and curation-first conflict policy cannot regress.

## Terminology

- **Sovereign**: plugin reads from local projection; backend is compute/sync peer.
- **Snapshot sync**: full pull via `GET /recognition/tenants/{tenant_uuid}/clusters/snapshot`.
- **Smoke gate**: deterministic E2E suite that blocks release when core production behaviors regress.

## Current State

Source:

- [v0.1.0 release notes](../../tasks/4.0/4.13.3/v0.1.0-release-notes.md)
- [v0.1.0 sovereign epic](../v0.1.0/wp-sovereign-cluster-epic.md)

### Confirmed Complete

- Sovereign local-first read path is live.
- Snapshot endpoint and projection tables are operational.
- Curation-first policy is enforced.
- Core automated unit/integration suites exist across backend, frontend, and plugin layers.
- TanStack React Query with centralized key factory and hierarchical invalidation.
- Job state machine (useJobStateMachine) with proper decomposition (effects/mutations/utils).
- Cluster edit state with useReducer pattern.
- BroadcastChannel cross-tab coordination for SSE streams.
- Bounded auto-retry on sync trigger with per-stale-cycle guard.
- 51 frontend test files covering hooks, pages, and components.
- Route-level `ErrorBoundary` protection exists in `App.tsx`, with additional cluster-surface fallback handling in `ScanTabContent`.
- `WorkbenchPage` has been decomposed into `ScanTabContent`, `BatchTabContent`, and `ConfirmTabContent`, with shared state centralized in `WorkbenchContext`.
- Tab state is URL-synced via `useTabParam`, pagination/search state is URL-persisted via `useWorkbenchFilters`, and scroll restoration exists via `useScrollRestoration`.
- `SyncStatusIndicator` renders above the workbench tab content, not only inside Scan.
- `DashboardPage` is live and backed by media, sync, retention, identity, and job-history hooks.

### Frontend Reliability Status

The originally-audited Phase 1 frontend defects are no longer release blockers:

| ID | Prior issue | Current status |
| -- | ----------- | -------------- |
| AP-1 | Missing error boundaries | Resolved via route-level `ErrorBoundary` wrappers and scoped fallbacks |
| AP-2 | AbortError left label saves stuck in a queued state | Resolved in cluster mutation handling |
| AP-3 | Scan completion force-switched tabs | Resolved; workbench no longer forces navigation on completion |
| AP-4 | No scroll/page restoration | Resolved with URL-backed filters and `useScrollRestoration` |
| AP-5 | Tabs not URL-synced | Resolved with `useTabParam` |
| AP-6 | WorkbenchPage as a god component | Resolved; page is now a thin coordinator at ~149 lines |
| AP-7 | Excessive prop drilling in workbench flows | Resolved by `WorkbenchContext` and extracted tab components |
| AP-8 | Dashboard was a static placeholder | Resolved; dashboard is now hook-backed and navigable |

### Product Gaps (Frontend)

| ID   | Gap | Status | Impact |
| ---- | --- | ------ | ------ |
| PG-1 | **Sync status only visible on Scan tab** | Resolved | — |
| PG-2 | **Batch tab is a thin read-only list** | Resolved/retired: Batch now routes users toward Dashboard and recent jobs instead of pretending to be a full workflow surface | — |
| PG-3 | **Roster Entries tab is read-only** | Resolved: roster entries support creation and deletion flows | — |
| PG-4 | **No "Entries vs Clusters" explanatory copy** | Resolved: roster hero and clusters help copy explain the distinction | — |
| PG-5 | **No loading state for SyncStatusIndicator**: returns `null` during initial fetch (invisible component) | Open | LOW |
| PG-6 | **Media detail exits the SPA** | Not currently evidenced as an active workbench media-edit flow in the current code; treat as follow-on UX constraint rather than a release-blocking gap | LOW |

### Production Gaps (Backend/Infra)

- No deterministic E2E smoke gate for outage/recovery behaviors (tracked in debt #12).
- No standardized production deployment path (image/runtime/proxy/secrets/ops docs).
- Security baseline is partial (API key exists; origin/rate/key lifecycle controls incomplete).
- Observability baseline is partial (health/readiness/structured telemetry not complete).

## Target Runtime Topology

```
WordPress host                          App VPS
|- ACX plugin + admin UI               |- FastAPI service (container)
|- Local projection tables             |- PostgreSQL + pgvector
'- Manual + scheduled sync triggers    '- Reverse proxy + TLS
```

## Phased Delivery

### Phase 1: UX Reliability and Failure Clarity (Frontend-Only)

> **Status**: complete
> **Dependencies**: none
> **Task plan source**: [background-surfacing-ui-hang-plan.md](../../tasks/4.0/4.11.2/background-surfacing-ui-hang-plan.md)

**Outcome**: Core workbench workflows are now structurally decomposed, URL-restorable, and protected against the previously-audited frontend failure modes. The remaining Phase 1 follow-on is the low-severity `SyncStatusIndicator` initial-loading invisibility (`PG-5`).

#### 1a. Critical Fixes (Antipatterns)

- Route-level and cluster-surface error boundaries are implemented.
- Abort and timeout flows no longer leave label-save UI stuck.
- Scan completion no longer force-navigates the operator away from the active tab.

#### 1b. Navigation State Continuity

- Workbench and roster tabs are URL-synced.
- Pagination and filter state are URL-backed in workbench flows.
- Scroll restoration exists for scan navigation round-trips.

#### 1c. Structural Improvement

- `SyncStatusIndicator` is visible on all workbench tabs.
- `WorkbenchPage` is under 200 lines and delegates to extracted tab content components.
- Shared state is coordinated through `WorkbenchContext` instead of the previous prop-drilling-heavy page shell.

---

### Phase 2: Deterministic E2E/Smoke Gate (Release-Critical)

> **Status**: planned
> **Dependencies**: Phase 1 provides stable UX assertions
> **Task plan**: [e2e-smoke-automation-path.md](../../tasks/tech-debt/e2e-smoke-automation-path.md)
> **Debt alignment**: promotes deferred item #12 from [current-debt.md](../../tasks/tech-debt/current-debt.md)

**Goal**: Replace ad-hoc manual smoke checks with repeatable automation that validates sovereign behavior end-to-end.

Deliverables:

- Playwright test harness for plugin E2E flows.
- WP-CLI seed/reset helpers for deterministic fixtures.
- Reproducible runtime path for CI (`wp-env` or Docker-based WP runtime).
- Deterministic outage simulation path (service stop/proxy fault injection).
- CI job that runs smoke tests and captures trace/video artifacts on failure.

Exit criteria:

- Required scenarios pass in CI:
  - offline label persistence,
  - local-read resilience with backend down,
  - sync-status transitions through outage/recovery.
- Required flow does not depend on LocalWP private APIs.

---

### Phase 3: Deployment Baseline

> **Status**: not-started
> **Dependencies**: Phase 6 (server provisioned)
> **Epic source**: [self-hosting-epic.md](./self-hosting-epic.md)

**Goal**: A new operator can deploy backend + database with one documented path.

Deliverables:

- Production Docker image for recognition service.
- Production compose stack (API + Postgres + persistent volumes).
- Environment contract (`.env.example` + required/optional var docs).
- Reverse proxy/TLS reference config.
- Model cache persistence across restarts.

Exit criteria:

- Cold start to healthy API in < 30s with warm model cache.
- Restart does not force model re-download.
- Documented runbook is sufficient for first-time deployment.

---

### Phase 4: Security Baseline

> **Status**: not-started
> **Dependencies**: external (key rotation policy decisions)

**Goal**: Default deployment is safe for internet exposure under normal small-team ops.

Deliverables:

- Strict API key validation with key fingerprint logging (no raw key logging).
- Allowlist-based browser origin policy for admin-driven requests.
- Request rate limiting with deterministic 429 behavior.
- API key rotation support (at least two valid keys during cutover).
- Plugin configuration UX for backend URL + API key validation feedback.

Exit criteria:

- Invalid/missing keys are rejected.
- Non-allowlisted browser origins cannot call privileged endpoints.
- Rotation can be performed without downtime.

---

### Phase 5: Observability Baseline

> **Status**: not-started
> **Dependencies**: Phase 6 (deployed backend to observe)

**Goal**: Failures are diagnosable without attaching debuggers or manual SSH spelunking.

Deliverables:

- Structured JSON logs with request and tenant correlation IDs.
- Health (`/health`) and readiness (`/ready`) endpoints with dependency checks.
- Request latency metrics (P50/P95/P99) and error counts by endpoint class.
- Minimal operational dashboard/runbook documenting where to inspect failures.

Exit criteria:

- Operators can answer "is it up, is it ready, why did this fail?" from logs/metrics alone.
- Correlation ID links WordPress-triggered actions to backend requests.

---

### Phase 6: Production Server Provisioning

> **Status**: in progress -- OCI baseline provisioned
> **Dependencies**: none (infrastructure provisioning; unblocks Phase 3)
> **Epic source**: [self-hosting-epic.md](./self-hosting-epic.md)

**Goal**: Provision and verify production server infrastructure so that Phase 3 (deployment baseline) has a target environment.

**Approach**: Oracle Cloud Pay-As-You-Go (PAYG) account with Always Free ARM instance. See [self-hosting-epic.md -- Oracle PAYG Evaluation](./self-hosting-epic.md#oracle-cloud-pay-as-you-go-payg-evaluation----production-backend) for full rationale.

**Why PAYG over Free Tier**: PAYG accounts retain all Always Free benefits ($0/mo for ARM instances) but receive **higher provisioning priority**, eliminating the well-documented "Out of host capacity" lottery that blocks Free Tier users for days or months. Budget alerts are the safety net against accidental charges.

Deliverables:

- **Oracle Cloud PAYG account**: Created and upgraded from Free Tier. Budget alerts still need verification/configuration evidence.
- **Backend compute instance**: `VM.Standard.A1.Flex` (4 ARM cores, 24GB RAM, 200GB boot volume). OCI network and compute are provisioned; Docker/bootstrap scaffold is present via `cloud-init`.
- **ARM compatibility verified**: Full dependency stack (onnxruntime, insightface, opencv, psycopg2/asyncpg, pgvector) confirmed working on aarch64. Integration test suite passes.
- **DNS + TLS**: Domain pointed to instance. TLS via Cloudflare free tier or Caddy auto-TLS.
- **WordPress demo page**: Shared PHP hosting (~$2-5/mo) or WP on the Oracle VPS. ACX plugin installed and configured to point at backend API.
- **End-to-end smoke**: WP plugin triggers recognition request, backend processes it, response displayed in plugin UI.

Exit criteria:

- Oracle PAYG instance is running and accessible via HTTPS.
- `docker compose up` on the instance starts FastAPI + Postgres successfully.
- InsightFace model downloads once and persists across container restarts.
- Budget alerts are active and verified (test alert triggered).
- WP demo page loads and can communicate with backend API.
- Fallback plan documented: Hetzner CX22 (~$4.35/mo) if Oracle proves unreliable.

**Cost target**: $0/mo backend + ~$2-5/mo WP hosting = ~$2-5/mo total.

## Important Follow-On Epic Stub (Tracked Here)

Follow-on epic:

- [sovereign-sync-and-workbench-ux-epic.md](../v0.2.0/sovereign-sync-and-workbench-ux-epic.md)

This v0.2.0 production epic intentionally does not gate release on the items below, but they are explicitly tracked and expected as next-wave work:

- Sovereign sync architecture expansion:
  - outbox,
  - Action Scheduler migration,
  - delta ingest,
  - drift reconciliation.
- UX continuation requirements:
  - Batch tab retirement or re-homing to Dashboard IA.
  - Roster CRUD operations and Entries vs Clusters copy clarity.
  - Previous/next media navigation controls (top and bottom).

## Post-v0.2.0 Backlog (Not Release-Blocking)

- Dashboard analytics/coverage UX (roadmap Epic D).
- LLM alt-text generation workflow and approval pipeline.
- Sovereign sync + workbench UX continuity epic:
  - [sovereign-sync-and-workbench-ux-epic.md](../v0.2.0/sovereign-sync-and-workbench-ux-epic.md)
- GPU inference tier and advanced roster analytics.

## External Dependencies

| Dependency                                                         | Owner               | Status      | Blocks           |
| ------------------------------------------------------------------ | ------------------- | ----------- | ---------------- |
| VPS/provider + DNS/TLS decisions                                   | Project owner       | In progress | Phase 3, Phase 6 |
| Oracle Cloud PAYG account setup + ARM verification                 | Project owner       | In progress | Phase 6          |
| WP demo hosting provisioning                                       | Project owner       | Not started | Phase 6          |
| CI secret provisioning for smoke/runtime tests                     | Project owner       | Not started | Phase 2, Phase 3 |
| Final policy choices for origin allowlist and key rotation cadence | Product/engineering | Not started | Phase 4          |

## Code Anchors

| Layer              | File/Area                                                                                    | Note                                                 |
| ------------------ | -------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Frontend workbench | `js/admin/pages/WorkbenchPage.tsx`                                                           | Phase 1 decomposition now landed; page is a thin shell |
| Frontend clusters  | `js/admin/pages/workbench/identity-clusters/useClusterLabelMutations.ts`                     | Abort handling path previously caused queued save hang; now fixed |
| Frontend clusters  | `js/admin/pages/workbench/identity-clusters/useClusterSaveAction.ts`                         | Save status lifecycle (Phase 1a)                     |
| Frontend sync      | `js/admin/pages/workbench/SyncStatusIndicator.tsx`                                           | Above-tab placement is landed; remaining follow-on is loading-state invisibility |
| Frontend nav       | `js/admin/App.tsx`                                                                           | Route-level error boundaries; tab URL sync is handled by `useTabParam` |
| Frontend combobox  | `js/components/ui/combobox.tsx`                                                              | Coverage should be reviewed as part of future UI-surface audits, not Phase 1 |
| Plugin sync        | `src/sovereign/sync/class-sync-pull-job.php`                                                 | Pull sync behavior and failure handling              |
| Plugin API         | `src/api/class-sync-status-controller.php`                                                   | Sync status contract                                 |
| Backend snapshot   | `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Snapshot endpoint contract                           |
| Backend deploy     | `apps/prototype-description-service/`                                                        | Deployment + health/metrics implementation area      |
| Hosting epic       | `docs/epics/v0.3.0/self-hosting-epic.md`                                                     | Server provisioning, Oracle PAYG eval, cost analysis |
| QA Automation      | `apps/prototype-wp-alt-context/tests/e2e/`                                                   | Proposed smoke gate location                         |

## Risks and Mitigations

- **Frontend decomposition risk**: refactoring WorkbenchPage might introduce regressions.
  - Mitigation: existing 51 frontend test files provide safety net; keep adding integration coverage around navigation/state transitions.
- **Automation drift risk**: smoke specs become flaky.
  - Mitigation: deterministic fixtures, bounded retries, artifact capture on failure.
- **Operational blind spots**: deploy succeeds but failures are opaque.
  - Mitigation: structured logging + readiness contracts before release cut.
- **UX ambiguity under outage**: users cannot distinguish "empty", "stale", and "in progress".
  - Mitigation: explicit sync state modeling and UI copy contracts.
- **Oracle ARM compatibility risk**: aarch64 wheels may not exist for all dependencies (especially `insightface`).
  - Mitigation: Hetzner CX22 x86 at ~$4.35/mo is the documented fallback. Test ARM compatibility locally on Apple Silicon before provisioning.
- **Oracle PAYG billing risk**: accidental non-free resource provisioning could generate charges.
  - Mitigation: budget alerts at $1/$5/$10; restrict provisioning to Always Free shapes only.

## Success Metrics

- Phase 1 (frontend) deliverable with zero backend changes required.
- Required smoke suite passes in CI without LocalWP private APIs.
- Fresh deployment reaches healthy state with documented runbook only.
- API security controls behave deterministically (auth/origin/rate/rotation).
- Operators can debug a failed sync from logs and health/ready endpoints.
- Workbench state transitions are bounded and user-visible under backend failure.
- Production server provisioned and serving recognition requests at $0-5/mo.
- WP demo page accessible and functional for product demonstrations.

---

# Consolidated Checklist

## Phase 1: UX Reliability and Failure Clarity -- COMPLETE

### 1a: Critical Fixes

- [x] Add ErrorBoundary at route level and around identity-clusters module [AP-1].
- [x] Fix "Saving..." hang: propagate AbortError to upstream onError in useClusterLabelMutations [AP-2].
- [x] Remove forced tab-switch on scan complete; use toast/notification instead [AP-3].
- [x] Add failing tests before each fix (TDD).

### 1b: Navigation State Continuity

- [x] Sync active tab to URL hash params (#/workbench?tab=scan) [AP-5].
- [x] Persist media list page/perPage in URL search params [AP-4].
- [x] Save and restore scroll position across media detail round-trips [AP-4].
- [x] Verify deep-linking works for all tab states.

### 1c: Structural Improvement

- [x] Move SyncStatusIndicator above tab content [PG-1].
- [x] Extract ScanTabContent, BatchTabContent, ConfirmTabContent from WorkbenchPage [AP-6].
- [x] Introduce WorkbenchContext to replace prop drilling [AP-7].
- [x] Reduce MediaSelection props from 18 to <10.

## Phase 2: Deterministic E2E/Smoke Gate -- PLANNED

- [ ] Scaffold Playwright E2E path for sovereign flows.
- [ ] Add WP-CLI seed/reset fixtures for deterministic setup.
- [ ] Add deterministic backend outage/recovery controls for tests.
- [ ] Automate required scenarios (offline persistence, local-read resilience, sync transitions).
- [ ] Add CI smoke job with trace/video artifacts.

## Phase 3: Deployment Baseline -- NOT STARTED

- [ ] Create production Docker image and runtime compose stack.
- [ ] Add environment contract docs (`.env.example` + runbook).
- [ ] Configure persistent model/cache volumes.
- [ ] Configure reverse proxy + TLS template.
- [ ] Verify cold start and restart behavior against exit criteria.

## Phase 4: Security Baseline -- NOT STARTED

- [ ] Enforce strict API key validation without sensitive logging.
- [ ] Add browser origin allowlist policy.
- [ ] Add rate limiting and deterministic 429 behavior.
- [ ] Implement no-downtime key rotation support.
- [ ] Add plugin-side backend URL/API key validation UX.

## Phase 5: Observability Baseline -- NOT STARTED

- [ ] Emit structured JSON logs with correlation IDs.
- [ ] Add `/health` and `/ready` endpoints with dependency checks.
- [ ] Add latency and error metrics by endpoint class.
- [ ] Document operator diagnostics flow/runbook.

## Phase 6: Production Server Provisioning -- IN PROGRESS

- [x] Create Oracle Cloud account and upgrade to PAYG.
- [ ] Configure budget alerts ($1 / $5 / $10 thresholds).
- [x] Provision `VM.Standard.A1.Flex` instance (4 ARM / 24GB / 200GB).
- [ ] Verify ARM aarch64 compatibility for all Python dependencies.
- [x] Install Docker + Docker Compose on the instance.
- [x] Configure firewall (443/HTTPS ingress only).
- [ ] Set up DNS + TLS (Cloudflare or Caddy auto-TLS).
- [ ] Deploy recognition service container and verify model cache persistence.
- [ ] Provision WP demo page (shared PHP hosting or Oracle VPS).
- [ ] Install ACX plugin on demo WP and configure backend URL.
- [ ] Run end-to-end smoke test (WP -> backend -> recognition -> response).
- [ ] Document fallback plan (Hetzner CX22 at ~$4.35/mo).

## Follow-On Stub: Sync Expansion + UX Continuity -- TRACKED

- [x] Create and link follow-on epic for sync architecture expansion + UX continuity.
- [ ] Implement outbox + Action Scheduler + delta ingest + drift reconciliation.
- [ ] Retire or move "Batch" tab into Dashboard IA.
- [ ] Add roster CRUD operations and Entries vs Clusters copy clarity.
- [ ] Add top-of-page previous/next media navigation controls.
