# Embedding Search Optimizations

This note preserves the post-MVP search-evolution roadmap that was previously misfiled under `docs/agentic/rules/`. It is deferred planning material, not a current operating rule.

## Intent

Evolve the recognition service from the current brute-force embedding scan toward a more scalable vector-search pipeline without losing observability or parity confidence.

## Deferred Roadmap

1. Establish baseline metrics.
   - Capture end-to-end latency for recognition flows at representative roster sizes.
   - Record memory footprint and startup time attributable to embedding load.
   - Snapshot accuracy so later index changes can be compared fairly.
2. Harden embedding management.
   - Add deterministic import/export tests.
   - Introduce schema versioning for embedding artifacts.
   - Add checksum validation to detect corruption before load.
3. Introduce a vector-index abstraction.
   - Refactor the current router adapter behind a pluggable query interface.
   - Add feature-flagged selection between brute-force and alternate implementations.
   - Document lifecycle hooks such as build, snapshot, and reload.
4. Implement in-process ANN as a first scaling step.
   - Evaluate a lightweight library such as `hnswlib` or `faiss-cpu`.
   - Prove top-K parity against the brute-force path.
   - Persist index artifacts and validate cold-start reload behavior.
5. Benchmark and tune.
   - Measure `p95` latency, recall@K, and memory usage at higher scales.
   - Tune ANN parameters against explicit latency and recall targets.
   - Surface index statistics via health/info endpoints.
6. Streamline updates and backfills.
   - Rebuild indexes asynchronously on bulk roster updates.
   - Keep incremental updates and index artifacts in sync.
   - Detect drift between source data and index state.
7. Evaluate an external vector store only if in-process limits are exceeded.
   - Prototype with dual-write safety and migration proof.
   - Include auth, retry, and disaster-recovery concerns from the start.
8. Roll out deliberately.
   - Stage internal, canary, and production rollout.
   - Preserve rollback paths and benchmark notes with the implementation.

## Placement Rule

When this roadmap becomes active implementation scope, move the relevant slice into a task plan or epic. Do not move it back into `docs/agentic/rules/` unless it becomes a present-tense operating rule.
