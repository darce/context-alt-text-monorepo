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
 *  - SQL column refs from alias-qualified references in repository sources
 *
 * This is the check that would have gone red when assigned_at was added to
 * ORDER BY without a matching CREATE TABLE column.
 *
 * @coversNothing
 */
class ProjectionQueryColumnParityTest extends TestCase
{
    /**
     * Every confidently-bound alias.column reference in sovereign repository SQL
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

        $scan = $this->scanRepositoryQualifiedColumnRefs();
        $bound = $scan['bound'];
        $skipped = $scan['skipped'];

        $this->assertNotEmpty(
            $bound,
            'extractor found no confidently-bound alias.column refs — parser or corpus is broken'
        );

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
            . 'Skipped (unbound/unresolved, not asserted): ' . $skipDiagnostic
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
     * Scan repository sources for alias-qualified column refs bound to tables
     * via FROM/JOIN/UPDATE/INTO %i &lt;alias&gt; + prepare_query args.
     *
     * @return array{
     *     bound: list<array{file:string,table:string,column:string,alias:string}>,
     *     skipped: list<string>
     * }
     */
    private function scanRepositoryQualifiedColumnRefs(): array
    {
        $dir = dirname(__DIR__, 2) . '/src/sovereign/repositories';
        $files = glob($dir . '/*.php');
        $this->assertIsArray($files);
        $this->assertNotEmpty($files, 'no sovereign repository source files found');

        $bound = [];
        $skipped = [];

        foreach ($files as $path) {
            $basename = basename($path);
            $source = (string) file_get_contents($path);
            foreach ($this->extractPrepareQueryUnits($source) as $unit) {
                $aliasMap = $this->bindAliasesToTables(
                    $unit['sql'],
                    $unit['args'],
                    $basename
                );

                if (! preg_match_all(
                    '/\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b/',
                    $unit['sql'],
                    $refs,
                    PREG_SET_ORDER
                )) {
                    continue;
                }

                foreach ($refs as $ref) {
                    $alias = $ref[1];
                    $column = $ref[2];

                    if (! array_key_exists($alias, $aliasMap)) {
                        $skipped[] = sprintf(
                            '%s: %s.%s (no FROM/JOIN/UPDATE/INTO %%i binding)',
                            $basename,
                            $alias,
                            $column
                        );
                        continue;
                    }

                    $table = $aliasMap[$alias];
                    if ($table === null) {
                        $skipped[] = sprintf(
                            '%s: %s.%s (unresolved table expression for alias)',
                            $basename,
                            $alias,
                            $column
                        );
                        continue;
                    }

                    $bound[] = [
                        'file' => $basename,
                        'table' => $table,
                        'column' => $column,
                        'alias' => $alias,
                    ];
                }
            }
        }

        return [
            'bound' => $bound,
            'skipped' => $skipped,
        ];
    }

    /**
     * @return list<array{sql:string,args:string[]}>
     */
    private function extractPrepareQueryUnits(string $source): array
    {
        $units = [];
        $offset = 0;
        $length = strlen($source);

        while (preg_match('/->prepare_query\s*\(/', $source, $match, PREG_OFFSET_CAPTURE, $offset)) {
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

            if (! preg_match(
                '/^\s*(["\'])((?:\\\\.|(?!\1).)*)\1\s*,\s*(.*)$/s',
                $callBody,
                $parts
            )) {
                continue;
            }

            $sql = stripcslashes($parts[2]);
            $rest = $parts[3];
            $args = [];

            // Leading table args for %i live in the first array of array_merge.
            if (preg_match('/^array_merge\s*\(\s*array\s*\((.*)\)\s*,/s', $rest, $arrayMatch)) {
                $args = $this->splitTopLevelArgs($arrayMatch[1]);
            } elseif (preg_match('/^array\s*\((.*)\)\s*$/s', $rest, $arrayMatch)) {
                $args = $this->splitTopLevelArgs($arrayMatch[1]);
            } else {
                continue;
            }

            $units[] = [
                'sql' => $sql,
                'args' => $args,
            ];
        }

        return $units;
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
     * Map SQL aliases to projection table suffixes via %i placeholder args.
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
        if (preg_match_all(
            '/\b(?:FROM|JOIN|UPDATE|INTO)\s+%i\s+([a-zA-Z_][a-zA-Z0-9_]*)\b/i',
            $sql,
            $aliasMatches,
            PREG_OFFSET_CAPTURE
        )) {
            foreach ($aliasMatches[1] as $aliasHit) {
                $alias = $aliasHit[0];
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
            'description_run_items' => 'acx_description_run_items',
            'description_runs' => 'acx_description_runs',
            'description_usage' => 'acx_description_usage',
            'identity_members' => 'acx_identity_members',
            'members_table' => 'acx_identity_members',
            'sync_state' => 'acx_sync_state',
            'sync_outbox' => 'acx_sync_outbox',
            'topology' => 'acx_topology_commands',
            'conflicts' => 'acx_sync_conflicts',
            'persons' => 'acx_persons',
            'clusters' => 'acx_clusters',
            'batch_runs' => 'acx_batch_runs',
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
