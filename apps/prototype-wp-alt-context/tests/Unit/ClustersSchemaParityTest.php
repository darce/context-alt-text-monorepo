<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * rg-005: columns referenced by ClustersRepository SQL must exist in clusters DDL.
 *
 * @coversNothing
 */
class ClustersSchemaParityTest extends TestCase
{
    /** @var string[] Columns verified present in class-clusters-repository.php SQL (2026-06-07). */
    private const REPOSITORY_COLUMNS = [
        'cluster_uuid',
        'tenant_id',
        'label',
        'curation_state',
        'person_id',
        'representative_thumb_path',
        'representative_id',
        'is_pinned',
        'identity_count',
        'snapshot_version',
        'is_user_confirmed',
        'local_revision',
        'created_at',
        'updated_at',
        'last_synced_at',
        'suggested_label',
        'suggested_label_source',
        'suggested_label_confidence',
        'suggested_target_cluster_id',
    ];

    /** @var string[] Parsed from class-life-cycle-manager.php clusters DDL block. */
    private const DDL_COLUMNS = [
        'cluster_uuid',
        'tenant_id',
        'label',
        'curation_state',
        'person_id',
        'representative_thumb_path',
        'representative_id',
        'is_pinned',
        'identity_count',
        'snapshot_version',
        'is_user_confirmed',
        'local_revision',
        'created_at',
        'updated_at',
        'last_synced_at',
        'suggested_label',
        'suggested_label_source',
        'suggested_label_confidence',
        'suggested_target_cluster_id',
    ];

    public function testRepositoryColumnsExistInClustersDdl(): void
    {
        $ddlPath = dirname(__DIR__, 2) . '/src/support/class-life-cycle-manager.php';
        $repoPath = dirname(__DIR__, 2) . '/src/sovereign/repositories/class-clusters-repository.php';
        $ddl = (string) file_get_contents($ddlPath);
        $repo = (string) file_get_contents($repoPath);

        $missing = [];
        foreach (self::REPOSITORY_COLUMNS as $column) {
            if (! in_array($column, self::DDL_COLUMNS, true)) {
                $missing[] = $column;
                continue;
            }
            $this->assertStringContainsString($column, $ddl, "DDL missing column {$column}");
            $this->assertStringContainsString($column, $repo, "Repository should reference {$column}");
        }

        $this->assertSame([], $missing);
    }

    public function testParityGuardDetectsFabricatedColumn(): void
    {
        $fabricated = 'fabricated_column_xyz';
        $this->assertNotContains($fabricated, self::DDL_COLUMNS);
        $this->assertContains($fabricated, array_merge(self::REPOSITORY_COLUMNS, [$fabricated]));
        $this->assertNotContains($fabricated, self::DDL_COLUMNS);
    }
}