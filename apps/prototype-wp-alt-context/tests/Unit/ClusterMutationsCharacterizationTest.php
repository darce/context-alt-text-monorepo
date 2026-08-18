<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * Golden-JSON characterization safety net for all 11 cluster-mutation routes.
 *
 * @covers \AltContext\Api\ClusterMutationsController
 */
class ClusterMutationsCharacterizationTest extends TestCase
{
    private const FIXTURE_ROOT = __DIR__ . '/../fixtures/cluster-mutations';

    private ClusterMutationsController $controller;
    private ClusterMutationsRepositorySpy $repository;
    private ClusterMutationsMembersSpy $membersRepository;
    private ClusterMutationsSyncStateSpy $syncStateRepository;
    private ClusterMutationsTopologyCommandSpy $topologyCommandRepository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_source', 'service');
        $GLOBALS['__ac_uuid_counter'] = 0;
        $this->repository = new ClusterMutationsRepositorySpy();
        $this->membersRepository = new ClusterMutationsMembersSpy();
        $this->syncStateRepository = new ClusterMutationsSyncStateSpy();
        $this->topologyCommandRepository = new ClusterMutationsTopologyCommandSpy();
        $this->controller = new ClusterMutationsController(
            $this->repository,
            $this->syncStateRepository,
            $this->membersRepository,
            null,
            $this->topologyCommandRepository
        );
    }

    public function testClusterMediaIsBackendProxyMutation(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => '{"job_id":"job-42","status":"queued"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/cluster');
        $request->set_param('mode', 'async');

        $response = $this->controller->cluster_media($request);

        $this->assertGolden('cluster_media', $response, [
            'classification' => 'backend_proxy_mutation',
            'http_calls' => count($this->getHttpCalls()),
            'touched_tenant_id' => $this->syncStateRepository->lastTouchedTenantId,
            'outbox_operations' => [],
            'transaction_queries' => [],
            'topology_command_type' => '',
            'refresh_curation_metrics' => $this->syncStateRepository->refreshCurationMetricsCalled,
        ]);
    }

    public function testReassignClusterIdentityGolden(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/reassign');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('target_cluster_id', 'cluster-target');

        $response = $this->controller->reassign_cluster_identity($request);

        $this->assertGolden('reassign_cluster_identity', $response, $this->captureSideEffects());
    }

    public function testUpdateClusterLabelGolden(): void
    {
        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Known Person');

        $response = $this->controller->update_cluster_label($request);

        $this->assertGolden('update_cluster_label', $response, $this->captureSideEffects());
    }

    public function testDismissClusterGolden(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-xyz/dismiss');
        $request->set_param('cluster_id', 'cluster-xyz');

        $response = $this->controller->dismiss_cluster($request);

        $this->assertGolden('dismiss_cluster', $response, $this->captureSideEffects());
    }

    public function testUndismissClusterGolden(): void
    {
        $request = new WP_REST_Request('DELETE', '/acx/v1/recognition/clusters/cluster-xyz/dismiss');
        $request->set_param('cluster_id', 'cluster-xyz');

        $response = $this->controller->undismiss_cluster($request);

        $this->assertGolden('undismiss_cluster', $response, $this->captureSideEffects());
    }

    public function testMergeClusterGolden(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Merged Cluster');

        $response = $this->controller->merge_cluster($request);

        $this->assertGolden('merge_cluster', $response, $this->captureSideEffects());
    }

    public function testSplitClusterGolden(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/split');
        $request->set_param('cluster_id', 'cluster-source');
        $request->set_param('n_clusters', 2);
        $request->set_param('split_mode', 'manual');

        $response = $this->controller->split_cluster($request);

        $this->assertGolden('split_cluster', $response, $this->captureSideEffects());
    }

    public function testCreateClusterForIdentityGolden(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/create-for-identity');
        $request->set_param('identity_id', 'identity-77');
        $request->set_param('label', 'Curated Name');

        $response = $this->controller->create_cluster_for_identity($request);

        $this->assertGolden('create_cluster_for_identity', $response, $this->captureSideEffects());
    }

    public function testRevertMergeClusterGolden(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/revert-merge');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('moved_identity_ids', ['identity-77', 'identity-88']);
        $request->set_param('source_label', 'Restored Cluster');

        $response = $this->controller->revert_merge_cluster($request);

        $this->assertGolden('revert_merge_cluster', $response, $this->captureSideEffects());
    }

    public function testAssignOutlierToClusterGolden(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-target/assign');
        $request->set_param('cluster_id', 'cluster-target');
        $request->set_param('identity_id', 'identity-outlier');
        $request->set_param('similarity', 0.42);

        $response = $this->controller->assign_outlier_to_cluster($request);

        $this->assertGolden('assign_outlier_to_cluster', $response, $this->captureSideEffects());
    }

    public function testPinRepresentativeGolden(): void
    {
        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz/representatives/identity-77/pin');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('representative_id', 'identity-77');
        $request->set_param('is_pinned', true);

        $response = $this->controller->pin_representative($request);

        $this->assertGolden('pin_representative', $response, $this->captureSideEffects());
    }

    /**
     * @return array<string,mixed>
     */
    private function captureSideEffects(): array
    {
        global $wpdb;

        return [
            'touched_tenant_id' => $this->syncStateRepository->lastTouchedTenantId,
            'outbox_operations' => $this->findOutboxOperations($wpdb->queries ?? []),
            'transaction_queries' => $this->captureTransactionQueries($wpdb->queries ?? []),
            'topology_command_type' => $this->topologyCommandRepository->lastCommandType,
            'refresh_curation_metrics' => $this->syncStateRepository->refreshCurationMetricsCalled,
        ];
    }

    /**
     * @param array<int,string> $queries
     * @return array<int,string>
     */
    private function captureTransactionQueries(array $queries): array
    {
        $captured = [];
        foreach ($queries as $query) {
            if (in_array($query, ['START TRANSACTION', 'COMMIT', 'ROLLBACK'], true)) {
                $captured[] = $query;
            }
        }

        return $captured;
    }

    /**
     * @param array<int,string> $queries
     * @return list<string>
     */
    private function findOutboxOperations(array $queries): array
    {
        $operations = [];
        foreach ($queries as $query) {
            if (! str_contains($query, 'INSERT INTO wp_acx_sync_outbox')) {
                continue;
            }
            if (preg_match("/'([a-z_]+)'/", $query, $matches) === 1) {
                $operations[] = $matches[1];
            }
        }

        return $operations;
    }

    /**
     * @param array<string,mixed> $sideEffects
     */
    private function assertGolden(string $handler, WP_REST_Response|WP_Error $response, array $sideEffects): void
    {
        $fixtureDir = self::FIXTURE_ROOT . '/' . $handler;
        $responseFixture = $fixtureDir . '/response.json';
        $sideEffectsFixture = $fixtureDir . '/side-effects.json';

        $actualResponse = $this->serializeResponse($response);
        $actualSideEffects = $this->serializeSideEffects($sideEffects);

        if (getenv('UPDATE_CLUSTER_MUTATIONS_FIXTURES') === '1') {
            if (! is_dir($fixtureDir)) {
                mkdir($fixtureDir, 0755, true);
            }
            file_put_contents($responseFixture, $actualResponse);
            file_put_contents($sideEffectsFixture, $actualSideEffects);
        }

        $this->assertFileExists($responseFixture, sprintf('Missing golden response fixture for %s.', $handler));
        $this->assertFileExists($sideEffectsFixture, sprintf('Missing golden side-effects fixture for %s.', $handler));

        $expectedResponse = (string) file_get_contents($responseFixture);
        $expectedSideEffects = (string) file_get_contents($sideEffectsFixture);
        $this->assertSame(
            json_decode($expectedResponse, true),
            json_decode($actualResponse, true),
            sprintf('Golden response drift for %s.', $handler)
        );
        $this->assertSame(
            json_decode($expectedSideEffects, true),
            json_decode($actualSideEffects, true),
            sprintf('Golden side-effects drift for %s.', $handler)
        );
    }

    private function serializeResponse(WP_REST_Response|WP_Error $response): string
    {
        if (is_wp_error($response)) {
            $payload = [
                'type' => 'error',
                'code' => $response->get_error_code(),
                'message' => $response->get_error_message(),
                'data' => $response->get_error_data(),
            ];
        } else {
            $payload = [
                'type' => 'response',
                'status' => $response->get_status(),
                'data' => $response->get_data(),
            ];
        }

        $encoded = wp_json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $this->assertIsString($encoded);

        return $encoded;
    }

    /**
     * @param array<string,mixed> $sideEffects
     */
    private function serializeSideEffects(array $sideEffects): string
    {
        $encoded = wp_json_encode($sideEffects, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $this->assertIsString($encoded);

        return $encoded;
    }
}
