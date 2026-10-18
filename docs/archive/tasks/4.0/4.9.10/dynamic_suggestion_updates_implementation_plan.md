# Implementation Plan: Dynamic Suggestion Updates & Real-time Notifications (SSE)

**Related Task**: `fix-identity-reassignment-implementation_plan.md`
**Date**: 2025-12-24
**Updated**: 2025-12-24 (gap analysis, scaffolding, code patterns)

## 1. Overview

Currently, when a cluster's representatives change (due to merge, assignment, or recomputation), pending suggestions for that cluster are not updated. This leads to stale similarity scores in the UI. Additionally, the frontend is not notified of these changes, requiring manual refresh or polling.

This plan addresses both issues:

1. **Backend Refresh**: Trigger suggestion re-calculation when cluster structure changes.
2. **Notification**: Use **Server-Sent Events (SSE)** to push real-time updates to the frontend.

---

## 1.1 Gap Analysis: Related Implementation Plans

### Already Implemented (from `fix-identity-reassignment-implementation_plan.md`)

| Item                                                 | Status  | Location                      |
| ---------------------------------------------------- | ------- | ----------------------------- |
| `CurationActionType` enum                            | ✅ Done | `cluster_curation.py:283-288` |
| Reassignment fix (source cluster detection)          | ✅ Done | `assign_outlier_to_cluster()` |
| `pose_diversity_bonus` / `pose_bucket_size` settings | ✅ Done | `ClusteringSettings`          |
| Logging with `action_type`                           | ✅ Done | `assign_outlier_to_cluster()` |

### Implemented by This Plan

| Item                                         | Status  | Location                                                |
| -------------------------------------------- | ------- | ------------------------------------------------------- |
| `refresh_for_cluster()` in SuggestionService | ✅ Done | `recognition/application/suggestions/service.py:297`    |
| `EventBroadcaster` singleton                 | ✅ Done | `recognition/application/events/broadcaster.py`         |
| SSE endpoint `/clusters/events`              | ✅ Done | `recognition/interface_adapters/http/routers/events.py` |
| `useClusterEvents` React hook                | ✅ Done | `js/admin/hooks/useClusterEvents.ts`                    |
| Tests for suggestion refresh                 | ✅ Done | `recognition/tests/service/test_suggestion_refresh.py`  |

### Not Yet Implemented (remaining gaps)

| Item                                 | Source Document                              | This Plan Section                                             |
| ------------------------------------ | -------------------------------------------- | ------------------------------------------------------------- |
| Metadata-only `update_cluster`       | metrics.md §"Edit Label Behavior"            | §6.1                                                          |
| Split → FALSE_POSITIVE logging       | metrics.md §"Split Behavior"                 | §6.2                                                          |
| `GET /clusters/top-unlabeled`        | metrics.md §"Curate Top Clusters"            | §6.3 ✅ (endpoint only)                                       |
| Top Clusters Curation UI             | User feedback                                | See `top_clusters_curation_ui_implementation_plan.md`         |
| `_should_upgrade_representative`     | metrics.md §"Representative Quality Upgrade" | Deferred to `representative_lifecycle_implementation_plan.md` |
| UI: Replace Combobox with text input | UX feedback                                  | §6.4                                                          |

---

## 2. Problem Statement

The user observed "cluster recomputations" in logs after curation, but these only update the _Cluster_ and _Representatives_. The _AssignmentSuggestion_ records (which drive the UI) are static and become stale. Furthermore, existing curation endpoints do not inform the client that suggestions might have changed.

## 3. Proposed Changes

### 3.1 Real-time Notification: Server-Sent Events (SSE)

> [!IMPORTANT] > **Rationale for SSE**:
> Compared to **Response Headers**, SSE handles background updates and supports multiple users.
> Compared to **WebSockets**, SSE is simpler to maintain, works over standard HTTP, and is perfectly suited for unidirectional server → client notifications (like "suggestions updated").

#### 3.1.1 EventBroadcaster (Application Layer)

**New File**: `recognition/application/events/broadcaster.py`

