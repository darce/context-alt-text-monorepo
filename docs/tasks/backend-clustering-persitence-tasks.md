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

### B0) Database Layer Architecture (NEW)

**Status:** ✅ Completed — pgvector-first persistence with SQLite dev parity.

**Highlights:**

- Canonical schema defined in `db/models.py` with pgvector support and tenant isolation.
- Alembic wired to `db/migrations/versions/` with a fresh baseline (`20251101_1421_7fe9d9f2b08f_baseline_schema.py`).
- Storage abstractions implemented in `roster/domain/interfaces.py`; concrete adapters live in `roster/adapters/postgresql_storage_adapter.py` and `roster/adapters/sqlite_storage_adapter.py`.
- File-based adapters were removed; a development reset guide (README “nuclear option”) documents how to drop/recreate the database when schemas change.
- Startup paths (`shared/startup/adapter_factory.py`) auto-select the correct adapter from `DATABASE_URL`.

**Next Steps:**

- Keep the baseline migration in sync with future model changes via `alembic revision --autogenerate`.
- No production migration story required until we have external consumers (see instructions.md “Greenfield Reset Policy”).

### B0.1) Database Schema (Alembic Migration 0001)

**Status:** ✅ Completed — baseline recreated 2025-11-01.

**Notes:**

- Fresh baseline migration generated after the schema refactor (`db/migrations/versions/20251101_1421_7fe9d9f2b08f_baseline_schema.py`).
- README documents the development-only drop/create workflow and the need to `CREATE EXTENSION vector` before running migrations.
- PostgreSQL 17 + pgvector is the primary target; SQLite remains supported for tests via `SQLAlchemy` JSON/TEXT columns.

**Reference Schema (excerpt):**

**PostgreSQL Schema (Production):**

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tenants table (multi-tenant isolation)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    plan_tier VARCHAR(32) NOT NULL DEFAULT 'free',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tenants_slug ON tenants(slug);

-- Roster entities (person/brand/other)
CREATE TABLE roster_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    label VARCHAR(191) NOT NULL,
    display_name VARCHAR(255),
    type VARCHAR(32) NOT NULL DEFAULT 'person',
    metadata JSONB DEFAULT '{}',
    aggregate_embedding vector(512),  -- pgvector type
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_roster_tenant ON roster_entries(tenant_id);
CREATE INDEX idx_roster_label ON roster_entries(tenant_id, label);
CREATE INDEX idx_roster_updated ON roster_entries(updated_at);

