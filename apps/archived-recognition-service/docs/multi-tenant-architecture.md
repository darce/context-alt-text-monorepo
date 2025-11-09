# Multi-Tenant Architecture

## Overview

The recognition service uses a **multi-tenant architecture** to support multiple customers (WordPress sites) sharing the same application and database while maintaining complete data isolation between tenants.

## What is Multi-Tenant Isolation?

**Multi-tenancy** means multiple customers (tenants) share the same application and database, but each tenant's data is kept completely separate and invisible to other tenants.

**In this recognition service:**

- Each WordPress site is a separate **tenant**
- Tenant A's face recognition roster should never see Tenant B's roster
- Tenant A searching for faces should only match against their own roster

## Why It's Needed

### Without Multi-Tenant Isolation (❌ Bad)

```python
# Dangerous: Returns ALL roster entries across ALL customers
entries = session.query(DBRosterEntry).all()

# Tenant A searches and gets matches from Tenant B's celebrities!
# Tenant B's private employee roster leaks to Tenant A
```

**Problems:**

- **Privacy breach**: Tenant A sees Tenant B's people
- **Wrong results**: Face search matches against other tenants' rosters
- **Security violation**: One customer accesses another's data
- **Compliance issue**: GDPR/data protection violations

### With Multi-Tenant Isolation (✅ Good)

```python
# Safe: Only returns entries for the specific tenant
entries = session.query(DBRosterEntry).filter(
    DBRosterEntry.tenant_id == tenant.id  # ← Isolation filter
).all()
```

**Benefits:**

- ✅ Complete data isolation between customers
- ✅ Face matches only against correct roster
- ✅ No data leakage between tenants
- ✅ Compliance with privacy regulations

## Real-World Scenario

Imagine two WordPress sites using the recognition service:

### Tenant A: Celebrity News Site

- **Roster**: Tom Hanks, Meryl Streep, Brad Pitt
- **Use Case**: Uploads photo to identify celebrities

### Tenant B: Corporate Intranet

- **Roster**: John Smith (employee), Jane Doe (employee)
- **Use Case**: Uploads photo to identify employees

### Without Isolation (❌)

```
Tenant B uploads employee photo
→ Service searches ALL rosters
→ Matches against Tenant A's celebrities by mistake
→ Returns "Tom Hanks" for an employee photo ❌
→ PRIVACY BREACH: Tenant A's roster leaked to Tenant B
```

### With Isolation (✅)

```
Tenant B uploads employee photo
→ Service filters: WHERE tenant_id = 'tenant-b'
→ Only searches Tenant B's employee roster
→ Returns correct employee match ✅
→ Tenant A's data never accessed
```

## Implementation

### Database Schema

Every table includes a `tenant_id` column that creates the isolation boundary:

```sql
-- Each table has tenant_id foreign key
CREATE TABLE roster_entries (
    id SERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    unique_id TEXT NOT NULL,
    name TEXT NOT NULL,
    aggregate_embedding VECTOR(512),
    ...
);

-- Ensure uniqueness per tenant, not globally
CREATE UNIQUE INDEX idx_roster_entries_unique_id
    ON roster_entries(tenant_id, unique_id);
```

**Key points:**

- `tenant_id` is required on every row
- Foreign key enforces referential integrity
- Unique constraints are per-tenant (tenant A and B can both have "person-001")

### Code Implementation

Every database query in the PostgreSQL storage adapter includes the tenant filter:

```python
class PostgreSQLStorageAdapter(RosterStoragePort):
    def __init__(self, database_url, tenant_id, ...):
        self.tenant_id = tenant_id  # Set during initialization
        ...

    def load_roster_entries(self, model: str) -> List[RosterEntry]:
        """Load all roster entries for a model."""
        with self._get_session() as session:
            # 1. Ensure tenant exists
            tenant = self._ensure_tenant(session, self.tenant_id)

            # 2. Always filter by tenant_id
            db_entries = session.query(DBRosterEntry).filter(
                DBRosterEntry.tenant_id == tenant.id  # ← Isolation
            ).all()

            return [self._roster_entry_to_domain(e) for e in db_entries]

    def search_similar(self, query_embedding, model, top_k, threshold):
        """Search for similar entries using pgvector."""
        with self._get_session() as session:
            tenant = self._ensure_tenant(session, self.tenant_id)

            # Vector search also isolated by tenant
            results = session.query(
                DBRosterEntry,
                DBRosterEntry.aggregate_embedding.cosine_distance(query_embedding)
            ).filter(
                and_(
                    DBRosterEntry.tenant_id == tenant.id,  # ← Isolation
                    DBRosterEntry.aggregate_embedding.isnot(None)
                )
            ).order_by('distance').limit(top_k).all()

            return [(self._roster_entry_to_domain(e), 1.0-dist)
                    for e, dist in results]
```

