# Why Programs Fail — distilled

> **Source**: Andreas Zeller, *Why Programs Fail: A Guide to Systematic Debugging*, 2nd ed. 2009 (Morgan Kaufmann) · extracted from `../why-programs-fail.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory that treats debugging as a *formal, automatable science*: the defect→infection→failure causality chain, the TRAFFIC process, scientific debugging as an explicit hypothesis→prediction→experiment→conclusion loop, delta debugging (ddmin/dd) as executable algorithms for minimizing failure-inducing input and bisecting version history, program slicing for tracking infections, and counterfactual causality ("a cause is proven only by an experiment in which removing it removes the failure"). Where Agans (`debugging-9-rules`) gives field intuition, Zeller gives the procedures an agent can literally execute — and the discipline of *verifying* every diagnosis instead of asserting it.

## Chapter map

- ch-1 — How failures come to be: defect/infection/failure vocabulary, the infection chain, the TRAFFIC 7-step process
- ch-2 — Tracking problems: what a reproducible bug report must contain; severity vs priority; tests supersede tickets
- ch-3 — Making programs fail: automated testing at presentation/functionality/unit layers; design for debuggability
- ch-4 — Reproducing problems: "first, reproduce" discipline; controlling every input source; Heisenbugs
- ch-5 — Simplifying problems: the ddmin delta-debugging algorithm; 1-minimal test cases
- ch-6 — Scientific debugging: the hypothesis→prediction→experiment→conclusion loop; the debugging logbook
- ch-7 — Deducing errors: control/data dependences, static slicing, statically detectable defect patterns
- ch-8 — Observing facts: logging, debuggers, watchpoints — observation without interference
- ch-9 — Tracking origins: omniscient debugging, dynamic slicing, the infection-tracking procedure
- ch-10 — Asserting expectations: invariants, pre/postconditions, memory checkers, assertions in production
- ch-11 — Detecting anomalies: coverage diffing, statistical debugging, inferred invariants — abnormal ≠ wrong but correlates
- ch-12 — Causes and effects: counterfactual causality, actual cause = closest possible world, verifying causes
- ch-13 — Isolating failure causes: the dd algorithm; isolating failure-inducing input, schedules, and code changes (bisection)
- ch-14 — Isolating cause–effect chains: delta debugging on program states; cause transitions as defect predictors
- ch-15 — Fixing the defect: focus heuristics, validating the fix, symptom-fixes and debugging-into-existence
- ch-16 — Learning from mistakes: mining defect history, Pareto distribution, defect prediction, fixing the process

## ch-1 — How failures come to be {#ch-1}

Precision vocabulary (retrieval keys — the whole book hangs on these):

| Term | Meaning |
|---|---|
| **Defect** | incorrect program *code* ("bug in the code"; IEEE: *fault*) |
| **Infection** | incorrect program *state* caused by executing the defect |
| **Failure** | externally observable incorrect *behavior* |
| **Infection chain** | the cause–effect chain defect → infection → … → failure |
| **Flaw** | a defect not attributable to a location — design/architecture level; implies major rework |
| **Problem** | neutral term for questionable behavior; becomes a *failure* once judged incorrect |

Causality chain rules:

- A failure comes about in four stages: (1) the programmer creates a **defect**; (2) executing the defect creates an **infection** — state that differs from what was intended; (3) the infection **propagates** through later state; (4) the infection becomes an observable **failure**.
- A defect causes an infection **only if executed under infection-triggering conditions**; an infection **need not propagate** (it can be masked, overwritten, or corrected by later code) — so *absence of failure proves nothing* (Dijkstra: testing shows the presence of defects, never their absence). An agent that says "tests pass, so the defect is gone" without having reproduced the failure first is making this exact error.
- Every failure, though, traces back through infections to a defect. Debugging = identifying the infection chain backward from the failure, finding its root (the defect), removing it.
- Debugging is a **search in space and time**: which part of the state is infected (space — states have thousands to millions of variables; a GCC state has ~44,000 variables), and when the sane→infected transition happened (time — millions of states). Two pruning principles: **separate sane from infected** and **separate relevant from irrelevant** (a value depends on few earlier values — follow dependences, ch-7/ch-9).

Canonical micro-example (`sample`, reused through the whole book): a shell-sort driver called as `shell_sort(a, argc)` instead of `shell_sort(a, argc - 1)`.

```
$ sample 11 14        → Output: 0 11       (failure: 14 lost, bogus 0)
defect:    shell_sort(a, argc)             — size one too large
infection: size = 3, a[] = [11, 14, ?]     — uninitialized a[2] read
propagation: a[2]==0 swapped into a[0]
failure:   prints "0 11"
```

With arguments `9 7 8` the *same defect* produced *no failure* — the out-of-bounds value happened not to get swapped in. The infection died before becoming observable; only the run with `11 14` exposed it.

**TRAFFIC** — the seven debugging steps, in order:

1. **T**rack the problem in the database (ch-2)
2. **R**eproduce the failure (ch-4)
3. **A**utomate and simplify the test case (ch-3, ch-5)
4. **F**ind possible infection origins (ch-7, ch-9)
5. **F**ocus on the most likely origins — known infections, causes, anomalies, code smells (ch-10–14)
6. **I**solate the infection chain via scientific method (ch-6)
7. **C**orrect the defect and verify the fix (ch-15)

The find–focus–isolate loop consumes by far the most time; correction is usually trivial once the chain is understood (unless the defect is a flaw). ↔ `debugging-9-rules` covers the same territory as heuristics; TRAFFIC is the procedural version.

## ch-2 — Tracking problems {#ch-2}

A problem report must let a stranger reproduce the failure. The single principle: **state all facts relevant for reproducing the problem** — from the developer's perspective, not the user's. Real reports err on both sides (gigabyte core dumps vs "your program crashed, just wanted to let you know"). Ranked by what developers actually need (Bettenburg et al. survey of Apache/Eclipse/Mozilla developers):

1. **Steps to reproduce** (most important — an unreproducible problem is unlikely to be fixed), including accessed resources/config files, simplified as far as possible
2. **Diagnostic output** — stack traces, logs
3. **Experienced behavior** (facts, neutral tone) and **expected behavior**
4. One-line summary; product release/version; operating environment; system resources (least important — "most bugs occur on all platforms")

Rules:

- **Severity** (impact) and **priority** (what gets fixed first) are independent axes — a blocker in an alpha may rank below a major in a shipped product; priority also weighs likelihood, users affected, and potential damage. Don't infer one from the other. Severity ladder:

| Severity | Meaning |
|---|---|
| Blocker | blocks development/testing itself (showstopper) |
| Critical | crash, data loss, severe leak |
| Major | major loss of function |
| Normal | the standard problem |
| Minor | minor loss / easy workaround exists |
| Trivial | cosmetic |
| Enhancement | not a failure — a desired feature (but an unmet *requirement* is major, not enhancement) |
- Problem lifecycle: UNCONFIRMED → NEW → ASSIGNED → RESOLVED (FIXED / INVALID / DUPLICATE / WONTFIX / WORKSFORME) → VERIFIED → CLOSED, with REOPENED on recurrence. Adapt states to the process, but keep the audit trail.
- Cross-link both ways: the ticket names the fixing change; the commit message names the ticket ("Fix: null pointer crash (PR 2074)"). Tag every release in version control; keep fixes on maintenance branches, features on trunk — this is what makes ch-13/ch-16 mining and bisection possible at all.
- **Tests make problem reports obsolete**: for problems found in-house, do not file a ticket — write an automated test that exposes the problem. The test proves presence, re-checks at a button press, and becomes the regression guard. Tickets are for what cannot immediately become code or a test.
- Duplicates are identified via simplification (ch-5): the fewer facts in a report, the easier similarity is to spot.

## ch-3 — Making programs fail {#ch-3}

**Testing for debugging** (making a *known* problem occur) differs from testing for validation (finding unknown ones). Debugging reruns the same test dozens of times — reproduce, simplify, observe, verify fix, guard regressions — so automate it.

Three layers to automate at, trading robustness against realism:

| Layer | Control via | Assessment | Longevity |
|---|---|---|---|
| **Presentation** (GUI/CLI events) | synthesized clicks/keys; coordinates or named controls | hard (parse screen) | fragile — breaks with any UI change |
| **Functionality** (scripting API) | designed automation interface | easy (structured results) | robust |
| **Unit** (API of one component) | direct calls in a test framework | easy (asserts) | robust; needs the unit to fail in isolation |

- Rule of thumb: **the friendlier an interface is to humans, the less friendly it is to computers.** Test at the presentation layer only if the problem lives there or nothing else is accessible.
- Automation matters doubly for debugging because the same test reruns at every step: reproduce (ch-4), simplify — dozens to thousands of reruns (ch-5), observe (ch-8), verify the fix (ch-15), guard against regression forever after. Automated tests are also the enabling precondition for every delta-debugging technique in ch-13/14 — "once one has automated testing, automated isolation of failure causes is a minor step."
- Rolling your own embedded scripting language for testability is not worth it — embed an existing interpreter or expose a component interface instead (you will eventually need variables, control flow, modules).
- If functionality can't be exercised without the UI (circular dependence like `print_to_file()` calling a confirmation dialog), break the cycle with the **dependence inversion principle**: make the code depend on an abstract interface (`Presentation`), substitute an `AutomatedPresentation` in tests. Same move as seams. Architectures like **model-view-controller** do this wholesale: testing = new controller, tracing = new logging view.
- **High cohesion / low coupling** is a *debugging* feature: fewer dependences = smaller search space, easier unit isolation, easier state judgment.
- Essential testing rules (List 3.1):
  - **Specify** — a program cannot be correct "on its own", only w.r.t. a specification;
  - **test early** — per unit, not after full assembly;
  - **test first** — test cases double as example specifications;
  - **test often** — every change; the smaller the change set since the last green run, the smaller the suspect set (this is what makes ch-13 bisection cheap);
  - **test enough** — measure coverage; random inputs for the extreme cases;
  - **have others test** — authors are psychologically unsuited to breaking their own code.

## ch-4 — Reproducing problems {#ch-4}

The **first task in any debugging activity is to reproduce the problem** — for two non-negotiable reasons: (1) you cannot *observe* what you cannot re-run; (2) you cannot *know a fix works* without re-running the original scenario. An agent that proposes a fix for an unreproduced failure has skipped both. ↔ `debugging-9-rules` "Make it Fail" — Zeller adds the mechanics.

- Don't cry success because you experience *a* problem — only if you experience *the* problem, with every symptom exactly as reported (same message, same backtrace). Deviations mean you may be chasing a different bug (see *artifacts*, ch-13).
- **Reproduce the environment iteratively**: start with your own environment; adopt circumstances from the problem environment one at a time (config files, versions, hardware), starting with those *most likely* to matter and *cheapest to apply*. Side effect: the circumstance whose adoption makes the failure appear is itself a failure cause. If you reach an identical environment and still no failure, the report is incomplete — query more facts (the "mad laptop" ran slower on battery; the failure needed that timing).
- **Reproduce the execution** by placing a *control layer* between each input source and the program, so runs become deterministic. Input sources to control, roughly in order of increasing pain:

| Input source | Control technique |
|---|---|
| Data (files, DB) | copy it — get *all* of it, *only* what's needed, mind privacy |
| User interaction | capture/replay; prefer named-control level over pixel coordinates (coordinate scripts are write-only and break on any layout change) |
| Communications | record/replay traffic; capture only since the last reproducible state (e.g. last transaction) |
| **Time** | make the clock an injectable, configurable input — never a hidden global (the "works only on Wednesday" bug) |
| **Randomness** | capture the PRNG seed; make random sources replaceable by deterministic ones (but never let end users disable crypto randomness) |
| Operating environment | intercept system calls (`strace`-style wrappers); or record/replay a whole VM; checkpoints trade state-size for replay length |
| **Thread/process schedules** | record-replay of thread switches; the worst nondeterminism to debug — see ch-13 (htpasswd lost-update race as the canonical example) |
- **Heisenbug**: a failure that disappears or mutates when probed. Prime suspect: **undefined behavior** (uninitialized memory, C/C++ semantics) interacting with the observation environment — a debugger doesn't zero leftover memory, a print statement relinks the binary. When a failure vanishes under observation, check data flow for uninitialized reads (ch-7) and run memory checkers (ch-10); confirm observations by *two independent means*. Related jargon: **Bohr bug** (reliably repeatable), **Mandelbug** (causes so complex it appears nondeterministic), **Schroedinbug** (stops working for everyone once someone notices it never should have worked).
- Blame physics (cosmic rays, bit flips) only when every other alternative is *proven* irrelevant and the physical influence is provable. It almost never is.
- **Focus on units**: rather than reproducing the whole program, record/replay at a unit boundary (databases: replay the SQL; compilers: capture intermediate structures). **Mock objects** replay recorded interaction in place of the real component — a recorded log that compiles into a standalone test is a regression test for free.
- **Reproducing crashes** automatically (**test case extraction** — turn a crashing run into a test that re-runs the failing calls on captured state). Three strategies with their trade-offs:

| Strategy | Overhead | Fidelity |
|---|---|---|
| Shadow copy of call stack + arguments ("used fields" mode: deep-copy only fields the method touches) | 13–50% | reproduced all crashes in the study |
| Re-invoke the failing method on the *failing* (post-crash) state | ~0% until crash | ~90% reproduced; brittle if constructors/invariants reject the corrupt state |
| **Second-chance mode** — no monitoring until the first crash, then instrument only the involved locations | ~1% | reproduces the *second* occurrence |

  Synthesis: try failing-state replay first; if it fails, deploy lightweight monitoring and wait for recurrence. All strategies work better the earlier the infection is detected — reproducing the crash is useless if the infection's origin predates the recorded state (a null record fetched long before the crash reproduces the *crash* but not the *chain*); this is why design-by-contract precondition checks (ch-10) multiply their value.

## ch-5 — Simplifying problems {#ch-5}

Once reproduced, **simplify**: remove every circumstance that is not required for the failure. A circumstance is *irrelevant* iff the problem occurs whether or not it is present — established only by experiment (omit it, retest). Goal (McConnell): a test case so simple that *changing any aspect of it changes the behavior*.

Why simplify — three concrete payoffs:

- **Communication**: "printing `<SELECT>` crashes Mozilla" replaces 896 lines of obfuscated HTML; every remaining detail is known-relevant.
- **Debugging**: less input ⇒ smaller states and shorter runs to examine; in the best case the minimal input names the responsible code directly (the code that prints `<SELECT>` tags).
- **Duplicate identification**: reports that reduce to the same minimal case are the same bug (the tension: good reports contain *many* facts, duplicate detection wants *few* — simplification resolves it).

Manual protocol (the Gecko BugAThon instructions, done by non-programmer volunteers): cut away half the input; if the failure persists, keep cutting; if it vanishes, restore and cut the other half; done when removing anything more makes the failure disappear. Simplification requires no program understanding — only a repeatable test.

**ddmin** (minimizing delta debugging) — automated simplification. Requires an automated `test(c) → {FAIL ✘, PASS ✔, UNRESOLVED ?}`:

```
n = 2
while |c✘| ≥ 2:
    split c✘ into n subsets
    if removing some subset still FAILs:
        c✘ = that complement; n = max(n−1, 2)     # "some removal fails"
    elif n < |c✘|:
        n = min(2n, |c✘|)                          # increase granularity
    else: done
