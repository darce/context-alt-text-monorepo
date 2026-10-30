# E15. Public Demo Launch Readiness (v0.4.0)

> **Source-of-truth status — 2026-10-30:** the [current roadmap status and continuation](../../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md#current-status-2026-10-30) supersede this epic's older actionable provisioning/status guidance. Source/runtime fixes and six-site **0.0.42** installation are complete. E15-38/E15-39/DESCPICK-5 have an accepted **planning** baseline (MCP 20609); their stale `proposed` headers do not reopen planning, and acceptance does not prove their implementation or quality comparisons shipped.

## Current continuation (2026-10-30)

Resume continuation `cont-20261030T200707380516Z-c947ce09` against accepted main `bda5a0d4ac75c5bf4c2ea0a0750252cef84995fc`, tree `ada3873a1c8aa67c7d9b0bd093e22e62dec6231a`. The six LocalWP sites (`fir`, `wp-context-alt-text`, `vlm`, `r`, `auraface-prod`, `insightface`) serve artifact SHA-256 `60038e0e11ed284fdd466c0c9b3ee95c518fb2e679a2b73c847082e6a86f7c33`. Consume `.task-state/localwp-rollout-20261030/rollout-result.json` for installation/assets/navigation and `.task-state/fircold-20261030/runtime-acceptance.json` (decision 20802) for accepted runtime scope. Retain all four persistent Compose overlays and current site bindings; do not reinstall or redo completed source/runtime cases.

| Track | Current state and remaining evidence |
| --- | --- |
| Accepted actual runtime | Cold GPU completion, saved-draft navigation and automatic OCI STOP; cold SFace CPU persistence/API/projection with original UUID preservation. These accepted cases are complete within their receipt scope. |
| Remaining installed runtime acceptance | Actual in-flight description navigation/remount/client Stop waiting; real saved-credential edit/autosave; remaining installed naming recovery. Controlled tests and deployment navigation do not establish these cases. |
| Accepted E15 planning | [E15-38](../../tasks/15.0/E15-38-public-demo-honest-wait-and-beta-copy-task-plan.md), [E15-39](../../tasks/15.0/E15-39-description-default-trusted-set-and-serve-pin-task-plan.md), [DESCPICK-5](../../tasks/vlm/DESCPICK-5-served-q4-candidate-and-four-candidate-panel-task-plan.md): use decision 20609, then inspect actual missing source deltas. At this source baseline the settings/API default and trusted list still include `florence_small`; the E15-39 plan is not implementation proof. |
| Description authority and curation | DESCAUTH-1 / IDWEAVE-1 archived `done` is planning only. [ADR-017](../../adrs/ADR-017-description-authority-wordpress-curation-service-generation.md) / [ADR-018](../../adrs/ADR-018-post-curation-identity-weaving.md) remain Proposed; [ADR-019](../../adrs/ADR-019-person-anchored-curation-surfaces.md) is Accepted with missing producer/real-database qualification. Existing recovery pieces do not prove the whole contract shipped. |
| Independent quality and outcomes | Exhaustive independent face truth, fixed representative production replay, calibrated comparisons and independent human description judgment remain. E15-40 depends on qualified generation/selected-generation/presentation producers; read/cache timestamps are not acceptance evidence. No runtime or rollout receipt supplies quality gold, a model winner or automatic promotion. |

Canonical C1: **The first description after a quiet period starts the GPU and can take several minutes. After that, each image takes seconds.** Stop waiting stops client observation only, with no backend cancel. Preserve the same-media key after timeout/transient errors; clear it for true terminal failures. Keep the 120-second client ceiling. Quota is charged at creation; unavailable GPU consumes zero; cancelling does not refund it.

The older MVP/phase material below is historical scope and requirement context, not a fresh dispatch list or proof of current readiness. Any unmapped criterion remains pending evidence. This docs-only reconciliation grants no service/deploy/settings/payment/inference/scan/GPU mutation, new credentials or paid calls.

> **Epic Short ID**: E15
> **Status**: source/runtime and six-site installation complete within recorded scope; remaining installed workflow acceptance, missing source deltas and independent quality evidence are distinct (2026-10-30)
> **Predecessors**: [production-readiness-epic.md](../v0.3.1/production-readiness-epic.md) (Phases 2-6), [self-hosting-epic.md](../v0.3.1/self-hosting-epic.md) (remaining deliverables)
> **Successor (deferred follow-ons)**: [v0.4.1/public-demo-followons-epic.md](../v0.4.1/public-demo-followons-epic.md)
> **Revision**: Apr 2026 — MVP close-out scope locked under handoff decision `scope_e15_mvp_close_intake_202604`. CI smoke-gate and observability/auth follow-ons demoted to v0.4.1; Jun 2026 accepted plan [E15-6. Playwright Operator-Evidence Harness](../../tasks/15.0/E15-6-playwright-operator-evidence-harness-task-plan.md) pulls the docs-first/operator-evidence v1 slice back into v0.4.0 while leaving the durable CI smoke envelope deferred.

## Historical MVP scope (Apr 2026 close-out)

The MVP for E15 is **public WP demo URL live + one manual end-to-end pass**. Everything else moves to the [v0.4.1 follow-on epic](../v0.4.1/public-demo-followons-epic.md).

**In MVP:**

- Phase 1 — Security Baseline (E15-1, E15-1b) — merged to `main`
- Phase 2 — Observability Baseline (E15-2) — merged to `main`
- Phase 3 — WordPress Demo Provisioning (E15-3 revision via [E15-28](../../tasks/15.0/E15-28-oci-demo-provisioning-task-plan.md)) — OCI-colocated WP demo behind Caddy; gated on [E15-22](../../tasks/15.0/E15-22-workbench-avatar-and-progress-readiness-task-plan.md), [E15-3a](../../tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md), and seeded local-media proof before public DNS cutover
- Phase 4 — End-to-End Verification (E15-4 in progress, E15-5a OCI operational hygiene, E15-5 manual remote E2E + ARM evidence, E15-22 Workbench avatar/progress readiness, E15-23 Workbench live findings panel)
- Phase 6 — Local Sync Correctness, operator hardening, and audit closure (E15-7 in progress; E15-13, E15-14, E15-15, E15-16, and E15-17 staged under the same phase with explicit dependency order below)

**Deferred to v0.4.1:**

- Phase 5 v2 envelope — durable CI E2E smoke gate automation follow-ons from E15-6
- E15-2b worker/queue correlation propagation
- E15-8 auth transaction isolation core
- E15-9 API key usage telemetry deferral
- E15-10 API key baseline schema alignment
- slr-1..4 session lifecycle resilience
- td-correlation-dashboards (cross-tenant correlation_id dashboards)
- td-retry-attempt-observability

## Objective

Bring the deployed recognition service from "running on the server" to "publicly accessible, secure, observable demo with a WordPress frontend." When this epic is complete, anyone with the demo URL can see the ACX plugin in action against a live recognition backend.

## Historical problem statement (pre-provisioning)

The original E14-to-E15 intake listed the following gaps. These are historical motivations, not current findings; completion and remaining cases are governed by the dated status above.

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

## Historical baseline and phase requirements

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

### Original gap register (not a current work queue)

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
| WordPress demo page                                       | Production Readiness Phase 6 / E14 | Original provisioning requirement; consume current receipts rather than reinstall |
| Manual remote E2E verification                            | Production Readiness Phase 6 / E14 | Not started — **E15-5** (this epic)                                                    |
| Workbench live findings panel                             | Workbench clustering UI scope       | Planned -- **E15-23**                                                                  |
| OCI budget alerts not verified                            | E14 / Production Readiness Phase 6 | Not started — **E15-5a** (OCI operational hygiene)                                    |
| ARM compatibility verification                            | E14                                | Not started — **E15-5** (de facto verified by running A1 instance; artifact pending)   |
| Dynamic IP SSH access drift                               | Tech debt                          | Folded into **E15-5a** (Tailscale)                                                     |
| Local reset bootstrap contract mismatch                   | E15-4 (in progress)                | In progress                                                                            |
| Local-sync correctness and audit closure                  | New for E15                        | In progress -- **E15-7**                                                               |
| Roster curation loop + person review projection contracts | Phase 6 follow-on                  | Planned -- **E15-13**, gated by ADR-009 and sequenced after E15-7 correctness work     |
| LocalWP batch smoke argument plumbing                     | Phase 6 verification hardening     | Planned -- **E15-14**                                                                  |
| Dashboard operator triage with existing fields            | Phase 6 operator UX hardening      | Planned -- **E15-15**                                                                  |
| Dashboard durable activity and diagnostics                | Phase 6 operator UX hardening      | Planned -- **E15-16**, after E15-15 and a recorded durable-source decision             |
| Roster person review scrub workspace                      | Phase 6 operator UX hardening      | Planned -- **E15-17**, after E15-13 projection + queue contracts land                  |
| Worker/queue correlation propagation                      | E15-2 follow-on                    | **Deferred → v0.4.1 (E15-2b)**                                                         |
| CI E2E smoke gate automation / operator-evidence harness | Production Readiness Phase 2       | **Active in v0.4.0 for docs-first/operator-evidence v1 (E15-6); durable CI smoke envelope deferred to v0.4.1** |
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
| WP demo colocated on OCI with container bulkheads | $0 incremental vendor; Caddy routes `demo.altcontext.com`; WP+MariaDB capped so inference keeps SLO (see [E15-28](../../tasks/15.0/E15-28-oci-demo-provisioning-task-plan.md)) |
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

### Phase 3: WordPress Demo Provisioning — historical contract

> **Status**: completed installation/runtime work is governed by the 2026-10-30 receipts above; no provisioning redispatch. This historical public-demo contract is not blanket acceptance of every criterion.
> **Task plans (historical ownership)**: [E15-28. OCI Demo Provisioning](../../tasks/15.0/E15-28-oci-demo-provisioning-task-plan.md), [E15-3a. LocalWP -> OCI Round-Trip Verification](../../tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md), [E15-3. WordPress Demo Provisioning](../../tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md) (superseded hosting deliverables)
> **Predecessor gates**: [E15-22](../../tasks/15.0/E15-22-workbench-avatar-and-progress-readiness-task-plan.md) Workbench avatar/review-drawer proof; [E15-3a](../../tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md) LocalWP → OCI round-trip before public DNS.
> **Source**: Production Readiness Phase 6, E14 remaining (subsumes E14 checklist items: provision WP demo hosting, install + configure ACX plugin)

**Goal**: A publicly accessible WordPress page at `https://demo.altcontext.com` demonstrates the ACX plugin against the live backend via the same DNS path self-hosted users take.

**Historical pre-provisioning gates**: truthful local Workbench avatars/populated Review Cluster drawer and the E15-3a round trip were prerequisites to public DNS. Preserve their evidence; do not repeat provisioning from this history.

Deliverables:

- OCI demo stack (`acx-demo.service`): WordPress + MariaDB on `acx-demo-net` with CPU/memory bulkheads.
- Caddy vhost + TLS for `demo.altcontext.com` (repo-tracked Caddyfile; recreate on network join).
- Non-interactive bootstrap (`bootstrap-wp.sh`) + packaged ACX plugin install.
- Explicit demo tenant + API key (never URL-derived/JIT); CORS origin allowlisted.
- Seed bundle + import script under `infra/oci/demo/seed/` with license provenance recorded.
- Operator walkthrough + smoke log (`E15-28-demo-smoke-log.md`).

Exit criteria:

- WP demo loads at `https://demo.altcontext.com`.
- Plugin settings show constant-provenance config; settings probe passes against configured API.
- Scan → recognition → curation walkthrough recorded with E15-22 proof bundle shapes.
- Sovereign local-read + degraded-state evidence (E15-26); this requirement is not authorization to stop the current API.

---

### Phase 4: End-to-End Verification — historical contract

> **Status**: historical ownership split, not a new remote E2E dispatch. Consume accepted runtime evidence and keep only the remaining actual acceptance cases in the dated status open.
> **Task plans**: [E15-4. Local Reset Bootstrap Hardening](../../tasks/15.0/E15-4-local-reset-bootstrap-hardening-task-plan.md), [E15-5a. OCI Operational Hygiene](../../tasks/15.0/E15-5a-oci-operational-hygiene-task-plan.md), [E15-5. Remote E2E Verification + ARM Evidence](../../tasks/15.0/E15-5-manual-remote-e2e-task-plan.md)
> **Source**: Production Readiness Phase 6 exit criteria; subsumes E14 checklist items: configure budget alerts, verify ARM compatibility, end-to-end smoke test, dynamic IP SSH access drift

**Goal**: Prove the full WP-to-backend-to-recognition round trip works under realistic conditions.

Deliverables (by task):

- **E15-4**: Local reset bootstrap hardening (`make reset` works from clean checkout).
- **E15-5a**: OCI budget alerts verified ($1/$5/$10 thresholds active and tested); Hetzner CX22 fallback plan documented; Tailscale SSH access verified.
- **E15-5**: End-to-end smoke test (WP plugin triggers recognition request, backend processes it, response displayed in plugin UI); ARM compatibility evidence artifact captured.

Exit criteria:

- **E15-4**: Local dev reset works from a clean checkout without undocumented manual steps.
- **E15-5a**: Budget alerts are active and one test alert has been verified; SSH access works reliably without IP-dependent terraform apply; Hetzner fallback plan is accepted.
- **E15-5**: WP demo page can trigger a recognition scan and display results; ARM evidence artifact is filed.

---

### Phase 5: E2E Smoke Gate Automation / Operator Evidence -- active v1, deferred v2 envelope

> **Status**: active in v0.4.0 for the accepted v1 docs/scaffolding/operator-evidence slice; durable CI smoke follow-ons remain deferred to [v0.4.1 follow-on epic](../v0.4.1/public-demo-followons-epic.md)
> **Task plans**: [E15-6. Playwright Operator-Evidence Harness](../../tasks/15.0/E15-6-playwright-operator-evidence-harness-task-plan.md), [E15-6. E2E Smoke Gate Automation (stub superseded)](../../tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md)
> **Source**: Production Readiness Phase 2

Rationale: MVP completion signal is still "demo URL live + manual E2E pass once", but the accepted E15-6 plan brings the docs-first harness contract, LocalWP operator-evidence path, and route-level a11y scaffolding back into v0.4.0 because that work unblocks demo proof generation now. The durable CI smoke envelope, outage helpers, and automation hardening remain deferred follow-on work.

---

### Phase 6: Local Sync Correctness and Audit Closure — historical contract

> **Status**: historical requirements; map source and receipts before identifying a current missing delta
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

Original Phase 6 dependency order (historical, not a redispatch instruction):

1. E15-7 closes the sovereign local-sync correctness and audit findings.
2. E15-3a and Workbench entity-avatar/review-drawer evidence preceded public provisioning. Current remaining installed naming recovery is listed above; it does not reopen completed installation.
3. E15-13 starts after ADR-009 review acceptance and lands the roster curation loop, person projection, and queue contracts.
4. E15-14 can run independently once LocalWP smoke evidence is prioritized, but still reports under Phase 6 because it hardens demo-readiness correctness proof.
5. E15-15 reshapes dashboard triage using existing fields only.
6. E15-16 follows E15-15 and records a durable activity-source decision before changing dashboard activity authority.
7. E15-17 follows E15-13 and consumes the landed RCL-002, RCL-004, RCL-005, and RCL-008 contracts rather than inventing parallel roster-review surfaces.

Exit criteria:

- Analyze completion leaves durable local state or an explicit degraded status even when snapshot fetch is unavailable immediately afterward.
- Fallback envelopes do not invent unsupported metadata or contradictory projection status.
- Remaining local-sync findings are fixed or explicitly deferred with rationale.
- `handoff_close_check(enforce=True, current_commit_sha=<HEAD>)` passes for the merge candidate branch.

## External Dependencies

| Dependency                              | Owner   | Status                  | Blocks  |
| --------------------------------------- | ------- | ----------------------- | ------- |
| OCI demo stack + DNS (`demo.altcontext.com`) | @daniel | Historical E15-28 dependency; consult receipts, no new provisioning | Historical Phase 3 |
| API key / origin policy decisions       | @daniel | Not started             | Phase 1 |
| OCI budget alert verification           | @daniel | Not started             | Phase 4 (E15-5a) |
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
- Historical CI smoke target: context only; current evidence status does not imply CI is enabled or passing.
- Monthly cost: $0 backend + ~$2-5 WP hosting = ~$2-5/mo total.

---

## Historical requirement checklist

Unchecked historical requirements below are not a current dispatch list. Reconcile them to actual source/receipts; keep missing evidence explicit without reopening accepted work.

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

## Phase 3: WordPress Demo Provisioning — receipt reconciliation → [E15-28](../../tasks/15.0/E15-28-oci-demo-provisioning-task-plan.md)

> Source: Production Readiness Phase 6 + E14 remaining (OCI-colocated topology)

- [x] Six-site 0.0.42 installation/assets/authenticated navigation completed within the rollout receipt scope above
- [x] Bounded actual cold GPU and cold SFace runtime cases accepted within their separate receipt scope
- [ ] Map any other historical public-demo criterion to exact evidence; leave unevidenced criteria pending without new installation, tenant/key, seed or DNS changes

## Phase 4: End-to-End Verification -- IN PROGRESS → [E15-4](../../tasks/15.0/E15-4-local-reset-bootstrap-hardening-task-plan.md) + [E15-5a](../../tasks/15.0/E15-5a-oci-operational-hygiene-task-plan.md) + [E15-5](../../tasks/15.0/E15-5-manual-remote-e2e-task-plan.md)

> Source: Production Readiness Phase 6 exit criteria + [tech-debt/dynamic-ip-ssh-access.md](../../tasks/tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md)

- [ ] Complete local reset bootstrap hardening (E15-4, in progress) ← _finding INVEST-reset-env-contract-mismatch_
- [ ] Verify OCI budget alerts ($1/$5/$10 thresholds) ← _Prod Readiness P6 + E14 (E15-5a)_
- [x] Resolve dynamic IP SSH access drift (Tailscale) ← _[tech-debt/dynamic-ip-ssh-access.md](../../tasks/tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md) (implemented/documented)_
- [ ] Reconcile E15-5 criteria with accepted actual runtime receipts; remaining in-flight/credential/naming cases are listed above
- [ ] Document Hetzner CX22 fallback plan ← _Prod Readiness P6 + E14 (E15-5a)_
- [ ] Capture ARM compatibility verification evidence ← _E14 (E15-5; de facto verified by running A1 instance, but missing recorded artifact)_

## Phase 5: E2E Smoke Gate Automation — historical CI envelope → [v0.4.1](../v0.4.1/public-demo-followons-epic.md)

> Source: Production Readiness Phase 2. Deferred under handoff decision `scope_e15_mvp_close_intake_202604`.

The durable CI envelope was deferred to v0.4.1, while E15-6 v1 operator evidence remained in v0.4.0 as described above. Consume existing evidence paths; this historical CI requirement does not authorize re-enabling retired GitHub CI or repeating accepted live cases.

## Phase 6: Local Sync Correctness -- IN PROGRESS → [E15-7](../../tasks/15.0/E15-7-local-sync-completion-and-audit-closure-task-plan.md)

> Source: runtime investigation follow-up on sovereign local-read correctness

- [ ] Direct local persistence path from completed analyze/clustering work into local projection ← _E15-7_
- [ ] Truthful fallback response metadata + bounded projection-trigger behavior during polling ← _E15-7_
- [ ] Snapshot/auth failure visibility ← _E15-7_
- [ ] `handoff_close_check(enforce=True)` passes on merge candidate ← _E15-7_
