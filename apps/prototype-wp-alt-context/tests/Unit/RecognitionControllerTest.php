<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * Tests for RecognitionController batch limit validation.
 *
 * @covers \AltContext\Api\RecognitionController
 */
class RecognitionControllerTest extends TestCase
{
    private RecognitionController $controller;

    protected function setUp(): void
    {
        parent::setUp();

        // Set up recognition URL so controller doesn't fail on missing config
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_tier', 'free');

        $this->controller = new RecognitionController();
    }

    /**
     * Test that batch limits allow up to 10000 items for MVP.
     *
     * This test ensures we don't regress to the old 50-item limit.
     * See: docs/tasks/4.0/4.11.0/stability-audit-2026-01-20.md
     */
    public function testBatchLimitAllows100Items(): void
    {
        // Generate 100 media IDs
        $mediaIds = range(1, 100);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        // Validate should pass (not return WP_Error)
        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(
            $result === true,
            'Batch of 100 items should pass validation (old limit was 50)'
        );
    }

    public function testDefaultCompositionWiresSyncJobAndSharedSyncStateRepository(): void
    {
        $controller = new RecognitionController();
        $recognitionReflection = new \ReflectionClass($controller);

        $clustersControllerProperty = $recognitionReflection->getProperty('clustersController');
        $clustersController = $clustersControllerProperty->getValue($controller);

        $clusterMutationsControllerProperty = $recognitionReflection->getProperty('clusterMutationsController');
        $clusterMutationsController = $clusterMutationsControllerProperty->getValue($controller);

        $clustersControllerReflection = new \ReflectionClass($clustersController);
        $syncPullJobProperty = $clustersControllerReflection->getProperty('sync_pull_job');
        $syncPullJob = $syncPullJobProperty->getValue($clustersController);
        $this->assertNotNull($syncPullJob);

        $clustersSyncStateProperty = $clustersControllerReflection->getProperty('sync_state_repository');
        $clustersSyncState = $clustersSyncStateProperty->getValue($clustersController);

        $mutationsReflection = new \ReflectionClass($clusterMutationsController);
        $mutationsSyncStateProperty = $mutationsReflection->getProperty('sync_state_repository');
        $mutationsSyncState = $mutationsSyncStateProperty->getValue($clusterMutationsController);

        $this->assertSame($clustersSyncState, $mutationsSyncState);
    }

    /**
     * Test that batch limits allow significantly more than old 50 limit.
     */
    public function testBatchLimitAllows500Items(): void
    {
        $mediaIds = range(1, 500);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(
            $result === true,
            'Batch of 500 items should pass validation for MVP'
        );
    }

    /**
     * Integration test: analyze_media should accept 100 items end-to-end.
     */
    public function testAnalyzeAccepts100MediaIds(): void
    {
        $mediaIds = range(1, 100);

        foreach ($mediaIds as $mediaId) {
            $GLOBALS['__ac_attachment_urls'][$mediaId] = sprintf('http://example.test/media/%d.jpg', $mediaId);
        }

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status": "queued"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $response = $this->controller->analyze_media($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $payload = json_decode($calls[0]['body'] ?? '', true);
        $this->assertIsArray($payload);
        $this->assertCount(100, $payload['media_items'] ?? []);
    }

    /**
     * Test that empty media_ids array is rejected.
     */
    public function testEmptyMediaIdsRejected(): void
    {
        $mediaIds = [];

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(is_wp_error($result), 'Empty media_ids should be rejected');
        $this->assertSame('missing_media_ids', $result->get_error_code());
    }

    /**
     * Test that non-array media_ids is rejected.
     */
    public function testNonArrayMediaIdsRejected(): void
    {
        $mediaIds = 'not-an-array';

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(is_wp_error($result), 'Non-array media_ids should be rejected');
        $this->assertSame('invalid_media_ids', $result->get_error_code());
    }

    /**
     * Test that exceeding 10000 limit is rejected.
     */
    public function testExceedingMaxLimitRejected(): void
    {
        // Generate more than max allowed
        $mediaIds = range(1, 10001);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(is_wp_error($result), 'Exceeding 10000 items should be rejected');
        $this->assertSame('too_many_media_ids', $result->get_error_code());
    }

