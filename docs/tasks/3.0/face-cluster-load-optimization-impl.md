# Face Cluster Load Optimization - Implementation Guide

**Parent Document**: [face-cluster-load-optimization.md](./face-cluster-load-optimization.md)  
**Status**: [PLANNED]  
**Epic**: Workbench Performance & Scalability  
**Priority**: HIGH  
**Complexity**: Medium (3-5 day vertical slice)  
**Estimated Effort**: 16-24 hours

## Implementation Plan (TDD Approach - Option B)

This document provides detailed implementation steps following the project's TDD standards and architectural patterns from `docs/architecture/rules/instructions.md`.

---

### Phase 1: Repository Layer - Cluster Summary Queries [BACKEND]

**Goal**: Add lightweight read-model methods that return aggregate cluster data without loading full face records.

**Estimated Time**: 4-6 hours

#### Test Cases (PHPUnit)

**File**: `tests/Infrastructure/Repositories/UnknownFaceRepositoryTest.php`

Add these test methods after existing tests:

```php
public function test_findClusterSummaries_returns_aggregated_data(): void
{
    // Arrange: Insert 3 clusters with varying face counts
    $cluster1 = 'cluster-abc';
    $cluster2 = 'cluster-def';
    $cluster3 = 'cluster-ghi';

    $this->insertFace(['cluster_id' => $cluster1, 'detected_at' => '2025-01-01 10:00:00']);
    $this->insertFace(['cluster_id' => $cluster1, 'detected_at' => '2025-01-02 11:00:00']);
    $this->insertFace(['cluster_id' => $cluster2, 'detected_at' => '2025-01-03 12:00:00']);
    $this->insertFace(['cluster_id' => $cluster2, 'detected_at' => '2025-01-03 13:00:00']);
    $this->insertFace(['cluster_id' => $cluster2, 'detected_at' => '2025-01-03 14:00:00']);
    $this->insertFace(['cluster_id' => $cluster3, 'detected_at' => '2025-01-04 15:00:00']);

    // Act
    $summaries = $this->repository->findClusterSummaries(10, 0);

    // Assert
    $this->assertCount(3, $summaries);
    $this->assertSame($cluster1, $summaries[0]['cluster_id']);
    $this->assertSame(2, $summaries[0]['face_count']);
    $this->assertSame('2025-01-01 10:00:00', $summaries[0]['created_at']);
    $this->assertSame('2025-01-02 11:00:00', $summaries[0]['updated_at']);
    $this->assertCount(2, $summaries[0]['preview_face_ids']); // All faces fit in preview

    $this->assertSame(3, $summaries[1]['face_count']);
    $this->assertCount(3, $summaries[1]['preview_face_ids']); // Only 3 faces
}

public function test_findClusterSummaries_limits_preview_faces_to_four(): void
{
    // Arrange: Create cluster with 10 faces
    $clusterId = 'large-cluster';
    for ($i = 1; $i <= 10; $i++) {
        $this->insertFace(['cluster_id' => $clusterId, 'detected_at' => "2025-01-01 10:{$i}:00"]);
    }

    // Act
    $summaries = $this->repository->findClusterSummaries(10, 0);

    // Assert
    $this->assertCount(1, $summaries);
    $this->assertSame(10, $summaries[0]['face_count']);
    $this->assertCount(4, $summaries[0]['preview_face_ids']); // Capped at 4
}

public function test_findClusterSummaries_excludes_deleted_and_cleared(): void
{
    // Arrange
    $this->insertFace(['cluster_id' => 'visible', 'roster_id' => null]);
    $this->insertFace(['cluster_id' => 'deleted', 'roster_id' => '__deleted__']);
    $this->insertFace(['cluster_id' => 'cleared', 'roster_id' => '__cleared__']);

    // Act
    $summaries = $this->repository->findClusterSummaries(10, 0);

    // Assert
    $this->assertCount(1, $summaries);
    $this->assertSame('visible', $summaries[0]['cluster_id']);
}

public function test_findClusterSummaries_respects_pagination(): void
{
    // Arrange: Create 5 clusters
    for ($i = 1; $i <= 5; $i++) {
        $this->insertFace(['cluster_id' => "cluster-{$i}"]);
    }

    // Act: Request page 2 with 2 per page
    $summaries = $this->repository->findClusterSummaries(2, 2);

    // Assert: Should get clusters 3 and 4
    $this->assertCount(2, $summaries);
    $this->assertSame('cluster-3', $summaries[0]['cluster_id']);
    $this->assertSame('cluster-4', $summaries[1]['cluster_id']);
}

public function test_findFacesPage_returns_paginated_faces_for_cluster(): void
{
    // Arrange: Create cluster with 10 faces
    $clusterId = 'test-cluster';
    for ($i = 1; $i <= 10; $i++) {
        $this->insertFace([
            'cluster_id' => $clusterId,
            'detected_at' => "2025-01-01 10:{$i}:00",
            'attachment_id' => 100 + $i
        ]);
    }

    // Act: Request page 2 (faces 6-10) with 5 per page
    $result = $this->repository->findFacesPage($clusterId, 2, 5);

    // Assert
    $this->assertSame(10, $result['total']);
    $this->assertSame(2, $result['page']);
    $this->assertSame(5, $result['per_page']);
    $this->assertCount(5, $result['faces']);
    $this->assertSame(106, $result['faces'][0]->attachmentId()); // 6th face
}

public function test_countUnresolvedClusters_returns_accurate_count(): void
{
    // Arrange
    $this->insertFace(['cluster_id' => 'cluster-1', 'roster_id' => null]); // Unresolved
    $this->insertFace(['cluster_id' => 'cluster-1', 'roster_id' => null]); // Same cluster
    $this->insertFace(['cluster_id' => 'cluster-2', 'roster_id' => null]); // Different cluster
    $this->insertFace(['cluster_id' => 'cluster-3', 'roster_id' => 'person-123']); // Resolved

    // Act
    $count = $this->repository->countUnresolvedClusters();

    // Assert
    $this->assertSame(2, $count); // Only clusters 1 and 2
}
```