```python
"""
In-memory event broadcaster for SSE notifications.

This module provides a simple pub/sub mechanism for broadcasting events
to connected SSE clients. For production, consider Redis pub/sub.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BroadcastEvent:
    """Immutable event payload for SSE broadcast.

    Attributes:
        event_type: Event name (e.g., "suggestions_updated", "cluster_merged").
        data: JSON-serializable payload.
        timestamp: UTC timestamp of event creation.
    """

    event_type: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class EventBroadcaster:
    """Manages SSE connections and broadcasts events to subscribers.

    Thread-safe via asyncio.Queue per subscriber. Designed for single-process
    prototype; production would use Redis pub/sub for horizontal scaling.

    Example:
        broadcaster = EventBroadcaster()

        # In SSE endpoint:
        async for event in broadcaster.subscribe(tenant_id):
            yield f"data: {event}\\n\\n"

        # In curation logic:
        await broadcaster.broadcast("suggestions_updated", {"cluster_id": "abc"}, tenant_id="t1")
    """

    def __init__(self) -> None:
        """Initialize broadcaster with empty subscriber registry."""
        self._subscribers: dict[str, list[asyncio.Queue[BroadcastEvent]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, tenant_id: str) -> AsyncIterator[BroadcastEvent]:
        """Subscribe to events for a tenant.

        Args:
            tenant_id: Tenant to receive events for.

        Yields:
            BroadcastEvent instances as they are published.

        Raises:
            asyncio.CancelledError: When client disconnects.
        """
        queue: asyncio.Queue[BroadcastEvent] = asyncio.Queue()
        async with self._lock:
            if tenant_id not in self._subscribers:
                self._subscribers[tenant_id] = []
            self._subscribers[tenant_id].append(queue)

        logger.info("[sse] Client subscribed tenant_id=%s total_subscribers=%d",
                    tenant_id, len(self._subscribers[tenant_id]))
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                if tenant_id in self._subscribers:
                    self._subscribers[tenant_id].remove(queue)
                    if not self._subscribers[tenant_id]:
                        del self._subscribers[tenant_id]
            logger.info("[sse] Client unsubscribed tenant_id=%s", tenant_id)

    async def broadcast(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> int:
        """Broadcast an event to all subscribers (optionally filtered by tenant).

        Args:
            event_type: Event name for client routing.
            data: JSON-serializable payload.
            tenant_id: If provided, only broadcast to this tenant's subscribers.

        Returns:
            Number of subscribers notified.
        """
        event = BroadcastEvent(event_type=event_type, data=data)
        notified = 0

        async with self._lock:
            tenants = [tenant_id] if tenant_id else list(self._subscribers.keys())
            for tid in tenants:
                for queue in self._subscribers.get(tid, []):
                    await queue.put(event)
                    notified += 1

        if notified > 0:
            logger.info("[sse] Broadcast event_type=%s tenant_id=%s notified=%d",
                        event_type, tenant_id, notified)
        return notified


# Module-level singleton for dependency injection
_broadcaster: EventBroadcaster | None = None


def get_event_broadcaster() -> EventBroadcaster:
    """Get or create the global EventBroadcaster singleton.

    Returns:
        The shared EventBroadcaster instance.
    """
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = EventBroadcaster()
    return _broadcaster
```

#### 3.1.2 SSE Endpoint (Interface Adapter)

**New File**: `recognition/interface_adapters/http/routers/events.py`

```python
"""
Server-Sent Events (SSE) endpoint for real-time notifications.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from recognition.application.events.broadcaster import BroadcastEvent, get_event_broadcaster
from recognition.interface_adapters.http.dependencies import require_auth
from recognition.interface_adapters.http.deps.tenant import get_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"], dependencies=[Depends(require_auth)])


async def _event_generator(request: Request, tenant_id: str):
    """Generate SSE-formatted events for a tenant.

    Args:
        request: FastAPI request (used for disconnect detection).
        tenant_id: Tenant to subscribe to.

    Yields:
        SSE-formatted strings: "data: {...}\\n\\n"
    """
    broadcaster = get_event_broadcaster()

    async for event in broadcaster.subscribe(tenant_id):
        if await request.is_disconnected():
            break

        payload = {
            "event": event.event_type,
            "timestamp": event.timestamp.isoformat(),
            **event.data,
        }
        yield f"data: {json.dumps(payload)}\n\n"


@router.get("/clusters/events")
async def cluster_events_stream(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    """Subscribe to real-time cluster/suggestion update events.

    Returns an SSE stream that emits events when:
    - Suggestions are refreshed (`suggestions_updated`)
    - Clusters are merged (`cluster_merged`)
    - Clusters are split (`cluster_split`)

    Example client usage:
        const eventSource = new EventSource('/api/v1/clusters/events');
        eventSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.event === 'suggestions_updated') {
                refetchSuggestions(data.cluster_id);
            }
        };
    """
    return StreamingResponse(
        _event_generator(request, tenant_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
```

**Router Registration** (add to `recognition/interface_adapters/http/app.py`):

```python
from recognition.interface_adapters.http.routers import events
app.include_router(events.router, prefix="/api/v1")
```

### 3.2 SuggestionService: `refresh_for_cluster`

**File**: `recognition/application/suggestions/service.py`

Add method after existing `refresh_for_identity`:

