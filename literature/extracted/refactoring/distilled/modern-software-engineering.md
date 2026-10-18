# Modern Software Engineering — distilled

> **Source**: David Farley, *Modern Software Engineering: Doing What Works to Build Better Software Faster*, Pearson 2022 · extracted from `../modern-software-engineering.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory that compiles *process* into falsifiable engineering rules: DORA stability/throughput as the fitness function for any process/tooling/org change, the deployment-pipeline scope rule ("scope of evaluation = one independently deployable unit"), testability as a design-quality *measurement instrument* (hard-to-write test ⇒ design defect, detected at write time), the DRY-scope boundary (deployment pipeline, never between services), and hard feedback-latency budgets (releasable ≤1 h from commit, commit stage ≤5 min). Other books tell you what good code looks like; this one tells you which observable signals prove your process is producing it — the upstream feed for a Testing Strategy lexicon section.

## Chapter map

- ch-1 — Introduction: what "engineering" means for software; the ten ideas (5 learning + 5 complexity) and 5 tools
- ch-2 — What Is Engineering?: design engineering vs production engineering; craft's precision ceiling; trade-offs
- ch-3 — Fundamentals of an Engineering Approach: DORA stability + throughput as the decision yardstick; CAB data
- ch-4 — Working Iteratively: flat cost-of-change; small batches; defined vs empirical process control
- ch-5 — Feedback: feedback-level ladder (IDE→unit→commit→acceptance); CI vs feature branching; TDD as design feedback
- ch-6 — Incrementalism: modularity enables piecewise delivery; refactoring/tests/Ports & Adapters as change-limiters
- ch-7 — Empiricism: assemble facts before hypothesizing; the parallelism/lock-cost numbers; Amdahl's law
- ch-8 — Being Experimental: hypothesis/measurement/controlled variables; predicting test failure messages; coverage-metric failure
- ch-9 — Modularity: points of measurement; determinism vs concurrency; service boundaries; deployability defines module scope
- ch-10 — Cohesion: relatedness-of-purpose; essential vs accidental complexity; DDD ubiquitous language/bounded context
- ch-11 — Separation of Concerns: one class one thing; dependency injection; Ports & Adapters; what counts as an API
- ch-12 — Information Hiding & Abstraction: big-ball-of-mud causes; YAGNI vs changeability; leaky abstractions; third-party isolation
- ch-13 — Managing Coupling: Nygard coupling taxonomy; DRY scope; microservices = org scaling; async messaging; the only two org strategies
- ch-14 — The Tools of an Engineering Discipline: testability, measurement points, deployability, speed, controlling variables, CD — the Testing Strategy core
- ch-15 — The Modern Software Engineer: BAPO vs OBAP; outcomes over mechanisms; durability test (applies to ML)

---

## ch-1 — Introduction {#ch-1}

**Working definition** (used throughout): *Software engineering is the application of an empirical, scientific approach to finding efficient, economic solutions to practical problems in software.*

Two master competencies, because software development is always discovery under uncertainty:

1. **Experts at learning** — via **iteration, feedback, incrementalism, experimentation, empiricism** (Part II).
2. **Experts at managing complexity** — via **modularity, cohesion, separation of concerns, abstraction/information hiding, loose coupling** (Part III). Needed so learning stays sustainable as systems outgrow one head.

Practical tools that operationalize both (Part IV): **testability, deployability, speed, controlling the variables, continuous delivery**.

The informal scientific method as a working loop: **Characterize → Hypothesize → Predict → Experiment**, controlling variables between runs. Applied at every granularity from a single TDD cycle to product strategy.

Paradigm-shift claim: adopting this discipline requires *discarding* superseded ideas (waterfall planning, coverage-as-quality, hero programming), not layering new practice on top. "If our 'software engineering' practices don't allow us to build better software faster, they aren't engineering, and we should change them."

## ch-2 — What Is Engineering? {#ch-2}

**Design engineering ≠ production engineering.** For software, production is `trigger the build` — automatic, near-free, solved. Software is *solely* design engineering: exploration, learning, iteration. Every "software factory"/production-line framing (waterfall, big-batch handoffs) misapplies production thinking to a discovery problem.

**Software's unique experimental advantage**: in every other discipline, models approximate the product (a bridge simulation is not the bridge). Our model — the code — *is* the product, testable in the exact environment of production. No other discipline can run millions of controlled experiments per hour on the real artifact.

**Craft's ceiling**: human-scale precision and repeatability. A human tester at 1 test/minute samples a 3 GHz machine at ~1:39,000,000 of what it does in the minimum humanly perceptible interval (13 ms). Manual verification is under-sampling by construction; engineering answers with instruments (automated tests) that measure faster and more precisely than the failure develops — detect the resource leak by measurement in minutes, not by a 3-week soak test.

**Formal methods failed mainstream adoption** because proving a complex system correct is harder than writing it, and provability collapses once concurrency, humans, or a complex domain enter. Like aerospace: use math to inform, then test the real thing.

**Margaret Hamilton (first "software engineer", Apollo flight control)** contributed two founding habits:
1. **Error obsession** — treat every idea/design with skepticism *until you run out of ways it could go wrong*: "a never ending pass-time of mine was what made a particular error, or class of errors, happen and how to prevent it in the future." Design reviews should enumerate failure modes, not confirm the happy path.
2. **Fail safely** — you can never code for every scenario, so build behavior that copes with the unexpected and still makes progress. Apollo 11's 1201/1202 alarms during lunar descent: the computer overloaded, rebooted, restarted only the important jobs (descent-engine steering, crew display), shed the erroneously scheduled radar jobs — and the landing proceeded. The fail-safe was implemented *without any specific prediction* of when it would matter. Rule: when a component saturates, degrade by shedding non-essential work while preserving the mission-critical path. (↔ same family as release-it's stability patterns — shed load, bulkheads.)

**Trade-offs are the substance of engineering decisions** (SpaceX steel-vs-carbon-fiber: cost/kg, strength at temperature — evidence-backed criteria). Coupling is software's master trade-off at every granularity. Corollary: a technology decision justified only by fashion/advocacy ("the illusion of progress") is not an engineering decision; tools matter only to the degree they move the dial on modularity, coupling, feedback.

## ch-3 — Fundamentals of an Engineering Approach {#ch-3}

Most software metrics are irrelevant (velocity) or actively harmful (LOC, raw test coverage). The DORA model (Forsgren/Humble/Kim, *Accelerate*) gives a correlative (not causal) but predictive yardstick:

| Dimension | Metric | Question it answers |
|---|---|---|
| Stability (quality) | **Change Failure Rate** | How often does a change introduce a defect? |
| Stability (quality) | **Recovery (Restore) Time** | How long to restore after failure? |
| Throughput (efficiency) | **Lead Time** | Single-line change → in production, how long? |
| Throughput (efficiency) | **Deployment Frequency** | How often do changes reach production? |

Key data points:
- Speed and quality are **positively correlated** — there is no speed/quality trade-off. High performers spend **44% more time on new work**. The real long-run choice is "better-faster" vs "worse-slower".
- **Change Approval Boards**: negatively correlated with lead time, deploy frequency, and restore time; **zero correlation with change failure rate** — "worse than having no change approval process at all."
- High DORA performance correlates with commercial success.

**Decision rule** (the book's master heuristic): for any proposed change to process, tech, org, or culture, ask *does it improve stability? does it improve throughput?* If it worsens either and you can't name the compensating gain, reject it; if it worsens neither, pick whichever you prefer. Measure before/after in your own team rather than trusting authority — including Farley's ("does this manual-testing stage actually improve stability, given that it certainly costs throughput?").

## ch-4 — Working Iteratively {#ch-4}

Iteration = repetition converging on a goal; it works even when you don't know the route, provided a fitness function tells you closer-vs-farther. Waterfall requires **defined process control** ("every piece of work completely understood, well-defined inputs") — a precondition software never satisfies; agile is **empirical process control** (Schwaber). "Inspect and adapt" starts from *we will inevitably get things wrong* and organizes to cheapen mistakes.

**Cost-of-change economics** (Dan North): classic model says change cost grows exponentially with time → forces the biggest decisions to the moment of maximum ignorance (project start). The engineering goal is a **flat cost-of-change curve**: discovering an error or new idea costs roughly the same whenever it happens. Achieving flatness *requires* small batches, modularity, CI/CD, automated regression testing — the rest of the book.

Why plans fail as a strategy — the plan-driven org implicitly claims it can do all of the following, and none survives contact with reality:

1. Correctly identify users' needs
2. Accurately assess the value of meeting them
3. Accurately estimate the cost of fulfilling them
4. Rationally decide benefit > cost
5. Make an accurate plan
6. Execute the plan without deviation
7. Count the money at the end

Data: at the best software companies, **2/3 of ideas produce zero or negative value** (Microsoft/large-scale online experiments) — we are terrible at guessing what users want, and users don't know either; 17% of >$15M projects threatened the company's existence (McKinsey/Oxford 2012). A defined plan is bounded by what is knowable up front (finite scope); an iterative approach is a "beginning of infinity" — unbounded, because each step generates knowledge for the next. So organize so that guesses can't destroy you: limit each guess's blast radius, validate continuously, and kill bad ideas at the lowest possible spend.

Iteration granularities, all the same idea:
- Sprint: coarse — production-ready work in a fixed window.
- **CI**: medium — commit atomic changes to shared mainline multiple times/day, each leaving the system releasable even mid-feature.
- **TDD**: fine — Red (write test, watch it fail) → Green (just enough code) → Refactor (small steps, test after each). Introduce classes/params via multistep refactorings, running tests continuously; always a couple of undo-steps from a safe place.

Small steps limit the time-horizon your assumptions must survive and cap the loss when one is wrong.

## ch-5 — Feedback {#ch-5}

Feedback = evaluative information returned to the controlling source. Without it you are guessing; most organizations run on guesswork, hierarchy, and tradition (e.g., writing business cases nobody ever validates against outcomes).

**Broom-balancing**: the predictive approach (compute the perfect balance point, place perfectly) has exactly one valid solution and fails on any perturbation; the feedback approach (watch tilt, correct continuously) has many valid paths and absorbs shocks — it is how rockets balance on thrust. Prediction-heavy plans are brittle by construction; feedback-driven processes are stable by construction.

Historical anchor: the **1968 NATO software engineering conference** already stated the durable ideas — Perlis: collect system-performance data in a feedback loop for future improvement (DevOps, 50 years early); Selig: feedback between external and internal specifications is essential to implementation (stories/what-vs-how); d'Agapeyeff: "shaping of modules and an environment for their testing; simulation of run time conditions" (testability + faked environments). The durable statements are of the form "establish feedback loops" and "assume you will get things wrong" — never "use language X." Durability is the test of a fundamental.

**Feedback-level ladder** — always prefer the lowest level that can catch the defect ("fail fast" / shift-left):

| Level | Mechanism | Latency |
|---|---|---|
| 1 | Type system / IDE while typing | ms |
| 2 | Unit tests for code under work | seconds |
| 3 | Full commit suite on CI trigger | minutes |
| 4 | Acceptance, performance, security tests | tens of minutes |
| 5 | Production telemetry | hours–days |

**CI vs feature branching — definitional incompatibility**: CI = merge everyone's work to shared mainline at least daily (ideally several times/day); branching = *isolate* change. One exposes change early, the other defers exposure. Merge tools cannot save FB: **behavioral conflicts** (you and I each add an increment to the same value in different places) merge cleanly at the text level and produce a double increment — merging code ≠ merging behavior.

**TDD as design feedback**: a hard-to-write test is an early, automatic signal of poor design. Test-first applies mechanical pressure toward modularity, SoC, high cohesion, information hiding, appropriate coupling — the same list as "hallmarks of quality," not by coincidence. TDD is a **talent amplifier**: it doesn't make bad developers great, but makes everyone measurably better than they'd otherwise be.

**Feedback in architecture**: target releasable software ≥ once/hour. Limiting case = deploy time + slowest single test; if either exceeds an hour, no amount of parallel hardware fixes feedback. Only two architectural responses: optimize a monolith for testability/deployability, or decompose into independently deployable services. Both force modularity and loose coupling — prioritizing feedback speed *causes* better architecture.

**Product feedback**: CD's real value is closing the idea→user loop; telemetry on feature usage moves an org from "business + IT" to a digital business. **Org feedback**: use stability/throughput as the fitness function for process and culture changes (correlative, not causative — still the best available).

## ch-6 — Incrementalism {#ch-6}

Iteration refines a thing; **incrementalism builds and (ideally) releases value piece by piece** — it needs modularity. Apollo lunar-orbit-rendezvous mission design as the canonical modular decomposition:

- Each module solved exactly one problem (Service: Earth↔Moon transit; Command: crew habitat + re-entry; Descent / Ascent: down to and up from the surface), so each compromised less and weighed less (the LEM never carried the return-to-Earth mass to the surface).
- Different companies built different modules **in parallel**, constrained only by agreed interfaces — the organizational payoff of module boundaries, 1960s edition.

**Organizational incrementalism**: transformations fail when driven by standardized processes ("process mapping" kills creative work). What predicts high performance: teams that can decide and act **without permission from outside the team**. Optimal team ≤ ~8 (Brooks: "fire the 175 troops and put the 25 managers back to programming"). Change strategy: many small autonomous teams making incremental changes toward a shared vision.

Tools that make increments safe:
1. **Architecture** — modularity + SoC limit blast radius of any step.
2. **Refactoring** — IDE-automated micro-transformations (extract method, introduce parameter) + version control ⇒ always a few steps from safety.
3. **Automated testing** — the safety net; also a feedback loop (testable → modular → safer increments).
4. **Ports & Adapters** — adapters at inter-component ports let core logic change without forcing change on collaborators; protocol changes (the expensive kind) become rarer and deliberate.
5. **Fast CI feedback** — breaking someone's code discovered in minutes is trivia; discovered months later, a crisis. Speed of feedback converts the same defect into a different cost class.

**Incremental design ≠ over-engineering**: don't code for imagined futures (YAGNI); *do* separate concerns even at a small line-count cost, because that keeps decisions reversible. Farley's own guiderails: functions ≲10 lines, ≲4 parameters — guides, not laws. "If your code is hard to change, it is low quality, whatever it does."

## ch-7 — Empiricism {#ch-7}

Empiricism = testing all theories against observed reality, not a-priori reasoning. Kept separate from "experimental" because you can run rigorous experiments on premises that don't match reality — then your model is precise nonsense.

**"I Know That Bug!" (canonical debugging lesson)**: exchange team saw stalled messaging + failing acceptance tests + a colleague's earlier weird messaging failure → concluded "new messaging code is broken," began planning a branch/rollback. Facts contradicted it (the messaging change had run green for a week). Once they *listed known facts first*, the log showed a threading bug in unrelated new code — fixed in 5 minutes. Rule: when debugging, write down what is actually known and check the hypothesis fits **all** facts before acting; a plausible narrative built guess-on-guess wastes the team on the wrong problem. (↔ same discipline as why-programs-fail's scientific debugging and debugging-9-rules "Quit Thinking and Look".)

**Inventing a reality (parallelism myth)**: academic premise "CPUs stopped getting faster (~2005), therefore parallelize algorithms." Mike Barker's experiment — same word-parse problem: concurrent Scala 61 LOC, 400 books/sec; single-thread Java 33 LOC, **1,600 books/sec**. Increment-500M-times microbenchmark:

| Method | Time |
|---|---|
| Single thread | 300 ms |
| Single thread + lock | 10,000 ms |
| Two threads + lock | 224,000 ms (746× baseline) |
| Single thread + CAS | 5,700 ms |
| Two threads + CAS | 30,000 ms (100× baseline) |

Locks and even CAS dominate once results must be joined; **Amdahl's law** caps concurrency benefit unless work is wholly independent. Rule: before building on a performance assumption, run the cheap experiment — the researchers never tested their starting premise.

**Self-deception is biological**: perception is a brain-constructed guess (visual field sampled ~every 2 s); we evolved to jump to conclusions. Feynman: "The first principle is that you must not fool yourself — and you are the easiest person to fool." Production is always "the best guess so far"; only 1/3 of Microsoft's ideas improved their target metric — treat every release as a learning opportunity, not a proof.

## ch-8 — Being Experimental {#ch-8}

Four characteristics of an experimental approach: **feedback** (close the loop with a clear signal), **hypothesis** (a stated idea under evaluation — science *institutionalizes guessing*; Feynman: "first, we guess it… if your guess disagrees with experiment, it is wrong"), **measurement** (success/failure defined before running), **controlling the variables** (eliminate noise so signals repeat).

Measurement failure cases:
- Team bonused on 80% **test coverage** hit the target; later audit found **>25% of tests contained no assertions**. They paid people to write tests that test nothing. What they wanted was quality → should have measured stability. Rule: coverage is a gameable proxy; a test without an assertion is a defect, not an asset.
- Low-latency trading: **averages are meaningless when outliers matter** — "2 ms" was a limit, not a mean; peak load was millions msg/s, not the average 100k. Measure percentiles at actual peak load. (↔ agrees latency-book & DDIA on percentile latency; coordinated omission.)

**Controlling variables is CD's real mechanism**: version control makes the deployed change precise; automated tests make behavior precise; deployment automation + infrastructure-as-code make environments precise. With technical variables controlled, the remaining question is the valuable one: are we building the right thing?

**Automated tests are experiments**; TDD is the clearest form. Micro-protocol for every new test: characterize (behavior wanted, as a test) → hypothesize ("this test will fail") → **predict the exact failure message** → run and observe. If it passes before code exists, or fails differently than predicted, the *test* is wrong — fix it before proceeding. TDD defect-reduction data: 40%–250%+ vs conventional development.

**Body of tests = body of knowledge**: the suite plus IaC-defined environment is an internally consistent, executable statement of everything known about system behavior; new knowledge (a new test + code) that contradicts prior knowledge fails visibly within minutes. That turnaround — minutes, not the months of physical sciences — is software's super-power.

## ch-9 — Modularity {#ch-9}

Module hallmarks: understandable stand-alone; has inside/outside with scope control; interface governs all communication; reusable in multiple contexts. Most bad code doesn't do modularity *badly* — it doesn't attempt it: "recipe code," linear step-lists in functions of hundreds of lines.

**Enforced guiderails**: Farley starts projects with a commit-stage pipeline check that **rejects any commit containing a method >20–30 lines or a signature >5–6 parameters**. Values are arbitrary/per-team; the point is mechanical enforcement keeps design honest under time pressure. (↔ contra philosophy-of-software-design ch-9: Ousterhout warns length-based decomposition can produce shallow "classitis"; Farley's own caveat — guiderails, not goals — is the reconciliation.)

**Testability drives modularity (wind-tunnel argument)**: you don't evaluate an airfoil by building the whole plane and flying it — too many uncontrolled variables, unmeasurable, unrepeatable. You isolate the component in a controlled rig. Software equivalent: testing chained systems A→B→C end-to-end cannot answer "what if A sends malformed data?" or "what if comms to C fail?" (the real A and C prevent the scenario), and any failure is unattributable. You need **points of measurement** — stable interfaces where probes inject inputs and collect outputs. End-to-end tests of the composite are at best a small supplement, never the strategy.

**Determinism**: root cause of non-determinism is concurrency. Design so concurrency is isolated *between* modules and entry into each module is sequenced → every module deterministic → tests reliable. Taken seriously, this yields record-and-replay: Farley's exchange could replay recorded production inputs to reproduce exact state in test. Same-version + same-test must give the same result every run, or your "definitive" release evaluation means nothing.

**Services as modules**: a service delivers capability while hiding implementation — the boundary is the point. Commonest large-codebase failure: **boundary code indistinguishable from interior code** — same calls, same data structures passed through, no validation, no translation → tangle. REST accidentally helped by forcing a text-encode/decode point, but people still pass raw HTML/payloads straight through. Entry points should be defensive barriers: validate inputs, assemble outputs (Ports & Adapters at service level, for any transport including plain method calls).

**Deployability defines module scope**: a deployment pipeline's output must be **independently deployable**; if the pipeline says "good," it's good to go — no further integration tests or sign-offs. Only two coherent strategies: (1) build/test/deploy everything together (monorepo/monolith + serious investment in fast feedback), or (2) each module fully independent. **The middle ground is a fudge** — slower and more complex than either extreme. Microservices are modularity taken to independent deployability; *if you test your microservices together before release, they are not microservices*.

**Fine-grained scale**: service-level modularity without fine-grained code modularity still yields hard-to-work-with systems — modularity is fractal down to methods. Dependency injection is the strongest fine-grained pressure: injected dependencies are the calipers. Answer to the "DI/large surface area makes control flow harder to follow" criticism: **if the surface must be exposed to test the code, that *is* the code's real surface area** — obscuring it doesn't shrink it, it just removes the tests.

**Human systems**: adding people doesn't scale development; decoupling teams does. QSM meta-study, 4,000+ projects: teams of ≤5 took only one week longer than teams of 20+ over 9 months — small teams ~4× productivity/person — and big teams produced **5× more defects**. Amazon two-pizza teams: scale by decoupling. Microservices are an *organizational* scalability play; technical benefit is secondary.

## ch-10 — Cohesion {#ch-10}

Cohesion = "degree to which the elements inside a module belong together"; Beck: "Pull the things that are unrelated further apart, and put the things that are related closer together." Piling everything into one file/method is not cohesion, it's absence of structure — *naive cohesion*.

Canonical micro-example: `loadProcessAndStore()` doing file-read, sort, file-write inline (load-process-store) vs extracting `readWords`/`sortWords`/`storeWords`. The second is more lines and *better*: each part focuses on one task and touches only what it needs. **Optimize to reduce thinking, not to reduce typing** — code's primary audience is humans; never buy brevity with obscurity.

Cohesion is contextual; tools for drawing the lines:
- **DDD**: code as a simulation of the problem domain. **Ubiquitous language** — the same words (`LimitOrder`, `Match`) in business conversation and code. **Bounded context** — "order" in order-management ≠ "order" in billing; distinct contexts are naturally loosely coupled, so aligning services to them yields low coupling for free. DDD's payoff property: a small change in the problem domain is a small change in the code.
- **Coupling relation** (C2 definitions): A,B *coupled* when B must change *only because* A changed; *cohesive* when a change to A lets B change so both add value. Coupling is the price of cohesion — cohesive regions are more internally coupled, by design.
- **TDD**: writing the test first designs the external API; writing *more* code than the test demands reduces cohesion (and cheats the process); writing less fails it. The discipline aims you at the sweet spot.

Detection cues: to make one conceptual change you edit many distant places → poor cohesion; class with two unrelated fields each used by one method → split it; "I don't know what this code does" → usually poor cohesion. Poor cohesion is the everyday texture of **legacy code** (Feathers' definition, quoted approvingly: *a system without tests*).

**Performance myth**: high performance requires simple code, not messy code — max work per instruction means the optimal path must be visible. Optimizing compilers inline small methods and **give up above a cyclomatic-complexity threshold**. Benchmark of the extracted-methods version vs inline: ~6 ns/call difference, sign flipping run to run. **Don't guess what's fast; measure.**

**Human systems**: DORA's leading predictor of high performance — teams that decide without external permission — is informational cohesion: the team contains everything it needs.

## ch-11 — Separation of Concerns {#ch-11}

Definition in practice: **"One class, one thing. One method, one thing."** SoC is the *technique* that produces modularity and cohesion; it's also the most objectively checkable of the five: if a unit does more than one thing, concerns aren't separate — little judgment required.

War story (why it pays): Farley's exchange kept strict SoC from function level to enterprise level — business logic knew nothing of remoting, persistence, collaborator addresses, security, clustering; all supplied elsewhere. Swapping the commercial RDBMS for open source: download, script deployment, adjust one adapter, two test failures fixed, deployed days later — **one morning of work**. Without SoC: months-to-years, likely never attempted.

**Essential vs accidental complexity** (Brooks) as the first cut: essential = inherent to the problem (cart total, order match); accidental = side effects of using computers (persistence, display, clustering, most security plumbing). The three-version `add_to_cart` canon:

```python
def add_to_cart1(self, item):          # essential + raw SQL, connections — untestable without a DB
def add_to_cart2(self, item):          # storage behind injected self.store — testable with fakes;
                                       #   still knows storage exists
