# E15. Public Demo Launch Readiness (v0.4.0)

> **Epic Short ID**: E15
> **Status**: active — Phase 1 + Phase 2 merged to `main` (via `b6a2e272` and predecessors); MVP narrowed to Phases 3, 4, and 6
> **Predecessors**: [production-readiness-epic.md](../v0.3.1/production-readiness-epic.md) (Phases 2-6), [self-hosting-epic.md](../v0.3.1/self-hosting-epic.md) (remaining deliverables)
> **Successor (deferred follow-ons)**: [v0.4.1/public-demo-followons-epic.md](../v0.4.1/public-demo-followons-epic.md)
> **Revision**: Apr 2026 — MVP close-out scope locked under handoff decision `scope_e15_mvp_close_intake_202604`. CI smoke-gate (Phase 5) and observability/auth follow-ons demoted to v0.4.1.

## MVP Scope (Apr 2026 close-out)

The MVP for E15 is **public WP demo URL live + one manual end-to-end pass**. Everything else moves to the [v0.4.1 follow-on epic](../v0.4.1/public-demo-followons-epic.md).

**In MVP:**

- Phase 1 — Security Baseline (E15-1, E15-1b) — merged to `main`
- Phase 2 — Observability Baseline (E15-2) — merged to `main`
- Phase 3 — WordPress Demo Provisioning (E15-3) — provider-agnostic plan
- Phase 4 — End-to-End Verification (E15-4 in progress, E15-5 manual remote E2E)
- Phase 6 — Local Sync Correctness, operator hardening, and audit closure (E15-7 in progress; E15-13, E15-14, E15-15, E15-16, and E15-17 staged under the same phase with explicit dependency order below)

**Deferred to v0.4.1:**

- Phase 5 — CI E2E smoke gate automation (was E15-6)
- E15-2b worker/queue correlation propagation
- E15-8 auth transaction isolation core
- E15-9 API key usage telemetry deferral
- E15-10 API key baseline schema alignment
- slr-1..4 session lifecycle resilience
- td-correlation-dashboards (cross-tenant correlation_id dashboards)
- td-retry-attempt-observability

## Objective

Bring the deployed recognition service from "running on the server" to "publicly accessible, secure, observable demo with a WordPress frontend." When this epic is complete, anyone with the demo URL can see the ACX plugin in action against a live recognition backend.

## Problem Statement

The backend is deployed and serving HTTPS at `api.altcontext.com` (E14-1 complete, all 6 slices verified), but five gaps prevent public exposure as a demo or MVP:

1. **Incomplete security hardening.** API key validation and tenant isolation already exist (`require_auth` in `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py` enforces hashed-key lookup, tenant header matching, and write-access gating). What is missing: browser origin allowlist (CORS), per-key rate limiting, and a key lifecycle/rotation surface. The service is internet-reachable and authenticated but not yet rate-limited or origin-restricted.
2. **No WordPress demo frontend.** There is no public-facing WP instance running the ACX plugin. The backend has no audience without a frontend.
3. **No observability.** Failures are invisible without SSH and manual log inspection. Operators cannot answer "is it up?" or "why did this fail?" without server access.
4. **No automated E2E regression path.** Manual smoke checks are the only validation. No automation prevents regressions across deploys.
5. **Local-sync correctness is incomplete.** The plugin's sovereign local-read story improved, but the remaining local-sync work still lacks a direct analyze-to-local persistence path and still carries correctness/audit findings around fallback honesty, polling bounds, and snapshot-failure visibility.

The recognition service, Docker stack, Caddy TLS proxy, persistent model cache, database, and core API authentication are all operational. The gap is the remaining hardening surface, frontend provisioning, and automated verification.

## UX Vision

- A product owner shares a URL. The visitor sees a WordPress page with the ACX plugin active, uploads or views demo media, and sees face recognition results populated from the live backend.
- If the backend is down, the plugin's sovereign local-read path shows cached data and a clear sync status indicator -- no blank screens.
- An operator monitors service health from `/health` and `/ready` endpoints without SSH, diagnoses failures from structured JSON logs with correlation IDs, and sees latency/error metrics.
- API keys are validated strictly. Non-allowlisted origins are rejected. Rate limiting produces deterministic 429 responses. Key rotation works without downtime.

