# Demo Operability Defects — Initial Assessment

> **Metadata**
>
> - **Date**: 2026-09-21
> - **Author**: Claude Fable 5.1 (claude-fable-5-1)
> - **Status**: initial assessment, feeds [E25 / DEMOHEAL](../../epics/v0.5.0/demo-operability-and-mirror-self-healing-epic.md)
> - **Scope note**: [demo-operability-and-mirror-self-healing-scope.md](../../scopes/demo-operability-and-mirror-self-healing-scope.md)
> - **Surface**: `demo.altcontext.com/wp-admin` (plugin 0.0.25) ↔ `api.altcontext.com` (`acx-prod-api-1`)
> - **Evidence classes**: `[code]` read at `file:line` on `11fe4dea7` · `[live]` operator-observed DOM or `docker logs` · `[hyp]` unconfirmed mechanism

## Executive Summary

Five operator-visible symptoms on the demo resolve to ten defects in three families. None needs a newer plugin build to diagnose; the confirmed defects need code; the remaining mechanisms need evidence before choosing a fix.

1. **The UI lies about service state.** One panel has never worked (wrong upstream path), two surfaces discard the typed `unavailable` envelope the PHP layer already builds, and "Warming GPU" is shown while the backend reports no intent and no work.
2. **Derived state cannot heal.** The WP mirror and outbox have no notion of *which backend dataset they were derived from*. A backend wipe leaves orphaned clusters and permanently failed outbox rows; the reclaimer prefers Action Scheduler and falls back to daily WP-cron; old rows expose a reclamation problem, but do not prove the scheduler never ran. No last-success signal distinguishes these cases.
3. **The operator cannot see why.** Breaker trips are unlogged and unqueryable, no correlation id crosses SPA → WP → API, and API logs are ~70% success-path chatter.

Handoff discipline (DBG-12): symptoms and conditions are listed before mechanisms; every mechanism below is tagged `[code]`, `[live]` or `[hyp]`.

## Symptoms (as reported, 2026-09-21)

| # | Symptom | Condition |
| --- | --- | --- |
| S1 | "Warming GPU (first run only)…" persists; no descriptions arrive; chip `data-gpu-state="unknown"`, "GPU tier: not reported" | Review queue, plugin 0.0.25 |
| S2 | "Backend unavailable — retention status cannot be loaded"; Retry does nothing; service not named | Settings › Data & retention |
| S3 | "Could not reach the description service. Retrying in 15 s." | Settings › Description Service chip |
| S4 | Four failed "Cluster label update" outbox entries dated 7/8/2026 | Sync status, ~10 weeks old |
| S5 | Repeated/incorrect clusters; three identical "Unnamed person" cards for one `uploads/2026/07` image | Review queue |

Live log evidence (operator-run, 30 min window, filtered): one `GET /scene/gpu/status 200` from the WP container; zero `/scene/gpu/intent`, zero describe requests; `/retention/*` 404s; remainder is `GET / 404`, `/health`, scanner probes. All traffic arrives from the proxy address `172.18.0.3`.

## Findings

### F1 — Retention proxy calls a path the API never served `[code]` · severity high

`RetentionController` proxies to unprefixed `/retention/*` (`apps/prototype-wp-alt-context/src/api/class-retention-controller.php:188-390`). The API mounts the retention router under `/recognition` (`recognition/interface_adapters/http/routers/retention.py` `prefix="/retention"`, included by `recognition/interface_adapters/http/router.py:42`, mounted at `api/main.py:597`). Both sides date from commit `3dbc3f241`: the panel has never worked against a real API.

Masking test: `tests/Unit/RetentionControllerTest.php:92,419` asserts `assertStringContainsString('/retention/policy', $url)`, true with or without the prefix.

### F2 — SPA fabricates an envelope-free "unavailable" `[code]` · medium

