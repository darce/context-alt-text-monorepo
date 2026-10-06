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
    protected function tearDown(): void
    {
        unset($GLOBALS['__ac_current_user_id']);
        parent::tearDown();
    }

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

    public function testSignedBlobUrlExpiresWithinFiveMinutes(): void
    {
        $before = time();
        $url = BlobUrlRewriter::rewrite_string('/recognition/blobs/job-x/private-media');
        $after = time();
        $parts = parse_url($url);
        $query = [];
        parse_str($parts['query'] ?? '', $query);

        $this->assertGreaterThan($before, (int) ($query['expires'] ?? 0));
        $this->assertLessThanOrEqual(
            $after + 300,
            (int) ($query['expires'] ?? 0),
            'Signed blob URLs should expire within five minutes.'
        );
    }

    public function testBlobTokenRequiresTheViewerThatReceivedIt(): void
    {
        $GLOBALS['__ac_current_user_id'] = 17;
        $expires = time() + 300;
        $token = BlobUrlRewriter::sign('job-x', 'private-media', $expires);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/blobs/job-x/private-media', [
            'job_id' => 'job-x',
            'media_id' => 'private-media',
            'expires' => $expires,
            'token' => $token,
        ]);
        $controller = new BlobsController();

        $this->assertTrue($controller->verify_blob_token($request));

        $GLOBALS['__ac_current_user_id'] = 18;
        $result = $controller->verify_blob_token($request);
        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('recognition_blob_token_invalid', $result->get_error_code());
    }

    public function testBlobTokenRequiresAnAuthenticatedViewer(): void
    {
        $GLOBALS['__ac_current_user_id'] = 0;
        $expires = time() + 300;
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/blobs/job-x/private-media', [
            'job_id' => 'job-x',
            'media_id' => 'private-media',
            'expires' => $expires,
            'token' => BlobUrlRewriter::sign('job-x', 'private-media', $expires),
        ]);

        $result = (new BlobsController())->verify_blob_token($request);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('recognition_blob_auth_required', $result->get_error_code());
    }

    /**
     * BR-137: admitted non-loopback blob proxy uses wp_safe_remote_get;
     * non-global literals fail before HTTP.
     * Data-driven so a fixture-host-only chooser goes RED (R4G-BR-02).
     *
     * @dataProvider nonLoopbackBlobBaseProvider
     */
    public function testBlobUsesSafeRemoteGetForNonLoopbackHttpsBase(string $baseUrl, bool $expectedDenied = false): void
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
        $result = (new BlobsController())->serve_blob($request);

        if ($expectedDenied) {
            $this->assertInstanceOf(\WP_Error::class, $result);
            // BlobsController:302-308 wraps the acx_egress_denied error while
            // preserving its message; it never serves the queued image bytes.
            $this->assertSame('recognition_blob_unavailable', $result->get_error_code());
            $this->assertSame('Recognition host resolves to a non-public address.', $result->get_error_message());
            $this->assertCount(0, $this->getHttpCalls());
            return;
        }

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
     * @return array<string, array{0: string, 1: bool}>
     */
    public static function nonLoopbackBlobBaseProvider(): array
    {
        return [
            'public_dns' => ['https://api.example.test', false],
            'unrelated_tld' => ['https://cdn.other-org.example', false],
            'bare_public_ipv4' => ['https://203.0.113.10', false],
            'global_ipv4' => ['https://93.184.216.34', false],
            'public_ipv6' => ['https://[2606:4700:4700::1111]', false],
            'bracketed_ipv6' => ['https://[2001:db8::1]', true],
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
