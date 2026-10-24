# The Pragmatic Programmer — distilled

> **Source**: Hunt, Andrew, and David Thomas. *The Pragmatic Programmer: Your Journey to Mastery*. 2nd ed. (20th anniversary edition), Addison-Wesley, 2019. · extracted from `literature/extracted/engineering/pragmatic-programmer.txt` · distilled 2026-07-22 (spec v2)
> **Contributes**: The upstream popular source for a cluster of *named* craft practices that successors specialized but did not invent: **tracer bullets** (kept, production-path thin end-to-end vs throwaway prototypes), **broken windows** as a *rate* of quality decay under neglect, **DRY as duplicated knowledge/intent** (not copy-paste text), **ETC** ("easier to change") as the single design criterion, **programming by coincidence**, deliberate **resource balancing** ("finish what you start"), and the workflow trio of the **pragmatic starter kit** (version control, testing, automation — "don't use manual procedures"). Most of the book has already reached the canon through Fowler, Ousterhout, Feathers, Agans, Nygard, Evans, and the Unix tradition; the genuine remainder is a short set of named distinctions plus a long cross-link map. User intent for this source: general programming and workflows.

## Chapter map
- ch-1 — A Pragmatic Philosophy: agency, broken windows / software entropy, stone soup, good-enough software, knowledge portfolio, communication
- ch-2 — A Pragmatic Approach: ETC, DRY-as-knowledge, orthogonality, reversibility, tracer bullets vs prototypes, domain languages, estimating
- ch-3 — The Basic Tools: plain text, shell, editor fluency, version control, debugging discipline, text manipulation, engineering daybooks
- ch-4 — Pragmatic Paranoia: design by contract, crash early, assertive programming, resource balancing, headlights / small steps
- ch-5 — Bend, or Break: decoupling (tell-don't-ask, train wrecks), events, transforming programming, inheritance tax, external configuration
- ch-6 — Concurrency: temporal coupling, shared state, actors, blackboards
- ch-7 — While You Are Coding: lizard brain, programming by coincidence, algorithm speed, refactoring, test-to-code, property-based tests, security
- ch-8 — Before the Project: requirements pit, impossible puzzles, working together, essence of agility
- ch-9 — Pragmatic Projects: teams, coconuts vs cargo-cult process, pragmatic starter kit, delight users, sign your work
- ch-10 — Postface: power and responsibility of software that runs the world (ethical close, not lexicon material)

## ch-1 — A Pragmatic Philosophy {#ch-1}

- **It's your life / you have agency** (Tips 1–3): craft care and deliberate thought are non-optional; if the environment is broken, fix or leave — do not outsource responsibility for quality of work.
- **Provide options, don't make lame excuses** (Tip 4): when reporting blockage, bring alternatives and trade-offs, not a dead end. Observable: status update that only narrates failure without a next option set.
- **Software entropy / broken windows** (Topic 3, Tip 5): entropy (disorder) rises unless fought. The urban **broken window** claim is the mechanism: one unrepaired defect (bad design, wrong decision, poor code) signals neglect; neglect is contagious; rot *accelerates*. The claim is about *rate of decay under visible neglect*, not a static quality bar.
  - Action: fix each broken window as soon as discovered; if you cannot fix properly, *board it up* (comment out, "Not Implemented", dummy data) so the signal is "we are on top of this," not abandonment.
  - Collateral: under crisis, still "first, do no harm" — do not smash more windows to hit a deadline. One broken window is enough to start the spiral.
  - Distinct from "technical debt we'll repay someday" optimism; authors note repayment often never comes.
- **Stone soup and boiled frogs** (Topic 4, Tips 6–7):
  - **Stone soup**: catalyze change by shipping a small working core and inviting others to add the next ingredient; people join ongoing success more readily than greenfield permission-seeking.
  - **Boiled frogs**: gradual bad change is invisible if you never look up; remember the big picture so entropy and scope creep do not cook you.
- **Good-enough software** (Topic 5, Tip 8): make quality a *requirements* issue with the user — trade-offs are explicit, not secret perfectionism. Know when to stop overembellishing.
- **Knowledge portfolio** (Topic 6, Tips 9–10): skills expire; invest regularly, diversify, critically analyze what you read. Not lexicon-grade for agent coding rules; career hygiene.
- **Communicate** (Topic 7, Tips 11–13): treat English as another programming language; documentation built in, not bolted on. Cross-links writing/NAME families more than engineering rows.

## ch-2 — A Pragmatic Approach {#ch-2}

### Topic 8 — Essence of good design: **ETC**
- Tip 14: **Good Design Is Easier to Change Than Bad Design.** A thing is well designed if it adapts to the people who use it; the pragmatic test is **Easier To Change (ETC)**. Prefer the option that lowers future change cost when you cannot yet know which change will come.
- Observable: design debate with no change-axis comparison — force the question "which option is easier to change when X moves?"

### Topic 9 — **DRY — Don't Repeat Yourself** (knowledge, not text)
- Tip 15: authors correct the 1st-edition misreading head-on: people took DRY as "don't copy-paste source." That is "a tiny and fairly trivial part."
- **DRY is about the duplication of knowledge, of intent** — expressing the same thing in two places, possibly in two totally different ways (code + docs, schema + struct, UI + validation rules, …).
- **Acid test**: when one facet must change, do you edit multiple places *and* multiple formats? If yes, not DRY.
- Catalog of duplication kinds (compressed):
  | Kind | Cue | Remedy direction |
  |---|---|---|
  | Imposed | Environment forces two representations (e.g. vendor schema + internal model) | Single transform/gateway; generate one from the other when possible |
  | Inadvertent | Developer didn't notice the knowledge already lived elsewhere | Find the owner of the fact; call it |
  | Interdeveloper | Two people reimplemented the same knowledge | Shared module, review for ownership |
  | Representational | Same concept in code, docs, tests, configs with no single source | Generate docs/config from code or vice versa; one authority |
- Tip 16 **Make it easy to reuse**: reuse fails when reuse is harder than reimplementation; environment and APIs must lower reuse friction (complements DRY).
- **Partition vs canon `REF-10`**: `REF-10` (Fowler) is the *anti-false-DRY* gate — do not merge coincidental similar *code text* that will not change together. Hunt & Thomas supply the *pro-true-DRY* gate — do not leave the *same intent* in two formats that *must* change together. Both can fire on one diff: extract real knowledge duplication; leave coincidental structure alone.

### Topic 10 — **Orthogonality**
- Tip 17: **Eliminate effects between unrelated things.** Components self-contained, single purpose (cohesion); change one without ripple.
- Productivity claim: orthogonal A doing *m* things × orthogonal B doing *n* things → ~*m×n* combinations; non-orthogonal overlap wastes combinations.
- Risk claim: disease isolated; vendor swaps localized; testing cheaper.
- Design test: "If I dramatically change the requirements behind a particular function, how many modules are affected?" Orthogonal answer: **one**.
- **Shy code**: modules that don't reveal unnecessary internals and don't rely on others' implementations (points forward to Demeter / tell-don't-ask in ch-5).
- Avoid global data; pass context explicitly. Toolkits that force special object-construction patterns break orthogonality.
- Largely already held by `REF-13`/`REF-14`/`REF-17`/`REF-18`/`ARCH-*` coupling material — treat as convergence, not a new row, unless a reviewer wants the named "one module affected" test as a cue.

