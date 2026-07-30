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
 *  - variable data args (R23-BR-29): when the data argument is a single `$var`,
 *    resolve `$var = array(…)` / `$var = […]` and later `$var['literal'] = …`
 *    additions inside the enclosing function body; fail closed on dynamic builds
 *
 * Corpus is decided by *which tables are written*, not by filename (R23-BR-29):
 * every runtime file that issues a clusters-table write is walked, including
 * writers outside `class-cluster*.php` (life-cycle import, label service, API).
 * Array-form scrapes skip non-clusters `$wpdb` writes in those multi-table files;
 * unresolvable clusters-table data arrays still fail closed [rg-005].
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
     * R23-BR-29 corpus pin: non-repository clusters writers are in the walk, and
     * the life-cycle-manager array-form `$wpdb->update( $table_clusters, … )` is
     * visible without going through other files' fail-closed sites.
     */
    public function testWriteCorpusIncludesNonRepositoryClustersWriters(): void
    {
        $root = dirname(__DIR__, 2);
        $files = $this->repositoryLayerFiles();
        $bases = array_map(
            static fn (string $path): string => basename(str_replace('\\', '/', $path)),
            $files
        );

        $this->assertContains('class-life-cycle-manager.php', $bases);
        $this->assertContains('class-cluster-label-service.php', $bases);
        $this->assertContains('class-api.php', $bases);
        $this->assertGreaterThanOrEqual(
            9,
            count($files),
            'widened corpus must include class-cluster* (6) plus at least three non-repository writers'
        );

        $lifeCycle = $root . '/src/support/class-life-cycle-manager.php';
        $columns = $this->parseSqlWriteColumns((string) file_get_contents($lifeCycle), $lifeCycle);
        $this->assertContains(
            'person_id',
            $columns,
            'life-cycle-manager $wpdb->update( $table_clusters, array( person_id => … ) ) must be visible to the array-form scrape'
        );
        // Per-file parity on the life-cycle writer alone (isolates the corpus
        // widen from other multi-table files' fail-closed sites). A fabricated
        // key at that call site must redden here naming the column [TEST-15].
        $this->assertSame(
            [],
            $this->columnsMissingFrom($columns, $this->parseClustersDdlColumns()),
            'life-cycle-manager clusters write columns must exist in the clusters DDL'
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
    $table_clusters,
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
$wpdb->insert( $table_clusters, $dynamic_row );
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
     * R23-BR-29: a single-variable data arg bound to a literal array (plus later
     * literal-key additions) in the enclosing function must resolve to the union
     * of those string-literal keys — the class-api.php:483 shape.
     */
    public function testArrayFormWriteColumnResolvesVariableLiteralArrayAndAdditions(): void
    {
        $php = <<<'PHP'
<?php
function assign_cluster_person( $person_id, $resolved_person_name, $cluster_id ) {
    global $wpdb;
    $table_clusters = $wpdb->prefix . 'acx_clusters';
    $now = current_time( 'mysql' );

    $update_data = array(
        'person_id'         => $person_id,
        'curation_state'    => 'confirmed',
        'is_user_confirmed' => 1,
        'updated_at'        => $now,
    );

    if ( null === $person_id ) {
        // format path only — no data-key change
    } elseif ( is_string( $resolved_person_name ) && '' !== trim( $resolved_person_name ) ) {
        $update_data['label'] = trim( $resolved_person_name );
    }

    $wpdb->update(
        $table_clusters,
        $update_data,
        array( 'cluster_uuid' => $cluster_id )
    );
}
PHP;

        $referenced = $this->parseSqlWriteColumns($php, 'variable-literal-fixture.php');
        sort($referenced);

        $this->assertSame(
            [
                'curation_state',
                'is_user_confirmed',
                'label',
                'person_id',
                'updated_at',
            ],
            $referenced,
            'variable data arg must resolve initial literal keys plus conditional $var[\'literal\'] additions'
        );
    }

    /**
     * R23-BR-29 pin 3: a variable data arg built dynamically must still fail closed
     * (fixture only — not a production edit).
     *
     * @throws \PHPUnit\Framework\AssertionFailedError When fail-closed does not fire.
     */
    public function testArrayFormWriteColumnFailsClosedOnDynamicallyBuiltVariable(): void
    {
        $php = <<<'PHP'
<?php
function write_dynamic_cluster_row( $table_clusters, $dynamic_key, $extra ) {
    global $wpdb;
    $update_data = array( 'person_id' => 1 );
    $update_data = array_merge( $update_data, $extra );
    $update_data[ $dynamic_key ] = 1;
    $wpdb->update( $table_clusters, $update_data, array( 'cluster_uuid' => 'x' ) );
}
PHP;

        try {
            $this->parseSqlWriteColumns($php, 'dynamic-variable-fixture.php');
            $this->fail('expected fail-closed on dynamically built $wpdb->update data variable');
        } catch (\PHPUnit\Framework\AssertionFailedError $e) {
            if (str_contains($e->getMessage(), 'expected fail-closed')) {
                throw $e;
            }
            $this->assertMatchesRegularExpression(
                '/dynamic-variable-fixture\.php:\d+/',
                $e->getMessage(),
                'fail-closed message must include file:line'
            );
            $this->assertTrue(
                str_contains($e->getMessage(), 'array_merge')
                    || str_contains($e->getMessage(), 'non-literal')
                    || str_contains($e->getMessage(), 'assigned more than once')
                    || str_contains($e->getMessage(), 'assigned from'),
                'fail-closed message must name the dynamic-build reason: ' . $e->getMessage()
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
     * Collect string-literal keys of every clusters-table `$wpdb->insert|update|replace`
     * data array in $source. Uses PHP's own lexer so comments, strings, and
     * nested braces cannot hide or truncate a call site. Non-clusters writes in
     * multi-table files are skipped. Unresolvable clusters-table data arrays
     * fail closed with file:line rather than being skipped [rg-005].
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
        $fileIsClusterRepository = $this->sourceLabelIsClusterRepositoryFile($sourceLabel);

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
                // Only fail closed when the call looks like a clusters-table write;
                // multi-table files contain unrelated $wpdb calls we do not own.
                if ($fileIsClusterRepository) {
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
                continue;
            }

            if (! $this->argumentTargetsClustersTable($args[0], $fileIsClusterRepository)) {
                continue;
            }

            $dataKeys = $this->extractWpdbDataArgKeys(
                $tokens,
                $i,
                $args[1],
                $sourceLabel,
                $line,
                $method
            );
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
     * Resolve write-column keys from a $wpdb insert/update/replace data argument.
     * Accepts a literal array(…)/[…] or a single variable bound to a literal
     * array (plus later literal-key additions) inside the enclosing function.
     *
     * @param list<string|array{0:int,1:string,2:int}> $fileTokens
     * @param list<string|array{0:int,1:string,2:int}> $dataArgTokens
     * @return string[]
     */
    private function extractWpdbDataArgKeys(
        array $fileTokens,
        int $callTokenIndex,
        array $dataArgTokens,
        string $sourceLabel,
        int $line,
        string $method
    ): array {
        $varName = $this->singleVariableName($dataArgTokens);
        if (null !== $varName) {
            return $this->resolveVariableDataArrayKeys(
                $fileTokens,
                $callTokenIndex,
                $varName,
                $sourceLabel,
                $line,
                $method
            );
        }

        return $this->extractLiteralArrayKeys($dataArgTokens, $sourceLabel, $line, $method);
    }

    /**
     * @param list<string|array{0:int,1:string,2:int}> $argTokens
     */
    private function singleVariableName(array $argTokens): ?string
    {
        $i = $this->skipInsignificantTokens($argTokens, 0);
        if ($i >= count($argTokens) || ! is_array($argTokens[$i]) || T_VARIABLE !== $argTokens[$i][0]) {
            return null;
        }
        $name = $argTokens[$i][1];
        $j = $this->skipInsignificantTokens($argTokens, $i + 1);
        if ($j < count($argTokens)) {
            // Not a bare variable (subscript, property, concatenation, etc.).
            return null;
        }

        return $name;
    }

    /**
     * Resolve `$var = array(…)` / `$var = […]` plus later `$var['key'] = …`
     * additions inside the enclosing function body before the call site.
     * Fail closed on dynamic construction, non-literal subscripts, multiple
     * reassignments, or assignments that cannot be ordered [rg-005].
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     * @return string[]
     */
    private function resolveVariableDataArrayKeys(
        array $tokens,
        int $callTokenIndex,
        string $varName,
        string $sourceLabel,
        int $line,
        string $method
    ): array {
        $scope = $this->findEnclosingFunctionBody($tokens, $callTokenIndex);
        if (null === $scope) {
            self::fail(
                $this->unresolvableArrayMessage(
                    $method,
                    $sourceLabel,
                    $line,
                    "data argument \${$varName} has no enclosing function body to resolve against"
                )
            );
        }

        $keys = [];
        $literalAssignCount = 0;
        $literalAssignIndex = null;
        $count = count($tokens);
        $i = $scope['start'];

        while ($i < $callTokenIndex) {
            $t = $tokens[$i];
            if (! is_array($t) || T_VARIABLE !== $t[0] || $t[1] !== $varName) {
                ++$i;
                continue;
            }

            $afterVar = $this->skipInsignificantTokens($tokens, $i + 1);

            // `$var['literal'] = …` key addition.
            if ($afterVar < $count && '[' === $tokens[$afterVar]) {
                $keyStart = $this->skipInsignificantTokens($tokens, $afterVar + 1);
                if (
                    $keyStart >= $count
                    || ! is_array($tokens[$keyStart])
                    || T_CONSTANT_ENCAPSED_STRING !== $tokens[$keyStart][0]
                ) {
                    self::fail(
                        $this->unresolvableArrayMessage(
                            $method,
                            $sourceLabel,
                            $line,
                            "data variable {$varName} uses a non-literal array subscript"
                        )
                    );
                }
                $closeBracket = $this->skipInsignificantTokens($tokens, $keyStart + 1);
                if ($closeBracket >= $count || ']' !== $tokens[$closeBracket]) {
                    self::fail(
                        $this->unresolvableArrayMessage(
                            $method,
                            $sourceLabel,
                            $line,
                            "data variable {$varName} uses a non-literal array subscript"
                        )
                    );
                }
                $afterBracket = $this->skipInsignificantTokens($tokens, $closeBracket + 1);
                if ($afterBracket >= $count || '=' !== $tokens[$afterBracket]) {
                    // `$var['k']` read / comparison — ignore.
                    ++$i;
                    continue;
                }
                // Reject `==` / `===` / `=>` (T_IS_EQUAL etc. are array tokens; `=` is string).
                $decoded = $this->decodeStringLiteralToken($tokens[$keyStart][1]);
                if (! is_string($decoded) || ! preg_match('/^[a-z_][a-z0-9_]*$/', $decoded)) {
                    self::fail(
                        $this->unresolvableArrayMessage(
                            $method,
                            $sourceLabel,
                            $line,
                            "data variable {$varName} addition key is not a plain column identifier"
                        )
                    );
                }
                $keys[$decoded] = true;
                $i = $afterBracket + 1;
                continue;
            }

            // Assignment: `$var = …` or `$var += …` / `.=` etc.
            if ($afterVar >= $count) {
                ++$i;
                continue;
            }

            $op = $tokens[$afterVar];
            if (is_array($op) && T_PLUS_EQUAL === $op[0]) {
                self::fail(
                    $this->unresolvableArrayMessage(
                        $method,
                        $sourceLabel,
                        $line,
                        "data variable {$varName} is modified with += (not a resolvable literal array)"
                    )
                );
            }
            if (is_array($op) && (T_CONCAT_EQUAL === $op[0] || T_MUL_EQUAL === $op[0]
                || T_DIV_EQUAL === $op[0] || T_MOD_EQUAL === $op[0]
                || T_AND_EQUAL === $op[0] || T_OR_EQUAL === $op[0]
                || T_XOR_EQUAL === $op[0] || T_SL_EQUAL === $op[0]
                || T_SR_EQUAL === $op[0] || T_COALESCE_EQUAL === $op[0]
            )) {
                self::fail(
                    $this->unresolvableArrayMessage(
                        $method,
                        $sourceLabel,
                        $line,
                        "data variable {$varName} is modified with a compound assignment"
                    )
                );
            }
            if ('=' !== $op) {
                ++$i;
                continue;
            }

            // True assignment `$var = RHS`.
            $rhsStart = $this->skipInsignificantTokens($tokens, $afterVar + 1);
            if ($rhsStart >= $count) {
                self::fail(
                    $this->unresolvableArrayMessage(
                        $method,
                        $sourceLabel,
                        $line,
                        "data variable {$varName} has an empty assignment"
                    )
                );
            }

            $rhs = $tokens[$rhsStart];
            $isLiteralArray = (is_array($rhs) && T_ARRAY === $rhs[0]) || '[' === $rhs;
            if (! $isLiteralArray) {
                $reason = "data variable {$varName} is assigned from a non-literal value";
                if (is_array($rhs) && T_STRING === $rhs[0] && in_array($rhs[1], ['array_merge', 'array_replace', 'array_replace_recursive', 'array_combine', 'compact'], true)) {
                    $reason = "data variable {$varName} is assigned from {$rhs[1]}()";
                } elseif (is_array($rhs) && T_VARIABLE === $rhs[0]) {
                    $reason = "data variable {$varName} is assigned from another variable";
                } elseif (is_array($rhs) && T_ELLIPSIS === $rhs[0]) {
                    $reason = "data variable {$varName} is assigned using spread";
                }
                self::fail(
                    $this->unresolvableArrayMessage($method, $sourceLabel, $line, $reason)
                );
            }

            // Assignment inside a loop/conditional that does not also enclose the
            // call site cannot be ordered — fail closed.
            if ($this->tokenIsInsideUnorderedControlStructure($tokens, $scope['start'], $i, $callTokenIndex)) {
                self::fail(
                    $this->unresolvableArrayMessage(
                        $method,
                        $sourceLabel,
                        $line,
                        "data variable {$varName} is assigned inside a loop or conditional that does not enclose the call site"
                    )
                );
            }

            ++$literalAssignCount;
            if ($literalAssignCount > 1) {
                self::fail(
                    $this->unresolvableArrayMessage(
                        $method,
                        $sourceLabel,
                        $line,
                        "data variable {$varName} is assigned more than once to a literal array"
                    )
                );
            }
            $literalAssignIndex = $i;

            // Build a token slice for the RHS array and extract keys.
            $arrayTokens = $this->sliceBalancedArrayTokens($tokens, $rhsStart);
            $assignedKeys = $this->extractLiteralArrayKeys($arrayTokens, $sourceLabel, $line, $method);
            foreach ($assignedKeys as $key) {
                $keys[$key] = true;
            }
            $i = $rhsStart + count($arrayTokens);
        }

        if (0 === $literalAssignCount || null === $literalAssignIndex) {
            self::fail(
                $this->unresolvableArrayMessage(
                    $method,
                    $sourceLabel,
                    $line,
                    "data argument is variable {$varName} with no resolvable literal-array assignment in the enclosing function"
                )
            );
        }

        return array_keys($keys);
    }

    /**
     * Innermost function/method body containing $pos, or null if none.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     * @return array{start:int,end:int}|null body open index (after '{') and close index (at '}')
     */
    private function findEnclosingFunctionBody(array $tokens, int $pos): ?array
    {
        $count = count($tokens);
        $candidates = [];

        for ($i = 0; $i < $count; $i++) {
            $t = $tokens[$i];
            if (! is_array($t) || T_FUNCTION !== $t[0]) {
                continue;
            }

            // Skip past optional name, parameter list, use-clause, and return type
            // until the body '{' (or ';' for abstract methods).
            $j = $this->skipInsignificantTokens($tokens, $i + 1);
            $sawParamList = false;
            while ($j < $count) {
                $cur = $tokens[$j];
                if ('{' === $cur) {
                    break;
                }
                if (';' === $cur) {
                    // Abstract / interface method — no body.
                    break;
                }
                if ('(' === $cur && ! $sawParamList) {
                    $sawParamList = true;
                    $depth = 0;
                    for (; $j < $count; $j++) {
                        if ('(' === $tokens[$j]) {
                            ++$depth;
                        } elseif (')' === $tokens[$j]) {
                            --$depth;
                            if (0 === $depth) {
                                ++$j;
                                break;
                            }
                        }
                    }
                    $j = $this->skipInsignificantTokens($tokens, $j);
                    // Closures: `function (…) use (…) {`.
                    if (
                        $j < $count
                        && is_array($tokens[$j])
                        && T_USE === $tokens[$j][0]
                    ) {
                        $j = $this->skipInsignificantTokens($tokens, $j + 1);
                        if ($j < $count && '(' === $tokens[$j]) {
                            $depth = 0;
                            for (; $j < $count; $j++) {
                                if ('(' === $tokens[$j]) {
                                    ++$depth;
                                } elseif (')' === $tokens[$j]) {
                                    --$depth;
                                    if (0 === $depth) {
                                        ++$j;
                                        break;
                                    }
                                }
                            }
                            $j = $this->skipInsignificantTokens($tokens, $j);
                        }
                    }
                    continue;
                }
                // Anything else (name, return type tokens, `&`, `?`, `|`, …).
                ++$j;
                $j = $this->skipInsignificantTokens($tokens, $j);
            }
            // Abstract / interface methods end with `;` — no body.
            if ($j >= $count || '{' !== $tokens[$j]) {
                continue;
            }

            $bodyStart = $j + 1;
            $bodyEnd = $this->findMatchingBrace($tokens, $j);
            if (null === $bodyEnd) {
                continue;
            }
            if ($bodyStart <= $pos && $pos < $bodyEnd) {
                $candidates[] = ['start' => $bodyStart, 'end' => $bodyEnd];
            }
        }

        if ($candidates === []) {
            return null;
        }

        // Innermost: smallest body range.
        usort(
            $candidates,
            static fn (array $a, array $b): int => ($a['end'] - $a['start']) <=> ($b['end'] - $b['start'])
        );

        return $candidates[0];
    }

    /**
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function findMatchingBrace(array $tokens, int $openBraceIndex): ?int
    {
        $count = count($tokens);
        $depth = 0;
        for ($i = $openBraceIndex; $i < $count; $i++) {
            $t = $tokens[$i];
            if ('{' === $t || (is_array($t) && (T_CURLY_OPEN === $t[0] || T_DOLLAR_OPEN_CURLY_BRACES === $t[0]))) {
                ++$depth;
                continue;
            }
            if ('}' === $t) {
                --$depth;
                if (0 === $depth) {
                    return $i;
                }
            }
        }

        return null;
    }

    /**
     * True when $assignIndex sits inside a control-structure block that does not
     * also contain $callIndex (assignment may not dominate the call).
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function tokenIsInsideUnorderedControlStructure(
        array $tokens,
        int $scopeStart,
        int $assignIndex,
        int $callIndex
    ): bool {
        $controlKeywords = [
            T_IF => true,
            T_ELSEIF => true,
            T_ELSE => true,
            T_FOR => true,
            T_FOREACH => true,
            T_WHILE => true,
            T_DO => true,
            T_SWITCH => true,
            T_TRY => true,
            T_CATCH => true,
            T_FINALLY => true,
        ];

        $count = count($tokens);
        for ($i = $scopeStart; $i < $assignIndex; $i++) {
            $t = $tokens[$i];
            if (! is_array($t) || ! isset($controlKeywords[$t[0]])) {
                continue;
            }

            // Find the block '{' that belongs to this control keyword.
            $j = $this->skipInsignificantTokens($tokens, $i + 1);
            // else / finally / do may go straight to '{'; if/for/while have '(...)'.
            if ($j < $count && '(' === $tokens[$j]) {
                $depth = 0;
                for (; $j < $count; $j++) {
                    if ('(' === $tokens[$j]) {
                        ++$depth;
                    } elseif (')' === $tokens[$j]) {
                        --$depth;
                        if (0 === $depth) {
                            ++$j;
                            break;
                        }
                    }
                }
                $j = $this->skipInsignificantTokens($tokens, $j);
            }
            // while after do: `while (...);` — no block for the while.
            if ($j >= $count || '{' !== $tokens[$j]) {
                continue;
            }
            $blockEnd = $this->findMatchingBrace($tokens, $j);
            if (null === $blockEnd) {
                continue;
            }
            $blockStart = $j + 1;
            $assignInside = $assignIndex >= $blockStart && $assignIndex < $blockEnd;
            $callInside = $callIndex >= $blockStart && $callIndex < $blockEnd;
            if ($assignInside && ! $callInside) {
                return true;
            }
        }

        return false;
    }

    /**
     * Slice tokens for a balanced `array(…)` or `[…]` starting at $start.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     * @return list<string|array{0:int,1:string,2:int}>
     */
    private function sliceBalancedArrayTokens(array $tokens, int $start): array
    {
        $count = count($tokens);
        $open = $tokens[$start];
        $depthParen = 0;
        $depthBracket = 0;
        $depthBrace = 0;
        $i = $start;

        if (is_array($open) && T_ARRAY === $open[0]) {
            // Include `array` and the following balanced `(…)`.
            $i = $this->skipInsignificantTokens($tokens, $start + 1);
            if ($i >= $count || '(' !== $tokens[$i]) {
                return array_slice($tokens, $start, 1);
            }
            $depthParen = 1;
            ++$i;
            for (; $i < $count; $i++) {
                $t = $tokens[$i];
                if ('(' === $t) {
                    ++$depthParen;
                } elseif (')' === $t) {
                    --$depthParen;
                    if (0 === $depthParen && 0 === $depthBracket && 0 === $depthBrace) {
                        return array_slice($tokens, $start, $i - $start + 1);
                    }
                } elseif ('[' === $t) {
                    ++$depthBracket;
                } elseif (']' === $t) {
                    --$depthBracket;
                } elseif ('{' === $t || (is_array($t) && (T_CURLY_OPEN === $t[0] || T_DOLLAR_OPEN_CURLY_BRACES === $t[0]))) {
                    ++$depthBrace;
                } elseif ('}' === $t) {
                    --$depthBrace;
                }
            }

            return array_slice($tokens, $start, $count - $start);
        }

        if ('[' === $open) {
            $depthBracket = 1;
            ++$i;
            for (; $i < $count; $i++) {
                $t = $tokens[$i];
                if ('[' === $t) {
                    ++$depthBracket;
                } elseif (']' === $t) {
                    --$depthBracket;
                    if (0 === $depthBracket && 0 === $depthParen && 0 === $depthBrace) {
                        return array_slice($tokens, $start, $i - $start + 1);
                    }
                } elseif ('(' === $t) {
                    ++$depthParen;
                } elseif (')' === $t) {
                    --$depthParen;
                } elseif ('{' === $t || (is_array($t) && (T_CURLY_OPEN === $t[0] || T_DOLLAR_OPEN_CURLY_BRACES === $t[0]))) {
                    ++$depthBrace;
                } elseif ('}' === $t) {
                    --$depthBrace;
                }
            }
        }

        return array_slice($tokens, $start, 1);
    }

    /**
     * True when the first argument of a $wpdb write names the clusters table
     * (or is $this->table_name inside a class-cluster* repository file).
     *
     * @param list<string|array{0:int,1:string,2:int}> $argTokens
     */
    private function argumentTargetsClustersTable(array $argTokens, bool $fileIsClusterRepository): bool
    {
        $text = '';
        foreach ($argTokens as $t) {
            $text .= is_array($t) ? $t[1] : $t;
        }
        $text = preg_replace('/\s+/', '', $text) ?? $text;

        if (preg_match('/cluster/i', $text) === 1) {
            return true;
        }
        if (str_contains($text, 'acx_clusters')) {
            return true;
        }
        // class-cluster* repositories bind $this->table_name to acx_clusters.
        if ($fileIsClusterRepository && preg_match('/\$this->table_name\b/', $text) === 1) {
            return true;
        }

        return false;
    }

    private function sourceLabelIsClusterRepositoryFile(string $sourceLabel): bool
    {
        $base = basename(str_replace('\\', '/', $sourceLabel));

        return 1 === preg_match('/^class-cluster.*\.php$/', $base);
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
     * Every runtime file that writes the clusters table — corpus by table, not
     * by `class-cluster*` filename (R23-BR-29). class-cluster* repositories plus
     * the known non-repository writers that issue `$wpdb` updates against
     * `$table_clusters` / acx_clusters.
     *
     * @return list<string>
     */
    private function repositoryLayerFiles(): array
    {
        $root = dirname(__DIR__, 2);
        $repoDir = $root . '/src/sovereign/repositories';
        $globbed = glob($repoDir . '/class-cluster*.php');
        if (! is_array($globbed)) {
            $globbed = [];
        }

        // Non-repository clusters-table writers enumerated from $wpdb call sites
        // whose first argument is $table_clusters / acx_clusters. Tenant re-key
        // loops `$table` over a suffix list that includes acx_clusters but the
        // table argument is not statically clusters-shaped, so it is not listed
        // here — its only written column (`tenant_id`) is already covered by the
        // class-cluster* insert paths.
        $extra = [
            $root . '/src/support/class-life-cycle-manager.php',
            $root . '/src/api/services/class-cluster-label-service.php',
            $root . '/src/api/class-api.php',
        ];

        $files = [];
        foreach (array_merge($globbed, $extra) as $path) {
            if (is_string($path) && is_readable($path)) {
                $files[$path] = true;
            }
        }
        $files = array_keys($files);
        $this->assertNotEmpty($files, 'no clusters write-corpus source files found');
        sort($files);

        return $files;
    }

    /**
     * Concatenated source of the clusters write corpus (repository layer +
     * non-repository clusters-table writers), so column references survive the
     * REFA-2 split and the R23-BR-29 corpus widen.
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