```

Result is **1-minimal**: removing any single remaining element makes the failure disappear. (Not globally minimal — that would take 2^n tests.) Worst case O(n²) tests; with resolved outcomes and a single failure-inducing element it degenerates to binary search, O(log n).

Speedups: **cache** test outcomes; **stop early** (granularity threshold / no-progress window / time budget); **simplify syntactically** — split by lines, then by syntax-tree nodes rather than characters, returning `?` for structurally invalid configurations (2 tests instead of 48 on the Mozilla `<SELECT>` example); or *isolate differences* instead of minimizing (ch-13). Applied to fuzz-crash inputs, ddmin reduced megabyte inputs to single failure-inducing characters. ↔ `debugging-9-rules` "Divide and Conquer" — ddmin is that rule as an algorithm, safe to run unattended.

## ch-6 — Scientific debugging {#ch-6}

Debugging without a method is guessing. The **scientific method of debugging**:

1. Observe the failure.
2. Invent a **hypothesis** consistent with all observations.
3. Derive a **prediction** from it.
4. **Experiment**: if the prediction holds, refine the hypothesis; if not, reject it and form an alternative.
5. Repeat until the hypothesis explains all observations and predicts the fix — it is now a **diagnosis** (theory).

The book's worked run of the loop on `sample` (four iterations to diagnosis):

| # | Hypothesis | Prediction | Experiment | Outcome |
|---|---|---|---|---|
| 1 | execution makes `a[0]` zero | `a[0] == 0` at line 37 | observe in debugger | confirmed |
| 2 | infection starts inside `shell_sort()` | args sane at entry: `a[]==[11,14]`, `size==2` | observe at entry | **rejected** — `size==3`, `a[]==[11,14,0]` |
| 3 | `size == 3` at the call causes the failure | setting `size=2` in the debugger makes the run pass | `set var size=2`, continue | confirmed |
| 4 | passing `argc` instead of `argc-1` causes the failure | changing the call fixes the output | edit, recompile, rerun | confirmed — diagnosis + fix |

Note the structure: each hypothesis is tied to a prediction an experiment can refute; hypothesis 2's *rejection* is what redirected the search from inside `shell_sort()` to its caller.

Observable agent violations → correction:

- Changing code before stating a hypothesis → write the hypothesis + prediction first; every experiment must be able to *falsify* it (Popper).
- Verifying "obvious" facts is skipped → don't trust the obvious: the program "obviously" should work and doesn't. Hypothesis 1 in the worked example is literally "the printed zero comes from `a[0]` being zero" — verified in a debugger before anything else.
- Each new hypothesis must **include all confirmed** and **exclude all rejected** earlier hypotheses, and explain every earlier observation.
- **Explicit debugging**: state the problem out loud / in writing (the teddy-bear/rubber-duck protocol) — stating it forces re-examining assumptions.
- **Keep a logbook**: for each step record *hypothesis / prediction / experiment / observation / conclusion*. Without it you are playing Mastermind blindfolded from memory; with it you can stop and resume anytime. ↔ `debugging-9-rules` "Keep an Audit Trail". For an agent: the logbook is the visible reasoning trace — hypotheses and test outcomes belong in it verbatim, not paraphrased from memory.
- **Quick-and-dirty budget**: simple problems deserve a light process — but set a time limit (~10 minutes). If exceeded, switch to the explicit method and start the logbook.
- **Algorithmic debugging** semi-automates the loop: repeatedly ask an oracle "is this intermediate result correct?", descending the execution tree until an incorrect result whose sub-computations are all correct is found — that computation is the defect (worked example: `sort([2,1,3])` wrong → `sort([1,3])` wrong → `sort([3])` correct ⇒ the defect is in the intervening `insert(1,[3])`). Scales poorly for imperative programs (huge shared state to judge per question; programmers dislike being driven), but is the template for any bisect-by-correctness dialogue with a human — including an agent asking its user targeted "is this intermediate value right?" questions instead of open-ended ones.
- Reasoning hierarchy (each uses the previous): **deduction** (0 runs — from code alone, ch-7) < **observation** (1 run, ch-8–10) < **induction** (n runs — abstractions over many runs, ch-11) < **experimentation** (n *controlled* runs — scientific method, delta debugging, ch-12–14). ↔ `modern-software-engineering`: same empiricism, applied to debugging rather than product decisions.

## ch-7 — Deducing errors {#ch-7}

Deduction = reasoning from code to what *any* run can do, without executing ("static analysis predicts approximations of the program's future; dynamic analysis remembers approximations of its past").

- **Control flow graph**; a statement *writes* state and/or *controls* successors; it *reads* state and is *executed* under control of others. **Data dependence**: B reads what A wrote with no intervening overwrite. **Control dependence**: A's outcome decides whether B executes. Together: the **program dependence graph**. Control-flow caveats that break easy reasoning: gotos/indirect jumps, dynamic dispatch (every call site has a *set* of possible targets), and exceptions (control may never reach the "official" end of a function).
- **Backward slice** S_B(s): all statements that could influence s — "where does this value come from?" **Forward slice**: everything s could influence — "what breaks if I change this?" Combinations: **chop** (forward ∩ backward: paths from A to B), **backbone** (slice ∩ slice: common origin of two infected values), **dice** (slice \ slice: statements contributing *only* to the infected value, given other values known correct — prime suspects when a program is "largely correct").
- Slicing found the book's Fibonacci defect by pure deduction: the returned `f` has *two* possible origins — the loop computation and the uninitialized declaration `int f;` — and the second one is reachable when the loop body doesn't execute (`fib(1)`). Uninitialized-read plus dependence analysis = defect located without a single run.
- Statically detectable **code smells** (Zeller's sense: *defect patterns flagged by analysis tools*, not Fowler's design smells — ↔ `refactoring-fowler-beck` uses the same word for a different catalog): reading uninitialized variables, values written but never read, unreachable code, memory leaks (path from allocation to reference-death without deallocation), interface misuse (open without close on some path), possible null dereference.
- **Before debugging, get rid of code smells reported by automated tools** (compiler with all warnings on, FindBugs-class linters): cheap elimination of a whole failure class. Expect ~50% false positives — rewrite even the non-errors so they stop appearing in the next report.
- Limits of static analysis, and the three risks of deduction-only debugging:
  - **Undecidability**: precise dependences reduce to the halting problem (does `a[i]` ever alias `a[j]`?); tools must use **conservative approximation** — indirect accesses, pointers, and function summaries inflate slices (static backward slice ≈ 30% of the program on average; a fully paranoid approximation degenerates to "anything can happen").
  - **Risk of code mismatch**: source ≠ executed binary — verify build/version identity before deducing anything (the "stubborn hello" bug was a PATH shadow: the edited program was never the one running). Preprocessors, macros, undefined behavior, and woven aspects all widen this gap.
  - **Risk of abstracting away**: deduction assumes the compiler/library/environment behave as specified; rarely, the defect lives there.
  - **Risk of imprecision**: approximate slices are big; combine with observation of the concrete failing run (ch-8+) and runtime-verified constraints (ch-10) to sharpen them.

## ch-8 — Observing facts {#ch-8}

Principles of observation: **(1) do not interfere** (side-effect-free observation, else Heisenbugs), **(2) know what and when to observe** (a run is too big to watch whole), **(3) proceed systematically** — every observation should serve the current hypothesis. A debugger's interactivity has a "toylike quality"; a debugger is only as good as the thinking that drives it.

- **printf debugging** works everywhere but has four systematic drawbacks: cluttered code (debug-only statements that get deleted after the session, losing the investment), cluttered output (interleaved with real output — use a dedicated channel), slowdown (Heisenbug risk), and *buffered output lost on crash* (log unbuffered or flush on abort). The upgrade ladder:
  1. **Logging functions/macros** — standard format with file:line, off-switch with zero argument-evaluation cost, per-module granularity, kept permanently in code;
  2. **Logging frameworks** (log4j-class) — per-class loggers, levels DEBUG…FATAL, runtime configuration of appenders/layouts/filtering; replaces every ad-hoc println;
  3. **Aspects** — logging woven in at described point cuts (all setters, one class, everything), zero source clutter, removable by not weaving;
  4. **Binary instrumentation** (PIN-class) — inject observation code into the running binary, no source or recompile needed.
- Debugger basics that replace recompile-and-print cycles — the three capabilities that define a debugger:
  1. execute the program and **stop it on specified conditions** (breakpoints, conditional breakpoints, watchpoints);
  2. **observe** the stopped state (print values, walk stack frames, invoke inspection functions — side-effect-free ones only);
  3. **change** the state (`set var`) and resume — the cheapest way to run a causality experiment ("if `size` were 2, would it pass?") without recompiling.
  Also: scripted breakpoint commands turn a debugger into a non-invasive logger; "fix and continue" is for trivial edits only (larger ones desynchronize source and binary). **Postmortem debugging**: a core dump's backtrace is the first observation of any crash. Seasoned programmers run tests under a debugger by default.
- **Watchpoints** ("stop when this variable changes") answer "who wrote this?" when dependences are unknown — but software watchpoints cost ~1000× slowdown; prefer conditional breakpoints at accessor functions, or hardware watchpoints. Uniform event queries (COCA-style "when did a[2] become 0?") generalize this.
- In interpreted languages, hook the interpreter (Python `sys.settrace`, JVM agents) — the cheapest way to prototype any observation or analysis tool.
- Visualize linked structures as graphs (DDD memory graphs) when relationships (aliasing, cycles) matter more than scalar values — a name/value list can't show two pointers aliasing one object.

## ch-9 — Tracking origins {#ch-9}

Programs execute forward; programmers reason **backward** from the failure. Tools that close the gap:

- **Omniscient debugging** (ODB): record every state change of the whole run; then navigate backward/forward freely — step *back* from the failing output to the assignment that infected the value, no restarts, no carefully re-approached breakpoints (the classic forward-debugger failure mode: step one too far, restart everything). Session shape: start at the failing output, walk backward, judge each state, follow the infection to the defect. Cost: ~10× slowdown, ~100 MB/s of trace; mitigate by recording a time window, a subsystem, or compressed events.
- **Dynamic slicing**: compute the backward slice *for this one run* from an execution trace, tracking per-statement reads/writes plus control predicates. Dynamic slices cover ~5% of executed statements vs ~30% for static slices — pointers and untaken paths resolve exactly. Trade-off: needs a trace; valid only for that run.
- **WHYLINE**: "why did / why didn't X happen?" queries answered by dynamic (why-did) and static (why-didn't) slices, presented as a dependence chain; halved-to-eighthed debugging time in studies. The "why didn't" direction — following control dependences to the condition that prevented execution — is a genuinely distinct move agents rarely make unprompted.
- **The infection-tracking procedure** (the core manual loop, ch-1's search made concrete):
  1. Start from the infected value reported by the failure (`a[0]` in sample).
  2. Follow dependences (static or dynamic) back to its possible origins (`a[]`'s other elements and `size`).
  3. Observe each origin; judge sane vs infected (`size` is infected).
  4. If an origin is infected, recurse on it (`size` depends only on `argc`; `argc` is sane).
  5. When an infected value has **only sane origins**, you have found the **infection site — the defect** (the `shell_sort(a, argc)` call). Fix it; verify the failure disappears.
  This procedure is guaranteed to terminate at the defect using only observation + judgment; it works even when dependences are imprecise (just more to observe). Assertions (ch-10) automate the judging; anomalies/causes (ch-11–14) prioritize which origin to check first; function/package boundaries are the efficient places to probe (narrow interfaces = easy sanity judgment).

## ch-10 — Asserting expectations {#ch-10}

Observation doesn't scale — *judging* thousands of values does not. **Assertions delegate the judgment to the machine**: each is an infection detector that catches the infection near its origin instead of at the failure. Where manual observation probes points of the state, assertions cover *areas* of space and time. Best long-term debugging investment in a codebase.

- Two systematic uses: **data invariants** — a `sane()` helper checked at entry and exit of every public mutator (aspects can weave this in without clutter; a debugger conditional breakpoint `break f if !sane()` works even with assertions compiled out); and **pre/postconditions** — the localization logic:
  - precondition violated ⇒ infection happened *before* the function (caller's fault);
  - postcondition violated ⇒ infection arose *inside* the function;
  - both pass ⇒ rule the function out entirely.
  This turns the ch-9 infection-tracking loop into binary search over the run.
- Complex-structure invariants decompose into named checks (`rootIsBlack()`, `treeIsAcyclic()`, `parentsAreConsistent()` for a red-black tree) — each a reusable oracle for both assertions and interactive probing. Postcondition helpers (`is_sorted()`, `has(x)`) usually deserve to be public methods.
- **Design by contract** (Eiffel `require`/`ensure`/`invariant`, JML for Java with `\old`, quantifiers, exceptional postconditions): assertions become checkable *specifications* living in the interface — documentation, runtime checking, test oracles, static-checking input, and blame assignment (caller broke the precondition vs callee broke the postcondition) in one artifact.
- **Reference runs / relative debugging**: when correctness is defined as "behaves like version/platform P₀", assert equality of chosen variables *between two runs* at given locations (`p1::x@file:line == p0::x@file:line`) and let the tool flag the first divergence. The four situations where a reference program is the oracle: the program was **modified** (patch must preserve everything but the fix), the **environment changed** (Y2K-style), the program was **ported** (new architecture/library), or **cloned/reimplemented** (behavior defined by the original implementation). If data layouts differ, compare through a user-supplied abstraction (e.g. both as sets).
- **System assertions** for memory sanity (C/C++): `MALLOC_CHECK_` (double-free), ElectricFence (fence pages catch overruns), **Valgrind** (shadow memory: per-bit initialized V-bits, per-byte allocated A-bits — catches uninitialized reads, out-of-bounds, leaks; ~25× slower), Purify (instrumentation, ~5–10×). **Run a memory checker before all other debugging of a C/C++ failure** — reasoning about variable values is pointless while the heap is broken; and it kills most Heisenbugs (ch-4) at the source. Safer dialects (Cyclone: non-null and fat pointers) prevent the class outright; managed languages don't have the problem.
- **Production policy** — the arguments, since agents routinely propose stripping assertions "for performance":
  - more active assertions ⇒ more infections caught that would otherwise pass silently;
  - the sooner a program fails, the shorter the defect→failure distance ("fail fast") and the cheaper the diagnosis;
  - defects that escape to the field are the hardest to reproduce — a failing assertion in a field report is often the only usable clue;
  - performance cost must be *measured* before it justifies disabling anything; turn off only the assertions proven expensive (hot-loop invariants), keep cheap result-integrity checks on.
  But **never use assertions for external conditions** (user input, file contents — validation must not be compilable away and deserves real error messages: "a PIN has four digits", not `assertion 'length == 4' failed`) **or for critical results** (use hard-coded checking / independent recomputation). Wrap failing assertions in a graceful global handler; an aborted behavior beats an unnoticed wrong one. ↔ `release-it` "crash early / fail fast" — same principle from the operations side.
- Specification ≠ desirability: the Warsaw A320 braking logic *met its specification*; the spec was wrong. Review assertions as critically as code — do not adapt code to a faulty spec.

## ch-11 — Detecting anomalies {#ch-11}

When no specification says what is *correct*, compare against what is *normal*: summarize properties of passing runs (induction), and flag where the failing run deviates. **An anomaly is neither a defect nor a cause — but abnormal properties are far more likely to indicate defects than normal ones**, so anomalies order the search.

Why assertions alone don't cover this: writing them takes time, temporal/control-flow properties are hard to state, and asserting *everything* would be a spec as complex (and defect-prone) as the program. Anomaly detection fills the gaps by learning "normal" from passing runs. The techniques:

| Technique | Compares | Signal | Cost |
|---|---|---|---|
| Coverage diff (Tarantula) | statements executed in failing vs passing runs | code executed (mostly) only in failing runs | two coverage runs — cheapest |
| Nearest neighbor | failing run vs the *most similar* passing run | the few remaining coverage differences | cheap; better precision |
| Call sequences | failure-correlated method-call *sequences* per object | protocol violations coverage can't see | cheap |
| Statistical debugging | sampled predicates over thousands of runs | predicates true only in failing runs | ~4% overhead, needs many runs |
| Dynamic invariants (Daikon) | invariants inferred from passing runs vs failing run | violated inferred invariant | heavy (cubic in variables in scope) |
| On-the-fly ranges (DIDUCE) | value/difference ranges learned during the run | value outside every previously seen range | 6–20× slowdown, switchable mid-run |

- **Coverage comparison** (Tarantula): rank statements by how exclusively failing runs execute them ("red" = executed mostly/only by failing tests). Micro-example from the book's `middle` program: the defective assignment was the one line executed by only one passing test but by the failing test — the coverage table alone singled it out. In the study, the defect landed in the most-suspicious 20% of code for 18/20 defects; for some defects the suspicious set was 3% of the code. Caveat: code executed in *neither* kind of run is not an anomaly. Refinements: **nearest neighbor** (diff against the single passing run with the most similar coverage, not against all — best coverage-based predictor), and **call-sequence** anomalies (failure-correlated *sequences* of method calls, e.g. `read()` then `finalize()` without `close()` — catches protocol bugs coverage misses; beat plain coverage in the NanoXML study).
- **Statistical debugging** (Liblit): instrument cheap predicates (sign of each return value, branch outcomes), sample them sparsely (1/1000 → <4% overhead, deployable to users), collect over thousands of runs, and keep the predicates true *only* in failing runs. In ccrypt, 2 of 1,710 counters survived — `file_exists() > 0 ∧ xreadline() == 0` — pinpointing the unhandled-EOF defect. More runs ⇒ sharper isolation; field data beats lab data in volume and variety (mind privacy and overhead).
- **Dynamic invariants** (Daikon): from a trace of many passing runs, instantiate an invariant-pattern library (`x ≤ y`, `n == size(b[])`, `return == sum(b[])`, sortedness…) and discard patterns violated by any run; survivors are likely specs — emit as assertions/JML and check the failing run against them. Limits: only finds invariants in its vocabulary; cost cubic in variables in scope; inferred invariants hold for the *observed* runs, not necessarily all. **DIDUCE** does a cheap on-the-fly version (value/difference bit-ranges per program point; switch from learn to check mid-run) — violations found real defects.
- Treat every anomaly with ch-12 discipline: does it indicate an infection (trace back)? could it cause the failure (trace forward)? is it a side effect of the defect (trace to common origin)? Whenever you must choose among origins to inspect, **inspect the abnormal ones first** (feeds the ch-15 focus ranking).

## ch-12 — Causes and effects {#ch-12}

**Counterfactual cause**: an event without which the effect would not have occurred. In the real world this is untestable (can't rerun history); in programs it is *directly testable* — repeat the run with and without the candidate. This makes debugging the one discipline that can genuinely prove causality.

- **To show causality, run the experiment**: alter the world so the candidate cause is absent; the effect must vanish. Reasoning alone — however plausible — does not suffice; "obviously a is zero" was false in the `printf("%d", double)` example. The fallacy to avoid: **post hoc ergo propter hoc** — a warning preceding a failure need not cause it; verify before resolving it.
- There are infinitely many causes (electricity, the existence of the program, removing the whole `printf`). The useful one is the **actual cause**: the *minimal* difference between the failing world and the **closest possible world** in which the failure does not occur (**Ockham's razor** — among competing explanations pick the one whose alternate world is closest). `"%d"` is the defect; "delete the printf" is not.
- **Finding an actual cause** = (1) find *any* alternate world where the failure doesn't occur — a passing input, config, account, version; it need *not* be a corrected program; (2) narrow the initial difference to a minimum via scientific method (or dd, ch-13). Everything the two worlds share is **common context** and is excluded from the search — so choose the alternate world *as close as possible* to shrink the search space (worked example: copying settings one at a time between user accounts isolated a custom keyboard layout as the cause of a presentation tool's crash — each copied setting was one hypothesis disproved or confirmed).
- The choice of alternate world *defines* the search space: diff against an older version and you'll find a causal *change*; diff against another input and you'll find causal *input*; diff against another machine and you'll find causal *configuration*. Pick the axis you can act on.
- Causes are the most valuable debugging artifacts: they are experimentally tied to the failure (unlike anomalies and smells), and every cause **suggests a fix or workaround** (remove the cause). They are not necessarily *defects* — ch-15 owns that distinction.

## ch-13 — Isolating failure causes {#ch-13}

Automating ch-12 needs: an automated test, a decomposable difference between passing and failing configurations, and a strategy. The strategy is **dd**, the general delta debugging algorithm.

- **Isolating vs simplifying**: ddmin (ch-5) shrinks the failing case until *everything* left is relevant; **dd** moves *both* a passing configuration c✔ *up* (adding deltas that keep it passing) and a failing c✘ *down*, until their difference is 1-minimal — that difference is an **actual cause**. Isolation is much cheaper (Mozilla `<SELECT>`: 5 tests vs 48; logarithmic when all tests resolve, quadratic worst case with many UNRESOLVED outcomes) but yields a cause *in a large context*; simplification yields a self-contained minimal case. Prefer isolation for speed; fall back to simplification when the isolated difference is incomprehensible without context.
  - Flight-test allegory: simplification returns the minimal set of circumstances that make the plane fly *and* crash; isolation returns two nearly identical flights — one lands, one crashes — differing in "cabin light on". The isolated difference is provably causal but may still need its context explained (why does the cabin light matter? — the short circuit is elsewhere).
- dd's moves per granularity level, over the delta set Δ = c✘ \ c✔ split into n subsets, ordered to shrink Δ fastest:

  1. removing a subset from c✘ still fails → new smaller c✘ (at n=2: pure binary search)
  2. removing a subset from c✘ *passes* → that configuration becomes the new larger c✔
  3. adding a subset to c✔ fails → new smaller c✘
  4. adding a subset to c✔ passes → new larger c✔
  5. all tests unresolved → double granularity n; done when n > |Δ|

  Each passing test is exploited to grow c✔ — this is what makes isolation beat minimization, where passing tests are wasted. Keep UNRESOLVED outcomes rare (grouping related deltas, validity-aware splitting, caching outcomes) — with fully resolved outcomes dd is logarithmic.
- Applies to any controllable circumstance:
  - **Input**: failure-inducing difference down to one character in 12–50 tests on fuzz crashes.
  - **Thread schedules** (with a record/replay tool): generate a passing schedule by fuzzing the failing one, then dd over the schedule difference — 3.8 billion thread-switch deltas narrowed to *one* switch in 50 tests, whose code location was the race.
  - **Code changes — the regression case** ("yesterday it worked, today it doesn't"): treat the set of textual changes between the old passing and new failing version as the configuration; a patch-and-test harness applies a subset, rebuilds, tests (build failure ⇒ UNRESOLVED). GDB 4.16→4.17: 178,200 diff lines = 8,721 changes → **one** failure-inducing change in 97 tests — a doc-string wording change ("arguments"→"argument list") whose output DDD's parser choked on. Optimizations, in impact order:
    - group changes by commit time — ordered history with intermediate testable states ⇒ **binary search over history** (this is `git bisect`; dd generalizes it to unordered change sets);
    - group changes by scope (same file/class/function) — halved the test count;
    - incremental rebuilds and compile caches — reconstruction dominates wall-clock;
    - on build errors, add the changes referenced by the error's identifiers and retry ("failure resolution").
    A **blame-o-meter** = this harness wired to CI: when a regression test fails, the failure-inducing change is computed in the background and attached to the report.
- **Artifacts**: a shrunken/mixed configuration may fail *differently* than the original. Guard the test function: return ✘ only if the failure matches the original (same backtrace / same message location); different failure ⇒ UNRESOLVED. Otherwise dd will happily isolate the cause of the wrong bug.
- Caveats: the isolated cause is one of possibly several actual causes (first found wins; rerun for alternatives); and **a cause need not be an error** — the GDB change was a legitimate doc-string fix that DDD's fragile parsing couldn't handle. Removing the cause is a *workaround*; locating the defect still requires ch-14/ch-15. If the same error exists in both worlds, it is common context — dd can never surface it.

## ch-14 — Isolating cause–effect chains {#ch-14}

When an input difference gives no clue (compilers, pipelines — the `+ 1.0` that crashes GCC touches dozens of passes), chase the cause *through the run*: a difference in input causes differences in state, which propagate until they become the failure. Delta debugging on **program states**:

- Capture the state at a chosen moment (comparable moments = identical backtraces; for crashes, sample locations off the crash backtrace: program start, middle, just before failure) as a **memory graph** — vertices are values, edges are references; graphs abstract from concrete addresses (two non-NULL pointers of the same type match even if addresses differ) and expose aliasing. Compute a common subgraph of the passing and failing graphs; unmatched vertices/edges are the state differences.
- Apply *subsets* of these differences to the passing run via debugger commands (mixed states), resume, test — dd isolates the failure-inducing variable(s): "the failure occurs iff `a[2]` is 0" (sample, 5 tests); "iff this RTL node contains a PLUS" (GCC, 44 tests over 871 differing vertices).
- Chaining isolations at several moments yields the **cause–effect chain** — the failure explained as propagating differences. GCC crash, fully automatic diagnosis:
  1. at `main()`: the only state difference is the input file name (fail.i vs pass.i);
  2. at `combine_instructions()`: dd over 871 differing graph vertices → one RTL node containing a PLUS operator (the proven effect of the `+ 1.0` in the source);
  3. at `if_then_else_cond()`: dd over 1,224 vertices → one pointer making the RTL tree cyclic (`link→fld[0].rtx→fld[0].rtx == link`) → endless recursion → crash.
- **Cause transitions**: the moment the failure-cause variable changes from A to B is where B *originates* — found by binary search in time (cts algorithm: isolate the cause variable at two moments; if it differs, bisect the interval until the transition sits at a single statement). Cause transitions are candidate fix locations and are frequently the defect itself (GCC: transition #9 sat two lines from the faulty `apply_distributive_law` call — 2 lines out of 338,000; sample: the transition argc→a[2] at line 36 *is* the defect). Empirically they predict defect locations better than any coverage-based anomaly method (Siemens suite: defect within 10% of code in 36% of runs, exact pinpoint in 5%) — but only code *executed in both runs* can host a transition; code run only in the failing run has no passing state to compare against.
- Costs and risks: state capture/manipulation is heavy; mixed states may be infeasible (artifact risk — check backtraces); C/C++ memory ambiguity (unions, dynamic arrays, invalid pointers) makes graphs approximate; the isolated variable is a **cause, not necessarily an infection** (`a[2]` was never "wrong", `size` was — yet `a[2]` is what dd can prove).
- The hard limit of all automation: **determining the defect requires knowing what is correct** — a full spec of every state is the correct program itself, and verifying "this defect caused the failure" requires the fix. Causes can be isolated automatically; the correct/incorrect judgment stays human.

## ch-15 — Fixing the defect {#ch-15}

Finding the defect = walking the infection chain to the place where an infected value has only sane origins (ch-9). This chapter assembles the whole toolkit into the "Focus" step of TRAFFIC. When multiple origins compete, **focus in this order** (most likely to pinpoint the defect first):

1. **Known infections** — failing assertions, observed wrong values (ch-10)
2. **Causes** in state/code/input, experimentally proven (ch-13/14)
3. **Anomalies** — failure-correlated behavior (ch-11)
4. **Code smells** — static defect patterns (ch-7)
5. **Dependences** — the backward slice; anything outside it is legally exculpated (ch-7/9)

Make big jumps between function/package boundaries (narrow interfaces = easy sanity judgment); on finding a sane state, search *forward* for the sane→infected transition.

Validation duties — each shown by observation *plus experiment*:

- **The error must cause the failure.** An infected-looking value that doesn't change the outcome when corrected is a false trail (the `%d`-format story: `a` was fine, printing was broken). For "suspicious" origins, substitute a sane value and check the failure disappears *before* chasing them.
- **The cause must be an error.** Fixes that check for the failing symptom (`if (account == 123) balance += 45.67;`) or tweak until green without understanding (**debugging into existence**, "ignorant surgery" — narrowing a loop bound because it happens to pass) leave the defect in place and usually add one. The Devil's Guide: find the defect by guessing; don't bother understanding; use the most obvious fix.
- **Think before you code**: before editing, you must be able to predict *how the change breaks the infection chain* and *why the failure (and its siblings) will disappear*. If you can explain the fix to a reviewer, you have a theory; the successful fix then retrospectively proves causality. Being wrong about a correction should astonish you — and be rare.
- The **Devil's Guide to Debugging** (McConnell) — the negative checklist, verbatim in spirit: find the defect by guessing (scatter print statements, change code until something works, keep no old versions, don't bother understanding what the program should do); don't waste time understanding the problem ("most problems are trivial anyway"); use the most obvious fix (patch the special case you can see, not the function that computes it). Every item maps to an anti-pattern below.
- When you fix, save the pre-fix state first (version control) — both to enable revert-on-wrong-diagnosis and to keep the audit trail that ch-16 mines.

After the fix, four duties:

1. **The original failure no longer occurs** — this is the last confirmation, not a heroic moment ("if you feel like a hero, you weren't systematic enough"). If the failure persists: either a second defect surfaced (multiple defects can feed one failure) or your diagnosis was wrong — revert to the pre-fix state before continuing so earlier observations stay valid, and re-audit the logbook.
2. **No new problems introduced** — regression suite + peer review, organized via the change-control process. Facts on fixes (empirical, List 15.2): 30–40% of all changes in Eclipse/Mozilla were fixes; fixes are 2–3× smaller than other changes but *more likely to induce failures*; new code is ~2.5× as defect-prone as year-old code. Fixes deserve *more* scrutiny, not less.
3. **The same mistake elsewhere** — sweep for sibling defects from the same misconception (every other `malloc(strlen(t))` missing the NUL byte), and prefer refactors that make the mistake unmakeable (`strdup`).
4. **Homework** — close the ticket with the right resolution, link fix↔report bidirectionally, feed the defect history (ch-16).

Fix one defect at a time; interleaved fixes mask each other and can mimic the original failure. ↔ `debugging-9-rules` "If you didn't fix it, it ain't fixed."

**Workarounds** (fix the symptom deliberately): legitimate when the code can't be changed (third-party), the correction is too risky, or the defect is a flaw requiring redesign. A workaround is not a correction — keep the problem report open (spam filters, virus scanners, and date windowing are civilization-scale workarounds).

## ch-16 — Learning from mistakes {#ch-16}

- **Pareto's law of defects**: ~80% of defects sit in ~20% of modules; in Mozilla, 96% of components never had a vulnerability; Eclipse compiler components had 4–5× the defect density of UI components. Past defect density is a strong prior — when choosing where to look or what to review/test hardest, weight components by their fix history.
- **Mining the history**: map problem reports to fixing changes — three extraction routes, none perfect (~50% of closed reports mappable in Eclipse/Mozilla):
  1. ticket IDs in commit messages + close-time correlation (richest: carries severity, discovery site);
  2. maintenance-branch commits (precise, needs branch discipline);
  3. log-message keywords ("fix", "bug", "crash") — lightweight, loses provenance.
  Then ask the learning questions: which modules are fixed most? in which phase did defects originate (spec/coding/QA)? which error *types* recur (→ build or adopt a checker for that type)? who/what context produced them — used to fix training and process, never to blame individuals, or they will stop filing honest data.
- Empirically validated predictors of defect-proneness:

| Predictor | Signal | Reported strength |
|---|---|---|
| Change churn | components changed most, relative to others | ~89% discrimination accuracy (Windows Server) |
| Recency/novelty | recently changed or newly added code | new code ~2.5× defect-prone vs old |
| Import sets (Vulture) | *what* a component depends on characterizes its risk domain | 93–100% of importers of certain headers had vulnerabilities |
| Dependency structure | complex/cyclic/central position in the dependency graph; domino effect from depending on defect-prone components | validated on Windows Server 2003 |
| **Bug cache** | 10% of components: new + recently changed + recently fixed + co-changed with fixed | holds 73–95% of the next defects |
| Complexity metrics | counts of branches/paths/params | project-specific — use only when validated against this project's history |

  Recommenders (Hatari) surface the risk in the IDE at edit time ("8 of 9 previous fixes to this method introduced a new defect").
- **Correlation ≠ causation — "fool's gold"**: Eclipse's second-highest defect-density author was Erich Gamma *because the riskiest tasks flow to the most experienced*. Before acting on any mined correlation, have a causal theory and check that removing the "cause" would plausibly change the effect (ch-12 discipline applied to process data).
- Per phase: specification errors → check specs early against clients, raise precision (contracts, formal fragments), automate generation; programming errors → everything for specs, plus reduce structural complexity (fewer/shorter paths, less coupling), document, **keep debugging assertions in the code**, adopt languages/features that make the recurring mistake impossible; QA errors → every escaped defect is also a QA gap: add a test for the problem *and its relatives*, review code, calibrate coverage metrics against actual defect history (high coverage of never-failing code proves little), consider mutation testing to measure the suite's detection power.
- The end goal is **fixing the process, not just the product**: the space-shuttle group's database records, for every error, how it was introduced *and how it slipped past every filter* (design review? inspection? verification?) — then repairs the filters, and checks whether similar errors escaped through the same holes. The practices behind that record ("plan before code, no change without blueprints, complete accurate history") are cheap; they are standard in every engineering discipline except software.
- Process-failure defects need process fixes: an early Android release shipped with a diagnostic root console left enabled, so any text typed on the phone was also executed as a superuser shell command (typing "reboot" in a text message rebooted the phone). No amount of code-level debugging skill prevents that class — a release checklist does.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Bug report in hand, agent starts editing code | Reproduce the failure first, exactly as reported (same symptom/backtrace) | Without reproduction you can neither observe nor verify a fix | ch-4 |
| "Tests pass, so the defect is gone" claim without a prior failing run | Demand the red→green transition on a test reproducing the failure | Absence of failure ≠ absence of defect (Dijkstra); infections need not propagate | ch-1 |
| Fix proposed for a failure that was never re-run | Verify: original scenario now passes, regression suite still passes | The fix retrospectively proves causality; without it you have a guess | ch-15 |
| Debugging session with untracked guesses | Run the explicit loop: hypothesis → prediction → experiment → conclusion; log each step | Unlogged debugging is Mastermind from memory; hypotheses must be falsifiable | ch-6 |
| >10 min of quick-and-dirty poking without progress | Stop; write the problem statement and switch to the systematic method | Time-boxing keeps the light process from becoming a random walk | ch-6 |
| Large failing input / long repro recipe | Simplify (ddmin) or isolate (dd) until 1-minimal before diagnosing | Minimal cases pinpoint code, communicate, and dedupe reports | ch-5, ch-13 |
| "Worked yesterday, fails today" (regression) | Bisect the change history with an automated test; don't eyeball the whole diff | Ordered changes + resolved tests = O(log n) to the failure-inducing change | ch-13 |
| A warning/anomaly precedes the failure, agent "fixes" it | Prove causality by experiment before resolving: remove candidate cause, failure must vanish | Post hoc ergo propter hoc — precedence is not causation | ch-12 |
| Two candidate explanations for a failure | Prefer the one whose alternate (passing) world is closest — Ockham's razor | The actual cause is the minimal difference to the closest passing world | ch-12 |
| Choosing which passing run/config/version to diff against | Pick the alternate world closest to the failing one | Everything shared is excluded from the search space | ch-12, ch-13 |
| Value known-wrong at point X, origin unknown | Follow the backward slice/dependences; judge each origin sane vs infected; recurse on infected | Infected value with all-sane origins = the defect; anything off-slice is exculpated | ch-7, ch-9 |
| Multiple candidate origins to inspect | Order: failing assertions > proven causes > anomalies > code smells > raw dependences | Ranked by likelihood of indicating the defect | ch-15 |
| C/C++ failure, heap not yet validated | Run a memory checker (Valgrind class) before any value-level reasoning | Reasoning about variables atop a corrupted heap is wasted; kills Heisenbugs | ch-10 |
| Failure disappears under debugger/logging (Heisenbug) | Suspect undefined behavior/uninitialized state; check via static analysis + memory checker; confirm by two independent observation means | The observation environment masks the infection, not the defect | ch-4 |
| Nondeterministic failure (timing, threads, randomness) | Put a control layer on each input source: inject clock, capture PRNG seed, record/replay schedule | Only controlled inputs make runs deterministic and diffable | ch-4 |
| Problem found in-house, agent files a ticket | Write a failing automated test instead; tickets only for what can't become a test | The test proves, re-checks, and guards; the ticket rots | ch-2 |
| Test plan drives the GUI for a logic bug | Test at the lowest layer that reproduces: unit > functionality > presentation | Human-friendly interfaces are automation-hostile and fragile | ch-3 |
| Unit untestable because functionality calls presentation | Apply dependence inversion: depend on an abstraction, substitute an automated implementation | Breaking the dependence isolates the unit for test and debug | ch-3 |
| Debugger session with no stated expectation | State prediction before observing ("a[0] should be 11 here") | Observation without a hypothesis degenerates into stepping-as-tourism | ch-6, ch-8 |
| During dd/simplification the failure "changes shape" | Match failures on backtrace/message; different failure ⇒ UNRESOLVED, not FAIL | Otherwise you isolate the cause of an artifact, not the reported bug | ch-13 |
| Diagnosis rests on "obviously X holds" | Verify the obvious with an observation | The program "obviously" should work — trust nothing unverified | ch-6, ch-12 |
| Fix adds a condition matching the failing symptom (`if (x==bad_input)`) | Reject: fix the cause, not the symptom | Symptom patches leave the defect and add a new one | ch-15 |
| Agent can't explain *why* the fix works | Block the fix until it predicts how the infection chain breaks | Debugging into existence produces unmaintainable accidents | ch-15 |
| Fix ready to merge | Sweep for the same mistake elsewhere; prefer refactorings that make the mistake impossible | Mistakes are patterns; one instance implies siblings | ch-15 |
| Two defects suspected | Fix one at a time; retest between | Interleaved fixes mask and mimic each other | ch-15 |
| Post-fix, failure persists | Revert before continuing; re-audit the logbook conclusions | A wrong correction must not contaminate further observations | ch-15 |
| Writing pre/postconditions or invariants during debugging | Keep them in the code (assertions on in production, if lightweight) | Assertions are permanent infection detectors; fail fast shortens defect→failure distance | ch-10 |
| Assertion guards user input or a safety-critical result | Replace with real validation / independent check that can't be compiled out | Assertions are for internal invariants only | ch-10 |
| No spec to judge a run against | Compare against normal: coverage diff vs nearest passing neighbor, inferred invariants, return-value stats | Abnormal ≠ wrong, but anomalies are where defects live | ch-11 |
| Reviewing/testing budget to allocate across modules | Weight by defect history: most-fixed, most-churned, newest, co-changed-with-fixed | Pareto: ~80% of defects in ~20% of modules | ch-16 |
| Escaped-to-field defect being closed | Also add tests for the problem *and its relatives*; ask how it slipped past each QA filter | An escaped defect is simultaneously a QA-process defect | ch-16 |
| Watchpoint proposed on a hot path | Prefer conditional breakpoints at accessors / interpreter hooks; watchpoints cost ~1000× | Software watchpoints check every instruction | ch-8 |
| Unreproducible-report triage | Adopt problem-environment circumstances one at a time, likeliest and cheapest first | Each adoption is an experiment; the enabling circumstance is itself a cause | ch-4 |
| Correction too risky / code not ours / defect is a flaw | Ship a workaround, but keep the problem report open | Workarounds decay; the defect will resurface after unrelated change | ch-15 |
| Mined correlation used to justify action | Require a causal theory first (would removing it change the outcome?) | Fool's gold: risky tasks correlate with expert authors | ch-16 |
| Cause isolated but not an error (e.g., legit upstream change) | Treat as workaround site; keep the report open; locate the actual defect separately | Causes suggest fixes but need not be defects | ch-13, ch-15 |

## Anti-patterns

- **Fixing without reproducing** — detection cue: a patch or diagnosis in a thread where no failing execution/log of the *reported* symptom exists. (ch-4)
- **Post hoc ergo propter hoc** — cue: "the log shows warning W before the crash, so W is the cause" with no experiment removing W. (ch-12)
- **Debugging into existence / ignorant surgery** — cue: repeated small semantic edits ("try `n-1`", "add a null check") each followed by "does it pass now?", with no hypothesis stated. (ch-15)
- **Symptom patch** — cue: fix contains a literal from the failing input/report (`if (account == 123)`, special-casing the crashing value). (ch-15)
- **Trusting the obvious** — cue: diagnosis chain contains "clearly/obviously X" for an unobserved fact. (ch-6)
- **Shotgun logging** — cue: dozens of ad-hoc print statements added and later deleted in the same PR; no logging levels or off-switch. (ch-8)
- **Debugger tourism** — cue: long stepping transcripts with no predictions recorded and no hypothesis narrowed. (ch-8)
- **Cosmic-ray blaming** — cue: closing an unreproducible bug as hardware/environment flake without exhausting controllable input sources. (ch-4)
- **Assertion abuse at boundaries** — cue: `assert` on user/network/file input, or on a result whose failure would be critical. (ch-10)
- **Mastermind from memory** — cue: mid-session contradiction of an earlier finding; no logbook of hypotheses/experiments to consult. (ch-6)
- **Ticket instead of test** — cue: internally discovered, reproducible bug filed as prose with no accompanying failing test. (ch-2)
- **Multi-fix commit** — cue: one change claiming to fix several unrelated failures at once. (ch-15)
- **Artifact chasing** — cue: during input minimization, the crash location/backtrace changed and minimization continued anyway. (ch-13)
- **Fool's-gold metrics** — cue: process decision (blame, gating, rewrite) justified purely by a mined correlation. (ch-16)

## Applicability & exemptions

- **Cost is proportional to mystery.** TRAFFIC's full apparatus (logbook, delta debugging, state diffing) is for failures that survive the quick look. Zeller himself licenses a ~10-minute quick-and-dirty pass first (ch-6). Do not demand a logbook for a typo-level fix whose failing test, cause, and fix are all visible in one screen.
- **Delta debugging preconditions**: an *automated, deterministic* test and a *decomposable* configuration. Without them (manual-only repro, monolithic binary input with no meaningful splits, flaky test), fall back to manual binary search plus the ch-4 control layers. dd degrades to quadratic when most outcomes are UNRESOLVED — invest in validity-aware splitting or don't bother.
- **Isolated causes are not verdicts.** dd output is an *actual cause*, possibly one of several, and possibly not an error at all (ch-13). Never auto-convert a dd result into a code fix; it licenses a workaround and a search location only.
- **Anomaly/prediction techniques are probabilistic.** Coverage diffs, statistical debugging, Daikon invariants, and defect predictors order the search; they must not fire as review blockers ("this line is red in Tarantula"). Small-benchmark figures (Siemens suite, etc.) do not generalize to arbitrary codebases.
- **"Keep assertions on in production" has explicit carve-outs**: hard-real-time/safety systems where an abort is not an option (prove instead), hot paths where measurement shows real cost, and anything user-facing (fail gracefully via a handler, not a raw abort). Input validation and critical-result checking are never assertions.
- **Memory-checker-first applies to unmanaged languages.** In managed runtimes (JVM, .NET, Python) the heap-integrity step is moot; the analogous first move is reading the exception/backtrace and checking for known-corrupting concurrency.
- **The human boundary**: no automation can determine the *defect* — that requires knowing what is correct, i.e., a spec or a human judgment (ch-14). Techniques here deliver causes, anomalies, and transitions; treating their output as "the bug is here, fix it" oversteps what the method proves.
- **Vocabulary collision**: Zeller's "code smell" = statically detectable defect pattern (uninitialized read, leak), not Fowler's design smell — ↔ `refactoring-fowler-beck`: don't cross-apply the catalogs.
- Field data collection (ch-11/16) is gated by privacy and overhead constraints; per-developer defect mining is gated by the blame hazard (ch-16).

## Candidate lexicon rows

| bug report received, edit proposed before any failing run | **Reproduce before you fix** — a failure you can't re-run can't be observed, and a fix for it can't be verified | Did we run the failure, with the exact reported symptom, before touching code? | blocker | plan | src: why-programs-fail ch-4 |
| debugging exchange shows edits with no stated expectation | **Hypothesis before experiment** — debug in explicit hypothesis→prediction→experiment→conclusion steps, logging each; unlogged guessing repeats itself | What is the current hypothesis, and what result would falsify it? | should | plan | src: why-programs-fail ch-6 |
| diagnosis blames the last warning/change/anomaly seen before the failure | **Prove the cause by removing it** — a cause is established only by an experiment where its absence makes the failure vanish; precedence is not causation | Did an experiment show the failure disappears without this candidate? | blocker | review | src: why-programs-fail ch-12 |
| failing input or repro recipe is large and mostly irrelevant | **Minimize the failing case (ddmin)** — shrink until every remaining element is failure-relevant; minimal cases localize code and dedupe reports | Does removing any single remaining piece make the failure disappear? | should | write | src: why-programs-fail ch-5 |
| "worked in version X, fails in Y" with many intervening changes | **Bisect the history, don't read the diff** — an automated test over ordered changes finds the failure-inducing change in O(log n) | Is there an automated test both endpoints can run, and are changes ordered? | should | plan | src: why-programs-fail ch-13 |
| fix special-cases the failing value or symptom (`if (x == badcase)`) | **Fix the cause, not the symptom** — symptom patches leave the defect live and add a new one; the fix must break the infection chain at the defect | Can we state how this change breaks the defect→infection→failure chain? | blocker | review | src: why-programs-fail ch-15 |
| repeated tweak-and-rerun edits with "passes now" as sole justification | **No debugging into existence** — a change is a fix only when its author can predict why the failure (and siblings) disappear before running it | Could the author explain this fix to a reviewer without "it just works"? | should | review | src: why-programs-fail ch-15 |
| a defect fixed at one site, pattern-identical code untouched elsewhere | **Sweep for sibling defects** — one mistake is a pattern; search for other instances and prefer refactors that make the mistake impossible | Where else could the same misconception have produced the same bug? | should | review | src: why-programs-fail ch-15 |
| wrong value identified, agent scans the whole file/program for origins | **Track infections along the backward slice** — only statements the value depends on can have infected it; judge each origin sane/infected and recurse until an infected value has all-sane origins | Which statements can legally influence this value, and which origin is infected? | judgment | plan | src: why-programs-fail ch-9 |
| internally found, reproducible problem written up as a ticket | **A failing test beats a bug report** — encode in-house problems as automated tests; tickets are only for what can't become code or a test | Could this report be a failing test in the suite instead? | should | write | src: why-programs-fail ch-2 |
| failure vanishes when logging/debugger/timing changes | **Heisenbug means undefined behavior** — suspect uninitialized state or races, run memory/race checkers, and confirm observations by two independent means before trusting either | What unchecked undefined behavior could make observation mask this failure? | judgment | plan | src: why-programs-fail ch-4 |
| C/C++ crash investigated by reasoning about variable values first | **Heap sanity before value reasoning** — run a memory checker before all other debugging; value analysis atop a corrupted heap is wasted work | Has a Valgrind-class check ruled out memory corruption in this run? | should | plan | src: why-programs-fail ch-10 |
