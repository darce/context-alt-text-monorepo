# RESTful Web API Patterns and Practices Cookbook — distilled

> **Source**: Mike Amundsen, *RESTful Web API Patterns and Practices Cookbook*, O'Reilly 2022 · extracted from `../restful-web-api-patterns.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory that gives HTTP-level API-design decision rules as a recipe catalog: which HTTP method makes a retry safe, when to return 200 vs 404 vs 4xx for an empty result, what an RFC 7807 error envelope must contain, how to run a long operation behind `202 Accepted`, the three non-breaking-change rules for a published interface, and how to bound collections. DDIA covers data semantics and release-it covers runtime stability, but neither states the wire-contract rules an agent needs when it writes or reviews an API endpoint. Hypermedia theory is compressed hard; the diff-observable rules are kept.

## Chapter map
- ch-1 — Introducing RESTful Web APIs: why message/format/vocabulary separation and "design on the scale of decades" frame every recipe
- ch-2 — Thinking and Designing in Hypermedia: the modifiability problem; **Hippocratic Oath of APIs** and the three non-breaking-change rules; read-vs-write asymmetry for distributed data
- ch-3 — Hypermedia Design (recipes 3.1–3.11): media types, vocabularies, semantic profiles, idempotent/repeatable/reversible actions, extensible messages, modifiable interfaces
- ch-4 — Hypermedia Clients (recipes 4.1–4.16): client resilience — no hardcoded URLs, bind to protocol+format not schema, validate in/out, keep your own state
- ch-5 — Hypermedia Services (recipes 5.1–5.17): stable URLs, model-leak prevention, content negotiation, health checks, **RFC 7807 problem details**, client-supplied IDs, idempotent create, dependency fallbacks
- ch-6 — Distributed Data (recipes 6.1–6.13): hide storage tech, idempotent writes, query metadata, 200-vs-400 discipline, **Must Ignore** rule, caching directives, production data-model changes, bounded responses
- ch-7 — Hypermedia Workflow (recipes 7.1–7.20): jobs/tasks with correlation IDs, shared state, progress resources, pagination actions, 202 delayed-response pattern, retries with backoff, local undo, queues/clusters
- ch-8 — Closing Remarks: adoption order — design recipes first, small measurable steps, pass-through proxies for legacy

## ch-1 — Introducing RESTful Web APIs {#ch-1}

Framing chapter; almost no diff-observable rules, but the ideas recur as rationale for everything later:

- **Message-centric, not object-centric.** Bind producers and consumers to protocol (HTTP) and message format (media type), never to object schema or URL layout — the abstraction that changes least is the best binding agent. HTTP survived Java Applets, Flash, and XHTML precisely because the envelope was decoupled from the contents; failed formats were removed without damaging the protocol.
- **Rule of Least Power** (Berners-Lee): use the least powerful technology sufficient for the task; the low barrier to entry is what made the web scale.
- **Extreme late binding** (Alan Kay): resolve interaction details (URLs, methods, parameters) at runtime from the response, not at build time — that is what lets you change a system while it is running. The internet is always running; every deploy modifies a live system.
- **Richardson's magic strings**: field and action names (`givenName`, `doCreate`) are the semantic contract between strangers. "Although computers will be your API's consumers, they'll be working on behalf of human beings, who need to understand what the magic strings mean." Use shared, published terms — this is Evans's ubiquitous language applied *across* independent codebases rather than within one.
- Fielding's architectural properties of interest (performance, scalability, simplicity, modifiability, visibility, portability, reliability) are induced by constraints (client-server, statelessness, cacheability, generality of interface), not bolted on.
- "REST is software design on the scale of decades: every detail is intended to promote software longevity and independent evolution" (Fielding). Don't assume your service is short-lived; the author's "short-term fixes" have run for 20+ years, and deprecated HTML tags still circulate decades later — things on the internet are hard to kill.

## ch-2 — Thinking and Designing in Hypermedia {#ch-2}

### The modifiability problem

The longer a service lives, the more it changes; short-lived services never face this. Emitting an API is trivial (schema-to-API generators exist); designing one that survives change is the hard part. The lazy path — new version, `/v2/`, retire the old one early — puts every consumer on a permanent upgrade treadmill: a client consuming several APIs, each versioning on its own schedule, lives in constant disruption.

**Hippocratic Oath of APIs** — "first, do no harm" to consumers. Three rules for any change to a published interface (**"Don't Change It, Add It"**):

| # | Rule | Meaning |
|---|------|---------|
| 1 | **Take nothing away** | Once an endpoint, parameter, output value, protocol, or supported media type is published, never remove it. You may return null or ignore it; you may not delete it. |
| 2 | **Don't redefine things** | Never change the meaning of an existing element. Published `user` object cannot become a `user` collection; `count` = "records in collection" cannot become "records on this page"; `?size` = page size cannot become hat size. |
| 3 | **Make additions optional** | New inputs must be optional with a server-side default. A new *required* input needs a *new* action/endpoint offered alongside the old one — and calling the new action must itself be optional. |

Corollaries:

- **Changed defaults are breaking changes.** Adding `page_size` defaulting to 100 to a previously unlimited list "breaks" clients that depended on getting the full list. Offer the paged variant as a *second* form/endpoint instead. **Hyrum's Law** (Hyrum Wright, Google): "With a sufficient number of users of an API, it does not matter what you promise in the contract: all observable behaviors of your system will be depended on by somebody."
- **Fork when you must break.** If a breaking change is unavoidable (e.g., a capability is being withdrawn), publish the new interface alongside the old and run both in production until consumers migrate on their own timeline.
- **Regression check**: run the *old, unchanged* test suite against the new interface — old-test failures approximate how existing clients will break.
- **"APIs are forever"** (Werner Vogels: "We knew that designing APIs was a very important task as we'd only have one chance to get it right"). Write the possibility of change *into* the contract from day one: "consumers SHOULD ignore any additional properties they do not understand."

### Hypermedia as the change absorber

Stability comes from structured media types (the message shape never changes); evolvability comes from hypermedia controls carrying the things that change often — URLs, methods, parameters — in the response at runtime. Paul Clements: good architecture "knows what changes often and makes that easy." Good binding agents: protocol, format, semantic profile. Bad binding agents: URLs and object schemas (codegen clients built on them are quick to deploy, easy to break, impossible to reuse).

**Find and bind**: the onboarding goal is web-like self-service — discover a service, integrate at runtime via published metadata (registry + definitions), instead of a human reading docs and hand-wiring each dependency.

### Distributed-data groundwork (expanded in ch-6)

- **All data is remote** (Irakli Nadareishvili: "treat all data as if it was remote"): you can't change the remote schema, can't control who reads/writes it, and you're on your own when it's unavailable. Assume more copies of any datum exist than you know about; re-fetch before acting on "current" state; be prepared for the owning service to reject your write — the owner alone maintains integrity.
- **Data is evidence of action**: data is the by-product of HTTP exchanges, not the center of the design. The highest-fidelity record is the HTTP messages themselves (HAR, `message/http`); query-friendly stores are derived representations of that evidence.
- **Outside vs inside**: "Your data model is not your object model is not your resource model is not your representation model." Spend design effort on the outside promises (kept for years); don't sweat the inside tech (changes freely — file store → SQL → streaming engine with no interface change).
- **Read vs write asymmetry**: read delays are what users notice — serve reads from local caches when possible; design explicit `202` responses for known-slow queries. Write delays are tolerable, but write *integrity* is not — limit each write action to one storage target ("one is best; any more than that are a problem"); multi-target writes force reject/undo coordination.
- **IRQL over DQL** at the interface: information-retrieval query languages (Lucene/Solr-style "documents matching criteria") fit web reads better than database query languages (definitive facts); most API traffic is reads anyway. Data stack ladder: file store → SQL-like store for writes → streaming engine (Kafka) at thousands of writes/sec — all invisible behind the interface.

