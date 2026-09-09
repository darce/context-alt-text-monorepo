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
            public mixed $gpuState = 'ready';
            public bool $omitGpuState = false;
            public ?string $itemsRunId = null;
            public int $itemRequests = 0;
            public WP_REST_Response|WP_Error|null $submitResult = null;
            /** @var array<string,mixed> */
            public array $statusData = [];

            public function __construct()
            {
            }

            public function submit_describe_run(WP_REST_Request $request): WP_REST_Response|WP_Error
            {
                /** @var list<int> $ids */
                $ids = $request->get_param('media_ids');
                $this->submissions[] = $ids;
                if (null !== $this->submitResult) {
                    return $this->submitResult;
                }

                $data = [
                    'run_id' => 'public-run-' . $this->nextRun++,
                    'status' => 'pending',
                    'phase' => 'queued',
                    'gpu_state' => $this->gpuState,
                    'completed' => 0,
                    'failed' => 0,
                    'skipped' => 0,
                    'total' => 1,
                    'tenant_id' => 'must-not-leak',
                ];
                if ($this->omitGpuState) {
                    unset($data['gpu_state']);
                }

                return new WP_REST_Response($data, 202);
            }

            public function get_describe_run_status(WP_REST_Request $request): WP_REST_Response|WP_Error
            {
                $data = array_merge([
                    'run_id' => (string) $request->get_param('run_id'),
                    'status' => $this->status,
                    'phase' => 'describing',
                    'gpu_state' => $this->gpuState,
                    'completed' => 0,
                    'failed' => 0,
                    'skipped' => 0,
                    'total' => 1,
                    'tenant_id' => 'must-not-leak',
                ], $this->statusData);
                if ($this->omitGpuState) {
                    unset($data['gpu_state']);
                }

                return new WP_REST_Response($data);
            }

            public function get_describe_run_items(WP_REST_Request $request): WP_REST_Response|WP_Error
            {
                ++$this->itemRequests;
                return new WP_REST_Response([
                    'run_id' => $this->itemsRunId ?? (string) $request->get_param('run_id'),
                    'items' => [[
                        'media_id' => 41,
                        'alt_text_draft' => 'A person walking beside a lake.',
                    ]],
                ]);
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

    public function testSameIdempotencyKeyReturnsExistingRunWithoutCreatingAnother(): void
    {
        $this->enable([41]);
        $first = $this->controller->submit($this->authorizedRequest('POST', [
            'media_id' => 41,
            'idempotency_key' => 'trigger-one-0001',
        ]));
        $retry = $this->controller->submit($this->authorizedRequest('POST', [
            'media_id' => 41,
            'idempotency_key' => 'trigger-one-0001',
        ]));

        self::assertSame(202, $first->get_status());
        self::assertSame(202, $retry->get_status());
        self::assertSame('public-run-1', $first->get_data()['run_id']);
        self::assertSame($first->get_data()['run_id'], $retry->get_data()['run_id']);
        self::assertCount(1, $this->pipeline->submissions);
    }

    public function testDifferentIdempotencyKeyCreatesDistinctRun(): void
    {
        $this->enable([41]);
        $first = $this->controller->submit($this->authorizedRequest('POST', [
            'media_id' => 41,
            'idempotency_key' => 'trigger-one-0001',
        ]));
        unset($GLOBALS['__ac_options']['acx_public_demo_inflight']);
        $second = $this->controller->submit($this->authorizedRequest('POST', [
            'media_id' => 41,
            'idempotency_key' => 'trigger-two-0002',
        ]));

        self::assertSame(202, $first->get_status());
        self::assertSame(202, $second->get_status());
        self::assertNotSame($first->get_data()['run_id'], $second->get_data()['run_id']);
        self::assertCount(2, $this->pipeline->submissions);
    }

    public function testExpiredIdempotencyMappingAllowsAFreshTrigger(): void
    {
        $this->enable([41]);
        $key = 'trigger-expiring';
        $first = $this->controller->submit($this->authorizedRequest('POST', [
            'media_id' => 41,
            'idempotency_key' => $key,
        ]));
        $rateKey = hash('sha256', (string) $_SERVER['REMOTE_ADDR']);
        $idempotencyKey = (new \ReflectionMethod(PublicDemoDescribeController::class, 'idempotency_transient_key'));
        $idempotencyKey->setAccessible(true);
        $transient = $idempotencyKey->invoke($this->controller, $rateKey, $key);
        $GLOBALS['__ac_transients'][$transient]['expires_at'] = time() - 1;
        unset($GLOBALS['__ac_options']['acx_public_demo_inflight']);

        $second = $this->controller->submit($this->authorizedRequest('POST', [
            'media_id' => 41,
            'idempotency_key' => $key,
        ]));

        self::assertSame(202, $first->get_status());
        self::assertSame(202, $second->get_status());
        self::assertNotSame($first->get_data()['run_id'], $second->get_data()['run_id']);
        self::assertCount(2, $this->pipeline->submissions);
    }

    public function testLockCannotBeAcquiredWhileLiveOwnerIsHeld(): void
    {
        $acquire = new \ReflectionMethod(PublicDemoDescribeController::class, 'acquire_lock');
        $acquire->setAccessible(true);
        $first = $acquire->invoke($this->controller, 'acx_public_demo_test_lock', 5);
        $second = $acquire->invoke($this->controller, 'acx_public_demo_test_lock', 5);

        self::assertIsString($first);
        self::assertFalse($second);
    }

    public function testStaleLockReleaseCannotRemoveReplacementOwner(): void
    {
        $acquire = new \ReflectionMethod(PublicDemoDescribeController::class, 'acquire_lock');
        $release = new \ReflectionMethod(PublicDemoDescribeController::class, 'release_lock');
        $acquire->setAccessible(true);
        $release->setAccessible(true);
        $option = 'acx_public_demo_test_lock';
        $first = $acquire->invoke($this->controller, $option, 5);
        self::assertIsString($first);
        $replacement = [
            'run_id' => '',
            'token' => 'replacement-token',
            'expires_at' => time() + 5,
        ];
        $GLOBALS['__ac_option_before_delete'][$option] = static function () use ($option, $replacement): void {
            unset($GLOBALS['__ac_option_before_delete'][$option]);
            $GLOBALS['__ac_options'][$option] = $replacement;
        };

        $release->invoke($this->controller, $option, $first);

        self::assertSame($replacement, $GLOBALS['__ac_options'][$option]);
    }

    public function testLockCanBeReacquiredAfterTtlExpiry(): void
    {
        $acquire = new \ReflectionMethod(PublicDemoDescribeController::class, 'acquire_lock');
        $acquire->setAccessible(true);
        $option = 'acx_public_demo_test_lock';
        $first = $acquire->invoke($this->controller, $option, 5);
        self::assertIsString($first);
        $GLOBALS['__ac_options'][$option]['expires_at'] = time() - 1;

        $second = $acquire->invoke($this->controller, $option, 5);

        self::assertIsString($second);
        self::assertNotSame($first, $second);
        self::assertSame($second, $GLOBALS['__ac_options'][$option]['token']);
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
        self::assertSame(
            ['run_id', 'status', 'phase', 'gpu_state', 'progress', 'deadline_seconds'],
            array_keys($submitted->get_data())
        );
        self::assertSame(['done' => 0, 'total' => 1], $submitted->get_data()['progress']);

        $this->pipeline->status = 'completed';
        $this->pipeline->statusData = ['phase' => 'complete', 'completed' => 1];
        $status = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));
        self::assertSame('completed', $status->get_data()['status']);
        self::assertSame('A person walking beside a lake.', $status->get_data()['description']);
        self::assertArrayNotHasKey('tenant_id', $status->get_data());
        self::assertArrayNotHasKey('acx_public_demo_inflight', $GLOBALS['__ac_options']);
    }

    public function testAgedLeaseWithLiveBackendRunIsRenewedAndRejectsAdmission(): void
    {
        $this->enable([41]);
        $this->setOption('acx_public_demo_inflight', [
            'run_id' => 'still-live',
            'media_id' => 41,
            'token' => 'old-token',
            'expires_at' => time() - 1,
        ]);

        $result = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));

        self::assertSame(429, $result->get_status());
        self::assertSame(PublicDemoErrorCode::BUSY, $result->get_data()['code']);
        self::assertSame('still-live', $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);
        self::assertGreaterThan(time(), $GLOBALS['__ac_options']['acx_public_demo_inflight']['expires_at']);
        self::assertSame([], $this->pipeline->submissions);
    }

    public function testAgedLeaseWithTerminalBackendRunAllowsAdmission(): void
    {
        $this->enable([41]);
        $this->pipeline->status = 'completed';
        $this->pipeline->statusData = ['phase' => 'complete', 'completed' => 1];
        $this->setOption('acx_public_demo_inflight', [
            'run_id' => 'finished-run',
            'media_id' => 41,
            'token' => 'old-token',
            'expires_at' => time() - 1,
        ]);

        $result = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));

        self::assertSame(202, $result->get_status());
        self::assertSame([41], $this->pipeline->submissions[0]);
        self::assertSame('public-run-1', $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);
    }

    /** @dataProvider malformedExpiredTerminalProvider */
    public function testR5MalformedExpiredTerminalMustNotAdmitPaidWork(array $overrides): void
    {
        $this->enable([41]);
        $this->pipeline->status = 'completed';
        $this->pipeline->statusData = array_merge(['phase' => 'complete', 'completed' => 1], $overrides);
        $this->setOption('acx_public_demo_inflight', [
            'run_id' => 'finished-run', 'media_id' => 41,
            'token' => 'old-token', 'expires_at' => time() - 1,
        ]);

        $result = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));

        self::assertSame(429, $result->get_status());
        self::assertSame(PublicDemoErrorCode::BUSY, $result->get_data()['code']);
        self::assertSame([], $this->pipeline->submissions);
        self::assertSame('old-token', $GLOBALS['__ac_options']['acx_public_demo_inflight']['token']);
    }

    public static function malformedExpiredTerminalProvider(): iterable
    {
        yield 'fractional completed' => [['completed' => 0.5]];
        yield 'live phase' => [['phase' => 'describing']];
        yield 'missing phase' => [['phase' => null]];
        yield 'invalid GPU state' => [['gpu_state' => 'invalid']];
        yield 'missing counter' => [['failed' => null]];
        yield 'unfinished completed run' => [['completed' => 0]];
        yield 'completed run with failed items' => [['completed' => 0, 'failed' => 1]];
    }

    public function testR5TerminalReleaseMustNotDeleteReplacementLease(): void
    {
        $this->enable([41]);
        $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        $this->pipeline->status = 'completed';
        $this->pipeline->statusData = ['phase' => 'complete', 'completed' => 1];
        $GLOBALS['__ac_options']['acx_public_demo_inflight']['expires_at'] = time() - 1;
        $replacement = null;
        // Pause the old status request after its ownership read, immediately
        // before deletion, and let a second request replace the expired lease.
        $GLOBALS['__ac_option_before_delete']['acx_public_demo_inflight'] = function () use (&$replacement): void {
            unset($GLOBALS['__ac_option_before_delete']['acx_public_demo_inflight']);
            $second = new PublicDemoDescribeController($this->pipeline);
            $response = $second->submit($this->authorizedRequest('POST', ['media_id' => 41]));
            self::assertSame(202, $response->get_status());
            $replacement = $GLOBALS['__ac_options']['acx_public_demo_inflight'];
        };

        $status = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));
        self::assertSame(200, $status->get_status());
        $third = new PublicDemoDescribeController($this->pipeline);
        $response = $third->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        self::assertSame(429, $response->get_status());
        self::assertSame($replacement, $GLOBALS['__ac_options']['acx_public_demo_inflight']);
        self::assertCount(2, $this->pipeline->submissions);
    }

    public function testR6RenewalMustNotOverwriteReplacementLease(): void
    {
        $this->enable([41]);
        $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        $GLOBALS['__ac_options']['acx_public_demo_inflight']['expires_at'] = time() - 1;
        $replacement = null;
        // Interleave at the write boundary for both update_option and SQL CAS.
        $GLOBALS['__ac_option_before_update']['acx_public_demo_inflight'] = function () use (&$replacement): void {
            unset($GLOBALS['__ac_option_before_update']['acx_public_demo_inflight']);
            $this->pipeline->status = 'completed';
            $this->pipeline->statusData = ['phase' => 'complete', 'completed' => 1];
            self::assertSame(200, $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']))->get_status());
            // The backend status request outlived the five-second guard.
            $GLOBALS['__ac_options']['acx_public_demo_inflight_reconcile']['expires_at'] = time() - 1;
            $second = new PublicDemoDescribeController($this->pipeline);
            self::assertSame(202, $second->submit($this->authorizedRequest('POST', ['media_id' => 41]))->get_status());
            $replacement = $GLOBALS['__ac_options']['acx_public_demo_inflight'];
        };

        $_SERVER['REMOTE_ADDR'] = '203.0.113.43';
        $reconciler = new PublicDemoDescribeController($this->pipeline);
        self::assertSame(429, $reconciler->submit($this->authorizedRequest('POST', ['media_id' => 41]))->get_status());
        $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));
        $_SERVER['REMOTE_ADDR'] = '203.0.113.44';
        $third = new PublicDemoDescribeController($this->pipeline);
        self::assertSame(429, $third->submit($this->authorizedRequest('POST', ['media_id' => 41]))->get_status());
        self::assertSame($replacement, $GLOBALS['__ac_options']['acx_public_demo_inflight']);
        self::assertCount(2, $this->pipeline->submissions);
    }

    public function testR7AcceptedIdSurvivesReconciliationGuardContention(): void
    {
        $this->enable([41]);
        // Pause request one after backend acceptance, before recording its ID.
        $acquire = new \ReflectionMethod(PublicDemoDescribeController::class, 'acquire_inflight_bulkhead');
        $started = new \ReflectionMethod(PublicDemoDescribeController::class, 'mark_submission_started');
        $bind = new \ReflectionMethod(PublicDemoDescribeController::class, 'bind_inflight_run');
        foreach ([$acquire, $started, $bind] as $method) {
            $method->setAccessible(true);
        }
        self::assertTrue($acquire->invoke($this->controller, 41));
        self::assertTrue($started->invoke($this->controller));
        $accepted = $this->pipeline->submit_describe_run($this->authorizedRequest('POST', ['media_ids' => [41]]));
        $runId = $accepted->get_data()['run_id'];
        $bound = null;

        // Request two holds the reconciliation guard when request one resumes.
        $GLOBALS['__ac_get_option_before_read']['acx_public_demo_inflight'] = function () use ($bind, $runId, &$bound): void {
            unset($GLOBALS['__ac_get_option_before_read']['acx_public_demo_inflight']);
            self::assertGreaterThan(time(), $GLOBALS['__ac_options']['acx_public_demo_inflight_reconcile']['expires_at']);
            $bound = $bind->invoke($this->controller, $runId);
        };
        $second = new PublicDemoDescribeController($this->pipeline);
        $result = $second->submit($this->authorizedRequest('POST', ['media_id' => 41]));

        self::assertSame(429, $result->get_status());
        self::assertTrue($bound);
        self::assertSame($runId, $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);
        self::assertSame(200, $this->controller->status($this->authorizedRequest('GET', ['run_id' => $runId]))->get_status());
        $GLOBALS['__ac_options']['acx_public_demo_inflight']['expires_at'] = time() - 1;
        self::assertSame(429, $second->submit($this->authorizedRequest('POST', ['media_id' => 41]))->get_status());
        self::assertCount(1, $this->pipeline->submissions);

        $this->pipeline->status = 'completed';
        $this->pipeline->statusData = ['phase' => 'complete', 'completed' => 1];
        self::assertSame(200, $this->controller->status($this->authorizedRequest('GET', ['run_id' => $runId]))->get_status());
        self::assertArrayNotHasKey('acx_public_demo_inflight', $GLOBALS['__ac_options']);
        self::assertSame(202, $second->submit($this->authorizedRequest('POST', ['media_id' => 41]))->get_status());
    }

    public function testBindingMustNotOverwriteReplacementAtWriteBoundary(): void
    {
        $acquire = new \ReflectionMethod(PublicDemoDescribeController::class, 'acquire_inflight_bulkhead');
        $bind = new \ReflectionMethod(PublicDemoDescribeController::class, 'bind_inflight_run');
        $acquire->setAccessible(true);
        $bind->setAccessible(true);
        self::assertTrue($acquire->invoke($this->controller, 41));
        $replacement = [
            'run_id' => 'replacement-run', 'media_id' => 41,
            'token' => 'replacement-owner', 'expires_at' => time() + 600,
        ];
        $GLOBALS['__ac_option_before_update']['acx_public_demo_inflight'] = static function () use ($replacement): void {
            $GLOBALS['__ac_options']['acx_public_demo_inflight'] = $replacement;
        };

        self::assertFalse($bind->invoke($this->controller, 'late-accepted-run'));
        self::assertSame($replacement, $GLOBALS['__ac_options']['acx_public_demo_inflight']);
    }

    public function testR6AcceptedRunTrackingFailureMustKeepBulkhead(): void
    {
        $this->enable([41]);
        // Exercise the real attachment loading, submission and tracking write;
        // only the transport boundary is replaced with backend acceptance.
        $pipeline = new class extends DescribeController {
            public int $accepted = 0;
            public string $status = 'running';
            public function __construct() {}
            public function get_tenant_id(): string { return 'public-demo-test'; }
            public function proxy_recognition_request(
                string $method, string $path, array $body = [], array $query = [],
                string $request_class = 'auto', string $body_kind = 'json', ?int $max_body_bytes = null
            ): WP_REST_Response|WP_Error {
                if ('POST' === $method) {
                    ++$this->accepted;
                }
                return new WP_REST_Response([
                    'run_id' => 'accepted-' . $this->accepted,
                    'status' => $this->status,
                    'phase' => 'failed' === $this->status ? 'failed' : 'describing',
                    'gpu_state' => 'ready', 'completed' => 0,
                    'failed' => 'failed' === $this->status ? 1 : 0,
                    'skipped' => 0, 'total' => 1,
                ], 'POST' === $method ? 202 : 200);
            }
        };
        $file = tempnam(sys_get_temp_dir(), 'acx-public-r6-');
        file_put_contents($file, "\xff\xd8\xff\xe0jpeg-test");
        $GLOBALS['__ac_attached_file'][41] = $file;
        $GLOBALS['__ac_update_option_fail']['acx_describe_run_media_ids_accepted-1'] = true;
        $GLOBALS['__ac_update_option_fail']['acx_describe_run_media_ids_accepted-2'] = true;
        try {
            $first = new PublicDemoDescribeController($pipeline);
            self::assertInstanceOf(WP_Error::class, $first->submit($this->authorizedRequest('POST', ['media_id' => 41])));
            $second = new PublicDemoDescribeController($pipeline);
            $result = $second->submit($this->authorizedRequest('POST', ['media_id' => 41]));
            self::assertSame(1, $pipeline->accepted);
            self::assertSame(429, $result->get_status());
            self::assertSame('accepted-1', $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);
            $GLOBALS['__ac_options']['acx_public_demo_inflight']['expires_at'] = time() - 1;
            self::assertSame(429, $second->submit($this->authorizedRequest('POST', ['media_id' => 41]))->get_status());
            self::assertSame(1, $pipeline->accepted);

            $pipeline->status = 'failed';
            self::assertSame(200, $first->status($this->authorizedRequest('GET', ['run_id' => 'accepted-1']))->get_status());
            self::assertArrayNotHasKey('acx_public_demo_inflight', $GLOBALS['__ac_options']);
        } finally {
            unset($GLOBALS['__ac_update_option_fail']['acx_describe_run_media_ids_accepted-1'], $GLOBALS['__ac_update_option_fail']['acx_describe_run_media_ids_accepted-2']);
            unlink($file);
        }
    }

    /**
     * GUIDEDFIX-2 [P03/P07d]: the public demo is the ONLY door that puts an
     * idempotency_key on the wire, and this test drives it through the REAL
     * DescribeController::submit_describe_run — the class under change — rather
     * than the suite's stub that overrides that method away.
     *
     * A malformed key must be rejected before any shared budget is touched. The
     * rate token, the site-wide inflight slot and the site's daily capacity are
     * all either non-refundable or held for minutes, so a loop of bad keys used
     * to drain the whole demo for every visitor at zero GPU cost, while the
     * caller was told (502 "temporarily unavailable") to keep retrying. The cap
     * is pinned to 1 here so a single leaked unit is unmistakable.
     */
    public function testMalformedIdempotencyKeyIsRejectedBeforeAnySharedBudgetIsSpent(): void
    {
        $this->enable([41]);
        $this->setOption('acx_public_demo_daily_cap', 1);
        $pipeline = new class extends DescribeController {
            public int $proxied = 0;
            public function __construct() {}
            public function get_tenant_id(): string { return 'public-demo-test'; }
            public function proxy_recognition_request(
                string $method, string $path, array $body = [], array $query = [],
                string $request_class = 'auto', string $body_kind = 'json', ?int $max_body_bytes = null
            ): WP_REST_Response|WP_Error {
                ++$this->proxied;
                return new WP_REST_Response([
                    'run_id' => 'budget-run-' . $this->proxied,
                    'status' => 'pending', 'phase' => 'queued', 'gpu_state' => 'ready',
                    'completed' => 0, 'failed' => 0, 'skipped' => 0, 'total' => 1,
                ], 202);
            }
        };
        $file = tempnam(sys_get_temp_dir(), 'acx-public-p03-');
        file_put_contents($file, "\xff\xd8\xff\xe0jpeg-test");
        $GLOBALS['__ac_attached_file'][41] = $file;

        try {
            $controller = new PublicDemoDescribeController($pipeline);
            // More attempts than the 3/minute rate allowance and than the cap.
            for ($attempt = 0; $attempt < 5; ++$attempt) {
                $rejected = $controller->submit($this->authorizedRequest('POST', [
                    'media_id' => 41,
                    'idempotency_key' => 'short-key',
                ]));
                self::assertInstanceOf(WP_Error::class, $rejected, "attempt {$attempt}");
                self::assertSame(PublicDemoErrorCode::INVALID_IDEMPOTENCY_KEY, $rejected->get_error_code());
                self::assertSame(422, $rejected->get_error_data()['status'] ?? null);
                self::assertSame('idempotency_key', $rejected->get_error_data()['field'] ?? null);
            }

            self::assertSame(0, $pipeline->proxied);
            self::assertArrayNotHasKey('acx_public_demo_daily_usage', $GLOBALS['__ac_options']);
            self::assertArrayNotHasKey('acx_public_demo_inflight', $GLOBALS['__ac_options']);

            // The site's single daily unit is still available to a real visitor.
            $accepted = $controller->submit($this->authorizedRequest('POST', [
                'media_id' => 41,
                'idempotency_key' => 'valid-retry-key-01',
            ]));
            self::assertInstanceOf(WP_REST_Response::class, $accepted);
            self::assertSame(202, $accepted->get_status());
            self::assertSame(1, $pipeline->proxied);
        } finally {
            unlink($file);
        }
    }

    /**
     * GUIDEDFIX-2 [P06]: rg-015 — an over-long key is rejected, never rewritten
     * into a sha256 digest. Rewriting made the caller's key and the stored
     * dedupe key differ, so the client could never replay its own submission.
     */
    public function testOverLongIdempotencyKeyIsRejectedRatherThanRewrittenIntoADigest(): void
    {
        $this->enable([41]);
        $controller = new PublicDemoDescribeController($this->pipeline);

        $rejected = $controller->submit($this->authorizedRequest('POST', [
            'media_id' => 41,
            'idempotency_key' => str_repeat('a', 200),
        ]));

        self::assertInstanceOf(WP_Error::class, $rejected);
        self::assertSame(PublicDemoErrorCode::INVALID_IDEMPOTENCY_KEY, $rejected->get_error_code());
        self::assertSame(422, $rejected->get_error_data()['status'] ?? null);
        self::assertCount(0, $this->pipeline->submissions);
        self::assertArrayNotHasKey('acx_public_demo_daily_usage', $GLOBALS['__ac_options']);
    }

    /**
     * GUIDEDFIX-2 [P06]: rg-015 — every idempotency_key that reaches the wire
     * comes from the request. Exercises the real DescribeController transport
     * so the multipart body is the actual bytes the backend would receive.
     *
     * A caller that sends a key gets that key forwarded verbatim; a caller that
     * sends none gets the field omitted, not a server-minted uuid that changes
     * on every attempt and so advertises a dedupe guarantee it cannot keep.
     */
    public function testPublicSubmitForwardsTheClientKeyVerbatimAndOmitsItWhenAbsent(): void
    {
        $this->enable([41]);
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $file = tempnam(sys_get_temp_dir(), 'acx-public-p06-');
        file_put_contents($file, "\xff\xd8\xff\xe0jpeg-test");
        $GLOBALS['__ac_attached_file'][41] = $file;
        $key = 'client-retry-key-0007';

        try {
            $this->queueHttpResponse([
                'response' => ['code' => 202, 'message' => 'Accepted'],
                'body' => '{"run_id":"public-wire-1","status":"pending","phase":"queued","completed":0,"failed":0,"skipped":0,"total":1,"cancel_requested":false,"gpu_state":"ready"}',
            ]);
            $withKey = new PublicDemoDescribeController(new DescribeController());
            $first = $withKey->submit($this->authorizedRequest('POST', [
                'media_id' => 41,
                'idempotency_key' => $key,
            ]));
            self::assertInstanceOf(WP_REST_Response::class, $first);
            self::assertSame(202, $first->get_status());
            self::assertMatchesRegularExpression(
                '/name="idempotency_key"\r\n\r\n' . preg_quote($key, '/') . '\r\n/',
                (string) $this->getHttpCalls()[0]['args']['body']
            );

            unset($GLOBALS['__ac_options']['acx_public_demo_inflight']);
            $this->queueHttpResponse([
                'response' => ['code' => 202, 'message' => 'Accepted'],
                'body' => '{"run_id":"public-wire-2","status":"pending","phase":"queued","completed":0,"failed":0,"skipped":0,"total":1,"cancel_requested":false,"gpu_state":"ready"}',
            ]);
            $withoutKey = new PublicDemoDescribeController(new DescribeController());
            $second = $withoutKey->submit($this->authorizedRequest('POST', ['media_id' => 41]));
            self::assertInstanceOf(WP_REST_Response::class, $second);
            self::assertSame(202, $second->get_status());
            self::assertStringNotContainsString(
                'name="idempotency_key"',
                (string) $this->getHttpCalls()[1]['args']['body']
            );
        } finally {
            unlink($file);
        }
    }

    /** @dataProvider uncertainSubmissionProvider */
    public function testUncertainSubmissionWithoutRunIdCannotExpireIntoFreeCapacity(string $failure): void
    {
        $this->enable([41]);
        $this->pipeline->submitResult = match ($failure) {
            'timeout' => new WP_Error('http_request_failed', 'Timed out', ['status' => 504]),
            'tracking' => new WP_Error('describe_run_media_ids_store_failed', 'Tracking failed', ['status' => 500]),
            'upstream' => new WP_REST_Response(['error' => 'upstream failure'], 503),
            'malformed acceptance' => new WP_REST_Response(['status' => 'pending'], 202),
        };
        $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        self::assertSame(true, $GLOBALS['__ac_options']['acx_public_demo_inflight']['submission_started']);
        $GLOBALS['__ac_options']['acx_public_demo_inflight']['expires_at'] = time() - 1;
        $second = new PublicDemoDescribeController($this->pipeline);
        self::assertSame(429, $second->submit($this->authorizedRequest('POST', ['media_id' => 41]))->get_status());
        self::assertCount(1, $this->pipeline->submissions);
    }

    public static function uncertainSubmissionProvider(): iterable
    {
        foreach (['timeout', 'tracking', 'upstream', 'malformed acceptance'] as $failure) {
            yield $failure => [$failure];
        }
    }

    public function testLocalAttachmentFailureReleasesCapacityBeforeAnyBackendAcceptance(): void
    {
        $this->enable([41]);
        $controller = new PublicDemoDescribeController(new DescribeController());
        $result = $controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        self::assertInstanceOf(WP_Error::class, $result);
        self::assertSame([], $this->getHttpCalls());
        self::assertArrayNotHasKey('acx_public_demo_inflight', $GLOBALS['__ac_options']);
        self::assertSame(202, $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]))->get_status());
    }

    public function testSubmissionMarkerWriteFailurePreventsBackendDispatch(): void
    {
        $this->enable([41]);
        $GLOBALS['wpdb']->defaultQueryResult = false;
        $result = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        self::assertSame(429, $result->get_status());
        self::assertSame([], $this->pipeline->submissions);
    }

    public function testExpiredPendingLeaseCanBeReclaimedRepeatedlyAndOldOwnersCannotBind(): void
    {
        $acquire = new \ReflectionMethod(PublicDemoDescribeController::class, 'acquire_inflight_bulkhead');
        $bind = new \ReflectionMethod(PublicDemoDescribeController::class, 'bind_inflight_run');
        $first = new PublicDemoDescribeController($this->pipeline);
        $second = new PublicDemoDescribeController($this->pipeline);
        $third = new PublicDemoDescribeController($this->pipeline);

        self::assertTrue($acquire->invoke($first, 41));
        $firstToken = $GLOBALS['__ac_options']['acx_public_demo_inflight']['token'];
        $GLOBALS['__ac_options']['acx_public_demo_inflight']['expires_at'] = time() - 1;

        self::assertTrue($acquire->invoke($second, 41));
        $secondToken = $GLOBALS['__ac_options']['acx_public_demo_inflight']['token'];
        self::assertNotSame($firstToken, $secondToken);
        self::assertFalse($bind->invoke($first, 'late-first-run'));
        self::assertSame('pending', $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);

        $GLOBALS['__ac_options']['acx_public_demo_inflight']['expires_at'] = time() - 1;
        self::assertTrue($acquire->invoke($third, 41));
        $thirdToken = $GLOBALS['__ac_options']['acx_public_demo_inflight']['token'];
        self::assertNotSame($secondToken, $thirdToken);
        self::assertFalse($bind->invoke($second, 'late-second-run'));
        self::assertTrue($bind->invoke($third, 'current-run'));
        self::assertSame('current-run', $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);
        self::assertSame($thirdToken, $GLOBALS['__ac_options']['acx_public_demo_inflight']['token']);
    }

    public function testExpiredPendingLeaseDoesNotOverwriteOwnerThatChangesBeforeReplacement(): void
    {
        $acquire = new \ReflectionMethod(PublicDemoDescribeController::class, 'acquire_inflight_bulkhead');
        $this->setOption('acx_public_demo_inflight', [
            'run_id' => 'pending',
            'media_id' => 41,
            'token' => 'expired-owner',
            'expires_at' => time() - 1,
        ]);
        $contendingOwner = [
            'run_id' => 'pending',
            'media_id' => 41,
            'token' => 'contending-owner',
            'expires_at' => time() + 600,
        ];
        $GLOBALS['__ac_get_option_before_read']['acx_public_demo_inflight'] = static function (string $key, int $read) use ($contendingOwner): void {
            if (2 === $read) {
                $GLOBALS['__ac_options'][$key] = $contendingOwner;
            }
        };

        self::assertFalse($acquire->invoke($this->controller, 41));
        self::assertSame($contendingOwner, $GLOBALS['__ac_options']['acx_public_demo_inflight']);
    }

    public function testAgedLeaseWithMismatchedTerminalBackendRunIsRenewedAndRejectsAdmission(): void
    {
        $this->enable([41]);
        $this->pipeline->status = 'completed';
        $this->pipeline->statusData = ['run_id' => 'foreign-terminal', 'phase' => 'complete', 'completed' => 1];
        $this->setOption('acx_public_demo_inflight', [
            'run_id' => 'recorded-run',
            'media_id' => 41,
            'token' => 'old-token',
            'expires_at' => time() - 1,
        ]);

        $result = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));

        self::assertSame(429, $result->get_status());
        self::assertSame(PublicDemoErrorCode::BUSY, $result->get_data()['code']);
        self::assertSame('recorded-run', $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);
        self::assertGreaterThan(time(), $GLOBALS['__ac_options']['acx_public_demo_inflight']['expires_at']);
        self::assertSame([], $this->pipeline->submissions);
    }

    public function testStatusRejectsMismatchedUpstreamRunWithoutFetchingItemsOrReleasingLease(): void
    {
        $this->enable([41]);
        $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        $this->pipeline->status = 'completed';
        $this->pipeline->statusData = ['run_id' => 'foreign-run', 'phase' => 'complete', 'completed' => 1];

        $result = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));

        self::assertInstanceOf(WP_Error::class, $result);
        self::assertSame(PublicDemoErrorCode::INVALID_RESPONSE, $result->get_error_code());
        self::assertSame(502, $result->get_error_data()['status']);
        self::assertSame(0, $this->pipeline->itemRequests);
        self::assertSame('public-run-1', $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);
    }

    public function testNullAndAbsentGpuStateArePreservedOnSubmitAndStatus(): void
    {
        $this->enable([41]);
        $this->pipeline->gpuState = null;

        $submitted = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        self::assertArrayHasKey('gpu_state', $submitted->get_data());
        self::assertNull($submitted->get_data()['gpu_state']);

        $status = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));
        self::assertArrayHasKey('gpu_state', $status->get_data());
        self::assertNull($status->get_data()['gpu_state']);

        unset($GLOBALS['__ac_options']['acx_public_demo_inflight']);
        $this->pipeline->gpuState = 'ready';
        $this->pipeline->omitGpuState = true;
        $submittedWithoutState = $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        self::assertArrayNotHasKey('gpu_state', $submittedWithoutState->get_data());

        $statusWithoutState = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-2']));
        self::assertArrayNotHasKey('gpu_state', $statusWithoutState->get_data());
    }

    public function testMalformedTerminalEnvelopeDoesNotReleaseBulkhead(): void
    {
        $this->enable([41]);
        $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        $this->pipeline->status = 'completed';
        $this->pipeline->statusData = ['phase' => 'complete', 'completed' => 0.5];

        $result = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));

        self::assertInstanceOf(WP_Error::class, $result);
        self::assertSame(PublicDemoErrorCode::INVALID_RESPONSE, $result->get_error_code());
        self::assertSame('public-run-1', $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);
        self::assertSame(0, $this->pipeline->itemRequests);
    }

    public function testForeignRunItemsEnvelopeIsRejectedWithoutReleasingBulkhead(): void
    {
        $this->enable([41]);
        $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        $this->pipeline->status = 'completed';
        $this->pipeline->statusData = ['phase' => 'complete', 'completed' => 1];
        $this->pipeline->itemsRunId = 'foreign-run';

        $result = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));

        self::assertInstanceOf(WP_Error::class, $result);
        self::assertSame(PublicDemoErrorCode::INVALID_RESPONSE, $result->get_error_code());
        self::assertSame(1, $this->pipeline->itemRequests);
        self::assertSame('public-run-1', $GLOBALS['__ac_options']['acx_public_demo_inflight']['run_id']);
    }

    /** @dataProvider invalidCounterProvider */
    public function testEnvelopeRejectsEachInvalidProgressCounter(array $invalidCounters): void
    {
        $this->enable([41]);
        $this->pipeline->statusData = $invalidCounters;
        $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));

        $result = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));

        self::assertInstanceOf(WP_Error::class, $result);
        self::assertSame(PublicDemoErrorCode::INVALID_RESPONSE, $result->get_error_code());
    }

    /** @return iterable<string,array{array<string,mixed>}> */
    public static function invalidCounterProvider(): iterable
    {
        yield 'negative completed masked by failed' => [['completed' => -1, 'failed' => 1]];
        yield 'negative failed masked by completed' => [['completed' => 1, 'failed' => -1]];
        yield 'negative skipped masked by completed' => [['completed' => 1, 'skipped' => -1]];
        yield 'negative total' => [['total' => -1]];
        yield 'fractional completed' => [['completed' => 0.5]];
        yield 'string total' => [['total' => '1']];
        yield 'null failed' => [['failed' => null]];
        yield 'null skipped' => [['skipped' => null]];
    }

    /** @dataProvider deadlineConfigSourceProvider */
    public function testDeadlineIncludesWarmupAndInferenceBudgetsFromEveryCanonicalConfigSource(string $sourceSetup): void
    {
        $script = $sourceSetup . <<<'PHP'
define('ABSPATH', getcwd() . '/');
function get_file_data($file, $headers) { return ['Version' => '0.0.6']; }
function plugin_dir_path($file) { return dirname($file) . '/'; }
function plugin_dir_url($file) { return 'https://example.test/wp-content/plugins/alt-context/'; }
function esc_html__($message, $domain = null) { return $message; }
function wp_die($message) { throw new RuntimeException((string) $message); }
function add_action($hook, $callback, $priority = 10, $acceptedArgs = 1) { return true; }
function register_activation_hook($file, $callback) { return true; }
function register_deactivation_hook($file, $callback) { return true; }
function register_uninstall_hook($file, $callback) { return true; }
function apply_filters($hook, $value, ...$args) { return $value; }
require 'alt-context.php';
require_once 'src/api/class-public-demo-describe-controller.php';
$reflection = new ReflectionClass(AltContext\Api\PublicDemoDescribeController::class);
$controller = $reflection->newInstanceWithoutConstructor();
$deadline = $reflection->getMethod('public_deadline_seconds')->invoke($controller);
echo (string) $deadline;
PHP;

        $command = sprintf(
            'cd %s && %s -r %s',
            escapeshellarg(__DIR__ . '/../..'),
            escapeshellarg((string) PHP_BINARY),
            escapeshellarg($script)
        );
        $output = shell_exec($command);

        self::assertSame(217, (int) trim((string) $output), 'Deadline must include 37s warm-up + 180s inference. Output: ' . $output);
    }

    /** @return iterable<string,array{string}> */
    public static function deadlineConfigSourceProvider(): iterable
    {
        yield 'getenv' => [<<<'PHP'
putenv('ACX_GPU_WARMUP_TIMEOUT_SECONDS=37');
unset($_ENV['ACX_GPU_WARMUP_TIMEOUT_SECONDS'], $_SERVER['ACX_GPU_WARMUP_TIMEOUT_SECONDS']);

PHP];
        yield 'dotenv ENV store' => [<<<'PHP'
putenv('ACX_GPU_WARMUP_TIMEOUT_SECONDS');
$_ENV['ACX_GPU_WARMUP_TIMEOUT_SECONDS'] = '37';
unset($_SERVER['ACX_GPU_WARMUP_TIMEOUT_SECONDS']);

PHP];
        yield 'dotenv SERVER store' => [<<<'PHP'
putenv('ACX_GPU_WARMUP_TIMEOUT_SECONDS');
unset($_ENV['ACX_GPU_WARMUP_TIMEOUT_SECONDS']);
$_SERVER['ACX_GPU_WARMUP_TIMEOUT_SECONDS'] = '37';

PHP];
        yield 'blank dotenv ENV falls through to SERVER' => [<<<'PHP'
putenv('ACX_GPU_WARMUP_TIMEOUT_SECONDS');
$_ENV['ACX_GPU_WARMUP_TIMEOUT_SECONDS'] = '   ';
$_SERVER['ACX_GPU_WARMUP_TIMEOUT_SECONDS'] = '37';

PHP];
        yield 'blank process and ENV stores fall through to SERVER' => [<<<'PHP'
putenv('ACX_GPU_WARMUP_TIMEOUT_SECONDS=   ');
$_ENV['ACX_GPU_WARMUP_TIMEOUT_SECONDS'] = '';
$_SERVER['ACX_GPU_WARMUP_TIMEOUT_SECONDS'] = '37';

PHP];
    }

    public function testStatusRebuildsPublicEnvelopeAndMapsRawFailure(): void
    {
        $this->enable([41]);
        $this->controller->submit($this->authorizedRequest('POST', ['media_id' => 41]));
        $this->pipeline->status = 'failed';
        $this->pipeline->statusData = [
            'phase' => 'failed',
            'error' => 'secret upstream exception text',
            'error_message' => 'database credentials leaked',
        ];

        $status = $this->controller->status($this->authorizedRequest('GET', ['run_id' => 'public-run-1']));
        $data = $status->get_data();

        self::assertSame(
            ['run_id', 'status', 'phase', 'gpu_state', 'progress', 'error'],
            array_keys($data)
        );
        self::assertSame(PublicDemoErrorCode::PIPELINE_FAILED, $data['error']['code']);
        self::assertStringNotContainsString('secret', json_encode($data, JSON_THROW_ON_ERROR));
        self::assertStringNotContainsString('credentials', json_encode($data, JSON_THROW_ON_ERROR));
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
