<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;
use ReflectionMethod;

/**
 * E21-14 wave-3 schema verification: SV-01, SV-02, SV-03, SV-04, SV-06, LO-03.
 *
 * @covers \AltContext\Support\LifecycleManager
 */
class SchemaVerificationTest extends TestCase
{
    private LifecycleManager $manager;

    protected function setUp(): void
    {
        parent::setUp();
        $this->manager = new LifecycleManager();
        unset(
            $GLOBALS['__ac_dbdelta_silent_skip_column'],
            $GLOBALS['__ac_dbdelta_silent_skip_table'],
            $GLOBALS['__ac_show_columns_error'],
            $GLOBALS['__ac_show_columns_error_table']
        );
    }

    protected function tearDown(): void
    {
        unset(
            $GLOBALS['__ac_dbdelta_silent_skip_column'],
            $GLOBALS['__ac_dbdelta_silent_skip_table'],
            $GLOBALS['__ac_show_columns_error'],
            $GLOBALS['__ac_show_columns_error_table']
        );
        parent::tearDown();
    }

    // -------------------------------------------------------------------------
    // SV-01 — empty intended-column parse fails closed (RLSE-05, OBS-08)
    // -------------------------------------------------------------------------

    public function testVerifierFailsClosedWhenCreateTableBodyCannotBeParsed(): void
    {
        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];

        $mgr = new LifecycleManagerSchemaOverride();
        // Regex cannot extract a parenthesised body → empty intended set.
        $mgr->statementsOverride = [
            'acx_persons' => 'CREATE TABLE wp_acx_persons;',
        ];

        $mgr->maybe_upgrade();

