# Implementing Effective Code Reviews — distilled

> **Source**: Carullo, Giuliana. *Implementing Effective Code Reviews: How to Build and Maintain Clean Code*. 1st ed. Apress, 2020. · extracted from `literature/extracted/engineering/implementing-effective-code-reviews.txt` · distilled 2026-08-06 (spec v2)
> **Contributes**: A **process-and-checklist** survey of clean-code review practice (peer review vs inspection, SMART findings, reviewer duties, manager economics, eight design-smell names). Wave intent: review process, defect classes, team dynamics — checked against `modern-software-engineering` (feedback/small batches/DORA) and `team-topologies` (org as architecture). Almost all clean-code, naming, pattern, concurrency, and security guidance already forces the same decisions under existing `REF`/`TEST`/`NAME`/`CON`/`SEC`/`RLSE`/`TEAM` rows. The residue worth promoting is thin and process-shaped: how a finding is written, whether the reviewer executes the change, and that re-review after requested fixes is mandatory. Defect-class catalog is useful as a review jump table, not as new lexicon IDs.

## Chapter map

- ch-1 — The Art of Programming: code smells as early quality signals; SDLC models; review types (informal / walkthrough / inspection); peer review limits; manual vs automation; ROI framing
- ch-2 — Code Structure: spaghetti recipe; KISS, reusability, readability, modularity, maintainability, testability; composition over inheritance; premature optimization vs design; API care; control-structure completeness; five architecture-health indicators
- ch-3 — Data Structures: fit-for-purpose DS choice (complexity, growth, native ops, 80/20 of operations); avoid forcing the wrong structure
- ch-4 — Design Smells: eight named smells (cyclic deps, feature density, unstable dependency, mashed components, ambiguous interface, mesh, first lady / god, bossy / not-my-responsibility)
- ch-5 — Software Architectures: GoF-style pattern catalogue (creational/structural/behavioral) with when/when-not; patterns as shower for architectural dirt
- ch-6 — From Scratch: problem statement; MVP vertical slices; FURPS+ and requirement validation properties; tech/team/process fitness; **before/during/after** design-review fields
- ch-7 — Naming and Formatting Conventions: meaningful/context names; consistency; parameters/modifiers; magic numbers; language conventions
- ch-8 — Comments: not excused by good code; pre/post/flows/IO types; sparse inline; TODOs out of release; comments-driven development mentioned
- ch-9 — Concurrency, Parallelism, and Performances: concurrency vs parallelism; safety/liveness; races, deadlocks; parallel costs and metrics
- ch-10 — Security: no 100% security unicorn; CIA/PAIN framing; principles; SSDLC; SAST + manual security reviews
- ch-11 — Code Reviews: **clean code lifecycle (CCLC)** / **code review lifecycle (CRLC)**; defect density / DRE; inspection rate / coverage / DDR; SMART feedback; prioritization templates; developer traps and manners; manager firefighting/CBA

## Read boundary

Read fully: frontmatter (identity, edition, chapter list), ch-1, ch-2, ch-4, ch-6, ch-11, conclusions.  
Deep skim (openings, summaries, review checklists, key mechanism sections): ch-3, ch-5, ch-7, ch-8, ch-9, ch-10.  
Not claimed beyond those: fine-grained pattern implementation details inside every ch-5 example, or every ch-3 complexity cell as a promotable rule.

Anchors below use printed chapter numbers and author-named mechanisms. No `L####` offsets.

---

## ch-1 — The Art of Programming {#ch-1}

**Code smell** (Beck/Fowler lineage restated): a surface cue of a deeper problem; sniff early so the baby defect does not become the multi-headed monster. Reviews teach, but must not license writing bad code on purpose for someone else to fix.

Why quality matters (compressed): poor readability → low productivity → bug pollution → release delay → poor maintainability → rewrite temptation (reject wholesale rewrite as default).

