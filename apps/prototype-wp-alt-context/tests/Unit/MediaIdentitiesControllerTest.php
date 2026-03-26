<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\MediaIdentitiesController;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\MediaIdentitiesController
 */
class MediaIdentitiesControllerTest extends TestCase
{
    public function testMediaIdentitiesUsesLocalProjectionWhenSyncStatePresent(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
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

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
					return 1; }
            public function get_last_updated(string $tenant_id): ?string {
					return '2026-02-14 00:00:00'; }
        };

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertArrayHasKey('22', $data['identities_by_media']);
        $this->assertSame('local_projection', $data['data_source'] ?? null);
    }

    public function testMediaIdentitiesReturnsEmptyPayloadWhenProxyUnavailable(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_media_ids(string $tenant_id, array $media_ids): array {
                return [];
            }
        };

        $syncRepo = new NullSyncStateRepository();

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
        $this->assertSame('unavailable', $data['data_source'] ?? null);
    }

    public function testMediaIdentitiesPropagatesBackendOverloadedAs503(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_media_ids(string $tenant_id, array $media_ids): array {
                return [];
            }
        };

        $syncRepo = new NullSyncStateRepository();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());
        $this->queueHttpResponse([
            'response' => ['code' => 503, 'message' => 'Service Unavailable'],
            'headers' => ['Retry-After' => '5'],
            'body' => '{"error":"database_unavailable","trace_id":"trace-1","path":"/recognition/media/identities"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22, 23]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(503, $response->get_status());
        $this->assertSame(['error' => 'backend_overloaded', 'retry_after' => 5], $response->get_data());
        $this->assertSame('5', $response->get_headers()['Retry-After'] ?? null);
    }

    public function testMediaIdentitiesAnnotatesBackendProxyResponses(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_media_ids(string $tenant_id, array $media_ids): array {
                return [];
            }
        };

        $syncRepo = new NullSyncStateRepository();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"identity_id":"identity-1","media_id":22}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('backend_proxy', $data['data_source'] ?? null);
        $this->assertArrayHasKey('22', $data['identities_by_media'] ?? []);
        $this->assertSame(10, $this->getHttpCalls()[0]['args']['timeout'] ?? null);
    }

    public function testMediaIdentitiesFallsBackToBackendProxyWhenSyncStateExistsButProjectionRowsAreMissing(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return false;
            }
        };

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 4;
            }
            public function get_last_updated(string $tenant_id): ?string {
                return '2026-03-26 12:00:00';
            }
        };

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"identity_id":"identity-1","media_id":22}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('backend_proxy', $data['data_source'] ?? null);
        $this->assertArrayHasKey('22', $data['identities_by_media'] ?? []);
    }
}
