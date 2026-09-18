<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RetentionController;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\RetentionController
 */
class RetentionControllerTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        // RECOG-1: default source flipped to 'service' with an empty default URL.
        // Pin a service target so backend-proxy paths have a non-empty effective target.
        $this->setOption('acx_recognition_url', 'https://recognition.test');
    }

    private function tenantId(): string
    {
        $controller = new RetentionController();
        $method = new \ReflectionMethod($controller, 'get_tenant_id');
        $method->setAccessible(true);

        return (string) $method->invoke($controller);
    }

    public function testGetStatusProxiesPolicyAndAuditAndCachesResult(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'retention_mode' => 'dispose_after_ack',
                'last_export_at' => '2026-03-12T11:00:00Z',
                'last_purge_at' => null,
                'retention_updated_at' => '2026-03-12T10:00:00Z',
            ]),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'items' => [
                    [
                        'id' => 'evt-1',
                        'event_type' => 'policy_updated',
                        'actor' => 'api_key:test',
                        'created_at' => '2026-03-12T10:00:00Z',
                        'payload' => ['retention_mode' => 'dispose_after_ack'],
                    ],
                ],
            ]),
        ]);

        $controller = new RetentionController();

        $first = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));
        $second = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(
            [
                'available' => true,
                'policy' => [
                    'retention_mode' => 'dispose_after_ack',
                    'last_export_at' => '2026-03-12T11:00:00Z',
                    'last_purge_at' => null,
                    'retention_updated_at' => '2026-03-12T10:00:00Z',
                ],
                'recent_audit_events' => [
                    [
                        'id' => 'evt-1',
                        'event_type' => 'policy_updated',
                        'actor' => 'api_key:test',
                        'created_at' => '2026-03-12T10:00:00Z',
                        'payload' => ['retention_mode' => 'dispose_after_ack'],
                    ],
                ],
            ],
            $first->get_data()
        );
        $this->assertSame($first->get_data(), $second->get_data());

        $calls = $this->getHttpCalls();
        $this->assertCount(2, $calls);
        $this->assertStringContainsString('/retention/policy', $calls[0]['url']);
        $this->assertStringContainsString('/retention/audit?limit=5', $calls[1]['url']);
    }

    public function testGetStatusReturnsGracefulFallbackWhenBackendUnavailable(): void
    {
        $this->queueHttpResponse(new WP_Error('backend_unavailable', 'offline', ['status' => 503]));
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['items' => []]),
        ]);

        $controller = new RetentionController();
        $response = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(200, $response->get_status());
        $this->assertTypedUnavailable($response->get_data(), 'upstream_5xx', 'recognition', 503);
        $this->assertStringNotContainsString('offline', (string) wp_json_encode($response->get_data()));
    }

    public function testGetStatusReturnsGracefulFallbackWhenBackendReturnsNonSuccessStatus(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 501, 'message' => 'Not Implemented'],
            'body' => json_encode(['detail' => 'not ready']),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['items' => []]),
        ]);

        $controller = new RetentionController();
        $response = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(200, $response->get_status());
        $this->assertTypedUnavailable($response->get_data(), 'upstream_5xx', 'recognition', 501);
        $this->assertStringNotContainsString('not ready', (string) wp_json_encode($response->get_data()));
        $this->assertArrayNotHasKey('acx_retention_status_' . $this->tenantId(), $GLOBALS['__ac_transients']);
    }

    public function testGetStatusTypedUnavailableIsRetryablePayload(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 503, 'message' => 'Service Unavailable'],
            'body' => json_encode([
                'detail' => [
                    'code' => 'description_service_unavailable',
                    'message' => 'Description service is unavailable.',
                    'operation_id' => null,
                    'startup_id' => null,
                    'timing' => [
                        'queue_ms' => null,
                        'ramp_up_ms' => null,
                        'processing_ms' => null,
                        'startup_ms' => null,
                        'server_elapsed_ms' => null,
                    ],
                ],
            ]),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['items' => []]),
        ]);

        $controller = new RetentionController();
        $response = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(200, $response->get_status());
        $this->assertTypedUnavailable($response->get_data(), 'upstream_5xx', 'recognition', 503);
        $this->assertStringNotContainsString(
            'Description service is unavailable.',
            (string) wp_json_encode($response->get_data())
        );
        $this->assertArrayNotHasKey('acx_retention_status_' . $this->tenantId(), $GLOBALS['__ac_transients']);
    }

    public function testGetStatusUnavailableWhenRecognitionNotConfigured(): void
    {
        $this->setOption('acx_recognition_url', '');

        $controller = new RetentionController();
        $response = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(200, $response->get_status());
        $this->assertTypedUnavailable($response->get_data(), 'not_configured', 'recognition', 500);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testGetStatusUnavailableWhenApiKeyMissing(): void
    {
        $this->setOption('acx_recognition_api_key', '');

        $controller = new RetentionController();
        $response = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(200, $response->get_status());
        $this->assertTypedUnavailable($response->get_data(), 'api_key_missing', 'recognition', 500);
        $this->assertSame([], $this->getHttpCalls());
        $this->assertStringNotContainsString('test-key', (string) wp_json_encode($response->get_data()));
    }

    public function testGetStatusUnavailableWhenCircuitOpen(): void
    {
        global $wpdb;
        $wpdb->mockVar = '1';

        $failure = [
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => json_encode(['detail' => 'boom-secret-detail']),
        ];
        $this->queueHttpResponse($failure);
        $this->queueHttpResponse($failure);

        $controller = new RetentionController();
        $first = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));
        $this->assertTypedUnavailable($first->get_data(), 'upstream_5xx', 'recognition', 500);
        $this->assertStringNotContainsString('boom-secret-detail', (string) wp_json_encode($first->get_data()));

        $second = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));
        $this->assertSame(200, $second->get_status());
        $this->assertTypedUnavailable($second->get_data(), 'circuit_open', 'recognition', 503);
        $this->assertCount(2, $this->getHttpCalls());
    }

    public function testGetStatusUnavailableMapsTimeout(): void
    {
        $timeout = new WP_Error(
            'http_request_failed',
            'cURL error 28: Operation timed out after 2000 milliseconds'
        );
        $this->queueHttpResponse($timeout);
        $this->queueHttpResponse($timeout);

        $controller = new RetentionController();
        $response = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(200, $response->get_status());
        $this->assertTypedUnavailable($response->get_data(), 'timeout', 'recognition', null);
        $this->assertStringNotContainsString('cURL error 28', (string) wp_json_encode($response->get_data()));
    }

    public function testGetStatusUnavailableMapsUpstream4xx(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'no such tenant secret']),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['items' => []]),
        ]);

        $controller = new RetentionController();
        $response = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(200, $response->get_status());
        $this->assertTypedUnavailable($response->get_data(), 'upstream_4xx', 'recognition', 404);
        $this->assertStringNotContainsString('no such tenant secret', (string) wp_json_encode($response->get_data()));
    }

    public function testGetStatusUnavailableMapsContractMismatch(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['unexpected' => true]),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['items' => []]),
        ]);

        $controller = new RetentionController();
        $response = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(200, $response->get_status());
        $this->assertTypedUnavailable($response->get_data(), 'contract_mismatch', 'recognition', 200);
    }

    public function testGetStatusUnavailableSourcesRetryAfterFromProxyHeader(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 503, 'message' => 'Service Unavailable'],
            'headers' => ['Retry-After' => '30'],
            'body' => json_encode(['detail' => 'overloaded-secret']),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['items' => []]),
        ]);

        $controller = new RetentionController();
        $response = $controller->get_status(new WP_REST_Request('GET', '/acx/v1/retention/status'));

        $this->assertSame(200, $response->get_status());
        $this->assertTypedUnavailable($response->get_data(), 'upstream_5xx', 'recognition', 503, 30);
        $this->assertStringNotContainsString('overloaded-secret', (string) wp_json_encode($response->get_data()));
    }

    public function testDescribeBreakerDoesNotBlankRetentionStatus(): void
    {
        global $wpdb;
        $wpdb->mockVar = '1';
        $this->setOption('acx_recognition_api_key', 'test-key');

        $describe = new class() extends RetentionController {
            public function failDescribe()
            {
                return $this->proxy_request('POST', '/scene/describe/multipart', [], [], 'description');
            }
        };
        $error = [
            'response' => ['code' => 502, 'message' => 'Bad Gateway'],
            'body' => json_encode([
                'detail' => [
                    'code' => 'description_service_error',
                    'message' => 'adapter failed',
                    'operation_id' => 'op-retry-opaque',
                    'startup_id' => null,
                ],
            ]),
        ];
        $this->queueHttpResponse($error);
        $this->queueHttpResponse($error);
        $describe->failDescribe();
        $describe->failDescribe();

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'retention_mode' => 'dispose_after_ack',
                'last_export_at' => null,
                'last_purge_at' => null,
                'retention_updated_at' => '2026-03-12T10:00:00Z',
            ]),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['items' => []]),
        ]);

        $response = (new RetentionController())->get_status(
            new WP_REST_Request('GET', '/acx/v1/retention/status')
        );

        $this->assertSame(200, $response->get_status());
        $this->assertTrue($response->get_data()['available'] ?? false);
        $this->assertSame('dispose_after_ack', $response->get_data()['policy']['retention_mode'] ?? null);
    }

    public function testUpdatePolicyForwardsToBackendAndInvalidatesCache(): void
    {
        $tenantId = $this->tenantId();
        set_transient('acx_retention_status_' . $tenantId, ['available' => true], 60);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['retention_mode' => 'purge_on_demand']),
        ]);

        $controller = new RetentionController();
        $request = new WP_REST_Request('PATCH', '/acx/v1/retention/policy');
        $request->set_body_params(['retention_mode' => 'purge_on_demand']);

        $response = $controller->update_policy($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertFalse(isset($GLOBALS['__ac_transients']['acx_retention_status_' . $tenantId]));

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/retention/policy', $calls[0]['url']);
        $this->assertSame('PATCH', $calls[0]['args']['method']);
        $this->assertSame('{"retention_mode":"purge_on_demand"}', $calls[0]['args']['body']);
    }

    public function testUpdatePolicySanitizesRetentionModeBeforeProxying(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['retention_mode' => 'purge_on_demand']),
        ]);

        $controller = new RetentionController();
        $request = new WP_REST_Request('PATCH', '/acx/v1/retention/policy');
        $request->set_body_params(['retention_mode' => '  PURGE_ON_DEMAND  ']);

        $response = $controller->update_policy($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(
            '{"retention_mode":"purge_on_demand"}',
            $this->getHttpCalls()[0]['args']['body']
        );
    }

    public function testTriggerExportInvalidatesCacheAfterSuccessfulProxy(): void
    {
        $tenantId = $this->tenantId();
        set_transient('acx_retention_status_' . $tenantId, ['available' => true], 60);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['exported_at' => '2026-03-12T11:30:00Z']),
        ]);

        $controller = new RetentionController();
        $response = $controller->trigger_export(new WP_REST_Request('POST', '/acx/v1/retention/export'));

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertFalse(isset($GLOBALS['__ac_transients']['acx_retention_status_' . $tenantId]));
        $this->assertStringContainsString('/retention/export', $this->getHttpCalls()[0]['url']);
    }

    public function testTriggerPurgeRequiresConfirmation(): void
    {
        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/purge');
        $request->set_body_params(['scope' => 'all']);

        $response = $controller->trigger_purge($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('retention_purge_confirmation_required', $response->get_error_code());
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testTriggerPurgeProxiesAndForcesSyncPull(): void
    {
        $tenantId = $this->tenantId();
        set_transient('acx_retention_status_' . $tenantId, ['available' => true], 60);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['deleted_counts' => ['clusters' => 3], 'scope' => 'all']),
        ]);

        $syncJob = new RetentionControllerSyncPullJobSpy();
        $controller = new RetentionController($syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/retention/purge');
        $request->set_body_params([
            'confirm' => true,
            'scope' => 'all',
        ]);

        $response = $controller->trigger_purge($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame($tenantId, $syncJob->performedTenantId);
        $this->assertFalse(isset($GLOBALS['__ac_transients']['acx_retention_status_' . $tenantId]));

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/retention/purge', $calls[0]['url']);
        $this->assertSame('{"confirm":true,"scope":"all"}', $calls[0]['args']['body']);
    }

    public function testTriggerPurgeSanitizesScopeAndBooleanConfirmationBeforeProxying(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['deleted_counts' => ['clusters' => 1], 'scope' => 'all']),
        ]);

        $syncJob = new RetentionControllerSyncPullJobSpy();
        $controller = new RetentionController($syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/retention/purge');
        $request->set_body_params([
            'confirm' => ' TRUE ',
            'scope' => ' ALL ',
        ]);

        $response = $controller->trigger_purge($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame('{"confirm":true,"scope":"all"}', $this->getHttpCalls()[0]['args']['body']);
    }

    public function testTriggerPurgeRejectsFalseStringConfirmation(): void
    {
        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/purge');
        $request->set_body_params([
            'confirm' => ' FALSE ',
            'scope' => ' all ',
        ]);

        $response = $controller->trigger_purge($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('retention_purge_confirmation_required', $response->get_error_code());
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testTriggerPurgeReturnsErrorWhenSyncRefreshIsUnavailable(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['deleted_counts' => ['clusters' => 3], 'scope' => 'all']),
        ]);

        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/purge');
        $request->set_body_params([
            'confirm' => true,
            'scope' => 'all',
        ]);

        $response = $controller->trigger_purge($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('retention_sync_refresh_unavailable', $response->get_error_code());
    }

    public function testTriggerPurgeReturnsErrorWhenSyncRefreshFails(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['deleted_counts' => ['clusters' => 3], 'scope' => 'all']),
        ]);

        $syncJob = new RetentionControllerSyncPullJobSpy(SyncPullResult::failed());
        $controller = new RetentionController($syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/retention/purge');
        $request->set_body_params([
            'confirm' => true,
            'scope' => 'all',
        ]);

        $response = $controller->trigger_purge($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('retention_sync_refresh_failed', $response->get_error_code());
        $this->assertSame('failed', $response->get_error_data()['sync_status'] ?? null);
    }

    public function testTriggerImportRejectsMissingDataField(): void
    {
        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/import');
        $request->set_body_params(['not_data' => []]);

        $response = $controller->trigger_import($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('retention_import_invalid_body', $response->get_error_code());
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testTriggerImportRejectsNonArrayDataField(): void
    {
        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/import');
        $request->set_body_params(['data' => 'not-an-array']);

        $response = $controller->trigger_import($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('retention_import_invalid_body', $response->get_error_code());
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testTriggerImportProxiesDataToBackend(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => 'abc123',
                'schema_version' => 2,
                'imported_at' => '2026-03-23T10:00:00Z',
                'counts' => ['clusters' => 1],
            ]),
        ]);

        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/import');
        $request->set_body_params(['data' => ['schema_version' => 2, 'clusters' => []]]);

        $response = $controller->trigger_import($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/retention/import', $calls[0]['url']);
        $this->assertSame(
            json_encode(['data' => ['schema_version' => 2, 'clusters' => []]]),
            $calls[0]['args']['body']
        );
    }

    public function testTriggerImportInvalidatesCacheAfterSuccess(): void
    {
        $tenantId = $this->tenantId();
        set_transient('acx_retention_status_' . $tenantId, ['available' => true], 60);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => 'abc123',
                'schema_version' => 2,
                'imported_at' => '2026-03-23T10:00:00Z',
                'counts' => [],
            ]),
        ]);

        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/import');
        $request->set_body_params(['data' => ['schema_version' => 2]]);

        $controller->trigger_import($request);

        $this->assertFalse(isset($GLOBALS['__ac_transients']['acx_retention_status_' . $tenantId]));
    }

    public function testListAuditEventsForwardsLimitOffsetAndEventType(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['items' => [], 'total' => 0, 'limit' => 10, 'offset' => 5]),
        ]);

        $controller = new RetentionController();
        $request = new WP_REST_Request('GET', '/acx/v1/retention/audit');
        $request->set_param('limit', '10');
        $request->set_param('offset', '5');
        $request->set_param('event_type', 'export_completed');

        $response = $controller->list_audit_events($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/retention/audit', $calls[0]['url']);
        $this->assertStringContainsString('limit=10', $calls[0]['url']);
        $this->assertStringContainsString('offset=5', $calls[0]['url']);
        $this->assertStringContainsString('event_type=export_completed', $calls[0]['url']);
    }

    public function testListAuditEventsOmitsUnsetOptionalParams(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['items' => [], 'total' => 0, 'limit' => 20, 'offset' => 0]),
        ]);

        $controller = new RetentionController();
        $request = new WP_REST_Request('GET', '/acx/v1/retention/audit');

        $response = $controller->list_audit_events($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $url = $this->getHttpCalls()[0]['url'];
        $this->assertStringNotContainsString('event_type', $url);
    }

    public function testApplyPresetRejectsMissingPresetField(): void
    {
        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/policy/preset');
        $request->set_body_params(['preset' => '']);

        $response = $controller->apply_preset($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('missing_preset', $response->get_error_code());
    }

    public function testApplyPresetProxiesPresetToBackend(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'retention_mode' => 'dispose_after_ack',
                'preset'         => 'gdpr',
            ]),
        ]);

        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/policy/preset');
        $request->set_body_params(['preset' => 'gdpr']);

        $response = $controller->apply_preset($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/retention/policy/preset', $calls[0]['url']);
        $this->assertSame('POST', $calls[0]['args']['method']);
        $this->assertSame('{"preset":"gdpr"}', $calls[0]['args']['body']);
    }

    public function testApplyPresetInvalidatesCacheAfterSuccess(): void
    {
        $tenantId = $this->tenantId();
        set_transient('acx_retention_status_' . $tenantId, ['available' => true], 60);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['retention_mode' => 'dispose_after_ack', 'preset' => 'gdpr']),
        ]);

        $controller = new RetentionController();
        $request = new WP_REST_Request('POST', '/acx/v1/retention/policy/preset');
        $request->set_body_params(['preset' => 'gdpr']);

        $controller->apply_preset($request);

        $this->assertFalse(isset($GLOBALS['__ac_transients']['acx_retention_status_' . $tenantId]));
    }

    /**
     * @param array<string, mixed> $payload
     * @return array<string, mixed>
     */
    private function assertTypedUnavailable(
        array $payload,
        string $reason,
        string $service,
        ?int $httpStatus,
        ?int $retryAfter = null
    ): array {
        $this->assertFalse($payload['available']);
        $this->assertNull($payload['policy']);
        $this->assertSame([], $payload['recent_audit_events']);
        $this->assertArrayHasKey('unavailable', $payload);
        $unavailable = $payload['unavailable'];
        $this->assertIsArray($unavailable);
        $this->assertSame(
            ['reason', 'service', 'http_status', 'retry_after_seconds', 'checked_at'],
            array_keys($unavailable)
        );
        $this->assertSame($reason, $unavailable['reason']);
        $this->assertSame($service, $unavailable['service']);
        $this->assertSame($httpStatus, $unavailable['http_status']);
        $this->assertSame($retryAfter, $unavailable['retry_after_seconds']);
        $this->assertMatchesRegularExpression(
            '/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/',
            $unavailable['checked_at']
        );

        return $unavailable;
    }
}

class RetentionControllerSyncPullJobSpy implements SyncPullJobInterface
{
    public ?string $performedTenantId = null;
    private SyncPullResult $result;

    public function __construct(?SyncPullResult $result = null)
    {
        $this->result = $result ?? SyncPullResult::ok();
    }

    public function perform(string $tenant_id): SyncPullResult
    {
        $this->performedTenantId = $tenant_id;
        return $this->result;
    }

    public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
    {
        $this->performedTenantId = $tenant_id;
        return $this->result;
    }

    public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
    {
        $this->performedTenantId = $tenant_id;
        return $this->result;
    }
}