## Constraints

- **Greenfield policy**: no production users or data to preserve. Clean rewrites acceptable.
- **Backend budget**: $0/mo (OCI Always Free ARM instance, already provisioned).
- **WP demo budget**: ~$2-5/mo shared PHP hosting (Hostinger, Namecheap, or equivalent).
- **Recognition-only**: InsightFace CPU inference. No VLM/Phi-3.5 for this milestone.
- **Security scope**: sufficient for controlled internet exposure under normal small-team ops, not enterprise-grade pen-test hardened.
- **Plugin boundary rule**: only monorepo-managed code/config changes.
- **Sovereign model**: local-read behavior and curation-first conflict policy must not regress.

## Terminology

- **Security baseline**: API key validation + browser origin allowlist + request rate limiting + key rotation support.
- **Observability baseline**: structured JSON logs + correlation IDs + `/health` and `/ready` endpoints + request latency metrics.
- **WP demo**: a publicly accessible WordPress instance with the ACX plugin installed, configured to communicate with the live backend.
- **E2E smoke gate**: automated Playwright test suite that validates sovereign flows end-to-end.

## Current State

### Confirmed Complete (from E14 / Production Readiness Phase 1 & 6)

- OCI `VM.Standard.A1.Flex` provisioned (4 ARM cores, 24GB RAM, 200GB disk). Running Ubuntu 24.04.
- `docker-compose.prod.yml` stack: FastAPI API + scan worker + Postgres 17/pgvector + Caddy reverse proxy.
- HTTPS live at `api.altcontext.com` with Let's Encrypt TLS via Caddy.
- DNS A records for `api`, `staging.api`, `dev.api` subdomains pointing to OCI IP.
- InsightFace models persist across container restarts in `/opt/acx-backend/data/models/`.
- Database persists in `/opt/acx-backend/data/pgdata/`.
- `acx-backend.service` systemd unit manages the Docker Compose stack.
- Frontend UX reliability (Production Readiness Phase 1): all AP-1 through AP-8 antipatterns resolved.
- `DashboardPage` is live and hook-backed.
- Route-level error boundaries, URL-synced tabs, scroll restoration all landed.

### Production Gaps (What This Epic Closes)