**SDLC** phases named: requirements (SRS), design (DDS), development, testing (scattered), release. Models: waterfall, iterative, agile, prototype. Prototype caution: isolation + short life may tolerate lower polish; long-lived, multi-integration “prototypes” still need quality or they slow dependents.

**Code reviews in the SDLC** (Figure 1-2 framing): not only PR-scoped peer review; regularly span broader clean-code concerns across the lifecycle.

**Review types**:

| Type | Character |
|---|---|
| Informal | Little prep; brainstorming; few metrics |
| Walkthrough | Author-led feedback seeking; less defect-correction focus |
| Inspection | Planned, checklist + metrics; find/log/communicate defects; usually not by author |

**Peer reviews** common and useful for small deltas, but clean code at scale is not only feature-sized PR review — take periodic steps back for broader form.

**Rule of thumb**: integrate reviews early in the development process.

**Manual vs automated**: automate formatting/style/static analysis and tests for speed and repeatability; quality is still the priority. Automation spots many standard violations; design judgment (e.g. whether a long method is multi-feature or legitimately complex) still needs a human read. Best automated tests catch breakage, not “clean code.”

Claimed benefits (compressed): ROI, agility fit, productivity, better testing/refactoring outcomes, learning, lessons, brand.

## ch-2 — Code Structure {#ch-2}

**Spaghetti code**: unstructured control, arbitrary jumps/GOTOs, unmaintainable tangle. Recipe for disaster (compressed anti-list): no design, globals, OO language without OO benefits, ignore patterns, god classes, high coupling, ad-hoc APIs, random threads, no reuse.

Principles restated (all already dense in the canon): **Zen of Python** as general guide; **KISS**; **reusability** / avoid duplication of logic and data; **readability** (names, comments, short units, consistent convention, Miller short-term memory cue); **modularity** (cohesion + loose coupling); **maintainability** / extensibility; **testability** (prefer independent tester when staffing allows); **composition over inheritance** (forwarding-method excess as rare inheritance cue); **premature optimization** ≠ skip design — meet known perf requirements, defer speculative speedups.

**APIs**: do not hide dirty code under a clean façade; design error handling and response shape early; API-first thinking helps edge cases and logical isolation.

**Control structures**: prefer fully defined conditionals (else for each if) for defined behavior.

**Five health indicators** beyond local defects: problem definition (scope, MVP/roadmap); validate architecture against functional/non-functional requirements; rethink tech (not every problem is a nail); team knowledge/training; processes that make development manageable.

Boy-scout note: leave code better than found.

## ch-3 — Data Structures {#ch-3}

Survey of common structures and average operation costs. Review stance: **fit for purpose**, not fashion.

Rules of thumb: if you force non-native operations, wrong structure; consider growth; use frequency of ops (80/20); do not pick fancy structures for show; simple that works beats complex that impresses.

## ch-4 — Design Smells {#ch-4}

Architecture/design debt makes features harder; smell often, incrementally (gym abs metaphor). Eight smells (author names + aliases):

| Smell | Cue | Direction |
|---|---|---|
| **Cyclic dependencies** | A↔B (or longer cycle); class diagram not a DAG | Redesign responsibilities; merge if cohesive/small; introduce interfaces |
| **Feature density** | One component, multiple logical goals; may steal callee duties (also “feature envy” in text) | Single responsibility; extract |
| **Unstable dependency** | Stable unit depends on less-stable unit | Prefer stabler dependency; system as weak as weakest link |
| **Mashed components** | One logical function scattered (scattered functionality) | Re-abstract; remove redundancy |
| **Ambiguous interface** | Single vague entry, or overlapping signatures that both apply | Redesign interfaces early |
| **Mesh components** | Dense coupling without clear patterns (dense structure) | Patterns/managers for auth, DB, etc. |
| **First lady** | God component: implements everything; few real deps | Split abstractions; logging-on-User anti-example |
| **Bossy / not-my-responsibility** | Abstraction only delegates; zero own duty | Question whether the layer earns its keep |

SRP restated: one logical goal per unit. Technical debt and architecture debt defined at bug vs component granularity.