#### Production Code

**File**: `src/Infrastructure/Repositories/UnknownFaceRepository.php`

Add these methods after `findUnresolvedFaces()`:

```php
/**
 * Retrieve cluster summaries with aggregated metadata and limited preview face IDs.
 *
 * @param int $limit Maximum clusters to return
 * @param int $offset Pagination offset
 * @return array<int,array{cluster_id:string,face_count:int,created_at:string,updated_at:string,preview_face_ids:array<int>}>
 */
public function findClusterSummaries(int $limit, int $offset): array
{
    $this->ensureTableExists();
    $table = $this->tableName();

    // Use GROUP_CONCAT to get all face IDs, limit to 4 in application layer
    $sql = $this->wpdb->prepare(
        "SELECT
            cluster_id,
            COUNT(*) as face_count,
            MIN(detected_at) as created_at,
            MAX(detected_at) as updated_at,
            GROUP_CONCAT(id ORDER BY detected_at ASC) as all_face_ids
         FROM {$table}
         WHERE cluster_id IS NOT NULL
           AND resolved_at IS NULL
           AND (roster_id IS NULL OR roster_id NOT IN ('__deleted__', '__cleared__'))
         GROUP BY cluster_id
         ORDER BY MAX(detected_at) DESC
         LIMIT %d OFFSET %d",
        $limit,
        $offset
    );

    $rows = $this->wpdb->get_results($sql, \ARRAY_A);

    return array_map(function (array $row): array {
        $allIds = array_map('intval', explode(',', $row['all_face_ids']));
        $previewIds = array_slice($allIds, 0, 4); // Limit to 4 preview faces

        return [
            'cluster_id' => $row['cluster_id'],
            'face_count' => (int) $row['face_count'],
            'created_at' => $row['created_at'],
            'updated_at' => $row['updated_at'],
            'preview_face_ids' => $previewIds,
        ];
    }, $rows);
}

/**
 * Retrieve a paginated subset of faces within a specific cluster.
 *
 * @param string $clusterId Cluster identifier
 * @param int $page Page number (1-indexed)
 * @param int $perPage Faces per page
 * @return array{total:int,page:int,per_page:int,faces:UnknownFace[]}
 */
public function findFacesPage(string $clusterId, int $page, int $perPage): array
{
    $this->ensureTableExists();
    $table = $this->tableName();

    // Get total count
    $countSql = $this->wpdb->prepare(
        "SELECT COUNT(*) FROM {$table}
         WHERE cluster_id = %s
           AND resolved_at IS NULL
           AND (roster_id IS NULL OR roster_id NOT IN ('__deleted__', '__cleared__'))",
        $clusterId
    );
    $total = (int) $this->wpdb->get_var($countSql);

    // Get paginated faces
    $offset = ($page - 1) * $perPage;
    $facesSql = $this->wpdb->prepare(
        "SELECT * FROM {$table}
         WHERE cluster_id = %s
           AND resolved_at IS NULL
           AND (roster_id IS NULL OR roster_id NOT IN ('__deleted__', '__cleared__'))
         ORDER BY detected_at ASC
         LIMIT %d OFFSET %d",
        $clusterId,
        $perPage,
        $offset
    );

    $rows = $this->wpdb->get_results($facesSql, \ARRAY_A);
    $faces = array_map(fn(array $row) => $this->hydrate($row), $rows);

    return [
        'total' => $total,
        'page' => $page,
        'per_page' => $perPage,
        'faces' => $faces,
    ];
}

/**
 * Count total number of unresolved clusters.
 *
 * @return int
 */
public function countUnresolvedClusters(): int
{
    $this->ensureTableExists();
    $table = $this->tableName();

    $sql = "SELECT COUNT(DISTINCT cluster_id) FROM {$table}
            WHERE cluster_id IS NOT NULL
              AND resolved_at IS NULL
              AND (roster_id IS NULL OR roster_id NOT IN ('__deleted__', '__cleared__'))";

    return (int) $this->wpdb->get_var($sql);
}
```

#### Database Optimization

Add composite index to migration or activation hook:

```php
CREATE INDEX idx_cluster_pagination
ON wp_cat_unknown_faces(cluster_id, resolved_at, roster_id, detected_at);
```

This index supports:

- GROUP BY cluster_id aggregation
- WHERE filtered on resolved_at and roster_id
- ORDER BY detected_at sorting

**Expected Performance**: <50ms for 10,000 faces

---

### Phase 2: Controller Layer - Lightweight Endpoints [BACKEND]

**Goal**: Refactor `ClusterController::listClusters()` to return summaries and add paginated detail endpoint. Remove the old `getClusterDetail()` method entirely (greenfield policy - no production usage).

**Estimated Time**: 4-6 hours

#### Test Cases (PHPUnit)

**File**: `tests/Recognition/ClusterControllerTest.php`

