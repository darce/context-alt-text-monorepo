<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;

/**
 * rg-005: repository SQL must not reference projection columns absent from DDL.
 *
 * Both sides are derived independently (TEST-15):
 *  - DDL columns from LifeCycleManager::build_projection_schema_statements()
 *  - SQL column refs from prepare_query / prepare_projection_read_query string
 *    units AND $wpdb->insert/update/delete array keys in sovereign repository
 *    sources
 *
 * Coverage is per-query-site, not per-table (OBS-08 / PT-05): every prepare-family
 * call site and every insert/update/delete site is either scanned (yielded ≥1
 * bound column ref), visited-but-unresolved (explicit allowlist), or unscanned
 * (explicit allowlist). The site census is computed independently of the
 * extractor so invisible call sites surface as unscanned gaps, not as silence.
 * Unresolved references fail loudly — never silent drops (OBS-08).
 *
 * @coversNothing
 */
class ProjectionQueryColumnParityTest extends TestCase
{
    /**
     * Expected unresolved alias.column skips, keyed by "basename:alias.column".
     * Stale entries fail (OBS-08). Empty once derived-table interiors bind.
     *
     * @var array<string, string>
     */
    private const ALLOWED_SKIPS = [];

    /**
     * prepare-family call sites that cannot yield a string-literal unit.
     * Keyed by "basename:signature". Stale entries fail (OBS-08).
     *
     * @var array<string, string>
     */
    private const ALLOWED_DROPPED_CALLS = [];

    /**
     * Census query sites the extractor cannot visit at all.
     * Keyed by "basename:line:kind". Stale entries fail.
     *
     * @var array<string, string>
     */
    private const ALLOWED_UNSCANNED_SITES = [];

    /**
     * Sites the extractor visits but that yield zero bound column refs.
     * Silence is not coverage (OBS-08): each entry must justify why zero yield
     * is correct. Keyed by "basename:line:kind". Stale entries fail.
     *
     * @var array<string, string>
     */
    private const ALLOWED_VISITED_UNRESOLVED = [];

    /**
     * Legitimate direct $wpdb->prepare|get_results|get_var|get_row|query call
     * sites that do not carry projection SQL through prepare_query /
     * prepare_projection_read_query. This list is intentionally non-empty:
     * four justified bypasses (transaction control + prepare implementation).
     * Keyed by "basename:line". Stale entries fail (OBS-08 / PT-01).
     *
     * @var array<string, string>
     */
    private const ALLOWED_WPDB_BYPASSES = [
        // Transaction control — string-literal SQL with no projection columns.
        'class-batch-run-repository.php:597' => 'justified: $wpdb->query(START TRANSACTION) — no projection columns',
        'class-batch-run-repository.php:600' => 'justified: $wpdb->query(COMMIT) — no projection columns',
        'class-batch-run-repository.php:602' => 'justified: $wpdb->query(ROLLBACK) — no projection columns',
        // Trait implementation of prepare_query — delegates to $wpdb->prepare;
        // SQL string units are scanned at the prepare_query / prepare_projection_read_query call sites.
        'trait-prepares-sql-queries.php:57' => 'justified: prepare_query implementation delegates to $wpdb->prepare',
    ];

    /**
     * SQL prepare-family method names that must appear in the independent
     * census. The extractor must visit every call site of each name; a name
     * present here but not handled by extractPrepareQueryUnits surfaces as
     * unscanned (FIX-2). Non-SQL methods named prepare_* (e.g.
     * prepare_snapshot_merge_for_tenant) are intentionally excluded.
     *
     * @var list<string>
     */
    private const PREPARE_FAMILY_METHODS = [
        'prepare_query',
        'prepare_projection_read_query',
    ];

    /** Bare SQL keywords — never treated as column names. */
    private const SQL_KEYWORDS = [
        'and', 'or', 'not', 'null', 'true', 'false', 'is', 'in', 'like', 'exists',
        'select', 'from', 'where', 'join', 'left', 'right', 'inner', 'outer', 'cross',
        'on', 'as', 'set', 'update', 'insert', 'into', 'values', 'delete', 'order',
        'by', 'group', 'having', 'limit', 'offset', 'union', 'all', 'distinct',
        'case', 'when', 'then', 'else', 'end', 'asc', 'desc', 'over', 'partition',
        'dual', 'primary', 'key', 'index', 'unique', 'default', 'interval',
        'between', 'escape', 'regexp', 'rlike', 'xor', 'div', 'mod', 'binary',
        'collate', 'using', 'force', 'ignore', 'straight_join', 'natural',
        'lateral', 'window', 'rows', 'range', 'unbounded', 'preceding', 'following',
        'current', 'row', 'filter', 'within', 'separator', 'both', 'leading',
        'trailing', 'for', 'lock', 'share', 'mode', 'nowait', 'skip', 'of', 'with',
        'recursive', 'materialized', 'duplicate', 'out',
    ];

    /**
     * Every confidently-bound column reference in sovereign repository SQL
     * must exist in that table's projection DDL column set.
     */
    public function testBoundRepositoryColumnsExistInProjectionDdl(): void
    {
        $ddlColumnsByTable = $this->parseProjectionDdlColumns();
        $this->assertGreaterThanOrEqual(
            12,
            count($ddlColumnsByTable),
            'build_projection_schema_statements must return the projection table set'
        );
        $this->assertArrayHasKey('acx_identity_members', $ddlColumnsByTable);

        $scan = $this->scanRepositorySqlColumnRefs();
        $bound = $scan['bound'];
        $skipped = $scan['skipped'];
        $dropped = $scan['dropped'];
        $callCount = $scan['call_count'];
        $extractedCount = $scan['extracted_count'];

        $this->assertNotEmpty(
            $bound,
            'extractor found no confidently-bound column refs — parser or corpus is broken'
        );

        $this->assertCallSitesAccountedFor($callCount, $extractedCount, $dropped);
        $this->assertSkippedBindingsAllowlisted($skipped);
        $this->assertWpdbBypassesAllowlisted($scan['bypasses']);
        $this->assertQuerySitesAccountedFor($scan['sites']);

        $missing = [];
        foreach ($bound as $ref) {
            $table = $ref['table'];
            $column = $ref['column'];
            $declared = $ddlColumnsByTable[$table] ?? null;
            if ($declared === null) {
                $missing[] = sprintf(
                    '%s: %s.%s (table not in projection DDL)',
                    $ref['file'],
                    $table,
                    $column
                );
                continue;
            }
            if (! in_array($column, $declared, true)) {
                $missing[] = sprintf(
                    '%s: %s.%s not in declared columns [%s]',
                    $ref['file'],
                    $this->displayTableName($table),
                    $column,
                    implode(', ', $declared)
                );
            }
        }

        $skipDiagnostic = $skipped === []
            ? '(none)'
            : implode('; ', $skipped);

        $this->assertSame(
            [],
            $missing,
            "Repository SQL references columns absent from projection DDL.\n"
            . 'Missing: ' . implode(' | ', $missing) . "\n"
            . 'Skipped (allowlisted unbound): ' . $skipDiagnostic . "\n"
            . 'bound=' . count($bound) . ' skipped=' . count($skipped)
            . ' calls=' . $callCount . ' extracted=' . $extractedCount
            . ' census=' . count($scan['sites'])
            . ' scanned=' . $scan['site_counts']['scanned']
            . ' visited_unresolved=' . $scan['site_counts']['visited_unresolved']
            . ' unscanned=' . $scan['site_counts']['unscanned']
        );
    }

    /**
     * Every prepare-family / insert / update / delete census site is either
     * scanned (yielded ≥1 bound column ref) or explicitly allowlisted.
     * Visited-but-zero-yield sites are a distinct failure bucket (OBS-08).
     * The denominator is the independent census, not the extractor's own
     * match set — invisible sites must surface as unscanned (PT-05).
     */
    public function testEveryQuerySiteIsScannedOrAllowlisted(): void
    {
        $scan = $this->scanRepositorySqlColumnRefs();
        $sites = $scan['sites'];

        $this->assertNotEmpty($sites, 'no query sites discovered in sovereign repositories');
        $this->assertSame(
            count($sites),
            $scan['census_count'],
            'site list must be the independent census denominator (not extractor self-count)'
        );

        $unscanned = [];
        $visitedUnresolved = [];
        foreach ($sites as $site) {
            if ($site['scanned']) {
                continue;
            }
            if (($site['bucket'] ?? '') === 'visited_unresolved') {
                if (! array_key_exists($site['key'], self::ALLOWED_VISITED_UNRESOLVED)) {
                    $visitedUnresolved[] = $site['key'] . ' (' . $site['detail'] . ')';
                }
                continue;
            }
            if (! array_key_exists($site['key'], self::ALLOWED_UNSCANNED_SITES)) {
                $unscanned[] = $site['key'] . ' (' . $site['detail'] . ')';
            }
        }

        $stale = [];
        $siteKeys = array_column($sites, 'key');
        foreach (array_keys(self::ALLOWED_UNSCANNED_SITES) as $key) {
            if (! in_array($key, $siteKeys, true)) {
                $stale[] = $key . ' (site gone)';
                continue;
            }
            foreach ($sites as $site) {
                if ($site['key'] === $key && $site['scanned']) {
                    $stale[] = $key . ' (now scanned)';
                }
            }
        }
        foreach (array_keys(self::ALLOWED_VISITED_UNRESOLVED) as $key) {
            if (! in_array($key, $siteKeys, true)) {
                $stale[] = 'visited_unresolved:' . $key . ' (site gone)';
                continue;
            }
            foreach ($sites as $site) {
                if ($site['key'] === $key && $site['scanned']) {
                    $stale[] = 'visited_unresolved:' . $key . ' (now scanned)';
                }
                if (
                    $site['key'] === $key
                    && ($site['bucket'] ?? '') !== 'visited_unresolved'
                    && ! $site['scanned']
                ) {
                    $stale[] = 'visited_unresolved:' . $key . ' (bucket is '
                        . ($site['bucket'] ?? '?') . ', not visited_unresolved)';
                }
            }
        }

        $this->assertSame(
            [],
            $unscanned,
            'Query sites not visited by extractor and not on ALLOWED_UNSCANNED_SITES (PT-05 / OBS-08): '
            . implode(' | ', $unscanned)
            . '. census=' . count($sites)
            . ' scanned=' . $scan['site_counts']['scanned']
            . ' visited_unresolved=' . $scan['site_counts']['visited_unresolved']
            . ' unscanned=' . $scan['site_counts']['unscanned']
        );
        $this->assertSame(
            [],
            $visitedUnresolved,
            'Query sites visited but yielding zero bound columns, not on ALLOWED_VISITED_UNRESOLVED (OBS-08): '
            . implode(' | ', $visitedUnresolved)
        );
        $this->assertSame(
            [],
            $stale,
            'Allowlist dead instrumentation (OBS-08): ' . implode(' | ', $stale)
        );
    }

