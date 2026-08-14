<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterMergeService;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsOutboxWriterSpy;
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
    use FindsSqlQueries;

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

    public function testMergeClusterRejectsReservedTargetLabelBeforeTransaction(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', ' cluster_7 ');

        $response = $this->service->merge_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('reserved_label', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status']);
        $this->assertSame('', $this->repository->updatedLabelClusterId);
        $this->assertNotContains('START TRANSACTION', $wpdb->queries);
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

    public function testMergeRollsBackWhenOutboxEnqueueFails(): void
    {
        global $wpdb;
        $service = $this->serviceWithFailingOutbox();

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Merged Cluster');

        $response = $service->merge_cluster($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    public function testRevertMergeRollsBackWhenOutboxEnqueueFails(): void
    {
        global $wpdb;
        $service = $this->serviceWithFailingOutbox();

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/revert-merge');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('moved_identity_ids', ['identity-77', 'identity-88']);
        $request->set_param('source_label', 'Restored Cluster');

        $response = $service->revert_merge_cluster($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    private function serviceWithFailingOutbox(): ClusterMergeService
    {
        $outbox = new ClusterMutationsOutboxWriterSpy();
        $outbox->nextEnqueueResult = false;
        $host = new ClusterMutationsController(
            $this->repository,
            $this->syncStateRepository,
            $this->membersRepository,
            $outbox,
            new ClusterMutationsTopologyCommandSpy()
        );

        return new ClusterMergeService(
            $host,
            $this->repository,
            $this->membersRepository,
            $this->syncStateRepository
        );
    }
}