```php
public function test_listClusters_returns_lightweight_summaries(): void
{
    // Arrange: Mock repository to return summaries
    $summaries = [
        [
            'cluster_id' => 'cluster-1',
            'face_count' => 5,
            'created_at' => '2025-01-01 10:00:00',
            'updated_at' => '2025-01-02 11:00:00',
            'preview_face_ids' => [1, 2, 3, 4],
        ],
    ];
    $this->repository->method('findClusterSummaries')->willReturn($summaries);
    $this->repository->method('findFacesByIds')->willReturn([$this->mockFace(1)]);

    // Act
    $request = new WP_REST_Request('GET', '/cat/v1/clusters');
    $response = $this->controller->listClusters($request);

    // Assert
    $this->assertIsArray($response);
    $this->assertCount(1, $response['clusters']);
    $this->assertSame('cluster-1', $response['clusters'][0]['id']);
    $this->assertSame(5, $response['clusters'][0]['face_count']);
    $this->assertArrayHasKey('preview_faces', $response['clusters'][0]);
    $this->assertCount(4, $response['clusters'][0]['preview_faces']);
}

public function test_listClusters_excludes_embedding_vectors_from_preview(): void
{
    // Arrange
    $summaries = [['cluster_id' => 'test', 'face_count' => 2, 'preview_face_ids' => [1, 2]]];
    $faces = [
        new UnknownFace(1, 123, ['x' => 10], 'emb-1', array_fill(0, 512, 0.1), 'thumb1', 'cluster-test'),
        new UnknownFace(2, 124, ['x' => 20], 'emb-2', array_fill(0, 512, 0.2), 'thumb2', 'cluster-test'),
    ];
    $this->repository->method('findClusterSummaries')->willReturn($summaries);
    $this->repository->method('findFacesByIds')->willReturn($faces);

    // Act
    $response = $this->controller->listClusters(new WP_REST_Request());

    // Assert
    $previewFaces = $response['clusters'][0]['preview_faces'];
    $this->assertArrayHasKey('thumbnail_url', $previewFaces[0]);
    $this->assertArrayHasKey('bbox', $previewFaces[0]);
    $this->assertArrayNotHasKey('embedding_vector', $previewFaces[0]); // Excluded
    $this->assertArrayNotHasKey('embedding_id', $previewFaces[0]); // Excluded
}

public function test_getClusterDetailPage_returns_paginated_faces(): void
{
    // Arrange
    $clusterId = 'test-cluster';
    $paginatedResult = [
        'total' => 10,
        'page' => 1,
        'per_page' => 5,
        'faces' => [$this->mockFace(1), $this->mockFace(2)],
    ];
    $this->repository->method('findFacesPage')->willReturn($paginatedResult);

    // Act
    $request = new WP_REST_Request('GET', "/cat/v1/clusters/{$clusterId}");
    $request->set_param('id', $clusterId);
    $request->set_param('page', 1);
    $request->set_param('per_page', 5);
    $response = $this->controller->getClusterDetailPage($request);

    // Assert
    $this->assertSame(10, $response['total']);
    $this->assertSame(1, $response['page']);
    $this->assertSame(5, $response['per_page']);
    $this->assertCount(2, $response['faces']);
}

public function test_getClusterDetailPage_includes_full_face_data(): void
{
    // Arrange
    $face = new UnknownFace(
        1, 123, ['x' => 10, 'y' => 20],
        'emb-1', array_fill(0, 512, 0.5),
        'base64thumb', 'test-cluster'
    );
    $this->repository->method('findFacesPage')->willReturn([
        'total' => 1, 'page' => 1, 'per_page' => 20, 'faces' => [$face]
    ]);

    // Act
    $response = $this->controller->getClusterDetailPage(new WP_REST_Request());

    // Assert
    $responseFace = $response['faces'][0];
    $this->assertArrayHasKey('thumbnail_url', $responseFace);
    $this->assertArrayHasKey('bbox', $responseFace);
    $this->assertArrayHasKey('embedding_id', $responseFace); // Included for detail view
}
```

#### Production Code

**File**: `src/Recognition/ClusterController.php`

**DELETE**: The existing `getClusterDetail()` method (no longer needed, replaced by paginated version)

**REPLACE**: The existing `listClusters()` method with this implementation:

```php
/**
 * Handle GET /cat/v1/clusters - returns lightweight cluster summaries.
 *
 * @return array<string,mixed>|WP_Error
 */
public function listClusters(WP_REST_Request $request)
{
    if (!$this->security->verifyCapability('upload_files')) {
        return new WP_Error(
            'rest_forbidden',
            __('You are not allowed to view face clusters.', 'context-alt-text'),
            ['status' => 403]
        );
    }

    $page = max(1, (int) ($request->get_param('page') ?? 1));
    $perPage = max(1, min(200, (int) ($request->get_param('per_page') ?? 50)));

    // Fetch lightweight summaries with preview face IDs
    $summaries = $this->repository->findClusterSummaries($perPage, ($page - 1) * $perPage);

    // Hydrate preview faces for each cluster (only 4 per cluster)
    $clusters = array_map(function (array $summary): array {
        $previewFaceIds = $summary['preview_face_ids'];
        $previewFaces = $this->repository->findFacesByIds($previewFaceIds);

        // Serialize with thumbnails but exclude heavy fields
        $serializedPreviews = array_map(function ($face): array {
            return [
                'id' => $face->id(),
                'attachment_id' => $face->attachmentId(),
                'bbox' => $face->bbox(),
                'thumbnail_url' => $this->thumbnailProvider->getThumbnailUrl($face),
            ];
        }, $previewFaces);

        // Sample face for card display
        $sampleFace = $previewFaces[0] ?? null;

        return [
            'id' => $summary['cluster_id'],
            'face_count' => $summary['face_count'],
            'created_at' => $summary['created_at'],
            'updated_at' => $summary['updated_at'],
            'sample_face' => $sampleFace ? [
                'attachment_id' => $sampleFace->attachmentId(),
                'thumbnail_url' => $this->thumbnailProvider->getThumbnailUrl($sampleFace),
                'bbox' => $sampleFace->bbox(),
            ] : null,
            'preview_faces' => $serializedPreviews,
        ];
    }, $summaries);

    // Get total count for pagination metadata
    $total = $this->repository->countUnresolvedClusters();

    return [
        'clusters' => $clusters,
        'total' => $total,
        'page' => $page,
        'per_page' => $perPage,
    ];
}

/**
 * Handle GET /cat/v1/clusters/{id} - returns paginated faces for a cluster.
 *
 * NOTE: This replaces the old getClusterDetail() method which loaded all faces at once.
 *
 * @return array<string,mixed>|WP_Error
 */
public function getClusterDetailPage(WP_REST_Request $request)
{
    if (!$this->security->verifyCapability('upload_files')) {
        return new WP_Error(
            'rest_forbidden',
            __('You are not allowed to view face clusters.', 'context-alt-text'),
            ['status' => 403]
        );
    }

    $clusterId = $request->get_param('id');
    $page = max(1, (int) ($request->get_param('page') ?? 1));
    $perPage = max(1, min(100, (int) ($request->get_param('per_page') ?? 20)));

    $result = $this->repository->findFacesPage($clusterId, $page, $perPage);

    // Serialize faces with full detail including thumbnails
    $serializedFaces = array_map(function ($face): array {
        return [
            'id' => $face->id(),
            'attachment_id' => $face->attachmentId(),
            'bbox' => $face->bbox(),
            'embedding_id' => $face->embeddingId(),
            'thumbnail_url' => $this->thumbnailProvider->getThumbnailUrl($face),
            'detected_at' => $face->detectedAt()->format('Y-m-d H:i:s'),
        ];
    }, $result['faces']);

    return [
        'cluster_id' => $clusterId,
        'total' => $result['total'],
        'page' => $result['page'],
        'per_page' => $result['per_page'],
        'faces' => $serializedFaces,
    ];
}
```

