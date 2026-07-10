# Operating Systems: Three Easy Pieces — distilled

> **Source**: Remzi H. Arpaci-Dusseau & Andrea C. Arpaci-Dusseau, *Operating Systems: Three Easy Pieces*, v1.10, 2008–2023 (ostep.org) · extracted from `../os-three-easy-pieces.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The ground-truth source for **general shared-memory concurrency correctness** — preemptive threads, locks, condition variables, semaphores — where `using-asyncio-in-python` covers only the cooperative single-thread model. Uniquely provides: the empirically-grounded taxonomy of concurrency bugs (Lu et al.: 97% of non-deadlock bugs are **atomicity violations** or **order violations** — two patterns an agent can grep for), the four deadlock conditions as a break-one-and-you-win table, the complete condition-variable discipline (while-not-if, state variable + lock + CV trio, Mesa semantics), the spin-vs-block decision, and the crash-consistency rules any program writing durable files must obey (`fsync` semantics, directory fsync, atomic `rename`, write-pointed-to-before-pointer). Also the memory-error catalog (leak, dangling pointer, double free, uninitialized read) and scheduling/paging vocabulary (convoy effect, thrashing, admission control) that other sources use without defining.

## Chapter map

- ch-7 — Scheduling: Introduction: turnaround vs response time; FIFO/SJF/STCF/RR; the convoy effect; overlap I/O with compute.
- ch-8 — Multi-Level Feedback Queue: how real schedulers infer job type from behavior; the 5 MLFQ rules.
- ch-14 — Interlude: Memory API: the six canonical malloc/free errors and which tools find them; when leaks matter.
- ch-22 — Beyond Physical Memory (Policies): demand paging, dirty-page cost, thrashing, admission control, OOM killer.
- ch-26 — Concurrency Introduction: race condition / critical section / mutual exclusion / indeterminate — the four core terms; why `x = x + 1` is three instructions.
- ch-27 — Interlude: Thread API: thread lifecycle rules; never return stack pointers; never synchronize with ad-hoc flags; check return codes.
- ch-28 — Locks: correctness/fairness/performance axes; spin vs block; priority inversion; two-phase locks; the wakeup/waiting race.
- ch-29 — Lock-based Concurrent Data Structures: big-lock-first; locks vs control flow; when fine-grained locking pays (and when it doesn't).
- ch-30 — Condition Variables: the full CV discipline; Mesa vs Hoare semantics; producer/consumer; covering conditions and broadcast.
- ch-31 — Semaphores: initialization rule; ordering vs mutual exclusion; lock-scope deadlock; reader-writer caution; dining philosophers; throttling.
- ch-32 — Common Concurrency Problems: atomicity violation, order violation, the 4 deadlock conditions and how to break each, livelock, detect-and-recover.
- ch-33 — Event-based Concurrency: the no-blocking rule; manual stack management (continuations); why multicore ends the no-locks free lunch.
- ch-39 — Files and Directories (durability subset): what `write()` actually promises; `fsync` file *and* directory; atomic `rename`; the write-temp-fsync-rename pattern.
- ch-42 — Crash Consistency (FSCK and Journaling): the crash-consistency problem; journaling protocol and its ordering rules; metadata vs data journaling; write-pointed-to-before-pointer.

## ch-7 — Scheduling: Introduction {#ch-7}

Two metrics, inherently in tension:

- **Turnaround time** = T_completion − T_arrival (batch/throughput metric).
- **Response time** = T_firstrun − T_arrival (interactivity metric).

| Policy | Optimizes | Fails at | Failure name |
|---|---|---|---|
| FIFO | simplicity | turnaround when job lengths vary | **convoy effect** — short consumers queue behind one heavyweight |
| SJF (shortest job first) | turnaround (optimal if all arrive together) | late-arriving short jobs; non-preemptive | convoy again |
| STCF (preemptive SJF) | turnaround with arrivals | response time — last job waits for all others | |
| Round-robin (time slicing) | response time | turnaround — "nearly pessimal", stretches every job | |

Rule: **any policy that is fair on a small time scale performs poorly on turnaround; any policy that runs short jobs to completion hurts response time.** Pick by which metric the workload actually needs.

Time-slice length is an **amortization** trade: slice must be long enough that context-switch cost (register save/restore *plus* cache/TLB/branch-predictor state flush) is a small fraction, short enough to keep response time acceptable.

**Overlap enables utilization**: treat each CPU burst between I/Os as its own job; while one job blocks on I/O, run another. Any design that serializes I/O-wait and compute wastes the machine (Figure 7.8 vs 7.9). This is the thread/async motivation in one picture.

## ch-8 — Multi-Level Feedback Queue {#ch-8}

Real general-purpose schedulers cannot know job lengths, so **MLFQ** learns them: "pay attention to how jobs behave over time and treat them accordingly." The refined rules:

1. Higher priority runs.
2. Equal priority → round-robin with that queue's quantum.
3. New jobs enter at top priority (assume interactive until proven otherwise).
4. A job that uses up its allotment at a level — *regardless of how many times it yields* — drops a level (the "regardless" clause is the anti-gaming fix: the original rule demoted only jobs that used a *full* quantum, so a job issuing a token I/O at 99% of each slice kept top priority forever; accounting must track cumulative use, not per-burst use).
5. Periodically boost every job back to the top (prevents starvation of long jobs; adapts when a batch job turns interactive).

Two tunables with failure modes: no priority boost → long jobs **starve** once the machine fills with interactive ones; per-burst instead of cumulative accounting → **gaming**. Any behavior-inferred priority scheme (rate limiters, adaptive pools, abuse scoring) inherits both.

Transferable heuristic: when you can't know cost a priori, **use recent past behavior as the predictor, and periodically reset your beliefs**. BSD, Solaris, Windows NT+ all use MLFQ variants. OSes also accept **advice/hints** (`nice`, `madvise`, informed prefetching) — interfaces where the user knows what the system can't infer.

## ch-14 — Interlude: Memory API {#ch-14}

The six canonical memory errors (all compile silently; "it compiled or it ran ≠ it is correct"):

| Error | Detection cue in code | Consequence |
|---|---|---|
| Forgetting to allocate | using a destination pointer that was never assigned an allocation (`strcpy(dst, src)` with bare `char *dst`) | segfault |
| **Buffer overflow** (not allocating enough) | size math missing the +1 for terminator; `sizeof(ptr)` instead of buffer size | often "works", then corrupts; major security-vuln class |
| **Uninitialized read** | malloc'd struct/array used before any field is set | value depends on heap garbage; intermittent |
| **Memory leak** | allocation with no owner responsible for freeing | long-running processes exhaust memory and must restart; **GC does not save you — a reachable reference is never collected**, so leaks persist in managed languages too |
| **Dangling pointer** (use-after-free) | free followed by any use; alias freed then used via another name | crash or silent overwrite of whatever recycled the memory |
| **Double free** / invalid free | free called twice, or on a pointer not returned by the allocator | undefined; allocator corruption, crashes |

Scope rule for leaks: a **short-lived process leaks nothing that matters** — the OS reclaims the whole address space at exit. Leak-hunting effort belongs on long-running servers/daemons, where a slow leak is an eventual outage. (Two levels of memory management: OS-level reclaim at process death; process-level heap management while alive.)

Size-math cues worth pattern-matching in C-family diffs:

```c
int *x = malloc(10 * sizeof(int));
sizeof(x)              // 4 or 8 — size of the POINTER, not the buffer
malloc(strlen(s))      // off by one: no room for the terminator; use strlen(s)+1
```

Never return a pointer to a stack (function-local) variable from a thread or function — deallocated on return (ch-27 repeats this for thread return values). `calloc()` (zeroing alloc) removes the uninitialized-read class; `realloc()` covers grow-in-place.

Tools are part of the method: valgrind/memcheck and ASan-class tools find all six classes; "know and use your tools" is presented as a discipline, not a suggestion. (Ch-27's parallel: `helgrind` finds races and lock-order violations — but reports on `main-deadlock-global.c` show race detectors also false-positive on correct-but-unusual protocols; treat tool output as leads, not verdicts.)

## ch-22 — Beyond Physical Memory: Policies {#ch-22}

Vocabulary an agent needs when reasoning about memory pressure:

- **Demand paging**: pages come in on first access; **prefetching** only when success likelihood is high (e.g., sequential next-page).
- **Dirty vs clean eviction**: evicting a modified (dirty) page costs a disk write; clean pages are free to drop. Systems prefer evicting clean pages — the same asymmetry any cache-with-writeback design inherits.
- **Clustering**: batch many small writes into one large one; disks (and most storage) do one big write far more efficiently than many small.
- **Thrashing**: memory demand of running processes exceeds physical memory → the system pages constantly and no one progresses.
- Two responses to thrashing: **admission control** — run a subset of processes so their **working sets** (actively-used pages) fit; "sometimes better to do less work well than to try to do everything at once poorly" — or the draconian **out-of-memory killer** (Linux OOM killer picks a memory-intensive process and kills it; can kill the wrong thing).
- Modern replacement is LRU-approximation (clock) plus **scan resistance** (ARC) to survive looping-sequential workloads that are LRU's worst case.

Practical implication (stated in ch-31 throttling): if N workers each entering a memory-intensive region would exceed RAM, thrashing follows — bound concurrent entry with a semaphore (admission control at application level).

## ch-26 — Concurrency: An Introduction {#ch-26}

The four core terms (Dijkstra's):

- **Critical section**: code that accesses a shared resource and must not be concurrently executed by more than one thread.
- **Race condition / data race**: multiple threads enter the critical section at roughly the same time; result depends on timing.
- **Indeterminate program**: contains ≥1 race; output varies run to run.
- **Mutual exclusion**: the property that guarantees one-thread-at-a-time in the critical section.

The canonical demonstration: `counter = counter + 1` compiles to load/add/store — three instructions; a timer interrupt between them lets two increments produce one. Two threads doing 10M increments each yield a *different wrong total each run*. Root cause name: **uncontrolled scheduling**. The trace to internalize (counter starts at 50; "correct" result 52):

```
T1: load counter→eax (50); add → eax=51        ── interrupt, save T1 ──
T2: load counter→eax (50); add; store → counter=51
                                                ── interrupt, restore T1 ──
