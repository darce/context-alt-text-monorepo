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
 *  - SQL column refs from alias-qualified references AND unqualified SET /
 *    ON DUPLICATE KEY UPDATE / INSERT column-list targets in repository sources
 *
 * Call-site and skip accounting (OBS-08): every prepare_query site must be
 * extracted or explicitly allowlisted; every unresolved alias.column must be
 * allowlisted; stale allowlist entries fail. Silence is not coverage.
 *
 * @coversNothing
 */
class ProjectionQueryColumnParityTest extends TestCase
{
    /**
     * Expected unresolved alias.column skips, keyed by "basename:alias.column".
     * Justified only for derived-table aliases that are not projection %i bindings.
     * An unexpected skip fails; an allowlist entry that no longer skips fails (OBS-08).
     */
    private const ALLOWED_SKIPS = [
        'class-clusters-read-repository.php:filtered.label' =>
            'derived-table alias from subquery (SELECT ... FROM %i ...) filtered — not a projection table binding',
    ];

    /**
     * prepare_query call sites that cannot yield a string-literal unit.
     * Keyed by "basename:signature" where signature is a stable snippet of the call body.
     * Empty by design once the dynamic-IN site is extracted via static-prefix handling.
     * Stale entries fail (OBS-08).
     *
     * @var array<string, string>
     */
    private const ALLOWED_DROPPED_CALLS = [];

    /**
     * Projection tables with no prepare_query SQL surface in sovereign repositories.
     * They are written via $wpdb->insert/$wpdb->update array maps instead.
     * Unexpected uncovered tables fail; allowlist entries that gain bound refs fail (OBS-08).
     *
     * @var array<string, string>
     */
    private const ALLOWED_UNCOVERED_TABLES = [
        'acx_description_runs' =>
            'no prepare_query surface; class-description-run-repository uses $wpdb->insert/update only',
        'acx_description_run_items' =>
            'no prepare_query surface; class-description-run-repository uses $wpdb->insert/update only',
    ];

    /** SQL keywords / functions that must never be treated as unqualified column names. */
    private const SQL_NON_COLUMNS = [
        'and', 'or', 'not', 'null', 'true', 'false', 'is', 'in', 'like', 'exists',
        'select', 'from', 'where', 'join', 'left', 'right', 'inner', 'outer', 'cross',
        'on', 'as', 'set', 'update', 'insert', 'into', 'values', 'delete', 'order',
        'by', 'group', 'having', 'limit', 'offset', 'union', 'all', 'distinct',
        'count', 'max', 'min', 'sum', 'avg', 'case', 'when', 'then', 'else', 'end',
        'asc', 'desc', 'over', 'partition', 'row_number', 'coalesce', 'greatest',
        'least', 'if', 'nullif', 'dual', 'primary', 'key', 'index', 'unique',
        'default', 'interval', 'date', 'time', 'datetime', 'timestamp', 'cast',
        'convert', 'between', 'escape', 'regexp', 'rlike', 'xor', 'div', 'mod',
        'binary', 'collate', 'using', 'force', 'ignore', 'straight_join',
        'natural', 'lateral', 'window', 'rows', 'range', 'unbounded', 'preceding',
        'following', 'current', 'row', 'filter', 'within', 'separator', 'both',
        'leading', 'trailing', 'for', 'lock', 'share', 'mode', 'nowait', 'skip',
        'of', 'with', 'recursive', 'materialized', 'values', 'duplicate',
    ];

