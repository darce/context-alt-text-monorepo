# Connection Pool Leak Fix Implementation Plan

**Status:** CRITICAL - Production service crashed due to connection exhaustion  
**Date:** 2025-12-21  
**Priority:** P0 - Deploy immediately after testing

---

## Problem Statement

The recognition service exhausted all database connections during a curation session, causing a crash:

```
QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00
```

**Root Cause:** Connection leak in `dependencies.py` - if `set_tenant_context()` fails, the try/finally block is never entered, leaving the session unclosed.

**Impact:**
- Service crashes after ~15 concurrent requests
- Leaked connections never released until service restart
- Production cost: unlimited connection growth

---

## Solution Overview

| Fix | Priority | Impact | Risk |
|-----|----------|--------|------|
| Fix 1: Move tenant context inside try | P0 | Prevents leak | Low |
| Fix 2: Remove redundant context calls | P1 | Saves 1 query/request | Low |
| Fix 3: Configure connection pool | P0 | Right-size for load | Low |
| Fix 4: Batch suggestion queries | P1 | Reduces N→1 queries | Medium |
| Fix 5: Add monitoring | P1 | Observability | Low |

---

## Phase 0: Scaffolding (MANDATORY)

### 0.1 Pool Monitoring Types

**File:** `recognition/interface_adapters/http/schemas/responses.py` (NEW section)

```python
class ConnectionPoolStats(BaseModel):
    """Connection pool statistics for monitoring.
    
    Attributes:
        size: Configured pool size (base connections).
        overflow: Configured max overflow connections.
        checked_out: Currently checked out connections.
        checked_in: Available connections in pool.
        overflow_count: Current overflow connections in use.
        total_capacity: Maximum possible connections.
        utilization_percent: Percentage of capacity in use.
    """
    
    size: int
    overflow: int
    checked_out: int
    checked_in: int
    overflow_count: int
    total_capacity: int
    utilization_percent: float


class HealthCheckResponse(BaseModel):
    """Health check response with database connectivity.
    
    Attributes:
        status: "healthy" or "degraded".
        database: Database connection status.
        pool_stats: Connection pool statistics.
        timestamp: ISO timestamp of check.
    """
    
    status: str
    database: str
    pool_stats: ConnectionPoolStats | None = None
    timestamp: str
```

### 0.2 Repository Batch Query Interface

**File:** `recognition/domain/repositories.py`

Add to `ClusterRepository` protocol:

```python
class ClusterRepository(Protocol):
    # ... existing methods ...
    
    async def get_labeled_with_representatives(
        self, 
        tenant_id: str,
    ) -> list[tuple[IdentityCluster, list[ClusterRepresentative]]]:
        """Fetch labeled clusters with representatives in single query.
        
        Uses eager loading to avoid N+1 query problem.
        
        Args:
            tenant_id: Tenant UUID string.
            
        Returns:
            List of (cluster, representatives) tuples.
            
        Raises:
            NotImplementedError: Until implemented.
        """
        raise NotImplementedError("TODO: get_labeled_with_representatives")
```

---

## Phase 1: Fix Critical Leak (P0)

### 1.1 Move Tenant Context Inside Try Block

**File:** `recognition/interface_adapters/http/dependencies.py`

**Lines 212-230:**

```python
async def get_session(tenant_id: str | None = Depends(get_tenant_id_optional)) -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy async session; set tenant context when provided."""
    async for session in _get_session():
        try:
            # MOVED INSIDE TRY: Ensures finally runs even if context setting fails
            if tenant_id:
                await set_tenant_context(session, uuid.UUID(str(tenant_id)))
            yield session
            commit = getattr(session, "commit", None)
            if callable(commit):
                await commit()
        except Exception:
            rollback = getattr(session, "rollback", None)
            if callable(rollback):
                await rollback()
            raise
        finally:
            # ALWAYS RUNS NOW: Even if set_tenant_context failed
            if tenant_id:
                await clear_tenant_context(session)
```

**Lines 232-259 (same fix for `get_optional_session`):**