#### REST Route Registration

**File**: `src/Api/Api.php`

Update `registerRoutes()` method:

```php
// Existing summary endpoint (modified response structure)
$this->register_endpoint_with_alias(
    '/clusters',
    [
        'methods' => 'GET',
        'callback' => [$this->clusterController, 'listClusters'],
        'permission_callback' => '__return_true', // Security handled in controller
        'args' => [
            'page' => [
                'type' => 'integer',
                'default' => 1,
                'minimum' => 1,
            ],
            'per_page' => [
                'type' => 'integer',
                'default' => 50,
                'minimum' => 1,
                'maximum' => 200,
            ],
        ],
    ],
    'clusters'
);

// New paginated detail endpoint
$this->register_endpoint_with_alias(
    '/clusters/(?P<id>[a-zA-Z0-9\-]+)',
    [
        'methods' => 'GET',
        'callback' => [$this->clusterController, 'getClusterDetailPage'],
        'permission_callback' => '__return_true',
        'args' => [
            'id' => [
                'type' => 'string',
                'required' => true,
                'validate_callback' => function ($param) {
                    return is_string($param) && !empty($param);
                },
            ],
            'page' => [
                'type' => 'integer',
                'default' => 1,
                'minimum' => 1,
            ],
            'per_page' => [
                'type' => 'integer',
                'default' => 20,
                'minimum' => 1,
                'maximum' => 100,
            ],
        ],
    ],
    'cluster-detail'
);
```

---

### Phase 3: Frontend Layer - Prefetch & Pagination [FRONTEND]

**Goal**: Update React hooks to consume summary API and prefetch detail pages on drawer open.

**Estimated Time**: 4-6 hours

#### Test Cases (Vitest + React Testing Library)

**File**: `js/hooks/useClusterDetail.test.tsx` (new file)

```typescript
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { useClusterDetail } from "./useClusterDetail";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

const server = setupServer(
  http.get(
    "http://example.test/wp-json/cat/v1/clusters/:id",
    ({ params, request }) => {
      const url = new URL(request.url);
      const page = parseInt(url.searchParams.get("page") || "1");
      const perPage = parseInt(url.searchParams.get("per_page") || "20");

      return HttpResponse.json({
        cluster_id: params.id,
        total: 50,
        page,
        per_page: perPage,
        faces: Array.from(
          { length: Math.min(perPage, 50 - (page - 1) * perPage) },
          (_, i) => ({
            id: (page - 1) * perPage + i + 1,
            attachment_id: 100 + i,
            bbox: { x: 10, y: 20, width: 50, height: 60 },
            embedding_id: `emb-${i}`,
            thumbnail_url: `http://example.test/thumb-${i}.jpg`,
            detected_at: "2025-01-01 10:00:00",
          })
        ),
      });
    }
  )
);

beforeEach(() => {
  server.listen();
});

afterEach(() => {
  server.close();
});

