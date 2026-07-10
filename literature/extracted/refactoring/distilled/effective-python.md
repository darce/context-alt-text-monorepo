# Effective Python (2nd ed.) — distilled

> **Source**: Brett Slatkin, *Effective Python: 90 Specific Ways to Write Better Python*, 2nd ed., Addison-Wesley 2020 · extracted from `../effective-python.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only per-language-mechanism rulebook for Python in this directory: 90 item-level rules keyed to concrete syntax an agent can pattern-match in a diff — mutable default arguments, closure scoping, iterator exhaustion, `try/except/else/finally` block roles, `with`/contextlib discipline, and the full threads-vs-Queue-vs-ThreadPoolExecutor-vs-coroutines-vs-ProcessPoolExecutor decision ladder. Where `using-asyncio-in-python` argues *why* to choose an event loop, this book supplies the *language traps on the way there* and everything outside asyncio: dict/function/class idioms, exception hierarchy design, module-import mechanics, and stdlib data-structure selection (deque/bisect/heapq/Decimal).

## Chapter map

- ch-1 — Pythonic Thinking: version/style baseline; bytes vs str; f-strings; unpacking/enumerate/zip; walrus; loop-`else` ban.
- ch-2 — Lists and Dictionaries: slicing limits; sort `key`; dict-ordering caveat; the missing-key ladder (`get` → `defaultdict` → `__missing__`).
- ch-3 — Functions: raise-don't-return-None; the closure **scoping bug**; `*args` limits; keyword/keyword-only args; the mutable-default-argument trap; `functools.wraps`.
- ch-4 — Comprehensions and Generators: complexity ceiling (two control subexpressions); generators over accumulated lists; iterator-exhaustion defense; `yield from`; `send`/`throw` bans.
- ch-5 — Classes and Interfaces: compose classes when dict nesting deepens; functions as interfaces; `@classmethod` constructors; `super()`; mix-ins; public-over-private; `collections.abc`.
- ch-6 — Metaclasses and Attributes: plain attributes then `@property`; descriptor/`__getattr__` cautions; `__init_subclass__` over metaclasses; class decorators.
- ch-7 — Concurrency and Parallelism: what the GIL allows; fan-out/fan-in; the tool-choice ladder threads→Queue→ThreadPoolExecutor→coroutines→ProcessPoolExecutor; never block the event loop.
- ch-8 — Robustness and Performance: `try/except/else/finally` block roles; contextlib; UTC datetimes; pickle limits; Decimal for money; profile before optimizing; deque/bisect/heapq/memoryview.
- ch-9 — Testing and Debugging: `__repr__` for debugging; TestCase organization; test isolation; `Mock(spec=)`; dependency-injection seams; `breakpoint()`; tracemalloc.
- ch-10 — Collaboration: venvs; docstrings; packages/`__all__`; module-scoped configuration; root-exception hierarchies; breaking circular imports; `warnings` for migration; gradual typing.

## ch-1 — Pythonic Thinking {#ch-1}

Style-tier items (one line each):

| Item | Rule |
|---|---|
| 1 | Target Python 3 only; verify which interpreter the executable on PATH actually is (`python --version`, `sys.version_info`). |
| 2 | Follow PEP 8 always; shared style is a collaboration protocol, not taste. |
| 5 | When a single expression needs repeated reading (nested ternaries, `or`/`and` defaulting tricks like `x or 0`), extract a helper function; `if/else` expressions beat boolean-operator tricks. |
| 6 | Prefer tuple unpacking (`a, b = pair`) over index access (`pair[0]`, `pair[1]`); works in `for` statements too. |
| 7 | Prefer `enumerate(seq)` (optionally `enumerate(seq, 1)`) over `range(len(seq))` + indexing. |
| 8 | `zip` iterates in parallel lazily — but **silently truncates to the shortest input**; use `itertools.zip_longest` when lengths may differ. |

**Item 3 — bytes vs str.** `bytes` holds 8-bit values, `str` holds Unicode code points; they never mix in operators (`+`, `%`, `>` raise; `==` is worse — it silently compares False: `b'foo' == 'foo'` → `False`). Do encoding/decoding at the edges of your program: accept either type at boundaries via small helpers, operate on one type internally:

```python
def to_str(bytes_or_str):
    if isinstance(bytes_or_str, bytes):
        return bytes_or_str.decode('utf-8')
    return bytes_or_str          # str passes through; to_bytes is the mirror
```

File I/O: binary data requires `'rb'`/`'wb'` (writing bytes to a text-mode handle raises `TypeError`); text mode uses the *system default* encoding (`python3 -c 'import locale; print(locale.getpreferredencoding())'` varies by host) — always pass `encoding=` explicitly to `open` when correctness matters.

**Item 4 — f-strings.** C-style `%` formatting has four gotchas: type/order changes break at runtime, readability collapses when values need pre-formatting tweaks, reused values must be repeated in the tuple, and dict-style `%(key)s` forms triple the verbosity. `str.format` fixes little and adds its own repetition. Use f-strings; they admit arbitrary expressions inline, including inside format specifiers:

```python
places = 3
number = 1.23456
print(f'My number is {number:.{places}f}')   # My number is 1.235
```

For debugging output prefer `!r` / `repr` (see Item 75).

**Item 9 — no `else` after loops.** `else` after `for`/`while` runs when the loop did **not** `break` — the opposite of what readers guess (`else` elsewhere means "if the block didn't run"; here it means "if the loop completed"). An empty loop runs the `else`; a `while False` loop runs the `else`. Detection cue: `for ... else:` or `while ... else:` in a diff → rewrite with a helper function returning early, or a result flag.

**Item 10 — walrus operator.** Use `:=` to kill the assign-then-test repetition and to hoist a variable's scope into exactly the expression that needs it:

```python
# before                                  # after
count = fresh_fruit.get('lemon', 0)
if count:                                 if count := fresh_fruit.get('lemon', 0):
    make_lemonade(count)                      make_lemonade(count)
