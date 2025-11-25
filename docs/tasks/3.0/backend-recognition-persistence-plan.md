# Backend Persistence Decision — Recognition Service (Hybrid, Multi‑Tenant)

_Last updated: 2025-10-31_

## ✅ Short Answer

**Yes.** The backend **does need a real database** for roster metadata, progressive learning embeddings, multi‑tenancy, auth, usage/billing, and audit.

For **embeddings**, use **PostgreSQL + `pgvector`** as the **canonical store**, with a **FAISS/HNSW acceleration index** as a derived in-memory artifact synchronized from the database.

- **Relational (canonical):** PostgreSQL with pgvector (JSONB for metadata, RLS for multi-tenancy, extensions for UUID/crypto)
- **Vector search (hybrid):**
  - **Primary:** pgvector IVFFLAT/HNSW indexes for production persistence and search
  - **Derived:** FAISS in-memory index synchronized from database (hot-reload on updates)
  - **Local dev:** SQLite with JSON blob storage + manual cosine similarity (no pgvector required)
- **Object storage (optional):** S3-compatible for FAISS index snapshots and backups (originals stay in WordPress)
- **Payments:** **Never** store card data; use Stripe tokens and webhooks; persist only **customer IDs, subscription status, and usage counters**

**Key Principle:** Database is source of truth; FAISS is a performance optimization that can be rebuilt at any time.

---

## Implementation Plan (aligned with backend-clustering-persistence-tasks.md)

| Phase | Scope | Key Tasks | Status |
| ----- | ----- | --------- | ------ |
| Phase 0 — Progressive Learning | API surface for progressive embeddings, FAISS hot reload, duplicate protection | `/roster/{id}/augment` endpoint, weighted aggregates, background reload debounce, idempotency cache | ✅ Complete (2025-10-30) |
| Phase 1 — Database Baseline (B0, B0.1) | Introduce relational persistence, Alembic migrations, dual SQLite/PostgreSQL targets | Scaffold `db/` package, initialise Alembic, author `0001_baseline_schema`, document migration path | 🔄 In progress — Alembic baseline + SQLAlchemy models merged (0001), migration guide drafted |
| Phase 2 — Storage Ports & Adapters (B0.2) | Implement PostgresStorageAdapter + SQLiteStorageAdapter behind `RosterStoragePort`; retain legacy adapter during transition | Define SQLAlchemy models, tenant scoping, vector search bridging (pgvector + NumPy fallback), unit/integration tests | 🔄 In progress — SQLite adapter + unit tests merged; Postgres adapter, adapter factory, vector search pending |
| Phase 3 — Synchronisation & Ops | Wire adapters into service bootstrap, add configuration plumbing, observability, roster delta sync | Update dependency wiring, feature-flag rollout, extend `/service/info`, document deployment steps | ⏳ Not started |

### Immediate next work items

1. Finalise storage port contract + adapter factory so `DATABASE_URL` selects SQLite/Postgres while legacy JSON remains fallback.
2. Implement `PostgresStorageAdapter` with pgvector queries + idempotent augmented embedding writes; add guarded tests and verify Alembic baseline on SQLite (CI-friendly).
3. Update `db-install-and-production-guide.md` and roadmap notes once adapters are wired, including JSON-to-DB migration guidance and operational runbooks.

---

## Why PostgreSQL (not MySQL) for this project

- **`pgvector`** — first‑class vector type and ANN indexes (IVFFLAT, HNSW in recent versions)
- **JSONB** — flexible metadata per entity without schema churn
- **RLS** — clean multi‑tenant isolation (`SET LOCAL app.tenant_id`)
- **Extensions** — `uuid-ossp`, `citext`, `pgcrypto`, `pg_partman` (optional)

> **Architecture Strategy:** PostgreSQL is the **source of truth** for roster + embeddings. FAISS (always used) is a **derived in-memory index** rebuilt/refreshed from Postgres on startup and on-demand. This hybrid approach combines database durability with FAISS performance.

---

## Database Adapter Pattern

The service uses a **ports-and-adapters** architecture with pluggable storage backends:

- **PostgresStorageAdapter** — Production (pgvector for vector search, RLS for multi-tenancy)
- **SQLiteStorageAdapter** — Local development (JSON blob storage, manual cosine similarity)
- **FileStorageAdapter** — Legacy (deprecated, kept for migration)

**Adapter Selection:** Auto-detect from `DATABASE_URL`:

- `postgresql://...` → PostgresStorageAdapter
- `sqlite://...` → SQLiteStorageAdapter
- Not set → FileStorageAdapter (backward compatibility)

---

## Phase 1 (MVP) — PostgreSQL + `pgvector` + FAISS Hybrid

### Enable extensions

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector
```

### Multi‑tenancy core

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector
```

