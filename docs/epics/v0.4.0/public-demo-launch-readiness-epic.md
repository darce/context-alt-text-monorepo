# E15. Public Demo Launch Readiness (v0.4.0)

> **Epic Short ID**: E15
> **Status**: active
> **Predecessors**: [production-readiness-epic.md](../v0.3.1/production-readiness-epic.md) (Phases 2-6), [self-hosting-epic.md](../v0.3.1/self-hosting-epic.md) (remaining deliverables)

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

| Gap | Source | Status |
|-----|--------|--------|
| API key validation + tenant isolation | Production Readiness Phase 4 | **Already implemented** (`require_auth`, `api_key_repository.py`) |
| No browser origin allowlist (CORS) | Production Readiness Phase 4 | Not started -- **E15-1 Slice 2** |
| No per-key rate limiting / 429 behavior | Production Readiness Phase 4 | Not started -- **E15-1 Slice 1** |
| No key rotation/lifecycle surface | Production Readiness Phase 4 | Not started -- **E15-1 Slice 3** |
| No `/health` or `/ready` endpoints with dependency checks | Production Readiness Phase 5 | Not started |
| No structured JSON logs or correlation IDs | Production Readiness Phase 5 | Not started |
| No request latency metrics | Production Readiness Phase 5 | Not started |
| No WordPress demo page | Production Readiness Phase 6 / E14 | Not started |
| No E2E smoke gate automation | Production Readiness Phase 2 | Planned |
| Local reset bootstrap contract mismatch | E15-4 (in progress) | In progress |
| Local-sync correctness and audit closure | New for E15 | In progress -- **E15-7** |
| OCI budget alerts not verified | E14 / Production Readiness Phase 6 | Not started |
| Dynamic IP SSH access drift | Tech debt | Decision pending |

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Security before WP demo provisioning | Cannot share a public URL until the backend is safe for internet exposure |
| Observability before E2E smoke gate | Need structured logs and health endpoints to debug smoke test failures |
| WP on separate shared hosting, not on the OCI VPS | Clean separation of concerns; inference VPS should not run PHP; ~$2-5/mo is acceptable |
| Tailscale for SSH access (replaces IP allowlist) | Eliminates dynamic-IP drift permanently; free for personal use; 15-minute setup |
| E2E smoke gate as final phase | All other infrastructure must be in place before automated tests can assert against it |

## Cross-Cutting: Branch Isolation Enforcement

All E15 implementation work must happen on feature branches, never on `main`. `PreToolUse` hooks in both harnesses enforce this by blocking code-file edits on the main branch. This was added after discovering uncommitted code changes on `main` from a prior agent session that bled into subsequent work.

**Enforcement mechanism:**
- VS Code hook: `.github/hooks/guard-main-branch.py` via `.github/hooks/terminal-guard.json`
- Claude hook: `scripts/hooks/guard-main-branch.sh` via `.claude/settings.json`
- Policy: code files (`*.py`, `*.ts`, etc.) under `apps/` or `packages/` are blocked on `main`
- Documentation: [development-workflow.md](../../agentic/rules/development-workflow.md) Branch Isolation Protocol
- The full lane orchestration (`agent-orchestrator-mcp`) is available for multi-agent parallel work but is not required for single-agent tasks. Feature branches are sufficient.

## Phased Delivery

### Phase 1: Security Baseline -- not-started

> **Status**: not-started
> **Task plans**: [E15-1. Security Baseline](../../tasks/15.0/E15-1-security-baseline-task-plan.md)
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

### Phase 2: Observability Baseline -- not-started

> **Status**: not-started
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

> **Status**: not-started
> **Task plans**: E15-3 (to be scoped)
> **Source**: Production Readiness Phase 6, E14 remaining

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

### Phase 4: End-to-End Verification -- not-started

> **Status**: not-started
> **Task plans**: E15-4 (existing: local reset hardening) + E15-5 (to be scoped: remote e2e)
> **Source**: Production Readiness Phase 6 exit criteria

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

### Phase 5: E2E Smoke Gate Automation -- not-started

> **Status**: not-started
> **Task plans**: E15-6 (to be scoped)
> **Source**: Production Readiness Phase 2

**Goal**: Replace ad-hoc manual smoke checks with repeatable automation that validates sovereign behavior end-to-end.

Deliverables:

- Playwright test harness for plugin E2E flows.
- WP-CLI seed/reset helpers for deterministic fixtures.
- Reproducible runtime path for CI (`wp-env` or Docker-based WP runtime).
- Deterministic outage simulation path (service stop/proxy fault injection).
- CI job that runs smoke tests and captures trace/video artifacts on failure.

Exit criteria:

- Required scenarios pass in CI:
  - Offline label persistence.

---

### Phase 6: Local Sync Correctness and Audit Closure -- in-progress

> **Status**: in-progress
> **Task plans**: [E15-7. Local Sync Completion and Audit Closure](../../tasks/15.0/E15-7-local-sync-completion-and-audit-closure-task-plan.md)
> **Source**: runtime investigation follow-up on sovereign local-read correctness

**Goal**: Finish the remaining local-sync work so completed analyze/clustering flows produce durable local state, fallback envelopes stay contract-honest, and the sovereign read path can be merged with clean review evidence.

Deliverables:

- A direct local persistence path from completed analyze/clustering work into the local projection, rather than relying entirely on a later snapshot pull.
- Truthful fallback response metadata and bounded projection-trigger behavior during polling.
- Explicit handling or surfacing of snapshot/auth failure state when backend-side auth regressions would otherwise leave local-sync degradation silent.
- Review/audit closure for the remaining local-sync findings, with commit-backed evidence and a passing close check.

Exit criteria:

- Analyze completion leaves durable local state or an explicit degraded status even when snapshot fetch is unavailable immediately afterward.
- Fallback envelopes do not invent unsupported metadata or contradictory projection status.
- Remaining local-sync findings are fixed or explicitly deferred with rationale.
- `handoff_close_check(enforce=True, current_commit_sha=<HEAD>)` passes for the merge candidate branch.
  - Local-read resilience with backend down.
  - Sync-status transitions through outage/recovery.
- Required flow does not depend on LocalWP private APIs.

## External Dependencies

| Dependency | Owner | Status | Blocks |
|------------|-------|--------|--------|
| WP shared hosting provisioning + domain | @daniel | Not started | Phase 3 |
| API key / origin policy decisions | @daniel | Not started | Phase 1 |
| OCI budget alert verification | @daniel | Not started | Phase 4 |
| Tailscale installation on OCI VM | @daniel | Not started | Phase 4 |
| CI secret provisioning for smoke tests | @daniel | Not started | Phase 5 |

## Code Anchors

| Layer | File | Note |
|-------|------|------|
| Backend API entry | `apps/prototype-description-service/api/main.py` | Security middleware, health/ready endpoints |
| Backend deploy | `apps/prototype-description-service/docker-compose.prod.yml` | Production stack definition |
| Backend Caddy | `apps/prototype-description-service/Caddyfile` | Reverse proxy + TLS config |
| Backend env | `apps/prototype-description-service/.env.prod.example` | Production env contract |
| Backend reset | `apps/prototype-description-service/scripts/reset_dev_db.sh` | Local reset (E15-4 scope) |
| Infra | `infra/oci/` | Terraform module, cloud-init, retry tooling |
| Plugin sync | `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php` | WP-to-backend sync path |
| Plugin API | `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | Sync status for E2E verification |
| Frontend workbench | `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` | Demo UX surface |
| QA automation | `apps/prototype-wp-alt-context/tests/e2e/` | Proposed smoke gate location |
| Tech debt | `docs/tasks/tech-debt/dynamic-ip-ssh-access.md` | SSH drift resolution |

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

# Consolidated Checklist

## Phase 1: Security Baseline -- NOT STARTED → [E15-1](../../tasks/15.0/E15-1-security-baseline-task-plan.md)

> Source: Production Readiness Phase 4 + E14 Phase 1

- [ ] Enforce strict API key validation without sensitive logging ← *Prod Readiness P4*
- [ ] Add browser origin allowlist policy ← *Prod Readiness P4 + E14 P1*
- [ ] Add rate limiting and deterministic 429 behavior ← *Prod Readiness P4*
- [ ] Implement no-downtime key rotation + beta-tester key provisioning ← *Prod Readiness P4*
- [ ] Add plugin-side backend URL/API key validation UX ← *Prod Readiness P4*

## Phase 2: Observability Baseline -- NOT STARTED → [E15-2](../../tasks/15.0/E15-2-observability-baseline-task-plan.md)

> Source: Production Readiness Phase 5

- [ ] Emit structured JSON logs with correlation IDs ← *Prod Readiness P5*
- [ ] Add `/health` and `/ready` endpoints with dependency checks ← *Prod Readiness P5*
- [ ] Add latency and error metrics by endpoint class ← *Prod Readiness P5*
- [ ] Document operator diagnostics flow/runbook ← *Prod Readiness P5*

## Phase 3: WordPress Demo Provisioning -- NOT STARTED → [E15-3](../../tasks/15.0/E15-3-wordpress-demo-provisioning-stub.md) (to be scoped)

> Source: Production Readiness Phase 6 + E14 remaining

- [ ] Provision shared PHP hosting ← *Prod Readiness P6*
- [ ] Install WordPress + ACX plugin ← *Prod Readiness P6 + E14*
- [ ] Configure plugin with production backend URL and API key ← *Prod Readiness P6 + E14*
- [ ] Seed demo content (media library with sample faces) ← *new for E15*
- [ ] Set up Cloudflare DNS + TLS for WP host ← *Prod Readiness P6*

## Phase 4: End-to-End Verification -- IN PROGRESS → [E15-4](../../tasks/15.0/E15-4-local-reset-bootstrap-hardening-task-plan.md) + [E15-5](../../tasks/15.0/E15-5-remote-e2e-verification-stub.md) (to be scoped)

> Source: Production Readiness Phase 6 exit criteria + [tech-debt/dynamic-ip-ssh-access.md](../../tasks/tech-debt/dynamic-ip-ssh-access.md)

- [ ] Complete local reset bootstrap hardening (E15-4, in progress) ← *finding INVEST-reset-env-contract-mismatch*
- [ ] Verify OCI budget alerts ($1/$5/$10 thresholds) ← *Prod Readiness P6 + E14*
- [ ] Resolve dynamic IP SSH access drift (Tailscale) ← *[tech-debt/dynamic-ip-ssh-access.md](../../tasks/tech-debt/dynamic-ip-ssh-access.md)*
- [ ] Run end-to-end WP → backend → recognition → response smoke test ← *Prod Readiness P6 + E14*
- [ ] Document Hetzner CX22 fallback plan ← *Prod Readiness P6 + E14*

## Phase 5: E2E Smoke Gate Automation -- NOT STARTED → [E15-6](../../tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md) (to be scoped)

> Source: Production Readiness Phase 2

- [ ] Scaffold Playwright E2E path for sovereign flows ← *Prod Readiness P2*
- [ ] Add WP-CLI seed/reset fixtures for deterministic setup ← *Prod Readiness P2*
- [ ] Add deterministic backend outage/recovery controls for tests ← *Prod Readiness P2*
- [ ] Automate required scenarios (offline persistence, local-read resilience, sync transitions) ← *Prod Readiness P2*
- [ ] Add CI smoke job with trace/video artifacts ← *Prod Readiness P2*