`fetchRetentionStatus` returns `{available:false, policy:null, recent_audit_events:[]}` with no `unavailable` object when the endpoint key is absent (`js/admin/api/recognition/retentionApi.ts:120-128`), which forces `RetentionPage.tsx:112-124` into the generic dead-end panel (no service, no reason, no last-checked). `RetentionStatusResponse` does not type `unavailable` at all. Why the generic panel rendered on the demo is **unexplained** `[hyp]`. Ruled out `[code]`: the `retentionStatus` endpoint key is localized (`src/admin/class-admin.php:481`), and the PHP envelope is well-formed (`class-retention-controller.php:430-437`), so a 404 upstream should have produced the typed `upstream_4xx` panel. Remaining candidates: the WP REST call itself errored (then `status` is undefined and `readUnavailable` has nothing to parse), or a stale cached bundle. One browser network capture of `acx/v1/retention/status` settles it.

Adjacent debt `[code]`: envelope construction and reason mapping are duplicated verbatim between `RetentionController` (`:430-530`) and `GpuControlController` (`:174-315`) instead of living on the abstract proxy controller.

### F3 — GPU card discards the typed envelope `[code]` · medium

`GpuControlController::map_transport_failure` attaches `unavailable{reason,service,http_status,retry_after_seconds,checked_at}` (`src/api/class-gpu-control-controller.php:126-158`). `GpuControlCard.tsx:155-160` `errorCopy` ignores it and string-matches `'502'` in `error.message`. `circuit_open`, `api_key_missing`, `timeout` and `upstream_4xx` all read as "could not reach".

### F4 — "Warming" is unbounded and suppresses its own watchdog `[code]` + `[hyp]` · high

`useActivityStatus.ts:253-261` enters `WARMING` from `run.phase === WARMING` *or* a warming GPU state. `useDescribeRunProgress.ts:229` disables the stall indicator while `isWarming`. So a describe run parked in `WARMING` has no stall detection at all. Backend at the same moment: `intent_status: none`, `load.has_work: false`, `state: stopped` `[live]`. Mechanism by which the run never reaches the API (breaker latched, WP-side queue never drained, or client never posts) is **unconfirmed** `[hyp]`; F5 is the instrument that will confirm it.

### F5 — No way to ask "can WordPress reach the API, and what did it last try?" `[code]` · high

`record_proxy_failure` trips the breaker with `set_transient` and no log line, no state-change record, no read endpoint (`class-abstract-recognition-proxy-controller.php:796-812`). Outbound requests carry no correlation id (`:205-222`), so an SPA error cannot be joined to a WP attempt or an API access line. Threshold 2 / open 60 s are filter-only. Diagnosing S1–S3 required production shell access, which is the defect.

### F6 — The outbox reclaimer has no successful-run liveness signal `[code]` + `[live]` · high

`OutboxMaintenanceService::maybe_schedule_purge` prefers an Action Scheduler single action one hour ahead and falls back to daily WP-cron. `OutboxDrain::purge_terminal_rows_for_tenants` also invokes the service from the drain path. `purge_terminal_rows` returns an aggregate array on success or `false` on failure; row eligibility, retries, transactions and backlog can all explain old rows. Seven-day retention does **not** imply every failed row is deleted at seven days. Rows dated 2026-07-08 remain `[live]`; absent last-success evidence, scheduler failure, purge failure and ineligible rows remain competing hypotheses `[hyp]`. Instrument successful completion per tenant and backlog separately; do not stamp success at scheduling or invocation.

### F7 — No dataset generation: a backend reset strands the mirror `[code]` · high

The inspected mirror/outbox paths do not carry a dataset incarnation. This is a bounded code observation, not an exhaustive claim about every identifier in both apps. Consequences:

- `discard_orphaned_failed_row` requires an entity-gone error code **and** the local entity to be absent (`class-outbox-maintenance-service.php:781-828`). After a backend wipe the local mirror row still exists, so the orphan is never discarded: deadlock.
- `SnapshotProjector::record_backend_roster_regression_aggregate` (`class-snapshot-projector.php:631-688`) records a roster shrink as a *conflict* instead of recognising a new dataset and rebuilding.
- `SyncStatusController::reset_mirror` (`class-sync-status-controller.php:159-177`) is the only recovery and is manual; `run_sync_action` can return `synced:false, reason:'sync_unavailable'` after the wipe has already happened (`:179-221`).

