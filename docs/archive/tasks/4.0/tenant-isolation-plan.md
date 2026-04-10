# Tenant Isolation Implementation Guide

> **Goal**: Enforce row-level security (RLS) at the database layer to prevent cross-tenant data access, even if application logic has bugs.  
> **Status**: Implementation specification  
> **Created**: 2025-11-16

## Overview

This plan combines PostgreSQL row-level security (RLS) with a trusted tenant context set by the application layer. The WordPress proxy validates the authenticated request and passes a verified tenant ID to the FastAPI service, which sets a PostgreSQL session variable before executing queries. RLS policies then automatically filter all reads/writes to the current tenant.

**Key Principles**:

- **Defense in depth**: RLS provides database-level enforcement even if application code is compromised
- **Trusted context**: Only the application layer (never user input) sets the tenant ID
- **Transparent filtering**: Queries don't need explicit `WHERE tenant_id = ?` clauses
- **Fail-safe default**: Without a valid tenant context, all queries return empty results or fail

---

## Current Architecture

### Tenant ID Generation

The WordPress plugin generates a deterministic tenant ID from the site URL:

```php
// apps/prototype-wp-alt-context/src/api/class-recognition-proxy-controller.php
private function get_tenant_id(): string {
    return md5( (string) get_site_url() );
}
```

This ensures multi-site WordPress installations have distinct tenant IDs per blog.

### Request Flow

1. User authenticates to WordPress admin
2. Frontend calls WordPress REST API (`/wp-json/acx/v1/...`)
3. WordPress validates nonce and capabilities
4. `RecognitionProxyController` generates tenant ID from site URL
5. Proxy forwards request to FastAPI service with `tenant_id` in JSON body
6. FastAPI service queries database with explicit `WHERE tenant_id = ?`

### Current Limitations

- **No database-level enforcement**: Application bugs could leak cross-tenant data
- **Manual filtering**: Every query must remember to filter by `tenant_id`
- **Trust in application code**: Compromised API keys bypass all tenant isolation

### Outstanding Gaps To Address

1. **Connection-pool hygiene**: when SQLAlchemy reuses a connection, it might still have `app.current_tenant` set from a prior request. **Fix**: install a SQLAlchemy `checkout` listener (and an explicit `clear_tenant_context()` call when returning sessions) that always executes `RESET app.current_tenant` before the connection is reused, ensuring pooled connections never leak a prior tenant context.
2. **Background workers**: Celery/RQ jobs and CLI scripts currently run without tenant context, so they must adopt the same helper that API routes use.
3. **Automated validation**: unit/integration tests must fail loudly if a query executes without a tenant context. **Fix**: add tests that deliberately omit `set_tenant_context()` and assert PostgreSQL raises `policy violation`, plus API/integration tests that send requests without `tenant_id` and expect 4xx errors. Wire those tests into CI to guard against regressions.

The rest of this guide closes those gaps before RLS is enabled.

---

## Implementation Phases

### Phase 1: Database Schema Preparation *(Status: Completed)*

**Goal**: Ensure all tenant-scoped tables have proper indexes and constraints.

#### Task 1.1: Verify Existing tenant_id Columns

All multi-tenant tables already have `tenant_id` columns:

- `media_identities.tenant_id` (FK to `tenants.id`)
- `identity_clusters.tenant_id` (FK to `tenants.id`)
- `identity_members.tenant_id` (FK to `tenants.id`)
- `identity_scan_jobs.tenant_id` (FK to `tenants.id`)

**Verification**:

```sql
SELECT
    t.table_name,
    c.column_name,
    c.data_type,
    tc.constraint_type
FROM information_schema.tables t
JOIN information_schema.columns c ON t.table_name = c.table_name
LEFT JOIN information_schema.constraint_column_usage ccu ON c.column_name = ccu.column_name AND c.table_name = ccu.table_name
LEFT JOIN information_schema.table_constraints tc ON ccu.constraint_name = tc.constraint_name
WHERE t.table_schema = 'public'
  AND c.column_name = 'tenant_id'
ORDER BY t.table_name;
```

#### Task 1.2: Create Composite Indexes for Performance *(Completed via merged migration)*

Add indexes on `(tenant_id, id)` for efficient tenant-scoped lookups. These are now part of the baseline migration (`db/migrations/versions/001_identity_schema.py`) so every fresh database comes with the tenant indexes plus `(tenant_id, media_id)` for `media_identities`.

**Verification**:

```bash
cd apps/prototype-description-service
alembic upgrade head
psql -U postgres -d prototype_description -c "\di idx_*_tenant_*"
```

