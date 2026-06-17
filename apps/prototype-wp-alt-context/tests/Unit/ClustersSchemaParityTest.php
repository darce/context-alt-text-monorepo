<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * rg-005: columns the clusters repository SQL references must exist in the
 * clusters DDL. Two complementary checks:
 *
 *  - Live parity: the DDL column set is parsed live from
 *    class-life-cycle-manager.php and the SQL write columns are parsed live
 *    from the repository-layer INSERT/upsert statements, so a fabricated or
 *    renamed *write* column is caught directly from the SQL
 *    (testSqlWriteColumnsExistInClustersDdl).
 *  - Allowlist: REPOSITORY_COLUMNS is a hand-maintained list kept as a
 *    secondary belt-and-suspenders check covering read/where columns the SQL
 *    parser does not extract. On its own it does not prove the SQL matches the
 *    DDL — that is what the live-parity check adds.
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
            // Word-boundary match so a substring column (e.g. `label`) is not
            // falsely satisfied by a longer one (`suggested_label`).
            $this->assertMatchesRegularExpression(
                '/\b' . preg_quote($column, '/') . '\b/',
                $source,
                "No repository-layer file references {$column} as a standalone column; prune it from REPOSITORY_COLUMNS or restore the SQL"
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
     * Live-parity check: the write columns the repository SQL actually names —
     * parsed straight out of its INSERT/upsert statements — must all exist in
     * the parsed DDL. Unlike testRepositoryColumnsExistInClustersDdl this does
     * not trust the hand-maintained allowlist; a renamed or fabricated write
     * column in the SQL is caught even if REPOSITORY_COLUMNS was never updated.
     */
    public function testSqlWriteColumnsExistInClustersDdl(): void
    {
        $referenced = $this->parseSqlWriteColumns($this->repositoryLayerSource());

        $this->assertNotEmpty(
            $referenced,
            'parser found no INSERT/upsert write columns in the clusters repository SQL — parser or corpus is broken'
        );

        $this->assertSame(
            [],
            $this->columnsMissingFrom($referenced, $this->parseClustersDdlColumns()),
            'Clusters repository SQL writes columns absent from the clusters DDL'
        );
    }

    public function testSqlWriteColumnGuardDetectsFabricatedColumn(): void
    {
        $sql = "INSERT INTO %i\n(cluster_uuid, fabricated_write_column_xyz)\nVALUES (%s, %s)";
        $referenced = $this->parseSqlWriteColumns($sql);

        $this->assertContains(
            'fabricated_write_column_xyz',
            $referenced,
            'parser must extract every identifier from the INSERT column list'
        );
        $this->assertSame(
            ['fabricated_write_column_xyz'],
            $this->columnsMissingFrom($referenced, $this->parseClustersDdlColumns()),
            'live-parity guard must flag an SQL write column missing from the DDL'
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
     * Parse the column identifiers the repository SQL writes — INSERT column
     * lists and `VALUES(col)` upsert back-references. Both name columns of the
     * single table being written, so the parsed set is a clean DDL-subset
     * candidate (unlike SELECT/JOIN lists, which span tables). Only these two
     * SQL-specific shapes are matched so the parser never trips on the
     * surrounding PHP source; `VALUES` is matched case-sensitively so PHP's
     * lower-case array_values() is not mistaken for an upsert back-reference.
     *
     * @return string[]
     */
    private function parseSqlWriteColumns(string $source): array
    {
        $columns = [];

        // INSERT INTO <table> (col, col, ...) VALUES|SELECT — the parenthesised
        // list before the VALUES or INSERT...SELECT row source is the write
        // column list.
        if (preg_match_all('/INSERT INTO\s+\S+\s*\(([^)]*)\)\s*(?:VALUES|SELECT)\b/i', $source, $insertMatches)) {
            foreach ($insertMatches[1] as $columnList) {
                foreach (preg_split('/\s*,\s*/', trim($columnList)) as $candidate) {
                    $candidate = trim((string) $candidate);
                    if (preg_match('/^[a-z_][a-z0-9_]*$/', $candidate)) {
                        $columns[$candidate] = true;
                    }
                }
            }
        }

        // ON DUPLICATE KEY UPDATE ... VALUES(col) back-references.
        if (preg_match_all('/VALUES\s*\(\s*([a-z_][a-z0-9_]*)\s*\)/', $source, $valueMatches)) {
            foreach ($valueMatches[1] as $candidate) {
                $columns[$candidate] = true;
            }
        }

        return array_keys($columns);
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
