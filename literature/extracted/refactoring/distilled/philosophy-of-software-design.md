# A Philosophy of Software Design — distilled

> **Source**: John Ousterhout, *A Philosophy of Software Design*, 2nd edition (2021) · extracted from `../philosophy-of-software-design.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory with a *unified theory of complexity* for module and API design: a falsifiable definition (complexity = cost of understanding/modifying, weighted by how often code is touched), three observable symptoms (**change amplification**, **cognitive load**, **unknown unknowns**), two root causes (dependencies, obscurity), and a catalog of 15 named **red flags** that an agent can pattern-match in a diff. It supplies the interface-to-functionality test (**deep vs shallow modules**) that other books assume but never define, the **define-errors-out-of-existence** family of exception-reduction techniques, and a comment doctrine grounded in abstraction (comments carry the informal half of every interface — the half code cannot express). It deliberately contradicts Clean-Code-style small-function and comments-are-failures dogma and TDD, giving the lexicon its main counterweight to decomposition-happy defaults.

## Chapter map

- ch-1 — Introduction: why complexity is the core limit; eliminate vs encapsulate; design is continuous
- ch-2 — The Nature of Complexity: definition, the 3 symptoms, the 2 causes, incremental accumulation
- ch-3 — Working Code Isn't Enough: tactical vs strategic programming; the 10–20% investment rate
- ch-4 — Modules Should Be Deep: interface vs implementation; formal/informal interface; deep/shallow; classitis
- ch-5 — Information Hiding (and Leakage): Parnas hiding; leakage; temporal decomposition; defaults; overexposure
- ch-6 — General-Purpose Modules are Deeper: "somewhat general-purpose"; push specialization up/down; eliminate special cases
- ch-7 — Different Layer, Different Abstraction: pass-through methods/variables; decorators; context objects
- ch-8 — Pull Complexity Downwards: simple interface beats simple implementation; configuration parameters
- ch-9 — Better Together Or Better Apart?: when to combine vs split code; method splitting; contra Clean Code
- ch-10 — Define Errors Out Of Existence: 4 techniques to reduce exception-handling sites
- ch-11 — Design it Twice: always sketch ≥2 radically different designs before implementing
- ch-12 — Why Write Comments? The Four Excuses: rebuttals; comments carry what code can't express
- ch-13 — Comments Should Describe Things that Aren't Obvious from the Code: comment taxonomy and precision/intuition rules
- ch-14 — Choosing Names: precision + consistency; the `block` data-loss bug; contra Go short names
- ch-15 — Write The Comments First: comments as design tool; hard-to-describe = bad abstraction
- ch-16 — Modifying Existing Code: stay strategic on every change; keeping comments alive
- ch-17 — Consistency: conventions, enforcement, "when in Rome", never half-migrate a convention
- ch-18 — Code Should be Obvious: what raises/lowers obviousness; reader decides, not writer
- ch-19 — Software Trends: inheritance, agile, unit tests, TDD critique, design patterns, getters/setters
- ch-20 — Designing for Performance: cost intuition table; measure first; design around the critical path
- ch-21 — Decide What Matters: leverage; minimize what matters; emphasize what remains
- ch-22 — Conclusion: it's all one subject — complexity

---

## ch-1 — Introduction {#ch-1}

The greatest limit on software is our ability to understand the systems we create. Two attacks on complexity, both used throughout the book:

1. **Eliminate** complexity: make code simpler and more obvious (fewer special cases, consistent identifiers).
2. **Encapsulate** complexity (**modular design**): divide the system so a developer faces only a small fraction of the total complexity at once.

Waterfall fails for software because a large system can't be visualized well enough up front; incremental development works because software is malleable — but it means **design is never done**: redesign happens continuously over the system's life, so developers should always be thinking about complexity, and every change should be an opportunity to improve design.

Usage note from the author: apply red flags as triggers — when you see one, stop and search for an alternative design that removes it; try several alternatives before settling. Every principle has "taking it too far" limits (§ Applicability below).

## ch-2 — The Nature of Complexity {#ch-2}

**Definition (falsifiable)**: complexity is anything about the *structure* of a system that makes it hard to understand and modify. Not size, not feature-sophistication. Operationally: `C = Σ cost(part) × fraction-of-dev-time-spent-in(part)` — complexity in code nobody touches barely counts; isolating complexity where it will never be seen is almost as good as removing it. Corollary: **complexity is what readers experience, not writers** — if a reader says it's complex, it is complex.

### Symptoms of complexity (the diagnostic triad)

| Symptom | Observable signal | Severity |
|---|---|---|
| **Change amplification** | One conceptual change requires edits in many places (e.g., banner color hardcoded per page) | Annoying but bounded — you at least know what to edit |
| **Cognitive load** | Developer must know a lot to complete a task (caller must free memory, many-method APIs, globals, cross-module dependencies) | Raises cost & bug risk. NOTE: lines-of-code is not the measure — *more* lines can be simpler if they reduce what a reader must hold in mind |
| **Unknown unknowns** | It is not obvious which code must be modified or what information is needed; you find out via post-change bugs | Worst of the three: the only mitigation is reading everything, which is impossible |

The design goal opposing all three is **obviousness**: a reader's quick first guess about behavior is correct, and they're confident in it.

### Causes

- **Dependencies**: code cannot be understood/modified in isolation (method signatures, protocol sender/receiver pairs, shared formats). Can't be eliminated — the goal is fewer, simpler, more *obvious* dependencies (a compiler-checked API dependency beats an implicit convention).
- **Obscurity**: important information is not obvious — generic names, undocumented units, invisible dependencies (new error status also needs a message-table entry), inconsistency. Persistent need for extensive documentation is itself a red flag that the design is wrong.

Mapping: dependencies → change amplification + cognitive load; obscurity → unknown unknowns + cognitive load.

**Complexity is incremental**: it accumulates in hundreds of small dependencies and obscurities, each individually defensible ("no big deal"). Hence the required stance is **zero tolerance** — the only counter to death-by-a-thousand-cuts is refusing each cut.

## ch-3 — Working Code Isn't Enough {#ch-3}

**Tactical programming**: primary goal = get the feature/fix working fast.

- Each task adds "just a little" complexity; kludges compound because complexity is incremental (ch-2).
- Refactoring always loses to the next feature; quick patches around problems create more problems needing more patches.
- The **tactical tornado** anti-hero: prolific committer, management hero, whose messes other engineers (the real heroes) silently clean up.

**Strategic programming**: working code is not the goal — the goal is a great design *that also works*, because most future code extends existing code, so facilitating extension is the primary job. Requires an **investment mindset**:

- Proactive investments: try 2+ designs per new class, imagine future changes, write docs.
- Reactive investments: when a design problem surfaces, fix it — don't patch around it.
- **Rate: 10–20% of total development time** on design investment. Payback estimate: 6–18 months (opinion, not measured); after crossover you develop *faster* than the tactical path forever.
- **Technical debt** framing: tactical programming borrows time; you repay more than you borrowed, and most of it is never fully repaid.

Startups: "we'll clean it up after we're successful" fails because spaghetti is nearly impossible to fix later, the payoff for good design arrives fast anyway, and messy code repels the strong engineers who would fix it (Facebook vs Google/VMware contrast). Crunch pressure is a slippery slope: delayed cleanups become permanent culture.

## ch-4 — Modules Should Be Deep {#ch-4}

A **module** = anything with an interface + implementation (class, method, function, subsystem, service). The **interface** is *everything a developer working in another module must know to use this one*:

- **Formal parts**: signatures, types, exceptions — machine-checkable.
- **Informal parts**: high-level behavior, side effects, ordering constraints ("call X before Y"), semantics of results. Usually *larger* than the formal parts and expressible only in comments (→ ch-12/13).

An **abstraction** is a simplified view of an entity that omits *unimportant* details. It fails in two directions: including unimportant details (cognitive load) or omitting important ones — a **false abstraction** that looks simple but leaves users without information they need (obscurity). Example: file systems may hide block allocation but must expose flush/durability semantics because databases need them.

**Deep module**: much functionality behind a simple interface (draw the module as a rectangle: area = functionality, top edge = interface cost). Benefit = functionality; cost to the rest of the system = interface — so "interfaces are good, but more, or larger, interfaces are not necessarily better."

- Canonical deep: Unix file I/O — five stable syscalls (`open/read/write/lseek/close`) hiding hundreds of thousands of lines (on-disk layout, path resolution, permissions, scheduling, caching, device diversity) that have been radically reimplemented for decades without interface change.
- Canonical deep: garbage collectors — *negative* interface: adding one removes the free-object API entirely.
- Depth test (falsifiable): if a module changes without its interface changing, no other module is affected — the more of the module that can change under a fixed interface, the deeper it is.

**Shallow module**: interface complexity ≈ implementation complexity — little leverage against complexity.

- Linked-list class: the abstraction hides almost nothing; interface ≈ implementation.
- Degenerate case: `addNullValueForAttribute(a) { data.put(a, null); }` — documenting it takes more text than the code, calling it takes more keystrokes than inlining it, and callers must still know it writes `data`. It *adds* net complexity.

**Classitis**: the "classes should be small" doctrine taken to system scale — many tiny classes, each simple, whose accumulated interfaces and boilerplate create huge system-level complexity. Java's 3-object file-read incantation (`FileInputStream` + `BufferedInputStream` + `ObjectInputStream`) vs Unix's defaults. Rule: **interfaces should make the common case as simple as possible** — buffering is wanted ~always, so it should be the default with an escape hatch, not an opt-in wrapper. If an interface has many features but most users need only a few, its *effective* complexity is just the commonly used part — so partition rarely-used features out of the mainline path.

## ch-5 — Information Hiding (and Leakage) {#ch-5}

**Information hiding** (Parnas 1972): each module encapsulates a few design decisions (data structures, algorithms, formats, assumptions) that appear in its implementation but not its interface. Two payoffs: simpler interface (less cognitive load) and easier evolution (no external dependencies on the hidden decision). When designing a module, ask "what can this module hide?" — more hiding = simpler interface = deeper module. Caveat: `private` is not information hiding if getters/setters re-expose the information.

**Information leakage**: a design decision is reflected in multiple modules — the same knowledge lives in several places, so changing the decision touches them all.

- Anything visible in an interface is by definition leaked → simpler interfaces correlate with better hiding.
- **Back-door leakage** (two classes both know a file format but neither interface shows it) is *worse* than interface leakage because it's invisible.
- Fix by asking: "how can I reorganize so this knowledge affects only one class?" — merge the classes if small and tied to the knowledge, or extract the shared knowledge into a new class with a *simple* interface (if the new class's interface re-exposes the knowledge, you've merely converted back-door leakage to interface leakage).
- The author calls sensitivity to leakage one of the most valuable skills a designer can develop.

**Temporal decomposition**: structuring the system around the *order of execution* (read-file class → modify class → write-file class) instead of around knowledge. Operations that run at different times but use the same knowledge get split, encoding the knowledge in multiple places → leakage. Rule: **structure modules around knowledge required, not execution order** (the HTTP-course teams that split "read request" from "parse request" both had to parse headers, duplicating format knowledge and forcing callers to call two methods in order).

Corollaries from the HTTP case study:

- **Making a class slightly larger often improves information hiding**: bring together all code for one capability; raise the interface level (one method that does the whole computation instead of one per step).
- Don't return internal representations (`getParams()` returning the internal `Map`): exposes representation, invites unwanted mutation, makes callers do extra work. Prefer `getParameter(name)` / `getIntParameter(name)` — deeper, hides representation and conversion.
- **Defaults are partial information hiding**: callers shouldn't have to specify what the module can determine (HTTP response version, Date header). Classes should "do the right thing" unasked; the best features are the ones you don't know exist. Overriding stays possible through rarely-used methods.
- Information hiding also applies *within* a class: private methods encapsulate capabilities; minimize the number of places each instance variable is touched.

**Taking it too far**: if information is genuinely needed outside the module (tunable performance parameter), it must be exposed. Goal = *minimize* what's needed outside (e.g., auto-tune instead of exposing a knob), then expose exactly that.

## ch-6 — General-Purpose Modules are Deeper {#ch-6}

Over-specialization "may be the single greatest cause of complexity in software." The sweet spot: **somewhat general-purpose** — the module's *functionality* reflects today's needs; its *interface* does not (it should be general enough for multiple uses, yet easy for today's use). General-purpose interfaces are simpler, deeper, and — counterintuitively — *less* code to implement than the specialized alternatives, even if never reused.

Canonical example (GUI editor text class): specialized API `backspace(cursor)/delete(cursor)/deleteSelection(sel)` leaked UI concepts into the text layer, produced many one-caller shallow methods, and hid information the UI actually needed (which characters get deleted — a **false abstraction**). General API: `insert(pos, str)`, `delete(start, end)`, `changePosition(pos, n)` — the UI code got slightly longer but *more obvious*, total code shrank, and the text class became reusable.

Three questions to find the general/special balance:

1. *What is the simplest interface that covers all my current needs?* (fewer methods with same capability = more general — but only while each method's own signature stays simple)
2. *In how many situations will this method be used?* One-purpose methods (`backspace`) are a red flag.
3. *Is this API easy to use for my current needs?* Guards against over-generalizing (a char-at-a-time API is simple and general but forces caller loops and is slow).

**Push specialization upwards** (app-specific features live in the top layer, not percolated into lower classes) **and downwards** (device drivers: OS defines a general block interface; each driver's specialization hides below it). Special-purpose code should be cleanly separated from the general mechanism it uses — the editor undo design: a general `History` class managing `Action` objects with `undo()/redo()` and grouping **fences**, action subclasses owned by the modules that understand them (text, UI), grouping policy in top-level UI code. Each of the three parts is ignorant of the others.

**Eliminate special cases in code**: design the normal case so edge cases fall out with no extra code — represent "no selection" as an *empty selection* and the no-selection `if`s vanish (copy of empty selection inserts 0 bytes; delete of empty range regenerates the line).

## ch-7 — Different Layer, Different Abstraction {#ch-7}

In a well-designed system each layer provides a *different* abstraction (file → block cache → device driver; TCP stream → best-effort packets). **Adjacent layers with similar abstractions are a red flag** for bad class decomposition. Manifestations:

- **Pass-through method**: does nothing but call another method with a similar/identical signature (13 of 15 public methods in one student class). Adds interface, adds dependency, adds zero functionality → indicates confused division of responsibility. Fixes: expose the lower class directly, redistribute functionality, or merge classes. Interface duplication is fine only when each method adds distinct functionality: **dispatchers** (choose which of several same-signature methods handles a request) and multiple implementations of one interface (drivers) are legitimate — they reduce cognitive load.
- **Decorators/wrappers**: encourage cross-layer API duplication and tend to be shallow boilerplate (`BufferedInputStream`, `ScrollableWindow`). Before writing one, ask: add to the underlying class? merge into the use case? merge into an existing decorator? implement standalone? Legit mainly for adapting an unmodifiable external class to a required interface.
- **Interface ≈ implementation** inside one class: a text class stored as lines with `getLine/putLine` API is shallow — callers split/join lines themselves, duplicating that logic. A character/range API over a line-based representation is deep: the difference between interface and representation *is* the value the class provides.
- **Pass-through variable**: a value threaded through a long chain of methods that don't use it (a `cert` from `main` to socket-opening `m3`). Every intermediate signature depends on it; adding a new one touches many methods. Fixes in order of preference: store in an already-shared object; global variable (breaks multi-instance/testing); **context object** — one per system instance, holding all would-be globals (config, shared subsystems, counters), a reference saved as an instance variable in major objects and passed only in constructors. Contexts are the least-bad option: they still risk becoming an unprincipled grab-bag and have thread-safety concerns (prefer immutable fields).

Net rule: each design element (interface, argument, function, class) must **eliminate more complexity than the element itself introduces**.

## ch-8 — Pull Complexity Downwards {#ch-8}

When you meet unavoidable complexity: handle it *inside* the module rather than exporting it to users. Modules have more users than developers; and **it is more important for a module to have a simple interface than a simple implementation**. Temptations that push complexity *up*: throw an exception and let the caller cope; add a configuration parameter and let the admin cope. Both amplify complexity — many people now deal with a problem one implementer could have solved once.

**Configuration parameters** get special scrutiny: sometimes users genuinely know best (request priorities), but often the parameter is an abdication ("hard to pick a retry interval" → measure response times and derive it dynamically; the computed value also stays current where a config value rots). Before exporting a knob, ask: *"will users/higher modules really be able to determine a better value than we can compute here?"* If you must add one, provide a sensible default so it matters only in exceptional cases.

**Taking it too far**: pull complexity down only when (a) it's closely related to the class's existing functionality, (b) it simplifies things elsewhere in the app, and (c) it simplifies the class's interface. (Pulling backspace-key knowledge into the text class fails (a) and (b): that's leakage, not depth.)

## ch-9 — Better Together Or Better Apart? {#ch-9}

Subdividing always *costs* something:

- component count itself (harder to track and find things);
- more interfaces — every new interface is complexity;
- management glue (code that used one object now juggles several);
- separation — related code farther apart means flipping back and forth, or worse, not knowing the other piece exists;
- duplication of code that was single-instance before the split.

So split only when the pieces are truly independent. **Signs two pieces of code belong together**:

- they share information (both know a document format);
- they're used together — but only if *bidirectionally* (block cache ↔ hash table fails the test: hash tables are used everywhere, so keep them separate);
- they overlap conceptually under one simple category (substring search + case conversion = "string manipulation"; flow control + reliable delivery = "network communication");
- one can't be understood without the other.

- **Bring together if information is shared** (the HTTP read+parse merge: shorter and simpler).
- **Bring together if it simplifies the interface** (the read→string→parse intermediate interface disappears; combined classes can also do things automatically — default buffering).
- **Bring together to eliminate duplication** (factor repeated snippets into a method only if the snippet is long and the method signature stays simple; alternatively restructure so the snippet executes in one place — a `goto err`-style single exit for repeated cleanup is legitimate).
- **Separate general-purpose from special-purpose code** (ch-6). **Special-General Mixture** is the corresponding red flag: a general mechanism containing code specialized for one of its uses.
- Worked contrast: selection + cursor combined into one object was *worse* (callers still treated them separately; a boolean tracked which end was the cursor) — separate objects, plus a shared low-level `Position` type, simplified both. Logging methods split into a `NetworkErrorLogger` class were *worse* — one-line shallow methods, one caller each, constant flipping; inline the log statements.

**Splitting/joining methods**: length alone is a bad reason to split; developers over-split. A method is fine at hundreds of lines if it has a simple signature and reads top-to-bottom. **Each method should do one thing and do it completely** and be deep. Two valid split shapes: (b) extract a cleanly separable, ideally general-purpose *subtask* as a child method (parent's interface unchanged) — invalid if you must flip between parent and child to understand either (**Conjoined Methods** red flag); (c) split into two caller-visible methods only if the original interface conflated unrelated things and most callers will need only one of the results. Joining methods is equally legitimate: it can replace shallow with deep, remove duplication/intermediates, and improve encapsulation.

↔ contra *Clean Code* (Martin), quoted directly: functions should be tiny (<10 lines, one-line blocks). Ousterhout: below a few dozen lines, further shrinking adds interfaces, breeds conjoined functions, and hurts the system; **depth over length — first make functions deep, then short enough to read; never sacrifice depth for length.** (↔ also tempers refactoring-fowler-beck's Extract Function default: apply it only when the extraction yields a genuinely independent, deeper abstraction.)

## ch-10 — Define Errors Out Of Existence {#ch-10}

An **exception** here means any uncommon condition altering normal control flow — thrown *or* signaled by special return values. Why exceptions add disproportionate complexity:

- A handler has only two options, both hard: recover forward (resend, restore from a copy) or abort while restoring consistent state (unwind partial changes).
- Handling creates *secondary* exceptions, often subtler than the primary (resent packet → duplicate at the peer; redundant copy also lost); aborting reports yet another exception upward — someone must eventually stop the cascade.
- try/catch syntax is verbose, obscures which line throws, and separates handling from the flow it interrupts.
- Handler code rarely executes, is hard to trigger in tests, and therefore rots — "code that hasn't been executed doesn't work."
- Cited study: **>90% of catastrophic failures in distributed data-intensive systems were caused by incorrect error handling** (Yuan et al., OSDI 2014).

Programmers make it worse by *over-detecting*: "the more errors detected, the better" leads to rejecting anything suspicious. **Exceptions thrown are part of the interface** and propagate up stacks, so exception-rich classes are shallow. Throwing is easy; handling is hard — so the master rule is: **reduce the number of places where exceptions must be handled**. Four techniques:

1. **Define errors out of existence** — respecify the operation so the "error" case is normal behavior.
   - Tcl `unset` on a nonexistent variable threw an error (Ousterhout: "one of the biggest mistakes I made in Tcl"); defining unset as "ensure the variable no longer exists" makes the case a successful no-op.
   - Windows can't delete open files (users hunt processes/reboot); Unix marks the file deleted, removes the name, lets existing opens keep working, frees data on last close — defining away errors for the deleter *and* for the file's current users.
   - Java `substring` throws `IndexOutOfBoundsException`; a "return the overlap of the range with the string" spec deletes 5–10 lines of clamping at every call site (Python slices already work this way). Counterargument "errors catch bugs" is answered: error-ful APIs force extra avoidance code, which breeds its own bugs; **the best way to reduce bugs is to make software simpler**.
2. **Mask exceptions** — detect and handle low, so higher layers never see it (TCP retransmission; NFS hanging-and-retrying rather than surfacing server outages, because callers could do nothing better). Masking = pulling complexity downward; results in deeper classes.
3. **Exception aggregation** — one handler, many sources: let request-scoped exceptions propagate to a single top-level handler in the dispatch loop that turns the exception's embedded message into the error response; new parameter-fetching methods plug in with zero new handler code. Aggregation works best when the exception travels *up* several layers (opposite of masking); both position one handler where it catches the most. RAMCloud's error *promotion*: rare small errors (corrupt object) are escalated to the already-required server-crash recovery path — fewer mechanisms, better-tested recovery; don't promote frequent errors (lost packet ≠ crash the server).
4. **Just crash** — for errors that are rare and hard/pointless to handle (out of memory: `ckalloc` aborts with a message; catching OOM handlers usually allocate too; most apps can't do anything useful about disk hard errors or corrupted internal state). What's crash-worthy is application-relative: a replicated storage system must *not* abort on I/O errors — recovery is its value proposition.

**Taking it too far**: masking/definition only apply when the information isn't needed outside the module. A student module that swallowed *all* network errors made robust applications impossible. Decide what matters: hide what doesn't; **expose what does** (→ ch-21).

## ch-11 — Design it Twice {#ch-11}

Your first design idea will not be the best one. Procedure, for every major decision:

1. Sketch **two or more radically different alternatives** — rough signatures of the most important methods suffice. Even if you're sure one approach is right, sketch a second anyway; a bad alternative still teaches by contrast.
2. List pros/cons. Compare on: **ease of use for higher-level code (most important)**, interface simplicity, generality, whether one enables a more efficient implementation.
3. Pick one, combine features of several, or — if all options are poor — use their specific weaknesses to drive a new design (line- and char-oriented text APIs both force callers to do text manipulation; that observation *derives* the range-oriented API).

Apply at each level separately: first the interface, then again for the implementation (linked list of lines vs fixed blocks vs gap buffer — where the criteria become simplicity and performance), and again at higher levels (module decomposition, UI features). Cost: an hour or two for a class vs days/weeks implementing it — the better design more than repays it.

The psychological trap: smart people learned early that their first idea is good enough, and carry that habit into problems where nobody's first idea is good enough; refusing to consider alternatives caps their performance. Side benefit: comparing designs is how design judgment gets trained.

## ch-12 — Why Write Comments? The Four Excuses {#ch-12}

Thesis: **without comments you cannot hide complexity** — comments are not an adjunct to design, they're part of the abstraction mechanism. The four excuses, rebutted:

1. *"Good code is self-documenting."* Only the formal interface lives in code. The informal interface — behavior, meaning of results, rationale, preconditions — can only live in comments. "If users must read the code of a method in order to use it, there is no abstraction." Writing code to be read-in-lieu-of-docs also drives pathological shortening (→ shallow methods).
2. *"No time."* Investment mindset: comments are ≲10% of dev time and pay back in maintainability; the most important (interface) comments are part of design (ch-15) and pay immediately.
3. *"Comments get stale and mislead."* Keeping them current is cheap if you avoid duplication and keep comments near code (ch-16); code reviews catch drift.
4. *"All comments I've seen are worthless."* Most are — because nobody is taught how; ch-13 is the how.

Good comments attack cognitive load (needed info in one place, irrelevant info skippable) and unknown unknowns (clarify structure and dependencies) — two of the three symptoms of ch-2.

↔ contra *Clean Code*: "comments are always failures", replace comments with extracted method names. Ousterhout: names like `isLeastRelevantMultipleOfNextLargerPrimeFactor` are cryptic, carry less than a sentence, and re-type the documentation at every call site; the failure framing shames people out of documenting.

## ch-13 — Comments Should Describe Things that Aren't Obvious from the Code {#ch-13}

Guiding rule (and the test for every comment): **could someone who has never seen the code write this comment just by reading the adjacent code? If yes, delete it.** ("The code" = the code *next to* the comment, not the whole app.) Comments exist to record the designer's mind-state that code can't express: why the code exists, rules like "always invoke a before b," what a range's endpoints mean, and above all the abstraction — "developers should be able to understand the abstraction provided by a module without reading any code other than its externally visible declarations."

**Pick conventions first** (Javadoc/Doxygen/godoc if available); conventions ensure consistency *and* ensure comments actually get written. Comment categories, by importance:

| Category | Where | Requirement |
|---|---|---|
| **Interface comment** | Before every class and every method | Class: the abstraction it provides, what an instance represents, limitations. Method: behavior as seen by callers; each arg + return, precisely (constraints, dependencies); side effects; exceptions; preconditions |
| **Data-structure member** | Every instance/static variable | What the value *represents* (nouns, not verbs — not how code manipulates it); units; inclusive/exclusive bounds; null meaning; ownership/freeing; invariants; meaning of a *missing* entry |
| **Implementation comment** | Inside longer methods | *What* and *why*, never how-in-detail: one abstract line per major block/phase, loop-iteration invariants, and rationale for non-obvious code (bug-fix references: "Fixes RAM-436") |
| **Cross-module comment** | Central location | Rare, hard, vital (see below) |

**Comments must sit at a different level of detail than the code**:

- **Lower-level comments add precision** where code is vague: `// Current offset in resp Buffer` → "Position in this buffer of the first object that hasn't been returned to the client."
- **Higher-level comments add intuition**: replace a line-by-line paraphrase with intent — "Try to append the current key hash onto an existing RPC to the desired server that hasn't been sent yet" lets a reader both explain and *judge* the code. "How-we-get-here" comments (conditions under which this runs) are especially valuable.
- Same-level comments repeat the code (**Comment Repeats Code** red flag; classic tell: comment made of the words of the method name).