```python
async def get_optional_session(
    tenant_id: str | None = Depends(get_tenant_id_optional),
) -> AsyncIterator[AsyncSession | None]:
    """Best-effort session provider; returns None when the database is unavailable."""
    async for session in _get_session():
        try:
            # Test connectivity first
            await session.execute(text("SELECT 1"))
            # MOVED INSIDE TRY: Guarantees cleanup
            if tenant_id:
                await set_tenant_context(session, uuid.UUID(str(tenant_id)))
        except Exception:
            # Early exit if DB unreachable or context fails
            yield None
            return
        try:
            yield session
            commit = getattr(session, "commit", None)
            if callable(commit):
                await commit()
        except Exception as exc:
            logger.error("get_optional_session: exception during yield/commit: %s", exc)
            rollback = getattr(session, "rollback", None)
            if callable(rollback):
                await rollback()
            raise
        finally:
            if tenant_id:
                await clear_tenant_context(session)
```

**Lines 329-348 (same fix for `get_observability_session`):**

```python
async def get_observability_session() -> AsyncIterator[AsyncSession | None]:
    """Session provider without tenant validation for diagnostics."""
    async for session in _get_session():
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            yield None
            return
        try:
            yield session
            commit = getattr(session, "commit", None)
            if callable(commit):
                await commit()
        except Exception:
            rollback = getattr(session, "rollback", None)
            if callable(rollback):
                await rollback()
            raise
        # No finally needed - no tenant context
```

### 1.2 Remove Redundant Context Setting

**File:** `recognition/interface_adapters/http/dependencies.py`

**Line 514 (remove this line):**

```python
async def build_cluster_service(
    session: AsyncSession,
    tenant_id: str,
    settings: ClusteringSettings | None = None,
) -> ClusterService:
    """Construct a ClusterService wired with SQLAlchemy repositories."""
    settings = settings or get_settings()

    # Auto-provision tenant if it doesn't exist
    tenant_uuid = uuid.UUID(tenant_id)
    await ensure_tenant_exists(session, tenant_uuid)
    # REMOVED: Context already set by get_session dependency
    # await set_tenant_context(session, tenant_uuid)
    
    cluster_repo = SqlAlchemyClusterRepository(session)
    ...
```

---

## Phase 2: Configure Connection Pool (P0)

### 2.1 Add Pool Settings

**File:** `db/settings.py`

Add pool configuration to DatabaseSettings:

```python
class DatabaseSettings(BaseModel):
    """Database connection settings.
    
    Pool sizing guide:
        - Low traffic (< 10 req/s): pool_size=5, max_overflow=2
        - Medium (10-50 req/s): pool_size=10, max_overflow=5
        - High (50+ req/s): pool_size=20, max_overflow=10
    """
    
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://...",
        description="PostgreSQL connection string",
    )
    
    pool_size: int = Field(
        default=10,
        description="Base connection pool size",
    )
    
    max_overflow: int = Field(
        default=5,
        description="Max overflow connections (total = pool_size + max_overflow)",
    )
    
    pool_timeout: int = Field(
        default=30,
        description="Seconds to wait for connection before timeout",
    )
    
    pool_recycle: int = Field(
        default=3600,
        description="Seconds before recycling connections (prevents stale)",
    )
```

### 2.2 Apply Pool Configuration

**File:** `db/session.py`

```python
from db.settings import get_database_settings

_settings = get_database_settings()

engine: AsyncEngine = create_async_engine(
    _settings.postgres_dsn,
    echo=False,
    pool_pre_ping=True,
    pool_size=_settings.pool_size,
    max_overflow=_settings.max_overflow,
    pool_timeout=_settings.pool_timeout,
    pool_recycle=_settings.pool_recycle,
)
```

---

## Phase 3: Batch Suggestion Queries (P1)

### 3.1 Implement Batch Repository Method

**File:** `recognition/infrastructure/repositories/cluster_repository.py`

