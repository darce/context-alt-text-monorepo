<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\PersonLabelBackfillService;
use AltContext\Api\Services\PersonResolutionService;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Services\PersonLabelBackfillService
 */
class PersonLabelBackfillServiceTest extends TestCase
{
    use FindsSqlQueries;

    public function testBackfillBindsPersonForHumanLabelWithoutPerson(): void
    {
        global $wpdb;

        $wpdb->insert_id = 44;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-tory',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Tory Guzman',
                'person_id' => null,
            ],
        ];
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-tory',
                'label' => 'Tory Guzman',
                'person_id' => null,
            ],
        ];

        $result = (new PersonLabelBackfillService())->backfill_tenant(self::currentTenantId(), 10);

        $this->assertSame(1, $result['bound']);
        $this->assertFalse($result['stalled']);

        $listSql = $this->findQueryContaining($wpdb->queries, 'person_id IS NULL');
        $this->assertStringContainsString("LIKE 'cluster-%%'", $listSql);
        $this->assertStringContainsString("LIKE 'cluster\\_%%'", $listSql);

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(1, $personInserts);
        $this->assertStringContainsString("'Tory Guzman'", $personInserts[0]);
        $this->assertStringContainsString(
            "'" . PersonResolutionService::normalize_name('Tory Guzman') . "'",
            $personInserts[0]
        );

        $bindUpdate = $this->findQueryContaining($wpdb->queries, 'person_id = 44');
        $this->assertStringContainsString('cluster-tory', $bindUpdate);
        $this->assertStringNotContainsString("curation_state = 'confirmed'", $bindUpdate);
        $this->assertStringNotContainsString('is_user_confirmed = 1', $bindUpdate);
    }

    public function testBackfillIsIdempotentWhenPersonAlreadyBound(): void
    {
        global $wpdb;

        $wpdb->insert_id = 45;
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 9,
                'person_uuid' => 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                'name' => 'Tory Guzman',
                'normalized_name' => PersonResolutionService::normalize_name('Tory Guzman'),
            ],
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-tory',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Tory Guzman',
                'person_id' => null,
            ],
        ];
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-tory',
                'label' => 'Tory Guzman',
                'person_id' => null,
            ],
        ];

        $service = new PersonLabelBackfillService();
        $first = $service->backfill_tenant(self::currentTenantId(), 10);
        $this->assertSame(1, $first['bound']);

        $wpdb->tableRows['wp_acx_clusters'][0]['person_id'] = 9;
        $wpdb->queries = [];
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-tory',
                'label' => 'Tory Guzman',
                'person_id' => 9,
            ],
        ];
        $second = $service->backfill_tenant(self::currentTenantId(), 10);

        $this->assertSame(0, $second['bound']);
        $this->assertSame(9, $wpdb->tableRows['wp_acx_clusters'][0]['person_id']);
        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $updates = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_starts_with($query, 'UPDATE wp_acx_clusters SET person_id')
            )
        );
        $this->assertCount(0, $personInserts);
        $this->assertCount(0, $updates);
    }

    public function testBackfillMarksRejectedRowsSeenAndDoesNotStall(): void
    {
        global $wpdb;

        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-blank',
                'label' => '   ',
                'person_id' => null,
            ],
        ];

        $result = (new PersonLabelBackfillService())->backfill_tenant(self::currentTenantId(), 10);

        $this->assertFalse($result['stalled']);
        $this->assertSame(0, $result['bound']);
        $this->assertSame(1, $result['skipped']);
        $this->assertSame(1, $result['examined']);
    }

    public function testAutomaticBindCreatesDistinctPersonOnNameCollision(): void
    {
        global $wpdb;

        $wpdb->insert_id = 80;
        $existingUuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 3,
                'person_uuid' => $existingUuid,
                'name' => 'John Smith',
                'normalized_name' => PersonResolutionService::normalize_name('John Smith'),
            ],
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-other',
                'tenant_id' => self::currentTenantId(),
                'label' => 'John Smith',
                'person_id' => 3,
            ],
            [
                'cluster_uuid' => 'cluster-new',
                'tenant_id' => self::currentTenantId(),
                'label' => 'John Smith',
                'person_id' => null,
            ],
        ];
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-new',
                'label' => 'John Smith',
                'person_id' => null,
            ],
        ];

        $result = (new PersonLabelBackfillService())->backfill_tenant(self::currentTenantId(), 10);

        $this->assertSame(1, $result['bound']);
        $this->assertGreaterThanOrEqual(1, $result['collisions']);
        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertNotEmpty($personInserts);
        $this->assertStringContainsString("'John Smith (2)'", $personInserts[0]);
    }

    public function testAutomaticBindReusesPersonAlreadyBoundToThisCluster(): void
    {
        global $wpdb;

        $wpdb->insert_id = 81;
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 3,
                'person_uuid' => 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                'name' => 'John Smith',
                'normalized_name' => PersonResolutionService::normalize_name('John Smith'),
            ],
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-same',
                'tenant_id' => self::currentTenantId(),
                'label' => 'John Smith',
                'person_id' => 3,
            ],
        ];
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-same',
                'label' => 'John Smith',
                'person_id' => 3,
            ],
        ];

        $result = (new PersonLabelBackfillService())->backfill_tenant(self::currentTenantId(), 10);

        $this->assertSame(0, $result['bound']);
        $this->assertSame(0, $result['collisions']);
        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(0, $personInserts);
    }
}