describe("useClusterDetail", () => {
  it("fetches first page of cluster faces", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useClusterDetail("cluster-123"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.faces).toHaveLength(20);
    expect(result.current.total).toBe(50);
    expect(result.current.hasMore).toBe(true);
  });

  it("prefetches page 2 when page 1 loads", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const prefetchSpy = vi.spyOn(queryClient, "prefetchQuery");

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    renderHook(() => useClusterDetail("cluster-123"), { wrapper });

    await waitFor(() => {
      expect(prefetchSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: expect.arrayContaining(["clusterDetail", "cluster-123"]),
        })
      );
    });
  });

  it("loads next page when fetchNextPage is called", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useClusterDetail("cluster-123"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.fetchNextPage();

    await waitFor(() => {
      expect(result.current.faces).toHaveLength(40); // 20 + 20
    });
  });
});
```

**File**: `js/hooks/useUnknownClusters.test.tsx` (update existing tests)

Add this test case:

```typescript
it("receives lightweight cluster summaries with preview faces", async () => {
  server.use(
    http.get("http://example.test/wp-json/cat/v1/clusters", () => {
      return HttpResponse.json({
        clusters: [
          {
            id: "cluster-1",
            face_count: 25,
            created_at: "2025-01-01 10:00:00",
            updated_at: "2025-01-02 11:00:00",
            sample_face: {
              attachment_id: 123,
              thumbnail_url: "http://example.test/thumb.jpg",
              bbox: { x: 10, y: 20, width: 50, height: 60 },
            },
            preview_faces: [
              {
                id: 1,
                attachment_id: 123,
                thumbnail_url: "http://example.test/1.jpg",
                bbox: {},
              },
              {
                id: 2,
                attachment_id: 124,
                thumbnail_url: "http://example.test/2.jpg",
                bbox: {},
              },
              {
                id: 3,
                attachment_id: 125,
                thumbnail_url: "http://example.test/3.jpg",
                bbox: {},
              },
              {
                id: 4,
                attachment_id: 126,
                thumbnail_url: "http://example.test/4.jpg",
                bbox: {},
              },
            ],
          },
        ],
        total: 1,
        page: 1,
        per_page: 50,
      });
    })
  );

  const { result } = renderHook(() => useUnknownClusters(), {
    wrapper: createWrapper(),
  });

  await waitFor(() => expect(result.current.isLoading).toBe(false));

  expect(result.current.clusters).toHaveLength(1);
  expect(result.current.clusters[0].faceCount).toBe(25);
  expect(result.current.clusters[0].previewFaces).toHaveLength(4);
  expect(result.current.clusters[0].previewFaces[0]).not.toHaveProperty(
    "embeddingVector"
  );
});
```

#### Production Code

**File**: `js/hooks/useClusterDetail.ts` (new hook)

```typescript
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { catApi } from "@/lib/api";
import { useEffect } from "react";

interface ClusterDetailFace {
  id: number;
  attachment_id: number;
  bbox: { x: number; y: number; width: number; height: number };
  embedding_id: string;
  thumbnail_url: string;
  detected_at: string;
}

interface ClusterDetailResponse {
  cluster_id: string;
  total: number;
  page: number;
  per_page: number;
  faces: ClusterDetailFace[];
}

interface UseClusterDetailOptions {
  enabled?: boolean;
  prefetchNext?: boolean;
}

export const useClusterDetail = (
  clusterId: string,
  options: UseClusterDetailOptions = {}
) => {
  const queryClient = useQueryClient();
  const { enabled = true, prefetchNext = true } = options;

  const query = useInfiniteQuery({
    queryKey: ["clusterDetail", clusterId],
    queryFn: async ({ pageParam = 1 }) => {
      const response = await catApi.get<ClusterDetailResponse>(
        `/cat/v1/clusters/${clusterId}`,
        {
          params: { page: pageParam, per_page: 20 },
        }
      );
      return response.data;
    },
    enabled,
    getNextPageParam: (lastPage) => {
      const hasMore = lastPage.page * lastPage.per_page < lastPage.total;
      return hasMore ? lastPage.page + 1 : undefined;
    },
    initialPageParam: 1,
  });

  // Prefetch next page when current page loads
  useEffect(() => {
    if (!prefetchNext || !query.data || query.isFetchingNextPage) {
      return;
    }

    const lastPage = query.data.pages[query.data.pages.length - 1];
    const nextPage = lastPage.page + 1;
    const hasMore = lastPage.page * lastPage.per_page < lastPage.total;

    if (hasMore) {
      queryClient.prefetchQuery({
        queryKey: ["clusterDetail", clusterId, nextPage],
        queryFn: async () => {
          const response = await catApi.get<ClusterDetailResponse>(
            `/cat/v1/clusters/${clusterId}`,
            { params: { page: nextPage, per_page: 20 } }
          );
          return response.data;
        },
      });
    }
  }, [
    query.data,
    query.isFetchingNextPage,
    prefetchNext,
    queryClient,
    clusterId,
  ]);

  // Flatten all pages into single faces array
  const allFaces = query.data?.pages.flatMap((page) => page.faces) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;

  return {
    faces: allFaces,
    total,
    hasMore: query.hasNextPage,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
  };
};
```

**File**: `js/hooks/useUnknownClusters.ts` (update types and mapping)

Update the interface and query logic:

```typescript
export interface ClusterSummary {
  id: string;
  faceCount: number;
  createdAt: string;
  updatedAt: string;
  sampleFace: {
    attachmentId: number;
    thumbnailUrl: string;
    bbox: { x: number; y: number; width: number; height: number };
  } | null;
  previewFaces: Array<{
    id: number;
    attachmentId: number;
    thumbnailUrl: string;
    bbox: { x: number; y: number; width: number; height: number };
  }>;
}

// Update the query function:
const query = useQuery({
  queryKey: ["unknownClusters", { page, perPage }],
  queryFn: async () => {
    const response = await catApi.get<{
      clusters: Array<{
        id: string;
        face_count: number;
        created_at: string;
        updated_at: string;
        sample_face: {
          attachment_id: number;
          thumbnail_url: string;
          bbox: { x: number; y: number; width: number; height: number };
        } | null;
        preview_faces: Array<{
          id: number;
          attachment_id: number;
          thumbnail_url: string;
          bbox: { x: number; y: number; width: number; height: number };
        }>;
      }>;
      total: number;
      page: number;
      per_page: number;
    }>("/cat/v1/clusters", { params: { page, per_page: perPage } });

    return {
      clusters: response.data.clusters.map((c) => ({
        id: c.id,
        faceCount: c.face_count,
        createdAt: c.created_at,
        updatedAt: c.updated_at,
        sampleFace: c.sample_face
          ? {
              attachmentId: c.sample_face.attachment_id,
              thumbnailUrl: c.sample_face.thumbnail_url,
              bbox: c.sample_face.bbox,
            }
          : null,
        previewFaces: c.preview_faces.map((f) => ({
          id: f.id,
          attachmentId: f.attachment_id,
          thumbnailUrl: f.thumbnail_url,
          bbox: f.bbox,
        })),
      })),
      total: response.data.total,
    };
  },
});
```

**File**: `js/components/workbench/UnknownPeoplePanel.tsx` (update usage)

```typescript
import { useClusterDetail } from "@/hooks/useClusterDetail";

