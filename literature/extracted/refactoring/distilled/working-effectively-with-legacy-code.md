# Working Effectively with Legacy Code — distilled

> **Source**: Michael C. Feathers, *Working Effectively with Legacy Code*, Prentice Hall PTR, 2005 · extracted from `../working-effectively-with-legacy-code.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory about changing code that has **no tests**. Feathers' operational definition — **legacy code is simply code without tests** — reframes every change decision: before behavior can be changed safely it must be pinned by **characterization tests**, and before tests can be written, dependencies must be broken at **seams**. This book supplies (a) the 5-step legacy-code change algorithm, (b) the seam model (object/link/preprocessing seams + enabling points) as the vocabulary for "where can behavior be swapped without editing here?", (c) sprout/wrap techniques for adding tested code when the host can't be tested yet, and (d) a 24-entry catalog of dependency-breaking refactorings explicitly designed to be performed *without* tests, conservatively, in the service of getting tests in place. Fowler's *Refactoring* assumes a test suite exists; this book is the missing step zero. ↔ contra refactoring-fowler-beck ch-2: Fowler treats "solid test suite" as a mandatory precondition; Feathers supplies the sanctioned exceptions (conservative catalog refactorings, tool-verified automated refactorings, scratch refactoring that is thrown away).

## Chapter map
- ch-1 — Changing Software: the four reasons to change code; why preserving existing behavior is the real problem
- ch-2 — Working with Feedback: Edit-and-Pray vs Cover-and-Modify; what a unit test is; the legacy code dilemma; the legacy-code change algorithm
- ch-3 — Sensing and Separation: the two reasons to break dependencies; fake objects and mocks
- ch-4 — The Seam Model: seam definition, enabling points, seam types (preprocessing/link/object) and how to choose
- ch-5 — Tools: refactoring-tool trust checks; xUnit; FIT/Fitnesse
- ch-6 — I Don't Have Much Time and I Have to Change It: Sprout Method, Sprout Class, Wrap Method, Wrap Class
- ch-7 — It Takes Forever to Make a Change: lag time, build dependencies, Dependency Inversion, compilation firewalls
- ch-8 — How Do I Add a Feature?: TDD in legacy code (step 0); Programming by Difference; LSP; normalized hierarchies
- ch-9 — I Can't Get This Class into a Test Harness: irritating parameters, hidden dependencies, construction blobs, global/singleton dependencies, include dependencies, onion & aliased parameters
- ch-10 — I Can't Run This Method in a Test Harness: private methods, sealed/final library classes, undetectable side effects, Command/Query Separation
- ch-11 — What Methods Should I Test?: effect reasoning, effect sketches, effect-propagation heuristic
- ch-12 — Many Changes in One Area: interception points, pinch points, pinch-point traps
- ch-13 — I Don't Know What Tests to Write: characterization tests (algorithm), targeted testing of branches and conversions, handling bugs found while characterizing
- ch-14 — Dependencies on Libraries Are Killing Me: wrappers, the once dilemma, the restricted-override dilemma
- ch-15 — My Application Is All API Calls: Skin and Wrap the API vs Responsibility-Based Extraction
- ch-16 — I Don't Understand the Code: sketching, listing markup, scratch refactoring, deleting unused code
- ch-17 — My Application Has No Structure: telling the story of the system, Naked CRC, conversation scrutiny
- ch-18 — My Test Code Is in the Way: naming conventions and placement for tests, fakes, testing subclasses
- ch-19 — My Project Is Not Object Oriented: seams in procedural code; function pointers; migrating toward OO
- ch-20 — This Class Is Too Big: Single Responsibility Principle; 7 heuristics for seeing responsibilities; feature sketches; ISP; safe class extraction without tests
- ch-21 — I'm Changing the Same Code All Over the Place: duplication removal, orthogonality, Open/Closed
- ch-22 — I Need to Change a Monster Method and I Can't Write Tests for It: sensing variables, coupling count, gleaning dependencies, Break Out Method Object, skeletonize vs find-sequences
- ch-23 — How Do I Know That I'm Not Breaking Anything?: hyperaware editing, single-goal editing, Preserve Signatures, Lean on the Compiler, pairing
- ch-24 — We Feel Overwhelmed: morale strategy for legacy teams
- ch-25 — Dependency-Breaking Techniques: the 24-technique catalog (each designed to be safe without tests)
- app — Appendix: Extract Method mechanics

## ch-1 — Changing Software {#ch-1}

Four reasons to change software: **add a feature**, **fix a bug**, **improve design (refactoring)**, **optimize**. All four share one structure: a small amount of intended behavioral change against a vast amount of behavior that must be preserved. Refactoring holds functionality invariant and changes structure; optimization holds functionality invariant and changes resource usage; feature addition/bug fixing change a sliver of functionality while preserving the rest.

- Distinction that matters to a programmer: **adding code and calling it** usually adds behavior; **modifying existing code** changes behavior. Adding an uncalled method changes nothing.
- Three risk questions before any change: (1) What changes do we have to make? (2) How will we know we've done them correctly? (3) How will we know we haven't broken anything?
- If a team's risk policy is "minimize the number of changes" ("if it's not broke, don't fix it"), methods and classes grow, understanding decays, and fear compounds. Avoiding change makes you worse at change — the skill atrophies. The failure isn't caution; it's caution without a safety mechanism.
- Preface definition (retrieval key): **legacy code = code without tests**. Code without tests is bad code regardless of how clean it looks, because you cannot change it quickly and verifiably.

## ch-2 — Working with Feedback {#ch-2}

Two ways to change a system: **Edit and Pray** (plan carefully, change, poke around and hope) and **Cover and Modify** (put tests around the change area first, then change with feedback). Edit and Pray masquerades as professional "working with care" — but care without the right tools is a surgeon with a butter knife.

- **Testing to detect change** (regression at the unit level) vs testing to show correctness. Tests around a change act as a **software vise**: behavior is clamped in place so you know you are changing only what you intend.
- Overnight/system-level regression runs give feedback in hours and localize errors poorly; unit tests give feedback in seconds. "Do you want your feedback in a minute or overnight?"
- **Unit test qualities**: runs fast, localizes problems. **A unit test that takes 1/10th of a second is a slow unit test** (30,000 such tests ≈ an hour per run). A test is **not** a unit test if it: (1) talks to a database, (2) communicates across a network, (3) touches the file system, (4) requires special environment setup (e.g., editing config files). Such tests are worth having — but keep them separate so the fast suite stays fast.
- **The Legacy Code Dilemma**: *when we change code, we should have tests in place; to put tests in place, we often have to change code.* Resolution: break dependencies with the most conservative, lowest-risk edits available (the ch-25 catalog), accepting temporary ugliness — "like incision points in surgery: there might be a scar, but everything beneath it can get better."

**The Legacy Code Change Algorithm** (the book's spine — follow in order for every change to untested code):
1. **Identify change points** (where the code must change — ch-16, ch-17).
2. **Find test points** (where effects of the change can be sensed — ch-11, ch-12).
3. **Break dependencies** (the minimum needed to get the code into a harness — ch-9, ch-10, ch-23, ch-25).
4. **Write tests** (characterization tests pinning current behavior — ch-13).
5. **Make changes and refactor** (TDD for new behavior — ch-8, ch-20–22).

Goal per programming episode: deliver the functional change *and* leave its area covered by tests. Tested areas grow "like islands rising out of the ocean" until you work in continents of covered code.

## ch-3 — Sensing and Separation {#ch-3}

Two — and only two — reasons to break dependencies for testing:
1. **Sensing** — we can't access the values our code computes (effects go into hardware, a display, another subsystem).
2. **Separation** — we can't even get the code into a test harness to run it.

There are many separation techniques (ch-25 catalog) but one dominant sensing technique: **faking collaborators**.

- **Fake object**: impersonates a collaborator during test. Canonical example: `Sale.scan()` writes to a cash-register display → introduce `Display` interface; `ArtR56Display` (real hardware) and `FakeDisplay` both implement it; the test asserts `display.getLastLine()` equals `"Milk $3.99"`.
- A fake has **two sides**: the interface methods the tested class sees (`showLine`) and the sensing methods only the test sees (`getLastLine`) — which is why tests hold the reference as `FakeDisplay`, not `Display`.
- "That's not really testing" objection: a fake-based test doesn't prove pixels appear on real hardware — it tells you exactly how `Sale` affects displays, which localizes failures. Divide and conquer.
- **Mock object** = fake that performs assertions internally (`setExpectation(...)` / `verify()`). Powerful, but simple hand-written fakes suffice in most situations and exist in every language.

Canonical fake, compressed:

```java
class FakeDisplay implements Display {          // interface side: what Sale sees
    private String lastLine = "";
    public void showLine(String line) { lastLine = line; }
    public String getLastLine() { return lastLine; }  // sensing side: what the test sees
}
// test: sale.scan("1"); assertEquals("Milk $3.99", display.getLastLine());
```

In non-OO languages the same move is an alternative function that records values into a global structure the test can read (ch-19).

## ch-4 — The Seam Model {#ch-4}

Reframes programs from "a sheet of text" to a set of substitution points.

- **Seam**: *a place where you can alter behavior in your program without editing in that place.*
- **Enabling point**: every seam has one — the place where you decide which behavior runs. If you can't point at an enabling point, it isn't a seam.

Canonical object seam (the `PostReceiveError` example, C++): a global function call inside a method is made replaceable without editing the method —

```cpp
class CAsyncSslRec {                       // 1. add same-signature virtual that
  virtual void PostReceiveError(UINT t, UINT e)   //    delegates to the global
  { ::PostReceiveError(t, e); }
};
class TestingAsyncSslRec : public CAsyncSslRec {  // 2. subclass nulls it out
  virtual void PostReceiveError(UINT t, UINT e) {}
};
// 3. enabling point: the place where the object is created
```

The body of `Init()` never changes; behavior at the call changed anyway. That is the seam property.

Seam types, with detection cues:

| Seam type | What it is | Enabling point | Detection cue in code |
|---|---|---|---|
| **Object seam** | A call whose target method can be replaced via polymorphism (subclass-and-override, or pass a different object) | Where the object is created or passed (constructor/argument list) | Call on a reference whose concrete class is decided *elsewhere* (`cell.Recalculate()` where `cell` is a parameter). NOT a seam: object `new`ed and used in the same method — no enabling point. A `private static` call is convertible: make it `protected` instance and it becomes a seam |
| **Link seam** | Call resolved by linker/classpath/library search; substitute a stub library or class | Build script, makefile, classpath — always *outside* the program text | Direct calls to library functions (`drawLine(...)`), imports resolved at runtime. Cue that you can use it: pervasive third-party calls with a "tell" interface (few return values) |
| **Preprocessing seam** | C/C++ macro preprocessor rewrites text before compilation (`#include "localdefs.h"` + `#define db_update(...)`) | A preprocessor define (e.g., `TESTING`) | C/C++ only; global function calls you can macro-replace |

