# E16. Public Demo Follow-Ons (v0.4.1)

> **Epic Short ID**: E16
> **Status**: scoped, not started
> **Predecessor**: [E15. Public Demo Launch Readiness (v0.4.0)](../v0.4.0/public-demo-launch-readiness-epic.md)
> **Charter decision**: handoff `scope_e15_mvp_close_intake_202604` (Apr 2026 MVP narrowing)

## Objective

Land the observability, auth, reliability, and CI-automation follow-ons that were intentionally deferred from E15 in order to ship the v0.4.0 public demo on time. v0.4.1 turns "demo URL live" into "demo URL durable, observable across hops, and regression-gated by CI".

## Scope Charter

E15 closed when the public WordPress demo URL was live and a single manual end-to-end pass succeeded. Everything below is a follow-on that improves resilience, traceability, or velocity but was **not** required to call the demo "launched".

This epic exists so the deferred work has a single owning artifact, an explicit cross-task ordering story, and a single place to track v0.4.1 close-out gates. It is not a "kitchen sink" — items are grouped by theme below.

## Themes and Member Tasks

### Theme A — Observability Continuity (extends E15-2)

> **Stub-vs-plan placement rule (applies to every theme below).** Scoping stubs live on `main` under [`docs/tasks/tech-debt/`](../../tasks/tech-debt/) as part of v0.4.0 close-out. Full task plans get generated under [`docs/tasks/15.0/`](../../tasks/15.0/) only when the implementation slice is picked up under v0.4.1, after the stub's stated prerequisite has landed. This avoids mid-planning 404s and keeps v0.4.0 MVP scope narrowed to "demo URL live + manual E2E".

| Task | Status | Owning Doc | Why It's Here |
| ---- | ------ | ---------- | ------------- |
| **E15-2b** Worker / Queue Correlation Propagation | Drafted (`feature/e15-2b` not started) | [E15-2b plan](../../tasks/15.0/E15-2b-worker-queue-correlation-task-plan.md) | E15-2 terminated correlation at the API boundary; once a request enqueues scan work, downstream worker logs are un-joinable. Required before any cross-hop tracing is meaningful. |
| **td-correlation-dashboards** Cross-Tenant Correlation Dashboards | Stub on `main` (source branch `feature/td-correlation-dashboards` retired) | [correlation-dashboards.md](../../tasks/tech-debt/correlation-dashboards.md) | Promote E15-2 metrics into actual operator-facing dashboards keyed on `correlation_id` × tenant. Depends on E15-2b for cross-hop joins. |
| **td-retry-attempt-observability** Retry / Attempt-Level Observability | Stub on `main` (source branch `feature/td-retry-attempt-observability` retired) | [retry-attempt-observability.md](../../tasks/tech-debt/retry-attempt-observability.md) | Per-attempt latency / failure attribution for the worker queue. Pairs with E15-2b. |

### Theme B — Auth & Key Lifecycle Hardening (extends E15-1)

| Task | Status | Owning Doc | Why It's Here |
| ---- | ------ | ---------- | ------------- |
| **E15-8** Auth Transaction Isolation Core | Drafted | [E15-8 plan](../../tasks/15.0/E15-8-auth-transaction-isolation-core-task-plan.md) | Tightens the read/write transaction boundary around auth so concurrent rotation cannot interleave with validation. |
| **E15-9** API Key Usage Telemetry Deferral | Drafted | [E15-9 plan](../../tasks/15.0/E15-9-api-key-usage-telemetry-deferral-task-plan.md) | Move per-request key-usage writes off the hot path. |
| **E15-10** API Key Baseline Schema Alignment | Drafted | [E15-10 plan](../../tasks/15.0/E15-10-api-key-baseline-schema-alignment-task-plan.md) | Bring the persisted key shape in line with the rotation contract that E15-1 established. |

### Theme C — Session-Lifecycle Resilience

Theme C tasks operate on pool/session lifecycle state and do not depend on E15-7 local-sync closure.

