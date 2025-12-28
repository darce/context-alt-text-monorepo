# Latency & Stability Analysis: Root Cause & Solution Proposal

**Date**: 2025-12-25
**Scope**: Scan Worker Latency, DB Stability, and Performance
**Related Issues**: `ISSUES_ANALYSIS.md`
**Reference Literature**: *Latency: Reduce delay in software systems* (Pekka Enberg, 2025)

---

## 1. Executive Summary

The system is currently suffering from **extreme latency** (13s+ overhead per batch) and **instability** (worker crashes plus DB pool exhaustion). These are not subtle optimization issues but fundamental architectural flaws in the worker loop and resource management.

Applying principles from Enberg's *Latency*, we have identified three critical root causes:
1.  **Redundant Work (Ch. 7)**: The heavy 512D face recognition model is reloaded from disk/GPU for *every* batch.
2.  **Blocking I/O (Ch. 10)**: Sequential processing exposes full network round-trip latency for every image.
3.  **Resource Leaks (Ch. 10)**: Worker restarts fail to release database resources, leading to pool exhaustion.

## 2. Root Cause Analysis

### 2.1. The "Model Reloading" Loop (Primary Latency Source)

**Observation**: `scan_worker.log` shows the `InsightFace model buffalo_l` being loaded repeatedly, taking ~13-18 seconds each time.

**Code Evidence**:
In `scan_worker.py`, `_build_scan_service` instantiates a **new** `InsightFaceAdapter` inside the processing loop. This violates the principle of **Eliminating Work** (Enberg, Ch. 7): *"The fastest code to execute is no code... eliminating work is about not introducing redundant work."*

**Impact**:
- **Fixed Overhead**: ~15s per batch of 10 items.
- **Throughput Cap**: Maximum ~0.6 items/second regardless of hardware.

### 2.2. Sequential Blocking Processing

**Observation**: `ScanWorker._process_claimed_items` awaits each item end-to-end, so I/O and inference are serialized within a batch.

**Code Evidence**:
`scan_worker.py` iterates `for item in claimed:` and awaits processing.
According to **Asynchronous Processing** (Enberg, Ch. 10), this approach fails to *hide latency*. We are paying the full cost of network RTT (Round Trip Time) for every image item.

