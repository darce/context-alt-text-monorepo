# Async Split Implementation Plan

**Goal:** Eliminate WP proxy timeouts on large split operations by adding async mode

**Problem:** Large splits (50+ identities) can timeout via WP proxy (60s limit), leaving UI unresponsive

**Solution:** Add optional async mode to split endpoint, return job_id for status polling

---

## Phase 0: Scaffolding (MANDATORY)

### 0.1 Request/Response Contracts

**File:** `recognition/interface_adapters/http/schemas/requests.py`

Update `SplitClusterRequest`:

```python
class SplitClusterRequest(BaseModel):
    """Request to split a cluster using hierarchical clustering.
    
    Args:
        tenant_id: The tenant that owns the cluster.
        n_clusters: Number of clusters to split into (0=auto, 2+=fixed).
        anchor_identity_id: Identity ID used to keep labels with the selected person.
        split_mode: Optional split mode hint (ex: "anchor", "media").
        mode: Execution mode - "sync" returns immediately, "async" queues job.
    """
    
    tenant_id: str
    n_clusters: int = Field(default=0, ge=0, description="0=auto-detect, 2+=fixed count")
    anchor_identity_id: str | None = None
    split_mode: str | None = Field(default=None, description="Optional split mode hint")
    mode: Literal["sync", "async"] = Field(default="sync", description="Execution mode")
    
    # ... existing validators ...
```

**File:** `recognition/interface_adapters/http/schemas/responses.py`

Add async response variant:

```python
class AsyncSplitClusterResponse(BaseModel):
    """Response when split is queued for async execution.
    
    Returns:
        job_id: UUID of the queued clustering job.
        status: Initial job status ("pending").
        message: User-facing message.
    """
    
    job_id: str
    status: str = "pending"
    message: str = "Split operation queued"
```

### 0.2 Job Payload Extension

**File:** `recognition/domain/job.py`

Add split-specific payload type:

```python
class SplitJobPayload(BaseModel):
    """Payload for async split jobs.
    
    Attributes:
        cluster_id: Target cluster to split.
        n_clusters: Desired cluster count.
        anchor_identity_id: Optional anchor for label retention.
        split_mode: Optional mode hint.
    """
    
    cluster_id: str
    n_clusters: int = 0
    anchor_identity_id: str | None = None
    split_mode: str | None = None
```

---

## Phase 1: Endpoint Changes

### 1.1 Split Endpoint Update

**File:** `recognition/interface_adapters/http/routers/clusters.py`

Modify `split_cluster` endpoint to support async mode:

```python
@router.post(
    "/clusters/{cluster_id}/split",
    response_model=SplitClusterResponse | AsyncSplitClusterResponse,
    status_code=200,  # 200 for sync, 202 for async
)
async def split_cluster(
    cluster_id: str,
    request: SplitClusterRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -\u003e SplitClusterResponse | AsyncSplitClusterResponse:
    """Split a cluster using hierarchical clustering.
    
    If mode="async", returns 202 Accepted with job_id for polling.
    If mode="sync", performs split immediately and returns 200 OK.
    """
    validate_entity_id(cluster_id, field_name="cluster_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    
    if request.mode == "async":
        # Queue job and return immediately
        job_service = await build_job_service(session=session)
        payload = SplitJobPayload(
            cluster_id=cluster_id,
            n_clusters=request.n_clusters,
            anchor_identity_id=request.anchor_identity_id,
            split_mode=request.split_mode,
        )
        job = await job_service.queue_clustering(
            tenant_id=request.tenant_id,
            job_type="split",
            payload=payload.model_dump(),
        )
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail=AsyncSplitClusterResponse(
                job_id=job.id,
                status=job.status,
                message=f"Split operation queued for cluster {cluster_id[:8]}",
            ).model_dump(),
        )
    
    # Sync mode - existing logic
    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    new_ids, counts = await cluster_service.split_cluster(
        cluster_id,
        n_clusters=request.n_clusters,
        anchor_identity_id=request.anchor_identity_id,
        split_mode=request.split_mode,
    )
    
    return SplitClusterResponse(
        new_cluster_ids=new_ids,
        moved_counts=counts,
        new_cluster_id=new_ids[0] if new_ids else None,
        moved_count=counts[0] if counts else 0,
    )
```

