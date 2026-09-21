# DEMOHEAL-1. Truthful Service State and Reclaimer Liveness

> - **Date**: 2026-09-21
> - **Author**: Claude Fable 5.1; planning revisions by Codex
> - **Owning Epic**: [E25. Truthful Service State and a Self-Healing Mirror](../../epics/v0.5.0/demo-operability-and-mirror-self-healing-epic.md)
> - **Epic Short ID**: `DEMOHEAL`
> - **Task ID**: `DEMOHEAL-1`
> - **Target Branch**: `feature/demoheal-1`
> - **Review Coverage Target**: 2
> - **Derived from**: [assessment](../../assessments/current/demo-operability-defects-assessment-2026-09-21.md) F1–F6; [scope](../../scopes/demo-operability-and-mirror-self-healing-scope.md)
> - **Production baseline verified**: `11fe4dea7`, 2026-09-21. New symbols and routes below are proposals.

## Objective

Retention reaches the real API. Degraded plugin surfaces name the service, reason and last observation; Settings exposes bounded connection diagnostics. Warming has a finite observation deadline. Reclaimer successful completion and backlog are visible, and sync can perform bounded local recovery.

## Intake

The reported symptoms S1–S4 motivate this task. F7 dataset replacement and F8/F9 cluster quality remain DEMOHEAL-2/3. This plan includes API manifest tooling and request-id middleware; it is not plugin-only. Root cause of the historical generic retention panel remains a hypothesis until a browser capture exists.

## Problem Statement

- `RetentionController` calls unprefixed retention paths; substring assertions conceal the mismatch.
- Retention and GPU consumers lose typed availability information through missing-endpoint and error paths.
- The breaker has no operator query/reset or transition history. No request id joins WP and API.
- `useDescribeRunProgress` disables its watchdog during warming.
- Purge completion is unobserved. Existing scheduling prefers Action Scheduler, then WP-cron; old rows do not prove neither scheduler ran.

## Constraints

