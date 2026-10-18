# Using Asyncio in Python — distilled

> **Source**: Caleb Hattingh, *Using Asyncio in Python: Understanding Python's Asynchronous Programming Features*, O'Reilly, 1st ed. 2020 · extracted from `../Using-Asyncio-in-Python-Understanding-Python-Hattingh.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory on single-threaded cooperative concurrency as a *safety* choice: why `await` points make races auditable where thread interleavings are invisible, exactly two legitimate reasons to pick an event loop over threads (and five myths that are not reasons), and rigorous startup/shutdown/cancellation procedures for event-loop programs — the lifecycle hygiene ("Task was destroyed but it is pending!", executor-outlives-loop, double-signal shutdown) that no distributed-systems or refactoring text covers. All mechanics are Python `asyncio`, but the decision rules (blocking-in-loop, decouple-receive-from-send, cancellation-is-a-directive, bounded-queue back-pressure) transfer to any cooperative-scheduling runtime (Node.js, Rust async, goroutine-adjacent designs).

## Chapter map

- ch-1 — Introducing Asyncio: what problem the event loop actually solves; the two real reasons and five false ones; the one fatal constraint (no task may hog the loop).
- ch-2 — The Truth About Threads: when threads are the right tool; why nontrivial threaded code is intractable; the race-condition signature and its root cause (`+=` is three ops).
- ch-3 — Asyncio Walk-Through: the API tier model; the 7-function end-user subset; coroutine/Task/Future mechanics; startup, shutdown, cancellation, and signal procedures; the executor-shutdown trap.
- ch-4 — Libraries & Case Studies: streams; the message-broker refactor (decouple receive from send); thread↔coroutine bridging (Janus); aiohttp, ZeroMQ, asyncpg/Sanic; cache invalidation via DB push.
- ch-5 — Concluding Thoughts & History: the key innovation was syntax, not the loop (asyncore existed in 1996); prefer library APIs over raw asyncio.

## ch-1 — Introducing Asyncio {#ch-1}

**The workload premise.** CPUs are hundreds of thousands of times faster than network I/O; a network program's threads are idle ~98% of the time (the **ThreadBots restaurant** measurement). Cooperative multitasking exploits that waiting: one worker (**LoopBot**) that switches tasks *whenever it would otherwise wait* replaces a fleet of mostly-idle preemptive workers — and collisions (races) disappear because there is only one worker.

**The two — and only two — reasons** to choose async over threads, for I/O-bound work:

1. **Safety**: eliminates the class of intra-process shared-memory races that plague nontrivial threaded code, because context switches happen only at visible `await` points.
2. **Scale**: thousands of long-lived socket connections (WebSockets, MQTT/IoT, SSE) per process, far past practical OS thread limits.

**Five myths — things asyncio does NOT do** (each is a real quote-pattern the author debunks):

| Myth | Reality |
|---|---|
| "Asyncio makes my code fast" | No. Threaded solutions usually benchmark *slightly faster* per-request. Asyncio's win is connection count, not speed. Want speed? Cython, not asyncio. |
| "Asyncio makes threading redundant" | No. Multi-CPU shared-memory computation (numpy-style) has no competitor; you will still use threads/processes for blocking libs and CPU work. |
| "Asyncio removes GIL problems" | No. Asyncio is single-threaded, so the GIL is merely *irrelevant* — you also get no multicore benefit. |
| "Asyncio prevents all race conditions" | No. Only intra-process shared-memory races. Inter-process / distributed races over shared resources (DB rows, caches, queues) remain fully possible. |
| "Asyncio makes concurrency easy" | No. Health checks, connection-pool limits vs 5,000 open sockets, graceful termination, blocking disk/log I/O — all design problems remain; only the reasoning is easier with one thread. |

**The one fatal constraint** (the flopped-soufflé lesson): a cooperative loop works only if *every* task is short. Any single long-running step (a "chatty guest" holding the LoopBot) starves every other task. This is the root rule behind every "never block the loop" mechanic in ch-3.

## ch-2 — The Truth About Threads {#ch-2}

Scope note: this whole comparison is **concurrency in network programming**; preemptive threading in other domains has entirely different trade-offs (author's explicit exclusion).

**Benefits of threading** (be honest about them): code reads as simple top-down sequences while running concurrently; shared-memory parallelism across CPUs; decades of know-how and a vast body of existing blocking code. In Python the parallelism benefit is nullified by the **GIL**, which pins interpreter execution to one core (escape hatches: Cython, Numba, processes).

**Drawbacks** (Edward Lee: "nontrivial multithreaded programs are incomprehensible to humans"):

| Drawback | Concrete signal |
|---|---|
| Hardest bug class | Race conditions are non-deterministic; naively designed threaded code can be unfixable even by experts |
| Resource cost | ~8 MB virtual stack per thread → 10,000 do-nothing threads ≈ 80 GB virtual address space (fatal on 32-bit's ~3 GB); shrinking `threading.stack_size()` trades recursion-depth safety |
| Throughput cliff | >~5,000 threads, context-switch cost bites (~50 µs/switch on Linux) — if the OS even lets you create them |
| Inflexible scheduling | OS gives CPU time to threads that are just waiting on sockets; `select()`-driven loops wake a coroutine only when its data is ready |

**Threading best practice when you must thread**: `ThreadPoolExecutor` (from `concurrent.futures`), pass all data through `submit()`, keep jobs short-lived so `shutdown(wait=True)` returns promptly, and **never touch global state from worker functions**. Same API as `ProcessPoolExecutor`, so the thread→process upgrade is one identifier.

**Case study: Robots and Cutlery — the race-condition signature.** A 10-bot kitchen-inventory test:

```
python cutlery_test.py 100     → inventory balances, reproducibly   (test passes)
python cutlery_test.py 10000   → knives=96 forks=108, then 112/96…  (fails, differently each run)
```

Diagnostic pattern to memorize: *simple logic + small test reproducibly passes + large/loaded test fails non-reproducibly by varying amounts* ⇒ race condition. Root cause: `self.knives += knives` compiles to three interpreter steps —

```
1. read self.knives into a temporary
2. add knives to the temporary
3. write the temporary back to self.knives
```

— and the OS can preempt between any two steps; thread B's read-modify-write interleaved with A's erases A's update. Two fixes:

1. Lock every modification:

   ```python
   def change(self, knives, forks):
       with self.lock:
           self.knives += knives
           self.forks += forks
   ```

   But this requires *knowing every place* state is shared — including inside third-party libraries — and **the source code gives no hint where switches occur** (preemption is invisible in the text).
2. The async fix (Example B-1, `CoroBot`): one thread; `+=` contains no `await`, so no context switch can occur mid-update — no lock needed, the test passes at any scale, and the safety is *visible in the source*.

**Await-visibility corollary** (the book's central safety claim): in asyncio, the only places execution can switch are `await` keywords. Reviewing for races = scanning for shared-state operations that *span* an await. This also states the inverse trap: a read-modify-write **with an await in the middle** has exactly the threaded race again.

## ch-3 — Asyncio Walk-Through {#ch-3}

**Two audiences.** The asyncio API serves *end-user developers* and *framework designers*; the official docs conflate them, which is why the module looks sprawling. End users need a small subset.

**The Tower of Asyncio** (author's tier model; bold = end-user tiers):

| Tier | Concept | Implementation |
|---|---|---|
| **9** | Network: streams | `StreamReader/StreamWriter`, `open_connection()`, `start_server()` |
| 8 | Network: TCP & UDP | `Protocol` |
| 7 | Network: transports | `BaseTransport` |
| **6** | Tools | `asyncio.Queue` |
| **5** | Subprocesses & threads | `run_in_executor()`, `asyncio.subprocess` |
| 4 | Tasks | `asyncio.Task`, `asyncio.create_task()` |
| 3 | Futures | `asyncio.Future` |
| **2** | Event loop | `asyncio.run()`, `BaseEventLoop` |
| **1** (base) | Coroutines | `async def`, `async with`, `async for`, `await` |

Curio and Trio build on Tier 1 alone; **uvloop** swaps in at Tier 2 only (`asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())`) — the spec/implementation split is deliberate. Prototype at Tier 9 (streams); drop to protocols only when you know you need fine-grained control.

**Quickstart = 7 functions** (Selivanov): start the loop (`asyncio.run(main())`), call async/await functions, create tasks (`asyncio.create_task()`), wait for many (`gather()`), run blocking code (`run_in_executor()`), close the loop. Everything else is framework-designer surface.

```python
import asyncio

