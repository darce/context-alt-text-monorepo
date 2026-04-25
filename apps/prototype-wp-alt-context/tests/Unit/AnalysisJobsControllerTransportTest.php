<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * Tests for AnalysisJobsController::analyze_media transport switching
 * (E15-11 Slice 2.2).
 *
 * Default (no filter set) is 'multipart' — the analyze controller reads
 * image bytes via get_attached_file and ships them to
 * /recognition/analyze/multipart through the body_kind=multipart proxy
 * path. Setting the acx_recognition_transport filter to 'url' restores
 * the legacy JSON path so managed-host installs that expose media
 * publicly keep working.
 *
 * @covers \AltContext\Api\AnalysisJobsController
 */
class AnalysisJobsControllerTransportTest extends TestCase
{
    private AnalysisJobsController $controller;
    private string $tempDir;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->setOption('acx_tier', 'free');
        $this->controller = new AnalysisJobsController();
        $this->tempDir = sys_get_temp_dir() . '/acx-e15-11-' . uniqid();
        mkdir($this->tempDir, 0o755, true);
    }

    protected function tearDown(): void
    {
        // Best-effort cleanup of temp fixture files.
        if (is_dir($this->tempDir)) {
            foreach (glob($this->tempDir . '/*') as $f) {
                @unlink($f);
            }
            @rmdir($this->tempDir);
        }
        parent::tearDown();
    }

    private function plantAttachment(int $id, string $bytes, string $extension = 'png'): string
    {
        $path = $this->tempDir . "/{$id}.{$extension}";
        file_put_contents($path, $bytes);
        $GLOBALS['__ac_attached_file'][$id] = $path;
        $GLOBALS['__ac_attachment_urls'][$id] = "http://example.test/media/{$id}.{$extension}";
        return $path;
    }

    public function testDefaultTransportIsMultipartAndPostsToMultipartRoute(): void
    {
        $bytes101 = "\x89PNG\r\n\x1a\nfake-101";
        $bytes202 = "\xff\xd8\xff\xe0fake-202";
        $this->plantAttachment(101, $bytes101, 'png');
        $this->plantAttachment(202, $bytes202, 'jpg');

        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'OK'],
            'body' => '{"id":"job-1","status":"pending"}',
        ]);

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $req->set_param('media_ids', [101, 202]);
        $result = $this->controller->analyze_media($req);

        $this->assertNotInstanceOf(\WP_Error::class, $result, var_export($result, true));

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $call = $calls[0];

        $this->assertStringContainsString('/recognition/analyze/multipart', $call['url']);

        $contentType = $call['args']['headers']['Content-Type'] ?? null;
        $this->assertIsString($contentType);
        $this->assertMatchesRegularExpression(
            '#^multipart/form-data;\s*boundary=#',
            $contentType
        );

        $body = $call['args']['body'];
        $this->assertIsString($body);

        // Each image part is present with its bytes embedded literally.
        $this->assertStringContainsString(
            "Content-Disposition: form-data; name=\"image_101\"; filename=",
            $body
        );
        $this->assertStringContainsString($bytes101, $body);
        $this->assertStringContainsString(
            "Content-Disposition: form-data; name=\"image_202\"; filename=",
            $body
        );
        $this->assertStringContainsString($bytes202, $body);

        // The 'request' JSON envelope carries tenant_id only — the recognition
        // service builds MediaItems from the image_<id> parts.
        $this->assertStringContainsString(
            "Content-Disposition: form-data; name=\"request\"\r\n",
            $body
        );
    }

    public function testUrlTransportFilterPreservesLegacyJsonPath(): void
    {
        // Tenant must still get attachments to derive URLs (legacy contract).
        $this->plantAttachment(101, 'irrelevant', 'png');

        add_filter(
            'acx_recognition_transport',
            static fn(string $current): string => 'url',
        );

        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'OK'],
            'body' => '{"id":"job-2","status":"pending"}',
        ]);

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $req->set_param('media_ids', [101]);
        $result = $this->controller->analyze_media($req);
        $this->assertNotInstanceOf(\WP_Error::class, $result, var_export($result, true));

        $call = $this->getHttpCalls()[0];
        $this->assertStringContainsString('/recognition/analyze', $call['url']);
        $this->assertStringNotContainsString('/multipart', $call['url']);

        $this->assertSame(
            'application/json',
            $call['args']['headers']['Content-Type'] ?? null
        );

        $decoded = json_decode((string) $call['args']['body'], true);
        $this->assertSame(101, $decoded['media_items'][0]['media_id'] ?? null);
        $this->assertSame(
            'http://example.test/media/101.png',
            $decoded['media_items'][0]['media_url'] ?? null
        );
    }

    public function testMultipartSkipsItemsWithMissingAttachedFile(): void
    {
        $bytes = "\x89PNGfake";
        $this->plantAttachment(1, $bytes, 'png');
        // 2 has no attached file — get_attached_file returns false; the
        // controller must skip it but still dispatch the others.

        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'OK'],
            'body' => '{"id":"job-3","status":"pending"}',
        ]);

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $req->set_param('media_ids', [1, 2]);
        $result = $this->controller->analyze_media($req);
        $this->assertNotInstanceOf(\WP_Error::class, $result, var_export($result, true));

        $body = $this->getHttpCalls()[0]['args']['body'];
        $this->assertStringContainsString('name="image_1"', $body);
        $this->assertStringNotContainsString('name="image_2"', $body);
    }

    public function testMultipartReturns400WhenAllAttachmentsMissing(): void
    {
        $req = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $req->set_param('media_ids', [9001]);
        $result = $this->controller->analyze_media($req);
        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('no_media_items', $result->get_error_code());
        $this->assertSame([], $this->getHttpCalls());
    }
}
