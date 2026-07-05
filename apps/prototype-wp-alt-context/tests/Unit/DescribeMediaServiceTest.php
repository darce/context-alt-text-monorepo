<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
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

        // The 'request' envelope carries tenant_id + media_id + inert wp context.
        $this->assertStringContainsString("name=\"request\"\r\n", $body);
        $this->assertMatchesRegularExpression('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body);
        preg_match('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body, $m);
        $envelope = json_decode($m[1], true);
        $this->assertSame(self::currentTenantId(), $envelope['tenant_id']);
        $this->assertSame(42, $envelope['media_id']);
        $this->assertIsArray($envelope['context']);
        $this->assertSame('http://acx.test', $envelope['context']['site_url']);
        $this->assertSame('Photo 42', $envelope['context']['title']);
        $this->assertSame('42.jpg', $envelope['context']['filename']);
        // No top-level keys the backend's extra='forbid' envelope rejects.
        $this->assertSame(array('tenant_id', 'media_id', 'context'), array_keys($envelope));

        // Response is passed through unchanged.
        $data = $result->get_data();
        $this->assertSame('A photo.', $data['alt_text_draft']);
        $this->assertFalse($data['cached']);
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
    }
}