| Task | Status | Owning Doc | Why It's Here |
| ---- | ------ | ---------- | ------------- |
| **slr-1** Session Lifecycle Resilience | Drafted | [slr-1 plan](../../tasks/15.0/slr-1-session-lifecycle-resilience-task-plan.md) | Foundation slice. |
| **slr-2** Circuit Breaker + Bulkhead Unblock | Drafted | [slr-2 plan](../../tasks/15.0/slr-2-circuit-breaker-and-bulkhead-unblock-task-plan.md) | |
| **slr-3** Session Dependency Circuit Breaker | Drafted | [slr-3 plan](../../tasks/15.0/slr-3-session-dependency-circuit-breaker-task-plan.md) | |
| **slr-4** Observability for Pool Bulkhead | Drafted | [slr-4 plan](../../tasks/15.0/slr-4-observability-pool-bulkhead-task-plan.md) | Closes the loop — exposes slr-1..3 state via the E15-2 metrics surface. |

### Theme D — CI & Regression Gates (was E15 Phase 5)

| Task | Status | Owning Doc | Why It's Here |
| ---- | ------ | ---------- | ------------- |
| **E15-6** E2E Smoke Gate Automation | Stub (to be promoted) | [E15-6 stub](../../tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md), [tech-debt/e2e-smoke-automation-path.md](../../tasks/tech-debt/e2e-smoke-automation-path.md) | Was E15 Phase 5. Replaces E15-5 manual passes with Playwright + WP-CLI fixtures + outage simulation in CI. Depends on the WP demo standing up (E15-3) and on the manual flow being well-understood (E15-5). |

## Cross-Theme Ordering

Recommended landing order to keep dependency arrows pointing one way:

1. **Theme A first.** E15-2b → td-correlation-dashboards / td-retry-attempt-observability in parallel. Without cross-hop correlation, the dashboards from D have nothing to link.
2. **Theme B in parallel with A.** Auth changes don't depend on observability; both can land independently.
3. **Theme C after B.** slr-* assumes the rotation/lifecycle contract from B is settled.
4. **Theme D last.** CI smoke gate locks in the behavior surfaced by A + B + C.

This is the recommended order, not a hard constraint. Individual tasks remain mergeable in isolation; the cross-theme ordering only matters for "v0.4.1 done".

## Exit Criteria

v0.4.1 is closed when:

- All Theme A tasks are merged and `correlation_id` joins API + worker logs and surfaces on at least one operator dashboard.
- All Theme B tasks are merged and the API key rotation contract has no known race or schema-drift findings open in MCP.
- At least slr-1 and slr-4 from Theme C are merged (slr-2/3 may defer if low-signal).
- Theme D ships a green CI smoke job covering: offline label persistence, local-read resilience with backend down, sync-status transitions through outage/recovery — without depending on LocalWP private APIs.

## Out of Scope (deferred again, possibly to v0.5.x)

- VLM/Phi-3.5 captioning rollout (separate epic).
- GPU host migration (Stage A/B/C from E14).
- Account-system database (E14 deferred follow-on).

## Code Anchors

| Layer | File | Note |
| ----- | ---- | ---- |
| Worker handler | `apps/prototype-description-service/recognition/worker/handlers/scan.py` | E15-2b correlation propagation target |
| Queue model | `apps/prototype-description-service/db/models/jobs.py` | Schema column for correlation_id (E15-2b) |
| Auth dep | `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py` | E15-8 / E15-9 / E15-10 surface |
| Metrics middleware | `apps/prototype-description-service/recognition/interface_adapters/http/middleware/metrics.py` | slr-4 + dashboards (Theme A) hook point |
| E2E harness target | `apps/prototype-wp-alt-context/tests/e2e/` | E15-6 lands here |

## Risks and Mitigations

- **E15-2b queue schema change** is the only Theme-A item touching DB shape. Land it first to avoid revving migrations twice.
- **Theme D blocked on Theme A** if the smoke gate wants to assert end-to-end correlation. Mitigation: scope the first CI cut to behavior assertions only, add correlation assertions in a follow-on slice.
- **Tech-debt promotion drift.** Resolved in v0.4.0 close-out: both stubs now live on `main` under [`docs/tasks/tech-debt/`](../../tasks/tech-debt/) per the stub-vs-plan placement rule above. Promote to full task plans under `docs/tasks/15.0/` when v0.4.1 implementation picks up (after E15-2b lands).
