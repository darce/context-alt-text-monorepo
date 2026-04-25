<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AbstractRecognitionProxyController;
use AltContext\Tests\TestCase;

/**
 * Tests for AbstractRecognitionProxyController::proxy_request body_kind=multipart
 * routing (E15-11 Slice 2.1).
 *
 * The legacy URL transport JSON-encodes the body and sets Content-Type:
 * application/json. The multipart transport must instead pass the body
 * array verbatim to wp_remote_request so WordPress sets the boundary
 * Content-Type itself.
 *
 * @covers \AltContext\Api\AbstractRecognitionProxyController
 */
class ProxyRequestMultipartTest extends TestCase
{
    private TestProxyController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->setOption('acx_tier', 'free');
        $this->controller = new TestProxyController();
    }

    public function testJsonBodyKindEncodesAsJsonWithJsonContentType(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'OK'],
            'body' => '{"id":"job-1","status":"pending"}',
        ]);

        $this->controller->callProxyRequest(
            'POST',
            '/recognition/analyze',
            ['tenant_id' => 'tenant-a', 'media_items' => []],
        );

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $args = $calls[0]['args'];
        $this->assertSame('application/json', $args['headers']['Content-Type'] ?? null);
        $this->assertIsString($args['body']);
        $decoded = json_decode($args['body'], true);
        $this->assertSame('tenant-a', $decoded['tenant_id'] ?? null);
    }

    public function testMultipartBodyKindPassesArrayBodyAndDropsJsonContentType(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'OK'],
            'body' => '{"id":"job-2","status":"pending"}',
        ]);

        $body = [
            'request' => json_encode(['tenant_id' => 'tenant-a']),
            'image_42' => 'fake-bytes',
        ];

        $this->controller->callProxyRequest(
            'POST',
            '/recognition/analyze/multipart',
            $body,
            [],
            'auto',
            'multipart',
        );

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $args = $calls[0]['args'];

        $this->assertIsArray(
            $args['body'],
            'multipart body must be an array so WordPress sets the multipart boundary itself'
        );
        $this->assertSame($body, $args['body']);

        // Content-Type must NOT be application/json — wp_remote_request will
        // set the multipart/form-data boundary Content-Type itself when body
        // is an array. Allow it to be either absent or a multipart value.
        $contentType = $args['headers']['Content-Type'] ?? null;
        $this->assertTrue(
            $contentType === null || str_starts_with((string) $contentType, 'multipart/'),
            'multipart requests must not declare Content-Type: application/json (got: '
            . var_export($contentType, true) . ')'
        );

        // Auth header still required.
        $this->assertSame('test-key', $args['headers']['X-API-Key'] ?? null);
    }

    public function testUnknownBodyKindRejectedWithWpError(): void
    {
        $result = $this->controller->callProxyRequest(
            'POST',
            '/recognition/analyze',
            ['tenant_id' => 'tenant-a'],
            [],
            'auto',
            'cbor',
        );
        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('recognition_invalid_body_kind', $result->get_error_code());
        $this->assertSame([], $this->getHttpCalls());
    }
}


/**
 * Test-only concrete subclass that exposes the protected proxy_request
 * helper so the multipart routing branch can be exercised directly.
 */
class TestProxyController extends AbstractRecognitionProxyController
{
    public function register_routes(): void
    {
        // No-op for tests; we exercise proxy_request directly.
    }

    public function callProxyRequest(
        string $method,
        string $path,
        array $body = [],
        array $query = [],
        string $request_class = 'auto',
        string $body_kind = 'json'
    ) {
        return $this->proxy_request($method, $path, $body, $query, $request_class, $body_kind);
    }
}
