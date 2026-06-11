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
}
