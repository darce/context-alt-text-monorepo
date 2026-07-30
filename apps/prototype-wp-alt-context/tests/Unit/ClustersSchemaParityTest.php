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
 * Write columns are scraped from two shapes (R23-BR-16):
 *  - raw SQL: `INSERT INTO … (cols) VALUES|SELECT` and `VALUES(col)` back-refs
 *  - array form: `$wpdb->insert|update|replace( $table, array( 'col' => … ) )`
 *    via `token_get_all`, fail-closed when keys are not string literals
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
     * parsed straight out of its INSERT/upsert statements and array-form
     * $wpdb->insert/update/replace data keys — must all exist in the parsed
     * DDL. Unlike testRepositoryColumnsExistInClustersDdl this does not trust
     * the hand-maintained allowlist; a renamed or fabricated write column in
     * the SQL or array form is caught even if REPOSITORY_COLUMNS was never
     * updated.
     */
    public function testSqlWriteColumnsExistInClustersDdl(): void
    {
        $scrape = $this->scrapeRepositoryLayerWriteColumns();

        $this->assertNotEmpty(
            $scrape['columns'],
            'parser found no INSERT/upsert write columns in the clusters repository SQL — parser or corpus is broken'
        );

        $this->assertSame(
            [],
            $this->columnsMissingFrom($scrape['columns'], $this->parseClustersDdlColumns()),
            'Clusters repository SQL writes columns absent from the clusters DDL'
        );
    }

    /**
     * False-failure / scrape-health pin: the unmutated repository layer stays
     * GREEN under the extended scrape, and the walker must resolve more than
     * one write call site (raw SQL + array form) or the GREEN means nothing.
     */
    public function testWriteColumnScrapeResolvesMultipleCallSitesWithoutFalseFailure(): void
    {
        $scrape = $this->scrapeRepositoryLayerWriteColumns();
        $ddlColumns = $this->parseClustersDdlColumns();

        $this->assertGreaterThan(
            1,
            $scrape['call_sites'],
            'extended scrape must resolve more than one write call site (raw SQL and/or array-form); '
                . 'a count of 0 or 1 means the walker is not seeing the corpus'
        );

        $this->assertNotEmpty($scrape['columns'], 'scrape returned no columns — walker or corpus is broken');

        // Success path: every resolved write column exists in the DDL.
        $this->assertSame(
            [],
            $this->columnsMissingFrom($scrape['columns'], $ddlColumns),
            'success-path pin: unmutated repository-layer writes must still report clean parity'
        );

        // No-op / already-in-DDL path: re-checking the same column set against
        // the same DDL still reports success (empty missing list), not failure.
        $this->assertSame(
            [],
            $this->columnsMissingFrom($scrape['columns'], $ddlColumns),
            'no-op pin: re-running parity on an already-matching set must still report success'
        );

        $this->assertGreaterThanOrEqual(
            1,
            $scrape['array_form_call_sites'],
            'array-form walker must resolve at least the $wpdb->insert in class-cluster-projection-writer.php'
        );

        $this->assertGreaterThanOrEqual(
            1,
            $scrape['raw_sql_call_sites'],
            'raw-SQL walker must still resolve at least one INSERT column list'
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
     * Array-form defect pin: a fabricated key on `$wpdb->insert( …, array(…) )`
     * must be visible to the scrape and flagged missing from the DDL.
     */
    public function testArrayFormWriteColumnGuardDetectsFabricatedColumn(): void
    {
        $php = <<<'PHP'
<?php
$wpdb->insert(
    $table,
    array(
        'cluster_uuid' => $id,
        'fabricated_array_column_xyz' => $value,
    )
);
PHP;

        $referenced = $this->parseSqlWriteColumns($php, 'array-form-fixture.php');

        $this->assertContains(
            'fabricated_array_column_xyz',
            $referenced,
            'parser must extract string-literal keys from array-form $wpdb->insert data'
        );
        $this->assertContains(
            'cluster_uuid',
            $referenced,
            'parser must extract every string-literal key from the data array'
        );
        $this->assertSame(
            ['fabricated_array_column_xyz'],
            $this->columnsMissingFrom($referenced, $this->parseClustersDdlColumns()),
            'live-parity guard must flag an array-form write column missing from the DDL'
        );
    }

    /**
     * Fail-closed pin: a non-literal data array must not be skipped silently.
     *
     * @throws \PHPUnit\Framework\AssertionFailedError When fail-closed does not fire.
     */
    public function testArrayFormWriteColumnGuardFailsClosedOnNonLiteralKeys(): void
    {
        $php = <<<'PHP'
<?php
$wpdb->insert( $table, $dynamic_row );
PHP;

        try {
            $this->parseSqlWriteColumns($php, 'non-literal-fixture.php');
            $this->fail('expected fail-closed on non-literal $wpdb->insert data array');
        } catch (\PHPUnit\Framework\AssertionFailedError $e) {
            if (str_contains($e->getMessage(), 'expected fail-closed')) {
                throw $e;
            }
            $this->assertStringContainsString(
                'non-literal-fixture.php',
                $e->getMessage(),
                'fail-closed message must name the source file'
            );
            $this->assertMatchesRegularExpression(
                '/non-literal-fixture\.php:\d+/',
                $e->getMessage(),
                'fail-closed message must include file:line'
            );
        }
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
     * Walk every clusters repository-layer file and union write columns from
     * raw SQL and array-form $wpdb calls. Fail-closed messages carry file:line.
     *
     * @return array{
     *     columns: string[],
     *     call_sites: int,
     *     raw_sql_call_sites: int,
     *     array_form_call_sites: int
     * }
     */
    private function scrapeRepositoryLayerWriteColumns(): array
    {
        $columns = [];
        $rawSites = 0;
        $arraySites = 0;

        foreach ($this->repositoryLayerFiles() as $file) {
            $source = (string) file_get_contents($file);
            $parsed = $this->parseSqlWriteColumnsDetailed($source, $file);
            foreach ($parsed['columns'] as $column) {
                $columns[$column] = true;
            }
            $rawSites += $parsed['raw_sql_call_sites'];
            $arraySites += $parsed['array_form_call_sites'];
        }

        return [
            'columns' => array_keys($columns),
            'call_sites' => $rawSites + $arraySites,
            'raw_sql_call_sites' => $rawSites,
            'array_form_call_sites' => $arraySites,
        ];
    }

    /**
     * Parse the column identifiers the repository SQL writes — INSERT column
     * lists, `VALUES(col)` upsert back-references, and string-literal keys of
     * array-form `$wpdb->insert|update|replace` data arrays (via token_get_all).
     * Call sites whose data array cannot be resolved to string literals fail
     * closed with the source label and line.
     *
     * @return string[]
     */
    private function parseSqlWriteColumns(string $source, string $sourceLabel = 'snippet'): array
    {
        return $this->parseSqlWriteColumnsDetailed($source, $sourceLabel)['columns'];
    }

    /**
     * @return array{
     *     columns: string[],
     *     raw_sql_call_sites: int,
     *     array_form_call_sites: int
     * }
     */
    private function parseSqlWriteColumnsDetailed(string $source, string $sourceLabel = 'snippet'): array
    {
        $columns = [];
        $rawSites = 0;

        // INSERT INTO <table> (col, col, ...) VALUES|SELECT — the parenthesised
        // list before the VALUES or INSERT...SELECT row source is the write
        // column list.
        if (preg_match_all('/INSERT INTO\s+\S+\s*\(([^)]*)\)\s*(?:VALUES|SELECT)\b/i', $source, $insertMatches)) {
            foreach ($insertMatches[1] as $columnList) {
                ++$rawSites;
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

        $arrayParsed = $this->parseArrayFormWpdbWriteColumns($source, $sourceLabel);
        foreach ($arrayParsed['columns'] as $column) {
            $columns[$column] = true;
        }

        return [
            'columns' => array_keys($columns),
            'raw_sql_call_sites' => $rawSites,
            'array_form_call_sites' => $arrayParsed['call_sites'],
        ];
    }

    /**
     * Collect string-literal keys of every `$wpdb->insert|update|replace`
     * data array in $source. Uses PHP's own lexer so comments, strings, and
     * nested braces cannot hide or truncate a call site. Unresolvable data
     * arrays fail closed with file:line rather than being skipped [rg-005].
     *
     * @return array{columns: string[], call_sites: int}
     */
    private function parseArrayFormWpdbWriteColumns(string $source, string $sourceLabel): array
    {
        $tokens = token_get_all($source);
        $count = count($tokens);
        $columns = [];
        $callSites = 0;
        $methods = ['insert' => true, 'update' => true, 'replace' => true];

        for ($i = 0; $i < $count; $i++) {
            $token = $tokens[$i];
            if (! is_array($token) || T_VARIABLE !== $token[0] || '$wpdb' !== $token[1]) {
                continue;
            }

            $line = $token[2];
            $j = $this->skipInsignificantTokens($tokens, $i + 1);
            if ($j >= $count || ! $this->isObjectOperatorToken($tokens[$j])) {
                continue;
            }

            $j = $this->skipInsignificantTokens($tokens, $j + 1);
            if ($j >= $count || ! is_array($tokens[$j]) || T_STRING !== $tokens[$j][0]) {
                continue;
            }
            $method = $tokens[$j][1];
            if (! isset($methods[$method])) {
                continue;
            }

            $j = $this->skipInsignificantTokens($tokens, $j + 1);
            if ($j >= $count || '(' !== $tokens[$j]) {
                continue;
            }

            $args = $this->splitCallArguments($tokens, $j);
            if (null === $args || count($args) < 2) {
                self::fail(
                    sprintf(
                        'Clusters write-column scrape cannot resolve $wpdb->%s() argument list at %s:%d — '
                            . 'array-form writes must pass a literal data array so schema parity can see the keys',
                        $method,
                        $sourceLabel,
                        $line
                    )
                );
            }

            $dataKeys = $this->extractLiteralArrayKeys($args[1], $sourceLabel, $line, $method);
            foreach ($dataKeys as $key) {
                $columns[$key] = true;
            }
            ++$callSites;
        }

        return [
            'columns' => array_keys($columns),
            'call_sites' => $callSites,
        ];
    }

    /**
     * Split a call's argument token slices. $openIndex points at '('.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     * @return list<list<string|array{0:int,1:string,2:int}>>|null
     */
    private function splitCallArguments(array $tokens, int $openIndex): ?array
    {
        $count = count($tokens);
        $depthParen = 0;
        $depthBracket = 0;
        $depthBrace = 0;
        $args = [];
        $current = [];
        $started = false;

        for ($i = $openIndex; $i < $count; $i++) {
            $t = $tokens[$i];

            if ('(' === $t) {
                ++$depthParen;
                if (1 === $depthParen) {
                    $started = true;
                    continue;
                }
                $current[] = $t;
                continue;
            }

            if (')' === $t) {
                --$depthParen;
                if (0 === $depthParen) {
                    if ($current !== [] || $args !== []) {
                        $args[] = $current;
                    }
                    return $args;
                }
                $current[] = $t;
                continue;
            }

            if (! $started) {
                continue;
            }

            if ('[' === $t) {
                ++$depthBracket;
                $current[] = $t;
                continue;
            }
            if (']' === $t) {
                --$depthBracket;
                $current[] = $t;
                continue;
            }
            if ('{' === $t || (is_array($t) && (T_CURLY_OPEN === $t[0] || T_DOLLAR_OPEN_CURLY_BRACES === $t[0]))) {
                ++$depthBrace;
                $current[] = $t;
                continue;
            }
            if ('}' === $t) {
                --$depthBrace;
                $current[] = $t;
                continue;
            }

            if (',' === $t && 1 === $depthParen && 0 === $depthBracket && 0 === $depthBrace) {
                $args[] = $current;
                $current = [];
                continue;
            }

            $current[] = $t;
        }

        return null;
    }

    /**
     * Extract top-level string-literal keys from an `array(…)` or `[…]` token
     * slice. Any non-literal key shape fails closed.
     *
     * @param list<string|array{0:int,1:string,2:int}> $argTokens
     * @return string[]
     */
    private function extractLiteralArrayKeys(array $argTokens, string $sourceLabel, int $line, string $method): array
    {
        $count = count($argTokens);
        $i = $this->skipInsignificantTokens($argTokens, 0);
        if ($i >= $count) {
            self::fail($this->unresolvableArrayMessage($method, $sourceLabel, $line, 'empty data argument'));
        }

        $open = $argTokens[$i];
        $close = null;
        if (is_array($open) && T_ARRAY === $open[0]) {
            $i = $this->skipInsignificantTokens($argTokens, $i + 1);
            if ($i >= $count || '(' !== $argTokens[$i]) {
                self::fail($this->unresolvableArrayMessage($method, $sourceLabel, $line, 'array keyword without ('));
            }
            $close = ')';
        } elseif ('[' === $open) {
            $close = ']';
        } else {
            self::fail(
                $this->unresolvableArrayMessage(
                    $method,
                    $sourceLabel,
                    $line,
                    'data argument is not a literal array(…) or […]'
                )
            );
        }

        $bodyStart = $i + 1;
        $depthParen = 0;
        $depthBracket = 0;
        $depthBrace = 0;
        if (')' === $close) {
            $depthParen = 1;
        } else {
            $depthBracket = 1;
        }

        $bodyEnd = null;
        for ($p = $bodyStart; $p < $count; $p++) {
            $t = $argTokens[$p];
            if ('(' === $t) {
                ++$depthParen;
            } elseif (')' === $t) {
                --$depthParen;
                if (')' === $close && 0 === $depthParen && 0 === $depthBracket && 0 === $depthBrace) {
                    $bodyEnd = $p;
                    break;
                }
            } elseif ('[' === $t) {
                ++$depthBracket;
            } elseif (']' === $t) {
                --$depthBracket;
                if (']' === $close && 0 === $depthBracket && 0 === $depthParen && 0 === $depthBrace) {
                    $bodyEnd = $p;
                    break;
                }
            } elseif ('{' === $t || (is_array($t) && (T_CURLY_OPEN === $t[0] || T_DOLLAR_OPEN_CURLY_BRACES === $t[0]))) {
                ++$depthBrace;
            } elseif ('}' === $t) {
                --$depthBrace;
            }
        }

        if (null === $bodyEnd) {
            self::fail($this->unresolvableArrayMessage($method, $sourceLabel, $line, 'unclosed data array'));
        }

        $keys = [];
        $k = $bodyStart;
        while ($k < $bodyEnd) {
            $k = $this->skipInsignificantTokens($argTokens, $k);
            if ($k >= $bodyEnd) {
                break;
            }

            // Trailing comma or separator.
            if (',' === $argTokens[$k]) {
                ++$k;
                continue;
            }

            // Spread / unpack — not a resolvable literal key set.
            if (is_array($argTokens[$k]) && T_ELLIPSIS === $argTokens[$k][0]) {
                self::fail(
                    $this->unresolvableArrayMessage(
                        $method,
                        $sourceLabel,
                        $line,
                        'data array uses ...spread'
                    )
                );
            }

            // Key must be a single string literal followed by =>.
            if (
                ! is_array($argTokens[$k])
                || T_CONSTANT_ENCAPSED_STRING !== $argTokens[$k][0]
            ) {
                self::fail(
                    $this->unresolvableArrayMessage(
                        $method,
                        $sourceLabel,
                        $line,
                        'data array key is not a string literal'
                    )
                );
            }

            $keyToken = $argTokens[$k][1];
            $k = $this->skipInsignificantTokens($argTokens, $k + 1);
            if ($k >= $bodyEnd || ! is_array($argTokens[$k]) || T_DOUBLE_ARROW !== $argTokens[$k][0]) {
                self::fail(
                    $this->unresolvableArrayMessage(
                        $method,
                        $sourceLabel,
                        $line,
                        'data array entry is missing => after key'
                    )
                );
            }

            $decoded = $this->decodeStringLiteralToken($keyToken);
            if (! is_string($decoded) || ! preg_match('/^[a-z_][a-z0-9_]*$/', $decoded)) {
                self::fail(
                    $this->unresolvableArrayMessage(
                        $method,
                        $sourceLabel,
                        $line,
                        'data array key is not a plain column identifier'
                    )
                );
            }
            $keys[] = $decoded;

            // Skip the value (balanced) until top-level comma or body end.
            $k = $this->skipInsignificantTokens($argTokens, $k + 1);
            $k = $this->skipArrayValue($argTokens, $k, $bodyEnd);
        }

        return $keys;
    }

    /**
     * Advance past one array value, stopping at the next top-level comma or body end.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function skipArrayValue(array $tokens, int $from, int $bodyEnd): int
    {
        $depthParen = 0;
        $depthBracket = 0;
        $depthBrace = 0;

        for ($i = $from; $i < $bodyEnd; $i++) {
            $t = $tokens[$i];
            if ('(' === $t) {
                ++$depthParen;
                continue;
            }
            if (')' === $t) {
                --$depthParen;
                continue;
            }
            if ('[' === $t) {
                ++$depthBracket;
                continue;
            }
            if (']' === $t) {
                --$depthBracket;
                continue;
            }
            if ('{' === $t || (is_array($t) && (T_CURLY_OPEN === $t[0] || T_DOLLAR_OPEN_CURLY_BRACES === $t[0]))) {
                ++$depthBrace;
                continue;
            }
            if ('}' === $t) {
                --$depthBrace;
                continue;
            }
            if (',' === $t && 0 === $depthParen && 0 === $depthBracket && 0 === $depthBrace) {
                return $i;
            }
        }

        return $bodyEnd;
    }

    private function unresolvableArrayMessage(string $method, string $sourceLabel, int $line, string $reason): string
    {
        return sprintf(
            'Clusters write-column scrape cannot resolve $wpdb->%s() data array at %s:%d (%s) — '
                . 'array-form writes must use a literal array of string-literal keys so schema parity can see the columns',
            $method,
            $sourceLabel,
            $line,
            $reason
        );
    }

    /**
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function skipInsignificantTokens(array $tokens, int $from): int
    {
        $count = count($tokens);
        while ($from < $count) {
            $t = $tokens[$from];
            if (is_array($t) && (T_WHITESPACE === $t[0] || T_COMMENT === $t[0] || T_DOC_COMMENT === $t[0])) {
                ++$from;
                continue;
            }
            break;
        }

        return $from;
    }

    /**
     * @param string|array{0:int,1:string,2:int} $token
     */
    private function isObjectOperatorToken(string|array $token): bool
    {
        if (is_array($token)) {
            return T_OBJECT_OPERATOR === $token[0] || T_NULLSAFE_OBJECT_OPERATOR === $token[0];
        }

        return false;
    }

    private function decodeStringLiteralToken(string $tokenText): ?string
    {
        if (strlen($tokenText) < 2) {
            return null;
        }

        $q = $tokenText[0];
        $end = $tokenText[strlen($tokenText) - 1];
        if (("'" !== $q && '"' !== $q) || $end !== $q) {
            return null;
        }

        $inner = substr($tokenText, 1, -1);
        if ('"' === $q) {
            return stripcslashes($inner);
        }

        return str_replace(['\\\\', '\\\''], ['\\', "'"], $inner);
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
     * @return list<string>
     */
    private function repositoryLayerFiles(): array
    {
        $dir = dirname(__DIR__, 2) . '/src/sovereign/repositories';
        $files = glob($dir . '/class-cluster*.php');
        if (! is_array($files)) {
            $files = [];
        }
        $this->assertNotEmpty($files, 'no clusters repository-layer source files found');
        sort($files);

        return $files;
    }

    /**
     * Concatenated source of the whole clusters repository layer (facade +
     * extracted collaborators), so column references survive the REFA-2 split.
     */
    private function repositoryLayerSource(): string
    {
        $source = '';
        foreach ($this->repositoryLayerFiles() as $file) {
            $source .= (string) file_get_contents($file);
        }

        return $source;
    }
}