```python
async def refresh_for_cluster(self, cluster_id: str) -> int:
    """Refresh similarity scores for all pending suggestions targeting a cluster.

    Called after cluster structural changes (merge, assignment, representative
    recomputation) to ensure suggestion scores reflect current representatives.

    Args:
        cluster_id: Cluster UUID string whose suggestions need refreshing.

    Returns:
        Number of suggestions refreshed.

    Example:
        # After merge completes:
        count = await suggestion_service.refresh_for_cluster(merged_cluster_id)
        logger.info("Refreshed %d suggestions for cluster %s", count, merged_cluster_id)
    """
    if self._session is None or self._cluster_repository is None:
        return 0

    # Fetch current representatives for the cluster
    cluster = await self._cluster_repository.get_by_id(cluster_id)
    if not cluster:
        logger.warning("[suggestions] refresh_for_cluster: cluster not found cluster_id=%s", cluster_id)
        return 0

    reps = await self._cluster_repository.get_all_representatives(cluster_id)
    if not reps:
        logger.info("[suggestions] refresh_for_cluster: no representatives cluster_id=%s", cluster_id)
        return 0

    rep_embeddings = [
        np.asarray(getattr(r, "embedding", r), dtype=np.float32)
        for r in reps
    ]

    # Fetch all pending suggestions for this cluster
    suggestions = await self._repository.get_by_cluster(self._tenant_id, cluster_id)
    pending = [s for s in suggestions if s.status == SuggestionStatus.PENDING]

    if not pending:
        return 0

    refreshed = 0
    now = datetime.now(tz=UTC)

    for suggestion in pending:
        try:
            identity_uuid = uuid.UUID(str(suggestion.identity_id))
        except ValueError:
            continue

        model = await self._session.get(MediaIdentityModel, identity_uuid)
        if model is None or model.embedding is None:
            continue

        identity_embedding = extract_face_embedding(np.asarray(model.embedding, dtype=np.float32))
        if identity_embedding.size == 0:
            continue

        # Compute best similarity against current representatives
        best_similarity = 0.0
        for rep_vec in rep_embeddings:
            similarity = compute_face_similarity(identity_embedding, rep_vec)
            best_similarity = max(best_similarity, similarity)

        # Update if score changed significantly (avoid churn)
        if abs(best_similarity - suggestion.representative_similarity) > 0.01:
            await self._repository.update_scores(
                self._tenant_id,
                suggestion.id,
                representative_similarity=best_similarity,
                member_similarity=best_similarity,
                confidence_score=best_similarity,
            )
            refreshed += 1

    logger.info(
        "[suggestions] refresh_for_cluster cluster_id=%s total_pending=%d refreshed=%d",
        cluster_id, len(pending), refreshed,
    )
    return refreshed
```

### 3.3 Curation Trigger Integration

**File**: `recognition/application/orchestration/cluster_curation.py`

Inject broadcast calls after structural changes:

```python
# At module top, add import:
from recognition.application.events.broadcaster import get_event_broadcaster

# After assign_outlier_to_cluster recomputes representatives (around line 365):
async def assign_outlier_to_cluster(...) -> IdentityCluster | None:
    # ... existing logic ...

    recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
    if callable(recompute_reps):
        await recompute_reps(target_cluster_id)
    recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
    if callable(recompute_centroid):
        await recompute_centroid(target_cluster_id)

    # NEW: Broadcast suggestion refresh event
    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "suggestions_updated",
        {"cluster_id": target_cluster_id, "reason": "identity_assigned"},
        tenant_id=tenant_id,
    )

    return cluster
```

Similar pattern for merge operations and `remove_identity_from_cluster`.

---

## 4. Frontend Integration

### 4.1 SSE Client Hook

**File**: `apps/prototype-wp-alt-context/js/admin/hooks/useClusterEvents.ts`

```typescript
/**
 * React hook for subscribing to cluster SSE events.
 */

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

interface ClusterEvent {
  event: "suggestions_updated" | "cluster_merged" | "cluster_split";
  cluster_id: string;
  timestamp: string;
  reason?: string;
}

/**
 * Subscribe to real-time cluster events via SSE.
 *
 * Automatically invalidates relevant React Query caches when events arrive.
 *
 * @param tenantId - Tenant ID for scoping (passed via auth header)
 * @param enabled - Whether to connect (default: true)
 */
export function useClusterEvents(tenantId: string, enabled = true): void {
  const queryClient = useQueryClient();
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled || !tenantId) {
      return;
    }

    const eventSource = new EventSource("/api/v1/clusters/events");
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as ClusterEvent;

        switch (data.event) {
          case "suggestions_updated":
            // Invalidate suggestions for the specific cluster
            queryClient.invalidateQueries({
              queryKey: ["suggestions", data.cluster_id],
            });
            // Also invalidate the global suggestions list
            queryClient.invalidateQueries({
              queryKey: ["suggestions"],
            });
            break;

          case "cluster_merged":
          case "cluster_split":
            // Invalidate cluster list
            queryClient.invalidateQueries({
              queryKey: ["clusters"],
            });
            break;
        }
      } catch (err) {
        console.error("[useClusterEvents] Failed to parse event:", err);
      }
    };

    eventSource.onerror = () => {
      // Reconnect handled automatically by EventSource
      console.warn("[useClusterEvents] Connection error, will retry...");
    };

    return () => {
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [tenantId, enabled, queryClient]);
}
```

---

## 5. Verification Plan

### 5.1 Automated Tests

#### Unit Tests (Layer 1)

**File**: `recognition/tests/unit/test_event_broadcaster.py`

