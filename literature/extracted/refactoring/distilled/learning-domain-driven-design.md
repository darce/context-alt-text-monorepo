# Learning Domain-Driven Design — distilled

> **Source**: Vlad Khononov, *Learning Domain-Driven Design: Aligning Software Architecture and Business Strategy*, O'Reilly 2021 · extracted from `../learning-domain-driven-design.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory that gives a *classification-first* decision procedure for domain modeling: classify a subdomain as **core / supporting / generic**, then read off the business-logic pattern (transaction script → active record → domain model → event-sourced domain model), architecture (layered → ports & adapters → CQRS), and testing strategy from an explicit decision tree (ch-10). It supplies the boundary rules other sources assume: bounded contexts as ubiquitous-language consistency boundaries (split when one term means two things), the aggregate = transaction-boundary rule with its corollaries (one aggregate per transaction, reference by ID, small aggregates), the context-mapping pattern catalog (partnership / shared kernel / conformist / ACL / OHS / separate ways), and the reverse-mapping trick (implementation complexity is a *detector* for misclassified subdomains). Crucially it is also the strongest **anti-overengineering** source: CRUD/transaction-script is the *correct* design for supporting and generic subdomains, and applying domain models or event sourcing there is a named failure mode with a case study (Appendix A).

## Chapter map

- ch-1 — Analyzing Business Domains: core/supporting/generic subdomains; how to classify and where to stop decomposing
- ch-2 — Discovering Domain Knowledge: ubiquitous language; no translation chains; one meaning per term
- ch-3 — Managing Domain Complexity: bounded contexts; when models must split; language/team/deployment boundaries
- ch-4 — Integrating Bounded Contexts: context-mapping patterns (partnership, shared kernel, conformist, ACL, OHS, separate ways)
- ch-5 — Implementing Simple Business Logic: transaction script & active record; the transactional-behavior bugs
- ch-6 — Tackling Complex Business Logic: domain model — value objects, entities, aggregates, domain services
- ch-7 — Modeling the Dimension of Time: event sourcing; when it earns its cost; snapshots; GDPR
- ch-8 — Architectural Patterns: layered vs ports & adapters vs CQRS; which fits which logic pattern
- ch-9 — Communication Patterns: model translation, outbox, saga, process manager
- ch-10 — Design Heuristics: the tactical decision tree (subdomain → pattern → architecture → test strategy)
- ch-11 — Evolving Design Decisions: subdomain type changes; pain as a signal; refactoring between patterns
- ch-12 — EventStorming: the workshop; when to use it and when not
- ch-13 — DDD in the Real World: brownfield strategy; strangler; undercover DDD
- ch-14 — Microservices: bounded context = widest safe boundary, microservice = narrowest; subdomains as default
- ch-15 — Event-Driven Architecture: event notification vs ECST vs domain event; coupling failure modes
- ch-16 — Data Mesh: analytical (OLAP) models; data mesh = DDD for analytical data
- app-a — Marketnovus case study: five bounded contexts; every misclassification failure mode observed in the wild

---

## ch-1 — Analyzing Business Domains {#ch-1}

A **business domain** is the company's area of activity; **subdomains** are the finer-grained building blocks it needs to operate. Three types, distinguished by competitive advantage and complexity — the classification drives every downstream design decision:

| Subdomain type | Competitive advantage | Complexity | Volatility | Implementation | Problem is… |
|---|---|---|---|---|---|
| **Core** | Yes — how the company differs from competitors | High (must be hard to copy) | High — solutions are emergent, work never done | In-house, best people, most advanced techniques | Interesting |
| **Generic** | No — everyone solves it the same way | High but *solved* ("known unknowns") | Low | **Buy/adopt** off-the-shelf or open source | Solved |
| **Supporting** | No — needed but not differentiating | Low — data-entry screens, ETL, CRUD, input validation | Low | In-house (no product exists) or outsource; fine to cut corners | Obvious |

Classification heuristics (falsifiable questions):
- **Side-business test** (core vs supporting): would someone pay for this capability on its own? If yes → core.
- **Build-vs-integrate test** (supporting vs generic): is hacking your own simpler/cheaper than integrating an existing solution? If yes → supporting.
- **Logic-shape test**: does the logic resemble CRUD/ETL over data-entry input, or algorithms/processes governed by invariants? Former → supporting; latter → core.
- Core subdomains are **not necessarily technical** (jewelry design, analyst expertise). If the software around a non-technical core is just displaying documents and tracking comments, the *software* is a supporting subdomain — design it as such.

Finding boundaries: start from departments/org units (coarse), then **distill**: inside a suspected generic department there may be a core gem (e.g., in a customer-service dept: help desk & telephony = generic, shift management = supporting, incident-routing algorithm = core). Stop drilling when finer grains stop changing design decisions. The precision floor: a **subdomain ≈ a set of coherent use cases** — same actor(s), same business entities, tightly related data. Distill core subdomains aggressively; relax for supporting/generic.

