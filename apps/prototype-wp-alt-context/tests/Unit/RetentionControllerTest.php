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

        $this->assertSame(
            [
                'available' => false,
                'policy' => null,
                'recent_audit_events' => [],
            ],
            $response->get_data()
        );
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

        $this->assertSame(
            [
                'available' => false,
                'policy' => null,
                'recent_audit_events' => [],
            ],
            $response->get_data()
        );
        $this->assertArrayNotHasKey('acx_retention_status_' . md5((string) \get_site_url()), $GLOBALS['__ac_transients']);
    }

    public function testUpdatePolicyForwardsToBackendAndInvalidatesCache(): void
    {
        $tenantId = md5((string) \get_site_url());
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

    public function testTriggerExportInvalidatesCacheAfterSuccessfulProxy(): void
    {
        $tenantId = md5((string) \get_site_url());
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
        $tenantId = md5((string) \get_site_url());
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
}