**Interface documentation must not contain implementation** (**Implementation Documentation Contaminates Interface** red flag) — and if the interface comment is *forced* to describe the implementation, the thing is shallow (design signal, ch-15). Worked example: the `IndexLookup` class comment shrank to what users need (what a range query is, how getNext drives it), dropping RPC names, private config constants, and "include the header" filler; server crashes go unmentioned *because they're masked*.

**Cross-module design decisions**: put the doc where developers must go anyway (the `Status` enum lists all 7 places a new status must be registered); when no natural home exists, a central `designNotes` file with named sections, referenced by one-liners (`// See "Zombies" in designNotes.`) — single copy, findable, at the cost of distance from the code.

Arbitration rule: "obvious" is decided by the *reader* — if a reviewer says it's not obvious, it's not; don't argue, clarify.

## ch-14 — Choosing Names {#ch-14}

Names are abstractions and documentation; name choice is complexity-is-incremental in action (one mediocre name ≈ harmless; thousands compound). War story: Sprite OS intermittently zeroed file data; the six-month hunt ended at a variable named `block` that meant *logical file block* in some code and *physical disk block* in others — used once in the wrong sense, it overwrote an unrelated disk block. Everyone who read the faulty code assumed the familiar meaning and saw nothing. `fileBlock`/`diskBlock` — or better, distinct *types* that can't be interchanged — would have prevented the bug outright.