    /**
     * FIX-4 / PT-02 production: the list_labels derived-table query in
     * class-clusters-read-repository.php must reach the scanner through
     * prepare_projection_read_query, and its interior columns must bind.
     */
    public function testProductionDerivedTableListLabelsIsScanned(): void
    {
        $path = dirname(__DIR__, 2)
            . '/src/sovereign/repositories/class-clusters-read-repository.php';
        $this->assertFileExists($path);
        $source = (string) file_get_contents($path);
        $basename = 'class-clusters-read-repository.php';

        $extraction = $this->extractPrepareQueryUnits($source, $basename);
        $derivedUnits = [];
        foreach ($extraction['units'] as $unit) {
            if (
                str_contains($unit['sql'], 'SELECT label, person_id FROM')
                && str_contains($unit['sql'], 'reserved_label_sql_predicate')
            ) {
                $this->assertSame(
                    'prepare_projection_read_query',
                    $unit['method'],
                    'list_labels SQL must arrive via prepare_projection_read_query'
                );
                $derivedUnits[] = $unit;
            }
        }

        $this->assertNotEmpty(
            $derivedUnits,
            'production list_labels SQL must be present in the extracted corpus (FIX-4)'
        );

        $interiorLabels = 0;
        $interiorTenantIds = 0;
        foreach ($derivedUnits as $unit) {
            $aliasMap = $this->bindAliasesToTables($unit['sql'], $unit['args'], $basename);
            $primaryTable = $this->resolvePrimaryTable($unit['sql'], $unit['args'], $basename);
            $items = $this->collectAllColumnRefs(
                $unit['sql'],
                $unit['args'],
                $aliasMap,
                $primaryTable,
                $basename
            );
            foreach ($items['bound'] as $ref) {
                $this->assertSame('acx_clusters', $ref['table'], 'list_labels binds to acx_clusters');
                if ($ref['column'] === 'label') {
                    $interiorLabels++;
                }
                if ($ref['column'] === 'tenant_id') {
                    $interiorTenantIds++;
                }
            }
        }

        $this->assertGreaterThan(
            0,
            $interiorLabels,
            'derived-table interior column label must be resolved from production list_labels SQL (FIX-4)'
        );
        $this->assertGreaterThan(
            0,
            $interiorTenantIds,
            'derived-table interior column tenant_id must be resolved from production list_labels SQL (FIX-4)'
        );

        // Also prove the main scan corpus carries the same production refs.
        $scan = $this->scanRepositorySqlColumnRefs();
        $prodLabels = 0;
        foreach ($scan['bound'] as $ref) {
            if (
                $ref['file'] === $basename
                && $ref['table'] === 'acx_clusters'
                && $ref['column'] === 'label'
            ) {
                $prodLabels++;
            }
        }
        $this->assertGreaterThan(
            0,
            $prodLabels,
            'scanRepositorySqlColumnRefs must include clusters-read label refs from production SQL'
        );
    }

    /**
     * PT-06 / TEST-15: write-column collector must collect known SET targets.
     * Deleting collectUnqualifiedWriteColumns must turn this red.
     */
    public function testWriteCollectorCapturesCurationWriterSetTargets(): void
    {
        $scan = $this->scanRepositorySqlColumnRefs();
        $writes = $scan['write_columns'];

        $this->assertNotEmpty(
            $writes,
            'collectUnqualifiedWriteColumns returned empty — write collector is dead (PT-06 / OBS-08)'
        );

        $assignedAtSites = [];
        $clusterUuidSites = [];
        foreach ($writes as $ref) {
            if ($ref['file'] === 'class-identity-member-curation-writer.php') {
                if ($ref['column'] === 'assigned_at') {
                    $assignedAtSites[] = $ref;
                }
                if ($ref['column'] === 'cluster_uuid') {
                    $clusterUuidSites[] = $ref;
                }
            }
        }

        $this->assertNotEmpty(
            $assignedAtSites,
            'curation writer SET assigned_at must appear in write-column collector (PT-06 / BR-12)'
        );
        $this->assertNotEmpty(
            $clusterUuidSites,
            'curation writer SET cluster_uuid must appear in write-column collector (PT-06 / BR-12)'
        );

        foreach ($assignedAtSites as $ref) {
            $this->assertSame('acx_identity_members', $ref['table']);
        }
    }

    /**
     * PT-01: direct $wpdb SQL entry points must not bypass prepare_query unless
     * explicitly allowlisted. Stale allowlist entries fail.
     */
    public function testNoUnallowlistedWpdbBypasses(): void
    {
        $scan = $this->scanRepositorySqlColumnRefs();
        $this->assertWpdbBypassesAllowlisted($scan['bypasses']);
    }

    /**
     * PT-02 fixture: a derived-table interior naming a nonexistent column must
     * fail the bound-column predicate (not be silently skipped).
     */
    public function testDerivedTableInteriorColumnsAreScanned(): void
    {
        $sql = 'SELECT outer_alias.label FROM (SELECT DISTINCT bogus_derived_col_xyz FROM %i WHERE tenant_id = %s) outer_alias LIMIT %d';
        $args = ["'acx_clusters'", '$tenant', '10'];
        $basename = 'fixture-derived.php';

        $aliasMap = $this->bindAliasesToTables($sql, $args, $basename);
        $primaryTable = $this->resolvePrimaryTable($sql, $args, $basename);
        $items = $this->collectAllColumnRefs($sql, $args, $aliasMap, $primaryTable, $basename);

        $columns = [];
        foreach ($items['bound'] as $ref) {
            $columns[] = $ref['column'];
        }

        $this->assertContains(
            'bogus_derived_col_xyz',
            $columns,
            'derived-table interior columns must be scanned (PT-02)'
        );
    }

    /**
     * PT-03 fixture: RHS of SET assignments are reads and must be bound.
     */
    public function testAssignmentRhsColumnsAreScanned(): void
    {
        $sql = 'UPDATE %i SET assigned_at = bogus_rhs_column_xyz WHERE identity_uuid = %s';
        $args = ['$this->members_table_name', '$id'];
        $basename = 'fixture-set-rhs.php';

        $aliasMap = $this->bindAliasesToTables($sql, $args, $basename);
        $primaryTable = $this->resolvePrimaryTable($sql, $args, $basename);
        $writes = $this->collectUnqualifiedWriteColumns($sql, $aliasMap, $primaryTable, $basename);

        $columns = array_column($writes, 'column');
        $this->assertContains('assigned_at', $columns, 'LHS SET target must be collected');
        $this->assertContains(
            'bogus_rhs_column_xyz',
            $columns,
            'RHS SET column reference must be collected (PT-03)'
        );
    }

    /**
     * PT-04 fixture: $wpdb->insert array keys are held to the DDL predicate.
     */
    public function testWpdbInsertArrayKeysAreScanned(): void
    {
        $source = <<<'PHP'
$wpdb->insert(
    $this->runs_table_name,
    array(
        'run_id' => $id,
        'bogus_insert_col_xyz' => 1,
        'status' => 'pending',
    )
);
PHP;
        $units = $this->extractWpdbArrayWriteUnits($source, 'fixture-insert.php');
        $this->assertNotEmpty($units);
        $columns = [];
        foreach ($units as $unit) {
            foreach ($unit['columns'] as $col) {
                $columns[] = $col;
            }
        }
        $this->assertContains('bogus_insert_col_xyz', $columns, 'insert array keys must be extracted (PT-04)');
        $this->assertContains('run_id', $columns);
        $this->assertContains('status', $columns);
    }

    /**
     * PT-08: IDENT( is a function call — name is not a column; arguments are.
     */
    public function testSqlFunctionNamesAreNotTreatedAsColumns(): void
    {
        $ids = $this->collectColumnIdentifiersFromFragment(
            'COUNT(*), MAX(assigned_at), COALESCE(p.name, c.label), NOW()'
        );
        $this->assertNotContains('COUNT', $ids);
        $this->assertNotContains('MAX', $ids);
        $this->assertNotContains('COALESCE', $ids);
        $this->assertNotContains('NOW', $ids);
        $this->assertContains('assigned_at', $ids);
        $this->assertContains('name', $ids);
        $this->assertContains('label', $ids);
    }

