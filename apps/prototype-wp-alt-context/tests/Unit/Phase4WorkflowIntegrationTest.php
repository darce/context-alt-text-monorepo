<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ConflictController;
use AltContext\Api\SyncStatusController;
use AltContext\Sovereign\Sync\ConflictResolutionService;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Tests\Stubs\InMemoryConflictRepository;
use AltContext\Tests\Stubs\InMemoryOutboxDrain;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\TrackingSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\ConflictController
 * @covers \AltContext\Api\SyncStatusController
 */
class Phase4WorkflowIntegrationTest extends TestCase
{
    public function testProjectionConflictCanBeQueriedAndResolvedThroughRestAndRefreshesMetrics(): void
    {
        $tenantId = self::currentTenantId();
        $conflict = [
            'id' => 41,
            'tenant_id' => $tenantId,
            'entity_type' => 'member',
            'entity_key' => 'identity-41',
            'outbox_id' => 0,
            'expected_base_version' => 7,
            'backend_version' => 8,
            'local_revision' => 2,
            'conflict_code' => 'curated_member_deleted',
            'machine_payload' => ['status' => 'missing_from_snapshot'],
            'local_payload' => ['cluster_uuid' => 'cluster-local', 'is_curated' => true],
            'resolution_status' => 'open',
            'resolved_at' => null,
            'created_at' => '2026-03-11 10:00:00',
        ];

        $repository = new InMemoryConflictRepository([$conflict]);
        $membersRepository = new TrackingMembersRepository();
        $resolutionService = new ConflictResolutionService(
            $repository,
            new OutboxDrain(),
            new NullClustersRepository(),
            $membersRepository
        );
        $syncState = new TrackingSyncStateRepository([
            'conflict_count' => 1,
            'last_updated' => '2026-03-11 09:59:00',
            'last_sync_result' => 'ok',
        ]);

        $controller = new ConflictController(
            $repository,
            $resolutionService,
            new OutboxDrain(),
            $syncState
        );

        $listResponse = $controller->list_conflicts(
            new WP_REST_Request('GET', '/acx/v1/recognition/conflicts')
        );
        $listData = $listResponse->get_data();

        $this->assertSame(1, $listData['total']);
        $this->assertCount(1, $listData['items']);
        $this->assertSame(['accepted', 'dismissed'], $listData['items'][0]['allowed_resolutions']);

        $detailRequest = new WP_REST_Request('GET', '/acx/v1/recognition/conflicts/41');
        $detailRequest->set_param('id', 41);
        $detailResponse = $controller->get_conflict_detail($detailRequest);
        $detailData = $detailResponse->get_data();

        $this->assertSame('curated_member_deleted', $detailData['conflict']['conflict_code']);
        $this->assertSame(['status' => 'missing_from_snapshot'], $detailData['conflict']['machine_payload']);

        $resolveRequest = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/41/resolve');
        $resolveRequest->set_param('id', 41);
        $resolveRequest->set_param('resolution_status', 'accepted');
        $resolveResponse = $controller->resolve_conflict($resolveRequest);
        $resolveData = $resolveResponse->get_data();

        $this->assertSame('accepted', $resolveData['conflict']['resolution_status']);
        $this->assertSame(1, $syncState->refreshCount);
        $this->assertSame($tenantId, $syncState->lastTenantId);
        $this->assertSame('identity-41', $membersRepository->deletedIdentityUuid);
    }

    public function testFailedOutboxOperationCanBeQueriedAndRetriedThroughRest(): void
    {
        $tenantId = self::currentTenantId();
        $operation = [
            'id' => 11,
            'tenant_id' => $tenantId,
            'operation_type' => 'cluster_label_updated',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-11',
            'status' => 'failed',
            'attempts' => 5,
            'expected_base_version' => 4,
            'local_revision' => 2,
            'last_error_code' => 'dispatch_failed',
            'last_error_message' => 'Replay failed.',
            'payload' => ['label' => 'Updated'],
            'created_at' => '2026-03-11 10:00:00',
            'last_attempted_at' => '2026-03-11 10:05:00',
            'acknowledged_at' => null,
        ];

        $outboxDrain = new InMemoryOutboxDrain([$operation]);
        $syncState = new TrackingSyncStateRepository();
        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            $outboxDrain,
            $syncState
        );