export const UnknownPeoplePanel = ({
  onFaceClick,
  onConfirmIdentity,
}: UnknownPeoplePanelProps): React.JSX.Element => {
  // Now requests 50 clusters with 4 preview faces each = ~200 face thumbnails max
  const { clusters, isLoading, error, total } = useUnknownClusters({
    perPage: 50,
  });
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null);

  // Load full cluster detail when drawer opens
  const clusterDetail = useClusterDetail(selectedCluster || "", {
    enabled: selectedCluster !== null,
    prefetchNext: true,
  });

  // ... rest of component logic

  return (
    <div>
      {/* Cluster cards showing preview faces */}
      {clusters.map((cluster) => (
        <ClusterCard
          key={cluster.id}
          cluster={cluster}
          onClick={() => setSelectedCluster(cluster.id)}
        />
      ))}

      {/* Detail drawer with paginated faces */}
      {selectedCluster && (
        <ClusterDetailDrawer
          clusterId={selectedCluster}
          faces={clusterDetail.faces}
          total={clusterDetail.total}
          hasMore={clusterDetail.hasMore}
          onLoadMore={clusterDetail.fetchNextPage}
          isLoadingMore={clusterDetail.isFetchingNextPage}
          onClose={() => setSelectedCluster(null)}
        />
      )}
    </div>
  );
};
```

---

### Phase 4: Cache Invalidation & Optimistic Updates [FRONTEND]

**Goal**: Ensure mutations (move, delete, clear) invalidate the right query keys.

**Estimated Time**: 2-3 hours

#### Test Cases (Vitest)

**File**: `js/hooks/useMoveFaces.test.tsx` (add to existing file)

```typescript
it("invalidates cluster summaries and detail cache after successful move", async () => {
  const queryClient = new QueryClient();
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  const { result } = renderHook(() => useMoveFaces(), { wrapper });

  await result.current.mutateAsync({
    faceIds: [1, 2],
    sourceClusterId: "cluster-old",
    targetClusterId: "cluster-new",
  });

  await waitFor(() => {
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["unknownClusters"],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["clusterDetail", "cluster-old"],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["clusterDetail", "cluster-new"],
    });
  });
});
```

#### Production Code

**File**: `js/hooks/useMoveFaces.ts` (update invalidation)

```typescript
export const useMoveFaces = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (params: MoveFacesParams) => {
      const response = await catApi.post(
        "/cat/v1/unknown-clusters/move",
        params
      );
      return response.data;
    },
    onSuccess: (_, variables) => {
      // Invalidate summary list (all pages)
      queryClient.invalidateQueries({ queryKey: ["unknownClusters"] });

      // Invalidate both source and target cluster details
      queryClient.invalidateQueries({
        queryKey: ["clusterDetail", variables.sourceClusterId],
      });
      queryClient.invalidateQueries({
        queryKey: ["clusterDetail", variables.targetClusterId],
      });
    },
  });
};
```

**File**: `js/hooks/useDeleteFace.ts` (update invalidation)

```typescript
export const useDeleteFace = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (faceId: number) => {
      const response = await catApi.delete(`/cat/v1/unknown-faces/${faceId}`);
      return response.data;
    },
    onSuccess: (data) => {
      // Invalidate summary list
      queryClient.invalidateQueries({ queryKey: ["unknownClusters"] });

      // Invalidate cluster detail if cluster_id is returned
      if (data.cluster_id) {
        queryClient.invalidateQueries({
          queryKey: ["clusterDetail", data.cluster_id],
        });
      }
    },
  });
};
```

**File**: `js/hooks/useClearAllFaces.ts` (update invalidation)

```typescript
export const useClearAllFaces = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const response = await catApi.post("/cat/v1/unknown-clusters/clear-all");
      return response.data;
    },
    onSuccess: () => {
      // Invalidate all cluster-related queries
      queryClient.invalidateQueries({ queryKey: ["unknownClusters"] });
      queryClient.invalidateQueries({ queryKey: ["clusterDetail"] });
    },
  });
};
```

---

### Phase 5: Background Clustering Job [BACKEND] (Optional)

**Goal**: Move incremental clustering to WP-Cron to avoid blocking UI requests.

**Estimated Time**: 2-4 hours

#### Test Cases (PHPUnit)

**File**: `tests/Domain/Clustering/IncrementalClusterJobTest.php` (new file)

```php
<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Domain\Clustering;

use ContextAltText\Domain\Clustering\IncrementalClusterJob;
use ContextAltText\Domain\Clustering\ClusteringEngine;
use ContextAltText\Infrastructure\Repositories\UnknownFaceRepository;
use PHPUnit\Framework\TestCase;

final class IncrementalClusterJobTest extends TestCase
{
    private ClusteringEngine $clusteringService;
    private UnknownFaceRepository $repository;
    private IncrementalClusterJob $job;

    protected function setUp(): void
    {
        $this->clusteringService = $this->createMock(ClusteringEngine::class);
        $this->repository = $this->createMock(UnknownFaceRepository::class);
        $this->job = new IncrementalClusterJob($this->clusteringService, $this->repository);
    }

