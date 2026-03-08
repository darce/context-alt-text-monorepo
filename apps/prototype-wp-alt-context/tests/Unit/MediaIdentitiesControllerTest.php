<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\MediaIdentitiesController;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\MediaIdentitiesController
 */
class MediaIdentitiesControllerTest extends TestCase
{
    public function testMediaIdentitiesUsesLocalProjectionWhenSyncStatePresent(): void
    {
        $membersRepo = new class() implements IdentityMembersRepositoryInterface {
            public function merge_snapshot_for_tenant(string $tenant_id, array $members, int $snapshot_version): void {}
            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array {
				return []; }
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array {
				return []; }
            public function list_for_media_ids(string $tenant_id, array $media_ids): array
            {
                return [
                    [
                        'identity_uuid' => 'identity-1',
                        'attachment_id' => 22,
                        'bbox_json' => '{"pixels":{"x":1,"y":1,"width":2,"height":2}}',
                    ],
                ];
            }
        };

        $syncRepo = new class() implements SyncStateRepositoryInterface {
            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void {}
            public function get_snapshot_version(string $tenant_id): int {
					return 1; }
            public function get_last_updated(string $tenant_id): ?string {
					return '2026-02-14 00:00:00'; }
            public function touch_local_curation_marker(string $tenant_id): void {}
            public function refresh_curation_metrics(string $tenant_id): void {}
            public function get_pending_curation_operations(string $tenant_id): int {
                return 0;
            }
            public function get_conflict_count(string $tenant_id): int {
                return 0;
            }
            public function get_last_curation_acknowledged_at(string $tenant_id): ?string {
                return null;
            }
            public function get_last_curation_conflict_at(string $tenant_id): ?string {
                return null;
            }
        };

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertArrayHasKey('22', $data['identities_by_media']);
    }

    public function testMediaIdentitiesReturnsEmptyPayloadWhenProxyUnavailable(): void
    {
        $membersRepo = new class() implements IdentityMembersRepositoryInterface {
            public function merge_snapshot_for_tenant(string $tenant_id, array $members, int $snapshot_version): void {}
            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array {
                return [];
            }
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array {
                return [];
            }
            public function list_for_media_ids(string $tenant_id, array $media_ids): array {
                return [];
            }
        };

        $syncRepo = new class() implements SyncStateRepositoryInterface {
            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void {}
            public function get_snapshot_version(string $tenant_id): int {
                return 0;
            }
            public function get_last_updated(string $tenant_id): ?string {
                return null;
            }
            public function touch_local_curation_marker(string $tenant_id): void {}
            public function refresh_curation_metrics(string $tenant_id): void {}
            public function get_pending_curation_operations(string $tenant_id): int {
                return 0;
            }
            public function get_conflict_count(string $tenant_id): int {
                return 0;
            }
            public function get_last_curation_acknowledged_at(string $tenant_id): ?string {
                return null;
            }
            public function get_last_curation_conflict_at(string $tenant_id): ?string {
                return null;
            }
        };

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22, 23]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame([], $data['identities_by_media'] ?? null);
    }
}