Worked classification (compressed from the book's two fictional companies — note that classification uses *inferred* as well as stated requirements):

| Company | Core | Generic | Supporting |
|---|---|---|---|
| Gigmaster (ticket sales; recommends nearby gigs from users' music/social data) | Recommendation engine; data anonymization (privacy is the differentiator); mobile-app UX (inferred — never stated) | Encryption; accounting; clearing; authN/authZ | Streaming-service & social-network integrations (ETL-shaped); attended-gigs log (CRUD) |
| BusVNext (on-demand bus rides; routes adjusted on the fly) | Routing algorithm (traveling-salesman variant, continuously re-tuned toward fast pickups); ride analytics; app UX; fleet management | Traffic-conditions feed (3rd party); accounting; billing; authorization | Promos/discounts management (CRUD over coupon codes) |

Resulting decisions read straight off the table: core → in-house with the best tooling; generic → off-the-shelf/managed; supporting → outsource-able. Note the promos module *supports* the core pricing strategy yet is itself supporting — proximity to the core does not make something core.

**Domain experts** = the business-side knowledge authorities (requirement originators or end users) — not analysts, not engineers.

## ch-2 — Discovering Domain Knowledge {#ch-2}

"It's developers' (mis)understanding, not domain experts' knowledge, that gets released in production" (Brandolini). Every hand-off translation (domain knowledge → analysis model → requirements → design → code) loses information, like the Telephone game. The fix is the **ubiquitous language**: one language, cultivated with domain experts, used by *all* stakeholders in conversation, docs, tests, and code.

Rules of the language:
- **Business terms only, no technical jargon.** "A campaign can be published only if at least one of its placements is active" ✅; "…if it has at least one record in the active-placements table" ❌. Engineers who only know the table-level view cannot model the domain.
- **One meaning per term** (no ambiguity): if "policy" means both regulatory rule and insurance contract, model two explicit terms.
- **No synonyms**: user/visitor/account used interchangeably usually hides distinct concepts with different behavior — name each in its context.
- A **model** is "a simplified representation that intentionally emphasizes certain aspects while ignoring others" (Wirfs-Brock); it must contain *just enough* to solve its problem (map analogy; "all models are wrong, but some are useful"). Effective abstraction is not vagueness — it "creates a new semantic level in which one can be absolutely precise" (Dijkstra).
- Cultivation is continuous and co-creative: asking questions exposes white spots in the *experts'* own understanding (happy-path-only requirements, undefined concepts) — especially in core subdomains, where the learning is mutual.
- Tools, in order of value: daily usage (the only prerequisite that matters) > wiki glossary (good for nouns; behavior — rules, assumptions, invariants — needs use cases or Gherkin tests, which domain experts can *read* to verify behavior, though they won't *write* them) > static analysis of term usage (e.g., NDepend). Non-English orgs: at least use English nouns for entities so code matches speech.
- Brownfield reality: an established, DDD-free language (often full of table names and tech jargon) already exists; changing spoken habits takes patience — control the language first where you can: docs and source code.

## ch-3 — Managing Domain Complexity {#ch-3}

**Trigger**: the same term carries different meanings for different domain experts (marketing's *lead* = contact-details event; sales' *lead* = long-running sales process). Two traditional non-solutions: (a) one enterprise-wide model / giant ERD — "jack of all trades, master of none," over- and under-engineered at once; (b) prefixing (`MarketingLead`, `CRMLead`) — cognitive load, and nobody speaks the prefixes, so code diverges from language.

The DDD solution: **bounded context** — split the ubiquitous language into smaller languages, each consistent within an explicit boundary. Bounded contexts are the **consistency boundaries of ubiquitous languages**: terminology, principles, and business rules hold only inside.

Key distinctions:
- **Subdomains are discovered; bounded contexts are designed.** Subdomains come from business strategy; context boundaries are a strategic *design* decision. One-context-per-subdomain is valid but not mandatory; a context may span several subdomains, and one subdomain may be usefully modeled twice in different contexts (cardboard-fridge example: two crude models, each fit for one question, beat one 3D model).
- Language consistency gives the *widest* possible boundary; you may decompose further for team formation, independent scaling, or divergent deployment lifecycles — but **never split a coherent set of use cases (same data, same actors) across contexts**, or every change requires coordinated multi-context deployment.
- Size is not a goal. Wider = harder to keep consistent; smaller = more integration overhead.
- **Physical boundary**: each bounded context is a separately implemented/versioned/deployed service or project; subdomains inside it are logical boundaries (namespaces/modules/packages).
- **Ownership boundary**: one bounded context = exactly one owning team (a team may own several contexts; never two teams on one context).

## ch-4 — Integrating Bounded Contexts {#ch-4}

Contexts must integrate; the touchpoints are **contracts**. The pattern chosen is a function of team collaboration quality and power balance:

| Pattern | Group | Who bends | Use when | Red lines |
|---|---|---|---|---|
| **Partnership** | Cooperation | Both, ad hoc, two-way coordination | Well-communicating teams (often same org, dependent goals); needs continuous integration | Poor fit for geographically distributed / low-communication teams |
| **Shared kernel** | Cooperation | Both co-own a small shared model (ideally only integration contracts/data structures) | Cost of duplication > cost of coordination — i.e., volatile shared model (⇒ naturally core subdomains); legacy-modernization interim; same-team contexts needing explicit contracts | Violates one-team-per-context — must be justified, minimized, and every change triggers integration tests in all users |
| **Conformist** | Customer–supplier (upstream dictates) | Downstream adopts upstream's model wholesale | Upstream contract is industry standard or good enough; downstream cedes autonomy | If a conforming context conforms to a mess, it becomes a mess |
| **Anticorruption layer (ACL)** | Customer–supplier (upstream dictates) | Downstream translates upstream's model into its own | Downstream holds a **core subdomain**; upstream model is inefficient/legacy-messy; upstream contract changes often | Translation cost — don't pay it for a model that's fine as-is |
| **Open-host service (OHS)** | Customer–supplier (consumers favored) | Upstream publishes an integration-oriented **published language** decoupled from its implementation model | Supplier wants to evolve internals freely and/or serve many consumers; supports multiple concurrent versions | The published language is *not* the internal ubiquitous language |
| **Separate ways** | No collaboration | Nobody — duplicate the functionality | Collaboration costs more than duplication: communication problems, easily integrated generic functionality (e.g., a logging framework), irreconcilable models | **Never for a core subdomain** — duplicating strategic functionality defeats the strategy |

The **context map** plots all contexts and their integration patterns — it reveals high-level design, team communication patterns, and organizational pathologies (e.g., every consumer of one upstream team building an ACL). Maintain it as a shared, per-team-updated artifact; one context pair can legitimately carry multiple patterns.

## ch-5 — Implementing Simple Business Logic {#ch-5}

**Transaction script** (Fowler): business logic organized as procedures, one per public operation; may hit the DB directly. The one non-negotiable requirement: **each operation is a transaction** — succeeds or fails atomically, never leaves invalid state. Deceptively easy to get wrong; three canonical corruption bugs:

1. **Missing transaction**: two writes (UPDATE users + INSERT visits_log) without a wrapping transaction → crash between them corrupts state. Fix: one DB transaction.
2. **Distributed writes**: DB update + message-bus publish cannot share a transaction → fix with CQRS projections (ch-8) or the **outbox** pattern (ch-9); avoid distributed transactions.
3. **Implicit distributed transaction**: even `UPDATE users SET visits=visits+1` is distributed — the *response to the caller* is the second participant. If the response is lost, the caller retries and the counter increments twice. Fixes: make the operation **idempotent** (caller passes the new absolute value) or use **optimistic concurrency** (`WHERE visits = @expected`).

Micro-example (the `LogVisit` bug family, compressed to scenario→outcome):

| Variant | Scenario | Outcome | Fix |
|---|---|---|---|
| No transaction | UPDATE users.last_visit, then INSERT into visits_log; crash between them | User updated, log missing — silent inconsistency | One DB transaction around both |
| DB + bus | UPDATE users, then publish to VISITS_TOPIC; publish fails | State changed, nobody notified | Outbox (ch-9) or CQRS projection (ch-8) |
| DB + caller | `visits = visits+1`; response to caller lost; caller retries | Counter +2 instead of +1 | Idempotent write (caller supplies absolute value) or `WHERE visits=@expected` (optimistic concurrency) |

Fits: supporting subdomains, ETL, adapters to external systems / ACL internals. **Never for core subdomains** — duplication across scripts drifts out of sync as logic grows. It is not an anti-pattern; it is the substrate all other patterns build on (the application layer of a domain model *is* a transaction script).

**Active record** (Fowler): objects that wrap a DB row/tree, encapsulate CRUD + ORM mapping; a transaction script then manipulates these objects. Use when logic is still simple but data structures are complicated (hierarchies, many-to-many). Distinctive shape: data structure with public getters/setters, behavior living *outside* the object. Also known pejoratively as "anemic domain model" — Khononov rejects the pejorative: it's the correct tool for simple logic; using a fancier pattern there **adds accidental complexity**.

**Be pragmatic**: at extreme scale, ask whether one corrupt record in a million actually matters to the business (billions of IoT events, 0.001% loss) — consistency guarantees may be relaxed *consciously*, weighing business risk.

## ch-6 — Tackling Complex Business Logic {#ch-6}

**Domain model** (Fowler; Evans's tactical patterns are its building blocks): for complex state transitions, business rules, and **invariants** (rules protected at all times — e.g., the ticket-SLA/escalation rule net). Building blocks share one theme: business logic first; objects are plain (no framework/infrastructure dependencies).

**Value objects** — identified by the composition of their values; no ID field (an ID on a color row is a bug generator); **immutable** (any change returns a new instance); equality by value. Cure for **primitive obsession**: `PhoneNumber.Parse("…")`, `Height.Metric(180)`, `Color.MixWith(...)` centralize validation + manipulation logic, make illegal states unrepresentable, and let short names carry intent (`country` of type `CountryCode`). When to use: *whenever you can*; especially for properties of entities, statuses, and **always for money** (primitive money ⇒ rounding/precision bugs and scattered logic). Strings in Java/.NET are the canonical value object.

**Entities** — require an explicit, unique, immutable-for-life ID (namesake people ≠ same person); mutable state; described by value objects. Not implemented standalone — only inside aggregates.

**Aggregates** — an entity hierarchy forming a **consistency-enforcement boundary**:
- State changes only via the aggregate's public interface (**commands**); external code reads only. All related business logic lives inside — nothing left to duplicate in the application layer.
- Application layer script: load → execute command → persist → return result — with a **concurrency check**. Storage must support optimistic concurrency (version field: `UPDATE … WHERE id=@id AND agg_version=@expected`).
- **Aggregate = transaction boundary**: all its changes commit as one atomic transaction, and **no system operation may assume a multi-aggregate transaction**. Needing to commit two aggregates together *is the definition of wrong aggregate boundaries*.
- Boundary rule: include only what the aggregate's logic needs to be **strongly consistent**; everything eventually-consistent lives outside, **referenced by ID only** (`UserId _customer`, not `User _customer`). Test: if this data were eventually consistent, could the aggregate's decisions corrupt state? (Unread-message counts drive reassignment ⇒ messages belong inside the Ticket aggregate.)
- **Keep aggregates as small as possible** — big aggregates = big transactions = contention and scale pain.
- **Aggregate root**: exactly one entity in the hierarchy is the public interface; internal entities are reached only through it.
- **Domain events**: past-tense messages (`TicketEscalated`) describing significant business happenings, published by the aggregate as part of its public interface, carrying all event-relevant data.
- Everything — names, members, commands, events — in the bounded context's ubiquitous language.

Micro-example (invariant that fixes the boundary): rule "escalated ticket unopened within 50% of the SLA window → auto-reassign" reads escalation flag + remaining time + *unread messages for the assigned agent*. If read-receipts were eventually consistent, tickets would be wrongly reassigned en masse — so `Message` entities belong **inside** the Ticket aggregate; customer, products, and agent are outside, held as `UserId`/`ProductId`.

Aggregate design checklist (compressed):
1. Commands are the only write path (plain methods, or command parameter objects dispatched to `Execute(cmd)` — author prefers the explicit objects).
2. Version field + compare-and-set on save (concurrency exception → caller retries).
3. Every datum inside is there because some invariant needs it strongly consistent — justify each member.
4. Cross-aggregate references are IDs.
5. One root; internal entities unreachable from outside.
6. Domain events named in past tense, carrying event-scoped data (ticket-id, reason, time), appended by the aggregate, published via outbox (ch-9).

**Domain services** — stateless objects hosting logic that spans aggregates or belongs to none (e.g., response-deadline calc from ticket + department policy + shifts). They may *read* many aggregates but are **not a loophole** around one-aggregate-per-transaction.

Why this reduces complexity (Goldratt's **degrees of freedom**): invariants make dependent fields functions of a few free variables — a class with five independent setters has five degrees of freedom; one where B, C, E derive from A and D has two. Aggregates and value objects encapsulate invariants, shrinking the state space you must reason about.

## ch-7 — Modeling the Dimension of Time {#ch-7}

**Event sourcing**: persist every state change as a domain event; events are the **source of truth**; current state is a **projection** (fold of events). A state table shows *where* each lead is; only events show *how it got there* — how many calls, which corrections, what timing — the data the business needs to optimize the process.

- **Event store**: append-only; minimum API = fetch events by entity + append with `expectedVersion` (optimistic concurrency). Nothing new conceptually — it's a ledger.
- **Event-sourced domain model** (his preferred term — event sourcing applied to aggregates): every operation follows a four-step script — (1) load the aggregate's events, (2) reconstitute state by folding them through a projector (`Apply(event)` per type; a `Version` counter increments per event, enabling time travel to any past version), (3) execute the command, which *appends new events* rather than setting state, (4) commit new events with the original version as the concurrency check. Multiple projections from the same events (search model retaining *all historical* names/phones so agents can find a lead by an old number; analysis model counting follow-ups per lead) — and you can add projections you never foresaw. Persisting projections for querying requires CQRS (ch-8).
- What state-based storage loses (the lead-table example): the table says a lead is CONVERTED; only events say it took one follow-up, a corrected phone number, and a payment 36 minutes after order — exactly the data needed to optimize the sales process.
- **When it earns its cost** (all are business-driven): monetary/financial transactions; a legally-required or business-critical consistent **audit log**; deep behavioral analytics of a core subdomain; smarter conflict resolution (inspect the concurrent events and decide domain-wise whether they truly conflict).
- **Costs**: learning curve; schema evolution of immutable events is a whole book (Young, *Versioning in an Event Sourced System*); architectural moving parts (CQRS). Unjustified use = pure accidental complexity.
- **Performance FAQ**: projection cost is noticeable only past ~10,000+ events per aggregate; most aggregates live under ~100 events. If you're beyond that, first re-check the aggregate boundary, then apply the **snapshot** pattern (cached projection + replay of the tail). Scales horizontally: shard the event store by aggregate ID.
- **Deletion/GDPR**: **forgettable payload** — encrypt sensitive fields per-aggregate, store keys in a key store; delete the key to "delete" the data.
- Why not "just" a log file / log table / history-table trigger? Log files aren't transactionally consistent with state; log tables rely on developers remembering to write them and degrade into chaos; triggers capture *what* changed but never *why* — killing future projections.

## ch-8 — Architectural Patterns {#ch-8}

Architecture organizes how business logic wires to input/output/persistence — chosen per pattern of business logic, **not** system-wide.

- **Layered architecture** (presentation → business logic → data access; top-down dependencies; optional **service layer** between presentation and logic). Fits transaction script and active record — the business logic *depends on* data access. Service layer needed when the logic pattern requires external orchestration (active record); redundant when transaction scripts already form the public API. Layers (logical) ≠ tiers (physical/deployable).
- **Ports & adapters** (= hexagonal = onion = clean): apply dependency inversion — business logic at the center depends on nothing; it defines **ports** (interfaces), infrastructure implements **adapters**. Required for the domain model: aggregates/value objects must stay persistence-ignorant.
- **CQRS**: one strongly consistent **command execution model** (the sole write model, source of truth, optimistic-concurrency-capable) plus any number of read-only **read models / projections** in whatever stores fit (search index, columnar, cache, flat file); projections are disposable/regenerable. Myth-bust: **commands may return data** (success/failure and fresh values) as long as it comes from the strongly consistent model. Use CQRS when data needs multiple models/stores (polyglot persistence) — and *obligatorily* with event sourcing, which cannot otherwise be queried except by ID.
- Projection modes:
  - **Synchronous** (catch-up subscription): projection engine queries the write store for records changed after its last checkpoint → updates read models → advances the checkpoint. Requires a monotonic checkpoint column (e.g., SQL Server `rowversion`); a checkpoint query that can return lower values later will silently skip records and desync projections. Regeneration = reset checkpoint to 0. **Implement this one first.**
  - **Asynchronous**: committed changes published to a bus; scales better, but duplicated/out-of-order messages corrupt projections and regeneration is hard — build it *on top of* the synchronous path, not instead of it.
- **Scope rule**: pick an architecture per subdomain/module ("architectural slices"), not per system or even per bounded context — a context spanning multiple subdomains needs vertical partitioning, else accidental complexity.

## ch-9 — Communication Patterns {#ch-9}

**Model translation** (mechanics of ACL/OHS):
- *Stateless sync*: proxy embedded in the codebase, or offloaded to an API gateway (Kong, AWS API Gateway…) — the gateway serves versioned published languages. A shared ACL consumed by several downstreams becomes an **interchange context**.
- *Stateless async*: **message proxy** subscribing, transforming, filtering, forwarding. Essential for OHS: **don't leak internal domain events as your public contract** — translate to published-language events; distinguish **private events** (internal) from **public events** (integration).
- *Stateful*: aggregating/batching incoming data or unifying multiple sources (backend-for-frontend) needs its own persistent storage; prefer off-the-shelf stream/batch processors before building one.

**Outbox** — reliable domain-event publishing. Anti-examples first: publishing from inside the aggregate (event escapes before commit; can't be retracted on rollback) and publishing after commit in the application layer (process dies between commit and publish ⇒ event lost forever). Pattern: commit state + new events **in the same atomic transaction** (outbox table; or embedded outbox array in the aggregate document for NoSQL); a **message relay** fetches unpublished events (polling, or transaction-log tailing / change streams) → publishes → marks published. Guarantee is **at-least-once** ⇒ consumers must deduplicate.

**Saga** — a business process spanning multiple transactions/aggregates: listens to events, issues commands, issues **compensating actions** on failure (campaign activation → submit to publisher → confirmed/rejected). Implicitly instantiated by a triggering event; stateless, or event-sourced when it must track history — in which case its command execution goes through an outbox-style relay too. **Consistency rule**: saga participants are only *eventually* consistent; a saga is **not a workaround for wrong aggregate boundaries** — operations needing strong consistency belong in one aggregate.

**Process manager** — like a saga but with a central state and business-logic-based routing. Rule of thumb: **if a "saga" contains if/else to choose the next step, it's a process manager**; it has no single trigger event and must be explicitly instantiated (trip booking: route → approvals → flight → hotel → compensations). Often implemented as a (possibly event-sourced) aggregate.

| | Saga | Process manager |
|---|---|---|
| Flow | Linear event→command matching | Branching, decision-based sequencing |
| Instantiation | Implicit, by observing a trigger event | Explicit — no single source event |
| State | Usually stateless (event-sourced if compensations need history) | Always stateful (the process *is* the state) |
| Command execution | Via outbox-style relay when stateful | Same — separate state transition from command dispatch |

## ch-10 — Design Heuristics {#ch-10}

The bridge chapter: heuristics = rules of thumb, not laws.

**Bounded-context sizing**: size is one of the *least* useful boundary heuristics (Nick Tune). Changes touching multiple contexts are expensive; boundaries get invalidated when the domain is poorly known or requirements churn — precisely the properties of **core subdomains**. Therefore: **start with wider boundaries**, especially around core subdomains, bundling in the subdomains they interact with most; decompose later as knowledge accrues (logical-boundary refactoring is cheap; physical is not).

**Business-logic pattern selection** (the decision tree — the book's hot path):
1. Does the subdomain track money/monetary transactions, need a consistent **audit log**, or need deep behavioral analysis? → **event-sourced domain model**. Otherwise:
2. Is the business logic complex (invariants, rules, algorithms — vs mere input validation; is the ubiquitous language itself describing processes/rules or just CRUD)? → **domain model**. Otherwise:
3. Are the data structures complex (trees/hierarchies)? → **active record**. Otherwise:
4. → **transaction script**.

**Reverse check (misclassification detector)**: pattern choice should co-vary with subdomain type. If a "core" subdomain is well-served by active record, or a "supporting" subdomain demands a domain model — **revisit the subdomain classification** (a core advantage may be non-technical, or the business hasn't noticed a supporting capability became strategic).

**Architecture selection**: event-sourced domain model → **CQRS required**; domain model → **ports & adapters** (persistence-ignorant aggregates); active record → **layered + service layer**; transaction script → minimal 3-layer. Exception: CQRS also pays off wherever multiple persistent models of the same data are needed.

**Testing strategy**: domain model (both variants) → **testing pyramid** (aggregates/value objects are perfect units); active record → **testing diamond** (integration-heavy — logic spans service + data layers); transaction script → **reversed pyramid** (end-to-end — few layers, simple logic). ↔ nuance vs modern-software-engineering ch-Testing: Farley pushes unit-heavy TDD universally; Khononov keys the test distribution to the logic pattern.

**The combined tactical decision tree** (subdomain → logic pattern → architecture → tests), rendered as one lookup:

```
subdomain type?
├─ generic ──────────────► buy/adopt; integrate via transaction script adapter
├─ supporting
│    └─ data structures complex?
│         ├─ no ─────────► transaction script · minimal layered (3) · reversed test pyramid (e2e-heavy)
│         └─ yes ────────► active record · layered + service layer · testing diamond (integration-heavy)
└─ core
     └─ money / audit-log duty / deep behavior analytics?
          ├─ no ─────────► domain model · ports & adapters · testing pyramid (unit-heavy)
          └─ yes ────────► event-sourced domain model · CQRS (mandatory) · testing pyramid
(+ CQRS bolt-on for ANY pattern whose data needs multiple persistent models)
```

Teams experienced in one heavy pattern may rationally use it everywhere; the tree encodes "simplest tool that fits," which he found more efficient in consulting practice. Build your own tree if yours differs — but decide *consciously*.

## ch-11 — Evolving Design Decisions {#ch-11}

Four change vectors: business domain, org structure, domain knowledge, growth.

**Subdomain type changes** (all observed in the wild — see app-a):

| Transition | Trigger example | Consequence |
|---|---|---|
| Core → generic | Competitor productizes your differentiator (BuyIT's routing vs DeliverIT SaaS) | Buy it; stop investing |
| Generic → core | Off-the-shelf underperforms; in-house redesign becomes advantage (inventory prediction; AWS) | In-house, best people |
| Supporting → generic | Open source catches up to your CRUD tool | Replace with adoption |
| **Supporting → core** | *Symptom: supporting logic keeps getting more complex*. If added complexity doesn't raise profit it's accidental business complexity (simplify requirements); if it does, it's a new core | Move in-house, upgrade pattern |
| Core → supporting | Complexity isn't profitable; cut to minimum | Can outsource |
| Generic → supporting | Integration cost of the generic solution exceeds its benefit | Modest in-house version |

Strategic effects: type change alters context-mapping choices (new core needs ACL protection and OHS published language; separate-ways becomes forbidden and must consolidate to customer–supplier) and sourcing (supporting→core must move in-house).

**Tactical signal**: the main indicator of a type change is *pain* — the existing design can't absorb current business needs. Migration paths are cheap **if the original choice was made consciously**:
- *Transaction script → active record*: when data manipulation hurts, encapsulate the complicated structures in active records.
- *Active record → domain model*: identify value objects first; then **make all setters private and let the compiler enumerate every external state mutation**; move that logic inside; find the smallest strongly consistent transaction boundaries → aggregates; reference other aggregates by ID; pick roots and lock internal entities down. Micro-example (compile-error-driven):

  ```
  // before: service mutates the record        // after: behavior lives in the object
  player = repo.Load(id);                      class Player {
  player.Points *= 1 + pct/100.0;  // external   public int Points { get; private set; }
  repo.Save(player);                             public void ApplyBonus(int pct)
                                                   { Points *= 1 + pct/100.0; }
  // step 1: make setter private —             }
  // every red compile error marks logic
  // that must move inside the boundary
  ```
- *Domain model → event-sourced*: model the lifecycle as domain events. Legacy history problem — either **generate past transitions** (approximate best-effort events; verifiable by projecting and diffing, but fabricates a falsely "complete" history) or **model a migration event** (`migrated-from-legacy` snapshot event; honest about the knowledge gap, but haunts every future projection).

**Organizational changes**: growing/distributing teams splits wide contexts (one team per context); communication degradation moves partnership → customer–supplier, and customer–supplier → separate ways (only acceptable for non-core).

**Growth**: unregulated growth ⇒ **big ball of mud**. Antidote = re-verify boundaries at every level: subdomains (re-split by coherent-use-case sets), bounded contexts (a context that got "chatty" — can't finish an operation without calling others — has wrong boundaries; extract focused contexts), aggregates (if an aggregate accumulated data not needed strongly consistent, extract new aggregates — often revealing a hidden model that belongs in another context). Eliminate *accidental* complexity; manage *essential* complexity with the DDD toolbox.

## ch-12 — EventStorming {#ch-12}

Low-tech group workshop modeling a business process as domain events on a timeline; the primary output is **shared knowledge and a ubiquitous language** — the model itself is a bonus. Participants: up to ~10 mixed stakeholders (engineers, experts, PO, UX, support). Ten steps:

| Step | Element (sticky) | Rule |
|---|---|---|
| 1. Unstructured exploration | Domain events (orange) | Past tense; brainstorm until rate slows |
| 2. Timelines | — | Order by occurrence; happy path first, then branches |
| 3. Pain points | Diamond (pink) | Bottlenecks, manual steps, missing knowledge |
| 4. **Pivotal events** | Vertical bars | Context/phase changes — **candidate bounded-context boundaries** |
| 5. Commands | Blue (+ actor on yellow) | Imperative; what triggered the events |
| 6. Policies | Purple | Automation: event → command (with decision criteria) |
| 7. Read models | Green | The data view an actor uses to decide on a command |
| 8. External systems | Pink | Anything outside the explored domain; after this, every command has a source |
| 9. Aggregates | Large yellow | Receive commands, produce events |
| 10. Bounded contexts | Groupings | Related/policy-coupled aggregate clusters |

Variant: run steps 1–4 for a big-picture pass across the whole domain, then a full 10-step session per business process. Output can seed an event-sourced domain model. Uses: build the language, model a process, explore new requirements, **recover lost domain knowledge** (legacy), onboarding, process optimization. **Don't** use it for simple/obvious sequential processes — nothing to learn. Remote sessions: possible (miro), lower bandwidth, cap at ~5 people.

## ch-13 — DDD in the Real World {#ch-13}

DDD pays off *most* on brownfield big-balls-of-mud, and it is **not all-or-nothing** — "domain-driven design is not about aggregates or value objects; it's about letting your business domain drive software design decisions."

**Strategic analysis recipe** (a checklist an agent can run on a codebase + org):
1. Business domain: what does the org sell, to whom, against whom?
2. Subdomains via org chart, then distill. Detection cues — core: secret sauce / IP, *and infamously the worst-designed component everyone hates but the business refuses to rewrite or replace off-the-shelf* (irreplaceable + change = business risk); generic: off-the-shelf/subscriptions/OSS already integrated; supporting: remaining in-house code that changes rarely and triggers little emotion even when ugly.
3. Current design: enumerate high-level components by the **decoupled-lifecycle test** (independently evolvable/testable/deployable — even inside a monorepo or monolith).
4. Tactical fit per component: does the pattern match the logic's complexity? Where are corners cuttable; where is more needed?
5. Chart the de-facto **context map**. Smells: multiple teams in one component; duplicated core implementations; **core subdomain outsourced**; chronic integration friction; awkward models spreading from legacy/external systems into consumers.
6. Where core-subdomain knowledge is lost (undocumented mess), run EventStorming to recover it and seed the ubiquitous language.

**Modernization**: big rewrites rarely succeed — *think big, start small*. First align **logical** boundaries (namespaces/modules/packages, and DB stored-procedure naming/schemas) with subdomain boundaries — safe, non-behavioral refactoring. Then extract physical bounded contexts only where value is highest: multiple teams sharing a codebase, or conflicting models cohabiting. Fix integration patterns: unsustainable partnerships → customer–supplier; ACLs against legacy-model spread and volatile upstream contracts; OHS where a component's internal changes ripple to consumers; separate ways to end friction on non-critical shared functionality.

**Strangler pattern**: new bounded context (strangler) takes all new development; legacy is frozen except hotfixes; functionality migrates until the host dies; a **façade** routes requests during migration and is then deleted. Explicitly permitted rule-bend: strangler + legacy may **temporarily share a database** to avoid distributed transactions — only because the legacy side is dying.

**In-place refactoring nuances**: (1) don't jump transaction script/active record → event-sourced model; go via **state-based aggregates** first — discovering wrong transactional boundaries in an event-sourced aggregate is orders of magnitude worse; (2) domain model can arrive gradually — value objects first, then gather logic, then boundaries by *business-driven* consistency analysis (where is strong consistency truly required, and where is it enforced unnecessarily?).

**Undercover DDD**: use the tools without the branding. Cultivate the language by steering conversations, fixing inconsistent terms in code/docs. Sell tactical rules by their logic, never by authority ("the book says so"): explicit transaction boundaries protect data consistency; one-aggregate-per-transaction proves your consistency boundaries are right; external state mutation ⇒ duplicated logic ⇒ data corruption; logic in stored procedures = duplicated logic that *will* desync; small aggregates because wide transaction scope hurts both complexity and performance. For event sourcing, show domain experts state-based vs event-based views of *their* data — they routinely become its advocates (the audit/insight sells itself).

## ch-14 — Microservices {#ch-14}

A **service** is defined by its public interface; a **microservice** is a service with a *micro public interface* — micro front door, not micro lines-of-code. Encapsulating the DB is interface-minimization (an exposed SQL schema is an infinite interface).

**Naïve decomposition** (one method per service) fails: services must coordinate, so integration methods balloon each interface back up and the system becomes a **distributed big ball of mud** — locally trivial, globally catastrophic. Design goal = balance **local complexity** (inside a service) and **global complexity** (interactions between services; Myers 1970s): a single monolith minimizes global complexity but can maximize local; over-decomposition inverts it. Both extremes are named failures (big ball of mud / distributed big ball of mud).

Uses Ousterhout's **deep modules** directly (↔ accord philosophy-of-software-design ch-4): effective services are deep — small interface over substantial logic; `AddTwoNumbers` as a service is the pathological shallow module. Decompose past the point where interfaces are minimal and interfaces grow back (integration methods) — cost of change rises again.

**Boundary heuristics**:
- **Bounded contexts ≠ microservices.** All microservices are bounded contexts (single team, no conflicting models); not all bounded contexts are micro. Bounded context = **widest valid boundary** (largest consistent monolith); microservice = **narrowest valid boundary**. Everything between is the *safe zone*; outside either edge lies a (distributed) big ball of mud.
- **Aggregates** = the narrowest boundary of all; an aggregate *can* be a service, but ask first: does it communicate with other aggregates in its subdomain? share value objects with them? do its logic changes ripple to them (and vice versa)? The stronger those ties, the shallower it becomes as a standalone service — usually raising global complexity.
- **Default heuristic: align microservices with subdomains.** Subdomains are coherent use-case sets, naturally deep (capability description hides implementation), and their contents change together. Deviate consciously (wider = context; narrower = aggregate) for org/scaling/nonfunctional reasons.
- Deepening tools: **OHS** (published language exposes a smaller, consumer-shaped model → deeper service) and **ACL as a standalone service** (integration complexity offloaded, consumer's interface compressed).

## ch-15 — Event-Driven Architecture {#ch-15}

EDA = asynchronous integration **between** components; event sourcing = state management **inside** one (its fine-grained domain events are not designed for integration). "Pouring events" on a system does not decouple it.

Message taxonomy: **command** (do X; can be rejected) vs **event** (X happened; past tense; can only be compensated, never refused). Three event types:

| Type | Payload | Intent | Use when |
|---|---|---|---|
| **Event notification** | Minimal + link/ID; consumer queries back for details | Alert integration | Security (no sensitive data on the bus; consumers re-authorize), race-sensitive data (query gets last write; can pair with pessimistic lock for exclusive processing) |
| **Event-carried state transfer (ECST)** | Full or delta snapshot of entity state | Async data replication → consumer-local cache | Consumer can live with eventual consistency; fault tolerance (works while producer is down); fan-in performance (BFF) |
| **Domain event** | All data *about the business occurrence* (not the entity's full state) | Model the domain itself; exists even with zero consumers | Sparingly for cross-context integration — prefer a dedicated set of *public* events |

Marriage example: `marriage-recorded` + details link (notification) vs `personal-details-changed{new-last-name}` (ECST — the *what* without the *why*) vs `married{assumed-partner-last-name}` (domain event — closest to the business meaning).

**Coupling failure modes** (from a real system where all consumers subscribed to a CRM's raw event-sourced stream): **temporal coupling** (Reporting must run after AdsOptimization; a 5-minute delay "enforces" ordering — until load/network/outage breaks it), **functional coupling** (two consumers each reimplement the same projection; changes must be applied twice), **implementation coupling** (every consumer must track every new/changed internal event or silently project inconsistent state). Fix: producer applies the **consumer-driven contract** — projects the model consumers need and publishes it as part of its published language; notification events replace delay-based ordering.

**Heuristics**:
1. *Assume the worst* — the network will be slow, servers will fail at the worst moment, events will arrive out of order and duplicated (most often on weekends/holidays). "Driven" means the whole system rides on message delivery, so ban the "things will be okay" mindset: outbox for publishing; consumers that deduplicate and detect/reorder out-of-order messages; sagas/process managers wherever cross-context flows need compensating actions (↔ accord release-it: design for failure).
2. Public vs private events — events are part of the context's public interface; translate to the published language before the boundary; keep a deliberately small set of public domain events.
3. Match event type to consistency need: eventual consistency acceptable → ECST; consumer must read the producer's last write → notification + explicit query.

## ch-16 — Data Mesh {#ch-16}

Analytical (OLAP) models differ from operational (OLTP): built around **fact tables** (immutable, append-only records of business activities — kin of domain events, at analyst-chosen granularity, e.g., 30-min snapshots) and **dimension tables** (highly normalized descriptive attributes for unpredictable ad-hoc slicing); **star** vs **snowflake** schemas.

Classic architectures repeat DDD's named sins: **data warehouse** = one enterprise-wide model (the ch-3 jack-of-all-trades failure), and its ETL reaches directly into operational DBs — coupling analytics to *internal implementation schemas*, so any model change breaks someone else's pipelines (acute in DDD projects, which evolve models constantly). **Data lake** stores raw operational data, deferring modeling — schema-less, no quality gate, degrades into a **data swamp** with per-version ETL sprawl.

**Data mesh** = DDD for analytical data; four principles: (1) **decompose data around domains** — analytical model ownership aligned with bounded contexts; the product team owns both its OLTP and OLAP models; (2) **data as a product** — analytical data served via well-defined, discoverable, schema'd, SLA'd, versioned output ports; polyglot serving; quality is the owning team's accountability; (3) **enable autonomy** — a dedicated data-infrastructure platform team provides the blueprint so teams don't reinvent serving; (4) **build an ecosystem** — federated governance body for interoperability rules. DDD mappings: the analytical model is an additional **published language** (OHS); **CQRS** trivially generates/regenerates multiple analytical model versions; context-integration patterns (partnership/ACL/separate ways) apply to analytical models too.

## app-a — Marketnovus case study {#app-a}

Five bounded contexts at a marketing start-up; each illustrates a failure/recovery pair:

1. **Marketing** — "aggregates everywhere": every noun declared an aggregate, no transactional boundaries, all logic in a giant service layer (accidental anemic model), one monolith. *Business outcome: success anyway* — because a robust ubiquitous language enabled fast, correct domain learning. Lesson: language quality out-predicts architecture quality.
2. **CRM** — proper aggregates attempted; modeling was slow; management offloaded features to the DBA team as stored procedures → an **implicit bounded context sliced through the Lead aggregate**; two teams, two vocabularies, duplicated rules that desynced; years of data corruption; total rewrite required. Named "suicidal boundaries": never let a boundary dissect an aggregate; never let two teams share one model.
3. **Event crunchers** — correctly built as a supporting subdomain (layered + transaction scripts)… which silently became core as BI kept adding flags → rules → invariants; nobody re-evaluated; big ball of mud; eventually rebuilt as an event-sourced domain model. Lesson: growth of complexity in a "supporting" module is the supporting→core signal; also, skipping the ubiquitous language on "simple" subdomains cost dearly later.
4. **Bonuses** — same supporting→core drift (commission calc grew rich business rules), but here the ubiquitous language existed from day one, so the mismatch ("the experts' language can no longer be modeled with active records") was *noticed early* and refactoring was cheap. Lesson: the language is a design-change early-warning system.
5. **Marketing hub** — labeled core by management, so the team fired all cannons: event-sourced model + CQRS + aggregate-sized microservices. Two failures: services drawn around aggregates got chatty → **distributed monolith**; and the *software* was never the competitive advantage (business relationships were) — behind the ornate architecture sat active-record-simple logic. Textbook **accidental complexity from misclassification**.

Distilled tricks: **map design decisions back to subdomains** — choose the pattern the requirements actually demand, infer the implied subdomain type, and reconcile with the business ("core you can hack in a day" ⇒ wrong granularity or nonviable business; "supporting that needs a domain model" ⇒ accidental business complexity to simplify, or an unrecognized profit source). **Never ignore pain** in implementing business logic — it signals a boundary or classification needs rework. Boundary strategy that survived: start wide, extract as knowledge grows; extracting from big is much safer than merging too-small.

---

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| New module/feature being scoped | Classify its subdomain first: core (differentiator, complex, volatile) / supporting (simple CRUD/ETL) / generic (solved, buy) — then pick the pattern from the tree | Every tactical decision keys off this classification | ch-1, ch-10 |
| Deciding build vs buy | Would competitors' access to the same solution hurt you? No + solution exists → generic: buy/adopt; don't build | Reimplementing solved problems burns core-subdomain capacity | ch-1 |
| Core-subdomain work planned for outsourcing / junior staffing | Core subdomains in-house with the strongest people; outsourcing/training-wheels are for supporting subdomains | Core = strategic investment, volatile, must evolve fast | ch-1, ch-11 |
| Subdomain identification going ever finer | Stop at coherent use-case sets (same actor, same data); distill hard only for core | Finer grains that don't change design decisions are noise | ch-1 |
| Business logic ≈ money, legal audit-log duty, or deep behavior analytics | Event-sourced domain model | Events as source of truth give consistent audit + arbitrary projections | ch-7, ch-10 |
| Complex rules/invariants/state machines (not just input validation) | Domain model (aggregates + value objects + domain services) | Invariants need an enforced consistency boundary | ch-6, ch-10 |
| Simple logic over complex data structures | Active record | Encapsulates ORM mapping; anything more is accidental complexity | ch-5, ch-10 |
| Simple logic over flat data | Transaction script — but verify atomicity | Simplest pattern; most transaction-behavior bugs live here | ch-5 |
| Multiple writes (DB+DB, DB+bus, DB+response) in one operation | Wrap in one transaction; across systems use outbox / idempotency / optimistic concurrency | Partial commit = corrupted state; retry-after-lost-response double-applies | ch-5, ch-9 |
| Term with two meanings, or synonyms for one concept, in one model | Split the ubiquitous language into bounded contexts (or fix the terms) | Code can't disambiguate by conversational context; prefixes desync code from speech | ch-2, ch-3 |
| Awkward prefixes appearing on entity names (`CrmLead`, `MarketingLead`) | You've detected a hidden context boundary — make it explicit | Prefixes are the code smell of a language crossing contexts | ch-3, app-a |
| Two teams committing to one bounded context/model | Rebound: one team per context (split context or reassign) | Shared models across teams ⇒ implicit assumptions, duplicated desyncing rules | ch-3, app-a |
| Drawing initial context boundaries in an unfamiliar/volatile (core) domain | Start wide; decompose later as knowledge stabilizes | Refactoring logical boundaries is cheap; physical boundaries expensive | ch-10, ch-11, app-a |
| Choosing an integration pattern between contexts | Use the collaboration/power table: cooperation→partnership/shared kernel; upstream-dictated→conformist or ACL; consumer-favored→OHS; else separate ways | Pattern is a function of team relations, not taste | ch-4 |
| Downstream core subdomain consuming a foreign/legacy/volatile model | Put an ACL in front | Conforming to a mess makes you a mess; core models need protection | ch-4, ch-13 |
| Upstream service whose internal changes keep breaking consumers | OHS: publish an integration-oriented published language, version it | Decouples implementation model from contract; enables gradual migration | ch-4, ch-9 |
| Proposal to duplicate functionality instead of integrating | Allowed for supporting/generic when collaboration costs more; **never for core** | Duplicating the differentiator defeats the strategy | ch-4 |
| Shared kernel proposed | Only when duplication cost > coordination cost; minimize to integration contracts; CI-test all users on every change | It deliberately violates one-team-per-context | ch-4 |
| Designing an aggregate's boundary | Include only data the logic needs strongly consistent; keep it as small as possible; reference other aggregates by ID only | Aggregate = transaction boundary; big aggregates = contention + complexity | ch-6 |
| An operation needs to commit two aggregates atomically | Redesign the boundaries — that need *is* the evidence they're wrong (or accept eventual consistency via saga) | One aggregate instance per transaction is the invariant-safety guarantee | ch-6, ch-9 |
| Aggregate state mutated by external code / public setters | Move the logic inside; commands on the root are the only write path | External mutation scatters and duplicates invariant enforcement | ch-6 |
| Domain concept held as string/int/decimal (esp. money, IDs, phone, email) | Introduce a value object: immutable, value-equality, self-validating, behavior-rich | Primitive obsession duplicates validation and breeds precision/rounding bugs | ch-6 |
| Persisting aggregates | Storage must support optimistic concurrency (version compare-and-set) | Concurrent writers silently overwrite each other otherwise | ch-6, ch-7 |
| Publishing domain events | Never publish from inside the aggregate or post-commit in the app layer; use the outbox + relay; consumers dedupe (at-least-once) | Pre-commit publish leaks uncommitted state; post-commit publish can be lost | ch-9 |
| Cross-aggregate/cross-context business process | Saga (linear, event→command, compensations); process manager when routing logic/if-else and no single trigger | Multi-transaction flows need explicit compensation, not distributed transactions | ch-9 |
| A saga being used to keep two aggregates "consistent" | Stop — strong consistency requirements mean the data belongs in one aggregate | Sagas are eventually consistent by construction | ch-9 |
| Event-sourced model needs queries beyond fetch-by-ID | CQRS; implement synchronous (checkpointed catch-up) projection first, async on top | Async-only projections are hard to regenerate and corrupt on reorder/duplication | ch-8 |
| CQRS command handler asked to return nothing "by the rules" | Commands may return data from the strongly consistent model | The no-return dogma is a misconception that wrecks UX and adds round trips | ch-8 |
| One architecture mandated for a whole system/context | Choose per subdomain slice — vertical partitions with their own pattern | Contexts span subdomains of different types; uniform architecture ⇒ accidental complexity | ch-8 |
| Supporting-subdomain module keeps accreting rules/invariants | Re-evaluate: likely supporting→core; upgrade pattern (script→AR→domain model) and move in-house | Complexity growth is the type-change symptom; unmanaged it becomes a ball of mud | ch-11, app-a |
| Chosen pattern conflicts with claimed subdomain type ("core" fits active record / "supporting" needs domain model) | Reverse-map: challenge the classification with the business | Detects both wrong granularity and unrecognized profit sources | ch-10, app-a |
| Refactoring legacy toward event sourcing | Go via state-based aggregates first; get boundaries right in state-land | Wrong transactional boundaries are far costlier to fix once event-sourced | ch-13 |
| Migrating state-based history into an event store | Either generate approximate past events (test by projecting+diffing) or an explicit `migrated-from-legacy` event — never pretend full history exists | Honest gap-modeling beats fabricated completeness | ch-11 |
| Sizing microservices | Default to subdomain boundaries; bounded context = widest safe, aggregate = narrowest; optimize interface depth, not service size | Shallow services shift complexity into integration → distributed big ball of mud | ch-14 |
| Choosing an integration event type | Eventual consistency OK → ECST; must read last write / sensitive data → notification + query-back; domain events across contexts only as a curated public set | Raw internal event streams create implementation/functional/temporal coupling | ch-15 |
| Consumers subscribing to a producer's full internal event stream | Producer publishes a consumer-driven contract (projected published-language events) instead | Every internal schema change otherwise breaks every consumer | ch-15 |
| Analytics/ETL reading an operational database directly | Serve analytical data as a product through explicit output ports (data mesh); owning team owns the OLAP model | Internal schemas are not contracts; direct reads freeze the operational model | ch-16 |
| Legacy modernization kickoff | Align logical (module/namespace/schema) boundaries with subdomains first; extract physical contexts only where multiple teams or conflicting models collide; prefer strangler over big rewrite | Big rewrites rarely succeed; logical realignment is safe and reversible | ch-13 |

## Anti-patterns

- **Enterprise-wide model / jack-of-all-trades ERD** — one model for all problems. Cue: wall-sized entity diagrams; every consumer filtering out irrelevant detail; term prefixes. Effective for nothing (ch-3; reappears as the data warehouse, ch-16).
- **Aggregates everywhere** — every noun in the requirements declared an aggregate. Cue: "aggregates" with public setters, no transactional boundaries, all behavior in a fat service layer. It's active record wearing a costume; harmless only while logic stays simple (app-a §1).
- **Accidental anemic domain model** — *aiming* for a domain model and landing in active record. Cue: entity classes with getters/setters and a "smart" service layer holding the invariants. (Note the pattern itself is fine when chosen for simple logic — the anti-pattern is the mismatch, not the shape; ch-5.)
- **DDD-ifying a supporting subdomain** (the marketing-hub failure) — event sourcing/CQRS/microservices wrapped around CRUD-simple logic because the business *called* it core. Cue: architecture complexity ≫ business-rule complexity. Pure accidental complexity (app-a §5, ch-10).
- **Suicidal boundaries** — a bounded-context/team boundary dissecting an aggregate (Lead half in C#, half in stored procedures). Cue: two codebases mutating the same entity's invariants; duplicated rules drifting. Result at Marketnovus: years of silent data corruption (app-a §2).
- **Complex logic as transaction scripts** — cue: business rules duplicated across procedures, growing if-forests, per-change regressions. Scripts don't scale in rule complexity; this is the ball-of-mud on ramp (ch-5, app-a §3).
- **Naïve event publishing** — `_messageBus.Publish` inside an aggregate method or after-commit in the controller. Cue: publish call not covered by the state-commit transaction. Ghost events on rollback, lost events on crash (ch-9).
- **Saga as boundary spackle** — using sagas/process managers to coordinate what should be one aggregate. Cue: compensation logic protecting an invariant the business considers absolute (ch-9).
- **Shallow (nano) services / distributed big ball of mud** — services sized by lines-of-code or one-method-per-service; aggregate-sized services that are "chatty." Cue: every service calls most others to finish any operation; interfaces full of integration-only methods (ch-14, app-a §5).
- **Raw domain events as public contract** — consumers coupled to an event-sourced model's internal stream. Cue: adding an internal event type requires coordinated consumer releases; multiple consumers maintaining identical projections; delay timers to fake ordering (ch-15).
- **Delay-based ordering** — "process 5 minutes later so the other service finishes first." Cue: literal sleeps/scheduled lags in consumers. Temporal coupling that load or outage will break (ch-15).
- **Data swamp** — schema-less lake ingestion with no quality contract. Cue: N versions of the same ETL script tracking producer schema drift (ch-16).
- **Big rewrite** — rebuilding "correctly" from scratch. Rarely succeeds and rarely gets sustained management support; strangle or refactor incrementally instead (ch-13).
- **Translation-chain knowledge transfer** — domain knowledge relayed expert → analyst → requirements doc → design doc → code, each hop lossy (the Telephone game). Cue: engineers who can describe tables and endpoints but not the business rule's *why*; requirements missing edge cases nobody can adjudicate. Fix: direct expert–engineer conversation in the ubiquitous language (ch-2).
- **Business logic in stored procedures alongside app logic** — a second, implicit implementation surface for the same model. Cue: rules enforced in both C#/Java and SQL; DBA team and app team using different vocabularies for the same entity. At Marketnovus this dissected the Lead aggregate and corrupted data for years (app-a §2, ch-13).

## Applicability & exemptions

- **CRUD is correct, not a smell, for supporting and generic subdomains.** Transaction script and active record are the *recommended* designs there; introducing aggregates, event sourcing, or CQRS into a config table, an integration adapter, or a data-entry module is the book's central named failure (accidental complexity). Do not flag simple code in simple subdomains. (ch-5, ch-10, app-a)
- **The decision tree is heuristic, not law.** Teams deeply fluent in one heavy pattern may standardize on it; alternative trees are legitimate if chosen consciously (ch-10).
- **Consistency may be relaxed at scale** when the business impact of rare corruption is negligible (e.g., 0.001% of billions of IoT events) — evaluate risk, then cut corners deliberately (ch-5).
- **One-DB-per-context bends during strangler migration**: legacy + strangler may share a database while the legacy side is being retired (ch-13).
- **Shared kernel is a sanctioned violation** of ownership boundaries — legitimate under duplication-cost > coordination-cost, legacy decomposition, or same-team contexts (ch-4).
- **Snapshot pattern only past ~10k events/aggregate** — below that it's accidental complexity; first suspect the aggregate boundary (ch-7).
- **Event sourcing needs a business justification** (money, audit, analytics) — its learning curve, schema-evolution pain, and CQRS entourage are real costs (ch-7).
- **EventStorming is wasted on simple, obvious, sequential processes** (ch-12).
- **Subdomain classification is time-indexed** — types migrate in all six directions; a decision correct at design time can be wrong today. Re-evaluate on "pain," not on schedule (ch-11).
- **Core subdomains may be non-technical** — the software serving a non-technical core (analyst tooling, relationship-driven business) is itself supporting and should be built plainly (ch-1, app-a §5).
- **DDD is not all-or-nothing** — ubiquitous language and business-driven decisions alone are DDD; tactical patterns are optional per fit (ch-13).

## Candidate lexicon rows

| new module/service being planned without a stated subdomain type | **Classify before you architect** — core/supporting/generic determines pattern, staffing, and build-vs-buy; unclassified work defaults to over- or under-engineering | Is this logic a competitive differentiator, plumbing, or a solved problem? | should | plan | src: learning-domain-driven-design ch-1 |
| aggregates/event sourcing/CQRS proposed for logic that is CRUD, ETL, or input validation | **Don't DDD-ify supporting subdomains** — transaction script/active record is the correct design for simple logic; elaborate patterns there are accidental complexity | Would active record fully express these rules? | should | plan | src: learning-domain-driven-design ch-10 |
| same term bound to two meanings, or two names for one concept, inside one module/model | **One meaning per term per context** — code can't disambiguate by conversation; conflicting models must split into bounded contexts | Which context does each meaning belong to? | should | review | src: learning-domain-driven-design ch-3 |
| entity names sprouting context prefixes (`CrmLead`, `MarketingLead`) in one codebase | **Prefixes reveal a hidden context boundary** — nobody speaks the prefix; make the boundary explicit instead of encoding it in names | What boundary are these prefixes standing in for? | judgment | review | src: learning-domain-driven-design ch-3 |
| diff commits changes to two aggregate roots in one transaction, or wraps them in a saga to fake atomicity | **Transaction boundary = aggregate boundary** — needing multi-aggregate commits is proof the boundaries are wrong | What is the smallest data set that must be strongly consistent here? | blocker | write | src: learning-domain-driven-design ch-6 |
| aggregate/entity holding a direct object reference to another aggregate | **Reference other aggregates by ID only** — object references smuggle foreign state into the consistency boundary and bloat transactions | Does this logic need that data strongly consistent, or just addressable? | should | write | src: learning-domain-driven-design ch-6 |
| money, IDs, emails, phone numbers, or units passed around as primitives | **Value objects over primitive obsession** — immutable, self-validating types centralize the logic and prevent precision/validation drift; always for money | Where else is this value validated or manipulated? | should | write | src: learning-domain-driven-design ch-6 |
| multiple state writes (DB+DB, DB+message-bus, DB+caller-response) in one operation without transactional protection | **Every operation is a transaction** — partial commit corrupts state; use one transaction, the outbox, idempotency, or optimistic concurrency | If the process dies between these two lines, what state remains? | blocker | review | src: learning-domain-driven-design ch-5 |
| `publish(event)` inside an aggregate method or after the DB commit in an application service | **Outbox or it didn't happen** — pre-commit publish leaks uncommitted state; post-commit publish is lost on crash; commit events with state, relay them after | Is the event's persistence atomic with the state change? | blocker | review | src: learning-domain-driven-design ch-9 |
| event sourcing proposed (or resisted) for a module | **Event sourcing must earn its cost** — adopt for money/audit-log/deep-analytics needs; otherwise its learning curve, versioning pain, and CQRS entourage are dead weight | Does the business need the history, or just the state? | judgment | plan | src: learning-domain-driven-design ch-7 |
| consumers subscribing to another service's internal/domain event stream | **Publish a consumer-driven contract, not your internals** — translate to a published language of public events; raw streams create implementation, functional, and temporal coupling | Would an internal event-schema change break this consumer? | should | plan | src: learning-domain-driven-design ch-15 |
| "supporting" module's rules and invariants visibly growing across recent diffs | **Complexity growth signals supporting→core** — re-evaluate the subdomain type and upgrade the pattern before the ball of mud forms; pain is the signal, don't ignore it | Is this added complexity making the business money? | judgment | review | src: learning-domain-driven-design ch-11 |