## ch-5 — Software Architectures {#ch-5}

Patterns as rinse for architectural dirt. Categories: creational, structural, behavioral (concurrency patterns deferred to ch-9). Catalogue includes singleton, lazy init, builder, abstract factory, factory method, adapter, decorator, façade, composite, pub-sub, iterator, visitor, state, chain of responsibility — each with purpose, use, and misuse notes (e.g. singleton/decorator becoming first-lady; chain length vs performance/debug cost).

Takeaway: pick a pattern only when the problem matches its goal; keep simple.

## ch-6 — From Scratch {#ch-6}

Resist full rewrite when code is only partially wrong.

**Problem statement** must be clear or tests and reviews have no correctness target. Incremental delivery is fine; each increment’s scope and the end goal still need clarity.

**MVP**: smallest usable set toward the goal. Prefer vertical slices (functionality + reliability + usability + design fit) per iteration, not horizontal “all features then reliability.”

**FURPS+** non-functionals: functional (incl. security), usability, reliability, performance, supportability; plus implementation, interfaces, packaging, operations, legal.

**Requirement validation properties**: complete, correct, consistent, unambiguous, realistic, verifiable, traceable.

**Technologies / team / processes**: past experience and trends are references not defaults; assess skill fit and learning-curve impact; processes clear, complete, systematic, actionable; prefer not to mix methodologies on one project without deliberate switch.

**Design-review lifecycle fields**:

- Before: project, reviewer, tech contact, developers, **scope**, iteration number, dates, **goal**, input docs  
- During: defect counts, impact ranks  
- After: detailed improvements, trade-offs/suggestions, prioritization input  

Embed reviews at early SDLC stages, not only at coding peer review.

## ch-7 — Naming and Formatting Conventions {#ch-7}

Meaningful, descriptive, context-oriented, consistent names; avoid joke names, cryptic acronyms, needless single letters (loop indices exception). Same name must not mean different things. Parameters, modifiers, globals, magic numbers, parameterization for reuse, spacing, language conventions (e.g. PEP 8) — automate style checks when possible.

## ch-8 — Comments {#ch-8}

Good code does not remove the need for comments as code and teams grow. Prefer coherent method-level docs: purpose, **pre/post-conditions**, flows including exceptions, **IO types** (especially dynamic languages). Sparse inline comments; excess inline often signals multi-feature or oversized units. Strip TODO/FIXME from released code. Comments-driven development mentioned as description-first practice. Maintain comments with code; avoid obvious noise and stale docs.

## ch-9 — Concurrency, Parallelism, and Performances {#ch-9}

Concurrency ≠ parallelism. Foundations: thread safety, immutability, races, atomicity, safety/liveness, deadlock/starvation/fairness, locking, ACID-ish properties for concurrent apps. Parallelism: hard problems stay hard; granularity, locality, load balance, coordination cost; prioritize metrics for the actual context. Review checklist mirrors these concerns.

## ch-10 — Security {#ch-10}

100% secure code is a unicorn; “later” is procrastination. CIA triad and related definitions; security principles and caveats (incl. against security-by-obscurity). **SSDLC**: training, requirements, security by design, secure build/test, incident response plan, public-release processes, ongoing maintenance. Security code reviews for exposure (authn/z, sessions, privacy, logging, crypto, injection, …). **SAST** for first pass; manual review still needed for context and false pos/neg. Monitor in production; no one-size-fits-all.

## ch-11 — Code Reviews {#ch-11}

### Clean code lifecycle and CRLC

**CCLC** ties classical SDLC and SSDLC feedback. **CRLC** composition: (1) peer reviews in development, (2) automation when feasible, (3) regular comprehensive manual reviews. Feedback loops keep clean and secure code over time.

### Code metrics

| Metric | Role | Caution |
|---|---|---|
| **Defect density (DD)** | Defects per LOC — high-level status | Quantity ≠ severity; prioritize |
| **Defect removal effectiveness (DRE)** | How effectively issues are removed across lifecycle | Track latent + newly introduced over time |
| Defect staging table | Functional / smells / design / requirements / architecture / process / security counts | Template, not law |

