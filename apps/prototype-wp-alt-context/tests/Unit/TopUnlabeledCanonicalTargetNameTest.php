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
 * Top-unlabeled suggestions must resolve their target's current canonical name
 * from the same tenant's cluster row, never from the source's stale inferred label.
 *
 * The source row is unlabeled and carries a stale suggested_label. Only the
 * target lookup seam (ClustersRepositoryInterface::find_by_uuid) is faked.
 *
 * @covers \AltContext\Api\Services\ClusterReadService
 */
class TopUnlabeledCanonicalTargetNameTest extends TestCase
{
    private const BOOTSTRAP_HOOK = 'acx_bootstrap_sync_test';
    private const TENANT_ID = 'tenant-1';
    private const SOURCE_ID = 'cluster-912073b6';
    private const TARGET_ID = 'cluster-210cc5f8';
    private const STALE_LABEL = 'Gilded Cypress';
    private const CANONICAL_LABEL = 'Ellyn Heald';
    private const FOREIGN_LABEL = 'Foreign Person';

    public function testSameTenantCanonicalTargetNameReplacesStaleInferredLabel(): void
    {
        $response = $this->listTopUnlabeled($this->canonicalTargetLookup());

        $cluster = $this->onlyCluster($response);
        $this->assertSame(self::CANONICAL_LABEL, $cluster['suggested_label']);
    }

    public function testSameTenantTargetKeepsIdConfidenceAndSourceWhileSourceStaysPending(): void
    {
        $response = $this->listTopUnlabeled($this->canonicalTargetLookup());

        $cluster = $this->onlyCluster($response);
        $this->assertSame(self::TARGET_ID, $cluster['suggested_target_cluster_id']);
        $this->assertEqualsWithDelta(0.616598, $cluster['suggested_label_confidence'], 1e-9);
        $this->assertSame('label_inference', $cluster['suggested_label_source']);
        $this->assertFalse($cluster['is_labeled']);
        $this->assertFalse($cluster['user_confirmed']);
        $this->assertNotSame(self::CANONICAL_LABEL, $cluster['label']);
    }

    public function testDeletedTargetIsNotClaimedAsValidNorStaleLabelPrefilled(): void
    {
        $response = $this->listTopUnlabeled(static fn (string $cluster_uuid): ?array => null);

        $cluster = $this->onlyCluster($response);
        $this->assertNull($cluster['suggested_target_cluster_id']);
        $this->assertNull($cluster['suggested_label']);
    }

    public function testForeignTenantTargetIsNotClaimedAsValid(): void
    {
        $response = $this->listTopUnlabeled($this->foreignTargetLookup());

        $cluster = $this->onlyCluster($response);
        $this->assertNull($cluster['suggested_target_cluster_id']);
        $this->assertNull($cluster['suggested_label']);
    }

    public function testForeignTenantTargetNameNeverLeaksIntoPayload(): void
    {
        $response = $this->listTopUnlabeled($this->foreignTargetLookup());

        $this->onlyCluster($response);
        $this->assertStringNotContainsString(self::FOREIGN_LABEL, (string) json_encode($response->get_data()));
    }

    public function testTargetLookupFailureRemainsErrorNotEmptyList(): void
    {
        $response = $this->listTopUnlabeled(static function (string $cluster_uuid): ?array {
            throw new ProjectionQueryException('Projection query failed [clusters.find_by_uuid]: broken');
        });

        $this->assertInstanceOf(WP_Error::class, $response);
    }

    /**
     * @param \Closure(string): ?array<string,mixed> $lookup
     * @return WP_REST_Response|WP_Error
     */
    private function listTopUnlabeled(\Closure $lookup): WP_REST_Response|WP_Error
    {
        $clustersRepo = new class(self::sourceRows(), $lookup) extends NullClustersRepository {
            /**
             * @param list<array<string,mixed>> $sourceRows
             * @param \Closure(string): ?array<string,mixed> $lookup
             */
            public function __construct(private array $sourceRows, private \Closure $lookup)
            {
            }

            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return $this->sourceRows;
            }

            public function find_by_uuid(string $cluster_uuid): ?array
            {
                return ($this->lookup)($cluster_uuid);
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                $members = [];
                foreach ($cluster_uuids as $cluster_uuid) {
                    $members[$cluster_uuid] = [
                        ['identity_uuid' => $cluster_uuid . '-a', 'attachment_id' => 1],
                        ['identity_uuid' => $cluster_uuid . '-b', 'attachment_id' => 2],
                    ];
                }

                return $members;
            }
        };

        return $this->makeService($clustersRepo, $membersRepo)
            ->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
    }

    /**
     * @return array<string,mixed>
     */
    private function onlyCluster(WP_REST_Response|WP_Error $response): array
    {
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $clusters = $response->get_data()['clusters'];
        $this->assertCount(1, $clusters);

        return $clusters[0];
    }

    /**
     * @return list<array<string,mixed>>
     */
    private static function sourceRows(): array
    {
        return [
            [
                'cluster_uuid' => self::SOURCE_ID,
                'tenant_id' => self::TENANT_ID,
                'label' => '',
                'identity_count' => 2,
                'is_user_confirmed' => 0,
                'suggested_label' => self::STALE_LABEL,
                'suggested_label_source' => 'label_inference',
                'suggested_label_confidence' => 0.616598,
                'suggested_target_cluster_id' => self::TARGET_ID,
            ],
        ];
    }

    /**
     * @return \Closure(string): ?array<string,mixed>
     */
    private function canonicalTargetLookup(): \Closure
    {
        return static fn (string $cluster_uuid): ?array => self::TARGET_ID === $cluster_uuid ? [
            'cluster_uuid' => self::TARGET_ID,
            'tenant_id' => self::TENANT_ID,
            'label' => self::CANONICAL_LABEL,
            'is_user_confirmed' => 1,
            'person_uuid' => 'person-ellyn',
            'person_id' => 7,
            'identity_count' => 47,
        ] : null;
    }

    /**
     * @return \Closure(string): ?array<string,mixed>
     */
    private function foreignTargetLookup(): \Closure
    {
        return static fn (string $cluster_uuid): ?array => self::TARGET_ID === $cluster_uuid ? [
            'cluster_uuid' => self::TARGET_ID,
            'tenant_id' => 'tenant-foreign',
            'label' => self::FOREIGN_LABEL,
            'is_user_confirmed' => 1,
            'person_uuid' => 'person-foreign',
            'person_id' => 9,
            'identity_count' => 3,
        ] : null;
    }

    private function makeService(NullClustersRepository $clustersRepo, NullIdentityMembersRepository $membersRepo): ClusterReadService
    {
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
                return new WP_Error('unexpected', 'must stay local');
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

        $projectionSync = new ClusterProjectionSyncService(
            $host,
            self::BOOTSTRAP_HOOK,
            $clustersRepo,
            $membersRepo,
            new NullSyncStateRepository(),
            new SpySyncPullJob(),
            null
        );

        $dependencies = new ClusterReadDependencies(
            $clustersRepo,
            $membersRepo,
            new ClusterFacade($clustersRepo, $membersRepo),
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
