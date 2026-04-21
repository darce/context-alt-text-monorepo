# Cross-Tenant Correlation Dashboards

## Problem

E15-2 Slice 3 exposes Prometheus histogram buckets at `/metrics` (request duration, counts by status class, in-flight gauge). E15-2b persists `correlation_id` on every job row and log line. Together they produce the raw signals — but operators have no UI for cross-cutting questions:

- "Show me the last 50 failed jobs grouped by `correlation_id`."
- "What's P95 latency for tenant X over the last hour?"
- "Which `correlation_id`s produced 3+ log lines with `level=ERROR`?"
- "Which endpoints are generating the most 429s per tenant?"

Today answering any of these requires hand-crafted PromQL against `/metrics` (which has no tenant label by design — see PA-06 cardinality constraint) joined manually against raw log grep output. The signals exist; the surface to consume them does not.

## Impact

- Triage during a staging or production incident depends on one operator's PromQL fluency
- Demos cannot show "here's how we monitor this" — there is no dashboard to screen-share
- Latency regressions go unnoticed until a user complains; no visual P95 over time
- Cross-tenant patterns (e.g., one tenant burning rate-limit budget) are invisible without bespoke queries

## Prerequisites

- **E15-2 Slice 3 must land first** (Prometheus `/metrics` endpoint + auth gate).
- **E15-2b must land first** (`correlation_id` persisted on job rows and log lines).
- Without both, there are no metrics or correlation data for a dashboard to consume.

## Solutions (ordered by recommendation)

### 1. Grafana + host-local Prometheus scrape (recommended)

Stand up a Grafana container alongside the existing `docker-compose.prod.yml` stack on the OCI VM. Grafana scrapes `/metrics` via the host-local Prometheus scraper (auth-keyed) and reads the file-based JSON logs via a grep-based datasource (or Loki if the operator has capacity to run it — see option 2).

Dashboards to ship:
- **Request overview**: P50/P95/P99 latency (derived from histogram buckets via `histogram_quantile`), RPS by status class, in-flight gauge over time.
- **Tenant breakdown**: the same panels filtered by a `tenant` Grafana template variable. Tenant values come from a config list (no cross-tenant leaks — each value is operator-approved).
- **Correlation lookup**: single-input panel where the operator pastes a `correlation_id` and sees all API + worker log lines for that ID, sorted by timestamp.
- **Auth/rate-limit**: 401/403/429 counters by endpoint, with drill-down to `api_key_id`-prefix fingerprint (source: E15-1 Slice 3 auth audit events).

**Pros**: Industry-standard stack. Prometheus + Grafana already in every SRE's muscle memory. No new infra beyond one more container.
**Cons**: One more container on the OCI A1 instance (24GB RAM budget — Grafana is small, ~150MB). Dashboard JSON lives in `infra/` and must be version-controlled.

### 2. Loki as log datasource (optional upgrade)

If grep-based log queries in Grafana prove too slow or lossy, add Grafana Loki as a structured log store. The E15-2 Slice 1 JSON formatter already emits single-line JSON records, so Loki ingestion is a config change only.

**Pros**: Powerful LogQL queries; joins between metrics and logs by correlation_id become first-class.
**Cons**: Another container, another volume, another set of retention knobs. Defer until pain is proven.

### 3. CLI-only recipes

Skip the UI entirely. Ship a set of runbook recipes under `docs/operations/observability-runbook.md` that document the exact grep + `jq` + PromQL one-liners for each common question.

**Pros**: Zero infra.
**Cons**: Only as good as the operator's muscle memory. Cannot screen-share during a demo or incident. Historical signal is whatever the log rotation window holds.

## Tenant Isolation Constraint

Any shared dashboard must respect the `tenant_claim` boundary that E15-1 enforces at the auth layer. Concretely:

- Template variables for tenant values are populated from an operator-maintained list, not from a `label_values(...)` query — so an accidental label leak cannot expose tenant names.
- Correlation-lookup panels must not show log lines from a tenant other than the one the operator has scoped the dashboard to.
- If a future consumer (e.g. a per-tenant "customer health" panel shared with the tenant themselves) is added, it must be a separate dashboard instance with auth-enforced scoping — not a template variable on a shared board.

## Not-Doing

- **Custom log-aggregation infrastructure install** — no Elastic / OpenSearch / Datadog. Loki is the only optional log store, and it's deferred to option 2.
- **Alerting rules** — a separate follow-on task. Dashboards first, alerts second.
- **Per-tenant customer-facing dashboards** — out of scope; shared internal dashboards only.
- **Historical backfill beyond Prometheus retention** — dashboards only cover what Prometheus holds (default 15 days on a single-instance scrape).

## Decision

Pending. Recommend solution 1 (Grafana + Prometheus) once both E15-2 Slice 3 and E15-2b have merged. Option 2 (Loki) stays deferred until option 1 is in use and grep-based log queries prove insufficient.

## Open Questions

1. Where does Grafana run — same OCI A1 host (simpler; shares fate with the API) or separate? MVP answer likely same-host.
2. Dashboard JSON: committed under `infra/grafana/` or managed via Grafana's own provisioning? Committed is more reviewable.
3. Is there a cost to running Prometheus continuously on the OCI A1 instance (storage, CPU) worth measuring before committing to the container? Expected footprint: <500MB disk over 15d, <5% CPU.
4. Should the correlation-lookup panel also surface E15-1 Slice 3 auth-audit events for the same `correlation_id` (requires auth-audit events to include `correlation_id`)?
