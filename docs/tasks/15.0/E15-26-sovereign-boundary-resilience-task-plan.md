# E15-26. Sovereign Boundary Resilience — Breaker Visibility, Async-Debt Recovery, Steady State

> **Metadata**
>
> - **Date**: 2026-06-10 (rev 2 — corrected after code verification: a per-class timeout/breaker layer already exists; this plan now extends and surfaces it instead of re-inventing it)
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-26`
> - **Review Coverage Target**: 2
> - **Companion assessment**: [E15-24-architecture-coherence-assessment.md](E15-24-architecture-coherence-assessment.md)
> - **Scope fence**: E15-7 owns local persistence path + fallback envelope honesty. slr-2/slr-3 (deferred, v0.4.1) own Python-service-internal breakers. This task owns **visibility and recovery at the PHP plugin → service boundary** and async-debt steady state only.
> - **Literature citation convention**: short form `release-it.md §Circuit Breaker` refers to `literature/extracted/refactoring/distilled/release-it.md`; same pattern for `designing-data-intensive-applications.md`, `latency-reduce-delay-in-software-systems.md`, `refactoring-ui.md`, `using-asyncio-in-python.md`.

## Objective

The resilience machinery that already exists at the plugin→service boundary becomes *visible and actionable*: users see degraded mode the moment it starts, operators see breaker state alongside the existing async-debt counts and recovery controls, and terminal sync rows stop accumulating unboundedly.

## Problem Statement

Code verification (this revision) shows the boundary already has more discipline than assumed: every recognition HTTP call — including sync drains via `SnapshotClientTransport` — flows through `AbstractRecognitionProxyController::proxy_request()`, which applies a per-request-class policy (`RecognitionProxyPolicy`) with bounded timeouts and, for `ui_read`, a transient-based circuit breaker. What is missing is everything *around* that machinery:

1. **Invisibility.** An open breaker returns a bare `WP_Error('recognition_circuit_open', …, 503)`. Nothing in the admin UI distinguishes "service down, working from local copy" from a generic failure — which directly violates the sovereignty goal: curation work *looks* gone when the user can't tell they're in a designed offline state (`release-it.md §Graceful Degradation`; `refactoring-ui.md §Don't Overlook Empty States` — offline is a state to design, not an accident).
2. **Async debt is only partially visible.** The current sync-status/dead-letter surfaces expose plugin-local outbox counts, conflicts, and failed outbox retry/discard controls, but they do not report breaker state, do not present one degraded-mode envelope, and do not cover service-side `CurationReplayRecord.refresh_status='failed'` rows (91 observed in prod-adjacent testing). `latency-reduce-delay-in-software-systems.md §Observability (Ch 10.7)` is the diagnosis: without separating queue-depth from processing health, "91 stuck replays" is discovered months late instead of the day it begins. `release-it.md §Steady State (5.4)` is the verdict: every accumulation mechanism must be purged or surfaced at the rate it grows.
3. **Recovery primitives are partly wired and must not be duplicated.** refa-6 Slice 4 extracted `OutboxMaintenanceService` (retry/discard/re-enqueue), and today `ConflictController`/`DeadLetterPanel` expose failed outbox retry/discard through `OutboxDrain` wrappers. This task should reuse or extend those seams; it only adds new recovery API where a verified gap remains.

## Constraints

- Curation-first conflict policy and local-read behavior must not regress (epic constraint).
- rg-002: recovery operations are thin delegations to existing `OutboxMaintenanceService` seams — never split one backend atomic operation into multiple frontend mutations.
- rg-007: any drain/loop change keeps bounded per-unit stall detection.
- sr-004: degraded/health indicators pair color with icon and text; tokens only.
- sr-009: new transactional PHP paths use the shared `run_transactional(callable)` wrapper.
- Characterization tests from refa-6 slice 1 (`SplitTopologyCommandDrainTest`, `OutboxDrainTest`) stay green throughout.
- Do NOT change `RecognitionProxyPolicy` default timeouts/thresholds in this task — they shipped reviewed; changing them is out of scope unless a finding demands it.