T1: store eax(51) → counter=51                  // one increment lost
```

Any read-modify-write on shared state — `x += 1`, `list.head = new`, `balance = balance + amount` — is this trace until proven atomic.

**Atomicity** = "all or nothing" — either the grouped actions all appear to have happened or none did, no in-between state visible. Synchronization primitives build atomic sections from hardware instructions; file systems build it with journaling/COW (ch-42) — one concept, every layer.

Threads vs processes: threads share the address space (cheap data sharing, all the races); processes are "a more sound choice for logically separate tasks where little sharing is needed." Each thread has its own stack — stack data is effectively thread-private; shared data must live in the heap or globals.

Two legitimate reasons to use threads: **parallelism** (multiple CPUs on CPU-bound work) and **overlap of I/O with computation**. (↔ `using-asyncio-in-python` ch-1: for I/O-bound-only workloads the event loop covers the second reason with fewer race classes; OSTEP ch-33 gives the same trade-off from the OS side.)

There is a second problem class besides atomicity: **waiting/ordering** — one thread must wait for another's action (I/O completion, initialization). Locks solve atomicity; condition variables/semaphores solve ordering. Bugs split the same way (ch-32).

**Think like a malicious scheduler**: to validate concurrent code, assume the scheduler interrupts at the worst possible instruction. An improbable interleaving is still a bug.

## ch-27 — Interlude: Thread API {#ch-27}

The API-guidelines aside, condensed (POSIX names, language-neutral rules):

- **Keep it simple**: tricky thread interactions → bugs. Minimize the number of ways threads interact; each interaction should use a known pattern.
- **Initialize locks and CVs** explicitly; failure produces code that "sometimes works and sometimes fails in very strange ways."
- **Check return codes** of lock/unlock and thread calls: a silently failed lock acquisition means multiple threads in the critical section. Minimally wrap with an assert-on-failure wrapper.
- **Never pass or return stack-allocated data across a thread boundary** — the frame is deallocated when the function returns.
- A create-then-immediately-join pattern is just a slow function call — thread creation must buy real concurrency or be deleted.
- `trylock`/`timedlock` variants exist for deadlock avoidance (ch-32); "should generally be avoided" otherwise.
- **Always use condition variables to signal between threads; a simple flag is never acceptable.** Empirical basis [X+10, "Ad Hoc Synchronization Considered Harmful"]: **roughly half** of ad-hoc flag-based synchronizations studied were buggy. Spinning on a flag also wastes CPU.
- CV mechanics preview: wait takes the mutex because it must *atomically* release the lock and sleep, then re-acquire before returning; waiting is done in a `while` loop because implementations can wake threads spuriously — "view waking up as a hint that something might have changed, rather than an absolute fact."

## ch-28 — Locks {#ch-28}

Evaluate any lock on three axes: **mutual exclusion** (does it work), **fairness** (can a waiter starve), **performance** (uncontended overhead; contended single-CPU; contended multi-CPU).

Build-up of implementations and the lesson each carries:

| Approach | Verdict | Lesson |
|---|---|---|
| Disable interrupts | Only inside a kernel, single-CPU | requires trusting the caller; no-op on multiprocessors; loses interrupts |
| Plain load/store flag | **Broken** — both threads can see flag==0 and both set it | test and set must be one atomic step |
| **Test-and-set** spin lock | Correct; unfair (spinner can starve); single-CPU contention wastes whole time slices | needs a preemptive scheduler even to work on one CPU |
| **Compare-and-swap** | Same lock; strictly more powerful primitive (enables lock-free structures, ch-32) | |
| **Ticket lock** (fetch-and-add) | Correct **and fair** — every thread's ticket guarantees eventual progress | FIFO ordering is what kills starvation: `myturn = FetchAndAdd(&ticket); while (turn != myturn) spin;` unlock: `turn++` |
| yield instead of spin | Better, but N−1 context switches per handoff and still starvation-prone | |
| **Queue + park/unpark (or futex)** | The real design: sleep waiters, hand the lock directly to the next queued thread | guard spin is bounded (few instructions); solves fairness and waste |

The queue-lock skeleton (Solaris park/unpark flavor) — worth knowing because its two subtleties recur in every runtime's lock:

```c
lock(m):   spin-acquire guard            unlock(m): spin-acquire guard
           if (flag == 0)                           if (queue empty)
               flag = 1;   // got it                    flag = 0;      // release
           else {                                   else
               enqueue(self);                           unpark(dequeue()); // pass lock
               guard = 0;                           guard = 0;
               setpark(); park(); }
