# Observability Engineering — distilled

> **Source**: Charity Majors, Liz Fong-Jones, George Miranda, *Observability Engineering* (O'Reilly, 2022) · extracted from `../observability-engineering.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory that defines *instrumentation as a code-review-time deliverable* with falsifiable triggers: wide structured events over unstructured logs, high-cardinality/high-dimensionality telemetry as a hard functional requirement, the core analysis loop as a debugging method that replaces dashboard pattern-matching, and SLO/error-budget burn alerts as the replacement for threshold alerting. It also states precisely when metrics/monitoring remain correct (infrastructure, resource ceilings) — the exemptions that keep an "everything must be an event" reviewer from over-firing. Complements release-it (which designs systems to *survive* failure) by defining how to make failure *explainable*: ↔ release-it ch-17 designs transparency around dashboards, log levels, and an OpsDB of historical metrics; this book argues those are the known-unknowns toolkit and adds the unknown-unknowns toolkit on top.

## Chapter map

- ch-1 — What Is Observability?: definition, cardinality/dimensionality, why metrics hit a complexity ceiling
- ch-2 — Debugging: Observability vs Monitoring: dashboard/intuition pattern-matching failure modes; the self-test for reactive debugging
- ch-3 — Lessons from Scaling Without Observability (Parse): when the runbook/dashboard/retro loop stops paying; boring-technology rule
- ch-4 — Relation to DevOps/SRE/Cloud Native: symptom-based alerting; observability as prerequisite for chaos/feature flags/canaries
- ch-5 — Structured Events Are the Building Blocks: wide event definition; why metrics and unstructured logs fail as building blocks
- ch-6 — Stitching Events into Traces: span anatomy (5 required fields), context propagation, non-RPC tracing of hot code blocks
- ch-7 — Instrumentation with OpenTelemetry: auto-instrumentation first, custom attributes second; OTLP-by-default to avoid lock-in
- ch-8 — Analyzing Events: debugging from first principles; the core analysis loop; AIOps limits
- ch-9 — How Observability and Monitoring Come Together: the systems-vs-software dividing line; which infra metrics still matter
- ch-10 — Applying Observability Practices in Your Team: start with worst pain, buy over build, instrument iteratively
- ch-11 — Observability-Driven Development: instrumentation as PR gate; observability locates, debugger explains; deploy-feedback loops
- ch-12 — Using SLOs for Reliability: alert-fatigue critique; two-part alert criteria; delete unactionable alerts
- ch-13 — Acting on SLO Burn Alerts: sliding windows, burn-rate forecasting, event-based vs time-based SLIs
- ch-14 — Observability and the Software Supply Chain (Slack): tracing CI/CD; flaky-test debugging with dimensions
- ch-15 — Build vs Buy and ROI: TCO of "free" software; buy-and-build via an observability team
- ch-16 — Efficient Data Storage: functional requirements (seconds-fast, no privileged index, real-time); columnar hybrid store (Retriever)
- ch-17 — Cheap and Accurate Enough: Sampling: constant/dynamic/key-based/target-rate; head vs tail sampling; record the sample rate
- ch-18 — Telemetry Management with Pipelines: receiver→buffer→processor→exporter; routing, quality, freshness monitoring
- ch-19 — The Business Case: reactive vs proactive adoption; breaking-point symptoms; TTD/TTR as first metrics
- ch-20 — Stakeholders and Allies: non-engineering uses of event data; observability vs BI tools trade-off table
- ch-21 — An Observability Maturity Model: five capability axes, doing-well/doing-poorly signals
- ch-22 — Where to Go from Here: tightened definition; predictions (OTel default, o11y absorbs RUM/synthetics)

---

## ch-1 — What Is Observability? {#ch-1}

**Definition (software adaptation of Kálmán's 1960 control-theory term)**: a system is observable to the degree you can understand and explain *any* state it gets into — however novel — by interrogating its external outputs, ad hoc and iteratively, **without shipping new code** to handle that state and without having predicted the question in advance. If answering a new question requires deploying new instrumentation first, you don't have observability for that class of problem.

- Four sub-conditions: understand the app's inner workings; understand any state, including never-before-seen ones; do it solely by observing/interrogating from outside; do it without needing prior knowledge encoded in advance.

- **Litmus tests** (abridged; failing several = not observable):
  - Isolate the 142nd-slowest user's requests and explain why they're slow?
  - Find hidden timeouts when p99/p99.9/p99.99 all look fast?
  - Compare arbitrary groups of requests to find what all the misbehaving ones share?
  - Identify the top-N load-generating users, and which of them started recently?
  - Answer questions you never predicted, within seconds, iteratively, on first-ever occurrences?
  - Do investigations regularly *surprise* you (finding unsuspected causes), or only confirm suspicions?
- **Three-pillars critique**: "metrics + logs + traces = observability" is a vendor framing of data *types*; it says nothing about analysis. If you must have three pillars, they are **high cardinality, high dimensionality, explorability**. Data without ad hoc analysis is just telemetry — a redundant synonym, not a capability.
- **Metrics ceiling**: the metric (SNMP 1988 lineage) = a number + optional tags, pre-aggregated over a time bucket. An upper bound exists on the complexity of systems understandable with metrics+monitoring, and crossing it is abrupt: what worked last month stops, and teams fall back to strace/tcpdump/print statements. The tipping point: possible system states outrun the team's ability to pattern-match from prior outages.
- Monitoring's baked-in assumptions vs modern reality:

| Monitoring assumes | Modern reality |
|---|---|
| Monolithic app, one database you run | Many services, polyglot persistence, SaaS dependencies you don't control |
| Static long-lived hosts to monitor | Elastic capacity flicking in and out of existence |
| System metrics are the primary debugging source | Auto-instrumented system metrics are insufficient; code/user questions dominate |
| Engineers look only after problems occur | Engineers proactively watch each production change |
| Focus: uptime and failure prevention | Focus: tolerating constant partial degradation (error budgets, UX) |
| Correlation across a small set of dimensions | Correlation across effectively unlimited dimensions |
- **Cardinality** = uniqueness of values in a field (UUID = max; boolean = min). High-cardinality fields (user ID, request ID, build ID, hostname) are *the most useful debugging fields*, and precisely the ones metrics systems can't tag with at scale. You can always derive low cardinality from high (bucket, prefix); never the reverse — so capture high.
- **Dimensionality** = number of keys per event. Wide events (hundreds of key-value pairs) let you query arbitrary combinations ("all 403s on /export by user bar from host foo"). Six dimensions is a toy; mature instrumentation carries 300–400 per event.
- With metrics, every question must be decided **before** the bug occurs (new custom metric, wait for recurrence, pay per metric). With events, questions are asked of already-captured data after the fact. Monitoring is for **known-unknowns**; observability is for **unknown-unknowns**.
- Even monolith teams benefit once most problems shift from "component failed" to "which users/code paths interact badly" — the trigger is question type, not architecture.

## ch-2 — Debugging: Observability vs Monitoring {#ch-2}

- Monitoring = machine checks metrics against human-chosen thresholds; humans read TSDB dashboards. Both are downstream of a prediction someone made in advance.
- **Dashboard troubleshooting is pattern-matching**: the veteran "just knows" that a red-ish tint plus a five-minute spike means a bad DB query. That skill is non-transferable (put the same person before a different app's dashboards and the psychic power vanishes) and it institutionalizes **hero culture**: the best debugger is whoever has been there longest, because knowledge lives in scar tissue, not in a tool.
- Canonical failure modes of dashboard debugging (each is a detection cue in your own practice):
  - **Insufficient correlation**: added a DB index, want to know which queries use it / whether writes regressed at p95 — but dashboards only show host-level CPU/memory/counters, so you eyeball timestamps and guess.
  - **Not drilling down**: disk dropping on one shard → assume problem is confined there; a simultaneous import masked the same bug on the other shard.
  - **Tool-hopping**: error spike → flip dashboards → grep logs for a request ID → paste into tracing tool → repeat until a traced request happens to match. Human carries context between tools; conversion error compounds until it's near-random guessing.
- Post-incident "add a custom metric for next time" is whack-a-mole: it can't answer this incident's question retroactively (no replaying the scenario), and per-metric pricing doubles the bill before you prune.
- **Self-test** (is your team reactive? each "yes" is a cue):
  - Do you look first where you found the answer last time?
  - Do you use tools to confirm hunches rather than explore for clues?
  - Have you fixed a "confirmed" symptom that turned out to be an effect, not the cause — leaving two problems?
  - Do you translate between what dashboards show and what you actually need to know, via system familiarity?
  - Do you hop tools and carry correlation context in your head?
  - Is the best debugger on the team the person who has been there the longest? (Dead giveaway: knowledge lives in tenure, not tools.)
- Guesses aren't good enough; correlation is not causation; confirmation bias warps investigations — you can't find what you don't know to look for.
- Observability alternative: all context in one tool; investigation = follow breadcrumbs stepwise; best debugger becomes the most *curious*, not the most senior; institutional knowledge becomes explicit, queryable data.

## ch-3 — Lessons from Scaling Without Observability (Parse) {#ch-3}

- Parse (MBaaS, multitenant, microservices-before-the-name): every few days a new hosted app hit an app-store top-10 with unpredictable workloads. Nagios/Ganglia/logging/APM all failed identically: valuable only when you already knew what to look for (which threshold, which regex, which top-10 list).
- Symptom clusters those tools couldn't crack (each defeats a top-10/threshold/regex tool by construction):
  - Brand-new users skyrocketing into an app-store top 10 every other day — never in yesterday's dashboards.
  - Load from identified top-10 users *not* being the cause of the outage.
  - Slow reads that were symptoms: many individually instant tiny writes collectively saturating a lock.
  - 99.9% aggregate uptime hiding one shard 100% down — the shard holding one giant customer's data.
  - A new bot account per day saturating the MySQL primary's lock percentage.
- Fixed worker pools amplify everything: Ruby's non-threaded Unicorn pool filled within seconds whenever *any* backend slowed, taking all of Parse down (co-tenancy: when anything got slow, everything got slow). Mitigations: overprovision (20% steady-state utilization), then a two-year rewrite to a threaded language.
- The traditional loop — investigate → retrospective → runbook → custom dashboard → done — **works for monoliths where novel problems are rare, and is wasted work where novel problems are the norm** (you never see the same failure twice; the Norwegian-death-metal-band dashboard is never needed again).
- Facebook's Scuba (real-time slice-and-dice on arbitrary high-cardinality dimensions) cut time-to-source for novel problems from days to seconds/minutes. The method (ask → answer → next question) is repeatable, teachable, and shared — killing hero culture; best debugger became most curious/persistent.
- **First rule of architecture**: don't add unnecessary complexity — if a LAMP-equivalent solves your problem, use it; **choose boring technology** (boring = edge cases widely understood), and shard/partition only when scale/reliability/speed forces you.
- Decomposition's second-order effects (each invalidates a monitoring-era practice):
  - Binary up/down becomes partial degradation with complex availability heuristics.
  - Big-bang deploys become **progressive delivery** (canary, blue/green, rolling, flags — Governor's term).
  - Deploys decouple from releases (feature flags gate code paths without deployment).
  - Multiple versions bake in production simultaneously.
  - Critical infrastructure moves behind other companies' APIs.
  - Staging loses fidelity → debugging and inspection must move to production itself.
- Third-order (practice-level) effects: user experience stops being uniform across users; alerting shifts to few, symptom-only alerts; debuggers can't attach across network hops; recurring known failures get auto-remediated, so what pages you is by definition novel.
- Attention ordering: modern teams must put primary engineering attention on production tooling first, staging second. Teams that keep production a **glass castle** (fear-driven rollbacks, deploy freezes) lack the controls to tweak, degrade gracefully, or progressively deploy — and suffer for it.

## ch-4 — Relation to DevOps, SRE, and Cloud Native {#ch-4}

- Observability is, like testability, a *property* of a system requiring continuous investment — not a one-time addition.
- Cloud native (per CNCF: loosely coupled, resilient, manageable, **observable**) trades emergent complexity for velocity; old work habits fail at the management cost. Immutable infra kills ssh-debugging; transient container state dies at restart; service meshes generate routing data useless without analysis.
- Mature DevOps/SRE alert on **symptoms of user pain, not enumerated causes** — then explain the failure with observability tooling, instead of maintaining an ever-growing list of known failure modes.
- Cloud-native technology adoption without work-habit change is a known trap: teams get several steps in before discovering old habits can't handle the new management costs — successful adoption of these patterns is inseparable from observable systems plus DevOps/SRE practice.
- Practices that *require* observability data to function:
  - **Chaos engineering / continuous verification** — meaningless without knowing baseline steady-state and being able to explain deviations. (No point injecting chaos if you can't tell how the system behaves *now*.)
  - **Feature flags** — flag-state combinations explode; per-user, per-flag impact can't be pre-tested; monitoring "component by component" no longer holds when one endpoint executes many ways.
  - **Progressive delivery (canary, blue/green)** — need to know when to stop the release and whether deviations are caused by it.
  - **Incident analysis / blameless postmortem** — needs an ex post facto paper trail of what the system *and* the responders were doing/believing.

## ch-5 — Structured Events Are the Building Blocks {#ch-5}

- **Arbitrarily wide structured event** = the fundamental unit of observability. Definition: a record of everything that occurred while one request interacted with one service. Mechanic: initialize an empty map at request entry; append anything interesting during execution (request params, IDs, variable values, remote-call targets and durations, runtime/host info); emit the whole map as one structured record at exit/error.
- Scope rule: one event ≈ one **unit of work** (for services: one request through one service; for batch jobs: one object processed).
- **Metrics fail as building blocks** because they are pre-aggregated at write time: the aggregate becomes the lowest granularity available; a single request smears across hundreds of disconnected metrics with no connective tissue to reassemble it. Events can compute every metric aggregate after the fact (1,000 events with `page_load_time` reproduce the 5-second average *and* subdivide by user/host); the reverse is impossible. "Enough metrics to reconstruct requests" is an escalating arms race metrics stores aren't built for.
- **Unstructured logs fail** because they're human-readable narrative split across multiple lines: one connection's story = five log lines, usually with no shared request ID. Remedy path: structure the logs (key=value / JSON) → collapse multi-line narratives into **one event per unit of work** → they become usable as events. Micro-example (paraphrased from the book's canonical one):

```
# before: 5 narrative lines for one request
6:01:00 accepted connection ...
6:01:03 auth accepted for user foo
6:01:15 processing /super/slow/server
6:01:18 sent 200
6:01:19 closed connection
# after: one structured event for the whole unit of work
{"msg":"Served HTTP request","authority":"10.0.0.3:63349","duration_ms":123,
 "path":"/super/slow/server","status":200,"service_name":"slowsvc",
 "trace.trace_id":"eafdf3123","user":"foo","time":"..."}
```
- Events must be arbitrarily wide (no fixed schema): predefining a schema requires predicting your debugging needs, which contradicts the point. Backends requiring predefined schemas are orthogonal to observability (→ ch-16).
- Debugging novel problems = finding outliers and what they share, which requires **high-cardinality query support** (e.g., "Canadian users, iOS 11.0.4, French language pack, installed last Tuesday, firmware 1.4.101, photos on shard3 us-west-1" — every constraint high-cardinality).

## ch-6 — Stitching Events into Traces {#ch-6}

- A trace = interrelated series of events; a **span** = one event within it. Lineage: Dapper (2010) → Zipkin (2012) → Jaeger (2017) → commercial tools.
- Five fields required to assemble any trace (everything else is tags/attributes):

| Field | Role |
|---|---|
| Trace ID | Generated at root span; propagated through every hop of the request |
| Span ID | Unique per span (unit of work within the trace) |
| Parent ID | Defines nesting; absent ⇒ this is the root span |
| Timestamp | When the span's work began |
| Duration | How long the work took |

- Add service name + span name for usability; then arbitrary attributes (hostname, user, build_id…). A service may appear multiple times in one trace (circular dependencies, parallel computations).
- Propagation mechanic: set trace ID + current span ID (as parent) in outbound request headers (W3C TraceContext or B3); each downstream service builds its own span and sends it to the backend, which reassembles the waterfall.
- Traces exist because latency stacks: a bottleneck three or four layers downstream shows up as latency in dozens of upstream services; "when something gets slow, everything gets slow." The waterfall view localizes it.
- **Tracing is not just for RPCs**: wrap "hot blocks" (e.g., CPU-heavy JSON unmarshaling) in their own spans inside a monolith; create a span per object in a batch job; per phase of a Lambda pipeline. Structured logs + trace fields can be stitched into waterfalls as a migration step.
- Vendor-specific tracing libraries force re-instrumentation to switch tools → use OTel (ch-7).

## ch-7 — Instrumentation with OpenTelemetry {#ch-7}

- **OTel** = merger of OpenTracing + OpenCensus (2019, CNCF); the single open standard: instrument once, export anywhere. Concepts: API vs SDK, tracer, meter, context propagation, exporter, collector (standalone proxy/sidecar; OTLP wire protocol).
- **Order of operations**:
  1. Enable automatic instrumentation — wrappers/interceptors (explicit in Go, runtime agent in Java/.NET) that auto-span every incoming/outgoing HTTP, gRPC, and DB/cache call. This alone gives the who-calls-whom skeleton and finds uncached hot DB calls and slow downstream endpoints in hours, not months.
  2. Add **custom instrumentation** on top: business-logic attributes (client ID, shard ID, cart value, errors) attached to the active span, plus custom spans around expensive internal steps. Custom instrumentation is where observability-driven development (ch-11) lives — write it alongside the feature to verify it in production during release.
- Rule of thumb: batch data from a request's execution into **one wide event per request per service**; add any field you'd want during a future debugging session. Open spans buffer attributes until finished — keep appending.
- **Metrics inside instrumented code**: most counters/measures belong as *attributes on the span they pertain to* (e.g., cart value on the cart-processing span). Reserve process-wide scraped metrics for values that are genuinely non-request-scoped (e.g., goroutine count) or need exact unsampled pre-aggregated counts.
- Export via OTLP gRPC to a collector or vendor endpoint by default; multiple simultaneous exporters are supported (useful to trial a second backend with zero re-instrumentation).
- Instrumentation-at-write-time trigger: adding a new endpoint, queue consumer, or external call with no span/attribute emission is a review-time defect (→ ch-11).

## ch-8 — Analyzing Events to Achieve Observability {#ch-8}

- Having the data isn't enough; you can still "debug from known conditions" with it (grep the event stream for known strings, eyeball dashboards of query results). The shift is methodological.
- **Debugging from first principles**: assume nothing; verify what's true; form and test hypotheses against data. Practiced via the **core analysis loop**:
  1. Start from what triggered the investigation (alert, customer report).
  2. Verify it in the data: is there a visible behavior change?
  3. Hunt for driving dimensions: inspect sample rows for outlier columns; group by candidate fields (`status_code`, endpoint…); filter to expose patterns.
  4. Enough to explain? Done. Otherwise isolate that slice as the new starting point; goto 3.
- This is brute-forceable with zero prior system knowledge — which is the point: it **democratizes debugging** (favors the curious over the tenured) and is slow for humans, so the tool should automate the brute-force stage: compute all dimension values inside the anomalous region vs the baseline region, diff, sort by difference (Honeycomb **BubbleUp**: draw a box around the anomaly on a heatmap).
- Example automated output shape — each line a candidate explanation, ranked by baseline/anomaly divergence:
  - `request.endpoint = batch` — 100% of anomalous requests vs 20% of baseline.
  - `handler_route = /1/markers/` — 100% vs 10%.
  - `global.availability_zone = us-east-1a` — 98% vs 17% → provider AZ issue, found in one query; small divergences rank low and are likely irrelevant.
- **AIOps critique**: anomaly-detection AI must choose its own baseline window; in frequently deployed systems every deploy/fix/optimization *is* an anomaly, so the box is always mis-sized → noise or silence. Division of labor: machines crunch (detect spikes, diff distributions); **only humans attach meaning** (good/bad, intended/not). Automate the core analysis loop; keep the judgment human.

## ch-9 — How Observability and Monitoring Come Together {#ch-9}

- Neither replaces the other. Dividing line: **monitoring for systems (infrastructure), observability for software (your code)**.
- The systems-vs-software factor comparison (condensed from the book's Table 9-1):

| Factor | Your systems (infra) | Your software (code you ship) |
|---|---|---|
| Rate of change | Package updates, ~monthly | Repo commits, daily |
| Predictability | High, stable | Low, constant new features |
| Business value | Cost center | Revenue generator / differentiator |
| Users | Few internal teams | Your customers |
| Core question | Is the service healthy? | Can each request complete end-to-end, timely and reliably? |
| Evaluation perspective | The operator | The customer |
| Method | Monitoring | Observability |

- Consequence: aggregate metrics + alerts fit slow-changing predictable infrastructure; per-request high-cardinality analysis fits fast-changing code evaluated through customer experience. "Bought as a service" components aren't your infrastructure; components you install/configure/upgrade/troubleshoot are.
- Sizing rule by operational responsibility: run bare metal → need low-level hardware monitoring; IaaS → drop hardware-level, keep system-level; mostly PaaS/serverless/SaaS → little traditional monitoring at all. You monitor what you *operate*.
- **The exemption that prevents over-firing**: higher-order infra metrics that directly bound software performance — CPU usage, memory consumption, disk activity/IO — remain essential *even for software teams*, as early-warning signals of code problems (deploy triples resident memory within minutes; new feature doubles CPU). Capture these alongside (or inside) your events; monitoring is used to rule infrastructure in/out during an investigation.
- ↔ agrees with release-it ch-17: historical/system trending belongs in metrics-and-monitoring land; ↔ contra release-it ch-17: dashboards + log levels are presented there as the primary transparency instrument — this book demotes them to known-unknown warning signals, inadequate for debugging application behavior.
- Coexistence patterns observed: Prometheus for central ops + observability for app teams; greenfield serverless shops skipping monitoring entirely; legacy estates keeping monitoring on stable services while new services get instrumented for observability (don't rip out what works on stable systems).

## ch-10 — Applying Observability Practices in Your Team {#ch-10}

- **Start with the biggest pain point, not a small safe service**: a well-behaved pilot service yields all of the cost and none of the proof. Pick the flaky service that pages people, the mystery DB congestion — solve it, then socialize the win.
- **Buy over build** (details ch-15): no current open source single tool meets the functional requirements (Prometheus = metrics ceiling; ELK = plain-text search, weak at compound analytical questions; Jaeger = traces without analytics). Instrument with OTel so trying/switching vendors is a config change, then stress-test any candidate against real high-cardinality debugging.
- **Instrument iteratively**: auto-instrumentation first; thereafter, every on-call page becomes an instrumentation opportunity — first responder adds instrumentation to the problem area, debugs from what it shows. Two or three cycles in, instrumenting-first becomes the habit.
- **Leverage existing streams to defuse sunk-cost resistance** (the sunk-cost fallacy will stall adoption if unaddressed; blend worlds so people see their current concerns in the new tool):
  - Tee Logstash/ELK output to the new tool as a secondary destination; invite comparison.
  - Add a unique request ID to existing structured logs and send them as trace events while keeping the old log tool running.
  - Run OTel beside the legacy APM agent; let users compare experiences directly.
  - Re-create the most-used old dashboards as saved queries — an imperfect but familiar landing spot invites exploration far better than a scratch dataset.
- **Plan the last push**: iterative on-call-driven adoption covers ~half to two-thirds of the stack; rarely touched components need a deliberate completion sprint or the org lives with split tooling indefinitely. Genericize instrumentation into shared libraries as you finish.

## ch-11 — Observability-Driven Development {#ch-11}

- TDD validates code against an isolated, repeatable specification; it says nothing about behavior amid production's concurrency, real data, and real users. ODD is the production-side complement: write instrumentation alongside features, watch them ship.
- **Bugs are cheapest to fix while original intent is fresh**: the elapsed time between merging a bug and examining it multiplies debugging cost across many people. It will never again be as easy to debug as right after writing and shipping it. So: engineers watch their own code deploy; optionally auto-route production alerts to whoever merged, for the first 30–60 minutes post-deploy — not punishment, ownership feedback loop. You cannot develop shipping instincts while insulated from your errors' consequences.
- Advanced feedback loops: test proposed changes against a slice of production traffic — feature flag exposed to a user subset, or route selected requests to the new path. Shrinks feedback from release-cycle-length to seconds/minutes.
- **Scale separation**: observability tells you *where* the problem lives (which component, hop, build ID, instance type, user subset — errors originate where? latency introduced where?); a debugger/profiler tells you *why* within the code, on a local reproduction seeded with context copied from a trace. Telescope vs microscope. Line-level "verbose logging" through the observability pipeline would cost 1–10× the system itself — wrong tool.
- Example forks from one latency spike: (a) group by endpoint → trace a slow request → timeouts start at service3 → reproduce locally under debugger; (b) group by endpoint → only writes slow → group by DB host → only one instance type in one AZ → infrastructure, not code.
- **PR gate**: never submit or accept a pull request without answering "how will I know if this change works or misbehaves in production?" Post-deploy, every engineer should be able to answer: is it doing what I expected? How does it compare to the previous version? Are users using it? Anything abnormal emerging?
- Speed and quality are not a trade-off (Accelerate): elite performers gain both; slow-moving teams fail more and recover slower. Track **time from code written to code in production** as the team's key health metric. To speed delivery: ship one coherent change per merge per engineer (batched multi-person deploys are the top cause of day-long untangles); staff the deploy pipeline with experienced engineers, owned and improvable by everyone.

## ch-12 — Using Service-Level Objectives for Reliability {#ch-12}

- **Threshold alerting on potential causes (CPU >80%, memory <10%, thread counts) generates false positives** because those states have many benign explanations (backups, GC, opportunistic caching). Teams learn to ignore or suppress them — **normalization of deviance** (Challenger-investigation term for desensitization to deviating from expected response) → alert fatigue; post-incident reviews add "the alert that would have caught this," compounding the noise incident over incident. AIOps alert-grooming products are the industry productizing its own dysfunction.
- The same system-metric anomaly (abnormal thread count) may mean GC in progress, imminent upstream slowness, or nothing — the 3 a.m. responder is left to divine which. Cause-based alerts fuse "what" and "why" and get both wrong.
- In distributed systems failure is continuous and partial; auto-remediation (autoscaling, failover, rollback-on-canary) handles known failures. **Auto-remediated failures must not page** — debug them during business hours; pages are reserved for emergencies. Alerts left over after that are largely novel problems.
- **Two-part criterion for keeping any alert** (subset of the Google SRE definition): (1) it reliably indicates degraded *user experience*; (2) it is actionable — a systematic response exists that isn't rote-automatable. Any alert failing either test should be deleted.
- Static thresholds can't express user experience: "10 users saw slow pages" means opposite things at 100 vs 10,000 concurrent sessions; five-minute good/bad buckets produce both false positives and false negatives.
- **SLO** = internal target for service health defined over user-centric **SLIs**. Event-based SLI construction, worked pattern:
  1. Qualify events (e.g., request path == /home).
  2. Screen for the experience condition (duration < 100 ms).
  3. Fast + successful ⇒ good.
  4. Slow ⇒ counts as an error **even if it returned a success code** — slowness is user pain.
  5. Every bad event spends error budget; enough spend triggers a burn alert (ch-13).
- SLO alerts decouple **what** (users are hurting) from **why** (unknown until investigated) — the decoupling is the point, and it is only tolerable if your system is debuggable enough to find the why: **SLOs without observability leave you with unactionable alarms**. You need *data for everything*, not *alerts for everything*.
- Honeycomb case study (trust must be earned before deleting old alerts): a 20-minute 1.5% ingest brownout — fleet-wide memory leak causing synchronized crash/restart — burned most of a 30-day error budget. The SLO alert fired at 1:29 a.m. and repeatedly thereafter; traditional consecutive-probe monitoring never fired at all (cluster "up," most data flowing; coarse probes can only see total outage, not 1-in-50 failures). The on-call engineer initially dismissed the SLO alert because the trusted traditional alerts stayed quiet; only the fourth firing triggered an incident. Alerting on OOMs wouldn't have worked either — the architecture OOM'd benignly all the time; predicting the exact bespoke combination of "notable OOMs" in advance is exactly the trap. After SLO alerts proved themselves in incidents like this, the team deleted all percentage-error/absolute-error/system-level alerts and runs SLO-only paging.

## ch-13 — Acting on and Debugging SLO-Based Alerts {#ch-13}

- **Error budget** = maximum tolerable unavailability (1 − target, over the window, in events). Empty budget ⇒ feature freeze / stability work — so the game is alerting *before* it empties.
- **Window framing**: use a sliding window (typically 30 days), never a fixed calendar window — customer memory of your outages doesn't reset on the 1st, and resets destroy the data you need for trend decisions. 7–14 days is too short to match customer/product memory; 90 days lets one terrible day technically pass.
- **Burn alerts**: crude form = alert when remaining budget crosses a threshold (30%) — just moves the goalposts. Better = **predictive burn alerts**: extrapolate current burn rate; page only if the budget empties within the lookahead window. On track for 99.88% vs a 99.9% target a month out = ticket tomorrow; on track for 98% within an hour = page now.
- **Baseline↔lookahead ratio**: extrapolate at most ~4× the baseline window — larger ratios flap, smaller ones react too slowly. Handy heuristic: 24-hour burn alarm ← last 6 h of data; 4-hour alarm ← last 1 h. Run burn alerts on multiple timescales and act on whichever fires; short-window alerts can fire while long-window ones don't (different baselines) and that ordering is correct, not a bug.
- Use **proportional** extrapolation (failure *rate* × expected traffic for the window), not linear failure counts. Worked contrast from the book's example (99% target, 43,800 units/month budget ⇒ 438 allowed failures): 25 failures out of 50 units in a quiet 6 h extrapolates linearly to a harmless ~105 total, but proportionally (50% failure rate × 1,440 expected units/day) to ~720 — budget gone in half a day; page now. Overnight lulls fool linear math.
- Two computation modes: **short-term/ahistorical** (baseline window only; cheap) vs **context-aware/historical** (tracks whole SLO-window totals; expensive — Honeycomb once hit $5k/day of Lambda recomputing them; choose it only if urgency should scale with budget remaining).
- **Event-based SLIs beat time-based SLIs**: with "good minute/bad minute," one minute at 94% success burns 25% of a four-9s monthly budget in one evaluation (5-minute buckets are worse). Event-based counting subtracts only the 6% of requests that actually failed. Brownouts dominate blackouts in modern systems: a 1% brownout of a 99.99% service ≈ a 100% outage of a 99% service — event-granularity measurement is what buys you the hours of response time.
- Acting on a burn alert — triage by shape before responding:
  - Gradual steady burn (normal in modern systems: retries, delayed completions, failovers) → business-hours work, sprint prioritization.
  - Bursty burn → look for periodic disturbances.
  - One-shot cliff (large fraction burned at once) → incident-style response.
  - Compare with the SLO's 90-day trend before deciding urgency — a budget recovering because an old dip aged out reads very differently from fresh degradation. Burning all at once vs slowly over time hints at different failure classes.

## ch-14 — Observability and the Software Supply Chain (Slack, guest ch.) {#ch-14}

- CI/CD is production for internal-tooling teams — often *more* complex than the product; when it's slow or flaky, the whole delivery pipeline downstream is bottlenecked. Lower cardinality than prod, but each event is far more critical.
- "It is slow" is the hardest distributed-systems problem; "it is flaky" is the most-heard internal-tooling complaint — both are correlation problems across interacting high-complexity systems, i.e., observability problems.
- Instrument the CI orchestrator and runners with traces; propagate common dimensions (hostname, worker label, commit head/main, test suite, platform) so failures can be grouped by any of them — each dimension is a breadcrumb; combinations drill to specific issues (e.g., hostname × worker label → concurrency hotspots; commit tag → which change broke the build).
- Payoffs within hours of instrumenting (both from an afternoon-prototype level of effort):
  - Anomalous Git-checkout runtimes exposed hosts that had silently fallen out of the auto-scaling group — a slowness bug producing no errors at all.
  - A first cross-service trace (runner → test environment) found Git-LFS-starved hosts and ended a multi-day multi-team cascading incident in under two hours.
- Flaky tests case: end-to-end suites at ~15% flake rate, p95 commit-to-results turnaround >30 min, 100k weekly compute-hours discarded on rerun executions; daily 30-minute triage sessions made no progress because the working belief was "the test code is flaky." Tracing runtime parameters showed, within days, that test-suite *configuration* dimensions correlated with flakes; better platform defaults + guardrails dropped suites from 15% to <0.5%. Rule: when "it's flaky" persists across triage sessions, instrument runtime dimensions before blaming test code. Method tenets: (1) trace previously unexplored runtime variables, (2) ship small observability-driven feedback loops, (3) run reversible experiments on correlated dimensions.
- Memory-jump incident: traces of per-test memory at p50/p95/p99 with hour fidelity let responders correlate OOM bursts to candidate PRs from months of change history, revert, and verify recovery in near real time.
- Embed alert links that open pre-parameterized queries (per test-suite dashboards, RED-style drill-downs) so responders land in the investigation, not at a blank query box.

## ch-15 — Build Versus Buy and ROI {#ch-15}

- "Free" open source has a hidden TCO: a real example — an in-house ELK stack rejected as "$1M/yr commercial is too expensive" actually cost >$2M/yr (dedicated hardware $80k/mo, three extra engineers at $250–300k plus recruiting/training). "Free as in puppies, not free as in beer." Engineers' time is the second-rarest element.
- Opportunity cost test: are you in the business of building observability tooling? If not, a bespoke platform is a distraction from core business value; enterprises habitually build v1, move on, and abandon the unowned tool.
- Building's genuine benefits: deep in-house expertise, bespoke fit; risks: no product management for internal users → low adoption; months of delay to first value; permanent maintenance tail.
- Buying's hidden costs: pricing dimensions that penalize the success behaviors you want (per-seat, per-host, per-query — curiosity should not cost linearly more; demand transparent cost forecasting from vendors), and vendor lock-in via proprietary agents — mitigated by instrumenting with **native OTel + vendor distros**, so switching = swapping exporters.
- **Recommended posture: buy and build.** Keep an observability *team* whose job is not building a backend but being the vendor↔engineering integration point:
  - Write shared instrumentation libraries and useful abstractions.
  - Standardize naming conventions/schemas across the organization.
  - Handle updates and upgrades gracefully; manage vendor relationships.
  - Consult with product teams on effective instrumentation.
  - Build last-mile workflow glue against the vendor's API (precondition: pick a product with a full query/config API).
- High-performing orgs aim maximum engineering firepower at core business problems and buy best-of-breed tools for everything else; low performers settle for mediocre tools, solve most problems in-house, and leak engineering cycles org-wide.

## ch-16 — Efficient Data Storage {#ch-16}

- **Functional requirements** the backend must satisfy (these define whether a tool can support observability at all):
  1. Queries return in ~seconds — iterative investigation dies at coffee-break latency.
  2. Any field on any event/span queryable, at full (pre-aggregate) resolution — pre-aggregation creates investigative dead ends.
  3. **No privileged dimensions** — indexing everything is prohibitive, so retrieval must be fast without indexes; time is the sole indexed exception.
  4. Data queryable within seconds of ingest — stale data → red herrings and wrong conclusions mid-incident.
  5. Fault-tolerant and durable — your o11y store must not be down precisely when production is.
- **TSDBs are structurally unfit**: their economics amortize cost by re-incrementing existing series; unique event dimensions ⇒ new row per event ⇒ **cardinality explosion** (row-creation cost linear in events). NoSQL stores need indexes to be fast, and indexing every high-cardinality column yields indexes larger than the data. Scuba solved it with RAM (≈40× SSD cost — economically infeasible outside Facebook). Dapper's own backend found indexing just three fields cost 76% of trace-data size.
- Row vs column trade-off:
  - Row stores (Bigtable-style): whole-row retrieval fast via primary key; but mutability machinery (overlay files + compaction) fights a write-once-read-many workload, and reading one field still drags the whole row/locality group.
  - Pure column stores (Dremel/ColumnIO-style): single-field scans cheap; but row reconstruction may scan the whole table, and manual date-sharded tables become unmanageable at volume.
- Answer: **hybrid columnar store partitioned by time**:
  - Append events to the active **segment** per tenant; finalize by age/rows/bytes; record oldest/newest timestamps as metadata; segments are immutable — no compaction, out-of-order arrival handled at read time by overlapping windows.
  - Within a segment, one append-only file per field + a timestamp index; dictionary/run-length/sparse encodings, then LZ4. New columns are cheap; one-use columns (key baked into the name) are the anti-pattern — put variable parts in values, not keys.
  - Query = select segments overlapping the time range → scan only referenced columns → filter/group per row → aggregate within, then across segments → top-K. No pre-aggregation, no privileged field, arbitrary filter combinations.
  - Recent data on local SSD, older segments tiered to object storage; queries fan out serverless map-reduce style; re-request the slowest ~10% of subqueries and race them (fast-but-99.5%-complete beats slow-perfect for debugging).
  - Ingest via Kafka for ordering/durability; stateless receivers validate and route rows to topic/partitions; stateful, deterministic ingesters consume in order (parallel consumers produce identical segments → redundancy; restart = checkpoint the offset and resume; replace = snapshot + replay). Kafka retention only needs to cover disaster-replay (hours–days).
  - Separation of concerns: ingestion and query share only the filesystem — a serialization stall delays ingest without blocking queries on older data, and a query spike doesn't stall ingest.
  - Scale reference point (2021): ~1.5 M spans/s ingested with millisecond query lag, ~700 TB columnar data, median query 50 ms / p99 5 s — on commodity workers + serverless, no RAM-resident dataset.
- If your problems are too hard to solve, you probably have the wrong data abstraction. Don't press Elasticsearch/Cassandra into this role; if building, start from a columnar store (ClickHouse, Druid, BigQuery).

## ch-17 — Cheap and Accurate Enough: Sampling {#ch-17}

- Past a certain scale you cannot run an o11y stack the size of production; most events are near-identical successes. Sample events, keep full per-event cardinality, and transmit metadata to reconstruct the original distribution — unlike pre-aggregation, granularity survives. Debugging needs a representative sample of *good* events to compare bad ones against.
- Strategy ladder (each fixes the previous one's failure mode):

| Strategy | Mechanic | Fails when |
|---|---|---|
| Constant-probability | Keep 1/N uniformly | You care about rare errors; low-traffic tenants drowned by big ones; traffic spikes overwhelm the backend |
| Traffic-volume-adjusted | Rate follows recent volume | — but reconstruction must weight each event by its own rate (medians expand weighted values, not average kept rows) |
| Content/key-based | Rate per field values: errors ≫ successes, new orders ≫ status checks, paying ≫ free tier | Key space large or rate ratios unstable (error floods invert the assumption — validate it) |
| Key + recent-volume | Per-key dynamic rates (e.g., [customer, dataset, error code] over last 30 s); rare combos kept near-verbatim | Hand-rolling it — use libraries (dynsampler-go) once past two keys |
| Target-rate | Compute rates from measured volume to hit a fixed events/sec budget; separate budgets for baseline vs outlier (error/slow) events | Needs per-key budgets as categories multiply |
- **Implementation invariants**: always record the in-effect `sampleRate` inside each kept event (backends must weight by it; never assume a global constant); derive the sampling decision from a **propagated trace/sampling ID**, not per-service RNG, so a trace is kept or dropped consistently end-to-end (child services sampling independently ⇒ broken traces).
- **Head vs tail decision timing**:

| Approach | Decision made | Can use | Cost | Failure mode |
|---|---|---|---|---|
| Head-based (up-front) | At trace start | Static fields only (endpoint, customer ID) | Cheap; propagate a "require sampling" header bit | Blind to outcomes — can't preferentially keep errors/slow requests |
| Tail-based | After completion | Dynamic fields (status, latency) | Requires buffering whole traces; collector-side logic | Infeasible purely in-process; orphan outlier spans if done per-service |
| Buffered/collector hybrid | Deferred until trace complete | Both | Highest | Operating the buffering tier |

- Practical hybrid: head sampling for a consistent baseline plus per-service tail/outlier rules; escalate to buffered collector sampling when decisions genuinely need whole-trace visibility.

## ch-18 — Telemetry Management with Pipelines (Slack, guest ch.) {#ch-18}

- A telemetry pipeline decouples producers from backends: chain of **receiver → buffer → processor → exporter** (chainable; the common "source/sink" naming hides that chaining). Adoption triggers — introduce a pipeline when any of these appear as requirements:
  - Routing changes without application changes (tee one trace stream to tracing backend + analytics cluster).
  - Security/compliance: PII detection/redaction, GDPR/FedRAMP-constrained storage location, retention/deletion lifecycles, self-service deletion.
  - Workload isolation: high-volume logs must not degrade query performance or retention of low-volume/long-retention sets.
  - Buffering: local disk + Kafka/Kinesis to survive backend outages and smooth spikes (Slack retains ~3 days for replay after a backend recovers).
  - Capacity control: quotas per telemetry category.
- Capacity levers: rate limiting (hard drop vs soft-limit-with-aggressive-sampling), volume-responsive sampling, and **freshness-first queuing** during log storms (new data explains the incident; backfill old data later).
- Data-quality functions: drop/fix absurd timestamps (Candy Crush users clock-skewing their phones for rewards is the canonical pollution case), enforce schemas, convert unstructured→structured, redact secrets/PII, drop low-value spans, enrich with region/K8s/GeoIP metadata, transform to a common event format (Slack's SpanEvent: id, timestamp, duration, parent/trace IDs, name, type, tags — writable both to the trace store and the warehouse for long-tail SQL analytics; landing latencies: seconds to Elasticsearch/Honeycomb, ~2 h to warehouse, retention 7 d / 60 d / 2 y respectively).
- Operating challenges = control theory: monitor pipeline correctness, saturation/bottlenecks, and **end-to-end freshness with synthetic events** (Slack: 100 synthetic logs/min injected, queried every 10 s; SLO on complete arrival) — uniquely tagged so they don't pollute user queries.
- Build-vs-buy: modern open source (OTel Collector, Fluent Bit, Vector, Cribl, M3 aggregator, Refinery) covers the pattern; don't write a bespoke pipeline core today. Keep it modular; build for current needs, anticipate (don't pre-build) compliance/enrichment.

## ch-19 — The Business Case for Observability {#ch-19}

- Reactive adoption follows a catastrophic outage and tends to oversimplify ("we lacked backups" → demote someone, buy backups) instead of treating causes. The subtler failure is tolerating obsolete dysfunction as normal: change-advisory boards, Friday deploy bans, on-call exemptions for heroes — cultural workarounds for not understanding production.
- **Breaking-point symptoms checklist** (multiple present ⇒ systemic observability gap):
  - Customers find and report critical production bugs before internal detection.
  - Minor incidents escalate into prolonged outages because detection/recovery is slow.
  - Triage/investigation backlog grows faster than it drains.
  - Break/fix operational work exceeds feature-delivery work.
  - Support can't verify, reproduce, or resolve customer-reported performance complaints.
  - Features slip by weeks/months because teams reverse-engineer how services interact.
- Cultural tells of the same gap: change-advisory boards, no-Friday-deploy rules, on-call exemptions for heroes — process workarounds for not understanding production.
- First proactive metrics: TTD and TTR — flawed but executive-legible; second-order: less unplanned work, lower on-call stress, retention; third-order: conversion/latency wins (>half of mobile users abandon after 3 s). Claimed universal ROI channels: incremental revenue from uptime/perf, faster response labor savings, avoided incidents, reduced churn/burnout.
- Adoption is a *practice*, like security or testability — never checkbox-done. Preconditions: blameless culture (psychological safety to experiment), one clearly scoped pilot team, baseline TTD/TTR measured before starting, budgeted platform work.
- Tooling section repeats the standards: OTel for instrumentation (no reason for proprietary agents); avoid one-tool-per-pillar — disjointed systems put context-carrying back on humans; beware self-hosted cluster toil (ELK time sink).
- **"Enough" observability** looks like: instrumentation reviewed in every code review as tests are; engineers watch each deploy; one-off production questions self-served by non-engineers; fewer "mystery" incidents; falling TTD/TTR; when data can't answer a question, the reflex is *add telemetry*, not guess. Don't over-index on raw incident counts — better detection surfaces more, and that's progress.

## ch-20 — Observability's Stakeholders and Allies {#ch-20}

- Wide-event telemetry doubles as product/business data; democratize it to build adoption allies. Uses: feature-adoption analysis, usage-pattern differences between retained and churned users, live status for support, reliability trends vs complaint volume, proactive issue detection, deploy watching.
- Per-team applications of the same event data:
  - **Support**: check SLO dashboards first, then query a specific customer's actual requests ("cart checkout failing 50% for Android users in Europe" beats binary up/down); confirm/deny known-issue linkage instead of blindly piling tickets; savvy support can even surface issues an under-parameterized SLI missed.
  - **Customer success/product**: find what active adopters of a feature do differently (e.g., adopters are 10× more likely to build custom reports → train toward that); see which customers still use features being sunset and reach out before the deadline; distinguish tire-kicking from workflow adoption of a new feature.
  - **Sales/executives**: which features strategic customers depend on (⇒ highest availability targets); which features demo hottest (⇒ must always be fast); express engineering investment goals in user-experience terms instead of vague "get to 100% availability" mandates — a shared cross-cutting language is what creates alignment.
- **Observability ≠ BI** — hyper-specialized for code×infra×users×time. Trade-off table:

| Axis | Observability tooling | BI tooling |
|---|---|---|
| Query latency | Subsecond–seconds (train of thought dies waiting) | Minutes fine; reports reused |
| Accuracy | Fast-and-99.5% beats slow-and-perfect | Exactness mandatory (billing) |
| Recency | Freshest data most valuable; seconds-old queryable | Caching/preprocessing acceptable |
| Retention | Bounded; two-year-old spans rarely wanted | Keep (practically) forever |
| Schema | Inferred/changed on the fly; wide events; no indexes | Predefined schemas, indexes, aggregates |
| Session length | Traces of seconds–minutes | Journeys of days–weeks |

- Aggregate multi-year performance trends belong to neither — that's monitoring's job (↔ release-it ch-17's OpsDB/historical-trending role, which this book leaves intact).
- Practical pairing: BI for macro (feature-of-the-month), observability for micro (per-request); shared telemetry vocabulary aligns engineers and business on real usage rather than composite personas.

## ch-21 — An Observability Maturity Model {#ch-21}

- Maturity-model caveats: static snapshot, author bias, no universal fit, practices have no upper bound; use as a starting checklist for prioritization (Wardley-map the capabilities), with named owners and executive sponsorship — a silo can't reach maturity alone.
- Survey signal: teams practicing observability were ~3× more likely to be confident in production code quality; non-adopters spent >half their time on work that shipped no features.
- Five capability axes, each with observable doing-well/doing-poorly tells:

| Capability | Doing well looks like | Doing poorly looks like | Observability's contribution |
|---|---|---|---|
| Resilient failure response | Sustainable on-call; alerts acted on; incidents handled without heroics | Alert fatigue; prolonged incidents; same few people always pulled in | Actionable alerts, context-rich events, shared investigation trails so anyone can respond |
| High-quality code | Stable in prod; debugging intuitive at any stage; isolated issues stay isolated | Time dominated by bug-fixing; deploy fear; low post-ship confidence | Watch code during deploys; validate fixes; same tooling debugs 1 machine or 10,000 |
| Complexity/tech-debt management | Most time on core goals; engineers navigate the codebase confidently | Ripple effects from local changes; "haunted graveyard" code nobody dares touch | Find the *right* bottleneck instead of guessing where to optimize |
| Predictable release cadence | Code ships shortly after review; flags decouple release from deploy; fast rollbacks | Infrequent human-heavy releases; ordered release trains; seasonal deploy freezes | Compare old/new build IDs side by side; instrumentation tells you the build is good |
| User behavior understanding | Instrumentation easy to add; PMs get real usage data; fast iteration behind flags | Scope creep; feedback arriving late; product-market fit guessed at | Event-level KPIs for customer outcomes visualized beside system cost |

## ch-22 — Where to Go from Here {#ch-22}

- Tightened definition: you have observability if you can understand any novel system state by arbitrarily slicing high-cardinality/high-dimensionality telemetry and applying the core analysis loop to isolate causes — without predicting the need in advance.
- Predictions (from 2022): OTel becomes the de facto starting point with auto-instrumentation on par with proprietary agents; backend switching trivializes; **code without custom instrumentation becomes as unthinkable as code without comments**; observability absorbs both RUM (aggregate real-user data you can't decompose per user) and synthetic monitoring (pre-scripted paths → tag test traffic in telemetry instead); build pipelines get faster with feedback loops connecting code-writing to production behavior.
- Companion reading it defers to: Google SRE book, Hidalgo's *Implementing Service Level Objectives*, Boten's *Cloud Native Observability with OpenTelemetry*, Parker et al. *Distributed Tracing in Practice*.

---

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Diff adds an endpoint, queue consumer, cron/batch job, or external call with no span/event emission | Add instrumentation in the same diff: auto-instrumented span + custom attributes for the business logic it touches | Bugs are cheapest to debug while intent is fresh; uninstrumented paths are invisible in production | ch-7, ch-11 |
| PR review question unanswered: "how will we know this change works (or misbehaves) in production?" | Block until the diff carries telemetry that would answer it | Instrumentation is a review deliverable, like tests | ch-11 |
| Code emits multiple free-text log lines for one request/unit of work | Consolidate into one structured (key=value/JSON) event per unit of work, carrying request/trace ID | Unstructured narrative logs are machine-unusable; per-unit events enable slicing and trace-stitching | ch-5 |
| Instrumentation truncates/omits user ID, request ID, build ID, or similar "too unique" fields | Keep the high-cardinality field | High-cardinality fields are the most useful debugging keys; you can bucket down later, never up | ch-1 |
| New telemetry added as a custom metric with tags for an application-level question (per-user, per-request behavior) | Emit it as an event/span attribute instead; reserve metrics for non-request-scoped or exact-count values | Pre-aggregation fixes granularity at write time and can't answer post-hoc questions; tag cardinality explodes TSDBs | ch-5, ch-7, ch-16 |
| Alert proposed on a potential cause (CPU%, memory%, thread count, disk%) that pages a human | Replace with an SLO/symptom-based alert; keep the resource signal as a non-paging warning/correlation input | Cause-based thresholds have many benign explanations → false positives → alert fatigue → normalization of deviance | ch-12, ch-9 |
| Existing alert fails either test: (1) reliable indicator of degraded user experience, (2) actionable non-rote response exists | Delete the alert | Unactionable alerts distract from the ones that matter; coverage of known-unknowns is false security | ch-12 |
| Failure condition is auto-remediated (autoscaling, failover, retry, restart) | Do not page on it; investigate during business hours | Pages are for emergencies that can't wait; paging on self-healing events burns responders | ch-12 |
| SLO defined over time buckets ("good minute/bad minute", 5-min probe windows) | Define SLIs on individual events (each request good/bad) | One 94%-success minute burns 25% of a four-9s monthly budget; brownouts dominate and need request granularity | ch-13 |
| SLO window specified as calendar month / fixed window | Use a sliding window (~30 days) | Customer memory doesn't reset on the 1st; window resets destroy trend data for burn decisions | ch-13 |
| Burn-alert forecast extrapolates a baseline window >4× forward (e.g., 15 min → 3 days) | Keep lookahead ≤ ~4× baseline; run alerts at multiple timescales; extrapolate proportionally (rate × expected traffic), not linearly | Larger ratios flap or lag; linear counts are fooled by traffic cycles | ch-13 |
| Sampled event emitted without its in-effect sample rate; or sampling decision made per-service by local RNG | Record `sampleRate` in every kept event; derive keep/drop from a propagated trace/sampling ID | Reconstruction must weight by rate; independent decisions break traces | ch-17 |
| Uniform 1/N sampling configured where errors/rare keys/low-volume tenants matter | Use key-based or target-rate dynamic sampling (errors ≫ successes; rare keys kept) | Constant probability discards exactly the outliers debugging needs | ch-17 |
| Sampling rule depends on latency or status (known only at completion) but is evaluated at trace start | Use tail/buffered (collector-side) sampling for outcome-dependent rules; head-based only for static fields | Head decisions can't see outcomes; independent tail keeps orphan spans without context | ch-17 |
| Debugging plan starts from "check the usual dashboards / it's probably X again" | Debug from first principles via the core analysis loop: verify change → diff anomaly vs baseline across all dimensions → isolate → repeat | Pattern-matching finds symptoms of past problems and feeds confirmation bias; the loop needs no prior system knowledge | ch-8, ch-2 |
| Incident retro proposes a new runbook page + custom dashboard for a novel failure | Invest in instrumentation and query capability instead; keep runbooks to ownership/escalation basics | Novel failures rarely recur; exhaustive runbooks go stale (wrong docs are worse than none); instrumentation is live documentation | ch-8, ch-3 |
| Deep investigation of code logic attempted inside the observability tool (line-level verbose events) | Use observability to locate (service, hop, build, cohort); reproduce locally under debugger/profiler for the why | Order-of-scale mismatch; line-level emission costs 1–10× the system | ch-11 |
| Team operates own infra (DBs, brokers, VMs) with only app-level events | Keep metrics-based monitoring for infrastructure you operate; capture CPU/memory/disk alongside events | Monitoring fits slow-changing predictable systems; resource ceilings warn of code problems | ch-9 |
| Post-deploy resource curve jumps (memory ×3, CPU ×2, disk-write spike right after release) | Treat as a code-change warning; compare old vs new build ID side by side before users notice | Higher-order infra metrics are early-warning exemptions to "events over metrics" | ch-9, ch-11 |
| New backend/data-store choice for telemetry requires predefined schema, per-column indexes, or pre-aggregation | Reject for observability workloads; require seconds-fast, index-free, arbitrarily wide, real-time-queryable storage (columnar/time-segmented) | Schemas require predicting questions; indexing everything costs more than the data; TSDBs cardinality-explode | ch-16, ch-5 |
| Programmatic column/key names embedding variable data (`timestamp_20210617=true`) | Put variable parts in values, constants in keys | One-use columns defeat columnar amortization | ch-16 |
| Observability pilot scoped to a small, healthy, low-risk service | Start on the worst pain point (flaky, paging, mysterious service) | A quiet pilot yields all the cost and none of the proof; adoption needs early wins | ch-10 |
| Plan to build an in-house o11y platform because vendor price looks high vs "free" OSS | Compute full TCO (hardware + dedicated engineers + recruiting + opportunity cost) before deciding; default is buy + build integration layer over an API-rich product | Real ELK example: "free" cost >2× the commercial quote | ch-15 |
| Instrumentation written against a vendor's proprietary agent/SDK | Instrument with native OTel; isolate vendor specifics in distros/exporter config | Switching backends becomes config, not re-instrumentation | ch-7, ch-15 |
| Deploy batches many engineers' changes; release == deploy | Ship one coherent change per merge; decouple release from deploy with flags; track code-written→in-production time as the team health metric | Batched deploys are the top cause of day-long untangles; elite teams gain speed and quality together | ch-11, ch-3 |
| CI tests dismissed as "just flaky" with no runtime telemetry | Trace CI runners/tests with dimensions (host, worker label, commit, suite, config) before blaming test code | Slack: config dimensions, not test code, drove 15%→<0.5% flake rates | ch-14 |
| Telemetry needs routing to multiple backends, PII redaction, retention tiers, or spike buffering, handled ad hoc in app code | Introduce a pipeline (receiver→buffer→processor→exporter; OTel Collector/Kafka), monitored for freshness with tagged synthetic events | Centralizes routing/compliance/quality; app changes stop being required per backend | ch-18 |
| AI/anomaly-detection product proposed to auto-diagnose incidents in a frequently deployed system | Let machines diff/sort/detect; keep humans assigning meaning; automate the core analysis loop instead | Every deploy is an anomaly; AI baselines mis-size → noise or silence | ch-8 |
| Adding shard/partition/new datastore/microservice split when a boring stack still fits | Don't add unnecessary complexity; choose boring technology until scale/reliability/speed forces otherwise | Well-understood edge cases beat novel infrastructure; Parse's speed-first choices were right *and* had to be paid for later knowingly | ch-3 |

## Anti-patterns

- **Three-pillars observability** — buying/gluing separate metrics, logging, and tracing tools and declaring observability. Cue: engineers copy-paste IDs between three UIs, carrying context in their heads (tool-hopping). ch-1, ch-2, ch-19
- **Dashboard pattern-matching / hero debugging** — diagnosis by resemblance to past outages; best debugger = longest-tenured. Cue: "it's probably Redis again"; troubleshooting knowledge that doesn't transfer to an unfamiliar stack; the hero paged on their honeymoon. ch-2, ch-3
- **Runbook-per-failure-mode** — maintaining a living document of every error and resolution. Cue: runbooks stale within a quarter; retro action items are mostly new dashboards/runbook pages for failures that never recur. ch-8
- **Cause-based threshold alerting** — CPU/memory/thread alarms paging humans. Cue: "ignore that alert, it does that sometimes" (normalization of deviance); alert volume grows after every incident. ch-12
- **Alert-fatigue productization** — adopting AIOps alert grooming instead of deleting unactionable alerts. Cue: budget line for alert-noise management. ch-12, ch-8
- **Pre-aggregation as telemetry** — recording only metrics aggregates of app behavior. Cue: investigation dead-ends at "we can't break that number down by user/host/build." ch-5
- **Cardinality flinching** — dropping user IDs/hostnames from telemetry to protect the metrics bill. Cue: instrumentation guidelines forbidding unique IDs as tags. ch-1, ch-16
- **Glass-castle production** — deploy freezes, Friday bans, reflexive rollbacks in lieu of understanding. Cue: rollback is the only incident response ever exercised; staging investment exceeds production tooling investment. ch-3, ch-11
- **Broken-trace sampling** — per-service independent sampling decisions. Cue: traces with orphan children or missing parents; error spans with no upstream context. ch-17
- **Good-minute/bad-minute SLIs** — time-bucketed SLO math on stringent targets. Cue: single evaluation windows burning double-digit % of monthly budget. ch-13
- **Sunk-cost tooling loyalty** — refusing adoption because of years invested in the old stack. Counter: tee existing streams, mirror old dashboards as queries. ch-10
- **Free-software TCO blindness** — in-house ELK/Prometheus estate with uncounted hardware and headcount. Cue: nobody can state the platform's annual cost. ch-15
- **One-use columns** — telemetry keys with embedded timestamps/IDs. Cue: schema browser shows thousands of columns with one row each. ch-16

## Applicability & exemptions

- **Monitoring stays correct for systems you operate**: infrastructure, runtimes, capacity ceilings — slow-changing, predictable, operator-perspective. The book explicitly does not tell you to delete infra monitoring; IaaS-provider metrics for CPU/memory/disk should even be pulled *into* your o11y data as early-warning code signals. The less infrastructure you operate (PaaS/serverless), the less monitoring you need — scope by operational responsibility, not fashion. (ch-9)
- **Metrics remain right** for exact unsampled counts, process-wide periodic values, aggregate multi-year performance trends (neither o11y nor BI serves those), and warning-signal use. (ch-7, ch-9, ch-20)
- **Simple/monolithic, stable systems**: dashboard+runbook+retro workflows genuinely work where novel failures are rare; observability still helps (tracing time-spent, user-perspective reproduction) but is nonnegotiable only past the complexity threshold — many services, polyglot storage, elastic infra, platform/multitenant dynamics, or when most questions concern user behavior and code interactions rather than component failures. (ch-1, ch-3)
- **Observability is not a code-logic debugger**: don't demand line-level event emission; locate with o11y, explain with a debugger/profiler. (ch-11)
- **Sampling is optional at low volume**: keeping 100% of events is fine (and simplest) until cost pressure; conversely constant-probability sampling is fine for genuinely uniform high-volume traffic. (ch-17)
- **Predictive burn alerts degrade above ~99.95% targets**: budgets empty in minutes; rely on automated remediation and report-only burn tracking there. (ch-13)
- **Exact-accuracy workloads** (billing, compliance reporting, long-lived user journeys measured in days/weeks) belong in BI/warehouse tooling, not the o11y store — fast-and-99.5% is the o11y trade, verboten for money. (ch-20)
- **Buy-vs-build reverses** if observability tooling *is* your core competency, or you have Facebook-scale economics; and even buyers should build the integration/convention layer. (ch-15, ch-16)
- **Runbooks aren't banned**: per-service ownership, escalation, dependency, and jump-off-query docs are expected; only the exhaustive error-catalog runbook is condemned. (ch-8)
- **SLO alerting presumes debuggability**: adopting symptom-based alerts without rich event telemetry yields alarms that say "users hurt" with no path to why — sequence instrumentation before deleting old alerts, and expect a trust-building period running both (Honeycomb only deleted traditional alerts after SLO alerts beat them in real incidents). (ch-12)
- Authors are vendor employees (Honeycomb); architecture guidance (ch-16) and buy-recommendation (ch-15) are argued but not disinterested — weigh accordingly.

## Candidate lexicon rows

| new endpoint/queue/external call in diff, no telemetry | **Instrument at write time** — uninstrumented code paths are invisible in production and bugs cost most after intent fades | Does this diff emit a span/wide event for the work it adds, with business-logic attributes? | should | write | src: observability-engineering ch-11 |
| multiple log lines per request; free-text logs | **One wide event per unit of work** — unstructured multi-line narratives can't be sliced, grouped, or traced | Can this request's full story be queried as a single structured record with a trace ID? | should | write | src: observability-engineering ch-5 |
| telemetry drops user/request/build IDs as "too unique" | **Keep high cardinality** — unique IDs are the most valuable debugging keys; you can bucket down later, never up | Is a high-cardinality field being omitted or truncated to appease a metrics backend? | should | review | src: observability-engineering ch-1 |
| new per-user/per-request question answered with a tagged metric | **Events over metrics for app behavior** — pre-aggregation fixes granularity at write time; tag cardinality explodes TSDBs | Will someone need to decompose this number by user/host/build during an incident? | should | plan | src: observability-engineering ch-5 |
| paging alert on CPU/memory/disk/thread threshold | **Page on symptoms, not causes** — resource thresholds have benign explanations; false positives breed normalization of deviance | Does this alert reliably indicate degraded user experience AND have a non-rote response? Delete if not | should | review | src: observability-engineering ch-12 |
| SLO math on time buckets or fixed calendar windows | **Event-based SLIs on sliding windows** — one bad minute burns 25% of a four-9s budget; customer memory doesn't reset on the 1st | Is each request judged good/bad individually over a trailing ~30-day window? | should | plan | src: observability-engineering ch-13 |
| sampled event without rate; per-service sampling RNG | **Propagate and record sampling decisions** — reconstruction needs per-event rates; independent decisions break traces | Does every kept event carry its sampleRate, and does the keep/drop decision ride the trace ID? | blocker | write | src: observability-engineering ch-17 |
| incident debugging starts from "the usual suspect" dashboard | **Core analysis loop over pattern matching** — diff anomaly vs baseline across all dimensions; needs no prior system knowledge | Are we following data stepwise, or confirming a hunch from past outages? | should | review | src: observability-engineering ch-8 |
| retro proposes new runbook page + dashboard for a novel failure | **Instrumentation is the documentation** — novel failures rarely recur; error-catalog runbooks go stale and mislead | Would richer telemetry have answered this faster than a runbook will next time? | judgment | plan | src: observability-engineering ch-8 |
| infra you operate covered only by app events; or post-deploy CPU/memory jump ignored | **Monitoring keeps the systems beat** — resource metrics stay right for infrastructure health and as early warnings of bad deploys | Do we watch CPU/memory/disk beside events, and compare old vs new build ID after deploys? ↔ release-it ch-17 (transparency/OpsDB) | should | plan | src: observability-engineering ch-9 |
| telemetry store choice needs predefined schema or per-column indexes | **No privileged dimensions** — observability queries must be seconds-fast on any field without pre-declared indexes or aggregation | Can this backend answer an arbitrary high-cardinality group-by in seconds on data ingested seconds ago? | should | plan | src: observability-engineering ch-16 |
| new shard/microservice/datastore while a boring stack still fits | **Choose boring technology** — well-understood edge cases beat novel infrastructure; add complexity only when scale/reliability forces it | What problem does this addition solve that the boring option cannot? ↔ agrees release-it (simplicity reduces crack propagation) | judgment | plan | src: observability-engineering ch-3 |
