<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\ClustersRepository
 */
class ClustersRepositoryMutationTest extends TestCase
{
    private ClustersRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClustersRepository();
    }

    public function testUpdateLabelScaffold(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->update_label('cluster-123', 'Ada Lovelace');

        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString("UPDATE `wp_acx_clusters` SET label = 'Ada Lovelace'", $query);
        $this->assertStringContainsString('is_user_confirmed = 1', $query);
        $this->assertStringContainsString("WHERE cluster_uuid = 'cluster-123'", $query);
        $this->assertSame(1, $result);
    }

    public function testUpdateLabelCanSkipUserConfirmation(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->update_label('cluster-123', 'Ada Lovelace', false);

        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString("UPDATE `wp_acx_clusters` SET label = 'Ada Lovelace', is_user_confirmed = 0", $query);
        $this->assertStringContainsString("WHERE cluster_uuid = 'cluster-123'", $query);
        $this->assertSame(1, $result);
    }

    public function testDismissScaffold(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->dismiss('cluster-456');

        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString("UPDATE `wp_acx_clusters` SET curation_state = 'dismissed'", $query);
        $this->assertStringContainsString('is_user_confirmed = 1', $query);
        $this->assertStringContainsString('local_revision = local_revision + 1', $query);
        $this->assertStringContainsString("WHERE cluster_uuid = 'cluster-456'", $query);
        $this->assertSame(1, $result);
    }

    public function testUndismissScaffold(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->undismiss('cluster-789');

        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString("UPDATE `wp_acx_clusters` SET curation_state = 'uncurated'", $query);
        $this->assertStringContainsString('is_user_confirmed = 0', $query);
        $this->assertStringContainsString('local_revision = local_revision + 1', $query);
        $this->assertStringContainsString("WHERE cluster_uuid = 'cluster-789'", $query);
        $this->assertSame(1, $result);
    }

    public function testUpdateLabelClearsSuggestedLabelColumns(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $this->repository->update_label('cluster-abc', 'Bob');

        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('suggested_label = NULL', $query);
        $this->assertStringContainsString('suggested_label_source = NULL', $query);
        $this->assertStringContainsString('suggested_label_confidence = NULL', $query);
        $this->assertStringContainsString('suggested_target_cluster_id = NULL', $query);
    }
}