Operator constraint: local and demo DBs may be wiped by hand, but production needs a mechanism.

### F8 — Labelled and unlabelled clusters of one person coexist `[live]` · medium

Cluster `46fbdd3f` is unlabelled with suggestion "Justin Trudeau" @0.773 while `d43f5ede` already carries that label. A confirmed label does not feed a merge suggestion. Root cause inside the clustering/suggestion path not yet traced `[hyp]`.

### F9 — Representatives serialize `bbox: null`, `thumb_url: null` `[live]` · medium

`debug_metrics.bbox_area` is populated on the same rows, which suggests earlier geometry existed but does not establish that the representative serializer received or dropped a usable box. Persistence, joins, projection and serialization remain candidate loss points. Produces mismatched/blank thumbnails in S5. Serializer location not yet traced `[hyp]`.

### F10 — API logs bury the one line that matters `[code]` + `[live]` · low

`session_dependency_timing` is emitted at INFO on every request (`recognition/interface_adapters/http/deps/session.py:117-118`), ≈70% of volume; `/health` access lines every 30 s; scanner probes (`/.env`, `phpinfo`) reach the app; access lines carry no correlation id and the real client IP is lost behind the proxy (no forwarded-header trust configured).

## Code-Verified Critique of Earlier Hypotheses

| Earlier claim | Verdict | Evidence |
| --- | --- | --- |
| WordPress cannot egress to the API | **Refuted** | `GET /scene/gpu/status 200` from the WP container `[live]` |
| Retention policy endpoint is healthy | **Misleading** | probe used `/recognition/retention/policy`, the path the plugin does *not* call |
| A 404 storm from retention trips the breaker and takes the GPU chip down | **Refuted** | only `>= 500` and transport errors count (`:268`); retention is `ui_read`, GPU is `post_scan_read` |
| A newer plugin build would fix S1–S5 | **Refuted** | every finding is present at `11fe4dea7` |

## Canon Validation Against the Distilled Corpus

Each cited rule was re-read at its `Src` anchor under `~/Development/heuristics-canon-research/distilled/` (read-only). Result: the design direction holds; four citations needed tightening.