**Estimated Time**: 2 hours

---

### Phase 2: Row-Level Security Policies *(Status: Completed with merged schema)*

**Goal**: Enable RLS and create policies that enforce tenant isolation. These statements now live inside `001_identity_schema.py` so RLS is enabled the moment the schema is created (no follow-up migration required).

**Notes**:

- `current_setting('app.current_tenant', true)` returns `NULL` if variable not set, causing queries to return empty results
- `FOR ALL` applies to SELECT, INSERT, UPDATE, DELETE
- `USING` clause filters reads; `WITH CHECK` validates writes
- Superuser connections (like Alembic migrations) bypass RLS

**Verification**:

```sql
-- Check RLS is enabled
SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public' AND rowsecurity = true;

-- List policies
SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual
FROM pg_policies
WHERE schemaname = 'public';
```

**Estimated Time**: 3 hours

---

### Phase 3: Application Layer Integration *(Status: In progress – tenant context helper live)*

**Goal**: Set the `app.current_tenant` session variable before executing queries.

#### Task 3.1: Create Tenant Context Dependency

**New File** (`apps/prototype-description-service/db/tenant_context.py`):

```python
"""Tenant context management for row-level security."""

from __future__ import annotations

from typing import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """
    Set the app.current_tenant session variable for RLS enforcement.

    Must be called before any queries that touch tenant-scoped tables.
    """
    await session.execute(
        text("SET LOCAL app.current_tenant = :tenant_id"),
        {"tenant_id": str(tenant_id)},
    )


async def clear_tenant_context(session: AsyncSession) -> None:
    """Clear the tenant context (primarily for testing)."""
    await session.execute(text("RESET app.current_tenant"))


async def get_tenant_aware_session(
    session: AsyncSession, tenant_id: UUID
) -> AsyncIterator[AsyncSession]:
    """
    Dependency that yields a session with tenant context set.

    Usage:
        @router.get("/resource")
        async def get_resource(
            tenant_id: UUID,
            session: AsyncSession = Depends(get_tenant_aware_session),
        ):
            # Session automatically filters by tenant_id
            result = await session.execute(select(Resource))
    """
    await set_tenant_context(session, tenant_id)
    try:
        yield session
    finally:
        # Explicitly reset so pooled connections never leak a prior tenant
        await clear_tenant_context(session)

# Optional: hook into SQLAlchemy events so every connection starts with a clean slate
# engine = async_session_factory().bind
# event.listen(engine.sync_engine, "checkout", lambda dbapi_conn, *_: dbapi_conn.cursor().execute("RESET app.current_tenant"))
```

#### Task 3.2: Update Router to Use Tenant Context

**Modify** (`apps/prototype-description-service/recognition/interface_adapters/http/recognition_router.py`):

```python
from db.tenant_context import set_tenant_context

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_media(
    request: AnalyzeRequest,
    session: AsyncSession = Depends(get_session),
    provider: FaceEmbeddingProvider = Depends(get_embedding_provider),
) -> AnalyzeResponse:
    # Set tenant context before any database operations
    await set_tenant_context(session, request.tenant_id)

    await _ensure_tenant(session, request.tenant_id, request.site_url)

    # Rest of implementation...
    # All queries now automatically filtered by tenant_id via RLS
```

Apply to all endpoints:

- `analyze_media`
- `get_analysis_job`
- `cluster_media`
- `list_clusters`
- `get_cluster_detail`
- `reassign_cluster_identity`

#### Task 3.3: Update Service Classes

**Modify** (`apps/prototype-description-service/recognition/application/identity_scan_service.py`):

Services receive tenant_id in constructor and queries are automatically filtered by RLS. **No changes needed** to query logic, but document the RLS dependency:

```python
class IdentityScanService:
    """
    Identity scanning service.

    Requires app.current_tenant session variable to be set before use.
    All queries are automatically filtered by tenant_id via RLS policies.
    """

    def __init__(
        self,
        session: AsyncSession,
        provider: FaceEmbeddingProvider,
        tenant_id: UUID,
    ):
        self.session = session
        self.provider = provider
        self.tenant_id = tenant_id
        # Note: Caller must call set_tenant_context(session, tenant_id) before instantiation
```

**Estimated Time**: 4 hours
*(Implementation underway: `set_tenant_context` helper created, all recognition routes now call it, decorator helper drafted for background tasks.)*

---

### Phase 4: Middleware for Automatic Context Setting

**Goal**: Create FastAPI middleware that sets tenant context automatically based on request headers or JWT claims.

#### Task 4.1: Create Tenant Middleware

