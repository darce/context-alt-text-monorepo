<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\ClusterMutationsController
 */
class ClusterMutationsControllerDualWriteTest extends TestCase
{
    use FindsSqlQueries;

    private ClusterMutationsController $controller;
    private ClusterMutationsRepositorySpy $repository;
    private ClusterMutationsMembersSpy $membersRepository;
    private ClusterMutationsSyncStateSpy $syncStateRepository;
    private ClusterMutationsTopologyCommandSpy $topologyCommandRepository;

    protected function setUp(): void
    {
        parent::setUp();
        // RECOG-1: default source flipped to 'service' with an empty default URL.
        // Pin a service target so backend-proxy paths have a non-empty effective target.
        $this->setOption('acx_recognition_url', 'https://recognition.test');
        $this->repository = new ClusterMutationsRepositorySpy();
        $this->membersRepository = new ClusterMutationsMembersSpy();
        $this->syncStateRepository = new ClusterMutationsSyncStateSpy();
        $this->topologyCommandRepository = new ClusterMutationsTopologyCommandSpy();
        $this->controller = new ClusterMutationsController($this->repository, $this->syncStateRepository, $this->membersRepository, null, $this->topologyCommandRepository);
    }

    public function testRegisterRoutesIncludesRepresentativePinEndpoint(): void
    {
        $this->controller->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains(
            '/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/representatives/(?P<representative_id>[a-f0-9-]+)/pin',
            $routes
        );
    }

    public function testPinRepresentativeQueuesReplayOperationInsideTransaction(): void
    {
        $request = new \WP_REST_Request('PATCH', '/recognition/clusters/cluster-xyz/representatives/identity-77/pin', [
            'cluster_id' => 'cluster-xyz',
            'representative_id' => 'identity-77',
            'is_pinned' => true,
        ]);

        $response = $this->controller->pin_representative($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertContains('START TRANSACTION', $GLOBALS['wpdb']->queries);
        $this->assertContains('COMMIT', $GLOBALS['wpdb']->queries);
        $this->assertSame('cluster-xyz', $this->repository->lastRepresentativeClusterId);
        $this->assertSame('identity-77', $this->repository->lastRepresentativeId);
        $this->assertTrue($this->repository->lastRepresentativePinned);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);

        $outboxInsert = $this->findQueryContaining($GLOBALS['wpdb']->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'representative_pin_updated'", $outboxInsert);
        $this->assertStringContainsString("'cluster-xyz'", $outboxInsert);
        $this->assertStringContainsString('identity-77', $outboxInsert);
        $this->assertStringContainsString('is_pinned', $outboxInsert);
        $this->assertSame([], $this->getHttpCalls());
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

    public function testDismissRollsBackWhenCommitFails(): void
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
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
        $this->assertContains('START TRANSACTION', $GLOBALS['wpdb']->queries);
        $this->assertContains('COMMIT', $GLOBALS['wpdb']->queries);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testReassignRollsBackWhenCommitFails(): void
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

    public function testLabelUpdateProxiesToBackendWhenLocalProjectionIsMissing(): void
    {
        $this->repository->localClusterRows = [];
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"id":"cluster-xyz","label":"Known Person","identity_count":3}',
        ]);

        $request = new \WP_REST_Request('PATCH', '/recognition/clusters/cluster-xyz', [
            'cluster_id' => 'cluster-xyz',
            'label' => 'Known Person',
        ]);

        $response = $this->controller->update_cluster_label($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/clusters/cluster-xyz', $calls[0]['url']);
        $this->assertSame('PATCH', $calls[0]['args']['method']);
        $this->assertStringContainsString('"tenant_id"', (string) ($calls[0]['args']['body'] ?? ''));
        $this->assertStringContainsString('"label":"Known Person"', (string) ($calls[0]['args']['body'] ?? ''));
    }