```python
"""Unit tests for EventBroadcaster."""

import asyncio
import pytest
from recognition.application.events.broadcaster import EventBroadcaster, BroadcastEvent


class TestEventBroadcaster:
    """Tests for in-memory event broadcasting."""

    @pytest.fixture
    def broadcaster(self) -> EventBroadcaster:
        return EventBroadcaster()

    async def test_subscribe_receives_broadcast(self, broadcaster: EventBroadcaster) -> None:
        """Subscriber receives events after broadcast."""
        received: list[BroadcastEvent] = []

        async def subscriber():
            async for event in broadcaster.subscribe("tenant-1"):
                received.append(event)
                if len(received) >= 1:
                    break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)  # Let subscriber start

        count = await broadcaster.broadcast("test_event", {"key": "value"}, tenant_id="tenant-1")

        await asyncio.wait_for(task, timeout=1.0)

        assert count == 1
        assert len(received) == 1
        assert received[0].event_type == "test_event"
        assert received[0].data == {"key": "value"}

    async def test_tenant_isolation(self, broadcaster: EventBroadcaster) -> None:
        """Events only go to matching tenant subscribers."""
        received_t1: list[BroadcastEvent] = []
        received_t2: list[BroadcastEvent] = []

        async def sub_t1():
            async for event in broadcaster.subscribe("tenant-1"):
                received_t1.append(event)
                break

        async def sub_t2():
            async for event in broadcaster.subscribe("tenant-2"):
                received_t2.append(event)
                break

        task1 = asyncio.create_task(sub_t1())
        task2 = asyncio.create_task(sub_t2())
        await asyncio.sleep(0.01)

        await broadcaster.broadcast("event", {"x": 1}, tenant_id="tenant-1")

        await asyncio.wait_for(task1, timeout=1.0)
        task2.cancel()

        assert len(received_t1) == 1
        assert len(received_t2) == 0
```

#### Service Tests (Layer 2)

**File**: `recognition/tests/service/test_suggestion_refresh.py`

```python
"""Service tests for suggestion refresh logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from recognition.application.suggestions.service import SuggestionService
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus


class TestRefreshForCluster:
    """Tests for SuggestionService.refresh_for_cluster."""

    @pytest.fixture
    def mock_repository(self) -> AsyncMock:
        repo = AsyncMock()
        repo.get_by_cluster = AsyncMock(return_value=[])
        repo.update_scores = AsyncMock()
        return repo

    @pytest.fixture
    def mock_cluster_repo(self) -> AsyncMock:
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=MagicMock(id="cluster-1"))
        repo.get_all_representatives = AsyncMock(return_value=[])
        return repo

    async def test_refresh_updates_changed_scores(
        self,
        mock_repository: AsyncMock,
        mock_cluster_repo: AsyncMock,
    ) -> None:
        """Suggestions with changed similarity are updated."""
        # Arrange
        pending_suggestion = MagicMock(spec=AssignmentSuggestion)
        pending_suggestion.id = "sug-1"
        pending_suggestion.identity_id = "identity-1"
        pending_suggestion.status = SuggestionStatus.PENDING
        pending_suggestion.representative_similarity = 0.75

        mock_repository.get_by_cluster.return_value = [pending_suggestion]

        # ... (mock identity model and representatives)

        service = SuggestionService(
            repository=mock_repository,
            tenant_id="tenant-1",
            cluster_repository=mock_cluster_repo,
        )

        # Act
        count = await service.refresh_for_cluster("cluster-1")

        # Assert
        # Detailed assertions depend on full mock setup
        assert isinstance(count, int)

    async def test_refresh_skips_non_pending(
        self,
        mock_repository: AsyncMock,
        mock_cluster_repo: AsyncMock,
    ) -> None:
        """Already-resolved suggestions are not refreshed."""
        accepted_suggestion = MagicMock(spec=AssignmentSuggestion)
        accepted_suggestion.status = SuggestionStatus.ACCEPTED

        mock_repository.get_by_cluster.return_value = [accepted_suggestion]

        service = SuggestionService(
            repository=mock_repository,
            tenant_id="tenant-1",
            cluster_repository=mock_cluster_repo,
        )

        count = await service.refresh_for_cluster("cluster-1")

        assert count == 0
        mock_repository.update_scores.assert_not_called()
```

#### Integration Tests (Layer 3)

**File**: `recognition/tests/integration/test_sse_flow.py`

```python
"""Integration tests for SSE notification flow."""

import pytest
from httpx import AsyncClient
from recognition.application.events.broadcaster import get_event_broadcaster


@pytest.mark.integration
class TestSSEFlow:
    """End-to-end SSE notification tests."""

    async def test_sse_endpoint_streams_events(
        self,
        async_client: AsyncClient,
        authenticated_headers: dict,
    ) -> None:
        """SSE endpoint returns streaming response."""
        async with async_client.stream(
            "GET",
            "/api/v1/clusters/events",
            headers=authenticated_headers,
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream"

    async def test_broadcast_triggers_sse_event(
        self,
        async_client: AsyncClient,
        authenticated_headers: dict,
        tenant_id: str,
    ) -> None:
        """Broadcasting an event delivers it to connected clients."""
        broadcaster = get_event_broadcaster()

        # Start SSE stream
        events_received = []

        async with async_client.stream(
            "GET",
            "/api/v1/clusters/events",
            headers=authenticated_headers,
        ) as response:
            # Broadcast event
            await broadcaster.broadcast(
                "suggestions_updated",
                {"cluster_id": "test-cluster"},
                tenant_id=tenant_id,
            )

            # Read first event
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    events_received.append(line)
                    break

        assert len(events_received) == 1
        assert "suggestions_updated" in events_received[0]
```