async def main():
    print('Hello!')
    await asyncio.sleep(1.0)
    print('Goodbye!')

asyncio.run(main())          # creates, runs, drains, and closes the loop
```

The manual equivalent (what `run()` hides — you need it for the shutdown discussion below):

```python
loop = asyncio.get_event_loop()
task = loop.create_task(main())
loop.run_until_complete(task)          # blocks main thread; other tasks also run
pending = asyncio.all_tasks(loop=loop)
for t in pending:
    t.cancel()
group = asyncio.gather(*pending, return_exceptions=True)
loop.run_until_complete(group)
loop.close()                           # closed loop is gone for good
```

**Coroutine mechanics** (know it to debug it, never call it yourself):
- `async def f()` is a *function*; calling it returns a *coroutine object* — nothing runs yet (mirrors generator functions: `iscoroutinefunction(f)` vs `iscoroutine(f())`).
- The loop drives coroutines with `coro.send(None)`; a returning coroutine raises `StopIteration` whose `.value` carries the return value:

  ```python
  coro = f()
  try:
      coro.send(None)
  except StopIteration as e:
      print('The answer was:', e.value)
  ```
- Cancellation is `coro.throw(asyncio.CancelledError)` injected at the current `await` point. **Task cancellation is ordinary exception raising** — nothing more magical.
- A coroutine *can* catch `CancelledError` and keep awaiting ("Nope!" example) — legal and wrong. **Cancellation is a directive, not a notification**: do cleanup only, then let it propagate.

**`await` accepts** exactly: a coroutine object, or any object whose `__await__()` returns an iterator. Only legal inside `async def`.

**Loop access**: inside a coroutine use `asyncio.get_running_loop()` (always correct; can only be called while a loop runs). `asyncio.get_event_loop()` is the discouraged legacy path — same-thread only; in a new thread it fails unless you `new_event_loop()` + `set_event_loop()`. Framework code should accept a `loop` parameter; application code should not thread loops through signatures.

**Task vs Future**: a `Future` is a loop-aware completion toggle (`done()`, `set_result()`, `result()`, `cancel()`, callbacks). A `Task` (subclass) additionally wraps a coroutine — loop-aware *and* coroutine-aware. Since Python 3.8, `set_result()` on a Task raises `RuntimeError`: a Task's result comes only from its coroutine's return. Critical operational fact: **`run_in_executor()` returns a Future, not a Task**, so it never appears in `asyncio.all_tasks()` — the root of the shutdown trap below.

**`create_task()` vs `ensure_future()`**: `ensure_future(x)` is type coercion for framework authors (coroutine → wrapped in Task; Future/Task → passed through unchanged — a `listify()` for awaitables; Guido: the only end-user-visible reason is calling Future-only methods like `cancel()` on a maybe-coroutine). The author names `ensure_future` a chief cause of asyncio's learnability problem. **Application code: always `asyncio.create_task()`** (3.7+).

**Async context managers**: `__aenter__`/`__aexit__`, or (preferred) `@asynccontextmanager` on an async generator. Rule: use `async with` only when enter/exit must await; a resource with non-blocking setup/teardown takes a plain `with` even inside async code.

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def web_page(url):
    data = await download_webpage(url)   # or: await loop.run_in_executor(None, download_webpage, url)
    yield data
    await update_stats(url)

async with web_page('example.com') as data:
    process(data)
```