**Impact**:
- **Network Bound**: CPU/GPU sits idle during download.
- **High "Wait" (W)**: Increases residency time in the system (Little's Law).

### 2.3. DB Connection Exhaustion

**Observation**: `recognition.log` shows `sqlalchemy.exc.TimeoutError: QueuePool limit reached`.

**Code Evidence**:
The `ScanWorker` creates an `AsyncEngine` but does not guarantee its disposal on crash/restart.
Enberg (Ch. 10) emphasizes **Resource Management** as a critical component of asynchronous systems. Leaking connections prevents the system from recovering (self-healing), turning transient errors into persistent outages.

### 2.4. Validation Notes (Logs + Code)

- **Model reload confirmed**: `scan_worker.log` shows repeated `Loading InsightFace model buffalo_l` events within the same worker run (e.g., 16:21:02, 16:21:13, 16:21:35).
- **Sequential processing confirmed**: `ScanWorker._process_claimed_items` awaits each `process_media_item` inside a `for` loop, so network + inference is serialized per item.
- **Pool exhaustion confirmed but not isolated to worker**: `recognition.log` includes `QueuePool limit ... connection timed out` errors. The worker still risks contributing because `_main` recreates a new `AsyncEngine` after crashes without explicit disposal.
- **Additional stability signal**: `scan_worker.log` shows session rollback errors (`UPDATE ... expected to update 1 row(s); 0 were matched`), indicating transactional state can carry across retries.

---

## 3. Proposed Solutions

### 3.1. Singleton Model Adapter (Eliminate Redundant Work)

**Concept**: Initialize heavy resources *once* at startup.

**Implementation**:
- Move `InsightFaceAdapter` initialization to `ScanWorker.__init__` or `_main`.
- Pass the adapter instance to the service factory.

### 3.2. Concurrent Batch Processing (Hide Latency)

**Concept**: Use **I/O Multiplexing** to overlap network operations.

**Implementation**:
- Use `asyncio.gather` to fetch and process images in parallel.
- This effectively implements **Request Batching** (Enberg, Ch. 10.2.2) for the network layer, hiding individual RTTs.

```python
# Pseudo-code
tasks = [scan_service.process_media_item(item) for item in claimed]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

### 3.3. Robust Resource Management (Stability)

**Concept**: Explicit lifecycle management for external resources.

**Implementation**:
- Implement `AsyncContextManager` pattern for `ScanWorker`.
- Ensure `engine.dispose()` is called in a `finally` block.
- Add **Exponential Backoff** (Enberg, Ch. 10) for retries instead of a fixed 5s delay, to prevent thundering herd effects on a recovering DB.

### 3.4. Future: Vectorized Inference (Request Batching)

**Concept**: Batch compute operations to maximize GPU utilization.

**Recommendation**:
- Future refactor to pass `List[Image]` to `InsightFaceAdapter`.
- Leverage ONNX Runtime's batch execution capabilities to process 10 inputs in a single forward pass, further reducing compute latency (Amdahl's Law).

---

## 4. Implementation Details & Code Patterns

### 4.1. Cache the InsightFace Adapter Once Per Worker

**Why**: `_build_scan_service()` is called on every batch inside `run_forever`, so `InsightFaceAdapter()` reloads weights each time.

**Pattern** (share adapter + detector/generator across batches, but keep session per batch):

```python
class ScanWorker:
    def __init__(self, config: ScanWorkerConfig) -> None:
        ...
        self._adapter = InsightFaceAdapter()
        self._detector = InsightFaceFaceDetector(self._adapter)
        self._generator = InsightFaceEmbeddingGenerator(self._adapter)

    def _scan_service(self, session: AsyncSession) -> ScanService:
        return ScanService(session=session, detector=self._detector, generator=self._generator)
```

### 4.2. Concurrency With Per-Item Sessions (AsyncSession is Not Concurrent-Safe)

**Why**: `AsyncSession` must not be shared across concurrent tasks. Use a new session per item or a work-queue with a bounded semaphore.

**Pattern** (bounded concurrency + per-item session):

```python
async def _process_claimed_items(self, claimed: list[ScanQueueItem]) -> None:
    sem = asyncio.Semaphore(min(self._config.max_concurrency, len(claimed)))

    async def _process_item(item: ScanQueueItem) -> None:
        request_id = uuid.uuid4()
        async with sem:
            async with self._session_factory() as session:
                await enable_rls_bypass(session)
                repo = SqlAlchemyScanQueueRepository(session)
                scan_service = self._build_scan_service(session)
                logger.info("[worker] START scan_item request_id=%s item_id=%s", request_id, item.id)
                try:
                    identities = await scan_service.process_media_item(
                        tenant_id=str(item.tenant_id),
                        media_id=item.media_id,
                        media_url=item.media_url,
                    )
                    await repo.mark_item_completed(
                        item_id=item.id,
                        completed_at=datetime.now(tz=UTC),
                        identities_detected=identities,
                    )
                except Exception as exc:
                    await self._handle_item_failure(
                        repo=repo,
                        item=item,
                        now=datetime.now(tz=UTC),
                        error_message=str(exc),
                    )
                await session.commit()

    await asyncio.gather(*[_process_item(item) for item in claimed], return_exceptions=True)
```

### 4.3. Reduce HTTP Overhead in the Detector

**Why**: `InsightFaceFaceDetector.detect` creates a new `httpx.AsyncClient` per request.

**Pattern** (reuse a client per batch or per worker):

```python
class InsightFaceFaceDetector(FaceDetectorProtocol):
    def __init__(self, adapter: InsightFaceAdapter, client: httpx.AsyncClient | None = None) -> None:
        self._adapter = adapter
        self._client = client

    async def _fetch_image(self, url: str) -> bytes | None:
        response = await self._client.get(url)
        response.raise_for_status()
        return response.content
```

### 4.4. Explicit Engine Disposal + Backoff on Crash

**Why**: `_main` recreates a new `AsyncEngine` on each crash without disposing the old one.

**Pattern** (context manager + exponential backoff):

```python
class ScanWorker:
    async def __aenter__(self) -> "ScanWorker":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
        await self._engine.dispose()

backoff = 2.0
while True:
    try:
        async with ScanWorker(...) as worker:
            await worker.run_forever()
    except Exception:
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60.0)
```

---

## 5. Implementation Steps

1.  **Refactor `ScanWorker`**:
    - Implement `__aenter__` and `__aexit__` for resource cleanup.
    - Instantiate `InsightFaceAdapter` once.
2.  **Refactor Loop**:
    - Update `_process_claimed_items` to use `asyncio.gather`.
    - Add `Request ID` tracing (Enberg, Ch. 10) to logs for better observability.
3.  **Verify**:
    - Confirm "Loading InsightFace" appears only once.
    - Confirm parallel timestamps.
    - Verify clean exit on interrupt.

---

## 6. Implementation Checklist

### Phase 1: Singleton Model Adapter
- [x] Refactor `ScanWorker` to initialize `InsightFaceAdapter` in `__init__` (once per worker) <!-- id: 1 -->
- [x] Pass shared adapter instance to `ScanService` factory <!-- id: 2 -->
- [ ] Verify `InsightFace model loaded` log appears only once per worker lifetime <!-- id: 3 -->

### Phase 2: Concurrent Batch Processing
- [x] Implement `asyncio.Semaphore` for bounded concurrency (e.g., limit 5-10) <!-- id: 4 -->
- [x] Refactor `_process_claimed_items` to use `asyncio.gather` for parallel processing <!-- id: 5 -->
- [x] Ensure `AsyncSession` is scoped per-task (not shared across concurrent tasks) <!-- id: 6 -->
- [x] Add Request ID logging to trace interleaved execution <!-- id: 7 -->

### Phase 3: Resource Management & Stability
- [x] Implement `__aenter__` and `__aexit__` in `ScanWorker` for explicit `engine.dispose()` <!-- id: 8 -->
- [x] Add exponential backoff retry loop in `run_worker` entry point <!-- id: 9 -->
- [ ] Verify worker recovers correctly after DB connectivity loss <!-- id: 10 -->

### Phase 4: HTTP Optimization
- [x] Refactor `InsightFaceFaceDetector` to accept a shared `httpx.AsyncClient` <!-- id: 11 -->
- [x] Pass shared client from `ScanWorker` through to detector <!-- id: 12 -->
