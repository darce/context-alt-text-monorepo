<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Api\MediaIdentitiesController;
use AltContext\Api\RecognitionDataSource;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;
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

        $pullJob = new SpySyncPullJob();
        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper(), $pullJob);
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
        // E15-37 Slice 1: a dead backend triggers neither an inline pull nor a scheduled bootstrap.
        $this->assertSame([], $pullJob->performCalls);
        $this->assertSame([], $pullJob->bypassCalls);
        $this->assertSame([], $this->scheduledBootstrapEvents());
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

    public function testMediaIdentitiesColdStartProxySuccessRunsInlineBootstrapPull(): void
    {
        $membersRepo = new NullIdentityMembersRepository();
        $syncRepo = new NullSyncStateRepository();
        $pullJob = new SpySyncPullJob();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper(), $pullJob);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"identity_id":"identity-1","media_id":22}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $data = $response->get_data();
        $this->assertSame(RecognitionDataSource::BACKEND_PROXY, $data['data_source'] ?? null);
        $this->assertSame([self::currentTenantId()], $pullJob->performCalls, 'Inline bootstrap pull expected in-request.');
        $this->assertSame([], $pullJob->bypassCalls, 'Inline leg is cooldown-gated; bypass is reserved for the cron handler.');
        $this->assertSame([], $this->scheduledBootstrapEvents(), 'No cron fallback when the inline pull succeeds.');
    }

    public function testMediaIdentitiesColdStartSchedulesDedupedFallbackWhenInlinePullFails(): void
    {
        $membersRepo = new NullIdentityMembersRepository();
        $syncRepo = new NullSyncStateRepository();
        $pullJob = new SpySyncPullJob();
        $pullJob->performResult = SyncPullResult::failed();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper(), $pullJob);
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
        $this->assertCount(1, $events, 'Failed inline pull must schedule the cron fallback.');
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);

        $controller->get_media_identities($request);
        $this->assertCount(1, $this->scheduledBootstrapEvents(), 'Queued event must dedup the second read.');
    }

    public function testMediaIdentitiesColdStartCooldownSkippedInlinePullStillSchedulesFallback(): void
    {
        $membersRepo = new NullIdentityMembersRepository();
        $syncRepo = new NullSyncStateRepository();
        $pullJob = new SpySyncPullJob();
        $pullJob->performResult = SyncPullResult::skipped();

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper(), $pullJob);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"identity_id":"identity-1","media_id":22}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $data = $response->get_data();
        $this->assertSame(RecognitionDataSource::BACKEND_PROXY, $data['data_source'] ?? null);
        $this->assertSame([self::currentTenantId()], $pullJob->performCalls);
        $events = $this->scheduledBootstrapEvents();
        $this->assertCount(1, $events, 'Cooldown-skipped inline pull must leave the deduped cron fallback scheduled.');
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);
    }

    public function testMediaIdentitiesInlinePullThrowableKeepsProxyResponseIntact(): void
    {
        $membersRepo = new NullIdentityMembersRepository();
        $syncRepo = new NullSyncStateRepository();
        $pullJob = new SpySyncPullJob();
        $pullJob->performThrows = new \RuntimeException('pull boom');

        $received = [];
        add_action('acx_sync_pull_failed', static function (array $payload) use (&$received): void {
            $received[] = $payload;
        });

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper(), $pullJob);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"identity_id":"identity-1","media_id":22}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $response = $controller->get_media_identities($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame(RecognitionDataSource::BACKEND_PROXY, $data['data_source'] ?? null);
        $this->assertArrayHasKey('22', $data['identities_by_media'] ?? []);

        $this->assertCount(1, $received, 'A throwing inline pull must fire the failure action.');
        $this->assertSame('bootstrap_after_proxy_read', $received[0]['context'] ?? null);
        $this->assertSame('pull boom', $received[0]['message'] ?? null);

        $events = $this->scheduledBootstrapEvents();
        $this->assertCount(1, $events, 'A throwing inline pull must schedule the deduped cron fallback.');
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);
    }

    public function testMediaIdentitiesColdStartProxyReadConvergesSoFollowUpReadServesLocalProjection(): void
    {
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
        $pullJob = new SpySyncPullJob();
        $pullJob->onPerform = static function () use ($membersRepo): void {
            $membersRepo->hasRows = true;
        };

        $controller = new MediaIdentitiesController($membersRepo, $syncRepo, new MemberResponseMapper(), $pullJob);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"identity_id":"identity-1","media_id":22}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/media-identities');
        $request->set_param('media_ids', [22]);

        $first = $controller->get_media_identities($request);
        $this->assertSame(RecognitionDataSource::BACKEND_PROXY, $first->get_data()['data_source'] ?? null);
        $httpCallsAfterProxyRead = count($this->getHttpCalls());

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

/**
 * Recording SyncPullJobInterface spy for Slice 1 convergence assertions.
 */
final class SpySyncPullJob implements SyncPullJobInterface
{
    /** @var list<string> */
    public array $performCalls = [];

    /** @var list<string> */
    public array $bypassCalls = [];

    public bool $succeed = true;

    public ?SyncPullResult $performResult = null;

    public ?\Throwable $performThrows = null;

    /** @var ?callable(string):void */
    public $onPerform = null;

    /** @var ?callable(string):void */
    public $onBypass = null;

    public function perform(string $tenant_id): SyncPullResult
    {
        $this->performCalls[] = $tenant_id;
        if (null !== $this->performThrows) {
            throw $this->performThrows;
        }
        if (null !== $this->onPerform) {
            ($this->onPerform)($tenant_id);
        }

        return $this->performResult ?? SyncPullResult::ok();
    }

    public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
    {
        $this->bypassCalls[] = $tenant_id;
        if (null !== $this->onBypass) {
            ($this->onBypass)($tenant_id);
        }

        return $this->succeed ? SyncPullResult::ok() : SyncPullResult::failed();
    }

    public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
    {
        return SyncPullResult::ok();
    }
}