### 1.2 Job Type Registration

**File:** `recognition/domain/job.py`

Add split to job types:

```python
class JobType(str, Enum):
    """Supported job categories."""
    
    ANALYZE = "analyze"
    CLUSTERING = "clustering"
    CURATION = "curation"
    SPLIT = "split"  # NEW
```

---

## Phase 2: Worker Handler

### 2.1 Split Job Handler

**File:** `recognition/worker/scan_worker.py`

Add handler for split jobs:

```python
async def _handle_split_job(self, job: ClusteringJob) -\u003e None:
    """Execute a split job.
    
    Args:
        job: Job with split payload.
        
    Raises:
        ValueError: If payload is invalid.
    """
    payload = job.payload
    cluster_id = payload.get("cluster_id")
    if not cluster_id:
        raise ValueError("Split job missing cluster_id")
    
    n_clusters = payload.get("n_clusters", 0)
    anchor_identity_id = payload.get("anchor_identity_id")
    split_mode = payload.get("split_mode")
    
    logger.info(
        "[worker] START split_job job_id=%s cluster_id=%s n_clusters=%d tenant_id=%s",
        job.id,
        cluster_id,
        n_clusters,
        job.tenant_id,
    )
    
    async with self._db_factory.create_session() as session:
        cluster_service = await build_cluster_service(
            session=session,
            tenant_id=str(job.tenant_id),
        )
        new_ids, counts = await cluster_service.split_cluster(
            cluster_id=cluster_id,
            n_clusters=n_clusters,
            anchor_identity_id=anchor_identity_id,
            split_mode=split_mode,
        )
    
    await self._job_repository.update_progress(
        job.id,
        progress=1.0,
        message=f"Split complete: created {len(new_ids)} clusters",
    )
    
    logger.info(
        "[worker] COMPLETE split_job job_id=%s new_clusters=%s moved_counts=%s",
        job.id,
        new_ids,
        counts,
    )

# Update dispatch logic
async def _execute_job(self, job: ClusteringJob) -\u003e None:
    if job.job_type == "split":
        await self._handle_split_job(job)
    elif job.job_type == "curation":
        await self._handle_curation_job(job)
    # ... existing handlers ...
```

---

## Phase 3: Frontend Updates

### 3.1 TypeScript Types

**File:** `apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts`

Add async response type:

```typescript
export interface SplitClusterRequest {
  nClusters?: number;
  anchorIdentityId?: string;
  splitMode?: 'auto' | 'forced';
  mode?: 'sync' | 'async';  // NEW
}

export interface AsyncSplitClusterResponse {
  job_id: string;
  status: string;
  message: string;
}
```

### 3.2 API Client

**File:** `apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApi.ts`

Update `splitCluster` to handle async responses:

```typescript
export const splitCluster = async (
  clusterId: string,
  request: SplitClusterRequest
): Promise\u003cSplitClusterResponse | AsyncSplitClusterResponse\u003e =\u003e {
  const response = await apiClient.post(
    `/clusters/${clusterId}/split`,
    request
  );
  
  // Handle 202 Accepted for async mode
  if (response.status === 202) {
    return response.data as AsyncSplitClusterResponse;
  }
  
  return response.data as SplitClusterResponse;
};
```

### 3.3 UI Component

**File:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterMutations.ts`

Add async mode support:

```typescript
const splitCluster = useMutation({
  mutationFn: async ({ clusterId, request }: SplitParams) =\u003e {
    const result = await clusterApi.splitCluster(clusterId, {
      ...request,
      mode: identityCount \u003e 50 ? 'async' : 'sync',  // Auto-async for large clusters
    });
    
    // If async, poll for completion
    if ('job_id' in result) {
      return pollJobStatus(result.job_id);
    }
    
    return result;
  },
  onSuccess: () =\u003e {
    queryClient.invalidateQueries(['clusters']);
  },
});
```

---

## Verification Plan

### Automated Tests

#### Unit Tests

**File:** `recognition/tests/unit/test_async_split.py` (NEW)

```python
import pytest
from recognition.interface_adapters.http.schemas.requests import SplitClusterRequest
from recognition.interface_adapters.http.schemas.responses import AsyncSplitClusterResponse

