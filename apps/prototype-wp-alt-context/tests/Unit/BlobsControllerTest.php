<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\BlobsController;
use AltContext\Api\BlobUrlRewriter;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\BlobsController
 */
class BlobsControllerTest extends TestCase
{
    public function testServeFaceThumbProxiesCropQueryToRecognitionService(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.example.test');
        $this->setOption('acx_recognition_source', 'service');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'headers' => ['content-type' => 'image/jpeg'],
            'body' => 'jpeg-bytes',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/face-thumbs/job-x/42', [
            'job_id' => 'job-x',
            'media_id' => '42',
            'x' => 1,
            'y' => 2,
            'width' => 30,
            'height' => 40,
        ]);

        $response = (new BlobsController())->serve_face_thumb($request);

        $this->assertSame(200, $response->get_status());
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame(
            'https://api.example.test/recognition/face-thumbs/job-x/42?x=1&y=2&width=30&height=40',
            $calls[0]['url']
        );
        $this->assertSame('test-key', $calls[0]['args']['headers']['X-API-Key']);
    }

    public function testVerifyFaceThumbTokenBindsCropParameters(): void
    {
        $expires = time() + 300;
        $token = BlobUrlRewriter::sign(
            'job-x',
            '42',
            $expires,
            'face-thumbs',
            ['x' => 1, 'y' => 2, 'width' => 30, 'height' => 40]
        );
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/face-thumbs/job-x/42', [
            'job_id' => 'job-x',
            'media_id' => '42',
            'x' => 1,
            'y' => 2,
            'width' => 31,
            'height' => 40,
            'expires' => $expires,
            'token' => $token,
        ]);

        $result = (new BlobsController())->verify_blob_token($request);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('recognition_blob_token_invalid', $result->get_error_code());
    }

    /**
     * BR-137: non-loopback blob proxy must use wp_safe_remote_get.
     * Data-driven so a fixture-host-only chooser goes RED (R4G-BR-02).
     *
     * @dataProvider nonLoopbackBlobBaseProvider
     */
    public function testBlobUsesSafeRemoteGetForNonLoopbackHttpsBase(string $baseUrl): void
    {
        $this->setOption('acx_recognition_url', $baseUrl);
        $this->setOption('acx_recognition_source', 'service');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'headers' => ['content-type' => 'image/jpeg'],
            'body' => 'jpeg-bytes',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/blobs/job-x/42', [
            'job_id' => 'job-x',
            'media_id' => '42',
        ]);
        (new BlobsController())->serve_blob($request);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $parsedHost = parse_url($baseUrl, PHP_URL_HOST);
        $host       = is_string($parsedHost) && '' !== $parsedHost ? $parsedHost : $baseUrl;
        $this->assertStringContainsString($host, $calls[0]['url']);
        $this->assertTrue(
            !empty($calls[0]['safe']),
            'non-loopback blob proxy must call wp_safe_remote_get for host ' . $host
        );
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function nonLoopbackBlobBaseProvider(): array
    {
        return [
            'public_dns' => ['https://api.example.test'],
            'unrelated_tld' => ['https://cdn.other-org.example'],
            'bare_public_ipv4' => ['https://203.0.113.10'],
            'bracketed_ipv6' => ['https://[2001:db8::1]'],
        ];
    }

    /**
     * BR-137 sibling: loopback development keeps plain wp_remote_get.
     *
     * @dataProvider loopbackBlobBaseProvider
     */
    public function testBlobUsesRemoteGetForLoopbackBase(string $baseUrl, string $hostNeedle): void
    {
        $this->setOption('acx_recognition_url', $baseUrl);
        $this->setOption('acx_recognition_source', 'service');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'headers' => ['content-type' => 'image/jpeg'],
            'body' => 'jpeg-bytes',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/blobs/job-x/42', [
            'job_id' => 'job-x',
            'media_id' => '42',
        ]);
        (new BlobsController())->serve_blob($request);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString($hostNeedle, $calls[0]['url']);
        $this->assertArrayNotHasKey(
            'safe',
            $calls[0],
            'loopback blob proxy must call wp_remote_get (no safe flag) for ' . $hostNeedle
        );
    }

    /**
     * @return array<string, array{0: string, 1: string}>
     */
    public static function loopbackBlobBaseProvider(): array
    {
        return [
            'ipv4_loopback' => ['http://127.0.0.1:8000', '127.0.0.1'],
            'localhost' => ['http://localhost:8000', 'localhost'],
        ];
    }

    /**
     * BR-137: credentialed blob GET must refuse redirects (redirection => 0).
     * Deleting the key turns this red.
     */
    public function testBlobPassesRedirectionZero(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.example.test');
        $this->setOption('acx_recognition_source', 'service');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'headers' => ['content-type' => 'image/jpeg'],
            'body' => 'jpeg-bytes',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/blobs/job-x/42', [
            'job_id' => 'job-x',
            'media_id' => '42',
        ]);
        (new BlobsController())->serve_blob($request);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertArrayHasKey('redirection', $calls[0]['args']);
        $this->assertSame(
            0,
            $calls[0]['args']['redirection'],
            "credentialed blob GET must pass 'redirection' => 0 so X-API-Key cannot walk on 3xx"
        );
    }

    /**
     * BR-137: a 3xx from the recognition service must surface as a defined
     * error and must not follow Location with the API key.
     */
    public function testBlobSurfaces3xxAsErrorWithoutFollowingRedirect(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.example.test');
        $this->setOption('acx_recognition_source', 'service');
        $this->setOption('acx_recognition_api_key', 'secret-must-not-walk');

        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => [
                'Location' => 'https://attacker.example/collect',
                'content-type' => 'text/html',
            ],
            'body' => '',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'headers' => ['content-type' => 'image/jpeg'],
            'body' => 'stolen-bytes',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/blobs/job-x/42', [
            'job_id' => 'job-x',
            'media_id' => '42',
        ]);
        $result = (new BlobsController())->serve_blob($request);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('recognition_blob_redirect_refused', $result->get_error_code());
        $this->assertSame(502, (int) ($result->get_error_data()['status'] ?? 0));

        $calls = $this->getHttpCalls();
        $this->assertCount(
            1,
            $calls,
            'must not follow redirect — second call would carry X-API-Key to attacker'
        );
        $this->assertSame(0, $calls[0]['args']['redirection'] ?? null);
        $this->assertSame(
            'secret-must-not-walk',
            $calls[0]['args']['headers']['X-API-Key'] ?? null
        );
        $this->assertStringNotContainsString('attacker.example', $calls[0]['url']);
    }
}
