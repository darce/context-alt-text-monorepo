<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Recognition;

use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionClientException;
use ContextAltText\Recognition\RecognitionServiceFaceDetectionPipeline;
use ContextAltText\Tests\TestCase;
use DateTimeInterface;

require_once __DIR__ . '/../bootstrap.php';

final class RecognitionServiceFaceDetectionPipelineTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();

        $GLOBALS['__cat_attachment_metadata'] = [];
        $GLOBALS['__cat_attachment_urls'] = [];
        $GLOBALS['__cat_attached_file'] = [];
    }

    protected function tearDown(): void
    {
        unset(
            $GLOBALS['__cat_attachment_metadata'],
            $GLOBALS['__cat_attachment_urls'],
            $GLOBALS['__cat_attached_file']
        );

        parent::tearDown();
    }

    public function test_detect_faces_returns_normalised_bounding_boxes(): void
    {
        $client = $this->createMock(RecognitionClient::class);
        $pipeline = new RecognitionServiceFaceDetectionPipeline($client);

        $attachmentId = 321;
        $GLOBALS['__cat_attachment_metadata'][$attachmentId] = ['width' => 400, 'height' => 300];
        $GLOBALS['__cat_attachment_urls'][$attachmentId] = 'http://example.test/uploads/photo.jpg';

        $client
            ->expects($this->once())
            ->method('analyzeScene')
            ->with($this->callback(static function (array $payload) {
                return isset($payload['images'][0]['image_url']) && $payload['images'][0]['image_url'] === 'http://example.test/uploads/photo.jpg';
            }))
            ->willReturn([
                'results' => [
                    [
                        'detected_entities' => [
                            ['bbox' => [10, 20, 210, 260]],
                            ['bbox' => [50, 60, 120, 160]],
                        ],
                        'roster_matches' => [
                            null,
                            ['is_match' => true],
                        ],
                    ],
                ],
            ]);

        $detections = $pipeline->detectFaces($attachmentId);

        $this->assertCount(1, $detections);
        $first = $detections[0];

        $this->assertArrayHasKey('bbox', $first);
        $this->assertArrayHasKey('detectedAt', $first);
        $this->assertInstanceOf(DateTimeInterface::class, $first['detectedAt']);

        $this->assertEqualsWithDelta(0.025, $first['bbox']['x'], 0.0001); // 10 / 400
        $this->assertEqualsWithDelta(0.0667, $first['bbox']['y'], 0.001);  // 20 / 300
        $this->assertEqualsWithDelta(0.5, $first['bbox']['width'], 0.0001); // 200 / 400
        $this->assertEqualsWithDelta(0.8, $first['bbox']['height'], 0.0001); // 240 / 300
    }

    public function test_detect_faces_returns_empty_when_attachment_url_missing(): void
    {
        $client = $this->createMock(RecognitionClient::class);
        $pipeline = new RecognitionServiceFaceDetectionPipeline($client);

        $attachmentId = 999;
        $GLOBALS['__cat_attachment_metadata'][$attachmentId] = ['width' => 100, 'height' => 100];

        $client->expects($this->never())->method('analyzeScene');

        $this->assertSame([], $pipeline->detectFaces($attachmentId));
    }

    public function test_detect_faces_handles_client_exception(): void
    {
        $client = $this->createMock(RecognitionClient::class);
        $pipeline = new RecognitionServiceFaceDetectionPipeline($client);

        $attachmentId = 654;
        $GLOBALS['__cat_attachment_metadata'][$attachmentId] = ['width' => 200, 'height' => 200];
        $GLOBALS['__cat_attachment_urls'][$attachmentId] = 'http://example.test/uploads/item.jpg';

        $client
            ->expects($this->once())
            ->method('analyzeScene')
            ->willThrowException(new RecognitionClientException('Failed', 500));

        $this->assertSame([], $pipeline->detectFaces($attachmentId));
    }
}