## Workflow Principles

- Surface before change: this task makes existing breaker/timeout behavior observable first; tuning or extending breaker coverage is a recorded decision, not a side effect (`release-it.md §Transparency (Ch 17)` — log/expose state transitions before optimizing them).
- Degradation is a designed product state: banner + per-surface affordances, never an implicit fallback (`refactoring-ui.md §Hierarchy is Everything`, §Don't Rely on Color Alone).
- Steady state: every queue this task touches gets a retention or operator-action story (`release-it.md §Steady State`).

## Terminology

- **Breaker transient**: `acx_recognition_circuit_<md5(base_url)>` — existence means OPEN for that base URL; expiry (default 60s) re-admits one attempt (effectively half-open).
- **Degraded mode**: breaker open for the effective target, or last sync pull failed; reads serve local projections, writes queue to outbox.
- **Async debt**: pending/failed outbox rows + open `acx_sync_conflicts` rows + failed curation replay records.
- **Request class**: `ui_read` / `background_sync` / `post_scan_read` / `mutation` — the policy key passed to `proxy_request()`.
- **Sync-row retention (this task)**: bounded purges of plugin-local terminal sync rows (acknowledged outbox, resolved conflicts). Distinct from the existing service-side **Retention domain** — `RetentionController` proxying `/acx/v1/retention/*`, `RetentionMode` (`retain_all`/`dispose_after_ack`/`purge_on_demand`), and `useRetentionStatus` rendered inside `SyncStatusIndicator.tsx`. Do NOT reuse `acx_retention_*` filter names or that UI vocabulary for sync-row purges; prefer `acx_sync_purge_*` naming.

## Current State Analysis (code-verified, commit `cb9d49dc`)

What exists and must not be duplicated:

- `apps/prototype-wp-alt-context/src/api/class-recognition-proxy-policy.php:16-55` — per-class policy. Defaults: `ui_read` 2s timeout / 1 retry / **circuit_enabled=true**; `background_sync` 30s / 3 retries / circuit off; `post_scan_read` 10s / 1 retry / circuit off; `mutation` 60s / 3 retries / circuit off. All values filterable (`acx_proxy_timeout_*`, `acx_proxy_max_retries_*`, `acx_proxy_backoff_base_ms_*`).
- `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:99-109` — breaker check before dispatch; `:408-444` — `build_circuit_breaker_key()`, `record_proxy_failure()` (threshold filter `acx_proxy_circuit_failure_threshold`, default 2; open window filter `acx_proxy_circuit_open_seconds`, default 60), `record_proxy_success()` (clears both transients).
- `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-client-transport.php:15-22` — sync drains reuse `proxy_request(..., 'background_sync')`; they are policy-covered already.
- `OutboxMaintenanceService` + `OutboxQueryRepository` (refa-6 slice 4) — recovery/query primitives, consumed through `OutboxDrain`, `ConflictResolutionService`, and `ConflictController`.
- `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` — `GET /acx/v1/recognition/sync-status` already reports `sync_health`, `last_sync_result`, pending/failed curation operation counts, open conflict count, and topology command counts. It does not read the recognition breaker transient.
- `apps/prototype-wp-alt-context/src/api/class-conflict-controller.php:80-113,202-299` — REST already lists outbox operations and exposes failed-operation retry/discard actions.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` and `DeadLetterPanel.tsx` — UI already surfaces queued/failed/conflict outbox state and failed outbox retry/discard controls.

What is missing (the actual scope):

- No endpoint reports breaker state or combines breaker state with the existing async-debt/status fields in one degraded-mode health contract.
- No persistent degraded-mode banner tells users "working offline from local copy" when the breaker is open; the existing sync status can say "offline" but does not distinguish designed local-read degradation from a generic sync problem.
- No retention/purge for acknowledged outbox rows, resolved conflicts, or terminal replay records.
- Service-side failed curation replays have no retry/discard surface; plugin-local failed outbox operations already do.

## Target Outcome

A `GET /acx/v1/recognition/sync/health` envelope reports `{breaker: {state, base_url, opened_at?}, outbox: {pending, failed}, conflicts: {open}, replays: {failed}, last_pull: {at, ok}}` cheaply (single-digit ms: transient read + indexed count/state reads). The admin UI shows a persistent degraded-mode banner driven by that envelope and reuses the existing conflict/dead-letter panels for plugin-local retry/discard. Acknowledged outbox rows and resolved conflicts purge in bounded batches piggybacked on existing drain cycles (not WP-Cron alone — WP-Cron fires only on traffic; a real-cron recommendation for self-hosters is documented in the same slice). Service-side failed replays warn at a threshold and require an explicit operator action or a recorded follow-on decision if no safe service endpoint exists.

## Context Loading

- Rules: `docs/workstate/rules/backend-php-guidelines.md`, `docs/workstate/rules/frontend-guidelines.md`, `docs/workstate/rules/testing-php.md`
- Contracts: `class-sync-status-controller.php` (existing sync status shape), `class-conflict-controller.php` (existing outbox/conflict recovery REST), refa-6 plan `docs/tasks/tech-debt/REFA-6-sync-drains-task-plan.md`
- Literature (read the cited sections before implementing): `release-it.md` §§ Circuit Breaker, Steady State, Fail Fast, Transparency; `latency-reduce-delay-in-software-systems.md` § Observability — separate queue-wait from processing time; `refactoring-ui.md` §§ Empty States, Color+Icon status.
- Handoff/MCP: E15-26 ref; E15-7 open findings (avoid double-fixing); refa-6 REV-B findings for drain seams.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET /acx/v1/recognition/sync/health` | plugin REST | none; related existing shape is `GET /acx/v1/recognition/sync-status` | new read-only debt+breaker envelope, or documented extension of sync-status if implementation chooses to avoid a sibling endpoint | n/a new/additive; existing sync-status clients must keep working | PHPUnit shape test + TS type |
| Breaker transients | plugin | written by proxy base, read nowhere | additionally read by sync-health (read-only) | yes — sync-health must never write them | PHPUnit: health call mutates no transient |
| Outbox recovery ops | plugin REST | existing `ConflictController` routes list outbox rows and retry/discard failed rows through `OutboxDrain`/`OutboxMaintenanceService` | reuse existing routes and UI; add only missing list/action fields proven necessary by the health panel | yes — preserve atomicity (rg-002) | PHPUnit through existing characterization suites |
| Failed-replay retry (service side) | service | replay records have no retry endpoint | possible thin endpoint — decide in Slice 2, record decision | yes if added | pytest |

## Proposed Solution

Three slices, strictly additive around the existing policy/breaker and sync-status layers: (1) sync-health envelope + TS type, (2) degraded banner + existing Async Debt/dead-letter panel integration + only missing recovery actions, (3) drain-coupled retention + thresholds. A failure-mode PHPUnit harness (a test double for `wp_remote_request` simulating hang/refuse/500/garbage — `release-it.md §Test Harness (5.7)`) backs the characterization of breaker-state reporting.

## Junior Implementer Guide

> Read this before touching code. It exists to keep you anchored to verified reality. **Rule zero: never trust a line number in this plan without re-verifying it** — run the grep given with each anchor; if it misses, search the symbol name instead and continue from what you find (rg-010: editor file models go stale; terminal grep is truth). If reality contradicts this plan in a way that changes a slice's design, STOP and record a blocker via `record_event(event_kind='blocker')` instead of improvising.

### Assumed setup

1. `make task-start TASK=E15-26 OBJECTIVE="..."` — creates worktree `../context-alt-text-monorepo-e15-26` on `feature/e15-26`. Work ONLY there.
2. `make context` at session start; fix drift warnings before editing.
3. Per slice: implement → `composer test` / `npm test` from `apps/prototype-wp-alt-context/` → `record_event(event_kind='test_result', ...)` → `close_slice(...)` → `render_handoff(kind='dashboard')`.

### Verified anchors (re-verify each before use)

| What | Where | Re-verify with |
| --- | --- | --- |
| Policy classes + defaults | `src/api/class-recognition-proxy-policy.php` | `grep -n "circuit_enabled" src/api/class-recognition-proxy-policy.php` |
| Breaker check + record | `src/api/class-abstract-recognition-proxy-controller.php` (~99-109, ~408-444) | `grep -n "circuit" src/api/class-abstract-recognition-proxy-controller.php` |
| Sync transport reuses proxy | `src/sovereign/sync/class-snapshot-client-transport.php` | `grep -n "proxy_request" src/sovereign/sync/class-snapshot-client-transport.php` |
| Recovery primitives | `src/sovereign/sync/class-outbox-maintenance-service.php` | `grep -n "function" src/sovereign/sync/class-outbox-maintenance-service.php` |
| Outbox/conflict tables | `wp_acx_sync_outbox`, `wp_acx_sync_conflicts` | grep schema/install code for `acx_sync_outbox` |

### Slice 1 walkthrough — sync-health envelope

1. New controller `src/api/class-sync-health-controller.php` registering `GET /acx/v1/recognition/sync/health` with the same permission callback style as `class-sync-status-controller.php` (copy its `register_routes` idiom; do not invent a new auth pattern). Wire the new controller into `src/api/class-recognition-controller.php` — the composition root that instantiates and registers the existing sync/conflict controllers — and add `require_once` entries for the new `class-*.php` files (rg-016: WordPress-style filenames are not PSR-4 autoloadable; verify with a runtime-style `class_exists` check). If implementation instead extends `GET /acx/v1/recognition/sync-status`, record the compatibility decision and keep the existing fields stable.
2. Breaker state: compute the effective base URL via `RecognitionEndpointResolver->get_effective_base_url()`, derive the transient key exactly as the proxy does. The key derivation is private to the abstract controller — extract `build_circuit_breaker_key()` into a small shared final class (e.g. `RecognitionCircuitKeys`) and have BOTH call sites use it; do not copy-paste the md5 expression (one-source rule; this is Fowler's Extract Function/Class move — `refactoring-fowler-beck.md §Extract Class` — applied to avoid a duplicated key recipe that silently diverges).
3. Counts: prefer existing `SyncStateRepository`/`SyncStatusController` state for the fields it already owns; use `OutboxQueryRepository`/`ConflictRepository` count methods only for fields not already present (`grep -n "count" class-outbox-query-repository.php`, `grep -n "count_conflicts" class-conflict-repository.php`). Do NOT write raw `$wpdb` queries in the controller.
4. `replays.failed`: replay records live service-side (`CurationReplayRecord`, Python). For Slice 1 report only what the plugin knows locally; if the sync-status surface already mirrors replay state, reuse it (`grep -rn "replay" src/api/ src/sovereign/`). If nothing local exists, return `replays: {failed: null, source: 'unavailable_local'}` — an honest null, never a fabricated 0 (rg-015: boundary adapters must not invent contract metadata).
5. The endpoint must be read-only: assert in a test that calling it changes no `acx_*` transient/option.
6. TS: add `SyncHealthResponse` to `js/admin/api/` mirroring the PHP shape exactly; PHPUnit shape test + Vitest type usage.

Didactic note: this envelope is the `latency-reduce-delay-in-software-systems.md §Observability` move — queue-depth (outbox/conflicts/replays) separated from liveness (breaker/last_pull) so an operator can tell "service is slow" from "debt is accumulating" at a glance.

### Slice 2 walkthrough — banner + Async Debt panel + recovery

1. Banner component in `js/admin/`: poll `recognition/sync/health` with react-query (`staleTime` ≥ 15s; do NOT poll faster — the breaker open window is 60s, sub-15s polling adds nothing but load). Banner shows when `breaker.state === 'open'` or `last_pull.ok === false`: amber surface, alert icon + "Working offline — showing your local copy; changes will sync when the service returns" (sr-004: icon + color + text; `refactoring-ui.md §Don't Use Grey Text on Colored Backgrounds` for the banner palette — pick a token pair, not opacity tricks).
2. Async Debt panel: reuse `SyncStatusIndicator`, `DeadLetterPanel`, the conflict overlay, and existing `ConflictController` outbox routes. Add or rearrange UI only where the health envelope needs to link users into those existing panels.
3. Recovery REST: do not add duplicate retry/discard routes for plugin-local failed outbox rows. Only add a REST action if a verified gap remains; each action is a thin delegation: validate id → call the existing maintenance/drain service → return the service result. No business logic in the controller (rg-002). If you find yourself writing more than ~15 lines per action, stop — you are reimplementing the service.
4. Service-side failed-replay retry needs a service-side decision: check whether a replay-retry endpoint exists (`grep -rn "replay" apps/prototype-description-service/recognition/interface_adapters/http/routers/`). If not, record a decision: either add a thin authenticated POST in this slice (boundary table row!) or defer replay-retry to a follow-on finding. Do not silently widen scope.

### Slice 3 walkthrough — retention + thresholds

1. Purge methods on `OutboxMaintenanceService` (bounded `LIMIT` batches, oldest-first): acknowledged outbox rows older than N days (default 14, filterable), resolved conflicts older than N days. Wrap multi-statement purges in `run_transactional` (sr-009).
2. Invoke one bounded purge batch at the end of each successful drain cycle in `class-outbox-drain.php` — find the cycle-complete point with `grep -n "function drain" class-outbox-drain.php` and read the refa-6 plan first so you respect the extracted phase structure. WP-Cron may ALSO schedule purges, but drains are the primary trigger (idle installs never fire WP-Cron — that's why; `release-it.md §Steady State`).
3. Thresholds: `recognition/sync/health` gains `warnings: []` entries when failed replays or open conflicts exceed filterable thresholds (defaults: 10 replays, 25 conflicts). The banner surfaces a secondary line when warnings are non-empty.
4. Characterization guard: run `composer test` filtering `OutboxDrainTest` BEFORE and AFTER wiring the purge call; the pre-existing assertions must not change.

### Pitfalls (each has bitten an agent before)

- The breaker is per-base-URL. Switching Local↔Service changes the transient key — the health endpoint must report the breaker for the *effective* target, not all targets.
- `background_sync` has `circuit_enabled=false` by design (writes must keep queueing into the outbox rather than short-circuit). Do not "fix" that — outbox queuing IS the degradation path for writes (`designing-data-intensive-applications.md §Offline-Capable Replicas`: clients hold local state and catch up; the outbox is our replication log, §Log-Based Derivation).
- Three or more findings in one review pass → `review_findings(operation='batch_record')`, never serial single records.
- Never edit files via absolute paths into the ROOT repo while working this task — you will silently write to `main` (see memory: worktree absolute-path hazard). Stay in the e15-26 worktree.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Circuit key extraction | `src/api/class-recognition-circuit-keys.php` (new) + abstract proxy controller | shared key derivation, no behavior change |
| Health endpoint | `src/api/class-sync-health-controller.php` (new) | debt + breaker envelope |
| Controller wiring | `src/api/class-recognition-controller.php` | instantiate + register `SyncHealthController` alongside the existing sync/conflict controllers; `require_once` the new `class-*.php` files (rg-016 autoload parity — verify with a runtime-style `class_exists` check) |
| Existing sync status | `src/api/class-sync-status-controller.php` + `src/sovereign/repositories/class-sync-state-repository.php` | reuse or extend existing debt/last-pull state instead of duplicating counts |
| Existing outbox recovery REST | `src/api/class-conflict-controller.php` + `src/sovereign/sync/class-outbox-drain.php` | reuse retry/discard; add only verified missing actions |
| Count queries | `src/sovereign/sync/class-outbox-query-repository.php`, `class-conflict-repository.php`, or existing sync-state repository | narrow count methods only if absent |
| Retention | `src/sovereign/sync/class-outbox-maintenance-service.php` + `class-outbox-drain.php` | bounded purges invoked from drain cycles (WP-Cron secondary) |
| UI | `js/admin/` banner + existing Async Debt/dead-letter panel integration + `SyncHealthResponse` type | degraded mode + recovery |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | Existing sync/debt status payload and route style to preserve |
| `apps/prototype-wp-alt-context/src/api/class-conflict-controller.php` | Existing conflict/outbox list and retry/discard routes |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | Current sync health/debt indicator |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx` | Existing failed outbox timeline and retry/discard UI |
| `apps/prototype-wp-alt-context/tests/Unit/SyncStatusControllerTest.php` | Existing sync-status contract coverage |
| `apps/prototype-wp-alt-context/tests/Unit/ConflictControllerTest.php` | Existing outbox/conflict recovery coverage |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && composer test` — health shape; read-only assertion; breaker-state reporting via failure-mode harness (hang/refuse/500/garbage double per `release-it.md §Test Harness`); recovery delegation atomicity; purge batches; refa-6 characterization suites untouched-and-green
  - `npm test` — banner state matrix (closed/open/last-pull-failed/warnings); debt panel actions
- Contract verification: `recognition/sync/health` PHPUnit shape ↔ `SyncHealthResponse` TS type; existing `recognition/sync-status` shape remains backward-compatible.
- Manual: stop local service mid-session → banner within one poll interval; curation reads still work; restart → breaker window expiry clears banner; seeded failed outbox row retried from panel.

## Slice Delivery

### Slice 1: Sync-health envelope

**Goal**: breaker state + async-debt counts are queryable in one cheap read-only call.

Changes: circuit-key extraction; health controller; count methods; TS type.
Proof: PHPUnit shape + read-only tests; refa-6 suites green.

### Slice 2: Degraded-mode banner + recovery actions

**Goal**: users see offline mode; operators retry/discard debt from the UI.

Changes: banner; health links into existing debt panels; only missing recovery REST delegations; replay-retry decision recorded.
Proof: Vitest state matrix; PHPUnit delegation tests; manual offline walkthrough.

### Slice 3: Steady-state retention + thresholds

**Goal**: terminal rows purge in bounded batches; debt past thresholds warns visibly.

Changes: purge methods + drain-cycle invocation + WP-Cron secondary; threshold warnings in envelope + banner.
Proof: purge test with seeded aged rows; characterization suites green; threshold warning rendering test.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded refa-6 plan + characterization suites + E15-7 scope fence + cited literature sections before editing.
- [ ] Re-verified every code anchor with the greps in the Junior Implementer Guide.
- [x] Boundary rows recorded in slice-close decisions.

### Checklist for Slice 1: Sync-health envelope

- [x] Circuit key derivation extracted and shared (no copy-paste)
- [x] Envelope shipped read-only with honest nulls (no fabricated counts) + TS type
- [x] New controller wired in `class-recognition-controller.php` with rg-016 autoload parity verified
- [x] Evidence recorded

### Checklist for Slice 2: Banner + recovery

- [x] Banner meets sr-004 (icon + color + text) and polls ≥15s intervals
- [x] Existing outbox retry/discard routes are reused; any new recovery action is a thin delegation; replay-retry decision recorded
- [x] Evidence recorded

### Checklist for Slice 3: Retention + thresholds

- [x] Drain-coupled bounded purges with run_transactional; WP-Cron secondary; real-cron documented
- [x] Threshold warnings in envelope and banner
- [x] Slice-complete decision + dashboard render

## Review Readiness

- [x] Refa-6 characterization suites untouched-and-green or consciously extended.
- [x] No atomic backend write split across frontend mutations.
- [x] `RecognitionProxyPolicy` defaults unchanged (or change justified by a recorded finding).

## Stretch Goals

- [x] None declared; defer any extra recovery mode or service-side replay tooling through a recorded decision/follow-on finding.

## Success Criteria

- [ ] Service offline: curation reads work, one banner explains why, and `recognition/sync/health` reports breaker open + debt counts.
- [ ] A seeded failed outbox row can be retried or discarded from the UI without touching the database manually.
- [ ] Aged terminal rows are purged by normal drain activity; debt past thresholds is visibly warned, not silently accumulated.
