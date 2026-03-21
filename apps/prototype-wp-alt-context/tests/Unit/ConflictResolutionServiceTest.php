<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

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
        $this->assertSame([['cluster-1', $tenantId]], $clustersRepository->reset);
        $this->assertSame([[12, $tenantId]], $outboxDrain->discarded);
        $this->assertSame([[12, 'accepted', $tenantId]], $repository->marked);
        $this->assertContains('START TRANSACTION', $GLOBALS['wpdb']->queries);
        $this->assertContains('COMMIT', $GLOBALS['wpdb']->queries);
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

            public function count_for_cluster(string $cluster_uuid): int
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

            public function count_for_cluster(string $cluster_uuid): int
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

            public function count_for_cluster(string $cluster_uuid): int
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
}