### Tenant Creation

Tenants are automatically created on first use:

```python
def _ensure_tenant(self, session: Session, tenant_id: str) -> Tenant:
    """Ensure tenant exists, create if not."""
    tenant = session.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        tenant = Tenant(
            id=tenant_id,
            name=f"Tenant {tenant_id}",
            created_at=datetime.utcnow()
        )
        session.add(tenant)
        session.flush()
        logger.info(f"Created new tenant: {tenant_id}")
    return tenant
```

## Multi-Tenant Strategy: Shared Database

This implementation uses **shared database, shared schema** multi-tenancy:

```
                    ┌─────────────────────┐
                    │   Recognition DB    │
                    │   (PostgreSQL 17)   │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
    ┌────▼────┐          ┌─────▼────┐         ┌─────▼────┐
    │ Tenant A│          │ Tenant B │         │ Tenant C │
    │ (rows)  │          │ (rows)   │         │ (rows)   │
    └─────────┘          └──────────┘         └──────────┘
```

### Advantages

- ✅ **Cost-effective**: One database serves all tenants
- ✅ **Easy maintenance**: Single schema to update
- ✅ **Efficient resource usage**: Shared connection pool
- ✅ **Simple deployment**: One instance to manage
- ✅ **Scalability**: Can serve thousands of tenants

### Trade-offs

- ⚠️ **Query discipline**: Must always filter by tenant_id
- ⚠️ **Performance**: Noisy neighbors can affect others
- ⚠️ **Blast radius**: Database breach could expose multiple tenants
- ⚠️ **Index size**: Indexes span all tenants' data

### Alternative Strategies (Not Implemented)

**Database per Tenant:**

- Each tenant gets their own PostgreSQL database
- Complete isolation but expensive and complex to manage

**Schema per Tenant:**

- Each tenant gets their own schema in shared database
- Better isolation but more complex migrations

## Configuration

### Setting Tenant ID

The tenant ID is set during adapter initialization:

```python
# From environment variable
adapter = PostgreSQLStorageAdapter(
    database_url=os.getenv("DATABASE_URL"),
    tenant_id=os.getenv("DEFAULT_TENANT_ID")
)

# Or explicit configuration
adapter = PostgreSQLStorageAdapter(
    database_url="postgresql+psycopg://...",
    tenant_id="wordpress-site-12345"
)
```

### Tenant ID Format

Tenant IDs should be:

- **Unique**: No two tenants can have the same ID
- **Stable**: Don't change over time
- **Meaningful**: Based on WordPress site URL or site ID
- **UUID format**: `00000000-0000-0000-0000-000000000001` (recommended)

**Example mapping:**

```
WordPress Site                    Tenant ID
─────────────────                ──────────────────────────────────────
example.com                  →   a1b2c3d4-e5f6-7890-abcd-ef1234567890
news.example.com             →   b2c3d4e5-f6a7-8901-bcde-f12345678901
blog.mysite.com              →   c3d4e5f6-a7b8-9012-cdef-123456789012
```

## Security Enhancements

### PostgreSQL Row-Level Security (RLS)

For even stronger isolation, PostgreSQL supports row-level security policies:

```sql
-- Enable RLS on tables
ALTER TABLE roster_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE reference_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE augmented_embeddings ENABLE ROW LEVEL SECURITY;

-- Create policy: Users can only see their tenant's rows
CREATE POLICY tenant_isolation ON roster_entries
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY tenant_isolation ON reference_embeddings
    USING (
        roster_entry_id IN (
            SELECT id FROM roster_entries
            WHERE tenant_id = current_setting('app.current_tenant_id')::uuid
        )
    );
```

**Benefits:**

