<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\RosterEntryProjectionRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\RosterEntryProjectionRepository
 */
class RosterEntryProjectionRepositoryTest extends TestCase
{
	public function testListEntriesReportsStaleProjectionWhenNeverRefreshed(): void
	{
		$this->seedRosterRows();

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 13,
				lastUpdated: null,
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());

		$this->assertCount(2, $data);
		$this->assertSame('stale', $data[0]['projection_status']);
		$this->assertNull($data[0]['projection_refreshed_at']);
		$this->assertSame(13, $data[0]['source_version']);
		$this->assertSame(['friend'], $data[0]['tags']);
	}

	public function testListEntriesReportsFailedProjectionBeforePendingRefreshWork(): void
	{
		$this->seedRosterRows();

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 21,
				lastUpdated: '2026-05-07 16:00:00',
				lastSyncResult: 'failed',
				pendingCurationOperations: 2,
				pendingTopologyCommands: 1
			)
		);

		$data = $repository->list_entries(self::currentTenantId());

		$this->assertSame('failed', $data[0]['projection_status']);
		$this->assertSame('2026-05-07 16:00:00', $data[0]['projection_refreshed_at']);
		$this->assertSame(21, $data[0]['source_version']);
	}

	public function testListEntriesReportsRefreshingProjectionWhenPendingWorkExists(): void
	{
		$this->seedRosterRows();

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 34,
				lastUpdated: '2026-05-07 17:00:00',
				lastSyncResult: 'ok',
				pendingTopologyCommands: 1
			)
		);

		$data = $repository->list_entries(self::currentTenantId());

		$this->assertSame('refreshing', $data[0]['projection_status']);
		$this->assertSame('2026-05-07 17:00:00', $data[0]['projection_refreshed_at']);
		$this->assertSame(34, $data[0]['source_version']);
	}

	private function seedRosterRows(): void
	{
		global $wpdb;

		$wpdb->mockResults = [
			[
				'id' => 1,
				'person_uuid' => '11111111-1111-1111-1111-111111111111',
				'name' => 'Alice',
				'tags' => '["friend"]',
				'cluster_count' => 2,
				'updated_at' => '2026-05-07 14:00:00',
			],
			[
				'id' => 2,
				'person_uuid' => '22222222-2222-2222-2222-222222222222',
				'name' => 'Bob',
				'tags' => '[]',
				'cluster_count' => 0,
				'updated_at' => '2026-05-07 14:30:00',
			],
		];
	}
}

class RosterEntryProjectionSyncStateSpy extends NullSyncStateRepository
{
	public function __construct(
		private readonly int $snapshotVersion = 0,
		private readonly ?string $lastUpdated = null,
		private readonly string $lastSyncResult = 'ok',
		private readonly int $pendingCurationOperations = 0,
		private readonly int $pendingTopologyCommands = 0,
	) {
	}

	public function get_snapshot_version( string $tenant_id ): int {
		return $this->snapshotVersion;
	}

	public function get_last_updated( string $tenant_id ): ?string {
		return $this->lastUpdated;
	}

	public function get_last_sync_result( string $tenant_id ): string {
		return $this->lastSyncResult;
	}

	public function get_pending_curation_operations( string $tenant_id ): int {
		return $this->pendingCurationOperations;
	}

	public function get_pending_topology_commands( string $tenant_id ): int {
		return $this->pendingTopologyCommands;
	}
}