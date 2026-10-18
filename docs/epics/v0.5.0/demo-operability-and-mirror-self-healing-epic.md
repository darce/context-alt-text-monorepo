# E25. Truthful Service State and a Self-Healing Mirror (v0.5.0)

> **Metadata**
>
> - **Date**: 2026-09-21
> - **Author**: Claude Fable 5.1 (claude-fable-5-1)
> - **Epic Short ID**: DEMOHEAL
> - **Target Version**: v0.5.0
> - **Status**: draft for planning review
> - **Grounding**: [assessment](../../assessments/current/demo-operability-defects-assessment-2026-09-21.md) · [scope](../../scopes/demo-operability-and-mirror-self-healing-scope.md) · canon validated against `~/Development/heuristics-canon-research/distilled/` (read-only)

## Objective

When a dependency is down, a backend dataset is replaced, or a background job dies, the WordPress plugin says so truthfully (which service, why, since when, what next) and recovers without a shell or a manual DB wipe. The API rejects writes derived from a dataset that no longer exists, and its logs stay quiet enough that the one line that matters is findable.

## Problem Statement

On `demo.altcontext.com` (plugin 0.0.25) five symptoms persisted across releases: a GPU that "warms" forever, a retention panel that says only "Backend unavailable", the Description Service state within the GPU card that says only "could not reach", four failed outbox rows ten weeks past a seven-day retention, and orphaned or duplicated cluster cards. The assessment maps these to ten findings, preserving unconfirmed mechanisms in three families: the UI misreports service state; derived state (mirror + outbox) has no way to notice that its source dataset was replaced; and neither the operator nor an engineer can see why without production shell access.

A one-off wipe and path correction may clear some symptoms; they neither establish all root causes nor supply production recovery.

## UX Vision

Every degraded surface answers four questions in one place: *which service · why · last checked · what happens next*. The vocabulary is identical on every page. "Unknown" is a designed state with its own copy, never a spinner that outlives its evidence. Settings carries one **Connection check** an operator can run and paste into a bug report. After a backend reset the operator sees one notice — "Backend dataset was replaced on <date>. Local mirror rebuilt. 3 queued changes could not be applied" — and nothing else to do.

## Constraints

- **Greenfield**: no migrations or shims; schema edits go directly into `001_identity_schema.py` and the mirror table create statements.
- **Enforce at the resource**: dataset-generation checks are enforced by the API. A client-side-only check is not a guard (DDIA ch-8).
- **No invented envelope fields** (rg-015): every `unavailable` field comes from the proxy attempt or the upstream payload.
- **No relaxed gates** (sr-001): vacuous URL assertions are replaced, not deleted.
- **Status vocabularies are centralized** (sr-007): one `as const` / PHP enum per vocabulary; no new string literals at call sites.
- **Production reads are operator-run**; isolated remote review/build/test sandboxes are permitted; production is not touched by this planning pass. E23 owns GPU lifecycle units; this epic does not edit them.
- **Step size bounded by feedback** (Principle 19): independent plugin fixes can ship first because they deploy from a laptop in minutes and produce the evidence the later phases need.

## Terminology

- **Unavailable envelope**: `{reason, service, http_status, retry_after_seconds, checked_at}` as built by the PHP proxy layer.
- **Route family**: the proxy's breaker partition (`ui_read`, `post_scan_read`, …).
- **Mirror**: WP tables `acx_clusters`, `acx_identity_members`, `acx_sync_outbox`; a derived store. The API database is the system of record.
- **Dataset generation**: an opaque, non-reused UUID incarnation minted by the API whenever the tenant's recognition dataset is destroyed or replaced (wipe, purge-all, import, reseed).
- **Reclaimer**: `OutboxMaintenanceService::purge_terminal_rows` and its scheduler.
- **Freshness breach**: a periodic job's last successful run is older than its declared interval plus grace.

## Current State

