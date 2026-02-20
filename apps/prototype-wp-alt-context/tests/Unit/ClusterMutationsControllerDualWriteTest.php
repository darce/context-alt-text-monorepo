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

    public function testLocalWriteSurvivesProxyFailureScaffold(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new \WP_REST_Request('PATCH', '/recognition/clusters/cluster-abc', [
            'cluster_id' => 'cluster-abc',
            'label' => 'Grace Hopper',
        ]);

        $response = $this->controller->update_cluster_label($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('cluster-abc', $this->repository->updatedClusterId);
        $this->assertSame('Grace Hopper', $this->repository->updatedLabel);
        $this->assertSame(1, $this->syncStateRepository->touchCount);
    }

    public function testLocalDismissWriteSurvivesProxyFailure(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/dismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->dismiss_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('cluster-xyz', $this->repository->dismissedClusterId);
        $this->assertSame(1, $this->syncStateRepository->touchCount);
    }

    public function testLocalUndismissWriteSurvivesProxyFailure(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/undismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->undismiss_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame('cluster-xyz', $this->repository->undismissedClusterId);
        $this->assertSame(1, $this->syncStateRepository->touchCount);
    }

    public function testDismissTreatsRemote404AsIdempotentSuccessWhenLocalWriteApplied(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'Cluster not found or already dismissed']),
        ]);

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/dismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->dismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('cluster-xyz', $this->repository->dismissedClusterId);
        $this->assertSame(1, $this->syncStateRepository->touchCount);
    }

    public function testUndismissTreatsRemote404AsIdempotentSuccessWhenLocalWriteApplied(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'Cluster not found or already dismissed']),
        ]);

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/undismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->undismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('cluster-xyz', $this->repository->undismissedClusterId);
        $this->assertSame(1, $this->syncStateRepository->touchCount);
    }

    public function testDismissTreatsRemote404AsIdempotentSuccessWhenClusterAlreadyLocallyDismissed(): void
    {
        $this->repository->nextDismissRows = 0;
        $this->repository->localClusterRows['cluster-xyz'] = [
            'cluster_uuid' => 'cluster-xyz',
            'curation_state' => 'dismissed',
        ];

        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'Cluster not found or already dismissed']),
        ]);

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/dismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->dismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('cluster-xyz', $this->repository->dismissedClusterId);
        $this->assertSame(0, $this->syncStateRepository->touchCount);
    }

    public function testZeroRowLabelMutationDoesNotTouchSyncStateMarker(): void
    {
        $this->repository->nextUpdateRows = 0;
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new \WP_REST_Request('PATCH', '/recognition/clusters/cluster-abc', [
            'cluster_id' => 'cluster-abc',
            'label' => 'Grace Hopper',
        ]);

        $response = $this->controller->update_cluster_label($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame(0, $this->syncStateRepository->touchCount);
    }

    public function testZeroRowDismissMutationDoesNotTouchSyncStateMarker(): void
    {
        $this->repository->nextDismissRows = 0;
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/dismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->dismiss_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame(0, $this->syncStateRepository->touchCount);
    }

    public function testZeroRowUndismissMutationDoesNotTouchSyncStateMarker(): void
    {
        $this->repository->nextUndismissRows = 0;
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new \WP_REST_Request('POST', '/recognition/clusters/cluster-xyz/undismiss', [
            'cluster_id' => 'cluster-xyz',
        ]);

        $response = $this->controller->undismiss_cluster($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertSame(0, $this->syncStateRepository->touchCount);
    }
}

class ClusterMutationsRepositorySpy extends NullClustersRepository
{
    public string $updatedClusterId = '';
    public string $updatedLabel = '';
    public string $dismissedClusterId = '';
    public string $undismissedClusterId = '';
    public int $nextUpdateRows = 1;
    public int $nextDismissRows = 1;
    public int $nextUndismissRows = 1;
    /** @var array<string,array<string,mixed>> */
    public array $localClusterRows = [];

    public function update_label(string $cluster_uuid, string $label): int
    {
        $this->updatedClusterId = $cluster_uuid;
        $this->updatedLabel = $label;
        return $this->nextUpdateRows;
    }

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
    public int $touchCount = 0;

    public function touch_local_curation_marker(string $tenant_id): void
    {
        $this->touchCount++;
    }
}