    public function test_processUnclusteredFaces_only_clusters_null_cluster_id(): void
    {
        // Arrange
        $unclusteredIds = [1, 2, 3];
        $this->repository->method('findUnclusteredFaceIds')
            ->with(100)
            ->willReturn($unclusteredIds);

        $this->clusteringService->expects($this->once())
            ->method('clusterUnknownFaces')
            ->with($unclusteredIds);

        // Act
        $result = $this->job->processUnclusteredFaces(100);

        // Assert
        $this->assertSame(3, $result['processed']);
        $this->assertSame(0, $result['errors']);
        $this->assertFalse($result['has_more']);
    }

    public function test_processUnclusteredFaces_indicates_more_when_batch_full(): void
    {
        // Arrange: Exactly 100 faces returned = potentially more
        $unclusteredIds = range(1, 100);
        $this->repository->method('findUnclusteredFaceIds')
            ->with(100)
            ->willReturn($unclusteredIds);

        // Act
        $result = $this->job->processUnclusteredFaces(100);

        // Assert
        $this->assertSame(100, $result['processed']);
        $this->assertTrue($result['has_more']);
    }

    public function test_processUnclusteredFaces_handles_errors_gracefully(): void
    {
        // Arrange
        $unclusteredIds = [1, 2];
        $this->repository->method('findUnclusteredFaceIds')->willReturn($unclusteredIds);
        $this->clusteringService->method('clusterUnknownFaces')
            ->willThrowException(new \RuntimeException('Clustering failed'));

        // Act
        $result = $this->job->processUnclusteredFaces(100);

        // Assert
        $this->assertSame(0, $result['processed']);
        $this->assertSame(2, $result['errors']);
        $this->assertTrue($result['has_more']);
    }
}
```

#### Production Code

**File**: `src/Domain/Clustering/IncrementalClusterJob.php` (new class)

```php
<?php

declare(strict_types=1);

namespace ContextAltText\Domain\Clustering;

use ContextAltText\Infrastructure\Repositories\UnknownFaceRepository;
use Throwable;

/**
 * Background job for incrementally clustering new unresolved faces.
 */
final class IncrementalClusterJob
{
    private ClusteringEngine $clusteringService;
    private UnknownFaceRepository $repository;

    public function __construct(
        ClusteringEngine $clusteringService,
        UnknownFaceRepository $repository
    ) {
        $this->clusteringService = $clusteringService;
        $this->repository = $repository;
    }

    /**
     * Process a batch of unclustered faces.
     *
     * @param int $batchSize Maximum faces to process in this run
     * @return array{processed:int,errors:int,has_more:bool}
     */
    public function processUnclusteredFaces(int $batchSize): array
    {
        $unclusteredFaceIds = $this->repository->findUnclusteredFaceIds($batchSize);

        if ($unclusteredFaceIds === []) {
            return ['processed' => 0, 'errors' => 0, 'has_more' => false];
        }

        try {
            $this->clusteringService->clusterUnknownFaces($unclusteredFaceIds);

            return [
                'processed' => count($unclusteredFaceIds),
                'errors' => 0,
                'has_more' => count($unclusteredFaceIds) === $batchSize,
            ];
        } catch (Throwable $e) {
            error_log(sprintf('[IncrementalClusterJob] Error: %s', $e->getMessage()));

            return [
                'processed' => 0,
                'errors' => count($unclusteredFaceIds),
                'has_more' => true,
            ];
        }
    }
}
```

**File**: `src/Infrastructure/Repositories/UnknownFaceRepository.php` (add method)

```php
/**
 * Find IDs of faces that have not been assigned to a cluster yet.
 *
 * @param int $limit Maximum IDs to return
 * @return array<int>
 */
public function findUnclusteredFaceIds(int $limit): array
{
    $this->ensureTableExists();
    $table = $this->tableName();

    $sql = $this->wpdb->prepare(
        "SELECT id FROM {$table}
         WHERE cluster_id IS NULL
           AND resolved_at IS NULL
           AND (roster_id IS NULL OR roster_id NOT IN ('__deleted__', '__cleared__'))
         ORDER BY detected_at ASC
         LIMIT %d",
        $limit
    );

    $rows = $this->wpdb->get_col($sql);

    return array_map('intval', $rows);
}
```

**File**: `context-alt-text.php` (register WP-Cron hook)

```php
// In plugin activation or during bootstrap:
$incrementalClusterJob = new IncrementalClusterJob(
    $clusteringService,
    $unknownFaceRepository
);

// Register cron callback
add_action('cat_incremental_cluster', function () use ($incrementalClusterJob) {
    $result = $incrementalClusterJob->processUnclusteredFaces(100);
    error_log(sprintf(
        '[WP-Cron] Incremental cluster: %d processed, %d errors, has_more: %s',
        $result['processed'],
        $result['errors'],
        $result['has_more'] ? 'yes' : 'no'
    ));
});

