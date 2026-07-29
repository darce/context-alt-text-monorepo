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

    private function plantPostType(int $id, string $type = 'attachment'): void
    {
        $GLOBALS['__ac_posts'][$id] = (object) ['ID' => $id, 'post_type' => $type];
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
     * BR-88a: alt===draft with provenance already an array (completed item)
     * stays skipped_existing; provenance must be byte-identical after apply
     * (no applied_at churn). Pins the `! is_array( $stored_prov )` conjunct.
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
        // Even a matching marker must not reopen a completed provenance write
        // when stored_prov is already an array (belt-and-braces conjunct).
        $this->setPostMeta(71, '_acx_description_provenance_pending', [
            'run_id' => $runId,
            'draft_hash' => hash('sha256', $draft),
        ]);
        $this->queueRunStatusResponse($runId, 'completed');
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
}
