<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Api\PublicDemoDescribeController;
use AltContext\PublicSite\PublicDemoErrorCode;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

final class PublicDemoDescribeControllerTest extends TestCase
{
    private DescribeController $pipeline;
    private PublicDemoDescribeController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $_SERVER['REMOTE_ADDR'] = '203.0.113.42';
        $this->pipeline = new class extends DescribeController {
            /** @var list<list<int>> */
            public array $submissions = [];
            public int $nextRun = 1;
            public string $status = 'running';

            public function __construct()
            {
            }

            public function submit_describe_run(WP_REST_Request $request): WP_REST_Response|WP_Error
            {
                /** @var list<int> $ids */
                $ids = $request->get_param('media_ids');
                $this->submissions[] = $ids;

                return new WP_REST_Response(['run_id' => 'public-run-' . $this->nextRun++], 202);
            }

            public function get_describe_run_status(WP_REST_Request $request): WP_REST_Response|WP_Error
            {
                return new WP_REST_Response([
                    'run_id' => (string) $request->get_param('run_id'),
                    'status' => $this->status,
                ]);
            }

            public function get_describe_run_items(WP_REST_Request $request): WP_REST_Response|WP_Error
            {
                return new WP_REST_Response(['items' => [[
                    'media_id' => 41,
                    'alt_text_draft' => 'A person walking beside a lake.',
                ]]]);
            }
        };
        $this->controller = new PublicDemoDescribeController($this->pipeline);
    }

    protected function tearDown(): void
    {
        unset($_SERVER['REMOTE_ADDR']);
        parent::tearDown();
    }

    public function testMissingNonceIsRejected(): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $result = $this->controller->check_public_permission(new WP_REST_Request('POST'));

        self::assertInstanceOf(WP_Error::class, $result);
        self::assertSame(PublicDemoErrorCode::INVALID_NONCE, $result->get_error_code());
        self::assertSame(403, $result->get_error_data()['status']);
    }

    public function testRoutesUseExplicitPublicPermissionCallback(): void
    {
        $this->controller->register_routes();

        self::assertCount(2, $GLOBALS['__ac_rest_routes']);
        foreach ($GLOBALS['__ac_rest_routes'] as $route) {
            self::assertSame('acx/v1', $route['namespace']);
            self::assertIsCallable($route['args']['permission_callback'] ?? null);
            self::assertNotSame('__return_true', $route['args']['permission_callback']);
        }
        self::assertSame('/public/demo/describe', $GLOBALS['__ac_rest_routes'][0]['route']);
        self::assertSame('/public/demo/describe/runs/(?P<run_id>[^/]+)', $GLOBALS['__ac_rest_routes'][1]['route']);
    }

    public function testDisabledFlagFailsClosed(): void
    {
        $request = $this->authorizedRequest('POST');
        $result = $this->controller->check_public_permission($request);

        self::assertInstanceOf(WP_Error::class, $result);
        self::assertSame(PublicDemoErrorCode::DISABLED, $result->get_error_code());
        self::assertSame(403, $result->get_error_data()['status']);
    }

    public function testNonAllowlistedMediaIsRejectedWithTypedCode(): void
    {
        $this->enable([41]);
        $request = $this->authorizedRequest('POST', ['media_id' => 42]);
        $result = $this->controller->submit($request);

        self::assertInstanceOf(WP_Error::class, $result);
        self::assertSame(PublicDemoErrorCode::MEDIA_NOT_ALLOWED, $result->get_error_code());
        self::assertSame(403, $result->get_error_data()['status']);
        self::assertSame([], $this->pipeline->submissions);
    }

    public function testPerIpRateLimitReturnsRetryAfterHeader(): void
    {
        $this->enable([41]);

        for ($attempt = 0; $attempt < 3; $attempt++) {
            $result = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
            self::assertSame(202, $result->get_status());
            unset($GLOBALS['__ac_options']['acx_public_demo_inflight']);
        }

        $limited = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        self::assertInstanceOf(WP_REST_Response::class, $limited);
        self::assertSame(429, $limited->get_status());
        self::assertSame(PublicDemoErrorCode::RATE_LIMITED, $limited->get_data()['code']);
        self::assertArrayHasKey('Retry-After', $limited->get_headers());
    }

    public function testConcurrencyBulkheadAllowsOnlyOneInflightRun(): void
    {
        $this->enable([41]);
        $first = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        $second = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));

        self::assertSame(202, $first->get_status());
        self::assertSame(429, $second->get_status());
        self::assertSame(PublicDemoErrorCode::BUSY, $second->get_data()['code']);
        self::assertSame('5', $second->get_headers()['Retry-After']);
        self::assertCount(1, $this->pipeline->submissions);
    }

    public function testHappyPathDelegatesToExistingPipelineAndTerminalStatusReleasesBulkhead(): void
    {
        $this->enable([41]);
        $submitted = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));

        self::assertSame([[41]], $this->pipeline->submissions);
        self::assertSame('public-run-1', $submitted->get_data()['run_id']);

        $this->pipeline->status = 'completed';
        $status = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));
        self::assertSame('completed', $status->get_data()['status']);
        self::assertSame('A person walking beside a lake.', $status->get_data()['description']);
        self::assertArrayNotHasKey('acx_public_demo_inflight', $GLOBALS['__ac_options']);
    }

    public function testDailyCapReturnsRetryAfterWithoutDelegating(): void
    {
        $this->enable([41]);
        $this->setOption('acx_public_demo_daily_cap', 1);
        $this->setOption('acx_public_demo_daily_usage', ['date' => gmdate('Ymd'), 'count' => 1]);

        $limited = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        self::assertSame(429, $limited->get_status());
        self::assertSame(PublicDemoErrorCode::DAILY_CAP_REACHED, $limited->get_data()['code']);
        self::assertArrayHasKey('Retry-After', $limited->get_headers());
        self::assertSame([], $this->pipeline->submissions);
    }

    /** @param list<int> $ids */
    private function enable(array $ids): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $this->setOption('acx_public_demo_media_ids', $ids);
        $this->setOption('acx_public_demo_daily_cap', 50);
    }

    /** @param array<string,mixed> $params */
    private function authorizedRequest(string $method, array $params = []): WP_REST_Request
    {
        $request = new WP_REST_Request($method, '', $params);
        $request->set_header('X-WP-Nonce', 'nonce-wp_rest');

        return $request;
    }
}