| Gap                                                       | Source                             | Status                                                                                 |
| --------------------------------------------------------- | ---------------------------------- | -------------------------------------------------------------------------------------- |
| API key validation + tenant isolation                     | Production Readiness Phase 4       | **Complete** (`require_auth`, `api_key_repository.py`) — pre-existing                  |
| Browser origin allowlist (CORS)                           | Production Readiness Phase 4       | **Complete — E15-1 Slice 1** (merged to `main`)                                        |
| Per-key rate limiting + deterministic 429                 | Production Readiness Phase 4       | **Complete — E15-1 Slice 2** (merged to `main`)                                        |
| Key rotation / lifecycle surface                          | Production Readiness Phase 4       | **Complete — E15-1 Slice 3** (merged to `main`)                                        |
| Plugin Settings UX (backend URL + key validation)         | Production Readiness Phase 4       | **Complete — E15-1b** (merged to `main`)                                               |
| `/health`, `/ready`, `/health/detailed` endpoints         | Production Readiness Phase 5       | **Complete — E15-2 Slice 2 + 2.5** (merged to `main`)                                  |
| Structured JSON logs + correlation IDs                    | Production Readiness Phase 5       | **Complete — E15-2 Slice 1** (merged to `main`)                                        |
| Request latency metrics + `/metrics` endpoint             | Production Readiness Phase 5       | **Complete — E15-2 Slice 3a** (merged to `main`)                                       |
| Operations runbook                                        | Production Readiness Phase 5       | **Complete — E15-2 Slice 3b** (merged to `main`)                                       |
| WordPress demo page                                       | Production Readiness Phase 6 / E14 | Not started — **E15-3** (provider-agnostic, this epic)                                 |
| Manual remote E2E verification                            | Production Readiness Phase 6 / E14 | Not started — **E15-5** (this epic)                                                    |
| OCI budget alerts not verified                            | E14 / Production Readiness Phase 6 | Not started — folded into **E15-5**                                                    |
| ARM compatibility verification                            | E14                                | Not started — folded into **E15-5** (de facto verified by running A1 instance)         |
| Dynamic IP SSH access drift                               | Tech debt                          | Folded into **E15-4 / E15-5** (Tailscale)                                              |
| Local reset bootstrap contract mismatch                   | E15-4 (in progress)                | In progress                                                                            |
| Local-sync correctness and audit closure                  | New for E15                        | In progress -- **E15-7**                                                               |
| Roster curation loop + person review projection contracts | Phase 6 follow-on                  | Planned -- **E15-13**, gated by ADR-009 and sequenced after E15-7 correctness work     |
| LocalWP batch smoke argument plumbing                     | Phase 6 verification hardening     | Planned -- **E15-14**                                                                  |
| Dashboard operator triage with existing fields            | Phase 6 operator UX hardening      | Planned -- **E15-15**                                                                  |
| Dashboard durable activity and diagnostics                | Phase 6 operator UX hardening      | Planned -- **E15-16**, after E15-15 and a recorded durable-source decision             |
| Roster person review scrub workspace                      | Phase 6 operator UX hardening      | Planned -- **E15-17**, after E15-13 projection + queue contracts land                  |
| Worker/queue correlation propagation                      | E15-2 follow-on                    | **Deferred → v0.4.1 (E15-2b)**                                                         |
| CI E2E smoke gate automation                              | Production Readiness Phase 2       | **Deferred → v0.4.1 (E15-6)**                                                          |
| Auth transaction isolation core                           | E15-1 follow-on                    | **Deferred → v0.4.1 (E15-8)**                                                          |
| API key usage telemetry                                   | E15-1 follow-on                    | **Deferred → v0.4.1 (E15-9)**                                                          |
| API key baseline schema alignment                         | E15-1 follow-on                    | **Deferred → v0.4.1 (E15-10)**                                                         |
| Session-lifecycle resilience (slr-1..4)                   | Reliability follow-on              | **Deferred → v0.4.1**                                                                  |
| Cross-tenant correlation dashboards                       | E15-2 follow-on                    | **Deferred → v0.4.1 (td-correlation-dashboards)**                                      |
| Retry/attempt-level observability                         | E15-2 follow-on                    | **Deferred → v0.4.1 (td-retry-attempt-observability)**                                 |

## Design Decisions

| Decision                                          | Rationale                                                                              |
| ------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Security before WP demo provisioning              | Cannot share a public URL until the backend is safe for internet exposure              |
| Observability before E2E smoke gate               | Need structured logs and health endpoints to debug smoke test failures                 |
| WP on separate shared hosting, not on the OCI VPS | Clean separation of concerns; inference VPS should not run PHP; ~$2-5/mo is acceptable |
| Tailscale for SSH access (replaces IP allowlist)  | Eliminates dynamic-IP drift permanently; free for personal use; 15-minute setup        |
| E2E smoke gate as final phase                     | All other infrastructure must be in place before automated tests can assert against it |

## Cross-Cutting: Branch Isolation Enforcement

All E15 implementation work must happen on feature branches, never on `main`. `PreToolUse` hooks in both harnesses enforce this by blocking code-file edits on the main branch. This was added after discovering uncommitted code changes on `main` from a prior agent session that bled into subsequent work.

**Enforcement mechanism:**

- VS Code hook: `.github/hooks/guard-main-branch.py` via `.github/hooks/terminal-guard.json`
- Claude hook: `scripts/hooks/guard-main-branch.sh` via `.claude/settings.json`
- Policy: code files (`*.py`, `*.ts`, etc.) under `apps/` or `packages/` are blocked on `main`
- Documentation: [development-workflow.md](../../agentic/rules/development-workflow.md) Branch Isolation Protocol
- The full lane orchestration (`agent-orchestrator-mcp`) is available for multi-agent parallel work but is not required for single-agent tasks. Feature branches are sufficient.

## Phased Delivery

### Phase 1: Security Baseline -- shipped

