<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Api\Services\AnalyzeMediaService;
use AltContext\Api\Services\BatchRunService;
use AltContext\Settings\RecognitionPolicy;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\Services\AnalyzeMediaService
 */
class AnalyzeMediaServiceTest extends TestCase
{
    private AnalyzeMediaService $service;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption(RecognitionPolicy::OPTION, true);
        $host = new AnalysisJobsController();
        $this->service = new AnalyzeMediaService($host, new BatchRunService($host));
    }

    public function testAnalyzeMediaRejectsMissingPayload(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('idempotency_key', 'analyze-action-0001');
        $controller = new AnalysisJobsController();

        $result = $this->service->analyze_media($request, array($controller, 'validate_media_ids'));

        $this->assertTrue(is_wp_error($result));
        $this->assertSame('no_media_items', $result->get_error_code());
    }

    public function testAnalyzeMediaRequiresOriginatorKeyBeforeDispatch(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_items', [['media_id' => 101, 'media_url' => 'http://example.test/101.jpg']]);

        $result = (new AnalysisJobsController())->analyze_media($request);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('idempotency_key_required', $result->get_error_code());
        $this->assertSame(400, $result->get_error_data()['status']);
        $this->assertCount(0, $this->getHttpCalls());
    }

    public function testAnalyzeMediaRejectsInvalidKeysBeforeDispatch(): void
    {
        foreach (['', 'short', str_repeat('a', 129), 'invalid/key-00001', "analyze-action-01\n", ' analyze-action-01 ', 123, ['analyze-action-01']] as $key) {
            foreach (['param', 'header'] as $source) {
                // HTTP headers are strings; non-string inputs exercise the request parameter.
                if ($source === 'header' && (!is_string($key) || $key === '')) {
                    continue;
                }
                $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
                $request->set_param('media_items', [['media_id' => 101, 'media_url' => 'http://example.test/101.jpg']]);
                if ($source === 'param') {
                    $request->set_param('idempotency_key', $key);
                } else {
                    $request->set_header('Idempotency-Key', $key);
                }

                $result = (new AnalysisJobsController())->analyze_media($request);

                $this->assertInstanceOf(\WP_Error::class, $result);
                $this->assertSame('invalid_idempotency_key', $result->get_error_code());
                $this->assertSame(400, $result->get_error_data()['status']);
                $this->assertCount(0, $this->getHttpCalls());
            }
        }
    }

    public function testAnalyzeMediaForwardsOriginatorKeyOnBothTransports(): void
    {
        $path = tempnam(sys_get_temp_dir(), 'acx-opid-');
        file_put_contents($path, 'image-bytes');
        $GLOBALS['__ac_attached_file'][101] = $path;
        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/101.jpg';

        try {
            foreach (['url', 'multipart'] as $transport) {
                $filter = static fn(string $current): string => $transport;
                add_filter('acx_recognition_transport', $filter);
                try {
                    foreach (['param', 'header'] as $source) {
                        foreach ([str_repeat('a', 16), str_repeat('Z', 126) . '_-'] as $key) {
                            $this->queueHttpResponse([
                                'response' => ['code' => 202, 'message' => 'OK'],
                                'body' => '{"id":"job-opid","status":"pending"}',
                            ]);
                            $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
                            $request->set_param('media_ids', [101]);
                            if ($source === 'param') {
                                $request->set_param('idempotency_key', $key);
                            } else {
                                $request->set_header('Idempotency-Key', $key);
                            }
                            $before = count($this->getHttpCalls());

                            $result = (new AnalysisJobsController())->analyze_media($request);

                            $this->assertInstanceOf(\WP_REST_Response::class, $result);
                            $calls = $this->getHttpCalls();
                            $this->assertCount($before + 1, $calls);
                            $call = $calls[$before];
                            if ($transport === 'url') {
                                $this->assertStringNotContainsString('/multipart', $call['url']);
                                $payload = json_decode($call['args']['body'], true);
                                $this->assertSame($key, $payload['idempotency_key'] ?? null);
                            } else {
                                $this->assertStringContainsString('/recognition/analyze/multipart', $call['url']);
                                $this->assertStringContainsString(
                                    "Content-Disposition: form-data; name=\"idempotency_key\"\r\n\r\n" . $key . "\r\n",
                                    $call['args']['body']
                                );
                            }
                        }
                    }
                } finally {
                    remove_filter('acx_recognition_transport', $filter);
                }
            }
        } finally {
            unlink($path);
        }
    }
}
