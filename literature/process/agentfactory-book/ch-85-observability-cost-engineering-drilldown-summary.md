# Chapter 85: Observability & Cost Engineering — Drilldown Summary

## Source record
- **Source type:** Panaversity curriculum chapter with lesson pages
- **Title:** Chapter 85: Observability & Cost Engineering
- **Part:** Part 7 — Deploying Agent Factories in the Cloud
- **Site:** Agent Factory / Panaversity
- **URL:** https://agentfactory.panaversity.org/docs/Deploying-Agent-Factories-in-the-Cloud/observability-cost-engineering
- **Accessed:** 2026-03-26

## Main idea
This chapter teaches observability as an operational system rather than a set of separate tools: first encode the work into a reusable skill, then build metrics, traces, logs, SRE targets, alerting, and cost controls into one production monitoring stack for the Task API.

## Chapter overview
The chapter starts with a skill-building lesson, then moves through the three observability signals, reliability management, and cost control, and ends with a capstone that combines all of them in one Kubernetes deployment. The through-line is practical: make system behavior visible, make reliability measurable, and make cloud spend attributable.

## Lesson-by-lesson drilldown

### L00 — Build Your Observability Skill
The opening lesson treats observability as reusable operational knowledge. The learner writes a short learning spec, fetches official documentation, creates an `observability-cost-engineer` skill grounded in those sources, and tests it with concrete PromQL output. The chapter then uses each later lesson to extend that skill instead of leaving the knowledge as isolated notes. A standing constraint runs through the lesson: observability pipelines can expose secrets, credentials, and user data, so instrumentation must be reviewed against security and data-handling rules.

### L01 — Three Pillars of Observability
This lesson defines metrics, traces, and logs as different levels of detail in the same debugging workflow. Metrics show that something changed, traces show where latency or failure occurred across services, and logs show the exact event or error that explains it. The lesson also introduces the four golden signals — latency, traffic, errors, and saturation — as the first questions to ask when a service degrades. The core mental model is not to pick one pillar over the others, but to move from coarse signal to precise evidence.

### L02 — Metrics with Prometheus
Prometheus is presented as the standard time-series system for Kubernetes because it can scrape dynamic workloads and support operational queries over time. The lesson covers Prometheus architecture, installation via the kube-prometheus stack, core PromQL patterns such as selectors, rates, aggregation, and `histogram_quantile()`, and direct instrumentation of a FastAPI service with `prometheus_client`. It centers the four golden signals in query form and adds ServiceMonitor and recording-rule patterns so the monitoring layer stays maintainable under load. It also warns against poor metric design, especially high-cardinality labels that create too many time series.

### L03 — Visualization with Grafana
Grafana turns raw metrics into dashboards that can answer operational questions quickly. The lesson builds a golden-signals dashboard for Task API, chooses panel types that fit each signal, sets thresholds that indicate risk, and adds variables so dashboards can be reused across namespaces and services instead of being hardcoded to one deployment. It treats dashboard JSON as an output worth standardizing, not just a UI artifact. The point of the lesson is speed of diagnosis: a dashboard should reduce time-to-understanding, not simply display everything Prometheus knows.

### L04 — Distributed Tracing with OpenTelemetry & Jaeger
This lesson addresses the gap metrics leave behind: they can show that latency rose, but not which step in a request path caused it. It defines spans, trace IDs, parent-child relationships, and context propagation, including the role of the `traceparent` header in carrying trace context between services. The operational goal is to instrument Task API so a request can be followed across the application, Dapr sidecar, and database, then inspected in Jaeger. The lesson frames tracing as the tool for bottleneck location, dependency analysis, and cross-service latency debugging.

### L05 — Centralized Logging with Loki
Loki supplies the event-level detail that metrics and traces cannot. The lesson explains the Loki stack in practical terms: Promtail runs on each node, attaches Kubernetes labels, and ships logs; Loki stores compressed log chunks and indexes labels; Grafana queries the result with LogQL. The chapter emphasizes structured logging and correlation between logs and traces so engineers can move from a failing trace to the exact log lines that explain it. Logs are positioned as the final explanatory layer, not as the first place to begin random inspection.

### L06 — SRE Foundations: SLIs, SLOs, and Error Budgets
This lesson turns reliability from aspiration into policy. It distinguishes SLIs, SLOs, and SLAs, then shows how an SLO translates into an error budget that can be measured and spent. The chapter uses a 99.9% availability target to show that reliability choices imply operational tradeoffs and release rules. Recording rules and dashboards make those targets visible, but the deeper point is governance: error-budget policy determines when teams ship normally, when they slow down, and when they stop risky changes to restore stability.

### L07 — Alerting and Incident Response
The alerting lesson argues that paging should be tied to meaningful reliability risk, not to every short-lived threshold breach. It introduces multi-window, multi-burn-rate alerting so short windows catch fast failures and longer windows confirm the issue is sustained, which cuts false positives while still detecting real incidents. The lesson encodes those rules in PrometheusRule objects and expects alerts to include routing and runbook context. The operational standard is disciplined response: alerts must be actionable, durable enough to matter, and connected to incident handling rather than inbox noise.

### L08 — Cost Engineering and FinOps
This lesson extends observability from system behavior to cloud spend. OpenCost provides live Kubernetes cost visibility, while allocation labels tie spend to services or teams so ownership is explicit. The lesson then adds practical cost controls such as identifying idle resources, right-sizing with VPA-style recommendations, and scheduling non-production workloads so they do not run continuously. FinOps is defined here as a management discipline with visibility, optimization, and governance phases, not as simple budget cutting.

### L09 — Dapr Observability Integration
By this point the stack can observe the application, but the lesson notes that Dapr introduces its own sidecar path that can hide latency or failure if it is not instrumented directly. The chapter shows that Dapr metrics and traces require explicit configuration, including the `dapr.io/config` annotation, and can be routed through an OpenTelemetry collector before landing in Jaeger and Prometheus. The purpose is to make state operations, pub/sub, service invocation, actors, and workflows visible as first-class parts of the system. Without that step, debugging stops at the application boundary and misses the middleware actually executing the work.

### L10 — Capstone: Full Observability Stack for Task API
The capstone combines the chapter into one production-style deployment for Task API. The expected result is a working stack with Prometheus for metrics, Grafana dashboards for the four golden signals, Jaeger for traces, Loki for structured logs with trace correlation, SLOs and error-budget tracking, multi-burn-rate alerts, and OpenCost views that assign spend by team or service. Just as important, the capstone includes a verification checklist across infrastructure, metrics, tracing, logging, SLOs, and cost, so the chapter ends with system validation rather than a demo. The final step is to update and test the reusable skill so the patterns can be invoked again in future deployments.

## What the chapter concludes
The chapter concludes that observability for deployed agents is a combined practice of visibility, reliability management, and financial control. A production system is not considered operationally complete when it merely runs; it is complete when engineers can explain its behavior, enforce service targets, respond to incidents with signal instead of guesswork, and trace cloud spend back to accountable owners.

## Structural notes
- The accessible chapter navigation exposed the landing page plus lessons L00-L10.
- I did **not** find a separate Chapter 85 quiz page in the visible chapter sequence available from the rendered navigation during this pass.
