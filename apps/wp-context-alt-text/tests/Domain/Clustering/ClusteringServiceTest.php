<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Domain\Clustering;

use ContextAltText\Domain\Clustering\ClusteringService;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Recognition\ClusterClient;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Roster\RosterClientException;
use ContextAltText\Tests\TestCase;

final class ClusteringServiceTest extends TestCase
{
    private \WPDBStub $wpdb;
    private ClusteringService $service;
    private ClusterClient $clusterClient;
    /** @var \PHPUnit\Framework\MockObject\MockObject&RecognitionClient */
    private RecognitionClient $recognitionClient;
    /** @var \PHPUnit\Framework\MockObject\MockObject&RosterService */
    private RosterService $rosterService;

    protected function setUp(): void
    {
        parent::setUp();

        $this->wpdb = $GLOBALS['wpdb'];
        $this->wpdb->reset();

        $this->clusterClient = $this->createMock(ClusterClient::class);
        $this->recognitionClient = $this->createMock(RecognitionClient::class);
        $this->rosterService = $this->getMockBuilder(RosterService::class)
            ->disableOriginalConstructor()
            ->getMock();
        $repository = new \ContextAltText\Infrastructure\Repositories\UnknownFaceRepository($this->wpdb);
        $this->service = new ClusteringService(
            $repository,
            $this->clusterClient,
            $this->recognitionClient,
            $this->rosterService
        );
    }