-- Vector similarity index (HNSW for production scale)
CREATE INDEX idx_roster_embedding ON roster_entries
    USING hnsw (aggregate_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Reference embeddings (curated images from initial onboarding)
CREATE TABLE reference_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    roster_entry_id UUID NOT NULL REFERENCES roster_entries(id) ON DELETE CASCADE,
    embedding vector(512) NOT NULL,
    image_path VARCHAR(512),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_emb_roster ON reference_embeddings(roster_entry_id);

-- Augmented embeddings (progressive learning from WordPress confirmations)
CREATE TABLE augmented_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    roster_entry_id UUID NOT NULL REFERENCES roster_entries(id) ON DELETE CASCADE,
    observation_id UUID NOT NULL UNIQUE,  -- from WordPress (idempotency key)
    embedding vector(512) NOT NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'wordpress_confirm',
    attachment_id BIGINT,
    bbox JSONB,
    confidence DECIMAL(5, 4),
    quality_tier VARCHAR(16) NOT NULL,  -- high, medium, low
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_aug_emb_roster ON augmented_embeddings(roster_entry_id);
CREATE INDEX idx_aug_emb_observation ON augmented_embeddings(observation_id);
CREATE INDEX idx_aug_emb_quality ON augmented_embeddings(quality_tier);

-- Row-level security for multi-tenancy
ALTER TABLE roster_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE reference_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE augmented_embeddings ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON roster_entries
    USING (tenant_id = current_setting('app.tenant_id')::UUID);

CREATE POLICY tenant_ref_emb_isolation ON reference_embeddings
    USING (roster_entry_id IN (
        SELECT id FROM roster_entries WHERE tenant_id = current_setting('app.tenant_id')::UUID
    ));

CREATE POLICY tenant_aug_emb_isolation ON augmented_embeddings
    USING (roster_entry_id IN (
        SELECT id FROM roster_entries WHERE tenant_id = current_setting('app.tenant_id')::UUID
    ));
```

**SQLite Schema (Local Development):**

```sql
-- Tenants table
CREATE TABLE tenants (
    id TEXT PRIMARY KEY,  -- UUID as TEXT
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    plan_tier TEXT NOT NULL DEFAULT 'free',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_tenants_slug ON tenants(slug);

-- Roster entries (embeddings stored as JSON blobs)
CREATE TABLE roster_entries (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    display_name TEXT,
    type TEXT NOT NULL DEFAULT 'person',
    metadata TEXT DEFAULT '{}',  -- JSON as TEXT
    aggregate_embedding TEXT,  -- JSON array as TEXT
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_roster_tenant ON roster_entries(tenant_id);
CREATE INDEX idx_roster_label ON roster_entries(tenant_id, label);

-- Reference embeddings
CREATE TABLE reference_embeddings (
    id TEXT PRIMARY KEY,
    roster_entry_id TEXT NOT NULL REFERENCES roster_entries(id) ON DELETE CASCADE,
    embedding TEXT NOT NULL,  -- JSON array as TEXT
    image_path TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_ref_emb_roster ON reference_embeddings(roster_entry_id);

-- Augmented embeddings
CREATE TABLE augmented_embeddings (
    id TEXT PRIMARY KEY,
    roster_entry_id TEXT NOT NULL REFERENCES roster_entries(id) ON DELETE CASCADE,
    observation_id TEXT NOT NULL UNIQUE,
    embedding TEXT NOT NULL,  -- JSON array as TEXT
    source TEXT NOT NULL DEFAULT 'wordpress_confirm',
    attachment_id INTEGER,
    bbox TEXT,  -- JSON as TEXT
    confidence REAL,
    quality_tier TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_aug_emb_roster ON augmented_embeddings(roster_entry_id);
CREATE INDEX idx_aug_emb_observation ON augmented_embeddings(observation_id);
```

**Files:**

- `db/migrations/versions/20251101_1421_7fe9d9f2b08f_baseline_schema.py`
- `db/models.py`

**Verification:**

- `alembic upgrade head` succeeds after enabling `CREATE EXTENSION vector;` in the target database.
- `alembic downgrade base` removes the schema without residue.
- `pytest tests/unit/test_postgresql_storage_adapter.py -q` exercises CRUD + stats against the new layout.

### B0.2) Database Adapter Implementation

**PostgreSQL Adapter:**

**Features:**

- Uses pgvector for native vector similarity search
- Supports batched embedding insertion (100 vectors per transaction)
- Tenant isolation via `SET LOCAL app.tenant_id`
- Aggregate embedding recomputation triggers HNSW index update
- Connection pooling (asyncpg for async, psycopg3 for sync)

**Implementation:**

```python
# roster/adapters/postgres_storage_adapter.py
from typing import List, Optional, Dict, Any
import numpy as np
from sqlalchemy import select, insert, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from db.models import RosterEntry, ReferenceEmbedding, AugmentedEmbedding
from db.session import get_session
from roster.ports.storage import RosterStoragePort

class PostgresStorageAdapter(RosterStoragePort):
    """PostgreSQL adapter with pgvector support."""

    def __init__(self, database_url: str, tenant_id: str):
        self.database_url = database_url
        self.tenant_id = tenant_id
        self.session = get_session(database_url)
        self._set_tenant_context()

    def _set_tenant_context(self):
        """Set tenant context for row-level security."""
        self.session.execute(f"SET LOCAL app.tenant_id = '{self.tenant_id}'")

    def save_roster_entry(self, entry: RosterEntry, model: str) -> bool:
        """Upsert roster entry with aggregate embedding."""
        stmt = pg_insert(RosterEntry).values(
            id=entry.unique_id,
            tenant_id=self.tenant_id,
            label=entry.name,
            display_name=entry.display_name,
            type=entry.metadata.get('type', 'person'),
            metadata=entry.metadata,
            aggregate_embedding=entry.aggregate_embedding,  # pgvector handles list → vector
            updated_at=entry.updated_timestamp
        ).on_conflict_do_update(
            index_elements=['id'],
            set_={
                'label': entry.name,
                'aggregate_embedding': entry.aggregate_embedding,
                'metadata': entry.metadata,
                'updated_at': entry.updated_timestamp
            }
        )
        self.session.execute(stmt)
        self.session.commit()
        return True

    def add_augmented_embedding(
        self,
        roster_id: str,
        observation_id: str,
        embedding: List[float],
        metadata: Dict[str, Any]
    ) -> bool:
        """Add progressive learning embedding (idempotent)."""
        try:
            stmt = insert(AugmentedEmbedding).values(
                roster_entry_id=roster_id,
                observation_id=observation_id,
                embedding=embedding,
                source=metadata.get('source', 'wordpress_confirm'),
                attachment_id=metadata.get('attachment_id'),
                bbox=metadata.get('bbox'),
                confidence=metadata.get('confidence'),
                quality_tier=metadata.get('quality_tier', 'medium')
            )
            self.session.execute(stmt)
            self.session.commit()
            return True
        except IntegrityError:
            # Duplicate observation_id → idempotency
            self.session.rollback()
            return False

    def vector_search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        threshold: float = 0.65
    ) -> List[Dict[str, Any]]:
        """Cosine similarity search using pgvector HNSW index."""
        # pgvector uses <=> for cosine distance (1 - cosine_similarity)
        stmt = select(
            RosterEntry.id,
            RosterEntry.label,
            (1 - RosterEntry.aggregate_embedding.cosine_distance(query_embedding)).label('score')
        ).where(
            RosterEntry.tenant_id == self.tenant_id
        ).order_by(
            RosterEntry.aggregate_embedding.cosine_distance(query_embedding)
        ).limit(top_k)

        results = self.session.execute(stmt).fetchall()
        return [
            {'entity_id': r.id, 'label': r.label, 'score': r.score}
            for r in results if r.score >= threshold
        ]
```

**SQLite Adapter:**

**Features:**

- JSON blob storage for embeddings
- Manual cosine similarity computation (Python/NumPy)
- File-based database (single tenant per file)
- Synchronous I/O (simpler for local dev)

**Implementation:**

```python
# roster/adapters/sqlite_storage_adapter.py
from typing import List, Optional, Dict, Any
import json
import numpy as np
from sqlalchemy import select, insert
from db.models import RosterEntry, AugmentedEmbedding
from db.session import get_session
from roster.ports.storage import RosterStoragePort

class SQLiteStorageAdapter(RosterStoragePort):
    """SQLite adapter with JSON embedding storage."""

    def __init__(self, database_url: str, tenant_id: str = 'default'):
        self.database_url = database_url  # e.g., sqlite:///roster.db
        self.tenant_id = tenant_id
        self.session = get_session(database_url)

    def save_roster_entry(self, entry: RosterEntry, model: str) -> bool:
        """Upsert roster entry (embedding as JSON string)."""
        embedding_json = json.dumps(entry.aggregate_embedding) if entry.aggregate_embedding else None
        metadata_json = json.dumps(entry.metadata)

        # SQLite upsert using INSERT OR REPLACE
        stmt = insert(RosterEntry).values(
            id=entry.unique_id,
            tenant_id=self.tenant_id,
            label=entry.name,
            display_name=entry.display_name,
            metadata=metadata_json,
            aggregate_embedding=embedding_json,
            updated_at=entry.updated_timestamp
        ).prefix_with('OR REPLACE')

        self.session.execute(stmt)
        self.session.commit()
        return True

    def vector_search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        threshold: float = 0.65
    ) -> List[Dict[str, Any]]:
        """Manual cosine similarity (fetch all, compute in Python)."""
        stmt = select(RosterEntry).where(RosterEntry.tenant_id == self.tenant_id)
        entries = self.session.execute(stmt).scalars().all()

        query_vec = np.array(query_embedding)
        results = []

        for entry in entries:
            if not entry.aggregate_embedding:
                continue

            entry_vec = np.array(json.loads(entry.aggregate_embedding))
            score = np.dot(query_vec, entry_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(entry_vec)
            )

            if score >= threshold:
                results.append({
                    'entity_id': entry.id,
                    'label': entry.label,
                    'score': float(score)
                })

        return sorted(results, key=lambda x: x['score'], reverse=True)[:top_k]
```

**Files:**

- `roster/adapters/postgres_storage_adapter.py` (NEW)
- `roster/adapters/sqlite_storage_adapter.py` (NEW)
- `roster/adapters/adapter_factory.py` (NEW, factory to select adapter based on DATABASE_URL)
- `db/session.py` (NEW, session factory with connection pooling)

**Done When:**

- PostgreSQL adapter passes integration tests with pgvector
- SQLite adapter passes unit tests with in-memory database
- Adapter factory selects correct implementation from `DATABASE_URL`
- Both adapters implement full `RosterStoragePort` interface
- Performance benchmarks documented (PostgreSQL <50ms for 1k entries, SQLite <200ms)

### B0.3) Migration from File-Based Storage _(OBSOLETE)_

> The original roadmap assumed an upgrade path from on-disk JSON rosters. The
> greenfield recognition service now persists exclusively to PostgreSQL with
> pgvector, so no file-based migration work is required. This section remains as
> historical context for earlier iterations of the plan.

### B1) Augmented Embeddings Storage (Database)

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

## N. Database Implementation Roadmap

### N1) Alembic Setup & Migrations

**Why:** Version-controlled schema changes; reproducible across environments; supports both PostgreSQL and SQLite.

**Quick Start:**

```bash
cd apps/recognition-service
pip install alembic psycopg[binary] asyncpg
alembic init db/migrations
```

**Configuration (`db/alembic.ini`):**

```ini
[alembic]
script_location = db/migrations
sqlalchemy.url = ${DATABASE_URL}  # Read from environment

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic
```

**Baseline Migration (0001):**

```bash
alembic revision -m "0001_baseline_schema"
# Edit db/migrations/versions/0001_baseline_schema.py
# Add DDL from B0.1 to upgrade()
alembic upgrade head
```

**Greenfield Pattern:**

- Create baseline revision (0001) with all initial tables and extensions
- Subsequent structural changes are new revisions (0002, 0003, ...)
- Use `alembic upgrade head` in CI/CD before app startup

**Files:**

- `db/alembic.ini` (NEW)
- `db/migrations/env.py` (Alembic environment)
- `db/migrations/versions/0001_baseline_schema.py` (baseline)

**Done When:**

- `alembic upgrade head` works on fresh PostgreSQL
- `alembic upgrade head` works on fresh SQLite
- `alembic downgrade base` cleanly removes all tables
- CI pipeline runs migrations before tests

### N2) Expanded HTTP API (Required Endpoints)

**Note:** All endpoints are tenant-scoped via API key; server sets `SET LOCAL app.tenant_id` per request.

#### Roster Endpoints

- **POST /api/v0/roster** — Create entity (person/brand/other)

  - **Body**: `{ "label": "Alice", "type": "person", "meta": {} }`
  - **200**: `{ "id", "revision", "etag" }`

- **GET /api/v0/roster** — List with pagination, optional search by label

  - **Query**: `page`, `per_page`, `q`
  - **200**: `{ "items": [...], "nextPage": null|number }`

- **GET /api/v0/roster/{id}** — Fetch one

- **PUT /api/v0/roster/{id}** — Update label/meta (bumps revision)

- **DELETE /api/v0/roster/{id}** — DSAR delete (hard delete entity; embeddings set NULL or deleted by job)

- **POST /api/v0/roster/{id}/merge** — Merge source entity into target; reassign embeddings; delete source

  - **Body**: `{ "source_id": "uuid" }`

- **POST /api/v0/roster/{id}/split** — Create a new entity from a subset of embeddings
  - **Body**: `{ "embedding_ids": ["..."] }`

#### Confirmations & Embeddings

- **POST /api/v0/roster/{id}/confirm** — Attach observation embedding; optional vector supplied by client

  - **Body**: `{ "vec": [..512..], "image_url": "...", "bbox": {...}, "quality": 0.92 }`

- **POST /api/v0/embeddings** — Batch upsert of embeddings (admin/import)

  - **Body**: `{ "items": [ { "entity_id": "uuid|null", "vec": [...], "meta": {...} } ] }`

- **GET /api/v0/embeddings** — Debug list by entity_id (admin-gated)

- **DELETE /api/v0/embeddings/{id}** — Remove one embedding (admin-gated)

#### Recognition/Search

- **POST /api/v0/recognize** — Single vector or crop URL → embed (if needed) → Top‑K search

  - **Body**: `{ "vec?: [...]", "image_url?: "...", "top_k": 10, "threshold": 0.65, "probes?: 10 }`
  - **200**: `{ "matches": [ { "entity_id", "label", "score" } ] }`

- **POST /api/v0/recognize/batch** — Batch search; returns array of result sets by input

#### Health & Stats

- **GET /healthz** — DB connectivity, version, extensions (vector), corpus size summary

- **GET /readyz** — Includes ANN index readiness, Stripe webhook reachability

- **GET /api/v0/stats** — Counts per tenant: entities, embeddings, usage today/month

- **GET /api/v0/index/status** — ANN parameters, corpus size, last rebuild time

- **POST /api/v0/index/rebuild** — Rebuild ANN (admin; no API change if using pgvector only)

#### Auth & Keys

- **GET /api/v0/api-keys** — List keys for current tenant (masked)

- **POST /api/v0/api-keys** — Issue a new key (returns token once; stores hash)

- **DELETE /api/v0/api-keys/{id}** — Revoke

#### Tenants & Usage

- **GET /api/v0/tenant** — Tenant profile + plan + current subscription status

- **GET /api/v0/tenant/usage?from=YYYY-MM-DD&to=YYYY-MM-DD** — Daily counters window

#### Billing Webhooks

- **POST /webhooks/stripe** — Inbound Stripe webhook (signed). Updates subscriptions and usage

#### DSAR/Export

- **GET /api/v0/roster/{id}/export** — JSON export of entity, metadata, and (optionally) embedding IDs & stats (no raw vectors)

**Done When:**

- OpenAPI spec covers all endpoints
- MSW/integration tests pass for each
- WordPress client uses `/roster` (delta), `/recognize`, `/confirm`, `/stats`

### N3) Hybrid Storage Mode (FAISS + Database)

**Why:** Combine database persistence with FAISS in-memory performance.

**Architecture:**

- **Database:** Source of truth for all embeddings (reference + augmented)
- **FAISS:** In-memory index rebuilt from database on startup or reload
- **Sync:** Background worker refreshes FAISS every 30 seconds if embeddings changed

**Implementation:**

```python
# recognition_core/services/hybrid_index_manager.py
class HybridIndexManager:
    """Manages FAISS index synchronized with database embeddings."""

    def __init__(self, storage_adapter: RosterStoragePort, faiss_adapter: EmbeddingRouterPort):
        self.storage = storage_adapter
        self.faiss = faiss_adapter
        self.last_reload = None
        self.reload_lock = asyncio.Lock()

    async def maybe_reload(self):
        """Check if database changed; reload FAISS if needed."""
        async with self.reload_lock:
            db_etag = await self.storage.get_etag()
            if db_etag != self.last_reload:
                await self.rebuild_index()
                self.last_reload = db_etag

    async def rebuild_index(self):
        """Fetch all embeddings from database; rebuild FAISS index."""
        entries = await self.storage.load_all_entries_with_embeddings()
        embeddings = []
        labels = []

        for entry in entries:
            if entry.aggregate_embedding:
                embeddings.append(entry.aggregate_embedding)
                labels.append(entry.unique_id)

        self.faiss.rebuild_index(embeddings, labels)
        logger.info(f"FAISS index rebuilt: {len(embeddings)} vectors")
```

**Files:**

- `recognition_core/services/hybrid_index_manager.py` (NEW)
- `api/startup.py` (initialize hybrid manager, background worker)

**Done When:**

- FAISS index rebuilds from database on startup (<5s for 1k entries)
- Background worker detects changes and reloads
- Search queries use FAISS for speed, database for accuracy
- Admin endpoint reports last reload timestamp

### N4) Local vs. Production Configuration

**Environment Detection:**

```python
# roster/config/database.py
import os
from typing import Literal

DatabaseType = Literal["postgresql", "sqlite"]

def detect_database_type(database_url: str) -> DatabaseType:
    """Detect database type from connection string."""
    if database_url.startswith("postgresql://") or database_url.startswith("postgres://"):
        return "postgresql"
    elif database_url.startswith("sqlite://"):
        return "sqlite"
    else:
        raise ValueError(f"Unsupported DATABASE_URL: {database_url}")

def get_storage_adapter(database_url: str, tenant_id: str):
    """Factory function to create appropriate storage adapter."""
    db_type = detect_database_type(database_url)

    if db_type == "postgresql":
        from roster.adapters.postgres_storage_adapter import PostgresStorageAdapter
        return PostgresStorageAdapter(database_url, tenant_id)
    else:
        from roster.adapters.sqlite_storage_adapter import SQLiteStorageAdapter
        return SQLiteStorageAdapter(database_url, tenant_id)
```

**Local Development Setup:**

```bash
# .env.local
DATABASE_URL=sqlite:///./roster_dev.db
TENANT_ID=default

# Start service
python -m uvicorn app:app --reload
```

**Production Setup (Hugging Face Spaces):**

```bash
# Hugging Face Spaces secrets
DATABASE_URL=postgresql://user:pass@host:5432/dbname
TENANT_ID=<from-api-key>

# Dockerfile addition
RUN pip install alembic psycopg[binary] asyncpg
CMD alembic upgrade head && uvicorn app:app --host 0.0.0.0 --port 7860
```

**Docker Compose (Local PostgreSQL):**

```yaml
# docker-compose.yml
version: "3.8"
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: roster_dev
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  recognition-service:
    build: .
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/roster_dev
      TENANT_ID: default
    ports:
      - "7860:7860"
    depends_on:
      - postgres

volumes:
  postgres_data:
```

**Files:**

- `roster/config/database.py` (NEW)
- `.env.local.example` (NEW)
- `docker-compose.yml` (NEW)
- `Dockerfile` (update with Alembic step)

**Done When:**

- Service starts with SQLite (no external dependencies) by default
- Setting `DATABASE_URL=postgresql://...` switches to PostgreSQL
- Docker Compose provides local PostgreSQL with pgvector
- Hugging Face Space deployment uses managed PostgreSQL

### N5) Clustering Service (Frontend Preprocessing)

**Why:** WordPress frontend clusters similar faces before sending to backend; reduces API calls and provides better UX.

**Current State:**

- No frontend clustering
- Every detected face triggers separate recognition call

**Target State:**

- WordPress performs local DBSCAN clustering on face embeddings
- Cluster representatives sent to backend for identification
- Suggestions propagated to all faces in cluster

**Backend Support (Not Included in This Task List):**

The clustering happens entirely in WordPress frontend. Backend only needs:

1. Batch recognition endpoint (already covered in N2)
2. Return multiple suggestions per query (already supported)

**Note:** Detailed clustering implementation is in `hybrid-roster-tasks.md` (WordPress tasks). Backend recognition service does not perform clustering—only provides similarity search.

---

## O. Summary & Implementation Checklist

### Core Changes (Must-Have for MVP)

- [x] **B0.1:** ~~Alembic migrations for PostgreSQL + SQLite schemas~~ **DONE** - PostgreSQL-only, schema complete
- [x] **B0.2:** ~~PostgreSQL adapter with pgvector support~~ **DONE** - DatabaseStorageBase + PostgreSQLStorageAdapter implemented
- [x] **~~B0.2:** SQLite adapter with JSON blob storage~~ **OBSOLETE** - PostgreSQL-only architecture
- [x] **~~B0.3:** Migration script from JSON files to database~~ **OBSOLETE** - Greenfield project, no legacy data
- [ ] **B1:** Augmented embeddings storage in database tables - **IN PROGRESS** (tables exist, workflow incomplete)
- [x] **B2:** ~~FAISS index hot-reload mechanism~~ **DONE** - Background reload with 30s debouncing implemented
- [x] **C1:** ~~POST `/api/v0/roster/{id}/augment` endpoint~~ **DONE** - Endpoint implemented with idempotency
- [ ] **C2:** ETag-based roster delta sync
- [ ] **C3:** Extended health/stats endpoints
- [x] **D1:** ~~Weighted aggregate embedding computation~~ **DONE** - Quality-based weighting implemented (high=1.0, medium=0.8, low=0.5)
- [x] **~~N3:** Hybrid index manager (FAISS + database)~~ **DONE** - HybridIndexManager implemented

### Testing (Required for All Changes)

- [x] **E1:** ~~Unit tests for database adapters~~ **DONE** - PostgreSQL adapter tests passing (138/140 tests pass)
- [ ] **E1:** Unit tests for weighted averaging
- [x] **E2:** ~~Integration tests with PostgreSQL~~ **DONE** - Integration tests passing
- [x] **~~E2:** Integration tests with SQLite~~ **OBSOLETE** - No SQLite support
- [ ] **E2:** Progressive learning scenarios
- [ ] **E2:** ETag caching scenarios

### Operations (Production Readiness)

- [ ] **F1:** Prometheus metrics for database operations
- [ ] **F1:** Logging for embedding additions
- [ ] **F2:** Performance benchmarks documented
- [ ] **N1:** Alembic setup in CI/CD pipeline
- [ ] **N4:** Docker Compose for local PostgreSQL
- [ ] **N4:** Hugging Face Spaces deployment with migrations

### Documentation (Knowledge Transfer)

- [ ] **G1:** OpenAPI schema updated with new endpoints
- [ ] **G2:** Architecture diagrams showing database layer
- [ ] **G3:** WordPress integration guide updated
- [ ] **N2:** API endpoint catalog complete
- [ ] **README:** Database setup instructions

### Estimated Timeline

- **Week 1:** B0 (Database layer architecture, migrations, adapters)
- **Week 2:** B1-B2 (Augmented embeddings, FAISS hot-reload)
- **Week 3:** C1-C3 (REST API endpoints, ETag sync)
- **Week 4:** E1-E2, F1-F2 (Testing, observability)
- **Week 5:** N1-N4, G1-G3 (Ops setup, documentation)

### Success Criteria Checklist

- [x] ~~Service runs with SQLite by default (no external deps)~~ **OBSOLETE** - PostgreSQL-only
- [x] Service runs with PostgreSQL when `DATABASE_URL` set **DONE**
- [ ] Progressive learning: 5 confirmations improve match score by 10%
- [ ] FAISS index reloads within 30 seconds of embedding addition
- [ ] ETag caching: 80% cache hit rate in typical WordPress usage
- [ ] Performance: <100ms for augment API, <200ms for search
- [x] ~~Zero-downtime migration from JSON file storage~~ **OBSOLETE** - Greenfield project
- [x] Integration tests pass against ~~both SQLite and~~ PostgreSQL **DONE**
- [ ] OpenAPI docs reflect all new endpoints
- [ ] WordPress client successfully syncs roster via delta endpoints

---

## End Notes

This task list focuses exclusively on backend recognition service changes required to support the hybrid roster architecture documented in `roadmap-v3.hybrid.md` and `hybrid-roster-tasks.md`.

Key additions in this revision:

- **Database persistence layer** with PostgreSQL (production) and SQLite (local dev)
- **Alembic migrations** for versioned schema management
- **pgvector integration** for native vector similarity search
- **Multi-tenant isolation** via row-level security policies
- **Hybrid storage mode** combining database persistence with FAISS performance
- **Migration path** from existing JSON file storage to database

WordPress plugin changes (clustering, frontend UI, sync queue) are documented separately in the main hybrid task list.
