# Workbench Cluster Editing Implementation Guide

> **Extends**: [`workbench-cluster-editing-plan.md`](workbench-cluster-editing-plan.md)  
> **Status**: Implementation specification

## Overview

This document provides concrete implementation details for surfacing detected identities directly in the Workbench media table and enabling inline cluster label editing ("Name this person"). The goal is to allow operators to review and curate identity clusters without leaving the Workbench page, making the recognition workflow more efficient.

---

## Part 1: Backend Extensions (Recognition/Identity service — `apps/prototype-description-service`)

### 1.1 New Endpoints

#### GET /recognition/media/identities

Returns detected identities (identities today, but future-proofed for other entity types) for a batch of media IDs, grouped by attachment, including pre-cropped thumbnails so the Workbench UI never has to issue ad-hoc crop requests back through WordPress.

**Request**:

```http
GET /recognition/media/identities?tenant_id=<uuid>&media_ids[]=1&media_ids[]=2
```

**Response**:

```json
{
  "identities_by_media": {
    "1": [
      {
        "id": "identity-uuid-1",
        "type": "identity",
        "cluster_id": "cluster-uuid-1",
        "cluster_label": "cluster-0af31e47",
        "is_auto_label": true,
        "bbox": { "x": 100, "y": 50, "width": 80, "height": 80 },
        "confidence": 0.92,
        "similarity": 0.87,
        "detected_at": "2025-11-13T10:30:00Z",
        "thumbnail_url": "https://recognition.example.com/identities/identity-uuid-1-thumb.jpg"
      }
    ],
    "2": []
  }
}
```

**Implementation**:

```python
# apps/prototype-description-service/recognition/interidentity_adapters/http/recognition_router.py

from typing import Dict, List

class MediaIdentitiesRequest(BaseModel):
    tenant_id: UUID
    media_ids: List[int] = Field(..., min_items=1, max_items=100)


class MediaIdentityDetail(BaseModel):
    id: str
    type: str = Field(default="identity")
    cluster_id: Optional[str]
    cluster_label: Optional[str]
    is_auto_label: bool
    bbox: dict
    confidence: float
    similarity: Optional[float]
    detected_at: str
    thumbnail_url: Optional[str]


class MediaIdentitiesResponse(BaseModel):
    identities_by_media: Dict[str, List[MediaIdentityDetail]]


@router.get("/media/identities", response_model=MediaIdentitiesResponse)
async def get_media_identities(
    tenant_id: UUID,
    media_ids: List[int] = Query(..., max_items=100),
    session: AsyncSession = Depends(get_session),
) -> MediaIdentitiesResponse:
    """
    Fetch all detected identities for the given media IDs, grouped by attachment.
    Includes cluster assignment and label metadata.
    """
    from db.models import MediaIdentity, ClusterMember, IdentityCluster
    from sqlalchemy.orm import selectinload

    stmt = (
        select(MediaIdentity)
        .where(MediaIdentity.tenant_id == tenant_id)
        .where(MediaIdentity.media_id.in_(media_ids))
        .where(MediaIdentity.is_deleted == False)
        .options(selectinload(MediaIdentity.cluster_members))
    )

    result = await session.execute(stmt)
    identities = result.scalars().all()

    # Group by media_id
    identities_by_media: Dict[int, List[MediaIdentity]] = {}
    for identity in identities:
        if identity.media_id not in identities_by_media:
            identities_by_media[identity.media_id] = []
        identities_by_media[identity.media_id].append(identity)

    # Fetch cluster labels
    cluster_ids = {
        member.cluster_id
        for identity in identities
        for member in identity.cluster_members
        if member.cluster_id
    }

    cluster_labels: Dict[UUID, tuple[str, bool]] = {}
    if cluster_ids:
        cluster_stmt = select(IdentityCluster).where(IdentityCluster.id.in_(cluster_ids))
        cluster_result = await session.execute(cluster_stmt)
        clusters = cluster_result.scalars().all()
        for cluster in clusters:
            # Check if label follows auto-generated pattern
            is_auto = cluster.label and cluster.label.startswith("cluster-")
            cluster_labels[cluster.id] = (cluster.label or "", is_auto)

    # Build response
    response_data: Dict[str, List[MediaIdentityDetail]] = {}
    for media_id in media_ids:
        media_identities = identities_by_media.get(media_id, [])
        response_data[str(media_id)] = [
            MediaIdentityDetail(
                id=str(identity.id),
                type="identity",
                cluster_id=str(identity.cluster_members[0].cluster_id) if identity.cluster_members else None,
                cluster_label=cluster_labels.get(identity.cluster_members[0].cluster_id, ("", True))[0]
                if identity.cluster_members
                else None,
                is_auto_label=cluster_labels.get(identity.cluster_members[0].cluster_id, ("", True))[1]
                if identity.cluster_members
                else False,
                bbox={
                    "x": identity.bbox_x,
                    "y": identity.bbox_y,
                    "width": identity.bbox_width,
                    "height": identity.bbox_height,
                },
                confidence=identity.confidence,
                similarity=identity.cluster_members[0].similarity if identity.cluster_members else None,
                detected_at=identity.created_at.isoformat(),
                thumbnail_url=identity.thumbnail_url,
            )
            for identity in media_identities
        ]

    return MediaIdentitiesResponse(identities_by_media=response_data)
```

