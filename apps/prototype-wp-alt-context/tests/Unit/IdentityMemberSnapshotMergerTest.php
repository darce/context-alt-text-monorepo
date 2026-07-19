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
                    // GFR-02 discrimination: the snapshot's assigned_at VALUE must land in
                    // the INSERT (asserting the column name alone is vacuous — it is always
                    // in the column list). A far-past value distinguishes it from any $now_utc
                    // write, so the assertion goes red if the merger stops honoring the snapshot.
                    'assigned_at' => '2024-06-01T10:15:30+00:00',
                ],
            ],
            7
        );

        global $wpdb;
        $insertCount = 0;
        $insert = '';
        foreach ($wpdb->queries as $query) {
            if (str_contains($query, 'INSERT INTO `wp_acx_identity_members`')) {
                ++$insertCount;
                $insert = $query;
            }
        }

        $this->assertSame(1, $insertCount);
        $this->assertStringContainsString('2024-06-01 10:15:30', $insert);
    }

    /**
     * GFR-02 / rg-005: when a member snapshot OMITS assigned_at, the merger must fall back to
     * the snapshot's created_at (converted to MySQL UTC), NOT $now_utc. Injecting a far-past
     * created_at makes this discriminate — a $now_utc (current-time) write would drop the fixed
     * past value, so this goes red if the merger silently timestamps every row with "now".
     */
    public function testMergeSnapshotAssignedAtFallsBackToCreatedAtNotNow(): void
    {
        $this->merger->merge_snapshot_for_tenant(
            'tenant-merger-fallback',
            [
                [
                    'identity_uuid' => 'identity-fallback-1',
                    'cluster_uuid' => 'cluster-merger',
                    'attachment_id' => 9,
                    // No assigned_at → the merger must use created_at, never a fresh $now_utc.
                    'created_at' => '2024-01-15T00:00:00+00:00',
                ],
            ],
            7
        );

        global $wpdb;
        $insert = '';
        foreach ($wpdb->queries as $query) {
            if (str_contains($query, 'INSERT INTO `wp_acx_identity_members`')) {
                $insert = $query;
            }
        }

        $this->assertNotSame('', $insert, 'expected a per-member INSERT query');
        // The created_at fallback flows into assigned_at (created_at/updated_at columns are $now_utc).
        $this->assertStringContainsString('2024-01-15 00:00:00', $insert);
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

    public function testMergeSnapshotWithStormSuppressionSkipsPerEntityConflictWritesButKeepsCurationProtection(): void
    {
        global $wpdb;
        // One curated member that the incoming snapshot reassigns, one it deletes.
        $wpdb->mockResults = [
            [
                'identity_uuid' => 'identity-moved',
                'cluster_uuid' => 'cluster-local',
                'projection_version' => 4,
            ],
            [
                'identity_uuid' => 'identity-gone',
                'cluster_uuid' => 'cluster-local',
                'projection_version' => 4,
            ],
        ];

        $this->merger->merge_snapshot_for_tenant(
            'tenant-suppressed',
            [
                [
                    'identity_uuid' => 'identity-moved',
                    'cluster_uuid' => 'cluster-remote',
                    'attachment_id' => 5,
                ],
            ],
            9,
            true
        );

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringNotContainsString('wp_acx_sync_conflicts', $sql, 'suppressed merge must record zero per-entity conflicts');
        $this->assertStringNotContainsString("INSERT INTO `wp_acx_identity_members`", $sql, 'curated reassignment target must stay protected while suppressed');
    }

    public function testAssignToClusterForProjectionUsesGreatest(): void
    {
        $this->merger->assign_to_cluster_for_projection('identity-proj-merger', 'cluster-proj-merger', 19);

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('projection_version = GREATEST(projection_version, 19)', $sql);
    }
}
