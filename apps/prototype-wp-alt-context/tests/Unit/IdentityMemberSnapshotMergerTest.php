<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\IdentityMembersReadRepository;
use AltContext\Sovereign\Repositories\IdentityMemberSnapshotMerger;
use AltContext\Sovereign\Repositories\MemberConflictRecorder;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\IdentityMemberSnapshotMerger
 */
class IdentityMemberSnapshotMergerTest extends TestCase
{
    private IdentityMemberSnapshotMerger $merger;

    protected function setUp(): void
    {
        parent::setUp();
        $readRepository = new IdentityMembersReadRepository('wp_acx_identity_members', 'wp_acx_clusters');
        $conflictRecorder = new MemberConflictRecorder(new ConflictRepository());
        $this->merger = new IdentityMemberSnapshotMerger(
            'wp_acx_identity_members',
            'wp_acx_clusters',
            $readRepository,
            $conflictRecorder
        );
    }

    public function testMergeSnapshotIssuesPerMemberInsert(): void
    {
        $this->merger->merge_snapshot_for_tenant(
            'tenant-merger',
            [
                [
                    'identity_uuid' => 'identity-merger-1',
                    'cluster_uuid' => 'cluster-merger',
                    'attachment_id' => 5,
                ],
            ],
            7
        );

        global $wpdb;
        $insertCount = 0;
        foreach ($wpdb->queries as $query) {
            if (str_contains($query, 'INSERT INTO `wp_acx_identity_members`')) {
                ++$insertCount;
            }
        }

        $this->assertSame(1, $insertCount);
    }

    public function testMergeSnapshotGatesMemberDataAndKeepsProjectionVersionMonotonic(): void
    {
        // COR-1 (PA-2 mechanism assertion): a stale member snapshot must not
        // regress data or lower projection_version for non-curated rows.
        $this->merger->merge_snapshot_for_tenant(
            'tenant-merger',
            [
                [
                    'identity_uuid' => 'identity-ver',
                    'cluster_uuid' => 'cluster-ver',
                    'attachment_id' => 9,
                ],
            ],
            12
        );

        global $wpdb;
        $insert = '';
        foreach ($wpdb->queries as $query) {
            if (str_contains($query, 'INSERT INTO `wp_acx_identity_members`')) {
                $insert = $query;
                break;
            }
        }

        $this->assertNotSame('', $insert, 'expected a per-member INSERT query');
        $this->assertStringContainsString('projection_version = IF(is_curated = 1, projection_version, GREATEST(projection_version, VALUES(projection_version)))', $insert);
        $this->assertStringContainsString('attachment_id = IF(VALUES(projection_version) >= projection_version, VALUES(attachment_id), attachment_id)', $insert);
        $this->assertStringContainsString('thumb_path = IF(VALUES(projection_version) >= projection_version, VALUES(thumb_path), thumb_path)', $insert);
        $this->assertStringContainsString('bbox_json = IF(VALUES(projection_version) >= projection_version, VALUES(bbox_json), bbox_json)', $insert);
        // The curation guard on cluster_uuid is preserved.
        $this->assertStringContainsString('cluster_uuid = IF(is_curated = 1, cluster_uuid, VALUES(cluster_uuid))', $insert);
    }

    public function testAssignToClusterForProjectionUsesGreatest(): void
    {
        $this->merger->assign_to_cluster_for_projection('identity-proj-merger', 'cluster-proj-merger', 19);

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('projection_version = GREATEST(projection_version, 19)', $sql);
    }
}
