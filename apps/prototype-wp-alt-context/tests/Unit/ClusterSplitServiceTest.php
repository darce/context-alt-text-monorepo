<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterSplitService;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterSplitService
 */
class ClusterSplitServiceTest extends TestCase
{
    use FindsSqlQueries;

    private ClusterSplitService $service;
    private ClusterMutationsSyncStateSpy $syncStateRepository;
    private ClusterMutationsTopologyCommandSpy $topologyCommandRepository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->syncStateRepository = new ClusterMutationsSyncStateSpy();
        $this->topologyCommandRepository = new ClusterMutationsTopologyCommandSpy();
        $host = new ClusterMutationsController(
            new ClusterMutationsRepositorySpy(),
            $this->syncStateRepository,
            new ClusterMutationsMembersSpy(),
            null,
            $this->topologyCommandRepository
        );
        $this->service = new ClusterSplitService(
            $host,
            $this->syncStateRepository,
            $this->topologyCommandRepository
        );
    }

    public function testSplitClusterEnqueuesTopologyCommandAndTouchesCurationMarker(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/split');
        $request->set_param('cluster_id', 'cluster-source');
        $request->set_param('n_clusters', 2);
        $request->set_param('split_mode', 'manual');

        $response = $this->service->split_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('cluster_split', $this->topologyCommandRepository->lastCommandType);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertTrue($this->syncStateRepository->refreshCurationMetricsCalled);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }
}
