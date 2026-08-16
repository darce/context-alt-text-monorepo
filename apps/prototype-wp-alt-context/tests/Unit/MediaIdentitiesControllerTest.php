<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Api\MediaIdentitiesController;
use AltContext\Api\RecognitionDataSource;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\SpySyncPullJob;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\MediaIdentitiesController
 */
class MediaIdentitiesControllerTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        // RECOG-1: default source flipped to 'service' with an empty default URL.
        // Pin a service target so backend-proxy paths have a non-empty effective target.
        $this->setOption('acx_recognition_url', 'https://recognition.test');
    }

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
        // BR-01: empty identities_by_media must serialize as a JSON object ({}), not [] (the workbench guard rejects arrays).
        $this->assertEquals(new \stdClass(), $data['identities_by_media'] ?? null);
        // BR-05: a transport-unreachable backend (WP_Error) is 'unavailable', distinct from a reachable 5xx 'endpoint_error'.
        $this->assertSame('unavailable', $data['data_source'] ?? null);
        // A dead backend returns the degraded state immediately and schedules no async heal.
        $this->assertSame([], $this->scheduledBootstrapEvents());
    }

    /**
     * E21-14-BR-03: projection SQL failure must become a typed WP_Error, not a PHP fatal.
     */
    public function testGetMediaIdentitiesReturnsTypedErrorOnProjectionQueryFailure(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_for_media_ids(string $tenant_id, array $media_ids): array
            {
                throw new ProjectionQueryException(
                    'Projection query failed [identity_members.list_for_media_ids]: '
                    . "Unknown column 'm.assigned_at' in 'order clause'"
                );
            }
        };

        $controller = new MediaIdentitiesController($membersRepo, new NullSyncStateRepository(), new MemberResponseMapper());
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('acx_projection_query_failed', $response->get_error_code());
        $this->assertSame(500, (int) ($response->get_error_data()['status'] ?? 0));
        $this->assertStringNotContainsString('assigned_at', $response->get_error_message());
        $this->assertStringContainsString('get_media_identities', $response->get_error_message());
    }

    /**
     * E21-14-BR-03: has_projection_rows probe failure must also surface as WP_Error.
     */
    public function testGetMediaIdentitiesReturnsTypedErrorWhenProjectionProbeFails(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                throw new ProjectionQueryException(
                    'Projection query failed [identity_members.has_projection_rows_for_tenant]: connection lost'
                );
            }
        };

        $controller = new MediaIdentitiesController($membersRepo, new NullSyncStateRepository(), new MemberResponseMapper());
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('acx_projection_query_failed', $response->get_error_code());
    }

    public function testMediaIdentitiesReturnsEndpointErrorWhenBackendReturns5xx(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_media_ids(string $tenant_id, array $media_ids): array {
                return [];
            }
        };
        $syncRepo = new NullSyncStateRepository();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());
        // A reachable backend that answers 500 (not a transport failure, not the 503 overload signal).
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error":"boom"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        // BR-05: reachable-but-erroring (5xx) is honestly labeled endpoint_error, not unavailable.
        $this->assertSame(RecognitionDataSource::ENDPOINT_ERROR, $data['data_source'] ?? null);
        // BR-01: object-shaped empty payload so the workbench renders the degraded state.
        $this->assertEquals(new \stdClass(), $data['identities_by_media'] ?? null);
    }

    /**
     * R4G-BR-09: a refused 3xx is reachable-but-bad — ENDPOINT_ERROR, not UNAVAILABLE.
     */
    public function testMediaIdentitiesReturnsEndpointErrorOnUnexpectedRedirect(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_media_ids(string $tenant_id, array $media_ids): array {
                return [];
            }
        };
        $syncRepo = new NullSyncStateRepository();
        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());

        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame(
            RecognitionDataSource::ENDPOINT_ERROR,
            $data['data_source'] ?? null,
            'refused 3xx must not be laundered as UNAVAILABLE'
        );
        $this->assertEquals(new \stdClass(), $data['identities_by_media'] ?? null);
    }

    public function testMediaIdentitiesServesLocalProjectionWithoutSyncState(): void
    {
        // The E15-35 incident state: projection rows survive, sync-state row wiped.
        $membersRepo = $this->membersRepoWithRows();
        $syncRepo = new NullSyncStateRepository();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame(RecognitionDataSource::LOCAL_PROJECTION, $data['data_source'] ?? null);
        $this->assertArrayHasKey('22', $data['identities_by_media']);
        $this->assertSame([], $this->getHttpCalls(), 'Sovereign read must issue zero HTTP requests.');
    }

    public function testMediaIdentitiesLocalReadWithMissingSyncStateSchedulesDedupedHealEvent(): void
    {
        $membersRepo = $this->membersRepoWithRows();
        $syncRepo = new NullSyncStateRepository();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $controller->get_media_identities($request);
        $controller->get_media_identities($request);

        $events = $this->scheduledBootstrapEvents();
        $this->assertCount(1, $events, 'Exactly one deduped heal event expected.');
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);
        $this->assertSame([], $this->getHttpCalls(), 'Async heal must not issue synchronous HTTP.');
    }

    public function testMediaIdentitiesLocalReadWithFreshSyncStateSchedulesNothing(): void
    {
        $membersRepo = $this->membersRepoWithRows();
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 3;
            }
            public function get_last_updated(string $tenant_id): ?string {
                return gmdate('Y-m-d H:i:s');
            }
        };

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $data = $response->get_data();
        $this->assertSame(RecognitionDataSource::LOCAL_PROJECTION, $data['data_source'] ?? null);
        $this->assertSame([], $this->scheduledBootstrapEvents());
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testMediaIdentitiesColdStartProxySuccessSchedulesAsyncBootstrap(): void
    {
        // BR-02: a successful proxy read converges the projection via the deduped
        // async cron event only. It must NOT block the response on an inline pull.
        $membersRepo = new NullIdentityMembersRepository();
        $syncRepo = new NullSyncStateRepository();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"identity_id":"identity-1","media_id":22}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $data = $response->get_data();
        $this->assertSame(RecognitionDataSource::BACKEND_PROXY, $data['data_source'] ?? null);
        // The proxy leg (post_scan_read) is the only synchronous HTTP call; convergence is off-path.
        $this->assertCount(1, $this->getHttpCalls(), 'Successful proxy read must not issue an inline convergence pull.');
        $events = $this->scheduledBootstrapEvents();
        $this->assertCount(1, $events, 'A successful proxy read schedules the deduped async bootstrap heal.');
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);
    }

    public function testMediaIdentitiesColdStartProxyReadDedupsAsyncBootstrapAcrossReads(): void
    {
        $membersRepo = new NullIdentityMembersRepository();
        $syncRepo = new NullSyncStateRepository();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper());
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"identity_id":"identity-1","media_id":22}]',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"identity_id":"identity-1","media_id":22}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $controller->get_media_identities($request);
        $events = $this->scheduledBootstrapEvents();
        $this->assertCount(1, $events, 'A successful proxy read schedules the async bootstrap heal.');
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);

        $controller->get_media_identities($request);
        $this->assertCount(1, $this->scheduledBootstrapEvents(), 'Queued event must dedup the second read.');
    }

    public function testMediaIdentitiesConvergesViaAsyncHealSoFollowUpReadServesLocalProjection(): void
    {
        // BR-02: the proxy read schedules an async heal (never an inline pull). Once
        // the cron handler completes the pull (projection rows land), follow-up reads
        // are sovereign. Here the completed heal is simulated by flipping hasRows.
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public bool $hasRows = false;
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return $this->hasRows;
            }
            public function list_for_media_ids(string $tenant_id, array $media_ids): array
            {
                if (!$this->hasRows) {
                    return [];
                }
                return [
                    [
                        'identity_uuid' => 'identity-1',
                        'attachment_id' => 22,
                        'bbox_json' => '{"pixels":{"x":1,"y":1,"width":2,"height":2}}',
                    ],
                ];
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

        $first = $controller->get_media_identities($request);
        $this->assertSame(RecognitionDataSource::BACKEND_PROXY, $first->get_data()['data_source'] ?? null);
        // The proxy read schedules the async heal but does not pull inline.
        $this->assertCount(1, $this->scheduledBootstrapEvents(), 'Proxy read must schedule the async heal.');
        $httpCallsAfterProxyRead = count($this->getHttpCalls());

        // Simulate the cron handler completing the convergence pull.
        $membersRepo->hasRows = true;

        $second = $controller->get_media_identities($request);
        $data = $second->get_data();
        $this->assertSame(RecognitionDataSource::LOCAL_PROJECTION, $data['data_source'] ?? null);
        $this->assertArrayHasKey('22', $data['identities_by_media']);
        $this->assertCount($httpCallsAfterProxyRead, $this->getHttpCalls(), 'Follow-up read must be sovereign (zero additional HTTP).');
    }

    public function testBootstrapSyncHandlerBoundInCronContextAtPluginLoad(): void
    {
        $pullJob = new SpySyncPullJob();
        $api = new Api(null, null, null, $pullJob);
        $api->init();

        // Cron context: rest_api_init is deliberately never fired.
        do_action(RecognitionDataSource::BOOTSTRAP_SYNC_HOOK, 'tenant-cron');

        $this->assertSame(['tenant-cron'], $pullJob->bypassCalls, 'Handler must perform the sync pull without rest_api_init.');
    }

    private function membersRepoWithRows(): NullIdentityMembersRepository
    {
        return new class() extends NullIdentityMembersRepository {
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
    }

    /**
     * @return array<string,array{timestamp:int,args:array<int,string>}>
     */
    private function scheduledBootstrapEvents(): array
    {
        $events = [];
        foreach (($GLOBALS['__ac_scheduled'] ?? []) as $key => $event) {
            if (str_starts_with((string) $key, RecognitionDataSource::BOOTSTRAP_SYNC_HOOK . '::')) {
                $events[$key] = $event;
            }
        }

        return $events;
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

    public function testMediaIdentitiesAnnotatesCanonicalBackendEnvelopeResponses(): void
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
            'body' => '{"identities_by_media":{"22":[{"identity_id":"identity-1","media_id":22}]}}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('backend_proxy', $data['data_source'] ?? null);
        $this->assertArrayHasKey('22', $data['identities_by_media'] ?? []);
    }

    public function testMediaIdentitiesRejectsUnexpectedObjectPayload(): void
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
            'body' => '{"items":[]}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_media_identities_payload', $response->get_error_code());
    }

    public function testMediaIdentitiesRejectsListItemsWithoutMediaId(): void
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
            'body' => '[{"identity_id":"identity-1"}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_media_identities_payload', $response->get_error_code());
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