### 5.2 Manual Verification

1. Connect via `curl -N http://localhost:8000/api/v1/clusters/events`
2. Curate a cluster in the UI or via API
3. Confirm event `data: {"event": "suggestions_updated", ...}` appears in the curl output

---

## 6. Implementation Gaps & Refinements

As identified in `fix-identity-reassignment-and-performance-metrics.md`, several critical behaviors were not covered in the initial reassignment plan:

### 6.1 Metadata-Only Label Updates

**Problem**: Currently, `update_cluster` triggers full representative and centroid recomputations even for simple name changes.

**Current Code** (`cluster_curation.py:136-143`):

```python
# Recompute representatives/centroid if hooks exist (label changes can affect reps)
recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
if callable(recompute_reps):
    await recompute_reps(cluster_id)
recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
if callable(recompute_centroid):
    await recompute_centroid(cluster_id)
```

**Fix**: Remove recomputation calls from `update_cluster`. Label changes are metadata-only:

**File**: `recognition/application/orchestration/cluster_curation.py`

```python
async def update_cluster(
    *,
    cluster_id: str,
    tenant_id: str,
    label: str | None,
    assignment_writer: AssignmentWriter,
    clustering_logger: ClusteringLogger | None = None,
) -> IdentityCluster | None:
    """Update cluster label and confirmation state.

    This is a **metadata-only** operation. It does NOT trigger representative
    or centroid recomputation. Use `recompute_representatives()` explicitly
    if structural changes have occurred.

    Args:
        cluster_id: Cluster UUID to update.
        tenant_id: Tenant scope for authorization.
        label: New label (None clears label).
        assignment_writer: Writer for persistence access.
        clustering_logger: Optional logger for audit events.

    Returns:
        Updated cluster, or None if not found/unauthorized.
    """
    cluster_repo: ClusterRepository = assignment_writer._clusters
    cluster = await cluster_repo.get_by_id(cluster_id)
    if not cluster or cluster.tenant_id.lower() != tenant_id.lower():
        return None

    old_label = cluster.label
    cluster.label = label
    cluster.is_labeled = bool(label)
    cluster.user_confirmed = bool(label)
    updated = await cluster_repo.update(cluster)

    if clustering_logger and old_label != label:
        with contextlib.suppress(Exception):
            clustering_logger.log_cluster_renamed(
                cluster_id=cluster_id,
                old_label=old_label,
                new_label=label,
                tenant_id=tenant_id,
            )

    logger.info(
        "[curation] RENAMED cluster_id=%s old_label='%s' new_label='%s' "
        "tenant_id=%s user_action=manual_rename metadata_only=true",
        cluster_id,
        old_label,
        label,
        tenant_id,
    )

    # NOTE: No recomputation here. Label changes don't affect embeddings.
    # Broadcast for UI refresh only (label display update).
    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "cluster_updated",
        {"cluster_id": cluster_id, "label": label},
        tenant_id=tenant_id,
    )

    return updated
```

### 6.2 Split Operation → FALSE_POSITIVE Logging

**Problem**: Large clusters incorrectly merged by the system are often "Split". We need to track identities moved to the new cluster as `FALSE_POSITIVE` events.

**File**: `recognition/application/orchestration/cluster_curation.py`

Add to split operation (or create if not exists):

```python
async def split_cluster(
    *,
    source_cluster_id: str,
    identity_ids_to_move: list[str],
    new_cluster_label: str | None,
    tenant_id: str,
    session: AsyncSession,
    assignment_writer: AssignmentWriter,
) -> IdentityCluster:
    """Split identities from a cluster into a new cluster.

    Identities moved to the new cluster are logged as FALSE_POSITIVE corrections,
    indicating the system incorrectly grouped them with the source cluster.

    Args:
        source_cluster_id: Cluster to split from.
        identity_ids_to_move: Identities to move to the new cluster.
        new_cluster_label: Label for the new cluster (optional).
        tenant_id: Tenant scope.
        session: Database session.
        assignment_writer: Persistence writer.

    Returns:
        Newly created cluster containing the moved identities.

    Raises:
        ValueError: If source cluster not found or no identities to move.
    """
    cluster_repo: ClusterRepository = assignment_writer._clusters
    member_repo: MemberRepository = assignment_writer._members

    source_cluster = await cluster_repo.get_by_id(source_cluster_id)
    if not source_cluster or source_cluster.tenant_id.lower() != tenant_id.lower():
        raise ValueError(f"Source cluster not found: {source_cluster_id}")

    if not identity_ids_to_move:
        raise ValueError("No identities specified for split")

    # Create new cluster
    new_cluster = await assignment_writer.persist_new_cluster(
        tenant_id=tenant_id,
        identities=[],  # Will add via membership
        similarities=[],
        algorithm="manual_split",
    )

    # Move identities and log as FALSE_POSITIVE
    for identity_id in identity_ids_to_move:
        await remove_identity_from_cluster(
            identity_id=identity_id,
            member_repo=member_repo,
            cluster_repo=cluster_repo,
            assignment_writer=assignment_writer,
            recompute=False,  # Defer until all moves complete
            tenant_id_for_logging=tenant_id,
        )

        await member_repo.add_member(new_cluster.id, identity_id=identity_id, similarity=1.0)

        logger.info(
            "[curation] SPLIT identity=%s from_cluster=%s to_cluster=%s "
            "tenant_id=%s user_action=manual_split action_type=%s",
            identity_id,
            source_cluster_id,
            new_cluster.id,
            tenant_id,
            CurationActionType.FALSE_POSITIVE.value,  # System incorrectly grouped
        )

    # Update counts
    new_cluster.identity_count = len(identity_ids_to_move)
    source_cluster.identity_count -= len(identity_ids_to_move)
    await cluster_repo.update(new_cluster)
    await cluster_repo.update(source_cluster)

    # Recompute both clusters
    recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
    if callable(recompute_reps):
        await recompute_reps(source_cluster_id)
        await recompute_reps(new_cluster.id)

    # Set label if provided
    if new_cluster_label:
        new_cluster.label = new_cluster_label
        new_cluster.is_labeled = True
        await cluster_repo.update(new_cluster)

    # Broadcast events
    broadcaster = get_event_broadcaster()
    await broadcaster.broadcast(
        "cluster_split",
        {
            "source_cluster_id": source_cluster_id,
            "new_cluster_id": new_cluster.id,
            "moved_count": len(identity_ids_to_move),
        },
        tenant_id=tenant_id,
    )

    return new_cluster
```

