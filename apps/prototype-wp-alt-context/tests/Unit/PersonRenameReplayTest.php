<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * Roster rename replay contract: renaming a person "Gilded Cypress" -> "Ellyn Heald"
 * keeps the person UUID and bound cluster identity, and durably enqueues one
 * canonical cluster_label_updated per bound cluster (current tenant only) inside
 * the same local transaction.
 *
 * Only the first test is expected to pass on the current source. The remaining
 * three pin behaviour the source does not yet implement: Api::update_person()
 * relabels bound clusters with a tenant-unscoped UPDATE and enqueues only a single
 * person_updated operation, which the backend acknowledges without persisting a name.
 *
 * @covers \AltContext\Api\Api
 */
class PersonRenameReplayTest extends TestCase
{
    private const PERSON_ID   = 42;
    private const PERSON_UUID = '3f6c1a9e-2b7d-4e5f-8a1b-7c0d9e2f4a61';
    private const OTHER_TENANT = 'other-tenant';

    private Api $api;
    private ?object $originalWpdb = null;

    protected function setUp(): void
    {
        parent::setUp();
        $this->api = new Api();
        $this->setUserCapability('manage_options', true);
        $this->api->register_routes();
    }

    protected function tearDown(): void
    {
        if (null !== $this->originalWpdb) {
            $GLOBALS['wpdb'] = $this->originalWpdb;
            $this->originalWpdb = null;
        }
        parent::tearDown();
    }

    public function testRenameKeepsPersonUuidAndBoundClusterIdentity(): void
    {
        global $wpdb;
        $this->seedGildedCypressRoster();

        $response = $this->renameTo('Ellyn Heald');

        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $person = $wpdb->tableRows['wp_acx_persons'][0];
        $this->assertSame(self::PERSON_ID, (int) $person['id']);
        $this->assertSame('Ellyn Heald', $person['name']);
        $this->assertSame(self::PERSON_UUID, $person['person_uuid']);

        $clusters = $wpdb->tableRows['wp_acx_clusters'];
        $this->assertSame(['cluster-rename-a', 'cluster-rename-b'], array_column($clusters, 'cluster_uuid'));
        foreach ($clusters as $cluster) {
            $this->assertSame(self::PERSON_ID, (int) $cluster['person_id']);
            $this->assertSame('Ellyn Heald', $cluster['label']);
        }
    }

    public function testRenameEnqueuesCanonicalLabelPerBoundClusterInsideTransaction(): void
    {
        global $wpdb;
        $this->seedGildedCypressRoster();

        $response = $this->renameTo('Ellyn Heald');

        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $labelOps = $this->outboxRowsFor('cluster_label_updated');
        $entityKeys = array_column($labelOps, 'entity_key');
        sort($entityKeys);
        $this->assertSame(['cluster-rename-a', 'cluster-rename-b'], $entityKeys);
        foreach ($labelOps as $row) {
            $this->assertSame('cluster', $row['entity_type']);
            $this->assertSame('Ellyn Heald', $this->decodePayload($row)['label'] ?? null);
        }

        $transactionIndex = array_search('START TRANSACTION', $wpdb->queries, true);
        $commitIndex = array_search('COMMIT', $wpdb->queries, true);
        $this->assertIsInt($transactionIndex);
        $this->assertIsInt($commitIndex);

        $labelInsertIndexes = $this->outboxInsertIndexesFor('cluster_label_updated');
        $this->assertCount(2, $labelInsertIndexes);
        foreach ($labelInsertIndexes as $index) {
            $this->assertGreaterThan($transactionIndex, $index);
            $this->assertLessThan($commitIndex, $index);
        }
    }

    public function testRenameDoesNotRelabelOrEnqueueOtherTenantClusterSharingPersonId(): void
    {
        global $wpdb;
        $this->seedGildedCypressRoster();
        $wpdb->tableRows['wp_acx_clusters'][] = $this->clusterRow(
            'cluster-other-tenant',
            self::OTHER_TENANT,
            'Gilded Cypress',
            self::PERSON_ID
        );

        $response = $this->renameTo('Ellyn Heald');

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame('Ellyn Heald', $this->clusterByUuid('cluster-rename-a')['label']);

        $otherTenantCluster = $this->clusterByUuid('cluster-other-tenant');
        $this->assertSame(self::OTHER_TENANT, $otherTenantCluster['tenant_id']);
        $this->assertSame('Gilded Cypress', $otherTenantCluster['label']);
        $this->assertSame(4, (int) $otherTenantCluster['local_revision']);

        $otherTenantOps = array_filter(
            $this->outboxRows(),
            static fn (array $row): bool => ($row['entity_key'] ?? null) === 'cluster-other-tenant'
        );
        $this->assertSame([], array_values($otherTenantOps));
    }

