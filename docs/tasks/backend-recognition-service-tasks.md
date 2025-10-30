# Backend Recognition Service Task List — Progressive Learning & Roster Sync

**Scope:** Backend recognition service changes (`apps/recognition-service`) to support progressive learning, augmented embeddings, and WordPress roster synchronization.

**Principle:** Recognition service is the canonical source of truth for roster data and FAISS matching. WordPress confirms identities and sends embeddings; backend aggregates them, updates the FAISS index, and serves suggestions.

**Source Documents:** `hybrid-roster-tasks.md`, `roadmap-v3.hybrid.md`

**Last Updated:** 2025-10-30

---

## A. Success Criteria (Backend Service)

- **Progressive Learning:** Each confirmed identity from WordPress appends a new embedding to the roster entry; FAISS index refreshes within 30 seconds.
- **Unlimited Embeddings:** No artificial cap on embeddings per person; storage uses JSON arrays in roster metadata.
- **FAISS Index Performance:** Suggestion queries return within 200ms for rosters up to 1,000 identities.
- **Idempotent Writes:** Duplicate confirmation requests (same observationId) do not create duplicate embeddings.
- **ETag/Delta Sync:** WordPress polls `/api/v0/roster` with `If-None-Match`; service returns 304 when unchanged, 200 with delta when updated.
- **Health & Observability:** `/api/v0/health` and `/api/v0/service/info` return roster stats (entry count, embedding count, last update timestamp).

---

## B. Database & Storage Tasks

### B1) Augmented Embeddings Storage (JSON metadata)

**Why:** Store multiple confirmed embeddings per identity without schema migrations; support progressive learning.

**Current State:**

- `RosterEntry` has `reference_images: List[RosterImage]` with embeddings
- `RosterImage.embedding` is a single vector per image
- Aggregate embedding computed as simple mean of all reference embeddings

**Changes Needed:**

1. **Add augmented embeddings collection to RosterEntry metadata:**

   - `metadata['augmented_embeddings']` → list of dicts with structure:

     ```json
     {
       "embedding": [512-dim float vector],
       "source": "wordpress_confirm",
       "observation_id": "uuid-from-wordpress",
       "attachment_id": 123,
       "bbox": {"x": 100, "y": 200, "w": 150, "h": 200},
       "confidence": 0.87,
       "created_at": "2025-10-30T12:34:56Z",
       "quality_tier": "high|medium|low"
     }
     ```

   - Quality tier determined by confidence: ≥0.85 = high, ≥0.65 = medium, <0.65 = low

2. **Update aggregate embedding computation:**

   - Include augmented embeddings alongside reference embeddings
   - Weight by quality tier: high=1.0, medium=0.8, low=0.5
   - Recompute on every confirmation and persist immediately

3. **Deduplication logic:**
   - Check `observation_id` before appending; skip if already exists
   - Log duplicate attempts for monitoring

**Files:**

- `roster/domain/entities.py` (RosterEntry class)
- `roster/domain/roster_service.py` (aggregate computation, add_augmented_embedding method)

**Done When:**

- `RosterEntry.add_augmented_embedding(embedding, source, observation_id, metadata)` method exists
- Aggregate embedding weights augmented embeddings correctly
- Duplicate observation_id rejected (idempotent)
- Unit tests verify weighted averaging and deduplication
- Metadata persists to JSON via existing storage adapter

### B2) FAISS Index Hot-Reload

**Why:** WordPress confirmations must propagate to FAISS index without service restart.

**Current State:**

- FAISS index built at startup from roster embeddings
- No hot-reload mechanism; changes require restart

**Changes Needed:**

1. **Add index refresh endpoint:**

   - `POST /api/v0/service/reload-embeddings` → triggers FAISS rebuild
   - Returns `{"status": "reloaded", "entry_count": N, "embedding_count": M, "duration_ms": T}`

2. **Automatic reload on roster write:**

   - After successful `POST /api/v0/roster` or `POST /api/v0/roster/{id}/embeddings`
   - Enqueue background task (FastAPI BackgroundTasks) to rebuild index
   - Max frequency: once per 30 seconds (debounce multiple rapid writes)

3. **Thread-safe index swap:**
   - Build new FAISS index in memory
   - Swap reference atomically (use threading.Lock or asyncio.Lock)
   - Continue serving old index during rebuild

**Files:**

- `recognition_core/adapters/embedding_router_adapter.py` (FAISS index management)
- `recognition_core/services/face_recognition_service.py` (reload trigger)
- `api/routes/roster.py` (background task after writes)
- `api/routes/main.py` (new reload endpoint)