    /**
     * Every confidently-bound column reference in sovereign repository SQL
     * must exist in that table's projection DDL column set.
     *
     * Also asserts call-site accounting (BR-07) and skip allowlisting (BR-06).
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
        );
    }

    /**
     * Every projection DDL table must contribute at least one bound SQL column
     * ref, or the gap must be explicit. Table-shaped allowlists alone are not
     * schema coverage (BR-13 / OBS-08).
     */
    public function testEveryProjectionTableHasBoundSqlColumnCoverage(): void
    {
        $ddlColumnsByTable = $this->parseProjectionDdlColumns();
        $scan = $this->scanRepositorySqlColumnRefs();

        $tablesWithBoundRefs = [];
        foreach ($scan['bound'] as $ref) {
            $tablesWithBoundRefs[$ref['table']] = true;
        }

        $uncovered = [];
        foreach (array_keys($ddlColumnsByTable) as $table) {
            if (! isset($tablesWithBoundRefs[$table])) {
                $uncovered[] = $table;
            }
        }

        $unexpected = [];
        foreach ($uncovered as $table) {
            if (! array_key_exists($table, self::ALLOWED_UNCOVERED_TABLES)) {
                $unexpected[] = $table;
            }
        }

        $stale = [];
        foreach (array_keys(self::ALLOWED_UNCOVERED_TABLES) as $table) {
            if (isset($tablesWithBoundRefs[$table])) {
                $stale[] = $table;
            }
            if (! array_key_exists($table, $ddlColumnsByTable)) {
                $stale[] = $table . '(removed from DDL)';
            }
        }

        $this->assertSame(
            [],
            $unexpected,
            'Projection DDL tables with zero bound SQL column refs and not on ALLOWED_UNCOVERED_TABLES '
            . '(schema-shaped gap, BR-13 / OBS-08): ' . implode(', ', $unexpected)
        );
        $this->assertSame(
            [],
            $stale,
            'ALLOWED_UNCOVERED_TABLES entries that now have bound refs or left the DDL — '
            . 'dead instrumentation (OBS-08): ' . implode(', ', $stale)
        );
    }

    /**
     * @param list<string> $dropped
     */
    private function assertCallSitesAccountedFor(int $callCount, int $extractedCount, array $dropped): void
    {
        $this->assertGreaterThan(
            0,
            $callCount,
            'no prepare_query call sites found in sovereign repositories'
        );

        $allowedKeys = array_keys(self::ALLOWED_DROPPED_CALLS);
        $droppedKeys = [];
        foreach ($dropped as $entry) {
            // entry format: "basename:signature — reason-detail"
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
            'prepare_query call sites dropped without extraction and not on ALLOWED_DROPPED_CALLS (BR-07 / OBS-08): '
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
            'prepare_query call_count must equal extracted + dropped'
        );
    }