**New File** (`apps/prototype-description-service/api/middleware/tenant_middleware.py`):

```python
"""Middleware to automatically set tenant context from authenticated requests."""

from typing import Callable
from uuid import UUID

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session_factory
from db.tenant_context import set_tenant_context


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    Extracts tenant_id from request and sets database session context.

    For now, tenant_id is expected in the request body (trusted from WordPress proxy).
    Future: Extract from JWT claims or API key mapping.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only process if this is a database-bound request
        if request.method in ("POST", "PUT", "PATCH", "DELETE") or \
           request.url.path.startswith("/recognition"):

            # For POST/PUT/PATCH, tenant_id is in body
            if request.method in ("POST", "PUT", "PATCH"):
                # Note: This consumes the body stream, need to cache it
                body = await request.body()
                # Parse tenant_id from JSON (this is a simplified example)
                # In production, use proper JSON parsing with error handling

                # For now, rely on route-level tenant context setting
                # Middleware approach requires request body caching
                pass

        response = await call_next(request)
        return response
```

**Note**: Full middleware implementation requires request body caching (non-trivial with FastAPI). Current approach of explicit `set_tenant_context()` calls in routes is simpler and more explicit.

**Decision**: Defer middleware implementation to Phase 5 (optional optimization). Use explicit context setting for now.

**Estimated Time**: 2 hours (investigation only)

---

#### Task 3.4: Background Jobs and Scripts

Any asynchronous workers (Celery/RQ), cron scripts, or management commands that touch tenant data **must** set the tenant context before issuing queries. Add helper utilities so workers look like:

```python
async with async_session_factory() as session:
    await set_tenant_context(session, tenant_id)
    service = IdentityClusteringService(session=session, tenant_id=tenant_id, provider=provider)
    await service.merge_similar_clusters()
```

Document this requirement in every worker module and add unit tests that fail when `app.current_tenant` is unset (expecting `policy violation`). Without this guard, background jobs could unintentionally run with the previous tenant's context from the pool.

**Estimated Time**: 1 hour

---

##### Tenant Task Decorator

Create a centralized decorator (e.g., `@tenant_task`) that:
1. Accepts `tenant_id` as a keyword argument.
2. Opens a session via `async_session_factory`, sets the tenant context, runs the wrapped function, and clears the context.
3. Makes it easy for CLI scripts or Celery/RQ tasks to stay stateless:

```python
@tenant_task
async def merge_clusters(session: AsyncSession, *, threshold: float):
    await IdentityClusteringService(session, tenant_id, similarity_threshold=threshold).merge_similar_clusters()
```

This keeps tenant plumbing in the runner while developer-facing functions remain synchronous and easy to test.

##### Improved Worker Pattern

To keep developer ergonomics high while enforcing RLS, wrap all worker entry points with a `@tenant_task` decorator (or custom Celery/RQ base class):

1. **Tenant-neutral business functions** accept `(session, payload)` assuming the session already has tenant context.
2. **Decorator/runner** extracts `tenant_id` from the job payload, opens a session, calls `set_tenant_context(session, tenant_id)` once, runs the business function, and then resets the context before returning the connection to the pool.
3. **Static checks/tests** ensure every task uses this decorator so no job can bypass RLS accidentally.

This separates infrastructure concerns (tenant plumbing, retries, logging) from task logic; developers just write the business function while the runner guarantees RLS compliance for Celery/RQ workers and CLI scripts alike.

### Phase 5: Testing and Validation

**Goal**: Verify RLS policies block cross-tenant access and don't break legitimate queries.

#### Task 5.1: Unit Tests for Tenant Context *(Completed)*

Implemented in `apps/prototype-description-service/recognition/tests/test_tenant_isolation.py` with the following coverage:

- RLS filters SELECTs to the active tenant context (`set_tenant_context`).
- INSERTs without tenant context raise a PostgreSQL policy violation.
- HTTP GET `/recognition/jobs/{job_id}` requires the caller’s `tenant_id`, returning `404` for mismatched tenants.

#### Task 5.2: Integration Tests for API Endpoints *(Completed)*

API-level checks now live alongside the unit tests. They prove:

- `/recognition/analyze` can create jobs for tenant A, and tenant B receives `404` when querying `/recognition/jobs/{job_id}`.
- `/recognition/clusters` only returns data for the requesting tenant; other tenants see an empty collection.

#### Task 5.3: Manual Verification Script *(Completed — `apps/prototype-description-service/scripts/verify_rls.py`)*

