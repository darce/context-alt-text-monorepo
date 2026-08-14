<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Sync\ConflictResolutionService;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Sync\ConflictResolutionService
 */
class ConflictResolutionServiceTest extends TestCase
{
    public function testResolveOutboxAcceptanceClearsCurationAndDiscardsOperation(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-1',
                    'outbox_id' => 12,
                    'backend_version' => 7,
                    'resolution_status' => 'open',
                    'conflict_code' => 'version_conflict',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };

        $outboxDrain = new class() extends OutboxDrain {
            public array $discarded = [];

            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'cluster_label_updated',
                ];
            }

            public function discard_operation(int $outbox_id, string $tenant_id): bool
            {
                $this->discarded[] = [$outbox_id, $tenant_id];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $reset = [];

            public function reset_curation(string $cluster_uuid, string $tenant_id): int
            {
                $this->reset[] = [$cluster_uuid, $tenant_id];
                return 1;
            }
        };

        $service = new ConflictResolutionService($repository, $outboxDrain, $clustersRepository, new NullIdentityMembersRepository());
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(12, 'accepted', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => true], $result);
    }

    /**
     * E21-14-BR-11: ProjectionQueryException during resolve must not escape;
     * return entity_mutation_failed after rollback (rg-007).
     */
    public function testResolveReturnsEntityMutationFailedOnProjectionQueryException(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-1',
                    'outbox_id' => null,
                    'backend_version' => 7,
                    'resolution_status' => 'open',
                    'conflict_code' => 'curated_cluster_deleted',
                ];
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public function delete_cluster_with_members(string $cluster_uuid, string $tenant_id): int
            {
                throw new ProjectionQueryException(
                    'Projection query failed [clusters.find_by_uuid]: boom'
                );
            }
        };

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $clustersRepository, new NullIdentityMembersRepository());
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(12, 'accepted', $tenantId);

        $this->assertSame(
            ['ok' => false, 'reason' => 'entity_mutation_failed', 'metrics_refreshed' => false],
            $result
        );
        $this->assertContains('ROLLBACK', $GLOBALS['wpdb']->queries);
    }

    public function testResolveOutboxDismissedReenqueuesWithUpdatedBaseVersion(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-1',
                    'outbox_id' => 21,
                    'backend_version' => 14,
                    'resolution_status' => 'open',
                    'conflict_code' => 'version_conflict',
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

            public function re_enqueue_with_current_base(int $outbox_id, int $backend_version, string $tenant_id, ?string $merged_value = null): bool
            {
                $this->reenqueued[] = [$outbox_id, $backend_version, $tenant_id];
                return true;
            }
        };

        $service = new ConflictResolutionService($repository, $outboxDrain, new NullClustersRepository(), new NullIdentityMembersRepository());
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(21, 'dismissed', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => true], $result);
        $this->assertSame([[21, 14, $tenantId]], $outboxDrain->reenqueued);
        $this->assertSame([[21, 'dismissed', $tenantId]], $repository->marked);
    }

    public function testResolveProjectionClusterDeletionDeletesClusterAndMembers(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-gone',
                    'outbox_id' => 0,
                    'resolution_status' => 'open',
                    'conflict_code' => 'curated_cluster_deleted',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $deleted = [];

            public function delete_cluster_with_members(string $cluster_uuid, string $tenant_id): int
            {
                $this->deleted[] = [$cluster_uuid, $tenant_id];
                return 1;
            }
        };

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $clustersRepository, new NullIdentityMembersRepository());

        $result = $service->resolve(31, 'accepted', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => false], $result);
        $this->assertSame([['cluster-gone', $tenantId]], $clustersRepository->deleted);
    }

    public function testResolveRollsBackWhenProjectionMutationFails(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-gone',
                    'outbox_id' => 0,
                    'resolution_status' => 'open',
                    'conflict_code' => 'curated_cluster_deleted',
                ];
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public function delete_cluster_with_members(string $cluster_uuid, string $tenant_id): int
            {
                return 0;
            }
        };

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $clustersRepository, new NullIdentityMembersRepository());
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(32, 'accepted', $tenantId);

        $this->assertSame(['ok' => false, 'reason' => 'entity_mutation_failed', 'metrics_refreshed' => false], $result);
        $this->assertContains('START TRANSACTION', $GLOBALS['wpdb']->queries);
        $this->assertContains('ROLLBACK', $GLOBALS['wpdb']->queries);
        $this->assertNotContains('COMMIT', $GLOBALS['wpdb']->queries);
    }

    public function testResolveProjectionMemberReassignmentUpdatesAssignmentAndClearsCuration(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'member',
                    'entity_key' => 'member-9',
                    'outbox_id' => 0,
                    'resolution_status' => 'open',
                    'conflict_code' => 'member_cluster_reassignment',
                    'machine_payload' => ['cluster_uuid' => 'cluster-99'],
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                return true;
            }
        };

        $membersRepository = new class() extends NullIdentityMembersRepository {
            public array $acceptedAssignments = [];

            public function accept_machine_cluster_assignment(string $identity_uuid, string $cluster_uuid, string $tenant_id): int
            {
                $this->acceptedAssignments[] = [$identity_uuid, $cluster_uuid, $tenant_id];
                return 1;
            }
        };

        $service = new ConflictResolutionService($repository, new OutboxDrain(), new NullClustersRepository(), $membersRepository);

        $result = $service->resolve(41, 'accepted', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => false], $result);
        $this->assertSame([['member-9', 'cluster-99', $tenantId]], $membersRepository->acceptedAssignments);
    }

    public function testResolveProjectionDismissedPreservesLocalState(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-keep',
                    'outbox_id' => 0,
                    'resolution_status' => 'open',
                    'conflict_code' => 'curated_cluster_deleted',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public int $deleteCalls = 0;

            public function delete_cluster_with_members(string $cluster_uuid, string $tenant_id): int
            {
                ++$this->deleteCalls;
                return 1;
            }
        };

        $membersRepository = new class() extends NullIdentityMembersRepository {
            public int $deleteCalls = 0;

            public function delete_member(string $identity_uuid, string $tenant_id): int
            {
                ++$this->deleteCalls;
                return 1;
            }
        };

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $clustersRepository, $membersRepository);

        $result = $service->resolve(51, 'dismissed', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => false], $result);
        $this->assertSame(0, $clustersRepository->deleteCalls);
        $this->assertSame(0, $membersRepository->deleteCalls);
        $this->assertSame([[51, 'dismissed', $tenantId]], $repository->marked);
    }

    public function testResolveReturnsAlreadyResolvedForInvalidStatusTransition(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-1',
                    'outbox_id' => 0,
                    'resolution_status' => 'accepted',
                    'conflict_code' => 'curated_cluster_deleted',
                ];
            }
        };

        $GLOBALS['wpdb']->reset();
        $service = new ConflictResolutionService($repository, new OutboxDrain(), new NullClustersRepository(), new NullIdentityMembersRepository());

        $result = $service->resolve(61, 'accepted', $tenantId);

        $this->assertSame(['ok' => false, 'reason' => 'already_resolved', 'metrics_refreshed' => false], $result);
        $this->assertNotContains('START TRANSACTION', $GLOBALS['wpdb']->queries);
    }

    public function testResolveRevertMergeAcceptanceMovesMembersBackAndDeletesLocalSourceCluster(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-target',
                    'outbox_id' => 77,
                    'backend_version' => 12,
                    'resolution_status' => 'open',
                    'conflict_code' => 'version_conflict',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };

        $outboxDrain = new class() extends OutboxDrain {
            public array $discarded = [];

            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'revert_merge_cluster',
                    'payload' => [
                        'target_cluster_id' => 'cluster-target',
                        'desired_source_cluster_id' => 'cluster-restored',
                        'moved_identity_ids' => ['identity-1', 'identity-2'],
                    ],
                ];
            }

            public function discard_operation(int $outbox_id, string $tenant_id): bool
            {
                $this->discarded[] = [$outbox_id, $tenant_id];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $updatedCounts = [];
            public array $deletedClusters = [];

            public function update_identity_count(string $cluster_uuid, int $identity_count): int
            {
                $this->updatedCounts[] = [$cluster_uuid, $identity_count];
                return 1;
            }

            public function delete_cluster_with_members(string $cluster_uuid, string $tenant_id): int
            {
                $this->deletedClusters[] = [$cluster_uuid, $tenant_id];
                return 1;
            }
        };

        $membersRepository = new class() extends NullIdentityMembersRepository {
            public array $acceptedAssignments = [];

            public function accept_machine_cluster_assignment(string $identity_uuid, string $cluster_uuid, string $tenant_id): int
            {
                $this->acceptedAssignments[] = [$identity_uuid, $cluster_uuid, $tenant_id];
                return 1;
            }

            public function count_for_cluster(string $cluster_uuid, ?string $tenant_id = null): int
            {
                return 'cluster-restored' === $cluster_uuid ? 0 : 8;
            }
        };

        $service = new ConflictResolutionService($repository, $outboxDrain, $clustersRepository, $membersRepository);
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(77, 'accepted', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => true], $result);
        $this->assertSame(
            [
                ['identity-1', 'cluster-target', $tenantId],
                ['identity-2', 'cluster-target', $tenantId],
            ],
            $membersRepository->acceptedAssignments
        );
        $this->assertSame([['cluster-target', 8]], $clustersRepository->updatedCounts);
        $this->assertSame([['cluster-restored', $tenantId]], $clustersRepository->deletedClusters);
        $this->assertSame([[77, $tenantId]], $outboxDrain->discarded);
        $this->assertSame([[77, 'accepted', $tenantId]], $repository->marked);
    }

    public function testResolveAssignOutlierAcceptanceRestoresMachineClusterAssignment(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'member',
                    'entity_key' => 'identity-7',
                    'outbox_id' => 87,
                    'backend_version' => 12,
                    'resolution_status' => 'open',
                    'conflict_code' => 'version_conflict',
                    'machine_payload' => ['cluster_uuid' => 'cluster-machine'],
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };

        $outboxDrain = new class() extends OutboxDrain {
            public array $discarded = [];

            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'assign_outlier_to_cluster',
                    'payload' => [
                        'identity_id' => 'identity-7',
                    ],
                ];
            }

            public function discard_operation(int $outbox_id, string $tenant_id): bool
            {
                $this->discarded[] = [$outbox_id, $tenant_id];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $updatedCounts = [];

            public function update_identity_count(string $cluster_uuid, int $identity_count): int
            {
                $this->updatedCounts[] = [$cluster_uuid, $identity_count];
                return 1;
            }
        };

        $membersRepository = new class() extends NullIdentityMembersRepository {
            public array $acceptedAssignments = [];

            public function find_by_identity_uuid(string $identity_uuid): ?array
            {
                return ['identity_uuid' => $identity_uuid, 'cluster_uuid' => 'cluster-local-target'];
            }

            public function accept_machine_cluster_assignment(string $identity_uuid, string $cluster_uuid, string $tenant_id): int
            {
                $this->acceptedAssignments[] = [$identity_uuid, $cluster_uuid, $tenant_id];
                return 1;
            }

            public function count_for_cluster(string $cluster_uuid, ?string $tenant_id = null): int
            {
                return 'cluster-machine' === $cluster_uuid ? 5 : 2;
            }
        };

        $service = new ConflictResolutionService($repository, $outboxDrain, $clustersRepository, $membersRepository);

        $result = $service->resolve(87, 'accepted', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => true], $result);
        $this->assertSame([['identity-7', 'cluster-machine', $tenantId]], $membersRepository->acceptedAssignments);
        $this->assertSame(
            [
                ['cluster-machine', 5],
                ['cluster-local-target', 2],
            ],
            $clustersRepository->updatedCounts
        );
        $this->assertSame([[87, $tenantId]], $outboxDrain->discarded);
        $this->assertSame([[87, 'accepted', $tenantId]], $repository->marked);
    }

    public function testResolveCreateClusterForIdentityAcceptanceRestoresMachineClusterAndDeletesLocalCluster(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-created-local',
                    'outbox_id' => 88,
                    'backend_version' => 12,
                    'resolution_status' => 'open',
                    'conflict_code' => 'version_conflict',
                    'machine_payload' => ['cluster_uuid' => 'cluster-machine'],
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };

        $outboxDrain = new class() extends OutboxDrain {
            public array $discarded = [];

            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return [
                    'id' => $outbox_id,
                    'tenant_id' => $tenant_id,
                    'operation_type' => 'cluster_created_for_identity',
                    'payload' => [
                        'identity_id' => 'identity-8',
                        'desired_cluster_id' => 'cluster-created-local',
                    ],
                ];
            }

            public function discard_operation(int $outbox_id, string $tenant_id): bool
            {
                $this->discarded[] = [$outbox_id, $tenant_id];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $updatedCounts = [];
            public array $deletedClusters = [];

            public function update_identity_count(string $cluster_uuid, int $identity_count): int
            {
                $this->updatedCounts[] = [$cluster_uuid, $identity_count];
                return 1;
            }

            public function delete_cluster_with_members(string $cluster_uuid, string $tenant_id): int
            {
                $this->deletedClusters[] = [$cluster_uuid, $tenant_id];
                return 1;
            }
        };

        $membersRepository = new class() extends NullIdentityMembersRepository {
            public array $acceptedAssignments = [];

            public function find_by_identity_uuid(string $identity_uuid): ?array
            {
                return ['identity_uuid' => $identity_uuid, 'cluster_uuid' => 'cluster-created-local'];
            }

            public function accept_machine_cluster_assignment(string $identity_uuid, string $cluster_uuid, string $tenant_id): int
            {
                $this->acceptedAssignments[] = [$identity_uuid, $cluster_uuid, $tenant_id];
                return 1;
            }

            public function count_for_cluster(string $cluster_uuid, ?string $tenant_id = null): int
            {
                return 'cluster-created-local' === $cluster_uuid ? 0 : 6;
            }
        };

        $service = new ConflictResolutionService($repository, $outboxDrain, $clustersRepository, $membersRepository);

        $result = $service->resolve(88, 'accepted', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => true], $result);
        $this->assertSame([['identity-8', 'cluster-machine', $tenantId]], $membersRepository->acceptedAssignments);
        $this->assertSame([['cluster-machine', 6]], $clustersRepository->updatedCounts);
        $this->assertSame([['cluster-created-local', $tenantId]], $clustersRepository->deletedClusters);
        $this->assertSame([[88, $tenantId]], $outboxDrain->discarded);
        $this->assertSame([[88, 'accepted', $tenantId]], $repository->marked);
    }

    public function testResolvePersonNameConflictAcceptBackendUpdatesClusterLabel(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-person',
                    'outbox_id' => 0,
                    'backend_version' => 19,
                    'resolution_status' => 'open',
                    'conflict_code' => 'person_name_conflict',
                    'backend_proposed_value' => 'Backend Name',
                    'machine_payload' => ['proposed_value' => 'Backend Name'],
                    'local_payload' => ['label' => 'Local Name'],
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $updatedLabels = [];

            public function update_label(string $cluster_uuid, string $label, bool $mark_user_confirmed = true): int
            {
                $this->updatedLabels[] = [$cluster_uuid, $label, $mark_user_confirmed];
                return 1;
            }
        };

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $clustersRepository, new NullIdentityMembersRepository());
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(91, 'accept_backend', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => false], $result);
        $this->assertSame([['cluster-person', 'Backend Name', false]], $clustersRepository->updatedLabels);
        $this->assertSame([[91, 'accept_backend', $tenantId]], $repository->marked);
    }

    public function testResolveReservedBackendPersonNameSkipsLabelWriteAndCompletes(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-person',
                    'outbox_id' => 0,
                    'backend_version' => 19,
                    'resolution_status' => 'open',
                    'conflict_code' => 'person_name_conflict',
                    'backend_proposed_value' => 'cluster-abcdef01',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $updatedLabels = [];

            public function update_label(string $cluster_uuid, string $label, bool $mark_user_confirmed = true): int
            {
                $this->updatedLabels[] = [$cluster_uuid, $label, $mark_user_confirmed];
                return 1;
            }
        };

        $GLOBALS['__ac_error_log'] = [];
        $service = new ConflictResolutionService($repository, new OutboxDrain(), $clustersRepository, new NullIdentityMembersRepository());
        $result = $service->resolve(94, 'accept_backend', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => false], $result);
        $this->assertSame([], $clustersRepository->updatedLabels);
        $this->assertSame([[94, 'accept_backend', $tenantId]], $repository->marked);
        $this->assertStringContainsString('reserved label', implode("\n", $GLOBALS['__ac_error_log']));
        unset($GLOBALS['__ac_error_log']);
    }

    public function testResolvePersonNameConflictMergeUpdatesLabelAndReenqueuesMergedValue(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-person',
                    'outbox_id' => 92,
                    'backend_version' => 19,
                    'resolution_status' => 'open',
                    'conflict_code' => 'person_name_conflict',
                    'backend_proposed_value' => 'Backend Name',
                    'machine_payload' => ['proposed_value' => 'Backend Name'],
                    'local_payload' => ['label' => 'Local Name'],
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
                    'status' => 'conflict',
                    'payload' => ['label' => 'Local Name'],
                ];
            }

            public function re_enqueue_with_current_base(int $outbox_id, int $backend_version, string $tenant_id, ?string $merged_value = null): bool
            {
                $this->reenqueued[] = [$outbox_id, $backend_version, $tenant_id, $merged_value];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $updatedLabels = [];

            public function update_label(string $cluster_uuid, string $label, bool $mark_user_confirmed = true): int
            {
                $this->updatedLabels[] = [$cluster_uuid, $label, $mark_user_confirmed];
                return 1;
            }
        };

        $service = new ConflictResolutionService($repository, $outboxDrain, $clustersRepository, new NullIdentityMembersRepository());
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(92, 'merge', $tenantId, 'Merged Name');

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => true], $result);
        $this->assertSame([['cluster-person', 'Merged Name', true]], $clustersRepository->updatedLabels);
        $this->assertSame([[92, 19, $tenantId, 'Merged Name']], $outboxDrain->reenqueued);
        $this->assertSame([[92, 'merge', $tenantId]], $repository->marked);
    }

    public function testResolveMergeReservedMergedValueRejectsWithoutMutating(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-person',
                    'outbox_id' => 95,
                    'backend_version' => 19,
                    'resolution_status' => 'open',
                    'conflict_code' => 'person_name_conflict',
                    'backend_proposed_value' => 'Backend Name',
                    'machine_payload' => ['proposed_value' => 'Backend Name'],
                    'local_payload' => ['label' => 'Local Name'],
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
                    'status' => 'conflict',
                    'payload' => ['label' => 'Local Name'],
                ];
            }

            public function re_enqueue_with_current_base(int $outbox_id, int $backend_version, string $tenant_id, ?string $merged_value = null): bool
            {
                $this->reenqueued[] = [$outbox_id, $backend_version, $tenant_id, $merged_value];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $updatedLabels = [];

            public function update_label(string $cluster_uuid, string $label, bool $mark_user_confirmed = true): int
            {
                $this->updatedLabels[] = [$cluster_uuid, $label, $mark_user_confirmed];
                return 1;
            }
        };

        $service = new ConflictResolutionService($repository, $outboxDrain, $clustersRepository, new NullIdentityMembersRepository());
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(95, 'merge', $tenantId, 'cluster-9');

        $this->assertFalse($result['ok']);
        $this->assertSame('reserved_label', $result['reason']);
        $this->assertSame([], $clustersRepository->updatedLabels);
        $this->assertSame([], $outboxDrain->reenqueued);
        $this->assertSame([], $repository->marked);
    }

    public function testResolveDriftConflictAcceptBackendClearsCuratedState(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = new class() extends ConflictRepository {
            public array $marked = [];

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return [
                    'id' => $conflict_id,
                    'tenant_id' => $tenant_id,
                    'entity_type' => 'cluster',
                    'entity_key' => 'cluster-drift',
                    'outbox_id' => 0,
                    'backend_version' => 27,
                    'resolution_status' => 'open',
                    'conflict_code' => 'drift_conflict',
                ];
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };

        $clustersRepository = new class() extends NullClustersRepository {
            public array $reset = [];

            public function reset_curation(string $cluster_uuid, string $tenant_id): int
            {
                $this->reset[] = [$cluster_uuid, $tenant_id];
                return 1;
            }
        };

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $clustersRepository, new NullIdentityMembersRepository());

        $result = $service->resolve(93, 'accept_backend', $tenantId);

        $this->assertSame(['ok' => true, 'reason' => 'success', 'metrics_refreshed' => false], $result);
        $this->assertSame([['cluster-drift', $tenantId]], $clustersRepository->reset);
        $this->assertSame([[93, 'accept_backend', $tenantId]], $repository->marked);
    }

    /**
     * @return array<string,mixed>
     */
    private function buildRosterRegressionConflict(string $tenantId, array $machineOverrides = [], array $overrides = []): array
    {
        return array_merge(
            [
                'id' => 61,
                'tenant_id' => $tenantId,
                'entity_type' => 'roster',
                'entity_key' => 'backend_roster',
                'outbox_id' => 0,
                'backend_version' => 41,
                'resolution_status' => 'open',
                'conflict_code' => 'backend_roster_regressed',
                'machine_payload' => array_merge(
                    [
                        'backend_version' => 41,
                        'counts' => [
                            'curated_cluster_deleted' => 1,
                            'curated_member_deleted' => 1,
                            'member_cluster_reassignment' => 1,
                        ],
                        'entities' => [
                            'curated_cluster_deleted' => ['cluster-a'],
                            'curated_member_deleted' => ['identity-del'],
                            'member_cluster_reassignment' => ['identity-moved'],
                        ],
                        'entity_set_truncated' => false,
                        'reassignment_targets' => ['identity-moved' => 'cluster-remote'],
                    ],
                    $machineOverrides
                ),
                'local_payload' => ['curated_clusters' => 1, 'curated_members' => 2],
            ],
            $overrides
        );
    }

    private function buildRosterConflictRepository(array $conflict): ConflictRepository
    {
        return new class($conflict) extends ConflictRepository {
            public array $marked = [];

            public function __construct(private array $conflict)
            {
                parent::__construct();
            }

            public function find_conflict_by_id(int $conflict_id, string $tenant_id): ?array
            {
                return array_merge($this->conflict, ['id' => $conflict_id, 'tenant_id' => $tenant_id]);
            }

            public function mark_resolved(int $conflict_id, string $resolution_status, string $tenant_id): bool
            {
                $this->marked[] = [$conflict_id, $resolution_status, $tenant_id];
                return true;
            }
        };
    }

    private function buildCuratedClustersRepository(): NullClustersRepository
    {
        return new class() extends NullClustersRepository {
            public array $deleted = [];

            public function get_curated_clusters_for_tenant(string $tenant_id): array
            {
                return [
                    'cluster-a' => [
                        'cluster_uuid' => 'cluster-a',
                        'label' => 'Alice',
                        'snapshot_version' => 40,
                        'local_revision' => 3,
                    ],
                ];
            }

            public function delete_cluster_with_members(string $cluster_uuid, string $tenant_id): int
            {
                $this->deleted[] = [$cluster_uuid, $tenant_id];
                return 1;
            }
        };
    }

    private function buildCuratedMembersRepository(): NullIdentityMembersRepository
    {
        return new class() extends NullIdentityMembersRepository {
            public array $deleted = [];
            public array $accepted = [];

            public function get_curated_members_for_tenant(string $tenant_id): array
            {
                return [
                    'identity-del' => ['identity_uuid' => 'identity-del', 'cluster_uuid' => 'cluster-keep'],
                    'identity-moved' => ['identity_uuid' => 'identity-moved', 'cluster_uuid' => 'cluster-local'],
                ];
            }

            public function delete_member(string $identity_uuid, string $tenant_id): int
            {
                $this->deleted[] = [$identity_uuid, $tenant_id];
                return 1;
            }

            public function accept_machine_cluster_assignment(string $identity_uuid, string $cluster_uuid, string $tenant_id): int
            {
                $this->accepted[] = [$identity_uuid, $cluster_uuid, $tenant_id];
                return 1;
            }
        };
    }

    public function testRestoreLocalSynthesizesRePushOutboxOpsAndPreservesLocalState(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = $this->buildRosterConflictRepository($this->buildRosterRegressionConflict($tenantId));
        $clustersRepository = $this->buildCuratedClustersRepository();
        $membersRepository = $this->buildCuratedMembersRepository();
        $writer = new RecordingOutboxWriterSpy();

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $clustersRepository, $membersRepository, $writer);
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(61, 'restore_local', $tenantId);

        $this->assertTrue($result['ok']);
        $this->assertSame('success', $result['reason']);
        $this->assertSame(
            ['enqueued' => 3, 'skipped' => 0, 'skipped_keys' => []],
            $result['restore_report']
        );

        $this->assertCount(3, $writer->enqueued);

        [$clusterOp, $deletedMemberOp, $movedMemberOp] = $writer->enqueued;
        $this->assertSame('cluster_label_updated', $clusterOp['operation_type']);
        $this->assertSame('cluster', $clusterOp['entity_type']);
        $this->assertSame('cluster-a', $clusterOp['entity_key']);
        $this->assertSame(41, $clusterOp['expected_base_version']);
        $this->assertSame(4, $clusterOp['local_revision']);
        $this->assertSame(['cluster_uuid' => 'cluster-a', 'label' => 'Alice'], $clusterOp['payload']);

        $this->assertSame('identity_reassigned', $deletedMemberOp['operation_type']);
        $this->assertSame('member', $deletedMemberOp['entity_type']);
        $this->assertSame('identity-del', $deletedMemberOp['entity_key']);
        $this->assertSame('cluster-keep', $deletedMemberOp['payload']['target_cluster_id']);

        $this->assertSame('identity_reassigned', $movedMemberOp['operation_type']);
        $this->assertSame('identity-moved', $movedMemberOp['entity_key']);
        $this->assertSame('cluster-local', $movedMemberOp['payload']['target_cluster_id'], 'restore_local must re-assert the LOCAL curated assignment');

        foreach ($writer->enqueued as $operation) {
            $this->assertSame(
                \AltContext\Sovereign\Sync\CurationIdempotencyKey::derive(
                    $operation['tenant_id'],
                    $operation['operation_type'],
                    $operation['entity_type'],
                    $operation['entity_key'],
                    $operation['local_revision'],
                    $operation['payload']
                ),
                $operation['idempotency_key'],
                'synthesized ops must use the shared idempotency-key derivation'
            );
        }

        $this->assertSame([], $clustersRepository->deleted, 'restore_local must not touch local curated state');
        $this->assertSame([], $membersRepository->deleted);
        $this->assertSame([], $membersRepository->accepted);
        $this->assertSame([[61, 'restore_local', $tenantId]], $repository->marked);
    }

    public function testRestoreLocalSkipsAndReportsEntitiesWithoutSurvivingLocalState(): void
    {
        $tenantId = md5((string) \get_site_url());
        $conflict = $this->buildRosterRegressionConflict(
            $tenantId,
            [
                'entities' => [
                    'curated_cluster_deleted' => ['cluster-a', 'cluster-vanished'],
                    'curated_member_deleted' => [],
                    'member_cluster_reassignment' => [],
                ],
            ]
        );
        $repository = $this->buildRosterConflictRepository($conflict);
        $writer = new RecordingOutboxWriterSpy();

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $this->buildCuratedClustersRepository(), $this->buildCuratedMembersRepository(), $writer);
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(61, 'restore_local', $tenantId);

        $this->assertTrue($result['ok'], 'a partially-restorable set must not fail the whole resolution');
        $this->assertSame(
            ['enqueued' => 1, 'skipped' => 1, 'skipped_keys' => ['cluster-vanished']],
            $result['restore_report']
        );
        $this->assertCount(1, $writer->enqueued);
    }

    public function testRestoreLocalOnAlreadyResolvedAggregateEnqueuesNothing(): void
    {
        $tenantId = md5((string) \get_site_url());
        $conflict = $this->buildRosterRegressionConflict($tenantId, [], ['resolution_status' => 'restore_local']);
        $repository = $this->buildRosterConflictRepository($conflict);
        $writer = new RecordingOutboxWriterSpy();

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $this->buildCuratedClustersRepository(), $this->buildCuratedMembersRepository(), $writer);
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(61, 'restore_local', $tenantId);

        $this->assertFalse($result['ok']);
        $this->assertSame('already_resolved', $result['reason']);
        $this->assertSame([], $writer->enqueued);
        $this->assertSame([], $repository->marked);
    }

    public function testRestoreLocalOnNonAggregateConflictIsNotAllowed(): void
    {
        $tenantId = md5((string) \get_site_url());
        $conflict = $this->buildRosterRegressionConflict($tenantId, [], [
            'conflict_code' => 'person_name_conflict',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-person',
        ]);
        $repository = $this->buildRosterConflictRepository($conflict);
        $writer = new RecordingOutboxWriterSpy();

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $this->buildCuratedClustersRepository(), $this->buildCuratedMembersRepository(), $writer);
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(61, 'restore_local', $tenantId);

        $this->assertFalse($result['ok']);
        $this->assertSame('resolution_not_allowed', $result['reason']);
        $this->assertSame([], $writer->enqueued, 'guarded restore_local must not touch any rows');
        $this->assertSame([], $repository->marked);
    }

    public function testRestoreLocalOnTruncatedAggregateFailsClosed(): void
    {
        $tenantId = md5((string) \get_site_url());
        $conflict = $this->buildRosterRegressionConflict($tenantId, ['entity_set_truncated' => true]);
        $repository = $this->buildRosterConflictRepository($conflict);
        $writer = new RecordingOutboxWriterSpy();

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $this->buildCuratedClustersRepository(), $this->buildCuratedMembersRepository(), $writer);
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(61, 'restore_local', $tenantId);

        $this->assertFalse($result['ok']);
        $this->assertSame('resolution_not_allowed', $result['reason']);
        $this->assertSame([], $writer->enqueued);
        $this->assertSame([], $repository->marked);
    }

    public function testAcceptBackendOnRosterRegressionAppliesPerEntityMutationsAndClearsConflict(): void
    {
        $tenantId = md5((string) \get_site_url());
        $repository = $this->buildRosterConflictRepository($this->buildRosterRegressionConflict($tenantId));
        $clustersRepository = $this->buildCuratedClustersRepository();
        $membersRepository = $this->buildCuratedMembersRepository();
        $writer = new RecordingOutboxWriterSpy();

        $service = new ConflictResolutionService($repository, new OutboxDrain(), $clustersRepository, $membersRepository, $writer);
        $GLOBALS['wpdb']->reset();

        $result = $service->resolve(61, 'accept_backend', $tenantId);

        $this->assertTrue($result['ok'], 'accept_backend must clear the aggregate, not fall through to entity_mutation_failed');
        $this->assertSame('success', $result['reason']);
        $this->assertSame([['cluster-a', $tenantId]], $clustersRepository->deleted);
        $this->assertSame([['identity-del', $tenantId]], $membersRepository->deleted);
        $this->assertSame([['identity-moved', 'cluster-remote', $tenantId]], $membersRepository->accepted);
        $this->assertSame([], $writer->enqueued);
        $this->assertSame([[61, 'accept_backend', $tenantId]], $repository->marked);
    }
}

class RecordingOutboxWriterSpy implements \AltContext\Sovereign\Sync\OutboxWriterInterface
{
    /** @var array<int,array<string,mixed>> */
    public array $enqueued = [];

    public function enqueue(
        string $tenant_id,
        string $operation_type,
        string $entity_type,
        string $entity_key,
        int $expected_base_version,
        int $local_revision,
        array $payload,
        ?string $idempotency_key = null
    ): int|false {
        $this->enqueued[] = [
            'tenant_id' => $tenant_id,
            'operation_type' => $operation_type,
            'entity_type' => $entity_type,
            'entity_key' => $entity_key,
            'expected_base_version' => $expected_base_version,
            'local_revision' => $local_revision,
            'payload' => $payload,
            'idempotency_key' => $idempotency_key,
        ];

        return count($this->enqueued);
    }
}