// Schedule if not already scheduled
if (!wp_next_scheduled('cat_incremental_cluster')) {
    wp_schedule_event(time(), 'hourly', 'cat_incremental_cluster');
}
```

---

## Performance Targets

### Before Optimization (Current State)

- **Initial load**: 2-5 seconds
- **Payload size**: 60+ MB (all faces with embeddings)
- **Faces displayed**: Capped at 10,000 (but all loaded into memory)
- **Memory usage**: 256+ MB PHP
- **User experience**: Slow, unresponsive, high page load

### After Optimization (Expected)

- **Initial load**: <500ms
- **Payload size**: <100 KB (50 clusters x 4 preview faces)
- **Faces displayed**: All clusters, lazy-loaded details on demand
- **Memory usage**: <64 MB PHP
- **Detail drawer**: <200ms per page (20 faces)
- **User experience**: Instant cluster list, smooth drawer navigation

---

## Acceptance Criteria

### Backend

- [ ] `UnknownFaceRepository::findClusterSummaries()` returns aggregated data without full face hydration
- [ ] `UnknownFaceRepository::findFacesPage()` returns paginated faces for a cluster
- [ ] `UnknownFaceRepository::countUnresolvedClusters()` returns accurate count
- [ ] `ClusterController::listClusters()` returns summaries with max 4 preview faces per cluster
- [ ] New endpoint `GET /cat/v1/clusters/{id}?page=N` returns paginated face details
- [ ] Composite database index created for optimal query performance
- [ ] No embedding vectors in preview_faces (summary endpoint)
- [ ] Full thumbnails included in detail endpoint response
- [ ] Response time <500ms for summary endpoint with 100 clusters
- [ ] Response time <200ms for detail page endpoint with 20 faces

### Frontend

- [ ] `useClusterDetail` hook fetches paginated cluster faces
- [ ] `useClusterDetail` hook prefetches page 2 when page 1 loads
- [ ] `useUnknownClusters` hook updated to handle new response structure
- [ ] Drag-and-drop from detail drawer works with paginated faces
- [ ] Cache invalidation triggers on move/delete/clear mutations
- [ ] All preview faces render with thumbnails (no missing images)
- [ ] Detail drawer loads smoothly without blocking UI

### Testing

- [ ] All existing PHPUnit tests pass with updated contracts
- [ ] All existing Vitest tests pass with updated contracts
- [ ] New repository method tests cover edge cases (empty, pagination, filtering)
- [ ] New controller tests verify response structure and security
- [ ] New hook tests verify prefetching and pagination behavior

### Optional (Phase 5)

- [ ] Background WP-Cron job processes new unclustered faces
- [ ] `IncrementalClusterJob` has test coverage
- [ ] Cron job scheduled and logging properly

---

## Migration Notes

### Greenfield Reset Policy Applied

Per the project's [Greenfield Reset Policy](../architecture/rules/instructions.md#core-engineering-principles), this plugin has no production footprint. We can aggressively refactor without backward compatibility concerns.

### Changes to Existing Code

**REMOVE**: `ClusterController::getClusterDetail()` method entirely

- This method loads full cluster data on-demand but is inefficient for large clusters
- Replaced by new `getClusterDetailPage()` with pagination
- No production usage exists, so safe to delete immediately

**REPLACE**: `ClusterController::listClusters()` implementation

- Old: Calls `clusterUnknownFaces()` and returns all face data
- New: Calls `findClusterSummaries()` and returns lightweight previews
- Response structure changed (see below)

**KEEP**: `ClusteringService::clusterUnknownFaces()`

- Still needed for background clustering jobs (Phase 5)
- Will only process faces with `cluster_id IS NULL` (incremental mode)
- No longer called by UI endpoints

### API Response Structure Changes

**`GET /cat/v1/clusters`** (summary endpoint):

```diff
{
    "clusters": [
        {
            "id": "cluster-abc",
            "face_count": 25,
            "created_at": "2025-01-01 10:00:00",
            "updated_at": "2025-01-02 11:00:00",
            "sample_face": { /* simplified */ },
+           "preview_faces": [ /* max 4, no embeddings */ ],
-           "faces": [ /* removed - use detail endpoint */ ]
        }
    ],
    "total": 82,
    "page": 1,
    "per_page": 50
}
```

**`GET /cat/v1/clusters/{id}`** (new detail endpoint):

```json
{
  "cluster_id": "cluster-abc",
  "total": 25,
  "page": 1,
  "per_page": 20,
  "faces": [
    /* paginated, includes full data */
  ]
}
```

### Database Changes

**ADD**: Composite index for performance

```sql
CREATE INDEX idx_cluster_pagination
ON wp_cat_unknown_faces(cluster_id, resolved_at, roster_id, detected_at);
```

**NO SCHEMA CHANGES**: Table structure remains identical, only new index added

### Rollback Strategy

This is development work in a feature branch with no production deployment. If issues arise:

1. **Abandon the branch** and return to main branch
2. **Fix forward**: Debug and iterate on the feature branch
3. **No migration rollback needed**: No production data affected

Since this follows TDD, all tests must pass before merging. If tests fail, fix the implementation until green.

---

## Next Steps After Implementation

1. **Monitor Performance**: Use Query Monitor to track endpoint response times
2. **Optimize Queries**: If OFFSET/LIMIT becomes slow, consider cursor-based pagination (Option C)
3. **Add Caching**: Implement WordPress transient caching for cluster summaries (30s TTL)
4. **Virtual Scrolling**: If users have 200+ clusters, add infinite scroll to cluster list
5. **Background Jobs**: Enable WP-Cron clustering job for large datasets
6. **Update Documentation**: Add API endpoint docs to `docs/architecture/contracts/`

---

## References

- Parent Document: [face-cluster-load-optimization.md](./face-cluster-load-optimization.md)
- Drag-and-Drop Plan: [face-cluster-editing-plan.md](./face-cluster-editing-plan.md)
- Instructions: [docs/architecture/rules/instructions.md](../architecture/rules/instructions.md)
- Frontend UML: `docs/architecture/frontend-uml/face-clustering-components.mmd`

---

## Alignment Notes & Handover

- This implementation guide fully supersedes `docs/tasks/face-cluster-load-optimization.md`; once work starts, retire the parent document to avoid duplication.
- The plan reflects the Option B decision (summary endpoint + paged detail fetch) and the choice to keep thumbnails in the database. When wiring the controller, continue using `FaceThumbnailProvider::generateThumbnail()` so we keep the inline data-URI behaviour.
- Back-end work should include removing `FETCH_LIMIT` from `ClusteringService::loadFaces()` and replacing `findUnresolvedFaces($limit)` with the new read-model methods described above; these clean-ups were called out in the parent doc.
- Any future cursor-based pagination (Option C) can layer on top of this contract without breaking the API outlined here; add a new parameter rather than replacing the default OFFSET/LIMIT flow.