```

It also emulates the missing `do/while` (`while fresh_fruit := pick_fruit():`) and flattens `switch/case` cascades that would otherwise nest ternaries. Parenthesize when used as a subexpression (`if (count := ...) >= 4:`). Scope note: assignment expressions leak into the enclosing scope — deliberate, but keep them in conditions only (Item 29).

## ch-2 — Lists and Dictionaries {#ch-2}

| Item | Rule |
|---|---|
| 11 | Slicing: omit redundant `0`/`len(seq)` bounds; out-of-bounds slice indexes are forgiving (useful for `a[:20]`); assigning to a slice splices in place even with different lengths. |
| 12 | Never combine start, end, **and** stride in one slice — split into two steps or use `itertools.islice`; avoid negative strides. |
| 13 | Prefer catch-all unpacking (`first, *rest = items`, `oldest, second, *others = ages`) over index/slice arithmetic when splitting sequences; starred targets work in any position but always become a `list` (memory risk on huge iterators). |

**Item 14 — sort by complex criteria.** `list.sort()` orders by natural ordering; objects without `__lt__` need `key=` returning a comparable value. Combine criteria by returning a tuple; negate numeric criteria to flip direction:

```python
power_tools.sort(key=lambda x: (x.weight, x.name))       # weight then name
power_tools.sort(key=lambda x: (-x.weight, x.name))      # weight desc, name asc
# non-negatable criteria: exploit stable sort, lowest-rank first
power_tools.sort(key=lambda x: x.name)                   # secondary
power_tools.sort(key=lambda x: x.weight, reverse=True)   # primary last
```

**Item 15 — dict ordering.** Since 3.7 `dict` preserves insertion order (and so do `**kwargs` and class attribute dicts) — before 3.6 iteration order was arbitrary and could differ per run. But duck-typed dict-*like* objects (e.g. a custom `MutableMapping` such as an alphabetized `SortedDict`) need not preserve it, and code like "first key wins" breaks silently on them. If order matters and inputs are duck-typed: don't rely on ordering, or `isinstance`-check for `dict` at runtime, or pin the parameter type with annotations + static analysis.

**Items 16–18 — the missing-key ladder.** Four ways to handle missing dict keys; choose by who owns the dict:

| Situation | Tool |
|---|---|
| Simple defaults, basic value types | `d.get(key, default)` — best general answer |
| Value construction is costly or can raise | `get` + walrus, not `setdefault` (setdefault **evaluates the default eagerly on every call**) |
| You own/create the dict, arbitrary key set | `collections.defaultdict(factory)` — factory takes no args |
| Default value must depend on the key | `dict` subclass with `__missing__(self, key)` |

```python
# get + walrus for the mutate-in-place case:
if (names := votes.get(key)) is None:
    votes[key] = names = []
names.append(who)

# defaultdict when you control the dict:
visits = defaultdict(set); visits[country].add(city)

# __missing__ when the default depends on the key:
class Pictures(dict):
    def __missing__(self, key):
        value = open_picture(key)   # key-aware; runs only on real misses
        self[key] = value
        return value
```

`setdefault` reads wrong (it *gets*), and — the trap — **evaluates its default argument on every call, hit or miss**. Detection cue: `d.setdefault(k, ExpensiveThing())` or `setdefault(k, [])` in a hot path in a diff. `defaultdict`'s own limit: the factory takes no arguments, so key-dependent defaults need `__missing__`.

## ch-3 — Functions {#ch-3}

**Item 19.** Never unpack more than three variables from one return; beyond that return a lightweight class or `namedtuple` — positional unpacking of 4+ values reorders silently under maintenance.

**Item 20 — raise, don't return None.** `None`-for-error is indistinguishable from falsy valid results (`0`, `''`) at call sites using `if not result:`. Raise a documented exception instead; annotate the return type non-`Optional` to make "never returns None" checkable.

**Item 21 — the scoping bug (closures).** Referencing a variable traverses scopes outward (function → enclosing → module → builtins); **assignment always defines a new variable in the current scope**. So a closure that does `found = True` silently shadows instead of mutating the enclosing `found`, and the outer function returns the stale value — sorted output correct, flag wrong:

```python
def sort_priority2(numbers, group):
    found = False
    def helper(x):
        if x in group:
            found = True   # new var in helper's scope — outer found untouched
            return (0, x)
        return (1, x)
    numbers.sort(key=helper)
    return found           # always False
```

Fix ladder: (1) `nonlocal found` for simple short functions only; (2) beyond that, wrap the state in a small class with `__call__` (a **stateful closure class**, Item 38). Avoid `nonlocal`/`global` where definition and assignment sit far apart. Detection cue: closure assigns to a name also assigned in the enclosing function, no `nonlocal`.

**Item 22.** `*args` reduces noise for genuinely optional short lists — but every `*args` call site materializes a tuple (a generator argument gets fully consumed → memory blowup), and adding a new positional parameter in front of `*args` shifts callers silently. Cap use to small, fixed-ish arities.

**Item 23.** Pass optional arguments by keyword, never by position; keyword defaults let you extend functions without migrating callers.

**Item 24 — dynamic/mutable default arguments.** A default value is evaluated **once, at module load**, not per call. Two canonical failures: `when=datetime.now()` (every call logs the same timestamp) and `default={}` (every caller shares one dict — mutations bleed across calls, `foo is bar`). Convention: default to `None`, allocate inside, document the real default in the docstring; with types, `Optional[T] = None`:

```python
def decode(data, default=None):
    """... default: Defaults to an empty dictionary."""
    try:
        return json.loads(data)
    except ValueError:
        if default is None:
            default = {}
        return default
```

Detection cue (blocker-grade): any `def f(..., x={})`, `x=[]`, `x=set()`, or `x=call())` where `call` is non-constant, in a diff.

**Item 25.** Enforce call clarity structurally: parameters after a bare `*` are keyword-only (callers can't pass confusable flags positionally); parameters before `/` (3.8+) are positional-only (callers can't couple to your parameter names, so you can rename them freely); parameters between `/` and `*` may go either way — the default:

```python
def safe_division(numerator, denominator, /,          # positional-only
                  ndigits=10,                          # either
                  *, ignore_overflow=False,            # keyword-only
                  ignore_zero_division=False):
```

Trigger to apply it: a function with two or more same-typed positional arguments (`f(number, divisor)`) or boolean flags — `f(x, y, True, False)` call sites are unreviewable.

**Item 26.** Every decorator you define must apply `functools.wraps` to its wrapper:

```python
def trace(func):
    @wraps(func)                      # without this: func.__name__ becomes 'wrapper',
    def wrapper(*args, **kwargs):     # help() shows the wrapper, pickling breaks,
        ...                           # and introspection tools (debuggers, test
        return func(*args, **kwargs)  # discovery) misbehave
    return wrapper
```

## ch-4 — Comprehensions and Generators {#ch-4}

**Item 27.** Prefer comprehensions to `map`/`filter` — no lambdas, and filtering is built-in. Dict and set comprehensions exist; use them.

**Item 28 — the complexity ceiling.** A comprehension may use at most **two control subexpressions** (two `for`s, or one `for` + one `if`, or two `if`s). Beyond that (e.g. flattening 3 levels, nested conditions) switch to nested `for` statements or a generator function with a helper. Detection cue: count `for` + `if` tokens inside a single comprehension in the diff; ≥3 → rewrite.

**Item 29.** Use a walrus assignment in the comprehension's *condition* to compute a value once and reuse it in the output — repeating the expression (`get_batches(...)` twice) is both slower and a drift bug waiting for the copies to diverge:

```python
# before: expression repeated, can drift        # after: computed once
found = {name: get_batches(stock.get(name, 0), 8)
         for name in order
         if get_batches(stock.get(name, 0), 8)}
found = {name: batches for name in order
         if (batches := get_batches(stock.get(name, 0), 8))}