#### PATCH /recognition/clusters/{cluster_id}

Updates a cluster's label.

**Request**:

```http
PATCH /recognition/clusters/{cluster_id}
Content-Type: application/json

{
  "tenant_id": "uuid",
  "label": "John Doe"
}
```

**Response**:

```json
{
  "id": "cluster-uuid",
  "label": "John Doe",
  "identity_count": 5,
  "updated_at": "2025-11-13T11:00:00Z"
}
```

**Implementation**:

```python
class UpdateClusterLabelRequest(BaseModel):
    tenant_id: UUID
    label: str = Field(..., min_length=1, max_length=255)


class UpdateClusterLabelResponse(BaseModel):
    id: str
    label: str
    identity_count: int
    updated_at: str


@router.patch("/clusters/{cluster_id}", response_model=UpdateClusterLabelResponse)
async def update_cluster_label(
    cluster_id: UUID,
    request: UpdateClusterLabelRequest,
    session: AsyncSession = Depends(get_session),
) -> UpdateClusterLabelResponse:
    """
    Update the label of an existing cluster.
    Validates tenant ownership and label uniqueness.
    """
    from datetime import datetime
    from db.models import IdentityCluster

    # Fetch cluster
    cluster = await session.get(IdentityCluster, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    if cluster.tenant_id != request.tenant_id:
        raise HTTPException(status_code=403, detail="Cluster belongs to different tenant")

    # Check label uniqueness for this tenant
    existing_stmt = select(IdentityCluster).where(
        IdentityCluster.tenant_id == request.tenant_id,
        IdentityCluster.label == request.label,
        IdentityCluster.id != cluster_id,
    )
    existing = await session.execute(existing_stmt)
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Label '{request.label}' already exists for this tenant")

    # Update label
    cluster.label = request.label
    cluster.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(cluster)

    return UpdateClusterLabelResponse(
        id=str(cluster.id),
        label=cluster.label,
        identity_count=cluster.identity_count,
        updated_at=cluster.updated_at.isoformat(),
    )
```

#### POST /recognition/clusters/{source_id}/merge

Merges source cluster into target cluster (identified by label).

**Request**:

```http
POST /recognition/clusters/{source_id}/merge
Content-Type: application/json

{
  "tenant_id": "uuid",
  "target_label": "Jane Smith"
}
```

**Response**:

```json
{
  "source_id": "cluster-uuid-old",
  "target_id": "cluster-uuid-new",
  "identities_moved": 3,
  "target_identity_count": 8
}
```

**Implementation**:

```python
class MergeClusterRequest(BaseModel):
    tenant_id: UUID
    target_label: str = Field(..., min_length=1, max_length=255)


class MergeClusterResponse(BaseModel):
    source_id: str
    target_id: str
    identities_moved: int
    target_identity_count: int


@router.post("/clusters/{source_id}/merge", response_model=MergeClusterResponse)
async def merge_cluster(
    source_id: UUID,
    request: MergeClusterRequest,
    session: AsyncSession = Depends(get_session),
) -> MergeClusterResponse:
    """
    Merge source cluster into a target cluster identified by label.
    If target doesn't exist, create it first.
    """
    from datetime import datetime
    from db.models import IdentityCluster, ClusterMember

    # Fetch source cluster
    source = await session.get(IdentityCluster, source_id)
    if not source or source.tenant_id != request.tenant_id:
        raise HTTPException(status_code=404, detail="Source cluster not found or unauthorized")

    # Find or create target cluster
    target_stmt = select(IdentityCluster).where(
        IdentityCluster.tenant_id == request.tenant_id,
        IdentityCluster.label == request.target_label,
    )
    target_result = await session.execute(target_stmt)
    target = target_result.scalar_one_or_none()

    if not target:
        # Create new cluster with the desired label
        target = IdentityCluster(
            tenant_id=request.tenant_id,
            label=request.target_label,
            identity_count=0,
            similarity_threshold=source.similarity_threshold,
            clustering_algorithm=source.clustering_algorithm,
        )
        session.add(target)
        await session.flush()

    # Move all members from source to target
    members_stmt = select(ClusterMember).where(ClusterMember.cluster_id == source_id)
    members_result = await session.execute(members_stmt)
    members = members_result.scalars().all()

    identities_moved = len(members)
    for member in members:
        member.cluster_id = target.id

    # Update identity counts
    target.identity_count += identities_moved
    target.updated_at = datetime.utcnow()

    # Soft-delete source cluster
    source.is_deleted = True
    source.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(target)

    return MergeClusterResponse(
        source_id=str(source_id),
        target_id=str(target.id),
        identities_moved=identities_moved,
        target_identity_count=target.identity_count,
    )
```

### 1.2 Database Schema Updates

Add `is_deleted` flag and harden tenant isolation with constraints + row-level security:

```python
# db/models.py - IdentityCluster model addition
is_deleted = Column(Boolean, default=False, nullable=False)
__table_args__ = (
    UniqueConstraint('tenant_id', 'label', name='unique_cluster_label_per_tenant'),
    UniqueConstraint('tenant_id', 'roster_id', name='unique_cluster_roster_per_tenant'),
    # ...existing indexes...
)
```

Alembic migration:

```python
# db/migrations/versions/002_add_cluster_soft_delete.py

def upgrade() -> None:
    op.add_column('identity_clusters', sa.Column('is_deleted', sa.Boolean, server_default='false'))
    op.create_index('idx_identity_clusters_active', 'identity_clusters', ['tenant_id', 'is_deleted'])


def downgrade() -> None:
    op.drop_index('idx_identity_clusters_active')
    op.drop_column('identity_clusters', 'is_deleted')
```

Enforce tenant isolation directly in PostgreSQL using Row-Level Security:

```sql
ALTER TABLE identity_clusters ENABLE ROW LEVEL SECURITY;
CREATE POLICY identity_clusters_tenant_policy ON identity_clusters
  USING (tenant_id = current_setting('app.current_tenant')::uuid);

ALTER TABLE cluster_members ENABLE ROW LEVEL SECURITY;
CREATE POLICY cluster_members_tenant_policy ON cluster_members
  USING (tenant_id = current_setting('app.current_tenant')::uuid);
```

Every DB session in the recognition service should set `SET app.current_tenant = '<tenant-uuid>';` before executing tenant-specific queries so RLS and unique constraints prevent any cross-tenant leakage.

### 1.3 Automatic Cluster Merge Service

Port the archived service's auto-merge logic to consolidate similar clusters post-clustering.

```python
# recognition/application/identity_clustering_service.py

async def merge_similar_clusters(self, threshold: float = 0.7) -> int:
    """
    Automatically merge clusters whose representative embeddings are within threshold.
    Returns the number of merges performed.
    """
    from sqlalchemy import func
    import numpy as np

    # Fetch all active clusters with representatives
    stmt = (
        select(IdentityCluster, MediaIdentity.embedding)
        .join(MediaIdentity, IdentityCluster.representative_identity_id == MediaIdentity.id)
        .where(IdentityCluster.tenant_id == self.tenant_id)
        .where(IdentityCluster.is_deleted == False)
    )
    result = await self.session.execute(stmt)
    clusters_with_embeddings = [(cluster, np.array(embedding)) for cluster, embedding in result.all()]

    merges_performed = 0
    i = 0
    while i < len(clusters_with_embeddings):
        cluster_a, embedding_a = clusters_with_embeddings[i]
        j = i + 1
        while j < len(clusters_with_embeddings):
            cluster_b, embedding_b = clusters_with_embeddings[j]

            # Compute cosine similarity
            similarity = np.dot(embedding_a, embedding_b) / (
                np.linalg.norm(embedding_a) * np.linalg.norm(embedding_b)
            )

            if similarity >= threshold:
                # Merge cluster_b into cluster_a
                await self._merge_clusters(cluster_a.id, cluster_b.id)
                clusters_with_embeddings.pop(j)
                merges_performed += 1
                # Don't increment j, check the next cluster at the same index
            else:
                j += 1
        i += 1

    return merges_performed


async def _merge_clusters(self, target_id: UUID, source_id: UUID) -> None:
    """Internal helper to merge source cluster into target."""
    from datetime import datetime

    # Move members
    members_stmt = select(ClusterMember).where(ClusterMember.cluster_id == source_id)
    members_result = await self.session.execute(members_stmt)
    members = members_result.scalars().all()

    for member in members:
        member.cluster_id = target_id

    # Update counts
    target = await self.session.get(IdentityCluster, target_id)
    source = await self.session.get(IdentityCluster, source_id)

    if target and source:
        target.identity_count += source.identity_count
        target.updated_at = datetime.utcnow()
        source.is_deleted = True
        source.updated_at = datetime.utcnow()

    await self.session.flush()
```