**Done When:**

- `/api/v0/service/reload-embeddings` triggers rebuild successfully
- Roster write endpoints enqueue background reload
- Concurrent requests continue using old index during rebuild
- Rebuild completes within 5 seconds for 1,000 entries
- Integration tests verify index refresh without restart

---

## C. REST API Tasks

### C1) Add Embedding to Existing Roster Entry

**Purpose:** WordPress calls this after user confirms an identity to append the observation's embedding.

**Current State:**

- `POST /api/v0/roster/{unique_id}/embeddings` exists but stores as reference_images
- No distinction between reference images and progressive learning embeddings

**Changes Needed:**

**Endpoint:** `POST /api/v0/roster/{unique_id}/augment`

**Request Schema:**

```json
{
  "embedding": [512-dim float vector],
  "observation_id": "uuid-from-wordpress",
  "attachment_id": 123,
  "bbox": {"x": 100, "y": 200, "w": 150, "h": 200},
  "confidence": 0.87,
  "idempotency_key": "optional-uuid"
}
```

**Response:**

```json
{
  "success": true,
  "roster_entry": {
    "unique_id": "abc-123",
    "name": "John Doe",
    "embedding_count": 15,
    "augmented_count": 12,
    "reference_count": 3,
    "aggregate_embedding": [512-dim vector],
    "updated_at": "2025-10-30T12:35:00Z"
  },
  "index_reloaded": true
}
```

**Implementation:**

1. Validate unique_id exists
2. Call `roster_service.add_augmented_embedding(unique_id, model, embedding, observation_id, metadata)`
3. Enqueue FAISS index reload (background task)
4. Return updated roster entry with counts

**Error Cases:**

- 404: Roster entry not found
- 400: Invalid embedding (dimension mismatch, not normalized)
- 409: Duplicate observation_id (already processed)
- 422: Validation errors

**Files:**

- `api/routes/roster.py` (new endpoint)
- `roster/domain/roster_service.py` (new method)
- `shared/dtos/roster.py` (request/response DTOs)

**Done When:**

- Endpoint registered and routable
- Request validation includes embedding dimension check
- Idempotency key handled (cache response for 10 minutes)
- Background index reload triggered
- OpenAPI schema updated with examples
- Integration tests verify happy path + error cases

### C2) ETag-Based Roster Delta Sync

**Purpose:** WordPress polls roster changes without re-fetching entire dataset every time.

**Current State:**

- `GET /api/v0/roster` returns full roster list
- No ETag or conditional request support

**Changes Needed:**

1. **Add ETag generation:**

   - Compute ETag from roster content hash (SHA256 of sorted unique_ids + updated_at timestamps)
   - Store in memory cache (5-minute TTL)
   - Invalidate on any roster write

2. **Support If-None-Match header:**

   - `GET /api/v0/roster?model=insightface_w600k` with `If-None-Match: "etag-value"`
   - If ETag matches current → return 304 Not Modified
   - If ETag differs → return 200 with full roster + new ETag in response header

3. **Add incremental sync endpoint (optional):**
   - `GET /api/v0/roster/delta?since=ISO8601_timestamp&model=insightface_w600k`
   - Returns only entries with `updated_at > since`
   - Includes deleted entries as `{"unique_id": "...", "deleted": true}`

**Files:**

- `api/routes/roster.py` (modify GET /api/v0/roster)
- `roster/domain/roster_service.py` (ETag computation method)
- `roster/adapters/file_storage_adapter.py` (track deletions for delta)

**Done When:**

- `GET /api/v0/roster` returns `ETag` header
- 304 response when `If-None-Match` matches
- ETag invalidated on roster writes
- Delta endpoint returns only changed entries
- WordPress client tests verify 304 caching behavior

### C3) Health & Stats Enhancements

**Purpose:** WordPress dashboard and admin diagnostics need roster statistics.

**Current State:**

- `GET /api/v0/health` returns basic liveness
- `GET /api/v0/service/info` returns model metadata

**Changes Needed:**

1. **Extend /api/v0/service/info response:**

   ```json
   {
     "status": "healthy",
     "version": "1.0.0",
     "model": "insightface_w600k",
     "device": "cuda",
     "roster_stats": {
       "total_entries": 150,
       "total_embeddings": 487,
       "augmented_embeddings": 337,
       "reference_embeddings": 150,
       "last_updated": "2025-10-30T12:35:00Z",
       "etag": "sha256:abc123..."
     },
     "faiss_index_stats": {
       "total_vectors": 487,
       "dimension": 512,
       "index_type": "Flat",
       "last_reload": "2025-10-30T12:35:00Z"
     }
   }
   ```