- Works: typed envelope construction in PHP; per-family breaker that ignores 4xx; orphan discard, retry backoff and dead-lettering in the outbox; manual mirror reset.
- Broken: retention proxy path; two SPA surfaces that drop or fabricate the envelope; unbounded `WARMING`; silent breaker; scheduler-driven reclaimer with no liveness; no dataset identity anywhere; label does not feed merge suggestion; representative bbox/thumb dropped; success-path log chatter.
- Misleading: `RetentionControllerTest` substring URL assertions pass for a path the API does not serve; a manual probe of `/recognition/retention/policy` returned 200 and was read as "retention is healthy".

## Applied Concepts from Sources

Rule text was re-read at each `Src` anchor in the distilled corpus. Verdict column records where the source tightened or corrected the citation.

| Source | Concept | Epic application | Verdict |
| --- | --- | --- | --- |
| `distilled/engineering/release-it.md` §5.4 (RES-07) | Steady State: purge is application logic; runs without human intervention | Reclaimer records per-tenant last successful batch and is driven opportunistically by sync, not only by WP-cron | confirmed |
| `release-it.md` §5.2 (RES-15) | Breaker: log every state change, expose state, manual trip/reset | Connection check exposes per-family breaker state and a reset; transitions are logged | reset and visibility adopted; manual trip explicitly deferred |
| `release-it.md` §5.5 | Fail Fast: report system failure differently from application failure | Static router-level 404/405 maps to `contract_mismatch`; typed entity-not-found and authentication errors retain their meaning | new input |
| `release-it.md` §17.4, §17.6 (OBS-03, OBS-04, OBS-05) | Levels are for operations; correlation id on request-scoped application and access lines; per integration point expose breaker state, counts by error class, actual remote IP, time of last request | Correlation id minted in WP, echoed by API; timing lines to DEBUG; forwarded headers trusted only from configured proxy addresses | confirmed |
| `distilled/engineering/observability-engineering.md` ch-18 (OBS-08) | End-to-end freshness monitored as an SLO on arrival | Freshness breach for the reclaimer and for sync pulls | lexicon `Src` says ch-8; mechanism is in ch-18 — cite ch-18, report upstream |
| `distilled/engineering/designing-data-intensive-applications.md` ch-8 (RES-10) + `patterns-of-distributed-systems.md` ch-11 Generation Clock | Stale authority is rejected at the resource; dataset identity uses exact equality | Dataset generation on every sync response and every mirror-originated write; API rejects stale | RES-10 trigger is leases; applied by mechanism analogy, Generation Clock also concerns leadership: dataset replacement is a mechanism analogy, not an exact trigger match |
| DDIA ch-11/12 (FLOW-06, DATA-14), `lexicons/ml-systems.md` IDX-10 | Heal a derived store by rebuilding from the source and cutting over, never by hand-patching rows; timeliness vs integrity | Generation change ⇒ atomic mirror rebuild; orphan-discard rule is not relaxed | confirmed for derived-store rebuilds; no consensus system is introduced |
| DDIA ch-8, ch-12 (RES-01, DATA-13, API-02) | Timeout means unknown, not failed; end-to-end request id | Outbox rows keep their idempotency key across rebuild; dead-generation rows are discarded visibly, not retried | confirmed |
| `distilled/engineering/latency-reduce-delay-in-software-systems.md` §11.3–11.4 | Optimistic state needs a rollback path and correction when truth lands | `WARMING` corrected from fresh nested GPU state and bounded by a finite UI deadline; current API exposes no warm-up deadline | new input |
| `reasoning/` CARD-03, CARD-07, CARD-09; `PRINCIPLES.md` 10, 11, 12, 13, 16, 19 | Designed unknown; fail loudly, succeed quietly; feedback-bounded waiting; evidence precedes commitment | UX Vision; log hygiene; phase order | confirmed |
| `lexicons/interaction-ux.md` HAI-02, `lexicons/graph-theory.md` GRPH-18, GRPH-22 | Correction must reach the source; never trust transitive closure; verify bridges pairwise | Label-aware merge *suggestion*, human-confirmed; no threshold change | confirmed at lexicon level; source re-read owed by the Phase 3 plan |

## Git Workflow Assessment

One task plan per phase, each on `feature/demoheal-<n>`. Phase 1 includes plugin changes plus API route-manifest tooling and request-id middleware. Plugin acceptance uses `make deploy-demo`; full correlation acceptance also requires the API release and received-request logs. Phase 2 crosses PHP/Python: implement both sides against the frozen contract concurrently, then deploy with writes quiesced until both enforce it; no missing-token compatibility bypass. One harmonizing review before `main` per task.

