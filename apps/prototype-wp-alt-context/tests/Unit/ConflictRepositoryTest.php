<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Tests\TestCase;

class ConflictRepositoryTest extends TestCase
{
	public function testRecordConflictPersistsOpenConflictRow(): void
	{
		global $wpdb;

		$repository = new ConflictRepository();
		$result = $repository->record_conflict(
			[
				'id' => 17,
				'tenant_id' => 'tenant-test-123',
				'entity_type' => 'cluster',
				'entity_key' => 'cluster-7',
				'expected_base_version' => 21,
				'local_revision' => 4,
				'payload' => ['cluster_uuid' => 'cluster-7', 'person_uuid' => null],
			],
			[
				'conflict_code' => 'version_conflict',
				'backend_version' => 22,
				'machine_payload' => ['cluster_uuid' => 'cluster-7', 'person_uuid' => 'person-remote'],
			]
		);

		$this->assertSame(1, $result);

		$insertQuery = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_conflicts');
		$this->assertStringContainsString("'tenant-test-123'", $insertQuery);
		$this->assertStringContainsString("'version_conflict'", $insertQuery);
		$this->assertStringContainsString("'open'", $insertQuery);
	}

	/**
	 * @param array<int,string> $queries
	 */
	private function findQueryContaining(array $queries, string $needle): string
	{
		foreach ($queries as $query) {
			if (str_contains($query, $needle)) {
				return $query;
			}
		}

		$this->fail(sprintf('Unable to find query containing "%s".', $needle));
		return '';
	}
}