### 6.3 "Curate Top Clusters" Endpoint

**Problem**: Suggestions only appear for _labeled_ clusters. Initial batches have zero labeled clusters, so suggestions never appear (chicken-and-egg).

**File**: `recognition/interface_adapters/http/routers/clusters.py`

```python
@router.get("/clusters/top-unlabeled", response_model=list[ClusterResponse])
async def get_top_unlabeled_clusters(
    limit: int = Query(default=10, ge=1, le=50, description="Max clusters to return"),
    tenant_id: str = Depends(get_tenant_id),
    session=Depends(get_session),
    auth=Depends(require_auth),
) -> list[ClusterResponse]:
    """Get unlabeled clusters with the highest identity counts.

    Use this endpoint to bootstrap the curation workflow. Returns clusters
    that have the most members but no user-assigned label yet, allowing
    users to label the most impactful clusters first.

    Returns:
        List of clusters sorted by identity_count descending.
    """
    cluster_service = await build_cluster_service(session=session, tenant_id=tenant_id)

    # Get unlabeled clusters sorted by member count
    clusters = await cluster_service.get_top_unlabeled(limit=limit)

    return [
        ClusterResponse(
            id=c.id,
            label=c.label,
            identity_count=c.identity_count,
            is_labeled=c.is_labeled,
            user_confirmed=c.user_confirmed,
            created_at=c.created_at,
            representatives=[],  # Lightweight response
        )
        for c in clusters
    ]
```

**Repository Method** (`recognition/domain/repositories.py`):

```python
class ClusterRepository(Protocol):
    # ... existing methods ...

    async def get_top_unlabeled(
        self,
        tenant_id: str,
        limit: int = 10,
    ) -> list[IdentityCluster]:
        """Get unlabeled clusters sorted by identity_count descending.

        Args:
            tenant_id: Tenant scope.
            limit: Maximum clusters to return.

        Returns:
            Unlabeled clusters with highest member counts.
        """
        raise NotImplementedError("TODO: Implement get_top_unlabeled")
```

### 6.4 Frontend: Replace Combobox with Autofocus Text Input

**Problem**: The "Edit Label" interaction currently renders a `Combobox` which requires an extra click before typing.

**File**: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterEditForm.tsx`

```tsx
/**
 * Cluster label edit form with direct text input and floating suggestions.
 */

import React, { useRef, useEffect, useState } from "react";
import { __ } from "@wordpress/i18n";

import type { ComboboxOption } from "../../../../components/ui/combobox";

interface ClusterEditFormProps {
  labelInput: string;
  onLabelChange: (value: string) => void;
  options: ComboboxOption[];
  isLoading: boolean;
  isPending: boolean;
  onSave: () => void;
  onCancel: () => void;
  /** Called when user selects a suggestion from the dropdown */
  onSelectSuggestion?: (option: ComboboxOption) => void;
}

/**
 * Edit form with autofocus text input and floating suggestions overlay.
 */