        $listResponse = $controller->list_failed_outbox_operations(
            new WP_REST_Request('GET', '/acx/v1/recognition/outbox/failed')
        );
        $listData = $listResponse->get_data();

        $this->assertSame(1, $listData['total']);
        $this->assertSame('failed', $listData['items'][0]['status']);
        $this->assertSame('dispatch_failed', $listData['items'][0]['last_error_code']);

        $retryRequest = new WP_REST_Request('POST', '/acx/v1/recognition/outbox/11/retry');
        $retryRequest->set_param('id', 11);
        $retryResponse = $controller->retry_failed_operation($retryRequest);
        $retryData = $retryResponse->get_data();

        $this->assertSame('pending', $retryData['operation']['status']);
        $this->assertSame(0, $retryData['operation']['attempts']);
        $this->assertTrue($outboxDrain->retryScheduled);
        $this->assertSame(1, $syncState->refreshCount);
        $this->assertSame($tenantId, $syncState->lastTenantId);
    }

    public function testFailedOutboxOperationCanBeDiscardedThroughRest(): void
    {
        $tenantId = self::currentTenantId();
        $operation = [
            'id' => 17,
            'tenant_id' => $tenantId,
            'operation_type' => 'cluster_label_updated',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-17',
            'status' => 'failed',
            'attempts' => 5,
            'expected_base_version' => 4,
            'local_revision' => 2,
            'last_error_code' => 'dispatch_failed',
            'last_error_message' => 'Replay failed.',
            'payload' => ['label' => 'Updated'],
            'created_at' => '2026-03-11 10:00:00',
            'last_attempted_at' => '2026-03-11 10:05:00',
            'acknowledged_at' => null,
        ];

        $outboxDrain = new InMemoryOutboxDrain([$operation]);
        $syncState = new TrackingSyncStateRepository();
        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            $outboxDrain,
            $syncState
        );

        $discardRequest = new WP_REST_Request('POST', '/acx/v1/recognition/outbox/17/discard');
        $discardRequest->set_param('id', 17);
        $discardResponse = $controller->discard_operation($discardRequest);
        $discardData = $discardResponse->get_data();

        $this->assertSame(200, $discardResponse->get_status());
        $this->assertSame('discarded', $discardData['operation']['status']);
        $this->assertSame(1, $syncState->refreshCount);
        $this->assertSame($tenantId, $syncState->lastTenantId);
    }

    /**
     * @dataProvider syncHealthMatrixProvider
     */
    public function testSyncStatusControllerClassifiesStateMatrixThroughRest(
        array $state,
        string $expectedHealth
    ): void {
        $controller = new SyncStatusController(new TrackingSyncStateRepository($state));

        $response = $controller->get_sync_status(
            new WP_REST_Request('GET', '/acx/v1/recognition/sync-status')
        );
        $data = $response->get_data();

        $this->assertSame($expectedHealth, $data['sync_health']);
    }

    public static function syncHealthMatrixProvider(): array
    {
        return [
            'healthy' => [
                [
                    'last_updated' => 'recent',
                    'last_sync_result' => 'ok',
                ],
                'healthy',
            ],
            'queued' => [
                [
                    'last_updated' => 'recent',
                    'last_sync_result' => 'ok',
                    'pending_curation_operations' => 2,
                ],
                'queued',
            ],
            'stale' => [
                [
                    'last_updated' => '2026-03-01 10:00:00',
                    'last_sync_result' => 'ok',
                ],
                'stale',
            ],
            'conflicts' => [
                [
                    'last_updated' => 'recent',
                    'last_sync_result' => 'ok',
                    'conflict_count' => 1,
                ],
                'conflicts',
            ],
            'failures' => [
                [
                    'last_updated' => 'recent',
                    'last_sync_result' => 'ok',
                    'failed_curation_operations' => 1,
                ],
                'failures',
            ],
            'offline' => [
                [
                    'last_updated' => 'recent',
                    'last_sync_result' => 'unreachable',
                ],
                'offline',
            ],
        ];
    }
}

final class TrackingMembersRepository extends NullIdentityMembersRepository
{
    public ?string $deletedIdentityUuid = null;

    public function delete_member(string $identity_uuid, string $tenant_id): int
    {
        $this->deletedIdentityUuid = $identity_uuid;

        return 1;
    }
}