2. **Add roster stats method to RosterService:**
   - `get_roster_stats(model: str) -> Dict[str, Any]`
   - Aggregate counts from all entries
   - Cache result for 60 seconds

**Files:**

- `api/routes/main.py` (extend /api/v0/service/info)
- `roster/domain/roster_service.py` (stats method)
- `recognition_core/adapters/embedding_router_adapter.py` (FAISS stats)

**Done When:**

- `/api/v0/service/info` includes roster_stats and faiss_index_stats
- Stats cached for 60 seconds
- WordPress client can fetch and display counts
- Tests verify stat aggregation accuracy

---

## D. Domain Services & Background Work

### D1) Weighted Aggregate Embedding Computation

**Why:** High-quality embeddings (from clear, frontal images) should contribute more to the aggregate than low-quality embeddings (partial occlusion, side profile).

**Current State:**

- Simple mean of all embeddings (equal weight)

**Changes Needed:**

1. **Add quality_tier to augmented embeddings:**

   - Determined by confidence score when embedding is added
   - ≥0.85 = high (weight=1.0)
   - ≥0.65 = medium (weight=0.8)
   - <0.65 = low (weight=0.5)

2. **Update RosterEntry.\_compute_aggregate_embedding():**

   - Collect reference embeddings (weight=1.0)
   - Collect augmented embeddings with weights
   - Compute weighted average: `sum(embedding * weight) / sum(weights)`
   - Normalize result to unit vector

3. **Recompute on every augmented embedding addition:**
   - Trigger in `RosterService.add_augmented_embedding()`
   - Persist updated aggregate_embedding immediately

**Files:**

- `roster/domain/entities.py` (RosterEntry class)
- `roster/domain/roster_service.py` (add_augmented_embedding method)

**Done When:**

- Weighted averaging implemented and tested
- Unit tests verify high-quality embeddings dominate low-quality ones
- Aggregate embedding normalized to unit vector
- Recomputation triggered on every addition

### D2) Embedding Retention & Pruning (Optional, Post-MVP)

**Why:** Prevent unbounded storage growth for very large rosters with many confirmations per person.

**Implementation (Deferred):**

- Add `max_augmented_embeddings_per_entry` setting (e.g., 100)
- When limit exceeded, prune lowest-quality embeddings first
- Preserve at least 10 high-quality embeddings per person
- Log pruning events for monitoring

**Files:**

- `roster/domain/roster_service.py` (pruning logic)
- `roster/config/` (settings)

**Done When:**

- Configurable limit enforced
- Pruning logic tested with >100 embeddings per entry
- Admin can adjust limit via settings

---

## E. Testing Matrix

### E1) Unit Tests

**Coverage Targets:**

- `RosterEntry.add_augmented_embedding()` (deduplication, quality tier, weighted averaging)
- `RosterService.add_augmented_embedding()` (validation, persistence, idempotency)
- `RosterService.get_roster_stats()` (count aggregation)
- ETag computation (stable, changes on write)
- FAISS index reload (thread safety, debouncing)

**Mocking:**

- File storage adapter (stub roster JSON read/write)
- FAISS adapter (stub index rebuild)

**Done When:**

- > 90% code coverage for new methods
- All tests green in CI
- Tests run with pytest in <30 seconds

### E2) Integration Tests

**Scenarios:**

1. **Progressive Learning:**

   - Create roster entry with 1 reference embedding
   - POST 5 augmented embeddings via `/api/v0/roster/{id}/augment`
   - Verify aggregate embedding updates after each addition
   - Verify FAISS index returns improved matches

2. **Idempotency:**

   - POST same observation_id twice
   - Verify second request returns 409 (already processed)
   - Verify embedding count unchanged

3. **ETag Caching:**

   - GET `/api/v0/roster` → capture ETag
   - GET with `If-None-Match: {etag}` → 304 response
   - POST new roster entry → invalidate ETag
   - GET with old ETag → 200 with new data

4. **FAISS Hot-Reload:**
   - Initial roster with 10 entries
   - POST augmented embedding to entry #5
   - GET `/api/v0/embeddings` (suggestion query) → verify new embedding used
   - No service restart required

**Done When:**

- All scenarios pass against local service
- Tests documented in `tests/integration/`
- Manual smoke test script added to `scripts/`

---

## F. Operations & Observability

### F1) Metrics & Logging

**Metrics to Add:**

