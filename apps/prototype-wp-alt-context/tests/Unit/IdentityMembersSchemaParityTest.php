<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * Narrow hand-maintained allowlist for the identity-members repository layer
 * only (not a general SQL↔DDL scanner — that is ProjectionQueryColumnParityTest).
 *
 * Asserts:
 *  - MEMBERS_COLUMNS / CLUSTERS_COLUMNS / PERSONS_COLUMNS are subsets of the
 *    matching CREATE TABLE blocks in class-life-cycle-manager.php
 *  - each allowlisted name still appears somewhere in the identity-members
 *    repository-layer sources
 *  - identity_members INSERT/upsert write columns scraped from that layer
 *    exist in the members DDL (live write-path check)
 *
 * Does not scan other repositories, derived tables, or $wpdb->insert maps.
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
        'assigned_at',
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

    /**
     * Concrete floors for the live SQL↔DDL parity walk (not merely > 0).
     * Tied to the identity_members INSERT column list and CREATE TABLE as of
     * 2026-07-30: twelve write columns, twelve DDL columns. A scrape that only
     * finds one of twelve still fails the floor [rg-005].
     */
    private const SQL_WRITE_COLUMN_FLOOR = 12;

    private const MEMBERS_DDL_COLUMN_FLOOR = 12;

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
     * Live-parity check: the identity_members write columns the repository SQL
     * actually names — parsed straight out of its INSERT/upsert statements —
     * must all exist in the parsed identity_members DDL, without trusting the
     * MEMBERS_COLUMNS allowlist.
     */
    public function testSqlWriteColumnsExistInMembersDdl(): void
    {
        $referenced = $this->parseSqlWriteColumns($this->repositoryLayerSource());
        $ddlColumns = $this->parseDdlColumns('members_table');

        // Concrete floors on both sides before comparing — empty-vs-empty (or
        // 1-of-N scrape drift) must not pass as clean parity [rg-005].
        $this->assertGreaterThanOrEqual(
            self::SQL_WRITE_COLUMN_FLOOR,
            count($referenced),
            sprintf(
                'identity-members SQL write-column scrape resolved %d column(s); expected at least %d — parser or corpus is broken',
                count($referenced),
                self::SQL_WRITE_COLUMN_FLOOR
            )
        );
        $this->assertGreaterThanOrEqual(
            self::MEMBERS_DDL_COLUMN_FLOOR,
            count($ddlColumns),
            sprintf(
                'identity_members DDL parse resolved %d column(s); expected at least %d — DDL parser or life-cycle source is broken',
                count($ddlColumns),
                self::MEMBERS_DDL_COLUMN_FLOOR
            )
        );

        $this->assertSame(
            [],
            $this->columnsMissingFrom($referenced, $ddlColumns),
            'identity-members repository SQL writes columns absent from the identity_members DDL'
        );
    }

    public function testSqlWriteColumnGuardDetectsFabricatedColumn(): void
    {
        $sql = "INSERT INTO %i\n(identity_uuid, fabricated_member_write_xyz)\nVALUES (%s, %s)";
        $referenced = $this->parseSqlWriteColumns($sql);

        $this->assertContains(
            'fabricated_member_write_xyz',
            $referenced,
            'parser must extract every identifier from the INSERT column list'
        );
        $this->assertSame(
            ['fabricated_member_write_xyz'],
            $this->columnsMissingFrom($referenced, $this->parseDdlColumns('members_table')),
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
     * lists (followed by either VALUES or an INSERT...SELECT row source) and
     * `VALUES(col)` upsert back-references. Both name columns of the single
     * identity_members table being written, so the parsed set is a clean
     * DDL-subset candidate (unlike SELECT/JOIN lists, which span tables). Only
     * these SQL-specific shapes are matched so the parser never trips on the
     * surrounding PHP source; `VALUES` is matched case-sensitively so PHP's
     * lower-case array_values() is not mistaken for an upsert back-reference.
     *
     * @return string[]
     */
    private function parseSqlWriteColumns(string $source): array
    {
        $columns = [];

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

        if (preg_match_all('/VALUES\s*\(\s*([a-z_][a-z0-9_]*)\s*\)/', $source, $valueMatches)) {
            foreach ($valueMatches[1] as $candidate) {
                $columns[$candidate] = true;
            }
        }

        return array_keys($columns);
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

        // Floor is enforced by callers that need a concrete count (members live
        // parity). Keep a non-empty guard here so empty DDL never silently
        // compares equal to an empty candidate list.
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