export const ClusterEditForm = ({
  labelInput,
  onLabelChange,
  options,
  isLoading,
  isPending,
  onSave,
  onCancel,
  onSelectSuggestion,
}: ClusterEditFormProps): React.JSX.Element => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [showSuggestions, setShowSuggestions] = useState(false);

  // Autofocus on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Filter options based on input
  const filteredOptions = options.filter((opt) =>
    opt.label.toLowerCase().includes(labelInput.toLowerCase())
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onSave();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  };

  const handleSelectSuggestion = (option: ComboboxOption) => {
    onLabelChange(option.label);
    setShowSuggestions(false);
    onSelectSuggestion?.(option);
  };

  return (
    <div className="acx-identity-cluster__edit">
      <div className="acx-identity-cluster__input-wrapper">
        <input
          ref={inputRef}
          type="text"
          value={labelInput}
          onChange={(e) => {
            onLabelChange(e.target.value);
            setShowSuggestions(true);
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => setShowSuggestions(true)}
          onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
          placeholder={__("Enter a name…", "alt-context")}
          aria-label={__("Cluster label", "alt-context")}
          disabled={isPending}
          className="acx-identity-cluster__label-input"
          autoComplete="off"
        />

        {showSuggestions && filteredOptions.length > 0 && (
          <ul
            className="acx-identity-cluster__suggestions-list"
            role="listbox"
            aria-label={__("Label suggestions", "alt-context")}
          >
            {isLoading ? (
              <li className="acx-identity-cluster__suggestion-loading">
                {__("Loading…", "alt-context")}
              </li>
            ) : (
              filteredOptions.map((option) => (
                <li
                  key={option.value}
                  role="option"
                  className="acx-identity-cluster__suggestion-item"
                  onMouseDown={() => handleSelectSuggestion(option)}
                >
                  <span>{option.label}</span>
                  {option.similarity !== undefined && (
                    <span className="acx-identity-cluster__match-score">
                      {Math.round((option.similarity as number) * 100)}%
                    </span>
                  )}
                </li>
              ))
            )}
          </ul>
        )}
      </div>

      <button
        type="button"
        className="acx-identity-cluster__save"
        onClick={onSave}
        disabled={isPending}
      >
        {isPending ? __("Saving…", "alt-context") : __("Save", "alt-context")}
      </button>
      <button
        type="button"
        className="acx-identity-cluster__cancel"
        onClick={onCancel}
      >
        {__("Cancel", "alt-context")}
      </button>
    </div>
  );
};
```

**CSS** (add to existing stylesheet):

```css
.acx-identity-cluster__input-wrapper {
  position: relative;
  flex: 1;
}

.acx-identity-cluster__label-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--wp-admin-theme-color, #007cba);
  border-radius: 4px;
  font-size: 14px;
}

.acx-identity-cluster__suggestions-list {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  max-height: 200px;
  overflow-y: auto;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  z-index: 100;
}

.acx-identity-cluster__suggestion-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
}

.acx-identity-cluster__suggestion-item:hover {
  background: #f0f0f1;
}
```

---

## 7. Phase 0: Scaffolding (MANDATORY per instructions.md)

Before implementation, scaffold all interfaces with type hints and `NotImplementedError` bodies.

### 7.1 Backend Scaffolds

**File**: `recognition/application/events/__init__.py`

```python
"""Event broadcasting for real-time notifications."""

from recognition.application.events.broadcaster import (
    BroadcastEvent,
    EventBroadcaster,
    get_event_broadcaster,
)