- **Create an image**: test a candidate name by asking what a reader would guess seeing it *in isolation*. 2–3 words max; pick the words that capture what's most important.
- **Be precise** (**Vague Name** red flag): `getCount` → `numActiveIndexlets`; `x, y` for character coordinates → `charIndex, lineIndex`; `blinkStatus` → `cursorVisible` (boolean names should be predicates); `VOTED_FOR_SENTINEL_VALUE` → `NOT_YET_VOTED`; don't name a non-return-value `result`. Names can also be too *specific* (`delete(Range selection)` when any range is deletable → `range`). Exception: tiny-scope loop variables `i, j` are fine — "the greater the distance between a name's declaration and its uses, the longer the name should be" (Gerrand's rule, endorsed).
- **Hard to Pick Name red flag**: if no precise, intuitive, short name exists, the underlying entity probably lacks a clean definition — consider refactoring (e.g., one variable representing several things).
- **Use names consistently**: always the same name for the same purpose, never for anything else, and the purpose narrow enough that all uses behave identically (the third requirement is the one the `block` bug violated). Related variables: common name + distinguishing prefix (`srcFileBlock`/`dstFileBlock`).
- **No extra words**: drop generic nouns (`fileObject`), type encodings/Hungarian notation (IDEs show types), and class-name echoes in members (`File.fileBlock` → `block`).
- ↔ contra Go style guide (very short names): readability is judged by readers, not writers; if readers complain your names are cryptic, lengthen them.