> **Status**: merged to `main` (E15-1 Slices 1–3 + E15-1b, via `feature/e15-2` → `b6a2e272`)
> **Task plans**: [E15-1. Security Baseline](../../tasks/15.0/E15-1-security-baseline-task-plan.md), [E15-1b. Plugin Settings UX](../../tasks/15.0/E15-1b-plugin-settings-ux-task-plan.md)
> **Source**: Production Readiness Phase 4

**Goal**: Default deployment is safe for internet exposure under normal small-team ops.

Deliverables (backend, owned by E15-1):

- Allowlist-based browser origin policy (CORS) for admin-driven requests.
- Per-API-key request rate limiting with deterministic 429 behavior.
- API key lifecycle support: expiry, revocation, and at least two valid keys during cutover.
- Key fingerprint logging for auth events (no raw key logging).

Plugin-side deliverables (deferred to a separate plugin task, NOT owned by E15-1):

- Plugin Settings page UX for backend URL + API key validation feedback. The plugin already has the SettingsController surface (`apps/prototype-wp-alt-context/src/api/class-settings-controller.php`) with a `/settings/test` connection probe; UX polish is a follow-on plugin task once the backend rotation/expiry contract lands.

Exit criteria:

- Existing strict API key validation continues to pass tests (no regression on `require_auth`).
- Non-allowlisted browser origins cannot call privileged endpoints.
- Rate limiting triggers deterministic 429 under sustained load against a single key.
- Rotation can be performed without downtime: a tenant can have two valid keys, the old one can be revoked, and revoked/expired keys are rejected with 401.

---

### Phase 2: Observability Baseline -- shipped

> **Status**: merged to `main` (via `feature/e15-2` → `b6a2e272`). Slices delivered: 1 (JSON logs + correlation IDs), 2 (root `/health` liveness + `/ready` dependency probe), 2.5 (consolidation + auth-gated `/health/detailed`), 3a (Prometheus metrics middleware + auth-gated `/metrics`), 3b (operations runbook). Slice 3b branch review verdict: conditional pass. Worker/queue correlation propagation deferred to **E15-2b** in [v0.4.1](../v0.4.1/public-demo-followons-epic.md).
> **Task plans**: [E15-2. Observability Baseline](../../tasks/15.0/E15-2-observability-baseline-task-plan.md)
> **Source**: Production Readiness Phase 5

**Goal**: Failures are diagnosable without SSH access or manual log inspection.

Deliverables:

- Structured JSON logs with request and tenant correlation IDs.
- Health (`/health`) and readiness (`/ready`) endpoints with dependency checks (Postgres, model cache).
- Request latency metrics (P50/P95/P99) and error counts by endpoint class.
- Minimal operational runbook documenting where to inspect failures.

Exit criteria:

- Operators can answer "is it up, is it ready, why did this fail?" from logs/metrics and HTTP endpoints alone.
- Correlation ID links WordPress-triggered actions to backend requests.

---

### Phase 3: WordPress Demo Provisioning -- not-started

> **Status**: not-started — task plan drafted Apr 2026
> **Task plans**: [E15-3. WordPress Demo Provisioning](../../tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md)
> **Source**: Production Readiness Phase 6, E14 remaining (subsumes E14 checklist items: provision WP demo hosting, install + configure ACX plugin)

**Goal**: A publicly accessible WordPress page demonstrates the ACX plugin against the live backend.

Deliverables:

- Shared PHP hosting provisioned (Hostinger Premium or equivalent, ~$2-5/mo).
- WordPress installed with ACX plugin.
- Plugin configured with `api.altcontext.com` backend URL and production API key.
- Demo content seeded: sample media library with recognizable faces for demonstration.
- Cloudflare DNS + TLS in front of the WP host.

Exit criteria:

- WP demo page loads at its public URL.
- ACX plugin admin UI is accessible and communicates with the backend API.
- Scan trigger from plugin reaches the backend and returns recognition results.
- Sovereign local-read path works when backend is temporarily unreachable.

---

### Phase 4: End-to-End Verification -- in-progress

