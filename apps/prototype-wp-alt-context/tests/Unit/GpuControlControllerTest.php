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

    public function testTransportFailureReturnsGpuUnavailable502WithoutLeakingMessage(): void
    {
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('gpu_status_unavailable', $response->get_error_code());
        $this->assertSame('GPU control is unavailable.', $response->get_error_message());
        $this->assertSame(502, $response->get_error_data()['status']);
        $this->assertTypedUnavailable($response->get_error_data()['unavailable'], 'upstream_5xx', 'scene', null);
        $this->assertStringNotContainsString('Connection refused', $response->get_error_message());
        $this->assertStringNotContainsString('Connection refused', (string) wp_json_encode($response->get_error_data()));
    }

    public function testGetStatusUnavailableWhenRecognitionNotConfigured(): void
    {
        $this->setOption('acx_recognition_url', '');

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('gpu_status_unavailable', $response->get_error_code());
        $this->assertSame(500, $response->get_error_data()['status']);
        $this->assertTypedUnavailable($response->get_error_data()['unavailable'], 'not_configured', 'scene', 500);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testGetStatusUnavailableWhenApiKeyMissing(): void
    {
        $this->setOption('acx_recognition_api_key', '');

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('gpu_status_unavailable', $response->get_error_code());
        $this->assertSame(500, $response->get_error_data()['status']);
        $this->assertTypedUnavailable($response->get_error_data()['unavailable'], 'api_key_missing', 'scene', 500);
        $this->assertStringNotContainsString('test-key', $response->get_error_message());
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testGetStatusUnavailableMapsTimeout(): void
    {
        $this->queueHttpResponse(new WP_Error(
            'http_request_failed',
            'cURL error 28: Operation timed out after 10000 milliseconds'
        ));

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame(502, $response->get_error_data()['status']);
        $this->assertTypedUnavailable($response->get_error_data()['unavailable'], 'timeout', 'scene', null);
        $this->assertStringNotContainsString('cURL error 28', $response->get_error_message());
        $this->assertStringNotContainsString(
            'cURL error 28',
            (string) wp_json_encode($response->get_error_data())
        );
    }

    public function testGetStatusUpstream5xxAllowlistsCodeAndMessageAndDropsSecrets(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 502, 'message' => 'Bad Gateway'],
            'headers' => ['Retry-After' => '15'],
            'body' => json_encode([
                'code' => 'gpu_adapter_failed',
                'message' => str_repeat('m', 301),
                'gpu_state' => ['state' => 'unknown'],
                'detail' => 'adapter exploded with key material',
                'trace' => 'File "/opt/scene/adapter.py", line 99',
                'api_key' => 'sk-secret',
            ], JSON_THROW_ON_ERROR),
        ]);

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(502, $response->get_status());
        $data = $response->get_data();
        $this->assertSame('gpu_adapter_failed', $data['code']);
        $this->assertSame(str_repeat('m', 300), $data['message']);
        $this->assertArrayNotHasKey('detail', $data);
        $this->assertArrayNotHasKey('trace', $data);
        $this->assertArrayNotHasKey('api_key', $data);
        $this->assertArrayNotHasKey('gpu_state', $data);
        $this->assertTypedUnavailable($data['unavailable'], 'upstream_5xx', 'scene', 502, 15);
    }

    public function testGetStatusUpstream4xxAddsUnavailableEnvelope(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 429, 'message' => 'Too Many Requests'],
            'headers' => ['Retry-After' => '20'],
            'body' => json_encode([
                'code' => 'rate_limited',
                'message' => 'slow down',
                'detail' => 'secret-limiter-config',
                'trace' => 'stack',
                'api_key' => 'sk-leak',
            ], JSON_THROW_ON_ERROR),
        ]);

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(429, $response->get_status());
        $data = $response->get_data();
        $this->assertSame('rate_limited', $data['code']);
        $this->assertSame('slow down', $data['message']);
        $this->assertArrayNotHasKey('detail', $data);
        $this->assertArrayNotHasKey('trace', $data);
        $this->assertArrayNotHasKey('api_key', $data);
        $this->assertTypedUnavailable($data['unavailable'], 'upstream_4xx', 'scene', 429, 20);
    }

    public function testGetStatusUnauthorized401PassesThroughWithoutEnvelope(): void
    {
        $fixture = ['detail' => 'Unauthorized'];
        $this->queueHttpResponse([
            'response' => ['code' => 401, 'message' => 'Unauthorized'],
            'body' => json_encode($fixture, JSON_THROW_ON_ERROR),
        ]);

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(401, $response->get_status());
        $this->assertSame($fixture, $response->get_data());
    }

    public function testPostIntentForbidden403PassesThroughWithoutEnvelope(): void
    {
        $fixture = ['detail' => 'gpu_control_forbidden'];
        $this->queueHttpResponse([
            'response' => ['code' => 403, 'message' => 'Forbidden'],
            'body' => json_encode($fixture, JSON_THROW_ON_ERROR),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/gpu/intent');
        $request->set_body_params(['action' => 'start']);

        $response = $this->controller->post_intent($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(403, $response->get_status());
        $this->assertSame($fixture, $response->get_data());
    }

    public function testPostIntentValidation422PassesThroughWithoutEnvelope(): void
    {
        $fixture = [
            'detail' => [
                [
                    'loc' => ['body', 'action'],
                    'msg' => 'value is not a valid enumeration member',
                    'type' => 'enum',
                ],
            ],
        ];
        $this->queueHttpResponse([
            'response' => ['code' => 422, 'message' => 'Unprocessable Entity'],
            'body' => json_encode($fixture, JSON_THROW_ON_ERROR),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/gpu/intent');
        $request->set_body_params(['action' => 'start']);

        $response = $this->controller->post_intent($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(422, $response->get_status());
        $this->assertSame($fixture, $response->get_data());
    }

    public function testGetStatusUpstream404AddsUnavailableEnvelope(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode([
                'detail' => 'Not Found',
                'trace' => 'missing route dump',
            ], JSON_THROW_ON_ERROR),
        ]);

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(404, $response->get_status());
        $data = $response->get_data();
        $this->assertArrayNotHasKey('detail', $data);
        $this->assertArrayNotHasKey('trace', $data);
        $this->assertTypedUnavailable($data['unavailable'], 'upstream_4xx', 'scene', 404);
    }

    public function testGetStatusUpstream5xxNonArrayJsonAddsUnavailableEnvelope(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 502, 'message' => 'Bad Gateway'],
            'body' => json_encode('adapter exploded', JSON_THROW_ON_ERROR),
        ]);

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(502, $response->get_status());
        $data = $response->get_data();
        $this->assertSame(['unavailable'], array_keys($data));
        $this->assertTypedUnavailable($data['unavailable'], 'upstream_5xx', 'scene', 502);
    }

    public function testGetStatusUpstream5xxNonJsonAddsContractMismatchEnvelope(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '<html>stack trace with api_key=sk-leak</html>',
        ]);

        $response = $this->controller->get_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/gpu/status')
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(500, $response->get_status());
        $data = $response->get_data();
        $this->assertSame(['unavailable'], array_keys($data));
        $this->assertTypedUnavailable($data['unavailable'], 'contract_mismatch', 'scene', 500);
        $this->assertStringNotContainsString('sk-leak', (string) wp_json_encode($data));
        $this->assertStringNotContainsString('stack trace', (string) wp_json_encode($data));
    }

    public function testPostIntentTransportFailureAddsUnavailableWithoutLeakingMessage(): void
    {
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/gpu/intent');
        $request->set_body_params(['action' => 'start']);

        $response = $this->controller->post_intent($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('gpu_status_unavailable', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status']);
        $this->assertTypedUnavailable($response->get_error_data()['unavailable'], 'upstream_5xx', 'scene', null);
        $this->assertStringNotContainsString('Connection refused', $response->get_error_message());
    }

    /**
     * @param mixed $unavailable
     * @return array<string, mixed>
     */
    private function assertTypedUnavailable(
        mixed $unavailable,
        string $reason,
        string $service,
        ?int $httpStatus,
        ?int $retryAfter = null
    ): array {
        $this->assertIsArray($unavailable);
        $this->assertSame(
            ['reason', 'service', 'http_status', 'retry_after_seconds', 'checked_at'],
            array_keys($unavailable)
        );
        $this->assertSame($reason, $unavailable['reason']);
        $this->assertSame($service, $unavailable['service']);
        $this->assertSame($httpStatus, $unavailable['http_status']);
        $this->assertSame($retryAfter, $unavailable['retry_after_seconds']);
        // Source: plugin-observed gmdate('Y-m-d\TH:i:s\Z'); proxy_request/WP_Error data has no failed-attempt timestamp.
        $this->assertMatchesRegularExpression(
            '/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/',
            $unavailable['checked_at']
        );

        return $unavailable;
    }
}

}
