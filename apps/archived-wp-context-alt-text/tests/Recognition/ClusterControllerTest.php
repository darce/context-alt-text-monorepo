<?php

declare(strict_types=1);

use ContextAltText\Recognition\ClusterController;
use ContextAltText\Recognition\FaceThumbnailProvider;
use ContextAltText\Security\Security;
use ContextAltText\Infrastructure\Repositories\UnknownFaceRepository;
use ContextAltText\Infrastructure\Repositories\UnknownFaceRepositoryInterface;
use ContextAltText\Domain\Clustering\UnknownFace;
use PHPUnit\Framework\TestCase;
use ContextAltText\Domain\Clustering\ClusteringEngine;

require_once __DIR__ . '/../bootstrap.php';

final class ClusterControllerTest extends TestCase
{
    /** @var \PHPUnit\Framework\MockObject\MockObject&Security */
    private Security $security;
    private FakeClusteringService $clusteringService;
    private FakeThumbnailProvider $thumbnailProvider;
    private FakeUnknownFaceRepository $repository;
    private ClusterController $controller;

    protected function setUp(): void
    {
        parent::setUp();

        $this->security = $this->createMock(Security::class);
        $this->clusteringService = new FakeClusteringService();
        $this->thumbnailProvider = new FakeThumbnailProvider();
        $this->repository = new FakeUnknownFaceRepository();
        $this->controller = new ClusterController(
            $this->security,
            $this->clusteringService,
            $this->thumbnailProvider,
            $this->repository
        );
    }