## ch-15 — Write The Comments First {#ch-15}

Delayed comments are bad comments: postponement usually means never; end-of-project comments are written by someone mentally checked out who no longer remembers the design, so they paraphrase code. Instead, put comments at the *front* of the process: class interface comment → interface comments + signatures of key public methods (bodies empty) → iterate until structure feels right → instance-variable declarations + comments → bodies (adding implementation comments as you go; new methods get their interface comment before their body). Done coding = done documenting, no backlog.

**Comments are a design tool** — the most important benefit. An interface comment is the measurable proxy for interface complexity: **if a method or variable needs a long comment to be complete, the abstraction is bad** ("comments serve as a canary in the coal mine of complexity" — **Hard to Describe** red flag). Compare interface comment vs implementation to gauge depth: interface comment that must restate the implementation ⇒ shallow. Writing them early lets you fix the design before code exists. (Caveat: comments only measure complexity if complete and clear.)

Cost objection quantified: comment typing is ≲5% of dev time; and comments-first stabilizes abstractions before coding, likely *saving* net time. Also: early comments are written during the fun design phase, not as a graduation tax.

## ch-16 — Modifying Existing Code {#ch-16}

A mature system's design is determined more by its evolution than by its initial conception, so the strategic mindset must govern *changes*, not just green-field work.

