# Scope: Demo operability — truthful service state and a self-healing mirror

> **Date:** 2026-09-21
> **Status:** scoped after code + live-log assessment
> **Surface:** WP admin SPA (review queue, Settings › Description Service, Settings › Data & retention, sync status) ↔ plugin proxy layer ↔ description-service API
> **Assessment:** [demo-operability-defects-assessment-2026-09-21.md](../assessments/current/demo-operability-defects-assessment-2026-09-21.md)
> **Epic:** [E25 / DEMOHEAL](../epics/v0.5.0/demo-operability-and-mirror-self-healing-epic.md)
> **Scope skill note:** F1–F7 have code anchors; F8/F9 still require root-cause traces, so the question-first intake is skipped. Design choices are grounded in code and the canon; hypotheses remain explicit and the later phases require their own plans.

## Intake boundary

The scoped outcome is: **when a dependency is down, a dataset is replaced, or a background job dies, the plugin must say so truthfully, name the service and the reason, and recover without a shell.**

## MVP scope

1. Retention panel works against the real API, and a route-parity test makes the class of bug impossible to reintroduce silently.
2. Every "unavailable" surface renders the one typed envelope: service, reason, last checked, retry-in. No surface fabricates or discards it.
3. An operator can run a connectivity self-test from Settings and see, per route family: breaker state, last outbound attempt, last result, correlation id. Breaker can be reset.
4. "Warming GPU" is bounded by backend truth and cannot outlive its evidence.
5. The outbox reclaimer's last run is visible; an overdue reclaimer is an alert, and sync runs it opportunistically.
6. A backend dataset replacement is detected by the plugin on the next sync and the mirror rebuilds itself; writes from the dead dataset are rejected by the API, not merely skipped by the client.

## Assumptions

- Greenfield: no migrations, no compatibility shims; the non-reused dataset-incarnation field goes straight into `001_identity_schema.py` and the mirror tables' create statements.
- The backend is the system of record for clusters and identities; the WP mirror is derived. Operator labels queued in the outbox are the only WP-originated state.
- Demo and local DBs may be wiped once by hand before slice 1 lands; that is cleanup, not the mechanism.
- Production reads stay operator-run; isolated remote build/test/review sandboxes are permitted. This planning pass neither deploys nor wipes production.

## Success criteria

- Retention panel loads policy on the demo; with the API stopped it shows "Recognition service unavailable because … · Last checked … · Retry in … s".
- With the API stopped, the GPU card and the retention panel show the same reason vocabulary; with a wrong API key both say so.
- Self-test distinguishes: not configured · key missing · DNS/connect failure · timeout · 4xx · 5xx · contract mismatch · breaker open, each with a WP request id. Only requests actually received by the API can have a matching API log; local rejection explicitly reports `not_sent`.
- A describe run cannot display "Warming" for longer than the documented finite UI observation deadline (the current backend has no warm-up deadline field) without transitioning to a named failed/stalled state with Retry.
- Setting the purge last-run timestamp 8 days back produces a visible freshness breach, and the next sync attempts a bounded purge; only committed success advances last-success, and remaining backlog stays visible.
- Drill: wipe the backend dataset with a populated mirror and three queued label writes → next sync rebuilds the mirror, the three writes end `discarded: dataset_replaced` (visible, not silent), zero orphan cards, zero manual steps.
- `docker logs acx-prod-api-1` over 30 idle minutes is under 50 lines.

## Not doing

- Clustering algorithm or threshold changes (duplicate-cluster work is limited to a label-aware merge *suggestion*, DEMOHEAL-3).
- Replacing WP-cron, replacement of the existing Action Scheduler path, or a system cron in the demo image.
- Multi-tenant generation semantics beyond one token per tenant dataset.
- Metrics backend, tracing, or log shipping; correlation id + levels only.
- Any GPU lifecycle unit change on `acx-backend` (owned by E23/GPUOPS).
- WAF / rate limiting beyond dropping known scanner paths at the proxy.

## Delivery and consistency boundaries

Phase 1 includes API route-manifest tooling and request-id middleware as well as plugin changes; API log correlation is not proven by a plugin deploy alone. Local preflight failures remain WP-only evidence. Diagnostic probes do not wake GPUs, modify data, or bypass an open breaker. Reclaimer health uses per-tenant successful completion and the effective schedule period, distinct from remaining backlog.

Phase 2 uses an opaque UUID dataset incarnation: API admits writes only on exact equality and serializes replacement against writes. Reset/import/restore must rotate the incarnation before serving traffic. Restore tooling must not revive the old token. The mirror is eventually consistent within one incarnation; partial or mixed-incarnation snapshots never replace the visible mirror. Offline changes from an old incarnation remain visible terminal discards, never replay into the replacement dataset. The [epic](../epics/v0.5.0/demo-operability-and-mirror-self-healing-epic.md) defines the required recovery drill.

See [parallel delivery and adjudication](demoheal-parallel-delivery.md) and [draft operability contracts](demoheal-operability-contract-draft.md). Independent groups start together; only named consumed outputs and shared-file ownership constrain integration.
