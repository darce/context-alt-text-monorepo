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
- Internet-facing security baseline (auth hardening, origin policy, rate limiting, key rotation).
- Observability baseline (structured logs, health/readiness, correlation IDs, latency metrics).

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
- 33 frontend test files covering hooks, pages, and components.

### Confirmed Antipatterns (Frontend)

| ID | Issue | Severity | Location |
| --- | --- | --- | --- |
| AP-1 | **No Error Boundaries**: render error in any cluster component crashes entire SPA | HIGH | Entire app -- no `ErrorBoundary` wrapper anywhere |
| AP-2 | **"Saving..." hang on AbortError**: `onError` in `useClusterLabelMutations` returns early on AbortError after `invalidateQueries()` without calling the upstream `onError` callback, so `saveStatus` stays "queued" permanently | HIGH | `useClusterLabelMutations.ts` L63-66 |
| AP-3 | **Force-navigation on scan complete**: `onScanComplete` always calls `setActiveSection(TAB_IDS.confirm)` regardless of user's current activity | MEDIUM | `WorkbenchPage.tsx` L179 |
| AP-4 | **No scroll/page restoration**: zero `scrollRestoration` or URL-persisted pagination; users lose position on every navigation | MEDIUM | All routes |
| AP-5 | **Tab state not URL-synced**: tabs are `useState` only; navigating away and back resets the active tab | MEDIUM | `WorkbenchPage.tsx` L108, `RosterPage.tsx` L23 |
| AP-6 | **God-component WorkbenchPage** (~428 lines): orchestrates scan, job state, clustering, media selection, and 3 tab panels directly; passes 18+ props to MediaSelection | MEDIUM | `WorkbenchPage.tsx` |
| AP-7 | **Massive prop drilling**: MediaSelection receives 18 props, ClusterDrawerPanel receives 20+ props; no React Context for shared state | MEDIUM | `WorkbenchPage.tsx` L321-349, `ClusterDrawerPanel.tsx` |
| AP-8 | **DashboardPage is static placeholder**: no live data, no navigation shortcuts, no coverage summary | LOW | `DashboardPage.tsx` |

### Product Gaps (Frontend)

| ID | Gap | Impact |
| --- | --- | --- |
| PG-1 | **Sync status only visible on Scan tab**: SyncStatusIndicator renders inside Scan tab content only; users on Batch/Confirm tabs have no sync visibility | MEDIUM |
| PG-2 | **Batch tab is a thin read-only list**: no batch configuration, queue management, or progress; selection must happen on Scan tab first | MEDIUM |
| PG-3 | **Roster Entries tab is read-only**: no create/edit/delete actions for roster entries | MEDIUM |
| PG-4 | **No "Entries vs Clusters" explanatory copy**: operator cannot understand the distinction from UI alone | LOW |
| PG-5 | **No loading state for SyncStatusIndicator**: returns `null` during initial fetch (invisible component) | LOW |
| PG-6 | **Media detail exits the SPA**: clicking a media item navigates to WordPress `post.php?action=edit`, losing all SPA context | LOW (architectural constraint) |

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

> **Status**: priority -- ready to start
> **Dependencies**: none (all changes are frontend-only)
> **Task plan source**: [background-surfacing-ui-hang-plan.md](../../tasks/4.0/4.11.2/background-surfacing-ui-hang-plan.md)

**Goal**: Core workbench workflows are reliable, recoverable under degraded backend conditions, and structurally sound.

#### 1a. Critical Fixes (Antipatterns)

Deliverables:

- **Error Boundaries** [AP-1]: Add `ErrorBoundary` wrappers at route level and around identity-clusters module. Render fallback UI with retry instead of white screen.
- **"Saving..." hang fix** [AP-2]: Ensure `onError` in `useClusterLabelMutations` propagates to upstream callback on AbortError paths so `saveStatus` resets to idle. Add failing test first (TDD).
- **Non-disruptive scan complete** [AP-3]: Remove forced `setActiveSection(TAB_IDS.confirm)` from `onScanComplete`. Show a toast/notification instead, letting user navigate to Confirm when ready.

Exit criteria:

- Render error in any cluster component shows fallback, does not crash SPA.
- Label mutation that times out or aborts resets to idle within bounded time (test-verified).
- Scan completion does not move the user away from their current tab.

#### 1b. Navigation State Continuity

Deliverables:

- **URL-synced tabs** [AP-5]: Sync active tab to hash params (`#/workbench?tab=scan`). Restore tab on mount from URL.
- **URL-persisted pagination** [AP-4]: Persist `page` and `perPage` in URL search params. Restore on return.
- **Scroll restoration**: Save scroll position before media detail navigation. Restore on return via `popstate` or back-button.

Exit criteria:

- Tab state survives page refresh and navigation round-trips.
- Media list page/scroll position is restored when returning from WordPress media editor.
- Deep-linking to `#/workbench?tab=confirm` works.

#### 1c. Structural Improvement

Deliverables:

- **Sync status visibility** [PG-1]: Move `SyncStatusIndicator` above tabs so it is visible regardless of active tab.
- **WorkbenchPage decomposition** [AP-6]: Extract tab content into `ScanTabContent`, `BatchTabContent`, `ConfirmTabContent` components. Introduce a `WorkbenchContext` (React Context) for shared state to reduce prop drilling [AP-7].

Exit criteria:

- `SyncStatusIndicator` visible on all workbench tabs.
- WorkbenchPage is under 200 lines. No component receives more than 10 props.
- MediaSelection props reduced from 18 to <10 via context.

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
> **Dependencies**: external (VPS/provider + DNS decisions)
> **Task plan source**: [self-hosting-implementation.md](../../tasks/4.0/4.13.0/self-hosting-implementation.md)

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

**Goal**: Failures are diagnosable without attaching debuggers or manual SSH spelunking.

Deliverables:

- Structured JSON logs with request and tenant correlation IDs.
- Health (`/health`) and readiness (`/ready`) endpoints with dependency checks.
- Request latency metrics (P50/P95/P99) and error counts by endpoint class.
- Minimal operational dashboard/runbook documenting where to inspect failures.

Exit criteria:

- Operators can answer "is it up, is it ready, why did this fail?" from logs/metrics alone.
- Correlation ID links WordPress-triggered actions to backend requests.

## Important Follow-On Epic Stub (Tracked Here)

Follow-on epic:

- [sovereign-sync-and-workbench-ux-epic.md](./sovereign-sync-and-workbench-ux-epic.md)

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
  - [sovereign-sync-and-workbench-ux-epic.md](./sovereign-sync-and-workbench-ux-epic.md)
- GPU inference tier and advanced roster analytics.

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| VPS/provider + DNS/TLS decisions | Project owner | Not started | Phase 3 |
| CI secret provisioning for smoke/runtime tests | Project owner | Not started | Phase 2, Phase 3 |
| Final policy choices for origin allowlist and key rotation cadence | Product/engineering | Not started | Phase 4 |

## Code Anchors

| Layer | File/Area | Note |
| --- | --- | --- |
| Frontend workbench | `js/admin/pages/WorkbenchPage.tsx` | God-component decomposition target (Phase 1c) |
| Frontend clusters | `js/admin/pages/workbench/identity-clusters/useClusterLabelMutations.ts` | "Saving..." hang: AbortError path (Phase 1a) |
| Frontend clusters | `js/admin/pages/workbench/identity-clusters/useClusterSaveAction.ts` | Save status lifecycle (Phase 1a) |
| Frontend sync | `js/admin/pages/workbench/SyncStatusIndicator.tsx` | Move above tabs (Phase 1c) |
| Frontend nav | `js/admin/App.tsx` | HashRouter, tab URL sync (Phase 1b) |
| Frontend combobox | `js/components/ui/combobox.tsx` | Untested -- add coverage (Phase 1a) |
| Plugin sync | `src/sovereign/sync/class-sync-pull-job.php` | Pull sync behavior and failure handling |
| Plugin API | `src/api/class-sync-status-controller.php` | Sync status contract |
| Backend snapshot | `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Snapshot endpoint contract |
| Backend deploy | `apps/prototype-description-service/` | Deployment + health/metrics implementation area |
| QA Automation | `apps/prototype-wp-alt-context/tests/e2e/` | Proposed smoke gate location |

## Risks and Mitigations

- **Frontend decomposition risk**: refactoring WorkbenchPage might introduce regressions.
  - Mitigation: existing 33 test files provide safety net; add integration tests before extracting components.
- **Automation drift risk**: smoke specs become flaky.
  - Mitigation: deterministic fixtures, bounded retries, artifact capture on failure.
- **Operational blind spots**: deploy succeeds but failures are opaque.
  - Mitigation: structured logging + readiness contracts before release cut.
- **UX ambiguity under outage**: users cannot distinguish "empty", "stale", and "in progress".
  - Mitigation: explicit sync state modeling and UI copy contracts.

## Success Metrics

- Phase 1 (frontend) deliverable with zero backend changes required.
- Required smoke suite passes in CI without LocalWP private APIs.
- Fresh deployment reaches healthy state with documented runbook only.
- API security controls behave deterministically (auth/origin/rate/rotation).
- Operators can debug a failed sync from logs and health/ready endpoints.
- Workbench state transitions are bounded and user-visible under backend failure.

---

# Consolidated Checklist

## Phase 1: UX Reliability and Failure Clarity -- READY TO START

### 1a: Critical Fixes

- [ ] Add ErrorBoundary at route level and around identity-clusters module [AP-1].
- [ ] Fix "Saving..." hang: propagate AbortError to upstream onError in useClusterLabelMutations [AP-2].
- [ ] Remove forced tab-switch on scan complete; use toast/notification instead [AP-3].
- [ ] Add failing tests before each fix (TDD).

### 1b: Navigation State Continuity

- [ ] Sync active tab to URL hash params (#/workbench?tab=scan) [AP-5].
- [ ] Persist media list page/perPage in URL search params [AP-4].
- [ ] Save and restore scroll position across media detail round-trips [AP-4].
- [ ] Verify deep-linking works for all tab states.

### 1c: Structural Improvement

- [ ] Move SyncStatusIndicator above tab content [PG-1].
- [ ] Extract ScanTabContent, BatchTabContent, ConfirmTabContent from WorkbenchPage [AP-6].
- [ ] Introduce WorkbenchContext to replace prop drilling [AP-7].
- [ ] Reduce MediaSelection props from 18 to <10.

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

## Follow-On Stub: Sync Expansion + UX Continuity -- TRACKED

- [x] Create and link follow-on epic for sync architecture expansion + UX continuity.
- [ ] Implement outbox + Action Scheduler + delta ingest + drift reconciliation.
- [ ] Retire or move "Batch" tab into Dashboard IA.
- [ ] Add roster CRUD operations and Entries vs Clusters copy clarity.
- [ ] Add top-of-page previous/next media navigation controls.
