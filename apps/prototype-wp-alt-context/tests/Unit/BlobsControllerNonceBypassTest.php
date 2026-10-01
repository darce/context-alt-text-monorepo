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

    if (!function_exists('remove_filter')) {
        function remove_filter($hook_name, $callback, $priority = 10): bool
        {
            if (empty($GLOBALS['__ac_filters'][$hook_name][$priority])) {
                return false;
            }

            $removed = false;
            foreach ($GLOBALS['__ac_filters'][$hook_name][$priority] as $index => $data) {
                if ($data['callback'] === $callback) {
                    unset($GLOBALS['__ac_filters'][$hook_name][$priority][$index]);
                    $removed = true;
                }
            }

            if (empty($GLOBALS['__ac_filters'][$hook_name][$priority])) {
                unset($GLOBALS['__ac_filters'][$hook_name][$priority]);
            }
            if (empty($GLOBALS['__ac_filters'][$hook_name])) {
                unset($GLOBALS['__ac_filters'][$hook_name]);
            }

            return $removed;
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
    private bool $hadWpGlobal = false;
    private $originalWpGlobal = null;

    protected function setUp(): void
    {
        parent::setUp();
        $this->hadWpGlobal = array_key_exists('wp', $GLOBALS);
        $this->originalWpGlobal = $this->hadWpGlobal ? $GLOBALS['wp'] : null;
    }

    protected function tearDown(): void
    {
        unset($_SERVER['REQUEST_URI']);
        unset($GLOBALS['__ac_current_user_id']);
        if ($this->hadWpGlobal) {
            $GLOBALS['wp'] = $this->originalWpGlobal;
        } else {
            unset($GLOBALS['wp']);
        }
        parent::tearDown();
    }

    public function testReturnsNullWhenNonceErrorAndDispatchedRouteIsBlobRoute(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42?expires=1&token=abc';
        $this->setDispatchedRoute('/acx/v1/recognition/blobs/job-x/42');
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertNull($result);
    }

    public function testCookieAuthWithoutNonceRestoresViewerBeforeBlobTokenCheck(): void
    {
        $GLOBALS['__ac_current_user_id'] = 17;
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/private-media?expires=1&token=abc';
        $this->setDispatchedRoute('/acx/v1/recognition/blobs/job-x/private-media');
        $expires = time() + 300;
        $token = BlobUrlRewriter::sign('job-x', 'private-media', $expires);
        $controller = new BlobsController();
        $controller->register_routes();

        // Model rest_cookie_check_errors()'s cookie-authenticated, no-nonce
        // branch: it clears the current user and returns true.
        $cookieAuthFilter = static function ($authResult) {
            $GLOBALS['__ac_current_user_id'] = 0;
            return true;
        };
        add_filter('rest_authentication_errors', $cookieAuthFilter, 100);

        try {
            $authResult = apply_filters('rest_authentication_errors', null);
        } finally {
            remove_filter('rest_authentication_errors', $cookieAuthFilter, 100);
        }
        $this->assertFalse(has_filter('rest_authentication_errors', $cookieAuthFilter));
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

    public function testReturnsNullWhenNonceErrorAndDispatchedRouteIsFaceThumbRoute(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/face-thumbs/job-x/42?x=1&y=2&width=30&height=40&expires=1&token=abc';
        $this->setDispatchedRoute('/acx/v1/recognition/face-thumbs/job-x/42');
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertNull($result);
    }

    public function testReturnsErrorUntouchedWhenDispatchedRouteIsNotBlobRoute(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/jobs/123';
        $this->setDispatchedRoute('/acx/v1/recognition/jobs/123');
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertSame($error, $result);
    }

    public function testDoesNotBypassWhenBlobPrefixAppearsOnlyInQueryString(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/wp/v2/media?next=/wp-json/acx/v1/recognition/blobs/job-x/42';
        $this->setDispatchedRoute('/wp/v2/media');
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertSame($error, $result);
    }

    public function testReturnsErrorUntouchedForNonNonceErrorCodes(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42';
        $this->setDispatchedRoute('/acx/v1/recognition/blobs/job-x/42');
        $error = new WP_Error('rest_forbidden', 'Forbidden', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertSame($error, $result);
    }

    public function testPassesThroughNullWhenThereIsNoUpstreamError(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42';
        $this->setDispatchedRoute('/acx/v1/recognition/blobs/job-x/42');

        $result = BlobsController::maybe_bypass_nonce_for_blob_route(null);

        $this->assertNull($result);
    }

    public function testPassesThroughTrueWhenAuthAlreadySucceeded(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42';
        $this->setDispatchedRoute('/acx/v1/recognition/blobs/job-x/42');

        $result = BlobsController::maybe_bypass_nonce_for_blob_route(true);

        $this->assertTrue($result);
    }

    public function testReturnsErrorWhenDispatchedRouteIsMissing(): void
    {
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/42';
        $GLOBALS['wp'] = (object) ['query_vars' => []];
        $error = new WP_Error('rest_cookie_invalid_nonce', 'Cookie check failed', ['status' => 403]);

        $result = BlobsController::maybe_bypass_nonce_for_blob_route($error);

        $this->assertSame($error, $result);
    }

    public function testDoesNotRestoreViewerWhenBlobPathDispatchesAnotherRoute(): void
    {
        $GLOBALS['__ac_current_user_id'] = 17;
        $_SERVER['REQUEST_URI'] = '/wp-json/acx/v1/recognition/blobs/job-x/private-media?rest_route=/wp/v2/users';
        $this->setDispatchedRoute('/wp/v2/users');
        $controller = new BlobsController();
        $controller->register_routes();

        $cookieAuthFilter = static function ($authResult) {
            $GLOBALS['__ac_current_user_id'] = 0;
            return true;
        };
        add_filter('rest_authentication_errors', $cookieAuthFilter, 100);
        try {
            $authResult = apply_filters('rest_authentication_errors', null);
        } finally {
            remove_filter('rest_authentication_errors', $cookieAuthFilter, 100);
        }

        $this->assertFalse(has_filter('rest_authentication_errors', $cookieAuthFilter));
        $this->assertTrue($authResult);
        $this->assertSame(0, get_current_user_id());
    }

    private function setDispatchedRoute(string $route): void
    {
        $GLOBALS['wp'] = (object) ['query_vars' => ['rest_route' => $route]];
    }
}
}
