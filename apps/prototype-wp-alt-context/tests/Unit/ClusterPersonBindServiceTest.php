<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\ClusterMergeService;
use AltContext\Api\Services\ClusterPersonBindService;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterPersonBindService
 */
class ClusterPersonBindServiceTest extends TestCase
{
    use FindsSqlQueries;

    private const PERSON_ID = 7;
    private const PERSON_UUID = '8cb36e76-7c2c-4aa8-bf2f-0d4dfab01234';
    private const PERSON_NAME = 'Roster Name';
    private const FIRST_CLUSTER = 'cluster-first';
    private const LOSER_CLUSTER = 'cluster-loser';
    private const SURVIVOR_CLUSTER = 'cluster-survivor';

    public function testFirstBindQueuesClusterPersonBoundAndDoesNotMerge(): void
    {
        global $wpdb;

        $this->seedPerson();
        $this->seedCluster(self::FIRST_CLUSTER);
        $wpdb->queryResults["SELECT local_revision FROM `wp_acx_clusters` WHERE cluster_uuid = '" . self::FIRST_CLUSTER . "'"] = 2;

        $merge = $this->createMergeService();
        $merge->expects($this->never())->method('merge_cluster');

        $enqueued = [];
        $result = $this->newService($merge)->bind_cluster_to_person(
            self::FIRST_CLUSTER,
            self::PERSON_ID,
            $this->captureEnqueue($enqueued),
            self::PERSON_UUID,
            self::PERSON_NAME
        );

        $this->assertIsArray($result);
        $this->assertSame(self::PERSON_ID, $result['person_id']);
        $this->assertSame(self::PERSON_UUID, $result['person_uuid']);
        $this->assertSame(self::PERSON_NAME, $result['person_name']);
        $this->assertArrayHasKey('updated_at', $result);

        $this->assertCount(1, $enqueued);
        $this->assertSame('cluster_person_bound', $enqueued[0]['operation_type']);
        $this->assertSame(self::FIRST_CLUSTER, $enqueued[0]['cluster_id']);
        $this->assertSame(
            [
                'cluster_uuid' => self::FIRST_CLUSTER,
                'person_uuid' => self::PERSON_UUID,
                'person_name' => self::PERSON_NAME,
            ],
            $enqueued[0]['payload']
        );

        $clusterUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_clusters');
        $this->assertStringContainsString('person_id = 7', $clusterUpdate);
        $this->assertStringContainsString("label = '" . self::PERSON_NAME . "'", $clusterUpdate);
        $this->assertStringContainsString("curation_state = 'confirmed'", $clusterUpdate);
    }

    public function testSecondBindMergesLoserIntoPersonSurvivorWithoutLabelReplay(): void
    {
        global $wpdb;

        $this->seedPerson();
        $this->seedCluster(self::SURVIVOR_CLUSTER, [
            'person_id' => self::PERSON_ID,
            'label' => self::PERSON_NAME,
            'curation_state' => 'confirmed',
            'is_user_confirmed' => 1,
        ]);
        $this->seedCluster(self::LOSER_CLUSTER);

        $captured = null;
        $merge = $this->createMergeService();
        $merge->expects($this->once())
            ->method('merge_cluster')
            ->willReturnCallback(static function (WP_REST_Request $request) use (&$captured): WP_REST_Response {
                $captured = $request;
                return new WP_REST_Response(
                    [
                        'source_cluster_id' => $request->get_param('source_id'),
                        'target_cluster_id' => $request->get_param('target_cluster_id'),
                        'moved_identity_count' => 3,
                        'synced' => false,
                        'status' => 'pending',
                    ],
                    200
                );
            });

        $enqueued = [];
        $result = $this->newService($merge)->bind_cluster_to_person(
            self::LOSER_CLUSTER,
            self::PERSON_ID,
            $this->captureEnqueue($enqueued),
            self::PERSON_UUID,
            self::PERSON_NAME
        );

        $this->assertIsArray($result);
        $this->assertSame(self::PERSON_ID, $result['person_id']);
        $this->assertSame(self::PERSON_UUID, $result['person_uuid']);
        $this->assertSame(self::PERSON_NAME, $result['person_name']);
        $this->assertSame([], $enqueued);
        $this->assertInstanceOf(WP_REST_Request::class, $captured);
        $this->assertSame(self::LOSER_CLUSTER, $captured->get_param('source_id'));
        $this->assertSame(self::SURVIVOR_CLUSTER, $captured->get_param('target_cluster_id'));
        $this->assertNull($captured->get_param('target_label'));
        $this->assertSame([], $this->queriesContaining($wpdb->queries, 'UPDATE wp_acx_clusters'));
        $this->assertSame([], $this->queriesContaining($wpdb->queries, "'cluster_person_bound'"));
        $this->assertSame([], $this->queriesContaining($wpdb->queries, "'cluster_label_updated'"));
    }

