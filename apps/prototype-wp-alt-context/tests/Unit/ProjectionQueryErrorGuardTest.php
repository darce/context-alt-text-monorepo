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
use AltContext\Sovereign\Repositories\ClustersReadRepository;
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
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- Test harness installs a wpdb stub.
        $GLOBALS['wpdb'] = new \WPDBStub();
        $this->repository = new IdentityMembersReadRepository('wp_acx_identity_members', 'wp_acx_clusters');
    }

    protected function tearDown(): void
    {
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- Test harness installs a wpdb stub.
        $GLOBALS['wpdb'] = new \WPDBStub();
        parent::tearDown();
    }

    public function testListForClusterThrowsInsteadOfReturningEmptyOnMysqlError(): void
    {
        $this->installFailingWpdb('get_results');

        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage(self::MYSQL_ASSIGNED_AT_ERROR);

        $this->repository->list_for_cluster('cluster-broken', 10, 0, self::currentTenantId());
    }

    public function testListForClusterUuidsThrowsInsteadOfReturningEmptyOnMysqlError(): void
    {
        $this->installFailingWpdb('get_results');

        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage('identity_members.list_for_cluster_uuids');

        $this->repository->list_for_cluster_uuids(['cluster-a'], 4);
    }

    public function testGuardLogsViaTelemetryAndClearsLastError(): void
    {
        $wpdb = $this->installFailingWpdb('get_results');
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
                $message = 'Projection query failed [identity_members.list_for_cluster]: '
                    . ProjectionQueryErrorGuardTest::MYSQL_ASSIGNED_AT_ERROR;

                // phpcs:ignore WordPress.Security.EscapeOutput.ExceptionNotEscaped -- Internal diagnostic message; never rendered as output.
                throw new ProjectionQueryException($message);
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
        // BR-10: REST surface must not leak raw MySQL / schema internals.
        $this->assertStringNotContainsString(self::MYSQL_ASSIGNED_AT_ERROR, $response->get_error_message());
        $this->assertStringNotContainsString('assigned_at', $response->get_error_message());
        $this->assertStringNotContainsString('wp_acx_', $response->get_error_message());
        $this->assertSame(0, $repairCalls, 'repair must not fire when the cause is a query error');
    }

    public function testListClusterLabelsReturnsTypedErrorOnProjectionQueryFailure(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function list_labels(string $tenant_id, string $search = '', int $limit = self::DEFAULT_LIST_LIMIT): array
            {
                throw new ProjectionQueryException('Projection query failed [clusters.list_labels]: broken');
            }
        };
        $service = $this->makeService($clustersRepo, new NullIdentityMembersRepository());

        $response = $service->list_cluster_labels(new WP_REST_Request('GET', '/clusters/labels'));

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('acx_projection_query_failed', $response->get_error_code());
        $this->assertStringContainsString('list_cluster_labels', $response->get_error_message());
    }

    public function testPrepareFailureThrowsInsteadOfReturningEmpty(): void
    {
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- Test harness installs a wpdb stub.
        $GLOBALS['wpdb'] = new class() {
            public string $prefix = 'wp_';
            public string $last_error = '';
            public function has_cap(string $cap): bool {
				return true; }
            public function prepare(string $query, ...$args) {
				return false; }
            public function get_results($query, $output = OBJECT): array {
				return []; }
        };

        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage('prepare_query');
        $this->repository->list_for_cluster('cluster-1', 10, 0, self::currentTenantId());
    }

    public function testSuccessfulQueryIgnoresStaleLastError(): void
    {
        global $wpdb;
        $wpdb->last_error = 'stale unrelated error';
        $wpdb->mockResults = [];

        $this->assertSame([], $this->repository->list_for_cluster('cluster-1', 10, 0, self::currentTenantId()));
    }

    /** @dataProvider readEndpointMethods */
    public function testProjectionAvailabilityFailureDegradesEveryReadEndpoint(string $method, array $params): void
    {
        $host = new class() implements ClustersHostInterface {
            public function get_tenant_id(): string {
				return 'tenant-1'; }
            public function proxy_recognition_request(string $method, string $path, array $body = [], array $query = [], string $request_class = 'auto', string $body_kind = 'json', ?int $max_body_bytes = null): WP_REST_Response|WP_Error
            {
                return new WP_REST_Response([], 200);
            }
            public function host_should_use_local_projection_gate(SyncStateRepositoryInterface $sync_state_repository, string $tenant_id): bool {
				return false; }
            public function host_is_projection_stale(?string $updated_at): bool {
				return false; }
        };
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                throw new ProjectionQueryException('Projection query failed [clusters.has_projection_rows_for_tenant]: broken');
            }
        };
        $membersRepo = new NullIdentityMembersRepository();
        $projectionSync = new ClusterProjectionSyncService($host, self::BOOTSTRAP_HOOK, $clustersRepo, $membersRepo, new NullSyncStateRepository());
        $service = new ClusterReadService($host, new ClusterReadDependencies(
            $clustersRepo,
            $membersRepo,
            new ClusterFacade($clustersRepo, $membersRepo),
            new ClusterResponseMapper(),
            new MemberResponseMapper(),
            $projectionSync,
            new ClusterResponseEnvelopeService(),
            new ClusterReadConfig(self::BOOTSTRAP_HOOK, 'backend_proxy', 'local_projection', 'unavailable', 'bootstrapping', 'available')
        ));
        $request = new WP_REST_Request('GET', '/clusters');
        foreach ($params as $key => $value) {
            $request->set_param($key, $value);
        }

        $response = $service->{$method}($request);

        $this->assertTrue($response instanceof WP_REST_Response || $response instanceof WP_Error);
        $this->assertNotEmpty($this->getErrorLog(), 'degrade must emit telemetry');
    }

    public static function readEndpointMethods(): array
    {
        return [
            'list clusters' => ['list_clusters', []],
            'top unlabeled' => ['list_top_unlabeled_clusters', []],
            'labels' => ['list_cluster_labels', []],
            'detail' => ['get_cluster_detail', ['cluster_id' => 'cluster-1']],
            'members' => ['get_cluster_members', ['cluster_id' => 'cluster-1']],
        ];
    }

    /**
     * E21-14-BR-17: null result with empty last_error must still throw.
     * wpdb returns null without setting last_error when !ready or query filter nullifies SQL.
     */
    public function testListForClusterThrowsOnNullResultWithoutLastError(): void
    {
        global $wpdb;
        $wpdb->get_results_returns_null = true;
        $wpdb->last_error = '';

        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage('query did not execute');

        $this->repository->list_for_cluster('cluster-null-path', 10, 0, self::currentTenantId());
    }

    /**
     * E21-14-BR-14: legitimately empty get_results must not throw.
     */
    public function testListForClusterReturnsEmptyWhenNoRowsAndNoError(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];
        $wpdb->last_error = '';
        $wpdb->get_results_returns_null = false;

        $rows = $this->repository->list_for_cluster('cluster-empty', 10, 0, self::currentTenantId());

        $this->assertSame([], $rows);
    }

    /** @dataProvider repositoryReadMethods */
    public function testEveryRepositoryReadMethodThrowsOnQueryFailure(callable $read): void
    {
        $this->installFailingWpdb('all');

        $this->expectException(ProjectionQueryException::class);
        $read();
    }

    public static function repositoryReadMethods(): array
    {
        $members = static fn(): IdentityMembersReadRepository => new IdentityMembersReadRepository('wp_acx_identity_members', 'wp_acx_clusters');
        $clusters = static fn(): ClustersReadRepository => new ClustersReadRepository('wp_acx_clusters');

        return [
            'members list_for_cluster' => [static fn() => $members()->list_for_cluster('cluster-1', 10, 0, self::currentTenantId())],
            'members list_for_cluster_uuids' => [static fn() => $members()->list_for_cluster_uuids(['cluster-1'], 4)],
            'members list_for_media_ids' => [static fn() => $members()->list_for_media_ids(self::currentTenantId(), [1])],
            'members has_projection_rows' => [static fn() => $members()->has_projection_rows_for_tenant(self::currentTenantId())],
            'members count_for_cluster' => [static fn() => $members()->count_for_cluster('cluster-1', self::currentTenantId())],
            'members find_by_identity_uuid' => [static fn() => $members()->find_by_identity_uuid('identity-1')],
            'members get_curated' => [static fn() => $members()->get_curated_members_for_tenant(self::currentTenantId())],
            'clusters list_for_tenant' => [static fn() => $clusters()->list_for_tenant(self::currentTenantId())],
            'clusters list_labels' => [static fn() => $clusters()->list_labels(self::currentTenantId())],
            'clusters has_projection_rows' => [static fn() => $clusters()->has_projection_rows_for_tenant(self::currentTenantId())],
            'clusters list_top_unlabeled' => [static fn() => $clusters()->list_top_unlabeled(self::currentTenantId())],
            'clusters count_top_unlabeled_singletons' => [static fn() => $clusters()->count_top_unlabeled_singletons(self::currentTenantId())],
            'clusters find_by_uuid' => [static fn() => $clusters()->find_by_uuid('cluster-1')],
            'clusters get_curated' => [static fn() => $clusters()->get_curated_clusters_for_tenant(self::currentTenantId())],
        ];
    }

    /**
     * E21-14-BR-08 behavioural: unguarded cluster reads used to return empty; they must throw.
     */
    public function testClustersListForTenantThrowsOnMysqlError(): void
    {
        $this->installFailingWpdb('get_results');

        $repo = new ClustersReadRepository('wp_acx_clusters');

        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage('clusters.list_for_tenant');

        $repo->list_for_tenant(self::currentTenantId(), 10, 0);
    }

    public function testClustersListForTenantThrowsOnNullWithoutLastError(): void
    {
        global $wpdb;
        $wpdb->get_results_returns_null = true;
        $wpdb->last_error = '';

        $repo = new ClustersReadRepository('wp_acx_clusters');

        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage('query did not execute');

        $repo->list_for_tenant(self::currentTenantId(), 10, 0);
    }

    public function testFindByUuidDoesNotThrowOnLegitimateNullRow(): void
    {
        global $wpdb;
        $wpdb->mockRow = null;
        $wpdb->get_row_returns_null = true;
        $wpdb->last_error = '';

        $repo = new ClustersReadRepository('wp_acx_clusters');
        $row = $repo->find_by_uuid('missing-cluster');

        $this->assertNull($row);
    }

    public function testFindByUuidThrowsWhenLastErrorSet(): void
    {
        $this->installFailingWpdb('get_row');

        $repo = new ClustersReadRepository('wp_acx_clusters');

        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage('clusters.find_by_uuid');

        $repo->find_by_uuid('broken-cluster');
    }

    public function testHasProjectionRowsThrowsWhenTotalProbeReturnsNull(): void
    {
        global $wpdb;
        $wpdb->get_var_returns_null = true;
        $wpdb->last_error = '';

        $repo = new ClustersReadRepository('wp_acx_clusters');
        $this->expectException(ProjectionQueryException::class);
        $this->expectExceptionMessage('clusters.has_projection_rows_for_tenant');
        $repo->has_projection_rows_for_tenant(self::currentTenantId());
    }

    public function testGetClusterMembersWithRealReadRepoDoesNotCollapseQueryErrorIntoEmptyList(): void
    {
        $this->installFailingWpdb('get_results');

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

    private function installFailingWpdb(string $method): \WPDBStub
    {
        $wpdb = new class($method) extends \WPDBStub {
            public function __construct(private string $method) {}

            public function get_results($query, $output = OBJECT)
            {
                if ('all' === $this->method || 'get_results' === $this->method) {
                    $this->last_error = ProjectionQueryErrorGuardTest::MYSQL_ASSIGNED_AT_ERROR;
                    return null;
                }
                return parent::get_results($query, $output);
            }

            public function get_row($query, $output = OBJECT, $y = 0)
            {
                if ('all' === $this->method || 'get_row' === $this->method) {
                    $this->last_error = ProjectionQueryErrorGuardTest::MYSQL_ASSIGNED_AT_ERROR;
                    return null;
                }
                return parent::get_row($query, $output, $y);
            }

            public function get_var($query, $x = 0, $y = 0)
            {
                if ('all' === $this->method || 'get_var' === $this->method) {
                    $this->last_error = ProjectionQueryErrorGuardTest::MYSQL_ASSIGNED_AT_ERROR;
                    return null;
                }
                return parent::get_var($query, $x, $y);
            }
        };
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- Test harness installs a wpdb stub.
        $GLOBALS['wpdb'] = $wpdb;
        return $wpdb;
    }
}
