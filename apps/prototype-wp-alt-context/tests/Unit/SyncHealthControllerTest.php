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
        $fixturePath = dirname(__DIR__) . '/fixtures/sync-health/debt-and-breaker-envelope.json';
        $fixture = json_decode((string) file_get_contents($fixturePath), true);
        $this->assertIsArray($fixture);

        $baseUrl = (string) ($fixture['breaker']['base_url'] ?? 'http://localhost:8000');
        $syncRepo = new class($fixture) extends NullSyncStateRepository {
            /** @var array<string,mixed> */
            private array $fixture;

            /**
             * @param array<string,mixed> $fixture
             */
            public function __construct(array $fixture)
            {
                $this->fixture = $fixture;
            }

            public function get_last_updated(string $tenant_id): ?string
            {
                $at = $this->fixture['last_pull']['at'] ?? null;
                return is_string($at) ? $at : null;
            }

            public function get_last_sync_result(string $tenant_id): string
            {
                return !empty($this->fixture['last_pull']['ok']) ? SyncPullResult::OK : SyncPullResult::FAILED;
            }

            public function get_conflict_count(string $tenant_id): int
            {
                return (int) ($this->fixture['conflicts']['open'] ?? 0);
            }
        };

        $outboxRepo = new class($fixture) extends OutboxQueryRepository {
            /** @var array<string,mixed> */
            private array $fixture;

            /**
             * @param array<string,mixed> $fixture
             */
            public function __construct(array $fixture)
            {
                $this->fixture = $fixture;
            }

            public function count_operations_by_status(string $tenant_id, ?string $status): int
            {
                return match ($status) {
                    'pending' => (int) ($this->fixture['outbox']['pending'] ?? 0),
                    'failed' => (int) ($this->fixture['outbox']['failed'] ?? 0),
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

        $this->assertSame($fixture['breaker'], $data['breaker']);
        $this->assertSame($fixture['outbox'], $data['outbox']);
        $this->assertSame($fixture['conflicts'], $data['conflicts']);
        $this->assertSame($fixture['replays'], $data['replays']);
        $this->assertSame($fixture['last_pull'], $data['last_pull']);
        $this->assertSame($fixture['warnings'], $data['warnings']);
    }

    public function testGetSyncHealthIncludesConflictThresholdWarning(): void
    {
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_conflict_count(string $tenant_id): int
            {
                return 30;
            }
        };

        $controller = new SyncHealthController($syncRepo);
        $response = $controller->get_sync_health(new WP_REST_Request('GET', '/acx/v1/recognition/sync/health'));
        $data = $response->get_data();

        $this->assertCount(1, $data['warnings']);
        $this->assertSame('open_conflicts_high', $data['warnings'][0]['code']);
        $this->assertSame(30, $data['warnings'][0]['count']);
        $this->assertSame(25, $data['warnings'][0]['threshold']);
    }

    public function testGetSyncHealthSurfacesBackendRosterRegressionWarning(): void
    {
        $conflictRepository = new class() extends \AltContext\Sovereign\Sync\ConflictRepository {
            public function find_open_backend_roster_regression(string $tenant_id): ?array
            {
                return ['id' => 7, 'backend_version' => 41, 'resolution_status' => 'open'];
            }
        };

        $controller = new SyncHealthController(new NullSyncStateRepository(), null, null, $conflictRepository);
        $response = $controller->get_sync_health(new WP_REST_Request('GET', '/acx/v1/recognition/sync/health'));
        $data = $response->get_data();

        $codes = array_column($data['warnings'], 'code');
        $this->assertContains('backend_roster_regressed', $codes, 'an open aggregate must surface as a degraded-mode warning');
    }

    public function testGetSyncHealthReportsOpenBreakerFromTransient(): void
    {
        // BR-131: remote recognition URLs must be https.
        $baseUrl = 'https://recognition.test';
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
        // BR-131: remote recognition URLs must be https.
        $baseUrl = 'https://recognition.test';
        $this->setOption('acx_recognition_source', 'service');
        $this->setOption('acx_recognition_url', $baseUrl);
        $circuitKey = RecognitionCircuitKeys::for_base_url($baseUrl);
        $failureKey = RecognitionCircuitKeys::failure_key_for_base_url($baseUrl);
        $GLOBALS['__ac_transients'] = [
            $circuitKey => ['value' => 1, 'expires' => time() + 60],
            $failureKey => ['value' => 2, 'expires' => time() + 60],
        ];

        $controller = new SyncHealthController();
        $before = $GLOBALS['__ac_transients'];
        $controller->get_sync_health(new WP_REST_Request('GET', '/acx/v1/recognition/sync/health'));

        $this->assertSame($before, $GLOBALS['__ac_transients']);
    }
}