    public function testSecondBindSurfacesTypedMergeErrorWithoutLabelCopy(): void
    {
        global $wpdb;

        $this->seedPerson();
        $this->seedCluster(self::SURVIVOR_CLUSTER, [
            'person_id' => self::PERSON_ID,
            'label' => self::PERSON_NAME,
            'curation_state' => 'confirmed',
        ]);
        $this->seedCluster(self::LOSER_CLUSTER);

        $mergeError = new WP_Error(
            'acx_db_error',
            'Could not queue merge replay operation.',
            ['status' => 500]
        );
        $merge = $this->createMergeService();
        $merge->expects($this->once())->method('merge_cluster')->willReturn($mergeError);

        $enqueued = [];
        $result = $this->newService($merge)->bind_cluster_to_person(
            self::LOSER_CLUSTER,
            self::PERSON_ID,
            $this->captureEnqueue($enqueued),
            self::PERSON_UUID,
            self::PERSON_NAME
        );

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('acx_db_error', $result->get_error_code());
        $this->assertSame(500, (int) ($result->get_error_data()['status'] ?? 0));
        $this->assertSame([], $enqueued);
        $this->assertSame([], $this->queriesContaining($wpdb->queries, 'UPDATE wp_acx_clusters'));
        $this->assertSame([], $this->queriesContaining($wpdb->queries, "'cluster_person_bound'"));
    }

    public function testSecondBindWithoutMergeServiceReturnsTypedErrorWithoutLabelCopy(): void
    {
        global $wpdb;

        $this->seedPerson();
        $this->seedCluster(self::SURVIVOR_CLUSTER, [
            'person_id' => self::PERSON_ID,
            'curation_state' => 'confirmed',
        ]);
        $this->seedCluster(self::LOSER_CLUSTER);

        $enqueued = [];
        $result = (new ClusterPersonBindService())->bind_cluster_to_person(
            self::LOSER_CLUSTER,
            self::PERSON_ID,
            $this->captureEnqueue($enqueued),
            self::PERSON_UUID,
            self::PERSON_NAME
        );

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('acx_cluster_merge_unavailable', $result->get_error_code());
        $this->assertSame(500, (int) ($result->get_error_data()['status'] ?? 0));
        $this->assertSame([], $enqueued);
        $this->assertSame([], $this->queriesContaining($wpdb->queries, 'UPDATE wp_acx_clusters'));
    }

    public function testDismissedClusterIsNotTreatedAsSurvivor(): void
    {
        $this->seedPerson();
        $this->seedCluster('cluster-dismissed', [
            'person_id' => self::PERSON_ID,
            'label' => self::PERSON_NAME,
            'curation_state' => 'dismissed',
        ]);
        $this->seedCluster(self::FIRST_CLUSTER);
        global $wpdb;
        $wpdb->queryResults["SELECT local_revision FROM `wp_acx_clusters` WHERE cluster_uuid = '" . self::FIRST_CLUSTER . "'"] = 2;

        $merge = $this->createMergeService();
        $merge->expects($this->never())->method('merge_cluster');

        $enqueued = [];
        $result = $this->newService($merge)->bind_cluster_to_person(
            self::FIRST_CLUSTER,
            self::PERSON_ID,
            $this->captureEnqueue($enqueued),
            self::PERSON_UUID,
            self::PERSON_NAME
        );

        $this->assertIsArray($result);
        $this->assertCount(1, $enqueued);
        $this->assertSame('cluster_person_bound', $enqueued[0]['operation_type']);
    }