Expose via endpoint that enqueues a background task and emits completion events/webhooks:

```python
@router.post("/clusters/merge-similar")
async def trigger_cluster_merge(
    tenant_id: UUID,
    threshold: float = 0.7,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Trigger automatic merge of similar clusters based on embedding distance by enqueuing
    an async task (Celery/RQ). Return job metadata so the frontend can listen for events.
    """
    job_id = await enqueue_merge_clusters_task(tenant_id=tenant_id, threshold=threshold)
    return {"job_id": job_id}
```

---

## Part 2: WordPress Integration (apps/prototype-wp-alt-context)

### 2.1 REST Proxy Endpoints

Extend `RecognitionProxyController` to expose new endpoints.

```php
// src/api/class-recognition-proxy-controller.php

public function register_routes(): void {
    // ... existing routes ...

    register_rest_route(
        'acx/v1',
        '/workbench/recognition/media-identities',
        array(
            'methods'             => 'GET',
            'callback'            => array( $this, 'get_media_identities' ),
            'permission_callback' => array( $this, 'can_manage_recognition' ),
            'args'                => array(
                'media_ids' => array(
                    'type'        => 'array',
                    'required'    => true,
                    'items'       => array( 'type' => 'integer' ),
                    'description' => 'Media IDs to fetch identities for (max 100).',
                ),
            ),
        )
    );

    register_rest_route(
        'acx/v1',
        '/workbench/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)',
        array(
            'methods'             => 'PATCH',
            'callback'            => array( $this, 'update_cluster_label' ),
            'permission_callback' => array( $this, 'can_manage_recognition' ),
        )
    );

    register_rest_route(
        'acx/v1',
        '/workbench/recognition/clusters/(?P<source_id>[a-f0-9-]+)/merge',
        array(
            'methods'             => 'POST',
            'callback'            => array( $this, 'merge_cluster' ),
            'permission_callback' => array( $this, 'can_manage_recognition' ),
        )
    );
}

public function get_media_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
    $media_ids = $request->get_param( 'media_ids' );

    if ( ! is_array( $media_ids ) || empty( $media_ids ) ) {
        return new WP_Error( 'invalid_media_ids', 'Provide media_ids array.', array( 'status' => 400 ) );
    }

    $query_params = array(
        'tenant_id' => $this->get_tenant_id(),
        'media_ids' => $media_ids,
    );

    return $this->proxy_request( 'GET', '/recognition/media/identities', null, $query_params );
}

public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
    $cluster_id = (string) $request->get_param( 'cluster_id' );
    $label      = sanitize_text_field( $request->get_param( 'label' ) );

    if ( '' === $label ) {
        return new WP_Error( 'empty_label', 'Label cannot be empty.', array( 'status' => 400 ) );
    }

    $payload = array(
        'tenant_id' => $this->get_tenant_id(),
        'label'     => $label,
    );

    return $this->proxy_request( 'PATCH', sprintf( '/recognition/clusters/%s', $cluster_id ), $payload );
}

public function merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
    $source_id    = (string) $request->get_param( 'source_id' );
    $target_label = sanitize_text_field( $request->get_param( 'target_label' ) );

    if ( '' === $target_label ) {
        return new WP_Error( 'empty_target', 'Target label required.', array( 'status' => 400 ) );
    }

    $payload = array(
        'tenant_id'    => $this->get_tenant_id(),
        'target_label' => $target_label,
    );

    return $this->proxy_request( 'POST', sprintf( '/recognition/clusters/%s/merge', $source_id ), $payload );
}
```

