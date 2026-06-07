<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterMergeService;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterMergeService
 */
class ClusterMergeServiceTest extends TestCase
{
    private ClusterMergeService $service;
    private ClusterMutationsRepositorySpy $repository;
    private ClusterMutationsMembersSpy $membersRepository;
    private ClusterMutationsSyncStateSpy $syncStateRepository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClusterMutationsRepositorySpy();
        $this->membersRepository = new ClusterMutationsMembersSpy();
        $this->syncStateRepository = new ClusterMutationsSyncStateSpy();
        $host = new ClusterMutationsController(
            $this->repository,
            $this->syncStateRepository,
            $this->membersRepository,
            null,
            new ClusterMutationsTopologyCommandSpy()
        );
        $this->service = new ClusterMergeService(
            $host,
            $this->repository,
            $this->membersRepository,
            $this->syncStateRepository
        );
    }

    public function testMergeClusterQueuesReplayAndTouchesCurationMarker(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Merged Cluster');

        $response = $this->service->merge_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('cluster-source', $this->repository->dismissedClusterId);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_merged'", $outboxInsert);
    }

    public function testRevertMergeClusterQueuesReplayInsideTransaction(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/revert-merge');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('moved_identity_ids', ['identity-77', 'identity-88']);
        $request->set_param('source_label', 'Restored Cluster');

        $response = $this->service->revert_merge_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertNotSame('', $this->repository->createdLocalClusterId);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'revert_merge_cluster'", $outboxInsert);
    }
}