```

Subtlety 1: on wakeup the flag is **not** reset — the lock is *passed directly* from releaser to the woken thread (the wakee couldn't safely re-set it). Subtlety 2: `setpark()` before releasing the guard closes the wakeup/waiting race (below). The guard itself spins, but only for a few instructions — bounded spin around bookkeeping is fine; unbounded spin around user critical sections is not.

**Spin vs block decision**: spinning wastes exactly what the waiter's time slice costs — catastrophic on one CPU (holder can't run while you spin), acceptable on multi-CPU **only when critical sections are short and the holder is running on another core**. **Two-phase locks** encode the compromise: spin briefly (lock may be released imminently), then sleep. Linux futex locks are one-spin two-phase.

**Priority inversion** (why spin locks are a *correctness* risk, not just waste): high-priority T2 spins on a lock held by low-priority T1, which never gets scheduled → system hangs (Mars Pathfinder). With three threads it happens even with blocking locks: medium-priority T2 starves lock-holder T1, stranding high-priority T3. Fixes: **priority inheritance** (booster the holder), avoid spin locks, or flatten priorities.

**Wakeup/waiting race**: between "enqueue myself" and "actually sleep", the wakeup can arrive and be lost → sleep forever. Solaris `setpark()` closes it (pre-declare intent to sleep; an intervening unpark makes park return immediately). Any hand-rolled sleep/wake protocol has this window — the reason to use provided primitives, and the OS-level ancestor of every "lost wakeup" bug.

Design asides worth keeping: **Lauer's Law** — brag about how *little* code accomplished the task; concise code has fewer bugs. Futex fast path — optimize the uncontended common case to one atomic op.

## ch-29 — Lock-based Concurrent Data Structures {#ch-29}

**The method**: to make a structure thread-safe, add one lock, acquired at every routine's entry and released at exit (monitor pattern). "If the data structure is not too slow, you are done! No need to do something fancy if something simple will work."

**Knuth's Law applied** (avoid premature optimization): start with the single big lock; refine *only* when a measured performance problem exists. Linux ran on the Big Kernel Lock for years; it was the right call until multi-CPU became the norm.

**More concurrency isn't necessarily faster**: hand-over-hand (lock-per-node) list locking is conceptually more concurrent but in practice slower than one lock — per-node acquire/release overhead swamps the parallelism. "You can't cheat on performance: build both and measure."

Where fine-graining *does* pay, the structure tells you:

- **Approximate counter**: per-CPU counters + periodic flush (threshold S) to a global; trades accuracy (global lags by ≤ CPUs×S) for near-perfect scaling. Exact reads would need all locks in a fixed order (deadlock discipline even here).
- **Michael-Scott queue**: separate head lock and tail lock + dummy node so enqueue and dequeue don't contend.
- **Hash table**: lock per bucket — scales "magnificently" because operations naturally shard.

**Locks and control flow**: be wary of early returns/error exits inside a lock-holding region — every exit path must release. ~40% of Linux kernel bugs were on rarely-taken error paths. Restructure so lock/unlock wrap only the true critical section (e.g., allocate *before* taking the lock — thread-safe `malloc` needs no protection) and use a single exit path for search loops.

## ch-30 — Condition Variables {#ch-30}

A **condition variable** is an explicit queue threads sleep on while some program state is not as desired; another thread that changes the state signals to wake one (or broadcasts to wake all). The complete discipline — every element is load-bearing, and the chapter proves each by deleting it:

1. **A state variable is mandatory** (e.g., `done`). Signal-with-no-state: the child signals before the parent waits → the signal is lost → the parent sleeps forever. *The CV is a wakeup channel, not a memory; the state variable records what happened.*
2. **Hold the lock when calling wait — mandated by semantics** (wait atomically releases the lock and sleeps, re-acquires before returning). **Hold the lock when signaling and when modifying the state variable — always do it**; without the lock, check-then-wait races the state change (parent checks `done==0`, is preempted, child sets and signals into the void, parent sleeps forever).
3. **Wait in a `while` loop, never an `if`.** Two independent reasons: (a) **Mesa semantics** — signaling merely moves the waiter to ready; between wakeup and running, another thread can consume the state (Tc2 "sneaks in" and empties the buffer; woken Tc1 asserts on empty). Virtually every real system is Mesa, not Hoare. (b) **Spurious wakeups** exist in real implementations. "Always use while loops; it is always safe; just do it."
4. **Signal the right waiters — use distinct CVs per condition.** One CV for producer/consumer lets a consumer wake a consumer while the producer sleeps → all threads asleep, deadlock. Producers wait on `empty`/signal `fill`; consumers wait on `fill`/signal `empty`.
The producer/consumer progression — each version's bug is a named failure mode you can match in reviews:

| Version | Defect | Failure trace (compressed) |
|---|---|---|
| Single CV + `if` | wakeup-to-run gap | producer signals Tc1; before Tc1 runs, Tc2 consumes the item; Tc1 proceeds past the stale `if` and consumes from an empty buffer |
| Single CV + `while` | wrong waiter woken | consumer's signal wakes another *consumer* instead of the sleeping producer → all three threads asleep forever |
| Two CVs + `while` | correct | producers wait on `empty`, signal `fill`; consumers wait on `fill`, signal `empty` — a class can never wake itself |

5. **Covering condition**: when the waker can't know *which* waiter can proceed (memory allocator: freed 50 bytes; waiters want 100 and 10), replace signal with **broadcast** — every waiter wakes, re-checks (the while loop again), and the ineligible go back to sleep. Cost: needless wakeups. Diagnostic: "if your program only works when you change signals to broadcasts, but you don't think it should need to, you probably have a bug" — broadcast is for genuinely covering conditions, not a fix for missing state.

Canonical micro-example (the whole trio in nine lines):

```c
// waiter                                // signaler
lock(&m);                                lock(&m);
while (ready == 0)                       ready = 1;
    cond_wait(&c, &m);                   cond_signal(&c);