### 2.2 Admin Localization

Update `class-admin.php` to expose new endpoints:

```php
// src/admin/class-admin.php - enqueue_admin_assets method

'workbenchRecognitionMediaIdentities' => rest_url( 'acx/v1/workbench/recognition/media-identities' ),
'workbenchRecognitionClusters'   => rest_url( 'acx/v1/workbench/recognition/clusters' ),
```

---

## Part 3: Frontend Implementation (apps/prototype-wp-alt-context/js)

### 3.1 Type Definitions

Extend `WorkbenchMediaItem` to include detected identities:

```typescript
// js/admin/hooks/useWorkbenchMedia.ts

type DetectedIdentity = {
  id: string;
  type: "identity";
  clusterId: string | null;
  clusterLabel: string | null;
  isAutoLabel: boolean;
  bbox: { x: number; y: number; width: number; height: number };
  confidence: number;
  similarity: number | null;
  detectedAt: string;
  thumbnailUrl: string | null;
};

type WorkbenchMediaItem = {
  id: number;
  title: string;
  altText: string | null;
  status: "missing" | "complete";
  thumbnailUrl: string | null;
  mimeType: string;
  editUrl: string;
  tags: string[];
  identities?: DetectedIdentity[]; // Optional, loaded on demand
};
**Status**: Completed – `useWorkbenchMedia` now enriches each row via `useMediaIdentities`, so the UI can render thumbnails with identity metadata without extra wiring.
```

### 3.2 Media Identities API

Create a dedicated hook for fetching identities:

```typescript
// js/admin/api/recognitionApi.ts additions

export type MediaIdentitiesResponse = {
  identities_by_media: Record<string, DetectedIdentity[]>;
};

export const fetchMediaIdentities = async (
  mediaIds: number[]
): Promise<MediaIdentitiesResponse> => {
  const config = getConfig();
  const endpoint = getEndpoint("workbenchRecognitionMediaIdentities");
  const url = new URL(endpoint, window.location.origin);

  mediaIds.forEach((id) => url.searchParams.append("media_ids[]", String(id)));

  return fetchApi(url.toString(), {
    method: "GET",
    restNonce: config.nonce,
  });
};

export const updateClusterLabel = async (
  clusterId: string,
  label: string
): Promise<void> => {
  const config = getConfig();
  const endpoint = getEndpoint("workbenchRecognitionClusters");
  const url = `${stripTrailingSlash(endpoint)}/${clusterId}`;

  await fetchApi(url, {
    method: "PATCH",
    body: { label },
    restNonce: config.nonce,
  });
};

export const mergeCluster = async (
  sourceId: string,
  targetLabel: string
): Promise<void> => {
  const config = getConfig();
  const endpoint = getEndpoint("workbenchRecognitionClusters");
  const url = `${stripTrailingSlash(endpoint)}/${sourceId}/merge`;

  await fetchApi(url, {
    method: "POST",
    body: { target_label: targetLabel },
    restNonce: config.nonce,
  });
};
```

Hook for identities:

```typescript
// js/admin/hooks/useMediaIdentities.ts

import { useQuery } from "@tanstack/react-query";
import {
  fetchMediaIdentities,
  type MediaIdentitiesResponse,
} from "../api/recognitionApi";

export const useMediaIdentities = (mediaIds: number[], enabled = true) =>
  useQuery<MediaIdentitiesResponse>({
    queryKey: ["media-identities", mediaIds],
    queryFn: () => fetchMediaIdentities(mediaIds),
    enabled: enabled && mediaIds.length > 0,
    staleTime: 60_000, // Cache for 1 minute
  });
```

### 3.3 Roster Autosuggest Hook

Provide a tenant-scoped roster search hook leveraged by the identity cluster editor:

```typescript
// js/admin/hooks/useRosterEntrySearch.ts

import { useQuery } from "@tanstack/react-query";
import { fetchRosterEntries } from "../api/recognitionApi";

export const useRosterEntrySearch = (term: string, enabled: boolean) =>
  useQuery({
    queryKey: ["roster-search", term],
    queryFn: () => fetchRosterEntries(term),
    enabled: enabled && term.trim().length > 0,
    staleTime: 5 * 60_000,
  });
```

### 3.4 Workbench Page Integration

Update `WorkbenchPage` to prefetch identities and invalidate on scan completion:

```typescript
// js/admin/pages/WorkbenchPage.tsx

import { useMediaIdentities } from '../hooks/useMediaIdentities';

export const WorkbenchPage = (): React.JSX.Element => {
  // ... existing state ...

  const mediaQuery = useWorkbenchMedia({
    page: currentPage,
    perPage: MEDIA_PAGE_SIZE,
    search: normalizedSearch,
    enabled: activeSection === TAB_IDS.scan,
  });

  const mediaData = mediaQuery.data;
  const mediaItems = mediaData?.items ?? [];
  const currentPageIds = mediaItems.map(item => item.id);

  // Prefetch next page IDs (if available) for smoother pagination
  const nextPageItems = mediaQuery.data?.nextPageItems ?? [];
  const nextPageIds = nextPageItems.map(item => item.id);
  const identityIdsToFetch = React.useMemo(() => [...currentPageIds, ...nextPageIds], [currentPageIds, nextPageIds]);

  // Prefetch identities for current + next page
  const identitiesQuery = useMediaIdentities(identityIdsToFetch, activeSection === TAB_IDS.scan);

  // ... existing mutations ...

  const scanMutation = useScanIdentities({
    onMutate: () => {
      setScanError(null);
    },
    onSuccess: (data) => {
      rememberJob(data.job_id);
      setClusterMessage(null);
      setActiveSection(TAB_IDS.confirm);
      // Invalidate identities cache to show new detections
      queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : __('Recognition job failed. Please try again.', 'alt-context');
      setScanError(message);
    },
  });

  // Invalidate identities when scan completes
  React.useEffect(() => {
    if (scanStatusQuery.data?.status === 'completed') {
      queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    }
  }, [scanStatusQuery.data?.status, queryClient]);

  // TODO: subscribe to recognition SSE/WebSocket stream to push identity updates without waiting for polling.

  // Merge identities into media items
  const mediaWithIdentities = React.useMemo(() => {
    const identitiesByMedia = identitiesQuery.data?.identities_by_media ?? {};
    return mediaItems.map(item => ({
      ...item,
      identities: identitiesByMedia[String(item.id)] ?? [],
    }));
  }, [mediaItems, identitiesQuery.data]);

  return (
    // ... pass mediaWithIdentities to MediaSelection ...
  );
};
```

### 3.5 MediaSelection Updates

Extend `MediaSelection` to render identity clusters in the details cell:

```typescript
// js/admin/pages/workbench/MediaSelection.tsx

import { IdentityClusterList } from "./IdentityClusterList";

const renderRows = ({
  items,
  isLoading,
  onToggleRow,
  selection,
}: {
  items: WorkbenchMediaItem[];
  // ... existing props
}) => {
  // ... existing logic ...

  return items.map((item) => {
    const key = item.id.toString();
    return (
      <tr key={key}>
        {/* ... checkbox and thumbnail cells ... */}
        <td className="acx-media-selection__details">
          <a href={mediaEditUrl(item.id)} className="acx-media-selection__link">
            <p className="acx-media-selection__media-title">{item.title}</p>
            <p className="acx-media-selection__media-alt">
              {item.altText ?? __("No alt text yet", "alt-context")}
            </p>
          </a>
          {item.identities && item.identities.length > 0 && (
            <IdentityClusterList
              identities={item.identities}
              mediaId={item.id}
            />
          )}
        </td>
        {/* ... tags cell ... */}
      </tr>
    );
  });
};
```

### 3.6 IdentityClusterList Component

Create a new component to show cluster thumbnails and name prompts:

```typescript
// js/admin/pages/workbench/IdentityClusterList.tsx

import React from "react";
import { __, sprintf } from "@wordpress/i18n";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mergeCluster, updateClusterLabel } from "../../api/recognitionApi";
import type { DetectedIdentity } from "../../hooks/useWorkbenchMedia";

type Props = {
  identities: DetectedIdentity[];
  mediaId: number;
};

export const IdentityClusterList = ({
  identities,
  mediaId,
}: Props): React.JSX.Element => {
  // Group identities by cluster
  const clusterGroups = React.useMemo(() => {
    const groups = new Map<string, DetectedIdentity[]>();
    identities.forEach((identity) => {
      const key = identity.clusterId ?? "unclustered";
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key)!.push(identity);
    });
    return Array.from(groups.entries());
  }, [identities]);

  return (
    <div className="acx-identity-clusters">
      {clusterGroups.map(([clusterId, clusterIdentities]) => (
        <IdentityClusterItem
          key={clusterId}
          clusterId={clusterId}
          identities={clusterIdentities}
          mediaId={mediaId}
        />
      ))}
    </div>
  );
};

type IdentityClusterItemProps = {
  clusterId: string;
  identities: DetectedIdentity[];
  mediaId: number;
};

const IdentityClusterItem = ({
  clusterId,
  identities,
  mediaId,
}: IdentityClusterItemProps): React.JSX.Element => {
  const [isEditing, setIsEditing] = React.useState(false);
  const [labelInput, setLabelInput] = React.useState("");
  const [showOverlay, setShowOverlay] = React.useState(false);
  const [selectedRoster, setSelectedRoster] =
    React.useState<RosterOption | null>(null);
  const { data: rosterOptions } = useRosterEntrySearch(labelInput, isEditing);
  const queryClient = useQueryClient();

  const firstIdentity = identities[0];
  const isAutoLabel = firstIdentity?.isAutoLabel ?? false;
  const currentLabel =
    firstIdentity?.clusterLabel ?? __("Unknown", "alt-context");

  const updateMutation = useMutation({
    mutationFn: (label: string) => updateClusterLabel(clusterId, label),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["media-identities"] });
      setIsEditing(false);
    },
  });

  const mergeMutation = useMutation({
    mutationFn: (targetLabel: string) => mergeCluster(clusterId, targetLabel),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["media-identities"] });
      setIsEditing(false);
    },
  });

  const handleSubmit = () => {
    const label = selectedRoster?.label ?? labelInput.trim();
    if (!label) return;

    // Prefer existing roster selection; otherwise merge into freshly named cluster
    if (isAutoLabel) {
      mergeMutation.mutate(label);
    } else {
      updateMutation.mutate(label);
    }
  };

  return (
    <div className="acx-identity-cluster">
      <div
        className="acx-identity-cluster__preview"
        onMouseEnter={() => setShowOverlay(true)}
        onMouseLeave={() => setShowOverlay(false)}
      >
        {/* Show first identity as representative thumbnail */}
        <img
          src={firstIdentity.thumbnailUrl ?? ""}
          alt={sprintf(__("Identity from %s", "alt-context"), currentLabel)}
          className="acx-identity-cluster__thumb"
        />
        {showOverlay && (
          <span
            className="acx-identity-cluster__overlay"
            style={
              {
                "--bbox-top": `${firstIdentity.bbox.y}px`,
                "--bbox-left": `${firstIdentity.bbox.x}px`,
                "--bbox-width": `${firstIdentity.bbox.width}px`,
                "--bbox-height": `${firstIdentity.bbox.height}px`,
              } as React.CSSProperties
            }
          />
        )}
        {identities.length > 1 && (
          <span className="acx-identity-cluster__count">
            +{identities.length - 1}
          </span>
        )}
      </div>

      <div className="acx-identity-cluster__info">
        {!isEditing ? (
          <>
            <span className="acx-identity-cluster__label">{currentLabel}</span>
            {isAutoLabel && !selectedRoster && (
              <button
                type="button"
                className="acx-identity-cluster__name-btn"
                onClick={() => setIsEditing(true)}
              >
                {__("Name this person", "alt-context")}
              </button>
            )}
          </>
        ) : (
          <div className="acx-identity-cluster__edit">
            <AutosuggestInput
              value={labelInput}
              onChange={(value, option) => {
                setLabelInput(value);
                setSelectedRoster(option ?? null);
              }}
              options={rosterOptions}
              placeholder={__("Search roster…", "alt-context")}
            />
            <button
              type="button"
              onClick={handleSubmit}
              disabled={updateMutation.isPending || mergeMutation.isPending}
              className="acx-identity-cluster__save"
            >
              {__("Save", "alt-context")}
            </button>
            <button
              type="button"
              onClick={() => setIsEditing(false)}
              className="acx-identity-cluster__cancel"
            >
              {__("Cancel", "alt-context")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
```

### 3.6 Styles

Add SCSS for identity cluster inline display:

```scss
// js/admin/styles/components/_media-selection.scss

.acx-identity-clusters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.acx-identity-cluster {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.5rem;
  background: var(--color-suridentity);
  border: 1px solid var(--color-border);
  border-radius: 0.25rem;

  &__preview {
    position: relative;
  }

  &__overlay {
    position: absolute;
    inset: 0;
    pointer-events: none;

    &::after {
      content: "";
      position: absolute;
      border: 2px solid var(--color-primary);
      border-radius: 0.25rem;
      top: var(--bbox-top, 0);
      left: var(--bbox-left, 0);
      width: var(--bbox-width, 100%);
      height: var(--bbox-height, 100%);
    }
  }

  &__thumb {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    object-fit: cover;
  }

  &__count {
    position: absolute;
    bottom: -2px;
    right: -2px;
    background: var(--color-primary);
    color: white;
    font-size: 0.625rem;
    padding: 0 0.25rem;
    border-radius: 0.25rem;
  }

  &__info {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  &__label {
    font-size: 0.875rem;
    font-weight: 500;
  }

  &__name-btn {
    font-size: 0.75rem;
    color: var(--color-primary);
    text-decoration: underline;
    background: none;
    border: none;
    cursor: pointer;

    &:hover {
      color: var(--color-primary-hover);
    }
  }

  &__edit {
    display: flex;
    gap: 0.25rem;
  }

  &__input {
    padding: 0.125rem 0.25rem;
    font-size: 0.875rem;
    border: 1px solid var(--color-border);
    border-radius: 0.25rem;
  }

  &__save,
  &__cancel {
    padding: 0.125rem 0.5rem;
    font-size: 0.75rem;
    border: 1px solid var(--color-border);
    border-radius: 0.25rem;
    cursor: pointer;
  }

  &__save {
    background: var(--color-primary);
    color: white;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  &__cancel {
    background: var(--color-suridentity);
  }
}
```

---

## Part 4: Implementation Sequence

1. **Backend Schema** (1 day)

   - Add `is_deleted` to `IdentityCluster`, create migration
   - Deploy and test locally

2. **Backend Endpoints** (2 days)

   - Implement `GET /recognition/media/identities`
   - Implement `PATCH /recognition/clusters/{id}`
   - Implement `POST /recognition/clusters/{id}/merge`
   - Add auto-merge service method
   - Write integration tests

3. **WordPress Proxy** (1 day)

   - Extend `RecognitionProxyController` with new routes
   - Update admin localization
   - Test proxy forwarding

4. **Frontend Types & API** (1 day)

   - [x] Update `WorkbenchMediaItem` type
   - [x] Add API functions for identities, label update, merge
   - [x] Create `useMediaIdentities` hook

5. **Workbench Integration** (2 days)

   - [x] Wire identity fetching into `WorkbenchPage`
   - [x] Invalidate caches on scan completion
   - [x] Add prefetching for next page

6. **IdentityClusterList Component** (2 days)

   - [x] Build cluster grouping display
   - [x] Implement inline edit UI
   - [x] Wire mutations for label update/merge
   - [x] Add SCSS styles

7. **Testing & QA** (2 days)
   - Manual workflow testing (scan → name → merge)
   - Cross-page navigation caching
   - Error handling and edge cases
   - Performance profiling (large media lists)

**Total estimate**: 11 days

---

## Part 5: Testing Checklist

### Backend

- [x] Identities endpoint returns correct bbox and cluster data
- [x] Label update enforces uniqueness per tenant
- [x] Merge creates new cluster if target doesn't exist
- [x] Merge moves all members and updates counts
- [x] Auto-merge consolidates similar clusters

### Frontend

- [x] Identities load when table renders
- [x] Identity clusters display grouped by label
- [x] "Name this person" opens edit input
- [x] Label update propagates immediately
- [x] Merge combines clusters under new label
- [x] Scan completion refreshes identity data
- [x] Pagination doesn't break identity associations
- [x] Loading/error states render correctly

### Integration

- [x] End-to-end flow: scan → identities appear → rename → verify
- [x] Multi-page prefetching works
- [x] Cache invalidation on mutations
- [x] Nonce/auth validation

- [x] Tenant isolation enforced

---

## Part 6: Future Enhancements

- **Typeahead search** for existing cluster labels (roster integration)
- **Bounding box overlays** on hover/toggle
- **Batch renaming** for multiple clusters
- **Confidence threshold filtering** in UI
- **SSE/WebSocket** for real-time scan progress
- **Cluster similarity visualization** (dendrograms, heatmaps)
- **Export/import** curated labels for backup/migration

---

## References

- [workbench-cluster-editing-plan.md](workbench-cluster-editing-plan.md)
- [face-scan-implementation-guide.md](face-scan-implementation-guide.md)
- Archived service: `apps/archived-wp-context-alt-text/src/Domain/Clustering/ClusteringService.php` (lines 582-651)