- Rule of preference: **object seams first** in OO languages; link and preprocessing seams are less explicit, harder to notice (the enabling point is outside the code), and tests depending on them are harder to maintain. Reserve them for pervasive dependencies with no better alternative. If you use link seams, make the test/production environment difference obvious.
- One call site can offer several seams at once (the `PostReceiveError` example offers all three); choosing the seam type is a design decision.

## ch-5 — Tools {#ch-5}

- A change is a refactoring **only if it doesn't change behavior**; refactoring tools should verify this, and many don't at the fringes. Trust but verify: run sanity checks on a new tool (does extract-method flag name collisions with base-class methods?).
- Canonical tool-betrayal example: automated "inline temp" of `int v = getValue()` into a loop body turned 1 call of `getValue()` (which increments `alpha`) into 10 — behavior changed, tool said nothing. If your tool's refactorings don't preserve behavior, follow the no-tool (test-first) advice instead.
- Chains of purely automated, verified refactorings may be performed without tests; the hazard is the manual edits *between* tool uses.
- Test harnesses: **xUnit** (JUnit, CppUnitLite, NUnit) — tests in the development language, isolated test objects, `setUp`/`tearDown` per test, suites. **FIT/Fitnesse** for table-driven, customer-facing tests. The most effective testing tools the author knows are free; expensive GUI-driving test tools routinely under-deliver because UIs are volatile and too far from the tested functionality.

## ch-6 — I Don't Have Much Time and I Have to Change It {#ch-6}

Techniques for adding **tested new code** when you cannot afford to get the existing host code under test right now. Caveat that applies to all four: the new code is tested, but its *use* by the untested host is not.

- **Sprout Method**: formulate the change as new code; write a new method for it via TDD; call it from the untested method. Steps:
  1. Identify the change point.
  2. Write the call for the new method at that point, then comment it out (lets you see the call in context first).
  3. Determine which local variables you need; make them arguments.
  4. Decide whether the sprout must return a value to the source method.
  5. Develop the sprout with TDD.
  6. Uncomment the call.

  Micro-example — duplicate-entry check added to untested `postEntries`:

  ```java
  // inline (bad): loop grows an if + temp inside untested code
  // sprouted (good):
  List entriesToAdd = uniqueEntries(entries);   // new, TDD'd method
  for (Iterator it = entriesToAdd.iterator(); ...) { ... }
  ```

  Prefer it whenever new work is a distinct piece — far better than inlining, which mingles responsibilities and hides mistakes. If instantiation is impossible, make the sprout a `public static` taking instance state as arguments (statics are a legitimate "staging area"). Disadvantage: you're giving up on the source method for now — new code lives beside a carcass, which at least marks future work.
- **Sprout Class**: same, but the change goes on a *new class* when the host class can't be instantiated in a harness in reasonable time (creational/hidden dependencies), or when the change is a new responsibility anyway. Cost: conceptual complexity — abstractions get gutted into side classes. Some sprouted classes later fold into existing concepts (rename `...TableHeaderProducer` → `...TableHeaderGenerator`, extract common `HTMLGenerator` interface); others become new concepts. Don't demand it look right on day one.
- **Wrap Method**: rename the old method, create a new method with the *original name* that calls the new behavior + the old method. Use when the new behavior must run every time the old is called:

  ```java
  public void pay() {          // callers unchanged
      logPayment();            // new, TDD'd
      dispatchPayment();       // = old pay(), renamed, now private
  }
  ```

  Second form: add a differently-named method (`makeLoggedPayment`) that composes old + new — callers opt in. Advantage over sprouting: existing method doesn't grow at all; new feature is explicitly not intertwined (avoids **temporal coupling** — grouping code only because it runs at the same time). Constraint: the new feature must be separable — it runs before or after the old code, not interleaved with it (which is a feature, not a bug). Cost: you must invent a name for the old code, and it's often a poor one until tests allow further extraction.
- **Wrap Class** (decorator): a new class implements the same interface, holds the original, adds behavior around delegation. Use when many callers need the new behavior transparently, or when the class is so big you refuse to make it bigger ("wrap just to put a stake in the ground"). Use decorators sparingly — nesting them is peeling an onion. Non-decorator variant: a small class that takes the wrapped object and exposes a composed operation, when the behavior is needed in only a couple of places.
- Sprout vs Wrap: sprout when the existing method still communicates a clear algorithm; wrap when the new feature is as important as the existing work.

## ch-7 — It Takes Forever to Make a Change {#ch-7}

Two causes: **understanding** (see ch-16/17) and **lag time** — the gap between making a change and getting real feedback (the Mars-rover analogy: 14-minute feedback loops make everyone bundle changes). Target: recompile and run tests for any class in **< 10 seconds**; you should be able to compile every class separately from the others in its own test harness.

- Mechanism: break build dependencies with interfaces. Extract interfaces/implementers for classes used across a cluster; dependents then recompile only when the *interface* changes. This builds a **compilation firewall**.
- **Dependency Inversion Principle**: depend on interfaces or abstract classes rather than concrete classes — less volatile targets mean fewer forced recompiles and fewer ripple changes.
- Accounting: more interfaces/packages make a *full* rebuild slightly slower but make the *average* incremental build dramatically faster. Pay the one-time cost per cluster; reap it forever.

## ch-8 — How Do I Add a Feature? {#ch-8}

Sprouting/wrapping without tests carries hazards: the old code doesn't improve, duplication festers, and fear becomes ambient. When you *can* get code under test, prefer confronting it.

- **TDD algorithm**, extended for legacy code:
  0. **Get the class you want to change under test.**
  1. Write a failing test case.
  2. Get it to compile.
  3. Make it pass — *trying not to change existing code as you do*.
  4. Remove duplication.
  5. Repeat.

  TDD's core value in legacy work: you are either writing new code or refactoring — never both at once. Brutal copy/paste of an existing method to make a variant (the `firstMomentAbout` → `secondMomentAbout` example, later unified as `nthMomentAbout`) is acceptable *during* the green step **only because** step 4 (remove duplication) is mandatory — skipping it converts the technique into plain duplication.
- **Programming by Difference**: introduce a variation quickly by subclassing and overriding (e.g., `AnonymousMessageForwarder` overrides `getFromAddress`); once tests pin the new behavior, refactor to a better structure (configuration object, delegation to a new concept — `MailingConfiguration` → renamed `MailingList`). Inheritance is the entry move, not the destination; features locked into sibling subclasses can't be combined.
- **Liskov Substitution Principle**: subclass objects must be substitutable for superclass objects everywhere. Rules of thumb: avoid overriding concrete methods; if you must, call the overridden method from the override. The `Square extends Rectangle` example: `setWidth(3); setHeight(4); area == 16` silently violates client expectations.
- **Normalized hierarchy**: no class has more than one implementation of any method (methods are either abstract or implemented in exactly one place in the chain). "How does this class do X?" then has one answer. Occasional concrete overrides are fine; drift too far and reasoning breaks down.
- "Rename Class is the most powerful refactoring" — it changes how people see the code and what they notice.

## ch-9 — I Can't Get This Class into a Test Harness {#ch-9}