## Target Architecture

```text
SPA -> WP proxy -> API (validated X-ACX-Request-Id)
        |           |
        |           +-- dataset_generation UUID, scoped by authenticated tenant
        +-- bounded diagnostic ring, explicit sent/not_sent
        +-- unavailable envelope -> one notice

mirror incarnation M; complete snapshot incarnation B
M != B -> stage complete snapshot B -> atomic local cutover
write incarnation != current B -> 409 dataset_replaced before mutation
```

### Design Decisions

| Decision | Rationale |
| --- | --- |
| One envelope, one renderer component | Two surfaces already diverged; a shared component makes a third impossible |
| Static route-level 404/405 ⇒ `contract_mismatch` | Release It §5.5; operator action differs (upgrade vs fix credentials) |
| Route-parity test reads a tracked route manifest exported from the FastAPI app | Catches F1's class at CI time without a live API; exact-URL assertions alone would only fix the nine known paths. No OpenAPI artifact is tracked today, so the export plus a staleness test is part of DEMOHEAL-1 slice 1 |
| Attempt ledger is a bounded ring per family (WP option, N=20) | OBS-05 visibility without an unbounded table (RES-07 applies to the fix too) |
| Dataset incarnation is a non-reused UUID, checked for exact equality | Dataset identity needs equality, not leader ordering. Reject missing, malformed and any non-current token; reset/restore tooling must never revive a previously issued token |
| Generation enforced by the API on writes | Client-only checks do not guard (DDIA ch-8) |
| Rebuild, never patch | FLOW-06; keeps orphan-discard strict |
| Dead-generation outbox rows end in a visible terminal state `discarded: dataset_replaced` | RLSE-05: the operator's labels were lost; say so |
| Reclaimer driven by sync when overdue, WP-cron retained | Removes single scheduler dependency without adopting a new scheduler |
| Merge is suggested, never automatic | GRPH-18; HAI-02 |

### Data Model and recovery contract

- API is the system of record. `dataset_generation` is a non-reused UUID per authenticated tenant dataset. It is not an ordered fencing counter. Wipe/purge-all/replacement import lock the tenant's authority row and rotate the UUID in the same transaction as replacement; every mirror-originated write takes the same lock and checks equality **before** mutation and before replaying an idempotency result. Stale, missing, malformed and fabricated tokens never mutate the new dataset.
- Full database restore/reseed is a separate administrative boundary: rotate all restored incarnations before accepting requests. Rotation is mandatory in the restore/startup procedure and its drill; restoring the old authority row and serving it unchanged is forbidden. DEMOHEAL-2 must identify every destructive entrypoint and the restore procedure before implementation approval.
- Sync pages carry one incarnation and a snapshot/cursor consistency token. The API must provide a stable snapshot or reject/restart pagination when it changes. No client can assemble mixed-incarnation or mixed-version pages. A 409 never advances the mirror cursor.
- Mirror consistency is eventual within an incarnation. Build a staging projection, verify page completion and incarnation, then atomically switch the active local projection and its generation/cursor. A crash, timeout or generation change retains the prior mirror, marked stale; it never exposes a partially emptied live mirror. `reset_mirror` followed by a possibly unavailable sync is not an implementation of atomic rebuild.
- Freeze old-generation dispatch during rebuild. Keep its outbox rows as visible terminal `dataset_replaced` dispositions with original operation ids and counts; do not silently replay labels into the new dataset. Same-generation retries preserve idempotency keys. Idempotency scope includes authenticated tenant, incarnation and operation id. New writes require the new incarnation after cutover; a racing write either commits in the old transaction before replacement or is rejected.
- Per-tenant reclaimer state distinguishes last attempt, last successful batch, outcome and remaining backlog. Diagnostic rings and breaker history have fixed bounds and redaction. They are best-effort observability, never the correctness authority.