unlock(&m);                              unlock(&m);
```

## ch-31 — Semaphores {#ch-31}

A semaphore is an integer with `wait` (decrement; sleep if negative) and `post` (increment; wake one waiter). One primitive that can act as lock *or* ordering device — the initial value selects which.

**Initialization rule (Kivolowitz)**: set the initial value to *the number of resources you are willing to give away immediately*. Lock (binary semaphore): 1. Ordering/join (wait for an event that hasn't happened): 0. Bounded buffer of N slots: `empty=N`, `full=0`. Throttling K concurrent entrants: K.

**The correct bounded buffer** (memorize the nesting — ordering waits *outside*, mutex *inside*):

```c
producer:                          consumer:
  sem_wait(&empty);                  sem_wait(&full);
  sem_wait(&mutex);                  sem_wait(&mutex);
  put(i);                            tmp = get();
  sem_post(&mutex);                  sem_post(&mutex);
  sem_post(&full);                   sem_post(&empty);
// init: empty=MAX, full=0, mutex=1
```

**Lock-scope deadlock** (the chapter's key negative example): invert that nesting — mutex *around* the `wait(empty)`/`wait(full)` calls — and it deadlocks: consumer holds the mutex and sleeps on `full`; producer needs the mutex to ever post `full`. Fix: **shrink the lock to the actual critical section**; ordering waits go outside the mutual-exclusion region. General rule: *never hold a lock while blocking on a condition that only another lock-needing thread can satisfy.* (Also note the mutex is needed at all only with multiple producers or consumers — two producers interleaving `buffer[fill]=v` and `fill++` overwrite each other's slot.)

**Reader-writer locks**: readers count in under a small lock; first reader takes the write lock, last reader releases it. Caveats: readers easily **starve writers**; the added overhead often loses to a plain lock. **Hill's Law: "Big and dumb is better"** — try the simple lock first; complex ≈ slow until measured otherwise. And Lampson: "Don't generalize; generalizations are generally wrong" — semaphores generalize locks+CVs, yet building a CV from semaphores is a famous bug farm; the generalization is weaker than it looks.

**Dining philosophers**: everyone grabs left fork then right → cycle → deadlock. Dijkstra's fix: **one participant acquires in the opposite order**, breaking the cycle. This is the minimal demonstration that you don't need a global redesign — breaking the circular-wait condition *anywhere in the cycle* suffices.

**Thread throttling / admission control**: bound the number of threads in a memory- or resource-intensive region with a semaphore initialized to the threshold — the application-level cure for ch-22 thrashing.

**Zemaphore** (semaphore from lock+CV): `value`, one lock, one CV, wait-in-while — the state-variable trio again; ~20 lines. The reverse construction (CV from semaphores) defeated "highly experienced concurrent programmers" — don't attempt it in production code.

## ch-32 — Common Concurrency Problems {#ch-32}

Empirical base: Lu et al. [L+08] studied 105 real concurrency bugs in MySQL, Apache, Mozilla, OpenOffice: **74 non-deadlock, 31 deadlock**. Of the non-deadlock bugs, **97% are one of exactly two patterns** — this is the review checklist:

**1. Atomicity violation** — "the desired serializability among multiple memory accesses is violated": a code region *assumed* atomic isn't enforced atomic. Detection cue: **check-then-act on shared state in separate steps** (test a pointer non-null, then dereference it, while another thread can NULL it in between; TOCTOU generally). Fix: one lock held across *both* the check and the act — and every other accessor of that state takes the same lock.

```c
Thread 1: if (thd->proc_info) { fputs(thd->proc_info, ...); }   // check … act
Thread 2: thd->proc_info = NULL;                                 // interleaves between them
```

**2. Order violation** — "the desired order between two memory accesses is flipped": B assumes A already ran (thread reads `mThread` that creator sets after spawn), but nothing *enforces* it. Detection cue: **cross-thread use of state initialized by another thread with no join/CV/semaphore between them**; "it always runs first in practice" is the tell. Fix: enforce the order — condition variable with a state flag (the ch-30 trio) or a 0-initialized semaphore.

**Deadlock — the four conditions** (Coffman). All four must hold; **break any one and deadlock is impossible**:

| Condition | Meaning | How to break it | Cost/caveat |
|---|---|---|---|
| Mutual exclusion | threads claim exclusive control of resources | lock-free/wait-free structures via compare-and-swap | complexity; livelock still possible; niche |
| Hold-and-wait | hold one lock while waiting for another | acquire all locks at once under a meta-lock | kills encapsulation (must know all locks up front); reduces concurrency |
| No preemption | locks can't be forcibly taken | `trylock` + release-all-and-retry | **livelock** (add random back-off delay); unwinding partially-acquired state is hard |
| **Circular wait** | a cycle of threads each holding what the next wants | **total or partial lock ordering** — *the most practical and frequently employed technique* | ordering is only a convention; needs codebase-wide knowledge; one violation reintroduces deadlock |

Lock-ordering craft: real systems document **partial orders** (Linux mm: "i_mutex before i_mmap_rwsem…" — ten ordered groups). When a function takes multiple lock arguments, **order acquisition by lock address** (always high-to-low or low-to-high) so `f(L1,L2)` and `f(L2,L1)` can't deadlock each other:

```c
if (m1 > m2) { lock(m1); lock(m2); }   // one canonical order,
else         { lock(m2); lock(m1); }   // whatever order the args came in
// assumes m1 != m2
```

The trylock (break no-preemption) protocol, with its cost visible:

```c
top:  lock(L1);
      if (trylock(L2) != 0) { unlock(L1); /* random delay */ goto top; }
