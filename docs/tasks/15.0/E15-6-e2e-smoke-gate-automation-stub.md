# E15-6. E2E Smoke Gate Automation (DEFERRED to E16)

> **Task Short ID**: E15-6
> **Status**: deferred -- owned by [E16. Public Demo Follow-Ons](../../epics/v0.4.1/public-demo-followons-epic.md)
> **Epic (source)**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 5
> **Epic (owner)**: E16 Public Demo Follow-Ons (v0.4.1)
> **Predecessors**: E15-3 (WP demo live), E15-5 (manual round-trip verified)

---

## Why this task exists and why it is NOT in the MVP

The MVP exit criterion for E15 is a **manual** WP -> backend -> recognition round-trip with a run log (see [E15-5](./E15-5-manual-remote-e2e-task-plan.md)). An automated smoke gate is the next increment after MVP: it prevents regressions across deploys rather than being necessary to ship the first demo.

Deferring the smoke gate to E16 keeps v0.4.0 shippable on a short timeline and puts the automation effort where it pays off -- after a real demo URL has existed for long enough that a regression story is plausible.

## Scope (to be refined in E16)

The same surface originally drafted in the epic:

- Playwright test harness for plugin E2E flows.
- WP-CLI seed/reset helpers for deterministic fixtures.
- Reproducible runtime path for CI (`wp-env` or Docker-based WP runtime).
- Deterministic outage simulation path (service stop / proxy fault injection).
- CI job that runs smoke tests and captures trace/video artifacts on failure.

Required scenarios once automated:
- Offline label persistence.
- Local-read resilience with backend down.
- Sync-status transitions through outage/recovery.
- Flow does not depend on LocalWP private APIs.

## Acceptance bar (when picked up under E16)

- Green CI run on a fresh checkout with zero manual steps.
- Trace + video captured on failure.
- Scenarios cover offline persistence, local-read resilience, sync transitions.
- No dependency on LocalWP private APIs.

## Unblock conditions

Pick up under E16 once:
- E15-3 + E15-5 are both closed.
- E15 MVP is declared complete.
- E15-7 (local-sync audit closure) has landed its first slice so sync-transition tests have a stable contract to assert against.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(BR-04 closed)` or "resolve handoff issue X"; finding status lives in MCP / `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the current E15/E16 scope split and the active demo-flow contracts before reopening this stub.
- [ ] Confirmed whether any new external tooling/runtime research is needed before E16 expands this into a full plan.
- [ ] Kept ownership explicit: this file stays deferred until E16 picks it up; do not implement from the stub while it remains in E15.

### Checklist for Slice 1: Stub expansion under E16

- [ ] Convert this deferred stub into a full task plan using `docs/agentic/templates/TASK_PLAN.template.md`.
- [ ] Carry forward the Playwright, WP reset/seed, deterministic outage, and CI artifact surfaces listed in Scope.
- [ ] Define the proof bundle so offline persistence, local-read resilience, and sync-transition assertions are executable in CI.

## Review Readiness

- [ ] The future E16 plan names the runtime path, outage simulation mechanism, and artifact capture surfaces concretely.
- [ ] The automation scope stays aligned with E15-3, E15-5, and E15-7 contracts instead of reinterpreting them.
- [ ] Handoff explicitly records when the stub is re-opened and promoted to an active plan.

## Success Criteria

- [ ] E16 replaces this stub with a full task plan that preserves the deferred scope and unblock conditions.
- [ ] The resulting automation plan is ready for implementation without relying on LocalWP private APIs.

## Handoff

This file is intentionally a stub and NOT an active task plan. Do not start implementation against this plan while it remains deferred. When E16 picks it up, re-open this file and expand into full slices.