| Rule / card | Distilled anchor read | Verdict | What the source adds or corrects |
| --- | --- | --- | --- |
| RES-07 steady-state reclaimer | `release-it` §5.4 | confirmed | "Purging must be *application logic*, not DBA scripts" and "runs indefinitely without intervention": the code already supplies application-level purging; missing completion evidence and old eligible backlog would prevent demonstrating steady state. Lack of telemetry alone does not prove the purge never ran. §5.5's print-renderer case is the same shape: the one unchecked resource was "one guy deleting files". |
| RES-15 circuit breaker | `release-it` §5.2 | confirmed, **extends scope** | Source requires: log every state change, expose current state, **give operations manual trip and reset**. F5 has none of the three. The distinct-error-when-open clause is already met (`circuit_open`). |
| Fail Fast (no lexicon row cited before) | `release-it` §5.5 | **new input** | "Report system failure differently from application failure." A confirmed route-level 404 for a static configured endpoint is a contract defect; an entity 404 is not; `upstream_4xx` copy "Check the API URL and key" misdirects the operator. Map static route-level 404/405 → `contract_mismatch`; preserve entity-not-found and authorization errors. |
| OBS-03 / OBS-04 / OBS-05 | `release-it` §17.4, §17.6 | confirmed | "Levels are for operations"; "no DEBUG in production"; per integration point expose breaker state, timeouts, counts by error class, **actual remote IP**, time of last request. Directly scopes F5 and F10. |
| OBS-08 silence is not success | lexicon says `observability-engineering ch-8` | **anchor mismatch** | Distilled ch-8 is the core analysis loop; the freshness mechanism (tagged synthetic events, SLO on arrival) is in **ch-18**. Cite ch-18 for the mechanism. Canon repo is out of bounds here; report upstream, do not edit. |
| RES-10 fencing tokens | `designing-data-intensive-applications` ch-8 | **analogy, not trigger match** | The rule's trigger is locks/leases. F7 is not a lease. The related mechanism is **Generation Clock** (`patterns-of-distributed-systems` ch-11: stamp every message, receiver rejects lower generation), which that distillation itself marks as a duplicate of RES-10. Cite both and say so. Enforcement must be at the resource (the API), never client-side only. |
| FLOW-06 / IDX-10 / DATA-14 | DDIA ch-11, ch-12 | confirmed | "Repair a wrong view by reprocessing into a fresh version and cutting over rather than hand-patching rows." The mirror is a derived store; backend is system of record. Timeliness-vs-integrity (ch-12): a stale mirror is a timeliness fault that heals by waiting; a mirror from a *dead dataset* is an integrity fault, "permanent until explicitly repaired". That distinction is the design test for F7. |
| DATA-13 / API-02 / RES-01 | DDIA ch-8, ch-12 | confirmed | "A timeout tells you nothing about whether the call executed." Outbox replay after rebuild needs the end-to-end id already carried by outbox rows; verify before relying on it. |
| DDIA exemption | DDIA applicability | checked, **does not exempt** | "Single-node, single-object work is exempt." Mirror + backend are two stores across a network with independent lifecycles; the rules apply. Do not add consensus machinery: one non-reused dataset incarnation checked for equality is sufficient; a monotonic counter is safe only if its authority survives resets/restores. Neither source proves the original in-dataset counter safe. |
| Optimistic UI (F4) | `latency-reduce-delay` §11.3–11.4 | **new input** | Optimistic/value-predicted UI is legitimate only with a rollback path and correction when the real value lands. "Warming" has neither. Hedging/speculation caveat does not apply (no speculation of work, only of state). |
| CARD-03, CARD-07, CARD-09; Principles 10, 11, 12, 13, 16, 19 | `reasoning/`, `PRINCIPLES.md` | confirmed | Unknown is a designed state (F2–F4); fail loudly, succeed quietly (F5, F6, F10); step size bounded by feedback (slice order). |
| GRPH-18 / GRPH-22 / HAI-02 | `lexicons/graph-theory.md`, `interaction-ux.md` | confirmed, not re-read at source | F8: a human label is a correction that must reach the graph; merge must be a verified pairwise suggestion, never transitive closure. Source-level re-read deferred to the DEMOHEAL-3 plan. |

## Recommendations (priority order)

| # | Recommendation | Traces | Priority |
| --- | --- | --- | --- |
| R1 | Prefix the nine retention proxy paths; replace substring URL assertions with exact-URL assertions; add a route-parity test that fails when a proxied path is absent from the API's OpenAPI document | F1 · rg-005, rg-015 | P0 |
| R2 | One `unavailable` contract end to end: type it on `RetentionStatusResponse`, remove the fabricated fallback, render it in `GpuControlCard`, map static route-level 404/405 → `contract_mismatch`; preserve entity-not-found and authorization errors | F2, F3 · Release It §5.5, RLSE-04, Principle 11 | P0 |
| R3 | Connectivity self-test + breaker state/reset + last outbound attempt per route family, with a correlation id minted in WP and echoed by the API | F5 · RES-15, OBS-03, OBS-05 | P0 |
| R4 | Correct `WARMING` from fresh nested GPU evidence; add a finite UI observation deadline and restore the stall watchdog | F4 · INT-08, CARD-09, latency §11.4 | P0 |
| R5 | Reclaimer liveness: persist last purge run; surface a freshness breach; opportunistic run on sync when overdue | F6 · RES-07, OBS-08 (ch-18) | P0 |
| R6 | Dataset generation token: API mints on wipe/import, returns on every sync response, rejects writes not matching the current incarnation; mirror stages a complete snapshot and cuts over atomically, preserving visible dead-generation dispositions | F7 · RES-10 + Generation Clock, FLOW-06, IDX-10 | P1 |
| R7 | Label-aware merge suggestion; representative serializer carries bbox/thumb | F8, F9 · HAI-02, GRPH-22 | P2 |
| R8 | Demote per-request timing to DEBUG, drop `/health` access lines, trust forwarded headers only from explicitly allowlisted proxies, correlation id on access lines, block scanner paths at the proxy | F10 · OBS-03, OBS-04, Principle 16 | P2 |