> **Status**: in-progress — E15-4 active (local reset hardening); E15-5 task plan drafted Apr 2026 (manual remote E2E + budget alerts + Tailscale + ARM verification)
> **Task plans**: [E15-4. Local Reset Bootstrap Hardening](../../tasks/15.0/E15-4-local-reset-bootstrap-hardening-task-plan.md), [E15-5. Manual Remote E2E + Production Smoke](../../tasks/15.0/E15-5-manual-remote-e2e-task-plan.md)
> **Source**: Production Readiness Phase 6 exit criteria; subsumes E14 checklist items: configure budget alerts, verify ARM compatibility, end-to-end smoke test, dynamic IP SSH access drift

**Goal**: Prove the full WP-to-backend-to-recognition round trip works under realistic conditions.

Deliverables:

- End-to-end smoke test: WP plugin triggers recognition request, backend processes it, response displayed in plugin UI.
- Local reset bootstrap hardening (E15-4, in progress): `make reset` works from clean checkout.
- OCI budget alerts verified ($1/$5/$10 thresholds active and tested).
- Fallback plan documented (Hetzner CX22 at ~$4.35/mo if Oracle proves unreliable).
- Dynamic IP SSH drift resolved (Tailscale or equivalent persistent fix).

Exit criteria:

- WP demo page can trigger a recognition scan and display results.
- Local dev reset works from a clean checkout without undocumented manual steps.
- Budget alerts are active and one test alert has been verified.
- SSH access works reliably without IP-dependent terraform apply.

---

### Phase 5: E2E Smoke Gate Automation -- DEFERRED to v0.4.1

> **Status**: deferred — moved to [v0.4.1 follow-on epic](../v0.4.1/public-demo-followons-epic.md) under handoff decision `scope_e15_mvp_close_intake_202604` (Apr 2026 MVP narrowing)
> **Task plans**: [E15-6. E2E Smoke Gate Automation (stub)](../../tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md) — promoted to full plan inside v0.4.1
> **Source**: Production Readiness Phase 2

Rationale: MVP completion signal is "demo URL live + manual E2E pass once". CI smoke automation is high-value follow-on but not blocking for the public-demo launch. Manual verification covered by E15-5.

---

### Phase 6: Local Sync Correctness and Audit Closure -- in-progress

> **Status**: in-progress
> **Task plans**: [E15-7. Local Sync Completion and Audit Closure](../../tasks/15.0/E15-7-local-sync-completion-and-audit-closure-task-plan.md), [E15-13. Recognition Roster Curation Loop](../../tasks/15.0/E15-13-roster-curation-loop-task-plan.md), [E15-14. LocalWP Batch Smoke Argument Plumbing](../../tasks/15.0/E15-14-localwp-batch-smoke-argument-plumbing-task-plan.md), [E15-15. Dashboard Operator Triage with Existing Fields](../../tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md), [E15-16. Dashboard Durable Activity and Diagnostics](../../tasks/15.0/E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md), [E15-17. Roster Person Review Scrub Workspace](../../tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md)
> **Source**: runtime investigation follow-up on sovereign local-read correctness

**Goal**: Finish the remaining local-sync work so completed analyze/clustering flows produce durable local state, fallback envelopes stay contract-honest, and the sovereign read path can be merged with clean review evidence.

Deliverables:

- A direct local persistence path from completed analyze/clustering work into the local projection, rather than relying entirely on a later snapshot pull.
- Truthful fallback response metadata and bounded projection-trigger behavior during polling.
- Explicit handling or surfacing of snapshot/auth failure state when backend-side auth regressions would otherwise leave local-sync degradation silent.
- Review/audit closure for the remaining local-sync findings, with commit-backed evidence and a passing close check.
- ADR-009-gated curation-loop planning and implementation ordering for E15-13 and E15-17, so person-review and curriculum-queue work stays attached to the same sovereign correctness track.
- Phase-6 verification and operator-hardening follow-ons: E15-14 for trustworthy LocalWP smoke evidence, E15-15 for existing-field dashboard triage, and E15-16 for durable dashboard activity/diagnostics.

Phase 6 execution order:

