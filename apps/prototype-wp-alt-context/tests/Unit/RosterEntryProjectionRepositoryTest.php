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

	public function testListEntriesIncludesProjectedClustersAndInstances(): void
	{
		global $wpdb;

		$wpdb->tableRows['wp_acx_persons'] = [
			[
				'id' => 1,
				'person_uuid' => '11111111-1111-1111-1111-111111111111',
				'name' => 'Alice',
				'tags' => '["friend"]',
				'updated_at' => '2026-05-07 14:00:00',
			],
		];
		$wpdb->tableRows['wp_acx_clusters'] = [
			[
				'cluster_uuid' => 'cluster-1',
				'person_id' => 1,
				'identity_count' => 2,
				'representative_id' => 'identity-1',
				'updated_at' => '2026-05-07 14:30:00',
			],
		];
		$wpdb->tableRows['wp_acx_identity_members'] = [
			[
				'identity_uuid' => 'identity-1',
				'cluster_uuid' => 'cluster-1',
				'attachment_id' => 101,
				'bbox_json' => '[0, 0, 10, 10]',
				'thumb_path' => 'http://example.test/101.jpg',
				'similarity' => '0.98',
				'updated_at' => '2026-05-07 14:31:00',
			],
			[
				'identity_uuid' => 'identity-2',
				'cluster_uuid' => 'cluster-1',
				'attachment_id' => 102,
				'bbox_json' => '[5, 5, 12, 12]',
				'thumb_path' => 'http://example.test/102.jpg',
				'similarity' => '0.84',
				'updated_at' => '2026-05-07 14:32:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 55,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());

		$this->assertCount(1, $data);
		$this->assertSame(1, $data[0]['cluster_count']);
		$this->assertCount(1, $data[0]['clusters']);
		$this->assertSame('cluster-1', $data[0]['clusters'][0]['cluster_id']);
		$this->assertCount(2, $data[0]['clusters'][0]['instances']);
		$this->assertSame('identity-1', $data[0]['clusters'][0]['representative_identity']['identity_id']);
	}

	public function testListEntriesRewritesBlobThumbPathWhenAttachmentUrlMissing(): void
	{
		global $wpdb;

		$wpdb->tableRows['wp_acx_persons'] = [
			[
				'id' => 1,
				'person_uuid' => '11111111-1111-1111-1111-111111111111',
				'name' => 'Alice',
				'tags' => '[]',
				'updated_at' => '2026-05-07 14:00:00',
			],
		];
		$wpdb->tableRows['wp_acx_clusters'] = [
			[
				'cluster_uuid' => 'cluster-1',
				'person_id' => 1,
				'identity_count' => 1,
				'representative_id' => 'identity-1',
				'updated_at' => '2026-05-07 14:30:00',
			],
		];
		$wpdb->tableRows['wp_acx_identity_members'] = [
			[
				'identity_uuid' => 'identity-1',
				'cluster_uuid' => 'cluster-1',
				'attachment_id' => 6731,
				'bbox_json' => '[0, 0, 10, 10]',
				'thumb_path' => 'file:///private/tmp/acx-recognition-blobs/tenant-x/job-y/6731.bin',
				'similarity' => '0.98',
				'updated_at' => '2026-05-07 14:31:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 55,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());
		$parts = \parse_url($data[0]['clusters'][0]['instances'][0]['media_url']);

		$this->assertSame('/wp-json/acx/v1/recognition/blobs/job-y/6731', $parts['path']);
	}

	public function testListEntriesIncludesOptionalSimilarityThresholdWhenProjected(): void
	{
		global $wpdb;

		$wpdb->tableRows['wp_acx_persons'] = [
			[
				'id' => 1,
				'person_uuid' => '11111111-1111-1111-1111-111111111111',
				'name' => 'Alice',
				'tags' => '["friend"]',
				'updated_at' => '2026-05-07 14:00:00',
			],
		];
		$wpdb->tableRows['wp_acx_clusters'] = [
			[
				'cluster_uuid' => 'cluster-1',
				'person_id' => 1,
				'identity_count' => 1,
				'representative_id' => 'identity-1',
				'updated_at' => '2026-05-07 14:30:00',
			],
		];
		$wpdb->tableRows['wp_acx_identity_members'] = [
			[
				'identity_uuid' => 'identity-1',
				'cluster_uuid' => 'cluster-1',
				'attachment_id' => 101,
				'bbox_json' => '[0, 0, 10, 10]',
				'thumb_path' => 'http://example.test/101.jpg',
				'similarity' => '0.98',
				'similarity_threshold' => '0.85',
				'updated_at' => '2026-05-07 14:31:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 55,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());

		$this->assertSame(0.85, $data[0]['clusters'][0]['representative_identity']['similarity_threshold']);
		$this->assertSame(0.85, $data[0]['clusters'][0]['instances'][0]['similarity_threshold']);
	}

	public function testListEntriesBatchesProjectionQueriesAndIncludesQueueMemberships(): void
	{
		global $wpdb;

		$wpdb->tableRows['wp_acx_persons'] = [
			[
				'id' => 1,
				'person_uuid' => '11111111-1111-1111-1111-111111111111',
				'name' => 'Alice',
				'tags' => '["friend"]',
				'queue_memberships_json' => '["hard-examples","needs-confirmation-after-merge"]',
				'updated_at' => '2026-05-07 14:00:00',
			],
			[
				'id' => 2,
				'person_uuid' => '22222222-2222-2222-2222-222222222222',
				'name' => 'Bob',
				'tags' => '[]',
				'updated_at' => '2026-05-07 14:30:00',
			],
		];
		$wpdb->tableRows['wp_acx_clusters'] = [
			[
				'cluster_uuid' => 'cluster-a',
				'person_id' => 1,
				'identity_count' => 1,
				'representative_id' => 'identity-a',
				'updated_at' => '2026-05-07 14:10:00',
			],
			[
				'cluster_uuid' => 'cluster-b',
				'person_id' => 2,
				'identity_count' => 1,
				'representative_id' => 'identity-b',
				'updated_at' => '2026-05-07 14:20:00',
			],
		];
		$wpdb->tableRows['wp_acx_identity_members'] = [
			[
				'identity_uuid' => 'identity-a',
				'cluster_uuid' => 'cluster-a',
				'attachment_id' => 201,
				'bbox_json' => '[0, 0, 10, 10]',
				'thumb_path' => 'http://example.test/201.jpg',
				'similarity' => '0.91',
				'updated_at' => '2026-05-07 14:11:00',
			],
			[
				'identity_uuid' => 'identity-b',
				'cluster_uuid' => 'cluster-b',
				'attachment_id' => 202,
				'bbox_json' => '[1, 1, 12, 12]',
				'thumb_path' => 'http://example.test/202.jpg',
				'similarity' => '0.88',
				'updated_at' => '2026-05-07 14:21:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 89,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());
		$selectQueries = array_values(
			array_filter(
				$wpdb->queries,
				static fn (string $sql): bool => str_starts_with($sql, 'SELECT')
			)
		);

		$this->assertCount(2, $data);
		$this->assertSame(['hard-examples', 'needs-confirmation-after-merge'], $data[0]['queue_memberships']);
		$this->assertSame([], $data[1]['queue_memberships']);
		$this->assertCount(3, $selectQueries);
		$this->assertStringContainsString('person_id IN (1, 2)', $selectQueries[1]);
		$this->assertStringContainsString('cluster_uuid IN (', $selectQueries[2]);
		$this->assertStringContainsString("'cluster-a'", $selectQueries[2]);
		$this->assertStringContainsString("'cluster-b'", $selectQueries[2]);
	}

	private function seedRosterRows(): void
	{
		global $wpdb;

		$wpdb->tableRows['wp_acx_persons'] = [
			[
				'id' => 1,
				'person_uuid' => '11111111-1111-1111-1111-111111111111',
				'name' => 'Alice',
				'tags' => '["friend"]',
				'updated_at' => '2026-05-07 14:00:00',
			],
			[
				'id' => 2,
				'person_uuid' => '22222222-2222-2222-2222-222222222222',
				'name' => 'Bob',
				'tags' => '[]',
				'updated_at' => '2026-05-07 14:30:00',
			],
		];
		$wpdb->tableRows['wp_acx_clusters'] = [
			[
				'cluster_uuid' => 'cluster-a',
				'person_id' => 1,
				'identity_count' => 1,
				'representative_id' => 'identity-a',
				'updated_at' => '2026-05-07 14:10:00',
			],
			[
				'cluster_uuid' => 'cluster-b',
				'person_id' => 1,
				'identity_count' => 1,
				'representative_id' => 'identity-b',
				'updated_at' => '2026-05-07 14:20:00',
			],
		];
		$wpdb->tableRows['wp_acx_identity_members'] = [
			[
				'identity_uuid' => 'identity-a',
				'cluster_uuid' => 'cluster-a',
				'attachment_id' => 201,
				'bbox_json' => '[0, 0, 10, 10]',
				'thumb_path' => 'http://example.test/201.jpg',
				'similarity' => '0.91',
				'updated_at' => '2026-05-07 14:11:00',
			],
			[
				'identity_uuid' => 'identity-b',
				'cluster_uuid' => 'cluster-b',
				'attachment_id' => 202,
				'bbox_json' => '[1, 1, 12, 12]',
				'thumb_path' => 'http://example.test/202.jpg',
				'similarity' => '0.88',
				'updated_at' => '2026-05-07 14:21:00',
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
