# E15-24. Architecture Coherence Assessment — Tenancy, Environments, Sovereignty, Pipeline

> **Metadata**
>
> - **Date**: 2026-06-10
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Kind**: assessment (companion to task plans E15-24 … E15-28; not itself an implementation plan)
> - **Literature inputs**: `literature/extracted/refactoring/distilled/` — designing-data-intensive-applications.md, release-it.md, latency-reduce-delay-in-software-systems.md, using-asyncio-in-python.md, refactoring-ui.md

## Problem

The product requirement "curated faces stay usable when the remote service is offline" (plugin sovereignty) is sound, but its implementation has tangled four concerns that should be independent seams: tenant identity, environment routing, sync resilience, and job orchestration. The tangle surfaces as concrete defects: media analysis scans fail with stuck jobs, the Service/Local toggle renders invisible (missing CSS), the settings page communicates routing state ambiguously, curation replays accumulate in failed state (observed: 91), and pointing local dev at prod tried to mint a `localhost:10010` tenant in the prod database.

## Smell Inventory (verified against code)

| # | Smell | Evidence | Principle violated |
|---|-------|----------|--------------------|
| S1 | Tenant identity derived from mutable env-specific value | `apps/prototype-wp-alt-context/src/api/class-tenant-identity.php:26-40` — `sha1('acx-site-tenant:' + siteurl)`, derived per request, never persisted; no constant/filter/option seam (unlike URL/key/source, all 4-level chains) | DDIA: partition-key stability — keys that partition all tenant data must be invariant; a URL/port change silently orphans every face, cluster, and curation row |
| S2 | Identity authority is ambiguous between plugin and service | Service binds tenant to API key (`auth.py:133-226`, `tenant_claim` from `api_keys` table, 403 on mismatch) while plugin re-derives from URL each request; service JIT-provisions placeholder tenants (`db/tenant_context.py:22-45`) | DDIA: single system of record — two derivation paths for one identity guarantee eventual divergence |
| S3 | Environment routing has inference-sandwiched precedence and a binary UI for a 4-environment topology | `class-recognition-endpoint-resolver.php:69-97` — `service` mode inferred from a non-empty service URL at two points (75-77: constant/filter URL outranks explicit source option; 89-94: option URL implies service below the explicit option); backend runs prod/staging/dev subdomains (infra/oci/README.md:324-333) but plugin UI offers only local/service | `release-it.md §Configuration Files (14.2)`: explicit per-environment configuration; no inferred routing |
| S4 | Settings UI does not communicate state | `.acx-radio-group__*` classes have no stylesheet (no `_radio-group.scss`, not in `js/admin/styles/components/index.scss`) — toggle invisible; inert credentials ("stored for service mode") shown at equal visual weight to active routing | Refactoring UI: hierarchy, affordance, designed empty/inactive states |
| S5 | Boundary resilience exists but is invisible and unrecoverable (corrected rev 2 after code verification) | `RecognitionProxyPolicy` + `proxy_request()` already apply per-class timeouts and a `ui_read` circuit breaker (`class-recognition-proxy-policy.php:16-55`, `class-abstract-recognition-proxy-controller.php:99-109,408-444`); but breaker state/debt counts surface nowhere, offline degradation (`data_source='local_projection'`) has no UI affordance, and failed sync work has no recovery path | `release-it.md §Transparency (Ch 17)`: expose state transitions; `§Graceful Degradation`; `latency-reduce-delay-in-software-systems.md §Observability (10.7)` |
| S6 | Failed async work accumulates without recovery path | `CurationReplayRecord.refresh_status='failed'` rows have no automatic retry and no operator surface; `acx_sync_conflicts` and outbox rows accumulate unbounded | Release It: steady state; latency lit: queue-depth observability separates queue-wait from processing failure |
| S7 | Scan jobs fail late instead of failing fast | `scan_worker.py` falls back to `UnavailableFaceDetector` when InsightFace is missing; items fail one-by-one at process time; job appears stuck in UI | Release It: fail fast — check required resources at transaction start; asyncio lit: structured task lifecycle with explicit terminal states |

## Target Architecture (decision summary)

