# Release It! — distilled

> **Source**: Michael T. Nygard, *Release It! Design and Deploy Production-Ready Software*, Pragmatic Bookshelf, 1st ed 2007 (ISBN 978-0-9787392-1-8) · extracted from `../Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory that catalogs *production failure modes* as named, pattern-matched antipatterns (Integration Points, Cascading Failure, Blocked Threads, Unbounded Result Sets…) with a paired catalog of stability countermeasures (Circuit Breaker, Bulkheads, Timeouts, Fail Fast, Steady State, Test Harness). Also the primary feed for an Observability lexicon: ch-17 specifies exactly what to log, which metrics to expose, how to structure log lines for humans and grep, and how to wire status/expectation data into an operations database. Complements observability-engineering (which covers modern telemetry pipelines) with the *application-side* design rules, and DDIA (which covers data-system internals) with the operations/deployment view.

## Chapter map

- ch-1 — Introduction: why "passing QA" ≠ production-ready; design decisions are financial decisions.
- ch-2 — Case study, the exception that grounded an airline: how one uncaught `SQLException` cascades enterprise-wide.
- ch-3 — Introducing stability: definitions (impulse/stress/strain, longevity), cracks propagate, design failure modes deliberately.
- ch-4 — Stability antipatterns: the 11-item failure-mode catalog with mechanisms and detection cues.
- ch-5 — Stability patterns: the 8-item countermeasure catalog (Timeouts, Circuit Breaker, Bulkheads, Steady State, Fail Fast, Handshaking, Test Harness, Decoupling Middleware).
- ch-6 — Stability summary: at production scale, astronomically unlikely coincidences happen daily.
- ch-7 — Case study, trampled by your own customers: launch-day session explosion from impolite traffic.
- ch-8 — Introducing capacity: definitions, constraint theory, scaling modes, "CPU/storage/bandwidth are cheap" myths.
- ch-9 — Capacity antipatterns: resource pool contention, session bloat, chatty remote calls, handcrafted SQL, DB eutrophication.
- ch-10 — Capacity patterns: connection pooling, careful caching, precomputed content, GC tuning.
- ch-11 — Networking: multihomed servers, explicit bind addresses, routing, virtual IPs.
- ch-12 — Security: least privilege, configured-password handling.
- ch-13 — Availability: costing the nines, precise SLA definitions, load balancing, clustering.
- ch-14 — Administration: QA/production topology parity, config-file design, start-up/shutdown, scriptable admin.
- ch-15 — Design summary: checklist recap of Part III.
- ch-16 — Case study, Black Friday outage: diagnosing blocked threads via transparency; component-level restart beats reboot-the-world.
- ch-17 — Transparency: the four perspectives, logging rules, monitoring systems, SNMP/JMX, what to expose, operations database, feedback processes. **Primary observability feed.**
- ch-18 — Adaptation: adaptable code and enterprise architecture, protocol versioning, no integration databases, zero-downtime (expand/rollout/cleanup) deployments.

## ch-1 — Introduction {#ch-1}

- Aim for production, not QA. Passing functional tests says nothing about the next 3–10 years of life under real traffic. "Design for production" is software's analog of design-for-manufacturability: designers and operators must stop living in different worlds.
- **Early decisions are the least informed and the hardest to reverse**: system boundaries and decomposition crystallize into team structure, funding allocation, and program-management structure. Team assignments are the first draft of the architecture (Conway's law).
- Design and architecture decisions are **financial decisions**:
  - Never trade a one-time development cost for a recurring operational cost.
  - At $100k/hr downtime cost, the gap between 98% and 99.99% uptime is >$17M/year.
  - A $5k automated build-and-release system that avoids release downtime returns ~4,000% ROI over five years.
- Two architect archetypes:
  - *Ivory-tower*: abstraction-first, decrees from afar, end-state visions of "ringing crystal perfection"; the resulting system admits no improvement.
  - *Pragmatic*: rubs shoulders with coders; thinks about memory, bandwidth, CPU bonding, "how do we deploy without rebooting the world?", "what metrics do we collect and how do we analyze them?", and which components will need replacement as stress factors change. Be the second kind.

## ch-2 — Case study: the exception that grounded an airline {#ch-2}

Scenario → lesson, compressed (≤10 lines):

1. Routine, correctly executed database failover moved the virtual IP; existing TCP connections silently died.
2. Oracle JDBC connections still created `Statement`s (driver checks only its own internal state); executing or closing them threw `SQLException`.
3. In the `finally` block, `stmt.close()` threw first → `conn.close()` was skipped → connection leaked from the pool.
4. After 40 leaks per app server, every request thread blocked forever in `connectionPool.getConnection()` (pool configured to block indefinitely).
5. Callers (check-in kiosks, IVR) used RMI/EJB, which by default **cannot time out** → all 40 of their request threads blocked in `SocketInputStream.socketRead0()`.
6. Entire check-in system down 3 hours at East Coast morning peak; operational ripple until 3 p.m. next day; stranded-passenger coverage on national TV; overtime, missed FAA metrics.

**Lessons**:
- The JDBC spec allows `Statement.close()` to throw — your cleanup code has to survive its own cleanup calls.
- Bugs cannot be eliminated, only survived. The design question is not "how do we prevent this bug forever" (code review would only have caught it if a reviewer knew Oracle driver internals) but "how do we keep one system's bug from taking down everything else."
- Missed **crack-stoppers**, any one of which would have contained the failure: pool checkout timeout; pool growing new connections when exhausted; socket timeouts on RMI (`Socket.setSoTimeout` via a socket factory); an HTTP web service instead of RMI (HTTP clients can set timeouts); partitioned CF service groups (Bulkheads); request/reply message queues (caller must design for no-reply); tuple-space lookup instead of synchronous query.
- Tight coupling amplifies: the more tightly coupled the architecture, the further a single coding error propagates. Loose coupling acts as a shock absorber.
- Incident discipline: restoring service takes precedence over investigation; collect diagnostic data via pre-scripted automation (thread dumps, DB snapshots) so data capture doesn't prolong the outage; post-mortems are murder mysteries where the corpse is gone — logs and dumps are all you get.
- Thread dumps are the debugging gold standard for hangs: they reveal thread pools, third-party libraries, protocols, and the exact blocked call, even without source access.

## ch-3 — Introducing stability {#ch-3}

Definitions (retrieval keys):

- **Transaction** — abstract unit of work processed by the system (not a DB transaction; "Customer Places Order" spans pages and external integrations). A *dedicated system* processes one transaction type; a *mixed workload* combines types.
- **System** — the complete, interdependent set of hardware, applications, and services needed to process transactions end to end.
- **Resilient system** — keeps processing transactions under transient impulse, persistent stress, or component failure. What matters is that *users can still get work done* — a hung process counts as down.
- **Impulse** — rapid shock (flash mob on a product page, Slashdotting, 12M messages dumped into a queue at midnight).
- **Stress** — force applied over time (a credit-card processor that responds slowly for hours).
- **Strain** — the deformation stress produces *elsewhere*: higher RAM usage on web servers, excess I/O on the database, effects at a distance. Stress in one place produces strain in another because layers are coupled.
- **Longevity** — the system runs without restart for at least one deployment cycle. Longevity bugs = memory leaks + data growth:
  - Never seen in dev (server lifetime ≈ one sitcom episode) or in standard load tests (vendors charge by the hour; nobody runs a week).
  - Only **longevity tests** catch them: continuous low-level load for days/weeks, *including slack periods* overnight — the slack is what exposes connection-pool and firewall idle timeouts.
  - If you can't afford a full environment, longevity-test the important parts and stub the rest; otherwise production becomes your longevity lab.
- **Failure modes & crack-stoppers** (via Chiles, *Inviting Disaster*): every system has cracks; under stress they propagate. Accepting that failures will happen lets you design *crumple zones* — decide what is indispensable and build failure modes that keep cracks away from it. Deny failure and you get emergent, dangerous failure modes instead.
- **Cracks propagate / chain of failure**: a failure at one point *increases the probability* of the next failure — the events are coupled, not independent, which is why post-hoc "one-in-a-billion" chains happen. Each step of the chain can be accelerated (tight coupling, high complexity) or stopped (crack-stoppers).
- The paranoid checklist to run at every external call, every I/O, every resource acquisition:
  - What if I can't make the initial connection?
  - What if it takes ten minutes to connect?
  - What if the connection drops mid-stream?
  - What if I get no response at all?
  - What if the response takes two minutes?
  - What if 10,000 requests arrive at once?
  - What if the disk is full when I try to log the error?
- Brute-force exhaustive analysis is impractical outside life-critical systems — that's why the pattern/antipattern catalogs of ch-4/ch-5 exist; the patterns interact (Timeouts feed Circuit Breaker; Bulkheads limit Chain Reactions; antipatterns mutually aggravate).

## ch-4 — Stability antipatterns {#ch-4}

Master catalog (mechanism → detection cue → countermeasure):

| # | Antipattern | Mechanism | Detection cue | Countermeasures |
|---|---|---|---|---|
| 4.1 | **Integration Points** | Every socket/process/pipe/RPC/DB call can and will hang; #1 killer of systems | Threads blocked in socket read; hang at traffic ramp; works in QA | Circuit Breaker + Decoupling Middleware; Timeouts; Test Harness |
| 4.2 | **Chain Reactions** | One node dies → survivors absorb its load → same defect (leak/race) fires faster on each | Accelerating crash intervals across a homogeneous farm | Fix the defect; Bulkheads to partition; Circuit Breaker in callers |
| 4.3 | **Cascading Failures** | Crack jumps layers, usually via drained resource pools or aggressive retries | Caller's pool exhausted after callee slows; caller CPU 100% retrying/logging | Timeouts + Circuit Breaker (the essential pair) |
| 4.4 | **Users** | Every session eats RAM; bots/scrapers without cookies mint a session per request; buyers hit every integration point | Session count ≫ real users; sessions from no-cookie clients; same-row DB deadlocks | Minimal session state, `SoftReference` payloads, cookie gateway, per-IP Circuit Breaker, block scrapers |
| 4.5 | **Blocked Threads** | Interpreter alive, all request threads waiting on impossible outcomes — the proximate cause of most failures | Thread dump: all threads in same blocking call (pool checkout, socket read, `synchronized`) | Timeouts on everything; proven concurrency libs; interrogate vendor libs with a Test Harness |
| 4.6 | **Attacks of Self-Denial** | Your own org creates the flash mob: deep-link mass email bypassing the CDN, exact-time offers, Fight Club bugs | Traffic spike exactly at a promo time; thousands of threads serialized on one hot item's lock | Talk to marketing; static landing pages; dedicated promo cluster (Bulkheads); shared-nothing or optimistic-locking fallback |
| 4.7 | **Scaling Effects** | Patterns safe at QA's 1:1 ratios break at production ratios; point-to-point comms cost O(n²) connections | Dev/QA has 1–2 instances where prod has dozens; connection counts grow with square of instances | Design out (can't test out): pub/sub or multicast instead of point-to-point; make shared resources redundant and nonexclusive |
| 4.8 | **Unbalanced Capacities** | Front end can always overwhelm back end (3,000 threads vs. 450 vs. 25) | Front:back thread ratio in prod ≫ ratio in QA; traffic-pattern change floods one transaction type | Front: Circuit Breaker. Back: Handshaking, Fail Fast, Bulkheads. Test 2× peak at the most expensive transaction |
| 4.9 | **Slow Responses** | Slower than refusing: ties up resources at both ends; from GC thrashing, leaks, TCP stalls | Latency climbing at constant load; users hitting Reload multiplying traffic | Track own response time; Fail Fast when above SLA; hunt leaks and contention |
| 4.10 | **SLA Inversion** | System availability = joint probability across every dependency; 5 deps at 99.9% caps you at 99.5% | Promised SLA exceeds worst dependency's SLA (incl. DNS, SMTP, MQ, SAN) | Decouple; degrade gracefully; write SLAs per feature, pass-through for third-party-backed features |
| 4.11 | **Unbounded Result Sets** | Query returns 10M rows where 1,000 expected; caller loads all into memory and dies | `SELECT` without LIMIT/`setMaxResults`; ORM association traversal; dev-sized test data | Limit at the caller; production-sized test data; limits in every application-level protocol |

### 4.1 Integration Points — details

- **Slow failure ≫ worse than fast failure.** "Connection refused" returns in milliseconds and is handled; a dropped ACK blocks the calling thread inside the kernel for the OS TCP timeout — Linux `tcp_retries2=15` ≈ 20 min, HP-UX ≈ 30 min. A read on an established socket can block *forever* unless `setSoTimeout` was called.
- The **listen queue** is the worst place to be: SYN sent, no SYN/ACK yet — the caller's `open()` blocks in the kernel for minutes.
- **Firewall idle-connection drop ("the 5 a.m. problem")**: firewalls expunge idle connections from their state table (commonly ~1 hr) *without notifying either endpoint*; subsequent packets are silently dropped (no RST, no ICMP). The TCP stack faithfully retransmits for 20–30 minutes.
  - A LIFO connection pool leaves 39 of 40 connections idle overnight → all go stale → total site hang at the morning traffic ramp.
  - Fixes: DB-side keepalive (Oracle dead connection detection pings the client, resetting the firewall's last-packet clock); pool-side idle-time eviction; socket timeouts.
  - Debugging required peeling the abstraction: thread dumps → tcpdump → the *absence* of reply packets was the clue. Keep packet capture non-interactive on production; analyze elsewhere.
- `java.net.URLConnection.getInputStream()` is one big blocking call with no timeout parameters (pre-Java 5). Use an HTTP client that offers separate connect and read timeouts (e.g., Apache HttpClient).
- **Vendor client libraries** are the worst stability offenders: internal resource pools that block forever, hidden sockets with no timeout knobs, `synchronized` callback methods that can deadlock request threads (a subclass may add `synchronized` a superclass/interface lacks — a Liskov violation Java permits). Test them deliberately: 20 parallel identical calls against a devious Test Harness; if unfixable, wrap in an external worker pool with a time limit — and lobby the vendor.
- Every integration point will eventually fail, the failure will arrive as a protocol violation / hang / slow response rather than a tidy error, and debugging it means dropping below the abstraction (packet sniffers).

### 4.2 Chain Reactions — details

- Arithmetic: 8-node farm at 12.5% each; one dies → survivors at ~14.3% (a 15% load increase each). In a 2-node cluster the survivor's load *doubles*.
- If the original death was load-related (memory leak, obscure race), each survivor is now *more* likely to hit the same defect: crash intervals shrink geometrically (search-farm war story: 5–6 min gap, then 3–4, then seconds).
- Only real cure is fixing the defect; Bulkheads split one chain reaction into slower, separate ones; the calling layer needs Circuit Breakers because a chain reaction below becomes a cascading failure above.

### 4.3 Cascading Failures — details

- The crack "jumps the gap" between layers via some transmission mechanism — usually a resource pool drained while waiting on the failed layer; every thread that touches it sticks; Integration Points without Timeouts is a guaranteed path here.
- "Hammer time" variant: caller treats every error as transient and retries aggressively → 100% caller CPU spent calling and logging against an already-sick callee.
- Cascading failures are the #1 crack *accelerator* just as integration points are the #1 crack *source*; preventing them is the key to resilience.

### 4.4 Users — details

- Sessions are the Achilles heel of web apps: 100 bytes of cookieless HTTP request → kilobytes of server-side session for the full timeout period. Sessions are guaranteed to outlive their users.
- Memory truths: low memory breaks logging (log-event objects can't be allocated — argument for *external* monitoring), and `malloc` failures inside native code (Type 2 JDBC drivers) crash the JVM outright.
- Keep whole search results and other bulky objects out of sessions; requery per page. Where large objects must live in sessions, hold them via **`SoftReference`**: the GC reclaims all softly reachable payloads before throwing `OutOfMemoryError`; callers must handle a null payload (recompute or degrade).
- *Expensive users*: buyers hit credit-card auth, tax, address verification, inventory, shipping. Load-test at 2–3× the expected conversion rate — but not 100%, which is a stability test, not a capacity plan (you'd buy 10× the hardware).
- *Unwanted users*: misconfigured proxies replaying URLs; screen scrapers and shopbots ignoring cookies and `robots.txt` (which only polite robots honor); session floods that also trigger hot-row deadlocks (100k "new logins" all updating the same last-login row). Defenses: network-level blocking (ARIN lookups; expire old blocks), CDN gateway pages, terms-of-service + lawyers — pest control, not cures.
- The **spider trap** war story: randomly generated self-links meant to trap an indexer → the search engine (which always has more bandwidth than you) gorged on it → $10k+ bandwidth overage. An elaborate self-DDoS.
- Malicious users: mostly script kiddies; DDoS against the application layer targets session management first; per-source-IP circuit breakers limit damage; note that naive per-IP connection limits (15/min) misfire on AJAX apps.

### 4.5 Blocked Threads — details

- The most common system failure mode in interpreted/VM languages is not a crash but "naval-gazing": the interpreter runs, every request thread waits for Godot.
- Why testing can't save you (four factors): error conditions create untestably many permutations; unexpected interactions introduce deadlocks into "safe" code; hang probability rises with concurrency; developers never test at 10,000 concurrent requests.
- Never `synchronize` domain-object methods: in-memory coherence is meaningless with >1 server, and it serializes request threads. Find a way for each thread to get its own copy.
- Nothing at the call site reveals blocking: `globalObjectCache.get(key)` looked innocent; a subclass (`RemoteAvailabilityCache`) held the lock while making a remote call to an undersized inventory system — when the back end died, one thread blocked inside `create()` and every other thread queued on the synchronized `get()`. "No one designed this failure mode in, but no one designed it out either."
- Double-checked locking does not work in Java; use proven `java.util.concurrent` primitives, always in their timeout forms; don't roll your own connection pool (safe + performant + instrumented is far harder than it looks).

### 4.6 Attacks of Self-Denial — details

- Any special offer for 10,000 users reaches millions: deal-hunter communities replicate coupon codes in milliseconds. "Good marketing can kill you at any time" (Paul Lord).
- Canonical incidents: retailer's preorder email with exact open time + deep link that bypassed Akamai → site "gone in sixty seconds"; Amazon's $100 Xbox promo → millions hammering Reload, nothing else sold.
- Machine-induced variant: one shared resource (ATG-style distributed lock manager) + one inadvertently modified popular item → thousands of threads on hundreds of servers serialized on a single write lock. Watch for **Fight Club bugs**: front-end load causing exponentially increasing back-end work.
- Mitigations: advance notice from marketing; static landing pages for the first click; no deep links in mass emails; watch for session IDs embedded in shared URLs; dedicated promo cluster so at most the promo dies (and Fail Fast when it does); fall back from pessimistic to optimistic locking when a lock manager is unavailable.

### 4.7 Scaling Effects — details

- Square-cube analogy: relationships that hold at small ratios break as one side grows. Anywhere you have many-to-one or many-to-few, growth on the many side eventually crushes the few.
- Point-to-point among N instances = O(n²) connections: fine at 2 servers, 4,950 connections at 100. QA (1–2 instances) will never show it — **design it out, you cannot test it out**. Ladder of alternatives: UDP broadcast (bandwidth-wasteful, wakes every NIC) → multicast (only interested servers) → pub/sub messaging (receiver can be offline; costs infrastructure) → message queues. Do the simplest thing that works at your target scale.
- Shared resources (lock managers, cluster managers, common services): fine while redundant and nonexclusive; deadly when exclusive-per-use — contention scales with transactions × clients; saturation → backlog → listen-queue overflow → failed transactions → stale/corrupt data (cache-coherence managers are the nasty case).
- **Shared-nothing** scales best (≈ linear) but complicates failover (sessions must live somewhere); approximate it by reducing fan-in, e.g. paired servers acting as each other's session-failover targets.

### 4.8 Unbalanced Capacities — details

- Short of a crisis, hardware capacity is fixed on any given day (2007 provisioning: weeks); you can't scale up for a one-day spike, so both sides must be *resilient* to a demand tsunami instead.
- Example ratio: 3,000 front-end threads → 450 back-end threads; a marketing event turns a tiny fraction of traffic into a majority hitting one back-end transaction type.
- Sizing the back end to the front end's theoretical max is capital waste (99% idle); instead the front end applies Circuit Breaker, the back end applies Handshaking + Bulkheads + Fail Fast.
- Test discipline: QA's 2-vs-2 topology hides ten-to-one production ratios. As the back-end provider, test at double the highest-ever demand *concentrated on your most expensive transaction* — passing = slow down, maybe Fail Fast, then recover; failing = hangs, empty replies, nonsense replies.

### 4.9 Slow Responses — details

- A slow response ties up resources in caller *and* callee; a fast failure lets the caller move on. Slow responses usually come from excess demand, memory leaks (GC thrash shows as high CPU), or hand-rolled socket code stalling TCP by never draining the receive buffer.
- Slow responses propagate upward layer by layer (gradual cascading failure) and are self-reinforcing on websites: waiting users hit Reload, adding traffic.
- If the system tracks its own response time (moving average over the last ~20 transactions), it can shed load when above SLA: refuse connections or return an error within the protocol — documented, so callers handle it gracefully.

### 4.10 SLA Inversion — details

- Naive availability = product over all dependencies: one no-SLA partner makes your 99.99% promise wishful thinking. Every dependency also rides on transport, DNS, and application-layer availability — check DNS clusters, SMTP, message brokers, SANs.
- Responses: (1) decouple — keep functioning (degraded) when a dependency dies; decoupling middleware where possible, circuit breakers everywhere; (2) write SLAs per feature, not per system — features with no third parties get your max; features with third parties get at most the vendor's SLA, further degraded by your own failure probability. "When calling third parties, service levels only decrease."

### 4.11 Unbounded Result Sets — details

- Pattern: send query, loop over the result set turning rows into objects. Works until the table has 10M rows.
- **Black Monday** war story: a JMS message table meant to hold <1,000 rows had accumulated 10M+; every app-server start ran an unlimited `SELECT ... FOR UPDATE` on it, went OOM inside native JDBC code, crashed, rolled back the row locks — handing the cliff to the next starting server. A 100-instance farm couldn't hold 25% capacity for a day.
- Applies to DB queries, distributed objects, web services, AJAX endpoints; master→detail traversals ("customer's orders") are the slow-fuse case — dev data never triggers it, year-two production data does. Audit-trail and parent→unbounded-children relationships are automatically suspect.
- SQL limit idioms: `SELECT TOP 15` (SQL Server), `WHERE rownum <= 15` (Oracle), `LIMIT 15` (MySQL/PostgreSQL); ORM `setMaxResults` — but note ORM *associations* don't limit automatically.
- Abstract statement: an unbounded result set is the caller letting the producer dictate terms — a handshaking failure. In any API or protocol the caller states how much it will accept (TCP window; search-API offset+count).

## ch-5 — Stability patterns {#ch-5}

| # | Pattern | Core rule | Counters |
|---|---|---|---|
| 5.1 | **Use Timeouts** | Never wait forever; every socket read, pool checkout, `wait()`, `poll()`, `tryLock()` gets a timeout | Integration Points, Blocked Threads, Slow Responses |
| 5.2 | **Circuit Breaker** | Wrap dangerous ops; count failures; trip open and fail without calling; one trial call after cooldown | Integration Points, Cascading Failures, Unbalanced Capacities, Slow Responses |
| 5.3 | **Bulkheads** | Partition capacity (farms, pools, thread groups, CPUs, VMs) so one failure can't sink everything | Chain Reactions, Attacks of Self-Denial, shared-service SPOFs |
| 5.4 | **Steady State** | For every mechanism that accumulates a resource, another must recycle it; no routine human intervention | Slow Responses, memory leaks, fiddling-induced outages |
| 5.5 | **Fail Fast** | If you can know up front the transaction will fail, fail now — don't burn resources to discard the result | Slow Responses, Cascading Failures; preserves capacity under partial failure |
| 5.6 | **Handshaking** | Server signals readiness; client throttles. Build into custom protocols; approximate via LB health checks | Unbalanced Capacities, Cascading Failures |
| 5.7 | **Test Harness** | A separate, deliberately evil server producing out-of-spec failures at every OSI layer | Finds Integration Point / Blocked Thread / timeout bugs before production does |
| 5.8 | **Decoupling Middleware** | Message-oriented middleware decouples in time and space; synchronous request/reply amplifies shocks | Integration Points, Cascading Failures, Slow Responses, Blocked Threads |

### 5.1 Use Timeouts

- Networks are permanently fallible; **hope is not a design method**. Well-placed timeouts provide fault isolation: someone else's problem stays theirs.
- Language traps: no-arg `Object.wait()`; non-timeout `poll`/`offer`/`tryLock`; vendor APIs that hide the socket and therefore the timeout.
- Any resource pool that blocks threads must have a bounded block time — threads must eventually unblock whether resources appear or not.
- Centralize the acquire/execute/release dance in reusable primitives (QueryObject + generic Gateway, e.g. Spring `JdbcTemplate`) so timeout and error handling live in one place — which also makes retrofitting a Circuit Breaker one change instead of dozens.
- **Retries**: immediate retry will usually fail again — inside a data center the cause persists. Return a fast answer (success, failure, or "queued for later"); queue-and-retry with delay makes the whole system self-healing (store-and-forward, like mail relays). For a synchronous SOA caller, "fast enough" ≈ under 250 ms.
- Timeouts and Fail Fast are two sides of one coin: Timeouts protect you from *others'* failures on outbound calls; Fail Fast reports *your* inability on inbound requests.

### 5.2 Circuit Breaker

- Electrical metaphor with the right moral: the fuse/breaker is a component *designed to fail first*, controlling the overall failure mode. Differs from retries: breakers exist to *prevent* operations, not re-execute them.
- State machine: **Closed** (calls pass; failures counted; success may reset the count) → **Open** when failure count/frequency crosses threshold (calls fail immediately; no real call made) → **Half-Open** after a cooldown timeout (exactly one trial call: success → Closed, failure → Open again).
- Implementation rules:
  - Track failure *types* separately — e.g. a lower threshold for remote timeouts than for connection-refused.
  - Throw a distinct exception type when open so callers can handle "circuit open" differently from an ordinary failure.
  - **Log every state change; expose current state for query and monitoring; chart state-change frequency** — it's a leading indicator of trouble elsewhere in the enterprise.
  - Give operations manual trip and reset controls.
- What the caller does while open is a **business decision** (accept an order without the stock check? proceed without credit-card verification?) — involve stakeholders; the breaker conversation is a better requirements elicitation than asking for a document.

### 5.3 Bulkheads

- Ship metaphor: sealed compartments so one hull breach doesn't sink the vessel. Partition to contain damage and preserve partial functionality.
- Granularities, coarse to fine:
  - Reserved server farms per critical client (dedicated check-in pool for airline kiosks: flight-status floods can't stop boarding).
  - Separate service pools for critical vs. shared consumers of a common service (Foo and Bar both on Baz = hidden coupling; partition Baz).
  - Thread-group partitions inside one process — reserve request threads for admin use so a hung server can still be interrogated and shut down cleanly.
  - CPU binding: a berserk process consumes only its bound CPUs, not the whole host.
  - Virtual machines as movable bulkheads (live migration in seconds; capacity shifted administratively).
- Cost: partitioned pools need more total reserve capacity than one shared pool (no borrowing across partitions); shared pools are efficient but couple tenants. Pick partition boundaries — by caller, by functionality, by topology — where the business impact justifies the reserve.
- In an SOA, one shared service is an enterprise-wide single point of failure: bulkhead it or the whole company halts together.

### 5.4 Steady State

- Every human login to production is an opportunity for unforced error (the "ohnosecond"; the engineer who resilvered the *good* disk from the blank replacement). If the system needs regular crank-turning, admins stay logged in, and fiddling follows. Target: runs indefinitely without intervention — at minimum one full deployment cycle.
- The accumulation rule: whatever fills a bucket (DB rows, log files, cache entries) needs a drain at the same or greater rate.
- **Data purging**: always cut from release 1 ("we've got six months after launch…" — the fuse is lit at launch); symptoms of neglect are steadily rising DB I/O and latency at constant load. Purging must be *application logic*, not DBA scripts: only the app knows its referential integrity and whether it survives items missing from mid-collection (Hibernate: it doesn't, by default).
- **Log files**: rotate by size with bounded count (`RollingFileAppender` and kin; `logrotate` for legacy). A full filesystem starts I/O errors at 90–95% (root reserve) and can turn the logging path itself into a crash loop — the reentrant "universal exception handler" that consumed eight UltraSPARC CPUs logging exceptions about logging exceptions, then OOM'd the JVM. Don't leave logs on production servers; copy to a staging area for analysis (also the answer to compliance retention).
- **In-memory caching**: to a long-running server, memory is oxygen and untended cache sucks it up. Two questions before building any cache: is the key space finite? do cached items change? Unbounded key space ⇒ enforce a size limit; changing items ⇒ invalidation strategy — a periodic time-based flush beats LRU/working-set cleverness nine times out of ten.

### 5.5 Fail Fast

- The worst response is the *slow failure* — burning cycles and clock time only to discard the result (DMV line: wait an hour to be told you filled out the wrong form).
- Mechanism is mundane: a large class of failures are "resource unavailable" and knowable up front. At transaction start, do the software *mise en place*: check out / verify the connections you'll need, check circuit-breaker states around required integration points, then begin work.
- A load balancer with zero healthy servers should refuse the connection, not queue it in hope.
- Input validation: do basic null/format checks in the controller *before* reserving resources — but don't move real domain validation forward; that violates encapsulation.
- **Report system failure (resources unavailable) differently from application failure (bad input)**: a generic "error" reply lets one user's typo-and-Reload trip an upstream circuit breaker.
- Print-renderer case: pre-check every font, image, background, alpha mask and preallocate memory before rendering → software-induced remake rate fell to zero; the one unchecked resource (disk space — the customer's "rock-solid purging process" was one guy deleting files) was exactly where it still failed late, a year in.

### 5.6 Handshaking

- Handshaking = the server protecting itself by throttling its own workload; ubiquitous in low-level protocols (TCP's three-way handshake and receive window), nearly absent at application level.
- HTTP handshakes badly: 503 exists but most clients treat any non-200/302/403 as fatal; CORBA/DCOM/RMI are no better.
- Workable approximations:
  - Web server signals "busy" to the load balancer's periodic health-check page → LB pulls it from rotation. Crude, binary, but real.
  - SOA "health check" query before the actual call: good handshaking, but doubles connection setup/teardown — worth it only when call cost ≫ check cost.
- Best value when unbalanced capacities are producing slow responses: a server that knows it can't meet SLA asks callers to back off. Build handshaking natively into any custom socket protocol. Circuit Breaker is the client-side stopgap for servers that can't handshake — call and track outcomes yourself.

### 5.7 Test Harness

- Integration-test environments verify the system only against dependencies operating *within spec* (and version-lock the whole company: testing against everyone's next release constrains the enterprise to one change at a time). Every system eventually operates out of spec.
- A harness is not a mock: mocks live in-process and conform to the defined interface, so they can only throw defined exceptions; the harness is a **separate server**, free to violate the network transport, protocol, and application layers. "Make your test harness act like a hacker."
- Failure menu to simulate: connection refused; sit in the listen queue until the caller times out; SYN/ACK then no data; nothing but RESET packets; full receive window never drained; connect but never send a byte; packet loss forcing retransmit delays; never ACK (endless retransmits); send response headers then no body; one byte every thirty seconds; HTML where XML was expected; megabytes where kilobytes were expected; refuse all credentials.
- Operational tricks: one "killer server," different misbehavior per port (10200 = accept-and-never-reply; 10201 = reply from /dev/random; …), shared by many applications and developers; make it log requests, because the app under test may die without recording what killed it; frame it as a pluggable server so each application protocol (or perversion of it) is a subclass.
- Supplement, don't replace: unit/acceptance tests verify functional behavior; the harness verifies *non-functional* behavior under out-of-spec abuse — flip its switches while the system is under real load.

### 5.8 Decoupling Middleware

- Done well, middleware integrates *and* decouples: passes data/events between systems while removing each system's specific knowledge of the others. Since Integration Points are the #1 instability source, this is leverage.
- Coupling spectrum (same time+host+process → different time+host+process):
  - In-process method calls → IPC (shared memory, pipes, semaphores) → RPC family (DCE RPC, DCOM, RMI, XML-RPC, HTTP) — synchronous, *vicious cascade amplifiers* → message-oriented middleware (MQ, pub/sub, SMTP, SMS) — decoupled in time, **cannot produce a cascading failure** → tuple spaces (JavaSpaces/TSpaces/GigaSpaces).
- The trade: synchronous is logically simple (credit-card auth answers now; checkout proceeds or not); asynchronous forces design for exception queues, late responses, callbacks, and "what if the answer never comes" — questions that reach business sponsors (acceptable financial risk).
- Unlike every other stability pattern, this one is architectural and nearly irreversible: it ripples through the whole design, products are expensive, and the decision is often made at enterprise level before your project starts. Decide at the last *responsible* moment; learn many architectural styles so you can pick the right one rather than defaulting to three-tier + Oracle.

## ch-6 — Stability summary {#ch-6}

- 10M page views/day × 3 years × 50 assets/page ≈ 547.5 *billion* chances for something to go wrong — more than the count of stars in the galaxy. Astronomically unlikely coincidences happen daily at production scale.
- Antipatterns amplify transient events and accelerate cracks; patterns stop cracks from propagating — they cannot prevent them, nothing can.
- "Count of patterns applied" is never a quality metric; apply with judgment against identified threats. View every external system with suspicion; paranoia is just good thinking.

## ch-7 — Case study: trampled by your own customers {#ch-7}

Scenario → lesson, compressed (≤10 lines):

1. Three-year, 300-person greenfield commerce replatform; every config file written for QA's topology; production configs an afterthought (fixed via a one-property-one-place override layer that also kept prod passwords out of QA and source control).
2. Load-tested for 3 months on daily 12-hour conference calls, 60+ builds, 10× capacity gain (1,200 → 12,000 sessions) — with polite, cookie-handling, happy-path scripts mixing grazers/searchers/buyers.
3. Launch 9:00 a.m.; 250,000 sessions by 9:30; site dead. Marketing hadn't even announced the date — demand estimates weren't the problem.
4. Cause: **noise**. Search engines drove old URLs to session-creating 404s; cookie-less spiders minted up to 10 sessions/second; commercial scrapers rotated IPs and User-Agent strings; 3-year-old PS2-availability shopbots still polled; a Navy-base proxy replayed one URL 4–5×/second.
5. Fixes under fire: CDN gateway page (cookie check + admission-throttle percentage + IP blocklist); fully static home page (had been 1,000+ DB transactions per render, identical for every viewer); session failover disabled (whole carts and search results were serialized per request); six repurposed servers provisioned bare-metal-to-serving in a 36-hour marathon.

**Lessons**:
- Test scripts obey the rules; the real world is "rude, crude, and vile." Hammer deep links cookie-less at 100 req/s before launch — and don't dismiss the resulting crash as "unrealistic."
- "Concurrent users" is fiction; count sessions, and know sessions strictly overestimate users (they persist a full timeout past the last click).
- Build safety devices that cut off bad behavior; without them threads pile into the danger zone like cars in fog.
- **Nothing is as permanent as a temporary fix**: every emergency patch stayed 1–2 years, each costing revenue (throttled customers, lost checkouts on instance death, abandoned personalization) plus a year of remediation instead of features. Two years later the same site handled 4× the load on fewer servers — pure software improvement that could have been designed in.

## ch-8 — Introducing capacity {#ch-8}

- Definitions:
  - **Performance** — how fast one transaction processes (end users only care about *their* transaction; past their expectation, "the system is down").
  - **Throughput** — transactions per time span.
  - **Capacity** — maximum throughput sustainable *at acceptable response time* for a given workload; workload-relative, never one fixed number ("acceptable" is a judgment: ~2 s retail, ms for an exchange, 500 ms search / 30 s confirm for travel).
  - **Scalability** — the throughput-vs-load curve, and/or the mode of growth (horizontal "wide" vs vertical "big").
- **Constraint theory** (The Goal): exactly one constraint limits capacity at a time; work queues or drops in front of it while everything downstream idles.
  - Improving any non-constraint metric does nothing. Once you find the constraint, you can *predict* the effect of changes to it — until the next constraint surfaces.
  - Finding it: distinguish **driving variables** (demand-side, outside your control: requests/s, clock, calendar) from **following variables** (CPU, memory, I/O, bandwidth). The constraint is the following variable whose correlation with demand *breaks down at the knee* of the load chart (correlation ≈0.8–1.0 below, collapse above).
- Interrelations: effects in one layer surface as causes in another (DB I/O drives app-server response time drives web-server memory); slow response in a layer can trigger cascading failure above it — capacity problems become stability problems.
- Scaling modes: horizontal (load-balanced/shared-nothing ≈ linear; clusters sub-linear from coordination overhead; spend incrementally) vs vertical (bigger boxes; chassis ceilings; forklift upgrades; capital up front).
- **Myths** (each hides multiplier effects):
  - *"CPU is cheap"* — 250 ms wasted per transaction × 1M transactions/day = 69.4 CPU-hours/day ≈ 4 extra servers at 80% load factor; app latency also holds web-tier sockets and memory; marginal CPU cost jumps at chassis breakpoints (a high-end chassis alone >$1M — that buys a lot of profiling).
  - *"Storage is cheap"* — storage is a *service*: drives × every server × RAID overhead (RAID 1 = 2×, RAID 5 ≈ 1.2×) × backup windows and tapes; managed storage charges back at up to $7/GB vs <$1 raw. (NAS = appliance on the IP network, cheap entry; SAN = a whole separate Fibre Channel network with mandatory redundancy, CIO-level money.)
  - *"Bandwidth is cheap"* — redundant OC3s run $15–24k/month; broadband users pull ~13× dial-up rates so richer clients consume more of you; 1KB of junk per page × 1M pages/day ≈ 1GB/day of pure waste.
- Summary rules: always hunt multiplier effects; understand cross-layer effects; do the most work when nobody is waiting; put safety limits on everything (timeouts, max memory, max connections); protect request-handling threads; monitor capacity continuously — every release and every traffic shift moves it.

## ch-9 — Capacity antipatterns {#ch-9}

| Antipattern | Mechanism / rule |
|---|---|
| **Resource Pool Contention** (9.1) | Contention begins the instant threads > pool size; 30 threads on 4 connections ⇒ >80% of time spent waiting; throughput knees at threads = pool size. Vicious cycle: contention → longer transactions → more contention → exponential throughput drop. Size pools ≈ request-thread count, but verify one DB node survives the total connection count during failover (20 hosts × 5 instances × 50 conns = 5,000 connections ≈ 5GB DB RAM). Always a bounded checkout timeout; app handles null/exception. Monitor high-water mark, blocked checkouts, create/destroy rates (pools are notoriously opaque — poll JMX). |
| **Excessive JSP Fragments** (9.2) | JSPs compile to classes in the permanent generation; with `-noclassgc` they never unload. 25,000 content-fragment JSPs (promos never retired) → PermGen exhaustion, GC death spiral. Content is not code: static HTML fragments + caching content repository; if trapped, removing `-noclassgc` trades degeneration-to-crash for consistently-slightly-slower. |
| **AJAX Overkill** (9.3) | AJAX shrinks think time (5–10 s between pages → 1–3 s between requests) and multiplies request count. Apply only where it smooths a real single user task (e.g. sending a mail); debounce autocomplete ≥500 ms after typing stops — never on a 250 ms timer; keep session affinity so background requests hit the session's server; return data (JSON), not HTML fragments; never `eval()` JSON (client-side code injection); raise web-tier connection limits (`MaxClients`). |
| **Overstaying Sessions** (9.4) | The 30-minute default timeout is arbitrary and memory-hostile; users leave at the *start* of the dead time. Set timeout to mean inter-request delay + 1σ (≈10 min retail, 5 media, 20 travel). Better: make the session a pure in-memory cache of persistent state — keep *keys*, not object graphs — so it can be dropped and rebuilt anytime, and users resume days later (users don't understand sessions; carts shouldn't vanish over a lunch break). Only truly sensitive data (cards, SSNs) stays session-only. |
| **Wasted Space in HTML** (9.5) | Template-include whitespace is real money: one site's page was one-third newlines; ~200KB waste per page ≈ $15k/yr bandwidth plus web-tier RAM (servers buffer whole responses) plus dial-up seconds. Strip whitespace in an interceptor (CPU cost < RAM+bandwidth cost). `&nbsp;` (5 bytes) beats a 53-byte spacer `<img>` ×12/page ×1M pages = 576MB/day; spacer images also cost cache-revalidation requests. CSS layout can halve table-built page weight, and the stylesheet downloads once instead of per page. Bigger pages hold web-server connections longer — a contended resource users queue on. |
| **The Reload Button** (9.6) | Past ~10 s users hit Reload: browser abandons the socket, server keeps processing the orphan; buffering means the server may not learn until the page is fully built; transactional requests can block or deadlock behind their own twins. No cure but speed — make Reload irrelevant. Never serialize requests by source IP (CDNs/corporate proxies share IPs, and it worsens the pileup); code must tolerate the same user running the same transaction concurrently. |
| **Handcrafted SQL** (9.7) | ORM-generated SQL is predictable and repetitive — a DBA can tune for it; developer SQL is idiosyncratic: joins on unindexed columns, 5+-table joins for one row issued 100× in a loop (the 1+N problem), 8-way UNIONs of table scans. Dynamically assembled WHERE clauses belong in reporting systems, not OLTP. Verify any hand SQL against production-sized (scrubbed or generated) data — toy-data gains evaporate under real query plans. DBA laugh test before production. |
| **Database Eutrophication** (9.8) | Sludge accumulates until "simple" operations take minutes. Index every column targeted by an ORM association — object-property relationships bypass the data architect's FK-index reflex, and dev-sized data can't reveal a table scan (it may even be *faster* there). Keep the DBA involved through development so indexes match real access patterns (agile schemas churn). Partition high-churn tables on a low-cardinality column (e.g. day-of-week) to allow online reorganization as growth estimates prove wrong (1GB audit/year → 1GB/day in one release). Purge/archive history; multilevel storage for old-but-visible data; reports and ad-hoc analysis **never** run on production OLTP — warehouse them (star schema, not OLTP schema). |
| **Integration Point Latency** (9.9) | A remote call ≈1,000× a local call, and "location transparency" doctrine produces chatty remote interfaces designed like local ones. War story: expanding a tree node = 1 + 3N remote calls → 20-minute response from the UK vs <1 s domestic; one coarse "summary object" call fixed it without the multimillion-dollar replica warehouse. A thread parked on a remote reply still holds memory, CPU slices, DB connections, row locks — opportunity cost across all queued work. Expose yourself to remote latency as seldom as possible; batch coarse-grained. |
| **Cookie Monsters** (9.10) | Cookies resend on *every* request (upstream, where users have least bandwidth; parsed 2–4× through web and app tiers). Serialized objects in cookies rot across code versions (`IOException` becomes routine), break referential integrity, and let the client lie — a crafted cart can set prices to $0.01 or bypass promotion rules. Cookies carry small identifiers only (~100 bytes); state stays server-side where clients can't tamper with it. |

## ch-10 — Capacity patterns {#ch-10}

### Pool Connections (10.1)

- Connection setup = TCP handshake + DB auth + session setup ≈ 400–500 ms; only thread creation costs more. Pooling is table stakes — "there's no excuse not to, except doing it poorly."
- One bad connection in a pool of ten causes *more* than 10% of errors: bad connections bounce back to the pool instantly while good ones stay checked out working, so the bad one is disproportionately available. Detect and evict.
- Sizing: undersized → contention (ch-9.1); oversized → DB-server stress. Monitor checkout wait times.
- Checkout models: **per-page** (one connection per page render; deadlock-safe via consistent ordering; more connections held longer), **per-fragment** (each fragment checks out its own; fewer connections, higher throughput; deadlock-prone; no shared transaction context), **hybrid** (fragment-level checkout inside one page-level transaction; safe and modular, but fragments can read sibling fragments' uncommitted writes — miserable to debug).
- Universal rule: bounded checkout time; the caller must know what to do when it gets nothing back.

### Use Caching Carefully (10.2)

- Every application cache gets a configurable **maximum memory** limit, or it steals heap from request processing and the GC thrashes trying to save it — the cache becomes the slowdown.
- Monitor **hit rates**: caching is a bet that build-once + hash/lookup < build-every-time; a low-hit cache loses the bet. Don't cache trivial or rarely reused objects (the content cache full of single-space strings from a per-user boolean conditional).
- Hold cached values via `SoftReference` so the GC can reclaim under pressure — the cache cooperates with memory management instead of fighting it.
- Multilevel (disk-backed) caching when items are huge or the working set exceeds heap, or when misses cross a WAN.
- Every cache needs an **invalidation strategy**: point-to-point notification works to ~10–12 servers; beyond that, pub/sub or multicast — and stagger reloads so every server doesn't stampede the database on the same invalidation.

### Precompute Content (10.3)

- Content rendered a million times a day but changed weekly sits on the wrong side of the multiplier: pay the render cost once *at change time*, serve the stored artifact thereafter. News portals do exactly this — templates pulling precomputed chunks, regenerated every few minutes, each version served thousands of times.
- Precomputing ≠ in-memory caching: precomputed files are warm from the first request and use no heap; in-memory fragment caches punish the first users of a cold server and thrash when the working set exceeds the limit.
- Personalization: precompute the shared ~100KB; "punch out" the ~100 personalized bytes. Apply selectively — high-traffic, low-change-rate pages first.
- War story, the **Profanity Masker**: an ATG droplet that tokenized every product name/description/track/actor field and compared each word against a list of eleven dirty words — on every page view, ~20× per page, 5M pages/day, ~10MB garbage per request — for content published *nightly* under copyright that forbade altering it anyway. Render-time work for change-time (or never) problems.

### Tune the Garbage Collector (10.4)

- Untuned Java at production load spends ~10% of wall time in GC; target ≤2%. Quickest capacity win available — and the exercise usually surfaces memory leaks as a bonus.
- Mechanics: object lifetimes are bimodal — most die in microseconds (eden), few live as long as the process (tenured); tune heap size and generation ratios so ephemeral garbage never reaches tenured space. Observe with `-verbosegc` / jconsole.
- Tuning is **ongoing**: allocation patterns change with every release and every seasonal traffic shift; retune after each major release and across the demand cycle. Only production-like load reveals the right settings.
- **Don't pool ordinary objects**: measured, pool bookkeeping overhead exceeded construction cost (~20.3% vs ~10.2% on one platform). Modern GCs make disposable objects cheap. Pool only what's genuinely expensive: connections, sockets, threads.

## ch-11 — Networking {#ch-11}

- **Multihomed servers** are the data-center norm (production ×2, backup, admin interfaces on separate VLANs — security isolation plus keeping backup floods off production bandwidth). This is the sharpest dev-vs-production difference:
  - Default `ServerSocket` constructors bind *every* interface → production service exposed on the admin network, admin functions on the production network.
  - Always bind to an explicit local address; make bind addresses **configurable**; `InetAddress.getLocalHost()` returns an arbitrary interface on a multihomed box.
  - Bonded/teamed NICs share one IP across interfaces; misconfigured cross-switch bonding causes routing loops.
- **Routing**: multihomed hosts need explicit routes per destination — front-end VLAN to web tier, back-end VLAN to DB, VPN routes to third-party services (never straight over the public Internet). Keep a record per integration point: destination name, address, desired route — the same list becomes the firewall rules.
- **Virtual IPs**: cluster servers (Veritas, ServiceGuard, MSCS) migrate a VIP+MAC between nodes so non-cluster-aware applications get failover; clients connect only to the VIP's DNS name.
  - In-memory state and uncommitted transactions do not migrate. Oracle drivers auto-retry *reads* after failover; writes/inserts/stored procedures cannot be auto-retried — the application must catch the `SQLException`.
  - Any caller through any VIP must be prepared for the next packet to reach a *different node* than the last — an `IOException` to handle distinctly from "destination unreachable," retrying against the new node within Circuit Breaker safety limits.

## ch-12 — Security {#ch-12}

- **Least privilege**: processes run with the minimum privilege for the task — never root/Administrator for application servers. Root-requiring software is an automatic cracker target, and a rooted box (or horizontally scaled farm of them) means reformat-and-reinstall.
  - One OS user per major application: a compromise of "apache" must not reach "websphere."
  - The only classic root excuse is binding ports <1024: put the app behind a load balancer (LB owns port 80; app listens ≥1024) or use Apache-style privilege separation — open the socket as root, then irreversibly downgrade to the app user.
- **Configured passwords**: production DB credentials are the highest-value strings in the enterprise.
  - Keep password files *separate* from other config and *outside* the install directory (install trees get zipped and mailed to vendors, copied between servers, overwritten by upgrades).
  - Owner-read-only, owned by the application user; if using privilege separation, read before downgrade (then the files can be root-owned).
  - Password vaulting (encrypted files) reduces N text files to one key to protect; add file-integrity monitoring (Tripwire-class) because permissions drift.
  - **Disable core dumps on production**: core files and kernel crash dumps contain in-memory passwords; on some platforms an attacker can *force* a memory dump.

## ch-13 — Availability {#ch-13}

- **Gathering requirements**: sponsors asked "how available?" answer "100%" or "five nines" — desire divorced from cost. Reframe financially: each additional "9" ≈ 10× implementation cost and 2× annual operating cost.
  - Worked example: 98% = 864 down-minutes/month ≈ $21.6k/month at $1,500/hr; 99.99% = 4 min ≈ $108. Added lifecycle cost ≈ $98.7k vs ≈ $1.29M saved over five years — *that* arithmetic, not vibes, justifies the target.
- **Documenting requirements**: "the system shall be 99.9% available" is a fight scheduled for a year after launch. Nail down:
  - Availability **per feature/function** (property locator ≠ online reservations ≠ loyalty club), because features carry different revenue and different dependencies; third-party-backed features can only pass through the vendor's SLA (SLA Inversion, ch-4.10).
  - How availability is *measured*: automated **synthetic transactions** (flagged user IDs so they don't pollute production data), not mouse-clicking humans or help-desk complaints.
  - The full variable list: monitoring device(s), synthetic-transaction frequency and locations, max acceptable response time per step, response codes/patterns meaning success and failure, where data is recorded, and the exact percentage formula (time-based or sample-based). "When the fur flies, paper makes a thin shield" — but it points the argument at data.
- **Load balancing** (horizontal scaling implies it):
  - *DNS round-robin*: vends one of several server IPs; no health checking (dead servers keep receiving traffic), servers must be front-routable (attack surface), client holds all the control — and Java callers cache the first resolved IP forever, defeating balancing entirely. Inappropriate for enterprise callers.
  - *Reverse proxy* (Squid, Apache mod_proxy): demultiplexes one public address across a farm; also caches static content (cutting inner-network traffic); logs must use forwarded-for headers; Squid/Apache don't health-check origin servers; the proxy itself eventually becomes the constraint. A CDN is logically this pattern at planetary scale. Apache 2.2 `mod_proxy_balancer` adds capacity-weighted balancing — fine for mid-size sites before hardware.
  - *Hardware load balancers* (F5 BigIP, Cisco CSS): L4–7 switching for any connection-oriented protocol; real health checks with pool removal; site-to-site failover for DR; SSL acceleration (author's caveat: puts the crypto on the box that's in *every* request path instead of on Moore's-law-refreshed web servers — but centralizes certificate management); five-to-six-figure price.
- **Clustering** vs load balancing: clusters coordinate actively (heartbeats, state sync) and scale *sub*-linearly; active/passive clusters buy redundancy, not capacity (one node's bandwidth idles). Cluster servers as an exoskeleton for non-cluster-aware apps = "marvelous and kludgy" Band-Aid: finicky configuration, glitchy failovers. Apps with native clustering (app servers, DBs) often have unique "master control" nodes — SPOFs and the first capacity ceiling.

## ch-14 — Administration {#ch-14}

- Easy-to-administer systems get good uptime; annoying ones get neglected, deprecated, implemented incorrectly, or sabotaged. Dev and sponsors see releases as value; ops sees new failure modes, obsolete run books, and risk — both views are simultaneously correct ("assume positive intent"). Win ops by making their work easier.
- **"Does QA match production?"** — cheap to ask, expensive to answer, and usually aimed at the wrong layer: config-property diffs are rarely the culprit; **topology** mismatches are.
  - Rules: keep applications that run on separate production hosts on separate (virtual) hosts in QA — co-hosting breeds hidden dependencies like implicitly shared directories; virtualization gives production topology on shared hardware, plus snapshots for deployment testing.
  - "Zero, one, many": if production runs N>1 instances, QA runs ≥2 — one-vs-many is a fundamental difference (point-to-point vs multicast cache invalidation, session affinity, etc.).
  - Buy the network gear: firewalls and load balancers from the same vendor/product line as production; hours of downtime from an untested firewall rule cost more than the hardware. "You play the way you practice": develop with firewalls in the architecture from day one and the rules are documented by launch.
- **Configuration files**:
  - Never mix production configuration with application plumbing — admins hand-editing a 5,000-line framework XML to change one DB password is "the ejection seat button next to the radio tuner"; it should be *impossible* for an admin edit to break object wiring.
  - Production config lives outside the install directory (upgrades overwrite it; admins copy install trees between servers; tape restores clobber it).
  - Separate per-machine properties from shared-across-the-farm properties so nobody asks "are these supposed to differ?"; periodically verify that supposedly identical servers actually are ("trust, but verify").
  - Name properties by *function*, not nature: `authenticationServer`, not `hostname`. Config is the user interface presented to your most overlooked users.
  - Version-control configs with constraints: secure repository (passwords inside), linked to change control (why, not just when), automated deployment from the repo, automated audit to catch incident-time edits never committed back.
- **Start-up and shutdown**:
  - Complete initialization before accepting work: bind sockets but don't accept until the "master switch" flips — don't open the store because one employee arrived.
  - Initialize minimum pool connections at boot as a Fail Fast self-test; if it fails, remain running in an *interrogable failure state* rather than exiting silently (a rebooted-at-3-a.m. host must be able to say what's wrong).
  - Clean shutdown: stop accepting new work, drain in-flight transactions, then exit — bounded by a timeout so shutdown itself can't hang.
- **Administrative interfaces**: GUIs demo well ("enterprisey") and operate terribly — clicking can't be scripted, repeats per server, and barely survives SSH tunnels, so real-world result is `kill -9`. Best: command line (scriptable, loggable, automatable — admins build scaffolding around it). Acceptable: pure HTML admin UI (scriptable via HTTP libraries).

## ch-15 — Design summary {#ch-15}

Checklist recap of Part III — cheap in development, paid for repeatedly in production if skipped:

- Bind listening sockets to the correct interfaces; expose admin functions on the admin network only; document and configure special routes.
- Reach clustered services through VIPs so providers can fail over without your reconfiguration; handle the resulting exceptions.
- Run as unprivileged per-application users; sensitive parameters (passwords, keys) in their own protected files.
- Buy only the availability the cost/benefit arithmetic justifies; define it per feature with exclusions for external dependencies; pick load-balancing/clustering mechanisms to fit, early.
- Separate essential plumbing from environment-specific configuration; make start-up/shutdown non-disruptive; make every administrative duty scriptable.

## ch-16 — Case study: Black Friday outage {#ch-16}

Scenario → lesson, compressed (≤10 lines):

1. Retail holiday peak (~50% of annual revenue Nov–Dec); Thanksgiving traffic already = a normal week in one day, site healthy at ~250 ms page latency.
2. Black Friday morning: all request-handling instances red on external monitoring; rolling restarts failing immediately; ~$1M/hr revenue loss.
3. Marketing had dropped a newspaper insert: free home delivery — so ~100% of orders now hit the delivery-scheduling integration.
4. The scheduling vendor had 3 of 4 servers down for holiday-weekend maintenance; the survivor handled 25 concurrent requests, was receiving ~90, pinned at 100% CPU — and its on-call ignored the CPU pages because chronic false positives had trained the team to.
5. Order management's 450 threads all blocked calling scheduling through a resource pool with **no checkout timeout**; the storefront's 3,000 threads on 100 servers all blocked calling order management (same flaw). Site down, CPUs near idle — the classic blocked-threads signature.
6. Diagnosis in minutes because transparency existed: Perl modules screen-scraping the HTML admin GUI sampled latency/heap/threads/sessions across the farm (the team knew the site's normal pulse on sight); thread dumps localized the block front and back.
7. Fix: the store happened to have a *separate* connection pool just for scheduling calls (a Conway's-law accident = accidental bulkhead). Scripts set `max=0` and `checkoutBlockTime=0`, then invoked `stopService()`/`startService()` per component — the code politely reported "delivery scheduling unavailable" instead of blocking. Site green in ~90 seconds.
8. Full restarts under that load would have taken 6+ hours; component-level restart took <5 minutes; the throttle script ran all weekend (max=1 under load, higher when quiet) as a manual admission valve.

**Lessons**: a resource pool without a checkout timeout converts a partner's brownout into your outage; alert false positives train humans to sleep through real alarms; **component-level restartability (Recovery-Oriented Computing: failures are inevitable, models are incomplete, humans cause failures — design for restart and containment)** plus scriptable admin is what makes minutes-not-hours recovery possible; visibility *and* fine-grained control together saved the site — neither alone would have.

## ch-17 — Transparency {#ch-17}

**Transparency**: the qualities that allow operators, developers, and sponsors to understand a system's historical trends, present status, instantaneous behavior, and future projections. Ship engineers diagnose engines by lived familiarity with their sounds; our systems are faceless boxes unless we deliberately radiate the equivalent signals. Transparent systems train their humans; opaque systems are sick goldfish — you wait to see if they live. Without transparency: no tuning, no maturing, no data for capacity decisions (politics decides instead), and the system "drifts into decay, functioning a bit worse with each release."

### The four perspectives (§17.1)

| Perspective | Question it answers | Served by | Audience note |
|---|---|---|---|
| **Historical trending** | How does today compare; what correlates with what | OpsDB + BI tools/spreadsheets | broad access for data mining; never report off the production OLTP DB |
| **Predictive forecasting** | Capacity? When to buy hardware? Can we survive the holiday? | correlation models built from historical data | sensitive; not for dashboards; projections-of-projections square the error |
| **Present status** | Is everything where it should be *now* | dashboard: events + parameters vs. expectations | broad visibility (project it in the lunchroom); per-audience rollups |
| **Instantaneous behavior** | "What the **** is going on right now" | thread dumps, JMX consoles, log tails, stack traces | incident-time view; restricted (control surfaces can stop servers) |

- Historical: even business metrics (orders, conversion rate, revenue) belong beside system metrics (CPU, free storage, error counts) so cross-layer correlations are discoverable. Compare same-day-of-week, not calendar date.
- Predictive: "yesterday's weather" extrapolation works; "good enough" correlation models in a spreadsheet beat costly queueing-theory models for ordinary web systems. **A release can invalidate the correlations** — recheck them after every release before trusting projections, and label outputs with which projection set produced them.
- Present status distinguished from behavior: a jogging fat man's *behavior* is healthy, his *status* is one thump from a heart attack. Status = what the system *has done*: per component, events (point-in-time; some required — a missing daily feed is an alarm) + parameters (continuous metrics/discrete states vs nominal ranges).
- **Dashboard color definitions must be explicit, not vibes**:
  - Green = all expected events occurred ∧ no abnormal events ∧ all metrics nominal ∧ all states fully operational.
  - Yellow = an expected event missed ∨ medium-severity abnormal event ∨ parameter above/below nominal ∨ non-critical state degraded (e.g. a breaker cut off a non-critical feature).
  - Red = required event missed ∨ high-severity event ∨ parameter far out of range ∨ critical state wrong (e.g. "accepting requests" false when it should be true).
  - Note the overlooked trouble mode this catches: *too much of a good thing* (metric above nominal is yellow too).
- Dashboards must model **linkages**: ops sees components, developers see applications, sponsors see features/business processes; a component outage should show which business processes it hits (prioritization + sponsor communication).
- Batch jobs and feeds are first-class system citizens: dashboards show expected-but-missing executions. "A startling number of business issues trace back to batch jobs failing invisibly for 33 days straight."
- **Nominal** rule of thumb for continuous metrics: mean ± 2σ *for the matching time slice* — hour-of-week (2 p.m. Tuesday) is usually the most stable envelope; retail overlays week-of-year; travel/floral/sports count backward from events.
- Sponsors asking to "see inside" usually want *status* (revenue tracking to plan? did the campaign lift conversion?), not thread dumps; giving them a status dashboard defuses the ops-vs-business tension around access.

### Designing for transparency (§17.2)

- Must be designed in from the beginning; "adding transparency" late works about as well as "adding quality."
- Local visibility → local optimization only: a project optimized the nightly batch chain by two hours, but items still went live at 5–6 a.m. because an unwatched parallel process was the real constraint. Per-server cache stats hid an all-servers invalidation storm (every display accidentally updated the item, broadcasting invalidations); one page showing all caches made it obvious — without it they'd have *added servers and made it worse*.
- Coupling discipline: monitoring is an **exoskeleton** around the system, not woven into it. Thresholds, alert rules, and health roll-up policy live *outside* the application — policy changes at a different rate than code.

### Logging (§17.4) — the white-box workhorse

- Log files remain the most reliable, versatile, loosely coupled transparency channel: every tool can scrape them, they persist (unlike traps), and they work in development where the enterprise console doesn't exist.
- **Configuration**: log locations configurable — admins want logs on a separate spindle/filesystem from install and OS (I/O parallelism, contention); don't force symlink workarounds.
- **Levels are for operations, not developers** (ops reads these files far more than you will):
  - ERROR/SEVERE = an operator must *act*: circuit breaker tripped open, database connection failure.
  - Bad user input, business-rule rejections → WARN at most; a `NullPointerException` is not automatically an ERROR.
  - **No DEBUG in production**: one committed config with debug enabled is all it takes; add a build step that strips debug/trace levels from release configs.
- **Message codes**: externalize log strings to a resource bundle (IDE i18n tooling does it in hours) and prefix the key as a code — e.g. `(FulfillmentClient.2) Timeout failure connecting to fulfillment system`. Benefits: exact ops↔dev communication (vs "it said something about a fatal error"), and a lookup key for run books / knowledge bases. Bonus: the resource bundle *is* the "catalog of all messages" ops always asks for.
- **Log lines are a human–computer interface**; judge them by human factors — misread status prolongs incidents (Three Mile Island operators misreading coolant values):
  - Single-line events; columnar, space-padded layout; severity indicator at a fixed column so the eye (a pattern-matcher of unparalleled speed) and `grep` can both scan. Two-line formats (JDK `java.util.logging` default) defeat man and machine.
  - Every line carries a **correlation identifier** — user ID, session ID, transaction ID, or a request-scoped number — so a post-mortem is one grep through 10,000 lines, not archaeology.
  - **Log interesting state transitions** (circuit breaker states, enabled→disabled) even when also emitting SNMP/JMX notifications: the log persists for post-mortems; the trap doesn't.
- Message wording must say **who acts**: the debug message "Data channel lifetime limit reached. Reset required" (the app reset *itself*) was read as a database omen after one temporal coincidence with a crash — and drove operators to perform unnecessary weekly *production database failovers during peak hours for six months*. **Voodoo operations** grow wherever messages are ambiguous and pattern-hungry humans fill the gap (we're evolved to see leopards in bushes; false-positive detection is cheap, so superstitions stick). Post-incident "fixes" that merely coincided with recovery enter the run book unchallenged.

### Monitoring systems (§17.5)

- Dead processes log no tales; hung ones neither. White-box logging must be paired with **black-box monitoring** outside the process: agents observing OS stats, process/port liveness, log patterns — with heartbeats so a dead agent (or severed network) is itself detected.
- **External synthetic transactions from outside the data center** are the only view matching the user's: a blocked-threads outage looks healthy to every internal check (ch-2's monitoring hit a status page and stayed green through the airline outage; ch-16's SiteScope from NYC/SF was what went red). Internal monitors report the system's opinion of itself.
- Monitoring traffic belongs on its **own VLAN**: shared with production, a production network incident blinds monitoring precisely when needed; and monitoring payloads (hostnames, internal IPs, log snippets, process lists) are sensitive.
- "Agentless monitoring" is marketing: collection still runs through the observed host's OS APIs and still consumes its resources.
- Agents detect what they were told to look for (configured patterns, traps, thresholds); novel behavior slips through — one reason to keep log formats uniform so *unexpected* errors still match the generic pattern.
- Commercial suites' gaps: they model systems, not the business features those systems serve (they should answer "which features does this component outage hit?"), and they present the system's view of itself, not the user's. The monitoring system is chosen at enterprise level, outlives your stack, and is part of your environment — **design to standards, not to the vendor**, to avoid lock-in.

### Standards & what to expose (§17.6)

- **SNMP**: the 800-lb gorilla; one concept — everything is a variable (get/set/enumerate + asynchronous traps). Universal platform support (OS agents, Apache module, app servers, Oracle MIBs). Weakness for *your* code: writing a custom application MIB is specialist work (ASN.1, global-variables-and-tables information model), and monitoring admins resist installing "untrusted" MIBs.
- **CIM** (DMTF): object-oriented successor with dynamic discovery — technically superior, adoption thin (as of 2007); watch, don't wait.
- **JMX**: the Java path — standard in JDK 5+.
  - MBeans = management proxies over **long-lived architecture components**: resource pools, caches, circuit breakers, integration-point gateways. Properties readable/writable and control methods invokable remotely (the ch-16 recovery = set two properties, call two methods, per component).
  - `StandardMBean` wraps any object + interface without polluting domain code; Spring auto-generates MBeans from config.
  - Don't gold-plate: dynamic/model MBeans and per-domain-object MBeans are platform-vendor territory — "if you're that far into JMX you've gotten lost in the weeds."
  - JMX-to-SNMP connectors bridge into the enterprise console: protocol mapping is trivial (three operations), the work is mapping objects → variables/tables and notifications → traps.
  - **JMX's killer benefit is scriptability** (wsadmin/wslt/twiddle-class shells): make every administrative function scriptable and operations "will bless your name."
- **What to expose — expose everything, externalize policy.** You will guess wrong about which metric matters, and the linchpin metric changes with each release; so provide universal visibility now and defer thresholds/reactions to external policy. The canonical exposure checklist:
  - *Traffic*: total page requests, requests/s, transaction counts by type, concurrent sessions.
  - *Resource pools* (every pool — connections, worker threads): enabled state, total resources, checked out, high-water mark, created count, destroyed count, checkout count, threads blocked waiting, number of times a thread has blocked.
  - *Database connection health*: `SQLException`s thrown, queries issued, average query response time.
  - *Integration points* (per partner): circuit-breaker state, timeouts, request count, average response time, counts of good responses / network errors / protocol errors / application errors, **actual remote IP** (VIPs hide the real endpoint), concurrent requests + high-water mark.
  - *Caches*: item count, memory used, hit rate, items flushed by GC, configured ceiling, time spent building items.
  - *Business transactions, per type*: processed, aborted, dollar value, transaction aging, conversion rate, completion rate.
  - *Users*: demographics/classification, registered %, usage patterns, errors encountered.
  - *Per app server*: heap/generation sizes, GC type/frequency/reclaimed, worker threads per pool (busy, busy >5 s, high/low-water marks, unavailable count, backlog), request-channel stats (processed, aborted, avg response time, time of last request, accepting-traffic flag).
  - All counters carry an implicit window: "in the last n minutes" / "since last reset."

### Operations database (§17.7)

- The **OpsDB** accumulates status + metrics from all servers, applications, batch jobs, and feeds — the "single pane of glass" that serves the historical and future perspectives that logging (single-app, instantaneous) and monitoring (present/instantaneous) serve poorly. Feeds the dashboard, capacity-planning correlations, automatic baselining of "normal," and batch-job window tracking (start/end/abort + items processed → "is tonight's job in danger of missing its window?").
- Object model:
  - **Feature** — business-significant function, the unit SLAs and capacity plans are written about; implemented across web/app/DB hosts, firewalls, network gear.
  - **Node** — any active thing: host, application, batch job (assign ID blocks to teams). Optional Node→Node dependency edges are burdensome but valuable: they are the pathways cascading failures travel.
  - **Observation** — one data point from a Node, typed by an **ObservationType**; concrete kinds: *Measurement* (periodic performance sample), *Event* (point-in-time occurrence, e.g. job start/end/abort), *Status* (state transition — last one drives the dashboard; transition *frequency* drives diagnosis).
  - (This is Fowler's Observation analysis pattern applied to systems instead of patients.)
- **Expectation**s formalize "normal" per ObservationType: NominalRange for metrics, ExpectedTime windows for events, ExpectedStatus for states; violations raise alerts.
  - Derive expectations from the OpsDB's own accumulated history — matching reality avoids false positives, and **false positives train operators to ignore alarms** (the plant operator who overrode the warning chime with no conscious memory of doing it; the pager that "normally" fires three times a night; ch-16's ignored CPU alert).
  - Mature over time: "0–80% CPU" → "5–50%" → a time-of-day/business-rhythm envelope or step function.
- Feeding: a thin client API in the system's primary language that **fails silently** — the OpsDB is non-critical and must never impair production; a command-line writer for shell/batch jobs (announce items-to-process at start, items-processed at end, abnormal termination on failure); for Java, a generic sampling/notification MBean makes instrumenting an app a configuration exercise.
- Eat your own Steady State: condense old observations (minute-level samples older than a week aren't helpful) or the transparency system becomes its own capacity problem.

### Supporting processes (§17.8)

- Transparency without a closed feedback loop is waste: the scheduled report that half the distribution list auto-deletes costs money, provides nothing, and manufactures false security. Effective feedback = "acting responsively to meaningful data": examine → interpret (against someone's mental model) → evaluate options (including doing nothing) → decide → act → observe again.
- Boyd's **O-O-D-A loop** (Observe–Orient–Decide–Act): observation must be unclouded by wishful thinking or spin; orientation updates the mental map; each pass feeds the next through both the changed environment and your changed understanding. Cycling faster than competitors/opponents "gets inside their decision cycle." (Deming's Plan-Do-Check-Act is the same family.)
- Review cadence (watch for trends *and* outliers; build an operational rhythm):
  - Weekly: problem tickets — recurring issues, biggest time sinks, problem subsystems, problem third parties/integration points.
  - Monthly: total ticket volume and type distribution (severity should trend down with a sawtooth at each release); data volumes and query statistics.
  - Daily/weekly: log exceptions and stack traces correlated to their most common sources — serious problems vs. error-handling gaps; help-desk call themes (UI improvements + robustness gaps); if volume is too high, review top categories + a random sample.
  - Monthly: most expensive DB queries — query-plan changes? newcomers to the list (= data accumulating somewhere)? table scans in common queries (= missing index)?
  - Traffic envelopes: daily/weekly demand curves vs system metrics — a dropping "popular hour" usually means the system is too slow at that hour; a plateau in a driving variable means a limiting factor, probably responsiveness.
  - Every 4–6 months: re-verify that previously discovered correlations still hold.
- The focus shifts reactive → predictive as the system matures (tickets and post-mortems early; capacity, trends, and traffic-pattern shifts later). **Stop reviewing metrics that stopped producing information** — launch-month reports are worthless or misleading two years on.

## ch-18 — Adaptation {#ch-18}

- Release 1.0 is the system's birth, not the project's end; 40–90% of lifetime cost lands after it. "Form follows failure" (Petroski): each release fills gaps (features) or files bumps (defects) between the system and its solution space — which itself keeps moving.
- Change requires **activation energy** = implementation cost + release cost; changes must be *exoeconomic* — release more cash than they consume — so drive both costs down deliberately.

### Adaptable software design (§18.2)

- **Dependency injection**: components interact through interfaces, wired by a container rather than instantiating each other. Either endpoint becomes swappable (new implementation or test mock); localized change stays localized.
- **Loose coupling & tight cohesion**, modernized: coupling = behaviors one class requires of another (interface "width"); examine the *subsets* of a class's public methods used by different callers — the more distinct the subsets, the easier to change (and each subset is a latent interface). Cohesion = how much of the object's state each method-set touches; a method-set touching an isolated slice of state is another object trying to get out.
- **Crystals**: clusters of objects that exist only in tight mutual collaboration. Small crystals = malleable metal; objects that participate in *multiple* collaboration patterns fuse crystals into bigger grains, until the whole app is one **crystal palace** — baroque, perfectly adapted, admitting no incremental change; developers tiptoe and touch nothing. (Novice trap: measuring design quality by the number of GoF patterns applied — overloading pattern roles on one object grows the rock.) Minimize ties across crystal boundaries.
- **Refactoring + unit testing**: refactoring is the standing counter-pressure to crystallization; without unit tests it's "just random mucking around." TDD + YAGNI naturally yields adaptable code. Subtler effect: unit testing is a *second usage context*, forcing dependencies out into injectable properties — nothing is "reusable" until it's been reused, and the test is the first reuse. Hard-to-test objects (needing extensive context, like a persistence-aware `Customer`) are the signal to extract responsibilities, not to stop testing.
- **Agile databases**:
  - Schemas must change when behavior changes; walled-off schemas don't stop change, they force developers to *route around* rigidity — overloaded columns, type indicators, XML packed into CLOBs, relationships enforced only in code, enums existing only in source — semantic pollution that hits every other consumer of the data.
  - Every schema carries a **version table** (even one row/one column); applications verify compatibility at start-up and refuse to run on mismatch (Fail Fast — a schema/ORM-metadata mismatch otherwise yields runtime rollbacks or corrupted data); the version can key automated migrations. **Bump the version for semantics-only changes too.**

### Adaptable enterprise architecture (§18.3)

- Top-down "seamless enterprise" frameworks (Zachman/TOGAF-style) assume the architecture can be *finished* and that time can be held still while it's defined — both false; the result is mechanistic: rigid *and* fragile, breaking often and requiring command-and-control that fails repeatedly.
- Version-locked integrations create an exponential problem: each system must change whenever any counterpart changes; an enterprise-service-bus protocol change implies simultaneous redeployment of every mission-critical system — so it never happens, and the ESB ossifies or gets subverted (the integration-database failure mode at enterprise scale).
- Prefer the **ecosystem** view: systems occupy niches, exchanging information flows; redundant implementations in one niche (the firm with seven partially interoperable SAP instances) are inefficient but robust and *independently evolvable*. Avoid monocultures (single language, single integration technology): any standard old enough to be chosen is already aging.
- The acid test for any proposed architecture: **"Does this make IT better at responding to users' needs?"** Most enterprise architectures are built for IT's needs instead. Let architecture emerge from interaction patterns under real forces (budget, schedule, features, mastery, friction) — not anarchy, dynamic tension.
- **Dependencies within a system**: loose clustering — losing one instance means as little as losing one tree in a forest; no start-up ordering requirements; no unique differentiated roles (WebSphere/WebLogic master-control nodes violate this); members depend on *service names / VIPs*, never on individual instance identities; members never enumerate each other (O(n²) membership-change cost) — broadcast via pub/sub topics or command queues.
- **Dependencies between systems — protocols**: simultaneous cutover at both endpoints requires synchronized downtime and throttles every team to the slowest release cycle in the enterprise (the fastest hiker walks at the slowest scout's pace).
  - **Version the protocol; support N and N+1 simultaneously** through an overlap window (minutes for a single deploy window, months across quarterly cycles): a version field in the socket handshake (keep the handshake itself frozen-simple — it can never change); multiple named remote interfaces bound at once (one implementation class can serve several); namespace/version attributes in XML.
  - Same for file formats, where handshaking is impossible: auto-detect version on input, generate old formats as needed, and define semantic reinterpretation of old versions, not just field mapping.
  - Test harnesses (ch-5.7) verify every supported protocol-version combination.
- **Integration databases — don't. Seriously.** Not with views, not with stored procedures. Foreign systems reaching into your schema: violate encapsulation at structural *and* semantic levels; bypass application logic (illegal/unreachable states); make your own in-memory objects untrustworthy (rows mutate under you); and version-lock every consumer to the schema — which therefore never changes.
  - Alternatives: wrap a web service around the data, made redundant behind a VIP (and test-harness its failure modes); ETL to a warehouse; materialized views; storage-level copies (BCVs).
  - Interrogate "we need live production data": count the human decision latency downstream — most consumers tolerate hour-old snapshots; only near-real-time feedback loops justify more.

### Releases shouldn't hurt (§18.4)

- Vicious cycle: infrequent releases → each release unique → extra planning → more pain → fewer releases. Some releases resemble NASA launch sequences (20 people, all night). Forcing *frequent* releases forces automation and standardization — you get good at the thing you practice; releases should be about as big an event as a haircut.
- Release costs hide in configuration management, docs, marketing comms, deployment labor, support — and above all **downtime during the release**. "Planned downtime" is an operations accounting fiction: to a user, down is down; a four-hour deploy at $10k/hr costs $40k regardless of the calendar.
- Release *dates*: your customers don't know them (only shrink-wrap vendors' do). Never rush an unfinished release to hit an arbitrarily chosen date — the go/no-go meeting that green-lit a release *before QA finished testing* was serving the date, not the customer.
- **Zero-downtime deployments**: redundancy paradoxically creates release downtime, because during rollout versions N and N+1 coexist and share external references (DB schema, URLs, endpoints). Break the deployment into three phases:
  1. **Expansion** — add everything, break nothing:
     - Version static-asset URLs (`/static/1.2/styles.css`, never mutate `/static/styles.css`).
     - New endpoint names / interface versions alongside old ones (or parallel LB service pools on different ports when multi-version support is impractical).
     - DB: add tables and columns; new columns *nullable* (old code can't fill them); bridging **triggers** populate new columns from old-code writes and old columns from new-code writes (a migration script shows the mapping; the trigger applies it row-by-row). Stored procedures updated to fill both shapes.
     - Precondition: all SQL explicit about columns — no `SELECT *`, no implicit-column INSERT (ORMs do this mechanically; retrofitting at release time "will not be met well").
  2. **Rollout** — deploy gradually; let servers bake hours-to-days; pin session failover within same-version LB pools; no downtime pressure means orderly shutdown/start per server (ch-14 discipline).
  3. **Cleanup** — remove bridging triggers, extra service pools, old asset versions, dead columns/tables; *now* add NOT NULL and referential-integrity constraints (DB-enforced FKs can fight the ORM — decide deliberately).
- Prerequisite: development–operations collaboration from the start — which is exactly why zero-downtime deploys are rare.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Any socket connect/read, HTTP call, or RPC without an explicit timeout | Set both connect and read timeouts; never use no-arg blocking forms (`wait()`, `getInputStream()` on `URLConnection`) | Slow failure blocks a thread 20–30 min (OS TCP timeout) or forever; slow is worse than refused | ch-4, ch-5 |
| Resource pool configured to block indefinitely on checkout | Bound the checkout wait; code handles null/exception result | Pool exhaustion without timeout turned two outages (ch-2, ch-16) into total site hangs | ch-5, ch-9 |
| `finally`/cleanup block calls multiple `close()`s sequentially | Guard each close; assume `close()` itself throws | `Statement.close()` may throw → connection leak → pool exhaustion grounded an airline | ch-2 |
| Repeated calls to a remote dependency with no failure accounting | Wrap in a Circuit Breaker: count failures by type, trip open, half-open trial after cooldown; distinct exception when open | Stops cascading failures and retry hammering of a struggling dependency | ch-5 |
| Circuit breaker added without ops surface | Log state changes, expose state + change frequency as metrics, provide manual trip/reset | Breaker state-change frequency is a leading indicator; invisible breakers strand operators | ch-5, ch-17 |
| Code retries immediately after a timeout | Queue for delayed retry; return a fast answer (failure or "queued") to the caller | The problem that caused the timeout is still there; fast retries push the caller past its own timeout | ch-5 |
| Query result iterated without LIMIT/`setMaxResults`; ORM association to an unbounded child set | Bound every result set at the caller; treat any multi-row query as potentially millions of rows | The only sensible numbers are zero, one, and lots; a 10M-row `SELECT *` caused Black Monday | ch-4 |
| `synchronized` on domain-object methods; homegrown pool/queue classes | Give each thread its own copy; use proven concurrency primitives with timeout forms | In-memory coherence is moot on >1 server; hand-rolled pools deadlock under load never seen in dev | ch-4 |
| New vendor client library at an integration point | Test it against a devious Test Harness (20 parallel calls, connect-and-hang ports) before trusting it | Vendor libs hide sockets, block forever, and sneak `synchronized` into callbacks | ch-4, ch-5 |
| Integration test plan only exercises in-spec errors | Add a Test Harness that produces out-of-spec failures per port (refuse, hang, RESET, slow drip, wrong content-type, huge payloads) | Real systems fail outside spec; mocks can only fail within the defined interface | ch-5 |
| Any mechanism that accumulates data (table, log dir, cache) with no purge/rotate in the same release | Ship the recycler with the accumulator (app-level purge, rolling logs, cache limits) | Steady State: the fuse is lit at launch; full filesystems turn loggers into crash loops | ch-5 |
| Transaction does expensive work before checking required resources | Fail Fast: verify connections, breaker states, and basic input up front | Burning cycles to discard the result is the worst response; slow failure ties up both ends | ch-5 |
| System failures and input-validation failures reported identically | Distinguish system error vs. application error in responses and logs | Generic errors let one user's bad input trip upstream circuit breakers | ch-5 |
| Marketing/promo plans with exact times, deep links, or limited offers | Get advance notice; static landing pages; no deep links in mass email; consider a dedicated promo pool | Attacks of Self-Denial: good marketing can kill you at any time | ch-4 |
| Point-to-point communication among N instances; N will grow | Replace with pub/sub, multicast, or queues before production scale | O(n²) connections can't be tested out at QA's 1:2 scale — design it out | ch-4, ch-18 |
| Front-end and back-end capacities sized independently | Compare thread/connection ratios in production terms; test the back end at 2× peak on its most expensive transaction | The front end can always overwhelm the back end; QA's 1:1 topology hides it | ch-4 |
| Whole objects (carts, results) stored in sessions or cookies | Sessions keep keys + `SoftReference` caches; cookies carry identifiers only | Sessions outlive users and eat RAM; clients lie about cookie contents | ch-4, ch-9 |
| Session timeout left at framework default | Set to mean inter-request delay + 1σ for the domain; design sessions to be droppable and re-creatable | The default 30 min holds memory long after users leave | ch-9 |
| Handcrafted or dynamically assembled SQL in OLTP code | Prefer ORM-predictable SQL; run hand SQL past the DBA and production-sized data | Idiosyncratic queries defeat systematic tuning; toy-data gains evaporate | ch-9 |
| Reports/BI querying the production OLTP database | Move to warehouse/replica; purge or archive historical rows | Reporting on production is a capacity killer; the OLTP schema is wrong for analysis anyway | ch-9, ch-17 |
| Content rendered per-request but changed rarely (weekly) | Precompute at change time; punch out only personalized fragments | Million-render/one-change is the wrong side of the multiplier effect | ch-10 |
| Cache added without limits or metrics | Set max memory, monitor hit rate, define an invalidation strategy, use SoftReferences | Unbounded caches are memory leaks; low-hit caches cost more than they save | ch-10 |
| Chatty remote interface (per-item calls in a loop; "location transparency") | Batch into coarse-grained summary calls | Remote ≈1,000× local; 1+3N calls made a tree control take 20 minutes cross-Atlantic | ch-9 |
| `ServerSocket`/listener bound to all interfaces on a data-center host | Bind to explicit, configurable addresses per network role | Multihomed hosts otherwise expose admin functions on production networks and vice versa | ch-11 |
| App requires root/Administrator, or passwords inside the install tree | Per-app OS user; LB fronts port 80; password files separate, owner-only, vaulted; core dumps disabled | Root software is a cracker magnet; install trees get overwritten, copied, and shipped | ch-12 |
| SLA stated as one number for "the system" | Define per feature, with monitoring device, synthetic-transaction cadence, response-time bounds, success patterns, and formula | You cannot exceed the worst dependency's SLA; vague SLAs cause post-incident blamestorms | ch-4, ch-13 |
| Prod runs N>1 instances but QA runs 1 | Run at least 2 in QA (VMs suffice); match firewall/LB vendor gear | Topology mismatches, not property diffs, cause most launch failures | ch-14 |
| Production endpoints/passwords inside plumbing config (framework XML) | Separate production config from wiring; outside the install dir; named by function | Admins hand-edit; every extra line is a land mine; upgrades overwrite | ch-14 |
| Service accepts connections before initialization completes; shutdown aborts in-flight work | Gate accept on ready; verify DB connectivity at boot (Fail Fast); drain-then-exit with a timeout | Half-started and rudely stopped apps corrupt work and hide their own failures | ch-14 |
| Admin function only reachable via GUI clicking | Provide CLI or HTML (scriptable) admin; expose control methods via JMX/equivalent | Per-server clicking doesn't scale to incidents; the ch-16 recovery was 100 servers × scripts in minutes | ch-14, ch-17 |
| Log message at ERROR for user input / business rules; DEBUG enabled in prod | ERROR = operator must act; WARN for business noise; strip debug configs in the release build | Alert fatigue trains operators to ignore alarms; ambiguous messages breed voodoo procedures | ch-17 |
| Log lines missing transaction/session/request IDs; multi-line formats | One line per event, fixed severity column, message-code prefix, correlation ID on every line | Post-mortems are greps; two-line formats defeat humans and grep alike | ch-17 |
| New pool/cache/breaker/integration gateway with no metrics | Expose the ch-17 checklist (state, counts, high-water marks, response times); keep thresholds/alert policy external | You can't predict the linchpin metric; policy changes at a different rate than code | ch-17 |
| Monitoring only from inside the data center | Add external synthetic transactions from outside; put monitoring on its own VLAN | Blocked-thread outages look healthy to every internal check; shared networks blind monitoring during network incidents | ch-16, ch-17 |
| Metric/alert thresholds hardcoded in the app | Externalize expectations (nominal ranges, expected-event windows); derive from historical data; tighten over time | False positives create ignored alarms; expectations change faster than code | ch-17 |
| Another system reads/writes your DB tables (or a plan proposes it) | Refuse; offer a versioned service behind a VIP, ETL, or materialized views | Integration databases version-lock every consumer and bypass application logic | ch-18 |
| Protocol/interface change deployed to caller and provider simultaneously | Version the protocol; provider supports N and N+1 through an overlap window | Simultaneous cutover means synchronized downtime and slowest-team throttling | ch-18 |
| Schema change bundled with app deploy in one downtime window | Expand (nullable columns + bridge triggers + explicit-column SQL) → rollout (baked, version-pinned pools) → cleanup (constraints, drops) | Zero-downtime deployment; "planned" downtime costs the same revenue as unplanned | ch-18 |
| No schema-version table / app starts against an unknown schema | Version the schema; verify at start-up and refuse to run on mismatch | Schema-metadata mismatch causes rollbacks at best, corrupted data at worst | ch-18 |

## Anti-patterns

Named antipatterns with detection cues (ch-4/ch-9 above give mechanisms; this is the grep list):

- **Integration Points (unguarded)** — outbound call with no timeout/breaker; thread dumps full of `socketRead0`.
- **Chain Reaction** — homogeneous farm nodes crashing at accelerating intervals.
- **Cascading Failure** — caller's pool empties after callee slows; caller CPU burned on retries + failure logging.
- **Users / session bloat** — session count ≫ users; cookieless clients minting sessions; giant objects in sessions.
- **Blocked Threads** — process alive, zero throughput; all threads in one blocking call.
- **Attack of Self-Denial** — traffic cliff at a promo timestamp; deep links bypassing the CDN; one hot row/lock serializing thousands of threads.
- **Scaling Effects** — O(n²) point-to-point links; works at QA scale only.
- **Unbalanced Capacities** — 3,000 front-end threads calling 450 back-end threads calling 25.
- **Slow Responses** — latency climbing at constant load; Reload-button traffic multiplication.
- **SLA Inversion** — promising 99.99% atop no-SLA dependencies (including DNS, SMTP, brokers, SANs).
- **Unbounded Result Sets** — `SELECT` with no LIMIT; "that table can't grow" assumptions.
- **Resource Pool Contention** — throughput knee at threads > pool; blocked-checkout counters climbing.
- **Cookie Monster** — serialized objects/carts in cookies; trusting client-supplied state.
- **Handcrafted SQL / Database Eutrophication** — unindexed joins, 1+N loops, reports on prod, no purge regimen.
- **Integration Database** — foreign systems selecting from (or writing) your tables.
- **Crystal Palace** — objects participating in many collaborations; nothing movable without moving everything.
- **GUI-only administration** — unscriptable click-sequences per server; `kill -9` culture.
- **Voodoo operations** — run-book actions justified by temporal coincidence plus ambiguous log wording.
- **The report nobody reads** — transparency without a feedback loop; auto-delete inbox rules are the detection cue.
- **Fight Club bug** — front-end load causing exponentially increasing back-end work (hot-lock serialization, per-view reprocessing).

## Applicability & exemptions

- **Era calibration**: 2007 first edition. J2EE/JSP/PermGen/Squid/SNMP specifics, hardware prices, dial-up ratios, and "AJAX" framing are dated; the failure mechanics (TCP, pools, sessions, coupling), the antipattern/pattern catalog, and ch-17's exposure lists are evergreen. Map JMX → your metrics endpoint, OpsDB → your TSDB/observability stack, SiteScope → synthetic monitoring, hardware LB → cloud LB. Cloud elasticity weakens (not voids) "capacity is fixed over short periods" (ch-4.8) and makes bulkheads/VM partitions cheap.
- **Scope**: written for enterprise/commerce distributed systems where downtime = money ("if anybody has to go home for the day because your software stops working"). For internal tools, prototypes, or batch research code, the stability patterns are optional armor — Nygard's own financial framing (ch-1, ch-13) says buy only the nines the arithmetic justifies. Don't demand circuit breakers on a cron script.
- **Pattern count ≠ quality** (ch-6, explicit): applying every pattern everywhere is over-firing. Bulkheads cost reserve capacity; health-check handshaking doubles connection overhead (worth it only when call cost ≫ check cost); async middleware is logically harder and near-irreversible — synchronous request/reply is legitimately simpler when the business answer must be immediate (credit-card auth).
- **Fail Fast vs. validation layering**: only null/format checks belong in the controller; pushing full domain validation forward violates encapsulation (ch-5.5).
- **Object pooling**: the "don't pool" measurement applies to ordinary objects on modern GCs; connections, sockets, and threads remain pool-worthy (ch-10.4).
- **Sessions**: minimal-session guidance excludes financially sensitive data, which should live only server-side and transiently (ch-9.4). Session-timeout tuning presumes stateful app-server sessions at all — token/stateless architectures moot it.
- **Zero-downtime three-phase deploys** assume relational schemas with trigger support and LB-controllable pools; on greenfield systems with no users (cf. this repo's Greenfield Policy) the expand/contract machinery is unnecessary ceremony — the transferable core is "no `SELECT *`, version the schema, version the protocol."
- **DNS round-robin** criticism (Java caching the first IP forever) reflects old JVM defaults; TTL-respecting clients weaken it, but the "no health check, client holds control" objection stands.
- ↔ contra observability-engineering: Nygard's dashboard/threshold/expectation model is metrics-plus-known-failure-modes ("monitoring"); high-cardinality event tracing for *unknown* failure modes largely supersedes the OpsDB design, though his what-to-expose list, correlation-ID rule, and log-line human-factors rules remain the application-side prerequisites. His own ch-17 concedes the gap: agents detect only what they were told to look for.
- ↔ contra modern-software-engineering / agile lore: Nygard endorses TDD/refactoring/frequent releases but insists some decisions cannot be YAGNI'd — middleware coupling, protocol versioning, and transparency are near-irreversible and must be made early (ch-5.8, ch-17.2).

## Candidate lexicon rows

| every new outbound socket/HTTP/DB/RPC call in a diff | **Timeouts everywhere** — a missing read timeout blocks a thread for the OS TCP timeout (20–30 min) or forever, and blocked threads are the proximate cause of most outages | Does every remote/blocking call in this change carry explicit connect and read timeouts? | blocker | write | src: release-it ch-5 |
| resource pool or semaphore acquired in request path | **Bounded checkout** — pools that block indefinitely convert a dependency brownout into total site hang (airline, Black Friday) | Can this checkout wait forever, and does the caller handle a timed-out checkout? | blocker | review | src: release-it ch-5 |
| loop over query results / ORM association traversal | **Bound every result set** — the only sensible row counts are zero, one, and lots; a 10M-row surprise is an OOM crash loop | What happens when this query returns a million rows instead of a hundred? | blocker | write | src: release-it ch-4 |
| repeated calls to an external dependency without failure accounting | **Circuit-break integration points** — stop calling what's already failing; expose breaker state and log transitions for operations | If this dependency starts timing out, what stops us from hammering it and draining our own pools? | should | plan | src: release-it ch-5 |
| retry logic that immediately re-attempts a failed remote call | **Queue-and-retry, answer fast** — the fault that caused the timeout persists; immediate retries fail again and push the caller past its own timeout | Does this retry happen now (wrong) or from a queue later (right), and does the caller get a fast answer? | should | review | src: release-it ch-5 |
| diff adds a table, log stream, or cache with no recycler | **Steady State** — every accumulating resource needs a same-rate recycling mechanism shipped in the same release, or production requires routine human logins | Where is the purge/rotation/eviction for what this change accumulates? | should | plan | src: release-it ch-5 |
| log statement at ERROR level / debug config in a release build | **ERROR means operator action** — user input and business noise log at WARN; alert false positives train operators to ignore real alarms | Would an on-call human need to act on this message at 3 a.m.? | should | write | src: release-it ch-17 |
| log line lacks a request/session/transaction identifier | **Correlation ID on every line** — post-mortems are greps; single-line columnar format with a message code and ID is the difference between minutes and days | Can one grep reconstruct this transaction's path across the logs? | should | write | src: release-it ch-17 |
| new pool, cache, breaker, or integration gateway without metrics | **Expose everything, externalize policy** — you can't predict the linchpin metric; emit state, counts, high-water marks, and response times, and keep thresholds outside the app | What does operations see when this component misbehaves, and can they change alert thresholds without a redeploy? | should | write | src: release-it ch-17 |
| plan wires one system to read another's database tables | **No integration databases** — foreign readers version-lock the schema and bypass application logic; integrate via versioned services, ETL, or views | Could this consumer survive our next schema change without a coordinated deploy? | should | plan | src: release-it ch-18 |
| interface/protocol change touching caller and provider together | **Version protocols, overlap versions** — simultaneous cutover means synchronized downtime and throttles every team to the slowest release cycle | Can the provider serve N and N+1 while callers migrate independently? | should | plan | src: release-it ch-18 |
| schema migration bundled into a deploy step | **Expand, then rollout, then cleanup** — nullable-first columns, bridging triggers, explicit-column SQL, and constraints added only after cutover make deploys downtime-free | Is this migration split so old and new code both run against the intermediate schema? | judgment | plan | src: release-it ch-18 |