The four common blockers: (1) objects of the class can't be created easily, (2) the harness won't build with the class in it, (3) the constructor has bad side effects, (4) significant work happens in the constructor and we need to sense it.

- **First move — the construction test**: don't analyze; write it and let the compiler tell you what's needed. Cheapest possible probe.

  ```java
  public void testCreate() {
      CreditValidator validator = new CreditValidator();  // no assertion —
  }                                                       // compiling/running IS the test
  ```

  Rename or delete the construction test once real tests exist.
- **Irritating parameter** (constructor needs something slow/unavailable, e.g., a live `RGHConnection`): **Extract Interface (ch-25)** on the parameter's class and pass a fake. Or **Pass Null** — pass `null` for parameters the test path never touches; safe in Java/C# (runtime throws, harness catches), *never* in C/C++ (silent memory corruption). Never pass null in production code — prefer the **Null Object pattern** (e.g., `NullEmployee` whose `pay()` does nothing) when clients don't need to care about lookup failure; beware counting bugs when nulls are counted as real objects.
- **Hidden dependency** (constructor `new`s a problematic collaborator internally, e.g., `new mail_service` + magic number 12): **Parameterize Constructor** — pass the collaborator in; keep the original signature as a forwarding constructor so *no callers change*:

  ```java
  public MailChecker(int checkPeriodSeconds) {           // original signature survives
      this(new MailReceiver(), checkPeriodSeconds);
  }
  public MailChecker(MailReceiver receiver, int checkPeriodSeconds) { ... }
  ```