Later review finding **more** defects than an earlier one may signal new injection (coarse indicator).

### Review process metrics

| Metric | Definition intent | Caution |
|---|---|---|
| **Inspection rate (IR)** | LOC / hours reviewing | Context: quality, experience, familiarity, feedback quality — no universal “good” IR |
| **Code coverage (CC)** of review | Expect full inspection of the scoped unit | Prefer small increments so complete review is tractable |
| **Defect detection rate (DDR)** | Defects found per unit time | Same contextual caution as IR |

### SMART findings and planning

**Clear goals** for each review (environment, stage, scope, tech).

**Stay scientific, stay SMART**: findings specific, measurable, achievable, relevant, time-bounded. Bad: “too many dependencies, bad design, change it.” Better: name smell/pattern, concrete refactor direction, priority, sprint-bounded action.

Track defects with type, component, priority, suggestion (tables or tickets). Checklists guide but are **not enough** alone — use scenario-based architecture review and similar methods.

### Developer traps and manners

Traps: (1) judgmental review (toxic, hurts morale), (2) personal (defect is in the code, not the person), (3) frustration with tedious process. Avoid ego competition over “most beautiful code.”

Process hygiene: not perfectionist nitpicks as reject reasons; **keep commits/branches focused and short** so reviews stay fast; commit accurately as reviewer; **do not assume code works** — rebuild and test even for senior authors; for new functionality check docs and tests; include some testing in review (catch early, not only QA); ask when unclear (readability is a quality property); **re-review** after requested changes (rebuild, retest, docs/tests again).

### Managers

Quality reduces firefighting and context-switch cost; distributed teams need shared coding practices as well as spoken language. Simplified CBA: recurring cost of unfixed debt vs one-time fix cost — numbers are illustrative; plug local rates. Do not treat reviews as pure feature-tax.

---

## Decision rules (summary)

| Trigger (observable) | Rule | Rationale | Src |
|---|---|---|---|
| Review finding is vague (“bad design”, “too coupled”) with no defect type, priority, or fix direction | Write **SMART** findings: specific defect, type, component, measurable suggestion, time box | Vague feedback cannot be scheduled or verified | ch-11 |
| Review of a change never rebuilt or re-ran tests | Reviewer **rebuilds and tests** the change; for new behavior also check docs/tests | Read-only review misses integration and broken-suite failures | ch-11 |
| Author returns after requested fixes; approval without checking each named item | **Re-review**: rebuild, retest, verify each required change | First-pass findings are worthless if not confirmed closed | ch-11 |
| Only PR-scoped peer reviews ever run; multi-component design never inspected | Schedule **broader inspection** (design/architecture scope), not only feature deltas | Peer PR review alone under-samples system-level smells | ch-1, ch-11 |
| Review goal/scope blank | Set **review goals and scope** before starting (what unit, what questions) | Unscoped review drifts or nits | ch-6, ch-11 |
| Review comment attacks person, ranks authors, or treats review as competition | Target **code defects**, teach/reward; no personal scorekeeping | Personal review destroys learning value of the process | ch-11 |
| Reject solely for non-defect style preference | Do not block on **minutia** without a named defect class | Perfect code does not exist; process becomes tedious trap | ch-11 |
| Giant multi-concern branch awaiting review | Prefer **focused short commits/branches** | Large units slow review and hide defects | ch-11 |
| Static analysis green treated as clean-code done | Keep **manual judgment** for design smells automation cannot settle | Automation ≠ quality ownership | ch-1, ch-10 |
| Class diagram has cycles | Break **cyclic dependencies** (SRP, merge, or interfaces) until DAG | Cycles couple change, test, and reuse | ch-4 |
| Type owns unrelated responsibilities or implements callees’ work | Split **feature density** / god (**first lady**) units | SRP failure multiplies deps and change cost | ch-4 |
| Type only delegates with no own policy | Remove or give purpose to **bossy** layer | Empty coordinator adds coupling without value | ch-4 |
| Stable module depends on known-unstable module | Avoid **unstable dependency** when production stability matters | Stability collapses to weakest link | ch-4 |
| Logical function split across many types without clear reason | Repair **mashed** / mesh coupling with real abstractions | Scatter multiplies touch points | ch-4 |
| Overlapping public signatures both apply to same call | Disambiguate **interfaces** | Ambiguity forces guesswork and integration pain | ch-4 |
| MVP plan is feature-layer only | Plan **vertical MVP slices** (function + reliability + usability + design) | Horizontal layers delay learning and ship broken usability | ch-6 |
| Problem/scope undefined | Fix **problem statement** before correctness review | No target → no done, weak tests and reviews | ch-6 |
| Coverage % is the quality target for reviews/process | Prefer **defect removal / escape** style outcomes over vanity density alone | DD without priority is quantitative theater | ch-11 (↔ RLSE-14, TEST-11) |
| Long-lived multi-integration “prototype” claims quality exemption | Apply quality proportional to coupling and lifetime | Prototype excuse fails when others depend on the code | ch-1 |

