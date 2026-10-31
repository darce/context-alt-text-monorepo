<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\PersonLabelBackfillService;
use AltContext\Api\Services\PersonResolutionService;
use AltContext\Sovereign\Repositories\ClusterCurationWriter;
use AltContext\Sovereign\Repositories\ClusterProjectionWriter;
use AltContext\Sovereign\Repositories\ClusterSnapshotMerger;
use AltContext\Tests\TestCase;
use PHPUnit\Framework\Attributes\DataProvider;

/** @covers \AltContext\Api\Services\PersonResolutionService */
class AutomaticPersonBindingAuthorityTest extends TestCase
{
    private const PERSON_UUID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

    private function seedPerson(string $tenant, string $name = 'Ada'): void
    {
        $GLOBALS['wpdb']->tableRows['wp_acx_persons'] = [[
            'id' => 3, 'person_uuid' => self::PERSON_UUID,
            'tenant_id' => $tenant, 'name' => $name,
            'normalized_name' => PersonResolutionService::normalize_name($name),
        ]];
    }

    private function seedGroup(string $tenant, ?int $personId = null, string $label = 'Ada'): void
    {
        $GLOBALS['wpdb']->tableRows['wp_acx_clusters'] = [[
            'cluster_uuid' => 'group', 'tenant_id' => $tenant,
            'label' => $label, 'person_id' => $personId,
            'curation_state' => 'uncurated', 'is_user_confirmed' => 0,
            'snapshot_version' => 1, 'local_revision' => 1,
        ]];
    }

    private function assertNoPersonWrites(): void
    {
        foreach ($GLOBALS['wpdb']->queries as $sql) {
            self::assertDoesNotMatchRegularExpression('/^(INSERT INTO|UPDATE|DELETE FROM) `?wp_acx_persons/i', $sql);
            self::assertStringNotContainsString('INSERT INTO wp_acx_outbox', $sql);
            self::assertStringNotContainsString('INSERT INTO wp_acx_sync_outbox', $sql);
        }
    }

    public static function labelCases(): array
    {
        return [
            'new human-looking label' => ['Ada', false, false],
            'unbound same-name person' => ['Ada', true, false],
            'same-name person bound elsewhere' => ['Ada', true, true],
            'machine PersonN label' => ['Person 7', false, false],
        ];
    }

    #[DataProvider('labelCases')]
    public function testLabelCannotAuthorizePerson(string $label, bool $personExists, bool $boundElsewhere): void
    {
        global $wpdb;
        if ($personExists) {
            $this->seedPerson(self::currentTenantId(), $label);
        }
        $this->seedGroup(self::currentTenantId(), null, $label);
        if ($boundElsewhere) {
            $wpdb->tableRows['wp_acx_clusters'][] = [
                'cluster_uuid' => 'other-group', 'tenant_id' => self::currentTenantId(), 'person_id' => 3,
            ];
        }
        $before = $wpdb->tableRows;
        $result = (new PersonResolutionService())->resolve_for_automatic_bind(
            $label, self::currentTenantId(), 'group',
            static function (): bool { self::fail('Automatic labels must never enqueue person creation.'); }
        );
        self::assertIsArray($result);
        self::assertSame(0, $result['person_id']);
        self::assertSame('unlinked', $result['outcome']);
        self::assertSame($label, $result['name']);
        self::assertSame($before, $wpdb->tableRows);
        $this->assertNoPersonWrites();
    }

    public function testAlreadyBoundAssociationUsesStoredIdentityRatherThanLabel(): void
    {
        global $wpdb;
        $this->seedPerson(self::currentTenantId(), 'Human chosen name');
        $this->seedGroup(self::currentTenantId(), 3, 'Person 7');
        $before = $wpdb->tableRows;
        for ($i = 0; $i < 2; ++$i) {
            $result = (new PersonResolutionService())->resolve_for_automatic_bind(
                'Different snapshot label', self::currentTenantId(), 'group', static fn(): bool => false
            );
            self::assertIsArray($result);
            self::assertSame(3, $result['person_id']);
            self::assertSame(self::PERSON_UUID, $result['person_uuid']);
            self::assertSame('Human chosen name', $result['name']);
            self::assertSame('rebound', $result['outcome']);
            self::assertFalse($result['collision']);
        }
        self::assertSame($before, $wpdb->tableRows);
        $this->assertNoPersonWrites();
    }

    public static function tenantCases(): array
    {
        return ['foreign group' => [true, false], 'foreign person' => [false, true]];
    }

    #[DataProvider('tenantCases')]
    public function testForeignAssociationCannotSupplyAuthority(bool $foreignGroup, bool $foreignPerson): void
    {
        $tenant = self::currentTenantId();
        $this->seedPerson($foreignPerson ? 'foreign' : $tenant);
        $this->seedGroup($foreignGroup ? 'foreign' : $tenant, 3);
        $result = (new PersonResolutionService())->resolve_for_automatic_bind('Ada', $tenant, 'group', static fn(): bool => false);
        self::assertIsArray($result);
        self::assertSame(0, $result['person_id']);
        $this->assertNoPersonWrites();
    }

    public static function automaticCallers(): array
    {
        return ['backfill' => ['backfill'], 'snapshot' => ['snapshot'], 'projection' => ['projection']];
    }

