# E15.5. Demo Operational Hardening (v0.4.1)

> **Epic Short ID**: E15.5
> **Status**: scoped -- not started; **do not begin until E15 MVP (v0.4.0) is declared complete**.
> **Predecessor**: [E15. Public Demo Launch Readiness](../v0.4.0/public-demo-launch-readiness-epic.md)
> **Created**: 2026-04-20 (carve-out from E15 to keep the MVP path tight)

## Why this epic exists

E15 (v0.4.0) ships a **manually-verified** public demo. Once that demo URL is live, a new class of work becomes actionable: regression prevention, operational visibility, correctness audit closure, and follow-on security/storage items that accumulated as "nice to have before we open the demo to wider audiences."

Rather than let those items drift as loose task plans under E15, they live here as a coherent "post-demo hardening" epic with a clear trigger (E15 MVP shipped) and a clear exit (demo URL is safe to share with a broader audience, observability shows regressions automatically, and the local-sync audit trail is closed).

## Entry condition

This epic does **not** start until all four MVP signals from [E15's MVP Completion Signal](../v0.4.0/public-demo-launch-readiness-epic.md#mvp-completion-signal) are satisfied. Starting any E15.5 slice while E15 MVP is still open is out of order.

## Exit condition

The epic is complete when:

1. E2E smoke gate runs on CI with trace/video artifacts (E15-6).
2. Local-sync correctness audit is closed with zero open findings (E15-7).
3. Auth transaction isolation is hardened (E15-8).
4. API key usage telemetry is wired and at least one dashboard reads from it (E15-9).
5. API key baseline schema alignment lands (E15-10).
6. Session lifecycle resilience work (slr-1 through slr-4) is either complete or explicitly deferred with rationale.
7. Correlation + retry-attempt observability dashboards are live (`td-correlation-dashboards`, `td-retry-attempt-observability`).
8. Worker/queue correlation work (E15-2b) is verified against the dashboards.

Any item that is not completed must be explicitly re-deferred with a named successor epic and a reason; silent deferrals are not acceptable.

## Constituent tasks

Each item below retains its existing task-plan file; this epic provides sequencing and closure ownership, not re-scoping.

| Task | File | Status today | Area |
|------|------|--------------|------|
| E15-2b. Worker/Queue Correlation | [tasks/15.0/E15-2b-worker-queue-correlation-task-plan.md](../../tasks/15.0/E15-2b-worker-queue-correlation-task-plan.md) | merged on `main` at 0f23968b; hardening/dashboards remain | observability |
| E15-6. E2E Smoke Gate Automation | [tasks/15.0/E15-6-e2e-smoke-gate-automation-task-plan.md](../../tasks/15.0/E15-6-e2e-smoke-gate-automation-task-plan.md) | stub, deferred from E15 | verification |
| E15-7. Local Sync Completion and Audit Closure | [tasks/15.0/E15-7-local-sync-completion-and-audit-closure-task-plan.md](../../tasks/15.0/E15-7-local-sync-completion-and-audit-closure-task-plan.md) | in-progress in E15, re-homed here | correctness |
| E15-8. Auth Transaction Isolation | [tasks/15.0/E15-8-auth-transaction-isolation-core-task-plan.md](../../tasks/15.0/E15-8-auth-transaction-isolation-core-task-plan.md) | scoped | security |
| E15-9. API Key Usage Telemetry | [tasks/15.0/E15-9-api-key-usage-telemetry-deferral-task-plan.md](../../tasks/15.0/E15-9-api-key-usage-telemetry-deferral-task-plan.md) | scoped | observability / security |
| E15-10. API Key Baseline Schema Alignment | [tasks/15.0/E15-10-api-key-baseline-schema-alignment-task-plan.md](../../tasks/15.0/E15-10-api-key-baseline-schema-alignment-task-plan.md) | scoped | storage |
| slr-1. Session Lifecycle Resilience | [tasks/15.0/slr-1-session-lifecycle-resilience-task-plan.md](../../tasks/15.0/slr-1-session-lifecycle-resilience-task-plan.md) | scoped | resilience |
| slr-2. Circuit Breaker and Bulkhead Unblock | [tasks/15.0/slr-2-circuit-breaker-and-bulkhead-unblock-task-plan.md](../../tasks/15.0/slr-2-circuit-breaker-and-bulkhead-unblock-task-plan.md) | scoped | resilience |
| slr-3. Session Dependency Circuit Breaker | [tasks/15.0/slr-3-session-dependency-circuit-breaker-task-plan.md](../../tasks/15.0/slr-3-session-dependency-circuit-breaker-task-plan.md) | scoped | resilience |
| slr-4. Observability Pool + Bulkhead | [tasks/15.0/slr-4-observability-pool-bulkhead-task-plan.md](../../tasks/15.0/slr-4-observability-pool-bulkhead-task-plan.md) | scoped | resilience |
| td-correlation-dashboards | branch `feature/td-correlation-dashboards` at 437c817c | in-progress branch | observability |
| td-retry-attempt-observability | branch `feature/td-retry-attempt-observability` at 14627f4d | in-progress branch | observability |

## Sequencing

The epic runs in three loose waves. Items within a wave can parallelize; waves themselves are gated.

**Wave A -- Visibility before hardening**

1. `td-correlation-dashboards` land first. Without the dashboards, E15-9 telemetry has no obvious consumer.
2. `td-retry-attempt-observability` lands next; it augments the same dashboard.
3. E15-2b final verification against the new dashboards (spot-check a worker job's correlation ID flows end-to-end through the dashboard panels).

Exit for Wave A: dashboards show real worker traffic; one deliberate outage drill confirms retry-attempt histograms populate correctly.

**Wave B -- Correctness + storage + auth**

4. E15-7 local-sync audit closure.
5. E15-10 API key baseline schema alignment.
6. E15-8 auth transaction isolation.
7. E15-9 API key usage telemetry (consumes Wave A dashboards).

Exit for Wave B: zero open review findings across these four tasks, and `handoff_close_check(enforce=True)` passes for each.

**Wave C -- Resilience + automation**

8. slr-1 .. slr-4 in their documented order.
9. E15-6 E2E smoke gate automation lands last so it asserts against the fully-hardened system.

Exit for Wave C: CI smoke gate green; slr-4 observability surfaces pool/bulkhead metrics live.

## Constraints (inherited from E15)

- Plugin boundary rule: monorepo-managed code/config changes only.
- Greenfield policy: no backward-compatibility shims.
- No VLM / Phi-3.5 in this epic's scope.
- Pre-merge gate (`handoff_close_check(enforce=True)`) on every task.

## Non-goals

- User-account database (remains deferred under [E14](../v0.3.1/self-hosting-epic.md#deferred-follow-on-user-account-database)).
- VLM captioning and Phase-2 VPS sizing (remains under E14 future path).
- Branded public launch / marketing site (separate epic when/if that materializes).

## Risks

- **Scope creep from in-flight branches** -- `td-correlation-dashboards` and `td-retry-attempt-observability` may each spawn adjacent ideas; keep each under its current task ref and flag new work as new tasks.
- **slr-* ordering drift** -- the slr-1..4 chain was scoped together; re-validate the ordering at Wave C kick-off rather than trusting the draft plans.
- **Local-sync audit scope** -- E15-7 still carries open correctness findings; do not let Wave B stall on audit-closure surprises. If E15-7 needs to split, do so inside this epic.

## Success signal

A single sentence the operator can say: "the demo URL has been live for N days, no regression slipped past the smoke gate, and no open findings block the next demo audience."
