# Post-MVP Search Optimizations

Once the recognition MVP is in a stable state, follow the sequence below to evolve embedding search from the current brute-force implementation into a production-ready, low-latency pipeline. Each milestone should close with benchmarks and documentation updates before progressing.

---

## 1. Establish Baseline Metrics

- Capture the current end-to-end latency for `recognize_faces` using the in-memory cosine scan with representative roster sizes (1k, 5k, 10k identities).
- Record memory footprint and startup time attributable to `EmbeddingRouterAdapter.load_embeddings()`.
- Snapshot accuracy (recall and precision) using an evaluation dataset so later optimizations can be compared apples-to-apples.

## 2. Harden Embedding Management

- Add automated integration tests that validate JSON export/import across roster adapters and guarantee deterministic ordering.
- Introduce schema versioning for the embedding JSON to simplify future migrations.
- Automate checksum generation for each embedding file so the service can detect corruption before loading.

## 3. Introduce Vector Index Abstraction

- Refactor `EmbeddingRouterAdapter` to expose a pluggable index layer (e.g., `VectorIndex` protocol with `add`, `remove`, `query` methods).
- Ship a feature flag that allows rolling between the existing brute-force index and alternative implementations at runtime.
- Document index lifecycle hooks (build, snapshot, reload) and wire them into existing file watcher callbacks.

## 4. Implement In-Process ANN (Phase 1)

- Integrate a lightweight ANN library (`hnswlib` or `faiss-cpu`) as the first `VectorIndex` implementation.
- Normalize embeddings identically to the brute-force path and add unit tests that compare top-K results across both implementations for parity.
- Persist the ANN index artifacts alongside the JSON export and validate reload logic during FastAPI startup.

## 5. Benchmark and Tune ANN Parameters

- Run controlled benchmarks covering roster sizes up to target scale (e.g., 50k identities) and measure p95 latency, recall@K, and memory usage.
- Tune ANN hyperparameters (ef_construction, M for HNSW; nlist, nprobe for IVF) to hit latency targets without unacceptable recall loss.
- Update `/api/v0/service/info` to surface index statistics (entries loaded, build time, last refresh).

## 6. Streamline Updates & Backfills

- Add background jobs that rebuild the ANN index asynchronously when roster bulk updates occur; swap indexes atomically to avoid downtime.
- Ensure incremental updates (create, update, archive) patch both the JSON export and ANN index consistently.
- Build monitoring hooks that alert when index drift is detected (e.g., JSON checksum mismatch, index rebuild failures).

## 7. Evaluate External Vector Store (Optional Phase 2)

- If roster size or query throughput exceeds in-process limits, prototype integration with a managed or self-hosted vector database (Qdrant, Weaviate, Pinecone, pgvector).
- Implement dual-write mode during the trial period to compare recall/latency and guarantee migration safety.
- Harden authentication, network retries, and disaster recovery for the chosen vendor.

## 8. Rollout Plan & Documentation

- Define a staged rollout (internal, canary sites, production) with rollback playbooks for each optimization phase.
- Update developer docs and playbooks (`recognition-service-tasks.md`, onboarding guides) to reflect the new index architecture and operational requirements.
- Archive post-mortem notes, benchmark results, and configuration tweaks in `docs/architecture/records/` for future engineers.

---

Following this roadmap keeps search optimizations incremental and observable, ensuring roster recognition stays fast while the system evolves beyond the MVP.
