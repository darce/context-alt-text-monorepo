<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterLifecycleService;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterLifecycleService
 */
class ClusterLifecycleServiceTest extends TestCase
{
    use FindsSqlQueries;

    private ClusterLifecycleService $service;
    private ClusterMutationsRepositorySpy $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClusterMutationsRepositorySpy();
        $host = new ClusterMutationsController(
            $this->repository,
            new ClusterMutationsSyncStateSpy(),
            new ClusterMutationsMembersSpy(),
            null,
            new ClusterMutationsTopologyCommandSpy()
        );
        $this->service = new ClusterLifecycleService($host, $this->repository);
    }

    public function testDismissQueuesReplayInsideTransaction(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-xyz/dismiss');
        $request->set_param('cluster_id', 'cluster-xyz');

        $response = $this->service->dismiss_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('cluster-xyz', $this->repository->dismissedClusterId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_dismissed'", $outboxInsert);
    }

    public function testUndismissQueuesReplayInsideTransaction(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('DELETE', '/acx/v1/recognition/clusters/cluster-xyz/dismiss');
        $request->set_param('cluster_id', 'cluster-xyz');

        $response = $this->service->undismiss_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('cluster-xyz', $this->repository->undismissedClusterId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_undismissed'", $outboxInsert);
    }
}
