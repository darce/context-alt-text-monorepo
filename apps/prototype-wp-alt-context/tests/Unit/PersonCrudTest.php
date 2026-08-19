<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Api
 */
class PersonCrudTest extends TestCase
{
    private Api $api;

    /**
     * @return array<string, mixed>
     */
    private function latestOutboxPayload(): array
    {
        global $wpdb;

        $rows = $wpdb->tableRows['wp_acx_sync_outbox'] ?? [];
        $this->assertNotEmpty($rows);
        $row = $rows[\array_key_last($rows)];
        $this->assertIsArray($row);

        $payload = $row['payload'] ?? null;
        $this->assertIsString($payload);

        $decoded = \json_decode($payload, true);
        $this->assertIsArray($decoded);

        return $decoded;
    }

    /**
     * @return array<string, mixed>
     */
    private function outboxPayloadAt(int $index): array
    {
        global $wpdb;

        $rows = $wpdb->tableRows['wp_acx_sync_outbox'] ?? [];
        $this->assertArrayHasKey($index, $rows);
        $row = $rows[$index];
        $this->assertIsArray($row);

        $payload = $row['payload'] ?? null;
        $this->assertIsString($payload);

        $decoded = \json_decode($payload, true);
        $this->assertIsArray($decoded);

        return $decoded;
    }

    protected function setUp(): void
    {
        parent::setUp();
        $this->api = new Api();
        // Mock capability for manage_options
        $this->setUserCapability('manage_options', true);
    }

