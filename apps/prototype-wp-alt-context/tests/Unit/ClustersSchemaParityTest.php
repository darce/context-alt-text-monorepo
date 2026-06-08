<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * rg-005: columns referenced by the clusters repository layer SQL must exist in
 * the clusters DDL. The DDL column set is parsed live from
 * class-life-cycle-manager.php — never hand-duplicated — so a fabricated or
 * renamed column is actually caught.
 *
 * @coversNothing
 */
class ClustersSchemaParityTest extends TestCase
{
    /** @var string[] Columns the repository-layer SQL references (2026-06-07). */
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

    public function testRepositoryColumnsExistInClustersDdl(): void
    {
        $ddlColumns = $this->parseClustersDdlColumns();

        $this->assertSame(
            [],
            $this->columnsMissingFrom(self::REPOSITORY_COLUMNS, $ddlColumns),
            'Repository SQL references columns absent from the clusters DDL'
        );
    }

    public function testEveryRepositoryColumnIsReferencedInTheRepositoryLayer(): void
    {
        $source = $this->repositoryLayerSource();

        foreach (self::REPOSITORY_COLUMNS as $column) {
            $this->assertStringContainsString(
                $column,
                $source,
                "No repository-layer file references {$column}; prune it from REPOSITORY_COLUMNS or restore the SQL"
            );
        }
    }

    public function testParityGuardDetectsFabricatedColumn(): void
    {
        $ddlColumns = $this->parseClustersDdlColumns();
        $fabricated = 'fabricated_column_xyz';

        $this->assertNotContains($fabricated, $ddlColumns, 'precondition: fabricated column must not exist in DDL');
        $this->assertSame(
            [$fabricated],
            $this->columnsMissingFrom([$fabricated], $ddlColumns),
            'guard must flag a column missing from the parsed DDL'
        );
    }

    /**
     * @param string[] $candidates
     * @param string[] $ddlColumns
     * @return string[]
     */
    private function columnsMissingFrom(array $candidates, array $ddlColumns): array
    {
        return array_values(array_filter(
            $candidates,
            static fn (string $column): bool => ! in_array($column, $ddlColumns, true)
        ));
    }

    /**
     * Parse the clusters CREATE TABLE block from the life-cycle manager and
     * return its real column names (excluding key/index definitions).
     *
     * @return string[]
     */
    private function parseClustersDdlColumns(): array
    {
        $ddlPath = dirname(__DIR__, 2) . '/src/support/class-life-cycle-manager.php';
        $ddl = (string) file_get_contents($ddlPath);

        if (! preg_match('/CREATE TABLE \{\$clusters_table\} \((.*?)\)\s*\{\$charset_collate\};/s', $ddl, $matches)) {
            $this->fail('Could not locate the clusters CREATE TABLE block in class-life-cycle-manager.php');
        }

        $lines = preg_split('/\r?\n/', $matches[1]);
        if (! is_array($lines)) {
            $lines = [];
        }

        $columns = [];
        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            if (preg_match('/^(PRIMARY\s+KEY|UNIQUE\s+KEY|FULLTEXT\s+KEY|FOREIGN\s+KEY|CONSTRAINT|KEY)\b/i', $line)) {
                continue;
            }
            if (preg_match('/^([a-z_][a-z0-9_]*)\s+\S/i', $line, $columnMatch)) {
                $columns[] = $columnMatch[1];
            }
        }

        $this->assertNotEmpty($columns, 'parsed clusters DDL yielded no columns — parser is broken');

        return $columns;
    }

    /**
     * Concatenated source of the whole clusters repository layer (facade +
     * extracted collaborators), so column references survive the REFA-2 split.
     */
    private function repositoryLayerSource(): string
    {
        $dir = dirname(__DIR__, 2) . '/src/sovereign/repositories';
        $files = glob($dir . '/class-cluster*.php');
        if (! is_array($files)) {
            $files = [];
        }
        $this->assertNotEmpty($files, 'no clusters repository-layer source files found');

        $source = '';
        foreach ($files as $file) {
            $source .= (string) file_get_contents($file);
        }

        return $source;
    }
}