    #[DataProvider('automaticCallers')]
    public function testUnlinkedSameNameStaysUnlinkedThroughActualAutomaticCaller(string $caller): void
    {
        global $wpdb;
        $tenant = self::currentTenantId();
        $this->seedPerson($tenant);
        $this->seedGroup($tenant, 3);
        // Model the completed unlink participant's local association write. The
        // journal/manual participant integration belongs to a separate lane.
        self::assertSame(1, $wpdb->update('wp_acx_clusters', ['person_id' => null], ['cluster_uuid' => 'group', 'tenant_id' => $tenant]));
        $people = $wpdb->tableRows['wp_acx_persons'];
        // The shared SQL stub cannot parse multiline SELECTs. Supply the
        // actual backfill row shape for this known eligible stored row.
        $wpdb->mockResults = [['cluster_uuid' => 'group', 'label' => 'Ada', 'person_id' => null]];
        if ($caller === 'projection') {
            // A new group carrying the old label is no stronger evidence.
            self::assertSame(1, (new ClusterProjectionWriter('wp_acx_clusters'))->create_local_cluster($tenant, 'new-group', 'Ada'));
        } else {
            for ($i = 0; $i < 2; ++$i) {
                if ($caller === 'snapshot') {
                    (new ClusterSnapshotMerger('wp_acx_clusters'))->merge_snapshot_batch_for_tenant(
                        $tenant, [['cluster_uuid' => 'group', 'label' => 'Ada', 'identity_count' => 2]], 2 + $i
                    );
                } else {
                    $result = (new PersonLabelBackfillService())->backfill_tenant($tenant);
                    self::assertSame(0, $result['bound']);
                    self::assertSame(0, $result['created']);
                    self::assertSame(1, $result['skipped']);
                }
            }
        }
        foreach ($wpdb->tableRows['wp_acx_clusters'] as $group) {
            self::assertNull($group['person_id'] ?? null, 'Label evidence must not undo unlink.');
            self::assertSame('Ada', $group['label']);
        }
        self::assertSame($people, $wpdb->tableRows['wp_acx_persons']);
        $this->assertNoPersonWrites();
    }

    public static function newLabelCallers(): array
    {
        $cases = [];
        foreach (['backfill', 'snapshot', 'projection'] as $caller) {
            foreach (['Ada', 'Person 7'] as $label) {
                $cases[$caller . ' ' . $label] = [$caller, $label];
            }
        }
        return $cases;
    }

    #[DataProvider('newLabelCallers')]
    public function testActualAutomaticCallerKeepsNewLabelWithoutCreatingPerson(string $caller, string $label): void
    {
        global $wpdb;
        $tenant = self::currentTenantId();
        $wpdb->tableRows['wp_acx_persons'] = [];
        if ($caller === 'projection') {
            self::assertSame(1, (new ClusterProjectionWriter('wp_acx_clusters'))->create_local_cluster($tenant, 'group', $label));
        } else {
            $this->seedGroup($tenant, null, $label);
            if ($caller === 'snapshot') {
                (new ClusterSnapshotMerger('wp_acx_clusters'))->merge_snapshot_batch_for_tenant(
                    $tenant, [['cluster_uuid' => 'group', 'label' => $label, 'identity_count' => 2]], 2
                );
            } else {
                $wpdb->mockResults = [['cluster_uuid' => 'group', 'label' => $label, 'person_id' => null]];
                $result = (new PersonLabelBackfillService())->backfill_tenant($tenant);
                self::assertSame(0, $result['bound']);
                self::assertSame(1, $result['skipped']);
            }
        }
        self::assertSame([], $wpdb->tableRows['wp_acx_persons']);
        self::assertSame($label, $wpdb->tableRows['wp_acx_clusters'][0]['label']);
        self::assertNull($wpdb->tableRows['wp_acx_clusters'][0]['person_id'] ?? null);
        $this->assertNoPersonWrites();
    }

    public function testExplicitHumanResolutionAndBindingRemainAvailable(): void
    {
        global $wpdb;
        $tenant = self::currentTenantId();
        $this->seedPerson($tenant);
        $this->seedGroup($tenant);
        $service = new PersonResolutionService();
        $selected = $service->resolve_or_create('Ada', static fn(): bool => false);
        self::assertIsArray($selected);
        self::assertSame(self::PERSON_UUID, $selected['person_uuid']);
        self::assertSame(1, (new ClusterCurationWriter('wp_acx_clusters'))->bind_person_to_cluster('group', $selected['person_id'], $tenant, true));
        self::assertSame(3, $wpdb->tableRows['wp_acx_clusters'][0]['person_id']);
        self::assertSame(1, $wpdb->tableRows['wp_acx_clusters'][0]['is_user_confirmed']);
        $createdEvents = [];
        $distinct = $service->create_distinct('Ada', static function (string $uuid, string $name) use (&$createdEvents): bool {
            $createdEvents[] = [$uuid, $name];
            return true;
        });
        self::assertIsArray($distinct);
        self::assertNotSame(self::PERSON_UUID, $distinct['person_uuid']);
        self::assertSame('Ada (2)', $distinct['name']);
        self::assertCount(1, $createdEvents);
        self::assertSame('Ada', $wpdb->tableRows['wp_acx_persons'][0]['name']);
    }
}