def test_split_request_validates_mode():
    \"\"\"Async mode must be either 'sync' or 'async'.\"\"\"
    valid = SplitClusterRequest(
        tenant_id="tenant-123",
        mode="async",
    )
    assert valid.mode == "async"
    
    with pytest.raises(ValidationError):
        SplitClusterRequest(tenant_id="tenant-123", mode="invalid")
```

**Run:** `cd apps/prototype-description-service && pytest recognition/tests/unit/test_async_split.py -v`

#### Integration Tests

**File:** `recognition/tests/integration/test_async_split_endpoint.py` (NEW)

```python
@pytest.mark.integration
async def test_async_split_returns_202_with_job_id(test_client, db_session):
    \"\"\"Async split should return 202 Accepted with job_id.\"\"\"
    # Setup: create cluster with 60 identities
    cluster = await create_test_cluster(db_session, identity_count=60)
    
    response = await test_client.post(
        f"/clusters/{cluster.id}/split",
        json={
            "tenant_id": str(cluster.tenant_id),
            "n_clusters": 2,
            "mode": "async",
        },
    )
    
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "pending"
    
    # Verify job was queued
    job = await get_job_by_id(db_session, data["job_id"])
    assert job.job_type == "split"
    assert job.payload["cluster_id"] == cluster.id
```

**Run:** `cd apps/prototype-description-service && pytest recognition/tests/integration/test_async_split_endpoint.py -v`

#### Worker Tests

**File:** `recognition/tests/integration/test_split_worker.py` (NEW)

```python
@pytest.mark.integration
async def test_worker_executes_split_job(db_session, worker):
    \"\"\"Worker should execute split jobs and update status.\"\"\"
    cluster = await create_test_cluster(db_session, identity_count=20)
    job = await queue_split_job(
        db_session,
        cluster_id=cluster.id,
        tenant_id=cluster.tenant_id,
    )
    
    # Execute job
    await worker.process_next_job()
    
    # Verify completion
    job = await get_job_by_id(db_session, job.id)
    assert job.status == "completed"
    assert job.progress == 1.0
    
    #Verify split occurred
    clusters = await list_clusters(db_session, cluster.tenant_id)
    assert len(clusters) \u003e 1  # Original + new clusters
```

**Run:** `cd apps/prototype-description-service && pytest recognition/tests/integration/test_split_worker.py -v`

### Manual Verification

**Prerequisites:**
1. Start local services: `./scripts/start_prototype_local.sh`
2. Create test cluster with 60+ identities in Workbench UI

**Test Steps:**
1. Navigate to Workbench \u003e Identity Clusters
2. Select cluster with 60+ identities
3. Click "Split Cluster" button
4. Verify UI shows loading state with job progress
5. Wait for completion (should \u003c 60s)
6. Verify split succeeded (new clusters appear)
7. Check browser network tab: `/split` endpoint returned 202
8. Verify no timeout errors in WP PHP logs

**Expected Outcome:** Split completes without timeout, UI updates after job finishes

---

## Implementation Checklist

- [x] Phase 0: Scaffold request/response contracts
- [x] Phase 0: Scaffold job payload types
- [x] Phase 1: Update split endpoint with async branch
- [x] Phase 1: Register "split" job type
- [x] Phase 2: Implement worker split handler
- [x] Phase 2: Update worker dispatch logic
- [x] Phase 3: Update TypeScript types
- [x] Phase 3: Update API client
- [x] Phase 3: Add UI polling logic
- [x] Write unit tests for request validation
- [x] Write integration test for async endpoint
- [x] Write integration test for worker execution
- [ ] Manual testing: split 60+ identity cluster
- [x] Update API documentation

---

## Acceptance Criteria

✅ Async split requests return 202 with job_id  
✅ Sync split requests still work (backward compatible)  
✅ Worker processes split jobs successfully  
✅ UI polls job status and updates on completion  
✅ No timeouts on large splits (60+ identities)  
✅ All tests pass
