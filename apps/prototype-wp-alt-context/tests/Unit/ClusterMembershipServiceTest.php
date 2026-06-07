<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterMembershipService;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterMembershipService
 */
class ClusterMembershipServiceTest extends TestCase
{
    private ClusterMembershipService $service;
    private ClusterMutationsRepositorySpy $repository;
    private ClusterMutationsMembersSpy $membersRepository;
    private ClusterMutationsSyncStateSpy $syncStateRepository;

    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__ac_uuid_counter'] = 0;
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
        $this->service = new ClusterMembershipService(
            $host,
            $this->repository,
            $this->membersRepository,
            $this->syncStateRepository
        );
    }

    public function testReassignClusterIdentityQueuesReplayInsideTransaction(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/reassign');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('target_cluster_id', 'cluster-target');

        $response = $this->service->reassign_cluster_identity($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('identity-77', $this->membersRepository->lastReassignedIdentityId);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testCreateClusterForIdentityQueuesReplayInsideTransaction(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/create-for-identity');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('label', 'Curated Name');

        $response = $this->service->create_cluster_for_identity($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertNotSame('', $this->repository->createdLocalClusterId);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_created_for_identity'", $outboxInsert);
    }

    public function testAssignOutlierToClusterQueuesReplayInsideTransaction(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-target/assign');
        $request->set_param('cluster_id', 'cluster-target');
        $request->set_param('identity_id', 'identity-outlier');
        $request->set_param('similarity', 0.42);

        $response = $this->service->assign_outlier_to_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('identity-outlier', $this->membersRepository->lastReassignedIdentityId);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }
}