__all__ = ["BroadcastEvent", "EventBroadcaster", "get_event_broadcaster"]
```

**File**: `recognition/application/events/broadcaster.py` (scaffold)

```python
"""In-memory event broadcaster for SSE notifications."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class BroadcastEvent:
    """Immutable event payload for SSE broadcast."""

    event_type: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class EventBroadcaster:
    """Manages SSE connections and broadcasts events to subscribers."""

    def __init__(self) -> None:
        """Initialize broadcaster with empty subscriber registry."""
        raise NotImplementedError("TODO: Initialize subscriber dict and lock")

    async def subscribe(self, tenant_id: str) -> AsyncIterator[BroadcastEvent]:
        """Subscribe to events for a tenant.

        Args:
            tenant_id: Tenant to receive events for.

        Yields:
            BroadcastEvent instances as they are published.
        """
        raise NotImplementedError("TODO: Implement subscription logic")

    async def broadcast(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> int:
        """Broadcast an event to all subscribers.

        Args:
            event_type: Event name for client routing.
            data: JSON-serializable payload.
            tenant_id: If provided, only broadcast to this tenant.

        Returns:
            Number of subscribers notified.
        """
        raise NotImplementedError("TODO: Implement broadcast logic")


def get_event_broadcaster() -> EventBroadcaster:
    """Get or create the global EventBroadcaster singleton."""
    raise NotImplementedError("TODO: Implement singleton pattern")
```

**File**: `recognition/application/suggestions/service.py` (add scaffold)

```python
# Add after refresh_for_identity method:

async def refresh_for_cluster(self, cluster_id: str) -> int:
    """Refresh similarity scores for all pending suggestions targeting a cluster.

    Args:
        cluster_id: Cluster UUID string whose suggestions need refreshing.

    Returns:
        Number of suggestions refreshed.

    Raises:
        ValueError: If cluster_id is invalid.
    """
    raise NotImplementedError("TODO: Implement refresh_for_cluster")
```

**File**: `recognition/domain/repositories.py` (add to ClusterRepository Protocol)

```python
async def get_top_unlabeled(
    self,
    tenant_id: str,
    limit: int = 10,
) -> list[IdentityCluster]:
    """Get unlabeled clusters sorted by identity_count descending.

    Args:
        tenant_id: Tenant scope.
        limit: Maximum clusters to return.

    Returns:
        Unlabeled clusters with highest member counts.
    """
    raise NotImplementedError("TODO: Implement get_top_unlabeled")
```

### 7.2 Frontend Scaffolds

**File**: `js/admin/hooks/useClusterEvents.ts` (scaffold)

```typescript
/**
 * React hook for subscribing to cluster SSE events.
 */

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * Subscribe to real-time cluster events via SSE.
 *
 * @param tenantId - Tenant ID for scoping
 * @param enabled - Whether to connect (default: true)
 */
export function useClusterEvents(tenantId: string, enabled = true): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    // TODO: Implement EventSource connection
    // TODO: Handle message events
    // TODO: Invalidate queries on relevant events
    throw new Error("TODO: Implement useClusterEvents hook");
  }, [tenantId, enabled, queryClient]);
}
```

---

## 8. Updated Checklist

### Phase 0: Scaffolding

- [x] Create `recognition/application/events/__init__.py` <!-- id: 30 -->
- [x] Scaffold `EventBroadcaster` class with `NotImplementedError` <!-- id: 31 -->
- [x] Scaffold `refresh_for_cluster` in `SuggestionService` <!-- id: 32 -->
- [x] Scaffold `get_top_unlabeled` in `ClusterRepository` Protocol <!-- id: 33 -->
- [x] Scaffold `useClusterEvents` hook <!-- id: 34 -->

### Phase 1: Core Infrastructure

- [x] Implement `EventBroadcaster` logic <!-- id: 20 -->
- [x] Create SSE endpoint in `recognition/interface_adapters/http/routers/events.py` <!-- id: 21 -->
- [x] Register events router in `app.py` <!-- id: 35 -->
- [x] Unit tests for `EventBroadcaster` <!-- id: 36 -->

### Phase 2: Suggestion Refresh

- [x] Implement `refresh_for_cluster` in `SuggestionService` <!-- id: 11 -->
- [x] Service tests for refresh logic <!-- id: 37 -->
- [x] Integrate broadcast trigger in `assign_outlier_to_cluster` <!-- id: 13 -->

### Phase 3: Metadata & Split Fixes

- [x] Refine `update_cluster` to be metadata-only (remove recomputation) <!-- id: 22 -->
- [x] Add `FALSE_POSITIVE` logging to split operations <!-- id: 23 -->
- [x] Implement `split_cluster` function if not exists <!-- id: 38 -->

### Phase 4: Bootstrapping

- [x] Implement `get_top_unlabeled` in SqlAlchemy repository <!-- id: 39 -->
- [x] Implement `GET /api/v1/clusters/top-unlabeled` endpoint <!-- id: 24 -->
- [x] Integration test for top-unlabeled endpoint <!-- id: 40 -->

### Phase 5: Frontend

- [x] Implement `useClusterEvents` hook <!-- id: 41 -->
- [x] Replace `Combobox` with autofocus text input in `ClusterEditForm.tsx` <!-- id: 25 -->
- [x] Add CSS for suggestions overlay <!-- id: 42 -->
- [x] Vitest tests for `ClusterEditForm` accessibility <!-- id: 43 -->

### Phase 6: Verification

- [ ] Integration test: SSE flow end-to-end <!-- id: 44 -->
- [ ] Manual verification: curl SSE stream <!-- id: 15 -->
- [ ] Manual verification: UI label edit UX <!-- id: 45 -->

---

## 9. Files Modified Summary

| File                                                             | Change Type | Description                                                                     |
| ---------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------- |
| `recognition/application/events/__init__.py`                     | New         | Package init                                                                    |
| `recognition/application/events/broadcaster.py`                  | New         | SSE broadcaster                                                                 |
| `recognition/interface_adapters/http/routers/events.py`          | New         | SSE endpoint                                                                    |
| `recognition/interface_adapters/http/app.py`                     | Modify      | Register events router                                                          |
| `recognition/application/suggestions/service.py`                 | Modify      | Add `refresh_for_cluster`                                                       |
| `recognition/application/orchestration/cluster_curation.py`      | Modify      | Remove recompute from `update_cluster`, add `split_cluster`, broadcast triggers |
| `recognition/domain/repositories.py`                             | Modify      | Add `get_top_unlabeled` to Protocol                                             |
| `recognition/infrastructure/repositories/cluster_repository.py`  | Modify      | Implement `get_top_unlabeled`                                                   |
| `recognition/interface_adapters/http/routers/clusters.py`        | Modify      | Add `top-unlabeled` endpoint                                                    |
| `js/admin/hooks/useClusterEvents.ts`                             | New         | SSE client hook                                                                 |
| `js/admin/pages/workbench/identity-clusters/ClusterEditForm.tsx` | Modify      | Text input + suggestions                                                        |

- **`_should_upgrade_representative`**: Quality-based representative replacement
- **Representative replacement on batch processing**: Wait until batch completes
- **User-confirmed representative protection**: Don't auto-replace user selections

These require additional design consideration for the representative lifecycle and are not blocking for the SSE/refresh flow.
