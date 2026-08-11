<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersHostInterface;
use AltContext\Api\Services\ClusterProjectionSyncService;
use AltContext\Api\Services\ClusterReadConfig;
use AltContext\Api\Services\ClusterReadDependencies;
use AltContext\Api\Services\ClusterReadService;
use AltContext\Api\Services\ClusterResponseEnvelopeService;
use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Repositories\IdentityMembersReadRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\Stubs\SpySyncPullJob;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * Behavioural guards for swallowed MySQL errors on sovereign reads (E21-14 Slice 2).
 *
 * These tests drive a failing $wpdb (null result + last_error) — they go red
 * against the pre-fix pattern that coerced null to []. TEST-15 / RLSE-05.
 *
 * @covers \AltContext\Sovereign\Repositories\PreparesSqlQueries
 * @covers \AltContext\Sovereign\Repositories\IdentityMembersReadRepository
 * @covers \AltContext\Api\Services\ClusterReadService
 */
class ProjectionQueryErrorGuardTest extends TestCase
{
    public const MYSQL_ASSIGNED_AT_ERROR = "Unknown column 'm.assigned_at' in 'order clause'";

    private const BOOTSTRAP_HOOK = 'acx_bootstrap_sync_projection_guard_test';

    private IdentityMembersReadRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new IdentityMembersReadRepository('wp_acx_identity_members', 'wp_acx_clusters');
    }

    public function testListForClusterThrowsInsteadOfReturningEmptyOnMysqlError(): void
    {
        global $wpdb;
        $wpdb->get_results_returns_null = true;
        $wpdb->last_error = self::MYSQL_ASSIGNED_AT_ERROR;

        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage(self::MYSQL_ASSIGNED_AT_ERROR);

        $this->repository->list_for_cluster('cluster-broken', 10, 0, self::currentTenantId());
    }

    public function testListForClusterUuidsThrowsInsteadOfReturningEmptyOnMysqlError(): void
    {
        global $wpdb;
        $wpdb->get_results_returns_null = true;
        $wpdb->last_error = self::MYSQL_ASSIGNED_AT_ERROR;

        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage('identity_members.list_for_cluster_uuids');

        $this->repository->list_for_cluster_uuids(['cluster-a'], 4);
    }

    public function testGuardLogsViaTelemetryAndClearsLastError(): void
    {
        global $wpdb;
        $wpdb->get_results_returns_null = true;
        $wpdb->last_error = self::MYSQL_ASSIGNED_AT_ERROR;
        $GLOBALS['__ac_error_log'] = [];

        try {
            $this->repository->list_for_cluster('cluster-log', 5, 0, self::currentTenantId());
            $this->fail('Expected ProjectionQueryException');
        } catch (ProjectionQueryException $exception) {
            $this->assertStringContainsString(self::MYSQL_ASSIGNED_AT_ERROR, $exception->getMessage());
        }

        $log = $this->getErrorLog();
        $this->assertNotEmpty($log, 'Telemetry::log_line must record the MySQL error');
        $joined = implode("\n", $log);
        $this->assertStringContainsString(self::MYSQL_ASSIGNED_AT_ERROR, $joined);
        $this->assertStringContainsString('identity_members.list_for_cluster', $joined);
        $this->assertSame('', $wpdb->last_error, 'last_error must be cleared after the guard records it');
    }

    public function testGetClusterMembersReturnsTypedErrorNotEmptyPayload(): void
    {
        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster(
                string $cluster_uuid,
                int $limit = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT,
                int $offset = 0,
                ?string $tenant_id = null
            ): array {
                throw new ProjectionQueryException(
                    'Projection query failed [identity_members.list_for_cluster]: '
                    . ProjectionQueryErrorGuardTest::MYSQL_ASSIGNED_AT_ERROR
                );
            }
        };

        $clustersRepo = new class() extends NullClustersRepository {
            public function find_by_uuid(string $cluster_uuid): ?array
            {
                return [
                    'cluster_uuid' => $cluster_uuid,
                    'identity_count' => 5,
                    'label' => 'Broken',
                ];
            }
        };

        $repairCalls = 0;
        $service = $this->makeService(
            $clustersRepo,
            $membersRepo,
            static function () use (&$repairCalls): bool {
                $repairCalls++;
                return true;
            }
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-broken/members');
        $request->set_param('cluster_id', 'cluster-broken');

        $response = $service->get_cluster_members($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('acx_projection_query_failed', $response->get_error_code());
        $this->assertSame(500, (int) ($response->get_error_data()['status'] ?? 0));
        $this->assertStringContainsString('get_cluster_members', $response->get_error_message());
        $this->assertStringContainsString(self::MYSQL_ASSIGNED_AT_ERROR, $response->get_error_message());
        $this->assertSame(0, $repairCalls, 'repair must not fire when the cause is a query error');
    }

    public function testGetClusterMembersWithRealReadRepoDoesNotCollapseQueryErrorIntoEmptyList(): void
    {
        global $wpdb;
        $wpdb->get_results_returns_null = true;
        $wpdb->last_error = self::MYSQL_ASSIGNED_AT_ERROR;

        $readRepo = new IdentityMembersReadRepository('wp_acx_identity_members', 'wp_acx_clusters');
        $membersRepo = new class($readRepo) extends NullIdentityMembersRepository {
            public function __construct(private IdentityMembersReadRepository $inner)
            {
            }

            public function list_for_cluster(
                string $cluster_uuid,
                int $limit = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT,
                int $offset = 0,
                ?string $tenant_id = null
            ): array {
                return $this->inner->list_for_cluster($cluster_uuid, $limit, $offset, $tenant_id);
            }
        };

        $clustersRepo = new class() extends NullClustersRepository {
            public function find_by_uuid(string $cluster_uuid): ?array
            {
                return [
                    'cluster_uuid' => $cluster_uuid,
                    'identity_count' => 5,
                    'label' => 'Broken',
                ];
            }
        };

        $service = $this->makeService($clustersRepo, $membersRepo);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-broken/members');
        $request->set_param('cluster_id', 'cluster-broken');

        $response = $service->get_cluster_members($request);

        $this->assertInstanceOf(WP_Error::class, $response, 'Must not return a 200 empty members envelope');
        $this->assertNotInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('acx_projection_query_failed', $response->get_error_code());
    }

    /**
     * @param callable():bool|null $on_repair
     */
    private function makeService(
        NullClustersRepository $clusters_repository,
        IdentityMembersRepositoryInterface $members_repository,
        ?callable $on_repair = null
    ): ClusterReadService {
        $host = new class() implements ClustersHostInterface {
            public function get_tenant_id(): string
            {
                return 'tenant-1';
            }

            public function proxy_recognition_request(
                string $method,
                string $path,
                array $body = [],
                array $query = [],
                string $request_class = 'auto',
                string $body_kind = 'json',
                ?int $max_body_bytes = null
            ): WP_REST_Response|WP_Error {
                return new WP_REST_Response([], 200);
            }

            public function host_should_use_local_projection_gate(
                SyncStateRepositoryInterface $sync_state_repository,
                string $tenant_id
            ): bool {
                return true;
            }

            public function host_is_projection_stale(?string $updated_at): bool
            {
                return false;
            }
        };

        $projectionSync = new class(
            $host,
            self::BOOTSTRAP_HOOK,
            $clusters_repository,
            $members_repository,
            new NullSyncStateRepository(),
            new SpySyncPullJob(),
            $on_repair
        ) extends ClusterProjectionSyncService {
            /** @var callable|null */
            private $on_repair_cb;

            public function __construct(
                ClustersHostInterface $host,
                string $bootstrap_hook,
                $clusters_repository,
                $members_repository,
                SyncStateRepositoryInterface $sync_state_repository,
                $sync_pull_job,
                ?callable $on_repair
            ) {
                parent::__construct(
                    $host,
                    $bootstrap_hook,
                    $clusters_repository,
                    $members_repository,
                    $sync_state_repository,
                    $sync_pull_job,
                    null
                );
                $this->on_repair_cb = $on_repair;
            }

            public function should_use_local_projection(string $tenant_id): bool
            {
                return true;
            }

            public function cluster_row_should_have_members(array $cluster_row): bool
            {
                return true;
            }

            public function repair_targeted_projection(string $tenant_id, array $cluster_ids): bool
            {
                if (null !== $this->on_repair_cb) {
                    return (bool) ($this->on_repair_cb)();
                }

                return false;
            }
        };

        $dependencies = new ClusterReadDependencies(
            $clusters_repository,
            $members_repository,
            new ClusterFacade($clusters_repository, $members_repository),
            new ClusterResponseMapper(),
            new MemberResponseMapper(),
            $projectionSync,
            new ClusterResponseEnvelopeService(),
            new ClusterReadConfig(
                self::BOOTSTRAP_HOOK,
                'backend_proxy',
                'local_projection',
                'unavailable',
                'bootstrapping',
                'available'
            )
        );

        return new ClusterReadService($host, $dependencies);
    }
}
