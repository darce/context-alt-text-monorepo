<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Infrastructure\Repositories;

use ContextAltText\Domain\Clustering\UnknownFace;
use ContextAltText\Infrastructure\Repositories\UnknownFaceRepository;
use ContextAltText\Tests\TestCase;
use DateTimeImmutable;

final class UnknownFaceRepositoryTest extends TestCase
{
    private \WPDBStub $wpdb;
    private UnknownFaceRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->wpdb = $GLOBALS['wpdb'];
        $this->wpdb->reset();
        $this->repository = new UnknownFaceRepository($this->wpdb);
    }

    public function test_save_unknown_face_inserts_new_record(): void
    {
        $this->wpdb->insert_id = 42;
        $face = new UnknownFace(
            null,
            123,
            ['x' => 1.0, 'y' => 2.0, 'width' => 3.0, 'height' => 4.0],
            'emb-1',
            [0.1, 0.2, 0.3], // embeddingVector
            'cluster-1',
            new DateTimeImmutable('2024-01-01 12:00:00')
        );

        $id = $this->repository->saveUnknownFace($face);

        $this->assertSame(42, $id);
        $this->assertNotEmpty($this->wpdb->queries);
        $insertQueries = array_values(array_filter(
            $this->wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_cat_unknown_faces')
        ));

        $this->assertNotEmpty($insertQueries, 'Expected an INSERT INTO wp_cat_unknown_faces query to be executed.');
        $this->assertStringContainsString("'emb-1'", $insertQueries[0]);
    }

    public function test_save_unknown_face_updates_existing_record(): void
    {
        $face = new UnknownFace(
            99,
            456,
            ['x' => 10.0, 'y' => 20.0, 'width' => 30.0, 'height' => 40.0],
            'emb-2',
            [0.4, 0.5, 0.6], // embeddingVector
            'cluster-2',
            new DateTimeImmutable('2024-02-01 08:00:00'),
            new DateTimeImmutable('2024-02-02 09:00:00'),
            'person-1'
        );

        $id = $this->repository->saveUnknownFace($face);

        $this->assertSame(99, $id);
        $this->assertNotEmpty($this->wpdb->queries);
        $updateQueries = array_values(array_filter(
            $this->wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'UPDATE wp_cat_unknown_faces')
        ));

        $this->assertNotEmpty($updateQueries, 'Expected an UPDATE wp_cat_unknown_faces query to be executed.');
        $this->assertStringContainsString('WHERE id = 99', $updateQueries[0]);
    }

    public function test_find_unresolved_faces_returns_unknown_face_entities(): void
    {
        $this->wpdb->mockResults = [
            [
                'id' => '7',
                'attachment_id' => '321',
                'bbox_json' => json_encode(['x' => 5, 'y' => 6, 'width' => 70, 'height' => 80]),
                'embedding_id' => 'emb-7',
                'cluster_id' => 'cluster-7',
                'detected_at' => '2024-03-01 10:00:00',
                'resolved_at' => null,
                'roster_id' => null,
            ],
        ];

        $faces = $this->repository->findUnresolvedFaces(25);

        $this->assertCount(1, $faces);
        $first = $faces[0];
        $this->assertInstanceOf(UnknownFace::class, $first);
        $this->assertSame(321, $first->attachmentId());
        $this->assertSame('cluster-7', $first->clusterId());
        $this->assertNotEmpty($this->wpdb->queries);
        $selectQueries = array_values(array_filter(
            $this->wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'SELECT * FROM wp_cat_unknown_faces')
        ));

        $this->assertNotEmpty($selectQueries);
        $this->assertStringContainsString('LIMIT 25', $selectQueries[0]);
    }

    public function test_find_faces_by_cluster_uses_expected_query(): void
    {
        $this->wpdb->mockResults = [];
        $this->repository->findFacesByCluster('cluster-x');

    $this->assertNotEmpty($this->wpdb->queries);
    $query = $this->findQueryContaining("WHERE cluster_id = 'cluster-x'");
    $this->assertNotNull($query);
    $this->assertStringContainsString('resolved_at IS NULL', $query);
    }

    public function test_mark_face_as_resolved_updates_record(): void
    {
        $this->repository->markFaceAsResolved(55, 'person-55');

        $this->assertNotEmpty($this->wpdb->queries);
    $query = $this->findQueryContaining('UPDATE wp_cat_unknown_faces');
    $this->assertNotNull($query);
        $this->assertStringContainsString('UPDATE wp_cat_unknown_faces', $query);
        $this->assertStringContainsString('SET resolved_at', $query);
        $this->assertStringContainsString('WHERE id = 55', $query);
    }

    public function test_update_cluster_assignment_updates_cluster_id(): void
    {
        $this->repository->updateClusterAssignment(77, 'cluster-new');

        $this->assertNotEmpty($this->wpdb->queries);
    $query = $this->findQueryContaining('SET cluster_id =');
    $this->assertNotNull($query);
        $this->assertStringContainsString("SET cluster_id = 'cluster-new'", $query);
        $this->assertStringContainsString('WHERE id = 77', $query);
    }

    public function test_find_faces_by_attachment_filters_by_attachment_id(): void
    {
        $this->wpdb->mockResults = [];
        $this->repository->findFacesByAttachment(444);

    $this->assertNotEmpty($this->wpdb->queries);
    $query = $this->findQueryContaining('WHERE attachment_id = 444');
    $this->assertNotNull($query);
    }

    public function test_find_face_by_id_returns_unknown_face(): void
    {
        $this->wpdb->mockRow = [
            'id' => '12',
            'attachment_id' => '512',
            'bbox_json' => json_encode(['x' => 2, 'y' => 3, 'width' => 40, 'height' => 50]),
            'embedding_id' => 'emb-12',
            'cluster_id' => 'cluster-12',
            'detected_at' => '2024-03-01 10:00:00',
            'resolved_at' => null,
            'roster_id' => null,
        ];

        $face = $this->repository->findFaceById(12);

        $this->assertInstanceOf(UnknownFace::class, $face);
    $query = $this->findQueryContaining('WHERE id = 12');
    $this->assertNotNull($query);
    }

    public function test_find_face_by_id_returns_null_when_missing(): void
    {
        $this->wpdb->mockResults = [];
        $face = $this->repository->findFaceById(999);

        $this->assertNull($face);
    $query = $this->findQueryContaining('WHERE id = 999');
    $this->assertNotNull($query);
    }

    public function test_find_faces_by_ids_filters_and_orders_unique_ids(): void
    {
        $this->wpdb->mockResults = [
            [
                'id' => '21',
                'attachment_id' => '600',
                'bbox_json' => json_encode(['x' => 1, 'y' => 2, 'width' => 30, 'height' => 40]),
                'embedding_id' => 'emb-21',
                'cluster_id' => 'cluster-a',
                'detected_at' => '2024-01-01 00:00:00',
                'resolved_at' => null,
                'roster_id' => null,
            ],
        ];

        $faces = $this->repository->findFacesByIds([21, '21', 0, -5, 32]);

        $this->assertCount(1, $faces);
        $this->assertInstanceOf(UnknownFace::class, $faces[0]);

        $query = $this->findQueryContaining('SELECT * FROM wp_cat_unknown_faces');
        $this->assertNotNull($query);
        $this->assertStringContainsString('IN (', $query);
        $this->assertStringContainsString('resolved_at IS NULL', $query);
    }

    private function findQueryContaining(string $needle): ?string
    {
        foreach ($this->wpdb->queries as $query) {
            if (str_contains($query, $needle)) {
                return $query;
            }
        }

        return null;
    }
}
