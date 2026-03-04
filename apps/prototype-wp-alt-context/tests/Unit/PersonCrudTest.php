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
    }

    public function testDeletePersonSoftDissociatesClusters(): void
    {
        $this->api->register_routes();
        global $wpdb;

        // Mock existing person
        $wpdb->mockRow = [
            'id' => 1,
            'name' => 'To Delete',
        ];

        $request = new WP_REST_Request('DELETE', '/acx/v1/roster/persons/1');
        $request->set_param('id', 1);

        $response = $this->api->delete_person($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertTrue($data['deleted']);

        // Verify soft dissociation on clusters
        $dissociateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_clusters');
        $this->assertStringContainsString('person_id = NULL', $dissociateQuery);
        $this->assertStringContainsString('person_id = 1', $dissociateQuery);

        // Verify person deletion
        $deleteQuery = $this->findQueryContaining($wpdb->queries, 'DELETE FROM wp_acx_persons');
        $this->assertStringContainsString('id = 1', $deleteQuery);
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
            ],
            [
                'id' => 2,
                'name' => 'Bob',
                'tags' => '[]',
            ],
        ];

        $request = new WP_REST_Request('GET', '/acx/v1/roster/entries');
        $response = $this->api->get_roster_entries($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();
        $this->assertCount(2, $data);
        $this->assertSame('Alice', $data[0]['name']);
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
}
