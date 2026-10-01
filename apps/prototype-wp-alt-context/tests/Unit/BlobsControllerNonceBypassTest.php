<?php

declare(strict_types=1);

namespace {
    if (!function_exists('wp_set_current_user')) {
        function wp_set_current_user($user_id, $user = '')
        {
            $GLOBALS['__ac_current_user_id'] = (int) $user_id;
            return (object) ['ID' => (int) $user_id];
        }
    }
}

namespace AltContext\Tests\Unit {

use AltContext\Api\BlobUrlRewriter;
use AltContext\Api\BlobsController;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\BlobsController::maybe_bypass_nonce_for_blob_route
 * @covers \AltContext\Api\BlobsController::remember_blob_viewer_before_cookie_check
 */
class BlobsControllerNonceBypassTest extends TestCase
{
    protected function tearDown(): void
    {
        unset($_SERVER['REQUEST_URI']);
        unset($GLOBALS['__ac_current_user_id']);
        parent::tearDown();
    }

    public function testReturnsNullWhenNonceErrorAndUriMatchesBlobRoute(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42?expires=1&token=abc';
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertNull($result);
    }

    public function testCookieAuthWithoutNonceRestoresViewerBeforeBlobTokenCheck(): void
    {
        $GLOBALS['__ac_current_user_id'] = 17;
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/private-media?expires=1&token=abc';
        $expires = time() + 300;
        $token = BlobUrlRewriter::sign('job-x', 'private-media', $expires);
        $controller = new BlobsController();
        $controller->register_routes();

        // Model rest_cookie_check_errors()'s cookie-authenticated, no-nonce
        // branch: it clears the current user and returns true.
        add_filter('rest_authentication_errors', static function ($authResult) {
            $GLOBALS['__ac_current_user_id'] = 0;
            return true;
        }, 100);

        $authResult = apply_filters('rest_authentication_errors', null);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/blobs/job-x/private-media', [
            'job_id' => 'job-x',
            'media_id' => 'private-media',
            'expires' => $expires,
            'token' => $token,
        ]);
        $result = $controller->verify_blob_token($request);

        $this->assertTrue($authResult);
        $this->assertSame(17, get_current_user_id());
        $this->assertTrue($result);
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
}
