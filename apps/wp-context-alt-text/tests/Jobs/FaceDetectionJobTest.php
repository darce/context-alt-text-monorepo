<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Jobs;

use ContextAltText\Infrastructure\Repositories\UnknownFaceRepository;
use ContextAltText\Jobs\FaceDetectionJob;
use ContextAltText\Recognition\FaceDetectionPipeline;
use ContextAltText\Tests\TestCase;
use DateTimeImmutable;

require_once __DIR__ . '/../bootstrap.php';

final class FaceDetectionJobTest extends TestCase
{
    public function test_persists_detected_faces(): void
    {
        /** @var \WPDBStub $wpdb */
        $wpdb = $GLOBALS['wpdb'];
        $wpdb->reset();

        $repository = new UnknownFaceRepository($wpdb);
        $pipeline = $this->createMock(FaceDetectionPipeline::class);

        $pipeline
            ->expects($this->once())
            ->method('detectFaces')
            ->with(321)
            ->willReturn([
                [
                    'bbox' => ['x' => 1.0, 'y' => 2.0, 'width' => 3.0, 'height' => 4.0],
                    'embeddingId' => 'emb-123',
                    'clusterId' => null,
                    'detectedAt' => new DateTimeImmutable('2024-01-01T10:00:00Z'),
                ],
            ]);

        $wpdb->insert_id = 1001;

        $job = new FaceDetectionJob($pipeline, $repository);
        $job->execute(321);

        $this->assertNotEmpty($wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('INSERT INTO wp_cat_unknown_faces', $query);
        $this->assertStringContainsString("'emb-123'", $query);
    }

    public function test_handles_empty_detection_set(): void
    {
        /** @var \WPDBStub $wpdb */
        $wpdb = $GLOBALS['wpdb'];
        $wpdb->reset();

        $repository = new UnknownFaceRepository($wpdb);
        $pipeline = $this->createMock(FaceDetectionPipeline::class);

        $pipeline
            ->expects($this->once())
            ->method('detectFaces')
            ->with(400)
            ->willReturn([]);

        $job = new FaceDetectionJob($pipeline, $repository);
        $job->execute(400);

        $this->assertSame([], $wpdb->queries);
    }
}
