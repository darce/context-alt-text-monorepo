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
        try {
            $result = $service->create_distinct('Ada', static fn(): bool => true);
        } catch (\Throwable $e) {
            $this->fail(
                'create_distinct must return WP_Error on suffix exhaustion, not throw: '
                . $e::class . ': ' . $e->getMessage()
            );
        }

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('acx_name_collision', $result->get_error_code());
    }

    public function testCreateDistinctReturnsErrorWhenWpdbUnavailable(): void
    {
        $saved = $GLOBALS['wpdb'] ?? null;
        $result = null;

        try {
            unset($GLOBALS['wpdb']);
            $service = new PersonResolutionService();
            try {
                $result = $service->create_distinct('Ada', static fn(): bool => true);
            } catch (\Throwable $e) {
                $this->fail(
                    'create_distinct must return WP_Error when wpdb is unavailable, not throw: '
                    . $e::class . ': ' . $e->getMessage()
                );
            }
        } finally {
            if ($saved !== null) {
                $GLOBALS['wpdb'] = $saved;
            }
        }

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('acx_db_error', $result->get_error_code());
    }

    public function testAutomaticAssociationUsesInjectedTablesAndExplicitTenant(): void
    {
        global $wpdb;
        $wpdb->tableRows['alt_acx_clusters'] = [[
            'cluster_uuid' => 'group', 'tenant_id' => 'requested-tenant', 'person_id' => 9,
        ]];
        // Legacy same-name humans remain separate UUID choices. Place the
        // other namesake first so name-based selection cannot pass this case.
        $wpdb->tableRows['alt_acx_persons'] = [[
            'id' => 8, 'tenant_id' => 'requested-tenant',
            'person_uuid' => 'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee', 'name' => 'Stored human name',
        ], [
            'id' => 9, 'tenant_id' => 'requested-tenant',
            'person_uuid' => 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', 'name' => 'Stored human name',
        ]];
        $result = (new PersonResolutionService('alt_'))->resolve_for_automatic_bind(
            'Person 3', 'requested-tenant', 'group',
            static function (): bool { self::fail('Observation must not enqueue creation.'); }
        );
        self::assertIsArray($result);
        self::assertSame(9, $result['person_id']);
        self::assertSame('Stored human name', $result['name']);
        self::assertSame('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', $result['person_uuid']);
        self::assertCount(2, $wpdb->tableRows['alt_acx_persons']);
        foreach ($wpdb->queries as $query) {
            self::assertStringNotContainsString('wp_acx_', $query);
        }
    }

    public function testAutomaticResolutionDoesNotInventIdentityWhenDatabaseUnavailable(): void
    {
        $saved = $GLOBALS['wpdb'];
        try {
            unset($GLOBALS['wpdb']);
            $result = (new PersonResolutionService())->resolve_for_automatic_bind(
                'Ada', self::currentTenantId(), 'group', static fn(): bool => false
            );
        } finally {
            $GLOBALS['wpdb'] = $saved;
        }
        self::assertInstanceOf(\WP_Error::class, $result);
        self::assertSame('acx_db_error', $result->get_error_code());
    }
}
