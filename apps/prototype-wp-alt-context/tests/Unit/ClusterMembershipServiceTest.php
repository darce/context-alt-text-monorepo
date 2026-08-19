<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterMembershipService;
use AltContext\Api\Services\PersonResolutionService;
use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Repositories\ClusterProjectionWriter;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsOutboxWriterSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterMembershipService
 */
class ClusterMembershipServiceTest extends TestCase
{
    use FindsSqlQueries;

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

    /**
     * E21-14-BR-04: controller boundary must catch projection failures as WP_Error (not fatal).
     * Failed projection probe hard-fails rather than proxying (split-brain risk).
     */
    public function testCreateClusterForIdentityReturnsTypedErrorOnProjectionProbeFailure(): void
    {
        $repository = new class() extends ClusterMutationsRepositorySpy {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                throw new ProjectionQueryException(
                    'Projection query failed [clusters.has_projection_rows_for_tenant]: boom'
                );
            }
        };
        $members = new ClusterMutationsMembersSpy();
        $sync = new ClusterMutationsSyncStateSpy();
        $controller = new ClusterMutationsController(
            $repository,
            $sync,
            $members,
            null,
            new ClusterMutationsTopologyCommandSpy()
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/create-for-identity');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('label', 'Curated Name');

        $response = $controller->create_cluster_for_identity($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('acx_projection_query_failed', $response->get_error_code());
        $this->assertSame(500, (int) ($response->get_error_data()['status'] ?? 0));
        $this->assertStringNotContainsString('boom', $response->get_error_message());
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

    public function testAssignOutlierAdjustsCountsWithAtomicRelativeDeltas(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-target/assign');
        $request->set_param('cluster_id', 'cluster-target');
        $request->set_param('identity_id', 'identity-outlier');
        $request->set_param('similarity', 0.42);

        $response = $this->service->assign_outlier_to_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        // CON-1: source -1 / target +1 applied as atomic relative deltas, never
        // as absolute read-modify-write counts (which lose concurrent updates).
        $this->assertSame([['cluster-source', -1], ['cluster-target', 1]], $this->repository->identityCountAdjustments);
        $this->assertSame([], $this->repository->identityCountUpdates);
    }

    public function testCreateClusterForIdentityRollsBackWhenLocalCreateFails(): void
    {
        global $wpdb;
        $this->repository->nextCreateLocalClusterRows = 0;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/create-for-identity');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('label', 'Curated Name');

        $response = $this->service->create_cluster_for_identity($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    public function testCreateClusterForIdentityRollsBackWhenCommitFails(): void
    {
        global $wpdb;
        $wpdb->queryResults['COMMIT'] = false;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/create-for-identity');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('label', 'Curated Name');

        $response = $this->service->create_cluster_for_identity($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
    }

    public function testAssignOutlierToClusterRollsBackWhenCommitFails(): void
    {
        global $wpdb;
        $wpdb->queryResults['COMMIT'] = false;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-target/assign');
        $request->set_param('cluster_id', 'cluster-target');
        $request->set_param('identity_id', 'identity-outlier');
        $request->set_param('similarity', 0.42);

        $response = $this->service->assign_outlier_to_cluster($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
    }

    public function testReassignClusterIdentityRollsBackWhenCommitFails(): void
    {
        global $wpdb;
        $wpdb->queryResults['COMMIT'] = false;

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/reassign');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('target_cluster_id', 'cluster-target');

        $response = $this->service->reassign_cluster_identity($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
    }

    public function testReassignClusterIdentityRollsBackWhenOutboxEnqueueFails(): void
    {
        global $wpdb;
        $service = $this->serviceWithFailingOutbox();

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/reassign');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('target_cluster_id', 'cluster-target');

        $response = $service->reassign_cluster_identity($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    public function testCreateClusterForIdentityRollsBackWhenOutboxEnqueueFails(): void
    {
        global $wpdb;
        $service = $this->serviceWithFailingOutbox();

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/create-for-identity');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('label', 'Curated Name');

        $response = $service->create_cluster_for_identity($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    public function testAssignOutlierToClusterRollsBackWhenOutboxEnqueueFails(): void
    {
        global $wpdb;
        $service = $this->serviceWithFailingOutbox();

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-target/assign');
        $request->set_param('cluster_id', 'cluster-target');
        $request->set_param('identity_id', 'identity-outlier');
        $request->set_param('similarity', 0.42);

        $response = $service->assign_outlier_to_cluster($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    public function testCreateForIdentitySurfacesNameCollisionAs409(): void
    {
        global $wpdb;

        $repository = new class() extends ClusterMutationsRepositorySpy {
            public function create_local_cluster(string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1): int|\WP_Error
            {
                return (new ClusterProjectionWriter('wp_acx_clusters'))
                    ->create_local_cluster($tenant_id, $cluster_uuid, $label, $identity_count);
            }
        };
        $host = new ClusterMutationsController(
            $repository,
            $this->syncStateRepository,
            $this->membersRepository,
            null,
            new ClusterMutationsTopologyCommandSpy()
        );
        $service = new ClusterMembershipService(
            $host,
            $repository,
            $this->membersRepository,
            $this->syncStateRepository
        );

        $rows = [
            [
                'id' => 1,
                'person_uuid' => 'aaaaaaaa-bbbb-cccc-dddd-000000000001',
                'name' => 'Ada Lovelace',
                'normalized_name' => PersonResolutionService::normalize_name('Ada Lovelace'),
                'tenant_id' => self::currentTenantId(),
            ],
        ];
        for ($suffix = 2; $suffix <= 99; $suffix++) {
            $name = 'Ada Lovelace (' . $suffix . ')';
            $rows[] = [
                'id' => $suffix,
                'person_uuid' => sprintf('aaaaaaaa-bbbb-cccc-dddd-%012d', $suffix),
                'name' => $name,
                'normalized_name' => PersonResolutionService::normalize_name($name),
                'tenant_id' => self::currentTenantId(),
            ];
        }
        $wpdb->tableRows['wp_acx_persons'] = $rows;
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-other',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Ada Lovelace',
                'person_id' => 1,
            ],
        ];

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/create-for-identity');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('label', 'Ada Lovelace');

        $response = $service->create_cluster_for_identity($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('acx_name_collision', $response->get_error_code());
        $this->assertSame(409, $response->get_error_data()['status']);
    }

    private function serviceWithFailingOutbox(): ClusterMembershipService
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

        return new ClusterMembershipService(
            $host,
            $this->repository,
            $this->membersRepository,
            $this->syncStateRepository
        );
    }
}