Required DEMOHEAL-2 tests: old/equal/fabricated/missing token; reset racing write; restore to an earlier backup; repeated replacement; page N failing or changing incarnation; crash before/after local cutover; duplicate replay; tenant isolation; visible discard accounting. API/plugin rollout is coordinated with writes quiesced until both enforce the new contract. No temporary acceptance of missing tokens. The later task plan must ground transaction and staging primitives before it is ready.

## Phased Delivery

### Phase 1: Truthful service state and reclaimer liveness -- NOT STARTED

> **Status**: not-started
> **Task plans**: [DEMOHEAL-1](../../tasks/v0.5.0/DEMOHEAL-1-truthful-service-state-and-reclaimer-liveness-task-plan.md)

**Goal**: Every degraded surface tells the truth, and the operator can diagnose connectivity and a dead reclaimer without a shell. Includes plugin changes, API manifest tooling and request-id logging middleware.

Deliverables:

- Retention proxy paths corrected; exact-URL assertions; route-parity test against an exported API route manifest
- Shared unavailable-notice component used by retention and GPU card; fabricated fallback removed; `contract_mismatch` mapping
- Connection check: per-family breaker state, reset, last attempts, correlation id
- `WARMING` bounded by backend truth; stall watchdog restored
- Reclaimer last-run recorded, freshness breach surfaced, opportunistic purge on sync

Exit criteria:

- Retention policy loads on the demo
- With the API stopped, retention and GPU card show identical service/reason/last-checked copy
- Connection check plus reclaimer status answer current breaker/reclaimer questions; the browser capture separately closes the historical generic-panel hypothesis
- A purge last-run forced 8 days back produces a visible breach and the next sync purges

### Phase 2: Dataset generation and mirror self-healing -- NOT STARTED

> **Status**: not-started
> **Task plans**: not yet scoped (DEMOHEAL-2)

**Goal**: A replaced backend dataset is detected and healed automatically; stale writes are rejected at the API.

Deliverables:

- `dataset_generation` UUID in the identity schema; rotated atomically by wipe, purge-all and replacement import, and rotated before traffic after restore/reseed
- Incarnation on every sync/snapshot page; required on mirror-originated writes; exact mismatch returns `409 dataset_replaced` before mutation
- Mirror rebuild on generation change; dead-generation outbox rows terminal and visible
- Roster-regression conflict path narrowed to same-generation regressions
- Contract docs: `cluster-snapshot-api.md`, `curation-sync-api.md`, `conflict-resolution-sync-contract.md`

Exit criteria:

- Drill (RES-16): wipe backend with populated mirror and three queued label writes ⇒ zero orphan cards, three visible discards, zero manual steps
- A write replayed with the old generation is rejected by the API with the plugin offline-patched to skip its own check

### Phase 3: Cluster quality at the boundary -- NOT STARTED

> **Status**: not-started
> **Task plans**: not yet scoped (DEMOHEAL-3)

**Goal**: A confirmed label produces a merge suggestion for look-alike unlabelled clusters, and representatives always carry a usable crop.

Deliverables:

- Root-cause trace of the labelled/unlabelled duplicate and of the null bbox/thumb serializer (observation before mechanism, DBG-02)
- Label-aware merge suggestion with pairwise verification; human-confirmed
- Serializer contract fix with schema parity test (rg-005)

Exit criteria:

- Labelling one of two same-person clusters surfaces a merge suggestion for the other
- No representative in a snapshot response has a null bbox when the detector recorded one

### Phase 4: API log hygiene -- NOT STARTED

