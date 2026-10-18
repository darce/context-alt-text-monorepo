<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AbstractRecognitionProxyController;
use AltContext\Tests\TestCase;

/**
 * Tests for AbstractRecognitionProxyController::proxy_request body_kind=multipart
 * routing (E15-11 Slice 2.1, fixed by BR-09).
 *
 * The legacy URL transport JSON-encodes the body and sets Content-Type:
 * application/json. The multipart transport must build a real
 * multipart/form-data body string with explicit boundaries — wp_remote_request
 * does NOT auto-build multipart from a plain array, contrary to the
 * original assumption (caught by BR-09).
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

    public function testMultipartBodyKindBuildsRealMultipartBody(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'OK'],
            'body' => '{"id":"job-2","status":"pending"}',
        ]);

        $request_json = json_encode(['tenant_id' => 'tenant-a']);
        $image_bytes  = "\x89PNG\r\n\x1a\nfake-png-bytes";
        $body = [
            'request'  => $request_json,
            'image_42' => [
                'filename'     => 'a.png',
                'content'      => $image_bytes,
                'content_type' => 'image/png',
            ],
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

        // Content-Type must be a real multipart/form-data declaration with a
        // boundary parameter — wp_remote_request does NOT auto-build multipart
        // from an array, so the proxy must build the body string itself.
        $contentType = $args['headers']['Content-Type'] ?? null;
        $this->assertIsString($contentType);
        $this->assertMatchesRegularExpression(
            '#^multipart/form-data;\s*boundary=([A-Za-z0-9_\-]+)$#',
            $contentType,
            'Content-Type must be multipart/form-data with an explicit boundary'
        );

        preg_match('#boundary=([A-Za-z0-9_\-]+)#', $contentType, $matches);
        $boundary = $matches[1];

        // Body must be a string (the serialized multipart payload), not an array.
        $this->assertIsString($args['body']);
        $serialized = $args['body'];

        // Boundary delimiters present.
        $this->assertStringContainsString('--' . $boundary . "\r\n", $serialized);
        $this->assertStringContainsString("\r\n--" . $boundary . "--\r\n", $serialized);

        // 'request' part: form-data field with the JSON envelope.
        $this->assertStringContainsString(
            "Content-Disposition: form-data; name=\"request\"\r\n",
            $serialized
        );
        $this->assertStringContainsString($request_json, $serialized);

        // 'image_42' part: file upload with filename + content-type + bytes.
        $this->assertStringContainsString(
            "Content-Disposition: form-data; name=\"image_42\"; filename=\"a.png\"\r\n",
            $serialized
        );
        $this->assertStringContainsString("Content-Type: image/png\r\n", $serialized);
        $this->assertStringContainsString($image_bytes, $serialized);

        // Auth header still required.
        $this->assertSame('test-key', $args['headers']['X-API-Key'] ?? null);
    }

    public function testMultipartAcceptsScalarPartAsFormField(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'OK'],
            'body' => '{}',
        ]);

        $this->controller->callProxyRequest(
            'POST',
            '/recognition/analyze/multipart',
            ['note' => 'plain string field'],
            [],
            'auto',
            'multipart',
        );

        $args = $this->getHttpCalls()[0]['args'];
        $this->assertIsString($args['body']);
        $this->assertStringContainsString(
            "Content-Disposition: form-data; name=\"note\"\r\n",
            $args['body']
        );
        $this->assertStringContainsString("plain string field", $args['body']);
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
