# Designing Data-Intensive Applications — distilled

> **Source**: Martin Kleppmann, *Designing Data-Intensive Applications: The Big Ideas Behind Reliable, Scalable, and Maintainable Systems*, 1st ed., O'Reilly 2017 · extracted from `../Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The directory's reference work on *data correctness under concurrency and distribution*. No other source here explains which isolation anomalies a given database actually prevents, when a quorum read can still return stale data, why wall-clock timestamps silently lose writes, what a fencing token is and when leases are unsafe without one, which schema changes are rolling-upgrade-safe, and when a distributed design is strictly worse than a single machine. Where release-it covers runtime stability and the latency book covers speed, DDIA covers *not corrupting or losing data* — and precisely when its expensive machinery (consensus, serializability, linearizability) is NOT needed.

## Chapter map

- ch-1 — Reliable, Scalable, Maintainable: what fault/failure/load/latency actually mean; percentiles; when to precompute
- ch-2 — Data Models and Query Languages: relational vs document vs graph — chosen by relationship shape, not fashion
- ch-3 — Storage and Retrieval: B-tree vs LSM trade-offs; OLTP vs OLAP; column stores; which index for which query
- ch-4 — Encoding and Evolution: rolling-upgrade-safe schema changes; backward/forward compatibility rules per format
- ch-5 — Replication: sync/async, failover hazards, replication-lag anomalies and their fixes, conflicts, quorums
- ch-6 — Partitioning: key-range vs hash, hot keys, secondary-index partitioning, rebalancing, request routing
- ch-7 — Transactions: the isolation-anomaly catalog (dirty read → write skew), what "repeatable read" really means, 3 roads to serializability
- ch-8 — The Trouble with Distributed Systems: unreliable networks/clocks/pauses; fencing tokens; system models; safety vs liveness
- ch-9 — Consistency and Consensus: when you actually need linearizability; causal order; total order broadcast ≡ consensus; 2PC; ZooKeeper
- ch-10 — Batch Processing: MapReduce/dataflow join strategies, skew handling, immutable-input philosophy, single-machine exemption
- ch-11 — Stream Processing: log-based brokers vs AMQP, CDC, event sourcing, windows/time, stream joins, exactly-once mechanisms
- ch-12 — The Future of Data Systems: log-derived data over dual writes, end-to-end argument, timeliness vs integrity, coordination avoidance, audit culture, ethics

## ch-1 — Reliable, Scalable, and Maintainable Applications {#ch-1}

**Data-intensive** = data quantity/complexity/rate of change is the bottleneck, not CPU. Modern apps compose standard building blocks — database, cache, search index, message queue, batch/stream processor — and the composition code is itself a data system with the same obligations.

### Reliability

- **Fault ≠ failure**: fault = one component deviates from spec; failure = system stops providing service to the user. Fault-tolerance design prevents faults from becoming failures.
- Hardware faults are random and mostly independent: disk MTTF 10–50 yrs → a 10,000-disk cluster expects ~1 disk death/day. Rule: once you run on many machines (or cloud VMs that vanish without warning), prefer *software* fault tolerance over hardware redundancy alone — it also buys rolling upgrades (patch one node at a time, no planned downtime).
- Software faults are *systematic and correlated* — they hit all nodes at once (e.g., the June 30 2012 leap second + Linux kernel bug hung many systems simultaneously). Redundancy doesn't help against them.
- Human/config error is the *leading* cause of outages; hardware faults only 10–25%. Countermeasures: sandbox environments, decouple places-people-make-mistakes from places-mistakes-cause-failures, fast rollback + gradual rollout, detailed telemetry.
- Rule: error-handling paths that never run are where critical bugs live — deliberately inject faults (**Chaos Monkey**) to exercise fault-tolerance machinery.
- Exemption: reliability may be consciously sacrificed for prototypes or unproven products — but make the trade-off explicit.
- Security faults must be *prevented*, not tolerated — data exfiltration can't be undone.

### Scalability

- "X is scalable" is meaningless as a label. Always: "if load grows in dimension D, what are our options?" Define **load parameters** (req/s, read:write ratio, fan-out, active users, cache hit rate) for *your* system.
- **Twitter fan-out** (canonical micro-example, Nov 2012 figures): 4.6k tweet-writes/s (12k peak) vs 300k home-timeline reads/s. Approach 1: join at read time (cheap writes, slow reads). Approach 2: fan out each tweet to per-follower timeline caches at write time (avg 75 followers → 345k cache writes/s; fast reads). Reads ≫ writes → Twitter chose 2 — *except* for celebrities (30M+ followers → 30M cache writes per tweet), whose tweets are merged at read time. Rule: shift work to write time when read:write ratio is high; exempt the extreme-fan-out entities and handle them at read time (hybrid).
- **Response time is a distribution — use percentiles, never the mean.** p50 = typical user; p95/p99/p999 = **tail latencies**, often your highest-value users (Amazon SLAs use p999; found 100 ms extra latency → −1% sales; but judged p9999 too expensive to chase). Never average percentiles across machines — aggregate histograms (HdrHistogram, t-digest).
- **Tail latency amplification**: a user request fanning out to N parallel backend calls is as slow as the slowest call — even rare slow backends dominate end-user latency. Detection cue: synchronous fan-out to many services in one request handler. ↔ same phenomenon is central to *latency* (Enberg); DDIA supplies the fan-out arithmetic.
- **Head-of-line blocking**: a few slow requests hold up queued fast ones; client-observed response time includes the queueing.
- Load-testing rule: the generator must keep sending requests *independent of response time*; waiting for each response before sending the next artificially shortens queues and hides the very congestion you're measuring (↔ latency book's **coordinated omission**).
- Scaling up (vertical) is simpler; scaling out (**shared-nothing**) adds distribution complexity. Keep stateful systems on a single node until scaling cost or HA forces otherwise; stateless services distribute easily. Expect to rethink architecture at every ~10× load increase — no "magic scaling sauce"; architecture is specific to *your* load parameters.

### Maintainability

- Majority of software cost is ongoing maintenance, not initial build. Three design principles:
  - **Operability**: good monitoring/telemetry, automation support, no single-machine dependence, predictable behavior, docs.
  - **Simplicity**: remove **accidental complexity** (from implementation) via abstraction; **essential complexity** (in the problem) can't be removed.
  - **Evolvability**: ease of change at data-system scale — the theme chapters 4, 11, 12 develop (schema evolution, derived views, reprocessing).

## ch-2 — Data Models and Query Languages {#ch-2}

Each layer models the one below: domain objects → general-purpose model (relational/document/graph) → bytes on disk. The model determines what's easy to express and what's slow.

### Choosing a model by relationship shape

| Data shape | Model | Why |
|---|---|---|
| Self-contained tree of one-to-many, loaded whole (résumé/profile) | Document | Locality: one query; matches app objects; schema-on-read |
| Many-to-many relations, joins needed | Relational | Joins are the DB's job; query optimizer handles access paths |
| Highly interconnected — anything may relate to anything | Graph | Variable-length traversals natural; heterogeneous vertices/edges |

- **Object-relational impedance mismatch**: ORMs cut boilerplate but can't hide the gap.
- Document-model failure mode: data becomes more interconnected over time; weak/no joins force app-level joins or denormalization (write overhead + inconsistency risk). Detection cue: app code loops issuing follow-up queries to stitch records = emulating a join the database should do.
- Rule: store IDs, not human-meaningful strings, wherever a value is referenced from many records — IDs never need to change; duplicated meaningful text must be updated everywhere and drifts. Detection cue: same display string duplicated across rows/documents.
- Locality cuts both ways: whole-document storage is fast for whole-document reads but wasteful for partial reads, and size-growing updates rewrite the document. Rule: keep documents small; avoid writes that grow them.
- **Schema-on-read** (document) ≈ dynamic typing — best when data is heterogeneous or structure is dictated by external systems you don't control. **Schema-on-write** (relational) ≈ static typing — best when records are uniform; the schema is enforced documentation. Migration note: most RDBMSs run `ALTER TABLE` in milliseconds; MySQL historically copies the whole table (minutes–hours) — use online-schema-change tools.
- History rhymes: the 1970s **hierarchical model** (IMS) had today's document-model problems with many-to-many; **CODASYL** (network model) exposed manual **access paths** — change an access path, rewrite queries. The relational model won because the **query optimizer** picks access paths automatically: add an index, queries just get faster. Document DBs are (partially) re-learning this.
- Convergence: relational DBs added JSON; document DBs added join-like features — **polyglot persistence**, models borrowing from each other.

### Query languages

- **Declarative** (SQL, Cypher, CSS): state the result pattern; the optimizer picks execution — enabling parallelism and internal improvement without rewriting queries. **Imperative** code over-constrains order and can't be transparently optimized. Prefer declarative when available.
- **MapReduce querying** sits between: two coordinated pure functions; usability friction led MongoDB to add a declarative aggregation pipeline on top.
- Graph-query rule: variable-length traversals ("any number of WITHIN hops") take ~4 lines of **Cypher** vs ~29 lines of recursive-CTE SQL — when queries are traversal-shaped, use a graph language (Cypher, **SPARQL** over RDF triples, **Datalog** for composable rules).
- **Property graph**: vertices + edges each with key-value properties; representable as two relational tables with indexes on head/tail vertex.

