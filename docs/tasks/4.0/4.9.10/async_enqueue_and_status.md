# Async Enqueueing & Granular Status Updates

## Goal

Resolve 500 timeouts when analyzing large batches of media (e.g., 10,000 items) by making the backend enqueueing process asynchronous. Additionally, provide granular status feedback (e.g., "Queueing 500/1000 items", "Processing") to the user via the frontend.

## Constraints

- Greenfield: update baseline schema only (no new migrations).
- No feature flags.
- Keep `/recognition/analyze` contract: 202 response, status values unchanged.
- TDD + scaffolding first (mandatory).

## Architecture Overview

```
┌─────────────────┐     POST /analyze       ┌──────────────────────────┐
│  Frontend       │ ───────────────────────▶│  analyze_media()         │
│  WorkbenchPage  │     202 Accepted        │  - create_scan_job_record│
│                 │ ◀───────────────────────│  - commit immediately    │
└────────┬────────┘                         │  - background_tasks.add  │
         │                                  └────────────┬─────────────┘
         │ poll GET /jobs/{id}                           │
         ▼                                               ▼
┌─────────────────┐                         ┌──────────────────────────┐
│  JobStatus      │                         │  populate_scan_job_items │
│  message:       │ ◀───────────────────────│  - chunked inserts       │
│  "Queueing      │     DB updates          │  - update message        │
│   500/1000"     │                         │  - mark job running      │
└─────────────────┘                         └──────────────────────────┘
```

## Phase 0: Scaffolding (MANDATORY)

- Add method signatures + docstrings with `raise NotImplementedError("TODO: ...")` for new APIs:
  - `ScanQueueService.create_scan_job_record(...)`
  - `ScanQueueService.populate_scan_job_items(...)`
  - `ScanQueueRepository.update_job_message(...)`
  - `JobService.update_job_message(...)` (if using JobService for status updates)
- Add `message: str | None` to `Job` and `JobStatusResponse` signatures (no logic yet).
- Add failing tests that assert message propagation (API response + job status polling).

---

## Proposed Changes

### Backend: `prototype-description-service`

#### [MODIFY] [db/models.py](../../../../apps/prototype-description-service/db/models.py)

Add `message` column to `IdentityScanJob`:

```python
class IdentityScanJob(Base):
    __tablename__ = "identity_scan_jobs"
    # ... existing fields ...
    error_message: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)  # NEW: granular status message
    # ...
```

**Implementation notes:**

- Position after `error_message` for logical grouping
- `error_message` = terminal failure reason, `message` = progress feedback

#### [MODIFY] [db/migrations/versions/001_identity_schema.py](../../../../apps/prototype-description-service/db/migrations/versions/001_identity_schema.py)

Add column to baseline schema (lines ~244-245, after `error_message`):

```python
sa.Column("error_message", sa.Text()),
sa.Column("message", sa.Text()),  # NEW: granular status message
sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
```

#### [MODIFY] [domain/job.py](../../../../apps/prototype-description-service/recognition/domain/job.py)

Add `message` to dataclass:

```python
@dataclass
class Job:
    """Represents a background job with progress tracking."""

    id: str
    type: JobType
    tenant_id: str
    status: JobStatus = JobStatus.PENDING
    progress_completed: int = 0
    progress_total: int = 0
    error_message: str | None = None
    message: str | None = None  # NEW: granular status (e.g., "Queueing 500/1000")
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    finished_at: datetime | None = None
```

#### [MODIFY] [responses.py](../../../../apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py)

Add `message` to `JobStatusResponse`:

```python
class JobStatusResponse(BaseModel):
    """Job status payload."""

    id: str
    type: Literal["analyze", "clustering"]
    status: Literal["pending", "running", "completed", "failed"]
    progress: JobProgressResponse | None
    message: str | None = None  # NEW: granular status message
    started_at: datetime
    finished_at: datetime | None
```

#### [MODIFY] [scan_queue_service.py](../../../../apps/prototype-description-service/recognition/application/scan/scan_queue_service.py)

Split `enqueue_scan_job` into two methods:

```python
class ScanQueueService:
    """Coordinates scan queue persistence and processing."""

    ENQUEUE_CHUNK_SIZE = 500  # Items per batch insert

    async def create_scan_job_record(
        self,
        *,
        tenant_id: uuid.UUID,
        total: int,
        created_by_user_id: int | None = None,
    ) -> uuid.UUID:
        """Create a scan job record with initial message.

        This is the synchronous portion - returns immediately so the
        HTTP request can respond with 202.

        Args:
            tenant_id: Tenant UUID.
            total: Total number of items to be queued.
            created_by_user_id: Optional WP user id for audit.

        Returns:
            The new job's UUID.
        """
        job_id = await self._repository.create_job_with_message(
            tenant_id=tenant_id,
            media_ids=[],  # Will be populated async
            total=total,
            message=f"Queueing 0/{total} items",
            created_by_user_id=created_by_user_id,
        )
        return job_id

    async def populate_scan_job_items(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        media_items: Sequence[tuple[int, str]],
    ) -> int:
        """Populate scan job items in chunks, updating message after each.

        This runs as a background task after the HTTP response is sent.

        Args:
            job_id: Parent scan job id.
            tenant_id: Tenant id (RLS scope).
            media_items: Sequence of (media_id, media_url).

        Returns:
            Total number of items enqueued.
        """
        total = len(media_items)
        queued = 0
        media_ids: list[int] = []

        for i in range(0, total, self.ENQUEUE_CHUNK_SIZE):
            chunk = media_items[i : i + self.ENQUEUE_CHUNK_SIZE]
            await self._repository.enqueue_items(
                job_id=job_id,
                tenant_id=tenant_id,
                items=chunk,
            )
            queued += len(chunk)
            media_ids.extend(mid for mid, _ in chunk)

            # Update message after each chunk
            await self._repository.update_job_message(
                job_id=job_id,
                message=f"Queueing {queued}/{total} items",
            )

        # Update media_ids array and mark ready for processing
        await self._repository.finalize_job_queue(
            job_id=job_id,
            media_ids=media_ids,
            message=f"Queued {total} items",
        )
        return queued

    # Keep existing enqueue_scan_job for backward compatibility
    async def enqueue_scan_job(
        self,
        *,
        tenant_id: uuid.UUID,
        media_items: Sequence[tuple[int, str]],
        created_by_user_id: int | None = None,
    ) -> EnqueueScanResult:
        """Create a scan job and enqueue all items (legacy synchronous API)."""
        # ... existing implementation unchanged ...
```

#### [MODIFY] [queue_repository.py (Protocol)](../../../../apps/prototype-description-service/recognition/application/scan/queue_repository.py)

Add new protocol methods:

```python
class ScanQueueRepository(Protocol):
    # ... existing methods ...

    async def create_job_with_message(
        self,
        *,
        tenant_id: uuid.UUID,
        media_ids: Sequence[int],
        total: int,
        message: str,
        created_by_user_id: int | None = None,
    ) -> uuid.UUID:
        """Create a job with initial message."""

    async def update_job_message(
        self,
        *,
        job_id: uuid.UUID,
        message: str,
    ) -> None:
        """Update the job's message field."""

    async def finalize_job_queue(
        self,
        *,
        job_id: uuid.UUID,
        media_ids: Sequence[int],
        message: str,
    ) -> None:
        """Update media_ids array and message after all items are queued."""
```

#### [MODIFY] [scan_queue_repository.py (SQLA impl)](../../../../apps/prototype-description-service/recognition/infrastructure/repositories/scan_queue_repository.py)

Implement new methods:

```python
class SqlAlchemyScanQueueRepository(ScanQueueRepository):
    # ... existing methods ...

    async def create_job_with_message(
        self,
        *,
        tenant_id: uuid.UUID,
        media_ids: Sequence[int],
        total: int,
        message: str,
        created_by_user_id: int | None = None,
    ) -> uuid.UUID:
        """Create a job record with initial message."""
        job = IdentityScanJob(
            tenant_id=tenant_id,
            status="pending",
            media_ids=list(media_ids),
            total_media=total,
            processed_media=0,
            identities_detected=0,
            message=message,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(job)
        await self._session.flush()
        return job.id

    async def update_job_message(
        self,
        *,
        job_id: uuid.UUID,
        message: str,
    ) -> None:
        """Update the job's message field."""
        await self._session.execute(
            update(IdentityScanJob)
            .where(IdentityScanJob.id == job_id)
            .values(message=message)
        )

    async def finalize_job_queue(
        self,
        *,
        job_id: uuid.UUID,
        media_ids: Sequence[int],
        message: str,
    ) -> None:
        """Update media_ids and message after queuing completes."""
        await self._session.execute(
            update(IdentityScanJob)
            .where(IdentityScanJob.id == job_id)
            .values(media_ids=list(media_ids), message=message)
        )
```