    /**
     * @param list<string> $dropped
     */
    private function assertCallSitesAccountedFor(int $callCount, int $extractedCount, array $dropped): void
    {
        $this->assertGreaterThan(
            0,
            $callCount,
            'no prepare_query / prepare_projection_read_query call sites found in sovereign repositories'
        );

        $allowedKeys = array_keys(self::ALLOWED_DROPPED_CALLS);
        $droppedKeys = [];
        foreach ($dropped as $entry) {
            $key = preg_replace('/\s+—.*$/', '', $entry) ?? $entry;
            $droppedKeys[] = $key;
        }

        $unexpected = [];
        foreach ($droppedKeys as $key) {
            if (! array_key_exists($key, self::ALLOWED_DROPPED_CALLS)) {
                $unexpected[] = $key;
            }
        }

        $stale = [];
        foreach ($allowedKeys as $key) {
            if (! in_array($key, $droppedKeys, true)) {
                $stale[] = $key;
            }
        }

        $this->assertSame(
            [],
            $unexpected,
            'prepare-family call sites dropped without extraction and not on ALLOWED_DROPPED_CALLS (BR-07 / OBS-08): '
            . implode(' | ', $unexpected)
        );
        $this->assertSame(
            [],
            $stale,
            'ALLOWED_DROPPED_CALLS entries that no longer drop — dead instrumentation (OBS-08): '
            . implode(' | ', $stale)
        );

        $this->assertSame(
            $callCount,
            $extractedCount + count($dropped),
            'prepare-family call_count must equal extracted + dropped'
        );
    }

    /**
     * @param list<string> $skipped
     */
    private function assertSkippedBindingsAllowlisted(array $skipped): void
    {
        $skipKeys = [];
        foreach ($skipped as $entry) {
            if (preg_match(
                '/^([a-z0-9_.\-]+):\s*([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b/',
                $entry,
                $m
            )) {
                $skipKeys[] = $m[1] . ':' . $m[2] . '.' . $m[3];
            } else {
                $skipKeys[] = $entry;
            }
        }
        $skipKeys = array_values(array_unique($skipKeys));

        $unexpected = [];
        foreach ($skipKeys as $key) {
            if (! array_key_exists($key, self::ALLOWED_SKIPS)) {
                $unexpected[] = $key;
            }
        }

        $stale = [];
        foreach (array_keys(self::ALLOWED_SKIPS) as $key) {
            if (! in_array($key, $skipKeys, true)) {
                $stale[] = $key;
            }
        }

        $this->assertSame(
            [],
            $unexpected,
            'Unresolved alias.column skips not on ALLOWED_SKIPS (BR-06 / OBS-08): '
            . implode(' | ', $unexpected)
            . '. Full skip list: ' . implode('; ', $skipped)
        );
        $this->assertSame(
            [],
            $stale,
            'ALLOWED_SKIPS entries that no longer skip — dead instrumentation (OBS-08): '
            . implode(' | ', $stale)
        );
    }

    /**
     * @param list<array{key:string,file:string,line:int,detail:string}> $bypasses
     */
    private function assertWpdbBypassesAllowlisted(array $bypasses): void
    {
        $foundKeys = [];
        $unexpected = [];
        foreach ($bypasses as $b) {
            $foundKeys[] = $b['key'];
            if (! array_key_exists($b['key'], self::ALLOWED_WPDB_BYPASSES)) {
                $unexpected[] = $b['key'] . ' — ' . $b['detail'];
            }
        }

        $stale = [];
        foreach (array_keys(self::ALLOWED_WPDB_BYPASSES) as $key) {
            if (! in_array($key, $foundKeys, true)) {
                $stale[] = $key;
            }
        }

        $this->assertSame(
            [],
            $unexpected,
            'Direct $wpdb SQL calls bypass prepare_query without ALLOWED_WPDB_BYPASSES entry (PT-01 / OBS-08): '
            . implode(' | ', $unexpected)
        );
        $this->assertSame(
            [],
            $stale,
            'ALLOWED_WPDB_BYPASSES entries that no longer match — dead instrumentation (OBS-08): '
            . implode(' | ', $stale)
        );
    }

    /**
     * @param list<array{key:string,scanned:bool,detail:string}> $sites
     */
    private function assertQuerySitesAccountedFor(array $sites): void
    {
        // Covered by testEveryQuerySiteIsScannedOrAllowlisted; keep helper for main test diagnostics.
        $this->assertNotEmpty($sites);
    }

    /**
     * @return array<string, string[]> table suffix => declared column names
     */
    private function parseProjectionDdlColumns(): array
    {
        $manager = new LifecycleManager();
        $statements = $manager->build_projection_schema_statements('wp_', '');
        $this->assertIsArray($statements);
        $this->assertNotEmpty($statements);

        $columnsByTable = [];
        foreach ($statements as $tableSuffix => $createSql) {
            $this->assertIsString($tableSuffix);
            $this->assertIsString($createSql);
            $columns = $this->parseCreateTableColumns($createSql);
            $this->assertNotEmpty(
                $columns,
                "parsed no columns from DDL for {$tableSuffix}"
            );
            $columnsByTable[$tableSuffix] = $columns;
        }

        return $columnsByTable;
    }

    /**
     * @return string[]
     */
    private function parseCreateTableColumns(string $createSql): array
    {
        $open = strpos($createSql, '(');
        $close = strrpos($createSql, ')');
        $this->assertNotFalse($open, 'CREATE TABLE missing opening parenthesis');
        $this->assertNotFalse($close, 'CREATE TABLE missing closing parenthesis');
        $this->assertGreaterThan($open, $close);

        $body = substr($createSql, $open + 1, $close - $open - 1);
        $lines = preg_split('/\r?\n/', $body);
        if (! is_array($lines)) {
            return [];
        }

        $columns = [];
        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            if (preg_match(
                '/^(PRIMARY\s+KEY|UNIQUE\s+KEY|FULLTEXT\s+KEY|FOREIGN\s+KEY|CONSTRAINT|KEY|INDEX)\b/i',
                $line
            )) {
                continue;
            }
            if (preg_match('/^([a-z_][a-z0-9_]*)\s+/i', $line, $match)) {
                $columns[] = $match[1];
            }
        }