```python
async def get_labeled_with_representatives(
    self, 
    tenant_id: str,
) -> list[tuple[IdentityCluster, list[ClusterRepresentative]]]:
    """Fetch labeled clusters with representatives via eager loading."""
    from sqlalchemy.orm import selectinload
    from db.models import IdentityCluster as ClusterModel
    from db.models import IdentityClusterRepresentative as RepModel
    
    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError:
        return []
    
    stmt = (
        select(ClusterModel)
        .options(selectinload(ClusterModel.representatives))
        .where(ClusterModel.tenant_id == tenant_uuid)
        .where(ClusterModel.user_confirmed == True)
        .where(ClusterModel.label != None)
        .where(~ClusterModel.label.startswith("cluster-"))
    )
    
    result = await self._session.execute(stmt)
    models = result.scalars().all()
    
    output: list[tuple[IdentityCluster, list[ClusterRepresentative]]] = []
    for model in models:
        cluster = self._to_domain(model)
        reps = [self._rep_to_domain(r) for r in model.representatives]
        output.append((cluster, reps))
    
    return output
```

### 3.2 Use Batch Query in Suggestion Service

**File:** `recognition/application/suggestions/service.py`

**Lines ~218-264:**

```python
async def refresh_for_identity(
    self,
    *,
    identity_id: str,
    reason: SuggestionRefreshReason,
) -> list[AssignmentSuggestion]:
    """Recompute suggestions for a single identity."""
    if self._session is None or self._cluster_repository is None:
        return []
    
    # ... identity loading code ...
    
    # CHANGED: Use batch query instead of loop
    clusters_with_reps = await self._cluster_repository.get_labeled_with_representatives(
        self._tenant_id
    )
    
    suggestions: list[AssignmentSuggestion] = []
    now = datetime.now(tz=UTC)
    
    for cluster, reps in clusters_with_reps:
        cluster_id = cluster.id
        if not cluster_id:
            continue
        
        # Check blocks
        if self._block_repository and await self._block_repository.is_blocked(
            tenant_id=self._tenant_id,
            identity_id=identity_id,
            cluster_id=cluster_id,
        ):
            continue
        
        # Compute similarity with representatives (already loaded)
        best_similarity = 0.0
        for rep in reps:
            rep_vec = np.asarray(getattr(rep, "embedding", rep), dtype=np.float32)
            similarity = compute_face_similarity(identity_embedding, rep_vec)
            best_similarity = max(best_similarity, similarity)
        
        # Check suggestion band
        if best_similarity < self._settings.suggestion_floor:
            continue
        if best_similarity >= self._settings.suggestion_ceiling:
            continue
        
        # Upsert suggestion
        payload = SuggestionCreateData(
            identity_id=identity_id,
            cluster_id=cluster_id,
            representative_similarity=best_similarity,
            member_similarity=best_similarity,
            confidence_score=best_similarity,
            source=reason.value,
            refreshed_at=now,
        )
        suggestion = await self._repository.upsert_by_identity_cluster(self._tenant_id, payload)
        suggestions.append(suggestion)
    
    return suggestions
```

---

## Phase 4: Add Monitoring (P1)

### 4.1 Pool Stats Utility

**File:** `db/session.py`

```python
def get_pool_stats() -> dict[str, int | float]:
    """Return current connection pool statistics.
    
    Returns:
        Dictionary with pool metrics.
    """
    pool = engine.pool
    size = pool.size()
    overflow = pool.overflow()
    checked_out = pool.checkedout()
    checked_in = size - checked_out
    overflow_count = max(0, checked_out - size)
    total_capacity = size + overflow
    utilization = (checked_out / total_capacity * 100) if total_capacity > 0 else 0
    
    return {
        "size": size,
        "overflow": overflow,
        "checked_out": checked_out,
        "checked_in": checked_in,
        "overflow_count": overflow_count,
        "total_capacity": total_capacity,
        "utilization_percent": round(utilization, 2),
    }
```

### 4.2 Health Check Endpoint

**File:** `recognition/interface_adapters/http/routers/health.py` (NEW)