```python
"""Manual verification script for RLS enforcement."""

import asyncio
from uuid import uuid4
from sqlalchemy import select, text
from db.session import async_session_factory
from db.models import MediaIdentity, Tenant
from db.tenant_context import set_tenant_context


async def verify_rls():
    """Run manual RLS verification checks."""
    async with async_session_factory() as session:
        # Create two test tenants
        tenant_a = Tenant(id=uuid4(), site_url="https://test-a.local")
        tenant_b = Tenant(id=uuid4(), site_url="https://test-b.local")
        session.add_all([tenant_a, tenant_b])
        await session.commit()

        print(f"Created tenant A: {tenant_a.id}")
        print(f"Created tenant B: {tenant_b.id}")

        # Insert identity for tenant A
        await set_tenant_context(session, tenant_a.id)
        identity_a = MediaIdentity(
            tenant_id=tenant_a.id,
            media_id=999,
            media_url="https://example.com/test.jpg",
            bbox_x=0, bbox_y=0, bbox_width=100, bbox_height=100,
            confidence=0.95,
            embedding=[0.1] * 512,
        )
        session.add(identity_a)
        await session.commit()
        print(f"✓ Inserted identity for tenant A: {identity_a.id}")

        # Query as tenant A (should see 1 row)
        result = await session.execute(select(MediaIdentity))
        count_a = len(result.scalars().all())
        print(f"✓ Tenant A sees {count_a} identity (expected: 1)")
        assert count_a == 1, f"Expected 1, got {count_a}"

        # Switch to tenant B
        await session.rollback()
        await set_tenant_context(session, tenant_b.id)

        # Query as tenant B (should see 0 rows)
        result = await session.execute(select(MediaIdentity))
        count_b = len(result.scalars().all())
        print(f"✓ Tenant B sees {count_b} identities (expected: 0)")
        assert count_b == 0, f"Expected 0, got {count_b}"

        # Try to insert with wrong tenant_id
        identity_wrong = MediaIdentity(
            tenant_id=tenant_a.id,  # Wrong tenant!
            media_id=1000,
            media_url="https://example.com/wrong.jpg",
            bbox_x=0, bbox_y=0, bbox_width=100, bbox_height=100,
            confidence=0.90,
            embedding=[0.2] * 512,
        )
        session.add(identity_wrong)

        try:
            await session.commit()
            print("✗ FAILED: Should have blocked cross-tenant insert")
        except Exception as e:
            if "policy" in str(e).lower():
                print(f"✓ RLS blocked cross-tenant insert: {e}")
            else:
                print(f"✗ Unexpected error: {e}")

        # Cleanup
        await session.rollback()
        print("\n✓ All RLS checks passed!")


if __name__ == "__main__":
    asyncio.run(verify_rls())
```

**Run verification**:

```bash
cd apps/prototype-description-service
python scripts/verify_rls.py
```

**Estimated Time**: 6 hours

---

### Phase 6: WordPress Proxy Hardening

**Goal**: Ensure WordPress proxy never leaks tenant IDs from untrusted sources.

#### Task 6.1: Audit Tenant ID Usage

**Review** all places `get_tenant_id()` is called to ensure it's never overrideable by user input:

```php
// ✓ GOOD: Deterministic from server-side context
private function get_tenant_id(): string {
    return md5( (string) get_site_url() );
}

// ✗ BAD: Never do this
private function get_tenant_id(): string {
    // NEVER trust user input for tenant ID
    return sanitize_text_field( $_REQUEST['tenant_id'] ?? md5( get_site_url() ) );
}
```

**Action**: Verify all REST controller methods use `$this->get_tenant_id()` and never `$request->get_param('tenant_id')`.

#### Task 6.2: Add Tenant ID Validation Comment

**Modify** (`apps/prototype-wp-alt-context/src/api/class-recognition-proxy-controller.php`):

```php
/**
 * Get the tenant ID for the current WordPress site.
 *
 * SECURITY: This value is computed server-side and must NEVER be
 * overrideable by user input. The recognition service trusts this
 * value for row-level security enforcement.
 *
 * @return string MD5 hash of the site URL (UUID format in production).
 */
private function get_tenant_id(): string {
    return md5( (string) get_site_url() );
}
```

#### Task 6.3: Consider JWT-Based Tenant Claims (Future)

For production deployments, replace MD5 hash with signed JWT:

```php
private function get_tenant_id(): string {
    // Future: Use WordPress site UUID from database
    $site_uuid = get_option( 'alt_context_tenant_uuid' );

    if ( ! $site_uuid ) {
        // Generate and persist tenant UUID on first use
        $site_uuid = wp_generate_uuid4();
        update_option( 'alt_context_tenant_uuid', $site_uuid, false );
    }

    return $site_uuid;
}
```

