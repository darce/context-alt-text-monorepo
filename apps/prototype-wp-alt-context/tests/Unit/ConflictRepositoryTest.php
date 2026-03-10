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

	public function testRecordProjectionConflictUsesUpsertSemantics(): void
	{
		global $wpdb;

		$repository = new ConflictRepository();
		$result = $repository->record_projection_conflict(
			'tenant-projection',
			'member',
			'identity-88',
			'member_cluster_reassignment',
			54,
			33,
			9,
			['cluster_uuid' => 'cluster-remote'],
			['cluster_uuid' => 'cluster-local']
		);

		$this->assertSame(1, $result);

		$insertQuery = $this->findQueryContaining($wpdb->queries, 'INSERT INTO `wp_acx_sync_conflicts`');
		$this->assertStringContainsString("'tenant-projection'", $insertQuery);
		$this->assertStringContainsString("'member_cluster_reassignment'", $insertQuery);
		$this->assertStringContainsString('ON DUPLICATE KEY UPDATE', $insertQuery);
		$this->assertStringContainsString('machine_payload = VALUES(machine_payload)', $insertQuery);
		$this->assertStringContainsString('local_payload = VALUES(local_payload)', $insertQuery);
		$this->assertStringNotContainsString('resolution_status = VALUES(resolution_status)', $insertQuery);
	}

	public function testRecordProjectionConflictUpdatesExistingOpenConflictAcrossVersions(): void
	{
		global $wpdb;
		$wpdb->mockRow = [
			'id' => 7,
			'backend_version' => 54,
			'resolution_status' => 'open',
		];

		$repository = new ConflictRepository();
		$result = $repository->record_projection_conflict(
			'tenant-projection',
			'cluster',
			'cluster-7',
			'curated_cluster_deleted',
			55,
			33,
			9,
			['status' => 'missing_from_snapshot'],
			['label' => 'Curated']
		);

		$this->assertSame(7, $result);

		$updateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_conflicts SET');
		$this->assertStringContainsString("backend_version = 55", $updateQuery);
		$this->assertStringContainsString("WHERE id = 7", $updateQuery);
	}

	public function testRecordProjectionConflictRejectsMissingRequiredIdentifiers(): void
	{
		$repository = new ConflictRepository();

		$result = $repository->record_projection_conflict(
			'',
			'member',
			'identity-88',
			'member_cluster_reassignment',
			54,
			33,
			9,
			['cluster_uuid' => 'cluster-remote'],
			['cluster_uuid' => 'cluster-local']
		);

		$this->assertFalse($result);
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
	}
}
