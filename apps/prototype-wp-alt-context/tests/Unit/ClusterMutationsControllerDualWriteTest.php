<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Sovereign\Sync\TopologyCommandRepositoryInterface;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\ClusterMutationsController
 */
class ClusterMutationsControllerDualWriteTest extends TestCase
{
    private ClusterMutationsController $controller;
    private ClusterMutationsRepositorySpy $repository;
    private ClusterMutationsMembersSpy $membersRepository;
    private ClusterMutationsSyncStateSpy $syncStateRepository;
    private ClusterMutationsTopologyCommandSpy $topologyCommandRepository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClusterMutationsRepositorySpy();
        $this->membersRepository = new ClusterMutationsMembersSpy();
        $this->syncStateRepository = new ClusterMutationsSyncStateSpy();
        $this->topologyCommandRepository = new ClusterMutationsTopologyCommandSpy();
        $this->controller = new ClusterMutationsController($this->repository, $this->syncStateRepository, $this->membersRepository, null, $this->topologyCommandRepository);
    }

    public function testDismissQueuesReplayOperationInsideTransaction(): void
    {
        global $wpdb;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/dismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->dismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('cluster-xyz', $this->repository->dismissedClusterId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_dismissed'", $outboxInsert);
        $this->assertStringContainsString("'cluster-xyz'", $outboxInsert);
        $this->assertStringContainsString('cluster_uuid', $outboxInsert);
        $this->assertStringContainsString('expected_base_version', $outboxInsert);
        $this->assertStringContainsString('local_revision', $outboxInsert);

        $this->assertSame([], $this->getHttpCalls());
    }

    public function testUndismissQueuesReplayOperationInsideTransaction(): void
    {
        global $wpdb;

        $request = new \WP_REST_Request('DELETE', '/recognition/clusters/cluster-xyz/dismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->undismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('cluster-xyz', $this->repository->undismissedClusterId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_undismissed'", $outboxInsert);
        $this->assertStringContainsString("'cluster-xyz'", $outboxInsert);

        $this->assertSame([], $this->getHttpCalls());
    }

    public function testDismissRollbackWhenOutboxEnqueueFails(): void
    {
        global $wpdb;
        $wpdb->queryResults['COMMIT'] = false;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/dismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->dismiss_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
    }

    public function testDismissReturnsAcknowledgedWhenLocalStateAlreadyMatches(): void
    {
        $this->repository->nextDismissRows = 0;
        $this->repository->localClusterRows['cluster-xyz']['curation_state'] = 'dismissed';

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/dismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->dismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('acknowledged', $response->get_data()['status']);
    }

    public function testUndismissReturnsAcknowledgedWhenLocalStateAlreadyMatches(): void
    {
        $this->repository->nextUndismissRows = 0;
        $this->repository->localClusterRows['cluster-xyz']['curation_state'] = 'uncurated';

        $request = new \WP_REST_Request('DELETE', '/recognition/clusters/cluster-xyz/dismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->undismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('acknowledged', $response->get_data()['status']);
    }

    public function testReassignQueuesReplayOperationInsideTransaction(): void
    {
        $request = new \WP_REST_Request('POST', '/recognition/clusters/reassign', [
            'identity_id' => 'identity-77',
            'target_cluster_id' => 'cluster-target',
        ]);

        $response = $this->controller->reassign_cluster_identity($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('identity-77', $this->membersRepository->lastReassignedIdentityId);
        $this->assertSame('cluster-target', $this->membersRepository->lastTargetClusterId);
        $this->assertSame(md5((string) get_site_url()), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertContains('START TRANSACTION', $GLOBALS['wpdb']->queries);
        $this->assertContains('COMMIT', $GLOBALS['wpdb']->queries);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testReassignRollbackWhenOutboxEnqueueFails(): void
    {
        global $wpdb;
        $wpdb->queryResults['COMMIT'] = false;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/reassign', [
            'identity_id' => 'identity-77',
            'target_cluster_id' => 'cluster-target',
        ]);

        $response = $this->controller->reassign_cluster_identity($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
    }

    public function testReassignDoesNotTouchCurationMarkerWhenNoRowsAffected(): void
    {
        $this->membersRepository->nextReassignRows = 0;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/reassign', [
            'identity_id' => 'identity-77',
            'target_cluster_id' => 'cluster-target',
        ]);

        $response = $this->controller->reassign_cluster_identity($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame('identity-77', $this->membersRepository->lastReassignedIdentityId);
        $this->assertSame('', $this->syncStateRepository->lastTouchedTenantId);
    }

    public function testLabelUpdateQueuesReplayOperationInsideTransaction(): void
    {
        global $wpdb;

        $request = new \WP_REST_Request('PATCH', '/recognition/clusters/cluster-xyz', [
            'cluster_id' => 'cluster-xyz',
            'label' => 'Known Person',
        ]);

        $response = $this->controller->update_cluster_label($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('cluster-xyz', $this->repository->updatedLabelClusterId);
        $this->assertSame('Known Person', $this->repository->updatedLabel);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_label_updated'", $outboxInsert);
        $this->assertStringContainsString("'cluster-xyz'", $outboxInsert);
        $this->assertStringContainsString('Known Person', $outboxInsert);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testMergeQueuesReplayOperationInsideTransaction(): void
    {
        global $wpdb;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-source/merge', [
            'source_id' => 'cluster-source',
            'target_cluster_id' => 'cluster-target',
            'target_label' => 'Merged Cluster',
        ]);

        $response = $this->controller->merge_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('cluster-source', $this->membersRepository->lastReassignedSourceClusterId);
        $this->assertSame('cluster-target', $this->membersRepository->lastReassignedTargetClusterId);
        $this->assertSame([['cluster-source', 0], ['cluster-target', 5]], $this->repository->identityCountUpdates);
        $this->assertSame('cluster-source', $this->repository->dismissedClusterId);
        $this->assertSame('cluster-target', $this->repository->updatedLabelClusterId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_merged'", $outboxInsert);
        $this->assertStringContainsString("'cluster-source'", $outboxInsert);
        $this->assertStringContainsString('cluster-target', $outboxInsert);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testCreateClusterForIdentityQueuesReplayOperationInsideTransaction(): void
    {
        global $wpdb;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/create-for-identity', [
            'identity_id' => 'identity-77',
            'label' => 'Curated Name',
        ]);

        $response = $this->controller->create_cluster_for_identity($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame('identity-77', $data['identity_id']);
        $this->assertSame('Curated Name', $data['label']);
        $this->assertNotSame('', $this->repository->createdLocalClusterId);
        $this->assertSame($this->repository->createdLocalClusterId, $data['cluster_id']);
        $this->assertSame('identity-77', $this->membersRepository->lastReassignedIdentityId);
        $this->assertSame($this->repository->createdLocalClusterId, $this->membersRepository->lastTargetClusterId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_created_for_identity'", $outboxInsert);
        $this->assertStringContainsString('desired_cluster_id', $outboxInsert);
        $this->assertStringContainsString($this->repository->createdLocalClusterId, $outboxInsert);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testSplitQueuesTopologyCommandInsideTransaction(): void
    {
        global $wpdb;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-source/split', [
            'cluster_id' => 'cluster-source',
            'n_clusters' => 2,
            'split_mode' => 'manual',
        ]);

        $response = $this->controller->split_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame(77, $data['command_id']);
        $this->assertSame('pending', $data['status']);
        $this->assertSame('queued', $data['command_state']);
        $this->assertSame('awaiting_backend_partition', $data['projection_state']);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertSame('cluster_split', $this->topologyCommandRepository->lastCommandType);
        $this->assertSame('cluster-source', $this->topologyCommandRepository->lastEntityKey);
        $this->assertSame(17, $this->topologyCommandRepository->lastExpectedBaseVersion);
        $this->assertSame(2, $this->topologyCommandRepository->lastPayload['n_clusters']);
        $this->assertSame('manual', $this->topologyCommandRepository->lastPayload['split_mode']);
        $this->assertNotSame('', $this->topologyCommandRepository->lastIdempotencyKey);
        $this->assertSame($this->topologyCommandRepository->lastIdempotencyKey, $data['idempotency_key']);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testSplitClusterDerivesStableIdempotencyKeyWhenRequestOmitsOne(): void
    {
        $requestA = new \WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/split');
        $requestA->set_param('cluster_id', 'cluster-source');
        $requestA->set_param('n_clusters', 2);
        $requestA->set_param('split_mode', 'manual');

        $requestB = new \WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/split');
        $requestB->set_param('cluster_id', 'cluster-source');
        $requestB->set_param('n_clusters', 2);
        $requestB->set_param('split_mode', 'manual');

        $responseA = $this->controller->split_cluster($requestA);
        $firstKey = $this->topologyCommandRepository->lastIdempotencyKey;

        $responseB = $this->controller->split_cluster($requestB);
        $secondKey = $this->topologyCommandRepository->lastIdempotencyKey;

        $this->assertInstanceOf(\WP_REST_Response::class, $responseA);
        $this->assertInstanceOf(\WP_REST_Response::class, $responseB);
        $this->assertNotSame('', $firstKey);
        $this->assertSame($firstKey, $secondKey);
    }

    /**
     * @param array<int,string> $queries
     */
    private function findQueryContaining(array $queries, string $needle): string
    {
        foreach ($queries as $query) {
            if (str_contains($query, $needle)) {
                return $query;
            }
        }

        $this->fail(sprintf('Unable to find query containing "%s".', $needle));
    }
}

class ClusterMutationsRepositorySpy extends NullClustersRepository
{
    public string $dismissedClusterId = '';
    public string $undismissedClusterId = '';
    public string $updatedLabelClusterId = '';
    public string $updatedLabel = '';
    public string $createdLocalClusterId = '';
    public int $nextDismissRows = 1;
    public int $nextUndismissRows = 1;
    /** @var array<int,array{0:string,1:int}> */
    public array $identityCountUpdates = [];
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

    public function find_by_uuid(string $cluster_uuid): ?array
    {
        return $this->localClusterRows[$cluster_uuid] ?? null;
    }

    public function update_label(string $cluster_uuid, string $label): int
    {
        $this->updatedLabelClusterId = $cluster_uuid;
        $this->updatedLabel = $label;
        return 1;
    }

    public function create_local_cluster(string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1): int
    {
        $this->createdLocalClusterId = $cluster_uuid;
        $this->localClusterRows[$cluster_uuid] = [
            'cluster_uuid' => $cluster_uuid,
            'tenant_id' => $tenant_id,
            'label' => $label,
            'snapshot_version' => 0,
            'local_revision' => 1,
            'curation_state' => 'uncurated',
            'identity_count' => $identity_count,
        ];
        return 1;
    }
}

class ClusterMutationsSyncStateSpy extends NullSyncStateRepository
{
    public string $lastTouchedTenantId = '';

    public function get_snapshot_version(string $tenant_id): int
    {
        return 99;
    }

    public function touch_local_curation_marker(string $tenant_id): void
    {
        $this->lastTouchedTenantId = $tenant_id;
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

        return 77;
    }

    public function find_pending(?string $tenant_id = null, int $limit = 25): array
    {
        return array();
    }

    public function find_reconcilable(?string $tenant_id = null, int $limit = 25): array
    {
        return array();
    }

    public function update_status(
        int $command_id,
        string $status,
        ?array $result_payload = null,
        ?string $backend_command_id = null
    ): bool {
        return true;
    }

    public function record_dispatch_result(int $command_id, array $response): bool
    {
        return true;
    }

    public function mark_reconciled(int $command_id, ?array $result_payload = null): bool
    {
        return true;
    }

    public function record_failure(int $command_id, string $status, string $error_code, string $error_message, bool $increment_attempt = true): bool
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
            'cluster_uuid' => 'cluster-xyz',
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
        return $this->nextReassignRows;
    }

    public function reassign_cluster_members(string $source_cluster_uuid, string $target_cluster_uuid): int
    {
        $this->lastReassignedSourceClusterId = $source_cluster_uuid;
        $this->lastReassignedTargetClusterId = $target_cluster_uuid;
        return $this->clusterCounts[$source_cluster_uuid] ?? 0;
    }

    public function count_for_cluster(string $cluster_uuid): int
    {
        return $this->clusterCounts[$cluster_uuid] ?? 0;
    }

    public function find_by_identity_uuid(string $identity_uuid): ?array
    {
        return $this->membersByIdentity[$identity_uuid] ?? null;
    }
}