- **Construction blob** (constructor creates objects from other objects it just created): **Extract and Override Factory Method** (not in C++ — virtual calls in constructors don't dispatch to subclasses); fallback **Supersede Instance Variable** (a `supersedeCursor(newCursor)` setter used only in test; in C++ mind the delete/ownership of the replaced object).
- **Irritating global / singleton** (`PermitRepository.getInstance().findAssociatedPermit(...)` in 10 classes): **Introduce Static Setter** (`setTestingInstance`) + relax the constructor to `protected`; each test must be a mini-application, so the singleton property must be relaxable under test. Alternative: `resetForTesting()` in setUp/tearDown when public methods can configure state. Interrogate *why* single instance is required:
  1. Modeling something with real-world singleness (one hardware board, one database) — sometimes legitimate.
  2. Two instances would be a serious problem (two controllers on the same nuclear control rods).
  3. Two instances would use too many resources (disk, memory, licenses).

  Most singletons match none of these — they exist to be global variables ("too painful to pass it around"), and that reason doesn't deserve constructor-level protection. Protect genuine single-instance invariants with build checks, runtime alarms on `setTestingInstance`, or team rules instead. Globals invert reasoning: with `Account example = new Account(); example.deposit(1);` you know exactly what can be affected; with globals, any use of a class may touch state declared anywhere. Also usable: **Subclass and Override Method** to neuter the DB-touching method of the singleton subclass; or Extract Interface on the singleton + Lean on the Compiler to convert all references. Exercise: pick any global and search — "globally accessible" almost never means globally *used*; localizing the users shows the refactoring. A global used truly everywhere means the code has no layering (ch-15, ch-17).
- **Horrible include dependencies** (C++): create tests in the same directory, provide alternate definitions of offending methods in the test file (separate test program). Last-resort technique for huge classes; duplicate definitions must be maintained until real dependency breaking happens.
- **Onion parameter** (need A to build B to build C…): you need only what the *test* needs from each layer — Pass Null, or Extract Interface/Extract Implementer on the most immediate dependency.
- **Aliased parameter** (parameter's type is one of a class hierarchy; extracting interfaces all the way down would produce a 1:1 interface-per-class mess): don't sever the whole class — sever only the problem part. **Subclass and Override Method** on the parameter class (e.g., `AlwaysValidPermit extends FakeOriginationPermit` overriding DB-touching `validate()`); anonymous/local classes in tests are fine.

## ch-10 — I Can't Run This Method in a Test Harness {#ch-10}

Blockers: method not accessible (private), parameters hard to build, bad side effects (modifies DB, launches missile), or we need to sense through an object it uses.

- **Hidden (private) method**: first ask — can you test it through a public method? If yes, do that: it tests the method *as used* and doesn't over-generalize it. If you genuinely need direct tests: **if you have the urge to test a private method, the method shouldn't be private**. If making it public bothers you, the class is doing too much (ch-20) — move the method to a new class where it can be public. Interim compromise: make it `protected` and expose via a testing subclass (`using CCAImage::setSnapRegion` in C++). Reflection-based access to privates is a cheat that hides how bad the code is getting — delaying the bill.
- **"Helpful" language feature** (sealed/final library classes with private constructors, e.g., `HttpServletRequest`/`HttpPostedFile`): you can't extract an interface from what you don't own. **Adapt Parameter (ch-25)**: introduce your own narrow interface (`ParameterSource` / `IHttpPostedFile`) + production wrapper + fake. Root fault: depending directly on library classes you don't control (ch-14).
- **Undetectable side effect** (a handler that computes, creates windows, and writes to widgets in one blob, e.g., `AccountDetailFrame.actionPerformed`): extract the event unpacking, then extract each GUI access into intention-named methods (`getAccountSymbol`, `setDisplayText`) — names must hide the display mechanics — then **Subclass and Override Method** on those to sense. Coarse, ugly extractions are a legitimate first step; safety first, clean later.
- **Command/Query Separation** (Meyer): a method should be a command (mutates, returns nothing) or a query (returns, doesn't mutate) — never both, so queries can be called freely in tests and reasoning.

## ch-11 — What Methods Should I Test? (Effect Reasoning) {#ch-11}

To know where tests must go, reason *forward* from change points: what can this change affect, and where can that be sensed?

- **Effect sketch**: bubbles for each variable that can change and each method whose return value can change; arrows toward everything affected. Minimal syntax, disposable.
- Effects propagate exactly three ways: (1) **return values** used by callers, (2) **modification of objects passed as parameters** and used later, (3) **modification of static/global data**. (Plus exotica like aspects.)
- Heuristic for finding effects: identify the changing method → if it returns a value, look at callers → look at values it modifies and their users, transitively → include superclasses/subclasses using the same variables/methods → check parameters (does anything the change touches share objects with them?) → check global/static mutation.
- **Know your language's firewalls**: `private` fields end propagation; package-scope fields don't (subclasses and package neighbors may write them); Java `String` is immutable, so `getName()` can't drift; C++ `const` can lie (`mutable` members are writable from `const` methods). Learning where you *don't* have to look is the payoff of good encapsulation.
- Canonical exercise (`CppClass(String name, List declarations)`): what can change results after construction? The list is held *by reference*, so callers appending to it, or mutating the `Declaration`s inside it, alter `getDeclarationCount`/`getDeclaration`/`getInterface` later. Trace the single population site (`matchVirtualDeclaration`) to prove nothing mutates post-construction, then mark references `final` to encode the proof.
- Cultivate "**but that would be stupid**" rules: contextual invariants a codebase honors (e.g., "constructor-received collections are never mutated afterward"). Good code bases accumulate them and become cheap to reason about; in bad ones the rules have exceptions and paranoia is mandatory.
- Removing tiny duplication (e.g., `getInterface` calling `getDeclaration` instead of duplicating the cast) shrinks the effect sketch's endpoints → fewer places must be tested.
- Encapsulation vs testability: encapsulation is a tool for reasoning, not an end. **When encapsulation and test coverage conflict, bias toward test coverage** — tests give you a stronger reasoning tool and often buy encapsulation back later.

## ch-12 — Many Changes in One Area: Interception Points and Pinch Points {#ch-12}

Do you have to break dependencies for every class involved in a multi-class change? Often no — test "one level back."

- **Interception point**: any place where the effects of a change can be detected. Prefer interception points *close to* change points, for two reasons:
  1. **Safety** — every step between change point and interception point is a step in an informal argument ("this affects this, which affects that…"); more steps, weaker argument. Sometimes the only way to validate a distant one is to break the change point deliberately and confirm the test fails.
  2. **Setup cost** — distant interception points force you to "play computer" to know a test covers the change.

  In most cases the best interception point is a public method on the class being changed.
- **Pinch point**: a narrowing in the effect sketch — a place where tests against one or two methods can detect changes in many methods (e.g., `BillingStatement.makeStatement` covers changes across `Invoice` and `Item`). Pinch points are determined by the *change points*, not by the class diagram: a class with many clients can still have a good pinch point if the planned changes don't affect the other clients.
- If no pinch point exists for the whole change set, split the change set — find pinch points for one or two changes at a time, or test each change as close as possible.
- Pinch points reveal design: a pinch point is a **natural encapsulation boundary** — a candidate interface/class. (Corresponding intra-class trick: an effect sketch of a big class exposes hidden classes, e.g., `parseExpression` → `getToken`/`hasMoreTerms` → extract `Tokenizer`.)
- **Pinch point trap**: unit tests that slowly grow into mini-integration tests (instantiating clusters of collaborators). Higher-level covering tests at pinch points are a *first step*, scaffolding for refactoring — write narrower unit tests as you go and **delete the pinch-point tests when class-level tests support the work**. They are not a substitute for unit tests.

## ch-13 — Characterization Tests {#ch-13}

Bug-finding in legacy code is misdirected effort as a testing goal — you'd never finish. Tests for legacy work exist to **preserve behavior** (detect change), and "what the system does is more important than what it is supposed to do." Don't write tests from old requirements documents; that's bug hunting in disguise.

**Characterization test**: a test that documents the *actual current behavior* of a piece of code.

Writing algorithm:
1. Use the code in a test harness.
2. Write an assertion you know will fail.
3. Let the failure tell you what the behavior actually is.
4. Change the test to expect the behavior the code produces.
5. Repeat.

```java
assertEquals("fred", generator.generate());     // step 2: known-wrong expectation
// harness: ComparisonFailure: expected:<fred> but was:<>   ← step 3
assertEquals("", generator.generate());          // step 4: document the fact
```

The finished test documents a basic fact: a freshly created `PageGenerator` generates the empty string. Feed it other inputs the same way and harvest each actual value from the failure message.

- These tests have no moral authority; they document what the code really does. That's exactly their value: the alternative is re-"playing computer" in your head on every change.
- You are *not* writing black-box tests — read the code, get curious, write tests until you understand it, then check that the tests would catch the mistakes your planned change could introduce; if not, add more or shrink the change.
- **When you find a bug while characterizing**: if the system was never deployed, fix it. If deployed, someone may depend on the behavior — mark the test as suspicious, escalate, and find out the impact of fixing before changing it.
- **The Method Use Rule**: before you *call* a method in a legacy system, check for tests on it; if there are none, write them. Tests become the medium of communication about what a method can be expected to do.
- **Targeted testing**: after characterizing the area, test the specific things you'll change: (a) verify each branch you'll touch is actually executed by some test — ask "could this test pass without executing this branch?"; use a **sensing variable** or debugger if unsure; (b) exercise every *type conversion* along the path (the double→long truncation example: a test using values below the corp minimum passed while the refactored code silently truncated) — pick inputs that would expose a wrong-type extraction. Manual value calculation, debugger stepping, sensing variables, or characterizing a smaller chunk are the tactics.
- Most characterization tests are "sunny day" tests — presence-of-behavior checks that let you infer a refactoring preserved and correctly connected the behavior. Two questions after any refactor: does the behavior still exist, and is it connected correctly?
- Class-level characterization heuristics:
  1. Probe tangled logic you don't understand with **sensing variables** (ch-22) to confirm which paths execute.
  2. As you discover responsibilities, list what can go wrong and write tests that try to trigger it.
  3. Test extreme input values.
  4. Try to assert **invariants** (conditions that must hold for the object's lifetime); refactoring to expose them teaches you the code.

  Order tests pedagogically — main intent first, idiosyncrasies after — they are documentation for the next reader.

## ch-14 — Dependencies on Libraries Are Killing Me {#ch-14}

- **Avoid littering direct calls to library classes through your code.** "You might think you'll never change them, but that can become a self-fulfilling prophecy" — one team's product died when a vendor raised royalties and the calls were unextractable. Every hard-coded library call is a place where a seam could have been.
- **The once dilemma**: a library that enforces singleton-ness makes fakes nearly impossible; sometimes wrapping the singleton is the only move.
- **The restricted override dilemma**: non-virtual/final/sealed methods block sensing and separation. Library designers who use language features to enforce design constraints forget code must run in *two* environments: production and test. Team convention ("treat this public method as non-virtual in production, override it only in test") is often as good as the language feature and keeps testability.
- When a library class is sealed/final: isolate it behind a thin wrapper so you have wiggle room (see ch-10 Adapt Parameter, ch-15).

## ch-15 — My Application Is All API Calls {#ch-15}

"We're just calling a library, we don't need tests" is how many legacy systems started. API-intensive systems are hard because (a) the design is invisible — all you see are calls — and (b) you don't own the API, so you can't rename or extend it.

Procedure: write a one-paragraph description of what the code does → separate responsibilities (in the mailing-list server: receive messages / send a message / build outgoing messages from incoming ones / periodic wake-up) → note which responsibilities are API-bound and which are logic. Nearly every system has core logic that can be peeled away from API calls.

Two migration strategies:

| Strategy | Mechanics | Choose when | Cost |
|---|---|---|---|
| **Skin and Wrap the API** | Interfaces that mirror the API 1:1; wrappers delegate; Preserve Signatures | API is small; you want total separation from the vendor; you can't test through the API at all | More upfront work; a thin untested delegation layer remains |
| **Responsibility-Based Extraction** | Extract intention-named methods/classes for responsibilities (e.g., `MailSender.sendMessage`) | API is complicated; you have a safe extract-method tool (or confidence by hand) | Extracted code may keep API dependencies → some of it stays untestable |

Many teams use both: a thin wrapper for testing plus a higher-level wrapper presenting a better interface. Note Java traps: `Session` is final — can't wrap it directly; plan around what the language permits.

## ch-16 — I Don't Understand the Code Well Enough to Change It {#ch-16}

Low-tech understanding tools that feel "suspiciously like not working" but pay off:

- **Notes/Sketching**: draw blobs and lines while reading; no UML required; the paper maintains mental state and makes pair conversation concrete.
- **Listing markup** (print the code): mark responsibility groups in colors; line up block start/ends for snarled indentation; circle candidate extractions and annotate with coupling counts (ch-22); mark change lines and everything they can affect (a paper effect sketch).
- **Scratch refactoring**: check out the code, refactor freely to learn it, **then throw the result away — never check it in**. No tests needed because nothing ships. Risks: a wrong move can teach you a false view of the system; and attachment to the scratch result can blind you to better structures later. It's for learning, not producing.
- **Delete unused code**: if code is confusing and provably unused, delete it. Version control remembers; "someone might need it" is what history is for.

## ch-17 — My Application Has No Structure {#ch-17}

Architecture degrades when nobody holds the big picture: too complex, no big picture exists, or the team is purely reactive. An architect who isn't in the code day-to-day diverges from reality. **Architecture is too important to be left to a few people** — every coder needs the big picture, or 17 of 20 people make unfamiliarity mistakes.

- **Telling the Story of the System**: explain the architecture in a few sentences using only 2–3 concepts, as if to someone who knows nothing; then add the next most important things. The forced simplification ("the gateway gets rule sets from the active database" — omitting the working set) feels like lying; each omission is a flag for what would ideally be simpler. Use the story to judge changes: prefer the change that makes the brief story *less* of a lie (JUnit example: report assertion counts through `TestResult` rather than bolting `buildUsageReport` onto `TestCase`).
- **Naked CRC**: blank index cards laid down and moved to describe instances and interactions. Two guidelines: cards represent **instances, not classes**; overlap cards to show collections.
- **Conversation scrutiny**: listen to design conversations — if the team keeps saying "locking policy" while writing inline count-bumping in arrays, the concept wants to be a class (`LockingPolicy`). If concepts in conversation don't overlap concepts in code, ask why. Design is never "over"; a team that believes it is will bloat classes rather than introduce abstractions.

## ch-18 — My Test Code Is in the Way {#ch-18}

Conventions (ergonomics of navigation is the criterion):

| Kind | Convention | Example |
|---|---|---|
| Test class | `Test` suffix (sorts adjacent to the class) | `DBEngineTest` |
| Fake collaborator | `Fake` prefix | `FakeAccountOwner` |
| Testing subclass (for Subclass and Override) | `Testing` prefix | `TestingCheckingAccount` |

- Default: tests live in the same directory/package as the code — navigation friction ("a tax as you work") kills test writing. Separate trees only for a real reason (deployment size on customer machines); Java allows same-package/two-directories; or strip test binaries at build time. Don't separate for aesthetics.

## ch-19 — My Project Is Not Object Oriented {#ch-19}

Procedural languages have few seams; the default strategy is: get a *large chunk* under test via a **pinch point (ch-12)** using **link seams** (fake library of stubbed functions) or the **preprocessing seam**, then develop with that feedback.

- Link-seam fakes are one-definition-per-executable: varying behavior per test means condition flags inside the stub — tedious. C's preprocessor gives finer control: `#ifdef TESTING #define ksr_notify(code,packet) #endif`, plus `#include "testscanner.tst"` at file end to keep tests in a separate file. Restrict macro games to test builds only.
- Bias toward **new functions** for new behavior (sprouting works procedurally): separate pure logic (`form_command` — testable string building) from dependency-bound wrappers (`send_command` — calls `mart_key_send`).
- **Replace Function with Function Pointer (ch-25)** or a struct of function pointers gives a substitution seam in C:

  ```c
  struct database {
      void (*retrieve)(struct record_id id);
      void (*update)(struct record_id id, struct record_set *record);
  };
  /* production init points at real db functions; tests point at fakes */
  db.update(loan->id, loan->record);
  ```
- If the language has an OO successor (C→C++, VB, COBOL/Fortran extensions), migrate incrementally: **Encapsulate Global References (ch-25)** — wrap the offending free function in a class (`ResultNotifier::ksr_notify` delegating to `::ksr_notify`), create a global instance, then wrap the calling function in a class and **Parameterize Constructor**. Preserve Signatures throughout.
- "All procedural programs are object oriented; it's a shame many contain only one object" — the whole program is the one object; encapsulating globals subdivides it.
- Object seams beat link/preprocessing seams long-term: visible in code, decompose the system, and double as extension points. Link/preprocessing seams get code under test but don't improve design.

## ch-20 — This Class Is Too Big {#ch-20}

Big-class problems: confusion (which of 60 methods matter?), task-scheduling collisions (many reasons to change → many people editing concurrently), and testing pain (over-encapsulation: "the stuff inside rots and festers" and people revert to Edit and Pray).

First aid: **Sprout Class/Sprout Method (ch-6)** so it gets no worse. Remedy: **Single Responsibility Principle** — a class should have one responsibility, one reason to change.

Seven heuristics for *seeing* responsibilities (discovery, not invention):
1. **Group methods** — list method names + visibility; cluster similar ones (`...Expression` methods; `nextTerm`/`hasMoreTerms`). Great as a team poster exercise.
2. **Look at hidden methods** — many private/protected methods ⇒ another class is dying to get out; the urge to test a private method is this signal (`nextTerm`/`hasMoreTerms` are odd as public on `RuleParser`, perfectly fine as public on `TermTokenizer` — encapsulation is preserved because the parser uses the tokenizer privately).
3. **Look for decisions that can change** — hard-coded "how" (which database, which API); extract intention-named methods around them; you may find a whole resource encapsulated.
4. **Look for internal relationships** — do some instance variables get used by only some methods? Draw a **feature sketch** (circles for variables and methods; arrows from each method to what it uses — the mirror image of an effect sketch). Clusters connected by few lines are pinch points inside the class → candidate extractions; circling groups and naming them is design exploration.
5. **Look for the primary responsibility** — describe the class in a single sentence. SRP can be violated at the **interface level** (huge surface) and the **implementation level** (the class actually does it all). Fix implementation first (extract + delegate = facade); fix the interface later via **Interface Segregation Principle** — per-client interfaces (`JobController` for clients that only run jobs), then optionally invert so the new class holds the logic and delegates to the old.
6. **Scratch refactoring (ch-16)** when you can't see anything.
7. **Focus on the current work** — the change you're making *now* often names one responsibility worth separating; don't try to fix all 20.

Strategy: don't binge-refactor big classes (stability drops even with tests); identify responsibilities, socialize them with the team, extract **as-needed** when changes touch them.

Tactics — extract class **without tests** (when the harness is unreachable), the conservative 7-step procedure:
1. Identify the responsibility to separate.
2. Move the instance variables that will go with it into a separate section of the class declaration.
3. For whole methods that will move: extract each body to a new method named `MOVING<OldName>` (Preserve Signatures), placed in the marked section.
4. For method *fragments* that will move: extract them likewise with the `MOVING` prefix.
5. **Manually text-search** (not the compiler) the class and all subclasses for uses of the variables you're moving — **variable shadowing makes Lean on the Compiler unsafe here**: commenting out a shadowed declaration just reveals the base-class one, and moving an overriding method silently rebinds callers to the base-class version.
6. Move the marked section to the new class; instantiate it in the old class; Lean on the Compiler to route calls through the instance.
7. Strip the `MOVING` prefixes (compiler navigates the renames).

The prefix is purely a mechanical way to guarantee no name clashes with inherited members before the move. Do it with a partner.

After extraction: the structure you have *works*; aim for "a few steps more maintainable," not the ideal design you sketched.

## ch-21 — I'm Changing the Same Code All Over the Place {#ch-21}

Duplication removal is not a re-architecture project; it's incremental, and the payoff compounds. Worked example: two network command classes (`AddEmployeeCmd`, `LoginCommand`) with parallel `write`/`getSize` logic reduced, step by tiny step (extract `writeField`, pull up to `Command`, extract differing `writeBody`/`getBodySize`, abstract `getCommandChar`, generalize fields into a list), to shells of subclasses that only set fields and a command char.

- Heuristics: **start small** (tiny duplications first — the big picture clarifies as you go); when two methods look roughly the same, **extract their differences into other methods** until they're identical, then keep one; don't agonize over which grouping (`aa(); b(); a(); bb()` vs `a(); ab(); ab(); b()`) — pick the one you can name, both beat the status quo.
- Payoff = **orthogonality** (independence): one knob per behavior. Change the field terminator or add an `AggregateCommand` (nested commands) by overriding one method. With duplication, each behavior has many knobs and every change is a scavenger hunt.
- "When you remove duplication zealously, **designs emerge**" — the field/body concepts were latent in the code; removal distilled them. This is the mechanism behind the **Open/Closed Principle** (open for extension, closed to modification): dedup'd code naturally accepts new features by subclassing/addition with few edits.
- Keep names consistent (`AddEmployeeCmd` → `AddEmployeeCommand`); inconsistent abbreviations (`Mgr` vs `Mngr`) make every use a guess.
- Judgment call at the end: near-empty subclasses may be fine — don't force clients onto static `Command.send(...)` calls just to kill two small classes.

## ch-22 — Monster Methods (No Tests Possible Yet) {#ch-22}

**Monster method**: hundreds/thousands of lines, navigation-defeating. Two shapes: **bulleted** (flat chunk-list, deceptive because temps flow between chunks) and **snarled** (dominated by deep nesting — "if you feel vertigo, it's a snarl").

With an automated refactoring tool: do a series of extractions **using the tool exclusively — no manual edits, not even statement reordering** (no tool verifies reordering is safe); goals: (1) separate logic from awkward dependencies, (2) introduce seams for testing. Hokey names (`commoditiesAreReadyForUpdate`) are fine; skeleton first, tests, then real design.

Without a tool — common extraction errors: forgetting to pass a variable (declaring a fresh local instead, compiler silent if an instance variable shadows), hiding/overriding a base-class method with the new name, wrong parameter/return types silently converting. Countermeasures:

- **Introduce Sensing Variable**: add a (public) instance variable set inside the hard-to-reach path, write tests proving the path executes, extract, re-run, delete variable and tests at the end of the refactoring session (not after each step — keeping them lets you undo and re-extract differently). Legitimate to add test-only code to production classes *temporarily*.

  ```java
  public boolean nodeAdded = false;      // sensing variable
  ...
  if (isBasicChild(node)) {              // condition just extracted
      paraList.add(node);
      nodeAdded = true;                  // test: assertTrue(builder.nodeAdded)
  }
  ```

  Also the progressive de-snarling tool: sense your way into deep nesting, extract conditions/bodies, repeat on the extracted methods.
- **Extract What You Know**: extract tiny chunks (2–5 lines) you're sure of; track the **coupling count** = values in + values out of the extraction (params + return; instance-variable accesses don't count — they're pure cut/paste).

  ```java
  // extracting max(a,b) from process(a,b,c): 2 in + 1 out → coupling count 3
  int maximum = max(a, b);
  ```

  Prefer low counts — the key extraction danger is a silent type-conversion error, and its likelihood scales with the number of values crossing the new interface. Count-0 extractions (no params, no return: commands on object state) are safest and build structural insight; naming them yields design perspective. Verify where each passed variable is *declared* before extracting, to get the signature right. In bulleted methods, ignore the visual chunk structure if the chunks share temps — hunt for low-count extractions inside and across chunks.
- **Gleaning Dependencies**: when secondary code (e.g., display calls) is tangled with critical logic (e.g., add logic), write tests for the *critical* behavior only, then extract the untested secondary code — deliberate, honest partial coverage that protects what matters.
- **Break Out Method Object (ch-25)**: move the whole method to a new class (`run()`/`execute()`); parameters become constructor args, locals become instance variables you can sense — production-legitimate, unlike sensing variables.
- Strategy knobs: **skeletonize** (extract condition and body separately — best when the control structure itself will be refactored; snarled methods lean this way) vs **find sequences** (extract condition+body together to reveal a linear sequence of operations; bulleted methods lean this way). **Extract to the current class first** even when the name screams another class (`recalculateOrder` → later `Order.recalculate`) — awkward-name-in-place is undoable; cross-class moves aren't. **Extract small pieces.** **Be prepared to redo extractions** — the first cut buys insight, not a commitment.

## ch-23 — How Do I Know That I'm Not Breaking Anything? {#ch-23}

Code doesn't fatigue — the only way it breaks is somebody editing it. Practices that lower edit risk:

- **Hyperaware editing**: classify every keystroke as behavior-changing or not; fast tests close the loop and make this a flow state rather than a memory burden.
- **Single-goal editing**: "programming is the art of doing one thing at a time." When a second concern appears mid-edit ("I should clean this up"), write it on a card and finish the current change; ask your pair to challenge you with "what are you doing?" — if the answer is two things, pick one.
- **Preserve Signatures**: when breaking dependencies without tests, copy/paste *entire* method signatures verbatim rather than "improving" them mid-move. The mechanical drill:
  1. Copy the whole argument list into the paste buffer.
  2. Type the new empty method declaration.
  3. Paste the buffer into it.
  4. Type the call to the new method.
  5. Paste the buffer into the call.
  6. Delete the types in the call, leaving argument names.

  The author's cautionary tale: bundling cleanup (new helper classes, unit changes like `interestRate * 100`) into an untested extraction produced late-found bugs. The drill becomes automatic and reliable; the remaining attention goes to real hazards (is the new name hiding a base-class method?).
- **Lean on the Compiler**: (1) alter a declaration to *cause* compile errors, (2) navigate the errors making the change (e.g., comment out globals after wrapping them in a class; every error site gets the `exchange.` prefix). Limits: **inheritance defeats it** — comment out `getX()` and get *no* errors if a superclass defines `getX()`; the code now silently calls that one. Same trap with shadowed variables. Know what the compiler will and won't find before trusting silence.
- **Pair programming**: legacy work is surgery; "doctors never operate alone." Especially when applying ch-25 techniques.

## ch-24 — We Feel Overwhelmed {#ch-24}

- Green-field rewrites aren't the escape they appear: the replacement team double-maintains against a moving target while the "legacy" team turns out to be tending the critical asset. "The grass isn't much greener."
- Morale mechanics: attitude beats code-base quality (teams with millions of bad lines can treat each day as a challenge); TDD something outside work to feel the contrast; as a team, pick **the ugliest, most obnoxious set of classes and get them under test** — beating the worst problem creates a sense of control, and oases of good code grow from there.

## ch-25 — Dependency-Breaking Techniques (catalog) {#ch-25}

All 24 techniques are refactorings **designed to be performed without tests, to get tests in place**. They are conservative by construction (Preserve Signatures, Lean on the Compiler) but not risk-free — pair, and re-read ch-23 first. Many will make a design-sensitive reviewer flinch; that's expected. They buy testability now; test-supported refactoring buys design later.

| Technique | Use when (trigger) | Mechanics (gist) | Cost / risk |
|---|---|---|---|
| **Adapt Parameter** | A method parameter's type is hard to fake and you can't Extract Interface on it (e.g., sealed API interface like `HttpServletRequest`) | Introduce your own narrow, responsibility-named interface (`ParameterSource`); production wrapper + fake implementer; change the method to take it | Does **not** Preserve Signatures — extra care; too-different simplified interface can introduce subtle bugs |
| **Break Out Method Object** | Long method that uses instance data; class hard to instantiate | New class; method params → constructor args; locals → instance variables; body → `run()`; original method delegates; use Extract Interface to cut the back-reference to the original class | Drastic; exposes formerly-private members (via getters/public methods); interim structure is odd until the class comes under test |
| **Definition Completion** (C/C++) | Worst-case dependencies; declarations in header, definitions elsewhere | Include the header in the test file; define the methods you need to neutralize right there | Requires a separate test executable; duplicate definitions are a maintenance burden — use only to break initial dependencies, then retire |
| **Encapsulate Global References** | Code under test reads/writes globals or free functions | New class holding the globals (or virtual methods delegating to free functions); global instance; comment out originals; Lean on the Compiler to prefix each use | First step only — follow with Static Setter / Parameterize Constructor/Method; if several globals are always used together, they belong in one class; name the class for the methods that will eventually live there |
| **Expose Static Method** | Method to change doesn't use instance data, but the class won't instantiate | Extract body to a `public static` (name from param: `validate(Packet)` → `validatePacket`); original delegates | Static area = "staging area" for code that belongs elsewhere; restrict visibility (package/protected) if misuse worries you |
| **Extract and Override Call** | One localized problematic call (often static/global, e.g., `StyleMaster.formStyles`) | Extract the call into a `protected` method; override in a testing subclass | Trivial with a tool; prefer Replace Global Reference with Getter when many calls hit the same global |
| **Extract and Override Factory Method** | Object creation hard-coded in a constructor | Extract creation into `protected makeX()`; override in testing subclass | **Not possible in C++** (no virtual dispatch in constructors) — use Supersede Instance Variable / Extract and Override Getter there |
| **Extract and Override Getter** | Constructor-created object used across the class; C++ | Lazy getter creates on first call; all uses go through the getter; override in testing subclass | Someone may use the variable before initialization — route *all* access through the getter; C++ lifetime/delete discipline; prefer Extract and Override Call for a single problem method |
| **Extract Implementer** | You want Extract Interface but the class's name *is* the right interface name (no rename tool) | Copy class as `ProductionX`; strip original to pure-virtual/abstract interface keeping the name; production class implements it; fix creation sites | Creation sites all change; hierarchies need recursive treatment (often better to Extract Interface with a new name instead) |
| **Extract Interface** | Need to fake a concrete collaborator; among the safest techniques | Empty interface → class implements it → change use sites to the interface type → Lean on the Compiler adds only the methods actually used | Don't extract all public methods — only what's used; non-virtual methods (C++/C#) can change dispatch when made virtual — add a new virtual delegating method instead; avoid `I`-prefix naming unless codebase convention |
| **Introduce Instance Delegator** | Static/utility methods with **static cling** (untestable innards) | Add instance methods that delegate to the statics; pass an instance to the call sites | Half-migrated utility classes look weird; finish by moving bodies into instance methods when all calls delegate |
| **Introduce Static Setter** | Singleton (or global factory) needed in a specific state per test | `setTestingInstance(...)` static setter; constructor private→protected; subclass to fake; `resetForTesting()` variant when public methods can rebuild state; factories: delegate to a swappable `Server` interface | Weakens the singleton guarantee (protect via team rule/build check); global test state — reset in setUp/tearDown; ultimate goal is reducing global references until the singleton is a normal class |
| **Link Substitution** | Procedural/C code, or Java via classpath; want to replace whole functions/classes at link time | Build a dummy library with same-signature functions (record calls in a global structure for sensing); adjust build to link it in test | One definition per executable — per-test behavior variation is messy; enabling point invisible in code; best for "tell"-style libraries (graphics) |
| **Parameterize Constructor** | Constructor `new`s a collaborator internally | Copy constructor; add parameter; assign; old constructor delegates `this(new X(), ...)` — **no client changes** | Opens door for production dependencies on the parameter type (minor); C++ default-arg variant forces header include |
| **Parameterize Method** | A method creates an object internally | Copy method with an extra parameter; original delegates passing `new X()` | Same-name overload can confuse (`runWithTestResult` alternative); same new-dependency caveat; consider Extract and Override Factory Method instead |
| **Primitivize Parameter** | Class is a dependency black hole; the needed computation can run on primitives | Free function operating on primitives (TDD it); thin method on the class builds the primitive representation and delegates | Leaves code in a *poor* state: exposed representation, duplicated data, untested glue; use only with a commitment to fold it in later; often a prelude to Sprout Class |
| **Pull Up Feature** | The methods you must change don't touch the bad dependencies, which live elsewhere in the class | Pull the method cluster into a new **abstract** superclass; test through a concrete testing subclass | Spreads a class across two for testability; a delegation-based factoring is the real target later; abstract superclass so no "dead" concrete class appears |
| **Push Down Dependency** | Bad dependencies are pervasive but separable from the logic (e.g., UI message boxes inside validation) | Make the class abstract; push dependency-laden methods into a `WindowsX` production subclass; testing subclass nulls them | Inheritance-as-partition is interim; later pull logic up / delegate UI to a new class |
| **Replace Function with Function Pointer** (C) | Need a seam in pure procedural code without link games | Declare a function pointer with the original name; rename the real function `..._production`; initialize pointer at startup; tests repoint it | Compile-time only, zero build impact; teams differ on function-pointer safety; consider migrating to C++ for richer seams |
| **Replace Global Reference with Getter** | Class references a global/singleton in several methods | `protected getX()` returning the global; replace uses; testing subclass overrides the getter | Constructor relaxation on the singleton still needed for the fake subclass |
| **Subclass and Override Method** | The core OO technique — nullify behavior you don't care about or access behavior you do | Identify the *smallest* method set to override; loosen visibility to protected (C++: private virtuals overridable); testing subclass overrides | Easy to null out behavior your test actually needed — know what the test requires; factoring quality of the class determines how surgical you can be |
| **Supersede Instance Variable** | C++ constructor creates the object (virtual-in-constructor rule blocks factory method) | `supersedeX(newX)` method deletes old, assigns new; call in tests after construction | Resource-management risk (double ownership, deletes); never call superseders in production — the distinctive `supersede` prefix makes misuse greppable |
| **Template Redefinition** (C++ generics) | Dependency (e.g., `CSocket`) inside a class you can turn into a template | Rename class `XImpl<T>`; `typedef XImpl<CSocket> X;` production unchanged; tests instantiate `XImpl<FakeSocket>` | Implementation moves into headers → more recompilation for all users; prefer inheritance seams unless code is already templatized |
| **Text Redefinition** (interpreted langs; Ruby) | Need to neuter a method under test in a language with open classes | Reopen the class in the test file and redefine just that method | Redefinition persists for the whole program run — later tests silently inherit it |

Cross-cutting catalog rules: **Preserve Signatures (ch-23)** on every copy/move; **Lean on the Compiler (ch-23)** to find use sites, *except* where inheritance/shadowing hides them; when several catalog options exist, pick the one you can execute with the most confidence, not the one with the prettiest end state — "Safety first. Once you have tests in place, you can make invasive changes much more confidently."

Selection guide (dependency shape → default technique):

| Dependency shape | First choice | Fallbacks |
|---|---|---|
| Constructor argument hard to build/fake | Extract Interface on its class | Pass Null (Java/C#); Subclass and Override on the parameter; Adapt Parameter (unownable class) |
| Constructor internally constructs collaborator | Parameterize Constructor | Extract and Override Factory Method (not C++); Extract and Override Getter; Supersede Instance Variable (C++) |
| Single problematic call inside a method | Extract and Override Call | Subclass and Override Method |
| Many calls to the same global/singleton | Replace Global Reference with Getter | Introduce Static Setter; Encapsulate Global References; Parameterize Constructor/Method |
| Static method with static cling | Introduce Instance Delegator | Expose Static Method (if no instance data at all) |
| Long method on an uninstantiable class | Break Out Method Object | Expose Static Method (small, no instance data) |
| Pervasive dependencies, logic separable | Push Down Dependency / Pull Up Feature | Extract Interface repeatedly |
| Procedural (C) function call | Link Substitution | Replace Function with Function Pointer; preprocessing seam; Definition Completion |
| Everything else fails, computation isolable | Primitivize Parameter | Sprout Class |

Steps for the four highest-frequency techniques (verbatim procedure, safe without tests):

**Extract Interface** — (1) create the new interface, empty; (2) make the class implement it (nothing can break — compile/test anyway); (3) change the use site to the interface type; (4) compile; add a declaration to the interface for each method the compiler reports missing. Never renumber: only methods actually used get extracted.

**Parameterize Constructor** — (1) copy the constructor; (2) add the collaborator parameter, replace the internal `new` with an assignment from it; (3) gut the old constructor to `this(new X(), …)` (or extract shared init to a method in languages without constructor chaining).

**Subclass and Override Method** — (1) identify the *smallest* set of methods whose override achieves sensing/separation; (2) make each overridable (virtual in C++, non-final in Java, `virtual`/`override` in .NET); (3) loosen visibility to protected if the language requires it for overriding; (4) write the testing subclass and verify it builds in the harness.

**Break Out Method Object** — (1) create the new class; (2) constructor takes a reference to the original class + exact copies of the method's parameters (Preserve Signatures); (3) each constructor arg becomes an identically-typed instance variable assigned in the constructor; (4) empty `run()` method; (5) copy the method body into `run()`, compile, Lean on the Compiler; (6) satisfy errors by using the back-reference / making original members accessible (getters over public fields); (7) original method becomes create-and-delegate; (8) Extract Interface if the back-reference to the original class must be broken. Variations: no back-reference needed if the method uses no instance members; a data-holder class can replace the back-reference if only data is used.

## app — Appendix: Extract Method {#app}

The one refactoring mechanic reproduced in full (with tests in place): (1) comment out the code to extract (easy rollback if a test fails); (2) name and create an empty method; (3) call it from the original; (4) copy the code in; (5) Lean on the Compiler for parameters/returns; (6) adjust the declaration; (7) run tests; (8) delete the commented code. Extract Method is the workhorse for extracting duplication, separating responsibilities, and breaking down long methods.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Any planned edit to code with no tests around it | Run the legacy-code change algorithm: identify change points → find test points → break dependencies → write characterization tests → change/refactor | Edit-and-Pray has no mechanism to detect the behavior you broke | ch-2 |
| About to change/refactor an untested method's behavior | Write characterization tests first: assert a wrong value, let the failure reveal actual behavior, encode that | Actual behavior, not intended behavior, is what callers depend on | ch-13 |
| A test talks to a DB, network, or filesystem, or needs env/config setup | It is not a unit test — keep it, but out of the fast suite | Slow suites stop being run; 0.1s/test ≈ 1hr for 30k tests | ch-2 |
| Unit test takes ≥ 1/10th second | Treat as slow; break the dependency that makes it slow | Feedback latency determines how often tests run | ch-2 |
| Need to fake a collaborator but can't modify its class (sealed/final/library) | Adapt Parameter: define your own narrow interface + production wrapper + fake | You can't Extract Interface on what you don't own | ch-10, ch-25 |
| Constructor `new`s a problematic collaborator | Parameterize Constructor, keeping a delegating original-signature constructor | Callers unchanged; seam gained with near-zero risk | ch-9, ch-25 |
| Call on an object created and used in the same method | No object seam exists there — create an enabling point (parameter, factory method, getter) before trying to fake it | A seam requires an enabling point outside the edited code | ch-4 |
| Choosing among seam types in an OO language | Prefer object seams; use link/preprocessing seams only for pervasive dependencies with no alternative | Link/preprocessing enabling points are invisible in code and brittle to maintain | ch-4 |
| Urge to write a test for a private method | Test through the public method; if direct testing is truly needed, the method wants to be public on a new class | The urge is an SRP violation signal, not a tooling problem | ch-10, ch-20 |
| Reaching for reflection/access hacks to test privates | Don't — fix the design signal instead | Subterfuge hides how bad the code is getting; delays the bill | ch-10 |
| Must add a feature to a method/class you can't test now | Sprout Method/Class: TDD the new code separately, call it from the old | New code gets tests even when the host can't; inline additions mingle and hide | ch-6 |
| New behavior must run on every call of an existing method | Wrap Method: rename old, new method with old name calls both | Avoids temporal coupling; existing method doesn't grow | ch-6 |
| Passing `null` to skip an irritating constructor arg in a test | Fine in Java/C# (runtime throws); forbidden in C/C++ | Null deref must fail loudly, not corrupt memory | ch-9 |
| Tempted to return null / pass null in production code | Use Null Object pattern or a different protocol | Null checks metastasize through the codebase | ch-9 |
| Singleton blocks test setup | Introduce Static Setter + protected constructor; reset in setUp/tearDown; question whether singleton-ness is even needed | Each test must be a mini-application with isolated state | ch-9, ch-25 |
| Change spans several collaborating untested classes | Look for a pinch point one level back and characterize there before breaking each class | One test point can cover many change points; less dependency-breaking | ch-12 |
| Pinch-point/covering tests still in place after class-level tests exist | Delete or narrow them | Covering tests are scaffolding, not a substitute for unit tests | ch-12 |
| Found a bug while characterizing deployed code | Don't silently fix: mark the test suspicious, escalate, assess who depends on the behavior | Deployed "bugs" may be depended-upon behavior | ch-13 |
| About to call an untested method of a legacy system | Method Use Rule: check for tests; write them if absent | Tests are the medium of communication about the method's contract | ch-13 |
| Refactoring will move/extract a branch or a type conversion | Add a test that provably executes that branch and exercises the conversion (sensing variable/debugger if unsure) | "Sunny day" tests pass through silent truncations and dead branches | ch-13 |
| Direct third-party library calls scattered through the code | Route them through a thin wrapper you own | Every hard-coded library call is a seam you didn't get; vendor lock compounds | ch-14, ch-15 |
| Codebase is mostly API calls | Identify the computational core; Skin-and-Wrap (small API / total separation) or Responsibility-Based Extraction (big API / safe tool) | Core logic can almost always be peeled from API glue | ch-15 |
| Code confusing, needs understanding, no tests | Scratch refactor on a throwaway checkout — never commit it | Learning needs no safety net if nothing ships | ch-16 |
| Provably unused confusing code | Delete it; version control remembers | Dead code costs attention and misleads readers | ch-16 |
| Class has many private methods / a variable cluster used by few methods | Draw a feature sketch; extract the cluster as a class (heuristics 2 & 4) | Hidden methods and lumped variables are a latent class | ch-20 |
| Extracting a class with no tests | Use the MOVING-prefix procedure; search manually for shadowed variables and overridden methods — do NOT lean on the compiler | Shadowing/overrides make silent rebinding invisible to the compiler | ch-20 |
| Two methods look roughly the same | Extract their differences until identical, then keep one | Duplication removal makes designs emerge and creates one knob per behavior | ch-21 |
| Monster method + refactoring tool available | Tool-only extraction session: no manual edits, no reordering, hokey names allowed | Tool-verified steps are safe without tests; manual edits between them aren't | ch-22 |
| Monster method, no tool | Extract tiny (2–5 line) chunks with low coupling count; count-0 first; sensing variables for hard paths | Type-conversion and missed-variable errors scale with coupling count | ch-22 |
| Extraction's natural name references another class's variable | Extract to the current class first with the awkward name; move later | In-place extraction is undoable; cross-class moves aren't | ch-22 |
| Breaking a dependency without tests (any catalog technique) | Preserve Signatures: copy signatures verbatim; no bundled cleanup | Improvement bundled into untested moves is where the bugs hid | ch-23 |
| Using compile errors to find change sites | Verify inheritance won't swallow the change (superclass method/variable with same name) | Silence from the compiler is not proof of absence | ch-23 |
| Mid-edit urge to fix something else | Write it down, finish the current single goal | Doing one thing at a time is faster than heroic multi-front editing | ch-23 |
| Team demoralized by the codebase | Get the ugliest class cluster under test as a team | Beating the worst problem creates the sense of control that sustains the practice | ch-24 |
| Method mixes mutation and returning a value | Split per Command/Query Separation | Queries must be safely repeatable in tests and reasoning | ch-10 |
| A method's callers would all need one more argument for a new dependency | Add the parameter on a new constructor/method; keep the old signature delegating with the default | Seams shouldn't tax callers; forwarding keeps the diff local | ch-9, ch-25 |
| Incremental build/test loop for a class exceeds ~10 seconds | Break build dependencies: extract interfaces, split packages, build a compilation firewall | Feedback lag changes how people work — bundled changes, Mars-rover loops | ch-7 |
| Subclass overrides a concrete method | Check LSP; prefer abstract-method (normalized) hierarchies; call super from the override if kept | Concrete overrides silently change the meaning of existing references | ch-8 |
| Test suite state set via static setters | Reset globals in setUp AND tearDown | Leaked global state makes later tests lie | ch-25 |

## Anti-patterns

- **Edit and Pray** — detection: change plan with no test step; verification = "run the app and poke around". The industry-standard failure mode. (ch-2)
- **Legacy dilemma paralysis** — refusing to touch untested code because touching it without tests is unsafe; resolution is the conservative catalog, not abstinence. (ch-2)
- **Testing through the GUI / app interface only** — regression suites at the application boundary: overnight feedback, poor error localization, volatile selectors. (ch-2, ch-5)
- **Unit tests growing into mini-integration tests** — detection: tests instantiate clusters of collaborators; suite time creeps. Break the tested class down; fake collaborators. (ch-12)
- **Writing "should-do" tests for legacy code from requirements docs** — that's bug hunting; it doesn't produce the change-detection vise you need. (ch-13)
- **Reflection/`friend`/access-hack testing of privates** — hides the over-responsibility signal; the class never improves. (ch-10)
- **Temporal coupling** — code appended to a method only because it must run at the same time; later inseparable. Wrap instead. (ch-6)
- **Once dilemma / restricted-override library design** — sealed/final/non-virtual-by-default APIs and enforced singletons block test seams; language-level design "protection" ignores that code runs in test environments too. (ch-14)
- **Big-class over-encapsulation** — "encapsulation is great — don't ask the testers": 10–15 responsibilities hidden behind one interface; effects of change unknowable. (ch-20)
- **Refactoring binge** — dedicating a week to breaking down all the big classes; stability collapses even with tests; extract as-needed instead. (ch-20)
- **Green-field rewrite escape hatch** — replacement team double-maintains against a moving target; rarely lands. (ch-24)
- **Inconsistent abbreviations in names** (`XXXMgr` vs `XXXMngr`) — every use becomes a guess. (ch-21)
- **Lie-of-omission architecture** — features bolted where they make the simple system story *more* false (e.g., `TestCase.buildUsageReport`). Test candidate changes against the story. (ch-17)

## Applicability & exemptions

- **When NOT to write tests first** (the book's own sanctioned exceptions — do not flag these):
  - **Scratch refactoring**: refactoring untested code freely *on a throwaway checkout* to learn it, never committed (ch-16, ch-20 heuristic 6).
  - **Tool-verified automated refactorings**: a chain of behavior-preserving refactorings executed *entirely by a trusted tool* with no manual edits between (ch-5, ch-22) — but the tool must be verified to preserve behavior, and manual edits void the exemption.
  - **The ch-25 catalog itself**: all 24 dependency-breaking techniques are designed to run *before* tests exist, conservatively (Preserve Signatures, Lean on the Compiler, pairing). Flag catalog use without those disciplines, not catalog use per se.
  - **Sprout/Wrap under deadline** (ch-6): adding tested new code to an untested host without first testing the host is legitimate triage — the new code has tests; the integration doesn't. Note it as debt, don't block it.
- **Temporary ugliness is sanctioned**: dependency-breaking may make code *worse* locally (odd parameters, exposed members, `supersede` setters, near-empty interfaces). Don't demand design purity in the "incision" commit; demand the follow-up once tests exist.
- **Test code standards differ from production**: public fields on fakes, empty method bodies, testing subclasses are fine; test code must still be clean and duplication-free (extract common setup to `setUp`). Don't apply production lint dogma to fakes. (ch-9)
- **Characterization tests lock in bugs by design**: expecting the actual (possibly wrong) value is correct procedure for deployed systems; the exemption is *deliberate* and paired with escalation. Never "fix" a characterization expectation to the intended value without the ch-13 bug protocol.
- **Language scope**: preprocessing seams and Definition Completion are C/C++ only; Extract and Override Factory Method fails in C++ constructors; Pass Null is unsafe in C/C++; Text Redefinition needs open classes (Ruby etc.); link seams need control over the build. Check the language column before recommending a technique.
- **Scale of claims**: the book targets 2004-era OO/procedural codebases; timings ("1/10th second is slow") are directional, but the *ratio* argument (suite time ∝ how often tests run ∝ error-localization ability) still holds.
- **Not for greenfield**: in fresh code with tests, use ordinary TDD and Fowler-style refactoring; the catalog's compromises (interface-per-need, exposed members) are unjustified when normal test-supported refactoring is available.

## Candidate lexicon rows

| any edit planned to code that has no tests around the change area | **Legacy change algorithm** — identify change points → find test points → break dependencies → write tests → change; untested edits are Edit-and-Pray | Is the change area covered by tests, and if not, which step of the algorithm are we on? | should | plan | src: working-effectively-with-legacy-code ch-2 |
| diff modifies behavior of an untested function/class | **Characterization before change** — pin actual current behavior with a failing-assert→record-actual test before altering it; actual behavior, not intended, is the contract | Does a test document what this code does *today* before the diff changes it? | should | write | src: working-effectively-with-legacy-code ch-13 |
| test being added that hits a DB, network, filesystem, or needs env setup | **Not a unit test** — keep it out of the fast suite; unit tests run fast (≪0.1s) and localize failures | Will this test keep the fast suite fast, or does it belong in a separate slow suite? | should | review | src: working-effectively-with-legacy-code ch-2 |
| plan needs to fake a collaborator but no substitution point exists (object `new`ed at use site, hard-coded static/global call) | **Find the seam** — behavior must be replaceable without editing the call site; create an enabling point (parameter, factory method, getter) and prefer object seams over link/preprocessing seams | Where is the enabling point that lets test and production choose different behavior here? | should | plan | src: working-effectively-with-legacy-code ch-4 |
| constructor constructs its own problematic collaborator | **Parameterize Constructor** — pass the collaborator in and keep a delegating original-signature constructor so no caller changes | Can the dependency be injected while existing callers stay untouched? | should | write | src: working-effectively-with-legacy-code ch-9 |
| new feature being inlined into a large untested method | **Sprout, don't inline** — write the new code as a TDD'd method/class and call it from the untested host | Can this change be formulated as new, separately tested code instead of edits inside the monster? | should | write | src: working-effectively-with-legacy-code ch-6 |
| test targets a private method (visibility hack, reflection, or made-public-just-for-test) | **Private-method test urge = SRP signal** — test via the public interface, or move the method to a new class where it is legitimately public | Is this a testing problem or a class-doing-too-much problem? | judgment | review | src: working-effectively-with-legacy-code ch-10 |
| change touches several untested collaborating classes at once | **Test at the pinch point** — find the narrowing in the effect sketch where one or two methods sense all the changes; characterize there first, then narrow; delete the covering tests later | Is there one interception point that covers all change points before we break each class individually? | judgment | plan | src: working-effectively-with-legacy-code ch-12 |
| dependency-breaking edit performed before tests exist (any ch-25 technique) | **Preserve Signatures / Lean on the Compiler** — copy signatures verbatim, no bundled cleanup, and don't trust compiler silence where inheritance or shadowing can swallow the change | Is this move purely mechanical, and would the compiler actually catch a mistake here? | blocker | write | src: working-effectively-with-legacy-code ch-23 |
| refactoring moves or extracts a branch or type conversion in weakly-typed math/IO code | **Exercise the conversion** — a test must provably execute the branch and expose a wrong-type extraction (sensing variable if needed); sunny-day tests pass through silent truncation | Would this test fail if the extraction declared the wrong type or skipped the branch? | should | review | src: working-effectively-with-legacy-code ch-13 |
| diff adds direct calls to a third-party library across multiple files | **Wrap the library** — route vendor/API calls through a thin owned wrapper; every hard-coded library call is a forfeited seam | Do we own an interface between our logic and this library? | judgment | review | src: working-effectively-with-legacy-code ch-14 |
| reviewer flags "ugly" test-enabling code (exposed member, odd parameter, supersede setter) in a dependency-breaking commit | **Incision-point exemption** — conservative ugliness that gets code under test is sanctioned; demand the cleanup after tests exist, not before | Is this ugliness the incision that enables tests, with a follow-up path once covered? | judgment | review | src: working-effectively-with-legacy-code ch-25 |