```

Using `:=` in the output expression instead evaluates without the guard (can raise on missing names) and leaks the loop variable into the enclosing scope — keep it in the condition only.

**Item 30.** When a function builds and returns an accumulated list (`result = []` … `result.append` … `return result`), return a generator instead (`yield` per item): the append/accumulator noise disappears, nothing is materialized, and arbitrarily large inputs stream in constant memory (e.g. yielding word indexes while reading a file line by line). Callers who need a list call `list(gen)`. Contract cost: the result is single-pass (next item) — say so in the docstring.

**Item 31 — iterator exhaustion (defensive iteration).** An iterator yields once; a second pass silently yields nothing — no error, because `for`, `list()`, `sum()` treat `StopIteration` as normal completion. A function that iterates its argument twice (e.g. `sum(numbers)` then a loop) returns `[]`/wrong results when handed a generator. Defenses, in preference order:

1. Accept a **container**, not an iterator, and check: `if iter(numbers) is numbers: raise TypeError('Must supply a container')` — the iterator protocol guarantees `iter(container)` returns a *new* iterator but `iter(iterator)` returns itself. Equivalent: `isinstance(numbers, collections.abc.Iterator)`.
2. Make the input re-iterable by defining a container class whose `__iter__` is a generator (`class ReadVisits: def __iter__(self): ...yield...`) — each `for`/`sum` gets a fresh iterator (re-reads the source each pass).
3. Last resort: `list(it)` copy — O(input) memory, defeats the point of streaming.

Detection cue: function body consumes the same parameter in two separate iterations/aggregations; caller passes a generator or `open()` handle.

**Item 32.** For large inputs, use generator expressions `(f(x) for x in big)` instead of list comprehensions; they compose by feeding one genexp as the `for` source of the next:

```python
it = (len(x) for x in open('my_file.txt'))   # nothing read yet
roots = ((x, x**0.5) for x in it)            # chained; O(1) working memory
print(next(roots))                           # pulls one line through both stages
```

Caveat: composed genexps are also single-pass (Item 31).

**Item 33.** Compose nested generators with `yield from child()` rather than `for x in child(): yield x` — clearer, and measurably faster (the interpreter hoists the loop).

**Items 34–35 — don't steer generators from outside.** Avoid `gen.send(value)` (bidirectional injection): composed with `yield from` it produces surprise `None`s in the output stream; pass an input *iterator* to the generator instead. Avoid `gen.throw(exc)` (re-raise at the last `yield`): it forces nested `try` boilerplate inside the generator; model exceptional state transitions with a container class exposing `__iter__` plus explicit methods. These two items are why `async`/`await` (ch-7) exists as dedicated syntax rather than generator plumbing.

**Item 36.** Reach for `itertools` before hand-rolling iterator logic — three families:

| Family | Functions |
|---|---|
| Linking | `chain`, `repeat`, `cycle`, `tee`, `zip_longest` |
| Filtering | `islice`, `takewhile`, `dropwhile`, `filterfalse` |
| Combining/producing | `accumulate`, `product`, `permutations`, `combinations`(`_with_replacement`) |

## ch-5 — Classes and Interfaces {#ch-5}

**Item 37 — compose classes when bookkeeping nests.** Escalation rule: a dict of simple values is fine; a dict whose *values are dicts* (or long tuples, or 3+-deep nesting) is unreadable — refactor to classes:

```python
# smell:                                   # refactor ladder:
self._grades = {}                          # tuple (2 items max)
self._grades[name][subject].append(        # -> namedtuple/dataclass record
    (score, weight))                       # -> small classes: Subject holds
                                           #    [Grade], Student holds {Subject},
                                           #    Gradebook holds {Student}
```

`namedtuple` limits: no default argument values (past ~2 optional fields use a class/dataclass); fields stay accessible by index and iteration, so external callers couple to positions — move to a real class when usage escapes your control. Detection cue in a diff: `dict[str, dict[str, list[tuple[...]]]]`-shaped annotations or `d[k1][k2].append(...)` chains.

**Item 38.** For simple hooks, pass a plain function (functions are first-class) instead of defining a one-method class — e.g. `defaultdict(log_missing)` where `log_missing` both logs and returns the default. When the hook needs *state*, prefer a small class with `__call__` over a stateful closure — the callable-object form makes the state explicit and the call site unchanged (this is the Item 21 fix generalized):

```python
class CountMissing:
    def __init__(self): self.added = 0
    def __call__(self):
        self.added += 1
        return 0
counter = CountMissing(); result = defaultdict(counter, current)
```

**Item 39.** `__init__` is Python's only constructor; provide alternative constructors as `@classmethod` factories that call `cls(...)`. **Class-method polymorphism** (factories subclasses override) builds families of concrete subclasses generically — e.g. a `create_workers(cls, input_class, config)` on a `GenericWorker` base lets orchestration code construct any worker/input pairing without hard-coding classes.

**Item 40.** Always initialize parents with zero-argument `super().__init__()`; Python's **MRO** (C3 linearization, inspect via `Class.mro()`) fixes both problems of direct calls — `Parent.__init__(self)` under diamond inheritance runs the shared base twice or in surprising order, and constructor-call order following the *call sites* rather than the class statement confuses maintainers.

**Item 41.** Prefer **mix-ins** (method-only classes: no instance attributes, no `__init__`) over multiple inheritance with state. A mix-in like `ToDictMixin` (generic `to_dict` via `hasattr`/`isinstance` dispatch) composes with others (`JsonMixin(ToDictMixin)`) and permits per-class overrides of individual hook methods. If mix-ins can achieve the outcome, don't reach for stateful multiple inheritance at all.

**Item 42.** Private (`__name`) attributes aren't enforced (name mangling is trivially bypassed: `_Class__name`); they mainly bite subclass authors. Default to public-or-`_protected` attributes plus docstring guidance; reserve `__private` for one case only — avoiding attribute-name collisions in classes designed for out-of-your-control subclassing.

**Item 43.** Simple container tweaks: subclass `list`/`dict` directly. Anything richer: inherit from `collections.abc` interfaces (`Sequence`, `MutableMapping`, …) — implement the few abstract methods and the ABC supplies/validates the rest (`index`, `count`, correct `__contains__`), instead of silently missing protocol methods.

## ch-6 — Metaclasses and Attributes {#ch-6}

Guiding rule for the whole chapter (author's framing): follow the **rule of least surprise**; use these powers only to implement well-understood idioms. (Depth intentionally compressed — this stack rarely needs descriptors/metaclasses.)

**Item 44.** Never write Java-style `get_x()`/`set_x()` methods — start with plain public attributes; Python lets you add behavior later without changing call sites (next item). Setter methods also invite abuse (callers chaining mutations inline).

**Item 45.** `@property` upgrades an existing attribute in place — validation on set, derivation on get — while every `obj.attr` call site keeps working:

```python
class Resistor:
    @property
    def ohms(self): return self._ohms
    @ohms.setter
    def ohms(self, ohms):
        if ohms <= 0:
            raise ValueError(f'ohms must be > 0; got {ohms}')
        self._ohms = ohms