    public function testLabelUpdateProxyReturnsBackendFailureResponse(): void
    {
        $this->repository->localClusterRows = [];
        for ($index = 0; $index < 3; $index++) {
            $this->queueHttpResponse([
                'response' => ['code' => 500, 'message' => 'Internal Server Error'],
                'body' => '{"detail":"backend exploded"}',
            ]);
        }

        $request = new \WP_REST_Request('PATCH', '/recognition/clusters/cluster-xyz', [
            'cluster_id' => 'cluster-xyz',
            'label' => 'Known Person',
        ]);

        $response = $this->controller->update_cluster_label($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(500, $response->get_status());
        $this->assertSame(['detail' => 'backend exploded'], $response->get_data());
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
        // CON-1: source emptied to 0 (absolute reset for the dismissed cluster);
        // target gains the moved members (+3) as an atomic relative delta.
        $this->assertSame([['cluster-source', 0]], $this->repository->identityCountUpdates);
        $this->assertSame([['cluster-target', 3]], $this->repository->identityCountAdjustments);
        $this->assertSame('cluster-source', $this->repository->dismissedClusterId);
        $this->assertSame('cluster-target', $this->repository->updatedLabelClusterId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxJoined = implode(
            "\n",
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_sync_outbox')
            )
        );
        $this->assertStringContainsString("'cluster_merged'", $outboxJoined);
        $this->assertStringContainsString("'cluster-source'", $outboxJoined);
        $this->assertStringContainsString('cluster-target', $outboxJoined);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testMergeRollsBackWhenCommitFails(): void
    {
        global $wpdb;
        $wpdb->queryResults['COMMIT'] = false;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-source/merge', [
            'source_id' => 'cluster-source',
            'target_cluster_id' => 'cluster-target',
        ]);

        $response = $this->controller->merge_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
    }

    public function testMergeRejectsSourceAndTargetBeingTheSame(): void
    {
        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-source/merge', [
            'source_id' => 'cluster-source',
            'target_cluster_id' => 'cluster-source',
        ]);

        $response = $this->controller->merge_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('invalid_target_cluster_id', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status']);
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

    public function testRevertMergeQueuesReplayOperationInsideTransaction(): void
    {
        global $wpdb;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/revert-merge', [
            'target_cluster_id' => 'cluster-target',
            'moved_identity_ids' => ['identity-77', 'identity-88'],
            'source_label' => 'Restored Cluster',
        ]);

        $response = $this->controller->revert_merge_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame('pending', $data['status']);
        $this->assertSame('cluster-target', $data['target_cluster_id']);
        $this->assertSame(2, $data['restored_identity_count']);
        $this->assertNotSame('', $data['restored_cluster_id']);
        $this->assertSame($data['restored_cluster_id'], $this->repository->createdLocalClusterId);
        $this->assertSame('identity-88', $this->membersRepository->lastReassignedIdentityId);
        $this->assertSame($data['restored_cluster_id'], $this->membersRepository->lastTargetClusterId);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'revert_merge_cluster'", $outboxInsert);
        $this->assertStringContainsString("'cluster-target'", $outboxInsert);
        $this->assertStringContainsString('desired_source_cluster_id', $outboxInsert);
        $this->assertStringContainsString($data['restored_cluster_id'], $outboxInsert);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testRevertMergeRollsBackWhenCommitFails(): void
    {
        global $wpdb;
        $wpdb->queryResults['COMMIT'] = false;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/revert-merge', [
            'target_cluster_id' => 'cluster-target',
            'moved_identity_ids' => ['identity-77'],
        ]);

        $response = $this->controller->revert_merge_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
    }

    public function testRevertMergeRejectsIdentityNotInTargetCluster(): void
    {
        $request = new \WP_REST_Request('POST', '/recognition/clusters/revert-merge', [
            'target_cluster_id' => 'cluster-target',
            'moved_identity_ids' => ['identity-outlier'],
        ]);

        $response = $this->controller->revert_merge_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('identity_not_in_target_cluster', $response->get_error_code());
        $this->assertSame(409, $response->get_error_data()['status']);
    }

    public function testAssignOutlierQueuesReplayOperationInsideTransaction(): void
    {
        global $wpdb;

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-target/assign', [
            'cluster_id' => 'cluster-target',
            'identity_id' => 'identity-outlier',
            'similarity' => 0.42,
        ]);

        $response = $this->controller->assign_outlier_to_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('identity-outlier', $this->membersRepository->lastReassignedIdentityId);
        $this->assertSame('cluster-target', $this->membersRepository->lastTargetClusterId);
        // CON-1: source -1 / target +1 as atomic relative deltas.
        $this->assertSame([], $this->repository->identityCountUpdates);
        $this->assertSame([['cluster-source', -1], ['cluster-target', 1]], $this->repository->identityCountAdjustments);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'assign_outlier_to_cluster'", $outboxInsert);
        $this->assertStringContainsString("'cluster-target'", $outboxInsert);
        $this->assertStringContainsString('\\"similarity\\":0.42', $outboxInsert);
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testAssignOutlierReturnsAcknowledgedWhenIdentityAlreadyInTargetCluster(): void
    {
        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-target/assign', [
            'cluster_id' => 'cluster-target',
            'identity_id' => 'identity-77',
        ]);

        $response = $this->controller->assign_outlier_to_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('acknowledged', $response->get_data()['status']);
    }
}
