<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\ClusterMutationsController
 */
class ClusterMutationsControllerDualWriteTest extends TestCase
{
    private ClusterMutationsController $controller;
    private ClusterMutationsRepositorySpy $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClusterMutationsRepositorySpy();
        $this->controller = new ClusterMutationsController($this->repository);
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
    }
}

class ClusterMutationsRepositorySpy extends NullClustersRepository
{
    public string $updatedClusterId = '';
    public string $updatedLabel = '';
    public string $dismissedClusterId = '';
    public string $undismissedClusterId = '';

    public function update_label(string $cluster_uuid, string $label): void
    {
        $this->updatedClusterId = $cluster_uuid;
        $this->updatedLabel = $label;
    }

    public function dismiss(string $cluster_uuid): void
    {
        $this->dismissedClusterId = $cluster_uuid;
    }

    public function undismiss(string $cluster_uuid): void
    {
        $this->undismissedClusterId = $cluster_uuid;
    }
}
