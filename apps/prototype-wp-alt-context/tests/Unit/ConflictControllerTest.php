<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ConflictController;
use AltContext\Sovereign\Sync\ConflictResolutionService;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Tests\Stubs\InMemoryConflictRepository;
use AltContext\Tests\Stubs\InMemoryOutboxDrain;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\Stubs\TrackingSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\ConflictController
 */
class ConflictControllerTest extends TestCase
{
    public function testListConflictsReturnsPaginatedEnvelope(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 9,
                'tenant_id' => $tenantId,
                'entity_key' => 'cluster-outbox',
                'outbox_id' => 44,
                'conflict_code' => 'version_conflict',
                'machine_payload' => ['label' => 'Remote'],
                'local_payload' => ['label' => 'Local'],
                'created_at' => '2026-03-11 11:00:00',
            ]),
            $this->buildConflictRecord([
                'id' => 7,
                'tenant_id' => $tenantId,
                'entity_key' => 'cluster-1',
                'outbox_id' => 0,
                'conflict_code' => 'curated_cluster_deleted',
                'machine_payload' => ['status' => 'missing_from_snapshot'],
                'local_payload' => ['label' => 'Curated'],
                'created_at' => '2026-03-11 10:00:00',
            ]),
        ]);

        $outboxDrain = new InMemoryOutboxDrain([
            $this->buildOutboxOperation([
                'id' => 44,
                'tenant_id' => $tenantId,
                'entity_key' => 'cluster-outbox',
                'operation_type' => 'cluster_label_updated',
                'payload' => ['label' => 'Local'],
                'created_at' => '2026-03-11 11:00:00',
            ]),
        ]);

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            $outboxDrain
        );

        $response = $controller->list_conflicts(new WP_REST_Request('GET', '/acx/v1/recognition/conflicts'));
        $data = $response->get_data();

        $this->assertSame(2, $data['total']);
        $this->assertCount(2, $data['items']);
        $this->assertSame([9, 7], array_column($data['items'], 'id'));
        $this->assertSame(44, $data['items'][0]['outbox_id']);
        $this->assertSame('cluster-outbox', $data['items'][0]['entity_key']);
        $this->assertSame(['accepted', 'dismissed'], $data['items'][0]['allowed_resolutions']);
        $this->assertSame('Remote label', $data['items'][0]['backend_proposed_value']);
        $this->assertSame(0, $data['items'][1]['outbox_id']);
        $this->assertSame(['accepted', 'dismissed'], $data['items'][1]['allowed_resolutions']);
        $this->assertSame(1, $outboxDrain->findByIdsCalls);
        $this->assertSame(0, $outboxDrain->findByIdCalls);
    }

    public function testListConflictsReturnsDismissOnlyForUnsupportedOutboxOperations(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 13,
                'tenant_id' => $tenantId,
                'entity_type' => 'person',
                'entity_key' => 'person-1',
                'outbox_id' => 88,
                'expected_base_version' => 2,
                'backend_version' => 3,
                'local_revision' => 1,
                'conflict_code' => 'version_conflict',
                'machine_payload' => ['name' => 'Remote'],
                'local_payload' => ['name' => 'Local'],
                'created_at' => '2026-03-11 09:00:00',
            ]),
        ]);

        $outboxDrain = new InMemoryOutboxDrain([
            $this->buildOutboxOperation([
                'id' => 88,
                'tenant_id' => $tenantId,
                'operation_type' => 'person_updated',
                'entity_type' => 'person',
                'entity_key' => 'person-1',
                'payload' => ['name' => 'Local'],
                'created_at' => '2026-03-11 09:00:00',
            ]),
        ]);

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            $outboxDrain
        );

        $response = $controller->list_conflicts(new WP_REST_Request('GET', '/acx/v1/recognition/conflicts'));
        $data = $response->get_data();

        $this->assertSame(['dismissed'], $data['items'][0]['allowed_resolutions']);
    }

    public function testListConflictsReturnsAcceptedAndDismissedForRevertMergeCompoundOperation(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 15,
                'tenant_id' => $tenantId,
                'entity_key' => 'cluster-target',
                'outbox_id' => 91,
                'conflict_code' => 'version_conflict',
            ]),
        ]);

        $outboxDrain = new InMemoryOutboxDrain([
            $this->buildOutboxOperation([
                'id' => 91,
                'tenant_id' => $tenantId,
                'operation_type' => 'revert_merge_cluster',
                'entity_key' => 'cluster-target',
                'payload' => [
                    'target_cluster_id' => 'cluster-target',
                    'desired_source_cluster_id' => 'cluster-restored',
                    'moved_identity_ids' => ['identity-1'],
                ],
            ]),
        ]);

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            $outboxDrain
        );

        $response = $controller->list_conflicts(new WP_REST_Request('GET', '/acx/v1/recognition/conflicts'));
        $data = $response->get_data();

        $this->assertSame(['accepted', 'dismissed'], $data['items'][0]['allowed_resolutions']);
    }

    public function testListConflictsReturnsAcceptBackendMergeAndDismissedForPersonNameConflict(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 18,
                'tenant_id' => $tenantId,
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-person',
                'conflict_code' => 'person_name_conflict',
                'backend_proposed_value' => 'Backend Name',
                'machine_payload' => ['proposed_value' => 'Backend Name'],
                'local_payload' => ['label' => 'Local Name'],
            ]),
        ]);

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            new InMemoryOutboxDrain()
        );

        $response = $controller->list_conflicts(new WP_REST_Request('GET', '/acx/v1/recognition/conflicts'));
        $data = $response->get_data();

        $this->assertSame(['accept_backend', 'merge', 'dismissed'], $data['items'][0]['allowed_resolutions']);
    }

    public function testListConflictsReturnsAcceptBackendAndDismissedForDriftConflict(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 19,
                'tenant_id' => $tenantId,
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-drift',
                'conflict_code' => 'drift_conflict',
                'backend_proposed_value' => 'Backend Name',
                'machine_payload' => ['proposed_value' => 'Backend Name'],
                'local_payload' => ['label' => 'Local Name'],
            ]),
        ]);

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            new InMemoryOutboxDrain()
        );

        $response = $controller->list_conflicts(new WP_REST_Request('GET', '/acx/v1/recognition/conflicts'));
        $data = $response->get_data();

        $this->assertSame(['accept_backend', 'dismissed'], $data['items'][0]['allowed_resolutions']);
    }

    public function testListConflictsReturnsAcceptedAndDismissedForAssignOutlierWhenMachineClusterIsKnown(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 16,
                'tenant_id' => $tenantId,
                'entity_type' => 'member',
                'entity_key' => 'identity-7',
                'outbox_id' => 92,
                'machine_payload' => ['cluster_uuid' => 'cluster-machine'],
            ]),
        ]);

        $outboxDrain = new InMemoryOutboxDrain([
            $this->buildOutboxOperation([
                'id' => 92,
                'tenant_id' => $tenantId,
                'operation_type' => 'assign_outlier_to_cluster',
                'entity_type' => 'member',
                'entity_key' => 'identity-7',
                'payload' => ['identity_id' => 'identity-7'],
            ]),
        ]);

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            $outboxDrain
        );

        $response = $controller->list_conflicts(new WP_REST_Request('GET', '/acx/v1/recognition/conflicts'));
        $data = $response->get_data();

        $this->assertSame(['accepted', 'dismissed'], $data['items'][0]['allowed_resolutions']);
    }

    public function testListConflictsReturnsDismissOnlyForAssignOutlierWhenMachineClusterIsMissing(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 17,
                'tenant_id' => $tenantId,
                'entity_type' => 'member',
                'entity_key' => 'identity-8',
                'outbox_id' => 93,
                'machine_payload' => [],
            ]),
        ]);

        $outboxDrain = new InMemoryOutboxDrain([
            $this->buildOutboxOperation([
                'id' => 93,
                'tenant_id' => $tenantId,
                'operation_type' => 'assign_outlier_to_cluster',
                'entity_type' => 'member',
                'entity_key' => 'identity-8',
                'payload' => ['identity_id' => 'identity-8'],
            ]),
        ]);

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            $outboxDrain
        );

        $response = $controller->list_conflicts(new WP_REST_Request('GET', '/acx/v1/recognition/conflicts'));
        $data = $response->get_data();

        $this->assertSame(['dismissed'], $data['items'][0]['allowed_resolutions']);
    }

    public function testListConflictsReturnsEmptyAllowedResolutionsWhenOutboxOperationIsMissing(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 21,
                'tenant_id' => $tenantId,
                'entity_key' => 'cluster-orphan',
                'outbox_id' => 404,
                'conflict_code' => 'version_conflict',
                'machine_payload' => ['label' => 'Remote'],
                'local_payload' => ['label' => 'Local'],
                'created_at' => '2026-03-11 09:00:00',
            ]),
        ]);

        $outboxDrain = new InMemoryOutboxDrain();

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            $outboxDrain
        );

        $response = $controller->list_conflicts(new WP_REST_Request('GET', '/acx/v1/recognition/conflicts'));
        $data = $response->get_data();

        $this->assertSame([], $data['items'][0]['allowed_resolutions']);
    }

    public function testGetConflictDetailReturns404WhenMissing(): void
    {
        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            new OutboxDrain()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/conflicts/99');
        $request->set_param('id', 99);
        $response = $controller->get_conflict_detail($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('conflict_not_found', $response->get_error_code());
    }

    public function testGetConflictDetailReturnsDecodedPayloadsWithAllowedResolutions(): void
    {
        $repository = new class() extends ConflictRepository {
            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-123',
                    'outbox_id' => 55,
                    'expected_base_version' => 7,
                    'backend_version' => 8,
                    'local_revision' => 2,
                    'conflict_code' => 'version_conflict',
                    'backend_proposed_value' => 'Remote label',
                    'machine_payload' => ['label' => 'Remote label'],
                    'local_payload' => ['label' => 'Local label'],
                    'resolution_status' => 'open',
                    'resolved_at' => null,
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }
        };

        $outboxDrain = new class() extends OutboxDrain {
            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'cluster_person_bound',
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-123',
                    'status' => 'conflict',
                    'attempts' => 1,
                    'payload' => ['person_id' => 12],
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }
        };

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            $outboxDrain
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/conflicts/55');
        $request->set_param('id', 55);
        $response = $controller->get_conflict_detail($request);
        $data = $response->get_data();

        $this->assertSame(200, $response->get_status());
        $this->assertSame(55, $data['conflict']['id']);
        $this->assertSame(55, $data['conflict']['outbox_id']);
        $this->assertSame(['label' => 'Remote label'], $data['conflict']['machine_payload']);
        $this->assertSame('Remote label', $data['conflict']['backend_proposed_value']);
        $this->assertSame(['label' => 'Local label'], $data['conflict']['local_payload']);
        $this->assertSame(['accepted', 'dismissed'], $data['conflict']['allowed_resolutions']);
    }

    public function testGetConflictDetailEnforcesTenantIsolation(): void
    {
        $expectedTenant = self::currentTenantId();

        $repository = new class($expectedTenant) extends ConflictRepository {
            public function __construct(private string $expectedTenant) {}

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                if ($tenant_id !== $this->expectedTenant) {
                    return [
                        'id' => $conflict_id,
                        'tenant_id' => 'other-tenant',
                    ];
                }

                return null;
            }
        };

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            new OutboxDrain()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/conflicts/99');
        $request->set_param('id', 99);
        $response = $controller->get_conflict_detail($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('conflict_not_found', $response->get_error_code());
    }

    public function testListFailedOutboxOperationsReturnsPaginatedEnvelope(): void
    {
        $outboxDrain = new class() extends OutboxDrain {
            public function find_failed_operations(string $tenant_id, int $limit = 50, int $offset = 0): array
            {
                return [[
                    'id' => 11,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'cluster_label_updated',
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-1',
                    'status' => 'failed',
                    'attempts' => 5,
                    'expected_base_version' => 11,
                    'local_revision' => 4,
                    'last_error_code' => 'dispatch_failed',
                    'last_error_message' => 'Remote curation replay failed.',
                    'payload' => ['cluster_uuid' => 'cluster-1', 'label' => 'Renamed'],
                    'created_at' => '2026-03-11 10:00:00',
                    'last_attempted_at' => '2026-03-11 10:05:00',
                    'acknowledged_at' => null,
                ],];
            }

            public function count_failed_operations(string $tenant_id): int
            {
                return 3;
            }
        };

        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            $outboxDrain
        );

        $response = $controller->list_failed_outbox_operations(
            new WP_REST_Request('GET', '/acx/v1/recognition/outbox/failed')
        );
        $data = $response->get_data();

        $this->assertSame(3, $data['total']);
        $this->assertSame(50, $data['limit']);
        $this->assertSame(0, $data['offset']);
        $this->assertCount(1, $data['items']);
        $this->assertSame(11, $data['items'][0]['id']);
        $this->assertSame('cluster_label_updated', $data['items'][0]['operation_type']);
        $this->assertSame('cluster', $data['items'][0]['entity_type']);
        $this->assertSame('cluster-1', $data['items'][0]['entity_key']);
        $this->assertSame('failed', $data['items'][0]['status']);
        $this->assertSame(5, $data['items'][0]['attempts']);
        $this->assertSame(11, $data['items'][0]['expected_base_version']);
        $this->assertSame(4, $data['items'][0]['local_revision']);
        $this->assertSame('dispatch_failed', $data['items'][0]['last_error_code']);
        $this->assertSame('Remote curation replay failed.', $data['items'][0]['last_error_message']);
        $this->assertSame(['cluster_uuid' => 'cluster-1', 'label' => 'Renamed'], $data['items'][0]['payload']);
        $this->assertSame('2026-03-11 10:05:00', $data['items'][0]['last_attempted_at']);
        $this->assertNull($data['items'][0]['acknowledged_at']);
    }

    public function testListOutboxOperationsReturnsTimelineAcrossStatuses(): void
    {
        $tenantId = self::currentTenantId();
        $outboxDrain = new \AltContext\Tests\Stubs\InMemoryOutboxDrain([
            $this->buildOutboxOperation([
                'id' => 19,
                'tenant_id' => $tenantId,
                'status' => 'acknowledged',
                'acknowledged_at' => '2026-03-11 10:06:00',
            ]),
            $this->buildOutboxOperation([
                'id' => 18,
                'tenant_id' => $tenantId,
                'status' => 'discarded',
            ]),
        ]);

        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            $outboxDrain
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/outbox');
        $request->set_param('limit', 10);
        $request->set_param('offset', 0);
        $response = $controller->list_outbox_operations($request);
        $data = $response->get_data();

        $this->assertSame(2, $data['total']);
        $this->assertCount(2, $data['items']);
        $this->assertSame(['acknowledged', 'discarded'], array_column($data['items'], 'status'));
        $this->assertSame('2026-03-11 10:06:00', $data['items'][0]['acknowledged_at']);
    }

    public function testResolveConflictReturns404WhenConflictIsMissing(): void
    {
        $controller = new ConflictController();

        $resolveRequest = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/1/resolve');
        $resolveRequest->set_param('id', 1);
        $resolveRequest->set_param('resolution_status', 'accepted');

        $response = $controller->resolve_conflict($resolveRequest);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('conflict_not_found', $response->get_error_code());
    }

    public function testResolveConflictEnforcesTenantIsolation(): void
    {
        $expectedTenant = self::currentTenantId();

        $repository = new class($expectedTenant) extends ConflictRepository {
            public function __construct(private string $expectedTenant) {}

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                if ($tenant_id !== $this->expectedTenant) {
                    return [
                        'id' => $conflict_id,
                        'tenant_id' => 'other-tenant',
                    ];
                }

                return null;
            }
        };

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            new OutboxDrain()
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/77/resolve');
        $request->set_param('id', 77);
        $request->set_param('resolution_status', 'accepted');

        $response = $controller->resolve_conflict($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('conflict_not_found', $response->get_error_code());
    }

    public function testResolveConflictReturns422WhenResolutionIsNotAllowed(): void
    {
        $repository = new class() extends ConflictRepository {
            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'person',
                    'entity_key' => 'person-1',
                    'outbox_id' => 17,
                    'expected_base_version' => 2,
                    'backend_version' => 3,
                    'local_revision' => 1,
                    'conflict_code' => 'version_conflict',
                    'machine_payload' => ['name' => 'Remote'],
                    'local_payload' => ['name' => 'Local'],
                    'resolution_status' => 'open',
                    'resolved_at' => null,
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }
        };

        $outboxDrain = new class() extends OutboxDrain {
            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'person_updated',
                    'entity_type' => 'person',
                    'entity_key' => 'person-1',
                    'status' => 'conflict',
                    'attempts' => 1,
                    'expected_base_version' => 2,
                    'local_revision' => 1,
                    'payload' => ['name' => 'Local'],
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }
        };

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(),
            $outboxDrain
        );

        $resolveRequest = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/17/resolve');
        $resolveRequest->set_param('id', 17);
        $resolveRequest->set_param('resolution_status', 'accepted');

        $response = $controller->resolve_conflict($resolveRequest);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('resolution_not_allowed', $response->get_error_code());
        $this->assertSame(422, $response->get_error_data()['status']);
    }

    public function testResolveConflictReturns409WhenAlreadyResolved(): void
    {
        $repository = new class() extends ConflictRepository {
            private int $calls = 0;

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                ++$this->calls;

                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-1',
                    'outbox_id' => 0,
                    'expected_base_version' => 0,
                    'backend_version' => 1,
                    'local_revision' => 1,
                    'conflict_code' => 'curated_member_deleted',
                    'machine_payload' => ['identity_uuid' => 'member-1'],
                    'local_payload' => ['identity_uuid' => 'member-1'],
                    'resolution_status' => $this->calls > 1 ? 'accepted' : 'open',
                    'resolved_at' => $this->calls > 1 ? '2026-03-11 10:01:00' : null,
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }
        };

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService($repository, new OutboxDrain(), new \AltContext\Tests\Stubs\NullClustersRepository(), new \AltContext\Tests\Stubs\NullIdentityMembersRepository()),
            new OutboxDrain()
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/1/resolve');
        $request->set_param('id', 1);
        $request->set_param('resolution_status', 'accepted');

        $response = $controller->resolve_conflict($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('conflict_already_resolved', $response->get_error_code());
        $this->assertSame(409, $response->get_error_data()['status']);
    }

    public function testResolveConflictPassesMergedValueToServiceForMergeResolution(): void
    {
        $repository = new class() extends ConflictRepository {
            public bool $resolved = false;

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-person',
                    'outbox_id' => 55,
                    'expected_base_version' => 0,
                    'backend_version' => 12,
                    'local_revision' => 1,
                    'conflict_code' => 'person_name_conflict',
                    'backend_proposed_value' => 'Backend Name',
                    'machine_payload' => ['proposed_value' => 'Backend Name'],
                    'local_payload' => ['label' => 'Local Name'],
                    'resolution_status' => $this->resolved ? 'merge' : 'open',
                    'resolved_at' => $this->resolved ? '2026-03-11 10:05:00' : null,
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->resolved = true;
                return true;
            }
        };

        $outboxDrain = new class() extends OutboxDrain {
            public array $reenqueued = [];

            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'cluster_label_updated',
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-person',
                    'status' => 'conflict',
                    'attempts' => 1,
                    'expected_base_version' => 0,
                    'local_revision' => 1,
                    'payload' => ['label' => 'Local Name'],
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }

            public function re_enqueue_with_current_base(int $outbox_id, int $backend_version, string $tenant_id, ?string $merged_value = null): bool
            {
                $this->reenqueued[] = [$outbox_id, $backend_version, $tenant_id, $merged_value];
                return true;
            }
        };

        $clustersRepository = new class() extends \AltContext\Tests\Stubs\NullClustersRepository {
            public array $updatedLabels = [];

            public function update_label(string $cluster_uuid, string $label, bool $mark_user_confirmed = true): int
            {
                $this->updatedLabels[] = [$cluster_uuid, $label];
                return 1;
            }
        };

        $service = new ConflictResolutionService(
            $repository,
            $outboxDrain,
            $clustersRepository,
            new \AltContext\Tests\Stubs\NullIdentityMembersRepository()
        );

        $controller = new ConflictController(
            $repository,
            $service,
            $outboxDrain
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/42/resolve');
        $request->set_param('id', 42);
        $request->set_param('resolution_status', 'merge');
        $request->set_param('merged_value', 'Merged Name');

        $response = $controller->resolve_conflict($request);

        $this->assertSame(200, $response->get_status());
        $this->assertSame([[55, 12, self::currentTenantId(), 'Merged Name']], $outboxDrain->reenqueued);
        $this->assertSame([['cluster-person', 'Merged Name']], $clustersRepository->updatedLabels);
    }

    public function testResolveConflictRejectsReservedMergedValueWith400(): void
    {
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-person',
                    'outbox_id' => 56,
                    'expected_base_version' => 0,
                    'backend_version' => 12,
                    'local_revision' => 1,
                    'conflict_code' => 'person_name_conflict',
                    'backend_proposed_value' => 'Backend Name',
                    'machine_payload' => ['proposed_value' => 'Backend Name'],
                    'local_payload' => ['label' => 'Local Name'],
                    'resolution_status' => 'open',
                    'resolved_at' => null,
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };

        $outboxDrain = new class() extends OutboxDrain {
            public array $reenqueued = [];

            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'cluster_label_updated',
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-person',
                    'status' => 'conflict',
                    'attempts' => 1,
                    'expected_base_version' => 0,
                    'local_revision' => 1,
                    'payload' => ['label' => 'Local Name'],
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }

            public function re_enqueue_with_current_base(int $outbox_id, int $backend_version, string $tenant_id, ?string $merged_value = null): bool
            {
                $this->reenqueued[] = [$outbox_id, $backend_version, $tenant_id, $merged_value];
                return true;
            }
        };

        $clustersRepository = new class() extends \AltContext\Tests\Stubs\NullClustersRepository {
            public array $updatedLabels = [];

            public function update_label(string $cluster_uuid, string $label, bool $mark_user_confirmed = true): int
            {
                $this->updatedLabels[] = [$cluster_uuid, $label];
                return 1;
            }
        };

        $controller = new ConflictController(
            $repository,
            new ConflictResolutionService(
                $repository,
                $outboxDrain,
                $clustersRepository,
                new \AltContext\Tests\Stubs\NullIdentityMembersRepository()
            ),
            $outboxDrain
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/43/resolve');
        $request->set_param('id', 43);
        $request->set_param('resolution_status', 'merge');
        $request->set_param('merged_value', 'cluster-9');

        $response = $controller->resolve_conflict($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('reserved_label', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status']);
        $this->assertSame([], $clustersRepository->updatedLabels);
        $this->assertSame([], $outboxDrain->reenqueued);
        $this->assertSame([], $repository->marked);
    }

    public function testResolveConflictReturns500OnMutationFailure(): void
    {
        $repository = new class() extends ConflictRepository {
            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-1',
                    'outbox_id' => 0,
                    'expected_base_version' => 0,
                    'backend_version' => 1,
                    'local_revision' => 1,
                    'conflict_code' => 'curated_cluster_deleted',
                    'machine_payload' => ['status' => 'missing_from_snapshot'],
                    'local_payload' => ['label' => 'Curated'],
                    'resolution_status' => 'open',
                    'resolved_at' => null,
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                return true;
            }
        };

        $clustersRepository = new class() extends \AltContext\Tests\Stubs\NullClustersRepository {
            public function delete_cluster_with_members(string $cluster_uuid, string $tenant_id): int
            {
                return 0;
            }
        };

        $resolutionService = new ConflictResolutionService(
            $repository,
            new OutboxDrain(),
            $clustersRepository,
            new \AltContext\Tests\Stubs\NullIdentityMembersRepository()
        );

        $controller = new ConflictController(
            $repository,
            $resolutionService,
            new OutboxDrain()
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/1/resolve');
        $request->set_param('id', 1);
        $request->set_param('resolution_status', 'accepted');

        $response = $controller->resolve_conflict($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('conflict_resolution_failed', $response->get_error_code());
        $this->assertSame(500, $response->get_error_data()['status']);
    }

    public function testResolveConflictReturnsResolvedConflictAndRefreshesMetrics(): void
    {
        $repository = new class() extends ConflictRepository {
            public bool $resolved = false;

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'member',
                    'entity_key' => 'member-1',
                    'outbox_id' => 0,
                    'expected_base_version' => 0,
                    'backend_version' => 4,
                    'local_revision' => 2,
                    'conflict_code' => 'curated_member_deleted',
                    'machine_payload' => ['identity_uuid' => 'member-1'],
                    'local_payload' => ['identity_uuid' => 'member-1'],
                    'resolution_status' => $this->resolved ? 'accepted' : 'open',
                    'resolved_at' => $this->resolved ? '2026-03-11 10:05:00' : null,
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->resolved = true;
                return true;
            }
        };

        $clustersRepository = new class() extends \AltContext\Tests\Stubs\NullClustersRepository {};

        $membersRepository = new class() extends \AltContext\Tests\Stubs\NullIdentityMembersRepository {
            public array $deletedMembers = [];

            public function delete_member(string $identity_uuid, string $tenant_id): int
            {
                $this->deletedMembers[] = [$identity_uuid, $tenant_id];
                return 1;
            }
        };

        $resolutionService = new ConflictResolutionService(
            $repository,
            new OutboxDrain(),
            $clustersRepository,
            $membersRepository
        );

        $syncStateRepository = new class() extends NullSyncStateRepository {
            public array $refreshed = [];

            public function refresh_curation_metrics(string $tenant_id): void
            {
                $this->refreshed[] = $tenant_id;
            }
        };

        $GLOBALS['wpdb']->reset();

        $controller = new ConflictController(
            $repository,
            $resolutionService,
            new OutboxDrain(),
            $syncStateRepository
        );

        $resolveRequest = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/22/resolve');
        $resolveRequest->set_param('id', 22);
        $resolveRequest->set_param('resolution_status', 'accepted');

        $response = $controller->resolve_conflict($resolveRequest);
        $data = $response->get_data();

        $this->assertSame(200, $response->get_status());
        $this->assertSame([[ 'member-1', self::currentTenantId() ]], $membersRepository->deletedMembers);
        $this->assertSame([self::currentTenantId()], $syncStateRepository->refreshed);
        $this->assertSame('accepted', $data['conflict']['resolution_status']);
        $this->assertContains('START TRANSACTION', $GLOBALS['wpdb']->queries);
        $this->assertContains('COMMIT', $GLOBALS['wpdb']->queries);
    }

    public function testResolveConflictDoesNotRefreshMetricsTwiceWhenServiceAlreadyDid(): void
    {
        $repository = new class() extends ConflictRepository {
            public bool $resolved = false;

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-1',
                    'outbox_id' => 41,
                    'expected_base_version' => 0,
                    'backend_version' => 4,
                    'local_revision' => 2,
                    'conflict_code' => 'version_conflict',
                    'machine_payload' => ['label' => 'Remote'],
                    'local_payload' => ['label' => 'Local'],
                    'resolution_status' => $this->resolved ? 'accepted' : 'open',
                    'resolved_at' => $this->resolved ? '2026-03-11 10:05:00' : null,
                    'created_at' => '2026-03-11 10:00:00',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->resolved = true;
                return true;
            }
        };

        $outboxDrain = new class() extends OutboxDrain {
            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'cluster_label_updated',
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-1',
                    'status' => 'conflict',
                ];
            }

            public function discard_operation(int $outbox_id, string $tenant_id): bool
            {
                return true;
            }
        };

        $clustersRepository = new class() extends \AltContext\Tests\Stubs\NullClustersRepository {
            public function reset_curation(string $cluster_uuid, string $tenant_id): int
            {
                return 1;
            }
        };

        $resolutionService = new ConflictResolutionService(
            $repository,
            $outboxDrain,
            $clustersRepository,
            new \AltContext\Tests\Stubs\NullIdentityMembersRepository()
        );

        $syncStateRepository = new class() extends NullSyncStateRepository {
            public int $refreshCalls = 0;

            public function refresh_curation_metrics(string $tenant_id): void
            {
                ++$this->refreshCalls;
            }
        };

        $controller = new ConflictController(
            $repository,
            $resolutionService,
            $outboxDrain,
            $syncStateRepository
        );

        $resolveRequest = new WP_REST_Request('POST', '/acx/v1/recognition/conflicts/41/resolve');
        $resolveRequest->set_param('id', 41);
        $resolveRequest->set_param('resolution_status', 'accepted');

        $response = $controller->resolve_conflict($resolveRequest);

        $this->assertSame(200, $response->get_status());
        $this->assertSame(0, $syncStateRepository->refreshCalls);
    }

    public function testRetryFailedOperationReturnsUpdatedOperation(): void
    {
        $tenantId = self::currentTenantId();
        $outboxDrain = new InMemoryOutboxDrain([
            $this->buildOutboxOperation([
                'id' => 1,
                'tenant_id' => $tenantId,
                'status' => 'failed',
                'attempts' => 5,
                'expected_base_version' => 11,
                'local_revision' => 4,
                'last_error_code' => 'dispatch_failed',
                'last_error_message' => 'Remote curation replay failed.',
                'payload' => ['cluster_uuid' => 'cluster-1'],
                'last_attempted_at' => '2026-03-11 10:05:00',
            ]),
        ]);
        $syncStateRepository = new TrackingSyncStateRepository();

        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            $outboxDrain,
            $syncStateRepository
        );

        $retryRequest = new WP_REST_Request('POST', '/acx/v1/recognition/outbox/1/retry');
        $retryRequest->set_param('id', 1);
        $response = $controller->retry_failed_operation($retryRequest);
        $data = $response->get_data();

        $this->assertSame(200, $response->get_status());
        $this->assertSame('pending', $data['operation']['status']);
        $this->assertSame(0, $data['operation']['attempts']);
        $this->assertNull($data['operation']['last_error_code']);
        $this->assertNull($data['operation']['last_error_message']);
        $this->assertTrue($outboxDrain->retryScheduled);
        $this->assertSame(1, $syncStateRepository->refreshCount);
        $this->assertSame($tenantId, $syncStateRepository->lastTenantId);
    }

    public function testRetryFailedOperationReturns404WhenMissing(): void
    {
        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            new OutboxDrain()
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/outbox/99/retry');
        $request->set_param('id', 99);
        $response = $controller->retry_failed_operation($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('outbox_operation_not_found', $response->get_error_code());
        $this->assertSame(404, $response->get_error_data()['status']);
    }

    public function testRetryFailedOperationReturns409ForNonFailedRow(): void
    {
        $outboxDrain = new class() extends OutboxDrain {
            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'status' => 'conflict',
                ];
            }
        };

        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            $outboxDrain
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/outbox/7/retry');
        $request->set_param('id', 7);
        $response = $controller->retry_failed_operation($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('outbox_operation_not_failed', $response->get_error_code());
        $this->assertSame(409, $response->get_error_data()['status']);
    }

    public function testDiscardOperationReturnsUpdatedOperation(): void
    {
        $tenantId = self::currentTenantId();
        $outboxDrain = new InMemoryOutboxDrain([
            $this->buildOutboxOperation([
                'id' => 8,
                'tenant_id' => $tenantId,
                'status' => 'failed',
                'attempts' => 5,
                'expected_base_version' => 11,
                'local_revision' => 4,
                'last_error_code' => 'dispatch_failed',
                'last_error_message' => 'Remote curation replay failed.',
                'payload' => ['cluster_uuid' => 'cluster-1'],
                'last_attempted_at' => '2026-03-11 10:05:00',
            ]),
        ]);
        $syncStateRepository = new TrackingSyncStateRepository();

        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            $outboxDrain,
            $syncStateRepository
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/outbox/8/discard');
        $request->set_param('id', 8);
        $response = $controller->discard_operation($request);
        $data = $response->get_data();

        $this->assertSame(200, $response->get_status());
        $this->assertSame('discarded', $data['operation']['status']);
        $this->assertSame('dispatch_failed', $data['operation']['last_error_code']);
        $this->assertSame(1, $syncStateRepository->refreshCount);
        $this->assertSame($tenantId, $syncStateRepository->lastTenantId);
    }

    public function testDiscardOperationReturns404WhenMissing(): void
    {
        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            new OutboxDrain()
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/outbox/99/discard');
        $request->set_param('id', 99);
        $response = $controller->discard_operation($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('outbox_operation_not_found', $response->get_error_code());
        $this->assertSame(404, $response->get_error_data()['status']);
    }

    public function testDiscardOperationReturns409ForNonFailedRow(): void
    {
        $outboxDrain = new class() extends OutboxDrain {
            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'status' => 'conflict',
                ];
            }
        };

        $controller = new ConflictController(
            new ConflictRepository(),
            new ConflictResolutionService(),
            $outboxDrain
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/outbox/7/discard');
        $request->set_param('id', 7);
        $response = $controller->discard_operation($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('outbox_operation_not_failed', $response->get_error_code());
        $this->assertSame(409, $response->get_error_data()['status']);
    }

    /**
     * @param array<string,mixed> $overrides
     * @return array<string,mixed>
     */
    public function testBackendRosterRegressionExposesRestoreLocalAndAcceptBackend(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 61,
                'entity_type' => 'roster',
                'entity_key' => 'backend_roster',
                'outbox_id' => 0,
                'conflict_code' => 'backend_roster_regressed',
                'machine_payload' => [
                    'backend_version' => 41,
                    'counts' => ['curated_cluster_deleted' => 25, 'curated_member_deleted' => 2, 'member_cluster_reassignment' => 1],
                    'entities' => ['curated_cluster_deleted' => ['cluster-a'], 'curated_member_deleted' => [], 'member_cluster_reassignment' => []],
                    'entity_set_truncated' => false,
                ],
            ]),
        ]);

        $controller = new ConflictController($repository, new ConflictResolutionService(), new InMemoryOutboxDrain());
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/conflicts/61');
        $request->set_param('id', 61);
        $response = $controller->get_conflict_detail($request);
        $data = $response->get_data();

        $this->assertSame(
            ['restore_local', 'accept_backend', 'dismissed'],
            $data['conflict']['allowed_resolutions'],
            'a non-truncated aggregate must offer both resolution directions'
        );
    }

    public function testTruncatedBackendRosterRegressionFailsRestoreLocalClosed(): void
    {
        $tenantId = self::currentTenantId();
        $repository = new InMemoryConflictRepository([
            $this->buildConflictRecord([
                'id' => 62,
                'entity_type' => 'roster',
                'entity_key' => 'backend_roster',
                'outbox_id' => 0,
                'conflict_code' => 'backend_roster_regressed',
                'machine_payload' => [
                    'backend_version' => 41,
                    'entities' => ['curated_cluster_deleted' => ['cluster-a']],
                    'entity_set_truncated' => true,
                ],
            ]),
        ]);

        $controller = new ConflictController($repository, new ConflictResolutionService(), new InMemoryOutboxDrain());
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/conflicts/62');
        $request->set_param('id', 62);
        $response = $controller->get_conflict_detail($request);
        $data = $response->get_data();

        $this->assertSame(
            ['accept_backend', 'dismissed'],
            $data['conflict']['allowed_resolutions'],
            'a truncated aggregate must not offer restore_local'
        );
    }

    private function buildConflictRecord(array $overrides = []): array
    {
        return array_merge([
            'id' => 1,
            'tenant_id' => self::currentTenantId(),
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-1',
            'outbox_id' => 0,
            'expected_base_version' => 4,
            'backend_version' => 5,
            'local_revision' => 2,
            'conflict_code' => 'version_conflict',
            'backend_proposed_value' => 'Remote label',
            'machine_payload' => ['label' => 'Remote'],
            'local_payload' => ['label' => 'Local'],
            'resolution_status' => 'open',
            'resolved_at' => null,
            'created_at' => '2026-03-11 10:00:00',
        ], $overrides);
    }

    /**
     * @param array<string,mixed> $overrides
     * @return array<string,mixed>
     */
    private function buildOutboxOperation(array $overrides = []): array
    {
        return array_merge([
            'id' => 1,
            'tenant_id' => self::currentTenantId(),
            'operation_type' => 'cluster_label_updated',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-1',
            'status' => 'conflict',
            'attempts' => 1,
            'expected_base_version' => 4,
            'local_revision' => 2,
            'last_error_code' => null,
            'last_error_message' => null,
            'payload' => ['label' => 'Local'],
            'created_at' => '2026-03-11 10:00:00',
            'last_attempted_at' => null,
            'acknowledged_at' => null,
        ], $overrides);
    }
}
