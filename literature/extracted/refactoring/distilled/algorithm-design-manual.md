# The Algorithm Design Manual — distilled

> **Source**: Steven S. Skiena, *The Algorithm Design Manual*, 3rd edition (2020) · extracted from `../algorithm-design-manual.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory about **algorithm selection**: given a problem shape, which named technique or catalog problem to reach for. It supplies the recognition questions ("is this really a graph problem in disguise?"), the **design-graphs-not-algorithms** doctrine, the n-thresholds table that says when brute force is simply correct, the DP applicability test (principle of optimality + state-space sizing *before* committing), hardness recognition (when to stop seeking exact answers and go heuristic/approximate), and a 75-problem identification index — the "if your problem looks like X, use Y" hot path. Where other books here optimize code that exists, this one prevents the unfixable mistake: implementing the wrong algorithm, or hand-rolling one that a catalog lookup would have solved.

## Chapter map

- ch-1 — Introduction to Algorithm Design: algorithms vs heuristics; proving correctness/incorrectness; modeling; estimation
- ch-2 — Algorithm Analysis: Big Oh; the n-thresholds table (which complexity class survives which input size)
- ch-3 — Data Structures: dictionary/heap/array selection rules; hashing tricks (dedup, canonicalization, fingerprinting)
- ch-4 — Sorting: "when in doubt, sort"; the sorting-solves-it list; sorting vs hashing; pragmatics
- ch-5 — Divide and Conquer: binary search variants; recurrences; recognizing convolutions
- ch-6 — Hashing and Randomized Algorithms: Bloom filters, minwise hashing, Monte Carlo vs Las Vegas
- ch-7 — Graph Traversal: the graph-flavor checklist; adjacency list vs matrix; what BFS/DFS each solve
- ch-8 — Weighted Graph Algorithms: MST, shortest path, network flow; design graphs, not algorithms
- ch-9 — Combinatorial Search: backtracking; pruning; best-first/A*; the 20–100 item exact-search limit
- ch-10 — Dynamic Programming: memoization; the two applicability tests; state-space sizing; when DP is doomed
- ch-11 — NP-Completeness: recognizing hardness; the four source problems; easy/hard twin problems
- ch-12 — Dealing with Hard Problems: approximation, heuristic search, simulated annealing; what to do after "it's NP-hard"
- ch-13 — How to Design Algorithms: the master question checklist (strategy before tactics)
- ch-14 — A Catalog of Algorithmic Problems: how to use the identification index
- ch-15 — Catalog: Data Structures {#see below}
- ch-16 — Catalog: Numerical Problems
- ch-17 — Catalog: Combinatorial Problems
- ch-18 — Catalog: Graph Problems (Polynomial-Time)
- ch-19 — Catalog: Graph Problems (NP-Hard)
- ch-20 — Catalog: Computational Geometry
- ch-21 — Catalog: Set and String Problems

---

## ch-1 — Introduction to Algorithm Design {#ch-1}

**Algorithm vs heuristic** — the book's first and most abused distinction: an *algorithm* always produces a correct result; a *heuristic* usually does a good job but provides no guarantee. Never label a greedy procedure an algorithm until you've proven it or failed to break it. Reasonable-looking algorithms are easily incorrect (nearest-neighbor and closest-pair greedy tours for TSP both fail on simple instances); correctness must be demonstrated, not assumed.

**Demonstrating incorrectness**: one counterexample settles it. Hunt for counterexamples by:
- *Thinking small* — when a greedy heuristic fails, there is usually a 2–3 element instance that shows it.
- *Seeking ties* — instances where the heuristic's selection rule can't decide.
- *Going extreme* — all-equal weights, zero weights, collinear points, empty/full sets.
Searching for counterexamples is the best way to disprove a heuristic's correctness; **mathematical induction** is usually the right way to verify a recursive or incremental-insertion algorithm.

**Modeling is the step that matters**: "Modeling your application in terms of well-defined structures and algorithms is the most important single step towards a solution." Ask which standard object your mess reduces to: **permutations** (arrangements, tours, orderings, sequences), **subsets** (selections, clusters), **trees** (hierarchies, taxonomies), **graphs** (relationships, networks), **points** (locations, records with numeric fields), **polygons** (shapes, regions), **strings** (text, sequences of tokens). Once named, the catalog (ch-14–21) tells you what is known.

**Narrowing instances** is honorable: restrict a graph problem to trees, 2-D to 1-D, general weights to unit weights — until a correct efficient algorithm exists. Two output-spec traps: (a) ill-defined questions ("best route" — best by what metric?); (b) asking for *all* solutions when *any* or *the count* suffices.

**Estimation** (war-story-grade skill): estimate every quantity at least two independent ways (volume, weight, analogy) and trust the answer only when the ways agree within a factor of ~2. A sound reasoning trail matters more than the numbers.

## ch-2 — Algorithm Analysis {#ch-2}

The **RAM model** — each simple operation costs one step — is coarse but its predictions rank algorithms correctly in practice. Big Oh + worst-case is the tool that makes comparison tractable; best-case is near useless, average-case needs real probability theory.

### The n-thresholds table (Figure 2.4 — the brute-force budget)

Operations at 1 ns each. **This is the table to consult before choosing exhaustive search.**

| n | lg n | n | n lg n | n² | 2ⁿ | n! |
|---|---|---|---|---|---|---|
| 10 | 0.003 μs | 0.01 μs | 0.033 μs | 0.1 μs | 1 μs | 3.63 ms |
| 20 | 0.004 μs | 0.02 μs | 0.086 μs | 0.4 μs | 1 ms | 77 years |
| 30 | 0.005 μs | 0.03 μs | 0.147 μs | 0.9 μs | 1 sec | 8.4×10¹⁵ yrs |
| 40 | 0.005 μs | 0.04 μs | 0.213 μs | 1.6 μs | 18.3 min | — |
| 50 | 0.006 μs | 0.05 μs | 0.282 μs | 2.5 μs | 13 days | — |
| 100 | 0.007 μs | 0.1 μs | 0.644 μs | 10 μs | 4×10¹³ yrs | — |
| 10⁴ | 0.013 μs | 10 μs | 130 μs | 100 ms | — | — |
| 10⁶ | 0.020 μs | 1 ms | 20 ms | 16.7 min | — | — |
| 10⁹ | 0.030 μs | 1 sec | 30 sec | 31.7 years | — | — |

Skiena's rules of thumb drawn from it:
- **n! dead by n ≥ 20**; **2ⁿ dead by n > 40** (so exact subset enumeration is fine to ~40 items, permutation enumeration to ~10–15 raw, ~20 with pruning).
- **n² usable to n ≈ 10,000, hopeless past 1,000,000.**
- **n and n lg n practical to a billion items.** lg n never sweats.

Dominance pecking order: `n! ≫ cⁿ ≫ n³ ≫ n² ≫ n^(1+ε) ≫ n log n ≫ n ≫ √n ≫ log²n ≫ log n ≫ log n/log log n ≫ log log n ≫ α(n) ≫ 1`. Logarithms arise whenever things are repeatedly halved or doubled — see a loop that halves, expect O(log n).

**War story (Mystery of the Pyramids)**: replacing a 2ⁿ-flavored search with precomputed lookup tables sped a computation ~30,000×; the million-dollar 16-CPU alternative offered at most 100×. *Lesson: in any sufficiently large computation, the algorithmic improvement beats the hardware upgrade.* (Bonus lesson: turn the compiler optimizer on before profiling.)

## ch-3 — Data Structures {#ch-3}

**Contiguous (arrays) vs linked**: arrays give constant-time index access, cache locality, zero pointer overhead; lists give constant-time insertion/deletion mid-structure and never overflow. Dynamic arrays (doubling) amortize growth at O(1) per element.

**Selection principle**: data structure design must balance *all* the operations the algorithm needs — the fastest structure for operations A and B jointly is often not the fastest for either alone (sorted array: O(log n) search but O(n) insert; unsorted: reverse). Corollary: *picking the wrong data structure is disastrous; picking the very best among adequate ones is usually not critical.*

**Dictionary operation costs** (the selection table — see also catalog ch-15):

| Need | Reach for |
|---|---|
| membership/lookup only, moderate–large n | **hash table** (the default dictionary) |
| ordered iteration, predecessor/successor, min/max, range | **balanced BST** (or skip list) |
| static key set, built once | **sorted array + binary search** |
| n ≲ 100 | unsorted array — nothing else pays for itself |
| skewed/clustered access pattern | splay tree / self-organizing list |
| repeated min (or max) extraction | **priority queue / heap** — not a full dictionary |

Building algorithms around dictionaries and priority queues yields both clean structure and good performance.

**Hashing beyond dictionaries** (§3.7 — recognize these problem shapes):
- **Duplicate detection**: hash each object; only collisions need full comparison (is this document already in the corpus?).
- **Canonicalization**: hash a *canonical form* (sorted letters, lowercased, stemmed, Soundex) so all equivalent variants collide — here collisions are the answer, not the enemy (anagram sets, near-duplicate names).
- **Fingerprinting/compaction**: represent huge objects by short hashes/prefixes; sort or compare the fingerprints, resolve rare collisions with the full object.

**Specialized structures to know exist**: suffix trees/arrays (string search), kd-trees (spatial), adjacency lists (graphs), bit vectors (dense sets), union–find (disjoint sets under merging).

**War story (Stripping Triangulations)**: a greedy mesh-stripping heuristic went from hopeless to orders-of-magnitude faster via a priority queue integrated with a dictionary. *Lessons: with large data only linear/near-linear algorithms are fast enough; the right data structure is often the whole speedup.* **War story (String 'em Up)**: same simulation ran on binary tree → hash table → suffix tree, each swap extending the reachable input size by ~an order of magnitude at fixed hardware.

## ch-4 — Sorting {#ch-4}

"**When in doubt, sort**" — sorting the data is one of the first things to try in the quest for efficiency; it is a rare application where the O(n log n) cost of a library sort is the bottleneck.

**Problems that fall to a sort** (then a linear scan/binary search):

| Problem | After sorting |
|---|---|
| Searching | binary search O(log n) |
| Closest pair of numbers | adjacent in sorted order — linear scan |
| Element uniqueness / duplicates | equal items adjacent — linear scan |
| Frequency counting / mode | runs are contiguous; count per run |
| Selection / median / kth largest | index k of the sorted array |
| Convex hull | insert points left-to-right, maintain hull |
| Set intersection/union | merge-scan of two sorted lists (sort the *smaller* set if only sorting one) |

**Sorting vs hashing**: hashing beats sorting for search, uniqueness, mode (linear expected time); hashing *cannot* do closest pair, median, convex hull, or anything needing order. Expected-linear hash beats worst-case n log n sort when order is irrelevant.

**Pragmatics**: specify order via an application-supplied comparison function; use the library sort, not your own. **Stability** is not guaranteed by fast sorts — get it by appending initial position as a secondary tie-breaker key. Beware many equal keys sending naive quicksort quadratic. Algorithm choice within O(n log n) (heapsort/mergesort/quicksort) usually doesn't matter; what matters: n ≤ 100 → insertion sort is fine; n ≥ ~10⁸ → external/multiway-merge territory; integer keys in small range → bucket/counting/radix sort in linear time (only when keys distribute evenly).

**War story (Give me a Ticket on an Airplane)**: cheapest sum-of-two-fares — exploit that the input lists arrive sorted; expand candidate pairs best-first from (1,1) via a **priority queue**, with a **hash table** guarding duplicates, stopping at the first feasible answer. Recognize this "enumerate combinations in cost order, stop early" shape.

## ch-5 — Divide and Conquer {#ch-5}

**Binary search and its variants are the quintessential divide-and-conquer algorithms.** Variants to recognize: counting occurrences (search for k−ε and k+ε boundaries); **one-sided/galloping search** (probe 1, 2, 4, 8… when the target is near the front or the array is unbounded); searching a monotone function's domain for a threshold (bisection on answers — "binary search the solution value" turns optimization into decision). War story: bisecting a genome region with pooled assays = binary search on an interval.

Recurrences: divide-and-conquer costs follow T(n) = aT(n/b) + f(n); the **master theorem** classifies them (leaves dominate / balanced / root dominates). Don't derive from scratch — pattern-match.

**Convolution recognition** (§5.9): if your problem multiplies/correlates every element of one sequence against every shift of another — polynomial multiplication, string matching with wildcards, cross-correlation, all pairwise sums (X+Y) — it is a **convolution**, and FFT computes it in Θ(n log n) instead of O(n²). "The first step is to recognize your problem is a convolution."

## ch-6 — Hashing and Randomized Algorithms {#ch-6}

Randomized quicksort's Θ(n²) worst case is a lottery ticket you almost certainly don't hold: the distribution is so tight you nearly always run close to expectation. The key to any randomized algorithm is *setting up a situation where you can bound the probability of success* — if you can't state the bound, you don't have an algorithm, you have hope.

- **Bloom filter**: membership with tunable false positives, zero false negatives, in a fraction of exact-set memory. Reach for it when "probably present" is acceptable and memory is tight.
- **Birthday paradox**: expect collisions once you've hashed ~√m items into m slots — sizes your table and your fingerprint width.
- **Minwise hashing**: estimate set/document similarity from small sketches (retain min hash values) instead of full contents.
- **Rabin–Karp**: rolling-hash string matching — hash of each window in O(1) from the previous window.
- **Monte Carlo algorithms** (e.g. randomized primality testing) are always fast, usually correct, and typically err in only one direction; repeat trials to drive error below any threshold. Las Vegas algorithms are always correct, usually fast.

**War story (Giving Knuth the Middle Initial)**: a conjecture whose random counterexamples would be rare (probability 1/n per trial) can't be supported by a handful of clean tests — run the cheap exhaustive loop over the weekend. *Lesson: compute how likely a chance counterexample is before treating "no counterexample found" as evidence.*

## ch-7 — Graph Traversal {#ch-7}

Graphs can model almost any relationship; **the first step in any graph problem is determining the flavor** you have, because flavor selects both data structure and algorithm:

| Question | Distinction | Why it matters |
|---|---|---|
| Are edges one-way? | directed vs undirected | different traversal/component semantics |
| Do edges carry costs? | weighted vs unweighted | unweighted shortest path = BFS; weighted needs Dijkstra (ch-8) |
| Self-loops/multiedges? | simple vs non-simple | most library code assumes simple |
| m ≈ n or m ≈ n²? | sparse vs dense | adjacency list vs matrix |
| Cycles? | cyclic vs acyclic (tree/DAG) | DAGs: topological sort first, DP becomes available |
| Geometry attached? | embedded vs topological | TSP on points = implicit complete graph |
| Materialized? | explicit vs **implicit** | search spaces and web-scale graphs: build only what you visit |
| Names matter? | labeled vs unlabeled | isomorphism/canonicalization questions |

**Adjacency list vs matrix** (Figure 7.5): matrix wins only edge-existence tests and O(1) edge insert/delete, and (small win) dense-graph memory. Lists win degree queries, memory on sparse graphs (m+n vs n²), traversal (Θ(m+n) vs Θ(n²)), and "most problems". **Adjacency lists are the right data structure for most applications of graphs** — and well-designed graph algorithms sweep edges via BFS/DFS rather than ever asking "is (i,j) an edge?".

**BFS vs DFS — what each gives you**: both visit every vertex/edge and underlie most simple linear-time graph algorithms.
- **BFS** (queue): shortest paths in *unweighted* graphs (tree paths from root are minimum-hop), connected components, **two-coloring/bipartiteness testing**.
- **DFS** (stack/recursion): entry/exit times classify edges into tree and back edges — back edge ⇒ **cycle**; finds **articulation vertices/bridges** (cut points for reliability), **topological sort** of DAGs (DFS exit order reversed), and **strongly connected components** of digraphs. "DFS organizes vertices by entry/exit times — this organization is what gives DFS its real power."
- Backtracking = DFS on an implicit graph (ch-9); use BFS when the answer is shallow, DFS when the space is deep and memory bounded.

**War story (I was a Victim of Moore's Law)**: three lessons — *to make a program faster, just wait* (hardware trickles down); *asymptotics eventually do matter* (future machines run bigger n — when implementation complexity is comparable, take the better asymptotic algorithm); *constant factors matter* (compiled vs interpreted = 10×; a week vs a day). **War story (Getting the Graph)**: even *initializing* the graph was the bottleneck — an O(n²) all-pairs comparison replaced by per-vertex incidence lists. Programs on large data must be linear or near-linear; once you demand that, an appropriate method usually exists.

## ch-8 — Weighted Graph Algorithms {#ch-8}

- **Minimum spanning tree** (Prim's for dense, Kruskal's with union–find for sparse): cheapest connecting subgraph. Also the basis of **clustering** — delete the k−1 longest MST edges to get k clusters. Maximum spanning tree = negate weights and run MST.
- **Shortest path**: **Dijkstra** for single-source with non-negative weights (Prim with total-distance keys); **Bellman–Ford** when negative edges exist; **Floyd–Warshall** (three tight loops on adjacency matrix) for all-pairs on graphs small enough for n³; plain **BFS** if unweighted. Unweighted-BFS vs weighted-Dijkstra is the most common selection error.
- **Network flow / bipartite matching**: max flow from s to t equals min s–t cut, so flow algorithms solve edge/vertex connectivity and a huge family of allocation problems. Bipartite matching (workers↔tasks, names↔slots) reduces to unit-capacity flow. Recognizing "this is a flow problem" takes practice — check the catalog before inventing.

### Design graphs, not algorithms (§8.7 — the modeling drills)

"Designing novel graph algorithms is very hard, so don't do it. Instead, design graphs that let classical algorithms solve your problem." Most applications reduce to standard graph properties. Worked recognitions:

| Messy problem | Graph you should build | Classical problem it becomes |
|---|---|---|
| Natural routes for game characters in a room | grid of legal standing points, edges between near points, distance weights | shortest path |
| Order DNA fragments given left-of/right-of constraints | vertex per fragment, directed edge per constraint | topological sort |
| Fewest buckets of mutually non-overlapping rectangles | vertex per rectangle, edge = overlap | vertex coloring (buckets = independent sets) |
| Shorten filenames without collisions | bipartite graph: names ↔ acceptable abbreviations | bipartite matching |
| Segment text lines in a noisy scanned image | vertex per pixel, edge weights ∝ darkness | shortest path left→right |

**War story (Nothing but Nets)**: circuit-board robot-arm routing — "I smelled TSP the instant they started talking about minimizing robot motion"; MST for clustering, and *complicated physics (acceleration) went into the distance metric, not the algorithm*. **War story (Dialing for Documents)**: decoding phone-keypad text = **Viterbi algorithm** = shortest path on a DAG of interpretations. "Hunting for a graph formulation to solve your problem is often the right idea."

## ch-9 — Combinatorial Search {#ch-9}

**Backtracking** systematically enumerates a solution space as vectors a = (a₁,…,aₙ) extended one position at a time — a DFS of the implicit tree of partial solutions (DFS, not BFS: space proportional to depth, not exponential width). The reusable skeleton needs five app-specific routines: `is_a_solution`, `construct_candidates`, `process_solution`, `make_move`/`unmake_move`.

**Pruning** — abandon a partial solution the instant it provably cannot extend to a winner:
1. *Feasibility pruning*: only generate candidates legal w.r.t. the partial solution (don't enumerate then filter).
2. *Bound pruning*: keep the best complete solution found; kill any partial solution whose cost already ≥ it (branch and bound).
3. *Symmetry breaking*: fix the first element of a TSP tour; never explore configurations equivalent to explored ones.
Clever pruning beats data-structure and language tuning as a source of search speedups.

**Size limit for exact combinatorial search: roughly 20–100 items** depending on pruning power (take-home lesson). Beyond that, go heuristic (ch-12). Sudoku war-story corollary: within the budget, the *most constrained next choice* ordering plus lookahead pruning makes "hard" instances trivial.

**Best-first search / branch and bound**: explore the most promising partial solution first; **A\***: promise = cost so far + a *lower bound* on the remainder — the tighter the admissible bound, the more you prune. (Dijkstra = A* with zero heuristic.)

## ch-10 — Dynamic Programming {#ch-10}

DP = exhaustive search made efficient by **storing the results of overlapping subproblems**. Start from a correct recurrence; add a table. **Memoization** (explicit caching of recursive calls) gives most of the benefit with less thought — an acceptable first implementation.

**Applicability test 1 — principle of optimality (correctness)**: partial solutions must be optimally extendable *given the state after the partial solution*, not the specifics of how it was reached. If the sequence of past operations (not just their cost/state) constrains future choices, DP recurrences are unsound.

**Applicability test 2 — state-space size (efficiency)**: runtime = (number of distinct states) × (cost to evaluate one state). **Size the state space before committing.** Objects with an inherent **left-to-right order** — characters of a string, elements of a sequence/permutation-prefix, points around a polygon, leaves of a rooted tree — have polynomially many "stopping places", so DP is likely efficient. "Without an inherent left-to-right ordering on the objects, DP is usually doomed to exponential space and time" — the longest-simple-path/TSP state needs the *set* of visited vertices: 2ⁿ states (usable to n ≈ 30, vs n! ≈ 20), no better.

Canonical recurrences to pattern-match: **edit distance** (approximate string matching: match/substitute, insert, delete — O(mn) table; recover the answer by walking parent pointers back); **longest increasing subsequence**; **subset sum / unordered partition** (pseudo-polynomial O(nk) in target k — works when the numbers are small integers, another instance-narrowing trick); **ordered/linear partition** (divide sequence into k contiguous ranges minimizing max range sum); CKY grammar parsing (interval DP).

**War stories**: *Text Compression for Bar Codes* — replacing a decent greedy mode-switching encoder with the DP optimum gained 8% average, never worse: "the global optimum is often noticeably better than the solution found by typical heuristics… it can never hurt." *The Balance of Power* — when the exact state space is too big, **coarsen the state** (bin loads by si/10): approximate DP on a shrunken state space still beats heuristics; "once you can reduce your state space to a small enough size, you can optimize just about anything." *What's Past is Prolog* — the customer's "works very well in practice" tree-partitioning heuristic was measurably beaten by a left-to-right interval DP.

## ch-11 — NP-Completeness {#ch-11}

A **reduction** translates problem A into problem B so answers correspond: fast algorithm for B ⇒ fast algorithm for A; hardness of A ⇒ hardness of B. Reductions run both directions in practice: *to solve* (reduce your problem to a catalog problem) and *to despair correctly* (reduce a known-hard problem to yours).

**Recognizing hardness — the twin-problem trap**: tiny wording changes flip complexity. Shortest path easy / **longest simple path hard**. Eulerian cycle (visit every *edge* once) easy / **Hamiltonian cycle** (every *vertex* once) hard. Minimum spanning tree easy / **Steiner tree** hard. Matching easy / general **independent set** hard. 2-SAT easy / **3-SAT** hard. Fractional knapsack easy / **integer knapsack** hard. When your problem resembles a known-hard catalog entry, check Garey & Johnson (or catalog ch-19) before writing code.

**The four source problems** (suffice to prove hardness of most problems — and to recognize your problem's shape):
- **3-SAT** — the old reliable, when nothing below fits.
- **Integer partition** — hardness that seems to require *large numbers*.
- **Vertex cover** — graph hardness by *selection* (choose the right subset: clique, independent set, chromatic number).
- **Hamiltonian path** — graph hardness by *ordering* (routing, scheduling sequences).

Proof tactics (for when you must): restrict the source problem as much as possible; generalize the target; amplify penalties for deviating; build gadgets that force choices. **When stuck, alternate between seeking an algorithm and seeking a reduction** — often you can't prove hardness because an efficient algorithm exists (DP, matching, or network flow in disguise). This keeps you honest in both directions.

P vs NP: assume P ≠ NP operationally. Verifying a solution being easy (NP) does not make finding one easy.

## ch-12 — Dealing with Hard Problems {#ch-12}

NP-completeness is never the end of the line — you still need a program. Three escapes:
1. **Fast-in-average-case exact algorithms** — backtracking with substantial pruning (ch-9), or DP with a coarsened state space (ch-10). Correct answer, no worst-case guarantee on time.
2. **Heuristics** (simulated annealing, greedy) — fast, no quality guarantee.
3. **Approximation algorithms** — provable bound on solution quality for every instance.

Cheap approximations worth knowing: **vertex cover** — take both endpoints of any maximal matching: ≤ 2× optimal (and the "obvious" greedy highest-degree heuristic is *worse*: Θ(log n) factor); **greedy set cover** — repeatedly take the set covering the most uncovered elements: Θ(ln n) factor; **Euclidean TSP** — Christofides gives 3/2, MST-doubling gives 2×; **maximum k-SAT** — a *random* assignment satisfies 1−(1/2)ᵏ of clauses (87.5% for 3-SAT): when most solutions are near-optimal ("**when average is good enough**"), random + local improvement is a legitimate algorithm. Best practice: *run both the approximation algorithm and a heuristic, take the better answer* — a guarantee plus a chance to do better.

**Heuristic search** — every method needs exactly two components: a concise *solution-candidate representation* and a *cost function*.
- **Random sampling**: right only when acceptable solutions are plentiful or the space has no coherence (no signal that you're getting closer). On coherent spaces like TSP it's terrible (8× optimal after 10⁸ samples).
- **Local search / gradient descent** (e.g. 2-opt vertex/edge swaps): fast, but stops at the first local optimum.
- **Simulated annealing**: local search that accepts *worsening* moves with probability shrinking over time (cooling schedule) — escapes local optima; "the most reliable method to apply in practice" and Skiena's recommended default for heuristic search. Expect to spend more time tuning cost function and cooling schedule than writing the program.
- **Genetic algorithms**: "I have never encountered any problem where genetic algorithms seemed to me the right way to attack it… stick to simulated annealing for your heuristic search voodoo needs."
- **Quantum computing**: cannot solve NP-complete problems in polynomial time (BQP ⊉ NP, as best we believe); it is not your escape hatch.

**War story (Only it is Not a Radio)**: selecting max working assemblies from defective parts — the win came from *shaping the cost function*: partial credit for near-working assemblies, exponentially decaying with defect count, so the search had a gradient to climb; annealing then beat the factory's best manual result. **War story (Annealing Arrays)**: careful state design + cost function tuned with max/min terms; result far better than construction heuristics, but "since simulated annealing is only a heuristic, we really don't know how close to optimal we are."

## ch-13 — How to Design Algorithms {#ch-13}

Proceed by asking questions and *writing down the answers*. The correct answer to "can I do it this way?" is never "no" but "no, because…" — if you can't articulate the because, your conclusion is probably wrong. Keep **strategy** (can I model this as a graph problem?) ahead of **tactics** (adjacency list or matrix?); tactical answers only matter under a working strategy.

**The checklist** (condensed; work it in order, loop when stuck):
1. **Do I really understand the problem?** What exactly is the input? The desired output? Can I solve a small example *by hand*? Do I need the *optimal* answer, or is close-to-best acceptable? **How large is a typical instance — 10, 1,000, 1,000,000 items?** How fast must it run — a second, a minute, a day? How much implementation time do I have — a day, or freedom to experiment? Is this a numerical / graph / geometric / string / set problem — which formulation is easiest?
2. **Can a simple algorithm or heuristic do it?** Will **brute force** over all subsets/arrangements solve it correctly — and is my problem *small enough* (ch-2 table) for that to suffice? Will a repeated simple rule (biggest first, smallest first, random) work — on what inputs does it break (ch-1 counterexample hunt)?
3. **Is my problem in the catalog?** (ch-14–21; browse the pictures, try all keywords.)
4. **Are there special cases I can solve?** Ignoring a parameter, setting it to 0/1, restricting the input class (tree, unit weights, small integers) — and does my *actual* input satisfy the special case? Is my problem a special case of a catalog problem?
5. **Which paradigm fits?** Sortable items → does sorted order help (ch-4)? Splittable → divide and conquer / binary search (ch-5)? Left-to-right order → DP (ch-10)? Repeated search/min/max operations → dictionary/heap (ch-3)? Random sampling / annealing (ch-12)? Formulate as linear/integer program (ch-16.6)? **Does it smell like SAT/TSP/a known NP-complete problem (ch-11)?**
6. **Still stuck?** Ask an expert; else loop to 1 — did any answer change?

## ch-14 — Catalog usage {#ch-14}

The catalog (75 problems) exists so you *identify* your problem rather than invent an algorithm: recall the name → look it up; otherwise leaf through problem shapes below. Each entry answers "what should I do about it?" with a quick-and-dirty option first, stronger options if that fails. The tables below give: the input shape that identifies the problem, and what to reach for. Depth (implementations, variant discussion) is in the book section named in the first column.

## ch-15 — Catalog: Data Structures {#ch-15}

| § | Your problem looks like | It is | Reach for |
|---|---|---|---|
| 15.1 | locate/insert/delete records by key | **dictionary** | hash table by default; balanced BST (red–black/skip list) if you need ordered iteration/successor/range; sorted array if static; unsorted array if n ≲ 100; isolate the implementation behind an interface so you can swap it |
| 15.2 | repeated access to smallest/largest key (event queues, greedy selection) | **priority queue** | binary heap; sorted array if no inserts after build; **bounded-height/bucket PQ** for small-integer keys; van Emde Boas/Fibonacci only at extremes |
| 15.3 | find all occurrences of many query strings in one big string; longest repeated/common substring | **suffix tree/array** | suffix array + LCP (simpler, cache-friendly); suffix tree turns many O(n²) string scans linear |
| 15.4 | represent a graph | **graph data structure** | adjacency list unless dense or edge-existence-query-heavy (→ matrix); see ch-7 table |
| 15.5 | maintain subsets: membership, union/intersection | **set data structure** | bit vector for dense subsets of a small universe; sorted list/dictionary for sparse; keep sets in canonical sorted order to make union/intersection merges linear; **union–find** for partitions under repeated merging (components, Kruskal) |
| 15.6 | fast access to points/objects by position, k dimensions | **kd-tree** family | kd-tree/quadtree/R-tree for k moderate; they die past k ≈ 20 (curse of dimensionality) |

## ch-16 — Catalog: Numerical Problems {#ch-16}

| § | Your problem looks like | It is | Reach for |
|---|---|---|---|
| 16.1 | solve A·x = b | **linear equations** | LAPACK/BLAS-backed library; never hand-roll Gaussian elimination (stability) |
| 16.2 | permute sparse matrix/graph so non-zeros hug the diagonal | **bandwidth reduction** | Cuthill–McKee heuristics; NP-hard exactly |
| 16.3 | many matrix products | **matrix multiplication** | library BLAS; order your chain multiplications (DP); equivalences: transitive closure, parsing |
| 16.4 | is matrix singular? volume/orientation tests | **determinant** | LU decomposition via library; permanent is #P-hard — avoid |
| 16.5 | maximize/minimize f(x₁…xₙ) | **constrained/unconstrained optimization** | gradient descent family if differentiable (the ML workhorse); simulated annealing if noisy/discrete; LP if linear |
| 16.6 | optimize a linear objective under linear inequalities | **linear programming** | a solver's simplex/interior-point (never your own); *the* Swiss-army knife for allocation problems; integer variables → ILP: NP-hard but solvers are strong |
| 16.7 | need random numbers | **random number generation** | library PRNG; never invent one ("random" home-brew generators are anything but); crypto needs a CSPRNG |
| 16.8 | is n prime / factor n | **factoring & primality** | randomized Miller–Rabin for testing (fast); factoring is the hard direction (RSA rests on it) |
| 16.9 | integers beyond 64 bits | **arbitrary-precision arithmetic** | bignum library (GMP, Python ints); Horner's rule for polynomial/hash evaluation |
| 16.10 | best subset of items with sizes/values under a capacity | **knapsack** | DP O(nC) when capacity C is a small integer; greedy by density for fractional; NP-hard in general |
| 16.11 | time-series ↔ frequency domain; convolutions; correlations | **discrete Fourier transform** | FFT via library (FFTW), n log n; see ch-5 convolution recognition |

## ch-17 — Catalog: Combinatorial Problems {#ch-17}

| § | Your problem looks like | It is | Reach for |
|---|---|---|---|
| 17.1 | arrange items in order | **sorting** | library quicksort/mergesort; n ≤ 100 insertion sort; integer/uniform keys → bucket/radix; ≥10⁸ items → external multiway mergesort; long keys → prefix-fingerprint sort |
| 17.2 | where is key q in set S | **searching** | binary search if sorted+static; hash table if not; self-organizing list for skewed access; interpolation search rarely worth it |
| 17.3 | kth smallest / median without full sort | **median & selection** | quickselect (expected linear); sort if you'll query many ranks |
| 17.4 | enumerate/sample orderings | **generating permutations** | ranking/unranking or Heap's algorithm; random = Fisher–Yates; if you're enumerating to *optimize*, see backtracking ch-9 first |
| 17.5 | enumerate/sample selections | **generating subsets** | binary counting / Gray code; random = coin per element |
| 17.6 | enumerate ways to split n | **generating partitions** | integer partitions in reverse-lexicographic order; set partitions via restricted-growth strings |
| 17.7 | test graphs / random graph instances | **generating graphs** | Erdős–Rényi G(n,p); beware: "random" graphs rarely resemble application graphs |
| 17.8 | day-of-week / date arithmetic | **calendrical calculations** | a date library; never write your own calendar math (leap rules will burn you) |
| 17.9 | order tasks under precedence to minimize time/processors | **job scheduling** | DAG + topological sort; critical path = longest path in DAG (easy); most variants with resource limits are NP-hard → catalog 19 heuristics |
| 17.10 | assign booleans to satisfy clause constraints | **satisfiability** | a modern SAT solver (astonishingly strong in practice); 2-SAT is polynomial (strongly connected components); consider encoding *your* constraint problem as SAT |

## ch-18 — Catalog: Graph Problems (Polynomial-Time) {#ch-18}

| § | Your problem looks like | It is | Reach for |
|---|---|---|---|
| 18.1 | which pieces of the graph hang together | **connected components** | BFS/DFS in linear time; union–find if edges arrive online; strongly connected components (directed) via DFS |
| 18.2 | linear order consistent with precedence arrows | **topological sorting** | DFS exit-time order on the DAG; first step of nearly every DAG algorithm; cycles = infeasible constraints (→ 19.11 feedback set) |
| 18.3 | cheapest set of edges connecting everything; clustering | **minimum spanning tree** | Prim (dense) / Kruskal + union–find (sparse); delete k−1 longest MST edges for k clusters; negate weights for maximum ST |
| 18.4 | cheapest route s→t | **shortest path** | BFS if unweighted; Dijkstra if weights ≥ 0; Bellman–Ford if negative edges; Floyd–Warshall for all-pairs (n³, tiny code); DAG → one DP sweep in topological order (Viterbi shape) |
| 18.5 | can I reach y from x, repeatedly | **transitive closure/reduction** | one BFS/DFS per query vertex; precompute closure matrix (Floyd-style) for O(1) queries |
| 18.6 | pair up workers↔jobs (each used once), max pairs / min cost | **matching** | bipartite: reduce to network flow or Hungarian algorithm; general graphs: blossom algorithm (use a library) |
| 18.7 | traverse every *edge* at least once, cheaply (routes, snowplows, menu testing) | **Eulerian cycle / Chinese postman** | Eulerian iff connected & all degrees even (directed: in=out) — then linear-time; otherwise add cheapest duplicate edges via matching |
| 18.8 | how many failures disconnect the network | **edge/vertex connectivity** | articulation points/bridges via DFS (single failure); general k via max-flow between vertex pairs |
| 18.9 | max stuff routable through capacity-limited edges; many allocation problems | **network flow** | max-flow = min-cut; augmenting-path algorithms via library; *recognizing* the flow formulation is the hard part (bipartite-looking assignment/allocation → try flow) |
| 18.10 | draw a graph legibly | **drawing graphs nicely** | inherently ill-defined — use Graphviz/force-directed layout, don't invent; small graphs only |
| 18.11 | draw a tree | **drawing trees** | ranked/layered layout; libraries |
| 18.12 | can it be drawn without edge crossings | **planarity detection** | linear-time planarity testing (library); planar graphs unlock faster algorithms (m ≤ 3n−6) |

## ch-19 — Catalog: Graph Problems (NP-Hard) {#ch-19}

All entries here: verify your instance isn't a polynomial special case (tree, bipartite, planar, small n), then go exact-with-pruning (n small, ch-9), approximation, or annealing (ch-12).

| § | Your problem looks like | It is | Reach for |
|---|---|---|---|
| 19.1 | largest all-mutually-connected group | **clique** | NP-hard; greedy + local search; exact backtracking fine to ~100 vertices; complement of independent set |
| 19.2 | largest mutually *non*-adjacent set (dispersion, non-interference) | **independent set** | NP-hard; complement of clique; polynomial on trees and bipartite graphs |
| 19.3 | smallest vertex set touching every edge (monitoring, covering) | **vertex cover** | NP-hard; **2-approx via maximal matching endpoints**; complement of independent set; special case of set cover |
| 19.4 | cheapest tour visiting all vertices/points | **traveling salesman** | exact: DP 2ⁿ to n≈30, branch-and-bound/solvers (Concorde) to thousands; heuristic: nearest-neighbor start + **2-opt**, or Christofides 3/2 for metric instances; simulated annealing |
| 19.5 | does a visit-each-vertex-once tour exist | **Hamiltonian cycle** | NP-hard (contrast Eulerian = easy); model as TSP with 1/∞ weights; backtracking with pruning for small n |
| 19.6 | split vertices into balanced pieces cutting few edges | **graph partition** | NP-hard; Kernighan–Lin local search, spectral methods, METIS-style multilevel tools |
| 19.7 | fewest "colors"/rounds so adjacent items differ (register allocation, exam slots) | **vertex coloring** | NP-hard; greedy in degree order (uses ≤ Δ+1 colors); backtracking small n; annealing; bipartite/interval special cases are easy |
| 19.8 | schedule pairwise meetings into fewest rounds | **edge coloring** | Vizing: Δ or Δ+1 colors always; near-optimal constructive algorithms exist |
| 19.9 | are two graphs the same up to renaming; find duplicate structures | **graph isomorphism** | not known NP-complete; canonical labeling via **nauty** works fast in practice; *sub*graph isomorphism is NP-complete |
| 19.10 | cheapest tree connecting a required subset, junctions allowed | **Steiner tree** | NP-hard (contrast MST = easy); MST on the required set is a 2-approx; geometric variants have better heuristics |
| 19.11 | fewest edges/vertices to delete to kill all cycles | **feedback edge/vertex set** | NP-hard; for edges: complement of maximum spanning forest / maximum acyclic subgraph (keep forward edges of any vertex order that keeps ≥ half); enables DAG algorithms afterwards |

## ch-20 — Catalog: Computational Geometry {#ch-20}

| § | Your problem looks like | It is | Reach for |
|---|---|---|---|
| 20.1 | does point sit left/right/on line; do segments cross | **robust geometric primitives** | CCW/orientation predicates with exact or careful arithmetic; degenerate cases (parallel, collinear, shared endpoints) are where geometry code dies — use a library (CGAL) |
| 20.2 | shape/extent of a point set; outer boundary | **convex hull** | Graham scan / gift wrapping, O(n log n); "the sorting of computational geometry" — a preprocessing step for diameter, width, etc. |
| 20.3 | break region/point set into triangles (graphics, FEM, interpolation) | **triangulation** | Delaunay triangulation (avoids skinny triangles); ear-clipping for simple polygons |
| 20.4 | which site is each location closest to (influence regions) | **Voronoi diagram** | Fortune's sweepline via library; dual of Delaunay; answers nearest-neighbor regions, largest empty circle |
| 20.5 | closest point of S to query q | **nearest-neighbor search** | kd-tree for low dims; Voronoi + point location for repeated planar queries; brute force is fine for small n or high dims; approximate NN for large high-dim data |
| 20.6 | all points inside a query box/region (DB/GIS queries) | **range search** | kd-tree / range tree; sorted arrays + binary search per dimension for static 1–2D |
| 20.7 | which region of a planar map contains q | **point location** | trapezoidal decomposition / slab method via library; grid bucketing is the quick-and-dirty |
| 20.8 | which of n segments/polygons intersect | **intersection detection** | sweep-line (Bentley–Ottmann) instead of all-pairs; bounding-box filter first |
| 20.9 | fit items into fewest fixed-size containers | **bin packing** | NP-hard; **first-fit decreasing** heuristic is the standard answer (≤ 11/9 OPT + small constant) |
| 20.10 | skeleton/centerline of a shape | **medial-axis transform** | grassfire/Voronoi of boundary; thinning for raster shapes |
| 20.11 | cut polygon into convex/simple pieces | **polygon partitioning** | convex partitioning heuristics; preprocessing that simplifies most later geometry |
| 20.12 | reduce vertex count while preserving shape | **simplifying polygons** | Douglas–Peucker style simplification; image cleanup or LOD compression |
| 20.13 | how alike are two shapes (OCR, matching) | **shape similarity** | ill-defined — pick a metric: Hausdorff distance, turning function; no universal algorithm |
| 20.14 | route an object through obstacles | **motion planning** | fatten obstacles by robot shape (**Minkowski sum**) → shortest path for a point in visibility graph/grid; sampling-based roadmaps (RRT) for high-dof |
| 20.15 | structure formed by n lines | **maintaining arrangements** | incremental arrangement construction; duality point↔line transforms |
| 20.16 | fatten/offset shapes; collision geometry | **Minkowski sum** | convex decomposition then pairwise sums; the tool behind motion-planning fattening |

## ch-21 — Catalog: Set and String Problems {#ch-21}

| § | Your problem looks like | It is | Reach for |
|---|---|---|---|
| 21.1 | fewest subsets whose union covers everything (buying in lots, test selection) | **set cover** | NP-hard; **greedy largest-uncovered-first**: Θ(ln n)-approx and the practical default; ILP solver when instances matter |
| 21.2 | most disjoint subsets / exact cover, no element twice | **set packing** | NP-hard; matching is the polynomial 2-element special case; LP relaxation + rounding, or backtracking (dancing links) for exact cover |
| 21.3 | find pattern p in text t | **string matching** | library find / Boyer–Moore / Rabin–Karp rolling hash; *many* patterns at once → Aho–Corasick; many queries on one fixed text → suffix array (15.3) |
| 21.4 | closest match allowing typos/mutations | **approximate string matching** | edit-distance DP O(mn) (ch-10); bit-parallel or BLAST-style filtering for scale; Soundex/canonicalization when classes of variants should collide |
| 21.5 | make text smaller | **text compression** | gzip/zstd (LZ family) — do not roll your own; Huffman only as a component; compression ratio ≈ entropy estimate |
| 21.6 | keep messages secret / verify integrity | **cryptography** | vetted library implementations of AES/RSA/SHA — *never* design or implement your own cipher or protocol |
| 21.7 | smallest automaton/regex machine with identical behavior | **finite state machine minimization** | Hopcroft's DFA minimization; NFA→DFA subset construction (may blow up exponentially) |
| 21.8 | longest string common to several strings | **longest common substring/subsequence** | substring: suffix tree, linear; subsequence: DP O(mn) (diff/patch is LCS); LCS of two permutations = LIS |
| 21.9 | shortest string containing all given strings (assembly, slot wheels) | **shortest common superstring** | NP-hard; greedy merge of max-overlap pairs (conjectured 2-approx, works well); overlap computation via suffix structures |

---

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| A greedy/"obvious" procedure is presented as the solution to an optimization problem | Label it heuristic until proven; hunt counterexamples (small, tied, extreme instances) before shipping | Reasonable-looking algorithms are easily incorrect; one counterexample settles it | ch-1 |
| Problem statement uses domain nouns, no standard structure named | Restate as permutation/subset/tree/graph/point/polygon/string before designing | Modeling in standard structures is the single most important step; it unlocks the catalog | ch-1 |
| "Best X" requested without a metric | Refuse to design until the objective is defined | Ill-defined questions produce unjudgeable answers | ch-1 |
| About to choose between algorithm work and bigger hardware | Estimate n and consult the thresholds table first; algorithmic gains dominate at scale | 30,000× algorithmic vs ≤100× hardware speedup in the pyramids war story | ch-2 |
| Considering exhaustive search | Budget it: n! dead at 20; 2ⁿ dead past 40; n² hopeless past 10⁶; n log n fine to 10⁹ | Brute force is *correct and preferred* under these thresholds, futile above them | ch-2 |
| Loop repeatedly halves/doubles a quantity | Expect O(log n); conversely, to get log n, arrange halving (binary search, balanced trees, heaps) | Logarithms arise whenever things are repeatedly halved | ch-2 |
| Repeated linear scans for membership/min/max inside a loop | Introduce a dictionary (hash) or priority queue (heap) | Building algorithms around dictionaries/PQs gives clean structure and performance | ch-3 |
| Choosing a container by micro-benchmarks | Match the *operation set* first: order needed → BST/sorted array; membership only → hash; repeated min → heap; n ≲ 100 → plain array | The fastest structure for A+B is not the fastest for A or B alone; wrong DS is disastrous, best-vs-good is not | ch-3, ch-15 |
| Comparing/deduplicating large objects (documents, files, records) | Hash to fingerprints; compare only on collision; canonicalize first if variants should match | Duplicate detection, canonicalization, and compaction are the three hashing patterns | ch-3 |
| Any "find pairs/duplicates/closest/mode/median" task solved with nested loops | Sort first (or hash if order is irrelevant), then linear scan | "When in doubt, sort" — n log n replaces n² for the whole problem family | ch-4 |
| Custom sort implementation in a diff | Use the library sort with a comparison function; add initial position as secondary key if stability needed | Library sorts are tuned; stability is not guaranteed by fast sorts | ch-4 |
| All-pairs products/shifts/sums of two sequences (n² loop over offsets) | Recognize convolution → FFT, Θ(n log n) | "The first step is to recognize your problem is a convolution" | ch-5 |
| Membership test where false positives are tolerable and memory is tight | Bloom filter | Fraction of exact-set memory for a tunable error rate | ch-6 |
| Claiming safety because random tests found no counterexample | Compute the per-trial probability a random counterexample would appear | Rare-by-chance counterexamples make clean test runs weak evidence | ch-6 |
| Entities with pairwise relationships (links, dependencies, conflicts, adjacency) | It's a graph problem — classify flavor (directed? weighted? DAG? sparse? implicit?) and check catalog ch-18/19 before coding | Most applications reduce to standard graph properties with known algorithms | ch-7, ch-8 |
| Graph stored as n×n matrix, or edge-existence queries in inner loops | Use adjacency lists and restructure to sweep edges via BFS/DFS | Lists win traversal Θ(m+n) vs Θ(n²) and memory on sparse graphs | ch-7 |
| Shortest-path code on an unweighted graph uses Dijkstra (or weighted uses BFS) | Unweighted → BFS; weights ≥ 0 → Dijkstra; negative → Bellman–Ford; all-pairs small n → Floyd–Warshall; DAG → topological DP | Each upgrade costs an order of complexity; each downgrade is a correctness bug | ch-7, ch-18 |
| Precedence/ordering constraints among tasks | Build the DAG, topological sort; cycles = infeasible input (or feedback-set removal) | Topological sort is the first step of nearly every DAG algorithm | ch-8, ch-18 |
| Assignment/allocation problem (each X to one Y, capacities, max throughput) | Try bipartite matching / network flow before inventing | Max-flow = min-cut solves a huge family; recognition is the only hard part | ch-8, ch-18 |
| Tempted to design a novel graph algorithm | Don't. Design the *graph* (vertices/edges/weights encoding your constraints) so a classical algorithm applies | Designing novel graph algorithms is very hard and usually unnecessary | ch-8 |
| Exact optimum required, ~20–100 items, no polynomial algorithm known | Backtracking + pruning (feasibility, bounds, symmetry breaking); prune before tuning anything else | Pruning beats data-structure and language optimizations in search | ch-9 |
| Best-first search where partial cost alone ranks candidates | Add an admissible lower bound on remaining cost (A*) | Promise = cost so far + potential remainder; tighter bound = more pruning | ch-9 |
| Recursive solution recomputes identical subcalls | Memoize first (cheap); full DP table if you need the last constant factor | Explicit caching gives most of DP's benefit, usually same asymptotics | ch-10 |
| Considering DP | Two gates *before coding*: (1) principle of optimality — state, not history, determines extensions; (2) count states × cost/state — need left-to-right order for polynomial states | Without inherent ordering DP is doomed to exponential space/time (TSP: 2ⁿ best case) | ch-10 |
| Team relies on a "works well in practice" heuristic where a DP optimum is feasible | Compute the optimum; expect a modest-but-real gain (≈8% in the bar-code story), never worse | Global optimum ≥ heuristic by definition; often noticeably better | ch-10 |
| DP state space slightly too large | Coarsen the state (bin values) for a near-optimal answer before abandoning DP | "Once the state space is small enough you can optimize just about anything" | ch-10 |
| Your problem resembles longest path / Hamiltonian / 3-SAT / partition / vertex-cover shapes | Suspect NP-hardness; check the catalog & Garey–Johnson before promising an exact fast solution | Twin problems (shortest/longest, Euler/Hamilton) differ by one word and a complexity class | ch-11 |
| Stuck proving hardness / stuck finding an algorithm | Alternate: attempt the other one | Failure to prove hardness often means a polynomial algorithm (DP, matching, flow) exists | ch-11 |
| Problem confirmed NP-hard | Pick an escape deliberately: pruned exact search (small n) / approximation with guarantee / simulated annealing — and consider running approximation + heuristic, keeping the better | NP-hardness is never the end of the line; the application remains | ch-12 |
| Reaching for a heuristic search method | Define representation + cost function; default to simulated annealing; shape the cost function to give partial credit (a gradient), exponential penalties for violations | Annealing is the most reliable method in practice; cost-function design is where the wins are | ch-12 |
| Genetic algorithm proposed | Use simulated annealing instead | Skiena: never saw a problem where GAs were the right attack | ch-12 |
| Optimization where random solutions score near-optimal (e.g. max k-SAT) | Random assignment + local improvement is a legitimate baseline with a provable bound | When average is good enough, mindless methods carry guarantees | ch-12 |
| Starting any algorithm design task | Run the ch-13 checklist: understand input/output/size/speed-need → try brute force & simple rules → search the catalog → special cases → paradigms → suspect hardness | Answering "no, because…" in writing exposes glossed-over possibilities | ch-13 |
| About to implement any named problem (sort, LP, SAT, crypto, dates, bignum, geometry primitives) | Use the standard library/solver implementation | Catalog entries exist because tuned, correct implementations already do | ch-14–21 |

## Anti-patterns

- **Heuristic-labeled-algorithm** — a greedy rule shipped as if guaranteed-correct. Cue: optimization code with no proof and no counterexample search; words "should usually work". (ch-1)
- **Wrong-flavor shortest path** — Dijkstra on unweighted graphs, BFS on weighted ones, Dijkstra with negative edges. Cue: any shortest-path call — check the weight model first. (ch-7/18)
- **Adjacency matrix by default** — O(n²) memory/traversal for a sparse graph. Cue: `matrix[n][n]` where m ≪ n². (ch-7)
- **Novel graph algorithm** — inventing traversal logic instead of re-encoding the problem as a classical one. Cue: bespoke "visit" logic with domain-specific rules woven through it. (ch-8)
- **DP without ordering** — a DP whose state must remember *which* elements were used (set-valued state) on unordered objects. Cue: bitmask or visited-set in the memo key with n beyond ~25. (ch-10)
- **Unbudgeted brute force** — enumeration written without consulting the n-thresholds table. Cue: nested loops / recursion over subsets or permutations with no size argument in the plan. (ch-2/9)
- **Enumerate-then-filter search** — generating all configurations and testing at the end instead of pruning partial solutions. Cue: `if is_valid(complete)` as the only constraint check. (ch-9)
- **Genetic-algorithm voodoo** — modeling with crossover/mutation metaphors instead of a direct representation + annealing. (ch-12)
- **Hand-rolled infrastructure** — own sort, own RNG, own crypto, own calendar math, own Gaussian elimination, own epsilon-free geometry predicates. Cue: any of these in a diff where a library exists. (ch-14–21)
- **Sorting-blindness** — solving pair/duplicate/mode/selection problems with nested loops or ad-hoc indexes. Cue: O(n²) scan where "sort then sweep" is one line. (ch-4)

## Applicability & exemptions

- **Small n voids most of this.** Below ~100 items, quadratic algorithms, unsorted arrays, and brute force are all *correct engineering* — simpler and less buggy. Do not fire complexity findings without an instance-size estimate.
- **Worst-case Big Oh is the book's lens.** It can mislead where inputs are benign (simplex, SAT solvers, hashing all excel in practice despite bad worst cases) or where constants/cache dominate (linked structures lose to arrays; compiled vs interpreted = 10×). Constants matter when they take a week to a day.
- **Expected-time analyses assume decent hash functions and real randomness.** Adversarial inputs (or user-controlled keys) can force worst cases — a security-adjacent exemption to "hash is the default dictionary".
- **The 20–100 exact-search limit and n-thresholds assume ~1 ns/op single-threaded.** Massive parallelism or per-op costs (network, disk) shift the boundaries in either direction; external-memory sorting has its own rules.
- **Approximation bounds vs practice:** a 2-approx guarantee may still lose to an unguaranteed heuristic on your instances — run both when it matters; the guarantee is a floor, not a forecast.
- **Domain limits:** the book covers combinatorial algorithms; continuous/numerical optimization, ML training, distributed algorithms, and cryptographic design are pointed at, not taught — defer to specialized sources (↔ ddia for distributed data concerns).
- **"Design graphs, not algorithms" presumes the catalog roughly fits.** Genuinely new problem structure (rare) justifies novel design — after the checklist and catalog have both failed, in writing.
- **Never-roll-your-own has a learning exemption:** implementing quicksort or Dijkstra to learn is fine; shipping it isn't.

## Candidate lexicon rows

| entities with pairwise relationships in the problem statement | **Graph in disguise** — most messy applied problems reduce to a classical graph problem once you design the right vertices/edges; novel graph algorithms are almost never needed | Can I name vertices, edges, and weights such that a catalog problem (path/tree/flow/matching/coloring) states my requirement? | should | plan | src: algorithm-design-manual ch-8 |
| exhaustive enumeration proposed or coded | **Brute-force budget** — n! dies at 20 items, 2ⁿ past 40, n² past 10⁶; below those, brute force is the correct, simplest solution | What is realistic n, and which complexity row does the plan sit in? | should | plan | src: algorithm-design-manual ch-2 |
| nested-loop search for duplicates, closest pair, mode, or rank | **When in doubt, sort** — sorting first turns this whole problem family into a linear scan; it is rarely the bottleneck | Would sort-then-sweep (or a hash table, if order is irrelevant) replace the O(n²) loop? | should | write | src: algorithm-design-manual ch-4 |
| repeated linear scans for membership/min/max inside a loop | **Dictionary/heap reflex** — build algorithms around dictionaries and priority queues; repeated scan-for-min is a heap, repeated scan-for-key is a hash table | Which operations repeat, and which structure serves exactly that operation set? | should | write | src: algorithm-design-manual ch-3 |
| shortest-path call in a diff | **Match algorithm to weight model** — unweighted→BFS, non-negative→Dijkstra, negative→Bellman–Ford, all-pairs small→Floyd–Warshall, DAG→topological DP | What are the edge weights, and can they be negative? | blocker | review | src: algorithm-design-manual ch-18 |
| dynamic-programming solution proposed | **Size the state space first** — DP needs (1) state-not-history extendability and (2) polynomially many states, which requires left-to-right ordered objects; otherwise it's exponential | How many distinct states, and what orders the objects? | should | plan | src: algorithm-design-manual ch-10 |
| optimization problem resembling longest path, TSP, coloring, cover, or partition | **Hardness recognition** — one word separates easy from NP-hard twins (Euler/Hamilton, shortest/longest); check the catalog before promising exact-and-fast | Is this problem (or its complement) a known NP-hard catalog entry, and is my instance a polynomial special case? | should | plan | src: algorithm-design-manual ch-11 |
| problem confirmed NP-hard but the application still needs answers | **Three escapes** — choose deliberately: pruned exact search (≤ ~100 items), approximation with a guarantee, or simulated annealing; run approximation + heuristic and keep the better | Which escape fits the instance size and the cost of suboptimality? | should | plan | src: algorithm-design-manual ch-12 |
| greedy or "obvious" rule shipped as the solution to an optimization problem | **Algorithms vs heuristics** — a procedure without a correctness argument is a heuristic; hunt counterexamples on small, tied, and extreme instances before trusting it | What is the smallest instance that could break this rule? | should | review | src: algorithm-design-manual ch-1 |
| backtracking/search code enumerating complete configurations before checking validity | **Prune partial solutions** — kill a branch the moment it is infeasible or bounded worse than the best-so-far; pruning beats all other search optimizations | Can validity or a cost bound be checked at each extension instead of at the leaves? | should | write | src: algorithm-design-manual ch-9 |
| hand-rolled sort, RNG, date math, linear algebra, crypto, or geometry predicates in a diff | **Catalog before code** — these are solved problems with tuned, correct library implementations; hand-rolling trades correctness for nothing | Which library/solver implements this catalog problem? | should | review | src: algorithm-design-manual ch-14 |
| performance plan proposes bigger hardware for an algorithmic bottleneck | **Algorithm beats iron** — algorithmic improvement delivered 30,000× where the million-dollar machine capped at 100×; at scale the complexity class is the only lever that matters | What complexity class is the current approach, and is a better class available? | judgment | plan | src: algorithm-design-manual ch-2 |
