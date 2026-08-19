<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;

/**
 * rg-005: acx_persons DDL carries normalized_name (utf8mb4_bin) + unique index;
 * legacy idx_name is retired in the same CREATE TABLE.
 *
 * Asserts structure from the CREATE TABLE that actually reaches the stubbed
 * dbDelta path (not source-file regex alone), so a comment/string reshuffle
 * cannot green-wash the gate.
 *
 * @coversNothing
 */
class PersonDedupeSchemaParityTest extends TestCase
{
	public function testPersonsDdlHasNormalizedNameWithPinnedBinCollation(): void
	{
		$personsSql = $this->personsCreateTableFromDbDelta();
		$structure  = $this->parseCreateTable($personsSql);

		$this->assertArrayHasKey('normalized_name', $structure['columns']);
		$columnDef = $structure['columns']['normalized_name'];
		$this->assertMatchesRegularExpression('/varchar\s*\(\s*255\s*\)/i', $columnDef);
		$this->assertMatchesRegularExpression('/CHARACTER\s+SET\s+utf8mb4/i', $columnDef);
		$this->assertMatchesRegularExpression('/COLLATE\s+utf8mb4_bin/i', $columnDef);
		$this->assertMatchesRegularExpression('/NOT\s+NULL/i', $columnDef);
	}

	public function testPersonsDdlHasUniqueIndexOnNormalizedName(): void
	{
		$personsSql = $this->personsCreateTableFromDbDelta();
		$structure  = $this->parseCreateTable($personsSql);

		$this->assertArrayHasKey('idx_normalized_name', $structure['unique_keys']);
		// Stronger than the prior single-column pin: that assertion encoded the
		// defect (a global unique on normalized_name, which locks a name to the
		// first tenant). Uniqueness is tenant-scoped, matching uq_projection_conflict.
		$this->assertSame(
			['tenant_id', 'normalized_name'],
			$structure['unique_keys']['idx_normalized_name'],
			'UNIQUE KEY idx_normalized_name must be composite (tenant_id, normalized_name)'
		);
	}

	public function testPersonsDdlRetiresIdxName(): void
	{
		$personsSql = $this->personsCreateTableFromDbDelta();
		$structure  = $this->parseCreateTable($personsSql);

		$this->assertArrayNotHasKey('idx_name', $structure['unique_keys']);
		$this->assertArrayNotHasKey('idx_name', $structure['keys']);
		// Residual token guard: no idx_name anywhere in the executed CREATE TABLE.
		$this->assertStringNotContainsString('idx_name', $personsSql);
	}

	public function testPersonsDdlKeepsPersonUuidUnique(): void
	{
		$personsSql = $this->personsCreateTableFromDbDelta();
		$structure  = $this->parseCreateTable($personsSql);

		$this->assertArrayHasKey('idx_person_uuid', $structure['unique_keys']);
		$this->assertSame(['person_uuid'], $structure['unique_keys']['idx_person_uuid']);
	}

	/**
	 * Run activate → capture the CREATE TABLE that the stubbed dbDelta path received.
	 */
	private function personsCreateTableFromDbDelta(): string
	{
		$GLOBALS['__ac_dbdelta_queries'] = [];
		(new LifecycleManager())->activate();

		$queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
		$this->assertIsArray($queries);
		$this->assertNotEmpty($queries, 'activate must invoke dbDelta with CREATE TABLE SQL');

		foreach ($queries as $sql) {
			if (!is_string($sql)) {
				continue;
			}
			if (preg_match('/CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?wp_acx_persons`?/i', $sql) === 1) {
				return $sql;
			}
		}

		$this->fail('dbDelta path did not receive CREATE TABLE for wp_acx_persons');
		return '';
	}

	/**
	 * Lightweight DDL structure parse for CREATE TABLE bodies.
	 *
	 * @return array{
	 *   columns: array<string,string>,
	 *   unique_keys: array<string,list<string>>,
	 *   keys: array<string,list<string>>
	 * }
	 */
	private function parseCreateTable(string $sql): array
	{
		$open = strpos($sql, '(');
		$close = strrpos($sql, ')');
		$this->assertNotFalse($open, 'CREATE TABLE must have an opening paren');
		$this->assertNotFalse($close, 'CREATE TABLE must have a closing paren');
		$this->assertGreaterThan($open, $close);

		$body = substr($sql, $open + 1, $close - $open - 1);
		// Split on commas that separate column/key clauses (line-oriented DDL from LifecycleManager).
		$parts = preg_split('/,\s*(?=\n|\r|PRIMARY\s+KEY|UNIQUE\s+KEY|KEY\s+|INDEX\s+)/i', $body);
		$this->assertIsArray($parts);

		$columns = [];
		$uniqueKeys = [];
		$keys = [];

		foreach ($parts as $part) {
			$clause = trim($part);
			if ($clause === '') {
				continue;
			}

			if (preg_match('/^UNIQUE\s+KEY\s+`?(\w+)`?\s*\((.+)\)/is', $clause, $m) === 1) {
				$uniqueKeys[$m[1]] = $this->parseIndexColumns($m[2]);
				continue;
			}

			if (preg_match('/^(?:KEY|INDEX)\s+`?(\w+)`?\s*\((.+)\)/is', $clause, $m) === 1) {
				$keys[$m[1]] = $this->parseIndexColumns($m[2]);
				continue;
			}

			if (preg_match('/^PRIMARY\s+KEY\b/i', $clause) === 1) {
				continue;
			}

			if (preg_match('/^`?(\w+)`?\s+(.+)$/s', $clause, $m) === 1) {
				$columns[$m[1]] = trim($m[2]);
			}
		}

		return [
			'columns' => $columns,
			'unique_keys' => $uniqueKeys,
			'keys' => $keys,
		];
	}

	/**
	 * @return list<string>
	 */
	private function parseIndexColumns(string $columnList): array
	{
		$names = [];
		foreach (explode(',', $columnList) as $raw) {
			$name = trim($raw);
			$name = trim($name, " \t\n\r\0\x0B`");
			// Strip length suffix e.g. name(191).
			$name = preg_replace('/\s*\(\s*\d+\s*\)\s*$/', '', $name) ?? $name;
			if ($name !== '') {
				$names[] = $name;
			}
		}

		return $names;
	}
}