## Anti-patterns

| Name (book) | Detection cue |
|---|---|
| Spaghetti code | Unstructured flow, globals, god classes, no modular design |
| First lady / god component | Huge LOC, many unrelated duties, logging-on-User style |
| Bossy component | Orchestrator with only delegated calls, no policy |
| Feature density | Multiple independent behaviors in one unit |
| Mesh / mashed | Dense or scattered coupling without clear patterns |
| Ambiguous interface | One vague entry or competing overloads |
| Unstable dependency | Clean unit imports known-smelly unit |
| Judgmental / personal review | Comments about people, ego competition |
| Nitpick reject | Block on non-defect preference |
| Checklist-only review | Tick boxes without scenario/architecture thinking |
| Automation-first quality | Green linters, dirty design |
| Firefighting culture | Constant defect interrupts of feature work (manager view) |

## Applicability & exemptions

- **Audience**: engineers with some programming experience; Python examples, OO lean; not an encyclopedia of DS/architecture/security.
- **Not a tools manual**: deliberately avoids prescribing specific review tools; process and judgment first.
- **Era**: 2020 Apress; security/tool links age; principles and process claims outlive tool lists.
- **Inspection-rate “good” values**: author rejects universal IR targets — always contextualize.
- **Agile tables**: defect tables are optional if tickets/planning capture the same; form follows process.
- **Prototype exemption**: only short-lived, isolated prototypes; not multi-month shared ones.
- **Security**: “secure enough” for context; not absolute safety.
- **Team-topologies check**: book’s team dynamics are review etiquette and manager CBA, **not** Conway/team-type design — do not promote as competing `TEAM-01..11` org topology rules.
- **Modern-software-engineering check**: continuous small-batch feedback and DORA fitness dominate over slow formal inspection theater; keep Carullo’s “broader than PR” only when multi-component debt is invisible to PR scope, not as a CAB-style gate.

## Candidate lexicon rows

| Trigger (observable in code/diff/plan) | Rule | Activating question | Tier | Phase | Src |
|---|---|---|---|---|---|
| Review comment states a defect without type, priority, concrete fix suggestion, or time box | **SMART review findings**: write specific, measurable, achievable, relevant, time-bounded findings (defect, type, component, priority, suggestion) so work can be scheduled and verified | Can this finding be actioned without guessing what “fix it” means? | should | review | src: implementing-effective-code-reviews ch-11 |
| Change under review has not been rebuilt or re-tested by the reviewer | **Reviewer rebuild-and-retest**: rebuild and run tests as part of the review; for new functionality also check accompanying docs/tests | Did the reviewer execute the change, or only read it? | should | review | src: implementing-effective-code-reviews ch-11 |
| Author pushes fixes after review requests; merge/approve without checking each named request | **Mandatory re-review of requested changes**: re-run build/tests and confirm each required defect is addressed before approval | Was every named request re-verified after the fix? | should | review | src: implementing-effective-code-reviews ch-11 |