```

Setter validation runs even in `__init__` (assignment routes through the property). Contract: getters must be fast, side-effect-free, and never mutate other attributes — I/O, slow computation, or surprising cross-attribute writes belong in named methods. A class sprouting `@property` on most attributes is a smell: refactor the data model instead (and pay the tech debt before piling on more properties).

**Items 46–47 (brief).** Reuse one validation across many attributes with a **descriptor** class (`__get__`/`__set__`); use `__set_name__` (Item 50) so the descriptor stores data in each instance's dict under its own attribute name (no `WeakKeyDictionary`, no leaks). `__getattr__` runs only on *missing* attributes (good for lazy loading); `__getattribute__` runs on **every** access; inside either, reach instance state via `super().__getattribute__` or you recurse infinitely.

**Items 48–49.** Validate subclass definitions (`class Polygon: def __init_subclass__(cls): ... if cls.sides < 3: raise ValueError`) and auto-register subclasses (registry dict for deserialization type maps — registration-at-definition means you can never forget the call) with `__init_subclass__`, not metaclasses. Always call `super().__init_subclass__()` so validation layers and mix-ins compose. Metaclass `__new__` can do the same but is heavyweight, and only one metaclass is allowed per class hierarchy.

**Item 51.** For cross-cutting modification of every method/attribute of a class (tracing, memoizing), prefer a **class decorator** — a function receiving the class and returning a modified one; class decorators stack cleanly where metaclasses conflict.

## ch-7 — Concurrency and Parallelism {#ch-7}

Definitions: **concurrency** = interleaved progress — thousands of paths, *no speedup* for total work; **parallelism** = simultaneous execution — real speedup. The key difference *is* speedup. Python's GIL means threads give concurrency, never CPU parallelism; true parallelism comes from child processes, `ProcessPoolExecutor`, or C extensions.

**Item 52 — subprocess.** Child processes *do* run in true parallel with the interpreter and are the way to drive CLI tools from Python: `subprocess.run(cmd, capture_output=True, check=True)` for simple cases; `Popen` for polling (`proc.poll()`) and UNIX-style pipelines (wire one process's `stdout` to the next's `stdin`). **Always pass `timeout=` to `communicate`** and kill on expiry — otherwise a hung child hangs you:

```python
try:
    proc.communicate(timeout=0.1)
except subprocess.TimeoutExpired:
    proc.terminate(); proc.wait()
```

**Item 53 — threads: blocking I/O yes, parallelism no.** The **GIL** (a mutex protecting CPython internals from preemptive interruption) allows only one thread to execute bytecode at a time: splitting a CPU-bound factorization across threads takes *longer* than serial (contention + scheduling overhead). Threads' legitimate use: the GIL is *released during blocking system calls*, so multiple file/socket/OS waits proceed truly in parallel while Python continues — e.g. five 0.1 s `select` calls complete in ~0.1 s threaded vs 0.5 s serial. ↔ agrees with using-asyncio-in-python ch-2.

**Item 54 — the GIL is not your lock.** The GIL switches threads *between bytecodes*, so a read-modify-write like `counter.count += 1` (three ops: read, add, assign) can interleave with another thread's between its read and write — the book's 5-thread counter loses ~80% of its increments. Any shared mutable state touched by 2+ threads needs `threading.Lock`:

```python
with self.lock:          # Lock as context manager (Item 66)
    self.count += offset
```

Detection cue: `Thread(target=...)` writing to a shared object with no `Lock` in sight — "but Python has the GIL" is precisely the wrong inference.

**Item 55 — pipelines via Queue.** A hand-rolled thread pipeline (deque per stage, workers polling) fails three ways: **busy waiting** (workers spin polling an empty input), **no stop signal** (workers loop forever after input ends), and **memory explosion** (a fast stage piles output in front of a slow one). `queue.Queue` fixes all three: blocking `get` (no polling), `Queue(maxsize=n)` (`put` blocks → back-pressure), `task_done`/`join` (completion without polling); terminate workers with a sentinel object and `close`/iteration idioms. ↔ same bounded-queue/back-pressure rule as using-asyncio-in-python ch-4.

**Item 56 — recognize fan-out/fan-in.** The moment one unit of work needs I/O per element (the book's Game-of-Life `game_logic` doing a socket read per cell), serial execution multiplies latency by N: 45 cells × 100 ms = 4.5 s per generation; 10,000 cells ≈ 15 minutes. Spawning a concurrent line of execution per work item = **fan-out**; waiting for all of them before the next coordinated phase = **fan-in**. Recognizing this shape in a plan *is* the decision point; then pick the tool:

**Items 57–60, 64 — the tool-choice ladder** (each rung fixes the previous rung's failure):

| Tool | Use when | Fails because / limits |
|---|---|---|
| `Thread` per work item (57) | never for fan-out | ~8 MB stack each, startup cost, needs `Lock`s, exceptions vanish into the thread (can't re-raise to starter), unbounded count |
| `Queue` + fixed workers (58) | existing threaded code, modest I/O | major refactor per pipeline stage; hard-caps I/O parallelism at worker count |
| `ThreadPoolExecutor` (59) | threads truly necessary (blocking libs), limited fan-out | easy `submit`/`result` with exception propagation; still capped by `max_workers` chosen up front |
| Coroutines / asyncio (60) | high fan-out I/O — the default answer | coroutine ≈ function call to start, <1 KB each, tens of thousands OK; single-threaded so shared state needs no locks; exceptions propagate normally and pdb works. Requires async-capable I/O libs |
| `ProcessPoolExecutor` (64) | CPU-bound parallel work | data must pickle across process boundary; use the simple executor, avoid raw `multiprocessing` advanced APIs until all else is exhausted |

Fan-out/fan-in in asyncio — the whole pattern is four lines:

```python
async def simulate(grid):
    next_grid = Grid(grid.height, grid.width)
    tasks = [step_cell(y, x, grid.get, next_grid.set)     # fan-out: calling a
             for y in ... for x in ...]                    # coroutine defers it
    await asyncio.gather(*tasks)                           # fan-in
    return next_grid