- `roster_entry_count` (gauge, labels: model)
- `roster_embedding_count` (gauge, labels: model, type={reference|augmented})
- `roster_augment_requests_total` (counter, labels: model, status={success|duplicate|error})
- `faiss_index_reload_duration_seconds` (histogram)
- `faiss_index_reload_total` (counter, labels: trigger={manual|auto})

**Logging Enhancements:**

- Log every augmented embedding addition with observation_id, roster_id, quality_tier
- Log FAISS reload events with entry count, duration, trigger
- Log ETag cache hits/misses

**Files:**

- `api/routes/roster.py` (request logging)
- `recognition_core/adapters/embedding_router_adapter.py` (reload metrics)

**Done When:**

- Prometheus metrics endpoint available (or structured logs for ingestion)
- Grafana dashboard template provided (optional)
- Metrics tested with load simulation

### F2) Error Budgets & Alerts

**Targets:**

- 95th percentile latency for `/api/v0/roster/{id}/augment`: <100ms
- 99th percentile latency for `/api/v0/embeddings` (suggestions): <200ms
- Error rate for roster writes: <1%
- FAISS reload duration: <5 seconds for 1,000 entries

**Alerts:**

- FAISS reload exceeding 10 seconds (indicates performance degradation)
- Roster write error rate >5% (indicates storage issues)
- ETag cache miss rate >20% (indicates cache invalidation bug)

**Done When:**

- Latency targets validated with load tests
- Alert rules documented in `docs/ops/`

---

## G. Documentation Updates

### G1) OpenAPI Schema Updates

**Changes:**

- Add `/api/v0/roster/{unique_id}/augment` endpoint
- Add request/response schemas for augmented embeddings
- Add ETag headers to `/api/v0/roster` documentation
- Update `/api/v0/service/info` response schema

**Files:**

- `api/routes/roster.py` (docstrings)
- `shared/dtos/roster.py` (Pydantic models)

**Done When:**

- FastAPI auto-generated OpenAPI docs reflect all changes
- Example requests/responses added to `api/examples/`

### G2) Architecture Diagrams

**Updates Needed:**

1. **`docs/architecture/backend-uml/database-entities.mmd`:**

   - Add `augmented_embeddings` collection to RosterEntry
   - Show relationship between reference and augmented embeddings

2. **`docs/architecture/backend-uml/roster_service.mermaid`:**

   - Add `add_augmented_embedding()` flow
   - Show FAISS index refresh trigger

3. **`docs/architecture/backend-uml/recognition_service.mermaid`:**
   - Document progressive learning loop (WordPress confirm → backend augment → index reload → improved suggestions)

**Done When:**

- Mermaid diagrams render correctly in VS Code
- Diagrams reviewed by team
- Committed to main branch

### G3) WordPress Integration Guide

**Purpose:** Document the backend contract for WordPress developers.

**Content:**

- Overview of progressive learning workflow
- Endpoint catalog with curl examples
- ETag caching strategy
- Idempotency key usage
- Error handling recommendations
- Rate limiting guidance (if implemented)

**Files:**

- `docs/integration/wordpress-backend-contract.md`

**Done When:**

- Guide reviewed by WordPress team
- All endpoints documented with examples
- Error responses cataloged

---

## H. Priority Order for Implementation

### Phase 1: Core Progressive Learning (Week 1)

1. B1 - Augmented embeddings storage
2. D1 - Weighted aggregate embedding computation
3. C1 - Add embedding to roster entry endpoint
4. E1 - Unit tests for new methods

### Phase 2: FAISS Integration (Week 2)

1. B2 - FAISS index hot-reload
2. C1 - Background index reload on writes
3. E2 - Integration tests for progressive learning

### Phase 3: Sync & Caching (Week 3)

1. C2 - ETag-based roster delta sync
2. C3 - Health & stats enhancements
3. E2 - Integration tests for ETag caching

### Phase 4: Observability (Week 4)

1. F1 - Metrics & logging
2. F2 - Error budgets & alerts
3. G1-G3 - Documentation updates

---

## I. Definition of Done (Backend Service)

### I1) Code Quality

- All pytest tests green (unit + integration)
- Code coverage ≥90% for new modules
- Type hints complete (mypy --strict passes)
- No Pylint errors

### I2) API Contract

- OpenAPI schema updated and validated
- Example requests/responses in `api/examples/`
- WordPress client can consume endpoints without errors
- Contract tests verify DTO compatibility

### I3) Performance

- Augmented embedding addition: <100ms (p95)
- FAISS index reload: <5s for 1,000 entries
- ETag cache hit rate: ≥80% in typical usage
- Suggestion queries: <200ms (p99)

### I4) Documentation