- The tactical maintenance mindset — "smallest possible change that does what I need," often rationalized as risk avoidance in unfamiliar code — quietly accretes special cases and dependencies; the design degrades one minimal patch at a time.
- Target instead: **after each change, the system should have the structure it would have had if it had been designed that way from the start.** If the change reveals the current design is no longer best, refactor toward the best design.
- Ratchet rule: find *some* small design improvement on every visit to the code — "if you're not making the design better, you are probably making it worse."
- Compromises under deadline are real (a 2-hour hack vs a 3-month refactor, or refactors that break other teams), but resist: ask "is this the best I can do *given my constraints*?" — often a 2-day alternative is nearly as clean; otherwise schedule the cleanup explicitly. Organizations should budget a fraction of total effort for refactoring.

Keeping comments true during change:

- **Keep comments near the code they describe** — interface comment adjacent to the method body (not in the distant `.h` file; users read Doxygen/IDE output, not headers). Spread implementation comments to the narrowest enclosing scope; a top-of-method overview may list the phases that are each documented in place. The farther a comment sits from its code, the more abstract it should be.
- **Comments belong in the code, not the commit log** — nobody rereads the log; a subtle-motivation note left only in the commit invites someone to undo the fix later. If future developers need it, put it in the code (duplicate to the log if you like).
- **Avoid duplication** — document each design decision exactly once, at the most findable spot (often a variable declaration); elsewhere, short pointers ("See comment in xyz"); a broken pointer is self-evident, a stale duplicate is not. Don't re-document another module's decisions at call sites, and don't restate externally documented material (HTTP spec, user manual) — link it.
- **Check the diffs** before every commit: scan the change set to confirm each change is reflected in documentation (also catches leftover debug code and unfinished TODOs).
- **Higher-level comments are easier to maintain** — they survive detail-level edits.

## ch-17 — Consistency {#ch-17}

Consistency = similar things done in similar ways *and* dissimilar things done in visibly different ways. It creates cognitive leverage (learn once, apply everywhere) and makes reader assumptions safe — inconsistency makes familiar-looking patterns lie. Applies to: names (ch-14), coding style, interfaces with multiple implementations, design patterns, **invariants** (properties always true — they cut special-case reasoning).

Maintaining it (people churn erodes conventions):

- **Document** conventions in a findable place; adopt a published style guide rather than inventing.
- **Enforce** with tooling: a pre-commit checker beats memory (the CRLF war story: a commit-time script ended a recurring cross-OS line-terminator mess). Nit-picky code reviews train newcomers fastest.
- **"When in Rome"**: in existing code, mimic the surrounding conventions; before making a design decision, look for an existing precedent in the project.
- **Don't change existing conventions.** "Having a 'better idea' is not a sufficient excuse": the value of consistency almost always exceeds the delta between approaches. Change only if (1) you have significant *new* information and (2) the improvement justifies migrating *all* old uses so no trace of the old convention remains. Half-migrations are worse than either endpoint.

**Taking it too far**: forcing dissimilar things into the same pattern/name is anti-consistency — the guarantee readers need is "if it looks like an x, it really *is* an x."

## ch-18 — Code Should be Obvious {#ch-18}

Obvious code: a reader's quick, low-effort first guess about behavior is correct (**Nonobvious Code** red flag otherwise). Obviousness is determined *by readers in review*, not by the author's feeling.

Raises obviousness: good names (ch-14); consistency (ch-17); **judicious white space** (parameter docs with visual structure; blank lines between labeled blocks; spaces inside statements); comments where non-obviousness is unavoidable.

Lowers obviousness (each requiring compensating documentation if used):

- **Event-driven programming**: handlers are invoked indirectly via registration, so control flow can't be followed; document each handler's invocation conditions in its interface comment ("invoked in the dispatch thread by a transport if…").
- **Generic containers** (`Pair<Integer,Boolean>` returns): `getKey()/getValue()` mean nothing at the call site. Define a small purpose-specific struct/class instead. General principle: **software should be designed for ease of reading, not ease of writing** — writer convenience never justifies reader confusion.
- **Declared type ≠ allocated type** (`List` declared, `ArrayList` allocated): the declaration misleads about performance/thread-safety; match them.
- **Code that violates reader expectations** (a `main` that returns while spawned threads keep the app alive): document at the point of surprise, not only in the constructor's interface comment.

Information framing: nonobvious code = the reader lacks information. Three remedies, best first: reduce the information *needed* (abstraction, eliminate special cases); exploit information readers already have (conventions, expectations); present the information in-line (names, comments).

## ch-19 — Software Trends {#ch-19}

Yardstick for any methodology: *does it actually reduce complexity in large systems?*

- **OOP/inheritance**: **interface inheritance** (many implementations of one signature set) fights complexity — the more implementations, the deeper the interface. **Implementation inheritance** (inherited default method bodies) reduces change amplification but couples parent and children via shared instance variables (information leakage within the hierarchy; worst case you need the whole class hierarchy in your head to change any class). Prefer **composition** (helper classes); if you must inherit implementation, have parent-managed state accessed by children read-only/through parent methods. OOP mechanisms *assist* but don't guarantee good design.
- **Agile**: its incrementalism matches ch-1; its risk is legitimizing tactical programming — feature-focus and "don't build general-purpose yet." Rule: **the increments of development should be abstractions, not features** — defer an abstraction until first needed, then design it fully and somewhat-general (ch-6), not feature-by-feature.
- **Unit tests**: unreservedly endorsed — a good suite is what makes strategic refactoring *safe*; without one, developers minimize structural change and design decays (Tcl bytecode-compiler rewrite shipped with one post-alpha bug thanks to the existing suite). Unit tests beat system tests on coverage per effort.
- **TDD**: ↔ contra modern-software-engineering (Farley) and refactoring-fowler-beck, which build on red-green-refactor. Ousterhout: writing tests first "focuses attention on getting specific features working, rather than finding the best design — this is tactical programming pure and simple"; there's no natural point where design happens. Exception he endorses: **write the failing test first when fixing a bug** (proves the test actually triggers the bug).
- **Design patterns**: fine when they fit (consistency benefit, ch-17); the risk is over-application — forcing a problem into a pattern when a custom approach is cleaner. "More design patterns" ≠ better.
- **Getters/setters**: a Java-culture pattern to avoid — they're shallow clutter that re-exposes implementation; the real fix is not exposing instance variables at all. Pattern-establishment itself carries the risk that people maximize the pattern's use.

## ch-20 — Designing for Performance {#ch-20}

Neither extreme works: optimizing every statement adds complexity for imaginary wins; ignoring performance yields "death by a thousand cuts" — a 5–10× slower system with no single fixable hotspot. Middle path: use **cost awareness** to pick *naturally efficient yet clean* designs.

| Operation | Approximate cost |
|---|---|
| Datacenter round-trip | 10–50 µs (tens of thousands of instructions) |
| WAN round-trip | 10–100 ms |
| Disk I/O | 5–10 ms (millions of instructions) |
| Flash I/O | 10–100 µs |
| Emerging NVM | ~1 µs (~2,000 instructions) |
| Dynamic allocation (`malloc`/`new`) | significant (alloc + free/GC overhead) |
| Cache miss (DRAM fetch) | a few hundred instructions |

