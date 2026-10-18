<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClusterDeletionService;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\ClusterDeletionService
 */
class ClusterDeletionServiceTest extends TestCase
{
    private ClusterDeletionService $service;

    protected function setUp(): void
    {
        parent::setUp();
        $this->service = new ClusterDeletionService('wp_acx_clusters');
    }

    public function testDeleteClusterWithMembersDeletesMembersThenCluster(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->service->delete_cluster_with_members('cluster-del', self::currentTenantId());

        $this->assertSame(1, $result);
        $this->assertCount(2, $wpdb->queries);
        $membersDelete = $wpdb->queries[0];
        $clusterDelete = $wpdb->queries[1];
        $this->assertStringContainsString('DELETE m FROM `wp_acx_identity_members`', $membersDelete);
        $this->assertStringContainsString('INNER JOIN `wp_acx_clusters`', $membersDelete);
        $this->assertStringContainsString("cluster_uuid = 'cluster-del'", $membersDelete);
        $this->assertStringContainsString('DELETE FROM `wp_acx_clusters`', $clusterDelete);
        $this->assertStringContainsString("tenant_id = '" . self::currentTenantId() . "'", $clusterDelete);
    }
}