- Database-level enforcement (can't be bypassed in application code)
- Protection against SQL injection attacks
- Defense in depth security

**To enable RLS in the adapter:**

```python
def _get_session(self):
    """Context manager with tenant-scoped session."""
    session = self.SessionLocal()
    try:
        # Set tenant context for RLS
        session.execute(
            text("SET app.current_tenant_id = :tenant_id"),
            {"tenant_id": self.tenant_id}
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

### API-Level Tenant Identification

The tenant ID should be derived from authentication:

```python
# Future: Extract tenant from JWT token
def get_current_tenant(token: str = Depends(oauth2_scheme)) -> str:
    """Extract tenant ID from authentication token."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    return payload.get("tenant_id")

# Use in API endpoints
@router.post("/roster/entries")
async def add_roster_entry(
    entry: AddRosterEntryRequest,
    tenant_id: str = Depends(get_current_tenant)
):
    adapter = PostgreSQLStorageAdapter(tenant_id=tenant_id)
    ...
```

## Testing Multi-Tenant Isolation

The test suite includes isolation verification:

```python
def test_multi_tenant_isolation(test_database_url):
    """Test that different tenants are isolated."""
    adapter1 = PostgreSQLStorageAdapter(
        database_url=test_database_url,
        tenant_id="tenant-001"
    )
    adapter2 = PostgreSQLStorageAdapter(
        database_url=test_database_url,
        tenant_id="tenant-002"
    )

    # Add entry to tenant 1
    entry1 = RosterEntry(...)
    adapter1.save_roster_entry(entry1, "test_model")

    # Verify tenant 1 can see it
    entries1 = adapter1.load_roster_entries("test_model")
    assert len(entries1) == 1

    # Verify tenant 2 cannot see it
    entries2 = adapter2.load_roster_entries("test_model")
    assert len(entries2) == 0  # ✓ Isolation confirmed
```

## Monitoring & Observability

Track tenant-specific metrics:

```python
# Log tenant activity
logger.info(
    f"Query executed",
    extra={
        "tenant_id": self.tenant_id,
        "operation": "load_roster_entries",
        "entry_count": len(entries),
        "duration_ms": elapsed_time
    }
)

# Prometheus metrics per tenant
roster_entries_total.labels(tenant_id=tenant_id).set(count)
search_latency_seconds.labels(tenant_id=tenant_id).observe(duration)
```

## Best Practices

### DO ✅

- **Always filter by tenant_id** in every query
- **Validate tenant_id** from trusted source (JWT token)
- **Test isolation** in integration tests
- **Monitor per-tenant** resource usage
- **Index tenant_id** columns for performance
- **Use UUIDs** for tenant identifiers
- **Document tenant boundaries** in API specs

### DON'T ❌

- **Never trust client-provided tenant_id** without authentication
- **Don't skip tenant filter** in any query
- **Avoid hard-coding tenant IDs** in application code
- **Don't share connections** between tenants without clearing session state
- **Never expose tenant_id** in public URLs or logs
- **Don't assume single tenant** when writing queries

## Compliance & Privacy

Multi-tenant isolation helps meet regulatory requirements:

### GDPR (EU)

- **Data segregation**: Each tenant's data is logically separated
- **Right to erasure**: Can delete all tenant data in one operation
- **Data portability**: Can export all tenant data efficiently

### HIPAA (US Healthcare)

- **Access controls**: Tenant-level access restrictions
- **Audit logging**: Track all tenant data access

### SOC 2

- **Logical isolation**: Demonstrates data protection controls
- **Monitoring**: Per-tenant audit trails

## Summary

Multi-tenant isolation ensures that:

1. **Privacy**: Each WordPress site's roster is completely private
2. **Security**: No data leakage between customers
3. **Correctness**: Face matching only searches relevant rosters
4. **Compliance**: Meets data protection regulations
5. **Efficiency**: Cost-effective shared infrastructure

Without multi-tenant isolation, the service would be **unusable in production**! 🔒

## References

- Database Schema: `apps/recognition-service/db/models.py`
- Adapter Implementation: `apps/recognition-service/roster/adapters/postgresql_storage_adapter.py`
- Test Suite: `apps/recognition-service/tests/unit/test_postgresql_storage_adapter.py`
- Migration: `apps/recognition-service/db/migrations/versions/0001_baseline_schema.py`
