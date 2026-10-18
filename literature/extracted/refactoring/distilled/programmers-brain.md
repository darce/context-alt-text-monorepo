# The Programmer's Brain — distilled

> **Source**: Felienne Hermans, *The Programmer's Brain: What every programmer needs to know about cognition*, Manning (2021) · extracted from `../programmers-brain.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory that grounds readability rules in *measured cognition* rather than taste: it supplies the mechanism (STM holds 2–6 **chunks**; code is read through chunking against LTM knowledge) behind why other books' rules work. Unique deliverables: the three-way diagnosis of confusion (knowledge/information/processing-power → LTM/STM/working-memory), the **intrinsic/extraneous/germane cognitive-load** taxonomy as a refactor-targeting tool, **beacons** as the unit of code scannability, the empirical naming corpus (Feitelson's **three-step name mold**, name-quality-predicts-bugs, words-beat-abbreviations, consistency-beats-quality, names-fossilize-early), Arnaoudova's **linguistic antipatterns** with fNIRS evidence that *misleading names raise cognitive load where bad formatting does not*, the five programming activities (search/comprehend/transcribe/increment/explore) each stressing a different memory system, and the interruption-cost data (~15 min to resume an edit) that justifies externalizing working memory into notes, todos, and subgoal comments. For an agent this book translates directly into HOW TO READ, NAME, and ANNOTATE code — the cognitive counterpart to philosophy-of-software-design's structural rules and the *why* behind refactoring-fowler-beck's smell catalog.

## Chapter map

- ch-1 — Decoding your confusion while coding: 3 confusion types → 3 memory systems; diagnose before acting
- ch-2 — Speed reading for code: chunking, STM limits, beacons, what makes code scannable/chunkable
- ch-3 — How to learn programming syntax quickly: forgetting curve, retrieval practice, why lookup round-trips cost more than they seem
- ch-4 — How to read complex code: intrinsic vs extraneous load; cognitive refactoring; dependency graphs and state tables as WM prostheses
- ch-5 — Reaching a deeper understanding of code: roles of variables; text vs plan knowledge; Sillito's 4 stages; reading code ≈ reading prose; 7 comprehension strategies
- ch-6 — Getting better at solving programming problems: models/representation choice; mental models vs notional machines; metaphors leak
- ch-7 — Misconceptions: positive/negative transfer between languages; misconceptions and how tests/docs pin corrected assumptions
- ch-8 — How to get better at naming things: the naming evidence base; molds; Feitelson's 3 steps; consistency; names→bugs
- ch-9 — Avoiding bad code and cognitive load: code smells mapped to cognition; linguistic antipatterns; misleading names measurably worse than ugly structure
- ch-10 — Getting better at solving complex problems: memory types; automatization; germane load; worked examples beat raw practice
- ch-11 — The act of writing code: 5 programming activities × memory systems; interruption cost; externalizing state (notes, todos, subgoals)
- ch-12 — Designing and improving larger systems: cognitive dimensions of codebases (CDCB); design maneuvers and trade-offs per activity
- ch-13 — How to onboard new developers: curse of expertise; neo-Piagetian stages; semantic wave; one activity at a time

---

## ch-1 — Decoding your confusion while coding {#ch-1}

Not all confusion is the same; each type maps to a different cognitive system and demands a different fix:

| Confusion type | Failing system | Observable signal | Correct response |
|---|---|---|---|
| **Lack of knowledge** | LTM (long-term memory) | An operator/keyword/concept you can't interpret at all (the APL `⊤` case) | Learn the concept *before* re-reading the code — don't brute-force |
| **Lack of information** | STM (short-term memory) | You understand each part but must navigate elsewhere (what does `toBinaryString()` do?) and forget where you were | Fetch the definition; keep notes of the navigation path |
| **Lack of processing power** | Working memory | You can read every line but can't hold the trace; you feel the urge to scribble intermediate values | Externalize: state table, dependency graph — don't re-read hoping |

Model: LTM ≈ disk (facts, syntax, experience), STM ≈ RAM/cache (holds what you just read, <30 s, 2–6 slots), working memory ≈ processor (STM applied to a problem; where **tracing** — mental execution — happens). All three run on every task. The urge to write something down is a *signal* of working-memory overload, and it is correct to obey it.

Agent translation: when code is confusing, classify the confusion first. "I don't know this idiom" → look it up; "I don't have the callee's contract" → read the callee; "too many interacting values" → build the table. Re-reading the same lines repeatedly is the tell that you skipped this diagnosis.

## ch-2 — Speed reading for code {#ch-2}

~60% of programmer time is spent understanding code, not writing it (Xia et al. 2017) — reading skill dominates output.

**Chunking** (de Groot's chess studies; replicated on code by McKeithen with ALGOL): experts recall real programs far better than novices, but on *scrambled* programs everyone is equal. Experts don't have bigger memories — they recognize larger units ("a Sicilian opening", "a for-loop over the array", "insertion sort") that occupy one STM slot each. Corollary: **what you can remember of code after a brief look is a diagnostic of what you know** — and code that experienced readers cannot chunk is objectively harder code, not a reader deficiency.

STM holds 2–6 items for <30 seconds. Meaningless names (`b`, `l` as loop vars) block chunking exactly the way random chess boards do. `l` is additionally perceptually confusable with `1`.

**How to write chunkable code** (all empirically supported):

1. **Use design patterns** — Tichy: after pattern training, maintenance time drops significantly *on code that contains patterns* (and not on code without; effect size varies by pattern — observer > decorator). Familiar shapes are pre-built chunks.
2. **Write high-level comments** — comments make reading slower *because they are read*; high-level comments ("prints the tree in order") help readers chunk whole blocks; line-restating comments ("increment i") *burden* chunking (Fan 2010). Novices lean on comments far more than experts (Crosby) — comments are onboarding infrastructure, not failure markers.
3. **Leave beacons** — a **beacon** is a code element that triggers "aha, now I see": names like `root`/`tree`, field pairs like `left`/`right`, a swap idiom, an init-to-empty-list, a string literal naming the domain.
   - **Simple beacons**: self-explaining single elements — meaningful identifiers, and in simple code even operators (`+`, `>`, `&&`) and structural keywords.
   - **Compound beacons**: several simple beacons that only carry meaning together — `self.left` + `self.right` ⇒ binary tree; a for-loop header (variable + init + bound + increment) reads as one unit.
   - Beacons work by confirming/refuting the reader's running hypothesis about what the code does. Experts navigate by them (Crosby: experts use beacons heavily, novices don't); beacon-free code forces line-by-line reading for everyone.

Canonical beacon example (compressed from the book's tree-traversal listing): in a `print_in_order(root)` function, the identifiers `Node`, `root`, `left`, `right` plus a "tree" comment let a reader conclude "in-order binary-tree traversal" without tracing a single line — remove those names and the same code must be traced.

Readers also scan before reading (an iconic-memory pass; Sperling's grid experiments show more is briefly stored visually than STM can process): structure, nesting depth, whitespace, standout lines all transmit information before a single identifier is parsed — code *shape* is part of the interface. Deliberate "code at a glance" first looks are a legitimate reading step, not sloppiness.

Order-of-recall diagnostics: *how* someone groups material reveals their knowledge organization (McKeithen: beginners memorized ALGOL keywords via sentences; experts grouped `TRUE/FALSE`, `IF/THEN/ELSE`). What you can reproduce of code you just read maps exactly to the chunks you own — usable as a self-test on any unfamiliar stack.

## ch-3 — How to learn programming syntax quickly {#ch-3}

The **forgetting curve** (Ebbinghaus, confirmed by Murre 2015): ~50% of new information gone in an hour, 75% in two days, unless revisited. Two fixes:

- **Spaced repetition** — fewer total exposures spread over weeks beats massed practice (Bahrick: 26 sessions at 8-week intervals → 76% recall a year later, vs 56% for 2-week intervals). Cramming produces knowledge that evaporates unless repeatedly reused.
- **Retrieval practice** — actively *trying to recall* strengthens memory far more than re-reading (Ballard's poem studies: recall improves across unstudied re-tests). The flashcard prompt side matters, not the answer side. Before searching for syntax, attempt recall first — even a failed attempt strengthens the path.

Distinguish **storage strength** (how well encoded; effectively only increases — memories are essentially never deleted) from **retrieval strength** (how findable; decays). "I'd recognize it instantly among six near-identical candidates but can't produce it" (the book's `rbegin()/rend()` reverse-iterator example) = retrieval-strength failure. Looking it up yet again does not fix it; the lookup-instead-of-recall loop is self-perpetuating.

Why memorized syntax matters even with search engines:
1. What's in LTM determines what you can chunk (ch-2) — syntax fluency is reading speed, not trivia.
2. Each lookup is an interruption — Parnin's 10,000-session study: after an interruption it takes ~15 minutes to resume editing code; only 10% of interrupted method-edits resume within a minute; the browser detour invites further distraction. The lookup's true cost is context reconstruction, not the search itself.

**Elaboration**: when learning a new concept, deliberately connect it to known ones — What does this remind me of? Same syntax elsewhere? Same context? An alternative to something I know? How do other languages express it? — because memories are a network (**schemata**), and new facts stored with more connections are easier to retrieve. Memories are *altered on save* to fit existing schemata (Bartlett's *War of the Ghosts*: recalled stories drift toward the reader's cultural priors) — expect your recollection of code to be biased toward what you already believed it did.

Flashcard mechanics that transfer to any deliberate-vocabulary effort: add a card when you meet a new construct *or when you catch yourself about to search for one* (the search impulse is the "not yet known" signal); retire cards after repeated successes; for advanced constructs put equivalent code on both sides (loop ↔ comprehension) rather than prose.

## ch-4 — How to read complex code {#ch-4}

**Cognitive load** = demand on working memory; overload = can't process. Sweller's taxonomy:

| Load type | Meaning | Code analogue | Action |
|---|---|---|---|
| **Intrinsic** | Inherent problem hardness | Essential/inherent complexity | Cannot be removed — only chunked or split |
| **Extraneous** | Accidental presentation cost | Accidental complexity: unfamiliar idioms, scattered definitions, bad names, noisy formatting | **This is the refactor target** |
| **Germane** | Effort of storing insight back to LTM | Learning from the code | Preserve room for it (see ch-10) |

Extraneous load is *reader-relative*: a list comprehension is zero extra load to one reader, overload to another. Two computationally identical snippets share intrinsic load but not extraneous load.

**Cognitive refactoring**: a behavior-preserving change whose goal is readability *for the current reader now*, not long-term maintainability — and it may legitimately be a *reverse* refactoring: inlining a method whose vague name (`calculate()`, `transform()`) hides its meaning, reordering methods near their call sites, rewriting a lambda/comprehension/ternary as a plain loop or if. Do it on a throwaway branch; roll back once understanding is solidified (or keep the pieces that turn out to be genuinely better, e.g. a truer method name discovered while inlining). ↔ contra refactoring-fowler-beck: there refactoring is a permanent design improvement; Hermans sanctions deliberately "worse" temporary transformations as comprehension tools.

When structure still overloads WM, offload to paper/notes:
- **Dependency graph**: circle all variables, link same-variable occurrences, circle calls, link calls to definitions, link class instances to definitions. Single-call methods spotted this way are inline candidates. Read by following the drawn links instead of searching — searching-while-reading is the double task that overloads WM.
- **State table**: one column per variable, one row per loop iteration/branch/coherent block; execute the code on paper filling every cell (**tracing / cognitive compiling**). For calculation-heavy code where variables interact. Fill it completely — skipping variables defeats the purpose.

Graph = the code's *structure*; table = its *calculations*. Both double as artifacts you can re-load after an interruption.

## ch-5 — Reaching a deeper understanding of code {#ch-5}

**Roles of variables** (Sajaniemi): 11 roles cover almost all variables. The reason variables are hard to reason about is grain size — "integer" is too coarse, `number_of_customers` too fine; roles are the missing mid-grain vocabulary:

| Role | Definition | Canonical example |
|---|---|---|
| **Fixed value** | Set once, never changes | `pi`, config read at startup |
| **Stepper** | Iterates a *predictable* sequence | `i` in a for-loop; `size = size/2` in binary search |
| **Flag** | Records that something happened/holds | `is_error`, `is_available` |
| **Walker** | Traverses a structure by a path *unknown in advance* | pointer walking a linked list / tree-search index |
| **Most recent holder** | Latest value in a series | `line = file.readline()`, `element = list[i]` |
| **Most wanted holder** | Best-so-far in a search | running `min`/`max`/first-match |
| **Gatherer** | Accumulates/aggregates | `sum += x` (or `sum(list)` in functional form) |
| **Container** | Holds many elements, add/remove | list, stack, tree |
| **Follower** | Trails another variable | `prev` pointer; lower bound in binary search |
| **Organizer** | Re-arranged copy for processing | sorted copy, string→char array |
| **Temporary** | Used briefly | swap `temp` |

Role combinations identify program archetypes (stepper + most-wanted-holder = search loop). Roles apply across paradigms (an object's `age` field incremented on `birthday()` is a stepper). Students taught the framework outperform controls; embedding the role in the name saves the reader the derivation. Historical note: **Apps Hungarian** (Simonyi's original — *semantic* prefixes like `cX` count-of-X, `rw`/`col` in Excel's codebase) was effectively a roles system; **Systems Hungarian** (type prefixes, `strName`) is the degenerate misreading that made the whole idea disreputable, likely via one word ("type" for "kind") in Simonyi's thesis.

**Text structure knowledge vs plan knowledge** (Pennington): knowing what each keyword/variable does vs knowing what the author *intended* and how parts connect. Frameworks with fragmented focal points (e.g. dependency injection) can leave you with full text knowledge and no plan knowledge — "every line is clear, the structure is invisible."

**Sillito's four stages** of comprehension (the natural deepening path — do them in order):
1. Find a **focal point** (entry point, failing line, profiler hotspot).
2. Expand from it — build the **slice** (all lines transitively related to the focal line).
3. Understand a concept from a set of related entities (heavily-called methods = key concepts).
4. Understand concepts across the whole program (data structures + their operations + their constraints).

**Reading code is cognitively reading**: fMRI shows program comprehension activates natural-language areas (BA21/44/47) even with obfuscated identifiers (Siegmund); language aptitude predicts learning-to-program far better than numeracy (Prat: language 17% of variance, math 2%, WM+reasoning 34%). Programmers scan first (70% of lines in the first 30% of reading time — Uwano); experts read by call structure, novices linearly.

Therefore the seven prose-comprehension strategies transfer to code:

| Strategy | Applied to code | Agent move |
|---|---|---|
| **Activating** | Prime prior knowledge; identify unfamiliar concepts and study them *before* reading on | Learning a concept while reading code that uses it doubles the load — sequence them |
| **Monitoring** | Mark ✓/? per line — track what you do and don't understand | Turns "I'm confused" into an addressable line list; also the right shape for asking for help |
| **Determining importance** | Pick the N most influential lines, state why | Teams disagree productively here — differences reveal priorities and experience |
| **Inferring** | List every identifier; classify domain word vs programming concept vs convention; flag ambiguous ones | Is a `shipment` an order? A factory batch? Domain meaning must be resolved, not assumed |
| **Visualizing** | State tables, operation tables (list each identifier + the operations applied to it — operations reveal types, types reveal roles) | The `zipWith(f, as, bs)` example: indexing reveals lists, application reveals a function |
| **Questioning** | What were the author's decisions, assumptions, benefits, downsides, alternatives? | Moves you from text knowledge to plan knowledge |
| **Summarizing** | Natural-language summary: goal, key lines, domain concepts, constructs, decisions | Doubles as documentation; the exit artifact of a comprehension task |

## ch-6 — Getting better at solving programming problems {#ch-6}

**Representation determines solution difficulty** (the two-trains-and-a-bird problem: model the bird's zigzag = hard calculus; model elapsed time = trivial). Languages/libraries embed representations — APL makes vector solutions trivial and others awkward; Java nudges toward nested loops. Choosing the model *is* most of the solving.

**Mental models** — abstractions in working memory used to reason about the system. Properties that matter operationally: they are *incomplete*, *unstable* (decay/mutate), *multiple-and-contradictory* (old wrong models coexist with new correct ones and resurface under high load — the snowman-in-a-sweater effect), and people are *frugal* (prefer tweak-and-rerun over building a model — the observed debugging antipattern). Johnson-Laird: **concrete, determinate models reason better** (88% vs 58% correct when the description pinned one arrangement vs many) — so make the model specific: list objects, relationships, constraints; answer test questions against it and refine.

**Notional machine**: a *correct-but-incomplete* abstraction of how the machine executes code (variables-as-boxes, call-stack-as-paper-stack, substitution model of evaluation) — unlike mental models it must not be wrong, only partial. Notional machines leak into language ("holds a value", "returns", "points to"). Metaphors have failure modes: the NEMO study (496 novices) — "variable = box" beats "variable = label" on simple tasks but *creates* the a-variable-can-hold-two-values misconception. Choose explanatory metaphors knowing which misconception each one seeds, and know which abstraction level (language / interpreter / VM / OS) your current model deliberately ignores — debugging optimized code fails precisely where the source-level model diverges from execution.

## ch-7 — Misconceptions: Bugs in thinking {#ch-7}

**Transfer** — prior knowledge shaping performance on new material — comes in flavors worth naming because each predicts a different failure:

- **Positive transfer**: existing knowledge accelerates learning (knowing Java's loop anatomy gives you the checklist for any language's loops). Strongest when you have *mastery* of the source skill, the tasks are *similar*, the *context/tooling* matches (same IDE helps), the useful prior knowledge is *pointed out explicitly*, the two feel *associated*, and you *like* the source domain.
- **Negative transfer**: prior knowledge silently imports wrong assumptions — Java dev assumes Python enforces variable initialization; C# dev doesn't know Java checked exceptions exist (*wrong model held with confidence — they think they have the right one*); OO habits actively obstruct learning functional languages.
- **High-road vs low-road**: conscious strategic transfer ("do I need to declare variables here?") vs automatic skill transfer (Ctrl-C works everywhere).
- **Near vs far**: C#→Java transfers; chess→logic and programming→general intelligence essentially do not (Salomon's overview; de Groot's random-board result). Expect to relearn *strategies*, not just syntax, in a genuinely different paradigm — and note that "knowing programming" doesn't automatically transfer even between concepts within one language.

A **misconception** is a belief that is (1) faulty, (2) held consistently across situations, (3) held with confidence. It is not fixed by being told you're wrong: it requires **conceptual change** — replacing the model, not patching it — and the replaced model persists in LTM and resurfaces under cognitive load (the snowman-sweater effect; suppression, not deletion). Canonical programming examples (Sorva catalogs 162, each rooted in a *sensible* prior):

- Assignment stores a live equation — `total = maximum + 12` keeps tracking `maximum` (true in math, and in Prolog-like languages).
- A `while` condition is re-checked continuously mid-body (that's what "while" means in English).
- A variable's *name* constrains its value — `minimum` can't hold a large number.
- Parameter names must differ between call site and signature (over-generalizing "names are used once").

Defenses that work in a codebase:
1. Assume you can be confidently wrong — verify assumptions about behavior by *running* code, not by inspection alone.
2. **Codify each discovered wrong assumption as a test** ("this value is never negative") — the test detects regressions of the misconception *and* documents the truth for the next reader (misconceptions resurface; tests don't forget).
3. Add documentation at the trap site.
4. Pair/review — colliding assumptions expose whose model is broken; and when learning a new language, ask people who learned the same language *pair* in the same order, because misconception sets are pair-specific.

## ch-8 — How to get better at naming things {#ch-8}

Why names dominate comprehension: identifiers are 33% of tokens and 72% of *characters* in Eclipse's 2M LOC; one in four code reviews contains naming remarks (Allamanis); names are the only documentation guaranteed to be in front of the reader; good names are beacons (ch-2), and they are the retrieval keys by which the reader's LTM finds domain knowledge. Naming is genuinely hard: median probability that two developers pick the *same* name for the same thing is 7% (Feitelson, 347 subjects) — but names others chose are still widely *understood*, because they draw on shared **name molds**.

Evidence base (each row is a decision input):

| Finding | Study | Consequence |
|---|---|---|
| Syntactic rule-set for names (dictionary words; 2–4 words; no odd caps/underscore patterns; no type-encoding) | Butler | Lintable hygiene floor; the 2–4-word limit matches STM chunk capacity |
| Consistency across a codebase matters more than local optimality | Allamanis | Consistent-and-mediocre beats good-but-inconsistent; deviation is the defect |
| **Naming quality is set early and never improves within a codebase** ("identifier quality takes hold early") | Lawrie, 78 codebases / 3 decades | Invest in names in the *first* files of a project/module; newcomers copy what exists (same effect as tests-beget-tests) |
| Full-word identifiers: 19% more defects found per minute vs letters/abbreviations (abbrev. = no better than letters) | Hofmeister, 72 pros | Spell words out; abbreviations buy nothing for reading |
| Longer names are harder to *recall* (per syllable) | Lawrie | Balance clarity vs length; audit prefix/suffix conventions — the added info must outweigh recall cost |
| Single letters have no shared meaning except `i/j/k/n` int, `s` string, `c` char | Beniamini | Never assume a letter conveys a type/role to the reader |
| camelCase: +51.5% identification accuracy, ~0.5 s slower vs snake_case; trained readers of one style are *slower* in the other | Binkley | Accuracy favors camelCase, but consistency with the codebase wins — never mix |
| Bad-name locations statistically co-locate with bug locations (FindBugs) | Butler 2009 | **Name quality is a bug-risk marker**: treat clusters of bad names as review hotspots (correlation — smell, not proof) |

**Name molds**: for "the maximal benefits someone can receive per month," Feitelson's subjects produced 14+ normalized shapes — `max_benefit`, `max_benefit_per_month`, `max_monthly_benefit`, `benefits`, `benefit_max_num`, `monthly_benefit_limit`… All denote the same value; the diversity is the problem. Different molds within one codebase add extraneous load (the reader must *find* the key concept in a different position each time) and break LTM retrieval (`max_benefit_amount` reminds you of your `max_interest_amount` code; `interest_maximum` doesn't). Agree on a small mold set per codebase; extract the existing molds before adding names.

**Feitelson's three-step name mold** (names produced with the model judged better 2:1 in a controlled follow-up with 100 fresh subjects):
1. **Select the concepts** to include — driven by *intent*: what the object holds and what it's used for. If a name needs an adjacent explanatory comment, the comment's key words belong *in the name*. Include the qualifier a reader will need: units (kilos), dimension (horizontal), provenance (`user_input` is unsafe — and rename on transformation: validated data gets a *new* name saying so).
2. **Choose the words** for each concept — one word per concept codebase-wide; maintain a **project lexicon** recording the chosen word and registered synonyms (readers otherwise hunt for a nuance between synonyms that doesn't exist).
3. **Compose using a mold** — a fixed ordering pattern (`max_X`, `X_per_Y`, `max_X_per_Y`…). Limit the codebase to few molds; prefer natural-language order (`max_points`, not `points_max`); prepositions read naturally (`indexOf`, `elementAt`).

Timing: don't polish names mid-problem-solving — WM is already saturated (that is *why* `foo` happens; the placeholder is a rational load-shedding move). Review time is the naming-quality gate. Mechanical review checklist: list every identifier in the diff *out of context* and ask — meaning clear without the code? ambiguous? confusing abbreviation? similar names that denote dissimilar things? Tooling exists: Naturalize learns a codebase's own conventions and flags deviations (14 of its first 18 suggested renames were accepted upstream; it once flagged a JUnit convention the maintainers themselves violated so often the violation looked canonical).

What a name feeds the reader (three LTM knowledge channels — a good name hits at least one cleanly): **domain knowledge** (`customer` unlocks buys-products/has-address associations), **programming concepts** (`tree` unlocks root/traverse/flatten), and **conventions** (`j` unlocks "inner loop counter"). A name like `nmcntravg` feeds none of them despite "containing" all the information; `name_counter_average` costs double the characters and a fraction of the mental effort — character count is the wrong economy.

## ch-9 — Avoiding bad code and cognitive load: Two frameworks {#ch-9}

**Code smells** (Fowler's 22, structural) explained by cognition — the mechanism tells you which smells matter most and when:

| Smell family | Cognitive failure |
|---|---|
| Long parameter list, complex switch | **WM overload** — more than ~6 un-chunkable items cannot be held (params that chunk, like `xOrigin,yOrigin,xDest,yDest` → 2 chunks, are exempt) |
| God class, long method | **No chunk boundaries** — no named sub-units means no documentation-by-name and no chunking; reader falls back to line-by-line |
| Code clones (duplication) | **Mischunking** — near-identical `goo()` gets chunked *as* `foo()`; the small difference is exactly what the brain discards, and the resulting misconception persists (ch-7) |

Smelly code is empirically more error-prone and more change-prone (Khomh on Eclipse: God classes significant error contributors; large-class/long-method significantly change-prone in >75% of releases).

**Linguistic antipatterns** (Arnaoudova) — *conceptual* mislabeling, orthogonal to structure: methods that do more / less / the opposite of what they say; identifiers containing more / less / the opposite of what their names claim. Real-world frequency: 11% of setters also return a value; 2.5% of methods have name and comment contradicting each other; **64% of identifiers starting with `is` are not Boolean**.

The killer experiment (Fakhoury, fNIRS + eye tracking): snippets with linguistic antipatterns measurably raise cognitive load (blood-oxygenation) and attract extra fixation; snippets with mangled *formatting/structure* annoyed participants but produced **no statistically detectable load increase**. → **A lying name is worse than ugly code.** Mechanism: the wrong name retrieves wrong LTM facts (transfer of falsehood) and licenses wrong chunking (`isValid` "must be" a Boolean — the brain economizes by not checking). Review priority follows: name/behavior mismatches outrank formatting nits by a full tier. Measurement aside: self-rated load (Paas scale, 1 question) correlates well with the biometrics — asking "how hard was this to read?" is a valid instrument.

## ch-10 — Getting better at solving complex problems {#ch-10}

Problem solving is **not a generic skill** — Pólya-style "understand/plan/execute" fails because devising a plan depends entirely on domain knowledge in LTM (you cannot plan a palindrome check in APL without knowing what APL offers), and because generic prompts give LTM no retrieval cues (specific cues like "tail division" retrieve; "make a plan" doesn't). Experts largely *recognize and recreate* solutions from **episodic memory** rather than solve from scratch.

Memory taxonomy: **procedural/implicit** (automatized skills — touch typing, bracket-closing, the reflexive breakpoint), **declarative/explicit** split into **episodic** (experienced solutions) and **semantic** (facts, syntax). Implicit skills pass through **cognitive → associative → autonomous** phases; only autonomous-phase skills are cognitively free. **Automatization** of small skills (via deliberate, spaced, varied repetition — e.g. write/adapt many loop variants) frees WM budget for the actual problem. Automatized skills also resist unlearning (negative transfer: `foreach` typed in Python for years).

**Germane load** completes the ch-4 taxonomy: the capacity needed to store what you're learning back to LTM. When intrinsic+extraneous load saturates WM, *nothing is retained* — the after-a-heavy-session-remember-nothing effect, and the reason max-difficulty work teaches the least.

**Worked examples** (Sweller): students given solved, explained problems got 5× faster *and* transferred better to new problems than students who only solved problems — replicated in programming. "You don't become an expert by doing expert things" (Kirschner). Practical forms: read code deliberately (code-reading club, GitHub sources, architecture books), exchange code-plus-summary with others, study solutions *with their design rationale*. For an agent: examples of a codebase's existing solved patterns are higher-value context than another attempt from first principles.

## ch-11 — The act of writing code {#ch-11}

Five distinct activities (Green/Blackwell/Petre's **cognitive dimensions of notation** framework), each stressing a different memory system — "programming" is never one task:

| Activity | What it is | Hard on | Support with |
|---|---|---|---|
| **Searching** | Locating specific info (bug site, callers, init point) | STM | Notes: what you seek, paths explored + verdicts, what's next; breadcrumb comments |
| **Comprehension** | Building understanding of unfamiliar code | Working memory | Incrementally updated model/diagram; refactor-for-readability; notes double as resume points |
| **Transcription** | "Just coding" a fully formed plan | LTM | Syntax fluency (ch-3) |
| **Incrementation** | Add a feature = search + comprehend + transcribe | All three | *Split it*: announce and perform the sub-activities one at a time |
| **Exploration** | Sketching with code; plan emerges while coding | WM (design on the fly) | Jot design direction/decisions as you go — notes free capacity, they don't break flow |

Debugging = a mix of all five. Agent translation: name which activity you're in; when a task stalls, the fix is usually that you're doing three activities at once — serialize them.

**Interruptions** (Parnin, 10K sessions; van Solingen): ~15–20 min each, ~20% of developer time; a typical developer gets *one* uninterrupted 2-hour block per day; only 10% of interrupted method-edits resume in under a minute. Comprehension has a warm-up phase (cognitive load peaks mid-task — Nakagawa/fNIRS), which is what an interruption destroys. Interruptions during a task (vs between tasks) also raise annoyance, anxiety, and double error rates (Bailey) — so interrupt (and accept interruption) at task boundaries.

Recovery/prevention techniques — all forms of **externalizing working memory**:
1. **Store the mental model**: brain-dump current model into comments/notes before switching. Code rarely captures the author's *reasoning* (goals, alternatives considered) — "self-documenting code" doesn't cover thought processes (explicitly citing Ousterhout: comments capture what was in the designer's mind but couldn't be represented in the code). ↔ aligns with philosophy-of-software-design ch-12/13 against the comments-are-failures doctrine.
2. **Support prospective memory** (remembering to do future things): TODO markers at the exact site, deliberate compile-error **roadblock reminders** to force return to half-done code; know that undated TODOs rot (136M on GitHub).
3. **Subgoal labeling**: before coding a multi-step task, write the numbered plan as comments in the file, then fill each in — after any interruption the plan is the resume point; leftover subgoal comments become documentation. (Empirical: provided subgoals structure learners' solutions — Margulieux.)

**Multitasking is impossible for non-automatized tasks** — parallel work is only real when one task is autonomous-phase (ch-10); "productive while chatting" self-assessments are reliably wrong (partners rate the output lower; interrupted readers need +50% time).

Agent translation of the whole chapter: an agent's context window *is* its working memory and it suffers the same losses across turns/compaction. Persist plans, per-path search verdicts, and discovered constraints into notes/todos/comments instead of re-deriving them; re-derivation is the agent's 15-minute resume tax.

## ch-12 — Designing and improving larger systems {#ch-12}

**CDCB** (cognitive dimensions of codebases — Hermans' adaptation of CDN): evaluate a codebase/library/framework by what it does to *brains*, not machines. The dimensions, each with its detection question:

| Dimension | Question | Example signal |
|---|---|---|
| **Error-proneness** | How easy is it to make a mistake? | Dynamic typing, inconsistent conventions, missing docs (Hanenberg: static types measurably speed error location, even vs better-documented dynamic code) |
| **Consistency** | Are similar things similar? | Same molds, same file layouts; built-in vs user-defined indistinguishable |
| **Diffuseness** | How much space per construct? | Chunk count, not just LOC; loop vs comprehension |
| **Hidden dependencies** | Are dependencies visible? | Callers invisible from callee (JS handlers on HTML); undocumented install requirements |
| **Provisionality** | Can you think incomplete thoughts in it? | Strictness (types/assertions) blocks sketching |
| **Viscosity** | How hard is change? | Type ripple, non-modular blobs, slow build/test cycles count too |
| **Progressive evaluation** | Can partial work be run? | Optional params with defaults; REPL/live programming |
| **Role expressiveness** | Is each part's role visible? | `()` on calls, syntax highlighting, `is_`-prefix Booleans; linguistic antipatterns = low role expressiveness |
| **Closeness of mapping** | How near is code to the domain? | `findCustomers()` vs `executeQuery()`; DDD is a closeness-of-mapping program |
| **Hard mental operations** | Does using it require heavy off-system thinking? | Long ordered param lists, vague names to memorize (`execute()`, `control()`), multi-format juggling |
| **Secondary notation** | Can authors add non-semantic meaning? | Comments, named/keyword arguments |
| **Abstraction** | Can users build abstractions as powerful as built-ins? | Subclassing allowed vs API-calls-only |
| **Visibility** | Can you see the parts of the system? | Returning typed objects vs opaque strings/JSON |

A **design maneuver** = a change targeting one dimension (add types → less error-prone; rename to domain terms → closer mapping). Dimensions trade off: types reduce error-proneness but add viscosity; provisionality/progressive evaluation invite never-cleaned-up sketch code (error-proneness); named parameters and type annotations add role expressiveness but increase diffuseness.

Dimensions × activities (from ch-11): consistency helps searching/comprehension but *taxes transcription* (new code must be made to fit); hidden dependencies and diffuseness hurt searching; role expressiveness and visibility drive comprehension; closeness of mapping drives incrementation, viscosity blocks it; provisionality + progressive evaluation enable exploration, hard mental operations kill it. **Optimize the codebase for its dominant expected activity** — a stable library is mostly *searched*, a young app mostly *incremented* — and re-audit as the mix shifts.

## ch-13 — How to onboard new developers {#ch-13}

The standard failed onboarding: dump people+domain+workflow+codebase at once, assign a "simple" fix, newcomer drowns in cognitive load, both sides draw wrong conclusions. Root cause: the **curse of expertise** — mastery erases the memory of how hard acquisition was ("that's trivial" = curse-of-expertise marker). Experts differ in kind, not just speed: they chunk code, error messages, and solutions; a novice's "Array index out of bounds" is three items, not one.

**Neo-Piagetian stages** (Lister) are *domain-specific and codebase-specific* — an expert in Java can be sensorimotor in Haskell, and learning any new concept causes temporary regression:

| Stage | Behavior | Support that works |
|---|---|---|
| Sensorimotor | Cannot trace program execution | Teach the execution model first; nothing else lands |
| Preoperational | Can trace; guesses meaning from a few traces; seems erratic (brilliant then absurd) | Vocabulary building (flashcards); diagrams do NOT help yet |
| Concrete operational | Reads code deductively via chunks/beacons; overcommits to first strategy | Diagrams now help; prompt strategy reflection |
| Formal operational | Reasons about code *and own approach*; self-directed | Just answer questions |

**Semantic wave** (Maton): effective explanation goes abstract (why the concept exists) → *unpack* to concrete details (syntax, mechanics) → *repack* to abstract, letting the learner connect to prior knowledge. Antipatterns: **high flatline** (all abstract, no syntax), **low flatline** (all mechanics, no purpose), **downward escalator** (never repacks — no time to integrate).

Concrete practices: limit each newcomer task to *one* of the five activities (ch-11) — comprehension/summarization tasks are better first tasks than "easy" features (a summarizing task produces documentation as a side effect; a feature task forces search+comprehend+increment simultaneously); prepare LTM support (glossary of domain concepts; list of libraries/frameworks/tools — "we use Laravel, deploy on Heroku with Jenkins" is noise to someone missing one term); pre-cut the search space for any implementation task; run collaborative code reading using the seven ch-5 strategies; monitor load — guessing and nonsense conclusions = overload, back off. Shared cognitive vocabulary ("I lack chunks for this" vs "I'm confused") makes the process discussable. For agents, onboarding = cold-starting in an unfamiliar repo: the same order applies — glossary and execution model before code, comprehension before modification, one activity at a time.

---

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Confused by code | Classify the confusion first: unknown concept / missing info / too much to trace | Each maps to a different memory system with a different fix (learn / navigate / externalize) | ch-1 |
| Re-reading the same code 3+ times without progress | Stop re-reading; build a dependency graph or state table | Working memory is overloaded; repetition doesn't add capacity, offloading does | ch-1, ch-4 |
| You feel the urge to jot intermediate values | Obey it — trace into a state table (all variables, every step) | The urge is the WM-overload signal; partial tables defeat the purpose | ch-4 |
| Code that a competent reader cannot summarize after a scan | Treat as refactor signal: add beacons, split into named units | Code that defies chunking is objectively harder, not a reader deficiency | ch-2 |
| Writing code others will read | Include beacons: domain names, telltale field/idiom pairs, high-level comments | Experts navigate by beacons; beacon-free code forces line-by-line reading | ch-2 |
| Comment restates the adjacent line | Delete it; comment only intent, decisions, and block-level purpose | Line-level comments burden chunking; high-level comments enable it | ch-2 |
| About to leave a task with reasoning only in your head | Write the mental model down (comment/note): goal, approach, alternatives rejected | Code cannot express thought processes; resume cost after loss ≈ 15 min | ch-11 |
| Starting a multi-step implementation | Write the numbered subgoal plan as comments first, fill in one by one | Subgoal labels survive interruption and structure the solution | ch-11 |
| Task feels stuck / doing everything at once | Name the current activity (search/comprehend/transcribe/increment/explore); serialize | Each activity stresses a different memory system; mixing multiplies load | ch-11 |
| Searching a codebase across many files | Log what you seek, each path explored + verdict, next candidates | Searching is STM-bound; unlogged exploration gets re-explored | ch-11 |
| Naming any new identifier | Feitelson 3-step: choose concepts (intent, units, provenance) → words (lexicon) → mold (codebase's) | Model-guided names judged better 2:1 in controlled experiment | ch-8 |
| Tempted to abbreviate an identifier | Use full dictionary words, 2–4 per name | +19% defects found/min with word names; abbreviations read no better than single letters; >4 words exceeds chunk capacity | ch-8 |
| Two names for one concept (or one name for two) in a diff | Enforce one word per concept; record it in a project lexicon | Synonyms make readers hunt for nonexistent nuance; consistency is what LTM retrieval keys on | ch-8 |
| Your preferred name/style conflicts with the codebase's | Follow the codebase (mold, case style, conventions) | Consistent-and-mediocre beats good-but-inconsistent; trained readers are slower in a mixed style | ch-8 |
| First files of a new project/module | Over-invest in naming and conventions now | Naming quality fossilizes at project birth and never improves (Lawrie); newcomers copy what exists | ch-8 |
| Single-letter variable outside `i/j/k/n/s/c` idiom | Rename to a word | No shared reader expectation exists for other letters | ch-8 |
| Renaming/aliasing during data transformation (e.g. validation) | Give transformed data a new name encoding its new state (`unsafe_input` → `validated_input`) | The name is where provenance/units information survives | ch-8 |
| Cluster of bad names in one region | Flag region as bug-risk hotspot for deeper review | Bad-name locations statistically co-locate with bugs | ch-8 |
| Name implies wrong type/behavior (`is*` non-Boolean, getter with side effect, setter returning value) | Fix name or behavior — priority above formatting nits | Linguistic antipatterns measurably raise cognitive load; bad formatting does not; wrong names seed persistent misconceptions | ch-9 |
| Method/function name vague (`calculate`, `execute`, `transform`, `control`) | Rename to what it does, or inline it while comprehending | Vague names force memorization (hard mental operation) and block chunking | ch-4, ch-12 |
| >~6 parameters or un-chunkable items in one signature/expression | Group into cohesive objects/chunks | WM capacity is 2–6 chunks; chunkable groups (origin/destination pairs) are exempt | ch-9 |
| Adding a function nearly identical to an existing one, similar name | Unify, or make names/differences loud | Clones get mischunked as identical; the small difference is what readers discard | ch-9 |
| Giant method/class in a diff | Split into named units | Names are chunk boundaries and free documentation; God units force line-by-line reading | ch-9 |
| Unfamiliar idiom blocks your comprehension | Cognitive-refactor it to a familiar form on a scratch branch; restore codebase idiom after | Readability is reader-relative; the transformation is a comprehension tool, not a design change | ch-4 |
| Comprehending unfamiliar code | Focal point → slice → related concepts → cross-entity constraints; scan before reading; summarize after | Matches expert reading behavior; summary doubles as documentation | ch-5 |
| Variable's purpose unclear | Identify its role (stepper, gatherer, most-wanted holder…); role combos identify the algorithm archetype | Roles are the missing mid-grain vocabulary; stepper+most-wanted = search | ch-5 |
| Verified an assumption the code's names/docs got wrong | Pin it with a test and a comment at the trap site | Misconceptions resurface under load; tests are the only durable correction | ch-7 |
| Working in language B with habits from language A | Actively list similarities/differences; verify "obvious" semantics by running code | Negative transfer produces confident wrong models (checked exceptions, init rules) | ch-7 |
| Explaining a concept via metaphor | Pick the metaphor knowing which misconception it seeds | Variable-as-box aids simple cases but creates holds-two-values errors | ch-6 |
| Solving a hard problem from scratch when solved examples exist | Study worked examples (existing patterns + rationale) first | Worked examples: 5× faster and better transfer than unaided solving | ch-10 |
| Marathon high-load session with nothing retained/noted | Reduce concurrent load or checkpoint learnings explicitly | Saturated WM leaves no germane capacity — nothing gets stored | ch-10 |
| Interruption arriving (or you must interrupt) | Defer to a task boundary; if unavoidable, brain-dump model + leave a roadblock reminder | Mid-task interruptions cost ~15 min and double errors; boundaries are cheap | ch-11 |
| Assessing a library/codebase's usability | Audit CDCB dimensions against its dominant activity (searched vs incremented vs explored) | Each activity needs different dimensions high; optimizing the wrong one wastes effort | ch-12 |
| Applying a design maneuver (add types, rename, split) | Name the dimension improved and the ones taxed | Every maneuver trades dimensions (types: −error-proneness +viscosity) | ch-12 |
| Onboarding (a person or yourself) into a new codebase | Glossary + execution model first; one activity per task; comprehension/summary before features | Overload prevents both performance and retention; summaries produce docs | ch-13 |
| Saying "this is trivial/easy" about something you mastered long ago | Curse-of-expertise check: re-estimate the learner's chunk inventory | Experts chunk what novices experience as many items | ch-13 |

## Anti-patterns

- **Lying name (linguistic antipattern)** — name promises what code doesn't do (`isValid` holding an int, `getCustomers()` returning a Boolean, setter that returns, method-comment contradiction). Detection: compare name's implied type/arity/side-effects against signature and body. The empirically worst readability defect — raises measured cognitive load where bad formatting doesn't.
- **Mischunkable clone** — near-duplicate code under a near-duplicate name (`foo`/`goo`). Detection: diff two similar functions; if the difference is small and unannounced, readers will chunk them as identical.
- **Chunk-proof blob (God method/class)** — no named sub-units, no beacons. Detection: can't produce a one-sentence summary per screenful; a reader must trace line-by-line.
- **Line-echo comments** — `i++ // increment i`. Detection: comment adds zero words not derivable from the line. Burdens chunking; crowds out intent comments.
- **Systems Hungarian** — type prefixes in names (`strName`, `int_page_counter`). The degenerate misreading of Simonyi's semantic (Apps) Hungarian; adds length without meaning in typed/IDE contexts.
- **Mold soup** — many name molds for the same concept family (`max_benefit`, `benefit_max_num`, `monthly_benefit_limit` in one codebase). Detection: normalize names in a module and count distinct orderings.
- **Lookup carousel** — repeatedly Googling the same syntax instead of ever attempting recall; retrieval strength never builds, each lookup costs an interruption.
- **Tweak-and-rerun debugging** — mutating code hoping the bug moves, instead of building a (mental) model; the "frugal brain" default under load.
- **Guess-driven reading (preoperational mode)** — asserting what code does from a partial trace or a name alone; the erratic-junior signature, also an agent failure mode under context pressure.
- **High/low flatline & downward escalator** — explanations that stay abstract, stay concrete, or never let the learner repack; onboarding/doc-writing antipatterns.
- **Simultaneous-activity task** — a "starter" task requiring search+comprehension+incrementation at once (most "good first issues"); overloads exactly the person with the fewest chunks.
- **Interrupt-mid-edit culture** — pinging on no signal; interruptions during a task double errors vs boundary-timed ones.

## Applicability & exemptions

- **Reader-relativity**: extraneous load depends on the reader's LTM. An idiom (comprehension, lambda, ternary) is not objectively a smell — for a team fluent in it, replacing it *adds* inconsistency. Cognitive refactorings are personal and usually temporary; don't push them into the shared codebase unless the team shares the unfamiliarity.
- **Chunkability overrides raw counts**: the 2–6 limit applies to *chunks*, not tokens. A 4-parameter signature that forms two natural pairs is fine; N lines of boilerplate that chunk as one known pattern are fine. Don't fire length rules mechanically.
- **Consistency can beat "better"**: a locally superior name/style that breaks the codebase's mold is a net loss (Allamanis; Binkley's style-training effect). Only migrate conventions wholesale, never per-diff. Camel-case's measured accuracy edge does NOT justify converting a snake_case codebase.
- **Longer ≠ always better names**: full words help comprehension but recall degrades per syllable; prefix/suffix schemes need their information value to beat their recall cost. The 2–4-word band is the target, not "maximally descriptive".
- **Name↔bug correlation is not causation**: bad-name clusters flag review hotspots; renaming alone is not a bug fix.
- **Comments doctrine is scoped**: the book defends *high-level, intent, and model-dump* comments; it agrees line-echo comments are harmful. Neither "no comments" nor "comment everything" survives the evidence.
- **Deliberate temporary "worse" code** (inlining, de-idiomizing, roadblock compile errors) is legitimate only on a scratch/understanding branch or as an explicit self-reminder — never merged.
- **Biometrics not required**: self-rated effort (Paas-style single question) correlates with fNIRS/eye measures; "this was very hard to read" from a reviewer is admissible evidence.
- **Study population caveats**: several key studies are small (10–20 subjects for fNIRS; 36 for Prat) or single-language (Java tooling for Naturalize/LAPD); treat exact percentages as direction, not calibration.
- **The five-activity model** describes work on an existing codebase; greenfield sketching is dominated by exploration, where provisionality beats strictness — premature typing/linting rigor there taxes thinking (restore rigor before merge).
- **Expert exemption for onboarding rules**: formal-operational newcomers (experienced dev, familiar stack) can self-direct; the one-activity-per-task discipline is for genuinely new territory — including an agent's own cold starts.

## Candidate lexicon rows

| naming a new identifier | **Feitelson three-step name mold** — pick intent concepts, then codebase-lexicon words, then the codebase's existing mold; model-guided names win 2:1 over ad-hoc | Does this name use the same concepts, words, and word-order as its siblings? | should | write | src: programmers-brain ch-8 |
| diff introduces a synonym for an existing domain term | **One word per concept** — synonyms make readers hunt for a nuance that doesn't exist and break LTM retrieval across the codebase | Does the project lexicon already have a word for this concept? | should | review | src: programmers-brain ch-8 |
| name implies a type/behavior the code doesn't have (`is*` non-Boolean, getter with side effects) | **No lying names** — linguistic antipatterns measurably raise cognitive load (worse than bad formatting) and seed persistent misconceptions | Do the name's implied type, arity, and side-effects match the signature and body? | should | review | src: programmers-brain ch-9 |
| tempted to abbreviate an identifier | **Full words in names** — readers find 19% more defects/min with word identifiers; abbreviations read no better than single letters | Is every word in this name a dictionary word (2–4 words total)? | should | write | src: programmers-brain ch-8 |
| your preferred style/mold conflicts with the codebase's | **Consistency beats local quality** — consistent-and-mediocre outperforms good-but-inconsistent; mixed styles slow trained readers | Am I matching the codebase's convention or optimizing my own taste? | should | write | src: programmers-brain ch-8 |
| first commits of a new project or module | **Names fossilize at birth** — identifier quality is set early and never improves within a codebase; later contributors copy what exists | Are these first names/conventions the ones we want copied forever? | should | plan | src: programmers-brain ch-8 |
| code a competent reader can't summarize after a scan | **Chunkability is a refactor signal** — code without beacons or named sub-units forces line-by-line reading; add domain names, idiom beacons, block-intent comments, or split | Could a fluent reader one-sentence each screenful of this? | judgment | review | src: programmers-brain ch-2 |
| diff adds a near-duplicate of an existing function with a similar name | **Clones get mischunked** — readers chunk `goo()` as `foo()` and discard exactly the small difference; unify or make the difference loud in the name | Will a reader who knows the original notice what differs here? | should | review | src: programmers-brain ch-9 |
| comment restates the adjacent line | **Comment intent, not mechanics** — line-echo comments burden chunking; high-level comments (goal, decision, rejected alternative) are what code cannot express | Does this comment say anything not derivable from the line itself? | should | write | src: programmers-brain ch-2 |
| leaving a task, or mid-task with reasoning only in-head | **Externalize working memory** — resume cost after context loss is ~15 min; persist the plan, path-verdicts, and model into notes/todos/subgoal comments rather than re-deriving | If I lost all context now, what note would let me resume in one minute? | should | plan | src: programmers-brain ch-11 |
| signature or expression forces tracking >~6 unrelated items | **Respect the chunk budget** — working memory holds 2–6 chunks; group parameters/values into cohesive named objects (natural pairs already chunk and are exempt) | Do these items chunk, or must a reader hold each one separately? | judgment | review | src: programmers-brain ch-9 |
| cluster of vague/broken names in one region of a diff | **Bad names mark bug hotspots** — naming-violation sites statistically co-locate with defects; review those regions deeper, don't just restyle them | Where names are worst, has the logic had extra scrutiny? | judgment | review | src: programmers-brain ch-8 |
