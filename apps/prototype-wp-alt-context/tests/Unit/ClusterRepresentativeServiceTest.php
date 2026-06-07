<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterRepresentativeService;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterRepresentativeService
 */
class ClusterRepresentativeServiceTest extends TestCase
{
    use FindsSqlQueries;

    private ClusterRepresentativeService $service;
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
        $this->service = new ClusterRepresentativeService($host, $this->repository, $this->syncStateRepository);
    }

    public function testPinRepresentativeQueuesReplayInsideTransaction(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz/representatives/identity-77/pin');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('representative_id', 'identity-77');
        $request->set_param('is_pinned', true);

        $response = $this->service->pin_representative($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('cluster-xyz', $this->repository->lastRepresentativeClusterId);
        $this->assertSame('identity-77', $this->repository->lastRepresentativeId);
        $this->assertTrue($this->repository->lastRepresentativePinned);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'representative_pin_updated'", $outboxInsert);
    }
}