For unmodifiable blocking calls (e.g., `requests` — async support usually cannot be retrofitted at the socket level), the executor variant in the comment is the pattern — and never forget the `await` on the exit-side executor call, or the manager proceeds before it completes.

**Async iteration**: `def __aiter__()` (not async) returning an object with `async def __anext__()` raising `StopAsyncIteration`; or — much simpler — an **async generator** (`async def` + `yield`):

```python
async def one_at_a_time(redis, keys):
    for k in keys:
        value = await redis.get(k)      # loop runs other tasks during each fetch
        yield value

async for value in one_at_a_time(redis, keys):
    await do_something_with(value)
```

Payoff: process unbounded data with a plain-looking loop, one chunk in memory at a time. Async comprehensions: `[x async for x in agen()]`, dict/set forms likewise; note `async for` is what makes a comprehension async — `await f(x)` inside is an independent, orthogonal feature (legal anywhere inside `async def`).

### Startup / shutdown / cancellation procedures

**Startup** is simple: one `main()` coroutine, `asyncio.run(main())`. Servers: `start_server(cb, host, port)` → `async with server: await server.serve_forever()`.

**What `asyncio.run()` does at exit** (know this sequence; every shutdown bug below is a violation of it):
1. Runs `main()` to completion via `run_until_complete()`.
2. Collects all still-pending tasks (`asyncio.all_tasks()`).
3. Cancels them — raises `CancelledError` inside each at its current `await`.
4. Gathers them with `return_exceptions=True` and runs the group to completion.
5. Closes the loop (a closed loop is gone for good; a merely stopped one can restart).

**"Task was destroyed but it is pending!"** = some task was never given steps 2–4 before `loop.close()`. With manual loop management you must perform cancel + gather + run_until_complete yourself; with `asyncio.run()` it means you created work the collector couldn't see (executor Futures, or tasks spawned during shutdown).