```

Deadlock-free in any acquisition order, but: (a) symmetric retriers **livelock** without the random delay; (b) anything else acquired between `top` and the failure (memory, other resources) must be released before retrying; (c) encapsulation makes the jump-back hard when L1 is buried in a callee.

Lock-free flavor (break mutual exclusion) — the CAS retry idiom:

```c
void insert(int value) {
    node_t *n = ...; n->value = value;
    do { n->next = head; }
    while (CompareAndSwap(&head, n->next, n) == 0);  // retry if head moved
}
```

No lock, no deadlock; livelock still possible, and anything beyond insert (delete + lookup coexisting) is research-grade hard — use vetted libraries.

Why deadlocks happen anyway: complex cross-component dependencies (VM needs FS, FS needs VM), and **encapsulation works against locking** — `v1.AddAll(v2)` locks both vectors in an order the caller can't see; a concurrent `v2.AddAll(v1)` deadlocks invisibly.

Other strategies, honestly priced: **avoidance via scheduling** (Banker's algorithm) needs global fore-knowledge of every thread's lock set — only viable in closed embedded systems, and it serializes work. **Detect and recover** (periodic cycle detection over the waits-for graph, then restart/rollback) is standard in databases and pragmatic when deadlock is rare — **Tom West's Law**: "not everything worth doing is worth doing well"; if a bad thing is rare and cheap, don't gold-plate the prevention.

Deadlock in the resource graph = a cycle; drawing the holds/wants graph is the diagnostic (Figure 32.7).

## ch-33 — Event-based Concurrency {#ch-33}

The event loop: `while (1) { events = getEvents(); for e: processEvent(e); }` — the handler is the only activity in the system, so **deciding which event to handle next = scheduling**, moved from OS to application. Built on `select()`/`poll()` readiness APIs (zero timeout → non-blocking poll).

Why simpler: **with a single CPU and one handler at a time, no locks are needed** — the class of interleaving bugs vanishes.

The rules and costs (each caveat is a decision trigger):

1. **No blocking calls, ever, in a handler** — one blocking call halts the entire server (the async runtime's cardinal rule; ↔ `using-asyncio-in-python` ch-1/ch-3, same rule from the application side). Disk I/O must go through **asynchronous I/O** APIs (issue now, poll `aio_error()` or get a signal on completion), or a hybrid thread pool for I/O when AIO is missing [Flash, PDZ99].
2. **Manual stack management**: async splits what was one sequential function into issue-handler + completion-handler; the in-between state that lived on the thread stack must be packaged into a **continuation** (record state keyed by request; look it up on completion). The two-line thread version vs the event version makes the tax concrete:

   ```c
   // thread version: sd lives on the stack across the blocking read
   rc = read(fd, buffer, size);
   rc = write(sd, buffer, size);
   // event version: store {fd → sd} in a table at issue time;
   // the read-completion handler looks up sd to know where to write
   ```

   This is the structural tax of event code — and why routines that change from non-blocking to blocking force their callers to be "ripped into two pieces." (Language-level async/await is this bookkeeping automated; the semantic constraints remain.)
3. **Multicore ends the free lunch**: to use >1 CPU you run handlers in parallel, and locks return. Single-threaded no-lock reasoning holds only single-threaded.
4. **Implicit blocking**: page faults block the handler regardless of code structure; heavily-paging event servers stall invisibly.
5. Neither model won: "both threads and events are likely to persist as two different approaches to the same concurrency problem."

## ch-39 — Files and Directories: durability rules {#ch-39}

**What `write()` promises**: only that data reached the file system's in-memory buffer; the FS flushes "at some point in the future" (5–30 s). A crash in that window loses acknowledged writes. `write()` returning success is *not* durability.

**`fsync(fd)`**: forces all dirty data for that file to persistent storage; returns only when writes are complete:

```c
int fd = open("foo", O_CREAT|O_WRONLY|O_TRUNC, S_IRUSR|S_IWUSR);
rc = write(fd, buffer, size);   assert(rc == size);
rc = fsync(fd);                 assert(rc == 0);
// only now is the data durable — "if fsync() is correctly implemented, that is"
```

The durability protocol:

- **fsync the containing directory too when the file is newly created** — fsync on the file makes its *contents* durable, but the directory entry that makes it reachable is separate metadata. "This detail is often overlooked, leading to many application-level bugs [P+13, P+14]."
- **`rename(old, new)` is (usually) atomic with respect to crashes**: after a crash the name refers to the old file or the new file, never an in-between. It is the only general atomic-replace primitive applications have.

**The canonical atomic-update pattern** (how editors avoid half-written files — memorize it):

```c
int fd = open("foo.txt.tmp", O_WRONLY|O_CREAT|O_TRUNC, ...);
write(fd, buffer, size);   // full new version
fsync(fd);                 // force contents to disk
close(fd);
rename("foo.txt.tmp", "foo.txt");  // atomic swap into place
```

Never update a must-survive-crash file in place: a crash mid-write leaves a torn file with no recovery path. Write the complete new version to a temp name, fsync, then rename (and fsync the directory if the entry itself must be durable immediately).

## ch-42 — Crash Consistency: FSCK and Journaling {#ch-42}

**The crash-consistency problem**: an operation that must update N on-disk structures (append = inode I + bitmap B + data block D) can crash between any two writes; the disk commits one write at a time. The complete outcome table for the three-write append — the vocabulary of every partial-write bug:

| Survived the crash | Result | Severity |
|---|---|---|
| D only | data on disk, nothing references it | harmless to FS (user lost data) |
| I only | inode points at garbage; inode/bitmap disagree | read garbage + **inconsistency** |
| B only | bitmap says allocated, nothing points to it | **space leak** |
| I + B | metadata fully *consistent* — pointing at garbage | worst kind: checkers can't detect it |
| I + D | inode/bitmap disagree | inconsistency |
| B + D | allocated block, unknown owner | inconsistency |

Goal: move from one consistent state to another **atomically** despite non-atomic hardware. Note the I+B row: *consistency and correctness are different properties* — a checker can restore agreement among metadata and still leave pointers at junk.

**Solution 1 — fsck (check-and-repair at boot)**: let inconsistencies happen; scan everything later (superblock sanity, bitmap rebuild from inodes, link counts, duplicate/bad pointers, directory integrity, lost+found). Verdict: works but is O(size-of-disk) — "search-the-entire-house-for-keys"; and it can only restore metadata *consistency*, not tell garbage data from real (a consistent FS can still point at junk). Too slow for modern volumes.

**Solution 2 — journaling (write-ahead logging)**: before overwriting structures in place, write a note describing the update to a log; on crash, replay committed notes (**redo logging**). Recovery cost drops to O(log size). The **data-journaling protocol** and its non-negotiable ordering:

1. **Journal write**: TxB (tx id + final addresses) + all updated blocks to the log; wait for completion.
2. **Journal commit**: write TxE (single 512-byte sector, which the disk does write atomically); wait. Only now is the tx *committed*.
3. **Checkpoint**: write the blocks to their final locations.
4. **Free**: mark the tx free in the journal superblock (the log is circular and finite).

Why TxE must be a separate step: issue all five blocks at once and the disk may reorder internally — TxB…TxE can land while a middle block didn't, leaving a *valid-looking* transaction full of garbage that recovery will happily replay over live data. (Optimization: **transaction checksums** in TxB/TxE let ext4 issue everything at once and detect torn transactions at recovery.)

Ordering is enforced with **write barriers** — and some disks lie about them for benchmark wins ("the fast almost always beats out the slow, even if the fast is wrong"). Trust in the fsync/barrier chain is a real-world risk, not paranoia.

**Metadata (ordered) journaling** — the common mode (ext3 ordered, XFS, NTFS): journal only metadata; write data blocks **directly to their final location first**, and only then commit the metadata transaction. The governing rule, core of all crash consistency:

> **Write the pointed-to object before the object that points to it.** A pointer must never come into existence before its target is durable — otherwise recovery produces consistent metadata pointing at garbage.

(Soft Updates generalizes this rule to all FS structures; copy-on-write (ZFS/LFS) sidesteps overwrite entirely — write new versions elsewhere, then atomically flip the root pointer.)

**Block-reuse hazard**: delete a journaled directory block, reuse the block for file data, crash → replay overwrites the new user data with old directory contents. ext3's fix: **revoke records** — replay first scans for revocations and never replays revoked blocks. General lesson: a log that can replay stale writes over reused resources needs an invalidation record type ("everything to do with delete is hairy" — Tweedie).

The complete ordering invariants, extracted from the two timelines (Figures 42.1/42.2) — the checklist for reviewing *any* WAL-style protocol:

1. Within a transaction, payload writes (TxB + contents; in ordered mode also the data blocks) may be issued concurrently and complete in any order.
2. The **commit record (TxE) must not be issued until every payload write has completed** — the only thing that makes a transaction real.
3. **Checkpointing (in-place writes) must not begin until the commit record has completed.**
4. In metadata journaling, **data must reach its final location before the commit** — the pointed-to-before-pointer rule in protocol form.
5. Space reclamation (free) happens only after checkpoint completes.
6. Completion order between writes is otherwise up to the device; only these dashed-line orderings are guaranteed, and only if barriers/flushes are honored.

Performance shape: batching many updates into one global transaction amortizes journal traffic; data journaling halves sequential-write bandwidth (everything written twice), which is why ordered/metadata mode is the default. Recovery replays committed transactions idempotently — a crash *during* checkpoint just redoes some writes, which is why checkpoint needs no ordering internally.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| `if` guarding a condition-variable wait | Change to `while`; re-check condition after every wakeup | Mesa semantics + spurious wakeups: wakeup is a hint, not a guarantee | ch-30 |
| Shared flag + spin/sleep-poll used to signal between threads | Replace with lock + state variable + condition variable | ~half of ad-hoc synchronizations studied were buggy; also burns CPU | ch-27 |
| `signal`/`broadcast` called without holding the associated lock, or with no state variable set | Set state under the lock, then signal under the lock | Lost-wakeup race: waiter checks state, is preempted, signal lands before the wait → eternal sleep | ch-30 |
| One CV shared by waiters with different wake conditions | One CV per condition (empty/fill); signal the class that can proceed | Wrong-waiter wakeup → all threads asleep (producer/consumer v2 bug) | ch-30 |
| Waker can't determine which waiter is now eligible | Broadcast (covering condition); waiters re-check and re-sleep | Only signal-per-condition or broadcast guarantees eligible waiters wake | ch-30 |
| Check of shared state and dependent action in separate steps (null-check→deref, exists→open, TOCTOU) | Hold one lock across check *and* act — atomicity violation | The check is invalid by the time the act runs; #1 non-deadlock bug pattern | ch-32 |
| Thread B uses state that thread A initializes, no join/CV/semaphore enforcing order | Enforce the order explicitly — order violation | "Usually runs first" is scheduling luck, not synchronization; #2 pattern | ch-32 |
| Code path acquiring ≥2 locks; or same locks acquired in different orders at different sites | Impose a total/partial lock order; for lock parameters, acquire in address order | Circular wait is the cheapest deadlock condition to break | ch-32 |
| Lock acquisition buried behind an interface that takes another locked object as argument (`v1.addAll(v2)`) | Treat as a multi-lock site: document order or use trylock-and-back-off | Encapsulation hides lock order; symmetric calls deadlock invisibly | ch-32 |
| `trylock` retry loop that releases and re-acquires | Add randomized back-off delay | Symmetric retry loops livelock — running but no progress | ch-32 |
| A lock held while blocking on a condition another thread must satisfy | Shrink the lock to the true critical section; wait outside it | Producer/consumer semaphore deadlock: sleeper holds the mutex the waker needs | ch-31 |
| Choosing a semaphore's initial value | Initial value = resources you can give away immediately (lock:1, ordering:0, N-buffer:N, throttle:K) | Wrong initial value silently becomes a deadlock or a broken lock | ch-31 |
| All parties acquire the same resource sequence in the same relative direction around a cycle | Make one participant acquire in the opposite order | Dining philosophers: breaking the cycle anywhere prevents the deadlock | ch-31 |
| Unbounded worker concurrency entering a memory/resource-intensive region | Throttle with a semaphore sized to the threshold (admission control) | Oversubscribed memory → thrashing → everything slows to a crawl | ch-31, ch-22 |
| Spin lock (or spin-wait) where the holder can be preempted, or on a single CPU | Use a blocking lock (or two-phase: bounded spin then sleep) | Spinner wastes whole time slices; priority inversion can hang the system | ch-28 |
| Lock choice where waiters and holders have different scheduling priorities | Avoid pure spin locks; require priority inheritance or equal priorities | Priority inversion is a correctness failure (Mars Pathfinder), not just waste | ch-28 |
| Hand-rolled sleep/wake protocol with a gap between "decide to sleep" and "sleep" | Use primitives with atomic release-and-sleep (CV wait, futex, setpark) | Wakeup/waiting race: the wake lands in the gap and is lost forever | ch-28 |
| New concurrent data structure designed with fine-grained/lock-free locking up front | Start with one big lock; refine only on measured contention | Big-lock version is likely correct; hand-over-hand lists lose to one lock in practice | ch-29 |
| Early return / error exit inside a lock-holding region | Single exit path; lock only the true critical section; move allocation outside | ~40% of kernel bugs live on rarely-taken paths; missed unlock = system hang | ch-29 |
| Choosing per-item vs whole-structure locks for a shardable structure (hash table) | Lock per bucket/shard when operations naturally partition | Bucket locks scale "magnificently"; whole-list locks don't — but only sharded access patterns benefit | ch-29 |
| Counter/statistic updated by many CPUs and read rarely or approximately | Per-CPU counters + threshold flush to global (approximate counter) | Precise shared counter serializes all CPUs; accuracy/perf trade is explicit via S | ch-29 |
| Handler code inside an event loop calling anything that can block (sync I/O, long compute) | Forbidden — async I/O, offload to thread pool, or split the handler | One blocking call stalls every connection the loop serves | ch-33 |
| Event-based design moving to multiple CPUs | Locks return; single-threaded no-lock reasoning no longer applies | Parallel handlers have the same critical sections as threads | ch-33 |
| A routine used by event handlers changes from non-blocking to blocking | Every calling handler must be restructured (split at the new wait point) | Blocking is disastrous in loops; semantic changes propagate to all callers | ch-33 |
| `write()` success treated as durability; file created/updated with no `fsync` | fsync the file; if newly created, fsync the containing directory too | Buffered writes flush seconds later; crash loses acknowledged data; the dirent is separate | ch-39 |
| In-place overwrite of a file whose content must survive a crash | Write temp file → fsync → close → `rename()` over the original | rename is atomic w.r.t. crashes; in-place update has torn-state windows | ch-39 |
| Any design writing a pointer/reference before the thing it points to is durable | Write the pointed-to object first, then the pointer | Recovery must never see valid metadata pointing at garbage — core of crash consistency | ch-42 |
| Log/journal replay where logged resources can be freed and reused | Add revoke/invalidation records; scan them before replay | Replay of stale entries overwrites reused blocks with old data | ch-42 |
| Issuing a commit/sentinel record together with the payload it validates | Commit record goes in a separate ordered write (or checksum the payload) | Devices reorder within a batch; a valid-looking torn transaction replays garbage | ch-42 |
| Batch job scheduling where short and long tasks share a FIFO queue | Prefer shortest-first / preemption, or separate queues | Convoy effect: short consumers queue behind one heavyweight | ch-7 |
| Task priority/cost unknown a priori | Infer from recent behavior; periodically reset (MLFQ boost) | History predicts; without reset, demoted jobs starve and behavior changes are missed | ch-8 |
| Long-running service with allocation sites lacking a freeing owner (or reachable caches that only grow) | Treat as a leak — GC does not collect reachable references | Slow leaks in servers end in OOM restart; short-lived processes are exempt | ch-14 |
| Fairness-sensitive lock or queue with no FIFO/ticket ordering | Add ordering (ticket lock / queue) if starvation matters | Plain test-and-set spinners can starve forever under contention | ch-28 |
| Reader-writer lock proposed for a read-mostly structure | Try the plain lock first; adopt RW only with measured benefit and a writer-starvation plan | RW locks add overhead, often lose to simple locks, and readers starve writers (Hill's Law) | ch-31 |
| A concurrency bug "fixed" by changing signal to broadcast without understanding why | Treat as a hidden bug unless the condition is genuinely covering | Broadcast masks wrong-waiter/missing-state defects; it's correct only when the waker can't know who's eligible | ch-30 |
| A checker/validator restores internal consistency of metadata after failures | Consistency ≠ correctness: valid-looking references can still point at garbage | The I+B crash case is fully consistent and fully wrong; only ordering rules prevent it | ch-42 |

## Anti-patterns

- **Ad-hoc synchronization** — bare shared flag with spin or sleep-poll instead of CV/semaphore. Cue: `while (flag == 0);` or `while not done: sleep(0.1)`. Half of studied instances were buggy [X+10]. (ch-27)
- **If-before-wait** — `if (cond) wait(cv)` instead of `while`. Cue: any CV wait not lexically inside a loop re-testing the predicate. Fails under Mesa semantics and spurious wakeups. (ch-30)
- **Signal without state** — CV used as if it stores the event. Cue: `signal()` with no accompanying state-variable write; `wait()` with no predicate to test. Signals sent before the wait are lost. (ch-30)
- **Check-then-act (atomicity violation / TOCTOU)** — cue: shared pointer/field tested and then used in separate statements; file existence checked then opened. #1 real-world non-deadlock bug. (ch-32)
- **Assumed initialization order (order violation)** — cue: `mState = mThread->State` style cross-thread reads of another thread's setup with no synchronization edge. #2 real-world pattern. (ch-32)
- **Hold-and-wait across a blocking condition** — cue: `lock(m); wait_for(resource)` where posting the resource requires `m`. Deadlocks with exactly two threads. (ch-31)
- **Hidden multi-lock via encapsulation** — cue: methods taking another lockable object as a parameter (`v1.addAll(v2)`) called with operands swapped elsewhere. (ch-32)
- **Symmetric trylock retry without back-off** — livelock: both threads loop forever making no progress. Cue: `goto top` / `continue` retry with no randomized delay. (ch-32)
- **Premature fine-grained locking** — hand-over-hand/lock-per-node designs with no contention measurement. Usually slower than one lock. (ch-29)
- **Blocking call in an event handler** — sync file read, DNS lookup, long loop inside a select/poll/async loop. One call stalls all clients. (ch-33)
- **Write-and-forget durability** — `write()`/`close()` with no fsync, or fsync on a new file without fsyncing its directory; in-place rewrite of a critical file. (ch-39)
- **Pointer-before-pointee** — persisting a reference (inode ptr, index entry, manifest line) before the referenced data is durable. (ch-42)
- **Returning stack memory across a boundary** — thread return value or callback context pointing into a deallocated frame. (ch-27, ch-14)
- **Leak absolution by GC** — assuming a garbage collector prevents leaks; reachable-but-unused references (registries, caches, listeners) are never collected. (ch-14)
- **Convoy** — FIFO service order letting one heavyweight request queue many short ones. Watch any single work queue with mixed job sizes. (ch-7)

## Applicability & exemptions

- **The concurrency discipline (ch-26–32) applies to preemptive shared-memory threads.** In single-threaded cooperative runtimes (asyncio, node) locks are unnecessary *within* the loop — but the atomicity/order-violation patterns reappear across `await` points, and the moment handlers run on multiple cores the full discipline returns (ch-33; see `using-asyncio-in-python` ch-2/3 for the cooperative-side rules).
- **Big-lock-first is a starting default, not an end state**: the exemption is a *measured* performance problem — then shard (buckets), split (head/tail), or approximate (per-CPU counters). Don't cite Knuth's Law to block a fix backed by contention data.
- **Spin locks are legitimate** inside kernels/interrupt-disabled contexts and on multiprocessors with provably short critical sections and equal priorities. The prohibition targets user-level code subject to preemption and priority differences.
- **Deadlock prevention is not always the right spend** (Tom West's Law): if deadlock is rare, detect-and-recover (databases do this) or even reboot-on-freeze is a defensible engineering position. Reserve total-ordering rigor for code where deadlock is frequent or the cost is high.
- **Leak rules exempt short-lived processes**: the OS reclaims everything at exit; freeing every byte in a run-once CLI is hygiene, not correctness. The rules bind for daemons, servers, and kernels.
- **fsync/rename rules apply to data the application promises to persist.** Caches, temp files, and re-derivable artifacts may deliberately skip fsync for performance. Note also fsync's promise depends on the storage stack honoring barriers — some hardware lies; critical systems verify.
- **Journaling specifics (TxB/TxE, revoke records) are file-system machinery**; agents cite them as *patterns* — write-ahead intent, separate commit record, checksummed transactions, invalidation before reuse — when reviewing any application-level log, migration journal, or outbox implementation.
- **Scheduling policies (ch-7/8) assume the scheduler can't know job lengths.** Where lengths *are* known (closed batch pipelines), SJF/STCF are provably optimal for turnaround and simpler than MLFQ-style inference.
- **Lock-free (CAS-based) structures** avoid deadlock by construction but are explicitly marked hard: livelock remains possible, correct delete/lookup is non-trivial, and the book recommends them only via vetted libraries.

## Candidate lexicon rows

| condition-variable / monitor wait guarded by `if` (any language) | **Wait in a while loop** — Mesa semantics and spurious wakeups make a wakeup a hint that state *might* have changed, never a guarantee | Is every wait lexically inside a loop that re-tests the predicate after waking? | blocker | review | src: os-three-easy-pieces ch-30 |
| bare shared flag with spin or sleep-poll used to signal between threads/tasks | **No ad-hoc synchronization** — roughly half of studied flag-based synchronizations were buggy; use lock + state variable + condition variable (or the runtime's event primitive) | Does this cross-thread signal use a real primitive with atomic release-and-sleep, not a polled flag? | blocker | review | src: os-three-easy-pieces ch-27 |
| `signal`/`notify` call with no accompanying state write, or state/signal updated outside the lock | **State variable, lock, and CV travel together** — a signal sent before the wait is lost forever; state records the event, the lock closes the check-then-sleep race | Is the state variable written under the same lock the waiter holds while testing it? | blocker | review | src: os-three-easy-pieces ch-30 |
| shared value checked in one step and used in another (null-check→deref, exists→open, read→conditional write) | **Atomicity violation (check-then-act)** — the #1 real-world concurrency bug: the check is stale by the time the act runs | Is one lock (or one atomic operation) held across both the check and the dependent act — by every accessor? | blocker | review | src: os-three-easy-pieces ch-32 |
| thread/task B reads state that thread/task A initializes, with no join/CV/semaphore edge between them | **Order violation** — "A always runs first" is scheduling luck, not synchronization; the #2 real-world concurrency bug | What synchronization edge guarantees the initialization happens-before this read? | blocker | review | src: os-three-easy-pieces ch-32 |
| code path acquiring two or more locks; or the same pair of locks taken in different orders at different call sites | **Order your locks** — circular wait is the one deadlock condition that is cheap to break; use a documented partial order, or address order for lock parameters | Can I state the global acquisition order these locks obey, and does every site follow it? | blocker | plan | src: os-three-easy-pieces ch-32 |
| lock held while blocking on a condition that only another thread needing that lock can satisfy | **Never sleep holding the waker's lock** — shrink the mutex to the true critical section; ordering waits go outside it | Could the thread that must wake me possibly need the lock I'm holding while I sleep? | blocker | review | src: os-three-easy-pieces ch-31 |
| new concurrent data structure or service designed with fine-grained/lock-free synchronization before any contention measurement | **Big lock first** — the single-lock version is likely correct; hand-over-hand designs routinely lose to one lock; refine only on measured contention | Is there contention data justifying anything more complex than one lock? | should | plan | src: os-three-easy-pieces ch-29 |
| early return, exception, or error branch inside a lock-holding region | **Mind locks on error paths** — ~40% of kernel bugs live on rarely-taken paths; a missed release is a hang | Does every exit path (including errors) release exactly what it acquired — or does scope-based release make that impossible to get wrong? | should | review | src: os-three-easy-pieces ch-29 |
| spin-wait or spin lock where the holder can be preempted, run on one CPU, or hold longer than a few instructions | **Spin only for short, running holders** — otherwise a waiter burns whole time slices, and priority inversion can hang the system; block or use two-phase locks | Is the lock holder guaranteed to be running on another core with a short critical section? | should | review | src: os-three-easy-pieces ch-28 |
| file created or updated for durability with no `fsync`, or a new file fsynced without its containing directory | **write() is not durability** — buffered data flushes seconds later and dies with a crash; a created file isn't reachable until its directory entry is also forced | After the crash we're defending against, is both the content and the directory entry guaranteed on disk? | blocker | review | src: os-three-easy-pieces ch-39 |
| in-place overwrite of a file whose contents must survive a crash | **Write-temp, fsync, rename** — `rename()` is the only atomic file replace; in-place rewrite has a torn-state window with no recovery | Is the new version fully written and fsynced under a temp name before an atomic rename swaps it in? | blocker | write | src: os-three-easy-pieces ch-39 |
