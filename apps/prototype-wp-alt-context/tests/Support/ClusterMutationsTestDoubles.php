<?php

declare(strict_types=1);

namespace AltContext\Tests\Support;

use AltContext\Sovereign\Sync\OutboxWriterInterface;
use AltContext\Sovereign\Sync\TopologyCommandRepositoryInterface;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;

class ClusterMutationsRepositorySpy extends NullClustersRepository
{
    public string $dismissedClusterId = '';
    public string $undismissedClusterId = '';
    public string $updatedLabelClusterId = '';
    public string $updatedLabel = '';
    public string $lastRepresentativeClusterId = '';
    public ?string $lastRepresentativeId = null;
    public bool $lastRepresentativePinned = false;
    public string $createdLocalClusterId = '';
    public int $nextDismissRows = 1;
    public int $nextUndismissRows = 1;
    public int $nextUpdateLabelRows = 1;
    public int $nextCreateLocalClusterRows = 1;
    /** @var array<int,array{0:string,1:int}> */
    public array $identityCountUpdates = [];
    /** @var array<int,array{0:string,1:int}> */
    public array $identityCountAdjustments = [];
    /** @var array<string,array<string,mixed>> */
    public array $localClusterRows = [
        'cluster-xyz' => [
            'cluster_uuid' => 'cluster-xyz',
            'snapshot_version' => 17,
            'local_revision' => 4,
            'curation_state' => 'uncurated',
        ],
        'cluster-source' => [
            'cluster_uuid' => 'cluster-source',
            'snapshot_version' => 17,
            'local_revision' => 4,
            'curation_state' => 'uncurated',
        ],
        'cluster-target' => [
            'cluster_uuid' => 'cluster-target',
            'snapshot_version' => 18,
            'local_revision' => 2,
            'curation_state' => 'uncurated',
        ],
    ];

    public function dismiss(string $cluster_uuid): int
    {
        $this->dismissedClusterId = $cluster_uuid;
        return $this->nextDismissRows;
    }

    public function undismiss(string $cluster_uuid): int
    {
        $this->undismissedClusterId = $cluster_uuid;
        return $this->nextUndismissRows;
    }

    public function update_identity_count(string $cluster_uuid, int $identity_count): int
    {
        $this->identityCountUpdates[] = [$cluster_uuid, $identity_count];
        return 1;
    }

    public function adjust_identity_count(string $cluster_uuid, int $delta): int
    {
        $this->identityCountAdjustments[] = [$cluster_uuid, $delta];
        return 1;
    }

    public function update_representative_state(string $cluster_uuid, ?string $representative_id, bool $is_pinned, bool $is_local_curation = true): int
    {
        $this->lastRepresentativeClusterId = $cluster_uuid;
        $this->lastRepresentativeId = $representative_id;
        $this->lastRepresentativePinned = $is_pinned;
        if (isset($this->localClusterRows[$cluster_uuid])) {
            $this->localClusterRows[$cluster_uuid]['representative_id'] = $representative_id;
            $this->localClusterRows[$cluster_uuid]['is_pinned'] = $is_pinned ? 1 : 0;
        }
        return 1;
    }

    public function find_by_uuid(string $cluster_uuid): ?array
    {
        return $this->localClusterRows[$cluster_uuid] ?? null;
    }

    public function has_projection_rows_for_tenant(string $tenant_id): bool
    {
        return ! empty($this->localClusterRows);
    }

    public function update_label(string $cluster_uuid, string $label, bool $mark_user_confirmed = true): int
    {
        $this->updatedLabelClusterId = $cluster_uuid;
        $this->updatedLabel = $label;
        return $this->nextUpdateLabelRows;
    }

    public function create_local_cluster(string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1): int|\WP_Error
    {
        $this->createdLocalClusterId = $cluster_uuid;
        if ($this->nextCreateLocalClusterRows <= 0) {
            return $this->nextCreateLocalClusterRows;
        }
        $this->localClusterRows[$cluster_uuid] = [
            'cluster_uuid' => $cluster_uuid,
            'tenant_id' => $tenant_id,
            'label' => $label,
            'snapshot_version' => 0,
            'local_revision' => 1,
            'curation_state' => 'uncurated',
            'identity_count' => $identity_count,
        ];
        return $this->nextCreateLocalClusterRows;
    }
}

class ClusterMutationsSyncStateSpy extends NullSyncStateRepository
{
    public string $lastTouchedTenantId = '';
    public bool $refreshCurationMetricsCalled = false;

    public function get_snapshot_version(string $tenant_id): int
    {
        return 99;
    }

    public function touch_local_curation_marker(string $tenant_id): void
    {
        $this->lastTouchedTenantId = $tenant_id;
    }