```python
"""Health and monitoring endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_pool_stats
from recognition.interface_adapters.http.dependencies import get_optional_session
from recognition.interface_adapters.http.schemas.responses import (
    ConnectionPoolStats,
    HealthCheckResponse,
)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthCheckResponse)
async def health_check(
    session: AsyncSession | None = Depends(get_optional_session),
) -> HealthCheckResponse:
    """Health check with database connectivity and pool stats."""
    db_status = "disconnected"
    pool_stats_dict = get_pool_stats()
    
    if session is not None:
        try:
            await session.execute(text("SELECT 1"))
            db_status = "connected"
        except Exception:
            db_status = "error"
    
    status = "healthy" if db_status == "connected" else "degraded"
    pool_stats = ConnectionPoolStats(**pool_stats_dict)
    
    return HealthCheckResponse(
        status=status,
        database=db_status,
        pool_stats=pool_stats,
        timestamp=datetime.now(tz=UTC).isoformat(),
    )


@router.get("/pool", response_model=ConnectionPoolStats)
async def pool_stats() -> ConnectionPoolStats:
    """Get connection pool statistics."""
    stats = get_pool_stats()
    return ConnectionPoolStats(**stats)
```

### 4.3 Register Health Router

**File:** `recognition/main.py`

```python
from recognition.interface_adapters.http.routers import health

app.include_router(health.router)
```

---

## Verification Plan

### Unit Tests

**File:** `recognition/tests/unit/test_connection_pool.py` (NEW)

```python
import pytest
from db.session import get_pool_stats


def test_pool_stats_returns_valid_metrics():
    """Pool stats should return all expected metrics."""
    stats = get_pool_stats()
    
    assert "size" in stats
    assert "overflow" in stats
    assert "checked_out" in stats
    assert "checked_in" in stats
    assert "overflow_count" in stats
    assert "total_capacity" in stats
    assert "utilization_percent" in stats
    
    # Utilization should be 0-100
    assert 0 <= stats["utilization_percent"] <= 100


@pytest.mark.asyncio
async def test_session_cleanup_on_context_failure(db_session):
    """Session should close even if set_tenant_context fails."""
    from recognition.interface_adapters.http.dependencies import get_session
    from unittest.mock import patch
    
    initial_stats = get_pool_stats()
    initial_checked_out = initial_stats["checked_out"]
    
    # Mock set_tenant_context to fail
    with patch("recognition.interface_adapters.http.dependencies.set_tenant_context") as mock_set:
        mock_set.side_effect = Exception("Simulated failure")
        
        try:
            async for session in get_session(tenant_id="test-tenant"):
                pass  # Should never reach here
        except Exception:
            pass  # Expected
    
    # Verify connection was returned to pool
    final_stats = get_pool_stats()
    assert final_stats["checked_out"] == initial_checked_out
```

**Run:** `cd apps/prototype-description-service && pytest recognition/tests/unit/test_connection_pool.py -v`

### Integration Tests

**File:** `recognition/tests/integration/test_connection_leak.py` (NEW)

```python
import asyncio
import pytest
from recognition.interface_adapters.http.dependencies import get_session
from db.session import get_pool_stats


@pytest.mark.integration
async def test_concurrent_requests_dont_exhaust_pool():
    """Concurrent requests should not exhaust connection pool."""
    initial_stats = get_pool_stats()
    
    async def simulate_request():
        async for session in get_session(tenant_id="test"):
            await session.execute(text("SELECT 1"))
    
    # Simulate 20 concurrent requests
    tasks = [simulate_request() for _ in range(20)]
    await asyncio.gather(*tasks)
    
    # All connections should be returned
    final_stats = get_pool_stats()
    assert final_stats["checked_out"] <= initial_stats["checked_out"] + 1
```

**Run:** `cd apps/prototype-description-service && pytest recognition/tests/integration/test_connection_leak.py -v`

### API Tests

**File:** `recognition/tests/api/test_health_endpoint.py` (NEW)