grid = asyncio.run(simulate(grid))                         # sync/async boundary
```

Calling a coroutine doesn't run it — it returns an awaitable (deferred execution is the fan-out mechanism, exactly as calling a generator function returns without executing). Requirement changes propagate by adding `async`/`await` at call sites rather than restructuring (contrast: adding one I/O point to a Queue pipeline means a new stage). Exceptions raised inside coroutines propagate through `await` normally — no cross-thread re-raise machinery — and pdb steps through them.

**Item 61 — porting threaded I/O to asyncio is mechanical.** `def`→`async def`; blocking I/O calls→`await` on async equivalents; `time.sleep`→`await asyncio.sleep`; producer loops→async generators; `with`→`async with`; helpers exist for the rest (`asyncio.gather`, async comprehensions, `async for`). The hard part is choosing the concurrency structure (Item 56), not the syntax.

**Item 62 — mixed codebases migrate incrementally.** Two directions, both supported:
- **Top-down** (entry points first): coroutine calls remaining sync/blocking code via `await loop.run_in_executor(None, blocking_fn)` (thread pool), then push `async` downward.
- **Bottom-up** (leaves first): threads call new coroutines via `loop.run_until_complete(coro)` or, across thread boundaries, `asyncio.run_coroutine_threadsafe(coro, loop)`.

↔ complements using-asyncio-in-python ch-4 (janus queue bridging is the same seam).

**Item 63 — never block the event loop.** Any syscall in a coroutine — file `open`/`write`/`close`, `time.sleep`, sync socket ops, *even starting a thread* — stalls every other task on the loop. Detect with `asyncio.run(coro(), debug=True)`: it prints the file/line of coroutines that hog the loop (`Executing <Task ...> took 0.503 seconds`). Fix pattern: move the blocking I/O to a dedicated `Thread` owning its own event loop; expose `write`/`stop` as thread-safe coroutines via `asyncio.run_coroutine_threadsafe(coro, self.loop)` + `await asyncio.wrap_future(future)`; give the wrapper `__aenter__`/`__aexit__` so `async with WriteThread(path) as output:` manages its lifecycle without blocking the main loop. ↔ same blocker as using-asyncio-in-python ch-3.

**Item 64 — true parallelism.** When profiling (Item 70) shows a CPU-bound hot spot and algorithmic fixes are exhausted: `concurrent.futures.ProcessPoolExecutor` parallelizes with a one-line change (`executor.map(fn, args)`) — it pickles each argument to a child process, runs on a separate core (own GIL), pickles results back. That serialization overhead means it only pays for **high-leverage** shapes: small data in/out, large computation between. Avoid the advanced `multiprocessing` primitives (shared memory, cross-process locks/queues) until everything else is exhausted; C extensions beat both but cost rewrite risk.

## ch-8 — Robustness and Performance {#ch-8}

**Item 65 — try/except/else/finally block roles.** Each block has one job; using them fully makes exception flow legible:

| Block | Role |
|---|---|
| `try` | only the statements whose exceptions you intend to catch |
| `except` | handle the *expected* failures of the try block |
| `else` | success-path code whose exceptions should **propagate** (visually distinct from handled code); runs only if try didn't raise |
| `finally` | cleanup that must run on every path |

Two placement rules with teeth: (1) `open()` goes **before** the `try` — if opening fails there is nothing to clean up, and `finally: handle.close()` must not run; (2) code shoved inside `try` that shouldn't be handled by the `except` masks bugs — move it to `else`. The `raise NewError(...) from e` idiom in an except block chains causes for diagnosis. Canonical full shape (the book's `divide_json`):

```python
handle = open(path, 'r+')            # OSError here skips everything below
try:
    data = handle.read()             # UnicodeDecodeError propagates
    op = json.loads(data)            # ValueError propagates
    value = op['numerator'] / op['denominator']
except ZeroDivisionError:            # the one expected failure
    return UNDEFINED
else:                                # success path; its OSErrors propagate
    op['result'] = value
    handle.seek(0); handle.write(json.dumps(op))
    return value
finally:
    handle.close()                   # every path
```

Detection cue: a `try` block spanning both the parse and the *use* of the result under one broad `except` — split with `else`.

**Item 66 — with / contextlib.** `with lock:` / `with open(...) as f:` replaces acquire/`try`/`finally`-release boilerplate and makes a missing release impossible. Write your own with `@contextlib.contextmanager` — far lighter than an `__enter__`/`__exit__` class:

```python
@contextmanager
def log_level(level, name):
    logger = logging.getLogger(name)
    old_level = logger.getEffectiveLevel()
    logger.setLevel(level)
    try:
        yield logger        # with-body runs here; body exceptions re-raise
    finally:                # at the yield, so finally restores state always
        logger.setLevel(old_level)

with log_level(logging.DEBUG, 'my-log') as logger:
    logger.debug('visible only inside the block')
```

`yield value` feeds the `as` target — hand the body its context object. Side benefits: the `with` block highlights the critical section, encouraging you to shrink how long the resource stays held, and swapping the context (a different logger name) touches one line. Detection cue: manual `.acquire()`/`.release()`, `.close()`, or save-restore of process-global state (log level, cwd, env var, signal handler) outside a context manager.

**Item 67 — time.** Never use the `time` module for timezone math (`localtime`/`strptime` depend on host TZ and fail across zones). Represent all times in **UTC** internally (`datetime` + `pytz`/zoneinfo); convert to local time only at presentation. Conversion order: local→UTC at intake, arithmetic in UTC, UTC→local last.

**Item 68 — pickle.** `pickle` is only for **trusted** programs (deserializing hostile bytes executes attacker code — it's not a secure format); serialized objects break silently when classes evolve (missing new attributes, renamed classes). If pickle must persist across versions, register defaults/versioning/class-paths via `copyreg`. Between untrusting programs use JSON.

**Item 69 — Decimal.** Money and precision-critical math: IEEE 754 floats approximate (`4.35 * 100` → `434.999...`, and rounding it gives `434.99` — an underbilling bug); use `decimal.Decimal` with explicit rounding policy:

```python
rate = Decimal('1.45')                       # str constructor: exact;
                                             # Decimal(1.45) inherits float error
