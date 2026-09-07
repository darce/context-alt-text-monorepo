<?php

declare(strict_types=1);

namespace {
    if (!function_exists('wp_get_current_user')) {
        function wp_get_current_user(): object
        {
            return (object) [
                'user_login' => $GLOBALS['__ac_gpu_control_user_login'] ?? 'test-admin',
            ];
        }
    }
}

namespace AltContext\Tests\Unit {

use AltContext\Api\GpuControlController;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\GpuControlController
 */
class GpuControlControllerTest extends TestCase
{
    private GpuControlController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'https://api.example.test');
        $this->setUserCapability('manage_options', true);
        $GLOBALS['__ac_gpu_control_user_login'] = 'operator.login';
        $this->controller = new GpuControlController();
    }

    public function testRegisterRoutesAddsStatusAndIntentEndpoints(): void
    {
        $this->controller->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains('/recognition/gpu/status', $routes);
        $this->assertContains('/recognition/gpu/intent', $routes);
    }

    public function testPermissionRequiresManageOptions(): void
    {
        $this->setUserCapability('manage_options', false);

        $this->assertFalse($this->controller->can_manage_recognition());
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testGetStatusPassesThroughUpstreamBodyAndStatus(): void
    {
        $fixture = [
            'gpu_state' => [
                'state' => 'stopped',
                'intent' => 'auto',
            ],
            'snapshot_fresh' => true,
            'server_time' => '2026-09-06T22:10:00Z',
        ];
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode($fixture, JSON_THROW_ON_ERROR),
        ]);

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame($fixture, $response->get_data());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame(
            'https://api.example.test/scene/gpu/status',
            $calls[0]['url']
        );
        $this->assertSame('GET', $calls[0]['method']);
        $this->assertSame(10, $calls[0]['args']['timeout']);
    }

    public function testPostIntentAddsCurrentUserAndPassesThroughAcceptedResponse(): void
    {
        $fixture = [
            'gpu_state' => ['state' => 'starting'],
            'intent' => ['action' => 'start', 'requested_by' => 'operator.login'],
        ];
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => json_encode($fixture, JSON_THROW_ON_ERROR),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/gpu/intent');
        $request->set_body_params([
            'action' => 'start',
            'ttl_seconds' => 120,
            'requested_by' => 'caller-controlled-value',
            'future_field' => ['forward' => true],
        ]);

        $response = $this->controller->post_intent($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(202, $response->get_status());
        $this->assertSame($fixture, $response->get_data());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame(
            'https://api.example.test/scene/gpu/intent',
            $calls[0]['url']
        );
        $this->assertSame('POST', $calls[0]['method']);
        $this->assertSame(10, $calls[0]['args']['timeout']);

        $body = json_decode((string) $calls[0]['args']['body'], true, 512, JSON_THROW_ON_ERROR);
        $this->assertSame('start', $body['action']);
        $this->assertSame(120, $body['ttl_seconds']);
        $this->assertSame('operator.login', $body['requested_by']);
        $this->assertSame(['forward' => true], $body['future_field']);
    }

    public function testInvalidActionReturnsBadRequestBeforeHttpCall(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/gpu/intent');
        $request->set_body_params(['action' => 'restart']);

        $response = $this->controller->post_intent($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('gpu_invalid_action', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status']);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testTransportFailureReturnsGpuUnavailable502WithOriginalMessage(): void
    {
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('gpu_status_unavailable', $response->get_error_code());
        $this->assertSame('Connection refused', $response->get_error_message());
        $this->assertSame(502, $response->get_error_data()['status']);
    }
}

}