    /**
     * @param list<string> $skipped
     */
    private function assertSkippedBindingsAllowlisted(array $skipped): void
    {
        $skipKeys = [];
        foreach ($skipped as $entry) {
            // "basename: alias.column (reason)" → "basename:alias.column"
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
     * @return array{
     *     bound: list<array{file:string,table:string,column:string,alias:string}>,
     *     skipped: list<string>,
     *     dropped: list<string>,
     *     call_count: int,
     *     extracted_count: int
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
        $callCount = 0;
        $extractedCount = 0;

        foreach ($files as $path) {
            $basename = basename($path);
            if ($basename === 'trait-prepares-sql-queries.php') {
                continue;
            }
            $source = (string) file_get_contents($path);
            $extraction = $this->extractPrepareQueryUnits($source, $basename);
            $callCount += $extraction['call_count'];
            $extractedCount += count($extraction['units']);
            foreach ($extraction['dropped'] as $d) {
                $dropped[] = $d;
            }

            foreach ($extraction['units'] as $unit) {
                $aliasMap = $this->bindAliasesToTables(
                    $unit['sql'],
                    $unit['args'],
                    $basename
                );

                // Implicit sole-table binding for UPDATE/INSERT/FROM %i with no alias.
                $primaryTable = $this->resolvePrimaryTable($unit['sql'], $unit['args'], $basename);

                foreach ($this->collectAliasQualifiedRefs($unit['sql'], $aliasMap, $basename) as $item) {
                    if ($item['kind'] === 'bound') {
                        $bound[] = $item['ref'];
                    } else {
                        $skipped[] = $item['skip'];
                    }
                }

                foreach ($this->collectUnqualifiedWriteColumns(
                    $unit['sql'],
                    $aliasMap,
                    $primaryTable,
                    $basename
                ) as $ref) {
                    $bound[] = $ref;
                }

                foreach ($this->collectUnqualifiedReadColumns(
                    $unit['sql'],
                    $primaryTable,
                    $basename
                ) as $ref) {
                    $bound[] = $ref;
                }
            }
        }

        return [
            'bound' => $bound,
            'skipped' => $skipped,
            'dropped' => $dropped,
            'call_count' => $callCount,
            'extracted_count' => $extractedCount,
        ];
    }

    /**
     * @param array<string, string|null> $aliasMap
     * @return list<array{kind:'bound',ref:array{file:string,table:string,column:string,alias:string}}|array{kind:'skip',skip:string}>
     */
    private function collectAliasQualifiedRefs(string $sql, array $aliasMap, string $basename): array
    {
        $out = [];
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

            // Skip SQL decimal/float fragments and placeholder-looking tokens.
            if (str_starts_with($alias, '%') || str_starts_with($column, '%')) {
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
     * Unqualified write-path columns: UPDATE SET targets, ON DUPLICATE KEY UPDATE
     * assignments, and INSERT column lists — bound to the statement's primary table.
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

        // UPDATE ... SET col = ..., alias.col = ...
        if (preg_match('/\bUPDATE\b/i', $sql)) {
            if (preg_match('/\bSET\s+(.+?)(?:\bWHERE\b|$)/is', $sql, $setMatch)) {
                foreach ($this->parseAssignmentTargets($setMatch[1]) as $target) {
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

        // ON DUPLICATE KEY UPDATE col = ...
        if (preg_match(
            '/\bON\s+DUPLICATE\s+KEY\s+UPDATE\s+(.+)$/is',
            $sql,
            $dupMatch
        )) {
            foreach ($this->parseAssignmentTargets($dupMatch[1]) as $target) {
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

        // INSERT INTO %i (col, col, ...) or INSERT INTO %i\n(col, ...)
        if (preg_match(
            '/\bINSERT\s+INTO\s+%i(?:\s+[a-zA-Z_][a-zA-Z0-9_]*)?\s*\(([^)]+)\)/is',
            $sql,
            $insMatch
        )) {
            foreach (preg_split('/\s*,\s*/', trim($insMatch[1])) ?: [] as $candidate) {
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
     * Unqualified read-path columns on single-table statements:
     * SELECT col lists, WHERE/ORDER BY identifiers.
     * Skipped when JOIN is present or more than one table %i appears, to avoid
     * false-positive storms against multi-table SQL (BR-12).
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
        // Subquery wrappers (FROM (SELECT ...)) introduce derived aliases — skip.
        if (preg_match('/\bFROM\s*\(/i', $sql)) {
            return [];
        }
        // More than one table-shaped %i (FROM/UPDATE/INTO/JOIN) → multi-table.
        if (preg_match_all('/\b(?:FROM|JOIN|UPDATE|INTO)\s+%i\b/i', $sql) > 1) {
            return [];
        }

        $bound = [];
        $seen = [];

        // SELECT a, b, MAX(c) FROM ... — strip AS aliases; ignore * and dynamic %i.
        if (preg_match('/\bSELECT\s+(.+?)\s+FROM\b/is', $sql, $selMatch)) {
            $selectList = $selMatch[1];
            // Drop "AS alias" output names so they are not treated as table columns.
            $selectList = (string) preg_replace('/\bAS\s+[a-zA-Z_][a-zA-Z0-9_]*/i', '', $selectList);
            if (trim($selectList) !== '*' && ! preg_match('/^\s*%i\s*$/', $selectList)) {
                if (preg_match_all(
                    '/(?<!%)\b([a-zA-Z_][a-zA-Z0-9_]*)\b/',
                    $selectList,
                    $idMatches
                )) {
                    foreach ($idMatches[1] as $id) {
                        if ($this->isPlausibleColumnIdentifier($id)) {
                            $seen[strtolower($id)] = $id;
                        }
                    }
                }
            }
        }

        // WHERE / AND / OR col =|IN|LIKE|IS|<|> ...
        if (preg_match('/\bWHERE\b(.+?)(?:\bORDER\s+BY\b|\bGROUP\s+BY\b|\bLIMIT\b|$)/is', $sql, $whereMatch)) {
            if (preg_match_all(
                '/(?<!%)\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=|!=|<>|<=|>=|<|>|\bIS\b|\bIN\b|\bLIKE\b|\bNOT\b)/i',
                $whereMatch[1],
                $wMatches
            )) {
                foreach ($wMatches[1] as $id) {
                    if ($this->isPlausibleColumnIdentifier($id)) {
                        $seen[strtolower($id)] = $id;
                    }
                }
            }
        }

        // ORDER BY col ASC/DESC, col2
        if (preg_match('/\bORDER\s+BY\s+(.+?)(?:\bLIMIT\b|$)/is', $sql, $orderMatch)) {
            if (preg_match_all(
                '/(?<!%)\b([a-zA-Z_][a-zA-Z0-9_]*)\b/',
                $orderMatch[1],
                $oMatches
            )) {
                foreach ($oMatches[1] as $id) {
                    if ($this->isPlausibleColumnIdentifier($id)) {
                        $seen[strtolower($id)] = $id;
                    }
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

    private function isPlausibleColumnIdentifier(string $id): bool
    {
        if ($id === '' || str_starts_with($id, '%')) {
            return false;
        }
        if (in_array(strtolower($id), self::SQL_NON_COLUMNS, true)) {
            return false;
        }
        // Single-letter tokens are almost always printf placeholders (%s/%d/%f/%i).
        if (strlen($id) === 1) {
            return false;
        }
        if (preg_match('/^\d+$/', $id)) {
            return false;
        }

        return (bool) preg_match('/^[a-z_][a-z0-9_]*$/i', $id);
    }

    /**
     * @return list<array{alias:?string,column:string}>
     */
    private function parseAssignmentTargets(string $assignmentsSql): array
    {
        $targets = [];
        $parts = $this->splitTopLevelCommaSeparated($assignmentsSql);
        foreach ($parts as $part) {
            $part = trim($part);
            if ($part === '') {
                continue;
            }
            // alias.column = expr  OR  column = expr
            if (preg_match(
                '/^([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=/s',
                $part,
                $m
            )) {
                $targets[] = ['alias' => $m[1], 'column' => $m[2]];
                continue;
            }
            if (preg_match('/^([a-zA-Z_][a-zA-Z0-9_]*)\s*=/s', $part, $m)) {
                $column = $m[1];
                if (in_array(strtolower($column), self::SQL_NON_COLUMNS, true)) {
                    continue;
                }
                $targets[] = ['alias' => null, 'column' => $column];
            }
        }

        return $targets;
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
            return null;
        }

        $kwOffset = $m[0][1];
        $chosen = null;
        foreach ($placeholders as $index => $placeholder) {
            if ($placeholder[0] === '%i' && $placeholder[1] >= $kwOffset) {
                $chosen = $index;
                break;
            }
            if ($placeholder[0] === '%i' && $placeholder[1] < $kwOffset) {
                $chosen = $index;
            }
        }
        // Prefer the %i that sits inside the matched keyword phrase.
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
     *     units: list<array{sql:string,args:string[],label:string}>,
     *     dropped: list<string>,
     *     call_count: int
     * }
     */
    private function extractPrepareQueryUnits(string $source, string $basename): array
    {
        $units = [];
        $dropped = [];
        $callCount = 0;
        $offset = 0;
        $length = strlen($source);

        while (preg_match('/->prepare_query\s*\(/', $source, $match, PREG_OFFSET_CAPTURE, $offset)) {
            $callCount++;
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
            $signature = $this->callSignature($callBody);

            if (! preg_match(
                '/^\s*(["\'])((?:\\\\.|(?!\1).)*)\1\s*,\s*(.*)$/s',
                $callBody,
                $parts
            )) {
                $dropped[] = sprintf(
                    '%s:%s — first argument is not a string literal',
                    $basename,
                    $signature
                );
                continue;
            }

            $sql = stripcslashes($parts[2]);
            $rest = $parts[3];

            // Normalize PHP double-quoted interpolations used for dynamic IN lists.
            // Static prefix is retained for column scanning; interpolated region must
            // be placeholder-only (asserted when present).
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

            $args = [];
            if (preg_match('/^array_merge\s*\(\s*array\s*\((.*)\)\s*,/s', $rest, $arrayMatch)) {
                $args = $this->splitTopLevelArgs($arrayMatch[1]);
            } elseif (preg_match('/^array\s*\((.*)\)\s*$/s', $rest, $arrayMatch)) {
                $args = $this->splitTopLevelArgs($arrayMatch[1]);
            } elseif (preg_match('/^\$([a-zA-Z_][a-zA-Z0-9_]*)\s*$/', trim($rest), $varMatch)) {
                $args = $this->resolveArgsVariableFromContext(
                    $source,
                    $callStart,
                    $varMatch[1]
                );
                if ($args === null) {
                    // Still extract the SQL unit so static columns are asserted;
                    // table binding may fall back to basename heuristics via empty args.
                    $args = [];
                }
            } else {
                $dropped[] = sprintf(
                    '%s:%s — arguments are neither array(...), array_merge(...), nor a simple variable',
                    $basename,
                    $signature
                );
                continue;
            }

            $units[] = [
                'sql' => $sql,
                'args' => $args,
                'label' => $basename . ':' . $signature,
            ];
        }

        return [
            'units' => $units,
            'dropped' => $dropped,
            'call_count' => $callCount,
        ];
    }

    /**
     * Dynamic IN interpolations must expand to %s / %d placeholders only (BR-07).
     *
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
            // $placeholders = implode( ', ', array_fill( 0, count( $statuses ), '%s' ) );
            $pattern = '/\$' . preg_quote($varName, '/')
                . '\s*=\s*implode\s*\(\s*[\'"],\s*[\'"]\s*,\s*array_fill\s*\(\s*[^,]+,\s*[^,]+,\s*[\'"](%[sd])[\'"]\s*\)/s';
            if (! preg_match($pattern, $window)) {
                // Also accept single-quoted implode glue variants already covered;
                // fall back to any array_fill producing %s or %d assigned to the var.
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
     * Resolve `$args = array_merge( array( ... ), ... )` or `$args = array( ... )`
     * appearing just above a prepare_query call.
     *
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

        for ($i = 0; $i < $length; $i++) {
            $ch = $body[$i];
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
     * Split on commas that are not inside parentheses.
     *
     * @return string[]
     */
    private function splitTopLevelCommaSeparated(string $body): array
    {
        return $this->splitTopLevelArgs($body);
    }

    /**
     * Map SQL aliases to projection table suffixes via %i placeholder args.
     * Accepts optional SQL-legal AS keyword (BR-06).
     *
     * @param string[] $args prepare_query arg expressions in placeholder order
     * @return array<string, string|null> alias => table suffix (null if unresolved)
     */
    private function bindAliasesToTables(string $sql, array $args, string $basename): array
    {
        if (! preg_match_all('/%[sdfi]/', $sql, $placeholderMatches, PREG_OFFSET_CAPTURE)) {
            return [];
        }
        $placeholders = $placeholderMatches[0];

        $aliasToPlaceholderIndex = [];
        // FROM/JOIN/UPDATE/INTO %i [AS] alias — AS is optional SQL-legal form.
        if (preg_match_all(
            '/\b(?:FROM|JOIN|UPDATE|INTO)\s+%i\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\b/i',
            $sql,
            $aliasMatches,
            PREG_OFFSET_CAPTURE
        )) {
            foreach ($aliasMatches[1] as $aliasHit) {
                $alias = $aliasHit[0];
                // Do not treat SQL keywords after %i as aliases (e.g. UPDATE %i SET).
                if (in_array(strtolower($alias), self::SQL_NON_COLUMNS, true)) {
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

        // Most-specific needles first.
        $needles = [
            'batch_run_failures' => 'acx_batch_run_failures',
            'batch_failures' => 'acx_batch_run_failures',
            'failures_table' => 'acx_batch_run_failures',
            'description_run_items' => 'acx_description_run_items',
            'description_runs' => 'acx_description_runs',
            'description_usage' => 'acx_description_usage',
            'topology_commands_table' => 'acx_topology_commands',
            'topology_commands' => 'acx_topology_commands',
            'topology_table' => 'acx_topology_commands',
            'identity_members' => 'acx_identity_members',
            'members_table' => 'acx_identity_members',
            'conflicts_table' => 'acx_sync_conflicts',
            'outbox_table' => 'acx_sync_outbox',
            'sync_state' => 'acx_sync_state',
            'sync_outbox' => 'acx_sync_outbox',
            'sync_conflicts' => 'acx_sync_conflicts',
            'topology' => 'acx_topology_commands',
            'conflicts' => 'acx_sync_conflicts',
            'persons' => 'acx_persons',
            'clusters' => 'acx_clusters',
            'batch_runs' => 'acx_batch_runs',
            'runs_table' => 'acx_batch_runs',
            'outbox' => 'acx_sync_outbox',
        ];
        foreach ($needles as $needle => $suffix) {
            if (stripos($expr, $needle) !== false) {
                return $suffix;
            }
        }

        if (
            stripos($expr, 'resolve_persons') !== false
            || preg_match('/\$persons_table\b/', $expr)
        ) {
            return 'acx_persons';
        }

        if (
            preg_match('/\$this->table(?:_name)?\b/', $expr)
            || preg_match('/^\$[a-z_]*table[a-z_]*$/i', $expr)
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

        return null;
    }

    private function displayTableName(string $tableSuffix): string
    {
        return str_starts_with($tableSuffix, 'acx_')
            ? substr($tableSuffix, 4)
            : $tableSuffix;
    }
}
