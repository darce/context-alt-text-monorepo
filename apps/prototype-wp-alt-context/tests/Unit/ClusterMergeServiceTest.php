<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterMergeService;
use AltContext\Sovereign\Repositories\ClusterProjectionWriter;
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

    /** @param array<string,mixed> $overrides */
    private function seedClusterRow(string $clusterUuid = 'cluster-target', array $overrides = []): void
    {
        global $wpdb;
        $wpdb->tableRows['wp_acx_clusters'] = [
            array_merge(
                [
                    'cluster_uuid' => $clusterUuid,
                    'tenant_id' => self::currentTenantId(),
                    'label' => 'Old',
                    'person_id' => null,
                ],
                $overrides
            ),
        ];
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

        $outboxJoined = implode(
            "\n",
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_sync_outbox')
            )
        );
        $this->assertStringContainsString("'cluster_merged'", $outboxJoined);
    }

    public function testLocalMergeResponseKeysMatchTheContract(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Merged Cluster');

        $response = $this->service->merge_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(
            [
                'source_cluster_id',
                'target_cluster_id',
                'moved_identity_count',
                'synced',
                'status',
                'roster_bound',
            ],
            array_keys($response->get_data())
        );
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

    public function testRevertMergeCreateLocalClusterStoresDistinctPersonNameOnCollision(): void
    {
        global $wpdb;

        $repository = new class() extends ClusterMutationsRepositorySpy {
            public function create_local_cluster(string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1): int|\WP_Error
            {
                $this->createdLocalClusterId = $cluster_uuid;
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
        $service = new ClusterMergeService(
            $host,
            $repository,
            $this->membersRepository,
            $this->syncStateRepository
        );

        $wpdb->insert_id = 41;
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 3,
                'person_uuid' => 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                'name' => 'Ada Lovelace',
                'normalized_name' => \AltContext\Api\Services\PersonResolutionService::normalize_name('Ada Lovelace'),
                'tenant_id' => self::currentTenantId(),
            ],
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-other',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Ada Lovelace',
                'person_id' => 3,
            ],
        ];

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/revert-merge');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('moved_identity_ids', ['identity-77']);
        $request->set_param('source_label', 'Ada Lovelace');

        $response = $service->revert_merge_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $created = null;
        foreach ($wpdb->tableRows['wp_acx_clusters'] as $row) {
            if (($row['cluster_uuid'] ?? '') === $repository->createdLocalClusterId) {
                $created = $row;
                break;
            }
        }
        $this->assertIsArray($created);
        $this->assertSame('Ada Lovelace (2)', $created['label']);
        $this->assertArrayHasKey('person_id', $created);
        $this->assertSame(41, (int) $created['person_id']);
    }

    public function testLocalMergeReportsRosterBoundTrueWhenBindMatches(): void
    {
        global $wpdb;

        $wpdb->insert_id = 88;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $this->seedClusterRow();

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Merged Person');

        $response = $this->service->merge_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertEmpty($this->getHttpCalls(), 'local merge must not proxy');
        $this->assertTrue($response->get_data()['roster_bound']);
    }

    public function testLocalMergeReportsRosterBoundFalseWhenBindMatchesNoRow(): void
    {
        global $wpdb;

        $wpdb->insert_id = 88;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [];

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Merged Person');

        $response = $this->service->merge_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertEmpty($this->getHttpCalls(), 'local merge must not proxy');
        $this->assertFalse($response->get_data()['roster_bound']);
    }

    public function testMergeClusterWithTargetLabelBindsPerson(): void
    {
        global $wpdb;

        $wpdb->insert_id = 88;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $this->seedClusterRow();

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Merged Person');

        $response = $this->service->merge_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('Merged Person', $this->repository->updatedLabel);
        $this->assertSame('cluster-target', $this->repository->updatedLabelClusterId);

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(1, $personInserts, 'target relabel must resolve_or_create a person');
        $this->assertStringContainsString("'Merged Person'", $personInserts[0]);

        $bindUpdate = $this->findQueryContaining($wpdb->queries, 'person_id = 88');
        $this->assertStringContainsString("cluster_uuid = 'cluster-target'", $bindUpdate);

        $outboxJoined = implode(
            "\n",
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_sync_outbox')
            )
        );
        $this->assertStringContainsString("'person_created'", $outboxJoined);
        $this->assertStringContainsString("'cluster_person_bound'", $outboxJoined);
    }

    public function testMergeProxyWithTargetLabelPersistsPersonAfterSuccess(): void
    {
        global $wpdb;

        $this->repository->localClusterRows = [];
        $wpdb->insert_id = 70;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $this->seedClusterRow();
        $this->setOption('acx_recognition_url', 'https://recognition.test');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"source_cluster_id":"cluster-source","target_cluster_id":"cluster-target"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Proxy Merged');

        $response = $this->service->merge_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(70, $response->get_data()['person_id']);
        $this->assertTrue($response->get_data()['roster_bound']);
        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(1, $personInserts);
    }

    public function testProxyMergeWriteSurfacesBindDatabaseFailureAsServerError(): void
    {
        global $wpdb;

        $this->repository->localClusterRows = [];
        $wpdb->insert_id = 70;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $this->seedClusterRow();
        $wpdb->updateResultsByTable['wp_acx_clusters'] = false;
        $this->setOption('acx_recognition_url', 'https://recognition.test');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"source_cluster_id":"cluster-source","target_cluster_id":"cluster-target"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Proxy Merged');

        $response = $this->service->merge_cluster($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertSame(500, $response->get_error_data()['status']);
        $this->assertArrayNotHasKey(
            'roster_bound',
            is_array($response->get_error_data()) ? $response->get_error_data() : []
        );
        $this->assertArrayNotHasKey(
            'roster_bound',
            is_array($response->get_data()) ? $response->get_data() : []
        );
    }

    public function testMergeReportsRosterBoundFalseWhenBindMatchesNoRow(): void
    {
        global $wpdb;

        $this->repository->localClusterRows = [];
        $wpdb->insert_id = 70;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [];
        $this->setOption('acx_recognition_url', 'https://recognition.test');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"source_cluster_id":"cluster-source","target_cluster_id":"cluster-target"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Proxy Merged');

        $response = $this->service->merge_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertFalse($data['roster_bound']);
    }

    public function testMergeRejectsRebindToDifferentPerson(): void
    {
        $this->repository->localClusterRows['cluster-target']['person_id'] = 5;
        $this->repository->localClusterRows['cluster-target']['label'] = 'Existing';

        global $wpdb;
        $wpdb->insert_id = 71;
        $wpdb->tableRows['wp_acx_persons'] = [];

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/merge');
        $request->set_param('source_id', 'cluster-source');
        $request->set_param('target_cluster_id', 'cluster-target');
        $request->set_param('target_label', 'Different Person');

        $response = $this->service->merge_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('cluster_already_bound', $response->get_error_code());
        $this->assertSame(409, $response->get_error_data()['status']);
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