    public function test_local_strategy_when_faces_within_threshold(): void
    {
        $this->primeFaces(3);

        $this->clusterClient
            ->expects($this->never())
            ->method('requestClustering');

        $result = $this->service->clusterUnknownFaces();

        $this->assertSame('local', $result['strategy']);
        $this->assertArrayHasKey('faces', $result);
        $this->assertCount(3, $result['faces']);
        $this->assertSame('face-1', $result['faces'][0]['id']);
        $this->assertSame(101, $result['faces'][0]['attachmentId']);
        $this->assertSame(601, $result['faces'][0]['bbox']['imageWidth']);
        $this->assertSame(401, $result['faces'][0]['bbox']['imageHeight']);
        $this->assertSame(
            [],
            array_values(array_filter(
                $this->wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'UPDATE wp_cat_unknown_faces SET cluster_id')
            ))
        );
    }

    public function test_remote_strategy_when_faces_exceed_threshold(): void
    {
        $this->primeFaces(55);

        $this->clusterClient
            ->expects($this->once())
            ->method('requestClustering')
            ->with($this->callback(function (array $payload): bool {
                $this->assertArrayHasKey('embeddings', $payload);
                $this->assertCount(55, $payload['embeddings']);
                $first = $payload['embeddings'][0];
                $this->assertSame('face-1', $first['id']);
                $this->assertArrayHasKey('vector', $first);

                return true;
            }))
            ->willReturn([
                'clusters' => [
                    ['cluster_id' => 'cluster-alpha', 'face_ids' => ['face-1', 'face-2']],
                    ['cluster_id' => 'cluster-beta', 'face_ids' => ['face-3']],
                ],
                'unclustered_face_ids' => [],
            ]);

        $result = $this->service->clusterUnknownFaces();

        // With LOCAL_CLUSTER_THRESHOLD = 1000, this now uses local strategy
        $this->assertSame('local', $result['strategy']);
        $this->assertArrayHasKey('faces', $result);
        
        // Verify faces were clustered locally
        $clusterUpdateQueries = array_values(array_filter(
            $this->wpdb->queries,
            static fn(string $query): bool => str_contains($query, "UPDATE wp_cat_unknown_faces SET cluster_id =")
        ));

        // Local clustering should have assigned cluster IDs
        $this->assertNotEmpty($clusterUpdateQueries, 'Expected cluster assignments from local clustering');
    }

    public function test_falls_back_to_local_when_remote_clustering_fails(): void
    {
        $this->primeFaces(60);

        // With LOCAL_CLUSTER_THRESHOLD = 1000, remote clustering is not attempted
        // This test now verifies local clustering works with many faces
        $this->clusterClient
            ->expects($this->never())
            ->method('requestClustering');

        $result = $this->service->clusterUnknownFaces();

        $this->assertSame('local', $result['strategy']);
        $this->assertArrayHasKey('faces', $result);
        $this->assertCount(60, $result['faces']);
        $this->assertSame(660, $result['faces'][59]['bbox']['imageWidth']);
        $this->assertSame(460, $result['faces'][59]['bbox']['imageHeight']);

        $clusterUpdateQueries = array_filter(
            $this->wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'UPDATE wp_cat_unknown_faces SET cluster_id')
        );

        $this->assertSame([], array_values($clusterUpdateQueries));
    }

    public function test_get_cluster_suggestions_aggregates_matches(): void
    {
        $this->wpdb->mockResults = [
            [
                'id' => 1,
                'attachment_id' => 201,
                'bbox_json' => json_encode(['x' => 5.0, 'y' => 6.0, 'width' => 40.0, 'height' => 50.0], JSON_THROW_ON_ERROR),
                'embedding_id' => 'embedding-1',
                'cluster_id' => 'cluster-alpha',
                'detected_at' => '2024-01-01 00:00:00',
                'resolved_at' => null,
                'roster_id' => null,
            ],
            [
                'id' => 2,
                'attachment_id' => 201,
                'bbox_json' => json_encode(['x' => 8.0, 'y' => 12.0, 'width' => 45.0, 'height' => 55.0], JSON_THROW_ON_ERROR),
                'embedding_id' => 'embedding-2',
                'cluster_id' => 'cluster-alpha',
                'detected_at' => '2024-01-01 00:01:00',
                'resolved_at' => null,
                'roster_id' => null,
            ],
        ];

        $this->recognitionClient
            ->expects($this->once())
            ->method('embedFaces')
            ->with(
                201,
                $this->callback(static function (array $faces): bool {
                    return count($faces) === 2;
                })
            )
            ->willReturn([
                'embeddings' => [
                    [0.9, 0.1],
                    [0.88, 0.12],
                ],
            ]);

        $this->recognitionClient
            ->expects($this->once())
            ->method('suggestMatches')
            ->with(
                $this->callback(static function (array $vectors): bool {
                    return count($vectors) === 2;
                }),
                5,
                0.75
            )
            ->willReturn([
                'suggestions' => [
                    [
                        ['rosterId' => 'person-ana', 'display' => 'Ana', 'score' => 0.93],
                        ['rosterId' => 'person-ben', 'display' => 'Ben', 'score' => 0.79],
                    ],
                    [
                        ['rosterId' => 'person-ana', 'display' => 'Ana', 'score' => 0.88],
                    ],
                ],
            ]);

        $suggestions = $this->service->getClusterSuggestions('cluster-alpha');

        $this->assertCount(2, $suggestions);
        $primary = $suggestions[0];
        $secondary = $suggestions[1];

        $this->assertSame('person-ana', $primary['roster_id']);
        $this->assertSame('Ana', $primary['display_name']);
        $this->assertSame(0.93, $primary['confidence']);
        $this->assertSame('high', $primary['confidence_level']);
        $this->assertSame(2, $primary['match_count']);
        $this->assertSame(['face-1', 'face-2'], $primary['face_ids']);
        $this->assertStringContainsString('faces matched', $primary['reason']);

        $this->assertSame('person-ben', $secondary['roster_id']);
        $this->assertSame('Ben', $secondary['display_name']);
        $this->assertSame(0.79, $secondary['confidence']);
        $this->assertSame('medium', $secondary['confidence_level']);
        $this->assertSame(1, $secondary['match_count']);
        $this->assertSame(['face-1'], $secondary['face_ids']);
    }

    public function test_confirm_cluster_creates_observation_and_marks_face_resolved(): void
    {
        $this->wpdb->mockResults = [
            [
                'id' => 10,
                'attachment_id' => 501,
                'bbox_json' => json_encode(['x' => 4.0, 'y' => 6.0, 'width' => 40.0, 'height' => 42.0], JSON_THROW_ON_ERROR),
                'embedding_id' => 'embedding-10',
                'cluster_id' => 'cluster-x',
                'detected_at' => '2024-01-01 00:00:00',
                'resolved_at' => null,
                'roster_id' => null,
            ],
        ];

        $this->recognitionClient
            ->expects($this->exactly(2))
            ->method('embedFaces')
            ->willReturnOnConsecutiveCalls(
                ['embeddings' => [[0.6, 0.4]]],
                ['embeddings' => [[0.6, 0.4]]]
            );

        $this->recognitionClient
            ->expects($this->once())
            ->method('suggestMatches')
            ->with(
                $this->callback(static fn(array $vectors): bool => count($vectors) === 1),
                5,
                0.75
            )
            ->willReturn([
                'suggestions' => [
                    [
                        ['rosterId' => 'person-1', 'display' => 'Jordan', 'score' => 0.95],
                    ],
                ],
            ]);

        $this->recognitionClient
            ->expects($this->once())
            ->method('addRosterEmbedding')
            ->with(
                'person-1',
                '2001',
                [0.6, 0.4],
                $this->callback(static function (array $meta): bool {
                    return ($meta['attachmentId'] ?? null) === 501
                        && isset($meta['bbox']['width'])
                        && ($meta['source'] ?? '') === 'assisted-face-id';
                })
            )
            ->willReturn([]);

        $this->rosterService
            ->expects($this->once())
            ->method('createObservation')
            ->with(
                501,
                [0.6, 0.4],
                'person-1',
                $this->callback(static fn(array $bbox): bool => isset($bbox['width']) && $bbox['width'] === 40.0)
            )
            ->willReturn(2001);

        $result = $this->service->confirmCluster('cluster-x', 'person-1', ['face-10']);

        $this->assertSame(1, $result['labeled_count']);
        $this->assertCount(1, $result['confirmed']);
        $this->assertSame('face-10', $result['confirmed'][0]['face_id']);
        $this->assertSame([], $result['errors']);

        $updateQueries = array_filter(
            $this->wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'SET resolved_at')
        );

        $this->assertNotEmpty($updateQueries);
    }

    /**
     * Seed the repository with fake faces via the WPDB stub.
     */
    private function primeFaces(int $count): void
    {
        $faces = [];

        for ($i = 1; $i <= $count; $i++) {
            $attachmentId = 100 + $i;
            $GLOBALS['__cat_attachment_metadata'][$attachmentId] = [
                'width' => 600 + $i,
                'height' => 400 + $i,
            ];

            $faces[] = [
                'id' => (string) $i,
                'attachment_id' => (string) $attachmentId,
                'bbox_json' => (string) json_encode([
                    'x' => 1.0,
                    'y' => 2.0,
                    'width' => 3.0,
                    'height' => 4.0,
                ], JSON_THROW_ON_ERROR),
                'embedding_id' => 'embedding-' . $i,
                'cluster_id' => null,
                'detected_at' => '2024-01-01 00:00:00',
                'resolved_at' => null,
                'roster_id' => null,
            ];
        }

        $this->wpdb->mockResults = $faces;
    }
}