### Multi‑tenancy core

```sql
CREATE TABLE tenants (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name      text NOT NULL,
  plan      text NOT NULL DEFAULT 'free' CHECK (plan IN ('free','pro','business','enterprise')),
  stripe_customer_id text UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email     citext NOT NULL UNIQUE,
  password_hash text,  -- optional if using external SSO
  role      text NOT NULL DEFAULT 'owner' CHECK (role IN ('owner','admin','member')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name       text NOT NULL,
  hashed_key text NOT NULL,  -- store hash only
  scopes     text[] NOT NULL DEFAULT ARRAY['recognition:read','recognition:write'],
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz
);
CREATE UNIQUE INDEX api_keys_tenant_name_idx ON api_keys(tenant_id, name);
```

### Billing & usage (tokenized via Stripe)

```sql
CREATE TABLE subscriptions (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  stripe_subscription_id text UNIQUE,
  price_id   text,
  status     text NOT NULL,  -- e.g., active, past_due, canceled
  current_period_end timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE usage_counters (
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  day        date NOT NULL,
  inference_count bigint NOT NULL DEFAULT 0,
  embedding_count bigint NOT NULL DEFAULT 0,
  storage_bytes   bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, day)
);
```

### Roster & embeddings (canonical, in Postgres + Progressive Learning)