### Candidate dispositions

- **SMART review findings:** PROMOTED as TEST-31
- **Reviewer rebuild-and-retest:** PROMOTED as TEST-32
- **Mandatory re-review of requested changes:** PROMOTED as TEST-33

## Cross-links

| Topic | Nearest existing IDs | What a kept row would force that they do not |
|---|---|---|
| SMART findings | `RLSE-03` (invariants before audit), `AGT-08` (rejection is specification), `FORE-02` (resolvable criteria) | Forces **reviewer finding form** (type/priority/suggestion/deadline), not release invariants or author gate satisfaction |
| Rebuild/retest in review | `TEST-01`/`TEST-03` (author test discipline), `DBG-01` (reproduce before fix) | Forces **reviewer-side execution** of the submitted change, not author-side suite ownership |
| Re-review after fixes | `AGT-08` (satisfy named rejection) | Forces **second reviewer pass** confirming closure, not only author re-attempt |
| Small batches / focused PRs | modern-software-engineering ch-4; `REF-05` two hats | Same decision: small change units — **not kept** |
| DRE / density vs coverage targets | `RLSE-14`, `TEST-11`, Jones DRE material | Same economic outcome metrics — **not kept** |
| God / multi-responsibility types | `REF-35`, `REF-36`, `REF-18` | Same SRP/split decision — **not kept** |
| Pass-through / empty layer | `REF-22`, `REF-18` | Bossy component ≈ empty coordinator; same remove-or-earn decision — **not kept** |
| Cycles / coupling | `REF-13`, `REF-14`, `ARCH-*` | Same independence/coupling triage — **not kept** |
| YAGNI / premature optimization | `REF-12`, `REF-28`, `PERF-06` | Same measure/speculative gates — **not kept** |
| Naming | `NAME-*` | Same lying/vague name decisions — **not kept** |
| Comments / contracts | `REF`/`why-programs-fail` contract material; pragmatic DBC | Same document pre/post — **not kept** |
| Concurrency | `CON-*` | Same race/deadlock discipline — **not kept** |
| Security review items | `SEC-*`, `WEB-*`, `SECD-*` | Same principle checks — **not kept** |
| Org structure / ownership | `TEAM-01..11` | Book does not add topology; etiquette ≠ Conway — **not kept** |
| Checklist incompleteness | `RLSE-01` multi-lens | Same “one checklist misses classes” — **not kept** |
| Broken windows / leave better | `REF-25` | Same visible-neglect rate claim — **not kept** |
| Metric gaming | `TEAM-12`, `TEST-11` | Same purpose-before-proxy — **not kept** |

## Tensions

- **Comprehensive inspection vs continuous small-batch feedback** (`modern-software-engineering` ch-4/ch-5): Carullo’s third CRLC leg (regular broad manual review) can become slow theater if it replaces small, frequent feedback. Prefer Farley’s fitness when the alternative is a late mega-inspection; keep multi-component scope only when PR-local review cannot see design smells.
- **Developer-as-tester vs specialist QA**: book wants review-time testing; orgs with separate QA still should not treat review as “compile only.” Does not force abolishing QA roles (`TEAM-06`/`TEAM-07` still forbid permanent hand-off silos that only queue work).
- **Composition over inheritance** vs rare inheritance when forwarding explodes: book allows re-evaluate inheritance if pass-through noise is high — judgment, not a new absolute.

## First-principles candidates

none — the process mechanisms here are software-engineering practice, not independent multi-domain causal convergences beyond what `REF-25` / `TEST-11` / team-load principles already capture.

## Candidate disposition

