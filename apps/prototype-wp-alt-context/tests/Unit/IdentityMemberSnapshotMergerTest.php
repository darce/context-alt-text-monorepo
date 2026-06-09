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

    public function testAssignToClusterForProjectionUsesGreatest(): void
    {
        $this->merger->assign_to_cluster_for_projection('identity-proj-merger', 'cluster-proj-merger', 19);

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('projection_version = GREATEST(projection_version, 19)', $sql);
    }
}
