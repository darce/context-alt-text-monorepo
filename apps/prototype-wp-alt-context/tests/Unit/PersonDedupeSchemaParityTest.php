<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * rg-005: acx_persons DDL carries normalized_name (utf8mb4_bin) + unique index;
 * legacy idx_name is retired in the same CREATE TABLE.
 *
 * @coversNothing
 */
class PersonDedupeSchemaParityTest extends TestCase
{
	public function testPersonsDdlHasNormalizedNameWithPinnedBinCollation(): void
	{
		$source = $this->lifecycleManagerSource();

		$this->assertMatchesRegularExpression(
			'/normalized_name\s+varchar\(255\)\s+CHARACTER SET utf8mb4\s+COLLATE utf8mb4_bin\s+NOT NULL/',
			$source
		);
		$this->assertMatchesRegularExpression(
			'/UNIQUE KEY idx_normalized_name\s*\(\s*normalized_name\s*\)/',
			$source
		);
	}

	public function testPersonsDdlRetiresIdxName(): void
	{
		$source = $this->lifecycleManagerSource();

		$this->assertDoesNotMatchRegularExpression(
			'/UNIQUE KEY idx_name\s*\(\s*name\s*\)/',
			$source
		);
		// No residual idx_name token in the persons CREATE TABLE block.
		$this->assertStringNotContainsString('idx_name', $this->personsSqlBlock($source));
	}

	public function testPersonsDdlKeepsPersonUuidUnique(): void
	{
		$source = $this->lifecycleManagerSource();

		$this->assertMatchesRegularExpression(
			'/UNIQUE KEY idx_person_uuid\s*\(\s*person_uuid\s*\)/',
			$this->personsSqlBlock($source)
		);
	}

	private function lifecycleManagerSource(): string
	{
		$source = file_get_contents(
			dirname(__DIR__, 2) . '/src/support/class-life-cycle-manager.php'
		);
		$this->assertIsString($source);

		return $source;
	}

	private function personsSqlBlock(string $source): string
	{
		$start = strpos($source, '$persons_sql');
		$end = strpos($source, '$clusters_sql');
		$this->assertNotFalse($start);
		$this->assertNotFalse($end);
		$this->assertGreaterThan($start, $end);

		return substr($source, $start, $end - $start);
	}
}