### Topic 11 — **Reversibility**
- Tip 18: **There Are No Final Decisions.** Architecture that assumes a final vendor, DB, UI, or deployment model becomes a single point of failure when the world moves.
- Tip 19: **Forgo Following Fads** — enable change; do not bet the farm on this year's framework.
- Flexible architecture: isolate third-party choices behind interfaces; decisions should be *reversible* at acceptable cost.
- **Tension with `ARCH-08` (choose boring technology)**: reversibility is not "always pick the novel flexible option." Boring tech can be the reversible choice (well-understood exit paths); fad tech often *reduces* reversibility. Name the tension: prefer decisions that stay undoable *and* default to boring unless a measured need forces novelty.

### Topic 12 — **Tracer bullets** vs Topic 13 — **Prototypes**
- Tip 20: **Use Tracer Bullets to Find the Target.**
  - Metaphor: luminous rounds show the aim path in the dark so you adjust fire; not a searchlight survey first.
  - Tracer *code*: thin but **real** end-to-end path through every architectural layer for one simple feature; production structure (error handling, docs, checks); incomplete functionality; **kept** and fleshed over time.
  - First tracer often: project skeleton + "hello world" that compiles and runs, then the thinnest diagonal that exercises uncertain integrations.
  - Benefits named: early user-visible progress, structure for the team, continuous integration platform, always-demoable system, honest progress (done use-case by use-case, not "95% complete" monoliths).
  - Misses are expected; low code mass means low inertia to re-aim.
- Tip 21: **Prototype to Learn.**
  - Prototypes answer a few risky questions (architecture, UI, algorithm, third-party, performance); value is **lessons**, not the code.
  - Disposable by contract: may ignore correctness, completeness, robustness, style. Make that expectation loud to sponsors — balsa-wood car is not for rush hour.
  - If culture will ship the prototype anyway, prefer tracer bullets.