Learn your local numbers with **micro-benchmarks** (RAMCloud built a harness: days to create, 5–10 minutes per new benchmark thereafter). Where equally simple options differ in cost, take the cheap one (hash table over ordered map ≈ 5–10×; array *of structs* over array of pointers to structs). If efficiency requires complexity: acceptable when small and hidden behind unchanged interfaces; otherwise start simple and optimize on evidence — unless you *already have* evidence it matters (RAMCloud committed to kernel-bypass networking up front because measurements showed kernel networking couldn't meet its latency goal).

**Measure before (and after) modifying.** Programmer intuition about performance is unreliable, including experts' — intuition-driven tuning wastes time and complicates the system.

- Before: measure deeply enough to *locate* the few specific places where time is spent and where you have an improvement idea — top-level "the system is slow" identifies nothing.
- After: re-measure against the baseline; **if there's no measurable improvement, back the change out** (unless it also simplified the system). Retained complexity must buy a significant speedup.

**Design around the critical path** — a last resort, used only after fundamental fixes (introduce a cache, change the algorithm, bypass a slow layer) are excluded:

1. Write down "the ideal": the minimum code that must execute for the common case, ignoring current class structure, current special cases, and current data layout (combine variables if convenient).
2. Find the cleanest design that stays close to the ideal — a little added code for clean abstraction is fine (an extra call into a deep general-purpose hash table class, say).
3. **Take special cases off the critical path**: ideally a single up-front `if` detects *all* special cases at once and branches aside; the hot path then runs test-free, and the off-path handling is structured for simplicity, not speed.

Worked example (RAMCloud `Buffer`): the internal-chunk alloc path checked 6 distinct conditions across three same-signature shallow layers (a red flag per ch-7). Redesign centered the class on its hot paths: one method, one test on a synthesizing variable (`availableAppendBytes` — zero simultaneously encodes "no space," "last chunk not internal," and "no chunks"). Result: ~2× faster (8.8 → 4.75 ns per small append) *and* 20% less code (1,476 vs 1,886 lines). Deliberate counter-trade: a `totalLength` field is updated on the alloc path because length queries are also hot.

Moral: **clean design and high performance are allies** — simple code is fast (no redundant work, deep classes amortize call overhead across layer crossings, defined-away special cases need no checks).

## ch-21 — Decide What Matters {#ch-21}

The meta-principle behind the whole book (new in the 2nd edition): separate what matters from what doesn't; **structure the system around what matters, hide the rest**. Abstractions (interface = what matters to users), names (the 2–3 words that matter most), performance work (critical path = the operations that matter), and exception exposure (ch-10's boundary: hide the unimportant, expose the important) are all instances.

- **How to find what matters**: look for **leverage** — a solution that solves many problems (the general text API vs `backspace`), knowledge that predicts many behaviors (**invariants**). Comparing alternatives (design-it-twice) reveals importance. When unsure, *hypothesize*, commit, observe, and extract the lesson either way — this is how design judgment ("good taste") is trained.
- **Minimize what matters**: fewer constructor parameters; defaults reflecting common usage; hidden info doesn't matter outside its module; a low-level-handled exception doesn't matter above; an auto-computed parameter doesn't matter to admins.
- **Emphasize what matters** via *prominence* (interface docs, names, parameters of hot methods), *repetition* (key ideas recur), *centrality* (what matters most sits at the heart and shapes the structure — the device-driver interface). Converse also holds: what is prominent/repeated/central is *read as* mattering — so de-emphasize the unimportant.
- **The two failure modes**: treating too many things as important (clutter, irrelevant arguments, the Java buffered/unbuffered distinction, shallow classes) and failing to mark something important (hidden vital info, missing functionality endlessly recreated → unknown unknowns).

## ch-22 — Conclusion {#ch-22}

One subject: complexity — its causes (dependencies, obscurity), its detectors (red flags), its treatments (deep generic classes, defined-away errors, separated interface/implementation documentation), and the investment mindset that funds all of them. The up-front cost is real; the payback is fast; and good design makes the work more fun — poor designers spend their time chasing bugs in brittle code.

---

## The book's own summary of design principles

Back-matter list, kept as retrieval keys (each expanded in the chapter cited):

| # | Principle | Src |
|---|---|---|
| 1 | Complexity is incremental: you have to sweat the small stuff | ch-2 |
| 2 | Working code isn't enough | ch-3 |
| 3 | Make continual small investments to improve system design | ch-3 |
| 4 | Modules should be deep | ch-4 |
| 5 | Interfaces should be designed to make the most common usage as simple as possible | ch-4 |
| 6 | It's more important for a module to have a simple interface than a simple implementation | ch-8, ch-9 |
| 7 | General-purpose modules are deeper | ch-6 |
| 8 | Separate general-purpose and special-purpose code | ch-6, ch-9 |
| 9 | Different layers should have different abstractions | ch-7 |
| 10 | Pull complexity downward | ch-8 |
| 11 | Define errors out of existence | ch-10 |
| 12 | Design it twice | ch-11 |
| 13 | Comments should describe things that are not obvious from the code | ch-13 |
| 14 | Software should be designed for ease of reading, not ease of writing | ch-18 |
| 15 | The increments of software development should be abstractions, not features | ch-19 |
| 16 | Separate what matters from what doesn't matter, and emphasize what matters | ch-21 |

## Red flags catalog

Ousterhout's own summary list; each is an observable trigger for redesign, not a style nit.

