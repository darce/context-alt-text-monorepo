<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\MemberConflictRecorder;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\MemberConflictRecorder
 */
class MemberConflictRecorderTest extends TestCase
{
    public function testIsMemberClusterConflictDetectsClusterMismatch(): void
    {
        $recorder = new MemberConflictRecorder(new ConflictRepository());

        $this->assertTrue(
            $recorder->is_member_cluster_conflict(
                ['cluster_uuid' => 'cluster-local'],
                'cluster-remote'
            )
        );
        $this->assertFalse(
            $recorder->is_member_cluster_conflict(
                ['cluster_uuid' => 'cluster-same'],
                'cluster-same'
            )
        );
    }

    public function testRecordMissingCuratedMemberConflictsWritesSyncConflict(): void
    {
        $repository = new class() extends ConflictRepository {
            /** @var list<array<string,mixed>> */
            public array $recorded = [];

            public function record_projection_conflict(
                string $tenant_id,
                string $entity_type,
                string $entity_key,
                string $conflict_code,
                int $backend_version,
                int $expected_base_version,
                int $local_revision,
                array $machine_payload,
                array $local_payload
            ): int|false {
                global $wpdb;
                $wpdb->queries[] = sprintf(
                    "INSERT INTO `wp_acx_sync_conflicts` ('%s')",
                    $conflict_code
                );

                return 1;
            }
        };

        $recorder = new MemberConflictRecorder($repository);
        $recorder->record_missing_curated_member_conflicts(
            'tenant-conflict-recorder',
            [
                'identity-missing' => [
                    'identity_uuid' => 'identity-missing',
                    'cluster_uuid' => 'cluster-missing',
                    'projection_version' => 3,
                ],
            ],
            [],
            4
        );

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString("'curated_member_deleted'", $sql);
    }
}