    public function testRenameRollsBackWhenPerClusterCanonicalEnqueueFails(): void
    {
        // Install the failing wpdb before seeding so the fixture rows live in the instance under test.
        $this->installWpdbFailingOutboxOperation('cluster_label_updated');
        $this->seedGildedCypressRoster();
        global $wpdb;

        $response = $this->renameTo('Ellyn Heald');

        $this->assertInstanceOf(
            \WP_Error::class,
            $response,
            'Rename must fail when a per-cluster canonical enqueue fails; current source commits without enqueuing cluster_label_updated.'
        );
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertSame(500, $response->get_error_data()['status']);
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    private function renameTo(string $name): WP_REST_Response|\WP_Error
    {
        $request = new WP_REST_Request('PUT', '/acx/v1/roster/persons/' . self::PERSON_ID);
        $request->set_param('id', self::PERSON_ID);
        $request->set_param('name', $name);

        return $this->api->update_person($request);
    }

    private function seedGildedCypressRoster(): void
    {
        global $wpdb;
        $tenant = self::currentTenantId();

        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id'              => self::PERSON_ID,
                'tenant_id'       => $tenant,
                'name'            => 'Gilded Cypress',
                'normalized_name' => 'gilded cypress',
                'person_uuid'     => self::PERSON_UUID,
                'tags'            => '[]',
                'local_revision'  => 3,
            ],
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            $this->clusterRow('cluster-rename-a', $tenant, 'Gilded Cypress', self::PERSON_ID),
            $this->clusterRow('cluster-rename-b', $tenant, 'Gilded Cypress', self::PERSON_ID),
        ];
    }

    /**
     * @return array<string, mixed>
     */
    private function clusterRow(string $clusterUuid, string $tenant, string $label, int $personId): array
    {
        return [
            'cluster_uuid'      => $clusterUuid,
            'tenant_id'         => $tenant,
            'label'             => $label,
            'person_id'         => $personId,
            'curation_state'    => 'confirmed',
            'is_user_confirmed' => 1,
            'identity_count'    => 3,
            'snapshot_version'  => 12,
            'local_revision'    => 4,
        ];
    }

    /**
     * Swap the global wpdb for a stub that rejects only the outbox insert of one
     * operation type, so a failure on the per-cluster enqueue is isolated from the
     * person-level enqueue.
     */
    private function installWpdbFailingOutboxOperation(string $operationType): void
    {
        global $wpdb;
        $this->originalWpdb = $wpdb;

        $failing = new class () extends \WPDBStub {
            public ?string $failingOperation = null;

            public function insert(string $table, array $data, $format = null)
            {
                if ('wp_acx_sync_outbox' === $table && ($data['operation_type'] ?? null) === $this->failingOperation) {
                    return false;
                }

                return parent::insert($table, $data, $format);
            }
        };
        $failing->failingOperation = $operationType;

        $GLOBALS['wpdb'] = $failing;
        $wpdb = $failing;
    }

    /**
     * @return array<string, mixed>
     */
    private function clusterByUuid(string $clusterUuid): array
    {
        global $wpdb;
        foreach ($wpdb->tableRows['wp_acx_clusters'] ?? [] as $cluster) {
            if (($cluster['cluster_uuid'] ?? null) === $clusterUuid) {
                return $cluster;
            }
        }

        $this->fail(sprintf('Cluster "%s" is missing from the fixture.', $clusterUuid));
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function outboxRows(): array
    {
        global $wpdb;

        return array_values($wpdb->tableRows['wp_acx_sync_outbox'] ?? []);
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function outboxRowsFor(string $operationType): array
    {
        return array_values(array_filter(
            $this->outboxRows(),
            static fn (array $row): bool => ($row['operation_type'] ?? null) === $operationType
        ));
    }

    /**
     * @return list<int>
     */
    private function outboxInsertIndexesFor(string $operationType): array
    {
        global $wpdb;

        $indexes = [];
        foreach ($wpdb->queries as $index => $query) {
            if (str_contains($query, 'INSERT INTO wp_acx_sync_outbox') && str_contains($query, "'" . $operationType . "'")) {
                $indexes[] = $index;
            }
        }

        return $indexes;
    }

    /**
     * @param array<string, mixed> $row
     * @return array<string, mixed>
     */
    private function decodePayload(array $row): array
    {
        $payload = $row['payload'] ?? null;
        $this->assertIsString($payload);

        $decoded = \json_decode($payload, true);
        $this->assertIsArray($decoded);

        return $decoded;
    }
}