| Red flag | Detection cue (in code/diff/review) | Primary fix | Src |
|---|---|---|---|
| **Shallow Module** | Class/method interface isn't much simpler than its implementation; doc longer than the code; calling it costs more than inlining | Deepen: merge, generalize, hide more | ch-4 |
| **Information Leakage** | Same design decision (format, protocol, representation) reflected in ≥2 modules — even if in no interface | Reorganize so the knowledge touches one class | ch-5 |
| **Temporal Decomposition** | Code structure mirrors execution order (readFoo → processFoo → writeFoo classes); same knowledge used at multiple phases | Structure around knowledge, not order | ch-5 |
| **Overexposure** | Using a common feature forces learning rarely-used features (mandatory params/wrappers for defaults) | Defaults; partition rare features out of the common path | ch-5 |
| **Pass-Through Method** | Method does nothing but call another with a near-identical signature | Expose lower class, redistribute, or merge classes | ch-7 |
| **Repetition** | The same nontrivial snippet appears again and again | Factor out, or restructure to execute it once | ch-9 |
| **Special-General Mixture** | A general-purpose mechanism contains code specialized for one of its uses | Push specialization up (or down) out of the mechanism | ch-9 |
| **Conjoined Methods** | Can't understand one method (or code piece) without reading another | Re-merge, or find a truly separable split | ch-9 |
| **Comment Repeats Code** | Comment deducible from adjacent code; comment made of the entity's name words | Different level of detail: add precision or intuition; else delete | ch-13 |
| **Implementation Documentation Contaminates Interface** | Interface comment mentions internals users don't need | Move to implementation comments; if unavoidable, class is shallow | ch-13 |
| **Vague Name** | Name (`count`, `status`, `x`, `data`) could refer to many things | Precise name; if none exists → next flag | ch-14 |
| **Hard to Pick Name** | No short, precise, intuitive name exists for the entity | The entity lacks a clean definition — refactor it | ch-14 |
| **Hard to Describe** | A complete interface comment for a method/variable must be long | The abstraction is wrong; redesign before coding | ch-15 |
| **Nonobvious Code** | Meaning/behavior not graspable in a quick read (per a *reader*, not the author) | Reduce info needed; follow conventions; document the surprise | ch-18 |
| *(unnamed) Adjacent similar abstractions* | Two layers expose near-identical APIs (decorator piles, same-signature call chains) | Different layer, different abstraction | ch-7 |

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Any new module/class/method being designed | Make it deep: interface much simpler than implementation; judge modules by functionality-per-interface, not size | Interface is the complexity a module *imposes*; benefit is what it hides | ch-4 |
| API where the common use case needs boilerplate, wrappers, or mandatory params | Make the common case the default; hide rare features behind separate, ignorable methods | Effective interface complexity = complexity of the commonly used part | ch-4, ch-5 |
| Plan splits one capability into classes by execution phase (read→parse→write) | Reject temporal decomposition; group code by the knowledge it needs | Same knowledge at different times → leakage + duplicated parsing/format code | ch-5 |
| Two modules both encode the same format/protocol/representation | Reorganize so the decision lives in exactly one class (merge, or extract with a *simple* interface) | Back-door leakage forces coordinated changes and is invisible | ch-5 |
| Method returns an internal collection/structure (`getParams()` → internal Map) | Return purpose-level values (`getParameter(name)`); never expose internal representation | Representation changes then break every caller; callers can corrupt state | ch-5 |
| Caller must supply a value the module could compute (protocol version, retry interval, buffer size) | Compute it; default it; export a knob only if users genuinely know better | Config parameters export one implementer's problem to every user/admin, and rot | ch-5, ch-8 |
| New class tailored to exactly today's caller (method per UI action; one-caller methods) | Make the *interface* somewhat general-purpose even though the functionality serves today's need | General interfaces are simpler, deeper, less total code — even without reuse | ch-6 |
| `if` handling an "absent/empty" state throughout a feature | Redesign the normal case to subsume the edge (empty selection instead of no-selection flag) | Special cases breed scattered conditionals and bugs | ch-6 |
| Diff adds a method that only forwards to a same-signature method | Remove the pass-through: expose callee, redistribute, or merge the classes (dispatchers/multiple implementations exempt) | Adds interface + dependency, zero functionality | ch-7 |
| A parameter threaded through methods that never use it | Use a context object (or an already-shared object); pass it only via constructors | Pass-through variables force every intermediate signature to know about them | ch-7 |
| Choice between complicating a module's interface vs its implementation | Pull complexity downward — the implementer suffers so users don't — if related to existing functionality and it simplifies the interface and callers | Modules have more users than developers | ch-8 |
| Proposal to split a method/class "because it's long/big" | Split only if it yields cleaner, independent, deeper abstractions; depth over length | Each split adds interfaces and separation; conjoined pieces are worse than length | ch-9 |
| Two code pieces share information, are used together bidirectionally, or can't be understood apart | Bring them together | Subdivision of related code creates interfaces, glue, and invisible dependencies | ch-9 |
| New `throw` for a suspicious-but-handleable input; exception the thrower can't say how to handle | Redefine semantics so the case is normal (unset = "ensure absent"; substring = "return overlap") | If the thrower doesn't know what to do, the caller won't either; exceptions are interface | ch-10 |
| Same exception caught with the same handling at many call sites | Aggregate: let it propagate to one top-level handler (request loop pattern), message carried in the exception | One handler replacing N; new sources plug in free | ch-10 |
| Low-level fault that higher layers can do nothing useful about (lost packet, temporarily-down server) | Mask it low (retry/recover inside the module) | Fewer exceptions in the interface = deeper module; complexity pulled down | ch-10 |
| Rare, unhandleable error (OOM, disk hard error, corrupted internal state) — and app is not a recovery-is-the-product system | Just crash with a clear diagnostic (`ckalloc` pattern) | Handling code that never runs doesn't work; >90% of catastrophic distributed failures are bad error handling | ch-10 |
| About to implement the first design that came to mind for any major decision | Design it twice: sketch ≥2 radically different alternatives; compare on caller ease-of-use first | First ideas aren't best at hard-problem scale; costs hours against weeks of implementation | ch-11 |
| New class or public method in a diff | Interface comment required (class: abstraction + instance meaning + limitations; method: behavior, args/returns precisely, side effects, exceptions, preconditions) | The informal interface exists only in comments; without it there is no abstraction | ch-13 |
| Comment a stranger could write from the adjacent code alone; comment reusing the entity's name words | Delete or rewrite at a different level: precision (units, bounds, null-meaning, ownership, invariants) or intuition (intent, how-we-get-here) | Same-level comments are noise that trains readers to ignore all comments | ch-13 |
| Design decision spanning modules (protocol pairs, multi-file registration ripple) | Document once, centrally (at the place devs must visit, or a `designNotes` file) with pointer comments elsewhere | Cross-module decisions cause many bugs; duplicated docs rot silently | ch-13, ch-16 |
| One name for two behaviors; name meaningless in isolation; boolean not a predicate | Names must be precise and used consistently (same name ⇔ same narrow purpose, everywhere) | The `block` bug: readers assume a name's familiar meaning — a wrong assumption costs months | ch-14 |
| You can't find a short precise name / can't write a short complete comment for a thing | Treat as a design signal: the entity's decomposition is wrong — refactor before shipping | Names and comments are the canary in the coal mine of complexity | ch-14, ch-15 |
| Starting implementation of a designed class | Write class + method interface comments *before* bodies | Comments-first tests the abstraction while it's still cheap to change; delayed comments never get written well | ch-15 |
| Bug-fix or feature diff into existing code that adds a special case/kludge | Leave the system as if it had been designed with this change in mind from the start; improve something every visit | "Smallest possible change" is tactical programming; design decays one minimal patch at a time | ch-16 |
| Detailed rationale written only in a commit message / PR description | Put it in the code (comment near the affected lines); the log is where explanations go to be forgotten | Future developers won't scan the log; they will undo unexplained fixes | ch-16 |
| Diff introduces a second convention (naming, structure, pattern) alongside an existing one | Follow the existing convention; change conventions only with new information *and* a full migration of all old uses | Consistency's value almost always exceeds the delta between approaches; half-migrations lie to readers | ch-17 |
| Return values via `Pair`/tuple with generic accessors; declared supertype ≠ allocated type; code defying reader expectations | Define a purpose-specific struct; match declaration to allocation; document the surprise at the surprise site | Design for ease of reading, not ease of writing | ch-18 |
| Proposal to inherit implementation (shared parent method bodies/state) | Prefer composition; if inheriting, keep parent state parent-managed (children read-only) | Shared instance variables leak information through the hierarchy | ch-19 |
| Planning increments as features; hacking to make the next test pass | Increments of development should be abstractions, not features; when an abstraction is first needed, design it whole | Feature-driven increments (incl. TDD) are tactical programming with no design moment | ch-19 |
| Performance-motivated change proposed on intuition | Measure first (deep enough to locate the cost), change, re-measure; back it out if no measurable win and no simplification | Programmer performance intuition is unreliable, even for experts | ch-20 |
| Confirmed hot path with no fundamental fix available | Redesign around the critical path: write the "ideal" minimal-instruction version, then the cleanest design near it; one up-front test deflects all special cases | Special-case checks and shallow layer crossings are where hot paths bleed | ch-20 |
| Choosing among equally simple primitives (hash vs ordered map; array-of-structs vs pointers) | Take the naturally efficient one | Free 5–10× wins avoid death-by-a-thousand-cuts | ch-20 |
| Code seems simple to its author but a reviewer calls it complex/nonobvious | The reader's verdict stands: don't argue — probe why, then clarify with better code or comments | Complexity is defined by readers; the disconnect itself is diagnostic | ch-2, ch-13, ch-18 |
| A change adds "just a little" complexity justified by schedule ("no big deal") | Zero tolerance: reject the increment or pair it with an offsetting cleanup | Complexity arrives in hundreds of individually defensible pieces and can't be removed piecewise later | ch-2, ch-3 |

