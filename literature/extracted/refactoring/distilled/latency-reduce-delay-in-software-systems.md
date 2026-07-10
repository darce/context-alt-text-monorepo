# Latency: Reduce Delay in Software Systems — distilled

> **Source**: Pekka Enberg, *Latency: Reduce delay in software systems*, Manning, 2026 · extracted from `../Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory that treats latency as a first-class engineering target across the whole stack — physics → NIC → kernel → allocator → consistency model → UX perception. Supplies the canonical latency-constants table and human-perception thresholds for back-of-envelope budgeting, the measurement discipline (latency is a distribution; **coordinated omission**; observer effect), and an ordered technique catalog (colocation → replication → partitioning → caching → eliminating work → wait-free sync → concurrency → async → predictive) with explicit selection criteria and scale exemptions. DDIA covers replication/partitioning semantics more deeply; Release It! covers failure containment; this book supplies the *latency math and technique-ordering* neither provides.

## Chapter map

- ch-1 — Introduction: what latency is; latency constants; human-perception thresholds; latency vs bandwidth/throughput/energy
- ch-2 — Modeling & measuring: Little's law, Amdahl's law; distribution not average; tail-at-scale fanout math; compounding; coordinated omission; eCDF
- ch-3 — Colocation: geographic & last-mile latency; edge/CDN; kernel network stack; TCP_NODELAY; kernel bypass; NUMA; embedded-DB case study
- ch-4 — Replication: consistency models vs latency; nines table; single/multi/leaderless; sync vs async; state machine replication; VSR
- ch-5 — Partitioning: horizontal/vertical/hybrid; logical (functional/geo/user/time); request routing; hot partitions vs skewed workloads
- ch-6 — Caching: when caching over other techniques; strategies; hit-ratio math; working set; LRU/LFU/FIFO/SIEVE; TTL; materialized views
- ch-7 — Eliminating work: algorithmic complexity; serialization formats; allocation/GC; virtual memory & paging; OS overhead; precomputation; flame graphs
- ch-8 — Wait-free synchronization: lock costs under contention; priority inversion/convoying/deadlock; atomics; memory barriers; progress conditions; SPSC queue
- ch-9 — Exploiting concurrency: concurrency vs parallelism; concurrency models; data/task parallelism; isolation levels vs latency; 2PL vs MVCC
- ch-10 — Asynchronous processing: hides latency, doesn't reduce it; event loop; batching; hedging; deferring; pools; backpressure
- ch-11 — Predictive techniques: prefetching (pattern/semantic); optimistic updates & clocks/CRDTs; speculative execution; overprovisioning/prewarming

## ch-1 — Introduction {#ch-1}

**Latency** = the time delay between a cause and its observed effect. It is context-specific (end-to-end page load vs NIC-to-userspace packet latency) and it exists at every layer; the observed number is the composition of all layers below you.

### Canonical latency constants (memorize for back-of-envelope budgets)

| Operation | Time | Order of magnitude (ns) |
|---|---|---|
| CPU cycle (3 GHz) | 0.3 ns | 10⁻¹ |
| L1 cache access | 1 ns | 10⁰ |
| LLC access / 40 Gbps NIC wire | 10–40 ns | 10¹ |
| DRAM access | 100 ns | 10² |
| NIC PCIe latency | 1,000 ns | 10³ |
| NVMe disk access | 10 µs | 10⁴ |
| SSD disk access | 100 µs | 10⁵ |
| NYC ↔ London round trip | 60 ms | 10⁷ |

- Physics is the floor: light ≈ 30 cm per nanosecond in wire (Grace Hopper's wire). Vacuum straight-line NYC→London RTT = 38 ms; best commercial fiber ≈ 60 ms; typical user 100–150 ms. No code change beats geography.
- Rule of thumb from the table: crossing each boundary (cache → DRAM → PCIe device → disk → WAN) costs roughly an order of magnitude or more. Every avoided boundary crossing is the cheapest optimization available.

### Human-perception thresholds (design targets)

| Category | Budget | Perception |
|---|---|---|
| Immediate | ≤ 0.1 s | No perceptible delay |
| Instant | ≤ 1 s | Noticeable but feels instantaneous |
| Slow | ≥ 10 s | Feels slow; users assume breakage without feedback |

- Business evidence: Akamai 2017 — +100 ms page load → −7 % conversions; Google 2006 — +1 s → −20 % engagement; > 3 s load → ~50 % abandonment.
- If an operation inherently exceeds ~10 s, stop optimizing latency and add feedback instead (progress bar; LLM token streaming) — the perception problem, not the latency, is what you can fix.
- **Hard real-time**: missed deadline = system failure (pacemaker, vehicle sensor). **Soft real-time**: missed deadline degrades quality only (A/V streaming). This book targets general low-latency, not certified hard-real-time.

### Latency vs bandwidth, throughput, energy

- Bandwidth = channel capacity; throughput = achieved rate. **You can always add bandwidth (more links, more concurrency); bad latency you are stuck with** — it can only be fixed by fixing the path or the architecture.
- Pipelining (laundry example): serial wash+dry = 90 min latency, 1/90 loads/min. Pipelined = 120 min latency (+33 %) but 1/60 loads/min throughput (+67 %). Pipelining/batching trades per-item latency for throughput — know which you are optimizing.
- Energy: busy-polling gives lowest, most predictable latency and can beat sleep/wake on energy when traffic is frequent and predictable; for sporadic traffic sleep/wake wins energy at the cost of wake-up latency spikes. Low-latency deployments commonly disable CPU frequency scaling / power management.

## ch-2 — Modeling and measuring latency {#ch-2}

### 2.1 Laws

- **Little's law**: `N = X · R` (concurrency = throughput × mean latency), i.e. `R = N / X`. Uses: size expected latency from load (1,000 req/s × 50 ms ⇒ 50 in-flight requests); halve latency by halving queue length or doubling throughput; derive a concurrency ceiling (20 ms service time at 1,000 req/s ⇒ ~50 concurrent before latency inflates). Limitation: assumes latency and throughput independent; real systems see latency rise with concurrency (locks, context switches), so the law *underestimates* concurrency needs.
- **Amdahl's law**: `Speedup = 1 / ((1−P) + P/N)` for parallelizable fraction P on N units. P=0.5 caps at 2×; P=0.3 example: 2 cores → 1.2×, 8 → 1.35×, ceiling 1.4×. Adding cores does not reduce latency when the serial fraction dominates — measure P before parallelizing.

### 2.2 Latency is a distribution — percentile math traps

- **Never report a single number.** The average is just the inverse of throughput (via Little's law) and hides variability; min/max show only the two extremes. Report p50/p95/p99/p99.9 (+p100).
- **Tail at scale** (Dean & Barroso 2013): a service that fans out to N sub-requests in parallel is as slow as the slowest one. With 1-in-100 requests slow and fanout 100, **63 %** of user requests hit the tail. With 1-in-10,000 slow and fanout 2,000, still **18 %**. ⇒ your p99 is your user's p50 once fanout is large; the **fanout count** is a latency-risk multiplier that must appear in any parallelization review.
- Users experience the tail far more often than intuition suggests; "outliers" in a benchmark are the product.

### 2.3 Common sources of latency variance (checklist for spike hunts)

- **Physics**: region placement (us-east-1 default penalizes everyone off the US East Coast).
- **CPU/hardware**: cache misses (1 ns vs 100 ns is a 100× step function); branch misprediction (discard + re-execute is worse than not speculating); frequency scaling / thermal behavior (latency varies with load and battery).
- **Virtualization**: hypervisor multiplexing, noisy neighbors, virtual switches, hardware emulation — spikes you cannot see from inside the guest.
- **OS/drivers/firmware**: context switches (µs + cache pollution); interrupts at unpredictable times; drivers batching/reordering I/O for throughput; CPU microcode and SSD-firmware GC pauses.
- **Managed runtime**: JIT compilation pauses (AOT avoids); GC pauses (choose low-pause algorithm, avoid hot-path allocation, tune).
- **Application**: the biggest lever and the subject of the rest of the book.

### 2.4 Compounding

Components: propagation (`d/v`), transmission (`L/R`), processing, queuing (incl. OS scheduler queues). Modes:
- **Serial compounding** — latency = Σ steps; reduce by speeding steps or parallelizing inside a step (e.g. SIMD HTTP parsing).
- **Parallel compounding** — latency = max(branches); more fanout ⇒ more tail exposure (§2.2).
- **Quorum compounding** — wait for majority (⌊N/2⌋+1); strictly faster than waiting for all N; the reason consensus protocols are usable at all.

### 2.5 Measuring correctly

- Define *what* you measure (user-perceived end-to-end vs subsystem) and control the environment (client placement, co-running load).
- **Observer effect**: load generator on the machine under test consumes the same resources it measures — isolate measurement infrastructure.
- **Coordinated omission** (Gil Tene): the closed-loop benchmark pattern "send → wait for response → send next" silently coordinates with the server: when the server stalls, the tool sends fewer requests, so the stall is sampled once instead of hitting every request that would have arrived. Result: distributions that look far better than production.
  - Fix: send at **fixed intervals**, handle responses asynchronously, record start→end per request; or use HdrHistogram's correction with a known expected interval.
  - Detection cue in review: any benchmark loop whose next send is gated on the previous response.
- Reference: Gil Tene, "How NOT to Measure Latency" (2013).

### 2.6 Visualization

- Histogram: shows distribution shape; tail = sparse right region.
- Percentile plot (HdrHistogram, logit x-axis): precise tail inspection.
- **eCDF** (empirical CDF): directly answers SLA questions ("what % complete within 100 ms?") — the preferred plot for latency comparisons (Brooker).

## ch-3 — Colocation {#ch-3}

Bring components closer so data travels less distance. Order of attack: **internode first** (geography dominates; can overshadow all app-level work), then intranode (network stack, NUMA, caches).

### 3.2 Internode

- Geographic RTTs: NYC↔London 60 ms best / 100–150 ms typical; London↔Cape Town ~160 ms; London↔Sydney ~250 ms. Speed of light binds — the only fix is avoiding long round trips.
- **Last-mile latency**: ISP backbone → device adds 10–50 ms in practice (Wi-Fi alone: few–tens of ms) even when servers are close. Colocation to a region does not remove last-mile.
- **Edge**: *near edge* = CDN PoPs closer than cloud regions; *far edge* = user-controlled infra (home network, IoT gateway) eliminating both geographic and last-mile latency. Programmable CDNs (e.g. Workers) now serve dynamic content at the PoP.

### 3.3 Intranode

- Packet path: NIC RX queue → driver (interrupt/poll hybrid, Linux NAPI) → protocol processing (possibly on a *different* CPU than the app thread ⇒ inter-processor interrupt) → socket API → userspace. Two placements work: isolate IRQs on dedicated CPUs, or colocate IRQ + app thread per CPU.
- **Nagle's algorithm** batches small TCP segments for throughput, adding queuing delay to every small write. For latency-sensitive request/response traffic set `TCP_NODELAY`. Default TCP is throughput-tuned, not latency-tuned.
- UDP: minimal overhead, no delivery guarantee — fine intra-datacenter or with loss-tolerant apps; Aeron layers reliability/flow control on UDP with low latency. TOE hardware offload cuts tens of µs to single-digit µs.
- **Kernel-bypass**: userspace stacks (DPDK/Netmap, F-Stack), hardware paths (RDMA, SR-IOV), and XDP/eBPF at kernel ingress or on programmable NICs. Removes context switches, syscalls, and copies — at significant complexity. Most applications should live with standard TCP/IP (see exemptions).

### 3.4 Multicore

- **UMA** vs **NUMA**: NUMA = asymmetric DRAM latency per core; place data near the CPU that uses it — CDN logic inside one machine. Application-level sharding + NIC flow steering (MICA pattern; also achievable with eBPF) routes each request to the core owning its partition. (Apple "Unified Memory" ≠ UMA.)
- L1 ≈ 1 ns / ≤ ~100 KiB; LLC ≈ 10+ ns / MBs–tens of MBs. Keep the working set within the LLC for consistent latency.

### 3.5 Case study — REST API, PostgreSQL vs embedded SQLite (same machine)

| Variant | p50 | p99 | max | throughput |
|---|---|---|---|---|
| PostgreSQL (separate process, Docker) | 5.6 ms | 33 ms | 75 ms | ~1,460 req/s |
| SQLite (in-process) | 41 µs | 1.97 ms | 13 ms | ~188,000 req/s |

~80–130× improvement with **zero geographic latency involved** — the entire gap is loopback network stack + process boundary + virtualization. Lesson: the process boundary itself is a latency budget item; embedding data in the app's memory space removes a whole distribution of variance (SQLite's eCDF is a near-vertical line).

## ch-4 — Replication {#ch-4}

Colocation to *multiple* places at once: keep copies near users, gain availability/fault tolerance. Fundamental trade: **stricter consistency ⇒ more coordination ⇒ higher latency**. Costs: ≥ 3 copies of storage for strong consistency; write coordination.

### 4.2 Availability

- **High availability ≠ fault tolerance**: HA = bounded downtime %; fault tolerance = zero disruption on component failure. Downtime and disruption surface to users as tail latency.

| Nines | Downtime/day | Downtime/year |
|---|---|---|
| 90 % | 2.4 h | 36.5 d |
| 99 % | 14.4 min | 3.65 d |
| 99.9 % | 1.44 min | 8.77 h |
| 99.99 % | 8.64 s | 52.6 min |
| 99.999 % | 864 ms | 5.26 min |

- Scale-out (more nodes, enabled by replication) vs scale-up (bigger node).

### 4.3 Consistency models (latency baseline)

- **Strong consistency / linearizability**: illusion of one copy; single-object single-operation property (vs serializability = multi-object transactions, see ch-9). Gold standard; pays a cross-replica round trip per write.
- **Eventual consistency**: replicas converge eventually; no read/write ordering guarantees; consecutive reads may go backwards (strong eventual consistency adds "reads never go back in time"). Very low *write* latency (local write, async propagate); *read* cost can reappear as read-repair or multi-replica reads. Acceptable for CDNs, write-heavy stale-tolerant loads.
- **Causal consistency**: causally-ordered operations seen in order everywhere; concurrent ops unordered; implemented with vector clocks; the right fit for collaboration where logical order > global order.
- **Session consistency**: monotonic reads + read-your-writes *within one session* only. Fits user-centric web/mobile (shopping cart); wrong for multi-user collaboration.

### 4.4 Strategies

- **Single-leader**: all writes via leader — simple to reason about; leader is bottleneck + failover risk (downtime/data loss).
- **Multi-leader**: local writes per datacenter ⇒ lower write latency across regions; must handle write conflicts — avoid via partitioning, or resolve via CRDTs / operational transforms.
- **Leaderless** (Dynamo 2007): any node accepts writes; **quorum consistency** (majority-ack) is stronger than plain eventual but still not linearizable.
- **Read-your-writes is not guaranteed under async replication** (replication lag) — verify before building UX that echoes a user's own write.
- **Local-first / offline-first**: data + logic on the device, CRDT sync — minimum possible latency (no network on the critical path), maximally relaxed consistency.

### 4.5 Sync vs async replication

- Async: ack before replication → lowest write latency, risk of loss on primary failure; eventually consistent.
- Sync: ack after (all or quorum of) replicas confirm → linearizable-grade guarantees, write latency includes the slowest/quorum replica round trip.

### 4.6–4.7 State machine replication & Viewstamped Replication

- SMR: all nodes apply the same command sequence in the same order ⇒ linearizability + fault tolerance. **2f+1 nodes tolerate f non-Byzantine failures; quorum = f+1; minimum useful cluster = 3.** Bigger cluster ⇒ more tolerance, more latency, more cost. Byzantine faults need different, larger machinery.
- Algorithms: Paxos (multiphase voting, notoriously hard), Raft (leader + log replication, easier), **VSR** (primary-backup with numbered *views*; deterministic next-primary selection — conceptually simplest; used by TigerBeetle).
- VSR normal path: Client→`Request`→primary appends → `Prepare` to backups in parallel → quorum of `PrepareOK` → apply → `Reply`. Latency = client↔primary RTT + quorum compounding of PrepareOK; cross-DC backup placement trades write latency for availability.

## ch-5 — Partitioning {#ch-5}

Split the dataset into independently accessible subsets ⇒ less synchronization, more concurrency. Choose it when replicating everything is impractical (storage, write-conflict coordination). Costs: request routing, rebalancing, and usually **no cross-partition transactions**.

### 5.2 Physical strategies

- **Horizontal (sharding)**: split records (rows/documents/key-ranges). Fits OLTP (short, independent, record-complete transactions), in-memory thread-per-core state, distributed SQL (transparent sharding — you still pick the partition key).
  - **Key-hash partitioning**: uniform spread, hotspot-resistant; kills range scans.
  - **Key-range partitioning**: efficient range scans; hot partitions if keys skew (e.g. zip codes) — the classic fix is switching to hash.
  - Queries without the partition key in the WHERE clause ⇒ scatter-gather over all partitions or a secondary index (consistency + storage cost). Partition key must be high-cardinality.
- **Vertical (columnar)**: split by columns. Fits OLAP: compression of like-typed sequential values, reduced read amplification (read only needed columns), SIMD-friendly. Harder to scale (each partition still spans all rows); writes touch multiple partitions.
- **Hybrid**: vertical then horizontal (or vice versa) — OLAP efficiency + scale-out; extra coordination cost.

### 5.3 Logical strategies (orthogonal, workload-shaped)

- **Functional**: separate read-heavy (catalog) from write-heavy (orders) so they don't interfere.
- **Geographical**: partition by user location — proximity queries scan a small local partition; complications: user mobility (repartitioning), partition-edge queries.
- **User-based**: per-user partitions ⇒ zero cross-user coordination; downside O(users) partitions — discovery overhead, expensive cross-user aggregates (mitigate with a duplicate aggregate-oriented copy).
- **Time-based**: hourly/daily partitions for time-series/audit logs; recent-window queries touch few partitions.
- **Overpartitioning**: extra replicas of *hot* partitions for read concurrency — requires a replication protocol; storage + complexity.

### 5.4 Request routing

| Strategy | Hops | Client coupling | Notes |
|---|---|---|---|
| Direct | 1 | Client tracks topology | Lowest latency; hardest to secure/evolve |
| Proxy | 2 | None | Extra hop; client can cache partition→node to bypass |
| Forward | 1–2 | None | Every node proxies; degrades to direct with client caching |

Bad routing silently forfeits partitioning's latency win — a request that lands on the wrong node pays an extra hop every time.

### 5.5 Partition imbalance

- **Hot partitions** = data imbalance from a bad key/scheme (low cardinality, skewed ranges, unevenly sized values). Fix = better key or hash scheme; live rebalancing is painful, so choose well up front.
- **Skewed workloads** = access imbalance despite even data (viral item, Black Friday, time zones). Not fixable by scheme alone — overprovision for known events, scale/load-balance dynamically.

### 5.6 Case study

5 SQLite-backed API nodes + round-robin client vs 1 node: tail latency drops because concurrent requests run in parallel instead of queuing. **Partitioning reduces latency chiefly by adding concurrency, not by making a single request faster.**

## ch-6 — Caching {#ch-6}

Temporary copy of data near the access point; trades freshness for speed. **Choose caching over replication/partitioning when**: (a) no transactions/complex queries needed (key-value access suffices), (b) you cannot change the backing system, or (c) compute/storage constraints rule out full copies.

### 6.2 Vocabulary

Cache hit/miss; **hit ratio = hits / (hits + misses)**; **negative caching** (cache "no result" for expensive empty lookups); persistence (in-memory lost on restart; Redis can persist); transactional (isolation-preserving) vs non-transactional (stale reads possible).

### 6.3 Strategies

| Strategy | Miss handling | Write path | Latency profile | Cost |
|---|---|---|---|---|
| Cache-aside | App fetches DB + populates cache | App manages | Hit fast; miss = full DB latency in tail | Concurrent-miss stampede; no transactions |
| Read-through | Cache fetches DB itself | — | Same, but cache can hide misses via **refresh-ahead** (async refill before expiry) | Cache must know data model |
| Write-through | — | Cache → sync DB write → ack | Write latency = DB commit | Consistency on partial failure (unless transactional) |
| Write-behind | — | Cache acks, async batched DB flush | Lowest write latency | Durability loss window; no transactions |

- **Client-side caching** (in-process): removes even the cache-server hop; read-through + write-behind is the lowest-latency combination; costs app memory. For complex sync needs prefer local-first (ch-4) instead.
- **Distributed caching** = caching × partitioning × replication — inherits all three trade-off sets at once.

### 6.4 Coherency

- **Cache coherence** = all caches agree on data (CPU MESI protocol: Modified/Exclusive/Shared/Invalid; a write to a Shared line invalidates other copies — cross-core invalidation costs latency; store buffers + invalidation queues mean cores may transiently disagree). Coherence ≠ consistency: coherence syncs the data, consistency orders the operations.
- Most application-level distributed caches are deliberately **incoherent** (stale reads allowed) because coherence coordination costs the latency the cache was meant to save.

### 6.5 Hit-ratio math (the part everyone gets wrong)

- `avg = hit_ratio · hit_latency + (1 − hit_ratio) · miss_latency`. At 80 % hits, 0.1 s hit, 1 s miss ⇒ 0.28 s average — but the **tail is still the miss latency**: 1 in 5 requests pays full DB cost. A high hit ratio fixes the average; it does not fix p99. Caching becomes a low-*tail*-latency solution only when the miss cost itself is reduced (refresh-ahead, colocating the backing store).
- Maximize hit ratio by: sizing cache ≥ **working set** (the actively-accessed subset, usually ≪ total data); matching replacement policy to workload; restructuring access patterns to process data in cache-sized batches instead of repeated full-dataset passes.

### 6.6 Replacement policies

| Policy | Evicts | Good for | Bad for |
|---|---|---|---|
| LRU | Least recently used | Temporal locality | Low-locality scans (caches junk, can be worse than no cache) |
| LFU | Least frequently used | Stable popularity (CDN assets) | Shifting working sets |
| FIFO (+ re-insertion) | Oldest inserted (lazy promotion at eviction) | Simple, scan-resistant | — |
| **SIEVE** | FIFO variant: hand pointer + visited bit; skip-and-unmark visited, evict first unvisited | Beats LRU in recent benchmarks; quick demotion, lazy in-place promotion | — |

### 6.7 TTL

Simple invalidation that works when writes bypass the cache (DNS: 24 h static records, 30 s load-balancing records). Trap: TTL has **no connection to actual change frequency** — too short kills hit ratio and re-fetches unchanged data; too long serves stale. Good for rarely-changing data; wrong tool for highly dynamic data.

### 6.8–6.9 Materialized views & memoization

- **Materialized view**: DB-managed precomputed query result, queryable like a table; refresh manually or incrementally (Noria-style dataflow keeps it always fresh). Eventual consistency (computation outside the transaction); combines SQL richness with cache-speed reads.
- **Memoization** = caching for computation, keyed by function inputs (client-side REST-response caching is memoization). Complementary: materialized views cover data retrieval, memoization covers compute.

### 6.10 Case study

PostgreSQL + in-process Moka cache (cache-aside, 5 s TTL): median and bulk latency drop, **heavy tail persists** — misses still pay the DB. Confirms §6.5.

## ch-7 — Eliminating work {#ch-7}

"The fastest code is no code." Loop: benchmark → find the widest flame-graph block → remove work → re-measure. Order targets by control and payoff: application logic → serialization → memory management → OS overhead → precomputation.

### 7.2 Algorithmic complexity

- Time complexity ≈ latency growth with input size n. **Quadratic is already a problem** in latency-sensitive code; aim for O(1)/O(log n) when n can grow or the operation is hot; O(n) is fine only when n is small and bounded (a small fixed array can beat a hash map — constants matter, big O doesn't state absolute speed).

| Structure | Insert/Delete/Search (avg) | (worst) | Note |
|---|---|---|---|
| Array | O(n) | O(n) | Fine small & fixed-size |
| Stack/queue | O(1)/O(1)/O(n) | same | Temporary work-holding |
| Linked list | O(n) | O(n) | — |
| Hash table | O(1) | O(n) (collisions) | Watch memory/cache-thrash cost |
| BST | O(log n) | O(n) | Keeps order ⇒ range queries |

### 7.3 Serialization

CPU cycles + memory copies on every boundary crossing. **JSON** (human-readable, big, expensive) < **Protocol Buffers** (binary, varint-compact) < **FlatBuffers** (zero serialization — ships the little-endian in-memory layout; larger messages than protobuf but no ser/deser at all). For truly latency-sensitive paths, prefer FlatBuffers; and question whether the boundary (and its serialization) is needed at all.

### 7.4 Memory management

- **Dynamic allocation is non-deterministic latency**: freelist traversal, **external fragmentation** (long searches; coalescing pushes latency onto `free()`), **internal fragmentation** (memory waste ⇒ pressure), multi-thread heap contention. **Boxing/autoboxing** (Java/C#) hides allocations in innocent-looking code — audit hot paths.
- **GC**: removes safety bugs, adds uncontrolled pauses (ms–s) ⇒ tail latency. Generational bump-the-pointer allocation is cheap; collection is not. Playbook: pick a low-pause collector, tune (heap size, generation ratios, thresholds, concurrent threads), *and* minimize hot-path allocation / use object pools.
- **Virtual memory & demand paging**: pages (4 KiB) map lazily on first-touch page faults; under memory pressure the OS swaps pages out — a "memory" access silently becomes a disk access (~100× slower). Latency-sensitive processes preallocate and pin with `mlock()`/`VirtualLock()`. **TLB pressure**: many pages ⇒ translation-cache misses; **large pages** (2 MB) reduce TLB pressure at the cost of bigger page-fault I/O.
- **Memory topology**: DRAM up to 100× slower than L1. Iterating a big dataset repeatedly thrashes caches — process in cache-sized batches (also enables hardware prefetch). On NUMA, bind memory to the consuming CPU's node (`mbind()`, discover with hwloc).

### 7.5 OS overhead

- **Scheduling delay**: a ready thread runs only when the OS decides. **Context switch**: ~100s of ns direct, > 1 µs with cache/TLB fallout; syscalls pay the same mode-transition cost. Mitigations: fewer threads; thread affinity (`pthread_setaffinity_np`); priorities; the extreme is **thread-per-core** — ≤ 1 pinned thread per core, app-level concurrency via coroutines/futures, OS effectively bypassed.
- **Background tasks & interrupts**: daemons and kernel threads steal CPU at unpredictable times; route IRQs with interrupt affinity, partition CPUs between app and OS/IRQ work; polling instead of interrupts gives you control of *when* (Linux NAPI switches dynamically).
- **Network stack**: kernel does async work after `sendmsg()` and processes *all* inbound traffic (not just yours) in background threads. Dedicate CPUs to the network stack, use NIC flow steering, or bypass the kernel entirely (ch-3.3.3).

### 7.6 Precomputation

Compute expensive results before they are needed (build time, startup, periodic); serve from a lookup table. Staleness is the trade; **incremental precomputation** (update on change) mitigates. Materialized views are DB-level precomputation; requires knowing queries ahead of time.

### 7.7 Case study — Fibonacci with Criterion + flame graphs

Recursive O(2ⁿ): 157 ns → memoized O(n): 44 ns (flame graph shows `calloc`/`free` dominating — allocation overhead) → iterative O(n) without allocation: **5 ns (30×)**. Lesson: complexity reduction *and* allocation elimination compound; the flame graph's widest block tells you which to do next.

## ch-8 — Wait-free synchronization {#ch-8}

### 8.1–8.2 Locks and why they hurt tails

- **Mutex** (blocked threads sleep via syscall), **RW-lock** (concurrent readers, exclusive writer), **spinlock** (busy-loop; for very short critical sections; wastes CPU under contention). Keep critical sections short.
- Measured contention scaling (mutex lock+unlock): 1 thread ≈ 7 ns; 10 threads ≈ 600 ns; 100 threads ≈ 5 µs — **~1000× degradation purely from contention**; RW-locks scale similarly for reads.
- **Priority inversion**: low-prio holder blocks high-prio waiter while medium-prio preempts; fix = priority inheritance.
- **Convoying**: one slow lock-holder queues everyone behind it → cascading tail latency; worsened by long critical sections, contention, scheduling.
- **Deadlock (ABBA)**: two threads take locks A,B in opposite orders → circular wait; symptom = extreme tail latency / frozen system.

### 8.3–8.4 Atomics and memory barriers

- Atomic ops: load/store (aligned loads/stores are inherently atomic on x86-64/ARM64), fetch-and-modify (RMW: `fetch_add`; x86 `LOCK XADD`, ARM `LDXR/STXR` or `LDADD`), **compare-and-exchange (CAS)** (x86 `LOCK CMPXCHG`; `compare_exchange_weak` may spuriously fail but is cheaper). A spinlock is one atomic `xchg` in a loop.
- CPUs and compilers reorder; concurrent code needs explicit ordering. x86-64 = TSO (stores not reordered, few barriers); ARM64 = relaxed (more barriers). High-level orderings: **Acquire** (nothing after moves before), **Release** (nothing before moves after), **SeqCst** (global total order, most expensive), **Relaxed** (no ordering; only for e.g. independent counters).
- Canonical pattern: writer stores payload (Relaxed) then flag with **Release**; reader loads flag with **Acquire** then payload — guarantees the payload write is visible whenever the flag is. With Relaxed on both, the flag can be observed before the payload (demonstrated invariant violation).
- `compiler_fence()` blocks only compiler reordering (no CPU instruction) — for cases where hardware ordering suffices.

### 8.5 Progress conditions (weakest → strongest)

1. Blocking — no guarantee (mutexes). 2. Starvation-free — eventual progress. 3. Obstruction-free — finite only in isolation (livelock risk). 4. **Lock-free** — *some* thread always progresses; others may starve ⇒ tail latency. 5. **Wait-free** — *every* thread finishes in finite time (immune to deadlock, priority inversion; failure of one thread cannot block others). 6. Wait-free bounded — known step bound (the practical low-latency target). 7. Wait-free population-oblivious — same step count regardless of thread count (strongest, hardest).
- Trap: a blocking `malloc` inside a "wait-free" operation silently destroys the guarantee.
- **Consensus numbers** (Herlihy): atomic registers = 1; test-and-set / fetch-and-add / plain queues & stacks = 2 (fine for SPSC); **CAS and queue-with-peek = ∞ (universal)** — for arbitrary thread counts you need CAS.
- Structures: wait-free queues = circular buffers with atomic front/back; stacks = array + atomic top (fetch-and-add); linked lists are hard — insertion needs allocation, deletion needs **safe memory reclamation** (reference counting, hazard pointers, epoch-based reclamation, or GC — which itself perturbs wait-freedom).

### 8.6 Case study — SPSC bounded queue

Mutex-wrapped queue: ~1.1 µs per 128-element drain; wait-free SPSC: **~73 ns (~15×)**. Design: `back` written only by producer, `front` only by consumer (no write contention); each side loads its own index Relaxed, the other side's with Acquire, and publishes its update with Release (element write visible before index advance).

## ch-9 — Exploiting concurrency {#ch-9}

### 9.1 Concurrency ≠ parallelism

Concurrency = tasks *in progress* simultaneously (interleaving); parallelism = tasks *executing* simultaneously (multiple cores). Little's law again: at constant throughput, more concurrency ⇒ more latency (contention); to keep latency flat under rising concurrency you must raise throughput proportionally. Concurrency pays when tasks *wait* (DB queries, RPCs, filesystem, network).

### 9.2 Concurrency models

| Model | Scheduler | Switch cost | Fit |
|---|---|---|---|
| Kernel threads | OS, preemptive | 100s ns direct, > 1 µs with cache fallout | True parallelism; simple model |
| Fibers (userspace threads) | Cooperative, in-process | Small (no kernel crossing) | You control all tasks; risk: one buggy fiber hogs the CPU; can't migrate cores independently |
| Coroutines | Language/runtime; resumable functions (yield/resume) | Minimal | Massive counts of I/O-waiting tasks |
| Event-driven | Event loop + I/O multiplexing (epoll/io_uring/kqueue/IOCP) | — | Thousands of connections per thread; handlers must never block |
| Futures/promises (async-await) | Runtime (e.g. Tokio) over event loop | — | Structured async; watch per-future heap allocation, per-promise state, many-small-task sync overhead (pair with partitioning) |
| Actor model | Runtime message dispatch | — | No shared state, no locks; message order not guaranteed; location-transparent, fault-tolerant stateful services |

### 9.3 Parallel processing

- **Data parallelism**: same op over data chunks — needs independent, similar-sized, locality-aware partitions. SIMD: AVX-512 = 512 bits/instruction (64×8-bit … 8×64-bit); GPUs = thousands of FLOPs/cycle. Scaling sub-linear (split/combine/communication overhead + Amdahl).
- **Task parallelism**: different independent ops in parallel — product page fetches specs + inventory + pricing + reviews concurrently ⇒ latency = slowest fetch, not the sum. Pin threads (processor affinity) to preserve cache locality; critical on NUMA.

### 9.4 Transactions vs latency

- **Serializability**: concurrent transactions ≡ *some* serial order (no real-time guarantee between transactions). **Linearizability**: real-time order of single ops. **Strict serializability** = both.
- **Snapshot isolation** (via MVCC): each transaction reads a consistent start-time snapshot; readers and writers never block each other. Permits **write skew**: two transactions read overlapping data, write disjoint data, each check passes on its own snapshot, combined result violates the invariant (two $200 withdrawals against a "sum ≥ 0" constraint both commit).
- Isolation ladder (weakest→strongest): Read Uncommitted → Read Committed → Cursor Stability → Repeatable Read → Snapshot Isolation → Serializable. Anomalies: dirty write/read, lost update, fuzzy read, phantom, read skew, write skew. **Relaxing isolation buys concurrency (latency) and sells anomaly risk** — choose per data criticality (finance ⇒ serializable; CMS ⇒ snapshot). Ref: Berenson et al., "A Critique of ANSI SQL Isolation Levels" (1995).

### 9.5 Concurrency control

- **2PL** (pessimistic): growing phase acquires all locks, shrinking phase releases; serializable but blocking-heavy — poor fit for concurrent low-latency systems.
- **MVCC** (optimistic): timestamped row versions; abort on conflict; readers never block writers. Costs: version storage + garbage collection of stale versions.

### 9.6 Case study

10 × 10 ms independent async tasks: sequential ≈ 130 ms, `join_all` concurrent ≈ 13 ms (10×). Only works because the waits overlap; if the underlying I/O can't parallelize, async machinery *adds* latency.

## ch-10 — Asynchronous processing {#ch-10}

**Async hides latency; it does not reduce it.** Each operation takes as long as before — the system just stays responsive and overlaps waits. Reach for it when reduction techniques (ch-3–9) are exhausted or the slow component is out of your control. If the I/O cannot actually overlap, async bookkeeping makes latency *worse*.

### 10.1 Event loop

Poll (io_uring/epoll/kqueue/IOCP, with timeout; busy-poll only for ultra-low-latency loops) → process events → run scheduled tasks → repeat. Handlers must be non-blocking — one blocking call stalls every connection on the loop. One thread ⇒ thousands of connections. Costs: complexity, resource throttling for in-flight work, nondeterministic debugging, partial-failure error handling.

### 10.2 Asynchronous I/O techniques

- **I/O multiplexing**: monitor many fds in one thread; kills thread-per-connection overhead.
- **Request batching**: N requests per round trip hides network RTT (2-digit ms in-DC, ~100 ms cross-DC). Caveat: batching *responses* makes the client wait for the whole batch — batch requests, stream responses, or tune batch size.
- **Request hedging**: send duplicate requests, take the first response. For strict tail-latency targets against high-variance dependencies you can't fix. Requirements: **idempotent operations** and service headroom — hedging multiplies load and can worsen latency at high utilization. ↔ tension with release-it retry/capacity patterns: hedging is deliberate extra load; justify with tail-SLA math before adopting.
- **Buffered I/O**: accumulate reads/writes, batch syscalls; combine with readahead.
- **Memory mapping** (`mmap`): OS demand-pages the file; free readahead. Risks: working set > RAM ⇒ page-fault storms; async write-back ⇒ crash consistency; page faults are irreducible tail latency. Hints via `fadvise` (SEQUENTIAL/RANDOM/WILLNEED/DONTNEED).

### 10.3 Deferring work

- Immediate execution for user-facing/freshness-critical work; **defer everything else off the critical path** (post now, update analytics later). Challenge = knowing what is safely deferrable.
- **Priority queues** with **aging** (waiting raises priority — prevents starvation) and dynamic adjustment (batch work promoted off-peak).
- **Work stealing**: idle workers steal from the *tail* of busy workers' queues (less contention); refine with work splitting and locality-aware stealing. Task granularity: too fine ⇒ stealing overhead; too coarse ⇒ imbalance.

### 10.4 Resource pools (hide setup latency)

- **Thread pools**: pre-spawned workers; sizing is the trap (few ⇒ underuse, many ⇒ context-switch + memory). Low-latency alternative: **thread-per-core** (Seastar/ScyllaDB) — zero context switches, hot caches; requires *everything* non-blocking.
- **Memory pools**: pre-allocated buffers; async work is allocation-hungry; watch per-pool exhaustion/fragmentation.
- **Connection pools**: hide DNS + TCP handshake + TLS; bound resource use; pair with async queries but cap concurrent queries to protect the DB.

### 10.5 Backpressure (mandatory in async systems)

Unbounded producers overwhelm consumers ⇒ queue growth ⇒ latency climb ⇒ crash. Mechanisms, in preference order:
1. **Throttle the producer** — consumer signals capacity (TCP transmission window; defer `recv()` until you have capacity so the window shrinks naturally).
2. **Buffering** — absorbs bursts; sizing trade: big buffers ride spikes but add queuing latency, small buffers keep latency low but drop under bursts.
3. **Rate limiting** — cap per-client request rate (requires knowing capacity).
4. **Dropping** — last-resort safety valve; pushes complexity to clients but must exist.

### 10.6–10.7 Errors & observability

- Partial failures are the norm: track per-operation status; retries with exponential backoff; **design operations idempotent** (operation IDs to detect duplicates); timeouts + cancellation with robust cleanup (cleanup itself can fail).
- Tracing: propagate one trace ID through all async hops (logs alone can't reconstruct nondeterministic order). Metrics: queue depth, pool utilization, active tasks, error rates by class, retry success; **measure queue-wait, processing, and external-wait separately**. Instrumentation is itself on the hot path — cheap metrics or you ruin the latency you're measuring.

## ch-11 — Predictive techniques {#ch-11}

Perform long-running operations *before* they're needed: (1) identify irreducible-latency operations, (2) build a predictor for when results are needed, (3) initiate early. Right prediction = perceived zero latency; wrong prediction = wasted bandwidth/compute, **cache pollution** (displacing data that was needed), rollback overhead — mispredictions can make latency *worse* than doing nothing. Also beware side effects: prefetching an email can fire a read receipt.

### 11.2 Prefetching

- OS layer: page cache **readahead** detects sequential access; steer with `fadvise(FADV_SEQUENTIAL | FADV_RANDOM | …)`. CPU layer: hardware prefetchers handle sequential/strided patterns well; explicit software prefetch instructions are easy to get wrong (cache pollution).
- **Pattern-based** (physical, semantics-blind):
  - *Sequential*: prefetch next N while processing current; keep a resident prefetch window sized so data is always ready. Harmful for random access.
  - *Spatial*: on access to X, prefetch neighbors (B-tree node ⇒ parent/siblings/children; map tile ⇒ surrounding tiles).
  - *Stride-based*: detect fixed-interval access (every Nth element; matrix code).
- **Semantic** (application-aware): *dependency-based* (profile ⇒ permissions; product ⇒ recommendations), *context-based* (checkout page ⇒ address + payment data; location ⇒ nearby POIs), *history-based* (past behavior at location X ⇒ prefetch Y). Combinations beat any single signal; complexity is the cost — pattern-based is enough for many cases.
- Tune aggressiveness: too conservative wastes the opportunity; too aggressive wastes resources and pollutes caches.

### 11.3 Optimistic updates (hide *write* latency)

- Apply the change locally at once, sync in the background; user sees instant feedback. Architecture: local store (e.g. embedded SQLite) + **shadow write queue** of unsynced modifications; the app queries the **optimistic view** = base data + shadow queue.
- Conflict resolution when syncing multiple writers:
  - **LWW** (last-writer-wins): simple; physical clocks unreliable (skew) — use logical clock + node-ID tiebreaker. ↔ contra designing-data-intensive-applications ch-5: DDIA treats LWW as silent write loss; Enberg admits it only where loss is tolerable — reconcile on data criticality.
  - **Lamport timestamps**: counter, max(local, received)+1 on receive; gives causal order; *cannot detect concurrency*.
  - **Vector clocks**: detect concurrency; heavy per-participant metadata.
  - **HLC** (hybrid logical clocks): wall clock compared with drift tolerance (~1–10 ms LAN, ~1 s WAN/NTP) + logical counter for ties.
  - **OT** (operational transformation): central server transforms ops against concurrent ops.
  - **CRDTs**: commutative/associative/idempotent ops ⇒ converge in any order, no central server, automatic resolution.
- Consistency you actually get: eventual (baseline) → strong eventual (CRDTs) → causal (HLC). Mental model: **snapshot isolation locally, read committed globally**.
- Error handling: transparent retry (requires idempotent sync ops — op IDs, CRDT transitions, conditional updates); **partial application** (accept conflict-free changes, reject the rest — fine for low-stakes data like carts); rollback via data snapshots or operation-dependency undo; human-in-the-loop UI for unresolvable conflicts.

### 11.4 Speculative execution

- Do work before knowing it's needed; discard if not. CPUs do this with spare execution units at near-zero cost (branch prediction, out-of-order; cf. Spectre 2018 — speculation is also an attack surface); **at application level speculation consumes real CPU/memory/network/DB connections, so prediction accuracy matters far more**.
- **Incremental computation**: update derived state on each write instead of recomputing (materialized views with dependency graphs; social feeds) — the always-fresh variant of precomputation.
- **Parallel speculation**: launch alternative paths concurrently, keep the first/needed one (personalized + generic recommendations; start computing recommendations *during* authentication).
- **Value prediction**: show an estimated value now, correct when the real one lands (estimated delivery date; search-as-you-type speculative fetch).

### 11.5 Predictive resource allocation

Provisioning VMs/DBs/containers takes seconds–minutes. **Overprovisioning**: keep spare capacity ⇒ instant assignment, pay for idle (cloud autoscaling manages this for you). **Prewarming**: provision just-in-time from cyclical patterns, event signals (launch, campaign), or real-time indicators — less idle cost, needs a good predictor.

---

## Decision rules (summary)

**Technique selection (the book's ordering — biggest lever first):**

| Situation (observable) | Reach for | Src |
|---|---|---|
| Data and compute in different regions / different machines / different processes | Colocation (move data next to compute; embed if possible) | ch-3 |
| Need same data near many user populations, or availability requirements | Replication (pick consistency model = latency baseline first) | ch-4 |
| Dataset too big / too write-contended to replicate wholesale | Partitioning (pick key by workload; plan routing) | ch-5 |
| Can't change the backing system; key-value access pattern; no transactions needed | Caching (plan the miss path, not just the hit path) | ch-6 |
| Profiler shows app CPU, serialization, allocation, or syscalls | Eliminate work (algorithms → formats → allocation → OS) | ch-7 |
| Shared mutable state on a hot path with lock contention | Partition state first; wait-free structures if sharing is unavoidable | ch-8 |
| Independent waits (DB, RPC, I/O) executed sequentially | Concurrency / task parallelism | ch-9 |
| Latency irreducible (physics, third party) but work can overlap or defer | Async processing (+ backpressure) | ch-10 |
| Latency irreducible and work can't overlap — but is predictable | Predictive: prefetch / optimistic update / speculate / prewarm | ch-11 |

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Latency reported as a single average in a benchmark, dashboard, or PR description | Report the distribution: p50/p95/p99/p99.9 + max; prefer eCDF for comparisons | Average = inverse throughput; hides the tail users actually feel | ch-2 |
| Benchmark loop sends next request only after previous response | Flag **coordinated omission**: send at fixed intervals, record responses async (or HdrHistogram-correct) | Closed-loop tools under-sample stalls; results look far better than production | ch-2 |
| Load generator runs on the machine under test | Isolate measurement infrastructure from the system under test | Observer effect skews shared CPU/memory/I/O | ch-2 |
| Design fans a request out to N parallel sub-requests | Compute tail amplification: P(slow) × N (1 % slow × fanout 100 ⇒ 63 % of users hit the tail); budget p99 of dependencies, not p50 | Service latency = slowest sub-request | ch-2 |
| Plan adds cores/threads to "make it faster" | Estimate parallelizable fraction P first (Amdahl); P=0.5 caps speedup at 2× | Serial fraction dominates; parallelism ≠ lower latency | ch-2 |
| Proposed latency target vs known constants (e.g. sub-ms API with cross-region DB call) | Sanity-check against the latency-constants table and geography before any code work | Physics sets the floor; 60–150 ms RTT can't be optimized away in code | ch-1, ch-3 |
| User-facing action budget being set | Use perception thresholds: ≤100 ms imperceptible, ≤1 s acceptable, ≥10 s needs progress feedback instead of more optimization | Below/above thresholds effort is wasted or misdirected | ch-1 |
| App and its database in separate processes/containers on general-purpose deployments | Consider embedding or colocating the store before distributed optimizations; measure the process-boundary cost | Same-machine PostgreSQL vs in-process SQLite = ~80× median gap from network stack + virtualization alone | ch-3 |
| Small request/response messages over TCP with default socket options | Set `TCP_NODELAY` on latency-sensitive sockets | Nagle batches small writes, adding queuing delay | ch-3 |
| Choosing a replication/consistency configuration | Pick the weakest consistency the domain tolerates; write down whether read-your-writes holds | Every consistency step up costs a coordination round trip on writes | ch-4 |
| UI echoes a user's own write; storage is async-replicated | Verify read-your-writes (session consistency or read-from-leader) explicitly | Replication lag makes users' own writes vanish | ch-4 |
| Consensus/SMR cluster sizing in a plan | 2f+1 nodes for f failures; minimum 3; larger clusters raise latency and cost | Quorum math; quorum placement across DCs trades latency for HA | ch-4 |
| New partition key in a schema/design | Require high cardinality + even value sizes; default to key-hash unless range scans are a stated requirement | Low-cardinality/skewed range keys create hot partitions; rebalancing live is painful | ch-5 |
| Query path lacking the partition key in its predicate | Treat as scatter-gather: needs an index or a design change | Whole-cluster fan-out is often slower than not partitioning | ch-5 |
| Predictable load spike (launch, Black Friday) on partitioned data | Overprovision/overpartition hot data ahead; scheme changes can't fix workload skew | Skewed workloads ≠ skewed data; scheme alone can't absorb them | ch-5 |
| Cache added to fix latency SLO | Verify the SLO percentile survives a miss: avg = h·hit + (1−h)·miss, tail = miss; plan miss-cost reduction (refresh-ahead, colocation) | High hit ratio fixes the average, not p99 | ch-6 |
| Cache sizing / eviction choice in a diff | Size ≥ working set; match policy to workload (LRU=temporal locality, LFU=stable popularity, SIEVE=modern default); low-locality scans may be better uncached | Wrong policy or undersized cache can be slower than no cache | ch-6 |
| TTL constant chosen for dynamic data | Justify TTL against actual change rate; if writes can go through the cache, prefer write-through/behind invalidation over TTL guessing | TTL has no link to change frequency; wrong in both directions | ch-6 |
| Concurrent cache-aside misses on a hot key | Coordinate miss handling (single-flight) | Stampede: N DB reads + N conflicting cache writes | ch-6 |
| Nested loop / O(n²) over unbounded input on a request path | Replace with O(n log n)/O(n)/O(1) structure, or prove n is small and bounded | Quadratic growth is already a latency problem at modest n | ch-7 |
| JSON (de)serialization inside a latency-sensitive hop | Consider protobuf; FlatBuffers when ser/deser must vanish; or remove the boundary | Serialization = CPU + copies + wire size on every crossing | ch-7 |
| Allocation, boxing, or GC-triggering code in a hot path | Hoist allocations out; pool/reuse objects; watch implicit boxing | Allocator latency is non-deterministic; GC pauses land in the tail | ch-7 |
| Latency-critical process relying on default paging | Preallocate + `mlock()` pinned memory; consider large pages under TLB pressure | Demand paging turns a RAM access into a disk access at the OS's whim | ch-7 |
| "Optimize" PR without profile evidence | Require benchmark + flame graph before/after; attack the widest block | Iterative measure→eliminate is the only reliable loop; 157→5 ns came from two profile-guided steps | ch-7 |
| Lock acquired on a hot path serving many threads | Measure under contention (locks degrade ~1000× from 1→100 threads); shorten critical section, partition state, or go wait-free | Contention, convoying, priority inversion all land in the tail | ch-8 |
| Two locks acquired in different orders in different call paths | Flag ABBA deadlock; enforce a global lock order | Circular wait freezes the system = infinite tail latency | ch-8 |
| `Ordering::Relaxed` on a flag that publishes other writes | Require Release on store + Acquire on load pair | Relaxed lets the flag become visible before the data it guards | ch-8 |
| "Lock-free" claimed where all threads need bounded latency | Distinguish: lock-free = some thread progresses; wait-free = all do; check for blocking allocation inside the algorithm | Lock-free still permits per-thread starvation ⇒ tail latency | ch-8 |
| Wait-free/lock-free design for > 2 threads built on fetch-and-add/test-and-set | Use CAS (consensus number ∞); FAA/TAS only guarantee consensus for 2 (SPSC) | Herlihy's hierarchy bounds what each primitive can coordinate | ch-8 |
| Sequential awaits over independent I/O (`await a; await b; …`) | Join them (`join_all`) when independent; 10×10 ms → ~13 ms | Latency of independent waits should be max, not sum | ch-9 |
| Transaction isolation level chosen by default | Choose per anomaly tolerance: serializable for invariant-critical (money), snapshot isolation for general use — but check for write skew on disjoint-write invariants | Isolation is a concurrency/latency dial with named anomaly costs | ch-9 |
| Async added to a path whose I/O cannot overlap | Remove it: async hides latency only when waits overlap; otherwise it adds overhead | Async ≠ faster; it's bookkeeping unless there's parallel wait | ch-10 |
| Producer→consumer queue with no capacity signal | Add backpressure: throttle producer first, then bounded buffers, rate limit, drop as last resort | Unbounded queues convert overload into latency then crash | ch-10 |
| Request hedging proposed | Require idempotent operations + measured headroom + tail-SLA justification | Hedging multiplies load; at high utilization it worsens latency | ch-10 |
| Retry logic in async/sync flows | Exponential backoff + idempotency via operation IDs | Blind retries duplicate effects and amplify overload | ch-10 |
| `mmap` proposed for data ≥ RAM or crash-sensitive writes | Prefer explicit async I/O; mmap page faults are irreducible tail latency and write-back is async | Working set > RAM ⇒ fault storms; crash ⇒ consistency loss | ch-10 |
| Prefetching added anywhere | Bound aggressiveness; measure hit rate of the *prediction*; check side effects (read receipts) and cache pollution | Wrong prefetch is worse than none: wasted I/O + evicted useful data | ch-11 |
| Client-side instant-feedback writes (optimistic UI) | Back with shadow write queue + explicit conflict strategy (CRDT/HLC/LWW-by-criticality) + rollback path + conflict UI | Perceived-zero write latency is bought with reconciliation machinery | ch-11 |
| Provisioning latency (VM/DB spin-up) on user path | Overprovision or prewarm from cyclical/event/real-time predictors | Seconds–minutes of provisioning can't be hidden any other way | ch-11 |

## Anti-patterns

- **Coordinated omission** — benchmark waits for each response before sending the next. *Cue*: closed request loop in load-test code; suspiciously clean p99. (ch-2)
- **Average-only latency reporting** — single number in dashboards/PRs. *Cue*: "avg latency = X ms" with no percentiles. (ch-2)
- **Fanout blindness** — parallelizing into N sub-requests without tail math. *Cue*: scatter-gather added with p50-based budget. (ch-2)
- **Wrong-side-of-the-ocean deployment** — service and its data in different regions by default (us-east-1 inertia). *Cue*: cross-region call on the request path. (ch-3)
- **Nagle by default** — small latency-sensitive TCP writes without `TCP_NODELAY`. (ch-3)
- **Cache as tail-latency fix** — adding a cache to meet a p99 SLO without reducing miss cost. *Cue*: "add Redis" as the whole plan. (ch-6)
- **TTL guessing** — TTL constants unrelated to data change rate. *Cue*: magic `ttl: 300` on dynamic data. (ch-6)
- **Hot-path allocation** — per-request `new`/boxing/vector growth in latency-critical loops. *Cue*: allocator frames widest in the flame graph (the memoized-Fibonacci trap). (ch-7)
- **Optimization without a profile** — code golf where no benchmark exists. *Cue*: perf PR with no before/after numbers. (ch-7)
- **ABBA locking** — inconsistent lock acquisition order across paths. (ch-8)
- **Relaxed-ordering publication** — atomic flag published without Release/Acquire pairing. (ch-8)
- **Async cargo-culting** — async/await sprinkled on non-overlapping I/O; sequential awaits over independent calls. (ch-9, ch-10)
- **Unbounded queues** — producer/consumer with no backpressure signal; buffers "big enough". (ch-10)
- **Hedging without idempotency/headroom** — duplicate requests to a mutation endpoint or a saturated service. (ch-10)
- **Aggressive prefetch** — speculative fetching that pollutes caches or fires side effects (read receipts). (ch-11)
- **Physical-clock LWW** — conflict resolution by wall clock across nodes. *Cue*: `ORDER BY updated_at` conflict logic. (ch-11)

## Applicability & exemptions

- **Scale gates — don't fire these below their scale.** Replication (ch-4), partitioning (ch-5), and distributed caching exist for data too large/hot/global for one node. A single-node app with one region of users usually wants colocation (embed the DB, ch-3) and work elimination (ch-7) first — the book explicitly orders techniques by impact, and the biggest lever for small systems is placement, not distribution. Flagging "no replication/sharding" in a small CRUD app is a false positive.
- **Kernel-bypass, TOE, XDP/eBPF, busy-polling, thread-per-core, wait-free structures, FlatBuffers, `mlock`, CPU pinning** are for sub-millisecond budgets (trading, DB engines, real-time pipelines). The author states most applications should accept standard TCP/IP and OS scheduling; recommending these in ordinary web services is over-firing. Wait-free code belongs in small isolated components (queues between stages), not general application logic.
- **Perception thresholds bound the effort**: work already ≤ 100 ms end-to-end has no user-visible payoff for further UX-motivated optimization; work ≥ 10 s needs progress feedback / streaming, not micro-optimization.
- **Async is hiding, not reduction** — exempt when the waits cannot overlap; there async rules invert (remove the machinery).
- **Hedging/speculation/prefetching require headroom and predictability**: at high utilization or with poor predictors they *degrade* latency. Don't recommend them for saturated or unpredictable systems.
- **Consistency-relaxation rules are domain-gated**: eventual consistency, snapshot isolation, LWW, partial application are correct suggestions only where the domain tolerates staleness/loss (carts, feeds, caches) — never for invariant-critical data (money, inventory constraints) without serializable/linearizable checks.
- **Hard real-time systems** (pacemakers, avionics) are out of scope — they need certified RTOS/deadline scheduling, not these general techniques.
- **Throughput-optimized batch systems** legitimately choose the other side of the latency/throughput trade (pipelining, batching, interrupt coalescing, Nagle); latency rules don't apply to offline/batch paths.
- **Little's-law and Amdahl estimates are models**: real systems violate their independence assumptions (latency rises with concurrency); use them to size expectations, then measure.

## Candidate lexicon rows

| Trigger phrase | Rule | Activating question | Tier | Phase | Src |
|---|---|---|---|---|---|
| benchmark loop awaits response before next send | **Coordinated omission** — closed-loop load tests under-sample stalls, making the latency distribution look far better than production; send at fixed intervals and record responses asynchronously | Does the load generator's send rate depend on the system's response time? | blocker | review | src: latency-reduce-delay-in-software-systems ch-2 |
| latency quoted as a single average | **Latency is a distribution** — average is the inverse of throughput and hides the tail; report p50/p95/p99/p99.9 (+max), prefer eCDF for comparisons | Which percentiles back this latency claim? | should | review | src: latency-reduce-delay-in-software-systems ch-2 |
| request fans out to N parallel sub-requests | **Tail-at-scale fanout math** — service latency = slowest sub-request; 1 % slow × fanout 100 ⇒ 63 % of users hit the tail, so budget dependency p99 not p50 | What is P(sub-request slow) × fanout for this path? | should | plan | src: latency-reduce-delay-in-software-systems ch-2 |
| latency target set for a new endpoint or system | **Budget against latency constants** — DRAM 100 ns, NVMe 10 µs, SSD 100 µs, cross-Atlantic RTT 60–150 ms; each boundary crossing costs ~an order of magnitude and geography sets a hard floor | Which physical boundary crossings does this path include, and do the constants permit the target? | should | plan | src: latency-reduce-delay-in-software-systems ch-1 |
| UX latency goal discussed | **Human-perception thresholds** — ≤ 100 ms reads as instant, ≤ 1 s acceptable, ≥ 10 s needs progress feedback/streaming instead of further optimization | Which perception bucket is this interaction in, and does more optimization change the bucket? | judgment | plan | src: latency-reduce-delay-in-software-systems ch-1 |
| cache proposed to meet a latency SLO | **Caches fix averages, not tails** — avg = h·hit + (1−h)·miss but p99 stays at miss latency; pair any cache with a miss-cost plan (refresh-ahead, colocation) and size ≥ working set | What does p99 look like on a cache miss, and how is miss cost reduced? | should | plan | src: latency-reduce-delay-in-software-systems ch-6 |
| sequential awaits over independent I/O calls | **Join independent waits** — latency of independent operations should be their max, not their sum; concurrent execution cut 10×10 ms tasks from 130 ms to 13 ms | Are these awaited operations actually dependent on each other? | should | write | src: latency-reduce-delay-in-software-systems ch-9 |
| async work queued between producer and consumer | **Backpressure or bust** — unbounded queues convert overload into latency growth then crash; throttle the producer first, then bounded buffers, rate limiting, dropping as last resort | How does the consumer signal capacity back to the producer? | blocker | review | src: latency-reduce-delay-in-software-systems ch-10 |
| duplicate/hedged requests proposed for tail latency | **Hedging needs idempotency + headroom** — first-response-wins multiplies load and requires side-effect-free retries; at high utilization it worsens the latency it targets | Are these operations idempotent, and is there measured capacity headroom? | should | plan | src: latency-reduce-delay-in-software-systems ch-10 |
| allocation or boxing inside a hot loop | **Hot paths don't allocate** — allocator freelists and GC pauses are non-deterministic tail latency; hoist, pool, or preallocate (memoized-Fibonacci: removing allocation was another 9× after the algorithmic fix) | Does the flame graph show allocator frames under this path? | should | write | src: latency-reduce-delay-in-software-systems ch-7 |
| conflict resolution via wall-clock timestamps | **No physical-clock LWW** — clock skew makes last-writer-wins nondeterministic; use logical/hybrid clocks with node-ID tiebreakers, or CRDTs, and reserve LWW for loss-tolerant data | What happens to a concurrent write from a node with a skewed clock? | blocker | review | src: latency-reduce-delay-in-software-systems ch-11 |
| lock added on a multi-threaded hot path | **Contention scales ~1000×** — a 7 ns uncontended mutex costs ~5 µs at 100 threads, plus convoying and priority inversion in the tail; shorten the critical section, partition the state, or use a wait-free structure | What does this lock cost at production thread counts, not at 1 thread? | should | review | src: latency-reduce-delay-in-software-systems ch-8 |