    public function testBindLocksPersonRowBeforeLockingSurvivorLookup(): void
    {
        global $wpdb;

        $this->seedPerson();
        $this->seedCluster(self::FIRST_CLUSTER);
        $wpdb->queryResults["SELECT local_revision FROM `wp_acx_clusters` WHERE cluster_uuid = '" . self::FIRST_CLUSTER . "'"] = 2;

        $merge = $this->createMergeService();
        $enqueued = [];
        $result = $this->newService($merge)->bind_cluster_to_person(
            self::FIRST_CLUSTER,
            self::PERSON_ID,
            $this->captureEnqueue($enqueued),
            self::PERSON_UUID,
            self::PERSON_NAME
        );

        $this->assertIsArray($result);
        $queries = array_values(array_filter($wpdb->queries, 'is_string'));
        $personLock = array_search('SELECT id FROM `wp_acx_persons` WHERE id = 7 FOR UPDATE', $queries, true);
        $survivorLookups = array_keys(array_filter(
            $queries,
            static fn (string $q): bool => str_contains($q, 'SELECT cluster_uuid FROM') && str_contains($q, 'person_id = 7')
        ));
        $this->assertIsInt($personLock);
        $this->assertCount(1, $survivorLookups);
        $this->assertLessThan($survivorLookups[0], $personLock);
        $this->assertStringEndsWith('FOR UPDATE', $queries[$survivorLookups[0]]);
    }

    public function testBindReturnsBusyWithoutWritesWhenPersonLockFails(): void
    {
        global $wpdb;

        $this->seedPerson();
        $this->seedCluster(self::FIRST_CLUSTER);
        $wpdb->queryResults['SELECT id FROM `wp_acx_persons` WHERE id = 7 FOR UPDATE'] = null;

        $merge = $this->createMergeService();
        $merge->expects($this->never())->method('merge_cluster');
        $enqueued = [];
        $result = $this->newService($merge)->bind_cluster_to_person(
            self::FIRST_CLUSTER,
            self::PERSON_ID,
            $this->captureEnqueue($enqueued),
            self::PERSON_UUID,
            self::PERSON_NAME
        );

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('acx_bind_busy', $result->get_error_code());
        $this->assertSame(409, (int) ($result->get_error_data()['status'] ?? 0));
        $this->assertSame([], $enqueued);
        $this->assertSame([], $this->queriesContaining($wpdb->queries, 'UPDATE wp_acx_clusters'));
    }

    /**
     * @return ClusterMergeService&\PHPUnit\Framework\MockObject\MockObject
     */
    private function createMergeService(): ClusterMergeService
    {
        return $this->getMockBuilder(ClusterMergeService::class)
            ->disableOriginalConstructor()
            ->onlyMethods(['merge_cluster'])
            ->getMock();
    }

    private function newService(ClusterMergeService $merge): ClusterPersonBindService
    {
        return new ClusterPersonBindService($merge);
    }

    /**
     * @param list<array{operation_type:string,cluster_id:string,local_revision:int,payload:array<string,mixed>}> $enqueued
     */
    private function captureEnqueue(array &$enqueued): callable
    {
        return static function (
            string $operation_type,
            string $cluster_id,
            int $local_revision,
            array $payload
        ) use (&$enqueued): bool {
            $enqueued[] = [
                'operation_type' => $operation_type,
                'cluster_id' => $cluster_id,
                'local_revision' => $local_revision,
                'payload' => $payload,
            ];
            return true;
        };
    }

    private function seedPerson(): void
    {
        global $wpdb;
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => self::PERSON_ID,
                'person_uuid' => self::PERSON_UUID,
                'name' => self::PERSON_NAME,
            ],
        ];
    }

    /** @param array<string,mixed> $overrides */
    private function seedCluster(string $clusterUuid, array $overrides = []): void
    {
        global $wpdb;
        if (!isset($wpdb->tableRows['wp_acx_clusters']) || !is_array($wpdb->tableRows['wp_acx_clusters'])) {
            $wpdb->tableRows['wp_acx_clusters'] = [];
        }
        $wpdb->tableRows['wp_acx_clusters'][] = array_merge(
            [
                'cluster_uuid' => $clusterUuid,
                'tenant_id' => self::currentTenantId(),
                'label' => null,
                'person_id' => null,
                'curation_state' => 'uncurated',
                'local_revision' => 1,
                'is_user_confirmed' => 0,
            ],
            $overrides
        );
    }

    /**
     * @param array<int,mixed> $queries
     * @return list<string>
     */
    private function queriesContaining(array $queries, string $needle): array
    {
        $matches = [];
        foreach ($queries as $query) {
            if (is_string($query) && str_contains($query, $needle)) {
                $matches[] = $query;
            }
        }

        return $matches;
    }
}
