<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionCircuitKeys;
use AltContext\Api\RecognitionEndpointResolver;
use AltContext\Api\SyncHealthController;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\SyncHealthController
 * @covers \AltContext\Api\RecognitionCircuitKeys
 */
class SyncHealthControllerTest extends TestCase
{
    public function testGetSyncHealthReturnsDebtAndBreakerEnvelope(): void
    {
        $baseUrl = 'http://localhost:8000';
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_last_updated(string $tenant_id): ?string
            {
                return '2026-06-11 12:00:00';
            }

            public function get_last_sync_result(string $tenant_id): string
            {
                return SyncPullResult::OK;
            }

            public function get_conflict_count(string $tenant_id): int
            {
                return 3;
            }
        };

        $outboxRepo = new class() extends OutboxQueryRepository {
            public function count_operations_by_status(string $tenant_id, ?string $status): int
            {
                return match ($status) {
                    'pending' => 5,
                    'failed' => 2,
                    default => 0,
                };
            }
        };

        $this->setOption('acx_recognition_source', 'service');
        $this->setOption('acx_recognition_url', $baseUrl);
        $controller = new SyncHealthController($syncRepo, $outboxRepo, new RecognitionEndpointResolver());
        $response = $controller->get_sync_health(new WP_REST_Request('GET', '/acx/v1/recognition/sync/health'));

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();

        $this->assertSame(
            [
                'state' => 'closed',
                'base_url' => $baseUrl,
                'opened_at' => null,
            ],
            $data['breaker']
        );
        $this->assertSame(['pending' => 5, 'failed' => 2], $data['outbox']);
        $this->assertSame(['open' => 3], $data['conflicts']);
        $this->assertSame(
            ['failed' => null, 'source' => 'unavailable_local'],
            $data['replays']
        );
        $this->assertSame(
            ['at' => '2026-06-11 12:00:00', 'ok' => true],
            $data['last_pull']
        );
    }

    public function testGetSyncHealthReportsOpenBreakerFromTransient(): void
    {
        $baseUrl = 'http://recognition.test';
        $this->setOption('acx_recognition_source', 'service');
        $this->setOption('acx_recognition_url', $baseUrl);
        $circuitKey = RecognitionCircuitKeys::for_base_url($baseUrl);
        set_transient($circuitKey, 1, 60);

        $controller = new SyncHealthController();
        $response = $controller->get_sync_health(new WP_REST_Request('GET', '/acx/v1/recognition/sync/health'));
        $data = $response->get_data();

        $this->assertSame('open', $data['breaker']['state']);
        delete_transient($circuitKey);
    }

    public function testGetSyncHealthDoesNotMutateTransients(): void
    {
        $GLOBALS['__ac_transients'] = [
            'acx_recognition_circuit_deadbeef' => ['value' => 1, 'expires' => time() + 60],
        ];

        $controller = new SyncHealthController();
        $before = $GLOBALS['__ac_transients'];
        $controller->get_sync_health(new WP_REST_Request('GET', '/acx/v1/recognition/sync/health'));

        $this->assertSame($before, $GLOBALS['__ac_transients']);
    }
}