```python
@pytest.mark.asyncio
async def test_health_endpoint_returns_pool_stats(test_client):
    """Health endpoint should return connection pool statistics."""
    response = await test_client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "status" in data
    assert "database" in data
    assert "pool_stats" in data
    
    pool = data["pool_stats"]
    assert "size" in pool
    assert "checked_out" in pool
    assert "utilization_percent" in pool


@pytest.mark.asyncio
async def test_pool_endpoint_shows_current_usage(test_client):
    """Pool endpoint should show real-time usage."""
    response = await test_client.get("/health/pool")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should show at least 1 connection (this request)
    assert data["checked_out"] >= 1
    assert data["utilization_percent"] > 0
```

**Run:** `cd apps/prototype-description-service && pytest recognition/tests/api/test_health_endpoint.py -v`

### Manual Verification

**Prerequisites:**
1. Apply all fixes
2. Restart service: `./scripts/start_prototype_local.sh`
3. Open Workbench UI

**Test Steps:**

1. **Verify No Leak:**
   ```bash
   # Monitor pool stats during curation
   watch -n 1 'curl -s http://localhost:8000/health/pool | jq'
   ```
   - Perform 10+ split/merge operations
   - **Expected:** `checked_out` never exceeds `total_capacity`
   - **Expected:** `utilization_percent` returns to ~0% when idle

2. **Load Test:**
   ```bash
   # Simulate 30 concurrent requests
   for i in {1..30}; do
     curl -s http://localhost:8000/health &
   done
   wait
   
   # Check final pool state
   curl -s http://localhost:8000/health/pool | jq
   ```
   - **Expected:** No timeout errors
   - **Expected:** All connections returned to pool

3. **Verify Batch Query:**
   ```bash
   # Enable SQL logging
   export DATABASE_ECHO=true
   
   # Trigger suggestion refresh (split a cluster)
   # Watch logs for SELECT queries
   ```
   - **Expected:** 1-2 queries total (not N queries for N clusters)

---

## Implementation Checklist

### Phase 0: Scaffolding
- [x] Add `ConnectionPoolStats` and `HealthCheckResponse` schemas
- [x] Add `get_labeled_with_representatives` to repository protocol

### Phase 1: Fix Leak (P0)
- [ ] Move `set_tenant_context` inside try block in `get_session`
- [ ] Move `set_tenant_context` inside try block in `get_optional_session`
- [ ] Remove redundant `set_tenant_context` in `build_cluster_service`

### Phase 2: Configure Pool (P0)
- [ ] Add pool settings to `DatabaseSettings`
- [ ] Apply pool configuration in `db/session.py`

### Phase 3: Batch Queries (P1)
- [ ] Implement `get_labeled_with_representatives` in cluster repository
- [ ] Update `refresh_for_identity` to use batch query

### Phase 4: Monitoring (P1)
- [ ] Add `get_pool_stats()` utility
- [ ] Create health check router
- [ ] Register health router in main app

### Testing
- [ ] Write unit tests for pool stats
- [ ] Write unit test for session cleanup on failure
- [ ] Write integration test for concurrent requests
- [ ] Write API tests for health endpoints
- [ ] Manual load testing

### Deployment
- [ ] Update pool configuration for production load
- [ ] Deploy to staging
- [ ] Monitor pool utilization for 24 hours
- [ ] Deploy to production

---

## Acceptance Criteria

✅ No connection leaks under concurrent load  
✅ Pool utilization returns to 0% when idle  
✅ Health endpoint shows real-time pool stats  
✅ Suggestion refresh uses single batch query  
✅ Service handles 30+ concurrent requests  
✅ All tests pass  
✅ Production pool sized for expected load

---

## Rollback Plan

If issues arise:

1. **Immediate:** Restart service to release stale connections
2. **Quick Fix:** Increase pool size to buy time
3. **Full Rollback:** Revert commits, restart service

**Monitoring:** Watch `/health/pool` endpoint - if `utilization_percent > 80%` for >5 minutes, investigate immediately.
