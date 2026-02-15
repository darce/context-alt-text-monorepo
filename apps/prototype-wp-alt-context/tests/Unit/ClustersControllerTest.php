<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersController;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\ClustersController
 */
class ClustersControllerTest extends TestCase
{
    private ClustersController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->controller = new ClustersController();
    }

    public function testRegisterRoutesIncludesReadOnlyClusterSurfaces(): void
    {
        $this->controller->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains('/recognition/clusters', $routes);
        $this->assertContains('/recognition/clusters/top-unlabeled', $routes);
        $this->assertContains('/recognition/clusters/labels', $routes);
        $this->assertContains('/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)', $routes);
        $this->assertContains('/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/members', $routes);

        $this->assertNotContains('/recognition/clusters/reassign', $routes);
        $this->assertNotContains('/recognition/media-identities', $routes);
    }

    public function testTopUnlabeledClustersHydrateThumbnailFallbacks(): void
    {
        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                [
                    'id' => 'cluster-1',
                    'representatives' => [
                        [
                            'id' => 'rep-1',
                            'media_id' => 101,
                            'thumb_url' => null,
                        ],
                        [
                            'id' => 'rep-2',
                            'media_id' => 202,
                            'thumbnail_url' => 'http://example.test/media/legacy-202.jpg',
                        ],
                    ],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $this->controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        $this->assertSame('http://example.test/media/101.jpg', $data[0]['representatives'][0]['thumb_url']);
        $this->assertSame('http://example.test/media/legacy-202.jpg', $data[0]['representatives'][1]['thumb_url']);
    }

    public function testListClustersUsesLocalProjectionWhenSyncStatePresent(): void
    {
        $clustersRepo = new class() implements ClustersRepositoryInterface {
            public function merge_snapshot_for_tenant(string $tenant_id, array $clusters, int $snapshot_version): void {}
            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-local',
                        'label' => 'Local',
                        'identity_count' => 1,
                    ],
                ];
            }
            public function list_labels(string $tenant_id): array {
				return ['Local']; }
            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array {
				return []; }
            public function find_by_uuid(string $cluster_uuid): ?array {
				return null; }
        };

        $membersRepo = new class() implements IdentityMembersRepositoryInterface {
            public function merge_snapshot_for_tenant(string $tenant_id, array $members, int $snapshot_version): void {}
            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
            {
                return [
                    [
                        'identity_uuid' => 'identity-1',
                        'attachment_id' => 10,
                        'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                    ],
                ];
            }
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                $result = [];
                foreach ($cluster_uuids as $uuid) {
                    $result[$uuid] = [
                        [
                            'identity_uuid' => 'identity-1',
                            'attachment_id' => 10,
                            'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                        ],
                    ];
                }
                return $result;
            }
            public function list_for_media_ids(string $tenant_id, array $media_ids): array {
				return []; }
        };

        $syncRepo = new class() implements SyncStateRepositoryInterface {
            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void {}
            public function get_snapshot_version(string $tenant_id): int {
				return 1; }
            public function get_last_updated(string $tenant_id): ?string {
				return '2026-02-14 00:00:00'; }
        };

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, new ClusterResponseMapper(), new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertArrayHasKey('clusters', $data);
        $this->assertArrayHasKey('tenant_id', $data);
        $this->assertSame('cluster-local', $data['clusters'][0]['id']);
    }

    public function testListClustersProxiesWhenNoLocalProjection(): void
    {
        $clustersRepo = new class() implements ClustersRepositoryInterface {
            public function merge_snapshot_for_tenant(string $tenant_id, array $clusters, int $snapshot_version): void {}
            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array {
				return []; }
            public function list_labels(string $tenant_id): array {
				return []; }
            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array {
				return []; }
            public function find_by_uuid(string $cluster_uuid): ?array {
				return null; }
        };

        $membersRepo = new class() implements IdentityMembersRepositoryInterface {
            public function merge_snapshot_for_tenant(string $tenant_id, array $members, int $snapshot_version): void {}
            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array {
				return []; }
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array {
				return []; }
            public function list_for_media_ids(string $tenant_id, array $media_ids): array {
				return []; }
        };

        // Sync repo with version 0 and no updated_at triggers proxy fallback
        $syncRepo = new class() implements SyncStateRepositoryInterface {
            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void {}
            public function get_snapshot_version(string $tenant_id): int {
				return 0; }
            public function get_last_updated(string $tenant_id): ?string {
				return null; }
        };

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, new ClusterResponseMapper(), new MemberResponseMapper());

        // Queue a mock HTTP response for the proxy request
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('cluster-proxy', $data[0]['id']);
    }

    public function testGetClusterMembersProxiesWhenNoLocalProjection(): void
    {
        $clustersRepo = new class() implements ClustersRepositoryInterface {
            public function merge_snapshot_for_tenant(string $tenant_id, array $clusters, int $snapshot_version): void {}
            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array {
				return []; }
            public function list_labels(string $tenant_id): array {
				return []; }
            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array {
				return []; }
            public function find_by_uuid(string $cluster_uuid): ?array {
				return null; }
        };

        $membersRepo = new class() implements IdentityMembersRepositoryInterface {
            public function merge_snapshot_for_tenant(string $tenant_id, array $members, int $snapshot_version): void {}
            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array {
				return []; }
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array {
				return []; }
            public function list_for_media_ids(string $tenant_id, array $media_ids): array {
				return []; }
        };

        // Sync repo with version 0 and no updated_at triggers proxy fallback
        $syncRepo = new class() implements SyncStateRepositoryInterface {
            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void {}
            public function get_snapshot_version(string $tenant_id): int {
				return 0; }
            public function get_last_updated(string $tenant_id): ?string {
				return null; }
        };

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, new ClusterResponseMapper(), new MemberResponseMapper());

        // Queue a mock HTTP response for the proxy request
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['identity_uuid' => 'id-1', 'media_id' => 10],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-123/members');
        $request->set_param('cluster_id', 'cluster-123');
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('id-1', $data[0]['identity_uuid']);
    }
}