#### [MODIFY] [analyze.py](../../../../apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py)

Update `analyze_media` to use async enqueueing:

```python
@router.post("/analyze", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_media(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    scan_service_builder=Depends(get_scan_service_builder),
    scan_queue=Depends(get_scan_queue_service_optional),
) -> JobStatusResponse:
    """Scan media for face identities. Returns a job ID for polling."""
    # ... existing validation logic ...

    # NEW: Create job record synchronously (fast)
    total = len(media_items)
    job_id = await scan_queue.create_scan_job_record(
        tenant_id=tenant_uuid,
        total=total,
        created_by_user_id=getattr(auth, "user_id", None),
    )

    # Commit before background task so polling can find the job
    if session is not None:
        await session.commit()

    # NEW: Chain background tasks to order execution and conserve connections
    async def _chain_populate_and_process():
        """Chain populate and process to ensure order and conserve connections."""
        await _populate_scan_job_items_async(
            tenant_id=str(request.tenant_id),
            job_id=str(job_id),
            media_items=media_items,
            scan_queue=scan_queue if not isinstance(scan_queue, ScanQueueService) else None,
            session_factory=session_factory,
        )
        if os.environ.get("RECOGNITION_ASYNC_ANALYZE_INLINE", "0") == "1":
            await _process_scan_job_inline(
                tenant_id=str(request.tenant_id),
                job_id=str(job_id),
                media_ids=media_ids,
                media_sources=media_sources,
                session_factory=session_factory,
            )

    background_tasks.add_task(_chain_populate_and_process)

    # Return immediately with initial message
    progress = JobProgressResponse(completed=0, total=total)
    return JobStatusResponse(
        id=str(job_id),
        type=JobType.ANALYZE.value,
        status="pending",
        progress=progress,
        message=f"Queueing 0/{total} items",  # NEW
        started_at=datetime.now(tz=UTC),
        finished_at=None,
    )
```

**Note:** `_process_scan_job_inline` has been refactored to release the DB connection during inference:

```python
async def _process_scan_job_inline(...):
    # 0. Load shared adapter (cached) to avoid re-initializing heavy models
    adapter = await get_shared_insightface_adapter()
    detector = InsightFaceFaceDetector(adapter)
    generator = InsightFaceEmbeddingGenerator(adapter)

    # 1. Mark Running (Short transaction)
    async with session_factory() as session:
        scan_service = ScanService(session=session)
        await scan_service.mark_job_running(uuid.UUID(str(job_id)))

    # 2. Inference (No DB connection)
    detections = await detector.detect(sources_list)
    # ... handle embeddings ...

    # 3. Save Results (Short transaction)
    async with session_factory() as session:
        scan_service = ScanService(session, detector, generator, embedder)
        await scan_service.save_job_results(...)
```

#### [MODIFY] [job_repository.py](../../../../apps/prototype-description-service/recognition/infrastructure/repositories/job_repository.py)

Map `message` field when reading scan jobs:

```python
async def get(self, job_id: str) -> Job | None:
    # ... existing code ...
    scan = await self._session.get(IdentityScanJob, job_uuid)
    if scan:
        return Job(
            id=str(scan.id),
            type=JobType.ANALYZE,
            tenant_id="",
            status=JobStatus(scan.status),
            progress_completed=scan.processed_media or 0,
            progress_total=scan.total_media or 0,
            error_message=scan.error_message,
            message=scan.message,  # NEW
            started_at=scan.started_at or datetime.now(tz=UTC),
            finished_at=scan.completed_at,
        )
```

#### [MODIFY] [analyze.py `_job_to_response`](../../../../apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py)

Include `message` in response mapping:

```python
def _job_to_response(job: Job) -> JobStatusResponse:
    """Convert domain Job to API response."""
    return JobStatusResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        progress=JobProgressResponse(
            completed=job.progress_completed,
            total=job.progress_total,
        ) if job.progress_total > 0 else None,
        message=job.message,  # NEW
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
```

---

### Frontend: `prototype-wp-alt-context`

