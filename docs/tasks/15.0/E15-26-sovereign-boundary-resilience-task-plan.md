# E15-26. Sovereign Boundary Resilience — Timeouts, Circuit Breaker, Steady State

> **Metadata**
>
> - **Date**: 2026-06-10
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-26`
> - **Review Coverage Target**: 2
> - **Companion assessment**: [E15-24-architecture-coherence-assessment.md](E15-24-architecture-coherence-assessment.md)
> - **Scope fence**: E15-7 owns local persistence path + fallback envelope honesty. slr-2/slr-3 (deferred, v0.4.1) own Python-service-internal breakers. This task owns the **PHP plugin → service boundary** and async-debt steady state only.

## Objective

Every plugin→service call acquires a bounded-time, breaker-guarded path so a slow or offline service degrades the UI to local-projection mode within one bounded timeout — visibly, not silently. Failed sync work (outbox, conflicts, curation replays) stops accumulating unboundedly and gains an operator recovery surface.

## Problem Statement

Sovereignty reads already degrade to local projections (`data_source='local_projection'`), but the boundary has no stability contract: proxy calls through `class-abstract-recognition-proxy-controller.php` rely on WP HTTP defaults, a hung service can hold admin requests for the full default timeout per call (Release It: integration points hang — slow failures are worse than fast ones), and nothing tells the user the plugin is in degraded mode, which directly violates the sovereignty goal — curation work *looks* gone when reads silently miss fresh data. Async debt accumulates: outbox rows retry to a ceiling then sit, conflicts queue for manual resolution with no surface, and `CurationReplayRecord.refresh_status='failed'` rows pile up (91 observed) with no retry or operator action.

## Constraints

- Curation-first conflict policy and local-read behavior must not regress (epic constraint).
- rg-002: no splitting of backend atomic writes into multiple frontend mutations — recovery operations reuse existing `OutboxMaintenanceService` seams (refa-6 slice 4).
- rg-007: any drain/loop change keeps bounded per-unit stall detection.
- sr-009: new transactional PHP paths use `run_transactional(callable)`.
- Characterization tests from refa-6 slice 1 (`SplitTopologyCommandDrainTest`, `OutboxDrainTest`) stay green throughout.

## Workflow Principles

- One client wrapper, one policy: timeout/breaker/telemetry live in a single `RecognitionHttpClient`; controllers never call `wp_remote_*` for recognition traffic directly (Release It: circuit breaker wraps the integration point once).
- Degradation is a designed product state: banner + per-surface affordances, color + icon + text (sr-004), never an implicit fallback.
- Steady state: every queue this task touches gets a retention/recovery story — nothing accumulates without a purge or an operator action path (Release It: steady state).

## Terminology

- **Breaker state**: `closed` (normal) / `open` (fail immediately, serve local) / `half-open` (single trial call) — persisted in a WP transient/option per target URL.
- **Degraded mode**: breaker open or last sync pull failed; reads serve local projections, writes queue to outbox.
- **Async debt**: pending/failed outbox rows + open conflicts + failed replay records.

## Current State Analysis

- Reads: controllers serve local tables and fall back honestly (E15-7 finishing this). Writes: `OutboxDrain` retries to `max_attempts=5`, conflict rows persist to `acx_sync_conflicts`; `OutboxMaintenanceService` (refa-6) already exposes retry/discard/re-enqueue primitives — unwired to any UI.
- No timeout policy: each proxy call independently waits on WP defaults; a scan-status poll against a hung service stalls the admin.
- No breaker: 20 widgets polling an offline service make 20 full-timeout attempts (Release It: cascading failure precondition).
- Curation replays: `refresh_status` enum has terminal `failed`/`timed_out` with no consumer.

## Target Outcome

`RecognitionHttpClient` wraps all recognition HTTP with per-class timeouts (interactive ≤5s, background/drain ≤15s — tuned in implementation), failure counting, and a breaker whose open state short-circuits to an immediate structured "degraded" result. Admin UI shows a persistent degraded-mode banner (dismissable per session) sourced from a new lightweight `GET /acx/v1/sync/health` that reports breaker state + outbox depth + open conflicts + failed replays — queue-depth vs processing-time observability per the latency literature, so "91 stuck replays" is visible the day it begins, not months later. Sync dashboard gains an Async Debt panel with retry/discard actions delegating to existing maintenance seams. Retention: acknowledged outbox rows and resolved conflicts purge on a bounded schedule; failed replays require explicit operator action (retry/discard) and warn at a threshold.

## Context Loading

- Rules: `docs/workstate/rules/backend-php-guidelines.md`, `docs/workstate/rules/frontend-guidelines.md`, `docs/workstate/rules/testing-php.md`
- Contracts: sync status controller (`class-sync-status-controller.php`), refa-6 task plan `docs/tasks/tech-debt/REFA-6-sync-drains-task-plan.md`
- Handoff/MCP: E15-26 ref; E15-7 open findings (avoid double-fixing); refa-6 REV-B findings for drain seams.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Recognition HTTP calls | plugin | per-controller `wp_remote_*` via proxy base | all routed through `RecognitionHttpClient` | No — internal refactor | PHPUnit: no direct `wp_remote_` in recognition controllers (lint-style test) |
| `GET /acx/v1/sync/health` | plugin REST | none (sync-status exists for E2E) | new compact health envelope: breaker, outbox depth, conflicts, failed replays | n/a new; additive | PHPUnit shape test + TS type |
| Outbox/replay recovery ops | plugin REST | maintenance service methods unexposed | thin REST actions delegating to `OutboxMaintenanceService` | yes — must preserve atomicity (rg-002) | PHPUnit through existing characterization suites |

## Proposed Solution

Slice 1 extracts the client wrapper with timeouts + telemetry (no breaker yet) and migrates call sites — pure seam introduction under characterization cover. Slice 2 adds breaker state machine + degraded short-circuit + `sync/health` endpoint. Slice 3 ships the UI: banner, Async Debt panel with recovery actions, and retention purges (WP-Cron bounded batches). A failure-mode test harness (Release It: test harness) — a tiny PHP test double simulating hang/refuse/500/garbage — backs PHPUnit characterization of timeout and breaker transitions.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| New client | `apps/prototype-wp-alt-context/src/api/class-recognition-http-client.php` | timeouts, breaker, telemetry |
| Proxy base | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | delegate to client |
| Sync drains | `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php`, `class-sync-pull-job.php` | use client; breaker-aware scheduling |
| Health endpoint | `apps/prototype-wp-alt-context/src/api/class-sync-health-controller.php` (new) | debt + breaker envelope |
| Recovery REST | extend `class-sync-status-controller.php` or sibling | retry/discard actions → maintenance service |
| UI | `js/admin/` banner component + Async Debt panel on dashboard/sync surface | degraded mode + recovery |
| Retention | WP-Cron registration + purge in maintenance service | bounded purges |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && composer test` — breaker state machine (closed→open→half-open→closed), timeout enforcement via harness double, characterization suites green, recovery actions atomicity
  - `npm test` — banner renders from health envelope states; debt panel actions
