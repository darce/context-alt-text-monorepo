# Performance Targets & Benchmarks

**Last Updated:** 2025-11-01  
**Status:** Targets defined; benchmarks pending implementation

## Service Level Objectives (SLOs)

### API Latency Targets

| Operation | Target (p95) | Target (p99) | Notes |
|-----------|--------------|--------------|-------|
| **POST `/roster/{id}/augment`** | <100ms | <150ms | Excluding FAISS reload (background task) |
| **GET `/roster/{id}`** | <50ms | <80ms | Cache hit should be <10ms |
| **POST `/analyze-scene`** | <200ms | <300ms | Single face, InsightFace inference |
| **POST `/embeddings`** | <150ms | <250ms | Batch of 5 faces |
| **GET `/roster` (list)** | <100ms | <200ms | 100 entries, no embeddings |
| **Vector search (FAISS)** | <50ms | <100ms | Top-10 similarity, 1k entries |
| **Vector search (pgvector)** | <200ms | <350ms | Top-10 similarity, 1k entries, HNSW |

### Background Task Targets

| Task | Target Duration | Notes |
|------|----------------|-------|
| **FAISS index reload** | <5 seconds | 1,000 roster entries with aggregates |
| **PostgreSQL materialized view refresh** | <2 seconds | `REFRESH MATERIALIZED VIEW roster_aggregate_embeddings` |
| **Aggregate recomputation** | <10ms | Single roster entry with 10 augmented embeddings |

### Throughput Targets

| Metric | Target | Measurement Window |
|--------|--------|-------------------|
| **Concurrent recognition requests** | 10 req/s | Single worker, CPU-only |
| **Augment requests** | 50 req/s | With debounced FAISS reload |
| **ETag cache hit rate** | >80% | WordPress roster polling scenario |

## Quality & Accuracy Targets

| Metric | Target | Validation Method |
|--------|--------|-------------------|
| **Progressive learning improvement** | +10% match score | After 5 augmented embeddings |
| **False positive rate** | <5% | At default threshold (0.45) |
| **FAISS recall@10** | >95% | vs brute-force cosine similarity |
| **Idempotency success rate** | 100% | Duplicate observation_id → 409 |

## Benchmark Methodology

### Prerequisites

```bash
# Start recognition service with PostgreSQL
export DATABASE_URL="postgresql://user:pass@localhost/recognition"
export FAISS_ACCELERATION=true
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1

# Install benchmark tooling
pip install locust pytest-benchmark
```

### Running Benchmarks

#### 1. API Latency Benchmarks (pytest-benchmark)

```bash
# Run augment endpoint benchmark
pytest tests/benchmarks/test_augment_latency.py --benchmark-only --benchmark-autosave

# Run search benchmark
pytest tests/benchmarks/test_search_latency.py --benchmark-only --benchmark-autosave
```

**Expected output format:**
```
test_augment_single_embedding       Mean: 45.2ms  StdDev: 8.3ms  p95: 62.1ms  p99: 85.7ms
test_search_faiss_top10            Mean: 12.5ms  StdDev: 2.1ms  p95: 17.3ms  p99: 23.4ms
```

#### 2. Load Testing (Locust)

```bash
# Run load test for augment endpoint
locust -f tests/load/augment_load_test.py --host=http://localhost:8000 --users=50 --spawn-rate=10
```

**Metrics to capture:**
- Requests per second (RPS)
- Response time percentiles (p50, p95, p99)
- Error rate
- FAISS reload frequency

#### 3. FAISS Reload Benchmarks

```python
# Manual benchmark script
import time
from roster.domain.roster_service import RosterService
from recognition_core/services/hybrid_index_manager import HybridIndexManager

# Create 1,000 roster entries with augmented embeddings
# Measure: hybrid_manager.rebuild_from_database()
start = time.time()
hybrid_manager.rebuild_from_database()
duration = time.time() - start
print(f"FAISS reload: {duration:.2f}s for {entry_count} entries")
```

#### 4. Progressive Learning Accuracy

```python
# Run progressive learning validation
pytest tests/integration/test_progressive_learning_accuracy.py -v

# Expected: baseline similarity increases by 10%+ after 5 augmented embeddings
```

## Recording Measurements

### Benchmark Result Format

**REQUIRED:** All benchmark results must include:

1. **Timestamp:** ISO 8601 format (e.g., `2025-11-01T21:45:00Z`)
2. **Environment:**
   - Hardware: CPU/RAM (e.g., "Intel i7-12700K, 32GB RAM")
   - Python version: `python --version`
   - PostgreSQL version: `psql --version`
   - pgvector version: `SELECT * FROM pg_available_extensions WHERE name = 'vector';`
3. **Dataset:**
   - Roster size (number of entries)
   - Total embeddings (reference + augmented)
   - FAISS index size (bytes)
4. **Measurement method:**
   - Tool used (pytest-benchmark, locust, manual timing)
   - Number of iterations/samples
   - Warm-up runs performed
5. **Results:**
   - Mean, StdDev, p95, p99
   - Throughput (RPS) if applicable
   - Error rate

### Example Benchmark Report

```markdown
## Augment Endpoint Latency Benchmark

**Date:** 2025-11-01T21:45:00Z  
**Environment:** Intel i7-12700K, 32GB RAM, Python 3.10.17, PostgreSQL 17 + pgvector 0.8.1  
**Dataset:** 500 roster entries, 1,500 total embeddings, FAISS index 24MB  
**Method:** pytest-benchmark, 100 iterations, 10 warm-up runs  

**Results:**
- Mean: 52.3ms
- StdDev: 9.1ms
- p95: 71.2ms ✅ (target: <100ms)
- p99: 94.8ms ✅ (target: <150ms)

**Conclusion:** Target met. Latency within acceptable range for 500-entry roster.
```

### Storage Location

Save benchmark results to:
- `docs/performance/benchmarks/YYYY-MM-DD-operation-name.md`
- Include raw data as CSV/JSON attachment if available
- Link from this document under "Historical Results" section

## Historical Results

_No benchmarks recorded yet. Add first benchmark report here after running the measurement suite._

### Planned Benchmarks

- [ ] Initial baseline (empty database → 100 entries)
- [ ] Medium scale (1,000 entries with 3,000 embeddings)
- [ ] Large scale (5,000 entries with 15,000 embeddings)
- [ ] Stress test (concurrent augment requests, 50 req/s for 5 minutes)
- [ ] Progressive learning accuracy validation

## Optimization Notes

### Current Bottlenecks (Hypothesized)

1. **Aggregate recomputation:** NumPy weighted average on every augment
2. **FAISS reload frequency:** Thrashing on rapid confirmations (mitigated by 30s debounce)
3. **PostgreSQL materialized view refresh:** Full table scan on large rosters

### Future Optimizations

- **Incremental FAISS updates:** Add single vector to existing index without full rebuild
- **Lazy aggregate recomputation:** Mark dirty, compute on next read
- **Partial materialized view refresh:** CONCURRENTLY option for non-blocking updates
- **Connection pooling tuning:** Increase pool size for high-concurrency scenarios
- **HNSW index tuning:** Adjust m/ef_construction parameters based on recall requirements

## References

- [FastAPI Performance Best Practices](https://fastapi.tiangolo.com/deployment/concepts/)
- [pgvector Performance Tuning](https://github.com/pgvector/pgvector#performance)
- [FAISS Benchmarks](https://github.com/facebookresearch/faiss/wiki/FAQ#what-is-the-performance-of-faiss-on-a-gpu)
- [Locust Documentation](https://docs.locust.io/)
- [pytest-benchmark](https://pytest-benchmark.readthedocs.io/)