#### [MODIFY] [js/admin/api/recognition/types/scan.ts](../../../../apps/prototype-wp-alt-context/js/admin/api/recognition/types/scan.ts)

Add `message` to response types:

```typescript
export interface AnalyzeResponse {
  id: string;
  type: "analyze" | "clustering";
  status: "pending" | "running" | "completed" | "failed";
  progress: JobProgress | null;
  message?: string | null; // NEW: granular status message
  started_at: string;
  finished_at: string | null;
}
```

#### [MODIFY] [js/admin/pages/WorkbenchPage.tsx](../../../../apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx)

Update `scanStatusText` to prefer backend message:

```typescript
const scanStatusText = useMemo(() => {
  if (clusterMutation.isPending) {
    return __("Clustering faces…", "alt-context");
  }

  // NEW: Prefer backend message if available
  const backendMessage = scanStatusQuery.data?.message;
  if (backendMessage && scanStatusQuery.data?.status !== "completed") {
    return backendMessage;
  }

  if (activeJobIds.length > 0) {
    const completed = multiScanStatus.filter(
      (q) => q.data?.status === "completed"
    ).length;
    const failed = multiScanStatus.filter(
      (q) => q.data?.status === "failed"
    ).length;
    const total = activeJobIds.length;

    if (completed + failed === total) {
      return "completed";
    }
    return sprintf(
      __("Processing %d/%d batches…", "alt-context"),
      completed + failed,
      total
    );
  }
  return (
    scanStatusQuery.data?.status ??
    (scanMutation.isPending ? __("Starting scan…", "alt-context") : undefined)
  );
}, [
  activeJobIds,
  multiScanStatus,
  scanStatusQuery.data,
  scanMutation.isPending,
  clusterMutation.isPending,
]);
```

---

## Verification Plan

### Automated Tests

#### Backend Unit Tests

**`test_scan_queue_service.py`** (new file):

```python
@pytest.mark.asyncio
async def test_create_scan_job_record_sets_initial_message():
    """create_scan_job_record should set message to 'Queueing 0/N'."""
    service = ScanQueueService(fake_repository)

    job_id = await service.create_scan_job_record(
        tenant_id=uuid.uuid4(),
        total=1000,
    )

    assert fake_repository.last_message == "Queueing 0/1000 items"


@pytest.mark.asyncio
async def test_populate_scan_job_items_updates_message_per_chunk():
    """populate_scan_job_items should update message after each chunk."""
    service = ScanQueueService(fake_repository)
    service.ENQUEUE_CHUNK_SIZE = 100
    items = [(i, f"http://example.com/{i}.jpg") for i in range(250)]

    await service.populate_scan_job_items(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        media_items=items,
    )

    # Should have updated 3 times: 100, 200, 250
    assert fake_repository.message_history == [
        "Queueing 100/250 items",
        "Queueing 200/250 items",
        "Queueing 250/250 items",
        "Queued 250 items",  # finalize
    ]
```

#### Backend API Tests

**`test_api_analyze.py`** additions:

```python
def test_analyze_returns_message_field(api_client, tenant_id):
    """POST /analyze response should include message field."""
    resp = api_client.post(
        "/recognition/analyze",
        json={"media_ids": ["1", "2", "3"], "tenant_id": tenant_id},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert "message" in body
    assert "Queueing" in body["message"]


def test_get_job_status_returns_message(api_client, tenant_id, fake_scan_queue_service):
    """GET /jobs/{id} should return message field."""
    # Create job with message
    # ... setup ...

    resp = api_client.get(f"/recognition/jobs/{job_id}")

    assert resp.status_code == 200
    assert "message" in resp.json()
```

### Manual Verification

1. **Large Batch Test**: Trigger a scan for 1000+ items
2. **Timeout Verification**: Confirm initial request completes in < 500ms
3. **Status Feedback**: Observe WorkbenchPage showing:
   - "Queueing 0/1000 items" → "Queueing 500/1000 items" → "Queued 1000 items"
   - Then "Processing..." when worker picks up items

---

## Performance Expectations

| Batch Size | Current (sync) | After (async) |
| ---------- | -------------- | ------------- |
| 100        | ~200ms         | ~50ms         |
| 1,000      | ~60s (timeout) | ~50ms         |

Background population runs at ~500 items/100ms, so a 10,000 item batch queues in ~2s total (but HTTP returns immediately).
