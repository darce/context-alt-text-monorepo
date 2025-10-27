<?php

declare(strict_types=1);

use ContextAltText\Recognition\ClusterController;
use ContextAltText\Recognition\FaceThumbnailProvider;
use ContextAltText\Security\Security;
use PHPUnit\Framework\TestCase;
use ContextAltText\Domain\Clustering\ClusteringEngine;

require_once __DIR__ . '/../bootstrap.php';

final class ClusterControllerTest extends TestCase
{
    /** @var \PHPUnit\Framework\MockObject\MockObject&Security */
    private Security $security;
    private FakeClusteringService $clusteringService;
    private FakeThumbnailProvider $thumbnailProvider;
    private ClusterController $controller;

    protected function setUp(): void
    {
        parent::setUp();

        $this->security = $this->createMock(Security::class);
        $this->clusteringService = new FakeClusteringService();
        $this->thumbnailProvider = new FakeThumbnailProvider();
        $this->controller = new ClusterController(
            $this->security,
            $this->clusteringService,
            $this->thumbnailProvider
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
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $request = new WP_REST_Request('GET', '/cat/v1/clusters');
        $response = $this->controller->listClusters($request);

        $this->assertIsArray($response);
        $this->assertSame(2, $response['total']);
        $this->assertSame(1, $response['page']);
        $this->assertSame(20, $response['per_page']);

        $clusters = $response['clusters'];
        $this->assertCount(2, $clusters);

        $firstCluster = $clusters[0];
        $this->assertSame('cluster-alpha', $firstCluster['id']);
        $this->assertSame(2, $firstCluster['face_count']);
        $this->assertSame(
            'https://example.test/crops/face-1.jpg',
            $firstCluster['sample_face']['thumbnail_url']
        );
        $this->assertSame(101, $firstCluster['sample_face']['attachment_id']);
    }

    public function test_honors_pagination_params(): void
    {
        $this->security
            ->expects($this->exactly(2))
            ->method('verifyCapability')
            ->willReturn(true);

        $requestPageOne = new WP_REST_Request('GET', '/cat/v1/clusters');
        $requestPageOne->set_param('page', 1);
        $requestPageOne->set_param('per_page', 1);

        $responsePageOne = $this->controller->listClusters($requestPageOne);
        $this->assertCount(1, $responsePageOne['clusters']);
        $this->assertSame('cluster-alpha', $responsePageOne['clusters'][0]['id']);
        $this->assertSame(2, $responsePageOne['total']);
        $this->assertSame(1, $responsePageOne['per_page']);

        $requestPageTwo = new WP_REST_Request('GET', '/cat/v1/clusters');
        $requestPageTwo->set_param('page', 2);
        $requestPageTwo->set_param('per_page', 1);

        $responsePageTwo = $this->controller->listClusters($requestPageTwo);
        $this->assertCount(1, $responsePageTwo['clusters']);
        $this->assertSame('cluster-beta', $responsePageTwo['clusters'][0]['id']);
    }

    public function test_get_cluster_detail_requires_capability(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(false);

        $request = new WP_REST_Request('GET', '/cat/v1/clusters/cluster-alpha');
        $request->set_param('id', 'cluster-alpha');

        $response = $this->controller->getClusterDetail($request);
        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('rest_forbidden', $response->get_error_code());
    }

    public function test_get_cluster_detail_returns_cluster_and_faces(): void
    {
        $this->security
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $this->clusteringService->detailResponse = [
            'cluster' => [
                'id' => 'cluster-alpha',
                'face_count' => 2,
                'created_at' => '2024-10-10T10:00:00+00:00',
                'updated_at' => '2024-10-11T10:00:00+00:00',
            ],
            'faces' => [
                [
                    'id' => 'face-1',
                    'attachmentId' => 101,
                    'bbox' => ['x' => 10, 'y' => 20, 'width' => 80, 'height' => 90],
                ],
                [
                    'id' => 'face-2',
                    'attachmentId' => 102,
                    'bbox' => ['x' => 15, 'y' => 25, 'width' => 85, 'height' => 95],
                ],
            ],
        ];

        $request = new WP_REST_Request('GET', '/cat/v1/clusters/cluster-alpha');
        $request->set_param('id', 'cluster-alpha');

        $response = $this->controller->getClusterDetail($request);

        $this->assertIsArray($response);
        $this->assertSame('cluster-alpha', $response['cluster']['id']);
        $this->assertCount(2, $response['faces']);
        $this->assertSame('https://example.test/crops/face-1.jpg', $response['faces'][0]['thumbnail_url']);
        $this->assertSame('cluster-alpha', $this->clusteringService->lastDetailClusterId);
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