        return $columns;
    }

    /**
     * Scan repository sources for column refs bound to projection tables.
     *
     * Site denominator comes from censusRepositoryQuerySites (independent of
     * the extractor). A site is scanned only when extraction yields ≥1 bound
     * column reference — visit alone is not coverage.
     *
     * @return array{
     *     bound: list<array{file:string,table:string,column:string,alias:string}>,
     *     skipped: list<string>,
     *     dropped: list<string>,
     *     call_count: int,
     *     extracted_count: int,
     *     write_columns: list<array{file:string,table:string,column:string,alias:string}>,
     *     sites: list<array{key:string,scanned:bool,visited:bool,yield:int,bucket:string,detail:string}>,
     *     site_counts: array{scanned:int,visited_unresolved:int,unscanned:int},
     *     census_count: int,
     *     bypasses: list<array{key:string,file:string,line:int,detail:string}>
     * }
     */
    private function scanRepositorySqlColumnRefs(): array
    {
        $dir = dirname(__DIR__, 2) . '/src/sovereign/repositories';
        $files = glob($dir . '/*.php');
        $this->assertIsArray($files);
        $this->assertNotEmpty($files, 'no sovereign repository source files found');

        $bound = [];
        $skipped = [];
        $dropped = [];
        $writeColumns = [];
        $sites = [];
        $bypasses = [];
        $callCount = 0;
        $extractedCount = 0;
        $censusCount = 0;

        foreach ($files as $path) {
            $basename = basename($path);
            $source = (string) file_get_contents($path);

            foreach ($this->findWpdbBypasses($source, $basename) as $bypass) {
                $bypasses[] = $bypass;
            }

            // Independent census first (denominator). Trait file is implementation
            // only — its prepare_* self-calls are not production query sites.
            $census = [];
            if ($basename !== 'trait-prepares-sql-queries.php') {
                $census = $this->censusRepositoryQuerySites($source, $basename);
            }
            $censusCount += count($census);

            // yieldByKey: null = never visited; int = bound-column yield after visit.
            $yieldByKey = [];
            $detailByKey = [];

            if ($basename === 'trait-prepares-sql-queries.php') {
                continue;
            }

            $extraction = $this->extractPrepareQueryUnits($source, $basename);
            $callCount += $extraction['call_count'];
            $extractedCount += count($extraction['units']);

            foreach ($extraction['dropped'] as $d) {
                $dropped[] = $d;
            }
            // Dropped calls are still "visited" — extractor saw them but could
            // not extract a unit (zero yield unless allowlisted).
            foreach ($extraction['dropped_keys'] as $dropKey => $dropDetail) {
                $yieldByKey[$dropKey] = 0;
                $detailByKey[$dropKey] = $dropDetail;
            }

            foreach ($extraction['units'] as $unit) {
                $aliasMap = $this->bindAliasesToTables(
                    $unit['sql'],
                    $unit['args'],
                    $basename
                );
                $primaryTable = $this->resolvePrimaryTable($unit['sql'], $unit['args'], $basename);

                $items = $this->collectAllColumnRefs(
                    $unit['sql'],
                    $unit['args'],
                    $aliasMap,
                    $primaryTable,
                    $basename
                );

                foreach ($items['bound'] as $ref) {
                    $bound[] = $ref;
                }
                foreach ($items['skipped'] as $skip) {
                    $skipped[] = $skip;
                }
                foreach ($items['writes'] as $ref) {
                    $writeColumns[] = $ref;
                    $bound[] = $ref;
                }

                $yield = count($items['bound']) + count($items['writes']);
                $siteKey = $unit['site_key'];
                $yieldByKey[$siteKey] = $yield;
                $detailByKey[$siteKey] = $unit['method'] . ' unit yield=' . $yield;
            }

            foreach ($this->extractWpdbArrayWriteUnits($source, $basename) as $writeUnit) {
                $siteKey = $writeUnit['site_key'];
                if ($writeUnit['table'] === null) {
                    $yieldByKey[$siteKey] = 0;
                    $detailByKey[$siteKey] = 'unresolved table for ' . $writeUnit['kind'];
                    continue;
                }
                foreach ($writeUnit['columns'] as $column) {
                    $ref = [
                        'file' => $basename,
                        'table' => $writeUnit['table'],
                        'column' => $column,
                        'alias' => '',
                    ];
                    $bound[] = $ref;
                }
                $yield = count($writeUnit['columns']);
                $yieldByKey[$siteKey] = $yield;
                $detailByKey[$siteKey] = $writeUnit['kind'] . ' array keys yield=' . $yield;
            }

            // Materialise sites from the independent census denominator.
            foreach ($census as $cSite) {
                $key = $cSite['key'];
                if (! array_key_exists($key, $yieldByKey)) {
                    $sites[] = [
                        'key' => $key,
                        'scanned' => false,
                        'visited' => false,
                        'yield' => 0,
                        'bucket' => 'unscanned',
                        'detail' => 'census site not visited by extractor: ' . $cSite['kind'],
                    ];
                    continue;
                }
                $yield = $yieldByKey[$key];
                if ($yield > 0) {
                    $sites[] = [
                        'key' => $key,
                        'scanned' => true,
                        'visited' => true,
                        'yield' => $yield,
                        'bucket' => 'scanned',
                        'detail' => $detailByKey[$key] ?? ('yield=' . $yield),
                    ];
                } else {
                    $sites[] = [
                        'key' => $key,
                        'scanned' => false,
                        'visited' => true,
                        'yield' => 0,
                        'bucket' => 'visited_unresolved',
                        'detail' => $detailByKey[$key] ?? 'visited but zero bound column refs',
                    ];
                }
            }
        }

        $siteCounts = [
            'scanned' => 0,
            'visited_unresolved' => 0,
            'unscanned' => 0,
        ];
        foreach ($sites as $site) {
            $bucket = $site['bucket'];
            if (isset($siteCounts[$bucket])) {
                $siteCounts[$bucket]++;
            }
        }

        return [
            'bound' => $bound,
            'skipped' => $skipped,
            'dropped' => $dropped,
            'call_count' => $callCount,
            'extracted_count' => $extractedCount,
            'write_columns' => $writeColumns,
            'sites' => $sites,
            'site_counts' => $siteCounts,
            'census_count' => $censusCount,
            'bypasses' => $bypasses,
        ];
    }

    /**
     * Independent census of prepare-family and $wpdb write call sites.
     * Does not extract SQL — only locates sites so the denominator is not
     * the extractor's own match set (FIX-2 / OBS-08).
     *
     * @return list<array{key:string,file:string,line:int,kind:string}>
     */
    private function censusRepositoryQuerySites(string $source, string $basename): array
    {
        $sites = [];
        $offset = 0;

        // Prepare-family census: match only SQL prepare helpers listed in
        // PREPARE_FAMILY_METHODS (not domain methods like prepare_snapshot_*).
        // Built independently of extractPrepareQueryUnits so a method the
        // extractor forgets still appears as unscanned.
        $prepareAlternation = implode(
            '|',
            array_map(
                static fn (string $m): string => preg_quote($m, '/'),
                self::PREPARE_FAMILY_METHODS
            )
        );
        while (preg_match(
            '/->(' . $prepareAlternation . ')\s*\(/',
            $source,
            $match,
            PREG_OFFSET_CAPTURE,
            $offset
        )) {
            $method = $match[1][0];
            $pos = $match[0][1];
            $line = substr_count(substr($source, 0, $pos), "\n") + 1;
            if (! $this->isOffsetInCommentOrString($source, $pos)) {
                $sites[] = [
                    'key' => $basename . ':' . $line . ':' . $method,
                    'file' => $basename,
                    'line' => $line,
                    'kind' => $method,
                ];
            }
            $offset = $pos + strlen($match[0][0]);
        }

        $offset = 0;
        while (preg_match(
            '/\$wpdb->(insert|update|delete)\s*\(/',
            $source,
            $match,
            PREG_OFFSET_CAPTURE,
            $offset
        )) {
            $kind = $match[1][0];
            $pos = $match[0][1];
            $line = substr_count(substr($source, 0, $pos), "\n") + 1;
            if (! $this->isOffsetInCommentOrString($source, $pos)) {
                $sites[] = [
                    'key' => $basename . ':' . $line . ':' . $kind,
                    'file' => $basename,
                    'line' => $line,
                    'kind' => $kind,
                ];
            }
            $offset = $pos + strlen($match[0][0]);
        }

        // Stable order by line for diagnostics.
        usort(
            $sites,
            static function (array $a, array $b): int {
                return $a['line'] <=> $b['line'];
            }
        );

        return $sites;
    }

    /**
     * Cheap guard: skip matches that sit on a line whose trim starts with a
     * comment marker (docblocks / line comments mentioning $wpdb->update etc.).
     */
    private function isOffsetInCommentOrString(string $source, int $pos): bool
    {
        $lineStart = strrpos(substr($source, 0, $pos), "\n");
        $lineStart = $lineStart === false ? 0 : $lineStart + 1;
        $lineEnd = strpos($source, "\n", $pos);
        $line = $lineEnd === false
            ? substr($source, $lineStart)
            : substr($source, $lineStart, $lineEnd - $lineStart);
        $trimmed = ltrim($line);

        return $trimmed === ''
            || str_starts_with($trimmed, '//')
            || str_starts_with($trimmed, '#')
            || str_starts_with($trimmed, '*')
            || str_starts_with($trimmed, '/*');
    }

    /**
     * Collect bound/skipped/write refs from one SQL unit, recursing into derived tables.
     *
     * @param string[] $args
     * @param array<string, string|null> $aliasMap
     * @return array{
     *     bound: list<array{file:string,table:string,column:string,alias:string}>,
     *     skipped: list<string>,
     *     writes: list<array{file:string,table:string,column:string,alias:string}>
     * }
     */
    private function collectAllColumnRefs(
        string $sql,
        array $args,
        array $aliasMap,
        ?string $primaryTable,
        string $basename
    ): array {
        $bound = [];
        $skipped = [];
        $writes = [];

        // PT-02: recurse into derived-table interiors before scanning the outer frame.
        foreach ($this->extractDerivedTables($sql, $args) as $derived) {
            $innerAliasMap = $this->bindAliasesToTables(
                $derived['sql'],
                $derived['args'],
                $basename
            );
            $innerPrimary = $this->resolvePrimaryTable(
                $derived['sql'],
                $derived['args'],
                $basename
            );
            $inner = $this->collectAllColumnRefs(
                $derived['sql'],
                $derived['args'],
                $innerAliasMap,
                $innerPrimary,
                $basename
            );
            foreach ($inner['bound'] as $ref) {
                $bound[] = $ref;
            }
            foreach ($inner['skipped'] as $skip) {
                $skipped[] = $skip;
            }
            foreach ($inner['writes'] as $ref) {
                $writes[] = $ref;
            }

            // Outer alias of the derived table resolves to the interior primary table.
            if ($derived['alias'] !== null && $innerPrimary !== null) {
                $aliasMap[$derived['alias']] = $innerPrimary;
            } elseif ($derived['alias'] !== null && $innerPrimary === null) {
                $aliasMap[$derived['alias']] = null;
            }
        }

        // Strip derived-table interiors from the outer SQL so unqualified scanners
        // do not double-count or mis-bind interior identifiers.
        $outerSql = $this->stripDerivedTableInteriors($sql);

        foreach ($this->collectAliasQualifiedRefs($outerSql, $aliasMap, $basename) as $item) {
            if ($item['kind'] === 'bound') {
                $bound[] = $item['ref'];
            } else {
                $skipped[] = $item['skip'];
            }
        }

        foreach ($this->collectUnqualifiedWriteColumns(
            $outerSql,
            $aliasMap,
            $primaryTable,
            $basename
        ) as $ref) {
            $writes[] = $ref;
        }

        foreach ($this->collectUnqualifiedReadColumns(
            $outerSql,
            $primaryTable,
            $basename
        ) as $ref) {
            $bound[] = $ref;
        }

        return [
            'bound' => $bound,
            'skipped' => $skipped,
            'writes' => $writes,
        ];
    }

    /**
     * @param string[] $args
     * @return list<array{sql:string,args:string[],alias:?string}>
     */
    private function extractDerivedTables(string $sql, array $args): array
    {
        $derived = [];
        $offset = 0;
        $length = strlen($sql);

        while ($offset < $length) {
            if (! preg_match(
                '/\b(?:FROM|JOIN)\s*\(\s*(SELECT)\b/i',
                $sql,
                $m,
                PREG_OFFSET_CAPTURE,
                $offset
            )) {
                break;
            }

            $selectStart = $m[1][1];
            // Opening paren is just before SELECT.
            $parenOpen = strrpos(substr($sql, 0, $selectStart), '(');
            if ($parenOpen === false) {
                $offset = $selectStart + 1;
                continue;
            }

            $depth = 0;
            $i = $parenOpen;
            $end = null;
            while ($i < $length) {
                $ch = $sql[$i];
                if ($ch === '(') {
                    $depth++;
                } elseif ($ch === ')') {
                    $depth--;
                    if ($depth === 0) {
                        $end = $i;
                        break;
                    }
                }
                $i++;
            }
            if ($end === null) {
                break;
            }

            $innerSql = substr($sql, $parenOpen + 1, $end - $parenOpen - 1);
            $alias = null;
            $after = substr($sql, $end + 1);
            if (preg_match('/^\s*(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\b/i', $after, $am)) {
                if (! $this->isSqlKeyword($am[1])) {
                    $alias = $am[1];
                }
            }

            // Map % placeholders inside the interior to the corresponding args slice.
            $placeholdersBefore = 0;
            if (preg_match_all('/%[sdfi]/', substr($sql, 0, $parenOpen), $beforeMatches)) {
                $placeholdersBefore = count($beforeMatches[0]);
            }
            $innerPlaceholderCount = 0;
            if (preg_match_all('/%[sdfi]/', $innerSql, $innerMatches)) {
                $innerPlaceholderCount = count($innerMatches[0]);
            }
            $innerArgs = array_slice($args, $placeholdersBefore, $innerPlaceholderCount);

            $derived[] = [
                'sql' => $innerSql,
                'args' => $innerArgs,
                'alias' => $alias,
            ];

            $offset = $end + 1;
        }

        return $derived;
    }

    private function stripDerivedTableInteriors(string $sql): string
    {
        $result = $sql;
        // Replace each (SELECT ... ) with (SELECT 1) to preserve structure without interior ids.
        $offset = 0;
        while (preg_match(
            '/\b(?:FROM|JOIN)\s*\(\s*SELECT\b/i',
            $result,
            $m,
            PREG_OFFSET_CAPTURE,
            $offset
        )) {
            $matchStart = $m[0][1];
            $parenOpen = strpos($result, '(', $matchStart);
            if ($parenOpen === false) {
                break;
            }
            $depth = 0;
            $length = strlen($result);
            $end = null;
            for ($i = $parenOpen; $i < $length; $i++) {
                if ($result[$i] === '(') {
                    $depth++;
                } elseif ($result[$i] === ')') {
                    $depth--;
                    if ($depth === 0) {
                        $end = $i;
                        break;
                    }
                }
            }
            if ($end === null) {
                break;
            }
            $result = substr($result, 0, $parenOpen) . '(SELECT 1)' . substr($result, $end + 1);
            $offset = $parenOpen + strlen('(SELECT 1)');
        }

        return $result;
    }

    /**
     * @return list<array{key:string,file:string,line:int,detail:string}>
     */
    private function findWpdbBypasses(string $source, string $basename): array
    {
        $bypasses = [];
        $lines = preg_split('/\r?\n/', $source);
        if (! is_array($lines)) {
            return [];
        }

        foreach ($lines as $index => $line) {
            $lineNo = $index + 1;
            $trimmed = trim($line);
            if ($trimmed === '' || str_starts_with($trimmed, '//') || str_starts_with($trimmed, '*') || str_starts_with($trimmed, '/*')) {
                continue;
            }
            // Docblocks / comments mentioning $wpdb->query are not call sites.
            if (preg_match('/^\s*(\/\/|\*|#)/', $line)) {
                continue;
            }

            if (preg_match('/\$wpdb->prepare\s*\(/', $line)) {
                $bypasses[] = [
                    'key' => $basename . ':' . $lineNo,
                    'file' => $basename,
                    'line' => $lineNo,
                    'detail' => 'direct $wpdb->prepare',
                ];
                continue;
            }

            // get_results/get_var/get_row/query that do not take a simple $var (bypass prepare_query).
            if (preg_match(
                '/\$wpdb->(get_results|get_var|get_row|query)\s*\(\s*(.+)$/',
                $line,
                $m
            )) {
                $arg = trim($m[2]);
                // Legitimate: $sql, $delete_members_sql, $query_result assignment of $wpdb->query( $sql )
                if (preg_match('/^\$[a-zA-Z_][a-zA-Z0-9_]*\s*[,)]/', $arg)) {
                    continue;
                }
                // Nested prepare or string literal SQL.
                $bypasses[] = [
                    'key' => $basename . ':' . $lineNo,
                    'file' => $basename,
                    'line' => $lineNo,
                    'detail' => 'direct $wpdb->' . $m[1] . ' first arg is not a prepared $var: ' . substr($arg, 0, 60),
                ];
            }
        }

        return $bypasses;
    }

    /**
     * Extract $wpdb->insert / update / delete array-key column references.
     *
     * @return list<array{kind:string,table:?string,columns:string[],site_key:string}>
     */
    private function extractWpdbArrayWriteUnits(string $source, string $basename): array
    {
        $units = [];
        $offset = 0;
        $length = strlen($source);

        while (preg_match(
            '/\$wpdb->(insert|update|delete)\s*\(/',
            $source,
            $match,
            PREG_OFFSET_CAPTURE,
            $offset
        )) {
            $kind = $match[1][0];
            $callStart = $match[0][1];
            $start = $match[0][1] + strlen($match[0][0]);
            $depth = 1;
            $i = $start;
            while ($i < $length && $depth > 0) {
                $ch = $source[$i];
                if ($ch === "'" || $ch === '"') {
                    $quote = $ch;
                    $i++;
                    while ($i < $length) {
                        if ($source[$i] === '\\') {
                            $i += 2;
                            continue;
                        }
                        if ($source[$i] === $quote) {
                            $i++;
                            break;
                        }
                        $i++;
                    }
                    continue;
                }
                if ($ch === '(') {
                    $depth++;
                } elseif ($ch === ')') {
                    $depth--;
                }
                $i++;
            }

            $callBody = substr($source, $start, $i - $start - 1);
            $offset = $i;
            $lineNo = substr_count(substr($source, 0, $callStart), "\n") + 1;
            $signature = $this->callSignature($callBody);
            // Line-keyed to match independent census (basename:line:kind).
            $siteKey = $basename . ':' . $lineNo . ':' . $kind;

            $args = $this->splitTopLevelArgs($callBody);
            $tableExpr = $args[0] ?? '';
            $table = $this->resolveTableSuffix(trim($tableExpr), $basename);

            $columns = [];
            if ($kind === 'insert') {
                $dataExpr = $args[1] ?? '';
                $columns = array_merge(
                    $columns,
                    $this->extractArrayKeysFromExpr($dataExpr, $source, $callStart)
                );
            } elseif ($kind === 'update') {
                $dataExpr = $args[1] ?? '';
                $whereExpr = $args[2] ?? '';
                $columns = array_merge(
                    $columns,
                    $this->extractArrayKeysFromExpr($dataExpr, $source, $callStart),
                    $this->extractArrayKeysFromExpr($whereExpr, $source, $callStart)
                );
            } else {
                // delete: where array is second arg.
                $whereExpr = $args[1] ?? '';
                $columns = array_merge(
                    $columns,
                    $this->extractArrayKeysFromExpr($whereExpr, $source, $callStart)
                );
            }

            $units[] = [
                'kind' => $kind,
                'table' => $table,
                'columns' => array_values(array_unique($columns)),
                'site_key' => $siteKey,
                'line' => $lineNo,
            ];
        }

        return $units;
    }

    /**
     * @return string[]
     */
    private function extractArrayKeysFromExpr(string $expr, string $source, int $callStart): array
    {
        $expr = trim($expr);
        if ($expr === '') {
            return [];
        }

        // Inline array( 'k' => ... ) or array_merge( array( ... ), $data )
        if (preg_match('/^array_merge\s*\(/i', $expr)) {
            $keys = [];
            if (preg_match_all(
                '/[\'"]([a-z_][a-z0-9_]*)[\'"]\s*=>/i',
                $expr,
                $m
            )) {
                $keys = $m[1];
            }
            // Also resolve $data-style trailing vars if present.
            if (preg_match_all('/\$([a-zA-Z_][a-zA-Z0-9_]*)/', $expr, $vm)) {
                foreach ($vm[1] as $varName) {
                    $resolved = $this->resolveArrayVariableKeysFromContext($source, $callStart, $varName);
                    $keys = array_merge($keys, $resolved);
                }
            }
            return array_values(array_unique($keys));
        }

        if (preg_match('/^array\s*\(/i', $expr)) {
            if (preg_match_all(
                '/[\'"]([a-z_][a-z0-9_]*)[\'"]\s*=>/i',
                $expr,
                $m
            )) {
                return $m[1];
            }
            return [];
        }

        if (preg_match('/^\$([a-zA-Z_][a-zA-Z0-9_]*)$/', $expr, $vm)) {
            return $this->resolveArrayVariableKeysFromContext($source, $callStart, $vm[1]);
        }

        return [];
    }

    /**
     * @return string[]
     */
    private function resolveArrayVariableKeysFromContext(
        string $source,
        int $callStart,
        string $varName
    ): array {
        $windowStart = max(0, $callStart - 1200);
        $window = substr($source, $windowStart, $callStart - $windowStart);
        $quoted = preg_quote($varName, '/');

        if (preg_match(
            '/\$' . $quoted . '\s*=\s*array\s*\((.*?)\)\s*;/s',
            $window,
            $m
        )) {
            if (preg_match_all(
                '/[\'"]([a-z_][a-z0-9_]*)[\'"]\s*=>/i',
                $m[1],
                $km
            )) {
                return $km[1];
            }
        }

        return [];
    }

    /**
     * @param array<string, string|null> $aliasMap
     * @return list<array{kind:'bound',ref:array{file:string,table:string,column:string,alias:string}}|array{kind:'skip',skip:string}>
     */
    private function collectAliasQualifiedRefs(string $sql, array $aliasMap, string $basename): array
    {
        $out = [];
        // Walk tokens so alias.col inside FUNC(alias.col) is still captured, but
        // bare FUNC is not treated as an alias (PT-08).
        if (! preg_match_all(
            '/\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b/',
            $sql,
            $refs,
            PREG_SET_ORDER
        )) {
            return $out;
        }

        foreach ($refs as $ref) {
            $alias = $ref[1];
            $column = $ref[2];

            if (str_starts_with($alias, '%') || str_starts_with($column, '%')) {
                continue;
            }
            // Function names never appear as alias.column left of a dot in valid SQL
            // that we care about; still skip known keywords.
            if ($this->isSqlKeyword($alias)) {
                continue;
            }

            if (! array_key_exists($alias, $aliasMap)) {
                $out[] = [
                    'kind' => 'skip',
                    'skip' => sprintf(
                        '%s: %s.%s (no FROM/JOIN/UPDATE/INTO %%i binding)',
                        $basename,
                        $alias,
                        $column
                    ),
                ];
                continue;
            }

            $table = $aliasMap[$alias];
            if ($table === null) {
                $out[] = [
                    'kind' => 'skip',
                    'skip' => sprintf(
                        '%s: %s.%s (unresolved table expression for alias)',
                        $basename,
                        $alias,
                        $column
                    ),
                ];
                continue;
            }

            $out[] = [
                'kind' => 'bound',
                'ref' => [
                    'file' => $basename,
                    'table' => $table,
                    'column' => $column,
                    'alias' => $alias,
                ],
            ];
        }

        return $out;
    }

    /**
     * Unqualified write-path columns: UPDATE SET targets + RHS reads,
     * ON DUPLICATE KEY UPDATE, INSERT column lists.
     *
     * @param array<string, string|null> $aliasMap
     * @return list<array{file:string,table:string,column:string,alias:string}>
     */
    private function collectUnqualifiedWriteColumns(
        string $sql,
        array $aliasMap,
        ?string $primaryTable,
        string $basename
    ): array {
        $bound = [];

        if (preg_match('/\bUPDATE\b/i', $sql)) {
            if (preg_match('/\bSET\s+(.+?)(?:\bWHERE\b|$)/is', $sql, $setMatch)) {
                foreach ($this->parseAssignmentColumnRefs($setMatch[1]) as $target) {
                    $ref = $this->bindWriteTarget(
                        $target,
                        $aliasMap,
                        $primaryTable,
                        $basename
                    );
                    if ($ref !== null) {
                        $bound[] = $ref;
                    }
                }
            }
        }

        if (preg_match(
            '/\bON\s+DUPLICATE\s+KEY\s+UPDATE\s+(.+)$/is',
            $sql,
            $dupMatch
        )) {
            foreach ($this->parseAssignmentColumnRefs($dupMatch[1]) as $target) {
                $ref = $this->bindWriteTarget(
                    $target,
                    $aliasMap,
                    $primaryTable,
                    $basename
                );
                if ($ref !== null) {
                    $bound[] = $ref;
                }
            }
        }

        if (preg_match(
            '/\bINSERT\s+INTO\s+%i(?:\s+[a-zA-Z_][a-zA-Z0-9_]*)?\s*\(([^)]+)\)/is',
            $sql,
            $insMatch
        )) {
            $candidates = preg_split('/\s*,\s*/', trim($insMatch[1]));
            if (! is_array($candidates)) {
                $candidates = [];
            }
            foreach ($candidates as $candidate) {
                $candidate = trim((string) $candidate);
                if ($candidate === '' || ! preg_match('/^[a-z_][a-z0-9_]*$/i', $candidate)) {
                    continue;
                }
                if ($primaryTable === null) {
                    continue;
                }
                $bound[] = [
                    'file' => $basename,
                    'table' => $primaryTable,
                    'column' => $candidate,
                    'alias' => '',
                ];
            }
        }

        return $bound;
    }

    /**
     * Unqualified read-path columns on single-table statements.
     *
     * @return list<array{file:string,table:string,column:string,alias:string}>
     */
    private function collectUnqualifiedReadColumns(
        string $sql,
        ?string $primaryTable,
        string $basename
    ): array {
        if ($primaryTable === null) {
            return [];
        }
        if (preg_match('/\bJOIN\b/i', $sql)) {
            return [];
        }
        // Derived interiors are handled by collectAllColumnRefs recursion; outer
        // SQL after stripDerivedTableInteriors should not still contain FROM (.
        if (preg_match('/\bFROM\s*\(\s*SELECT\b/i', $sql)) {
            // Unresolvable derived frame without interior extraction — fail loud via skip? No:
            // outer primary may still be null; leave unqualified empty rather than invent.
            return [];
        }
        if (preg_match_all('/\b(?:FROM|JOIN|UPDATE|INTO)\s+%i\b/i', $sql) > 1) {
            return [];
        }

        $bound = [];
        $seen = [];

        if (preg_match('/\bSELECT\s+(.+?)\s+FROM\b/is', $sql, $selMatch)) {
            $selectList = $selMatch[1];
            $selectList = (string) preg_replace('/\bAS\s+[a-zA-Z_][a-zA-Z0-9_]*/i', '', $selectList);
            if (trim($selectList) !== '*' && ! preg_match('/^\s*%i\s*$/', $selectList)) {
                foreach ($this->collectColumnIdentifiersFromFragment($selectList) as $id) {
                    $seen[strtolower($id)] = $id;
                }
            }
        }

        if (preg_match('/\bWHERE\b(.+?)(?:\bORDER\s+BY\b|\bGROUP\s+BY\b|\bLIMIT\b|$)/is', $sql, $whereMatch)) {
            foreach ($this->collectColumnIdentifiersFromFragment($whereMatch[1]) as $id) {
                // WHERE tokens include operators; keep only plausible columns.
                if ($this->isPlausibleColumnIdentifier($id)) {
                    $seen[strtolower($id)] = $id;
                }
            }
        }

        if (preg_match('/\bORDER\s+BY\s+(.+?)(?:\bLIMIT\b|$)/is', $sql, $orderMatch)) {
            foreach ($this->collectColumnIdentifiersFromFragment($orderMatch[1]) as $id) {
                if ($this->isPlausibleColumnIdentifier($id)) {
                    $seen[strtolower($id)] = $id;
                }
            }
        }

        foreach ($seen as $column) {
            $bound[] = [
                'file' => $basename,
                'table' => $primaryTable,
                'column' => $column,
                'alias' => '',
            ];
        }

        return $bound;
    }

    /**
     * Tokenise a SQL fragment: IDENT( is a function (name skipped, args scanned);
     * bare keywords skipped; other bare identifiers are column candidates (PT-08).
     *
     * @return string[]
     */
    private function collectColumnIdentifiersFromFragment(string $fragment): array
    {
        $ids = [];
        $length = strlen($fragment);
        $i = 0;

        while ($i < $length) {
            $ch = $fragment[$i];

            // Skip string literals.
            if ($ch === "'" || $ch === '"') {
                $quote = $ch;
                $i++;
                while ($i < $length) {
                    if ($fragment[$i] === '\\') {
                        $i += 2;
                        continue;
                    }
                    if ($fragment[$i] === $quote) {
                        $i++;
                        break;
                    }
                    $i++;
                }
                continue;
            }

            // Skip placeholders %s %d %i %f
            if ($ch === '%' && $i + 1 < $length && preg_match('/^[sdfi]$/', $fragment[$i + 1])) {
                $i += 2;
                continue;
            }

            // Identifier or keyword or function.
            if (preg_match('/[a-zA-Z_]/', $ch)) {
                $start = $i;
                $i++;
                while ($i < $length && preg_match('/[a-zA-Z0-9_]/', $fragment[$i])) {
                    $i++;
                }
                $ident = substr($fragment, $start, $i - $start);

                // Skip whitespace to see if this is IDENT(
                $j = $i;
                while ($j < $length && ctype_space($fragment[$j])) {
                    $j++;
                }
                if ($j < $length && $fragment[$j] === '(') {
                    // Function call — do not treat name as column; recurse into args.
                    $depth = 0;
                    $argStart = $j + 1;
                    $k = $j;
                    while ($k < $length) {
                        if ($fragment[$k] === '(') {
                            $depth++;
                        } elseif ($fragment[$k] === ')') {
                            $depth--;
                            if ($depth === 0) {
                                $argBody = substr($fragment, $argStart, $k - $argStart);
                                foreach ($this->collectColumnIdentifiersFromFragment($argBody) as $inner) {
                                    $ids[] = $inner;
                                }
                                $i = $k + 1;
                                break;
                            }
                        } elseif ($fragment[$k] === "'" || $fragment[$k] === '"') {
                            $q = $fragment[$k];
                            $k++;
                            while ($k < $length && $fragment[$k] !== $q) {
                                if ($fragment[$k] === '\\') {
                                    $k++;
                                }
                                $k++;
                            }
                        }
                        $k++;
                    }
                    continue;
                }

                // Qualified alias.column — skip bare alias here; dotted form handled elsewhere.
                // But collect the column part when we see alias.column as two tokens? Handled by
                // the dotted matcher. If next non-ws is '.', skip the alias token.
                if ($j < $length && $fragment[$j] === '.') {
                    continue;
                }

                if ($this->isPlausibleColumnIdentifier($ident)) {
                    $ids[] = $ident;
                }
                continue;
            }

            $i++;
        }

        return $ids;
    }

    private function isSqlKeyword(string $id): bool
    {
        return in_array(strtolower($id), self::SQL_KEYWORDS, true);
    }

    private function isPlausibleColumnIdentifier(string $id): bool
    {
        if ($id === '' || str_starts_with($id, '%') || strtolower($id) === 'this') {
            return false;
        }
        if ($this->isSqlKeyword($id)) {
            return false;
        }
        // Single-letter tokens are almost always printf placeholders residual.
        if (strlen($id) === 1) {
            return false;
        }
        if (preg_match('/^\d+$/', $id)) {
            return false;
        }

        return (bool) preg_match('/^[a-z_][a-z0-9_]*$/i', $id);
    }

    /**
     * Parse SET / ON DUPLICATE assignments for both LHS targets and RHS column reads (PT-03).
     *
     * @return list<array{alias:?string,column:string}>
     */
    private function parseAssignmentColumnRefs(string $assignmentsSql): array
    {
        $targets = [];
        $parts = $this->splitTopLevelCommaSeparated($assignmentsSql);
        foreach ($parts as $part) {
            $part = trim($part);
            if ($part === '') {
                continue;
            }

            $eqPos = $this->findTopLevelEquals($part);
            if ($eqPos === null) {
                continue;
            }

            $lhs = trim(substr($part, 0, $eqPos));
            $rhs = trim(substr($part, $eqPos + 1));

            // LHS: alias.column or column
            if (preg_match(
                '/^([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)$/',
                $lhs,
                $m
            )) {
                $targets[] = ['alias' => $m[1], 'column' => $m[2]];
            } elseif (preg_match('/^([a-zA-Z_][a-zA-Z0-9_]*)$/', $lhs, $m)) {
                if (! $this->isSqlKeyword($m[1])) {
                    $targets[] = ['alias' => null, 'column' => $m[1]];
                }
            }

            // RHS: column identifiers (not literals, placeholders, or function names).
            // Qualified refs on RHS are rare in this corpus; collect bare + qualified.
            if (preg_match_all(
                '/\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b/',
                $rhs,
                $qRefs,
                PREG_SET_ORDER
            )) {
                foreach ($qRefs as $qr) {
                    $targets[] = ['alias' => $qr[1], 'column' => $qr[2]];
                }
            }

            foreach ($this->collectColumnIdentifiersFromFragment($rhs) as $id) {
                $targets[] = ['alias' => null, 'column' => $id];
            }
        }

        return $targets;
    }

    private function findTopLevelEquals(string $part): ?int
    {
        $depth = 0;
        $length = strlen($part);
        for ($i = 0; $i < $length; $i++) {
            $ch = $part[$i];
            if ($ch === '(') {
                $depth++;
                continue;
            }
            if ($ch === ')') {
                $depth--;
                continue;
            }
            if ($ch === "'" || $ch === '"') {
                $quote = $ch;
                $i++;
                while ($i < $length && $part[$i] !== $quote) {
                    if ($part[$i] === '\\') {
                        $i++;
                    }
                    $i++;
                }
                continue;
            }
            if ($ch === '=' && $depth === 0) {
                // Skip != <> <= >=
                $prev = $i > 0 ? $part[$i - 1] : '';
                $next = $i + 1 < $length ? $part[$i + 1] : '';
                if ($prev === '!' || $prev === '<' || $prev === '>' || $next === '=') {
                    continue;
                }
                return $i;
            }
        }
        return null;
    }

    /**
     * @param array{alias:?string,column:string} $target
     * @param array<string, string|null> $aliasMap
     * @return array{file:string,table:string,column:string,alias:string}|null
     */
    private function bindWriteTarget(
        array $target,
        array $aliasMap,
        ?string $primaryTable,
        string $basename
    ): ?array {
        $column = $target['column'];
        $alias = $target['alias'];

        if ($alias !== null) {
            if (! array_key_exists($alias, $aliasMap) || $aliasMap[$alias] === null) {
                return null;
            }
            return [
                'file' => $basename,
                'table' => $aliasMap[$alias],
                'column' => $column,
                'alias' => $alias,
            ];
        }

        if ($primaryTable === null) {
            return null;
        }

        return [
            'file' => $basename,
            'table' => $primaryTable,
            'column' => $column,
            'alias' => '',
        ];
    }

    /**
     * Primary table for a unit: first UPDATE/INSERT/FROM/DELETE %i binding.
     *
     * @param string[] $args
     */
    private function resolvePrimaryTable(string $sql, array $args, string $basename): ?string
    {
        if (! preg_match_all('/%[sdfi]/', $sql, $placeholderMatches, PREG_OFFSET_CAPTURE)) {
            return null;
        }
        $placeholders = $placeholderMatches[0];

        if (! preg_match(
            '/\b(?:UPDATE|INSERT\s+INTO|FROM|DELETE(?:\s+\w+)?\s+FROM)\s+%i\b/i',
            $sql,
            $m,
            PREG_OFFSET_CAPTURE
        )) {
            // Derived-only outer frame: no direct %i — primary is unknown at this level.
            return null;
        }

        $kwOffset = $m[0][1];
        $chosen = null;
        foreach ($placeholders as $index => $placeholder) {
            if ($placeholder[0] !== '%i') {
                continue;
            }
            if ($placeholder[1] >= $kwOffset && $placeholder[1] <= $kwOffset + strlen($m[0][0]) + 4) {
                $chosen = $index;
                break;
            }
        }
        if ($chosen === null) {
            foreach ($placeholders as $index => $placeholder) {
                if ($placeholder[0] === '%i') {
                    $chosen = $index;
                    break;
                }
            }
        }
        if ($chosen === null) {
            return null;
        }

        $expr = $args[$chosen] ?? null;
        if ($expr === null) {
            return null;
        }

        return $this->resolveTableSuffix($expr, $basename);
    }

    /**
     * @return array{
     *     units: list<array{sql:string,args:string[],label:string,method:string,line:int,site_key:string}>,
     *     dropped: list<string>,
     *     dropped_keys: array<string, string>,
     *     call_count: int
     * }
     */
    private function extractPrepareQueryUnits(string $source, string $basename): array
    {
        $units = [];
        $dropped = [];
        $droppedKeys = [];
        $callCount = 0;
        $offset = 0;
        $length = strlen($source);

        // Match every PREPARE_FAMILY_METHODS name. Order longer names first so
        // prepare_query never steals a prepare_projection_read_query site.
        $methods = self::PREPARE_FAMILY_METHODS;
        usort($methods, static fn (string $a, string $b): int => strlen($b) <=> strlen($a));
        $prepareAlternation = implode(
            '|',
            array_map(static fn (string $m): string => preg_quote($m, '/'), $methods)
        );
        while (preg_match(
            '/->(' . $prepareAlternation . ')\s*\(/',
            $source,
            $match,
            PREG_OFFSET_CAPTURE,
            $offset
        )) {
            $callCount++;
            $methodName = $match[1][0];
            $callStart = $match[0][1];
            $lineNo = substr_count(substr($source, 0, $callStart), "\n") + 1;
            $siteKey = $basename . ':' . $lineNo . ':' . $methodName;
            $start = $match[0][1] + strlen($match[0][0]);
            $depth = 1;
            $i = $start;
            while ($i < $length && $depth > 0) {
                $ch = $source[$i];
                if ($ch === "'" || $ch === '"') {
                    $quote = $ch;
                    $i++;
                    while ($i < $length) {
                        if ($source[$i] === '\\') {
                            $i += 2;
                            continue;
                        }
                        if ($source[$i] === $quote) {
                            $i++;
                            break;
                        }
                        $i++;
                    }
                    continue;
                }
                if ($ch === '(') {
                    $depth++;
                } elseif ($ch === ')') {
                    $depth--;
                }
                $i++;
            }

            $callBody = substr($source, $start, $i - $start - 1);
            $offset = $i;
            $signature = $this->callSignature($callBody);

            if (! preg_match(
                '/^\s*(["\'])((?:\\\\.|(?!\1).)*)\1\s*,\s*(.*)$/s',
                $callBody,
                $parts
            )) {
                $detail = sprintf(
                    '%s:%s — first argument is not a string literal',
                    $basename,
                    $signature
                );
                $dropped[] = $detail;
                $droppedKeys[$siteKey] = $detail;
                continue;
            }

            $sql = stripcslashes($parts[2]);
            $rest = $parts[3];

            if (preg_match_all('/\{\$([a-zA-Z_][a-zA-Z0-9_]*)\}/', $sql, $interpMatches)) {
                $this->assertDynamicInterpolationsArePlaceholders(
                    $source,
                    $callStart,
                    $interpMatches[1],
                    $basename,
                    $signature
                );
                $sql = (string) preg_replace('/\{\$[a-zA-Z_][a-zA-Z0-9_]*\}/', '', $sql);
            }

            // Double-quoted PHP strings with $placeholders bare interpolation.
            if (preg_match_all('/(?<!\{)\$([a-zA-Z_][a-zA-Z0-9_]*)/', $sql, $bareInterp)) {
                $this->assertDynamicInterpolationsArePlaceholders(
                    $source,
                    $callStart,
                    $bareInterp[1],
                    $basename,
                    $signature
                );
                $sql = (string) preg_replace('/(?<!\{)\$[a-zA-Z_][a-zA-Z0-9_]*/', '', $sql);
            }

            $args = [];
            // Leading backslash allowed for fully-qualified \array_merge / \array.
            if (preg_match('/^\\\\?array_merge\s*\(\s*\\\\?array\s*\((.*)\)\s*,/s', $rest, $arrayMatch)) {
                $args = $this->splitTopLevelArgs($arrayMatch[1]);
            } elseif (preg_match('/^\\\\?array\s*\((.*)\)\s*$/s', $rest, $arrayMatch)) {
                $args = $this->splitTopLevelArgs($arrayMatch[1]);
            } elseif (preg_match('/^\$([a-zA-Z_][a-zA-Z0-9_]*)\s*$/', trim($rest), $varMatch)) {
                $args = $this->resolveArgsVariableFromContext(
                    $source,
                    $callStart,
                    $varMatch[1]
                );
                if ($args === null) {
                    $args = [];
                }
            } else {
                $detail = sprintf(
                    '%s:%s — arguments are neither array(...), array_merge(...), nor a simple variable',
                    $basename,
                    $signature
                );
                $dropped[] = $detail;
                $droppedKeys[$siteKey] = $detail;
                continue;
            }

            $units[] = [
                'sql' => $sql,
                'args' => $args,
                'label' => $basename . ':' . $signature,
                'method' => $methodName,
                'line' => $lineNo,
                'site_key' => $siteKey,
            ];
        }

        return [
            'units' => $units,
            'dropped' => $dropped,
            'dropped_keys' => $droppedKeys,
            'call_count' => $callCount,
        ];
    }

    /**
     * @param string[] $varNames
     */
    private function assertDynamicInterpolationsArePlaceholders(
        string $source,
        int $callStart,
        array $varNames,
        string $basename,
        string $signature
    ): void {
        $windowStart = max(0, $callStart - 600);
        $window = substr($source, $windowStart, $callStart - $windowStart + 200);

        foreach ($varNames as $varName) {
            $pattern = '/\$' . preg_quote($varName, '/')
                . '\s*=\s*implode\s*\(\s*[\'"],\s*[\'"]\s*,\s*array_fill\s*\(\s*[^,]+,\s*[^,]+,\s*[\'"](%[sd])[\'"]\s*\)/s';
            if (! preg_match($pattern, $window)) {
                $loose = '/\$' . preg_quote($varName, '/')
                    . '\s*=\s*[^;]*array_fill\s*\(\s*[^;]*[\'"](%[sd])[\'"]/s';
                $this->assertMatchesRegularExpression(
                    $loose,
                    $window,
                    sprintf(
                        '%s:%s interpolates {$%s} but nearby assignment is not array_fill(%%s|%%d) — '
                        . 'dynamic region must be placeholder-only (BR-07)',
                        $basename,
                        $signature,
                        $varName
                    )
                );
            }
        }
    }

    /**
     * @return string[]|null
     */
    private function resolveArgsVariableFromContext(
        string $source,
        int $callStart,
        string $varName
    ): ?array {
        $windowStart = max(0, $callStart - 800);
        $window = substr($source, $windowStart, $callStart - $windowStart);

        $quoted = preg_quote($varName, '/');
        if (preg_match(
            '/\$' . $quoted . '\s*=\s*array_merge\s*\(\s*array\s*\((.*)\)\s*,/s',
            $window,
            $m
        )) {
            return $this->splitTopLevelArgs($m[1]);
        }
        if (preg_match(
            '/\$' . $quoted . '\s*=\s*array\s*\((.*)\)\s*;/s',
            $window,
            $m
        )) {
            return $this->splitTopLevelArgs($m[1]);
        }

        return null;
    }

    private function callSignature(string $callBody): string
    {
        $flat = preg_replace('/\s+/', ' ', trim($callBody)) ?? trim($callBody);
        if (strlen($flat) > 72) {
            return substr($flat, 0, 72);
        }
        return $flat;
    }

    /**
     * @return string[]
     */
    private function splitTopLevelArgs(string $body): array
    {
        $parts = [];
        $buffer = '';
        $depth = 0;
        $length = strlen($body);
        $inString = null;

        for ($i = 0; $i < $length; $i++) {
            $ch = $body[$i];
            if ($inString !== null) {
                $buffer .= $ch;
                if ($ch === '\\' && $i + 1 < $length) {
                    $buffer .= $body[$i + 1];
                    $i++;
                    continue;
                }
                if ($ch === $inString) {
                    $inString = null;
                }
                continue;
            }
            if ($ch === "'" || $ch === '"') {
                $inString = $ch;
                $buffer .= $ch;
                continue;
            }
            if ($ch === '(' || $ch === '[') {
                $depth++;
                $buffer .= $ch;
                continue;
            }
            if ($ch === ')' || $ch === ']') {
                $depth--;
                $buffer .= $ch;
                continue;
            }
            if ($ch === ',' && $depth === 0) {
                $trimmed = trim($buffer);
                if ($trimmed !== '') {
                    $parts[] = $trimmed;
                }
                $buffer = '';
                continue;
            }
            $buffer .= $ch;
        }

        $trimmed = trim($buffer);
        if ($trimmed !== '') {
            $parts[] = $trimmed;
        }

        return $parts;
    }

    /**
     * @return string[]
     */
    private function splitTopLevelCommaSeparated(string $body): array
    {
        return $this->splitTopLevelArgs($body);
    }

    /**
     * @param string[] $args
     * @return array<string, string|null>
     */
    private function bindAliasesToTables(string $sql, array $args, string $basename): array
    {
        if (! preg_match_all('/%[sdfi]/', $sql, $placeholderMatches, PREG_OFFSET_CAPTURE)) {
            return [];
        }
        $placeholders = $placeholderMatches[0];

        $aliasToPlaceholderIndex = [];
        if (preg_match_all(
            '/\b(?:FROM|JOIN|UPDATE|INTO)\s+%i\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\b/i',
            $sql,
            $aliasMatches,
            PREG_OFFSET_CAPTURE
        )) {
            foreach ($aliasMatches[1] as $aliasHit) {
                $alias = $aliasHit[0];
                if ($this->isSqlKeyword($alias)) {
                    continue;
                }
                $aliasOffset = $aliasHit[1];
                $chosen = null;
                foreach ($placeholders as $index => $placeholder) {
                    if ($placeholder[0] === '%i' && $placeholder[1] < $aliasOffset) {
                        $chosen = $index;
                    }
                }
                if ($chosen !== null) {
                    $aliasToPlaceholderIndex[$alias] = $chosen;
                }
            }
        }

        $map = [];
        foreach ($aliasToPlaceholderIndex as $alias => $placeholderIndex) {
            $expr = $args[$placeholderIndex] ?? null;
            if ($expr === null) {
                $map[$alias] = null;
                continue;
            }
            $map[$alias] = $this->resolveTableSuffix($expr, $basename);
        }

        return $map;
    }

    private function resolveTableSuffix(string $expr, string $basename): ?string
    {
        $expr = trim($expr);

        if (preg_match("/['\"](acx_[a-z0-9_]+)['\"]/", $expr, $match)) {
            return $match[1];
        }

        if (preg_match('/acx_[a-z0-9_]+/', $expr, $match)) {
            return $match[0];
        }

        // Specific property / variable names before basename heuristics so
        // $this->outbox_table_name in sync-state-repository does not collapse
        // to acx_sync_state, and $persons_table in clusters-read stays persons.
        $needles = [
            'batch_run_failures' => 'acx_batch_run_failures',
            'batch_failures' => 'acx_batch_run_failures',
            'failures_table' => 'acx_batch_run_failures',
            'description_run_items' => 'acx_description_run_items',
            'items_table_name' => 'acx_description_run_items',
            'items_table' => 'acx_description_run_items',
            'description_runs' => 'acx_description_runs',
            'description_usage' => 'acx_description_usage',
            'topology_commands_table' => 'acx_topology_commands',
            'topology_commands' => 'acx_topology_commands',
            'topology_table' => 'acx_topology_commands',
            'identity_members' => 'acx_identity_members',
            'members_table' => 'acx_identity_members',
            'conflicts_table' => 'acx_sync_conflicts',
            'outbox_table' => 'acx_sync_outbox',
            'sync_outbox' => 'acx_sync_outbox',
            'sync_conflicts' => 'acx_sync_conflicts',
            'sync_state' => 'acx_sync_state',
            'topology' => 'acx_topology_commands',
            'conflicts' => 'acx_sync_conflicts',
            'persons_table' => 'acx_persons',
            'table_persons' => 'acx_persons',
            'persons' => 'acx_persons',
            'table_clusters' => 'acx_clusters',
            'clusters_table' => 'acx_clusters',
            'clusters' => 'acx_clusters',
            'table_members' => 'acx_identity_members',
            'batch_runs' => 'acx_batch_runs',
            'outbox' => 'acx_sync_outbox',
        ];
        foreach ($needles as $needle => $suffix) {
            if (stripos($expr, $needle) !== false) {
                return $suffix;
            }
        }

        if (stripos($expr, 'resolve_persons') !== false) {
            return 'acx_persons';
        }

        // Generic $this->table_name / $this->runs_table_name — basename fallback.
        // Do not match $persons_table / $this->outbox_table_name (needles above).
        if (
            preg_match('/\$this->table(?:_name)?\b/', $expr)
            || preg_match('/\$this->runs_table_name\b/', $expr)
            || preg_match('/^\$table(?:_name)?$/i', $expr)
        ) {
            if (str_contains($basename, 'identity-member')) {
                return 'acx_identity_members';
            }
            if (str_contains($basename, 'cluster')) {
                return 'acx_clusters';
            }
            if (str_contains($basename, 'sync-state')) {
                return 'acx_sync_state';
            }
            if (str_contains($basename, 'batch-run')) {
                return 'acx_batch_runs';
            }
            if (str_contains($basename, 'description-usage')) {
                return 'acx_description_usage';
            }
            if (str_contains($basename, 'description-run')) {
                return 'acx_description_runs';
            }
        }

        // description-run $this->runs_table_name vs batch-run $this->runs_table_name
        // already handled; items:
        if (preg_match('/\$this->items_table_name\b/', $expr)) {
            return 'acx_description_run_items';
        }
        if (preg_match('/\$this->failures_table_name\b/', $expr)) {
            return 'acx_batch_run_failures';
        }

        return null;
    }

    private function displayTableName(string $tableSuffix): string
    {
        return str_starts_with($tableSuffix, 'acx_')
            ? substr($tableSuffix, 4)
            : $tableSuffix;
    }
}