cost = rate * seconds / Decimal(60)
cost.quantize(Decimal('0.01'), rounding=ROUND_UP)   # explicit policy per domain
```

For effectively-infinite precision with rational numbers, `fractions.Fraction` exists.

**Item 70 — profile before optimizing.** Intuition about Python slowdowns is reliably wrong (the book's example: an insertion sort was dominated not by the algorithm but by a linear-scan `insert_value` helper — obvious only in the profile). Measure with `cProfile` (the pure-Python `profile` module distorts results), isolate the workload via `Profile().runcall(fn)` with a deterministic test case, and read with `pstats.Stats`: `tottime` = time in the function itself, `cumtime` = including callees; `print_callers()` attributes shared-utility cost to its callers. Only then optimize.

**Items 71–74 — stdlib data-structure selection:**

| Symptom in code | Replace with | Why |
|---|---|---|
| `list.pop(0)` consumer / FIFO via list | `collections.deque` (`popleft`) | `pop(0)` is superlinear as the queue grows; deque is O(1) both ends |
| linear `in` / `.index()` over a *sorted* list | `bisect.bisect_left` | log-time search, orders of magnitude faster |
| priority queue via `list.sort()` after every insert | `heapq` (`heappush`/`heappop`) | list approach degrades superlinearly; heap is log-time; items need `__lt__` (or push `(priority, item)` tuples) |
| slicing big `bytes` buffers in I/O loops | `memoryview` + `bytearray` | zero-copy slices/splices via the buffer protocol (e.g. `socket.recv_into`) |

## ch-9 — Testing and Debugging {#ch-9}

(Stack note: the book uses `unittest`; principles map 1:1 to pytest — `setUp`→fixture, `subTest`→`@pytest.mark.parametrize`, `assertEqual`→plain `assert` with pytest introspection. `unittest.mock` is used unchanged under pytest.)

**Item 75 — repr for debugging.** `print(x)` hides types (`5` vs `'5'` print identically). Debug output should use `repr(x)`, f-string `!r`, or `%r`. Give every class you'll ever debug a `__repr__` that shows constructor-like detail (`f'BetterClass({self.x!r}, {self.y!r})'`); otherwise you get `<__main__.OpaqueClass object at 0x...>`.

**Item 76.** One `TestCase` subclass per related-behavior group; one `test_` method per behavior; use assertion helpers (`assertEqual`, `assertRaises` as context manager) over bare `assert` for failure detail; data-driven cases via `subTest` so one failure doesn't stop the table. Write tests for both unit level and integration level — in Python you can't rely on a compiler to catch anything.

**Item 77 — isolation.** Tests must not share state: per-test setup/teardown in `setUp`/`tearDown` (pytest: function fixtures); expensive shared harnesses (DB spin-up) in `setUpModule`/`tearDownModule` (pytest: session/module fixtures).

**Item 78 — mocks.** Use `unittest.mock.Mock(spec=RealClass)` — `spec` makes calls to misspelled/nonexistent methods raise `AttributeError` instead of silently passing, killing the both-test-and-code-share-the-bug failure mode. Verify *both* the return value and the dependency interactions (`assert_called_once_with`, `assert_has_calls`). Inject mocks by parameter (keyword-only args like `utcnow=datetime.utcnow`) when you can; `unittest.mock.patch` when you can't control the call path.

**Item 79 — encapsulate dependencies; DI over module globals.** When tests drown in `patch` boilerplate, restructure the code: gather related helper functions into a class (`ZooDatabase`), pass that object in as a parameter (`do_rounds(database, ...)`) — now tests just build `Mock(spec=ZooDatabase)`, no patching. For end-to-end tests, provide one explicit **seam**: a module-level `get_database()` accessor caching a singleton that `patch` can replace at a single point. Design-for-test is the point: the integration test was "straightforward because I designed the implementation to make it easier to test." Detection cue: function reaches out to a module-level connection/client/config instead of receiving it; test files with 3+ nested `patch` context managers.

**Item 80 — pdb.** Drop `breakpoint()` at the point of interest (no import); post-mortem: `python -m pdb -c continue program.py` or `pdb.pm()` after an exception in the REPL.

**Item 81 — tracemalloc.** For leaks, `gc.get_objects()` shows *what* exists but not where it came from; `tracemalloc.start(frames)` + `take_snapshot()`/`compare_to` attributes allocations to source lines.

## ch-10 — Collaboration {#ch-10}

| Item | Rule |
|---|---|
| 82 | Check PyPI before building; `pip` for install. |
| 83 | Every project gets an isolated venv (`python -m venv`); reproduce with `pip freeze` → `requirements.txt`. Never install into the system interpreter. |
| 84 | Docstrings on every module (what it contains), class (behavior, important attributes, subclassing contract), and function (args, return, raised exceptions, side effects). **Exceptions raised belong in the docstring** — annotations can't express them. Don't duplicate what type annotations already say. |
| 85 | Packages (`__init__.py`) give namespacing; expose a deliberate API by importing public names in `__init__.py` and underscore-prefixing internals; `__all__` matters for released libraries, is noise within one team/codebase. |

**Item 86 — module-scoped configuration.** Module top-level code is real code run at import; use it to select deployment-environment implementations (e.g. `if TESTING: from dev_db import Database else: from prod_db import Database`) — cheaper than mocks everywhere when environments diverge. Caution (pairs with Items 88/79): keep module scope to *selection and constants*; running side-effectful work at import time is exactly what creates circular-import crashes and untestable code — prefer the DI seam of Item 79 when a mock-able object suffices.

**Item 87 — root exception hierarchy.** A module/service API's exceptions are part of its interface. Define `class Error(Exception)` as the module root, all deliberate exceptions inherit from it (optionally via intermediate roots per area: `WeightError(Error)`, …). Callers write three except tiers, each with distinct meaning:

```python
try:
    weight = my_module.determine_weight(0, 1)
except my_module.InvalidDensityError:   # expected, handled
    weight = 0
except my_module.Error:                 # missed deliberate exc → bug in CALLER
    logging.exception('Bug in the calling code')
except Exception:                       # non-hierarchy exc → bug in the API; re-raise
    logging.exception('Bug in the API code!')
    raise
