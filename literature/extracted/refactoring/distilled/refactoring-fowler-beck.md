# Refactoring: Improving the Design of Existing Code (2nd ed) — distilled

> **Source**: Martin Fowler with Kent Beck, *Refactoring: Improving the Design of Existing Code*, 2nd edition (2018, JavaScript examples) · extracted from `../Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The canonical vocabulary for behavior-preserving code change: 24 named **code smells** with their mapped fixes, ~60 named refactorings with safe step-by-step mechanics, and the process discipline around them (**two hats**, compile-test-commit rhythm, revert-to-green, preparatory refactoring). No other source in this directory gives an agent a smell→refactoring dispatch table, the micro-step mechanics that keep a codebase green mid-restructure, or the economic (not moral) justification for when to refactor and — equally load-bearing — when not to. Ch-4 is the directory's most concrete guide to building a test suite *against existing code* before touching it.

## Chapter map

- `ch-1 — Refactoring: A First Example`: what the refactoring process looks like end-to-end; the rhythm of tiny steps; the three-stage decomposition of a real function.
- `ch-2 — Principles in Refactoring`: definitions, two hats, why/when/when-not to refactor, economics vs. morality, branches & CI, legacy code, databases, YAGNI, performance strategy.
- `ch-3 — Bad Smells in Code`: the 24 smells — detection cue → refactorings dispatch table (the hot path for review work).
- `ch-4 — Building Tests`: building a self-checking suite against existing code; what to assert; fixture discipline; risk-driven coverage.
- `ch-5 — Introducing the Catalog`: catalog entry format; how to read mechanics.
- `ch-6 — A First Set of Refactorings`: Extract/Inline Function & Variable, Change Function Declaration, Encapsulate Variable, Rename, Parameter Object, Combine Functions into Class/Transform, Split Phase.
- `ch-7 — Encapsulation`: Encapsulate Record/Collection, Replace Primitive with Object, Replace Temp with Query, Extract/Inline Class, Hide Delegate, Remove Middle Man, Substitute Algorithm.
- `ch-8 — Moving Features`: Move Function/Field, Move Statements, Slide Statements, Split Loop, Replace Loop with Pipeline, Remove Dead Code.
- `ch-9 — Organizing Data`: Split Variable, Rename Field, Replace Derived Variable with Query, reference↔value.
- `ch-10 — Simplifying Conditional Logic`: Decompose Conditional, guard clauses, Replace Conditional with Polymorphism, Special Case (null object), assertions.
- `ch-11 — Refactoring APIs`: query/modifier separation, flag arguments, whole objects, parameter↔query, setters, factories, command objects.
- `ch-12 — Dealing with Inheritance`: pull up/push down, Replace Type Code with Subclasses, Remove Subclass, Extract Superclass, Collapse Hierarchy, replacing inheritance with delegation.

---

## ch-1 — Refactoring: A First Example {#ch-1}

Worked example: a monolithic `statement()` function (theater invoice: switch on play type, inline calculation + string formatting) is decomposed in three stages: (1) extract nested functions, (2) **Split Phase** — separate calculation from rendering via an intermediate data structure (`createStatementData` → `renderPlainText`/`renderHtml`), (3) **Replace Conditional with Polymorphism** — a `PerformanceCalculator` hierarchy with a factory function, so `amount`/`volumeCredits` become subclass overrides.

Sequence of refactorings applied (each a catalog entry): Extract Function → rename vars → Replace Temp with Query (`playFor`) → Inline Variable → Change Function Declaration (drop now-derivable parameter) → Split Loop + Slide Statements → Extract Function on totals → Inline Variable → Split Phase → Replace Type Code with Subclasses + Replace Conditional with Polymorphism (via factory).

Process rules this chapter establishes (they recur through the whole book):

- **First step is always the same**: before touching anything, ensure a solid suite of **self-checking** tests for that section of code (green/red, no manual output inspection).
- **compile-test-commit after every small step.** Frequent private commits give a cheap undo point. Squash before pushing.
- **Revert to green**: if a test fails mid-refactor and the cause isn't immediately obvious, revert to the last green commit and redo with smaller steps. Small steps are the key to moving quickly — "you go faster when you take tiny steps, the code is never broken."
- **Remove local variables before extracting.** Temps create locally scoped names that block extraction (this is why `playFor` and `usd` were made queries). Usually take out local variables before doing any extractions.
- **Name by intent, not mechanism.** Return variable always named `result`; parameters carry a type hint with indefinite article (`aPerformance`) in dynamically typed code. If you can't name the extraction better than the code reads, don't extract. Names rarely come out right first time — rename on the second pass without hesitation.
- **A misleading comment is worse than none** — after extraction, delete comments the code now states.
- **Performance worries during refactoring: ignore them.** Repeating a loop or a lookup is almost never measurable; "most programmers, even experienced ones, are poor judges of how code actually performs." Refactor first; if a real slowdown lands, tune afterwards on the now-well-factored code (see ch-2).
- Reading → insight → refactor to move that insight from your head into the code (Ward Cunningham: the head is "a notoriously volatile form of storage"). Comprehension refactoring is a positive feedback loop.
- **The true test of good code is how easy it is to change it.**

---

## ch-2 — Principles in Refactoring {#ch-2}

### Definitions (used precisely)

- **Refactoring (noun)**: a change made to the internal structure of software to make it easier to understand and cheaper to modify **without changing its observable behavior**.
- **Refactoring (verb)**: restructuring by applying a *series* of refactorings, each behavior-preserving.
- Litmus test: "If someone says their code was broken for a couple of days while they are refactoring, you can be pretty sure they were not refactoring." Refactoring ≠ generic restructuring/cleanup; it's the specific discipline of composing small behavior-preserving steps, so the code is never broken and you can stop at any moment.
- "Observable behavior" is deliberately loose: call stacks, performance, and module-internal interfaces may change; nothing the user cares about may change. Latent bugs nobody has observed may be fixed; observed bugs must survive the refactoring.
- Refactoring vs. performance optimization: same kind of manipulation, different purpose — refactoring optimizes for understandability/changeability and may slow code down; optimization accepts harder-to-work-with code for speed.

### The Two Hats (Kent Beck)

Two distinct activities, never simultaneous:

| Hat | Allowed | Forbidden |
|---|---|---|
| **Adding functionality** | new capabilities, new tests; progress = tests going green | changing existing code structure |
| **Refactoring** | restructuring only | new functionality; new tests (except covering a previously missed case); test changes only when an interface changes |

Swap frequently (possibly every few minutes) but always *know which hat you're wearing* — it changes what "done" and "safe" mean for the current edit.

### Why refactor (all four reduce to the fourth)

1. **Improves design** — architecture decays as people change code without grasping the design; decay compounds ("the harder it is to see the design in the code... the more rapidly it decays"). Core design move: eliminate duplication so the code says everything once and only once.
2. **Makes code easier to understand** — the most important reader of code is the future programmer (often yourself); put everything you'd have to remember into the code.
3. **Helps find bugs** — clarifying structure surfaces assumptions until "even I can't avoid spotting the bugs." (Beck: "I'm not a great programmer; I'm just a good programmer with great habits.")
4. **Helps program faster** — the **Design Stamina Hypothesis**: good internal design increases the stamina of the effort; teams with healthy code add features faster for longer, because the code base becomes "a platform for building new features for its domain."

### When to refactor

- **Preparatory refactoring** (the best time): just before adding a feature or fixing a bug, restructure so the change becomes easy. Kent Beck: "for each desired change, make the change easy (warning: this may be hard), then make the easy change." Jessica Kerr's image: drive 20 miles north to the highway to go 100 miles east at 3× the speed.
- **Comprehension refactoring**: while reading code you had to think about — rename, extract — to move understanding from head into code. Ralph Johnson: like wiping dirt off a window so you can see beyond. Skipping it means never seeing the opportunities hidden behind the confusion.
- **Litter-pickup refactoring**: you understand the code and it's doing something badly — fix now if easy, note it if not; always leave the camp site cleaner than you found it. Small improvements per visit compound; the code is never broken part-way.
- **Planned refactoring**: should be *rare* — a sign of prior neglect. Most refactoring is unremarkable and opportunistic: "I don't put time on my plans to do refactoring — any more than you set aside time to write if statements." Excellent code needs plenty of refactoring too (yesterday's correct tradeoffs are wrong for today's features).
- **Long-term refactoring** (library swap, dependency untangling): don't dedicate the team; agree on the direction and have everyone nudge code in that direction whenever they touch the zone, over weeks. For library replacement use **Branch By Abstraction**: introduce an abstraction that can front either library, migrate callers, then swap.
- **Code review**: refactor to try suggestions concretely instead of imagining them; works best with the author present (pair review); the pull-request model without the author works poorly for this.
- Separate refactoring commits from feature commits? Fowler is *not* convinced — often too interwoven, and separation removes context. Team experiment, not a principle.

### When NOT to refactor (load-bearing — see Applicability & exemptions)

- **Ugly code you never need to modify or understand** — leave it. Code you can treat as an opaque API may remain ugly; refactoring only pays when someone needs to understand it.
- **Easier to rewrite than refactor** — a real option; requires judgment and often you only find out by spending some time trying.
- The tiny-feature case: when a large-scale refactoring is needed but today's change is trivial, doing just the change and leaving the refactoring is a legitimate judgment call — weighted by how often you visit that code.

### Economics, not morality

The most dangerous trap: justifying refactoring as "clean code" or "good engineering practice." **The point of refactoring is purely economic — it makes us faster to add features and fix bugs.** Communicate it that way to developers, managers, customers. If a manager isn't technically savvy: "Don't tell!" — refactoring is simply the fastest way to do the professional job you're paid for. Industry evidence: too little refactoring vastly outnumbers too much; developers squelch it in themselves even when leadership favors it.

### Problems / preconditions

- **Code ownership**: refactorings that cross ownership boundaries (published interfaces — clients you can't see or edit) force keep-old-as-forwarder + deprecate cycles, sometimes forever. Recommendation: team ownership (anyone on the team edits anything), or open-source-style cross-team commits; against fine-grained per-programmer ownership.
- **Branches**: long-lived feature branches create **semantic merge conflicts** (rename in my branch + new call in yours = clean textual merge, broken build) and merge pain grows *exponentially* with branch age. Refactoring makes this so much worse that feature-branch teams stop refactoring. Answer: **Continuous Integration / trunk-based development** — integrate with mainline at least daily; requires healthy-mainline discipline, small feature slices, feature toggles. CI + refactoring were combined in XP for this reason; cites [Forsgren et al.] for objective evidence.
- **Testing**: mistakes are fine *if caught quickly* — which requires a fast, comprehensive, self-checking suite (see ch-4). Alternative without tests: restrict yourself to refactorings that a trusted tool automates safely, or to proven-safe manual recipes — a workable but limited menu.
- **Legacy code**: no tests → you can't safely refactor into clarity. Follow *Working Effectively with Legacy Code* [Feathers]: find/create **seams**, insert tests there (this initial seam-making is refactoring without tests — a necessary risk, take it in the safest possible steps), then improve piecemeal — most effort in the areas you visit most often. Never big-bang.
- **Databases**: evolutionary database design [Ambler & Sadalage] — schema change + access-code change + data-migration script versioned together, composed in sequence. Unlike code refactorings, DB changes are best spread over multiple production releases so they're reversible: **parallel change (expand-contract)** — add new field, write both, migrate readers, watch, then drop old.

### Refactoring, architecture, YAGNI

Refactoring replaces finished-upfront architecture with **evolutionary architecture**. Speculative **flexibility mechanisms** (extra parameters, hooks for imagined futures) usually *slow* reaction to change: they complicate today's code and are often wrong. Instead: build excellently designed software for *current* needs only; when needs change, refactor (e.g., Parameterize Function is cheap later). Only add a mechanism now if you can see refactoring it in later would be *substantially* harder. Self-testing code + CI + refactoring → enables YAGNI/simple design → which in turn makes refactoring easier (less speculative complexity to wade through) → foundation for Continuous Delivery.

### Performance: three approaches

1. **Time budgeting** — per-component resource budgets; for hard real-time systems (pacemakers) where late data is bad data. Not for typical information systems.
2. **Constant attention** — every programmer optimizes everything all the time. Intuitive and **does not work**: diffuse micro-optimizations make code harder to change, are usually written with broken intuitions about compilers/caches, and most of them sit in code that barely runs. "In most programs, most of their time is spent in a small fraction of the code."
3. **Profile-then-tune** (recommended): build well-factored ignoring performance; in a deliberate optimization phase, run a profiler, find the hot spots, tune only those — in small steps, re-profiling after each, backing out changes that don't help. Well-factored code gives you more time to tune and finer granularity to profile. Sidebar (Beck/Fowler/Garzaniti, Chrysler C3): every speculated cause was wrong; the profiler showed half the runtime creating identical date instances — refactoring for clarity then enabled the real fix.

---

## ch-3 — Bad Smells in Code {#ch-3}

"If it stinks, change it." — Grandma Beck. Smells answer *when* to refactor (the catalog answers *how*). No metric threshold is offered on purpose: "no set of metrics rivals informed human intuition" — smells are indications, not verdicts; develop calibration.

### Smell → refactoring dispatch table

| Smell | Detection cue (observable) | Primary refactorings | Caveats / notes |
|---|---|---|---|
| **Mysterious Name** | you puzzle over what a function/variable/field name means | Change Function Declaration (124), Rename Variable (137), Rename Field (244) | can't find a good name → usually a deeper design problem; renaming is how you find simplifications |
| **Duplicated Code** | same code structure in >1 place; every read requires diffing them | Extract Function (106); Slide Statements (223) to align near-dupes then extract; Pull Up Method (350) for sibling subclasses | |
| **Long Function** | need comments to follow it; length is a proxy — real metric is *semantic distance* between name and body | Extract Function (99% of cases); temps in the way → Replace Temp with Query (178); params in the way → Introduce Parameter Object (140), Preserve Whole Object (319); still too many → Replace Function with Command (337); conditionals → Decompose Conditional (260); same switch repeated → Replace Conditional with Polymorphism (272); overloaded loop → Split Loop (227) | heuristic: whenever you feel the need to comment, extract a function named for the intent; extract even a single line if it needs explanation, even if the call is longer than the code |
| **Long Parameter List** | signature you can't hold in your head | derivable param → Replace Parameter with Query (324); unpacked structure → Preserve Whole Object (319); co-traveling params → Introduce Parameter Object (140); mode flag → Remove Flag Argument (314); several functions sharing params → Combine Functions into Class (144) | |
| **Global Data** | data modifiable from anywhere, no way to discover which code touched it (globals, class variables, singletons) | Encapsulate Variable (132) — always the first move — then shrink scope | Paracelsus: the dose makes the poison; immutable global data is relatively safe |
| **Mutable Data** | update here breaks an unstated expectation there; failures under rare conditions | Encapsulate Variable (132); Split Variable (240); Slide Statements (223) + Extract Function (106) to isolate side-effect-free logic; Separate Query from Modifier (306); Remove Setting Method (331); Replace Derived Variable with Query (248); Combine Functions into Class/Transform (144/149) to shrink update scope; Change Reference to Value (252) | risk scales with the variable's scope; a two-line-scope mutable is fine |
| **Divergent Change** | one module changed in different ways for different reasons ("these 3 functions per new DB, those 4 per new instrument") | sequential contexts → Split Phase (154); back-and-forth → Move Function (198); mixed inside functions → Extract Function first; classes → Extract Class (182) | context boundaries only become visible after a few changes — expect to discover this late |
| **Shotgun Surgery** | one logical change requires little edits in many modules; easy to miss one | Move Function (198) + Move Field (207) to consolidate; Combine Functions into Class (144) / into Transform (149); Split Phase (154); tactical: *inline* (Inline Function 115 / Inline Class 186) to pull the logic together first, then re-extract sensibly | deliberately creating a Long Function/Large Class as an intermediate step is fine |
| **Feature Envy** | a function communicates with another module's data/functions more than its own (half-a-dozen getters on another object) | Move Function (198) to where the data lives; envious fragment only → Extract Function then move | rule: put things together that *change together*; deliberate exceptions: Strategy, Visitor, Self Delegation — they trade indirection for isolating overridable behavior |
| **Data Clumps** | same 3–4 items travel together across fields and signatures | fields → Extract Class (182); signatures → Introduce Parameter Object (140) / Preserve Whole Object (319) | test: delete one item — do the others still make sense? no → an object is dying to be born; make a **class**, not a bare record, so behavior (feature envy) can migrate in |
| **Primitive Obsession** | domain concepts as ints/strings — money without currency, quantities without units, `a < upper && a > lower`, "stringly typed" phone numbers | Replace Primitive with Object (174); type code driving behavior → Replace Type Code with Subclasses (362) + Replace Conditional with Polymorphism (272); primitive clumps → Extract Class (182), Introduce Parameter Object (140) | |
| **Repeated Switches** | the *same* switch/if-else cascade in multiple places; adding a case means finding all copies | Replace Conditional with Polymorphism (272) | 2nd-ed softening: a *single* switch is not a red flag; the smell is the duplication |
| **Loops** | imperative loop where a pipeline would show what's included and what's done with it | Replace Loop with Pipeline (231) | |
| **Lazy Element** | function whose body reads as clearly as its name; class that's one simple function; structure that never grew into its ambitions | Inline Function (115), Inline Class (186); hierarchy → Collapse Hierarchy (380) | "needs to die with dignity" |
| **Speculative Generality** | hooks/abstract classes/parameters for "someday" cases that don't exist; machinery only exercised by tests | Collapse Hierarchy (380); Inline Function/Class; Change Function Declaration (124) to drop unused params; delete the test and Remove Dead Code (237) | "If all this machinery were being used, it would be worth it. But if it isn't, it isn't." |
| **Temporary Field** | instance field only set in certain circumstances; readers expect objects to need all their fields | Extract Class (182) for the orphan fields + Move Function (198); Introduce Special Case (289) for the invalid-state conditional code | |
| **Message Chains** | `a.getB().getC().getD()` — client coupled to the navigation structure | Hide Delegate (189) at some point in the chain; often better: Extract Function on the code *using* the result + Move Function to push it down the chain | hiding at every link turns every intermediate into a Middle Man — moderation |
| **Middle Man** | half a class's methods just delegate to another class | Remove Middle Man (192); few trivial delegators → Inline Function (115); with behavior → Replace Superclass/Subclass with Delegate (399/381) | inverse tension with Message Chains — you tune the hiding dial between them |
| **Insider Trading** | modules "whispering by the coffee machine" — heavy private data exchange; subclasses knowing too much about parents | Move Function/Move Field to reduce chat; third module or Hide Delegate (189) as regulated intermediary; inheritance collusion → Replace Subclass/Superclass with Delegate | |
| **Large Class** | too many fields (duplication follows); too much code | Extract Class (182) — grouped by common prefixes/suffixes of field names; inheritance-shaped subsets → Extract Superclass (375) or Replace Type Code with Subclasses (362); also: look at *clients* — each used-subset of features suggests a split | 500-line methods → five 10-line + ten 2-line methods via internal dedup |
| **Alternative Classes with Different Interfaces** | two classes do the same job but can't substitute for each other | Change Function Declaration (124) to align signatures; Move Function (198) until protocols match; then possibly Extract Superclass (375) | |
| **Data Class** | fields + getters/setters, no behavior; manipulated in far too much detail by others | public fields → Encapsulate Record (162) immediately; Remove Setting Method (331) on non-changing fields; Move Function (198) (or Extract Function first) to bring behavior home | **exception**: immutable result records (e.g., Split Phase intermediate data) are fine — immutable fields need no encapsulation |
| **Refused Bequest** | subclass ignores most inherited methods/data | traditional: sibling class + Push Down Method (359)/Push Down Field (361) | "nine times out of ten this smell is too faint to be worth cleaning"; but refusing the *interface* (not just implementation) is strong — don't fiddle with the hierarchy, gut it: Replace Subclass/Superclass with Delegate |
| **Comments (as deodorant)** | thickly commented code; the comments exist because the code is bad | comment explains a block → Extract Function (106); explains an extracted function → rename via Change Function Declaration (124); states required system state → Introduce Assertion (302) | comments per se are a *sweet* smell; good uses: what you don't know yet, and **why** you did something |

Rule of thumb printed alongside: *when you feel the need to write a comment, first try to refactor the code so that any comment becomes superfluous.*

---

## ch-4 — Building Tests {#ch-4}

Refactoring requires tests; tests also pay for themselves independently. Most programmer time is spent debugging, not writing — fixing a bug is quick, *finding* it is the nightmare. "A suite of tests is a powerful bug detector that decapitates the time it takes to find bugs."

### The non-negotiables

- **Fully automatic, self-checking.** A test either goes green or lists failures; nothing requires a human to compare output by eye. Manual checking is what makes testing "gut-wrenchingly boring" and unrun.
- **Run frequently.** Run the tests exercising the code you're working on at least every few minutes; all tests at least daily. Value comes from proximity: if the suite was green minutes ago, the bug is in the few lines you just wrote.
- **Never refactor on a red bar.** If the suite is failing, either fix it or revert to green (last version-control checkpoint with all tests passing) before restructuring.
- **Test-first for new features** (TDD): write the failing test before the code — it forces you to define done, and concentrates you on the *interface* rather than the implementation. Cycle: failing test → code to green → refactor; many times per hour.

### Building tests against existing code (characterization workflow)

The chapter's example is legacy-shaped: untested `Province`/`Producer` business logic that must be tested *before* an ugly derived-data update can be refactored. The workflow:

1. Separate concerns first: test business logic apart from UI/persistence/external services (and structure code so that's possible — architectures are rightly judged on testability).
2. Write a test asserting current observable output. **Placeholder trick**: write the assertion with a dummy expected value, run, paste the code's *actual* output as the expected value — trusting current behavior as the spec (a characterization test).
3. **Always make sure a test will fail when it should**: temporarily inject a fault into the production code (e.g., `* 2` in the formula), watch the test fail with a meaningful message, revert the fault. A test you've never seen fail may not be exercising what you think.
4. Repeat per behavior of the unit, prioritized by risk.

### Fixture discipline

- **Fresh fixture per test**: build shared setup in a `beforeEach` (setup phase), never in describe-scope shared state. A shared mutable fixture is "a petri dish primed for one of the nastiest bugs in testing" — tests interacting through it produce order-dependent, intermittent failures that at best cost long debugging and at worst collapse confidence in the suite. (JS trap: `const` freezes the reference, not the contents.) Fresh-fixture cost is usually unnoticeable; only consider sharing when it's truly immutable or provably never mutated.
- Test shape: **setup–exercise–verify** (aka given-when-then, arrange-act-assert), with an implicit **teardown** phase you get free from `beforeEach` re-creation.
- One verify per `it` block *as a general rule* — the test stops at the first failed assertion, hiding the rest of the diagnosis; multiple asserts acceptable when the characteristics are tightly coupled and you'd split on first failure.
- A visible `beforeEach` standard fixture tells the reader every test in the block starts from the same base data.

### What to test (risk-driven, not coverage-driven)

- "Test all the things the class *should do* and any conditions that might cause it to fail" — **not** every public method. Don't test simple accessors — you're hunting bugs, and there are none there.
- **Trying to write too many tests leads to writing not enough.** Concentrate on the areas you're most worried about; "it is better to write and run incomplete tests than not to run complete tests."
- **Probe the boundaries**: empty collections, zero, negative numbers, blank strings — actively "play the part of an enemy to my code." Boundary tests also surface domain questions (should negative demand even be legal? should the setter clamp or throw?) — writing them is how you discover the code's intended contract.
- Know the **failure vs. error** distinction: a *failure* is a verify step outside expected bounds; an *error* is an exception in an earlier phase (e.g., setup throwing `forEach is not a function`) — a condition the authors never anticipated. Decide explicitly: better error response, validation (only at trust boundaries — validating between modules of the same codebase duplicates checks and causes more trouble than it's worth), or leave-as-is.
- **Refactoring-scope rule**: behavior outside the observable contract (crash shape on invalid input nobody sends) is *not* something refactoring must preserve — discard such tests before refactoring, or use Introduce Assertion (302) to fail fast instead; don't write tests for assertion failures, assertions are themselves a form of test.
- **When you get a bug report, start by writing a unit test that exposes the bug** — then fix it; the test keeps the bug dead, and prompts "what other gaps does this reveal?"
- Test coverage tooling only identifies *untested areas*; it does not assess suite quality. The real measure is subjective: **how confident are you that if someone introduces a defect, some test will fail?** Enough confidence to refactor on green = good enough suite.
- Over-testing exists (sign: you spend more time changing tests than code, and the tests feel like drag) but is "vanishingly rare compared to under-testing." Don't let "testing can't catch all bugs" stop you from tests that catch most bugs.
- Test suites are iterated like production code: refactor them, improve clarity, add tests with every feature *and every bug*.

---

## ch-5 — Introducing the Catalog {#ch-5}

Entry format: **name** (+ former names/aliases — names are the shared vocabulary), sketch, **motivation** (why, and when *not*), **mechanics** (terse safe-step checklist — one workable path, not the only one; take larger steps when confident, drop back to baby steps the moment things get tricky), example. The catalog is a reference, not a reading list; page numbers in this file (e.g., "Extract Function (106)") are the book's cross-reference keys. Inverses exist for every refactoring but only interesting ones are cataloged.

---

## ch-6 — A First Set of Refactorings {#ch-6}

### Extract Function (106) *(formerly Extract Method; inverse: Inline Function)*

**Trigger**: you must spend effort figuring out *what* a fragment does — separation of **intention from implementation**. Not length, not reuse count: **semantic distance** between name and body. (Fowler habitually writes functions of a few lines; a one-line function with a better name than the code is fine — Smalltalk's `highlight` calling `reverse`.) A block-explaining comment is both the trigger and the name-donor.

Mechanics:
1. Create a new function named after *what* it does, not how. (Can't find a meaningful name → sign you shouldn't extract. Extracting, finding it doesn't help, and inlining back is not wasted time.)
2. If the language supports nested functions, nest it in the source first — kills variable plumbing; Move Function (198) later. But extract at least to sibling level before a planned move, so scope issues surface early.
3. Copy the code across; scan for source-local variables:
   - used but not assigned → parameters;
   - used only inside → move declaration inside;
   - one assigned-to variable → treat the extraction as a query, return it (name it `result`);
   - several assigned-to variables → **abandon**; first apply Split Variable (240) / Replace Temp with Query (178), then retry.
4. Compile/static-check; replace source fragment with a call; test.
5. Hunt other copies of the body → Replace Inline Code with Function Call (222).

**When not**: no better name exists than the code itself.
↔ contra *A Philosophy of Software Design* (same directory): Ousterhout warns that many tiny shallow functions raise interface overhead ("classitis"); Fowler's counter is that the split is justified only when the name closes a semantic gap — both agree a no-better-name extraction is bad.

### Inline Function (115) *(formerly Inline Method; inverse: Extract Function)*

**Trigger**: body reads as clearly as the name; needless indirection ("every function does simple delegation... I get lost in all the delegation"); or a badly factored cluster you want to collapse into one lump and re-extract along better lines (also the Shotgun Surgery tactic).

Mechanics:
1. Check it isn't a polymorphic method (subclass overrides → can't inline).
2. Find all callers; replace each call with the body, fitting variable names; test per replacement (gradual is fine).
3. Delete the definition.
4. If a replacement is tricky, go line-by-line with Move Statements to Callers (217); if tests break on a bold move, revert to green and redo smaller "with a touch of chagrin."

**When not**: recursion, multiple return points, no accessors in target context — "if you encounter these complexities, you shouldn't do this refactoring."

### Extract Variable (119) *(formerly Introduce Explaining Variable; inverse: Inline Variable)*

**Trigger**: a complex expression needs a name for a part of the logic; also gives a debugger/print hook.

Mechanics:
1. Ensure the expression has no side effects.
2. Declare an immutable variable set to a copy of the expression.
3. Replace occurrences one at a time; test after each.

Context test: if the name is meaningful beyond this function — especially inside a class — prefer Extract Function / a getter instead, so other code shares it (in a class this is nearly free). Canonical example: `price(order)` decomposed into `basePrice`, `quantityDiscount`, `shipping`; the routing comment deleted as redundant.

### Inline Variable (123) *(formerly Inline Temp)*

**Trigger**: the name says no more than the expression, or the temp blocks refactoring its neighbors.

Mechanics: check the RHS is side-effect-free → declare the variable immutable and test (proves single assignment) → replace references one at a time, testing → remove declaration and assignment.

### Change Function Declaration (124) *(aka Rename Function / Change Signature; formerly Rename Method, Add Parameter, Remove Parameter)*

Function declarations are "the joints in our software systems." A wrong name is never "only a name" — rename as soon as you understand a better one (trick: write the comment describing the function's purpose; turn it into the name). Parameters set a function's context and coupling: `formatPhoneNumber(person)` vs `(phoneNumber)` — narrower is more reusable, wider is more encapsulated against future data needs. **There is no right answer, especially over time** — this refactoring is how declarations evolve with understanding.

Simple mechanics (few, reachable callers; tool support):
1. If removing a parameter, check the body doesn't use it.
2. Change the declaration; update all callers; test.
3. Do rename and parameter changes as **separate steps**; on trouble, revert and switch to migration mechanics.

Migration mechanics (many/unreachable callers, polymorphic method, published API, complex change):
1. Refactor the body if needed to ease extraction.
2. Extract Function on the whole body under a searchable temp name (`zz_addReservation`, `xxNEW...`).
3. Add new parameters via simple mechanics; guard their use with **Introduce Assertion (302)** (e.g., `assert(isPriority === true || isPriority === false)`) so callers missed during migration fail fast.
4. Inline Function on the old function, one caller at a time, testing.
5. Rename the new function to the original name.
6. Polymorphic methods need forwarders per binding (superclass only, if hierarchy-linked). Published APIs pause at "both exist": deprecate old, retire when (if ever) clients migrate.

Micro-example (change a parameter to one of its properties, `inNewEngland(aCustomer)` → `(stateCode)`): Extract Variable on `aCustomer.address.state` → Extract Function → Inline Variable → Inline Function into callers → rename `xxNEW` back.

### Encapsulate Variable (132) *(formerly Self-Encapsulate Field, Encapsulate Field)*

**Why data is special**: functions can be moved by leaving a forwarding stub; data cannot — every reference must move in one atomic change, and difficulty scales with scope (globals are the extreme). So before moving or renaming widely used data, route all access through functions: reorganizing data becomes reorganizing functions. Encapsulation is also the hook for validation, derived logic, monitoring.

Mechanics:
1. Create getting/setting functions for the variable.
2. Replace each reference with the appropriate call; test after each.
3. Restrict the raw variable's visibility (own module exporting only accessors); if impossible, rename the variable (`privateOnly_defaultOwner`) to flush residual references.
4. Value is a record → consider Encapsulate Record (162).

Encapsulating the **value** (deeper than the reference): the basic move controls reassignment, not content mutation — either have the getter return a copy (`Object.assign({}, data)`; standard for lists) or wrap in a class controlling change. Caution: some clients may legitimately expect to mutate shared data — tests are the net.
Habits: all mutable data with scope beyond one function gets encapsulated; in legacy code, encapsulate whenever you must touch such a variable. Self-encapsulation (internal accessors within a class) is excessive except as a prelude to splitting the class. Immutable data needs almost none of this — "immutability is a powerful preservative."
Naming aside: never use the **Overloaded Getter Setter** convention (same name, arg-presence dispatch).

### Rename Variable (137)

Wide-scope variable → Encapsulate Variable (132) first, then rename inside the capsule. Constants (and const-like variables): copy under the new name (`const cpyNm = companyName`), migrate readers gradually, delete the old.

### Introduce Parameter Object (140)

**Trigger**: a data clump traveling through signatures. Grouping makes the relationship explicit, shrinks every signature, standardizes vocabulary — and, the deep payoff, creates a home that attracts behavior (`range.contains(x)` replacing scattered `x >= low && x <= high` — a Range object is born).

Mechanics:
1. Create the structure — prefer a **class** with value-object semantics over a bare record (behavior magnet).
2. Change Function Declaration (124) to add the object parameter; test.
3. Adjust callers to pass the instance; test each.
4. Replace uses of each original element parameter with fields of the object, removing the parameters one at a time.

### Combine Functions into Class (144)

**Trigger**: a group of functions operating on the same data (usually the same arguments passed around). A class gives shared context, shorter signatures, a findable home, and a fixed common state (the OO reading of partially applied functions).

Mechanics: Encapsulate Record (162) on the shared data → Move Function (198) each function into the class (common args become fields and leave the signatures) → Extract Function on remaining same-data logic and move it in too.
Choose vs. Transform (below): class when the source data is **updated** (methods recompute; no staleness) or when you want a reference other code can extend.

### Combine Functions into Transform (149)

Same trigger, functional alternative: one **transform** takes the source record and returns an enriched **deep copy** with derived fields added — every derivation findable and non-duplicated in one place.

Mechanics: create the transform returning a deep copy → move each derivation's body onto the copy as a new field, updating clients to read the field; test per derivation.
**Choose class instead when the source data is mutable/updated** — stored derived data goes stale. Works best when the enriched record stays effectively immutable downstream (and consider a test asserting non-mutation of the input).

### Split Phase (154)

**Trigger**: one block dealing with two different things — parse-then-process (compiler front/back ends), calculate-then-format — and you want to think about them separately, change them separately, maybe reuse one (ch-1: `createStatementData` feeding both text and HTML renderers).

Mechanics (work backwards from the output):
1. Extract Function on the second phase; test.
2. Introduce an **intermediate data structure** as an extra parameter to it; test.
3. For each remaining parameter of phase 2: if phase 1 produces/uses it, migrate it into the intermediate structure; test per move.
4. Extract Function on phase 1, returning the intermediate structure.

Result: `output = secondPhase(firstPhase(input))` — the intermediate structure makes the boundary explicit, and is the legitimate immutable Data Class of ch-3.

---

## ch-7 — Encapsulation {#ch-7}

Module decomposition = deciding which **secrets** modules hide (Parnas); data structures are the most common secrets.

### Encapsulate Record (162) *(formerly Replace Record with Data Class)*

Prefer objects over bare records **for mutable data**: the class hides what's stored vs. what's computed, and enables gradual field rename (methods for old and new name during migration). Immutable data can stay a record — copy/enrich freely. Hashmap-as-record is fine in a small scope, but its implicit structure (which fields exist? `start/end` or `start/length`?) becomes a liability as usage spreads — at that point make it a class rather than an explicit record.

Mechanics:
1. Encapsulate Variable (132) on the variable holding the record — give the raw accessor a deliberately ugly, searchable name (`getRawDataOfOrganization`): its life will be short.
2. Wrap the record in a simple class holding it; keep a raw-data accessor temporarily.
3. Provide functions returning the object; migrate users: **updaters to setters first** (the dangerous part), then readers to getters; test per user.
4. Delete the raw accessor and the searchable temp functions.
5. Recurse into nested structures (Encapsulate Record / Encapsulate Collection); for deep read access choose per case: return a copy (simple, maybe costly), purpose-built accessors (explicit, verbose), or wrapped objects.

### Encapsulate Collection (170)

A getter returning the raw collection lets any caller mutate it behind the class's back — encapsulating the field is not enough.

Mechanics:
1. Encapsulate Variable (132) if not already done.
2. Add `add`/`remove` methods on the owning class; route all external mutations through them (test per call site).
3. Remove Setting Method (331) if possible; a kept setter copies its input.
4. Change the getter to return a **copy** (usual for lists) or a read-only proxy; test.

**Pick one protection mechanism (copy vs. proxy) codebase-wide** for predictability.

### Replace Primitive with Object (174) *(formerly Replace Data Value with Object, Replace Type Code with Class)*

The moment you want any behavior beyond display on a primitive-typed domain value (validation, formatting, comparison — phone number, money, priority), wrap it in a value class. Starts embarrassingly small (constructor capturing the primitive + getter/`toString`) and pays compounding "second-order benefits" as behavior accretes.

Mechanics: Encapsulate Variable (132) → create the simple value class → setter wraps a new instance, getter delegates → test → Rename accessors to reflect meaning → decide identity semantics (Change Reference to Value 252 vs Change Value to Reference 256).

### Replace Temp with Query (178)

Temps are only reachable inside their function → they push functions long and block extraction. A query is callable from anywhere, kills the parameter-plumbing that blocks Extract Function, and avoids duplicated calculation logic. Works best inside a class (free shared context).

Mechanics:
1. Check the variable is computed once and only read after; make it read-only if possible; test.
2. Extract the assignment RHS into a function — must be side-effect-free (else Separate Query from Modifier 306 first) and return the same answer each call (deliberate snapshot temps don't qualify).
3. Inline Variable (123) to remove the temp.

### Extract Class (182) *(inverse: Inline Class)*

**Trigger**: class doing the work of two — a coherent sub-cluster of data + methods (shared name prefixes/suffixes; fields that change together; fields only sometimes used; subtyping that affects only some features).

Mechanics: decide the split → create the child class, link from parent's constructor → Move Field (207) one at a time, test each → Move Function (198), lowest-level first, test each → review and trim both interfaces, rename for the new shape → decide whether to expose the new object (and whether as a reference or a value).

### Inline Class (186) *(inverse: Extract Class)*

**Trigger**: a class no longer earning its keep after responsibilities drained away — or a deliberate prelude: fold two badly split classes into one, then re-extract along better lines.

Mechanics: create delegating methods on the absorber for the source's whole public API → repoint all references to the absorber, test each → move functions and data across, test each → delete the husk.

### Hide Delegate (189) *(inverse: Remove Middle Man)*

Client calls `server.department.manager` → the client is coupled to Department's existence and interface; a change there ripples to every navigating client. Add `server.manager` (delegating method) and the ripple stops at the server. Encapsulation = fewer things each client needs in its head.

Mechanics: for each delegate method clients use, create a forwarding method on the server → migrate clients, test per change → if nothing external needs the delegate anymore, remove the server's delegate accessor.

### Remove Middle Man (192) *(inverse: Hide Delegate)*

When the server is mostly forwarding methods (half its interface delegates), let clients talk to the delegate directly.

Mechanics: add a getter for the delegate → per delegating method, repoint callers to the chained call (`server.department.manager`), test per method → delete the forwarders.
No fixed right ratio: the Hide Delegate/Remove Middle Man pair is a dial you re-tune as the system changes — "an amount of hiding that was comfortable yesterday may be uncomfortable today," and refactoring means never having to say you're sorry.

### Substitute Algorithm (195)

Found a clearer way — or a library — that produces the same result; or you must vary the algorithm and want to replace it with something easier to change first.

Mechanics:
1. Arrange the code so the algorithm to replace fills one whole function.
2. Have tests capturing its behavior (this is where characterization tests shine).
3. Prepare the alternative; run the tests against it; failing cases → old implementation is your comparison oracle.

Decompose to the smallest replaceable unit before substituting something big; this move requires a wholesale-replacement mindset rather than small steps, so keep the unit small.

---

## ch-8 — Moving Features {#ch-8}

### Move Function (198) *(formerly Move Method)*

Modularity = the ability to modify a program while understanding only a small part of it; as your understanding of good grouping improves, elements must move. Triggers: function references more elements of another context than its own (Feature Envy); its callers live elsewhere; a nested helper deserves independent visibility (nested functions breed hidden data interrelationships); you'll need it elsewhere for the next enhancement.

Deciding is hard — examine what calls it, what it calls, what data it uses; sometimes the answer is a new context (Combine Functions into Class 144 / Extract Class 182). But "the more difficult this choice, often the less it matters" — pick one, learn from living with it, move again if wrong.

Mechanics:
1. Look at the elements it uses in its current context — move tightly bound dependents first (least-dependent function of the cluster leads); a sole-caller helper cluster can be inlined, moved, re-extracted.
2. Check for polymorphism (super/subclass declarations).
3. **Copy** to the target; adjust the body — pass source data as parameters or pass a source-context reference; often rename for the new home.
4. Static-check; make the source a delegating stub pointing at the target; test.
5. Consider Inline Function (115) on the stub — it can stay indefinitely, but if callers can reach the target easily, remove the middle man.

### Move Field (207)

Triggers: pieces of data always passed together belong in one record; a field that changes whenever a *different* record changes is in the wrong place; the same fact updated in multiple structures should live once. Fowler: choosing the right data structures is primary — "if you have good data structures, your behavior code becomes simple and straightforward"; expect early choices to be wrong and move fields as domain understanding deepens.

Mechanics:
1. Encapsulate Variable (132) on the source field — always; data moves are riskier than function moves. Test.
2. Create the field + accessors on the target.
3. Ensure a source→target reference path exists (existing field or method; create one if needed — possibly a temporary one).
4. Point the source accessors at the target's field; test.
5. Remove the source field; test.

Shared-target variant (many sources → one canonical): dual-write in the setter with an **Introduce Assertion (302)** comparing both copies during the soak; once quiet, cut reads over and drop the source field.

### Move Statements into Function (213) / Move Statements to Callers (217)

Inverse pair for shifting a function's boundary as understanding changes.
- **Into (213)**: statements duplicated adjacent to every call of a function belong inside it — test: can you imagine ever calling the function *without* those statements? No → move them in. (If they don't fully belong, maybe extract statements+call into a new enclosing function instead.)
- **To Callers (217)**: behavior that now must vary per call site moves out of the shared function.

Mechanics (both, non-trivial cases): Slide Statements (223) until the moving code is adjacent to the boundary → Extract Function on what should remain (or on call+statements, for Into) under a temp name → Inline Function on the old function one caller at a time → Rename to the final name. Simple cases are just cut/paste of edge lines with a test.

### Replace Inline Code with Function Call (222)

Inline code does what an existing function does → replace with the call; test. Functions with good names dedupe by *meaning*, not just text.
**Unless the similarity is coincidental** — ask: if the function's body changed, should this inline code change too? No → don't call it (the function's name is the guide; a library function is always safe to prefer).

### Slide Statements (223) *(formerly Consolidate Duplicate Conditional Fragments)*

Related code belongs together; declare variables just before first use — mostly as *preparation* for Extract Function.

Interference analysis (a slide is invalid if):
- the fragment slides backward over a declaration it references;
- forward over a statement that references it;
- the fragment *modifies* an element that the skipped-over code references, or vice versa (moving a modifying fragment past any reference to the same element is the general danger).

Mechanics: identify the target position → check interference → cut, paste, test; on failure, break into smaller slides. Commutative-in-principle side effects (two appends to independent state) are slideable if code honors command-query separation — when in doubt, don't.
Conditionals: sliding duplicate leg-tails *out* of the conditional removes duplication; sliding code *in* duplicates it into each leg (legitimate as an intermediate step).

### Split Loop (227)

A loop doing two things forces you to understand both on every edit; one loop per concern, and each split loop usually becomes an Extract Function target (splitting also frees a loop that computed two values to return one value cleanly instead of smuggling a structure).

Mechanics: copy the whole loop → delete the duplicated side effects (one concern per copy), test → Extract Function each loop.
Performance: two passes over a list is almost never the bottleneck — "refactoring is separate from optimization"; if profiling later says merge, merging split loops back is easy.

### Replace Loop with Pipeline (231)

Collection pipelines (filter/map/reduce) read top-to-bottom as a declarative flow of collection states — "the anachronism of loops": you see immediately which elements are included and what's done with them.

Mechanics: capture the source collection in a variable → peel loop behaviors one at a time, top-down, into pipeline stages appended to that variable, testing each → when the loop body is empty, delete the loop and assign the pipeline result.

### Remove Dead Code (237)

Unused code costs every reader who must work out why it's there and whether it matters. Delete it — **version control remembers**; don't comment it out (that habit predates reliable VCS). Speculative "we may need it" code fails YAGNI the same way. If unsure about external references, search for callers first; then delete and test.

---

## ch-9 — Organizing Data {#ch-9}

### Split Variable (240) *(formerly Remove Assignments to Parameters / Split Temp)*

A non-loop, non-collecting variable assigned more than once carries more than one responsibility — "using a variable for two different things is very confusing for the reader."

Mechanics:
1. Rename the variable at its declaration and first assignment; declare the new name `const`/immutable if possible.
2. Retarget references up to the second assignment; test.
3. Repeat at each subsequent assignment boundary until every responsibility has its own (ideally single-assignment) variable, testing per stage.

Legit multi-assignment (exempt): loop variables; collecting variables (sum accumulators, string builds, collection appends).
Special case: **assignment to an input parameter** — split immediately into `let result = inputParam;` (also defuses pass-by-value vs. by-reference confusion).

### Rename Field (244)

Field names of record structures are load-bearing across the program — they're vocabulary. Small scope: just rename everything and test. Wide scope:
1. Encapsulate Record (162) if the record isn't already a class.
2. Rename the private field inside the object; fix internal methods.
3. Constructor uses the old name → Change Function Declaration (124); accessors → Rename Function.

Migration trick for gradual cutover: constructor temporarily accepts both keys (`data.title !== undefined ? data.title : data.name`), migrate callers one at a time, drop the old key support.

### Replace Derived Variable with Query (248)

Mutable derived data can drift from its source, hides an invariant, and widens the mutation surface for no reason ("we spray it with a concentrated solution of vinegar"). Compute on demand.

Mechanics:
1. Identify every update point of the variable (Split Variable 240 first if it has multiple sources).
2. Write the calculating function.
3. **Introduce Assertion (302)**: assert stored == calculated at read time during the transition.
4. Swap reads to the query; test; delete the variable and its updates.

Exemption: source data immutable + derivation set-once → the stored copy can't drift; keeping it is fine.
Accumulator-with-initial-value variant: Split Variable first (`_initialValue` vs adjustments), then replace only the derived accumulation.

### Change Reference to Value (252) / Change Value to Reference (256)

Inverse pair; choose deliberately by update semantics.

**To Value (252)**: treat the inner object as immutable — update by wholesale replacement. Value objects can be copied and shared fearlessly and shine in distributed/concurrent designs. Mechanics: verify/make the class immutable → Remove Setting Method (331) on each setter (host setters replace the whole object: `new TelephoneNumber(...)`) → implement value-based equality (`equals` + hash). **Don't** when collaborators must *see* updates to a shared entity — then it's a reference.

**To Reference (256)**: N copies of one logical entity = N places to update consistently (and a subtle bug when only one copy gets the update). Share one instance. Mechanics: create a **repository/registry** for canonical instances → ensure constructors can look up the right one → change host constructors to fetch from the repository instead of constructing; test each. Cost: something must own the lookup table — a global registry carries all the ch-3 Global Data caveats; consider passing the repository in.

---

## ch-10 — Simplifying Conditional Logic {#ch-10}

### Decompose Conditional (260)

Conditionals tell you *what* happens but obscure *why*. "Just Extract Function applied to conditionals," flagged separately because the value per effort is remarkably high.

Mechanics: Extract Function (106) on the condition (`summer()`), then on the then-leg (`summerCharge()`), then on the else-leg (`regularCharge()`); often finish as a ternary of named calls.

### Consolidate Conditional Expression (263)

Several checks with the same result *and the same reason* are really one check — combining says so, and sets up Extract Function on the compound (`isNotEligibleForDisability()`).

Mechanics: verify the conditions are side-effect-free (else Separate Query from Modifier 306 first) → combine pairwise: sequential ifs with `||`, nested ifs with `&&`; test per combination → Extract Function on the result.
**Don't** consolidate checks you consider genuinely independent — consolidation is a statement of intent, not just dedup.

### Replace Nested Conditional with Guard Clauses (266)

Two kinds of conditional: two legitimate branches (if/else — equal weight is honest) vs. **normal path + unusual conditions**. For the latter, check the unusual condition and return early (**guard clause**): "this is not the core case — deal with it and get out." Kills the arrow-shape of nested ifs and marks which path matters.

Mechanics: take the outermost condition that should be a guard, convert to guard-and-return, test; repeat inward; Consolidate Conditional Expression (263) on guards returning the same result. Variant: when conditions are phrased positively and nested, *reverse/negate* them into guards (mind De Morgan on the compounds).
Explicitly rejects single-exit-point dogma: "one exit point is really not a useful rule. Clarity is the key principle: if the function is clearer with one exit point, use one; otherwise don't."

### Replace Conditional with Polymorphism (272)

When the *same* set of conditions reappears across several functions (repeated switch on a type code), lift the cases into classes: each switch leg becomes a subclass override, the dispatch happens once in a factory.

Two shapes:
- **Flat cases**: each type is its own logic (ch-1's tragedy/comedy calculators) — superclass method throws "subclass responsibility" or holds the default once all legs move.
- **Base-and-variation**: superclass carries the normal case; the subclass overrides only where the variant differs (voyage-rating example: `ExperiencedChinaRating` extends the base rating), using `super` calls or extension hooks for "and-then" modifications.

Mechanics: create the hierarchy + factory function (Replace Constructor with Factory Function 334) → route all construction through the factory → move the conditional function to the superclass (Extract Function first if not self-contained) → per subclass: create the override, copy that leg's body, adjust, test → delete each migrated leg from the superclass switch → make the base method default/abstract/throw.

Do **not** treat every conditional this way: "most of my conditional logic uses basic conditional statements... polymorphism only when the conditional logic is duplicated."

### Introduce Special Case (289) *(formerly Introduce Null Object)*

Many call sites checking the same special value (`null` customer, `"unknown"`) and reacting the same way → one **special-case object** carrying the common responses; the checks collapse into ordinary dispatch.

Three implementation forms:
1. **Class** (`UnknownCustomer` with default `name`, billing plan, payment-history stubs) — when behavior is needed.
2. **Literal object** (frozen `{isUnknown: true, name: "occupant", ...}`) — read-only usage.
3. **Transform** — enrich records with the special-case defaults in a pipeline step.

Mechanics (class form): add `isUnknown → false` on the real class → special-case class with `isUnknown → true` → **Extract Function on the comparison** (`isUnknown(arg)`) so all call sites funnel through one point → make the data source return the special case instead of the sentinel → switch the comparison to the property → Combine Functions into Class (144) to migrate the common default responses into the special case, test per behavior → Inline Function the comparison where it's no longer needed.

Rules: special-case objects must be **immutable**; a client needing *different* special-case behavior keeps its own check (only shared responses move in); nested special properties become special cases of their own (unknown customer's null payment history).

### Introduce Assertion (302)

Make buried assumptions explicit: an assertion states a condition the code **assumes always true**, communicating it to readers and failing fast in development. Program correctness must never depend on assertions — removing them all must leave behavior unchanged (some environments compile them out).

Mechanics: when a condition is assumed true, add the assertion — preferably **at the setting site**, not the usage site (a failed use-site assertion still leaves you hunting the bad write); dedupe repeated assumed expressions with Extract Function first.

**Not** for external-input validation (that's error handling, always on) — only for programmer-error invariants. Don't blanket-assert everything you believe true — only what *must* be true; over-asserted code buries the signal. Also a migration power-tool (dual-write equality in Move Field, new-parameter presence in Change Function Declaration) and a fail-fast alternative to testing unobservable error behavior (ch-4).

---

## ch-11 — Refactoring APIs {#ch-11}

APIs are the joints between modules; you learn better joints only by use, so keep refactoring them.

### Separate Query from Modifier (306)

**Command-query separation**: any function that returns a value should have no *observable* side effects — then you can call it freely, move it, and test it without worry. (Cache fills are unobservable: repeated queries still agree.) Fowler: not 100% pure on the rule, "but I try to follow it most of the time, and it has served me well."

Mechanics:
1. Copy the function; name the copy for the query (the variable it populates in callers is a naming clue).
2. Strip side effects from the query; static-check.
3. Callers using the return value → replace with `query()` then `modifier()`; test per caller.
4. Remove the modifier's return value; test; dedupe (modifier calls the query).

Signal example: `alertForMiscreant(people)` returning the found name → `findMiscreant` (query) + `alertForMiscreant` (modifier calling it).

### Parameterize Function (310) *(formerly Parameterize Method)*

Near-identical functions differing only in literal values → one function taking the value(s) as parameters — less duplication, more reach.

Mechanics: pick one of the similar functions → Change Function Declaration (124) to add the literal as a parameter, updating its callers to pass it → replace body literals with the parameter, testing → repoint calls to each sibling function, testing each. Range trick: refactor from the *middle* case (`middleBand(usage)` references both bounds); the edge functions become calls passing `0`/`Infinity`.

### Remove Flag Argument (314) *(formerly Replace Parameter with Explicit Methods)*

A **flag argument** = the caller sets a literal (usually boolean) telling the callee which behavior to run. It hides the behavioral variety from the function list, forces readers to decode `bookConcert(customer, false)`, and boolean flags are the worst — the call site says nothing. Explicit functions also help static analysis.

Mechanics:
- Flag gates a top-level dispatch → Decompose Conditional (260); one explicit function per flag value; migrate literal-passing callers; retire the original.
- Flag threads through tangled logic → thin wrappers: `function rushDelivery(o) { return deliveryDate(o, true); }`; migrate callers; demote/rename the flagged original as internal.

*Not* a flag if the value flows in as **data** (the caller isn't passing a literal) — then leave it. Multiple toggles on one function → wrappers explode combinatorially, which itself signals the function does too much.

### Preserve Whole Object (319)

A caller derives several values from one object just to pass them separately → pass the object. Shorter signatures; the callee can take more from the object later without signature churn; and it flushes out Feature Envy — logic that unpacks an object often belongs *on* that object (follow with Move Function). An object passing several of **its own** fields → consider passing `this`.

Mechanics: create an empty function with the desired signature under an easily-replaced name (`xxNEW...`) → body = call to the old function, mapping parameters → migrate callers, test each → Inline Function the old one; rename. Pure-refactoring variant: Extract Variable on the parts + Extract Function in a caller builds the new function without hand-writing it.

**When not**: you *want* the callee decoupled from the object's module — dependency direction beats signature brevity.

### Replace Parameter with Query (324) / Replace Query with Parameter (327)

Inverse pair; the tension is **who should know what**.

**Param→Query (324)**: if the callee can determine a value itself, the parameter is duplicate knowledge and caller burden. Safest case: derivable from another parameter. Mechanics: Extract Function on the derivation if needed → replace in-body references to the parameter with the derivation → Change Function Declaration to drop it. **Don't** if resolution adds an unwanted dependency to the callee or destroys referential transparency (never replace a parameter with mutable-global access).

**Query→Param (327)**: an internal reference (global, mutable shared state, wrong-direction dependency) hoisted into a parameter, creating a referentially transparent core (same args → same result — "easier to test and reason about") wrapped by an impure shell. Mechanics: Extract Variable on the query result → Extract Function on the body minus the query (`xxNEW`) → inline the variable, then the old function into callers → rename. Cost: every caller gets more complex — a design tradeoff about responsibility placement, "not one I can give crisp advice on."

### Remove Setting Method (331)

A setter advertises post-construction mutability; if the field should be fixed at creation, the setter is a lie. Two common cases: the setter is only called from the constructor path anyway; or the object is built by a creation script (constructor + setter chain) and frozen afterwards.

Mechanics: get the value into the constructor (Change Function Declaration 124) if not there → replace each external setter call with constructor supply, testing (can't? — shared-reference update — abandon) → Inline Function the setter; declare the field immutable if the language can.
Common flush: JSON round-trip code writing fields it shouldn't.

### Replace Constructor with Factory Function (334) *(formerly Replace Constructor with Factory Method)*

Constructors are constrained: must return an instance of their own class (no subclass or proxy substitution), name fixed to the class (can't say *intent*), require `new`, awkward in dynamic contexts. A factory function has none of those limits.

Mechanics: write the factory (body = constructor call) → migrate constructor callers one at a time, testing → restrict constructor visibility as far as possible.
Variant: per-type named factories (`createEngineer(name)`) instead of passing type-code string literals through one general door.

### Replace Function with Command (337) / Replace Command with Function (344)

A **command object** (command *pattern* — not the CQS sense; Fowler says "command object" then "command") wraps a function as an object whose fields are its parameters and local variables.

Buys: undo/complementary operations; a rich parameter-building lifecycle (constructor args preferred, execute() taking none — commands with different parameters then queue uniformly); inheritance + hook customization; and above all **decomposing a function too tangled for Extract Function** — locals become fields, so sub-extractions stop fighting variable scope (the answer when nested functions aren't available or aren't enough; e.g., a 10-branch `score()` decomposed via `new Scorer(candidate, medicalExam).execute()`).

Price: complexity. **"Given the choice between a first-class function and a command, I'll pick the function 95% of the time"** — use a command only when you specifically need a facility simpler approaches can't provide.

Mechanics (337): empty class named for the function → Move Function (198) the body into `execute()`, keep the original as forwarder → parameters → constructor fields → each local variable → field (test per conversion) → now Extract Function freely inside the class.
Inverse (344): flexibility no longer earning its keep → Extract Function around create+execute → Inline Function each supporting method into execute → Change Function Declaration to move constructor params onto execute → replace field reads with parameters, test → inline constructor+execute into the wrapper → Remove Dead Code (237) the class.

---

## ch-12 — Dealing with Inheritance {#ch-12}

Inheritance is very useful *and* easy to misuse — and the misuse is often visible only in the rear-view mirror; hence both directions of every move below.

### Pull Up Method (350) / Pull Up Field (353) / Pull Up Constructor Body (355)

Duplicate members in sibling subclasses = divergence risk — "nothing but a breeding ground for bugs in the future."

Pull Up Method mechanics:
1. Inspect the sibling methods: if they do the same thing but differ textually, refactor until the bodies are identical — the differences you find are frequently untested behavior.
2. Verify every feature the body references is reachable from the superclass; Pull Up Field / Pull Up Method those first. If the pulled-up body calls something only subclasses provide, declare a trap on the superclass (`throw new SubclassResponsibilityError()`).
3. Different signatures → Change Function Declaration (124) to the one the superclass will carry.
4. Copy one body into the superclass; static-check; delete one subclass method; test; repeat deletions.

Two similar-but-parameterizable methods → Parameterize Function (310) first, then pull up. Similar flow, differing details → Form Template Method.
Pull Up Field: check the sibling fields are used the same way; rename to match (244); declare in superclass (protected in static languages); delete subclass fields; test. Beyond data dedup, it lets field-using behavior be pulled up next.
Pull Up Constructor Body: constructors' fixed call order makes them awkward — define/ensure the super constructor; Slide Statements (223) to position common statements right after `super(...)`; move them into the superclass constructor, passing referenced values as parameters; if the common code can't be front-positioned, Extract Function + Pull Up Method instead.

### Push Down Method (359) / Push Down Field (361)

A member only one subclass cares about moves out of the superclass into it — the superclass API stops advertising things most children don't do. Valid only when callers know they're dealing with that subclass (else the move breaks them, and you likely need Replace Conditional with Polymorphism instead). Mechanics: copy into every subclass that needs it → remove from superclass → test → remove from subclasses that don't need it → test.

### Replace Type Code with Subclasses (362) *(subsumes Extract Subclass, Replace Type Code with State/Strategy; inverse: Remove Subclass)*

A type-code field (`"engineer" | "manager"`) earns subclasses when: (a) several functions switch on it → sets up Replace Conditional with Polymorphism (272); or (b) some fields/methods are valid only for some codes → Push Down Field/Method makes the constraint explicit in the structure.

Two shapes:
- **Direct**: `Engineer extends Employee`. Simple; but consumes the class's single inheritance slot, and the kind is fixed at construction.
- **Indirect**: Replace Primitive with Object (174) on the code, then subclass the *type object* (`EmployeeType` → `Engineer`). The employee's kind can change at runtime, the inheritance slot stays free, and type-specific behavior migrates onto the type classes (moving it there is straightforward with Move Function).

Mechanics (direct): self-encapsulate the type code with a getter → create one subclass overriding the getter with its literal → Replace Constructor with Factory Function (334), selector logic in the factory → test; repeat per code → remove the type-code field → Push Down Method + Replace Conditional with Polymorphism on the code-switching functions.

### Remove Subclass (369) *(formerly Replace Subclass with Fields; inverse: Replace Type Code with Subclasses)*

Subclasses that do too little (differ in one getter's return value) cost more — a reader's comprehension budget and an occupied variation axis — than they deliver, especially as understanding shifts after the design was minted. Replace with a field.

Mechanics: Replace Constructor with Factory Function (334), selector logic into the factory → Extract Function + Move Function on any type-probing checks (`instanceof`-alikes) so the probe lives on the superclass → add the representing field → retarget the subclass-differing methods onto the field → delete the subclass; test. Usually done in batch across a sibling group.

### Extract Superclass (375)

Two classes doing similar things → a superclass hosting the shared data (Pull Up Field) and behavior (Pull Up Method / Pull Up Constructor Body). Trigger is duplication discovered during evolution, not up-front taxonomy. Alternative is Extract Class (182) (delegation) — extracting the superclass is usually simpler; if it proves wrong, Replace Superclass with Delegate (399) later.

Mechanics: empty superclass, both originals extend it → adjust constructors (124) → pull members up one at a time, testing (near-identical methods: Extract Function on the common parts first) → examine clients; point them at the superclass interface where possible.

### Collapse Hierarchy (380)

Parent and child no longer different enough to justify two classes → merge. Pick the survivor by which *name* serves the future; pull up / push down everything; retarget references; delete the empty class; test.

### Replace Subclass with Delegate (381)

Inheritance's two structural limits: it gives you exactly **one axis of variation** (subclass people by age category *or* income level, not both), and the parent-child relationship is **compile-time fixed and tightly coupled** (changes ripple; an object can't change category at runtime — no `bePremium()` on a subclass-based design). Delegation fixes both: composition, a host field pointing at a delegate that carries the variant behavior with a back-reference to the host.

Book's reading of GoF "favor object composition over class inheritance": composition ≈ delegation here, and the real advice is **"favor a judicious mixture"** — inheritance first (cheap, visible, tool-supported), migrate to delegation when it rubs.

Mechanics skeleton:
1. Replace Constructor with Factory Function (334) if constructors are called widely.
2. Empty delegate class: constructor takes subclass-specific data + host back-reference; host gets a delegate field, populated by the factory for the variant case.
3. Per subclass method: Move Function into the delegate (leave a subclass forwarder), then lift the forwarder to the host as a dispatch: `return this._premiumDelegate ? this._premiumDelegate.x() : <default>` — test each.
4. Subclass-only methods: host dispatches or returns `undefined`.
5. All moved → factory returns the host type; delete the subclass.

`super.method()` calls inside moved code become either delegate calls back into host internals (`this._host._basePrice...`) or the **extension pattern**: host computes the base result and passes it to `delegate.extendX(base)`.
Whole-hierarchy variant: build a parallel delegate hierarchy (`SpeciesDelegate` base via Extract Superclass holding the default behavior) and give **every** host a delegate (default delegate class) — the dispatch guards disappear and host methods become plain forwards.

### Replace Superclass with Delegate (399) *(formerly Replace Inheritance with Delegation)*

Subclassing is wrong when the "subclass" doesn't use or honor the whole superclass interface, or isn't a subtype in every context. Canonical horrors: **Stack extends List** (most of List's API makes no sense on a stack — it should have a List field instead); the **type-instance homonym** — Scrolls extends CatalogItem because a scroll "is an" item of its catalog entry: two different senses of the word ("my car is a Bugatti Veyron" vs "this model is a Bugatti Veyron") welded into one hierarchy, which breaks the moment instances need their own lifecycle (dates, ids).

Mechanics: create a field in the ex-subclass holding a superclass instance → per used superclass function, add a forwarding method, migrating in consistent groups (get/set pairs together), testing per group → remove the inheritance link → test. Follow-on: if the superclass data was per-instance-copied but is logically shared (catalog entries), Change Value to Reference (256) with a repository.

Consequences to accept: no more inherited dispatch — ex-superclass logic can't invoke ex-subclass overrides (template hooks must become explicit delegate calls); every exposed operation needs a forwarder (boring, but mercifully hard to get wrong).
Position: **not** "never inherit" — when the subtype relation genuinely holds, inheritance is the simpler mechanism and this refactoring is your escape hatch later; "use inheritance first, replace when (and if) it becomes a problem."

---

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| About to add a feature to code whose structure makes it awkward | Refactor first so the feature becomes easy, then add it (preparatory refactoring) | make-the-change-easy then make-the-easy-change is usually the fastest total path | ch-2 |
| A diff both restructures and changes behavior | Split the work: wear one hat at a time | mixed edits make failures undiagnosable and reviews unverifiable | ch-2 |
| Planning a refactor on code with no fast self-checking tests | Stop; build characterization tests (or restrict to tool-safe automated refactorings) | mistakes are inevitable; only fast tests make them cheap | ch-2, ch-4 |
| A refactoring "will take a couple of days" with the code broken meanwhile | That's not refactoring — recompose into small always-green steps | behavior-preserving small steps allow stopping at any moment | ch-2 |
| Test fails mid-refactor, cause not instantly visible | Revert to last green commit; redo in smaller steps | debugging a composite change costs more than redoing it | ch-1 |
| Each small refactoring step passes tests | Commit immediately (private/local), squash later | cheap restore points are what make tiny steps fast | ch-1 |
| Urge to write a comment explaining what a block does | Extract the block into a function named for the intent | the name persists understanding; the comment rots | ch-3, ch-6 |
| Extraction candidate has no better name than the code itself | Don't extract (or inline an extraction that didn't help) | indirection without a semantic-gap payoff is pure cost | ch-6 |
| Extraction blocked by too many temps/params | Remove locals first: Replace Temp with Query, Split Variable, Introduce Parameter Object; heavy artillery: Replace Function with Command | fewer names in scope = clean extraction seams | ch-1, ch-3, ch-6 |
| Same 3–4 values travel together in fields/signatures | Introduce Parameter Object / Extract Class; prefer a class over a record | the clump is an object waiting to attract behavior | ch-3, ch-6 |
| Same switch on the same condition in ≥2 places | Replace Conditional with Polymorphism (classes + factory) | every new case currently requires finding all copies | ch-3, ch-10 |
| A single, non-repeated switch | Leave it — plain conditionals are fine | polymorphism buys nothing without duplication | ch-3, ch-10 |
| Boolean/enum literal at call sites selecting callee behavior | Remove Flag Argument: one explicit function per mode | `f(x, false)` hides the API's real shape from callers and analyzers | ch-11 |
| Function returns a value **and** has observable side effects | Separate Query from Modifier (CQS) | pure queries can be called/moved/tested freely; cache-filling doesn't count as observable | ch-11 |
| Caller unpacks an object just to pass its parts | Preserve Whole Object — unless it would couple the callee to a module it must not see | future data needs stop being signature changes; unpacking logic often signals Feature Envy | ch-11 |
| Parameter derivable from another parameter | Replace Parameter with Query | duplicate knowledge in the signature invites inconsistent calls | ch-11 |
| Callee reads a mutable global / wrong-direction dependency internally | Replace Query with Parameter to restore referential transparency | pure core + impure shell is easier to test and reason about | ch-11 |
| Field never legitimately changes after construction | Remove Setting Method; set in constructor | a setter is a public claim of mutability | ch-11 |
| Mutable field is computable from other data | Replace Derived Variable with Query (assert stored==computed during migration) | stored derived data drifts; queries can't | ch-9 |
| Non-loop variable assigned more than once | Split Variable — one responsibility per variable | multi-purpose temps confuse readers and block extraction | ch-9 |
| Assignment to an input parameter | Split into `result` variable immediately | parameter mutation confuses by-value/by-reference expectations | ch-9 |
| Getter returns a raw mutable collection | Encapsulate Collection: add/remove methods + copy or read-only view, one mechanism codebase-wide | callers can otherwise mutate owner state invisibly | ch-7 |
| Widely-accessed mutable data needs rename/move | Encapsulate Variable first; then it's a function-reorg problem | data has no forwarding stubs; functions do | ch-6 |
| Domain concept represented as int/string acquiring behavior | Replace Primitive with Object | "stringly typed" values scatter validation/formatting | ch-3, ch-7 |
| Nested conditionals where some branches are early-exit conditions | Replace Nested Conditional with Guard Clauses; ignore single-exit dogma | guards mark "not the core case"; nesting claims equal weight falsely | ch-10 |
| Same special-value check (null/"unknown") with same response at many sites | Introduce Special Case object (immutable) | dispatch replaces N duplicated conditionals | ch-10 |
| Invariant the code silently assumes | Introduce Assertion at the *setting* site; never for external input; behavior must not depend on it | assumptions become visible and fail fast | ch-10 |
| Renaming/changing a signature with many, unreachable, or polymorphic callers | Use migration mechanics: extract new under temp name, inline old caller-by-caller, deprecate published old | atomic rename is only safe when you own every caller | ch-6 |
| Changing a published API | Keep old declaration as forwarder + deprecate; retire only when clients migrate | you can't see, let alone edit, external callers | ch-2, ch-6 |
| DB schema change | Expand-contract across releases: add new, dual-write, migrate readers, soak, drop old; migration script versioned with code | multi-release parallel change keeps every step reversible | ch-2 |
| Long-lived feature branches on a refactoring team | Integrate with mainline at least daily (CI/trunk-based) | semantic merge conflicts grow exponentially with branch age and kill refactoring | ch-2 |
| Duplicate methods in sibling subclasses | Pull Up Method (make identical first; differences are often untested behavior) | copies diverge silently | ch-12 |
| Subclass exists only to vary one value | Remove Subclass, use a field | a class per constant is complexity without behavior | ch-12 |
| Hierarchy needs a second variation axis, runtime category change, or parent-child coupling hurts | Replace Subclass with Delegate | inheritance gives you exactly one, static axis | ch-12 |
| "Subclass" ignores or breaks parts of the superclass interface (Stack extends List; type-instance homonym) | Replace Superclass with Delegate; forward only what makes sense | non-subtype inheritance exports a lying API | ch-12 |
| Code only referenced by its own tests | Delete test and code (Remove Dead Code) | version control remembers; readers pay for corpses | ch-3, ch-8 |
| Performance objection raised against a proposed refactoring | Proceed; profile-then-tune afterward on the well-factored result (exception: hard real-time time-budgeted systems) | hot spots are few; intuition about them is usually wrong | ch-1, ch-2 |
| New test written | Watch it fail once (inject a fault, revert) | a never-failed test may assert nothing | ch-4 |
| Test fixture created in shared/describe scope and mutated by tests | Rebuild per test (beforeEach) | shared-fixture interaction = order-dependent intermittent failures | ch-4 |
| Bug report arrives | Write the unit test that exposes it before fixing | the test keeps the bug dead and maps suite gaps | ch-4 |

---

## Anti-patterns

Process anti-patterns the book names or warns against (each with its detection cue):

- **Big-bang cleanup** — "let's schedule weeks of refactoring" for a legacy mess. Cue: dedicated refactoring epics with the code broken in between. Do camp-site improvement in the areas you actually visit; planned refactoring episodes should be rare.
- **Moral justification** — selling refactoring as "clean code"/"good engineering practice"/craftsmanship. Cue: quality arguments with no economic content. The justification is speed of future change; anything else invites (justified) pushback.
- **Refactoring on a red bar** — restructuring while the suite is failing. Cue: refactor commits with failing CI. Fix or revert to green first.
- **Shared mutable test fixture** — fixture built once at suite scope. Cue: outer-scope `const fixture` + tests that pass alone but fail in combination / by order. (JS: `const` doesn't freeze contents.)
- **Coverage worship** — using test-coverage % as the quality target. Cue: coverage gates without a confidence argument. Coverage only locates *untested* code; the target is "a defect would make some test fail."
- **Flexibility mechanisms on spec** — parameters/hooks/abstract layers for anticipated needs. Cue: config nobody sets, params with one caller value, abstract classes with one subclass. Add flexibility only when refactoring it in later would be substantially harder.
- **Constant-attention performance tuning** — micro-optimizing everything while writing. Cue: "faster" idioms replacing clear code outside any profiled hot spot; ~90% of that work is wasted on cold code.
- **Comment as deodorant** — commenting around a smell instead of removing it. Cue: block comments narrating steps of a long function.
- **Strong fine-grained code ownership** — per-file/per-person write locks. Cue: forwarding-stub gymnastics between three people on one team. Prefer team ownership.
- **Long-lived feature branches** — cue: branch age in weeks; teams that "stopped refactoring because merges hurt."
- **Overloaded Getter Setter** — same function name for get and set distinguished by argument presence. Fowler: strongly dislikes; keep `set` prefix.
- **Flag argument** — see ch-11; the call-site literal `true` is the cue.
- **Type-instance homonym inheritance** — subclassing to borrow a word's other meaning (CarModel extends Vehicle). Cue: "is-a" holds in English but not in the API.

---

## Applicability & exemptions

When the book's own advice does **not** apply — read before firing any rule above:

- **Don't refactor code you don't need to change or understand.** Ugly-but-working code treatable as an opaque API can stay ugly indefinitely. Refactoring pays only at the point of needing to understand/modify.
- **Rewrite can beat refactor.** A legitimate alternative; usually discoverable only by attempting the refactor for a while. No simple rule exists — the book explicitly declines to give one.
- **Trivial change vs. big refactoring**: adding a small feature and skipping a large adjacent refactoring is a professional judgment call, weighted by visit frequency ("I'm more likely not to refactor code I rarely touch").
- **No tests + no tool support**: full-menu refactoring is unsafe. Options: characterization tests first (ch-4), tool-automated-safe subset only, or Feathers-style seam work (accepting bounded untested risk). This is a precondition, not an exemption to ignore.
- **Smell-specific false-positive guards**:
  - Single (non-repeated) switch statements are fine; the 1st-edition "switch statements = smell" is explicitly retired.
  - Refused Bequest is "nine times out of ten too faint to be worth cleaning" — act only on confusion/problems, or on refused *interface*.
  - Data Class is fine as an immutable result record (Split Phase intermediates); immutable fields don't need encapsulation, derived values may be stored as fields.
  - Feature Envy is deliberately violated by Strategy/Visitor/Self Delegation — grouping by *rate of change* beats grouping by data when behavior must be swappable.
  - Split Variable exempts loop variables and collecting variables/accumulators.
  - Replace Derived Variable with Query exempts derivations from immutable sources (can't drift).
  - Preserve Whole Object is wrong when it would couple the callee to a module it shouldn't know.
  - Replace Parameter with Query is wrong when it adds an unwanted dependency or replaces a parameter with mutable-global access.
  - Assertions must never carry input validation or behavior the program depends on.
  - Comments explaining *why*, or marking uncertainty, are encouraged — only *what*-comments signal extraction.
  - Inheritance is not deprecated: use it first when the subtype relation holds; the delegate refactorings are for when it *stops* holding ("favor a judicious mixture", not "composition always").
  - Command objects: justified ~5% of the time — only when undo/lifecycle/decomposition-of-untamable-function is actually needed.
- **Performance contexts**: profile-then-tune is for normal systems; **hard real-time** systems (pacemakers: "late data is always bad data") legitimately use time budgeting and may reject refactorings that break budgets. Occasionally a refactoring does cause a real slowdown — finish refactoring, then tune, possibly reversing that specific change.
- **Refactoring scope of "behavior"**: observable behavior only. Error shapes on inputs that can't occur, call-stack details, and internal interfaces are fair game to change; tests pinning them should be discarded before refactoring.
- **Published interfaces**: the atomic mechanics don't apply — you're in deprecate-and-wait territory, and some old declarations live forever.
- **Test-scope limits**: this book's ch-4 covers unit tests of in-process business logic; UI, persistence, integration, and performance testing are explicitly out of scope — don't cite it for those.
- **Language scope**: examples are unclassed/classed JavaScript; mechanics mention adjustments for static typing (safer automated renames), single-inheritance OO, and languages with real immutability. The refactorings' *triggers* transfer; some mechanics steps (visibility restriction, compile checks) vary by language.

---

## Candidate lexicon rows

| when the plan touches code without a fast self-checking test suite | **Tests before refactoring** — refactoring without a bug detector converts small mistakes into long debugging sessions | Can I run a suite in seconds that would catch a behavior change here? | blocker | plan | src: refactoring-fowler-beck ch-4 |
| a single diff that both restructures code and changes behavior | **Two hats** — adding functionality and refactoring are different activities with different definitions of done; never wear both at once | Which hat is this edit wearing, and would the diff still make sense split in two? | should | write | src: refactoring-fowler-beck ch-2 |
| about to bolt a feature onto code shaped wrong for it | **Preparatory refactoring** — first make the change easy (warning: this may be hard), then make the easy change | Would 20 minutes of restructuring make this feature a near-trivial diff? | should | plan | src: refactoring-fowler-beck ch-2 |
| a test fails mid-refactor and the cause isn't obvious within a minute | **Revert to green** — go back to the last green commit and redo with smaller steps instead of debugging a composite change | Is debugging this cheaper than redoing it in smaller steps from green? | should | write | src: refactoring-fowler-beck ch-1 |
| a new test that has never been seen failing | **Watch it fail once** — inject a temporary fault, confirm the red and the message, revert; a never-failed test may assert nothing | If the behavior this test names broke, would this test actually go red? | should | write | src: refactoring-fowler-beck ch-4 |
| test fixture built in shared scope and mutated by test bodies | **Fresh fixture per test** — shared mutable fixtures make tests interact, producing order-dependent intermittent failures | Is any object created once reused across tests that mutate it? | blocker | review | src: refactoring-fowler-beck ch-4 |
| the urge to write a comment explaining what a block does | **Extract function instead of comment** — name the block for its intent; the comment was the name trying to get out | Could this comment become the name of an extracted function? | should | write | src: refactoring-fowler-beck ch-3 |
| the same switch/if-cascade on one condition in two or more places | **Repeated switch → polymorphism** — every new case requires finding and editing all copies; a single switch is fine | Does adding a case mean editing more than one site? | should | review | src: refactoring-fowler-beck ch-3 |
| a boolean or enum literal at the call site selecting the callee's behavior | **No flag arguments** — split into one explicit function per mode; `f(x, false)` hides the API's real surface | What does this literal mean at the call site without opening the callee? | should | review | src: refactoring-fowler-beck ch-11 |
| a function that returns a value and also mutates observable state | **Separate query from modifier** — value-returning functions should have no observable side effects (caching doesn't count) | Can I call this twice safely, and does its name admit the side effect? | should | review | src: refactoring-fowler-beck ch-11 |
| a mutable field whose value is computable from other data | **Derived data as query** — stored derived values drift from their sources; compute on demand, assert equality during migration | Could this field and its source ever disagree, and what happens then? | should | review | src: refactoring-fowler-beck ch-9 |
| a performance objection raised against a clarity refactoring | **Refactor now, profile later** — most time hides in a few hot spots and intuition misidentifies them; tune the well-factored result (exempt: hard real-time budgets) | Is there a profile showing this code is hot? | judgment | review | src: refactoring-fowler-beck ch-2 |