- OpenAPI docs deployed to Hugging Face Space
- WordPress integration guide complete
- Architecture diagrams updated
- README.md reflects new endpoints

---

## J. WordPress Integration Touchpoints

**Backend → WordPress Contract:**

- **POST `/api/v0/roster/{id}/augment`** — WordPress calls after user confirms identity
- **GET `/api/v0/roster`** with `If-None-Match` — WordPress polls for roster changes
- **GET `/api/v0/service/info`** — WordPress dashboard fetches stats
- **POST `/api/v0/service/reload-embeddings`** — WordPress admin can trigger manual refresh

**WordPress → Backend Payload Examples:**

See `docs/architecture/contracts/augmented-embedding-request.json` (to be created).

**Error Handling:**

- 404: Roster entry not found → WordPress logs error, shows admin notice
- 409: Duplicate observation → WordPress no-op (silent success)
- 503: Service unavailable → WordPress queues confirmation for retry
- 422: Invalid embedding → WordPress logs validation error, alerts admin

---

## K. Open Questions / Future Enhancements

### K1) Multi-Model Support

**Question:** Should the service support multiple embedding models simultaneously (e.g., InsightFace + CLIP)?

**Impact:** Would require model-specific FAISS indexes and routing logic.

**Recommendation:** Defer until post-MVP; current single-model approach sufficient.

### K2) Embedding Quality Scoring

**Question:** Should the service automatically score embedding quality (beyond confidence threshold)?

**Considerations:**

- Detect blur, occlusion, extreme angles
- Assign quality score 0.0-1.0
- Use score in weighted averaging

**Recommendation:** Defer; current confidence-based tiers adequate for MVP.

### K3) Distributed FAISS Index

**Question:** For very large rosters (>10,000 entries), should FAISS index be partitioned?

**Considerations:**

- Current Flat index scales to ~10k vectors on single machine
- IVF index would enable larger rosters but adds complexity
- Multi-shard deployment for horizontal scaling

**Recommendation:** Monitor performance; revisit if query latency exceeds 200ms at scale.

---

## L. Concrete File Touch List

### L1) New Files

- `api/routes/augment.py` (optional, if separating augment endpoints)
- `tests/integration/test_progressive_learning.py`
- `tests/integration/test_etag_caching.py`
- `docs/integration/wordpress-backend-contract.md`
- `docs/architecture/contracts/augmented-embedding-request.json`

### L2) Modified Files

**Domain:**

- `roster/domain/entities.py` (RosterEntry.add_augmented_embedding)
- `roster/domain/roster_service.py` (add_augmented_embedding, get_roster_stats, weighted averaging)

**API:**

- `api/routes/roster.py` (new augment endpoint, ETag support)
- `api/routes/main.py` (extend /service/info, add reload endpoint)
- `api/dependencies.py` (inject roster service with caching)

**Adapters:**

- `recognition_core/adapters/embedding_router_adapter.py` (hot-reload, thread safety)
- `roster/adapters/file_storage_adapter.py` (ETag tracking)

**DTOs:**

- `shared/dtos/roster.py` (augment request/response models)

**Tests:**

- `tests/unit/test_roster_service.py` (augmented embedding tests)
- `tests/unit/test_embedding_router.py` (hot-reload tests)

**Documentation:**

- `README.md` (update endpoint list)
- `docs/architecture/backend-uml/*.mmd` (diagram updates)

---

## M. Success Metrics (Post-Implementation)

### M1) Progressive Learning Effectiveness

- **Metric:** Average similarity score improvement after N confirmations
- **Target:** +5% similarity score after 3 confirmations, +10% after 5 confirmations
- **Measurement:** A/B test with reference-only vs. augmented embeddings

### M2) FAISS Index Freshness

- **Metric:** Time from WordPress confirmation to FAISS availability
- **Target:** <30 seconds (p95)
- **Measurement:** Log timestamp delta between augment API call and index reload completion

### M3) WordPress Sync Efficiency

- **Metric:** ETag cache hit rate on roster polling
- **Target:** ≥80% cache hits (304 responses)
- **Measurement:** Aggregate API logs over 7-day period

### M4) Operational Stability

- **Metric:** FAISS reload error rate
- **Target:** <0.1% (1 failure per 1,000 reloads)
- **Measurement:** Prometheus counter over 30-day period

---

## End Notes

This task list focuses exclusively on backend recognition service changes required to support the hybrid roster architecture documented in `roadmap-v3.hybrid.md` and `hybrid-roster-tasks.md`. WordPress plugin changes are documented separately in the main hybrid task list.