1. **Tenant identity becomes explicit, persisted, and key-anchored.** Resolution chain `ACX_RECOGNITION_TENANT_ID` constant → `acx_recognition_tenant_id` filter → option → one-time URL derivation persisted to the option (sticky). The API key's `tenant_claim` is the service-side authority; a pairing step adopts the canonical tenant id from the service and stores it. URL changes stop orphaning data. (→ E15-24 plan)
2. **Environment routing is explicit and honest.** Keep the local/service binary as the *mode*, but the service URL names the environment (prod/staging/dev subdomains). Remove the inferred-source special case. The settings UI is rebuilt as selectable target cards with live health state, active-target hierarchy, and de-emphasized inert fields; the missing radio CSS is hotfixed first. Local dev pairs with staging by default, never prod. (→ E15-25 plan)
3. **The boundary's existing stability machinery becomes visible and actionable.** (Corrected rev 2: every recognition call — including sync drains via `SnapshotClientTransport` — already flows through `proxy_request()` with per-class timeouts and a `ui_read` breaker.) E15-26 therefore surfaces breaker state + async-debt counts in a `sync/health` envelope, adds the degraded-mode banner and operator retry/discard, and gives terminal rows steady-state retention. (→ E15-26 plan)
4. **Scan/cluster pipeline fails fast and reports progress.** Capability check at job intake (embedding runtime present?) rejects scans with an explicit reason instead of stuck jobs; jobs expose a progress envelope (items done/failed/total) the Workbench can poll; worker isolates per-tenant failures (rg-007 bounded stall detection). (→ E15-27 plan)
5. **Demo topology: OCI hosts both halves.** demo.altcontext.com (WP + ACX plugin, containerized on the existing A1 VM behind the existing Caddy) + api.altcontext.com (recognition). Revises E15-3's shared-hosting decision; users still self-host plugins against the central service. (→ E15-28 plan)

## Sovereignty model (clarified, not changed)

- **Plugin/WP is the system of record for curation intent** (persons, labels, dismissals, pins) — DDIA "system of record vs derived data."
- **Service is the system of record for derived recognition data** (embeddings, cluster topology, snapshots).
- Curation flows up through the outbox (idempotent, retried, conflict-surfacing); topology flows down through snapshots/deltas. Reads never require the network; writes queue. Offline is a *designed state with UI affordance*, not an error.

## Dependency order

```
E15-25 Slice 1 (radio CSS hotfix)  — immediate, unblocks operator today
E15-24 (tenant identity)           — before demo provisioning; stable demo tenant required
E15-27 (scan fail-fast + progress) — before demo; demo must not show stuck jobs
E15-26 (boundary resilience)       — parallel with E15-7; scoped to not overlap it
E15-25 (settings redesign)         — after E15-24 (tenant display) ; UI consumes health + identity
E15-28 (OCI demo provisioning)     — last; consumes all of the above + E15-3a round-trip gate
```

**Non-overlap with existing plans**: E15-7 owns local persistence path + fallback envelope honesty; E15-26 deliberately excludes those and owns timeout/CB/steady-state/replay-recovery. E15-22 owns Workbench avatar/progress rendering; E15-27 owns the backend progress/failure envelope it consumes. slr-2/slr-3 (deferred v0.4.1) sketched session circuit breakers for the Python service; E15-26 is the PHP-side boundary and does not depend on them.

## Principle traceability

> Citation convention used across the E15-24…E15-28 plans: short form `release-it.md §Circuit Breaker` refers to `literature/extracted/refactoring/distilled/release-it.md`. **`literature/` is gitignored and exists only in the root checkout** (`~/Development/context-alt-text-monorepo/literature/...`) — implementing agents in task worktrees must read it from there.

- **`designing-data-intensive-applications.md`**: §Partition Key Stability (S1), §Systems of Record vs Derived Data (sovereignty model), §Eventual Consistency + Idempotence and §Log-Based Derivation vs Dual Writes (outbox; one-writer identity), §Offline-Capable Replicas (local projections catch up by snapshot/delta), §Timespan of Consistency — Timeliness vs Integrity (stale local reads acceptable; lost curation never).
- **`release-it.md`**: §Use Timeouts (5.1), §Circuit Breaker (5.2), §Bulkheads (5.3, demo colocations), §Steady State (5.4, retention), §Fail Fast (5.5, scan intake + tenant provisioning), §Handshaking (5.6, health chips), §Test Harness (5.7, failure-mode doubles), §Configuration Files (14.2, per-env explicitness), §Zero-Downtime Deployment (18.4, identity migration shape), §Transparency (Ch 17, breaker visibility).
- **`latency-reduce-delay-in-software-systems.md`**: §Perceived vs Actual Latency (scan progress feedback), §Request Batching (per-batch progress writes), §Observability — queue-wait vs processing time (10.7, diagnoses the "91 stuck replays" class), §Optimistic Updates (11.3.1, already present in curation — keep), §Deferred Task Scheduling (10.3, bulk re-key off the request path).
- **`using-asyncio-in-python.md`**: §Executor Offloading (InsightFace CPU work), §Queue-Mediated Decoupling + §Back-Pressure via maxsize (per-tenant pipeline stages), §Gather with return_exceptions (tenant isolation), §Cancellation Propagation + structured terminal states (job lifecycle).
- **`refactoring-ui.md`**: §Think Outside the Box (selectable cards over radios), §Hierarchy is Everything + §Emphasize by De-emphasizing (inert credentials), §Don't Overlook Empty States (offline/unconfigured as designed states), §Don't Rely on Color Alone (status = color + icon + label; sr-004).
- **`refactoring-fowler-beck.md`**: §Extract Class (shared circuit-key derivation; refa-6 outbox surfaces), characterize-then-change test discipline used in every behavior-altering slice.