> **Status**: not-started
> **Task plans**: not yet scoped (DEMOHEAL-4; may ride with Phase 2's API lane)

**Goal**: Success is quiet; request-scoped lines are joinable to a received request. Background events have their own operation identifiers.

Deliverables:

- Per-request dependency timing to DEBUG; `/health` access lines suppressed
- Forwarded-header trust restricted to the actual proxy address/network; reject spoofed client headers; correlation id on access lines
- Known scanner paths dropped at the proxy

Exit criteria:

- 30 idle minutes of `docker logs acx-prod-api-1` is under 50 lines
- One request id joins WP and API records for a request actually received by the API; a local rejection is explicitly `not_sent` and has no fabricated API record

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| Two operator-run production reads (scheduler event list, breaker transients) and one browser capture of `acx/v1/retention/status` | Operator | Not started | Confirms Phase 1 hypotheses; does not block authoring |
| One-off demo + local DB wipe | Operator | Not started | Optional cleanup only; not required for route, envelope, warming or reclaimer tests |
| E23 / GPUOPS lifecycle units on `acx-backend` | E23 | In progress | Phase 1 reads existing nested GPU status fields; no dependency on a future lifecycle timeout field |
| Reverse-proxy config under `infra/oci/` | Infra role | Not started | Phase 4 trusted-proxy allowlist and scanner drop |
| Canon `OBS-08` `Src` anchor correction (ch-8 → ch-18) | Canon repo owner | Not started | Nothing; hygiene |

## Code Anchors

| Layer | File | Note |
| --- | --- | --- |
| PHP proxy | `apps/prototype-wp-alt-context/src/api/class-retention-controller.php` | Nine unprefixed upstream paths |
| PHP proxy | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | URL build, breaker trip without log, header construction |
| PHP proxy | `apps/prototype-wp-alt-context/src/api/class-gpu-control-controller.php` | Reference envelope construction and reason mapping |
| PHP sync | `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-maintenance-service.php` | Reclaimer, orphan discard, WP-cron schedule |
| PHP sync | `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Roster regression recorded as conflict |
| PHP sync | `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | Manual mirror reset |
| SPA | `apps/prototype-wp-alt-context/js/admin/utils/serviceUnavailable.ts` | Envelope parser and copy; single vocabulary |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx`, `js/admin/api/recognition/retentionApi.ts` | Generic panel; fabricated fallback |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx` | `errorCopy` discards envelope |
| SPA | `apps/prototype-wp-alt-context/js/admin/hooks/useActivityStatus.ts`, `useDescribeRunProgress.ts` | `WARMING` derivation; watchdog suppression |
| API | `apps/prototype-description-service/api/main.py`, `recognition/interface_adapters/http/routers/retention.py` | Router mount prefix |
| API | `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | INFO timing line per request |
| Contracts | `docs/workbay/contracts/cluster-snapshot-api.md`, `curation-sync-api.md`, `conflict-resolution-sync-contract.md` | Generation field and `dataset_replaced` |

---

# Consolidated Checklist

## Phase 1: Truthful service state and reclaimer liveness -- NOT STARTED

- [ ] Retention paths, exact-URL assertions, route-parity test
- [ ] Shared unavailable notice; fabricated fallback removed; `contract_mismatch` mapping
- [ ] Connection check with breaker state/reset, attempt ring, correlation id
- [ ] `WARMING` bound and watchdog
- [ ] Reclaimer liveness and opportunistic purge
- [ ] Demo verification via `make deploy-demo`

## Phase 2: Dataset generation and mirror self-healing -- NOT STARTED

- [ ] Task plan authored and reviewed
- [ ] API generation mint + enforcement
- [ ] Plugin detection, rebuild, visible discard
- [ ] Contracts updated; wipe drill recorded

## Phase 3: Cluster quality at the boundary -- NOT STARTED

- [ ] Root-cause traces recorded
- [ ] Task plan authored and reviewed
- [ ] Merge suggestion; serializer parity

## Phase 4: API log hygiene -- NOT STARTED

- [ ] Levels, health suppression, forwarded headers, correlation id, scanner drop

## Deferred (Post-v0.5.0)

- Replace WP-cron with a real scheduler for all plugin periodic work
- Metrics/trace export; SLO alerting on freshness breaches
- Multi-dataset tenants (generation per dataset rather than per tenant)
- Re-clustering objective changes (GRPH-19/22 partition-plus-verification) — separate epic if Phase 3 traces point there

## Parallel execution policy

Phase numbers group outcomes, not a four-task chain. DEMOHEAL-1, DEMOHEAL-2 contract/inventory work, DEMOHEAL-3 root-cause traces and DEMOHEAL-4 log-noise work can proceed concurrently. Phase 4 consumes Phase 1 request-id behavior only for its final correlation proof; no other blanket phase edge is justified. API `main.py` edits have one integrator. See [the dependency packet](../../scopes/demoheal-parallel-delivery.md) for the task and defect DAGs, lane output schema and ownership constraints.
