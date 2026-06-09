<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * rg-005: columns referenced by the identity-members repository SQL must exist in
 * the identity_members / clusters / persons DDL. Parsed live from
 * class-life-cycle-manager.php — never hand-duplicated.
 *
 * @coversNothing
 */
class IdentityMembersSchemaParityTest extends TestCase
{
    /** @var string[] identity_members columns the repository layer writes or selects. */
    private const MEMBERS_COLUMNS = [
        'identity_uuid',
        'cluster_uuid',
        'attachment_id',
        'bbox_json',
        'thumb_path',
        'similarity',
        'similarity_threshold',
        'is_curated',
        'projection_version',
        'created_at',
        'updated_at',
    ];

    /** @var string[] clusters columns joined or filtered in member queries. */
    private const CLUSTERS_COLUMNS = [
        'cluster_uuid',
        'tenant_id',
        'label',
        'curation_state',
        'person_id',
        'is_user_confirmed',
        'representative_id',
        'is_pinned',
    ];

    /** @var string[] persons columns joined for cluster labels. */
    private const PERSONS_COLUMNS = [
        'id',
        'name',
    ];

    public function testMembersColumnsExistInIdentityMembersDdl(): void
    {
        $ddlColumns = $this->parseDdlColumns('members_table');

        $this->assertSame(
            [],
            $this->columnsMissingFrom(self::MEMBERS_COLUMNS, $ddlColumns),
            'Repository SQL references identity_members columns absent from DDL'
        );
    }

    public function testClustersColumnsExistInClustersDdl(): void
    {
        $ddlColumns = $this->parseDdlColumns('clusters_table');

        $this->assertSame(
            [],
            $this->columnsMissingFrom(self::CLUSTERS_COLUMNS, $ddlColumns),
            'Repository SQL references clusters columns absent from DDL'
        );
    }

    public function testPersonsColumnsExistInPersonsDdl(): void
    {
        $ddlColumns = $this->parseDdlColumns('persons_table');

        $this->assertSame(
            [],
            $this->columnsMissingFrom(self::PERSONS_COLUMNS, $ddlColumns),
            'Repository SQL references persons columns absent from DDL'
        );
    }

    public function testEveryMembersColumnIsReferencedInRepositorySource(): void
    {
        $source = $this->repositoryLayerSource();

        foreach (self::MEMBERS_COLUMNS as $column) {
            $this->assertMatchesRegularExpression(
                '/\b' . preg_quote($column, '/') . '\b/',
                $source,
                "Repository source does not reference identity_members column {$column}"
            );
        }
    }

    public function testEveryClustersColumnIsReferencedInRepositorySource(): void
    {
        $source = $this->repositoryLayerSource();

        foreach (self::CLUSTERS_COLUMNS as $column) {
            $this->assertMatchesRegularExpression(
                '/\b' . preg_quote($column, '/') . '\b/',
                $source,
                "Repository source does not reference clusters column {$column}"
            );
        }
    }

    public function testEveryPersonsColumnIsReferencedInRepositorySource(): void
    {
        $source = $this->repositoryLayerSource();

        foreach (self::PERSONS_COLUMNS as $column) {
            $this->assertMatchesRegularExpression(
                '/\b' . preg_quote($column, '/') . '\b/',
                $source,
                "Repository source does not reference persons column {$column}"
            );
        }
    }

    public function testParityGuardDetectsFabricatedColumn(): void
    {
        $ddlColumns = $this->parseDdlColumns('members_table');
        $fabricated = 'fabricated_member_column_xyz';

        $this->assertNotContains($fabricated, $ddlColumns);
        $this->assertSame(
            [$fabricated],
            $this->columnsMissingFrom([$fabricated], $ddlColumns)
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
     * @return string[]
     */
    private function parseDdlColumns(string $tableVar): array
    {
        $patterns = [
            'members_table' => '/CREATE TABLE \{\$members_table\} \((.*?)\)\s*\{\$charset_collate\};/s',
            'clusters_table' => '/CREATE TABLE \{\$clusters_table\} \((.*?)\)\s*\{\$charset_collate\};/s',
            'persons_table' => '/CREATE TABLE \{\$persons_table\} \((.*?)\)\s*\{\$charset_collate\};/s',
        ];

        $ddlPath = dirname(__DIR__, 2) . '/src/support/class-life-cycle-manager.php';
        $ddl = (string) file_get_contents($ddlPath);

        if (! isset($patterns[$tableVar]) || ! preg_match($patterns[$tableVar], $ddl, $matches)) {
            $this->fail("Could not locate {$tableVar} CREATE TABLE block in class-life-cycle-manager.php");
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

        $this->assertNotEmpty($columns, "parsed {$tableVar} DDL yielded no columns");

        return $columns;
    }

    /**
     * Concatenated source of the identity-members repository layer (facade +
     * extracted collaborators) so column references survive the REFA-5 split.
     */
    private function repositoryLayerSource(): string
    {
        $dir = dirname(__DIR__, 2) . '/src/sovereign/repositories';
        $patterns = [
            $dir . '/class-identity-members*.php',
            $dir . '/class-identity-member-*.php',
            $dir . '/class-member-conflict-recorder.php',
            $dir . '/trait-normalizes-member-rows.php',
        ];

        $files = [];
        foreach ($patterns as $pattern) {
            $matches = glob($pattern);
            if (is_array($matches)) {
                $files = array_merge($files, $matches);
            }
        }

        $files = array_values(array_unique($files));
        $this->assertNotEmpty($files, 'no identity-members repository-layer source files found');

        $source = '';
        foreach ($files as $file) {
            $source .= (string) file_get_contents($file);
        }

        return $source;
    }
}
