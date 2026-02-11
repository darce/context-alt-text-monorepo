<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\SnapshotProjector;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Sync\SnapshotProjector
 * @covers \AltContext\Sovereign\Repositories\ClustersRepository
 * @covers \AltContext\Sovereign\Repositories\IdentityMembersRepository
 * @covers \AltContext\Sovereign\Repositories\SyncStateRepository
 */
class SovereignProjectionIntegrationTest extends TestCase
{
    public function testFixtureSnapshotProjectionWritesExpectedReadModelRowPayloads(): void
    {
        $projector = new SnapshotProjector(
            new ClustersRepository(),
            new IdentityMembersRepository(),
            new SyncStateRepository()
        );

        $projector->project(
            'tenant-integration',
            [
                'snapshot_version' => 31,
                'clusters' => [
                    [
                        'cluster_uuid' => 'cluster-int-1',
                        'label' => 'Daniel',
                        'curation_state' => 'confirmed',
                        'is_user_confirmed' => true,
                        'identity_count' => 2,
                        'representative_media_id' => 901,
                    ],
                ],
                'members' => [
                    [
                        'identity_uuid' => 'identity-int-1',
                        'cluster_uuid' => 'cluster-int-1',
                        'attachment_id' => 901,
                        'bbox' => [
                            'x' => 10,
                            'y' => 20,
                            'width' => 50,
                            'height' => 60,
                        ],
                        'image_width' => 1000,
                        'image_height' => 800,
                        'similarity' => 0.91,
                    ],
                ],
            ]
        );

        global $wpdb;
        $queries = $wpdb->queries;
        $sql = implode("\n", $queries);

        $this->assertStringContainsString('START TRANSACTION', $sql);
        $this->assertStringContainsString('COMMIT', $sql);

        $clusterInsert = $this->findQueryContaining($queries, 'INSERT INTO `wp_acx_clusters`');
        $this->assertStringContainsString("'cluster-int-1'", $clusterInsert);
        $this->assertStringContainsString("'tenant-integration'", $clusterInsert);
        $this->assertStringContainsString("'Daniel'", $clusterInsert);
        $this->assertStringContainsString("'confirmed'", $clusterInsert);
        $this->assertStringContainsString("'acx://cluster/cluster-int-1/media/901'", $clusterInsert);
        $this->assertStringContainsString(', 2, 31, 1,', $clusterInsert);

        $memberInsert = $this->findQueryContaining($queries, 'INSERT INTO `wp_acx_identity_members`');
        $this->assertStringContainsString("SELECT 'identity-int-1', 'cluster-int-1', 901", $memberInsert);
        $this->assertStringContainsString('\\"pixels\\":{\\"x\\":10,\\"y\\":20,\\"width\\":50,\\"height\\":60}', $memberInsert);
        $this->assertStringContainsString('\\"normalized\\":{\\"x\\":0.01,\\"y\\":0.025,\\"width\\":0.05,\\"height\\":0.075}', $memberInsert);
        $this->assertStringContainsString("NULLIF('0.91', '')", $memberInsert);

        $syncInsert = $this->findQueryContaining($queries, 'INSERT INTO `wp_acx_sync_state`');
        $this->assertStringContainsString("'tenant:tenant-integration:clusters'", $syncInsert);
        $this->assertStringContainsString(', 31,', $syncInsert);
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
