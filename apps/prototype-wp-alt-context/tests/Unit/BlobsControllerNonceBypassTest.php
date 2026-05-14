<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\BlobsController;
use AltContext\Tests\TestCase;
use WP_Error;

/**
 * @covers \AltContext\Api\BlobsController::maybe_bypass_nonce_for_blob_route
 */
class BlobsControllerNonceBypassTest extends TestCase
{
    protected function tearDown(): void
    {
        unset($_SERVER['REQUEST_URI']);
        parent::tearDown();
    }

    public function testReturnsNullWhenNonceErrorAndUriMatchesBlobRoute(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42?expires=1&token=abc';
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertNull($result);
    }

    public function testReturnsNullWhenNonceErrorAndUriMatchesFaceThumbRoute(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/face-thumbs/job-x/42?x=1&y=2&width=30&height=40&expires=1&token=abc';
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertNull($result);
    }

    public function testReturnsErrorUntouchedWhenUriDoesNotMatchBlobRoute(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/jobs/123';
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertSame($error, $result);
    }

    public function testDoesNotBypassWhenBlobPrefixAppearsOnlyInQueryString(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/wp/v2/media?next=/wp-json/acx/v1/recognition/blobs/job-x/42';
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertSame($error, $result);
    }

    public function testReturnsErrorUntouchedForNonNonceErrorCodes(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42';
        $error = new WP_Error('rest_forbidden', 'Forbidden', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertSame($error, $result);
    }

    public function testPassesThroughNullWhenThereIsNoUpstreamError(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42';

        $result = BlobsController::maybe_bypass_nonce_for_blob_route(null);

        $this->assertNull($result);
    }

    public function testPassesThroughTrueWhenAuthAlreadySucceeded(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42';

        $result = BlobsController::maybe_bypass_nonce_for_blob_route(true);

        $this->assertTrue($result);
    }

    public function testReturnsErrorWhenRequestUriIsMissing(): void
    {
        unset($_SERVER['REQUEST_URI']);
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertSame($error, $result);
    }
}