    public function testDismissClusterProxiesToBackend(): void
    {
        $clusterId = 'eb3d26d3-dbb6-4c99-be66-068e1f3b82ae';
        $this->queueHttpResponse([
            'response' => ['code' => 204, 'message' => 'No Content'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/' . $clusterId . '/dismiss');
        $request->set_param('cluster_id', $clusterId);

        $response = $this->controller->dismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(204, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('POST', $calls[0]['method']);
        $this->assertStringContainsString('/recognition/clusters/' . $clusterId . '/dismiss', $calls[0]['url']);
        $this->assertStringContainsString('tenant_id=', $calls[0]['url']);

        $this->assertTrue($calls[0]['body'] === null || $calls[0]['body'] === '');
    }

    public function testUndismissClusterProxiesToBackend(): void
    {
        $clusterId = 'eb3d26d3-dbb6-4c99-be66-068e1f3b82ae';
        $this->queueHttpResponse([
            'response' => ['code' => 204, 'message' => 'No Content'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('DELETE', '/acx/v1/recognition/clusters/' . $clusterId . '/dismiss');
        $request->set_param('cluster_id', $clusterId);

        $response = $this->controller->undismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(204, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('DELETE', $calls[0]['method']);
        $this->assertStringContainsString('/recognition/clusters/' . $clusterId . '/dismiss', $calls[0]['url']);
        $this->assertStringContainsString('tenant_id=', $calls[0]['url']);

        $this->assertTrue($calls[0]['body'] === null || $calls[0]['body'] === '');
    }

    public function testRegisterRoutesIncludesMediaIdentitiesIncludeDebugArg(): void
    {
        $this->controller->register_routes();

        $route = $this->findRegisteredRoute('/recognition/media-identities', 'GET');

        $this->assertNotNull($route);
        $this->assertArrayHasKey('args', $route);
        $this->assertArrayHasKey('args', $route['args']);
        $this->assertArrayHasKey('include_debug', $route['args']['args']);
        $this->assertSame('string', $route['args']['args']['include_debug']['type']);
        $this->assertFalse($route['args']['args']['include_debug']['required']);
    }

    public function testRegisterRoutesDoesNotExposeRemovedSurfaces(): void
    {
        $this->controller->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertNotContains('/recognition/training-stage', $routes);
        $this->assertNotContains('/recognition/clusters/recover-orphans', $routes);
        $this->assertNotContains('/recognition/clusters/events', $routes);
    }

    public function testGetMediaIdentitiesForwardsIncludeDebugQueryWhenTruthy(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [1001]);
        $request->set_param('include_debug', 'true');

        $response = $this->controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);

        $query = [];
        $queryString = parse_url($calls[0]['url'], PHP_URL_QUERY);
        parse_str(is_string($queryString) ? $queryString : '', $query);

        $this->assertSame('true', $query['include_debug'] ?? null);
    }

    public function testUpdateClusterLabelTriggersXmpRefreshForClusterMembers(): void
    {
        $clusterId = '5bc82b54-e3ca-41f9-a665-87f57ab2b3ce';
        $captured = [];

        add_action(
            'acx_recognition_complete',
            static function ($attachmentId, $context) use (&$captured): void {
                $captured[] = [(int) $attachmentId, (string) $context];
            },
            10,
            2
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $clusterId,
                'label' => 'Daniel',
            ]),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['identity_id' => 'a', 'media_id' => 501],
                ['identity_id' => 'b', 'media_id' => 502],
            ]),
        ]);

        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/' . $clusterId);
        $request->set_param('cluster_id', $clusterId);
        $request->set_param('label', 'Daniel');

        $response = $this->controller->update_cluster_label($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame([], $captured);
        $this->assertNotFalse(
            wp_next_scheduled('acx_refresh_xmp_for_clusters', [[$clusterId], 'cluster-label-update'])
        );

        do_action('acx_refresh_xmp_for_clusters', [$clusterId], 'cluster-label-update');

        $this->assertSame(
            [
                [501, 'cluster-label-update'],
                [502, 'cluster-label-update'],
            ],
            $captured
        );
    }

    public function testReassignClusterIdentityTriggersXmpRefreshForSourceAndTargetClusters(): void
    {
        $sourceClusterId = '92b407ec-2768-4ff3-90e4-e33afbf7c609';
        $targetClusterId = '19734ad5-4d95-4077-a711-8e407a9dd9ff';
        $captured = [];

        add_action(
            'acx_recognition_complete',
            static function ($attachmentId, $context) use (&$captured): void {
                $captured[] = [(int) $attachmentId, (string) $context];
            },
            10,
            2
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'identity_id' => 'f30df8eb-4946-4a09-9df9-b5d74e8e0d1d',
                'source_cluster_id' => $sourceClusterId,
                'target_cluster_id' => $targetClusterId,
            ]),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['identity_id' => 'm1', 'media_id' => 601],
                ['identity_id' => 'm2', 'media_id' => 602],
            ]),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'members' => [
                    ['identity_id' => 'm3', 'media_id' => 602],
                    ['identity_id' => 'm4', 'media_id' => 603],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/reassign');
        $request->set_param('identity_id', 'f30df8eb-4946-4a09-9df9-b5d74e8e0d1d');
        $request->set_param('target_cluster_id', $targetClusterId);

        $response = $this->controller->reassign_cluster_identity($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame([], $captured);
        $this->assertNotFalse(
            wp_next_scheduled('acx_refresh_xmp_for_clusters', [[$sourceClusterId, $targetClusterId], 'cluster-reassign'])
        );

        do_action('acx_refresh_xmp_for_clusters', [$sourceClusterId, $targetClusterId], 'cluster-reassign');

        $this->assertSame(
            [
                [601, 'cluster-reassign'],
                [602, 'cluster-reassign'],
                [603, 'cluster-reassign'],
            ],
            $captured
        );
    }

    public function testMergeClusterSchedulesAsyncXmpRefresh(): void
    {
        $sourceClusterId = '6f83f4e9-fe44-49d0-9ed9-62581f5a6ddf';
        $targetClusterId = '2e489e1d-0f64-4694-9082-5779d6cc7e52';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode(['merged' => true]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/' . $sourceClusterId . '/merge');
        $request->set_param('source_id', $sourceClusterId);
        $request->set_param('target_cluster_id', $targetClusterId);

        $response = $this->controller->merge_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertNotFalse(
            wp_next_scheduled('acx_refresh_xmp_for_clusters', [[$sourceClusterId, $targetClusterId], 'cluster-merge'])
        );
    }

    public function testSplitClusterSchedulesAsyncXmpRefreshIncludingNewClusterIds(): void
    {
        $clusterId = '7e2e1003-0e24-4e8c-a4d8-97ec8d269ba8';
        $newClusterA = '9b0a0e4d-2658-4eac-81f0-fba5f89e5b82';
        $newClusterB = 'dd333f66-e5fd-4c26-84a0-5f3df64d7c66';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'new_cluster_ids' => [$newClusterA, $newClusterB],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/' . $clusterId . '/split');
        $request->set_param('cluster_id', $clusterId);
        $request->set_param('n_clusters', 2);

        $response = $this->controller->split_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertNotFalse(
            wp_next_scheduled('acx_refresh_xmp_for_clusters', [[$clusterId, $newClusterA, $newClusterB], 'cluster-split'])
        );
    }

    public function testCreateClusterForIdentitySchedulesAsyncXmpRefresh(): void
    {
        $newClusterId = 'a3e8ac0f-3f7e-494c-a814-265184ceb4c2';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'cluster_id' => $newClusterId,
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/create-for-identity');
        $request->set_param('identity_id', 'd07a0e5b-0607-49dc-8b7f-8f63f6f18d2a');
        $request->set_param('label', 'Curated Name');

        $response = $this->controller->create_cluster_for_identity($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertNotFalse(
            wp_next_scheduled('acx_refresh_xmp_for_clusters', [[$newClusterId], 'cluster-create-for-identity'])
        );
    }

    public function testRevertMergeClusterSchedulesAsyncXmpRefresh(): void
    {
        $targetClusterId = 'de7e4cc7-bfe2-45f7-9c04-79f34dcd73f1';
        $sourceClusterId = '62096ccf-1c96-4de8-bf1c-2ca71411c96a';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'source_cluster_id' => $sourceClusterId,
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/revert-merge');
        $request->set_param('target_cluster_id', $targetClusterId);
        $request->set_param('moved_identity_ids', ['id-1', 'id-2']);

        $response = $this->controller->revert_merge_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertNotFalse(
            wp_next_scheduled('acx_refresh_xmp_for_clusters', [[$targetClusterId, $sourceClusterId], 'cluster-revert-merge'])
        );
    }

    /**
     * @return array<string,mixed>|null
     */
    private function findRegisteredRoute(string $route, string $method): ?array
    {
        foreach ($GLOBALS['__ac_rest_routes'] as $definition) {
            if (!is_array($definition)) {
                continue;
            }

            if (($definition['route'] ?? null) !== $route) {
                continue;
            }

            $registeredMethod = $definition['args']['methods'] ?? null;
            if ($registeredMethod === $method) {
                return $definition;
            }
        }

        return null;
    }
}
