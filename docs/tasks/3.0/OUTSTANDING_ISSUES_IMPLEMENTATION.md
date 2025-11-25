# Outstanding Issues: Implementation Details

This document provides detailed implementation guidance for resolving the remaining gaps identified in GAPS_IMPROVEMENTS_EXPANDED.md.

## Status Summary

**✅ RESOLVED (Gaps #1, #2, #5, #6, #8):**

- Gap #1: `DatabaseMetrics.record_error` now accepts flexible kwargs
- Gap #2: Materialized view uses scalar multiplication (`embedding * weight`)
- Gap #5: Baseline migration creates required extensions with version check
- Gap #6: Documentation updated to reflect PostgreSQL-only requirement
- Gap #8: `/service/info` exposes progressive learning stats

**⚠️ REQUIRES IMPLEMENTATION (Gaps #3, #4, #7, #9):**

---

## Issue #1: Materialized View Refresh Blocks Request Thread (Gap #3)

**Current Problem:**

- `roster/domain/roster_service.py` (line 305): `add_augmented_embedding()` calls `refresh_aggregate_view()` synchronously
- `roster/adapters/postgresql_storage_adapter.py` (line 415): `REFRESH MATERIALIZED VIEW CONCURRENTLY` runs on request thread
- Large rosters (1000+ entries) cause 500ms-2s blocking

**Impact:** WordPress confirmations take >500ms, violating latency SLA

**Implementation: Add Incremental Refresh Method**

### Step 1: Add `refresh_aggregate_incremental()` Method

File: `apps/recognition-service/roster/adapters/postgresql_storage_adapter.py`

Add after `refresh_aggregate_view()` method (around line 440):

```python
def refresh_aggregate_incremental(self, roster_id: str) -> None:
    """
    Incrementally update aggregate for single roster entry using direct SQL UPDATE.

    Fast path: 5-10ms vs 500ms+ for full MV refresh.
    Trade-off: Only updates specified roster_id, doesn't refresh entire MV.

    Full MV refresh should run:
    - Nightly via cron job
    - After batch imports (>100 entries)
    - On service startup

    Args:
        roster_id: UUID of roster entry to update
    """
    start_time = time.perf_counter()
    operation = "refresh_aggregate_incremental"

    try:
        with self._session() as session:
            # Compute weighted aggregate in subquery, update roster_entries directly
            result = session.execute(text("""
                UPDATE roster_entries
                SET
                    aggregate_embedding = (
                        SELECT
                            (SUM(weighted.embedding * weighted.weight) / NULLIF(SUM(weighted.weight), 0))::vector(512)
                        FROM (
                            -- Reference embeddings: weight = 3.0
                            SELECT embedding, 3.0 AS weight
                            FROM reference_embeddings
                            WHERE roster_entry_id = :roster_id

                            UNION ALL

                            -- Augmented embeddings: quality-based weighting
                            SELECT
                                embedding,
                                CASE quality_tier
                                    WHEN 'high' THEN 3.0
                                    WHEN 'medium' THEN 2.0
                                    WHEN 'low' THEN 1.0
                                    ELSE 2.0
                                END AS weight
                            FROM augmented_embeddings
                            WHERE roster_entry_id = :roster_id
                        ) weighted
                    ),
                    updated_at = NOW()
                WHERE id = :roster_id
                RETURNING id
            """), {"roster_id": roster_id})

            updated = result.fetchone()
            if not updated:
                logger.warning(f"No roster entry found for incremental refresh: {roster_id}")

            session.commit()

        duration_ms = (time.perf_counter() - start_time) * 1000
        self._metrics.record_query(operation, duration_ms, success=True)

        if duration_ms > self._slow_query_threshold_ms:
            self._metrics.record_slow_query(
                operation, duration_ms,
                {"roster_id": roster_id, "type": "incremental"}
            )
            logger.warning(
                f"Slow incremental aggregate refresh: {duration_ms:.2f}ms for {roster_id}"
            )
        else:
            logger.debug(
                f"Incremental aggregate refresh completed: {duration_ms:.2f}ms for {roster_id}"
            )

    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000
        self._metrics.record_query(operation, duration_ms, success=False)
        self._metrics.record_error(operation, exc, context={"roster_id": roster_id})
        logger.error(
            f"Failed to incrementally refresh aggregate for {roster_id}: {exc}",
            exc_info=True
        )
        raise
```

### Step 2: Update RosterService to Use Incremental Refresh

File: `apps/recognition-service/roster/domain/roster_service.py`

Replace lines 305-309:

```python
# OLD CODE:
if hasattr(self.roster_storage, 'refresh_aggregate_view'):
    try:
        self.roster_storage.refresh_aggregate_view(roster_id=unique_id)
    except Exception as exc:
        logger.warning(f"Failed to refresh aggregate view for {unique_id}: {exc}")

# NEW CODE:
if hasattr(self.roster_storage, 'refresh_aggregate_incremental'):
    try:
        # Fast path: 5-10ms incremental update (updates roster_entries directly)
        self.roster_storage.refresh_aggregate_incremental(roster_id=unique_id)
        logger.debug(f"Incremental aggregate refresh scheduled for {unique_id}")
    except Exception as exc:
        logger.warning(f"Failed to refresh aggregate for {unique_id}: {exc}")
        # Graceful degradation: progressive learning still works, just with stale aggregate
elif hasattr(self.roster_storage, 'refresh_aggregate_view'):
    # Fallback: Full MV refresh (slower, 500ms+)
    try:
        self.roster_storage.refresh_aggregate_view(roster_id=unique_id)
        logger.warning(f"Using slow MV refresh for {unique_id} - consider implementing incremental")
    except Exception as exc:
        logger.warning(f"Failed to refresh aggregate view for {unique_id}: {exc}")
```

### Step 3: Add Unit Test

File: `apps/recognition-service/tests/unit/test_postgresql_adapter.py`

```python
def test_refresh_aggregate_incremental(postgresql_adapter, test_roster_entry):
    """Test incremental aggregate refresh updates roster_entries directly."""
    import time

    # Create roster entry with reference embedding
    roster_id = test_roster_entry["unique_id"]
    model = test_roster_entry["model"]

    # Add augmented embedding
    postgresql_adapter.save_augmented_embedding(
        roster_id=roster_id,
        observation_id="test-obs-1",
        embedding=[0.2] * 512,
        quality_tier="high",
        metadata={}
    )

    # Capture initial aggregate
    entry_before = postgresql_adapter.get_roster_entry(roster_id, model)
    aggregate_before = entry_before.aggregate_embedding

    # Trigger incremental refresh
    start = time.perf_counter()
    postgresql_adapter.refresh_aggregate_incremental(roster_id)
    duration_ms = (time.perf_counter() - start) * 1000

    # Verify performance: <50ms for single entry
    assert duration_ms < 50, f"Incremental refresh too slow: {duration_ms:.2f}ms"

    # Verify aggregate updated
    entry_after = postgresql_adapter.get_roster_entry(roster_id, model)
    aggregate_after = entry_after.aggregate_embedding

    assert aggregate_after is not None
    assert aggregate_after != aggregate_before  # Should change after adding augmented
```

---

## Issue #2: Roster Reads Don't Consult Materialized View (Gap #4)

**Current Problem:**

- `_hydrate_roster_entry()` reads from `roster_entries.aggregate_embedding`
- Materialized view only used by pgvector search
- Weighted aggregation logic ignored for API responses, ETags

**Impact:** API returns stale/unweighted aggregates, WordPress sees inconsistent data

**Implementation: Join MV in All Read Queries**

### Step 1: Update `get_roster_entry()` to Join MV

File: `apps/recognition-service/roster/adapters/postgresql_storage_adapter.py`

Replace lines ~250-270:

```python
def get_roster_entry(self, unique_id: str, model: str) -> Optional[RosterEntry]:
    """Fetch roster entry with aggregate from materialized view."""
    with self._timed_operation('get_roster_entry', unique_id=unique_id, model=model):
        with self._session() as session:
            # Join MV to get weighted aggregate (canonical source)
            result = session.execute(text("""
                SELECT
                    re.id,
                    re.label,
                    re.display_name,
                    re.type,
                    re.meta,
                    re.model,
                    re.created_at,
                    re.updated_at,
                    COALESCE(mv.aggregate_embedding, re.aggregate_embedding) AS aggregate_embedding,
                    mv.reference_count,
                    mv.augmented_count
                FROM roster_entries re
                LEFT JOIN roster_aggregate_embeddings mv
                    ON mv.roster_entry_id = re.id
                WHERE re.id = :id AND re.model = :model
            """), {"id": unique_id, "model": model}).fetchone()

            if not result:
                return None

            # Fetch sub-entities (reference images, augmented embeddings)
            reference_images = self._load_reference_images(unique_id)
            augmented_embeddings = self._load_augmented_embeddings(unique_id)

            # Hydrate using MV data
            return self._hydrate_roster_entry(result, augmented_embeddings, reference_images)
```

### Step 2: Update `load_roster_entries()` to Join MV

File: `apps/recognition-service/roster/adapters/postgresql_storage_adapter.py`

Replace lines ~150-180:

```python
def load_roster_entries(self, model: str) -> List[RosterEntry]:
    """Load all roster entries for model with MV aggregates."""
    with self._timed_operation('load_roster_entries', model=model):
        with self._session() as session:
            results = session.execute(text("""
                SELECT
                    re.id,
                    re.label,
                    re.display_name,
                    re.type,
                    re.meta,
                    re.model,
                    re.created_at,
                    re.updated_at,
                    COALESCE(mv.aggregate_embedding, re.aggregate_embedding) AS aggregate_embedding,
                    mv.reference_count,
                    mv.augmented_count
                FROM roster_entries re
                LEFT JOIN roster_aggregate_embeddings mv
                    ON mv.roster_entry_id = re.id
                WHERE re.model = :model
                ORDER BY re.created_at DESC
            """), {"model": model}).fetchall()

            # Hydrate all entries
            entries = []
            for row in results:
                reference_images = self._load_reference_images(row.id)
                augmented_embeddings = self._load_augmented_embeddings(row.id)
                entry = self._hydrate_roster_entry(row, augmented_embeddings, reference_images)
                entries.append(entry)

            return entries
```

### Step 3: Update `_hydrate_roster_entry()` to Track MV Source

File: `apps/recognition-service/roster/adapters/database_storage_base.py`

Replace lines ~735-750:

```python
def _hydrate_roster_entry(
    self, row, augmented_embeddings, reference_images
) -> RosterEntry:
    metadata = _coerce_metadata(row.meta)
    metadata.setdefault("model", getattr(row, "model", None))
    metadata["augmented_embeddings"] = augmented_embeddings

    # Use MV aggregate if available (row has reference_count from MV join)
    aggregate_embedding = getattr(row, "aggregate_embedding", None)

    # Add MV stats to metadata for debugging/monitoring
    if hasattr(row, "reference_count") and row.reference_count is not None:
        metadata["_mv_stats"] = {
            "reference_count": row.reference_count,
            "augmented_count": row.augmented_count or 0,
            "source": "materialized_view",
            "hydrated_at": datetime.utcnow().isoformat()
        }
        logger.debug(f"Hydrating {row.label} with MV aggregate: {row.reference_count} ref + {row.augmented_count or 0} aug")
    else:
        # Fallback to roster_entries column (MV not available)
        logger.warning(f"Hydrating {row.label} without MV data - using roster_entries.aggregate_embedding")
        metadata["_mv_stats"] = {
            "source": "roster_entries_column",
            "reason": "mv_join_failed_or_null"
        }

    payload: Dict[str, Any] = {
        "name": metadata.get("name", row.display_name or row.label),
        "display_name": row.display_name or row.label,
        "unique_id": row.label,
        "reference_images": reference_images,
        "aggregate_embedding": aggregate_embedding,  # ✅ Now from MV!
        "metadata": metadata,
        "created_timestamp": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else None,
        "updated_timestamp": row.updated_at.isoformat() if hasattr(row.updated_at, "isoformat") else None,
    }
    return RosterEntry.from_dict(payload)
```

### Step 4: Add Monitoring Query

Create new monitoring script to detect MV usage:

File: `apps/recognition-service/scripts/monitor_mv_usage.py`

```python
"""Monitor materialized view usage in API responses."""
import requests
import json

def check_mv_usage():
    """Check if roster entries are using MV aggregates."""
    resp = requests.get("http://localhost:7860/api/v0/roster")
    entries = resp.json()

    mv_count = 0
    column_count = 0

    for entry in entries:
        metadata = entry.get("metadata", {})
        mv_stats = metadata.get("_mv_stats", {})
        source = mv_stats.get("source", "unknown")

        if source == "materialized_view":
            mv_count += 1
        elif source == "roster_entries_column":
            column_count += 1
            print(f"⚠️  Entry {entry['unique_id']} NOT using MV: {mv_stats.get('reason')}")

    total = len(entries)
    mv_pct = (mv_count / total * 100) if total > 0 else 0

    print(f"\n📊 MV Usage Report:")
    print(f"   Total entries: {total}")
    print(f"   Using MV: {mv_count} ({mv_pct:.1f}%)")
    print(f"   Using column: {column_count}")

    if column_count > 0:
        print(f"\n❌ WARNING: {column_count} entries not using MV!")
        return 1
    else:
        print(f"\n✅ All entries using MV aggregates")
        return 0

if __name__ == "__main__":
    import sys
    sys.exit(check_mv_usage())
```

---

## Issue #3: E2E Tests Permanently Skipped in CI (Gap #7)

**Current Problem:**

- `.github/workflows/nightly-e2e.yml` doesn't start API
- Tests always skip, zero E2E coverage

**Impact:** Progressive learning regressions go undetected until production

**Implementation: Launch Service in Workflow**

### Step 1: Update Workflow to Start Service

File: `.github/workflows/nightly-e2e.yml`

Replace entire file:

```yaml
name: Nightly E2E Tests

on:
  schedule:
    - cron: "0 2 * * *" # 2 AM UTC daily
  workflow_dispatch: # Allow manual trigger
  pull_request:
    paths:
      - "apps/recognition-service/**"
      - ".github/workflows/nightly-e2e.yml"

jobs:
  e2e-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    services:
      postgres:
        image: pgvector/pgvector:pg17
        env:
          POSTGRES_USER: testuser
          POSTGRES_PASSWORD: testpass
          POSTGRES_DB: recognition_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U testuser"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python 3.10
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"
          cache: "pip"

      - name: Install dependencies
        working-directory: apps/recognition-service
        run: |
          pip install --upgrade pip
          pip install -r requirements_main.txt
          pip install -r requirements_local_dev.txt

      - name: Run database migrations
        working-directory: apps/recognition-service
        env:
          DATABASE_URL: postgresql+psycopg://testuser:testpass@localhost:5432/recognition_test
        run: |
          alembic upgrade head

      - name: Start recognition service in background
        working-directory: apps/recognition-service
        env:
          DATABASE_URL: postgresql+psycopg://testuser:testpass@localhost:5432/recognition_test
          PORT: 7860
          LOG_LEVEL: INFO
          USE_FAISS_ACCELERATION: "false"
        run: |
          # Start service in background
          python app.py > service.log 2>&1 &
          SERVICE_PID=$!
          echo "SERVICE_PID=$SERVICE_PID" >> $GITHUB_ENV
          echo "Started service with PID: $SERVICE_PID"

          # Wait for service to be ready (max 60 seconds)
          for i in {1..60}; do
            if curl -f http://localhost:7860/api/v0/health > /dev/null 2>&1; then
              echo "✅ Service ready after $i seconds"
              curl http://localhost:7860/api/v0/health | jq .
              break
            fi
            if [ $i -eq 60 ]; then
              echo "❌ Service failed to start within 60 seconds"
              echo "=== Service logs ==="
              cat service.log
              exit 1
            fi
            sleep 1
          done

      - name: Run E2E tests
        working-directory: apps/recognition-service
        env:
          RUN_E2E: "1"
          RECOGNITION_BASE_URL: http://localhost:7860
          PYTHONUNBUFFERED: "1"
        run: |
          pytest tests/integration/test_progressive_learning_e2e.py \
                 tests/integration/test_wordpress_contract.py \
                 tests/integration/test_etag_caching.py \
                 -v --tb=short --log-cli-level=INFO \
                 --junitxml=pytest-e2e-report.xml

      - name: Print service logs on failure
        if: failure()
        working-directory: apps/recognition-service
        run: |
          echo "=== Service logs ==="
          cat service.log || echo "No service logs found"

      - name: Cleanup service
        if: always()
        run: |
          if [ ! -z "$SERVICE_PID" ]; then
            echo "Stopping service (PID: $SERVICE_PID)"
            kill $SERVICE_PID || true
            # Wait for graceful shutdown
            sleep 2
            # Force kill if still running
            kill -9 $SERVICE_PID 2>/dev/null || true
          fi

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: e2e-test-results
          path: apps/recognition-service/pytest-e2e-report.xml

      - name: Upload service logs
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: service-logs
          path: apps/recognition-service/service.log
```

### Step 2: Ensure Health Endpoint Exists

File: `apps/recognition-service/api/routes/main.py`

Add if missing (check around line 460):

```python
@router.get("/health")
def health_check():
    """Simple health check for CI readiness and load balancer probes."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0"
    }
```

---

## Issue #4: DatabaseMetrics Context Dropped (Gap #1 Regression)

**Current Problem:**

- `context` dict passed positionally, interpreted as `error_type`
- Debugging context silently lost

**Impact:** Harder to debug production errors, missing roster_id/model/tenant context

**Implementation: Enforce Keyword-Only Arguments**

### Step 1: Update `DatabaseMetrics.record_error()` Signature

File: `apps/recognition-service/roster/adapters/postgresql_storage_adapter.py`

Replace lines ~60-95:

```python
def record_error(
    self,
    operation: str,
    error: Optional[BaseException] = None,
    *,  # <-- Force all following args to be keyword-only
    error_type: Optional[str] = None,
    message: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> None:
    """Record error with operation name and optional context.

    The asterisk (*) enforces keyword-only arguments after 'error',
    preventing accidental positional passing of context dict.

    Args:
        operation: Name of the operation that failed (e.g., 'load_roster', 'refresh_mv')
        error: Exception object if available (will extract type and message)
        error_type: Type name of error (keyword-only, alternative to error)
        message: Error message (keyword-only, alternative to error)
        context: Additional debugging context (keyword-only, e.g., {'roster_id': '...', 'model': '...'})

    Examples:
        # Recommended: Pass exception object with context
        try:
            self.load_roster(model)
        except Exception as exc:
            metrics.record_error('load_roster', exc, context={'model': model})

        # Alternative: Pass error details manually
        metrics.record_error(
            'refresh_mv',
            error_type='TimeoutError',
            message='Query exceeded 30s timeout',
            context={'roster_id': id, 'entry_count': count}
        )
    """
    # Support both styles: exception object OR manual error_type+message
    if error is not None:
        error_info = {
            "error_type": type(error).__name__,
            "message": str(error)
        }
    else:
        error_info = {
            "error_type": error_type or "UnknownError",
            "message": message or "No error message provided"
        }

    entry = {
        "operation": operation,
        "timestamp": datetime.utcnow().isoformat(),
        **error_info,
        **(context or {}),  # Safely merge context (now guaranteed to be dict)
    }
    self._errors.append(entry)
    if len(self._errors) > 50:
        self._errors = self._errors[-50:]
```

### Step 2: Audit and Fix All Call Sites

Run search and fix script:

```bash
cd apps/recognition-service

# Find all record_error calls
echo "=== Auditing record_error calls ==="
grep -rn "\.record_error(" roster/adapters/*.py | tee record_error_audit.txt

# Expected fixes:
# OLD: self._metrics.record_error('op', exc, {'roster_id': id})
# NEW: self._metrics.record_error('op', exc, context={'roster_id': id})
```

Common patterns to fix:

```python
# Pattern 1: Context dict passed positionally
# BEFORE:
self._metrics.record_error('refresh_aggregate_view', exc, {'roster_id': roster_id})

# AFTER:
self._metrics.record_error('refresh_aggregate_view', exc, context={'roster_id': roster_id})


# Pattern 2: Error type + message without keywords
# BEFORE:
self._metrics.record_error('load_roster', None, 'ValidationError', 'Invalid model')

# AFTER:
self._metrics.record_error('load_roster', error_type='ValidationError', message='Invalid model')


# Pattern 3: With full context
# BEFORE:
self._metrics.record_error('save_entry', exc, {'unique_id': id, 'model': model, 'ref_count': count})

# AFTER:
self._metrics.record_error('save_entry', exc, context={
    'unique_id': id,
    'model': model,
    'reference_count': count
})
```

### Step 3: Add Unit Test

File: `apps/recognition-service/tests/unit/test_database_metrics.py`

```python
def test_record_error_with_context():
    """Test that context dict is properly captured in error records."""
    metrics = DatabaseMetrics()

    # Test with exception object + context
    try:
        raise ValueError("Test error")
    except ValueError as exc:
        metrics.record_error(
            'test_operation',
            exc,
            context={'roster_id': 'test-123', 'model': 'insightface_w600k'}
        )

    # Verify error recorded with context
    assert len(metrics._errors) == 1
    error_entry = metrics._errors[0]

    assert error_entry['operation'] == 'test_operation'
    assert error_entry['error_type'] == 'ValueError'
    assert error_entry['message'] == 'Test error'
    assert error_entry['roster_id'] == 'test-123'  # Context merged
    assert error_entry['model'] == 'insightface_w600k'  # Context merged

    # Test with manual error_type + message
    metrics.record_error(
        'another_operation',
        error_type='TimeoutError',
        message='Query timeout',
        context={'duration_ms': 30000}
    )

    assert len(metrics._errors) == 2
    error_entry2 = metrics._errors[1]
    assert error_entry2['error_type'] == 'TimeoutError'
    assert error_entry2['duration_ms'] == 30000


def test_record_error_rejects_positional_context():
    """Test that passing context positionally raises TypeError."""
    metrics = DatabaseMetrics()

    # This should raise TypeError because context must be keyword-only
    with pytest.raises(TypeError, match="keyword-only argument"):
        try:
            raise ValueError("Test")
        except ValueError as exc:
            # Trying to pass context as 3rd positional arg (WRONG!)
            metrics.record_error('test_op', exc, {'roster_id': '123'})
```

---

## Issue #5: WordPress Contract Tests Not in CI (Gap #9)

**Already addressed in Issue #3** - workflow now runs `test_wordpress_contract.py`

### Additional: Add Contract Schema Validation Test

File: `apps/recognition-service/tests/integration/test_wordpress_contract.py`

Add new test:

```python
def test_wordpress_confirmation_contract_schema(requests_client):
    """
    Verify WordPress confirmation payload exactly matches documented contract.

    Contract doc: docs/integration/wordpress-backend-contract.md
    """
    # Create test roster
    create_resp = requests_client.post(
        "/api/v0/roster",
        json={
            "entries": [{
                "name": "contract-test-person",
                "embedding": [0.1] * 512,
                "metadata": {"source": "contract_validation"}
            }],
            "model": "insightface_w600k"
        }
    )
    assert create_resp.status_code == 200, f"Failed to create roster: {create_resp.text}"

    # Get roster ID
    list_resp = requests_client.get("/api/v0/roster?model=insightface_w600k")
    assert list_resp.status_code == 200
    roster_list = list_resp.json()
    assert len(roster_list) > 0, "No roster entries found"
    roster_id = roster_list[0]["unique_id"]

    # WordPress confirmation payload (exact format from contract)
    wordpress_payload = {
        "observation_id": "wp_attachment_123_face_0",
        "embedding": [0.15] * 512,
        "confidence": 0.88,
        "quality_tier": "high",
        "attachment_id": 123,
        "bbox": {"x": 100, "y": 150, "width": 200, "height": 200},
        "metadata": {
            "confirmed_by": "user_42",
            "confirmed_at": "2025-11-03T14:30:00Z"
        }
    }

    # Send confirmation
    confirm_resp = requests_client.post(
        f"/api/v0/roster/{roster_id}/augment",
        json=wordpress_payload
    )

    # Validate response matches contract
    assert confirm_resp.status_code == 200, f"Confirmation failed: {confirm_resp.text}"
    data = confirm_resp.json()

    # Required fields per contract
    assert "roster_entry" in data, "Missing roster_entry in response"
    assert "unique_id" in data["roster_entry"], "Missing unique_id in roster_entry"
    assert "aggregate_embedding" in data["roster_entry"], "Missing aggregate_embedding"

    # Validate aggregate is a list of 512 floats
    aggregate = data["roster_entry"]["aggregate_embedding"]
    assert isinstance(aggregate, list), "aggregate_embedding should be list"
    assert len(aggregate) == 512, f"aggregate should have 512 dims, got {len(aggregate)}"
    assert all(isinstance(x, (int, float)) for x in aggregate), "aggregate should contain numbers"

    # Optional progressive learning metadata
    if "progressive_learning" in data:
        pl = data["progressive_learning"]
        assert "quality_tier" in pl, "Missing quality_tier in progressive_learning"
        assert pl["quality_tier"] in ["high", "medium", "low"], f"Invalid quality_tier: {pl['quality_tier']}"

    print(f"✅ Contract validation passed for roster {roster_id}")
```

---

## Implementation Checklist

### Priority 1: Immediate (This Sprint - 3-5 days)

- [ ] **Issue #1.1:** Add `refresh_aggregate_incremental()` to `PostgreSQLStorageAdapter` (~2 hours)
- [ ] **Issue #1.2:** Update `RosterService.add_augmented_embedding()` to use incremental refresh (~30 min)
- [ ] **Issue #1.3:** Add unit test for incremental refresh (~1 hour)
- [ ] **Issue #2.1:** Update `get_roster_entry()` to join MV (~1 hour)
- [ ] **Issue #2.2:** Update `load_roster_entries()` to join MV (~1 hour)
- [ ] **Issue #2.3:** Update `_hydrate_roster_entry()` to track MV source (~30 min)
- [ ] **Issue #2.4:** Create MV usage monitoring script (~30 min)
- [ ] **Issue #4.1:** Add `*` to `record_error()` signature (~15 min)
- [ ] **Issue #4.2:** Audit and fix all `record_error()` call sites (~1 hour)
- [ ] **Issue #4.3:** Add unit tests for metrics context (~30 min)

**Estimated Time: ~9 hours (1-2 sprint days)**

### Priority 2: CI/CD (This Week - 2-3 days)

- [ ] **Issue #3.1:** Update `.github/workflows/nightly-e2e.yml` (~1 hour)
- [ ] **Issue #3.2:** Ensure health endpoint exists (~15 min)
- [ ] **Issue #3.3:** Test workflow manually via workflow_dispatch (~30 min)
- [ ] **Issue #5.1:** Add WordPress contract schema validation test (~1 hour)
- [ ] **Issue #5.2:** Verify all E2E tests pass in CI (~1 hour)

**Estimated Time: ~4 hours (0.5 sprint days)**

### Priority 3: Monitoring & Validation (Next Sprint)

- [ ] Add Prometheus metric for `refresh_aggregate_incremental_total` counter
- [ ] Add Prometheus metric for `refresh_aggregate_incremental_duration_seconds` histogram
- [ ] Add dashboard panel showing incremental vs full refresh ratio
- [ ] Set up alert: `refresh_aggregate_incremental_duration_seconds > 0.5s` for 5+ minutes
- [ ] Run MV usage monitoring script weekly, track % using MV

### Priority 4: Future Optimization (If Needed)

- [ ] Implement background refresh queue if traffic >10 confirmations/sec
- [ ] Add ETag calculation from MV aggregate + updated_at
- [ ] Deprecate `roster_entries.aggregate_embedding` column (v2.0)
- [ ] Drop column entirely (v2.1)

---

## Testing Strategy

### Unit Tests (Fast, No Database)

```bash
pytest tests/unit/test_postgresql_adapter.py::test_refresh_aggregate_incremental -v
pytest tests/unit/test_database_metrics.py::test_record_error_with_context -v
```

### Integration Tests (With PostgreSQL)

```bash
export RUN_E2E=1
pytest tests/integration/test_progressive_learning.py -v
pytest tests/integration/test_wordpress_contract.py::test_wordpress_confirmation_contract_schema -v
```

### E2E Tests (Full Service)

```bash
# Start service in terminal 1
cd apps/recognition-service
python app.py

# Run E2E tests in terminal 2
export RUN_E2E=1
pytest tests/integration/test_progressive_learning_e2e.py -v
pytest tests/integration/test_wordpress_contract.py -v
pytest tests/integration/test_etag_caching.py -v
```

### Performance Validation

```bash
# Before: Full MV refresh (~500ms)
curl -X POST http://localhost:7860/api/v0/roster/{id}/augment -H "Content-Type: application/json" -d '{...}'
# Check logs: "refresh_aggregate_view finished in 523.45ms"

# After: Incremental refresh (~5-10ms)
curl -X POST http://localhost:7860/api/v0/roster/{id}/augment -H "Content-Type: application/json" -d '{...}'
# Check logs: "refresh_aggregate_incremental finished in 7.23ms"

# Improvement: ~70x faster (523ms → 7ms)
```

### MV Usage Monitoring

```bash
# Run monitoring script
cd apps/recognition-service
python scripts/monitor_mv_usage.py

# Expected output:
# 📊 MV Usage Report:
#    Total entries: 42
#    Using MV: 42 (100.0%)
#    Using column: 0
# ✅ All entries using MV aggregates
```

---

## Rollout Plan

### Phase 1: Incremental Refresh (Week 1)

1. Implement `refresh_aggregate_incremental()` method
2. Update `RosterService` to use it
3. Deploy to staging, monitor performance
4. Verify latency drops from 500ms → <50ms per confirmation

### Phase 2: MV Read Integration (Week 1-2)

1. Update read queries to join MV
2. Deploy to staging
3. Run MV usage monitoring script
4. Validate 100% MV usage
5. Check for aggregate drift (compare MV vs column)

### Phase 3: CI/CD Enablement (Week 2)

1. Update nightly E2E workflow
2. Test workflow manually
3. Enable for all PRs touching recognition-service
4. Monitor E2E test stability for 1 week

### Phase 4: Production Deployment (Week 3)

1. Deploy to production with feature flag (incremental refresh OFF)
2. Monitor baseline metrics (current MV refresh duration)
3. Enable incremental refresh for 10% of traffic
4. Gradually increase to 100% over 24 hours
5. Monitor:
   - Confirmation latency (should drop 90%)
   - Error rates (should stay flat)
   - MV usage % (should reach 100%)
   - Aggregate drift (should be zero)

### Rollback Plan

If issues detected:

1. Disable incremental refresh via feature flag
2. Revert to full MV refresh
3. Investigate logs for errors
4. Fix and redeploy to staging

---

## Success Criteria

### Performance

- ✅ Confirmation latency <200ms p95 (down from 500ms+)
- ✅ Incremental refresh <50ms p95
- ✅ No increase in error rates

### Correctness

- ✅ 100% of roster entries using MV aggregates
- ✅ Zero aggregate drift between MV and incremental updates
- ✅ All E2E tests passing in CI

### Observability

- ✅ Prometheus metrics showing refresh method breakdown
- ✅ MV usage tracking in metadata
- ✅ Error context preserved in all metrics

### CI/CD

- ✅ E2E tests running nightly without manual intervention
- ✅ WordPress contract tests validating API schema
- ✅ Test results uploaded to artifacts