- `proposed SMART review findings` — live shortlist; nearest `RLSE-03`/`AGT-08`; forces finding grammar for reviewers
- `proposed Reviewer rebuild-and-retest` — live shortlist; nearest author-side `TEST-*`; forces reviewer execution
- `proposed Mandatory re-review of requested changes` — live shortlist; nearest `AGT-08`; forces second-pass verification
- `not promoted (proposed focused short commits for review; duplicates modern-software-engineering small batches + REF-05)`
- `not promoted (proposed DRE/defect-density process metrics; duplicates RLSE-14, TEST-11, software-development-patterns-antipatterns DRE)`
- `not promoted (proposed inspection-rate quality gate; author rejects universal IR; TEAM-12 metric purpose)`
- `not promoted (proposed peer-plus-comprehensive CRLC as three mandatory gates; tension with continuous feedback; keep only as ch-1/ch-11 process note)`
- `not promoted (proposed checklist-not-enough; duplicates RLSE-01 non-overlapping lenses)`
- `not promoted (proposed clear review goals/scope template; duplicates RLSE-03 invariants-before-audit mechanism)`
- `not promoted (proposed non-judgmental/personal review etiquette; soft skill; no distinct agent-observable contract beyond BIAS-04 fairness)`
- `not promoted (proposed no-nitpick rejects; overlaps REF-11 style exemptions + judgment; weak falsifiability)`
- `not promoted (proposed first-lady/god component smell; duplicates REF-35)`
- `not promoted (proposed feature density / multi-responsibility; duplicates REF-35 / SRP cluster)`
- `not promoted (proposed feature envy naming; duplicates REF-36)`
- `not promoted (proposed bossy empty coordinator; duplicates REF-22 + REF-18)`
- `not promoted (proposed cyclic dependency DAG check; covered by coupling/architecture REF-13/REF-14 and design practice)`
- `not promoted (proposed mashed/mesh/scattered functionality; covered by cohesion/coupling REF-13/REF-18/modularity material)`
- `not promoted (proposed ambiguous interface; covered by API/NAME clarity rows)`
- `not promoted (proposed unstable dependency; weak novel force vs ARCH dependency judgment + weak-link security analogy)`
- `not promoted (proposed composition-over-inheritance default; already standard OO guidance in REF/clean-code distillations)`
- `not promoted (proposed premature-optimization gate; duplicates PERF-06 / REF-12 / REF-28)`
- `not promoted (proposed hide-dirty-code-under-API; covered by REF-16 leaky abstraction / API consistency)`
- `not promoted (proposed leave-code-better / boy scout; duplicates REF-25 broken windows)`
- `not promoted (proposed MVP vertical slice; product/process, overlaps modern-software-engineering incrementalism)`
- `not promoted (proposed problem-statement-before-review; process hygiene already implied by RLSE-03 / testability-of-done)`
- `not promoted (proposed FURPS+ requirement catalogue; project-management checklist, not engineering agent rule)`
- `not promoted (proposed naming meaningfulness/consistency; duplicates NAME-*)`
- `not promoted (proposed comment pre/post/IO docs; duplicates contract/comment practice already grounded elsewhere)`
- `not promoted (proposed concurrency safety checklist; duplicates CON-*)`
- `not promoted (proposed security review checklist / SAST+manual; duplicates SEC/WEB/SECD and existing SSDLC practice)`
- `not promoted (proposed data-structure fit-for-purpose; duplicates ALG/PERF structure choice)`
- `not promoted (proposed design-pattern catalogue rows; GoF already ambient; no new decision force)`
- `not promoted (proposed manager CBA for tech debt; illustrative economics; Jones/Farley already cover quality economics)`
- `not promoted (proposed distributed-team shared coding standards; soft; TEAM owns structure not style guides)`

## Disposition summary

**Three** process candidates shortlisted (SMART findings, reviewer rebuild-and-retest, mandatory re-review). **Thirty-plus** mechanisms considered and rejected as duplicates of existing IDs or as non-promotable soft/PM material. This source is a **strong review checklist companion** and a weak new-rule mine — expected outcome given corpus density and prior intake wave pattern.
