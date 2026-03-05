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
class DashboardApiTest extends TestCase
{
    private Api $api;

    protected function setUp(): void
    {
        parent::setUp();
        $this->api = new Api();
    }

    public function testGetDashboardStatsRespondsWithCorrectCounts(): void
    {
        $this->api->register_routes();
        global $wpdb;

        // Mock counts
        // 1. Person count (rows in wp_acx_persons)
        // 2. Assigned clusters (person_id IS NOT NULL)
        // 3. Pending review (person_id IS NULL AND curation_state = 'uncurated')
        // 4. Media with faces (distinct media_id in identity members)
        // 5. Persons with no assigned clusters (NOT EXISTS on clusters)

        $wpdb->mockVar = null;
        $wpdb->queryResults['SELECT COUNT(*) FROM `wp_acx_persons`'] = 10;
        $wpdb->queryResults['SELECT COUNT(*) FROM `wp_acx_clusters` WHERE person_id IS NOT NULL'] = 25;
        $wpdb->queryResults["SELECT COUNT(*) FROM `wp_acx_clusters` WHERE person_id IS NULL AND curation_state = 'uncurated'"] = 15;
        $wpdb->queryResults['SELECT COUNT(DISTINCT media_id) FROM `wp_acx_identity_members`'] = 40;
        $wpdb->queryResults['SELECT COUNT(*) FROM `wp_acx_persons` p WHERE NOT EXISTS (SELECT 1 FROM `wp_acx_clusters` c WHERE c.person_id = p.id)'] = 3;

        $request = new WP_REST_Request('GET', '/acx/v1/dashboard/stats');
        $response = $this->api->get_dashboard_stats($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $data = $response->get_data();

        $this->assertSame(10, $data['people_count']);
        $this->assertSame(25, $data['assigned_clusters_count']);
        $this->assertSame(15, $data['pending_clusters_count']);
        $this->assertSame(40, $data['media_with_faces_count']);
        $this->assertSame(3, $data['unassigned_persons_count']);
    }
}