## ch-3 — Storage and Retrieval {#ch-3}

Core trade-off: **every index speeds some reads and slows every write** — index by the application's actual query patterns, never "everything".

### Log-structured storage: hash indexes, SSTables, LSM-trees

- Append-only log + in-memory hash of key→offset (**Bitcask**): great when writes-per-key are high but distinct keys fit in RAM (canonical: video play-counters). Limits: all keys in memory, no range queries.
- **Compaction** discards overwritten values (keep latest per key); deletion = append a **tombstone**; segments merge in background. Sequential appends beat random overwrites on both disks and SSDs, and crash recovery is simpler (no half-overwritten pages).
- **SSTable** = segment sorted by key. Enables: merge-sort of segments bigger than RAM; *sparse* in-memory index (one key per few KB); block compression. **Memtable** (in-memory balanced tree) absorbs writes, flushed to an SSTable at a few MB; a small WAL restores the memtable on crash. Read path: memtable → newest SSTable → older ones; add a **Bloom filter** so lookups of *absent* keys don't touch disk.
- This is the **LSM-tree** (LevelDB, RocksDB, Cassandra, HBase; Lucene's term dictionary). Compaction strategies: **size-tiered** (small newer merged into large older; HBase) vs **leveled** (key range split into levels; more incremental, less disk; LevelDB/RocksDB).
- Operational rule (falsifiable): LSM engines do NOT throttle incoming writes when compaction falls behind — unmerged segments accumulate until the disk fills and reads slow. If write rate is high, monitor compaction backlog explicitly.

### B-trees

- Fixed-size pages (traditionally 4 KB), branching factor in the hundreds; nearly all databases fit in 3–4 levels (4 KB pages, branching 500, 4 levels → 256 TB). Introduced 1970, "ubiquitous" by 1979.
- Writes overwrite pages in place; overfull pages split. Crash safety requires a **write-ahead log** (redo log) — every modification goes to the WAL before the page. Concurrency needs **latches**. Alternative: copy-on-write (LMDB) — also gives cheap snapshots.

### B-tree vs LSM decision table

| Dimension | B-tree | LSM-tree |
|---|---|---|
| Reads | Generally faster (key in exactly one place) | Slower: memtable + several SSTables |
| Writes | Slower; **write amplification** ≥2× (WAL + whole page) | Faster: sequential batched writes |
| Latency profile | Predictable | Compaction spikes tail latency |
| Space | Fragmentation (partial pages) | Better compression, less fragmentation |
| Transactions | Range locks natural (one copy per key) | Multiple copies per key — harder |

Rule: no universal winner — benchmark with *your* workload. Write amplification matters doubly on SSDs (wear + finite write bandwidth).

### Other index structures

- **Secondary indexes**: point into a **heap file** (avoids duplicating rows) or use a **clustered index** (row stored in the index — InnoDB primary key). A **covering index** answers queries from the index alone. A **concatenated index** (lastname, firstname) serves only left-prefix queries — a WHERE on the second column alone won't use it (detection cue for slow queries). True multi-dimensional queries (lat AND long) need R-trees/space-filling curves; fuzzy search needs Levenshtein automata (Lucene).
- In-memory DBs (VoltDB, MemSQL, Redis): the win is *not* avoiding disk reads (the OS page cache already does that) — it's avoiding the overhead of encoding data structures for disk.

### OLTP vs OLAP, warehouses, column stores

| Property | OLTP | OLAP / warehouse |
|---|---|---|
| Read pattern | Few records by key | Aggregate millions of rows |
| Write pattern | Random, low-latency | Bulk ETL / event stream |
| Bottleneck | Disk seek | Disk bandwidth |
| Size | GB–TB | TB–PB |

- Rule: don't run analytics on the OLTP database — ad-hoc scans wreck concurrent transaction latency; ETL into a separate warehouse (**star schema**: central fact table of events + dimension tables; **snowflake** = further normalized; analysts prefer star).
- **Column-oriented storage**: fact tables have 100+ columns, queries touch 4–5 — store each column contiguously and read only what's queried. Columns compress hugely (**bitmap encoding** + run-length; bitwise AND/OR answers multi-predicate filters), enabling **vectorized processing** (L1-cache-sized chunks, SIMD). Sort whole rows by a commonly filtered column — the first sort key run-length-encodes best; Vertica stores redundant copies in different sort orders (you replicate anyway). Writes use the LSM pattern (in-memory buffer, bulk merge).
- Warning: Cassandra/HBase "**column families**" are row-oriented despite the name.
- **Materialized views / data cubes** precompute aggregates: fast for anticipated queries, useless for dimensions they omit — keep raw data, treat cubes as optimization only.

## ch-4 — Encoding and Evolution {#ch-4}

Rolling upgrades mean old and new code — and old and new data formats — *always* coexist. Two directional guarantees:
- **Backward compatibility**: new code reads old data (easy — you know the old format).
- **Forward compatibility**: old code reads new data (hard — old code must ignore what it doesn't know).

### Format rules

- Never use language-built-in serialization (Java serialization, pickle) for anything persistent or cross-service: language lock-in, deserialization = remote-code-execution risk, no versioning, bad performance.
- JSON/XML/CSV are fine as *interchange between organizations*, but know the traps: no integer-vs-float distinction (JSON), integers >2^53 lose precision in JavaScript (Twitter ships tweet IDs twice: number + string), binary data needs Base64 (+33%), CSV escaping is vague. Binary JSON (MessagePack) saves little (81 B JSON → 66 B) — not worth losing readability.
- Schema'd binary formats for the same record: Thrift BinaryProtocol 59 B → Thrift Compact 34 B → Protocol Buffers 33 B → Avro 32 B. Schemas double as always-in-sync documentation and enable compatibility checks at build time.

### Schema evolution — the falsifiable rules

Thrift/Protocol Buffers (field **tag numbers** are the wire contract, names are free):
- Adding a field: use a NEW tag number, and it must be optional or have a default — otherwise new code fails reading old data (backward-compat break). Old code ignores unknown tags (forward-compatible).
- Removing a field: only ever remove optional fields, and **never reuse the tag number** — old data still carries it.
- Renaming: safe (tags, not names, are encoded). Changing a tag number: never — invalidates all existing data.
- Widening int32→int64: new-reads-old is safe (zero-fill); old-reads-new *truncates* — flag any lossy narrowing in review.
- Protobuf `optional`→`repeated` is a safe evolution; Thrift's typed lists don't allow the single→multi trick.

Avro (no tags; decoder matches **writer's schema** against **reader's schema** by field name):
- Add/remove a field: only with a default value — otherwise you break backward (add without default) or forward (remove without default) compatibility.
- null is not an implicit default: declare `union { null, long }` with null first — a deliberate feature (prevents null bugs).
- Rename: via aliases, backward-compatible only. Avro's tag-free design is why it excels at *dynamically generated* schemas (e.g., dumping any relational schema) — no manual tag bookkeeping.
- Writer's schema travels: once per large file (object container), as a version number + schema registry per DB record, or negotiated per connection (RPC).

### Dataflow rules

- **Data outlives code**: five-year-old rows are still in their original encoding; databases need backward AND forward compatibility simultaneously (multiple app versions share the DB during a rolling upgrade).
- Trap (canonical): old code reads a record written by new code, rewrites it from its model objects, and *silently drops the unknown new fields*. Rule: preserve unknown fields through read-modify-write cycles. Detection cue: ORM round-trip that reconstructs records from named fields only.
- Services: deploy servers first → requests need backward compat, responses need forward compat. Public APIs: you can't force client upgrades — version side-by-side (URL or Accept header) indefinitely.
- **RPC is not a local call**: unpredictable failure modes; a timeout tells you *nothing* about whether the call executed; retries duplicate execution unless the operation is idempotent (→ ch-12 request IDs); latency wildly variable; no pass-by-reference. Modern frameworks (gRPC, Finagle) at least make the network explicit (futures, streams). REST wins for public/experimental APIs (curl, debuggability); binary RPC wins for internal latency-sensitive calls.
- **Message brokers** decouple sender from recipient (buffering, redelivery, pub/sub, no address knowledge) and are encoding-agnostic — producer/consumer deploy independently if the format stays both-ways compatible.
- Distributed actor frameworks = broker + actor model; check the default serializer (Akka defaults to Java serialization — replace it or rolling upgrades break).

## ch-5 — Replication {#ch-5}

Why replicate: latency (geographic proximity), availability (survive node loss), read throughput. Three families: **single-leader**, **multi-leader**, **leaderless**. Replication and partitioning are orthogonal — each partition is typically its own leader/follower group.

### Single-leader mechanics

- All writes go to the **leader**; **followers** apply the leader's replication log in order and serve reads (PostgreSQL ≥9.0, MySQL, MongoDB, Kafka, …).
- **Synchronous** follower: guaranteed up-to-date copy, but one slow/dead sync follower blocks *all* writes — so fully synchronous is impractical. Rule: if a durable second copy is required on failover, run **semi-synchronous** (exactly one sync follower, rest async). Read-scaling fan-outs must be async — with many followers, someone is always down.
- Fully **asynchronous** (common, esp. geo-distributed): writes confirmed before replication → recently committed writes are LOST if the leader dies before replicating. This is a real durability hole, not a corner case.
- New followers come up without downtime: consistent snapshot → copy → connect at the snapshot's log position (LSN/binlog coordinates) → catch up.

### Failover — the hazard list

Failover = detect leader death (typically ~30 s timeout) → elect new leader → reroute writes; the old leader must rejoin as follower. Every step can go wrong:
- Async lag → new leader is missing writes; the old leader's unreplicated writes are usually *discarded*. If external systems saw those writes, discarding corrupts them — canonical: **GitHub 2012**, an out-of-date MySQL follower was promoted, reused auto-increment PKs that Redis had already indexed → private data served to wrong users. Rule: never let externally-visible identifiers depend on state that failover can roll back.
- **Split brain**: two nodes believe they're leader, both accept writes → data loss/corruption. Mitigation: fencing/STONITH (and a badly designed fencing mechanism can shut down *both* nodes).
- Timeout tuning: too long = slow recovery; too short = spurious failovers under load spikes — which add load to an already struggling system. Some teams deliberately keep failover manual.

### Replication log types

| Type | Property | Gotcha |
|---|---|---|
| Statement-based | Ship SQL text | NOW()/RAND()/auto-increment/side effects diverge across replicas — abandoned (MySQL auto-switches to row-based on nondeterminism) |
| WAL shipping | Ship storage-engine byte log (Postgres, Oracle) | Coupled to storage format → leader/follower must run same version → upgrades need downtime |
| Logical (row-based) | Row-level change records | Decoupled from engine: cross-version replication, parseable by external consumers (**change data capture**) — now the default choice |
| Trigger-based | App-level triggers to shadow tables | Most flexible (subset, cross-DB); highest overhead and bug rate |

### Replication lag — the three read anomalies (know these by name)

**Eventual consistency** is not a config value; it's "the lag is unbounded". Three specific promises you can make and how:
1. **Read-after-write (read-your-writes)**: user writes then reads a stale follower → their own change is missing → they think it's lost. Fixes: read own-modifiable data from the leader; read from leader for N seconds after a write; client remembers last-write timestamp (logical LSN preferred) and only reads replicas caught up past it. Cross-device: the timestamp must be centralized, and devices may hit different datacenters.
2. **Monotonic reads**: successive reads hit replicas with different lag → user sees data, then it *vanishes* (moving backward in time). Fix: pin each user to one replica (hash of user ID). Detection cue: per-request random/round-robin replica routing.
3. **Consistent prefix reads**: with partitioned writes there is no global write order → observer sees an answer before its question. Fix: write causally related data to the same partition, or track causal dependencies explicitly.
- Rule: if minutes of replication lag would visibly break your UX, design in one of these guarantees (or use transactions) instead of pretending async is sync.

### Multi-leader

- Legitimate uses only: multi-datacenter (one leader per DC, async between DCs), offline-capable clients (device's local DB = a leader), collaborative editing. Rule: within a single datacenter, multi-leader complexity is rarely worth it.
- Fundamental cost: **write conflicts**. Conflict handling options:
  - **Conflict avoidance**: route all writes for a record to one "home" leader — breaks when the home DC fails or the user relocates.
  - **Last write wins (LWW)**: highest timestamp survives, others *silently discarded* — data loss by design; only safe for write-once/immutable keys (→ ch-8 clock hazards). Cassandra's only method.
  - Merge values, record the conflict for app-level resolution on read (Riak siblings), or **CRDTs** (data structures that merge deterministically, including deletions).
- Canonical merge bug: Amazon's cart resolution preserved additions but not removals → deleted items reappeared. Deletion under merge requires **tombstones**.
- All-to-all topology: writes can arrive out of causal order (update before its insert) — timestamps can't fix this (clock skew); **version vectors** can. Star/circular topologies: single node failure interrupts replication.

### Leaderless (Dynamo-style: Riak, Cassandra, Voldemort)

- No failover: client writes to all n replicas in parallel, succeeds after w acks; reads query r nodes and take the newest version. **Quorum condition w + r > n** (typical n=3, w=r=2) makes overlap likely — but is NOT a linearizability guarantee (→ ch-9).
- Stale reads remain possible even with w+r>n: **sloppy quorum** in effect; two concurrent writes; write concurrent with read; write succeeded on <w replicas (not rolled back!); a restored-from-old-replica node re-enters. Leaderless generally provides *none* of the three lag guarantees above.
- Repair paths: **read repair** (reader writes newer value back to stale replicas — only heals frequently-read keys) + **anti-entropy** (background diff; unordered, may lag; Voldemort lacks it → rarely-read keys can rot).
- **Sloppy quorum** (Riak default on; Cassandra off): during a partition, accept writes on reachable non-home nodes for durability, then **hinted handoff** returns them home. Consequence: w+r>n no longer implies reading the latest value.
- Concurrency bookkeeping: **happens-before** — A precedes B iff B knew about A; otherwise concurrent (wall-clock time is irrelevant). Version numbers per key let the server classify; clients must read before writing and merge siblings; multiple replicas require **version vectors** passed to the client as causal context.

## ch-6 — Partitioning {#ch-6}

Terminology map: partition = shard (Mongo/ES) = region (HBase) = tablet (Bigtable) = vnode (Cassandra/Riak) = vBucket (Couchbase). Goal: spread data AND load evenly; a disproportionately loaded partition is a **hot spot**, the imbalance is **skew**.

### Key-range vs hash partitioning

- **Key-range** (HBase, Bigtable, RethinkDB): sorted keys per partition → efficient range scans. Failure mode: sequential keys (timestamps!) send all today's writes to one partition. Fix: prefix the key with something distributing (sensor ID before timestamp) and fan range queries per prefix.
- **Hash partitioning**: even load, destroys ordering → range queries scatter to all partitions. Rule: never use a language built-in hash (Java `hashCode`, Ruby `hash`) — not stable across processes; use MD5/FNV-style.
- Cassandra's compromise: compound primary key — hash the first column to pick the partition, sort by the remaining columns within it → efficient "all of user X's events by time" queries.
- **Hot key** despite hashing (identical celebrity ID hashes identically — Justin Bieber ≈ 3% of Twitter's servers): only app-level relief — append a random suffix to split one key into N keys, at the price of fan-out reads and bookkeeping. Apply only to *known* hot keys.

### Secondary indexes across partitions

| | Local (document-partitioned) index | Global (term-partitioned) index |
|---|---|---|
| Write | One partition (fast, atomic) | Multiple index partitions (needs distributed txn or async update → stale index) |
| Read | **Scatter/gather** every partition; tail-latency amplification | Single index partition (fast) |
| Users | Mongo, Riak, Cassandra, ES, Solr, VoltDB | DynamoDB GSI, Riak search, Oracle warehouse |

Detection cue: a "find by non-key attribute" endpoint on a locally-indexed store = hidden all-partition fan-out; expect p99 trouble as partition count grows.

### Rebalancing

- **Never `hash mod N`**: changing node count N remaps almost every key (123456 → node 6 of 10, node 3 of 11, node 0 of 12) → mass migration. Rebalancing must move only what's necessary.
- Strategies: **fixed partition count** (create far more partitions than nodes, e.g. 1,000 for 10 nodes; move whole partitions on node add — Riak/ES/Couchbase/Voldemort; partition count = your max node count, choose generously); **dynamic split/merge** (HBase splits at 10 GB; adapts to data volume; empty DB starts as 1 partition → **pre-split** if you know the key distribution); **proportional-to-nodes** (Cassandra: 256 vnodes/node; new node splits random partitions).
- Rule: keep a human in the rebalancing loop. Fully automatic rebalancing + automatic failure detection is dangerous: a slow-but-alive node gets declared dead, its load rebalanced onto already-loaded nodes → cascading failure. (Systems generate a plan; an admin commits it.) ↔ release-it: same self-amplifying failure shape as retry storms.

### Request routing

Three options: any-node-forwards (gossip; Cassandra/Riak), dedicated routing tier (partition-aware LB), or partition-aware clients. Keeping the routing map current *is a consensus problem* → most systems outsource it to **ZooKeeper** (HBase, Kafka, SolrCloud); analytic MPP stores add full parallel query execution on top.

## ch-7 — Transactions {#ch-7}

### ACID, precisely

- **Atomicity** = *abortability* (all-or-nothing on fault) — nothing to do with concurrency. Its payoff: safe retries.
- **Consistency** = app-defined invariants; a property of the *application*, not the DB ("tossed in to make the acronym work" — Hellerstein). The DB can only help via constraints.
- **Isolation** = concurrent transactions don't step on each other; the ideal is serializability, rarely the default.
- **Durability** = fsync'd WAL and/or replication. "Perfect durability does not exist."
- Rule: "ACID compliant" is marketing; isolation-level names are not standardized in behavior. Verify what a specific DB actually guarantees (Hermitage test suite).

### The isolation-anomaly catalog

Each row: what it is → canonical example → weakest level that prevents it → detection cue in code.

| Anomaly | Canonical example | Prevented by | Code shape to flag |
|---|---|---|---|
| **Dirty read** (see uncommitted data) | Unread-mail counter shows half of a multi-object update; reading data later rolled back | Read committed | Reads that require coherent multi-object state |
| **Dirty write** (overwrite uncommitted data) | Car sale: listing goes to Bob, invoice to Alice | Read committed (row write locks) | Interleaved multi-table writes |
| **Read skew** (non-repeatable read) | $500+$500 accounts; mid-transfer reader sees total $900 | Snapshot isolation (MVCC) | Long scan (backup, analytics, integrity check) over live writes |
| **Lost update** (two read-modify-write cycles; one clobbers) | Two counter increments 42→43 instead of 44; full-document wiki save | Atomic ops / `SELECT FOR UPDATE` / auto-detection / CAS | Read value → modify in app code → write back |
| **Write skew** (read shared premise, write *different* rows, invariant breaks) | Two on-call doctors both read "2 on call ≥ 2" and both sign off → zero on call | Serializable ONLY | `SELECT`/count checks a precondition → app decides → write changes that precondition |
| **Phantom** (a write changes another txn's *search result*; the premise is row *absence*, so nothing exists to lock) | Meeting-room double-booking; username claim; double-spend | Serializable / next-key locks / materialized conflicts | INSERT gated on "no matching rows" query |

- **Snapshot isolation / MVCC**: every transaction reads a consistent snapshot; readers never block writers, writers never block readers. Implementation: versioned rows (`created_by`/`deleted_by` txids); updates = delete + insert.
- Naming trap (memorize): snapshot isolation is called **"repeatable read" in PostgreSQL and MySQL**, and **"serializable" in Oracle**. Oracle's maximum setting therefore does NOT prevent write skew. IBM DB2's "repeatable read" is actual serializability. MySQL/InnoDB's "repeatable read" does not even detect lost updates. "Nobody really knows what repeatable read means."

### Lost updates — options ranked

1. Atomic DB operation (`UPDATE counters SET value = value + 1 …`) — use whenever expressible.
2. Explicit lock: `SELECT ... FOR UPDATE` — when the decision logic can't live in one statement.
3. Automatic detection + abort (free with snapshot isolation in PostgreSQL/Oracle/SQL Server — *not* MySQL) — retry on abort.
4. Compare-and-set (`UPDATE ... WHERE value = old`) — verify the DB doesn't evaluate the WHERE against an old snapshot.
- Replicated stores (multi-leader/leaderless): locks and CAS don't apply — there is no single up-to-date copy. Use commutative operations / CRDTs; beware LWW defaults.

### Retry rules

- Retry on transient aborts (deadlock, serialization failure, failover) with exponential backoff and a retry cap; do NOT retry constraint violations (permanent) and do NOT blind-retry overload (makes it worse ↔ release-it retry storms).
- A committed-but-ack-lost transaction is re-executed by a retry: dedup at app level (→ ch-12 request IDs). Side effects outside the DB (emails) fire again on retry. Note: popular ORMs (ActiveRecord, Django) don't retry aborts — they surface exceptions.

### Serializability — three implementations

1. **Actual serial execution** (VoltDB/H-Store, Redis, Datomic): one transaction at a time on one core. Preconditions: entire active dataset in RAM, every transaction short + submitted as a **stored procedure** (interactive multi-statement round-trips would stall the single thread), throughput within one core or cleanly partitionable (cross-partition ≈ 1,000 writes/s, orders of magnitude slower).
2. **Two-phase locking (2PL)** (MySQL/InnoDB serializable, SQL Server): shared locks to read, exclusive to write — readers block writers AND writers block readers (exact opposite of MVCC). Phantoms need **predicate locks**, in practice approximated by **index-range (next-key) locks** (degrading to whole-table locks without a suitable index). Costs: frequent deadlocks (auto-abort + retry), unstable tail latency, throughput collapse under contention. Not to be confused with 2PC.
3. **Serializable Snapshot Isolation (SSI)** (PostgreSQL ≥9.1 `SERIALIZABLE`, FoundationDB): optimistic — run on a snapshot, track read/write dependencies, abort at commit if the premise went stale. Readers don't block writers → predictable latency. Weakness: high contention → high abort rate; wants spare capacity and short read-write transactions (long read-only ones are fine).
- Choice rule: contention low + capacity available → SSI; contention high and unavoidable → 2PL or serialize actual execution; and first try to *remove* contention (atomic/commutative ops).

### Exemptions

- Single-object reads/writes get atomicity + isolation from virtually every storage engine — no transaction needed. "Lightweight transactions" (CAS, atomic increment) are single-object features, not transactions.
- Multi-object transactions become *necessary* with: foreign-key/reference updates across rows, denormalized data kept in sync, secondary indexes (they're separate objects).
- Weak isolation is a legitimate choice — but only after you've checked this chapter's catalog against your access patterns, not by default ignorance.

## ch-8 — The Trouble with Distributed Systems {#ch-8}

A single computer is deterministic: things work or everything fails. A distributed system has **partial failure**: some parts broken, nondeterministically, and *you often cannot even know whether an operation succeeded*. Everything in this chapter assumes honest-but-unreliable nodes (no Byzantine faults).

### Unreliable networks

- On an async packet network, no response is indistinguishable among: request lost, remote node down, remote node paused, response lost, response delayed. The ONLY information a timeout gives you: "I didn't hear back." The request may still have executed (→ retries need idempotence).
- Real-world fault rates: medium DC ≈ 12 network faults/month (half isolate one machine, half a rack); switch software upgrades can delay packets >1 min; NICs fail one-directionally; sharks bite undersea cables; redundant network gear doesn't protect against the leading cause — human misconfiguration.
- Rule: network fault handling must be *defined and tested* (fault injection), not assumed rare. Untested error paths deadlock or lose data. "Handling" may legitimately be "show an error."
- TCP ack ≠ processed: require an application-level positive response. TCP RST/FIN tells you no process is listening — not how much of your request was handled before a crash.
- Timeout selection has no correct answer: short → false positives (premature failover, duplicate actions, load shifted onto overloaded survivors → cascade); long → users wait. Best practice: measure the RTT distribution continuously and set/adapt timeouts from it (**Phi Accrual failure detector** — Cassandra, Akka). Variable delay is mostly *queueing* (switch buffers, CPU run queues, VM scheduling, TCP flow control), worst near saturation. ↔ release-it ch-4/5: DDIA explains *why* no static timeout is right; release-it supplies the pattern kit around it.

### Unreliable clocks

- Two clocks per machine: **time-of-day** (wall; NTP-synced; can jump backward/forward) and **monotonic** (always advances; only meaningful as a difference on one node). Rule: durations and timeouts → monotonic clock; wall-clock timestamps → never for ordering or elapsed time. Detection cue: `System.currentTimeMillis()`/`time.time()` differences in timing code.
- Magnitudes: crystal drift ~200 ppm (≈17 s/day unsynced); NTP over internet ≥ ~35 ms error, spiking to ~1 s; VM clocks pause tens of ms; leap seconds have crashed major systems (mitigate by *smearing*); regulated HFT must hit 100 µs (special hardware).
- **LWW + wall clocks silently drops writes**: a node with a fast clock generates timestamps that out-rank causally *later* writes from a lagging-clock node — data vanishes with no error. Rule: order events with **logical clocks** (counters, version vectors), not physical time. A physical timestamp is really a confidence interval; only Google's **TrueTime** (GPS/atomic, ~7 ms bound) exposes that interval — Spanner *waits out the interval* before commit to get real ordering.

### Process pauses

- Any thread can stop for a long time at any point: stop-the-world GC (occasionally minutes), VM suspend/live-migration, laptop lid, CPU steal, swapping/thrashing, sneaky synchronous disk I/O (Java classloading). The node doesn't know it slept; meanwhile the cluster declared it dead.
- Consequence: code of the form "check lease still valid → do the write" is broken by a pause between check and write.
- Canonical corruption sequence (real HBase bug): client 1 acquires lock/lease → long GC pause → lease expires, client 2 acquires lock and writes → client 1 wakes, still believes it holds the lease, writes → corruption.
- **Fencing tokens** — the fix, exact mechanism: the lock service hands out a monotonically increasing token with every grant (ZooKeeper: `zxid`/`cversion`); every write to the protected resource carries the token; the *resource itself* remembers the highest token seen and rejects lower ones. Client-side lease checking alone can never be safe — enforcement must be at the resource. Rule (falsifiable): a distributed lock/lease whose protected resource does not check a fencing token does not protect anything.
- Mitigation for GC: treat major GC like a planned brief outage (drain traffic first), or restrict GC to short-lived objects + periodic rolling restarts (trading systems). Hard real-time = specialized embedded domain, not server software.

### Truth, models, correctness

- **Truth is defined by the majority**: a node cannot trust its own judgment of its status (it may be paused, semi-disconnected, or "limping" — e.g., a NIC driver bug dropping to 1 Kb/s). A quorum can declare a node dead; the node must comply even if it feels alive.
- Byzantine fault tolerance is for aerospace radiation and mutually untrusting multi-org systems (blockchains). In your own datacenter: don't build BFT; do validate/sanitize client input (server is authoritative), add app-level checksums, sanity-check inputs, use multiple NTP servers.
- System models — pick assumptions explicitly: timing = synchronous / **partially synchronous** (realistic: usually well-behaved, occasionally unbounded) / asynchronous; nodes = crash-stop / **crash-recovery** (stable storage survives, memory lost) / Byzantine. Practical algorithms target partially synchronous + crash-recovery.
- **Safety** ("nothing bad happens" — violation is a pointable, irreversible event) vs **liveness** ("something good eventually happens"). Rule: require safety to hold under ALL conditions, including total network failure; liveness may carry caveats ("if a majority is up"). Eventual consistency is a liveness property; uniqueness and fencing-token monotonicity are safety properties.

## ch-9 — Consistency and Consensus {#ch-9}

### Linearizability

- Definition: the system behaves as if there were one copy of the data and every operation took effect atomically at some instant — a **recency guarantee**: once any read returns a new value, every subsequent read (any client) must too. Detection cue for violation: a value "flips back" to an older state after a newer one was observed.
- **Linearizability ≠ serializability**: serializability is transaction isolation (some serial order, not necessarily real-time); linearizability is single-object recency. Combined = **strict serializability**. 2PL and actual-serial-execution are typically linearizable; snapshot isolation and SSI are NOT (they read from a snapshot by design).
- When you actually need it (checklist):
  1. Locks and leader election (all nodes must agree who holds it) — plus fencing tokens.
  2. Hard uniqueness constraints (username, seat, non-negative balance) — a distributed compare-and-set.
  3. Cross-channel timing: one system writes to store A and signals via channel B; the B-consumer reads A and races its recency (e.g., file upload + resize-queue message).
- When you don't (exemptions): constraints fixable after the fact (overbooking + apology → ch-12), foreign-key/attribute constraints, caches and analytics, service discovery (DNS is stale by design and that's correct).
- What provides it: consensus systems (ZooKeeper/etcd) yes; single-leader — potentially, if you read from the leader and failover is sound; multi-leader — no; **leaderless quorums even with w+r>n — no** (variable network delays produce non-linearizable interleavings; LWW clocks and sloppy quorums make it worse). Riak doesn't attempt it; Cassandra's LWW loses it on concurrent writes. Linearizable CAS on a leaderless store requires a consensus round.
- **CAP, correctly**: partitions are a *fault*, not a design choice — the real statement is "when Partitioned, choose Consistent or Available." Formally CAP covers only linearizability + network partitions, nothing about delay, dead nodes, or other trade-offs; the author's verdict: mostly historical, superseded by better-scoped results.
- Cost: linearizability is slow *all the time*, not just during faults (Attiya-Welch: response time necessarily proportional to network-delay uncertainty). Even multi-core CPUs drop linearizability (store buffers) for speed. Reason to drop it: performance more than fault tolerance.

### Ordering and causality

- **Causal consistency** — preserve happens-before, allow concurrent ops to be unordered (partial order, like git history) — is the strongest model that stays available under partitions and doesn't pay the network-delay tax. Many "we need linearizability" claims actually need only causal.
- **Lamport timestamps**: (counter, nodeID); every message carries the max counter seen; receivers fast-forward. Gives a total order *consistent with* causality — but cannot distinguish concurrent from causally-related (version vectors can; they're bulkier).
- Why timestamps can't enforce uniqueness: the total order is only knowable *after* collecting all operations; a node deciding "now" can't rule out an in-flight lower-timestamped claim without asking every node. You need to know when the order is *finalized* → **total order broadcast**.

### Total order broadcast and consensus

- **Total order broadcast (TOB)**: reliable delivery (to one ⇒ to all) + same delivery order everywhere; the order is fixed at delivery (no retroactive inserts). It IS: a replication log (state machine replication), a fencing-token generator (zxid), a serializable-transaction substrate (deterministic stored procedures in log order).
- Equivalence theorem (the chapter's spine): **linearizable compare-and-set ≡ total order broadcast ≡ consensus.** Build linearizable writes from TOB: append your tentative claim, read the log back, you win iff your message is the first claim for that key. Linearizable *reads* need one of: sequence the read through the log, ZooKeeper `sync()`, or read from a synchronously-updated replica.
- **FLP impossibility**: no deterministic consensus algorithm can always terminate in the fully asynchronous crash model — but timeouts or randomness escape it in practice; it's a caution, not a prohibition.

### Two-phase commit (2PC) — atomic commit ≠ consensus quality

- Flow: coordinator sends *prepare*; each participant durably ensures it *can* commit under all circumstances and answers yes (surrendering the right to abort); coordinator durably logs the decision (**the commit point**), then broadcasts it, retrying forever.
- Failure anatomy: participant crash before yes → abort, fine. Coordinator crash after participants voted yes → participants are **in doubt**: they can neither commit nor abort unilaterally and must hold their locks — blocking reads/writes on those rows until the coordinator recovers (or an admin resolves by hand). 2PC is a *blocking* protocol; 3PC only fixes this under bounded delay (unrealistic).
- **XA** (heterogeneous 2PC, 1991 C API): coordinator usually lives in the app process → app crash strands participants in-doubt; lowest-common-denominator (no cross-system deadlock detection, no SSI); MySQL distributed transactions measured >10× slower than single-node. Rule: avoid XA across heterogeneous systems; prefer log-based derivation (→ ch-11/12). Database-*internal* distributed transactions (same engine everywhere) can work well — the exemption.
- 2PC vs fault-tolerant consensus: 2PC needs EVERY participant's yes and has an unelected coordinator with no recovery protocol; consensus needs only a majority and defines recovery.

### Fault-tolerant consensus (Paxos, Raft, Zab, VSR)

- Formal properties: uniform agreement, integrity, validity (safety) + termination (liveness; requires a functioning majority). Safety holds even when the majority fails — progress stops, corruption never happens.
- Mechanics they share: **epoch numbers** (term/ballot/view) with a unique leader *per epoch*; two voting rounds (elect leader; vote on each proposal) whose quorums must overlap — that overlap is how a leader learns whether a higher epoch has superseded it.
- Costs (why not everywhere): synchronous-replication latency; strict majority (3 nodes to survive 1, 5 to survive 2; minority partitions block); mostly-static membership; timeout-based leader detection thrashes on variable-latency networks (Raft is known to bounce leadership over one flaky link). Rule: never implement consensus yourself — the field's track record on homegrown variants is dismal; use ZooKeeper/etcd or a proven library.
- **ZooKeeper/etcd** = consensus outsourced: small, memory-resident, totally-ordered config store with linearizable atomic ops (locks/leases via CAS), fencing tokens (zxid), ephemeral nodes (session-based failure detection), and watches (change notification). Use for leader election and partition assignment — data that changes on the scale of minutes, NOT request-rate application state. Service discovery doesn't need consensus (stale DNS answers are fine); membership services do.

## ch-10 — Batch Processing {#ch-10}

Three system types: services (online; optimize response time), batch (bounded input → output; optimize throughput), stream (unbounded, near-real-time; ch-11). Batch's core invariant: input is **bounded and immutable**; the job knows when it's done.

### The Unix template

- Unix philosophy = do one thing well; every program's output can be another's input via a **uniform interface** (byte stream / newline records); separate logic from wiring (stdin/stdout); immutable inputs make experimentation safe (rerun, inspect any stage, checkpoint to a file).
- Sort vs in-memory aggregation rule: if the distinct-key working set fits in RAM, an in-memory hash table is fine; if not, sort — mergesort is sequential-I/O-friendly and GNU `sort` spills to disk and parallelizes automatically. Detection cue: unbounded distinct-key cardinality feeding an in-memory map.

### MapReduce

- = Unix pipes made distributed: mapper extracts sorted (key, value) pairs; the framework's **shuffle** routes-and-merges by key; reducer iterates each key's values. Scheduler puts computation near the data (mapper on the block's replica holder). Output valid only on full job success; failed tasks retried safely *because inputs are immutable and partial output is discarded*.
- Workflows chain via output/input directories (50–100-job chains are normal; Oozie/Airflow etc. manage them).
- Why eager disk materialization: designed for Google's mixed datacenters where a 1-hour task has ~5% preemption risk (≫ hardware failure) — a 100-task job sees >50% chance of losing a task. On dedicated clusters this rationale disappears (→ dataflow engines).

### Join strategy decision table (batch)

| Situation | Strategy |
|---|---|
| No assumptions about either input | **Reduce-side sort-merge join** (map by join key; secondary sort delivers the dimension record first; one record in memory at a time) |
| One input fits in memory | **Broadcast hash join** (map-only; hash table per mapper; Pig "replicated join", Hive "MapJoin") |
| Both inputs partitioned identically (same key/hash/count) | **Partitioned hash join** (each mapper loads only its partition of the small side) |
| Both partitioned AND sorted alike | **Map-side merge join** (no memory limit at all) |

- Iron rule: never query an external DB per record inside a batch job — throughput collapses to network round-trips, results become nondeterministic (DB changes mid-job), and you overwhelm the DB. Take a snapshot/copy into the cluster instead.
- **Skew / hot keys** (linchpin objects — celebrities): one reducer becomes the **straggler** the whole workflow waits on. Fixes: sampled hot-key detection → spread hot keys over random reducers + replicate the other side (Pig skewed join); explicit hot-key list (Crunch, Hive metadata + map-side join); two-stage aggregation (random partial aggregate → combine).

### Batch outputs

- Never write to an external live DB record-by-record from a job (same reasons as above, plus externally visible partial results defeat all-or-nothing retry). Build immutable DB files inside the job → bulk load → **atomic switchover** (Voldemort serves old files until new ones are copied, and can switch back).
- **Human fault tolerance** — the philosophy: immutable input + full-replace output means a buggy deploy is fixed by rolling back code and re-running; a read-write database offers no such mercy. Minimize irreversibility. **Sushi principle**: "raw data is better" — store raw, interpret at read (schema-on-read data lake); the interpreted view can always be regenerated.

### Beyond MapReduce

- **Dataflow engines** (Spark, Tez, Flink) run the whole workflow as one DAG: no per-stage HDFS materialization, operators start when input is ready, sorts only where needed. Fault tolerance by *recomputation* (Spark RDD lineage, Flink checkpoints) — which requires operators to be **deterministic**: hash-map iteration order, random seeds, and clock reads all silently break recompute (cascading downstream kills). If intermediate data ≪ source or the computation is CPU-heavy, materialize instead of recompute.
- **Pregel/BSP** for iterative graph algorithms: vertex-local function + messages along edges + iteration barriers; state persists across iterations.
- Single-machine exemption (falsifiable): if the graph (or dataset) fits in one machine's RAM — or even one machine's disk (GraphChi) — a single-machine algorithm likely *outperforms* the distributed cluster; cross-machine messaging dominates distributed graph runtime. Check dataset-fits-where before reaching for a cluster.
- Declarative sprinkles converge batch with MPP: cost-based optimizers pick join strategies, column storage + vectorized inner loops — while retaining arbitrary-code callbacks (the thing MPP databases lack).

## ch-11 — Stream Processing {#ch-11}

Streams = unbounded inputs, jobs that never finish. **Event**: small immutable record with a timestamp, written once, read by many consumers via topics.

### Messaging: the two broker families

- Producer-faster-than-consumer options: drop, buffer, or **backpressure** (block the producer — what Unix pipes and TCP do). Choose per loss tolerance: metrics/sensor feeds tolerate loss (UDP, StatsD — counters become approximate); event *counting* does not.
- Brokerless direct messaging (UDP multicast, ZeroMQ, webhooks) is low-latency but assumes consumers are online; a crashed consumer misses events.

| | AMQP/JMS broker (RabbitMQ, ActiveMQ, SQS) | Log-based broker (Kafka, Kinesis) |
|---|---|---|
| Delete on ack | Yes — messages are transient | No — log retained by segment expiry |
| Ordering | Broken by redelivery + load balancing | Guaranteed within a partition |
| Parallelism | Per message | Per partition (≤ partition count) |
| Replay | Impossible | Trivial — reset the consumer offset |
| Fits when | Expensive per-message work, order irrelevant | High throughput, order matters, replay wanted |

- Log-based consumer = a database follower: one offset per partition (no per-message ack bookkeeping). Slow consumers just fall behind without affecting others — but monitor lag, because offsets pointing into deleted segments silently skip messages.
- Buffering arithmetic: 6 TB disk / 150 MB/s write = ~11 hours at maximum rate; real deployments retain days–weeks. Throughput is constant regardless of retention (everything is written to disk anyway).
- Head-of-line note: one slow message stalls its whole partition in a log broker — a genuine reason to pick AMQP-style for slow, independent jobs.

### Databases and streams

- **Dual writes are the bug** (name it in review): application code writes to the DB *and* separately to the search index / cache / other store. Two failure modes: (a) race — the two systems apply concurrent writes in different orders → permanent, silent divergence; (b) one write succeeds, the other fails → divergence. Root cause: no single authority on write order.
- Fix: pick ONE system of record; derive everything else from its ordered change stream. **Change data capture (CDC)** = parse the replication log (Debezium/Maxwell for MySQL binlog, Bottled Water for Postgres WAL, Mongoriver) and republish through a log broker; source DB becomes the leader, derived systems followers. Bootstrapping: consistent snapshot pinned to a log offset, then apply changes.
- **Log compaction** (Kafka): for streams keyed by primary key where each update supersedes the last, keep only the latest record per key (tombstone = delete) — disk cost tracks DB size, not write history, and a new consumer can rebuild full state from offset 0 with no snapshot.
- **Event sourcing** vs CDC: event sourcing stores *application-intent* events ("student cancelled enrollment"), CDC captures low-level state changes ("row deleted"). Intent events don't supersede each other → log compaction does NOT apply; snapshots are an optimization only. **Command vs event**: validate the command synchronously first; once accepted it becomes an immutable *fact* that consumers may not reject.
- The slogan set: changelog = the state's derivative; state = the changelog's integral; "the truth is the log; the database is a cache of a subset of the log" (Helland). **CQRS**: derive multiple read-optimized views from one event log — the normalization-vs-denormalization argument dissolves when views are disposable.
- Immutability limits: high-churn datasets stress compaction/GC; real deletion (privacy law) is genuinely hard — copies hide in snapshots, SSD remapping, backups (Datomic "excision").

### Time and windows

- Rule: aggregate by **event time**, not processing time — a redeploy or backlog replay otherwise manufactures fake rate spikes and makes reprocessing nondeterministic. Exemption: processing time is fine when event→processing lag is negligible and replay never happens.
- **Stragglers** (events arriving after their window closed): either drop + track a dropped-events metric with alerting, or emit corrections/retractions. **Watermark** = "no events earlier than t will follow" — hard with many producers.
- Untrusted device clocks: log three timestamps (event occurred @device, sent @device, received @server); offset = received − sent; correct the event time.
- Window types: **tumbling** (fixed, disjoint), **hopping** (fixed, overlapping — smoothing), **sliding** (any events within interval t of each other), **session** (per-user activity until an inactivity gap).

### Stream joins

- **Stream-stream** (e.g., search events × click events within an hour, either order): keep windowed indexed state of both sides; emit on match or on expiry-without-match.
- **Stream-table** (enrichment): don't query the DB per event (slow, nondeterministic) — hold a local replica in the processor, kept fresh by subscribing to the table's CDC changelog.
- **Table-table**: two changelogs in → changelog of the materialized join out (Twitter timelines = tweets ⋈ follows, maintained incrementally).
- **Time-dependence problem**: if ordering across the two inputs is undefined, the join is nondeterministic (which tax rate was current at sale time?). Fix: **slowly changing dimension** — version every record of the joined table and reference the version ID at event time; deterministic, but forecloses log compaction.

### Exactly-once (effectively-once) in streams

Failure handling must not double-count. Mechanisms, weakest precondition first:
1. **Microbatching** (Spark Streaming, ~1 s batches) and **checkpointing** (Flink barrier snapshots): exactly-once *within* the framework only — any output that already left (DB write, email) happens again on restart.
2. **Internal atomic commit**: state + output + offset advance commit together (Dataflow, VoltDB, Kafka transactions) — deliberately NOT heterogeneous XA.
3. **Idempotence**: set-key-to-value is naturally idempotent; make increments idempotent by storing the triggering message offset with the value and skipping already-applied offsets. Preconditions: deterministic processing, stable replay order (log broker), no concurrent writers — and **fencing on failover** (a presumed-dead node may still write).
- Rebuild processor state from: replicated remote store (slow), periodic local-state snapshots (Flink→HDFS), a compacted changelog topic (Kafka Streams), or replaying input.

## ch-12 — The Future of Data Systems {#ch-12}

### Integration: log-derived data beats distributed transactions

- No single tool serves all access patterns; integration is the real engineering problem. Principle: funnel writes through ONE totally-ordered event log; derive every other representation (index, cache, warehouse, ML features) by deterministic, idempotent consumers — **state machine replication** at organization scale. (Same detection cue as ch-11: any direct dual write is a bug.)
- vs distributed transactions: XA/2PC gives linearizable timeliness but poor fault tolerance (failure amplification: any participant down aborts everyone) and poor performance; log-based derivation is async (weaker timeliness) but contains faults locally — a dead consumer buffers and catches up. Author's stance: for heterogeneous systems, log-based wins; transactions remain fine *within* one system.
- Total order has scaling limits: order is per-partition only; no cross-DC, cross-microservice, or offline-client global order; TOB ≡ consensus, and geo-scaling consensus throughput is open research. Causality across services can be captured by logical timestamps or by logging what the user *saw* before acting.
- **Lambda architecture** (parallel batch for truth + stream for speed) — its own critique: logic duplicated across two frameworks; merging the two outputs is hard beyond trivial aggregations; incremental batch reintroduces the streaming complexity it was meant to avoid. Superseded by unified engines: replayable log + exactly-once + event-time windowing (Beam/Flink/Dataflow).
- **Unbundling the database**: the org's dataflow is one big database turned inside out — batch/stream jobs are its index-builders and trigger/matview machinery ("`CREATE INDEX` ≈ bootstrap a new follower from a snapshot then tail the log"). Federation unifies *reads*; unbundling unifies *writes* via CDC/logs — writes are the harder, more important half. Exemption (falsifiable): if a single product covers your requirements, USE IT — unbundling buys breadth, not depth; fewer moving parts win otherwise; don't build for scale you don't have.
- Dataflow-first application design: replace synchronous service calls with subscriptions where reads dominate (exchange-rate example: subscribe to rate changes + query the local replica — "the fastest network request is no network request"). **Write path** (eager precompute) vs **read path** (lazy): caches/indexes/materialized views shift the boundary; even end-user devices can sit on the write path (offline clients = log consumers with an offset that catch up on reconnect; React/Redux are already client-side event logs).

### The end-to-end argument (Saltzer/Reed/Clark 1984)

- Dedup, integrity checking, and encryption can only be *complete* at the application endpoints; lower layers (TCP retransmit/dedup, Ethernet checksums, TLS) are performance optimizations, not guarantees. TCP dedups within one connection; a retried HTTP POST is a brand-new transaction to the DB.
- Canonical: `UPDATE … +$11; … −$11; COMMIT` retried after a lost commit-ack transfers $22. Transactions alone did not save you.
- The fix: a **client-generated operation ID** (UUID / request hash) carried through every layer to the store, enforced with a UNIQUE constraint — which works correctly even at weak isolation, and the request table doubles as an event log. Rule (falsifiable): any retryable operation without an end-to-end dedup key will eventually double-execute.

### Constraints without coordination

- Uniqueness enforcement requires consensus — but consensus is cheap when *partitioned by the constrained value*: route every claim for username X (hash) to the same log partition; a single-threaded consumer validates sequentially and emits accept/reject; client watches the output stream. Scales linearly in partitions; generalizes to any constraint whose conflicts can be routed to one partition.
- Multi-partition transfer without atomic commit (canonical): (1) append a single transfer-request message (atomic single-object write) partitioned by request ID; (2) a processor deterministically emits a debit instruction (partition A) and credit instruction (partition B) carrying the request ID; (3) downstream appliers dedup by request ID. Crash anywhere → deterministic replay + dedup = exactly-once, no 2PC.
- **Timeliness vs integrity** — the chapter's key distinction: *timeliness* = readers see up-to-date state (violation = stale read, heals by waiting); *integrity* = no lost/corrupted/contradictory data (violation = permanent until explicitly repaired). "Violations of timeliness are eventual consistency; violations of integrity are perpetual inconsistency." **Integrity matters far more** for most systems (a delayed bank statement is fine; a wrong balance is catastrophic). Log-based dataflow deliberately sacrifices timeliness while making integrity central: atomic single-message writes + deterministic derivation + end-to-end IDs + immutable replayable log.
- **Coordination avoidance + compensating transactions**: many "hard" constraints are actually soft — airlines overbook deliberately; overdrafts get fees; two bookings of one seat get an apology and a rebooking (**compensating transaction**). Decision rule: compare the cost of an apology against the cost of synchronous coordination (which trades inconsistency-apologies for outage-apologies); coordinate only where recovery after the fact is impossible, and don't make the whole system pay for the one constraint that needs it.

### Trust, but verify

- Hardware and software lie occasionally at scale: silent disk bit rot, TCP-checksum-evading corruption, rowhammer, and bugs in the databases themselves (MySQL uniqueness, PostgreSQL serializability have both failed). ACID culture bred *blind trust*; NoSQL weakened guarantees without adding audit mechanisms — the worst of both.
- Rules: if you need to know data is intact, read and check it (HDFS/S3 continuously re-read and compare replicas); restore backups periodically or you don't have backups; prefer event-sourced designs for auditability — deterministic derivation from a hashable immutable log allows re-running the pipeline to verify derived state (and time-travel debugging). End-to-end integrity checks cover every disk, network, and algorithm on the path at once. Merkle trees (certificate transparency) prove membership cryptographically.

### Doing the right thing

- Predictive analytics on people (loans, hiring, recidivism): biased input data yields amplified biased output — "ML is like money laundering for bias"; probabilistic population correctness ≠ individual fairness; opaque scores create "algorithmic prisons" with no appeal; feedback loops compound (bad credit score → joblessness → worse score). Engineers building these systems own part of the accountability.
- Privacy = the right to *choose* what to reveal to whom — surveillance transfers that right to the collector. Data is a **toxic asset**: breaches, subpoenas, future misuse. Rules: purge data when no longer needed; enforce access cryptographically, not by policy; treat users as humans, not optimization metrics.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Latency dashboard/report uses mean or averages percentiles | Report p50/p95/p99 from merged histograms | Mean hides how many users suffer; percentiles don't average | ch-1 |
| Request handler fans out to N backends synchronously | Budget for tail latency amplification; monitor p99 of the fan-out | User sees the max of N calls — rare slowness dominates | ch-1 |
| Read:write ratio ≫ 1 on a hot query | Precompute at write time (fan-out/matview); exempt extreme-fan-out entities | Optimize the dominant operation; celebrities explode write cost | ch-1 |
| App code loops issuing follow-up queries to stitch records | Use a DB with real joins (or restructure) | You're hand-implementing a join, slowly and buggily | ch-2 |
| High write rate on an LSM store (Cassandra/RocksDB/HBase) | Monitor compaction backlog explicitly | Engines don't throttle writes; backlog fills disk and slows reads | ch-3 |
| WHERE on the 2nd column of a concatenated index | Add a dedicated index or reorder | Concatenated indexes serve left-prefixes only | ch-3 |
| Analytics/aggregation queries against the OLTP database | ETL into a separate warehouse/replica | Ad-hoc scans destroy transaction latency | ch-3 |
| New schema field in Protobuf/Thrift | New tag number + optional/default; never reuse or renumber tags | Old data still carries old tags; required-new breaks old readers | ch-4 |
| New/removed Avro field without a default value | Add a default (union with null first) | Breaks backward (add) or forward (remove) compatibility | ch-4 |
| Old code round-trips records written by newer code | Preserve unknown fields through read-modify-write | Model objects silently drop fields they don't know | ch-4 |
| Anything persisted with language-native serialization | Use a schema'd cross-language format | RCE risk, lock-in, no versioning | ch-4 |
| Async replication + auto-failover configured | Assume committed writes can vanish on failover; never leak rollback-able IDs to external systems | Unreplicated writes are discarded; GitHub PK-reuse incident | ch-5 |
| User reads own data right after writing, replicas in path | Provide read-your-writes (leader reads / timestamp gating) | Stale follower makes the user's own write "disappear" | ch-5 |
| Per-request random replica routing | Pin user→replica (monotonic reads) | Otherwise data appears then vanishes across refreshes | ch-5 |
| Multi-leader or leaderless store accepting concurrent writes | Choose an explicit conflict strategy (merge/siblings/CRDT); LWW only for immutable keys | LWW silently discards writes | ch-5 |
| w+r>n quorum treated as strong consistency | Don't — sloppy quorums, concurrent ops, partial writes still yield stale reads | Quorum overlap is probabilistic, not linearizable | ch-5 |
| Timestamp or sequential value as partition key | Prefix/compound key to spread writes | All writes land on one partition (hot spot) | ch-6 |
| `hash(key) mod N` in partition assignment | Use fixed/dynamic partitions with stable key→partition map | Changing N remaps nearly every key | ch-6 |
| Query by non-key attribute on a document-partitioned index | Expect scatter/gather; consider a global index if read-heavy | All-partition fan-out amplifies tail latency | ch-6 |
| Fully automatic rebalancing + automatic failure detection | Keep a human approving rebalance plans | Slow node declared dead → load moved onto strained nodes → cascade | ch-6 |
| Read value → modify in app code → write back | Use atomic op / `FOR UPDATE` / CAS / detection+retry | Lost update under every weak isolation level | ch-7 |
| SELECT checks a precondition, then a write changes it | Serializable isolation (or lock the read set) | Write skew — snapshot isolation does NOT catch it | ch-7 |
| INSERT gated on "no matching rows" query | Serializable / unique constraint / next-key locks | Phantom: absent rows can't be locked | ch-7 |
| Config says "repeatable read" or Oracle "serializable" | Verify actual guarantees per engine | These names mean snapshot isolation (or less) in PG/MySQL/Oracle | ch-7 |
| Transaction retry loop in code | Retry only transient aborts, with backoff + cap + dedup of side effects | Constraint violations are permanent; overload retries amplify | ch-7 |
| Timeout fires on a remote call | Treat outcome as UNKNOWN, not failed; make the op idempotent before retrying | The request may have executed | ch-8 |
| Wall-clock timestamps ordering events / LWW conflict resolution | Use logical clocks / version vectors | Clock skew silently drops causally-later writes | ch-8 |
| Elapsed time measured with time-of-day clock | Use the monotonic clock | NTP jumps make durations negative or huge | ch-8 |
| Distributed lock/lease without fencing token checked at the resource | Add monotonic fencing tokens; resource rejects lower tokens | A GC-paused ex-holder will write after lease expiry; check-then-act breaks under pauses | ch-8 |
| Design claims to need linearizability | Check the checklist: locks/uniqueness/cross-channel only; else causal suffices | Linearizability costs latency at all times | ch-9 |
| Uniqueness constraint across nodes | Route through consensus or a single log partition per value | Uniqueness ≡ consensus; timestamps can't finalize order | ch-9 |
| XA/2PC across heterogeneous systems in a design | Prefer log-based derivation | In-doubt transactions hold locks; coordinator SPOF; >10× slower | ch-9 |
| Homegrown consensus/leader-election code in a diff | Replace with ZooKeeper/etcd/Raft library | Homegrown consensus has a dismal correctness record | ch-9 |
| Batch/stream job queries a live external DB per record | Snapshot or CDC-replicate the DB locally; pick a join strategy | Round-trip bound, nondeterministic, hammers the DB | ch-10 |
| Batch job writes to a live DB record-by-record | Build immutable output files + bulk load + atomic switchover | Partial output escapes retry semantics; enables rollback | ch-10 |
| Dataset/graph fits on one machine | Use the single machine | Cross-machine coordination usually loses to one big box | ch-10 |
| App writes to DB and separately to index/cache (dual writes) | Single system of record + CDC-derived followers | No order authority → permanent silent divergence | ch-11 |
| Windowed aggregation keyed on processing time | Key on event time; handle stragglers explicitly | Redeploys/backlogs manufacture fake spikes; replay breaks | ch-11 |
| Retryable user-facing operation without a dedup key | Client-generated request ID + UNIQUE constraint end-to-end | TCP/transactions don't dedup across connections; double execution | ch-12 |
| Synchronous cross-service coordination for a soft constraint | Optimistic write + compensating transaction (apology) | Coordination trades inconsistency-apologies for outage-apologies | ch-12 |
| Backups/derived data never verified | Periodically restore and re-derive; checksum end-to-end | Silent corruption accumulates; untested backups don't exist | ch-12 |

## Anti-patterns

- **Dual writes** — one code path writes the same logical change to two stores (DB + search index, DB + cache). Cue: two client-issued writes to different systems in one handler. Consequence: permanent silent divergence. (ch-11)
- **LWW as default conflict handling** — Cassandra-style latest-timestamp-wins on mutable keys. Cue: `USING TIMESTAMP`, "last write wins" in config, wall-clock tie-breaking. Consequence: silently discarded writes, worse under clock skew. (ch-5, ch-8)
- **Lease without fencing** — distributed lock holder writes to a resource that doesn't check tokens. Cue: lock client code with no token parameter on the protected write path. (ch-8)
- **Read-modify-write in application code** — load, mutate, save. Cue: `obj = get(); obj.x += 1; save(obj)`. Lost updates at any isolation below serializable unless atomic ops/locking used. (ch-7)
- **Check-then-act on a query result** — count/existence check gates a write. Write skew/phantoms; snapshot isolation won't save you. (ch-7)
- **`hash mod N` partition assignment** — remaps the world on every topology change. (ch-6)
- **Timestamp keys / monotonic partition keys** — all writes to the newest partition. (ch-6)
- **Trusting "repeatable read"/"serializable" labels** — vendor names diverge from behavior; Oracle serializable = snapshot isolation. (ch-7)
- **Distributed-first design** — reaching for a cluster when the data fits one machine; distributed graph processing losing to a laptop. (ch-10)
- **Lambda architecture** — duplicated batch+stream logic with a merge problem; superseded by unified log replay. (ch-12)
- **Blind-trust persistence** — no backup restores, no derived-state verification, no end-to-end checksums. (ch-12)
- **Per-record external DB calls from batch/stream jobs** — throughput death and nondeterminism. (ch-10, ch-11)
- **Averaged percentiles / mean-only latency metrics** — statistically meaningless; hides the tail. (ch-1)

## Applicability & exemptions

- **Single-node, single-object work is exempt from most of this book.** One process + one ACID database: no replication lag, no quorums, no fencing, no consensus, no clock-skew ordering hazards. Single-object reads/writes get atomicity+isolation from any real engine without transactions. Don't demand distributed machinery in review when nothing is distributed.
- **Isolation-anomaly rules need real concurrency on shared rows.** Single-writer systems, append-only workloads, and naturally commutative/idempotent operations don't exhibit lost updates or write skew.
- **LWW is legitimate** for write-once/immutable keys (UUID-keyed caches, content-addressed blobs) — there's nothing to lose.
- **Linearizability is usually not required**: caches, analytics, feeds, service discovery, and any constraint fixable by apology+compensation can run on causal/eventual consistency. Fire linearizability requirements only for locks/leader election, hard uniqueness, and cross-channel races.
- **Byzantine tolerance is out of scope** in a single-org datacenter — validate inputs and secure the perimeter instead; BFT protocols are for aerospace and mutually untrusting parties.
- **Weak timeliness is fine when integrity is preserved** — async derived views are not a defect if the write path is a durable ordered log with end-to-end IDs.
- **Prototypes/unproven products** may consciously trade reliability and scalability for iteration speed (Kleppmann says so explicitly) — flag the trade-off, don't block it.
- **Don't build for hypothetical scale**: rethink at each ~10× load step; premature sharding/unbundling adds the very complexity this book spends 12 chapters taming. If one product meets requirements, use it.
- **Percentile/tail rules apply to services**, not batch jobs (batch cares about throughput) — and beyond ~p999 the cost usually exceeds the benefit.
- **Author's stated non-answers**: B-tree vs LSM (benchmark your workload), timeout values (measure your RTT distribution), sync vs async replication trade-offs (per-durability-need) — treat any absolute claim on these as suspect.

## Candidate lexicon rows

| read-modify-write of a stored value in app code | **No unguarded read-modify-write** — concurrent cycles silently clobber each other (lost update) at every default isolation level | Is this load→mutate→save expressible as an atomic op, or locked/CAS-guarded? | blocker | write | src: designing-data-intensive-applications ch-7 |
| a SELECT/count/existence check gates a subsequent write | **Write-skew check-then-act** — the premise can change between read and write; snapshot isolation will not catch it | Does an invariant span rows this transaction reads but doesn't write — and is isolation truly serializable? | blocker | review | src: designing-data-intensive-applications ch-7 |
| code writes the same logical change to two stores (DB + index/cache) | **No dual writes** — without a single order authority the two systems diverge permanently and silently | Which system is the system of record, and does the second copy derive from its change log? | blocker | plan | src: designing-data-intensive-applications ch-11 |
| distributed lock/lease guarding writes to storage | **Fence the resource, not the client** — a GC-paused ex-leaseholder will write after expiry; only monotonic tokens checked at the resource stop it | Does the protected resource reject writes bearing a lower fencing token? | blocker | plan | src: designing-data-intensive-applications ch-8 |
| wall-clock timestamps used to order events or resolve conflicts | **Logical clocks for ordering** — clock skew makes LWW drop causally-later writes with no error | Could two nodes' clock skew reorder these events; should this be a counter/version vector? | blocker | write | src: designing-data-intensive-applications ch-8 |
| retryable operation crossing a network (RPC, HTTP POST, job enqueue) | **End-to-end request ID** — TCP and DB transactions don't dedup across connections; a retried request double-executes | Does a client-generated ID travel to the final store and hit a UNIQUE constraint? | blocker | write | src: designing-data-intensive-applications ch-12 |
| schema change to a serialized format (Protobuf/Thrift/Avro/JSON contract) | **Both-ways compatible evolution** — rolling upgrades mean old readers meet new data and vice versa; tags/defaults are the contract | New tag + optional/default? No tag reuse? Avro default present? Unknown fields preserved on rewrite? | blocker | review | src: designing-data-intensive-applications ch-4 |
| reads served by async replicas after a user-visible write | **Read-your-writes routing** — a stale follower makes the user's own write vanish | After this write, can the same user's next read hit a replica that hasn't applied it? | should | plan | src: designing-data-intensive-applications ch-5 |
| timestamp/sequential partition key, or `hash mod N` assignment | **Skew-proof partitioning** — monotonic keys hot-spot one partition; mod-N remaps everything on resize | Where do today's writes land, and what moves when a node is added? | should | review | src: designing-data-intensive-applications ch-6 |
| latency reported as a mean, or percentiles averaged across hosts | **Percentiles from histograms** — the mean hides the tail; percentiles don't average | What are p50/p95/p99 from merged histograms, and who lives in the tail? | should | review | src: designing-data-intensive-applications ch-1 |
| design invokes consensus/linearizable storage/2PC | **Coordination only where apologies can't work** — coordination trades inconsistency-apologies for outage-apologies and taxes every request | Is this a lock, hard uniqueness, or cross-channel race — or would a compensating transaction do? | judgment | plan | src: designing-data-intensive-applications ch-9 |
| cluster/distributed framework proposed for a dataset of known size | **Single machine first** — if data fits one machine's RAM (or disk), it usually outperforms the cluster | Does this actually exceed one big machine, at the load we have today? | judgment | plan | src: designing-data-intensive-applications ch-10 |
