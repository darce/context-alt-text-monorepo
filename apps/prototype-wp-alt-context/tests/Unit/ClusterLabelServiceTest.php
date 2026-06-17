<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterLabelService;
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
 * @covers \AltContext\Api\Services\ClusterLabelService
 */
class ClusterLabelServiceTest extends TestCase
{
    use FindsSqlQueries;

    private ClusterLabelService $service;
    private ClusterMutationsRepositorySpy $repository;
    private ClusterMutationsSyncStateSpy $syncStateRepository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClusterMutationsRepositorySpy();
        $this->syncStateRepository = new ClusterMutationsSyncStateSpy();
        $host = new ClusterMutationsController(
            $this->repository,
            $this->syncStateRepository,
            new ClusterMutationsMembersSpy(),
            null,
            new ClusterMutationsTopologyCommandSpy()
        );
        $this->service = new ClusterLabelService($host, $this->repository, $this->syncStateRepository);
    }

    public function testUpdateClusterLabelQueuesReplayInsideTransaction(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Known Person');

        $response = $this->service->update_cluster_label($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('cluster-xyz', $this->repository->updatedLabelClusterId);
        $this->assertSame('Known Person', $this->repository->updatedLabel);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_label_updated'", $outboxInsert);
    }

    public function testUpdateClusterLabelRejectsEmptyLabel(): void
    {
        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', '');

        $response = $this->service->update_cluster_label($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('missing_label', $response->get_error_code());
    }

    public function testUpdateClusterLabelRollsBackWhenOutboxEnqueueFails(): void
    {
        global $wpdb;
        $outbox = new ClusterMutationsOutboxWriterSpy();
        $outbox->nextEnqueueResult = false;
        $host = new ClusterMutationsController(
            $this->repository,
            $this->syncStateRepository,
            new ClusterMutationsMembersSpy(),
            $outbox,
            new ClusterMutationsTopologyCommandSpy()
        );
        $service = new ClusterLabelService($host, $this->repository, $this->syncStateRepository);

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Known Person');

        $response = $service->update_cluster_label($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }
}