```sql
CREATE TABLE roster_entities (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  label      text NOT NULL,
  type       text NOT NULL DEFAULT 'person' CHECK (type IN ('person','brand','other')),
  display_name text,
  canonical_embedding_id bigint,  -- points to embeddings.id for aggregate
  meta       jsonb NOT NULL DEFAULT '{}',
  revision   integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX roster_entities_tenant_label_idx ON roster_entities(tenant_id, label);
CREATE INDEX roster_entities_updated_idx ON roster_entities(updated_at);

-- Reference embeddings (curated images from initial onboarding)
CREATE TABLE reference_embeddings (
  id         bigserial PRIMARY KEY,
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  roster_entry_id uuid NOT NULL REFERENCES roster_entities(id) ON DELETE CASCADE,
  embedding  vector(512) NOT NULL,                 -- adjust to your model dimension
  image_path text,                                 -- optional reference image path
  metadata   jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ref_emb_tenant_idx ON reference_embeddings(tenant_id);
CREATE INDEX ref_emb_roster_idx ON reference_embeddings(roster_entry_id);

-- Augmented embeddings (progressive learning from WordPress confirmations)
CREATE TABLE augmented_embeddings (
  id         bigserial PRIMARY KEY,
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  roster_entry_id uuid NOT NULL REFERENCES roster_entities(id) ON DELETE CASCADE,
  observation_id uuid NOT NULL UNIQUE,  -- from WordPress (idempotency key)
  embedding  vector(512) NOT NULL,
  source     text NOT NULL DEFAULT 'wordpress_confirm',
  attachment_id bigint,                            -- WordPress attachment ID
  bbox       jsonb,                                -- {x,y,w,h} if from a crop
  confidence real,                                 -- detection confidence 0..1
  quality_tier text NOT NULL CHECK (quality_tier IN ('high','medium','low')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX aug_emb_tenant_idx ON augmented_embeddings(tenant_id);
CREATE INDEX aug_emb_roster_idx ON augmented_embeddings(roster_entry_id);
CREATE INDEX aug_emb_observation_idx ON augmented_embeddings(observation_id);
CREATE INDEX aug_emb_quality_idx ON augmented_embeddings(quality_tier);

-- Aggregate embeddings view (computed weighted average for recognition)
-- This materializes the aggregate for each roster entry by combining reference + augmented
CREATE MATERIALIZED VIEW roster_aggregate_embeddings AS
SELECT
  re.id AS roster_entry_id,
  re.tenant_id,
  -- Weighted average: reference embeddings (weight=1.0) + augmented by quality tier
  -- high=1.0, medium=0.8, low=0.5
  AVG(
    CASE
      WHEN ref.embedding IS NOT NULL THEN ref.embedding
      WHEN aug.quality_tier = 'high' THEN aug.embedding
      WHEN aug.quality_tier = 'medium' THEN aug.embedding * 0.8
      WHEN aug.quality_tier = 'low' THEN aug.embedding * 0.5
    END
  ) AS aggregate_embedding
FROM roster_entities re
LEFT JOIN reference_embeddings ref ON ref.roster_entry_id = re.id
LEFT JOIN augmented_embeddings aug ON aug.roster_entry_id = re.id
GROUP BY re.id, re.tenant_id;

CREATE UNIQUE INDEX roster_agg_emb_roster_idx ON roster_aggregate_embeddings(roster_entry_id);

-- ANN index on aggregate embeddings for fast similarity search
CREATE INDEX roster_agg_emb_vec_ivfflat_idx ON roster_aggregate_embeddings
  USING ivfflat (aggregate_embedding vector_cosine_ops) WITH (lists = 100);

-- Alternative: HNSW index (PostgreSQL 16+ with pgvector 0.5.0+)
-- CREATE INDEX roster_agg_emb_vec_hnsw_idx ON roster_aggregate_embeddings
--   USING hnsw (aggregate_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

**Progressive Learning Pattern:**

1. WordPress confirms identity → sends embedding + observation_id
2. Backend inserts into `augmented_embeddings` (idempotent via observation_id UNIQUE constraint)
3. Backend refreshes materialized view: `REFRESH MATERIALIZED VIEW roster_aggregate_embeddings`
4. Backend triggers FAISS index rebuild from updated aggregates
5. Subsequent searches use improved weighted average

### Optional: Audit/Webhooks

```sql
CREATE TABLE webhook_events (
  id        bigserial PRIMARY KEY,
  tenant_id uuid,
  type      text NOT NULL,
  payload   jsonb NOT NULL,
  delivered boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

### Row‑Level Security (RLS) pattern

```sql
ALTER TABLE roster_entities ENABLE ROW LEVEL SECURITY;
CREATE POLICY roster_tenant_iso ON roster_entities
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
CREATE POLICY embeddings_tenant_iso ON embeddings
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- At request start, set: SET LOCAL app.tenant_id = '<tenant-uuid>';
```

### Recognition queries (pgvector)

**Top‑K by cosine:**

```sql
-- SET ivfflat.probes = 10;  -- tune per latency/recall
SELECT e.entity_id,
       re.label,
       1 - (e.vec <=> $1::vector) AS score
FROM embeddings e
JOIN roster_entities re ON re.id = e.entity_id
WHERE e.tenant_id = $2
ORDER BY e.vec <=> $1::vector
LIMIT 10;
```

**Upserting new observation embedding after a confirmation:**

```sql
WITH ins AS (
  INSERT INTO embeddings (tenant_id, entity_id, source, vec, image_url, bbox, quality)
  VALUES ($1, $2, 'observation', $3::vector, $4, $5::jsonb, $6)
  RETURNING id
)
UPDATE roster_entities re
SET revision = re.revision + 1,
    updated_at = now()
WHERE re.id = $2 AND re.tenant_id = $1;
```

---

## Phase 2 — FAISS as Derived In-Memory Index

**Architecture Decision:** FAISS is a **derived, in-memory index** synchronized from the canonical database (PostgreSQL or SQLite). The database remains the source of truth.

**When to enable:**

- Corpus grows beyond 10K embeddings
- SLOs require <10ms query latency
- Need GPU acceleration or advanced quantization (IVF-PQ)

**Synchronization Strategy:**

```python
# HybridIndexManager: hot-reload FAISS from database on updates
class HybridIndexManager:
    def __init__(self, storage_adapter: StorageAdapter):
        self.storage = storage_adapter
        self.index = None
        self.entity_map = {}  # faiss_id -> roster_entry_id

    def rebuild_from_database(self):
        """Rebuild FAISS index from aggregate embeddings in database"""
        aggregates = self.storage.get_all_aggregate_embeddings()

        if not aggregates:
            self.index = None
            return

        embeddings = np.array([agg["embedding"] for agg in aggregates])

        # Use IndexFlatIP (cosine via normalized L2) or HNSW/IVF for larger corpora
        self.index = faiss.IndexFlatIP(embeddings.shape[1])
        self.index.add(embeddings)

        self.entity_map = {i: agg["roster_entry_id"] for i, agg in enumerate(aggregates)}

    def search(self, query_embedding: np.ndarray, top_k: int = 5):
        """Search FAISS index and map results back to roster entries"""
        if self.index is None:
            # Fallback to database search if FAISS not available
            return self.storage.search_embeddings(query_embedding, top_k)

        distances, indices = self.index.search(query_embedding.reshape(1, -1), top_k)

        return [
            {
                "roster_entry_id": self.entity_map[idx],
                "distance": float(dist),
                "similarity": float(dist)  # already cosine similarity with IndexFlatIP
            }
            for dist, idx in zip(distances[0], indices[0])
            if idx in self.entity_map
        ]
```

**Hybrid Storage Mode (Config):**

```python
# recognition_core/config.py
class Settings:
    USE_FAISS_ACCELERATION: bool = False  # Enable FAISS for production
    FAISS_INDEX_PATH: Optional[Path] = None  # Persist to disk for faster restarts

# In startup
if settings.USE_FAISS_ACCELERATION:
    hybrid_manager.rebuild_from_database()
    if settings.FAISS_INDEX_PATH and settings.FAISS_INDEX_PATH.exists():
        hybrid_manager.load_from_disk(settings.FAISS_INDEX_PATH)
```

**Progressive Learning Integration:**

- When WordPress confirms identity → insert into `augmented_embeddings`
- Backend refreshes materialized view: `REFRESH MATERIALIZED VIEW roster_aggregate_embeddings`
- Backend triggers `hybrid_manager.rebuild_from_database()` to update FAISS
- Next search uses improved aggregate embedding

**Note:** For most deployments, **native pgvector HNSW** (PostgreSQL 16+ with pgvector ≥0.5.0) provides sufficient performance without FAISS complexity.

---

## API Surface (FastAPI example — server)

**POST /api/v0/roster** — create person/brand  
**PUT /api/v0/roster/{id}** — update label/meta  
**DELETE /api/v0/roster/{id}** — hard delete (cascade embeddings)  
**POST /api/v0/roster/{id}/confirm** — record observation; optional vec supplied by client  
**GET /api/v0/recognize** — embed crops server‑side → search (pgvector/FAISS)  
**GET /api/v0/roster?since=rev** — delta sync; also support `If-None-Match`/`ETag`

Pydantic models (sketch):

```python
class RosterEntity(BaseModel):
    id: UUID
    tenant_id: UUID
    label: str
    type: Literal['person','brand','other']
    meta: dict = {}
    revision: int

class EmbeddingCreate(BaseModel):
    entity_id: Optional[UUID]
    source: Literal['aggregate','observation']
    vec: List[float]           # length 512
    image_url: Optional[str]
    bbox: Optional[dict]
    quality: Optional[float]
```

---

## Payment & User Data

- **Do not store** card numbers or sensitive payment data. Use **Stripe** (or equivalent) and save only tokens/IDs:
  - `tenants.stripe_customer_id`
  - `subscriptions.stripe_subscription_id`, `price_id`, `status`, `current_period_end`
- **Usage‑based pricing:** update `usage_counters` per request; reconcile daily for billing and rate limiting.
- **Privacy:** implement DSAR delete → delete roster entity + cascade embeddings (`ON DELETE SET NULL` or hard delete by job), and audit the action.

---

## Operational Notes

- **Backups:** Postgres continuous backups (pgBackRest or managed service).
- **Migrations:** `alembic` (Python) or `golang-migrate` — keep DDL in repo.
- **Index maintenance:** re‑analyze after large imports; vacuum strategy for big embedding churn.
- **Partitioning (later):** range partition `embeddings` on `created_at` if volume > 50M rows.
- **Secrets:** env‑only; rotate API keys; hash keys with strong KDF; never log raw tokens.

---

## Success Markers

- Creating a roster person writes to `roster_entities` and returns `revision`/`etag`.
- Confirming faces writes **embeddings** and bumps `revision` in one transaction.
- Recognition query returns top‑K in **≤150 ms** for 1M embeddings on mid‑tier hardware (IVFFLAT probes tuned).
- Stripe webhook updates `subscriptions.status` and `current_period_end` within 10s.
- DSAR delete for an entity removes or nulls related embeddings and returns 204.

---

## Minimal DAO Query Examples (server)

**Create entity:**

```sql
INSERT INTO roster_entities (tenant_id, label, type, meta)
VALUES ($1, $2, $3, $4::jsonb)
RETURNING id, revision;
```

**Attach observation embedding:**

```sql
INSERT INTO embeddings (tenant_id, entity_id, source, vec, image_url, bbox, quality)
VALUES ($1, $2, 'observation', $3::vector, $4, $5::jsonb, $6);
```

**Search (pgvector cosine):**

```sql
SET LOCAL ivfflat.probes = 10;
SELECT re.id, re.label, 1 - (e.vec <=> $1::vector) AS score
FROM embeddings e
JOIN roster_entities re ON re.id = e.entity_id
WHERE e.tenant_id = $2
ORDER BY e.vec <=> $1::vector
LIMIT $3;
```

---

## Client Impact (WordPress plugin)

- Store only **remote_id/etag/revision** locally; do not persist vectors.
- Cache labels/avatars for UX; rely on remote for recognition.
- Sync delta via `If-None-Match` ETag; remote = authority.

---

## Checklist to Implement

1. Stand up managed **Postgres 15+** with `pgvector` and extensions above.
2. Apply **DDL** in this document; add RLS policies.
3. Implement DAO layer + migrations; seed admin tenant.
4. Implement **/roster, /recognize, /confirm** endpoints backed by Postgres.
5. Tune IVFFLAT `lists` and query `probes`; establish latency SLOs.
6. Wire **Stripe** customer/subscription webhooks → update `tenants/subscriptions/usage`.
7. Add **DSAR delete** and audit trail events.
8. (Optional) Build **FAISS Adapter**; snapshot & warm strategy; toggle via config.