    public function test_returns_error_when_user_lacks_capability(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(false);

        $request = new WP_REST_Request('GET', '/cat/v1/clusters');
        $response = $this->controller->listClusters($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('rest_forbidden', $response->get_error_code());
    }

    public function test_returns_cluster_payload_with_sample_face(): void
    {
        // Arrange
        $this->repository->clusterSummaries = [
            [
                'cluster_id' => 'cluster-123',
                'face_count' => 2,
                'created_at' => '2024-01-01 10:00:00',
                'updated_at' => '2024-01-02 10:00:00',
                'preview_face_ids' => ['face-1', 'face-2'],
            ],
        ];

        $this->repository->faces = [
            $this->createFaceStub(1, 1, 'cluster-123', '2024-01-01 10:00:00'),
        ];
        $this->repository->totalClusters = 1;

        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $request = new WP_REST_Request('GET', '/cat/v1/clusters');
        $request->set_param('per_page', 50);

        // Act
        $response = $this->controller->listClusters($request);

        // Assert
        $this->assertIsArray($response);
        $this->assertArrayHasKey('clusters', $response);
        $this->assertCount(1, $response['clusters']);
    }

    public function test_honors_pagination_params(): void
    {
        // Arrange - setup multiple clusters
        $this->repository->clusterSummaries = [
            [
                'cluster_id' => 'cluster-1',
                'face_count' => 1,
                'created_at' => '2024-01-01 10:00:00',
                'updated_at' => '2024-01-01 10:00:00',
                'preview_face_ids' => ['face-1'],
            ],
        ];

        $this->repository->faces = [
            $this->createFaceStub(1, 1, 'cluster-1', '2024-01-01 10:00:00'),
        ];
        $this->repository->totalClusters = 1;

        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $request = new WP_REST_Request('GET', '/cat/v1/clusters');
        $request->set_param('per_page', 1);

        // Act
        $response = $this->controller->listClusters($request);

        // Assert
        $this->assertIsArray($response);
        $this->assertArrayHasKey('clusters', $response);
        $this->assertCount(1, $response['clusters']);
    }

    public function test_get_cluster_suggestions_requires_capability(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(false);

        $request = new WP_REST_Request('GET', '/cat/v1/clusters/cluster-alpha/suggestions');
        $request->set_param('id', 'cluster-alpha');

        $response = $this->controller->getClusterSuggestions($request);
        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('rest_forbidden', $response->get_error_code());
    }

    public function test_get_cluster_suggestions_returns_payload(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $request = new WP_REST_Request('GET', '/cat/v1/clusters/cluster-alpha/suggestions');
        $request->set_param('id', 'cluster-alpha');

        $suggestions = $this->controller->getClusterSuggestions($request);

        $this->assertIsArray($suggestions);
        $this->assertSame('cluster-alpha', $suggestions['cluster_id']);
        $this->assertCount(1, $suggestions['suggestions']);
        $this->assertSame('person-001', $suggestions['suggestions'][0]['roster_id']);
        $this->assertSame('cluster-alpha', $this->clusteringService->lastSuggestionsClusterId);
    }

    public function test_confirm_cluster_requires_capability(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(false);

        $request = new WP_REST_Request('POST', '/cat/v1/clusters/cluster-alpha/confirm');
        $request->set_param('id', 'cluster-alpha');

        $response = $this->controller->confirmCluster($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('rest_forbidden', $response->get_error_code());
    }

    public function test_confirm_cluster_returns_confirmation_payload(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $request = new WP_REST_Request('POST', '/cat/v1/clusters/cluster-alpha/confirm');
        $request->set_param('id', 'cluster-alpha');
        $request->set_param('roster_id', 'person-002');
        $request->set_param('face_ids', ['face-1', 'face-2']);

        $response = $this->controller->confirmCluster($request);

        $this->assertIsArray($response);
        $this->assertSame(2, $response['labeled_count']);
        $this->assertSame('person-002', $response['roster_id']);
        $this->assertSame('cluster-alpha', $this->clusteringService->lastConfirmation['cluster_id'] ?? null);
        $this->assertSame(['face-1', 'face-2'], $this->clusteringService->lastConfirmation['face_ids'] ?? []);
    }

    // Phase 2: New tests for lightweight cluster summaries

    public function test_listClusters_returns_lightweight_summaries(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Setup fake repository data
        $this->repository->clusterSummaries = [
            [
                'cluster_id' => 'cluster-001',
                'face_count' => 5,
                'created_at' => '2024-10-10 10:00:00',
                'updated_at' => '2024-10-11 12:00:00',
                'preview_face_ids' => [1, 2, 3, 4],
            ],
        ];

        $this->repository->totalClusters = 1;

        $this->repository->faces = [
            $this->createFaceStub(1, 101, 'cluster-001', '2024-10-10 10:00:00'),
            $this->createFaceStub(2, 102, 'cluster-001', '2024-10-10 11:00:00'),
            $this->createFaceStub(3, 103, 'cluster-001', '2024-10-10 12:00:00'),
            $this->createFaceStub(4, 104, 'cluster-001', '2024-10-10 13:00:00'),
        ];

        $request = new WP_REST_Request('GET', '/cat/v1/clusters');
        $request->set_param('per_page', 50);
        $response = $this->controller->listClusters($request);

        $this->assertIsArray($response);
        $this->assertArrayHasKey('clusters', $response);
        $this->assertCount(1, $response['clusters']);

        $cluster = $response['clusters'][0];
        $this->assertSame('cluster-001', $cluster['id']);
        $this->assertSame(5, $cluster['face_count']);
        $this->assertArrayHasKey('preview_faces', $cluster);
        $this->assertCount(4, $cluster['preview_faces']);
    }

    public function test_listClusters_excludes_embedding_vectors_from_preview(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Setup fake repository data
        $this->repository->clusterSummaries = [
            [
                'cluster_id' => 'cluster-001',
                'face_count' => 2,
                'created_at' => '2024-10-10 10:00:00',
                'updated_at' => '2024-10-11 12:00:00',
                'preview_face_ids' => [1, 2],
            ],
        ];

        $this->repository->totalClusters = 1;

        $this->repository->faces = [
            $this->createFaceStub(1, 101, 'cluster-001', '2024-10-10 10:00:00'),
            $this->createFaceStub(2, 102, 'cluster-001', '2024-10-10 11:00:00'),
        ];

        $request = new WP_REST_Request('GET', '/cat/v1/clusters');
        $response = $this->controller->listClusters($request);

        $previewFaces = $response['clusters'][0]['preview_faces'];
        $this->assertCount(2, $previewFaces);

        // Verify embedding_id is not included in preview faces
        foreach ($previewFaces as $face) {
            $this->assertArrayNotHasKey('embedding_id', $face);
            $this->assertArrayHasKey('id', $face);
            $this->assertArrayHasKey('attachment_id', $face);
            $this->assertArrayHasKey('thumbnail_url', $face);
        }
    }

    public function test_getClusterDetailPage_returns_paginated_faces(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Setup fake repository data
        $this->repository->facesPage = [
            'faces' => [
                $this->createFaceStub(21, 121, 'cluster-001', '2024-10-10 10:00:00'),
                $this->createFaceStub(22, 122, 'cluster-001', '2024-10-10 11:00:00'),
            ],
            'total' => 25,
            'page' => 2,
            'per_page' => 20,
        ];

        $request = new WP_REST_Request('GET', '/cat/v1/clusters/cluster-001');
        $request->set_param('id', 'cluster-001');
        $request->set_param('page', 2);

        $response = $this->controller->getClusterDetailPage($request);

        $this->assertIsArray($response);
        $this->assertArrayHasKey('faces', $response);
        $this->assertCount(2, $response['faces']);
        $this->assertArrayHasKey('pagination', $response);
        $this->assertSame(25, $response['pagination']['total_faces']);
        $this->assertSame(2, $response['pagination']['current_page']);
        $this->assertFalse($response['pagination']['has_more']);
    }

    public function test_getClusterDetailPage_includes_full_face_data(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Setup fake repository data
        $this->repository->facesPage = [
            'faces' => [
                $this->createFaceStub(1, 101, 'cluster-001', '2024-10-10 10:00:00'),
            ],
            'total' => 1,
            'page' => 1,
            'per_page' => 20,
        ];

        $request = new WP_REST_Request('GET', '/cat/v1/clusters/cluster-001');
        $request->set_param('id', 'cluster-001');

        $response = $this->controller->getClusterDetailPage($request);

        $responseFace = $response['faces'][0];

        // Verify embedding_id IS included for detail view
        $this->assertArrayHasKey('embedding_id', $responseFace);
        $this->assertArrayHasKey('id', $responseFace);
        $this->assertArrayHasKey('attachment_id', $responseFace);
        $this->assertArrayHasKey('thumbnail_url', $responseFace);
        $this->assertArrayHasKey('bbox', $responseFace);
    }

    public function test_getClusterDetailPage_returns_nested_pagination_structure(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $this->repository->facesPage = [
            'faces' => [
                $this->createFaceStub(1, 101, 'cluster-001', '2024-10-10 10:00:00'),
                $this->createFaceStub(2, 102, 'cluster-001', '2024-10-10 11:00:00'),
            ],
            'total' => 42,
            'page' => 2,
            'per_page' => 20,
        ];

        $request = new WP_REST_Request('GET', '/cat/v1/clusters/cluster-001');
        $request->set_param('id', 'cluster-001');
        $request->set_param('page', 2);
        $request->set_param('per_page', 20);

        $response = $this->controller->getClusterDetailPage($request);

        // Verify pagination is nested object, not flat structure
        $this->assertArrayHasKey('pagination', $response);
        $this->assertIsArray($response['pagination']);
        
        // Verify all pagination fields are present
        $pagination = $response['pagination'];
        $this->assertArrayHasKey('current_page', $pagination);
        $this->assertArrayHasKey('per_page', $pagination);
        $this->assertArrayHasKey('total_pages', $pagination);
        $this->assertArrayHasKey('total_faces', $pagination);
        $this->assertArrayHasKey('has_more', $pagination);
        
        // Verify calculated values are correct
        $this->assertSame(2, $pagination['current_page']);
        $this->assertSame(20, $pagination['per_page']);
        $this->assertSame(3, $pagination['total_pages']); // ceil(42/20) = 3
        $this->assertSame(42, $pagination['total_faces']);
        $this->assertTrue($pagination['has_more']); // page 2 of 3
    }

    public function test_getClusterDetailPage_calculates_has_more_correctly_on_last_page(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $this->repository->facesPage = [
            'faces' => [
                $this->createFaceStub(1, 101, 'cluster-001', '2024-10-10 10:00:00'),
                $this->createFaceStub(2, 102, 'cluster-001', '2024-10-10 11:00:00'),
            ],
            'total' => 22,
            'page' => 2,
            'per_page' => 20,
        ];

        $request = new WP_REST_Request('GET', '/cat/v1/clusters/cluster-001');
        $request->set_param('id', 'cluster-001');
        $request->set_param('page', 2);

        $response = $this->controller->getClusterDetailPage($request);

        $pagination = $response['pagination'];
        $this->assertSame(2, $pagination['total_pages']); // ceil(22/20) = 2
        $this->assertFalse($pagination['has_more']); // page 2 of 2, no more
    }

    public function test_listClusters_passes_thumbnail_data_to_provider(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $this->repository->clusterSummaries = [
            [
                'cluster_id' => 'cluster-123',
                'face_count' => 1,
                'created_at' => '2024-01-01 10:00:00',
                'updated_at' => '2024-01-02 10:00:00',
                'preview_face_ids' => [1],
            ],
        ];

        $this->repository->faces = [
            $this->createFaceStub(1, 101, 'cluster-123', '2024-01-01 10:00:00'),
        ];
        $this->repository->totalClusters = 1;

        $request = new WP_REST_Request('GET', '/cat/v1/clusters');

        $response = $this->controller->listClusters($request);

        // Verify thumbnail provider was called with correct data structure including thumbnail
        $this->assertCount(1, $this->thumbnailProvider->requests);
        $lastCall = $this->thumbnailProvider->requests[0];
        $this->assertIsArray($lastCall);
        $this->assertArrayHasKey('thumbnail', $lastCall);
        $this->assertSame('base64thumbnaildata', $lastCall['thumbnail']);
        $this->assertArrayHasKey('id', $lastCall);
        $this->assertArrayHasKey('attachmentId', $lastCall);
        $this->assertArrayHasKey('bbox', $lastCall);
    }

    public function test_getClusterDetailPage_passes_thumbnail_data_to_provider(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $this->repository->facesPage = [
            'faces' => [
                $this->createFaceStub(1, 101, 'cluster-001', '2024-10-10 10:00:00'),
            ],
            'total' => 1,
            'page' => 1,
            'per_page' => 20,
        ];

        $request = new WP_REST_Request('GET', '/cat/v1/clusters/cluster-001');
        $request->set_param('id', 'cluster-001');

        $response = $this->controller->getClusterDetailPage($request);

        // Verify thumbnail provider received thumbnail data
        $this->assertCount(1, $this->thumbnailProvider->requests);
        $lastCall = $this->thumbnailProvider->requests[0];
        $this->assertIsArray($lastCall);
        $this->assertArrayHasKey('thumbnail', $lastCall);
        $this->assertSame('base64thumbnaildata', $lastCall['thumbnail']);
    }

    /**
     * Helper to create UnknownFace test doubles.
     */
    private function createFaceStub(
        int $id,
        int $attachmentId,
        string $clusterId,
        string $detectedAt
    ): object {
        return new class($id, $attachmentId, $clusterId, $detectedAt) {
            public function __construct(
                private int $id,
                private int $attachmentId,
                private string $clusterId,
                private string $detectedAt
            ) {
            }

            public function id(): int
            {
                return $this->id;
            }

            public function attachmentId(): int
            {
                return $this->attachmentId;
            }

            public function clusterId(): string
            {
                return $this->clusterId;
            }

            public function detectedAt(): string
            {
                return $this->detectedAt;
            }

            public function resolvedAt(): ?string
            {
                return null;
            }

            public function rosterId(): ?string
            {
                return null;
            }

            public function embeddingId(): string
            {
                return "embedding-{$this->id}";
            }

            public function bbox(): array
            {
                return ['x' => 10, 'y' => 20, 'width' => 80, 'height' => 90];
            }

            public function thumbnail(): ?string
            {
                return 'base64thumbnaildata';
            }

            public function toArray(): array
            {
                return [
                    'id' => $this->id,
                    'attachment_id' => $this->attachmentId,
                    'cluster_id' => $this->clusterId,
                    'detected_at' => $this->detectedAt,
                    'resolved_at' => null,
                    'roster_id' => null,
                    'embedding_id' => $this->embeddingId(),
                    'bbox' => $this->bbox(),
                ];
            }
        };
    }
}

final class FakeClusteringService implements ClusteringEngine
{
    public ?string $lastDetailClusterId = null;
    public ?string $lastSuggestionsClusterId = null;
    /** @var array<string,mixed> */
    public array $detailResponse = [
        'cluster' => [
            'id' => 'cluster-alpha',
            'face_count' => 2,
            'created_at' => null,
            'updated_at' => null,
        ],
        'faces' => [],
    ];
    /** @var array<int,array<string,mixed>> */
    public array $suggestionResponse = [
        [
            'cluster_id' => 'cluster-alpha',
            'roster_id' => 'person-001',
            'display_name' => 'Jordan',
            'confidence' => 0.91,
            'confidence_level' => 'high',
            'match_count' => 2,
            'face_ids' => ['face-1', 'face-2'],
            'reason' => 'Mock suggestion payload',
        ],
    ];
    /** @var array<string,mixed>|null */
    public ?array $lastConfirmation = null;

    public function clusterUnknownFaces(array $faceIds = []): array
    {
        return [
            'strategy' => 'remote',
            'clusters' => [
                ['id' => 'cluster-alpha', 'faceIds' => [1, 2], 'size' => 2],
                ['id' => 'cluster-beta', 'faceIds' => [3], 'size' => 1],
            ],
            'faces' => [
                [
                    'id' => 'face-1',
                    'databaseId' => 1,
                    'attachmentId' => 101,
                    'bbox' => ['x' => 10, 'y' => 15, 'width' => 120, 'height' => 140],
                    'embeddingId' => 'embedding-1',
                    'clusterId' => 'cluster-alpha',
                    'detectedAt' => '2024-10-10T10:00:00+00:00',
                    'resolvedAt' => null,
                    'rosterId' => null,
                ],
                [
                    'id' => 'face-2',
                    'databaseId' => 2,
                    'attachmentId' => 102,
                    'bbox' => ['x' => 20, 'y' => 25, 'width' => 110, 'height' => 130],
                    'embeddingId' => 'embedding-2',
                    'clusterId' => 'cluster-alpha',
                    'detectedAt' => '2024-10-11T10:00:00+00:00',
                    'resolvedAt' => null,
                    'rosterId' => null,
                ],
                [
                    'id' => 'face-3',
                    'databaseId' => 3,
                    'attachmentId' => 103,
                    'bbox' => ['x' => 5, 'y' => 8, 'width' => 115, 'height' => 135],
                    'embeddingId' => 'embedding-3',
                    'clusterId' => 'cluster-beta',
                    'detectedAt' => '2024-10-12T10:00:00+00:00',
                    'resolvedAt' => null,
                    'rosterId' => null,
                ],
            ],
            'unclustered' => [],
        ];
    }

    public function getClusterDetail(string $clusterId): array
    {
        $this->lastDetailClusterId = $clusterId;
        return $this->detailResponse;
    }

    public function getClusterSuggestions(string $clusterId): array
    {
        $this->lastSuggestionsClusterId = $clusterId;

        return array_map(
            static function (array $suggestion) use ($clusterId): array {
                $suggestion['cluster_id'] = $clusterId;
                return $suggestion;
            },
            $this->suggestionResponse
        );
    }

    public function confirmCluster(string $clusterId, string $rosterId, array $faceIds): array
    {
        $this->lastConfirmation = [
            'cluster_id' => $clusterId,
            'roster_id' => $rosterId,
            'face_ids' => $faceIds,
        ];

        $confirmed = [];
        foreach ($faceIds as $faceId) {
            $confirmed[] = [
                'face_id' => (string) $faceId,
                'database_id' => is_numeric($faceId) ? (int) $faceId : null,
                'observation_id' => 123,
            ];
        }

        return [
            'cluster_id' => $clusterId,
            'roster_id' => $rosterId,
            'confirmed' => $confirmed,
            'labeled_count' => count($confirmed),
            'warnings' => [],
            'errors' => [],
            'cascade' => [
                'auto' => [],
                'candidates' => [],
            ],
        ];
    }
}

final class FakeThumbnailProvider implements FaceThumbnailProvider
{
    /** @var array<int,array<string,mixed>> */
    public array $requests = [];

    /**
     * @param array<string,mixed> $face
     */
    public function generateThumbnail(array $face): ?string
    {
        $this->requests[] = $face;

        return sprintf('https://example.test/crops/%s.jpg', $face['id'] ?? 'unknown');
    }
}

final class FakeUnknownFaceRepository implements UnknownFaceRepositoryInterface
{
    /** @var array<int,array<string,mixed>> */
    public array $clusterSummaries = [];

    /** @var array<int,array<string,mixed>> */
    public array $faces = [];

    /** @var array<string,mixed> Returned by findFacesPage */
    public array $facesPage = [];

    public int $totalClusters = 0;
    
    public int $totalFaces = 0;

    /**
     * @return array<int,array<string,mixed>>
     */
    public function findClusterSummaries(int $limit, int $offset): array
    {
        return array_slice($this->clusterSummaries, $offset, $limit);
    }

    /**
     * @param string $clusterId
     * @param int $page
     * @param int $perPage
     * @return array{faces: UnknownFace[], total: int, page: int, per_page: int}
     */
    public function findFacesPage(string $clusterId, int $page, int $perPage): array
    {
        // Return the pre-configured facesPage array
        return $this->facesPage;
    }

    public function countUnresolvedClusters(): int
    {
        return $this->totalClusters;
    }

    public function countUnresolvedFaces(): int
    {
        return $this->totalFaces;
    }

    /**
     * @param int[] $faceIds
     * @return UnknownFace[]
     */
    public function findFacesByIds(array $faceIds): array
    {
        return $this->faces;
    }

    /**
     * @return UnknownFace[]
     */
    public function findUnresolvedFaces(int $limit = 10000): array
    {
        return [];
    }

    /**
     * @return UnknownFace[]
     */
    public function findFacesByCluster(string $clusterId): array
    {
        return [];
    }

    public function findFaceById(int $faceId): ?UnknownFace
    {
        return null;
    }

    public function markFaceAsResolved(int $faceId, string $rosterId): bool
    {
        return true;
    }

    /**
     * @param int[] $faceIds
     */
    public function updateClusterMembership(array $faceIds, string $targetClusterId, int $userId): int
    {
        return count($faceIds);
    }

    public function softDeleteFace(int $faceId, int $userId): bool
    {
        return true;
    }

    public function clearAllUnresolvedFaces(int $userId): int
    {
        return $this->totalFaces;
    }
}
