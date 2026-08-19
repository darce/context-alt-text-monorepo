<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\PersonResolutionService;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Services\PersonResolutionService
 */
class PersonResolutionServiceTest extends TestCase
{
    public function testCreateDistinctUsesInjectedTablePrefix(): void
    {
        global $wpdb;

        $wpdb->tableRows['alt_acx_persons'] = [
            [
                'id' => 2,
                'person_uuid' => 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                'name' => 'Ada (2)',
                'normalized_name' => PersonResolutionService::normalize_name('Ada (2)'),
            ],
        ];
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->insert_id = 50;

        $service = new PersonResolutionService('alt_');
        $service->create_distinct('Ada', static fn(): bool => true);

        $altInserts = array_values(array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'INSERT INTO alt_acx_persons')
        ));
        $wpInserts = array_values(array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
        ));
        $this->assertNotEmpty($altInserts, 'injected prefix must be used for the persons table');
        $this->assertSame([], $wpInserts);
    }

    public function testCreateDistinctReturnsErrorWhenSuffixesExhausted(): void
    {
        global $wpdb;

        $rows = [];
        for ($suffix = 2; $suffix <= 99; $suffix++) {
            $name = 'Ada (' . $suffix . ')';
            $rows[] = [
                'id' => $suffix,
                'person_uuid' => sprintf('aaaaaaaa-bbbb-cccc-dddd-%012d', $suffix),
                'name' => $name,
                'normalized_name' => PersonResolutionService::normalize_name($name),
                'tenant_id' => self::currentTenantId(),
            ];
        }
        $wpdb->tableRows['wp_acx_persons'] = $rows;

        $service = new PersonResolutionService();
        $result = $service->create_distinct('Ada', static fn(): bool => true);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('acx_name_collision', $result->get_error_code());
    }
}
