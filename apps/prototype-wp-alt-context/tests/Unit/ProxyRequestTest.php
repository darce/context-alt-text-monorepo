<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionController;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_Error;

/**
 * Tests for RecognitionController proxy_request behavior.
 *
 * @covers \AltContext\Api\RecognitionController
 */
class ProxyRequestTest extends TestCase
{
    private RecognitionController $controller;

    protected function setUp(): void
    {
        parent::setUp();

        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->setOption('acx_tier', 'free');

        $this->controller = new RecognitionController();
    }

    public function testProxyFallsBackToLocalhostWhenUrlNotConfigured(): void
    {
        $this->setOption('acx_recognition_url', '');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status":"completed"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-job-id');

        $result = $this->controller->get_job_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('http://localhost:8000/recognition/jobs/test-job-id', $calls[0]['url']);
    }

    /**
     * Test successful proxy request returns response.
     */
    public function testSuccessfulProxyRequestReturnsResponse(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status": "completed", "job_id": "test-123"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());

        $data = $result->get_data();
        $this->assertSame('completed', $data['status']);
        $this->assertSame('test-123', $data['job_id']);
    }

    public function testProxyRequestPreservesHeadersFromCaseInsensitiveDictionary(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'headers' => ['Retry-After' => '7', 'Content-Length' => '505'],
            'body' => '{"status": "completed"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame('7', $result->get_headers()['Retry-After'] ?? null);
        $this->assertArrayNotHasKey('Content-Length', $result->get_headers());
        $this->assertArrayNotHasKey('content-length', $result->get_headers());
    }

    public function testAbstractProxyControllerLoadsPolicyUnderRuntimeAutoloadRules(): void
    {
        $script = <<<'PHP'
require 'vendor/autoload.php';
require_once 'src/api/interface-recognition-route-controller.php';
require_once 'src/api/class-abstract-recognition-proxy-controller.php';
var_export(class_exists('AltContext\\Api\\RecognitionProxyPolicy'));
PHP;

        $command = sprintf(
            'cd %s && %s -r %s',
            escapeshellarg(__DIR__ . '/../../'),
            escapeshellarg((string) PHP_BINARY),
            escapeshellarg($script)
        );

        $output = shell_exec($command);

        $this->assertSame('true', trim((string) $output));
    }

    /**
     * Test proxy request includes API key header when configured.
     */
    public function testProxyRequestIncludesApiKeyHeader(): void
    {
        $this->setOption('acx_recognition_api_key', 'secret-key-123');
        $controller = new RecognitionController();

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $controller->get_job_status($request);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('secret-key-123', $calls[0]['args']['headers']['X-API-Key'] ?? null);
    }

    public function testPluginBootstrapDefinesRecognitionConstantsFromEnvironment(): void
    {
        $script = <<<'PHP'
putenv('ACX_RECOGNITION_BASE_URL=https://env.example');
putenv('ACX_RECOGNITION_API_KEY=env-api-key');
define('ABSPATH', getcwd() . '/');
if (!function_exists('get_file_data')) {
    function get_file_data($file, $default_headers)
    {
        return ['Version' => '0.0.2'];
    }
}
if (!function_exists('plugin_dir_path')) {
    function plugin_dir_path($file)
    {
        return dirname($file) . '/';
    }
}
if (!function_exists('plugin_dir_url')) {
    function plugin_dir_url($file)
    {
        return 'https://example.test/wp-content/plugins/alt-context/';
    }
}
if (!function_exists('plugin_basename')) {
    function plugin_basename($file)
    {
        return 'alt-context/alt-context.php';
    }
}
if (!function_exists('esc_html__')) {
    function esc_html__($value, $domain = null)
    {
        return $value;
    }
}
if (!function_exists('wp_die')) {
    function wp_die($message)
    {
        throw new RuntimeException((string) $message);
    }
}
if (!function_exists('add_action')) {
    function add_action($hook, $callback, $priority = 10, $accepted_args = 1)
    {
        return true;
    }
}
if (!function_exists('register_activation_hook')) {
    function register_activation_hook($file, $callback)
    {
        return true;
    }
}
if (!function_exists('register_deactivation_hook')) {
    function register_deactivation_hook($file, $callback)
    {
        return true;
    }
}
if (!function_exists('register_uninstall_hook')) {
    function register_uninstall_hook($file, $callback)
    {
        return true;
    }
}
require 'alt-context.php';
echo json_encode([
    'url' => defined('ACX_RECOGNITION_URL') ? ACX_RECOGNITION_URL : null,
    'key' => defined('ACX_RECOGNITION_API_KEY') ? ACX_RECOGNITION_API_KEY : null,
]);
PHP;

        $command = sprintf(
            'cd %s && %s -r %s',
            escapeshellarg(__DIR__ . '/../../'),
            escapeshellarg((string) PHP_BINARY),
            escapeshellarg($script)
        );

        $output = shell_exec($command);
        $data = json_decode(trim((string) $output), true);

        $this->assertIsArray($data);
        $this->assertSame('https://env.example', $data['url'] ?? null);
        $this->assertSame('env-api-key', $data['key'] ?? null);
    }

    public function testAnalyzeRequestUsesDeterministicUuidTenantId(): void
    {
        $GLOBALS['__ac_attachment_urls'][123] = 'http://example.test/media/123.jpg';

        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => '{"status":"queued"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', [123]);

        $result = $this->controller->analyze_media($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);

        $tenantId = $calls[0]['args']['headers']['X-Tenant-ID'] ?? '';
        $payload = json_decode($calls[0]['body'] ?? '', true);