1. E15-7 closes the sovereign local-sync correctness and audit findings.
2. E15-13 starts after ADR-009 review acceptance and lands the roster curation loop, person projection, and queue contracts.
3. E15-14 can run independently once LocalWP smoke evidence is prioritized, but still reports under Phase 6 because it hardens demo-readiness correctness proof.
4. E15-15 reshapes dashboard triage using existing fields only.
5. E15-16 follows E15-15 and records a durable activity-source decision before changing dashboard activity authority.
6. E15-17 follows E15-13 and consumes the landed RCL-002, RCL-004, RCL-005, and RCL-008 contracts rather than inventing parallel roster-review surfaces.

Exit criteria:

- Analyze completion leaves durable local state or an explicit degraded status even when snapshot fetch is unavailable immediately afterward.
- Fallback envelopes do not invent unsupported metadata or contradictory projection status.
- Remaining local-sync findings are fixed or explicitly deferred with rationale.
- `handoff_close_check(enforce=True, current_commit_sha=<HEAD>)` passes for the merge candidate branch.

## External Dependencies

| Dependency                              | Owner   | Status                  | Blocks  |
| --------------------------------------- | ------- | ----------------------- | ------- |
| WP shared hosting provisioning + domain | @daniel | Not started             | Phase 3 |
| API key / origin policy decisions       | @daniel | Not started             | Phase 1 |
| OCI budget alert verification           | @daniel | Not started             | Phase 4 |
| Tailscale installation on OCI VM        | @daniel | Implemented/documented  | Phase 4 |
| CI secret provisioning for smoke tests  | @daniel | Not started             | Phase 5 |

## Code Anchors

| Layer              | File                                                                                  | Note                                        |
| ------------------ | ------------------------------------------------------------------------------------- | ------------------------------------------- |
| Backend API entry  | `apps/prototype-description-service/api/main.py`                                      | Security middleware, health/ready endpoints |
| Backend deploy     | `apps/prototype-description-service/docker-compose.prod.yml`                          | Production stack definition                 |
| Backend Caddy      | `apps/prototype-description-service/Caddyfile`                                        | Reverse proxy + TLS config                  |
| Backend env        | `apps/prototype-description-service/.env.prod.example`                                | Production env contract                     |
| Backend reset      | `apps/prototype-description-service/scripts/reset_dev_db.sh`                          | Local reset (E15-4 scope)                   |
| Infra              | `infra/oci/`                                                                          | Terraform module, cloud-init, retry tooling |
| Plugin sync        | `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php`            | WP-to-backend sync path                     |
| Plugin API         | `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php`              | Sync status for E2E verification            |
| Frontend workbench | `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`                      | Demo UX surface                             |
| QA automation      | `apps/prototype-wp-alt-context/tests/e2e/`                                            | Proposed smoke gate location                |
| Tech debt          | `docs/tasks/tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md`        | SSH drift resolution                        |

## Risks and Mitigations

- **Security gap exposure**: Sharing the demo URL before Phase 1 is complete exposes an unhardened API.
  - Mitigation: Phase ordering enforces security before WP provisioning.
- **Oracle ARM reliability**: OCI Free Tier ARM instances have documented reliability concerns.
  - Mitigation: Hetzner CX22 fallback documented; migration is a docker compose transfer.
- **Shared hosting PHP constraints**: Some cheap hosts limit cron, memory, or plugin complexity.
  - Mitigation: Choose a host with confirmed PHP 8.1+, real cron, and adequate resource limits before committing.
- **E2E test flakiness**: Smoke specs against real infrastructure can be flaky.
  - Mitigation: Deterministic fixtures, bounded retries, artifact capture on failure.

## Success Metrics

- Public demo URL accessible and functional for product demonstrations.
- Backend API rejects invalid keys, non-allowlisted origins, and excess request rates.
- Operator can diagnose a failed sync from HTTP endpoints and structured logs alone.
- E2E smoke suite passes in CI without LocalWP private APIs.
- Monthly cost: $0 backend + ~$2-5 WP hosting = ~$2-5/mo total.

---

## Consolidated Checklist

## Phase 1: Security Baseline -- SHIPPED → [E15-1](../../tasks/15.0/E15-1-security-baseline-task-plan.md), [E15-1b](../../tasks/15.0/E15-1b-plugin-settings-ux-task-plan.md)

