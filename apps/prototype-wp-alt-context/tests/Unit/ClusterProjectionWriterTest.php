<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClusterProjectionWriter;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\ClusterProjectionWriter
 */
class ClusterProjectionWriterTest extends TestCase
{
    private ClusterProjectionWriter $writer;

    protected function setUp(): void
    {
        parent::setUp();
        $this->writer = new ClusterProjectionWriter('wp_acx_clusters');
    }

    public function testCreateLocalClusterSetsUserConfirmed(): void
    {
        global $wpdb;
        $wpdb->defaultInsertResult = 1;

        $result = $this->writer->create_local_cluster(
            self::currentTenantId(),
            'cluster-new',
            'Curated Label',
            3
        );

        $this->assertSame(1, $result);
        $inserts = array_values(array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_clusters')
        ));
        $this->assertNotEmpty($inserts);
        $this->assertStringContainsString('INSERT INTO wp_acx_clusters', $inserts[0]);

        // Assert the curation-marker value pairing, not just column presence:
        // a flipped is_user_confirmed or dropped local_revision bump must fail here.
        $row = $wpdb->tableRows['wp_acx_clusters'][0];
        $this->assertSame(1, $row['is_user_confirmed']);
        $this->assertSame(1, $row['local_revision']);
        $this->assertSame('uncurated', $row['curation_state']);
        $this->assertSame(0, $row['snapshot_version']);
        $this->assertSame(3, $row['identity_count']);
    }

    public function testCreateLocalClusterUsesAutomaticBindAndEnqueuesPersonCreated(): void
    {
        global $wpdb;

        $wpdb->insert_id = 40;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [];

        $result = $this->writer->create_local_cluster(
            self::currentTenantId(),
            'cluster-new',
            'Ada Lovelace',
            1
        );

        $this->assertSame(1, $result);
        $outbox = array_values(array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_sync_outbox')
        ));
        $this->assertNotEmpty($outbox, 'create_local_cluster must enqueue person_created');
        $this->assertStringContainsString("'person_created'", $outbox[0]);
        $row = $wpdb->tableRows['wp_acx_clusters'][0];
        $this->assertArrayHasKey('person_id', $row);
        $this->assertSame(40, (int) $row['person_id']);
        $this->assertSame('Ada Lovelace', $row['label']);
    }

    public function testCreateLocalClusterBindsResolvedPersonAndStoresItsName(): void
    {
        global $wpdb;

        $wpdb->insert_id = 41;
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 3,
                'person_uuid' => 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                'name' => 'Ada Lovelace',
                'normalized_name' => \AltContext\Api\Services\PersonResolutionService::normalize_name('Ada Lovelace'),
                'tenant_id' => self::currentTenantId(),
            ],
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-other',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Ada Lovelace',
                'person_id' => 3,
            ],
        ];

        $result = $this->writer->create_local_cluster(
            self::currentTenantId(),
            'cluster-new',
            'Ada Lovelace',
            1
        );

        $this->assertSame(1, $result);
        $created = null;
        foreach ($wpdb->tableRows['wp_acx_clusters'] as $row) {
            if (($row['cluster_uuid'] ?? '') === 'cluster-new') {
                $created = $row;
                break;
            }
        }
        $this->assertIsArray($created);
        $this->assertArrayHasKey('person_id', $created);
        $this->assertSame(41, (int) $created['person_id']);
        $this->assertSame('Ada Lovelace (2)', $created['label']);
    }

    public function testCreateLocalClusterCreatesDistinctPersonOnNameCollision(): void
    {
        global $wpdb;

        $wpdb->insert_id = 41;
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 3,
                'person_uuid' => 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                'name' => 'Ada Lovelace',
                'normalized_name' => \AltContext\Api\Services\PersonResolutionService::normalize_name('Ada Lovelace'),
                'tenant_id' => self::currentTenantId(),
            ],
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-other',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Ada Lovelace',
                'person_id' => 3,
            ],
        ];

        $this->writer->create_local_cluster(
            self::currentTenantId(),
            'cluster-new',
            'Ada Lovelace',
            1
        );

        $personInserts = array_values(array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
        ));
        $this->assertNotEmpty($personInserts);
        $this->assertStringContainsString("'Ada Lovelace (2)'", $personInserts[0]);
        $ids = array_values(array_unique(array_map(
            static fn(array $row): int => (int) ($row['id'] ?? 0),
            $wpdb->tableRows['wp_acx_persons']
        )));
        $this->assertContains(3, $ids);
        $this->assertGreaterThan(1, count($ids), 'collision must create a distinct person id');
    }

    public function testUpsertProjectionClusterLeavesUserConfirmedUnset(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->writer->upsert_projection_cluster(
            self::currentTenantId(),
            'cluster-proj',
            'Projection Label',
            4,
            9
        );

        $this->assertSame(1, $result);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('INSERT INTO `wp_acx_clusters`', $query);
        $this->assertStringContainsString('ON DUPLICATE KEY UPDATE', $query);
        $this->assertStringContainsString('is_user_confirmed = VALUES(is_user_confirmed)', $query);
    }
}
