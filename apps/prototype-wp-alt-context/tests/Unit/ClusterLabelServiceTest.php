<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterLabelService;
use AltContext\Api\Services\PersonResolutionService;
use AltContext\Sovereign\Repositories\RosterEntryProjectionRepository;
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
 * @covers \AltContext\Api\Services\PersonResolutionService
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

        $wpdb->insert_id = 77;

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

        $outboxInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_sync_outbox')
            )
        );
        $this->assertNotEmpty($outboxInserts);
        $joined = implode("\n", $outboxInserts);
        $this->assertStringContainsString("'cluster_label_updated'", $joined);
        $this->assertStringContainsString("'person_created'", $joined);
        $this->assertStringContainsString("'cluster_person_bound'", $joined);

        // Response shape stays pre-slice-2 (plan: request/response shapes unchanged).
        $data = $response->get_data();
        $this->assertSame('cluster-xyz', $data['cluster_id']);
        $this->assertSame('Known Person', $data['label']);
        $this->assertFalse($data['synced']);
        $this->assertSame('pending', $data['status']);
        $this->assertSame(77, $data['person_id']);
        $this->assertTrue($data['roster_bound']);
        $bindUpdate = $this->findQueryContaining($wpdb->queries, 'person_id = 77');
        $this->assertStringContainsString("cluster_uuid = 'cluster-xyz'", $bindUpdate);
        $this->assertStringContainsString('tenant_id =', $bindUpdate);
    }

    public function testUpdateClusterLabelSurfacesBindFailure(): void
    {
        global $wpdb;

        $wpdb->insert_id = 77;
        $wpdb->updateResultsByTable['wp_acx_clusters'] = false;
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-xyz',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Old',
                'person_id' => null,
            ],
        ];

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Known Person');

        $response = $this->service->update_cluster_label($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
    }

    public function testUpdateClusterLabelCreatesPersonAndBindingOnUnlabeledCluster(): void
    {
        global $wpdb;

        $wpdb->insert_id = 55;
        $wpdb->tableRows['wp_acx_persons'] = [];

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Ada Lovelace');

        $response = $this->service->update_cluster_label($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(1, $personInserts, 'labeling unlabeled cluster must create exactly one person');
        $this->assertStringContainsString("'Ada Lovelace'", $personInserts[0]);
        $this->assertStringContainsString(
            "'" . PersonResolutionService::normalize_name('Ada Lovelace') . "'",
            $personInserts[0]
        );

        $bindUpdate = $this->findQueryContaining($wpdb->queries, 'person_id = 55');
        $this->assertStringContainsString("cluster_uuid = 'cluster-xyz'", $bindUpdate);
        $this->assertStringContainsString("curation_state = 'confirmed'", $bindUpdate);

        $outboxPersonCreated = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, "'person_created'")
            )
        );
        $this->assertCount(1, $outboxPersonCreated);

        $outboxBound = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, "'cluster_person_bound'")
            )
        );
        $this->assertCount(1, $outboxBound);
    }

    public function testUpdateClusterLabelRebindsExistingPersonWithoutInsert(): void
    {
        global $wpdb;

        $existingUuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 42,
                'person_uuid' => $existingUuid,
                'name' => 'Ada Lovelace',
                'normalized_name' => PersonResolutionService::normalize_name('Ada Lovelace'),
                'tags' => '[]',
            ],
        ];

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        // Case + whitespace variant — normalizes equal, must rebind not insert.
        $request->set_param('label', '  ada lovelace  ');

        $response = $this->service->update_cluster_label($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        // Response shape unchanged; rebind identity is a side effect (DB + outbox).
        $this->assertSame('cluster-xyz', $data['cluster_id']);
        $this->assertSame('ada lovelace', $data['label']);
        $this->assertSame('pending', $data['status']);
        $this->assertSame(42, $data['person_id']);
        $this->assertTrue($data['roster_bound']);

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(0, $personInserts, 're-label to existing name must not insert');

        $outboxPersonCreated = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, "'person_created'")
            )
        );
        $this->assertCount(0, $outboxPersonCreated, 'rebind must not enqueue person_created');

        $outboxBound = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, "'cluster_person_bound'")
            )
        );
        $this->assertCount(1, $outboxBound);

        $bindUpdate = $this->findQueryContaining($wpdb->queries, 'person_id = 42');
        $this->assertStringContainsString("cluster_uuid = 'cluster-xyz'", $bindUpdate);
    }

    public function testWriteThroughToReadShowsPersonOnListEntries(): void
    {
        global $wpdb;

        $wpdb->insert_id = 91;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [];
        $wpdb->tableRows['wp_acx_identity_members'] = [];

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Grace Hopper');

        $response = $this->service->update_cluster_label($request);
        $this->assertInstanceOf(WP_REST_Response::class, $response);

        $created = $wpdb->tableRows['wp_acx_persons'][0] ?? null;
        $this->assertIsArray($created);
        $this->assertSame(91, $created['id']);

        $entries = (new RosterEntryProjectionRepository($this->syncStateRepository))
            ->list_entries(self::currentTenantId());

        $names = array_map(static fn(array $row): string => (string) ($row['name'] ?? ''), $entries);
        $this->assertContains('Grace Hopper', $names, 'Entries must not be empty after naming via label path');
    }

    public function testResolverInsideRunTransactionalIssuesNoNestedStartTransaction(): void
    {
        global $wpdb;

        $wpdb->insert_id = 12;

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Nested Guard');

        $response = $this->service->update_cluster_label($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);

        $starts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => $query === 'START TRANSACTION'
            )
        );
        $this->assertCount(
            1,
            $starts,
            'resolver must stay transaction-agnostic; nested START TRANSACTION would implicitly commit'
        );
        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertNotContains('ROLLBACK', $wpdb->queries);
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

    public function testUpdateClusterLabelRejectsReservedLabel(): void
    {
        global $wpdb;

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'CLUSTER-9');

        $response = $this->service->update_cluster_label($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('reserved_label', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status']);
        $this->assertSame('', $this->repository->updatedLabelClusterId);
        $this->assertNotContains('START TRANSACTION', $wpdb->queries);
    }

    /**
     * BR-11: identical-label resubmit with no person binding still write-throughs.
     * update_label returns 0 (no row change) but resolver/bind must still run.
     */
    public function testIdenticalLabelResubmitWithoutPersonBindingRunsWriteThrough(): void
    {
        global $wpdb;

        $this->repository->nextUpdateLabelRows = 0;
        $this->repository->localClusterRows['cluster-xyz'] = [
            'cluster_uuid' => 'cluster-xyz',
            'snapshot_version' => 17,
            'local_revision' => 4,
            'curation_state' => 'uncurated',
            'label' => 'Ada Lovelace',
            // person_id absent / null — binding missing despite label already set.
            'person_id' => null,
        ];
        $wpdb->insert_id = 66;
        $wpdb->tableRows['wp_acx_persons'] = [];

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Ada Lovelace');

        $response = $this->service->update_cluster_label($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('pending', $data['status']);
        $this->assertSame('Ada Lovelace', $data['label']);

        $labelUpdated = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, "'cluster_label_updated'")
            )
        );
        $this->assertCount(0, $labelUpdated, 'identical-label no-op must not re-enqueue cluster_label_updated');

        $personCreated = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, "'person_created'")
            )
        );
        $this->assertCount(1, $personCreated, 'missing person bind must still create/resolve person');

        $personBound = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, "'cluster_person_bound'")
            )
        );
        $this->assertCount(1, $personBound);

        $bindUpdate = $this->findQueryContaining($wpdb->queries, 'person_id = 66');
        $this->assertStringContainsString("cluster_uuid = 'cluster-xyz'", $bindUpdate);
        $this->assertSame(self::currentTenantId(), $this->syncStateRepository->lastTouchedTenantId);
    }

    /**
     * Identical-label resubmit when person binding already exists is a pure ack.
     */
    public function testIdenticalLabelResubmitWithPersonBindingAcknowledgesWithoutWriteThrough(): void
    {
        global $wpdb;

        $this->repository->nextUpdateLabelRows = 0;
        $this->repository->localClusterRows['cluster-xyz'] = [
            'cluster_uuid' => 'cluster-xyz',
            'snapshot_version' => 17,
            'local_revision' => 4,
            'curation_state' => 'confirmed',
            'label' => 'Ada Lovelace',
            'person_id' => 42,
        ];

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Ada Lovelace');

        $response = $this->service->update_cluster_label($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(
            [
                'cluster_id' => 'cluster-xyz',
                'label' => 'Ada Lovelace',
                'synced' => false,
                'status' => 'acknowledged',
            ],
            $response->get_data()
        );

        $personCreated = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, "'person_created'")
            )
        );
        $this->assertCount(0, $personCreated);
        $personBound = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, "'cluster_person_bound'")
            )
        );
        $this->assertCount(0, $personBound);
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

        $wpdb->insert_id = 3;
        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Known Person');

        $response = $service->update_cluster_label($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    public function testProxyLabelWriteStillCreatesLocalPerson(): void
    {
        global $wpdb;

        $this->repository->localClusterRows = [];
        $wpdb->insert_id = 33;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $this->setOption('acx_recognition_url', 'https://recognition.test');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"cluster_id":"cluster-xyz","label":"Proxy Person","synced":true}',
        ]);

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Proxy Person');

        $response = $this->service->update_cluster_label($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertNotEmpty($this->getHttpCalls(), 'proxy branch must still forward the label mutation');

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(1, $personInserts, 'proxy label write must persist a local person');
        $this->assertStringContainsString("'Proxy Person'", $personInserts[0]);

        $created = $wpdb->tableRows['wp_acx_persons'][0] ?? null;
        $this->assertIsArray($created);
        $this->assertSame(33, $created['id']);
        $this->assertTrue($response->get_data()['roster_bound']);
        $this->assertSame(33, $response->get_data()['person_id']);

        $entries = (new RosterEntryProjectionRepository($this->syncStateRepository))
            ->list_entries(self::currentTenantId());
        $names = array_map(static fn(array $row): string => (string) ($row['name'] ?? ''), $entries);
        $this->assertContains('Proxy Person', $names);
    }

    public function testProxyLabelWriteDoesNotPersistPersonOnProxyFailure(): void
    {
        global $wpdb;

        $this->repository->localClusterRows = [];
        $wpdb->insert_id = 33;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $this->setOption('acx_recognition_url', 'https://recognition.test');
        $failure = [
            'response' => ['code' => 500, 'message' => 'Error'],
            'body' => '{"error":"backend failed"}',
        ];
        $this->queueHttpResponse($failure);
        $this->queueHttpResponse($failure);
        $this->queueHttpResponse($failure);

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/cluster-xyz');
        $request->set_param('cluster_id', 'cluster-xyz');
        $request->set_param('label', 'Orphan Person');

        $response = $this->service->update_cluster_label($request);

        $this->assertTrue(is_wp_error($response) || ($response instanceof WP_REST_Response && $response->get_status() >= 500));
        $this->assertSame([], $wpdb->tableRows['wp_acx_persons'] ?? []);
        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(0, $personInserts);
    }

    public function testPersonResolutionServiceIsLoadableViaRequireOnceChain(): void
    {
        $controller = realpath(__DIR__ . '/../../src/api/class-cluster-mutations-controller.php');
        $this->assertIsString($controller);

        // rg-016: service must be loadable via classmap; controller must require_once it.
        $autoload = realpath(__DIR__ . '/../../vendor/autoload.php');
        $this->assertIsString($autoload);
        $output = shell_exec(
            sprintf(
                'php -r %s 2>&1',
                escapeshellarg(
                    sprintf(
                        'require %s; var_export(class_exists(%s));',
                        var_export($autoload, true),
                        var_export('AltContext\\Api\\Services\\PersonResolutionService', true)
                    )
                )
            )
        );
        $this->assertSame(
            'true',
            trim((string) $output),
            'PersonResolutionService must be loadable (rg-016 class_exists)'
        );

        $source = (string) file_get_contents((string) $controller);
        $this->assertStringContainsString(
            "require_once __DIR__ . '/services/class-person-resolution-service.php';",
            $source,
            'controller must explicit-require PersonResolutionService (rg-016)'
        );
    }
}