- **The distinction the canon needs** (authors' own words, compressed): *Prototyping generates disposable code. Tracer code is lean but complete, and forms part of the skeleton of the final system. Think of prototyping as the reconnaissance before a single tracer bullet is fired.*
- Observable misfires:
  - Plan says "prototype" but describes production-path plumbing kept forever → it is a tracer; treat and staff it as production.
  - Plan says "tracer" / "spike we keep" but omits error handling, tests, and real interfaces → it is a prototype; schedule a rewrite, do not build on it.

### Topic 14 — Domain languages
- Tip 22: **Program close to the problem domain.** Prefer vocabulary of the domain; sometimes embed domain syntax. Cross-link `DOM-*` / `NAME-*` / project glossary (ch-8 Tip 80) rather than new engineering vocabulary.

### Topic 15 — Estimating
- Tip 23: **Estimate to avoid surprises**; Tip 24: **Iterate the schedule with the code.**
- Technique sketch: understand scope → build a model of parameters → value critical parameters → calculate ranges → record accuracy for calibration.
- **Do not nominate engineering estimation rows.** The canon's `FORE` family in `lexicons/epistemics.md` owns forecast/estimate discipline. Cross-link only: schedule iteration with working software is the engineering-facing consequence of tracer development (ch-2 Topic 12), not a competing FORE vocabulary.

## ch-3 — The Basic Tools {#ch-3}

- Tip 25: **Keep knowledge in plain text** — human-readable, durable, toolable; binary formats tax every future reader. Already largely `AGT-18` (textual until measured) + art-of-unix textuality.
- Tip 26: **Use the power of command shells** — shell as combinatorial workbench beats one-off GUI clicks for repeatable work. Convergence with Unix-tradition distillations.
- Tip 27: **Achieve editor fluency** — editor as extension of hands; productivity is not "seconds saved" alone but flow and reduced friction. Soft for agent lexicon (agents are not IDE users the same way); note only.
- Tip 28: **Always use version control** — even solo week projects; VCS as time machine, collaboration bus, and (later) build driver (ch-9 Tip 89).
- Topic 20 **Debugging** (Tips 29–34): fix the problem not the blame; don't panic; failing test before fix; **read the damn error message**; "select isn't broken" (suspect your code first); **don't assume it — prove it**. Almost entirely held by `DBG-*` (Agans) and `DIAG-*`. Rubber ducking named here as explain-aloud technique.
- Tip 35: learn a text-manipulation language (awk/sed/Python one-liners as glue).
- Topic 22 **Engineering daybooks**: written working memory across sessions — converges with `AGT-07` externalize at discovery.

## ch-4 — Pragmatic Paranoia {#ch-4}

- Tip 36: **You can't write perfect software** — axiom; design for the imperfect world (defensive posture without fantasy of total correctness).
- Topic 23 **Design by Contract** (Tip 37): preconditions, postconditions, invariants; "shy code" meets explicit obligations. Semantic invariants ("err in favor of the consumer") are inviolate laws, not whimsical policy. Already deep in `why-programs-fail` distillation; cross-link, do not re-own.
- Topic 24 **Dead programs tell no lies** (Tip 38: **Crash Early**): when the impossible has happened, the program is no longer viable — terminate rather than write corrupted state. "A dead program normally does a lot less damage than a crippled one." Catch-and-relog-all-exceptions patterns couple callers to callee exception lists; prefer propagation. Erlang "let it crash" + supervisors cited. Overlaps `RLSE-05` (silent failure worst), `AGT-10`, `OBS-08` — the *named* crash-early tip is still a useful cue pointing at those IDs.
- Topic 25 **Assertive programming** (Tip 39): whenever you think "that can never happen," assert it. Leave assertions on in production when the cost is right; never use assertions for *external* input validation (that is error handling, not assert). Cross-link `why-programs-fail` ch on contracts/assertions.
- Topic 26 **How to balance resources** (Tip 40: **Finish What You Start**): the unit that allocates a resource is responsible for releasing it; open/close (or acquire/release) should be visible in one place. Nested lifetimes, `with`/RAII/block scope as mechanical guarantee. Partial overlap with `RES-04` (pool exhaustion / finally) but the *symmetry* rule is the distinctive cue: split open-in-A / close-in-B across shared mutable handle is the anti-pattern.
- Topic 27 **Don't outrun your headlights** (Tips 42–43):
  - **Take small steps — always.** Feedback rate is the speed limit (REPL, unit tests, user demos).
  - Task too big = requires **fortune-telling** (estimates months out, designs for unknown future needs, guessing future tech).
  - Prefer **replaceable** code over speculative future-proofing; black swans make long predictions fragile (Motif vs OpenLook vs the web).
  - Tip 43: **Avoid Fortune-Telling.** Tomorrow often looks like today — don't count on it.
  - Convergence/tension: `REF-12` YAGNI gates speculative generality; headlights add the *feedback-rate* bound and the replaceability alternative.

## ch-5 — Bend, or Break {#ch-5}

- Tip 44: **Decoupled code is easier to change** — symptoms: wacky cross-module deps, "simple" changes that ripple, fear of editing, all-hands meetings for unknown blast radius.
- **Train wrecks**: `a.b().c().d().e()` chains encode multi-level knowledge into callers.
- Tip 45: **Tell, Don't Ask** — do not fetch internal state, decide, and write back; tell the object to do the operation (preserves encapsulation). Pragmatic exception: universal top-level concepts (Customer, Order) may be exposed; TDA is a pattern, not a law.
- Tip 46: **Don't chain method calls** — prefer ≤ one `.` of traversal beyond the immediate collaborator (softened Law of Demeter).
- Tips 47–48: avoid global data (including singleton-as-global); if it must be global, wrap in an API.
- Topic 29–30: event strategies; **transforming programming** (Tip 49–50) — programs are about data transformations; don't hoard state, pass it along pipelines.
- Topic 31 **Inheritance tax** (Tips 51–54): prefer interfaces/protocols for polymorphism, **has-a** (delegation) over **is-a**, mixins for shared behavior; inheritance rarely the answer.
- Topic 32 **Configuration** (Tip 55): parameterize via external configuration — values that change across deploys/customers live outside code. Convergence with `AGT-19`/`AGT-20` and art-of-unix configuration chapter.

## ch-6 — Concurrency {#ch-6}

- Definitions: concurrency = appear simultaneous; parallelism = are simultaneous.
- Tip 56: analyze workflow (activity diagrams) to find concurrent opportunities and temporal coupling.
- Tip 57: **Shared state is incorrect state** — pie-case/diner example: check-then-act on shared counts is the bug; mutual exclusion or, better, no shared mutable state.
- Tip 58: random failures are often concurrency issues.
- Tips 59–60: actors/processes and blackboards as coordination without shared mutable state.
- Largely held by `CON-*` family; cross-link Tip 57 → `CON-05`/`CON-11` (lost update / check-then-act), Tip 58 → `CON-17` / `DBG-13`.

## ch-7 — While You Are Coding {#ch-7}

- Topic 37: listen to lizard-brain discomfort — stop, create space, dig; often a design smell speaking early.
- Topic 38 **Programming by coincidence** (Tip 62: **Don't Program by Coincidence**):
  - Code that "works" for reasons you cannot state is coincidence, not knowledge.
  - Accidental context (default configs, evaluation order, race-free on 4-core laptop, US-only phone formats, 16 cups/gallon US measure) becomes production failure.
  - Deliberate programming checklist (compressed): know what you're doing; explain it to a junior; don't code in the dark on ungrasped tech; proceed from a plan; rely only on reliable things; document assumptions (DBC helps); test assumptions with assertions; prioritize hard fundamentals; don't be a slave to history — refactor when past code constrains badly.
- Topic 39 **Algorithm speed** (Tips 63–64): Big-O estimates; test estimates with profilers. Cross-link `PERF-05`/`PERF-06`/`ALG-*`.
- Topic 40 **Refactoring** (Tip 65: **Refactor early, refactor often**): don't live with broken windows; refactoring is ongoing, not a scheduled week-long rewrite. Cross-link `REF-05` two hats, `TEST-01`, Fowler distillation.
- Topic 41 **Test to code** (Tips 66–70):
  - Tip 66: testing is not primarily about finding bugs — major benefit is *thinking* and design feedback.
  - Tip 67: **A test is the first user of your code** — hard-to-test ⇒ overcoupled.
  - TDD cycle acknowledged; warning against TDD slavery (coverage theater, redundant tests, bottom-up wandering — Sudoku blog cautionary tale).
  - Tip 68: **Build end-to-end, not top-down or bottom-up** — same spine as tracer bullets.
  - Tip 69–70: design to test; test or your users will.
  - Cross-link `TEST-*`, especially `TEST-09` hard test = design defect, `TEST-06`/`TEST-15` watch it fail.
- Topic 42 property-based testing (Tip 71): validate assumptions with generated cases — cross-link testing distillations.
- Topic 43 security (Tips 72–73): minimize attack surface, least privilege, apply patches quickly — belongs to security lexicon more than engineering craft rows.
- Topic 44 naming (Tip 74): name well; rename when needed — `NAME-*` / ETC violation when a wrong name cannot be fixed.

## ch-8 — Before the Project {#ch-8}

### Topic 45 — The requirements pit
- Tip 75: **No one knows exactly what they want.** "Gathering" is a myth — requirements are rarely lying on the ground.
- Tip 76: **Programmers help people understand what they want** — the initial need statement is an invitation to explore, not a ship-it order.
- Tip 77: **Requirements are learned in a feedback loop** — feed consequences back; mockups and short iterations; the whole project is requirements learning.
- Tip 78: **Work with a user to think like a user** — sit in the warehouse / on the help desk.
- **Requirements vs policy**: "only supervisors may view records" may be *policy* (will change) not a semantic invariant; implement general case with policy as data (Tip 79: **Policy is metadata**).
- Overspecification danger: good requirements are abstract need, not architecture/UI. Prefer index-card-scale user stories that force clarifying questions.
- Tip 80: **Use a project glossary** — one meaning per term; all roles share it. Strong convergence with `DOM-03` / `NAME-02`.

### Topics 46–48
- Tip 81: **Don't think outside the box — find the box** — enumerate real constraints; the box is often smaller or differently shaped than assumed.
- Tip 82: don't go into the code alone (pair / ensemble as default for hard problems).
- Tip 83: **Agile is not a noun; agile is how you do things** — process cargo-cult fails; thinking does not.

## ch-9 — Pragmatic Projects {#ch-9}

- Topic 49 teams (Tips 84–86): small stable teams; schedule communication; organize fully functional teams that can build end-to-end (Conway-relevant; cross-link `TEAM-*`).
- Topic 50 **Coconuts don't cut it** (Tip 87): do what works, not what's fashionable; cargo-cult the surface of a method and you get the coconut radio, not the airport.
- Topic 51 **Pragmatic starter kit** — the magic trio:
  - Version control driving builds/tests/releases (Tip 89)
  - Ruthless automated testing (Tips 90–94): test early/often/automatically; coding ain't done 'til tests run; saboteurs to test the tests; state coverage not just line coverage; find bugs once (then automate the regression)
  - Tip 95: **Don't use manual procedures** — "People just aren't as repeatable as computers are." Shell script or program for anything you would otherwise click through twice. This is the workflow rule the user intent points at; partial overlap with `AGT-14` (never prompt in automation path) but broader: any manual runbook step that can be scripted should be.
- Topic 52: delight users, don't just deliver code (Tip 96).
- Topic 53: sign your work / pride (Tip 97) — craft accountability.

## ch-10 — Postface {#ch-10}

- Ethical close: software runs life-critical and society-scale systems; power implies responsibility (Tips 98–100). No candidate engineering rows; out of scope for the lexicon's condition→action grammar.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Known bad design / wrong decision / poor code left visible with no fix or board-up | **Don't live with broken windows** — repair or explicitly board up immediately | Neglect signals abandonment; rot accelerates as a social/technical feedback loop | ch-1 |
| Plan labeled "prototype" but kept as production skeleton, or "tracer" that is throwaway | **Name tracer vs prototype correctly** — tracer is thin *kept* end-to-end production path; prototype is disposable learning | Wrong name → wrong quality bar, wrong staffing, wrong expectation with sponsors | ch-2 |
| Same intent expressed in code + docs + schema + config with multi-place edits on one change | **DRY is knowledge** — one authority for each fact of intent | Contradictions appear when one face changes and another is forgotten | ch-2 |
| Two similar code blocks that will not change together | **Do not false-DRY** — leave coincidental similarity alone | Merging accidental similarity raises coupling (`REF-10`) | ch-2 / REF-10 |
| Design options compared without a change axis | **ETC** — prefer the design easier to change | Future change direction is unknown; option value is reversibility of structure | ch-2 |
| "Final" vendor/DB/UI decision baked through the codebase | **No final decisions** — isolate so the decision is reversible | Environment will move; irreversible decisions become project single points of failure | ch-2 |
| Dramatic requirement change for one function touches N unrelated modules | **Orthogonality test failed** — retarget so answer is one module | Unrelated effects multiply cost and risk | ch-2 |
| New project / uncertain integration without an end-to-end thin path | **Fire a tracer bullet first** — hello-world through all layers, then one thin feature diagonal | Big-bang integration hides aim error until inertia is high | ch-2 |
| Estimate or schedule treated as fixed while code is still teaching the problem | **Iterate schedule with the code** (cross-link `FORE-*`, do not mint ENG estimate IDs) | Early estimates are models; working software updates the model | ch-2 |
| Knowledge stored only in proprietary binary or GUI state | **Plain text for knowledge** | Text survives tools and composes with the shell (`AGT-18`) | ch-3 |
| Bug investigation without repro, without reading the error, or with blame focus | **Debug deliberately** — prove, don't assume; fix problem not blame | Held by `DBG-*` / `DIAG-*` | ch-3 |
| Function continues after detecting impossible state | **Crash early** — dead programs lie less than crippled ones | Corrupted continuation writes bad data (`RLSE-05`) | ch-4 |
| "That can never happen" without a check | **Assert the impossible** | Unchecked assumptions become Heisenbugs in production | ch-4 |
| Resource opened in one routine and closed in another via shared handle | **Finish what you start** — allocator releases; prefer scoped lifetime | Split open/close is a leak under the first new conditional | ch-4 |
| Step requires months-out estimates, speculative extension points, or future-tech guesses | **Don't outrun headlights** — small steps bounded by feedback; prefer replaceable code | Fortune-telling is risk theater (`REF-12`) | ch-4 |
| Caller reads object fields, decides, writes fields back | **Tell, don't ask** | Decision logic belongs with the data; train wrecks spread knowledge | ch-5 |
| Method chain traverses >1–2 objects' internals | **Don't chain calls / shy code** | Each link is coupling and a future break | ch-5 |
| Shared mutable value with check-then-act under concurrency | **Shared state is incorrect state** | Classic lost update (`CON-05`/`CON-11`) | ch-6 |
| Code works in dev for unstated reasons (order, timing, locale, defaults) | **Don't program by coincidence** — state and test assumptions | Accidental context will not travel to prod | ch-7 |
| Hard-to-test module blamed on "needs more mocks" | **Test is the first user** — hard test ⇒ design defect | Coupling is the disease (`TEST-09`) | ch-7 |
| Top-down full design or bottom-up libraries with no vertical slice | **Build end-to-end** | Same spine as tracer bullets | ch-7 |
| Requirements treated as collectible nuggets frozen up front | **Requirements are learned** — feedback loop with client | Nobody knows exactly what they want at the start | ch-8 |
| Business policy hard-coded as if semantic invariant | **Policy is metadata** | Policy changes with management; invariants don't | ch-8 |
| Project terms used inconsistently across code and conversation | **Project glossary** | One meaning per term (`DOM-03`/`NAME-02`) | ch-8 |
| Deploy/test/release step performed by human click-path twice | **Don't use manual procedures** — script it | Humans are not repeatable; automation is | ch-9 |
| VCS not driving build/test/release | **Starter kit** — VCS + automated test + automation | Trio is the minimum reliability stack | ch-9 |

## Anti-patterns

| Name (book or compressed) | Detection cue | Counter |
|---|---|---|
| **Broken windows left open** | Known smell remains with no ticket, board-up, or fix | Fix or board up now; never "later when we have time" as the only plan |
| **Boiled frog** | Gradual quality/scope slide with no big-picture check | Explicit big-picture review; absolute bars (`OBS-11` kinship) |
| **False DRY** (copy-paste paranoia) | Extract method that merges code that will diverge | `REF-10` coincidental vs real |
| **Knowledge scatter** (true DRY violation) | One business fact edited in code+doc+schema separately | Single authority + generation |
| **Prototype shipped as product** | Disposable spike becomes production without rewrite | Either tracer from the start, or scheduled replacement |
| **Big-bang integration** | Modules coded in vacuum until final assembly | Tracer diagonal early |
| **Final decision architecture** | Ubiquitous hard dependency on one vendor/DB with no seam | Interface + reversible choice |
| **Fortune-telling design** | Speculative frameworks "for when we need X" with zero X today | Headlights + `REF-12` YAGNI |
| **Programming by coincidence** | "It works" + cannot explain why; depends on accidental environment | Prove assumptions; assert; deliberate checklist |
| **Catch and re-log everything** | Try/rescue every exception type, log, re-raise | Propagate; handle at boundaries |
| **Crippled continuation** | On invariant failure, log and keep writing | Crash early / fail visible |
| **Split resource lifetime** | open in A, close in B, shared field | Finish what you start; scoped blocks |
| **Train wreck / ask-then-set** | `a.getB().getC().setX(...)` from afar | Tell, don't ask |
| **Global/singleton soup** | Hidden coupling via ambient state | Pass context; API-wrap true globals |
| **Inheritance for reuse** | Deep is-a trees for code sharing | Interfaces, delegation, mixins |
| **Requirements gathering theater** | Huge frozen spec, no feedback loop | Stories + iteration + consequence feedback |
| **Policy as code invariant** | Hard-coded org rules without config | Policy as metadata |
| **Coconut / cargo-cult agile** | Ceremonies and tools without feedback empiricism | "Do what works"; agile as adjective |
| **Manual runbook** | Wiki click-path for build/deploy/migrate | Script; VCS-driven pipeline |
| **TDD theater** | Redundant tests, coverage chasing, lost product goal | Tests serve destination; end-to-end aim |

## Applicability & exemptions

- **Not a systems/architecture encyclopedia.** Prefer Nygard (`release-it`), DDIA, Hard Parts, Just Enough for runtime topology, data systems, and trade-off records. This book is craft posture and workflow.
- **Estimation**: do not promote PragProg estimating tips as engineering lexicon rows; use `FORE-*` for forecast discipline. Keep only the link that schedules iterate with working software.
- **DbC / assertions / crash-early**: rich coverage already in `why-programs-fail` and `RLSE-05`/`DBG-*`. New rows only if a reviewer wants the *Hunt & Thomas name* as an alternate cue — not a second mechanism.
- **Orthogonality / decoupling / deep modules**: Ousterhout, Fowler, modern-software-engineering, and `REF-*`/`ARCH-*` already own the mechanism. Use this book as historical upstream + the "one module affected" test phrasing.
- **Concurrency**: `CON-*` is authoritative; diner/pie examples are teaching props, not new rules.
- **Security chapter**: defer to security lexicon; Tips 72–73 are reminders, not a security program.
- **Career/soft topics** (knowledge portfolio, pride, delight, ethics postface): valuable human advice; weak agent-fireable triggers; keep out of candidate shortlist unless an AGT-style session rule is desired.
- **Good-enough software**: does *not* license silent quality abandonment — it requires making the quality bar an explicit requirements negotiation. Still "no broken windows" inside the agreed bar.
- **Tracer bullets** assume you can ship thin vertical slices; hard real-time or safety-certified contexts may require more up-front analysis — still prototype risks, but keep/dispose discipline remains.
- **Assert in production**: authors favor keeping checks; environments with hard latency budgets may sample or strip some asserts — never strip *validation* of external input.

## Candidate lexicon rows

Shortlist only — mechanisms not already owned, or owned only partially with a clear partition. Grammar per engineering DISTILLATION_SPEC.

| plan or spike labeled "prototype" that is kept, wired into production paths, and extended; or "tracer"/"vertical slice we keep" that omits production error handling and is intended to be thrown away | **Tracer vs prototype**: tracer code is lean, end-to-end, production-structured and *kept*; a prototype is disposable learning — mislabeling applies the wrong quality bar and freezes the wrong code | Is this spike disposable reconnaissance, or a kept skeletal path through real layers? | should | plan | src: pragmatic-programmer ch-2 |
| known bad design, wrong decision, or poor code remains visible in the tree with neither a fix nor an explicit board-up (Not Implemented, dummy, quarantined) | **No broken windows**: one unrepaired defect signals neglect and *accelerates* further rot; fix immediately or board up to show the situation is owned | What is the repair or board-up for this known defect, and is neglect visible to the next editor? | should | review | src: pragmatic-programmer ch-1 |
| a single facet of intent must change in multiple places *and formats* (code + docs, schema + struct, UI rules + server validation, duplicated config keys) | **DRY is knowledge, not text**: duplication of *intent* across representations is the defect; the acid test is multi-format multi-place edit for one change (partition: do not merge coincidental code similarity — [[REF-10]]) | When this fact changes, how many places and formats must move together? | should | review | src: pragmatic-programmer ch-2 |
| change works in dev/CI but depends on unstated environment (timing, core count, locale, default config, evaluation order, US-only formats) or author cannot explain why it works | **Don't program by coincidence**: accidental context is not a dependency; state assumptions, prove them, assert the impossible, proceed from a plan | Can I explain why this works to a junior, and which assumptions are tested? | should | review | src: pragmatic-programmer ch-7 |
| build, deploy, migrate, or release step is a human click-path or wiki runbook executed more than once | **Don't use manual procedures**: people are not repeatable; script the procedure and preferably drive it from version control | Is this step automated, or will a human recreate it under stress? | should | plan | src: pragmatic-programmer ch-9 |
| resource (file, connection, lock, temp) opened in one function and closed in another via shared field/handle, especially with early-return paths between | **Finish what you start**: the unit that allocates releases; prefer block-scoped lifetime so every open has a visible matching close | Can I point to one scope that both acquires and releases this resource on every path? | should | write | src: pragmatic-programmer ch-4 |
| plan or design step requires forecasting months-out dates, speculative extension points for unknown futures, or bets on unavailable tech, without a near feedback check | **Don't outrun your headlights**: step size is bounded by feedback rate; prefer replaceable code over fortune-telling (complements [[REF-12]] YAGNI) | What independent feedback confirms this step before the next, and what would we throw away if wrong? | judgment | plan | src: pragmatic-programmer ch-4 |
| initial stakeholder statement treated as frozen implementation order without consequence-feedback, or "requirements gathering" phase expected to finish before learning | **Requirements are learned, not gathered**: nobody knows exactly what they want; programmers feed consequences back in a loop (stories, mockups, short iterations) | What feedback loop updates this requirement when consequences appear? | should | plan | src: pragmatic-programmer ch-8 |

**Not nominated (already held — see Cross-links):** orthogonality/decoupling deep treatment; DbC/assert/crash-early mechanisms; plain text/shell/VCS-as-tooling; debugging procedure; TDD/test design; shared-state concurrency; domain glossary as `DOM-03`/`NAME-02`; estimation (`FORE-*`); ETC as free-standing row (overlaps `REF-23` / Ousterhout changeability — optional future merge if a reviewer wants the three-letter cue).

## Cross-links

Long list is the correct outcome for this book.

| Book idea | Already in canon as | Notes |
|---|---|---|
| Coincidental vs real code duplication (don't merge what won't change together) | `REF-10` | Fowler side of DRY; complementary to knowledge-DRY row above |
| Speculative generality / YAGNI | `REF-12` | Headlights/fortune-telling strengthens the same gate |
| Two hats / refactor vs feature | `REF-05` | Topic 40 |
| Stay strategic / preparatory refactor | `REF-23` | Kin to ETC and broken-window repair |
| Deep modules, information hiding, pull complexity down | `REF-18`–`REF-22`, philosophy-of-software-design | Orthogonality/shy code converge |
| Coupling triage, independent deployability | `REF-13`, `REF-14` | Orthogonality test is a productivity phrasing of same |
| Ports & adapters / isolate vendors | `REF-15`, reversibility Topic 11 | |
| Legacy change, seams, characterization | `TEST-02`–`TEST-05`, Feathers distillation | Not PragProg's center |
| Hard test = design defect; test first-user | `TEST-09`, Tip 67 | |
| Prove green can go red; watch fail | `TEST-06`, `TEST-15` | Tips 31, 91–92 |
| E2E supplement not strategy | `TEST-10` | Still: build end-to-end *slices* (tracer), not E2E-only QA |
| Debug procedure | `DBG-01`–`DBG-13`, Agans | Tips 29–34 almost entirely covered |
| Facts before hypothesis; empiricism | `DIAG-01`–`DIAG-03`, modern-software-engineering | |
| Silent failure / degrade loudly | `RLSE-05`, `AGT-10`, `OBS-08` | Crash early points here |
| Absolute standards vs eroding goals | `OBS-11` | Kinship with broken windows / boiled frogs as *process* decay — different stock (code neglect vs sliding metric bar) |
| Textual until measured | `AGT-18`, art-of-unix ch-5 | Tip 25 |
| Never prompt in automation path | `AGT-14` | Narrower than "no manual procedures" |
| Config detectability & precedence | `AGT-19`, `AGT-20` | Tip 55 |
| Externalize working memory | `AGT-07` | Engineering daybooks |
| Resource pool / finally leaks | `RES-04` | Related to finish-what-you-start |
| Shared mutable / lost update / check-then-act | `CON-02`, `CON-05`, `CON-11` | Tips 57–58 |
| Nonreproducible under load = race | `CON-17`, `DBG-13` | Tip 58 |
| One meaning per term / glossary | `DOM-03`, `NAME-02` | Tip 80 |
| Domain classification before architecture | `DOM-01` | Domain languages Topic 14 |
| Choose boring technology | `ARCH-08` | Tension with reversibility/fads (see Tensions) |
| Why beats how / ADR | `ARCH-07` | Communication of decisions |
| Team cognitive load, stream-aligned, Conway | `TEAM-*` | Tips 84–86 |
| Measure before optimizing perf; Big-O | `PERF-05`, `PERF-06`, `ALG-*` | Tips 63–64 |
| Estimation / forecast discipline | `FORE-*` (epistemics) | Tips 23–24 — do not duplicate in engineering |
| Design by contract / assertions | why-programs-fail distillation; partial `RLSE-05` | Topics 23–25 |
| Fail fast / operations | release-it distillation | Crash early kinship |
| Unix shell, plain text, tool composition | art-of-unix-programming, unix-programming-environment | ch-3 tools |
| Incremental delivery / feedback empiricism | modern-software-engineering ch-4–8 | Tracer + requirements loop |

## Tensions

- **Reversibility (Tip 18) vs `ARCH-08` boring technology.** Flexible seams can be read as permission to adopt novel stacks "so we can switch later." Authors also say forgo fads (Tip 19). Resolution: maximize *undo cost quality*, not novelty — boring choices with clear exit seams beat fashionable choices with irreversible lock-in.
- **DRY knowledge vs `REF-10` anti-false-DRY.** Aggressive DRY on text produces the wrong abstraction; aggressive tolerance of knowledge scatter produces contradiction bugs. Partition on the acid tests: change-together-in-multiple-formats → unify knowledge; similar-looking-but-diverge-later → leave alone.
- **Good-enough software vs no broken windows.** Good-enough sets the *negotiated* quality bar with the user; broken windows forbid *neglect inside* that bar. Shipping without a feature is fine; shipping with an unrepaired known defect and no board-up is not.
- **TDD as driver vs tracer / end-to-end aim (Tips 66–68).** Authors endorse tests as first user and are cool to TDD theater that wanders bottom-up (Sudoku caution). Tension with pure test-first dogma: tests serve a destination; green bar is not the destination.
- **Tell-don't-ask vs pragmatic exposure of top-level domain objects.** Slavish TDA produces `customer.applyDiscountToOrder(id)` noise; authors stop when Customer/Order are universal concepts. Pattern, not law — same spirit as Demeter softening in 2nd ed.
- **Crash early vs high-availability continue-and-repair.** Erlang supervisors make crash-early *compatible* with availability; naïve process exit in an unsupervised monolith can violate uptime SLOs. Apply crash-early at the *component* boundary with a recovery story (`RES-13`, release-it), not as "abort the only process."

## First-principles candidates

Mechanisms that might deserve a name even if not promoted soon:

1. **Neglect acceleration (broken-window dynamics)** — quality as a stock with a reinforcing loop under visible non-repair; related to but not identical with `OBS-11` eroding goals.
2. **Keep vs dispose spike contract** — every exploratory artifact must declare its disposal fate before it starts (generalization of tracer/prototype).
3. **Feedback-rate speed limit** — maximum safe step size is a function of how fast independent confirmation arrives (headlights).
4. **Allocator-releaser identity** — lifetime symmetry as a local correctness rule (finish what you start).
5. **Policy vs semantic invariant split** — hard-code only what cannot change without changing the meaning of the system; parameterize the rest.

## Reviewer notes
- rows nominated: **8**
- rows I am least confident in:
  - **Requirements are learned** — real and distinctive phrasing, but soft trigger for agents; may belong nearer product/process docs than engineering.md; overlaps iterative empiricism in modern-software-engineering.
  - **Don't outrun your headlights** — close to `REF-12` YAGNI; retained because feedback-rate + replaceability framing is checkable and not identical to "≥2 consumers."
  - **Finish what you start** — close to `RES-04`; retained for the split-open/close shared-handle cue, which `RES-04` does not name.
- existing canon rules I would cross-link instead of duplicating: `REF-10`, `REF-12`, `REF-13`–`REF-15`, `REF-18`–`REF-23`, `TEST-*`, `DBG-*`, `DIAG-*`, `RLSE-05`, `AGT-10`/`14`/`18`/`19`/`20`, `RES-04`, `CON-05`/`11`/`17`, `DOM-03`, `NAME-02`, `ARCH-07`/`08`, `TEAM-*`, `PERF-05`/`06`, `FORE-*`, plus distillations: why-programs-fail (DbC), release-it, philosophy-of-software-design, modern-software-engineering, art-of-unix-programming, refactoring-fowler-beck, working-effectively-with-legacy-code.
- anything in the extract that is garbled/unusable: extract is page-image OCR-style with `=== f_NNNN ===` markers and occasional soft hyphens / special spaces around tip titles; readable enough for grounding. Code samples sometimes split with stray `​` characters; semantics intact. No chapter content appeared missing for Topics 1–53 + postface.
- volume calibration: book is upstream received wisdom; **long cross-link list + 8 nominees** is intentional. Resist promoting orthogonality, DbC, plain text, or estimation as new ENG rows without a named partition.