    public function testCreatePersonEndpointRegistersAndResponds(): void
    {
        $this->api->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains('/roster/persons', $routes);

        $request = new WP_REST_Request('POST', '/acx/v1/roster/persons');
        $request->set_param('name', 'John Doe');
        $request->set_param('tags', ['family', 'friend']);

        // This will fail because the method doesn't exist yet in Api class
        // or because it's not registered correctly.
        $response = $this->api->create_person($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(201, $response->get_status());

        $data = $response->get_data();
        $this->assertSame('John Doe', $data['name']);
        $this->assertArrayHasKey('id', $data);
        $this->assertArrayHasKey('person_uuid', $data);

        // Verify DB insert
        global $wpdb;
        $insertQuery = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_persons');
        $this->assertStringContainsString("'John Doe'", $insertQuery);
        $this->assertStringContainsString('local_revision', $insertQuery);
        $this->assertStringContainsString(', 1,', $insertQuery);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'person_created'", $outboxInsert);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testCreatePersonFailsOnDuplicateName(): void
    {
        $this->api->register_routes();
        global $wpdb;

        // Mock existing person
        $wpdb->mockVar = 1; // ID of existing person

        $request = new WP_REST_Request('POST', '/acx/v1/roster/persons');
        $request->set_param('name', 'Existing Person');

        $response = $this->api->create_person($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame(409, $response->get_error_data()['status']);
        $this->assertSame('acx_person_exists', $response->get_error_code());
    }

    public function testCreatePersonAllowsSameNormalizedNameAcrossTenantsAndDedupesWithinTenant(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $tenantA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        $tenantB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

        $this->setOption('acx_recognition_tenant_id', $tenantA);
        $requestA = new WP_REST_Request('POST', '/acx/v1/roster/persons');
        $requestA->set_param('name', 'Jane Doe');
        $requestA->set_param('tags', []);
        $responseA = $this->api->create_person($requestA);

        $this->assertInstanceOf(WP_REST_Response::class, $responseA);
        $this->assertSame(201, $responseA->get_status());
        $dataA = $responseA->get_data();
        $this->assertIsArray($dataA);
        $this->assertArrayHasKey('id', $dataA);
        $idA = $dataA['id'];

        $this->setOption('acx_recognition_tenant_id', $tenantB);
        $requestB = new WP_REST_Request('POST', '/acx/v1/roster/persons');
        $requestB->set_param('name', 'Jane Doe');
        $requestB->set_param('tags', []);
        $responseB = $this->api->create_person($requestB);

        $this->assertInstanceOf(
            WP_REST_Response::class,
            $responseB,
            'tenant B creating Jane Doe must not 409 against tenant A (cross-tenant existence oracle)'
        );
        $this->assertSame(201, $responseB->get_status());
        $dataB = $responseB->get_data();
        $this->assertIsArray($dataB);
        $this->assertArrayHasKey('id', $dataB);
        $idB = $dataB['id'];
        $this->assertNotSame($idA, $idB, 'tenant B Jane Doe must be a distinct person id');

        $requestBDup = new WP_REST_Request('POST', '/acx/v1/roster/persons');
        $requestBDup->set_param('name', 'Jane Doe');
        $responseBDup = $this->api->create_person($requestBDup);

        $this->assertInstanceOf(\WP_Error::class, $responseBDup);
        $this->assertSame(409, $responseBDup->get_error_data()['status']);
        $this->assertSame('acx_person_exists', $responseBDup->get_error_code());

        $personsSql = (new \AltContext\Support\LifecycleManager())
            ->build_projection_schema_statements((string) $wpdb->prefix, '')['acx_persons'] ?? '';
        $this->assertIsString($personsSql);
        $this->assertNotSame('', $personsSql);
        $this->assertMatchesRegularExpression(
            '/UNIQUE\s+KEY\s+idx_tenant_normalized_name\s*\(\s*tenant_id\s*,\s*normalized_name\s*\)/i',
            $personsSql,
            'UNIQUE(normalized_name) alone would reject tenant B Jane Doe after tenant A created it'
        );
    }

    public function testCreatePersonFailsOnEmptyName(): void
    {
        $this->api->register_routes();

        $request = new WP_REST_Request('POST', '/acx/v1/roster/persons');
        $request->set_param('name', '   '); // Whitespace only

        $response = $this->api->create_person($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame(400, $response->get_error_data()['status']);
        $this->assertSame('acx_invalid_name', $response->get_error_code());
    }

    public function testUpdatePersonSucceeds(): void
    {
        $this->api->register_routes();
        global $wpdb;

        // Mock existing person
        $wpdb->mockRow = [
            'id' => 1,
            'name' => 'Original Name',
            'tags' => '["old"]',
        ];

        $request = new WP_REST_Request('PUT', '/acx/v1/roster/persons/1');
        $request->set_param('id', 1);
        $request->set_param('name', 'New Name');
        $request->set_param('tags', ['new']);

        // Mock conflicting name check (returns null = no conflict)
        $wpdb->mockVar = null;

        $response = $this->api->update_person($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $updateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_persons');
        $this->assertStringContainsString("name = 'New Name'", $updateQuery);
        $clusterSyncQuery = $this->findQueryContaining($wpdb->queries, 'WHERE person_id = 1');
        $this->assertStringContainsString("UPDATE `wp_acx_clusters` SET label = 'New Name'", $clusterSyncQuery);
        $this->assertStringContainsString('local_revision = local_revision + 1', $clusterSyncQuery);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'person_updated'", $outboxInsert);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testDeletePersonSoftDissociatesClusters(): void
    {
        $this->api->register_routes();
        global $wpdb;

        // Mock existing person
        $wpdb->mockRow = [
            'id' => 1,
            'name' => 'To Delete',
            'person_uuid' => '7fa30d6d-5d89-4d09-b4fb-b5fe11111111',
        ];

        $request = new WP_REST_Request('DELETE', '/acx/v1/roster/persons/1');
        $request->set_param('id', 1);

        $response = $this->api->delete_person($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertTrue($data['deleted']);
        $this->assertArrayHasKey('clusters_dissociated', $data);
        $this->assertArrayHasKey('cluster_ids', $data);
        $this->assertSame(0, $data['clusters_dissociated']);

        // Verify person deletion
        $deleteQuery = $this->findQueryContaining($wpdb->queries, 'DELETE FROM wp_acx_persons');
        $this->assertStringContainsString('id = 1', $deleteQuery);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'person_deleted'", $outboxInsert);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testDeletePersonClearsHumanLabelAndReturnsClusterToUnlabeledQueue(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $clusterUuid = 'cluster-tory-6731';
        $wpdb->mockRow = [
            'id' => 1,
            'name' => 'Tory Guzman',
            'person_uuid' => '7fa30d6d-5d89-4d09-b4fb-b5fe11111111',
            'local_revision' => 2,
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => $clusterUuid,
                'tenant_id' => self::currentTenantId(),
                'label' => 'Tory Guzman',
                'person_id' => 1,
                'curation_state' => 'confirmed',
                'is_user_confirmed' => 1,
                'identity_count' => 3,
                'local_revision' => 4,
            ],
        ];

        $request = new WP_REST_Request('DELETE', '/acx/v1/roster/persons/1');
        $request->set_param('id', 1);

        $response = $this->api->delete_person($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertTrue($data['deleted']);
        $this->assertSame(1, $data['clusters_dissociated']);
        $this->assertSame([$clusterUuid], $data['cluster_ids']);

        $cluster = $wpdb->tableRows['wp_acx_clusters'][0];
        $this->assertNull($cluster['label']);
        $this->assertNull($cluster['person_id']);
        $this->assertSame(0, (int) $cluster['is_user_confirmed']);

        $dissociateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE `wp_acx_clusters` SET');
        $this->assertStringContainsString('label = NULL', $dissociateQuery);
        $this->assertStringContainsString('is_user_confirmed = 0', $dissociateQuery);
        $this->assertStringContainsString('label_cleared_revision = snapshot_version', $dissociateQuery);

        $outboxJoined = implode("\n", array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_sync_outbox')
        ));
        $this->assertStringContainsString("'cluster_person_unbound'", $outboxJoined);
        $this->assertStringContainsString("'cluster_label_updated'", $outboxJoined);

        $wpdb->queries = [];
        $wpdb->mockResults = [];
        (new \AltContext\Sovereign\Repositories\ClustersReadRepository('wp_acx_clusters'))
            ->list_top_unlabeled(self::currentTenantId(), 10);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('c.is_user_confirmed = 0', $sql);
        $this->assertStringContainsString("LOWER(c.label) LIKE 'cluster-%%'", $sql);
        $this->assertStringContainsString("LOWER(c.label) LIKE 'cluster\\_%%'", $sql);
        $this->assertStringContainsString('c.identity_count >= 2', $sql);
    }

    public function testDeletePersonSingletonIsCountedByTopUnlabeledSingletons(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $clusterUuid = 'cluster-singleton';
        $wpdb->mockRow = [
            'id' => 1,
            'name' => 'Solo',
            'person_uuid' => '7fa30d6d-5d89-4d09-b4fb-b5fe11111111',
            'local_revision' => 1,
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => $clusterUuid,
                'tenant_id' => self::currentTenantId(),
                'label' => 'Solo',
                'person_id' => 1,
                'is_user_confirmed' => 1,
                'identity_count' => 1,
                'curation_state' => 'confirmed',
            ],
        ];

        $request = new WP_REST_Request('DELETE', '/acx/v1/roster/persons/1');
        $request->set_param('id', 1);
        $response = $this->api->delete_person($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $wpdb->queries = [];
        $wpdb->mockVar = 1;
        $count = (new \AltContext\Sovereign\Repositories\ClustersReadRepository('wp_acx_clusters'))
            ->count_top_unlabeled_singletons(self::currentTenantId());
        $this->assertSame(1, $count);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('c.identity_count <= 1', $sql);
    }

    public function testDeletePersonDoesNotDeleteOtherTenantSharingPersonId(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $currentTenant = self::currentTenantId();
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 7,
                'tenant_id' => 'other-tenant',
                'name' => 'Bob',
                'person_uuid' => 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                'local_revision' => 1,
            ],
            [
                'id' => 7,
                'tenant_id' => $currentTenant,
                'name' => 'Alice',
                'person_uuid' => 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                'local_revision' => 1,
            ],
        ];

        $request = new WP_REST_Request('DELETE', '/acx/v1/roster/persons/7');
        $request->set_param('id', 7);
        $response = $this->api->delete_person($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $remaining = $wpdb->tableRows['wp_acx_persons'];
        $this->assertCount(1, $remaining);
        $this->assertSame('other-tenant', $remaining[0]['tenant_id']);
        $this->assertSame('Bob', $remaining[0]['name']);
        $deleteQuery = $this->findQueryContaining($wpdb->queries, 'DELETE FROM wp_acx_persons');
        $this->assertStringContainsString('tenant_id =', $deleteQuery);
        $this->assertSame('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', $this->latestOutboxPayload()['person_uuid'] ?? null);
    }

    public function testDeletePersonSurfacesDatabaseFailureAsServerError(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 1,
                'tenant_id' => self::currentTenantId(),
                'name' => 'Broken',
                'person_uuid' => '7fa30d6d-5d89-4d09-b4fb-b5fe11111111',
                'local_revision' => 1,
            ],
        ];
        $wpdb->deleteResultsByTable['wp_acx_persons'] = false;

        $request = new WP_REST_Request('DELETE', '/acx/v1/roster/persons/1');
        $request->set_param('id', 1);
        $response = $this->api->delete_person($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertSame(500, $response->get_error_data()['status']);
    }

    public function testUpdatePersonDoesNotTouchOtherTenantRow(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $currentTenant = self::currentTenantId();
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 7,
                'tenant_id' => $currentTenant,
                'name' => 'Alice',
                'person_uuid' => 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                'local_revision' => 1,
                'normalized_name' => 'alice',
            ],
            [
                'id' => 7,
                'tenant_id' => 'other-tenant',
                'name' => 'Bob',
                'person_uuid' => 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                'local_revision' => 4,
                'normalized_name' => 'bob',
            ],
        ];

        $request = new WP_REST_Request('PUT', '/acx/v1/roster/persons/7');
        $request->set_param('id', 7);
        $request->set_param('name', 'Alice Renamed');

        $response = $this->api->update_person($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame('Bob', $wpdb->tableRows['wp_acx_persons'][1]['name']);
        $this->assertSame(4, (int) $wpdb->tableRows['wp_acx_persons'][1]['local_revision']);
        $this->assertSame('Alice Renamed', $wpdb->tableRows['wp_acx_persons'][0]['name']);
    }

    public function testDeletePersonSurfacesResetCurationFailure(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $wpdb->mockRow = [
            'id' => 1,
            'name' => 'Broken',
            'person_uuid' => '7fa30d6d-5d89-4d09-b4fb-b5fe11111111',
            'local_revision' => 1,
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-broken',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Broken',
                'person_id' => 1,
            ],
        ];
        $wpdb->defaultQueryResult = false;

        $request = new WP_REST_Request('DELETE', '/acx/v1/roster/persons/1');
        $request->set_param('id', 1);
        $response = $this->api->delete_person($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
    }

    public function testCommitRosterClusterMarksClusterAsCuratedAndQueuesOutboxEvent(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $wpdb->queryResults['SELECT person_uuid FROM `wp_acx_persons` WHERE id = 7'] =
            '8cb36e76-7c2c-4aa8-bf2f-0d4dfab01234';
        $wpdb->queryResults['SELECT name FROM `wp_acx_persons` WHERE id = 7'] = 'Roster Name';
        $wpdb->queryResults['SELECT snapshot_version FROM `wp_acx_clusters` WHERE cluster_uuid = \'cluster-123\' LIMIT 1'] = 27;
        $wpdb->queryResults['SELECT local_revision FROM `wp_acx_clusters` WHERE cluster_uuid = \'cluster-123\''] = 3;

        $request = new WP_REST_Request('POST', '/acx/v1/roster/clusters/cluster-123/commit');
        $request->set_param('cluster_id', 'cluster-123');
        $request->set_param('roster_entry_id', 7);

        $response = $this->api->commit_roster_cluster($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame('cluster-123', $data['cluster_id']);
        $this->assertSame(7, $data['person_id']);

        $clusterUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_clusters');
        $this->assertStringContainsString('person_id = 7', $clusterUpdate);
        $this->assertStringContainsString("label = 'Roster Name'", $clusterUpdate);
        $this->assertStringContainsString("curation_state = 'confirmed'", $clusterUpdate);
        $this->assertStringContainsString('is_user_confirmed = 1', $clusterUpdate);

        $revisionUpdate = $this->findQueryContaining($wpdb->queries, 'local_revision = local_revision + 1');
        $this->assertStringContainsString('cluster-123', $revisionUpdate);

        $outboxInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'cluster_person_bound'", $outboxInsert);
        $this->assertStringContainsString('cluster-123', $outboxInsert);
        $outboxPayload = $this->latestOutboxPayload();
        $this->assertSame('Roster Name', $outboxPayload['person_name']);
        $this->assertStringContainsString(', 27, 3,', $outboxInsert);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testCommitRosterClusterCreatesPersonInsideTransactionAndQueuesCreateThenBind(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $wpdb->insert_id = 12;
        $wpdb->queryResults['SELECT snapshot_version FROM `wp_acx_clusters` WHERE cluster_uuid = \'cluster-inline\' LIMIT 1'] = 44;
        $wpdb->queryResults['SELECT local_revision FROM `wp_acx_clusters` WHERE cluster_uuid = \'cluster-inline\''] = 4;

        $request = new WP_REST_Request('POST', '/acx/v1/roster/clusters/cluster-inline/commit');
        $request->set_param('cluster_id', 'cluster-inline');
        $request->set_param('new_entry_name', 'Inline Person');

        $response = $this->api->commit_roster_cluster($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertSame('cluster-inline', $data['cluster_id']);
        $this->assertSame(12, $data['person_id']);

        $transactionIndex = array_search('START TRANSACTION', $wpdb->queries, true);
        $personInsertIndex = $this->findQueryIndexContaining($wpdb->queries, 'INSERT INTO wp_acx_persons');
        $this->assertIsInt($transactionIndex);
        $this->assertGreaterThan($transactionIndex, $personInsertIndex);

        $personInsert = $wpdb->queries[$personInsertIndex];
        $this->assertStringContainsString("'Inline Person'", $personInsert);
        $this->assertStringContainsString('local_revision', $personInsert);
        $this->assertStringContainsString(', 1,', $personInsert);

        $clusterUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_clusters');
        $this->assertStringContainsString("label = 'Inline Person'", $clusterUpdate);

        $outboxInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_sync_outbox')
            )
        );
        $this->assertCount(2, $outboxInserts);
        $this->assertStringContainsString("'person_created'", $outboxInserts[0]);
        $this->assertStringContainsString("'cluster_person_bound'", $outboxInserts[1]);
        $outboxPayload = $this->outboxPayloadAt(1);
        $this->assertSame('Inline Person', $outboxPayload['person_name']);
        $this->assertStringContainsString(', 44, 4,', $outboxInserts[1]);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testGetRosterEntriesFetchesFromDb(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $wpdb->mockResults = [
            [
                'id' => 1,
                'name' => 'Alice',
                'tags' => '["friend"]',
                'person_uuid' => '11111111-1111-1111-1111-111111111111',
                'local_revision' => 7,
            ],
            [
                'id' => 2,
                'name' => 'Bob',
                'tags' => '[]',
                'person_uuid' => '22222222-2222-2222-2222-222222222222',
                'local_revision' => 3,
            ],
        ];
        $stream_name = sprintf('tenant:%s:clusters', md5((string) get_site_url()));
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT last_snapshot_version FROM %i WHERE stream_name = %s LIMIT 1',
            'wp_acx_sync_state',
            $stream_name
        )] = 42;
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT updated_at FROM %i WHERE stream_name = %s LIMIT 1',
            'wp_acx_sync_state',
            $stream_name
        )] = '2026-05-07 15:00:00';
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT last_sync_result FROM %i WHERE stream_name = %s LIMIT 1',
            'wp_acx_sync_state',
            $stream_name
        )] = 'ok';

        $request = new WP_REST_Request('GET', '/acx/v1/roster/entries');
        $response = $this->api->get_roster_entries($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertCount(2, $data);
        $this->assertSame('Alice', $data[0]['name']);
        $this->assertSame('11111111-1111-1111-1111-111111111111', $data[0]['person_uuid']);
        $this->assertSame(42, $data[0]['source_version']);
        $this->assertSame('current', $data[0]['projection_status']);
        $this->assertSame('2026-05-07 15:00:00', $data[0]['projection_refreshed_at']);
        $this->assertSame(['friend'], $data[0]['tags']);
    }

    /**
     * @param array<int,string> $queries
     */
    private function findQueryContaining(array $queries, string $needle): string
    {
        foreach ($queries as $query) {
            if (str_contains($query, $needle)) {
                return $query;
            }
        }

        $this->fail(sprintf('Unable to find query containing "%s".', $needle));
        return '';
    }

    /**
     * @param array<int,string> $queries
     */
    private function findQueryIndexContaining(array $queries, string $needle): int
    {
        foreach ($queries as $index => $query) {
            if (str_contains($query, $needle)) {
                return $index;
            }
        }

        $this->fail(sprintf('Unable to find query containing "%s".', $needle));
        return -1;
    }
}
