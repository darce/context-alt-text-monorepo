<?php

declare(strict_types=1);

use ContextAltText\Recognition\ScanController;
use ContextAltText\Security\Security;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class ScanControllerTest extends TestCase
{
    private Security $mockSecurity;
    private FakeFaceDetectionQueue $queue;
    private ScanController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->mockSecurity = $this->createMock(Security::class);
        $this->queue = new FakeFaceDetectionQueue();
        $this->controller = new ScanController($this->mockSecurity, $this->queue);
    }

    public function test_returns_403_when_user_cannot_upload_files(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(false);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/scan');
        $request->set_body_params(['attachment_ids' => [1]]);

        $response = $this->controller->scanBatch($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('rest_forbidden', $response->get_error_code());
    }

    public function test_returns_error_when_batch_exceeds_limit(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->willReturn(true);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/scan');
        $request->set_body_params([
            'attachment_ids' => range(1, 55),
        ]);

        $response = $this->controller->scanBatch($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('invalid_request', $response->get_error_code());
        $this->assertStringContainsString('50', $response->get_error_message());
    }

    public function test_returns_error_when_attachment_list_missing(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->willReturn(true);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/scan');
        $request->set_body_params([]);

        $response = $this->controller->scanBatch($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('invalid_request', $response->get_error_code());
    }

    public function test_enqueues_face_detection_jobs_and_returns_payload(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->willReturn(true);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/scan');
        $request->set_body_params([
            'attachment_ids' => ['12', 34, 34],
            'priority' => 'high',
        ]);

        $response = $this->controller->scanBatch($request);

        $this->assertIsArray($response);
        $data = $response;

        $this->assertSame('fake-job-1', $data['job_id']);
        $this->assertSame(2, $data['queued_count']);
        $this->assertSame([12, 34], $this->queue->lastAttachmentIds);
        $this->assertSame('high', $this->queue->lastPriority);
    }
}

final class FakeFaceDetectionQueue implements \ContextAltText\Recognition\FaceDetectionQueue
{
    /** @var int[] */
    public array $lastAttachmentIds = [];
    public ?string $lastPriority = null;

    public function enqueueBatch(array $attachmentIds, string $priority = 'normal'): array
    {
        $this->lastAttachmentIds = $attachmentIds;
        $this->lastPriority = $priority;

        return [
            'job_id' => 'fake-job-1',
            'queued_count' => count($attachmentIds),
        ];
    }
}
