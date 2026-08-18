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

        $wpdb->queries = [];
        $wpdb->mockResults = [];
        $second = $service->backfill_tenant(self::currentTenantId(), 10);

        $this->assertSame(0, $second['bound']);
        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(0, $personInserts);
    }

    public function testBackfillStopsAfterBoundedStalls(): void
    {
        global $wpdb;

        $wpdb->defaultInsertResult = false;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-bad',
                'label' => '   ',
                'person_id' => null,
            ],
        ];

        $result = (new PersonLabelBackfillService())->backfill_tenant(self::currentTenantId(), 10);

        $this->assertTrue($result['stalled']);
        $this->assertSame(0, $result['bound']);
        $this->assertGreaterThanOrEqual(PersonLabelBackfillService::MAX_STALLS, $result['stalls']);
    }
}