        $this->assertSame(
            '0.0.1-stale',
            get_option('acx_version'),
            'SV-01: unparseable CREATE TABLE must not stamp acx_version'
        );
        $this->assertFalse(
            get_option('acx_schema_fingerprint'),
            'SV-01: unparseable CREATE TABLE must not stamp fingerprint'
        );
        $joined = \implode("\n", $this->getErrorLog());
        $this->assertStringContainsString(
            'acx_persons',
            $joined,
            'SV-01: telemetry must name the table whose intended columns could not be parsed'
        );
        $this->assertMatchesRegularExpression(
            '/parse|intended column|verifier/i',
            $joined,
            'SV-01: log must distinguish parse failure from missing columns'
        );
    }

    public function testVerifierFailsClosedWhenIntendedColumnSetIsEmpty(): void
    {
        $verify = new ReflectionMethod(LifecycleManager::class, 'verify_projection_schema_columns');
        $verify->setAccessible(true);

        $GLOBALS['__ac_error_log'] = [];
        // Body parses but yields only constraint lines → empty intended set.
        $sql = "CREATE TABLE wp_acx_persons (\n\tPRIMARY KEY (id)\n) DEFAULT CHARSET utf8mb4;";
        $result = $verify->invoke($this->manager, ['acx_persons' => $sql]);

        $this->assertFalse($result, 'SV-01: empty intended-column set is a verifier defect, not a pass');
        $this->assertStringContainsString('acx_persons', \implode("\n", $this->getErrorLog()));
    }

    // -------------------------------------------------------------------------
    // SV-02 — coverage for every owned table (TEST-15, OBS-08)
    // -------------------------------------------------------------------------

    /**
     * Derive (tableKey, column) pairs from build_projection_schema_statements only —
     * no hand-maintained second list (BR-02/BR-09). Prefer a column unique to that
     * table so silent-skip cannot fire first on an earlier map entry.
     *
     * @return array<string, array{0: string, 1: string}>
     */
    public static function everyProjectionTableColumnProvider(): array
    {
        $manager = new LifecycleManager();
        $statements = $manager->build_projection_schema_statements('wp_', '');
        $columnsByTable = [];
        foreach ($statements as $key => $sql) {
            $columnsByTable[$key] = self::extractColumnNamesForProvider($sql);
        }

        $cases = [];
        foreach ($columnsByTable as $key => $columns) {
            if ($columns === []) {
                $cases[$key . '::unparsed'] = [$key, '__unparsed__'];
                continue;
            }

            $column = null;
            foreach ($columns as $candidate) {
                $unique = true;
                foreach ($columnsByTable as $otherKey => $otherColumns) {
                    if ($otherKey === $key) {
                        continue;
                    }
                    if (\in_array($candidate, $otherColumns, true)) {
                        $unique = false;
                        break;
                    }
                }
                if ($unique) {
                    $column = $candidate;
                    break;
                }
            }
            if ($column === null) {
                $column = $columns[0];
            }

            $cases[$key . '::' . $column] = [$key, $column];
        }

        return $cases;
    }

    /**
     * Minimal CREATE TABLE line scanner used only to pick a column name for the
     * data provider. Production parsing lives on LifecycleManager.
     *
     * @return list<string>
     */
    private static function extractColumnNamesForProvider(string $sql): array
    {
        if (\method_exists(LifecycleManager::class, 'parse_create_table_column_names')) {
            $parsed = LifecycleManager::parse_create_table_column_names($sql);
            return \is_array($parsed) ? $parsed : [];
        }

        $columns = [];
        if (!\preg_match('/^CREATE TABLE\s+[^\s(]+\s*\((.*)\)\s*[^)]*;?$/si', \trim($sql), $matches)) {
            return [];
        }
        $definitions = \preg_split('/\R/', $matches[1]);
        if (! \is_array($definitions)) {
            $definitions = [];
        }
        foreach ($definitions as $definition) {
            if (\preg_match('/^\s*`?([a-zA-Z0-9_]+)`?\s+/', $definition, $columnMatch)) {
                $name = $columnMatch[1];
                if (!\in_array(\strtoupper($name), ['PRIMARY', 'KEY', 'UNIQUE', 'FULLTEXT', 'SPATIAL'], true)) {
                    $columns[] = $name;
                }
            }
        }

        return $columns;
    }

    /**
     * @dataProvider everyProjectionTableColumnProvider
     */
    public function testMaybeUpgradeRefusesStampWhenAnyOwnedTableMissesAColumn(
        string $tableKey,
        string $column
    ): void {
        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];
        $GLOBALS['__ac_dbdelta_silent_skip_column'] = $column;
        $GLOBALS['__ac_dbdelta_silent_skip_table'] = 'wp_' . $tableKey;

        $this->manager->maybe_upgrade();

        unset(
            $GLOBALS['__ac_dbdelta_silent_skip_column'],
            $GLOBALS['__ac_dbdelta_silent_skip_table']
        );

        $this->assertSame(
            '0.0.1-stale',
            get_option('acx_version'),
            \sprintf('SV-02: missing %s.%s must refuse acx_version stamp', $tableKey, $column)
        );
        $this->assertFalse(
            get_option('acx_schema_fingerprint'),
            \sprintf('SV-02: missing %s.%s must refuse fingerprint stamp', $tableKey, $column)
        );
        $joined = \implode("\n", $this->getErrorLog());
        $this->assertStringContainsString('wp_' . $tableKey, $joined);
        if ($column !== '__unparsed__') {
            $this->assertStringContainsString($column, $joined);
        }
    }

    // -------------------------------------------------------------------------
    // SV-03 — shared column grammar (one parser for production + stub)
    // -------------------------------------------------------------------------

    public function testParseCreateTableColumnNamesHandlesRealProjectionDdlShapes(): void
    {
        $statements = $this->manager->build_projection_schema_statements('wp_', 'DEFAULT CHARSET utf8mb4');
        $this->assertNotEmpty($statements);

        foreach ($statements as $key => $sql) {
            $columns = LifecycleManager::parse_create_table_column_names($sql);
            $this->assertIsArray(
                $columns,
                \sprintf('SV-03: parser must accept real DDL for %s', $key)
            );
            $this->assertNotEmpty(
                $columns,
                \sprintf('SV-03: parser must extract columns for %s', $key)
            );
            foreach (['PRIMARY', 'KEY', 'UNIQUE', 'FULLTEXT', 'SPATIAL', 'INDEX', 'CONSTRAINT', 'FOREIGN', 'CHECK'] as $kw) {
                $this->assertNotContains(
                    $kw,
                    $columns,
                    \sprintf('SV-03: %s must not appear as a column on %s', $kw, $key)
                );
            }
        }

        $members = $statements['acx_identity_members'] ?? '';
        $memberCols = LifecycleManager::parse_create_table_column_names($members);
        $this->assertContains('assigned_at', $memberCols);
        $this->assertContains('bbox_json', $memberCols);
        $this->assertContains('identity_uuid', $memberCols);

        // Multi-word type forms present in production DDL.
        $this->assertMatchesRegularExpression(
            "/assigned_at datetime\\(6\\) NOT NULL DEFAULT '1970-01-01 00:00:00\\.000000'/",
            $members
        );
        $this->assertStringContainsString('bbox_json longtext NOT NULL', $members);
    }

    public function testParseCreateTableColumnNamesRejectsConstraintAndIndexLines(): void
    {
        $sql = <<<'SQL'
CREATE TABLE wp_acx_demo (
	id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
	name varchar(191) NOT NULL DEFAULT '',
	body longtext NULL,
	PRIMARY KEY  (id),
	KEY idx_name (name),
	UNIQUE KEY uq_name (name),
	INDEX idx_extra (name),
	CONSTRAINT chk_name CHECK (name <> ''),
	FOREIGN KEY (id) REFERENCES other(id),
	CHECK (id > 0)
) DEFAULT CHARSET utf8mb4;
SQL;

        $columns = LifecycleManager::parse_create_table_column_names($sql);
        $this->assertSame(['id', 'name', 'body'], $columns);
    }

    public function testParseCreateTableColumnNamesReturnsNullForUnparseableSql(): void
    {
        $this->assertNull(
            LifecycleManager::parse_create_table_column_names('CREATE TABLE wp_acx_persons;'),
            'SV-03/SV-01: unparseable DDL must not yield an empty pass list'
        );
    }

    // -------------------------------------------------------------------------
    // SV-04 — SHOW COLUMNS failure fail-closed; clear stale last_error (AGT-10)
    // -------------------------------------------------------------------------

    public function testMaybeUpgradeDoesNotStampWhenShowColumnsErrors(): void
    {
        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];
        $GLOBALS['__ac_show_columns_error'] = "Table 'wp.wp_acx_persons' doesn't exist";
        $GLOBALS['__ac_show_columns_error_table'] = 'wp_acx_persons';

        $this->manager->maybe_upgrade();

        unset($GLOBALS['__ac_show_columns_error'], $GLOBALS['__ac_show_columns_error_table']);

        $this->assertSame('0.0.1-stale', get_option('acx_version'));
        $this->assertFalse(get_option('acx_schema_fingerprint'));
        $joined = \implode("\n", $this->getErrorLog());
        $this->assertStringContainsString('SHOW COLUMNS', $joined);
        $this->assertStringContainsString("doesn't exist", $joined);
        $this->assertStringNotContainsString(
            'missing columns:',
            $joined,
            'SV-04: SHOW COLUMNS failure must not be laundered as missing-columns'
        );
    }

    public function testMaybeUpgradeIgnoresStaleLastErrorWhenShowColumnsSucceeds(): void
    {
        global $wpdb;

        $this->setOption('acx_version', '0.0.1-stale');
        $wpdb->last_error = 'stale error from an earlier unrelated query';

        $this->manager->maybe_upgrade();

        $this->assertSame(
            ACX_VERSION,
            get_option('acx_version'),
            'SV-04: stale last_error must not cause a spurious verification failure'
        );
        $this->assertSame(
            $this->manager->compute_projection_schema_fingerprint(),
            get_option('acx_schema_fingerprint')
        );
        $this->assertSame('', $wpdb->last_error);
    }

    // -------------------------------------------------------------------------
    // SV-06 — INDEX/CONSTRAINT lines are not columns; stamp still lands
    // -------------------------------------------------------------------------

    public function testVerifierAcceptsIndexAndConstraintLinesAndStamps(): void
    {
        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];

        $mgr = new LifecycleManagerSchemaOverride();
        $mgr->statementsOverride = [
            'acx_persons' => "CREATE TABLE wp_acx_persons (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			name varchar(255) NOT NULL,
			PRIMARY KEY  (id),
			INDEX idx_name_legacy (name),
			CONSTRAINT chk_name CHECK (name <> '')
		) DEFAULT CHARSET utf8mb4;",
        ];

        $mgr->maybe_upgrade();

        $this->assertSame(
            ACX_VERSION,
            get_option('acx_version'),
            'SV-06: INDEX/CONSTRAINT lines must not block verification stamp'
        );
        $this->assertNotFalse(get_option('acx_schema_fingerprint'));
        $joined = \implode("\n", $this->getErrorLog());
        $this->assertStringNotContainsString('missing columns: INDEX', $joined);
        $this->assertStringNotContainsString('missing columns: CONSTRAINT', $joined);
    }

    public function testParseFailsLoudlyOnUnrecognisedLeadingKeyword(): void
    {
        $sql = "CREATE TABLE wp_acx_persons (\n\tid bigint(20) NOT NULL,\n\tPARTITION BY RANGE (id)\n) DEFAULT CHARSET utf8mb4;";
        $columns = LifecycleManager::parse_create_table_column_names($sql);
        $this->assertNull(
            $columns,
            'SV-06: unrecognised leading keyword must fail closed, not become a column name'
        );
    }

    // -------------------------------------------------------------------------
    // LO-03 — drop legacy UNIQUE idx_name on acx_persons (OBS-08)
    // -------------------------------------------------------------------------

    public function testMaybeUpgradeDropsLegacyPersonsIdxNameWhenPresent(): void
    {
        global $wpdb;

        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];
        $wpdb->tableIndexes['wp_acx_persons'] = ['idx_name', 'idx_normalized_name'];

        $this->manager->maybe_upgrade();

        $drop = null;
        foreach ($wpdb->queries as $query) {
            if (\str_contains($query, 'DROP INDEX') && \str_contains($query, 'idx_name')) {
                $drop = $query;
                break;
            }
        }
        $this->assertNotNull($drop, 'LO-03: must issue DROP INDEX for legacy idx_name');
        $this->assertStringContainsString('wp_acx_persons', $drop);
        $this->assertSame(ACX_VERSION, get_option('acx_version'), 'LO-03: drop must not prevent stamp');
        $this->assertStringContainsString('idx_name', \implode("\n", $this->getErrorLog()));
        $this->assertNotContains(
            'idx_name',
            $wpdb->tableIndexes['wp_acx_persons'] ?? [],
            'LO-03: idx_name must be removed from achieved index set after drop'
        );
    }

    public function testMaybeUpgradeIsNoOpWhenLegacyPersonsIdxNameAbsent(): void
    {
        global $wpdb;

        $this->setOption('acx_version', '0.0.1-stale');
        $wpdb->tableIndexes['wp_acx_persons'] = ['idx_normalized_name'];

        $this->manager->maybe_upgrade();

        foreach ($wpdb->queries as $query) {
            $this->assertFalse(
                \str_contains($query, 'DROP INDEX') && \str_contains($query, 'idx_name'),
                'LO-03: must not DROP INDEX when idx_name is absent'
            );
        }
        $this->assertSame(ACX_VERSION, get_option('acx_version'));
    }

    /**
     * FIX-2 / OBS-08: null from SHOW INDEX is a failed probe, not "index absent".
     * Must refuse the stamp so legacy idx_name is not silently left in place.
     * TEST-15: goes red when null is treated as empty-result success.
     */
    public function testMaybeUpgradeDoesNotStampWhenLegacyIndexProbeReturnsNull(): void
    {
        global $wpdb;

        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];
        // Index is present on the live install, but the SHOW INDEX probe fails.
        // Scoped flag so SHOW COLUMNS verification still runs (global null would
        // mask the probe failure behind a later verifier error).
        $wpdb->tableIndexes['wp_acx_persons'] = ['idx_name', 'idx_normalized_name'];
        $GLOBALS['__ac_show_index_returns_null'] = true;
        $wpdb->last_error = '';

        try {
            $this->manager->maybe_upgrade();
        } finally {
            unset($GLOBALS['__ac_show_index_returns_null']);
        }

        $this->assertSame(
            '0.0.1-stale',
            get_option('acx_version'),
            'failed index probe must not stamp acx_version'
        );
        $this->assertFalse(
            get_option('acx_schema_fingerprint'),
            'failed index probe must not stamp fingerprint'
        );
        $joined = \implode("\n", $this->getErrorLog());
        $this->assertStringContainsString('legacy-index probe failed', $joined);
        $this->assertStringContainsString('idx_name', $joined);
        $this->assertStringContainsString('query did not execute', $joined);
        $this->assertContains(
            'idx_name',
            $wpdb->tableIndexes['wp_acx_persons'] ?? [],
            'failed probe must not DROP INDEX'
        );
    }
}

/**
 * Test double: inject a custom projection statement map for verifier edge cases.
 */
final class LifecycleManagerSchemaOverride extends LifecycleManager
{
    /** @var array<string, string>|null */
    public ?array $statementsOverride = null;

    public function build_projection_schema_statements(string $prefix, string $charset_collate): array
    {
        if ($this->statementsOverride !== null) {
            return $this->statementsOverride;
        }

        return parent::build_projection_schema_statements($prefix, $charset_collate);
    }
}