```

Payoffs: callers are insulated from your internals; escaping non-`Error` exceptions self-identify as API bugs; new specific subclasses (`NegativeDensityError(InvalidDensityError)`) never break existing handlers. Detection cue: a library/service module raising bare `ValueError`/`RuntimeError` across its public boundary, or a FastAPI service with no exception taxonomy between domain errors and bugs.

**Item 88 — circular imports.** Import machinery: find → compile → create empty module → **insert into sys.modules** → run body to define attributes. A cycle crashes because module B can import A after step 4 while A's attributes (step 5) don't exist yet → `AttributeError: partially initialized module`. Fix ranking:

1. **Best**: refactor the shared piece (e.g. `prefs`) into a leaf module at the bottom of the dependency tree; both sides import it.
2. **Import-configure-run**: modules only define at import; each exposes `configure()`; main imports everything, then configures everything, then runs. Enables DI; cost is split definition/configuration.
3. **Dynamic import** (`import app` inside the function that needs it): simplest, no restructuring — but import cost in hot paths and failure deferred to runtime (a production `SyntaxError` hours after startup is the book's horror story — cover dynamic imports with tests).
4. **Anti-fix**: reordering imports to the bottom of the module works but is brittle and violates PEP 8 — don't.

**Item 89 — warnings for migration.** Deprecating an API argument/behavior: `warnings.warn('...', DeprecationWarning, stacklevel=2)` (stacklevel points the report at the caller). CI runs `python -W error` so dependency deprecations fail tests instead of surprising production; production maps warnings into `logging` (`logging.captureWarnings(True)`); and unit-test that your warnings fire with the right message.

**Item 90 — gradual typing.** Annotations + external checker (mypy `--strict`, pyright, pytype, pyre — `typing` itself checks nothing). Catches statically: wrong argument types, bytes/str mixing, forgotten `return`, forgotten `self.`, `Optional`/None misuse, generic misuse via `TypeVar`. Adoption best practices (author's list): write code and tests first, annotate where most valuable after; types matter most at **API boundaries** many callers depend on; annotate the most complex/error-prone internals next, but 100% coverage has diminishing returns; run the checker continuously as you annotate (not one big pass at the end); wire the checker into CI with its config committed. Forward references: annotation names are evaluated at runtime — use `from __future__ import annotations` (preferred) or string annotations. Exceptions are **not** part of typed interfaces (unlike Java checked exceptions) — test them (Item 87/76). Skip annotations for throwaway scripts and prototypes.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| `def f(..., x={})` / `=[]` / `=datetime.now()` / any non-literal default | Default to `None`, allocate inside, document real default in docstring | Defaults evaluate once at module load; mutable ones are shared across all calls | ch-3 |
| Closure assigns a name also defined in enclosing function, no `nonlocal` | Assignment creates a new local — use `nonlocal` (short fns) or a `__call__` class | Outer variable silently untouched; flag/result bugs with correct-looking output | ch-3 |
| Function returns `None` to signal failure | Raise a documented exception instead | `None` is indistinguishable from falsy valid results at `if not x:` call sites | ch-3 |
| Function iterates a parameter twice; callers may pass generators | Reject iterators (`iter(x) is x` → `TypeError`) or accept re-iterable containers | Exhausted iterators yield nothing silently — no error raised | ch-4 |
| Comprehension with ≥3 `for`/`if` control subexpressions | Rewrite as nested statements or a generator helper | Beyond two, comprehensions are write-only | ch-4 |
| Function builds+returns an accumulated list | Return a generator (`yield`) | Less noise, streams arbitrarily large inputs | ch-4 |
| `gen.send(...)` or `gen.throw(...)` in a diff | Pass an input iterator / use a state-class with `__iter__` instead | send yields surprise Nones under composition; throw forces nested boilerplate | ch-4 |
| `zip()` over sequences whose lengths may differ | Use `itertools.zip_longest` or assert equal lengths | zip truncates to the shortest input silently | ch-1 |
| `for`/`while` with an `else` block | Rewrite with early-return helper | else-after-loop means "no break" — readers guess wrong | ch-1 |
| `open()` without `encoding=`, or bytes/str mixed in one expression | Pass `encoding` explicitly; convert at boundaries with helpers | System default encoding varies by host; bytes/str never interoperate | ch-1 |
| `d.setdefault(k, expensive())` | `get`+walrus, `defaultdict`, or `__missing__` | setdefault evaluates the default on every call, hit or miss | ch-2 |
| Unpacking 4+ return values | Return a small class / namedtuple | Positional reordering bugs under maintenance | ch-3 |
| Multiple same-typed positional params in a public function | Add `*` (keyword-only) and consider `/` (positional-only) | Structural enforcement beats convention | ch-3 |
| Hand-written decorator without `functools.wraps` | Add `@wraps(func)` | Breaks introspection, docstrings, pickling, debuggers | ch-3 |
| Dict values that are dicts / 3-deep nesting / long tuples | Refactor to namedtuple/dataclass → small classes | Bookkeeping code becomes unmaintainable past one nesting level | ch-5 |
| Multiple inheritance with stateful `__init__`s | Use zero-arg `super().__init__()`; prefer stateless mix-ins | MRO handles diamonds; manual parent calls double-run | ch-5 |
| `__private` attributes in a class others subclass | Use public/`_protected` + docs | Name mangling isn't access control; it breaks subclasses | ch-5 |
| Metaclass written for validation/registration | `__init_subclass__` (+ `super().__init_subclass__()`) | Same power, composable, comprehensible | ch-6 |
| Slow work or side effects inside `@property` | Move to a normal method | Attribute access must look cheap because it reads as cheap | ch-6 |
| `subprocess` … `communicate()` without `timeout=` | Add timeout | Hung child hangs the parent | ch-7 |
| Threads spawned for CPU-bound speedup | Use `ProcessPoolExecutor` | GIL: threads never run bytecode in parallel | ch-7 |
| 2+ threads writing shared structure, no `Lock` | `with threading.Lock():` around read-modify-write | GIL switches between bytecodes; `+=` is three ops | ch-7 |
| `Thread()` per work item in a fan-out loop | ThreadPoolExecutor (few, blocking libs) or coroutines (many) | Per-thread memory/startup cost, lost exceptions, unbounded count | ch-7 |
| New high-fan-out I/O code | Default to asyncio coroutines; `await asyncio.gather(*tasks)` for fan-in | <1 KB per coroutine, no locks, exceptions propagate, debuggable | ch-7 |
| Blocking syscall (`time.sleep`, sync file/socket I/O) inside `async def` | Move to executor/dedicated thread; verify with `asyncio.run(debug=True)` | One blocking call stalls every task on the loop | ch-7 |
| try block containing both risky call and success-path code | Move success path to `else` | else visually separates handled failures from propagating ones | ch-8 |
| `open()` inside the `try` of a try/finally-close | Open before try | Open-failure must skip cleanup | ch-8 |
| Manual acquire/release, close, or save-restore of global state | `with` statement; `@contextmanager` (yield inside try/finally) for custom | Guaranteed cleanup, impossible to forget release | ch-8 |
| `time` module used for timezone conversion; local times stored | UTC internally, convert at presentation; datetime+zoneinfo | Host-TZ-dependent behavior | ch-8 |
| `pickle` on data crossing a trust boundary | JSON (or validated format) | Unpickling executes arbitrary code | ch-8 |
| float arithmetic on money | `Decimal(str_value)` + explicit `quantize` rounding | IEEE 754 approximation errors accumulate | ch-8 |
| `list.pop(0)`, sorted-list linear search, sort-per-insert priority queue | deque / bisect / heapq | Superlinear degradation as N grows | ch-8 |
| Optimization PR with no profile attached | Profile first (`cProfile`, `runcall`) | Slowdown sources are reliably non-obvious | ch-8 |
| Debug/log output via `print(x)`/`{x}` on ambiguous types | `repr`/`!r`; define `__repr__` on your classes | str-forms hide type information | ch-9 |
| `Mock()` without `spec=` | `Mock(spec=RealClass)` | Misspelled method calls pass silently otherwise | ch-9 |
| 3+ nested `patch` blocks per test; functions reading module-global clients | Encapsulate deps in a class, pass as parameter; one `get_X()` seam for e2e | DI makes tests one `Mock(spec=)`; patching couples tests to internals | ch-9 |
| Library/service raising bare `ValueError` across its public boundary | Module root `Error(Exception)` + hierarchy; callers catch tiered | Insulates callers; escaping exceptions self-identify as API bugs | ch-10 |
| `AttributeError: partially initialized module` at startup | Refactor shared state to a leaf module; else configure-phase; else dynamic import | Cycle hits empty module object between sys.modules insert and body exec | ch-10 |
| Removing/changing a public API argument | `warnings.warn(DeprecationWarning, stacklevel=2)`; CI `-W error` | Callers migrate before the break lands | ch-10 |
| New/changed public API boundary without annotations | Annotate boundary types; run mypy/pyright in CI | Boundaries are where type bugs cross team lines | ch-10 |

## Anti-patterns

- **Mutable default argument** — `def f(x=[])` / `={}`; shared across every call. Cue: non-literal or mutable default in a `def`.
- **The scoping bug** — closure assignment expecting to mutate enclosing scope. Cue: same name assigned in both closure and enclosing function.
- **Silent zip truncation** — `zip` over unequal-length inputs drops the tail. Cue: zipped lists built by separate code paths.
- **Loop `else`** — runs on no-break; universally misread.
- **setdefault-with-constructor** — default value constructed on every access.
- **Iterator double-consumption** — `sum(it)` then `for x in it`. Cue: parameter iterated twice; generator passed in.
- **Generator steering** — `send`/`throw` to inject data/exceptions into generators.
- **Java-style getters/setters** — `get_x()`/`set_x()` methods in Python; plain attributes + `@property` later.
- **Private-attribute lockout** — `__name` used as access control.
- **Metaclass where `__init_subclass__` suffices.**
- **Thread-per-task fan-out** — unbounded `Thread(target=...)` in a loop.
- **CPU parallelism via threads** — GIL makes it slower, not faster.
- **Blocking the event loop** — sync I/O inside `async def`.
- **try-block sprawl** — success-path code inside `try` where the `except` can mask its bugs; belongs in `else`.
- **C-style `%` formatting / `str.format`** — use f-strings.
- **`time` module timezone math; local-time storage.**
- **Float money.**
- **`list` as FIFO / priority queue** — `pop(0)` and sort-per-insert are superlinear.
- **Pickle across trust boundaries.**
- **Bottom-of-file import reordering** to dodge a circular import — brittle; use leaf-module refactor, configure phase, or dynamic import.
- **Import-time side effects** — module top-level running real work; crashes as circular imports, blocks testability.
- **Patch-tower tests** — stacks of `unittest.mock.patch` compensating for globals instead of injected dependencies.

## Applicability & exemptions

- **Python 3.7–3.8 vintage.** Written against 3.8: `pytz` → stdlib `zoneinfo` (3.9+); `Optional[X]` → `X | None` (3.10+); `from __future__ import annotations` semantics settled differently than predicted ("Python 4" never came); `asyncio.get_event_loop` patterns → `asyncio.run`/`get_running_loop`. The *rules* stand; update the spellings.
- **Style-tier items (1, 2, 5–8, 11, 27, 82–85) are `judgment`, not blockers** — don't fail reviews over enumerate-vs-range in someone else's diff; do write new code with them.
- **Item 15 (dict ordering)**: relying on insertion order **is** correct for real `dict` on 3.7+; the caveat only fires for duck-typed dict-likes.
- **Item 20 (raise over None)**: returning `None` is fine when None is a *domain value* (e.g. "not found" for an optional lookup) and the signature says `Optional[T]`; the rule targets None-as-error-code.
- **Item 31 defense (`TypeError` on iterators)** applies to functions that *must* multi-pass; single-pass functions should keep accepting iterators — don't over-fire.
- **Item 42 (public attributes)**: private `__attrs` remain legitimate to dodge name collisions in widely-subclassed base classes.
- **Item 64**: `ProcessPoolExecutor` only pays when work units are CPU-heavy and their inputs/outputs pickle cheaply; per-item overhead dwarfs small tasks.
- **Item 86 vs 79 tension** (author holds both): module-scoped environment selection is sanctioned; module-scoped *stateful work* is what breaks Items 88/79. Selection and constants yes; connections and computation no.
- **Item 90**: type annotations explicitly *not* worth it for small scripts, prototypes, ad-hoc code; don't demand annotations on throwaway work. Annotate boundaries first, not everything.
- **unittest vs pytest**: Items 76–78 mechanics are unittest-specific; in this stack apply the principles through pytest fixtures/parametrize — the isolation, spec-mock, and DI rules are framework-independent.
- The concurrency ladder (Items 57–60) presumes **I/O-bound fan-out**; for a handful of concurrent blocking calls, `ThreadPoolExecutor` is simpler than adopting asyncio, and the book endorses it when threads are genuinely necessary.

## Candidate lexicon rows

| py: `def` with mutable or call-expression default (`={}`, `=[]`, `=now()`) | **None-default convention** — defaults evaluate once at module load, so mutable/dynamic defaults are shared across all calls | Is every default either an immutable literal or `None`-with-inside-allocation? | blocker | review | src: effective-python ch-3 |
| py: closure assigns a name also defined in its enclosing function without `nonlocal` | **Scoping bug** — assignment defines a new local in the closure; the enclosing variable stays stale while output looks right | Does this inner-function assignment intend to mutate outer state, and if so where is `nonlocal` or the `__call__` class? | blocker | review | src: effective-python ch-3 |
| py: function iterates the same parameter twice (e.g. `sum(x)` then `for v in x`) | **Iterator exhaustion defense** — a passed-in generator yields nothing on the second pass, silently; reject iterators (`iter(x) is x`) or require containers | Can a caller pass a generator here, and what does pass two see if they do? | blocker | review | src: effective-python ch-4 |
| py: comprehension containing three or more `for`/`if` subexpressions | **Two-control-subexpression ceiling** — beyond two, comprehensions are write-only; use nested statements or a generator helper | Would a newcomer parse this comprehension in one read? | should | write | src: effective-python ch-4 |
| py: success-path statements inside a `try` block alongside the risky call | **Give else its job** — code in `try` gets its bugs masked by the `except`; success-path work belongs in `else`, cleanup in `finally`, resource-open before `try` | Which exact statement is this except clause meant to guard? | should | review | src: effective-python ch-8 |
| py: manual `.acquire()`/`.close()` or save-restore of global state (log level, cwd, env) | **Context-manage every resource** — `with`/`@contextmanager` (yield inside try/finally) makes release unforgettable on every exit path | What runs if the body raises between setup and teardown? | should | review | src: effective-python ch-8 |
| py: plan adds threads for CPU-bound speedup, or `Thread(target=...)` per item in a fan-out loop | **Concurrency ladder** — GIL: threads only overlap blocking I/O; fan-out belongs to ThreadPoolExecutor (few/blocking-lib) or coroutines (many); CPU work to ProcessPoolExecutor | Is each unit of work I/O-bound or CPU-bound, and how many run at once? | should | plan | src: effective-python ch-7 |
| py: 2+ threads read-modify-write shared state with no `Lock` | **The GIL is not your lock** — interpreter switches between bytecodes, so `x += 1` interleaves and corrupts | Which lock serializes every mutation of this shared object? | blocker | review | src: effective-python ch-7 |
| py: service/library module raising bare `ValueError`/`RuntimeError` across its public boundary | **Root exception hierarchy** — module `Error(Exception)` root insulates callers, self-identifies API bugs (escaping non-`Error`), and future-proofs new subtypes | Can a caller catch everything this module deliberately raises with one except clause? | should | plan | src: effective-python ch-10 |
| py: test file stacking `patch()` contexts, or code reading module-global clients/connections | **Encapsulate and inject dependencies** — wrap dependency functions in a class, pass it as a parameter (`Mock(spec=...)` in tests); keep at most one `get_X()` seam for e2e patching | Could this test inject a fake by argument instead of patching module internals? | should | review | src: effective-python ch-9 |
| py: `Mock()` created without `spec=` | **Spec your mocks** — spec-less mocks accept misspelled methods, letting the same bug live in code and test | Would calling a nonexistent method on this mock fail the test? | should | write | src: effective-python ch-9 |
| py: `zip()` over independently built sequences | **zip truncates silently** — unequal lengths drop the tail with no error; use `zip_longest` or assert lengths | What guarantees these iterables are the same length? | should | review | src: effective-python ch-1 |