### Workflow groundwork (expanded in ch-7)

| Approach | Metaphor | Strength | Weakness |
|---|---|---|---|
| Orchestration (BPEL, AWS Step, engines) | conductor | explicit, testable, monitorable in one place | central engine is a SPOF; encourages synchronous, tighter coupling |
| Choreography (events, pub/sub, SNS/SQS) | dance | loosely coupled, resilient, parts replaceable | workflow is emergent — hard to monitor a job or assess ecosystem health |
| **Hypermedia workflow** (the book's approach) | jazz | declarative job documents + a small fixed action interface; parallel by default | requires services to implement the compliance contract (ch-7) |

Rule of thumb: few steps/branches → orchestration (often plain code); many steps, async, per-step rollback → choreography; the book's job-control recipes aim to combine both. Workflow challenges to design for: share *state* not data models, constrain the action vocabulary, make workflow observable, treat time as an element (`maxTTL`, cancel on breach), and plan the error path including human escalation.

## ch-3 — Hypermedia Design {#ch-3}

### 3.1 Registered media types
Designing message exchange? Pick IANA-registered formats (HTML, Collection+JSON, SIREN, HAL, UBER) and document which you support; support more than one and let consumers discover/select. A format strangers already parse is the interoperability contract; the author ships HTML alongside JSON formats because any browser becomes a test client. Don't invent your own media type unless you're internal-only, hyperscale, or the vertical leader — and if you do, you own its documentation, registration, tooling, and community "for a long time."

### 3.2 Structured media types; well-formed vs valid
A **structured media type (SMT)** keeps the same *structure* when *content* changes: an HTML `<ul>` gains an `<li name="emailAddress">` and the same validator still passes; a bare JSON object gains a key and needs a new schema. Design consumers to check in two separate passes:
1. **Well-formed** — complies with the media type's structural rules (stable forever; safe to hard-fail).
2. **Valid** — content follows domain rules ("Person MUST include givenName…") (evolves; fail tolerantly).
Consumers that only hard-fail on well-formedness survive content evolution.

### 3.3 Shared domain vocabularies
External field names come from published vocabularies — Schema.org first, then Microformats/Dublin Core, then a company-wide repository; industry: FHIR (health), PSD2 (payments), ACORD (insurance). `fname/lname/ph` → `givenName/familyName/telephone`. Internal legacy names stay behind an **anti-corruption layer** — no need to touch storage. Publish the full "magic string" list with definitions (ALPS document linking each term to its source definition). Mixing sources is fine; synonyms are not — one external term per concept (`telephone`, not also `tel`). Vocabulary terms must stay free of software/hardware dependencies.

### 3.4 Semantic profiles
A **semantic profile document (SPD)** (ALPS, DCAP) describes the whole problem space: ontology (terms), taxonomy (groupings), choreography (actions, typed `safe`/`unsafe`/`idempotent`). It is machine-readable interface *description*, not an API *definition* — no URLs, methods, or status codes in it (those live in OpenAPI etc.). Rules: keep profiles general (specificity shrinks the audience); return the profile URI with every response (`rel="profile"`); host profiles at a stable central location; and **no breaking changes to a published profile** — a change means a new URI (`…/personV2`) with the old one left online.

### 3.5 Embedded hypermedia
Put action metadata in the response as links/forms so clients resolve it at runtime — the HTML `<form>` model: URL, method, enctype, inputs with `required`/`pattern` all delivered in the message, enforceable by a generic client with zero custom code. Then services can change URLs, methods, input sets, validation rules, even relocate an action to another host, in production, without breaking form-following clients; workflow steps can merge or split the same way. Cost: it's a design-time constraint both sides must accept, and translating domain rules into hypermedia controls is a learned skill. This is the book's core bet; skip the depth unless building hypermedia clients.

### 3.6 Idempotent data writes (PUT-Create pattern)
The "failed POST" problem: client POSTs "deduct 50 credits", gets no response. Did it arrive? Is a retry a double-spend? Rule: create and update with **PUT** (idempotent by design), not POST:

```
PUT /person/q1w2e3 HTTP/2.0          | PUT /person/q1w2e3 HTTP/2.0
If-None-Match: *                     | If-Match: "p0o9i8u7..."
→ 201 CREATED, ETag: "..."           | → 200 OK (or 412 Precondition Failed)
   (create iff nothing at this URL)  |    (update iff version matches)
```

Any lost response can now be retried blindly. Requires client-supplied identifiers (see 5.14). Bake it into `createResource()`/`updateResource()` cover methods so client and server apply it consistently. Attempts to make POST retryable (HTTPLR, POE) never gained adoption.

### 3.7 Inter-service state transfer
Design services as standalone, stateless operations enlistable in solutions you didn't design (services are "part of a whole, not just a whole"). Transfer state by value (forms; or explicit `importState`/`exportState` operations for large collections) or by reference (shared URL both parties can resolve — requires pre-agreed format and vocabulary). Prefer single-step transfers; don't require session/login choreography first — if identity is needed, let a `401` on the operation itself trigger it. For browser-reachable by-reference transfers, remember CORS headers.

### 3.8 Repeatable actions
Two independent layers of idempotence, both required:
- **Network idempotence**: use GET/PUT/DELETE, not POST.
- **Operation idempotence**: message bodies must be replacement-style, not increment-style.

```
# not repeatable: which products already got the 5%?
PUT /catalog/priceUpdate      body: updatePercent=.05
# repeatable: server can check-then-set per row
PUT /catalog/priceUpdate      body: productId,currentPrice,newPrice
                                    q1w2e3, 100, 105 ...
```
Never rely on the HTTP method alone for repeatability. The up-front design cost "pays for itself the first time you have an unexpected crash in the middle of applying a large update."

### 3.9 Reversible actions
Design undo in, one of:
- **Compensating second request**: re-`PUT` the prior value, guarded by `If-Match` on the new ETag (requires knowing the prior value and that nobody else has written since).
- **Special rollback operation**: e.g., `PUT /users/rollback?id=q1w2e3` → `201 Created` + `Location` restoring a DELETEd resource. There is no HTTP `UNDELETE`, so a restorable DELETE means the service retains deleted resources for a window.
Client-friendly (no need to remember old state) but the service now owns change history. Multi-resource actions (`removeCustomerData` touching customer+orders+sales) need a designed rollback across all dependents — coordinate with their owners or wrap in local undo (7.17).

### 3.10 Extensible messages
Design response bodies to absorb additions without structural change:
- **NVP collection**: include `"nvp": [...]` from v1; future scalars/arrays/objects land there.
- **Parallel properties**: to split `name` into `givenName`+`familyName`, *add* the new fields beside the old; the service accepts either on write and derives the other.
- **Root wrapper**: `{"message": {"person": {...}}}` from v1, so `personv2`, `links`, `metadata` siblings can appear later.
Predefined hypermedia formats already follow these rules. The residual risk is consumers applying strict schema validation to incoming messages — warn them; you can't prevent it.

### 3.11 Modifiable interfaces
The three ch-2 rules applied to forms/actions: a new search filter is an optional input with a default (`regions`, default `all` — server must assume the default when absent; both old and new submissions stay valid). A new *required* input (e.g., `salesRep` for rep-credited orders) becomes a new named action (`processSalesRepOrder`) published alongside the old (`processOrder`); clients use the one they understand. Same discipline applies to vocabulary/profile changes.

## ch-4 — Hypermedia Clients {#ch-4}

Services must be stable and predictable; clients must be adaptable and resilient. "The more detailed the solution, the less reusable it becomes" — a client transcribed from one service's docs is broken by any change to that service.

### 4.1 Limit hardcoded URLs
Every URL in client code is a named variable; values live in configuration, not source; the count of memorized URLs approaches **one** (the home/entry URL — see 5.1) with everything else discovered from responses. Detection cue: string-literal URLs sprinkled through client source. If you can influence the service team, ask for hypermedia responses or at least a downloadable URL config.

### 4.2 HTTP-aware clients
Even when using a vendor SDK, keep the ability to speak raw HTTP (a small local high-level HTTP library); SDK gaps must not become capability gaps. Mixing SDK calls and direct HTTP is fine. Side note: services can learn desired features by watching how clients actually drive the API.

### 4.3 Message-centric binding
Bind the client to the media type returned, not to the service's domain objects or identity; minor service changes that preserve the format don't break you, and the same client works against any service speaking that format (the browser model).

### 4.4 / 4.5 Vocabulary profiles & profile negotiation
Code both parties to the same vocabulary document (ALPS/RDF/OWL/DCAP — the format matters less than the agreement). At runtime, verify with **profile negotiation**: client sends `accept-profile` request header; service replies with `content-profile`; on mismatch the client rejects, asks for more info, or knowingly proceeds. Protocol + format + profile = the three stable binding agents for M2M.

### 4.6 Representation formats at runtime
Always send `Accept`; always check response `Content-Type` against what you can parse; on an unsupported format, stop and report (M2M: error to caller + log to supervisor) — never guess-parse. Route each body to a format handler implementing the **Message Translator** pattern so external formats and internal models stay decoupled.

### 4.7 Schema documents as metadata
When services return unstructured XML/JSON but consistently ship schemas at runtime, a schema-driven client is the fallback binding — organize client code around schema info instead of a profile.

### 4.8 Addressable elements in responses
Find things by stable identifiers, never position. Four identifier kinds: **ID** (document-unique), **NAME** (application-unique), **REL** (system-wide, multivalue), **TAG**/class (solution-specific, non-unique). Positional parsing breaks on any reorder; identifier lookup survives restructuring.

### 4.9 Hypermedia controls (H-Factors)
Each media type has a "hypermedia signature" — which of the nine **H-Factors** (five link factors, four control-data factors) it can express. Clients that execute links/forms from the response survive URL/method/workflow changes; clients that replay documentation don't. The onboarding example: a doc-transcribed 4-step sequence breaks when a `creditCheck` step is inserted; a client that pops actions off the response's `actions` list doesn't.

### 4.10 Client-supplied links and forms
When the service isn't hypermedia and you still want the decoupling: build the links/forms client-side from the documentation, in one place, and drive the client from those — change absorption is then centralized instead of scattered through call sites.

### 4.11 Validate data properties at runtime
Honor **rich input descriptions** in responses (`required`, `pattern`, `type`, `size`…) rather than compiling validation rules into the client; the rules can then change server-side (even per-context) without redeploying clients.

### 4.12 Validate outgoing bodies
Before sending POST/PUT/PATCH: validate the request body locally — schema validation (JSON Schema/XSD) where applicable, local routines otherwise; check well-formed first, then valid (types, ranges). Postel's Law applied to the write side: the sender crafts conservative, valid messages; the service does its best with all valid requests.

### 4.13 Validate incoming responses at three levels
1. **Protocol** — status code, `Content-Type`, key headers as expected?
2. **Structure** — expected elements present (title, links with expected `rel`s, forms)?
3. **Value** — right types, values in range, dates real?
Check in that order; each level's failure has a different remedy.

### 4.14 Defend against incoming data
Always filter incoming data; **allow-list, never deny-list**; maintain min/max for every value and reject outliers; syntactic validation (does it look like a postal code?) then semantic validation (`startDate < stopDate`). The book explicitly overrides Postel for the consumption side: "defend yourself at all costs — including to the point of refusing to process the request altogether." Only operate on fields you already understand.

### 4.15 Maintain your own state
The client is the only party that sees the whole multi-service interaction, so the client keeps application state: record each request/response pair (request URL/method/headers/query/body; response URL/status/content-type/headers/body — note request and response URLs can differ via redirects) and select or compute state from that history. Don't expect servers to remember your session.

### 4.16 Goal-driven clients
For clients that run until a goal is met (possibly a goal no service knows about), use the classic AI **PAGE** model: **P**ercepts (properties to monitor), **A**ctions (read/write/compute), **G**oals (target values), **E**nvironment (the services). Pairs with state-watch (7.13).

## ch-5 — Hypermedia Services {#ch-5}

### 5.1 Publish at least one stable URL
One permanent, documented entry URL per service — the only thing consumers may memorize; exact value irrelevant. Everything else is discovered. If the service moves, the stable URL answers `301 Moved Permanently`. Consider RFC 8615 well-known URIs only if you need them (nontrivial).

### 5.2 Prevent internal model leaks
Design the interface as its own artifact — its properties, collections, and parameters must "stand alone" apart from internal models — not a wrapper generated from service code or DB schema. Detection cue: API resource shapes identical to DB tables / ORM entities; API PRs that mirror migration PRs.

### 5.3 Design representations deliberately
Never direct-serialize internal objects into responses ("brittle… likely to break when internal models change — which they will"); map internal data into a structured media type via a representation library. Costs more up front, pays off at every future change and every additional format.

### 5.4 Internal functions as external actions
Expose operations in the published vocabulary (`firstName` internal → `givenName` external; the middleware translates, so internal renames like `fNameValue` never surface). Collapse multi-service internal processes into single external actions — `sendOnboardingData` rather than exposing calls to `userSvc` + `customerRelationsSvc` + `accountSalesSvc`. "Design a good interface; don't just echo the service internals."

### 5.5 Advertise client preferences
Expose the tuneable exchange parameters via `OPTIONS` and/or a `meta` resource linked from home: `Accept` (response formats), `Allow` (methods), `enctype` (request formats), charset, encoding, language, `profile` (vocabularies). Return the full meta resource even when only one value is supported — discovery is the point.

### 5.6 HTTP content negotiation
- **Proactive (server-driven)**: client sends ranked `Accept`; server picks and answers with `Content-Type`. The server may return a format *not* on the client's list — clients must check (4.6).
- **Reactive (client-driven)**: server returns `300 Multiple Choices` + a list (often `Link` headers, optionally `Location` for auto-redirect); client picks and re-requests. Costs a round trip; suits many-variable negotiations.

### 5.7 / 5.8 Publish complete vocabularies
A machine-readable profile lists every data property *and* action name that can appear in messages — schemas typically cover data names only and omit action names (forms, link relations), which is why "data dictionary" undersells it. Link with `rel="profile"` (RFC 6906) — a profile adds semantics without changing message meaning. Standard carriers: RDF family (JSON-LD), XSD/JSON Schema (data-only), ALPS (the author's choice; XML/JSON/YAML serializations).

### 5.9 / 5.10 Service definition documents & API metadata
Publish the API definition at a discoverable location, matched to interface style: CRUD → OpenAPI; event-driven → AsyncAPI/CloudEvents; RPC → protobuf; GraphQL → SDL; hypermedia → ALPS. Link it with `rel="service-desc"` (RFC 8631) in responses and on `OPTIONS`. Separately publish an **APIs.json** metadata document (name, URLs, docs, contacts, maintainers, specs) at the service root, linked with `rel="service-meta"` from home.

### 5.11 Service health monitoring
Expose a health endpoint (suggested `/health`, link `rel="health-check"`), media type `application/health+json` (IETF Health Check draft):

| Field | Meaning |
|---|---|
| `status` | `pass` / `warn` / `fail` |
| `version`, `releaseId` | public version, release |
| `checks` | per-downstream-dependency detail statuses |
| `notes`, `output` | state notes; raw error output on warn/fail |
| `links`, `serviceId`, `description` | further info, identity |

Add caching directives (`max-age`, `ETag`) to the health response so frequent pollers can't turn it into a DoS vector — and clients must honor them.

### 5.12 Standardized error reporting (RFC 7807 problem details)
Return errors as `application/problem+json` (or `+xml`):

```json
HTTP/1.1 403 Forbidden
Content-Type: application/problem+json
{ "type": "https://example.com/probs/out-of-credit",
  "title": "You do not have enough credit.",
  "detail": "Your current balance is 30, but that costs 50.",
  "instance": "/account/12345/msgs/abc",
  "status": 403,
  "balance": 30, "accounts": ["/account/12345", "/account/67890"] }
```

- `type` — URI identifying the problem class (default `about:blank`); should dereference to human-readable docs that also define any extension members (`balance`, `accounts`) — effectively a semantic profile for the error.
- `title` + `status` — fixed per problem type (`status` is a number and matches the HTTP status); `detail` + `instance` vary per occurrence.
- Define a new type by documenting three things: type URI, title, appropriate status code. **Keep the set of types small and reusable**; customize via `detail`/`instance`, not new types.
- Do **not** put stack traces/debug info in problem details — the format describes the interface, not the service behind it.
- Skip the envelope when the bare status suffices (plain `403` on a forbidden PUT); use it when the caller can *fix* something (e.g., invalid body → describe the problem and the fix).
- Pair with `Retry-After` when the client should retry later.
- Treat errors as an *alternate response* — a designed feature of the interface, not a failure condition. If your media type has native error support (Collection+JSON's `error` object), use that instead of double-enveloping.

### 5.13 Runtime service registry
Services self-manage registry membership: **register on startup** (location, capability, formats, vocabularies, definitions, health URL), **periodic health ping-back** (optionally usage/error/latency stats), **unregister on shutdown**. "DNS for services." All three behaviors are internal — not part of the public API surface.

### 5.14 Client-supplied identifiers
Let clients generate resource IDs (UUID per RFC 4122, or random/date-derived strings) and send them in the URL or body; the service validates uniqueness and returns `409 Conflict` (with fix guidance) on collision. Removes the create-then-read-back-the-ID round trip and converts sequential multistep workflows into parallel ones (each step can pre-name its resources).

### 5.15 Idempotent create
The lost-response problem, money version: POST transfers $500, no response arrives — repeat and risk a double transfer, or don't and risk losing the transfer. POST is defined non-idempotent: it cannot "be repeated automatically if a communication failure occurs before the client is able to read the server's response." Solution = PUT-Create (3.6): client-supplied URL + `If-None-Match: *` (create) / `If-Match: <etag>` (update); retries become safe by construction. The `Idempotency-Key` header (IETF draft) is the acknowledged POST-preserving alternative; the book prefers PUT because it works with no extensions. (↔ industry practice: Stripe-style idempotency keys on POST are now common; the *shared* rule is "no unsafe retried operation without an idempotency mechanism.")

### 5.16 Runtime fallbacks for dependent services
An aggregating API (shopping = cart + payment + delivery APIs) inherits every dependency's failures — cover both read-from and write-to scenarios with a "backup plan" per dependency, in preference order:

| Option | When |
|---|---|
| Automatic retry | transient faults; note most HTTP libs auto-retry GET only — add your own for unsafe methods carefully |
| Static fallback | configured alternate URL for the same capability |
| Dynamic fallback | look up a replacement in the service registry (5.13) at runtime |
| Queue + replay | accept the request, return `202 Accepted` + monitoring info (7.15), replay when the dependency recovers — document this response in the API design |
| Give up | `5xx` "unable to process at this time" + estimated wait; beware cascading consumers' own mitigation |

Assume failure: "Any large system is going to be operating most of the time in failure mode" (John Gall). Pure data dependencies (postal codes, country lists) can often be replaced by caching (ch-6). ↔ *release-it*: Amundsen deliberately excludes code-level Circuit Breaker/bulkhead patterns as out of scope — use release-it for in-process stability; this recipe covers the *interface-level contract* of degradation.

### 5.17 Semantic proxies
Wrap non-compliant/legacy services in a translating proxy rather than modifying them. Three grades: **enterprise-level proxy** (algorithmic translation of a whole platform, e.g., CICS EXCI), **custom one-off proxy** (single service, incremental), **semantic profile proxy** (format/vocabulary normalization only, e.g., CSV → SIREN). All three are full interface-design jobs: publish a profile (5.7), publish a definition (5.9), implement external actions over the underlying service (5.4).

## ch-6 — Distributed Data {#ch-6}

### 6.1 Hide storage internals
Consumers must not be able to tell whether you run SQL, GraphQL, or flat files. The interface expresses **jobs to be done** (`findUnpaidInvoices`), never data-language (`queryData('invoices where balance>0')`). Exception: you are literally building a data-engine product — then the query language *is* the product.

### 6.2 Make all changes idempotent
Data writes over HTTP use **PUT only** — not POST, and not PATCH (the method registry lists PATCH as non-idempotent; it *can* be issued idempotently, but the book finds "implementing PATCH more of a challenge than simply using PUT"). Every PUT is a **conditional request**: `If-None-Match: *` on create (only if nothing exists at the URL), `If-Match: <etag>` on update (only if unchanged since read). This buys two guarantees at once: safe blind retries after lost responses, and lost-update protection (you can't silently overwrite another writer — you get `412`). Especially critical for M2M flows where no human can untangle a failed write.

### 6.3 Hide data relationships
Write operations accept a "flat view" of related entities (person + address fields in one message); the API or service splits it into however many internal writes. Include in the write response a link/form for adding further related entities ("Add another address"). Don't make consumers understand your entity graph.

### 6.4 "Contains" queries via URL name/value pairs
Simplest viable IRQL and often all you need: `?name=value` where `=` means **contains** (substring/in) rather than strict equality, and `&` means AND (`?ID=3e&NAME=Mi`). Prefer case-insensitive matching (the URI spec says query strings are case-sensitive; most implementations aren't — make yours discoverable). 

### 6.5 Query response metadata
Return metadata with query results — inline for a few values, or via a linked metadata resource for many:

| Field | Purpose |
|---|---|
| `q-status` | query outcome description (≠ HTTP error status — see 6.6) |
| `q-sent` | echo of the submitted query (lets machines verify parsing) |
| `q-executed` | translated backend query — **security risk, usually omit** |
| `q-returned` / `q-count` | rows in this response vs estimated total matches — the truncation signal |
| `q-seconds`, `q-datetime` | execution cost + timestamp (vital if response gets cached) |
| `q-score`, `q-suggest` | relevance; hints to narrow/broaden |
| `q-source` | data sources used — coupling/security risk, usually omit |
| `q-location` | replay URL for the stored query (7.14) |

Select what fits the use case (a by-id lookup may need only the timestamp).

### 6.6 200 vs 404 vs 4xx/5xx for data requests
The status-code discipline for data endpoints:

| Case | Status |
|---|---|
| Well-formed filter query, zero matches | `200 OK` + empty collection — empty is a successful answer |
| Single, directly addressed resource absent (`/persons/q1w2e3`) | `404 Not Found` |
| Malformed request (bad URL, invalid query) | `400`-class + details on how to fix |
| Request fine, service can't fulfill (store unreachable…) | `5xx` + details |

The split is *who can fix it*: 4xx = caller must change the request; 5xx = caller may retry later. Also: `/persons/?id=q1w2e3` for a single resource is a weak design — prefer `/persons/q1w2e3` (though you don't always control the URLs you consume).

### 6.7 Media types for data queries
Support query languages as negotiable *request media types* in POST/PUT bodies — `application/sql` is registered (RFC 6922); the author uses vanity types (`application/prs.graphql+json`, etc.) for Solr/OData/GraphQL. The interface translates to whatever engine runs behind it; content negotiation (5.6) then covers query languages too, and query bodies become storable/replayable resources (7.14).

### 6.8 Ignore unknown data fields (Must Ignore)
When a message contains more fields than you understand: **ignore what you don't know, operate on what you do, and exchange the complete record on update** — never strip unknown fields when writing back or forwarding, or round-tripped writes destroy other services' data and lose integrity at the source. (Fowler's "tolerant reader" is the read half of this rule; the write half — return the whole record — is what intermediaries most often get wrong.)

### 6.9 Caching directives
The fastest, most resilient remote read is a local cache hit — "the best way to implement responses for data reads is to serve up the solution without involving the network at all."
- **Providers**: mark every response — scope (`public`/`private`), `max-age`, handling (`no-store`, `no-cache`, `must-revalidate`); `ETag` + `must-revalidate` for changeable resources so consumers make conditional GET/PUT via `If-Match`/`If-None-Match`; `immutable` (RFC 8246) for truly static subresources. If a data service you consume sends no cache metadata, lobby its team to add it.
- **Consumers**: request-side directives — `no-cache` to force fresh before an edit; `max-age`/`min-fresh` to demand remaining freshness; `max-stale, stale-if-error` to accept a stale copy rather than surface a 4xx/5xx on read-only paths.

### 6.10 Modifying data models in production
Build change-absorption into storage from day one: **explicit fields + an implicit name-value collection** (`{"nvp":[{"name":"familyName","value":"Quarkus"}]}`). New properties land in the NVP bag: no schema migration to ship, no consumer schema updates, and — the killer feature — a rolled-back release doesn't lose the data the new fields collected; the fixed re-release picks it up. Forward *and* backward compatibility.

### 6.11 Extending remote data stores
Never push new fields into a store you don't own. Keep a local store holding only the extension values plus an **associative key** linking local rows to remote records; you own integrity between the two.

### 6.13 (with 6.12 below) Pass-through proxies for data exchange
Always exchange **complete records**, even when editing a subset: read whole → edit the part → write whole back for the owner to validate and store. An address service between a consumer and a person service holds the full person record, splices in the updated address, returns the whole — and must be ready to report a failed upstream write. Consumers can never know whether they're talking to storage or a pass-through ("turtles all the way down"), so the rule must hold at every layer. Subset editors may support update-only (create/delete of sub-entities belongs to the owner).

### 6.12 Limiting large-scale responses
Bound every collection:
- Set and document a **default maximum record count** for all data queries — at the interface even if the backend has its own.
- Always inject the max into backend queries (`LIMIT`/`TOP` in SQL, `$top`/`maxpagesize` in OData, `first:nn` in GraphQL, `rows` in Lucene); a query sent without a max is a performance and security problem.
- Always clamp client-supplied limits that are out of range; insert the default when absent.
- If the engine can't limit, truncate at the interface.
- Report the applied limit in query metadata (6.5); pair with list navigation (7.11) for interactive paging.

## ch-7 — Hypermedia Workflow {#ch-7}

Multi-service workflow as *jobs* (sets of tasks that must be parallel-safe) of *tasks* (single actions), coordinated by documents rather than a central engine. Tasks that require strict ordering go in separate jobs, run sequentially.

### 7.1 Workflow-compliant services
The composability contract every enlistable service implements:

| Level | Actions |
|---|---|
| Task | **Execute** (do the work) · **Repeat** (idempotent redo) · **Revert** (undo) |
| Job | **Continue** (resume where left off) · **Restart** (from the beginning) · **Cancel** (stop + undo all) |
| State | **ReadState** / **WriteState** against a shared state resource |

Implement all of them even as no-ops — uniformity is what makes composition cheap. Every request/response carries the job ID as `correlation-id` header and the task ID as `request-id` (non-standard headers — use your org's equivalents, but be consistent and document them). Actions may be specific (`computeSalesTax`) or generic (`writeRecord`) but must be fully described (URL, method, media types, inputs).

### 7.2 Shared state resource
Share *state, not data models*: a standalone HTTP resource keyed by job ID (`rel="sharedState"`, e.g. `/shared-state/u7y6t5r4e3`), its URL passed with every request/response of the job. Services read it to fill action forms and write results back; property names are governed by the agreed profiles (3.3/3.4), not by shared schemas or shared database tables (both explicitly rejected). Archive it when the job completes. Distinct from the progress resource (7.7) — robust systems need both.

### 7.3–7.5 Workflow as code / DSL / documents
- **Code** (7.3): fine for simple, stable, non-customizable flows — publish one stable interface, enlist remote services in source behind it; swap enlisted services freely without breaking the promise.
- **DSL** (7.4): when flows multiply or need per-customer variation; lowers the create/test/deploy barrier.
- **Documents** (7.5): fully declarative job descriptions (what, not how) built on a workflow vocabulary; expressed as HTTP resources or queue messages (queues suit high/spiky volume — 7.19).

### 7.6 RESTful job control language (JCL)
Job documents carry everything an engine needs:
- Task controls: `taskStartURL`, `taskRerunURL`, `taskRollbackURL`, `taskCancelURL`, `taskStatus`.
- Job controls: `jobRestartURL`, `jobContinueURL`, `jobCancelURL`, plus completion callbacks `jobSuccessURL` / `jobFailedURL`.
- **`jobMaxTTL` / `taskMaxTTL`**: engines monitor and cancel work that exceeds its time budget.
Submitting a job returns `202 Accepted` (7.15) while tasks run in parallel; completion activates the success/failed link and archives the job document. Job records themselves get list/filter/read/create/update/remove management actions (7.11 applied); task-level management is rarely needed.

### 7.7 Progress resource
Every workflow job gets an observable progress resource tied to the `correlation-id`: job metadata (`jobID`, `jobURL`, `jobStatus` pending/working/completed/failed, created/updated timestamps, `jobMaxTTL`) and per-task metadata (`taskID`, `taskStatus`, start/stop times, `taskMaxTTL`, `taskMessage` — often multiple lines, one per attempt). Include a refresh link and caching hints. Recording full HTTP request/response details there is a **security leak** — restrict to authorized readers.

### 7.8 / 7.9 Related actions & MRU links
Payload bloat from listing every possible action every time: move the complete, context-computed action list behind a `rel="related"` resource (contents can reflect data state, service mode, client mid-workflow position, caller identity). But don't over-correct into responses containing a single `related` link forcing extra round trips: track **most recently used** resources (per app or per user) and inline the top links — MRUs also teach new developers the common paths.

### 7.10 Work-in-progress (WIP)
Long, multi-party data collection (employee onboarding: HR inputs, third-party background check, contract — hours or days apart): a persistent WIP document with actions `listWIP`/`filterWIP` (manage the collection), `createWIP`/`readWIP`/`updateWIP`/`cancelWIP` (one document), `shareWIP` (hand to another user/machine), `submitWIP` (final processing). Multiple WIP documents can be in flight for one goal.

### 7.11 Standard list navigation (pagination)
Pagination is an **action set exposed in the response**, not URL math the client performs: `first`, `previous`, `next`, `last`, `select` (into an item — signals which members are individually readable), `exit`/`home` (leave, optionally with cleanup). Entry via `rel="list"`/`rel="collection"`. Clients follow links; servers stay free to change page-token mechanics underneath. Combine with 6.4 for filtered lists and 7.12 for editing.

### 7.12 Partial Form Submit (PFS)
For long/complex forms — especially machine-driven clients: accept `partialSubmit` (validate + store what was sent; return the updated form with filled values and remaining inputs), plus `resetSubmit`, `refreshSubmit`, `cancelSubmit`, `finalSubmit` (triggers post-input processing). A machine can submit one field at a time and get per-field validation feedback — machine-fixable errors instead of a monolithic rejection. Unlike WIP (7.10), PFS is not for multi-day, multi-page processes.

### 7.13 State-watch (client-driven workflow)
When the client, not the service, knows the goal state (thermostat app watching temperature sensors): the service publishes which properties are **watchable**; the client registers its watch list and every subsequent response includes the watched values. Four transport options — query string (long URLs), `Prefer` header (RFC 7240; no registered property yet), request body (GraphQL-style; forces unsafe methods, complicates caching), or a dedicated **state-watch resource** linked `rel="watch"` (the book's recommendation: set once per session, proper HTTP, no URL bloat). GraphQL is the mainstream instance of client-selected response shape — reuse it if you already run it.

### 7.14 Stored replays for expensive queries
Complex/expensive queries become resources: submit the query body once to create a query resource, then request its URL to execute. Avoids URL-length limits (long query strings get misread as attacks), enables caching (`cacheTTL`, `cachingDirectives`), sharing (`shareQuery`, `owner`), tagging, and audit (`dateLastRun`). Note the execute-URL and the edit-URL of a query resource are different things. Manage the collection with 7.11.

### 7.15 Synchronous reply for incomplete work (202 pattern)
The long-running-operation recipe. When a request will take more than a few seconds, return **`202 Accepted` immediately** — even before work starts — with a status document (some fields can travel as `Link` headers):

| Metadata | Actions |
|---|---|
| `identifier`, `acceptedURL` (poll here) | `goAccepted` — check status (safe) |
| `completedURL`, `failedURL` | `goCompleted` / `goFailed` — fetch outcome (safe) |
| `status`: pending/working/completed/failed | `doCancel` — DELETE, idempotent |
| `percentCompleted`, `refresh` interval | `goHome` |
| `dateCreated/Updated/Estimated` | |

Design this in wherever delay is foreseeable — big collations, queued writes during dependency outages (5.16), workflow job submission (7.6). Holding the connection instead fails at whichever timeout layer fires first.

### 7.16 Automatic retries
Internal server-side detail — don't expose retry machinery on the web. Preconditions before any auto-retry:
1. The request is idempotent — network level (GET/PUT/DELETE) *and* operation level (3.8).
2. The failure class warrants it: `4xx` → never retry unmodified (it cannot succeed); `5xx` or local connection loss → retry.

Strategy preference order: **exponential backoff** (2s, 4s, 16s) > incremental (4s, 8s, 16s) > regular interval (fleet-synchronized retries amplify outages) > immediate (max ~2, only for LB/gateway blips) > randomized (≤15s jitter; may wait longer than needed). Cap at ~3 attempts. Aggressive retries look like a DoS to the target. Keep parameters in a config resource per service or task: `Method`, `Max-Retries`, `Max-Wait-Seconds`, `Starting-Value-Seconds`, `Increment-Value-Seconds`. On final failure report the last status; log attempts locally — not to the public progress resource.

### 7.17 Local undo / rollback
Expose the underlying service's undo if it exists. Otherwise build a "faux undo" at the interface:
- **Direct undo** (simple CRUD): keep a durable history of undoable actions keyed by `contextId`; expose `undoUpdateCustomer(contextId)`; enforce a validity window (e.g., seconds — undoing last week's change has unbounded blast radius).
- **Undo with delays**: hold the write for N seconds before forwarding; an undo inside the window means the backend never sees the original — zero rollback risk, at the cost of built-in write latency. Only for latency-tolerant paths (batch, queue-fed flows).

### 7.18 Calling for help
When retries can't fix a workflow error, escalate to a predetermined human (email + SMS) with the minimum bundle: the workflow description (7.3–7.5), the progress resource (7.7), the shared state (7.2), and error reports/traces — as attachments or as URLs the responder can access. The human continues, restarts, or cancels. Record every escalation as an incident in a regularly reviewed collection — it seeds bug fixes and redesigns that reduce future calls for help.

### 7.19 Queues and clusters
Internal scaling levers, invisible to the public interface: a message queue between interface and processor lets you `202`-ack instantly under load (natural fit for document-described jobs); messages timing out in queue (hitting `jobMaxTTL`/`taskMaxTTL`) → add queue readers; processing timing out → cluster the workflow engines (also rides through single-machine failures).

### 7.20 Workflow proxies for non-compliant services
Enlist a non-compliant service by wrapping it in a workflow-compliant proxy implementing Execute/Repeat/Revert + shared state + correlation IDs. Execute is easy; Repeat/Revert are only trustworthy when the target is read-only or compute-only (postal-code validation, tax calculation — nothing to revert, safe to repeat). If the target changes server-side state you don't own, you cannot know what dependent state a Revert would orphan. "Here be dragons": only proxy state-changing services you own and can verifiably repeat and revert; otherwise avoid workflow proxies entirely.

## ch-8 — Closing Remarks {#ch-8}

Adoption guidance: apply the design recipes (ch-3) to *new* interfaces first — retrofitting rules onto established non-compliant services is where transformations stall. Start with cheap unilateral wins (fixed set of representation formats); repeatability/reversibility/extensibility need producer+consumer cooperation at runtime, so sequence them later. Transform existing systems via "the smallest thing that teaches you the most… over and over again" (Adrian Cockcroft), one measurable improvement at a time — measurable wins create the flywheel for the next initiative. The pass-through proxy recipes (5.17, 6.13, 7.20) are the sanctioned way to modernize legacy without recoding it — with their stated cautions. The recipe names themselves are a shared team vocabulary; most orgs already half-implement several patterns (e.g., paging) without a common name, and naming them brings coherence.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Diff removes an endpoint, parameter, response field, or supported format from a published API | Take nothing away — deprecate by ignoring, never by deleting | published elements are promises; removal breaks unknown consumers | src: ch-2 |
| Diff changes the meaning/type of an existing field (`count` semantics, object→array) | Don't redefine — add a new field/action instead | redefinition is deletion in disguise (Hyrum's Law) | src: ch-2 |
| Diff adds a required input to an existing operation | Make additions optional with a server default, or publish a new action alongside the old | new required inputs break every existing caller | src: ch-2 |
| Diff changes a default behavior (page size, sort order, limit) of a published endpoint | A changed default is a breaking change; new behavior goes behind a new optional parameter or new action | clients depend on observable behavior, not documentation | src: ch-2 |
| Client code retries a POST after timeout / no response | No unsafe retry without an idempotency mechanism — use PUT+`If-None-Match:*`/`If-Match` (or an idempotency key) | lost response + non-idempotent retry = double-create/double-spend | src: ch-3 (3.6), ch-5 (5.15) |
| Write body expresses a delta ("increment by", "add 5%") | Make operations replacement-style (`currentValue,newValue`) so replay is safe | method idempotence doesn't cover operation idempotence; partial failure + retry corrupts data | src: ch-3 (3.8) |
| Update endpoint writes without a version/ETag precondition | Make PUTs conditional (`If-Match: <etag>`, reject with `412`) | prevents lost updates between concurrent writers and makes retries safe | src: ch-6 (6.2) |
| DELETE implemented as hard-delete with no recovery path | If undo is promised, retain deleted resources for a window and expose a restore operation | there is no HTTP UNDELETE; reversibility must be designed in | src: ch-3 (3.9) |
| Error response is ad-hoc JSON (`{"error": "..."}`) or bare 500 with prose | Return RFC 7807 `application/problem+json`: `type`, `title`, `status`, `detail`, `instance` | standardized envelope lets clients recognize and resolve errors programmatically | src: ch-5 (5.12) |
| Error body contains stack trace / internal exception / SQL | Problem details describe the interface, never the implementation — no debug info to callers | leaks internals, couples clients to implementation, security exposure | src: ch-5 (5.12) |
| New problem `type` minted per call site | Keep problem types few and reusable; vary `detail`/`instance` per occurrence | type+title+status are the fixed contract; proliferation defeats recognition | src: ch-5 (5.12) |
| Collection/query endpoint with no record limit | Always set a documented default max; clamp client-supplied limits; inject `LIMIT`/`$top`/`rows` into backend queries | unbounded responses are a performance and security failure that appears only at scale | src: ch-6 (6.12) |
| Endpoint returns a list without paging controls or truncation metadata | Expose navigation links (`first/previous/next/last`) and return `q-returned` vs `q-count` so truncation is visible | clients can't distinguish "all results" from "first page" otherwise | src: ch-7 (7.11), ch-6 (6.5) |
| Filter query with zero matches returns 404 | Well-formed filter with empty result → `200` + empty collection; `404` only for a missing *single addressed* resource | empty is a successful answer, not an error; 404 misfires client error handling | src: ch-6 (6.6) |
| Handler returns 4xx for a server-side failure (or 5xx for bad input) | 4xx = caller must change the request; 5xx = caller may retry later — classify by who can fix it | retry logic branches on this exact distinction | src: ch-6 (6.6), ch-7 (7.16) |
| Operation known to take more than a few seconds handled synchronously | Return `202 Accepted` + status resource (`status`, `percentCompleted`, poll/cancel links); complete via `completedURL`/`failedURL` | holding the connection fails at every timeout layer; delay must be explicit in the contract | src: ch-7 (7.15) |
| Retry loop with fixed interval / unbounded attempts | Exponential backoff, ~3 attempts max, never auto-retry 4xx, config-driven parameters | synchronized fixed-rate retries amplify outages; 4xx retries can never succeed | src: ch-7 (7.16) |
| Service consumes a message and drops fields it doesn't recognize before writing back | Must Ignore: skip unknown fields when reading, but round-trip the complete record on update | stripping unknown fields destroys other services' data through you | src: ch-6 (6.8, 6.13) |
| Consumer hard-fails validation when a response gains a new optional field | Validate well-formedness strictly, content tolerantly; ignore unknown properties | additive evolution is the compatibility contract; strict schemas break it | src: ch-3 (3.2, 3.10) |
| API resource shapes mirror DB tables / ORM entities / internal function signatures | Design the interface as its own artifact; translate internal names (anti-corruption layer) | leaked internals make every refactor a breaking change | src: ch-5 (5.2–5.4), ch-6 (6.1) |
| External API exposes storage/query technology (raw SQL params, engine-specific syntax) | Interface expresses jobs-to-be-done; storage tech stays swappable behind it | consumers must survive a storage migration without noticing | src: ch-6 (6.1) |
| Multi-call internal process exposed as N dependent public endpoints | Collapse into one external action; orchestrate internally | fewer interface promises; internal steps can be re-sequenced freely | src: ch-5 (5.4) |
| Client code contains string-literal service URLs beyond the entry point | URLs are config-sourced named variables; memorize one home URL | URL changes then need no client rebuild | src: ch-4 (4.1) |
| Client parses response without checking `Content-Type`/status first | Validate protocol → structure → values, in that order; refuse unsupported formats | each layer's failure has a different remedy; guess-parsing hides real errors | src: ch-4 (4.6, 4.13) |
| Client accepts input data with no bounds/allow-list | Filter all incoming data; allow-list over deny-list; min/max on every value | consumption side of Postel's Law is a vulnerability, not a courtesy | src: ch-4 (4.14) |
| POST-create forces read-back to learn the new ID | Accept client-supplied IDs (UUID); `409 Conflict` on collision | removes a round trip and enables parallel creation workflows | src: ch-5 (5.14) |
| New service ships with no health endpoint | Expose `/health` returning `application/health+json` (`status`, `version`, `checks`) with caching directives | monitoring needs a stable contract; uncached health endpoints invite DoS | src: ch-5 (5.11) |
| Aggregating service calls a dependency with no failure plan | Per dependency choose: retry → static fallback → registry lookup → queue+`202` → `5xx`+wait estimate | dependencies fail routinely; the degradation path is part of the interface design | src: ch-5 (5.16) |
| Responses to remote-data reads carry no caching metadata | Mark every response (`Cache-Control`, `ETag`); consumers honor it; use `stale-if-error` for read-only resilience | local cache hits are the cheapest availability and latency win | src: ch-6 (6.9) |
| Multi-service workflow with no shared IDs in requests | Pass job ID as `correlation-id` and task ID as `request-id` on every request and response | without correlation, distributed failures can't be traced to a job | src: ch-7 (7.1) |
| Long-running job with no way to observe or cancel it | Every job gets a progress resource (per-task status, timestamps) and cancel/continue/restart controls, plus `maxTTL` auto-cancel | unobservable workflow can't be operated; TTL-less jobs leak forever | src: ch-7 (7.6, 7.7) |
| Workflow task cannot be re-run or undone | Composable tasks support Execute/Repeat/Revert (even as documented no-ops) | jobs fail partway; repeat and revert are what make composition safe | src: ch-7 (7.1) |
| Proxy adds write operations over a service it doesn't own | Only proxy read-only/compute services unless you can verifiably Repeat and Revert the target | you can't compensate state changes you don't understand | src: ch-7 (7.20) |
| Schema migration required to ship or roll back a release | Two-tier model: explicit fields + name-value extension bag; new fields land in the bag first | rollback without schema change and without losing newly collected data | src: ch-6 (6.10) |
| Breaking change unavoidable on a production API | Fork: run old and new interfaces in parallel; consumers migrate on their own timeline; run the old test suite against the new interface | early retirement exports your change cost to every consumer | src: ch-2 |

## Anti-patterns

- **Schema/URL binding** — client generated from service object schema + literal URLs. Cue: codegen client breaks on any service-side rename; identical service at a different URL unusable. Fix: bind to protocol + media type (+ profile). (ch-2, ch-4)
- **Failed-POST double-write** — POST for money-moving/create operations retried by client, gateway, or queue with no idempotency mechanism. Cue: `POST` + retry logic in the same client path. (ch-3, ch-5)
- **Increment-style write bodies** — `updatePercent=0.05`, "add 1 to each total". Cue: replaying the request changes the outcome. (ch-3)
- **Internal model leak** — API responses that are serialized ORM entities; storage-tech vocabulary in the interface. Cue: DB column names in JSON keys; migration PRs that also touch API docs. (ch-5, ch-6)
- **Strict-schema consumer** — client validates incoming responses against a closed schema and hard-fails on new optional fields. Cue: `additionalProperties: false` on *incoming* message validation. (ch-3)
- **Field-stripping intermediary** — service persists/forwards only the fields it knows, dropping the rest on round-trip. Cue: read-modify-write that reconstructs the record from a local DTO. (ch-6)
- **Unbounded collection** — list/query endpoint with no default limit; client-supplied `limit=10000000` honored; backend query issued without `LIMIT`. (ch-6)
- **404-for-empty** — filter queries returning 404 when the result set is empty. (ch-6)
- **Synchronous long-runner** — multi-second report/import held open on one request; timeouts "fixed" by raising client timeout config. Fix: 202 + status resource. (ch-7)
- **Retry storm** — fixed-interval, unbounded retries; retrying 4xx; fleet-synchronized retry schedules. Cue: retry helper without backoff/max-attempts parameters. (ch-7)
- **Debug-info error body** — stack traces, SQL, internal service names in error responses; per-call-site problem types. (ch-5)
- **Captive client** — client whose workflow is a hardcoded sequence of service calls transcribed from documentation; any service-side step change breaks it. (ch-2, ch-4)
- **Session-first API** — state transfer requires login/session choreography before the operation instead of `401`-triggered auth on the operation itself. (ch-3)
- **Uncontrolled custom media type / vocabulary synonyms** — inventing formats without owning their lifetime; `tel` and `telephone` used interchangeably across services. (ch-3)
- **Early version retirement** — shipping `/v2/` and shutting `/v1/` down on the provider's schedule, putting all consumers on a permanent upgrade treadmill. (ch-2)

## Applicability & exemptions

- **Hypermedia maximalism is optional; the HTTP-contract rules are not.** The book's core bet (clients driven entirely by runtime links/forms, ALPS profiles, profile negotiation) has low industry adoption; recipes 3.5, 4.9–4.10, 5.7–5.8, 7.13 are judgment calls for typical JSON/OpenAPI shops. The idempotency, status-code, pagination, error-envelope, and compatibility rules stand on their own without any hypermedia buy-in.
- **PUT-only writes is the book's stance, not the industry's.** POST + `Idempotency-Key` (Stripe-style, IETF draft) achieves the same retry safety; the enforceable rule is "unsafe retried operation ⇒ some idempotency mechanism," not "never POST." PATCH *can* be made idempotent; the book avoids it for simplicity, not correctness.
- **Internal, single-team APIs** can relax the no-breaking-changes rules when all consumers are in the same repo/deploy unit and migrate atomically — the Oath protects consumers you can't see or coordinate with. (A greenfield service with no users yet is the limiting case: contracts protect users, and there are none.)
- **Short-lived tools** (one-off migration scripts, spikes) don't need forever-APIs — but the author warns short-lived things routinely live for decades; treat this as judgment, not exemption-by-default.
- **Genuine data-engine products** are exempt from "hide your query language" (6.1) — the query language *is* the product.
- **Code-level resilience is out of scope by design**: Circuit Breaker, bulkheads, load shedding are explicitly deferred (to books like release-it); don't cite this book against in-process stability patterns.
- **200-for-empty has one exception**: a single, directly addressed resource that doesn't exist is a legitimate 404.
- **Must Ignore does not apply to security-relevant consumption**: recipe 4.14 explicitly overrides tolerance — bound, allow-list, and refuse suspicious input even at the cost of rejecting the message. Postel's Law governs what you *send* (4.12), not what you *accept*.
- **Problem details are not mandatory on every error**: when a bare status code fully communicates the situation (plain `403`), the envelope adds nothing; use it when the caller can act on the detail.
- **`correlation-id`/`request-id` headers are conventions, not standards** — match your org's existing tracing headers (e.g., W3C `traceparent`) rather than introducing parallel ones; consistency and documentation are the actual rule.
- **MRU/related-link, state-watch, WIP, and stored-replay recipes** presuppose interactive or workflow-heavy APIs; they're noise for simple CRUD services.
- **Delayed-undo (7.17)** intentionally adds write latency; only applicable where the write path already tolerates delay (batch, queues).

## Candidate lexicon rows

| endpoint returns a collection or query result with no record limit or paging | **Bound every collection** — unbounded responses are a scale-triggered performance and security failure; set a documented default max, clamp client limits, expose next/prev links and returned-vs-total counts | Can this response grow without bound as data grows, and could a client tell it was truncated? | should | plan | src: restful-web-api-patterns ch-6 |
| non-idempotent POST (create, payment, send) retried by client, gateway, or queue | **No unsafe retry without idempotency** — a lost response plus blind retry double-executes; use PUT with `If-None-Match:*`/`If-Match` or an idempotency key | If the response is lost, can this request be safely re-sent? | blocker | plan | src: restful-web-api-patterns ch-3 |
| write body expresses a relative change ("increment", "apply 5%") | **Replacement over increment** — replay-safe writes state current and new values so the server can check-then-set; deltas corrupt on retry or partial failure | If this write ran twice, would the result differ? | blocker | write | src: restful-web-api-patterns ch-3 |
| update handler writes without a version/ETag precondition | **Conditional writes** — `If-Match` + `412` prevents lost updates between concurrent writers and makes retries safe | What happens if two clients update this resource concurrently? | should | review | src: restful-web-api-patterns ch-6 |
| API error returned as ad-hoc JSON, bare status, or stack trace | **RFC 7807 problem details** — a standard envelope (`type`,`title`,`status`,`detail`,`instance`) lets clients handle errors programmatically; debug internals never belong in it | Would a machine client recognize and act on this error without parsing prose? | should | write | src: restful-web-api-patterns ch-5 |
| filter/search endpoint returns 404 for an empty result set | **Empty is 200** — an empty match is a successful query; reserve 404 for a missing directly-addressed resource, 4xx for caller errors, 5xx for server faults | Is "no matches" an error here, or an answer? | should | review | src: restful-web-api-patterns ch-6 |
| request handler performs work that can exceed a few seconds synchronously | **202 + status resource** — acknowledge immediately, expose poll/cancel links and completed/failed URLs; explicit delay beats timeout roulette | Under worst-case data volume, how long does this handler hold the connection? | should | plan | src: restful-web-api-patterns ch-7 |
| diff removes, renames, retypes, or makes-required an element of a published API | **Don't change it, add it** — take nothing away, redefine nothing, make additions optional; changed defaults count as breaking (Hyrum's Law) | Could any existing caller observe this change as different behavior? | blocker | review | src: restful-web-api-patterns ch-2 |
| service persists or forwards a record after dropping fields it didn't recognize | **Must Ignore, round-trip whole** — ignore unknown fields when reading but return the complete record on update; stripping destroys other services' data through you | Does this write path preserve fields this service doesn't understand? | blocker | review | src: restful-web-api-patterns ch-6 |
| retry helper with fixed interval, unbounded attempts, or retry-on-4xx | **Backoff, bounded, 5xx-only** — exponential backoff, ~3 attempts, never retry an unmodified 4xx; synchronized retries amplify outages | Which failure classes does this retry, and what stops it? | should | review | src: restful-web-api-patterns ch-7 |
| API resource shapes mirror DB tables, ORM entities, or internal function names | **Interface is its own artifact** — translate internal models/names at the boundary (anti-corruption layer) so storage and refactors never surface as breaking changes | If the storage schema changed tomorrow, would this API change too? | should | plan | src: restful-web-api-patterns ch-5 |
| multi-service workflow or job runner without correlation IDs, progress visibility, or TTL | **Observable, cancelable jobs** — pass correlation-id/request-id on every hop, expose a progress resource with per-task status, auto-cancel past maxTTL | When a step fails at 2 a.m., how do you find which job it belongs to and stop it? | should | plan | src: restful-web-api-patterns ch-7 |
