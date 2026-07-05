<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Api\Services\DescriptionBudgetService;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function json_decode;

/**
 * E19-1 S6: WordPress describe path. The controller resolves one attachment,
 * reads its bytes, attaches inert wp_context, and dispatches a single-image
 * multipart request to the backend /scene/describe/multipart route. The
 * backend response is passed through unchanged; a malformed upstream envelope
 * is rejected with an explicit 502 (rg-015 — never fabricate fields).
 *
 * @covers \AltContext\Api\DescribeController
 * @covers \AltContext\Api\Services\DescribeMediaService
 */
class DescribeMediaServiceTest extends TestCase
{
    private DescribeController $controller;
    private string $tempDir;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->controller = new DescribeController();
        $this->tempDir = sys_get_temp_dir() . '/acx-e19-1-' . uniqid();
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
        $GLOBALS['__ac_posts'][$id] = (object) array(
            'post_title'   => "Photo {$id}",
            'post_excerpt' => 'A caption.',
            'post_content' => 'A long description.',
        );
        return $path;
    }

    /**
     * @return array<string,mixed>
     */
    private function validBackendBody(int $media_id): array
    {
        return array(
            'tenant_id'              => self::currentTenantId(),
            'media_id'               => $media_id,
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'visual_facts'           => array('caption' => 'A photo.', 'objects' => array(), 'ocr_text' => null),
            'alt_text_draft'         => 'A photo.',
            'context_used'           => array('sources' => array(), 'applied' => false),
            'provider_disclosure'    => array('provider' => 'none', 'left_service_boundary' => false),
            'cached'                 => false,
            'duration_ms'            => 3,
            'retention_class'        => 'retain_all',
        );
    }

    public function testDispatchesSingleImageMultipartToSceneRoute(): void
    {
        $bytes = "\xff\xd8\xff\xe0fake-jpeg-bytes";
        $this->plantAttachment(42, $bytes, 'jpg');
        $GLOBALS['__ac_site_url'] = 'http://acx.test';

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertNotInstanceOf(WP_Error::class, $result, var_export($result, true));
        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $call = $calls[0];
        $this->assertStringContainsString('/scene/describe/multipart', $call['url']);

        $body = $call['args']['body'];
        $this->assertIsString($body);
        // Exactly one image part with the raw bytes embedded.
        $this->assertStringContainsString('name="image_42"; filename=', $body);
        $this->assertStringContainsString($bytes, $body);

        // The 'request' envelope carries tenant_id + media_id + WP context.
        $this->assertStringContainsString("name=\"request\"\r\n", $body);
        $this->assertMatchesRegularExpression('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body);
        preg_match('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body, $m);
        $envelope = json_decode($m[1], true);
        $this->assertSame(self::currentTenantId(), $envelope['tenant_id']);
        $this->assertSame(42, $envelope['media_id']);
        $this->assertIsArray($envelope['context_pack']);
        $this->assertSame('Photo 42', $envelope['context_pack']['attachment']['title']);
        $this->assertSame('42.jpg', $envelope['context_pack']['attachment']['filename']);
        // No top-level keys the backend's extra='forbid' envelope rejects.
        $this->assertSame(array('tenant_id', 'media_id', 'context_pack'), array_keys($envelope));

        // Response is passed through unchanged.
        $data = $result->get_data();
        $this->assertSame('A photo.', $data['alt_text_draft']);
        $this->assertFalse($data['cached']);

        $usage = (new DescriptionBudgetService())->usage_summary();
        $this->assertSame(1, $usage['attempts']);
        $this->assertSame(1, $usage['successes']);
        $this->assertSame(0, $usage['failures']);
    }

    public function testRegisterRoutesExposesWriteIntentArgs(): void
    {
        $this->controller->register_routes();

        $route = null;
        foreach ($GLOBALS['__ac_rest_routes'] as $definition) {
            if (($definition['namespace'] ?? null) === 'acx/v1' && ($definition['route'] ?? null) === '/recognition/describe') {
                $route = $definition;
                break;
            }
        }

        $this->assertIsArray($route);
        $args = $route['args']['args'] ?? array();
        $this->assertArrayHasKey('media_id', $args);
        $this->assertArrayHasKey('write_alt', $args);
        $this->assertSame('boolean', $args['write_alt']['type'] ?? null);
        $this->assertFalse($args['write_alt']['default'] ?? true);
        $this->assertArrayHasKey('force', $args);
        $this->assertSame('boolean', $args['force']['type'] ?? null);
        $this->assertFalse($args['force']['default'] ?? true);
    }

    public function testPreviewOnlyDoesNotWriteAltTextOrProvenance(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));
        $this->assertArrayNotHasKey('alt_text_write', $result->get_data());
    }

    public function testWriteIntentPersistsMissingAltTextAndProvenance(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('written', $result->get_data()['alt_text_write']['status'] ?? null);

        $provenance = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($provenance);
        $this->assertSame('seeded', $provenance['adapter']);
        $this->assertSame('seeded-fixtures', $provenance['model_id']);
        $this->assertSame('1', $provenance['model_version']);
        $this->assertSame('1', $provenance['prompt_or_task_version']);
        $this->assertSame(str_repeat('a', 64), $provenance['image_hash']);
        $this->assertSame(str_repeat('b', 64), $provenance['context_hash']);
        $this->assertArrayHasKey('generated_at', $provenance);
    }

    public function testWriteIntentSkipsExistingAltTextByDefault(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('Human-authored alt', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));
        $this->assertSame('skipped_existing_alt', $result->get_data()['alt_text_write']['status'] ?? null);
    }

    public function testForceWriteOverwritesExistingAltTextAndStoresProvenance(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $req->set_param('force', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('forced_overwrite', $result->get_data()['alt_text_write']['status'] ?? null);
        $this->assertIsArray(get_post_meta(42, '_acx_description_provenance', true));
    }

    public function testForceWritePreservesMatchingGeneratedProvenance(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
        $existingProvenance = array(
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'generated_at'           => '2026-01-01T00:00:00+00:00',
        );
        $this->setPostMeta(42, '_acx_description_provenance', $existingProvenance);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $req->set_param('force', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame($existingProvenance, get_post_meta(42, '_acx_description_provenance', true));
        $this->assertSame('forced_overwrite', $result->get_data()['alt_text_write']['status'] ?? null);
    }

    public function testRegistersAndServesMissingAltDryRunWithoutBackendCall(): void
    {
        $GLOBALS['__ac_posts'][42] = (object) array('ID' => 42, 'post_title' => 'Missing');
        $GLOBALS['__ac_get_posts_results'][] = $GLOBALS['__ac_posts'][42];
        $GLOBALS['__ac_attachment_mimes'][42] = 'image/jpeg';
        $GLOBALS['__ac_attached_file'][42] = $this->tempDir . '/42-missing.jpg';
        $GLOBALS['__ac_post_meta'][42]['_wp_attachment_image_alt'] = '';

        $this->controller->register_routes();

        $route = null;
        foreach ($GLOBALS['__ac_rest_routes'] as $definition) {
            if (($definition['namespace'] ?? null) === 'acx/v1' && ($definition['route'] ?? null) === '/recognition/describe/candidates') {
                $route = $definition;
                break;
            }
        }

        $this->assertIsArray($route);
        $this->assertSame('GET', $route['args']['methods'] ?? null);
        $this->assertArrayHasKey('limit', $route['args']['args'] ?? array());
        $this->assertArrayHasKey('offset', $route['args']['args'] ?? array());

        $req = new WP_REST_Request('GET', '/acx/v1/recognition/describe/candidates');
        $req->set_param('limit', 10);
        $req->set_param('offset', 0);
        $result = $this->controller->list_description_candidates($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());
        $this->assertSame(array(42), array_column($result->get_data()['candidates'], 'media_id'));
        $this->assertSame(array(), $this->getHttpCalls());
    }

    public function testBuildsBoundedContextPackFromAttachmentParentTermsAndProductMeta(): void
    {
        $bytes = "\xff\xd8\xff\xe0fake-jpeg-bytes";
        $this->plantAttachment(42, $bytes, 'jpg');
        $GLOBALS['__ac_posts'][42]->post_parent = 77;
        $GLOBALS['__ac_posts'][77] = (object) array(
            'ID'           => 77,
            'post_title'   => 'Trail jackets for spring',
            'post_excerpt' => 'Lightweight red jackets for spring hikes.',
            'post_content' => 'Private body should not travel.',
            'post_type'    => 'product',
            'post_status'  => 'publish',
        );
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Model in a red jacket');
        $this->setPostMeta(77, '_sku', 'JKT-RED-1');
        $this->setPostMeta(77, '_price', '129.00');

        $term = wp_insert_term('Jackets', 'product_cat', array('slug' => 'jackets'));
        wp_set_object_terms(77, array($term['term_id']), 'product_cat');

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $body = $this->getHttpCalls()[0]['args']['body'];
        preg_match('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body, $m);
        $contextPack = json_decode($m[1], true)['context_pack'];

        $this->assertSame('Photo 42', $contextPack['attachment']['title']);
        $this->assertSame('A caption.', $contextPack['attachment']['caption']);
        $this->assertSame('Model in a red jacket', $contextPack['attachment']['alt_text']);
        $this->assertSame('Trail jackets for spring', $contextPack['post']['title']);
        $this->assertSame('product', $contextPack['post']['post_type']);
        $this->assertSame('publish', $contextPack['post']['status']);
        $this->assertArrayNotHasKey('description', $contextPack['post']);
        $this->assertSame('Jackets', $contextPack['taxonomy_terms'][0]['name']);
        $this->assertSame('JKT-RED-1', $contextPack['product']['sku']);
        $this->assertSame('129.00', $contextPack['product']['price']);
    }

    public function testContextPackExcludesNonPublicParentPostContent(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $GLOBALS['__ac_posts'][42]->post_parent = 77;
        $GLOBALS['__ac_posts'][77] = (object) array(
            'ID'           => 77,
            'post_title'   => 'Draft product',
            'post_excerpt' => 'Draft teaser',
            'post_type'    => 'product',
            'post_status'  => 'draft',
        );

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $this->controller->describe_media($req);

        $body = $this->getHttpCalls()[0]['args']['body'];
        preg_match('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body, $m);
        $contextPack = json_decode($m[1], true)['context_pack'];

        $this->assertArrayNotHasKey('post', $contextPack);
        $this->assertArrayNotHasKey('product', $contextPack);
    }

    public function testContextPackTruncatesMultibyteTextWithoutBreakingJson(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $GLOBALS['__ac_posts'][42]->post_title = str_repeat('€', 170);

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $this->controller->describe_media($req);

        $body = $this->getHttpCalls()[0]['args']['body'];
        preg_match('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body, $m);
        $envelope = json_decode($m[1], true);

        $this->assertIsArray($envelope);
        $this->assertSame(str_repeat('€', 160), $envelope['context_pack']['attachment']['title']);
    }

    public function testRejectsUnreadableAttachmentBeforeDispatch(): void
    {
        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 9001);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('describe_attachment_unreadable', $result->get_error_code());
        $this->assertSame(array(), $this->getHttpCalls());
    }

    public function testRejectsMissingMediaId(): void
    {
        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('describe_invalid_media_id', $result->get_error_code());
        $this->assertSame(array(), $this->getHttpCalls());
    }

    public function testBudgetLimitBlocksBeforeBackendDispatch(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setOption('acx_description_budget_max_attempts', 0);

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_budget_attempt_limit_exceeded', $result->get_error_code());
        $this->assertSame(429, $result->get_error_data()['status'] ?? null);
        $this->assertSame(array(), $this->getHttpCalls());
    }

    public function testRejectsOversizePayloadBeforeDispatch(): void
    {
        $bytes = str_repeat('A', 26 * 1024 * 1024);
        $this->plantAttachment(7, $bytes, 'png');

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 7);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('describe_payload_too_large', $result->get_error_code());
        $this->assertSame(array(), $this->getHttpCalls());
    }

    public function testMalformedUpstreamEnvelopeReturns502(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');

        // Upstream 200 but missing required provenance fields → rg-015 violation.
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => '{"caption":"oops","cached":false}',
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('invalid_description_envelope', $result->get_error_code());
        $this->assertSame(502, $result->get_error_data()['status'] ?? null);
    }

    public function testUpstreamErrorStatusPassesThroughUnwrapped(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');

        // Backend rejects an unsupported MIME with 415 — the proxy must forward
        // it verbatim, not re-wrap it as a 502 envelope error.
        $this->queueHttpResponse(array(
            'response' => array('code' => 415, 'message' => 'Unsupported Media Type'),
            'body'     => '{"detail":"unsupported image type"}',
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(415, $result->get_status());

        $usage = (new DescriptionBudgetService())->usage_summary();
        $errors = (new DescriptionBudgetService())->recent_errors();
        $this->assertSame(1, $usage['attempts']);
        $this->assertSame(1, $usage['failures']);
        $this->assertSame('upstream_http_415', $errors[0]['error_code']);
    }
}