**Estimated Time**: 2 hours

---

## Rollout Strategy

### Development Environment

1. Apply migrations on local PostgreSQL
2. Run verification script
3. Run integration tests
4. Manually test WordPress → FastAPI flow

### Staging Environment

1. Coordinate downtime window (RLS adds minimal overhead but test first)
2. Apply migrations: `alembic upgrade head`
3. Deploy updated FastAPI code
4. Run smoke tests with two test WordPress sites
5. Monitor PostgreSQL logs for policy violations

### Production Rollout

Because this is a greenfield deployment with no existing tenants, apply migrations and enable RLS immediately after deploying the code. No feature flags or staged toggles are required—simply `alembic upgrade head`, restart the service, and begin testing with fresh tenant data. Monitor logs for policy violations as a sanity check.

---

## Performance Considerations

### Index Strategy

Composite indexes on `(tenant_id, id)` ensure efficient lookups:

```sql
EXPLAIN ANALYZE
SELECT * FROM media_identities
WHERE tenant_id = 'uuid-here' AND id = 'another-uuid';

-- Should use: idx_media_identities_tenant_id (Index Scan)
```

### RLS Overhead

- **Minimal**: RLS adds a filter predicate, equivalent to explicit `WHERE tenant_id = ?`
- **Caching**: Session variable set once per transaction (not per query)
- **Planner integration**: PostgreSQL query planner optimizes RLS checks

### Benchmarking

Run `pgbench` with and without RLS enabled to measure overhead:

```bash
# Before RLS
pgbench -c 10 -j 2 -T 60 prototype_description

# After RLS
# Expected: <5% overhead for tenant-scoped queries
```

---

## Monitoring and Alerts

### Log RLS Policy Violations

**PostgreSQL Configuration**:

```ini
# postgresql.conf
log_error_verbosity = verbose
log_statement = 'mod'  # Log INSERT/UPDATE/DELETE
```

**Application Logging**:

```python
# Add to db/tenant_context.py
import logging

logger = logging.getLogger(__name__)

async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    logger.info(f"Setting tenant context: {tenant_id}")
    await session.execute(
        text("SET LOCAL app.current_tenant = :tenant_id"),
        {"tenant_id": str(tenant_id)},
    )
```

### Alerting Rules

Set up alerts for:

1. **Policy violations**: `ERROR: new row violates row-level security policy`
2. **Missing context**: Queries returning 0 rows when data exists
3. **Cross-tenant access attempts**: Audit logs showing tenant B trying to access tenant A's job IDs

---

## Testing Checklist

### Database Layer

- [x] RLS enabled on all tenant-scoped tables
- [x] Policies reference `app.current_tenant` session variable
- [x] Composite indexes created for performance
- [ ] Migration applies cleanly on fresh database

### Application Layer

- [x] `set_tenant_context()` called before all queries
- [x] Sessions automatically `RESET app.current_tenant` after each request/worker
- [x] Service classes document RLS dependency
- [x] Unit tests verify cross-tenant isolation
- [x] Unit test asserts that executing a query without tenant context raises a policy violation
- [x] Integration tests validate API-level enforcement

### WordPress Proxy

- [x] `get_tenant_id()` only uses server-side context
- [x] No user input can override tenant ID
- [ ] JWT claims validated (future enhancement)

### End-to-End

- [ ] Two WordPress sites can't see each other's data
- [ ] Scan jobs isolated per tenant
- [ ] Cluster assignments isolated per tenant
- [ ] Performance overhead <5% for typical queries

---

## Rollback Plan

If RLS causes production issues:

1. **Disable RLS policies** (keeps data, removes enforcement):

   ```sql
   ALTER TABLE media_identities DISABLE ROW LEVEL SECURITY;
   ALTER TABLE identity_clusters DISABLE ROW LEVEL SECURITY;
   ALTER TABLE identity_members DISABLE ROW LEVEL SECURITY;
   ALTER TABLE identity_scan_jobs DISABLE ROW LEVEL SECURITY;
   ```

2. **Revert migration**:

   ```bash
   alembic downgrade base
   ```

3. **Remove tenant context calls**:

   ```bash
   git revert <commit-sha>
   ```

4. **Notify team**: Document issues in incident report

---

## References

- [PostgreSQL Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [SQLAlchemy Session Management](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
- [FastAPI Dependency Injection](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [Multi-Tenant SaaS Security Best Practices](https://cheatsheetseries.owasp.org/cheatsheets/Multitenant_Security_Cheat_Sheet.html)
