<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Api\RecognitionController;
use AltContext\Api\RecognitionCircuitKeys;
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
        $this->setOption('acx_recognition_source', 'service');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->setOption('acx_tier', 'free');

        $this->controller = new RecognitionController();
    }

    public function testProxyFallsBackToLocalhostWhenUrlNotConfigured(): void
    {
        $this->setOption('acx_recognition_url', '');
        $this->setOption('acx_recognition_source', 'local');

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

    public function testProxyUsesLocalhostWhenRecognitionSourceIsLocal(): void
    {
        $this->setOption('acx_recognition_url', 'https://service.example');
        $this->setOption('acx_recognition_source', 'local');

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

    /**
     * Regression test for finding M-1 (decision #1431).
     *
     * The existing testPluginBootstrapDefinesRecognitionConstantsFromEnvironment
     * test only seeds the process env via putenv(), which is the Pass 1 (getenv())
     * path inside acx_define_env_constant(). It does NOT exercise the Pass 2
     * fallback that reads Dotenv-loaded values from $_ENV / $_SERVER.
     *
     * Dotenv::createImmutable writes to $_ENV/$_SERVER but does NOT call putenv(),
     * so getenv() returns false for values loaded from .env / .env.local. This
     * test pre-seeds $_ENV in the child process (mimicking the post-Dotenv state)
     * with no putenv() calls. After alt-context.php loads:
     *   - Pass 1: getenv(ACX_RECOGNITION_URL) -> false; getenv(ACX_RECOGNITION_BASE_URL) -> false
     *   - Pass 2: $_ENV[ACX_RECOGNITION_URL] -> the pre-seeded value -> constant defined
     *
     * Dotenv createImmutable mode does NOT overwrite existing $_ENV entries, so
     * the pre-seeded values survive the safeLoad() call inside alt-context.php.
     */
    public function testPluginBootstrapDefinesRecognitionConstantsFromDotenvBackedEnvSuperglobal(): void
    {
        $script = <<<'PHP'
$_ENV['ACX_RECOGNITION_URL'] = 'https://dotenv-env.example';
$_ENV['ACX_RECOGNITION_API_KEY'] = 'dotenv-env-key';
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
    'getenv_url' => getenv('ACX_RECOGNITION_URL'),
    'getenv_key' => getenv('ACX_RECOGNITION_API_KEY'),
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
        // Pre-condition: getenv() must NOT see the values; if it did, the test
        // would be exercising the same Pass 1 path as the existing test.
        $this->assertFalse($data['getenv_url'], 'Pass 1 path leaked: getenv() saw the URL value');
        $this->assertFalse($data['getenv_key'], 'Pass 1 path leaked: getenv() saw the KEY value');
        // Actual assertion: constants must come from the $_ENV second-pass path.
        $this->assertSame('https://dotenv-env.example', $data['url'] ?? null);
        $this->assertSame('dotenv-env-key', $data['key'] ?? null);
    }

    public function testAnalyzeRequestUsesDeterministicUuidTenantId(): void
    {
        $GLOBALS['__ac_attachment_urls'][123] = 'http://example.test/media/123.jpg';

        // E15-11 Slice 2.2: pin to legacy URL transport — this test asserts
        // on the JSON envelope shape, not the new multipart path.
        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');

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
        add_filter('acx_recognition_source', static function (): string {
            return 'service';
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

    public function testFilteredBaseUrlBeatsSavedLocalSourceOption(): void
    {
        // E15-25: explicit local source wins; a code-managed service URL filter
        // must not override an operator-selected local mode.
        $this->setOption('acx_recognition_source', 'local');
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
        $this->assertStringContainsString('http://localhost:8000/recognition/jobs/test-123', $calls[0]['url']);
    }

    public function testBr07FilteredBaseUrlBeatsSavedNonEmptyOptionUrl(): void
    {
        // E15-12-BR-07: when both a saved option URL AND a code-managed filter
        // URL are set, the filter (code-managed) MUST win over the option
        // (operator-saved). The pre-fix candidate order in
        // get_recognition_base_url() was [constant, option, filter], which
        // meant a stale saved URL silently kept routing recognition traffic
        // even after an operator wired up a filter to point at a new
        // environment. The selector also reported the URL as option-owned and
        // editable, hiding the fact that code-managed source was active.
        $this->setOption('acx_recognition_url', 'https://stale-saved.example');
        $this->setOption('acx_recognition_source', 'service');

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
        $this->assertStringContainsString(
            'https://filtered.example/recognition/jobs/test-123',
            $calls[0]['url'],
            'filter URL must win over saved option URL when service mode is explicit'
        );
        $this->assertStringNotContainsString(
            'stale-saved.example',
            $calls[0]['url'],
            'request must not leak the stale saved option URL when a filter is active'
        );
    }

    public function testProxyRequestIgnoresInvalidFilteredBaseUrl(): void
    {
        $this->setOption('acx_recognition_url', '');
        $this->setOption('acx_recognition_source', 'local');

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

    public function testProxyRequestUsesFilteredApiKeyOverStaleOption(): void
    {
        $this->setOption('acx_recognition_api_key', 'option-api-key');

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

    public function testProxyRequestReturnsNotConfiguredWhenServiceModeHasNoUrl(): void
    {
        $this->setOption('acx_recognition_url', '');
        $this->setOption('acx_recognition_source', 'service');

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('recognition_not_configured', $result->get_error_code());
        $this->assertCount(0, $this->getHttpCalls());
    }

    public function testProxyRequestReturnsErrorWhenApiKeyMissing(): void
    {
        $this->setOption('acx_recognition_api_key', '');

        // E15-11 Slice 2.2: pin to legacy URL transport so the test reaches
        // the api_key check inside proxy_request without first failing the
        // multipart get_attached_file readability check.
        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');

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
    public function testProxyRequestUsesLocalTargetWhenConstantUrlWithoutExplicitSource(): void
    {
        define('ACX_RECOGNITION_URL', 'https://constant.example');
        $this->setOption('acx_recognition_source', '');

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

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testProxyRequestUsesConstantBaseUrlOverOption(): void
    {
        define('ACX_RECOGNITION_URL', 'https://constant.example');
        define('ACX_RECOGNITION_SOURCE', 'service');

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
        $this->setOption('acx_recognition_source', 'service');

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

    /**
     * CON-5: the circuit-breaker failure counter increment must be atomic.
     *
     * PA-2 mechanism assertion (a true cross-request race cannot be reproduced
     * in PHPUnit): a failing `ui_read` proxy request must serialize the
     * failure-counter read-modify-write *inside* a short-lived MySQL named lock
     * window, instead of the previous non-atomic get_transient/++/set_transient
     * that loses increments when two requests fail in the same window.
     *
     * Asserting only that GET_LOCK/RELEASE_LOCK queries appear (and GET_LOCK
     * precedes RELEASE_LOCK) is false confidence: the RMW writes
     * $GLOBALS['__ac_transients'] and never hits $wpdb, so a regression that
     * moves the increment outside the lock (acquire; release; set_transient)
     * emits a byte-identical query log and still passes. To pin the ordering we
     * snapshot the failure-counter transient at the moment GET_LOCK and
     * RELEASE_LOCK are issued: it must be unset when the lock is acquired and
     * already incremented when the lock is released — i.e. GET_LOCK <
     * set_transient < RELEASE_LOCK.
     */
    public function testUiReadFailureIncrementsCircuitCounterUnderAtomicNamedLock(): void
    {
        global $wpdb;

        $harness    = $this->makeUiReadHarness();
        $failureKey = RecognitionCircuitKeys::failure_key_for_base_url($harness->resolvedBaseUrl());

        // Snapshot the failure-counter transient at the moment GET_LOCK and
        // RELEASE_LOCK are issued. set_transient never touches $wpdb, so this is
        // the only way to witness whether the increment ran inside the lock.
        $transientAtGetLock = 'unset';
        $transientAtRelease = 'unset';
        $wpdb->onGetVar = static function (string $sql) use (
            &$transientAtGetLock,
            &$transientAtRelease,
            $failureKey
        ): void {
            if (stripos($sql, 'RELEASE_LOCK') !== false) {
                $transientAtRelease = get_transient($failureKey);
            } elseif (stripos($sql, 'GET_LOCK') !== false) {
                $transientAtGetLock = get_transient($failureKey);
            }
        };
        $wpdb->mockVar = '1'; // GET_LOCK(...) acquired.

        $this->queueHttpResponse(new WP_Error('http_request_failed', 'down'));
        $harness->callUiRead();

        $getLock = array_values(array_filter(
            $wpdb->queries,
            static fn (string $q): bool => stripos($q, 'GET_LOCK') !== false
        ));
        $releaseLock = array_values(array_filter(
            $wpdb->queries,
            static fn (string $q): bool => stripos($q, 'RELEASE_LOCK') !== false
        ));

        $this->assertNotEmpty(
            $getLock,
            'Failure-counter increment must acquire a named lock so concurrent failures cannot lose increments (CON-5).'
        );
        $this->assertNotEmpty(
            $releaseLock,
            'The named lock must be released after the increment (CON-5).'
        );

        // The increment is invisible in the query log, so pin its position via
        // the transient snapshots captured at lock acquire/release.
        $this->assertFalse(
            $transientAtGetLock,
            'Counter must NOT be incremented before the lock is acquired — the RMW belongs inside the lock window.'
        );
        $this->assertSame(
            1,
            $transientAtRelease,
            'Counter must already be incremented when the lock is released — proves the RMW ran inside the lock, '
            . 'catching a regression that moves the increment after RELEASE_LOCK (CON-5).'
        );
    }

    /**
     * CON-5 success criterion: the breaker trips once the failure count reaches
     * the threshold (default 2).
     *
     * This is a behavioral/threshold guard only — it does NOT guard the
     * atomicity fix. ui_read is max_retries=1, so two sequential failing calls
     * accumulate to the threshold the same way the pre-CON-5 non-atomic code
     * did in single-threaded PHPUnit. The atomicity regression guard is
     * testUiReadFailureIncrementsCircuitCounterUnderAtomicNamedLock; this test
     * pins the threshold/open-seconds wiring around it.
     */
    public function testUiReadBreakerTripsDeterministicallyAtThreshold(): void
    {
        global $wpdb;
        $wpdb->mockVar = '1'; // GET_LOCK(...) acquired.

        $harness = $this->makeUiReadHarness();
        $circuitKey = RecognitionCircuitKeys::for_base_url($harness->resolvedBaseUrl());

        $this->queueHttpResponse(new WP_Error('http_request_failed', 'down'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'down'));

        $harness->callUiRead();
        $this->assertFalse(
            get_transient($circuitKey),
            'Breaker stays closed below the failure threshold.'
        );

        $harness->callUiRead();
        $this->assertNotFalse(
            get_transient($circuitKey),
            'Breaker opens deterministically once the failure count reaches the threshold.'
        );
    }

    private function makeUiReadHarness(): object
    {
        return new class() extends AnalysisJobsController {
            /**
             * @return \WP_REST_Response|\WP_Error
             */
            public function callUiRead()
            {
                return $this->proxy_request('GET', '/ping', [], [], 'ui_read');
            }

            public function resolvedBaseUrl(): string
            {
                return \untrailingslashit($this->get_recognition_base_url());
            }
        };
    }
}