## Deferred / Rejected

- **Manual DB wipe as the fix for S4/S5** — accepted as a one-off for demo and local; rejected as the mechanism (operator constraint; RES-07 "no routine human intervention").
- **Relaxing orphan-discard to ignore local entity presence** — rejected: it hand-patches rows (FLOW-06) and would discard legitimate retries during a transient backend 404.
- **Replacing WP-cron with a system cron in the demo image** — deferred: fixes one host, not the class. R5 makes any scheduler's death visible first.
- **Re-clustering algorithm changes** — out of scope until F8 is traced; GRPH-18 forbids closing the duplicate by lowering a threshold.

## Open Questions (need one production read each; operator-run)

1. WP-cron: `wp cron event list` inside `acx-demo-wordpress-1` — is `PURGE_HOOK` scheduled, and when did it last run?
2. Breaker: are any `acx_*circuit*` transients set for `post_scan_read`?
3. Browser: status code and body of `acx/v1/retention/status` on the demo (DevTools network tab; no shell needed).

R3 and R5 make future breaker and reclaimer diagnosis visible. The browser capture remains a separate evidence source for the unexplained live rendering; connection checks cannot reconstruct an old browser response.

## Next Step

Review [E25](../../epics/v0.5.0/demo-operability-and-mirror-self-healing-epic.md) and [DEMOHEAL-1](../../tasks/v0.5.0/DEMOHEAL-1-truthful-service-state-and-reclaimer-liveness-task-plan.md) via `/wb-review-plan`.

## Review grounding and applicability

Coordinator recheck: 2026-09-21, production baseline `11fe4dea7`. Codebase graph search/snippets and coverage checks grounded the GPU response, warming hook, proxy and purge paths; no recorded coverage gap on those anchors is a best-effort signal only. Semantic prior art returned VLM-2B finding 2148 (breaker recovery), VLM-6 finding 9234 (warmup trips breaker), and E15-35 decision 2514 (outbox compare-and-swap). Retrieval suggests checks; it does not adjudicate correctness (GRPH-36).

- *Release It!* §5.1–5.5 supports finite timeouts, one half-open probe, transition visibility, and a drain that keeps up with accumulation. It does not establish which scheduler failed here.
- DDIA ch-8/11/12 and *Patterns of Distributed Systems* ch-11 support stale-authority rejection and rebuilding derived stores. Generation Clock addresses leadership terms: dataset identity is an analogy, and equality against a non-reused incarnation is the chosen contract. A counter restored with the wiped data is not a fence.
- *Latency* §11.4 value prediction directly supports correcting a predicted display. §11.3 optimistic writes is an analogy; this task does not add CRDTs or a shadow write queue. CARD-09 supplies the finite waiting requirement.
- CARD-03/07 and Principles 11/13 require designed unknown states and evidence before commitment: populated `bbox_area` and old failed rows are insufficient to claim a specific cause.
- GRPH-01/09/31/32/33 distinguish dependency order, shared-file interference, scheduling and explicit lane contracts. See the [dependency packet](../../scopes/demoheal-parallel-delivery.md). F8/F9 remain trace-first work; no clustering algorithm change is justified by this review.

Mutable review findings and verdicts are in MCP under `DEMOHEAL-1`; this assessment is not a duplicate findings ledger.

Existing API correlation is prior art: `recognition/interface_adapters/http/middleware/correlation.py:CorrelationIdMiddleware` already binds `X-Request-ID`, and `api/logging_config.py:configure_logging` installs its filter. F5 is missing **cross-boundary WP propagation and operator visibility**, not absence of all API correlation machinery. Extend that owner when adopting `X-ACX-Request-Id`; include access-record/exception tests.