    public function refresh_curation_metrics(string $tenant_id): void
    {
        $this->refreshCurationMetricsCalled = true;
    }
}

class ClusterMutationsTopologyCommandSpy implements TopologyCommandRepositoryInterface
{
    public string $lastCommandType = '';
    public string $lastEntityKey = '';
    public int $lastExpectedBaseVersion = 0;
    public string $lastIdempotencyKey = '';
    /** @var array<string,mixed> */
    public array $lastPayload = [];
    public int|false $nextEnqueueResult = 77;

    public function enqueue(
        string $tenant_id,
        string $command_type,
        string $entity_key,
        int $expected_base_version,
        array $payload,
        ?string $idempotency_key = null
    ): int|false {
        $this->lastCommandType = $command_type;
        $this->lastEntityKey = $entity_key;
        $this->lastExpectedBaseVersion = $expected_base_version;
        $this->lastPayload = $payload;
        $this->lastIdempotencyKey = (string) $idempotency_key;

        return $this->nextEnqueueResult;
    }

    public function find_pending(?string $tenant_id = null, int $limit = 25): array
    {
        return array();
    }

    public function find_reconcilable(?string $tenant_id = null, int $limit = 25): array
    {
        return array();
    }

    public function claim_command(int $command_id, string $expected_status): bool
    {
        return true;
    }

    public function update_status(
        int $command_id,
        string $status,
        ?array $result_payload = null,
        ?string $backend_command_id = null,
        ?string $expected_status = null
    ): bool {
        return true;
    }

    public function record_dispatch_result(int $command_id, array $response, ?string $expected_status = null): bool
    {
        return true;
    }

    public function mark_reconciled(int $command_id, ?array $result_payload = null, ?string $expected_status = null): bool
    {
        return true;
    }

    public function record_failure(int $command_id, string $status, string $error_code, string $error_message, bool $increment_attempt = true, ?string $expected_status = null): bool
    {
        return true;
    }

    public function record_reconcile_failure(int $command_id, string $status, string $error_code, string $error_message, ?string $expected_status = null): bool
    {
        return true;
    }
}

class ClusterMutationsMembersSpy extends NullIdentityMembersRepository
{
    public string $lastCuratedIdentityId = '';
    public string $lastReassignedIdentityId = '';
    public string $lastTargetClusterId = '';
    public string $lastReassignedSourceClusterId = '';
    public string $lastReassignedTargetClusterId = '';
    public int $nextMarkRows = 1;
    public int $nextReassignRows = 1;
    /** @var array<string,int> */
    public array $clusterCounts = [
        'cluster-source' => 3,
        'cluster-target' => 2,
        'cluster-xyz' => 1,
    ];
    /** @var array<string,array<string,mixed>> */
    public array $membersByIdentity = [
        'identity-77' => [
            'identity_uuid' => 'identity-77',
            'cluster_uuid' => 'cluster-target',
        ],
        'identity-88' => [
            'identity_uuid' => 'identity-88',
            'cluster_uuid' => 'cluster-target',
        ],
        'identity-outlier' => [
            'identity_uuid' => 'identity-outlier',
            'cluster_uuid' => 'cluster-source',
        ],
    ];

    public function mark_as_curated(string $identity_uuid): int
    {
        $this->lastCuratedIdentityId = $identity_uuid;
        return $this->nextMarkRows;
    }

    public function reassign_to_cluster(string $identity_uuid, string $target_cluster_uuid): int
    {
        $this->lastReassignedIdentityId = $identity_uuid;
        $this->lastTargetClusterId = $target_cluster_uuid;
        if (isset($this->membersByIdentity[$identity_uuid])) {
            $this->membersByIdentity[$identity_uuid]['cluster_uuid'] = $target_cluster_uuid;
        }
        return $this->nextReassignRows;
    }

    public function reassign_cluster_members(string $source_cluster_uuid, string $target_cluster_uuid): int
    {
        $this->lastReassignedSourceClusterId = $source_cluster_uuid;
        $this->lastReassignedTargetClusterId = $target_cluster_uuid;
        return $this->clusterCounts[$source_cluster_uuid] ?? 0;
    }

    public function count_for_cluster(string $cluster_uuid, ?string $tenant_id = null): int
    {
        return $this->clusterCounts[$cluster_uuid] ?? 0;
    }

    public function find_by_identity_uuid(string $identity_uuid): ?array
    {
        return $this->membersByIdentity[$identity_uuid] ?? null;
    }
}

class ClusterMutationsOutboxWriterSpy implements OutboxWriterInterface
{
    public int|false $nextEnqueueResult = 55;
    public string $lastOperationType = '';

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
        $this->lastOperationType = $operation_type;

        return $this->nextEnqueueResult;
    }
}
