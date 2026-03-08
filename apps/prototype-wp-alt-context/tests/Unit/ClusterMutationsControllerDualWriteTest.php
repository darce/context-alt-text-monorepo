<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\ClusterMutationsController
 */
class ClusterMutationsControllerDualWriteTest extends TestCase
{
    private ClusterMutationsController $controller;
    private ClusterMutationsRepositorySpy $repository;
    private ClusterMutationsSyncStateSpy $syncStateRepository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClusterMutationsRepositorySpy();
        $this->syncStateRepository = new ClusterMutationsSyncStateSpy();
        $this->controller = new ClusterMutationsController($this->repository, $this->syncStateRepository);
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

    public function testDismissRollbackWhenOutboxEnqueueFails(): void
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

    /**
     * @param array<int,string> $queries
     */
    private function findQueryContaining(array $queries, string $needle): string
    {
        foreach ($queries as $query) {
            if (str_contains($query, $needle)) {
                return $query;
            }
        }

        $this->fail(sprintf('Unable to find query containing "%s".', $needle));
        return '';
    }
}

class ClusterMutationsRepositorySpy extends NullClustersRepository
{
    public string $dismissedClusterId = '';
    public string $undismissedClusterId = '';
    public int $nextDismissRows = 1;
    public int $nextUndismissRows = 1;
    /** @var array<string,array<string,mixed>> */
    public array $localClusterRows = [
        'cluster-xyz' => [
            'cluster_uuid' => 'cluster-xyz',
            'snapshot_version' => 17,
            'local_revision' => 4,
            'curation_state' => 'uncurated',
        ],
    ];

    public function dismiss(string $cluster_uuid): int
    {
        $this->dismissedClusterId = $cluster_uuid;
        return $this->nextDismissRows;
    }

    public function undismiss(string $cluster_uuid): int
    {
        $this->undismissedClusterId = $cluster_uuid;
        return $this->nextUndismissRows;
    }

    public function find_by_uuid(string $cluster_uuid): ?array
    {
        return $this->localClusterRows[$cluster_uuid] ?? null;
    }
}

class ClusterMutationsSyncStateSpy extends NullSyncStateRepository
{
    public function get_snapshot_version(string $tenant_id): int
    {
        return 99;
    }
}