def add_to_cart3(self, item, listener):# fires listener.on_item_added — core logic knows nothing of
                                       #   storage/totals; most separated, most testable
```
v1 is ruled out by SoC; v2 vs v3 is contextual design choice. Testability ranks them: v1 needs a real database (slow, fragile, unparallelizable); v2/v3 test with fakes.

**Dependency injection** = dependencies supplied as parameters rather than created internally. Not a framework feature — a language-agnostic design decision that flips code from "tightly bound to one implementation it constructs" to "collaborator with anything satisfying the contract," and draws the demarcation line between concerns.

**DDD signal**: needing "and" to describe a class/method = SoC violation. Battleship example: `GameSheet` accumulated placement *and* rules-validation (6 of 11 tests were about rule-checking); extracting `Rules` deleted ~10 lines of validation from the sheet, simplified tests, and created a seam for future rule variants with zero speculative work. Keep a **low tolerance for complexity**: the moment code feels like hard work, hunt for the missing concept.

**Ports & Adapters**: mixed abstraction levels in one scope (`process(thing)` then `s3client.putObject(...)`) is an SoC failure — the second line is an interloper from the accidental realm. Introduce a port at your level (`store.storeThings(...)`); the concrete adapter translates. The port exposes only the subset of the external API you actually use, so it's simpler than the real thing, testable without it, and an S3-client-v2 migration touches one adapter instead of every call site. Evans: **"Always translate information that crosses between bounded contexts."** Default stance: apply Ports & Adapters wherever the code you talk to lives in a different scope of evaluation (different repo, different deployment pipeline).

**What is an API**: *all* information exposed to consumers — if your function parses the content of a byte stream, the stream's structure and semantics are part of your API and of your coupling surface. Adapters must translate/validate the whole API, not just the signature. A messaging system must not know what messages say (wrap payloads opaquely); knowing couples transport to conversation semantics.

## ch-12 — Information Hiding and Abstraction {#ch-12}

Treated as one idea: draw **seams** so consumers need know nothing of what's behind them (behavior, implementation detail, and data). Writing software *is* creating abstractions; the skill is creating good ones.

**Big-ball-of-mud causes — cultural**: "my manager won't let me refactor/test" is usually an excuse; developers are complicit when they parse estimates into "with/without quality." Chef analogy: a professional doesn't ask permission to sharpen knives — quality practices are the job, not a negotiable extra. Managers want better-software-faster; the data (44% more feature time for disciplined teams) says quality *is* the speed strategy. Don't offer quality-stripped estimates.

**Technical causes**: frozen code is dead code (Brooks: "As soon as one freezes a design, it becomes obsolete"). Dan North's **software half-life**: team quality ~ time to rewrite half the code they own — good teams: months; poor teams: never. Fear of change begets **future-proofing** (speculative generality), which is design immaturity: **YAGNI** — build only for now, but make the code *safe to change at any future time*. Three routes to safe change: (1) hero programmer who understands everything — "the stupid one," yet the most common; (2) **abstraction**; (3) **testing**. The real answer is 2 + 3.

**Over-engineering war story (abstraction vs pragmatism)**: an insurer's "strategy group" mandated a grand distributed component architecture — services for everything, infrastructure handling security/persistence/integration. It was vapor-ware: 40+ people, 3–4 years late, documents and non-working code; *every* project was mandated to use it, *no* project ever did. Farley's rescue team politely declined and shipped. Rule: if a platform/architecture is mandated but has no working consumer, treat it as imaginary; explore shiny tech as a cheap, discardable trial, never as the load-bearing cornerstone.

**Why "raise the abstraction level" keeps failing (diagram-driven / low-code sidebar)**: code generation from diagrams dies on the **round-trip problem** — you always learn things that invalidate the early skeleton, and regenerating diagrams from hand-modified code while keeping the detail is the hurdle every attempt has fallen at. Diagrams-as-the-program demo brilliantly because a graphical DSL on a narrow problem *is* powerful — but general-purpose logic is inherently intricate, and you forfeit exception handling, version control, debugging, libraries, automated testing. "Text is a surprisingly flexible, concise way of encoding ideas." Genuinely promising abstraction-raiser: **DSLs** — narrow by design; the best test suites are executable specifications in a domain DSL.

**Test-first improves abstraction**: a specification is written before the work, so write the test before the code. The test then expresses the abstraction from the consumer's side, divorced from implementation. Consequence: if the test is fragile under change, the *abstraction* is fragile — feedback no other technique provides. (Test-after coupling to implementation is the true source of the "tests lock the design" complaint.)

**Leaky abstractions** (Spolsky: all non-trivial abstractions leak) — two kinds of leak:
1. Physically unavoidable (GC pauses, RAM-vs-cache latency in low-latency systems): design around them consciously.
2. Continuity breaks from lazy design: an auth service reporting *business* failures as HTML error codes; domain logic surfacing `NullPointerException`. Fix by holding one abstraction level per scope — technical failures may use technical channels; business failures must be modeled in the domain (e.g., a boolean/result value for a transactional store failure, not vendor error codes; or reliable async retry that preserves the abstraction entirely).

Box: "All models are wrong, some models are useful." Choose abstractions for the *purpose*: Mercator chart (constant bearing, wrong distances) vs Beck's Tube map (topology, wrong geography) — both excellent, non-interchangeable. Accuracy is not the goal; fitness for the problem is.

**Isolate third-party code**: letting third-party types into your code couples you to them. Default: language + standard library allowed inside; every other third-party library accessed via your own facade/adapter; be wary of frameworks that impose their programming model. (Combines with ch-11 ports rule: the wrapper is the port.)

**Prefer hiding, within bounds** — return-type ladder: `ArrayList<String>` (over-specific: callers rarely care about ArrayList-ness) < `List<String>` (sweet spot: abstract yet self-documenting) < `Object` (generic to the point of useless). Prefer the most general representation that still documents intent.

Guidance from the domain: **event storming** (Brandolini) maps domain interactions; behavior clusters → module/service candidates; highlights bounded contexts and natural abstraction lines. **DSLs**: the best test suites are executable specifications written in a small DSL of the domain's desirable behaviors.

## ch-13 — Managing Coupling {#ch-13}

Coupling = interdependence between modules. Perfect decoupling = no communication = useless; the goal is *managed* coupling. Costs of too-tight vastly exceed costs of too-loose in practice, so **default looser** — but know the failure mode on each side.

**Nygard coupling taxonomy** (evaluate designs against each row):

| Type | Effect |
|---|---|
| Operational | Consumer can't run without provider |
| Developmental | Producer and consumer changes must be coordinated |
| Semantic | Change together because of shared concepts |
| Functional | Change together because of shared responsibility |
| Incidental | Change together for no good reason (e.g., breaking API changes) |

**Scaling**: development scales by reducing inter-team coupling, not by headcount. Two strategies only —
1. **Coordinated** (monorepo/monolith): everything stored/built/tested/deployed together; coupling's symptoms managed by making feedback so fast (CI/CD at Google/Facebook scale) that coupled work stays cheap. Costs heavy infrastructure investment most orgs won't make.
2. **Distributed** (microservices): decision-making distributed, services independently deployable, no direct coordination cost — indirect cost is design sophistication (insulation, protocol/versioning discipline) and *consciously loosening central control* (guidance yes, enforcement no — enforcement reinstates coordination cost).
No coherent middle ground; hybrids inherit both cost profiles. Manage coupling by checking faster when coupling is high, or not checking together at all when coupling is low.

**Microservices defined**: small; focused on one task; aligned with a bounded context; autonomous; **independently deployable** (the defining, genuinely-new property); loosely coupled. If version compatibility with collaborators must be tested before release, they're not independently deployable and the architecture is a distributed monolith. Don't adopt microservices unless the thing you need to scale is the *organization*.

**Decoupling may mean more code** — and that's fine: two extra lines to extract `store_item` buys cohesion and SoC; at 800-line-function scale, unmanaged code hides duplication that decoupled code exposes and removes. **Optimize for thinking, not typing.**

**Too-loose exists**: finance client "stored anything" via fully abstract name-value/star schema with recursive links — loading one business record took hundreds-to-thousands of DB round trips. Total abstraction, unusable performance. Draw seams so hot paths sit *inside* one module; pay transition costs at module boundaries only. Performance is never an excuse for a ball of mud: fast code is simple, predictable code (ch-10).

**DRY has a scope**: one canonical representation is excellent *within* a function/class/service — precisely, **within one deployment pipeline** (one independently deployable unit). Between independently deployed services, shared code (e.g., a common library forcing lock-step upgrades) is insidious **developmental coupling**: **do not share code between microservices**; accept duplication as the cheaper cost. (↔ tension with refactoring-fowler-beck's broad duplication-removal instinct: Fowler operates within one codebase/pipeline, where Farley agrees.)

**Async as decoupling tool**: synchrony across any process boundary is an illusion (a leaky abstraction). Nine failure points in a "synchronous" A→B call (bugs at each end, connect failures each side, lost request, lost response, dropped connections mid-flight); with reliable async messaging the same failures exist but A's code no longer handles them inline — even "meteorite hits B's datacenter" resolves by redeploying B and resubmitting, with identical processing semantics. Prefer async events between distributed modules; it models reality and shrinks coupling to accidental complexity. (↔ complements release-it's integration-point defenses: Nygard hardens sync calls, Farley removes them.)

**Coupling ≠ (inverse of) separation of concerns** — the two vary independently; check both:
- *Good SoC, tight coupling*: an order-processing service and an order-storage service, cleanly separated, but exchanging a detailed shared "order" shape — if one changes its concept of order, the other breaks (semantic coupling survives the separation).
- *Loose coupling, poor SoC*: two account services moving money via a fire-and-forget async message ("A debited, credit B") — technically decoupled, but one logical transaction is smeared across both with no protocol keeping the ends in step; a lost message loses money. Loose coupling doesn't excuse an incoherent responsibility split; you still need the transaction concern designed and owned somewhere.

**Design signal**: hard-to-test code usually means inappropriate coupling — respond by changing the design, not by writing a heavier test.

## ch-14 — The Tools of an Engineering Discipline {#ch-14}

The chapter that operationalizes everything: five interlocking tools — **testability, deployability, speed, controlling the variables, continuous delivery**. Adopt only these as organizing principles and the rest of the book re-derives itself.

Four things development must learn, continuously: *Are we solving the right problem? Does our solution work as we think? What is the quality of our work? Are we working efficiently?* Humans can't proofread their way to correct software (we see what we expect); code that has never been run is a hostage to fortune; separate testing teams give slow, late, low-context feedback. So testing must be automated, continuous, and designed-for.

### Testability

Testable code is *forced* to be modular, cohesive, well-separated, information-hiding, appropriately coupled — testability is the one property that implies the others, and the only early objective signal of design quality besides taste.

Canonical micro-example (**BetterCar**): `Car` constructing `new PetrolEngine()` internally has *nothing to assert* — the effect of `start()` is invisible without breaking encapsulation (making fields public / backdoor hacks — both terrible). Inject the engine:

```java
class Car { private final Engine engine = new PetrolEngine(); ... }   // untestable endpoint
class BetterCar { BetterCar(Engine engine) { this.engine = engine; } } // injectable
// test: FakeEngine engine; new BetterCar(engine); car.start();
//       assertTrue(engine.startedSuccessfully());
```
One DI step abstracts `Engine`, removes construction responsibility, and as a side effect the car now takes Petrol/Electric/Jet/Fake engines — **designing for testability produced the flexibility**. Fakes recording interactions are the measurement instrument.

**Measurement points** are the unit of testability: places to establish state, invoke behavior, and observe results without compromising integrity. Fine-grained: parameters, return values, injected fakes. System-level: fake every external dependency at the system's integration points and treat the whole system as a black box (the exchange faked banks/clearinghouses and injected account registrations).

**Edge problem (technical)**: at system edges (disk, screen, DOM, hardware) you can't inject/collect. Solution: push edges to the margins and minimize their complexity — define an abstraction for the interaction, test against a fake of it, write a dumb adapter to the real edge ("add a level of indirection; you can always do this"). Example: a `Display` interface with `ConsoleDisplay` at runtime and a mock in tests; project example: a JavaScript component factory "in front of the DOM" (Ports & Adapters for the DOM) making web UI logic unit-testable without a browser.

**Culture problem**: every team claiming "we tried TDD and it didn't work" turns out to have written unit tests *after* the code. Test-after encourages corner-cutting, encapsulation-breaking, and tests tightly coupled to existing structure — producing exactly the "tests block change" symptom then blamed on TDD. Test-first is the practice; Farley has never met a team that genuinely practiced it and found it didn't work. (↔ working-effectively-with-legacy-code: for code that already exists, characterization tests written after the fact are the entry ramp — different problem, not a contradiction.)

**Test discipline per increment**: work iteratively, one test per small piece; structure each test as an experiment — predict the failure and its message before running (verifies the test tests what you think); make it pass; then use the passing code+test platform to refactor safely. **If the test before you is difficult to write, the design of the code is poor and needs improvement — fix the design, not the test.** Testability is fractal: enterprise system down to three lines.

### Deployability

**Deployable ≠ releasable**: deployable = safe to put into production even with unfinished features hidden (flags/dark launch); releasable = feature-complete for users. CD works in deployable units so features can span many deployments.

Deployability bundles everything that "no more work to do" means in context: works, fast enough, secure enough, resilient enough, compliant enough. **If the deployment pipeline passes, there is no more testing, no sign-offs, no further integration checks before production.** Therefore: **the scope of evaluation (the pipeline) must equal one independently deployable unit**. If you can't confidently release on a green pipeline without extra work, the pipeline's scope is wrong — either widen it to the real unit (whole system) or genuinely decouple the parts. Components built in separate repos but validated together have a whole-system evaluation scope no matter what the org chart says, and the feedback time that matters is the *whole-scope* time.

### Speed

Feedback speed is a **fitness function** for the entire method (agile, lean, CD, DevOps): target a production-quality deployable outcome **≤1 hour from any commit** (commit stage ≤5 min; aim for something releasable every hour; result in five minutes from the commit stage). Work backward from the target and it forces: small non-siloed teams (communication overhead), serious automated testing, CI/CD, architecture cut into independently deployable units. Chasing the number produces the practices; following practice rituals doesn't reliably produce the number. Physical-product caveat: Tesla/SpaceX/telecoms can't hit one hour, but the principles (always releasable; reject on first failing test; simulate to keep feedback fast) still bind — treat the target as a direction under physical/economic constraints.

Speed war story (ch-8 sidebar "The Need for Speed"): a 9.5-hour nightly C++ build; in three years, **all tests passed on 3 occasions** — teams shipped whichever modules happened to be green, breaking when a green module depended on a red one. Reworking only feedback (12-min commit stage + 40-min remainder, no other process/tooling/org change) yielded at least one all-green, releasable build per day within a month. Feedback speed alone gave teams the tool to fix the underlying instability.

### Controlling the Variables

Same inputs must give same outputs: automate deployment, manage configuration as code, version-control everything that defines the "universe" of a test. Where you can't control (external environment, third-party systems), abstract the dependency and depend on it minimally.

- **Flaky/variable test results = insufficient control**; either isolate the test better or make the code more deterministic. A result you can't reproduce means nothing (perf suite run on the corporate network → results incomparable between runs → all that effort waste).
- **Concurrency rule**: reliably testable code is **not multithreaded within the scope of a test** (narrow exceptions aside). Design concurrency out to controlled, well-understood edges; the payoff is deterministic tests *and* more comprehensible, usually faster code.
- Long-running or manual tests are often a symptom of uncontrolled variables, not thoroughness.

### Continuous Delivery

CD is the organizing philosophy: work so software is **always in a releasable state**, producing a semi-continuous flow of small changes. It is not deployment automation (that's a part); it demands minimized organizational dependencies, autonomous small teams, high automation (especially testing), repeatability and reliability everywhere. Best available scaffold for a software engineering discipline.

### The testing strategy, compiled (Part IV synthesis)

Farley's whole testing position in one table — what to run, where, with what discipline, and what a violation looks like:

| Layer / concern | Rule | Budget / bound | Violation signal |
|---|---|---|---|
| Test authorship | Test-first, always; the test is a mini-specification written from the consumer's side | One test per small increment, minutes apart | Tests mirror implementation structure; privates exposed; "TDD didn't work" |
| New-test validation | Predict exact failure message; run; observe predicted failure before writing code | Seconds | Test passes before code exists; fails differently than predicted |
| Unit scope | Single-threaded within the scope of a test; all collaborators injectable; assert one named behavior | ms per test | Threads/sleeps in tests; real DB/file/network; multi-behavior assertions |
| Measurement points | Every unit observable via params, returns, injected fakes; every system-edge behind an owned abstraction with a dumb adapter | — | "Can't test without breaking encapsulation"; logic reaching directly into DOM/disk/SDK |
| Commit stage | Full unit + static checks + guiderail enforcement (method length, param count) on every commit to mainline | ≤5 min | Guiderails advisory-only; commit stage skipped under pressure |
| Acceptance stage | Executable specifications (ATDD/BDD, ideally a domain DSL) against a production-like, IaC-defined environment with all external systems faked at integration points | Whole pipeline ≤1 h | Staging tests against live third parties; environment drift; manual test phases |
| Determinism | Same version + same test ⇒ same result, every run; record/replay possible at full-system level when concurrency is isolated | 0 flakes tolerated as "normal" | Retry-until-green culture; quarantined-flaky lists that never shrink |
| E2E / whole-system | Thin supplement only: deployment/config smoke, black-box flows with faked externals | Small fixed suite | E2E as primary strategy; unattributable failures; can't inject malformed input |
| Performance tests | Isolated rig, controlled variables, discard warm-up runs, statistics over many runs, percentiles at peak load | Reproducible to μs where it matters | Corporate-network test runs; averages; results incomparable between runs |
| Scope of evaluation | Pipeline scope = one independently deployable unit; green ⇒ deployable, full stop | — | Post-pipeline sign-offs; cross-pipeline integration testing; release trains |
| Metric of health | Stability (change-failure rate, restore time) + throughput (lead time, deploy frequency) | Trend-tracked per change | Coverage targets; velocity; LOC; assertion-free tests |

### Evaluating any third-party tech (qualifier checklist, before "is it useful")

1. Deployable? (automatable, reliable, repeatable deployment)
2. Testable in the context of our system?
3. Lets us control the variables? (version-controlled config, reproducible deployments)
4. Fast enough for CD? (deploy/evaluate multiple times per day)
5. Preserves our modular design, or imposes its own programming model?

A wrong answer to any question disqualifies the tech unless it's indispensable — and if indispensable, the cost of achieving these properties despite it goes into the cost-benefit.

## ch-15 — The Modern Software Engineer {#ch-15}

All ten ideas interlock (can't separate concerns without improving modularity; modularity enables feedback and experiments). The best developers write good software in any language/toolchain — the transferable skill is these principles, not tool mastery; the tech choice matters about as much as the model of a carpenter's hammer.

**BAPO vs OBAP** (Jan Bosch): most firms run **OBAP** — Organization fixed first, then Business strategy constrained by it, then Architecture, then Process: backwards, the business vision hostage to the org chart. Engineering-led firms run **BAPO**: Business vision → Architecture to achieve it → Process to build it → Organization as a *tool* shaped to support that process. Digitally disruptive companies (Amazon, Tesla, Uber) are engineering-led — software is the business, not a cost center; Tesla reconfigures the factory through software.

Org-coupling data: Amazon more than doubles productivity when doubling headcount; traditionally structured firms gain ~85%. High-performing teams are **informationally decoupled** — they decide without outside permission (the Accelerate finding, again).

**Outcomes over mechanisms**: CD is stated as an outcome ("always releasable; optimize for fast feedback") so it generalizes to unforeseen situations; DevOps is a practice collection, so it under-specifies novel cases. Measurable outcome set: commercial results, usage/adoption, DORA stability + throughput, customer satisfaction. Good stability/throughput with a failing product means the *product idea or business strategy* is at fault, not delivery — the measures cleanly split the blame.

**Durability test — apply the model to ML** (a domain Farley disclaims expertise in). The workflow (collect → prepare data → train against fitness functions → validate → deploy → monitor → retrain) maps directly:
- **Control the variables**: version-control training data *and* scripts — basics often missing where practitioners lack a software background.
- **Iterate/experiment**: each training run is an experiment; optimize the loop so it's short with clear feedback.
- **Predict before release**: deploying a model is an experiment, so state expected error bounds up front and monitor against them (a book-recommender drifting toward "take over the world" is out of bounds regardless of fitness score).
- **Manage complexity in data**: modular, focused training data = faster iteration; embedded bias (economic status ↔ ethnicity, salary ↔ gender baked into training data) = **poor separation of concerns in the data**.

A real engineering discipline poses useful questions even in unfamiliar territory — that generality is the point.

Closing frame: (1) optimize everything to maximize learning; (2) at every scale, manage complexity. Simple model, hard to apply — "software is difficult, so let's approach it thoughtfully."

---

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Any proposed process/tool/org/tech change | Ask: does it improve stability (change-failure rate, restore time) and/or throughput (lead time, deploy frequency)? Reject if it worsens either without a named compensating gain | DORA: the only validated yardstick; speed and quality are positively correlated | ch-3 |
| Plan adds an external approval step (CAB, sign-off gate) | Remove it; replace with pipeline-automated checks | CABs correlate negatively with lead time/deploy frequency/restore time and **zero** with change failure rate | ch-3 |
| Design review covers only the happy path; component has no defined overload behavior | Enumerate failure modes until you run out; on saturation, shed non-essential work and preserve the critical path (fail safely) | Hamilton: you can't code every scenario; Apollo 11 landed because the 1202 overload shed radar jobs, not the descent engine | ch-2 |
| A change is planned as one large batch with no intermediate verified state | Slice it so every step leaves the system releasable and is minutes from a safe rollback point | Small steps cap assumption horizon and loss-per-mistake; flat cost-of-change requires it | ch-4 |
| Branch has diverged from mainline >1 day | Merge to mainline now (or slice work so you can); branch isolation is definitionally incompatible with CI | Merge tools miss behavioral conflicts (two increments merge cleanly, double the effect) | ch-5 |
| A defect class is caught at level N of the feedback ladder but detectable at level N−1 (type/unit/commit/acceptance) | Move detection down a level | Lower level = faster, cheaper, better-attributed feedback ("fail fast") | ch-5 |
| Debugging: hypothesis formed before facts listed | Stop; write down everything known; check hypothesis fits **all** facts before acting | "I Know That Bug!" — plausible narratives built guess-on-guess burn hours on the wrong problem | ch-7 |
| Design assumes parallelism will speed up an algorithm whose results must be joined | Run the single-thread baseline experiment first | Lock: 33×; two threads + lock: 746×; CAS: ~19× slower than single thread; Amdahl caps joined work | ch-7 |
| New test about to run for the first time | Predict the exact failure message before running; if it passes immediately or fails differently, fix the test | A test never seen failing is unverified; the experiment protocol validates the instrument | ch-8 |
| Test coverage used as a target/incentive | Replace with stability metrics; audit for assertion-free tests | Coverage is gameable: bonused 80% target produced >25% assertion-free tests | ch-8 |
| Latency requirement stated as an average | Restate as percentile/limit at measured peak load | Averages are meaningless where outliers matter; 2 ms was a limit, peaks were 10× the mean rate | ch-8 |
| Diff introduces a method >20–30 lines or >5–6 parameters | Break it up (team-tunable guiderail, enforceable as a commit-stage check) | Recipe-code is non-modular by construction; guiderails keep design honest under pressure | ch-9 |
| Test suite gives different results for the same version | Treat as a defect in control of variables: isolate the test or remove non-determinism (usually concurrency) from the code | Non-deterministic evaluation cannot certify releasability | ch-9, ch-14 |
| Test plan's primary strategy is end-to-end tests of A→B→C together | Add points of measurement at module interfaces; make E2E a thin supplement | Composite tests can't express malformed-input/broken-comms cases and failures are unattributable | ch-9 |
| Boundary code passes interior data structures through unvalidated / untranslated | Make every service entry point a defensive barrier: validate inputs, assemble outputs | Boundary indistinguishable from interior is the commonest path to a tangled codebase | ch-9 |
| "Microservices" that are tested together before release | Admit it's a distributed monolith: either widen pipeline scope to the whole, or decouple until independent | Independent deployability is the defining property; the middle ground is a fudge | ch-9, ch-13 |
| One conceptual change requires edits in many distant places | Improve cohesion: co-locate what changes together (bounded contexts as the guide) | Cost-of-change is the measure of cohesion | ch-10 |
| Extraction/decoupling rejected because "it's more lines / more typing" | Accept the line-count cost; optimize for thinking, not typing | Code communicates to humans; at scale, managed structure exposes and removes the duplication that unstructured code hides | ch-10, ch-13 |
| Resource leak suspected; multi-week soak test proposed | Instrument instead: measure resource trends in regular short test runs and alert on the slope | Engineering = precision of measurement beating waiting-for-obvious-failure; minutes vs weeks to signal | ch-2 |
| Business case / feature shipped with no outcome tracking | Define the expected metric movement up front; instrument and compare (telemetry) | Only 1/3 of ideas improve their target metric; unvalidated business cases are guesswork with a spreadsheet | ch-5, ch-7 |
| Code kept inline/convoluted "for performance" | Demand a measurement; prefer simple code | Compilers inline and optimize simple code, give up above complexity thresholds; measured diff was ~6 ns and sign-unstable | ch-10 |
| Class/method description needs "and" | Extract the missing concept (SoC violation) | Battleship `Rules` extraction: simpler class, focused tests, free future seam | ch-11 |
| Function constructs its own dependencies (`new`, global connection, singleton) | Inject them as parameters/constructor args | Construction couples to one implementation; injection creates the measurement point | ch-11 |
| Two abstraction levels in one scope (domain call next to vendor-SDK call) | Introduce a port at the domain's level; adapter translates | Consistent abstraction per scope; vendor API v2 migration = one adapter, not every call site | ch-11 |
| Code reads/interprets content of a payload it transports | Either that content is officially part of your API (validate/translate it in the adapter) or wrap it opaquely | Coupling surface = all information the code understands, not the signature | ch-11 |
| Code written "we'll probably need it later" | Delete (YAGNI); invest instead in changeability (abstraction + tests) | Future-proofing fixes design at max ignorance; safe-change makes prediction unnecessary | ch-12 |
| Business-level failure surfaced via technical mechanism (HTTP codes for domain errors, NPE from domain logic) | Model failure in the domain abstraction (result value / domain error / reliable retry) | Continuity break in the abstraction; technical channels are for technical failures | ch-12 |
| Third-party library types appearing in domain code | Wrap behind your own facade/adapter; allow only language/stdlib inside | Third-party code inside = coupling to its model and its release cadence | ch-12 |
| Return type over-specific (`ArrayList<String>`) or over-generic (`Object`) | Pick the most general type that still documents intent (`List<String>`) | Hide information within self-documenting bounds | ch-12 |
| Shared library forces consumer services to upgrade in lock-step | Cut the share: DRY's scope is one deployment pipeline; duplicate rather than couple across services | Dependency management is insidious developmental coupling; defeats independent deployability | ch-13 |
| Cross-process call treated as synchronous in domain logic | Model the boundary as async messaging | Sync-over-network is a leaky abstraction with ~9 failure points the caller otherwise owns inline | ch-13 |
| A test is hard to write | Change the **design** (coupling/SoC), not the test | Hard-to-test is the earliest objective signal of a design defect | ch-13, ch-14 |
| Behavior's effect invisible to a test without breaking encapsulation | Add a measurement point via DI (fake records the interaction); never expose privates for tests | BetterCar: the untestable design was also the inflexible one | ch-14 |
| Logic entangled with a system edge (disk, DOM, screen, hardware) | Abstract the edge, test against a fake, keep the real adapter dumb and margin-thin | You can always add the indirection; edges are the only genuinely hard-to-test code | ch-14 |
| Green pipeline followed by more manual tests/sign-offs before release | Fix the pipeline scope (it must equal one independently deployable unit) until green = deployable | If pipeline pass doesn't mean "no more work," the evaluation is scoped wrong | ch-14 |
| Commit-to-deployable time >1 h (or commit stage >5 min) | Treat as an engineering defect; optimize feedback path before adding features | Speed is the fitness function that forces small teams, testing, architecture; 9.5 h build → 3 green builds in 3 years | ch-14 |
| Test spawns threads within its scope | Redesign: move concurrency to controlled edges; keep the tested unit single-threaded | Concurrency is the root cause of non-determinism; deterministic modules are testable modules | ch-14 |
| Adopting third-party tech | Qualify first: deployable? testable? variables controllable? fast enough for CD? preserves modularity? Any "no" disqualifies unless indispensable (then price the workaround) | Non-conforming tech taxes every future change | ch-14 |
| Org design fixed before business/architecture/process (OBAP) | Invert to BAPO: org structure is a tool chosen last | Structure eats strategy; org chart becomes the architecture (Conway) | ch-15 |
| Scaling plan = add people to the team/codebase | Scale by decoupling: more small (≤8) autonomous teams over bigger teams | Teams of ≤5 ≈ 4× productivity/person vs 20+, with 5× fewer defects | ch-6, ch-9 |

## Anti-patterns

- **Recipe code** — hundreds-of-lines linear step-list methods; modularity not attempted. *Cue*: method length/parameter counts far past guiderails; no inside/outside boundary. (ch-9)
- **Naive cohesion** — "it's all in one place" load-process-store methods/classes. *Cue*: one unit reads, transforms, and persists; test needs real files/DB. (ch-10)
- **Boundary = interior** — service/module boundaries crossed with raw internal data structures, no validation or translation. *Cue*: payload types from another context used directly in domain logic; HTML/JSON passed through untranslated. (ch-9, ch-11)
- **Test-after "TDD"** — unit tests written after code, coupled to implementation; later cited as "TDD doesn't work / tests block refactoring." *Cue*: tests mirror private structure; assertions on internals; encapsulation broken for access. (ch-14)
- **Coverage theater** — coverage targets/incentives without behavior focus. *Cue*: assertion-free tests; coverage bonuses; stability metrics absent. (ch-8)
- **Hero-programmer strategy** — safe change relies on the one person who understands everything. *Cue*: named individual required for risky merges; bus factor 1; no tests where they work. (ch-12)
- **Future-proofing / speculative generality** — code for imagined needs "so we don't have to change it later." *Cue*: unused flexibility, config nobody sets, interfaces with one implementation *and no test-driven reason*. (ch-12)
- **The middle-ground deployment fudge** — components built separately but only trusted when tested together. *Cue*: cross-pipeline integration-test stage before release; release trains synchronizing "independent" services; version-compatibility matrices. (ch-9, ch-13, ch-14)
- **Distributed monolith** — "microservices" with shared libraries, coordinated releases, joint testing. *Cue*: DRY applied across service boundaries; lock-step upgrades. (ch-13)
- **Abstraction inversion via error channels** — business failures reported as transport/technical errors. *Cue*: HTTP status codes carrying domain semantics; NPEs as domain outcomes. (ch-12)
- **Over-abstraction** — generality with no consumer: name-value-pair "store anything" schemas, frameworks-on-frameworks. *Cue*: loading one business entity = hundreds of round trips; nobody can state what the abstraction forbids. (ch-13)
- **CAB / external approval as quality gate** — the data says it slows everything and improves nothing. *Cue*: change tickets awaiting human boards; approval steps outside the pipeline. (ch-3)
- **Vapor-ware platform mandate** — an internal architecture/platform every project must use and no project actually uses. *Cue*: mandated dependency with zero working consumers; multi-year platform effort with no shipped increment. (ch-12)
- **Diagram-driven / low-code as general-purpose dev** — demos well (graphical DSL on a narrow problem), dies on round-trip and on losing version control/testing/debugging. *Cue*: generated skeletons hand-edited then never regenerable; logic trapped in a vendor canvas. (ch-12)
- **Manual/soak testing as leak detection** — waiting for failure to become obvious instead of instrumenting. *Cue*: multi-week soak tests; "run it and see"; no resource-trend measurement in regular tests. (ch-2)

## Applicability & exemptions

- **Guiderail numbers are team-tunable, not laws.** 20–30 lines / 5–6 params (and Farley's personal 10/4) are enforcement points chosen per team; the rule is "have mechanically enforced guiderails," not those constants. Don't flag a 35-line method in a codebase whose agreed rail is 50. (ch-9) ↔ philosophy-of-software-design: depth of module beats smallness — don't shred cohesive logic to satisfy a line count.
- **Test-first claims apply to new code.** For existing untested legacy, test-after characterization tests are the correct entry (working-effectively-with-legacy-code); Farley's "test-after is the anti-pattern" targets teams choosing it for greenfield work. (ch-14)
- **DRY still binds within one deployable unit.** The "don't share code" rule fires only *across* independently deployed services; inside one pipeline, duplication is still the smell Fowler says it is. (ch-13)
- **Microservices only if org scaling is the problem.** Services/bounded contexts are broadly useful; *independent deployability's* cost (protocol discipline, versioning, design sophistication) is justified by team decoupling, not by fashion. Small single-team products: prefer the well-factored monolith + fast pipeline. (ch-13)
- **≤1 h releasability is a direction, not a universal constant.** Physical products (cars, rockets, telecom hardware) can't hit it; the binding principles are "always releasable," "reject on first failing test," "maximize simulation." Judge by trend toward the target under real physical/economic constraints. (ch-14, ch-15)
- **Async-everywhere applies at process boundaries**, not inside a module — within a deterministic module, plain synchronous calls are exactly right; the exchange's speed came from single-threaded business logic. (ch-7, ch-13)
- **DORA metrics are correlative and delivery-scoped.** They measure "building it right," not "building the right thing"; good stability/throughput with commercial failure indicts product strategy, not the team's process — don't wield the metrics beyond their scope, and don't use them to rank individuals. (ch-3, ch-15)
- **Third-party isolation exempts language + standard library.** No facades for `String`/`List`; the rule targets libraries/frameworks with their own programming model and release cadence. (ch-12)
- **`Object`-level genericity is legitimate** in rare accidental-complexity plumbing (serializers, transports) — the prefer-general rule holds only within self-documenting bounds. (ch-12)
- **Some end-to-end tests are fine** as a thin supplement (deployment/config smoke, whole-system black-box with faked externals); the anti-pattern is E2E as the primary evaluation strategy. (ch-9)

## Candidate lexicon rows

| a change is planned as one batch with no releasable intermediate state | **Slice to releasable steps** — small steps cap the assumption horizon and the cost of any misstep; flat cost-of-change requires them | Can each step ship (or roll back in minutes) on its own? | should | plan | src: modern-software-engineering ch-4 |
| new test about to be run for the first time | **Predict the failure first** — a test never observed failing (with the predicted message) is an unverified instrument | What exact failure message do you expect before you run it? | should | write | src: modern-software-engineering ch-8 |
| a test is hard to write, needs threads, or needs a real DB/file/network | **Hard test = design defect** — test difficulty is the earliest objective signal of coupling/SoC problems; fix the design, not the test | What coupling makes this hard — and can a seam remove it? | should | write | src: modern-software-engineering ch-14 |
| a behavior's effect can't be asserted without exposing privates | **Add a measurement point** — inject the dependency and assert via a fake; never break encapsulation for tests | Where can a fake observe this effect through the public contract? | should | write | src: modern-software-engineering ch-14 |
| test suite gives different results for the same code version | **Determinism is non-negotiable** — non-deterministic evaluation certifies nothing; isolate the test or design the concurrency out to the edges | Same version, N runs: identical results every time? | blocker | review | src: modern-software-engineering ch-9 |
| plan's primary verification is end-to-end tests across multiple services | **E2E is a supplement, not a strategy** — composite tests can't express failure-injection cases and their failures are unattributable | Which module interface could measure this precisely instead? | should | plan | src: modern-software-engineering ch-9 |
| green pipeline is followed by manual sign-offs or joint integration testing before release | **Pipeline scope = deployable unit** — if green doesn't mean "no more work," the evaluation scope is wrong: widen it or decouple | Would you deploy on green alone — and if not, what's missing from the pipeline? | should | plan | src: modern-software-engineering ch-14 |
| test coverage appears as a target or incentive | **Measure stability, not coverage** — coverage is gameable (bonused targets produced >25% assertion-free tests); change-failure rate measures what you actually want | Does every test assert the behavior its name claims? | should | review | src: modern-software-engineering ch-8 |
| a shared library forces two independently deployed services to upgrade together | **DRY stops at the pipeline boundary** — cross-service code sharing is developmental coupling that defeats independent deployability; duplicate instead | Could service A release today if B's library bumped yesterday? | should | review | src: modern-software-engineering ch-13 |
| domain code calls a vendor SDK / third-party API directly | **Port at the seam** — access third-party code through your own minimal adapter; a vendor API change then touches one file, and tests run without the vendor | What's the minimal subset of this API the domain actually needs? | should | write | src: modern-software-engineering ch-12 |
| debugging session where a fix is proposed before the facts are listed | **Facts before hypothesis** — list everything known and check the story fits all of it; plausible guess-chains burn hours on the wrong problem | Which known fact does this hypothesis fail to explain? | should | review | src: modern-software-engineering ch-7 |
| design justifies parallelism for work whose results must be joined | **Benchmark the single thread first** — locks cost 33×, contended locks 746×, CAS ~19×; Amdahl caps joined work | Have you measured the single-threaded baseline on this problem? | judgment | plan | src: modern-software-engineering ch-7 |
