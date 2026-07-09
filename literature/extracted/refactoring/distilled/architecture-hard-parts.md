# Software Architecture: The Hard Parts — distilled

> **Source**: Neal Ford, Mark Richards, Pramod Sadalage, Zhamak Dehghani, *Software Architecture: The Hard Parts — Modern Trade-Off Analyses for Distributed Architectures*, O'Reilly 2022 · extracted from `../architecture-hard-parts.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: This is the only source in this directory that teaches the *method* of architectural trade-off analysis rather than answers: how to untangle coupled dimensions, build trade-off tables, and justify decisions with ADRs when no best practice exists. It supplies the decision tables this lexicon otherwise lacks — granularity **disintegrators vs integrators** for splitting services, **data disintegrators vs integrators** for splitting databases, the **8 transactional saga patterns** (communication × consistency × coordination), data-ownership assignment rules (who writes what table), distributed read-access patterns, reuse patterns (replicate/library/service/sidecar), and strict-vs-loose contract selection. Where DDIA explains distributed-data mechanics and release-it explains production failure modes, this book tells an agent *when a plan should split, merge, share, or own* — and forces every such plan to name what it sacrifices.

## Chapter map
- ch-1 — When there are no "best practices": trade-off mindset, ADRs, fitness functions, operational vs analytical data, core definitions
- ch-2 — Discerning coupling: architecture quantum, static vs dynamic coupling, the 3 C's (communication/consistency/coordination), 8-pattern matrix
- ch-3 — Architectural modularity: the five business drivers that justify breaking a monolith apart (and when they don't)
- ch-4 — Architectural decomposition: is the codebase decomposable? coupling metrics; component-based decomposition vs tactical forking
- ch-5 — Component-based decomposition patterns: the six-pattern sequence from monolith to service-based architecture, with governance fitness functions
- ch-6 — Pulling apart operational data: data disintegrators vs integrators, the five-step database decomposition, database-type selection
- ch-7 — Service granularity: the disintegrator/integrator decision table for splitting or merging services
- ch-8 — Reuse patterns: code replication vs shared library vs shared service vs sidecar/service mesh; when reuse adds value
- ch-9 — Data ownership & distributed transactions: single/common/joint ownership rules, ACID vs BASE, eventual-consistency patterns
- ch-10 — Distributed data access: four patterns for reading data your service doesn't own
- ch-11 — Managing distributed workflows: orchestration vs choreography, workflow state management, semantic coupling law
- ch-12 — Transactional sagas: the eight saga patterns and their ratings; compensating updates vs state management
- ch-13 — Contracts: strict vs loose spectrum, consumer-driven contracts, stamp coupling
- ch-14 — Managing analytical data: data warehouse vs data lake vs data mesh; data product quantum
- ch-15 — Build your own trade-off analysis: the 3-step method, MECE lists, out-of-context trap, scenario modeling, anti-evangelism

## ch-1 — When There Are No "Best Practices" {#ch-1}

Architects face problems that conflate their exact organization and constraints — nothing to Google. Core posture:

- **Least-worst trade-offs**: don't seek the *best* design; seek the least worst combination of trade-offs. "Best" implies all competing factors were maximized simultaneously, which never happens.
- **Second law of software architecture**: *why is more important than how*. A decision without recorded rationale rots; the "how" can be re-derived, the "why" cannot.
- Timeless advice = decision method, not technology. Dominant styles (orchestration-driven SOA → microservices) are artifacts of era constraints (no viable open source → operationally free Linux + programmable infra), so never copy a style without checking whether its enabling constraints hold for you.

**Architectural Decision Records (ADRs)** (Nygard): 1–2 page text file per consequential decision with three sections — *Context* (problem + alternatives), *Decision* (choice + justification), *Consequences* (what it costs, trade-offs considered). Every worked decision in the book ends in an ADR; treat "ADR written" as the exit criterion for an architecture decision.

**Architecture fitness functions**: any mechanism performing an *objective* integrity assessment of one or more architecture characteristics — a CI test, monitor, or chaos experiment that governs a design rule automatically instead of by code review.
- **Atomic** (one characteristic, e.g., a component-cycle test via JDepend) vs **holistic** (interacting characteristics, e.g., security × performance).
- Scoping test: "does executing this test require domain knowledge?" Yes → unit/functional test. No → fitness function (elasticity needs no domain knowledge; address validation does).
- Objective ≠ static: dynamic fitness functions return context-dependent values (per-user performance as user count grows).
- Canonical examples: cycle detection; ArchUnit/NetArchTest layer-access rules (`whereLayer("Persistence").mayOnlyBeAccessedByLayers("Service")`); an enterprise "security slot" in every deployment pipeline so a zero-day (Equifax/Struts scenario) becomes one inserted test that fails every affected build.
- Fitness functions are an executable checklist of *important-but-not-urgent* principles (Checklist Manifesto argument) — the antidote to "we'll fix it later." Don't build an ivory-tower interlocking suite that merely frustrates teams.

**Operational vs analytical data**: operational (OLTP, transactional; the company stops without it) vs analytical (trending, ML, BI; drives strategy, not day-to-day). The split is an architectural concern threaded through the whole book (ch-6, ch-14).

Definitions used throughout (deliberately minimal): **service** = cohesive functionality deployed as an independent executable; **coupling** = two artifacts are coupled if a change in one might require a change in the other; **component** = build block manifested as namespace/directory; **synchronous** = caller waits; **asynchronous** = caller doesn't; **orchestrated** = a dedicated coordinator service exists; **choreographed** = no coordinator; **atomic** = all-or-nothing consistent at all times; **contract** = the format by which any two parts convey information or dependencies (REST, method signature, queue message, IP address — anywhere software joins).

## ch-2 — Discerning Coupling in Software Architecture {#ch-2}

Microservices made data a first-class architectural concern: putting the database inside the service boundary (bounded context) moved transactionality from the database's problem to the architect's. Generic advice ("decouple everything!") fails — fully decoupled things can't communicate; like poison, dosage decides.

**Modern trade-off analysis, 3 steps** (the book's master algorithm):
1. Find what parts are entangled together.
2. Analyze how they are coupled to one another.
3. Assess trade-offs by determining the impact of change on interdependent systems.

**Architecture quantum**: an independently deployable artifact with high functional cohesion, high static coupling, and synchronous dynamic coupling — a bounded context expressed in architectural terms. It defines the scope within which architecture characteristics (scale, security, elasticity) can differ.

- **Static coupling** = how services are *wired*: everything needed to bootstrap the service — OS, frameworks/transitive dependencies, database, message broker presence, URLs/IPs. Diagnostic question: "is this dependency necessary to bootstrap this service?"
- **Dynamic coupling** = how services *call each other at runtime*; couples quanta temporarily for the duration of a workflow (a synchronous call ties the caller's performance/scale to the callee's).
Quantum counting by topology:

| Topology | Quanta | Why |
|---|---|---|
| Any monolith (layered, modular, microkernel) | 1 | single deployment unit + single database |
| Service-based architecture | 1 | separately deployed services, but one shared relational DB |
| Mediated event-driven architecture | 1 | shared DB *and* the central request orchestrator are holistic coupling points |
| Broker EDA, all services on one DB | 1 | services not touching the DB still depend on services that do |
| EDA with two independent data stores, no cross-dependency | 2 | each half bootstraps and operates alone (even if not in every workflow) |
| Microservices, data per service | n | each service+DB pair forms its own quantum with its own characteristics |
| Microservices behind one tightly coupled UI | 1 | UI won't operate with backends missing; sync calls fuse characteristics |
| Microservices + micro-frontends (event-coupled UI components) | n | each service plus its emitted UI component is a quantum |
| Two systems sharing one database | 1 | the shared DB fuses otherwise separate systems |

Practical uses: a static-coupling diagram answers "if I change X, what must be tested?" (buildable from container manifests, POM/npm dependency trees, and observability call graphs); legacy archaeology; blast-radius analysis. Dynamic-coupling example: Ticketing runs at 10× the elasticity of Assignment — a synchronous call drags the whole workflow to the slower service's pace; an async queue buffers them so each scales independently.

**Dynamic coupling has three dimensions ("the 3 C's")** — they cannot be chosen in isolation, each exerts gravity on the others:
- **Communication**: synchronous vs asynchronous
- **Consistency**: atomic vs eventual
- **Coordination**: orchestrated vs choreographed

The 2×2×2 space yields the **eight saga patterns** (full analysis in ch-12): Epic(sao, very high coupling), Phone Tag(sac, high), Fairy Tale(seo, high), Time Travel(sec, medium), Fantasy Fiction(aao, high), Horror Story(aac, medium coupling / worst complexity), Parallel(aeo, low), Anthology(aec, very low). Transactionality is easiest synchronous+orchestrated; scale is highest asynchronous+eventual+choreographed.

## ch-3 — Architectural Modularity {#ch-3}

Rule zero: **don't break a system apart without clear business drivers.** The two business drivers are speed-to-market (via agility) and competitive advantage (via scale + availability). They decompose into five measurable architecture characteristics — build the business case by mapping observed pain to these drivers:

| Driver | Definition | Monolith failure mode | Modularity payoff |
|---|---|---|---|
| Maintainability | ease of add/change/remove | change smeared across all layers, 3 teams per field added | change scoped to domain (service-based) or function (microservice) |
| Testability | ease + completeness of testing | full regression suite per tiny change; unrelated failures | small targeted suites — *until* services chat heavily, then scope re-expands |
| Deployability | ease + frequency + risk of deploy | ceremony, code freezes, batched risky monthly releases | frequent small low-risk deploys — degraded again by interservice coupling |
| Scalability/elasticity | responsiveness under gradual growth / instant spikes | whole app must scale as one; poor MTTS | scalability tracks modularity; elasticity tracks granularity (small MTTS) |
| Fault tolerance | parts keep working while others fail | one OOM crashes everything; multiple instances share the bug | failure isolated per deployment unit — *only if* dependents aren't synchronous |

Cross-cutting caveat (repeats through the table): every benefit erodes as synchronous interservice communication grows. Matt Stine: "If your microservices must be deployed as a complete set in a specific order, please put them back in a monolith."

Distinctions worth keeping straight:
- **Scalability** (gradual growth in concurrent users) vs **elasticity** (instant erratic spikes — concert tickets going on sale: 20 → 3,000 users in seconds). Elasticity needs small **MTTS** (mean time to startup) ⇒ fine granularity; scalability needs modularity. Both degrade as interservice chatter grows.
- Fault tolerance via load-balanced monolith instances is weak: a code bug exists in every instance.
- Modularity ≠ distribution: a modular monolith or microkernel gets maintainability/testability/deployability without distribution costs.
- Agility is a composite — never a fitness-function target itself; decompose it into deployability, testability, cycle time (ch-1's measurability rule).

Business-case method (the Sysops pattern): take each observed pain ("changes break other things", "system freezes when reports run", "customers can't enter tickets") → map to the characteristic it violates (maintainability/testability, scalability + DB load, fault tolerance) → show how modularity addresses each → write the migration ADR with costs (feature delay, migration cost, DB breakup) in the consequences.

## ch-4 — Architectural Decomposition {#ch-4}

Decision tree: **(1) Is the codebase decomposable at all? (2) If yes: does it have discernible component structure?** Structured → component-based decomposition (ch-5). Unstructured **Big Ball of Mud** → tactical forking. Neither → total rewrite territory.

Decomposability metrics (macro triage, not gospel):
- **Afferent coupling (CA)** = incoming dependencies; **efferent (CE)** = outgoing (Yourdon/Constantine).
- **Abstractness** A = abstract artifacts ÷ total; **Instability** I = CE ÷ (CE + CA). I≈1 = volatile; I≈0 = stable (if abstract) or rigid (if concrete).
- **Distance from the main sequence** D = |A + I − 1|. Components far into the **zone of pain** (concrete + stable, brittle) or **zone of uselessness** (abstract + unstable) mean poor foundations; if most components live in those zones, restructuring before moving may not be worth it. Golfball/basketball/airliner sizing: a component-dependency diagram answers feasibility, effort, and refactor-vs-rewrite in one visual.

**Component-based decomposition**: build services from *components* (namespaces), never from individual classes. Target **service-based architecture** first — separately deployed coarse-grained domain services over a still-monolithic database. As a stepping stone it (a) defers database breakup, (b) needs no container/ops automation, (c) requires no org change, (d) lets you learn which domains actually justify microservice granularity. Many never need to go further.

**Tactical forking** (De La Torre): clone the entire monolith per target team, then each team *deletes* what it doesn't need — deletion avoids unraveling the coupling that extraction drags along. Benefits: start immediately, no up-front analysis. Costs: latent dead code remains, internal quality unchanged ("just less of it"), shared-code drift across forks.

## ch-5 — Component-Based Decomposition Patterns {#ch-5}

Six patterns applied in sequence (then individually during maintenance), each with governance fitness functions so the migration survives ongoing change. Refactorings are tracked as **architecture stories** — like user stories but describing structural change driven by a business need (distinct from technical-debt stories).

1. **Identify and Size Components** — inventory components; size by **total statements** (not LOC/classes — coding style noise), percent of codebase. Components should sit within 1–2 standard deviations of mean size; break outliers along subdomains (33%-of-codebase Reporting → shared + tickets + experts + financial). Fitness functions: component inventory diff alerts; no component > n% of codebase; no component > 3 std-dev from mean.
2. **Gather Common Domain Components** — consolidate duplicated *domain* functionality (notification in 3 places → one component); distinguish from infrastructure code. Detection cues: same class shared across namespaces, common namespace leaf names (`.audit` × 3). Check afferent coupling before/after: consolidation is safe when total incoming coupling is unchanged (3 components CA 2+2+1 → 1 component CA 5).
3. **Flatten Components** — source files must live only in *leaf-node* namespaces. A namespace extended by another node is a **root namespace** (subdomain); classes stranded there are **orphaned classes**. Flatten down (merge subcomponents in) or up (split root code into new leaves); move shared code to a `.sharedcode`-style leaf. Metric: if `.sharedcode` totals ~45% of the codebase, distribution will produce a shared-library nightmare — reconsider.
4. **Determine Component Dependencies** — build the component-level (not class-level) dependency graph before any extraction; it answers feasibility/effort/rewrite-or-refactor. Fitness functions: total coupling per component < threshold; explicit "X must not depend on Y" ArchUnit rules.
5. **Create Component Domains** — group components into domains manifested through hierarchical namespaces (`ss.customer.billing.payment`); refactor namespaces so structure matches domain. Governance: whitelist of allowed root domains.
6. **Create Domain Services** — extract each *fully refactored* domain into a separately deployed service (service-based architecture). Don't extract until domains are stable, or you'll re-modify already-migrated services. Governance: all components in a domain service share the namespace prefix.

## ch-6 — Pulling Apart Operational Data {#ch-6}

Breaking a database is harder than breaking code: data outlives systems, and coupling hides in foreign keys, views, triggers, procedures. Decide with **data disintegrators** (forces to split) vs **data integrators** (forces to keep together):

**Six data disintegrators**:
1. **Change control** — how many services break when a schema changes? Breaking changes (drop/rename column, type change) force coordinated test+deploy of every sharing service; the forgotten ones silently fail in production. Bounded contexts isolate change: the service contract (JSON etc.) *abstracts* consumers from the schema — a dropped column changes the owner service only, the contract evolves later.
2. **Connection management** — connections don't scale with instance count: 200-connection monolith → 50 services × 10-connection pools × 2 instances = 1,000; half scaling to 5 instances → 1,700. Symptom: **connection waits**, surfacing as request time-outs and tripped circuit breakers — check for waits first when a shared DB misbehaves. Mitigation short of splitting: per-service **connection quotas** — start with even distribution (simple, wasteful), then rebalance to variable quotas from observed max-used vs waits (take from under-users, give to waiters), keep quota values in an external config service, and continuously verify with a metrics-streaming fitness function. Quotas break down once instances scale (quota × instances > pool), which is itself the argument for splitting.
3. **Scalability** — when services scale, the shared DB's connections/throughput/capacity must scale too; splitting reduces per-DB load.
4. **Fault tolerance** — one shared DB is a SPOF for every service; splitting creates data silos that fail independently.
5. **Architectural quantum** — a shared DB fuses services needing different characteristics into one quantum; split the data to split the quantum.
6. **Database type optimization** — polyglot persistence: move key-value-ish, document-ish, graph-ish data to the type that fits (illustrated: survey JSON → document DB, justified by marketing's change-request lead time, sealed with an ADR).

**Two data integrators**:
1. **Data relationships** — FKs, triggers, views, and logical relationships must be *removed* across any split boundary; that loss of DB-enforced integrity is the price. Weigh explicitly: "is change control worth losing this FK?"
2. **Database transactions** — a split kills the single ACID unit of work; if the business requires all-or-nothing writes across the tables, keep them together (see ch-9/12).

**Five-step database decomposition** (evolutionary, uses **data domains** = a domain-cohesive set of tables + coupling artifacts):
1. Analyze database, group tables into candidate data domains (dotted cross-domain lines = dependencies to break; use *Refactoring Databases* patterns).
2. Assign tables to schemas per domain; temporarily bridge with synonyms (they don't remove cross-schema coupling, but make it findable and breakable later). Tightly coupled domains may merge into a broader bounded context.
3. Separate connections: each service connects only to its own schema; cross-domain access moves to service calls. Rule: **a service that needs another domain's data asks the owning service — it never reaches into the schema.** Companion rule from the saga: services may share one schema, but no service connects to multiple schemas. End state = data sovereignty per service (benefits: independent schema change, per-service DB tech; costs: high-volume access pain, no cross-domain referential integrity, DB code moves to services).
4. Move schemas to separate DB servers (backup-and-restore = downtime; replicate = no downtime, more coordination).
5. Switch over and remove old schemas; only now optimize per-database type/availability.

**Database type selection** (rated on learning curve, modeling ease, scalability/throughput, availability/partition tolerance, consistency, community/maturity, read-vs-write priority):
| Type | Sweet spot | Watch out | Products |
|---|---|---|---|
| Relational | balanced read/write, ACID, flexible modeling | vertical scaling, complex replication | PostgreSQL, Oracle, SQL Server |
| Key-value | fast key lookups, session/cache, tunable consistency | query by key only; aggregate redesign = rewrite all data | DynamoDB, Riak, Redis |
| Document | readable aggregates, flexible schema, indexed queries | sharding complexity; "schema-less" data still has an implicit schema apps must version | MongoDB, Couchbase |
| Column family | very high write volume, sparse data, horizontal scale | hard modeling; row-key design takes iterations | Cassandra, Scylla |
| Graph | relationship traversal, read-heavy | steep learning; changing relationship types is expensive (rebuild every edge) | Neo4j, Tiger Graph |
| NewSQL | SQL + ACID + horizontal scale, geo-distribution | newer, some DBaaS-only | CockroachDB, VoltDB |
| Cloud native | low ops burden, easy experiments | varied models, hiring, cloud lock-in | Snowflake, Redshift, Datomic |
| Time-series | append-only telemetry/analytics over time windows | not general purpose; append-only mindset | InfluxDB, kdb+, Timestream |

**Aggregate orientation** (all NoSQL): operate on whole related structures; distributes and reads/writes fast, but aggregate boundaries are hard to get right and cross-aggregate analysis is hard. Choosing single vs split aggregates = duplication vs render/change ease — model both, pick per actual change pattern.

## ch-7 — Service Granularity {#ch-7}

**Modularity** = breaking into parts; **granularity** = size of the parts — and granularity is where distributed systems actually hurt. Size is what a service *does*, measured (imperfectly) by statement count and number of exposed operations, never by class/LOC counts or "micro means small" instinct. The single-responsibility principle is too subjective to settle arguments ("is notification one thing or three?"); replace opinion with the two opposing force sets and an explicit trade-off conversation with the business.

**Granularity disintegrators** — reasons to split (usually several apply, not one):

| Disintegrator | Trigger question | Objective evidence | Payoff |
|---|---|---|---|
| Service scope & function | doing unrelated things? | weak cohesion across a broad noun (profile + preferences + comments = "customer") vs strong cohesion within one verb (SMS/email/letter = "notify") | single-purpose cohesion |
| Code volatility | changes isolated to one part? | VCS change rates (postal-letter code weekly, SMS/email twice a year → split letter out) | smaller test scope, lower deploy risk |
| Scalability & throughput | parts scale differently? | measured demand (SMS 220k/min, email 500/min, letter 1/min) | independent scaling, lower cost, better MTTS |
| Fault tolerance | one part's crashes take down critical functions? | frequent OOM in email kills SMS too | failure isolation |
| Security | some functions need higher access control? | PCI/credit-card ops mixed with profile ops in one service | service-level access boundary |
| Extensibility | context keeps growing? | payment types keep being added | add a service, not retest everything — apply only when growth is *known/confirmed*, not speculative |

Name test: after any split, the leftover must still form a strongly cohesive, nameable service. "Email Service + Non-Email Service" is the smell that the split is wrong — split fully or not at all.

**Granularity integrators** — reasons to merge (or not split):

| Integrator | Trigger question | Consequence of ignoring |
|---|---|---|
| Database transactions | does the business require all-or-nothing writes across the parts? | registration half-commits; complex error-prone compensation (ch-12) |
| Workflow & choreography | do the parts talk constantly? | transitive-dependency fault chains; ~300 ms latency per hop (5 hops ≈ +1.5 s); rule of thumb — if most requests span services, merge; weigh criticality of the cross-service requests, not just their percentage |
| Shared code | is shared *domain* code a large fraction (e.g., >40%) or fast-changing? | lockstep redeploys defeat the split; infra cross-cutting code (logging/auth) does NOT count |
| Data relationships | can the data even be split into per-service bounded contexts? | every operation needs the other service's table → chatty interservice reads; fewest-trade-off integrator — table entanglement often decides |

Resolution protocol: convert the tension into one business question and let the sponsor choose. Template: "We want to split for ⟨disintegrator⟩, but that costs ⟨integrator⟩. Which matters more to the business?" Canonical instances:
- Volatility isolation (split) vs ACID transaction (merge) → sponsor chose consistency; stayed one service.
- ACID consistency (merge) vs sensitive-data access control (split) → CIO priority on security won; stayed split, consistency mitigated separately.
- Extensibility for new payment types (split) vs responsiveness of multi-type payment workflows (merge) → only 2–3 new types expected; responsiveness won.

Sysops worked outcomes: ticket assignment + routing merged into one service (assignment can't complete without routing — tightly bound synchronous workflow beats change isolation; volatile assignment code isolated via internal namespaces instead — *design, not architecture*). Customer registration kept as one consolidated service (all-or-nothing registration is a hard business requirement; PCI concerns mitigated with tokenization + security library at API gateway and service mesh — again design substituting for an architectural split).

## ch-8 — Reuse Patterns {#ch-8}

Code reuse is trivially cheap in a monolith and a coupling decision in distributed architecture. Four techniques:

| Technique | Best when | Key advantages | Key disadvantages |
|---|---|---|---|
| **Code replication** | tiny, static, one-off code (marker annotations, frozen utilities) | preserves bounded context, zero sharing | bug fixes must be hand-propagated everywhere; no versioning |
| **Shared library** (compile-time) | homogeneous stack, low-to-moderate change rate | versioning ⇒ backward compatibility + agility; no runtime risk or latency | dependency-management mess as libraries multiply; duplication across polyglot stacks; version communication/deprecation pain |
| **Shared service** (runtime) | polyglot environments, high-volatility shared logic | one deploy updates all consumers; no duplication; preserves bounded context | runtime change risk (a "simple" deploy can break everyone), network/security latency, must scale with consumers, availability dependency, endpoint versioning is subjective and multi-protocol |
| **Sidecar / service mesh** | *operational* cross-cutting concerns (logging, monitoring, auth, service discovery, circuit breakers) | consistent isolated coupling across polyglot services; one owning infra team | one sidecar per platform; sidecar bloat if abused |

Shared-library granularity: avoid one coarse `SharedStuff.jar` — a change forces retest/redeploy of every consumer; prefer fine-grained, functionally partitioned libraries (favor change control over dependency management). Always version; tailor deprecation per library's change rate (global "keep last N versions" policies cause churn on hot libraries); **never depend on LATEST** — emergency deploys then meet surprise incompatibilities. Versioning is "the ninth fallacy of distributed computing: versioning is simple."

**Sidecar rule**: operational coupling only, never domain classes (Customer, Address) — putting domain types in the sidecar recreates the coupling microservices exist to avoid. Sidecar is an **orthogonal reuse pattern** (cross-cutting concern intersecting domain seams at right angles — architectural Decorator). Utility-code threshold from the saga: if fewer than ~half the teams need a library, it doesn't belong in the sidecar.

**When reuse adds value**: reuse is *discovered* via abstraction but *operationalized by slow rate of change*. OSes and stable frameworks are great coupling targets; fast-changing internal domain capabilities are terrible ones. The SOA-era single canonical Customer service failed twice over: complexity to serve every domain, and every change rippling everywhere. Platforms work as reuse targets because a well-designed API hides an aggressively changing implementation behind a slowly changing contract.

## ch-9 — Data Ownership and Distributed Transactions {#ch-9}

**Ownership rule of thumb: the service that performs writes to a table owns the table.** Read access never confers ownership. Three scenarios:

- **Single ownership** (one writer): assign owner, done. Resolve these first to clear the field.
- **Common ownership** (most/all services write, e.g., Audit): don't fall back to a shared schema — create a dedicated owning service; other services send writes to it (fire-and-forget via persistent queue if no reply needed; request-reply/REST if a key or confirmation must come back).
- **Joint ownership** (a few same-domain services write, e.g., Catalog + Inventory on Product) — four techniques:

| Technique | Mechanism | Advantages | Disadvantages |
|---|---|---|---|
| **Table split** | split the table (Product → Product + Inventory), each service owns its half | preserves bounded context, single ownership | table restructuring; the halves must be synchronized (create/delete product ⇒ notify) — availability-vs-consistency choice per CAP; sync = consistency but slower, async = fast but eventual |
| **Data domain** (shared schema) | both services own the shared tables in one schema | best performance, no service dependency, data consistent, FKs preserved | schema changes now coordinate multiple services; write-governance blurs; re-justify why the services are separate at all |
| **Delegate** | one service is sole owner; others send it their writes | single ownership, schema change control, abstraction | service coupling; non-owner writes are slow, non-atomic, fault-sensitive. Owner choice: *primary domain priority* (owns most CRUD on the entity — usually recommended, patch performance with replicated cache) vs *operational characteristics priority* (highest write rate gets direct DB access — but misassigns domain responsibility) |
| **Service consolidation** | merge the writers into one service | atomicity preserved, good performance | coarser scaling, less fault tolerance, bigger test/deploy scope |

**ACID vs BASE.** Within one service+database, ACID holds (atomicity, consistency, isolation, durability). Spanning services, the business request becomes a **distributed transaction** and loses all four: atomicity is per-service not per-request; constraints can't span commits; committed intermediate data is visible mid-workflow (no isolation); durability is per-service. Distributed transactions are **BASE**: **b**asic **a**vailability (all participants expected up), **s**oft state (the request is in flight, state possibly unknown), **e**ventual consistency.

**Eventual-consistency patterns** (how out-of-sync data converges):
| Pattern | Mechanism | Advantages | Disadvantages |
|---|---|---|---|
| **Background synchronization** | nightly/periodic external process re-syncs sources | services decoupled; best end-user responsiveness | slowest consistency; the sync process needs write access to everyone's tables — *breaks every bounded context* and duplicates business logic (the remove_date rule now lives in three places); suitable only for closed, self-contained heterogeneous systems |
| **Orchestrated request-based** | orchestrator completes all updates during the request | data timely and consistent; atomic-feeling business request | user waits; complex error handling; usually needs compensating transactions, and compensation itself can fail — then human intervention |
| **Event-based** | owner publishes event; participants subscribe (durable subscribers / persisted streams) | fast, decoupled, timely | error handling complex: broker retries → dead-letter queue → automated repair → human |

## ch-10 — Distributed Data Access {#ch-10}

Four patterns for *reading* data another service owns:

| Pattern | Mechanism | Advantages | Disadvantages |
|---|---|---|---|
| **Interservice communication** | just call the owner | simple; no data-volume limit | network+security+data latency stack up (can approach ~1 s per lookup chain); static coupling — owner down ⇒ you're down; owner must co-scale with you |
| **Column schema replication** | replicate the needed columns into your table; owner pushes changes async | fast local joins; no runtime dependency | data consistency/synchronization burden; ownership governance erodes (you *can* write the replica); best reserved for aggregation/reporting or when nothing else fits |
| **Replicated caching** | owner populates an in-memory cache replicated read-only into consumers | in-memory speed; consumer survives owner outage (after initial load); consistent; ownership preserved | owner must be up before the *first* consumer instance starts; infeasible for large volumes (cache × instances = total RAM) or high update rates; cache-cluster config painful in cloud/dynamic-IP environments (products: Hazelcast, Ignite, Coherence) |
| **Data domain** (shared schema) | both services read the shared tables | fastest, no dependency, consistent, FKs and views preserved | broader bounded context — schema change hits multiple services; write governance; wider data access than security may want |

Selection logic (as run in the saga): consolidation impossible across domains → data domain barred by the "one service, one schema" rule → interservice calls too slow for a hot loop → measure the data (900 experts × 1.3 KB ≈ 1.2 MB, near-static, few instances) → replicated cache wins; record startup-order dependency and license cost as ADR consequences.

## ch-11 — Managing Distributed Workflows {#ch-11}

Coordination = combining services into domain workflows. Two patterns; never say always/never.

**Orchestration**: one orchestrator *per workflow* (a global ESB-style orchestrator recreates the coupling microservices avoid) holds workflow state, error handling, retries, notifications. Happy paths look wasteful; the payoff is that error paths (payment rejected, item back-ordered) need *no new communication links* — the orchestrator already talks to everyone. Trade-offs: + centralized workflow, error handling, recoverability, queryable state; − responsiveness bottleneck, single point of failure, lower scale, higher coupling.

**Choreography**: services pass the workflow peer-to-peer (dance partners; moves planned in advance, no conductor). Happy path is simpler and faster; every error scenario *adds* communication links, and compensating messages must fan out from wherever the failure was noticed. Trade-offs: + responsiveness, scalability, fault tolerance (no single choke point), decoupling; − distributed workflow ownership, state management, error handling, recoverability.

**Semantic coupling law**: every workflow has inherent (semantic) coupling mandated by the domain; implementation can never *reduce* it — only preserve or worsen it. Technically partitioned architecture "smears" a domain concept across layers, adding implementation complexity on top of semantic complexity; model the implementation as close to the domain semantics as possible. Corollary: the more workflow steps and error paths, the more an orchestrator earns its keep — orchestrator utility rises with workflow complexity.

**Workflow state in choreography** (no natural state owner), three options:
| Option | Mechanism | Trade-off |
|---|---|---|
| **Front Controller** | first service in the chain owns workflow state | trivial state query, pseudo-orchestrator; but extra state + chatter in a domain service, hurts performance/scale |
| **Stateless choreography** | no stored state; snapshot rebuilt by querying every service | maximally decoupled, high performance; state reconstruction complex and costly, blows up with workflow complexity |
| **Stamp coupling** | workflow state travels inside the message contract, each service updates its slice | no state-owner queries needed; larger contracts, still no single just-in-time status endpoint |

Decision method (Sysops ticket workflow): list the concrete concerns (workflow control, state query, error handling), score each pattern per concern in a small table, count and weigh — orchestration won on workflow control + error handling; state query tied. Sweet spots: choreography for responsive/scalable workflows with simple or rare errors; orchestration for complex workflows with boundary/error conditions.

## ch-12 — Transactional Sagas {#ch-12}

A saga (Garcia-Molina 1987; Richardson's microservices form) = a sequence of local transactions, each publishing the trigger for the next; failures unwind via compensating updates. That classic description is only 1 of 8 patterns from the communication × consistency × coordination matrix:

| Pattern | Comm | Consistency | Coordination | Coupling | Complexity | Responsiveness/availability | Scale/elasticity |
|---|---|---|---|---|---|---|---|
| **Epic Saga(sao)** | sync | atomic | orchestrated | very high | low | low | very low |
| **Phone Tag Saga(sac)** | sync | atomic | choreographed | high | high | low | low |
| **Fairy Tale Saga(seo)** | sync | eventual | orchestrated | high | very low | medium | high |
| **Time Travel Saga(sec)** | sync | eventual | choreographed | medium | low | medium | high |
| **Fantasy Fiction Saga(aao)** | async | atomic | orchestrated | high | high | low | low |
| **Horror Story(aac)** | async | atomic | choreographed | medium | very high | low | medium |
| **Parallel Saga(aeo)** | async | eventual | orchestrated | low | low | high | high |
| **Anthology Saga(aec)** | async | eventual | choreographed | very low | high | high | very high |

Reading the matrix (from ch-15's meta-analysis): coupling inversely correlates with scale/elasticity and (nearly) with responsiveness/availability. Atomicity is the single worst coupling amplifier; whichever two dimensions you loosen, keeping atomic consistency keeps you in the left half of the table.

- **Epic(sao)**: mimics the monolith — the default architects reach for out of familiarity and stakeholder "must be synchronized" demands. A pattern's existence proves commonality, not solvability: compensating-update failure modes are legendary. Prefer alternatives when possible.
- **Phone Tag(sac)**: atomicity without an orchestrator — coordination logic (undo, routing) leaks into every domain service; the front controller grows mediator-complex. Only for simple workflows needing a bit more scale; error paths are slower than Epic.
- **Fairy Tale(seo)**: drop atomicity, keep the easy parts (orchestrator, sync). Each service owns its own transaction; orchestrator manages workflow and compensations without a live transaction. The popular, balanced choice.
- **Time Travel(sec)**: sync + eventual + choreographed; fits chain-of-responsibility / pipes-and-filters, fire-and-forget throughput; workflow logic embedded per service, so simple workflows only.
- **Fantasy Fiction(aao)**: async + atomic + orchestrated — attempts to speed up Epic with async but the mediator must now track overlapping pending transactions (ordering, deadlocks, races); usually a worse Parallel Saga.
- **Horror Story(aac)**: async + atomic + choreographed — strictest consistency with the two loosest coordination choices; every service tracks undo state for out-of-order pending transactions. The named worst case; the fix is dropping atomicity (→ Anthology), not more cleverness.
- **Parallel(aeo)**: async + eventual + orchestrated — mediator for complex workflows, async for parallelism, per-service transactions; the book's recommended workhorse for complex high-scale workflows.
- **Anthology(aec)**: message queues, no orchestrator, per-service transactions — maximum throughput/scale; poor for complex workflows or messy consistency errors (stamp coupling can carry state).

**Compensating updates: the failure catalog** (why atomic distributed transactions bite):
- No isolation: mid-saga commits are visible; downstream consumers (e.g., an Analytics queue reader) may act on data you're about to un-commit — *side effects* that undo can't reach ("turtles all the way down").
- Compensation can itself fail — the system lands in an inconsistent state with a confused user and no automated way back.
- Semantic coupling of the end user to internal workflow: forcing the expert to retry "mark complete" because the *survey* insert failed couples the user to a business step they shouldn't care about.
- Responsiveness: user waits while compensation unwinds.
- Trade-off summary: compensations restore prior state and allow retry-from-start; state management gives better responsiveness at the cost of temporarily out-of-sync data.

**State management alternative**: model the saga as a **finite state machine** (states + transition actions, e.g., START→CREATED→ASSIGNED→ACCEPTED→COMPLETED→CLOSED with REASSIGN and NO_SURVEY error states). On non-critical failure, record an error state (NO_SURVEY), respond success to the user, and repair asynchronously via retries/automation/human escalation. Keep the state-transition table explicit so developers implement triggers and error paths from it.

Management technique: annotate service entry points with the sagas they join (`@Saga(Transaction.NEW_TICKET)`); a trivial repo-walking tool then answers "which services participate in saga X?" — defining test scope and change blast radius for any workflow modification.

## ch-13 — Contracts {#ch-13}

Contracts cut across all three C's — they're how anything wires to anything (method signatures, REST, queue payloads, transitive dependencies). Spectrum from **strict** (RMI/gRPC-style: names, types, ordering exact) to **loose** (bare name-value JSON/YAML).

| | Advantages | Disadvantages |
|---|---|---|
| **Strict** | guaranteed fidelity; versioned evolution; build-time verification; self-documenting | tight coupling — every change ripples to all users; version-count explosion without a deprecation strategy |
| **Loose** | maximal decoupling; easiest evolution; polyglot lingua franca (name-value pairs) | no built-in fidelity (typos, missing fields); needs fitness functions to be safe |

Guidance:
- Strict contracts create brittleness precisely where architecture can least afford it — the glue; use them only when the coupling is genuinely semantic (things that must change together). REST/GraphQL sit mid-spectrum: modeling *resources* means additive changes don't break consumers.
- Keep contracts at **need-to-know**: if Wishlist needs only `name` from Profile, contract only `name`. Contracting the whole entity "for future proofing" means unrelated Profile changes break Wishlist — accidental stamp coupling.
- **Consumer-driven contracts** invert push to pull: each consumer hands the provider a contract test for exactly the fields it needs; the provider runs all consumer contracts green in its CI. Gives loose coupling *and* fidelity, at the price of engineering maturity (teams must actually run and honor the tests) and two interlocking mechanisms instead of one schema tool.

**Stamp coupling** — passing a large structure of which each service touches a slice:
- Legitimate: industry-standard documents (travel-itinerary XML); *workflow state management in choreography* (contract carries status/transactional state; each service updates its slice — enables complex workflows without a mediator, see ch-11/12).
- Anti-pattern: over-specified contracts (brittleness) and bandwidth blowout — 2,000 req/s × 500 KB payload = 1 GB/s where the needed field was 200 bytes ("bandwidth is infinite" fallacy).
- Contract-tightness selection is per-edge, not global: in the Sysops workflow, orchestrator↔ticket services got tight contracts (high semantic coupling, change together); notification/survey got loose; the mobile app got loose *because app-store review makes coordinated deploys slow* — deployment cadence is a contract-coupling input.

## ch-14 — Managing Analytical Data {#ch-14}

Three generations of serving analytics from operational systems:

- **Data Warehouse**: extract from all sources, transform to one denormalized **Star Schema** (facts + dimensions), analyze centrally via SQL-ish tools. Failure modes: *integration brittleness* (every source schema change breaks ingestion transforms), extreme partitioning of domain knowledge (domain experts needed twice — in systems and in warehouse queries), standalone complexity, and historically weak business value for the investment; synchronization pipelines bottleneck and leak load into operational systems. Technical partitioning of data, at odds with domain-partitioned architecture.
- **Data Lake**: inverse reaction — load raw, transform on demand ("load and transform"); better for ML (near-raw data) and avoids useless up-front modeling. Still centralized and technically partitioned; new problems: asset discovery without domain context, PII/re-identification risk from dumping unstructured data, staleness from batch cadence, quality/testing pushed downstream onto brittle pipelines.
- **Data Mesh** (Dehghani): decentralized, domain-aligned analytical data. Four principles: **domain ownership of data**; **data as a product** (discoverable, timely, high-quality, consumer-delighting); **self-serve data platform**; **computational federated governance** (compliance/PII/interop policies decided federally, executed as code in each product's sidecar).
  - Core building block: the **data product quantum (DPQ)** — a **cooperative quantum** adjacent to each service: operationally independent, asynchronously synced, eventually consistent, tightly contract-coupled to its service and loosely to the analytics plane. Types: source-aligned, aggregate, fit-for-purpose.
  - Hard rule: DPQ↔service sync must be async + eventually consistent (Parallel(aeo) or Anthology(aec) pattern) — a transactional requirement between operational and analytical data defeats the orthogonal decoupling entirely.
  - Trade-offs: fits microservices, decouples analytical from operational evolution; requires contract coordination per DPQ and tolerance of eventual consistency. Data-quality rule from the saga: for trend analysis, a whole missing day beats a partial day — enforce complete-snapshot-or-nothing with a fitness function, plus consumer-driven contracts between DPQs.

## ch-15 — Build Your Own Trade-Off Analysis {#ch-15}

The book's generic tables are starting points; your architecture will add columns. The method:

1. **Find entangled dimensions** — build the static-coupling diagram (OS/container deps, transitive libraries, persistence, bootstrap integration points, messaging infra); dynamic-only collaborators are excluded. Automate collection from manifests/POMs/observability call graphs where possible.
2. **Analyze coupling points** — model the feasible combinations lightly (skip impossible ones); choose the outcome dimensions you care about (the book used coupling, complexity, responsiveness/availability, scale/elasticity); rate each combination in isolation, then consolidate into a comparison matrix and read off correlations (coupling ∝ 1/scalability).
3. **Assess trade-offs** — fix the most fundamental dimension first (e.g., sync vs async), which prunes the space; iterate on what remains. What's left after the entangled decisions is "just design."

**Trade-off techniques**:
- **Qualitative over quantitative**: two architectures never match enough for true quantitative comparison; hone comparative qualitative ratings backed by many observed cases; testing converts speculation toward engineering.
- **MECE lists** (mutually exclusive, collectively exhaustive): compare like with like (message queue vs ESB is invalid — different category), and check no recent capability was omitted before a long-term decision.
- **Out-of-context trap**: a generic winner (shared library over shared service) flips once situation-specific context lands; finding the narrowest correct context shrinks the option set — that's what "embrace simple design" operationally means.
- **Model relevant domain scenarios**: 2–3 concrete workflows (update one payment type; add a payment type; combined multi-type payment) expose the real bottom-line trade-off (extensibility+agility vs performance+consistency) better than generic force lists.
- **Prefer bottom line over overwhelming evidence**: reduce the analysis to one aggregate question a nontechnical sponsor can answer ("guaranteed start of credit approval vs responsiveness+fault tolerance"); don't drown stakeholders in detail.
- **Avoid snake oil and evangelism**: force any evangelized technique to a good-and-bad assessment; model the scenarios (single pub-sub topic vs point-to-point queues: heterogeneous contracts, data security, per-consumer ops profiles vs extensibility). Don't accept the "opposing foil" role in someone's advocacy — convert the argument to a trade-off table plus fitness functions guarding the feared downside (monorepo accidental-coupling example).

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Plan/design claims a "best" solution or lists only benefits | Name the trade-offs; strive for least-worst, not best | everything in architecture is a trade-off; unlisted downsides are undiscovered, not absent | ch-1, ch-15 |
| Consequential architecture decision made in chat/PR with no record | Write an ADR (context/decision/consequences) | *why* is more important than *how*; rationale is unrecoverable later | ch-1 |
| Design rule exists only in docs/diagrams (layers, allowed deps, size limits) | Encode it as a CI fitness function (ArchUnit/NetArchTest/custom) | manual review catches violations too late; important-but-not-urgent rules get skipped under pressure | ch-1, ch-5 |
| Proposed "quality" goal isn't measurable (agility, robustness) | Decompose composites into measurable characteristics before targeting them | unmeasurable = too vaguely defined to govern or test | ch-1 |
| Plan asserts two services are independent but they share a database, orchestrator, or coupled UI | Count quanta by static coupling — shared coupling point ⇒ one quantum | independent deploy/scale claims are false while a common bootstrap dependency exists | ch-2 |
| Plan chooses communication, consistency, or coordination in isolation | Decide the 3 C's together — each choice constrains the others | e.g., adding async to an atomic choreographed flow lands in Horror Story territory | ch-2, ch-12 |
| Plan proposes breaking up a monolith "because it's a mess" | Demand a business driver mapped to maintainability/testability/deployability/scalability/fault tolerance | without matched drivers the migration spends money without addressing the pain | ch-3 |
| Plan piles synchronous calls between the freshly split services | Re-check the split — chatty synchronous services forfeit modularity's testability/deployability/fault-tolerance gains | transitive sync dependencies re-couple what deployment separated | ch-3, ch-7 |
| Migration plan extracts services piecemeal with no component analysis | Run the decision tree: decomposable? structured → component-based decomposition; mud → tactical forking | seat-of-the-pants extraction unravels coupling strand by strand into a distributed monolith | ch-4 |
| Monolith-to-microservices plan goes straight to fine-grained services + split DB | Move to service-based architecture first (domain services, shared DB) as stepping stone | defers data breakup and ops automation; reveals which domains actually need microservice granularity | ch-4, ch-5 |
| Plan builds a service from a class or partial component | Build services from whole components (leaf-node namespaces), never classes | class-level extraction ignores component boundaries and dependencies | ch-4, ch-5 |
| One component holds a large share of the codebase (e.g., >2σ from mean statements) | Split it along subdomains before migration; if no subdomains, leave it | oversized components couple widely and resist extraction | ch-5 |
| Source files sit in a namespace that other namespaces extend | Flatten: code only in leaf nodes; move root-namespace orphans into named components (incl. `.sharedcode`) | orphaned classes have no component, so no service home | ch-5 |
| Shared `.sharedcode` components approach ~half the codebase | Reconsider distribution — the result will be a shared-library dependency nightmare | high shared fraction means the "separate" services change in lockstep | ch-5 |
| Plan has multiple services reading/writing one shared schema | Check the six data disintegrators vs two integrators before deciding to split or keep | change control, connections, scale, fault tolerance, quantum, DB type vs relationships and ACID | ch-6 |
| Schema change plan touches a table used by several services | Treat drop/rename/retype as breaking; deploy owner+DB together; hunt for forgotten readers | forgotten services fail silently in production until redeployed | ch-6 |
| Plan passes raw table rows across a service boundary | Expose data through a contract that abstracts the schema | contract abstraction lets the schema change without breaking consumers | ch-6, ch-13 |
| Distributed plan multiplies service instances against one database | Budget connections: quota per service, start even, rebalance from max-used/wait metrics | instance × pool growth saturates connections long before load does | ch-6 |
| Plan splits the database in one big-bang migration | Use the five-step process: domains → schemas → per-service connections → separate servers → switch | each step is independently verifiable; synonyms make remaining coupling findable | ch-6 |
| A service connects to two schemas/databases | Route the foreign-domain access through the owning service instead | multi-schema connections break bounded contexts and change isolation | ch-6, ch-9 |
| Plan splits a service citing "single responsibility" alone | Require a measured disintegrator (volatility, scale delta, fault isolation, security, confirmed extensibility) | SRP is subjective; measurements arbitrate | ch-7 |
| Plan splits a service that shares an ACID business transaction, heavy workflow, >~40% shared domain code, or entangled tables | Apply the integrators — consider keeping/merging | consistency, latency (~300 ms/hop), lockstep deploys, or chatty reads erase the split's value | ch-7 |
| Post-split leftover service is hard to name ("Non-Email Service") | Bad split — re-cut until every part has strong nameable cohesion | naming difficulty is the observable proxy for weak cohesion | ch-7 |
| Granularity dispute stalls in opinions | Convert to one business question and let the sponsor pick (e.g., time-to-market vs consistency) | the trade-off is a business decision wearing technical clothes | ch-7 |
| Plan shares volatile domain logic via one coarse library | Prefer fine-grained versioned libraries; never depend on LATEST | coarse libraries force whole-fleet retests; LATEST breaks emergency deploys | ch-8 |
| Plan centralizes shared behavior in a runtime shared service | Accept runtime change risk + latency + co-scaling + availability coupling — only for polyglot or high-volatility code | a "simple" shared-service deploy can break every consumer at runtime | ch-8 |
| Plan puts domain classes in the sidecar/mesh, or shares an entity service enterprise-wide | Sidecar = operational coupling only; reuse targets must have slow rate of change | fast-changing shared domain assets recreate SOA's ripple-everything failure | ch-8 |
| Plan makes a table writable by multiple services | Assign ownership: single writer owns; common → dedicated owner service; joint → split table / data domain / delegate / consolidate | uncontrolled multi-writer tables break bounded contexts and change control | ch-9 |
| Plan assumes an ACID transaction across services | It's BASE: no atomicity/isolation across services — design the eventual-consistency path explicitly | mid-workflow commits are visible; failures leave data half-written | ch-9 |
| Plan adds a background job that writes other services' tables to re-sync data | Reject for bounded-context architectures; sync via events or orchestrator | the sync process becomes a shadow owner duplicating business logic | ch-9 |
| Service needs frequent reads of data it doesn't own | Choose by data size/volatility/consistency: interservice call, column replication, replicated cache, or shared data domain | each pattern trades latency, consistency, ownership, and RAM differently | ch-10 |
| Plan adopts replicated cache for cross-service reads | Verify data volume (cache × instances), update rate, and startup ordering first | large/volatile data or cold-start dependency sinks the pattern | ch-10 |
| Workflow has complex error/alternate paths but plan uses choreography | Prefer orchestration (one orchestrator per workflow, not a global ESB) | error paths add links to choreography but reuse orchestration's existing ones | ch-11 |
| Plan adds layers/indirection hoping to simplify a messy domain workflow | You can't reduce semantic coupling via implementation — only worsen it; model implementation on domain semantics | technical partitioning smears domain concepts across layers | ch-11 |
| Choreographed plan needs workflow status | Pick a state strategy: front controller, stateless snapshot queries, or stamp-coupled state in messages | each trades chatter, complexity, and queryability differently | ch-11, ch-13 |
| Plan mixes async + choreography with atomic consistency | Horror Story — drop atomicity (→ Anthology) or add orchestration; don't attempt all three | per-service undo tracking of out-of-order pending transactions is the worst complexity in the matrix | ch-12 |
| Plan reaches for the classic orchestrated atomic saga by default | Consider Fairy Tale(seo) or Parallel(aeo) first — eventual consistency removes the worst coupling | Epic Saga's compensating updates have no isolation, can fail, and couple users to internal steps | ch-12 |
| Saga plan relies on compensating updates | Enumerate: side effects on already-consumed data, compensation failure, user-visible retries | compensation is not a rollback; downstream actions may be irreversible | ch-12 |
| Non-critical step fails mid-saga (e.g., survey send) | Prefer state management: record error state, respond success, repair async (retry → automation → human) | users shouldn't wait on or retry steps they don't own | ch-12 |
| Contract includes fields the consumer doesn't use ("future proofing") | Cut to need-to-know; unrelated provider changes then can't break the consumer | over-specified contracts are brittleness with no benefit | ch-13 |
| Loose name-value contracts chosen for decoupling | Add consumer-driven contract tests in the provider's CI | fidelity must come from somewhere once the schema doesn't provide it | ch-13 |
| Large payload passed at high request rate | Multiply payload × rate before approving (500 KB × 2,000 rps = 1 GB/s) | "bandwidth is infinite" is a fallacy; need-to-know contracts fix it | ch-13 |
| Plan couples analytical pipelines directly to operational schemas (warehouse/lake style) | For distributed architectures prefer data mesh: per-domain DPQs, async + eventually consistent with their service | schema-coupled pipelines are brittle and re-centralize domain knowledge | ch-14 |
| Analytical feed may deliver partial time windows | Enforce complete-snapshot-or-none with a fitness function | partial data skews trends worse than missing data | ch-14 |
| Two options being compared aren't the same category (queue vs ESB) | MECE the comparison: mutually exclusive capabilities, collectively exhaustive options | category mismatch and omitted candidates invalidate the analysis | ch-15 |
| Generic research picked a winner before local constraints were applied | Re-run the analysis in context — added context legitimately flips decisions | out-of-context trap; narrow context also shrinks the option space | ch-15 |
| Stakeholder decision needed on a technical trade-off | Reduce to one bottom-line question; hide the evidence pile | overwhelmed nontechnical stakeholders can't contribute insight | ch-15 |
| Someone (including you) evangelizes a technique as all-upside | Demand the honest bad-parts list; guard feared downsides with fitness functions rather than argue | evangelism inflates positives; trade-offs always return | ch-15 |

## Anti-patterns

- **Big Ball of Mud** (Foote) — no internal structure; detection: event handlers wired to DB calls, no components, most components in the zones of pain/uselessness. Not decomposable as-is; tactical fork or rewrite. (ch-4)
- **Elephant Migration** — "eat the monolith one bite at a time" with no holistic component/dependency analysis; detection: extraction stories with no component inventory or dependency diagram. Produces the **big ball of distributed mud / distributed monolith**. (ch-4)
- **Distributed monolith** — services that must be tested/deployed together in order; detection: coordinated multi-service release trains, one change → many service deploys. (ch-3, ch-5, ch-8)
- **Too-fine granularity by instinct** ("micro means small") — splitting on subjective single-responsibility with no disintegrator evidence; detection: split justification contains no measurement. (ch-7)
- **Hard-to-name leftover service** — "Other/Non-X Service"; detection cue is the name itself; signals a wrong cut. (ch-7)
- **Coarse `SharedStuff` library / LATEST dependency** — detection: one shared artifact most services import; dependency ranges resolving to latest. (ch-8)
- **Enterprise canonical entity service** (SOA-era Customer service) — single shared owner of a fast-changing domain concept; detection: one service in every domain's critical path, changes requiring cross-division coordination. (ch-8)
- **Domain classes in the sidecar** — detection: entity/DTO types in mesh/sidecar config or shared platform layer. (ch-8)
- **Background sync process writing other services' tables** — detection: batch job credentials with write access to multiple service schemas. (ch-9)
- **Horror Story(aac)** — asynchronous + atomic + choreographed; detection: message-driven workflow whose spec demands all-or-nothing consistency with no orchestrator. (ch-12)
- **Fantasy Fiction(aao) as "faster Epic"** — adding async to an orchestrated atomic saga for performance; detection: mediator tracking multiple pending distributed transactions. (ch-12)
- **Compensating-update faith** — assuming compensation always succeeds and nothing consumed the intermediate state; detection: saga design with undo steps but no side-effect or compensation-failure analysis. (ch-12)
- **Stamp coupling by over-specification** — full-entity contracts where one field is used; detection: contract schema ⊃ consumer's field usage; also single shared topic forcing one contract + full data visibility on all consumers. (ch-13, ch-15)
- **Data warehouse/lake reflexes in distributed systems** — central pipelines coupled to operational schemas; detection: ingestion transforms that break when a service changes its schema. (ch-14)
- **Silver-bullet evangelism** — technique advocated without a disadvantages column; detection: proposal/table with an empty "cons" side. (ch-1, ch-15)

## Applicability & exemptions

- **The book's domain is distributed architectures** (microservices, service-based, EDA). Inside a monolith with one ACID database, most of ch-6–ch-14 doesn't fire: transactions are free, reuse is an import, contracts are method signatures. Don't demand sagas, ownership analysis, or contract fitness functions from monolith code.
- **Modularity ≠ distribution**: maintainability/testability/deployability goals can be met by a modular monolith or microkernel; only scale, elasticity, fault isolation, and per-domain characteristics genuinely require distribution (ch-3). Don't flag a well-structured monolith as an anti-pattern.
- **Service-based architecture with a shared database is a legitimate end state**, not an unfinished microservices migration (ch-4, ch-5). Sharing one schema among domain services is allowed; the hard rule is one service ↛ multiple schemas.
- **Data-sharing patterns the book "generally discourages" have sanctioned uses**: data domain for genuinely joint ownership and integrity-critical reads; column replication for aggregation/reporting/high-volume; background sync for closed self-contained heterogeneous systems; stamp coupling for industry-standard documents and choreographed workflow state.
- **Epic Saga(sao) is legitimate** when the business truly requires atomicity and workflow scope is small — all eight saga patterns "have legitimate uses"; the rule is knowing the trade-offs, not banning cells of the matrix.
- **Extensibility as a split driver only with confirmed growth** — wait for an established pattern of context expansion; speculative "we might add types" is not a disintegrator (ch-7).
- **Security splits can be answered by design instead of architecture** — tokenization/encryption + security libraries at API/mesh can satisfy the concern without separate deployment units (ch-7).
- **Consumer-driven contracts assume engineering maturity** — teams that ignore red builds get no fidelity from them; with immature teams, stricter contracts are the safer default (ch-13).
- **Generic tables are starting points**: the ratings (saga matrix, DB types, pattern trade-offs) are qualitative aggregates over many systems; local context can legitimately flip them (ch-15 out-of-context trap). Never cite a table row as overriding measured local evidence.
- All numeric thresholds in this distillation (40% shared code, 300 ms/hop, 500 MB cache, 3σ) are the authors' illustrative heuristics, not standards — recalibrate per system.

## Candidate lexicon rows

| plan splits a service into smaller services | **Disintegrators need integrators** — a split is justified only by measured drivers (volatility, scale delta, fault/security isolation) that survive the integrator check (shared ACID transaction, chatty workflow, shared domain code, entangled tables) | Which measured disintegrator applies, and which integrator did you rule out? | should | plan | src: architecture-hard-parts ch-7 |
| plan lets two or more services write the same table | **Single writer owns the table** — multi-writer tables break bounded contexts; assign one owner, or resolve joint ownership via table split, shared data domain, delegate, or service consolidation | Which one service owns writes to this table, and how do the others submit changes? | should | plan | src: architecture-hard-parts ch-9 |
| plan assumes an all-or-nothing transaction spanning services | **Cross-service = BASE, not ACID** — distributed transactions lose atomicity and isolation; design the eventual-consistency and failure path or merge the services | What happens when the second service's write fails after the first committed? | blocker | plan | src: architecture-hard-parts ch-9 |
| plan combines async messaging and choreography with atomic consistency | **Don't write a Horror Story** — atomicity with the two loosest coordination styles forces every service to track out-of-order undo state; drop atomicity or add an orchestrator | Can this workflow tolerate eventual consistency, or does it need a mediator? | should | plan | src: architecture-hard-parts ch-12 |
| plan models a workflow with several error/alternate paths as choreography | **Orchestrator utility rises with workflow complexity** — error paths add links to choreography but reuse orchestration's existing ones; one orchestrator per workflow, never a global one | How many error scenarios exist, and where does each one's handling live? | judgment | plan | src: architecture-hard-parts ch-11 |
| plan's contract exposes an entity's full schema when the consumer uses a few fields | **Need-to-know contracts** — over-specified contracts break consumers on changes they don't care about and waste bandwidth at scale | Which fields does the consumer actually read, and what's payload × request rate? | should | plan | src: architecture-hard-parts ch-13 |
| plan makes services share a schema, orchestrator, or coupled UI while claiming independence | **Shared coupling point = one quantum** — anything required to bootstrap both services fuses their deploy, scale, and failure scopes | Could each service run and deploy with the other's coupling point absent? | should | plan | src: architecture-hard-parts ch-2 |
| plan puts domain logic in a sidecar, shared platform layer, or fast-changing shared library | **Reuse is operationalized by slow rate of change** — sidecars carry operational coupling only; volatile shared domain assets ripple changes to every consumer | How often does this shared asset change, and who must redeploy when it does? | should | plan | src: architecture-hard-parts ch-8 |
| plan extracts monolith pieces ad hoc, or jumps straight to microservices + split DB | **Decompose by the tree, land on the stepping stone** — check decomposability, use component-based decomposition (or tactical forking for mud), and reach service-based architecture before splitting data | Do we have a component inventory and dependency diagram, and why not domain services first? | should | plan | src: architecture-hard-parts ch-4 |
| plan has a service read another service's data on a hot path | **Pick the read pattern by data shape** — interservice call, column replication, replicated cache, or shared data domain trade latency, consistency, ownership, and RAM; measure volume and volatility first | How big and how volatile is the data, and what breaks if the owner is down? | judgment | plan | src: architecture-hard-parts ch-10 |
| design/plan presents a chosen approach with no downsides listed | **Everything is a trade-off** — if you haven't found the downside, you haven't found it yet; seek the least-worst combination, not the best | What does this choice sacrifice, and who confirmed that's acceptable? | should | review | src: architecture-hard-parts ch-1 |
| consequential architecture decision lands without recorded rationale | **Why beats how (write the ADR)** — context, decision, and consequences must outlive the author; the how can be re-derived, the why cannot | Where is the ADR with the alternatives considered and the trade-offs accepted? | should | review | src: architecture-hard-parts ch-1 |