- Contract verification: `sync/health` PHPUnit shape ↔ TS type.
- Manual: stop local service mid-session → banner appears within one timeout; curation still readable; restart → half-open recovery clears banner; replay retry action drains a seeded failed record.

## Slice Delivery

### Slice 1: RecognitionHttpClient seam

**Goal**: all recognition HTTP flows through one wrapper with bounded timeouts and telemetry.

Changes: client class; call-site migration; lint-style test forbidding direct `wp_remote_` in recognition paths.
Proof: characterization suites green; harness-backed timeout test.

### Slice 2: Breaker + sync health envelope

**Goal**: offline service costs at most one timeout per breaker window; degraded state is queryable.

Changes: breaker state machine + persistence; short-circuit structured result; `sync/health` endpoint.
Proof: PHPUnit transitions; endpoint shape test; polling loop under open breaker makes zero remote calls (assert via harness call counter).

### Slice 3: Degraded-mode UI + async-debt recovery + steady state

**Goal**: users see degraded mode; operators can retry/discard debt; queues stop growing unboundedly.

Changes: banner; Async Debt panel; recovery REST actions; retention purges; threshold warnings.
Proof: Vitest states; PHPUnit recovery atomicity; purge test with seeded aged rows; manual offline walkthrough recorded.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded refa-6 plan + characterization suites + E15-7 scope fence before editing.
- [ ] Confirmed no overlap with E15-7 deliverables (persistence path, fallback honesty).
- [ ] Boundary rows recorded in slice-close decisions.

### Checklist for Slice 1: Client seam

- [ ] Client extracted; call sites migrated; direct-call lint test in place
- [ ] Timeout policy enforced + tested via harness
- [ ] Evidence recorded

### Checklist for Slice 2: Breaker + health

- [ ] State machine + persistence + short-circuit tested
- [ ] `sync/health` envelope shipped with TS type
- [ ] Evidence recorded

### Checklist for Slice 3: UI + recovery + retention

- [ ] Banner + debt panel + recovery actions landed (sr-004 compliant)
- [ ] Retention purges bounded and tested
- [ ] Manual offline walkthrough evidence; slice-complete decision

## Review Readiness

- [ ] Refa-6 characterization suites untouched-and-green or consciously extended.
- [ ] No atomic backend write split across frontend mutations.
- [ ] Handoff decisions per slice; dashboard rendered.

## Success Criteria

- [ ] Service offline: curation reads work, one banner explains why, admin never stalls longer than one bounded timeout.
- [ ] Breaker open: zero remote calls until half-open trial; recovery is automatic and visible.
- [ ] Async debt is observable (counts in `sync/health`) and recoverable (operator actions), with bounded retention for terminal rows.