**Why `return_exceptions=True` in the shutdown gather** (the causal chain): `run_until_complete()` re-raises any exception from its future → an unhandled subtask exception (including `CancelledError` from tasks that don't handle it) escapes the group future → the loop stops early → remaining tasks never finish. With `return_exceptions=True`, exceptions become entries in the results list and all tasks run to completion. Cost: errors are now silently in-band — scan the results list for `Exception` instances and log them.

**Cancellation-handler rule**: do not `create_task()` inside an `except CancelledError:` block. The canonical bug (Telnet-demo, Example 3-31):

```python
except asyncio.CancelledError:
    msg = 'Connection dropped!'
    asyncio.create_task(send_event(msg))   # BUG: born after run()'s snapshot
# → "Task was destroyed but it is pending! task: <Task pending ... send_event ...>"
```

The new task is created *after* the shutdown snapshot (step 2) and will be destroyed pending. If unavoidable, `await` the new task within the same function scope. Also: catch `CancelledError`, clean up, re-raise/return — never absorb it and continue awaiting.

**Signal procedure** (SIGTERM must be handled — `kill` sends TERM by default, and TERM/INT is your only chance before KILL, which cannot be handled):
1. Inside `main()`: `loop = get_running_loop()`; `loop.add_signal_handler(sig, handler, sig)` for SIGINT and SIGTERM. (Setting a SIGINT handler *replaces* `KeyboardInterrupt`.)
2. In `handler`: cancel all tasks (under `asyncio.run()`, do **not** `loop.stop()` — cancelling `main()`'s task lets `run()`'s own cleanup take over).
3. Make shutdown idempotent against repeated signals: `loop.remove_signal_handler(SIGTERM)`; for SIGINT set a no-op `loop.add_signal_handler(SIGINT, lambda: None)` — removing it would *restore* `KeyboardInterrupt` and re-arm Ctrl-C. (`add_signal_handler` is really *set*: one handler per signal.)
4. `main()`'s `except CancelledError:` block may then run multi-second cleanup (close sockets, notify peers) safely; new signals during it do nothing.

```python
def handler(sig):
    loop = asyncio.get_running_loop()
    for task in asyncio.all_tasks(loop=loop):
        task.cancel()                                  # not loop.stop()
    loop.remove_signal_handler(SIGTERM)                # step 3: idempotent
    loop.add_signal_handler(SIGINT, lambda: None)      # suppress further Ctrl-C

async def main():
    loop = asyncio.get_running_loop()
    for sig in (SIGTERM, SIGINT):
        loop.add_signal_handler(sig, handler, sig)
    try:
        while True: ...
    except asyncio.CancelledError:
        await slow_cleanup()    # safe: repeat signals are now no-ops
```

**Executor-shutdown trap (Python ≤3.8)**: an executor job that outlives the async tasks dies with `RuntimeError: Event loop is closed` — `run_in_executor()`'s Future is invisible to `asyncio.run()`'s task collection, and `loop.close()` doesn't wait for executor jobs. Three escalating fixes:
- **A — try/finally await** (simplest; forces a try/finally at every call site):

  ```python
  future = loop.run_in_executor(None, blocking)
  try:
      ...
  finally:
      await future
  ```
- **B — wrap the Future in a Task** so it joins the shutdown gather:

  ```python
  async def make_coro(future):
      try:
          return await future
      except asyncio.CancelledError:
          return await future      # keep waiting even when cancelled

  asyncio.create_task(make_coro(loop.run_in_executor(None, blocking)))
  ```
- **C — own the loop and executor** (fully general): create your own `Executor`, `loop.set_default_executor(executor)`, run the manual cancel/gather sequence, then `executor.shutdown(wait=True)` before `loop.close()`.
- Python 3.9+: `asyncio.run()` waits for executor shutdown correctly; the trap ages out but the Future-vs-Task distinction does not.

**Test shutdown explicitly.** The author's blunt advice: graceful shutdown is among the hardest parts of network programming, strategies differ per app — put clean-shutdown tests in your automated suite (his `aiorun` package exists because of this).

## ch-4 — Libraries & Case Studies {#ch-4}

**Framing**: every case study is a complete program because *application lifetime management is a core consideration* of async correctness — fragments hide the startup/shutdown half of the problem.

**Streams + message framing.** TCP is a byte stream, not messages; smallest viable protocol is a 4-byte big-endian size prefix then payload:

```python
async def read_msg(stream: StreamReader) -> bytes:
    size = int.from_bytes(await stream.readexactly(4), 'big')
    return await stream.readexactly(size)

async def send_msg(stream: StreamWriter, data: bytes):
    stream.writelines([len(data).to_bytes(4, 'big'), data])
    await stream.drain()
```

**Case study: message broker, naive → improved** (the chapter's transferable design lesson):
- *Naive*: the per-client receive loop also fans out sends: `await gather(*[send_msg(w, data) for w in subscribers])`. Flaw: distribution completes at the pace of the **slowest subscriber**, and no new messages can be received meanwhile.
- *Improved*: **decouple receiving from sending.** Per-client send `Queue` drained by a dedicated `send_client()` coroutine; per-channel `Queue(maxsize=10)` drained by a `chan_sender()` coroutine. Receive loop only enqueues and returns to the socket:

  ```python
  # receive loop: enqueue and go straight back to reading
  await CHAN_QUEUES[channel_name].put(data)

  # chan_sender(): fan out to per-client queues, never to sockets directly
  for writer in subscribers:
      if not SEND_QUEUES[writer].full():     # explicit drop policy
          await SEND_QUEUES[writer].put(msg)
  ```
- **Back-pressure**: a bounded channel queue makes a fast producer block at `put()`, which stops socket reads, which pushes back to the sending client via TCP. Alternatively **drop policy**: if a subscriber's send queue is full, skip them — losing data is a legitimate, explicit choice for slow consumers.
- **Queue-sentinel shutdown**: terminate the sender task by putting `None` on its queue and `await send_task` — *not* by cancelling it — so already-queued messages flush first. `send_client()` suppresses `CancelledError` inside its loop precisely so only the sentinel ends it. (↔ aligned with release-it's bounded-queues/back-pressure stability patterns; Hattingh derives the same move from single-process queue mechanics.)
- Point-to-point vs pub-sub on the same broker: `/queue`-prefixed channels `rotate()` the subscriber deque and send to one subscriber (round-robin work sharing, O(1) rotation); all other channels fan out to everyone.

**Queues across the thread boundary**: `queue.Queue` blocks the loop; `asyncio.Queue` can't be called from threads; neither bridges the two. **Janus** exposes one queue with both faces:

```python
queue = janus.Queue()
# thread side (inside run_in_executor job):
queue.sync_q.put(item)
# coroutine side:
data = await queue.async_q.get()
```

Prefer short executor jobs that need no queue at all; reach for Janus when jobs are long-lived producers.

**aiohttp**: client + server + WebSocket; hides all loop/task machinery (`web.run_app(app)`) — the model for how asyncio frameworks should feel. Long-lived background coroutines hook into `app.on_startup.append(...)` / `app.on_cleanup.append(...)` (the news-scraper's collector task is created in startup and cancelled-then-awaited in cleanup). Client idiom: `async with ClientSession() as s: async with s.get(url) as resp: data = await resp.read()`.

**ZeroMQ + asyncio**: ØMQ "smart sockets" already do message framing, auto-reconnect, and buffering-while-disconnected (broker features in the socket; either end may `bind()` or `connect()`). What asyncio adds is *structure*: the threaded version needs a `zmq.Poller` loop with an if-block per socket (ØMQ sockets are not thread-safe); the asyncio version gives **each socket its own coroutine**:

```python
from zmq.asyncio import Context
context = Context()

async def do_receiver():
    receiver = context.socket(zmq.PULL)
    receiver.connect("tcp://localhost:5557")
    while message := await receiver.recv_json():
        print(f'Via PULL: {message}')
# one such coroutine per socket type; gather() them in main()
```

The poller disappears into the event loop, each handler is self-contained (own file, own logic), and the same refactor in threads would reintroduce race risk. The APM case study (PUB apps → SUB collector → SSE browser feed, `WeakSet` of per-client queues so disconnected clients self-evict) shows any layer restarting with zero reconnect-handling code.

**asyncpg**: fastest Postgres client by speaking the binary protocol directly; prepared statements; auto type-mapping SQL↔Python (`date` → `datetime.date`). Always use `$1, $2` parameters — never string interpolation/concatenation into SQL.

```python
pool = await asyncpg.create_pool(dsn)
pk   = await conn.fetchval('INSERT INTO users(name) VALUES($1) RETURNING id', name)
row  = await conn.fetchrow('SELECT * FROM users WHERE id = $1', pk)   # Record
ok   = await conn.execute('UPDATE users SET dob=$1 WHERE id=$2', d, pk) == 'UPDATE 1'
await conn.add_listener('chan_patron', callback)   # callback(conn, pid, channel, payload)
```

`fetchval()` for scalar returns (the `RETURNING id` idiom), `fetchrow()`/`fetch()` return `Record`s, `execute()` returns a status string you can assert.

**Case study: cache invalidation by DB push** (Sanic + asyncpg + LISTEN/NOTIFY):
1. Postgres triggers on the table call `pg_notify('chan_patron', json_payload)` for INSERT/UPDATE/DELETE, payload carrying `old`/`new`/`diff`.
2. Every app instance holds a long-lived listener connection: `conn.add_listener(channel, callback)`.
3. The callback updates each instance's in-memory LRU cache.
4. Only the read path consults the cache; **write paths never update the cache** — the DB notification does, so all horizontally-scaled instances converge (a second instance served fresh data from cache on its *first* request after another instance's write).
5. Cost note: one listener connection per channel ties up a Postgres worker each — multiplex channels over one connection in real designs.
Framework lifecycle again: DB pool creation in Sanic's `before_server_start` listener, disconnect in `after_server_stop`.

**aiofiles**: disk access blocks the loop too, and it matters at high concurrency; `aiofiles` wraps file ops in threads (Python releases the GIL during file I/O). `async with aiofiles.open(...) as f: await f.read()`.

**Twisted**: not replaced by asyncio — it carries production-grade implementations of dozens of protocols (SSH, IMAP, IRC, DNS, SMTP, XMPP…). Interop: `from twisted.internet import asyncioreactor; asyncioreactor.install()` **before** importing `reactor`; then native `async def`/`await` work in Twisted code (`ensureDeferred` ≈ `create_task`, `reactor.run()` ≈ `run_forever()`).

## ch-5 — Concluding Thoughts & History {#ch-5}

**The 20-year lesson**: single-threaded async socket handling existed in Python 1.5.2 (**asyncore**, 1996; deprecated 3.6 — "obsolete… for all intents and purposes"). What was missing for two decades was **language syntax**: generators (`yield`, 2.2/2001) → coroutine-ish generators (`send()`/`throw()`, 2.5/2005) → `yield from` (3.3) → the `asyncio` module (3.4, PEP 3156 — deliberately a common event-loop base Twisted/Tornado could standardize on) → native `async`/`await` (3.5, PEP 492) → `asyncio.run()` and `create_task()` (3.7). Corollary for the present: syntax and callback-free linear layout are the durable value; specific APIs keep churning.

**Trajectory advice**: as the ecosystem matures, end users will mostly program against library APIs (aiohttp, Sanic, asyncpg) rather than raw asyncio; learn the raw layer to debug lifecycle issues, not to build on directly.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Choosing a concurrency model for I/O-bound, many-connection work | Prefer async only for the two real reasons: race-safety and socket scale | Speed is a myth — threads benchmark slightly faster per request | src: ch-1 |
| Plan justifies asyncio with "it'll be faster" / "fixes the GIL" | Reject the justification; re-derive from the two real reasons | Asyncio is single-threaded: GIL irrelevant, no multicore, no speedup | src: ch-1 |
| CPU-bound or shared-memory parallel computation in an async design | Use processes/threads (numpy-class libs, ProcessPoolExecutor), not coroutines | Cooperative single-thread cannot use multiple cores | src: ch-1 |
| Distributed/multi-instance shared resource (DB row, cache) in async app | Still design for races — asyncio only removed intra-process ones | Inter-process races unaffected by the event loop | src: ch-1 |
| Any potentially long synchronous step inside a coroutine | Every task on a loop must be short; long steps starve all others | One "chatty guest" flops the soufflé — the loop's fatal constraint | src: ch-1 |
| Threaded code touching module/global state from workers | Pass all data through `submit()`; no global access in workers | Shared state + preemption = the hardest bug class | src: ch-2 |
| Small test passes reproducibly; large/loaded test fails by varying amounts | Diagnose as race condition, not flaky test | Non-deterministic interleaving only bites under load | src: ch-2 |
| Read-modify-write on shared state in threads (`x += n`, check-then-set) | Lock it, or move to single-threaded async | `+=` is read/add/write; preemption between steps loses updates | src: ch-2 |
| Reviewing async code for races | Scan for shared-state operations spanning an `await` | Awaits are the only switch points; a mid-operation await = threaded race again | src: ch-2 |
| >~thousands of threads planned | Redesign: coroutines or select-driven I/O | 8 MB stack/thread, >5k threads context-switch throughput cliff | src: ch-2 |
| Blocking call (`time.sleep`, `requests`, sync DB driver, disk) in `async def` | `await loop.run_in_executor(None, func, ...)` or async-native lib | The gravest sin: one blocking call halts every task on the loop | src: ch-3 |
| Application code calls `asyncio.ensure_future()` | Use `asyncio.create_task()` | `ensure_future` is framework-author type coercion; chief source of API confusion | src: ch-3 |
| Loop access inside a coroutine via `get_event_loop()` | Use `asyncio.get_running_loop()` | Legacy call is thread-sensitive; running-loop variant always correct | src: ch-3 |
| `except asyncio.CancelledError:` that continues awaiting / doesn't re-raise | Clean up, then let it propagate | Cancellation is a directive to exit, not an event to absorb | src: ch-3 |
| `create_task()` inside a `CancelledError` handler | Avoid; if unavoidable, `await` the task in the same scope | Task born after shutdown's snapshot is destroyed pending | src: ch-3 |
| Manual shutdown path: gather without `return_exceptions=True` | Set it, then scan results for `Exception` instances | First unhandled subtask exception stops the loop before others finish | src: ch-3 |
| "Task was destroyed but it is pending!" in logs | Find work created outside the cancel→gather→complete sequence | Some task never got steps 2–4 of the `asyncio.run()` exit sequence | src: ch-3 |
| Service handles only Ctrl-C / `KeyboardInterrupt` | Add SIGTERM handling; make shutdown idempotent under repeated signals | `kill` sends TERM; second signal mid-cleanup must be a no-op (SIGINT→`lambda: None`, remove SIGTERM) | src: ch-3 |
| Under `asyncio.run()`, signal handler calls `loop.stop()` | Cancel all tasks instead | Stopping the loop directly aborts `run()`'s own cleanup sequence | src: ch-3 |
| `run_in_executor()` job may outlive async tasks (Py ≤3.8) | try/finally-await it, wrap it in a Task, or own the executor and `shutdown(wait=True)` | Executor returns a Future — invisible to `all_tasks()`, unwaited at close | src: ch-3 |
| New long-running async service in test plan | Add explicit clean-shutdown tests | Graceful shutdown strategies are app-specific and regress silently | src: ch-3 |
| `async with` on a manager whose enter/exit never awaits | Use plain `with` | Async managers are only for awaiting in `__aenter__`/`__aexit__` | src: ch-3 |
| Custom `__aiter__`/`__anext__` class for straightforward iteration | Write an async generator instead | Same semantics, fraction of the code | src: ch-3 |
| Fan-out/send logic inline in a receive loop | Decouple: per-consumer queue + dedicated sender coroutine | Otherwise the slowest consumer throttles receipt for everyone | src: ch-4 |
| Unbounded queue between producer and consumers | Bound it (`maxsize`); choose block (back-pressure) or drop, explicitly | Bounded `put()` propagates pressure to the socket; full queue + drop is a valid policy | src: ch-4 |
| Shutting down a queue-draining worker by `task.cancel()` | Send a sentinel (`None`) and await the worker | Cancellation discards queued items; sentinel lets the queue flush | src: ch-4 |
| `queue.Queue` in a coroutine, or `asyncio.Queue` touched from a thread | Match queue to domain; bridge with Janus (`sync_q`/`async_q`) | Blocking `get()` halts the loop; asyncio queue isn't thread-safe | src: ch-4 |
| Raw TCP messaging design | Frame messages (4-byte size prefix) or use ØMQ smart sockets | TCP is a byte stream; "messages" are your protocol's job | src: ch-4 |
| SQL built by f-string/concat in any driver | Use driver parameters (`$1, $2` in asyncpg) | String-built SQL is an injection risk, full stop | src: ch-4 |
| Multi-instance app caching DB reads | Invalidate via DB push (LISTEN/NOTIFY): writes don't touch cache, notifications do | Write-path cache updates can't reach other instances' caches | src: ch-4 |
| Framework app (aiohttp/Sanic) spawning background coroutines ad hoc | Register via the framework's startup/cleanup hooks | Frameworks own the loop lifecycle; orphan tasks die pending | src: ch-4 |
| High-concurrency service doing direct file I/O in coroutines | `aiofiles` (thread-wrapped; GIL released during file ops) | Disk blocks the loop just like network | src: ch-4 |
| Event-loop throughput bottleneck, code unchanged | Swap in uvloop at Tier 2 | Loop implementation is pluggable below the API you use | src: ch-3 |

## Anti-patterns

- **Blocking the loop** — detection: `time.sleep`, `requests.*`, sync DB drivers, un-wrapped file I/O, or any long pure-CPU stretch inside `async def`. One occurrence stalls *every* connection ("the most grave sin of event-based programming").
- **Cancellation swallowing** — detection: `except asyncio.CancelledError:` whose body loops, awaits new work, or returns normally without re-raising. The task becomes unkillable during shutdown.
- **Shutdown-spawned orphan** — detection: `create_task()` (or fire-and-forget coroutine) inside a `CancelledError` handler or cleanup hook. Symptom: "Task was destroyed but it is pending!".
- **`ensure_future()` in application code** — detection: any non-framework call site. Works, but signals a copy-pasted mental model; use `create_task()`.
- **Naive fan-out** (`gather()` of sends inside the receive loop) — detection: `await gather(*[send(...)])` in the same coroutine that reads the socket. Slowest-subscriber convoy.
- **Global mutable state in thread workers** — detection: executor/thread target reading or writing module-level objects. The cutlery bug; unfixable-by-inspection because preemption points are invisible.
- **Race spanning an await** — detection: read of shared state, then `await`, then dependent write. Asyncio's safety guarantee is void across that gap.
- **Kill-by-cancel of queue consumers** — detection: `worker_task.cancel()` where the worker drains a queue. In-flight items are silently dropped; use a sentinel.
- **Signal-handler re-entry** — detection: SIGINT/SIGTERM handler that can run twice (no handler removal/no-op swap). Second Ctrl-C restarts shutdown mid-cleanup.
- **Hand-rolled loop lifecycle under a framework** — detection: `get_event_loop()`/`run_until_complete()`/`loop.close()` in aiohttp/Sanic/Twisted app code instead of the framework's run function and hooks.

## Applicability & exemptions

- **Scope is I/O-bound network concurrency only.** The author explicitly excludes other domains of preemptive threading — GUI toolkits, embedded, scientific compute — where trade-offs differ entirely. Do not cite this book against threads outside network servers.
- **Threads/processes legitimately beat asyncio when**: (a) CPU-bound work needs multiple cores with shared memory (numpy-class; "no competitor to this programming model"); (b) the codebase depends on blocking third-party libraries you cannot modify (SQLAlchemy-era ORMs, `requests`) — executors are the bridge, but a mostly-blocking app may as well be threaded; (c) raw per-request latency matters more than connection count (threaded solutions benchmark slightly faster); (d) concurrency is modest (tens–hundreds of tasks) and the team knows threads — Beazley's own advice opens ch-2: "you should probably be programming with threads."
- **Asyncio's race-safety guarantee is narrow**: intra-process, between awaits, single loop thread. It says nothing about distributed races, executor threads you spawn, or state shared across an `await`. Reviewers must not wave off race concerns in async code categorically.
- **Version-scoped rules**: the executor-shutdown trap is Python ≤3.8 (`asyncio.run()` waits from 3.9); `get_running_loop()` needs 3.7+ (usable pattern from 3.8); `Task.set_result()` prohibition is 3.8+. Pre-3.7 codebases legitimately use `loop.create_task()`/`ensure_future`-era idioms — don't flag history as error, migrate it.
- **Case-study code is didactic, not production**: the message broker (O(n) subscriber removal, unbounded channel-queue growth with no subscribers, forever-lived `chan_sender`s) and the one-connection-per-LISTEN-channel design are explicitly flagged by the author as simplifications. Extract the design moves, not the listings.
- **Drop-vs-block is a policy choice**: the broker drops messages for full subscriber queues. Only valid where the domain tolerates loss (metrics, live feeds) — not for money or commands.
- **Language transfer caveat**: mechanics (`create_task`, `gather`, signal API, Janus) are CPython-specific; the portable layer is the decision rules. Node hides loop lifecycle entirely; Go's scheduler is preemptive — the "await-visibility" safety argument applies only to runtimes with explicit yield points.

## Candidate lexicon rows

| py: blocking call (`time.sleep`, `requests`, sync DB/file I/O) or long CPU stretch inside `async def` | **Never block the event loop** — one blocking call inside a coroutine stalls every task the loop is serving | Does every call in this coroutine either await, finish in microseconds, or run via `run_in_executor`/async-native lib? | blocker | review | src: using-asyncio-in-python ch-3 |
| py: read of shared state, then `await`, then dependent write in the same coroutine | **No shared read-modify-write across an await** — awaits are the only context-switch points, so spanning one reintroduces the full threaded race | Can another task observe or mutate this state while we're suspended at the await in the middle? | blocker | review | src: using-asyncio-in-python ch-2 |
| py: `except asyncio.CancelledError:` that returns normally, loops, or starts new awaits | **Cancellation is a directive** — clean up and propagate; absorbing it makes the task unkillable and hangs shutdown | After cleanup, does CancelledError still propagate out of this handler? | blocker | review | src: using-asyncio-in-python ch-3 |
| py: `asyncio.create_task()` inside a `CancelledError` handler or shutdown hook | **No orphan tasks during shutdown** — tasks created after the cancel/gather snapshot are destroyed pending | Is the newly created task awaited within this same scope before it returns? | should | review | src: using-asyncio-in-python ch-3 |
| py: manual shutdown path calling `gather()` on pending tasks without `return_exceptions=True` | **Gather with return_exceptions at shutdown** — the first unhandled subtask exception stops the loop before remaining tasks finish | Are subtask exceptions captured as results (and then scanned/logged) rather than allowed to abort the group? | should | write | src: using-asyncio-in-python ch-3 |
| py: `loop.run_in_executor()` result not awaited and job may outlive async tasks (≤3.8) | **Executor jobs are Futures, not Tasks** — invisible to `all_tasks()`, so `asyncio.run()` closes the loop under them | Who awaits this future before the loop closes (finally-await, Task wrapper, or owned executor with `shutdown(wait=True)`)? | should | review | src: using-asyncio-in-python ch-3 |
| py: plan proposes asyncio "for speed" or "because of the GIL", or coroutines for CPU-bound work | **Asyncio buys safety and socket scale, nothing else** — threads benchmark slightly faster per request; CPU work needs processes/multicore | Is the workload I/O-bound with high connection counts, or race-prone shared state — the only two wins? | judgment | plan | src: using-asyncio-in-python ch-1 |
| py: send/fan-out logic inline in a socket receive loop (`await gather(*sends)` before next read) | **Decouple receive from send** — per-consumer queues plus dedicated sender coroutines, else the slowest consumer throttles everyone | If one consumer stalls forever, does the receive loop keep reading? | should | plan | src: using-asyncio-in-python ch-4 |
| py: unbounded queue between producer and consumer coroutines | **Bound the queue, pick a policy** — `maxsize` gives back-pressure at `put()`; explicit drop is legal for loss-tolerant streams | What happens at the put site when this queue is full — block, drop, or grow without limit? | should | review | src: using-asyncio-in-python ch-4 |
| py: `queue.Queue` used in a coroutine, or `asyncio.Queue` called from a thread | **Match the queue to the concurrency domain** — blocking `get()` halts the loop; asyncio queues aren't thread-safe; bridge with a dual-face queue (janus) | Is each queue endpoint (put/get) in the domain the queue class was built for? | blocker | write | src: using-asyncio-in-python ch-4 |
| py: long-running service whose only shutdown path is `KeyboardInterrupt`/Ctrl-C | **Handle SIGTERM and make shutdown idempotent** — `kill` sends TERM; a second signal mid-cleanup must not restart shutdown (remove SIGTERM handler, set SIGINT to no-op) | What happens if the process receives TERM, then INT again two seconds into cleanup? | should | plan | src: using-asyncio-in-python ch-3 |
| py: small concurrency test passes reproducibly while the loaded/scaled run fails by different amounts each time | **Nonreproducible-under-load = race** — treat as a shared-state race condition, not flaky infrastructure | What shared state do concurrent workers read-modify-write, and where can execution switch mid-operation? | should | review | src: using-asyncio-in-python ch-2 |
