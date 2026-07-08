<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

use function glob;
use function is_dir;
use function json_decode;
use function mkdir;
use function rmdir;
use function sys_get_temp_dir;
use function uniqid;
use function unlink;

/**
 * @covers \AltContext\Api\DescribeController
 */
class DescribeRunControllerTest extends TestCase
{
    private DescribeController $controller;
    private string $tempDir;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->controller = new DescribeController();
        $this->tempDir = sys_get_temp_dir() . '/acx-wbux-3-' . uniqid();
        mkdir($this->tempDir, 0o755, true);
    }

    protected function tearDown(): void
    {
        if (is_dir($this->tempDir)) {
            foreach (glob($this->tempDir . '/*') as $f) {
                @unlink($f);
            }
            @rmdir($this->tempDir);
        }
        parent::tearDown();
    }

    private function plantAttachment(int $id, string $bytes, string $extension = 'jpg'): string
    {
        $path = $this->tempDir . "/{$id}.{$extension}";
        file_put_contents($path, $bytes);
        $GLOBALS['__ac_attached_file'][$id] = $path;
        return $path;
    }

    public function testSubmitBulkDescribeRunSendsMultipartWithImageParts(): void
    {
        $bytes101 = "\xff\xd8\xff\xe0jpeg-101";
        $bytes202 = "\x89PNG\r\n\x1a\npng-202";
        $this->plantAttachment(101, $bytes101, 'jpg');
        $this->plantAttachment(202, $bytes202, 'png');

        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => '{"run_id":"11111111-1111-1111-1111-111111111111","status":"pending","phase":"queued","completed":0,"failed":0,"skipped":0,"total":2,"cancel_requested":false,"gpu_state":null}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101, 202]);

        $response = $this->controller->submit_describe_run($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $call = $this->getHttpCalls()[0];
        $this->assertStringContainsString('/scene/describe/run', $call['url']);
        $this->assertSame('POST', $call['method']);

        // request_class 'description' → 180s timeout, no breaker (large/slow bulk upload).
        $this->assertSame(180, $call['args']['timeout']);

        // multipart/form-data body with a boundary Content-Type.
        $this->assertStringContainsString('multipart/form-data; boundary=', (string) $call['args']['headers']['Content-Type']);

        $body = (string) $call['args']['body'];

        // Form field `tenant_id`.
        $this->assertStringContainsString('name="tenant_id"', $body);
        $this->assertStringContainsString(self::currentTenantId(), $body);

        // Form field `media_ids` = JSON int array as string.
        $this->assertStringContainsString('name="media_ids"', $body);
        $this->assertStringContainsString('[101,202]', $body);

        // One `image_<media_id>` file part per id, carrying the raw bytes.
        $this->assertStringContainsString('name="image_101"; filename="101.jpg"', $body);
        $this->assertStringContainsString('Content-Type: image/jpeg', $body);
        $this->assertStringContainsString($bytes101, $body);
        $this->assertStringContainsString('name="image_202"; filename="202.png"', $body);
        $this->assertStringContainsString('Content-Type: image/png', $body);
        $this->assertStringContainsString($bytes202, $body);
    }

    public function testSubmitRejectsMoreThan200MediaIds(): void
    {
        $mediaIds = range(1, 201);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', $mediaIds);

        $response = $this->controller->submit_describe_run($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('too_many_media_ids', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status'] ?? null);
        // No silent truncation → no backend dispatch.
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testSubmitRejectsUnreadableAttachmentNamingTheId(): void
    {
        // 101 is readable; 202 has no planted file → load fails, run is rejected.
        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101, 202]);

        $response = $this->controller->submit_describe_run($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_attachment_unreadable', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status'] ?? null);
        $this->assertStringContainsString('202', $response->get_error_message());
        // Fail fast before dispatching a partial run.
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testSubmitRejectsEmptyMediaIds(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', []);

        $response = $this->controller->submit_describe_run($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('missing_media_ids', $response->get_error_code());
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testStatusAndCancelProxyToSceneRunEndpoint(): void
    {
        $runId = '22222222-2222-2222-2222-222222222222';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"run_id":"' . $runId . '","status":"running","phase":"describing","completed":1,"failed":0,"skipped":0,"total":2,"cancel_requested":false,"gpu_state":null}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"run_id":"' . $runId . '","status":"cancelled","phase":"cancelled","completed":1,"failed":0,"skipped":1,"total":2,"cancel_requested":true,"gpu_state":null}',
        ]);

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $cancelRequest = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/cancel');
        $cancelRequest->set_param('run_id', $runId);

        $this->controller->get_describe_run_status($statusRequest);
        $this->controller->cancel_describe_run($cancelRequest);

        $calls = $this->getHttpCalls();
        $this->assertStringContainsString('/scene/describe/run/' . $runId, $calls[0]['url']);
        $this->assertSame('GET', $calls[0]['args']['method']);
        // Status polling uses 'post_scan_read' (10s, no breaker) so it never trips
        // the shared recognition circuit breaker during a long run. (PHP-02)
        $this->assertSame(10, $calls[0]['args']['timeout']);
        $this->assertStringContainsString('/scene/describe/run/' . $runId, $calls[1]['url']);
        $this->assertSame('DELETE', $calls[1]['args']['method']);
    }

    public function testSubmitDeduplicatesMediaIdsPreservingFirstSeenOrder(): void
    {
        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $this->plantAttachment(202, "\x89PNG\r\n\x1a\npng-202", 'png');

        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => '{"run_id":"11111111-1111-1111-1111-111111111111","status":"pending","phase":"queued","completed":0,"failed":0,"skipped":0,"total":2,"cancel_requested":false,"gpu_state":null}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101, 202, 101, 202, 101]);

        $response = $this->controller->submit_describe_run($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $body = (string) $this->getHttpCalls()[0]['args']['body'];
        // Distinct, first-seen order preserved; no redundant inference.
        $this->assertStringContainsString('[101,202]', $body);
        $this->assertSame(1, substr_count($body, 'name="image_101"'));
        $this->assertSame(1, substr_count($body, 'name="image_202"'));
    }

    public function testSubmitRejectsRunExceedingBodyCapWith413(): void
    {
        // Shrink the aggregate cap so a small planted file overflows it, without
        // materializing hundreds of MB of test bytes. (PHP-01 / PHP-03)
        add_filter('acx_describe_run_max_body_bytes', static fn (): int => 8);
        $this->plantAttachment(101, 'too-many-bytes-here', 'jpg');

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);

        $response = $this->controller->submit_describe_run($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_payload_too_large', $response->get_error_code());
        $this->assertSame(413, $response->get_error_data()['status'] ?? null);
        $this->assertStringContainsString('101', $response->get_error_message());
        // Rejected before any backend dispatch (and before OOM-buffering).
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testMaxItemsCapIsFilterable(): void
    {
        // Operators align the WP cap with the backend ACX_DESCRIBE_RUN_MAX_ITEMS. (PHP-03)
        add_filter('acx_describe_run_max_items', static fn (): int => 2);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [1, 2, 3]);

        $response = $this->controller->submit_describe_run($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('too_many_media_ids', $response->get_error_code());
        $this->assertStringContainsString('2 media IDs', $response->get_error_message());
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testGetDescribeRunItemsProxiesAndAnnotatesExistingAlt(): void
    {
        // WBUX-4 INT-01b: media 70 already has operator alt text; 71 does not.
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');

        $runId = '11111111-1111-1111-1111-111111111111';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 70, 'status' => 'completed', 'alt_text_draft' => 'a cat on a sofa', 'caption' => 'cat', 'provenance' => ['adapter' => 'florence']],
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => null],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs/' . $runId . '/items');
        $request->set_param('run_id', $runId);

        $response = $this->controller->get_describe_run_items($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(200, $response->get_status());

        // Read-class proxy: post_scan_read (10s, no shared breaker) like status.
        $call = $this->getHttpCalls()[0];
        $this->assertStringContainsString('/scene/describe/run/' . $runId . '/items', $call['url']);
        $this->assertSame('GET', $call['args']['method']);

        $data = $response->get_data();
        $items = [];
        foreach ($data['items'] as $item) {
            $items[$item['media_id']] = $item;
        }
        // existing_alt bucketing is computed in WP from post meta, not the backend.
        $this->assertTrue($items[70]['existing_alt']);
        $this->assertFalse($items[71]['existing_alt']);
        // Draft passthrough is preserved unchanged.
        $this->assertSame('a cat on a sofa', $items[70]['alt_text_draft']);
        $this->assertSame('a dog in a park', $items[71]['alt_text_draft']);
    }

    public function testGetDescribeRunItemsRequiresRunId(): void
    {
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs//items');
        $request->set_param('run_id', '');
        $response = $this->controller->get_describe_run_items($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
    }

    private function queueRunItemsResponse(string $runId): void
    {
        // media 70: has draft, WILL have existing alt planted by the test.
        // media 71: has draft, no existing alt (safe auto-apply).
        // media 72: failed item, no draft.
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 70, 'status' => 'completed', 'alt_text_draft' => 'a cat on a sofa', 'caption' => 'cat', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                    ['media_id' => 72, 'status' => 'failed', 'alt_text_draft' => null, 'caption' => null, 'provenance' => null],
                ],
            ]),
        ]);
    }

    public function testApplyRunDraftsAutoAppliesEmptyAltAndGuardsExisting(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        // No overwrite list → existing-alt items are guarded.

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        $this->assertSame([71], $data['applied']);
        $this->assertSame([70], $data['skipped_existing']);
        $this->assertSame([72], $data['skipped_no_draft']);

        // 71 written; 70 NOT clobbered; provenance persisted for the written item.
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('human-authored alt', get_post_meta(70, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('florence', $prov['adapter']);
    }

    public function testApplyRunDraftsOverwritesOnlyExplicitlyListedMedia(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        $request->set_param('overwrite_media_ids', [70]);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $data = $response->get_data();
        $this->assertContains(70, $data['applied']);
        $this->assertContains(71, $data['applied']);
        $this->assertSame([], $data['skipped_existing']);

        // 70 overwritten because it was explicitly listed.
        $this->assertSame('a cat on a sofa', get_post_meta(70, '_wp_attachment_image_alt', true));
    }
}
