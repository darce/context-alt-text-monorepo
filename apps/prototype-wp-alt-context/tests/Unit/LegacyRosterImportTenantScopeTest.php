<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;
use WP_Error;

/**
 * UXW2-4-R8-01: legacy roster import is tenant-scoped.
 *
 * @covers \AltContext\Support\LifecycleManager
 */
class LegacyRosterImportTenantScopeTest extends TestCase
{
    public function testImportLegacyRosterCreatesDistinctPersonsPerTenant(): void
    {
        global $wpdb;

        $tenantA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        $tenantB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
        $legacyEntries = [
            [
                'id' => 7,
                'name' => 'Jane Doe',
                'tags' => ['analyst'],
            ],
        ];

        $wpdb->tableRows['wp_acx_persons'] = [];

        $this->setOption('acx_recognition_tenant_id', $tenantA);
        $this->setOption('acx_roster_entries', $legacyEntries);
        $this->runLegacyImport(new LifecycleManager());

        $afterA = $wpdb->tableRows['wp_acx_persons'] ?? [];
        $this->assertCount(1, $afterA, 'tenant A import must insert Jane Doe');
        $idA = (int) ($afterA[0]['id'] ?? 0);
        $this->assertGreaterThan(0, $idA);

        $this->setOption('acx_recognition_tenant_id', $tenantB);
        $this->setOption('acx_roster_entries', $legacyEntries);
        $this->runLegacyImport(new LifecycleManager());

        $persons = $wpdb->tableRows['wp_acx_persons'] ?? [];
        $this->assertCount(2, $persons, 'tenant B import must insert a distinct Jane Doe');

        $ids = [];
        $tenantIds = [];
        foreach ($persons as $row) {
            $tenantId = trim((string) ($row['tenant_id'] ?? ''));
            $this->assertNotSame(
                '',
                $tenantId,
                'imported person must not have empty tenant_id'
            );
            $ids[] = (int) ($row['id'] ?? 0);
            $tenantIds[] = $tenantId;
        }

        $idB = $ids[0] === $idA ? $ids[1] : $ids[0];
        $this->assertNotSame(
            $idA,
            $idB,
            'tenant B id_map must not point at tenant A person'
        );
        $this->assertContains($tenantA, $tenantIds);
        $this->assertContains($tenantB, $tenantIds);
    }

    public function testImportLegacyRosterFailsClosedWhenTenantUnresolved(): void
    {
        global $wpdb;

        $legacyEntries = [
            [
                'id' => 3,
                'name' => 'Ada Lovelace',
                'tags' => [],
            ],
        ];
        $this->setOption('acx_roster_entries', $legacyEntries);
        $wpdb->tableRows['wp_acx_persons'] = [];

        $manager = new class() extends LifecycleManager {
            protected function resolve_active_tenant_id(): string
            {
                return '';
            }
        };

        $result = $this->runLegacyImport($manager);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame(
            'acx_legacy_roster_tenant_unresolved',
            $result->get_error_code()
        );
        $this->assertSame(
            'Tenant identity is unavailable.',
            $result->get_error_message()
        );
        $this->assertSame(
            [],
            array_values(
                array_filter(
                    $wpdb->queries,
                    static fn(string $query): bool => str_starts_with($query, 'INSERT INTO wp_acx_persons')
                )
            ),
            'fail-closed import must insert nothing'
        );
        $this->assertSame($legacyEntries, get_option('acx_roster_entries'));
        $this->assertSame([], $wpdb->tableRows['wp_acx_persons'] ?? []);
    }

    private function runLegacyImport(LifecycleManager $manager): mixed
    {
        $method = new \ReflectionMethod(LifecycleManager::class, 'migrate_legacy_roster_data');
        $method->setAccessible(true);

        return $method->invoke($manager);
    }
}