> Source: Production Readiness Phase 4 + E14 Phase 1

- [x] Enforce strict API key validation without sensitive logging ← _Prod Readiness P4_
- [x] Add browser origin allowlist policy ← _Prod Readiness P4 + E14 P1_
- [x] Add rate limiting and deterministic 429 behavior ← _Prod Readiness P4_
- [x] Implement no-downtime key rotation + beta-tester key provisioning ← _Prod Readiness P4_
- [x] Add plugin-side backend URL/API key validation UX ← _Prod Readiness P4 (E15-1b)_

## Phase 2: Observability Baseline -- SHIPPED → [E15-2](../../tasks/15.0/E15-2-observability-baseline-task-plan.md)

> Source: Production Readiness Phase 5

- [x] Emit structured JSON logs with correlation IDs ← _Prod Readiness P5 (Slice 1)_
- [x] Add `/health` and `/ready` endpoints with dependency checks ← _Prod Readiness P5 (Slices 2 + 2.5)_
- [x] Add latency and error metrics by endpoint class ← _Prod Readiness P5 (Slice 3a)_
- [x] Document operator diagnostics flow/runbook ← _Prod Readiness P5 (Slice 3b)_

## Phase 3: WordPress Demo Provisioning -- NOT STARTED → [E15-3](../../tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md)

> Source: Production Readiness Phase 6 + E14 remaining

- [ ] Provision shared PHP hosting (provider-agnostic; vendor selected at provisioning time) ← _Prod Readiness P6_
- [ ] Install WordPress + ACX plugin ← _Prod Readiness P6 + E14_
- [ ] Configure plugin with production backend URL and API key ← _Prod Readiness P6 + E14_
- [ ] Seed demo content (media library with sample faces) ← _new for E15_
- [ ] Set up Cloudflare DNS + TLS for WP host ← _Prod Readiness P6_

## Phase 4: End-to-End Verification -- IN PROGRESS → [E15-4](../../tasks/15.0/E15-4-local-reset-bootstrap-hardening-task-plan.md) + [E15-5](../../tasks/15.0/E15-5-manual-remote-e2e-task-plan.md)

> Source: Production Readiness Phase 6 exit criteria + [tech-debt/dynamic-ip-ssh-access.md](../../tasks/tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md)

- [ ] Complete local reset bootstrap hardening (E15-4, in progress) ← _finding INVEST-reset-env-contract-mismatch_
- [ ] Verify OCI budget alerts ($1/$5/$10 thresholds) ← _Prod Readiness P6 + E14 (E15-5)_
- [x] Resolve dynamic IP SSH access drift (Tailscale) ← _[tech-debt/dynamic-ip-ssh-access.md](../../tasks/tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md) (implemented/documented)_
- [ ] Run end-to-end WP → backend → recognition → response smoke test ← _Prod Readiness P6 + E14 (E15-5)_
- [ ] Document Hetzner CX22 fallback plan ← _Prod Readiness P6 + E14 (E15-5)_
- [ ] Capture ARM compatibility verification evidence ← _E14 (E15-5; de facto verified by running A1 instance, but missing recorded artifact)_

## Phase 5: E2E Smoke Gate Automation -- DEFERRED → [v0.4.1](../v0.4.1/public-demo-followons-epic.md)

> Source: Production Readiness Phase 2. Deferred under handoff decision `scope_e15_mvp_close_intake_202604`.

All Phase 5 deliverables move to the v0.4.1 follow-on epic. MVP-blocking scenarios (offline persistence, local-read resilience, sync transitions) are validated manually as part of E15-5.

## Phase 6: Local Sync Correctness -- IN PROGRESS → [E15-7](../../tasks/15.0/E15-7-local-sync-completion-and-audit-closure-task-plan.md)

> Source: runtime investigation follow-up on sovereign local-read correctness

- [ ] Direct local persistence path from completed analyze/clustering work into local projection ← _E15-7_
- [ ] Truthful fallback response metadata + bounded projection-trigger behavior during polling ← _E15-7_
- [ ] Snapshot/auth failure visibility ← _E15-7_
- [ ] `handoff_close_check(enforce=True)` passes on merge candidate ← _E15-7_