        $this->assertMatchesRegularExpression(
            '/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/',
            $tenantId
        );
        $this->assertIsArray($payload);
        $this->assertSame($tenantId, $payload['tenant_id'] ?? null);
        $this->assertNotSame(md5((string) \get_site_url()), $tenantId);
    }

    public function testProxyRequestUsesFilteredBaseUrlWhenOptionMissing(): void
    {
        $this->setOption('acx_recognition_url', '');

        add_filter('acx_recognition_base_url', static function (): string {
            return 'https://filtered.example';
        });

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status":"completed"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('https://filtered.example/recognition/jobs/test-123', $calls[0]['url']);
    }

    public function testProxyRequestIgnoresInvalidFilteredBaseUrl(): void
    {
        $this->setOption('acx_recognition_url', '');

        add_filter('acx_recognition_base_url', static function (): string {
            return 'ftp://invalid-filter.example';
        });

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status":"completed"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('http://localhost:8000/recognition/jobs/test-123', $calls[0]['url']);
    }

    public function testProxyRequestUsesFilteredApiKeyWhenOptionMissing(): void
    {
        $this->setOption('acx_recognition_api_key', '');

        add_filter('acx_recognition_api_key', static function (): string {
            return 'filtered-api-key';
        });

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $this->controller->get_job_status($request);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('filtered-api-key', $calls[0]['args']['headers']['X-API-Key'] ?? null);
    }

    public function testProxyRequestReturnsErrorWhenApiKeyMissing(): void
    {
        $this->setOption('acx_recognition_api_key', '');

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_body_params(['media_ids' => [1]]);

        // Stub attachment metadata so build_media_items doesn't bail early
        $GLOBALS['__ac_attachment_urls'][1] = 'http://example.com/image.jpg';
        $GLOBALS['__ac_attachment_mimes'][1] = 'image/jpeg';
        $GLOBALS['__ac_attachment_metadata'][1] = ['width' => 100, 'height' => 100];

        $result = $this->controller->analyze_media($request);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('recognition_api_key_missing', $result->get_error_code());
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testProxyRequestUsesConstantBaseUrlOverOption(): void
    {
        define('ACX_RECOGNITION_URL', 'https://constant.example');

        $this->setOption('acx_recognition_url', 'https://option.example');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status":"completed"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('https://constant.example/recognition/jobs/test-123', $calls[0]['url']);
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testProxyRequestUsesConstantApiKeyOverOption(): void
    {
        define('ACX_RECOGNITION_API_KEY', 'constant-api-key');

        $this->setOption('acx_recognition_api_key', 'option-api-key');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $this->controller->get_job_status($request);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('constant-api-key', $calls[0]['args']['headers']['X-API-Key'] ?? null);
    }

    public function testProxyRequestReadsLatestUrlWithoutControllerReconstruction(): void
    {
        $this->setOption('acx_recognition_url', 'http://example.internal:9000');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status": "completed"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('http://example.internal:9000/recognition/jobs/test-123', $calls[0]['url']);
    }

    /**
     * Job-status polling uses the post-scan read policy.
     */
    public function testProxyRequestJobStatusUsesPostScanReadPolicyOn500Error(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error": "temporary failure"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        // get_job_status maps proxy-unavailable into a synthetic offline 200 payload.
        $this->assertSame(200, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls, 'Post-scan reads should fast-fail without retries.');
        $this->assertSame(10, $calls[0]['args']['timeout'] ?? null);
    }

    /**
     * Test proxy request does not retry on 4xx client errors.
     */
    public function testProxyRequestDoesNotRetryOn4xxError(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 400, 'message' => 'Bad Request'],
            'body' => '{"error": "invalid request"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        // Should return 400 immediately without retry
        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(400, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls, 'Should not retry on 4xx errors');
    }

    /**
     * Job-status polling should keep the post-scan read timeout on transport errors.
     */
    public function testProxyRequestJobStatusUsesPostScanReadPolicyOnNetworkError(): void
    {
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection timed out'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        // get_job_status maps proxy-unavailable into a synthetic offline 200 payload.
        $this->assertSame(200, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls, 'Post-scan reads should not retry transport failures.');
        $this->assertSame(10, $calls[0]['args']['timeout'] ?? null);
    }

    public function testProxyRequestJobStatusDoesNotOpenCircuitAfterConsecutivePostScanReadFailures(): void
    {
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection timed out'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection timed out'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection timed out'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $this->controller->get_job_status($request);
        $this->controller->get_job_status($request);

        $callsAfterFailures = $this->getHttpCalls();
        $this->assertCount(2, $callsAfterFailures, 'First two post-scan reads should hit the remote service.');

        $this->controller->get_job_status($request);
        $callsAfterCircuit = $this->getHttpCalls();
        $this->assertCount(3, $callsAfterCircuit, 'Post-scan reads should not be short-circuited by the UI-read circuit breaker.');
        $this->assertSame(10, $callsAfterCircuit[2]['args']['timeout'] ?? null);
    }

    /**
     * Test proxy request returns error after max retries exhausted.
     */
    public function testProxyRequestReturnsErrorAfterMaxRetries(): void
    {
        // Queue: 500, 500, 500 (3 failures = max retries exhausted)
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error": "server down"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error": "server down"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error": "server down"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        // Should return the 500 response after max retries
        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(500, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, 'Should make exactly 3 attempts (max retries)');
    }

    /**
     * Test proxy request returns WP_Error after max network retries.
     */
    public function testProxyRequestReturnsWpErrorAfterMaxNetworkRetries(): void
    {
        // Queue: 3 network errors
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        // Should return the WP_Error after max retries
        $this->assertTrue(is_wp_error($result), 'Should return WP_Error after max network retries');
        $this->assertSame('http_request_failed', $result->get_error_code());

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, 'Should make exactly 3 attempts');
    }
}