## Anti-patterns

- **Tactical programming / tactical tornado** (ch-3): velocity via accumulated kludges. Cue: recurring "quick fix now, clean later" justifications; one contributor whose features ship fast and whose files everyone else patches.
- **Classitis** (ch-4): "more classes = better." Cue: many tiny classes/methods, each individually trivial, requiring N objects to accomplish one common operation (Java stream stacking).
- **Temporal decomposition** (ch-5): module boundaries = execution phases. Cue: `Reader`/`Processor`/`Writer` triads sharing format knowledge.
- **False abstraction** (ch-4, ch-6): interface hides information callers actually need. Cue: users routinely read the implementation to use the API safely (e.g., `backspace` hiding which characters die; a file API hiding flush semantics from a database).
- **Configuration-parameter abdication** (ch-8): knobs instead of decisions. Cue: parameters no user can plausibly set better than the implementation could compute; hundreds of knobs.
- **Over-defensive exception definition** (ch-10): "the more errors detected, the better." Cue: `throw` for conditions callers routinely catch-and-ignore (Tcl `unset` pattern); APIs where common inputs require pre-validation ritual (Java `substring`).
- **Blanket exception swallowing** (ch-10 "taking it too far"): masking errors callers *need* (a network layer discarding all failures). Cue: robust behavior impossible to build above the module.
- **Comments-are-failures culture** (ch-12): replacing documentation with mega-names and extraction. Cue: `isLeastRelevantMultipleOf...`-style names; uncommented public APIs defended as "self-documenting."
- **Comment paraphrase** (ch-13): one comment per line at code level. Cue: delete-the-comment test passes (nothing lost).
- **Convention "improvement"** (ch-17): introducing a better-but-second way. Cue: diff adds a new pattern for something the codebase already does another way, without migrating old uses.
- **Getter/setter reflex** (ch-19): exposing state through method clutter. Cue: field-per-accessor pairs with no behavior.
- **Premature/intuition-driven optimization and its mirror, cost-blindness** (ch-20): tuning without measurement; or N free 5–10× losses (pointer-chasing structures, chatty round-trips) nobody chose deliberately.

## Applicability & exemptions

- **Every principle has a "taking it too far" limit.** The book's own stated exemptions: information hiding must not hide what callers genuinely need (ch-5); pulling complexity down requires relatedness + net simplification (ch-8); general-purpose must stay easy for today's use — don't build speculative frameworks (ch-6); defining errors away / masking is only valid when the error information is not needed above (ch-10); consistency must not force dissimilar things to look similar (ch-17); larger classes are only better *up to* coherent-responsibility boundaries — ch-9 gives the separation criteria (selection vs cursor).
- **Judgment calibration, not law**: the author labels the book an opinion piece; the meta-rule is "the overall goal is to reduce complexity; this is more important than any particular principle." If applying a rule doesn't reduce complexity in context, drop it.
- **Deep-module and anti-small-function guidance is contested territory.** Do not auto-flag long functions as violations *or* auto-merge small ones: the test is depth and independence (conjoined-ness), not line count. When reviewing code in a codebase that follows Clean-Code/Fowler conventions, consistency (ch-17) can locally outweigh depth preferences.
- **TDD critique** (ch-19) is about design sequencing, not testing: unit tests themselves are strongly endorsed, and test-first *is* endorsed for bug fixes. ↔ modern-software-engineering treats TDD as a core practice — surface the tension, don't resolve it silently.
- **Crash-on-error** (ch-10) is application-relative: forbidden where recovery is the product (replicated storage, high-availability services — cf. release-it's stability patterns, which assume errors must be absorbed, not crashed on, at system boundaries).
- **10–20% investment and 6–18 month payback** are explicitly the author's unmeasured estimates — use as defaults, not evidence.
- **Performance numbers** (ch-20 table) are 2021-era magnitudes for cost *intuition*; for engineering decisions use measured numbers (the latency book in this directory is the deeper source).
- **Scope**: examples are Java/C++ classes, but "module" explicitly includes functions, subsystems, and network services; the rules transfer to non-OO code. Comment-density rules assume typed compiled languages with doc tooling; in contexts with strong type-level expressiveness, some informal-interface content migrates into types — the test remains "can a user invoke this correctly without reading the body?"

## Candidate lexicon rows

| new class/method whose complete interface description is nearly as long as its implementation | **Deep modules** — a module's cost is its interface, its benefit the functionality hidden behind it; shallow modules add interface without leverage | Is this interface much simpler than what it hides? | should | plan | src: philosophy-of-software-design ch-4 |
| design decision (format, protocol, representation) appearing in more than one module | **No information leakage** — every leaked decision couples modules so a change fans out invisibly | Which single class could own this knowledge outright? | should | review | src: philosophy-of-software-design ch-5 |
| module boundaries drawn along execution phases (read→process→write) | **No temporal decomposition** — structure follows knowledge, not run order, or shared knowledge gets encoded twice | Do two of these phases need the same knowledge? | should | plan | src: philosophy-of-software-design ch-5 |
| new `throw`/error return for a condition callers will routinely catch-and-ignore or pre-validate around | **Define errors out of existence** — respecify the operation so the case is normal behavior; exceptions are interface complexity and >90% of catastrophic distributed failures are error-handling bugs | Can the spec make this case a successful no-op or clamped result? | should | write | src: philosophy-of-software-design ch-10 |
| new configuration parameter, or an exception punted to callers, in lieu of an internal decision | **Pull complexity downward** — the module implementer should suffer so its many users don't; a simple interface beats a simple implementation | Could this module compute/handle this better than its users can? | should | plan | src: philosophy-of-software-design ch-8 |
| method that only forwards its arguments to a near-identical signature | **No pass-through methods** — adjacent layers must offer different abstractions; forwarding adds dependency with zero functionality | What distinct responsibility does each of these two layers own? | should | review | src: philosophy-of-software-design ch-7 |
| class API shaped exactly around its first caller (one-purpose, one-call-site methods) | **Somewhat general-purpose** — implement today's functionality behind an interface not tied to today's use; it comes out simpler and smaller | Would this interface still make sense for a second, different caller? | judgment | plan | src: philosophy-of-software-design ch-6 |
| comment that a stranger could write from the adjacent code alone | **Comments at a different level than the code** — add precision (units, bounds, null semantics, ownership, invariants) or intuition (intent, how-we-get-here), never paraphrase | What does a reader need here that the code cannot say? | should | write | src: philosophy-of-software-design ch-13 |
| public class or method landing without an interface comment | **Document the informal interface** — behavior, side effects, exceptions, preconditions exist only in comments; without them there is no abstraction | Can a caller use this correctly without reading its body? | should | review | src: philosophy-of-software-design ch-13 |
| struggling to name a variable/method or to write a short complete comment for it | **Hard-to-describe is a design smell** — comments and names are the canary in the coal mine of complexity; redesign the entity, don't force the description | Is the difficulty in the wording, or in what the thing is? | judgment | write | src: philosophy-of-software-design ch-15 |
| bug-fix/feature diff adding a kludge or special case to existing code | **Stay strategic** — after the change the system should look as if designed that way from the start; smallest-possible-change is how designs rot | What would this code look like if the change had been planned originally? | should | write | src: philosophy-of-software-design ch-16 |
| performance change proposed without profiling data, or kept without a re-measurement | **Measure before and after** — intuition about performance is unreliable; back out changes with no measured win unless they simplify | Where exactly is the time going, and did the change move that number? | should | review | src: philosophy-of-software-design ch-20 |