- No new runtime dependencies or GPU lifecycle-unit changes. Preserve declared PHP >=8.0 with class-constant vocabularies, not new native enums.
- Existing purge eligibility, row-level concurrency protections and tenant isolation remain authoritative.
- Greenfield schema policy applies; no compatibility shim. API logging and manifest tooling are explicit scope.
- Secrets, full query strings, bodies and arbitrary upstream errors never enter diagnostics. Admin diagnostics are capability/nonce guarded.
- Remote isolated build/test/review work is allowed. Production reads, destructive cleanup and deploy acceptance remain operator-run. This planning pass makes no production changes.
- Canon [heuristics-canon](https://github.com/darce/heuristics-canon) is read-only; cite stable rule IDs at use time.

## Workflow Principles

Each implementation slice begins with a defect-reproducing test, closes with its bounded proof and records a handoff decision/test result. Independent slices begin together according to the DAG. Shared-file integration has one owner. Planning and implementation findings live in MCP, not this checklist.

## Terminology

| Term | Meaning |
| --- | --- |
| Route family | Existing breaker partition passed to `proxy_request` |
| Unavailable envelope | Existing typed availability observation plus optional request id |
| Attempt ring | Bounded best-effort diagnostic history; explicitly distinguishes sent/not_sent |
| Connection check | Explicit POST read-only probes; GET returns cached diagnostics |
| Warming deadline | Finite UI observation policy, not a backend completion guarantee |
| Reclaimer success | A committed eligible purge/reclaim batch, distinct from empty backlog |
| Freshness breach | Last successful batch older than two effective scheduler periods |

## Current State Analysis

Codebase graph search/snippets at `11fe4dea7` verified these existing anchors. Prefix `P` below means `apps/prototype-wp-alt-context`; `S` means `apps/prototype-description-service`. Prefixes are path abbreviations only.

| Existing anchor | Observed behavior |
| --- | --- |
| `P/src/api/class-retention-controller.php:RetentionController` | Nine retention call sites; private `build_unavailable_envelope` |
| `P/src/api/class-gpu-control-controller.php:GpuControlController::build_unavailable_envelope` | Duplicate builder |
| `P/src/api/class-abstract-recognition-proxy-controller.php:AbstractRecognitionProxyController::proxy_request/record_proxy_failure` | Per-family breaker; headers and early returns are here |
| `P/js/admin/api/recognition/retentionApi.ts:fetchRetentionStatus` | Missing localized endpoint returns envelope-free unavailable |
| `P/js/admin/utils/serviceUnavailable.ts:parseUnavailable/readUnavailable` | Shared parser to extend, including thrown error path |
| `P/js/admin/hooks/useDescribeRunProgress.ts:useDescribeRunProgress` | Watchdog suppressed by `isWarming`; exposes run/startup id |
| `P/js/admin/hooks/useActivityStatus.ts:useActivityStatus` | Consumes run and GPU state |
| `S/scene/interface_adapters/http/routers/gpu.py:GpuStatusResponse/GpuStateResponse/GpuIntentStatus` | Nested GPU status and freshness; no warm-up deadline field or `active` intent status |
| `P/src/sovereign/sync/class-outbox-maintenance-service.php:OutboxMaintenanceService::maybe_schedule_purge/purge_terminal_rows/purge_failed_non_retryable_batch` | Hourly Action Scheduler single action, daily cron fallback; array or false result; bounded eligibility-filtered batches |
| `P/src/sovereign/sync/class-outbox-drain.php:OutboxDrain::purge_terminal_rows_for_tenants` | Reuses maintenance service; failure hook |
| `P/src/api/class-sync-status-controller.php:SyncStatusController::run_sync_action` | Local purge must not depend on upstream sync succeeding |

Graph coverage for these inspected paths had no recorded issue; this is best-effort, not an exhaustive proof. F1 route claims additionally need the emitted-method/path test in slice 1. No live demo capture was obtained during planning.

## Target Outcome

```text
SPA -> WP ingress request id -> proxy attempt -> API request-scoped logs
        |                        |
        +-- local not_sent       +-- bounded per-family diagnostics
        +-- one envelope -> one notice

fresh GPU truth + finite observation deadline -> warming / unknown / stalled
per-tenant purge success + backlog -> health display + bounded next-sync recovery
```

## Context Loading

- [Draft operability contracts](../../scopes/demoheal-operability-contract-draft.md): mandatory detailed wire, state, locking and failure semantics for all five slices.
- [Parallel delivery packet](../../scopes/demoheal-parallel-delivery.md): defect groups, work DAG and explicit lane inputs/outputs.
- Role maps: `docs/workbay/maps/php-plugin.md`, `frontend.md`; contracts `gpu-lifecycle.md`, `security.md`.
- UX maps: `P/docs/ux-maps/gpu-operator-control` and `describe-gpu-tier`; run `python3 docs/ux-maps/render_ux_maps.py --check` from P before and after edits.
- Prior art: semantic gte-base-en-v1.5 hits VLM-2B finding 2148, VLM-6 finding 9234, E15-35 decision 2514; semantic reinjection decision 13168. Read exact prior rows before treating a retrieved similarity as authority.
- Continuation `cont-20260919T232614799720Z-d1c8fec2`: GPUFLOW-3 is already gated; do not repeat its review. The second requested packet was absent from current MCP; do not reconstruct its content from its id.
- Canon: RES-07/15, OBS-03/04/05/08, SEC-01, CARD-03/07/09, GRPH-01/09/31/32/33; *Release It!* §5.1–5.5/17, *Latency* §11.4 value prediction, DDIA ch-8/11/12. OBS-08 freshness mechanism is in *Observability Engineering* ch-18. Analogy is explicitly distinguished from trigger match in the assessment.

## Contract and Boundary Impact

| Boundary / owner | Contract | Change / compatibility | Proof |
| --- | --- | --- | --- |
| API manifest / Python tooling | `proxy-route-manifest.md` (new) | Deterministic sorted method/path export, checked fixture; no API behavior change | Export freshness + actual PHP emission parity |
| WP→API retention / PHP proxy | same | Correct prefix; static route mismatch differs from entity 404 | Exact URL/method assertions |
| WP REST→SPA / PHP + TS | same | Shared vocabulary and optional request id; PHP 8.0 class constants | Producer/consumer fixtures and error-path rendering |
| WP→API request header / both HTTP boundaries | `security.md` | Validated UUID; API echo/logging; no authentication meaning | Concurrent/exception/access-log tests |
| Connection endpoints / WP admin | same | GET cached status; POST check/reset, capability/nonce, fixed targets | Unauthenticated/forbidden/timeout/concurrency tests |
| GPU status→UI / existing API + frontend policy | `gpu-lifecycle.md` | No invented backend bound; finite UI observation fallback | Fake timers, fresh/stale fixtures, remount |
| Purge→status / PHP maintenance | new reclaimer section of proxy contract | Per-tenant success/attempt/backlog; bounded lock/cleanup | Failure, tenant and contention tests |

## Proposed Solution

Apply the detailed draft contract, not a shorthand inferred from this summary. First declare retention routes and prove actual requests match the API manifest. Hoist genuinely shared unavailable construction and render one notice from both data and error paths. Add bounded diagnostic probes and breaker state transitions without changing auth or waking the GPU. Give warming a finite policy deadline using existing nested status fields. Instrument successful purge completion and allow bounded inline recovery even when upstream is unavailable.

Coupling: route inventory and envelope fixtures are semantic/developmental contracts; network availability is operational coupling; the shared abstract proxy is functional coupling. Keep diagnostics bounded so it does not add a new operational dependency. Cross-language parity is intentional and tested rather than claimed independently deployable.

## Files and Surfaces to Change

Existing change symbols appear in Current State Analysis. Additional symbols below are **new** unless stated otherwise; each slice includes its corresponding tests.

| Slice | Surface / change symbols |
| --- | --- |
| 1 | `P/src/api/class-proxy-routes.php:ProxyRoutes`; existing `RetentionController`; `P/tests/Unit/ProxyRouteParityTest.php:ProxyRouteParityTest`; existing `RetentionControllerTest`; `S/scripts/export_route_manifest.py:export_route_manifest`; `S/api/tests/test_route_manifest_fresh.py:test_route_manifest_fresh`; root `Makefile:export-route-manifest`; `P/tests/fixtures/api-route-manifest.json`; new route contract |
| 2 | Existing two builders and abstract proxy; `P/src/api/class-unavailable-reason.php:UnavailableReason` constant class; existing parser/fetcher; `P/js/admin/components/ServiceUnavailableNotice.tsx:ServiceUnavailableNotice`; existing `RetentionPage` and `GpuControlCard`; Description Service state within `GpuControlCard` (not a third independent component); shared vocabulary fixture |
| 3 | Existing `proxy_request/record_proxy_failure`; `P/src/api/class-connection-controller.php:ConnectionController::register_routes/get_status/check/reset_breaker`; `P/js/admin/pages/settings/ConnectionCheckCard.tsx:ConnectionCheckCard`; existing `S/recognition/interface_adapters/http/middleware/correlation.py:CorrelationIdMiddleware/CorrelationIdFilter/generate_correlation_id`, `S/api/logging_config.py:configure_logging` and `S/api/main.py` middleware registration; controller registration, localized endpoint keys and Settings mount included |
| 4 | Existing `useDescribeRunProgress/useActivityStatus`; `P/js/admin/utils/warmingDeadline.ts:deriveWarmingObservation`; `gpu-lifecycle.md` UI policy section; UX-map mirrors |
| 5 | Existing maintenance service, OutboxDrain and sync status controller; sync-status TS response/parser and its existing status renderer; tenant-scoped success/attempt/backlog state; effective-scheduler-period helper and atomic lease helper (new) |
| Integration | Plugin entrypoint/manual includes and admin endpoint localization as needed; `P/uninstall.php` union of new options; Settings registration; generated contract fixtures; UX maps; cross-lane proofs. One integrator owns shared registration/uninstall files |

Frontend registration/localization and sync-status rendering are required behavior, not optional follow-up. Existing grounded anchors: `P/src/api/class-api.php:Api::register_routes`, `P/src/admin/class-admin.php:Admin::localize_spa_config`, `P/js/admin/pages/SettingsPage.tsx:SettingsPage`, `P/js/admin/api/recognition/types/sync.ts:SyncStatusResponse`, `P/js/admin/api/recognition/syncApi.ts:fetchSyncStatus`, `P/js/admin/hooks/useSyncStatus.ts:useSyncStatus`, `P/js/admin/pages/workbench/SyncStatusIndicator.tsx:SyncStatusIndicator/SyncStatusStrip`. Extend these with the new response fields; add explicit normalization/validation in `fetchSyncStatus` if its current implementation does not validate them. `GpuControlCard` itself renders the Settings Description Service state; do not invent a separate third chip module. API correlation already exists under `CorrelationIdMiddleware`, registered in `api/main.py`; extend it and `CorrelationIdFilter`, never create a second request-context system. Do not invent an autoload mechanism: test the runtime entrypoint as well as Composer's test autoloader.

## Related Files

Extend `P/tests/Unit/ProxyRequestTest.php`, `RecognitionProxyRetryPolicyTest.php`, `GpuControlControllerTest.php`, `OutboxMaintenanceServicePurgeTest.php` and the existing hook tests. Inspect actual producer shapes before mocking. API dependency timing log changes belong to DEMOHEAL-4; do not bundle them into the request-id lane.

## Verification Strategy

All commands run from the stated directory. Remote sandboxes must install their own test dependencies; missing `vendor`/`node_modules` is an environment failure, not a product regression. Named new tests are delivered in their slice.

| Slice | Bounded command / location |
| --- | --- |
| 1 PHP | `composer test -- --filter 'RetentionControllerTest|ProxyRouteParityTest'` from P |
| 1 API | `uv run pytest api/tests/test_route_manifest_fresh.py` from S on remote test VM; root `make export-route-manifest` is a **new target**, runs exporter with explicit output P fixture path |
| 2 PHP | `composer test -- --filter 'RetentionControllerTest|GpuControlControllerTest|UnavailableEnvelopeTest'` from P; last class new |
| 2 TS | `npx vitest run js/admin/components/__tests__/ServiceUnavailableNotice.test.tsx js/admin/api/recognition/__tests__/retentionApi.test.ts` from P; add fixtures for both available:false and thrown WP errors |
| 3 PHP | `composer test -- --filter 'ProxyRequestTest|RecognitionProxyRetryPolicyTest|ConnectionControllerTest'` from P; last class new |
| 3 API/TS | `uv run pytest recognition/tests/api/test_correlation.py api/tests/test_request_id.py` from S (second file new); `npx vitest run js/admin/pages/settings/__tests__/ConnectionCheckCard.test.tsx` from P (new) |
| 4 | `npx vitest run js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx js/admin/hooks/__tests__/useActivityStatus.test.ts js/admin/utils/__tests__/warmingDeadline.test.ts` from P; last file new |
| 5 | `composer test -- --filter 'OutboxMaintenanceServicePurgeTest|SyncStatusControllerTest'` from P; `npx vitest run js/admin/pages/workbench/__tests__/SyncStatusIndicator.test.tsx js/admin/hooks/__tests__/useSyncStatus.test.tsx` from P |
| Integration | Changed-path `composer cs-check`, `npm run lint`, service ruff; runtime include/load check; contract and UX-map checks. Distinguish style debt from syntax/security/contract failure; no blanket downgrade of all lint findings |
| Plans | `make lint-task-plans` where installed; if facade missing, record that limitation and run available direct structural/link checks |
| Live acceptance | Operator plugin packaging/deploy plus API release; record bundle version and received-request log correlation. No destructive cleanup needed for deterministic tests |

## Slice Delivery

### Slice 1: Retention route parity

- **Goal**: Correct nine call sites and make actual method/path drift fail CI.
- **Changes**: exporter + freshness test (lane S1A), map/callers/exact assertions + emitted-request parity (S1B). Scope the map honestly to migrated callers.
- **Proof**: baseline unprefixed emitted paths fail; corrected paths pass; reverting one caller fails even if the map remains correct. Exporter works without live API/DB. Run slice 1 commands above.

### Slice 2: Shared unavailable contract and notice

- **Goal**: Retention and the GPU card including its Description Service state render the same vocabulary from data and error paths.
- **Changes**: shared PHP builder/vocabulary (S2A), consumer types/parser/notice (S2B), constrained static-route mismatch mapping. Do not convert entity-not-found to contract mismatch.
- **Proof**: table-driven reason producer/consumer tests; missing endpoint, missing key, 401/403, resource 404, router 404/405, 429, timeout, 5xx, breaker-open and malformed envelope. The browser capture is a historical-cause check only; independent deterministic fixes do not wait for it.

### Slice 3: Bounded connection diagnostics and correlation

- **Goal**: Settings distinguishes received responses, attempted-but-unreceived requests and local not_sent rejection.
- **Changes**: WP diagnostic/breaker lane S3A; independent API request-id lane S3B; Settings consumer S3C. Contract specifies total budget, one half-open trial, versioned reset race, redaction and explicit POST probes.
- **Proof**: trip/open/no upstream/reset/half-open concurrency, authorization, nonce, secret-exclusion and fixed-target tests; real API access logging on success/error/concurrent requests. No API-log requirement for local rejection or a connection failure the API never received.

### Slice 4: Finite warming observation

- **Goal**: No live run remains indefinitely represented as warming without fresh evidence.
- **Changes**: shared helper and both hooks, finite proposed 600s+30s policy, persisted first observation per run/startup, unknown-vs-stopped distinction, demand-driven START without a required operator intent, Retry refetch without duplicate work. Full semantics in draft contract.
- **Proof**: fake timers, stale/missing/malformed/fresh nested fixtures, bound edges, polling/remount and actual resumed/terminal progress; UX-map check. Runs independently from slice 3.

### Slice 5: Successful-run liveness and bounded purge

- **Goal**: Show per-tenant purge health and backlog; local recovery can run even if upstream fails.
- **Changes**: completion instrumentation at shared maintenance boundary; atomic tenant lock with owner-safe release; effective schedule period; capped inline batch; retry/reschedule on failure; status type/parser/renderer.
- **Proof**: never-run, old-success, false/exception/rollback, partial backlog, concurrent claim, expired owner, tenant isolation, scheduler modes and upstream unavailable. Only committed batches advance last-success; a capped backlog remains visible and eligible for subsequent recovery. Runs independently from slice 3.

## Lane Decomposition (Multi-Agent)

The [dependency packet](../../scopes/demoheal-parallel-delivery.md) and [machine-readable DAG](../../scopes/demoheal-dependency-dag.json) are authoritative. Initial independent work: S1A, S3B, S4, S5. S1B consumes the manifest; S2A consumes route metadata; S2B and S3A consume the envelope vocabulary independently; S3C consumes both. Integration consumes their proofs and owns shared registration/uninstall files. Reserve changed shared files for one writer; use symbol-level contract stubs in separate worktrees only after outputs are frozen.

Requested mechanical-review adapter: `codex-remote`, `gpt-5.6-luna`, `max`; no silent fallback. Passing a planning review does not prove the remote adapter executed. Remote result/provenance and blockers remain in handoff.

## Consolidated Checklist

## Context and Ownership

- [ ] Load draft contracts, dependency packet, code anchors and handoff; freeze lane input/output contracts before dispatch.
- [ ] Use the grounded registration/localization/correlation/sync-rendering anchors above; pin proposed shared database CAS helper in each edit packet and test its atomic behavior.
- [ ] Record review evidence and declared runtime/tenant boundaries.

### Checklist for Slice 1

- [ ] Exporter/freshness target and actual emitted-method/path parity tests, red then green.
- [ ] Nine retention call sites migrated; static-vs-entity 404 classification metadata.
- [ ] Contract and tracked fixture updated in the same slice.

### Checklist for Slice 2

- [ ] One PHP 8.0-compatible vocabulary/builder; TS fixture parity.
- [ ] Retention and GPU/Description Service states use notice for returned and thrown failure paths.
- [ ] Characterization tests pass; historical browser cause remains evidence-tagged until captured.

### Checklist for Slice 3

- [ ] Capability/nonce, fixed probes, deadlines and redaction tests.
- [ ] Atomic half-open admission and reset-race tests; bounded rings.
- [ ] Correlation echo and actual request-scoped access logs verified; local not_sent truthful.
- [ ] Runtime controller registration and Settings mount/localization tested.

### Checklist for Slice 4

- [ ] Existing wire fields only; finite shared policy and stable run/startup deadline.
- [ ] Fresh/stale/unknown, expiry/remount/Retry and terminal transition tests; UX-map parity.

### Checklist for Slice 5

- [ ] Tenant success vs attempt vs backlog, scheduler modes and unknown state.
- [ ] Atomic claim/owner-safe release; bounded batches; failure does not advance success.
- [ ] API outage does not prevent local purge; status parser/renderer displays breach and backlog.

## Review Readiness

- [ ] All cross-boundary fields have matching contract/fixture evidence.
- [ ] Reviewers receive prior-art context, exact anchors and bounded diff; they may read producers/consumers where necessary. No whole-file-reading prohibition that prevents grounding.
- [ ] One integrator combines registration/uninstall/UX changes; changed proofs rerun after integration.
- [ ] Required planning coverage exists in MCP; one harmonizing branch review before merge; no re-review of already gated GPUFLOW-3.
- [ ] Operator live acceptance separately recorded; a docs review does not mark application defects fixed.

## Stretch Goals

- Copyable redacted support report; manual trip control separate from reset.

## Success Criteria

- Retention loads actual policy; all degraded surfaces display the same truthful vocabulary and optional fields.
- Settings identifies local not_sent vs received upstream failure, with no secret leakage or unbounded probes.
- Received requests correlate in WP/API logs after both deploys; local rejected requests remain WP-only.
- Warming transitions to unknown/stalled at its documented bound without claiming the backend job failed or posting duplicate work.
- Overdue reclaimer attempts bounded local work on sync; committed success clears freshness breach while remaining backlog stays visible.

The existing `AbstractRecognitionProxyController::acquire_named_lock/release_named_lock` provides bounded MySQL named locking around breaker updates. Reuse this serialization when extending breaker state, with timeout clamped to the diagnostic budget. New persistent half-open ownership/expiry must be tested against this boundary; do not duplicate lock state in a process-local cache. Purge has no corresponding named-lock helper in the inspected sync scope, so slice 5 introduces its tenant-scoped atomic database lease explicitly.
